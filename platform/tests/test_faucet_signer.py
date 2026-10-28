"""Faucet ticket signing tests; no network, no EVM."""

import json

import pytest
from eth_account import Account
from web3 import Web3

from redteam_platform.config import REPO_ROOT
from redteam_platform.custody import Custody
from redteam_platform.custody_audit import AuditedCustody
from redteam_platform.faucet_signer import (
    TICKET_TYPE,
    TICKET_TYPEHASH,
    FaucetSigner,
    FaucetSignerError,
    SignedTicket,
    recover_ticket_signer,
)

MASTER = "aa" * 32
SIGNER_KEY = "0x" + "11" * 32
OTHER_KEY = "0x" + "22" * 32
FAUCET = Web3.to_checksum_address("0x" + "ab" * 20)
RECIPIENT = Web3.to_checksum_address("0x" + "cd" * 20)
CHAIN_ID = 48850
NOW = 1_000_000
SMALL_N = 2**14


@pytest.fixture
def audited(tmp_path):
    vault = Custody(tmp_path / "vault.json", MASTER, scrypt_n=SMALL_N)
    vault.store("faucet-signer", SIGNER_KEY)
    return AuditedCustody(vault, tmp_path / "audit.jsonl", clock=lambda: 7.0)


def make_signer(audited, **overrides):
    values = {
        "custody": audited,
        "signer_entry": "faucet-signer",
        "faucet_address": FAUCET,
        "chain_id": CHAIN_ID,
        "nonce_lookup": lambda address: 0,
        "expected_signer": Account.from_key(SIGNER_KEY).address,
        "clock": lambda: NOW,
    }
    values.update(overrides)
    return FaucetSigner(**values)


def audit_records(audited):
    return [
        json.loads(line)
        for line in audited.log_path.read_text(encoding="utf-8").splitlines()
    ]


def test_ticket_recovers_to_expected_signer(audited):
    signer = make_signer(audited)

    ticket = signer.sign(RECIPIENT)

    assert isinstance(ticket, SignedTicket)
    assert ticket.to == RECIPIENT
    assert ticket.nonce == 1
    assert ticket.deadline == NOW + signer.ticket_ttl
    assert len(bytes.fromhex(ticket.signature[2:])) == 65

    typed = signer.build_typed_data(ticket.to, ticket.nonce, ticket.deadline)
    recovered = recover_ticket_signer(typed, ticket.signature)
    assert recovered == Account.from_key(SIGNER_KEY).address
    assert ticket.as_dict() == {
        "to": RECIPIENT,
        "nonce": 1,
        "deadline": NOW + signer.ticket_ttl,
        "signature": ticket.signature,
    }

    records = audit_records(audited)
    assert len(records) == 1
    assert records[0]["action"] == "load"
    assert records[0]["result"] == "ok"
    assert records[0]["context"] == {
        "purpose": "faucet_ticket",
        "recipient": RECIPIENT,
        "chain_id": str(CHAIN_ID),
        "ticket_count": "1",
    }
    log = audited.log_path.read_text(encoding="utf-8")
    assert SIGNER_KEY not in log
    assert SIGNER_KEY[2:] not in log


def test_typehash_matches_contract_string():
    assert TICKET_TYPEHASH == Web3.to_hex(
        Web3.keccak(text="Ticket(address to,uint256 nonce,uint64 deadline)")
    )


def test_nonce_is_chain_aware_and_strictly_increasing(audited):
    chain_nonces = {RECIPIENT: 5}
    signer = make_signer(
        audited, nonce_lookup=lambda address: chain_nonces.get(address, 0)
    )

    assert signer.sign(RECIPIENT).nonce == 6
    assert signer.sign(RECIPIENT).nonce == 7

    chain_nonces[RECIPIENT] = 10
    assert signer.sign(RECIPIENT).nonce == 11

    assert signer.sign(RECIPIENT, nonce=20).nonce == 20
    assert signer.sign(RECIPIENT).nonce == 21

    with pytest.raises(FaucetSignerError):
        signer.sign(RECIPIENT, nonce=21)
    with pytest.raises(FaucetSignerError):
        signer.sign(RECIPIENT, nonce=0)

    other = Web3.to_checksum_address("0x" + "ef" * 20)
    assert signer.sign(other).nonce == 1


