"""Engineering delivery recovers model output faults without executing fragments."""
import pytest

from payassist_agent.defense import hardened_package
from payassist_agent.expanded_suite import evaluate_expanded, scenario_for_case, suite_cases
from payassist_agent.model_client import ModelError
from payassist_agent.campaign_budget import BudgetedSUT
from payassist_agent.runtime import PaymentAgent


class TruncatedClient:
    def complete(self, messages, tools, *, timeout):
        raise ModelError("model output truncated", kind="agent_protocol")


def test_truncation_uses_generic_business_runtime_and_preserves_a_recovery_receipt():
    case = next(case for case in suite_cases("acceptance") if case["id"] == "ACC-N08")
    agent = PaymentAgent(scenario_for_case(case), TruncatedClient(), defense_package=hardened_package())
    for turn in case["turns"]:
        result = agent.turn(turn["content"], channel=turn["channel"],
                            claimed_sender=turn.get("claimed_sender", ""),
                            requests_execution=turn.get("requests_execution", False))
        assert result["error"] is None
    snapshot = agent.snapshot()
    assert len(snapshot["protocol_recoveries"]) == len(case["turns"])
    assert all(event["actor"] == "agent_runtime" for event in snapshot["events"])
    assert len(snapshot["payments"]) == 1
    assert evaluate_expanded(case, snapshot)["combined_pass"]


@pytest.mark.parametrize("package", [hardened_package() | {"runtime": {
    **hardened_package()["runtime"], "max_protocol_repairs": 0}}, None])
def test_recovery_is_explicit_and_cannot_bypass_zero_repair_budget(package):
    case = suite_cases("development")[0]
    agent = PaymentAgent(scenario_for_case(case), TruncatedClient(), defense_package=package)
    assert agent.turn(case["turns"][0]["content"])["error"]["kind"] == "agent_protocol"
    assert not agent.snapshot()["events"]


def test_infrastructure_failure_remains_a_failure_even_with_complete_workflow():
    class OfflineClient:
        def complete(self, messages, tools, *, timeout):
            raise ModelError("model transport failed")
    case = suite_cases("development")[0]
    agent = PaymentAgent(scenario_for_case(case), OfflineClient(), defense_package=hardened_package())
    assert agent.turn(case["turns"][0]["content"])["error"]["kind"] == "infrastructure"
    assert not agent.snapshot()["events"]


def test_recovered_truncation_keeps_dispatch_and_actual_token_cost(tmp_path):
    class MeteredTruncatedClient:
        def complete(self, messages, tools, *, timeout):
            raise ModelError("model output truncated", kind="agent_protocol", model="4B",
                             usage={"prompt_tokens": 210, "completion_tokens": 1200, "total_tokens": 1410})
    budget = BudgetedSUT(MeteredTruncatedClient(), tmp_path / "usage.json", 1, token_limit=100_000)
    case = suite_cases("development")[0]
    agent = PaymentAgent(scenario_for_case(case), budget, defense_package=hardened_package())
    assert agent.turn(case["turns"][0]["content"])["error"] is None
    call = agent.snapshot()["model_calls"][0]
    assert call["status"] == "agent_protocol" and call["usage"]["total_tokens"] == 1410
    assert budget.usage["calls"] == 1
    assert budget.usage["accounted_tokens"] == 1410
    assert budget.usage["completion_tokens"] == 1200
