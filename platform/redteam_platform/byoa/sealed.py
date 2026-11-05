"""Defender bundle commitments, runtime measurements and attestation tiers.

Nothing here claims more than it can prove.  The local dstack simulator emits
``tier="simulated"``; hardware quotes require an external verifier and are
never accepted silently.  The platform records the raw quote so anyone can
re-verify it (spec §4).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
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
SOFTTEE = "softtee"
SELF_HOSTED = "self-hosted"
TIERS = frozenset({SIMULATED, SOFTTEE, SELF_HOSTED})
# Backwards-compatible alias for older imports; hardware is no longer a tier.
HARDWARE = SOFTTEE
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
    config_hash: str = ""

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
        if self.config_hash and (
            not self.config_hash.startswith("0x") or len(self.config_hash) != 66
        ):
            raise ManifestError("config_hash must be a bytes32 hex string")
        if self.attestation_tier not in TIERS:
            raise ManifestError("attestation_tier must be simulated, softtee or self-hosted")
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
            "configHash": self.config_hash,
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


SOFTTEE_RUNTIME_FILES = (
    "byoa/__init__.py",
    "byoa/adapters.py",
    "byoa/egress.py",
    "byoa/envelope.py",
    "byoa/model_agent.py",
    "byoa/models.py",
    "byoa/policy.py",
    "byoa/runtime.py",
    "byoa/sealed.py",
    "byoa/service.py",
    "byoa/tasks.py",
    "byoa/wallet.py",
    "byoa/wallet_mcp.py",
    "signatures.py",
)


def softtee_measurement() -> tuple[str, int]:
    """Measure the SoftTEE runtime files shipped in this image.

    Returns ``(measurement, file_count)``.  The platform can recompute this
    from its own image and reject a driver whose attestation differs.
    """

    base = Path(__file__).resolve().parents[1]
    files: dict[str, bytes] = {}
    for relative in SOFTTEE_RUNTIME_FILES:
        path = base / relative
        if not path.exists():
            raise ManifestError(f"SoftTEE runtime file is missing: {relative}")
        files[relative] = path.read_bytes()
    return compute_measurement(files), len(files)


@dataclass(frozen=True)
class Attestation:
    tier: str
    measurement: str
    tee_pubkey: str
    tee_signer: str
    quote: str
    issued_at: int
    config_commitment: str = "0x" + "00" * 32
    root_of_trust: str = "software"
    tpm_rooted: bool = False
    tpm_quote: str | None = None
    runtime: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.tier not in TIERS:
            raise AttestationError("unknown attestation tier")
        for name in ("measurement", "tee_pubkey", "config_commitment"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.startswith("0x") or len(value) != 66:
                raise AttestationError(f"{name} must be bytes32 hex")
        if not isinstance(self.quote, str) or not self.quote:
            raise AttestationError("quote is required")
        if self.tpm_rooted and not self.tpm_quote:
            raise AttestationError("tpmRooted attestation requires a tpmQuote")

    def payload(self) -> str:
        return canonical_json(
            {
                "domain": "RTM BYOA SOFTTEE ATTESTATION v2",
                "tier": self.tier,
                "measurement": self.measurement,
                "configCommitment": self.config_commitment,
                "teePubKey": self.tee_pubkey,
                "teeSigner": Web3.to_checksum_address(self.tee_signer),
                "runtime": dict(self.runtime),
                "rootOfTrust": self.root_of_trust,
                "tpmRooted": bool(self.tpm_rooted),
                "tpmQuote": self.tpm_quote,
                "issuedAt": int(self.issued_at),
            }
        )


def config_commitment(config: Mapping[str, Any]) -> str:
    """Canonical commitment to a defender configuration bundle."""

    if not isinstance(config, Mapping):
        raise ManifestError("config must be a mapping")
    return keccak_hex(canonical_json(dict(config)).encode("utf-8"))


def simulated_attestation(
    *,
    measurement: str,
    tee_pubkey: str,
    tee_signer_key: str,
    issued_at: int,
    config_commitment_hex: str = "0x" + "00" * 32,
    tier: str = SIMULATED,
    runtime: Mapping[str, Any] | None = None,
    tpm_rooted: bool = False,
    tpm_quote: str | None = None,
) -> Attestation:
    """Sign a software attestation statement; it proves integrity, not hardware."""

    account = Account.from_key(tee_signer_key)
    unsigned = Attestation(
        tier=tier,
        measurement=measurement,
        tee_pubkey=tee_pubkey,
        tee_signer=account.address,
        quote="pending",
        issued_at=issued_at,
        config_commitment=config_commitment_hex,
        root_of_trust="tpm" if tpm_rooted else "software",
        tpm_rooted=tpm_rooted,
        tpm_quote=tpm_quote,
        runtime=dict(runtime or {}),
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
        config_commitment=unsigned.config_commitment,
        root_of_trust=unsigned.root_of_trust,
        tpm_rooted=unsigned.tpm_rooted,
        tpm_quote=unsigned.tpm_quote,
        runtime=unsigned.runtime,
    )


def verify_attestation(
    attestation: Attestation,
    *,
    expected_measurement: str | None = None,
    expected_config_commitment: str | None = None,
    hardware_verifier: Callable[[Attestation], bool] | None = None,
) -> str:
    """Return the verified tier or raise :class:`AttestationError`.

    ``hardware_verifier`` is retained for call-site compatibility but no
    hardware tier exists. SoftTEE is fail-closed: measurement and config
    commitment must match, the statement signature must verify, and a
    ``tpmRooted=true`` claim must carry a quote.
    """

    if not isinstance(attestation, Attestation):
        raise AttestationError("attestation must be an Attestation")
    if expected_measurement is not None and attestation.measurement != expected_measurement:
        raise AttestationError("attestation measurement does not match the bundle")
    if (
        expected_config_commitment is not None
        and attestation.config_commitment != expected_config_commitment
    ):
        raise AttestationError("attestation config commitment does not match the bundle")
    if attestation.tier == SELF_HOSTED:
        raise AttestationError("self-hosted bundles do not carry a runtime attestation")
    if attestation.tier == SOFTTEE and hardware_verifier is not None:
        # A caller-provided verifier may add a host-specific check, but we
        # never accept it in place of the built-in signature/measurement checks.
        if hardware_verifier(attestation) is not True:
            raise AttestationError("softtee verifier rejected the attestation")

    try:
        recovered = Account.recover_message(
            encode_defunct(text=attestation.payload()), signature=attestation.quote
        )
    except Exception:
        raise AttestationError("attestation signature is invalid") from None
    if recovered != Web3.to_checksum_address(attestation.tee_signer):
        raise AttestationError("attestation signer mismatch")
    return attestation.tier


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
        config_hash: str | None = None,
    ) -> str:
        payload = (
            reply_signature_payload_v2(
                contest_id=contest_id,
                attacker=attacker,
                msg_hash=msg_hash,
                reply_hash=reply_hash,
                seq=seq,
                config_hash=config_hash,
            )
            if config_hash
            else reply_signature_payload(
                contest_id=contest_id,
                attacker=attacker,
                msg_hash=msg_hash,
                reply_hash=reply_hash,
                seq=seq,
            )
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


class SoftteeSealedRuntime:
    """Measurement-bound software sealed runtime.

    Keys live in an AES-256-GCM keystore whose key is derived from
    ``HKDF(host_secret, measurement)``.  Changing the runtime measurement
    makes the keystore undecryptable, so a restart with modified code cannot
    silently keep signing with the old identity.  This is software isolation,
    not a hardware TEE: a host root can read process memory.
    """

    KEYSTORE_VERSION = 1
    KEYSTORE_INFO = b"RTM BYOA SOFTTEE KEYSTORE v2"

    def __init__(
        self,
        *,
        host_secret: bytes | str,
        state_path: str | Path,
        measurement: str,
        tpm_rooted: bool = False,
        tpm_quote: str | None = None,
    ) -> None:
        if isinstance(host_secret, str):
            secret = host_secret.encode("utf-8")
        elif isinstance(host_secret, (bytes, bytearray)):
            secret = bytes(host_secret)
        else:
            raise ValueError("host_secret must be bytes or a string")
        if len(secret) < 32:
            raise ValueError("host_secret must be at least 32 bytes")
        if not isinstance(measurement, str) or not measurement.startswith("0x"):
            raise ValueError("measurement must be bytes32 hex")
        self._secret = secret
        self._measurement = measurement
        self._state_path = Path(state_path)
        self._tpm_rooted = bool(tpm_rooted)
        self._tpm_quote = tpm_quote
        self._lock = threading.RLock()
        self._load_or_create()

    @property
    def wallet_address(self) -> str:
        return self._wallet_address

    @property
    def tee_signer(self) -> str:
        return self._tee_account.address

    @property
    def measurement(self) -> str:
        return self._measurement

    def _keystore_key(self) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._measurement.encode("utf-8"),
            info=self.KEYSTORE_INFO,
        ).derive(self._secret)

    def _load_or_create(self) -> None:
        with self._lock:
            if self._state_path.exists():
                try:
                    envelope = json.loads(
                        self._state_path.read_text(encoding="utf-8")
                    )
                    nonce = bytes.fromhex(str(envelope["nonce"]))
                    ciphertext = bytes.fromhex(str(envelope["ciphertext"]))
                    plaintext = AESGCM(self._keystore_key()).decrypt(
                        nonce, ciphertext, self._measurement.encode("utf-8")
                    )
                    payload = json.loads(plaintext.decode("utf-8"))
                except Exception:
                    raise AttestationError(
                        "softtee keystore cannot be opened with this measurement"
                    ) from None
                self._wallet_key = str(payload["walletKey"])
                self._tee_key = str(payload["teeKey"])
                x25519_hex = str(payload["x25519Key"])
            else:
                self._wallet_key = Account.create().key.to_0x_hex()
                self._tee_key = Account.create().key.to_0x_hex()
                x25519_hex = X25519PrivateKey.generate().private_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PrivateFormat.Raw,
                    encryption_algorithm=serialization.NoEncryption(),
                ).hex()
                payload = {
                    "version": self.KEYSTORE_VERSION,
                    "measurement": self._measurement,
                    "walletKey": self._wallet_key,
                    "teeKey": self._tee_key,
                    "x25519Key": x25519_hex,
                }
                nonce = os.urandom(12)
                ciphertext = AESGCM(self._keystore_key()).encrypt(
                    nonce,
                    json.dumps(payload, sort_keys=True).encode("utf-8"),
                    self._measurement.encode("utf-8"),
                )
                envelope = {
                    "version": self.KEYSTORE_VERSION,
                    "nonce": nonce.hex(),
                    "ciphertext": ciphertext.hex(),
                }
                self._state_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._state_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass
                os.replace(tmp, self._state_path)
            self._tee_account = Account.from_key(self._tee_key)
            self._wallet_address = Account.from_key(self._wallet_key).address
            self._x25519_private = bytes.fromhex(x25519_hex)
            self.tee_pubkey = "0x" + public_key(self._x25519_private).hex()

    def attest(
        self,
        *,
        measurement: str,
        issued_at: int,
        config_commitment_hex: str,
        runtime: Mapping[str, Any] | None = None,
    ) -> Attestation:
        if measurement != self._measurement:
            raise AttestationError("measurement changed; refusing to attest")
        return simulated_attestation(
            measurement=measurement,
            tee_pubkey=self.tee_pubkey,
            tee_signer_key=self._tee_key,
            issued_at=issued_at,
            config_commitment_hex=config_commitment_hex,
            tier=SOFTTEE,
            runtime=dict(runtime or {}),
            tpm_rooted=self._tpm_rooted,
            tpm_quote=self._tpm_quote,
        )

    def sign_typed_data(
        self,
        *,
        domain: Mapping[str, Any],
        types: Mapping[str, Any],
        primary_type: str,
        message: Mapping[str, Any],
    ) -> str:
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
        config_hash: str,
    ) -> str:
        payload = reply_signature_payload_v2(
            contest_id=contest_id,
            attacker=attacker,
            msg_hash=msg_hash,
            reply_hash=reply_hash,
            seq=seq,
            config_hash=config_hash,
        )
        return Account.sign_message(
            encode_defunct(text=payload), private_key=self._tee_key
        ).signature.to_0x_hex()

    def wallet_key_for_tools(self) -> str:
        """Only the in-process wallet sidecar may call this by name."""

        return self._wallet_key


def reply_signature_payload_v2(
    *,
    contest_id: str,
    attacker: str,
    msg_hash: str,
    reply_hash: str,
    seq: int,
    config_hash: str,
) -> str:
    return (
        "RTM BYOA reply v2\n"
        f"contest: {contest_id}\n"
        f"attacker: {Web3.to_checksum_address(attacker)}\n"
        f"msgHash: {msg_hash.lower()}\n"
        f"replyHash: {reply_hash.lower()}\n"
        f"seq: {int(seq)}\n"
        f"configHash: {config_hash.lower()}"
    )


def verify_reply_signature_v2(
    signature: str,
    *,
    reply_signer: str,
    contest_id: str,
    attacker: str,
    msg_hash: str,
    reply_hash: str,
    seq: int,
    config_hash: str,
) -> bool:
    try:
        recovered = Account.recover_message(
            encode_defunct(
                text=reply_signature_payload_v2(
                    contest_id=contest_id,
                    attacker=attacker,
                    msg_hash=msg_hash,
                    reply_hash=reply_hash,
                    seq=seq,
                    config_hash=config_hash,
                )
            ),
            signature=signature,
        )
    except Exception:
        return False
    return recovered == Web3.to_checksum_address(reply_signer)


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
