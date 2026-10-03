"""RTM claim request registry (docs/EVIDENCE_REWARD_PROTOCOL.md, frozen v1).

The arena emits one content-bound claim request per deduped, independently
validated finding; re-registering the same finding is a no-op, and the claim
id recomputes from the record's own binding fields.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rsi4safety.arena.audit import HashChain
from rsi4safety.arena.config import ArenaConfig
from rsi4safety.arena.control import digest as control_digest
from rsi4safety.arena.orchestrator import ArenaOrchestrator, _fixture
from rsi4safety.arena.runtime import StubAgentRuntime
from rsi4safety.claim_protocol import CLAIM_PROTOCOL, claim_id_hex

REPO_ROOT = Path(__file__).resolve().parents[3]
BENEFICIARY = "0x" + "ab" * 20


def _config(tmp: Path, campaign: str, **overrides) -> ArenaConfig:
    settings = dict(
        campaign_id=campaign, state_dir=tmp / campaign, rounds=1, repetitions=1,
        dry_run=True, repo_root=REPO_ROOT,
        claim_beneficiary=BENEFICIARY, claim_amount="1500000",
    )
    settings.update(overrides)
    return ArenaConfig(**settings)


def _finding(evidence_id: str, actions: list[dict], category: str = "forged_receipt") -> dict:
    fixture = _fixture("arena-r1", 17, 0)
    manifest = {"task_fixture": fixture.brief_form(),
                "attack_submission": {"actions": actions},
                "sut_version": "seed-v0", "sut_digest": "bb" * 32, "files": {}}
    return {"evidence_id": evidence_id, "manifest": manifest,
            "verdict": SimpleNamespace(category=category)}


def _requests(config: ArenaConfig) -> list[dict]:
    path = config.state_dir / "claim-requests.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line
            in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _recompute(request: dict) -> str:
    return claim_id_hex({"protocol": request["protocol"], "dedup_key": request["dedup_key"],
                         "sut_digest": request["sut_digest"],
                         "beneficiary": request["beneficiary"], "amount": request["amount"]})


class ClaimRequestRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reregistering_the_same_finding_is_a_noop(self) -> None:
        config = _config(self.tmp, "it-claim-dedup")
        orchestrator = ArenaOrchestrator(config, runtime=StubAgentRuntime())
        finding = _finding("ev-dedup0000001", StubAgentRuntime.FORGED_RECEIPT_ACTIONS)
        orchestrator._append_claim_request(1, finding, finding["manifest"])
        orchestrator._append_claim_request(2, finding, finding["manifest"])
        requests = _requests(config)
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request["claim_id"], _recompute(request))
        self.assertEqual(request["status"], "pending")
        self.assertEqual(request["beneficiary"], BENEFICIARY)
        registered = [entry for entry in
                      (config.audit_dir / "chain.jsonl").read_text(encoding="utf-8").splitlines()
                      if "claim_request_registered" in entry]
        self.assertEqual(len(registered), 1)

    def test_campaign_requests_are_content_bound(self) -> None:
        config = _config(self.tmp, "it-claim-campaign", rounds=2)
        report = ArenaOrchestrator(config, runtime=StubAgentRuntime()).run()
        self.assertEqual(report["status"], "completed", report.get("stop_reason"))
        # The stub alternates forged-receipt / recipient-swap: two distinct
        # mechanisms on two distinct authorizations, two distinct claims.
        requests = _requests(config)
        self.assertEqual(len(requests), 2)
        self.assertNotEqual(requests[0]["claim_id"], requests[1]["claim_id"])
        for request in requests:
            self.assertEqual(request["protocol"], CLAIM_PROTOCOL)
            self.assertEqual(request["claim_id"], _recompute(request))
            manifest = json.loads((config.evidence_dir / request["evidence_id"] /
                                   "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(request["sut_digest"], manifest["sut_digest"])
            self.assertEqual(request["manifest_digest"], control_digest(manifest))
        self.assertTrue(HashChain.verify(config.audit_dir / "chain.jsonl").ok)

    def test_registry_stays_empty_without_claim_config(self) -> None:
        settings = dict(campaign_id="it-claim-off", state_dir=self.tmp / "it-claim-off",
                        rounds=1, repetitions=1, dry_run=True, repo_root=REPO_ROOT)
        config = ArenaConfig(**settings)
        ArenaOrchestrator(config, runtime=StubAgentRuntime()).run()
        self.assertFalse((config.state_dir / "claim-requests.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
