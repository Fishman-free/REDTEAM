"""Offline tests for the pilot's binding, hardware and compose checks.

These tests use synthetic quotes. They prove the verifier fails closed and the
binding math is consistent; they do not prove TDX hardware. The hardware proof
only comes from running verify_pilot.py against a real CVM.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import verify_pilot  # noqa: E402
from binding import binding_hash, signature_text  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402

DOMAIN = "RTM TEE pilot v1"


def make_attestation(nonce: str | None = None):
    signer = Account.create()
    wallet = Account.create()
    nonce = nonce or secrets.token_hex(32)
    digest = binding_hash(nonce, signer.address, wallet.address)
    signature = Account.sign_message(
        encode_defunct(text=signature_text(nonce, signer.address, wallet.address, digest)),
        private_key=signer.key,
    ).signature.to_0x_hex()
    return {
        "binding": {
            "domain": DOMAIN,
            "nonce": nonce,
            "signer": signer.address,
            "wallet": wallet.address,
        },
        "bindingHash": "0x" + digest,
        "signature": signature,
        "signer": signer.address,
        "wallet": wallet.address,
        "report_data": nonce + digest,
        "quote": "00" * 64,
        "event_log": "[]",
    }, nonce


def info_and_events():
    app_compose = json.dumps({"services": {"tee-pilot": {"image": "pilot@sha256:aa"}}})
    compose_hash = hashlib.sha256(app_compose.encode()).hexdigest()
    info = {
        "app_id": "app_test",
        "instance_id": "instance_test",
        "tcb_info": {"app_compose": app_compose},
    }
    events = [{"event": "compose-hash", "event_payload": compose_hash}]
    return info, json.dumps(events), compose_hash


class BindingTests(unittest.TestCase):
    def test_valid_binding_passes(self):
        attestation, nonce = make_attestation()
        result = verify_pilot.check_binding(attestation, nonce)
        self.assertEqual(result["nonce"], nonce)
        self.assertEqual(result["reportData"], nonce + result["bindingHash"][2:])

    def test_wrong_nonce_fails(self):
        attestation, _ = make_attestation()
        with self.assertRaises(verify_pilot.VerificationError):
            verify_pilot.check_binding(attestation, secrets.token_hex(32))

    def test_replaced_wallet_fails(self):
        attestation, nonce = make_attestation()
        attestation["binding"]["wallet"] = Account.create().address
        with self.assertRaises(verify_pilot.VerificationError):
            verify_pilot.check_binding(attestation, nonce)

    def test_replaced_report_data_fails(self):
        attestation, nonce = make_attestation()
        attestation["report_data"] = secrets.token_hex(64)
        with self.assertRaises(verify_pilot.VerificationError):
            verify_pilot.check_binding(attestation, nonce)

    def test_replaced_signature_fails(self):
        attestation, nonce = make_attestation()
        other = Account.create()
        attestation["signature"] = Account.sign_message(
            encode_defunct(text="not the binding"), private_key=other.key
        ).signature.to_0x_hex()
        with self.assertRaises(verify_pilot.VerificationError):
            verify_pilot.check_binding(attestation, nonce)


class HardwareTests(unittest.TestCase):
    def test_verified_quote_with_matching_report_data_passes(self):
        report = "ab" * 64
        post = mock.Mock(
            return_value={
                "quote": {
                    "verified": True,
                    "body": {"report_data": report, "tee_tcb_svn": "0601"},
                }
            }
        )
        result = verify_pilot.check_hardware("00" * 64, report, post=post)
        self.assertTrue(result["verified"])

    def test_rejected_quote_fails(self):
        post = mock.Mock(return_value={"quote": {"verified": False, "body": {}}})
        with self.assertRaises(verify_pilot.VerificationError):
            verify_pilot.check_hardware("00" * 64, "ab" * 64, post=post)

    def test_report_data_mismatch_fails(self):
        post = mock.Mock(
            return_value={
                "quote": {"verified": True, "body": {"report_data": "cd" * 64}}
            }
        )
        with self.assertRaises(verify_pilot.VerificationError):
            verify_pilot.check_hardware("00" * 64, "ab" * 64, post=post)

    def test_missing_body_fails_closed(self):
        post = mock.Mock(return_value={"quote": {"verified": True}})
        with self.assertRaises(verify_pilot.VerificationError):
            verify_pilot.check_hardware("00" * 64, "ab" * 64, post=post)


class ComposeTests(unittest.TestCase):
    def test_compose_hash_matches_event_log(self):
        info, events, compose_hash = info_and_events()
        result = verify_pilot.check_compose(info, events)
        self.assertEqual(result["composeHash"], compose_hash)

    def test_wrong_compose_fails(self):
        info, events, _ = info_and_events()
        info["tcb_info"]["app_compose"] = "{}"
        with self.assertRaises(verify_pilot.VerificationError):
            verify_pilot.check_compose(info, events)

    def test_missing_event_fails(self):
        info, _, _ = info_and_events()
        with self.assertRaises(verify_pilot.VerificationError):
            verify_pilot.check_compose(info, "[]")

    def test_expected_hash_mismatch_fails(self):
        info, events, _ = info_and_events()
        with self.assertRaises(verify_pilot.VerificationError):
            verify_pilot.check_compose(info, events, expected_hash="ff" * 32)


class EndToEndWiringTests(unittest.TestCase):
    def test_verify_wires_all_checks(self):
        info, events, _ = info_and_events()

        def fake_http(url, payload=None):
            if "/attestation?" in url:
                from urllib.parse import parse_qs, urlparse

                nonce = parse_qs(urlparse(url).query)["nonce"][0]
                attestation, _ = make_attestation(nonce)
                attestation["event_log"] = events
                return attestation
            if "/info" in url:
                return info
            raise AssertionError(url)

        def fake_hardware(quote, report_data, **kwargs):
            return {"verified": True, "reportData": report_data}

        with mock.patch.object(verify_pilot, "http_json", side_effect=fake_http), \
             mock.patch.object(verify_pilot, "check_hardware", side_effect=fake_hardware):
            result = verify_pilot.verify("https://cvm.example")
        self.assertTrue(result["ok"])
        self.assertEqual(result["compose"]["composeHash"], hashlib.sha256(
            info["tcb_info"]["app_compose"].encode()
        ).hexdigest())


if __name__ == "__main__":
    unittest.main()
