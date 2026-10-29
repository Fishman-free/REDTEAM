"""Pre-flight checks a defender can run before submitting a bundle.

The report is intentionally blunt: any failing check means the platform would
reject the bundle (policy floor, egress declaration) or the runtime would be
unstable (measurement drift).  It never claims hardware confidentiality.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ..egress import EgressDeclaration, EgressPolicy
from ..policy import PolicyError, WalletPolicy, validate_byoa_floor
from ..sealed import compute_measurement


def conformance_report(
    *,
    egress: EgressDeclaration,
    compose_files: Mapping[str, str | bytes],
    policy: WalletPolicy,
    max_task_amount: int,
    contest_end: int,
    transport_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}

    decisions = EgressPolicy(egress)
    checks["egress_denies_undeclared"] = not decisions.check(
        "https://undeclared.invalid/", kind="model"
    ).allowed
    if egress.model_hosts:
        host = sorted(egress.model_hosts)[0]
        checks["egress_allows_declared_model"] = decisions.check(
            f"https://{host}/v1/chat", kind="model"
        ).allowed
    if egress.oracles:
        rule = egress.oracles[0]
        decision = decisions.check(
            f"https://{rule.host}{rule.path_prefix}", kind="oracle"
        )
        checks["egress_oracle_allows_schema"] = decision.allowed
        if decision.allowed:
            redacted = decisions.redact(
                decision,
                {"injected": "attack", **{field: "ok" for field in rule.fields}},
            )
            checks["egress_oracle_redacts"] = set(redacted) == set(rule.fields)

    first = compute_measurement(compose_files)
    checks["measurement_stable"] = first == compute_measurement(compose_files)

    try:
        validate_byoa_floor(
            policy,
            max_task_amount=max_task_amount,
            contest_end=contest_end,
        )
        checks["policy_floor"] = True
    except PolicyError:
        checks["policy_floor"] = False

    if transport_check is not None:
        try:
            checks["transport_reachable"] = transport_check() is True
        except Exception:
            checks["transport_reachable"] = False

    return {
        "ok": all(checks.values()),
        "checks": checks,
        "measurement": first,
        "tier": "simulated",
        "note": (
            "Simulated tier: verifies flow only. Hardware attestation requires "
            "a vendor quote verifier and is not claimed here."
        ),
    }
