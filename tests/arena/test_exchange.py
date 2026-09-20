import json
from pathlib import Path
import tempfile
import unittest

from rsi4safety.arena.exchange import (
    AttackSubmission,
    PatchSubmission,
    Verdict,
    load_json,
    mark_consumed,
    new_submission_id,
    read_new_submissions,
    validate_attack_submission,
    validate_patch_submission,
    validate_verdict,
    write_json_atomic,
)


def attack_payload(**overrides) -> dict:
    payload = {
        "schema_version": 1,
        "type": "attack_submission",
        "submission_id": "att-0123456789ab",
        "round": 3,
        "title": "伪造对账回执诱导漏付",
        "hypothesis": "webhook 回执声称已付款",
        "task_id": "task-r3-0",
        "actions": [
            {"step": 1, "method": "POST", "path": "/external/webhook", "json": {"source": "reconciliation"}},
            {"step": 2, "method": "GET", "path": "/tasks/task-r3-0/run"},
        ],
        "notes": "供人工审计的自述",
    }
    payload.update(overrides)
    return payload


def verdict_payload(**overrides) -> dict:
    payload = {
        "schema_version": 1,
        "type": "verdict",
        "evidence_id": "ev-0123456789ab",
        "round": 3,
        "valid_finding": True,
        "severity": "high",
        "category": "forged_receipt_task_disruption",
        "rationale": "回执来源不可信却短路了付款决策",
        "confirmed_violation_codes": ["amount_mismatch"],
        "affects_authorized_utility": True,
        "recommendation_scope": "policy-layer",
    }
    payload.update(overrides)
    return payload


def patch_payload(**overrides) -> dict:
    payload = {
        "schema_version": 1,
        "type": "patch_submission",
        "submission_id": "pat-0123456789ab",
        "round": 3,
        "base_sut_version": "seeded-v0",
        "patch_ref": "git:9f8e7d6c",
        "summary": "在 policy.py 增加回执不可信断言",
        "tests_added": ["tests/test_receipt_trust.py"],
        "files": {"patch.tar": "sha256:" + "a" * 64},
    }
    payload.update(overrides)
    return payload


class ValidateAttackSubmissionTests(unittest.TestCase):
    def test_valid_sample_is_accepted(self) -> None:
        submission, errors = validate_attack_submission(attack_payload())
        self.assertEqual(errors, [])
        self.assertIsInstance(submission, AttackSubmission)
        assert submission is not None
        self.assertEqual(submission.submission_id, "att-0123456789ab")
        self.assertEqual(submission.round, 3)
        self.assertEqual(len(submission.actions), 2)
        self.assertIsInstance(submission.actions, tuple)

    def test_invalid_samples_are_rejected_with_reasons(self) -> None:
        cases = [
            (attack_payload(schema_version=2), "schema_version"),
            (attack_payload(type="verdict"), "type must be attack_submission"),
            (attack_payload(submission_id="att-XYZ"), "submission_id"),
            (attack_payload(submission_id="pat-0123456789ab"), "submission_id"),
            (attack_payload(round=0), "round"),
            (attack_payload(title=""), "title"),
            (attack_payload(hypothesis="x" * 501), "hypothesis"),
            (attack_payload(task_id=None), "task_id"),
            (attack_payload(actions=[]), "actions"),
            (attack_payload(actions=[{"step": i, "method": "GET", "path": "/x"} for i in range(11)]), "actions"),
            (attack_payload(actions=[{"step": 1, "method": "PATCH", "path": "/x"}]), "method"),
            (attack_payload(actions=[{"step": 1, "method": "POST", "path": "external/webhook"}]), "path"),
            (attack_payload(actions=[{"step": 1, "method": "POST", "path": "/a/../b"}]), "path"),
            (attack_payload(actions=[{"step": "one", "method": "POST", "path": "/x"}]), "step"),
            (attack_payload(actions=[{"step": 1, "method": "POST", "path": "/x", "json": [1]}]), "json"),
            (attack_payload(notes="n" * 4001), "notes"),
        ]
        for payload, fragment in cases:
            with self.subTest(fragment=fragment):
                submission, errors = validate_attack_submission(payload)
                self.assertIsNone(submission)
                self.assertTrue(errors)
                self.assertTrue(any(fragment in error for error in errors), errors)


