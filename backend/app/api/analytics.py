from datetime import timedelta

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import stats as st
from app.analytics.analysis import analyze_metric, history
from app.analytics.drivers import recovery_drivers
from app.analytics.metrics import METRICS, resolve_metric
from app.analytics.similar import find_similar_days
from app.analytics.timeseries import load_daily_frame
from app.db import get_db
from app.deps import get_current_user
from app.models import LearnedPattern, MetricAnomaly, User, WhoopWorkout
from app.reports.daily import anomaly_to_dict, pattern_to_dict

router = APIRouter(prefix="/api", tags=["analytics"])

TREND_METRICS = ["hrv", "rhr", "recovery", "sleep_duration", "sleep_performance", "strain", "deep_sleep", "rem_sleep",
                 "sleep_debt", "sleep_consistency", "resp_rate", "skin_temp", "weight", "workout_minutes"]


def _frame(db: Session, user: User) -> pd.DataFrame:
    df = load_daily_frame(db, user.id)
    if df.empty:
        raise HTTPException(404, "暂无数据")
    return df


@router.get("/metrics")
def metric_list():
    return [{"key": k, "label": METRICS[k].label, "unit": METRICS[k].unit, "direction": METRICS[k].direction} for k in TREND_METRICS]


@router.get("/trends")
def trends(metric: str = "hrv", days: int = 28, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        metric = resolve_metric(metric)
    except KeyError as e:
        raise HTTPException(400, str(e)) from e
    days = max(7, min(days, 365))
    df = _frame(db, user)
    h = history(df, metric, days)
    a = analyze_metric(df, metric)
    since = df.index.max().date() - timedelta(days=days - 1)
    anomalies = [
        anomaly_to_dict(x)
        for x in db.scalars(
            select(MetricAnomaly).where(MetricAnomaly.user_id == user.id, MetricAnomaly.date >= since,
                                        MetricAnomaly.metric == metric, MetricAnomaly.severity != "low")
        )
    ]
    sl = st.slope(df[metric].astype(float).iloc[-days:])
    return {**h, "analysis": a, "anomalies": anomalies,
            "period_trend": {"direction": sl.direction, "pct_per_week": st.r(sl.pct_per_week, 4), "p_value": st.r(sl.p_value, 4)}}


@router.get("/trends/overview")
def trends_overview(days: int = 28, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    df = _frame(db, user)
    out = []
    for m in ("recovery", "hrv", "rhr", "sleep_duration", "strain"):
        a = analyze_metric(df, m)
        s = df[m].astype(float).iloc[-days:]
        out.append({
            "metric": m, "label": METRICS[m].label, "unit": METRICS[m].unit,
            "value_text": a.get("value_text"), "avg": st.r(s.mean()), "baseline_28d": a.get("baseline_28d"),
            "deviation_pct_28d": a.get("deviation_pct_28d"), "trend": (a.get("trend_28d") or {}).get("label"),
            "points": [{"date": d.date().isoformat(), "value": st.r(v)} for d, v in s.items()],
        })
    return out


@router.get("/workouts")
def workouts(days: int = 28, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    df = _frame(db, user)
    since = df.index.max().date() - timedelta(days=days - 1)
    rows = db.scalars(select(WhoopWorkout).where(WhoopWorkout.user_id == user.id, WhoopWorkout.date >= since).order_by(WhoopWorkout.start.desc()))
    items = []
    for w in rows:
        zones = [w.zone_zero_milli, w.zone_one_milli, w.zone_two_milli, w.zone_three_milli, w.zone_four_milli, w.zone_five_milli]
        items.append({
            "id": w.id, "date": w.date.isoformat(), "sport": w.sport_name, "minutes": round((w.end - w.start).total_seconds() / 60),
            "strain": st.r(w.strain, 1), "avg_hr": w.average_heart_rate, "max_hr": w.max_heart_rate,
            "kilojoule": st.r(w.kilojoule, 0), "distance_km": st.r((w.distance_meter or 0) / 1000, 2) if w.distance_meter else None,
            "zone_minutes": [round((z or 0) / 60000) for z in zones],
        })
    return {"days": days, "items": items}


@router.get("/anomalies")
def anomalies(days: int = 30, include_low: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    df = _frame(db, user)
    since = df.index.max().date() - timedelta(days=days - 1)
    q = select(MetricAnomaly).where(MetricAnomaly.user_id == user.id, MetricAnomaly.date >= since)
    if not include_low:
        q = q.where(MetricAnomaly.severity != "low")
    return [anomaly_to_dict(a) for a in db.scalars(q.order_by(MetricAnomaly.date.desc()))]


@router.get("/patterns")
def patterns(include_inactive: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(LearnedPattern).where(LearnedPattern.user_id == user.id)
    if not include_inactive:
        q = q.where(LearnedPattern.active.is_(True))
    order = {"high": 0, "medium": 1, "low": 2}
    items = [pattern_to_dict(p) for p in db.scalars(q)]
    items.sort(key=lambda p: (order.get(p["confidence"], 3), -abs(p["effect"])))
    return items


@router.get("/drivers")
def drivers(days: int = 120, outcome: str = "recovery", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return recovery_drivers(_frame(db, user), days, resolve_metric(outcome))


@router.get("/similar")
def similar(day: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    df = _frame(db, user)
    return find_similar_days(df, pd.Timestamp(day) if day else df.index.max())
