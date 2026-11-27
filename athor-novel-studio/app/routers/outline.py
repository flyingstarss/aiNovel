import asyncio

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

from app import monitor
from app.agents import editor, reviewer, session_store
from app.db import execute as db_execute
from app.schemas import (
    OutlineRequest,
    OutlineReviseRequest,
    OutlineUpdate,
    ReviewRequest,
)
from app.sse import sse, sse_headers

router = APIRouter()


@router.post("/api/outline/stream")
async def outline_stream(req: OutlineRequest):
    if req.session_id:
        await asyncio.to_thread(
            session_store.add_message, req.session_id, "user", req.userinput
        )

    async def gen():
        try:
            # 每本书有独立世界观：新会话必须先按本书需求重新生成，
            # 老会话则按自身的 outline_id 读取，避免串到别的书
            sess = (
                await asyncio.to_thread(session_store.get_session, req.session_id)
                if req.session_id
                else None
            )
            world_result = None
            if sess and sess.get("outline_id"):
                worldview_text = await asyncio.to_thread(
                    editor._worldview_text, sess["outline_id"]
                )
            else:
                yield sse({
                    "type": "stage",
                    "message": "正在为本书生成专属世界观…",
                })
                world_result = await asyncio.to_thread(
                    editor.worldEdit, {"userinput": req.userinput}
                )
                worldview_text = await asyncio.to_thread(editor._worldview_text)

            parts = []
            with monitor.step("大纲流式生成"):
                async for chunk in editor.llm.astream([
                    SystemMessage(
                        "你是一位资深小说总编，负责把控整部小说的总体故事走向。"
                        "请依据世界观和用户需求，直接输出 Markdown 格式的全书大纲。"
                        "用户给出的身份、地点或事件只是故事起点（引子），不是故事边界："
                        "你必须主动把舞台扩展到更大的世界，绝不能围绕起点打转。"
                        "世界观只作参考：其中与本次需求无关的旧设定或专有名词一律不得写入大纲，以用户需求为准。"
                    ),
                    HumanMessage(content=f"""【世界观】
{worldview_text}

【用户需求】
{req.userinput}

请严格按以下 5 个小节输出，每个小节用 Markdown 二级标题（##），不要增加其他小节：

## 书名
## 主角
（姓名、身份起点、性格底色、核心渴望与恐惧；弧光：从……到……，最终成为本世界最强者）
## 女主/关键配角
（每人 1-2 句：身份、立场、与主角的关系变化）
## 主线
（1-3 句话讲清：开局获得什么、被什么势力盯上、如何升级、最终登顶）
## 支线
（2-3 条，用分号分隔，每条一句话，必须服务主线）

要求：
1. 这是网文，以爽感为主，节奏明快，奇遇、升级、打脸、势力扩张等爽点要明确；
2. 主角最终必须成为本世界观下的最强者或巅峰存在，禁止归于平凡、隐退或牺牲式结局；
3. 大纲只写骨架，不要写分幕细节和逐章剧情，每节控制在 1-3 句话；
4. 用户输入只是开篇引子：主线必须包含离开初始地点、走向更大世界的升级路线，中后期不得停留在初始场景；
5. 主线至少跨越 3 个差异明显的地理或势力区域，最终舞台要足够大；
6. 只输出大纲本身，不要输出寒暄、创作说明或其他内容。""")
                ]):
                    text = chunk.content or ""
                    if text:
                        parts.append(text)
                        yield sse({"type": "delta", "text": text})

            markdown = "".join(parts).strip()
            if not markdown:
                raise RuntimeError("模型未返回大纲内容")

            yield sse({"type": "stage", "message": "正在整理大纲结构并入库…"})
            structured = editor.llm.with_structured_output(editor.NovelOutline)
            with monitor.step("大纲结构化提取"):
                ai = await structured.ainvoke([
                    SystemMessage(
                        "你是信息提取器，只从给定大纲中提取字段。"
                        "缺失的字段返回空字符串，禁止编造原文没有的剧情。"
                        "theme / logline / core_conflict 可高度概括，各不超过 40 字；"
                        "act_qi 到 act_he 若原文没有对应内容，一律返回空字符串。"
                    ),
                    HumanMessage(content=f"请从下面的大纲中提取结构化字段：\n\n{markdown}"),
                ])
            outline_id = await asyncio.to_thread(editor._save_outline, ai, markdown)
            worldview_id = (world_result or {}).get("worldview_id")
            if worldview_id:
                await asyncio.to_thread(
                    db_execute,
                    "UPDATE worldview SET outline_id = %s WHERE id = %s",
                    (outline_id, worldview_id),
                )
            if req.session_id:
                await asyncio.to_thread(
                    session_store.add_message,
                    req.session_id, "assistant",
                    f"已生成大纲《{ai.title or '未命名'}》，状态：待审核。",
                )
                await asyncio.to_thread(
                    session_store.update_session,
                    req.session_id,
                    outline_id=outline_id,
                    status="大纲待审核",
                    message="大纲已生成，待用户审核",
                )
            yield sse({
                "type": "done",
                "outline_id": outline_id,
                "status": "待审核",
                "outline": ai.model_dump(),
            })
        except Exception as exc:
            if req.session_id:
                await asyncio.to_thread(
                    session_store.add_message,
                    req.session_id, "system", f"大纲生成失败：{exc}",
                )
            yield sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=sse_headers()
    )


