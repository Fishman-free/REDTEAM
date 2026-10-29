"""SQLite persistence for the process-local platform state.

The API is deliberately single-worker (see the handoff doc): runner sessions,
defender registrations and processed payment transactions all lived only in
memory, so a restart silently dropped them.  This store makes the recoverable
parts durable:

* ``defenders``      -- BYOK registrations, including the vault entry names and
                        the pinned agent version + digest;
* ``seen_txs``       -- attack payments already turned into agent turns;
* ``sessions``       -- per-contest session metadata (version, wallet, mandate)
                        plus the runner state that can be rebuilt safely.

Only data the join-time consent allows is stored.  ``AgentSession.export_state``
drops the conversation of opted-out attackers, so their threads come back empty
while the turn counter is preserved (a restart must not reset the turn budget).

The store never stores model API keys: it keeps vault *entry names* only, and
the vault remains the single secret holder.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS defenders (
    defender TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    defense_prompt TEXT NOT NULL,
    mandate TEXT NOT NULL,
    wallet TEXT NOT NULL,
    wallet_entry TEXT NOT NULL,
    api_key_entry TEXT NOT NULL,
    version_name TEXT NOT NULL,
    version_digest TEXT NOT NULL,
    contests TEXT NOT NULL,
    registered_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_txs (
    tx_hash TEXT PRIMARY KEY,
    contest_id TEXT NOT NULL,
    seen_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    contest_id TEXT PRIMARY KEY,
    defender TEXT NOT NULL,
    version_name TEXT NOT NULL,
    version_digest TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    wallet_entry TEXT NOT NULL,
    api_key_entry TEXT NOT NULL,
    provider TEXT NOT NULL,
    mandate TEXT NOT NULL,
    is_mining INTEGER NOT NULL,
    created_at REAL NOT NULL,
    state TEXT
);
"""


class StateStoreError(RuntimeError):
    """Raised when the durable state cannot be read or written."""