def test_captcha_policy(audited):
    with pytest.raises(FaucetSignerError):
        make_signer(audited, captcha_required=True)

    signer = make_signer(
        audited,
        captcha_required=True,
        captcha_verifier=lambda token: token == "good",
    )
    with pytest.raises(FaucetSignerError):
        signer.sign(RECIPIENT)
    with pytest.raises(FaucetSignerError):
        signer.sign(RECIPIENT, captcha_token="")
    with pytest.raises(FaucetSignerError):
        signer.sign(RECIPIENT, captcha_token="bad")

    ticket = signer.sign(RECIPIENT, captcha_token="good")
    assert ticket.nonce == 1

    def broken(token):
        raise RuntimeError("provider down")

    broken_signer = make_signer(
        audited,
        captcha_required=True,
        captcha_verifier=broken,
    )
    with pytest.raises(FaucetSignerError) as excinfo:
        broken_signer.sign(RECIPIENT, captcha_token="secret-token")
    assert "secret-token" not in str(excinfo.value)


def test_deadline_bounds(audited):
    signer = make_signer(audited)

    assert signer.sign(RECIPIENT, deadline=NOW + signer.max_ttl).deadline == (
        NOW + signer.max_ttl
    )
    for deadline in (NOW, NOW - 1, NOW + signer.max_ttl + 1, "soon", 1.5, True):
        with pytest.raises(FaucetSignerError):
            signer.sign(RECIPIENT, deadline=deadline)

    with pytest.raises(FaucetSignerError):
        make_signer(audited, ticket_ttl=10, max_ttl=5)
    with pytest.raises(FaucetSignerError):
        make_signer(audited, ticket_ttl=0)


def test_invalid_configuration_and_recipients(audited):
    with pytest.raises(FaucetSignerError):
        make_signer(audited, faucet_address="0x123")
    with pytest.raises(FaucetSignerError):
        make_signer(audited, faucet_address="0x" + "00" * 20)
    with pytest.raises(FaucetSignerError):
        make_signer(audited, chain_id=0)
    with pytest.raises(FaucetSignerError):
        make_signer(audited, signer_entry="")
    with pytest.raises(FaucetSignerError):
        make_signer(audited, nonce_lookup=None)
    with pytest.raises(FaucetSignerError):
        make_signer(audited, expected_signer="0x123")

    signer = make_signer(audited)
    for recipient in ("0x123", "0x" + "00" * 20, None, 123):
        with pytest.raises(FaucetSignerError):
            signer.sign(recipient)


def test_missing_bad_or_mismatched_key_never_echoes_secret(audited):
    missing = make_signer(audited, signer_entry="missing")
    with pytest.raises(FaucetSignerError):
        missing.sign(RECIPIENT)

    bad_vault = Custody(audited.log_path.parent / "bad-vault.json", MASTER, scrypt_n=SMALL_N)
    bad_key = "not-a-private-key"
    bad_vault.store("faucet-signer", bad_key)
    bad = make_signer(AuditedCustody(bad_vault, audited.log_path.parent / "bad-audit.jsonl"))
    with pytest.raises(FaucetSignerError) as excinfo:
        bad.sign(RECIPIENT)
    assert bad_key not in str(excinfo.value)

    mismatch_vault = Custody(audited.log_path.parent / "mismatch-vault.json", MASTER, scrypt_n=SMALL_N)
    mismatch_vault.store("faucet-signer", OTHER_KEY)
    mismatch = make_signer(
        AuditedCustody(mismatch_vault, audited.log_path.parent / "mismatch-audit.jsonl")
    )
    with pytest.raises(FaucetSignerError):
        mismatch.sign(RECIPIENT)


def test_raw_custody_is_not_accepted_for_signing(tmp_path):
    vault = Custody(tmp_path / "vault.json", MASTER, scrypt_n=SMALL_N)
    vault.store("faucet-signer", SIGNER_KEY)
    signer = make_signer(vault)

    with pytest.raises(FaucetSignerError):
        signer.sign(RECIPIENT)


def test_repr_contains_no_key(audited):
    signer = make_signer(audited)
    assert SIGNER_KEY not in repr(signer)
    assert SIGNER_KEY[2:] not in repr(signer)


def test_faucet_abi_guard():
    path = REPO_ROOT / "contracts" / "artifacts" / "src" / "Faucet.sol" / "Faucet.json"
    if not path.is_file():
        pytest.skip("compile contracts first: npx hardhat compile")

    abi = json.loads(path.read_text(encoding="utf-8"))["abi"]
    claim = next(
        entry for entry in abi if entry.get("type") == "function" and entry.get("name") == "claim"
    )
    ticket_type, signature_type = claim["inputs"]
    assert ticket_type["type"] == "tuple"
    assert [component["type"] for component in ticket_type["components"]] == [
        "address",
        "uint256",
        "uint64",
    ]
    assert signature_type["type"] == "bytes"
    assert [field["name"] for field in TICKET_TYPE] == [
        component["name"] for component in ticket_type["components"]
    ]
    assert [field["type"] for field in TICKET_TYPE] == [
        component["type"] for component in ticket_type["components"]
    ]
