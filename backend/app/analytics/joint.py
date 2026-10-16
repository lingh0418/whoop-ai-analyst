"""多指标联合分析 —— 本项目最核心的判断逻辑。

不是把每个指标分别解释一遍，而是看它们是否“同向变化”：
- HRV↓ + RHR↑ + 睡眠↓ + 近期负荷↑ 同时出现 → 恢复不足（但不断言“过度训练”）
- 只有 HRV↓，其余都正常 → 保守，不根据单日 HRV 下强结论
- HRV↓ + RHR↑ + 呼吸频率/皮温↑，而训练负荷不高 → 提示非训练因素（不做医学诊断）

输出为结构化结论 + 中文说明，供日报、Dashboard 和 Agent 使用。
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from app.analytics import stats as st
from app.analytics.analysis import _run_length, analyze_metric
from app.analytics.anomaly import signal_flags
from app.analytics.metrics import fmt_delta, fmt_minutes, fmt_value

STATES = {
    "calibrating": ("数据积累中", 0),
    "non_training_stress": ("多项生理指标异常（非训练负荷型）", 3),
    "systemic_decline": ("整体恢复状态明显下降", 3),
    "short_term_under_recovery": ("短期恢复不足", 2),
    "sleep_related": ("睡眠不足相关的恢复下降", 2),
    "load_related": ("训练负荷相关的恢复下降", 2),
    "mixed_decline": ("多项指标轻度偏离", 1),
    "isolated_hrv_dip": ("HRV 单项偏低", 1),
    "isolated_rhr_rise": ("静息心率单项偏高", 1),
    "recovery_low_only": ("Recovery 偏低但核心指标稳定", 1),
    "sleep_short_but_stable": ("睡眠偏少，恢复指标暂稳", 1),
    "load_high_but_absorbed": ("负荷偏高，身体暂时吸收良好", 0),
    "well_recovered": ("恢复良好", 0),
    "normal": ("状态平稳", 0),
}

TRAINING_LEVEL = {0: "normal", 1: "caution", 2: "reduce", 3: "recovery"}


def _metric_sentence(a: dict, compare: str = "28 日个人均值") -> str | None:
    if not a.get("available") or a.get("value") is None or a.get("baseline_28d") is None:
        return None
    return (
        f"{a['label']} {a['value_text']}，比 {compare} {fmt_value(a['metric'], a['baseline_28d'])} "
        f"{fmt_delta(a['metric'], a['value'], a['baseline_28d'])}"
    )


def load_context(df: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    """近期训练负荷：昨日 Strain、近 3 日均值、连续高负荷天数。"""
    if "strain" not in df:
        return {"available": False}
    s = df["strain"].astype(float)
    yday = as_of - timedelta(days=1)
    if yday not in s.index:
        return {"available": False}
    a = analyze_metric(df, "strain", yday, light=True)
    if not a.get("available"):
        return {"available": False}
    last3 = s.loc[:yday].iloc[-3:]
    base = a.get("baseline_28d")
    avg3 = st.clean(last3.mean())
    p75s = s.shift(1).rolling(90, min_periods=20).quantile(0.75)
    p75 = st.clean(p75s.get(yday))
    streak = int(_run_length(s > p75s).get(yday, 0))
    z = a.get("z_score_28d") or 0
    dev = a.get("deviation_pct_28d") or 0
    avg3_dev = st.pct_change(avg3, base)
    high = bool((z >= 1.3 and dev >= 0.15) or dev >= 0.35 or (avg3_dev is not None and avg3_dev >= 0.2) or streak >= 3)
    values = "、".join(f"{v:.1f}" for v in last3.dropna().tolist())
    text = f"昨日 Strain {a['value_text']}，28 日均值 {base:.1f}" if base is not None else f"昨日 Strain {a['value_text']}"
    if len(last3.dropna()) >= 2:
        text += f"；最近 3 天分别为 {values}"
    return {
        "available": True,
        "yesterday": a["value"],
        "yesterday_deviation_pct": a.get("deviation_pct_28d"),
        "yesterday_z": a.get("z_score_28d"),
        "avg_3d": st.r(avg3),
        "avg_3d_deviation_pct": st.r(avg3_dev, 4),
        "baseline_28d": base,
        "p75_90d": st.r(p75),
        "high_strain_streak": streak,
        "high_load": high,
        "text": text,
    }


def sleep_context(df: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    a = analyze_metric(df, "sleep_duration", as_of, light=True)
    if not a.get("available"):
        return {"available": False}
    s = df["sleep_duration"].astype(float)
    base = a.get("baseline_28d")
    last4 = st.clean(s.loc[:as_of].iloc[-4:].mean())
    diff4 = (last4 - base) if (last4 is not None and base is not None) else None
    diff_today = (a["value"] - base) if (a.get("value") is not None and base is not None) else None
    debt = st.clean(df["sleep_debt"].get(as_of)) if "sleep_debt" in df else None
    need = st.clean(df["sleep_need"].get(as_of)) if "sleep_need" in df else None
    low = bool(
        (diff_today is not None and base and diff_today <= -max(30.0, 0.08 * base))
        or (diff4 is not None and diff4 <= -25)
        or (debt is not None and debt >= 60)
    )
    return {
        "available": True,
        "last_night": a["value"],
        "last_night_text": a["value_text"],
        "baseline_28d": base,
        "diff_vs_baseline_min": st.r(diff_today, 0),
        "avg_4d": st.r(last4, 0),
        "avg_4d_diff_min": st.r(diff4, 0),
        "sleep_debt_min": st.r(debt, 0),
        "sleep_need_min": st.r(need, 0),
        "low": low,
    }


def assess(
    df: pd.DataFrame,
    as_of: pd.Timestamp,
    rules: dict,
    analyses: dict | None = None,
    events: list[dict] | None = None,
    flags: pd.DataFrame | None = None,
) -> dict:
    analyses = analyses or {
        m: analyze_metric(df, m, as_of, light=True)
        for m in ("hrv", "rhr", "recovery", "sleep_duration", "resp_rate", "skin_temp")
    }
    hrv = analyses.get("hrv", {})
    if not hrv.get("available") or hrv.get("baseline_days", 0) < 7:
        label, sev = STATES["calibrating"]
        return {
            "state": "calibrating",
            "label": label,
            "severity": sev,
            "headline": "个人基线数据还不够（少于 7 天），目前只能参考 WHOOP 原始分数。",
            "explanation": "",
            "caution": "随着数据积累到 28 天以上，个人化分析会越来越准确。",
            "signals": [],
            "confidence": "low",
            "training_level": "normal",
            "context_events": [],
        }

    flags = flags if flags is not None else signal_flags(df, rules)
    neg = {m for m in flags.columns if as_of in flags.index and bool(flags.at[as_of, m])}
    load = load_context(df, as_of)
    sleep = sleep_context(df, as_of)
    high_load = bool(load.get("high_load"))
    sleep_low = bool(sleep.get("low"))

    pos = set()
    if (hrv.get("deviation_pct_28d") or 0) >= 0.07:
        pos.add("hrv")
    rhr = analyses.get("rhr", {})
    if (rhr.get("deviation_pct_28d") or 0) <= -0.04:
        pos.add("rhr")
    if sleep.get("available") and (sleep.get("diff_vs_baseline_min") or 0) >= 20 and not sleep_low:
        pos.add("sleep")

    # ---- 信号列表（给前端和 LLM 看的证据）
    signals = []
    for m in ("hrv", "rhr", "recovery", "resp_rate", "skin_temp"):
        a = analyses.get(m) or analyze_metric(df, m, as_of, light=True)
        sent = _metric_sentence(a)
        if m in neg and sent:
            signals.append({"metric": m, "direction": "negative", "text": sent})
        elif m in pos and sent:
            signals.append({"metric": m, "direction": "positive", "text": sent})
    if sleep.get("available"):
        diff = sleep.get("diff_vs_baseline_min")
        diff4 = sleep.get("avg_4d_diff_min")
        txt = f"昨晚睡眠 {sleep['last_night_text']}"
        if diff is not None:
            txt += f"，比 28 日平均{'少' if diff < 0 else '多'} {fmt_minutes(abs(diff))}"
        if diff4 is not None and abs(diff4) >= 20:
            txt += f"；最近 4 天平均比平时{'少' if diff4 < 0 else '多'} {fmt_minutes(abs(diff4))}"
        if sleep.get("sleep_debt_min"):
            txt += f"；睡眠负债约 {fmt_minutes(sleep['sleep_debt_min'])}"
        signals.append({"metric": "sleep", "direction": "negative" if sleep_low else ("positive" if "sleep" in pos else "neutral"), "text": txt})
    if load.get("available"):
        signals.append({"metric": "strain", "direction": "negative" if high_load else "neutral", "text": load["text"]})

    core_neg = neg & {"hrv", "rhr"}
    illness_like = {"hrv", "rhr"} <= neg and bool(neg & {"resp_rate", "skin_temp"}) and not high_load
    factors = len(neg & {"hrv", "rhr", "recovery"}) + int(sleep_low) + int(high_load)
    hrv_streak = hrv.get("consecutive_unfavorable_days", 0)
    rhr_streak = rhr.get("consecutive_unfavorable_days", 0)
    sustained = max(hrv_streak, rhr_streak) >= 5

    if illness_like:
        state = "non_training_stress"
    elif {"hrv", "rhr"} <= neg and factors >= 3:
        state = "systemic_decline" if sustained else "short_term_under_recovery"
    elif "hrv" in neg and ("rhr" in neg or sleep_low) and high_load:
        state = "short_term_under_recovery"
    elif (neg & {"hrv", "recovery"}) and sleep_low and not high_load:
        state = "sleep_related"
    elif (neg & {"hrv", "recovery"}) and high_load and not sleep_low:
        state = "load_related"
    elif neg == {"hrv"}:
        state = "isolated_hrv_dip"
    elif neg == {"rhr"}:
        state = "isolated_rhr_rise"
    elif neg == {"recovery"}:
        state = "recovery_low_only"
    elif not neg and sleep_low:
        state = "sleep_short_but_stable"
    elif not neg and high_load:
        state = "load_high_but_absorbed"
    elif not neg and len(pos) >= 2:
        state = "well_recovered"
    elif not neg:
        state = "normal"
    else:
        state = "mixed_decline"

    label, severity = STATES[state]
    if state == "mixed_decline" and len(core_neg) == 2:
        severity = 2

    headline, explanation, caution = _texts(state, analyses, neg, sleep, load, hrv_streak)
    evidence = _evidence(analyses, neg, sleep, load)
    # verdict：去掉证据罗列后的“结论句”，供界面在信号列表下方展示
    verdict = explanation[len(evidence) + 1:] if evidence and explanation.startswith(evidence + "。") else explanation

    # ---- 置信度：基线天数 + 信号一致性
    bdays = hrv.get("baseline_days", 0)
    if bdays >= 21 and (factors >= 3 or state in {"normal", "well_recovered"}):
        confidence = "high"
    elif bdays >= 14:
        confidence = "medium"
    else:
        confidence = "low"
    if state.startswith("isolated"):
        confidence = "medium" if bdays >= 14 else "low"

    # ---- 记忆中的近期事件（只作为“可能相关因素之一”）
    context_events = []
    for ev in events or []:
        context_events.append(ev)
    if severity >= 1 and context_events:
        names = "；".join(f"{e['date']}：{e['content']}" for e in context_events[:3])
        note = f"另外，你最近记录过：{names}。这可能是今天恢复变化的相关因素之一（并非确定原因）。"
        explanation += "\n" + note
        verdict = (verdict + "\n" + note).strip()

    return {
        "state": state,
        "label": label,
        "severity": severity,
        "headline": headline,
        "explanation": explanation,
        "verdict": verdict,
        "caution": caution,
        "negative_signals": sorted(neg),
        "positive_signals": sorted(pos),
        "sleep_low": sleep_low,
        "high_load": high_load,
        "signals": signals,
        "load": load,
        "sleep": sleep,
        "confidence": confidence,
        "training_level": "rest" if state == "non_training_stress" else TRAINING_LEVEL[severity],
        "context_events": context_events,
    }


def _evidence(analyses, neg, sleep, load) -> str:
    """不利方向的关键证据（一句话罗列）。"""
    hrv, rhr = analyses.get("hrv", {}), analyses.get("rhr", {})
    parts = [s for s in (_metric_sentence(hrv) if "hrv" in neg else None,
                         _metric_sentence(rhr) if "rhr" in neg else None) if s]
    if sleep.get("low") and sleep.get("diff_vs_baseline_min") is not None:
        d = sleep["diff_vs_baseline_min"]
        parts.append(f"睡眠 {sleep['last_night_text']}，比平时{'少' if d < 0 else '多'} {fmt_minutes(abs(d))}")
    if load.get("high_load"):
        parts.append(load["text"])
    return "；".join(parts)


def _texts(state, analyses, neg, sleep, load, hrv_streak) -> tuple[str, str, str]:
    hrv, rhr = analyses.get("hrv", {}), analyses.get("rhr", {})
    evidence = _evidence(analyses, neg, sleep, load)
    caution_default = "以上为个人数据的相关性分析，不构成医学诊断。"

    if state == "non_training_stress":
        return (
            "HRV 下降、静息心率升高，同时呼吸频率/皮肤温度也偏离平时，而近期训练负荷并不高。",
            f"{evidence}。这种组合不太像单纯的训练疲劳，有时会与生病早期、饮酒、睡眠环境或心理压力等非训练因素同时出现。",
            "如果同时感觉不适（咽痛、发热、乏力等），建议优先休息并关注身体变化，必要时就医。本分析不构成医学诊断。",
        )
    if state == "systemic_decline":
        return (
            "HRV、静息心率等多个恢复指标同时向不利方向变化，并已持续多天，整体恢复状态明显下降。",
            f"{evidence}。这不是单一指标的随机波动，而是多个方向同时指向恢复不足。",
            "多指标同步变差只说明“恢复跟不上”，不能直接断定为过度训练；建议结合主观疲劳、睡眠和生活压力一起判断。"
            + caution_default,
        )
    if state == "short_term_under_recovery":
        streak_txt = f"HRV 已连续 {hrv_streak} 天低于个人基线，" if hrv_streak >= 2 else ""
        return (
            f"{streak_txt}今天不是单一指标异常，多个恢复指标同时显示低于你的正常水平。",
            f"{evidence}。综合来看更像是“短期恢复不足”，而不是单纯的 HRV 随机波动。",
            "这是短期状态判断，不代表“过度训练”。通常在 1-3 天的减量和充足睡眠后会回到基线。" + caution_default,
        )
    if state == "sleep_related":
        return (
            "恢复指标下降与近期睡眠不足在时间上重合。",
            f"{evidence}。训练负荷并不突出，睡眠更可能是相关因素之一（存在相关趋势，不代表确定因果）。",
            caution_default,
        )
    if state == "load_related":
        return (
            "恢复指标下降出现在高训练负荷之后。",
            f"{evidence}。睡眠基本正常，近期训练负荷偏高可能是相关因素之一。",
            caution_default,
        )
    if state == "isolated_hrv_dip":
        return (
            "目前主要是 HRV 单项偏低，其余恢复指标暂未出现同步恶化。",
            f"{_metric_sentence(hrv) or 'HRV 偏低'}；静息心率、睡眠和训练负荷都在个人正常范围内。",
            "不建议根据单日 HRV 做过强判断，HRV 本身日间波动较大，可以观察接下来 1-2 天是否持续。",
        )
    if state == "isolated_rhr_rise":
        return (
            "目前主要是静息心率单项偏高，HRV 与睡眠没有同步变差。",
            f"{_metric_sentence(rhr) or '静息心率偏高'}。单独的 RHR 升高可能与晚餐时间、饮水、室温、咖啡因等有关。",
            "单一指标的短期变化不宜过度解读，如持续多天升高再重点关注。",
        )
    if state == "recovery_low_only":
        return (
            "WHOOP Recovery 低于你的平常水平，但 HRV 与静息心率基本稳定。",
            "Recovery 分数下降主要来自其他分项（如睡眠表现），核心心血管恢复指标没有明显变差。",
            "可以正常安排，但避免额外加量。",
        )
    if state == "sleep_short_but_stable":
        return (
            "睡眠偏少，但 HRV、静息心率暂时稳定。",
            f"昨晚睡眠 {sleep.get('last_night_text')}。恢复指标暂未受明显影响，但持续睡眠不足通常会在之后几天体现。",
            "今晚尽量补足睡眠。",
        )
    if state == "load_high_but_absorbed":
        return (
            "近期训练负荷偏高，但恢复指标保持稳定，身体暂时吸收良好。",
            f"{load.get('text', '')}。HRV 和静息心率都在个人正常范围内。",
            "可以按计划训练，但连续高负荷时注意安排恢复日。",
        )
    if state == "well_recovered":
        return (
            "多个恢复指标优于你的个人基线，今天恢复状态良好。",
            "HRV、静息心率和睡眠至少有两项优于平时，且没有不利信号。",
            "状态好时适合安排高质量训练，但也不必为了“利用好状态”而临时大幅加量。",
        )
    if state == "mixed_decline":
        return (
            "有多个指标出现轻度不利偏离，但还没有形成明确的同步恶化模式。",
            f"{evidence or '部分指标偏离个人基线'}。",
            "建议保持计划但控制强度，观察明天的变化。",
        )
    return (
        "核心恢复指标都在你的个人正常范围内，状态平稳。",
        "HRV、静息心率和睡眠没有明显偏离个人基线，近期负荷也在正常范围。",
        "可以按原计划训练。",
    )
