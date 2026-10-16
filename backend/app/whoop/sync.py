"""WHOOP 数据同步：增量拉取 → 原始表 upsert → 重算分析层。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.pipeline import recompute_user
from app.config import get_settings
from app.models import BodyMeasurement, User, WhoopConnection
from app.whoop import client as wc
from app.whoop import ingest

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.utcnow()


def save_connection(db: Session, user: User, token: dict) -> WhoopConnection:
    conn = db.scalar(select(WhoopConnection).where(WhoopConnection.user_id == user.id))
    if conn is None:
        conn = WhoopConnection(user_id=user.id, access_token="")
        db.add(conn)
    conn.access_token = token["access_token"]
    conn.refresh_token = token.get("refresh_token") or conn.refresh_token
    conn.expires_at = wc.token_expiry(token)
    conn.scopes = token.get("scope")
    db.commit()
    return conn


def _ensure_token(db: Session, conn: WhoopConnection) -> str:
    if conn.expires_at and conn.expires_at > _utcnow() + timedelta(minutes=2):
        return conn.access_token
    if not conn.refresh_token:
        raise wc.WhoopAuthError("WHOOP 授权已过期，请重新连接")
    token = wc.refresh_token(conn.refresh_token)
    conn.access_token = token["access_token"]
    conn.refresh_token = token.get("refresh_token") or conn.refresh_token
    conn.expires_at = wc.token_expiry(token)
    db.commit()
    return conn.access_token


def sync_user(db: Session, user: User, full: bool = False) -> dict:
    conn = db.scalar(select(WhoopConnection).where(WhoopConnection.user_id == user.id))
    if conn is None:
        raise wc.WhoopAuthError("尚未连接 WHOOP")
    token = _ensure_token(db, conn)
    now = _utcnow()
    if full or conn.last_sync_at is None:
        start = now - timedelta(days=get_settings().whoop_initial_backfill_days)
    else:
        start = conn.last_sync_at - timedelta(days=3)  # 回看 3 天，覆盖延迟打分 / 修改过的数据

    counts = {"cycles": 0, "recoveries": 0, "sleeps": 0, "workouts": 0}
    try:
        with wc.WhoopClient(token) as api:
            if conn.whoop_user_id is None:
                profile = api.profile()
                conn.whoop_user_id = profile.get("user_id")
                if profile.get("first_name") and user.name in ("我", ""):
                    user.name = profile["first_name"]
            for rec in api.cycles(start=start):
                ingest.ingest_cycle(db, user.id, rec)
                counts["cycles"] += 1
            db.flush()
            for rec in api.recoveries(start=start):
                ingest.ingest_recovery(db, user.id, rec)
                counts["recoveries"] += 1
            for rec in api.sleeps(start=start):
                ingest.ingest_sleep(db, user.id, rec)
                counts["sleeps"] += 1
            for rec in api.workouts(start=start):
                ingest.ingest_workout(db, user.id, rec)
                counts["workouts"] += 1
            try:
                body = api.body_measurement()
                if body.get("weight_kilogram"):
                    today = datetime.now(ZoneInfo(user.timezone or "Asia/Shanghai")).date()
                    row = db.scalar(select(BodyMeasurement).where(BodyMeasurement.user_id == user.id, BodyMeasurement.date == today))
                    if row is None:
                        db.add(BodyMeasurement(user_id=user.id, date=today, weight_kg=body["weight_kilogram"],
                                               height_meter=body.get("height_meter"), max_heart_rate=body.get("max_heart_rate"),
                                               source="whoop"))
            except Exception as e:  # noqa: BLE001 体重不是核心数据，失败不影响同步
                log.warning("获取身体测量数据失败：%s", e)
        conn.last_sync_at = now
        conn.last_sync_status = "ok"
        user.is_demo = False
        db.commit()
    except Exception as e:
        db.rollback()
        conn.last_sync_status = f"error: {e}"[:250]
        db.commit()
        raise
    analysis = recompute_user(db, user)
    return {"fetched": counts, "since": start.isoformat(), "analysis": analysis}
