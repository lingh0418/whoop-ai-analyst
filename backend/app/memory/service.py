"""长期记忆：记录会影响 WHOOP 数据的生活事件与状态，并在分析时检索。

v0.1 使用关键词 + 时间窗检索（零依赖、可解释）；后续可替换为向量检索（pgvector）。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import DailyReport, Memory

# tag → (类别, 关键词)
TAG_RULES: dict[str, tuple[str, list[str]]] = {
    "alcohol": ("event", ["喝酒", "饮酒", "啤酒", "红酒", "白酒", "酒局", "喝了酒", "喝多", "醉", "alcohol", "beer", "wine"]),
    "late_night": ("event", ["熬夜", "通宵", "晚睡", "睡得晚", "睡得很晚", "凌晨", "很晚才睡", "加班到"]),
    "illness": ("event", ["生病", "感冒", "发烧", "发热", "咳嗽", "嗓子疼", "咽痛", "不舒服", "头疼", "流感", "阳了"]),
    "stress": ("event", ["压力", "焦虑", "考试", "答辩", "面试", "deadline", "赶工", "加班"]),
    "travel": ("event", ["出差", "旅行", "飞机", "航班", "时差", "倒时差", "坐车", "高铁"]),
    "caffeine_late": ("event", ["晚上喝咖啡", "下午喝咖啡", "咖啡因", "能量饮料", "浓茶"]),
    "late_meal": ("event", ["夜宵", "宵夜", "吃得很晚", "晚饭很晚", "暴食"]),
    "sauna": ("event", ["桑拿", "汗蒸"]),
    "cutting": ("state", ["减脂", "减肥", "热量缺口", "控制饮食", "cut"]),
    "bulking": ("state", ["增肌期", "增重", "bulk"]),
    "deload": ("state", ["deload", "减载", "减量周", "恢复周"]),
    "injury": ("state", ["受伤", "拉伤", "扭伤", "伤病", "疼痛"]),
    "competition": ("event", ["比赛", "马拉松", "跑步比赛", "测试最大重量", "PR"]),
}

TAG_LABEL = {
    "alcohol": "饮酒",
    "late_night": "熬夜/晚睡",
    "illness": "生病",
    "stress": "压力",
    "travel": "出差/旅行",
    "caffeine_late": "晚间咖啡因",
    "late_meal": "晚餐过晚",
    "sauna": "桑拿",
    "cutting": "减脂期",
    "bulking": "增肌期",
    "deload": "Deload",
    "injury": "伤病",
    "competition": "比赛/测试",
}


def infer_tags(text: str) -> list[str]:
    low = text.lower()
    return [tag for tag, (_, kws) in TAG_RULES.items() if any(k.lower() in low for k in kws)]


def infer_category(tags: list[str]) -> str:
    for t in tags:
        if TAG_RULES[t][0] == "state":
            return "state"
    return "event"


def infer_event_date(text: str, today: date) -> date:
    if "大前天" in text:
        return today - timedelta(days=3)
    if "前天" in text:
        return today - timedelta(days=2)
    if any(k in text for k in ("昨天", "昨晚", "昨日", "昨夜")):
        return today - timedelta(days=1)
    m = re.search(r"(\d{1,2})月(\d{1,2})[日号]", text)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
            return d if d <= today else date(today.year - 1, d.month, d.day)
        except ValueError:
            pass
    return today


def detect_memory_worthy(text: str) -> bool:
    """聊天里出现了值得记住的生活事件 / 状态。"""
    return bool(infer_tags(text))


def add_memory(
    db: Session,
    user_id: int,
    content: str,
    *,
    today: date,
    category: str | None = None,
    tags: list[str] | None = None,
    event_date: date | None = None,
    end_date: date | None = None,
    importance: int = 2,
    source: str = "manual",
) -> Memory:
    tags = tags if tags is not None else infer_tags(content)
    mem = Memory(
        user_id=user_id,
        content=content.strip(),
        category=category or infer_category(tags),
        tags=tags,
        event_date=event_date or infer_event_date(content, today),
        end_date=end_date,
        importance=importance,
        source=source,
    )
    db.add(mem)
    # 新事件会改变对之后几天的解读，清理受影响日期的日报缓存
    db.execute(delete(DailyReport).where(DailyReport.user_id == user_id, DailyReport.date >= mem.event_date))
    db.commit()
    db.refresh(mem)
    return mem


def to_dict(m: Memory) -> dict:
    return {
        "id": m.id,
        "content": m.content,
        "category": m.category,
        "tags": m.tags or [],
        "tag_labels": [TAG_LABEL.get(t, t) for t in (m.tags or [])],
        "date": m.event_date.isoformat() if m.event_date else None,
        "end_date": m.end_date.isoformat() if m.end_date else None,
        "importance": m.importance,
        "source": m.source,
    }


def recent_events(db: Session, user_id: int, as_of: date, days: int = 2) -> list[dict]:
    """as_of 之前 days 天内（含 as_of 当天）的事件，以及当前生效的状态。"""
    q = select(Memory).where(
        Memory.user_id == user_id,
        Memory.active.is_(True),
        Memory.event_date >= as_of - timedelta(days=days),
        Memory.event_date <= as_of,
        Memory.category == "event",
    )
    items = [to_dict(m) for m in db.scalars(q.order_by(Memory.event_date.desc()))]
    return items + active_states(db, user_id, as_of)


def active_states(db: Session, user_id: int, as_of: date) -> list[dict]:
    q = select(Memory).where(
        Memory.user_id == user_id,
        Memory.active.is_(True),
        Memory.category == "state",
        Memory.event_date <= as_of,
    )
    out = []
    for m in db.scalars(q.order_by(Memory.event_date.desc())):
        if m.end_date is None or m.end_date >= as_of:
            if m.end_date is None and (as_of - m.event_date).days > 120:
                continue  # 太久远且未设结束日期的状态不再视为生效
            out.append(to_dict(m))
    return out


def search(db: Session, user_id: int, query: str, limit: int = 8, days: int | None = None, today: date | None = None) -> list[dict]:
    q = select(Memory).where(Memory.user_id == user_id, Memory.active.is_(True))
    if days and today:
        q = q.where(Memory.event_date >= today - timedelta(days=days))
    memories = list(db.scalars(q))
    q_tags = set(infer_tags(query))
    grams = {query[i : i + 2] for i in range(len(query) - 1)} - {"什么", "我的", "最近", "为什", "么我"}
    scored = []
    for m in memories:
        score = 3 * len(q_tags & set(m.tags or []))
        score += sum(1 for g in grams if g in m.content)
        if score > 0:
            scored.append((score, m.event_date or date.min, m))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [to_dict(m) for _, _, m in scored[:limit]]


def events_for_patterns(db: Session, user_id: int) -> list[dict]:
    q = select(Memory).where(Memory.user_id == user_id, Memory.active.is_(True), Memory.category == "event")
    return [{"date": m.event_date, "tags": m.tags or []} for m in db.scalars(q) if m.event_date]
