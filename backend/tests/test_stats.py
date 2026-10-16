import numpy as np
import pandas as pd

from app.analytics import stats as st
from app.analytics.analysis import analyze_metric, baseline_frame, deviation_series


def _series(values, start="2026-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"), dtype=float)


def test_baseline_excludes_today():
    s = _series([10.0] * 28 + [100.0])
    b = baseline_frame(s, 28)
    assert b["mean"].iloc[-1] == 10.0  # 当天的 100 不进入基线
    assert deviation_series(s, 28).iloc[-1] == 9.0


def test_slope_direction():
    up = _series(np.linspace(50, 70, 28))
    assert st.slope(up).direction == "up"
    flat = _series([60.0] * 28)
    assert st.slope(flat).direction == "flat"


def test_zscore_and_percentile():
    assert st.zscore(12, 10, 2) == 1.0
    assert st.zscore(10, 10, 0) == 0.0
    hist = _series(list(range(1, 101)))
    assert 49 < st.percentile_rank(50, hist) < 51


def test_trailing_streak():
    assert st.trailing_streak(pd.Series([True, False, True, True])) == 2
    assert st.trailing_streak(pd.Series([False])) == 0


def test_analyze_metric_counts_consecutive_days():
    values = [70.0] * 30 + [60.0, 58.0, 57.0]
    df = pd.DataFrame({"hrv": _series(values)})
    a = analyze_metric(df, "hrv")
    assert a["consecutive_below_baseline"] == 3
    assert a["consecutive_unfavorable_days"] == 3
    assert a["consecutive_decline_days"] == 3
    assert round(a["deviation_pct_28d"], 3) == round((57 - 70) / 70, 3) or a["deviation_pct_28d"] < -0.1
    assert a["status"] == "worse"
