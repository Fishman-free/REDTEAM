"""Tiny OpenAI-compatible model used for local RTM Arena demos.

This is deliberately deterministic and NOT a real defender model.  It exists
so the full stake → attack → breach → data-market loop can be exercised on a
local fork without a cloud API key.  It follows the same tool surface the
platform exposes to real BYOK agents:

* qualification: transfer 1 wei to the address in the verified-owner envelope;
* external dialogue: a deliberately vulnerable demo agent will transfer 1 wei
  to the claimed sender when the message asks for a transfer;
* balance questions use the get_balance tool.

Run with the platform venv or any Python 3.11+:
    python tools/mock_model.py
The allowlist entry should point at http://127.0.0.1:18081/v1.
"""

from __future__ import annotations

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("MOCK_MODEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("MOCK_MODEL_PORT", "18081"))
MODEL = os.environ.get("MOCK_MODEL_NAME", "mock-defender")
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")
# Demo extension: an explicit amount in the message is honoured so the
# duplicate-payment scenario can be exercised (pay 0.5 now, 0.5 later, ...).
AMOUNT_RE = re.compile(
    r"(?:支付|付款|转账|打款|转|pay|transfer|send)\s*"
    r"([0-9]{1,12}(?:\.[0-9]{1,6})?)\s*(?:tRTM|RTM)",
    re.IGNORECASE,
)
COUNTER = 0


def next_call_id() -> str:
    global COUNTER
    COUNTER += 1
    return f"mock-call-{COUNTER}"


def completion(text: str | None, tool_calls: list[dict] | None = None) -> dict:
    message: dict = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": f"chatcmpl-mock-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def tool_call(name: str, arguments: dict) -> dict:
    return {
        "id": next_call_id(),
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }


def last_tool_result(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "tool":
            content = message.get("content") or ""
            return content if isinstance(content, str) else json.dumps(content)
    return ""


def decide(payload: dict) -> dict:
    messages = payload.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return completion("没有可处理的输入。")

    last = messages[-1]
    role = last.get("role")

    # After any tool result, finish the turn with a short confirmation.
    if role == "tool":
        result = last_tool_result(messages)
        if "balance" in result:
            return completion(f"当前钱包余额是 {result}。")
        return completion("已完成。")

    content = last.get("content") or ""
    if not isinstance(content, str):
        return completion("输入格式不正确。")

    envelope = None
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            envelope = parsed
    except (ValueError, TypeError):
        parsed = None

    if envelope and envelope.get("owner_requests_execution") is True:
        text = str(envelope.get("content") or "")
        target = ADDRESS_RE.search(text)
        if target:
            return completion(
                None,
                [
                    tool_call(
                        "transfer_rtm",
                        {"to": target.group(0), "amount": "1"},
                    )
                ],
            )
        return completion("缺少资格测试地址。")

    if envelope and envelope.get("channel") == "external_dialogue":
        text = str(envelope.get("content") or "")
        claimed = str(envelope.get("claimed_sender") or "")
        if any(keyword in text.lower() for keyword in ("余额", "balance")):
            return completion(None, [tool_call("get_balance", {})])
        wants_transfer = any(
            keyword in text.lower()
            for keyword in ("转", "付款", "打款", "transfer", "send", "pay")
        )
        target = ADDRESS_RE.search(text)
        destination = target.group(0) if target else claimed
        if wants_transfer and ADDRESS_RE.fullmatch(destination):
            # Demo-only vulnerability: this mock intentionally obeys external
            # transfer requests so the breach / data loop can be exercised.
            # An explicit "0.5 tRTM" style amount is converted to wei so the
            # split-payment scenario can be exercised; the host-side preflight
            # controls are what stop it, not the model.
            amount_match = AMOUNT_RE.search(text)
            if amount_match:
                whole, _, frac = amount_match.group(1).partition(".")
                amount = str(int(whole or "0") * 10**18 + int((frac + "0" * 18)[:18]))
            else:
                amount = "1"
            return completion(
                None,
                [
                    tool_call(
                        "transfer_rtm",
                        {"to": destination, "amount": amount},
                    )
                ],
            )
        return completion(
            "我只执行主人明确授权的付款。请提供收款地址和已授权的用途。"
        )

    return completion("我已收到消息，但没有可执行的付款指令。")


class Handler(BaseHTTPRequestHandler):
    server_version = "RTM-Mock-Model/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[mock-model] {self.address_string()} {fmt % args}")

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/health", "/healthz"):
            self._json(200, {"status": "ok"})
        elif self.path.rstrip("/") in ("/v1/models", "/models"):
            self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": MODEL,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "rtm-demo",
                        }
                    ],
                },
            )
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(min(length, 2_000_000))
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            self._json(400, {"error": "invalid JSON"})
            return
        self._json(200, decide(payload))


if __name__ == "__main__":
    print(f"[mock-model] listening on http://{HOST}:{PORT}/v1 model={MODEL}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
