"""LLM 调用监控：记录每一步的 token 消耗与耗时，同时输出到日志和前端。

用法：
    @monitor.track_step("大纲生成")
    def outlineEdit(state): ...

    monitor.attach(llm)   # 给 ChatDeepSeek 挂上用量回调
"""

import contextvars
import contextlib
import functools
import inspect
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "llm_usage.log"

logger = logging.getLogger("athor.usage")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s | %(message)s")
    _fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    logger.addHandler(_sh)
    logger.propagate = False

_current_step: contextvars.ContextVar = contextvars.ContextVar("athor_step", default=None)

_lock = threading.Lock()
_records = []
MAX_RECORDS = 300


class _Step:
    __slots__ = ("name", "prompt_tokens", "completion_tokens", "llm_calls")

    def __init__(self, name):
        self.name = name
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.llm_calls = 0


def _extract_usage(response):
    usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
    prompt = usage.get("prompt_tokens") or 0
    completion = usage.get("completion_tokens") or 0
    if not prompt and not completion:
        try:
            message = response.generations[0][0].message
            meta = getattr(message, "usage_metadata", None) or {}
            prompt = meta.get("input_tokens") or prompt
            completion = meta.get("output_tokens") or completion
        except Exception:
            pass
    return int(prompt), int(completion)


def _append_record(record):
    with _lock:
        _records.append(record)
        if len(_records) > MAX_RECORDS:
            del _records[: len(_records) - MAX_RECORDS]


def _finish(step, started):
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    total = step.prompt_tokens + step.completion_tokens
    record = {
        "name": step.name,
        "time": datetime.now().strftime("%H:%M:%S"),
        "duration_ms": duration_ms,
        "prompt_tokens": step.prompt_tokens,
        "completion_tokens": step.completion_tokens,
        "total_tokens": total,
        "llm_calls": step.llm_calls,
    }
    _append_record(record)
    logger.info(
        "步骤=%s | 用时 %.2fs | tokens=%d（输入 %d / 输出 %d）| LLM 调用 %d 次",
        step.name, duration_ms / 1000, total,
        step.prompt_tokens, step.completion_tokens, step.llm_calls,
    )


class UsageCallback(BaseCallbackHandler):
    """LangChain 回调：把每次 LLM 调用的 token 用量记到当前步骤"""

    def on_llm_end(self, response, **kwargs):
        prompt, completion = _extract_usage(response)
        step = _current_step.get()
        if step is not None:
            step.prompt_tokens += prompt
            step.completion_tokens += completion
            step.llm_calls += 1
            return
        # 没有归入任何步骤的调用，单独记录，避免用量丢失
        record = {
            "name": "未归组 LLM 调用",
            "time": datetime.now().strftime("%H:%M:%S"),
            "duration_ms": 0,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "llm_calls": 1,
        }
        _append_record(record)
        logger.info(
            "步骤=未归组 LLM 调用 | tokens=%d（输入 %d / 输出 %d）",
            prompt + completion, prompt, completion,
        )


def attach(llm):
    """给 LLM 实例挂上用量统计回调"""
    try:
        existing = list(getattr(llm, "callbacks", None) or [])
        llm.callbacks = existing + [UsageCallback()]
    except Exception as exc:  # 回调挂载失败不影响主流程
        logger.warning("挂载用量回调失败：%s", exc)
    return llm


def track_step(name):
    """装饰器：统计函数耗时与 token 消耗，支持同步、异步、异步生成器"""

    def decorator(func):
        if inspect.isasyncgenfunction(func):
            @functools.wraps(func)
            async def async_gen_wrapper(*args, **kwargs):
                step = _Step(name)
                token = _current_step.set(step)
                started = time.perf_counter()
                try:
                    async for item in func(*args, **kwargs):
                        yield item
                finally:
                    _current_step.reset(token)
                    _finish(step, started)
            return async_gen_wrapper

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                step = _Step(name)
                token = _current_step.set(step)
                started = time.perf_counter()
                try:
                    return await func(*args, **kwargs)
                finally:
                    _current_step.reset(token)
                    _finish(step, started)
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            step = _Step(name)
            token = _current_step.set(step)
            started = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                _current_step.reset(token)
                _finish(step, started)
        return sync_wrapper

    return decorator


@contextlib.contextmanager
def step(name):
    """上下文管理器：统计一段代码内所有 LLM 调用的耗时与 token"""
    current = _Step(name)
    token = _current_step.set(current)
    started = time.perf_counter()
    try:
        yield current
    finally:
        _current_step.reset(token)
        _finish(current, started)


def summary(limit=50):
    """返回累计用量与最近步骤，供前端展示"""
    with _lock:
        rows = list(_records)
    totals = {
        "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
        "completion_tokens": sum(r["completion_tokens"] for r in rows),
        "total_tokens": sum(r["total_tokens"] for r in rows),
        "llm_calls": sum(r["llm_calls"] for r in rows),
        "duration_ms": round(sum(r["duration_ms"] for r in rows), 1),
    }
    return {"totals": totals, "steps": list(reversed(rows[-limit:]))}
