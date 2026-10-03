"""RTM claim binding primitives (docs/EVIDENCE_REWARD_PROTOCOL.md, frozen v1).

The Arena side derives a content-bound ``claim_id`` for every validated
finding; the contracts side derives the identical id from the same payload
(contracts/scripts/claim-id.js). Both sides are pinned to the same sample
constant by their unit tests. Only string fields are allowed in the payload
so Python and JS canonical JSON serialization can never disagree.
"""
from __future__ import annotations

import hashlib
import json
import re

CLAIM_PROTOCOL = "rtm-claim-binding-v1"
_REQUIRED_FIELDS = ("amount", "beneficiary", "dedup_key", "protocol", "sut_digest")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_DECIMAL = re.compile(r"^[0-9]+$")


def canonical_json(payload: dict[str, str]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def claim_id(payload: dict[str, str]) -> bytes:
    """32-byte content-bound claim id; invalid payloads are refused, not coerced."""
    if not isinstance(payload, dict) or any(not isinstance(value, str) for value in payload.values()):
        raise ValueError("claim payload must be a flat mapping of strings")
    missing = [key for key in _REQUIRED_FIELDS if key not in payload]
    extra = [key for key in payload if key not in _REQUIRED_FIELDS]
    if missing or extra:
        raise ValueError(f"claim payload fields mismatch: missing={missing} extra={extra}")
    if payload["protocol"] != CLAIM_PROTOCOL:
        raise ValueError(f"protocol must be {CLAIM_PROTOCOL}")
    if not _HEX64.match(payload["dedup_key"]) or not _HEX64.match(payload["sut_digest"]):
        raise ValueError("dedup_key and sut_digest must be lowercase 64-hex digests")
    if not _ADDRESS.match(payload["beneficiary"]):
        raise ValueError("beneficiary must be a lowercase 0x address")
    if not _DECIMAL.match(payload["amount"]) or int(payload["amount"]) <= 0:
        raise ValueError("amount must be a positive decimal string")
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).digest()


def claim_id_hex(payload: dict[str, str]) -> str:
    return claim_id(payload).hex()


def fixture_digest(task_fixture_brief: dict) -> str:
    """Task/authorization summary digest for the binding record (control.digest shape)."""
    encoded = json.dumps(task_fixture_brief, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def claim_request(*, dedup_key: str, sut_digest: str, sut_version: str,
                  fixture_digest_value: str, evidence_id: str, manifest_digest: str,
                  evidence_files: dict[str, str], beneficiary: str, amount: str,
                  created_round: int, protocol_version: str) -> dict:
    """Build a pending claim request record per the frozen schema."""
    payload = {"protocol": CLAIM_PROTOCOL, "dedup_key": dedup_key,
               "sut_digest": sut_digest, "beneficiary": beneficiary, "amount": amount}
    return {
        "schema_version": 1,
        "protocol": CLAIM_PROTOCOL,
        "claim_id": claim_id_hex(payload),
        "dedup_key": dedup_key,
        "fixture_digest": fixture_digest_value,
        "evidence_id": evidence_id,
        "manifest_digest": manifest_digest,
        "evidence_files": dict(evidence_files),
        "sut_version": sut_version,
        "sut_digest": sut_digest,
        "protocol_version": protocol_version,
        "beneficiary": beneficiary,
        "amount": amount,
        "created_round": created_round,
        "status": "pending",
        "history": [{"event": "registered"}],
    }
