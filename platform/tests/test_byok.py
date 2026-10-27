"""Offline tests for the BYOK allowlisted model client.

Every test blocks ``urllib.request.urlopen`` by default and installs a fake
only where a request is expected, so the suite never opens a socket.
"""

import json
import urllib.error
import urllib.request

import pytest

from redteam_platform import byok
from redteam_platform.byok import (
    AllowlistError,
    ByokClient,
    ModelError,
    ModelUnavailable,
    load_allowlist,
)

SECRET = "sk-test-secret-123"
BASE_URL = "https://glm.example/v1"
MODEL = "glm-5.3-test"
ALLOW = {"glm": {"base_url": BASE_URL, "model": MODEL}}
MESSAGES = [{"role": "user", "content": "hello"}]
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_balance",
            "description": "query balance",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
]
MAX_RESPONSE_BYTES = 2_000_000


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted in unit test")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def read(self, size=-1):
        if size is None or size < 0:
            return self.payload
        return self.payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True
        return False


class Recorder:
    """Fake urlopen that records requests and returns/raises a canned result."""

    def __init__(self, *, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        body = self.payload
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        return FakeResponse(body)


def install(monkeypatch, *, payload=None, error=None):
    recorder = Recorder(payload=payload, error=error)
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    return recorder


def success_payload(**overrides):
    payload = {
        "id": "chatcmpl-test",
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hello back"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }
    payload.update(overrides)
    return payload


def make_client(**kwargs):
    kwargs.setdefault("allowlist", ALLOW)
    return ByokClient("glm", SECRET, **kwargs)


def http_error(code):
    return urllib.error.HTTPError(
        BASE_URL + "/chat/completions", code, "provider error", None, None
    )


# -- allowlist loading and URL validation ---------------------------------


def test_load_allowlist_absent_or_blank_returns_empty():
    assert load_allowlist({}) == {}
    assert load_allowlist({"MODEL_ALLOWLIST_JSON": ""}) == {}
    assert load_allowlist({"MODEL_ALLOWLIST_JSON": "   "}) == {}


def test_load_allowlist_parses_and_returns_independent_copies():
    env = {"MODEL_ALLOWLIST_JSON": json.dumps(ALLOW)}

    first = load_allowlist(env)
    assert first == ALLOW

    first["glm"]["model"] = "mutated"
    first["new"] = {}
    assert load_allowlist(env) == ALLOW


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "null",
        json.dumps({"": {"base_url": BASE_URL, "model": MODEL}}),
        json.dumps({"   ": {"base_url": BASE_URL, "model": MODEL}}),
        json.dumps({"glm": []}),
        json.dumps({"glm": "nope"}),
        json.dumps({"glm": {"model": MODEL}}),
        json.dumps({"glm": {"base_url": BASE_URL}}),
        json.dumps({"glm": {"base_url": "", "model": MODEL}}),
        json.dumps({"glm": {"base_url": BASE_URL, "model": "   "}}),
        json.dumps({"glm": {"base_url": 123, "model": MODEL}}),
        json.dumps({"glm": {"base_url": BASE_URL, "model": 123}}),
    ],
)
def test_load_allowlist_rejects_malformed_entries(raw):
    with pytest.raises(AllowlistError):
        load_allowlist({"MODEL_ALLOWLIST_JSON": raw})


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://api.example.com/v1",
        "api.example.com/v1",
        "https:///v1",
        "https:api.example.com/v1",
        "http://api.example.com/v1",
        "http://localhost.evil.example/v1",
        "http://0.0.0.0:8080/v1",
        "https://user:pass@api.example.com/v1",
        "https://user@api.example.com/v1",
        "https://api.example.com/v1?key=1",
        "https://api.example.com/v1?",
        "https://api.example.com/v1#frag",
        "https://api.example.com/v1#",
        "https://api.example.com:not-a-port/v1",
        "https://api.example.com/v1 path",
    ],
)
def test_load_allowlist_rejects_unsafe_base_urls(base_url):
    env = {"MODEL_ALLOWLIST_JSON": json.dumps({"p": {"base_url": base_url, "model": "m"}})}

    with pytest.raises(AllowlistError):
        load_allowlist(env)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example.com/v1",
        "https://api.example.com",
        "https://127.0.0.1/v1",
        "http://127.0.0.1:18081/v1",
        "http://localhost:18081/v1",
        "http://[::1]:18081/v1",
    ],
)
def test_load_allowlist_accepts_https_and_loopback_http(base_url):
    env = {"MODEL_ALLOWLIST_JSON": json.dumps({"p": {"base_url": base_url, "model": "m"}})}

    assert load_allowlist(env) == {"p": {"base_url": base_url, "model": "m"}}


def test_no_module_level_allowlist_cache():
    assert not hasattr(byok, "MODEL_ALLOWLIST")


# -- construction ---------------------------------------------------------


def test_unknown_provider_is_rejected():
    with pytest.raises(AllowlistError):
        ByokClient("openai", SECRET, allowlist=ALLOW)


def test_empty_allowlist_rejects_every_provider(monkeypatch):
    monkeypatch.delenv("MODEL_ALLOWLIST_JSON", raising=False)

    with pytest.raises(AllowlistError):
        ByokClient("glm", SECRET)


