"""Bounded, auditable cross-round checkpoints for the attacker and defender roles.

The attacker checkpoint is a sedimented skill library: confirmed findings are
distilled (by the glm-5.3 improver endpoint) into reusable techniques that re-
enter future attack generations.  The defender checkpoint is a lesson store
derived deterministically from promoted, gate-verified repairs.  Both stores
are capped (FIFO eviction), schema-validated on load, and every mutation is
recorded by the campaign hash chain by the caller.  Nothing here grants host
authority: skills are advisory text for role prompts only.
"""
from __future__ import annotations

import copy
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

SURFACES = ("dialogue", "tool_return")
LEVELS = ("L0", "L1")
MAX_ATTACK_SKILLS = 12
MAX_DEFENSE_LESSONS = 12
_TEXT_LIMIT = 2000


def _bounded_text(value: Any, name: str, limit: int = _TEXT_LIMIT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be nonempty text of at most {limit} characters")
    return value


def _sequence(value: Any, name: str, allowed: tuple) -> list:
    if not isinstance(value, list) or not value or len(value) > len(allowed):
        raise ValueError(f"{name} must be a nonempty subset of {list(allowed)}")
    for item in value:
        if item not in allowed:
            raise ValueError(f"{name} contains an unsupported value")
    return list(value)


def validate_sedimented_skill(raw: Any) -> dict:
    """Strict schema for a distilled attack technique (glm output or import)."""
    if not isinstance(raw, dict) or set(raw) != {"id", "name", "mechanism", "craft",
                                                 "example", "surfaces", "levels"}:
        raise ValueError("sedimented skill requires exactly the seven skill fields")
    if not re.fullmatch(r"sed-[a-z0-9-]{1,48}", raw["id"]):
        raise ValueError("sedimented skill id must be sed-<lowercase-token>")
    for key in ("id", "name", "mechanism", "craft", "example"):
        _bounded_text(raw[key], key)
    _sequence(raw["surfaces"], "surfaces", SURFACES)
    _sequence(raw["levels"], "levels", LEVELS)
    return copy.deepcopy(raw)


def validate_defense_lesson(raw: Any) -> dict:
    if not isinstance(raw, dict) or set(raw) != {"id", "mechanism", "guidance"}:
        raise ValueError("defense lesson requires exactly id, mechanism and guidance")
    if not re.fullmatch(r"def-[a-z0-9-]{1,48}", raw["id"]):
        raise ValueError("defense lesson id must be def-<lowercase-token>")
    for key in ("id", "mechanism", "guidance"):
        _bounded_text(raw[key], key)
    return copy.deepcopy(raw)


def _origin(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) - {"campaign", "source_id", "role_call_id", "note"}:
        raise ValueError("origin must carry campaign/source provenance only")
    for key, item in value.items():
        # Provenance hints may be absent (empty), never oversized or non-text.
        if not isinstance(item, str) or len(item) > 256:
            raise ValueError(f"origin.{key} must be bounded text")
    return copy.deepcopy(value)


class RoleMemoryStore:
    """FIFO-capped role checkpoints persisted as one JSON document."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        if self.path.is_file():
            document = json.loads(self.path.read_text(encoding="utf-8"))
            self._validate(document)
            self._document = document
        else:
            self._document = {"schema_version": "payassist.role-memory.v1",
                              "attack_skills": [], "defense_lessons": [], "ledger": []}

    @staticmethod
    def _validate(document: dict) -> None:
        if not isinstance(document, dict) or set(document) != {
                "schema_version", "attack_skills", "defense_lessons", "ledger"}:
            raise ValueError("role memory document has unknown or missing sections")
        if document["schema_version"] != "payassist.role-memory.v1":
            raise ValueError("unsupported role memory schema")
        seen = set()
        for skill in document["attack_skills"]:
            validate_sedimented_skill({k: skill[k] for k in (
                "id", "name", "mechanism", "craft", "example", "surfaces", "levels")})
            _origin(skill.get("origin", {}))
            if not isinstance(skill.get("created_at"), (int, float)):
                raise ValueError("sedimented skill requires a numeric created_at")
            if skill["id"] in seen:
                raise ValueError("duplicate sedimented skill id")
            seen.add(skill["id"])
        seen = set()
        for lesson in document["defense_lessons"]:
            validate_defense_lesson({k: lesson[k] for k in ("id", "mechanism", "guidance")})
            _origin(lesson.get("origin", {}))
            if not isinstance(lesson.get("created_at"), (int, float)):
                raise ValueError("defense lesson requires a numeric created_at")
            if lesson["id"] in seen:
                raise ValueError("duplicate defense lesson id")
            seen.add(lesson["id"])
        if not isinstance(document["ledger"], list) or len(document["ledger"]) > 256:
            raise ValueError("role memory ledger must be a bounded list")

    def _save(self) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._document, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def _append_ledger(self, action: str, entry_id: str, detail: str) -> None:
        self._document["ledger"].append({"action": action, "id": entry_id, "at": time.time(),
                                         "detail": detail[:400]})
        del self._document["ledger"][:-256]

    @classmethod
    def from_document(cls, path: Path, document: dict) -> "RoleMemoryStore":
        """Seed a fresh checkpoint from an already validated prior document."""
        store = cls.__new__(cls)
        store.path = Path(path)
        store._lock = threading.RLock()
        cls._validate(document)
        store._document = copy.deepcopy(document)
        store._save()
        return store

    def add_attack_skill(self, skill: dict, *, origin: dict) -> tuple[dict, list[dict]]:
        """Insert a validated skill; returns (stored, evicted) for audit."""
        clean = validate_sedimented_skill(skill)
        _origin(origin)
        with self._lock:
            if any(item["id"] == clean["id"] for item in self._document["attack_skills"]):
                raise ValueError("sedimented skill id already stored")
            stored = {**clean, "origin": copy.deepcopy(origin), "created_at": time.time()}
            self._document["attack_skills"].append(stored)
            evicted = self._document["attack_skills"][:-MAX_ATTACK_SKILLS]
            del self._document["attack_skills"][:-MAX_ATTACK_SKILLS]
            self._append_ledger("attack_skill_added", stored["id"],
                                f"origin={origin.get('source_id', '')} evicted={len(evicted)}")
            self._save()
            return copy.deepcopy(stored), copy.deepcopy(evicted)

    def add_defense_lesson(self, lesson: dict, *, origin: dict) -> tuple[dict, list[dict]]:
        clean = validate_defense_lesson(lesson)
        _origin(origin)
        with self._lock:
            if any(item["id"] == clean["id"] for item in self._document["defense_lessons"]):
                raise ValueError("defense lesson id already stored")
            stored = {**clean, "origin": copy.deepcopy(origin), "created_at": time.time()}
            self._document["defense_lessons"].append(stored)
            evicted = self._document["defense_lessons"][:-MAX_DEFENSE_LESSONS]
            del self._document["defense_lessons"][:-MAX_DEFENSE_LESSONS]
            self._append_ledger("defense_lesson_added", stored["id"],
                                f"origin={origin.get('source_id', '')} evicted={len(evicted)}")
            self._save()
            return copy.deepcopy(stored), copy.deepcopy(evicted)

    def attack_skills(self, limit: int = 3) -> list[dict]:
        if not 1 <= limit <= MAX_ATTACK_SKILLS:
            raise ValueError("attack skill limit out of bounds")
        with self._lock:
            return copy.deepcopy(self._document["attack_skills"][-limit:])

    def defense_lessons(self, limit: int = 6) -> list[dict]:
        if not 1 <= limit <= MAX_DEFENSE_LESSONS:
            raise ValueError("defense lesson limit out of bounds")
        with self._lock:
            return copy.deepcopy(self._document["defense_lessons"][-limit:])

    def skill_digest(self, skill: dict) -> list[str]:
        return [item["id"] for item in self._document["attack_skills"]]

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._document)
