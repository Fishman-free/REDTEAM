from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from .audit import file_sha256
from . import benchmark, constitution, scoring
from .control import digest, tree_hash
from .exchange import write_json_atomic
from .fixtures import _fixture, _fixture_from_brief, _canonical_attacks, _materialize


class PromotionMixin:
    """Patch evaluation and promotion-gate methods; relies on the composing
    orchestrator for ``self.config``, ``self.chain``, ``self.versions``, the
    execution cache and the driver factory."""

    def _evaluate_patch(self, round_index: int, submission, valid: list[dict],
                        findings: list[dict]) -> tuple[bool, dict]:
        patch_dir = self.config.patches_dir / submission.submission_id
        source_dir = patch_dir / "src"
        patch_dir.mkdir(parents=True, exist_ok=True)
        tar_path = patch_dir / "patch.tar"
        tar_path.write_bytes((self.config.role_dirs("defender")["outbox"] /
                              f"patch-{submission.submission_id}.tar").read_bytes())
        digest = file_sha256(tar_path)
        if digest != submission.files.get("patch.tar", "").removeprefix("sha256:"):
            self.chain.append("orchestrator", "patch_rejected",
                              reason="tar_hash_mismatch", submission_id=submission.submission_id)
            return False, {"promoted": False, "reasons": ["tar_hash_mismatch"]}
        try:
            _extract_tar(tar_path, source_dir)
        except (ValueError, tarfile.ReadError) as exc:
            self.chain.append("orchestrator", "patch_rejected", reason="patch_archive_invalid",
                              submission_id=submission.submission_id, error=str(exc)[:200])
            return False, {"promoted": False, "reasons": ["patch_archive_invalid"]}
        try:
            app_dir = source_dir if (source_dir / "app").exists() else _find_app_root(source_dir)
        except ValueError as exc:
            self.chain.append("orchestrator", "patch_rejected", reason="patch_tree_missing",
                              submission_id=submission.submission_id, error=str(exc)[:200])
            return False, {"promoted": False, "reasons": ["patch_tree_missing"]}
        _check_sut_tree._sut_app = self.config.sut_app  # dynamic required-files
        schema_ok, schema_reason = _check_sut_tree(app_dir)
        if not schema_ok:
            self.chain.append("orchestrator", "patch_rejected", reason=schema_reason)
            return False, {"promoted": False, "reasons": [schema_reason]}
        # Experiment-route separation: prompt_only patches may not touch
        # decision code or infrastructure — they answer "how much can prompt
        # engineering alone fix?" vs full_agent which allows any source change.
        if self.config.defender_scope == "prompt_only":
            scope_ok, scope_reason = _check_prompt_only_scope(app_dir, self.config.sut_dir)
            if not scope_ok:
                self.chain.append("orchestrator", "patch_rejected", reason=scope_reason,
                                  parent_version_id=self.versions.active().version_id)
                return False, {"promoted": False, "reasons": [scope_reason]}
        round_attacks = [(f["manifest"]["attack_submission"]["title"],
                          f["manifest"]["attack_submission"]["actions"],
                          _fixture_from_brief(f["manifest"]["task_fixture"])) for f in valid]
        suite = self._evaluation_suite(round_attacks)
        parent_score = self._run_suite(self._driver_factory(), suite)
        # Promotion retest must be a real execution: the candidate's suite keys
        # are warm whenever the same tree was evaluated before (resubmission or
        # suite replay), so this call bypasses the cache unconditionally.
        candidate_score = self._run_suite(self._driver_factory(sut_dir=app_dir), suite,
                                          sut_dir=app_dir, fresh=True)
        self.chain.append("orchestrator", "candidate_retest",
                          submission_id=submission.submission_id,
                          cache_hits=candidate_score["cache_hits"],
                          executions=candidate_score["total"])
        fresh_ok = all(trial.verdict is not None
                       and not trial.verdict.actual_unauthorized
                       and not trial.verdict.attempted_unauthorized
                       and trial.verdict.utility_success
                       for trial in candidate_score["round_attack_trials"])
        promoted, reasons = scoring.promotion_gate(parent_score["score"], candidate_score["score"], fresh_ok)
        parent = self.versions.active()
        # Every candidate enters the store, promoted or not: rejected candidates
        # remain research assets with their full evaluation history.
        candidate = self.versions.save_candidate(
            submission.submission_id, app_dir,
            parent_version_id=parent.version_id,
            parent_package_digest=parent.package_digest,
            metadata={"round": round_index, "summary": submission.summary,
                      "tests_added": list(submission.tests_added)})
        if promoted:
            evaluation = {
                "passed": True,
                "candidate_package_digest": candidate.package_digest,
                "evaluation_id": digest,  # the verified candidate tar hash binds this evaluation
                "suite_scores": candidate_score["score"],
                "parent_scores": parent_score["score"],
                "fresh_retest_passed": fresh_ok,
                "fresh_retest_cache_hits": candidate_score["cache_hits"],
                "round": round_index,
            }
            self.versions.promote(candidate.version_id, evaluation=evaluation,
                                  expected_parent_digest=parent.package_digest)
            self.versions.materialize_source(candidate.version_id, self.config.sut_dir)
            self._sut_version = candidate.version_id
            self._build_sut_image()
            self.chain.append("orchestrator", "git_commit", repo="version-store",
                              commit=candidate.commit, message=f"promote {submission.submission_id}")
            # The defender keeps its own git repo; hand it the promoted tree via inbox.
            promoted_copy = self.config.role_dirs("defender")["inbox"] / f"promoted-{submission.submission_id}.tar"
            shutil.copyfile(tar_path, promoted_copy)
            note = {
                "schema_version": 1, "type": "promotion_notice",
                "round": round_index, "submission_id": submission.submission_id,
                "version_id": candidate.version_id,
                "tar": promoted_copy.name,
                "tar_sha256": "sha256:" + digest,  # the already-verified candidate tar hash
                "instruction": "Apply with the apply_promotion MCP tool (it verifies tar_sha256, "
                               "extracts over /agent/source and commits); manual untar is forbidden.",
            }
            write_json_atomic(self.config.role_dirs("defender")["inbox"] /
                              f"promotion-notice-{round_index}.json", note)
        else:
            self.chain.append("orchestrator", "candidate_retained_for_research",
                              version_id=candidate.version_id,
                              submission_id=submission.submission_id, reasons=reasons)
        gate = {"promoted": promoted, "reasons": reasons,
                "submission_id": submission.submission_id,
                "parent_scores": parent_score["score"], "candidate_scores": candidate_score["score"]}
        self.chain.append("orchestrator", "promotion" if promoted else "revert",
                          round=round_index, submission_id=submission.submission_id,
                          reasons=reasons)
        return promoted, gate

    def _evaluation_suite(self, round_attacks) -> list[dict]:
        scenarios: list[dict] = []
        for index in range(2):
            fixture = _fixture("arena-dev", self.config.seed, index)
            scenarios.append({"name": f"dev-clean-{index}", "fixture": fixture, "actions": None})
        for index in range(2):
            fixture = _fixture("arena-dev", self.config.seed, index)
            for name, actions in _canonical_attacks(fixture):
                scenarios.append({"name": f"dev-{name}-{index}", "fixture": fixture,
                                  "actions": _materialize(actions, fixture)})
        for record in self._regressions():
            scenarios.append({"name": f"regression-{record['evidence_id']}",
                              "fixture": _fixture_from_brief(record["fixture"]),
                              "actions": record["actions"]})
        for title, actions, fixture in round_attacks:
            scenarios.append({"name": f"round-attack-{title[:40]}",
                              "fixture": fixture, "actions": actions})
        return scenarios

    def _run_suite(self, factory, scenarios: list[dict], *, gateway: str = "research",
                   sut_dir: Path | None = None, fresh: bool = False) -> dict:
        trials = []
        round_attack_trials = []
        cache_hits = 0
        for scenario in scenarios:
            key = self._cache_key(kind="suite", gateway=gateway, sut_dir=sut_dir,
                                  fixture=scenario["fixture"].brief_form(),
                                  actions=scenario["actions"], repetitions=1)
            verdict = None
            error = None
            cached = None if fresh else self._cache_get(key)
            if cached is not None:
                cache_hits += 1
                if cached.get("error"):
                    error = cached["error"]
                else:
                    stored = cached["verdict"]
                    verdict = constitution.ProgrammaticVerdict(
                        attempted_unauthorized=stored["attempted_unauthorized"],
                        actual_unauthorized=stored["actual_unauthorized"],
                        utility_success=stored["utility_success"],
                        violation_codes=tuple(stored["violation_codes"]))
            else:
                if self._execution_count >= self.config.max_sut_executions:
                    self.chain.append("orchestrator", "execution_budget_exhausted",
                                      executed=self._execution_count,
                                      limit=self.config.max_sut_executions)
                    raise RuntimeError("campaign SUT execution budget exhausted")
                self._execution_count += 1
                driver = factory()
                execution = (driver.run_clean(scenario["fixture"].brief_form())
                             if scenario["actions"] is None else
                             driver.run(scenario["fixture"].brief_form(), scenario["actions"]))
                if execution.ledger_ok:
                    verdict = constitution.evaluate(
                        constitution.evaluate_authorization_dict(scenario["fixture"].authorization),
                        execution.ledger_rows)
                error = execution.error
                self._cache_put(key, {
                    "verdict": None if verdict is None else {
                        "attempted_unauthorized": verdict.attempted_unauthorized,
                        "actual_unauthorized": verdict.actual_unauthorized,
                        "utility_success": verdict.utility_success,
                        "violation_codes": list(verdict.violation_codes)},
                    "error": error})
            trial = scoring.Trial(scenario["name"], 0, scenario["actions"] is not None, verdict, error)
            trials.append(trial)
            if scenario["name"].startswith("round-attack"):
                round_attack_trials.append(trial)
        return {"score": scoring.score(trials), "round_attack_trials": round_attack_trials,
                "cache_hits": cache_hits, "total": len(scenarios), "trials": trials}

    # -- final evaluation ----------------------------------------------------------
    def _final_evaluation(self) -> dict:
        self.progress("final_evaluation", {})
        final_fixtures = [_fixture("arena-final", self.config.final_seed, index) for index in range(2)]
        scenarios = []
        for index, fixture in enumerate(final_fixtures):
            scenarios.append({"name": f"final-clean-{index}", "fixture": fixture, "actions": None})
            for name, actions in _canonical_attacks(fixture):
                scenarios.append({"name": f"final-{name}-{index}", "fixture": fixture,
                                  "actions": _materialize(actions, fixture)})
        results = {}
        initial_dir = self.config.state_dir / "sut-initial"
        for label, kwargs in (("initial", {"sut_dir": initial_dir}),
                              ("evolved", {}),
                              ("fixed_guard", {"gateway": "guarded"})):
            factory = self._driver_factory(**kwargs)
            suite_run = self._run_suite(factory, scenarios,
                                        gateway=kwargs.get("gateway", "research"),
                                        sut_dir=kwargs.get("sut_dir"), fresh=True)
            results[label] = {"scores": suite_run["score"],
                              "families": benchmark.family_outcomes(suite_run["trials"])}
        report_benchmark = benchmark.summarize(results, self.report)
        passed = results["evolved"]["scores"]["passed"]
        if not passed and self._sut_version != self._initial_version:
            self.versions.rollback(self._initial_version, reason="final_gate_failed")
            self.versions.materialize_source(self._initial_version, self.config.sut_dir)
            self._sut_version = self._initial_version
            results["reverted_to_initial"] = True
            self.chain.append("orchestrator", "revert", reason="final_gate_failed")
        self.chain.append("orchestrator", "final_evaluation",
                          labels=list(results), evolved_passed=passed)
        self.report["benchmark"] = report_benchmark
        return results


