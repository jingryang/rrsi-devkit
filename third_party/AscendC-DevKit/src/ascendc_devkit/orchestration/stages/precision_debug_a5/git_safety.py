"""Git safety helpers for A5 precision_debug (entry snapshot + rollback anchor)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _operator_dir

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


def _profile_commit_scope(state: "State") -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (include, exclude) globs from the profile's precision_debug_commit."""
    profile = getattr(state, "profile", None)
    scope = (getattr(profile, "precision_debug_commit", None)
             if profile is not None else None)
    include = tuple(getattr(scope, "include", ()) or ()) if scope else ()
    exclude = tuple(getattr(scope, "exclude", ()) or ()) if scope else ()
    return include, exclude


def _matches_globs(relpath: str, globs: tuple[str, ...]) -> bool:
    """fnmatch against the profile globs (relative to the operator dir).

    ``fnmatch`` does not cross ``/``, so a ``*.bak`` pattern would not match
    ``op_kernel/foo.bak``. Match BOTH the full relpath and the basename so
    extension/name patterns like ``*.bak`` / ``*.log`` apply at any depth.
    """
    import fnmatch
    from pathlib import PurePosixPath
    base = PurePosixPath(relpath).name
    for g in globs:
        if fnmatch.fnmatch(relpath, g) or fnmatch.fnmatch(base, g):
            return True
        if fnmatch.fnmatch(relpath, g.rstrip("/") + "/*"):
            return True
    return False


def _allowed_operator_files(state: "State", repo_root: Path, op_dir: Path) -> list[str]:
    """Enumerate op_dir working-tree changes and select those allowed to commit.

    Uses ``git status --porcelain -- op_dir`` so untracked AND modified files
    under op_dir are both considered. Selection:
      - profile ``include`` (fnmatch, rel to op_dir) when non-empty, else all;
      - profile ``exclude`` narrows;
      - non-overridable debug-output exclusions always drop logs, backups,
        plain-text captures, debug scripts and precision-debug artifact dirs.

    Returns repo-root-relative paths safe to pass to ``git add``.
    """
    import fnmatch
    from pathlib import PurePosixPath
    rel_op = _op_dir_rel(repo_root, op_dir)
    include, exclude = _profile_commit_scope(state)
    _DEBUG_EXCLUDES = ("*.log", "*.bak", "*.txt", "*_debug*.py",
                       ".precision-fix", ".ascend-debug")
    # 构建清单是基础设施,不是调试文本:``*.txt`` 是机制代理(调试文本按
    # 扩展名拦截),对 CMakeLists.txt 这一精确文件名豁免——快照缺了它,
    # 回滚 checkout+clean 会物理删除该未跟踪文件,其后所有重建死于
    # cmake "does not contain a CMakeLists.txt file"。
    _BUILD_MANIFEST_BASENAMES = ("CMakeLists.txt",)
    status = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain", "-z",
         "--untracked-files=all", "--", str(op_dir)],
        capture_output=True, text=True, timeout=30,
    )
    if status.returncode != 0:
        return []
    allowed: list[str] = []
    for entry in status.stdout.split("\0"):
        if not entry:
            continue
        relpath = entry[3:] if len(entry) >= 3 else entry
        if not relpath.startswith(rel_op + "/"):
            continue
        rel_to_op = relpath[len(rel_op) + 1:]
        if include and not _matches_globs(rel_to_op, include):
            continue
        if exclude and _matches_globs(rel_to_op, exclude):
            continue
        if (PurePosixPath(rel_to_op).name not in _BUILD_MANIFEST_BASENAMES
                and _matches_globs(rel_to_op, _DEBUG_EXCLUDES)):
            continue
        allowed.append(relpath)
    return allowed


def _operator_pathspecs(state: "State", repo_root: Path, op_dir: Path) -> list[str]:
    """Operator commit pathspec driven by the profile's ``precision_debug_commit``.

    The profile whitelist (``PrecisionDebugCommitScope.include``) selects which
    production codegen files under ``op_dir`` get committed; ``exclude`` narrows
    it further. Patterns are matched relative to the operator directory (67ef7ce2
    semantics). Debug outputs, logs, backups, caches and compiled artifacts must
    NOT be committed — they stay in the working tree so converge/teardown can
    clean them independently of source (test_precision_debug_stage
    test_first_run_commits_untracked_codegen_products).

    Uses ``git status`` enumeration + fnmatch filtering (not raw git pathspec
    globs) because git 2.34 pathspec exclude patterns interfere with include
    ``**`` matching when both are present — the reliable approach is to stage
    the exact allowed file paths.
    """
    return _allowed_operator_files(state, repo_root, op_dir)


