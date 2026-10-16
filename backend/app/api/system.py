from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.llm import provider_info
from app.analytics.pipeline import latest_date, recompute_user
from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.demo.generator import generate
from app.models import DailyMetric, User, WhoopConnection

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/status")
def status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = get_settings()
    conn = db.scalar(select(WhoopConnection).where(WhoopConnection.user_id == user.id))
    days = db.scalar(select(func.count()).select_from(DailyMetric).where(DailyMetric.user_id == user.id)) or 0
    first = db.scalar(select(func.min(DailyMetric.date)).where(DailyMetric.user_id == user.id))
    last = latest_date(db, user.id)
    return {
        "user": {"id": user.id, "name": user.name, "is_demo": user.is_demo, "profile": user.profile or {}},
        "data": {"days": days, "start": first.isoformat() if first else None, "end": last.isoformat() if last else None},
        "whoop": {
            "configured": bool(s.whoop_client_id and s.whoop_client_secret),
            "connected": conn is not None,
            "last_sync_at": conn.last_sync_at.isoformat() if conn and conn.last_sync_at else None,
            "last_sync_status": conn.last_sync_status if conn else None,
        },
        "llm": provider_info(),
    }


class DemoRequest(BaseModel):
    days: int = 200


@router.post("/demo/seed")
def seed_demo(req: DemoRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    info = generate(db, user, days=max(60, min(req.days, 400)))
    analysis = recompute_user(db, user)
    return {"demo": info, "analysis": analysis}


@router.post("/recompute")
def recompute(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return recompute_user(db, user)
