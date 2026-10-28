"""Small JSON/JSONL file helpers shared by the audit and transcript stores.

Every helper creates missing directories (0700 best effort), writes files with
mode 0600 best effort, and fsyncs before returning.  Errors surface as plain
``OSError`` so callers can wrap them in their domain-specific error type.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _best_effort_chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        # Windows and some filesystems cannot represent POSIX modes.
        pass


def _fsync_directory(path: Path) -> None:
    """Best-effort directory fsync (not supported on Windows)."""

    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def ensure_directory(path: Path) -> None:
    """Create ``path`` and its parents; raise ``OSError`` on failure."""

    created = not path.exists()
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise NotADirectoryError(str(path))
    if created:
        _best_effort_chmod(path, 0o700)
        _fsync_directory(path.parent)


def write_text_atomic(path: Path, text: str) -> None:
    """Atomically replace ``path`` with ``text`` (temp file + fsync + replace)."""

    ensure_directory(path.parent)
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _best_effort_chmod(Path(tmp_name), 0o600)
        os.replace(tmp_name, path)
        tmp_name = None
        _fsync_directory(path.parent)
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def append_jsonl(path: Path, line: str) -> None:
    """Append one newline-terminated JSON line under O_APPEND."""

    ensure_directory(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    _best_effort_chmod(path, 0o600)
