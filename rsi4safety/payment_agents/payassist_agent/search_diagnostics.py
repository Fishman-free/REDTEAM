"""Cheap summaries of recorded search evidence; never make provider calls."""
from collections import Counter, defaultdict


def summarize_search(state):
    by_version = defaultdict(lambda: defaultdict(list))
    unattributed = 0
    for trial in state["trials"]:
        if trial["evaluation"].get("attack_exposure", {}).get("required"):
            if not trial.get("version") or not trial.get("case_id"):
                unattributed += 1
                continue
            by_version[trial["version"]][trial["case_id"]].append(trial["evaluation"])
    versions = []
    for version, cases in sorted(by_version.items()):
        versions.append({"version": version, "attack_cases": len(cases),
            "attack_runs": sum(len(runs) for runs in cases.values()),
            "runtime_reached_cases": sum(any(e["attack_exposure"].get("delivered_to_runtime") for e in runs) for runs in cases.values()),
            "model_reached_cases": sum(any(e["attack_exposure"].get("delivered_to_model") for e in runs) for runs in cases.values()),
            "model_violation_cases": sum(any(e.get("model_behavior", {}).get("violations") for e in runs) for runs in cases.values()),
            "system_breach_cases": sum(any(not e.get("error") and
                (e.get("breach_classes") or not e.get("business_outcome") or not e.get("delivery_complete", True))
                for e in runs) for runs in cases.values())})
    reasons = Counter(pair["reason"] for record in state["rounds"] for attack in record["attacks"]
                      for pair in attack["pairs"])
    model_reasons = Counter(pair.get("model_reason", "not_recorded") for record in state["rounds"]
                            for attack in record["attacks"] for pair in attack["pairs"])
    return {"scope": "observed attack cases per version, including replays; not confirmed findings",
            "duplicate_proposals_skipped": sum(bool(a.get("duplicate_of")) for a in state.get("generated_attacks", [])),
            "versions": versions, "unattributed_attack_runs": unattributed,
            "system_pair_reasons": dict(reasons), "model_pair_reasons": dict(model_reasons)}
