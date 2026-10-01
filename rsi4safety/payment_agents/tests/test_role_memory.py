"""Role-checkpoint (skill/lesson sedimentation) boundaries."""
from __future__ import annotations

import json

import pytest

from payassist_agent.role_memory import (
    MAX_ATTACK_SKILLS, MAX_DEFENSE_LESSONS, RoleMemoryStore,
    validate_defense_lesson, validate_sedimented_skill,
)

SKILL = {"id": "sed-poison-append", "name": "公告污染", "mechanism": "m", "craft": "c",
         "example": "e", "surfaces": ["tool_return"], "levels": ["L0", "L1"]}
LESSON = {"id": "def-trust-hierarchy", "mechanism": "结构化字段才是事实", "guidance": "保留正常查询"}


def test_skill_schema_is_strict():
    clean = validate_sedimented_skill(SKILL)
    assert clean == SKILL
    for mutation in ({"id": "Poison"}, {"id": "sed-" + "x" * 49}, {"surfaces": ["web"]},
                     {"levels": ["L2"]}, {"mechanism": "  "}, {"extra": 1}):
        with pytest.raises(ValueError):
            validate_sedimented_skill({**SKILL, **mutation})
    with pytest.raises(ValueError):
        validate_sedimented_skill({k: v for k, v in SKILL.items() if k != "craft"})


def test_lesson_schema_is_strict():
    assert validate_defense_lesson(LESSON) == LESSON
    with pytest.raises(ValueError):
        validate_defense_lesson({**LESSON, "id": "wrong-prefix"})
    with pytest.raises(ValueError):
        validate_defense_lesson({**LESSON, "rationale": "unknown field"})


def test_store_roundtrip_evicts_fifo_and_persists(tmp_path):
    store = RoleMemoryStore(tmp_path / "m.json")
    for index in range(MAX_ATTACK_SKILLS + 3):
        store.add_attack_skill({**SKILL, "id": f"sed-n{index:02d}"}, origin={"campaign": "c"})
    reloaded = RoleMemoryStore(tmp_path / "m.json")
    ids = [skill["id"] for skill in reloaded.snapshot()["attack_skills"]]
    assert len(ids) == MAX_ATTACK_SKILLS and ids[0] == "sed-n03"  # oldest evicted
    with pytest.raises(ValueError):
        reloaded.add_attack_skill({**SKILL, "id": ids[0]}, origin={"campaign": "c"})


def test_store_rejects_tampered_documents(tmp_path):
    path = tmp_path / "m.json"
    RoleMemoryStore(path).add_defense_lesson(LESSON, origin={"campaign": "c"})
    document = json.loads(path.read_text())
    document["defense_lessons"][0]["mechanism"] = ""  # hand-edited after the fact
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        RoleMemoryStore(path)


def test_from_document_deep_copies_and_revalidates(tmp_path):
    source = tmp_path / "donor.json"
    donor = RoleMemoryStore(source)
    donor.add_attack_skill(SKILL, origin={"campaign": "first", "source_id": "f1"})
    seeded = RoleMemoryStore.from_document(tmp_path / "seed.json", json.loads(source.read_text()))
    seeded.add_attack_skill({**SKILL, "id": "sed-second"}, origin={"campaign": "second"})
    assert [s["id"] for s in RoleMemoryStore(source).attack_skills()] == ["sed-poison-append"]
    document = json.loads(source.read_text())
    document["attack_skills"][0]["surfaces"] = ["web"]
    with pytest.raises(ValueError):
        RoleMemoryStore.from_document(tmp_path / "bad.json", document)


def test_limit_accessors_are_bounded(tmp_path):
    store = RoleMemoryStore(tmp_path / "m.json")
    for index in range(MAX_DEFENSE_LESSONS):
        store.add_defense_lesson({**LESSON, "id": f"def-l{index:02d}"}, origin={"campaign": "c"})
    assert len(store.defense_lessons(limit=6)) == 6
    assert store.defense_lessons(limit=6)[0]["id"] == f"def-l{MAX_DEFENSE_LESSONS - 6:02d}"
    with pytest.raises(ValueError):
        store.defense_lessons(limit=0)
    with pytest.raises(ValueError):
        store.attack_skills(limit=99)
