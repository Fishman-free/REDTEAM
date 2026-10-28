"""Wallet tool tests with a fake chain; no RPC, no signing library."""

import json
import threading
import time
from types import SimpleNamespace

import pytest
from web3 import Web3
from web3.datastructures import AttributeDict

from benchmark.harness import TOOL_DEFINITIONS
from redteam_platform.agent_tools import WalletTools, tool_definitions
from redteam_platform.custody import Custody
from redteam_platform.custody_audit import AuditedCustody

WALLET = "0x" + "10" * 20
ATTACKER = "0x" + "aa" * 20
KEY = "0x" + "11" * 32
MASTER = "aa" * 32
CONTEXT = {
    "purpose": "runner",
    "contest_id": "0x" + "ab" * 32,
    "runner_id": "runner-1",
    "wallet_address": WALLET,
}


class FakeCall:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


class FakeTransfer:
    def __init__(self, eth, to, amount):
        self.eth, self.to, self.amount = eth, to, amount

    def build_transaction(self, params):
        self.eth.builds.append(
            {"to": self.to, "amount": self.amount, "params": dict(params)}
        )
        if self.eth.build_error is not None:
            raise self.eth.build_error
        return {"to": self.to, "amount": self.amount, **params}


class FakeFunctions:
    def __init__(self, eth):
        self.eth = eth

    def balanceOf(self, address):
        if self.eth.balance_error is not None:
            raise self.eth.balance_error
        return FakeCall(self.eth.balance)

    def transfer(self, to, amount):
        return FakeTransfer(self.eth, to, amount)


class FakeRTM:
    def __init__(self, eth):
        self.functions = FakeFunctions(eth)


class FakeAccount:
    def __init__(self, eth):
        self.eth = eth

    def sign_transaction(self, tx, key):
        self.eth.signed_keys.append(key)
        return SimpleNamespace(raw_transaction=b"raw-" + str(tx["nonce"]).encode())


class FakeEth:
    def __init__(
        self,
        *,
        balance=0,
        status=1,
        send_error=None,
        build_error=None,
        balance_error=None,
        wait_delay=0.0,
        receipt_error=None,
    ):
        self.balance = balance
        self.status = status
        self.send_error = send_error
        self.build_error = build_error
        self.balance_error = balance_error
        self.wait_delay = wait_delay
        self.receipt_error = receipt_error
        self.chain_id = 48850
        self.account = FakeAccount(self)
        self.signed_keys = []
        self.builds = []
        self.sent = []
        self.active = 0
        self.max_active = 0
        self._nonce = 0
        self._lock = threading.Lock()

    def get_transaction_count(self, address):
        with self._lock:
            nonce = self._nonce
            self._nonce += 1
            return nonce

    def send_raw_transaction(self, raw):
        if self.send_error is not None:
            raise self.send_error
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.sent.append(raw)
        return "0xtxhash"

    def wait_for_transaction_receipt(self, tx_hash, timeout=None):
        time.sleep(self.wait_delay)
        with self._lock:
            self.active -= 1
        if self.receipt_error is not None:
            raise self.receipt_error
        return AttributeDict({"status": self.status})


class FakeW3:
    def __init__(self, eth):
        self.eth = eth


def make_tools(*, receipt_timeout=60.0, **eth_kwargs):
    eth = FakeEth(**eth_kwargs)
    return WalletTools(
        FakeW3(eth),
        FakeRTM(eth),
        WALLET,
        KEY,
        receipt_timeout=receipt_timeout,
    ), eth


def test_tool_surface_is_fixed_and_copied():
    definitions = tool_definitions()

    assert definitions == TOOL_DEFINITIONS
    assert {tool["function"]["name"] for tool in definitions} == {
        "get_balance",
        "transfer_rtm",
    }

    definitions[0]["function"]["name"] = "mutated"
    assert tool_definitions() == TOOL_DEFINITIONS


def test_get_balance_returns_wei_string():
    tools, eth = make_tools(balance=10**18)

    assert tools.call("get_balance", {}) == {"result": {"balance": str(10**18)}}


def test_get_balance_failure_is_generic():
    tools, _eth = make_tools(balance_error=RuntimeError("rpc down"))

    receipt = tools.call("get_balance", {})

    assert receipt == {"result": {"status": "failed", "reason": "balance unavailable"}}


def test_transfer_success_uses_signed_real_transaction_shape():
    tools, eth = make_tools(balance=10**18)

    receipt = tools.call(
        "transfer_rtm", {"to": ATTACKER.lower(), "amount": str(10**18)}
    )

    expected_to = Web3.to_checksum_address(ATTACKER)
    assert receipt == {
        "result": {"status": "ok", "tx": "0xtxhash"},
        "to": expected_to,
        "amount": 10**18,
    }
    build = eth.builds[0]
    assert build["to"] == expected_to
    assert build["params"]["from"] == Web3.to_checksum_address(WALLET)
    assert build["params"]["nonce"] == 0
    assert build["params"]["gas"] == 400_000
    assert build["params"]["gasPrice"] == 0
    assert build["params"]["chainId"] == 48850
    assert eth.signed_keys == [KEY]
    assert eth.sent == [b"raw-0"]


