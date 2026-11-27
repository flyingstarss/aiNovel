import asyncio
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agents import humanizer, reviewer, session_store
from app.agents import writer as writer_agent
from app.schemas import (
    ChapterIdRequest,
    ChapterRequest,
    ShortChoiceRequest,
    ShortOptionsRequest,
)
from app.sse import sse, sse_headers

router = APIRouter()

WORD_MIN = 2000
WORD_MAX = 3000
MAX_REWRITES = 3
MAX_POLISH_ROUNDS = 3

# 网络抖动可重试的错误特征
RETRYABLE_MARKERS = (
    "connection error",
    "connection reset",
    "connection aborted",
    "connection refused",
    "remote end closed",
    "broken pipe",
    "eof occurred",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "502",
    "503",
    "504",
)


def _is_retryable(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    if "connection" in name or "timeout" in name:
        return True
    text = str(exc).lower()
    return any(m in text for m in RETRYABLE_MARKERS)


def _error_hint(exc: Exception) -> str:
    """把模型返回的英文错误码翻成可操作的中文提示，方便用户修复后断点续写"""
    text = str(exc)
    low = text.lower()
    if "insufficient balance" in low or "insufficient_balance" in low or "402" in low:
        return "API 账户余额不足（402）。充值或更换密钥后，点「续写本章」即可从断点继续"
    if "401" in low or "invalid api key" in low or "authentication" in low:
        return "API 密钥无效或已失效（401）。检查 .env 里的 DEEPSEEK_API_KEY 后点「续写本章」继续"
    if "429" in low or "rate limit" in low:
        return "请求被限流（429）。稍等一会儿点「续写本章」即可从断点继续"
    if "500" in low or "502" in low or "503" in low or "overloaded" in low:
        return "模型服务暂时不可用。稍后点「续写本章」即可从断点继续"
    if "connection" in low or "timed out" in low or "timeout" in low:
        return "连接中断。检查网络后点「续写本章」即可从断点继续"
    return f"写作中断：{text}"


CN_TOKEN = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9]")


def _char_overlap(a: str, b: str) -> float:
    sa = set(CN_TOKEN.findall(a or ""))
    sb = set(CN_TOKEN.findall(b or ""))
    if not sa:
        return 1.0
    return len(sa & sb) / len(sa)


def _keep_key_info(
    original: str, new: str, is_last: bool = False, names: list[str] | None = None
) -> tuple[bool, str]:
    """局部改写后的段落必须保留关键信息（人名、地名、数字与章末钩子）"""
    if not new:
        return False, "改写结果为空"
    if len(new) < max(4, len(original) * 0.45):
        return False, "改写后过短"
    if len(new) > max(20, len(original) * 2):
        return False, "改写后过度膨胀"
    # 一句一段的短段落本来就短，阈值按长度分级，避免误杀合规改写
    length = len(original)
    if length < 20:
        threshold = 0.0
    elif length < 40:
        threshold = 0.35
    elif length < 80:
        threshold = 0.5
    else:
        threshold = 0.7
    if is_last:
        # 章末钩子所在段落最保守，改写后必须保留大部分原用字
        threshold = max(threshold, 0.5)
    overlap = _char_overlap(original, new)
    if overlap < threshold:
        return False, f"与原段用字重合度仅 {overlap:.0%}"
    for num in re.findall(r"\d+", original):
        if num not in new:
            return False, f"丢失数字 {num}"
    if names is None:
        names = _key_entities(original)
    lost = [n for n in names if n in original and n not in new]
    if lost:
        return False, f"丢失人名或地名 {('、'.join(lost[:3]))}"
    return True, ""


# 含这些字的多半是虚词搭配，不当作实体词
FUNC_CHARS = set(
    "的了着过是在不没和与及或而但就都也还又很太更最把被给让使对从向于为以之其"
    "这那我你他她它们吗呢吧啊么个些一两点半声下上里外时后前中只几再才朝往"
)
# 常见动词用字：跨词切出来的动作片段不算实体
VERB_CHARS = set(
    "看说道走跑抓抬拉推扯站坐转伸落掉打举握压踢扑跳爬蹲低喊问叫笑点摇挥切割"
    "递接拿放捂按摸跪靠挪扫盯望皱咬牙吐喝吟念喘抖颤缩退迎挡拦扔砸劈砍刺挑撩"
    "扶拽拖攥捏搓揉拍敲捅插拔拧喝戴拽扶靠"
)
ENTITY_STOP = {
    "忍不住", "突然", "终于", "似乎", "仿佛", "好像", "一样", "时候", "什么",
    "怎么", "这样", "那样", "一下", "一声", "一边", "一直", "已经", "还是",
    "就是", "没有", "起来", "出来", "过来", "下来", "上去", "回去", "说道",
    "问道", "喊道", "声音", "东西", "地方", "眼睛", "手里", "心里", "身上",
    "这种", "那种", "只是", "立刻", "马上", "仍然", "几乎", "显然", "毕竟",
    "其实", "甚至", "可是", "于是", "然后", "因为", "什么", "不知", "仿佛",
}
BOUNDARY_CHARS = "。！？，；：“”‘’\n"


