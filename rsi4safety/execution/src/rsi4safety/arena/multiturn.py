"""Arena entry point for the native, multi-turn payment-agent campaign.

The campaign uses Arena's version store, audit chain and experience records,
but keeps the multi-turn host evidence and oracle intact. It must not be
translated into the legacy, single-run HTTP/SQL payment protocol.
"""
from __future__ import annotations

from pathlib import Path


def run_live_campaign(state_dir: Path, *, rounds: int = 3,
                      attacks_per_round: int = 8, repetitions: int = 2,
                      max_candidates: int = 2, seed: int = 17,
                      max_sut_calls: int = 2500, max_role_calls: int = 80,
                      max_role_tokens: int = 2_500_000,
                      resume: bool = False) -> dict:
    """Dispatch real GLM 5.3 roles against the configured local payment model.

There is no deterministic fallback here. The campaign owns budget validation,
fresh execution, evidence-backed promotion and resumption. Model configuration
is loaded by its clients from the environment, independently for each role.
    """
    try:
        from payassist_agent.campaign import run_campaign
    except ModuleNotFoundError as exc:
        if exc.name not in {"payassist_agent", "payassist_agent.campaign"}:
            raise
        raise RuntimeError(
            "The multi-turn payment agent must be installed: "
            "python -m pip install -e payment_agents (from rsi4safety/)"
        ) from exc
    return run_campaign(
        Path(state_dir).resolve(), rounds=rounds,
        attacks_per_round=attacks_per_round, repetitions=repetitions,
        max_candidates=max_candidates, seed=seed,
        max_sut_calls=max_sut_calls, max_role_calls=max_role_calls,
        max_role_tokens=max_role_tokens, resume=resume,
    )