def test_allowlist_is_read_at_construction_not_at_import(monkeypatch):
    monkeypatch.setenv(
        "MODEL_ALLOWLIST_JSON",
        json.dumps({"glm": {"base_url": "https://one.example/v1", "model": "one"}}),
    )
    first = ByokClient("glm", SECRET)
    assert first.base_url == "https://one.example/v1"
    assert first.model == "one"

    monkeypatch.setenv(
        "MODEL_ALLOWLIST_JSON",
        json.dumps({"glm": {"base_url": "https://two.example/v1", "model": "two"}}),
    )
    second = ByokClient("glm", SECRET)
    assert second.base_url == "https://two.example/v1"
    assert second.model == "two"

    assert first.base_url == "https://one.example/v1"
    assert first.model == "one"


def test_explicit_allowlist_is_used_without_environment(monkeypatch):
    monkeypatch.delenv("MODEL_ALLOWLIST_JSON", raising=False)

    client = ByokClient("glm", SECRET, allowlist=ALLOW)

    assert client.provider == "glm"
    assert client.base_url == BASE_URL
    assert client.model == MODEL


def test_base_url_trailing_slash_is_removed(monkeypatch):
    monkeypatch.setenv(
        "MODEL_ALLOWLIST_JSON",
        json.dumps({"glm": {"base_url": BASE_URL + "/", "model": MODEL}}),
    )

    assert ByokClient("glm", SECRET).base_url == BASE_URL


def test_constructor_does_not_accept_base_url_or_model():
    with pytest.raises(TypeError):
        ByokClient("glm", SECRET, allowlist=ALLOW, base_url="https://evil.example/v1")
    with pytest.raises(TypeError):
        ByokClient("glm", SECRET, allowlist=ALLOW, model="evil-model")


def test_constructor_rejects_invalid_allowlist_entries():
    with pytest.raises(AllowlistError):
        ByokClient("glm", SECRET, allowlist="not-a-mapping")
    with pytest.raises(AllowlistError):
        ByokClient(
            "glm",
            SECRET,
            allowlist={"glm": {"base_url": "http://evil.example/v1", "model": MODEL}},
        )
    with pytest.raises(AllowlistError):
        ByokClient("glm", SECRET, allowlist={"glm": {"base_url": BASE_URL}})


@pytest.mark.parametrize("api_key", ["", "   "])
def test_empty_api_key_is_rejected(api_key):
    with pytest.raises(ValueError, match="api_key"):
        ByokClient("glm", api_key, allowlist=ALLOW)


def test_api_key_with_control_characters_is_rejected():
    with pytest.raises(ValueError, match="api_key"):
        ByokClient("glm", "sk-test\r\nInjected: 1", allowlist=ALLOW)


def test_api_key_is_not_in_repr():
    assert SECRET not in repr(make_client())


@pytest.mark.parametrize("timeout", [0, -1, -0.5, float("nan"), float("inf"), True])
def test_constructor_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="timeout"):
        ByokClient("glm", SECRET, allowlist=ALLOW, timeout=timeout)


# -- successful request / response ---------------------------------------


def test_complete_success_sends_fixed_allowlisted_request(monkeypatch):
    recorder = install(monkeypatch, payload=success_payload())
    client = make_client(timeout=9.5)

    result = client.complete(MESSAGES, TOOLS, max_tokens=321, timeout=12.5)

    assert result == {
        "message": {"role": "assistant", "content": "hello back"},
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }
    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request.full_url == BASE_URL + "/chat/completions"
    assert request.get_method() == "POST"

    body = json.loads(request.data.decode("utf-8"))
    assert body == {
        "model": MODEL,
        "messages": MESSAGES,
        "tools": TOOLS,
        "parallel_tool_calls": False,
        "temperature": 0,
        "max_tokens": 321,
    }

    headers = {name.lower(): value for name, value in request.header_items()}
    assert headers["authorization"] == "Bearer " + SECRET
    assert headers["content-type"] == "application/json"
    assert recorder.timeouts == [12.5]

    assert SECRET not in request.full_url
    assert SECRET not in request.data.decode("utf-8")
    assert SECRET not in json.dumps(result)


def test_complete_uses_constructor_timeout_and_default_max_tokens(monkeypatch):
    recorder = install(monkeypatch, payload=success_payload())

    make_client(timeout=7.25).complete(MESSAGES, TOOLS)

    body = json.loads(recorder.requests[0].data.decode("utf-8"))
    assert body["max_tokens"] == 1200
    assert recorder.timeouts == [7.25]


def test_complete_default_timeout_is_sixty_seconds(monkeypatch):
    recorder = install(monkeypatch, payload=success_payload())

    make_client().complete(MESSAGES, TOOLS)

    assert recorder.timeouts == [60.0]


def test_complete_missing_usage_returns_empty_dict(monkeypatch):
    payload = success_payload()
    payload.pop("usage")
    install(monkeypatch, payload=payload)

    assert make_client().complete(MESSAGES, TOOLS)["usage"] == {}


