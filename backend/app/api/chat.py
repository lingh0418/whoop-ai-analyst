from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.agent import chat, message_to_dict
from app.db import get_db
from app.deps import get_current_user
from app.models import Conversation, User

router = APIRouter(prefix="/api", tags=["chat"])

SUGGESTED = [
    "为什么我今天 Recovery 这么低？",
    "为什么我的 HRV 最近一直下降？",
    "最近一个月恢复怎么样？",
    "我的 RHR 最近有没有问题？",
    "为什么这周睡眠很好但 Recovery 还是低？",
    "我最近是不是训练负荷太高？",
    "过去3个月我的 HRV 是变好了还是变差了？",
    "什么情况下我的 Recovery 通常最好？",
    "这种情况以前出现过吗？",
    "今天的训练要怎么调整？",
]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None


@router.post("/chat")
def post_chat(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return chat(db, user, req.message, req.conversation_id)


@router.get("/chat/suggestions")
def suggestions():
    return SUGGESTED


@router.get("/conversations")
def conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(50))
    return [{"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat() if c.updated_at else None} for c in rows]


@router.get("/conversations/{cid}")
def conversation(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Conversation, cid)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "对话不存在")
    return {"id": c.id, "title": c.title, "messages": [message_to_dict(m) for m in c.messages]}


@router.delete("/conversations/{cid}")
def delete_conversation(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Conversation, cid)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "对话不存在")
    db.delete(c)
    db.commit()
    return {"ok": True}