def ensure_entry_snapshot(state: "State", *, record_anchor: bool = False) -> str | None:
    """On first entry, snapshot all codegen products in op_dir via a single commit.

    This is the A5 equivalent of A3 ``_entry_commit_codegen``. It is idempotent:
    if checkpoint.json already exists, it does nothing.
    """
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path, _operator_dir,
    )
    ctrl = _control_path(state)
    first_entry = ctrl is None or not ctrl.exists()
    if not first_entry and not record_anchor:
        return None
    op_dir = _operator_dir(state)
    if op_dir is None:
        return None
    repo_root = (state.op_identity.repo_root
                 if state.op_identity and state.op_identity.repo_root
                 else op_dir)
    from ascendc_devkit.infra.logger import Logger
    try:
        inside = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=15,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        if first_entry:
            pathspecs = _operator_pathspecs(state, repo_root, op_dir)
            add = subprocess.run(
                ["git", "-C", str(repo_root), "add", "--", *pathspecs],
                capture_output=True, text=True, timeout=60,
            )
            if add.returncode != 0:
                Logger.warn(f"A5 entry commit: git add failed ({add.stderr.strip()[:160]})")
                return None
            commit_cmd = [
                "git", "-C", str(repo_root), "commit",
                "-m", "A5 precision_debug entry: snapshot codegen products",
                "--", *pathspecs,
            ]
            # Keep the legacy A3 helper semantics unchanged.  A5 uses --only
            # so unrelated pre-staged repository changes are never captured.
            if record_anchor:
                commit_cmd = [
                    "git", "-C", str(repo_root), "commit",
                    "-m", "A5 precision_debug entry: snapshot codegen products",
                    "--only", "--", *pathspecs,
                ]
            commit = subprocess.run(
                commit_cmd,
                capture_output=True, text=True, timeout=60,
            )
            if commit.returncode == 0:
                Logger.action("A5 precision_debug_entry_commit",
                              "snapshot codegen products at op_dir")
            else:
                leftover = subprocess.run(
                    ["git", "-C", str(repo_root), "status", "--porcelain", "--", str(op_dir)],
                    capture_output=True, text=True, timeout=30,
                )
                dirty = [ln for ln in leftover.stdout.splitlines() if ln.strip()]
                if not dirty:
                    Logger.warn("A5 entry commit: nothing-to-commit (op_dir clean)")
                else:
                    Logger.error(f"A5 entry commit FAILED: op_dir still dirty ({len(dirty)} changes)")
                    if record_anchor:
                        _record_anchor_failure(state, f"entry commit left {len(dirty)} dirty changes")
                    return None
        head = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL, timeout=15,
        ).strip()
        if record_anchor:
            _record_entry_anchor(state, head)
        return head
    except Exception as e:
        Logger.warn(f"A5 entry commit failed ({e}) — continuing")
        if record_anchor:
            _record_anchor_failure(state, str(e))
        return None


def _record_entry_anchor(state: "State", head: str) -> None:
    if not head:
        return
    from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
        _load_a5_checkpoint, _save_a5_checkpoint,
    )
    cp = _load_a5_checkpoint(state)
    cp.setdefault("initial_commit", head)
    cp.setdefault("best_commit", head)
    if not cp.get("initial_commit"):
        cp["initial_commit"] = head
    if not cp.get("best_commit"):
        cp["best_commit"] = head
    cp["rollback_safe"] = True
    cp["anchor_error"] = ""
    _save_a5_checkpoint(state, cp)


def _record_anchor_failure(state: "State", reason: str) -> None:
    from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
        _load_a5_checkpoint, _save_a5_checkpoint,
    )
    cp = _load_a5_checkpoint(state)
    cp["rollback_safe"] = False
    cp["anchor_error"] = reason
    _save_a5_checkpoint(state, cp)


def validate_commit_for_operator(state: "State", commit: str) -> tuple[bool, str]:
    """Validate that ``commit`` contains operator source files under op_dir."""
    op_dir = _operator_dir(state)
    if not op_dir:
        return False, "no op_dir"
    repo_root = (state.op_identity.repo_root
                 if state.op_identity and state.op_identity.repo_root
                 else op_dir)
    try:
        files = subprocess.check_output(
            ["git", "-C", str(repo_root), "ls-tree", "-r", "--name-only", commit],
            text=True, stderr=subprocess.DEVNULL, timeout=15,
        )
    except Exception as e:
        return False, f"git ls-tree failed: {e}"
    rel = _op_dir_rel(repo_root, op_dir)
    has_source = any(line.startswith(rel) for line in files.splitlines())
    if not has_source:
        return False, f"commit {commit[:12]} contains no operator source under {rel}"
    return True, ""


def validated_rollback_anchor(state: "State", cp: dict) -> tuple[str | None, str]:
    """Return the validated best_commit to roll back to, or None + reason."""
    op_dir = _operator_dir(state)
    if not op_dir:
        return None, "no op_dir"
    repo_root = (state.op_identity.repo_root
                 if state.op_identity and state.op_identity.repo_root
                 else op_dir)
    if not cp.get("rollback_safe"):
        return None, f"rollback_safe is False; anchor_error={cp.get('anchor_error', '')}"
    initial = cp.get("initial_commit")
    best = cp.get("best_commit")
    if not best:
        return None, "best_commit empty"
    try:
        head = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL, timeout=15,
        ).strip()
    except Exception as e:
        return None, f"HEAD probe failed: {e}"
    if initial and head != initial:
        return None, f"initial_commit {initial[:12]} is not HEAD {head[:12]}"
    ok, reason = validate_commit_for_operator(state, best)
    if not ok:
        return None, reason
    return best, ""


def _op_dir_rel(repo_root: Path, op_dir: Path) -> str:
    try:
        return str(op_dir.relative_to(repo_root))
    except ValueError:
        return str(op_dir)
