"""Bounded declarative package search, screening and independent confirmation."""
import json
from rsi4safety.arena.audit import file_sha256
from .campaign_io import write_json
from .defense import DefensePackage
from .models import canonical_hash
from .defense_skills import select_defense_skills
from .gate import GATE_SCOPE, functional_pass, promotion_gate

def repair_round(self, index, version, round_record):
    findings = [f["case"] for f in self.state["findings"]]
    finding_ids = [case["id"] for case in findings]
    # Findings first, then ordinary tasks, then transfer fixtures. Acceptance
    # never enters repair feedback or any development gate.
    cases = findings + self.normal["development"] + self.normal["transfer"]
    parent_phase = self.parent_gate_phase(version, cases)
    parent_runs = self.run_suite(cases, version, parent_phase)
    failures = [r for r in parent_runs if r["case_id"] in finding_ids and not functional_pass(r["evaluation"])]
    if not failures:
        return version
    feedback = []
    unique_failures = list({r["case_id"]: r for r in failures}.values())
    development_ids = {case["id"] for case in self.normal["development"]}
    normals = [r for r in parent_runs if r["case_id"] in development_ids and r["repetition"] == 1]
    normal_brief = [{"case_id": r["case_id"], "case": r["case"], "evaluation": r["evaluation"],
                     **({"snapshot": r["snapshot"]} if not functional_pass(r["evaluation"]) else {})} for r in normals]
    seen_packages = {canonical_hash(self.defense_package(version))}
    for path in (self.root / "candidates").glob("*/defense.json"):
        seen_packages.add(canonical_hash(DefensePackage.parse(json.loads(path.read_text())).to_dict()))
    last_signature, same_failures = None, 0
    for attempt in range(1, self.config.max_candidates + 1):
        identifier = f"repair-r{index}-c{attempt}"
        output = self.role_action(identifier, "repair", defense_prompt=self.instructions(version),
            defense_package=self.defense_package(version), failures=unique_failures + feedback,
            normal_baselines=normal_brief, defense_lessons=self.role_memory.defense_lessons(limit=6),
            defense_skills=select_defense_skills(
                self.observed_breach_classes(unique_failures), generation_id=identifier))
        if output is None:
            continue
        proposal = output["repair"]
        package = DefensePackage.parse(proposal.get("defense_package") or
                                       {"system_prompt": proposal["system_prompt"]}).to_dict()
        package_hash = canonical_hash(package)
        source = self.root / "candidates" / identifier
        duplicate = package_hash in seen_packages and not source.exists()
        if duplicate:
            gate = {"passed": False, "reasons": ["duplicate_package"], "regressions": [],
                    "repaired": [], "unresolved": finding_ids, "aborted_early": False,
                    "scope": GATE_SCOPE, "content_sha256": package_hash}
            write_json(self.root / "gates" / f"{identifier}.json", {
                "parent_version": version.version_id, "candidate": identifier, "gate": gate,
                "early_abort": None, "parent_trials": [], "candidate_trials": []})
            round_record.setdefault("candidates", []).append({"id": identifier, "gate": gate})
            self.chain.append("host", "candidate_skipped_duplicate", candidate=identifier, **gate)
            self.save()
            continue
        seen_packages.add(package_hash)
        if not source.exists():
            write_json(source / "defense.json", package)
        manifest = self.versions.manifests / f"{identifier}.json"
        candidate = self.versions.get(identifier) if manifest.exists() else self.versions.save_candidate(
            identifier, source, parent_version_id=version.version_id,
            parent_package_digest=version.package_digest,
            metadata={"role_call_id": output.get("role_call_id"), "mutable_surface": "declarative_agent_package"})
        if self.defense_package(candidate) != package:
            raise ValueError("committed package differs from validated proposal")
        runs, abort = self.run_candidate_gate_suite(
            cases, candidate, f"r{index}-candidate-{attempt}-screen", parent_runs,
            finding_case_ids=finding_ids)
        gate = promotion_gate(parent_runs, runs, finding_ids, aborted_early=abort is not None)
        stage = "screen"
        if gate["passed"]:
            # Only a promising package buys independent repeated evaluation.
            parent_runs = self.run_suite(cases, version, parent_phase + "-confirm",
                                         repetitions=self.config.confirmation_repetitions)
            runs, abort = self.run_candidate_gate_suite(
                cases, candidate, f"r{index}-candidate-{attempt}-confirm", parent_runs,
                repetitions=self.config.confirmation_repetitions, finding_case_ids=finding_ids)
            gate = promotion_gate(parent_runs, runs, finding_ids, aborted_early=abort is not None)
            stage = "confirmation"
        gate.update(stage=stage, candidate_package_digest=candidate.package_digest,
                    content_sha256=package_hash,
                    evaluation_id="gate-" + canonical_hash({"gate": gate,
                        "candidate": candidate.package_digest, "trials": [r["id"] for r in parent_runs + runs]})[:24])
        evaluation_path = self.root / "gates" / f"{identifier}.json"
        write_json(evaluation_path, {"parent_version": version.version_id, "candidate": candidate.version_id,
            "gate": gate, "early_abort": abort,
            "parent_trials": [r["id"] for r in parent_runs], "candidate_trials": [r["id"] for r in runs]})
        self.memory.record_feedback(candidate.version_id, version.version_id, gate["evaluation_id"],
            file_sha256(evaluation_path), gate["passed"], gate["reasons"],
            lessons=proposal.get("rationale", ""), evaluation_path=evaluation_path,
            candidate_package_digest=candidate.package_digest)
        round_record.setdefault("candidates", []).append({"id": candidate.version_id, "gate": gate})
        self.chain.append("host", "candidate_evaluated", candidate=candidate.version_id,
                          evaluation_sha256=file_sha256(evaluation_path), **gate)
        if gate["passed"]:
            promoted = self.versions.promote(candidate.version_id, evaluation=gate,
                                            expected_parent_digest=version.package_digest)
            self.chain.append("host", "live_version_promoted", parent=version.version_id,
                              version=promoted.version_id, repaired=gate["repaired"], unresolved=gate["unresolved"])
            self._record_defense_lesson(identifier, proposal, promoted, version, gate)
            self.save()
            return promoted
        regressed_ids = {item["case_id"] for item in gate["regressions"]}
        regressed_ids |= {abort["case_id"]} if abort else set()
        # Transfer contents stay withheld: only verdicts, not fixtures/gold,
        # can influence a subsequent repair.
        feedback.append({"previous_candidate": package, "gate_rejection": gate,
            "early_abort": abort, "regressed_traces": [r for r in runs if
                r["case_id"] in regressed_ids and r["case_id"] in development_ids][:4]})
        signature = canonical_hash({"dimensions": sorted({d for r in gate["regressions"] for d in r["dimensions"]}),
                                    "reasons": gate["reasons"]})
        same_failures = same_failures + 1 if signature == last_signature else 1
        last_signature = signature
        self.save()
        self.progress("candidate_rejected", version=candidate.version_id, gate=gate)
        if same_failures >= 2:
            round_record["repair_stop_reason"] = "repeated_failure_mechanism"
            self.chain.append("host", "repair_search_stopped", round=index,
                              reason="repeated_failure_mechanism", signature=signature)
            self.save()
            break
        # A later cheap screen must compare against cheap parent runs too.
        parent_runs = self.run_suite(cases, version, parent_phase)
    return version
