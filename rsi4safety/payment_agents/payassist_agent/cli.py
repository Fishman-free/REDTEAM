from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import time

from .evaluation import evaluate
from .model_client import ModelConfig, OpenAICompatibleClient
from .models import all_cases, all_scenarios, canonical_hash, load_scenario
from .runtime import PaymentAgent

DEFAULT_STATE = Path(__file__).resolve().parents[2] / ".rsi4safety" / "payassist-v2"


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def summarize(results: list[dict], *, expected_repetitions: int = 1) -> dict:
    def group(items):
        count = len(items)
        return {"count": count, "passed": sum(r["evaluation"]["combined_pass"] for r in items),
                "task_completed": sum(r["evaluation"]["task_completed"] for r in items),
                "unsafe_attempt_cases": sum(bool(r["evaluation"]["unsafe_attempts"]) for r in items),
                "actual_violation_cases": sum(bool(r["evaluation"]["actual_violations"]) for r in items),
                "explicit_over_refusal": sum(r["evaluation"]["explicit_over_refusal"] for r in items),
                "safe_but_incomplete": sum(r["evaluation"]["safe_but_incomplete"] for r in items),
                "errors": sum(r["evaluation"]["error"] is not None for r in items)}
    result = {"all": group(results)}
    for category in ("level", "kind", "surface", "persona"):
        result["by_" + category] = {value: group([r for r in results if r[category] == value])
                                    for value in sorted({r[category] for r in results})}
    case_ids = sorted({r["case_id"] for r in results})
    result["all_repetitions_passed"] = sum(
        len([r for r in results if r["case_id"] == case_id]) == expected_repetitions
        and all(r["evaluation"]["combined_pass"] for r in results if r["case_id"] == case_id)
        for case_id in case_ids)
    result["unique_cases"] = len(case_ids)
    result["denominator"] = "all selected runs, including errors; by-group counts shown explicitly"
    result["payment_execution"] = "host_guarded_simulation; zero committed violations alone is not agent safety"
    result["model_calls"] = sum(len(r["snapshot"]["model_calls"]) for r in results)
    usage = Counter()
    for run in results:
        for call in run["snapshot"]["model_calls"]:
            usage.update({k: v for k, v in call.get("usage", {}).items()
                          if k in {"prompt_tokens", "completion_tokens", "total_tokens"} and type(v) is int})
    result["usage"] = dict(usage)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Multi-turn L0/L1 payment agent lab (simulated funds)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list implemented scenarios and cases")
    def common(name):
        p = sub.add_parser(name)
        p.add_argument("--env-file", type=Path)
        p.add_argument("--model")
        p.add_argument("--base-url")
        return p
    chat = common("chat")
    chat.add_argument("--scenario", required=True)
    chat.add_argument("--output", type=Path)
    bench = common("bench")
    bench.add_argument("--level", choices=["L0", "L1"])
    bench.add_argument("--kind", choices=["normal", "attack"])
    bench.add_argument("--case", action="append")
    bench.add_argument("--repetitions", type=int, default=1)
    bench.add_argument("--output", type=Path)
    serve = common("serve")
    serve.add_argument("--port", type=int, default=8011)
    serve.add_argument("--access-file", type=Path, default=DEFAULT_STATE / "server-access.json")
    live = sub.add_parser("campaign", help="live GLM-5.3 attack/repair campaign against the Studio model")
    live.add_argument("--state-dir", type=Path, required=True)
    live.add_argument("--level", choices=["all", "L0", "L1"], default="all")
    live.add_argument("--rounds", type=int, default=3)
    live.add_argument("--attacks-per-round", type=int, default=8)
    live.add_argument("--repetitions", type=int, default=2)
    live.add_argument("--max-candidates", type=int, default=2)
    live.add_argument("--seed", type=int, default=17)
    live.add_argument("--max-sut-calls", type=int, default=2500)
    live.add_argument("--max-role-calls", type=int, default=80)
    live.add_argument("--max-role-tokens", type=int, default=2_500_000)
    live.add_argument("--concurrency", type=int, default=1)
    live.add_argument("--memory-file", type=Path)
    live.add_argument("--resume", action="store_true")
    creport = sub.add_parser("campaign-report", help="render a finished campaign state dir into the L0 report")
    creport.add_argument("--state-dir", type=Path, required=True)
    creport.add_argument("--level", choices=["all", "L0", "L1"], default="L0")
    creport.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    scenarios = all_scenarios()
    if args.command == "list":
        print(json.dumps({"scenarios": [{"id": s.id, "level": s.level, "persona": s.persona,
                                         "instruction": s.owner_instruction} for s in scenarios.values()],
                          "cases": [{k: c[k] for k in ("id", "scenario_id", "kind", "surface")} for c in all_cases()]},
                         ensure_ascii=False, indent=2))
        return
    if args.command == "campaign":
        from .campaign import run_campaign
        report = run_campaign(args.state_dir, rounds=args.rounds,
                              attacks_per_round=args.attacks_per_round, repetitions=args.repetitions,
                              max_candidates=args.max_candidates, seed=args.seed,
                              max_sut_calls=args.max_sut_calls, max_role_calls=args.max_role_calls,
                              max_role_tokens=args.max_role_tokens, level=args.level,
                              concurrency=args.concurrency, memory_file=args.memory_file,
                              resume=args.resume)
        print(json.dumps({key: report[key] for key in ("status", "phase", "active_version", "summary", "usage")
                          if key in report}, ensure_ascii=False, indent=2))
        print("Report:", (Path(args.state_dir).resolve() / "report.json"))
        raise SystemExit(0 if report.get("status") == "complete" else 1)
    if args.command == "campaign-report":
        from .campaign_report import build_report
        markdown = build_report(args.state_dir, level=args.level)
        output = args.output or DEFAULT_STATE / f"campaign-report-{args.state_dir.name}.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown + "\n", encoding="utf-8")
        print(f"Report written: {output.resolve()} ({len(markdown)} chars)")
        return
    config = ModelConfig.from_env(env_file=args.env_file)
    config = replace(config, **{key: value for key, value in {"model": args.model, "base_url": args.base_url}.items() if value})
    client = OpenAICompatibleClient(config)
    if args.command == "chat":
        agent = PaymentAgent(load_scenario(args.scenario), client)
        output = args.output or DEFAULT_STATE / f"chat-{agent.id}.json"
        print(json.dumps(agent.scenario.contract, ensure_ascii=False, indent=2))
        print("输入委托用户消息；/external 内容 = 外部对话；/quit = 保存退出。")
        try:
            while True:
                try:
                    message = input("你> ").strip()
                except EOFError:
                    break
                if message == "/quit":
                    break
                if not message:
                    continue
                external = message.startswith("/external ")
                result = agent.turn(message.removeprefix("/external ") if external else message,
                                    channel="external" if external else "owner")
                print("PayAssist>", result["reply"])
                if result["error"]:
                    print("执行错误（本轮未通过验收）:", result["error"])
                _write(output, agent.snapshot())
                if result["error"]:
                    break
        finally:
            _write(output, agent.snapshot())
            print("Evidence:", output.resolve())
    elif args.command == "serve":
        import uvicorn
        from .service import create_app
        token = os.environ.get("PAYASSIST_CONTROL_TOKEN") or secrets.token_urlsafe(32)
        app = create_app(token, client)
        args.access_file.parent.mkdir(parents=True, exist_ok=True)
        # Private capability material is not printed to shared terminal output.
        if args.access_file.is_symlink():
            raise ValueError("access file must not be a symbolic link")
        fd = os.open(args.access_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w") as stream:
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), 0o600)
            json.dump({"base_url": f"http://127.0.0.1:{args.port}", "control_token": token}, stream)
        print("Controller access file:", args.access_file.resolve())
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    elif args.command == "bench":
        if not 1 <= args.repetitions <= 10:
            parser.error("repetitions must be between 1 and 10")
        cases = [case for case in all_cases() if (not args.level or scenarios[case["scenario_id"]].level == args.level)
                 and (not args.kind or case["kind"] == args.kind) and (not args.case or case["id"] in args.case)]
        if not cases or (args.case and set(args.case) != {case["id"] for case in cases}):
            parser.error("empty, unknown or conflicting case selection")
        output = args.output or DEFAULT_STATE / f"benchmark-{time.strftime('%Y%m%d-%H%M%S')}.json"
        report = {"schema_version": "payassist.benchmark.v1", "started_at": time.time(),
                  "status": "in_progress", "expected_run_count": len(cases) * args.repetitions,
                  "model": config.model, "base_url": config.base_url, "repetitions": args.repetitions,
                  "case_set_sha256": canonical_hash(cases),
                  "source_sha256": canonical_hash({p.name: p.read_text() for p in sorted(Path(__file__).parent.glob('*.py'))}),
                  "results": []}
        for case in cases:
            for repetition in range(1, args.repetitions+1):
                scenario = scenarios[case["scenario_id"]]
                agent = PaymentAgent(scenario, client)
                for override in case.get("tool_overrides", []):
                    agent.add_tool_override(override)
                for turn in case["turns"]:
                    result = agent.turn(turn["content"], channel=turn["channel"], claimed_sender=turn.get("claimed_sender", ""),
                                        requests_execution=bool(turn.get("requests_execution", False)))
                    if result["error"]:
                        break
                snapshot = agent.snapshot()
                evaluation = evaluate(case, snapshot)
                report["results"].append({"case_id": case["id"], "repetition": repetition,
                    "scenario_id": scenario.id, "level": scenario.level, "persona": scenario.persona,
                    "kind": case["kind"], "surface": case["surface"], "evaluation": evaluation, "snapshot": snapshot})
                label = "ERROR" if evaluation["error"] else "PASS" if evaluation["combined_pass"] else "FAIL"
                print(f"{case['id']} #{repetition}: {label} completion={evaluation['task_completed']} "
                      f"unsafe_attempts={len(evaluation['unsafe_attempts'])} "
                      f"calls={len(snapshot['model_calls'])}", flush=True)
                report["summary"] = summarize(report["results"], expected_repetitions=args.repetitions)
                _write(output, report)
        report["finished_at"] = time.time()
        report["status"] = "complete"
        _write(output, report)
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        print("Evidence:", output.resolve())
        raise SystemExit(2 if report["summary"]["all"]["errors"] else
                         0 if report["summary"]["all"]["passed"] == len(report["results"]) else 1)
