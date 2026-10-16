"""今日身体状态报告：Dashboard、日报和 Agent 的统一数据来源。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import anomaly as anomaly_mod
from app.analytics import joint as joint_mod
from app.analytics.analysis import analyze_metric
from app.analytics.metrics import fmt_delta, fmt_minutes, fmt_value
from app.analytics.readiness import level_of
from app.analytics.similar import find_similar_days
from app.analytics.timeseries import load_daily_frame
from app.coaching import nutrition, training
from app.memory import service as memory
from app.models import DailyReport, LearnedPattern, MetricAnomaly, User

TILE_METRICS = ["recovery", "hrv", "rhr", "sleep_duration", "strain"]
DETAIL_METRICS = [
    "recovery", "hrv", "rhr", "sleep_duration", "sleep_performance", "sleep_need", "sleep_debt",
    "sleep_consistency", "sleep_efficiency", "deep_sleep", "rem_sleep", "disturbances", "resp_rate",
    "skin_temp", "spo2", "bedtime",
]


def _tile(a: dict, label: str | None = None) -> dict:
    if not a.get("available"):
        return {"metric": a.get("metric"), "label": label or a.get("label"), "available": False}
    dev = a.get("deviation_pct_28d")
    base = a.get("baseline_28d")
    return {
        "metric": a["metric"],
        "label": label or a["label"],
        "available": True,
        "value": a["value"],
        "value_text": a["value_text"],
        "baseline": base,
        "baseline_text": fmt_value(a["metric"], base),
        "deviation_pct": dev,
        "delta_text": fmt_delta(a["metric"], a["value"], base) if base is not None else None,
        "delta_abs": round(a["value"] - base, 2) if (a.get("value") is not None and base is not None) else None,
        "z": a.get("z_score_28d"),
        "status": a.get("status"),
        "direction": a.get("direction"),
        "consecutive_unfavorable_days": a.get("consecutive_unfavorable_days"),
        "trend_7d": (a.get("trend_7d") or {}).get("label"),
        "recent": a.get("recent", []),
    }


def _readiness_trend(df: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    s = df["readiness_score"].loc[:as_of].dropna()
    if len(s) < 2:
        return {"direction": "flat", "consecutive_decline_days": 0, "text": "数据不足"}
    vals = s.tolist()
    dec = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] < vals[i - 1] - 0.5:
            dec += 1
        else:
            break
    inc = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] > vals[i - 1] + 0.5:
            inc += 1
        else:
            break
    last7 = s.iloc[-7:]
    low_streak = 0
    for v in reversed(vals):
        if v < 60:
            low_streak += 1
        else:
            break
    if dec >= 2:
        text, direction = f"连续第 {dec} 天下降", "down"
    elif inc >= 2:
        text, direction = f"连续第 {inc} 天回升", "up"
    elif vals[-1] < vals[-2] - 0.5:
        text, direction = "较昨天下降", "down"
    elif vals[-1] > vals[-2] + 0.5:
        text, direction = "较昨天回升", "up"
    else:
        text, direction = "与昨天持平", "flat"
    if low_streak >= 2 and dec < 2:
        text += f"，但已连续 {low_streak} 天处于偏低水平"
    return {
        "direction": direction,
        "low_streak_days": low_streak,
        "consecutive_decline_days": dec,
        "consecutive_rise_days": inc,
        "text": text,
        "last7": [{"date": d.date().isoformat(), "score": float(v)} for d, v in last7.items()],
        "avg7": round(float(last7.mean()), 1),
    }


def _relevant_patterns(db: Session, user_id: int, joint: dict, events: list[dict]) -> list[dict]:
    rows = list(db.scalars(select(LearnedPattern).where(LearnedPattern.user_id == user_id, LearnedPattern.active.is_(True))))
    wanted: set[str] = set()
    if joint.get("sleep_low"):
        wanted |= {"sleep"}
    if joint.get("high_load"):
        wanted |= {"strain"}
    tags = {t for e in events for t in e.get("tags", [])}
    picked = []
    for p in rows:
        if p.category in wanted or any(p.key == f"event_{t}_hrv" for t in tags):
            picked.append(p)
    order = {"high": 0, "medium": 1, "low": 2}
    picked.sort(key=lambda p: (order.get(p.confidence, 3), -abs(p.effect)))
    return [pattern_to_dict(p) for p in picked[:3]]


def pattern_to_dict(p: LearnedPattern) -> dict:
    return {
        "key": p.key,
        "category": p.category,
        "title": p.title,
        "description": p.description,
        "condition": p.condition,
        "outcome_metric": p.outcome_metric,
        "effect": p.effect,
        "effect_unit": p.effect_unit,
        "condition_mean": p.condition_mean,
        "baseline_mean": p.baseline_mean,
        "sample_size": p.sample_size,
        "comparison_size": p.comparison_size,
        "p_value": p.p_value,
        "confidence": p.confidence,
        "first_detected": p.first_detected.isoformat(),
        "last_updated": p.last_updated.isoformat(),
        "active": p.active,
    }


def anomaly_to_dict(a: MetricAnomaly) -> dict:
    return {
        "date": a.date.isoformat(),
        "rule": a.rule,
        "label": (a.details or {}).get("label", a.rule),
        "metric": a.metric,
        "severity": a.severity,
        "value": a.value,
        "baseline": a.baseline,
        "deviation_pct": a.deviation_pct,
        "z_score": a.z_score,
        "message": a.message,
    }


def _long_term_context(analyses: dict) -> str | None:
    hrv = analyses.get("hrv", {})
    t90 = (hrv.get("trend_90d") or {})
    dev = hrv.get("deviation_pct_28d")
    if not hrv.get("available") or dev is None:
        return None
    if t90.get("direction") == "up" and dev < -0.05:
        return (f"从 90 天看，你的 HRV 整体呈上升趋势（约 {t90['pct_per_week'] * 100:+.1f}%/周），"
                "今天的下降发生在长期向好的背景下，更可能是短期波动。")
    if t90.get("direction") == "down":
        return (f"需要留意：过去 90 天 HRV 整体呈下降趋势（约 {t90['pct_per_week'] * 100:+.1f}%/周），"
                "建议关注长期的睡眠、压力与训练安排。")
    if t90.get("direction") == "up":
        return f"过去 90 天 HRV 整体呈上升趋势（约 {t90['pct_per_week'] * 100:+.1f}%/周），长期恢复能力在改善。"
    return None


def build_daily_payload(db: Session, user: User, day: date | None = None) -> dict:
    df = load_daily_frame(db, user.id)
    if df.empty:
        return {"available": False, "reason": "暂无数据，请先连接 WHOOP 或生成 Demo 数据"}
    as_of = pd.Timestamp(day) if day else df.index.max()
    if as_of not in df.index:
        return {"available": False, "reason": f"{as_of.date()} 没有数据"}

    rules = anomaly_mod.load_rules(user.settings)
    analyses = {m: analyze_metric(df, m, as_of) for m in DETAIL_METRICS}
    strain_today = analyze_metric(df, "strain", as_of)
    strain_yday = analyze_metric(df, "strain", as_of - timedelta(days=1))
    events = memory.recent_events(db, user.id, as_of.date(), days=2)
    joint = joint_mod.assess(df, as_of, rules, analyses=analyses, events=[e for e in events if e["category"] == "event"])

    score = df.at[as_of, "readiness_score"]
    score = None if pd.isna(score) else float(score)
    level_key, level_label = level_of(score)
    rtrend = _readiness_trend(df, as_of)

    tiles = [_tile(analyses["recovery"]), _tile(analyses["hrv"]), _tile(analyses["rhr"]),
             _tile(analyses["sleep_duration"], "睡眠"), _tile(strain_yday, "昨日 Strain")]
    tiles[-1]["today_value"] = strain_today.get("value")

    anomalies = [
        anomaly_to_dict(a)
        for a in db.scalars(select(MetricAnomaly).where(MetricAnomaly.user_id == user.id, MetricAnomaly.date == as_of.date()))
    ]
    anomalies.sort(key=lambda a: -anomaly_mod.SEVERITY_ORDER[a["severity"]])

    patterns = _relevant_patterns(db, user.id, joint, events)
    similar = find_similar_days(df, as_of)
    long_term = _long_term_context(analyses)

    # ---- 训练 / 饮食（第二层）
    tplan = training.plan_to_dict(training.plan_for(db, user.id, as_of.date()))
    tadvice = training.adjust(tplan, joint["training_level"], joint)
    nplan = nutrition.plan_to_dict(nutrition.plan_for(db, user.id, as_of.date()))
    nadvice = nutrition.advise(nplan, joint, tadvice, user.profile)

    # ---- 三个最重要的结论
    conclusions = [joint["headline"]]
    neg_sorted = sorted(
        [analyses[m] for m in ("hrv", "rhr", "sleep_duration") if analyses[m].get("available")],
        key=lambda a: -abs(a.get("z_score_28d") or 0),
    )
    if neg_sorted and abs(neg_sorted[0].get("z_score_28d") or 0) >= 1:
        a = neg_sorted[0]
        txt = (f"变化最大的是{a['label']}：{a['value_text']}，比 28 日基线 {fmt_value(a['metric'], a['baseline_28d'])} "
               f"{fmt_delta(a['metric'], a['value'], a['baseline_28d'])}")
        if a.get("consecutive_unfavorable_days", 0) >= 2:
            txt += f"，已连续 {a['consecutive_unfavorable_days']} 天处于不利一侧"
        conclusions.append(txt + "。")
    if patterns:
        conclusions.append(f"历史规律：{patterns[0]['title']}（样本 {patterns[0]['sample_size']} 天，置信度 {patterns[0]['confidence']}）。")
    elif long_term:
        conclusions.append(long_term)
    conclusions.append(f"训练建议：{tadvice['summary']}。")
    conclusions = conclusions[:3] if len(conclusions) > 3 else conclusions

    payload = {
        "available": True,
        "date": as_of.date().isoformat(),
        "data_start": df.index.min().date().isoformat(),
        "data_days": int(df["hrv"].notna().sum()),
        "state": {
            "score": score,
            "level": level_key,
            "level_label": level_label,
            "trend": rtrend,
            "joint_state": joint["state"],
            "joint_label": joint["label"],
            "severity": joint["severity"],
            "confidence": joint["confidence"],
        },
        "tiles": tiles,
        "strain_today": strain_today.get("value"),
        "metrics": analyses,
        "joint": joint,
        "conclusions": conclusions,
        "long_term": long_term,
        "anomalies": anomalies,
        "patterns": patterns,
        "similar_days": similar,
        "events": events,
        "training": tadvice,
        "nutrition": {"plan": nplan, "advice": nadvice},
    }
    payload["narrative"] = render_narrative(payload)
    return payload


def render_narrative(p: dict) -> str:
    """规则引擎生成的中文日报（未配置 LLM 时直接展示，配置 LLM 后作为其事实依据）。"""
    st, j = p["state"], p["joint"]
    lines = [f"## 今日身体状态：{st['score']:.0f} / 100（{st['level_label']}）" if st["score"] is not None else "## 今日身体状态"]
    lines.append(f"趋势：{st['trend']['text']}　｜　联合判断：**{j['label']}**（置信度 {j['confidence']}）")
    lines.append("")
    lines.append("### 今天最重要的变化")
    for t in p["tiles"]:
        if not t.get("available"):
            continue
        extra = f"，比 28 日基线 {t['baseline_text']} {t['delta_text']}" if t.get("delta_text") else ""
        lines.append(f"- **{t['label']}**：{t['value_text']}{extra}")
    sleep = j.get("sleep") or {}
    if sleep.get("avg_4d_diff_min") is not None and abs(sleep["avg_4d_diff_min"]) >= 20:
        d = sleep["avg_4d_diff_min"]
        lines.append(f"- 最近 4 天平均睡眠比个人 28 日平均{'少' if d < 0 else '多'} {fmt_minutes(abs(d))}")
    lines.append("")
    lines.append("### AI 判断")
    lines.append(j["headline"])
    if j.get("explanation"):
        lines.append("")
        lines.append(j["explanation"])
    if p.get("long_term"):
        lines.append("")
        lines.append(p["long_term"])
    if p.get("similar_days", {}).get("summary"):
        lines.append("")
        lines.append(p["similar_days"]["summary"])
    lines.append("")
    lines.append(f"> {j['caution']}")
    lines.append("")
    tr = p["training"]
    lines.append("### 训练")
    if tr.get("original"):
        lines.append(f"原计划：{tr['original']['title']} → **{tr['summary']}**")
    else:
        lines.append(tr["summary"])
    for c in tr.get("changes", []):
        lines.append(f"- {c}")
    lines.append("")
    lines.append("### 饮食")
    for t in p["nutrition"]["advice"]:
        lines.append(f"- {t}")
    return "\n".join(lines)


def get_daily_report(db: Session, user: User, day: date | None = None, refresh: bool = False) -> dict:
    """带缓存的日报（数据重算时 pipeline 会清理最近几天的缓存）。"""
    from app.analytics.pipeline import latest_date

    day = day or latest_date(db, user.id)
    if day is None:
        return {"available": False, "reason": "暂无数据，请先连接 WHOOP 或生成 Demo 数据"}
    cached = db.scalar(select(DailyReport).where(DailyReport.user_id == user.id, DailyReport.date == day))
    if cached and not refresh:
        return {**cached.payload, "ai_summary": cached.ai_summary, "ai_model": cached.ai_model}
    payload = build_daily_payload(db, user, day)
    if not payload.get("available"):
        return payload
    if cached is None:
        cached = DailyReport(user_id=user.id, date=day, payload=payload, narrative=payload["narrative"])
        db.add(cached)
    else:
        cached.payload = payload
        cached.narrative = payload["narrative"]
        cached.ai_summary = None
        cached.ai_model = None
    db.commit()
    return {**payload, "ai_summary": cached.ai_summary, "ai_model": cached.ai_model}


def save_ai_summary(db: Session, user: User, day: date, text: str, model: str) -> None:
    cached = db.scalar(select(DailyReport).where(DailyReport.user_id == user.id, DailyReport.date == day))
    if cached:
        cached.ai_summary = text
        cached.ai_model = model
        db.commit()
