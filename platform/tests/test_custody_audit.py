"""Metadata-only custody audit tests; no network and no real secrets."""

import json

import pytest

from redteam_platform.custody import Custody, CustodyError
from redteam_platform.custody_audit import AuditedCustody, CustodyAuditError

MASTER = "aa" * 32
SMALL_N = 2**14
KEY = "0x" + "11" * 32
CONTEXT = {
    "purpose": "runner",
    "contest_id": "0x" + "ab" * 32,
    "runner_id": "runner-1",
    "wallet_address": "0x" + "cd" * 20,
}


@pytest.fixture
def audited(tmp_path):
    vault = Custody(tmp_path / "vault.json", MASTER, scrypt_n=SMALL_N)
    return AuditedCustody(vault, tmp_path / "audit" / "custody.jsonl")


def read_records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_records_metadata_without_secret(audited):
    audited.store("wallet-w", KEY, context=CONTEXT)
    assert audited.load("wallet-w", context=CONTEXT) == KEY
    audited.delete("wallet-w", context={**CONTEXT, "purpose": "cleanup"})

    records = read_records(audited.log_path)
    assert [record["action"] for record in records] == ["store", "load", "delete"]
    assert all(record["result"] == "ok" for record in records)
    for record in records:
        assert set(record) == {"ts", "action", "entry_id", "result", "context"}
        assert isinstance(record["ts"], float)
        assert KEY not in json.dumps(record)
    assert records[0]["context"] == CONTEXT
    assert records[2]["context"]["purpose"] == "cleanup"


def test_failed_load_is_audited_and_reraised(audited):
    with pytest.raises(CustodyError):
        audited.load("missing", context=CONTEXT)

    records = read_records(audited.log_path)
    assert records[-1]["action"] == "load"
    assert records[-1]["result"] == "error"
    assert records[-1]["entry_id"] == "missing"


@pytest.mark.parametrize(
    "bad_context",
    [
        {},
        {"purpose": ""},
        {"purpose": "runner", "attacker_content": "secret"},
        {"purpose": "runner", "contest_id": "line\nbreak"},
        {"purpose": 123},
        {"purpose": "runner", "runner_id": "x" * 257},
    ],
)
def test_context_is_strict_and_writes_nothing(audited, bad_context):
    with pytest.raises(ValueError):
        audited.load("wallet-w", context=bad_context)
    assert not audited.log_path.exists()


def test_audit_append_failure_does_not_return_secret(tmp_path):
    vault = Custody(tmp_path / "vault.json", MASTER, scrypt_n=SMALL_N)
    vault.store("wallet-w", KEY)
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    audited = AuditedCustody(vault, blocker / "audit.jsonl")

    with pytest.raises(CustodyAuditError):
        audited.load("wallet-w", context=CONTEXT)


def test_faucet_ticket_context_fields_are_supported(tmp_path):
    vault = Custody(tmp_path / "vault.json", MASTER, scrypt_n=SMALL_N)
    vault.store("faucet-signer", KEY)
    audited = AuditedCustody(vault, tmp_path / "audit.jsonl")
    context = {
        "purpose": "faucet_ticket",
        "recipient": "0x" + "ef" * 20,
        "chain_id": "48850",
        "ticket_count": "3",
    }

    assert audited.load("faucet-signer", context=context) == KEY

    record = read_records(audited.log_path)[0]
    assert record["context"] == context


def test_clock_is_injectable(tmp_path):
    vault = Custody(tmp_path / "vault.json", MASTER, scrypt_n=SMALL_N)
    vault.store("wallet-w", KEY)
    audited = AuditedCustody(
        vault, tmp_path / "audit.jsonl", clock=lambda: 42.5
    )

    audited.load("wallet-w", context=CONTEXT)

    assert read_records(audited.log_path)[0]["ts"] == 42.5
