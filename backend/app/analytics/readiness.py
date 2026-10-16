"""身体状态分（0-100）。

不是 WHOOP Recovery 的复刻，而是“你今天和你自己平时相比”的综合分：
- 个人偏差分：HRV / 静息心率 / 睡眠 / 昨日负荷 / 呼吸频率 相对个人 28 日基线的 z-score 加权
- 若有 WHOOP Recovery，则与之混合（Recovery 40% + 个人偏差分 60%）
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.analysis import z_series

# (指标, 权重, 方向, 只计不利一侧)
COMPONENTS = [
    ("hrv", 0.35, +1, False),
    ("rhr", 0.25, -1, False),
    ("sleep_duration", 0.20, +1, False),
    ("strain_prev", 0.12, -1, True),
    ("resp_rate", 0.08, -1, True),
]

LEVELS = [(75, "good", "良好"), (60, "normal", "正常"), (45, "low", "偏低"), (0, "very_low", "明显偏低")]


def level_of(score: float | None) -> tuple[str | None, str | None]:
    if score is None or pd.isna(score):
        return None, None
    for threshold, key, label in LEVELS:
        if score >= threshold:
            return key, label
    return LEVELS[-1][1], LEVELS[-1][2]


def readiness_series(df: pd.DataFrame) -> pd.DataFrame:
    """返回 DataFrame[score, composite_z, level]，索引与 df 一致。"""
    zs = {}
    for name, _, _, _ in COMPONENTS:
        if name == "strain_prev":
            if "strain" in df:
                zs[name] = z_series(df["strain"].astype(float), 28).shift(1)
        elif name in df:
            zs[name] = z_series(df[name].astype(float), 28)
    num = pd.Series(0.0, index=df.index)
    den = pd.Series(0.0, index=df.index)
    for name, w, sign, one_sided in COMPONENTS:
        if name not in zs:
            continue
        z = (zs[name] * sign).clip(-3, 3)
        if one_sided:
            z = z.clip(upper=0)
        mask = z.notna()
        num = num.add((z * w).where(mask, 0.0))
        den = den.add(pd.Series(np.where(mask, w, 0.0), index=df.index))
    composite = (num / den).where(den >= 0.5)
    dev_score = (65 + 15 * composite).clip(5, 98)

    rec = df["recovery"].astype(float) if "recovery" in df else pd.Series(np.nan, index=df.index)
    score = pd.Series(np.where(rec.notna() & dev_score.notna(), 0.4 * rec + 0.6 * dev_score, dev_score), index=df.index)
    score = score.where(score.notna(), rec)  # 基线不足时直接使用 Recovery
    out = pd.DataFrame({"score": score.round(0), "composite_z": composite.round(3)})
    out["level"] = [level_of(s)[0] for s in out["score"]]
    return out
