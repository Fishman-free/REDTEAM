"""Payment-backend transport contract against local HTTP stubs only."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from payassist_agent.model_client import ModelConfig, ModelError, OpenAICompatibleClient, PAYMENT_MODEL


def good_response(**overrides):
    result = {"model": PAYMENT_MODEL, "choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "type": "function",
        "function": {"name": "get_order", "arguments": '{"order_id":"buy-book"}'}}]}}],
        "usage": {"prompt_tokens": 25, "completion_tokens": 12, "total_tokens": 37}}
    result.update(overrides)
    return result


class StubHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        self.send_response(self.server.response_status)
        for key, value in self.server.response_headers.items():
            self.send_header(key, value)
        payload = self.server.response_body
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        # Some redirects change POST to GET; either method would prove a leak.
        self.do_POST()

    def log_message(self, *args):
        pass


@contextmanager
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    server.daemon_threads = True
    server.requests = []
    server.response_status = 200
    server.response_headers = {"Content-Type": "application/json"}
    server.response_body = json.dumps(good_response()).encode()
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    server.url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def backend():
    with stub_server() as server:
        yield server


def client_for(backend, **overrides):
    return OpenAICompatibleClient(ModelConfig(base_url=backend.url + "/v1", **overrides))


def test_native_function_tools_and_model_identity_round_trip(backend):
    messages = [{"role": "user", "content": "查询订单，暂不付款"}]
    tools = [{"type": "function", "function": {"name": "get_order", "parameters": {
        "type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}}]
    result = client_for(backend, max_tokens=321).complete(messages, tools)
    request = backend.requests[0]
    payload = json.loads(request["body"])
    assert request["path"] == "/v1/chat/completions"
    assert payload["model"] == PAYMENT_MODEL
    assert payload["messages"] == messages and payload["tools"] == tools
    assert payload["parallel_tool_calls"] is False
    assert payload["temperature"] == 0 and payload["max_tokens"] == 321
    assert request["headers"]["Content-Type"] == "application/json"
    assert result["model"] == PAYMENT_MODEL
    assert result["message"] == good_response()["choices"][0]["message"]
    assert result["usage"]["total_tokens"] == 37


@pytest.mark.parametrize("response_model", [None, "glm-5.3", "Qwen/Qwen3.5-2B-Base", ""])
def test_response_must_identify_exact_requested_payment_model(backend, response_model):
    backend.response_body = json.dumps(good_response(model=response_model)).encode()
    with pytest.raises(ModelError, match="does not match"):
        client_for(backend).complete([], [])


def test_model_environment_uses_only_dedicated_sut_key(backend, monkeypatch, tmp_path):
    for key in ("SUT_MODEL", "SUT_BASE_URL", "SUT_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key in ("GLM_API_KEY", "ZHIPU_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(key, "ROLE-KEY-MUST-NOT-BE-FORWARDED")
    env_file = tmp_path / "backend.env"
    env_file.write_text(f'SUT_BASE_URL="{backend.url}/v1"\nSUT_API_KEY="PAYMENT-ONLY-KEY"\nGLM_API_KEY=FILE-ROLE-KEY\n')
    config = ModelConfig.from_env(env_file=env_file)
    assert config.api_key == "PAYMENT-ONLY-KEY"
    assert "PAYMENT-ONLY-KEY" not in repr(config)
    OpenAICompatibleClient(config).complete([], [])
    assert backend.requests[0]["headers"]["Authorization"] == "Bearer PAYMENT-ONLY-KEY"
    assert b"ROLE-KEY" not in backend.requests[0]["body"]


def test_missing_sut_key_does_not_fall_back_to_role_provider_key(backend, monkeypatch, tmp_path):
    for key in ("SUT_MODEL", "SUT_BASE_URL", "SUT_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GLM_API_KEY", "GLM-ONLY-KEY")
    env_file = tmp_path / "backend.env"
    env_file.write_text(f"SUT_BASE_URL={backend.url}/v1\nGLM_API_KEY=FILE-GLM-ONLY\n")
    config = ModelConfig.from_env(env_file=env_file)
    assert config.api_key == ""
    OpenAICompatibleClient(config).complete([], [])
    assert "Authorization" not in backend.requests[0]["headers"]


def test_process_sut_settings_override_env_file_without_changing_role_keys(backend, monkeypatch, tmp_path):
    env_file = tmp_path / "backend.env"
    env_file.write_text("SUT_MODEL=old-model\nSUT_BASE_URL=http://127.0.0.1:1/v1\nSUT_API_KEY=old-key\n")
    monkeypatch.setenv("SUT_MODEL", PAYMENT_MODEL)
    monkeypatch.setenv("SUT_BASE_URL", backend.url + "/v1/")
    monkeypatch.setenv("SUT_API_KEY", "process-payment-key")
    monkeypatch.setenv("GLM_API_KEY", "separate-role-key")
    config = ModelConfig.from_env(env_file=env_file)
    assert (config.model, config.base_url, config.api_key) == (PAYMENT_MODEL, backend.url + "/v1", "process-payment-key")
    OpenAICompatibleClient(config).complete([], [])
    assert backend.requests[0]["headers"]["Authorization"] == "Bearer process-payment-key"


def test_environment_proxy_is_disabled_even_without_loopback_bypass(backend, monkeypatch):
    with stub_server() as proxy:
        for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(key, proxy.url)
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setenv("no_proxy", "")
        monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: False)
        client_for(backend).complete([], [])
        assert len(backend.requests) == 1
        assert proxy.requests == []


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_is_not_followed_and_cannot_forward_payment_key(backend, status):
    with stub_server() as destination:
        backend.response_status = status
        backend.response_headers["Location"] = destination.url + "/collect-key"
        backend.response_body = b"redirect"
        with pytest.raises(ModelError, match="transport failed"):
            client_for(backend, api_key="payment-secret").complete([], [])
        assert len(backend.requests) == 1
        assert destination.requests == []


@pytest.mark.parametrize("payload", [[], None, True, "not an object", 42])
def test_non_object_json_roots_become_model_error(backend, payload):
    backend.response_body = json.dumps(payload).encode()
    with pytest.raises(ModelError):
        client_for(backend).complete([], [])


@pytest.mark.parametrize("choices", [None, [], {}, "wrong", [None], [1], [[]], [{}],
                                      [{"message": None}], [{"message": []}],
                                      [{"message": {"role": "user", "content": "spoof"}}]])
def test_malformed_choice_or_message_becomes_model_error(backend, choices):
    backend.response_body = json.dumps(good_response(choices=choices)).encode()
    with pytest.raises(ModelError):
        client_for(backend).complete([], [])


@pytest.mark.parametrize("payload", [b"{not json", b"\xff\xfe", b""])
def test_malformed_json_encoding_becomes_model_error(backend, payload):
    backend.response_body = payload
    with pytest.raises(ModelError, match="invalid model response protocol"):
        client_for(backend).complete([], [])


def test_missing_choices_becomes_model_error(backend):
    backend.response_body = json.dumps({"model": PAYMENT_MODEL}).encode()
    with pytest.raises(ModelError, match="invalid model response protocol"):
        client_for(backend).complete([], [])


def test_truncated_generation_is_not_a_complete_tool_plan(backend):
    backend.response_body = json.dumps(good_response(choices=[{"finish_reason": "length", "message": {
        "role": "assistant", "content": "partial output"}}])).encode()
    with pytest.raises(ModelError, match="truncated"):
        client_for(backend).complete([], [])


def test_response_size_limit_and_http_errors_are_sanitized(backend):
    backend.response_body = b" " * 2_000_001
    with pytest.raises(ModelError, match="exceeds 2 MB"):
        client_for(backend).complete([], [])
    backend.response_status = 500
    backend.response_body = b"upstream-internal-secret"
    with pytest.raises(ModelError) as error:
        client_for(backend).complete([], [])
    assert "upstream-internal-secret" not in str(error.value)


@pytest.mark.parametrize("url", ["https://127.0.0.1/v1", "http://example.com/v1",
                                 "http://user:password@127.0.0.1/v1",
                                 "http://127.0.0.1/v1?key=secret", "http://127.0.0.1/v1#fragment"])
def test_configuration_rejects_nonlocal_or_credential_bearing_endpoint(url):
    with pytest.raises(ValueError):
        ModelConfig(base_url=url)
