"""Durable bounded provider accounting and campaign resource configuration."""
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from rsi4safety.providers import BudgetExceeded, CallBudget
from .model_client import ModelError
from .campaign_io import write_json

@dataclass(frozen=True)
class CampaignConfig:
    rounds: int = 3
    attacks_per_round: int = 4
    repetitions: int = 1
    max_candidates: int = 2
    seed: int = 17
    max_sut_calls: int = 600
    max_role_calls: int = 80
    max_role_tokens: int = 2_500_000
    level: str = "all"
    concurrency: int = 1
    confirmation_repetitions: int = 3
    max_sut_tokens: int = 2_000_000
    max_duration_seconds: int = 1800

    def __post_init__(self):
        limits = {"rounds": 10, "attacks_per_round": 24, "repetitions": 10,
                  "max_candidates": 4, "max_sut_calls": 20000, "max_role_calls": 500,
                  "max_role_tokens": 20_000_000, "concurrency": 8,
                  "confirmation_repetitions": 10, "max_sut_tokens": 200_000_000,
                  "max_duration_seconds": 86400}
        for name, upper in limits.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f"{name} must be between 1 and {upper}")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        if self.level not in {"all", "L0", "L1"}:
            raise ValueError("level filter must be all, L0 or L1")


class DurableRoleBudget(CallBudget):
    def __init__(self, path: Path, config: CampaignConfig):
        super().__init__(max_calls=config.max_role_calls, max_tokens=config.max_role_tokens)
        self.path = path
        if path.exists():
            value = json.loads(path.read_text())
            self.calls, self.accounted_tokens, self.reported_tokens = (
                value[key] for key in ("calls", "accounted_tokens", "reported_tokens"))
            if any(type(v) is not int or v < 0 for v in (self.calls, self.accounted_tokens, self.reported_tokens)):
                raise ValueError("invalid persisted role usage")

    def reserve(self, input_bound, max_output):
        result = super().reserve(input_bound, max_output)
        write_json(self.path, self.snapshot())
        return result

    def settle(self, reservation, usage):
        super().settle(reservation, usage)
        write_json(self.path, self.snapshot())

    def refund(self, reservation):
        super().refund(reservation)
        write_json(self.path, self.snapshot())


class BudgetedSUT:
    def __init__(self, client, path: Path, limit: int, *, token_limit=None, duration_limit=None,
                 max_output_tokens=1200):
        self.client, self.path, self.limit = client, path, limit
        self.token_limit, self.duration_limit = token_limit, duration_limit
        self.max_output_tokens = max_output_tokens
        if getattr(client, "use_cache", False) is True:
            raise ValueError("cached SUT completions cannot serve as independent confirmation")
        self.usage = json.loads(path.read_text()) if path.exists() else {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        if any(type(self.usage.get(k)) is not int or self.usage[k] < 0
               for k in ("calls", "prompt_tokens", "completion_tokens")):
            raise ValueError("invalid persisted SUT usage")
        if token_limit is not None:
            self.usage.setdefault("accounted_tokens", self.usage["prompt_tokens"] + self.usage["completion_tokens"])
        if duration_limit is not None:
            self.usage.setdefault("started_at", time.time())
        self._lock = threading.Lock()

    def check_duration(self):
        if self.duration_limit is not None and time.time() - self.usage["started_at"] >= self.duration_limit:
            raise BudgetExceeded("campaign duration budget exhausted")

    def complete(self, messages, tools, *, timeout):
        with self._lock:
            self.check_duration()
            if self.usage["calls"] >= self.limit:
                raise ModelError("campaign SUT call budget exhausted")
            reservation = len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False).encode("utf-8")) + 128 + self.max_output_tokens
            if self.token_limit is not None:
                if self.usage["accounted_tokens"] + reservation > self.token_limit:
                    raise BudgetExceeded("campaign SUT token budget exhausted before dispatch")
                self.usage["accounted_tokens"] += reservation
            self.usage["calls"] += 1
            write_json(self.path, self.usage)
        result = self.client.complete(messages, tools, timeout=timeout)
        usage = result.get("usage") or {}
        with self._lock:
            if result.get("status") == "cache_hit" or result.get("cached") is True:
                raise ModelError("cached response cannot serve as independent confirmation")
            reported = sum(usage.get(key, 0) for key in ("prompt_tokens", "completion_tokens")
                           if type(usage.get(key)) is int and usage[key] >= 0)
            if self.token_limit is not None and reported:
                self.usage["accounted_tokens"] += reported - reservation
            for key in ("prompt_tokens", "completion_tokens"):
                if type(usage.get(key)) is int and usage[key] >= 0:
                    self.usage[key] += usage[key]
            write_json(self.path, self.usage)
        return result
