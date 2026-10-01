"""Attack-skill library integrity and deterministic selection."""
from __future__ import annotations

import pytest

from payassist_agent.attack_skills import ATTACK_SKILLS, SURFACES, LEVELS, select_skills


def test_library_has_unique_wellformed_skills():
    ids = [skill["id"] for skill in ATTACK_SKILLS]
    assert len(ids) == len(set(ids)) and len(ids) >= 10
    for skill in ATTACK_SKILLS:
        assert set(skill) == {"id", "name", "mechanism", "craft", "example", "surfaces", "levels"}
        assert skill["surfaces"] and set(skill["surfaces"]) <= set(SURFACES)
        assert set(skill["levels"]) <= set(LEVELS)
        for key in ("id", "name", "mechanism", "craft", "example"):
            assert isinstance(skill[key], str) and 0 < len(skill[key]) <= 2000


def test_both_surfaces_have_substantial_coverage():
    for surface in SURFACES:
        available = [skill for skill in ATTACK_SKILLS if surface in skill["surfaces"]]
        assert len(available) >= 5


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("level", LEVELS)
def test_selection_matches_surface_and_level_and_is_deterministic(surface, level):
    first = select_skills("r1-a01", surface=surface, level=level)
    second = select_skills("r1-a01", surface=surface, level=level)
    assert first == second and 0 < len(first) <= 5
    for skill in first:
        assert surface in skill["surfaces"] and level in skill["levels"]


def test_selection_rotates_across_generation_ids():
    picks = {tuple(skill["id"] for skill in select_skills(f"r1-a{i:02d}", surface="dialogue", level="L0"))
             for i in range(12)}
    assert len(picks) > 1, "skill rotation should differ across generations"


def test_selection_order_derives_from_a_process_independent_digest():
    import hashlib
    generation_id, surface, level = "stable-id", "tool_return", "L1"
    eligible = [skill for skill in ATTACK_SKILLS
                if surface in skill["surfaces"] and level in skill["levels"]]
    expected = sorted(eligible, key=lambda skill: hashlib.sha256(
        f"{generation_id}:{skill['id']}".encode("utf-8")).hexdigest())[:5]
    assert [skill["id"] for skill in select_skills(generation_id, surface=surface, level=level)] \
        == [skill["id"] for skill in expected]


@pytest.mark.parametrize("surface,level", [("web", "L0"), ("dialogue", "L9"), ("dialogue", "l0")])
def test_unknown_surface_or_level_is_rejected(surface, level):
    with pytest.raises(ValueError):
        select_skills("id", surface=surface, level=level)


@pytest.mark.parametrize("limit", [0, -1, 99])
def test_limit_out_of_bounds_is_rejected(limit):
    with pytest.raises(ValueError):
        select_skills("id", surface="dialogue", level="L0", limit=limit)


def test_selected_skills_are_copies_not_library_aliases():
    picked = select_skills("r1-a01", surface="dialogue", level="L0")
    picked[0]["name"] = "tampered"
    assert all(skill["name"] != "tampered" for skill in ATTACK_SKILLS)
