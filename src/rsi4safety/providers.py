from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Protocol
from urllib import error, request


class ChatModel(Protocol):
    def complete(self, system: str, user: str) -> str: ...


@dataclass
class OfflineChatModel:
    """Deterministic placeholder used before an API key is configured."""

    response: str = '{"status":"offline","message":"deterministic fallback"}'

    def complete(self, system: str, user: str) -> str:
        del system, user
        return self.response


@dataclass
class OpenAICompatibleChatModel:
    """Small dependency-free adapter for OpenAI-compatible chat endpoints."""

    model: str
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 60

    def complete(self, system: str, user: str) -> str:
        key = self.api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
            }
        ).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"model endpoint returned HTTP {exc.code}: {detail}") from exc
        return str(data["choices"][0]["message"]["content"])
