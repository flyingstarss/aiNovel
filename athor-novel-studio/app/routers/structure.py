import asyncio

from fastapi.responses import StreamingResponse

from app.agents import editor, session_store
from app.schemas import StructureRequest, VolumeRequest
from app.sse import sse, sse_headers, stage_heartbeat
from fastapi import APIRouter

router = APIRouter()


async def prepare_volume_events(outline_id, vol):
    """按卷生成细纲、人物、章纲：一层卷写完后，再准备下一卷"""
    vid = vol["id"]
    vno = vol["volume_no"]

    has_short = await asyncio.to_thread(
        editor._fetch_one,
        "SELECT id FROM short_outline WHERE volume_id = %s LIMIT 1", (vid,),
    )
    if not has_short:
        yield sse({"type": "stage", "stage": "short", "message": f"正在生成第{vno}卷细纲…"})
        holder = {}
        async for ev in stage_heartbeat(
            editor.shortOutlineEdit, {"outline_id": outline_id, "volume_id": vid}, "short", holder
        ):
            yield ev

    has_person = await asyncio.to_thread(
        editor._fetch_one,
        "SELECT id FROM person WHERE first_volume_no = %s AND outline_id = %s LIMIT 1",
        (vno, outline_id),
    )
    if not has_person:
        yield sse({"type": "stage", "stage": "person", "message": f"正在生成第{vno}卷人物（依据本卷地点与地图）…"})
        holder = {}
        async for ev in stage_heartbeat(
            editor.volumePersonEdit, {"outline_id": outline_id, "volume_id": vid}, "person", holder
        ):
            yield ev

    placeholder_rows = await asyncio.to_thread(
        editor._fetch_all,
        """
        SELECT so.id, so.volume_id, so.seq, so.chapter_count
        FROM short_outline so
        WHERE so.volume_id = %s AND so.segment_mode = 1
          AND NOT EXISTS (SELECT 1 FROM chapter_outline co WHERE co.short_id = so.id)
        ORDER BY so.seq
        """, (vid,),
    )
    if placeholder_rows:
        yield sse({"type": "stage", "stage": "chapter", "message": f"第{vno}卷细纲完成，正在创建章节占位…"})
        for row in placeholder_rows:
            await asyncio.to_thread(editor.ensure_chapter_placeholders, row)
        yield sse({"type": "stage", "stage": "chapter", "message": f"第{vno}卷章节占位已就绪"})

    yield sse({"type": "volume_done", "volume_no": vno, "message": f"第{vno}卷细纲与章节占位已就绪"})


@router.post("/api/structure/stream")
async def structure_stream(req: StructureRequest):
    async def gen():
        try:
            outline_id = req.outline_id
            if not outline_id and req.session_id:
                sess = await asyncio.to_thread(
                    session_store.get_session, req.session_id
                )
                outline_id = sess.get("outline_id") if sess else None
            if not outline_id:
                raise ValueError("缺少大纲，请先生成并审核大纲")

            if req.session_id:
                await asyncio.to_thread(
                    session_store.add_message,
                    req.session_id, "user", "生成/补全小说结构",
                )
            yield sse({"type": "stage", "stage": "volume", "message": "正在生成分卷…"})
            holder = {}
            async for ev in stage_heartbeat(editor.volumeEdit, {"outline_id": outline_id}, "volume", holder):
                yield ev
            vol = holder["result"]

            yield sse({"type": "stage", "stage": "map", "message": f"分卷完成（{len(vol.get('volume_ids', []))} 卷），正在生成地图…"})
            holder = {}
            async for ev in stage_heartbeat(editor.mapEdit, {"outline_id": outline_id}, "map", holder):
                yield ev

            yield sse({"type": "stage", "stage": "foreshadow", "message": "地图完成，正在整理伏笔…"})
            holder = {}
            async for ev in stage_heartbeat(editor.foreshadowEdit, {"outline_id": outline_id}, "foreshadow", holder):
                yield ev

            first_vol = await asyncio.to_thread(
                editor._fetch_one,
                "SELECT * FROM volume WHERE outline_id = %s ORDER BY volume_no LIMIT 1",
                (outline_id,),
            )
            if first_vol:
                async for ev in prepare_volume_events(outline_id, first_vol):
                    yield ev

            if req.session_id:
                await asyncio.to_thread(
                    session_store.add_message,
                    req.session_id, "assistant",
                    "小说结构已生成：分卷、地图、伏笔，以及第 1 卷细纲与章纲。",
                )
                await asyncio.to_thread(
                    session_store.update_session,
                    req.session_id, status="结构已生成",
                    message="分卷、地图、伏笔已生成，第 1 卷细纲与章纲已就绪",
                )
            yield sse({"type": "done", "outline_id": outline_id, "message": "小说结构生成完成"})
        except Exception as exc:
            yield sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=sse_headers()
    )


@router.post("/api/volume/stream")
async def volume_stream(req: VolumeRequest):
    async def gen():
        try:
            outline_id = req.outline_id
            if not outline_id and req.session_id:
                sess = await asyncio.to_thread(
                    session_store.get_session, req.session_id
                )
                outline_id = sess.get("outline_id") if sess else None
            if not outline_id:
                raise ValueError("缺少大纲")

            if req.volume_no:
                vol = await asyncio.to_thread(
                    editor._fetch_one,
                    "SELECT * FROM volume WHERE outline_id = %s AND volume_no = %s",
                    (outline_id, req.volume_no),
                )
            else:
                vol = await asyncio.to_thread(
                    editor._fetch_one,
                    """
                    SELECT v.* FROM volume v
                    WHERE v.outline_id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM short_outline so WHERE so.volume_id = v.id
                      )
                    ORDER BY v.volume_no LIMIT 1
                    """, (outline_id,)
                )
            if not vol:
                yield sse({"type": "error", "message": "没有待准备的下一卷"})
                return

            async for ev in prepare_volume_events(outline_id, vol):
                yield ev
            yield sse({"type": "done", "outline_id": outline_id, "message": f"第{vol['volume_no']}卷已就绪"})
        except Exception as exc:
            yield sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=sse_headers()
    )


