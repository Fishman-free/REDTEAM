"""Wallet sidecar: policy enforcement around the fixed RTM tool surface.

The agent only receives the same generic ``transfer failed`` receipt for every
denial, matching ``redteam_platform.agent_tools``.  The driver keeps the
structured audit trail (decision reason, amount, target) for scoring, but the
audit never contains a private key.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from web3 import Web3

from .policy import PolicyDecision, PolicyOutcome, WalletPolicy

TRANSFER_FAILED: dict[str, Any] = {
    "result": {"status": "failed", "reason": "transfer failed"}
}
_AMOUNT_RE = re.compile(r"^[0-9]{1,78}$")
_MAX_UINT256 = 2**256 - 1


def parse_amount(value: Any) -> int | None:
    """Accept the same amount shapes as the fixed tool schema."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        amount = value
    elif isinstance(value, str) and _AMOUNT_RE.fullmatch(value):
        amount = int(value)
    else:
        return None
    if amount <= 0 or amount > _MAX_UINT256:
        return None
    return amount


class TransferExecutor(Protocol):
    """The subset of ``agent_tools.WalletTools`` used by the sidecar."""

    def call(self, name: str, args: Any) -> dict[str, Any]: ...


def _generic_failure() -> dict[str, Any]:
    return {"result": {"status": "failed", "reason": "transfer failed"}}


def _receipt_ok(receipt: Mapping[str, Any], to: str, amount: int) -> bool:
    result = receipt.get("result")
    return (
        isinstance(result, Mapping)
        and result.get("status") == "ok"
        and receipt.get("to") == to
        and receipt.get("amount") == amount
    )


@dataclass(frozen=True)
class WalletTransfer:
    """Internal result returned to the driver (not the agent)."""

    ok: bool
    reason: str
    agent_receipt: Mapping[str, Any]
    to: str | None = None
    amount: int | None = None
    tx: str | None = None
    confirmed: bool = False
    audit_index: int | None = None


@dataclass(frozen=True)
class SessionToken:
    token: str
    contest_id: str
    wallet: str


class WalletSession:
    """One contest wallet with an L3 policy and a monotonic audit trail."""

    def __init__(
        self,
        *,
        wallet_address: str,
        executor: TransferExecutor,
        policy: WalletPolicy,
        contest_id: str,
        now: Callable[[], int] | None = None,
        confirmer: Callable[[str, int], bool] | None = None,
    ) -> None:
        try:
            self.wallet_address = Web3.to_checksum_address(wallet_address)
        except (ValueError, TypeError):
            raise ValueError("wallet_address must be a valid address") from None
        if not isinstance(policy, WalletPolicy):
            raise ValueError("policy must be a WalletPolicy")
        if not isinstance(contest_id, str) or not contest_id:
            raise ValueError("contest_id is required")
        self._executor = executor
        self.policy = policy
        self.contest_id = contest_id
        self._now = now or (lambda: int(time.time()))
        self._confirmer = confirmer
        self._spent = 0
        self._audit: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    @property
    def spent(self) -> int:
        with self._lock:
            return self._spent

    def balance(self) -> int | None:
        try:
            receipt = self._executor.call("get_balance", {})
        except Exception:
            return None
        result = receipt.get("result") if isinstance(receipt, Mapping) else None
        if not isinstance(result, Mapping):
            return None
        try:
            value = int(result.get("balance", ""))
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None

    def transfer(self, to: str, amount: Any) -> WalletTransfer:
        """Authorize and execute; the agent sees only the generic receipt."""

        parsed = parse_amount(amount)
        if parsed is None:
            return self._record(
                WalletTransfer(
                    ok=False,
                    reason="invalid_amount",
                    agent_receipt=_generic_failure(),
                    to=_safe_address(to),
                )
            )
        amount = parsed
        with self._lock:
            outcome = self.policy.evaluate(
                to=to,
                amount=amount,
                spent=self._spent,
                now=self._now(),
            )
            confirmed = False
            if outcome.decision is PolicyDecision.CONFIRM:
                confirmed = self._confirm(to, amount)
                if confirmed:
                    outcome = self.policy.evaluate(
                        to=to,
                        amount=amount,
                        spent=self._spent,
                        now=self._now(),
                        confirmed=True,
                    )
                else:
                    outcome = PolicyOutcome(
                        PolicyDecision.DENY, "confirmation_rejected"
                    )
            if not outcome.allowed:
                return self._record(
                    WalletTransfer(
                        ok=False,
                        reason=outcome.reason,
                        agent_receipt=_generic_failure(),
                        to=_safe_address(to),
                        amount=amount if isinstance(amount, int) else None,
                        confirmed=confirmed,
                    )
                )

            try:
                receipt = self._executor.call(
                    "transfer_rtm", {"to": to, "amount": str(amount)}
                )
            except Exception:
                receipt = _generic_failure()
            ok = isinstance(receipt, Mapping) and _receipt_ok(
                receipt, Web3.to_checksum_address(to), amount
            )
            if not ok:
                return self._record(
                    WalletTransfer(
                        ok=False,
                        reason="transfer_failed",
                        agent_receipt=_generic_failure(),
                        to=Web3.to_checksum_address(to),
                        amount=amount,
                        confirmed=confirmed,
                    )
                )
            self._spent += amount
            result = receipt.get("result")
            tx = result.get("tx") if isinstance(result, Mapping) else None
            return self._record(
                WalletTransfer(
                    ok=True,
                    reason="ok",
                    agent_receipt=dict(receipt),
                    to=Web3.to_checksum_address(to),
                    amount=amount,
                    tx=tx if isinstance(tx, str) else None,
                    confirmed=confirmed,
                )
            )

    def audit(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in self._audit]

    # -- internal -------------------------------------------------------

    def _confirm(self, to: str, amount: int) -> bool:
        if self._confirmer is None:
            return False
        try:
            return self._confirmer(to, amount) is True
        except Exception:
            return False

    def _record(self, transfer: WalletTransfer) -> WalletTransfer:
        entry = {
            "index": len(self._audit),
            "at": self._now(),
            "ok": transfer.ok,
            "reason": transfer.reason,
            "to": transfer.to,
            "amount": transfer.amount,
            "tx": transfer.tx,
            "confirmed": transfer.confirmed,
        }
        self._audit.append(entry)
        return WalletTransfer(
            ok=transfer.ok,
            reason=transfer.reason,
            agent_receipt=transfer.agent_receipt,
            to=transfer.to,
            amount=transfer.amount,
            tx=transfer.tx,
            confirmed=transfer.confirmed,
            audit_index=entry["index"],
        )


def _safe_address(value: Any) -> str | None:
    try:
        return Web3.to_checksum_address(value)
    except (ValueError, TypeError):
        return None


class WalletRegistry:
    """Bearer tokens for the CVM-internal wallet MCP endpoint."""

    def __init__(self) -> None:
        self._sessions: dict[str, WalletSession] = {}
        self._tokens: dict[str, SessionToken] = {}
        self._lock = threading.RLock()

    def issue(self, session: WalletSession) -> SessionToken:
        token = secrets.token_urlsafe(32)
        record = SessionToken(
            token=token,
            contest_id=session.contest_id,
            wallet=session.wallet_address,
        )
        with self._lock:
            self._sessions[token] = session
            self._tokens[token] = record
        return record

    def resolve(self, token: str) -> WalletSession | None:
        if not isinstance(token, str):
            return None
        with self._lock:
            return self._sessions.get(token)

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)
            self._tokens.pop(token, None)
