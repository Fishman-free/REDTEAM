"""Benchmark denominators include failures and incomplete repetitions."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from payassist_agent.cli import summarize


def run(case_id, *, passed=True, error=None, unsafe=False, actual=False, refusal=False):
    return {"case_id": case_id, "level": "L1", "kind": "normal", "surface": "none", "persona": "personal",
            "evaluation": {"combined_pass": passed, "task_completed": passed,
                           "unsafe_attempts": [{"event_id": "ev-1"}] if unsafe else [],
                           "actual_violations": [{"payment_id": "pay-1"}] if actual else [],
                           "explicit_over_refusal": refusal, "safe_but_incomplete": not passed and not unsafe and error is None,
                           "error": error},
            "snapshot": {"model_calls": [{"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}]}}


def test_one_success_of_two_expected_runs_is_not_all_repetitions_passed():
    summary = summarize([run("case-a")], expected_repetitions=2)
    assert summary["all"]["count"] == summary["all"]["passed"] == 1
    assert summary["unique_cases"] == 1
    assert summary["all_repetitions_passed"] == 0


def test_only_cases_with_all_expected_successes_are_counted():
    results = [run("case-a"), run("case-a"), run("case-b"), run("case-c"), run("case-c", passed=False)]
    summary = summarize(results, expected_repetitions=2)
    assert summary["unique_cases"] == 3
    assert summary["all_repetitions_passed"] == 1
    assert summary["all"]["count"] == 5 and summary["all"]["passed"] == 4


def test_more_than_expected_runs_do_not_hide_duplicate_execution():
    summary = summarize([run("case-a"), run("case-a"), run("case-a")], expected_repetitions=2)
    assert summary["all_repetitions_passed"] == 0


def test_errors_stay_in_denominator_and_prevent_case_all_pass():
    summary = summarize([run("case-a"), run("case-a", passed=False, error="model timeout")], expected_repetitions=2)
    assert summary["all"]["count"] == 2 and summary["all"]["errors"] == 1
    assert summary["by_kind"]["normal"]["count"] == 2
    assert summary["all_repetitions_passed"] == 0


def test_default_one_repetition_and_empty_run_set():
    assert summarize([run("case-a")])["all_repetitions_passed"] == 1
    empty = summarize([])
    assert empty["all_repetitions_passed"] == empty["unique_cases"] == empty["all"]["count"] == 0


def test_safety_business_refusal_and_usage_metrics_remain_separate():
    summary = summarize([run("safe-pass"), run("blocked-unsafe", passed=False, unsafe=True),
                         run("actual-unsafe", passed=False, unsafe=True, actual=True),
                         run("over-refusal", passed=False, refusal=True)])
    assert summary["all"]["passed"] == summary["all"]["task_completed"] == 1
    assert summary["all"]["unsafe_attempt_cases"] == 2
    assert summary["all"]["actual_violation_cases"] == summary["all"]["explicit_over_refusal"] == 1
    assert summary["model_calls"] == 4
    assert summary["usage"] == {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60}
