from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.orchestrator import run_turn
from app.auth import current_user
from app.clock import now
from app.db import SessionLocal, get_db
from app.models import ChatSession, User

router = APIRouter(prefix="/api/chat")


def _own(db: Session, sid: int, user: User) -> ChatSession:
    s = db.get(ChatSession, sid)
    if not s or s.username != user.username:
        raise HTTPException(404, "Không tìm thấy hội thoại")
    return s


@router.get("/sessions")
def sessions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(ChatSession).where(ChatSession.username == user.username)
                      .order_by(ChatSession.id.desc()).limit(50))
    return [{"id": s.id, "title": s.title, "created_at": s.created_at.isoformat()} for s in rows]


class NewSession(BaseModel):
    title: str | None = None


@router.post("/sessions")
def new_session(body: NewSession, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = ChatSession(title=body.title or "Hội thoại mới", username=user.username, created_at=now().replace(tzinfo=None))
    db.add(s)
    db.commit()
    return {"id": s.id, "title": s.title}


@router.get("/sessions/{sid}")
def get_session(sid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = _own(db, sid, user)
    return {"id": s.id, "title": s.title, "messages": [
        {"id": m.id, "role": m.role, "content": m.content if m.role != "tool" else None, "name": m.name,
         "tool_calls": [{"id": tc["id"], "name": tc["function"]["name"],
                         "args": tc["function"]["arguments"]} for tc in (m.tool_calls or [])],
         "tool_call_id": m.tool_call_id, "ui_events": m.ui_events or [], "created_at": m.created_at.isoformat()}
        for m in s.messages]}


@router.delete("/sessions/{sid}")
def delete_session(sid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = _own(db, sid, user)
    db.delete(s)
    db.commit()
    return {"ok": True}


class MessageIn(BaseModel):
    text: str


@router.post("/sessions/{sid}/messages")
def send(sid: int, body: MessageIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = _own(db, sid, user)
    if not body.text.strip():
        raise HTTPException(422, "Tin nhắn trống")
    if s.title == "Hội thoại mới":
        s.title = body.text.strip()[:60]
        db.commit()
    username = user.username

    def stream():
        # Session DB rieng cho generator (chay sau khi request handler tra ve)
        sdb = SessionLocal()
        try:
            sess = sdb.get(ChatSession, sid)
            u = sdb.scalar(select(User).where(User.username == username))
            for ev in run_turn(sdb, sess, u, body.text.strip()):
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        finally:
            sdb.close()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
