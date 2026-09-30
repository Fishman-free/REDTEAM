from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from typing import Callable, Protocol
from uuid import uuid4

from .core import PaymentAgent, run_scenario
from .domain import AttackPayload, ChallengeSpec, DefensePolicy, TaskSpec, VerificationRecord, VersionManifest
from .learning import (
    CandidateArchive,
    CandidateProposer,
    ContinuousImprover,
    EvaluationReport,
    ExperienceStore,
    ImprovementOutcome,
    PromotionEvaluator,
)
from .scenarios import Scenario, default_challenge, evaluation_scenarios, shopping_task, verification_fee_attack


class AttackGenerator(Protocol):
    def generate(self, task: TaskSpec, policy: DefensePolicy, challenge: ChallengeSpec) -> AttackPayload: ...


@dataclass(frozen=True)
class RoundResult:
    round_id: str
    attack_record: VerificationRecord
    retest_record: VerificationRecord
    improvement: ImprovementOutcome | None
    before: EvaluationReport
    after: EvaluationReport
    active_version: str


class ContinuousSafetyRunner:
    """Attack, execute, score, propose bounded fixes, and retest with durable memory."""

    def __init__(
        self,
        state_dir: Path,
        *,
        agent_factory: Callable[[DefensePolicy], PaymentAgent] = PaymentAgent,
        proposer: CandidateProposer | None = None,
        attack_generator: AttackGenerator | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.agent_factory = agent_factory
        self.attack_generator = attack_generator
        self.experiences = ExperienceStore(state_dir / "verified-experiences.jsonl")
        self.archive = CandidateArchive(state_dir / "versions")
        self.evaluator = PromotionEvaluator(
            evaluation_scenarios(), agent_factory=agent_factory, experience_store=self.experiences
        )
        self.improver = ContinuousImprover(
            self.experiences, self.archive, self.evaluator, proposer=proposer
        )

    def initial_manifest(self) -> VersionManifest:
        active = self.archive.load_active()
        if active is not None:
            return active
        policy = DefensePolicy(policy_id="payment-agent-v0")
        manifest = VersionManifest(
            version_id=policy.policy_id,
            parent_version_id=None,
            policy=policy,
            experience_hash=self.experiences.content_hash,
            status="active",
        )
        self.archive.save(manifest)
        return manifest

    def run_round(
        self,
        *,
        task: TaskSpec | None = None,
        attack: AttackPayload | None = None,
    ) -> RoundResult:
        parent = self.initial_manifest()
        task = task or shopping_task()
        challenge = default_challenge(parent.version_id)
        if attack is None:
            attack = (
                self.attack_generator.generate(task, parent.policy, challenge)
                if self.attack_generator is not None
                else verification_fee_attack()
            )
        record = run_scenario(
            task, parent.policy, attack=attack, challenge=challenge,
            agent=self.agent_factory(parent.policy),
        )
        improvement = None
        if record.actual_unauthorized:
            improvement = self.improver.improve(
                parent, record, scenario=Scenario(f"regression:{attack.attack_id}", task, attack)
            )
            before = improvement.baseline
        else:
            before = self.evaluator.evaluate(parent.policy, parent.policy)

        selected = improvement.promoted if improvement and improvement.promoted else parent
        selected_report = (
            next(report for report in improvement.reports if report.candidate_version == selected.version_id)
            if improvement and improvement.promoted else before
        )
        retest = run_scenario(
            task, selected.policy, attack=attack, challenge=default_challenge(selected.version_id),
            agent=self.agent_factory(selected.policy),
        )
        active = parent
        after = before
        if improvement and improvement.promoted and (
            not retest.actual_unauthorized and not retest.attempted_unauthorized and retest.utility_success
        ):
            active = replace(selected, status="active")
            self.archive.save(active, selected_report)
            after = selected_report

        result = RoundResult(uuid4().hex, record, retest, improvement, before, after, active.version_id)
        rounds = self.state_dir / "rounds"
        rounds.mkdir(exist_ok=True)
        (rounds / f"{result.round_id}.json").write_text(
            json.dumps(
                {"task": asdict(task), "attack_payload": asdict(attack), "result": asdict(result), "summary": self.summary(result)},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        return result

    @staticmethod
    def summary(result: RoundResult) -> dict:
        def verdict(record: VerificationRecord) -> dict:
            return {
                "version": record.target_version,
                "attempted_unauthorized": record.attempted_unauthorized,
                "actual_unauthorized": record.actual_unauthorized,
                "utility_success": record.utility_success,
                "evidence_hash": record.evidence_hash,
            }

        reports = result.improvement.reports if result.improvement else ()
        proposed = result.improvement.promoted if result.improvement else None
        return {
            "round_id": result.round_id,
            "attack": verdict(result.attack_record),
            "before_scores": result.before.scores,
            "after_scores": result.after.scores,
            "scenario_count": result.after.scenario_count,
            "candidates": [
                {"version": report.candidate_version, "passed": report.promoted,
                 "scores": report.scores, "reasons": list(report.reasons)}
                for report in reports
            ],
            "retest": verdict(result.retest_record),
            "promoted_version": proposed.version_id if proposed and proposed.version_id == result.active_version else None,
            "active_version": result.active_version,
        }