def test_transfer_integer_amount_is_accepted():
    tools, eth = make_tools()

    receipt = tools.call("transfer_rtm", {"to": ATTACKER, "amount": 1})

    assert receipt["result"]["status"] == "ok"
    assert eth.builds[0]["amount"] == 1


@pytest.mark.parametrize(
    "amount",
    [
        "0",
        "00",
        "-1",
        "1.5",
        " 1",
        "1 ",
        "0x10",
        "１",
        "1" * 79,
        0,
        -1,
        1.5,
        True,
        None,
    ],
)
def test_invalid_amounts_fail_generically_without_chain_calls(amount):
    tools, eth = make_tools()

    receipt = tools.call("transfer_rtm", {"to": ATTACKER, "amount": amount})

    assert receipt == {
        "result": {"status": "failed", "reason": "transfer failed"}
    }
    assert eth.builds == []


@pytest.mark.parametrize("to", ["", "0x123", "not-an-address", None, 123])
def test_invalid_addresses_fail_generically_without_chain_calls(to):
    tools, eth = make_tools()

    receipt = tools.call("transfer_rtm", {"to": to, "amount": "1"})

    assert receipt == {
        "result": {"status": "failed", "reason": "transfer failed"}
    }
    assert eth.builds == []


def test_reverted_receipt_is_scrubbed():
    tools, _eth = make_tools(status=0)

    receipt = tools.call("transfer_rtm", {"to": ATTACKER, "amount": "1"})

    assert receipt == {
        "result": {"status": "failed", "reason": "transfer failed"}
    }
    assert "TargetTransferRestricted" not in json.dumps(receipt)
    assert "revert" not in json.dumps(receipt).lower()


def test_transport_and_build_errors_are_scrubbed():
    send_tools, _ = make_tools(send_error=RuntimeError("boom"))
    build_tools, _ = make_tools(build_error=RuntimeError("boom"))
    receipt_tools, _ = make_tools(receipt_error=RuntimeError("boom"))

    for tools in (send_tools, build_tools, receipt_tools):
        receipt = tools.call("transfer_rtm", {"to": ATTACKER, "amount": "1"})
        assert receipt == {
            "result": {"status": "failed", "reason": "transfer failed"}
        }
        assert "boom" not in json.dumps(receipt)


def test_transfers_are_serialized_per_wallet():
    tools, eth = make_tools(wait_delay=0.05)
    receipts = []

    def run():
        receipts.append(
            tools.call("transfer_rtm", {"to": ATTACKER, "amount": "1"})
        )

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [receipt["result"]["status"] for receipt in receipts] == ["ok", "ok"]
    assert eth.max_active == 1
    assert [build["params"]["nonce"] for build in eth.builds] == [0, 1]


def test_unknown_tool_raises():
    tools, _eth = make_tools()

    with pytest.raises(ValueError):
        tools.call("delete_everything", {})


def test_private_key_is_validated_and_never_in_repr():
    with pytest.raises(ValueError) as excinfo:
        WalletTools(FakeW3(FakeEth()), FakeRTM(FakeEth()), WALLET, "not-a-key")
    assert "not-a-key" not in str(excinfo.value)

    tools, _eth = make_tools()
    assert KEY not in repr(tools)
    assert KEY[2:] not in repr(tools)


def test_from_custody_requires_and_writes_audit(tmp_path):
    vault = Custody(tmp_path / "vault.json", MASTER, scrypt_n=2**14)
    vault.store("wallet-w", KEY)
    audited = AuditedCustody(vault, tmp_path / "audit.jsonl")
    eth = FakeEth()
    tools = WalletTools.from_custody(
        audited,
        entry_id="wallet-w",
        context=CONTEXT,
        w3=FakeW3(eth),
        rtm_contract=FakeRTM(eth),
        wallet_address=WALLET,
    )

    assert tools.address == Web3.to_checksum_address(WALLET)
    log = audited.log_path.read_text(encoding="utf-8")
    assert KEY not in log
    record = json.loads(log.strip())
    assert record["action"] == "load"
    assert record["result"] == "ok"
    assert record["context"] == CONTEXT


def test_from_custody_rejects_raw_un_audited_custody(tmp_path):
    vault = Custody(tmp_path / "vault.json", MASTER, scrypt_n=2**14)
    vault.store("wallet-w", KEY)
    eth = FakeEth()

    with pytest.raises(TypeError):
        WalletTools.from_custody(
            vault,
            entry_id="wallet-w",
            context=CONTEXT,
            w3=FakeW3(eth),
            rtm_contract=FakeRTM(eth),
            wallet_address=WALLET,
        )
