"""Public attack interface — minimal session/quota prototype (frozen v1).

Implements the minimal prototype row of docs/references/ATTACK_INTERFACE_DESIGN.md
§6: an attacker-facing HTTP surface that wraps the Arena's trusted execution.
Design (§2.1):

- ``POST /v1/sessions``  — one bounded session per call: a frozen task fixture,
  an action quota and a TTL. Concurrent sessions per token are capped.
- ``POST /v1/sessions/{sid}/surfaces/{name}`` — deliver attacker content to an
  external surface (merchant_message / product_page / webhook / invoice).
- ``POST /v1/sessions/{sid}/run`` — consumes one action, executes the frozen
  target through the platform driver and returns the *bounded* attacker view.
- ``GET  /v1/sessions/{sid}/trace`` — the attacker's own run history, bounded
  by the limited-feedback protocol (no ledger rows, no HTTP trace).

Red lines (§1.3): the interface only feeds information. There is no route that
writes adjudication, rewards or trusted authorization, and every attacker
response is re-checked against ``feedback_policy.assert_feedback_bounded``.
Every submission is stored replayable on the platform side.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from uuid import uuid4

from ...benchmark import task_variant
from ..config import ArenaConfig
from ..control import tree_hash
from ..constitution import evaluate as evaluate_verdict, evaluate_authorization_dict
from ..feedback_policy import assert_feedback_bounded
from ..sut_driver import InProcessSutDriver

SURFACE_PATHS = {
    "merchant_message": "/external/merchant_message",
    "product_page": "/external/product_page",
    "webhook": "/external/webhook",
    "invoice": "/external/invoice",
}
DEFAULT_MAX_ACTIONS = 50
DEFAULT_TTL_SECONDS = 3600
DEFAULT_MAX_SESSIONS_PER_TOKEN = 4
MAX_SURFACE_CONTENT_CHARS = 20_000


class InterfaceError(Exception):
    """Protocol-level failure mapped to an HTTP status by the handler."""


class QuotaError(InterfaceError):
    pass


@dataclass(frozen=True)
class InterfaceConfig:
    """Service settings; the frozen target is materialized at startup."""

    host: str = "127.0.0.1"
    port: int = 0                      # 0 = pick a free port
    token: str = ""                    # required bearer token
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[4])
    state_dir: Path | None = None      # defaults to .arena-interface under repo root
    sut_app: str = "paygate"           # frozen target application
    task_seed: int = 4242              # fixture seed; tasks differ per session index
    max_actions: int = DEFAULT_MAX_ACTIONS
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    max_sessions_per_token: int = DEFAULT_MAX_SESSIONS_PER_TOKEN

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("an interface token is required (never run open)")
        if self.max_actions < 1 or self.ttl_seconds < 1 or self.max_sessions_per_token < 1:
            raise ValueError("max_actions, ttl_seconds and max_sessions_per_token must be positive")

    @property
    def resolved_state_dir(self) -> Path:
        return (self.state_dir if self.state_dir is not None
                else self.repo_root / ".arena-interface").resolve()


@dataclass
class Session:
    session_id: str
    token_fingerprint: str
    fixture_brief: dict
    target_version_digest: str
    max_actions: int
    expires_at: float
    actions: list = field(default_factory=list)
    runs: list = field(default_factory=list)
    runs_used: int = 0

    def expired(self) -> bool:
        return time.time() > self.expires_at

    def bounded_view(self) -> dict:
        """Attacker-visible projection; re-checked against the feedback policy."""
        return {
            "session_id": self.session_id,
            "task": self.fixture_brief,
            "attack_budget": {"max_actions": self.max_actions, "used": self.runs_used},
            "target_version": {"digest": self.target_version_digest},
            "expires_at": self.expires_at,
        }


class InterfaceService:
    """Session bookkeeping and trusted execution for the public interface."""

    def __init__(self, config: InterfaceConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        self._token_counts: dict[str, int] = {}
        self._session_counter = 0
        self.state_dir = config.resolved_state_dir
        self._arena_config = ArenaConfig(
            campaign_id="interface", state_dir=self.state_dir / "arena",
            rounds=1, repetitions=1, dry_run=True, repo_root=config.repo_root,
            sut_app=config.sut_app,
        )
        self.target_version_digest = self._materialize_target()

    def _materialize_target(self) -> str:
        """Freeze the target: copy the SUT app once and pin its tree digest."""
        source = self.config.repo_root / "payment_agents" / self.config.sut_app
        if not (source / "app" / "main.py").exists():
            raise FileNotFoundError(f"SUT source missing at {source}")
        target = self._arena_config.sut_dir
        if not (target / "app" / "main.py").exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target,
                            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        return tree_hash(target)

    def create_session(self, token_fingerprint: str) -> dict:
        with self._lock:
            self._evict_expired()
            if self._token_counts.get(token_fingerprint, 0) >= self.config.max_sessions_per_token:
                raise QuotaError("session limit reached for this token")
            self._session_counter += 1
            spec = task_variant(self.config.task_seed, self._session_counter, split="interface")
            fixture_brief = {"task_id": spec.task_id, "user_request": spec.user_request,
                             "authorization": asdict(spec.authorization)}
            session = Session(session_id="sess-" + uuid4().hex[:12],
                              token_fingerprint=token_fingerprint,
                              fixture_brief=fixture_brief,
                              target_version_digest=self.target_version_digest,
                              max_actions=self.config.max_actions,
                              expires_at=time.time() + self.config.ttl_seconds)
            self._sessions[session.session_id] = session
            self._token_counts[token_fingerprint] = self._token_counts.get(token_fingerprint, 0) + 1
            return session.bounded_view() | {"quota_remaining": self.config.max_actions}

    def deliver_surface(self, session_id: str, surface: str, content: str) -> dict:
        if surface not in SURFACE_PATHS:
            raise ValueError(f"unknown surface {surface}")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("surface content must be a non-empty string")
        if len(content) > MAX_SURFACE_CONTENT_CHARS:
            raise ValueError("surface content exceeds the size budget")
        with self._lock:
            session = self._live_session(session_id)
            session.actions.append({"step": len(session.actions) + 1, "method": "POST",
                                    "path": SURFACE_PATHS[surface],
                                    "json": {"source": "attacker_session", "content": content}})
            return {"session_id": session_id, "surface": surface,
                    "queued_actions": len(session.actions)}

    def run(self, session_id: str, token_fingerprint: str) -> dict:
        with self._lock:
            session = self._live_session(session_id)
            if session.token_fingerprint != token_fingerprint:
                raise LookupError("no such session")
            if session.runs_used >= session.max_actions:
                raise QuotaError("action budget exhausted for this session")
            session.runs_used += 1
            fixture_brief = json.loads(json.dumps(session.fixture_brief))
            actions = json.loads(json.dumps(session.actions))
        # Execute outside the lock: driver.run spawns and stops the SUT process.
        view = self._execute_and_record(session, session_id, fixture_brief, actions)
        with self._lock:
            session.runs.append(view)
            remaining = session.max_actions - session.runs_used
        assert_feedback_bounded([view])
        return view | {"runs_remaining": remaining}

    def _execute_and_record(self, session: Session, session_id: str,
                            fixture_brief: dict, actions: list) -> dict:
        driver = InProcessSutDriver(self._arena_config, gateway="research")
        execution = driver.run(fixture_brief, actions)
        verdict = None
        if execution.ledger_ok:
            verdict = evaluate_verdict(
                evaluate_authorization_dict(fixture_brief["authorization"]),
                execution.ledger_rows)
        run_id = "run-" + uuid4().hex[:12]
        record = {"schema_version": 1, "type": "interface_submission",
                  "run_id": run_id, "session_id": session_id,
                  "target_version_digest": session.target_version_digest,
                  "fixture": fixture_brief, "actions": actions,
                  "programmatic_outcome": asdict(verdict) if verdict is not None else None,
                  "http_trace": execution.http_trace,
                  "ledger_rows": execution.ledger_rows,
                  "error": execution.error,
                  "executed_at": time.time()}
        record["record_digest"] = hashlib.sha256(json.dumps(
            record, sort_keys=True, ensure_ascii=False,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        store = self.state_dir / "submissions" / session_id
        store.mkdir(parents=True, exist_ok=True)
        (store / f"{run_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"run_id": run_id,
                "status": "completed" if execution.error is None else "error",
                "programmatic_outcome": record["programmatic_outcome"],
                "error": (execution.error or "")[:240] or None,
                "replay_digest": record["record_digest"]}

    def trace(self, session_id: str, token_fingerprint: str) -> dict:
        with self._lock:
            session = self._live_session(session_id)
            if session.token_fingerprint != token_fingerprint:
                raise LookupError("no such session")
            bounded = [dict(item) for item in session.runs]
            remaining = session.max_actions - session.runs_used
        assert_feedback_bounded(bounded)
        return {"session_id": session_id, "runs": bounded, "runs_remaining": remaining}

    def close_session(self, session_id: str, token_fingerprint: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None and session.token_fingerprint == token_fingerprint:
                self._drop(session_id, session)

    def _live_session(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None or session.expired():
            if session is not None:
                self._drop(session_id, session)
            raise LookupError("session not found or expired")
        return session

    def _evict_expired(self) -> None:
        for session_id, session in list(self._sessions.items()):
            if session.expired():
                self._drop(session_id, session)

    def _drop(self, session_id: str, session: Session) -> None:
        self._sessions.pop(session_id, None)
        count = self._token_counts.get(session.token_fingerprint, 1) - 1
        if count <= 0:
            self._token_counts.pop(session.token_fingerprint, None)
        else:
            self._token_counts[session.token_fingerprint] = count


def token_fingerprint(token: str) -> str:
    """Only the digest of a token is ever stored or logged."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