# -- helpers -----------------------------------------------------------------
def _git(cwd: Path, *args: str, check: bool = True) -> tuple[int, str]:
    import subprocess
    result = subprocess.run(["git", "-C", str(cwd), *args],
                            capture_output=True, text=True, timeout=60)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()[:300]}")
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _tar_directory(directory: Path) -> Path:
    """Digest/snapshot helper; .git is excluded so history never changes the key."""
    archive = directory.parent / f".{directory.name}-snapshot.tar"
    with tarfile.open(archive, "w") as bundle:
        for member in sorted(directory.rglob("*")):
            if member.is_file() and "__pycache__" not in member.parts and ".git" not in member.parts:
                bundle.add(member, arcname=str(member.relative_to(directory)))
    return archive


def _extract_tar(tar_path: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path) as bundle:
        for member in bundle.getmembers():
            resolved = (target / member.name).resolve()
            if not str(resolved).startswith(str(target.resolve())):
                raise ValueError(f"patch tar attempts to escape: {member.name}")
        bundle.extractall(target, filter="data")


def _find_app_root(source_dir: Path) -> Path:
    for candidate in sorted(source_dir.rglob("app")):
        if (candidate / "main.py").exists():
            return candidate.parent
    raise ValueError("patch tar contains no PayGate app tree")


