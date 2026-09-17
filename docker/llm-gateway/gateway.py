"""Hardened LLM egress gateway for the RSI Arena battle network.

Threat model: attacker-controlled containers share the Docker network with
this gateway, so every request is hostile until proven otherwise.

Invariants (exercised by tests/arena/test_gateway.py):
  * Auth: exactly `Authorization: Bearer $GATEWAY_TOKEN` (constant-time
    compare). No configured token -> forwarding is refused outright (503);
    wrong/missing token -> 401. The raw GLM key never leaves this process.
  * Rate limiting: per-client-IP token bucket (GATEWAY_RATE_LIMIT_PER_MIN
    requests per minute, burst == limit). GET /health is neither limited
    nor counted.
  * Model allowlist: GATEWAY_ALLOWED_MODELS (comma separated), tolerating
    "[1m]"-style variant suffixes on the requested model name.
  * No request smuggling: HTTP/1.0 semantics (one request per connection,
    `Connection: close` on every response), Content-Length must be a plain
    digit string <= 8 MiB, duplicate Content-Length / Transfer-Encoding are
    rejected, and exactly Content-Length body bytes are consumed.
  * No redirect leakage: upstream calls go through an opener that never
    follows redirects (mirrors rsi4safety.providers._NoRedirect) so the
    Authorization header can never be replayed against a redirect target;
    upstream 3xx is surfaced to the client as 502.
  * Log discipline: exactly one JSON line per request on stdout; tokens,
    keys and request/response bodies are never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8080

DEFAULT_OPENAI_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
DEFAULT_ANTHROPIC_BASE_URL = "https://open.bigmodel.cn/api/anthropic"
DEFAULT_ALLOWED_MODELS = "glm-5.3,glm-5.3-flash"
DEFAULT_RATE_LIMIT_PER_MIN = 60

MAX_BODY_BYTES = 8 * 1024 * 1024  # hard cap on forwarded request bodies
UPSTREAM_TIMEOUT_SECONDS = 120
SOCKET_TIMEOUT_SECONDS = 30

# Gateway route -> (base-url env var, default base url, upstream path suffix).
ROUTES = {
    "/v1/chat/completions": ("GLM_OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL, "/chat/completions"),
    "/v1/messages": ("GLM_ANTHROPIC_BASE_URL", DEFAULT_ANTHROPIC_BASE_URL, "/v1/messages"),
}

_DIGITS_ONLY_RE = re.compile(r"\A\d+\Z")
_MODEL_SUFFIX_RE = re.compile(r"\[[^\[\]]*\]\Z")
_LOG_LOCK = threading.Lock()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects (mirrors rsi4safety.providers._NoRedirect).

    urllib would otherwise silently replay the Authorization-bearing request
    against whatever host the upstream (or a man in the middle) points at.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Deterministic egress: no environment-proxy surprises, no redirects.
_OPENER = urllib.request.build_opener(_NoRedirect(), urllib.request.ProxyHandler({}))


class TokenBucketLimiter:
    """Per-key token bucket; capacity == burst == refill-per-minute."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict = {}  # key -> (tokens, last_monotonic)

    def take(self, key: str, limit_per_minute: int):
        """Consume one token if available; returns (allowed, remaining)."""
        now = time.monotonic()
        with self._lock:
            if len(self._state) > 4096:  # bound memory under address churn
                stale_cutoff = now - 600.0
                self._state = {k: v for k, v in self._state.items() if v[1] > stale_cutoff}
            capacity = float(limit_per_minute)
            tokens, last = self._state.get(key, (capacity, now))
            tokens = min(capacity, tokens + (now - last) * limit_per_minute / 60.0)
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            self._state[key] = (tokens, now)
            return allowed, max(0, int(tokens))

    def reset(self) -> None:
        with self._lock:
            self._state.clear()


_LIMITER = TokenBucketLimiter()


def _rate_limit_per_minute() -> int:
    raw = (os.environ.get("GATEWAY_RATE_LIMIT_PER_MIN") or "").strip()
    if not raw:
        return DEFAULT_RATE_LIMIT_PER_MIN
    try:
        value = int(raw, 10)
    except ValueError:
        return DEFAULT_RATE_LIMIT_PER_MIN
    return value if value > 0 else DEFAULT_RATE_LIMIT_PER_MIN


def _allowed_models() -> set:
    raw = os.environ.get("GATEWAY_ALLOWED_MODELS")
    if raw is None or not raw.strip():
        raw = DEFAULT_ALLOWED_MODELS
    return {name.strip() for name in raw.split(",") if name.strip()}


def _gateway_token() -> str:
    return os.environ.get("GATEWAY_TOKEN") or ""