def test_complete_non_object_usage_is_ignored(monkeypatch):
    install(monkeypatch, payload=success_payload(usage=["not", "an", "object"]))

    assert make_client().complete(MESSAGES, TOOLS)["usage"] == {}


# -- HTTP fault classification -------------------------------------------


@pytest.mark.parametrize("code", [401, 402, 403, 429, 500, 502, 503])
def test_http_infrastructure_errors(monkeypatch, code):
    install(monkeypatch, error=http_error(code))

    with pytest.raises(ModelUnavailable) as caught:
        make_client().complete(MESSAGES, TOOLS)

    exc = caught.value
    assert isinstance(exc, ModelError)
    assert exc.kind == "infrastructure"
    assert exc.usage == {}
    assert str(exc) == f"http {code}"
    assert SECRET not in str(exc)
    assert BASE_URL not in str(exc)


@pytest.mark.parametrize("code", [300, 400, 404, 409, 422])
def test_http_protocol_errors(monkeypatch, code):
    install(monkeypatch, error=http_error(code))

    with pytest.raises(ModelUnavailable) as caught:
        make_client().complete(MESSAGES, TOOLS)

    assert caught.value.kind == "agent_protocol"
    assert str(caught.value) == f"http {code}"
    assert SECRET not in str(caught.value)
    assert BASE_URL not in str(caught.value)


def test_complete_does_not_retry(monkeypatch):
    recorder = install(monkeypatch, error=http_error(500))

    with pytest.raises(ModelUnavailable):
        make_client().complete(MESSAGES, TOOLS)

    assert len(recorder.requests) == 1


# -- transport faults -----------------------------------------------------


@pytest.mark.parametrize(
    ("error", "label"),
    [
        (urllib.error.URLError("connection refused"), "URLError"),
        (TimeoutError("timed out"), "TimeoutError"),
        (ConnectionResetError("reset"), "ConnectionResetError"),
        (OSError("socket exploded"), "OSError"),
    ],
)
def test_transport_errors_are_infrastructure(monkeypatch, error, label):
    install(monkeypatch, error=error)

    with pytest.raises(ModelUnavailable) as caught:
        make_client().complete(MESSAGES, TOOLS)

    exc = caught.value
    assert exc.kind == "infrastructure"
    assert str(exc) == f"transport {label}"
    assert SECRET not in str(exc)
    assert BASE_URL not in str(exc)


# -- response protocol faults --------------------------------------------


def test_response_model_mismatch_is_agent_protocol(monkeypatch):
    install(monkeypatch, payload=success_payload(model="some-other-model"))

    with pytest.raises(ModelUnavailable) as caught:
        make_client().complete(MESSAGES, TOOLS)

    assert caught.value.kind == "agent_protocol"
    assert str(caught.value) == "model mismatch"
    assert SECRET not in str(caught.value)
    assert BASE_URL not in str(caught.value)


def test_response_missing_model_is_agent_protocol(monkeypatch):
    payload = success_payload()
    payload.pop("model")
    install(monkeypatch, payload=payload)

    with pytest.raises(ModelUnavailable) as caught:
        make_client().complete(MESSAGES, TOOLS)

    assert caught.value.kind == "agent_protocol"
    assert str(caught.value) == "model mismatch"


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b"[]",
        b'"text"',
        json.dumps(success_payload(choices=[])).encode("utf-8"),
        json.dumps(success_payload(choices="nope")).encode("utf-8"),
        json.dumps(success_payload(choices=["nope"])).encode("utf-8"),
        json.dumps(success_payload(choices=[{"message": "nope"}])).encode("utf-8"),
        json.dumps(success_payload(choices=[{}])).encode("utf-8"),
    ],
)
def test_malformed_response_is_agent_protocol(monkeypatch, payload):
    install(monkeypatch, payload=payload)

    with pytest.raises(ModelUnavailable) as caught:
        make_client().complete(MESSAGES, TOOLS)

    assert caught.value.kind == "agent_protocol"
    assert SECRET not in str(caught.value)
    assert BASE_URL not in str(caught.value)


def test_oversized_response_is_agent_protocol(monkeypatch):
    install(monkeypatch, payload=b"x" * (MAX_RESPONSE_BYTES + 1))

    with pytest.raises(ModelUnavailable) as caught:
        make_client().complete(MESSAGES, TOOLS)

    assert caught.value.kind == "agent_protocol"


def test_error_is_suppressed_chain_without_url(monkeypatch):
    install(monkeypatch, error=http_error(401))

    with pytest.raises(ModelUnavailable) as caught:
        make_client().complete(MESSAGES, TOOLS)

    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


# -- argument validation --------------------------------------------------


@pytest.mark.parametrize("max_tokens", [0, -1, True, 1.5, "10", None])
def test_complete_rejects_invalid_max_tokens(max_tokens):
    with pytest.raises(ValueError, match="max_tokens"):
        make_client().complete(MESSAGES, TOOLS, max_tokens=max_tokens)


@pytest.mark.parametrize("timeout", [0, -1, -0.5, float("nan"), float("inf"), True])
def test_complete_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="timeout"):
        make_client().complete(MESSAGES, TOOLS, timeout=timeout)