def _token_stats(text: str) -> list[tuple[str, int, int]]:
    """统计 2-3 字候选词的出现次数与句首次数，用于筛出高置信度实体"""
    counts: dict[str, int] = {}
    starts: dict[str, int] = {}
    for size in (2, 3):
        for i in range(len(text) - size + 1):
            token = text[i:i + size]
            if not all("\u4e00" <= c <= "\u9fa5" for c in token):
                continue
            counts[token] = counts.get(token, 0) + 1
            if i == 0 or text[i - 1] in BOUNDARY_CHARS:
                starts[token] = starts.get(token, 0) + 1
    picked = []
    for token, count in counts.items():
        if count < 3 or token in ENTITY_STOP:
            continue
        if any(c in FUNC_CHARS or c in VERB_CHARS for c in token):
            continue
        picked.append((token, count, starts.get(token, 0)))
    picked.sort(key=lambda item: (-item[1], -len(item[0])))
    return picked[:30]


def _text_entities(text: str) -> list[str]:
    """从正文提取高置信度实体：高频且多次出现在句首，避免把人名误判成动作片段"""
    return [
        token for token, count, starts in _token_stats(text)
        if starts >= 3
    ][:20]


def _key_entities(text: str) -> list[str]:
    """提取原文中已出现的人物、地点与关键实体，用于改写与润色后的回检"""
    body = text or ""
    names: list[str] = []
    for sql in ("SELECT name FROM person", "SELECT name FROM story_map"):
        try:
            rows = writer_agent._fetch_all(sql) or []
        except Exception:
            rows = []
        for row in rows:
            name = (row.get("name") or "").strip()
            if len(name) >= 2 and name in body and name not in names:
                names.append(name)
    for token in _text_entities(body):
        if token not in names:
            names.append(token)
    return names


def _fix_paragraph(
    call, original: str, issue_text: str, names: list[str], is_last: bool
) -> tuple[str | None, str]:
    """改写/润色单个段落并校验；问题没减少时带着残留问题再试一次"""
    hint = issue_text
    before = len(writer_agent.line_issues(original))
    for _ in range(2):
        try:
            new = call(original, hint)
        except Exception as exc:
            return None, f"改写失败：{exc}"
        new = (new or "").strip().strip("“”\"")
        ok, why = _keep_key_info(original, new, is_last, names)
        if not ok:
            return None, why
        after = len(writer_agent.line_issues(new))
        if after < before or (before == 0 and after == 0):
            return new, ""
        residual = writer_agent.line_issues(new)
        hint = (
            issue_text
            + "\n上一稿仍存在这些问题，必须彻底删掉："
            + "；".join(residual)
        )
    return None, "问题未减少"


def _rewrite_targets(text: str, targets: list, reasons: str) -> tuple[str, list[str]]:
    """只重写命中的段落，其余段落原样保留"""
    lines = (text or "").split("\n")
    last_idx = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
    names = _key_entities(text)
    notes = []
    for item in targets[:6]:
        idx = item["index"]
        if idx >= len(lines):
            continue
        old = lines[idx]
        issue_text = "；".join(item["issues"]) + "\n" + reasons
        new, why = _fix_paragraph(
            writer_agent.rewriteParagraph,
            old,
            issue_text,
            names,
            idx == last_idx,
        )
        if new is None:
            notes.append(f"第 {idx + 1} 段{why}，已保留原段")
            continue
        lines[idx] = new
    return "\n".join(lines), notes


# 审核意见的两种文本格式：`类别｜严重｜片段｜改法` 与 `【类别·严重】片段 → 改法`
ISSUE_LINE = re.compile(r"^(.+?)[｜|](严重|轻微)[｜|](.+?)[｜|](.+)$")
ISSUE_BRACKET = re.compile(r"【(.+?)[·・|｜](严重|轻微)】\s*(.+?)\s*(?:→|->|—>)\s*(.+)$")


def _parse_issue_lines(issues) -> list[tuple[str, str, str, str]]:
    """把审核意见统一成（类别, 严重程度, 原文片段, 修改方向）四元组"""
    items: list[tuple[str, str, str, str]] = []
    if isinstance(issues, str):
        for raw in issues.splitlines():
            line = raw.strip().lstrip("-• ").strip()
            line = re.sub(r"^\d+[.、]\s*", "", line)
            m = ISSUE_BRACKET.match(line) or ISSUE_LINE.match(line)
            if m:
                items.append((m.group(1).strip(), m.group(2), m.group(3).strip(), m.group(4).strip()))
        return items
    for it in issues or []:
        category = str(it.get("category") or "").strip()
        evidence = str(it.get("evidence") or "").strip()
        if not category or not evidence:
            continue
        items.append((
            category,
            str(it.get("severity") or "轻微"),
            evidence,
            str(it.get("fix") or it.get("suggestion") or "").strip(),
        ))
    return items


