"""Portable advisory file locking for the Arena host orchestrator.

POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking`` on a single byte
at offset 0 -- the closest cross-process primitive in the stdlib. On Windows a
requested *shared* lock is upgraded to an exclusive lock: stronger than asked,
never weaker, so callers cannot observe a weaker guarantee than on POSIX.

Contract (matches ``fcntl.flock`` semantics used by the call sites):

* ``blocking=False`` on a held lock raises ``BlockingIOError``.
* ``blocking=True`` waits until the lock is free (on Windows, up to
  ``WINDOWS_LOCK_TIMEOUT_S`` before surfacing ``OSError``).
* Locks are released by ``unlock`` or when the underlying handle closes.
"""
from __future__ import annotations

import os

__all__ = ["lock", "unlock"]

if os.name == "nt":  # Windows: byte-range lock as flock substitute
    import msvcrt
    import time

    WINDOWS_LOCK_TIMEOUT_S = 120.0
    _RETRY_INTERVAL_S = 0.1

    def _try_acquire(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def lock(handle, *, shared: bool = False, blocking: bool = True) -> None:
        if not blocking:
            try:
                _try_acquire(handle)
            except OSError as exc:  # busy: normalise to the POSIX exception
                raise BlockingIOError(
                    exc.errno or 0, "file is locked by another process", getattr(handle, "name", "")
                ) from None
            return
        deadline = time.monotonic() + WINDOWS_LOCK_TIMEOUT_S
        while True:
            try:
                _try_acquire(handle)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(_RETRY_INTERVAL_S)

    def unlock(handle) -> None:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass  # already released (e.g. handle closed underneath us)

else:  # POSIX: fcntl.flock, exactly as before
    import fcntl

    def lock(handle, *, shared: bool = False, blocking: bool = True) -> None:
        mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        if not blocking:
            mode |= fcntl.LOCK_NB
        fcntl.flock(handle, mode)

    def unlock(handle) -> None:
        fcntl.flock(handle, fcntl.LOCK_UN)
