"""LLM 提供方抽象。

- openai_compatible：DeepSeek / 通义千问(DashScope) / Kimi / 智谱 / OpenAI 等兼容 Chat Completions 的服务（国内用户首选）
- anthropic：Claude（使用官方 anthropic SDK）
- none：不调用大模型，使用规则引擎

两种 provider 都实现同一个工具调用循环：模型请求工具 → Python 执行 → 结果回传 → 直到模型给出最终回答。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from app.config import get_settings

log = logging.getLogger(__name__)

ToolExecutor = Callable[[str, dict], str]


class LLMError(RuntimeError):
    pass


@dataclass
class AgentTurn:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    model: str = ""


def _summarize_result(result: str, limit: int = 300) -> str:
    return result if len(result) <= limit else result[:limit] + "…"


class BaseProvider:
    name = "base"
    model = ""

    def run(self, system: str, history: list[dict], tools: list, execute: ToolExecutor, max_steps: int) -> AgentTurn:
        raise NotImplementedError

    def complete(self, system: str, prompt: str, max_tokens: int = 4000) -> str:
        raise NotImplementedError


# --------------------------------------------------------------------------- OpenAI 兼容（DeepSeek / Qwen / Kimi ...）


class OpenAICompatibleProvider(BaseProvider):
    name = "openai_compatible"

    def __init__(self, api_key: str, base_url: str, model: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=120)
        self.model = model

    @staticmethod
    def _tool_specs(tools: list) -> list[dict]:
        return [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools
        ]

    def run(self, system, history, tools, execute, max_steps):
        from openai import APIError

        messages: list[dict] = [{"role": "system", "content": system}, *history]
        specs = self._tool_specs(tools)
        trace: list[dict] = []
        try:
            for step in range(max_steps + 1):
                force_answer = step == max_steps
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=specs,
                    tool_choice="none" if force_answer else "auto",
                )
                msg = resp.choices[0].message
                if not msg.tool_calls or force_answer:
                    return AgentTurn((msg.content or "").strip(), trace, self.model)
                assistant: dict = {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                        for c in msg.tool_calls
                    ],
                }
                reasoning = getattr(msg, "reasoning_content", None)
                if reasoning:  # DeepSeek 思考模式：同一轮工具调用需要回传 reasoning_content
                    assistant["reasoning_content"] = reasoning
                messages.append(assistant)
                for c in msg.tool_calls:
                    try:
                        args = json.loads(c.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = execute(c.function.name, args)
                    trace.append({"name": c.function.name, "args": args, "result": _summarize_result(result)})
                    messages.append({"role": "tool", "tool_call_id": c.id, "content": result})
        except APIError as e:
            raise LLMError(f"{self.model} 调用失败：{e}") from e
        return AgentTurn("", trace, self.model)

    def complete(self, system, prompt, max_tokens=4000):
        from openai import APIError

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
        except APIError as e:
            raise LLMError(f"{self.model} 调用失败：{e}") from e
        return (resp.choices[0].message.content or "").strip()


# --------------------------------------------------------------------------- Anthropic Claude


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, effort: str, enable_fallbacks: bool):
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key or None)
        self.model = model
        self.effort = effort
        self.enable_fallbacks = enable_fallbacks

    def _create(self, **params):
        params.setdefault("output_config", {"effort": self.effort})
        if self.enable_fallbacks:
            # 服务端 fallback：模型拒答时自动由其他模型接续
            return self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
            )
        return self.client.messages.create(**params)

    def run(self, system, history, tools, execute, max_steps):
        import anthropic

        messages: list = [*history]
        specs = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        trace: list[dict] = []
        try:
            for step in range(max_steps + 1):
                force_answer = step == max_steps
                response = self._create(
                    model=self.model,
                    max_tokens=16000,
                    system=system,
                    tools=specs,
                    tool_choice={"type": "none"} if force_answer else {"type": "auto"},
                    messages=messages,
                )
                if response.stop_reason == "refusal":
                    return AgentTurn("抱歉，这个问题我无法回答。可以换个方式描述你想了解的 WHOOP 数据。", trace, response.model)
                # 原样追加（含 thinking 块），保持历史 append-only
                messages.append({"role": "assistant", "content": response.content})
                if response.stop_reason == "pause_turn":
                    continue
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason != "tool_use" or not tool_uses:
                    text = "".join(b.text for b in response.content if b.type == "text").strip()
                    if response.stop_reason == "max_tokens":
                        text += "\n\n（回答过长被截断）"
                    return AgentTurn(text, trace, response.model)
                results = []
                for b in tool_uses:
                    args = b.input if isinstance(b.input, dict) else {}
                    result = execute(b.name, args)
                    trace.append({"name": b.name, "args": args, "result": _summarize_result(result)})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": result})
                messages.append({"role": "user", "content": results})
        except anthropic.APIConnectionError as e:
            raise LLMError(f"无法连接 Claude API：{e}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API 错误 {e.status_code}：{e.message}") from e
        return AgentTurn("", trace, self.model)

    def complete(self, system, prompt, max_tokens=8000):
        import anthropic

        try:
            response = self._create(
                model=self.model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIConnectionError as e:
            raise LLMError(f"无法连接 Claude API：{e}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API 错误 {e.status_code}：{e.message}") from e
        if response.stop_reason == "refusal":
            raise LLMError("模型拒绝了该请求")
        return "".join(b.text for b in response.content if b.type == "text").strip()


# --------------------------------------------------------------------------- 工厂


def get_provider() -> BaseProvider | None:
    s = get_settings()
    kind = (s.llm_provider or "none").lower()
    if kind == "openai_compatible" and s.llm_api_key:
        return OpenAICompatibleProvider(s.llm_api_key, s.llm_base_url, s.llm_model)
    if kind == "anthropic":
        return AnthropicProvider(s.anthropic_api_key, s.anthropic_model, s.anthropic_effort, s.anthropic_enable_fallbacks)
    return None


def provider_info() -> dict:
    s = get_settings()
    p = get_provider()
    if p is None:
        return {"provider": "none", "model": None, "enabled": False,
                "note": "未配置大模型，使用规则引擎生成中文解读（所有统计功能完整可用）"}
    return {"provider": p.name, "model": p.model, "enabled": True,
            "base_url": s.llm_base_url if p.name == "openai_compatible" else None}