def _targets_from_issues(text: str, issues) -> list[dict]:
    """从审核意见里取出原文片段，定位到命中段落，供局部改写/润色"""
    lines = (text or "").split("\n")
    found: dict[int, list[str]] = {}

    def bind(index: int, note: str) -> None:
        bucket = found.setdefault(index, [])
        if note not in bucket:
            bucket.append(note)

    for category, severity, evidence, fix in _parse_issue_lines(issues):
        frag = evidence.strip().strip("“”\"'…")
        note = f"{category}（{severity}）：{fix or '按文风规范改写'}"
        if len(frag) < 4:
            continue
        for index, line in enumerate(lines):
            if frag in line:
                bind(index, note)
                break
        else:
            # 片段被模型缩写或截断时，退化为前 8 个字的关键词匹配
            key = frag[:8]
            if len(key) >= 6:
                for index, line in enumerate(lines):
                    if key in line:
                        bind(index, note)
                        break
    return [
        {"index": i, "text": lines[i], "issues": found[i]}
        for i in sorted(found)
    ]


def _merge_targets(*groups: list[dict]) -> list[dict]:
    """合并确定性命中与审核意见定位，同一段落的问题合并处理"""
    merged: dict[int, dict] = {}
    for group in groups:
        for item in group or []:
            bucket = merged.get(item["index"])
            if bucket is None:
                merged[item["index"]] = {
                    "index": item["index"],
                    "text": item["text"],
                    "issues": list(item["issues"]),
                }
            else:
                for issue in item["issues"]:
                    if issue not in bucket["issues"]:
                        bucket["issues"].append(issue)
    return [merged[i] for i in sorted(merged)]


def _polish_targets(text: str, targets: list) -> tuple[str, list[str]]:
    """只润色命中的段落，其余段落原样保留"""
    lines = (text or "").split("\n")
    last_idx = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
    names = _key_entities(text)
    notes = []
    for item in targets[:8]:
        idx = item["index"]
        if idx >= len(lines):
            continue
        old = lines[idx]
        new, why = _fix_paragraph(
            humanizer.polishParagraph,
            old,
            "；".join(item["issues"]),
            names,
            idx == last_idx,
        )
        if new is None:
            notes.append(f"第 {idx + 1} 段润色{why}，已保留原段")
            continue
        lines[idx] = new
    return "\n".join(lines), notes


def _chapter_text(novel_chapter_id) -> str:
    row = writer_agent._fetch_one(
        "SELECT content FROM novel_chapter WHERE id = %s", (novel_chapter_id,)
    )
    return (row or {}).get("content") or ""


def _audit_issues(audit: dict) -> str:
    """把违规与一致性审核结果压缩成给写手的修改意见"""
    parts = []
    violation = audit.get("violation") or {}
    if not violation.get("passed", True):
        if violation.get("issues"):
            parts.append(f"违规问题：{violation['issues']}")
        if violation.get("suggestion"):
            parts.append(f"违规修改建议：{violation['suggestion']}")
    consistency = audit.get("consistency") or {}
    if not consistency.get("passed", True):
        if consistency.get("issues"):
            parts.append(f"细纲/人物问题：{consistency['issues']}")
        if consistency.get("suggestion"):
            parts.append(f"修改建议：{consistency['suggestion']}")
    return "\n".join(parts)


def _is_better(new: dict | None, old: dict | None) -> bool:
    """比较两版 AI 味审核结果：优先不看一票否决，再看分数高低"""
    if new is None:
        return False
    if old is None:
        return True
    if bool(new.get("vetoed")) != bool(old.get("vetoed")):
        return not new.get("vetoed")
    return (new.get("score") or 0) > (old.get("score") or 0)


@router.get("/api/chapter/next")
def chapter_next(outline_id: int | None = None):
    draft = writer_agent._draft_chapter_row(outline_id=outline_id)
    if draft:
        return {
            "has_next": True,
            "mode": "draft",
            "chapter_outline_id": draft["id"],
            "chapter_no": draft.get("chapter_no"),
            "title": draft.get("title"),
            "volume_no": draft.get("volume_no"),
            "volume_title": draft.get("volume_title"),
            "target_words": draft.get("target_words"),
            "draft_content": draft.get("draft_content") or "",
            "draft_words": draft.get("draft_words") or 0,
            "segment": writer_agent.segment_payload(draft),
        }

    row = writer_agent._next_chapter_row(outline_id=outline_id)
    if not row:
        return {"has_next": False}
    return {
        "has_next": True,
        "mode": "new",
        "chapter_outline_id": row["id"],
        "chapter_no": row.get("chapter_no"),
        "title": row.get("title"),
        "volume_no": row.get("volume_no"),
        "volume_title": row.get("volume_title"),
        "target_words": row.get("target_words"),
        "segment": writer_agent.segment_payload(row),
    }


