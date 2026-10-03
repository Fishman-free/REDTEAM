"""A bounded retry must receive the reason its prior package was rejected."""
from unittest.mock import Mock

from payassist_agent.campaign import CampaignConfig, LiveCampaign
from payassist_agent.expanded_suite import attack_targets
from payassist_agent.live_roles import RoleOutputError


def test_invalid_role_output_is_preserved_and_becomes_next_attempt_feedback(tmp_path, monkeypatch):
    roles = Mock()
    roles.repair.side_effect = [RoleOutputError("unknown runtime rule"), RoleOutputError("training identifier")]
    runner = LiveCampaign(tmp_path, CampaignConfig(rounds=1, attacks_per_round=1, max_candidates=2),
                          sut=Mock(), roles=roles)
    case = attack_targets("development")[0]
    runner.state["findings"] = [{"case": case}]
    failure = {"case_id": case["id"], "case": case, "repetition": 1,
               "evaluation": {"business_outcome": False, "breach_classes": ["task_disruption"]}}
    monkeypatch.setattr(runner, "run_suite", lambda *args, **kwargs: [failure])
    runner.repair_round(1, runner.initial, {})
    assert roles.repair.call_count == 2
    second = roles.repair.call_args_list[1].kwargs["failures"]
    assert second[-1]["output_validation"]["message"] == "unknown runtime rule"
    assert len(runner.state["role_errors"]) == 2
    assert (tmp_path / "role_outputs" / "repair-r1-c1.json").is_file()
    assert not list((tmp_path / "trials").glob("*"))
