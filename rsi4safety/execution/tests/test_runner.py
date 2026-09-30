import tempfile
import unittest
from pathlib import Path

from rsi4safety.runner import ContinuousSafetyRunner
from rsi4safety.core import PaymentAgent
from rsi4safety.domain import RunResult


class EndToEndRunnerTests(unittest.TestCase):
    def test_candidate_failing_fresh_retest_cannot_replace_active_version(self) -> None:
        calls = {}

        class FlakyAgent(PaymentAgent):
            def run(self, environment):
                key = self.policy.policy_id
                calls[key] = calls.get(key, 0) + 1
                # Five built-in cases plus the newly stored discovery case.
                if key.startswith("candidate-") and calls[key] > 6:
                    return RunResult(environment.task.task_id, key, (), "refused on fresh retest")
                return super().run(environment)

        with tempfile.TemporaryDirectory() as directory:
            runner = ContinuousSafetyRunner(Path(directory), agent_factory=FlakyAgent)
            result = runner.run_round()
            self.assertFalse(result.retest_record.utility_success)
            self.assertEqual(result.active_version, "payment-agent-v0")
            self.assertIsNone(runner.summary(result)["promoted_version"])
            self.assertEqual(runner.archive.load_active().version_id, "payment-agent-v0")

    def test_offline_round_attacks_scores_repairs_and_retests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = ContinuousSafetyRunner(Path(directory))
            result = runner.run_round()
            summary = runner.summary(result)
            self.assertTrue(summary["attack"]["actual_unauthorized"])
            self.assertFalse(summary["retest"]["actual_unauthorized"])
            self.assertTrue(summary["retest"]["utility_success"])
            self.assertIsNotNone(summary["promoted_version"])
            self.assertLess(summary["before_scores"]["no_unauthorized_commit"], 100)
            self.assertTrue(all(score == 100 for score in summary["after_scores"].values()))
            self.assertTrue((Path(directory) / "rounds" / f"{result.round_id}.json").exists())
            self.assertTrue((Path(directory) / "verified-experiences.jsonl").exists())
            restarted = ContinuousSafetyRunner(Path(directory))
            self.assertEqual(restarted.initial_manifest().version_id, summary["promoted_version"])
            second = restarted.run_round()
            self.assertFalse(second.attack_record.actual_unauthorized)
            self.assertIsNone(second.improvement)
            self.assertEqual(second.active_version, result.active_version)
            self.assertEqual(len(restarted.experiences.regression_scenarios()), 1)


if __name__ == "__main__":
    unittest.main()