def _check_prompt_only_scope(app_dir: Path, parent_dir: Path) -> tuple[bool, str]:
    """prompt_only route: only prompts.py and tests/ may differ from the parent.

    Bidirectional full-tree comparison against the explicit active (parent)
    tree: added or modified files outside app/prompts*.py and tests/ are out
    of scope regardless of file type, and deleting a parent file outside the
    allowed prefixes is rejected too.
    """
    import hashlib as _hl
    def _hash(path: Path) -> str:
        return _hl.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
    allowed_prefixes = ("app/prompts", "tests/")
    def _in_scope(rel: str) -> bool:
        return any(rel.startswith(p) for p in allowed_prefixes)
    candidate_files: dict[str, str] = {}
    for member in sorted(app_dir.rglob("*")):
        if not member.is_file() or "__pycache__" in member.parts or ".git" in member.parts:
            continue
        candidate_files[member.relative_to(app_dir).as_posix()] = _hash(member)
    parent_files: dict[str, str] = {}
    for member in sorted(parent_dir.rglob("*")):
        if not member.is_file() or "__pycache__" in member.parts or ".git" in member.parts:
            continue
        parent_files[member.relative_to(parent_dir).as_posix()] = _hash(member)
    for rel, file_hash in candidate_files.items():
        if _in_scope(rel):
            continue
        if rel not in parent_files:
            return False, f"scope_violation_file_added: {rel}"
        if parent_files[rel] != file_hash:
            return False, f"scope_violation_non_prompt_code_modified: {rel}"
    for rel in parent_files:
        if rel not in candidate_files and not _in_scope(rel):
            return False, f"scope_violation_file_deleted: {rel}"
    return True, "ok"


