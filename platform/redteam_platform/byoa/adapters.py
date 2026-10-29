"""Four defender transports behind the single ``DefenderPort`` seam.

Everything runs inside the sealed runtime; the platform API never calls these
endpoints directly.  The HTTP client disables redirects, bounds response size
and never logs message content.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import Channel, ContentKind, InboundMessage, OutboundReply
from .ports import DefenderUnavailable

MAX_RESPONSE_BYTES = 1_000_000
MAX_URL_LENGTH = 2048
DEFAULT_TIMEOUT = 30.0
MAX_TOOL_CALLS = 64


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        raise ValueError("endpoint must be a bounded URL")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("endpoint must use http or https")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("endpoint must contain a host and no credentials")
    return url


def _bounded_timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timeout must be a positive number")
    timeout = float(value)
    if not 0 < timeout <= 300:
        raise ValueError("timeout must be positive and at most 300 seconds")
    return timeout


@dataclass
class HttpJsonClient:
    timeout: float = DEFAULT_TIMEOUT
    max_bytes: int = MAX_RESPONSE_BYTES
    _opener: urllib.request.OpenerDirector = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.timeout = _bounded_timeout(self.timeout)
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect()
        )

    def post(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.post_raw(url, body, headers=headers)

    def post_raw(
        self,
        url: str,
        body: bytes,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        url = _validate_url(url)
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        return self._open(request)

    def get(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        url = _validate_url(url)
        return self._open(urllib.request.Request(url, method="GET", headers=headers or {}))

    def _open(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(self.max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise DefenderUnavailable(f"defender returned HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DefenderUnavailable(f"defender transport failed: {type(exc).__name__}") from None
        if len(raw) > self.max_bytes:
            raise DefenderUnavailable("defender response is too large")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise DefenderUnavailable("defender response is not JSON") from None
        if not isinstance(decoded, dict):
            raise DefenderUnavailable("defender response must be a JSON object")
        return decoded


def _reply_from_payload(payload: Mapping[str, Any]) -> OutboundReply:
    text = payload.get("reply", payload.get("text"))
    if not isinstance(text, str):
        raise DefenderUnavailable("defender response is missing reply text")
    calls = payload.get("tool_calls", [])
    if not isinstance(calls, list) or len(calls) > MAX_TOOL_CALLS:
        raise DefenderUnavailable("defender response has invalid tool_calls")
    normalized: list[Mapping[str, Any]] = []
    for call in calls:
        if not isinstance(call, Mapping):
            raise DefenderUnavailable("defender tool call must be an object")
        normalized.append(dict(call))
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    return OutboundReply(
        text=text, tool_calls=tuple(normalized), metadata=dict(metadata)
    )


class WebhookAdapter:
    """Signed JSON webhook: ``POST /arena/turn`` with HMAC-SHA256."""

    kind = "webhook"

    def __init__(
        self,
        endpoint: str,
        *,
        secret: str,
        timeout: float = DEFAULT_TIMEOUT,
        client: HttpJsonClient | None = None,
        wallet_mcp_url: str | None = None,
        wallet_token: str | None = None,
    ) -> None:
        if not isinstance(secret, str) or len(secret) < 16:
            raise ValueError("webhook secret must be at least 16 characters")
        self.endpoint = _validate_url(endpoint)
        self._secret = secret.encode("utf-8")
        self._client = client or HttpJsonClient(timeout=timeout)
        self._wallet = _wallet_ref(wallet_mcp_url, wallet_token)

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def send(self, message: InboundMessage) -> OutboundReply:
        envelope = message.as_envelope()
        if self._wallet is not None:
            envelope["wallet_mcp"] = self._wallet
        body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        signature = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        response = self._client.post_raw(
            self.endpoint,
            body,
            headers={
                "X-RTM-Signature": f"sha256={signature}",
                "X-RTM-Contest": message.contest_id,
            },
        )
        return _reply_from_payload(response)


class A2aAdapter:
    """A2A v1 ``message/send`` client; accepts Message or Task results."""

    kind = "a2a"

    def __init__(
        self,
        endpoint: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        wallet_mcp_url: str | None = None,
        wallet_token: str | None = None,
    ) -> None:
        self.endpoint = _validate_url(endpoint)
        self._client = HttpJsonClient(timeout=timeout)
        self._wallet = _wallet_ref(wallet_mcp_url, wallet_token)

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def send(self, message: InboundMessage) -> OutboundReply:
        request_id = uuid.uuid4().hex
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": uuid.uuid4().hex,
                    "parts": [{"kind": "text", "text": message.content}],
                    "metadata": {
                        "channel": message.channel.value,
                        "kind": message.kind.value,
                        "seq": message.seq,
                        "contestId": message.contest_id,
                        **({"wallet_mcp": self._wallet} if self._wallet else {}),
                        **dict(message.metadata),
                    },
                }
            },
        }
        response = self._client.post(self.endpoint, payload)
        if response.get("error") is not None:
            raise DefenderUnavailable("A2A defender returned an error")
        result = response.get("result")
        if isinstance(result, Mapping):
            texts = _a2a_texts(result)
            if texts:
                return OutboundReply(text="\n".join(texts))
        raise DefenderUnavailable("A2A response contains no text parts")


def _a2a_texts(result: Mapping[str, Any]) -> list[str]:
    texts: list[str] = []

    def collect(parts: Any) -> None:
        if not isinstance(parts, list):
            return
        for part in parts:
            if isinstance(part, Mapping) and part.get("kind") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    texts.append(text)

    if result.get("kind") == "message" or "parts" in result:
        collect(result.get("parts"))
    message = result.get("message")
    if isinstance(message, Mapping):
        collect(message.get("parts"))
    status = result.get("status")
    if isinstance(status, Mapping):
        status_message = status.get("message")
        if isinstance(status_message, Mapping):
            collect(status_message.get("parts"))
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, Mapping):
                collect(artifact.get("parts"))
    return texts


class HostedMcpAdapter:
    """Main path: the defender harness runs in the CVM and uses wallet MCP.

    The harness endpoint receives the conversation envelope plus the
    CVM-internal wallet MCP URL/token; all payment tool calls happen through
    that sidecar, so the driver can log and score them.
    """

    kind = "hosted-mcp"

    def __init__(
        self,
        endpoint: str,
        *,
        wallet_mcp_url: str,
        wallet_token: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        base = _validate_url(endpoint).rstrip("/")
        self.endpoint = base if base.endswith("/arena/turn") else base + "/arena/turn"
        self.wallet_mcp_url = _validate_url(wallet_mcp_url)
        if not isinstance(wallet_token, str) or len(wallet_token) < 16:
            raise ValueError("wallet token must be at least 16 characters")
        self._wallet_token = wallet_token
        self._client = HttpJsonClient(timeout=timeout)

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def send(self, message: InboundMessage) -> OutboundReply:
        payload = {
            **message.as_envelope(),
            "wallet_mcp": {
                "url": self.wallet_mcp_url,
                "token": self._wallet_token,
            },
        }
        response = self._client.post(self.endpoint, payload)
        return _reply_from_payload(response)


@dataclass
class _Pending:
    message: InboundMessage
    event: threading.Event = field(default_factory=threading.Event)
    reply: OutboundReply | None = None


class PullInbox:
    """Server side of the mcp-pull transport.

    The defender agent long-polls :meth:`next_message` and posts
    :meth:`submit_reply`.  The driver's :class:`McpPullAdapter` blocks on
    :meth:`deliver` until the reply arrives or the turn times out.
    """

    def __init__(
        self,
        *,
        wallet_mcp_url: str,
        wallet_token: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.wallet_mcp_url = _validate_url(wallet_mcp_url)
        if not isinstance(wallet_token, str) or len(wallet_token) < 16:
            raise ValueError("wallet token must be at least 16 characters")
        self._wallet_token = wallet_token
        self._timeout = _bounded_timeout(timeout)
        self._pending: _Pending | None = None
        self._lock = threading.RLock()

    @property
    def timeout(self) -> float:
        return self._timeout

    def deliver(self, message: InboundMessage) -> OutboundReply:
        pending = _Pending(message=message)
        with self._lock:
            if self._pending is not None:
                raise DefenderUnavailable("pull inbox already has a pending turn")
            self._pending = pending
        completed = pending.event.wait(self._timeout)
        with self._lock:
            reply = pending.reply
            if self._pending is pending:
                self._pending = None
        if not completed or reply is None:
            raise DefenderUnavailable("defender did not answer the pull inbox")
        return reply

    def next_message(self) -> dict[str, Any] | None:
        with self._lock:
            pending = self._pending
            if pending is None:
                return None
            return {
                "message": pending.message.as_envelope(),
                "wallet_mcp": {
                    "url": self.wallet_mcp_url,
                    "token": self._wallet_token,
                },
            }

    def submit_reply(
        self,
        *,
        seq: int,
        text: str,
        tool_calls: tuple[Mapping[str, Any], ...] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        if isinstance(seq, bool) or not isinstance(seq, int):
            raise ValueError("seq must be an integer")
        if not isinstance(text, str) or len(text) > 50_000:
            raise ValueError("reply text must be a bounded string")
        with self._lock:
            pending = self._pending
            if pending is None or pending.message.seq != seq:
                return False
            pending.reply = OutboundReply(
                text=text,
                tool_calls=tuple(dict(call) for call in tool_calls),
                metadata=dict(metadata or {}),
            )
            pending.event.set()
            return True


class McpPullAdapter:
    """Driver-side client for the pull inbox."""

    kind = "mcp-pull"

    def __init__(self, inbox: PullInbox) -> None:
        self.inbox = inbox

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def send(self, message: InboundMessage) -> OutboundReply:
        return self.inbox.deliver(message)


def _wallet_ref(
    wallet_mcp_url: str | None, wallet_token: str | None
) -> dict[str, str] | None:
    if wallet_mcp_url is None and wallet_token is None:
        return None
    if wallet_mcp_url is None or wallet_token is None:
        raise ValueError("wallet_mcp_url and wallet_token must be provided together")
    if len(wallet_token) < 16:
        raise ValueError("wallet token must be at least 16 characters")
    return {"url": _validate_url(wallet_mcp_url), "token": wallet_token}


def build_adapter(
    kind: str,
    *,
    endpoint: str,
    secret: str | None = None,
    wallet_mcp_url: str | None = None,
    wallet_token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    inbox: PullInbox | None = None,
) -> HostedMcpAdapter | A2aAdapter | WebhookAdapter | McpPullAdapter:
    """Build one of the four supported transports."""

    if kind == "hosted-mcp":
        if wallet_mcp_url is None or wallet_token is None:
            raise ValueError("hosted-mcp requires wallet_mcp_url and wallet_token")
        return HostedMcpAdapter(
            endpoint,
            wallet_mcp_url=wallet_mcp_url,
            wallet_token=wallet_token,
            timeout=timeout,
        )
    if kind == "a2a":
        return A2aAdapter(
            endpoint,
            timeout=timeout,
            wallet_mcp_url=wallet_mcp_url,
            wallet_token=wallet_token,
        )
    if kind == "webhook":
        if secret is None:
            raise ValueError("webhook requires a shared secret")
        return WebhookAdapter(
            endpoint,
            secret=secret,
            timeout=timeout,
            wallet_mcp_url=wallet_mcp_url,
            wallet_token=wallet_token,
        )
    if kind == "mcp-pull":
        if inbox is not None:
            return McpPullAdapter(inbox)
        if wallet_mcp_url is None or wallet_token is None:
            raise ValueError("mcp-pull requires wallet_mcp_url and wallet_token")
        return McpPullAdapter(
            PullInbox(
                wallet_mcp_url=wallet_mcp_url,
                wallet_token=wallet_token,
                timeout=timeout,
            )
        )
    raise ValueError(f"unsupported defender transport: {kind}")