class PlatformStateStore:
    """Small synchronous SQLite store; one connection guarded by a lock."""

    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._clock = clock
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(self.path), check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_SCHEMA)
            self._db.commit()
        except (OSError, sqlite3.Error) as exc:
            raise StateStoreError(f"cannot open platform state: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            try:
                self._db.close()
            except sqlite3.Error:
                pass

    # -- defenders ------------------------------------------------------

    def save_defender(self, record: dict[str, Any]) -> None:
        with self._lock:
            try:
                self._db.execute(
                    """
                    INSERT INTO defenders (
                        defender, provider, defense_prompt, mandate, wallet,
                        wallet_entry, api_key_entry, version_name, version_digest,
                        contests, registered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(defender) DO UPDATE SET
                        provider=excluded.provider,
                        defense_prompt=excluded.defense_prompt,
                        mandate=excluded.mandate,
                        wallet=excluded.wallet,
                        wallet_entry=excluded.wallet_entry,
                        api_key_entry=excluded.api_key_entry,
                        version_name=excluded.version_name,
                        version_digest=excluded.version_digest,
                        contests=excluded.contests
                    """,
                    (
                        record["defender"],
                        record["provider"],
                        record["defense_prompt"],
                        record["mandate"],
                        record["wallet"],
                        record["wallet_entry"],
                        record["api_key_entry"],
                        record["version_name"],
                        record["version_digest"],
                        json.dumps(record.get("contests", [])),
                        float(record.get("registered_at") or self._clock()),
                    ),
                )
                self._db.commit()
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot persist defender: {exc}") from exc

    def load_defenders(self) -> list[dict[str, Any]]:
        with self._lock:
            try:
                rows = self._db.execute("SELECT * FROM defenders").fetchall()
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot read defenders: {exc}") from exc
        records: list[dict[str, Any]] = []
        for row in rows:
            try:
                contests = json.loads(row["contests"])
            except ValueError:
                contests = []
            records.append(
                {
                    "defender": row["defender"],
                    "provider": row["provider"],
                    "defense_prompt": row["defense_prompt"],
                    "mandate": row["mandate"],
                    "wallet": row["wallet"],
                    "wallet_entry": row["wallet_entry"],
                    "api_key_entry": row["api_key_entry"],
                    "version_name": row["version_name"],
                    "version_digest": row["version_digest"],
                    "contests": [item for item in contests if isinstance(item, str)],
                    "registered_at": row["registered_at"],
                }
            )
        return records

    # -- processed transactions ----------------------------------------

    def mark_seen(self, tx_hash: str, contest_id: str) -> bool:
        """Record ``tx_hash``; return False when it was already processed."""

        key = tx_hash.lower()
        with self._lock:
            try:
                cursor = self._db.execute(
                    "INSERT OR IGNORE INTO seen_txs (tx_hash, contest_id, seen_at) VALUES (?, ?, ?)",
                    (key, contest_id, self._clock()),
                )
                self._db.commit()
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot record transaction: {exc}") from exc
            return cursor.rowcount == 1

    def forget_seen(self, tx_hash: str) -> None:
        with self._lock:
            try:
                self._db.execute("DELETE FROM seen_txs WHERE tx_hash = ?", (tx_hash.lower(),))
                self._db.commit()
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot clear transaction: {exc}") from exc

    def has_seen(self, tx_hash: str) -> bool:
        with self._lock:
            try:
                row = self._db.execute(
                    "SELECT 1 FROM seen_txs WHERE tx_hash = ?", (tx_hash.lower(),)
                ).fetchone()
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot read transaction: {exc}") from exc
        return row is not None

    # -- sessions -------------------------------------------------------

    def save_session(self, record: dict[str, Any], state: dict[str, Any] | None = None) -> None:
        with self._lock:
            try:
                self._db.execute(
                    """
                    INSERT INTO sessions (
                        contest_id, defender, version_name, version_digest,
                        wallet_address, wallet_entry, api_key_entry, provider,
                        mandate, is_mining, created_at, state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(contest_id) DO UPDATE SET
                        state=excluded.state
                    """,
                    (
                        record["contest_id"],
                        record["defender"],
                        record["version_name"],
                        record["version_digest"],
                        record["wallet_address"],
                        record["wallet_entry"],
                        record["api_key_entry"],
                        record["provider"],
                        record["mandate"],
                        1 if record["is_mining"] else 0,
                        float(record.get("created_at") or self._clock()),
                        json.dumps(state, ensure_ascii=False) if state is not None else None,
                    ),
                )
                self._db.commit()
            except (sqlite3.Error, ValueError) as exc:
                raise StateStoreError(f"cannot persist session: {exc}") from exc

    def update_session_state(self, contest_id: str, state: dict[str, Any]) -> None:
        payload = json.dumps(state, ensure_ascii=False)
        with self._lock:
            try:
                self._db.execute(
                    "UPDATE sessions SET state = ? WHERE contest_id = ?",
                    (payload, contest_id),
                )
                self._db.commit()
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot persist session state: {exc}") from exc

    def load_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            try:
                rows = self._db.execute("SELECT * FROM sessions").fetchall()
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot read sessions: {exc}") from exc
        items: list[dict[str, Any]] = []
        for row in rows:
            state = None
            if row["state"]:
                try:
                    state = json.loads(row["state"])
                except ValueError:
                    state = None
            items.append(
                {
                    "contest_id": row["contest_id"],
                    "defender": row["defender"],
                    "version_name": row["version_name"],
                    "version_digest": row["version_digest"],
                    "wallet_address": row["wallet_address"],
                    "wallet_entry": row["wallet_entry"],
                    "api_key_entry": row["api_key_entry"],
                    "provider": row["provider"],
                    "mandate": row["mandate"],
                    "is_mining": bool(row["is_mining"]),
                    "created_at": row["created_at"],
                    "state": state,
                }
            )
        return items

    def load_session(self, contest_id: str) -> dict[str, Any] | None:
        for item in self.load_sessions():
            if item["contest_id"] == contest_id:
                return item
        return None

    def delete_session(self, contest_id: str) -> None:
        with self._lock:
            try:
                self._db.execute("DELETE FROM sessions WHERE contest_id = ?", (contest_id,))
                self._db.commit()
            except sqlite3.Error as exc:
                raise StateStoreError(f"cannot delete session: {exc}") from exc
