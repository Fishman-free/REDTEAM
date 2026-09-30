from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import time
import threading
from typing import Any, Protocol
from urllib import error, parse, request
from uuid import uuid4

_LOG_LOCK = threading.Lock()


class ChatModel(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class ModelCallError(RuntimeError):
    """Sanitized provider or output error; never contains credentials."""


class BudgetExceeded(ModelCallError):
    pass


@dataclass
class CallBudget:
    max_calls: int = 120
    max_tokens: int = 200_000
    calls: int = 0
    accounted_tokens: int = 0
    reported_tokens: int = 0
    _lock: Any = field(default_factory=threading.Lock, repr=False)

    def reserve(self, input_bound: int, max_output: int) -> int:
        with self._lock:
            reservation = input_bound + max_output
            if self.calls >= self.max_calls:
                raise BudgetExceeded("model call limit reached")
            if self.accounted_tokens + reservation > self.max_tokens:
                raise BudgetExceeded("token reservation limit reached")
            self.calls += 1
            self.accounted_tokens += reservation
            return reservation

    def settle(self, reservation: int, usage: dict) -> None:
        with self._lock:
            total = usage.get("total_tokens")
            if type(total) is int and total >= 0:
                self.accounted_tokens += total - reservation
                self.reported_tokens += total

    def refund(self, reservation: int) -> None:
        """Release a reservation for an attempt that never produced output."""
        with self._lock:
            self.accounted_tokens = max(0, self.accounted_tokens - reservation)
            self.calls = max(0, self.calls - 1)

    def snapshot(self) -> dict:
        return {
            "max_calls": self.max_calls, "max_tokens": self.max_tokens,
            "calls": self.calls, "accounted_tokens": self.accounted_tokens,
            "reported_tokens": self.reported_tokens,
        }


@dataclass
class OfflineChatModel:
    response: str = '{"status":"offline","message":"deterministic fallback"}'

    def complete(self, system: str, user: str) -> str:
        del system, user
        return self.response


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an Authorization header to a redirect destination.
        return None


@dataclass
class OpenAICompatibleChatModel:
    model: str
    api_key: str | None = field(default=None, repr=False)
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 45
    max_output_tokens: int = 1024
    temperature: float = 0
    max_retries: int = 2
    disable_thinking: bool = False
    role: str = "model"
    budget: CallBudget | None = None
    audit_log: Path | None = None
    cache_dir: Path | None = None
    use_cache: bool = False
    _thread_state: Any = field(default_factory=threading.local, init=False, repr=False)

    @property
    def last_metadata(self) -> dict:
        return getattr(self._thread_state, "metadata", {})

    @last_metadata.setter
    def last_metadata(self, value: dict) -> None:
        self._thread_state.metadata = value

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, str):
            key = self.api_key or os.getenv("GLM_API_KEY") or os.getenv("OPENAI_API_KEY")
            return value.replace(key, "[REDACTED]") if key else value
        if isinstance(value, dict):
            return {key: self._sanitize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        return value

    def _log(self, data: dict) -> None:
        if self.audit_log is not None:
            self.audit_log.parent.mkdir(parents=True, exist_ok=True)
            with _LOG_LOCK:
                with self.audit_log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(self._sanitize(data), ensure_ascii=False, sort_keys=True) + "\n")

    def complete(self, system: str, user: str) -> str:
        key = self.api_key or os.getenv("GLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ModelCallError("model API key is not configured")
        url = parse.urlparse(self.base_url)
        if url.scheme != "https" or not url.netloc or url.username or url.password or url.query:
            raise ModelCallError("model base URL must be an HTTPS endpoint without embedded credentials")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
            "stream": False,
        }
        if self.disable_thinking:
            body["thinking"] = {"type": "disabled"}
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        cache_key = hashlib.sha256(self.base_url.encode() + b"\n" + payload).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json" if self.cache_dir is not None else None
        if self.use_cache and cache_path is not None and cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_usage = (cached.get("response") or {}).get("usage", {})
            self.last_metadata = {
                "call_id": uuid4().hex, "source_call_id": cached["call_id"],
                "role": self.role, "status": "cache_hit", "cache_key": cache_key,
                "requested_model": self.model, "request": body,
                "response": cached["response"], "timestamp": time.time(),
                # No provider spend; the original usage is surfaced for audit.
                "billable_usage": None, "cached_usage": cached_usage or None,
            }
            self._log(self.last_metadata)
            return cached["response"]["choices"][0]["message"]["content"]
        # UTF-8 bytes plus overhead is deliberately conservative without a vendor tokenizer.
        input_bound = len(system.encode("utf-8")) + len(user.encode("utf-8")) + 256
        call_id = uuid4().hex
        opener = request.build_opener(_NoRedirect())
        for attempt in range(self.max_retries + 1):
            reservation = self.budget.reserve(input_bound, self.max_output_tokens) if self.budget else 0
            started = time.monotonic()
            entry = {
                "call_id": call_id, "attempt": attempt + 1, "role": self.role,
                "requested_model": self.model, "base_url": self.base_url,
                "request_hash": hashlib.sha256(payload).hexdigest(),
                "max_output_tokens": self.max_output_tokens,
                "request": body, "cache_key": cache_key, "timestamp": time.time(),
            }
            try:
                http_request = request.Request(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    data=payload,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "rsi4safety/0.2"},
                    method="POST",
                )
                with opener.open(http_request, timeout=self.timeout_seconds) as response:
                    data = json.loads(response.read().decode("utf-8"))
                usage = data.get("usage", {})
                if self.budget:
                    self.budget.settle(reservation, usage)
                choice = data["choices"][0]
                content = choice["message"].get("content")
                finish_reason = choice.get("finish_reason")
                entry.update(
                    usage=usage, returned_model=data.get("model"), finish_reason=finish_reason,
                    response_hash=hashlib.sha256(str(content).encode()).hexdigest(),
                    response=data,
                )
                if not isinstance(content, str) or not content.strip() or finish_reason == "length":
                    raise ModelCallError("model returned empty or truncated content")
                entry["status"] = "ok"
                self.last_metadata = dict(entry)
                if self.use_cache and cache_path is not None:
                    # Only cache-eligible writers populate the store; a
                    # cache-disabled reader (independent evaluation) must not
                    # leave entries that flip it back into reuse later.
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = cache_path.with_suffix(f".{call_id}.tmp")
                    temporary.write_text(
                        json.dumps(self._sanitize({"call_id": call_id, "response": data}), ensure_ascii=False),
                        encoding="utf-8",
                    )
                    temporary.replace(cache_path)
                return content
            except error.HTTPError as exc:
                # Raw provider error bodies are intentionally excluded from logs.
                entry.update(status="http_error", http_status=exc.code)
                retryable = exc.code in {429, 500, 502, 503, 504}
                if not retryable or attempt == self.max_retries:
                    if self.budget and retryable:
                        # Exhausted retries on a provider-side failure never
                        # produced a completion; refund the dead reservations.
                        self.budget.refund(reservation)
                    raise ModelCallError(f"model endpoint returned HTTP {exc.code}") from None
            except (error.URLError, TimeoutError, ConnectionError):
                entry["status"] = "transport_error"
                if self.budget:
                    self.budget.refund(reservation)  # the request never reached the provider
                if attempt == self.max_retries:
                    raise ModelCallError("model transport failed after bounded retries") from None
            except (ValueError, KeyError, IndexError, TypeError, ModelCallError) as exc:
                entry.update(status="invalid_response", error_type=type(exc).__name__)
                raise ModelCallError("model returned malformed, empty or truncated content") from None
            finally:
                entry["duration_seconds"] = round(time.monotonic() - started, 3)
                self._log(entry)
            time.sleep(min(2 ** attempt, 4))
        raise ModelCallError("model call failed")


def complete_json(model: ChatModel, system: str, payload: dict, *, retries: int = 1) -> dict:
    """Retry JSON formatting once, without executing model-generated code."""
    user = json.dumps(payload, ensure_ascii=False)
    for attempt in range(retries + 1):
        text = model.complete(system, user)
        stripped = text.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(stripped)
            if not isinstance(parsed, dict):
                raise ValueError("expected an object")
            return parsed
        except (ValueError, IndexError):
            if attempt == retries:
                raise ModelCallError("model did not return a JSON object") from None
            user = json.dumps(payload, ensure_ascii=False) + "\nPrevious response had invalid JSON. Return one JSON object only."
    raise ModelCallError("JSON decoding failed")
