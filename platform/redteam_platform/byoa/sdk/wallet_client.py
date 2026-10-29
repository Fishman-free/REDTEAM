"""Client for the CVM-internal wallet MCP endpoint."""

from __future__ import annotations

import urllib.parse
from typing import Any, Mapping

from ..adapters import HttpJsonClient


class WalletClientError(RuntimeError):
    """Raised when the wallet MCP is unreachable or returns a bad shape."""


def _validate_base_url(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("wallet MCP URL is required")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("wallet MCP URL must be http(s)")
    return value.rstrip("/")


class WalletMCPClient:
    """Thin JSON client; the token is only ever sent in the Authorization header."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        client: HttpJsonClient | None = None,
    ) -> None:
        self.base_url = _validate_base_url(base_url)
        if not isinstance(token, str) or len(token) < 16:
            raise ValueError("wallet token must be at least 16 characters")
        self._token = token
        self._client = client or HttpJsonClient(timeout=timeout)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(name, str) or not name:
            raise ValueError("tool name is required")
        response = self._client.post(
            self.base_url + "/mcp",
            {"name": name, "arguments": dict(arguments or {})},
            headers={"Authorization": f"Bearer {self._token}"},
        )
        if not isinstance(response, dict) or "result" not in response:
            raise WalletClientError("wallet MCP returned no result")
        return response

    def get_balance(self) -> str | None:
        response = self.call("get_balance", {})
        result = response.get("result")
        if not isinstance(result, dict):
            return None
        value = result.get("balance")
        return value if isinstance(value, str) else None

    def transfer(self, to: str, amount: int | str) -> dict[str, Any]:
        return self.call("transfer_rtm", {"to": to, "amount": str(amount)})
