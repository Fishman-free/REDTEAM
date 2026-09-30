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


def _same_path(left: Path, right: Path) -> bool:
    """Compare Windows link targets after resolving short/extended path forms."""
    if os.name == "nt":
        return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))
    return left.resolve() == right.resolve()


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


class ProjectionRollbackTests(unittest.TestCase):
    """Fault injection needs neither Git worktrees nor Windows link privileges."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = VersionStore(self.root / "store")
        self.source = self.store.root / "projections" / "verified" / "source"
        (self.source / "app").mkdir(parents=True)
        (self.source / "app" / "main.py").write_text("new committed bytes\n")
        self.target = self.root / "live"
        (self.target / "app").mkdir(parents=True)
        (self.target / "app" / "main.py").write_text("old view\n")
        (self.target / "old.txt").write_text("preserve\n")
        windows = patch("rsi4safety.arena.versions._is_windows", return_value=True)
        windows.start()
        self.addCleanup(windows.stop)

    def copy_mode(self):
        return patch.object(Path, "symlink_to", side_effect=_winerror1314())

    def switch(self):
        with self.store._locked():
            return self.store._switch_projection(self.source, self.target)

    def assert_old_view(self):
        self.assertEqual((self.target / "app" / "main.py").read_text(), "old view\n")
        self.assertEqual((self.target / "old.txt").read_text(), "preserve\n")
        self.assertEqual((self.source / "app" / "main.py").read_text(), "new committed bytes\n")

    def assert_no_staging(self):
        self.assertEqual(list(self.root.glob(".live-*")), [])

    def make_old_link(self, *, dangling=False):
        original = self.root / "old-source"
        os.rename(self.target, original)
        if dangling:
            original = self.root / "missing-source"
        self.target.symlink_to(original, target_is_directory=True)
        return original

    def test_move_aside_failure_never_removes_old_view(self):
        real_rename = os.rename

        def deny_move(source, destination):
            if Path(source) == self.target:
                raise _winerror5()
            return real_rename(source, destination)

        with self.copy_mode(), patch("rsi4safety.arena.versions.os.rename", side_effect=deny_move):
            with self.assertRaises(PermissionError):
                self.switch()
        self.assert_old_view()
        self.assert_no_staging()
        self.assertEqual(list((self.store.root / "legacy-projections").iterdir()), [])

    def test_install_rename_failure_restores_old_view(self):
        real_rename = os.rename

        def deny_install(source, destination):
            if Path(source).suffix == ".copy" and Path(destination) == self.target:
                raise _winerror5()
            return real_rename(source, destination)

        with self.copy_mode(), \
                patch("rsi4safety.arena.versions.os.replace", side_effect=_winerror5()), \
                patch("rsi4safety.arena.versions.os.rename", side_effect=deny_install):
            with self.assertRaises(PermissionError):
                self.switch()
        self.assert_old_view()
        self.assert_no_staging()
        self.assertEqual(list((self.store.root / "legacy-projections").iterdir()), [])

    def test_partial_fallback_copy_never_exposes_half_tree_and_restores_old_view(self):
        real_copytree = shutil.copytree

        def fail_copy(source, destination, *args, **kwargs):
            if Path(destination).suffix == ".copy":
                self.assertFalse(self.target.exists())
                Path(destination).mkdir()
                (Path(destination) / "partial.txt").write_text("incomplete\n")
                raise OSError("copy interrupted")
            return real_copytree(source, destination, *args, **kwargs)

        with self.copy_mode(), \
                patch("rsi4safety.arena.versions.os.replace", side_effect=_winerror5()), \
                patch("rsi4safety.arena.versions.shutil.copytree", side_effect=fail_copy):
            with self.assertRaisesRegex(OSError, "copy interrupted"):
                self.switch()
        self.assert_old_view()
        self.assert_no_staging()
        self.assertFalse((self.target / "partial.txt").exists())

    def test_1314_partial_staging_failure_preserves_existing_view(self):
        def fail_copy(source, destination, **kwargs):
            Path(destination).mkdir()
            (Path(destination) / "partial.txt").write_text("incomplete\n")
            raise OSError("staging interrupted")

        with self.copy_mode(), patch("rsi4safety.arena.versions.shutil.copytree", side_effect=fail_copy):
            with self.assertRaisesRegex(OSError, "staging interrupted"):
                self.switch()
        self.assert_old_view()
        self.assert_no_staging()
        self.assertFalse((self.store.root / "legacy-projections").exists())

    def test_failed_initial_copy_does_not_leave_a_new_view(self):
        shutil.rmtree(self.target)

        def fail_copy(source, destination, **kwargs):
            Path(destination).mkdir()
            raise OSError("staging interrupted")

        with self.copy_mode(), patch("rsi4safety.arena.versions.shutil.copytree", side_effect=fail_copy):
            with self.assertRaisesRegex(OSError, "staging interrupted"):
                self.switch()
        self.assertFalse(self.target.exists())
        self.assert_no_staging()

    def test_restore_failure_retains_backup_and_reports_its_path(self):
        real_rename = os.rename

        def deny_restore(source, destination):
            if Path(source).parent.name == "legacy-projections":
                raise _winerror5()
            return real_rename(source, destination)

        with self.copy_mode(), \
                patch("rsi4safety.arena.versions.os.replace", side_effect=OSError("install denied")), \
                patch("rsi4safety.arena.versions.os.rename", side_effect=deny_restore):
            with self.assertRaisesRegex(RuntimeError, "restore failed") as caught:
                self.switch()
        backups = list((self.store.root / "legacy-projections").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertIn(str(backups[0]), str(caught.exception))
        self.assertEqual((backups[0] / "app" / "main.py").read_text(), "old view\n")
        self.assertFalse(self.target.exists())
        self.assert_no_staging()

    def test_unexpected_live_target_is_not_removed_or_merged_on_rollback(self):
        def occupy_then_deny(source, destination):
            self.target.mkdir()
            (self.target / "other-writer.txt").write_text("not ours\n")
            raise _winerror5()

        with self.copy_mode(), patch("rsi4safety.arena.versions.os.replace", side_effect=occupy_then_deny):
            with self.assertRaisesRegex(RuntimeError, "target remained occupied"):
                self.switch()
        self.assertEqual((self.target / "other-writer.txt").read_text(), "not ours\n")
        self.assertFalse((self.target / "app").exists())
        backups = list((self.store.root / "legacy-projections").iterdir())
        self.assertEqual((backups[0] / "app" / "main.py").read_text(), "old view\n")
        self.assert_no_staging()

    def test_non_windows_permission_failure_is_not_treated_as_windows_fallback(self):
        def stage_ordinary_copy(link, source, **kwargs):
            shutil.copytree(source, link)

        with patch("rsi4safety.arena.versions._is_windows", return_value=False), \
                patch.object(Path, "symlink_to", autospec=True, side_effect=stage_ordinary_copy), \
                patch("rsi4safety.arena.versions.os.replace", side_effect=_winerror5()):
            with self.assertRaises(PermissionError):
                self.switch()
        self.assert_old_view()
        self.assert_no_staging()

    @unittest.skipUnless(_SYMLINKS_OK, "directory symlink privilege unavailable")
    def test_actual_directory_symlink_replacement_does_not_follow_old_link(self):
        original = self.make_old_link()
        self.switch()
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(self.target.resolve(), self.source)
        self.assertEqual((original / "app" / "main.py").read_text(), "old view\n")
        self.assert_no_staging()

    @unittest.skipUnless(_SYMLINKS_OK, "directory symlink privilege unavailable")
    def test_actual_directory_symlink_move_failure_keeps_old_link(self):
        original = self.make_old_link()
        with patch("rsi4safety.arena.versions.os.rename", side_effect=_winerror5()):
            with self.assertRaises(PermissionError):
                self.switch()
        self.assertTrue(self.target.is_symlink())
        self.assertTrue(_same_path(self.target.resolve(), original))
        self.assert_old_view()
        self.assert_no_staging()

    @unittest.skipUnless(_SYMLINKS_OK, "directory symlink privilege unavailable")
    def test_actual_directory_symlink_install_failure_restores_old_link(self):
        original = self.make_old_link()
        real_rename = os.rename

        def deny_install(source, destination):
            if Path(source).suffix == ".copy" and Path(destination) == self.target:
                raise _winerror5()
            return real_rename(source, destination)

        with patch("rsi4safety.arena.versions.os.replace", side_effect=_winerror5()), \
                patch("rsi4safety.arena.versions.os.rename", side_effect=deny_install):
            with self.assertRaises(PermissionError):
                self.switch()
        self.assertTrue(self.target.is_symlink())
        self.assertTrue(_same_path(self.target.resolve(), original))
        self.assert_old_view()
        self.assert_no_staging()

    @unittest.skipUnless(_SYMLINKS_OK, "directory symlink privilege unavailable")
    def test_actual_directory_symlink_partial_copy_failure_restores_old_link(self):
        original = self.make_old_link()

        def fail_copy(source, destination, **kwargs):
            self.assertFalse(self.target.exists())
            Path(destination).mkdir()
            (Path(destination) / "partial.txt").write_text("incomplete\n")
            raise OSError("copy interrupted")

        with patch("rsi4safety.arena.versions.os.replace", side_effect=_winerror5()), \
                patch("rsi4safety.arena.versions.shutil.copytree", side_effect=fail_copy):
            with self.assertRaisesRegex(OSError, "copy interrupted"):
                self.switch()
        self.assertTrue(self.target.is_symlink())
        self.assertTrue(_same_path(self.target.resolve(), original))
        self.assert_old_view()
        self.assert_no_staging()

    @unittest.skipUnless(_SYMLINKS_OK, "directory symlink privilege unavailable")
    def test_actual_directory_symlink_winerror5_installs_complete_copy(self):
        original = self.make_old_link()
        with patch("rsi4safety.arena.versions.os.replace", side_effect=_winerror5()):
            self.switch()
        self.assertFalse(self.target.is_symlink())
        self.assertEqual((self.target / "app" / "main.py").read_text(), "new committed bytes\n")
        self.assertEqual((original / "app" / "main.py").read_text(), "old view\n")
        self.assert_no_staging()

    @unittest.skipUnless(_SYMLINKS_OK, "directory symlink privilege unavailable")
    def test_dangling_directory_symlink_is_restored_after_install_failure(self):
        self.make_old_link(dangling=True)
        original_link = os.readlink(self.target)
        with patch("rsi4safety.arena.versions.os.replace", side_effect=OSError("install denied")):
            with self.assertRaisesRegex(OSError, "install denied"):
                self.switch()
        self.assertTrue(self.target.is_symlink())
        self.assertFalse(self.target.exists())
        self.assertEqual(os.readlink(self.target), original_link)
        self.assert_no_staging()


if __name__ == "__main__":
    unittest.main()
