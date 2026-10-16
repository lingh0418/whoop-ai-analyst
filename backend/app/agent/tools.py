"""Agent Tools：LLM 只能通过这些工具获取真实数据，所有统计都由 Python 分析层完成。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import anomaly as anomaly_mod
from app.analytics import stats as st
from app.analytics.analysis import analyze_metric, history
from app.analytics.drivers import recovery_drivers
from app.analytics.metrics import METRICS, resolve_metric
from app.analytics.similar import find_similar_days
from app.analytics.timeseries import load_daily_frame
from app.coaching import training
from app.memory import service as memory
from app.models import LearnedPattern, MetricAnomaly, User, WhoopWorkout
from app.reports.daily import anomaly_to_dict, get_daily_report, pattern_to_dict
from app.reports.weekly import get_weekly_report, week_start_of


@dataclass
class ToolContext:
    db: Session
    user: User
    _df: pd.DataFrame | None = field(default=None, repr=False)
    saved_memories: list[dict] = field(default_factory=list)

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            self._df = load_daily_frame(self.db, self.user.id)
        return self._df

    @property
    def today(self) -> date:
        return self.df.index.max().date() if not self.df.empty else date.today()


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., dict]


def _days_param(default: int, maximum: int = 365) -> dict:
    return {"type": "integer", "description": f"回看天数（默认 {default}，最大 {maximum}）", "minimum": 1, "maximum": maximum}


def _clamp(days, default: int, maximum: int = 365) -> int:
    try:
        return max(1, min(int(days or default), maximum))
    except (TypeError, ValueError):
        return default


def _compact_history(ctx: ToolContext, metric: str, days: int) -> dict:
    df = ctx.df
    if df.empty:
        return {"available": False}
    h = history(df, metric, days)
    a = analyze_metric(df, metric)
    a.pop("recent", None)
    points = h["points"]
    if days > 60:
        # 长周期按周聚合，节省上下文
        s = pd.Series({pd.Timestamp(p["date"]): p["value"] for p in points}, dtype=float)
        weekly = s.resample("W-SUN").agg(["mean", "min", "max", "count"])
        series = [
            {"week_end": d.date().isoformat(), "mean": st.r(r["mean"]), "min": st.r(r["min"]), "max": st.r(r["max"]), "n": int(r["count"])}
            for d, r in weekly.iterrows()
        ]
    else:
        series = [{"date": p["date"], "value": p["value"], "baseline_28d": p["baseline"], "deviation_pct": p["deviation_pct"]} for p in points]
    return {"metric": metric, "label": METRICS[metric].label, "unit": METRICS[metric].unit, "days": days,
            "period_summary": h["summary"], "today_analysis": a, "series": series}


# --------------------------------------------------------------------------- 工具实现


def get_today_whoop(ctx: ToolContext) -> dict:
    r = get_daily_report(ctx.db, ctx.user)
    if not r.get("available"):
        return r
    j = r["joint"]
    return {
        "date": r["date"],
        "body_state_score": r["state"]["score"],
        "level": r["state"]["level_label"],
        "trend": r["state"]["trend"]["text"],
        "joint_assessment": {k: j.get(k) for k in ("state", "label", "headline", "explanation", "caution", "confidence",
                                                     "negative_signals", "positive_signals", "sleep_low", "high_load")},
        "tiles": [{k: t.get(k) for k in ("label", "value_text", "baseline_text", "delta_text", "z", "status",
                                         "consecutive_unfavorable_days")} for t in r["tiles"]],
        "strain_today_so_far": r.get("strain_today"),
        "sleep_detail": j.get("sleep"),
        "load_detail": j.get("load"),
        "anomalies_today": [a["message"] for a in r["anomalies"]],
        "long_term_context": r.get("long_term"),
        "similar_days_summary": (r.get("similar_days") or {}).get("summary"),
        "recent_events_from_memory": r.get("events"),
    }


def get_recovery_history(ctx: ToolContext, days: int = 28) -> dict:
    return _compact_history(ctx, "recovery", _clamp(days, 28))


def get_hrv_history(ctx: ToolContext, days: int = 28) -> dict:
    return _compact_history(ctx, "hrv", _clamp(days, 28))


def get_rhr_history(ctx: ToolContext, days: int = 28) -> dict:
    return _compact_history(ctx, "rhr", _clamp(days, 28))


def get_strain_history(ctx: ToolContext, days: int = 28) -> dict:
    return _compact_history(ctx, "strain", _clamp(days, 28))


def get_sleep_history(ctx: ToolContext, days: int = 14) -> dict:
    days = _clamp(days, 14)
    out = _compact_history(ctx, "sleep_duration", days)
    df = ctx.df
    if df.empty:
        return out
    extra = {}
    for m in ("sleep_performance", "sleep_need", "sleep_debt", "sleep_consistency", "sleep_efficiency", "deep_sleep",
              "rem_sleep", "disturbances", "bedtime"):
        a = analyze_metric(df, m)
        if a.get("available"):
            extra[m] = {k: a.get(k) for k in ("label", "value_text", "avg_7d", "baseline_28d", "deviation_pct_28d",
                                              "z_score_28d", "status")}
    out["other_sleep_metrics_today"] = extra
    if days <= 31:
        tail = df.iloc[-days:]
        out["nightly"] = [
            {"date": d.date().isoformat(), "sleep_min": st.r(r["sleep_duration"], 0), "performance": st.r(r["sleep_performance"], 0),
             "consistency": st.r(r["sleep_consistency"], 0), "deep_min": st.r(r["deep_sleep"], 0), "rem_min": st.r(r["rem_sleep"], 0),
             "debt_min": st.r(r["sleep_debt"], 0), "bedtime_h_since_noon": st.r(r["bedtime"], 2)}
            for d, r in tail.iterrows()
        ]
        out.pop("series", None)
    return out


def get_workout_history(ctx: ToolContext, days: int = 28) -> dict:
    days = _clamp(days, 28)
    since = ctx.today - timedelta(days=days - 1)
    rows = list(
        ctx.db.scalars(
            select(WhoopWorkout).where(WhoopWorkout.user_id == ctx.user.id, WhoopWorkout.date >= since).order_by(WhoopWorkout.start)
        )
    )
    items, by_sport = [], {}
    for w in rows:
        mins = (w.end - w.start).total_seconds() / 60
        zones = [w.zone_zero_milli, w.zone_one_milli, w.zone_two_milli, w.zone_three_milli, w.zone_four_milli, w.zone_five_milli]
        items.append(
            {"date": w.date.isoformat(), "sport": w.sport_name, "minutes": round(mins), "strain": st.r(w.strain, 1),
             "avg_hr": w.average_heart_rate, "max_hr": w.max_heart_rate,
             "zone_minutes": [round((z or 0) / 60000) for z in zones]}
        )
        s = by_sport.setdefault(w.sport_name or "unknown", {"count": 0, "minutes": 0.0, "strain": []})
        s["count"] += 1
        s["minutes"] += mins
        if w.strain is not None:
            s["strain"].append(w.strain)
    summary = {
        k: {"count": v["count"], "total_minutes": round(v["minutes"]), "avg_strain": st.r(sum(v["strain"]) / len(v["strain"]), 1) if v["strain"] else None}
        for k, v in by_sport.items()
    }
    return {"days": days, "total_workouts": len(items), "per_week": round(len(items) / days * 7, 1), "by_sport": summary, "workouts": items[-40:]}


def get_personal_baseline(ctx: ToolContext, metric: str) -> dict:
    m = resolve_metric(metric)
    a = analyze_metric(ctx.df, m)
    keys = ("label", "unit", "value", "value_text", "avg_7d", "baseline_7d", "baseline_28d", "median_28d", "std_28d",
            "baseline_90d", "p10_90d", "p90_90d", "baseline_days", "cv_28d", "cv_90d", "volatility")
    return {k: a.get(k) for k in keys} | {"metric": m, "note": "基线均为当天之前的窗口（不含当天）"}


def get_metric_trend(ctx: ToolContext, metric: str, days: int = 28) -> dict:
    m = resolve_metric(metric)
    days = _clamp(days, 28)
    df = ctx.df
    a = analyze_metric(df, m)
    a.pop("recent", None)
    s = df[m].astype(float).iloc[-days:]
    sl = st.slope(s)
    half = len(s) // 2
    first, second = s.iloc[:half], s.iloc[half:]
    out = {
        "metric": m,
        "label": METRICS[m].label,
        "days": days,
        "slope_per_day": st.r(sl.per_day, 3),
        "pct_per_week": st.r(sl.pct_per_week, 4),
        "p_value": st.r(sl.p_value, 4),
        "direction": sl.direction,
        "first_half_mean": st.r(first.mean()),
        "second_half_mean": st.r(second.mean()),
        "second_vs_first_pct": st.r(st.pct_change(st.clean(second.mean()), st.clean(first.mean())), 4),
        "today": a,
    }
    if days >= 60:
        monthly = s.resample("MS").agg(["mean", "std", "count"])
        out["monthly"] = [
            {"month": d.strftime("%Y-%m"), "mean": st.r(r["mean"]), "std": st.r(r["std"]), "n": int(r["count"])}
            for d, r in monthly.iterrows()
        ]
    return out


def detect_anomalies(ctx: ToolContext, days: int = 14) -> dict:
    days = _clamp(days, 14, 120)
    since = ctx.today - timedelta(days=days - 1)
    rows = list(
        ctx.db.scalars(
            select(MetricAnomaly).where(MetricAnomaly.user_id == ctx.user.id, MetricAnomaly.date >= since).order_by(MetricAnomaly.date.desc())
        )
    )
    items = [anomaly_to_dict(a) for a in rows if a.severity != "low"]
    return {"days": days, "count": len(items), "anomalies": items[:40],
            "rules_mode": anomaly_mod.load_rules(ctx.user.settings).get("mode")}


def get_recent_events(ctx: ToolContext, days: int = 7) -> dict:
    days = _clamp(days, 7, 90)
    return {"events": memory.recent_events(ctx.db, ctx.user.id, ctx.today, days=days)}


def get_user_profile(ctx: ToolContext) -> dict:
    df = ctx.df
    return {
        "name": ctx.user.name,
        "profile": ctx.user.profile or {},
        "timezone": ctx.user.timezone,
        "data_range": [df.index.min().date().isoformat(), df.index.max().date().isoformat()] if not df.empty else None,
        "days_with_data": int(df["hrv"].notna().sum()) if not df.empty else 0,
        "active_states": memory.active_states(ctx.db, ctx.user.id, ctx.today),
    }


def get_training_plan(ctx: ToolContext, date_str: str | None = None) -> dict:
    day = date.fromisoformat(date_str) if date_str else ctx.today
    r = get_daily_report(ctx.db, ctx.user, day if day <= ctx.today else None)
    plan = training.plan_to_dict(training.plan_for(ctx.db, ctx.user.id, day))
    level = (r.get("joint") or {}).get("training_level", "normal") if r.get("available") else "normal"
    return {"date": day.isoformat(), "plan": plan, "recommended_adjustment": training.adjust(plan, level, r.get("joint"))}


def search_relevant_memory(ctx: ToolContext, query: str, days: int | None = None) -> dict:
    return {"query": query, "results": memory.search(ctx.db, ctx.user.id, query, days=days, today=ctx.today)}


def get_learned_patterns(ctx: ToolContext) -> dict:
    rows = ctx.db.scalars(select(LearnedPattern).where(LearnedPattern.user_id == ctx.user.id, LearnedPattern.active.is_(True)))
    return {"patterns": [pattern_to_dict(p) for p in rows],
            "note": "这些都是用户历史数据中的相关趋势，不代表确定因果"}


def find_similar_days_tool(ctx: ToolContext, date_str: str | None = None) -> dict:
    as_of = pd.Timestamp(date_str) if date_str else ctx.df.index.max()
    return find_similar_days(ctx.df, as_of)


def analyze_recovery_drivers(ctx: ToolContext, days: int = 120, outcome: str = "recovery") -> dict:
    outcome = resolve_metric(outcome) if outcome else "recovery"
    return recovery_drivers(ctx.df, _clamp(days, 120), outcome)


def get_daily_report_tool(ctx: ToolContext, date_str: str | None = None) -> dict:
    day = date.fromisoformat(date_str) if date_str else None
    r = get_daily_report(ctx.db, ctx.user, day)
    if not r.get("available"):
        return r
    return {k: r.get(k) for k in ("date", "state", "conclusions", "narrative", "anomalies", "patterns")}


def get_weekly_report_tool(ctx: ToolContext, week_start: str | None = None) -> dict:
    ws = date.fromisoformat(week_start) if week_start else week_start_of(ctx.today)
    r = get_weekly_report(ctx.db, ctx.user, week_start_of(ws))
    r.pop("daily", None)
    return r


def save_memory(ctx: ToolContext, content: str, event_date: str | None = None, category: str | None = None,
                tags: list[str] | None = None) -> dict:
    d = date.fromisoformat(event_date) if event_date else None
    tags = [t for t in (tags or []) if t in memory.TAG_RULES] or None
    m = memory.add_memory(ctx.db, ctx.user.id, content, today=ctx.today, event_date=d, category=category,
                          tags=tags, source="chat")
    item = memory.to_dict(m)
    ctx.saved_memories.append(item)
    return {"saved": True, "memory": item}


# --------------------------------------------------------------------------- 注册表

_METRIC_PARAM = {"type": "string", "description": "指标名：recovery / hrv / rhr / sleep_duration / sleep_performance / strain / sleep_debt / sleep_consistency / deep_sleep / rem_sleep / resp_rate / skin_temp / weight"}
_DATE_PARAM = {"type": "string", "description": "日期 YYYY-MM-DD，不填则为最新一天"}


def _schema(props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


TOOLS: list[Tool] = [
    Tool("get_today_whoop", "获取最新一天的 WHOOP 身体状态：身体状态分、Recovery/HRV/RHR/睡眠/Strain 与个人 28 日基线的偏差、多指标联合判断、今日异常、近期记忆事件。回答“今天怎么样/为什么 Recovery 低”时首先调用。", _schema(), get_today_whoop),
    Tool("get_recovery_history", "Recovery 历史序列与统计（含 28 日基线、偏差、趋势）。超过 60 天按周聚合。", _schema({"days": _days_param(28)}), get_recovery_history),
    Tool("get_hrv_history", "HRV 历史序列与统计：今日值、7/28/90 日均值、个人基线偏差、z-score、趋势斜率、连续低于基线天数、波动性。", _schema({"days": _days_param(28)}), get_hrv_history),
    Tool("get_rhr_history", "静息心率历史序列与统计（同 HRV）。", _schema({"days": _days_param(28)}), get_rhr_history),
    Tool("get_sleep_history", "睡眠历史：时长、表现、需求、睡眠负债、一致性、效率、深睡、REM、夜醒、入睡时间。", _schema({"days": _days_param(14)}), get_sleep_history),
    Tool("get_strain_history", "Strain（训练负荷）历史序列与统计。", _schema({"days": _days_param(28)}), get_strain_history),
    Tool("get_workout_history", "训练记录：类型、时长、Strain、平均/最大心率、心率区间分钟数、按运动类型汇总的频率。", _schema({"days": _days_param(28)}), get_workout_history),
    Tool("get_personal_baseline", "某个指标的个人基线：7/28/90 日均值、中位数、标准差、P10/P90、变异系数。", _schema({"metric": _METRIC_PARAM}, ["metric"]), get_personal_baseline),
    Tool("get_metric_trend", "某个指标在指定天数内的趋势：线性斜率（每周变化%）、p 值、前后半段对比；≥60 天时附带按月均值。用于“最近是变好还是变差”。", _schema({"metric": _METRIC_PARAM, "days": _days_param(90)}, ["metric"]), get_metric_trend),
    Tool("detect_anomalies", "最近 N 天检测到的异常（HRV 异常下降、RHR 升高、睡眠明显减少、Recovery 连续偏低、Strain 突增、多指标同步异常）。", _schema({"days": _days_param(14, 120)}), detect_anomalies),
    Tool("get_recent_events", "长期记忆中最近 N 天的生活事件（饮酒、熬夜、考试、出差、生病等）以及当前生效的状态（减脂期、Deload 等）。", _schema({"days": _days_param(7, 90)}), get_recent_events),
    Tool("get_user_profile", "用户背景：目标、训练年限、数据范围、当前生效的状态。", _schema(), get_user_profile),
    Tool("get_training_plan", "某天的训练计划，以及根据当天 WHOOP 状态给出的调整方案。", _schema({"date_str": _DATE_PARAM}), get_training_plan),
    Tool("search_relevant_memory", "按关键词检索用户长期记忆（如“喝酒”“考试”“减脂”）。", _schema({"query": {"type": "string"}, "days": {"type": "integer", "description": "只看最近 N 天，可选"}}, ["query"]), search_relevant_memory),
    Tool("get_learned_patterns", "系统从用户历史中学到的个人规律（条件 → 结果、样本量、p 值、置信度）。", _schema(), get_learned_patterns),
    Tool("find_similar_days", "在历史中寻找与某天偏离模式（HRV/RHR/睡眠/前日负荷）最相似的日子，以及之后几天的恢复情况。用于“这种情况以前出现过吗”。", _schema({"date_str": _DATE_PARAM}), find_similar_days_tool),
    Tool("analyze_recovery_drivers", "对比恢复最好与最差的 25% 日子在睡眠、入睡时间、前日负荷等方面的差异（Spearman 相关）。用于“什么情况下我的 Recovery 通常最好”。", _schema({"days": _days_param(120), "outcome": {"type": "string", "description": "recovery 或 hrv，默认 recovery"}}), analyze_recovery_drivers),
    Tool("get_daily_report", "某天的完整日报（含结论与规则引擎生成的解读）。", _schema({"date_str": _DATE_PARAM}), get_daily_report_tool),
    Tool("get_weekly_report", "某周的 WHOOP 周报（本周 vs 上周 vs 基线、状态分布、本周新发现的规律）。", _schema({"week_start": {"type": "string", "description": "该周周一 YYYY-MM-DD，不填为本周"}}), get_weekly_report_tool),
    Tool("save_memory", "当用户提到会影响身体恢复的事件或状态时（喝酒、熬夜、考试、生病、出差、开始减脂、Deload 等）保存为长期记忆，便于以后解释 WHOOP 数据。", _schema({
        "content": {"type": "string", "description": "用一句话描述事件，如“昨晚喝了 3 杯啤酒”"},
        "event_date": {"type": "string", "description": "事件发生日期 YYYY-MM-DD（“昨晚”就填昨天）"},
        "category": {"type": "string", "enum": ["event", "state", "preference", "profile"]},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "可选：alcohol, late_night, illness, stress, travel, caffeine_late, late_meal, sauna, cutting, bulking, deload, injury, competition"},
    }, ["content"]), save_memory),
]
TOOL_MAP = {t.name: t for t in TOOLS}


def execute_tool(ctx: ToolContext, name: str, args: dict) -> str:
    tool = TOOL_MAP.get(name)
    if tool is None:
        return json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False)
    try:
        result = tool.fn(ctx, **(args or {}))
    except TypeError as e:
        result = {"error": f"参数错误: {e}"}
    except KeyError as e:
        result = {"error": str(e)}
    except Exception as e:  # noqa: BLE001 —— 工具失败要反馈给模型而不是中断对话
        ctx.db.rollback()
        result = {"error": f"{type(e).__name__}: {e}"}
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > 16000:
        text = text[:16000] + '..."(已截断)"'
    return text
