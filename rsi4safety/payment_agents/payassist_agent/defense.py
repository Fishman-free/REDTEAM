"""Versioned agent software: instructions, runtime policy and reusable memory.

These switches operate on agent-visible inputs and proposals. They cannot edit
the host contract, ledger or evaluator. A repair is a complete small package,
not executable Python supplied by a model.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from .models import canonical_hash, require_text
from .prompts import SYSTEM_PROMPT

RUNTIME_DEFAULTS = {
    "project_tool_data": False,
    "enforce_execution_release": False,
    "preflight_payments": False,
    "complete_workflow": False,
    "ground_reports": False,
    "repair_report_schema": False,
    "max_protocol_repairs": 1,
}


@dataclass(frozen=True)
class DefensePackage:
    system_prompt: str
    runtime: dict
    memory: tuple

    @classmethod
    def parse(cls, raw: dict) -> "DefensePackage":
        if not isinstance(raw, dict) or set(raw) - {"system_prompt", "runtime", "memory"}:
            raise ValueError("defense package can only edit prompt, runtime policy and memory")
        prompt = require_text(raw.get("system_prompt"), "system_prompt", 16000)
        if len(prompt) < 100:
            raise ValueError("system_prompt must contain at least 100 characters")
        policy = raw.get("runtime", {})
        if not isinstance(policy, dict) or set(policy) - set(RUNTIME_DEFAULTS):
            raise ValueError("unknown runtime rule; host authority is immutable")
        runtime = {**RUNTIME_DEFAULTS, **policy}
        for key, value in runtime.items():
            if key == "max_protocol_repairs":
                if type(value) is not int or not 0 <= value <= 2:
                    raise ValueError("max_protocol_repairs must be 0..2")
            elif type(value) is not bool:
                raise ValueError(f"runtime.{key} must be boolean")
        memory = raw.get("memory", [])
        if not isinstance(memory, list) or len(memory) > 8:
            raise ValueError("agent memory must contain at most eight reusable rules")
        for item in memory:
            if not isinstance(item, dict) or set(item) != {"rule", "rationale"}:
                raise ValueError("memory entries require rule and rationale")
            require_text(item["rule"], "memory.rule", 1000)
            require_text(item["rationale"], "memory.rationale", 1000)
        return cls(prompt, deepcopy(runtime), tuple(deepcopy(memory)))

    def to_dict(self) -> dict:
        return {"system_prompt": self.system_prompt, "runtime": deepcopy(self.runtime),
                "memory": deepcopy(list(self.memory))}

    @property
    def digest(self) -> str:
        return canonical_hash(self.to_dict())


def default_package(prompt: str = SYSTEM_PROMPT) -> dict:
    return DefensePackage.parse({"system_prompt": prompt}).to_dict()


def hardened_package(prompt: str = SYSTEM_PROMPT) -> dict:
    """A transparent engineering control, not a model-generated repair claim."""
    return DefensePackage.parse({"system_prompt": prompt, "runtime": {
        key: 1 if key == "max_protocol_repairs" else True for key in RUNTIME_DEFAULTS
    }}).to_dict()
