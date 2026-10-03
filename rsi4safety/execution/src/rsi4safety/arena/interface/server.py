"""HTTP surface for the public attack interface (stdlib server, no extra deps)."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .service import InterfaceService, InterfaceError, QuotaError, token_fingerprint

MAX_BODY_BYTES = 64_000
_SESSION_PREFIX = "/v1/sessions/"


class _InterfaceHandler(BaseHTTPRequestHandler):
    server: "_InterfaceServer"

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> str | None:
        header = self.headers.get("Authorization", "")
        scheme, _, credential = header.partition(" ")
        if scheme.lower() != "bearer" or not credential:
            return None
        expected = self.server.service.config.token
        if hmac_compare(credential, expected):
            return token_fingerprint(credential)
        return None

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError("request body exceeds the size budget")
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        service = self.server.service
        fingerprint = self._authorized()
        if fingerprint is None:
            return self._reply(401, {"error": "unauthorized"})
        path = self.path.rstrip("/") or "/"
        try:
            if path == "/v1/sessions":
                return self._reply(201, service.create_session(fingerprint))
            if path.startswith(_SESSION_PREFIX):
                parts = path[len(_SESSION_PREFIX):].split("/")
                if len(parts) == 3 and parts[1] == "surfaces":
                    payload = self._read_json()
                    return self._reply(200, service.deliver_surface(parts[0], parts[2],
                                                                    payload.get("content", "")))
                if len(parts) == 2 and parts[1] == "run":
                    return self._reply(200, service.run(parts[0], fingerprint))
            # Red line: there is deliberately no route for verdicts, rewards,
            # claims or trusted authorization on the attacker surface.
            return self._reply(404, {"error": "no such route"})
        except QuotaError as exc:
            return self._reply(429, {"error": str(exc)})
        except LookupError as exc:
            return self._reply(410, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            return self._reply(400, {"error": str(exc)})

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        service = self.server.service
        fingerprint = self._authorized()
        if fingerprint is None:
            return self._reply(401, {"error": "unauthorized"})
        path = self.path.rstrip("/") or "/"
        try:
            if path == "/v1/health":
                return self._reply(200, {"ok": True,
                                         "target_version": {"digest": service.target_version_digest}})
            if path.startswith(_SESSION_PREFIX):
                parts = path[len(_SESSION_PREFIX):].split("/")
                if len(parts) == 2 and parts[1] == "trace":
                    return self._reply(200, service.trace(parts[0], fingerprint))
            return self._reply(404, {"error": "no such route"})
        except LookupError as exc:
            return self._reply(410, {"error": str(exc)})

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        pass  # never log paths/tokens; the audit trail lives in the submission store


def hmac_compare(credential: str, expected: str) -> bool:
    import hmac
    return hmac.compare_digest(credential.encode("utf-8"), expected.encode("utf-8"))


class _InterfaceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service: InterfaceService):
        super().__init__(address, _InterfaceHandler)
        self.service = service


def serve(config) -> tuple[_InterfaceServer, str]:
    """Start the interface server; returns (server, base_url). Call serve_forever()."""
    service = InterfaceService(config)
    server = _InterfaceServer((config.host, config.port), service)
    host, port = server.server_address[:2]
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else str(host)
    return server, f"http://{shown}:{port}"
