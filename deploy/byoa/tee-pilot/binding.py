"""Binding shared by the CVM pilot and its external verifier.

Keep this module dependency-free so both sides can hash and sign exactly the
same bytes.
"""

from __future__ import annotations

import hashlib
import json

DOMAIN = "RTM TEE pilot v1"


def canonical_json(data: dict[str, object]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def binding_payload(nonce: str, signer: str, wallet: str) -> dict[str, str]:
    return {
        "domain": DOMAIN,
        "nonce": nonce.lower(),
        "signer": signer,
        "wallet": wallet,
    }


def binding_hash(nonce: str, signer: str, wallet: str) -> str:
    return hashlib.sha256(
        canonical_json(binding_payload(nonce, signer, wallet)).encode("utf-8")
    ).hexdigest()


def signature_text(nonce: str, signer: str, wallet: str, digest: str) -> str:
    return (
        f"{DOMAIN}\n"
        f"nonce: {nonce.lower()}\n"
        f"signer: {signer}\n"
        f"wallet: {wallet}\n"
        f"bindingHash: 0x{digest}"
    )
