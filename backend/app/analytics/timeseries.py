"""原始 WHOOP 数据 → 按天对齐的时间序列。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BodyMeasurement,
    DailyMetric,
    WhoopCycle,
    WhoopRecovery,
    WhoopSleep,
    WhoopWorkout,
)
from app.whoop.ingest import local

MS_PER_MIN = 60_000

DAILY_COLUMNS = [
    c.name for c in DailyMetric.__table__.columns if c.name not in {"id", "user_id", "date"}
]
DERIVED_COLUMNS = {
    "hrv_deviation_28d",
    "rhr_deviation_28d",
    "sleep_deviation_28d",
    "recovery_deviation_28d",
    "strain_deviation_28d",
    "readiness_score",
    "readiness_level",
    "joint_state",
}
RAW_COLUMNS = [c for c in DAILY_COLUMNS if c not in DERIVED_COLUMNS]


def _ms(v) -> float | None:
    return None if v is None else v / MS_PER_MIN


def _bedtime_hours(local_start) -> float:
    """入睡时刻表示为“距前一个中午 12:00 的小时数”，便于跨午夜比较（23:30 → 11.5，01:00 → 13）。"""
    noon = local_start.replace(hour=12, minute=0, second=0, microsecond=0)
    if local_start.hour < 12:
        noon -= timedelta(days=1)
    return (local_start - noon).total_seconds() / 3600


def build_raw_daily_frame(db: Session, user_id: int) -> pd.DataFrame:
    """从原始表汇总出每日一行的基础指标（不含衍生偏差）。"""
    rows: dict[date, dict] = {}

    def row(d: date) -> dict:
        return rows.setdefault(d, {})

    for rec in db.scalars(
        select(WhoopRecovery).where(WhoopRecovery.user_id == user_id, WhoopRecovery.score_state == "SCORED")
    ):
        r = row(rec.date)
        r.update(
            recovery=rec.recovery_score,
            hrv=rec.hrv_rmssd_milli,
            rhr=rec.resting_heart_rate,
            spo2=rec.spo2_percentage,
            skin_temp=rec.skin_temp_celsius,
        )

    sleeps = list(
        db.scalars(select(WhoopSleep).where(WhoopSleep.user_id == user_id, WhoopSleep.score_state == "SCORED"))
    )
    main_by_date: dict[date, list[WhoopSleep]] = {}
    for s in sleeps:
        if s.nap:
            r = row(s.date)
            asleep = sum(
                _ms(x) or 0
                for x in (s.total_light_sleep_milli, s.total_slow_wave_sleep_milli, s.total_rem_sleep_milli)
            )
            r["nap_minutes"] = (r.get("nap_minutes") or 0) + asleep
        else:
            main_by_date.setdefault(s.date, []).append(s)

    for d, group in main_by_date.items():
        primary = max(group, key=lambda s: s.total_in_bed_milli or 0)
        r = row(d)
        light = sum(_ms(s.total_light_sleep_milli) or 0 for s in group)
        deep = sum(_ms(s.total_slow_wave_sleep_milli) or 0 for s in group)
        rem = sum(_ms(s.total_rem_sleep_milli) or 0 for s in group)
        need_parts = [
            primary.need_baseline_milli,
            primary.need_from_sleep_debt_milli,
            primary.need_from_recent_strain_milli,
            primary.need_from_recent_nap_milli,
        ]
        r.update(
            sleep_duration=light + deep + rem,
            light_sleep=light,
            deep_sleep=deep,
            rem_sleep=rem,
            time_in_bed=sum(_ms(s.total_in_bed_milli) or 0 for s in group),
            awake_time=sum(_ms(s.total_awake_milli) or 0 for s in group),
            disturbances=sum(s.disturbance_count or 0 for s in group),
            sleep_need=sum(_ms(x) or 0 for x in need_parts) if primary.need_baseline_milli else None,
            sleep_debt=_ms(primary.need_from_sleep_debt_milli),
            sleep_performance=primary.sleep_performance_percentage,
            sleep_consistency=primary.sleep_consistency_percentage,
            sleep_efficiency=primary.sleep_efficiency_percentage,
            resp_rate=primary.respiratory_rate,
            bedtime=_bedtime_hours(local(min(s.start for s in group), primary.timezone_offset)),
        )

    for c in db.scalars(select(WhoopCycle).where(WhoopCycle.user_id == user_id)):
        if c.strain is None:
            continue
        r = row(c.date)
        if r.get("strain") is None or c.strain > r["strain"]:
            r.update(strain=c.strain, kilojoule=c.kilojoule, day_avg_hr=c.average_heart_rate)

    for w in db.scalars(
        select(WhoopWorkout).where(WhoopWorkout.user_id == user_id, WhoopWorkout.score_state == "SCORED")
    ):
        r = row(w.date)
        r["workout_count"] = (r.get("workout_count") or 0) + 1
        r["workout_minutes"] = (r.get("workout_minutes") or 0) + (w.end - w.start).total_seconds() / 60
        if w.strain is not None:
            r["workout_strain"] = max(r.get("workout_strain") or 0, w.strain)

    for b in db.scalars(select(BodyMeasurement).where(BodyMeasurement.user_id == user_id)):
        if b.weight_kg:
            row(b.date)["weight"] = b.weight_kg

    if not rows:
        return pd.DataFrame(columns=RAW_COLUMNS, dtype=float)

    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    full = pd.date_range(df.index.min(), df.index.max(), freq="D")
    df = df.reindex(full)
    # 有睡眠/恢复数据但没有训练记录的日子，训练次数为 0
    has_day = df[["strain"]].notna().any(axis=1) if "strain" in df else pd.Series(False, index=df.index)
    for col in ("workout_count", "workout_minutes"):
        if col not in df:
            df[col] = None
        df.loc[has_day & df[col].isna(), col] = 0
    for col in RAW_COLUMNS:
        if col not in df:
            df[col] = None
    return df[RAW_COLUMNS].astype(float)


def load_daily_frame(db: Session, user_id: int, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """读取已计算好的 daily_metrics，返回连续日期索引的 DataFrame。"""
    q = select(DailyMetric).where(DailyMetric.user_id == user_id)
    if start:
        q = q.where(DailyMetric.date >= start)
    if end:
        q = q.where(DailyMetric.date <= end)
    items = list(db.scalars(q.order_by(DailyMetric.date)))
    if not items:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    data = {
        pd.Timestamp(m.date): {c: getattr(m, c) for c in DAILY_COLUMNS} for m in items
    }
    df = pd.DataFrame.from_dict(data, orient="index").sort_index()
    full = pd.date_range(df.index.min(), df.index.max(), freq="D")
    df = df.reindex(full)
    numeric = [c for c in DAILY_COLUMNS if c not in {"readiness_level", "joint_state"}]
    df[numeric] = df[numeric].astype(float)
    return df
