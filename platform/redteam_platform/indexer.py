"""SQLite event indexer and leaderboards for the REDTEAM arena (task 13).

Scope:

* idempotent raw event storage keyed by ``(block_number, log_index)``;
* contest/attacker/defender/miner aggregates built from Arena, RTMToken and
  DataMarket events;
* normal attacker, defender, miner and mining leaderboards, plus the active
  mining versions (contest id + defense hash);
* explicit smoke-contest exclusion.  Deployment ``mintForTest`` injections are
  never counted: mining issuance is derived from ``MiningSettled.reward`` for
  included contests, and ``MiningMinted`` is not treated as a statistic.

Leaderboard definitions (v1):

* attackers: wins, ``rtm_won`` (Breach transfer + ContestSettled rest),
  difficulty (contest paid-message count at the winning breach), current and
  longest streak;
* defenders: ``contests_survived`` (Expired only), ``msgs_withstood`` (paid
  messages in expired contests), ``net_income = penalties - breach_loss``,
  ``longest_survival`` (creation to breach/expiry/fault, seconds);
* miners: joined, ``decided_joined`` (settled + retired), wins, fixed reward,
  difficulty, ``breach_rate = wins / decided_joined``;
* mining: created/settled/retired/decided counts, global breach rate, total
  fixed reward, active versions and a settled/retired history.

The indexer stores only public chain data.  Custody access audit is task 12's
``AuditedCustody``; this module neither reads keys nor writes audit records.
The HTTP API is task 14's concern.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from web3 import Web3

SCHEMA_VERSION = 1
_ZERO = "0"

ARENA_EVENTS = (
    "ContestCreated",
    "Joined",
    "MiningJoined",
    "DataConsentRecorded",
    "AttackPaid",
    "MarkDelivered",
    "PenaltiesCollected",
    "Paused",
    "Unpaused",
    "DefenderFault",
    "RefundUnserved",
    "Expired",
    "ContestSettled",
    "StakeWithdrawn",
    "MiningSettled",
    "MiningRetired",
    "OperatorUpdated",
)
TOKEN_EVENTS = ("Breach",)
MARKET_EVENTS = ("DatasetPublished", "DataSold")

_ADDRESS_KEYS = frozenset(
    {
        "defender",
        "attacker",
        "miner",
        "wallet",
        "recipient",
        "winner",
        "buyer",
        "seller",
        "operator",
        "previous",
        "next",
    }
)
_ID_KEYS = frozenset({"id", "contestId", "msgHash", "defenseHash", "root"})
_CONTEST_ID_RE = re.compile(r"^0x[0-9a-f]{64}$")
_VISIBLE_RE = re.compile(r"^[\x20-\x7e]{1,128}$")


class IndexerError(RuntimeError):
    """Raised for invalid configuration, events or inconsistent replay state."""


class EventSource(Protocol):
    def fetch(self, from_block: int, to_block: int) -> Iterable[dict]: ...


def _require_visible(value: Any, field: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise IndexerError(f"{field} must be a non-empty string of at most {maximum} characters")
    if any(not 0x20 <= ord(character) <= 0x7E for character in value):
        raise IndexerError(f"{field} must contain only visible ASCII characters")
    return value


def normalize_contest_id(value: Any) -> str:
    """Normalize a bytes32 contest id to ``0x`` + 64 lowercase hex."""

    if isinstance(value, (bytes, bytearray)):
        text = "0x" + bytes(value).hex()
    elif isinstance(value, str):
        text = value.lower()
    else:
        raise IndexerError("contest id must be a bytes32 hex string")
    if not _CONTEST_ID_RE.fullmatch(text):
        raise IndexerError("contest id must be a bytes32 hex string")
    return text


def _require_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise IndexerError(f"{field} must be an integer >= {minimum}")
    return value


def _require_amount(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise IndexerError(f"{field} must be a non-negative integer amount")
    try:
        amount = int(value)
    except (TypeError, ValueError):
        raise IndexerError(f"{field} must be a non-negative integer amount") from None
    if amount < 0:
        raise IndexerError(f"{field} must be a non-negative integer amount")
    return amount


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if isinstance(value, list):
        return [_normalize_scalar(item) for item in value]
    return value


def _normalize_args(args: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in dict(args).items():
        key = str(key)
        if key in _ADDRESS_KEYS and isinstance(value, str):
            try:
                value = Web3.to_checksum_address(value)
            except (ValueError, TypeError):
                pass
        elif key in _ID_KEYS and isinstance(value, str):
            value = value.lower()
        else:
            value = _normalize_scalar(value)
        normalized[key] = value
    return normalized


def _event_contest_id(args: Mapping[str, Any]) -> str | None:
    for key in ("id", "contestId"):
        if key in args:
            return normalize_contest_id(args[key])
    return None


def normalize_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one raw event into the indexer's event shape."""

    if not isinstance(event, Mapping):
        raise IndexerError("event must be a mapping")
    name = event.get("name") or event.get("event")
    if not isinstance(name, str) or not _VISIBLE_RE.fullmatch(name):
        raise IndexerError("event name must be visible ASCII")
    args = event.get("args")
    if not isinstance(args, Mapping):
        raise IndexerError(f"event {name} must carry an args mapping")

    block_number = _require_int(
        event.get("block_number", event.get("blockNumber")), "block_number"
    )
    log_index = _require_int(
        event.get("log_index", event.get("logIndex")), "log_index"
    )
    timestamp = _require_int(
        event.get("block_timestamp", event.get("blockTimestamp", 0)) or 0,
        "block_timestamp",
    )
    tx_hash = event.get("tx_hash", event.get("transactionHash", ""))
    if isinstance(tx_hash, (bytes, bytearray)):
        tx_hash = "0x" + bytes(tx_hash).hex()
    else:
        tx_hash = str(tx_hash or "").lower()
    contract = str(event.get("contract") or "")

    return {
        "block_number": block_number,
        "log_index": log_index,
        "block_timestamp": timestamp,
        "tx_hash": tx_hash,
        "contract": contract,
        "name": name,
        "args": _normalize_args(args),
    }


