"""Repair-skill library integrity, relevance-first selection and wiring."""
from __future__ import annotations

import pytest

from payassist_agent.defense_skills import (
    BREACH_CLASSES, DEFENSE_SKILLS, select_defense_skills, validate_defense_skill,
)


def test_library_is_wellformed_with_unique_ids():
    ids = [skill["id"] for skill in DEFENSE_SKILLS]
    assert len(ids) == len(set(ids)) and len(ids) >= 8
    for skill in DEFENSE_SKILLS:
        assert validate_defense_skill(skill) == {**skill, "addresses": list(skill["addresses"])}
        assert skill["addresses"] and set(skill["addresses"]) <= set(BREACH_CLASSES)


def test_every_observed_family_has_at_least_one_countermeasure():
    for family in ("false_business_statement", "repeat_payment_attempt",
                   "unrequested_payment_attempt", "unauthorized_terms_attempt",
                   "wrong_recipient_attempt", "workflow_violation", "task_disruption"):
        assert any(family in skill["addresses"] for skill in DEFENSE_SKILLS), family


def test_selection_is_relevance_first_and_deterministic():
    observed = ["repeat_payment_attempt", "unrequested_payment_attempt", "task_disruption"]
    first = select_defense_skills(observed, generation_id="r1-c1")
    again = select_defense_skills(observed, generation_id="r1-c1")
    assert first == again and first
    # terminal-state-verification covers both payment classes and must lead.
    assert first[0]["id"] == "terminal-state-verification"
    for skill in first:
        assert set(skill["addresses"]) & set(observed)


def test_selection_rotates_on_ties_across_candidates():
    # Two skills cover false_business_statement equally; order must rotate.
    picks = {tuple(s["id"] for s in select_defense_skills(
        ["false_business_statement"], generation_id=f"r1-c{i}")) for i in range(1, 5)}
    assert len(picks) == 2
    assert all(set(ids) == {"fact-source-hierarchy", "structured-delivery-discipline"} for ids in picks)
    # Strictly higher coverage always leads regardless of rotation.
    for i in range(1, 5):
        ranked = select_defense_skills(["repeat_payment_attempt", "unrequested_payment_attempt"],
                                       generation_id=f"r2-c{i}")
        assert ranked[0]["id"] == "terminal-state-verification"


def test_unknown_or_empty_classes_and_bounds():
    # Observed classes without a curated countermeasure match nothing and fall
    # back to the core mechanisms; they must never kill a live campaign.
    core = select_defense_skills(["time_travel_attempt"], generation_id="g")
    assert {skill["id"] for skill in core} == {"fact-source-hierarchy", "contract-verbatim-ids"}
    with pytest.raises(ValueError):
        select_defense_skills(["task_disruption"], generation_id="g", limit=0)
    empty = select_defense_skills([], generation_id="g")
    assert {skill["id"] for skill in empty} == {"fact-source-hierarchy", "contract-verbatim-ids"}


def test_reference_reading_failure_selects_the_fact_source_hierarchy():
    # Regression for the 2026-10-05 L0 crash: a confirmed finding carrying the
    # evaluator's required-reading class must select relevant guidance instead
    # of raising out of the repair round.
    observed = ["false_reference_statement", "unsafe_payment_attempt"]
    skills = select_defense_skills(observed, generation_id="repair-r1-c1")
    assert skills and "fact-source-hierarchy" in {skill["id"] for skill in skills}
    mixed = select_defense_skills(["false_reference_statement", "time_travel_attempt"],
                                  generation_id="repair-r1-c1")
    assert [skill["id"] for skill in mixed] == ["fact-source-hierarchy"]


def test_skill_schema_is_strict():
    base = DEFENSE_SKILLS[0]
    for mutation in ({"addresses": ["nope"]}, {"rule": " "}, {"extra": 1}):
        with pytest.raises(ValueError):
            validate_defense_skill({**base, **mutation})
    with pytest.raises(ValueError):
        validate_defense_skill({k: v for k, v in base.items() if k != "rule"})


def test_campaign_collects_breach_classes_from_failures(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from payassist_agent import campaign
    from payassist_agent.model_client import ModelConfig
    monkeypatch.setattr(campaign.ModelConfig, "from_env", lambda: ModelConfig())
    runner = campaign.LiveCampaign(tmp_path, campaign.CampaignConfig(
        rounds=1, attacks_per_round=1, repetitions=1, max_candidates=1), sut=Mock(), roles=Mock())
    failures = [{"case_id": "a", "evaluation": {"breach_classes": ["repeat_payment_attempt"]}},
                {"case_id": "b", "evaluation": {"breach_classes": ["task_disruption",
                                                                    "repeat_payment_attempt"]}},
                {"case_id": "c", "evaluation": {"breach_classes": []}}]
    assert runner.observed_breach_classes(failures) == ["repeat_payment_attempt", "task_disruption"]
    skills = select_defense_skills(runner.observed_breach_classes(failures), generation_id="r1-c1")
    assert skills and {"attack-inoculation-continuation", "terminal-state-verification",
                       "urgency-immunity"} >= {skills[0]["id"]}
