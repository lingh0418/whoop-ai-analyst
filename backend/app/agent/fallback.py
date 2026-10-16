"""未配置大模型时的规则引擎问答：基于意图路由调用同一套工具，用模板生成中文回答。

它保证项目在零 API Key 的情况下也能完整演示“调用真实数据 → 联合分析 → 中文解释”的链路。
"""

from __future__ import annotations

import json
import re

from app.agent.tools import TOOL_MAP, ToolContext
from app.analytics.metrics import METRICS, fmt_delta, fmt_value
from app.memory import service as memory

CONF = {"high": "高", "medium": "中", "low": "低"}

INTENTS: list[tuple[str, list[str]]] = [
    ("drivers", ["什么情况下", "通常最好", "怎样才能", "影响因素", "什么因素", "怎么提高", "如何提高"]),
    ("patterns", ["规律", "pattern", "模式", "学到"]),
    ("similar", ["以前", "什么时候出现", "出现过", "类似", "相似"]),
    ("anomaly", ["异常", "有没有问题", "正常吗", "是否正常"]),
    ("strain", ["负荷", "strain", "训练量", "练太多", "过度训练", "练得太"]),
    ("training", ["今天练", "训练计划", "怎么练", "能不能练", "训练建议", "要不要练", "还能练"]),
    ("weekly", ["这周", "本周", "这一周", "周报", "上周"]),
    ("hrv", ["hrv", "心率变异"]),
    ("rhr", ["rhr", "静息心率"]),
    ("sleep", ["睡眠", "睡觉", "睡得", "失眠"]),
    ("recovery_trend", ["恢复怎么样", "恢复如何", "恢复情况"]),
]


def _detect_days(text: str) -> int | None:
    if re.search(r"(3|三)\s*个?月|90\s*天|季度|长期", text):
        return 90
    if re.search(r"(1|一)\s*个?月|30\s*天|28\s*天|这个月|最近一月", text):
        return 28
    if re.search(r"(2|两)\s*周|14\s*天", text):
        return 14
    if re.search(r"一周|7\s*天|这周|本周", text):
        return 7
    if re.search(r"半年|180\s*天|6\s*个月", text):
        return 180
    return None


def _call(ctx: ToolContext, trace: list, name: str, **args) -> dict:
    result = TOOL_MAP[name].fn(ctx, **args)
    trace.append({"name": name, "args": args, "result": json.dumps(result, ensure_ascii=False, default=str)[:300]})
    return result


def _trend_word(direction: str) -> str:
    return {"up": "上升", "down": "下降", "flat": "没有明显趋势（平稳）"}.get(direction, direction)


def _metric_answer(ctx: ToolContext, trace: list, metric: str, days: int) -> str:
    t = _call(ctx, trace, "get_metric_trend", metric=metric, days=days)
    a = t["today"]
    label = METRICS[metric].label
    lines = [f"### 过去 {days} 天的{label}"]
    if t.get("first_half_mean") is not None:
        chg = t.get("second_vs_first_pct")
        lines.append(
            f"- 前半段平均 {fmt_value(metric, t['first_half_mean'])} → 后半段平均 {fmt_value(metric, t['second_half_mean'])}"
            + (f"（{chg * 100:+.1f}%）" if chg is not None else "")
        )
    if t.get("pct_per_week") is not None:
        lines.append(f"- 线性趋势：{_trend_word(t['direction'])}，约 {t['pct_per_week'] * 100:+.1f}%/周（p={t['p_value']}）")
    for m in t.get("monthly", [])[-4:]:
        lines.append(f"  - {m['month']}：月均 {fmt_value(metric, m['mean'])}（{m['n']} 天）")
    if a.get("available"):
        lines.append(f"- 最新一天 {a['value_text']}，比 28 日个人基线 {fmt_value(metric, a['baseline_28d'])} "
                     f"{fmt_delta(metric, a['value'], a['baseline_28d'])}（z={a['z_score_28d']}，90 日百分位 {a.get('percentile_90d')}）")
        if a.get("consecutive_unfavorable_days", 0) >= 2:
            lines.append(f"- 已连续 {a['consecutive_unfavorable_days']} 天处于不利一侧")
        if a.get("volatility"):
            lines.append(f"- 波动性：{a['volatility']}（28 日变异系数 {a['cv_28d']}，90 日 {a['cv_90d']}）")
    pats = [p for p in _call(ctx, trace, "get_learned_patterns")["patterns"] if p["outcome_metric"] == metric][:3]
    if pats:
        lines.append("\n**相关的个人规律（相关趋势，非因果）**")
        lines += [f"- {p['title']}（样本 {p['sample_size']} 天，置信度 {CONF.get(p['confidence'], p['confidence'])}）" for p in pats]
    events = _call(ctx, trace, "get_recent_events", days=7)["events"]
    if events:
        lines.append("\n**最近记录的事件**：" + "；".join(f"{e['date']} {e['content']}" for e in events[:4]))
    return "\n".join(lines)


