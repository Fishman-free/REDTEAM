"""P0 engineering fixes (RESEARCH_PLAN §6 items 2/6/7/8).

- prompt_only scope: bidirectional full-tree compare against the explicit
  active parent (self.config.sut_dir), catching modified, added and deleted
  files of any type.
- promotion retest: the candidate evaluation always bypasses the execution
  cache and records zero cache hits as evidence.
- defender input: the findings brief carries the paired HTTP trace, host
  ledger rows and the evidence bundle reference (facts, not inferences).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from rsi4safety.arena.audit import HashChain
from rsi4safety.arena.config import ArenaConfig
from rsi4safety.arena.exchange import new_submission_id, write_json_atomic
from rsi4safety.arena.orchestrator import ArenaOrchestrator
from rsi4safety.arena.runtime import StubAgentRuntime

REPO_ROOT = Path(__file__).resolve().parents[3]


def _config(tmp: Path, campaign: str, **overrides) -> ArenaConfig:
    settings = dict(
        campaign_id=campaign, state_dir=tmp / campaign, rounds=1, repetitions=1,
        dry_run=True, repo_root=REPO_ROOT,
    )
    settings.update(overrides)
    return ArenaConfig(**settings)


def _chain_entries(config: ArenaConfig) -> list[dict]:
    return [json.loads(line) for line
            in (config.audit_dir / "chain.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _tar_source_tree(patched: Path, tar_path: Path) -> str:
    with tarfile.open(tar_path, "w") as archive:
        for member in sorted(patched.rglob("*")):
            if member.is_file() and "__pycache__" not in member.parts:
                archive.add(member, arcname=str(member.relative_to(patched)))
    return hashlib.sha256(tar_path.read_bytes()).hexdigest()


class _PromptOnlyDefenderRuntime(StubAgentRuntime):
    """Defender that ships a full-tree patch with one deliberate mutation."""

    mode = "policy_edit"

    def _defender(self, config: ArenaConfig, round_index: int) -> str:
        staging = Path(tempfile.mkdtemp(prefix="prompt-only-defender-"))
        try:
            patched = staging / "src"
            shutil.copytree(config.sut_dir, patched,
                            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            if self.mode == "policy_edit":
                policy = patched / "app" / "policy.py"
                policy.write_text(policy.read_text(encoding="utf-8") + "\n# scope probe\n",
                                  encoding="utf-8")
            elif self.mode == "delete_file":
                (patched / "app" / "surfaces.py").unlink()
            elif self.mode == "add_binary":
                (patched / "app" / "notes.txt").write_text("scope probe", encoding="utf-8")
            elif self.mode == "prompts_only":
                (patched / "app" / "prompts.py").write_text("PROMPT_HINT = 'stay in scope'\n",
                                                            encoding="utf-8")
            else:  # pragma: no cover - test wiring guard
                raise AssertionError(f"unknown mode {self.mode}")
            dirs = config.role_dirs("defender")
            brief = self._latest_brief(dirs["inbox"])
            base = brief.get("base_sut_version", "unknown")
            patch_id = new_submission_id("pat", {"round": round_index, "base": base,
                                                 "mode": self.mode})
            dirs["outbox"].mkdir(parents=True, exist_ok=True)
            tar_path = dirs["outbox"] / f"patch-{patch_id}.tar"
            file_digest = _tar_source_tree(patched, tar_path)
            write_json_atomic(dirs["outbox"] / f"patch-{patch_id}.json", {
                "schema_version": 1, "type": "patch_submission",
                "submission_id": patch_id, "round": round_index,
                "base_sut_version": base, "patch_ref": f"git:test-{file_digest[:12]}",
                "summary": f"prompt_only scope probe: {self.mode}",
                "tests_added": [], "files": {"patch.tar": f"sha256:{file_digest}"},
            })
            return f"submitted {patch_id}"
        finally:
            shutil.rmtree(staging, ignore_errors=True)


class _FixingRuntime(StubAgentRuntime):
    """Defender that ships a real code fix (policy gateway defaults to guarded)."""

    def _defender(self, config: ArenaConfig, round_index: int) -> str:
        staging = Path(tempfile.mkdtemp(prefix="fixing-defender-"))
        try:
            patched = staging / "src"
            shutil.copytree(config.sut_dir, patched,
                            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            policy = patched / "app" / "policy.py"
            text = policy.read_text(encoding="utf-8")
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
            file_digest = _tar_source_tree(patched, tar_path)
            write_json_atomic(dirs["outbox"] / f"patch-{patch_id}.json", {
                "schema_version": 1, "type": "patch_submission",
                "submission_id": patch_id, "round": round_index,
                "base_sut_version": base, "patch_ref": f"git:test-{file_digest[:12]}",
                "summary": "default the policy gateway to the guarded profile",
                "tests_added": [], "files": {"patch.tar": f"sha256:{file_digest}"},
            })
            return f"submitted {patch_id}"
        finally:
            shutil.rmtree(staging, ignore_errors=True)


class PromptOnlyScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_out_of_scope_mutations_are_rejected(self) -> None:
        cases = {
            "policy_edit": "scope_violation_non_prompt_code_modified",
            "delete_file": "scope_violation_file_deleted",
            "add_binary": "scope_violation_file_added",
        }
        for mode, expected_reason in cases.items():
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as raw:
                    config = _config(Path(raw), f"it-scope-{mode}", defender_scope="prompt_only")
                    runtime = _PromptOnlyDefenderRuntime()
                    runtime.mode = mode
                    ArenaOrchestrator(config, runtime=runtime).run()
                    rejected = [entry["payload"]["reason"] for entry in _chain_entries(config)
                                if entry["kind"] == "patch_rejected" and "reason" in entry["payload"]]
                    self.assertTrue(any(str(reason).startswith(expected_reason)
                                        for reason in rejected), rejected)

    def test_prompt_and_test_files_stay_in_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            config = _config(Path(raw), "it-scope-ok", defender_scope="prompt_only")
            runtime = _PromptOnlyDefenderRuntime()
            runtime.mode = "prompts_only"
            ArenaOrchestrator(config, runtime=runtime).run()
            for entry in _chain_entries(config):
                reason = str(entry["payload"].get("reason", ""))
                self.assertFalse(reason.startswith("scope_violation"), entry)


class FreshRetestTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_promotion_retest_records_zero_cache_hits(self) -> None:
        config = _config(self.tmp, "it-fresh-promote")
        orchestrator = ArenaOrchestrator(config, runtime=_FixingRuntime())
        report = orchestrator.run()
        self.assertEqual(report["status"], "completed", report.get("stop_reason"))
        self.assertTrue(report["rounds"][0]["promoted"], report["rounds"][0])
        retests = [entry for entry in _chain_entries(config) if entry["kind"] == "candidate_retest"]
        self.assertEqual(len(retests), 1)
        self.assertEqual(retests[0]["payload"]["cache_hits"], 0)

    def test_resubmitted_identical_patch_still_executes_fresh(self) -> None:
        config = _config(self.tmp, "it-fresh-resubmit")
        orchestrator = ArenaOrchestrator(config, runtime=_FixingRuntime())
        report = orchestrator.run()
        self.assertTrue(report["rounds"][0]["promoted"], report["rounds"][0])
        outbox = config.role_dirs("defender")["outbox"]
        original = sorted(outbox.glob("patch-*.tar"))[0]
        payload = json.loads((outbox / (original.stem + ".json")).read_text(encoding="utf-8"))
        second_id = new_submission_id("pat", {"resubmit": True})
        shutil.copyfile(original, outbox / f"patch-{second_id}.tar")
        write_json_atomic(outbox / f"patch-{second_id}.json",
                          {**payload, "submission_id": second_id, "round": 1})

        @dataclass
        class _Resubmission:
            submission_id: str
            files: dict = field(default_factory=dict)
            summary: str = ""
            tests_added: list = field(default_factory=list)

        before = orchestrator._execution_count
        promoted, gate = orchestrator._evaluate_patch(
            1, _Resubmission(second_id, dict(payload["files"]), "identical resubmission", []),
            [], [])
        self.assertFalse(promoted)  # evolved parent passes the suite: nothing to fix
        self.assertIn("no_reproduced_failure", gate["reasons"])
        retests = [entry for entry in _chain_entries(config) if entry["kind"] == "candidate_retest"]
        self.assertEqual(len(retests), 2, retests)
        # The suite keys are warm (round 1 evaluated the identical tree), so any
        # cache read would show up here; the retest must still be all-miss.
        self.assertEqual(retests[1]["payload"]["cache_hits"], 0)
        self.assertGreater(orchestrator._execution_count, before)


class DefenderEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_findings_brief_carries_replayable_execution_evidence(self) -> None:
        config = _config(self.tmp, "it-defender-evidence")
        ArenaOrchestrator(config, runtime=StubAgentRuntime()).run()
        inbox = config.role_dirs("defender")["inbox"]
        briefs = sorted(inbox.glob("round-*-brief.json"))
        self.assertTrue(briefs, "defender must receive a findings brief")
        findings = json.loads(briefs[0].read_text(encoding="utf-8"))["findings"]
        self.assertTrue(findings, "the stub attacker produces at least one valid finding")
        evidence = findings[0]["execution_evidence"]
        self.assertTrue(evidence["http_trace"], "defender must see the paired HTTP trace")
        self.assertTrue(evidence["host_ledgers"], "defender must see host ledger rows")
        rows = [row for ledger in evidence["host_ledgers"] for row in ledger["rows"]]
        self.assertTrue(rows, "host ledger rows must be present, not only digests")
        bundle = config.state_dir / evidence["evidence_ref"]
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        recomputed = hashlib.sha256(json.dumps(
            manifest, sort_keys=True, ensure_ascii=False,
            separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(evidence["manifest_digest"], recomputed)
        # The evidence bundle itself must still verify against its manifest.
        from rsi4safety.arena.control import verify_evidence
        ok, reason = verify_evidence(bundle)
        self.assertTrue(ok, reason)
        # And the audit chain must remain intact after the new events.
        self.assertTrue(HashChain.verify(config.audit_dir / "chain.jsonl").ok)


if __name__ == "__main__":
    unittest.main()
