"""Dataset bundle/publish/delivery tests; no network, no real operator key."""

import hashlib
import json
import zipfile
from types import SimpleNamespace

import pytest
from web3 import Web3

from redteam_platform.custody import Custody
from redteam_platform.custody_audit import AuditedCustody
from redteam_platform.data_service import (
    ZERO_ROOT,
    ChainDataMarketWriter,
    DataService,
    DataServiceError,
)
from redteam_platform.indexer import EventIndexer

ONE = 10**18
DEFENDER = Web3.to_checksum_address("0x" + "11" * 20)
WALLET = Web3.to_checksum_address("0x" + "22" * 20)
ATTACKER_A = Web3.to_checksum_address("0x" + "33" * 20)
ATTACKER_B = Web3.to_checksum_address("0x" + "34" * 20)
TREASURY = Web3.to_checksum_address("0x" + "66" * 20)
MINER = Web3.to_checksum_address("0x" + "88" * 20)
CID = "0x" + "44" * 32
LIVE_CID = "0x" + "45" * 32
MINING_CID = "0x" + "46" * 32
SMOKE_CID = "0x" + "47" * 32
HASH = "0x" + "55" * 32
ROOT = "0x" + "99" * 32


class Chain:
    def __init__(self, indexer):
        self.indexer = indexer
        self.block = 1
        self.log = 0

    def next_block(self):
        self.block += 1
        self.log = 0

    def emit(self, name, args, *, ts=100, contract="Arena"):
        self.log += 1
        assert self.indexer.apply_event(
            {
                "block_number": self.block,
                "log_index": self.log,
                "block_timestamp": ts,
                "contract": contract,
                "name": name,
                "args": args,
                "tx_hash": "0x" + f"{self.log:064x}",
            }
        )


def setup_normal(chain, cid=CID, *, finish=True):
    chain.emit(
        "ContestCreated",
        {
            "id": cid,
            "defender": DEFENDER,
            "wallet": WALLET,
            "stake": 50 * ONE,
            "end": 2000,
            "isMining": False,
            "stakeBps": 1000,
            "defenseHash": "0x" + "00" * 32,
        },
        ts=100,
    )
    chain.emit(
        "Joined",
        {"id": cid, "attacker": ATTACKER_A, "stake": 5 * ONE, "dataConsent": True},
        ts=100,
    )
    chain.emit(
        "Joined",
        {"id": cid, "attacker": ATTACKER_B, "stake": 5 * ONE, "dataConsent": False},
        ts=100,
    )
    chain.emit(
        "AttackPaid",
        {
            "id": cid,
            "attacker": ATTACKER_A,
            "msgHash": "0x" + f"{1:064x}",
            "seq": 1,
            "fee": ONE // 200,
        },
        ts=110,
    )
    if not finish:
        return
    chain.emit(
        "Breach",
        {"contestId": cid, "winner": ATTACKER_A, "amount": 50 * ONE},
        ts=150,
        contract="RTMToken",
    )
    chain.emit(
        "ContestSettled", {"id": cid, "winner": ATTACKER_A, "amount": 0}, ts=150
    )


def setup_mining(chain, cid=MINING_CID):
    chain.emit(
        "ContestCreated",
        {
            "id": cid,
            "defender": TREASURY,
            "wallet": WALLET,
            "stake": 0,
            "end": 2**64 - 1,
            "isMining": True,
            "stakeBps": 0,
            "defenseHash": HASH,
        },
        ts=100,
    )
    chain.emit(
        "MiningJoined", {"id": cid, "miner": MINER, "base": ONE}, ts=100
    )


