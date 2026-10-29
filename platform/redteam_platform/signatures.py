"""EIP-712 signing helpers shared by the platform, dApp and tests.

The domain matches the on-chain Arena domain (``RTM Arena`` / ``1`` / chainId /
Arena address), so a defender uses the same ``signTypedData`` implementation
for the off-chain registration and for ``createByoaContest``.

Registration commits to ``configHash`` rather than the plaintext prompt: the
platform can verify the defender's consent without putting private bundle
contents into a wallet popup or a log line.
"""

from __future__ import annotations

from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data
from web3 import Web3

DOMAIN_NAME = "RTM Arena"
DOMAIN_VERSION = "1"

EIP712_DOMAIN_TYPE = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ]
}

DEFENDER_REGISTRATION_TYPES: dict[str, list[dict[str, str]]] = {
    "DefenderRegistration": [
        {"name": "defender", "type": "address"},
        {"name": "configHash", "type": "bytes32"},
        {"name": "nonce", "type": "uint64"},
        {"name": "deadline", "type": "uint64"},
    ]
}

# Field order must match Arena.BYOA_MANDATE_TYPEHASH / TEE_WALLET_BINDING_TYPEHASH.
BYOA_MANDATE_TYPES: dict[str, list[dict[str, str]]] = {
    "ByoaMandate": [
        {"name": "defender", "type": "address"},
        {"name": "wallet", "type": "address"},
        {"name": "teeSigner", "type": "address"},
        {"name": "stake", "type": "uint256"},
        {"name": "duration", "type": "uint64"},
        {"name": "stakeBps", "type": "uint32"},
        {"name": "configCommitment", "type": "bytes32"},
        {"name": "runtimeMeasurement", "type": "bytes32"},
        {"name": "teePubKey", "type": "bytes32"},
        {"name": "attestationTier", "type": "uint8"},
        {"name": "defenderDataConsent", "type": "bool"},
        {"name": "utilityMissThreshold", "type": "uint16"},
        {"name": "utilityPenaltyBps", "type": "uint16"},
        {"name": "nonce", "type": "uint64"},
        {"name": "deadline", "type": "uint64"},
    ]
}

TEE_WALLET_BINDING_TYPES: dict[str, list[dict[str, str]]] = {
    "TeeWalletBinding": [
        {"name": "defender", "type": "address"},
        {"name": "wallet", "type": "address"},
        {"name": "configCommitment", "type": "bytes32"},
        {"name": "runtimeMeasurement", "type": "bytes32"},
        {"name": "teePubKey", "type": "bytes32"},
        {"name": "nonce", "type": "uint64"},
        {"name": "deadline", "type": "uint64"},
    ]
}

# Off-chain only: binds an attacker's X25519 reply key to its paid message.
ATTACK_KEY_TYPES: dict[str, list[dict[str, str]]] = {
    "AttackKey": [
        {"name": "attacker", "type": "address"},
        {"name": "contestId", "type": "bytes32"},
        {"name": "msgHash", "type": "bytes32"},
        {"name": "pubkey", "type": "bytes32"},
        {"name": "deadline", "type": "uint64"},
    ]
}


def arena_typed_data(
    *,
    chain_id: int,
    arena: str,
    primary_type: str,
    message: dict[str, Any],
) -> dict[str, Any]:
    """Build the shared Arena EIP-712 document for any primary type."""

    all_types = {
        **DEFENDER_REGISTRATION_TYPES,
        **BYOA_MANDATE_TYPES,
        **TEE_WALLET_BINDING_TYPES,
        **ATTACK_KEY_TYPES,
    }
    if primary_type not in all_types:
        raise ValueError(f"unknown primary type: {primary_type}")
    # eth_account derives the primary type from the full type map, so include
    # only the selected struct (plus the domain) rather than every Arena type.
    types = {**EIP712_DOMAIN_TYPE, primary_type: all_types[primary_type]}
    payload = dict(message)
    for key in ("defender", "wallet", "teeSigner", "attacker"):
        if key in payload:
            payload[key] = Web3.to_checksum_address(payload[key])
    return {
        "types": types,
        "primaryType": primary_type,
        "domain": {
            "name": DOMAIN_NAME,
            "version": DOMAIN_VERSION,
            "chainId": int(chain_id),
            "verifyingContract": Web3.to_checksum_address(arena),
        },
        "message": payload,
    }


def ownership_challenge(
    *, defender: str, purpose: str, nonce: int, deadline: int
) -> str:
    """EIP-191 text used for off-chain key-ownership proofs."""

    return canonical_challenge(defender, purpose, nonce, deadline)


def canonical_challenge(
    defender: str, purpose: str, nonce: int, deadline: int
) -> str:
    address = Web3.to_checksum_address(defender)
    return (
        "RTM Arena key ownership\n"
        f"address: {address}\n"
        f"purpose: {purpose}\n"
        f"nonce: {int(nonce)}\n"
        f"deadline: {int(deadline)}"
    )


def recover_personal_signer(signature: str, text: str) -> str:
    try:
        return Account.recover_message(encode_defunct(text=text), signature=signature)
    except Exception:
        raise ValueError("invalid signature") from None


def recover_typed_signer(
    signature: str,
    *,
    chain_id: int,
    arena: str,
    primary_type: str,
    message: dict[str, Any],
) -> str:
    """Recover an Arena EIP-712 signer; raise ``ValueError`` when malformed."""

    typed = arena_typed_data(
        chain_id=chain_id,
        arena=arena,
        primary_type=primary_type,
        message=message,
    )
    try:
        signable = encode_typed_data(full_message=typed)
        return Account.recover_message(signable, signature=signature)
    except Exception:
        raise ValueError("invalid signature") from None


def config_hash(provider: str, defense_prompt: str, mandate: str) -> str:
    """Commit to the BYOK package without revealing it in the signature UI."""

    payload = f"{provider}\x00{defense_prompt}\x00{mandate}".encode("utf-8")
    digest = Web3.keccak(payload).hex()
    return digest if digest.startswith("0x") else "0x" + digest


def defender_registration_typed_data(
    *,
    chain_id: int,
    arena: str,
    defender: str,
    config_hash_hex: str,
    nonce: int,
    deadline: int,
) -> dict[str, Any]:
    """Build the full typed-data document (also useful for client SDKs)."""

    return {
        "types": {**EIP712_DOMAIN_TYPE, **DEFENDER_REGISTRATION_TYPES},
        "primaryType": "DefenderRegistration",
        "domain": {
            "name": DOMAIN_NAME,
            "version": DOMAIN_VERSION,
            "chainId": int(chain_id),
            "verifyingContract": Web3.to_checksum_address(arena),
        },
        "message": {
            "defender": Web3.to_checksum_address(defender),
            "configHash": config_hash_hex,
            "nonce": int(nonce),
            "deadline": int(deadline),
        },
    }


def recover_defender_registration(
    signature: str,
    *,
    chain_id: int,
    arena: str,
    defender: str,
    config_hash_hex: str,
    nonce: int,
    deadline: int,
) -> str:
    """Recover the signer; raise ``ValueError`` for malformed signatures."""

    typed = defender_registration_typed_data(
        chain_id=chain_id,
        arena=arena,
        defender=defender,
        config_hash_hex=config_hash_hex,
        nonce=nonce,
        deadline=deadline,
    )
    try:
        signable = encode_typed_data(full_message=typed)
        return Account.recover_message(signable, signature=signature)
    except Exception:
        raise ValueError("invalid defender signature") from None
