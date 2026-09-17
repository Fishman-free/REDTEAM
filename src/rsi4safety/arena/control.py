"""Host-owned campaign identity, locking and evidence verification."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import tarfile

PROTOCOL_VERSION = "arena-trusted-execution-v2"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def tree_hash(root: Path) -> str:
    files = {}
    for path in sorted(root.rglob("*")):
        if any(part in {".git", "__pycache__", ".pytest_cache"} for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            raise ValueError("symbolic links are not allowed in executable artifacts")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest(files)


def runtime_fingerprint(config) -> str:
    roots = [Path(__file__).parent, config.repo_root / "agents", config.repo_root / "docker"]
    return digest({"protocol": PROTOCOL_VERSION, "config": config.public_dict(),
                   "platform": [tree_hash(root) for root in roots],
                   "seed_source": tree_hash(config.repo_root / "sut" / "paygate")})


@contextmanager
def campaign_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another process is writing this campaign") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def extract_source(archive: Path, target: Path) -> None:
    """Accept ordinary bounded source files only, never links or embedded Git metadata."""
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        if len(members) > 10000 or sum(m.size for m in members) > 50_000_000:
            raise ValueError("source archive exceeds the size budget")
        names = set()
        for member in members:
            path = Path(member.name)
            if (path.is_absolute() or ".." in path.parts or ".git" in path.parts
                    or not (member.isfile() or member.isdir())
                    or member.name in names):
                raise ValueError("unsafe source archive member: " + member.name)
            names.add(member.name)
            if not (target / path).resolve().is_relative_to(target.resolve()):
                raise ValueError("source archive escapes destination")
        bundle.extractall(target, filter="data")


def verify_evidence(directory: Path) -> tuple[bool, str]:
    try:
        manifest = json.loads((directory / "manifest.json").read_text())
        expected = "ev-" + digest({k: v for k, v in manifest.items() if k != "evidence_id"})[:12]
        if manifest["evidence_id"] != expected or directory.name != expected:
            return False, "evidence manifest identity mismatch"
        for name, expected_hash in manifest["files"].items():
            file = directory / name
            if not file.resolve().is_relative_to(directory.resolve()) or file.is_symlink():
                return False, "evidence file escapes bundle"
            actual = "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest()
            if actual != expected_hash:
                return False, "evidence file digest mismatch: " + name
        return True, "verified"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, type(exc).__name__
