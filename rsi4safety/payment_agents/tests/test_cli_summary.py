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


def test_expanded_summary_keeps_business_delivery_and_protocol_separate():
    item = run('expanded', passed=False)
    item['evaluation'] = {'combined_pass': False, 'business_outcome': True, 'delivery_complete': False,
                         'answer_truthfulness': True, 'workflow_compliance': True,
                         'strict_legacy': {'unsafe_attempts': [], 'actual_violations': []},
                         'agent_protocol_errors': ['invalid_finish'], 'error': None}
    summary = summarize([item])['all']
    assert summary['task_completed'] == 1 and summary['delivery_complete'] == 0
    assert summary['agent_protocol_errors'] == 1 and summary['errors'] == 0


def test_cli_list_uses_expanded_transfer_fixtures(capsys):
    import json
    from payassist_agent.cli import main
    main(['list', '--split', 'transfer'])
    result = json.loads(capsys.readouterr().out)
    assert result['split'] == 'transfer'
    assert len(result['cases']) == 8 and len(result['attack_seeds']) == 32
    assert all(c['id'].startswith('TRN-') for c in result['cases'])


def test_defense_example_writes_control_without_loading_model(tmp_path, monkeypatch):
    import json
    from payassist_agent import cli
    monkeypatch.setattr(cli.ModelConfig, 'from_env', lambda **kwargs: (_ for _ in ()).throw(AssertionError('model load')))
    output = tmp_path / 'control.json'
    cli.main(['defense-example', '--output', str(output)])
    package = json.loads(output.read_text())
    assert package['runtime']['complete_workflow'] and package['runtime']['project_tool_data']


def test_cli_bench_applies_contexts_and_labels_seed_evidence(tmp_path, monkeypatch):
    import json
    import pytest
    from payassist_agent import cli
    from payassist_agent.model_client import ModelConfig
    seed = next(c for c in cli.attack_targets('transfer') if c['surface'] == 'document')
    seen = []

    class Agent:
        def __init__(self, scenario, client, **kwargs):
            self.scenario = scenario
            seen.append(('package', kwargs['defense_package']))
        def add_tool_override(self, item):
            seen.append(('override', item))
        def add_context_input(self, item):
            seen.append(('context', item))
        def turn(self, content, **kwargs):
            seen.append(('turn', kwargs))
            return {'error': None}
        def snapshot(self):
            return {'model_calls': []}

    monkeypatch.setattr(cli.ModelConfig, 'from_env', lambda **kwargs: ModelConfig())
    monkeypatch.setattr(cli, 'OpenAICompatibleClient', lambda config: object())
    monkeypatch.setattr(cli, 'PaymentAgent', Agent)
    monkeypatch.setattr(cli, 'evaluate_expanded', lambda case, snapshot: {
        'business_outcome': True, 'delivery_complete': True, 'answer_truthfulness': True,
        'workflow_compliance': True, 'combined_pass': True, 'error': None, 'strict_legacy': {}})
    output = tmp_path / 'bench.json'
    with pytest.raises(SystemExit) as exc:
        cli.main(['bench', '--split', 'transfer', '--kind', 'attack', '--case', seed['id'], '--output', str(output)])
    assert exc.value.code == 0
    report = json.loads(output.read_text())
    assert report['schema_version'] == 'payassist.benchmark.v2'
    assert 'not an independently confirmed finding' in report['evidence_kind']
    assert [item for kind, item in seen if kind == 'context'] == seed['context_inputs']
    assert report['results'][0]['case_id'] == seed['id']