@router.post("/api/short/options")
def short_options(req: ShortOptionsRequest):
    """为一段（3 章）生成 3 个互斥的发展走向，供作者选择或交给模型自行处理"""
    try:
        options = writer_agent.generate_short_options(
            req.short_id, force=req.force, note=req.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"短纲走向生成失败：{exc}")
    return {"short_id": req.short_id, "options": options}


@router.post("/api/short/choice")
def short_choice(req: ShortChoiceRequest):
    """记录本段走向：choice_no 为 1-3 选具体走向，为空表示交给模型自行处理"""
    try:
        return writer_agent.set_short_choice(req.short_id, req.choice_no, note=req.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"短纲走向保存失败：{exc}")


@router.post("/api/chapter/stream")
async def chapter_stream(req: ChapterRequest):
    if req.session_id:
        if req.rewrite:
            action = "按审核意见重写本章"
        elif req.resume:
            action = "继续续写本章草稿"
        else:
            action = "开始写下一章"
        if req.scene_choice:
            action += f"，采用走向：{req.scene_choice}"
        await asyncio.to_thread(
            session_store.add_message, req.session_id, "user", action
        )

    async def gen():
        issues = (
            req.content_issues or (req.audit_issues if req.rewrite else "")
        ).strip()
        resume = req.resume
        chapter_outline_id = (
            req.chapter_outline_id if (req.rewrite or req.resume) else None
        )
        final_event = None
        final_ok = True
        rewrites = 0
        last_reasons = []
        existing_text = ""

        # 只有 AI 味不通过：不重写正文，直接交给润色 agent
        ai_only = bool(
            req.rewrite and req.novel_chapter_id and req.ai_issues.strip()
            and not issues
        )
        if ai_only:
            existing_text = await asyncio.to_thread(
                _chapter_text, req.novel_chapter_id
            )
            if not existing_text:
                yield sse({"type": "error", "message": "该章暂无正文，无法润色"})
                return
            row = await asyncio.to_thread(
                writer_agent._fetch_one,
                "SELECT id, title, chapter_no, chapter_outline_id, word_count "
                "FROM novel_chapter WHERE id = %s",
                (req.novel_chapter_id,),
            )
            final_event = {
                "type": "done",
                "novel_chapter_id": req.novel_chapter_id,
                "chapter_outline_id": (row or {}).get("chapter_outline_id"),
                "chapter_no": (row or {}).get("chapter_no"),
                "title": (row or {}).get("title"),
                "word_count": (row or {}).get("word_count")
                or len(re.sub(r"\s+", "", existing_text)),
            }
            yield sse({
                "type": "stage",
                "message": "检测到仅 AI 味未通过，跳过重写，交给润色 agent 按意见润色…",
            })

        while not ai_only:
            outline_id = req.outline_id
            if not outline_id and req.session_id:
                sess = await asyncio.to_thread(
                    session_store.get_session, req.session_id
                )
                if sess:
                    outline_id = sess.get("outline_id")
            if not chapter_outline_id and not resume and not outline_id:
                yield sse({
                    "type": "error",
                    "message": "当前会话还没有自己的大纲，请先生成并审核大纲",
                })
                return
            state = {
                "chapter_outline_id": chapter_outline_id,
                "outline_id": outline_id,
                "audit_issues": issues,
                "resume": resume,
                "scene_choice": req.scene_choice or "",
            }
            done_event = None
            stream_retries = 0
            while True:
                emitted = False
                try:
                    async for event in writer_agent.novelWriterStream(state):
                        if event.get("type") == "done":
                            done_event = event
                            continue
                        if event.get("type") == "delta" and event.get("text"):
                            emitted = True
                        yield sse(event)
                    break
                except Exception as exc:
                    # 尚未输出正文时遇到连接类错误，可安全地整段重试
                    if emitted or not _is_retryable(exc) or stream_retries >= 2:
                        payload = {"type": "error", "message": _error_hint(exc)}
                        draft = await asyncio.to_thread(
                            writer_agent._draft_chapter_row, outline_id
                        )
                        if draft:
                            payload.update({
                                "draft": True,
                                "chapter_outline_id": draft.get("id"),
                                "chapter_no": draft.get("chapter_no"),
                                "title": draft.get("title"),
                                "draft_words": draft.get("draft_words") or 0,
                            })
                        yield sse(payload)
                        return
                    stream_retries += 1
                    yield sse({
                        "type": "stage",
                        "message": f"模型连接中断（{exc}），正在自动重试第 {stream_retries} 次…",
                    })
                    await asyncio.sleep(2 * stream_retries)

            if not done_event:
                return
            final_event = done_event
            word_count = done_event.get("word_count") or 0

            # 生成一版后先尝试局部修复；无法定位问题段落时才整章重写
            while True:
                word_ok = WORD_MIN <= word_count <= WORD_MAX

                text_now = await asyncio.to_thread(
                    _chapter_text, done_event["novel_chapter_id"]
                )
                metaphor_hits = writer_agent.find_metaphor_hits(text_now)
                metaphor_ok = not metaphor_hits
                contrast_hits = writer_agent.find_contrast_hits(text_now)
                contrast_ok = not contrast_hits

                audit = None
                try:
                    audit = await asyncio.to_thread(
                        reviewer.chapterAudit,
                        {"novel_chapter_id": done_event["novel_chapter_id"]},
                    )
                except Exception as exc:
                    yield sse({"type": "warning", "message": f"审核失败，已跳过自动重写：{exc}"})
                audit_passed = True if audit is None else bool(audit.get("passed"))
                yield sse({
                    "type": "audit",
                    "passed": audit_passed,
                    "word_ok": word_ok,
                    "word_count": word_count,
                    "metaphor_ok": metaphor_ok,
                    "metaphor_hits": metaphor_hits,
                    "contrast_ok": contrast_ok,
                    "contrast_hits": contrast_hits,
                    "issues": _audit_issues(audit) if audit else "",
                })

                reasons = []
                if not word_ok:
                    reasons.append(
                        f"本章 {word_count} 字，不在 {WORD_MIN}-{WORD_MAX} 字区间内。"
                    )
                if audit and not audit_passed:
                    reasons.append(_audit_issues(audit))
                if metaphor_hits:
                    reasons.append(
                        "以下句子使用了比喻，必须改写成直接的动作或状态："
                        + "；".join(metaphor_hits[:5])
                    )
                if contrast_hits:
                    reasons.append(
                        "以下句子用了「不是……，是……」的先否定再纠正句式，"
                        "必须直接写确定的那个事实："
                        + "；".join(contrast_hits[:5])
                    )

                if word_ok and audit_passed and metaphor_ok and contrast_ok:
                    break
                if rewrites >= MAX_REWRITES:
                    final_ok = False
                    last_reasons = reasons
                    break

                # 优先局部重写：确定性命中与审核意见片段都先定位到段落
                targets = _merge_targets(
                    writer_agent.locality_targets(text_now),
                    _targets_from_issues(text_now, "\n".join(reasons)),
                )
                if word_ok and targets:
                    rewrites += 1
                    yield sse({
                        "type": "stage",
                        "message": (
                            f"第 {rewrites} 次自动重写：定位到 {len(targets)} 处问题段落，"
                            "只重写这些段落，其余原样保留…"
                        ),
                    })
                    new_text, notes = await asyncio.to_thread(
                        _rewrite_targets, text_now, targets, "\n".join(reasons)
                    )
                    if notes:
                        yield sse({"type": "warning", "message": "；".join(notes)})
                    if new_text and new_text != text_now:
                        word_count = await asyncio.to_thread(
                            writer_agent.update_chapter_content,
                            done_event["novel_chapter_id"],
                            new_text,
                        )
                        yield sse({"type": "replace"})
                        yield sse({"type": "delta", "text": new_text})
                        continue

                rewrites += 1
                issues = "\n".join(reasons)
                chapter_outline_id = done_event["chapter_outline_id"]
                resume = False

                yield sse({"type": "replace"})
                yield sse({
                    "type": "stage",
                    "message": f"第 {rewrites} 次自动重写：字数或审核未通过，正在按意见重写整章…",
                })
                break

        # 去 AI 味：先审核原文，只把不通过的稿子交给润色 agent，并保留评分最高的一版
        flavor = None
        if final_ok and final_event:
            original = existing_text or await asyncio.to_thread(
                _chapter_text, final_event["novel_chapter_id"]
            )
            if original:
                baseline = None
                try:
                    baseline = await asyncio.to_thread(humanizer.audit, original)
                except Exception as exc:
                    yield sse({"type": "warning", "message": f"AI 味审核失败：{exc}"})

                if baseline:
                    yield sse({
                        "type": "flavor",
                        "score": baseline["score"],
                        "passed": baseline["passed"],
                        "borderline": baseline.get("borderline"),
                        "vetoed": baseline.get("vetoed"),
                        "threshold": baseline.get("threshold"),
                        "min_threshold": baseline.get("min_threshold"),
                        "rechecked": baseline.get("rechecked"),
                    })

                best_text, best_flavor = original, baseline
                style_hits = (
                    writer_agent.find_dialogue_tag_hits(original)
                    + writer_agent.find_style_hits(original)
                    + writer_agent.find_contrast_hits(original)
                )
                if baseline and baseline["passed"] and not style_hits:
                    yield sse({
                        "type": "stage",
                        "message": f"AI 味审核 {baseline['score']} 分，已通过，无需润色。",
                    })
                elif (
                    baseline
                    and baseline.get("borderline")
                    and not style_hits
                    and not (req.ai_issues or "").strip()
                ):
                    yield sse({
                        "type": "stage",
                        "message": (
                            f"原文 AI 味 {baseline['score']} 分，处于边界区间，"
                            "已保留；可人工接受或再润色一轮。"
                        ),
                    })
                else:
                    yield sse({
                        "type": "stage",
                        "message": "内容审核已通过，正在把 AI 味意见交给润色 agent…",
                    })
                    polish_issues = (req.ai_issues or "").strip() or (
                        baseline["issues"] if baseline else ""
                    )
                    if style_hits:
                        polish_issues = (
                            polish_issues
                            + "\n存在台词、文风或句式硬伤，必须逐句改写（说话动词用说道/问道/喊道，"
                            "删掉旁白判断，修正量词与拟人生硬；"
                            "「不是……，是……」这类先否定再纠正的句式要直接写确定的事实）："
                            + "；".join(style_hits[:5])
                        ).strip()
                    # 优先局部润色：只改命中的段落，未命中的段落原样保留
                    local_done = False
                    flavor_src = (baseline or {}).get("issue_list") or polish_issues
                    targets = _merge_targets(
                        writer_agent.locality_targets(best_text),
                        _targets_from_issues(best_text, flavor_src),
                    )
                    if targets:
                        local_done = True
                        for local_round in range(1, MAX_POLISH_ROUNDS + 1):
                            targets = _merge_targets(
                                writer_agent.locality_targets(best_text),
                                _targets_from_issues(best_text, polish_issues),
                            )
                            if not targets:
                                yield sse({
                                    "type": "stage",
                                    "message": "问题段落已全部处理，其余段落原样保留。",
                                })
                                break
                            yield sse({
                                "type": "stage",
                                "message": (
                                    f"定位到 {len(targets)} 处问题段落，"
                                    "只润色这些段落，其余原样保留…"
                                ),
                            })
                            candidate, notes = await asyncio.to_thread(
                                _polish_targets, best_text, targets
                            )
                            if notes:
                                yield sse({
                                    "type": "warning",
                                    "message": "；".join(notes),
                                })
                            if not candidate or candidate == best_text:
                                yield sse({
                                    "type": "stage",
                                    "message": "局部润色没有产生可用改动，已保留原稿。",
                                })
                                break

                            lost = [
                                n for n in _key_entities(best_text)
                                if n not in candidate
                            ]
                            if lost:
                                yield sse({
                                    "type": "warning",
                                    "message": (
                                        "局部润色丢失关键人物或地点："
                                        + "、".join(lost[:5])
                                        + "，已保留原稿。"
                                    ),
                                })
                                break

                            candidate_flavor = None
                            try:
                                candidate_flavor = await asyncio.to_thread(
                                    humanizer.audit, candidate
                                )
                            except Exception as exc:
                                yield sse({
                                    "type": "warning",
                                    "message": f"AI 味审核失败：{exc}",
                                })
                            yield sse({"type": "polish_start", "round": local_round})
                            yield sse({
                                "type": "polish_replace",
                                "content": candidate,
                            })
                            yield sse({
                                "type": "polish_done",
                                "round": local_round,
                                "passed": bool(
                                    candidate_flavor
                                    and candidate_flavor["passed"]
                                ),
                                "borderline": bool(
                                    candidate_flavor
                                    and candidate_flavor.get("borderline")
                                ),
                                "vetoed": bool(
                                    candidate_flavor
                                    and candidate_flavor.get("vetoed")
                                ),
                                "score": (
                                    candidate_flavor["score"]
                                    if candidate_flavor else None
                                ),
                                "threshold": humanizer.AI_FLAVOR_THRESHOLD,
                                "min_threshold": humanizer.MIN_THRESHOLD,
                            })
                            best_text = candidate
                            if candidate_flavor:
                                best_flavor = candidate_flavor
                                if candidate_flavor.get("issues"):
                                    polish_issues = candidate_flavor["issues"]
                            if candidate_flavor and candidate_flavor["passed"]:
                                break

                    for round_no in range(1, MAX_POLISH_ROUNDS + 1):
                        if local_done:
                            break
                        yield sse({"type": "polish_start", "round": round_no})
                        parts = []
                        try:
                            async for piece in humanizer.polishStream(
                                best_text, polish_issues
                            ):
                                parts.append(piece)
                                yield sse({"type": "polish_delta", "text": piece})
                        except Exception as exc:
                            yield sse({"type": "polish_replace", "content": best_text})
                            yield sse({
                                "type": "warning",
                                "message": f"去 AI 味润色失败，已保留当前稿：{exc}",
                            })
                            break

                        candidate = "".join(parts).strip()
                        if not candidate:
                            yield sse({"type": "polish_replace", "content": best_text})
                            yield sse({
                                "type": "warning",
                                "message": "润色结果为空，已保留当前稿。",
                            })
                            break

                        candidate_flavor = None
                        try:
                            candidate_flavor = await asyncio.to_thread(
                                humanizer.audit, candidate
                            )
                        except Exception as exc:
                            yield sse({
                                "type": "warning",
                                "message": f"AI 味审核失败：{exc}",
                            })

                        yield sse({
                            "type": "polish_done",
                            "round": round_no,
                            "passed": bool(
                                candidate_flavor and candidate_flavor["passed"]
                            ),
                            "borderline": bool(
                                candidate_flavor and candidate_flavor.get("borderline")
                            ),
                            "vetoed": bool(
                                candidate_flavor and candidate_flavor.get("vetoed")
                            ),
                            "score": (
                                candidate_flavor["score"] if candidate_flavor else None
                            ),
                            "threshold": humanizer.AI_FLAVOR_THRESHOLD,
                            "min_threshold": humanizer.MIN_THRESHOLD,
                        })

                        candidate_contrast = writer_agent.find_contrast_hits(candidate)
                        if candidate_contrast:
                            polish_issues = (
                                "润色稿仍有「不是……，是……」的先否定再纠正句式，"
                                "必须直接写确定的那个事实："
                                + "；".join(candidate_contrast[:5])
                            )
                            yield sse({
                                "type": "warning",
                                "message": "润色稿出现「不是……，是……」句式，已丢弃该轮结果并重试。",
                            })
                            yield sse({"type": "polish_replace", "content": best_text})
                            continue
                        candidate_metaphors = writer_agent.find_metaphor_hits(candidate)
                        candidate_tags = (
                            writer_agent.find_dialogue_tag_hits(candidate)
                            + writer_agent.find_style_hits(candidate)
                        )
                        if candidate_metaphors:
                            polish_issues = (
                                "润色稿出现了比喻，必须改写成直接动作或状态："
                                + "；".join(candidate_metaphors[:5])
                            )
                            yield sse({
                                "type": "warning",
                                "message": "润色稿出现比喻，已丢弃该轮结果并重试。",
                            })
                            yield sse({"type": "polish_replace", "content": best_text})
                            continue
                        best_tags = (
                            writer_agent.find_dialogue_tag_hits(best_text)
                            + writer_agent.find_style_hits(best_text)
                        )
                        if candidate_tags and len(candidate_tags) >= len(best_tags):
                            polish_issues = (
                                "台词或文风硬伤仍未改好（说话动词用说道/问道/喊道，"
                                "删旁白判断，修正量词与拟人）："
                                + "；".join(candidate_tags[:5])
                            )
                            yield sse({
                                "type": "warning",
                                "message": "润色稿仍有台词或文风硬伤，已丢弃该轮结果并重试。",
                            })
                            yield sse({"type": "polish_replace", "content": best_text})
                            continue

                        better = _is_better(candidate_flavor, best_flavor)
                        if (
                            not better
                            and candidate_flavor
                            and best_flavor
                            and len(candidate_tags) < len(best_tags)
                            and candidate_flavor["score"] >= best_flavor["score"]
                        ):
                            better = True
                        if better:
                            best_text, best_flavor = candidate, candidate_flavor
                        else:
                            old_score = (
                                best_flavor["score"] if best_flavor else "未知"
                            )
                            new_score = (
                                candidate_flavor["score"]
                                if candidate_flavor
                                else "未知"
                            )
                            message = (
                                f"第 {round_no} 轮润色 {new_score} 分，"
                                f"未高于当前稿 {old_score} 分，已丢弃该轮结果。"
                            )
                            if candidate_flavor and best_flavor:
                                polish_issues = best_flavor["issues"]
                            elif candidate_flavor:
                                polish_issues = candidate_flavor["issues"]
                            yield sse({"type": "warning", "message": message})
                            yield sse({"type": "polish_replace", "content": best_text})

                        if candidate_flavor and (
                            candidate_flavor["passed"]
                            or candidate_flavor.get("borderline")
                        ):
                            break
                        if better and candidate_flavor:
                            polish_issues = candidate_flavor["issues"]

                    if best_text == original and best_flavor is not None \
                            and not best_flavor["passed"]:
                        yield sse({
                            "type": "warning",
                            "message": (
                                f"润色未能提高 AI 味评分，已保留原文"
                                f"（{best_flavor['score']} 分）。"
                            ),
                        })

                    remaining_tags = (
                        writer_agent.find_dialogue_tag_hits(best_text)
                        + writer_agent.find_style_hits(best_text)
                        + writer_agent.find_contrast_hits(best_text)
                    )
                    if remaining_tags:
                        yield sse({
                            "type": "warning",
                            "message": (
                                "润色后仍存在台词或文风硬伤，建议人工修改："
                                + "；".join(remaining_tags[:3])
                            ),
                        })

                flavor = best_flavor
                final_word_count = await asyncio.to_thread(
                    writer_agent.update_chapter_content,
                    final_event["novel_chapter_id"],
                    best_text,
                )
                final_event["word_count"] = final_word_count
                final_event["ai_flavor"] = best_flavor

                if not (WORD_MIN <= final_word_count <= WORD_MAX):
                    yield sse({
                        "type": "warning",
                        "message": (
                            f"润色后为 {final_word_count} 字，已超出 "
                            f"{WORD_MIN}-{WORD_MAX} 字区间，请人工调整。"
                        ),
                    })
                if flavor and flavor.get("borderline"):
                    yield sse({
                        "type": "warning",
                        "message": (
                            f"当前稿 {flavor['score']} 分，处于 "
                            f"{humanizer.MIN_THRESHOLD}-{humanizer.AI_FLAVOR_THRESHOLD - 1} "
                            "区间，已保留；可人工接受或再润色一轮。"
                        ),
                    })
                elif not flavor or not flavor.get("passed"):
                    yield sse({
                        "type": "warning",
                        "message": "AI 味仍未通过，已保留评分最高的一版，建议人工微调。",
                    })

        if req.session_id:
            score = (final_event.get("ai_flavor") or {}).get("score")
            await asyncio.to_thread(
                session_store.add_message,
                req.session_id, "assistant",
                f"已完成第 {final_event.get('chapter_no')} 章"
                f"《{final_event.get('title')}》，"
                f"{final_event.get('word_count')} 字"
                + (f"，AI 味 {score} 分。" if score is not None else "。"),
            )
            await asyncio.to_thread(
                session_store.update_session,
                req.session_id,
                current_chapter_id=final_event.get("chapter_outline_id"),
                current_novel_chapter_id=final_event.get("novel_chapter_id"),
                status="写作中",
                message=(
                    f"已完成第 {final_event.get('chapter_no')} 章"
                    f"《{final_event.get('title')}》"
                    f"（{final_event.get('word_count')} 字）"
                ),
            )

        yield sse(final_event)

        # 正文最终落库后自动摘要，同时更新人物状态与伏笔进度
        yield sse({"type": "stage", "message": "正在生成本章摘要并更新人物/伏笔状态…"})
        try:
            res = await asyncio.to_thread(
                writer_agent.chapterSummarizer,
                {"novel_chapter_id": final_event.get("novel_chapter_id")},
            )
            yield sse({
                "type": "summary",
                "novel_chapter_id": final_event.get("novel_chapter_id"),
                "summary": res.get("summary", ""),
            })
            if req.session_id:
                await asyncio.to_thread(
                    session_store.add_message,
                    req.session_id, "assistant",
                    f"第 {final_event.get('chapter_no')} 章摘要："
                    f"{res.get('summary', '')}",
                )
                await asyncio.to_thread(
                    session_store.update_session,
                    req.session_id,
                    message=f"第 {final_event.get('chapter_no')} 章已完成并生成摘要",
                )
        except Exception as exc:
            yield sse({"type": "warning", "message": f"摘要生成失败：{exc}"})

        if not final_ok:
            reasons = last_reasons or ["字数或内容审核未通过，但未返回具体原因"]
            detail = "\n".join(f"{i}. {r}" for i, r in enumerate(reasons, 1))
            yield sse({
                "type": "final_fail",
                "reasons": reasons,
                "message": (
                    f"自动重写 {MAX_REWRITES} 次仍未通过，请按以下原因人工修改：\n"
                    + detail
                ),
            })

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=sse_headers()
    )


