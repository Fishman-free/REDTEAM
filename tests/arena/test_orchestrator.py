"""End-to-end protocol tests: stub agents drive the full campaign loop offline."""
from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

from rsi4safety.arena.audit import HashChain
from rsi4safety.arena.config import ArenaConfig
from rsi4safety.arena.exchange import new_submission_id, write_json_atomic
from rsi4safety.arena.orchestrator import ArenaOrchestrator
from rsi4safety.arena.runtime import StubAgentRuntime

REPO_ROOT = Path(__file__).resolve().parents[2]


def _config(tmp: Path, campaign: str, **overrides) -> ArenaConfig:
    settings = dict(
        campaign_id=campaign, state_dir=tmp / campaign, rounds=1, repetitions=1,
        dry_run=True, repo_root=REPO_ROOT,
    )
    settings.update(overrides)
    return ArenaConfig(**settings)


class _FixingDefenderRuntime(StubAgentRuntime):
    """Defender that flips the SUT policy gateway default to the guarded profile."""

    def _defender(self, config: ArenaConfig, round_index: int) -> str:
        staging = Path(tempfile.mkdtemp(prefix="fixing-defender-"))
        try:
            patched = staging / "src"
            shutil.copytree(config.sut_dir, patched,
                            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            policy = patched / "app" / "policy.py"
            text = policy.read_text(encoding="utf-8")
            # A real code fix: always select the guarded flag set. The driver pins
            # PAYGATE_GATEWAY=research in the environment, so changing the env
            # default would be a no-op here - exactly what a defender must notice.
            patched_text = text.replace(
                'GUARDED_FLAGS if mode == "guarded" else RESEARCH_FLAGS', 'GUARDED_FLAGS')
            if patched_text == text:
                raise AssertionError("guard-flags patch point not found in policy.py")
            policy.write_text(patched_text, encoding="utf-8")
            dirs = config.role_dirs("defender")
            brief = self._latest_brief(dirs["inbox"])
            base = brief.get("base_sut_version", "unknown")
            patch_id = new_submission_id("pat", {"round": round_index, "base": base, "fix": True})
            dirs["outbox"].mkdir(parents=True, exist_ok=True)
            tar_path = dirs["outbox"] / f"patch-{patch_id}.tar"
            with tarfile.open(tar_path, "w") as archive:
                for member in sorted(patched.rglob("*")):
                    if member.is_file() and "__pycache__" not in member.parts:
                        archive.add(member, arcname=str(member.relative_to(patched)))
            digest = hashlib.sha256(tar_path.read_bytes()).hexdigest()
            write_json_atomic(dirs["outbox"] / f"patch-{patch_id}.json", {
                "schema_version": 1, "type": "patch_submission",
                "submission_id": patch_id, "round": round_index,
                "base_sut_version": base, "patch_ref": f"git:test-{digest[:12]}",
                "summary": "default the policy gateway to the guarded profile",
                "tests_added": [], "files": {"patch.tar": f"sha256:{digest}"},
            })
            return f"submitted {patch_id}"
        finally:
            shutil.rmtree(staging, ignore_errors=True)


class _FailingRoundRuntime(StubAgentRuntime):
    """Attacker crashes on round 2 so the campaign stops at a round boundary."""

    def _attacker(self, config, round_index):
        if round_index == 2:
            raise RuntimeError("simulated crash in the attacker session")
        return super()._attacker(config, round_index)


class ArenaProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_protocol_completes_honestly_without_a_fix(self) -> None:
        config = _config(self.tmp, "it-honest")
        orchestrator = ArenaOrchestrator(config, runtime=StubAgentRuntime())
        report = orchestrator.run()
        self.assertEqual(report["status"], "completed", report.get("stop_reason"))
        round_one = report["rounds"][0]
        # The stub attacker's forged receipt forces a skip-payment failure: a valid finding.
        self.assertTrue(round_one["verdicts"], "judge must adjudicate at least one evidence")
        self.assertTrue(round_one["verdicts"][0]["valid_finding"])
        # But the stub patch fixes nothing, so promotion must be refused.
        self.assertFalse(round_one["promoted"])
        self.assertIn("candidate_failed_frozen_suite", round_one["promotion"]["reasons"])
        # Parent keeps its seeded vulnerabilities: canonical attacks cause real violations.
        self.assertGreater(round_one["promotion"]["parent_scores"]["actual_violations"], 0)
        # The fixed-guard baseline passes the frozen final suite; the seed does not.
        final = report["final_evaluation"]
        self.assertTrue(final["fixed_guard"]["scores"]["passed"])
        self.assertFalse(final["initial"]["scores"]["passed"])
        self.assertEqual(report["final_tree_sha256"], report["initial_tree_sha256"])
        # Audit chain and evidence bundles exist and verify.
        verification = HashChain.verify(config.audit_dir / "chain.jsonl")
        self.assertTrue(verification.ok, verification.reason)
        self.assertTrue(list((config.evidence_dir).glob("ev-*/manifest.json")))
        self.assertTrue((config.state_dir / "report.md").exists())

    def test_promotion_when_defender_ships_a_real_fix(self) -> None:
        config = _config(self.tmp, "it-promote")
        orchestrator = ArenaOrchestrator(config, runtime=_FixingDefenderRuntime())
        report = orchestrator.run()
        self.assertEqual(report["status"], "completed", report.get("stop_reason"))
        round_one = report["rounds"][0]
        self.assertTrue(round_one["verdicts"][0]["valid_finding"])
        self.assertTrue(round_one["promoted"], round_one["promotion"])
        # The evolved tree differs from the seed and passes the frozen final suite.
        self.assertNotEqual(report["final_tree_sha256"], report["initial_tree_sha256"])
        self.assertTrue(report["final_evaluation"]["evolved"]["scores"]["passed"])
        self.assertFalse(report["final_evaluation"]["initial"]["scores"]["passed"])
        # The promoted patch survives as a regression entry for later rounds.
        regressions = (config.state_dir / "regressions.jsonl")
        self.assertTrue(regressions.exists())

    def test_benchmark_metrics_are_programmatic(self) -> None:
        config = _config(self.tmp, "it-promote")
        report = ArenaOrchestrator(config, runtime=_FixingDefenderRuntime()).run()
        benchmark = report["benchmark"]
        self.assertEqual(benchmark["benchmark_version"], "payment-agent-security-v1")
        self.assertGreater(benchmark["exploitability_initial_pct"], 0)
        self.assertEqual(benchmark["residual_evolved_pct"], 0)
        self.assertEqual(benchmark["fix_effectiveness_pct"], 100.0)
        self.assertEqual(benchmark["residual_families"], [])
        self.assertTrue(benchmark["guard_parity_reached"])
        self.assertGreater(benchmark["research_efficiency"]["valid_findings"], 0)

    def test_resume_and_execution_cache(self) -> None:
        config = _config(self.tmp, "it-resume", rounds=2)
        first = ArenaOrchestrator(config, runtime=_FailingRoundRuntime()).run()
        self.assertEqual(first["status"], "stopped")
        self.assertEqual(len(first["rounds"]), 1)
        chain_path = config.audit_dir / "chain.jsonl"
        self.assertNotIn('"resume"', chain_path.read_text())
        # Rerun with the same config resumes at round 2 instead of repeating round 1.
        second = ArenaOrchestrator(config, runtime=StubAgentRuntime()).run()
        self.assertEqual(second["status"], "completed", second.get("stop_reason"))
        self.assertEqual(len(second["rounds"]), 2)
        chain = chain_path.read_text()
        self.assertIn('"resume"', chain)
        # Repeated executions come from the cache, not from new SUT runs.
        self.assertIn('"execution_cache_hit"', chain)
        cache_dir = config.state_dir / "cache" / "executions"
        self.assertTrue(list(cache_dir.glob("*.json")))
        # A fully completed campaign rerun is a no-op, not a repeat.
        third = ArenaOrchestrator(config, runtime=StubAgentRuntime()).run()
        self.assertEqual(len(third["rounds"]), 2)
        self.assertIn('"resume_noop"', chain_path.read_text())

    def test_programmatic_judging_is_default_and_reproducibility_gated(self) -> None:
        config = _config(self.tmp, "it-judge")
        report = ArenaOrchestrator(config, runtime=StubAgentRuntime()).run()
        round_one = report["rounds"][0]
        self.assertEqual(round_one["judge_session"]["mode"], "programmatic")
        verdict = round_one["verdicts"][0]
        self.assertTrue(verdict["valid_finding"])
        # The stub's forged receipt is a utility failure, adjudicated deterministically.
        manifest_files = sorted((config.evidence_dir).glob("ev-*/manifest.json"))
        manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
        self.assertIn(manifest["programmatic_verdict"]["utility_success"], (False, True))


if __name__ == "__main__":
    unittest.main()
