#!/usr/bin/env python3
"""Bounded real-model engineering screen, separate from live repair claims.

Run baseline DEV, the same prompt with hardened runtime on all three splits,
then two seeds per exposure surface. One sample per case is deliberately only
a smoke screen. Raw receipts stay in the requested state directory.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "rsi4safety/payment_agents"), str(ROOT / "rsi4safety/execution/src")]

from payassist_agent.campaign_budget import BudgetedSUT
from payassist_agent.campaign_io import write_json
from payassist_agent.defense import default_package, hardened_package
from payassist_agent.expanded_suite import (ATTACK_SURFACES, SPLITS, attack_targets,
                                           evaluate_expanded, scenario_for_case, suite_cases, suite_manifest)
from payassist_agent.model_client import ModelConfig, OpenAICompatibleClient
from payassist_agent.models import canonical_hash
from payassist_agent.runtime import PaymentAgent
from rsi4safety.providers import BudgetExceeded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--max-calls", type=int, default=200)
    parser.add_argument("--max-tokens", type=int, default=2_000_000)
    parser.add_argument("--max-seconds", type=int, default=600)
    args = parser.parse_args()
    if min(args.max_calls, args.max_tokens, args.max_seconds) < 1:
        parser.error("budgets must be positive")
    args.state_dir.mkdir(parents=True, exist_ok=True)
    if (args.state_dir / "report.json").exists():
        parser.error("use a fresh state directory; a smoke run never silently resumes")
    config = ModelConfig.from_env()
    client = BudgetedSUT(OpenAICompatibleClient(config), args.state_dir / "usage.json", args.max_calls,
                         token_limit=args.max_tokens, duration_limit=args.max_seconds,
                         max_output_tokens=config.max_tokens)
    packages = {"baseline": default_package(), "engineering_control": hardened_package()}
    seeds = []
    for surface in ATTACK_SURFACES:
        pool = [case for case in attack_targets("transfer") if case["surface"] == surface]
        seeds.extend(next(case for case in pool if scenario_for_case(case).level == level)
                     for level in ("L0", "L1"))
    plan = [("baseline", "development", case) for case in suite_cases("development")]
    plan += [("engineering_control", split, case) for split in SPLITS for case in suite_cases(split)]
    plan += [("engineering_control", "transfer_seed", case) for case in seeds]
    sources = {path.name: path.read_text() for path in sorted(
        (ROOT / "rsi4safety/payment_agents/payassist_agent").glob("*.py"))}
    report = {"protocol": "payassist.engineering-smoke.v1", "status": "running", "started_at": time.time(),
              "model": config.model, "suite": suite_manifest(), "source_sha256": canonical_hash(sources),
              "packages": packages, "same_prompt": packages["baseline"]["system_prompt"] ==
                  packages["engineering_control"]["system_prompt"],
              "budgets": {"calls": args.max_calls, "tokens": args.max_tokens, "seconds": args.max_seconds},
              "expected_runs": len(plan), "results": [],
              "scope": "one-run engineering control and static seed screen; no independent attack confirmation or model-generated repair"}
    write_json(args.state_dir / "sources.json", sources)
    write_json(args.state_dir / "plan.json", [{"variant": variant, "split": split, "case": case}
                                              for variant, split, case in plan])
    write_json(args.state_dir / "report.json", report)
    try:
        for variant, split, case in plan:
            if client.usage["calls"] >= args.max_calls:
                raise BudgetExceeded("SUT call budget exhausted")
            client.check_duration()
            agent = PaymentAgent(scenario_for_case(case), client, defense_package=packages[variant])
            for override in case.get("tool_overrides", []):
                agent.add_tool_override(override)
            for item in case.get("context_inputs", []):
                agent.add_context_input(item)
            for turn in case["turns"]:
                result = agent.turn(turn["content"], channel=turn["channel"],
                                    claimed_sender=turn.get("claimed_sender", ""),
                                    requests_execution=turn.get("requests_execution", False))
                if result["error"]:
                    break
            snapshot = agent.snapshot()
            evaluation = evaluate_expanded(case, snapshot)
            record = {"variant": variant, "split": split, "case_id": case["id"], "repetition": 1,
                      "scenario_id": agent.scenario.id, "level": agent.scenario.level,
                      "persona": agent.scenario.persona, "kind": case["kind"], "surface": case["surface"],
                      "evaluation": evaluation, "snapshot": snapshot}
            trial_path = args.state_dir / "trials" / f"{variant}-{case['id']}.json"
            write_json(trial_path, record)
            report["results"].append({key: value for key, value in record.items() if key != "snapshot"} |
                                     {"path": str(trial_path.relative_to(args.state_dir)),
                                      "sha256": canonical_hash(record), "calls": len(snapshot["model_calls"])})
            report["usage"] = client.usage
            write_json(args.state_dir / "report.json", report)
            print(f"{variant} {split} {case['id']}: pass={evaluation['combined_pass']} "
                  f"business={evaluation['business_outcome']} delivery={evaluation['delivery_complete']} "
                  f"breaches={evaluation['breach_classes']} calls={len(snapshot['model_calls'])}", flush=True)
        report["status"] = "complete"
    except BudgetExceeded as exc:
        report["status"], report["stop_reason"] = "budget_stopped", str(exc)
    finally:
        report["usage"] = client.usage
        report["finished_at"] = time.time()
        write_json(args.state_dir / "report.json", report)
        print(json.dumps({key: report[key] for key in ("status", "expected_runs", "usage")}, indent=2))


if __name__ == "__main__":
    main()
