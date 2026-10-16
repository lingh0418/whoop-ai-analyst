"""基础统计：均值 / 中位数 / 标准差 / 偏差 / z-score / 趋势斜率 / 连续天数 / 个人百分位。

约定：所有序列都是以连续自然日为索引的 pd.Series（缺失日为 NaN）。
个人基线一律使用“当天之前”的窗口（不含当天），避免当天数值污染基线。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as sps

MIN_PERIODS = {7: 4, 28: 10, 90: 20}


def min_periods(window: int) -> int:
    return MIN_PERIODS.get(window, max(3, window // 3))


def trailing(series: pd.Series, window: int) -> pd.core.window.Rolling:
    """当天之前 window 天（不含当天）的滚动窗口。"""
    return series.shift(1).rolling(window, min_periods=min_periods(window))


def recent(series: pd.Series, window: int) -> pd.core.window.Rolling:
    """包含当天在内的最近 window 天。"""
    return series.rolling(window, min_periods=max(1, min_periods(window) // 2))


def pct_change(value: float | None, base: float | None) -> float | None:
    if value is None or base is None or _nan(value) or _nan(base) or base == 0:
        return None
    return (value - base) / abs(base)


def zscore(value: float | None, mean: float | None, std: float | None) -> float | None:
    if value is None or mean is None or std is None or _nan(value) or _nan(mean) or _nan(std):
        return None
    if std < 1e-9:
        return 0.0
    return (value - mean) / std


@dataclass
class Slope:
    per_day: float | None
    pct_per_week: float | None  # 相对窗口均值的每周变化
    p_value: float | None
    n: int

    @property
    def direction(self) -> str:
        """up / down / flat —— 需要统计上较可信且幅度足够才算趋势。"""
        if self.per_day is None or self.pct_per_week is None:
            return "flat"
        if self.p_value is not None and self.p_value < 0.1 and abs(self.pct_per_week) >= 0.015:
            return "up" if self.per_day > 0 else "down"
        return "flat"


def slope(series: pd.Series) -> Slope:
    s = series.dropna()
    n = len(s)
    if n < 4:
        return Slope(None, None, None, n)
    x = (s.index - s.index[0]).days.astype(float)
    y = s.values.astype(float)
    if np.allclose(y, y[0]):
        return Slope(0.0, 0.0, 1.0, n)
    res = sps.linregress(x, y)
    mean = float(np.mean(y))
    pct = (res.slope * 7 / abs(mean)) if mean else None
    return Slope(float(res.slope), pct, float(res.pvalue), n)


def percentile_rank(value: float | None, history: pd.Series) -> float | None:
    """value 在历史分布中的百分位（0-100）。"""
    h = history.dropna()
    if value is None or _nan(value) or len(h) < 5:
        return None
    return float(sps.percentileofscore(h.values, value, kind="mean"))


def trailing_streak(flags: pd.Series) -> int:
    """从序列末尾往前数连续为 True 的天数（NaN 视为中断）。"""
    count = 0
    for v in reversed(flags.tolist()):
        if v is True or (isinstance(v, (bool, np.bool_)) and bool(v)):
            count += 1
        else:
            break
    return count


def cv(series: pd.Series) -> float | None:
    """变异系数：波动程度。"""
    s = series.dropna()
    if len(s) < 5 or s.mean() == 0:
        return None
    return float(s.std(ddof=1) / abs(s.mean()))


def welch(a: pd.Series, b: pd.Series) -> tuple[float | None, float | None]:
    """Welch t 检验：返回 (均值差 a-b, p 值)。"""
    a, b = a.dropna(), b.dropna()
    if len(a) < 3 or len(b) < 3:
        return None, None
    diff = float(a.mean() - b.mean())
    if a.std(ddof=1) == 0 and b.std(ddof=1) == 0:
        return diff, 0.0 if diff != 0 else 1.0
    res = sps.ttest_ind(a, b, equal_var=False)
    p = float(res.pvalue)
    return diff, (p if not math.isnan(p) else None)


def proportion_test(hit_a: int, n_a: int, hit_b: int, n_b: int) -> float | None:
    if min(n_a, n_b) < 3:
        return None
    _, p = sps.fisher_exact([[hit_a, n_a - hit_a], [hit_b, n_b - hit_b]])
    return float(p)


def clean(x) -> float | None:
    """numpy / NaN → Python float / None，便于 JSON 序列化。"""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def r(x, nd: int = 2) -> float | None:
    v = clean(x)
    return None if v is None else round(v, nd)


def _nan(x) -> bool:
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return True
