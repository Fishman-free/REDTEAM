from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rsi4safety.arena.versions import VersionStore


def _symlinks_supported() -> bool:
    """POSIX supports symlinks everywhere; Windows requires Developer Mode/admin."""
    try:
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / "probe-link"
            link.symlink_to(Path(directory) / "probe-target")
        return True
    except (OSError, NotImplementedError):
        return False


_SYMLINKS_OK = _symlinks_supported()


def _winerror5() -> PermissionError:
    error = PermissionError(5, "access denied")
    error.winerror = 5
    return error


def _winerror1314() -> OSError:
    error = OSError(1314, "privilege")
    error.winerror = 1314
    return error


def git(directory: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "user.name=test", "-c", "user.email=test@localhost",
         "-c", "commit.gpgsign=false", "-C", str(directory), *args], text=True,
        stderr=subprocess.STDOUT,
    ).strip()


class VersionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "seed"
        (self.source / "app").mkdir(parents=True)
        (self.source / "app" / "main.py").write_text("SAFE = False\n")
        (self.source / "old.txt").write_text("legacy\n")
        self.store = VersionStore(self.root / "state" / "versions")
        self.seed = self.store.initialize(self.source)

    def candidate(self, name: str, contents: str = "SAFE = True\n"):
        path = self.root / f"input-{name}"
        (path / "app").mkdir(parents=True)
        (path / "app" / "main.py").write_text(contents)
        return self.store.save_candidate(name, path, parent_version_id=self.seed.version_id,
                                         parent_package_digest=self.seed.package_digest)

    @staticmethod
    def evaluation(package) -> dict:
        return {"evaluation_id": f"eval-{package.version_id}", "passed": True,
                "candidate_package_digest": package.package_digest}

    def test_real_git_worktrees_preserve_candidate_isolation_and_lineage(self) -> None:
        rejected = self.candidate("rejected", "SAFE = 'bad fix'\n")
        revised = self.candidate("revised", "SAFE = True\n")
        self.assertEqual(self.store.active(), self.seed)
        self.assertNotEqual(rejected.commit, revised.commit)
        self.assertEqual(git(self.store.worktree_path(revised.version_id), "rev-parse", "HEAD^"), self.seed.commit)
        self.assertFalse((self.store.worktree_path(revised.version_id) / "source" / "old.txt").exists())
        self.assertEqual((self.store.repo / "source" / "app" / "main.py").read_text(), "SAFE = False\n")
        self.assertIn(self.store.worktree_path(rejected.version_id).as_posix(),
                      git(self.store.repo, "worktree", "list", "--porcelain"))
        self.assertEqual(self.store.get(rejected.version_id), rejected)

    def test_never_uses_enclosing_repository_even_with_git_environment(self) -> None:
        project = self.root / "project"
        project.mkdir()
        git(project, "init", "--quiet")
        (project / "tracked.txt").write_text("do not change\n")
        git(project, "add", ".")
        git(project, "commit", "--quiet", "-m", "project commit")
        head = git(project, "rev-parse", "HEAD")
        status = git(project, "status", "--porcelain", "--untracked-files=no")
        nested = VersionStore(project / "campaign" / "versions")
        with patch.dict(os.environ, {"GIT_DIR": str(project / ".git"), "GIT_WORK_TREE": str(project)}):
            seed = nested.initialize(self.source)
            package = nested.save_candidate("fix", self.source, parent_version_id=seed.version_id,
                                            parent_package_digest=seed.package_digest)
            nested.promote(package.version_id, evaluation=self.evaluation(package),
                           expected_parent_digest=seed.package_digest)
        self.assertEqual(git(project, "rev-parse", "HEAD"), head)
        self.assertEqual(git(project, "status", "--porcelain", "--untracked-files=no"), status)
        self.assertEqual(Path(git(nested.repo, "rev-parse", "--show-toplevel")).resolve(), nested.repo)

    def test_agent_memory_and_skills_are_part_of_package_identity(self) -> None:
        agent = self.root / "agent"
        (agent / "skills" / "repair").mkdir(parents=True)
        (agent / "memory").mkdir()
        (agent / "skills" / "repair" / "SKILL.md").write_text("check authorization\n")
        (agent / "memory" / "lesson.md").write_text("avoid trusting receipts\n")
        (agent / "tools.json").write_text('{"allowed":["payment"]}')
        one = self.store.save_candidate("agent-one", self.source,
            parent_version_id=self.seed.version_id, parent_package_digest=self.seed.package_digest,
            agent_dir=agent)
        (agent / "memory" / "lesson.md").write_text("do not skip legitimate payments\n")
        two = self.store.save_candidate("agent-two", self.source,
            parent_version_id=self.seed.version_id, parent_package_digest=self.seed.package_digest,
            agent_dir=agent)
        self.assertEqual(one.source_digest, two.source_digest)
        self.assertNotEqual(one.package_digest, two.package_digest)
        self.assertNotEqual(one.components["agent/memory"], two.components["agent/memory"])
        self.assertIn("agent/skills", one.scope)
        projected = self.store.materialize(two.version_id, self.root / "package-view")
        self.assertEqual((projected / "agent" / "memory" / "lesson.md").read_text(),
                         "do not skip legitimate payments\n")

    def test_parent_digest_must_match_before_candidate_is_staged(self) -> None:
        with self.assertRaisesRegex(ValueError, "parent content digest"):
            self.store.save_candidate("forged-parent", self.source,
                parent_version_id=self.seed.version_id, parent_package_digest="0" * 64)
        self.assertFalse(self.store.worktree_path("forged-parent").exists())

    def test_embedded_agent_artifacts_have_explicit_scope(self) -> None:
        (self.source / "agent" / "prompts").mkdir(parents=True)
        (self.source / "agent" / "prompts" / "system.md").write_text("verify authorization")
        package = self.store.save_candidate("embedded-agent", self.source,
            parent_version_id=self.seed.version_id, parent_package_digest=self.seed.package_digest)
        self.assertIn("source/agent/prompts", package.scope)
        self.assertIn("source/agent", package.components)

    def test_promotion_requires_bound_passing_evaluation_and_active_parent(self) -> None:
        first = self.candidate("first")
        second = self.candidate("second", "SAFE = 'another fix'\n")
        for evaluation in ({"passed": True}, self.evaluation(first) | {"passed": False},
                           self.evaluation(first) | {"candidate_package_digest": "0" * 64}):
            with self.assertRaisesRegex(ValueError, "passing evaluation"):
                self.store.promote(first.version_id, evaluation=evaluation,
                                   expected_parent_digest=self.seed.package_digest)
        self.store.promote(first.version_id, evaluation=self.evaluation(first),
                           expected_parent_digest=self.seed.package_digest)
        with self.assertRaisesRegex(ValueError, "parent is stale"):
            self.store.promote(second.version_id, evaluation=self.evaluation(second),
                               expected_parent_digest=self.seed.package_digest)
        self.assertEqual(self.store.active(), first)

    def test_unaccepted_candidate_cannot_be_activated_through_rollback(self) -> None:
        candidate = self.candidate("failed")
        with self.assertRaisesRegex(ValueError, "never an accepted"):
            self.store.rollback(candidate.version_id, reason="try bypassing the gate")
        self.assertEqual(self.store.active(), self.seed)

    def test_projection_uses_committed_bytes_not_dirty_worktree_or_export_attributes(self) -> None:
        (self.source / ".gitattributes").write_text("secret.txt export-ignore\n")
        (self.source / "secret.txt").write_text("required artifact\n")
        candidate = self.store.save_candidate("with-attributes", self.source,
            parent_version_id=self.seed.version_id, parent_package_digest=self.seed.package_digest)
        (self.store.worktree_path(candidate.version_id) / "source" / "secret.txt").write_text("tampered\n")
        target = self.store.materialize_source(candidate.version_id, self.root / "view")
        self.assertEqual((target / "secret.txt").read_text(), "required artifact\n")
        self.assertFalse((target / ".git").exists())

    def test_windows_copy_fallback_uses_committed_bytes_not_candidate_worktree(self) -> None:
        target = self.root / "copy-fallback"
        target.mkdir()
        (target / "old.txt").write_text("old view\n")
        candidate = self.candidate("copy-fallback")
        (self.store.worktree_path(candidate.version_id) / "source" / "app" / "main.py").write_text("tampered\n")
        real_replace = os.replace

        def deny_view_replace(source, destination):
            if Path(destination) == target:
                raise _winerror5()
            return real_replace(source, destination)

        with patch("rsi4safety.arena.versions._is_windows", return_value=True), \
                patch.object(Path, "symlink_to", side_effect=_winerror1314()), \
                patch("rsi4safety.arena.versions.os.replace", side_effect=deny_view_replace):
            projected = self.store.materialize_source(candidate.version_id, target)
        self.assertEqual(projected, target)
        self.assertTrue(target.is_dir() and not target.is_symlink())
        self.assertEqual((target / "app" / "main.py").read_text(), "SAFE = True\n")
        self.assertFalse((target / "old.txt").exists())
        self.assertFalse((target / ".git").exists())
        self.assertEqual(self.store.active(), self.seed)
        backups = list((self.store.root / "legacy-projections").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "old.txt").read_text(), "old view\n")
        self.assertEqual(list(self.root.glob(".copy-fallback-*")), [])

    def test_promotion_recovery_and_rollback_update_source_without_stale_files(self) -> None:
        target = self.root / "live"
        (target / ".git").mkdir(parents=True)
        (target / ".git" / "do-not-delete").write_text("old history")
        self.store.materialize_source(self.seed.version_id, target)
        if _SYMLINKS_OK:
            self.assertTrue(target.is_symlink())
        else:  # Windows copy fallback: the projection is a real directory
            self.assertTrue(target.is_dir() and not target.is_symlink())
        self.assertTrue((target / "old.txt").exists())
        candidate = self.candidate("promoted")
        self.store.promote(candidate.version_id, evaluation=self.evaluation(candidate),
                           expected_parent_digest=self.seed.package_digest)
        # Simulate restart after ACTIVE changed but before the runtime projection.
        restored = VersionStore(self.store.root)
        self.assertEqual(restored.recover(target), candidate)
        self.assertFalse((target / "old.txt").exists())
        self.assertEqual((target / "app" / "main.py").read_text(), "SAFE = True\n")
        restored.rollback(self.seed.version_id, reason="independent final evaluation failed")
        restored.recover(target)
        self.assertTrue((target / "old.txt").exists())
        preserved = list((self.store.root / "legacy-projections").glob("*/.git/do-not-delete"))
        self.assertEqual(len(preserved), 1)

    def test_manifest_is_write_once_and_detects_tampering(self) -> None:
        candidate = self.candidate("immutable")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.store.save_candidate(candidate.version_id, self.source,
                parent_version_id=self.seed.version_id, parent_package_digest=self.seed.package_digest)
        path = self.store.manifests / f"{candidate.version_id}.json"
        value = json.loads(path.read_text())
        value["parent_package_digest"] = "0" * 64
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "manifest integrity"):
            self.store.get(candidate.version_id)

    @unittest.skipUnless(_SYMLINKS_OK, "symbolic links unavailable on this platform")
    def test_symlink_payload_is_rejected_without_reading_its_target(self) -> None:
        (self.source / "leak").symlink_to(self.root / "outside")
        with self.assertRaisesRegex(ValueError, "symlinks are forbidden"):
            self.store.save_candidate("linked", self.source,
                parent_version_id=self.seed.version_id, parent_package_digest=self.seed.package_digest)


if __name__ == "__main__":
    unittest.main()
