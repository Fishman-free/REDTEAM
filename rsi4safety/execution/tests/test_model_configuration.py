"""All research roles use GLM 5.3; only the payment planner is configurable."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from rsi4safety.arena.config import ArenaConfig, ROLES
from rsi4safety.arena.runtime import ClaudeCodeRuntime
from rsi4safety.cli import _run_arena, build_parser
from rsi4safety.config import DEFAULT_PAYMENT_MODEL, ExperimentConfig


class ModelConfigurationTests(unittest.TestCase):
    def test_role_defaults_and_all_claude_aliases_select_glm_53(self):
        config = ArenaConfig()
        self.assertEqual(config.planning_model, DEFAULT_PAYMENT_MODEL)
        for role in ROLES:
            with self.subTest(role=role):
                self.assertEqual(config.model_for(role), "glm-5.3")
                env = config.agent_container_env(role, "never-forward-this-key", "gateway-token")
                for key in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                            "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                            "ANTHROPIC_SMALL_FAST_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
                    self.assertEqual(env[key], "glm-5.3", key)
                self.assertNotIn("never-forward-this-key", str(env))

    def test_non_payment_model_overrides_are_rejected_before_execution(self):
        for model in ("glm-5.3-flash", "glm-4.6", "deepseek-chat", DEFAULT_PAYMENT_MODEL):
            with self.subTest(model=model), self.assertRaisesRegex(ValueError, "must be glm-5.3"):
                ExperimentConfig(model=model)
            for role in ROLES:
                with self.subTest(model=model, role=role), self.assertRaisesRegex(ValueError, "must be glm-5.3"):
                    ArenaConfig(**{f"{role}_model": model})

    def test_payment_model_override_remains_independent(self):
        config = ArenaConfig(sut_model="explicit-payment-model", sut_base_url="http://127.0.0.1:18081/v1")
        self.assertEqual(config.planning_model, "explicit-payment-model")
        self.assertEqual({config.model_for(role) for role in ROLES}, {"glm-5.3"})
        self.assertEqual(ExperimentConfig().model, "glm-5.3")

    def test_cli_rejects_legacy_role_model_selection(self):
        parser = build_parser()
        commands = [["arena", "run", f"--{role}-model", "glm-5.3-flash"] for role in ROLES]
        commands.append(["experiment", "--model", "glm-5.3-flash"])
        for command in commands:
            with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit):
                parser.parse_args(command)

    def test_cli_explicit_role_model_and_payment_settings_reach_runtime(self):
        args = build_parser().parse_args(["arena", "run", "--dry-run", "--attacker-model", "glm-5.3",
                                         "--sut-model", DEFAULT_PAYMENT_MODEL])
        with patch.dict(os.environ, {}, clear=True), \
                patch("rsi4safety.arena.orchestrator.ArenaOrchestrator") as orchestrator, \
                contextlib.redirect_stdout(io.StringIO()):
            orchestrator.return_value.run.return_value = {"status": "completed"}
            _run_arena(args)
        config = orchestrator.call_args.args[0]
        self.assertEqual({config.model_for(role) for role in ROLES}, {"glm-5.3"})
        self.assertEqual(config.planning_model, DEFAULT_PAYMENT_MODEL)

    def test_live_session_command_pins_glm_53_for_new_and_resumed_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ArenaConfig(state_dir=Path(directory))
            host = MagicMock()
            host.exec_agent.return_value = (0, '{"type":"result","subtype":"success","num_turns":2,"session_id":"session"}')
            runtime = ClaudeCodeRuntime(host)
            for resumed in (False, True):
                with self.subTest(resumed=resumed):
                    if resumed:
                        runtime._session_ids["attacker"] = "previous-session"
                    with patch.object(runtime, "_inject_deadline_nudge"), \
                            patch.object(runtime, "_archive_transcripts"):
                        runtime.run_session(config, "attacker", 1)
                    command = host.exec_agent.call_args.args[1]
                    self.assertEqual(command[command.index("--model") + 1], "glm-5.3")
                    self.assertEqual("--resume" in command, resumed)
