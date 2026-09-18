from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path

from .providers import CallBudget, OpenAICompatibleChatModel


def load_env(path: Path = Path(".env")) -> None:
    """Read a simple local env file without evaluating shell syntax or overriding env."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {"GLM_API_KEY", "GLM_BASE_URL", "GLM_MODEL", "DEEPSEEK_API_KEY"}:
            os.environ.setdefault(key, value.strip().strip("\"'"))


@dataclass(frozen=True)
class ExperimentConfig:
    model: str = "glm-5.3-flash"
    base_url: str = "https://open.bigmodel.cn/api/coding/paas/v4"
    rounds: int = 3
    attacks_per_round: int = 3
    max_candidates: int = 2
    repetitions: int = 2
    max_calls: int = 400
    max_tokens: int = 2_000_000
    max_output_tokens: int = 1200
    timeout_seconds: int = 45
    seed: int = 17
    concurrency: int = 3

    def __post_init__(self) -> None:
        for name in ("rounds", "attacks_per_round", "max_candidates", "repetitions", "max_calls", "max_tokens", "max_output_tokens", "timeout_seconds", "concurrency"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.rounds > 20 or self.attacks_per_round > 12 or self.max_candidates > 4:
            raise ValueError("experiment exceeds bounded round/attack/candidate limits")
        if self.concurrency > 8:
            raise ValueError("concurrency must be at most 8")

    def public_dict(self) -> dict:
        return asdict(self)

    def models(self, budget: CallBudget, audit_log: Path) -> dict[str, OpenAICompatibleChatModel]:
        return {
            role: OpenAICompatibleChatModel(
                model=self.model, base_url=self.base_url, role=role, budget=budget,
                audit_log=audit_log, max_output_tokens=self.max_output_tokens,
                timeout_seconds=self.timeout_seconds, disable_thinking=True,
                temperature=0.8 if role == "attacker" else 0,
                cache_dir=audit_log.parent / "cache",
                use_cache=role in {"attacker", "improver"},
            )
            for role in ("attacker", "defender", "improver")
        }
