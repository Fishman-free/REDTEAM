import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

from rsi4safety.cli import _run_arena, build_parser


class ArenaCliTests(unittest.TestCase):
    def test_run_and_smoke_share_optional_sut_model(self):
        for command in ('run', 'smoke'):
            with self.subTest(command=command):
                args = build_parser().parse_args(['arena', command])
                self.assertIsNone(args.sut_model)
                args = build_parser().parse_args([
                    'arena', command, '--sut-model', 'test-model'])
                self.assertEqual(args.sut_model, 'test-model')

    def test_smoke_reaches_orchestrator_without_attribute_error(self):
        args = build_parser().parse_args(['arena', 'smoke', '--campaign', 'cli-test'])
        with patch('rsi4safety.cli.load_env'), \
                patch('rsi4safety.arena.config.glm_api_key', return_value='fixture'), \
                patch('rsi4safety.arena.docker_host.DockerHost') as docker, \
                patch('rsi4safety.arena.orchestrator.ArenaOrchestrator') as orchestrator, \
                patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            orchestrator.return_value.run.return_value = {'status': 'completed'}
            _run_arena(args)
        self.assertEqual(json.loads(output.getvalue())['status'], 'completed')
        self.assertEqual(orchestrator.call_args.args[0].rounds, 1)
        docker.return_value.ping.assert_called_once()
        orchestrator.return_value.run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
