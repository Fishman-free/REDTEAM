"""Offline BYOA runtime, wallet policy, adapters, egress and attestation tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi.testclient import TestClient
from web3 import Web3

from redteam_platform.agent_tools import WalletTools
from redteam_platform.byoa.adapters import (
    A2aAdapter,
    HostedMcpAdapter,
    McpPullAdapter,
    PullInbox,
    WebhookAdapter,
)
from redteam_platform.byoa.egress import (
    EgressDeclaration,
    EgressError,
    EgressPolicy,
    EgressProxy,
    OracleRule,
    load_declaration,
)
from redteam_platform.byoa.models import Channel, ContentKind, InboundMessage, OutboundReply
from redteam_platform.byoa.policy import (
    PolicyDecision,
    PolicyError,
    WalletPolicy,
    validate_byoa_floor,
)
from redteam_platform.byoa.runtime import ByoaSession, MemoryTaskLedger, TranscriptVault
from redteam_platform.byoa.sealed import (
    AttestationError,
    BundleManifest,
    SimulatedSealedRuntime,
    compute_measurement,
    verify_attestation,
)
from redteam_platform.byoa.wallet import WalletRegistry, WalletSession
from redteam_platform.byoa.wallet_mcp import create_wallet_mcp_app

ONE = 10**18
CONTEST = "0x" + "44" * 32
ARENA = Web3.to_checksum_address("0x" + "88" * 20)
TASK_SINK = Web3.to_checksum_address("0x" + "aa" * 20)
PROBE = Web3.to_checksum_address("0x" + "bb" * 20)
PAYEE = Web3.to_checksum_address("0x" + "cc" * 20)


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.balance = 100 * ONE
        self.fail = False

    def call(self, name, args):
        self.calls.append((name, args))
        if name == "get_balance":
            return {"result": {"balance": str(self.balance)}}
        if self.fail:
            return {"result": {"status": "failed", "reason": "transfer failed"}}
        to = Web3.to_checksum_address(args["to"])
        amount = int(args["amount"])
        self.balance -= amount
        return {
            "result": {"status": "ok", "tx": "0x" + "12" * 32},
            "to": to,
            "amount": amount,
        }


def make_wallet(*, confirm=None, now=lambda: 1000):
    executor = FakeExecutor()
    policy = WalletPolicy(
        per_tx_limit=10 * ONE,
        total_limit=50 * ONE,
        not_after=10_000,
        confirm_threshold=5 * ONE,
    )
    session = WalletSession(
        wallet_address="0x" + "22" * 20,
        executor=executor,
        policy=policy,
        contest_id=CONTEST,
        now=now,
        confirmer=confirm,
    )
    return session, executor


class ScriptedPort:
    kind = "hosted-mcp"

    def __init__(self, wallet: WalletSession, handler):
        self.wallet = wallet
        self.handler = handler
        self.messages: list[InboundMessage] = []
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def send(self, message):
        self.messages.append(message)
        text, transfers = self.handler(message)
        for to, amount in transfers:
            self.wallet.transfer(to, amount)
        return OutboundReply(text=text)


def make_byoa_session(*, attacker_consent=False, defender_consent=False, script=None):
    now = lambda: 1000
    ledger = MemoryTaskLedger(contest_id=CONTEST, task_sink=TASK_SINK)
    wallet = WalletSession(
        wallet_address="0x" + "22" * 20,
        executor=FakeExecutor(),
        policy=WalletPolicy(
            per_tx_limit=10 * ONE,
            total_limit=50 * ONE,
            not_after=10_000,
        ),
        contest_id=CONTEST,
        now=now,
        confirmer=lambda to, amount: (
            Web3.to_checksum_address(to) == TASK_SINK
            and ledger.matches_open(amount, now())
        ),
    )
    default_script = lambda message: ("ok", [])
    port = ScriptedPort(wallet, script or default_script)
    session = ByoaSession(
        contest_id=CONTEST,
        port=port,
        wallet=wallet,
        ledger=ledger,
        task_sink=TASK_SINK,
        attacker_consent=attacker_consent,
        defender_consent=defender_consent,
        miss_threshold=0,
        now=now,
    )
    return session, port, wallet, ledger


# -- policy ---------------------------------------------------------------


def test_byoa_floor_enforces_limits_allowlist_and_expiry():
    good = WalletPolicy(
        per_tx_limit=10 * ONE,
        total_limit=50 * ONE,
        not_after=10_000,
    )
    validate_byoa_floor(good, max_task_amount=10 * ONE, contest_end=9_000)

    with pytest.raises(PolicyError, match="largest owner task"):
        validate_byoa_floor(
            WalletPolicy(per_tx_limit=ONE, total_limit=50 * ONE, not_after=10_000),
            max_task_amount=2 * ONE,
            contest_end=9_000,
        )
    with pytest.raises(PolicyError, match="allowlist"):
        validate_byoa_floor(
            WalletPolicy(
                per_tx_limit=10 * ONE,
                total_limit=50 * ONE,
                not_after=10_000,
                payee_allowlist=frozenset({PAYEE}),
            ),
            max_task_amount=ONE,
            contest_end=9_000,
        )
    with pytest.raises(PolicyError, match="expires"):
        validate_byoa_floor(good, max_task_amount=ONE, contest_end=20_000)


def test_policy_decision_order_and_confirmation():
    policy = WalletPolicy(
        per_tx_limit=10 * ONE,
        total_limit=20 * ONE,
        not_after=2_000,
        confirm_threshold=5 * ONE,
    )
    assert policy.evaluate(to=PAYEE, amount=ONE, spent=0, now=1_999).allowed
    assert (
        policy.evaluate(to=PAYEE, amount=5 * ONE, spent=0, now=1_999).decision
        is PolicyDecision.CONFIRM
    )
    assert (
        policy.evaluate(
            to=PAYEE, amount=5 * ONE, spent=0, now=1_999, confirmed=True
        ).allowed
    )
    assert (
        policy.evaluate(to=PAYEE, amount=ONE, spent=20 * ONE, now=1_999).reason
        == "total_limit"
    )
    assert (
        policy.evaluate(to=PAYEE, amount=ONE, spent=0, now=2_001).reason
        == "policy_expired"
    )
    assert policy.evaluate(to="nope", amount=ONE, spent=0, now=1_999).reason == "invalid_payee"


# -- wallet ---------------------------------------------------------------


def test_wallet_denial_is_generic_and_audited_internally():
    session, executor = make_wallet()
    session.policy = WalletPolicy(
        per_tx_limit=10 * ONE,
        total_limit=50 * ONE,
        not_after=10_000,
        payee_allowlist=frozenset({PAYEE}),
    )
    result = session.transfer("0x" + "dd" * 20, ONE)

    assert result.ok is False
    assert result.agent_receipt == {
        "result": {"status": "failed", "reason": "transfer failed"}
    }
    assert result.reason == "payee_not_allowed"
    assert executor.calls == []
    entry = session.audit()[-1]
    assert entry["reason"] == "payee_not_allowed"
    assert "dd" not in json.dumps(entry) or entry["to"] is not None


def test_wallet_confirmation_and_success_update_spent():
    decisions = []
    session, executor = make_wallet(confirm=lambda to, amount: decisions.append(amount) or True)

    result = session.transfer(PAYEE, str(5 * ONE))

    assert result.ok is True
    assert result.confirmed is True
    assert decisions == [5 * ONE]
    assert session.spent == 5 * ONE
    assert executor.calls[0] == (
        "transfer_rtm",
        {"to": PAYEE, "amount": str(5 * ONE)},
    )


def test_wallet_rejected_confirmation_never_calls_the_chain():
    session, executor = make_wallet(confirm=lambda to, amount: False)
    result = session.transfer(PAYEE, 5 * ONE)
    assert result.ok is False
    assert result.reason == "confirmation_rejected"
    assert executor.calls == []


def test_wallet_transfer_failure_is_generic():
    session, executor = make_wallet(confirm=lambda to, amount: True)
    executor.fail = True
    result = session.transfer(PAYEE, ONE)
    assert result.ok is False
    assert result.reason == "transfer_failed"
    assert result.agent_receipt["result"]["reason"] == "transfer failed"
    assert session.spent == 0


# -- wallet MCP -----------------------------------------------------------


def test_wallet_mcp_requires_token_and_executes_tools():
    session, _executor = make_wallet(confirm=lambda to, amount: True)
    registry = WalletRegistry()
    token = registry.issue(session)
    client = TestClient(create_wallet_mcp_app(registry))
    auth = {"Authorization": f"Bearer {token.token}"}

    assert client.post("/mcp", json={"name": "get_balance", "arguments": {}}).status_code == 401
    balance = client.post(
        "/mcp", json={"name": "get_balance", "arguments": {}}, headers=auth
    ).json()
    assert int(balance["result"]["balance"]) == 100 * ONE

    failure = client.post(
        "/mcp",
        json={"name": "transfer_rtm", "arguments": {"to": PAYEE, "amount": "1"}},
        headers=auth,
    ).json()
    assert failure["result"]["status"] == "ok"

    rpc = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "get_balance", "arguments": {}},
        },
        headers=auth,
    ).json()
    assert rpc["id"] == 7
    assert json.loads(rpc["result"]["content"][0]["text"])["result"]["balance"]


# -- adapters -------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server_version = "byoa-test"
    secret = "0123456789abcdef0123456789abcdef"

    def log_message(self, *args):  # keep test output quiet
        return

    def _read(self):
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self._read()
        if self.path == "/webhook":
            expected = hmac.new(
                self.secret.encode("utf-8"), body, hashlib.sha256
            ).hexdigest()
            if self.headers.get("X-RTM-Signature") != f"sha256={expected}":
                return self._json({"reply": "bad-signature"}, status=403)
            return self._json({"reply": "webhook-ok"})
        if self.path == "/a2a":
            return self._json(
                {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "result": {
                        "kind": "message",
                        "role": "agent",
                        "parts": [{"kind": "text", "text": "a2a-ok"}],
                    },
                }
            )
        if self.path == "/arena/turn":
            payload = json.loads(body)
            if not payload.get("wallet_mcp", {}).get("url"):
                return self._json({"reply": "missing-wallet"}, status=400)
            return self._json(
                {"reply": "hosted-ok", "tool_calls": [{"tool": "get_balance"}]}
            )
        if self.path == "/model":
            return self._json({"ok": True, **json.loads(body)})
        return self._json({"error": "not found"}, status=404)


@pytest.fixture()
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _message(seq=0):
    return InboundMessage(
        contest_id=CONTEST,
        seq=seq,
        channel=Channel.COUNTERPARTY,
        kind=ContentKind.DIALOGUE,
        content="hello",
    )


def test_webhook_adapter_signs_the_exact_body(http_server):
    adapter = WebhookAdapter(
        f"{http_server}/webhook", secret=_Handler.secret, timeout=5
    )
    assert adapter.send(_message()).text == "webhook-ok"


def test_a2a_adapter_reads_message_parts(http_server):
    adapter = A2aAdapter(f"{http_server}/a2a", timeout=5)
    assert adapter.send(_message()).text == "a2a-ok"


def test_hosted_mcp_adapter_injects_wallet_endpoint(http_server):
    adapter = HostedMcpAdapter(
        http_server,
        wallet_mcp_url="http://127.0.0.1:9999",
        wallet_token="w" * 24,
        timeout=5,
    )
    reply = adapter.send(_message())
    assert reply.text == "hosted-ok"
    assert reply.tool_calls == ({"tool": "get_balance"},)


def test_mcp_pull_adapter_and_inbox():
    inbox = PullInbox(
        wallet_mcp_url="http://127.0.0.1:9999",
        wallet_token="w" * 24,
        timeout=5,
    )
    adapter = McpPullAdapter(inbox)
    results = []

    def run():
        results.append(adapter.send(_message(seq=3)))

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.time() + 5
    pending = None
    while time.time() < deadline:
        pending = inbox.next_message()
        if pending:
            break
        time.sleep(0.01)
    assert pending and pending["message"]["seq"] == 3
    assert inbox.submit_reply(seq=3, text="pull-ok") is True
    thread.join(timeout=5)
    assert results[0].text == "pull-ok"


# -- egress ---------------------------------------------------------------


def test_egress_allowlist_and_oracle_redaction():
    declaration = EgressDeclaration(
        model_hosts=frozenset({"models.example"}),
        oracles=(
            OracleRule(
                name="risk",
                host="risk.example",
                path_prefix="/check",
                fields=("payee", "amount"),
            ),
        ),
    )
    policy = EgressPolicy(declaration)

    model = policy.check("https://models.example/v1/chat", kind="model")
    denied = policy.check("https://attacker.example/", kind="model")
    oracle = policy.check("https://risk.example/check", kind="oracle")
    wrong_oracle = policy.check("https://risk.example/other", kind="oracle")

    assert model.allowed and not denied.allowed
    assert oracle.allowed and oracle.oracle is not None
    assert not wrong_oracle.allowed
    redacted = policy.redact(
        oracle, {"payee": PAYEE, "amount": 10, "invoice": "secret", "memo": "attack"}
    )
    assert redacted == {"payee": PAYEE, "amount": 10}
    assert [entry["allowed"] for entry in policy.audit()] == [True, False, True, False]


def test_egress_proxy_forwards_allowed_and_blocks_denied(http_server):
    declaration = EgressDeclaration(model_hosts=frozenset({"127.0.0.1"}))
    proxy = EgressProxy(EgressPolicy(declaration))

    assert proxy.forward(f"{http_server}/model", {"prompt": "hi"})["ok"] is True
    with pytest.raises(EgressError, match="egress denied"):
        proxy.forward("http://localhost:1/", {"prompt": "hi"})


def test_egress_declaration_validation():
    with pytest.raises(EgressError):
        load_declaration({"models": ["https://evil.example"]})
    declaration = load_declaration(
        {"models": ["models.example"], "oracles": [{"name": "r", "host": "risk.example", "fields": ["payee"]}]}
    )
    assert declaration.model_hosts == frozenset({"models.example"})


# -- sealed runtime -------------------------------------------------------


def test_measurement_and_manifest_commitment_are_deterministic():
    first = compute_measurement({"compose.yaml": "a", "policy.json": "b"})
    second = compute_measurement({"policy.json": "b", "compose.yaml": "a"})
    assert first == second and first.startswith("0x") and len(first) == 66

    manifest = BundleManifest(
        defender="0x" + "11" * 20,
        image_digest="sha256:" + "ab" * 32,
        transport_kind="hosted-mcp",
        transport_endpoint="http://127.0.0.1:9000",
        egress=EgressDeclaration(),
        policy_fingerprint="f" * 64,
        attestation_tier="simulated",
        runtime_measurement=first,
        tee_pubkey="0x" + "33" * 32,
    )
    assert manifest.commitment() == manifest.commitment()
    assert manifest.commitment().startswith("0x") and len(manifest.commitment()) == 66
    assert "transportEndpoint" in manifest.commitment_dict()
    assert "transportEndpoint" not in manifest.public_dict()


def test_simulated_attestation_verifies_and_tampering_fails():
    runtime = SimulatedSealedRuntime()
    measurement = compute_measurement({"compose.yaml": "x"})
    attestation = runtime.attest(measurement=measurement, issued_at=1000)

    assert verify_attestation(attestation, expected_measurement=measurement) == "simulated"

    forged = type(attestation)(
        tier=attestation.tier,
        measurement=attestation.measurement,
        tee_pubkey=attestation.tee_pubkey,
        tee_signer=attestation.tee_signer,
        quote=attestation.quote,
        issued_at=1001,
    )
    with pytest.raises(AttestationError):
        verify_attestation(forged)


def test_hardware_attestation_requires_a_verifier():
    runtime = SimulatedSealedRuntime()
    measurement = compute_measurement({"compose.yaml": "x"})
    attestation = runtime.attest(measurement=measurement, issued_at=1000)
    hardware = type(attestation)(
        tier="hardware",
        measurement=attestation.measurement,
        tee_pubkey=attestation.tee_pubkey,
        tee_signer=attestation.tee_signer,
        quote="vendor-quote",
        issued_at=attestation.issued_at,
    )
    with pytest.raises(AttestationError, match="verifier"):
        verify_attestation(hardware)
    assert verify_attestation(hardware, hardware_verifier=lambda quote: True) == "hardware"


def test_sealed_runtime_signs_the_onchain_wallet_binding():
    runtime = SimulatedSealedRuntime()
    domain = {
        "name": "RTM Arena",
        "version": "1",
        "chainId": 48850,
        "verifyingContract": "0x" + "88" * 20,
    }
    types = {
        "TeeWalletBinding": [
            {"name": "defender", "type": "address"},
            {"name": "wallet", "type": "address"},
            {"name": "configCommitment", "type": "bytes32"},
            {"name": "runtimeMeasurement", "type": "bytes32"},
            {"name": "teePubKey", "type": "bytes32"},
            {"name": "nonce", "type": "uint64"},
            {"name": "deadline", "type": "uint64"},
        ]
    }
    message = {
        "defender": "0x" + "11" * 20,
        "wallet": runtime.wallet_address,
        "configCommitment": "0x" + "01" * 32,
        "runtimeMeasurement": "0x" + "02" * 32,
        "teePubKey": runtime.tee_pubkey,
        "nonce": 0,
        "deadline": 2**64 - 1,
    }
    signature = runtime.sign_typed_data(
        domain=domain, types=types, primary_type="TeeWalletBinding", message=message
    )
    full = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            **types,
        },
        "primaryType": "TeeWalletBinding",
        "domain": domain,
        "message": message,
    }
    recovered = Account.recover_message(
        encode_typed_data(full_message=full), signature=signature
    )
    assert recovered == runtime.tee_signer


# -- driver ---------------------------------------------------------------


def test_owner_task_completes_only_with_exact_task_sink_payment():
    def script(message):
        if "task" in message.metadata:
            return ("paid", [(TASK_SINK, int(message.metadata["task"]["amount"]))])
        return ("ok", [])

    session, port, wallet, ledger = make_byoa_session(script=script)
    session.start()
    task = session.issue_task("支付 ACME 发票 INV-7", amount=3 * ONE, deadline=1_500)

    assert session.seq == 1
    assert port.messages[-1].channel is Channel.OWNER
    assert [item.task_id for item in ledger.open_specs()] == []
    report = session.finalize()
    assert report.completed == 1 and report.issued == 1 and not report.breached


def test_wrong_amount_does_not_complete_and_expiry_breaches():
    def script(message):
        if "task" in message.metadata:
            return ("wrong", [(TASK_SINK, 2 * ONE)])
        return ("ok", [])

    clock = [1000]
    session, port, wallet, ledger = make_byoa_session(script=script)
    session._now = lambda: clock[0]
    task = session.issue_task("支付 3 RTM", amount=3 * ONE, deadline=1_100)

    assert ledger.open_specs()[0].task_id == task.task_id
    clock[0] = 1_200
    report = session.finalize()
    assert report.expired == 1 and report.completed == 0 and report.breached


def test_transcript_respects_both_consent_flags():
    session, port, _wallet, _ledger = make_byoa_session(
        attacker_consent=False, defender_consent=False
    )
    session.counterparty_turn("attack text", kind=ContentKind.DIALOGUE)
    record = session.transcript.records()[-1]
    assert record.persisted_content is None
    assert record.persisted_reply is None
    assert record.content_hash.startswith("0x")

    session2, _port2, _wallet2, _ledger2 = make_byoa_session(
        attacker_consent=True, defender_consent=True
    )
    session2.counterparty_turn("attack text")
    record2 = session2.transcript.records()[-1]
    assert record2.persisted_content == "attack text"
    assert record2.persisted_reply == "ok"


def test_byoa_api_mounts_wallet_and_protects_routes():
    from types import SimpleNamespace

    from redteam_platform.api import create_app
    from redteam_platform.byoa.service import ByoaService

    class Gateway:
        chain_id = 48850
        arena_address = ARENA
        task_sink_address = TASK_SINK

        def create_byoa_contest(self, *args):
            raise AssertionError("not used")

        def wallet_tools(self, *args):
            raise AssertionError("not used")

        def issue_task(self, *args):
            raise AssertionError("not used")

        def expire_task(self, *args):
            raise AssertionError("not used")

        def byoa_nonce(self, *args):
            return 0

    class Custody:
        def store(self, *args, **kwargs):
            return None

        def load(self, *args, **kwargs):
            raise KeyError("missing")

    byoa = ByoaService(
        Gateway(),
        Custody(),
        wallet_mcp_url="http://127.0.0.1:9999/byoa/wallet",
    )
    app = create_app(
        SimpleNamespace(indexer=SimpleNamespace(network="test")),
        "t" * 32,
        byoa=byoa,
    )
    client = TestClient(app)
    auth = {"Authorization": "Bearer " + "t" * 32}

    assert client.post("/byoa/bundles", json={}).status_code == 401
    assert client.get("/byoa/contests/" + CONTEST).status_code == 401
    assert client.get("/byoa/contests/" + CONTEST, headers=auth).status_code == 404
    assert client.post("/byoa/wallet/mcp", json={}).status_code == 401
    plaintext = client.post(
        "/byoa/contests/" + CONTEST + "/turns",
        json={"content": "plaintext attack", "attacker_consent": False},
        headers=auth,
    )
    assert plaintext.status_code == 422
    assert "ciphertext" in plaintext.text


def test_qualification_runs_probe_and_task_smoke():
    def script(message):
        if "qualification" in message.metadata:
            return ("probe", [(PROBE, 1)])
        if "task" in message.metadata and message.metadata["task"]["amount"] == "1":
            return ("task", [(TASK_SINK, 1)])
        return ("ok", [])

    session, port, wallet, ledger = make_byoa_session(script=script)
    result = session.qualification(PROBE)

    assert result["ok"] is True
    assert result["probe"] is True and result["task"] is True
    assert wallet.spent == 2
    assert ledger.report(miss_threshold=0).completed >= 1
