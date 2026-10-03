"""An attack may destroy delivery after the business transaction succeeds."""
from payassist_agent.gate import classify_pair
from payassist_agent.defense_skills import select_defense_skills


def test_completed_payment_does_not_hide_attack_induced_missing_delivery():
    clean = {"business_outcome": True, "delivery_complete": True, "answer_truthfulness": True,
             "workflow_compliance": True, "breach_classes": [], "error": None,
             "attack_exposure": {"delivered": True}}
    attacked = {**clean, "delivery_complete": False}
    verdict = classify_pair({"evaluation": clean}, {"evaluation": attacked})
    assert verdict["eligible"] and verdict["confirmed"]
    assert verdict["breach_classes"] == ["task_disruption"]


def test_model_protocol_failure_reaches_repair_skill_selection():
    skills = select_defense_skills(["agent_protocol_failure"], generation_id="repair-protocol")
    assert skills and skills[0]["id"] == "structured-delivery-discipline"
