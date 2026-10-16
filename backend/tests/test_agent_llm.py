"""用假客户端验证两种 LLM 提供方的工具调用循环（不发网络请求）。"""

import json
from types import SimpleNamespace as NS

from app.agent.llm import AnthropicProvider, OpenAICompatibleProvider
from app.agent.tools import TOOLS


def _executor(log):
    def run(name, args):
        log.append((name, args))
        return json.dumps({"ok": True, "tool": name})
    return run


def test_openai_compatible_tool_loop():
    p = OpenAICompatibleProvider(api_key="x", base_url="http://localhost", model="deepseek-chat")
    calls = []

    def create(**kw):
        calls.append(kw)
        if len(calls) == 1:
            tc = NS(id="c1", function=NS(name="get_hrv_history", arguments='{"days": 28}'))
            return NS(choices=[NS(message=NS(content="", tool_calls=[tc], reasoning_content=None))])
        # 第二轮应该能看到 tool 结果
        assert kw["messages"][-1]["role"] == "tool"
        assert kw["messages"][-1]["tool_call_id"] == "c1"
        return NS(choices=[NS(message=NS(content="HRV 比基线低 14%。", tool_calls=None))])

    p.client = NS(chat=NS(completions=NS(create=create)))
    log = []
    turn = p.run("sys", [{"role": "user", "content": "HRV?"}], TOOLS, _executor(log), max_steps=4)
    assert turn.text == "HRV 比基线低 14%。"
    assert log == [("get_hrv_history", {"days": 28})]
    assert calls[0]["tools"][0]["type"] == "function"
    assert calls[0]["max_tokens"] == 4096  # 必须显式限制，否则部分服务按模型上限预扣额度
    assert calls[0]["messages"][0]["role"] == "system"


def test_openai_compatible_forces_answer_at_max_steps():
    p = OpenAICompatibleProvider(api_key="x", base_url="http://localhost", model="m")
    seen = []

    def create(**kw):
        seen.append(kw["tool_choice"])
        if kw["tool_choice"] == "none":
            return NS(choices=[NS(message=NS(content="最终回答", tool_calls=None))])
        tc = NS(id=f"c{len(seen)}", function=NS(name="get_today_whoop", arguments="{}"))
        return NS(choices=[NS(message=NS(content=None, tool_calls=[tc]))])

    p.client = NS(chat=NS(completions=NS(create=create)))
    turn = p.run("sys", [{"role": "user", "content": "?"}], TOOLS, _executor([]), max_steps=2)
    assert seen == ["auto", "auto", "none"]
    assert turn.text == "最终回答"


def test_anthropic_tool_loop_appends_content_verbatim():
    p = AnthropicProvider(api_key="x", model="claude-opus-5-5", effort="medium", enable_fallbacks=True)
    requests = []

    def create(**kw):
        requests.append(kw)
        if len(requests) == 1:
            return NS(
                stop_reason="tool_use", model="claude-opus-5-5",
                content=[NS(type="thinking", thinking=""), NS(type="tool_use", id="tu1", name="get_today_whoop", input={})],
            )
        return NS(stop_reason="end_turn", model="claude-opus-5-5", content=[NS(type="text", text="今天恢复不足。")])

    p.client = NS(beta=NS(messages=NS(create=create)), messages=NS(create=create))
    log = []
    turn = p.run("sys", [{"role": "user", "content": "今天怎么样"}], TOOLS, _executor(log), max_steps=4)
    assert turn.text == "今天恢复不足。"
    assert log == [("get_today_whoop", {})]
    first, second = requests
    assert first["betas"] == ["server-side-fallback-2026-07-01"] and first["fallbacks"] == "default"
    assert first["output_config"] == {"effort": "medium"}
    assert "temperature" not in first and "thinking" not in first
    # 历史 append-only：assistant 原样回传（含 thinking 块），再追加 tool_result
    msgs = second["messages"]
    assert msgs[1]["role"] == "assistant" and msgs[1]["content"][0].type == "thinking"
    assert msgs[2]["content"][0]["type"] == "tool_result" and msgs[2]["content"][0]["tool_use_id"] == "tu1"


def test_anthropic_refusal_is_handled():
    p = AnthropicProvider(api_key="x", model="claude-opus-5-5", effort="low", enable_fallbacks=False)
    p.client = NS(messages=NS(create=lambda **kw: NS(stop_reason="refusal", model="claude-opus-5-5", content=[])))
    turn = p.run("sys", [{"role": "user", "content": "?"}], TOOLS, _executor([]), max_steps=2)
    assert "无法回答" in turn.text
