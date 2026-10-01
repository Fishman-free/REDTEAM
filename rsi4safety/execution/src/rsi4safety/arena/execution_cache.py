from __future__ import annotations

import json
from pathlib import Path

from .control import PROTOCOL_VERSION, digest, runtime_fingerprint, tree_hash
from .exchange import write_json_atomic


class ExecutionCacheMixin:
    """Execution-cache and budgeted-execution methods; relies on the composing
    orchestrator for ``self.config``, ``self.chain`` and ``self._execution_count``."""

    def _sut_tree_digest(self, sut_dir: Path | None = None) -> str:
        return tree_hash(sut_dir if sut_dir is not None else self.config.sut_dir)

    def _cache_dir(self) -> Path:
        path = self.config.state_dir / "cache" / "executions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _cache_key(self, *, kind: str, gateway: str, fixture: dict, actions,
                   repetitions: int, sut_dir: Path | None = None) -> str:
        return digest({"kind": kind, "sut": self._sut_tree_digest(sut_dir), "gateway": gateway,
                       "fixture": fixture, "actions": actions, "repetitions": repetitions,
                       "runtime": getattr(self, "_fingerprint", runtime_fingerprint(self.config)),
                       "mode": self.config.sut_llm_mode, "protocol": PROTOCOL_VERSION})

    def _cache_get(self, key: str) -> dict | None:
        if not self.config.use_execution_cache or self.config.sut_llm_mode != "deterministic":
            return None
        path = self._cache_dir() / f"{key}.json"
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text())
            if entry["key"] != key or entry["digest"] != digest(entry["payload"]):
                return None
        except (ValueError, KeyError, TypeError):
            return None
        self.chain.append("orchestrator", "execution_cache_hit", key=key)
        return entry["payload"]

    def _cache_put(self, key: str, payload: dict) -> None:
        if (not self.config.use_execution_cache or self.config.sut_llm_mode != "deterministic"
                or payload.get("error") or payload.get("verdict") is None):
            return
        write_json_atomic(self._cache_dir() / f"{key}.json",
                          {"key": key, "payload": payload, "digest": digest(payload)})
        self.chain.append("orchestrator", "execution_cache_store", key=key)

    def _execute(self, factory, fixture: dict, actions=None):
        if self._execution_count >= self.config.max_sut_executions:
            raise RuntimeError("campaign SUT execution budget exhausted")
        self._execution_count += 1
        driver = factory()
        return driver.run_clean(fixture) if actions is None else driver.run(fixture, actions)
