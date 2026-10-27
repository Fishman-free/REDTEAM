"""BYOK (bring your own key) model client with a platform-controlled allowlist.

Defenders provide only an API key.  The provider entry, base URL and model
name come exclusively from ``MODEL_ALLOWLIST_JSON``, which is read when a
client is constructed (never at import time).  The API key is kept on the
instance only and is never logged, serialized, placed in a URL or included in
error messages.

Faults are split into two classes because the runner treats them differently:

* ``infrastructure`` -- the model backend or transport is unavailable; the
  defender should be considered at fault (abstain).
* ``agent_protocol`` -- the backend replied, but the response was invalid or
  violated the protocol; this is not an infrastructure outage.

No retries are performed here; the runner owns retry/abstention policy.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from .config import ENV_MODEL_ALLOWLIST

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_TOKENS = 1200
MAX_RESPONSE_BYTES = 2_000_000

INFRASTRUCTURE = "infrastructure"
AGENT_PROTOCOL = "agent_protocol"
_KINDS = frozenset({INFRASTRUCTURE, AGENT_PROTOCOL})
_INFRASTRUCTURE_HTTP_CODES = frozenset({401, 402, 403, 429})


class AllowlistError(ValueError):
    """Raised when the model allowlist or a provider entry is invalid."""


class ModelError(RuntimeError):
    """A model call failed.

    ``kind`` is ``"infrastructure"`` or ``"agent_protocol"``; ``usage`` is a
    detached copy of provider usage data when one is available (usually only
    for successful calls).
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str = INFRASTRUCTURE,
        usage: Mapping[str, Any] | None = None,
    ) -> None:
        if kind not in _KINDS:
            raise ValueError(
                f"kind must be one of {sorted(_KINDS)}, got {kind!r}"
            )
        super().__init__(message)
        self.kind = kind
        self.usage: dict[str, Any] = dict(usage) if isinstance(usage, Mapping) else {}


class ModelUnavailable(ModelError):
    """Concrete model failure: backend unavailable or protocol violation."""


def _provider_error(provider: str, detail: str) -> AllowlistError:
    """Build an allowlist error without echoing URLs or other raw values."""

    return AllowlistError(f"provider {provider!r} {detail}")


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_base_url(base_url: str, provider: str) -> None:
    if any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
        for character in base_url
    ):
        raise _provider_error(provider, "base_url must not contain whitespace or control characters")
    if "\\" in base_url:
        raise _provider_error(provider, "base_url must not contain backslashes")

    try:
        parsed = urllib.parse.urlsplit(base_url)
        hostname = parsed.hostname
        _ = parsed.port  # validates the port, if present
    except ValueError:
        raise _provider_error(provider, "base_url is not a valid URL") from None

    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not hostname:
        raise _provider_error(provider, "base_url must be an http(s) URL with a host")

    if parsed.username is not None or parsed.password is not None:
        raise _provider_error(provider, "base_url must not contain userinfo")

    # A path is allowed (for example ``/v1``); queries and fragments are not.
    if parsed.query or parsed.fragment or "?" in base_url or "#" in base_url:
        raise _provider_error(provider, "base_url must not contain a query or fragment")

    if parsed.scheme == "http" and not _is_loopback(hostname):
        raise _provider_error(provider, "base_url must use https unless the host is loopback")


