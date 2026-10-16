"""长期个人规律学习。

在用户自己的历史数据中寻找“条件 → 结果”的相关趋势，例如：
- 睡眠 < 6.5h 的夜晚之后，HRV 平均比基线低 11%
- 连续两天 Strain > 16 后，第三天 Recovery 平均只有 43%
- 睡眠 > 7.5h 时 Recovery > 70% 的概率明显更高

所有结论都写成“历史数据中存在这种相关趋势”，并附带样本量、p 值与置信度。禁止写成因果。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app.analytics import stats as st
from app.analytics.analysis import deviation_series
from app.analytics.metrics import fmt_bedtime

WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
EVENT_TAG_LABEL = {
    "alcohol": "饮酒",
    "late_night": "熬夜 / 晚睡",
    "illness": "生病",
    "stress": "压力大 / 考试",
    "travel": "出差 / 旅行",
    "caffeine_late": "晚间咖啡因",
    "late_meal": "晚餐过晚",
    "sauna": "桑拿",
}


@dataclass
class PatternResult:
    key: str
    category: str
    title: str
    description: str
    condition: str
    outcome_metric: str
    effect: float
    effect_unit: str
    condition_mean: float | None
    baseline_mean: float | None
    sample_size: int
    comparison_size: int
    p_value: float | None
    confidence: str
    details: dict = field(default_factory=dict)


def _confidence(n: int, p: float | None, min_n: int) -> str | None:
    if p is None or n < min_n:
        return None
    if n >= 15 and p < 0.01:
        return "high"
    if n >= 8 and p < 0.05:
        return "medium"
    if n >= min_n and p < 0.12:
        return "low"
    return None


def _mean_effect(
    key: str,
    category: str,
    cond: pd.Series,
    outcome: pd.Series,
    outcome_metric: str,
    condition_text: str,
    title_fn: Callable[[float, float, float], str],
    unit: str,
    min_effect: float,
    min_n: int = 5,
) -> PatternResult | None:
    cond = cond.fillna(False).astype(bool)
    valid = outcome.notna()
    a = outcome[cond & valid]
    b = outcome[~cond & valid]
    diff, p = st.welch(a, b)
    if diff is None or abs(diff) < min_effect:
        return None
    conf = _confidence(len(a), p, min_n)
    if conf is None:
        return None
    title = title_fn(diff, float(a.mean()), float(b.mean()))
    return PatternResult(
        key=key,
        category=category,
        title=title,
        description=(
            f"{title}。样本：条件成立 {len(a)} 天，对照 {len(b)} 天；p={p:.3f}。"
            "这是你历史数据中存在的相关趋势，不代表确定的因果关系。"
        ),
        condition=condition_text,
        outcome_metric=outcome_metric,
        effect=round(diff, 4),
        effect_unit=unit,
        condition_mean=st.r(a.mean(), 3),
        baseline_mean=st.r(b.mean(), 3),
        sample_size=len(a),
        comparison_size=len(b),
        p_value=round(p, 4) if p is not None else None,
        confidence=conf,
        details={"condition_dates": [d.date().isoformat() for d in a.index[-10:]]},
    )


def mine_patterns(df: pd.DataFrame, events: list[dict] | None = None) -> list[PatternResult]:
    """在完整历史中挖掘个人规律。events: [{"date": date, "tags": [...]}] 来自长期记忆。"""
    if df.empty or df["hrv"].notna().sum() < 30:
        return []
    out: list[PatternResult] = []
    hrv_dev = deviation_series(df["hrv"].astype(float), 28)
    rhr_dev = deviation_series(df["rhr"].astype(float), 28)
    rec = df["recovery"].astype(float)
    sleep_h = df["sleep_duration"].astype(float) / 60
    strain = df["strain"].astype(float)

    def pct_title(prefix: str, metric_label: str):
        def f(diff, a, b):
            word = "高" if a > 0 else "低"
            return f"{prefix}，{metric_label}平均比个人基线{word} {abs(a) * 100:.0f}%（其他日子平均 {b * 100:+.0f}%）"
        return f

    # 1. 短睡眠 → 当天 HRV（WHOOP 的 HRV 测量于这一晚的睡眠中）
    for hours in (6.0, 6.5):
        r = _mean_effect(
            f"short_sleep_{hours}_hrv", "sleep", sleep_h < hours, hrv_dev, "hrv",
            f"睡眠 < {hours}h", pct_title(f"睡眠少于 {hours} 小时的夜晚之后", "HRV "), "pct", 0.04,
        )
        if r:
            out.append(r)
            break
    # 1b. 短睡眠 → RHR
    r = _mean_effect(
        "short_sleep_rhr", "sleep", sleep_h < 6.5, rhr_dev, "rhr",
        "睡眠 < 6.5h", pct_title("睡眠少于 6.5 小时的夜晚之后", "静息心率"), "pct", 0.025,
    )
    if r:
        out.append(r)
    # 1c. 短睡眠的滞后效应：第二天 HRV
    r = _mean_effect(
        "short_sleep_next_day_hrv", "sleep", (sleep_h < 6.5).shift(1), hrv_dev, "hrv",
        "前一晚睡眠 < 6.5h（看再下一天）", pct_title("短睡眠后的第二天", "HRV "), "pct", 0.04,
    )
    if r:
        out.append(r)

    # 2. 连续两天高 Strain → 第三天 Recovery
    thr = 16.0 if (strain > 16).sum() >= 10 else float(strain.quantile(0.8))
    cond = (strain.shift(1) > thr) & (strain.shift(2) > thr)
    r = _mean_effect(
        "two_high_strain_days_recovery", "strain", cond, rec, "recovery",
        f"连续两天 Strain > {thr:.1f}",
        lambda d, a, b: f"连续两个 Strain > {thr:.1f} 的训练日之后，第三天 Recovery 平均 {a:.0f}%（其他日子 {b:.0f}%）",
        "points", 5,
    )
    if r:
        out.append(r)

    # 3. 前一天高负荷 → 今天 HRV
    p80 = float(strain.quantile(0.8))
    r = _mean_effect(
        "high_strain_prev_hrv", "strain", strain.shift(1) > p80, hrv_dev, "hrv",
        f"前一天 Strain > {p80:.1f}（个人 P80）",
        pct_title(f"前一天 Strain 高于 {p80:.1f}（你的 P80）时", "第二天 HRV "), "pct", 0.03,
    )
    if r:
        out.append(r)

    # 4. 长睡眠 → Recovery > 70% 的概率
    long = sleep_h > 7.5
    valid = rec.notna() & sleep_h.notna()
    good = rec >= 70
    n_a, n_b = int((long & valid).sum()), int((~long & valid).sum())
    if n_a >= 8 and n_b >= 8:
        hit_a, hit_b = int((long & valid & good).sum()), int((~long & valid & good).sum())
        pa, pb = hit_a / n_a, hit_b / n_b
        p = st.proportion_test(hit_a, n_a, hit_b, n_b)
        conf = _confidence(n_a, p, 8)
        if conf and pa - pb >= 0.12:
            title = f"睡眠超过 7.5 小时的日子，Recovery ≥ 70% 的比例为 {pa * 100:.0f}%（其他日子 {pb * 100:.0f}%）"
            out.append(
                PatternResult(
                    "long_sleep_green_recovery", "sleep", title,
                    f"{title}。样本：{n_a} 天 vs {n_b} 天，p={p:.3f}。这是相关趋势，不代表确定因果。",
                    "睡眠 > 7.5h", "recovery", round(pa - pb, 4), "probability",
                    round(pa, 3), round(pb, 3), n_a, n_b, round(p, 4), conf,
                )
            )

    # 5. 晚睡 → HRV
    if "bedtime" in df and df["bedtime"].notna().sum() > 30:
        bt = df["bedtime"].astype(float)
        late = bt > 12.5  # 00:30 之后入睡
        r = _mean_effect(
            "late_bedtime_hrv", "sleep", late, hrv_dev, "hrv",
            "00:30 之后入睡", pct_title(f"入睡晚于 {fmt_bedtime(12.5)} 的夜晚之后", "HRV "), "pct", 0.04,
        )
        if r:
            out.append(r)

    # 6. 睡眠一致性
    if "sleep_consistency" in df and df["sleep_consistency"].notna().sum() > 30:
        cons = df["sleep_consistency"].astype(float)
        r = _mean_effect(
            "low_consistency_recovery", "sleep", cons < 70, rec, "recovery", "睡眠一致性 < 70%",
            lambda d, a, b: f"睡眠一致性低于 70% 的日子，Recovery 平均 {a:.0f}%（其他日子 {b:.0f}%）",
            "points", 5,
        )
        if r:
            out.append(r)

    # 7. 星期效应
    wd_dev = rec - rec.rolling(28, min_periods=10).mean().shift(1)
    best = None
    for wd in range(7):
        r = _mean_effect(
            f"weekday_{wd}_recovery", "weekday", pd.Series(rec.index.weekday == wd, index=rec.index), wd_dev,
            "recovery", f"{WEEKDAY[wd]}",
            lambda d, a, b, wd=wd: f"{WEEKDAY[wd]}的 Recovery 平均比你的 28 日均值{'高' if a > 0 else '低'} {abs(a):.0f} 个百分点",
            "points", 6, min_n=6,
        )
        if r and (best is None or abs(r.effect) > abs(best.effect)):
            best = r
    if best:
        out.append(best)

    # 8. 来自长期记忆的生活事件 → 第二天 HRV（事件当天晚上发生，次日早晨体现）
    by_tag: dict[str, set[date]] = {}
    for ev in events or []:
        for tag in ev.get("tags", []):
            if tag in EVENT_TAG_LABEL and ev.get("date"):
                by_tag.setdefault(tag, set()).add(ev["date"])
    for tag, dates in by_tag.items():
        next_days = {pd.Timestamp(d) + pd.Timedelta(days=1) for d in dates}
        cond = pd.Series(df.index.isin(list(next_days)), index=df.index)
        r = _mean_effect(
            f"event_{tag}_hrv", "lifestyle", cond, hrv_dev, "hrv", f"记录了「{EVENT_TAG_LABEL[tag]}」的第二天",
            pct_title(f"你记录「{EVENT_TAG_LABEL[tag]}」后的第二天", "HRV "), "pct", 0.04, min_n=3,
        )
        if r:
            out.append(r)

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda p: (order[p.confidence], -abs(p.effect)))
    return out
