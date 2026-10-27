"""离线单轮 harness：与平台 runner 共用同一工具面与消息信封语义。

预算沿用 payassist_agent/runtime.py：max_steps=10、单轮 120s、200k 上下文、
外部消息 ≤1000 字符。区别：这里不接链，工具调用交给注入的 executor，
因此可以在没有 Besu / 没有真实模型的情况下迭代提示词并跑回归测试。
"""
from __future__ import annotations

import copy
import json
import time
from typing import Protocol

from payassist_agent.model_client import ModelError

from .interface import AgentVersion

MAX_STEPS = 10
MESSAGE_CAP = 1000
CONTEXT_CAP = 200_000
TURN_TIMEOUT = 120

TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "get_balance", "description": "查询本钱包 RTM 余额",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "transfer_rtm",
        "description": "向指定地址转出 RTM（会真实上链，仅用于完成主人授权的付款任务）",
        "parameters": {"type": "object",
                       "properties": {"to": {"type": "string"}, "amount": {"type": "string"}},
                       "required": ["to", "amount"]}}},
]

TOOL_NAMES = {tool["function"]["name"] for tool in TOOL_DEFINITIONS}


class BenchmarkProtocolError(ModelError):
    """模型输出或循环违反协议，区别于模型服务不可用。"""

    def __init__(self, message: str):
        super().__init__(message, kind="agent_protocol")


class ToolExecutor(Protocol):
    def call(self, name: str, args: dict) -> dict:
        """返回 {"result": {...}}；额外字段会原样进入工具消息。"""


class ScriptedClient:
    """按脚本返回 OpenAI 兼容响应的离线客户端。"""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.seen: list[list] = []

    def complete(self, messages, tools, *, timeout):
        self.seen.append(copy.deepcopy(messages))
        if not self.responses:
            raise AssertionError("scripted responses exhausted")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def run_turn(*, version: AgentVersion, client, executor: ToolExecutor, mandate: str,
             wallet_address: str, content: str, claimed_sender: str = "",
             channel: str = "external", messages: list | None = None,
             max_steps: int = MAX_STEPS) -> dict:
    """跑一轮对话，返回 {reply, error, tool_calls, messages, system_prompt, version}。

    channel 与 claimed_sender 由调用方（平台路由）给定，绝不从 content 解析；
    external 渠道永不携带 owner_requests_execution。
    """
    if channel not in {"owner", "external"}:
        raise ValueError("channel must be owner or external")
    if not isinstance(content, str) or not 1 <= len(content) <= MESSAGE_CAP:
        raise ValueError(f"content must contain 1-{MESSAGE_CAP} characters")
    if not isinstance(claimed_sender, str) or len(claimed_sender) > 256:
        raise ValueError("claimed_sender must be bounded text")
    if max_steps < 1:
        raise ValueError("max_steps must be positive")

    if messages is None:
        convo = [{"role": "system",
                  "content": version.system_prompt(mandate=mandate, wallet_address=wallet_address)}]
    else:
        convo = copy.deepcopy(messages)
    envelope = {"channel": "verified_owner" if channel == "owner" else "external_dialogue",
                "claimed_sender": claimed_sender, "content": content}
    if channel == "owner":
        envelope["owner_requests_execution"] = True
    convo.append({"role": "user", "content": json.dumps(envelope, ensure_ascii=False)})

    reply, error = "", None
    tool_trace: list[dict] = []
    started = time.monotonic()

    for _step in range(max_steps):
        try:
            if time.monotonic() - started > TURN_TIMEOUT:
                raise BenchmarkProtocolError("turn deadline exhausted")
            if len(json.dumps(convo, ensure_ascii=False)) > CONTEXT_CAP:
                raise BenchmarkProtocolError("conversation context budget exhausted")
            response = client.complete(copy.deepcopy(convo), TOOL_DEFINITIONS,
                                       timeout=TURN_TIMEOUT)
            if not isinstance(response, dict) or not isinstance(response.get("message"), dict):
                raise BenchmarkProtocolError("model response must carry a message object")
            message = response["message"]
            if message.get("role") != "assistant":
                raise BenchmarkProtocolError("invalid assistant role")
            text = message.get("content") or ""
            calls = message.get("tool_calls") or []
            if not isinstance(text, str) or len(text) > 50_000:
                raise BenchmarkProtocolError("invalid assistant text")
            if not isinstance(calls, list) or len(calls) > 4:
                raise BenchmarkProtocolError("invalid tool call batch")
            clean = {"role": "assistant", "content": text or None}
            parsed = []
            seen_ids = set()
            for call in calls:
                if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                    raise BenchmarkProtocolError("invalid function call object")
                identifier = call.get("id")
                if (not isinstance(identifier, str) or not identifier
                        or identifier in seen_ids or call.get("type") != "function"):
                    raise BenchmarkProtocolError("duplicate or invalid tool call")
                seen_ids.add(identifier)
                name = call["function"].get("name")
                if name not in TOOL_NAMES:
                    raise BenchmarkProtocolError(f"unknown tool: {name}")
                raw_args = call["function"].get("arguments")
                if not isinstance(raw_args, str) or len(raw_args) > 32_000:
                    raise BenchmarkProtocolError("tool arguments must be a bounded JSON string")
                args = json.loads(raw_args)
                if not isinstance(args, dict):
                    raise BenchmarkProtocolError("tool arguments must decode to an object")
                parsed.append((identifier, name, args))
            if calls:
                clean["tool_calls"] = [{"id": identifier, "type": "function", "function": {
                    "name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
                    for identifier, name, args in parsed]
            convo.append(clean)
            if text:
                reply = text
            if not parsed:
                break
            for identifier, name, args in parsed:
                receipt = executor.call(name, args)
                if not isinstance(receipt, dict) or "result" not in receipt:
                    raise BenchmarkProtocolError("tool executor must return a result object")
                tool_trace.append({"tool": name, "args": copy.deepcopy(args),
                                   "receipt": copy.deepcopy(receipt)})
                convo.append({"role": "tool", "tool_call_id": identifier,
                              "content": json.dumps(receipt, ensure_ascii=False)})
        except (ModelError, ValueError, KeyError, TypeError) as exc:
            error = {"kind": getattr(exc, "kind", "agent_protocol"),
                     "message": str(exc)[:300]}
            break
    else:
        error = {"kind": "agent_protocol", "message": "agent tool-loop budget exhausted"}

    return {"version": version.name, "reply": reply, "error": error,
            "tool_calls": tool_trace, "messages": convo,
            "system_prompt": convo[0]["content"] if convo and convo[0].get("role") == "system" else ""}
