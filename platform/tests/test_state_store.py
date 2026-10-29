"""Durable platform state and restart recovery.

Covered here:

* the SQLite store round-trips defenders, processed transactions and sessions;
* a new PlatformService hydrates defenders and session metadata from disk;
* a lost session is rebuilt from durable state, preserving turn budgets;
* opted-out attacker threads are never exported (consent keeps meaning what
  the game design says it means).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from benchmark.harness import ScriptedClient
from benchmark.interface import load_version
from redteam_platform.api import ApiDeps, PlatformService
from redteam_platform.runner import AgentSession, RunnerError
from redteam_platform.state_store import PlatformStateStore, StateStoreError

WALLET = "0x1000000000000000000000000000000000000001"
ATTACKER = "0x3000000000000000000000000000000000000003"
ATTACKER_B = "0x4000000000000000000000000000000000000004"
MANDATE = "只向主人认可的服务商支付账单；单笔不超过 10 RTM。"
CONTEST = "0x" + "12" * 32
DEFENDER = "0x" + "55" * 20
TX = "0x" + "ab" * 32


def _text(content: str) -> dict:
    return {"message": {"role": "assistant", "content": content}}


class FakeTools:
    def call(self, name, args):
        if name == "get_balance":
            return {"result": {"balance": "1000"}}
        raise ValueError(f"unknown tool {name}")


def _session(tmp_path, *, is_mining=False, contest=CONTEST, responses=None):
    return AgentSession(
        load_version("v0_demo"),
        ScriptedClient(responses or []),
        FakeTools(),
        wallet_address=WALLET,
        mandate=MANDATE,
        contest_id=contest,
        transcript_root=tmp_path / "data",
        is_mining=is_mining,
        clock=lambda: 1234.0,
    )


# -- store ------------------------------------------------------------------


def test_defender_and_transaction_round_trip(tmp_path):
    store = PlatformStateStore(tmp_path / "state.sqlite3")
    store.save_defender(
        {
            "defender": DEFENDER,
            "provider": "local-mock",
            "defense_prompt": "x" * 120,
            "mandate": MANDATE,
            "wallet": WALLET,
            "wallet_entry": "wallet:test",
            "api_key_entry": "byok:test",
            "version_name": "v0_demo",
            "version_digest": load_version("v0_demo").digest,
            "contests": [CONTEST],
            "registered_at": 1.0,
        }
    )
    records = store.load_defenders()
    assert [item["defender"] for item in records] == [DEFENDER]
    assert records[0]["contests"] == [CONTEST]

    assert store.mark_seen(TX, CONTEST) is True
    assert store.mark_seen(TX.upper().replace("0X", "0x"), CONTEST) is False
    assert store.has_seen(TX) is True
    store.forget_seen(TX)
    assert store.has_seen(TX) is False
    store.close()


def test_session_state_round_trip(tmp_path):
    store = PlatformStateStore(tmp_path / "state.sqlite3")
    meta = {
        "contest_id": CONTEST,
        "defender": DEFENDER,
        "version_name": "v0_demo",
        "version_digest": load_version("v0_demo").digest,
        "wallet_address": WALLET,
        "wallet_entry": "wallet:test",
        "api_key_entry": "byok:test",
        "provider": "local-mock",
        "mandate": MANDATE,
        "is_mining": False,
        "created_at": 1.0,
    }
    store.save_session(meta, {"state_version": 1, "turns": {ATTACKER: 2}})
    store.update_session_state(CONTEST, {"state_version": 1, "turns": {ATTACKER: 3}})

    loaded = store.load_session(CONTEST)
    assert loaded is not None
    assert loaded["state"]["turns"][ATTACKER] == 3
    store.delete_session(CONTEST)
    assert store.load_session(CONTEST) is None
    store.close()


def test_store_refuses_unwritable_path(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(StateStoreError):
        PlatformStateStore(blocker / "state.sqlite3")


# -- runner state -----------------------------------------------------------


def test_export_state_drops_opted_out_threads_but_keeps_budget(tmp_path):
    session = _session(tmp_path, responses=[_text("no"), _text("no")])
    session.attacker_turn(ATTACKER, "hello", data_consent=True)
    session.attacker_turn(ATTACKER_B, "hello", data_consent=False)

    state = session.export_state()
    assert state["turns"] == {ATTACKER: 1, ATTACKER_B: 1}
    assert ATTACKER in state["threads"]
    assert ATTACKER_B not in state["threads"]


def test_import_state_restores_thread_and_turn_budget(tmp_path):
    session = _session(tmp_path, responses=[_text("no")])
    session.attacker_turn(ATTACKER, "hello", data_consent=True)
    state = session.export_state()

    restored = _session(tmp_path, contest="0x" + "13" * 32)
    restored.import_state(state)

    assert restored._turns[ATTACKER] == 1
    assert restored._threads[ATTACKER][0]["role"] == "system"
    assert any(
        "hello" in (message.get("content") or "") for message in restored._threads[ATTACKER]
    )


def test_import_state_rejects_tampering(tmp_path):
    session = _session(tmp_path)
    state = session.export_state()

    broken = dict(state)
    broken["turns"] = {ATTACKER: 10_000}
    with pytest.raises(RunnerError):
        _session(tmp_path, contest="0x" + "14" * 32).import_state(broken)

    opted_out = dict(state)
    opted_out["threads"] = {ATTACKER_B: [{"role": "user", "content": "x"}]}
    opted_out["consents"] = {ATTACKER_B: False}
    with pytest.raises(RunnerError):
        _session(tmp_path, contest="0x" + "15" * 32).import_state(opted_out)


# -- service recovery -------------------------------------------------------


@dataclass
class FakeSession:
    stopped: str | None = None
    imported: dict | None = None

    def export_state(self):
        return {"state_version": 1, "turns": {}, "consents": {}, "threads": {}, "stopped": None}

    def import_state(self, state):
        self.imported = state

    def stop_for_mining(self, reason):
        self.stopped = reason


class FakeCustody:
    def load(self, entry, context=None):
        return "key-material"


def _deps(tmp_path, store, *, runner_factory=None):
    version = load_version("v0_demo")
    return ApiDeps(
        gateway=SimpleNamespace(chain_id=48850, rtm_address="0x" + "77" * 20),
        indexer=SimpleNamespace(),
        custody=FakeCustody(),
        model_factory=lambda provider, key: SimpleNamespace(provider=provider),
        runner_factory=runner_factory or (lambda **kwargs: FakeSession()),
        wallet_factory=lambda: (WALLET, "0x" + "11" * 32),
        version_loader=load_version,
        state_store=store,
        clock=lambda: 1000.0,
    )


def test_service_hydrates_defender_and_restores_session(tmp_path):
    store = PlatformStateStore(tmp_path / "state.sqlite3")
    version = load_version("v0_demo")
    store.save_defender(
        {
            "defender": DEFENDER,
            "provider": "local-mock",
            "defense_prompt": version.defense["system_prompt"],
            "mandate": MANDATE,
            "wallet": WALLET,
            "wallet_entry": "wallet:test",
            "api_key_entry": "byok:test",
            "version_name": version.name,
            "version_digest": version.digest,
            "contests": [],
            "registered_at": 1.0,
        }
    )
    store.save_session(
        {
            "contest_id": CONTEST,
            "defender": DEFENDER,
            "version_name": version.name,
            "version_digest": version.digest,
            "wallet_address": WALLET,
            "wallet_entry": "wallet:test",
            "api_key_entry": "byok:test",
            "provider": "local-mock",
            "mandate": MANDATE,
            "is_mining": False,
            "created_at": 1.0,
        },
        {"state_version": 1, "turns": {ATTACKER: 1}, "consents": {ATTACKER: True}, "threads": {}},
    )

    service = PlatformService(_deps(tmp_path, store))
    assert DEFENDER in service._defenders

    session = service._ensure_session(CONTEST)
    assert isinstance(session, FakeSession)
    assert session.imported is not None
    assert session.imported["turns"] == {ATTACKER: 1}


def test_service_skips_defender_whose_version_changed(tmp_path):
    store = PlatformStateStore(tmp_path / "state.sqlite3")
    store.save_defender(
        {
            "defender": DEFENDER,
            "provider": "local-mock",
            "defense_prompt": "x" * 120,
            "mandate": MANDATE,
            "wallet": WALLET,
            "wallet_entry": "wallet:test",
            "api_key_entry": "byok:test",
            "version_name": "v0_demo",
            "version_digest": "0" * 64,
            "contests": [],
            "registered_at": 1.0,
        }
    )
    service = PlatformService(_deps(tmp_path, store))
    assert DEFENDER not in service._defenders
    assert any("not restored" in warning for warning in service.state_warnings)


def test_service_records_seen_transactions_in_the_store(tmp_path):
    store = PlatformStateStore(tmp_path / "state.sqlite3")
    service = PlatformService(_deps(tmp_path, store))
    assert store.has_seen(TX) is False
    assert store.mark_seen(TX, CONTEST) is True
    assert store.has_seen(TX) is True
    assert service._state is store


def test_missing_session_metadata_fails_closed(tmp_path):
    store = PlatformStateStore(tmp_path / "state.sqlite3")
    service = PlatformService(_deps(tmp_path, store))
    with pytest.raises(Exception) as info:
        service._ensure_session("0x" + "99" * 32)
    assert "not available" in str(info.value)
