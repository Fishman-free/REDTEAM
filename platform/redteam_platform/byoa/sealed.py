"""Defender bundle commitments, runtime measurements and attestation tiers.

Nothing here claims more than it can prove.  The local dstack simulator emits
``tier="simulated"``; hardware quotes require an external verifier and are
never accepted silently.  The platform records the raw quote so anyone can
re-verify it (spec §4).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data
from web3 import Web3

from .egress import EgressDeclaration
from .envelope import (
    attack_context,
    open_envelope,
    public_key,
    reply_context,
    seal,
)

SIMULATED = "simulated"
HARDWARE = "hardware"
TIERS = frozenset({SIMULATED, HARDWARE})
_BYTES32_RE = r"^0x[0-9a-fA-F]{64}$"


class AttestationError(ValueError):
    """Raised when a quote is malformed, unverifiable or tier-forged."""


class ManifestError(ValueError):
    """Raised when a defender bundle is missing public commitments."""


def canonical_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash32(payload: bytes) -> str:
    return "0x" + hashlib.sha256(payload).hexdigest()


def keccak_hex(payload: bytes) -> str:
    digest = Web3.keccak(payload).hex()
    return digest if digest.startswith("0x") else "0x" + digest


@dataclass(frozen=True)
class BundleManifest:
    """What the defender submits; only digests and declarations are public."""

    defender: str
    image_digest: str
    transport_kind: str
    transport_endpoint: str
    egress: EgressDeclaration
    policy_fingerprint: str
    attestation_tier: str
    runtime_measurement: str
    tee_pubkey: str

    def __post_init__(self) -> None:
        for name in ("image_digest", "runtime_measurement", "tee_pubkey"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ManifestError(f"{name} must be a hex string")
        if not self.image_digest.startswith("sha256:"):
            raise ManifestError("image_digest must use sha256:<hex>")
        for name in ("runtime_measurement", "tee_pubkey"):
            value = getattr(self, name)
            if not value.startswith("0x") or len(value) != 66:
                raise ManifestError(f"{name} must be a bytes32 hex string")
        if self.attestation_tier not in TIERS:
            raise ManifestError("attestation_tier must be simulated or hardware")
        if not isinstance(self.egress, EgressDeclaration):
            raise ManifestError("egress must be an EgressDeclaration")
        if not isinstance(self.policy_fingerprint, str) or not self.policy_fingerprint:
            raise ManifestError("policy_fingerprint is required")
        if not isinstance(self.transport_kind, str) or not self.transport_kind:
            raise ManifestError("transport_kind is required")

    def public_dict(self) -> dict[str, Any]:
        """Safe to show attackers and put on chain (no endpoint/secret)."""

        return {
            "defender": Web3.to_checksum_address(self.defender),
            "imageDigest": self.image_digest,
            "transport": self.transport_kind,
            "egress": self.egress.as_public_dict(),
            "policyFingerprint": self.policy_fingerprint,
            "attestationTier": self.attestation_tier,
            "runtimeMeasurement": self.runtime_measurement,
            "teePubKey": self.tee_pubkey,
        }

    def commitment_dict(self) -> dict[str, Any]:
        """Full commitment, including the private transport endpoint."""

        return {**self.public_dict(), "transportEndpoint": self.transport_endpoint}

    def commitment(self) -> str:
        """bytes32 config commitment stored in Arena's defenseHash slot."""

        return keccak_hex(canonical_json(self.commitment_dict()).encode("utf-8"))


def compute_measurement(files: Mapping[str, str | bytes]) -> str:
    """Deterministic stand-in for dstack's ``compose_hash``.

    Each file contributes ``name\\0sha256(content)\\n``; the digest is a
    bytes32-compatible hex string.
    """

    if not isinstance(files, Mapping) or not files:
        raise ManifestError("measurement requires at least one file")
    lines: list[bytes] = []
    for name in sorted(files):
        content = files[name]
        if isinstance(content, str):
            data = content.encode("utf-8")
        elif isinstance(content, bytes):
            data = content
        else:
            raise ManifestError("measurement files must be str or bytes")
        lines.append(name.encode("utf-8") + b"\0" + hashlib.sha256(data).digest() + b"\n")
    return _hash32(b"".join(lines))


