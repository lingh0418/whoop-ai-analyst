"""饮食建议（辅助功能）：只基于宏量计划 + WHOOP 状态给简单建议，不做食物记录。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NutritionPlan

DAY_TYPE = {"high_carb": "高碳日", "low_carb": "低碳日", "normal": "常规日"}
GOAL = {"cut": "减脂", "maintain": "维持", "bulk": "增肌"}


def plan_for(db: Session, user_id: int, day: date) -> NutritionPlan | None:
    plan = db.scalar(select(NutritionPlan).where(NutritionPlan.user_id == user_id, NutritionPlan.date == day))
    if plan:
        return plan
    return db.scalar(
        select(NutritionPlan).where(NutritionPlan.user_id == user_id, NutritionPlan.date.is_(None),
                                    NutritionPlan.weekday == day.weekday())
    )


def plan_to_dict(p: NutritionPlan | None) -> dict | None:
    if p is None:
        return None
    return {
        "id": p.id,
        "date": p.date.isoformat() if p.date else None,
        "weekday": p.weekday,
        "day_type": p.day_type,
        "day_type_label": DAY_TYPE.get(p.day_type, p.day_type),
        "goal": p.goal,
        "goal_label": GOAL.get(p.goal, p.goal),
        "calories": p.calories,
        "protein": p.protein,
        "carbs": p.carbs,
        "fat": p.fat,
        "notes": p.notes,
    }


def advise(plan: dict | None, joint: dict, training: dict, profile: dict | None = None) -> list[str]:
    tips: list[str] = []
    level = joint.get("training_level", "normal")
    goal = (plan or {}).get("goal") or (profile or {}).get("goal")
    sleep = joint.get("sleep") or {}
    load = joint.get("load") or {}

    if goal == "cut" and level in ("reduce", "recovery", "rest"):
        tips.append("今天恢复偏低，不建议进一步加大热量缺口；按计划热量吃够即可，必要时可临时回到维持热量。")
    if level in ("recovery", "rest") and plan and plan.get("day_type") == "high_carb":
        tips.append("训练改为低强度后，碳水可以比高碳日计划略少，但不要低于低碳日水平。")
    if load.get("high_load"):
        tips.append("最近训练负荷偏高，保证碳水补充糖原，蛋白质维持在计划值。")
    adjusted = (training or {}).get("adjusted") or {}
    title = adjusted.get("title") or ""
    if level in ("normal", "caution") and any(k in title for k in ("腿", "长距离", "HIIT")):
        tips.append("今天有高强度训练，可以把更多碳水安排在训练前 1-2 小时和训练后。")
    if sleep.get("low"):
        tips.append("最近睡眠偏少：晚餐不要太晚、避免下午之后摄入咖啡因，有助于今晚的睡眠质量。")
    if plan and plan.get("protein"):
        tips.append(f"蛋白质目标 {plan['protein']:.0f} g，分 3-4 餐摄入。")
    if not tips:
        tips.append("状态正常，按饮食计划执行即可。")
    return tips