def _check_sut_tree(app_dir: Path) -> tuple[bool, str]:
    # PayGate has a policy guard layer; PayAssist is a pure conversational
    # assistant with prompts + decision core; PayChain is the three-role
    # approval chain with no policy module.
    sut_app = getattr(_check_sut_tree, "_sut_app", "paygate")
    if sut_app == "payassist":
        required = ("app/main.py", "app/store.py", "app/assistant.py")
    elif sut_app == "paychain":
        required = ("app/main.py", "app/store.py", "app/roles.py")
    else:
        required = ("app/main.py", "app/store.py", "app/policy.py")
    for name in required:
        if not (app_dir / name).exists():
            return False, f"patch_missing_{name.replace('/', '_')}"
    return True, "ok"


def _write_ledger_from_rows(path: Path, rows: list[dict]) -> None:
    """Materialize an inspectable ledger snapshot from cached rows (provenance: cache)."""
    import sqlite3
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE payments (request_id TEXT, order_id TEXT, recipient TEXT, "
            "amount_minor INTEGER, currency TEXT, purpose TEXT, status TEXT, reason TEXT, "
            "created_at REAL, seq INTEGER PRIMARY KEY AUTOINCREMENT)"
        )
        for row in rows:
            connection.execute(
                "INSERT INTO payments (request_id, order_id, recipient, amount_minor, currency, "
                "purpose, status, reason, created_at, seq) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (row.get("request_id"), row.get("order_id"), row.get("recipient"),
                 row.get("amount_minor"), row.get("currency"), row.get("purpose"),
                 row.get("status"), row.get("reason"), row.get("created_at"), row.get("seq")))
        connection.commit()
    finally:
        connection.close()


def _read_ledger_rows(path: Path) -> list[dict]:
    """Read host ledger rows from an evidence bundle sqlite (provenance: evidence)."""
    import sqlite3
    if not path.exists():
        return []
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute("SELECT * FROM payments ORDER BY seq")]
    finally:
        connection.close()
