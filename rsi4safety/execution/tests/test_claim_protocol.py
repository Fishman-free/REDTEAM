"""Claim binding protocol (docs/EVIDENCE_REWARD_PROTOCOL.md, frozen v1).

The sample constant is shared with contracts/test/claim-id.test.js: both sides
must derive the identical claim_id for the identical payload, and any change
to one side's canonicalization breaks its own test.
"""
from __future__ import annotations

import unittest

from rsi4safety.claim_protocol import (
    CLAIM_PROTOCOL,
    canonical_json,
    claim_id_hex,
    claim_request,
    fixture_digest,
)

SAMPLE_PAYLOAD = {
    "protocol": CLAIM_PROTOCOL,
    "dedup_key": "aa" * 32,
    "sut_digest": "bb" * 32,
    "beneficiary": "0x" + "ab" * 20,
    "amount": "1500000",
}
# Computed once from the Python implementation; contracts/test/claim-id.test.js
# pins the same value for the same payload.
SAMPLE_CLAIM_ID = "658b35c00f93a7be5708257b0888f6a3ca43c5978198155330a3973ef721349f"


class ClaimIdDerivationTests(unittest.TestCase):
    def test_sample_payload_matches_frozen_constant(self) -> None:
        self.assertEqual(claim_id_hex(SAMPLE_PAYLOAD), SAMPLE_CLAIM_ID)
        self.assertEqual(canonical_json(SAMPLE_PAYLOAD),
                         '{"amount":"1500000",'
                         '"beneficiary":"0xabababababababababababababababababababab",'
                         '"dedup_key":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
                         'aaaaaaaaaaaaaaaaaaaaaaaa",'
                         '"protocol":"rtm-claim-binding-v1",'
                         '"sut_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
                         'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}')

    def test_content_changes_change_the_id(self) -> None:
        base = claim_id_hex(SAMPLE_PAYLOAD)
        self.assertNotEqual(claim_id_hex({**SAMPLE_PAYLOAD, "amount": "1500001"}), base)
        self.assertNotEqual(claim_id_hex({**SAMPLE_PAYLOAD, "beneficiary": "0x" + "ac" * 20}), base)
        self.assertNotEqual(claim_id_hex({**SAMPLE_PAYLOAD, "dedup_key": "ab" * 32}), base)

    def test_invalid_payloads_are_refused(self) -> None:
        for payload in (
            {**SAMPLE_PAYLOAD, "beneficiary": "0xAB" + "ab" * 19},   # uppercase address
            {**SAMPLE_PAYLOAD, "amount": "0"},                        # zero amount
            {**SAMPLE_PAYLOAD, "amount": 1500000},                    # numeric amount
            {**SAMPLE_PAYLOAD, "protocol": "other-v1"},               # wrong protocol
            {key: value for key, value in SAMPLE_PAYLOAD.items() if key != "amount"},
            {**SAMPLE_PAYLOAD, "extra": "field"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    claim_id_hex(payload)

    def test_claim_request_record_shape(self) -> None:
        request = claim_request(
            dedup_key=SAMPLE_PAYLOAD["dedup_key"], sut_digest=SAMPLE_PAYLOAD["sut_digest"],
            sut_version="seed-v0", fixture_digest_value=fixture_digest({"task_id": "t"}),
            evidence_id="ev-0123456789ab", manifest_digest="cd" * 32,
            evidence_files={"ledger.sqlite": "sha256:" + "ef" * 32},
            beneficiary=SAMPLE_PAYLOAD["beneficiary"], amount=SAMPLE_PAYLOAD["amount"],
            created_round=1, protocol_version="arena-trusted-execution-v2")
        self.assertEqual(request["claim_id"], claim_id_hex(SAMPLE_PAYLOAD))
        self.assertEqual(request["status"], "pending")
        self.assertEqual(request["protocol"], CLAIM_PROTOCOL)
        for key in ("dedup_key", "sut_digest", "beneficiary", "amount"):
            self.assertEqual(request[key], SAMPLE_PAYLOAD[key])


if __name__ == "__main__":
    unittest.main()