def _today_answer(ctx: ToolContext, trace: list) -> str:
    t = _call(ctx, trace, "get_today_whoop")
    if "joint_assessment" not in t:
        return t.get("reason", "暂无数据")
    j = t["joint_assessment"]
    lines = [f"**今日身体状态 {t['body_state_score']:.0f}/100（{t['level']}），{t['trend']}。联合判断：{j['label']}。**", "", j["headline"], ""]
    for tile in t["tiles"]:
        if tile.get("value_text"):
            extra = f"，比 28 日基线 {tile['baseline_text']} {tile['delta_text']}" if tile.get("delta_text") else ""
            lines.append(f"- {tile['label']}：{tile['value_text']}{extra}")
    if j.get("explanation"):
        lines += ["", j["explanation"]]
    if t.get("similar_days_summary"):
        lines += ["", t["similar_days_summary"]]
    tp = _call(ctx, trace, "get_training_plan")
    adj = tp["recommended_adjustment"]
    lines += ["", f"**训练建议**：{adj['summary']}"] + [f"- {c}" for c in adj.get("changes", [])]
    lines += ["", f"> {j['caution']}"]
    return "\n".join(lines)


def _strain_answer(ctx: ToolContext, trace: list) -> str:
    t = _call(ctx, trace, "get_today_whoop")
    w = _call(ctx, trace, "get_workout_history", days=28)
    tr = _call(ctx, trace, "get_metric_trend", metric="strain", days=28)
    load = t.get("load_detail") or {}
    j = t.get("joint_assessment") or {}
    lines = ["### 近期训练负荷"]
    if load.get("available"):
        lines.append(f"- {load['text']}")
        if load.get("avg_3d_deviation_pct") is not None:
            lines.append(f"- 近 3 天平均 Strain {load['avg_3d']:.1f}，比 28 日均值 {load['avg_3d_deviation_pct'] * 100:+.0f}%")
        if load.get("high_strain_streak"):
            lines.append(f"- 已连续 {load['high_strain_streak']} 天高于你的 90 日 P75（{load['p75_90d']}）")
    lines.append(f"- 过去 28 天训练 {w['total_workouts']} 次（约每周 {w['per_week']} 次），Strain 趋势：{_trend_word(tr['direction'])}")
    lines.append("")
    lines.append("### 恢复指标是否跟得上")
    neg = j.get("negative_signals") or []
    if neg:
        lines.append(f"同时出现不利偏离的恢复指标：{'、'.join(METRICS[m].label for m in neg if m in METRICS)}。联合判断：{j.get('label')}。")
    else:
        lines.append("HRV、静息心率目前都在个人正常范围内，身体对当前负荷吸收良好。")
    lines.append("")
    lines.append("> 负荷高 + 恢复指标同步下降，只能说明“恢复暂时跟不上负荷”，不能直接判断为过度训练；通常 1-3 天减量后会回到基线。")
    return "\n".join(lines)


