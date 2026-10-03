"""Cross-process reproducibility of benchmark fixtures (RESEARCH_PLAN §6 item 8).

``task_variant`` must derive its RNG seed from a stable digest so the same
``(seed, split, index)`` generates identical fixtures in every process,
regardless of PYTHONHASHSEED. The old implementation used built-in ``hash()``,
which is salted per process — two subprocesses with different hash seeds must
still agree.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

SNIPPET = (
    "import json;"
    "from dataclasses import asdict;"
    "from rsi4safety.benchmark import task_variant, frozen_suite;"
    "tasks = [asdict(task_variant(7, i, split='development')) for i in range(6)];"
    "suite = [c.name for c in frozen_suite(7)];"
    "print(json.dumps({'tasks': tasks, 'suite': suite}, sort_keys=True, ensure_ascii=False))"
)


class BenchmarkFixtureReproducibilityTests(unittest.TestCase):
    def test_same_seed_same_fixtures_across_processes(self) -> None:
        env = dict(os.environ, PYTHONHASHSEED="random", PYTHONPATH=SRC)
        outputs = []
        for _ in range(2):
            proc = subprocess.run([sys.executable, "-c", SNIPPET], capture_output=True,
                                  text=True, timeout=300, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            outputs.append(proc.stdout)
        self.assertEqual(outputs[0], outputs[1],
                         "same seed must generate identical fixtures in two processes")

    def test_frozen_suite_is_deterministic_in_process(self) -> None:
        from rsi4safety.benchmark import frozen_suite
        self.assertEqual([c.name for c in frozen_suite(11)],
                         [c.name for c in frozen_suite(11)])


if __name__ == "__main__":
    unittest.main()