OUTLINE_FORMAT_RULES = """请严格按以下 5 个小节输出，每个小节用 Markdown 二级标题（##），不要增加其他小节：

## 书名
## 主角
（姓名、身份起点、性格底色、核心渴望与恐惧；弧光：从……到……，最终成为本世界最强者）
## 女主/关键配角
（每人 1-2 句：身份、立场、与主角的关系变化）
## 主线
（1-3 句话讲清：开局获得什么、被什么势力盯上、如何升级、最终登顶）
## 支线
（2-3 条，用分号分隔，每条一句话，必须服务主线）

要求：
1. 这是网文，以爽感为主，节奏明快，奇遇、升级、打脸、势力扩张等爽点要明确；
2. 主角最终必须成为本世界观下的最强者或巅峰存在，禁止归于平凡、隐退或牺牲式结局；
3. 大纲只写骨架，不要写分幕细节和逐章剧情，每节控制在 1-3 句话；
4. 用户输入只是开篇引子：主线必须包含离开初始地点、走向更大世界的升级路线，中后期不得停留在初始场景；
5. 主线至少跨越 3 个差异明显的地理或势力区域，最终舞台要足够大；
6. 只输出大纲本身，不要输出寒暄、创作说明或其他内容。"""


@router.post("/api/outline/revise/stream")
async def outline_revise_stream(req: OutlineReviseRequest):
    """已生成的大纲按用户修改意见重写，保留未涉及部分，写回原大纲并回到待审核"""
    comment = (req.comment or "").strip()
    if not comment:
        raise HTTPException(status_code=400, detail="请填写修改大纲的意见")

    row = await asyncio.to_thread(
        editor._fetch_one,
        "SELECT id, title, content FROM outline WHERE id = %s",
        (req.outline_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="大纲不存在")
    original = (row.get("content") or "").strip()
    if not original:
        raise HTTPException(status_code=400, detail="该大纲暂无原文，无法按意见修改")

    if req.session_id:
        await asyncio.to_thread(
            session_store.add_message, req.session_id, "user", f"修改大纲：{comment}"
        )

    async def gen():
        try:
            yield sse({"type": "stage", "message": "正在按修改意见重写大纲…"})
            worldview_text = await asyncio.to_thread(
                editor._worldview_text, req.outline_id
            )

            parts = []
            with monitor.step("大纲按意见修订"):
                async for chunk in editor.llm.astream([
                    SystemMessage(
                        "你是一位资深小说总编，负责按作者的修改意见修订全书大纲。"
                        "必须保留原大纲中与修改意见无关的内容，只调整被点名的部分，"
                        "输出完整的 Markdown 大纲，而不是差异说明或修改建议。"
                    ),
                    HumanMessage(content=f"""【世界观】
{worldview_text}

【当前大纲】
{original}

【作者修改意见】
{comment}

请在保留原大纲整体走向的前提下，按修改意见调整相关内容，重新输出完整大纲。
{OUTLINE_FORMAT_RULES}""")
                ]):
                    text = chunk.content or ""
                    if text:
                        parts.append(text)
                        yield sse({"type": "delta", "text": text})

            markdown = "".join(parts).strip()
            if not markdown:
                raise RuntimeError("模型未返回修订后的大纲内容")

            yield sse({"type": "stage", "message": "正在重新解析大纲结构并保存…"})
            outline_id, ai = await asyncio.to_thread(
                editor.update_outline_content, req.outline_id, markdown, comment
            )
            if req.session_id:
                await asyncio.to_thread(
                    session_store.add_message,
                    req.session_id, "assistant",
                    f"已按意见修改大纲《{ai.title or '未命名'}》，状态：待审核。",
                )
                await asyncio.to_thread(
                    session_store.update_session,
                    req.session_id,
                    outline_id=outline_id,
                    status="大纲待审核",
                    message="大纲已按意见修改，待重新审核",
                )
            yield sse({
                "type": "done",
                "outline_id": outline_id,
                "status": "待审核",
                "outline": ai.model_dump(),
            })
        except Exception as exc:
            if req.session_id:
                await asyncio.to_thread(
                    session_store.add_message,
                    req.session_id, "system", f"大纲修改失败：{exc}",
                )
            yield sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=sse_headers()
    )