def _validated_allowlist(data: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    if not isinstance(data, Mapping):
        raise AllowlistError("model allowlist must be a mapping")

    allowlist: dict[str, dict[str, str]] = {}
    for provider, entry in data.items():
        if not isinstance(provider, str) or not provider.strip():
            raise AllowlistError("model allowlist provider names must be non-empty strings")
        if not isinstance(entry, Mapping):
            raise AllowlistError(
                f"model allowlist entry {provider!r} must be a mapping"
            )

        base_url = entry.get("base_url")
        model = entry.get("model")
        if not isinstance(base_url, str) or not base_url.strip():
            raise _provider_error(provider, "base_url must be a non-empty string")
        if not isinstance(model, str) or not model.strip():
            raise _provider_error(provider, "model must be a non-empty string")

        base_url = base_url.strip()
        model = model.strip()
        _validate_base_url(base_url, provider)
        allowlist[provider] = {"base_url": base_url, "model": model}

    return allowlist


def load_allowlist(env: Mapping[str, str] | None = None) -> dict[str, dict[str, str]]:
    """Parse and validate ``MODEL_ALLOWLIST_JSON``.

    ``env`` defaults to ``os.environ``.  Missing or blank configuration means
    an empty allowlist.  The returned dictionary and nested entries are fresh
    copies; no API keys are read here.
    """

    env_map = os.environ if env is None else env
    raw = env_map.get(ENV_MODEL_ALLOWLIST)
    if raw is None:
        return {}
    if not isinstance(raw, str):
        raise AllowlistError(f"{ENV_MODEL_ALLOWLIST} must be a JSON string")
    if not raw.strip():
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise AllowlistError(f"{ENV_MODEL_ALLOWLIST} is not valid JSON") from None
    if not isinstance(data, dict):
        raise AllowlistError(f"{ENV_MODEL_ALLOWLIST} must be a JSON object")

    return _validated_allowlist(data)


def _validate_timeout(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timeout must be a positive number")
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive number")
    return timeout


class ByokClient:
    """OpenAI-compatible client bound to one allowlisted provider.

    ``base_url`` and ``model`` cannot be supplied by callers; they are taken
    from the allowlist entry for ``provider``.  The API key is held only on
    this instance and is never exposed by ``repr``.
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        *,
        allowlist: Mapping[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not isinstance(provider, str) or not provider.strip():
            raise AllowlistError("provider must be a non-empty string")

        if allowlist is None:
            allowlist = load_allowlist()
        providers = _validated_allowlist(allowlist)
        entry = providers.get(provider)
        if entry is None:
            raise AllowlistError(
                f"provider {provider!r} is not in the model allowlist"
            )

        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in api_key):
            raise ValueError("api_key must not contain control characters")

        self.provider = provider
        self.base_url = entry["base_url"].rstrip("/")
        self.model = entry["model"]
        self.timeout = _validate_timeout(timeout)
        self._api_key = api_key

    def __repr__(self) -> str:
        return f"{type(self).__name__}(provider={self.provider!r}, model={self.model!r})"

    def _post(self, request: urllib.request.Request, timeout: float) -> Any:
        """Send the request; split out so tests can inject a transport."""

        return urllib.request.urlopen(request, timeout=timeout)

    def complete(
        self,
        messages: list,
        tools: list,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Call ``/chat/completions`` once and return the assistant message."""

        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
        ):
            raise ValueError("max_tokens must be a positive integer")
        effective_timeout = (
            self.timeout if timeout is None else _validate_timeout(timeout)
        )

        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "parallel_tool_calls": False,
                "temperature": 0,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        try:
            with self._post(request, effective_timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            kind = (
                INFRASTRUCTURE
                if exc.code in _INFRASTRUCTURE_HTTP_CODES or 500 <= exc.code <= 599
                else AGENT_PROTOCOL
            )
            raise ModelUnavailable(f"http {exc.code}", kind=kind) from None
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.HTTPException,
            OSError,
        ) as exc:
            raise ModelUnavailable(
                f"transport {type(exc).__name__}", kind=INFRASTRUCTURE
            ) from None

        if len(raw) > MAX_RESPONSE_BYTES:
            raise ModelUnavailable("response too large", kind=AGENT_PROTOCOL)

        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise ModelUnavailable("invalid json", kind=AGENT_PROTOCOL) from None
        if not isinstance(data, dict):
            raise ModelUnavailable("invalid response", kind=AGENT_PROTOCOL)
        if data.get("model") != self.model:
            raise ModelUnavailable("model mismatch", kind=AGENT_PROTOCOL)

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelUnavailable("empty choices", kind=AGENT_PROTOCOL)
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ModelUnavailable("invalid response", kind=AGENT_PROTOCOL)
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ModelUnavailable("invalid message", kind=AGENT_PROTOCOL)

        usage = data.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        return {"message": message, "usage": usage}
