"""Best snapshot comparison and merge helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _operator_dir

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


def _snapshot_better(new: dict, old: dict | None) -> bool:
    """True if new snapshot is strictly better than old.

    Compare passed/total first, then tie-break on max_err (lower is better).
    """
    if old is None:
        return True
    new_passed = new.get("passed", 0)
    old_passed = old.get("passed", 0)
    if new_passed != old_passed:
        return new_passed > old_passed
    new_total = new.get("total", 0)
    old_total = old.get("total", 0)
    if new_total != old_total:
        # More total cases with same passed is worse (lower pass rate)
        return new_total < old_total
    new_err = new.get("max_err")
    old_err = old.get("max_err")
    if new_err is not None and old_err is not None:
        return new_err < old_err
    return False


def _has_valid_numeric_result(result: dict) -> bool:
    """Result has a numeric pass/total without VECTOR_ERROR/ENV_ERROR/SCHEMA_ERROR."""
    error_type = result.get("error_type", "")
    if error_type in ("VECTOR_ERROR", "ENV_ERROR", "SCHEMA_ERROR"):
        return False
    raw = (result.get("precision_result") or result.get("rc_result")
           or result.get("kl_result") or {})
    pr = _numeric_result({"precision_result": raw}, "")
    if isinstance(pr, dict) and pr.get("total", 0) > 0:
        return True
    # baseline schema
    if result.get("baseline_total_count", 0) > 0:
        return True
    return False


def _numeric_result(result: dict, phase: str) -> dict:
    """Normalize the numeric payload emitted by each full-suite phase.

    A5 agents historically emitted ``rc_result``/``kl_result`` while the
    framework only understood ``precision_result``.  Keep that wire format,
    but normalize it in the framework so checkpoint ownership stays here.
    """
    if phase == "baseline":
        raw = result.get("rc_result") or result.get("precision_result") or {}
        if not raw.get("total"):
            raw = result.get("kl_result") or raw
    elif phase == "kernel_debug":
        # kernel_debug 已合入 regression 职责：fixed 后批跑全量 KernelLaunch 并把
        # 汇总写进 ``kl_result``（全量高水位）——做快照比较时用它，缺省回退 per-case
        # 的 ``precision_result``（单 case 验证，无全量语义）。
        raw = result.get("kl_result") or result.get("precision_result") or {}
    else:
        raw = result.get("precision_result") or {}
    if not isinstance(raw, dict):
        return {}
    passed = raw.get("pass", raw.get("passed", 0))
    max_diff = raw.get("max_diff")
    if max_diff is None:
        max_diff = raw.get("mere", raw.get("mare"))
    return {
        "pass": passed,
        "total": raw.get("total", 0),
        "max_diff": max_diff,
        "failed_cases": raw.get("failed_cases", raw.get("failed", [])) or [],
    }


def _build_snapshot_from_result(result: dict, phase: str, round_num: int) -> dict | None:
    """Build a best_snapshot dict from a phase result JSON.

    Returns None for non-numeric error results.
    """
    error_type = result.get("error_type", "")
    if error_type in ("VECTOR_ERROR", "ENV_ERROR", "SCHEMA_ERROR"):
        return None
    pr = _numeric_result(result, phase)
    total = pr.get("total", 0)
    passed = pr.get("pass", 0)
    failed = pr.get("failed_cases", []) or []
    max_err = pr.get("max_diff")
    if not total and result.get("baseline_total_count"):
        total = result.get("baseline_total_count", 0)
        passed = result.get("baseline_passed_count", 0)
        failed = result.get("failed_cases", []) or []
        max_err = result.get("baseline_max_diff")
    if not total:
        # A candidate snapshot may be carried in the phase result, but direct
        # writes to checkpoint.json are never trusted.
        candidate = result.get("best_snapshot")
        return dict(candidate) if isinstance(candidate, dict) and candidate.get("total") else None
    return {
        "max_err": max_err,
        "commit": "",
        "passed": passed,
        "total": total,
        "failed_cases": failed,
        "updated_by": phase,
        "updated_round": round_num,
    }


def _merge_best_snapshot(cp: dict, result: dict, phase: str, round_num: int) -> bool:
    """Merge result into checkpoint["best_snapshot"] if it is strictly better.

    The framework reconstructs the candidate from the phase result.  Agents
    must not write ``checkpoint.json.best_snapshot`` directly.

    Returns True when best_snapshot is updated (new high water mark), so that
    callers can record ``best_commit`` only at a true improvement.
    """
    candidate = _build_snapshot_from_result(result, phase, round_num)
    if candidate is None:
        return False
    old = cp.get("best_snapshot")
    if old and not _snapshot_better(candidate, old):
        return False
    cp["best_snapshot"] = candidate
    return True


def _commit_candidate_phase(state: "State", cp: dict, phase: str, round_num: int) -> bool:
    """Commit a stage-verified source change without promoting it to best.

    Kernel/vector/op-plugin stages validate a local fix but do not own the
    full-suite high-water mark.  A candidate commit makes the work recoverable;
    baseline/kernel_debug（修复后全量 KL）later promote it after full-suite
    improvement.
    """
    return _commit_operator_tree(state, cp, phase, round_num, promote=False)


def _commit_modified_numeric_phase(state: "State", cp: dict, phase: str, round_num: int) -> bool:
    """Commit and promote a full-suite numeric improvement.

    Source-changing stages first create recoverable candidate commits.  A
    baseline/kernel_debug（修复后全量 KL 提升）improvement promotes the current
    operator-tree commit to both ``best_commit`` and ``best_snapshot.commit``.
    Commit failures are fail-closed and never turn the previous HEAD into an
    implicit best anchor.
    """
    return _commit_operator_tree(state, cp, phase, round_num, promote=True)


def _commit_operator_tree(
    state: "State", cp: dict, phase: str, round_num: int, *, promote: bool,
) -> bool:
    import subprocess
    from ascendc_devkit.infra.logger import Logger
    from ascendc_devkit.infra.repo_guard import RepoGuard
    op_dir = _operator_dir(state)
    if not op_dir:
        return False
    repo_root = (state.op_identity.repo_root
                 if state.op_identity and state.op_identity.repo_root
                 else op_dir)

    def _head() -> str:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL, timeout=15,
        ).strip()

    guard = RepoGuard()
    try:
        # is_clean excludes build artifacts (kernel_meta/build via ignore globs),
        # so a dirty verdict means real op_dir code changes (the agent's fix).
        if not guard.is_clean(repo_root, op_dir):
            # git add respects .gitignore; op_dir is the operator source dir so
            # this stages only operator code (op_kernel/op_host/op_plugin/op_api).
            added = guard._git(repo_root, "add", "--", str(op_dir))
            if not added or added.returncode != 0:
                raise RuntimeError("git add op_dir failed")
            # --only prevents unrelated pre-staged repository changes from
            # leaking into the framework-owned operator commit.
            commit = guard._git(
                repo_root, "commit", "-m",
                f"[precision_debug] {phase} round {round_num} fix",
                "--only", "--", str(op_dir),
            )
            if commit and commit.returncode == 0:
                Logger.info(f"A5 phase commit: {phase} r{round_num} "
                            f"committed op_dir fix")
            else:
                Logger.warn(f"A5 phase commit: git commit returned "
                            f"{commit.returncode if commit else 'None'}")
        head = _head()
        if not guard.is_clean(repo_root, op_dir):
            raise RuntimeError("op_dir remains dirty after phase commit")
        cp["candidate_commit"] = head
        if promote:
            cp["best_commit"] = head
            snapshot = cp.get("best_snapshot")
            if isinstance(snapshot, dict):
                snapshot["commit"] = head
        cp["commit_error"] = ""
        cp["rollback_safe"] = True
        cp["anchor_error"] = ""
        return True
    except Exception as e:
        Logger.warn(f"A5 phase commit: commit/probe failed ({e})")
        cp["commit_error"] = f"{phase} round {round_num}: {e}"
        cp["rollback_safe"] = False
        cp["anchor_error"] = cp["commit_error"]
        return False


def _extract_max_diff(result: dict) -> float | None:
    pr = result.get("precision_result") or {}
    return pr.get("max_diff")


def _extract_passed_count(result: dict) -> int:
    pr = result.get("precision_result") or {}
    return pr.get("pass", 0)


def _extract_total_count(result: dict) -> int:
    pr = result.get("precision_result") or {}
    return pr.get("total", 0)


def _extract_failed_cases(result: dict) -> list:
    pr = result.get("precision_result") or {}
    return pr.get("failed_cases", []) or []


def _extract_failed_count(result: dict) -> int:
    return len(_extract_failed_cases(result))


def _extract_crashed_count(result: dict) -> int:
    cases = _extract_failed_cases(result)
    return sum(1 for c in cases if c.get("max_err") == 999.0 or c.get("elapsed_ms", 0) < 0)


def _extract_real_max_err(result: dict) -> float | None:
    cases = _extract_failed_cases(result)
    errs = [c.get("max_err") for c in cases
            if c.get("max_err") != 999.0 and c.get("elapsed_ms", 0) >= 0]
    if not errs:
        return None
    return max(errs)
