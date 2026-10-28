"""Consent-aware transcript persistence tests (no network)."""

import json

import pytest

from redteam_platform.transcripts import (
    PURPOSE_DATASET,
    PURPOSE_RSI,
    TranscriptError,
    TranscriptStore,
)

CONTEST = "0x" + "12" * 32
SNAPSHOT = {
    "version": "v0_demo",
    "digest": "ab" * 32,
    "wallet_address": "0x" + "10" * 20,
    "system_prompt_sha256": "cd" * 32,
}
ATTACKER_A = "0x" + "aa" * 20
ATTACKER_B = "0x" + "bb" * 20
MESSAGES = [{"role": "user", "content": "attack content"}]
TRACE = [{"tool": "get_balance", "args": {}, "receipt": {"result": {"balance": "1"}}}]


def make_store(tmp_path, *, is_mining=False):
    return TranscriptStore(
        tmp_path / "data",
        CONTEST,
        is_mining=is_mining,
        snapshot=SNAPSHOT,
        clock=lambda: 111.0,
    )


def turn(store, attacker=ATTACKER_A, consent=True, turn=1, messages=None, reply="hi"):
    return store.record_turn(
        attacker,
        consent,
        turn=turn,
        messages=MESSAGES if messages is None else messages,
        reply=reply,
        tool_calls=TRACE,
        error=None,
    )


def test_opt_out_performs_no_file_io(tmp_path):
    store = make_store(tmp_path)

    assert turn(store, consent=False) is False
    assert not (tmp_path / "data").exists()
    assert list(tmp_path.rglob("*")) == []


def test_consent_writes_snapshot_and_turn(tmp_path):
    store = make_store(tmp_path)

    assert turn(store, consent=True) is True

    directory = tmp_path / "data" / CONTEST
    snapshot = json.loads((directory / "session.json").read_text(encoding="utf-8"))
    assert snapshot["kind"] == "snapshot"
    assert snapshot["purpose"] == PURPOSE_DATASET
    assert snapshot["rsi_only"] is False
    assert snapshot["version"] == "v0_demo"
    assert snapshot["ts"] == 111.0
    assert "attack content" not in json.dumps(snapshot)

    lines = (directory / f"{ATTACKER_A}.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "turn"
    assert record["attacker"] == ATTACKER_A
    assert record["turn"] == 1
    assert record["consent"] is True
    assert record["purpose"] == PURPOSE_DATASET
    assert record["rsi_only"] is False
    assert record["messages"] == MESSAGES
    assert record["tool_calls"] == TRACE
    assert record["ts"] == 111.0


def test_mining_requires_consent_and_marks_rsi_only(tmp_path):
    store = make_store(tmp_path, is_mining=True)

    with pytest.raises(ValueError):
        turn(store, consent=False)
    assert not (tmp_path / "data").exists()

    store.record_snapshot()
    directory = tmp_path / "data" / CONTEST
    snapshot = json.loads((directory / "session.json").read_text(encoding="utf-8"))
    assert snapshot["purpose"] == PURPOSE_RSI
    assert snapshot["rsi_only"] is True
    assert snapshot["is_mining"] is True

    assert turn(store, consent=True) is True
    record = json.loads(
        (directory / f"{ATTACKER_A}.jsonl").read_text(encoding="utf-8").strip()
    )
    assert record["purpose"] == PURPOSE_RSI
    assert record["rsi_only"] is True
    assert record["consent"] is True


def test_turns_append_per_attacker(tmp_path):
    store = make_store(tmp_path)

    assert turn(store, attacker=ATTACKER_A, turn=1) is True
    assert turn(store, attacker=ATTACKER_B, turn=1) is True
    assert turn(store, attacker=ATTACKER_A, turn=2) is True

    directory = tmp_path / "data" / CONTEST
    a_lines = (directory / f"{ATTACKER_A}.jsonl").read_text(encoding="utf-8").splitlines()
    b_lines = (directory / f"{ATTACKER_B}.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(a_lines) == 2
    assert len(b_lines) == 1
    assert json.loads(a_lines[1])["turn"] == 2


@pytest.mark.parametrize(
    "attacker",
    ["", "0x123", "not-an-address", "../escape", "0x" + "zz" * 20],
)
def test_invalid_attacker_is_rejected_before_writing(tmp_path, attacker):
    store = make_store(tmp_path)

    with pytest.raises(ValueError):
        turn(store, attacker=attacker)

    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("turn_number", [0, -1, True, "1", 1.5])
def test_invalid_turn_number_is_rejected(tmp_path, turn_number):
    store = make_store(tmp_path)

    with pytest.raises(ValueError):
        store.record_turn(
            ATTACKER_A,
            True,
            turn=turn_number,
            messages=MESSAGES,
            reply="hi",
            tool_calls=[],
            error=None,
        )


def test_non_serializable_turn_raises(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(TranscriptError):
        turn(store, messages=[{"role": "user", "content": object()}])


@pytest.mark.parametrize(
    "contest_id",
    ["", "../escape", "a/b", "x" * 129, "space id"],
)
def test_unsafe_contest_id_is_rejected(tmp_path, contest_id):
    with pytest.raises(ValueError):
        TranscriptStore(
            tmp_path / "data",
            contest_id,
            is_mining=False,
            snapshot=SNAPSHOT,
        )


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {**SNAPSHOT, "extra": "attacker content"},
        {**SNAPSHOT, "digest": "not-hex"},
        {**SNAPSHOT, "wallet_address": "0x123"},
        {**SNAPSHOT, "system_prompt_sha256": "AB" * 32},
    ],
)
def test_snapshot_is_strictly_validated(tmp_path, snapshot):
    with pytest.raises(ValueError):
        TranscriptStore(
            tmp_path / "data",
            CONTEST,
            is_mining=False,
            snapshot=snapshot,
        )


def test_snapshot_is_written_once(tmp_path):
    store = make_store(tmp_path)

    store.record_snapshot()
    path = tmp_path / "data" / CONTEST / "session.json"
    first = path.read_text(encoding="utf-8")
    store.record_snapshot()

    assert path.read_text(encoding="utf-8") == first
