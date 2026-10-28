"""Unit tests for the background indexer loop."""

from __future__ import annotations

import time

from redteam_platform.indexer_runner import IndexerRunner


class FakeIndexer:
    def __init__(self, last=None):
        self._last = last
        self.calls = []
        self.closed = False

    def last_block(self):
        return self._last

    def process_block_range(self, source, start, end):
        self.calls.append((start, end))
        self._last = end
        return end - start + 1

    def sync_state(self):
        return {"events": len(self.calls)}

    def close(self):
        self.closed = True


class FakeSource:
    def __init__(self, latest=12):
        self.latest = latest

    @property
    def latest_block(self):
        return self.latest


def test_runner_syncs_from_start_block_and_reports_state():
    indexer = FakeIndexer()
    runner = IndexerRunner(indexer, FakeSource(12), start_block=10, interval=0.01, chunk_size=2)
    runner.start()
    deadline = time.time() + 2
    while time.time() < deadline and not indexer.calls:
        time.sleep(0.01)
    runner.stop()
    assert indexer.calls
    assert indexer.calls[0] == (10, 11)
    snapshot = runner.snapshot()
    assert snapshot["lastBlock"] == 12
    assert snapshot["latestBlock"] == 12
    assert snapshot["lag"] == 0
    assert snapshot["running"] is False


def test_runner_warns_when_public_fork_has_no_start_block():
    indexer = FakeIndexer()
    runner = IndexerRunner(
        indexer,
        FakeSource(2_000_000),
        start_block=0,
        interval=0.2,
        chunk_size=100,
    )
    runner.start()
    deadline = time.time() + 2
    while time.time() < deadline and not indexer.calls:
        time.sleep(0.01)
    runner.stop()
    assert indexer.calls[0][0] == 1_990_000
    assert all(start >= 1_990_000 for start, _end in indexer.calls)
