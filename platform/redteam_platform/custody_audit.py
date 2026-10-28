"""Thin, fail-closed audit wrapper around :class:`~redteam_platform.custody.Custody`.

The vault itself does not record access.  Runner and API code must route every
``load``/``store``/``delete`` through :class:`AuditedCustody`, which appends a
structured JSONL record::

    {"ts": <float>, "action": "load", "entry_id": "...", "result": "ok",
     "context": {"purpose": "runner", ...}}

Only metadata is recorded.  Context keys are fixed and values must be bounded
visible ASCII, so attacker messages, tool traces or secrets cannot end up in
the audit log by accident.  A successful operation whose audit append fails
raises :class:`CustodyAuditError` instead of returning the secret: a missing
audit trail is treated as a failure.  Error text never contains a secret.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from ._jsonl import append_jsonl
from .custody import Custody

CONTEXT_FIELDS = frozenset(
    {
        "purpose",
        "contest_id",
        "runner_id",
        "wallet_address",
        # Faucet ticket signing (task 14) must audit these as well.
        "recipient",
        "chain_id",
        "ticket_count",
    }
)
MAX_TEXT = 256

_ACTIONS = frozenset({"load", "store", "delete"})


class CustodyAuditError(RuntimeError):
    """Raised when custody access metadata cannot be written."""


def _require_visible_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_TEXT:
        raise ValueError(
            f"{field} must be a non-empty string of at most {MAX_TEXT} characters"
        )
    if any(not 0x20 <= ord(character) <= 0x7E for character in value):
        raise ValueError(f"{field} must contain only visible ASCII characters")
    return value


def _validate_context(context: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(context, Mapping):
        raise ValueError("context must be a mapping")
    unknown = set(context) - CONTEXT_FIELDS
    if unknown:
        raise ValueError("context contains unsupported fields")
    if "purpose" not in context:
        raise ValueError("context requires a purpose")
    return {
        key: _require_visible_text(value, f"context.{key}")
        for key, value in context.items()
    }


class AuditedCustody:
    """Route vault access through a metadata-only JSONL audit log.

    ``custody`` may be any object exposing ``load``/``store``/``delete``;
    :class:`~redteam_platform.custody.Custody` is the expected implementation.
    ``clock`` is injectable so tests can pin timestamps.
    """

    def __init__(
        self,
        custody: Custody,
        log_path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._custody = custody
        self.log_path = Path(log_path).expanduser()
        self._clock = clock
        self._lock = threading.RLock()

    def load(self, entry_id: str, *, context: Mapping[str, Any]) -> str:
        return self._run("load", entry_id, context, lambda: self._custody.load(entry_id))

    def store(
        self, entry_id: str, secret: str, *, context: Mapping[str, Any]
    ) -> None:
        self._run("store", entry_id, context, lambda: self._custody.store(entry_id, secret))

    def delete(self, entry_id: str, *, context: Mapping[str, Any]) -> None:
        self._run("delete", entry_id, context, lambda: self._custody.delete(entry_id))

    # -- internals ------------------------------------------------------

    def _run(
        self,
        action: str,
        entry_id: str,
        context: Mapping[str, Any],
        operation: Callable[[], Any],
    ) -> Any:
        if action not in _ACTIONS:
            raise ValueError("unsupported custody action")
        entry_id = _require_visible_text(entry_id, "entry_id")
        valid_context = _validate_context(context)

        try:
            value = operation()
        except Exception as exc:
            try:
                self._write(action, entry_id, "error", valid_context)
            except CustodyAuditError as audit_exc:
                raise audit_exc from exc
            raise

        self._write(action, entry_id, "ok", valid_context)
        return value

    def _write(
        self,
        action: str,
        entry_id: str,
        result: str,
        context: Mapping[str, str],
    ) -> None:
        record = {
            "ts": self._clock(),
            "action": action,
            "entry_id": entry_id,
            "result": result,
            "context": dict(context),
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        try:
            with self._lock:
                append_jsonl(self.log_path, line)
        except OSError as exc:
            raise CustodyAuditError(
                f"cannot write custody audit log {self.log_path}: {exc}"
            ) from exc
