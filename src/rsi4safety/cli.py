from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import ContinuousSafetyRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Payment safety RSI research harness")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("demo", help="run offline attack, test, score, improve and retest rounds")
    demo.add_argument("--state-dir", type=Path, default=Path(".rsi4safety/demo"))
    demo.add_argument("--json", action="store_true", help="print machine-readable output")
    demo.add_argument("--rounds", type=int, default=1, help="bounded number of rounds (1-100)")
    return parser


def main() -> None:
    args = build_parser().parse_args()
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
