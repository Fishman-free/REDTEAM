"""Background event-indexer loop for the single-process platform API.

The API historically required a separate ``process_block_range`` loop.  For a
public web deployment that is one more moving part (and one more way for the
dApp to show empty leaderboards), so this runner owns the loop inside the API
process.  It is deliberately tiny and single-writer: the indexer is SQLite
backed and the API is deployed with one uvicorn worker.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

LOGGER = logging.getLogger(__name__)


class IndexerRunner:
    """Poll a chain event source and feed the idempotent EventIndexer."""

    def __init__(
        self,
        indexer: Any,
        source: Any,
        *,
        start_block: int = 0,
        interval: float = 1.5,
        chunk_size: int = 200,
    ) -> None:
        if int(start_block) < 0:
            raise ValueError("start_block must be non-negative")
        if not interval > 0:
            raise ValueError("interval must be positive")
        if int(chunk_size) <= 0:
            raise ValueError("chunk_size must be positive")
        self.indexer = indexer
        self.source = source
        self.start_block = int(start_block)
        self.interval = float(interval)
        self.chunk_size = int(chunk_size)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._start_warning: str | None = None
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "running": False,
            "lastBlock": None,
            "latestBlock": None,
            "lag": None,
            "lastError": None,
            "updatedAt": None,
            "events": None,
        }

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._state["running"] = True
            self._thread = threading.Thread(
                target=self._loop,
                name="redteam-indexer",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 8.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        with self._lock:
            self._state["running"] = False

    # -- status ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        state["running"] = bool(self._thread and self._thread.is_alive())
        return state

    # -- loop -----------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._step()
            except Exception as exc:  # keep the loop alive across transient RPC errors
                LOGGER.warning("indexer loop failed: %s", exc)
                with self._lock:
                    self._state["lastError"] = str(exc)
                    self._state["updatedAt"] = int(time.time())
                self._stop.wait(min(self.interval * 4, 10.0))
                continue
            self._stop.wait(self.interval)

    def _step(self) -> None:
        latest = int(self.source.latest_block)
        last = self.indexer.last_block()
        start = self.start_block if last is None else int(last) + 1
        start = max(0, start)
        # A fork of a public chain can be tens of millions of blocks deep.  Without
        # an explicit deployment block, never attempt a full-history scan.
        if last is None and self.start_block == 0 and latest > 1_000_000:
            if self._start_warning is None:
                self._start_warning = (
                    "PLATFORM_INDEXER_START_BLOCK is not configured; "
                    "scanning only the most recent 10,000 blocks"
                )
            start = max(0, latest - 10_000)
        start_warning = self._start_warning

        with self._lock:
            self._state["latestBlock"] = latest
            self._state["lastBlock"] = last
            self._state["updatedAt"] = int(time.time())
            self._state["lastError"] = start_warning

        if start <= latest:
            cursor = start
            while cursor <= latest and not self._stop.is_set():
                end = min(latest, cursor + self.chunk_size - 1)
                self.indexer.process_block_range(self.source, cursor, end)
                cursor = end + 1
                last = self.indexer.last_block()
                with self._lock:
                    self._state["lastBlock"] = last
                    self._state["latestBlock"] = latest
                    self._state["lag"] = (
                        max(0, latest - int(last)) if last is not None else None
                    )
                    self._state["updatedAt"] = int(time.time())

        if last is None:
            last = self.indexer.last_block()
        lag = max(0, latest - int(last)) if last is not None else None
        events = None
        try:
            events = int(self.indexer.sync_state().get("events", 0))
        except Exception:
            events = None
        if self._start_warning and lag == 0:
            self._start_warning = None
            start_warning = None
        with self._lock:
            self._state["lastBlock"] = last
            self._state["latestBlock"] = latest
            self._state["lag"] = lag
            self._state["events"] = events
            self._state["lastError"] = start_warning
            self._state["updatedAt"] = int(time.time())
