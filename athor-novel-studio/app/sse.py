"""SSE 输出与阶段心跳的公共工具。"""

import asyncio
import json

from app.config import settings


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


async def stage_heartbeat(func, state, stage, holder):
    """在线程中执行耗时阶段，期间每 5 秒发送一次心跳，避免长时间无输出"""
    task = asyncio.create_task(asyncio.to_thread(func, state))
    while True:
        done, _ = await asyncio.wait({task}, timeout=5)
        if done:
            holder["result"] = task.result()
            return
        yield sse({"type": "heartbeat", "stage": stage})


async def stage_heartbeat_many(coro, stage, holder):
    """等待一个并发任务集合，期间每 5 秒发送一次心跳"""
    task = asyncio.create_task(coro)
    while True:
        done, _ = await asyncio.wait({task}, timeout=5)
        if done:
            holder["result"] = task.result()
            return
        yield sse({"type": "heartbeat", "stage": stage})


async def run_parallel(func, states, concurrency=None):
    """并发执行多个同构阶段，控制并发数，避免串行等待过久"""
    sem = asyncio.Semaphore(concurrency or settings.llm_concurrency)

    async def one(state):
        async with sem:
            return await asyncio.to_thread(func, state)

    return await asyncio.gather(*(one(s) for s in states))
