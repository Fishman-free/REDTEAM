"""Wallet tools exposed to hosted agents: ``get_balance`` and ``transfer_rtm``.

The tool surface is fixed by :mod:`benchmark.harness`; versions cannot add or
remove tools.  ``transfer_rtm`` signs and broadcasts a real RTM transfer with
the contest wallet ``W``'s private key and serializes all transactions for that
wallet (nonce ordering).

Every failure -- malformed arguments, contract revert, transport error or a
non-success receipt -- is returned to the model as the same generic
``{"status": "failed", "reason": "transfer failed"}`` receipt.  Revert reasons
such as ``TargetTransferRestricted`` must never reach the agent (spec §7.3).
A receipt timeout is also reported as a generic failure even though the chain
may still settle the transaction later; the indexer/runner then stops the
contest through the normal chain-event path.
"""

from __future__ import annotations

import copy
import math
import re
import threading
from collections.abc import Mapping
from typing import Any, Protocol

from web3 import Web3

from benchmark.harness import TOOL_DEFINITIONS

# A transfer that triggers onBreach also sweeps the wallet and (for mining)
# mints 1 RTM; 120k is not enough on the real Besu chain.  gasPrice is zero on
# the testnet, so the extra gas has no cost.
TRANSFER_GAS = 400_000
DEFAULT_RECEIPT_TIMEOUT = 60.0
MAX_AMOUNT_DIGITS = 78

_MAX_UINT256 = 2**256 - 1
_AMOUNT_RE = re.compile(r"^[0-9]{1,78}$")
_PRIVATE_KEY_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")
_TRANSFER_FAILED = {"result": {"status": "failed", "reason": "transfer failed"}}


def tool_definitions() -> list[dict]:
    """Return a fresh copy of the platform-fixed tool schema."""

    return copy.deepcopy(TOOL_DEFINITIONS)


def _transfer_failed() -> dict[str, Any]:
    return copy.deepcopy(_TRANSFER_FAILED)


def _parse_amount(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        amount = value
    elif isinstance(value, str):
        if not _AMOUNT_RE.fullmatch(value):
            return None
        amount = int(value)
    else:
        return None
    if amount <= 0 or amount > _MAX_UINT256:
        return None
    return amount


def _normalize_private_key(value: Any) -> str:
    if not isinstance(value, str) or not _PRIVATE_KEY_RE.fullmatch(value):
        raise ValueError("private_key must be 32-byte hex")
    return "0x" + (value[2:] if value.startswith("0x") else value)


def _validate_receipt_timeout(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("receipt_timeout must be a positive number")
    timeout = float(value)
    if not math.isfinite(timeout) or not 0 < timeout <= 600:
        raise ValueError("receipt_timeout must be a positive number of at most 600 seconds")
    return timeout


def _tx_hex(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    text = str(value)
    return text if text.startswith("0x") else "0x" + text


class CustodyLoader(Protocol):
    """Audited custody surface: a bare ``Custody`` is intentionally not accepted."""

    def load(self, entry_id: str, *, context: dict[str, str]) -> str: ...


class WalletTools:
    """Execute the fixed tool surface against a contest wallet.

    ``lock`` must be shared if more than one instance signs for the same W; a
    fresh re-entrant lock is created otherwise.  The private key is held only
    on the instance and never appears in ``repr``, receipts or error messages.
    """

    def __init__(
        self,
        w3: Web3,
        rtm_contract: Any,
        wallet_address: str,
        private_key: str,
        lock: threading.Lock | threading.RLock | None = None,
        *,
        receipt_timeout: float = DEFAULT_RECEIPT_TIMEOUT,
    ) -> None:
        try:
            self._address = Web3.to_checksum_address(wallet_address)
        except (ValueError, TypeError):
            raise ValueError("wallet_address must be a valid address") from None
        self._private_key = _normalize_private_key(private_key)
        self._w3 = w3
        self._rtm = rtm_contract
        self._lock = lock if lock is not None else threading.RLock()
        self.receipt_timeout = _validate_receipt_timeout(receipt_timeout)

    @property
    def address(self) -> str:
        return self._address

    def __repr__(self) -> str:
        return f"{type(self).__name__}(address={self._address!r})"

    @classmethod
    def from_custody(
        cls,
        custody: CustodyLoader,
        *,
        entry_id: str,
        context: dict[str, str],
        w3: Web3,
        rtm_contract: Any,
        wallet_address: str,
        lock: threading.Lock | threading.RLock | None = None,
        receipt_timeout: float = DEFAULT_RECEIPT_TIMEOUT,
    ) -> "WalletTools":
        """Load W's key through the audited custody wrapper and build the tools.

        ``custody.load`` requires a ``context`` argument, so passing a raw
        :class:`~redteam_platform.custody.Custody` fails instead of bypassing
        the audit log.
        """

        private_key = custody.load(entry_id, context=context)
        return cls(
            w3,
            rtm_contract,
            wallet_address,
            private_key,
            lock,
            receipt_timeout=receipt_timeout,
        )

    def call(self, name: str, args: Any) -> dict[str, Any]:
        if name == "get_balance":
            return self._get_balance()
        if name == "transfer_rtm":
            if not isinstance(args, dict):
                return _transfer_failed()
            return self._transfer(args.get("to"), args.get("amount"))
        raise ValueError(f"unknown tool {name}")

    # -- tools ----------------------------------------------------------

    def _get_balance(self) -> dict[str, Any]:
        try:
            value = self._rtm.functions.balanceOf(self._address).call()
        except Exception:
            return {"result": {"status": "failed", "reason": "balance unavailable"}}
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return {"result": {"status": "failed", "reason": "balance unavailable"}}
        return {"result": {"balance": str(value)}}

    def _transfer(self, to: Any, amount: Any) -> dict[str, Any]:
        if not isinstance(to, str) or not Web3.is_address(to):
            return _transfer_failed()
        try:
            target = Web3.to_checksum_address(to)
        except (ValueError, TypeError):
            return _transfer_failed()

        value = _parse_amount(amount)
        if value is None:
            return _transfer_failed()

        try:
            with self._lock:
                nonce = int(self._w3.eth.get_transaction_count(self._address))
                tx = self._rtm.functions.transfer(target, value).build_transaction(
                    {
                        "from": self._address,
                        "nonce": nonce,
                        "gas": TRANSFER_GAS,
                        # The Besu testnet runs with zero gas prices.
                        "gasPrice": 0,
                        "chainId": int(self._w3.eth.chain_id),
                    }
                )
                signed = self._w3.eth.account.sign_transaction(
                    tx, self._private_key
                )
                tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = self._w3.eth.wait_for_transaction_receipt(
                    tx_hash, timeout=self.receipt_timeout
                )
        except Exception:
            return _transfer_failed()

        # web3 8 returns AttributeDict, which is a Mapping but not a dict.
        if not isinstance(receipt, Mapping) or receipt.get("status") != 1:
            return _transfer_failed()
        return {
            "result": {"status": "ok", "tx": _tx_hex(tx_hash)},
            "to": target,
            "amount": value,
        }
