import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi4safety.arena.config import ArenaConfig, glm_api_key
from rsi4safety.cli import _run_arena, build_parser
from rsi4safety.paths import project_root


PROJECT = Path(__file__).resolve().parents[2]


class ProjectPathTests(unittest.TestCase):
    def test_source_assets_and_cli_defaults_do_not_depend_on_cwd(self):
        with tempfile.TemporaryDirectory() as temporary:
            for directory in (PROJECT.parent, PROJECT, Path(temporary)):
                with self.subTest(cwd=directory), contextlib.chdir(directory):
                    self.assertEqual(project_root(), PROJECT)
                    config = ArenaConfig()
                    self.assertEqual(config.repo_root, PROJECT)
                    self.assertTrue((config.repo_root / "payment_agents" / "payassist" / "app" / "main.py").is_file())
                    self.assertEqual(config.state_dir, PROJECT / ".rsi4safety" / "arena")
                    args = build_parser().parse_args(["demo"])
                    self.assertEqual(args.state_dir, PROJECT / ".rsi4safety" / "demo")
                    args = build_parser().parse_args(["experiment"])
                    self.assertEqual(args.env_file, PROJECT / ".env")

    def test_arena_command_uses_the_same_source_and_campaign_from_both_roots(self):
        for directory in (PROJECT.parent, PROJECT):
            with self.subTest(cwd=directory), contextlib.chdir(directory):
                args = build_parser().parse_args([
                    "arena", "run", "--dry-run", "--campaign", "path-test"])
                with patch("rsi4safety.arena.orchestrator.ArenaOrchestrator") as orchestrator, \
                        contextlib.redirect_stdout(io.StringIO()):
                    orchestrator.return_value.run.return_value = {"status": "completed"}
                    _run_arena(args)
                config = orchestrator.call_args.args[0]
                self.assertEqual(config.repo_root, PROJECT)
                self.assertEqual(config.state_dir, PROJECT / ".rsi4safety" / "arena" / "path-test")

    def test_explicit_paths_keep_caller_relative_semantics(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.chdir(temporary):
            config = ArenaConfig(repo_root=Path("custom-source"))
            expected_source = Path(temporary).resolve() / "custom-source"
            self.assertEqual(config.repo_root, expected_source)
            self.assertEqual(config.state_dir, expected_source / ".rsi4safety" / "arena")
            config = ArenaConfig(repo_root=Path("custom-source"), state_dir=Path("run-data"))
            self.assertEqual(config.state_dir, Path(temporary).resolve() / "run-data")
            args = build_parser().parse_args([
                "arena", "run", "--state-dir", "run-data", "--env-file", "custom.env"])
            self.assertEqual(args.state_dir, Path("run-data"))
            self.assertEqual(args.env_file, Path("custom.env"))

    def test_default_env_is_project_local_and_explicit_env_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text("GLM_API_KEY=project-fixture\n", encoding="utf-8")
            (root / "custom.env").write_text("GLM_API_KEY=explicit-fixture\n", encoding="utf-8")
            with patch("rsi4safety.arena.config.project_root", return_value=root), \
                    patch.dict(os.environ, {}, clear=True), contextlib.chdir(root):
                self.assertEqual(glm_api_key(), "project-fixture")
                self.assertEqual(glm_api_key(Path("custom.env")), "explicit-fixture")


if __name__ == "__main__":
    unittest.main()