@router.post("/api/outline/import")
async def outline_import(file: UploadFile = File(...)):
    """读取用户上传的 txt，返回可放进需求输入框的文本"""
    raw = await file.read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="ignore")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文件内容为空或无法识别编码")

    limit = 12000
    truncated = len(text) > limit
    if truncated:
        text = text[:limit]
    return {
        "filename": file.filename,
        "chars": len(text),
        "truncated": truncated,
        "text": text,
    }


@router.get("/api/outline/{outline_id}")
def outline_get(outline_id: int):
    row = editor._fetch_one(
        "SELECT id, title, content, status, review_comment "
        "FROM outline WHERE id = %s",
        (outline_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="大纲不存在")
    return row


@router.put("/api/outline/{outline_id}")
def outline_update(outline_id: int, req: OutlineUpdate):
    try:
        outline_id, ai = editor.update_outline_content(
            outline_id, req.content, req.comment
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"保存失败：{exc}")

    if req.session_id:
        session_store.add_message(
            req.session_id, "user",
            "修改大纲并保存" + (f"，备注：{req.comment}" if req.comment else ""),
        )
        session_store.update_session(
            req.session_id,
            outline_id=outline_id,
            status="大纲待审核",
            message="大纲已修改，待重新审核",
        )
    return {
        "outline_id": outline_id,
        "status": "待审核",
        "title": ai.title,
        "outline": ai.model_dump(),
    }


@router.post("/api/outline/review")
def outline_review(req: ReviewRequest):
    try:
        res = reviewer.outlineReview({
            "outline_id": req.outline_id,
            "review_decision": req.decision,
            "review_comment": req.comment,
        })
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if req.session_id:
        session_store.add_message(
            req.session_id, "user",
            f"大纲审核：{req.decision}" + (f"，意见：{req.comment}" if req.comment else ""),
        )
        session_store.add_message(
            req.session_id, "assistant",
            f"大纲审核完成，结果：{res['status']}"
            + (f"；{res.get('comment')}" if res.get("comment") else ""),
        )
        session_store.update_session(
            req.session_id,
            status=f"大纲{res['status']}",
            message=req.comment or res["status"],
        )
    return res
