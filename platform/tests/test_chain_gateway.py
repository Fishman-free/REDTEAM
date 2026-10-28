"""Chain gateway transaction/audit tests with a fake web3; no network."""

import json
from types import SimpleNamespace

import pytest
from eth_account import Account
from web3 import Web3
from web3.datastructures import AttributeDict

from redteam_platform.chain_gateway import GatewayError, Web3ChainGateway
from redteam_platform.custody import Custody
from redteam_platform.custody_audit import AuditedCustody

ONE = 10**18
CONTEST = "0x" + "44" * 32
MSG_HASH = "0x" + "ab" * 32
DEFENSE_HASH = "0x" + "55" * 32
WALLET = Web3.to_checksum_address("0x" + "22" * 20)
ARENA = Web3.to_checksum_address("0x" + "88" * 20)
TREASURY = Web3.to_checksum_address("0x" + "66" * 20)
RTM = Web3.to_checksum_address("0x" + "77" * 20)
DEFENDER = Web3.to_checksum_address("0x" + "11" * 20)
MASTER = "aa" * 32


class FakeFunctionCall:
    def __init__(self, eth, name, args):
        self.eth, self.name, self.args = eth, name, args

    def call(self):
        self.eth.reads.append((self.name, self.args))
        return self.eth.values[self.name]

    def build_transaction(self, params):
        self.eth.builds.append((self.name, self.args, dict(params)))
        return {"data": "0x", **params}


class FakeFunctions:
    def __init__(self, eth):
        self.eth = eth

    def __getattr__(self, name):
        def call(*args):
            return FakeFunctionCall(self.eth, name, args)

        return call


class FakeEvents:
    def __init__(self, eth):
        self.eth = eth

    def __getattr__(self, name):
        return SimpleNamespace(
            process_receipt=lambda receipt, **kwargs: [
                {"args": {"id": bytes.fromhex(CONTEST[2:])}}
            ]
        )


class FakeContract:
    def __init__(self, eth):
        self.functions = FakeFunctions(eth)
        self.events = FakeEvents(eth)


class FakeSigner:
    def __init__(self, eth):
        self.eth = eth

    def sign_transaction(self, tx, key):
        self.eth.keys.append(key)
        return SimpleNamespace(raw_transaction=b"raw")


class FakeEth:
    def __init__(self):
        self.values = {}
        self.reads = []
        self.builds = []
        self.keys = []
        self.status = 1
        self.account = FakeSigner(self)

    def get_transaction_count(self, address):
        return 0

    def send_raw_transaction(self, raw):
        return "0xtxhash"

    def wait_for_transaction_receipt(self, tx_hash, timeout=None):
        return AttributeDict({"status": self.status, "logs": []})


class FakeW3:
    def __init__(self, eth):
        self.eth = eth


def make_gateway(tmp_path, *, operator_key=None):
    operator = Account.create()
    treasury_owner = Account.create()
    wallet = Account.create()
    vault = Custody(tmp_path / "vault.json", MASTER, scrypt_n=2**14)
    vault.store("operator", operator_key or operator.key.to_0x_hex())
    vault.store("treasury-owner", treasury_owner.key.to_0x_hex())
    vault.store("wallet:test", wallet.key.to_0x_hex())
    audited = AuditedCustody(vault, tmp_path / "audit.jsonl")
    eth = FakeEth()
    contracts = {
        "Arena": FakeContract(eth),
        "RTMToken": FakeContract(eth),
        "Treasury": FakeContract(eth),
    }
    gateway = Web3ChainGateway(
        FakeW3(eth),
        contracts,
        audited,
        operator_entry="operator",
        treasury_owner_entry="treasury-owner",
        chain_id=48850,
        operator_address=operator.address,
        treasury_address=TREASURY,
        treasury_owner_address=treasury_owner.address,
        rtm_address=RTM,
        arena_address=ARENA,
    )
    return gateway, eth, audited, operator, treasury_owner, wallet


def audit_records(audited):
    return [
        json.loads(line)
        for line in audited.log_path.read_text(encoding="utf-8").splitlines()
    ]


def test_create_contest_checks_allowance_and_parses_event(tmp_path):
    gateway, eth, audited, operator, _owner, _wallet = make_gateway(tmp_path)
    eth.values["allowance"] = 50 * ONE

    contest_id, tx_hash = gateway.create_contest(
        DEFENDER, WALLET, 50 * ONE, 24 * 3600, 1000
    )

    assert contest_id == CONTEST
    assert tx_hash == "0xtxhash"
    name, args, params = eth.builds[0]
    assert name == "createContest"
    assert args == (DEFENDER, WALLET, 50 * ONE, 24 * 3600, 1000)
    assert params["from"] == operator.address
    assert params["gasPrice"] == 0
    assert params["chainId"] == 48850
    records = audit_records(audited)
    assert records[-1]["action"] == "load"
    assert records[-1]["context"] == {
        "purpose": "create_contest",
        "wallet_address": WALLET,
    }
    assert "0x" + bytes(operator.key).hex() not in audited.log_path.read_text(encoding="utf-8")


