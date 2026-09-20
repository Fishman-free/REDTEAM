"""Single safe OpenAI-compatible transport and strict proposal parser.

The adapter is advisory only. Network use is opt-in and injectable transports are
provided for deterministic tests; no provider error text is returned to callers.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

PROMPT_VERSION = "payment-agent-system-v1"
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "payment_agent_system_v1.txt"
_MAX_BODY = 65536
_MAX_OUTPUT = 200
_PAY = re.compile(r"^PAY (INV-[0-9]{3}) TO ([a-z][a-z0-9_-]{0,31}) AMOUNT ([0-9]{1,6})$", re.I)
_NONE = re.compile(r"^NONE$", re.I)


class AdapterError(Exception):
    """Internal error with a public, secret-free category."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8-sig")


def parse_model_output(line):
    """Parse exactly one PAY line or NONE; reject every other value safely."""
    if not isinstance(line, str):
        raise ValueError("non_string")
    if len(line) > _MAX_OUTPUT:
        raise ValueError("oversize")
    text = line.strip()
    if _NONE.fullmatch(text):
        return None
    match = _PAY.fullmatch(text)
    if not match:
        raise ValueError("parse")
    invoice, recipient, amount = match.groups()
    return {"invoice": invoice.upper(), "recipient": recipient.lower(), "amount": int(amount)}


def _safe_error(error) -> str:
    if isinstance(error, AdapterError) and error.code in {
        "disabled", "missing_config", "body_limit", "schema", "parse", "network", "http", "transport"
    }:
        return error.code
    if isinstance(error, urllib.error.HTTPError):
        return "http"
    if isinstance(error, (urllib.error.URLError, TimeoutError, OSError, RuntimeError)):
        return "network"
    return "transport"


def _wire_payload(model: str, system_prompt: str, trusted_block: str, participant_text: str) -> bytes:
    # Trusted state is a distinct privileged message; participant data is user role.
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "developer", "content": trusted_block},
        {"role": "user", "content": participant_text if isinstance(participant_text, str) else ""},
    ]
    return json.dumps({"model": model, "messages": messages}, ensure_ascii=False).encode("utf-8")


def _decode_content(raw):
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > _MAX_BODY:
            raise AdapterError("body_limit")
        try:
            obj = json.loads(bytes(raw).decode("utf-8"))
        except Exception as error:
            raise AdapterError("schema") from error
    elif isinstance(raw, str):
        if len(raw.encode("utf-8")) > _MAX_BODY:
            raise AdapterError("body_limit")
        try:
            obj = json.loads(raw)
        except Exception as error:
            raise AdapterError("schema") from error
    else:
        raise AdapterError("schema")
    try:
        content = obj["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise AdapterError("schema") from error
    if not isinstance(content, str) or len(content) > _MAX_OUTPUT:
        raise AdapterError("schema")
    return content.strip()


class OpenAICompatLLM:
    name = "openai-compatible"

    def __init__(self, transport=None, timeout=5):
        self.transport = transport
        self.timeout = timeout

    def complete(self, system_prompt, trusted_block, participant_text):
        base, key, model = (os.getenv(k, "").strip() for k in (
            "REDTEAM_LLM_BASE_URL", "REDTEAM_LLM_API_KEY", "REDTEAM_LLM_MODEL"))
        if os.getenv("REDTEAM_LLM_ENABLED") != "1" and self.transport is None:
            raise AdapterError("disabled")
        if not (base and key and model) and self.transport is None:
            raise AdapterError("missing_config")
        payload = _wire_payload(model, system_prompt, trusted_block, participant_text)
        url = base.rstrip("/") + "/chat/completions"
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        try:
            if self.transport is not None:
                raw = self.transport(url, payload, headers, self.timeout)
            else:
                request = urllib.request.Request(url, data=payload, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if int(response.headers.get("Content-Length", "0") or 0) > _MAX_BODY:
                        raise AdapterError("body_limit")
                    raw = response.read(_MAX_BODY + 1)
            return _decode_content(raw)
        except AdapterError:
            raise
        except Exception as error:
            raise AdapterError(_safe_error(error)) from error


def request_proposal(text, transport=None, timeout=5):
    """Legacy wrapper returning (parsed proposal, sanitized metadata)."""
    adapter = OpenAICompatLLM(transport=transport, timeout=timeout)
    trusted = "TRUSTED STATE (host-controlled; no legacy wrapper state supplied)"
    meta = {"adapter": "openai-compatible", "prompt_version": PROMPT_VERSION,
            "fallback": False, "error": None}
    if os.getenv("REDTEAM_LLM_ENABLED") != "1" and transport is None:
        meta.update(adapter="deterministic", fallback=True, error="disabled")
        return None, meta
    if not isinstance(text, str) or len(text) > 8000:
        meta.update(fallback=True, error="bad_input")
        return None, meta
    try:
        content = adapter.complete(load_system_prompt(), trusted, text)
    except Exception as error:
        meta.update(fallback=True, error=_safe_error(error))
        return None, meta
    try:
        return parse_model_output(content), meta
    except ValueError:
        meta.update(fallback=True, error="bad_output")
        return None, meta
