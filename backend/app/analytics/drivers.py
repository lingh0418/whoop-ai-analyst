"""“什么情况下我的 Recovery 通常最好？” —— 对比恢复最好与最差的日子各自的前置条件。"""

from __future__ import annotations

import pandas as pd
from scipy import stats as sps

from app.analytics import stats as st
from app.analytics.metrics import fmt_bedtime, fmt_minutes

FACTORS = {
    "sleep_duration": ("前一晚睡眠时长", lambda df: df["sleep_duration"], "min"),
    "bedtime": ("入睡时间", lambda df: df["bedtime"], "bedtime"),
    "sleep_consistency": ("睡眠一致性", lambda df: df["sleep_consistency"], "%"),
    "deep_sleep": ("深睡时长", lambda df: df["deep_sleep"], "min"),
    "strain_prev": ("前一天 Strain", lambda df: df["strain"].shift(1), ""),
    "strain_prev3": ("前 3 天平均 Strain", lambda df: df["strain"].shift(1).rolling(3, min_periods=2).mean(), ""),
    "workout_prev": ("前一天训练次数", lambda df: df["workout_count"].shift(1), "次"),
}


def _fmt(unit: str, v: float | None) -> str:
    if v is None:
        return "—"
    if unit == "min":
        return fmt_minutes(v)
    if unit == "bedtime":
        return fmt_bedtime(v)
    if unit == "%":
        return f"{v:.0f}%"
    return f"{v:.1f}{unit}"


def recovery_drivers(df: pd.DataFrame, days: int = 120, outcome: str = "recovery") -> dict:
    data = df.iloc[-days:]
    y = data[outcome].astype(float)
    if y.notna().sum() < 20:
        return {"available": False, "reason": "数据少于 20 天"}
    q_hi, q_lo = y.quantile(0.75), y.quantile(0.25)
    top, bottom = y >= q_hi, y <= q_lo
    rows = []
    for key, (label, fn, unit) in FACTORS.items():
        x = fn(df).reindex(data.index).astype(float)
        mask = x.notna() & y.notna()
        if mask.sum() < 15:
            continue
        rho, p = sps.spearmanr(x[mask], y[mask])
        top_mean, bottom_mean = st.clean(x[top & mask].mean()), st.clean(x[bottom & mask].mean())
        rows.append(
            {
                "factor": key,
                "label": label,
                "spearman_rho": st.r(rho, 3),
                "p_value": st.r(p, 4),
                "top_quartile_mean": st.r(top_mean),
                "bottom_quartile_mean": st.r(bottom_mean),
                "top_text": _fmt(unit, top_mean),
                "bottom_text": _fmt(unit, bottom_mean),
                "significant": bool(p is not None and p < 0.05 and abs(rho) >= 0.15),
            }
        )
    rows.sort(key=lambda r: -abs(r["spearman_rho"] or 0))
    sig = [r for r in rows if r["significant"]]
    summary = None
    if sig:
        parts = [f"{r['label']}（最好的日子 {r['top_text']} vs 最差的日子 {r['bottom_text']}）" for r in sig[:3]]
        summary = f"过去 {days} 天里，与 {outcome} 关系最明显的是：" + "；".join(parts) + "。这是相关性，不代表因果。"
    return {
        "available": True,
        "days": days,
        "outcome": outcome,
        "top_quartile_threshold": st.r(q_hi, 1),
        "bottom_quartile_threshold": st.r(q_lo, 1),
        "factors": rows,
        "summary": summary,
    }
