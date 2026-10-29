"""mcp-pull reference client: long-poll the CVM, answer through the wallet MCP."""

from __future__ import annotations

import time
import urllib.parse
from typing import Any, Callable, Mapping

from ..adapters import HttpJsonClient


class PullClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        handler: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> None:
        if not callable(handler):
            raise ValueError("handler must be callable")
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("pull base URL must be http(s)")
        if not isinstance(token, str) or len(token) < 16:
            raise ValueError("pull token must be at least 16 characters")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._handler = handler
        self._client = HttpJsonClient(timeout=timeout)
        self._poll_interval = max(0.05, float(poll_interval))
        self._stopped = False

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    def stop(self) -> None:
        self._stopped = True

    def poll_once(self) -> bool:
        """Process at most one pending message; return whether one was handled."""

        response = self._client.get(
            self.base_url + "/next_message",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        message = response.get("message")
        if not isinstance(message, Mapping):
            return False
        wallet = response.get("wallet_mcp")
        payload = dict(message)
        metadata = payload.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        if isinstance(wallet, Mapping):
            payload["wallet_mcp"] = wallet
            metadata["wallet_mcp"] = wallet
        payload["metadata"] = metadata
        reply = self._handler(payload)
        if not isinstance(reply, Mapping):
            reply = {"reply": "agent failed", "tool_calls": []}
        self._client.post(
            self.base_url + "/reply",
            {
                "seq": message.get("seq"),
                "text": str(reply.get("reply", ""))[:50_000],
                "tool_calls": list(reply.get("tool_calls") or ()),
                "metadata": dict(reply.get("metadata") or {}),
            },
            headers={"Authorization": f"Bearer {self._token}"},
        )
        return True

    def run(self, *, iterations: int | None = None) -> int:
        """Poll until stopped (or ``iterations`` polls); return handled count."""

        handled = 0
        polls = 0
        while not self._stopped and (iterations is None or polls < iterations):
            polls += 1
            if self.poll_once():
                handled += 1
            else:
                time.sleep(self._poll_interval)
        return handled