def test_create_contest_requires_allowance_without_building(tmp_path):
    gateway, eth, _audited, _operator, _owner, _wallet = make_gateway(tmp_path)
    eth.values["allowance"] = 0

    with pytest.raises(GatewayError):
        gateway.create_contest(DEFENDER, WALLET, 50 * ONE, 24 * 3600, 1000)
    assert eth.builds == []


def test_mark_delivered_and_faults_build_expected_args(tmp_path):
    gateway, eth, _audited, _operator, _owner, _wallet = make_gateway(tmp_path)

    assert gateway.mark_delivered(CONTEST, DEFENDER, MSG_HASH) == "0xtxhash"
    assert gateway.report_defender_fault(CONTEST) == "0xtxhash"
    assert gateway.retire_mining(CONTEST) == "0xtxhash"

    names = [build[0] for build in eth.builds]
    assert names == ["markDelivered", "reportDefenderFault", "retireMining"]
    assert eth.builds[0][1] == (bytes.fromhex(CONTEST[2:]), DEFENDER, bytes.fromhex(MSG_HASH[2:]))
    assert eth.builds[1][1] == (bytes.fromhex(CONTEST[2:]),)


def test_treasury_withdraw_uses_owner_entry_and_audits(tmp_path):
    gateway, eth, audited, _operator, owner, _wallet = make_gateway(tmp_path)

    tx = gateway.treasury_withdraw(WALLET, ONE)

    assert tx == "0xtxhash"
    name, args, params = eth.builds[0]
    assert name == "withdraw"
    assert args == (RTM, WALLET, ONE)
    assert params["from"] == owner.address
    record = audit_records(audited)[-1]
    assert record["entry_id"] == "treasury-owner"
    assert record["context"] == {
        "purpose": "treasury_prefund",
        "wallet_address": WALLET,
        "chain_id": "48850",
    }


def test_wallet_transfer_and_key_mismatch(tmp_path):
    gateway, eth, _audited, _operator, _owner, wallet = make_gateway(tmp_path)

    assert gateway.wallet_transfer(
        "wallet:test", wallet.address, TREASURY, ONE
    ) == "0xtxhash"
    assert eth.builds[0][0] == "transfer"
    assert eth.builds[0][1] == (TREASURY, ONE)
    assert eth.builds[0][2]["from"] == wallet.address

    bad = Web3ChainGateway(
        gateway._w3,
        {"Arena": gateway._arena, "RTMToken": gateway._rtm, "Treasury": gateway._treasury},
        gateway._custody,
        operator_entry="operator",
        treasury_owner_entry="treasury-owner",
        chain_id=48850,
        operator_address=wallet.address,
        treasury_address=TREASURY,
        treasury_owner_address=wallet.address,
        rtm_address=RTM,
        arena_address=ARENA,
    )
    with pytest.raises(GatewayError, match="expected address"):
        bad.mark_delivered(CONTEST, DEFENDER, MSG_HASH)


def test_contest_info_and_reads(tmp_path):
    gateway, eth, _audited, _operator, _owner, _wallet = make_gateway(tmp_path)
    eth.values["contestInfo"] = (
        DEFENDER,
        WALLET,
        50 * ONE,
        1000,
        bytes.fromhex("00" * 32),
        100,
        200,
        0,
        0,
        False,
        3,
        False,
    )
    eth.values["activeMiningCount"] = 2
    eth.values["retiredDefenseHash"] = True
    eth.values["activeDefenseHash"] = bytes.fromhex("00" * 32)
    eth.values["balanceOf"] = 7
    eth.values["allowance"] = 9

    info = gateway.contest_info(CONTEST)

    assert info["defender"] == DEFENDER
    assert info["wallet"] == WALLET
    assert info["stake"] == str(50 * ONE)
    assert info["stake_bps"] == 1000
    assert info["state"] == 0
    assert info["is_mining"] is False
    assert info["attacker_count"] == 3
    assert gateway.active_mining_count() == 2
    assert gateway.defense_hash_retired(DEFENSE_HASH) is True
    assert gateway.active_defense_hash(DEFENSE_HASH) == "0x" + "00" * 32
    assert gateway.rtm_balance(WALLET) == 7
    assert gateway.allowance(DEFENDER) == 9


def test_receipt_failure_raises(tmp_path):
    gateway, eth, _audited, _operator, _owner, _wallet = make_gateway(tmp_path)
    eth.values["allowance"] = 50 * ONE
    eth.status = 0

    with pytest.raises(GatewayError, match="reverted"):
        gateway.create_contest(DEFENDER, WALLET, 50 * ONE, 24 * 3600, 1000)