class EventIndexer:
    """Idempotent SQLite event store plus leaderboard aggregates."""

    _HANDLERS = {
        "ContestCreated": "_handle_contest_created",
        "Joined": "_handle_joined",
        "MiningJoined": "_handle_mining_joined",
        "DataConsentRecorded": "_handle_data_consent",
        "AttackPaid": "_handle_attack_paid",
        "MarkDelivered": "_handle_mark_delivered",
        "Breach": "_handle_breach",
        "ContestSettled": "_handle_contest_settled",
        "Expired": "_handle_expired",
        "DefenderFault": "_handle_defender_fault",
        "PenaltiesCollected": "_handle_penalties_collected",
        "MiningSettled": "_handle_mining_settled",
        "MiningRetired": "_handle_mining_retired",
    }

    def __init__(
        self,
        db_path: str | Path,
        *,
        network: str,
        excluded_contest_ids: Iterable[str] = (),
        on_mining_ended: Callable[[str, str], None] | None = None,
    ) -> None:
        self.network = _require_visible(network, "network", maximum=64)
        if on_mining_ended is not None and not callable(on_mining_ended):
            raise IndexerError("on_mining_ended must be callable")
        self._on_mining_ended = on_mining_ended
        if isinstance(excluded_contest_ids, str):
            excluded_contest_ids = (excluded_contest_ids,)
        self._excluded = frozenset(
            normalize_contest_id(value) for value in excluded_contest_ids
        )
        self.db_path = Path(db_path).expanduser()
        self._lock = threading.RLock()
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn: sqlite3.Connection | None = sqlite3.connect(
                str(self.db_path), check_same_thread=False
            )
        except (OSError, sqlite3.Error) as exc:
            raise IndexerError(f"cannot open index database {self.db_path}: {exc}") from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA foreign_keys = ON")
        try:
            with self._lock, self._conn:
                self._create_schema()
                self._ensure_meta()
        except Exception:
            self._conn.close()
            self._conn = None
            raise

    # -- lifecycle ------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "EventIndexer":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise IndexerError("index database is closed")
        return self._conn

    # -- schema ---------------------------------------------------------

    def _create_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                block_number INTEGER NOT NULL,
                log_index INTEGER NOT NULL,
                tx_hash TEXT NOT NULL,
                contract TEXT NOT NULL,
                name TEXT NOT NULL,
                args_json TEXT NOT NULL,
                block_timestamp INTEGER NOT NULL,
                excluded INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (block_number, log_index)
            );
            CREATE TABLE IF NOT EXISTS contests (
                id TEXT PRIMARY KEY,
                defender TEXT NOT NULL,
                wallet TEXT NOT NULL,
                stake TEXT NOT NULL,
                end TEXT NOT NULL,
                is_mining INTEGER NOT NULL,
                stake_bps INTEGER NOT NULL,
                defense_hash TEXT NOT NULL,
                start_ts INTEGER NOT NULL,
                ended_ts INTEGER,
                state TEXT NOT NULL,
                paid_count INTEGER NOT NULL DEFAULT 0,
                winner TEXT,
                breach_amount TEXT NOT NULL DEFAULT '0',
                reward TEXT NOT NULL DEFAULT '0',
                settled INTEGER NOT NULL DEFAULT 0,
                excluded INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS contest_attackers (
                contest_id TEXT NOT NULL,
                attacker TEXT NOT NULL,
                is_mining INTEGER NOT NULL,
                stake TEXT NOT NULL,
                data_consent INTEGER,
                paid INTEGER NOT NULL DEFAULT 0,
                delivered INTEGER NOT NULL DEFAULT 0,
                won INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (contest_id, attacker)
            );
            CREATE TABLE IF NOT EXISTS attackers (
                address TEXT PRIMARY KEY,
                wins INTEGER NOT NULL DEFAULT 0,
                rtm_won TEXT NOT NULL DEFAULT '0',
                difficulty TEXT NOT NULL DEFAULT '0',
                current_streak INTEGER NOT NULL DEFAULT 0,
                longest_streak INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS defenders (
                address TEXT PRIMARY KEY,
                contests_survived INTEGER NOT NULL DEFAULT 0,
                msgs_withstood INTEGER NOT NULL DEFAULT 0,
                penalties TEXT NOT NULL DEFAULT '0',
                breach_loss TEXT NOT NULL DEFAULT '0',
                faults INTEGER NOT NULL DEFAULT 0,
                longest_survival INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS miners (
                address TEXT PRIMARY KEY,
                joined INTEGER NOT NULL DEFAULT 0,
                decided_joined INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                rtm_won TEXT NOT NULL DEFAULT '0',
                difficulty TEXT NOT NULL DEFAULT '0'
            );
            CREATE INDEX IF NOT EXISTS idx_contests_defender
                ON contests(defender);
            CREATE INDEX IF NOT EXISTS idx_contest_attackers_attacker
                ON contest_attackers(attacker);
            """
        )

    def _ensure_meta(self) -> None:
        assert self._conn is not None
        version = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        network = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'network'"
        ).fetchone()
        if version is None:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES('network', ?)", (self.network,)
            )
            return
        if version["value"] != str(SCHEMA_VERSION):
            raise IndexerError(
                f"unsupported index schema version {version['value']!r}; "
                f"expected {SCHEMA_VERSION}"
            )
        if network is None:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES('network', ?)", (self.network,)
            )
        elif network["value"] != self.network:
            raise IndexerError(
                f"index database belongs to network {network['value']!r}, "
                f"not {self.network!r}"
            )

    # -- ingestion ------------------------------------------------------

    def apply_event(self, event: Mapping[str, Any]) -> bool:
        """Store one event and update aggregates; return False on duplicate."""

        normalized = normalize_event(event)
        contest_id = _event_contest_id(normalized["args"])
        excluded = contest_id is not None and contest_id in self._excluded
        args_json = json.dumps(
            normalized["args"], ensure_ascii=False, sort_keys=True
        )

        with self._lock:
            with self._db():
                cursor = self._db().execute(
                    """
                    INSERT OR IGNORE INTO events(
                        block_number, log_index, tx_hash, contract, name,
                        args_json, block_timestamp, excluded
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized["block_number"],
                        normalized["log_index"],
                        normalized["tx_hash"],
                        normalized["contract"],
                        normalized["name"],
                        args_json,
                        normalized["block_timestamp"],
                        1 if excluded else 0,
                    ),
                )
                if cursor.rowcount == 0:
                    return False
                if not excluded:
                    self._apply(normalized)
                return True

    def apply_events(self, events: Iterable[Mapping[str, Any]]) -> int:
        return sum(1 for event in events if self.apply_event(event))

    def process_block_range(
        self, source: EventSource, start_block: int, end_block: int
    ) -> int:
        """Fetch and apply ``[start_block, end_block]``; idempotent on replay."""

        start = _require_int(start_block, "start_block")
        end = _require_int(end_block, "end_block")
        if start > end:
            raise IndexerError("start_block must not exceed end_block")
        try:
            events = source.fetch(start, end)
        except IndexerError:
            raise
        except Exception as exc:
            raise IndexerError(f"event source failed: {exc}") from exc

        ordered = sorted(
            events,
            key=lambda item: (
                _require_int(
                    item.get("block_number", item.get("blockNumber")),
                    "block_number",
                ),
                _require_int(
                    item.get("log_index", item.get("logIndex")),
                    "log_index",
                ),
            ),
        )
        stored = 0
        for event in ordered:
            block_number = _require_int(
                event.get("block_number", event.get("blockNumber")),
                "block_number",
            )
            if not start <= block_number <= end:
                continue
            if self.apply_event(event):
                stored += 1

        with self._lock, self._db():
            current = self.last_block()
            if current is None or end > current:
                self._db().execute(
                    """
                    INSERT INTO meta(key, value) VALUES('last_block', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (str(end),),
                )
        return stored

    def last_block(self) -> int | None:
        with self._lock:
            row = self._db().execute(
                "SELECT value FROM meta WHERE key = 'last_block'"
            ).fetchone()
            return None if row is None else int(row["value"])

    # -- aggregate dispatch ---------------------------------------------

    def _apply(self, event: Mapping[str, Any]) -> None:
        handler = self._HANDLERS.get(event["name"])
        if handler is None:
            return
        getattr(self, handler)(event["args"], event["block_timestamp"])

    def _fire_mining_ended(self, contest_id: str, name: str) -> None:
        if self._on_mining_ended is not None:
            self._on_mining_ended(contest_id, name)

    # -- small SQL helpers ----------------------------------------------

    def _contest(self, contest_id: str) -> sqlite3.Row:
        row = self._db().execute(
            "SELECT * FROM contests WHERE id = ?", (contest_id,)
        ).fetchone()
        if row is None:
            raise IndexerError(f"contest not indexed: {contest_id}")
        return row

    def _upsert_attacker(self, address: str) -> None:
        self._db().execute(
            "INSERT OR IGNORE INTO attackers(address) VALUES(?)", (address,)
        )

    def _upsert_defender(self, address: str) -> None:
        self._db().execute(
            "INSERT OR IGNORE INTO defenders(address) VALUES(?)", (address,)
        )

    def _upsert_miner(self, address: str) -> None:
        self._db().execute(
            "INSERT OR IGNORE INTO miners(address) VALUES(?)", (address,)
        )

    def _add_text(self, table: str, key: str, column: str, delta: int) -> None:
        row = self._db().execute(
            f"SELECT {column} FROM {table} WHERE address = ?", (key,)
        ).fetchone()
        if row is None:
            raise IndexerError(f"{table} row missing for {key}")
        value = int(row[column] or 0) + int(delta)
        self._db().execute(
            f"UPDATE {table} SET {column} = ? WHERE address = ?",
            (str(value), key),
        )

    def _add_contest_amount(self, contest_id: str, column: str, delta: int) -> None:
        row = self._contest(contest_id)
        value = int(row[column] or 0) + int(delta)
        self._db().execute(
            f"UPDATE contests SET {column} = ? WHERE id = ?",
            (str(value), contest_id),
        )

    def _ending_contest(self, contest_id: str, state: str, ended_ts: int) -> None:
        self._db().execute(
            "UPDATE contests SET state = ?, ended_ts = ? WHERE id = ?",
            (state, ended_ts, contest_id),
        )

    def _record_survival(self, defender: str, start_ts: int, ended_ts: int) -> None:
        duration = max(0, int(ended_ts) - int(start_ts))
        row = self._db().execute(
            "SELECT longest_survival FROM defenders WHERE address = ?", (defender,)
        ).fetchone()
        if row is None:
            raise IndexerError(f"defender row missing for {defender}")
        if duration > int(row["longest_survival"]):
            self._db().execute(
                "UPDATE defenders SET longest_survival = ? WHERE address = ?",
                (duration, defender),
            )

    def _reset_normal_streaks(self, contest_id: str, *, except_address: str | None = None) -> None:
        if except_address is None:
            self._db().execute(
                """
                UPDATE attackers SET current_streak = 0
                WHERE address IN (
                    SELECT attacker FROM contest_attackers
                    WHERE contest_id = ? AND is_mining = 0
                )
                """,
                (contest_id,),
            )
        else:
            self._db().execute(
                """
                UPDATE attackers SET current_streak = 0
                WHERE address IN (
                    SELECT attacker FROM contest_attackers
                    WHERE contest_id = ? AND is_mining = 0 AND attacker != ?
                )
                """,
                (contest_id, except_address),
            )

    # -- handlers -------------------------------------------------------

    def _handle_contest_created(self, args: Mapping[str, Any], ts: int) -> None:
        contest_id = normalize_contest_id(args["id"])
        is_mining = bool(args.get("isMining", False))
        defender = args["defender"]
        stake = _require_amount(args.get("stake", 0), "stake")
        cursor = self._db().execute(
            """
            INSERT OR IGNORE INTO contests(
                id, defender, wallet, stake, end, is_mining, stake_bps,
                defense_hash, start_ts, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'live')
            """,
            (
                contest_id,
                defender,
                args["wallet"],
                str(stake),
                str(int(args.get("end", 0))),
                1 if is_mining else 0,
                int(args.get("stakeBps", 0)),
                str(args.get("defenseHash", "0x" + "00" * 32)),
                int(ts),
            ),
        )
        if cursor.rowcount and not is_mining:
            self._upsert_defender(defender)

    def _handle_joined(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["id"]))
        if contest["is_mining"]:
            raise IndexerError("Joined event for a mining contest")
        attacker = args["attacker"]
        self._upsert_attacker(attacker)
        self._db().execute(
            """
            INSERT OR IGNORE INTO contest_attackers(
                contest_id, attacker, is_mining, stake, data_consent
            ) VALUES (?, ?, 0, ?, ?)
            """,
            (
                contest["id"],
                attacker,
                str(_require_amount(args.get("stake", 0), "stake")),
                1 if bool(args.get("dataConsent", False)) else 0,
            ),
        )

    def _handle_mining_joined(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["id"]))
        if not contest["is_mining"]:
            raise IndexerError("MiningJoined event for a normal contest")
        miner = args["miner"]
        self._upsert_miner(miner)
        cursor = self._db().execute(
            """
            INSERT OR IGNORE INTO contest_attackers(
                contest_id, attacker, is_mining, stake, data_consent
            ) VALUES (?, ?, 1, '0', 1)
            """,
            (contest["id"], miner),
        )
        if cursor.rowcount:
            self._db().execute(
                "UPDATE miners SET joined = joined + 1 WHERE address = ?",
                (miner,),
            )

    def _handle_data_consent(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["id"]))
        is_mining = bool(args.get("isMining", False))
        if bool(contest["is_mining"]) != is_mining:
            raise IndexerError("DataConsentRecorded isMining does not match contest")
        cursor = self._db().execute(
            """
            UPDATE contest_attackers SET data_consent = ?
            WHERE contest_id = ? AND attacker = ?
            """,
            (
                1 if bool(args.get("consented", False)) else 0,
                contest["id"],
                args["attacker"],
            ),
        )
        if cursor.rowcount == 0:
            raise IndexerError("DataConsentRecorded before join")

    def _handle_attack_paid(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["id"]))
        attacker = args["attacker"]
        cursor = self._db().execute(
            """
            UPDATE contest_attackers SET paid = paid + 1
            WHERE contest_id = ? AND attacker = ?
            """,
            (contest["id"], attacker),
        )
        if cursor.rowcount == 0:
            raise IndexerError("AttackPaid before join")
        self._db().execute(
            "UPDATE contests SET paid_count = paid_count + 1 WHERE id = ?",
            (contest["id"],),
        )

    def _handle_mark_delivered(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["id"]))
        delivered = _require_amount(args.get("delivered", 0), "delivered")
        cursor = self._db().execute(
            """
            UPDATE contest_attackers SET delivered = MAX(delivered, ?)
            WHERE contest_id = ? AND attacker = ?
            """,
            (delivered, contest["id"], args["attacker"]),
        )
        if cursor.rowcount == 0:
            raise IndexerError("MarkDelivered before join")

    def _handle_breach(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["contestId"]))
        if contest["state"] != "live":
            return
        amount = _require_amount(args.get("amount", 0), "amount")
        winner = args["winner"]
        if contest["is_mining"]:
            # The fixed mining reward is settled by MiningSettled; this event
            # only records the on-chain W transfer and stops the runner.
            self._db().execute(
                "UPDATE contests SET winner = ?, breach_amount = ? WHERE id = ?",
                (winner, str(amount), contest["id"]),
            )
            self._fire_mining_ended(contest["id"], "Breach")
            return

        row = self._db().execute(
            """
            SELECT 1 FROM contest_attackers
            WHERE contest_id = ? AND attacker = ? AND is_mining = 0
            """,
            (contest["id"], winner),
        ).fetchone()
        if row is None:
            raise IndexerError("Breach winner did not join the contest")
        self._db().execute(
            """
            UPDATE contests SET state = 'breached', ended_ts = ?, winner = ?,
                breach_amount = ?, settled = 0
            WHERE id = ?
            """,
            (int(ts), winner, str(amount), contest["id"]),
        )
        self._upsert_attacker(winner)
        self._db().execute(
            "UPDATE attackers SET wins = wins + 1 WHERE address = ?", (winner,)
        )
        streak = self._db().execute(
            "SELECT current_streak, longest_streak FROM attackers WHERE address = ?",
            (winner,),
        ).fetchone()
        new_streak = int(streak["current_streak"]) + 1
        new_longest = max(int(streak["longest_streak"]), new_streak)
        self._db().execute(
            """
            UPDATE attackers SET current_streak = ?, longest_streak = ?
            WHERE address = ?
            """,
            (new_streak, new_longest, winner),
        )
        # Wei amounts can exceed SQLite's signed 64-bit INTEGER; keep them in
        # Python and store decimal strings.
        self._add_text("attackers", winner, "rtm_won", amount)
        self._add_text("attackers", winner, "difficulty", int(contest["paid_count"]))
        self._db().execute(
            "UPDATE contest_attackers SET won = 1 WHERE contest_id = ? AND attacker = ?",
            (contest["id"], winner),
        )
        self._reset_normal_streaks(contest["id"], except_address=winner)
        self._upsert_defender(contest["defender"])
        self._add_text("defenders", contest["defender"], "breach_loss", amount)
        self._record_survival(
            contest["defender"], int(contest["start_ts"]), int(ts)
        )

    def _handle_contest_settled(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["id"]))
        if contest["is_mining"]:
            raise IndexerError("ContestSettled for a mining contest")
        if contest["state"] != "breached":
            raise IndexerError("ContestSettled before Breach")
        if int(contest["settled"]):
            return
        winner = args["winner"]
        if winner != contest["winner"]:
            raise IndexerError("ContestSettled winner does not match Breach")
        rest = _require_amount(args.get("amount", 0), "amount")
        self._db().execute(
            "UPDATE contests SET settled = 1 WHERE id = ?", (contest["id"],)
        )
        self._add_text("attackers", winner, "rtm_won", rest)
        self._add_text("defenders", contest["defender"], "breach_loss", rest)

    def _handle_expired(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["id"]))
        if contest["is_mining"]:
            raise IndexerError("Expired for a mining contest")
        if contest["state"] != "live":
            return
        self._ending_contest(contest["id"], "expired", int(ts))
        self._upsert_defender(contest["defender"])
        self._db().execute(
            """
            UPDATE defenders SET contests_survived = contests_survived + 1,
                msgs_withstood = msgs_withstood + ?
            WHERE address = ?
            """,
            (int(contest["paid_count"]), contest["defender"]),
        )
        self._record_survival(
            contest["defender"], int(contest["start_ts"]), int(ts)
        )
        self._reset_normal_streaks(contest["id"])

    def _handle_defender_fault(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["id"]))
        if contest["is_mining"]:
            raise IndexerError("DefenderFault for a mining contest")
        if contest["state"] != "live":
            return
        self._ending_contest(contest["id"], "faulted", int(ts))
        self._upsert_defender(contest["defender"])
        self._db().execute(
            "UPDATE defenders SET faults = faults + 1 WHERE address = ?",
            (contest["defender"],),
        )
        self._record_survival(
            contest["defender"], int(contest["start_ts"]), int(ts)
        )
        self._reset_normal_streaks(contest["id"])

    def _handle_penalties_collected(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["id"]))
        if contest["is_mining"]:
            raise IndexerError("PenaltiesCollected for a mining contest")
        recipient = args["recipient"]
        if recipient != contest["defender"]:
            raise IndexerError("PenaltiesCollected recipient is not the defender")
        self._upsert_defender(recipient)
        self._add_text(
            "defenders", recipient, "penalties",
            _require_amount(args.get("amount", 0), "amount"),
        )

    def _handle_mining_settled(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["id"]))
        if not contest["is_mining"]:
            raise IndexerError("MiningSettled for a normal contest")
        if contest["state"] not in {"live", "breached"}:
            return
        winner = args["winner"]
        row = self._db().execute(
            """
            SELECT 1 FROM contest_attackers
            WHERE contest_id = ? AND attacker = ? AND is_mining = 1
            """,
            (contest["id"], winner),
        ).fetchone()
        if row is None:
            raise IndexerError("MiningSettled winner did not join the contest")
        reward = _require_amount(args.get("reward", 0), "reward")
        defense_hash = str(args.get("defenseHash", contest["defense_hash"]))
        self._db().execute(
            """
            UPDATE contests SET state = 'settled', ended_ts = ?, winner = ?,
                defense_hash = ?, reward = ?, settled = 1
            WHERE id = ?
            """,
            (int(ts), winner, defense_hash, str(reward), contest["id"]),
        )
        self._upsert_miner(winner)
        self._db().execute(
            "UPDATE miners SET wins = wins + 1 WHERE address = ?", (winner,)
        )
        self._add_text("miners", winner, "rtm_won", reward)
        self._add_text("miners", winner, "difficulty", int(contest["paid_count"]))
        self._db().execute(
            """
            UPDATE miners SET decided_joined = decided_joined + 1
            WHERE address IN (
                SELECT attacker FROM contest_attackers
                WHERE contest_id = ? AND is_mining = 1
            )
            """,
            (contest["id"],),
        )
        self._fire_mining_ended(contest["id"], "MiningSettled")

    def _handle_mining_retired(self, args: Mapping[str, Any], ts: int) -> None:
        contest = self._contest(normalize_contest_id(args["id"]))
        if not contest["is_mining"]:
            raise IndexerError("MiningRetired for a normal contest")
        if contest["state"] not in {"live", "breached"}:
            return
        defense_hash = str(args.get("defenseHash", contest["defense_hash"]))
        self._ending_contest(contest["id"], "retired", int(ts))
        self._db().execute(
            "UPDATE contests SET defense_hash = ? WHERE id = ?",
            (defense_hash, contest["id"]),
        )
        self._db().execute(
            """
            UPDATE miners SET decided_joined = decided_joined + 1
            WHERE address IN (
                SELECT attacker FROM contest_attackers
                WHERE contest_id = ? AND is_mining = 1
            )
            """,
            (contest["id"],),
        )
        self._fire_mining_ended(contest["id"], "MiningRetired")

    # -- queries --------------------------------------------------------

    def leaderboards(self) -> dict[str, Any]:
        with self._lock:
            attackers: dict[str, dict[str, Any]] = {}
            for row in self._db().execute("SELECT * FROM attackers ORDER BY address"):
                attackers[row["address"]] = {
                    "wins": int(row["wins"]),
                    "rtm_won": str(row["rtm_won"]),
                    "difficulty": int(row["difficulty"]),
                    "current_streak": int(row["current_streak"]),
                    "longest_streak": int(row["longest_streak"]),
                }

            defenders: dict[str, dict[str, Any]] = {}
            for row in self._db().execute("SELECT * FROM defenders ORDER BY address"):
                penalties = int(row["penalties"])
                loss = int(row["breach_loss"])
                defenders[row["address"]] = {
                    "contests_survived": int(row["contests_survived"]),
                    "msgs_withstood": int(row["msgs_withstood"]),
                    "penalties": str(penalties),
                    "breach_loss": str(loss),
                    "net_income": str(penalties - loss),
                    "faults": int(row["faults"]),
                    "longest_survival": int(row["longest_survival"]),
                }

            miners: dict[str, dict[str, Any]] = {}
            for row in self._db().execute("SELECT * FROM miners ORDER BY address"):
                decided = int(row["decided_joined"])
                wins = int(row["wins"])
                miners[row["address"]] = {
                    "joined": int(row["joined"]),
                    "decided_joined": decided,
                    "wins": wins,
                    "rtm_won_fixed": str(row["rtm_won"]),
                    "difficulty": int(row["difficulty"]),
                    "breach_rate": round(wins / decided, 6) if decided else 0.0,
                }

            return {
                "network": self.network,
                "attackers": attackers,
                "defenders": defenders,
                "miners": miners,
                "mining": self._mining_stats(),
            }

    def _mining_stats(self) -> dict[str, Any]:
        rows = self._db().execute(
            "SELECT * FROM contests WHERE is_mining = 1"
        ).fetchall()
        settled = [row for row in rows if row["state"] == "settled"]
        retired = [row for row in rows if row["state"] == "retired"]
        active = [row for row in rows if row["state"] == "live"]
        decided = len(settled) + len(retired)
        history = [
            {
                "contest_id": row["id"],
                "outcome": row["state"],
                "defense_hash": row["defense_hash"],
                "ended_ts": int(row["ended_ts"] or 0),
                "paid_messages": int(row["paid_count"]),
                "winner": row["winner"],
            }
            for row in sorted(
                (row for row in rows if row["state"] in {"settled", "retired"}),
                key=lambda item: (int(item["ended_ts"] or 0), item["id"]),
            )
        ]
        return {
            "created": len(rows),
            "settled": len(settled),
            "retired": len(retired),
            "decided": decided,
            "breach_rate": round(len(settled) / decided, 6) if decided else 0.0,
            "total_fixed_reward": str(sum(int(row["reward"]) for row in settled)),
            "active_contests": len(active),
            "active_versions": [
                {
                    "contest_id": row["id"],
                    "defense_hash": row["defense_hash"],
                    "start_ts": int(row["start_ts"]),
                    "paid_messages": int(row["paid_count"]),
                }
                for row in sorted(active, key=lambda item: item["start_ts"])
            ],
            "history": history,
        }

    def _contest_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "defender": row["defender"],
            "wallet": row["wallet"],
            "stake": str(row["stake"]),
            "end": str(row["end"]),
            "is_mining": bool(row["is_mining"]),
            "stake_bps": int(row["stake_bps"]),
            "defense_hash": row["defense_hash"],
            "start_ts": int(row["start_ts"]),
            "ended_ts": None if row["ended_ts"] is None else int(row["ended_ts"]),
            "state": row["state"],
            "paid_count": int(row["paid_count"]),
            "winner": row["winner"],
            "breach_amount": str(row["breach_amount"]),
            "reward": str(row["reward"]),
            "settled": bool(row["settled"]),
        }

    def contest(self, contest_id: str) -> dict[str, Any] | None:
        contest_id = normalize_contest_id(contest_id)
        with self._lock:
            row = self._db().execute(
                "SELECT * FROM contests WHERE id = ? AND excluded = 0",
                (contest_id,),
            ).fetchone()
            return None if row is None else self._contest_dict(row)

    def contests(self, *, limit: int = 200) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise IndexerError("limit must be an integer in 1..1000")
        with self._lock:
            rows = self._db().execute(
                """
                SELECT * FROM contests WHERE excluded = 0
                ORDER BY start_ts DESC, id LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._contest_dict(row) for row in rows]

    def event_by_tx(self, tx_hash: str, name: str | None = None) -> dict[str, Any] | None:
        if not isinstance(tx_hash, str) or not re.fullmatch(
            r"0x[0-9a-fA-F]{64}", tx_hash
        ):
            raise IndexerError("tx_hash must be a 0x-prefixed 32-byte hex string")
        if name is not None:
            _require_visible(name, "event name")
        query = "SELECT * FROM events WHERE tx_hash = ?"
        params: list[Any] = [tx_hash.lower()]
        if name is not None:
            query += " AND name = ?"
            params.append(name)
        query += " ORDER BY log_index LIMIT 1"
        with self._lock:
            row = self._db().execute(query, params).fetchone()
            if row is None:
                return None
            return {
                "block_number": int(row["block_number"]),
                "log_index": int(row["log_index"]),
                "tx_hash": row["tx_hash"],
                "contract": row["contract"],
                "name": row["name"],
                "args": json.loads(row["args_json"]),
                "block_timestamp": int(row["block_timestamp"]),
                "excluded": bool(row["excluded"]),
            }

    def contest_attackers(self, contest_id: str) -> dict[str, dict[str, Any]]:
        contest_id = normalize_contest_id(contest_id)
        with self._lock:
            rows = self._db().execute(
                "SELECT * FROM contest_attackers WHERE contest_id = ? ORDER BY attacker",
                (contest_id,),
            ).fetchall()
            return {
                row["attacker"]: {
                    "is_mining": bool(row["is_mining"]),
                    "stake": str(row["stake"]),
                    "data_consent": None
                    if row["data_consent"] is None
                    else bool(row["data_consent"]),
                    "paid": int(row["paid"]),
                    "delivered": int(row["delivered"]),
                    "won": bool(row["won"]),
                }
                for row in rows
            }

    def data_consent(self, contest_id: str, attacker: str) -> bool | None:
        contest_id = normalize_contest_id(contest_id)
        with self._lock:
            row = self._db().execute(
                """
                SELECT data_consent FROM contest_attackers
                WHERE contest_id = ? AND attacker = ?
                """,
                (contest_id, attacker),
            ).fetchone()
            if row is None or row["data_consent"] is None:
                return None
            return bool(row["data_consent"])

    def is_excluded(self, contest_id: str) -> bool:
        return normalize_contest_id(contest_id) in self._excluded

    def sync_state(self) -> dict[str, Any]:
        with self._lock:
            counts = self._db().execute(
                """
                SELECT COUNT(*) AS total,
                    SUM(CASE WHEN excluded = 1 THEN 1 ELSE 0 END) AS excluded
                FROM events
                """
            ).fetchone()
            return {
                "network": self.network,
                "schema_version": SCHEMA_VERSION,
                "last_block": self.last_block(),
                "events": int(counts["total"] or 0),
                "excluded_events": int(counts["excluded"] or 0),
                "excluded_contests": sorted(self._excluded),
            }


class ChainEventSource:
    """Fetch normalized events from the deployed Arena/RTMToken/DataMarket."""

    def __init__(
        self,
        w3: Web3,
        arena: Any,
        rtm: Any,
        data_market: Any | None = None,
    ) -> None:
        self._w3 = w3
        self._sources: list[tuple[str, Any, tuple[str, ...]]] = [
            ("Arena", arena, ARENA_EVENTS),
            ("RTMToken", rtm, TOKEN_EVENTS),
        ]
        if data_market is not None:
            self._sources.append(("DataMarket", data_market, MARKET_EVENTS))

    @classmethod
    def from_chain_client(cls, chain_client: Any, *, include_market: bool = True) -> "ChainEventSource":
        contracts = chain_client.contracts
        return cls(
            chain_client.w3,
            contracts["Arena"],
            contracts["RTMToken"],
            contracts.get("DataMarket") if include_market else None,
        )

    @property
    def latest_block(self) -> int:
        return int(self._w3.eth.block_number)

    def fetch(self, from_block: int, to_block: int) -> list[dict[str, Any]]:
        start = _require_int(from_block, "from_block")
        end = _require_int(to_block, "to_block")
        if start > end:
            raise IndexerError("from_block must not exceed to_block")
        events: list[dict[str, Any]] = []
        timestamps: dict[int, int] = {}

        for contract_name, contract, names in self._sources:
            for name in names:
                try:
                    event_filter = getattr(contract.events, name)
                except AttributeError:
                    raise IndexerError(
                        f"{contract_name} ABI lacks event {name}; recompile contracts"
                    ) from None
                try:
                    logs = event_filter.get_logs(from_block=start, to_block=end)
                except Exception as exc:
                    raise IndexerError(
                        f"failed to fetch {contract_name}.{name}: {exc}"
                    ) from None
                for log in logs:
                    block_number = int(log["blockNumber"])
                    timestamp = timestamps.get(block_number)
                    if timestamp is None:
                        try:
                            timestamp = int(
                                self._w3.eth.get_block(block_number)["timestamp"]
                            )
                        except Exception as exc:
                            raise IndexerError(
                                f"failed to fetch block {block_number}: {exc}"
                            ) from None
                        timestamps[block_number] = timestamp
                    events.append(
                        {
                            "block_number": block_number,
                            "log_index": int(log["logIndex"]),
                            "tx_hash": log.get("transactionHash", ""),
                            "contract": contract_name,
                            "name": log.get("event", name),
                            "args": dict(log.get("args", {})),
                            "block_timestamp": timestamp,
                        }
                    )

        events.sort(key=lambda item: (item["block_number"], item["log_index"]))
        return events
