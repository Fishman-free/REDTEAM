"""Indexer/leaderboard tests with synthetic chain events (no network)."""

import json
from types import SimpleNamespace

import pytest
from web3 import Web3

from redteam_platform.config import REPO_ROOT
from redteam_platform.indexer import (
    ARENA_EVENTS,
    MARKET_EVENTS,
    TOKEN_EVENTS,
    ChainEventSource,
    EventIndexer,
    IndexerError,
    normalize_contest_id,
    normalize_event,
)

ONE = 10**18
STAKE = 50 * ONE
DEFENDER = "0x" + "11" * 20
WALLET = "0x" + "22" * 20
ATTACKER = "0x" + "33" * 20
ATTACKER2 = "0x" + "34" * 20
CONTESTS = ["0x" + f"{index:02x}" * 32 for index in range(0x41, 0x4A)]
SMOKE = "0x" + "ff" * 32
HASHES = ["0x" + f"{index:02x}" * 32 for index in range(0x51, 0x56)]
TREASURY = "0x" + "66" * 20
MINER = "0x" + "88" * 20
ZERO_HASH = "0x" + "00" * 32


def ev(name, args, *, block=1, log=0, ts=1000, contract="Arena", tx="0xtx"):
    return {
        "block_number": block,
        "log_index": log,
        "block_timestamp": ts,
        "contract": contract,
        "name": name,
        "args": args,
        "tx_hash": tx,
    }


class Chain:
    """Emit sequential events for one test; log indexes are unique per block."""

    def __init__(self, indexer):
        self.indexer = indexer
        self.block = 1
        self.log = 0

    def emit(self, name, args, *, ts=1000, block=None, contract="Arena"):
        if block is not None:
            self.block = block
            self.log = 0
        self.log += 1
        return self.indexer.apply_event(
            ev(
                name,
                args,
                block=self.block,
                log=self.log,
                ts=ts,
                contract=contract,
                tx="0x" + f"{self.log:064x}",
            )
        )


def created_args(cid, *, defender=DEFENDER, stake=STAKE, end=2000, hash_=ZERO_HASH):
    return {
        "id": cid,
        "defender": defender,
        "wallet": WALLET,
        "stake": stake,
        "end": end,
        "isMining": False,
        "stakeBps": 1000,
        "defenseHash": hash_,
    }


def joined_args(cid, *, attacker=ATTACKER, consent=True, stake=5 * ONE):
    return {
        "id": cid,
        "attacker": attacker,
        "stake": stake,
        "dataConsent": consent,
    }


