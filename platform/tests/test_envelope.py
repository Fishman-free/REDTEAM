"""E2E envelope round-trip, tamper and context binding."""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from redteam_platform.byoa.envelope import (
    EnvelopeError,
    attack_context,
    ciphertext_hash,
    derive_identity_key,
    envelope_hash,
    open_envelope,
    public_key,
    reply_context,
    seal,
)


def _identity(key="0x" + "11" * 32):
    signature = Account.sign_message(
        encode_defunct(text="RTM BYOA identity v1"), private_key=key
    )
    private = derive_identity_key(signature.signature)
    return private, public_key(private)


def test_round_trip_and_deterministic_identity():
    first, pub_a = _identity()
    second, pub_b = _identity()
    assert first == second and pub_a == pub_b

    private, public = _identity("0x" + "22" * 32)
    envelope = seal(public, b"attack text", context="ctx-1")
    assert open_envelope(private, envelope, context="ctx-1") == b"attack text"
    assert envelope["ctx"] == "ctx-1"
    assert envelope_hash(envelope).startswith("0x")
    assert ciphertext_hash(envelope["ct"]).startswith("0x")


def test_wrong_context_and_tampering_are_rejected():
    private, public = _identity()
    envelope = seal(public, b"attack text", context="ctx-1")

    with pytest.raises(EnvelopeError, match="context"):
        open_envelope(private, envelope, context="ctx-2")

    tampered = dict(envelope)
    raw = bytearray(bytes.fromhex(tampered["ct"][2:]))
    raw[-1] ^= 1
    tampered["ct"] = "0x" + raw.hex()
    with pytest.raises(EnvelopeError, match="authentication"):
        open_envelope(private, tampered, context="ctx-1")


def test_contexts_bind_direction_and_message():
    attacker = "0x" + "33" * 20
    contest = "0x" + "44" * 32
    message = "0x" + "55" * 32

    assert attack_context(contest, attacker) != attack_context(contest, "0x" + "66" * 20)
    assert reply_context(contest, attacker, message, 1) != reply_context(
        contest, attacker, message, 2
    )


def test_envelope_rejects_invalid_shapes():
    private, public = _identity()
    envelope = seal(public, b"x", context="ctx")
    with pytest.raises(EnvelopeError):
        open_envelope(private, {**envelope, "v": 2}, context="ctx")
    with pytest.raises(EnvelopeError):
        open_envelope(private, {**envelope, "epk": "0x00"}, context="ctx")
    with pytest.raises(EnvelopeError):
        seal("0x" + "00" * 31, b"x", context="ctx")
