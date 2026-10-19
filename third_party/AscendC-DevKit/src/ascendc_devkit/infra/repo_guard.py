"""L7 Infrastructure — git workspace snapshot/rollback for in-repo codegen.

Plan-A safety net (replaces the old output-dir isolation). Establishes a
baseline before the first write into the operator repo, then rolls the
operator directory back to that baseline on hard failure.

Safety (git_safety) — hard constraints, also enforced by callers:
  * All destructive operations are scoped to ``op_dir`` only.
  * NEVER ``git reset --hard`` the whole repo.
  * NEVER touch git config or user branches.
  * rollback blast radius == ``op_dir``.

Degradation: when git is unavailable / not a git repo, falls back to a
plain file backup of ``op_dir``. When ``enabled=False`` every method is a
no-op so unit tests need not depend on a real git installation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from fnmatch import fnmatch
from pathlib import Path

from ascendc_devkit.infra.logger import Logger

_GIT_TIMEOUT = 30
_FILE_BACKUP_PREFIX = "filebackup:"

# Synthetic committer identity for framework-internal commits (precision_debug's
# git-based rollback anchoring) in bare CI/container envs that have no global
# user.name/user.email. Supplied ONLY as a conditional fallback via GIT_* env
# vars — never written to git config (git_safety constraint), never overriding a
# real developer's identity. Clearly-synthetic so the provenance is obvious in
# `git log`.
_FALLBACK_COMMITTER_NAME = "AscendC-DevKit precision_debug"
_FALLBACK_COMMITTER_EMAIL = "devkit@ascendc-devkit.local"


def git_commit_identity_env(work_dir: Path | str | None = None,
                            base_env: dict | None = None) -> dict[str, str]:
    """Return GIT_* env overrides supplying a synthetic committer identity ONLY
    when git cannot otherwise resolve one; ``{}`` when an identity already exists.

    ``git commit`` stamps a committer/author into the commit object and REFUSES
    (rc=128 "Author identity unknown") when neither config nor env provides one.
    Bare CI/container environments (DevKit's target, §1.7 self-closure) often
    lack a global identity — precision_debug's git-based rollback anchoring would
    then fail every commit AND leave ``best_commit`` stale, making the exit-time
    ``git clean -fd`` destroy the codegen it was meant to preserve.

    Probing with ``git var GIT_COMMITTER_IDENT`` under ``base_env`` replicates
    exactly what ``git commit`` will resolve (config + env, plus repo-local config
    when ``work_dir`` is inside a repo). rc==0 → an identity exists → return ``{}``
    so a real developer keeps their real author (GIT_* env would otherwise take
    precedence over their config). rc!=0 (or git missing/timeout, a fail-safe
    toward supplying one) → inject a clearly-synthetic framework identity so the
    commit succeeds.

    No git config is ever written; the returned vars are merged into a subprocess
    env by the caller, scoping the fallback to that subprocess tree only.
    """
    env = dict(base_env) if base_env is not None else dict(os.environ)
    args = ["git"]
    if work_dir is not None:
        args += ["-C", str(work_dir)]
    args += ["var", "GIT_COMMITTER_IDENT"]
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=_GIT_TIMEOUT, env=env)
        if r.returncode == 0 and r.stdout.strip():
            return {}
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass  # git unavailable → supplying a fallback is harmless and safer
    return {
        "GIT_AUTHOR_NAME": _FALLBACK_COMMITTER_NAME,
        "GIT_AUTHOR_EMAIL": _FALLBACK_COMMITTER_EMAIL,
        "GIT_COMMITTER_NAME": _FALLBACK_COMMITTER_NAME,
        "GIT_COMMITTER_EMAIL": _FALLBACK_COMMITTER_EMAIL,
    }


class RepoGuard:
    """Snapshot + rollback guard scoped to a single operator directory."""

    def __init__(self, backup_root: Path | str | None = None,
                 ignore_globs: list[str] | None = None,
                 enabled: bool = True):
        self._backup_root = Path(backup_root) if backup_root else None
        self._ignore_globs = list(ignore_globs or [])
        self._enabled = enabled

    # —— internal helpers ——

    def _git(self, repo_root: Path | str, *args: str):
        """Run a git subprocess with list args (no shell → no injection).

        Returns the CompletedProcess, or None when git is unavailable /
        times out (caller degrades gracefully, never raises).
        """
        try:
            return subprocess.run(
                ["git", "-C", str(repo_root), *args],
                capture_output=True, text=True, timeout=_GIT_TIMEOUT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            Logger.warn(f"git command unavailable/failed ({args[:1]}): {e}")
            return None

    def _is_ignored(self, rel_path: str) -> bool:
        """Match a repo-relative path against configured build-artifact globs."""
        rp = rel_path.replace("\\", "/").strip().strip('"')
        for pat in self._ignore_globs:
            p = pat.rstrip("/")
            if fnmatch(rp, p) or fnmatch(rp, p + "/*") \
                    or any(fnmatch(part, p) for part in rp.split("/")):
                return True
        return False

# __REPO_GUARD_APPEND__

    # —— public API ——

    def is_git_repo(self, repo_root: Path | str) -> bool:
        if not self._enabled:
            return False
        cp = self._git(repo_root, "rev-parse", "--is-inside-work-tree")
        return bool(cp and cp.returncode == 0 and cp.stdout.strip() == "true")

    def is_clean(self, repo_root: Path | str, op_dir: Path | str) -> bool:
        """True when ``op_dir`` has no tracked changes and no untracked files.

        Build artifacts matching ignore globs are excluded from the check so
        a prior build does not falsely flag the directory as dirty.
        """
        if not self._enabled or not self.is_git_repo(repo_root):
            return True  # cannot assess → treat as clean (degraded)
        # -uall expands untracked directories to individual files so the
        # ignore-glob check sees real filenames (git otherwise collapses an
        # all-untracked dir to a single "<dir>/" entry).
        cp = self._git(repo_root, "status", "--porcelain", "-uall",
                       "--", str(op_dir))
        if cp is None or cp.returncode != 0:
            return True
        for line in cp.stdout.splitlines():
            rel = line[3:].strip() if len(line) > 3 else line.strip()
            if rel and not self._is_ignored(rel):
                return False
        return True

    @staticmethod
    def is_git_baseline(baseline: str) -> bool:
        """M3（review 整改）：基线是否为 git 真值。

        ``filebackup:`` 前缀是 repo_guard 对非 git 环境的降级基线——
        changed_paths/deleted_paths 对其恒空是「git 不适用」而非「零改动」；
        消费方（产物收集）据此走降级 scan，而非把整轮产物静默折叠为空。"""
        return bool(baseline) and not baseline.startswith(_FILE_BACKUP_PREFIX)

    def create_baseline(self, repo_root: Path | str, op_dir: Path | str) -> str:
        """Establish the pre-write baseline; returns an opaque baseline ref.

        git repo  → current HEAD sha (validity guaranteed by the caller's
                    pre-flight ``is_clean`` check, per decision D4).
        non-git   → copy ``op_dir`` into ``backup_root`` and return a
                    ``filebackup:<path>`` token.
        """
        if not self._enabled:
            return ""
        if self.is_git_repo(repo_root):
            cp = self._git(repo_root, "rev-parse", "HEAD")
            if cp and cp.returncode == 0:
                ref = cp.stdout.strip()
                Logger.action("repo_baseline", f"HEAD={ref[:12]} (op_dir={op_dir})")
                return ref
            Logger.warn("rev-parse HEAD failed; falling back to file backup")
        return self._file_backup(op_dir)

    def _file_backup(self, op_dir: Path | str) -> str:
        op_dir = Path(op_dir)
        if not self._backup_root:
            Logger.warn("No backup_root configured; baseline unavailable (non-git)")
            return ""
        dest = self._backup_root / op_dir.name
        try:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            if op_dir.exists():
                shutil.copytree(op_dir, dest)
            else:
                dest.mkdir(parents=True, exist_ok=True)  # op_dir not yet created (new mode)
            Logger.action("repo_baseline", f"file backup → {dest}")
            return f"{_FILE_BACKUP_PREFIX}{dest}"
        except Exception as e:
            Logger.warn(f"File backup failed: {e}")
            return ""

# __REPO_GUARD_APPEND2__

    def deleted_paths(self, repo_root: Path | str, op_dir: Path | str,
                      baseline_ref: str) -> list[str]:
        """Repo-relative paths DELETED under ``op_dir`` since the baseline
        (step-109: ``git diff --name-only --diff-filter=D``).

        自报 deleted 标签通路删除后的唯一删除信息来源——由 git 构造性派生，
        不依赖 LLM 纪律（§2.9）。守卫与 ``changed_paths`` 同款（enabled/baseline/
        git-repo 检查、filebackup 基线不适用）；恒为 ``changed_paths`` 的子集。
        ``--no-renames``：rename 记法下 git 把 ``git mv`` 记作 R（非 D），旧路径
        会从删除集漏报；关掉 rename 检测后 mv = D旧 + A新，删除标签完整。
        git 失败（rc≠0）WARN 留痕后返回空——不静默吞（§1.2 可诊断）。
        """
        if not self._enabled or not baseline_ref \
                or baseline_ref.startswith(_FILE_BACKUP_PREFIX):
            return []
        if not self.is_git_repo(repo_root):
            return []
        cp = self._git(repo_root, "diff", "--name-only", "--diff-filter=D",
                       "--no-renames", baseline_ref, "--", str(op_dir))
        if not cp or cp.returncode != 0:
            if cp is not None:
                Logger.warn(
                    f"deleted_paths git diff failed (rc={cp.returncode}): "
                    f"{(cp.stderr or '').strip()[:300]}")
            return []
        return sorted(l.strip() for l in cp.stdout.splitlines() if l.strip())

    def changed_paths(self, repo_root: Path | str, op_dir: Path | str,
                      baseline_ref: str) -> list[str]:
        """Repo-relative paths changed under ``op_dir`` since the baseline.

        Union of tracked diff (``git diff --name-only`` + ``--diff-filter``
        for deletions are included by default) and untracked files, scoped
        to ``op_dir`` and excluding ignored build artifacts. ``--no-renames``
        keeps a ``git mv`` visible as BOTH old (D) and new (A) paths — with
        rename detection on, the old path would drop out of the diff.
        git 失败（rc≠0）WARN 留痕后按空集继续——不静默吞（§1.2 可诊断）。
        """
        if not self._enabled or not baseline_ref \
                or baseline_ref.startswith(_FILE_BACKUP_PREFIX):
            return []
        if not self.is_git_repo(repo_root):
            return []
        out: set[str] = set()
        diff = self._git(repo_root, "diff", "--name-only", "--no-renames",
                         baseline_ref, "--", str(op_dir))
        if diff is not None and diff.returncode != 0:
            Logger.warn(
                f"changed_paths git diff failed (rc={diff.returncode}): "
                f"{(diff.stderr or '').strip()[:300]}")
        elif diff:
            out.update(l.strip() for l in diff.stdout.splitlines() if l.strip())
        untracked = self._git(repo_root, "ls-files", "--others",
                              "--exclude-standard", "--", str(op_dir))
        if untracked is not None and untracked.returncode != 0:
            Logger.warn(
                f"changed_paths git ls-files failed (rc={untracked.returncode}): "
                f"{(untracked.stderr or '').strip()[:300]}")
        elif untracked:
            out.update(l.strip() for l in untracked.stdout.splitlines() if l.strip())
        return sorted(p for p in out if not self._is_ignored(p))

    def rollback(self, repo_root: Path | str, op_dir: Path | str,
                 baseline_ref: str) -> bool:
        """Restore ``op_dir`` to the baseline. Blast radius == op_dir only.

        git repo → ``git checkout <ref> -- op_dir`` + ``git clean -fd op_dir``
        non-git  → restore from the file backup captured at baseline time.

        Returns True on success. NEVER touches paths outside ``op_dir`` and
        NEVER runs ``reset --hard`` on the whole repo (decision D4 / R1).
        """
        if not self._enabled or not baseline_ref:
            Logger.warn("rollback skipped: no baseline ref")
            return False
        if baseline_ref.startswith(_FILE_BACKUP_PREFIX):
            return self._file_restore(op_dir, baseline_ref)
        if not self.is_git_repo(repo_root):
            Logger.warn("rollback skipped: not a git repo and no file backup")
            return False
        # §step-124: baseline_ref 必须是合法 git ref。{sha12}-dirty-N 类溯源标签
        # 不是 ref——旧实现里 ls-tree 对其 rc!=0 被当「无 tracked 内容」跳过
        # checkout、clean 照跑，最后打出假 "restored to {ref}" 成功日志（实为
        # no-op）。拒之并响亮报错，交调用方走既有 fallback（§1.2 可诊断）。
        verified = self._git(repo_root, "rev-parse", "--verify", "-q",
                             baseline_ref)
        if not (verified is not None and verified.returncode == 0
                and (verified.stdout or "").strip()):
            Logger.error(
                f"rollback refused: baseline_ref {baseline_ref!r} 不是合法 git "
                f"ref（如 {{sha}}-dirty-N 溯源标签）— op_dir 未还原")
            return False
        # Step 1 (incremental): restore tracked files modified since baseline.
        # Only run checkout when op_dir actually had tracked content at the
        # baseline ref — otherwise (new mode) checkout errors with
        # "pathspec did not match", which is harmless, not a rollback failure.
        had_tracked = self._git(repo_root, "ls-tree", "-r", "--name-only",
                                baseline_ref, "--", str(op_dir))
        co_ok = True
        if had_tracked and had_tracked.returncode == 0 and had_tracked.stdout.strip():
            co = self._git(repo_root, "checkout", baseline_ref, "--", str(op_dir))
            co_ok = bool(co and co.returncode == 0)
        # Step 2 (new): remove untracked files/dirs the run added under op_dir.
        cl = self._git(repo_root, "clean", "-fd", "--", str(op_dir))
        ok = bool(co_ok and cl and cl.returncode == 0)
        if ok:
            Logger.action("repo_rollback",
                          f"op_dir restored to {baseline_ref[:12]} (checkout+clean)")
        else:
            Logger.error(f"rollback failed for {op_dir} "
                         f"(checkout_ok={co_ok}, "
                         f"clean rc={getattr(cl, 'returncode', None)})")
        return ok

    def _file_restore(self, op_dir: Path | str, baseline_ref: str) -> bool:
        op_dir = Path(op_dir)
        src = Path(baseline_ref[len(_FILE_BACKUP_PREFIX):])
        if not src.exists():
            Logger.error(f"file backup missing: {src}")
            return False
        try:
            if op_dir.exists():
                shutil.rmtree(op_dir, ignore_errors=True)
            shutil.copytree(src, op_dir)
            Logger.action("repo_rollback", f"op_dir restored from backup {src}")
            return True
        except Exception as e:
            Logger.error(f"file restore failed: {e}")
            return False
