"""Platform-side BYOA service: bundles, sealed sessions and owner tasks.

The platform process acts as the *simulator host* in local development.  It
receives only the W address, the TEE signer address and public commitments
from the sealed runtime; the wallet key stays inside the runtime object.  On
real hardware this object is replaced by the CVM driver.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from web3 import Web3

from .adapters import McpPullAdapter, build_adapter
from .egress import EgressDeclaration
from .envelope import (
    EnvelopeError,
    ciphertext_hash,
    envelope_hash,
)
from .models import ContentKind
from .policy import PolicyError, WalletPolicy, validate_byoa_floor
from .ports import DefenderUnavailable
from .runtime import ByoaSession, MemoryTaskLedger, UtilityReport
from .sealed import (
    Attestation,
    AttestationError,
    BundleManifest,
    HARDWARE,
    SIMULATED,
    SimulatedSealedRuntime,
    compute_measurement,
    verify_attestation,
)
from .wallet import WalletRegistry, WalletSession
from ..indexer import normalize_contest_id
from ..signatures import recover_typed_signer

TRANSPORT_KINDS = frozenset({"hosted-mcp", "a2a", "webhook", "mcp-pull"})
MAX_TASKS = 64


class ByoaServiceError(RuntimeError):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class BundleRequest:
    defender: str
    image_digest: str
    transport_kind: str
    transport_endpoint: str
    transport_secret: str | None
    egress: EgressDeclaration
    policy: WalletPolicy
    max_task_amount: int
    defender_data_consent: bool
    compose_files: Mapping[str, str]
    attestation_tier: str = SIMULATED
    nonce: int = 0
    deadline: int = 0
    signature: str = ""


@dataclass(frozen=True)
class ContestRequest:
    bundle_id: str
    stake: int
    duration_h: int
    stake_bps: int
    defender_signature: str
    miss_threshold: int = 0
    penalty_bps: int = 1000
    nonce: int | None = None
    deadline: int | None = None


@dataclass(frozen=True)
class TurnRequest:
    content: str
    kind: ContentKind
    attacker_consent: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class _ContestRecord:
    bundle: "_BundleRecord"
    contest_id: str
    end: int
    wallet: WalletSession
    ledger: MemoryTaskLedger
    session: ByoaSession
    registry_token: str
    manifest: BundleManifest
    attestation: Attestation
    policy: WalletPolicy
    defender_data_consent: bool
    created_at: int
    sealed: bool = False
    task_seed: bytes | None = None
    pull_token: str | None = None


@dataclass
class _BundleRecord:
    bundle_id: str
    defender: str
    manifest: BundleManifest
    attestation: Attestation
    runtime: Any
    policy: WalletPolicy
    transport_kind: str
    transport_endpoint: str
    transport_secret: str | None
    max_task_amount: int
    defender_data_consent: bool
    created_at: int
    contest_id: str | None = None


class ByoaService:
    def __init__(
        self,
        gateway: Any,
        custody: Any,
        *,
        now: Callable[[], int] | None = None,
        runtime_factory: Callable[[], Any] = SimulatedSealedRuntime,
        wallet_mcp_url: str,
        registry: WalletRegistry | None = None,
        hardware_verifier: Callable[[Attestation], bool] | None = None,
        indexer: Any | None = None,
    ) -> None:
        if gateway is None or custody is None:
            raise ValueError("gateway and custody are required")
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        self.gateway = gateway
        self.custody = custody
        self._now = now or (lambda: int(time.time()))
        self._runtime_factory = runtime_factory
        self.wallet_mcp_url = wallet_mcp_url
        self.wallet_registry = registry or WalletRegistry()
        self.hardware_verifier = hardware_verifier
        self.indexer = indexer
        self._bundles: dict[str, _BundleRecord] = {}
        self._contests: dict[str, _ContestRecord] = {}
        self._lock = threading.RLock()

    # -- bundles --------------------------------------------------------

    def register_bundle(self, request: BundleRequest) -> dict[str, Any]:
        defender = _address(request.defender, "defender")
        if request.transport_kind not in TRANSPORT_KINDS:
            raise ByoaServiceError(422, "unsupported transport kind")
        if request.attestation_tier != SIMULATED:
            raise ByoaServiceError(
                422,
                "hardware attestation is not configured; use the simulated tier",
            )
        if request.deadline < self._now():
            raise ByoaServiceError(422, "ownership signature has expired")
        if not request.signature:
            raise ByoaServiceError(422, "ownership signature is required")
        _verify_ownership(request, defender)
        _validate_endpoint(request.transport_endpoint)
        if request.transport_kind == "webhook" and not (
            isinstance(request.transport_secret, str)
            and len(request.transport_secret) >= 16
        ):
            raise ByoaServiceError(422, "webhook requires a 16+ character secret")
        if request.max_task_amount <= 0:
            raise ByoaServiceError(422, "max_task_amount must be positive")
        try:
            validate_byoa_floor(
                request.policy,
                max_task_amount=request.max_task_amount,
                contest_end=self._now(),
            )
        except PolicyError as exc:
            raise ByoaServiceError(422, str(exc)) from None

        measurement = compute_measurement(dict(request.compose_files))
        runtime = self._runtime_factory()
        attestation = runtime.attest(measurement=measurement, issued_at=self._now())
        if attestation.tee_pubkey != runtime.tee_pubkey:
            raise ByoaServiceError(422, "attestation key does not match the runtime")
        try:
            tier = verify_attestation(
                attestation,
                expected_measurement=measurement,
                hardware_verifier=self.hardware_verifier,
            )
        except AttestationError as exc:
            raise ByoaServiceError(422, str(exc)) from None
        if tier != request.attestation_tier:
            raise ByoaServiceError(422, "attestation tier mismatch")
        manifest = BundleManifest(
            defender=defender,
            image_digest=request.image_digest,
            transport_kind=request.transport_kind,
            transport_endpoint=request.transport_endpoint,
            egress=request.egress,
            policy_fingerprint=request.policy.fingerprint(),
            attestation_tier=tier,
            runtime_measurement=measurement,
            tee_pubkey=runtime.tee_pubkey,
        )
        bundle_id = manifest.commitment()
        record = _BundleRecord(
            bundle_id=bundle_id,
            defender=defender,
            manifest=manifest,
            attestation=attestation,
            runtime=runtime,
            policy=request.policy,
            transport_kind=request.transport_kind,
            transport_endpoint=request.transport_endpoint,
            transport_secret=request.transport_secret,
            max_task_amount=request.max_task_amount,
            defender_data_consent=request.defender_data_consent,
            created_at=self._now(),
        )
        if request.transport_secret is not None:
            try:
                self.custody.store(
                    _secret_entry(bundle_id),
                    request.transport_secret,
                    context={"purpose": "byoa_transport_store", "wallet_address": defender},
                )
            except Exception:
                raise ByoaServiceError(503, "custody unavailable") from None
        with self._lock:
            if bundle_id in self._bundles:
                raise ByoaServiceError(409, "bundle already registered")
            self._bundles[bundle_id] = record
        try:
            byoa_nonce = int(self.gateway.byoa_nonce(defender))
        except Exception:
            byoa_nonce = 0
        return {
            "bundle_id": bundle_id,
            "defender": defender,
            "commitment": bundle_id,
            "attestation_tier": tier,
            "runtime_measurement": measurement,
            "tee_pubkey": runtime.tee_pubkey,
            "tee_signer": runtime.tee_signer,
            "wallet": runtime.wallet_address,
            "byoa_nonce": byoa_nonce,
            "defender_data_consent": request.defender_data_consent,
            "policy_fingerprint": request.policy.fingerprint(),
            "manifest": manifest.public_dict(),
            "egress": request.egress.as_public_dict(),
        }

    # -- contests -------------------------------------------------------

    def create_contest(self, request: ContestRequest) -> dict[str, Any]:
        with self._lock:
            bundle = self._bundles.get(request.bundle_id)
            if bundle is None:
                raise ByoaServiceError(404, "bundle is not registered")
            if bundle.contest_id is not None:
                raise ByoaServiceError(409, "bundle already created a contest")
        duration = request.duration_h * 3600
        if duration <= 0:
            raise ByoaServiceError(422, "duration must be positive")
        if request.stake <= 0:
            raise ByoaServiceError(422, "stake must be positive")
        if not 0 <= request.miss_threshold <= 64:
            raise ByoaServiceError(422, "miss_threshold must be between 0 and 64")
        if not 0 <= request.penalty_bps <= 5000:
            raise ByoaServiceError(422, "penalty_bps must be between 0 and 5000")
        end = self._now() + duration
        try:
            validate_byoa_floor(
                bundle.policy,
                max_task_amount=bundle.max_task_amount,
                contest_end=end,
            )
        except PolicyError as exc:
            raise ByoaServiceError(422, str(exc)) from None
        task_sink = getattr(self.gateway, "task_sink_address", None)
        if not task_sink:
            raise ByoaServiceError(503, "TaskSink is not deployed")

        onchain_nonce = int(self.gateway.byoa_nonce(bundle.defender))
        nonce = onchain_nonce if request.nonce is None else int(request.nonce)
        if nonce != onchain_nonce:
            raise ByoaServiceError(409, "BYOA nonce is stale; refresh and sign again")
        deadline = (
            self._now() + 900 if request.deadline is None else int(request.deadline)
        )
        if deadline < self._now() or deadline > self._now() + 3600:
            raise ByoaServiceError(422, "mandate deadline must be within the next hour")
        message = {
            "defender": bundle.defender,
            "wallet": bundle.runtime.wallet_address,
            "teeSigner": bundle.runtime.tee_signer,
            "stake": request.stake,
            "duration": duration,
            "stakeBps": request.stake_bps,
            "configCommitment": bundle.manifest.commitment(),
            "runtimeMeasurement": bundle.manifest.runtime_measurement,
            "teePubKey": bundle.manifest.tee_pubkey,
            "attestationTier": 1 if bundle.manifest.attestation_tier == HARDWARE else 0,
            "defenderDataConsent": bundle.defender_data_consent,
            "utilityMissThreshold": request.miss_threshold,
            "utilityPenaltyBps": request.penalty_bps,
            "nonce": nonce,
            "deadline": deadline,
        }
        try:
            signer = recover_typed_signer(
                request.defender_signature,
                chain_id=int(self.gateway.chain_id),
                arena=self.gateway.arena_address,
                primary_type="ByoaMandate",
                message=message,
            )
        except ValueError:
            raise ByoaServiceError(422, "defender signature is invalid") from None
        if signer.lower() != bundle.defender.lower():
            raise ByoaServiceError(403, "defender signature does not match defender")
        binding = {
            "defender": bundle.defender,
            "wallet": bundle.runtime.wallet_address,
            "configCommitment": bundle.manifest.commitment(),
            "runtimeMeasurement": bundle.manifest.runtime_measurement,
            "teePubKey": bundle.manifest.tee_pubkey,
            "nonce": nonce,
            "deadline": deadline,
        }
        tee_signature = bundle.runtime.sign_typed_data(
            domain={
                "name": "RTM Arena",
                "version": "1",
                "chainId": int(self.gateway.chain_id),
                "verifyingContract": self.gateway.arena_address,
            },
            types={
                "TeeWalletBinding": [
                    {"name": "defender", "type": "address"},
                    {"name": "wallet", "type": "address"},
                    {"name": "configCommitment", "type": "bytes32"},
                    {"name": "runtimeMeasurement", "type": "bytes32"},
                    {"name": "teePubKey", "type": "bytes32"},
                    {"name": "nonce", "type": "uint64"},
                    {"name": "deadline", "type": "uint64"},
                ]
            },
            primary_type="TeeWalletBinding",
            message=binding,
        )
        try:
            contest_id, tx_hash = self.gateway.create_byoa_contest(
                message, request.defender_signature, tee_signature
            )
        except Exception as exc:
            raise ByoaServiceError(
                502, f"createByoaContest failed: {type(exc).__name__}"
            ) from None

        try:
            tools = self.gateway.wallet_tools(
                bundle.runtime.wallet_address,
                bundle.runtime.wallet_key_for_tools(),
            )
        except Exception:
            raise ByoaServiceError(500, "wallet sidecar initialization failed") from None
        ledger = MemoryTaskLedger(contest_id=contest_id, task_sink=task_sink)
        wallet = WalletSession(
            wallet_address=bundle.runtime.wallet_address,
            executor=tools,
            policy=bundle.policy,
            contest_id=contest_id,
            now=self._now,
            confirmer=lambda to, amount: (
                Web3.to_checksum_address(to) == Web3.to_checksum_address(task_sink)
                and ledger.matches_open(amount, self._now())
            ),
        )
        token = self.wallet_registry.issue(wallet)
        try:
            port = build_adapter(
                bundle.transport_kind,
                endpoint=bundle.transport_endpoint,
                secret=self._load_secret(bundle),
                wallet_mcp_url=self.wallet_mcp_url,
                wallet_token=token.token,
                timeout=30.0,
            )
        except ValueError as exc:
            raise ByoaServiceError(422, str(exc)) from None

        session = ByoaSession(
            contest_id=contest_id,
            port=port,
            wallet=wallet,
            ledger=ledger,
            task_sink=task_sink,
            attacker_consent=False,
            defender_consent=bundle.defender_data_consent,
            miss_threshold=request.miss_threshold,
            now=self._now,
            chain_issue=lambda amount, task_deadline, task_hash: self.gateway.issue_task(
                contest_id, amount, task_deadline, task_hash
            ),
        )
        pull_token = (
            secrets.token_urlsafe(32)
            if bundle.transport_kind == "mcp-pull"
            else None
        )
        record = _ContestRecord(
            bundle=bundle,
            contest_id=contest_id,
            end=end,
            wallet=wallet,
            ledger=ledger,
            session=session,
            registry_token=token.token,
            manifest=bundle.manifest,
            attestation=bundle.attestation,
            policy=bundle.policy,
            defender_data_consent=bundle.defender_data_consent,
            created_at=self._now(),
            pull_token=pull_token,
        )
        with self._lock:
            bundle.contest_id = contest_id
            self._contests[contest_id] = record
        return {
            "contest_id": contest_id,
            "tx_hash": tx_hash,
            "wallet": bundle.runtime.wallet_address,
            "defender": bundle.defender,
            "tee_signer": bundle.runtime.tee_signer,
            "config_commitment": bundle.manifest.commitment(),
            "runtime_measurement": bundle.manifest.runtime_measurement,
            "attestation_tier": bundle.manifest.attestation_tier,
            "end": end,
            "task_sink": task_sink,
            "pull_token": pull_token,
        }

    # -- runtime --------------------------------------------------------

    def issue_task(
        self,
        contest_id: str,
        *,
        text: str,
        amount: int,
        deadline: int,
    ) -> dict[str, Any]:
        record = self._contest(contest_id)
        if amount > record.bundle.max_task_amount:
            raise ByoaServiceError(422, "task amount exceeds the signed maximum")
        if deadline <= self._now() or deadline > record.end:
            raise ByoaServiceError(422, "task deadline is outside the contest window")
        if len(record.ledger.open_specs()) >= MAX_TASKS:
            raise ByoaServiceError(409, "too many open tasks")
        try:
            spec = record.session.issue_task(text, amount=amount, deadline=deadline)
        except DefenderUnavailable:
            raise ByoaServiceError(502, "defender transport is unavailable") from None
        return {
            "contest_id": contest_id,
            "task_id": spec.task_id,
            "task_hash": spec.task_hash,
            "amount": str(spec.amount),
            "deadline": spec.deadline,
        }

    def generate_tasks(
        self,
        contest_id: str,
        *,
        count: int,
        seed_hex: str | None = None,
    ) -> list[dict[str, Any]]:
        """Generate and issue a deterministic batch of owner tasks."""

        import secrets

        from .tasks import TaskGenerator

        record = self._contest(contest_id)
        if seed_hex is not None:
            try:
                seed = bytes.fromhex(seed_hex.removeprefix("0x"))
            except ValueError:
                raise ByoaServiceError(422, "seed must be hex") from None
            if len(seed) < 16:
                raise ByoaServiceError(422, "seed must be at least 16 bytes")
        elif record.task_seed is not None:
            seed = record.task_seed
        else:
            seed = secrets.token_bytes(32)
        record.task_seed = seed
        try:
            generator = TaskGenerator(
                seed=seed,
                contest_end=record.end,
                now=self._now(),
                min_amount=max(1, record.bundle.max_task_amount // 10),
                max_amount=record.bundle.max_task_amount,
            )
            generated = generator.generate(count)
        except ValueError as exc:
            raise ByoaServiceError(422, str(exc)) from None
        return [
            self.issue_task(
                contest_id,
                text=item.text,
                amount=item.amount,
                deadline=item.deadline,
            )
            for item in generated
        ]

    def turn(self, contest_id: str, request: TurnRequest) -> dict[str, Any]:
        record = self._contest(contest_id)
        if self._now() >= record.end:
            raise ByoaServiceError(409, "contest has ended")
        if not isinstance(request.attacker_consent, bool):
            raise ByoaServiceError(422, "attacker_consent is required")
        try:
            result = record.session.counterparty_turn(
                request.content,
                kind=request.kind,
                metadata=request.metadata,
                attacker_consent=request.attacker_consent,
            )
        except DefenderUnavailable:
            raise ByoaServiceError(502, "defender transport is unavailable") from None
        except ValueError as exc:
            raise ByoaServiceError(422, str(exc)) from None
        return {
            "contest_id": contest_id,
            "seq": result.seq,
            "reply": result.reply.text,
            "reply_hash": result.record.reply_hash,
            "content_hash": result.record.content_hash,
            "attacker_consent": request.attacker_consent,
            "defender_consent": record.defender_data_consent,
            "completed_tasks": [task.task_id for task in result.completed_tasks],
            "transfers": [
                {
                    "to": transfer.to,
                    "amount": str(transfer.amount),
                    "tx": transfer.tx,
                }
                for transfer in result.transfers
            ],
            "sealed": False,
        }

    def sealed_turn(
        self,
        contest_id: str,
        *,
        tx_hash: str,
        attacker: str,
        ciphertext: Mapping[str, Any],
        attacker_pubkey: str,
        key_signature: str,
        key_deadline: int,
        kind: ContentKind = ContentKind.DIALOGUE,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Verify the paid ciphertext, decrypt in the TEE, run and seal the reply."""

        record = self._contest(contest_id)
        if self.indexer is None:
            raise ByoaServiceError(503, "indexer is not configured")
        if self._now() >= record.end:
            raise ByoaServiceError(409, "contest has ended")
        event = self._attack_event(contest_id, tx_hash)
        stored = event["args"]
        msg_hash = str(stored.get("msgHash", "")).lower()
        if stored.get("attacker", "").lower() != _address(attacker, "attacker").lower():
            raise ByoaServiceError(403, "transaction belongs to another attacker")
        if not isinstance(ciphertext, Mapping):
            raise ByoaServiceError(422, "ciphertext must be an envelope object")
        try:
            paid_hash = ciphertext_hash(ciphertext.get("ct"))
        except EnvelopeError:
            raise ByoaServiceError(422, "ciphertext envelope is malformed") from None
        if not hmac.compare_digest(paid_hash, msg_hash):
            raise ByoaServiceError(422, "ciphertext does not match the paid msgHash")

        membership = self.indexer.contest_attackers(contest_id).get(
            _address(attacker, "attacker")
        )
        if membership is None or membership.get("is_mining"):
            raise ByoaServiceError(403, "sender is not a joined attacker")
        consent = membership.get("data_consent")
        if not isinstance(consent, bool):
            raise ByoaServiceError(409, "join consent is not indexed yet")

        if key_deadline < self._now():
            raise ByoaServiceError(422, "attacker key signature has expired")
        pubkey = _bytes32_hex(attacker_pubkey, "attacker_pubkey")
        try:
            signer = recover_typed_signer(
                key_signature,
                chain_id=int(self.gateway.chain_id),
                arena=self.gateway.arena_address,
                primary_type="AttackKey",
                message={
                    "attacker": attacker,
                    "contestId": contest_id,
                    "msgHash": msg_hash,
                    "pubkey": pubkey,
                    "deadline": key_deadline,
                },
            )
        except ValueError:
            raise ByoaServiceError(422, "attacker key signature is invalid") from None
        if signer.lower() != _address(attacker, "attacker").lower():
            raise ByoaServiceError(403, "attacker key signature does not match attacker")

        runtime = record.bundle.runtime
        try:
            plaintext = runtime.open_attack(
                ciphertext,
                contest_id=contest_id,
                attacker=attacker,
            )
        except (EnvelopeError, AttestationError):
            raise ByoaServiceError(422, "attack ciphertext cannot be decrypted") from None
        try:
            result = record.session.counterparty_turn(
                plaintext,
                kind=kind,
                metadata=dict(metadata or {}),
                attacker_consent=consent,
            )
        except DefenderUnavailable:
            raise ByoaServiceError(502, "defender transport is unavailable") from None

        try:
            reply_envelope = runtime.seal_reply(
                pubkey,
                result.reply.text,
                contest_id=contest_id,
                attacker=attacker,
                msg_hash=msg_hash,
                seq=result.seq,
            )
        except EnvelopeError:
            raise ByoaServiceError(500, "reply encryption failed") from None
        reply_hash = envelope_hash(reply_envelope)
        reply_signature = runtime.sign_reply(
            contest_id=contest_id,
            attacker=attacker,
            msg_hash=msg_hash,
            reply_hash=reply_hash,
            seq=result.seq,
        )
        try:
            self.gateway.mark_delivered_reply(
                contest_id, attacker, msg_hash, reply_hash
            )
        except Exception as exc:
            raise ByoaServiceError(
                502, f"markDelivered failed: {type(exc).__name__}"
            ) from None
        record.sealed = True
        return {
            "contest_id": contest_id,
            "seq": result.seq,
            "sealed": True,
            "reply_envelope": reply_envelope,
            "reply_hash": reply_hash,
            "reply_signature": reply_signature,
            "tee_signer": record.bundle.runtime.tee_signer,
            "completed_tasks": [task.task_id for task in result.completed_tasks],
            "transfers": [
                {"to": transfer.to, "amount": str(transfer.amount), "tx": transfer.tx}
                for transfer in result.transfers
            ],
        }

    def finalize(self, contest_id: str) -> dict[str, Any]:
        record = self._contest(contest_id)
        report = record.session.finalize()
        expired: list[str] = []
        errors: list[str] = []
        for spec in record.ledger.expired_specs():
            try:
                self.gateway.expire_task(contest_id, spec.task_id)
                expired.append(spec.task_id)
            except Exception as exc:
                errors.append(f"{spec.task_id}: {type(exc).__name__}")
        penalty_tx = None
        try:
            onchain_expired = int(self.gateway.expired_task_count(contest_id))
        except Exception:
            onchain_expired = None
        if (
            onchain_expired is not None
            and onchain_expired > report.miss_threshold
        ):
            try:
                penalty_tx = self.gateway.report_byoa_utility_breach(contest_id)
            except Exception as exc:
                errors.append(
                    f"utility breach: {type(exc).__name__}"
                )
        return {
            **_report_dict(report),
            "expired_onchain": expired,
            "onchain_expired_count": onchain_expired,
            "penalty_tx": penalty_tx,
            "errors": errors,
        }

    def state(self, contest_id: str) -> dict[str, Any]:
        record = self._contest(contest_id)
        report = record.ledger.report(miss_threshold=record.session.miss_threshold)
        transcript = record.session.transcript.public_view()
        if record.sealed:
            # The relay view never contains E2E plaintext, even when the
            # defender consented to later decryption.
            for entry in transcript:
                entry["content"] = None
                entry["reply"] = None
                entry["toolCalls"] = []
        return {
            "contest_id": contest_id,
            "defender": record.bundle.defender,
            "wallet": record.wallet.wallet_address,
            "tee_signer": record.bundle.runtime.tee_signer,
            "tee_pubkey": record.manifest.tee_pubkey,
            "config_commitment": record.manifest.commitment(),
            "runtime_measurement": record.manifest.runtime_measurement,
            "attestation_tier": record.manifest.attestation_tier,
            "policy_fingerprint": record.policy.fingerprint(),
            "defender_data_consent": record.defender_data_consent,
            "manifest": record.manifest.public_dict(),
            "egress": record.bundle.manifest.egress.as_public_dict(),
            "transcript": transcript,
            "utility": _report_dict(report),
            "wallet_audit": record.wallet.audit(),
            "encryption": "e2e" if record.sealed else "none-simulator",
            "end": record.end,
        }

    def wallet_session(self, token: str) -> WalletSession | None:
        return self.wallet_registry.resolve(token)

    def pull_next(self, contest_id: str, token: str) -> dict[str, Any]:
        record = self._contest(contest_id)
        self._check_pull(record, token)
        port = record.session.port
        if not isinstance(port, McpPullAdapter):
            raise ByoaServiceError(409, "contest is not using mcp-pull")
        return port.inbox.next_message() or {"message": None}

    def pull_reply(
        self,
        contest_id: str,
        token: str,
        *,
        seq: int,
        text: str,
        tool_calls: list[Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = self._contest(contest_id)
        self._check_pull(record, token)
        port = record.session.port
        if not isinstance(port, McpPullAdapter):
            raise ByoaServiceError(409, "contest is not using mcp-pull")
        try:
            accepted = port.inbox.submit_reply(
                seq=seq,
                text=text,
                tool_calls=tuple(tool_calls or ()),
                metadata=metadata,
            )
        except ValueError as exc:
            raise ByoaServiceError(422, str(exc)) from None
        if not accepted:
            raise ByoaServiceError(409, "no pending message with that sequence")
        return {"accepted": True}

    def _check_pull(self, record: _ContestRecord, token: str) -> None:
        if record.pull_token is None:
            raise ByoaServiceError(409, "contest is not using mcp-pull")
        if not isinstance(token, str) or not hmac.compare_digest(
            token, record.pull_token
        ):
            raise ByoaServiceError(401, "invalid pull token")

    # -- helpers --------------------------------------------------------

    def _contest(self, contest_id: str) -> _ContestRecord:
        with self._lock:
            record = self._contests.get(contest_id)
        if record is None:
            raise ByoaServiceError(404, "BYOA contest is not running")
        return record

    def _attack_event(self, contest_id: str, tx_hash: str) -> Mapping[str, Any]:
        try:
            event = self.indexer.event_by_tx(tx_hash, "AttackPaid")
        except Exception:
            raise ByoaServiceError(502, "indexer unavailable") from None
        if event is None:
            raise ByoaServiceError(409, "attack payment is not indexed yet")
        if event.get("excluded"):
            raise ByoaServiceError(403, "contest is excluded")
        args = event.get("args") or {}
        try:
            event_contest = normalize_contest_id(args.get("id"))
        except Exception:
            raise ByoaServiceError(409, "invalid AttackPaid event") from None
        if event_contest.lower() != contest_id.lower():
            raise ByoaServiceError(409, "transaction does not belong to this contest")
        return event

    def _load_secret(self, bundle: _BundleRecord) -> str | None:
        if bundle.transport_secret is not None:
            return bundle.transport_secret
        if bundle.transport_kind != "webhook":
            return None
        try:
            return self.custody.load(
                _secret_entry(bundle.bundle_id),
                context={
                    "purpose": "byoa_transport_load",
                    "wallet_address": bundle.defender,
                },
            )
        except Exception:
            raise ByoaServiceError(503, "transport secret is unavailable") from None


def _secret_entry(bundle_id: str) -> str:
    return f"byoa-transport:{bundle_id.lower()}"


def _validate_endpoint(value: Any) -> None:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ByoaServiceError(422, "transport endpoint must be a bounded URL")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ByoaServiceError(422, "transport endpoint must be an http(s) URL")
    if parsed.username or parsed.password:
        raise ByoaServiceError(422, "transport endpoint must not contain credentials")


def _bytes32_hex(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 66
        or not value.startswith("0x")
    ):
        raise ByoaServiceError(422, f"{field} must be a bytes32 hex string")
    try:
        bytes.fromhex(value[2:])
    except ValueError:
        raise ByoaServiceError(422, f"{field} must be a bytes32 hex string") from None
    return value.lower()


def _address(value: Any, field: str) -> str:
    try:
        return Web3.to_checksum_address(value)
    except (ValueError, TypeError):
        raise ByoaServiceError(422, f"{field} must be a valid address") from None


def _verify_ownership(request: BundleRequest, defender: str) -> None:
    from ..signatures import canonical_challenge, recover_personal_signer

    text = canonical_challenge(
        defender, "byoa-bundle", request.nonce, request.deadline
    )
    try:
        signer = recover_personal_signer(request.signature, text)
    except ValueError:
        raise ByoaServiceError(422, "ownership signature is invalid") from None
    if signer.lower() != defender.lower():
        raise ByoaServiceError(403, "ownership signature does not match defender")


def _report_dict(report: UtilityReport) -> dict[str, Any]:
    return {
        "issued": report.issued,
        "completed": report.completed,
        "expired": report.expired,
        "open": report.open,
        "miss_threshold": report.miss_threshold,
        "breached": report.breached,
        "completion_ratio": report.completion_ratio,
    }
