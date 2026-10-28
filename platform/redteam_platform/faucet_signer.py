"""EIP-712 tickets for :class:`contracts/src/Faucet.sol` (task 14).

The platform signs a ``Ticket(address to,uint256 nonce,uint64 deadline)``
struct under the domain ``("RTM Faucet", "1", chainId, faucet address)``.
The signer key is loaded from the audited custody wrapper for every ticket
and never retained on the instance.  Nonces are strictly increasing per
recipient: the signer combines the on-chain ``Faucet.nonces(to)`` with an
in-process highest-issued counter; callers may pass an explicit nonce when a
persistent store already guarantees monotonicity.

Captcha policy: when ``captcha_required=True`` a ``captcha_verifier`` must be
supplied at construction, and every ``sign`` call must pass a token that the
verifier accepts.  Development may set ``captcha_required=False`` explicitly.

Limitations (v1): the in-process nonce counter does not survive restarts or
coordinate multiple signer processes.  A restarted/multi-process issuer can
re-issue an unclaimed nonce; the Faucet's strict nonce check still prevents a
double claim, but the second ticket becomes unusable.  Task 15/ops should run
a single signer process or add a persistent nonce store.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

DOMAIN_NAME = "RTM Faucet"
DOMAIN_VERSION = "1"
TICKET_TYPE = (
    {"name": "to", "type": "address"},
    {"name": "nonce", "type": "uint256"},
    {"name": "deadline", "type": "uint64"},
)
TICKET_TYPEHASH_TEXT = "Ticket(address to,uint256 nonce,uint64 deadline)"
TICKET_TYPEHASH = Web3.to_hex(Web3.keccak(text=TICKET_TYPEHASH_TEXT))
DEFAULT_TICKET_TTL = 600
MAX_TICKET_TTL = 3600
MAX_ENTRY_TEXT = 256


class FaucetSignerError(RuntimeError):
    """Raised when a ticket cannot be signed (no secret is ever included)."""


class AuditedCustodyPort(Protocol):
    def load(self, entry_id: str, *, context: dict[str, str]) -> str: ...


@dataclass(frozen=True)
class SignedTicket:
    to: str
    nonce: int
    deadline: int
    signature: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "to": self.to,
            "nonce": self.nonce,
            "deadline": self.deadline,
            "signature": self.signature,
        }


def _require_visible(value: Any, field: str, *, maximum: int = MAX_ENTRY_TEXT) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise FaucetSignerError(f"{field} must be a non-empty string of at most {maximum} characters")
    if any(not 0x20 <= ord(character) <= 0x7E for character in value):
        raise FaucetSignerError(f"{field} must contain only visible ASCII characters")
    return value


def _require_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FaucetSignerError(f"{field} must be an integer >= {minimum}")
    return value


def _require_address(value: Any, field: str) -> str:
    try:
        address = Web3.to_checksum_address(value)
    except (ValueError, TypeError):
        raise FaucetSignerError(f"{field} must be a valid address") from None
    if int(address, 16) == 0:
        raise FaucetSignerError(f"{field} must not be the zero address")
    return address


class FaucetSigner:
    """Sign Faucet tickets while auditing every custody access."""

    def __init__(
        self,
        *,
        custody: AuditedCustodyPort,
        signer_entry: str,
        faucet_address: str,
        chain_id: int,
        nonce_lookup: Callable[[str], int],
        captcha_required: bool = False,
        captcha_verifier: Callable[[str], bool] | None = None,
        expected_signer: str | None = None,
        ticket_ttl: int = DEFAULT_TICKET_TTL,
        max_ttl: int = MAX_TICKET_TTL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.signer_entry = _require_visible(signer_entry, "signer_entry")
        self.faucet_address = _require_address(faucet_address, "faucet_address")
        self.chain_id = _require_int(chain_id, "chain_id", minimum=1)
        if not callable(nonce_lookup):
            raise FaucetSignerError("nonce_lookup must be callable")
        self._nonce_lookup = nonce_lookup
        if not isinstance(captcha_required, bool):
            raise FaucetSignerError("captcha_required must be a boolean")
        if captcha_required and not callable(captcha_verifier):
            raise FaucetSignerError(
                "captcha_required=True needs a captcha_verifier at startup"
            )
        if captcha_verifier is not None and not callable(captcha_verifier):
            raise FaucetSignerError("captcha_verifier must be callable")
        self.captcha_required = captcha_required
        self._captcha_verifier = captcha_verifier
        self.expected_signer = (
            None if expected_signer is None else _require_address(expected_signer, "expected_signer")
        )
        ttl = _require_int(ticket_ttl, "ticket_ttl", minimum=1)
        ceiling = _require_int(max_ttl, "max_ttl", minimum=1)
        if ttl > ceiling:
            raise FaucetSignerError("ticket_ttl must not exceed max_ttl")
        self.ticket_ttl = ttl
        self.max_ttl = ceiling
        if not callable(clock):
            raise FaucetSignerError("clock must be callable")
        self._clock = clock
        self._custody = custody
        self._last_issued: dict[str, int] = {}
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(faucet_address={self.faucet_address!r}, "
            f"chain_id={self.chain_id})"
        )

    # -- typed data -----------------------------------------------------

    def build_typed_data(self, to: str, nonce: int, deadline: int) -> dict[str, Any]:
        recipient = _require_address(to, "to")
        nonce = _require_int(nonce, "nonce", minimum=1)
        deadline = _require_int(deadline, "deadline", minimum=0)
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Ticket": [dict(field) for field in TICKET_TYPE],
            },
            "primaryType": "Ticket",
            "domain": {
                "name": DOMAIN_NAME,
                "version": DOMAIN_VERSION,
                "chainId": self.chain_id,
                "verifyingContract": self.faucet_address,
            },
            "message": {
                "to": recipient,
                "nonce": nonce,
                "deadline": deadline,
            },
        }

    # -- signing --------------------------------------------------------

    def sign(
        self,
        to: str,
        *,
        captcha_token: str | None = None,
        nonce: int | None = None,
        deadline: int | None = None,
    ) -> SignedTicket:
        recipient = _require_address(to, "to")
        self._verify_captcha(captcha_token)

        now = int(self._clock())
        if deadline is None:
            deadline = now + self.ticket_ttl
        deadline = _require_int(deadline, "deadline", minimum=0)
        if not now < deadline <= now + self.max_ttl:
            raise FaucetSignerError(
                "deadline must be in the future and within max_ttl seconds"
            )

        try:
            on_chain = self._nonce_lookup(recipient)
        except Exception:
            raise FaucetSignerError("nonce lookup failed") from None
        on_chain = _require_int(on_chain, "on-chain nonce", minimum=0)

        with self._lock:
            last = self._last_issued.get(recipient, 0)
            base = max(on_chain, last)
            chosen = base + 1 if nonce is None else _require_int(nonce, "nonce", minimum=1)
            if chosen <= base:
                raise FaucetSignerError("nonce must exceed the last issued/on-chain nonce")
            self._last_issued[recipient] = chosen

        context = {
            "purpose": "faucet_ticket",
            "recipient": recipient,
            "chain_id": str(self.chain_id),
            "ticket_count": "1",
        }
        try:
            private_key = self._custody.load(self.signer_entry, context=context)
        except Exception:
            raise FaucetSignerError("faucet signer key unavailable") from None

        try:
            account = Account.from_key(private_key)
        except Exception:
            # Never chain the original exception: it may echo key material.
            raise FaucetSignerError("faucet signer key is invalid") from None
        if self.expected_signer is not None and account.address != self.expected_signer:
            raise FaucetSignerError("faucet signer key does not match expected_signer")

        typed_data = self.build_typed_data(recipient, chosen, deadline)
        try:
            signed = Account.sign_typed_data(private_key, full_message=typed_data)
            signature = Web3.to_hex(signed.signature)
        except Exception:
            raise FaucetSignerError("faucet ticket signing failed") from None

        return SignedTicket(
            to=recipient,
            nonce=chosen,
            deadline=deadline,
            signature=signature,
        )

    def _verify_captcha(self, token: str | None) -> None:
        if not self.captcha_required:
            return
        if not isinstance(token, str) or not token.strip():
            raise FaucetSignerError("captcha token required")
        try:
            accepted = self._captcha_verifier(token)
        except Exception:
            raise FaucetSignerError("captcha verification failed") from None
        if accepted is not True:
            raise FaucetSignerError("captcha verification failed")


def recover_ticket_signer(typed_data: dict[str, Any], signature: str) -> str:
    """Test/verification helper mirroring the Faucet's EIP-712 recovery."""

    try:
        signable = encode_typed_data(full_message=typed_data)
        return Account.recover_message(signable, signature=signature)
    except Exception:
        raise FaucetSignerError("ticket signature cannot be recovered") from None
