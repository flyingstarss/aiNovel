from fastapi import APIRouter, HTTPException, Response

from app.agents import session_store
from app.schemas import SessionCreate, SessionUpdate

router = APIRouter()


@router.post("/api/sessions")
def session_create(req: SessionCreate):
    return session_store.create_session(req.userinput, req.title)


@router.get("/api/sessions")
def session_list(limit: int = 20):
    return session_store.list_sessions(limit)


@router.get("/api/sessions/{session_id}/messages")
def session_messages(session_id: str, response: Response):
    row = session_store.get_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "session": row,
        "messages": session_store.list_messages(session_id),
    }


@router.patch("/api/sessions/{session_id}")
def session_update(session_id: str, req: SessionUpdate):
    if not session_store.get_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    title = req.title.strip()[:64]
    if not title:
        raise HTTPException(status_code=400, detail="会话标题不能为空")
    session_store.update_session(session_id, title=title)
    return session_store.get_session(session_id)
