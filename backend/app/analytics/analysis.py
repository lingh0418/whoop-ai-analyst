"""单指标深度分析：今天 vs 个人基线、7/28/90 天趋势、连续异常天数、个人百分位、波动性。

这里输出的全部是结构化数字，供联合分析、日报和 Agent Tools 使用。LLM 不做任何基础统计。
"""

from __future__ import annotations

import weakref

import pandas as pd

from app.analytics import stats as st
from app.analytics.metrics import METRICS, fmt_value

TREND_LABEL = {"up": "上升", "down": "下降", "flat": "平稳"}


def baseline_frame(series: pd.Series, window: int) -> pd.DataFrame:
    """每一天的个人基线（使用当天之前 window 天，不含当天）。"""
    roll = st.trailing(series, window)
    return pd.DataFrame(
        {
            "mean": roll.mean(),
            "median": roll.median(),
            "std": roll.std(),
            "p10": roll.quantile(0.1),
            "p90": roll.quantile(0.9),
            "n": series.shift(1).rolling(window, min_periods=1).count(),
        }
    )


def deviation_series(series: pd.Series, window: int = 28) -> pd.Series:
    base = st.trailing(series, window).mean()
    return (series - base) / base.abs()


def z_series(series: pd.Series, window: int = 28) -> pd.Series:
    roll = st.trailing(series, window)
    std = roll.std().where(lambda s: s > 1e-9)
    return (series - roll.mean()) / std


def _run_length(flags: pd.Series) -> pd.Series:
    """每一天往前连续为 True 的天数。"""
    flags = flags.fillna(False).astype(bool)
    return flags.groupby((~flags).cumsum()).cumsum()


# 同一个 DataFrame 上的重复分析（如逐日联合分析）复用预计算结果
_CACHE: dict[int, dict] = {}


def _pre(df: pd.DataFrame, metric: str) -> dict:
    key = id(df)
    entry = _CACHE.get(key)
    if entry is None:
        entry = _CACHE[key] = {}
        weakref.finalize(df, _CACHE.pop, key, None)
    if metric not in entry:
        series = df[metric].astype(float)
        b28 = baseline_frame(series, 28)
        valid = series.notna() & b28["mean"].notna()
        obs = series.dropna()
        dec = (obs < obs.shift(1)).reindex(series.index, fill_value=False)
        inc = (obs > obs.shift(1)).reindex(series.index, fill_value=False)
        entry[metric] = {
            "series": series,
            "b7": baseline_frame(series, 7),
            "b28": b28,
            "b90": baseline_frame(series, 90),
            "below": _run_length((series < b28["mean"]) & valid),
            "above": _run_length((series > b28["mean"]) & valid),
            # 只在有数据的日子之间比较“连续下降/上升”
            "dec": _run_length(dec.where(series.notna())).where(series.notna()).ffill(),
            "inc": _run_length(inc.where(series.notna())).where(series.notna()).ffill(),
        }
    return entry[metric]


def _trend(sl: st.Slope) -> dict:
    return {
        "direction": sl.direction,
        "label": TREND_LABEL[sl.direction],
        "per_day": st.r(sl.per_day, 3),
        "pct_per_week": st.r(sl.pct_per_week, 4),
        "p_value": st.r(sl.p_value, 3),
    }


