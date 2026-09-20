"""Versioned agent packages with isolated Git history and atomic activation.

The repository and evaluation receipts are owned by the orchestrator. Candidate
worktrees are scratch space: only their committed, content-addressed packages
can become active. Git never discovers or writes an enclosing project repo.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
import uuid

from . import filelock


EXCLUDED = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _is_windows() -> bool:
    """Keep platform branching patchable without changing pathlib's Path class."""
    return os.name == "nt"


def _path_present(path: Path) -> bool:
    """Also count broken symlinks, which Path.exists() intentionally excludes."""
    return path.exists() or path.is_symlink()


def _remove_projection(path: Path) -> None:
    """Remove a projection without following a directory symlink."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def tree_digest(directory: Path) -> str:
    """Hash relative names, executable bits and bytes; reject links and devices."""
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"missing package directory: {directory}")
    entries = []
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part in EXCLUDED for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"package symlinks are forbidden: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"package special files are forbidden: {relative}")
        entries.append((relative.as_posix(), bool(path.stat().st_mode & 0o111),
                        hashlib.sha256(path.read_bytes()).hexdigest()))
    return _digest(entries)


def _copy_tree(source: Path, target: Path) -> None:
    tree_digest(source)  # Validate before copying or following any paths.
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=lambda _p, names: set(names) & EXCLUDED)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canonical(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        if os.name != "nt":  # Windows cannot open a directory handle; no dir-fsync there
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        Path(name).unlink(missing_ok=True)


@dataclass(frozen=True)
class AgentPackage:
    version_id: str
    parent_version_id: str | None
    parent_package_digest: str | None
    commit: str
    package_digest: str
    source_digest: str
    components: dict[str, str]
    scope: tuple[str, ...]
    metadata: dict
    schema_version: int = 1

    def to_dict(self) -> dict:
        result = asdict(self)
        result["scope"] = list(self.scope)
        return result


class VersionStore:
    """One local store, safe across processes via an advisory mutation lock."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo = self.root / "repository"
        self.manifests = self.root / "manifests"
        self.worktrees = self.root / "worktrees"
        for directory in (self.manifests, self.worktrees, self.root / "activations"):
            directory.mkdir(exist_ok=True)

    @contextmanager
    def _locked(self):
        with (self.root / ".lock").open("a") as handle:
            filelock.lock(handle)
            try:
                yield
            finally:
                filelock.unlock(handle)

    def _git(self, *args: str, cwd: Path | None = None, data: bytes | None = None) -> bytes:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                   GIT_TERMINAL_PROMPT="0")
        result = subprocess.run(
            ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "commit.gpgsign=false",
             "-c", "user.name=arena-orchestrator", "-c", "user.email=arena@localhost",
             "-C", str(cwd or self.repo), *args], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=120,
        )
        if result.returncode:
            raise ValueError(f"package Git operation failed: {result.stderr.decode(errors='replace')[:800]}")
        return result.stdout

    def _assert_repository(self) -> None:
        if not (self.repo / ".git").is_dir() or (self.repo / ".git").is_symlink():
            raise ValueError("package repository must have its own .git directory")
        actual = Path(self._git("rev-parse", "--show-toplevel").decode().strip()).resolve()
        if actual != self.repo:
            raise ValueError("refusing to operate on an enclosing Git repository")

    @staticmethod
    def _check_id(version_id: str) -> None:
        if not isinstance(version_id, str) or not VERSION_PATTERN.fullmatch(version_id):
            raise ValueError("invalid package version id")

    def _write_manifest(self, package: AgentPackage) -> None:
        payload = package.to_dict()
        payload["manifest_digest"] = _digest(payload)
        path = self.manifests / f"{package.version_id}.json"
        # Version identity is write-once, even when the proposed bytes match.
        with path.open("xb") as handle:
            handle.write(_canonical(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _package(self, version_id: str, tree: Path, *, parent: AgentPackage | None,
                 metadata: dict | None = None) -> AgentPackage:
        source = tree / "source"
        components = {"source": tree_digest(source)}
        for prefix, agent in (("agent", tree / "agent"), ("source/agent", source / "agent")):
            if not agent.exists():
                continue
            components[prefix] = tree_digest(agent)
            for child in sorted(agent.iterdir()):
                if child.name in EXCLUDED:
                    continue
                components[f"{prefix}/{child.name}"] = (tree_digest(child) if child.is_dir()
                    else hashlib.sha256(child.read_bytes()).hexdigest())
        scope = tuple(sorted(components))
        material = {"schema_version": 1, "components": components, "scope": scope}
        return AgentPackage(version_id, parent.version_id if parent else None,
                            parent.package_digest if parent else None,
                            self._git("rev-parse", "HEAD", cwd=tree).decode().strip(),
                            _digest(material), components["source"], components, scope,
                            json.loads(_canonical(metadata or {})))

    def initialize(self, source_dir: Path, agent_dir: Path | None = None,
                   *, version_id: str = "seeded-v0") -> AgentPackage:
        self._check_id(version_id)
        with self._locked():
            if (self.root / "ACTIVE").exists():
                self._assert_repository()
                return self.active()
            self.repo.mkdir(exist_ok=True)
            if not (self.repo / ".git").exists():
                if any(self.repo.iterdir()):
                    raise ValueError("refusing to initialize a nonempty package repository")
                self._git("init", "--quiet")
            self._assert_repository()
            manifest_path = self.manifests / f"{version_id}.json"
            if manifest_path.exists():
                package = self.get(version_id)
            else:
                _copy_tree(Path(source_dir), self.repo / "source")
                if agent_dir is not None:
                    _copy_tree(Path(agent_dir), self.repo / "agent")
                self._git("add", "--all", "--force", "--", ".")
                self._git("commit", "--quiet", "--allow-empty", "-m", f"initialize {version_id}")
                package = self._package(version_id, self.repo, parent=None)
                with tempfile.TemporaryDirectory(prefix=".verify-", dir=self.root) as temporary:
                    self._export(package, Path(temporary))
                self._write_manifest(package)
            self._activate(package, kind="initialize", detail={"reason": "initial baseline"})
            return package

    def get(self, version_id: str) -> AgentPackage:
        self._check_id(version_id)
        payload = json.loads((self.manifests / f"{version_id}.json").read_text())
        seal = payload.pop("manifest_digest", None)
        if seal != _digest(payload) or payload.get("version_id") != version_id:
            raise ValueError("package manifest integrity check failed")
        payload["scope"] = tuple(payload["scope"])
        package = AgentPackage(**payload)
        expected = _digest({"schema_version": package.schema_version,
                            "components": package.components, "scope": package.scope})
        if expected != package.package_digest or package.components.get("source") != package.source_digest:
            raise ValueError("package content identity is inconsistent")
        self._assert_repository()
        self._git("cat-file", "-e", f"{package.commit}^{{commit}}")
        return package

    def active(self) -> AgentPackage | None:
        pointer = self.root / "ACTIVE"
        if not pointer.exists():
            return None
        value = json.loads(pointer.read_text())
        package = self.get(value["version_id"])
        if value.get("package_digest") != package.package_digest:
            raise ValueError("ACTIVE content digest mismatch")
        receipt_path = self.root / "activations" / f"{value['activation_id']}.json"
        receipt = json.loads(receipt_path.read_text())
        if (_digest(receipt) != value["activation_id"] or receipt.get("version_id") != package.version_id
                or receipt.get("package_digest") != package.package_digest):
            raise ValueError("ACTIVE activation receipt mismatch")
        return package

    def worktree_path(self, version_id: str) -> Path:
        self._check_id(version_id)
        return self.worktrees / version_id

    def save_candidate(self, candidate_id: str, source_dir: Path, *, parent_version_id: str,
                       parent_package_digest: str, agent_dir: Path | None = None,
                       metadata: dict | None = None) -> AgentPackage:
        self._check_id(candidate_id)
        with self._locked():
            parent = self.get(parent_version_id)
            if parent.package_digest != parent_package_digest:
                raise ValueError("candidate parent content digest mismatch")
            if (self.manifests / f"{candidate_id}.json").exists():
                raise ValueError("candidate version already exists")
            target = self.worktree_path(candidate_id)
            if target.exists():
                raise ValueError("candidate worktree already exists; use a new candidate id")
            self._git("worktree", "add", "--quiet", "--detach", str(target), parent.commit)
            _copy_tree(Path(source_dir), target / "source")
            if agent_dir is not None:
                _copy_tree(Path(agent_dir), target / "agent")
            self._git("add", "--all", "--force", "--", ".", cwd=target)
            self._git("commit", "--quiet", "--allow-empty", "-m", f"candidate {candidate_id}", cwd=target)
            package = self._package(candidate_id, target, parent=parent, metadata=metadata)
            with tempfile.TemporaryDirectory(prefix=".verify-", dir=self.root) as temporary:
                self._export(package, Path(temporary))
            self._write_manifest(package)
            return package

    def _export(self, package: AgentPackage, target: Path) -> None:
        """Export literal Git blobs: .gitattributes cannot omit or rewrite files."""
        listing = self._git("ls-tree", "-rz", "--full-tree", package.commit)
        entries = []
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            header, raw_path = entry.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            path = Path(os.fsdecode(raw_path))
            if (kind != "blob" or mode not in {"100644", "100755"} or path.is_absolute()
                    or ".." in path.parts or path.parts[0] not in {"source", "agent"}):
                raise ValueError("Git tree contains a forbidden package entry")
            entries.append((path, mode, oid))
        output = self._git("cat-file", "--batch", data=b"".join(
            oid.encode() + b"\n" for _, _, oid in entries))
        offset = 0
        target.mkdir(parents=True, exist_ok=True)
        for path, mode, oid in entries:
            newline = output.index(b"\n", offset)
            actual_oid, kind, size = output[offset:newline].decode().split()
            if actual_oid != oid or kind != "blob":
                raise ValueError("Git blob export integrity failed")
            offset = newline + 1
            content = output[offset:offset + int(size)]
            offset += int(size) + 1
            destination = target / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            destination.chmod(0o755 if mode == "100755" else 0o644)
        (target / "source").mkdir(exist_ok=True)
        if "agent" in package.components:
            (target / "agent").mkdir(exist_ok=True)
        if tree_digest(target / "source") != package.source_digest:
            raise ValueError("committed source differs from its package manifest")
        if "agent" in package.components and tree_digest(target / "agent") != package.components["agent"]:
            raise ValueError("committed agent artifacts differ from their package manifest")

    def _projection(self, package: AgentPackage) -> Path:
        projections = self.root / "projections"
        projections.mkdir(exist_ok=True)
        target = projections / f"{package.version_id}-{package.package_digest[:16]}"
        if target.exists():
            if tree_digest(target / "source") != package.source_digest:
                raise ValueError("stored source projection was modified")
            if "agent" in package.components and tree_digest(target / "agent") != package.components["agent"]:
                raise ValueError("stored agent projection was modified")
            return target
        staging = Path(tempfile.mkdtemp(prefix=".projection-", dir=projections))
        try:
            self._export(package, staging)
            os.replace(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return target

    def _switch_projection(self, source: Path, target: Path) -> Path:
        target = Path(os.path.abspath(target))  # Preserve a previous projection symlink.
        if target == self.root or self.root.is_relative_to(target) or target.is_relative_to(self.root):
            raise ValueError("projection target must be outside the version store")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}-{uuid.uuid4().hex}.link"
        copy = temporary.with_suffix(".copy")
        backup = None  # Set only after the old view has actually moved.
        install_committed = False
        try:
            try:
                temporary.symlink_to(source, target_is_directory=True)
            except OSError as exc:
                if not _is_windows() or getattr(exc, "winerror", None) != 1314:
                    raise
                # No Developer Mode/admin privilege: stage a complete ordinary
                # directory, never copy directly into the consumer-visible view.
                shutil.copytree(source, temporary, symlinks=False)
            if _path_present(target) and (not target.is_symlink() or _is_windows()):
                # POSIX can replace a symlink atomically. Windows directory links
                # and ordinary directories need a move-aside, under the store's
                # mutation lock. Retain legacy .git and old view bytes intact.
                backups = self.root / "legacy-projections"
                backups.mkdir(exist_ok=True)
                moved = backups / uuid.uuid4().hex
                # Do NOT use shutil.move's copy/delete fallback. A failed rename
                # must leave the old view alone; publish backup only on success.
                os.rename(target, moved)
                backup = moved
            try:
                os.replace(temporary, target)
            except PermissionError as exc:
                if not _is_windows() or getattr(exc, "winerror", None) != 5:
                    raise
                if _path_present(target):
                    # Another writer is outside our advisory lock. Do not merge
                    # into it, follow it, or delete it during rollback.
                    raise RuntimeError("Windows projection target remained occupied after move-aside") from exc
                # Some Windows filesystems/ACLs reject directory-link replacement.
                # Copy only verified committed projection bytes (not the mutable
                # candidate worktree), then rename a complete ordinary directory.
                shutil.copytree(source, copy, symlinks=False)
                if _path_present(target):
                    raise FileExistsError("projection target appeared during copy staging")
                os.rename(copy, target)
            install_committed = True
        except BaseException as exc:
            if backup is not None and not install_committed:
                if _path_present(target):
                    raise RuntimeError(
                        f"projection install failed ({exc}); target occupied; "
                        f"previous view retained at {backup}"
                    ) from exc
                try:
                    os.rename(backup, target)
                except OSError as restore_error:
                    raise RuntimeError(
                        f"projection install failed ({exc}); previous view retained at {backup}; "
                        f"restore failed: {restore_error}"
                    ) from exc
            raise
        finally:
            # Only our staging entries: never remove target or follow a link into
            # the immutable store. A partial copy cannot survive as a live view.
            _remove_projection(temporary)
            _remove_projection(copy)
        return target

    def materialize(self, version_id: str, target_dir: Path) -> Path:
        """Install a complete projection; Windows move-aside is not atomic."""
        with self._locked():
            return self._switch_projection(self._projection(self.get(version_id)), Path(target_dir))

    def materialize_source(self, version_id: str, target_dir: Path) -> Path:
        """Project committed source without .git, with rollback on install errors."""
        with self._locked():
            return self._switch_projection(self._projection(self.get(version_id)) / "source", Path(target_dir))

    def _activate(self, package: AgentPackage, *, kind: str, detail: dict) -> None:
        receipt = {"schema_version": 1, "kind": kind, "version_id": package.version_id,
                   "package_digest": package.package_digest, "detail": detail}
        activation_id = _digest(receipt)
        receipt_path = self.root / "activations" / f"{activation_id}.json"
        if not receipt_path.exists():
            _atomic_json(receipt_path, receipt)
        _atomic_json(self.root / "ACTIVE", {"version_id": package.version_id,
                     "package_digest": package.package_digest, "activation_id": activation_id})

    def promote(self, version_id: str, *, evaluation: dict,
                expected_parent_digest: str) -> AgentPackage:
        with self._locked():
            package = self.get(version_id)
            parent = self.active()
            if (parent is None or parent.package_digest != expected_parent_digest
                    or package.parent_package_digest != expected_parent_digest
                    or package.parent_version_id != parent.version_id):
                raise ValueError("promotion parent is stale or content digest mismatched")
            if (evaluation.get("passed") is not True
                    or evaluation.get("candidate_package_digest") != package.package_digest
                    or not isinstance(evaluation.get("evaluation_id"), str)
                    or not evaluation["evaluation_id"]):
                raise ValueError("promotion requires a passing evaluation bound to this package")
            self._projection(package)  # Verify committed content before changing ACTIVE.
            self._activate(package, kind="promotion", detail={"evaluation": evaluation,
                           "parent_version_id": parent.version_id})
            return package

    def rollback(self, version_id: str, *, reason: str) -> AgentPackage:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("rollback requires a reason")
        with self._locked():
            package = self.get(version_id)
            validated = False
            for path in (self.root / "activations").glob("*.json"):
                record = json.loads(path.read_text())
                if path.stem != _digest(record):
                    raise ValueError("activation receipt integrity check failed")
                if (record.get("version_id") == version_id
                        and record.get("package_digest") == package.package_digest
                        and record.get("kind") in {"initialize", "promotion"}):
                    validated = True
            if not validated:
                raise ValueError("rollback target was never an accepted version")
            self._projection(package)
            previous = self.active()
            self._activate(package, kind="rollback", detail={"reason": reason,
                           "previous_version_id": previous.version_id if previous else None})
            return package

    def recover(self, target_dir: Path | None = None) -> AgentPackage | None:
        """ACTIVE is authoritative after interruption; rebuild its source view."""
        package = self.active()
        if package is not None and target_dir is not None:
            self.materialize_source(package.version_id, target_dir)
        return package
