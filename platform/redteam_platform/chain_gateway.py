"""Chain reads/writes used by the FastAPI entrypoint (task 15).

All state-changing calls load their key through ``AuditedCustody`` with a
purpose context, use the testnet's zero gas price, and require a successful
receipt.  Operator, Treasury-owner and per-contest wallet keys are separate
entries; a key whose derived address does not match the expected address is
rejected before any transaction is built.  Error messages never include keys.
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Mapping
from typing import Any, Callable, Protocol

from eth_account import Account
from web3 import Web3
from web3.logs import DISCARD

from .indexer import IndexerError, normalize_contest_id

BYTES32_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

GAS_CREATE_CONTEST = 500_000
GAS_CREATE_MINING = 500_000
GAS_MARK_DELIVERED = 200_000
GAS_FAULT = 250_000
GAS_TREASURY_WITHDRAW = 200_000
GAS_TRANSFER = 120_000
DEFAULT_RECEIPT_TIMEOUT = 90.0

_CONTEST_FIELDS = (
    "defender",
    "wallet",
    "stake",
    "stakeBps",
    "defenseHash",
    "start",
    "end",
    "endedAt",
    "state",
    "isMining",
    "attackerCount",
    "paused",
)


class GatewayError(RuntimeError):
    """Raised when a chain read/write cannot be completed."""


class ChainGatewayPort(Protocol):
    operator_address: str
    treasury_address: str

    def allowance(self, owner: str) -> int: ...
    def rtm_balance(self, address: str) -> int: ...
    def active_mining_count(self) -> int: ...
    def defense_hash_retired(self, defense_hash: str) -> bool: ...
    def active_defense_hash(self, defense_hash: str) -> str: ...
    def contest_info(self, contest_id: str) -> dict[str, Any]: ...
    def fund_wallet(self, wallet: str, amount: int) -> str: ...
    def create_contest(
        self, defender: str, wallet: str, stake: int, duration: int, stake_bps: int
    ) -> tuple[str, str]: ...
    def mark_delivered(self, contest_id: str, attacker: str, msg_hash: str) -> str: ...
    def report_defender_fault(self, contest_id: str) -> str: ...
    def retire_mining(self, contest_id: str) -> str: ...
    def create_mining_contest(
        self, wallet: str, defense_hash: str
    ) -> tuple[str, str]: ...
    def treasury_withdraw(self, wallet: str, amount: int) -> str: ...
    def wallet_transfer(
        self, wallet_entry: str, wallet_address: str, to: str, amount: int,
        *, contest_id: str | None = None,
    ) -> str: ...


def _require_address(value: Any, field: str) -> str:
    try:
        address = Web3.to_checksum_address(value)
    except (ValueError, TypeError):
        raise GatewayError(f"{field} must be a valid address") from None
    if int(address, 16) == 0:
        raise GatewayError(f"{field} must not be the zero address")
    return address


def _bytes32(value: Any, field: str) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    elif isinstance(value, str) and BYTES32_RE.fullmatch(value):
        data = bytes.fromhex(value[2:])
    else:
        raise GatewayError(f"{field} must be 32-byte hex")
    if len(data) != 32:
        raise GatewayError(f"{field} must be 32-byte hex")
    return data


def _hex32(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    text = str(value).lower()
    return text if text.startswith("0x") else "0x" + text


def _require_amount(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise GatewayError(f"{field} must be a non-negative integer")
    try:
        amount = int(value)
    except (TypeError, ValueError):
        raise GatewayError(f"{field} must be a non-negative integer") from None
    if amount < 0:
        raise GatewayError(f"{field} must be a non-negative integer")
    return amount


class Web3ChainGateway:
    """Concrete gateway for the R4 Arena/RTMToken/Treasury/Faucet deployment."""

    def __init__(
        self,
        w3: Web3,
        contracts: dict[str, Any],
        custody: Any,
        *,
        operator_entry: str,
        treasury_owner_entry: str,
        chain_id: int,
        operator_address: str,
        treasury_address: str,
        treasury_owner_address: str,
        rtm_address: str,
        arena_address: str,
        receipt_timeout: float = DEFAULT_RECEIPT_TIMEOUT,
    ) -> None:
        for entry, label in (
            (operator_entry, "operator_entry"),
            (treasury_owner_entry, "treasury_owner_entry"),
        ):
            if not isinstance(entry, str) or not entry.strip():
                raise GatewayError(f"{label} must be a non-empty entry name")
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise GatewayError("chain_id must be a positive integer")
        if isinstance(receipt_timeout, bool) or not isinstance(receipt_timeout, (int, float)):
            raise GatewayError("receipt_timeout must be a positive number")
        timeout = float(receipt_timeout)
        if not math.isfinite(timeout) or not 0 < timeout <= 600:
            raise GatewayError("receipt_timeout must be positive and at most 600")
        self._w3 = w3
        self._arena = contracts["Arena"]
        self._rtm = contracts["RTMToken"]
        self._treasury = contracts["Treasury"]
        self._custody = custody
        self.operator_entry = operator_entry
        self.treasury_owner_entry = treasury_owner_entry
        self.chain_id = chain_id
        self.operator_address = _require_address(operator_address, "operator_address")
        self.treasury_address = _require_address(treasury_address, "treasury_address")
        self.treasury_owner_address = _require_address(
            treasury_owner_address, "treasury_owner_address"
        )
        self.rtm_address = _require_address(rtm_address, "rtm_address")
        self.arena_address = _require_address(arena_address, "arena_address")
        self.receipt_timeout = timeout
        self._lock = threading.RLock()

    # -- key/transaction helpers ---------------------------------------

    def _load_key(self, entry: str, expected: str, context: dict[str, str]) -> tuple[str, str]:
        try:
            private_key = self._custody.load(entry, context=context)
        except Exception:
            raise GatewayError("custody key unavailable") from None
        try:
            account = Account.from_key(private_key)
        except Exception:
            raise GatewayError("custody key is invalid") from None
        if account.address != expected:
            raise GatewayError("custody key does not match the expected address")
        return private_key, account.address

    def _send(
        self,
        *,
        entry: str,
        expected: str,
        context: dict[str, str],
        build: Callable[[str], Any],
        gas: int,
    ) -> tuple[str, dict]:
        with self._lock:
            private_key, sender = self._load_key(entry, expected, context)
            try:
                nonce = int(self._w3.eth.get_transaction_count(sender))
                tx = build(sender).build_transaction(
                    {
                        "from": sender,
                        "nonce": nonce,
                        "gas": gas,
                        "gasPrice": 0,
                        "chainId": self.chain_id,
                    }
                )
                signed = self._w3.eth.account.sign_transaction(tx, private_key)
                tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = self._w3.eth.wait_for_transaction_receipt(
                    tx_hash, timeout=self.receipt_timeout
                )
            except Exception as exc:
                raise GatewayError("transaction failed") from exc
            # web3 8 returns AttributeDict, which is a Mapping but not a dict.
            if not isinstance(receipt, Mapping) or receipt.get("status") != 1:
                raise GatewayError("transaction reverted")
            return _hex32(tx_hash), receipt

    def _send_operator(
        self, *, purpose: str, context: dict[str, str], build: Callable[[str], Any], gas: int
    ) -> tuple[str, dict]:
        valid_context = {"purpose": purpose, **context}
        return self._send(
            entry=self.operator_entry,
            expected=self.operator_address,
            context=valid_context,
            build=build,
            gas=gas,
        )

    def _contest_id_from_receipt(self, receipt: dict, event_name: str = "ContestCreated") -> str:
        try:
            event = getattr(self._arena.events, event_name)
            decoded = event.process_receipt(receipt, errors=DISCARD)
        except Exception as exc:
            raise GatewayError("cannot decode contest event") from exc
        for entry in decoded:
            args = entry.get("args", {})
            value = args.get("id") or args.get("contestId")
            if value is not None:
                try:
                    return normalize_contest_id(value)
                except IndexerError as exc:
                    raise GatewayError(str(exc)) from None
        raise GatewayError("contest event missing from receipt")

    # -- reads ----------------------------------------------------------

    def _call(self, fn: Callable[[], Any], field: str) -> Any:
        try:
            return fn()
        except Exception as exc:
            raise GatewayError(f"cannot read {field}") from exc

    def allowance(self, owner: str) -> int:
        owner = _require_address(owner, "owner")
        return _require_amount(
            self._call(
                lambda: self._rtm.functions.allowance(
                    owner, self.arena_address
                ).call(),
                "allowance",
            ),
            "allowance",
        )

    def rtm_balance(self, address: str) -> int:
        address = _require_address(address, "address")
        return _require_amount(
            self._call(
                lambda: self._rtm.functions.balanceOf(address).call(), "balance"
            ),
            "balance",
        )

    def active_mining_count(self) -> int:
        return _require_amount(
            self._call(
                lambda: self._arena.functions.activeMiningCount().call(),
                "activeMiningCount",
            ),
            "activeMiningCount",
        )

    def defense_hash_retired(self, defense_hash: str) -> bool:
        digest = _bytes32(defense_hash, "defense_hash")
        return bool(
            self._call(
                lambda: self._arena.functions.retiredDefenseHash(digest).call(),
                "retiredDefenseHash",
            )
        )

    def active_defense_hash(self, defense_hash: str) -> str:
        digest = _bytes32(defense_hash, "defense_hash")
        value = self._call(
            lambda: self._arena.functions.activeDefenseHash(digest).call(),
            "activeDefenseHash",
        )
        return _hex32(value)

    def contest_info(self, contest_id: str) -> dict[str, Any]:
        digest = _bytes32(normalize_contest_id(contest_id), "contest_id")
        info = self._call(
            lambda: self._arena.functions.contestInfo(digest).call(),
            "contestInfo",
        )
        if isinstance(info, Mapping):
            values = [info.get(name) for name in _CONTEST_FIELDS]
        else:
            try:
                values = list(info)
            except TypeError:
                raise GatewayError("contestInfo returned an unexpected value") from None
        if len(values) < len(_CONTEST_FIELDS):
            raise GatewayError("contestInfo returned an incomplete value")
        return {
            "defender": Web3.to_checksum_address(values[0]),
            "wallet": Web3.to_checksum_address(values[1]),
            "stake": str(int(values[2])),
            "stake_bps": int(values[3]),
            "defense_hash": _hex32(values[4]),
            "start": int(values[5]),
            "end": int(values[6]),
            "ended_at": int(values[7]),
            "state": int(values[8]),
            "is_mining": bool(values[9]),
            "attacker_count": int(values[10]),
            "paused": bool(values[11]),
        }

    # -- writes ---------------------------------------------------------

    def fund_wallet(self, wallet: str, amount: int) -> str:
        wallet = _require_address(wallet, "wallet")
        amount = _require_amount(amount, "amount")
        tx, _receipt = self._send_operator(
            purpose="wallet_funding",
            context={"wallet_address": wallet},
            build=lambda sender: self._rtm.functions.transfer(wallet, amount),
            gas=GAS_TRANSFER,
        )
        return tx

    def create_contest(
        self, defender: str, wallet: str, stake: int, duration: int, stake_bps: int
    ) -> tuple[str, str]:
        defender = _require_address(defender, "defender")
        wallet = _require_address(wallet, "wallet")
        stake = _require_amount(stake, "stake")
        duration = _require_amount(duration, "duration")
        stake_bps = _require_amount(stake_bps, "stake_bps")
        if stake == 0 or duration == 0:
            raise GatewayError("stake and duration must be positive")
        if self.allowance(defender) < stake:
            raise GatewayError("defender must approve the Arena stake first")
        tx, receipt = self._send_operator(
            purpose="create_contest",
            context={"wallet_address": wallet},
            build=lambda sender: self._arena.functions.createContest(
                defender, wallet, stake, duration, stake_bps
            ),
            gas=GAS_CREATE_CONTEST,
        )
        return self._contest_id_from_receipt(receipt), tx

    def mark_delivered(self, contest_id: str, attacker: str, msg_hash: str) -> str:
        cid = normalize_contest_id(contest_id)
        attacker = _require_address(attacker, "attacker")
        digest = _bytes32(msg_hash, "msg_hash")
        tx, _receipt = self._send_operator(
            purpose="mark_delivered",
            context={"contest_id": cid, "wallet_address": attacker},
            build=lambda sender: self._arena.functions.markDelivered(
                bytes.fromhex(cid[2:]), attacker, digest
            ),
            gas=GAS_MARK_DELIVERED,
        )
        return tx

    def report_defender_fault(self, contest_id: str) -> str:
        cid = normalize_contest_id(contest_id)
        tx, _receipt = self._send_operator(
            purpose="report_defender_fault",
            context={"contest_id": cid},
            build=lambda sender: self._arena.functions.reportDefenderFault(
                bytes.fromhex(cid[2:])
            ),
            gas=GAS_FAULT,
        )
        return tx

    def retire_mining(self, contest_id: str) -> str:
        cid = normalize_contest_id(contest_id)
        tx, _receipt = self._send_operator(
            purpose="retire_mining",
            context={"contest_id": cid},
            build=lambda sender: self._arena.functions.retireMining(
                bytes.fromhex(cid[2:])
            ),
            gas=GAS_FAULT,
        )
        return tx

    def create_mining_contest(self, wallet: str, defense_hash: str) -> tuple[str, str]:
        wallet = _require_address(wallet, "wallet")
        digest = _bytes32(defense_hash, "defense_hash")
        tx, receipt = self._send_operator(
            purpose="create_mining_contest",
            context={"wallet_address": wallet},
            build=lambda sender: self._arena.functions.createMiningContest(
                wallet, digest
            ),
            gas=GAS_CREATE_MINING,
        )
        return self._contest_id_from_receipt(receipt), tx

    def treasury_withdraw(self, wallet: str, amount: int) -> str:
        wallet = _require_address(wallet, "wallet")
        amount = _require_amount(amount, "amount")
        tx, _receipt = self._send(
            entry=self.treasury_owner_entry,
            expected=self.treasury_owner_address,
            context={
                "purpose": "treasury_prefund",
                "wallet_address": wallet,
                "chain_id": str(self.chain_id),
            },
            build=lambda sender: self._treasury.functions.withdraw(
                self.rtm_address, wallet, amount
            ),
            gas=GAS_TREASURY_WITHDRAW,
        )
        return tx

    def wallet_transfer(
        self,
        wallet_entry: str,
        wallet_address: str,
        to: str,
        amount: int,
        *,
        contest_id: str | None = None,
    ) -> str:
        wallet = _require_address(wallet_address, "wallet_address")
        to = _require_address(to, "to")
        amount = _require_amount(amount, "amount")
        context = {"purpose": "wallet_recovery", "wallet_address": wallet}
        if contest_id is not None:
            context["contest_id"] = normalize_contest_id(contest_id)
        tx, _receipt = self._send(
            entry=wallet_entry,
            expected=wallet,
            context=context,
            build=lambda sender: self._rtm.functions.transfer(to, amount),
            gas=GAS_TRANSFER,
        )
        return tx
