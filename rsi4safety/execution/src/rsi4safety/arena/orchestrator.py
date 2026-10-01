from __future__ import annotations

import json
from pathlib import Path
import shutil
import time
from typing import Callable
from uuid import uuid4

from .config import ArenaConfig
from .docker_host import DockerHost
from .exchange import (
    mark_consumed,
    read_new_submissions,
    validate_attack_submission,
    validate_patch_submission,
    validate_verdict,
    write_json_atomic,
)
from .audit import HashChain
from .sut_driver import BaseSutDriver, DockerSutDriver, InProcessSutDriver, _Http
from .runtime import StubAgentRuntime
from .control import PROTOCOL_VERSION, campaign_lock, runtime_fingerprint, tree_hash
from .versions import VersionStore
from .experience import ExperienceStore, diversity_guidance
from .feedback_policy import attacker_feedback as _attacker_feedback_view
from .fixtures import Fixture, _fixture, _fixture_from_brief, _canonical_attacks, _materialize
from .execution_cache import ExecutionCacheMixin
from .adjudication import AdjudicationMixin
from .promotion import PromotionMixin

WAKEUP_ROLES = ("attacker", "judge", "defender")


class ArenaOrchestrator(ExecutionCacheMixin, AdjudicationMixin, PromotionMixin):
    """The campaign loop: attack -> trusted evidence -> adjudication -> patch -> gates.

    Scoring never reads SUT-owned state: every payment proposal is executed by
    the platform's trusted executor and replayed against the authorization
    constitution (see trusted_execution.py and sut_driver.py).
    """

    def run(self) -> dict:
        with campaign_lock(self.config.state_dir / "campaign.lock"):
            self._fingerprint = runtime_fingerprint(self.config)
            # Validate compatibility before changing any existing experiment artifacts.
            start_round = self._maybe_resume()
            if self.report.get("status") == "completed":
                self.report["chain_head"] = self.chain.head()
                self._write_report_files()
                return self.report
            self.report["runtime_fingerprint"] = self._fingerprint
            self.report["protocol"] = PROTOCOL_VERSION
            self.report["status"] = "running"
            self.chain.append("orchestrator", "campaign_start", **self.config.public_dict())
            try:
                self._seed_sut_source()
                self._ensure_docker()
                self.report["initial_version"] = self._initial_version
                self.report["initial_tree_sha256"] = tree_hash(self.config.state_dir / "sut-initial")
                self._write_report_files()
                for index in range(start_round, self.config.rounds + 1):
                    self._round_index = index
                    self._checkpoint_before_round(index)
                    result = self._run_round(index)
                    self.report["rounds"].append(result)
                    self.report["active_version_label"] = self._current_version_label()
                    self.report["attacker_feedback"] = getattr(self, "_last_attacker_feedback", [])
                    self.report["executions"] = self._execution_count
                    self._write_report_files()
                    (self.config.state_dir / "round-checkpoint.json").unlink(missing_ok=True)
                self.report["final_evaluation"] = self._final_evaluation()
                self.report["final_tree_sha256"] = tree_hash(self.config.sut_dir)
                self.report["active_version_label"] = self._current_version_label()
                self.report["status"] = "completed"
            except Exception as exc:
                self.report["status"] = "stopped"
                self.report["stop_reason"] = f"{type(exc).__name__}: {str(exc)[:1000]}"
                self.chain.append("orchestrator", "error", message=self.report["stop_reason"])
            finally:
                self.report["executions"] = self._execution_count
                self.report["finished_at"] = time.time()
                self._ingest_mcp_audit()
                self.chain.append("orchestrator", "campaign_end", status=self.report["status"])
                self.report["chain_head"] = self.chain.head()
                self._write_report_files()
            return self.report

    def _checkpoint_before_round(self, index: int) -> None:
        path = self.config.state_dir / "round-checkpoint.json"
        if path.exists():
            saved = json.loads(path.read_text())
            self.versions.rollback(saved["version"], reason="recover interrupted round")
            self.versions.materialize_source(saved["version"], self.config.sut_dir)
            self._sut_version = saved["version"]
            # Pending submissions have uncertain execution state; preserve them outside the live spool.
            for role in WAKEUP_ROLES:
                for name in ("inbox", "outbox"):
                    directory = self.config.role_dirs(role)[name]
                    backup = self.config.state_dir / "interrupted" / uuid4().hex / role / name
                    if directory.exists():
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(directory), backup)
                        directory.mkdir(parents=True)
                marker = self.config.exchange_dir / role / ".consumed.json"
                marker.unlink(missing_ok=True)
            self.chain.append("orchestrator", "interrupted_round_recovered", round=index)
        write_json_atomic(path, {"round": index, "version": self.versions.active().version_id})

    def __init__(self, config: ArenaConfig, *, runtime=None, docker_host: DockerHost | None = None,
                 progress: Callable[[str, dict], None] | None = None) -> None:
        self.config = config
        self.versions = VersionStore(config.state_dir / "version-store")
        self.experiences = ExperienceStore(config.state_dir / "experience.jsonl")
        self._execution_count = 0
        self._round_index = 0
        self.chain = HashChain(config.audit_dir / "chain.jsonl")
        self.runtime = runtime
        self.docker_host = docker_host
        self.progress = progress or (lambda phase, data: None)
        self.report: dict = {
            "campaign_id": config.campaign_id, "config": config.public_dict(),
            "status": "created", "started_at": time.time(), "rounds": [],
            "usage": {}, "limitations": [
                "Heavy-agent sessions are bounded by turns and time, not by verified token bills.",
                "The same underlying GLM account serves all three roles; container isolation "
                "cannot remove same-model blind spots.",
                "Frozen final suites share attack mechanisms with development suites; they are "
                "engineering verification, not an independent research benchmark.",
            ],
        }
        config.state_dir.mkdir(parents=True, exist_ok=True)
        for directory in (config.evidence_dir, config.patches_dir, config.audit_dir,
                          config.snapshots_dir, config.sessions_dir):
            directory.mkdir(parents=True, exist_ok=True)
        for role in ("attacker", "defender", "judge"):
            for sub in ("inbox", "outbox", "audit"):
                (config.exchange_dir / role / sub).mkdir(parents=True, exist_ok=True)

    # -- lifecycle ---------------------------------------------------------
    def _seed_sut_source(self) -> None:
        source = self.config.repo_root / "payment_agents" / getattr(self.config, "sut_app", "paygate")
        if not (source / "app" / "main.py").exists():
            raise FileNotFoundError(f"PayGate source missing at {source}")
        initial = self.versions.initialize(source)
        self._initial_version = initial.version_id
        active = self.versions.active()
        self.versions.materialize_source(active.version_id, self.config.sut_dir)
        self.versions.materialize_source(initial.version_id, self.config.state_dir / "sut-initial")
        self._sut_version = active.version_id
        self.chain.append("orchestrator", "sut_source_seeded", version=active.version_id,
                          package_digest=active.package_digest, commit=active.commit)

    def _driver_factory(self, *, gateway: str = "research",
                        sut_dir: Path | None = None) -> Callable[[], BaseSutDriver]:
        cfg = _sut_dir_config(self.config, sut_dir) if sut_dir is not None else self.config
        if self.config.dry_run or self.docker_host is None:
            return lambda: InProcessSutDriver(cfg, gateway=gateway)
        return lambda: DockerSutDriver(cfg, self.docker_host, gateway=gateway)

    def preflight(self) -> dict:
        self.progress("preflight", {})
        checks: dict = {"dry_run": self.config.dry_run}
        if not self.config.dry_run:
            if self.docker_host is None:
                raise RuntimeError("real campaigns require a DockerHost")
            checks["docker"] = self.docker_host.ping()
            from .config import glm_api_key
            if not glm_api_key():
                raise RuntimeError("GLM_API_KEY is required for real campaigns")
            if self.runtime is not None and not isinstance(self.runtime, StubAgentRuntime):
                checks["runtime"] = "claude-code"
        self.chain.append("orchestrator", "preflight", **checks)
        return checks

    # -- campaign ------------------------------------------------------------
    def _ensure_docker(self) -> None:
        """Real campaigns: build images, boot the gateway and the three agents."""
        if self.config.dry_run or self.docker_host is None:
            return
        from .config import glm_api_key
        from .runtime import ClaudeCodeRuntime
        api_key = glm_api_key()
        if not api_key:
            raise RuntimeError("GLM_API_KEY is required for real campaigns")
        self.docker_host.down()  # idempotent restart; workspace volumes persist
        self.docker_host.ensure_networks()
        self.docker_host.build_image(f"arena-{self.config.campaign_id}-agent:latest",
                                     self.config.repo_root / "execution" / "docker" / "agent")
        self.docker_host.build_image(f"arena-{self.config.campaign_id}-gateway:latest",
                                     self.config.repo_root / "execution" / "docker" / "llm-gateway")
        self._build_sut_image()
        # One shared gateway token per campaign; the raw key stays in the gateway.
        gateway_token = uuid4().hex
        self.docker_host.set_gateway_token(gateway_token)  # SUT llm mode needs it too
        self.docker_host.up_gateway(api_key, gateway_token)
        self.docker_host.up_agents(api_key, gateway_token)
        if self.runtime is None:
            self.runtime = ClaudeCodeRuntime(self.docker_host)
        self.chain.append("orchestrator", "docker_ready",
                          networks=["egress", "battle", "sutops"],
                          containers=["attacker", "defender", "judge", "llm-gateway"])

    def _build_sut_image(self) -> None:
        if self.config.dry_run or self.docker_host is None:
            return
        # Tags are per tree digest, so the parent and every candidate get
        # their own image; identical trees reuse the cached build.
        self.docker_host.sut_image(self.config.sut_dir)

    # -- resume -------------------------------------------------------------------
    def _maybe_resume(self) -> int:
        prior_path = self.config.state_dir / "report.json"
        if not prior_path.exists():
            return 1
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        if (prior.get("config") != self.config.public_dict()
                or prior.get("runtime_fingerprint") != self._fingerprint):
            raise ValueError("campaign runtime or configuration changed; use a new state directory")
        self.report = prior
        self._execution_count = int(prior.get("executions", 0))
        self._last_attacker_feedback = prior.get("attacker_feedback", [])
        rounds_done = len(prior.get("rounds", []))
        if prior.get("status") == "completed":
            self.chain.append("orchestrator", "resume_noop", rounds=rounds_done)
            return self.config.rounds + 1
        self.report["status"] = "running"
        self.report.pop("stop_reason", None)
        self.chain.append("orchestrator", "resume", from_round=rounds_done + 1)
        return rounds_done + 1

    # -- one round --------------------------------------------------------------
    def _run_round(self, round_index: int) -> dict:
        self.progress("round_start", {"round": round_index})
        self.chain.append("orchestrator", "round_start", round=round_index)
        round_report: dict = {"round": round_index}
        fixtures = [_fixture(f"arena-r{round_index}", self.config.seed, round_index * 10 + i)
                    for i in range(2)]
        # 1. recon instance: attacker probes a live SUT with real task ids.
        recon = self._open_recon_instance(fixtures)
        try:
            self._write_brief("attacker", round_index, fixtures)
            attacker_outcome = self._session("attacker", round_index)
            round_report["attacker_session"] = self._outcome_summary(attacker_outcome)
        finally:
            recon_stop = self._close_recon_instance(recon)
        # 2. execute every valid submission against fresh instances.
        submissions = self._collect_submissions("attacker", validate_attack_submission)
        findings: list[dict] = []
        for submission in submissions:
            evidence = self._execute_submission(round_index, submission, fixtures)
            round_report.setdefault("evidence", []).append(evidence["summary"])
            findings.append(evidence)
        self._deliver_patch_context(round_index)  # ensures stale reads cannot leak rounds
        # 3. adjudication: programmatic by default; an LLM judge is explicit opt-in.
        if self.config.judge_mode == "claude":
            self._write_verdict_request(round_index, findings)
            judge_outcome = self._session("judge", round_index)
            round_report["judge_session"] = self._outcome_summary(judge_outcome)
            verdicts = self._collect_submissions("judge", validate_verdict)
        else:
            verdicts = self._programmatic_verdicts(findings)
            round_report["judge_session"] = {"mode": "programmatic", "ok": True}
        valid = self._apply_verdicts(round_index, findings, verdicts)
        # 有限反馈协议（研究计划 §03）：攻击侧只拿 bounty 式结果摘要，
        # 永不包含账本/轨迹/防御方信息（feedback_policy 显式化并可测试）。
        self._last_attacker_feedback = _attacker_feedback_view(findings)
        round_report["verdicts"] = [
            {"evidence_id": item.evidence_id, "valid_finding": item.valid_finding,
             "severity": item.severity} for item in verdicts]
        round_report["valid_findings"] = [item["evidence_id"] for item in valid]
        # 4. defender patches only when a valid finding exists.
        promoted = False
        patch_submission = None
        if valid:
            self._write_findings(round_index, valid, findings)
            defender_outcome = self._session("defender", round_index)
            round_report["defender_session"] = self._outcome_summary(defender_outcome)
            patch_submission = self._collect_submissions("defender", validate_patch_submission)
            if patch_submission:
                promoted, gate = self._evaluate_patch(round_index, patch_submission[0], valid, findings)
                round_report["promotion"] = gate
                if not promoted:
                    self._resync_defender_source(round_index)
            else:
                round_report["promotion"] = {"promoted": False, "reasons": ["defender_produced_no_patch"]}
        else:
            round_report["promotion"] = {"promoted": False, "reasons": ["no_valid_findings"]}
        # 5. snapshots, audit ingestion, usage.
        self._snapshot_roles(round_index)
        self._ingest_mcp_audit()
        round_report["promoted"] = promoted
        round_report["recon_log_tail"] = recon_stop[-2000:]
        self.chain.append("orchestrator", "round_complete", round=round_index, promoted=promoted)
        self.progress("round_complete", {"round": round_index, "promoted": promoted})
        return round_report

    # -- sessions and submissions -----------------------------------------------
    def _session(self, role: str, round_index: int):
        if self.runtime is None:
            raise RuntimeError("no agent runtime configured")
        self.chain.append("orchestrator", "session_start", role=role, round=round_index)
        outcome = self.runtime.run_session(self.config, role, round_index)
        self.chain.append("orchestrator", "session_end", role=role, round=round_index,
                          ok=outcome.ok, session_id=outcome.session_id,
                          num_turns=outcome.num_turns, usage=outcome.usage,
                          error_subtype=outcome.error_subtype,
                          refusal_suspected=outcome.refusal_suspected,
                          refusal_evidence=outcome.refusal_evidence[:300])
        self._add_usage(role, outcome.usage)
        return outcome

    @staticmethod
    def _outcome_summary(outcome) -> dict:
        return {"ok": outcome.ok, "num_turns": outcome.num_turns,
                "error_subtype": outcome.error_subtype, "detail": outcome.detail[-500:],
                "refusal_suspected": outcome.refusal_suspected,
                "refusal_evidence": outcome.refusal_evidence[:300]}

    def _collect_submissions(self, role: str, validator) -> list:
        dirs = self.config.role_dirs(role)
        consumed = dirs["inbox"].parent / ".consumed.json"
        collected = []
        for path, data in read_new_submissions(dirs["outbox"], consumed):
            parsed, errors = validator(data)
            self.chain.append("orchestrator", f"{role}_submission_read",
                              file=path.name, valid=parsed is not None, errors=errors[:5])
            if parsed is not None:
                collected.append(parsed)
            mark_consumed(consumed, path.name)
        return collected

    def _write_brief(self, role: str, round_index: int, fixtures: list[Fixture],
                     extra: dict | None = None) -> None:
        payload = {
            "schema_version": 1, "type": "round_brief",
            "round": round_index, "campaign_id": self.config.campaign_id, "role": role,
            "task_fixtures": [item.brief_form() for item in fixtures],
            "sut_base_url": "http://paygate:8000",
            "base_sut_version": self._current_version_label(),
            "budget": {"max_turns": self.config.max_turns_for(role),
                       "deadline_unix": int(time.time() + self.config.session_deadline_seconds)},
        }
        if role == "attacker" and self.config.attacker_hints:
            payload["intel_hints"] = list(self.config.attacker_hints)
        if role == "attacker":
            # Rainbow-Teaming 式多样性管理：报告已探索的机制簇并要求新簇。
            try:
                payload["attack_diversity"] = diversity_guidance(self.experiences)
            except (ValueError, OSError):
                pass
            priors = self._attacker_prior_findings()
            if priors:
                payload["own_prior_findings"] = priors
            feedback = getattr(self, "_last_attacker_feedback", None)
            if feedback:
                # Bounty-style outcome feedback: the attacker could not observe
                # its own attacks; without this it cannot adapt at all.
                payload["previous_round_feedback"] = feedback
        payload.update(extra or {})
        write_json_atomic(self.config.role_dirs(role)["inbox"] / f"round-{round_index}-brief.json", payload)
        self.chain.append("orchestrator", "brief_written", role=role, round=round_index,
                          file=f"round-{round_index}-brief.json")

    def _current_version_label(self) -> str:
        return getattr(self, "_sut_version", "seeded-v0")

    def _attacker_prior_findings(self) -> list[dict]:
        """Bounded recap of the attacker's own verified findings (no per-actor filter exists)."""
        try:
            occurrences: dict[str, int] = {}
            for record in self.experiences.all():
                if record.get("kind") == "finding" and record.get("verified"):
                    signature = record.get("attack_digest")
                    if isinstance(signature, str) and signature:
                        occurrences[signature] = occurrences.get(signature, 0) + 1
            priors = []
            for record in self.experiences.search(limit=8):
                if record.get("kind") != "finding":
                    continue
                signature = str(record.get("attack_digest") or record.get("experience_id", ""))
                priors.append({"title": str(record.get("mechanism") or "prior finding")[:200],
                               "signature": signature,
                               "occurrences": occurrences.get(signature, 1)})
                if len(priors) >= 3:
                    break
            return priors
        except (ValueError, OSError):
            return []

    def _resync_defender_source(self, round_index: int) -> None:
        """A rejected candidate must not become the next defender round's base."""
        if self.config.dry_run or self.docker_host is None:
            return
        self.docker_host.sync_defender_source(self.config.sut_dir)
        self.chain.append("orchestrator", "defender_source_resynced", round=round_index,
                          version=self._current_version_label())

    # -- recon instance -------------------------------------------------------
    def _open_recon_instance(self, fixtures: list[Fixture]):
        driver = self._driver_factory()()
        try:
            driver.start()
            http = _Http(driver.base_url)
            http.wait_healthy()
            live = []
            for fixture in fixtures:
                status, created = http.call("POST", "/tasks", {
                    "user_request": fixture.user_request, "authorization": fixture.authorization})
                if status != 200 or not isinstance(created, dict) or not created.get("task_id"):
                    raise ValueError("recon task creation failed")
                live.append(Fixture(created["task_id"], fixture.user_request, fixture.authorization))
            fixtures[:] = live
            return driver
        except Exception:
            driver.stop()
            raise

    def _close_recon_instance(self, driver) -> str:
        try:
            return driver.stop()
        except Exception as exc:  # noqa: BLE001
            return f"recon stop failed: {exc}"

    # -- bookkeeping ------------------------------------------------------------
    def _add_usage(self, role: str, usage: dict) -> None:
        bucket = self.report["usage"].setdefault(role, {"sessions": 0, "turns": 0,
                                                        "input_tokens": 0, "output_tokens": 0})
        bucket["sessions"] += 1
        bucket["turns"] += int(usage.get("num_turns") or 0)
        bucket["input_tokens"] += int(usage.get("input_tokens") or 0)
        bucket["output_tokens"] += int(usage.get("output_tokens") or 0)

    def _snapshot_roles(self, round_index: int) -> None:
        target = self.config.snapshots_dir / f"round-{round_index}"
        target.mkdir(parents=True, exist_ok=True)
        for role in WAKEUP_ROLES:
            try:
                if self.docker_host is not None and not self.config.dry_run:
                    self.docker_host.snapshot_agent_volume(role, target)
                else:
                    from .audit import snapshot_directory
                    digest = snapshot_directory(self.config.exchange_dir / role,
                                                target / f"{role}-exchange.tar.gz")
                    self.chain.append("orchestrator", "snapshot", role=role,
                                      round=round_index, sha256=digest)
            except Exception as exc:  # noqa: BLE001 - snapshots must not kill rounds
                self.chain.append("orchestrator", "snapshot_failed", role=role,
                                  round=round_index, error=str(exc)[:200])

    def _ingest_mcp_audit(self) -> None:
        for role in WAKEUP_ROLES:
            path = self.config.role_dirs(role)["audit"] / "mcp.jsonl"
            if path.exists():
                count = self.chain.ingest_file(path, actor=f"mcp:{role}")
                if count:
                    path.write_text("", encoding="utf-8")

    def _write_report_files(self) -> None:
        from . import reports
        reports.write_report(self.config, self.report)


def _sut_dir_config(config: ArenaConfig, sut_dir: Path) -> ArenaConfig:
    from dataclasses import replace
    return replace(config, sut_override_dir=sut_dir)
