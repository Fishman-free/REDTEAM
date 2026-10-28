"""Consent-aware transcript persistence for hosted agent sessions.

Only attacker-generated content is governed by the join-time ``dataConsent``:

* normal contest, consent ``true`` -- snapshot, messages, replies and tool
  traces are appended for the defender dataset (DataMarket 70/30);
* normal contest, consent ``false`` -- nothing is written; the turn stays in
  memory and never enters a dataset;
* mining contest -- always written, marked ``rsi_only`` and never sold.

The store writes only under ``<root>/<contest_id>/``.  Snapshot metadata is a
fixed four-field whitelist (version, digest, wallet address, prompt hash) and
contains no attacker content.  Writes are process-serialized and fail loudly
with :class:`TranscriptError`; nothing is silently downgraded.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from ._jsonl import append_jsonl, write_text_atomic

PURPOSE_DATASET = "defender_dataset"
PURPOSE_RSI = "rsi"

_SNAPSHOT_FIELDS = frozenset(
    {"version", "digest", "wallet_address", "system_prompt_sha256"}
)
_CONTEST_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

# One store per contest in v1, but a process-wide lock also keeps concurrent
# stores from interleaving snapshot writes or JSONL appends.
_LOCK = threading.RLock()


class TranscriptError(RuntimeError):
    """Raised when a transcript cannot be validated or written."""


def _require_visible_text(value: Any, field: str, *, maximum: int = 64) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    if any(not 0x20 <= ord(character) <= 0x7E for character in value):
        raise ValueError(f"{field} must contain only visible ASCII characters")
    return value


def _require_attacker(value: Any) -> str:
    if not isinstance(value, str) or not _ADDRESS_RE.fullmatch(value):
        raise ValueError("attacker must be a 0x-prefixed 20-byte hex address")
    return value


def _require_hex64(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HEX64_RE.fullmatch(value):
        raise ValueError(f"{field} must be 64 lowercase hex characters")
    return value


def _validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(snapshot, Mapping) or set(snapshot) != _SNAPSHOT_FIELDS:
        raise ValueError(
            "snapshot must contain exactly version, digest, wallet_address "
            "and system_prompt_sha256"
        )
    version = _require_visible_text(snapshot["version"], "snapshot.version")
    wallet = snapshot["wallet_address"]
    if not isinstance(wallet, str) or not _ADDRESS_RE.fullmatch(wallet):
        raise ValueError("snapshot.wallet_address must be a 0x-prefixed 20-byte hex address")
    return {
        "version": version,
        "digest": _require_hex64(snapshot["digest"], "snapshot.digest"),
        "wallet_address": wallet,
        "system_prompt_sha256": _require_hex64(
            snapshot["system_prompt_sha256"], "snapshot.system_prompt_sha256"
        ),
    }


class TranscriptStore:
    """Append-only, consent-aware JSONL store for one contest.

    Constructing the store performs no file I/O, so an opted-out attacker never
    causes a directory to appear.  Mining sessions call :meth:`record_snapshot`
    immediately; normal sessions write the snapshot lazily on the first turn
    whose attacker consented.
    """

    def __init__(
        self,
        root: str | Path,
        contest_id: str,
        *,
        is_mining: bool,
        snapshot: Mapping[str, Any],
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(is_mining, bool):
            raise ValueError("is_mining must be a boolean")
        if not isinstance(contest_id, str) or not _CONTEST_RE.fullmatch(contest_id):
            raise ValueError("contest_id must be 1-128 characters of [A-Za-z0-9_.:-]")
        self.root = Path(root).expanduser()
        self.contest_id = contest_id
        self.is_mining = is_mining
        self.purpose = PURPOSE_RSI if is_mining else PURPOSE_DATASET
        self._snapshot = _validate_snapshot(snapshot)
        self._clock = clock
        self._snapshot_written = False

    # -- paths ----------------------------------------------------------

    @property
    def contest_directory(self) -> Path:
        return self.root / self.contest_id

    @property
    def snapshot_path(self) -> Path:
        return self.contest_directory / "session.json"

    def _turn_path(self, attacker: str) -> Path:
        return self.contest_directory / f"{attacker.lower()}.jsonl"

    # -- snapshot -------------------------------------------------------

    def record_snapshot(self) -> None:
        """Write the session metadata once; idempotent and content-free."""

        with _LOCK:
            self._write_snapshot_locked()

    def _write_snapshot_locked(self) -> None:
        if self._snapshot_written:
            return
        payload = {
            "ts": self._clock(),
            "kind": "snapshot",
            "contest": self.contest_id,
            "is_mining": self.is_mining,
            "purpose": self.purpose,
            "rsi_only": self.is_mining,
            **self._snapshot,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            write_text_atomic(self.snapshot_path, text)
        except OSError as exc:
            raise TranscriptError(
                f"cannot write transcript snapshot for {self.contest_id}: {exc}"
            ) from exc
        self._snapshot_written = True

    # -- turns ----------------------------------------------------------

    def record_turn(
        self,
        attacker: str,
        consent: bool,
        *,
        turn: int,
        messages: list,
        reply: str,
        tool_calls: list,
        error: dict | None,
    ) -> bool:
        """Persist one attacker turn when allowed.

        Returns ``True`` when the turn was written and ``False`` when the
        attacker opted out.  An opted-out turn performs no file I/O at all.
        """

        attacker = _require_attacker(attacker)
        if not isinstance(consent, bool):
            raise ValueError("consent must be a boolean")
        if self.is_mining and consent is not True:
            raise ValueError("mining transcripts require data consent")
        if isinstance(turn, bool) or not isinstance(turn, int) or turn < 1:
            raise ValueError("turn must be a positive integer")
        if not isinstance(messages, list) or not isinstance(tool_calls, list):
            raise ValueError("messages and tool_calls must be lists")
        if not isinstance(reply, str):
            raise ValueError("reply must be a string")
        if error is not None and not isinstance(error, dict):
            raise ValueError("error must be a mapping or None")

        if not consent:
            return False

        record = {
            "ts": self._clock(),
            "kind": "turn",
            "contest": self.contest_id,
            "attacker": attacker,
            "turn": turn,
            "consent": True,
            "purpose": self.purpose,
            "rsi_only": self.is_mining,
            "messages": messages,
            "reply": reply,
            "tool_calls": tool_calls,
            "error": error,
        }
        try:
            line = (
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        except (TypeError, ValueError):
            raise TranscriptError("transcript turn is not JSON serializable") from None

        with _LOCK:
            self._write_snapshot_locked()
            try:
                append_jsonl(self._turn_path(attacker), line)
            except OSError as exc:
                raise TranscriptError(
                    f"cannot write transcript for {attacker}: {exc}"
                ) from exc
        return True