def attack_args(cid, *, attacker=ATTACKER, seq=1, fee=ONE // 200):
    return {
        "id": cid,
        "attacker": attacker,
        "msgHash": "0x" + f"{seq:064x}",
        "seq": seq,
        "fee": fee,
    }


def breach_args(cid, *, winner=ATTACKER, amount=STAKE):
    return {"contestId": cid, "winner": winner, "amount": amount}


def settled_args(cid, *, winner=ATTACKER, amount=0):
    return {"id": cid, "winner": winner, "amount": amount}


def expired_args(cid, *, defender=DEFENDER, returned=STAKE):
    return {"id": cid, "defender": defender, "returned": returned}


def mining_created_args(cid, *, hash_=HASHES[0], defender=TREASURY):
    return {
        "id": cid,
        "defender": defender,
        "wallet": WALLET,
        "stake": 0,
        "end": 2**64 - 1,
        "isMining": True,
        "stakeBps": 0,
        "defenseHash": hash_,
    }


def mining_joined_args(cid, *, miner=MINER):
    return {"id": cid, "miner": miner, "base": ONE}


def consent_args(cid, *, who=ATTACKER, consented=True, is_mining=False):
    return {
        "id": cid,
        "attacker": who,
        "consented": consented,
        "isMining": is_mining,
    }


def mining_settled_args(cid, *, winner=MINER, hash_=HASHES[0], reward=ONE):
    return {
        "id": cid,
        "winner": winner,
        "defenseHash": hash_,
        "reward": reward,
    }


def mining_retired_args(cid, *, hash_=HASHES[0], returned=ONE):
    return {"id": cid, "defenseHash": hash_, "returned": returned}


@pytest.fixture
def indexer(tmp_path):
    with EventIndexer(tmp_path / "index.sqlite3", network="test") as idx:
        yield idx


def test_byoa_contest_metadata_is_indexed(indexer):
    chain = Chain(indexer)
    chain.emit("ContestCreated", created_args(CONTESTS[0]), ts=100)
    chain.emit(
        "ByoaContestCreated",
        {
            "id": CONTESTS[0],
            "defender": DEFENDER,
            "wallet": WALLET,
            "teeSigner": ATTACKER,
            "configCommitment": HASHES[0],
            "runtimeMeasurement": HASHES[1],
            "teePubKey": HASHES[2],
            "attestationTier": 0,
            "defenderDataConsent": True,
        },
        ts=100,
    )

    contest = indexer.contest(CONTESTS[0])
    assert contest["is_byoa"] is True
    info = indexer.byoa_info(CONTESTS[0])
    assert info["tee_signer"] == ATTACKER
    assert info["tee_pubkey"] == HASHES[2]
    assert info["runtime_measurement"] == HASHES[1]
    assert info["config_commitment"] == HASHES[0]
    assert info["attestation_tier"] == 0
    assert info["defender_data_consent"] is True


def test_leaderboards_from_events(indexer):
    chain = Chain(indexer)
    chain.emit("ContestCreated", created_args(CONTESTS[0]), ts=100)
    chain.emit("Joined", joined_args(CONTESTS[0]), ts=100)
    chain.emit("AttackPaid", attack_args(CONTESTS[0]), ts=110)
    chain.emit(
        "Breach",
        breach_args(CONTESTS[0]),
        ts=150,
        contract="RTMToken",
    )

    boards = indexer.leaderboards()

    assert boards["network"] == "test"
    assert boards["attackers"][ATTACKER]["wins"] == 1
    assert boards["attackers"][ATTACKER]["difficulty"] == 1
    assert boards["attackers"][ATTACKER]["rtm_won"] == str(STAKE)
    assert boards["attackers"][ATTACKER]["current_streak"] == 1
    assert boards["defenders"][DEFENDER]["contests_survived"] == 0
    assert boards["defenders"][DEFENDER]["longest_survival"] == 50


def test_contests_and_event_lookup(indexer):
    created_tx = "0x" + "aa" * 32
    attack_tx = "0x" + "bb" * 32
    indexer.apply_event(
        ev("ContestCreated", created_args(CONTESTS[0]), block=1, log=1, tx=created_tx)
    )
    indexer.apply_event(
        ev("Joined", joined_args(CONTESTS[0]), block=1, log=2, tx="0x" + "cc" * 32)
    )
    indexer.apply_event(
        ev("AttackPaid", attack_args(CONTESTS[0]), block=1, log=3, tx=attack_tx)
    )

    contests = indexer.contests()
    assert [item["id"] for item in contests] == [CONTESTS[0]]
    assert contests[0]["state"] == "live"
    assert contests[0]["paid_count"] == 1

    event = indexer.event_by_tx(attack_tx, "AttackPaid")
    assert event["name"] == "AttackPaid"
    assert event["args"]["attacker"] == ATTACKER
    assert event["args"]["id"] == CONTESTS[0]
    assert event["excluded"] is False
    assert indexer.event_by_tx(attack_tx, "Joined") is None
    assert indexer.event_by_tx("0x" + "00" * 32) is None

    with pytest.raises(IndexerError):
        indexer.event_by_tx("bad")
    with pytest.raises(IndexerError):
        indexer.contests(limit=0)


def test_large_breach_rest_and_net_income_are_exact(indexer):
    chain = Chain(indexer)
    chain.emit("ContestCreated", created_args(CONTESTS[0]), ts=100)
    chain.emit("Joined", joined_args(CONTESTS[0]), ts=100)
    chain.emit("AttackPaid", attack_args(CONTESTS[0]), ts=110)
    chain.emit(
        "Breach",
        breach_args(CONTESTS[0], amount=STAKE),
        ts=150,
        contract="RTMToken",
    )
    chain.emit("ContestSettled", settled_args(CONTESTS[0], amount=3 * ONE), ts=151)
    chain.emit(
        "PenaltiesCollected",
        {"id": CONTESTS[0], "recipient": DEFENDER, "amount": 2 * ONE},
        ts=160,
    )

    boards = indexer.leaderboards()
    won = STAKE + 3 * ONE
    assert boards["attackers"][ATTACKER]["rtm_won"] == str(won)
    assert boards["defenders"][DEFENDER]["breach_loss"] == str(won)
    assert boards["defenders"][DEFENDER]["penalties"] == str(2 * ONE)
    assert boards["defenders"][DEFENDER]["net_income"] == str(2 * ONE - won)

    contest = indexer.contest(CONTESTS[0])
    assert contest["state"] == "breached"
    assert contest["settled"] is True
    assert contest["breach_amount"] == str(STAKE)


def test_expired_counts_survival_and_resets_streak(indexer):
    chain = Chain(indexer)
    for cid, start, strike_at in (
        (CONTESTS[0], 100, 150),
        (CONTESTS[1], 200, 250),
    ):
        chain.emit("ContestCreated", created_args(cid), ts=start)
        chain.emit("Joined", joined_args(cid), ts=start)
        chain.emit("AttackPaid", attack_args(cid), ts=start + 10)
        chain.emit(
            "Breach", breach_args(cid), ts=strike_at, contract="RTMToken"
        )

    chain.emit("ContestCreated", created_args(CONTESTS[2]), ts=300)
    chain.emit("Joined", joined_args(CONTESTS[2]), ts=300)
    chain.emit("AttackPaid", attack_args(CONTESTS[2], seq=1), ts=310)
    chain.emit("AttackPaid", attack_args(CONTESTS[2], seq=2), ts=320)
    chain.emit("Expired", expired_args(CONTESTS[2]), ts=500)

    boards = indexer.leaderboards()
    attacker = boards["attackers"][ATTACKER]
    assert attacker["wins"] == 2
    assert attacker["difficulty"] == 2
    assert attacker["current_streak"] == 0
    assert attacker["longest_streak"] == 2

    defender = boards["defenders"][DEFENDER]
    assert defender["contests_survived"] == 1
    assert defender["msgs_withstood"] == 2
    assert defender["longest_survival"] == 200


def test_defender_fault_resets_streak_without_survival(indexer):
    chain = Chain(indexer)
    chain.emit("ContestCreated", created_args(CONTESTS[0]), ts=100)
    chain.emit("Joined", joined_args(CONTESTS[0]), ts=100)
    chain.emit(
        "Breach", breach_args(CONTESTS[0]), ts=150, contract="RTMToken"
    )
    chain.emit("ContestCreated", created_args(CONTESTS[1]), ts=300)
    chain.emit("Joined", joined_args(CONTESTS[1]), ts=300)
    chain.emit("DefenderFault", {"id": CONTESTS[1]}, ts=400)

    boards = indexer.leaderboards()
    assert boards["attackers"][ATTACKER]["current_streak"] == 0
    assert boards["attackers"][ATTACKER]["longest_streak"] == 1
    defender = boards["defenders"][DEFENDER]
    assert defender["contests_survived"] == 0
    assert defender["faults"] == 1
    assert defender["longest_survival"] == 100


def test_mining_breach_is_not_a_win_until_settlement(indexer):
    chain = Chain(indexer)
    chain.emit("ContestCreated", mining_created_args(CONTESTS[0]), ts=100)
    chain.emit("MiningJoined", mining_joined_args(CONTESTS[0]), ts=100)
    chain.emit(
        "DataConsentRecorded",
        consent_args(CONTESTS[0], who=MINER, is_mining=True),
        ts=100,
    )
    chain.emit("AttackPaid", attack_args(CONTESTS[0], attacker=MINER, seq=1), ts=110)
    chain.emit("AttackPaid", attack_args(CONTESTS[0], attacker=MINER, seq=2), ts=120)
    chain.emit(
        "Breach",
        breach_args(CONTESTS[0], winner=MINER, amount=ONE),
        ts=150,
        contract="RTMToken",
    )

    before = indexer.leaderboards()
    assert before["miners"][MINER]["wins"] == 0
    assert before["miners"][MINER]["rtm_won_fixed"] == "0"
    assert before["mining"]["settled"] == 0
    assert before["mining"]["active_contests"] == 1

    chain.emit("MiningSettled", mining_settled_args(CONTESTS[0]), ts=150)

    after = indexer.leaderboards()
    miner = after["miners"][MINER]
    assert miner["joined"] == 1
    assert miner["decided_joined"] == 1
    assert miner["wins"] == 1
    assert miner["rtm_won_fixed"] == str(ONE)
    assert miner["difficulty"] == 2
    assert miner["breach_rate"] == 1.0
    mining = after["mining"]
    assert mining["created"] == 1
    assert mining["settled"] == 1
    assert mining["retired"] == 0
    assert mining["decided"] == 1
    assert mining["breach_rate"] == 1.0
    assert mining["total_fixed_reward"] == str(ONE)
    assert mining["active_contests"] == 0
    assert mining["active_versions"] == []
    assert indexer.data_consent(CONTESTS[0], MINER) is True
    assert indexer.contest(CONTESTS[0])["state"] == "settled"
    assert indexer.contest(CONTESTS[0])["reward"] == str(ONE)


def test_mining_retired_and_active_versions(indexer):
    chain = Chain(indexer)
    # Settled mining contest.
    chain.emit(
        "ContestCreated", mining_created_args(CONTESTS[0], hash_=HASHES[0]), ts=100
    )
    chain.emit("MiningJoined", mining_joined_args(CONTESTS[0]), ts=100)
    chain.emit("AttackPaid", attack_args(CONTESTS[0], attacker=MINER, seq=1), ts=110)
    chain.emit(
        "Breach",
        breach_args(CONTESTS[0], winner=MINER, amount=ONE),
        ts=150,
        contract="RTMToken",
    )
    chain.emit(
        "MiningSettled",
        mining_settled_args(CONTESTS[0], hash_=HASHES[0]),
        ts=150,
    )
    # Retired mining contest.
    chain.emit(
        "ContestCreated", mining_created_args(CONTESTS[1], hash_=HASHES[1]), ts=200
    )
    chain.emit("MiningJoined", mining_joined_args(CONTESTS[1]), ts=200)
    chain.emit(
        "MiningRetired", mining_retired_args(CONTESTS[1], hash_=HASHES[1]), ts=300
    )
    # Active mining contest.
    chain.emit(
        "ContestCreated", mining_created_args(CONTESTS[2], hash_=HASHES[2]), ts=400
    )
    chain.emit("MiningJoined", mining_joined_args(CONTESTS[2]), ts=400)

    boards = indexer.leaderboards()
    miner = boards["miners"][MINER]
    assert miner["joined"] == 3
    assert miner["decided_joined"] == 2
    assert miner["wins"] == 1
    assert miner["breach_rate"] == 0.5

    mining = boards["mining"]
    assert mining["created"] == 3
    assert mining["settled"] == 1
    assert mining["retired"] == 1
    assert mining["decided"] == 2
    assert mining["breach_rate"] == 0.5
    assert mining["active_contests"] == 1
    assert mining["active_versions"] == [
        {
            "contest_id": CONTESTS[2],
            "defense_hash": HASHES[2],
            "start_ts": 400,
            "paid_messages": 0,
        }
    ]
    assert [item["outcome"] for item in mining["history"]] == [
        "settled",
        "retired",
    ]
    assert [item["defense_hash"] for item in mining["history"]] == [
        HASHES[0],
        HASHES[1],
    ]


def test_deployment_mints_do_not_affect_mining_issuance(indexer):
    chain = Chain(indexer)
    chain.emit("ContestCreated", mining_created_args(CONTESTS[0]), ts=100)
    chain.emit("MiningJoined", mining_joined_args(CONTESTS[0]), ts=100)
    chain.emit("MiningSettled", mining_settled_args(CONTESTS[0]), ts=150)
    chain.emit(
        "MiningMinted",
        {"to": TREASURY, "amount": 1_000_000 * ONE},
        ts=150,
        contract="RTMToken",
    )
    chain.emit(
        "MiningMinted",
        {"to": TREASURY, "amount": 3 * ONE},
        ts=150,
        contract="RTMToken",
    )

    mining = indexer.leaderboards()["mining"]
    assert mining["total_fixed_reward"] == str(ONE)
    assert indexer.sync_state()["events"] == 5


def test_smoke_contest_is_excluded_everywhere(tmp_path):
    hook_calls = []
    with EventIndexer(
        tmp_path / "index.sqlite3",
        network="test",
        excluded_contest_ids=SMOKE,
        on_mining_ended=lambda cid, name: hook_calls.append((cid, name)),
    ) as idx:
        chain = Chain(idx)
        chain.emit("ContestCreated", mining_created_args(SMOKE), ts=100)
        chain.emit("MiningJoined", mining_joined_args(SMOKE), ts=100)
        chain.emit("AttackPaid", attack_args(SMOKE, attacker=MINER, seq=1), ts=110)
        chain.emit(
            "Breach",
            breach_args(SMOKE, winner=MINER, amount=ONE),
            ts=150,
            contract="RTMToken",
        )
        chain.emit("MiningSettled", mining_settled_args(SMOKE), ts=150)
        chain.emit(
            "MiningMinted",
            {"to": TREASURY, "amount": 1_000_000 * ONE},
            ts=150,
            contract="RTMToken",
        )

        boards = idx.leaderboards()
        assert boards["miners"] == {}
        assert boards["attackers"] == {}
        assert boards["defenders"] == {}
        assert boards["mining"]["created"] == 0
        assert boards["mining"]["settled"] == 0
        assert boards["mining"]["active_versions"] == []
        assert hook_calls == []
        assert idx.contest(SMOKE) is None
        assert idx.is_excluded(SMOKE) is True

        state = idx.sync_state()
        assert state["events"] == 6
        assert state["excluded_events"] == 5
        assert state["excluded_contests"] == [SMOKE]


def test_normal_smoke_contest_is_excluded(tmp_path):
    with EventIndexer(
        tmp_path / "index.sqlite3", network="test", excluded_contest_ids={SMOKE}
    ) as idx:
        chain = Chain(idx)
        chain.emit("ContestCreated", created_args(SMOKE), ts=100)
        chain.emit("Joined", joined_args(SMOKE), ts=100)
        chain.emit("AttackPaid", attack_args(SMOKE), ts=110)
        chain.emit(
            "Breach", breach_args(SMOKE), ts=150, contract="RTMToken"
        )

        boards = idx.leaderboards()
        assert boards["attackers"] == {}
        assert boards["defenders"] == {}
        assert idx.contest(SMOKE) is None


class FakeSource:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def fetch(self, start, end):
        self.calls.append((start, end))
        return [
            event
            for event in self.events
            if start <= event["block_number"] <= end
        ]


def test_process_block_range_is_idempotent(indexer):
    events = [
        ev("ContestCreated", created_args(CONTESTS[0]), block=10, log=1, ts=100),
        ev("Joined", joined_args(CONTESTS[0]), block=10, log=2, ts=100),
        ev("AttackPaid", attack_args(CONTESTS[0]), block=11, log=1, ts=110),
        ev(
            "Breach",
            breach_args(CONTESTS[0]),
            block=12,
            log=1,
            ts=150,
            contract="RTMToken",
        ),
        ev("FutureEvent", {"x": 1}, block=5, log=1, ts=90),
    ]
    source = FakeSource(events)

    assert indexer.last_block() is None
    assert indexer.process_block_range(source, 10, 20) == 4
    assert indexer.last_block() == 20
    boards = indexer.leaderboards()
    assert boards["attackers"][ATTACKER]["wins"] == 1

    assert indexer.process_block_range(source, 10, 20) == 0
    assert indexer.leaderboards() == boards
    assert indexer.sync_state()["events"] == 4
    assert source.calls == [(10, 20), (10, 20)]


def test_process_block_range_sorts_unsorted_source(indexer):
    events = [
        ev(
            "Breach",
            breach_args(CONTESTS[0]),
            block=12,
            log=1,
            ts=150,
            contract="RTMToken",
        ),
        ev("AttackPaid", attack_args(CONTESTS[0]), block=11, log=1, ts=110),
        ev("Joined", joined_args(CONTESTS[0]), block=10, log=2, ts=100),
        ev("ContestCreated", created_args(CONTESTS[0]), block=10, log=1, ts=100),
    ]
    source = FakeSource(events)

    assert indexer.process_block_range(source, 10, 12) == 4
    assert indexer.leaderboards()["attackers"][ATTACKER]["wins"] == 1


def test_duplicate_apply_returns_false(indexer):
    event = ev("ContestCreated", created_args(CONTESTS[0]), block=1, log=1)

    assert indexer.apply_event(event) is True
    assert indexer.apply_event(event) is False
    assert indexer.sync_state()["events"] == 1
    assert indexer.contest(CONTESTS[0]) is not None


def test_unknown_and_data_market_events_are_stored_raw(indexer):
    event = ev("FutureEvent", {"x": 1})
    assert indexer.apply_event(event) is True
    assert indexer.apply_event(
        ev(
            "DatasetPublished",
            {"contestId": CONTESTS[0], "root": "0x" + "ab" * 32},
            log=2,
        )
    )
    assert indexer.apply_event(
        ev(
            "DataSold",
            {
                "buyer": DEFENDER,
                "seller": ATTACKER,
                "contestId": CONTESTS[0],
                "amount": ONE,
                "platformCut": ONE // 10,
            },
            log=3,
        )
    )

    assert indexer.sync_state()["events"] == 3
    boards = indexer.leaderboards()
    assert boards["attackers"] == {}
    assert boards["defenders"] == {}
    assert boards["mining"]["created"] == 0


def test_data_consent_and_contest_attackers(indexer):
    chain = Chain(indexer)
    chain.emit("ContestCreated", created_args(CONTESTS[0]), ts=100)
    chain.emit("Joined", joined_args(CONTESTS[0], consent=False), ts=100)
    chain.emit(
        "DataConsentRecorded",
        consent_args(CONTESTS[0], consented=False),
        ts=100,
    )
    chain.emit("AttackPaid", attack_args(CONTESTS[0]), ts=110)
    chain.emit(
        "MarkDelivered",
        {
            "id": CONTESTS[0],
            "attacker": ATTACKER,
            "msgHash": "0x" + f"{1:064x}",
            "delivered": 1,
        },
        ts=120,
    )

    assert indexer.data_consent(CONTESTS[0], ATTACKER) is False
    attackers = indexer.contest_attackers(CONTESTS[0])
    assert attackers[ATTACKER] == {
        "is_mining": False,
        "stake": str(5 * ONE),
        "data_consent": False,
        "paid": 1,
        "delivered": 1,
        "won": False,
    }

    chain.emit(
        "DataConsentRecorded",
        consent_args(CONTESTS[0], consented=True),
        ts=130,
    )
    assert indexer.data_consent(CONTESTS[0], ATTACKER) is True


def test_network_mismatch_is_rejected(tmp_path):
    path = tmp_path / "index.sqlite3"
    EventIndexer(path, network="network-a").close()

    with pytest.raises(IndexerError):
        EventIndexer(path, network="network-b")


def test_normalize_event_values():
    raw = ev(
        "Breach",
        {
            "contestId": bytes.fromhex("44" * 32),
            "winner": "0x" + "ab" * 20,
            "amount": 7,
        },
        block=3,
        log=2,
        ts=99,
        contract="RTMToken",
        tx=bytes.fromhex("cd" * 32),
    )

    normalized = normalize_event(raw)

    assert normalized["block_number"] == 3
    assert normalized["log_index"] == 2
    assert normalized["block_timestamp"] == 99
    assert normalized["tx_hash"] == "0x" + "cd" * 32
    assert normalized["args"]["contestId"] == "0x" + "44" * 32
    assert normalized["args"]["winner"] == Web3.to_checksum_address(
        "0x" + "ab" * 20
    )

    with pytest.raises(IndexerError):
        normalize_contest_id("0x123")
    with pytest.raises(IndexerError):
        normalize_event({"name": "Breach", "args": {}, "log_index": 1})
    with pytest.raises(IndexerError):
        normalize_event(ev("Breach", [], block=1, log=1))


def test_hook_failure_rolls_back_event(tmp_path):
    def failing_hook(contest_id, name):
        raise RuntimeError("runner unavailable")

    with EventIndexer(
        tmp_path / "index.sqlite3",
        network="test",
        on_mining_ended=failing_hook,
    ) as idx:
        chain = Chain(idx)
        chain.emit("ContestCreated", mining_created_args(CONTESTS[0]), ts=100)
        chain.emit("MiningJoined", mining_joined_args(CONTESTS[0]), ts=100)
        chain.emit("AttackPaid", attack_args(CONTESTS[0], attacker=MINER), ts=110)

        with pytest.raises(RuntimeError):
            chain.emit(
                "Breach",
                breach_args(CONTESTS[0], winner=MINER, amount=ONE),
                ts=150,
                contract="RTMToken",
            )

        assert idx.sync_state()["events"] == 3
        assert idx.contest(CONTESTS[0])["state"] == "live"


def test_mining_hook_fires_only_for_included_mining_ends(indexer):
    calls = []
    indexer._on_mining_ended = lambda cid, name: calls.append((cid, name))

    chain = Chain(indexer)
    # Normal breach does not fire.
    chain.emit("ContestCreated", created_args(CONTESTS[0]), ts=100)
    chain.emit("Joined", joined_args(CONTESTS[0]), ts=100)
    chain.emit(
        "Breach", breach_args(CONTESTS[0]), ts=150, contract="RTMToken"
    )
    assert calls == []

    # Mining breach and settlement fire once each; replay does not refire.
    chain.emit("ContestCreated", mining_created_args(CONTESTS[1]), ts=200)
    chain.emit("MiningJoined", mining_joined_args(CONTESTS[1]), ts=200)
    breach = chain.emit(
        "Breach",
        breach_args(CONTESTS[1], winner=MINER, amount=ONE),
        ts=250,
        contract="RTMToken",
    )
    assert breach is True
    chain.emit("MiningSettled", mining_settled_args(CONTESTS[1]), ts=250)
    assert calls == [
        (CONTESTS[1], "Breach"),
        (CONTESTS[1], "MiningSettled"),
    ]

    # Retired fires once.
    chain.emit(
        "ContestCreated", mining_created_args(CONTESTS[2], hash_=HASHES[2]), ts=300
    )
    chain.emit("MiningJoined", mining_joined_args(CONTESTS[2]), ts=300)
    chain.emit(
        "MiningRetired", mining_retired_args(CONTESTS[2], hash_=HASHES[2]), ts=350
    )
    assert calls[-1] == (CONTESTS[2], "MiningRetired")


class FakeFilter:
    def __init__(self, logs):
        self.logs = logs
        self.calls = []

    def get_logs(self, *, from_block, to_block):
        self.calls.append((from_block, to_block))
        return self.logs


class FakeEvents:
    def __init__(self, mapping):
        self._mapping = mapping

    def __getattr__(self, name):
        try:
            return self._mapping[name]
        except KeyError:
            raise AttributeError(name) from None


class FakeContract:
    def __init__(self, mapping):
        self.events = FakeEvents(mapping)


class FakeEth:
    def __init__(self):
        self.block_number = 100

    def get_block(self, number):
        return {"timestamp": 1000 + number}


class FakeW3:
    def __init__(self):
        self.eth = FakeEth()


def test_chain_event_source_fetch_and_sort():
    arena_created = FakeFilter(
        [
            {
                "blockNumber": 7,
                "logIndex": 2,
                "transactionHash": "0xabc",
                "event": "ContestCreated",
                "args": {"id": CONTESTS[0]},
            }
        ]
    )
    arena_paid = FakeFilter(
        [
            {
                "blockNumber": 6,
                "logIndex": 4,
                "transactionHash": "0xdef",
                "event": "AttackPaid",
                "args": {"id": CONTESTS[0]},
            }
        ]
    )
    token_breach = FakeFilter(
        [
            {
                "blockNumber": 7,
                "logIndex": 3,
                "transactionHash": "0x123",
                "event": "Breach",
                "args": {"contestId": CONTESTS[0]},
            }
        ]
    )
    market_sold = FakeFilter(
        [
            {
                "blockNumber": 7,
                "logIndex": 4,
                "transactionHash": "0x456",
                "event": "DataSold",
                "args": {"contestId": CONTESTS[0]},
            }
        ]
    )
    arena_map = {name: FakeFilter([]) for name in ARENA_EVENTS}
    arena_map.update({"ContestCreated": arena_created, "AttackPaid": arena_paid})
    market_map = {name: FakeFilter([]) for name in MARKET_EVENTS}
    market_map["DataSold"] = market_sold
    arena = FakeContract(arena_map)
    token = FakeContract({"Breach": token_breach})
    market = FakeContract(market_map)
    w3 = FakeW3()

    source = ChainEventSource(w3, arena, token, market)
    events = source.fetch(5, 10)

    assert source.latest_block == 100
    assert [(item["block_number"], item["log_index"]) for item in events] == [
        (6, 4),
        (7, 2),
        (7, 3),
        (7, 4),
    ]
    assert [item["block_timestamp"] for item in events] == [1006, 1007, 1007, 1007]
    assert events[2]["contract"] == "RTMToken"
    assert events[3]["contract"] == "DataMarket"
    assert arena_paid.calls == [(5, 10)]


def test_chain_event_source_missing_event_abi_raises():
    arena = FakeContract({"ContestCreated": FakeFilter([])})
    token = FakeContract({"Breach": FakeFilter([])})

    with pytest.raises(IndexerError):
        ChainEventSource(FakeW3(), arena, token).fetch(1, 2)


def test_chain_event_source_from_chain_client():
    arena = FakeContract({name: FakeFilter([]) for name in ARENA_EVENTS})
    token = FakeContract({name: FakeFilter([]) for name in TOKEN_EVENTS})
    market = FakeContract({name: FakeFilter([]) for name in MARKET_EVENTS})
    client = SimpleNamespace(
        w3=FakeW3(),
        contracts={"Arena": arena, "RTMToken": token, "DataMarket": market},
    )

    source = ChainEventSource.from_chain_client(client)

    assert source.fetch(1, 2) == []
    assert source.latest_block == 100


def test_current_artifacts_expose_indexed_events():
    artifacts = REPO_ROOT / "contracts" / "artifacts" / "src"
    paths = {
        "Arena": artifacts / "Arena.sol" / "Arena.json",
        "RTMToken": artifacts / "RTMToken.sol" / "RTMToken.json",
        "DataMarket": artifacts / "DataMarket.sol" / "DataMarket.json",
    }
    if not all(path.is_file() for path in paths.values()):
        pytest.skip("compile contracts first: npx hardhat compile")

    def event_names(path):
        abi = json.loads(path.read_text(encoding="utf-8"))["abi"]
        return {entry["name"] for entry in abi if entry.get("type") == "event"}

    assert set(ARENA_EVENTS) <= event_names(paths["Arena"])
    assert set(TOKEN_EVENTS) <= event_names(paths["RTMToken"])
    assert set(MARKET_EVENTS) <= event_names(paths["DataMarket"])