def write_transcripts(tmp_path, cid=CID):
    root = tmp_path / "transcripts" / cid
    root.mkdir(parents=True, exist_ok=True)
    (root / "session.json").write_text(
        json.dumps(
            {
                "kind": "snapshot",
                "contest": cid,
                "version": "v0_demo",
                "digest": "ab" * 32,
                "wallet_address": WALLET,
                "system_prompt_sha256": "cd" * 32,
                "is_mining": False,
                "purpose": "defender_dataset",
                "rsi_only": False,
            }
        ),
        encoding="utf-8",
    )
    good = {
        "kind": "turn",
        "contest": cid,
        "attacker": ATTACKER_A,
        "turn": 1,
        "consent": True,
        "purpose": "defender_dataset",
        "rsi_only": False,
        "messages": [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "channel": "external_dialogue",
                        "claimed_sender": ATTACKER_A,
                        "content": "A MESSAGE",
                    }
                ),
            },
            {"role": "assistant", "content": "A REPLY"},
        ],
        "reply": "A REPLY",
        "tool_calls": [],
        "error": None,
    }
    poisoned = {
        **good,
        "turn": 2,
        "rsi_only": True,
        "purpose": "rsi",
        "reply": "MINER SECRET",
    }
    wrong_attacker = {
        **good,
        "turn": 3,
        "attacker": ATTACKER_B,
        "reply": "OTHER ATTACKER",
    }
    (root / f"{ATTACKER_A.lower()}.jsonl").write_text(
        "\n".join(json.dumps(record) for record in (good, poisoned, wrong_attacker))
        + "\n",
        encoding="utf-8",
    )
    (root / f"{ATTACKER_B.lower()}.jsonl").write_text(
        json.dumps(
            {
                **good,
                "attacker": ATTACKER_B,
                "consent": False,
                "reply": "OPT OUT SECRET",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return root


class FakeWriter:
    def __init__(self):
        self.roots = {}
        self.published = []

    def dataset_root(self, contest_id):
        return self.roots.get(contest_id, ZERO_ROOT)

    def publish(self, contest_id, root):
        self.roots[contest_id] = root
        self.published.append((contest_id, root))
        return "0xtxhash"


@pytest.fixture
def indexer(tmp_path):
    with EventIndexer(tmp_path / "index.sqlite3", network="test") as idx:
        yield idx


def make_service(tmp_path, indexer, writer=None, clock=None):
    return DataService(
        indexer,
        tmp_path / "transcripts",
        tmp_path / "bundles",
        writer=writer,
        clock=clock or (lambda: 5000.0),
        delivery_ttl=10,
    )


def test_bundle_includes_only_consented_attacker_data(indexer, tmp_path):
    chain = Chain(indexer)
    setup_normal(chain)
    write_transcripts(tmp_path)
    service = make_service(tmp_path, indexer)

    bundle = service.bundle(CID)

    paths = {item.path for item in bundle.files}
    assert paths == {
        "defender/contest.json",
        "defender/session.json",
        f"attackers/{ATTACKER_A.lower()}/transcript.jsonl",
    }
    assert bundle.excluded["opt_out_attackers"] == [ATTACKER_B]
    assert bundle.excluded["skipped_records"] == 2
    assert bundle.root.startswith("0x") and len(bundle.root) == 66

    transcript = (
        bundle.directory / f"attackers/{ATTACKER_A.lower()}/transcript.jsonl"
    ).read_text(encoding="utf-8")
    assert "A MESSAGE" in transcript
    assert "A REPLY" in transcript
    assert "MINER SECRET" not in transcript
    assert "OPT OUT SECRET" not in transcript
    assert "OTHER ATTACKER" not in transcript

    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert manifest["root"] == bundle.root
    assert manifest["contest_id"] == CID
    assert all(item["path"] != "manifest.json" for item in manifest["files"])
    assert "A MESSAGE" not in json.dumps(manifest, ensure_ascii=False)
    assert "OPT OUT SECRET" not in json.dumps(manifest, ensure_ascii=False)

    leaves = [
        item["sha256"]
        for item in sorted(manifest["files"], key=lambda item: item["path"])
    ]
    recomputed = "0x" + hashlib.sha256("".join(leaves).encode("ascii")).hexdigest()
    assert recomputed == bundle.root
    for item in manifest["files"]:
        data = (bundle.directory / item["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
        assert len(data) == item["bytes"]


def test_bundle_is_cached(indexer, tmp_path):
    chain = Chain(indexer)
    setup_normal(chain)
    write_transcripts(tmp_path)
    service = make_service(tmp_path, indexer)

    first = service.bundle(CID)
    second = service.bundle(CID)

    assert first is second
    assert first.directory == second.directory


def test_bundle_rejects_live_mining_and_excluded_contests(indexer, tmp_path):
    chain = Chain(indexer)
    setup_normal(chain, cid=LIVE_CID, finish=False)
    chain.next_block()
    setup_mining(chain)
    service = make_service(tmp_path, indexer)

    with pytest.raises(DataServiceError):
        service.bundle(LIVE_CID)
    with pytest.raises(DataServiceError):
        service.bundle(MINING_CID)

    with EventIndexer(
        tmp_path / "excluded.sqlite3",
        network="test",
        excluded_contest_ids={SMOKE_CID},
    ) as excluded:
        excluded_chain = Chain(excluded)
        setup_normal(excluded_chain, cid=SMOKE_CID)
        excluded_service = make_service(tmp_path, excluded)
        with pytest.raises(DataServiceError):
            excluded_service.bundle(SMOKE_CID)


def test_publish_requires_writer_and_ended_contest(indexer, tmp_path):
    chain = Chain(indexer)
    setup_normal(chain)
    write_transcripts(tmp_path)

    with pytest.raises(DataServiceError):
        make_service(tmp_path, indexer).publish(CID)

    writer = FakeWriter()
    service = make_service(tmp_path, indexer, writer)
    result = service.publish(CID)

    assert result.contest_id == CID
    assert result.root == service.bundle(CID).root
    assert result.tx_hash == "0xtxhash"
    assert writer.published == [(CID, result.root)]

    with pytest.raises(DataServiceError):
        service.publish(CID)


def test_delivery_slices_and_tokens(indexer, tmp_path):
    chain = Chain(indexer)
    setup_normal(chain)
    write_transcripts(tmp_path)
    writer = FakeWriter()
    now = [5000.0]
    service = make_service(tmp_path, indexer, writer, clock=lambda: now[0])
    result = service.publish(CID)

    own = service.deliver_own(CID, DEFENDER)
    with zipfile.ZipFile(own.path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    assert names == {"manifest.json", "defender/contest.json", "defender/session.json"}
    assert manifest["root"] == result.root
    assert own.kind == "own"
    assert own.attacker is None
    assert own.root == result.root

    attacker = service.deliver_attacker(CID, DEFENDER, ATTACKER_A)
    with zipfile.ZipFile(attacker.path) as archive:
        names = set(archive.namelist())
        payload = archive.read(f"attackers/{ATTACKER_A.lower()}/transcript.jsonl")
    assert names == {
        "manifest.json",
        f"attackers/{ATTACKER_A.lower()}/transcript.jsonl",
    }
    assert b"A MESSAGE" in payload
    assert b"MINER SECRET" not in payload
    assert attacker.kind == "attacker"
    assert attacker.attacker == ATTACKER_A

    assert service.resolve_delivery(own.token) == own
    assert service.resolve_delivery("missing") is None
    now[0] = 5009.0
    assert service.resolve_delivery(own.token) == own
    now[0] = 5010.0
    assert service.resolve_delivery(own.token) is None

    with pytest.raises(DataServiceError):
        service.deliver_own(CID, ATTACKER_A)
    with pytest.raises(DataServiceError):
        service.deliver_attacker(CID, DEFENDER, ATTACKER_B)
    with pytest.raises(DataServiceError):
        service.deliver_attacker(CID, DEFENDER, "0x" + "99" * 20)


def test_delivery_rejects_tampered_bundle_file(indexer, tmp_path):
    chain = Chain(indexer)
    setup_normal(chain)
    write_transcripts(tmp_path)
    writer = FakeWriter()
    service = make_service(tmp_path, indexer, writer)
    service.publish(CID)
    bundle = service.bundle(CID)

    target = bundle.directory / f"attackers/{ATTACKER_A.lower()}/transcript.jsonl"
    target.write_text("tampered", encoding="utf-8")

    with pytest.raises(DataServiceError):
        service.deliver_attacker(CID, DEFENDER, ATTACKER_A)


def test_delivery_requires_matching_published_root(indexer, tmp_path):
    chain = Chain(indexer)
    setup_normal(chain)
    write_transcripts(tmp_path)
    writer = FakeWriter()
    service = make_service(tmp_path, indexer, writer)
    result = service.publish(CID)

    writer.roots[CID] = ZERO_ROOT
    with pytest.raises(DataServiceError):
        service.deliver_own(CID, DEFENDER)

    writer.roots[CID] = "0x" + "77" * 32
    with pytest.raises(DataServiceError):
        service.deliver_own(CID, DEFENDER)

    writer.roots[CID] = result.root
    assert service.deliver_own(CID, DEFENDER).root == result.root


def test_mining_session_snapshot_is_not_included_in_normal_bundle(indexer, tmp_path):
    chain = Chain(indexer)
    setup_normal(chain)
    root = write_transcripts(tmp_path)
    session = json.loads((root / "session.json").read_text(encoding="utf-8"))
    session["is_mining"] = True
    (root / "session.json").write_text(json.dumps(session), encoding="utf-8")

    bundle = make_service(tmp_path, indexer).bundle(CID)

    assert "defender/session.json" not in {item.path for item in bundle.files}


class FakeCall:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


class FakePublishTx:
    def __init__(self, eth):
        self.eth = eth

    def build_transaction(self, params):
        self.eth.params = dict(params)
        return {"data": "0x", **params}


class FakeFunctions:
    def __init__(self, eth):
        self.eth = eth

    def datasetRoot(self, contest_id):
        self.eth.root_reads.append(contest_id)
        return FakeCall(self.eth.root)

    def publish(self, contest_id, root):
        self.eth.publish_args = (contest_id, root)
        if self.eth.publish_error is not None:
            raise self.eth.publish_error
        self.eth.root = root
        return FakePublishTx(self.eth)


class FakeMarket:
    def __init__(self, eth):
        self.functions = FakeFunctions(eth)


class FakeSigner:
    def __init__(self, eth):
        self.eth = eth

    def sign_transaction(self, tx, key):
        self.eth.keys.append(key)
        return SimpleNamespace(raw_transaction=b"raw")


class FakeEth:
    def __init__(self, status=1):
        self.root = b"\x00" * 32
        self.status = status
        self.root_reads = []
        self.publish_args = None
        self.publish_error = None
        self.params = None
        self.keys = []
        self.account = FakeSigner(self)
        self.chain_id = 48850

    def get_transaction_count(self, address):
        return 0

    def send_raw_transaction(self, raw):
        return "0xtxhash"

    def wait_for_transaction_receipt(self, tx_hash, timeout=None):
        return {"status": self.status}


class FakeW3:
    def __init__(self, eth):
        self.eth = eth


OPERATOR_KEY = "0x" + "33" * 32
MASTER = "aa" * 32


def make_audited_operator(tmp_path):
    vault = Custody(tmp_path / "vault.json", MASTER, scrypt_n=2**14)
    vault.store("operator", OPERATOR_KEY)
    return AuditedCustody(vault, tmp_path / "audit.jsonl")


def test_chain_writer_publishes_with_audited_operator_key(tmp_path):
    audited = make_audited_operator(tmp_path)
    eth = FakeEth()
    writer = ChainDataMarketWriter(
        FakeW3(eth), FakeMarket(eth), audited, "operator", 48850
    )

    assert writer.dataset_root(CID) == ZERO_ROOT
    tx_hash = writer.publish(CID, ROOT)

    assert tx_hash == "0xtxhash"
    assert eth.publish_args == (
        bytes.fromhex(CID[2:]),
        bytes.fromhex(ROOT[2:]),
    )
    assert eth.params["chainId"] == 48850
    assert eth.params["gasPrice"] == 0
    assert eth.params["nonce"] == 0
    log = audited.log_path.read_text(encoding="utf-8")
    assert OPERATOR_KEY not in log
    record = json.loads(log.strip())
    assert record["action"] == "load"
    assert record["result"] == "ok"
    assert record["context"] == {"purpose": "data_publish", "contest_id": CID}

    with pytest.raises(DataServiceError):
        writer.publish(CID, ROOT)
    assert len(audited.log_path.read_text(encoding="utf-8").splitlines()) == 1


def test_chain_writer_revert_and_raw_custody(tmp_path):
    audited = make_audited_operator(tmp_path)
    eth = FakeEth(status=0)
    writer = ChainDataMarketWriter(
        FakeW3(eth), FakeMarket(eth), audited, "operator", 48850
    )
    with pytest.raises(DataServiceError):
        writer.publish(CID, ROOT)

    vault = Custody(tmp_path / "raw-vault.json", MASTER, scrypt_n=2**14)
    vault.store("operator", OPERATOR_KEY)
    raw_eth = FakeEth()
    raw_writer = ChainDataMarketWriter(
        FakeW3(raw_eth), FakeMarket(raw_eth), vault, "operator", 48850
    )
    with pytest.raises(DataServiceError):
        raw_writer.publish(CID, ROOT)


def test_chain_writer_rejects_already_published_without_audit(tmp_path):
    audited = make_audited_operator(tmp_path)
    eth = FakeEth()
    eth.root = bytes.fromhex(ROOT[2:])
    writer = ChainDataMarketWriter(
        FakeW3(eth), FakeMarket(eth), audited, "operator", 48850
    )

    with pytest.raises(DataServiceError):
        writer.publish(CID, ROOT)
    assert not audited.log_path.exists()
