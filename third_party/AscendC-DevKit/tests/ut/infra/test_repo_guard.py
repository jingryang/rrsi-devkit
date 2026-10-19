"""Unit tests for L7 infra RepoGuard (git snapshot/rollback, file backup).

UT does NOT depend on host global git config: fixtures set user.name/email
locally per-repo via ``git -c``-equivalent ``git config`` on the tmp repo.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ascendc_devkit.infra.repo_guard import RepoGuard


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)


def _has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_git(), reason="git not installed")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A tmp git repo with one committed file outside op_dir."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    # Local-only identity, never touches host global config.
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


class TestGitDetection:
    def test_is_git_repo_true(self, git_repo):
        assert RepoGuard().is_git_repo(git_repo) is True

    def test_is_git_repo_false_for_plain_dir(self, tmp_path):
        assert RepoGuard().is_git_repo(tmp_path) is False

    def test_disabled_guard_is_noop(self, git_repo):
        g = RepoGuard(enabled=False)
        assert g.is_git_repo(git_repo) is False
        assert g.create_baseline(git_repo, git_repo / "ops") == ""
        assert g.rollback(git_repo, git_repo / "ops", "deadbeef") is False


class TestIsClean:
    def test_clean_when_op_dir_committed(self, git_repo):
        op = git_repo / "ops" / "add"
        op.mkdir(parents=True)
        (op / "add.cpp").write_text("int x;\n", encoding="utf-8")
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-q", "-m", "add op")
        assert RepoGuard().is_clean(git_repo, op) is True

    def test_dirty_when_untracked_in_op_dir(self, git_repo):
        op = git_repo / "ops" / "add"
        op.mkdir(parents=True)
        (op / "add.cpp").write_text("int x;\n", encoding="utf-8")
        assert RepoGuard().is_clean(git_repo, op) is False

    def test_ignored_artifacts_do_not_mark_dirty(self, git_repo):
        op = git_repo / "ops" / "add"
        op.mkdir(parents=True)
        (op / "add.o").write_text("binary", encoding="utf-8")
        g = RepoGuard(ignore_globs=["*.o", "build/"])
        assert g.is_clean(git_repo, op) is True

# __APPEND_ROLLBACK_TESTS__

class TestBaselineAndRollbackGit:
    def test_baseline_is_head_sha(self, git_repo):
        head = _git(git_repo, "rev-parse", "HEAD").stdout.strip()
        ref = RepoGuard().create_baseline(git_repo, git_repo / "ops")
        assert ref == head

    def test_rollback_removes_new_untracked_files(self, git_repo):
        # new mode: op_dir created fresh, all files untracked.
        op = git_repo / "ops" / "add"
        g = RepoGuard()
        ref = g.create_baseline(git_repo, op)
        op.mkdir(parents=True)
        (op / "add.cpp").write_text("half-baked\n", encoding="utf-8")
        (op / "add.h").write_text("decl\n", encoding="utf-8")
        assert g.rollback(git_repo, op, ref) is True
        # clean -fd removes the untracked dir/files entirely.
        assert not (op / "add.cpp").exists()
        assert not (op / "add.h").exists()
        assert g.is_clean(git_repo, op) is True

    def test_rollback_restores_tracked_modifications(self, git_repo):
        # incremental mode: op file already committed, then modified.
        op = git_repo / "ops" / "add"
        op.mkdir(parents=True)
        f = op / "add.cpp"
        f.write_text("original\n", encoding="utf-8")
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-q", "-m", "add op")
        g = RepoGuard()
        ref = g.create_baseline(git_repo, op)
        f.write_text("BROKEN half-edit\n", encoding="utf-8")
        assert g.rollback(git_repo, op, ref) is True
        assert f.read_text(encoding="utf-8") == "original\n"

    def test_rollback_blast_radius_limited_to_op_dir(self, git_repo):
        # An unrelated untracked file outside op_dir must survive rollback.
        op = git_repo / "ops" / "add"
        g = RepoGuard()
        ref = g.create_baseline(git_repo, op)
        op.mkdir(parents=True)
        (op / "add.cpp").write_text("x\n", encoding="utf-8")
        outsider = git_repo / "ops" / "other" / "keep.txt"
        outsider.parent.mkdir(parents=True)
        outsider.write_text("do not delete\n", encoding="utf-8")
        assert g.rollback(git_repo, op, ref) is True
        assert not (op / "add.cpp").exists()
        assert outsider.exists()  # outside op_dir → untouched

    def test_changed_paths_reports_op_dir_changes(self, git_repo):
        op = git_repo / "ops" / "add"
        g = RepoGuard(ignore_globs=["*.o"])
        ref = g.create_baseline(git_repo, op)
        op.mkdir(parents=True)
        (op / "add.cpp").write_text("x\n", encoding="utf-8")
        (op / "add.o").write_text("obj\n", encoding="utf-8")  # ignored
        changed = g.changed_paths(git_repo, op, ref)
        assert "ops/add/add.cpp" in changed
        assert not any(p.endswith(".o") for p in changed)

    # —— step-109: deleted 集由 git 构造性派生（自报 deleted 标签通路已死）——

    def test_deleted_paths_from_git_filter_d(self, git_repo):
        """基线含 gone.cpp、工作区删掉 + 新增另一文件 → deleted_paths 精确只含
        删除集（repo-relative，与 changed_paths 同款坐标）。"""
        op = git_repo / "ops" / "add"
        op.mkdir(parents=True)
        (op / "gone.cpp").write_text("old\n", encoding="utf-8")
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-q", "-m", "base")
        g = RepoGuard()
        ref = g.create_baseline(git_repo, op)
        (op / "gone.cpp").unlink()
        (op / "new.cpp").write_text("n\n", encoding="utf-8")
        assert g.deleted_paths(git_repo, op, ref) == ["ops/add/gone.cpp"]

    def test_deleted_paths_empty_when_none_deleted(self, git_repo):
        op = git_repo / "ops" / "add"
        op.mkdir(parents=True)
        (op / "a.cpp").write_text("a\n", encoding="utf-8")
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-q", "-m", "base")
        g = RepoGuard()
        ref = g.create_baseline(git_repo, op)
        (op / "b.cpp").write_text("b\n", encoding="utf-8")  # 只新增，无删除
        assert g.deleted_paths(git_repo, op, ref) == []

    def test_deleted_paths_subset_of_changed(self, git_repo):
        """一致性：删除集恒为 changed_paths（diff ∪ untracked）的子集。"""
        op = git_repo / "ops" / "add"
        op.mkdir(parents=True)
        (op / "x.cpp").write_text("x\n", encoding="utf-8")
        (op / "y.cpp").write_text("y\n", encoding="utf-8")
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-q", "-m", "base")
        g = RepoGuard()
        ref = g.create_baseline(git_repo, op)
        (op / "x.cpp").unlink()
        (op / "x.cpp").write_text("x2\n", encoding="utf-8")  # 修改
        (op / "y.cpp").unlink()                              # 删除
        deleted = set(g.deleted_paths(git_repo, op, ref))
        changed = set(g.changed_paths(git_repo, op, ref))
        assert deleted == {"ops/add/y.cpp"}
        assert deleted <= changed

    def test_git_mv_deleted_reports_old_path(self, git_repo):
        """M10：``git mv`` 后 deleted_paths 必含旧路径——rename 记法（R）下
        ``--diff-filter=D`` 会漏报旧路径删除；``--no-renames`` 让 mv = D旧 + A新。"""
        op = git_repo / "ops" / "add"
        op.mkdir(parents=True)
        (op / "add.cpp").write_text("x\n", encoding="utf-8")
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-q", "-m", "base")
        g = RepoGuard()
        ref = g.create_baseline(git_repo, op)
        _git(git_repo, "mv", "ops/add/add.cpp", "ops/add/renamed.cpp")
        assert g.deleted_paths(git_repo, op, ref) == ["ops/add/add.cpp"]
        changed = set(g.changed_paths(git_repo, op, ref))
        assert {"ops/add/add.cpp", "ops/add/renamed.cpp"} <= changed

    def test_git_error_warns_and_returns_empty(self, git_repo, monkeypatch):
        """M10：git rc≠0（如坏 baseline ref）WARN 带 stderr 摘要后返回空——
        不静默吞（空返回与「真无变更」不可区分，必须留观测信号）。"""
        import ascendc_devkit.infra.repo_guard as rg
        warned: list[str] = []
        monkeypatch.setattr(
            rg.Logger, "warn", staticmethod(lambda msg: warned.append(msg)))
        g = RepoGuard()
        assert g.deleted_paths(git_repo, git_repo, "deadbeef") == []
        assert g.changed_paths(git_repo, git_repo, "deadbeef") == []
        assert any("failed" in w for w in warned), warned
        assert any("rc=" in w for w in warned)  # 退出码进 WARN
        assert any("deadbeef" in w for w in warned)  # stderr 摘要进 WARN


class TestFileBackupFallback:
    def test_baseline_and_restore_for_non_git_dir(self, tmp_path):
        backup = tmp_path / "backups"
        op = tmp_path / "plain" / "ops" / "add"
        op.mkdir(parents=True)
        (op / "add.cpp").write_text("original\n", encoding="utf-8")
        g = RepoGuard(backup_root=backup)
        ref = g.create_baseline(tmp_path / "plain", op)
        assert ref.startswith("filebackup:")
        # mutate then restore
        (op / "add.cpp").write_text("BROKEN\n", encoding="utf-8")
        (op / "extra.cpp").write_text("junk\n", encoding="utf-8")
        assert g.rollback(tmp_path / "plain", op, ref) is True
        assert (op / "add.cpp").read_text(encoding="utf-8") == "original\n"
        assert not (op / "extra.cpp").exists()

    def test_baseline_for_nonexistent_op_dir_new_mode(self, tmp_path):
        backup = tmp_path / "backups"
        op = tmp_path / "plain" / "ops" / "newop"  # not yet created
        g = RepoGuard(backup_root=backup)
        ref = g.create_baseline(tmp_path / "plain", op)
        assert ref.startswith("filebackup:")
        op.mkdir(parents=True)
        (op / "f.cpp").write_text("half\n", encoding="utf-8")
        assert g.rollback(tmp_path / "plain", op, ref) is True
        assert not (op / "f.cpp").exists()  # restored to empty baseline
