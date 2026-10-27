"""智能体版本的统一接口与注册表。

一个版本 = `versions/<name>/agent.json`，只允许包含：
    name        版本名（与目录名一致）
    description 一句话说明（可选）
    defense     payassist DefensePackage 原始 dict（system_prompt/runtime/memory）

接口保持一致：底座提示词、工具面、消息信封均由平台固定；版本之间只允许
不同 defense 内容。这样平台 runner、离线 demo 与测试可以无差别加载任何版本。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from payassist_agent.defense import DefensePackage

from .base_prompt import compose_base_prompt

VERSIONS_DIR = Path(__file__).resolve().parent / "versions"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class AgentVersion:
    """一个可加载的智能体版本；behavior 只由 defense 决定。"""

    name: str
    description: str
    defense: dict

    def system_prompt(self, *, mandate: str, wallet_address: str) -> str:
        return compose_base_prompt(self.defense["system_prompt"], mandate, wallet_address)

    @property
    def digest(self) -> str:
        return DefensePackage.parse(self.defense).digest


def list_versions() -> list[str]:
    if not VERSIONS_DIR.is_dir():
        return []
    return sorted(path.parent.name for path in VERSIONS_DIR.glob("*/agent.json"))


def load_version(name: str) -> AgentVersion:
    """按名称加载版本；名字受限，防止目录穿越。"""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise ValueError("version name must match [a-z0-9][a-z0-9_-]{0,63}")
    path = VERSIONS_DIR / name / "agent.json"
    if not path.is_file():
        raise ValueError(f"unknown agent version: {name}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) - {"name", "description", "defense"}:
        raise ValueError("agent.json may only contain name, description and defense")
    if raw.get("name") != name:
        raise ValueError("agent.json name must match its directory")
    if "defense" not in raw:
        raise ValueError("agent.json requires a defense package")
    description = raw.get("description", "")
    if not isinstance(description, str) or len(description) > 500:
        raise ValueError("description must be bounded text")
    defense = DefensePackage.parse(raw["defense"]).to_dict()
    return AgentVersion(name=name, description=description, defense=defense)
