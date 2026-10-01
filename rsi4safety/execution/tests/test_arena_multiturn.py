"""Native multi-turn dispatch must preserve its protocol and Arena audit path."""
import contextlib
import io
import json
import sys
import types
from unittest.mock import Mock, patch

import pytest

from rsi4safety.arena.audit import HashChain
from rsi4safety.arena.multiturn import run_live_campaign
from rsi4safety.cli import _run_arena, build_parser


def test_adapter_forwards_campaign_budgets_without_legacy_protocol(tmp_path):
    report = {"status": "completed", "summary": {"verified_breaks": 2}}
    campaign = types.ModuleType("payassist_agent.campaign")
    campaign.run_campaign = Mock(return_value=report)
    with patch.dict(sys.modules, {"payassist_agent.campaign": campaign}):
        result = run_live_campaign(
            tmp_path / "state", rounds=4, attacks_per_round=12, repetitions=3,
            max_candidates=3, seed=29, max_sut_calls=2400, max_role_calls=95,
            max_role_tokens=3_000_000, resume=True,
        )
    assert result is report
    campaign.run_campaign.assert_called_once_with(
        (tmp_path / "state").resolve(), rounds=4, attacks_per_round=12,
        repetitions=3, max_candidates=3, seed=29, max_sut_calls=2400,
        max_role_calls=95, max_role_tokens=3_000_000, resume=True,
    )


def test_live_dispatch_loads_environment_and_never_enters_legacy_driver(tmp_path):
    args = build_parser().parse_args([
        "arena", "live", "--campaign", "multi-live", "--state-dir", str(tmp_path),
        "--env-file", str(tmp_path / "private.env"), "--rounds", "4",
        "--attacks-per-round", "12", "--repetitions", "3", "--max-candidates", "3",
        "--seed", "29", "--max-sut-calls", "2400", "--max-role-calls", "95",
        "--max-role-tokens", "3000000", "--resume",
    ])
    output = io.StringIO()
    with patch("rsi4safety.cli.load_env") as load_env, \
            patch("rsi4safety.arena.multiturn.run_live_campaign") as live, \
            patch("rsi4safety.arena.config.ArenaConfig") as legacy_config, \
            contextlib.redirect_stdout(output):
        live.return_value = {"status": "completed", "summary": {"verified_breaks": 2},
                             "snapshots": [{"private_trace": "should not print"}]}
        _run_arena(args)
    load_env.assert_called_once_with(tmp_path / "private.env")
    legacy_config.assert_not_called()
    live.assert_called_once_with(
        tmp_path, rounds=4, attacks_per_round=12, repetitions=3, max_candidates=3,
        seed=29, max_sut_calls=2400, max_role_calls=95,
        max_role_tokens=3_000_000, resume=True,
    )
    printed = json.loads(output.getvalue())
    assert printed["report"] == str(tmp_path.resolve() / "report.json")
    assert printed["summary"]["verified_breaks"] == 2
    assert "private_trace" not in output.getvalue()


def test_live_defaults_remain_real_and_bounded():
    args = build_parser().parse_args(["arena", "live"])
    assert args.campaign == "payassist-live"
    assert (args.rounds, args.attacks_per_round, args.repetitions) == (3, 8, 2)
    assert (args.max_sut_calls, args.max_role_calls, args.max_role_tokens) == (2500, 80, 2_500_000)
    assert args.resume is False
    assert not hasattr(args, "dry_run")
    assert not hasattr(args, "sut_llm_mode")


@pytest.mark.parametrize("arguments", [
    ["--dry-run"], ["--sut-app", "payassist"],
    ["--attacker-model", "glm-5.3-flash"], ["--sut-llm-mode", "deterministic"],
])
def test_live_cannot_silently_switch_to_scripted_or_legacy_path(arguments):
    with contextlib.redirect_stderr(io.StringIO()), pytest.raises(SystemExit):
        build_parser().parse_args(["arena", "live", *arguments])


@pytest.mark.parametrize("status", ["stopped", "budget_exhausted", "failed"])
def test_incomplete_live_campaign_is_not_reported_as_success(tmp_path, status):
    args = build_parser().parse_args(["arena", "live", "--state-dir", str(tmp_path)])
    output = io.StringIO()
    with patch("rsi4safety.cli.load_env"), \
            patch("rsi4safety.arena.multiturn.run_live_campaign", return_value={"status": status}), \
            contextlib.redirect_stdout(output), pytest.raises(SystemExit) as exit_value:
        _run_arena(args)
    assert exit_value.value.code == 1
    assert json.loads(output.getvalue())["status"] == status


def test_live_and_verify_share_arena_audit_path(tmp_path):
    def campaign(state_dir, **_kwargs):
        chain = HashChain(state_dir / "audit" / "chain.jsonl")
        chain.append("attacker", "multiturn_attack", evidence_id="evidence-1")
        chain.append("defender", "candidate_retested", candidate_id="repair-1")
        return {"status": "completed", "chain_head": chain.head()}

    live_args = build_parser().parse_args(["arena", "live", "--state-dir", str(tmp_path)])
    verify_args = build_parser().parse_args(["arena", "verify", "--state-dir", str(tmp_path)])
    with patch("rsi4safety.cli.load_env"), \
            patch("rsi4safety.arena.multiturn.run_live_campaign", side_effect=campaign), \
            contextlib.redirect_stdout(io.StringIO()):
        _run_arena(live_args)
    output = io.StringIO()
    with contextlib.redirect_stdout(output), pytest.raises(SystemExit) as exit_value:
        _run_arena(verify_args)
    assert exit_value.value.code == 0
    assert json.loads(output.getvalue()) == {
        "ok": True, "checked": 2, "first_bad_seq": None, "reason": "chain verified",
    }


@pytest.mark.parametrize("name", ["../escape", "foo/bar", "", "x" * 65])
def test_live_campaign_name_cannot_escape_default_state_directory(name):
    args = build_parser().parse_args(["arena", "live", "--campaign", name])
    with patch("rsi4safety.cli.load_env"), \
            patch("rsi4safety.arena.multiturn.run_live_campaign") as live, \
            pytest.raises(SystemExit, match="safe alphanumeric"):
        _run_arena(args)
    live.assert_not_called()
