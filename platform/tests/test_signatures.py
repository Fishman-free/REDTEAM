"""EIP-712 registration helpers used by the API and the dApp."""

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from redteam_platform.signatures import (
    config_hash,
    defender_registration_typed_data,
    recover_defender_registration,
)

ARENA = "0x" + "88" * 20
CHAIN_ID = 48850


def _sign(key, *, config, nonce=0, deadline=2**64 - 1):
    account = Account.from_key(key)
    typed = defender_registration_typed_data(
        chain_id=CHAIN_ID,
        arena=ARENA,
        defender=account.address,
        config_hash_hex=config,
        nonce=nonce,
        deadline=deadline,
    )
    return account, Account.sign_message(
        encode_typed_data(full_message=typed), private_key=key
    ).signature.to_0x_hex()


def test_round_trip_recovers_the_defender():
    key = "0x" + "11" * 32
    config = config_hash("glm", "prompt", "mandate")
    account, signature = _sign(key, config=config)

    recovered = recover_defender_registration(
        signature,
        chain_id=CHAIN_ID,
        arena=ARENA,
        defender=account.address,
        config_hash_hex=config,
        nonce=0,
        deadline=2**64 - 1,
    )

    assert recovered == account.address


def test_tampered_config_recovers_a_different_signer():
    key = "0x" + "11" * 32
    account, signature = _sign(key, config=config_hash("glm", "prompt", "mandate"))
    tampered = config_hash("glm", "prompt", "another mandate")

    recovered = recover_defender_registration(
        signature,
        chain_id=CHAIN_ID,
        arena=ARENA,
        defender=account.address,
        config_hash_hex=tampered,
        nonce=0,
        deadline=2**64 - 1,
    )

    assert recovered != account.address


def test_config_hash_is_separator_safe():
    assert config_hash("a", "b", "c") != config_hash("a", "bc", "")
    assert config_hash("a", "b", "c") == config_hash("a", "b", "c")


def test_byoa_type_strings_match_the_contract():
    from redteam_platform.signatures import BYOA_MANDATE_TYPES, TEE_WALLET_BINDING_TYPES

    def encode(name, fields):
        return f"{name}(" + ",".join(f"{field['type']} {field['name']}" for field in fields) + ")"

    assert encode("ByoaMandate", BYOA_MANDATE_TYPES["ByoaMandate"]) == (
        "ByoaMandate(address defender,address wallet,address teeSigner,uint256 stake,"
        "uint64 duration,uint32 stakeBps,bytes32 configCommitment,bytes32 runtimeMeasurement,"
        "bytes32 teePubKey,uint8 attestationTier,bool defenderDataConsent,"
        "uint16 utilityMissThreshold,uint16 utilityPenaltyBps,uint64 nonce,uint64 deadline)"
    )
    assert encode("TeeWalletBinding", TEE_WALLET_BINDING_TYPES["TeeWalletBinding"]) == (
        "TeeWalletBinding(address defender,address wallet,bytes32 configCommitment,"
        "bytes32 runtimeMeasurement,bytes32 teePubKey,uint64 nonce,uint64 deadline)"
    )


def test_malformed_signature_is_rejected_without_echoing_it():
    with pytest.raises(ValueError, match="invalid defender signature"):
        recover_defender_registration(
            "0xdeadbeef",
            chain_id=CHAIN_ID,
            arena=ARENA,
            defender="0x" + "11" * 20,
            config_hash_hex=config_hash("glm", "prompt", "mandate"),
            nonce=0,
            deadline=2**64 - 1,
        )
