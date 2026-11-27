import pymysql
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from app.db import connect as db_connect

router = APIRouter()


def _fetch_all(sql, args=()):
    conn = db_connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def _fetch_one(sql, args=()):
    conn = db_connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute(sql, args)
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


@router.get("/api/library/books")
def library_books():
    """列出所有已写有正文的大纲，供阅读页选择"""
    return _fetch_all(
        """
        SELECT o.id AS outline_id, o.title, o.status,
               COUNT(nc.id) AS chapters,
               MAX(nc.updated_at) AS last_time
        FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        JOIN outline o ON v.outline_id = o.id
        WHERE nc.content IS NOT NULL AND nc.content <> ''
        GROUP BY o.id, o.title, o.status
        ORDER BY last_time DESC
        """
    )


@router.get("/api/library/chapters")
def library_chapters(outline_id: int):
    """按卷、短纲、章的阅读顺序列出某本小说的已写章节"""
    return _fetch_all(
        """
        SELECT nc.id, nc.title, nc.word_count, nc.status, nc.updated_at,
               (nc.summary IS NOT NULL AND nc.summary <> '') AS has_summary,
               co.chapter_no, so.seq AS short_seq, so.title AS short_title,
               v.volume_no, v.title AS volume_title
        FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s
          AND nc.content IS NOT NULL AND nc.content <> ''
        ORDER BY v.volume_no, so.seq, co.chapter_no
        """,
        (outline_id,),
    )


@router.get("/api/library/latest")
def library_latest(outline_id: int):
    """最近一次生成完成的章节，用于重新进入会话时展示"""
    row = _fetch_one(
        """
        SELECT nc.id, nc.title, nc.content, nc.word_count, nc.status, nc.updated_at,
               co.id AS chapter_outline_id, co.chapter_no,
               v.volume_no, v.title AS volume_title
        FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s
          AND nc.content IS NOT NULL AND nc.content <> ''
        ORDER BY v.volume_no DESC, so.seq DESC, co.chapter_no DESC
        LIMIT 1
        """,
        (outline_id,),
    )
    return {"has_chapter": bool(row), "chapter": row}


@router.get("/api/library/settings")
def library_settings(outline_id: int):
    """查看本书的世界观、人物档案、人物关系、地图地点与伏笔"""
    outline = _fetch_one(
        "SELECT id, title, status FROM outline WHERE id = %s", (outline_id,)
    )
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")

    return {
        "outline": outline,
        "worldview": _fetch_one(
            "SELECT * FROM worldview WHERE outline_id = %s "
            "OR outline_id IS NULL ORDER BY outline_id DESC, id DESC LIMIT 1",
            (outline_id,),
        ),
        "persons": _fetch_all(
            """
            SELECT name, age, gender, appear, charTr, situat, ability, goal,
                   relation, first_volume_no, current_state, current_location,
                   last_chapter_no
            FROM person
            WHERE outline_id = %s OR outline_id IS NULL
            ORDER BY COALESCE(first_volume_no, 999), name
            """,
            (outline_id,),
        ),
        "relations": _fetch_all(
            """
            SELECT name_a, name_b, relation_desc, relation_type
            FROM person_relation
            WHERE outline_id = %s OR outline_id IS NULL
            ORDER BY id
            """,
            (outline_id,),
        ),
        "places": _fetch_all(
            """
            SELECT name, type, parent_name, region, description, terrain,
                   climate, resources, inhabitants, story_function, related_events
            FROM story_map
            WHERE outline_id = %s OR outline_id IS NULL
            ORDER BY id
            """,
            (outline_id,),
        ),
        "foreshadows": _fetch_all(
            "SELECT name, content, plant_place, reveal_place, payoff, "
            "importance, status FROM foreshadow "
            "WHERE outline_id = %s OR outline_id IS NULL ORDER BY id",
            (outline_id,),
        ),
    }


@router.get("/api/library/download")
def library_download(outline_id: int):
    """把整本已生成的小说导出为 txt"""
    outline = _fetch_one(
        "SELECT id, title FROM outline WHERE id = %s", (outline_id,)
    )
    if not outline:
        raise HTTPException(status_code=404, detail="大纲不存在")

    chapters = _fetch_all(
        """
        SELECT nc.title, nc.content, co.chapter_no,
               v.volume_no, v.title AS volume_title
        FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s
          AND nc.content IS NOT NULL AND nc.content <> ''
        ORDER BY v.volume_no, so.seq, co.chapter_no
        """,
        (outline_id,),
    )
    if not chapters:
        raise HTTPException(status_code=404, detail="该书还没有已生成的正文")

    lines = [outline.get("title") or "未命名小说", ""]
    last_volume = None
    for ch in chapters:
        if ch["volume_no"] != last_volume:
            last_volume = ch["volume_no"]
            lines.extend([f"第 {ch['volume_no']} 卷 {ch.get('volume_title') or ''}".strip(), ""])
        lines.append(f"第 {ch['chapter_no']} 章 {ch.get('title') or ''}".strip())
        lines.extend(["", (ch.get("content") or "").strip(), ""])
    text = "\n".join(lines).strip() + "\n"

    filename = quote(f"{outline.get('title') or '小说'}.txt")
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/api/library/chapters/{chapter_id}")
def library_chapter_detail(chapter_id: int):
    row = _fetch_one(
        """
        SELECT nc.id, nc.title, nc.content, nc.word_count, nc.summary,
               nc.summary_points, nc.status, nc.updated_at,
               co.chapter_no, co.title AS outline_title,
               so.title AS short_title,
               v.volume_no, v.title AS volume_title
        FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE nc.id = %s
        """,
        (chapter_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="章节不存在")
    return row
