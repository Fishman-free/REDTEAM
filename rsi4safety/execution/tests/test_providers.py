import os
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from rsi4safety.providers import BudgetExceeded, CallBudget, ModelCallError, OpenAICompatibleChatModel


def response(content='{"ok":true}'):
    return io.BytesIO(json.dumps({"model": "glm-5.3-flash", "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                 "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}).encode())


class ProviderTests(unittest.TestCase):
    def test_cache_hit_is_logged_and_does_not_consume_another_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = CallBudget(2, 10_000)
            model = OpenAICompatibleChatModel("glm-5.3-flash", api_key=os.environ.get("TEST_API_KEY", "test-not-real"), budget=budget,
                                             audit_log=root / "calls.jsonl", cache_dir=root / "cache", use_cache=True)
            with patch("rsi4safety.providers.request.build_opener") as factory:
                factory.return_value.open.return_value = response()
                self.assertEqual(model.complete("system", "task"), '{"ok":true}')
                self.assertEqual(model.complete("system", "task"), '{"ok":true}')
                self.assertEqual(factory.return_value.open.call_count, 1)
            self.assertEqual(budget.calls, 1)
            self.assertEqual(budget.reported_tokens, 15)
            raw = (root / "calls.jsonl").read_text()
            logs = [json.loads(line) for line in raw.splitlines()]
            self.assertEqual([entry["status"] for entry in logs], ["ok", "cache_hit"])
            self.assertEqual(logs[0]["request"]["messages"][1]["content"], "task")
            self.assertIn("response", logs[0])
            self.assertNotIn("test-private-secret", raw)
            self.assertNotIn("Authorization", raw)

    def test_fresh_evaluation_never_reads_an_existing_cache_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            model = OpenAICompatibleChatModel("glm-5.3-flash", api_key="secret", cache_dir=Path(directory), use_cache=False)
            with patch("rsi4safety.providers.request.build_opener") as factory:
                factory.return_value.open.side_effect = [response(), response()]
                model.complete("system", "task")
                model.complete("system", "task")
                self.assertEqual(factory.return_value.open.call_count, 2)

    def test_concurrent_reservations_cannot_exceed_call_limit(self):
        budget = CallBudget(3, 100_000)
        def reserve(_):
            try:
                budget.reserve(100, 100)
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            successes = list(pool.map(reserve, range(20)))
        self.assertEqual(sum(successes), 3)
        self.assertEqual(budget.calls, 3)

    def test_rate_limit_retries_are_counted_and_auth_failure_is_not_retried(self):
        budget = CallBudget(5, 30_000)
        model = OpenAICompatibleChatModel("glm-5.3-flash", api_key="secret", budget=budget)
        with patch("rsi4safety.providers.request.build_opener") as factory, patch("rsi4safety.providers.time.sleep"):
            factory.return_value.open.side_effect = [HTTPError("url", 429, "limited", {}, None), response()]
            model.complete("system", "task")
            self.assertEqual(budget.calls, 2)
            factory.return_value.open.side_effect = HTTPError("url", 401, "secret", {}, None)
            with self.assertRaises(ModelCallError) as caught:
                model.complete("system", "task")
            self.assertNotIn("secret", str(caught.exception))
            self.assertEqual(budget.calls, 3)


if __name__ == "__main__":
    unittest.main()
