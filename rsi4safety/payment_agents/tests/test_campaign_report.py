"""Reports must preserve gate provenance and measured model identity."""
import json

from payassist_agent.campaign_report import build_report


def test_report_names_measured_model_and_reports_legacy_early_abort(tmp_path):
    (tmp_path / 'gates').mkdir()
    (tmp_path / 'manifest.json').write_text(json.dumps({'payment_model': 'fixture-9B', 'role_model': 'fixture-role', 'config': {}}))
    (tmp_path / 'report.json').write_text(json.dumps({'rounds': [], 'findings': [], 'summary': {}, 'usage': {}}))
    (tmp_path / 'gates' / 'early.json').write_text(json.dumps({'candidate': 'early',
        'gate': {'passed': False, 'aborted_early': True, 'regressions': [], 'reasons': ['evaluation_coverage_mismatch']},
        'early_abort': {'case_id': 'DEV-N08', 'dimensions': ['answer_truthfulness']}}))
    (tmp_path / 'gates' / 'promoted.json').write_text(json.dumps({'candidate': 'promoted',
        'gate': {'passed': True, 'repaired': ['attack'], 'regressions': [], 'reasons': []}}))
    report = build_report(tmp_path, level='L1')
    assert 'SUT=fixture-9B' in report and 'fixture-role' in report
    assert 'DEV-N08: answer_truthfulness' in report and '剩余用例未评估' in report
    assert '| promoted | 是 |' in report
    assert '双重复现全部修复' not in report