@dataclass(frozen=True)
class Attestation:
    tier: str
    measurement: str
    tee_pubkey: str
    tee_signer: str
    quote: str
    issued_at: int

    def __post_init__(self) -> None:
        if self.tier not in TIERS:
            raise AttestationError("unknown attestation tier")
        if not isinstance(self.measurement, str) or not self.measurement.startswith("0x"):
            raise AttestationError("measurement must be bytes32 hex")
        if not isinstance(self.tee_pubkey, str) or not self.tee_pubkey.startswith("0x"):
            raise AttestationError("tee_pubkey must be bytes32 hex")
        if not isinstance(self.quote, str) or not self.quote:
            raise AttestationError("quote is required")

    def payload(self) -> str:
        return canonical_json(
            {
                "tier": self.tier,
                "measurement": self.measurement,
                "teePubKey": self.tee_pubkey,
                "teeSigner": Web3.to_checksum_address(self.tee_signer),
                "issuedAt": int(self.issued_at),
                "domain": "RTM BYOA ATTESTATION v1",
            }
        )


def simulated_attestation(
    *,
    measurement: str,
    tee_pubkey: str,
    tee_signer_key: str,
    issued_at: int,
) -> Attestation:
    """Sign a labelled simulator quote; this proves flow, not confidentiality."""

    account = Account.from_key(tee_signer_key)
    unsigned = Attestation(
        tier=SIMULATED,
        measurement=measurement,
        tee_pubkey=tee_pubkey,
        tee_signer=account.address,
        quote="pending",
        issued_at=issued_at,
    )
    signature = Account.sign_message(
        encode_defunct(text=unsigned.payload()), private_key=tee_signer_key
    ).signature.to_0x_hex()
    return Attestation(
        tier=unsigned.tier,
        measurement=unsigned.measurement,
        tee_pubkey=unsigned.tee_pubkey,
        tee_signer=unsigned.tee_signer,
        quote=signature,
        issued_at=unsigned.issued_at,
    )


def verify_attestation(
    attestation: Attestation,
    *,
    expected_measurement: str | None = None,
    hardware_verifier: Callable[[Attestation], bool] | None = None,
) -> str:
    """Return the verified tier or raise :class:`AttestationError`.

    Simulated quotes are only checked for signatures; callers must surface
    the returned tier in the UI.  Hardware quotes without a configured vendor
    verifier are rejected rather than trusted.
    """

    if not isinstance(attestation, Attestation):
        raise AttestationError("attestation must be an Attestation")
    if expected_measurement is not None and attestation.measurement != expected_measurement:
        raise AttestationError("attestation measurement does not match the bundle")
    if attestation.tier == HARDWARE:
        if hardware_verifier is None:
            raise AttestationError("hardware quote verifier is not configured")
        if hardware_verifier(attestation) is not True:
            raise AttestationError("hardware quote was rejected")
        return HARDWARE

    try:
        recovered = Account.recover_message(
            encode_defunct(text=attestation.payload()), signature=attestation.quote
        )
    except Exception:
        raise AttestationError("simulated quote signature is invalid") from None
    if recovered != Web3.to_checksum_address(attestation.tee_signer):
        raise AttestationError("simulated quote signer mismatch")
    return SIMULATED


