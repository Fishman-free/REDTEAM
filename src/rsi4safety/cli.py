from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .runner import ContinuousSafetyRunner
from .campaign import ExperimentRunner
from .config import ExperimentConfig, load_env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Payment safety RSI research harness")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("demo", help="run offline attack, test, score, improve and retest rounds")
    demo.add_argument("--state-dir", type=Path, default=Path(".rsi4safety/demo"))
    demo.add_argument("--json", action="store_true", help="print machine-readable output")
    demo.add_argument("--rounds", type=int, default=1, help="bounded number of rounds (1-100)")
    for name, help_text in (
        ("probe", "verify GLM credentials, model identity and JSON protocol"),
        ("experiment", "run parallel adaptive model attacks, evaluation and evolution"),
        ("repair-check", "test the repair protocol using explicitly synthetic evidence"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--state-dir", type=Path, default=Path(f".rsi4safety/{name}"))
        command.add_argument("--env-file", type=Path, default=Path(".env"))
        command.add_argument("--model", default=None)
        command.add_argument("--base-url", default=None)
        command.add_argument("--rounds", type=int, default=3)
        command.add_argument("--attacks-per-round", type=int, default=3)
        command.add_argument("--max-candidates", type=int, default=2)
        command.add_argument("--repetitions", type=int, default=2)
        command.add_argument("--concurrency", type=int, default=3)
        command.add_argument("--max-calls", type=int, default=400)
        command.add_argument("--max-tokens", type=int, default=2_000_000)
        command.add_argument("--max-output-tokens", type=int, default=1200)
        command.add_argument("--seed", type=int, default=17)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command in {"probe", "experiment", "repair-check"}:
        load_env(args.env_file)
        config = ExperimentConfig(
            model=args.model or os.getenv("GLM_MODEL", "glm-5.3-flash"),
            base_url=args.base_url or os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4"),
            rounds=args.rounds, attacks_per_round=args.attacks_per_round,
            max_candidates=args.max_candidates, repetitions=args.repetitions,
            concurrency=args.concurrency, max_calls=args.max_calls, max_tokens=args.max_tokens,
            max_output_tokens=args.max_output_tokens, seed=args.seed,
        )
        runner = ExperimentRunner(args.state_dir, config, progress=lambda event: print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True))
        if args.command == "probe":
            result = runner.preflight()
        elif args.command == "repair-check":
            runner.preflight()
            full = runner.repair_protocol_check()
            result = {"passed": full["passed"], "evidence_source": full["evidence_source"], "usage": full["usage"],
                      "report": str(args.state_dir / "repair-protocol-check.json")}
        else:
            full = runner.run()
            result = {key: full.get(key) for key in ("status", "stop_reason", "final_gate", "active_version", "usage")}
            result["verified_findings"] = sum(item.get("verified_findings", 0) for item in full["rounds"])
            result["final_scores"] = {key: value["scores"] for key, value in full.get("final_evaluation", {}).items()}
            result["report"] = str(args.state_dir / "report.json")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("status") == "stopped" or result.get("passed") is False:
            raise SystemExit(1)
        return
    if args.command == "demo":
        if not 1 <= args.rounds <= 100:
            raise SystemExit("--rounds must be between 1 and 100")
        runner = ContinuousSafetyRunner(args.state_dir)
        summaries = [runner.summary(runner.run_round()) for _ in range(args.rounds)]
        if args.json:
            print(json.dumps(summaries[0] if args.rounds == 1 else summaries, indent=2, ensure_ascii=False))
            return
        for summary in summaries:
            print(f"Payment safety round: {summary['round_id']}")
            print(f"- unauthorized commit: {summary['attack']['actual_unauthorized']} -> {summary['retest']['actual_unauthorized']}")
            print(f"- scores before: {summary['before_scores']}")
            print(f"- scores after: {summary['after_scores']}")
            for candidate in summary["candidates"]:
                state = "PASSED" if candidate["passed"] else "REJECTED"
                print(f"- {state}: {candidate['version']} ({', '.join(candidate['reasons']) or 'all gates passed'})")
            print(f"- active version: {summary['active_version']}")
