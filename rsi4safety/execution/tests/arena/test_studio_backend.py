"""Planner routing is independent of role models and cloud credentials."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from rsi4safety.arena.config import ArenaConfig
from rsi4safety.arena.docker_host import DockerHost
from rsi4safety.arena.sut_driver import InProcessSutDriver
from rsi4safety.cli import _run_arena, build_parser
from rsi4safety.config import load_env

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
BASE = "http://127.0.0.1:18081/v1"


class StudioBackendTests(unittest.TestCase):
    def test_local_planner_environment_contains_only_its_own_key(self):
        for app in ("payassist", "paygate"):
            with self.subTest(app=app), tempfile.TemporaryDirectory() as directory:
                config = ArenaConfig(state_dir=Path(directory), sut_app=app, sut_llm_mode="llm",
                                     sut_model=MODEL, sut_base_url=BASE)
                driver = InProcessSutDriver(config)
                with patch.dict(os.environ, {"GLM_API_KEY": "cloud-key", "DEEPSEEK_API_KEY": "other-key",
                                             "SUT_API_KEY": "planner-key"}), \
                        patch("rsi4safety.arena.sut_driver.subprocess.Popen") as spawn:
                    driver.start()
                try:
                    env = spawn.call_args.kwargs["env"]
                    self.assertEqual(env["PAYGATE_LLM_URL"], BASE + "/chat/completions")
                    self.assertEqual(env["PAYGATE_LLM_MODEL"], MODEL)
                    self.assertEqual(env["PAYGATE_LLM_MODE"], "llm")
                    self.assertEqual(env["PAYGATE_LLM_TOKEN"], "planner-key")
                    self.assertNotIn("GLM_API_KEY", env)
                    self.assertNotIn("DEEPSEEK_API_KEY", env)
                    if app == "payassist":
                        self.assertEqual(env["PAYASSIST_MODEL"], MODEL)
                        self.assertEqual(env["PAYASSIST_MODE"], "llm")
                finally:
                    driver._log_file.close()

    def test_local_runner_rejects_missing_or_non_loopback_backend(self):
        for base in (None, "https://127.0.0.1/v1", "http://192.168.100.2:18080/v1"):
            with self.subTest(base=base), tempfile.TemporaryDirectory() as directory:
                driver = InProcessSutDriver(ArenaConfig(state_dir=Path(directory),
                    sut_app="payassist", sut_llm_mode="llm", sut_base_url=base))
                with patch("rsi4safety.arena.sut_driver.subprocess.Popen") as spawn, \
                        self.assertRaisesRegex(ValueError, "HTTP loopback"):
                    driver.start()
                spawn.assert_not_called()

    def test_paychain_does_not_silently_ignore_llm_selection(self):
        with self.assertRaisesRegex(ValueError, "no LLM planner"):
            ArenaConfig(sut_app="paychain", sut_llm_mode="llm", sut_model=MODEL, sut_base_url=BASE)

    def test_endpoint_cannot_put_credentials_in_public_report(self):
        for base in ("http://user:secret@localhost/v1", "http://localhost/v1?key=secret"):
            with self.subTest(base=base), self.assertRaises(ValueError):
                ArenaConfig(sut_base_url=base)

    def test_docker_gateway_and_sut_receive_matching_model_configuration(self):
        config = ArenaConfig(sut_app="payassist", sut_llm_mode="llm", sut_model=MODEL, sut_base_url=BASE)
        host = DockerHost(config)
        host._client = MagicMock()
        container = host.client.containers.create.return_value
        container.attrs = {"NetworkSettings": {"Ports": {"8000/tcp": [{"HostPort": "19000"}]}}}
        with patch.object(host, "ensure_networks"), patch.object(host, "_connect"), \
                patch.object(host, "_detach_default_bridge"), \
                patch.object(host, "sut_image", return_value="sut:image"), \
                patch("rsi4safety.arena.docker_host.SutContainer.wait_healthy"), \
                patch.dict(os.environ, {"SUT_API_KEY": "planner-key"}):
            host.up_gateway("cloud-key", "campaign-token")
            env = host.client.containers.create.call_args.kwargs["environment"]
            self.assertEqual(env["SUT_MODEL"], MODEL)
            self.assertEqual(env["SUT_OPENAI_BASE_URL"], "http://host.docker.internal:18081/v1")
            self.assertEqual(env["SUT_API_KEY"], "planner-key")
            self.assertEqual(set(env["GATEWAY_ALLOWED_MODELS"].split(",")), {MODEL, "glm-5.3"})
            self.assertNotIn("DEEPSEEK_API_KEY", env)
            host.start_sut(Path("unused-evidence.sqlite"))
            env = host.client.containers.create.call_args.kwargs["environment"]
            self.assertEqual(env["PAYASSIST_MODEL"], MODEL)
            self.assertEqual(env["PAYASSIST_MODE"], "llm")
            self.assertNotIn("SUT_API_KEY", env)

    def test_env_file_and_cli_override_reach_arena_config(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(f"SUT_MODEL={MODEL}\nSUT_BASE_URL={BASE}\nSUT_API_KEY=planner-key\n")
            for override in (None, "explicit-model"):
                with self.subTest(override=override), patch.dict(os.environ, {}, clear=True), \
                        patch("rsi4safety.arena.config.glm_api_key", return_value="fixture"), \
                        patch("rsi4safety.arena.docker_host.DockerHost"), \
                        patch("rsi4safety.arena.orchestrator.ArenaOrchestrator") as orchestrator, \
                        contextlib.redirect_stdout(io.StringIO()):
                    args = ["arena", "smoke", "--sut-app", "payassist", "--sut-llm-mode", "llm",
                            "--env-file", str(env_file)]
                    if override:
                        args.extend(["--sut-model", override])
                    orchestrator.return_value.run.return_value = {"status": "completed"}
                    _run_arena(build_parser().parse_args(args))
                    config = orchestrator.call_args.args[0]
                    self.assertEqual(config.planning_model, override or MODEL)
                    self.assertEqual(config.sut_base_url, BASE)
                    self.assertNotIn("planner-key", str(config.public_dict()))

    def test_env_file_preserves_explicit_process_settings(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"SUT_MODEL": "override"}):
            env_file = Path(directory) / ".env"
            env_file.write_text(f"SUT_MODEL={MODEL}\n")
            load_env(env_file)
            self.assertEqual(os.environ["SUT_MODEL"], "override")