def _authorized(header_value) -> bool:
    token = _gateway_token()
    if not token:
        return False
    expected = f"Bearer {token}".encode("utf-8")
    received = (header_value or "").encode("utf-8", "replace")
    # Exact full-header match (no suffix/whitespace tricks), constant time.
    return hmac.compare_digest(received, expected)


def _parse_model(body: bytes):
    """Return (model, None) on success or (None, error_code) for bad bodies."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "body_not_object"
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        return None, "missing_model"
    return model, None


def _base_model(model: str) -> str:
    """Strip a trailing bracketed variant tag: 'glm-5.3[1m]' -> 'glm-5.3'."""
    return _MODEL_SUFFIX_RE.sub("", model)


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _clean_header(value: str, fallback: str) -> str:
    """Defensive header passthrough: no CR/LF, bounded length."""
    value = value.split("\r")[0].split("\n")[0].strip()[:200]
    return value or fallback


class Handler(BaseHTTPRequestHandler):
    """One request per connection; every response closes the socket."""

    protocol_version = "HTTP/1.0"  # HTTP/1.0 semantics: no keep-alive surface
    server_version = "rsi4safety-llm-gateway/2"
    sys_version = ""
    timeout = SOCKET_TIMEOUT_SECONDS

    def log_message(self, fmt: str, *args) -> None:  # default stderr noise off
        pass

    # -- entry points -------------------------------------------------------

    def do_GET(self) -> None:
        self._guard(self._get)

    def do_POST(self) -> None:
        self._guard(self._post)

    def _guard(self, action) -> None:
        self._started = time.monotonic()
        self.close_connection = True
        try:
            action()
        except Exception:  # noqa: BLE001 - one bad request must never kill the worker
            self._send(500, {"error": "internal_error"})

    # -- request handling ---------------------------------------------------

    def _get(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/health":  # local liveness: no auth, no rate limit, no counting
            self._send(200, {"status": "ok"})
            self._log(path=path, status=200)
            return
        self._send(404, {"error": "not_found"})
        self._log(path=path, status=404, error_category="not_found")

    def _post(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/health":  # answered locally, never forwarded upstream
            self._drain_body()
            self._send(405, {"error": "method_not_allowed"}, extra_headers=[("Allow", "GET")])
            self._log(path=path, status=405, error_category="method_not_allowed")
            return
        route = ROUTES.get(path)
        if route is None:
            self._drain_body()
            self._send(404, {"error": "path_not_allowed"})
            self._log(path=path, status=404, error_category="path_not_allowed")
            return
        if not _gateway_token():  # unconfigured = refuse to forward anything
            self._drain_body()
            self._send(503, {"error": "gateway_not_configured"})
            self._log(path=path, status=503, error_category="gateway_token_missing")
            return
        allowed, remaining = _LIMITER.take(self.client_address[0], _rate_limit_per_minute())
        if not allowed:
            self._drain_body()
            self._send(429, {"error": "rate_limited"})
            self._log(path=path, status=429, rate_limit_remaining=0)
            return
        if not _authorized(self.headers.get("Authorization")):
            self._drain_body()
            self._send(401, {"error": "unauthorized"})
            self._log(path=path, status=401, rate_limit_remaining=remaining,
                      error_category="auth_failed")
            return
        body, length_error = self._read_exact_body()
        if length_error is not None:
            status, code = length_error
            self._send(status, {"error": code})
            self._log(path=path, status=status, rate_limit_remaining=remaining,
                      error_category=code)
            return
        model, model_error = _parse_model(body)
        if model_error is not None:
            self._send(400, {"error": model_error})
            self._log(path=path, status=400, request_sha256=_sha256(body),
                      rate_limit_remaining=remaining, error_category=model_error)
            return
        if _base_model(model) not in _allowed_models():
            self._send(400, {"error": "model_not_allowed"})
            self._log(path=path, status=400, model=model, request_sha256=_sha256(body),
                      rate_limit_remaining=remaining, error_category="model_not_allowed")
            return
        self._forward(path, route, body, model, remaining)

    def _read_exact_body(self):
        """Read exactly Content-Length bytes; reject anything ambiguous.

        Duplicate Content-Length headers, Transfer-Encoding, and non-digit /
        negative / oversized values are the classic request-smuggling
        primitives against naive keep-alive proxies.
        """
        if self.headers.get_all("Transfer-Encoding"):
            return None, (400, "unsupported_transfer_encoding")
        lengths = self.headers.get_all("Content-Length") or []
        if not lengths:
            return None, (411, "length_required")
        if len(lengths) > 1:
            return None, (400, "ambiguous_content_length")
        raw = lengths[0].strip()
        if not _DIGITS_ONLY_RE.match(raw):  # rejects "-1", "+5", "0x10", ...
            return None, (400, "bad_content_length")
        length = int(raw, 10)
        if length > MAX_BODY_BYTES:
            return None, (400, "body_too_large")
        try:
            body = self.rfile.read(length)
        except OSError:
            return None, (400, "body_read_failed")
        if len(body) != length:
            return None, (400, "short_body")
        return body, None

    def _drain_body(self) -> None:
        """Best-effort drain of a declared body on early-reject paths.

        Keeps the error response from being lost to a TCP reset when the
        socket is closed with unread data. Bounded by MAX_BODY_BYTES and the
        socket timeout; only attempted when Content-Length is unambiguous.
        """
        try:
            if self.headers.get_all("Transfer-Encoding"):
                return
            lengths = self.headers.get_all("Content-Length") or []
            if len(lengths) != 1:
                return
            raw = lengths[0].strip()
            if not _DIGITS_ONLY_RE.match(raw):
                return
            remaining = int(raw, 10)
            if remaining > MAX_BODY_BYTES:
                return
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass

    # -- upstream forwarding -------------------------------------------------

    def _forward(self, path: str, route, body: bytes, model: str, remaining: int) -> None:
        env_name, default_base, suffix = route
        base_url = os.environ.get(env_name) or default_base
        upstream_url = base_url.rstrip("/") + suffix
        api_key = os.environ.get("GLM_API_KEY", "")
        upstream_request = urllib.request.Request(
            upstream_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "rsi4safety-llm-gateway/2",
            },
        )
        log_tail = {"path": path, "model": model, "request_sha256": _sha256(body),
                    "rate_limit_remaining": remaining}
        try:
            with _OPENER.open(upstream_request, timeout=UPSTREAM_TIMEOUT_SECONDS) as response:
                status = response.status
                raw = response.read()
                content_type = _clean_header(
                    response.headers.get("Content-Type", ""), "application/json")
        except urllib.error.HTTPError as exc:
            try:
                exc.close()
            except Exception:  # noqa: BLE001 - release of the error socket is best effort
                pass
            if 300 <= exc.code < 400:
                # Following this redirect would have replayed our Authorization.
                self._send(502, {"error": "upstream_redirect"})
                self._log(status=502, upstream_status=exc.code,
                          error_category="upstream_redirect", **log_tail)
                return
            status = exc.code
            try:
                raw = exc.read()
                content_type = _clean_header(
                    (exc.headers or {}).get("Content-Type", ""), "application/json")
            except Exception:  # noqa: BLE001 - error body is optional
                raw, content_type = b'{"error": "upstream_failed"}', "application/json"
        except Exception:  # noqa: BLE001 - DNS, refused sockets, timeouts, TLS, ...
            self._send(502, {"error": "upstream_failed"})
            self._log(status=502, error_category="upstream_unreachable", **log_tail)
            return
        self._send(status, raw, content_type)
        self._log(status=status, upstream_status=status,
                  error_category="upstream_http_error" if status >= 400 else None, **log_tail)

    # -- responses and logging ------------------------------------------------

    def _send(self, status: int, payload, content_type: str = "application/json",
              extra_headers=()) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        if getattr(self, "_responded", False):  # never emit a second response
            self.close_connection = True
            return
        self._responded = True
        try:
            self.send_response(status)
            for keyword, value in extra_headers:
                self.send_header(keyword, value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")  # also sets close_connection
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass  # client vanished mid-response; nothing left to protect
        finally:
            self.close_connection = True

    def _log(self, *, path: str, status: int, model=None, request_sha256=None,
             rate_limit_remaining=None, upstream_status=None, error_category=None) -> None:
        started = getattr(self, "_started", None)
        entry = {
            "event": "request",
            "path": path,
            "status": status,
            "model": model,
            "request_sha256": request_sha256,
            "duration_ms": round((time.monotonic() - started) * 1000, 3) if started else None,
            "rate_limit_remaining": rate_limit_remaining,
        }
        if upstream_status is not None:  # upstream errors: status + category only
            entry["upstream_status"] = upstream_status
        if error_category is not None:
            entry["error_category"] = error_category
        line = json.dumps(entry, ensure_ascii=False)
        with _LOG_LOCK:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()


def main() -> None:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(json.dumps({
        "event": "gateway_started",
        "listen": f"{LISTEN_HOST}:{LISTEN_PORT}",
        "auth": "token_required" if _gateway_token() else "unconfigured_refusing_forwarding",
        "rate_limit_per_min": _rate_limit_per_minute(),
        "allowed_models": sorted(_allowed_models()),
    }), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
