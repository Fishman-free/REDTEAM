import os
"""Security regression tests for docker/llm-gateway/gateway.py.

The gateway lives outside the importable package tree, so it is loaded by
path with importlib and served for real over HTTP via ThreadingHTTPServer on
an ephemeral port. The upstream LLM API is replaced by a local stub server;
both GLM_*_BASE_URL env vars are pointed at it for every test.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import socket
import sys
import threading
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

GATEWAY_FILE = Path(__file__).resolve().parents[2] / "docker" / "llm-gateway" / "gateway.py"
STUB_API_KEY = os.environ.get("TEST_UPSTREAM_KEY", "stub-not-real")
TOKEN = os.environ.get("TEST_GATEWAY_TOKEN", "unit-test-not-real")
STUB_REQUESTS: list = []  # appended by the stub upstream, read by assertions


def _load_gateway():
    spec = importlib.util.spec_from_file_location("gateway", GATEWAY_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gateway"] = module
    spec.loader.exec_module(module)
    return module


gateway = _load_gateway()


class _StubUpstreamHandler(BaseHTTPRequestHandler):
    """Records every request; answers 200 or a self-referencing 302."""

    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length > 0 else b""
        STUB_REQUESTS.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "body": body,
        })
        if getattr(self.server, "stub_mode", "ok") == "redirect":
            # Points back at the stub itself: if the gateway follows the
            # redirect a second entry appears in STUB_REQUESTS.
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/redirected")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        try:
            decoded = json.loads(body) if body else {}
        except ValueError:
            decoded = None
        payload = json.dumps({
            "stub": True,
            "path": self.path,
            "saw_model": (decoded or {}).get("model"),
            "saw_authorization": self.headers.get("Authorization"),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)


class GatewayTestCase(unittest.TestCase):
    """Fresh gateway + stub servers (and env) per test method."""

    def setUp(self):
        self._env_backup = os.environ.copy()
        self.stub = ThreadingHTTPServer(("127.0.0.1", 0), _StubUpstreamHandler)
        self.stub.stub_mode = "ok"
        self._stub_thread = threading.Thread(target=self.stub.serve_forever,
                                             kwargs={"poll_interval": 0.05}, daemon=True)
        self._stub_thread.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
        self._server_thread = threading.Thread(target=self.server.serve_forever,
                                               kwargs={"poll_interval": 0.05}, daemon=True)
        self._server_thread.start()
        stub_base = f"http://127.0.0.1:{self.stub.server_port}"
        os.environ.update({
            "GATEWAY_TOKEN": TOKEN,
            "GLM_API_KEY": STUB_API_KEY,
            "GATEWAY_RATE_LIMIT_PER_MIN": "60",
            "GLM_OPENAI_BASE_URL": stub_base,
            "GLM_ANTHROPIC_BASE_URL": stub_base,
        })
        # The gateway must never be influenced by a developer-shell proxy.
        for var in ("http_proxy", "https_proxy", "all_proxy",
                    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            os.environ.pop(var, None)
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        STUB_REQUESTS.clear()
        gateway._LIMITER.reset()  # all tests share the client IP 127.0.0.1

    def tearDown(self):
        try:
            self.server.shutdown()
            self.server.server_close()
            self.stub.shutdown()
            self.stub.server_close()
        finally:
            os.environ.clear()
            os.environ.update(self._env_backup)

    # -- helpers -------------------------------------------------------------

    @property
    def auth_headers(self):
        return {"Authorization": f"Bearer {TOKEN}"}

    def request(self, method, path, body=None, headers=None, timeout=15):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=timeout)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            data = response.read()
            return response.status, response.getheaders(), data
        finally:
            conn.close()

    def post_json(self, path, payload, headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return self.request("POST", path, body=body, headers=headers)

    def raw_exchange(self, payload: bytes, timeout: float = 5.0):
        """Send raw bytes, read until EOF/timeout; returns (data, saw_eof)."""
        with socket.create_connection(("127.0.0.1", self.server.server_port),
                                       timeout=timeout) as sock:
            sock.sendall(payload)
            chunks, eof = [], False
            while True:
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    eof = True
                    break
                chunks.append(chunk)
        return b"".join(chunks), eof

    @staticmethod
    def status_line(data: bytes) -> bytes:
        return data.split(b"\r\n", 1)[0]

    def chat_body(self, model="glm-5.3", content="pay this invoice"):
        return {"model": model, "messages": [{"role": "user", "content": content}]}

    # -- auth ------------------------------------------------------------------

    def test_missing_authorization_header_401(self):
        status, _, _ = self.post_json("/v1/chat/completions", self.chat_body())
        self.assertEqual(status, 401)
        self.assertEqual(len(STUB_REQUESTS), 0)

    def test_wrong_token_401(self):
        for header in (f"Bearer {TOKEN}-wrong", "Bearer", f"Basic {TOKEN}",
                       f"Bearer {TOKEN} trailing", f"bearer {TOKEN}"):
            with self.subTest(header=header):
                status, _, _ = self.post_json(
                    "/v1/chat/completions", self.chat_body(), {"Authorization": header})
                self.assertEqual(status, 401)
        self.assertEqual(len(STUB_REQUESTS), 0)

    def test_correct_token_forwards_to_openai_upstream(self):
        status, headers, data = self.post_json(
            "/v1/chat/completions", self.chat_body(), self.auth_headers)
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertTrue(payload["stub"])
        self.assertEqual(payload["saw_model"], "glm-5.3")
        self.assertEqual(len(STUB_REQUESTS), 1)
        seen = STUB_REQUESTS[0]
        self.assertEqual(seen["path"], "/chat/completions")
        self.assertEqual(seen["authorization"], f"Bearer {STUB_API_KEY}")
        self.assertEqual(seen["content_type"], "application/json")
        header_names = {name.lower() for name, _ in headers}
        self.assertIn("connection", header_names)

    def test_missing_gateway_token_env_refuses_forwarding_503(self):
        os.environ["GATEWAY_TOKEN"] = ""
        status, _, _ = self.post_json("/v1/chat/completions", self.chat_body(),
                                      self.auth_headers)
        self.assertEqual(status, 503)
        self.assertEqual(len(STUB_REQUESTS), 0)
        # /health stays a purely local liveness probe.
        status, _, _ = self.request("GET", "/health")
        self.assertEqual(status, 200)

    # -- rate limiting -----------------------------------------------------------

    def test_rate_limit_429_and_health_exempt(self):
        os.environ["GATEWAY_RATE_LIMIT_PER_MIN"] = "2"
        self.assertEqual(self.post_json("/v1/chat/completions", self.chat_body(),
                                        self.auth_headers)[0], 200)
        self.assertEqual(self.post_json("/v1/chat/completions", self.chat_body(),
                                        self.auth_headers)[0], 200)
        self.assertEqual(self.post_json("/v1/chat/completions", self.chat_body(),
                                        self.auth_headers)[0], 429)
        # /health is neither limited nor counted: still 200, and it does not
        # refill the bucket for another forwarding attempt.
        for _ in range(5):
            self.assertEqual(self.request("GET", "/health")[0], 200)
        self.assertEqual(self.post_json("/v1/chat/completions", self.chat_body(),
                                        self.auth_headers)[0], 429)
        self.assertEqual(len(STUB_REQUESTS), 2)

    # -- model allowlist ----------------------------------------------------------

    def test_model_outside_allowlist_400(self):
        for model in ("gpt-4o", "glm-4.6", "glm-5.3-evil"):
            with self.subTest(model=model):
                status, _, _ = self.post_json("/v1/chat/completions",
                                              self.chat_body(model=model), self.auth_headers)
                self.assertEqual(status, 400)
        self.assertEqual(len(STUB_REQUESTS), 0)

    def test_model_variant_suffix_allowed_and_body_forwarded_verbatim(self):
        status, _, data = self.post_json("/v1/chat/completions",
                                         self.chat_body(model="glm-5.3[1m]"), self.auth_headers)
        self.assertEqual(status, 200)
        # The allowlist matched after stripping "[1m]" and the upstream saw the
        # original, unmodified request body.
        self.assertEqual(json.loads(STUB_REQUESTS[0]["body"])["model"], "glm-5.3[1m]")

    # -- malformed bodies -----------------------------------------------------------

    def test_malformed_bodies_400_and_service_survives(self):
        bad_bodies = [
            b"{not json",
            b'"just a string"',
            b"[1, 2, 3]",
            b"",
            b'{"messages": []}',       # no model field
            b'{"model": 42}',          # model not a string
            b'{"model": ""}',
        ]
        for body in bad_bodies:
            with self.subTest(body=body):
                status, _, _ = self.post_json("/v1/chat/completions", body, self.auth_headers)
                self.assertEqual(status, 400)
        self.assertEqual(len(STUB_REQUESTS), 0)
        status, _, data = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["status"], "ok")

    # -- content-length discipline ----------------------------------------------

    def test_negative_content_length_rejected(self):
        raw = (f"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\n"
               f"Authorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\n"
               f"Content-Length: -5\r\n\r\n").encode()
        data, eof = self.raw_exchange(raw)
        self.assertIn(b"400", self.status_line(data))
        self.assertTrue(eof)
        self.assertEqual(len(STUB_REQUESTS), 0)

    def test_oversized_content_length_rejected(self):
        raw = (f"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\n"
               f"Authorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\n"
               f"Content-Length: {8 * 1024 * 1024 + 1}\r\n\r\n").encode()
        data, eof = self.raw_exchange(raw)
        self.assertIn(b"400", self.status_line(data))
        self.assertTrue(eof)
        self.assertEqual(len(STUB_REQUESTS), 0)

    def test_missing_content_length_411_and_duplicate_rejected_400(self):
        raw = (f"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\n"
               f"Authorization: Bearer {TOKEN}\r\n\r\n").encode()
        data, _ = self.raw_exchange(raw)
        self.assertIn(b"411", self.status_line(data))
        body = json.dumps(self.chat_body()).encode()
        raw = (f"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\n"
               f"Authorization: Bearer {TOKEN}\r\n"
               f"Content-Length: {len(body)}\r\nContent-Length: 999\r\n\r\n").encode() + body
        data, _ = self.raw_exchange(raw)
        self.assertIn(b"400", self.status_line(data))
        self.assertEqual(len(STUB_REQUESTS), 0)

    def test_smuggling_probe_single_response_and_connection_closed(self):
        body = json.dumps(self.chat_body(content=" smuggled probe")).encode()
        head = (f"POST /v1/chat/completions HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.server.server_port}\r\n"
                f"Authorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n\r\n").encode()
        probe = head + body + b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n"
        data, eof = self.raw_exchange(probe)
        # Exactly one response, for the first request only ...
        self.assertEqual(data.count(b"HTTP/1."), 1)
        self.assertIn(b"200", self.status_line(data))
        self.assertEqual(len(STUB_REQUESTS), 1)
        # ... and the connection is closed: the pipelined request is dead.
        self.assertTrue(eof)

    # -- upstream redirect / passthrough ------------------------------------------

    def test_upstream_302_maps_to_502_without_following_redirect(self):
        self.stub.stub_mode = "redirect"
        status, _, data = self.post_json("/v1/chat/completions", self.chat_body(),
                                         self.auth_headers)
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(data)["error"], "upstream_redirect")
        # Only the original POST hit the stub; the redirect target never saw us.
        self.assertEqual(len(STUB_REQUESTS), 1)
        self.assertEqual(STUB_REQUESTS[0]["path"], "/chat/completions")

    def test_anthropic_messages_passthrough_roundtrip(self):
        payload = {"model": "glm-5.3-flash", "max_tokens": 16,
                   "messages": [{"role": "user", "content": "hello"}]}
        status, _, data = self.post_json("/v1/messages", payload, self.auth_headers)
        self.assertEqual(status, 200)
        body = json.loads(data)
        self.assertTrue(body["stub"])
        self.assertEqual(body["saw_model"], "glm-5.3-flash")
        self.assertEqual(len(STUB_REQUESTS), 1)
        seen = STUB_REQUESTS[0]
        self.assertEqual(seen["path"], "/v1/messages")
        self.assertEqual(seen["authorization"], f"Bearer {STUB_API_KEY}")
        self.assertEqual(json.loads(seen["body"]), payload)

    # -- routing / methods -----------------------------------------------------------

    def test_post_health_405_locally(self):
        status, headers, data = self.post_json("/health", self.chat_body(), self.auth_headers)
        self.assertEqual(status, 405)
        self.assertEqual(json.loads(data)["error"], "method_not_allowed")
        self.assertIn("GET", dict(headers).get("Allow", ""))
        self.assertEqual(len(STUB_REQUESTS), 0)

    def test_unknown_post_path_404(self):
        status, _, _ = self.post_json("/v1/embeddings", self.chat_body(), self.auth_headers)
        self.assertEqual(status, 404)
        self.assertEqual(len(STUB_REQUESTS), 0)

    # -- log discipline -------------------------------------------------------------

    def test_log_line_schema_and_no_secret_leakage(self):
        secret_marker = "SECRET-BODY-MARKER"
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            status, _, _ = self.post_json(
                "/v1/chat/completions",
                self.chat_body(content=secret_marker), self.auth_headers)
        self.assertEqual(status, 200)
        lines = [line for line in captured.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        for key in ("event", "path", "status", "model", "request_sha256",
                    "duration_ms", "rate_limit_remaining"):
            self.assertIn(key, entry)
        self.assertEqual(entry["path"], "/v1/chat/completions")
        self.assertEqual(entry["status"], 200)
        self.assertEqual(entry["model"], "glm-5.3")
        self.assertEqual(entry["request_sha256"],
                         __import__("hashlib").sha256(
                             json.dumps(self.chat_body(content=secret_marker)).encode()
                         ).hexdigest())
        logged = captured.getvalue()
        self.assertNotIn(TOKEN, logged)
        self.assertNotIn(STUB_API_KEY, logged)
        self.assertNotIn(secret_marker, logged)


if __name__ == "__main__":
    unittest.main()
