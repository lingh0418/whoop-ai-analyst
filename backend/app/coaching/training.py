"""训练建议（第二层）：先有 WHOOP 身体状态判断，再读取今天的训练计划并调整。

调整等级来自联合分析 joint.training_level：
- normal   恢复正常 → 按计划训练
- caution  单项偏离 → 照常训练，但不额外加量，RPE 不超过计划
- reduce   短期恢复不足 → 保留训练，总量下降 20-30%，RPE 下降 1，避免力竭
- recovery 整体恢复明显下降 → 改为轻量恢复训练（Zone 2 / 灵活性）
- rest     疑似非训练因素（生病等）→ 建议休息，观察身体
"""

from __future__ import annotations

import copy
import math
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TrainingPlan

LEVEL_TEXT = {
    "normal": "按计划正常训练",
    "caution": "照常训练，但不额外加量",
    "reduce": "保留训练，降低总量与强度",
    "recovery": "改为轻量恢复训练",
    "rest": "建议休息，优先恢复",
}


def plan_for(db: Session, user_id: int, day: date) -> TrainingPlan | None:
    """优先取指定日期的计划，否则取周模板。"""
    plan = db.scalar(select(TrainingPlan).where(TrainingPlan.user_id == user_id, TrainingPlan.date == day))
    if plan:
        return plan
    return db.scalar(
        select(TrainingPlan).where(TrainingPlan.user_id == user_id, TrainingPlan.date.is_(None),
                                   TrainingPlan.weekday == day.weekday())
    )


def plan_to_dict(p: TrainingPlan | None) -> dict | None:
    if p is None:
        return None
    return {
        "id": p.id,
        "date": p.date.isoformat() if p.date else None,
        "weekday": p.weekday,
        "title": p.title,
        "focus": p.focus,
        "intensity": p.intensity,
        "exercises": p.exercises or [],
        "notes": p.notes,
    }


def _rpe(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def adjust(plan: dict | None, level: str, joint: dict | None = None) -> dict:
    joint = joint or {}
    if plan is None:
        tips = {
            "normal": "今天没有训练计划。身体状态正常，可以自由安排。",
            "caution": "今天没有训练计划。可以做中低强度活动，不建议临时加练。",
            "reduce": "今天没有训练计划，正好作为恢复日：散步 / 拉伸 / 早点睡。",
            "recovery": "今天没有训练计划，建议保持休息，优先补觉。",
            "rest": "今天没有训练计划，建议完全休息并关注身体状况。",
        }
        return {"level": level, "summary": tips.get(level, ""), "original": None, "adjusted": None, "changes": []}

    is_rest_day = plan.get("intensity") == "low" and "休息" in (plan.get("title") or "")
    exercises = copy.deepcopy(plan.get("exercises") or [])
    changes: list[str] = []
    summary = LEVEL_TEXT[level]

    if level == "normal" or is_rest_day:
        if joint.get("state") == "well_recovered" and plan.get("intensity") == "high":
            changes.append("恢复状态良好，可以按计划完成，主项最后一组可以冲击计划上限（仍不建议力竭）")
        else:
            changes.append("按原计划执行")
        adjusted = exercises
    elif level == "caution":
        adjusted = exercises
        for ex in adjusted:
            r = _rpe(ex.get("rpe"))
            if r and r > 8:
                ex["rpe"] = 8
        changes += ["不额外加组或加重量", "RPE 上限 8，最后一组留 2 次余力"]
    elif level == "reduce":
        adjusted = []
        for i, ex in enumerate(exercises):
            ex = dict(ex)
            sets = ex.get("sets")
            if isinstance(sets, int) and sets > 1:
                new_sets = max(1, math.floor(sets * 0.7 + 0.5)) if i == 0 else max(1, sets - 1)
                if new_sets != sets:
                    ex["sets"] = new_sets
            r = _rpe(ex.get("rpe"))
            if r:
                ex["rpe"] = max(5, r - 1.5 if i == 0 else r - 1)
            if str(ex.get("reps", "")).upper() == "AMRAP":
                ex["reps"] = "8-10（不做到力竭）"
            adjusted.append(ex)
        if len(adjusted) > 3:
            dropped = adjusted[-1]["name"]
            adjusted = adjusted[:-1]
            changes.append(f"去掉最后一个辅助动作（{dropped}）")
        changes = [
            "总训练量下降约 20-30%（主项减组，辅助项各减 1 组）",
            "RPE 整体下降 1-1.5，主项保持技术质量即可",
            "所有动作避免力竭",
        ] + changes
        summary += "；也可以直接换成 30-40 分钟 Zone 2 有氧"
    elif level == "recovery":
        adjusted = [
            {"name": "Zone 2 有氧（快走 / 慢骑）", "sets": 1, "reps": "30-40min", "rpe": 4},
            {"name": "灵活性 / 拉伸", "sets": 1, "reps": "15min", "rpe": 2},
        ]
        changes = [f"原计划「{plan.get('title')}」建议推迟 1-2 天", "今天只做低强度活动，心率保持在 Zone 1-2"]
    else:  # rest
        adjusted = [{"name": "休息 / 散步", "sets": 1, "reps": "20-30min", "rpe": 2}]
        changes = [f"原计划「{plan.get('title')}」建议取消", "多个指标异常且训练负荷不高，先观察身体状况"]

    return {
        "level": level,
        "summary": summary,
        "original": plan,
        "adjusted": {**plan, "exercises": adjusted},
        "changes": changes,
    }
