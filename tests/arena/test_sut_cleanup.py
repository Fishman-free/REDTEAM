import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rsi4safety.arena.config import ArenaConfig
from rsi4safety.arena.sut_driver import InProcessSutDriver, _Http, _terminate_process_tree


class SutCleanupTests(unittest.TestCase):
    def test_windows_kills_full_tree_even_on_initial_stop(self):
        process = Mock(pid=12345)
        with patch('rsi4safety.arena.sut_driver.os.name', 'nt'), \
                patch('rsi4safety.arena.sut_driver.subprocess.run') as run:
            run.return_value.returncode = 0
            _terminate_process_tree(process, force=False)
        self.assertEqual(run.call_args.args[0], ['taskkill', '/PID', '12345', '/T', '/F'])
        process.terminate.assert_not_called()

    def test_failed_tree_cleanup_does_not_only_kill_the_launcher(self):
        process = Mock(pid=12345)
        process.poll.return_value = None
        with patch('rsi4safety.arena.sut_driver.os.name', 'nt'), \
                patch('rsi4safety.arena.sut_driver.subprocess.run') as run:
            run.return_value.returncode = 1
            with self.assertRaisesRegex(RuntimeError, 'process-tree termination'):
                _terminate_process_tree(process, force=False)
        process.terminate.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows venv process-tree regression')
    def test_windows_sut_releases_database_on_stop(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            config = ArenaConfig(campaign_id='cleanup-test', state_dir=Path(directory) / 'state',
                                 dry_run=True, repo_root=root)
            shutil.copytree(root / 'sut' / 'paygate', config.sut_dir,
                            ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
            driver = InProcessSutDriver(config)
            driver.start()
            try:
                _Http(driver.base_url).wait_healthy(timeout_seconds=10)
            finally:
                driver.stop()
            self.assertFalse(driver._private_db_path.exists())
            self.assertIsNone(driver._process)
            self.assertIsNone(driver._log_file)


if __name__ == '__main__':
    unittest.main()
