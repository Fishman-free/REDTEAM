"""Signed faucet claims that the platform submits on the correct chain.

The faucet UI asks the player's wallet to sign a short, human-readable claim
message.  The signature proves address ownership without requiring the wallet
to broadcast a transaction, so a stale wallet RPC can never send the claim to a
different local chain.  The platform verifies the signature, enforces a
persistent per-address cooldown, and mints the test tokens from the operator
account on the chain used by this deployment.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct

CLAIM_PREFIX = "RTM Arena testnet faucet claim"
CLAIM_TTL_SECONDS = 300
CLAIM_CLOCK_SKEW_SECONDS = 30
DEFAULT_COOLDOWN_SECONDS = 24 * 60 * 60


class FaucetRelayError(RuntimeError):
    """Raised when a relayed faucet claim is invalid or unavailable."""


def claim_message(to: str, issued_at: int, nonce: str) -> str:
    if not isinstance(to, str) or not to:
        raise FaucetRelayError("claim address is required")
    if isinstance(issued_at, bool) or not isinstance(issued_at, int) or issued_at < 0:
        raise FaucetRelayError("claim issue time is invalid")
    if not isinstance(nonce, str) or len(nonce) != 66 or not nonce.startswith("0x"):
        raise FaucetRelayError("claim nonce is invalid")
    return (
        f"{CLAIM_PREFIX}\n"
        f"address: {to.lower()}\n"
        f"issued-at: {issued_at}\n"
        f"nonce: {nonce.lower()}"
    )


def recover_claim_signer(to: str, issued_at: int, nonce: str, signature: str) -> str:
    """Recover the wallet address that signed a faucet claim message."""
    if not isinstance(signature, str) or not signature.startswith("0x"):
        raise FaucetRelayError("claim signature is invalid")
    message = claim_message(to, issued_at, nonce)
    try:
        signer = Account.recover_message(encode_defunct(text=message), signature=signature)
    except Exception:
        raise FaucetRelayError("claim signature cannot be recovered") from None
    return signer


class FaucetClaimStore:
    """Persistent cooldown and nonce replay protection for relayed claims."""

    def __init__(
        self,
        path: Path,
        *,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
        ttl_seconds: int = CLAIM_TTL_SECONDS,
        clock: Any = time.time,
    ) -> None:
        self.path = Path(path)
        self.cooldown_seconds = int(cooldown_seconds)
        self.ttl_seconds = int(ttl_seconds)
        self._clock = clock
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connect().close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS claims ("
            "address TEXT PRIMARY KEY, claimed_at INTEGER NOT NULL, tx_hash TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS nonces ("
            "nonce TEXT PRIMARY KEY, address TEXT NOT NULL, used_at INTEGER NOT NULL)"
        )
        connection.commit()
        return connection

    @staticmethod
    def _validate_address(address: str) -> str:
        if not isinstance(address, str) or len(address) != 42 or not address.startswith("0x"):
            raise FaucetRelayError("claim address is invalid")
        return address.lower()

    def validate_issued_at(self, issued_at: int, now: int | None = None) -> None:
        current = int(self._clock() if now is None else now)
        if issued_at < current - self.ttl_seconds:
            raise FaucetRelayError("claim signature expired")
        if issued_at > current + CLAIM_CLOCK_SKEW_SECONDS:
            raise FaucetRelayError("claim issue time is in the future")

    def cooldown_remaining(self, address: str, now: int | None = None) -> int:
        normalized = self._validate_address(address)
        current = int(self._clock() if now is None else now)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT claimed_at FROM claims WHERE address = ?", (normalized,)
            ).fetchone()
        if row is None:
            return 0
        elapsed = max(0, current - int(row[0]))
        return max(0, self.cooldown_seconds - elapsed)

    def reserve(self, address: str, nonce: str, now: int | None = None) -> None:
        """Atomically enforce cooldown + one-time nonce before any transaction."""
        normalized = self._validate_address(address)
        normalized_nonce = nonce.lower()
        current = int(self._clock() if now is None else now)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT claimed_at FROM claims WHERE address = ?", (normalized,)
                ).fetchone()
                if row is not None:
                    elapsed = max(0, current - int(row[0]))
                    remaining = max(0, self.cooldown_seconds - elapsed)
                    if remaining > 0:
                        raise FaucetRelayError(f"faucet cooldown active: {remaining} seconds")
                try:
                    connection.execute(
                        "INSERT INTO nonces (nonce, address, used_at) VALUES (?, ?, ?)",
                        (normalized_nonce, normalized, current),
                    )
                except sqlite3.IntegrityError:
                    raise FaucetRelayError("claim signature was already used") from None
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def release_nonce(self, nonce: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM nonces WHERE nonce = ?", (nonce.lower(),))
            connection.commit()

    def record_claim(self, address: str, tx_hash: str, now: int | None = None) -> None:
        normalized = self._validate_address(address)
        claimed_at = int(self._clock() if now is None else now)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO claims (address, claimed_at, tx_hash) VALUES (?, ?, ?) "
                "ON CONFLICT(address) DO UPDATE SET claimed_at = excluded.claimed_at, "
                "tx_hash = excluded.tx_hash",
                (normalized, claimed_at, tx_hash),
            )
            connection.commit()
