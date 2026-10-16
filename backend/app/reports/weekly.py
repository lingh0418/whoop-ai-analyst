"""WHOOP 周报：本周 vs 上周 vs 个人基线，以及本周新发现的个人规律。"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import stats as st
from app.analytics.joint import STATES
from app.analytics.metrics import fmt_minutes
from app.analytics.timeseries import load_daily_frame
from app.models import LearnedPattern, MetricAnomaly, User, WeeklyReport
from app.reports.daily import pattern_to_dict


def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _avg(s: pd.Series) -> float | None:
    return st.r(s.mean(), 2) if s.notna().any() else None


def _cmp(this: float | None, last: float | None) -> dict:
    return {
        "this_week": this,
        "last_week": last,
        "change": st.r(this - last, 2) if this is not None and last is not None else None,
        "change_pct": st.r(st.pct_change(this, last), 4),
    }


def build_weekly_payload(db: Session, user: User, week_start: date) -> dict:
    df = load_daily_frame(db, user.id)
    if df.empty:
        return {"available": False, "reason": "暂无数据"}
    ws, we = pd.Timestamp(week_start), pd.Timestamp(week_start + timedelta(days=6))
    this = df.loc[ws:we]
    last = df.loc[ws - timedelta(days=7): ws - timedelta(days=1)]
    if this["hrv"].notna().sum() == 0:
        return {"available": False, "reason": "这一周没有数据"}
    end = min(we, df.index.max())
    # 本周之前的 28 日基线
    base = df.loc[ws - timedelta(days=28): ws - timedelta(days=1)]

    hrv_slope = st.slope(df["hrv"].loc[:end].iloc[-28:])
    rec = _cmp(_avg(this["recovery"]), _avg(last["recovery"]))
    hrv = {
        **_cmp(_avg(this["hrv"]), _avg(last["hrv"])),
        "baseline_28d": _avg(base["hrv"]),
        "vs_baseline_pct": st.r(st.pct_change(_avg(this["hrv"]), _avg(base["hrv"])), 4),
        "trend_28d": hrv_slope.direction,
        "trend_pct_per_week": st.r(hrv_slope.pct_per_week, 4),
    }
    rhr = {**_cmp(_avg(this["rhr"]), _avg(last["rhr"])), "baseline_28d": _avg(base["rhr"])}
    sleep = {
        **_cmp(_avg(this["sleep_duration"]), _avg(last["sleep_duration"])),
        "baseline_28d": _avg(base["sleep_duration"]),
        "consistency": _avg(this["sleep_consistency"]),
        "performance": _avg(this["sleep_performance"]),
        "nights_under_7h": int((this["sleep_duration"] < 420).sum()),
        "nights": int(this["sleep_duration"].notna().sum()),
    }
    strain = {
        **_cmp(_avg(this["strain"]), _avg(last["strain"])),
        "workouts": int(this["workout_count"].fillna(0).sum()),
        "workouts_last_week": int(last["workout_count"].fillna(0).sum()),
        "workout_minutes": st.r(this["workout_minutes"].fillna(0).sum(), 0),
        "high_strain_days": int((this["strain"] >= 15).sum()),
    }
    readiness = _cmp(_avg(this["readiness_score"]), _avg(last["readiness_score"]))
    states = Counter(s for s in this["joint_state"].dropna().tolist())
    state_dist = [{"state": k, "label": STATES.get(k, (k, 0))[0], "days": v} for k, v in states.most_common()]

    best = this["readiness_score"].idxmax() if this["readiness_score"].notna().any() else None
    worst = this["readiness_score"].idxmin() if this["readiness_score"].notna().any() else None

    anomalies = list(
        db.scalars(
            select(MetricAnomaly).where(
                MetricAnomaly.user_id == user.id, MetricAnomaly.date >= week_start,
                MetricAnomaly.date <= week_start + timedelta(days=6), MetricAnomaly.severity != "low",
            )
        )
    )
    anomaly_counts = Counter((a.details or {}).get("label", a.rule) for a in anomalies)
    new_patterns = [
        pattern_to_dict(p)
        for p in db.scalars(
            select(LearnedPattern).where(
                LearnedPattern.user_id == user.id, LearnedPattern.active.is_(True),
                LearnedPattern.first_detected >= week_start,
                LearnedPattern.first_detected <= week_start + timedelta(days=6),
            )
        )
    ]

    payload = {
        "available": True,
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "days_with_data": int(this["hrv"].notna().sum()),
        "recovery": rec,
        "hrv": hrv,
        "rhr": rhr,
        "sleep": sleep,
        "strain": strain,
        "readiness": readiness,
        "state_distribution": state_dist,
        "best_day": {"date": best.date().isoformat(), "score": st.r(this.at[best, "readiness_score"], 0)} if best is not None else None,
        "worst_day": {"date": worst.date().isoformat(), "score": st.r(this.at[worst, "readiness_score"], 0)} if worst is not None else None,
        "anomalies": [{"label": k, "count": v} for k, v in anomaly_counts.most_common()],
        "new_patterns": new_patterns,
        "daily": [
            {
                "date": d.date().isoformat(),
                "recovery": st.r(r["recovery"], 0),
                "hrv": st.r(r["hrv"], 1),
                "rhr": st.r(r["rhr"], 0),
                "sleep": st.r(r["sleep_duration"], 0),
                "strain": st.r(r["strain"], 1),
                "readiness": st.r(r["readiness_score"], 0),
                "state": r["joint_state"],
            }
            for d, r in this.iterrows()
        ],
    }
    payload["narrative"] = render_weekly_narrative(payload)
    return payload


def _chg(v: float | None, unit: str = "", nd: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v:+.{nd}f}{unit}"


def render_weekly_narrative(p: dict) -> str:
    rec, hrv, rhr, sleep, strain = p["recovery"], p["hrv"], p["rhr"], p["sleep"], p["strain"]
    lines = [f"## WHOOP 周报 {p['week_start']} ~ {p['week_end']}", ""]
    r0 = lambda v: "—" if v is None else f"{v:.0f}"  # noqa: E731
    lines.append(f"- **Recovery**：本周平均 {r0(rec['this_week'])}%，上周 {r0(rec['last_week'])}%（{_chg(rec['change'], ' 个百分点', 0)}）")
    if hrv["this_week"] is not None:
        vs = f"，比本周之前 28 日基线 {hrv['baseline_28d']:.1f} ms {(hrv['vs_baseline_pct'] or 0) * 100:+.1f}%" if hrv.get("baseline_28d") else ""
        trend = {"up": "上升", "down": "下降", "flat": "平稳"}[hrv["trend_28d"]]
        lines.append(f"- **HRV**：本周平均 {hrv['this_week']:.1f} ms{vs}；近 28 天趋势：{trend}")
    if rhr["this_week"] is not None:
        lines.append(f"- **静息心率**：本周平均 {rhr['this_week']:.1f} bpm（较上周 {_chg(rhr['change'], ' bpm')}）")
    if sleep["this_week"] is not None:
        lines.append(
            f"- **睡眠**：平均 {fmt_minutes(sleep['this_week'])}（较上周 {_chg(sleep['change'], ' 分钟', 0)}），"
            f"一致性 {'—' if sleep['consistency'] is None else format(sleep['consistency'], '.0f')}%，{sleep['nights_under_7h']}/{sleep['nights']} 晚少于 7 小时"
        )
    if strain["this_week"] is not None:
        lines.append(
            f"- **Strain**：平均 {strain['this_week']:.1f}（上周 {'—' if strain['last_week'] is None else format(strain['last_week'], '.1f')}），"
            f"训练 {strain['workouts']} 次 / {strain['workout_minutes'] or 0:.0f} 分钟，高负荷日 {strain['high_strain_days']} 天"
        )
    lines.append("")
    # 整体总结（规则）
    summary = []
    if rec["change"] is not None:
        if rec["change"] <= -8:
            summary.append("本周整体恢复明显低于上周")
        elif rec["change"] >= 8:
            summary.append("本周整体恢复明显好于上周")
        else:
            summary.append("本周整体恢复与上周接近")
    if hrv.get("vs_baseline_pct") is not None and hrv["vs_baseline_pct"] <= -0.05:
        summary.append("HRV 周均值低于个人基线")
    if sleep["nights"] and sleep["nights_under_7h"] >= max(3, sleep["nights"] // 2):
        summary.append("睡眠不足的夜晚偏多")
    if strain["change"] is not None and strain["change"] >= 1.5:
        summary.append("训练负荷较上周明显增加")
    if summary:
        lines.append("**本周总结**：" + "；".join(summary) + "。")
    if p["state_distribution"]:
        dist = "、".join(f"{s['label']} {s['days']} 天" for s in p["state_distribution"][:4])
        lines.append(f"状态分布：{dist}。")
    if p["new_patterns"]:
        lines.append("")
        lines.append("### 本周新发现的个人规律")
        for pt in p["new_patterns"]:
            lines.append(f"- {pt['title']}（样本 {pt['sample_size']} 天，置信度 {pt['confidence']}）")
    return "\n".join(lines)


def get_weekly_report(db: Session, user: User, week_start: date, refresh: bool = False) -> dict:
    cached = db.scalar(select(WeeklyReport).where(WeeklyReport.user_id == user.id, WeeklyReport.week_start == week_start))
    if cached and not refresh:
        return {**cached.payload, "ai_summary": cached.ai_summary}
    payload = build_weekly_payload(db, user, week_start)
    if not payload.get("available"):
        return payload
    if cached is None:
        cached = WeeklyReport(user_id=user.id, week_start=week_start, payload=payload, narrative=payload["narrative"])
        db.add(cached)
    else:
        cached.payload, cached.narrative, cached.ai_summary = payload, payload["narrative"], None
    db.commit()
    return {**payload, "ai_summary": cached.ai_summary}


def save_ai_summary(db: Session, user: User, week_start: date, text: str) -> None:
    cached = db.scalar(select(WeeklyReport).where(WeeklyReport.user_id == user.id, WeeklyReport.week_start == week_start))
    if cached:
        cached.ai_summary = text
        db.commit()
