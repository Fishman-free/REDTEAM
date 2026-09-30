"""SQLite-backed ledger for PayAssist.

The ledger is the source of truth for payment decisions. Every decision the
assistant makes is appended to the ``payments`` table and never rewritten, so
a downstream auditor can replay the full history from this table alone. The
table/column layout and the status vocabulary (``executed``,
``blocked_by_policy``, ``duplicate_blocked``) are identical to PayGate so the
platform-side constitution scorer can replay this ledger unchanged.

Request-id based idempotency: the assistant treats ``request_id`` as the
stable deduplication key issued by the calling system. A request_id that was
already recorded is answered with ``duplicate_blocked`` and leaves the task
budget untouched.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

DEFAULT_DB_PATH = "/data/payassist.sqlite"


@dataclass(frozen=True)
class Authorization:
    """Trusted authorization facts injected by the platform when a task is created."""

    order_id: str
    recipient: str
    exact_amount_minor: int
    max_total_minor: int
    currency: str = "CNY"
    allowed_purposes: tuple[str, ...] = ("purchase",)
    max_executions: int = 1
    require_confirmation_above_minor: int | None = None
    # 场景分级（研究计划 §02）：L0 不允许付款 / L2 限额模式
    allows_payment: bool = True
    max_per_payment_minor: int | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Authorization":
        purposes = data.get("allowed_purposes") or ["purchase"]
        threshold = data.get("require_confirmation_above_minor")
        per_payment = data.get("max_per_payment_minor")
        return cls(
            order_id=str(data["order_id"]),
            recipient=str(data["recipient"]),
            exact_amount_minor=int(data["exact_amount_minor"]),
            max_total_minor=int(data["max_total_minor"]),
            currency=str(data.get("currency") or "CNY"),
            allowed_purposes=tuple(str(p) for p in purposes),
            max_executions=int(data.get("max_executions") or 1),
            require_confirmation_above_minor=int(threshold) if threshold is not None else None,
            allows_payment=bool(data.get("allows_payment", True)),
            max_per_payment_minor=int(per_payment) if per_payment is not None else None,
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "recipient": self.recipient,
            "exact_amount_minor": self.exact_amount_minor,
            "max_total_minor": self.max_total_minor,
            "currency": self.currency,
            "allowed_purposes": list(self.allowed_purposes),
            "max_executions": self.max_executions,
            "require_confirmation_above_minor": self.require_confirmation_above_minor,
            "allows_payment": self.allows_payment,
            "max_per_payment_minor": self.max_per_payment_minor,
        }


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    user_request: str
    authorization: Authorization
    status: str = "pending"
    spent_minor: int = 0
    executed_count: int = 0


_SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    request_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    created_at REAL NOT NULL,
    seq INTEGER PRIMARY KEY AUTOINCREMENT
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    user_request TEXT NOT NULL,
    authorization TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    spent_minor INTEGER NOT NULL DEFAULT 0,
    executed_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS surfaces (
    surface TEXT PRIMARY KEY,
    order_id TEXT,
    content TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS user_messages (
    message_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def resolve_db_path() -> Path:
    """Resolve the ledger file location from the environment.

    The default ``/data`` directory exists in the container image. When the
    module is imported on a developer machine without a writable ``/data``,
    fall back to a file next to the current directory so imports never fail.
    An explicitly configured ``PAYASSIST_DB`` is always honored as-is.
    """
    raw = os.environ.get("PAYASSIST_DB") or DEFAULT_DB_PATH
    path = Path(raw)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        if os.environ.get("PAYASSIST_DB"):
            raise
        path = Path("payassist.sqlite").resolve()
    return path


class Ledger:
    """Append-only payment ledger plus task and surface persistence."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = Path(db_path) if db_path is not None else resolve_db_path()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ tasks

    def create_task(self, task_id: str, user_request: str, authorization: Authorization) -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO tasks(task_id, user_request, authorization, status,"
                " spent_minor, executed_count, created_at, updated_at)"
                " VALUES(?,?,?,?,0,0,?,?)",
                (
                    task_id,
                    user_request,
                    json.dumps(authorization.as_mapping(), ensure_ascii=False),
                    "pending",
                    now,
                    now,
                ),
            )

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT task_id, user_request, authorization, status, spent_minor,"
                " executed_count FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return TaskRecord(
            task_id=row["task_id"],
            user_request=row["user_request"],
            authorization=Authorization.from_mapping(json.loads(row["authorization"])),
            status=row["status"],
            spent_minor=row["spent_minor"],
            executed_count=row["executed_count"],
        )

    def set_task_status(self, task_id: str, status: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (status, time.time(), task_id),
            )

    # --------------------------------------------------------------- surfaces

    def set_surface(self, surface: str, order_id: str | None, content: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO surfaces(surface, order_id, content, updated_at) VALUES(?,?,?,?)"
                " ON CONFLICT(surface) DO UPDATE SET"
                " order_id=excluded.order_id, content=excluded.content,"
                " updated_at=excluded.updated_at",
                (surface, order_id, content, time.time()),
            )

    def get_surface(self, surface: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT surface, order_id, content, updated_at FROM surfaces WHERE surface = ?",
                (surface,),
            ).fetchone()
        return dict(row) if row is not None else None

    # ---------------------------------------------------------- user channel

    def append_user_message(self, message_id: str, task_id: str, subject: str, content: str) -> dict[str, Any]:
        """Record one platform-verified 用户对话入口 message (确认变更 channel).

        Only the platform host can reach this: external HTTP traffic is limited
        to the four untrusted surfaces. Duplicate message_ids are idempotent.
        """
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO user_messages(message_id, task_id, subject, content, created_at)"
                " VALUES(?,?,?,?,?)"
                " ON CONFLICT(message_id) DO NOTHING",
                (message_id, task_id, subject, content, now),
            )
            row = self._conn.execute(
                "SELECT message_id, task_id, subject, content, created_at"
                " FROM user_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        return dict(row)

    def user_messages_for_task(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT message_id, task_id, subject, content, created_at"
                " FROM user_messages WHERE task_id = ? ORDER BY created_at, message_id",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # --------------------------------------------------------------- payments

    def pay(self, task_id: str, item: Any, allowed: bool, reason: str | None) -> dict[str, Any]:
        """Append one decision to the ledger.

        The idempotency key is ``request_id``: if it was already recorded the
        new row is stored with status ``duplicate_blocked`` and the task budget
        is left untouched. Otherwise the row reflects the assistant's decision
        (``executed`` decrements the remaining task budget, ``blocked_by_policy``
        records a decision the assistant itself withheld, together with its
        reason).
        """
        now = time.time()
        with self._lock, self._conn:
            seen = self._conn.execute(
                "SELECT 1 FROM payments WHERE request_id = ? LIMIT 1",
                (item.request_id,),
            ).fetchone()
            if seen is not None:
                status, reason = "duplicate_blocked", "request_id already recorded"
            elif allowed:
                status = "executed"
                if reason is None:
                    reason = "allowed"
            else:
                status = "blocked_by_policy"

            cursor = self._conn.execute(
                "INSERT INTO payments(request_id, order_id, recipient, amount_minor,"
                " currency, purpose, status, reason, created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    item.request_id,
                    item.order_id,
                    item.recipient,
                    int(item.amount_minor),
                    item.currency,
                    item.purpose,
                    status,
                    reason,
                    now,
                ),
            )
            seq = cursor.lastrowid
            if status == "executed":
                self._conn.execute(
                    "UPDATE tasks SET spent_minor = spent_minor + ?,"
                    " executed_count = executed_count + 1, updated_at = ? WHERE task_id = ?",
                    (int(item.amount_minor), now, task_id),
                )
            else:
                self._conn.execute(
                    "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                    (now, task_id),
                )
            row = self._conn.execute(
                "SELECT request_id, order_id, recipient, amount_minor, currency, purpose,"
                " status, reason, created_at, seq FROM payments WHERE seq = ?",
                (seq,),
            ).fetchone()
        return dict(row)

    def all_payments(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT request_id, order_id, recipient, amount_minor, currency, purpose,"
                " status, reason, created_at, seq FROM payments ORDER BY seq"
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ misc

    def reset(self) -> None:
        """Drop all rows (test helper; production ledgers are append-only)."""
        with self._lock, self._conn:
            self._conn.executescript(
                "DELETE FROM payments; DELETE FROM tasks; DELETE FROM surfaces;"
                " DELETE FROM user_messages;"
            )
