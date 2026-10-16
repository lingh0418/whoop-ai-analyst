"""分析流水线：原始 WHOOP 数据 → daily_metrics → 个人基线 → 异常 → 联合状态 → 个人规律。

任何时候都可以从原始表完整重算（幂等）。
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics import anomaly, joint, patterns
from app.analytics.analysis import baseline_frame, deviation_series
from app.analytics.metrics import BASELINE_METRICS, WINDOWS
from app.analytics.readiness import readiness_series
from app.analytics.stats import clean
from app.analytics.timeseries import DAILY_COLUMNS, build_raw_daily_frame
from app.memory import service as memory
from app.models import (
    DailyMetric,
    DailyReport,
    LearnedPattern,
    MetricAnomaly,
    MetricBaseline,
    User,
    WeeklyReport,
)

log = logging.getLogger(__name__)

# 只给最近这么多天逐日计算联合状态（更早的日子用于基线即可）
JOINT_STATE_DAYS = 180


def enrich(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """在原始日数据上加上偏差、身体状态分、联合状态。"""
    df = df.copy()
    df["hrv_deviation_28d"] = deviation_series(df["hrv"], 28)
    df["rhr_deviation_28d"] = deviation_series(df["rhr"], 28)
    df["sleep_deviation_28d"] = deviation_series(df["sleep_duration"], 28)
    df["recovery_deviation_28d"] = deviation_series(df["recovery"], 28)
    df["strain_deviation_28d"] = deviation_series(df["strain"], 28)
    rd = readiness_series(df)
    df["readiness_score"] = rd["score"]
    df["readiness_level"] = rd["level"]
    df["joint_state"] = None
    flags = anomaly.signal_flags(df, rules)
    days = [d for d in df.index[-JOINT_STATE_DAYS:] if not pd.isna(df.at[d, "hrv"])]
    for d in days:
        df.at[d, "joint_state"] = joint.assess(df, d, rules, flags=flags)["state"]
    return df


def recompute_user(db: Session, user: User) -> dict:
    t0 = time.time()
    raw = build_raw_daily_frame(db, user.id)
    if raw.empty:
        return {"days": 0}
    rules = anomaly.load_rules(user.settings)
    df = enrich(raw, rules)

    # ---- daily_metrics
    db.execute(delete(DailyMetric).where(DailyMetric.user_id == user.id))
    rows = []
    for d, rec in df.iterrows():
        if rec[["recovery", "hrv", "sleep_duration", "strain"]].isna().all():
            continue
        item = {c: (clean(rec[c]) if c not in {"readiness_level", "joint_state"} else rec[c]) for c in DAILY_COLUMNS}
        for c in ("workout_count",):
            if item[c] is not None:
                item[c] = int(item[c])
        rows.append(DailyMetric(user_id=user.id, date=d.date(), **item))
    db.add_all(rows)

    # ---- metric_baselines（每天、每指标、每窗口）
    db.execute(delete(MetricBaseline).where(MetricBaseline.user_id == user.id))
    base_rows = []
    for metric in BASELINE_METRICS:
        if metric not in df or df[metric].notna().sum() == 0:
            continue
        for w in WINDOWS:
            bf = baseline_frame(df[metric].astype(float), w).dropna(subset=["mean"])
            for d, b in bf.iterrows():
                base_rows.append(
                    MetricBaseline(
                        user_id=user.id, metric=metric, window=w, as_of_date=d.date(),
                        mean=clean(b["mean"]), median=clean(b["median"]), std=clean(b["std"]),
                        p10=clean(b["p10"]), p90=clean(b["p90"]), n=int(b["n"]),
                    )
                )
    db.add_all(base_rows)

    # ---- metric_anomalies
    db.execute(delete(MetricAnomaly).where(MetricAnomaly.user_id == user.id))
    events = anomaly.detect(df, rules)
    db.add_all(MetricAnomaly(user_id=user.id, **e) for e in events)

    # ---- learned_patterns（保留首次发现日期）
    today = df.index.max().date()
    found = patterns.mine_patterns(df, memory.events_for_patterns(db, user.id))
    existing = {p.key: p for p in db.scalars(select(LearnedPattern).where(LearnedPattern.user_id == user.id))}
    seen = set()
    # 首次挖掘（刚导入历史数据）时发现的规律视为“已有规律”，不在周报里算作本周新发现
    first_seen = df.index.min().date() if not existing else today
    for p in found:
        seen.add(p.key)
        row = existing.get(p.key)
        fields = {k: getattr(p, k) for k in p.__dataclass_fields__ if k != "key"}
        if row is None:
            db.add(LearnedPattern(user_id=user.id, key=p.key, active=True, first_detected=first_seen,
                                  last_updated=today, **fields))
        else:
            for k, v in fields.items():
                setattr(row, k, v)
            if not row.active:
                row.first_detected = today
            row.active = True
            row.last_updated = today
    for key, row in existing.items():
        if key not in seen:
            row.active = False

    # 数据变化后，最近的日报 / 本周周报需要重新生成
    db.execute(delete(DailyReport).where(DailyReport.user_id == user.id, DailyReport.date >= today - timedelta(days=3)))
    db.execute(delete(WeeklyReport).where(WeeklyReport.user_id == user.id, WeeklyReport.week_start >= today - timedelta(days=13)))
    db.commit()
    elapsed = time.time() - t0
    log.info("用户 %s 重算完成：%s 天，%s 个异常，%s 条规律，用时 %.1fs", user.id, len(rows), len(events), len(found), elapsed)
    return {
        "days": len(rows),
        "start": df.index.min().date().isoformat(),
        "end": today.isoformat(),
        "anomalies": len(events),
        "patterns": len(found),
        "seconds": round(elapsed, 2),
    }


def latest_date(db: Session, user_id: int) -> date | None:
    return db.scalar(
        select(DailyMetric.date).where(DailyMetric.user_id == user_id).order_by(DailyMetric.date.desc()).limit(1)
    )
