import json
import os
import unittest
from unittest.mock import patch

from redteam.agents import decide_with_meta
from redteam.llm import request_proposal


class TestLLMAdapter(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()

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

    def test_model_cannot_authorize_hardened_payment(self):
        os.environ.update(REDTEAM_LLM_BASE_URL="http://local", REDTEAM_LLM_API_KEY="test", REDTEAM_LLM_MODEL="demo")
        def transport(*args):
            return json.dumps({"choices": [{"message": {"content": "PAY INV-100 TO participant AMOUNT 999"}}]}).encode()
        proposal, reason, meta = decide_with_meta("hardened", "PAY INV-100 TO participant AMOUNT 999", set(), adapter=transport)
        self.assertIsNone(proposal)
        self.assertIn("recipient or amount", reason)
        self.assertFalse(meta["fallback"])


if __name__ == "__main__":
    unittest.main()
