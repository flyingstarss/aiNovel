import uuid

import pymysql

from app.db import connect as db_connect


ALLOWED_FIELDS = {
    "title", "status", "outline_id",
    "current_chapter_id", "current_novel_chapter_id", "message",
}


def new_session_id():
    return uuid.uuid4().hex


def _connect():
    return db_connect()


def create_session(userinput="", title=None, session_id=None):
    session_id = session_id or new_session_id()
    title = title or (userinput.strip()[:30] or "未命名会话")

    conn = _connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute(
            """
            INSERT INTO novel_session (session_id, title, userinput, status)
            VALUES (%s, %s, %s, '进行中')
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                userinput = VALUES(userinput)
            """,
            (session_id, title, userinput),
        )
        conn.commit()
        return get_session(session_id)
    finally:
        cur.close()
        conn.close()


def get_session(session_id):
    conn = _connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute(
            "SELECT * FROM novel_session WHERE session_id = %s", (session_id,)
        )
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def list_sessions(limit=20):
    conn = _connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute(
            "SELECT s.*, o.title AS outline_title "
            "FROM novel_session s "
            "LEFT JOIN outline o ON o.id = s.outline_id "
            "ORDER BY s.update_time DESC LIMIT %s",
            (limit,),
        )
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def update_session(session_id, **fields):
    data = {k: v for k, v in fields.items() if k in ALLOWED_FIELDS}
    if not data:
        return
    assignments = ", ".join(f"{k} = %s" for k in data)
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            f"UPDATE novel_session SET {assignments} WHERE session_id = %s",
            (*data.values(), session_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def add_message(session_id, role, content):
    """追加一条会话记录，role 取值 user / assistant / system"""
    if not session_id or not (content or "").strip():
        return
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO session_message (session_id, role, content) "
            "VALUES (%s, %s, %s)",
            (session_id, role, content.strip()),
        )
        conn.commit()
    except pymysql.MySQLError:
        # 记录失败不应影响创作流程（例如会话已被清理）
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def list_messages(session_id, limit=200):
    conn = _connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute(
            "SELECT id, role, content, create_time FROM session_message "
            "WHERE session_id = %s ORDER BY id ASC LIMIT %s",
            (session_id, limit),
        )
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()
