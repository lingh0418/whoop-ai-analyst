"""个性化上下文：长期记忆、训练计划、饮食计划、体重、用户设置。"""

import datetime as dt
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import anomaly
from app.analytics.pipeline import latest_date, recompute_user
from app.analytics.timeseries import load_daily_frame
from app.coaching import nutrition, training
from app.db import get_db
from app.deps import get_current_user
from app.memory import service as memory
from app.models import BodyMeasurement, Memory, NutritionPlan, TrainingPlan, User

router = APIRouter(prefix="/api", tags=["context"])


def _today(db: Session, user: User) -> date:
    return latest_date(db, user.id) or date.today()


# --------------------------------------------------------------------------- 记忆


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    event_date: date | None = None
    end_date: date | None = None
    category: str | None = None
    tags: list[str] | None = None
    importance: int = 2


@router.get("/memories")
def list_memories(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Memory).where(Memory.user_id == user.id, Memory.active.is_(True))
                      .order_by(Memory.event_date.desc(), Memory.id.desc()).limit(300))
    return [memory.to_dict(m) for m in rows]


@router.post("/memories")
def create_memory(body: MemoryIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = memory.add_memory(db, user.id, body.content, today=_today(db, user), category=body.category, tags=body.tags,
                          event_date=body.event_date, end_date=body.end_date, importance=body.importance)
    return memory.to_dict(m)


@router.delete("/memories/{mid}")
def delete_memory(mid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.get(Memory, mid)
    if m is None or m.user_id != user.id:
        raise HTTPException(404, "记忆不存在")
    m.active = False
    db.commit()
    return {"ok": True}


@router.get("/memories/tags")
def memory_tags():
    return [{"tag": k, "label": memory.TAG_LABEL[k], "category": v[0]} for k, v in memory.TAG_RULES.items()]


# --------------------------------------------------------------------------- 训练计划


class Exercise(BaseModel):
    name: str
    sets: int | None = None
    reps: str | None = None
    rpe: float | None = None
    weight: str | None = None


class TrainingIn(BaseModel):
    date: dt.date | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    title: str
    focus: str | None = None
    intensity: str = "moderate"
    exercises: list[Exercise] = []
    notes: str | None = None


@router.get("/training-plans")
def list_training(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(TrainingPlan).where(TrainingPlan.user_id == user.id).order_by(TrainingPlan.weekday, TrainingPlan.date))
    return [training.plan_to_dict(p) for p in rows]


@router.post("/training-plans")
def create_training(body: TrainingIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.date is None and body.weekday is None:
        raise HTTPException(400, "需要指定日期或星期")
    data = body.model_dump()
    data["exercises"] = [e.model_dump(exclude_none=True) for e in body.exercises]
    if body.weekday is not None and body.date is None:
        for old in db.scalars(select(TrainingPlan).where(TrainingPlan.user_id == user.id, TrainingPlan.weekday == body.weekday, TrainingPlan.date.is_(None))):
            db.delete(old)
    p = TrainingPlan(user_id=user.id, **data)
    db.add(p)
    db.commit()
    return training.plan_to_dict(p)


@router.put("/training-plans/{pid}")
def update_training(pid: int, body: TrainingIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(TrainingPlan, pid)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "计划不存在")
    data = body.model_dump()
    data["exercises"] = [e.model_dump(exclude_none=True) for e in body.exercises]
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    return training.plan_to_dict(p)


@router.delete("/training-plans/{pid}")
def delete_training(pid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(TrainingPlan, pid)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "计划不存在")
    db.delete(p)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- 饮食计划


class NutritionIn(BaseModel):
    date: dt.date | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    day_type: str = "normal"
    goal: str = "maintain"
    calories: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None
    notes: str | None = None


@router.get("/nutrition-plans")
def list_nutrition(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(NutritionPlan).where(NutritionPlan.user_id == user.id).order_by(NutritionPlan.weekday, NutritionPlan.date))
    return [nutrition.plan_to_dict(p) for p in rows]


@router.post("/nutrition-plans")
def create_nutrition(body: NutritionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.date is None and body.weekday is None:
        raise HTTPException(400, "需要指定日期或星期")
    if body.weekday is not None and body.date is None:
        for old in db.scalars(select(NutritionPlan).where(NutritionPlan.user_id == user.id, NutritionPlan.weekday == body.weekday, NutritionPlan.date.is_(None))):
            db.delete(old)
    p = NutritionPlan(user_id=user.id, **body.model_dump())
    db.add(p)
    db.commit()
    return nutrition.plan_to_dict(p)


@router.put("/nutrition-plans/{pid}")
def update_nutrition(pid: int, body: NutritionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(NutritionPlan, pid)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "计划不存在")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return nutrition.plan_to_dict(p)


@router.delete("/nutrition-plans/{pid}")
def delete_nutrition(pid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(NutritionPlan, pid)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "计划不存在")
    db.delete(p)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- 体重


class WeightIn(BaseModel):
    date: dt.date
    weight_kg: float = Field(gt=20, lt=300)


@router.post("/body/weight")
def add_weight(body: WeightIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.scalar(select(BodyMeasurement).where(BodyMeasurement.user_id == user.id, BodyMeasurement.date == body.date))
    if row is None:
        row = BodyMeasurement(user_id=user.id, date=body.date, source="manual")
        db.add(row)
    row.weight_kg = body.weight_kg
    db.commit()
    recompute_user(db, user)
    return {"ok": True}


# --------------------------------------------------------------------------- 设置


class SettingsIn(BaseModel):
    name: str | None = None
    timezone: str | None = None
    profile: dict | None = None
    anomaly_rules: dict | None = None


@router.get("/settings")
def get_settings_(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "name": user.name,
        "timezone": user.timezone,
        "profile": user.profile or {},
        "anomaly_rules": anomaly.load_rules(user.settings),
        "anomaly_overrides": (user.settings or {}).get("anomaly_rules", {}),
    }


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.name is not None:
        user.name = body.name
    if body.timezone is not None:
        user.timezone = body.timezone
    if body.profile is not None:
        user.profile = body.profile
    recompute = False
    if body.anomaly_rules is not None:
        user.settings = {**(user.settings or {}), "anomaly_rules": body.anomaly_rules}
        recompute = True
    db.commit()
    result = recompute_user(db, user) if recompute else None
    return {"ok": True, "recomputed": result}


@router.get("/settings/threshold-suggestions")
def threshold_suggestions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    df = load_daily_frame(db, user.id)
    if df.empty:
        return {}
    return anomaly.suggest_thresholds(df, anomaly.load_rules(user.settings))
