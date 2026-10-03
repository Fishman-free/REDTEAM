from __future__ import annotations
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

PAYMENT_MODEL = "Qwen/Qwen3-4B-Instruct-2507"


@dataclass(frozen=True)
class ModelConfig:
    model: str = PAYMENT_MODEL
    base_url: str = "http://127.0.0.1:18081/v1"
    api_key: str = field(default="", repr=False)
    max_tokens: int = 1200
    timeout: float = 60

    def __post_init__(self):
        url = urllib.parse.urlsplit(self.base_url)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "llm-gateway"}
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("payment backend must be the HTTP loopback SSH tunnel or platform llm-gateway")
        if not self.model or not 1 <= self.max_tokens <= 8192 or not 0 < self.timeout <= 120:
            raise ValueError("invalid bounded model configuration")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    @classmethod
    def from_env(cls, *, env_file: Path | None = None):
        # Read only this backend's three fields. Never forward role-provider keys.
        path = env_file or Path(__file__).resolve().parents[2] / ".env"
        values = {}
        if path.is_file():
            for line in path.read_text().splitlines():
                key, separator, value = line.partition("=")
                if separator and key.strip() in {"SUT_MODEL", "SUT_BASE_URL", "SUT_API_KEY"}:
                    values[key.strip()] = value.strip().strip("\"'")
        for key in ("SUT_MODEL", "SUT_BASE_URL", "SUT_API_KEY"):
            if key in os.environ:
                values[key] = os.environ[key]
        return cls(model=values.get("SUT_MODEL") or PAYMENT_MODEL,
                   base_url=values.get("SUT_BASE_URL") or "http://127.0.0.1:18081/v1",
                   api_key=values.get("SUT_API_KEY", ""))


class ModelError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "infrastructure"):
        super().__init__(message)
        self.kind = kind


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class OpenAICompatibleClient:
    def __init__(self, config: ModelConfig):
        self.config = config
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def complete(self, messages: list, tools: list, *, timeout: float | None = None) -> dict:
        body = json.dumps({"model": self.config.model, "messages": messages,
                           "tools": tools, "parallel_tool_calls": False,
                           "temperature": 0, "max_tokens": self.config.max_tokens}, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = "Bearer " + self.config.api_key
        request = urllib.request.Request(self.config.base_url + "/chat/completions",
                                         data=body, headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=min(timeout or self.config.timeout, self.config.timeout)) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ModelError("model response exceeds 2 MB")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ModelError("model response must be an object")
            if data.get("model") != self.config.model:
                raise ModelError("response model does not match the requested payment model")
            choice = data["choices"][0]
            if not isinstance(choice, dict):
                raise ModelError("invalid model choice")
            if choice.get("finish_reason") == "length":
                raise ModelError("model output truncated", kind="agent_protocol")
            message = choice["message"]
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise ModelError("invalid assistant role")
            return {"message": message, "model": data["model"], "usage": data.get("usage", {})}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise ModelError(f"model transport failed ({type(exc).__name__})") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelError("invalid model response protocol") from None
