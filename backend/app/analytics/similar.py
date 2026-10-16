"""“这种情况过去什么时候出现过？” —— 在历史中寻找偏离模式相似的日子，并看之后发生了什么。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics import stats as st
from app.analytics.analysis import deviation_series, z_series

# 特征及其“典型尺度”（用于标准化距离）
FEATURES = {
    "hrv_dev": 0.10,
    "rhr_dev": 0.05,
    "sleep_dev": 0.15,
    "strain_prev_z": 1.0,
}


def _feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "hrv_dev": deviation_series(df["hrv"].astype(float), 28),
            "rhr_dev": deviation_series(df["rhr"].astype(float), 28),
            "sleep_dev": deviation_series(df["sleep_duration"].astype(float), 28),
            "strain_prev_z": z_series(df["strain"].astype(float), 28).shift(1),
        },
        index=df.index,
    )


def find_similar_days(df: pd.DataFrame, as_of: pd.Timestamp, k: int = 5) -> dict:
    if df.empty or as_of not in df.index:
        return {"available": False, "items": []}
    feats = _feature_frame(df)
    target = feats.loc[as_of]
    if target[["hrv_dev", "rhr_dev"]].isna().any():
        return {"available": False, "items": []}
    cand = feats.loc[: as_of - pd.Timedelta(days=4)].dropna(subset=["hrv_dev", "rhr_dev"])
    if len(cand) < 20:
        return {"available": False, "items": []}

    scales = pd.Series(FEATURES)
    diff = (cand - target) / scales
    # 缺失特征不参与距离
    dist = np.sqrt((diff**2).sum(axis=1, skipna=True) / diff.notna().sum(axis=1).clip(lower=1))
    # 避免挑出同一段连续日子：贪心选择，彼此间隔 ≥ 3 天
    chosen: list[pd.Timestamp] = []
    for d in dist.sort_values().index:
        if all(abs((d - c).days) >= 3 for c in chosen):
            chosen.append(d)
        if len(chosen) >= k:
            break

    hrv_dev = feats["hrv_dev"]
    rec = df["recovery"].astype(float)
    items = []
    for d in chosen:
        nxt = [d + pd.Timedelta(days=i) for i in (1, 2, 3)]
        back = None
        for i in range(1, 8):
            v = hrv_dev.get(d + pd.Timedelta(days=i))
            if v is not None and not pd.isna(v) and v >= -0.03:
                back = i
                break
        items.append(
            {
                "date": d.date().isoformat(),
                "distance": st.r(dist[d], 3),
                "hrv_dev": st.r(feats.at[d, "hrv_dev"], 4),
                "rhr_dev": st.r(feats.at[d, "rhr_dev"], 4),
                "sleep_dev": st.r(feats.at[d, "sleep_dev"], 4),
                "strain_prev_z": st.r(feats.at[d, "strain_prev_z"]),
                "recovery": st.r(rec.get(d), 0),
                "joint_state": (df["joint_state"].get(d) if "joint_state" in df and isinstance(df["joint_state"].get(d), str) else None),
                "next_days_recovery": [st.r(rec.get(x), 0) for x in nxt],
                "days_to_hrv_baseline": back,
            }
        )
    backs = [i["days_to_hrv_baseline"] for i in items if i["days_to_hrv_baseline"]]
    nxt1 = [i["next_days_recovery"][0] for i in items if i["next_days_recovery"][0] is not None]
    summary = None
    if items:
        summary = f"历史上找到 {len(items)} 个与今天偏离模式相似的日子"
        if nxt1:
            summary += f"，它们第二天的 Recovery 平均为 {np.mean(nxt1):.0f}%"
        if backs:
            summary += f"，HRV 通常在 {np.median(backs):.0f} 天左右回到个人基线"
        summary += "（仅供参考，历史相似不代表今天一定如此）。"
    return {
        "available": bool(items),
        "target": {k_: st.r(v, 4) for k_, v in target.items()},
        "items": items,
        "summary": summary,
    }