class SimulatedSealedRuntime:
    """Local dstack stand-in: W and the TEE signer live in one sealed object.

    The platform only receives the W address, the TEE address and public
    commitments.  This is *not* a confidentiality boundary; it exists so the
    whole flow (signatures, policy, task consumption) can be exercised without
    hardware.  The UI must label it ``simulated``.
    """

    def __init__(self) -> None:
        self._wallet_key = Account.create().key.to_0x_hex()
        self._tee_key = Account.create().key.to_0x_hex()
        self._tee_account = Account.from_key(self._tee_key)
        self._wallet_address = Account.from_key(self._wallet_key).address
        self._x25519_private = X25519PrivateKey.generate().private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self.tee_pubkey = "0x" + public_key(self._x25519_private).hex()

    @property
    def wallet_address(self) -> str:
        return self._wallet_address

    @property
    def tee_signer(self) -> str:
        return self._tee_account.address

    def attest(self, *, measurement: str, issued_at: int) -> Attestation:
        return simulated_attestation(
            measurement=measurement,
            tee_pubkey=self.tee_pubkey,
            tee_signer_key=self._tee_key,
            issued_at=issued_at,
        )

    def sign_typed_data(
        self,
        *,
        domain: Mapping[str, Any],
        types: Mapping[str, Any],
        primary_type: str,
        message: Mapping[str, Any],
    ) -> str:
        """Sign the on-chain BYOA binding; the key never leaves this object."""

        full = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                **dict(types),
            },
            "primaryType": primary_type,
            "domain": dict(domain),
            "message": dict(message),
        }
        signable = encode_typed_data(full_message=full)
        return Account.sign_message(
            signable, private_key=self._tee_key
        ).signature.to_0x_hex()

    def open_attack(
        self,
        envelope: Mapping[str, Any],
        *,
        contest_id: str,
        attacker: str,
    ) -> str:
        plaintext = open_envelope(
            self._x25519_private,
            envelope,
            context=attack_context(contest_id, attacker),
        )
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError:
            raise AttestationError("attack plaintext is not UTF-8") from None

    def seal_reply(
        self,
        recipient_public: str,
        plaintext: str,
        *,
        contest_id: str,
        attacker: str,
        msg_hash: str,
        seq: int,
    ) -> dict[str, Any]:
        return seal(
            recipient_public,
            plaintext.encode("utf-8"),
            context=reply_context(contest_id, attacker, msg_hash, seq),
        )

    def sign_reply(
        self,
        *,
        contest_id: str,
        attacker: str,
        msg_hash: str,
        reply_hash: str,
        seq: int,
    ) -> str:
        payload = reply_signature_payload(
            contest_id=contest_id,
            attacker=attacker,
            msg_hash=msg_hash,
            reply_hash=reply_hash,
            seq=seq,
        )
        return Account.sign_message(
            encode_defunct(text=payload), private_key=self._tee_key
        ).signature.to_0x_hex()

    def wallet_key_for_tools(self) -> str:
        """Only the in-CVM wallet sidecar may call this.

        It is named explicitly so code review can catch accidental use in the
        platform API; the simulator has no hardware boundary.
        """

        return self._wallet_key


def reply_signature_payload(
    *,
    contest_id: str,
    attacker: str,
    msg_hash: str,
    reply_hash: str,
    seq: int,
) -> str:
    return (
        "RTM BYOA reply v1\n"
        f"contest: {contest_id}\n"
        f"attacker: {Web3.to_checksum_address(attacker)}\n"
        f"msgHash: {msg_hash.lower()}\n"
        f"replyHash: {reply_hash.lower()}\n"
        f"seq: {int(seq)}"
    )


def verify_reply_signature(
    signature: str,
    *,
    tee_signer: str,
    contest_id: str,
    attacker: str,
    msg_hash: str,
    reply_hash: str,
    seq: int,
) -> bool:
    try:
        recovered = Account.recover_message(
            encode_defunct(
                text=reply_signature_payload(
                    contest_id=contest_id,
                    attacker=attacker,
                    msg_hash=msg_hash,
                    reply_hash=reply_hash,
                    seq=seq,
                )
            ),
            signature=signature,
        )
    except Exception:
        return False
    return recovered == Web3.to_checksum_address(tee_signer)
