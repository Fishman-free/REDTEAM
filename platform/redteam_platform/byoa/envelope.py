"""Application-layer E2E envelope for BYOA messages.

Suite: X25519 + HKDF-SHA256 + AES-256-GCM (HPKE base-mode shape, implemented
locally so the browser and Python use the same wire format).

The platform relay sees only the envelope JSON and its keccak hash.  Context
strings bind each envelope to one contest, direction and (for replies) one
attack message, so a ciphertext cannot be replayed into another turn.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Mapping

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from web3 import Web3

SUITE = "X25519-HKDF-SHA256-AES-256-GCM"
VERSION = 1
INFO_PREFIX = b"RTM BYOA envelope v1"
SALT = hashlib.sha256(b"RTM BYOA salt v1").digest()
MAX_CIPHERTEXT = 64 * 1024


class EnvelopeError(ValueError):
    """Raised for malformed, tampered or context-mismatched envelopes."""


def derive_identity_key(signature: bytes | str) -> bytes:
    """Deterministic X25519 seed from a wallet signature.

    The dApp signs a fixed EIP-191 message; hashing the signature gives a
    32-byte seed.  X25519 clamps it internally, so no extra derivation is
    required.
    """

    if isinstance(signature, str):
        try:
            data = bytes.fromhex(signature[2:] if signature.startswith("0x") else signature)
        except ValueError:
            raise EnvelopeError("signature must be hex") from None
    else:
        data = bytes(signature)
    if len(data) < 64:
        raise EnvelopeError("signature is too short")
    return hashlib.sha256(data).digest()


def public_key(private_key: bytes) -> bytes:
    _require_key(private_key)
    return (
        X25519PrivateKey.from_private_bytes(private_key)
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )


def _require_key(value: bytes) -> None:
    if not isinstance(value, (bytes, bytearray)) or len(value) != 32:
        raise EnvelopeError("X25519 keys must be 32 bytes")


def _public(value: bytes | str, name: str) -> bytes:
    if isinstance(value, str):
        text = value[2:] if value.startswith("0x") else value
        try:
            data = bytes.fromhex(text)
        except ValueError:
            raise EnvelopeError(f"{name} must be hex") from None
    elif isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    else:
        raise EnvelopeError(f"{name} must be bytes or hex")
    if len(data) != 32:
        raise EnvelopeError(f"{name} must be 32 bytes")
    return data


def _key(shared: bytes, recipient: bytes, ephemeral: bytes, context: str) -> bytes:
    info = INFO_PREFIX + recipient + ephemeral + context.encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        info=info,
    ).derive(shared)


def seal(recipient_public: bytes | str, plaintext: bytes, *, context: str) -> dict[str, Any]:
    """Encrypt ``plaintext`` to a recipient X25519 public key."""

    recipient = _public(recipient_public, "recipient_public")
    if not isinstance(plaintext, bytes) or len(plaintext) == 0:
        raise EnvelopeError("plaintext must be non-empty bytes")
    if len(plaintext) > MAX_CIPHERTEXT:
        raise EnvelopeError("plaintext is too large")
    if not isinstance(context, str) or not context or len(context) > 512:
        raise EnvelopeError("context must be a bounded string")
    ephemeral_private = X25519PrivateKey.generate()
    ephemeral = ephemeral_private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    shared = ephemeral_private.exchange(X25519PublicKey.from_public_bytes(recipient))
    key = _key(shared, recipient, ephemeral, context)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, context.encode("utf-8"))
    return {
        "v": VERSION,
        "suite": SUITE,
        "epk": "0x" + ephemeral.hex(),
        "nonce": "0x" + nonce.hex(),
        "ct": "0x" + ciphertext.hex(),
        "ctx": context,
    }


def open_envelope(
    private_key: bytes, envelope: Mapping[str, Any], *, context: str
) -> bytes:
    """Decrypt and authenticate an envelope; wrong context is rejected."""

    _require_key(private_key)
    if not isinstance(envelope, Mapping):
        raise EnvelopeError("envelope must be an object")
    if envelope.get("v") != VERSION or envelope.get("suite") != SUITE:
        raise EnvelopeError("unsupported envelope version or suite")
    if envelope.get("ctx") != context:
        raise EnvelopeError("envelope context does not match")
    ephemeral = _public(envelope.get("epk"), "epk")
    nonce = _hex_bytes(envelope.get("nonce"), "nonce")
    ciphertext = _hex_bytes(envelope.get("ct"), "ct")
    if len(nonce) != 12:
        raise EnvelopeError("nonce must be 12 bytes")
    if not ciphertext or len(ciphertext) > MAX_CIPHERTEXT + 64:
        raise EnvelopeError("ciphertext is invalid")
    recipient = public_key(private_key)
    shared = X25519PrivateKey.from_private_bytes(private_key).exchange(
        X25519PublicKey.from_public_bytes(ephemeral)
    )
    key = _key(shared, recipient, ephemeral, context)
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, context.encode("utf-8"))
    except Exception:
        raise EnvelopeError("envelope authentication failed") from None


def _hex_bytes(value: Any, name: str) -> bytes:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise EnvelopeError(f"{name} must be 0x-prefixed hex")
    try:
        return bytes.fromhex(value[2:])
    except ValueError:
        raise EnvelopeError(f"{name} must be hex") from None


def canonical_envelope(envelope: Mapping[str, Any]) -> str:
    if not isinstance(envelope, Mapping):
        raise EnvelopeError("envelope must be an object")
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def envelope_hash(envelope: Mapping[str, Any]) -> str:
    """keccak256 of the canonical envelope JSON (used as replyHash)."""

    digest = Web3.keccak(canonical_envelope(envelope).encode("utf-8")).hex()
    return digest if digest.startswith("0x") else "0x" + digest


def attack_context(contest_id: str, attacker: str) -> str:
    return f"rtm-byoa/attack/v1/{contest_id}/{Web3.to_checksum_address(attacker)}"


def reply_context(contest_id: str, attacker: str, msg_hash: str, seq: int) -> str:
    return (
        "rtm-byoa/reply/v1/"
        f"{contest_id}/{Web3.to_checksum_address(attacker)}/{msg_hash.lower()}/{int(seq)}"
    )


def ciphertext_hash(ciphertext: bytes | str) -> str:
    """keccak256 of the raw ciphertext bytes, matching the dApp's msgHash."""

    if isinstance(ciphertext, str):
        raw = _hex_bytes(ciphertext, "ciphertext")
    else:
        raw = bytes(ciphertext)
    digest = Web3.keccak(raw).hex()
    return digest if digest.startswith("0x") else "0x" + digest