def analyze_metric(df: pd.DataFrame, metric: str, as_of: pd.Timestamp | None = None, light: bool = False) -> dict:
    """返回某个指标截至 as_of 的完整分析。light=True 时跳过趋势/百分位/波动性（用于逐日批量计算）。"""
    mdef = METRICS[metric]
    if metric not in df or df.empty:
        return {"metric": metric, "label": mdef.label, "available": False}
    pre = _pre(df, metric)
    series = pre["series"]
    as_of = as_of if as_of is not None else series.index.max()
    if as_of not in series.index:
        return {"metric": metric, "label": mdef.label, "available": False}
    s = series.loc[:as_of]
    if s.dropna().empty:
        return {"metric": metric, "label": mdef.label, "available": False}

    value = st.clean(s.iloc[-1])
    b7, b28, b90 = pre["b7"].loc[as_of], pre["b28"].loc[as_of], pre["b90"].loc[as_of]
    base28_mean, base28_std = st.clean(b28["mean"]), st.clean(b28["std"])
    base90_mean = st.clean(b90["mean"])
    last7 = s.iloc[-7:]

    dev28 = st.pct_change(value, base28_mean)
    z28 = st.zscore(value, base28_mean, base28_std)
    below, above = int(pre["below"].get(as_of, 0)), int(pre["above"].get(as_of, 0))
    unfavorable = below if mdef.direction > 0 else (above if mdef.direction < 0 else 0)

    if dev28 is None:
        status = "unknown"
    elif mdef.direction == 0:
        status = "high" if (z28 or 0) >= 1 else ("low" if (z28 or 0) <= -1 else "normal")
    else:
        signed = dev28 * mdef.direction
        zz = (z28 or 0) * mdef.direction
        status = "worse" if (signed <= -0.07 or zz <= -1) else ("better" if (signed >= 0.07 or zz >= 1) else "normal")

    out = {
        "metric": metric,
        "label": mdef.label,
        "unit": mdef.unit,
        "direction": mdef.direction,
        "available": True,
        "date": as_of.date().isoformat(),
        "value": st.r(value),
        "value_text": fmt_value(metric, value),
        "avg_7d": st.r(last7.mean()),
        "baseline_7d": st.r(b7["mean"]),
        "baseline_28d": st.r(base28_mean),
        "median_28d": st.r(b28["median"]),
        "std_28d": st.r(base28_std),
        "baseline_90d": st.r(base90_mean),
        "p10_90d": st.r(b90["p10"]),
        "p90_90d": st.r(b90["p90"]),
        "baseline_days": int(b28["n"]) if not pd.isna(b28["n"]) else 0,
        "deviation_pct_28d": st.r(dev28, 4),
        "deviation_pct_90d": st.r(st.pct_change(value, base90_mean), 4),
        "avg7_vs_28d_pct": st.r(st.pct_change(st.clean(last7.mean()), base28_mean), 4),
        "z_score_28d": st.r(z28),
        "consecutive_below_baseline": below,
        "consecutive_above_baseline": above,
        "consecutive_unfavorable_days": unfavorable,
        "consecutive_decline_days": int(pre["dec"].get(as_of, 0) or 0),
        "consecutive_rise_days": int(pre["inc"].get(as_of, 0) or 0),
        "status": status,  # better | normal | worse | high | low | unknown
    }
    if light:
        return out

    last28, last90 = s.iloc[-28:], s.iloc[-90:]
    cv28, cv90 = st.cv(last28), st.cv(last90)
    volatility = None
    if cv28 is not None and cv90 is not None and cv90 > 0:
        ratio = cv28 / cv90
        volatility = "波动加大" if ratio > 1.3 else ("波动减小" if ratio < 0.75 else "波动正常")
    out.update(
        {
            "percentile_90d": st.r(st.percentile_rank(value, last90), 1),
            "trend_7d": _trend(st.slope(last7)),
            "trend_28d": _trend(st.slope(last28)),
            "trend_90d": _trend(st.slope(last90)),
            "cv_28d": st.r(cv28, 4),
            "cv_90d": st.r(cv90, 4),
            "volatility": volatility,
            "recent": [{"date": d.date().isoformat(), "value": st.r(v)} for d, v in last7.items()],
        }
    )
    return out


def history(df: pd.DataFrame, metric: str, days: int, as_of: pd.Timestamp | None = None) -> dict:
    """指标历史序列 + 7日均线 + 28日基线带（均值 ± 1 标准差），用于图表与 Agent。"""
    series = df[metric].astype(float)
    as_of = as_of or series.index.max()
    ma7 = series.rolling(7, min_periods=3).mean()
    b28 = baseline_frame(series, 28)
    z = z_series(series, 28)
    dev = deviation_series(series, 28)
    window = series.loc[:as_of].iloc[-days:]
    points = []
    for d in window.index:
        points.append(
            {
                "date": d.date().isoformat(),
                "value": st.r(series.get(d)),
                "ma7": st.r(ma7.get(d)),
                "baseline": st.r(b28["mean"].get(d)),
                "band_low": st.r(b28["mean"].get(d) - b28["std"].get(d)) if not pd.isna(b28["std"].get(d)) else None,
                "band_high": st.r(b28["mean"].get(d) + b28["std"].get(d)) if not pd.isna(b28["std"].get(d)) else None,
                "deviation_pct": st.r(dev.get(d), 4),
                "z": st.r(z.get(d)),
            }
        )
    vals = window.dropna()
    return {
        "metric": metric,
        "label": METRICS[metric].label,
        "unit": METRICS[metric].unit,
        "days": days,
        "points": points,
        "summary": {
            "n": int(len(vals)),
            "mean": st.r(vals.mean()),
            "median": st.r(vals.median()),
            "std": st.r(vals.std()),
            "min": st.r(vals.min()),
            "max": st.r(vals.max()),
        },
    }
