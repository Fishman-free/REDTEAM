"""Allowlisted LLM egress proxy for PayGate.

The SUT container sits on an internal network with no internet route; this
gateway is its only door to the model API, and every forwarded call is logged
to stdout so container logs become part of the audit evidence.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED_PATHS = {"/v1/chat/completions", "/health"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # route stderr noise into our own log line
        pass

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._reply(200, {"status": "ok"})
            return
        self._reply(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path not in ALLOWED_PATHS:
            self._reply(404, {"error": "path_not_allowed"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
        except ValueError:
            self._reply(400, {"error": "bad_length"})
            return
        upstream = os.environ.get(
            "GLM_OPENAI_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4"
        ).rstrip("/") + "/chat/completions"
        key = os.environ.get("GLM_API_KEY", "")
        request = urllib.request.Request(
            upstream, data=body, method="POST",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "User-Agent": "rsi4safety-llm-gateway/1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller verbatim
            print(json.dumps({"event": "upstream_error", "error": str(exc)[:300]}),
                  file=sys.stderr, flush=True)
            self._reply(502, {"error": "upstream_failed"})
            return
        try:
            usage = (json.loads(raw) or {}).get("usage", {})
        except ValueError:
            usage = {}
        print(json.dumps({
            "event": "forwarded", "path": self.path, "status": status,
            "request_sha256": __import__("hashlib").sha256(body).hexdigest()[:16],
            "model": (json.loads(body or b"{}") or {}).get("model"),
            "usage": usage,
        }), flush=True)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
