"""对话 Agent：围绕 WHOOP 数据回答问题，必须先调用工具取数再回答。"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.agent import fallback
from app.agent.llm import LLMError, get_provider
from app.agent.prompts import DAILY_SUMMARY_SYSTEM, WEEKLY_SUMMARY_SYSTEM, system_prompt
from app.agent.tools import TOOLS, ToolContext, execute_tool
from app.config import get_settings
from app.memory import service as memory
from app.models import Conversation, ConversationMessage, User

log = logging.getLogger(__name__)

HISTORY_TURNS = 10


def _history(conv: Conversation) -> list[dict]:
    msgs = [m for m in conv.messages if m.role in ("user", "assistant") and m.content]
    return [{"role": m.role, "content": m.content} for m in msgs[-HISTORY_TURNS * 2:]]


def chat(db: Session, user: User, message: str, conversation_id: int | None = None) -> dict:
    conv = db.get(Conversation, conversation_id) if conversation_id else None
    if conv is None or conv.user_id != user.id:
        conv = Conversation(user_id=user.id, title=message.strip()[:40] or "新对话")
        db.add(conv)
        db.commit()
        db.refresh(conv)
    history = _history(conv)
    db.add(ConversationMessage(conversation_id=conv.id, role="user", content=message))
    db.commit()

    ctx = ToolContext(db=db, user=user)
    provider = get_provider()
    model = "rule-engine"
    error = None
    if provider is None:
        text, trace = fallback.answer(ctx, message)
    else:
        try:
            turn = provider.run(
                system_prompt(ctx.today.isoformat(), user.name, user.profile or {}),
                history + [{"role": "user", "content": message}],
                TOOLS,
                lambda name, args: execute_tool(ctx, name, args),
                get_settings().agent_max_steps,
            )
            text, trace, model = turn.text, turn.tool_calls, turn.model
            # 模型没有主动保存、但消息里明显有生活事件时，兜底记录
            if not any(t["name"] == "save_memory" for t in trace) and memory.detect_memory_worthy(message):
                m = memory.add_memory(db, user.id, message, today=ctx.today, source="chat")
                trace.append({"name": "save_memory", "args": {"content": message, "auto": True},
                              "result": json.dumps(memory.to_dict(m), ensure_ascii=False)})
        except LLMError as e:
            log.warning("LLM 调用失败，降级为规则引擎：%s", e)
            error = str(e)
            text, trace = fallback.answer(ctx, message)
            text = f"⚠️ 大模型调用失败（{e}），以下为规则引擎的回答。\n\n" + text

    reply = ConversationMessage(conversation_id=conv.id, role="assistant", content=text or "（没有生成回答）", tool_calls=trace)
    db.add(reply)
    db.commit()
    db.refresh(reply)
    return {
        "conversation_id": conv.id,
        "message": message_to_dict(reply),
        "model": model,
        "error": error,
    }


def message_to_dict(m: ConversationMessage) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "tool_calls": m.tool_calls or [],
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# --------------------------------------------------------------------------- 报告 AI 解读


def _daily_facts(payload: dict) -> dict:
    j = payload["joint"]
    return {
        "date": payload["date"],
        "body_state": payload["state"],
        "tiles": [{k: t.get(k) for k in ("label", "value_text", "baseline_text", "delta_text", "z", "consecutive_unfavorable_days")}
                  for t in payload["tiles"] if t.get("available")],
        "joint": {k: j.get(k) for k in ("label", "headline", "explanation", "caution", "confidence", "negative_signals")},
        "sleep": j.get("sleep"),
        "load": j.get("load"),
        "anomalies": [a["message"] for a in payload.get("anomalies", [])],
        "patterns": [p["title"] for p in payload.get("patterns", [])],
        "similar_days": (payload.get("similar_days") or {}).get("summary"),
        "long_term": payload.get("long_term"),
        "events": [f"{e['date']} {e['content']}" for e in payload.get("events", [])],
        "training": {k: payload["training"].get(k) for k in ("summary", "changes")},
        "nutrition": payload["nutrition"]["advice"],
    }


def summarize_daily(payload: dict) -> tuple[str, str] | None:
    provider = get_provider()
    if provider is None:
        return None
    facts = json.dumps(_daily_facts(payload), ensure_ascii=False, default=str)
    text = provider.complete(DAILY_SUMMARY_SYSTEM, f"今日结构化分析结果：\n{facts}")
    return text, provider.model


def summarize_weekly(payload: dict) -> str | None:
    provider = get_provider()
    if provider is None:
        return None
    facts = {k: v for k, v in payload.items() if k not in ("narrative", "daily")}
    return provider.complete(WEEKLY_SUMMARY_SYSTEM, "周报结构化数据：\n" + json.dumps(facts, ensure_ascii=False, default=str))