@router.get("/api/progress")
def progress(session_id: str | None = None):
    outline = None
    if session_id:
        sess = session_store.get_session(session_id)
        if sess and sess.get("outline_id"):
            outline = editor._fetch_one(
                "SELECT * FROM outline WHERE id = %s", (sess["outline_id"],)
            )
    else:
        outline = editor._fetch_one("SELECT * FROM outline ORDER BY id DESC LIMIT 1")

    empty = {
        "stage": "未开始",
        "outline_status": None,
        "outline_id": None,
        "percent": 0,
        "counts": {"volumes": 0, "shorts": 0, "chapters": 0,
                   "written": 0, "summarized": 0},
        "volumes": [],
        "next_volume_no": None,
        "next_chapter": None,
        "recent": [],
    }
    if not outline:
        return empty

    outline_id = outline["id"]
    volumes = editor._fetch_one(
        "SELECT COUNT(*) AS c FROM volume WHERE outline_id = %s", (outline_id,)
    )["c"]
    shorts = editor._fetch_one(
        """
        SELECT COUNT(*) AS c FROM short_outline so
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s
        """, (outline_id,)
    )["c"]
    chapters = editor._fetch_one(
        """
        SELECT COUNT(*) AS c FROM chapter_outline co
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s
        """, (outline_id,)
    )["c"]
    written = editor._fetch_one(
        """
        SELECT COUNT(*) AS c FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s AND nc.content IS NOT NULL AND nc.content <> ''
        """, (outline_id,)
    )["c"]
    summarized = editor._fetch_one(
        """
        SELECT COUNT(*) AS c FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s
          AND nc.summary IS NOT NULL AND nc.summary <> ''
        """, (outline_id,)
    )["c"]

    next_chapter = editor._fetch_one(
        """
        SELECT co.id, co.chapter_no, co.title, co.target_words,
               v.volume_no, v.title AS volume_title
        FROM chapter_outline co
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        LEFT JOIN novel_chapter nc ON nc.chapter_outline_id = co.id
        WHERE v.outline_id = %s AND nc.id IS NULL
        ORDER BY v.volume_no, so.seq, co.chapter_no
        LIMIT 1
        """, (outline_id,)
    )

    volume_stats = []
    for v in editor._fetch_all(
        "SELECT id, volume_no, title FROM volume WHERE outline_id = %s ORDER BY volume_no",
        (outline_id,),
    ):
        v_shorts = editor._fetch_one(
            "SELECT COUNT(*) AS c FROM short_outline WHERE volume_id = %s", (v["id"],)
        )["c"]
        v_chapters = editor._fetch_one(
            """
            SELECT COUNT(*) AS c FROM chapter_outline co
            JOIN short_outline so ON co.short_id = so.id
            WHERE so.volume_id = %s
            """, (v["id"],)
        )["c"]
        v_written = editor._fetch_one(
            """
            SELECT COUNT(*) AS c FROM novel_chapter nc
            JOIN chapter_outline co ON nc.chapter_outline_id = co.id
            JOIN short_outline so ON co.short_id = so.id
            WHERE so.volume_id = %s AND nc.content IS NOT NULL AND nc.content <> ''
            """, (v["id"],)
        )["c"]
        if v_chapters == 0:
            v_status = "待准备"
        elif v_written < v_chapters:
            v_status = "写作中"
        else:
            v_status = "已完成"
        volume_stats.append({
            "volume_no": v["volume_no"],
            "title": v["title"],
            "shorts": v_shorts,
            "chapters": v_chapters,
            "written": v_written,
            "status": v_status,
        })

    next_volume_no = next(
        (v["volume_no"] for v in volume_stats if v["chapters"] == 0), None
    )

    recent = editor._fetch_all(
        """
        SELECT nc.id, nc.chapter_no, nc.title, nc.word_count,
               (nc.summary IS NOT NULL AND nc.summary <> '') AS has_summary,
               v.volume_no
        FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s
        ORDER BY nc.id DESC
        LIMIT 5
        """, (outline_id,)
    )
    for item in recent:
        item["has_summary"] = bool(item["has_summary"])

    status = outline.get("status") or "待审核"
    if status == "待审核":
        stage = "大纲待审核"
    elif status == "已驳回":
        stage = "大纲已驳回"
    elif chapters == 0:
        stage = "结构待生成"
    elif written == 0:
        stage = "待开始写作"
    elif written < chapters:
        stage = "写作中"
    else:
        stage = "已完成"

    return {
        "stage": stage,
        "outline_status": status,
        "outline_id": outline_id,
        "percent": round(written / chapters * 100, 1) if chapters else 0,
        "counts": {
            "volumes": volumes,
            "shorts": shorts,
            "chapters": chapters,
            "written": written,
            "summarized": summarized,
        },
        "volumes": volume_stats,
        "next_volume_no": next_volume_no,
        "next_chapter": next_chapter,
        "recent": recent,
    }
