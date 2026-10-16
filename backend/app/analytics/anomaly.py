"""Anomaly Detection Service。

所有阈值来自 anomaly_rules.yaml，并可被用户设置覆盖（users.settings["anomaly_rules"]）。
`suggest_thresholds` 根据用户自身历史分布给出个性化阈值建议。
"""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from app.analytics import stats as st
from app.analytics.analysis import deviation_series, z_series
from app.analytics.metrics import METRICS, fmt_delta, fmt_pct, fmt_value

RULES_PATH = Path(__file__).with_name("anomaly_rules.yaml")
SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}


@lru_cache
def default_rules() -> dict:
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_rules(user_settings: dict | None = None) -> dict:
    return _deep_merge(default_rules(), (user_settings or {}).get("anomaly_rules", {}))


# --------------------------------------------------------------------------- 信号


def signal_flags(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """每天每个指标是否出现“不利方向的轻度偏离”（联合分析和多指标异常共用）。"""
    out = {}
    for metric, cfg in rules.get("signals", {}).items():
        if metric not in df:
            continue
        s = df[metric].astype(float)
        z = z_series(s, 28)
        sign = -1 if cfg["direction"] == "low" else 1
        if "abs" in cfg:
            base = st.trailing(s, 28).mean()
            hit = ((s - base) * sign >= cfg["abs"]) | ((z * sign >= cfg.get("z", 99)) & ((s - base) * sign >= cfg["abs"] * 0.5))
        else:
            hit = deviation_series(s, 28) * sign >= cfg["pct"]
            # z 很高但绝对变化很小（个人波动本来就很小）时不算信号
            hit = hit | ((z * sign >= cfg.get("z", 99)) & (deviation_series(s, 28) * sign >= cfg["pct"] * 0.5))
        out[metric] = hit.fillna(False).astype(bool)
    return pd.DataFrame(out, index=df.index)


# --------------------------------------------------------------------------- 检测


def _threshold_rule(df: pd.DataFrame, key: str, cfg: dict, mode: str) -> list[dict]:
    metric = cfg["metric"]
    if metric not in df:
        return []
    s = df[metric].astype(float)
    base = st.trailing(s, 28).mean()
    dev = deviation_series(s, 28)
    z = z_series(s, 28)
    sign = -1 if cfg["direction"] == "low" else 1
    sdev, sz = dev * sign, z * sign
    pct, zt = cfg["pct"], cfg.get("z", 1.5)

    pct_hit = sdev >= pct
    z_hit = sz >= zt
    trigger = pct_hit if mode == "fixed" else (pct_hit | z_hit)
    events = []
    for d in s.index[trigger.fillna(False).astype(bool)]:
        v, b, dv, zz = s[d], base[d], dev[d], z[d]
        if pd.isna(v) or pd.isna(b):
            continue
        szz = (zz * sign) if not pd.isna(zz) else None
        if abs(dv) >= 2 * pct or (szz is not None and szz >= 2.5):
            severity = "high"
        elif mode != "fixed" and szz is not None and szz < 1.0 and not z_hit[d]:
            severity = "low"
        else:
            severity = "medium"
        msg = (
            f"{METRICS[metric].label} {fmt_value(metric, v)}，比 28 日个人基线 "
            f"{fmt_value(metric, b)} {fmt_delta(metric, v, b)}"
        )
        if szz is not None:
            msg += f"（z={zz:+.1f}）"
        events.append(
            {
                "date": d.date(),
                "rule": key,
                "metric": metric,
                "severity": severity,
                "value": st.r(v),
                "baseline": st.r(b),
                "deviation_pct": st.r(dv, 4),
                "z_score": st.r(zz),
                "message": msg,
                "details": {"label": cfg.get("label", key), "threshold_pct": pct, "threshold_z": zt},
            }
        )
    return events


def _streak_rules(df: pd.DataFrame, streaks: dict) -> list[dict]:
    events = []
    for key, cfg in streaks.items():
        metric = cfg["metric"]
        if metric not in df:
            continue
        s = df[metric].astype(float)
        if "below" in cfg:
            flags = s < cfg["below"]
            desc = f"低于 {cfg['below']}"
        elif "above_percentile" in cfg:
            p = s.shift(1).rolling(90, min_periods=20).quantile(cfg["above_percentile"] / 100)
            flags = s > p
            desc = f"高于个人 90 日 P{cfg['above_percentile']}"
        else:
            flags = s < st.trailing(s, 28).mean()
            desc = "低于个人 28 日均值"
        flags = flags.fillna(False).astype(bool)
        run = flags.groupby((~flags).cumsum()).cumsum()
        for d in s.index[run >= cfg["min_days"]]:
            n = int(run[d])
            recent_vals = "、".join(fmt_value(metric, x) for x in s.loc[:d].iloc[-n:].tolist()[-5:])
            events.append(
                {
                    "date": d.date(),
                    "rule": key,
                    "metric": metric,
                    "severity": "high" if n >= cfg["min_days"] + 2 else "medium",
                    "value": st.r(s[d]),
                    "baseline": None,
                    "deviation_pct": None,
                    "z_score": None,
                    "message": f"{METRICS[metric].label}已连续 {n} 天{desc}（最近：{recent_vals}）",
                    "details": {"label": cfg.get("label", key), "streak_days": n},
                }
            )
    return events


def _multi_metric(df: pd.DataFrame, rules: dict) -> list[dict]:
    cfg = rules.get("multi_metric") or {}
    flags = signal_flags(df, rules)
    if flags.empty:
        return []
    count = flags.sum(axis=1)
    events = []
    for d in df.index[count >= cfg.get("min_signals", 3)]:
        names = [METRICS[m].label for m in flags.columns if flags.at[d, m]]
        events.append(
            {
                "date": d.date(),
                "rule": "multi_metric",
                "metric": "multi",
                "severity": "high" if len(names) >= 4 else "medium",
                "value": float(len(names)),
                "baseline": None,
                "deviation_pct": None,
                "z_score": None,
                "message": f"{'、'.join(names)} 同时向不利方向偏离个人基线",
                "details": {"label": cfg.get("label", "多指标同步异常"), "signals": names},
            }
        )
    return events


def detect(df: pd.DataFrame, rules: dict) -> list[dict]:
    """对整个时间序列做异常检测，返回事件列表。"""
    if df.empty:
        return []
    mode = rules.get("mode", "adaptive")
    events: list[dict] = []
    for key, cfg in rules.get("rules", {}).items():
        events += _threshold_rule(df, key, cfg, mode)
    events += _streak_rules(df, rules.get("streaks", {}))
    events += _multi_metric(df, rules)
    events.sort(key=lambda e: (e["date"], -SEVERITY_ORDER[e["severity"]]))
    return events


# --------------------------------------------------------------------------- 个性化阈值建议


def suggest_thresholds(df: pd.DataFrame, rules: dict, target_rate: float = 0.07) -> dict:
    """基于用户自己的偏差分布，建议让约 target_rate 的日子触发的阈值。"""
    out = {}
    for key, cfg in rules.get("rules", {}).items():
        metric = cfg["metric"]
        if metric not in df:
            continue
        dev = deviation_series(df[metric].astype(float), 28).dropna()
        if len(dev) < 30:
            continue
        sign = -1 if cfg["direction"] == "low" else 1
        sdev = dev * sign
        suggested = float(np.clip(sdev.quantile(1 - target_rate), 0.03, 0.6))
        out[key] = {
            "label": cfg.get("label", key),
            "current_pct": cfg["pct"],
            "current_trigger_rate": st.r((sdev >= cfg["pct"]).mean(), 3),
            "suggested_pct": round(suggested, 3),
            "suggested_trigger_rate": st.r((sdev >= suggested).mean(), 3),
            "sample_days": int(len(dev)),
            "note": (
                f"按你过去 {len(dev)} 天的数据，当前阈值 {fmt_pct(cfg['pct'], False)} "
                f"约有 {(sdev >= cfg['pct']).mean() * 100:.0f}% 的日子会触发；"
                f"建议 {fmt_pct(suggested, False)}（约 {target_rate * 100:.0f}% 的日子触发）"
            ),
        }
    return out