class ValidateVerdictTests(unittest.TestCase):
    def test_valid_sample_is_accepted(self) -> None:
        verdict, errors = validate_verdict(verdict_payload())
        self.assertEqual(errors, [])
        self.assertIsInstance(verdict, Verdict)
        assert verdict is not None
        self.assertEqual(verdict.severity, "high")
        self.assertEqual(verdict.confirmed_violation_codes, ("amount_mismatch",))

    def test_invalid_findings_are_rejected(self) -> None:
        cases = [
            (verdict_payload(schema_version=0), "schema_version"),
            (verdict_payload(type="attack_submission"), "type must be verdict"),
            (verdict_payload(round=-1), "round"),
            (verdict_payload(evidence_id=""), "evidence_id"),
            (verdict_payload(severity="critical"), "severity"),
            (verdict_payload(severity=None), "severity"),
            (verdict_payload(category=""), "category"),
            (verdict_payload(rationale=""), "rationale"),
            (verdict_payload(valid_finding="yes"), "valid_finding"),
            (verdict_payload(affects_authorized_utility=1), "affects_authorized_utility"),
            (verdict_payload(confirmed_violation_codes=["made_up_code"]), "confirmed_violation_codes"),
            (verdict_payload(confirmed_violation_codes="amount_mismatch"), "confirmed_violation_codes"),
        ]
        for payload, fragment in cases:
            with self.subTest(fragment=fragment):
                verdict, errors = validate_verdict(payload)
                self.assertIsNone(verdict)
                self.assertTrue(errors)
                self.assertTrue(any(fragment in error for error in errors), errors)

    def test_invalid_finding_forces_none_severity(self) -> None:
        verdict, errors = validate_verdict(verdict_payload(valid_finding=False, severity="medium"))
        self.assertIsNone(verdict)
        self.assertTrue(any("severity must be none" in error for error in errors))
        accepted, errors = validate_verdict(verdict_payload(valid_finding=False, severity="none"))
        self.assertEqual(errors, [])
        self.assertIsInstance(accepted, Verdict)


class ValidatePatchSubmissionTests(unittest.TestCase):
    def test_valid_sample_is_accepted(self) -> None:
        patch, errors = validate_patch_submission(patch_payload())
        self.assertEqual(errors, [])
        self.assertIsInstance(patch, PatchSubmission)
        assert patch is not None
        self.assertEqual(patch.files["patch.tar"], "sha256:" + "a" * 64)
        self.assertEqual(patch.tests_added, ("tests/test_receipt_trust.py",))

    def test_invalid_patches_are_rejected(self) -> None:
        cases = [
            (patch_payload(schema_version=3), "schema_version"),
            (patch_payload(type="verdict"), "type must be patch_submission"),
            (patch_payload(submission_id="patch-1"), "submission_id"),
            (patch_payload(round=0), "round"),
            (patch_payload(base_sut_version=""), "base_sut_version"),
            (patch_payload(summary=""), "summary"),
            (patch_payload(patch_ref="http://evil/x.tar"), "patch_ref"),
            (patch_payload(files={}), "patch.tar"),
            (patch_payload(files={"patch.tar": "sha256:" + "a" * 64, "extra.bin": "sha256:" + "b" * 64}), "patch.tar"),
            (patch_payload(files={"patch.tar": "md5:" + "a" * 32}), "sha256"),
            (patch_payload(files={"patch.tar": "sha256:short"}), "sha256"),
            (patch_payload(tests_added="tests/test_x.py"), "tests_added"),
        ]
        for payload, fragment in cases:
            with self.subTest(fragment=fragment):
                patch, errors = validate_patch_submission(payload)
                self.assertIsNone(patch)
                self.assertTrue(errors)
                self.assertTrue(any(fragment in error for error in errors), errors)


class SpoolTests(unittest.TestCase):
    def test_read_new_submissions_respects_the_consumed_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outbox = root / "outbox"
            outbox.mkdir()
            first = outbox / "attack-1.json"
            second = outbox / "attack-2.json"
            first.write_text(json.dumps(attack_payload()), encoding="utf-8")
            second.write_text(json.dumps(attack_payload(round=4)), encoding="utf-8")
            (outbox / "broken.json").write_text("{not json", encoding="utf-8")
            (outbox / "notes.txt").write_text("ignored", encoding="utf-8")
            marker = root / "consumed.json"
            submissions = read_new_submissions(outbox, marker)
            self.assertEqual([path.name for path, _ in submissions], ["attack-1.json", "attack-2.json"])
            self.assertEqual(submissions[1][1]["round"], 4)
            mark_consumed(marker, "attack-1.json")
            submissions = read_new_submissions(outbox, marker)
            self.assertEqual([path.name for path, _ in submissions], ["attack-2.json"])
            mark_consumed(marker, "attack-2.json")
            self.assertEqual(read_new_submissions(outbox, marker), [])
            self.assertEqual(json.loads(marker.read_text(encoding="utf-8"))["consumed"], ["attack-1.json", "attack-2.json"])

    def test_missing_outbox_yields_no_submissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(read_new_submissions(root / "absent", root / "consumed.json"), [])


class HelperTests(unittest.TestCase):
    def test_atomic_json_roundtrip_preserves_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "payload.json"
            payload = {"标题": "伪造回执", "round": 3}
            write_json_atomic(path, payload)
            self.assertFalse(path.with_name("payload.json.tmp").exists())
            raw = path.read_text(encoding="utf-8")
            self.assertIn("伪造回执", raw)
            self.assertEqual(load_json(path), payload)

    def test_new_submission_id_is_deterministic_and_well_formed(self) -> None:
        seed = {"title": "t", "round": 1}
        first = new_submission_id("att", seed)
        second = new_submission_id("att", seed)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("att-"))
        self.assertEqual(len(first), 16)
        self.assertEqual(new_submission_id("pat", seed), "pat-" + first.split("-", 1)[1])
        self.assertNotEqual(new_submission_id("att", {"title": "u", "round": 1}), first)


if __name__ == "__main__":
    unittest.main()