def answer(ctx: ToolContext, message: str) -> tuple[str, list[dict]]:
    trace: list[dict] = []
    text = message.lower()
    prefix = ""
    if memory.detect_memory_worthy(message):
        saved = _call(ctx, trace, "save_memory", content=message)
        m = saved["memory"]
        prefix = f"📝 已记录到长期记忆：「{m['content']}」（{m['date']}，标签：{'、'.join(m['tag_labels'])}），以后分析恢复时会考虑这一点。\n\n"

    intent = next((name for name, kws in INTENTS if any(k in text for k in kws)), "today")
    days = _detect_days(message)

    if intent == "drivers":
        d = _call(ctx, trace, "analyze_recovery_drivers", days=days or 120)
        lines = ["### 你的 Recovery 通常在什么情况下最好"]
        if d.get("summary"):
            lines.append(d["summary"])
        for f in d.get("factors", [])[:5]:
            lines.append(f"- {f['label']}：恢复最好的 25% 日子平均 {f['top_text']}，最差的 25% 日子平均 {f['bottom_text']}（ρ={f['spearman_rho']}）")
        pats = _call(ctx, trace, "get_learned_patterns")["patterns"][:3]
        if pats:
            lines.append("\n**系统学到的个人规律**")
            lines += [f"- {p['title']}" for p in pats]
        body = "\n".join(lines)
    elif intent == "patterns":
        pats = _call(ctx, trace, "get_learned_patterns")["patterns"]
        body = "### 从你的历史数据中发现的规律\n" + "\n".join(
            f"- {p['title']}（样本 {p['sample_size']} 天，p={p['p_value']}，置信度 {CONF.get(p['confidence'], p['confidence'])}）" for p in pats
        ) + "\n\n> 以上都是相关趋势，不代表确定因果。" if pats else "数据还不够，暂时没有发现稳定的个人规律（通常需要 30 天以上）。"
    elif intent == "similar":
        s = _call(ctx, trace, "find_similar_days")
        if not s.get("available"):
            body = "历史数据还不够，暂时找不到相似的日子。"
        else:
            lines = [s["summary"], ""]
            for i in s["items"]:
                nxt = "、".join(f"{v:.0f}%" for v in i["next_days_recovery"] if v is not None)
                lines.append(f"- {i['date']}：HRV {i['hrv_dev'] * 100:+.0f}%，RHR {i['rhr_dev'] * 100:+.0f}%，之后 3 天 Recovery {nxt}")
            body = "\n".join(lines)
    elif intent == "anomaly":
        an = _call(ctx, trace, "detect_anomalies", days=days or 14)
        if an["count"] == 0:
            body = f"过去 {an['days']} 天没有检测到明显异常。"
        else:
            body = f"### 过去 {an['days']} 天检测到 {an['count']} 条异常\n" + "\n".join(
                f"- {a['date']}【{a['label']}·{a['severity']}】{a['message']}" for a in an["anomalies"][:12]
            )
        if "rhr" in text or "静息心率" in text:
            body = _metric_answer(ctx, trace, "rhr", days or 28) + "\n\n" + body
    elif intent == "strain":
        body = _strain_answer(ctx, trace)
    elif intent == "training":
        tp = _call(ctx, trace, "get_training_plan")
        adj = tp["recommended_adjustment"]
        body = _today_answer(ctx, trace) if adj.get("original") is None else (
            f"### 今天的训练：{adj['original']['title']}\n**{adj['summary']}**\n" + "\n".join(f"- {c}" for c in adj["changes"])
            + "\n\n调整后：\n" + "\n".join(
                f"- {e['name']}：{e.get('sets', '')} × {e.get('reps', '')}" + (f"，RPE {e['rpe']}" if e.get("rpe") else "")
                for e in adj["adjusted"]["exercises"]
            )
        )
    elif intent == "weekly":
        w = _call(ctx, trace, "get_weekly_report")
        body = w.get("narrative") or w.get("reason", "暂无周报")
    elif intent in ("hrv", "rhr", "sleep"):
        metric = {"hrv": "hrv", "rhr": "rhr", "sleep": "sleep_duration"}[intent]
        body = _metric_answer(ctx, trace, metric, days or 28)
        if intent == "sleep" and ("recovery" in text or "恢复" in text):
            body += "\n\n" + _today_answer(ctx, trace)
    elif intent == "recovery_trend" or (days and days >= 14):
        body = _metric_answer(ctx, trace, "recovery", days or 28)
    else:
        body = _today_answer(ctx, trace)

    note = "\n\n---\n*当前未配置大模型，以上回答由规则引擎基于你的真实数据生成。配置 LLM 后可获得更灵活的对话。*"
    return prefix + body + note, trace
