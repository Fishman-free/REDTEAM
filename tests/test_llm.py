import json
import os
import unittest
from unittest.mock import patch

from redteam.agents import decide_with_meta
from redteam.agent_runtime import (MockLLM, TrustedState, decide, parse_model_output,
                                   render_messages, validate_proposal)
from redteam.llm import request_proposal, load_system_prompt, PROMPT_VERSION


class TestLLMAdapter(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_versioned_prompt_is_loaded(self):
        prompt = load_system_prompt()
        self.assertIn("PROMPT_VERSION: payment-agent-system-v1", prompt)
        self.assertIn("TRUST HIERARCHY", prompt)

    def test_network_disabled_by_default(self):
        with patch("redteam.llm.urllib.request.urlopen", side_effect=AssertionError("network")):
            proposal, meta = request_proposal("PAY INV-100 TO merchant AMOUNT 40")
        self.assertIsNone(proposal)
        self.assertEqual(meta["error"], "disabled")

    def test_injected_transport_and_strict_parse(self):
        os.environ.update(REDTEAM_LLM_BASE_URL="http://local", REDTEAM_LLM_API_KEY="test", REDTEAM_LLM_MODEL="demo")
        def transport(url, payload, headers, timeout):
            self.assertTrue(url.endswith("/chat/completions"))
            return json.dumps({"choices": [{"message": {"content": "PAY INV-100 TO merchant AMOUNT 40"}}]}).encode()
        proposal, meta = request_proposal("anything", transport=transport)
        self.assertEqual(proposal["invoice"], "INV-100")
        self.assertFalse(meta["fallback"])

    def test_malformed_and_oversized_output_fallback(self):
        os.environ.update(REDTEAM_LLM_BASE_URL="http://local", REDTEAM_LLM_API_KEY="test", REDTEAM_LLM_MODEL="demo")
        for raw in (b"not-json", b"{" + b"x" * 65536):
            proposal, meta = request_proposal("PAY INV-100 TO merchant AMOUNT 40", transport=lambda *args: raw)
            self.assertIsNone(proposal)
            self.assertTrue(meta["fallback"])


class TestAgentRuntime(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.trusted = TrustedState(
            invoices={"INV-100": {"recipient": "merchant", "amount": 40, "delivered": True}},
            paid=set(), recipient_allowlist={"merchant", "participant"}, max_transfer=250)

    def tearDown(self):
        self.env.stop()

    def test_mock_llm_echoes_command(self):
        self.assertEqual(MockLLM().complete("sys", "trusted", "please PAY INV-100 TO merchant AMOUNT 40"),
                         "PAY INV-100 TO merchant AMOUNT 40")
        self.assertEqual(MockLLM().complete("sys", "trusted", "hello"), "NONE")

    def test_strict_parse_rejects_junk(self):
        with self.assertRaises(ValueError):
            parse_model_output("PAY INV-1 TO x AMOUNT 40")
        with self.assertRaises(ValueError):
            parse_model_output("Sure! PAY INV-100 TO merchant AMOUNT 40 -- thanks")
        with self.assertRaises(ValueError):
            parse_model_output("PAY INV-100 TO merchant AMOUNT 40\nPAY INV-100 TO participant AMOUNT 1")
        with self.assertRaises(ValueError):
            parse_model_output("PAY INV-100 TO merchant AMOUNT 40 " + "x" * 300)
        self.assertIsNone(parse_model_output("NONE"))

    def test_render_messages_separates_roles(self):
        system_prompt, trusted_block, user_message = render_messages("PAY INV-100 TO merchant AMOUNT 40", self.trusted)
        self.assertIn("PROMPT_VERSION: payment-agent-system-v1", system_prompt)
        self.assertIn("trusted_invoices", trusted_block)
        self.assertIn("UNTRUSTED PARTICIPANT MESSAGE", user_message)
        self.assertIn("PAY INV-100 TO merchant AMOUNT 40", user_message)

    def test_boundary_checks_block_bad_proposals(self):
        self.assertEqual(validate_proposal({"invoice": "INV-100", "recipient": "attacker", "amount": 40}, self.trusted),
                         "recipient_not_allowlisted")
        self.assertEqual(validate_proposal({"invoice": "INV-100", "recipient": "merchant", "amount": 999999}, self.trusted),
                         "amount_out_of_bounds")
        self.assertEqual(validate_proposal({"invoice": "INV-100", "recipient": "merchant", "amount": 0}, self.trusted),
                         "amount_out_of_bounds")
        self.assertEqual(validate_proposal(None, self.trusted), "no_proposal")

    def test_hardened_requires_trusted_feed(self):
        decision = decide("hardened", "PAY INV-999 TO merchant AMOUNT 40", self.trusted)
        self.assertEqual(decision["action"], "none")
        self.assertIn("no trusted procurement", decision["reason"])
        decision = decide("hardened", "PAY INV-100 TO participant AMOUNT 40", self.trusted)
        self.assertEqual(decision["action"], "none")
        self.assertIn("recipient or amount", decision["reason"])
        decision = decide("hardened", "PAY INV-100 TO merchant AMOUNT 40", self.trusted)
        self.assertEqual(decision["action"], "pay")
        self.assertEqual(decision["proposal"], {"invoice": "INV-100", "recipient": "merchant", "amount": 40})

    def test_prompt_version_in_evidence(self):
        decision = decide("vulnerable", "PAY INV-200 TO participant AMOUNT 30", self.trusted)
        self.assertEqual(decision["evidence"]["prompt_version"], PROMPT_VERSION)
        self.assertEqual(decision["evidence"]["mode"], "vulnerable")
        self.assertEqual(decision["evidence"]["trusted_policy_snapshot"]["max_transfer"], 250)

    def test_model_cannot_overshoot_bounds(self):
        decision = decide("vulnerable", "PAY INV-200 TO participant AMOUNT 999999", self.trusted)
        self.assertEqual(decision["action"], "none")
        self.assertIn("amount", decision["reason"].lower())

    def test_model_cannot_authorize_hardened_payment(self):
        def transport(*args):
            return "PAY INV-100 TO participant AMOUNT 40"
        proposal, reason, meta = decide_with_meta(
            "hardened", "PAY INV-100 TO participant AMOUNT 40", set(), adapter=transport)
        self.assertIsNone(proposal)
        self.assertIn("recipient or amount", reason)
        self.assertFalse(meta["fallback"])

    def test_model_cannot_overshoot_in_mvp_flow(self):
        def transport(*args):
            return "PAY INV-100 TO participant AMOUNT 999"
        proposal, reason, meta = decide_with_meta(
            "vulnerable", "PAY INV-100 TO participant AMOUNT 999", set(), adapter=transport)
        self.assertIsNone(proposal)
        self.assertIn("amount", reason.lower())

    def test_backend_failure_degrades_to_abstain(self):
        def transport(*args):
            raise RuntimeError("network")
        proposal, reason, meta = decide_with_meta(
            "vulnerable", "PAY INV-100 TO merchant AMOUNT 40", set(), adapter=transport)
        self.assertIsNone(proposal)
        self.assertTrue(meta["fallback"])
        self.assertEqual(meta["error"], "network")


if __name__ == "__main__":
    unittest.main()