@router.post("/api/chapter/summarize")
def chapter_summarize(req: ChapterIdRequest):
    try:
        res = writer_agent.chapterSummarizer({
            "novel_chapter_id": req.novel_chapter_id,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "novel_chapter_id": res["novel_chapter_id"],
        "summary": res["summary"],
    }


@router.post("/api/chapter/audit")
def chapter_audit(req: ChapterIdRequest):
    try:
        result = reviewer.chapterAudit({
            "novel_chapter_id": req.novel_chapter_id,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    content = _chapter_text(req.novel_chapter_id)
    try:
        result["ai_flavor"] = humanizer.audit(content)
    except Exception as exc:
        result["ai_flavor"] = {
            "passed": False,
            "score": 0,
            "threshold": humanizer.AI_FLAVOR_THRESHOLD,
            "min_threshold": humanizer.MIN_THRESHOLD,
            "vetoed": False,
            "borderline": False,
            "issues": f"AI 味审核失败：{exc}",
            "suggestion": "无",
        }
    return result


@router.post("/api/chapter/polish")
def chapter_polish(req: ChapterIdRequest):
    """对已有正文再润色一轮：先审核取意见，润色后仅保留评分更高的版本"""
    content = _chapter_text(req.novel_chapter_id)
    if not content:
        raise HTTPException(status_code=400, detail="该章暂无正文，无法润色")
    try:
        before = humanizer.audit(content)
        issues = "" if before["passed"] else before.get("issues", "")
        polished = humanizer.polish(content, issues)
        if not polished:
            raise ValueError("润色结果为空")
        after = humanizer.audit(polished)
        if not _is_better(after, before):
            return {
                "novel_chapter_id": req.novel_chapter_id,
                "content": content,
                "word_count": len(re.sub(r"\s+", "", content)),
                "ai_flavor": before,
                "improved": False,
            }
        word_count = writer_agent.update_chapter_content(
            req.novel_chapter_id, polished
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"润色失败：{exc}")
    return {
        "novel_chapter_id": req.novel_chapter_id,
        "content": polished,
        "word_count": word_count,
        "ai_flavor": after,
        "improved": True,
    }
