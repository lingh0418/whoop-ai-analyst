import numpy as np
import pandas as pd

from app.analytics import anomaly, joint


def _frame(n=60, **overrides):
    rng = np.random.default_rng(1)
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {
            "hrv": 70 + rng.normal(0, 5, n),
            "rhr": 55 + rng.normal(0, 1, n),
            "recovery": 65 + rng.normal(0, 8, n),
            "sleep_duration": 450 + rng.normal(0, 35, n),
            "sleep_debt": 20.0,
            "sleep_need": 470.0,
            "strain": 12 + rng.normal(0, 3.0, n),
            "resp_rate": 15 + rng.normal(0, 0.2, n),
            "skin_temp": 33.5 + rng.normal(0, 0.1, n),
        },
        index=idx,
    )
    # 最近 5 天固定为“平常值”，避免随机噪声干扰断言
    df.iloc[-5:] = [70.0, 55.0, 65.0, 450.0, 20.0, 470.0, 12.0, 15.0, 33.5]
    for col, vals in overrides.items():
        for offset, v in vals.items():
            df.iloc[offset, df.columns.get_loc(col)] = v
    return df


def test_isolated_hrv_dip_is_conservative():
    df = _frame(hrv={-1: 55.0})
    r = joint.assess(df, df.index[-1], anomaly.load_rules())
    assert r["state"] == "isolated_hrv_dip"
    assert "单日" in r["caution"]


def test_multi_metric_under_recovery():
    df = _frame(
        hrv={-1: 57.0, -2: 62.0},
        rhr={-1: 61.0},
        sleep_duration={-1: 360.0, -2: 380.0},
        strain={-2: 17.5, -3: 17.0, -4: 16.5},
        recovery={-1: 30.0},
    )
    r = joint.assess(df, df.index[-1], anomaly.load_rules())
    assert r["state"] in {"short_term_under_recovery", "systemic_decline"}
    assert "过度训练" in r["caution"]  # 明确不断言过度训练


def test_illness_like_pattern():
    df = _frame(hrv={-1: 55.0}, rhr={-1: 62.0}, resp_rate={-1: 16.5}, skin_temp={-1: 34.4})
    r = joint.assess(df, df.index[-1], anomaly.load_rules())
    assert r["state"] == "non_training_stress"
    assert r["training_level"] == "rest"


def test_normal_day():
    df = _frame()
    r = joint.assess(df, df.index[-1], anomaly.load_rules())
    assert r["severity"] <= 1


def test_rules_are_configurable():
    rules = anomaly.load_rules({"anomaly_rules": {"rules": {"hrv_drop": {"pct": 0.05}}, "mode": "fixed"}})
    assert rules["rules"]["hrv_drop"]["pct"] == 0.05
    assert rules["rules"]["rhr_rise"]["pct"] == 0.10  # 其余保持默认
    df = _frame(hrv={-1: 64.0})
    events = [e for e in anomaly.detect(df, rules) if e["rule"] == "hrv_drop"]
    assert events and events[-1]["date"] == df.index[-1].date()
