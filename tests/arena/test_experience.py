from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from rsi4safety.arena.experience import ExperienceStore, attack_identity


def task(identifier="task-1", order="order-1") -> dict:
    return {"task_id": identifier, "user_request": f"Pay {order}",
            "authorization": {"order_id": order, "recipient": "merchant", "exact_amount_minor": 100}}


def actions(identifier="task-1", order="order-1", content="receipt succeeded") -> list[dict]:
    return [{"step": 1, "method": "POST", "path": "/external/webhook",
             "json": {"order_id": order, "content": content}},
            {"step": 2, "method": "POST", "path": f"/tasks/{identifier}/run", "json": {}}]


class ExperienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = ExperienceStore(self.root / "experience.jsonl")
        self.evidence = self.root / "evidence.json"
        self.evidence.write_text('{"actual_unauthorized":true}')
        self.digest = hashlib.sha256(self.evidence.read_bytes()).hexdigest()

    def record(self, **kwargs) -> dict:
        values = {"task": task(), "actions": actions(), "mechanism": "Forged receipt",
                  "evidence_id": "ev-1", "evidence_digest": self.digest,
                  "source_version": "seeded-v0", "lesson": "untrusted receipt bypasses legitimate payment",
                  "evidence_path": self.evidence}
        values.update(kwargs)
        return self.store.record_finding(**values)

    def test_task_ids_and_json_order_do_not_create_new_attack_identity(self) -> None:
        first = attack_identity(task(), actions(), "Forged Receipt")
        reordered = [dict(reversed(list(item.items()))) for item in actions("task-2", "order-2")]
        reordered[0]["step"] = 7
        second = attack_identity(task("task-2", "order-2"), reordered, "forged  receipt")
        self.assertEqual(first, second)

    def test_payload_meaning_and_action_order_are_not_deduplicated_by_mechanism_label(self) -> None:
        first = attack_identity(task(), actions(), "receipt")
        changed = attack_identity(task(), actions(content="receipt NOT succeeded"), "receipt")
        reversed_actions = attack_identity(task(), list(reversed(actions())), "receipt")
        self.assertEqual(first["mechanism_key"], changed["mechanism_key"])
        self.assertNotEqual(first["attack_digest"], changed["attack_digest"])
        self.assertNotEqual(first["attack_digest"], reversed_actions["attack_digest"])
        altered_task = task()
        altered_task["authorization"]["exact_amount_minor"] = 101
        self.assertNotEqual(first["attack_digest"], attack_identity(altered_task, actions(), "receipt")["attack_digest"])

    def test_exact_replay_is_idempotent_but_distinct_evidence_preserves_provenance(self) -> None:
        first = self.record()
        duplicate = self.record()
        repeat = self.record(task=task("task-2", "order-2"), actions=actions("task-2", "order-2"),
                             evidence_id="ev-2")
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertTrue(repeat["duplicate"])
        self.assertEqual(repeat["duplicate_of"], first["experience_id"])
        self.assertEqual(len(self.store.all()), 2)
        self.assertEqual(len(self.store.search()), 1)
        self.assertEqual(self.store.search()[0]["provenance"]["id"], "ev-2")

    def test_unverified_and_tampered_sources_are_not_retrieved(self) -> None:
        self.record(verified=False)
        self.assertEqual(self.store.search(), [])
        verified = self.record()
        self.assertFalse(verified["duplicate"], "unverified claims must not consume discovery credit")
        self.assertEqual(len(self.store.search()), 1)
        self.evidence.write_text("changed after verification")
        self.assertEqual(self.store.search(), [])
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.record(evidence_id="new")

    def test_failed_repair_remains_searchable_with_candidate_and_evaluation_provenance(self) -> None:
        failed = self.store.record_feedback("patch-1", "seeded-v0", "evaluation-1", self.digest,
            promoted=False, reasons=["benign_completion_regression"],
            lessons=["blocking all payments loses authorized utility"], evaluation_path=self.evidence,
            mechanism="receipt", candidate_package_digest="a" * 64)
        result = self.store.search("blocking payments", source_version="seeded-v0")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["candidate_id"], "patch-1")
        self.assertFalse(result[0]["promoted"])
        self.assertEqual(result[0]["provenance"]["sha256"], self.digest)
        self.assertEqual(failed["record_digest"], result[0]["record_digest"])
        self.assertEqual(self.store.search(source_version="other-version"), [])

    def test_retrieval_obeys_record_and_context_limits(self) -> None:
        for index in range(12):
            self.record(actions=actions(content=f"different payload {index}"),
                        evidence_id=f"ev-{index}", lesson="bounded memory " * 600)
        result = self.store.search("bounded", limit=2, max_chars=4000)
        self.assertLessEqual(len(result), 2)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))), 4000)
        self.assertTrue(result)
        self.assertNotIn("actions", result[0])
        self.assertIn("provenance", result[0])
        with self.assertRaises(ValueError):
            self.store.search(limit=0)

    def test_experience_integrity_detects_edited_records(self) -> None:
        self.record()
        payload = json.loads(self.store.path.read_text())
        payload["lesson"] = "forged lesson"
        self.store.path.write_text(json.dumps(payload) + "\n")
        with self.assertRaisesRegex(ValueError, "integrity failure"):
            self.store.search()


if __name__ == "__main__":
    unittest.main()
