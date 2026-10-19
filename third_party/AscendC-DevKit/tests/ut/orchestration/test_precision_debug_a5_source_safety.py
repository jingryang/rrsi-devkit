"""A5-only regression tests for source preservation and relay ownership."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ascendc_devkit.domain.operator import OperatorIdentity, OperatorSpec
from ascendc_devkit.domain.repository import (
    PrecisionDebugCommitScope,
    RepositoryProfile,
)
from ascendc_devkit.orchestration.kernel.state import State


class _Workspace:
    def __init__(self, root: Path):
        self._root = root

    @property
    def artifacts(self) -> Path:
        return self._root / "artifacts"

    @property
    def dir(self) -> Path:
        return self._root


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path, *, with_source: bool = True):
    repo = tmp_path / "repo"
    op_dir = repo / "ops" / "gather"
    op_dir.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "precision-debug@test.invalid")
    _git(repo, "config", "user.name", "Precision Debug Test")
    (repo / "README.md").write_text("repo\n", encoding="utf-8")
    if with_source:
        (op_dir / "kernel.cpp").write_text("// initial\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo, op_dir, _git(repo, "rev-parse", "HEAD")


def _state(
    tmp_path: Path, repo: Path, op_dir: Path,
    *, profile: RepositoryProfile | None = None,
) -> State:
    identity = OperatorIdentity(
        spec=OperatorSpec(name="gather"), repo_root=repo, op_dir=op_dir)
    return State.empty().with_updates(
        op_identity=identity,
        design_target_chip="A5",
        profile=profile,
    ).with_field("_workspace", _Workspace(tmp_path))


def _checkpoint_path(tmp_path: Path) -> Path:
    return tmp_path / "artifacts" / "precision_debug_a5" / "checkpoint.json"


@pytest.mark.parametrize("new_name", ["tiling.cpp", "op_plugin.cpp"])
def test_a5_first_spawn_commits_untracked_codegen_and_records_anchor(
        tmp_path, new_name):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        BaselineSubstage, validate_commit_for_operator,
    )

    repo, op_dir, old_head = _repo(tmp_path)
    (op_dir / new_name).write_text("// generated\n", encoding="utf-8")
    state = _state(tmp_path, repo, op_dir)

    actions = BaselineSubstage().actions(state)

    assert len(actions) == 1
    new_head = _git(repo, "rev-parse", "HEAD")
    assert new_head != old_head
    assert validate_commit_for_operator(state, new_head) == (True, "")
    assert _git(repo, "status", "--porcelain", "--", "ops/gather") == ""


def test_a5_resume_empty_best_backfills_current_source_anchor(tmp_path):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        BaselineSubstage,
    )

    repo, op_dir, head = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    cp_path = _checkpoint_path(tmp_path)
    cp_path.parent.mkdir(parents=True)
    cp_path.write_text(json.dumps({
        "status": "in_progress", "phase": "baseline",
        "kernel_debug_round": 0, "best_commit": "",
    }), encoding="utf-8")

    BaselineSubstage().actions(state)

    cp = json.loads(cp_path.read_text(encoding="utf-8"))
    assert cp["rollback_safe"] is True
    assert cp["initial_commit"] == head
    assert cp["best_commit"] == head


def test_a5_git_identity_failure_preserves_untracked_source(
        tmp_path, monkeypatch):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        BaselineSubstage,
    )

    repo, op_dir, _head = _repo(tmp_path)
    generated = op_dir / "new_kernel.cpp"
    generated.write_text("// must survive\n", encoding="utf-8")
    for key in (
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.setenv(key, "")
    state = _state(tmp_path, repo, op_dir)

    BaselineSubstage().actions(state)

    assert generated.read_text(encoding="utf-8") == "// must survive\n"
    assert _git(repo, "status", "--porcelain", "--", f"ops/gather/{generated.name}") != ""


def test_entry_snapshot_commits_only_profile_allowed_production_files(tmp_path):
    from ascendc_devkit.orchestration.stages.precision_debug_a5.git_safety import (
        ensure_entry_snapshot,
    )

    repo, op_dir, old_head = _repo(tmp_path)
    (op_dir / "op_kernel").mkdir()
    production = op_dir / "op_kernel" / "gather.h"
    production.write_text("// generated\n", encoding="utf-8")
    debug_files = [
        op_dir / "gather_dump_debug_test.py",
        op_dir / "round1_verify.log",
        op_dir / "op_kernel" / "gather.h.bak",
        op_dir / "stderr_case.txt",
    ]
    for path in debug_files:
        path.write_text("debug\n", encoding="utf-8")
    profile = RepositoryProfile(
        name="test",
        precision_debug_commit=PrecisionDebugCommitScope(
            include=("op_kernel/**",),
            exclude=("*.txt", "**/*.txt"),
        ),
    )
    state = _state(tmp_path, repo, op_dir, profile=profile)

    new_head = ensure_entry_snapshot(state)

    assert new_head is not None and new_head != old_head
    committed = set(_git(
        repo, "show", "--pretty=", "--name-only", "HEAD").splitlines())
    assert committed == {"ops/gather/op_kernel/gather.h"}
    status = _git(repo, "status", "--porcelain", "--", "ops/gather")
    for path in debug_files:
        assert path.relative_to(repo).as_posix() in status


def test_entry_snapshot_keeps_build_manifest_despite_txt_debug_veto(tmp_path):
    """CMakeLists.txt 是构建清单,不是调试文本抓拍,不得被 *.txt 排除表误杀。

    回归:真实批跑中 profile include 显式声明了 CMakeLists.txt,但框架
    _DEBUG_EXCLUDES 的 ``*.txt`` 机制代理把它挡在快照提交之外;收尾
    rollback 的 checkout+clean 随即物理删除这个未跟踪文件,其后所有重建
    均死于 cmake "does not contain a CMakeLists.txt file"。调试文本
    (stderr_case.txt)仍必须留在提交之外。
    """
    from ascendc_devkit.orchestration.stages.precision_debug_a5.git_safety import (
        ensure_entry_snapshot,
    )

    repo, op_dir, old_head = _repo(tmp_path)
    (op_dir / "CMakeLists.txt").write_text("# op build manifest\n",
                                           encoding="utf-8")
    (op_dir / "stderr_case.txt").write_text("debug capture\n",
                                           encoding="utf-8")
    profile = RepositoryProfile(
        name="test",
        precision_debug_commit=PrecisionDebugCommitScope(
            include=("CMakeLists.txt", "op_kernel/**"),
        ),
    )
    state = _state(tmp_path, repo, op_dir, profile=profile)

    new_head = ensure_entry_snapshot(state)

    assert new_head is not None and new_head != old_head
    committed = set(_git(
        repo, "show", "--pretty=", "--name-only", "HEAD").splitlines())
    assert committed == {"ops/gather/CMakeLists.txt"}
    status = _git(repo, "status", "--porcelain", "--", "ops/gather")
    assert "ops/gather/stderr_case.txt" in status


def test_commit_without_operator_source_is_never_a_rollback_anchor(tmp_path):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        validated_rollback_anchor,
    )

    repo, op_dir, head = _repo(tmp_path, with_source=False)
    state = _state(tmp_path, repo, op_dir)
    best, reason = validated_rollback_anchor(state, {
        "rollback_safe": True,
        "initial_commit": head,
        "best_commit": head,
    })
    assert best is None
    assert "contains no operator source" in reason


def test_empty_best_never_implicitly_falls_back_to_unrecorded_head(tmp_path):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        validated_rollback_anchor,
    )

    repo, op_dir, _head = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    best, reason = validated_rollback_anchor(state, {
        "rollback_safe": True,
        "initial_commit": "not-the-current-head",
        "best_commit": "",
    })
    assert best is None
    assert "best_commit empty" in reason


def test_a5_converge_skips_rollback_and_redeploy_for_invalid_anchor(
        tmp_path, monkeypatch):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        _converge_a5_to_best_commit,
    )

    repo, op_dir, head = _repo(tmp_path, with_source=False)
    state = _state(tmp_path, repo, op_dir)
    cp_path = _checkpoint_path(tmp_path)
    cp_path.parent.mkdir(parents=True)
    cp_path.write_text(json.dumps({
        "status": "max_rounds_reached",
        "initial_commit": head, "best_commit": head,
        "rollback_safe": True, "anchor_error": "",
    }), encoding="utf-8")
    rollback_calls = []
    deploy_calls = []
    monkeypatch.setattr(
        "ascendc_devkit.infra.repo_guard.RepoGuard.rollback",
        lambda *args, **kwargs: rollback_calls.append(1) or True)
    monkeypatch.setattr(
        "ascendc_devkit.orchestration.stages.deploy.Deployer.deploy",
        lambda *args, **kwargs: deploy_calls.append(1))

    out = _converge_a5_to_best_commit(state)

    assert out is state
    assert rollback_calls == [1]
    assert deploy_calls == [1]


def test_kernel_debug_round_uses_pre_spawn_checkpoint_when_agent_advances_disk(
        tmp_path, capsys):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _extract_a5_debug_checkpoint,
        _load_a5_checkpoint, _save_a5_checkpoint,
    )

    repo, op_dir, head = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    before = {
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 1,
        "history": [{"phase": "kernel_debug", "round": 1}],
        "initial_commit": head, "best_commit": head,
        "rollback_safe": True, "anchor_error": "",
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 0}],
    }
    _save_a5_checkpoint(state, before)
    state = state.with_updates(
        _debug_checkpoint=_extract_a5_debug_checkpoint(before))

    # Contract violation: leaf advances the disk checkpoint before returning.
    tampered = dict(before)
    tampered["kernel_debug_round"] = 2
    tampered["phase"] = "regression"
    _save_a5_checkpoint(state, tampered)
    result = (
        tmp_path / "artifacts" / "precision_debug_a5" / "kernel-debug"
        / "kernel_debug_result_r001_p000.json"
    )
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({
        "phase": "kernel_debug",
        "debug_status": "fixed",
        "is_vf_issue": False,
        "code_modified": False,
        "precision_result": {
            "pass": 1, "total": 1, "max_diff": 0.0, "failed_cases": [],
        },
    }), encoding="utf-8")

    out = KernelDebugSubstage().transition(state, {})

    saved = _load_a5_checkpoint(state)
    assert out._debug_checkpoint["phase"] == "kernel_debug"
    assert saved["phase"] == "kernel_debug"
    assert len(saved["history"]) == 2


def test_missing_expected_result_is_abort_without_round_increment(
        tmp_path):
    """No phase output at all = aborted spawn → anneal (agent_aborted), NOT a
    hard contract error and NOT a stale-default route. Round is not consumed."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage,
        _extract_a5_debug_checkpoint, _load_a5_checkpoint,
        _save_a5_checkpoint,
    )

    repo, op_dir, head = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    cp = {
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 1, "history": [],
        "initial_commit": head, "best_commit": head,
        "rollback_safe": True, "anchor_error": "",
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 0}],
    }
    _save_a5_checkpoint(state, cp)
    state = state.with_updates(
        _debug_checkpoint=_extract_a5_debug_checkpoint(cp))

    out = KernelDebugSubstage().transition(state, {})

    assert out._debug_checkpoint["agent_aborted"] is True
    assert KernelDebugSubstage().resolve_condition(out) == "agent_aborted"
    assert _load_a5_checkpoint(state)["kernel_debug_round"] == 1


def test_stale_latest_without_current_round_output_is_abort(tmp_path):
    """Round-convention stage: a STALE ``latest`` relay file from a previous
    round (written by ``_sync_phase_latest``) is NOT evidence this round produced
    output. A killed round-2 spawn leaves ``kernel_debug_result.json`` holding
    round-1's result; the abort anneal must fire (agent_aborted), NOT raise a
    contract error — otherwise the contract-error path sets last_error and
    graph_executor's stagnation guard falls through to a linear sibling (vf_test)
    with zero VF evidence (2026-08-11 轨迹回归)."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _extract_a5_debug_checkpoint,
        _load_a5_checkpoint, _save_a5_checkpoint,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _phase_path,
    )

    repo, op_dir, head = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    cp = {
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 1, "history": [],
        "initial_commit": head, "best_commit": head,
        "rollback_safe": True, "anchor_error": "",
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 0}],
    }
    _save_a5_checkpoint(state, cp)
    # latest path = round-1 residue (stale), NO round-2 file, NO round-2 relay
    latest = _phase_path(state, "kernel_debug_result.json", round_suffix=False)
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps({"debug_status": "retry"}), encoding="utf-8")
    state = state.with_updates(
        _debug_checkpoint=_extract_a5_debug_checkpoint(cp))

    out = KernelDebugSubstage().transition(state, {})

    assert out._debug_checkpoint["agent_aborted"] is True
    assert _load_a5_checkpoint(state)["kernel_debug_round"] == 1
    assert KernelDebugSubstage().resolve_condition(out) == "agent_aborted"


def test_kernel_fixed_round_creates_candidate_without_promoting_best(
        tmp_path):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _extract_a5_debug_checkpoint,
        _load_a5_checkpoint, _save_a5_checkpoint,
    )

    repo, op_dir, initial = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    cp = {
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 0, "history": [],
        "initial_commit": initial, "best_commit": initial,
        "rollback_safe": True, "anchor_error": "",
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 0}],
        "best_snapshot": {
            "max_err": 1.0, "commit": initial, "passed": 0, "total": 1,
            "failed_cases": [{"case_id": "c1"}],
            "updated_by": "baseline", "updated_round": 0,
        },
    }
    _save_a5_checkpoint(state, cp)
    state = state.with_updates(
        _debug_checkpoint=_extract_a5_debug_checkpoint(cp))
    (op_dir / "kernel.cpp").write_text("// fixed\n", encoding="utf-8")
    result = (
        tmp_path / "artifacts" / "precision_debug_a5" / "kernel-debug"
        / "kernel_debug_result_r001_p000.json"
    )
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({
        "phase": "kernel_debug", "debug_status": "fixed",
        "is_vf_issue": False, "code_modified": True,
        "precision_result": {
            "pass": 1, "total": 1, "max_diff": 0.0, "failed_cases": [],
        },
    }), encoding="utf-8")

    KernelDebugSubstage().transition(state, {})

    saved = _load_a5_checkpoint(state)
    candidate = saved["candidate_commit"]
    assert candidate != initial
    assert saved["best_snapshot"]["passed"] == 0
    assert saved["best_commit"] == initial
    assert _git(repo, "rev-parse", "HEAD") == candidate
    assert (op_dir / "kernel.cpp").read_text(encoding="utf-8") == "// fixed\n"


def test_kernel_candidate_preserves_dirty_fix_from_previous_vector_phase(
        tmp_path):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _extract_a5_debug_checkpoint,
        _load_a5_checkpoint, _save_a5_checkpoint,
    )

    repo, op_dir, initial = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    cp = {
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 0, "history": [],
        "initial_commit": initial, "best_commit": initial,
        "rollback_safe": True, "anchor_error": "",
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 0}],
    }
    _save_a5_checkpoint(state, cp)
    state = state.with_updates(
        _debug_checkpoint=_extract_a5_debug_checkpoint(cp))
    (op_dir / "kernel.cpp").write_text("// vector fix\n", encoding="utf-8")
    result = (
        tmp_path / "artifacts" / "precision_debug_a5" / "kernel-debug"
        / "kernel_debug_result_r001_p000.json"
    )
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({
        "phase": "kernel_debug", "debug_status": "fixed",
        "code_modified": True,
        "precision_result": {
            "pass": 1, "total": 1, "max_diff": 0.0, "failed_cases": [],
        },
    }), encoding="utf-8")

    KernelDebugSubstage().transition(state, {})

    saved = _load_a5_checkpoint(state)
    assert saved["candidate_commit"] != initial
    assert saved["best_commit"] == initial
    assert _git(repo, "rev-parse", "HEAD") == saved["candidate_commit"]


def test_a5_candidate_commit_excludes_unrelated_pre_staged_change(tmp_path):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        _commit_candidate_phase,
    )

    repo, op_dir, initial = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    outside = repo / "README.md"
    outside.write_text("user staged change\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    (op_dir / "kernel.cpp").write_text("// candidate\n", encoding="utf-8")
    cp = {"best_commit": initial, "rollback_safe": True}

    assert _commit_candidate_phase(state, cp, "kernel_debug", 1) is True

    assert _git(repo, "show", "HEAD:README.md") == "repo"
    assert _git(repo, "diff", "--cached", "--name-only") == "README.md"
    assert cp["candidate_commit"] == _git(repo, "rev-parse", "HEAD")


def test_agent_written_worse_snapshot_cannot_replace_pre_spawn_best(tmp_path):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _extract_a5_debug_checkpoint,
        _load_a5_checkpoint, _save_a5_checkpoint,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
        _save_framework_checkpoint_guard,
    )

    repo, op_dir, initial = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    old_snapshot = {
        "max_err": 0.0, "commit": initial, "passed": 1, "total": 1,
        "failed_cases": [],
        "updated_by": "baseline", "updated_round": 0,
    }
    before = {
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 0, "history": [],
        "initial_commit": initial, "best_commit": initial,
        "rollback_safe": True, "anchor_error": "",
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 0}],
        "best_snapshot": old_snapshot,
    }
    _save_a5_checkpoint(state, before)
    _save_framework_checkpoint_guard(state)
    state = state.with_updates(
        _debug_checkpoint=_extract_a5_debug_checkpoint(before))
    tampered = dict(before)
    tampered["best_snapshot"] = {
        "max_err": 1.0, "commit": "invented", "passed": 0, "total": 1,
        "failed_cases": [{"case_id": "c1"}],
        "updated_by": "kernel_debug", "updated_round": 1,
    }
    _save_a5_checkpoint(state, tampered)
    result = (
        tmp_path / "artifacts" / "precision_debug_a5" / "kernel-debug"
        / "kernel_debug_result_r001_p000.json"
    )
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({
        "phase": "kernel_debug", "debug_status": "retry",
        "is_vf_issue": False, "code_modified": False,
        "precision_result": {
            "pass": 0, "total": 1, "max_diff": 1.0,
            "failed_cases": [{"case_id": "c1"}],
        },
    }), encoding="utf-8")

    KernelDebugSubstage().transition(state, {})

    saved = _load_a5_checkpoint(state)
    assert saved["best_snapshot"] == old_snapshot
    assert saved["best_commit"] == initial


def test_kernel_debug_fixed_kl_schema_commits_and_promotes_fix(
        tmp_path):
    """kernel_debug fixed 后批跑全量 KL（原 regression 职责）晋升修复。

    agent prewrites 20/20，result 只含 kl_result；pre-spawn guard 必须恢复
    framework 的 18/20 snapshot、归一化 kl_result、commit dirty fix、
    并在全量 KL 高水位改善时原子晋升 best_commit。
    """
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5.checkpoint import (
        _save_framework_checkpoint_guard,
    )

    repo, op_dir, initial = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    before = {
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 0, "history": [],
        "initial_commit": initial, "best_commit": initial,
        "rollback_safe": True, "anchor_error": "",
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 1}],
        "best_snapshot": {
            "max_err": 0.031, "commit": initial, "passed": 18, "total": 20,
            "failed_cases": [{"case_id": "c1"}, {"case_id": "c2"}],
            "updated_by": "baseline", "updated_round": 0,
        },
    }
    _save_a5_checkpoint(state, before)
    _save_framework_checkpoint_guard(state)
    (op_dir / "kernel.cpp").write_text("// scaleBuf -> outQueueScale\n", encoding="utf-8")

    tampered = dict(before)
    tampered["best_commit"] = ""
    tampered["best_snapshot"] = {
        "max_err": 0.0, "commit": "", "passed": 20, "total": 20,
        "failed_cases": [], "updated_by": "kernel_debug", "updated_round": 1,
    }
    _save_a5_checkpoint(state, tampered)

    result = (tmp_path / "artifacts" / "precision_debug_a5" / "kernel-debug"
              / "kernel_debug_round_1_result.json")
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({
        "phase": "kernel_debug", "debug_status": "fixed",
        "code_modified": True, "is_vf_issue": False,
        "new_failed_cases": [], "error_type": "",
        "kl_result": {"pass": 20, "total": 20, "max_diff": 0.0, "failed_cases": []},
    }), encoding="utf-8")

    KernelDebugSubstage().transition(state, {})

    saved = _load_a5_checkpoint(state)
    promoted = saved["best_commit"]
    assert promoted and promoted != initial
    assert promoted == saved["candidate_commit"]
    assert promoted == saved["best_snapshot"]["commit"]
    assert saved["best_snapshot"]["passed"] == 20
    assert saved["best_snapshot"]["total"] == 20
    assert _git(repo, "rev-parse", "HEAD") == promoted
    assert _git(repo, "status", "--porcelain", "--", "ops/gather") == ""


def test_a5_converge_refuses_dirty_tree_instead_of_checkout_clean(
        tmp_path, monkeypatch):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        _converge_a5_to_best_commit, _save_a5_checkpoint,
    )

    repo, op_dir, initial = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    _save_a5_checkpoint(state, {
        "status": "max_rounds_reached", "initial_commit": initial,
        "best_commit": initial, "rollback_safe": True, "anchor_error": "",
        "best_snapshot": {"commit": initial, "passed": 0, "total": 1},
    })
    kernel = op_dir / "kernel.cpp"
    kernel.write_text("// verified but not committed\n", encoding="utf-8")
    rollback_calls = []
    monkeypatch.setattr(
        "ascendc_devkit.infra.repo_guard.RepoGuard.rollback",
        lambda *args, **kwargs: rollback_calls.append(1) or True,
    )

    out = _converge_a5_to_best_commit(state)

    assert out is state
    assert rollback_calls == []
    assert kernel.read_text(encoding="utf-8") == "// verified but not committed\n"


def test_a5_converge_empty_best_never_falls_back_to_head(
        tmp_path, monkeypatch):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        _converge_a5_to_best_commit, _save_a5_checkpoint,
    )

    repo, op_dir, initial = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    _save_a5_checkpoint(state, {
        "status": "max_rounds_reached", "initial_commit": initial,
        "best_commit": "", "rollback_safe": True, "anchor_error": "",
    })
    rollback_calls = []
    deploy_calls = []
    monkeypatch.setattr(
        "ascendc_devkit.infra.repo_guard.RepoGuard.rollback",
        lambda *args, **kwargs: rollback_calls.append(1) or True,
    )
    monkeypatch.setattr(
        "ascendc_devkit.orchestration.stages.deploy.Deployer.deploy",
        lambda *args, **kwargs: deploy_calls.append(1),
    )

    out = _converge_a5_to_best_commit(state)

    assert out is state
    assert rollback_calls == []
    assert deploy_calls == []


@pytest.mark.parametrize("error_type", [
    "VECTOR_ERROR", "ENV_ERROR", "SCHEMA_ERROR",
])
def test_non_numeric_error_sentinel_never_builds_snapshot(error_type):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        _build_snapshot_from_result,
    )

    result = {
        "error_type": error_type,
        "precision_result": {"pass": 1, "total": 1, "max_diff": 0.0},
    }
    assert _build_snapshot_from_result(result, "kernel_debug", 1) is None


# —— skill↔framework result-filename contract (2026-08-03) ——
#
# Root cause of the "kernel_debug → kernel_debug" self-loop: skills told the
# agent to write ``{stem}_round_{round}_result.json`` (e.g.
# kernel_debug_round_1_result.json) while the framework only read
# ``{stem}_result.json``. `_agent_produced_output` saw nothing → every spawn
# aborted → agent_aborted self-loop → escalate. These tests pin the
# round-convention reading and guard against further drift.

def _write_round_result(tmp_path, phase_stem, filename, payload):
    d = tmp_path / "artifacts" / "precision_debug_a5" / phase_stem
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _a5_cp(head: str, phase: str, round_key: str = "") -> dict:
    cp = {
        "status": "in_progress", "phase": phase,
        "history": [],
        "initial_commit": head, "best_commit": head,
        "rollback_safe": True, "anchor_error": "",
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 1}],
    }
    if round_key:
        cp[round_key] = 0
    return cp


def test_agent_produced_output_accepts_skill_round_result(tmp_path):
    """A spawn that wrote the skill-convention round file is NOT an abort."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage,
    )
    repo, op_dir, head = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    _write_round_result(tmp_path, "kernel-debug", "kernel_debug_round_1_result.json",
                        {"phase": "kernel_debug", "debug_status": "fixed"})
    assert KernelDebugSubstage()._agent_produced_output(state) is True


def test_read_phase_result_reads_framework_decided_round(tmp_path):
    """The round is decided by the framework's checkpoint counter, not by a
    numeric-max directory scan. A leftover file at a HIGHER round number from a
    previous run/session must never be read for the current round."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _extract_a5_debug_checkpoint,
        _load_a5_checkpoint, _save_a5_checkpoint,
    )
    repo, op_dir, head = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    # Current round = kernel_debug_round(0) + 1 = 1.
    cp = _a5_cp(head, "kernel_debug", round_key="kernel_debug_round")
    _save_a5_checkpoint(state, cp)
    state = state.with_updates(
        _debug_checkpoint=_extract_a5_debug_checkpoint(cp))
    _write_round_result(tmp_path, "kernel-debug", "kernel_debug_round_1_result.json",
                        {"debug_status": "retry"})
    # Stale leftover from an earlier run — must be ignored for the current round.
    _write_round_result(tmp_path, "kernel-debug", "kernel_debug_round_3_result.json",
                        {"debug_status": "fixed"})
    out = KernelDebugSubstage()._read_phase_result(state, "kernel_debug_result.json")
    assert out.get("debug_status") == "retry"

    # Once the framework advances the counter, the SAME file name round_3 is
    # read (now it IS the current round), not because it's the max on disk.
    cp["kernel_debug_round"] = 2
    _save_a5_checkpoint(state, cp)
    state = state.with_updates(
        _debug_checkpoint=_extract_a5_debug_checkpoint(cp))
    out = KernelDebugSubstage()._read_phase_result(state, "kernel_debug_result.json")
    assert out.get("debug_status") == "fixed"


def test_kernel_debug_fixed_routes_on_skill_round_result(tmp_path):
    """kernel_debug fixed 后读 skill round 文件并路由：无 KL summary（未批跑全量）
    → 保守 case_kl_fails 回 kernel_debug（不直通 baseline）。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _extract_a5_debug_checkpoint,
        _load_a5_checkpoint, _save_a5_checkpoint,
    )
    repo, op_dir, head = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    cp = _a5_cp(head, "kernel_debug", round_key="kernel_debug_round")
    _save_a5_checkpoint(state, cp)
    state = state.with_updates(
        _debug_checkpoint=_extract_a5_debug_checkpoint(cp))
    _write_round_result(tmp_path, "kernel-debug", "kernel_debug_round_1_result.json",
                        {"phase": "kernel_debug", "debug_status": "fixed",
                         "is_vf_issue": False, "code_modified": False,
                         "new_failed_cases": []})
    out = KernelDebugSubstage().transition(state, {})
    assert out._debug_checkpoint.get("agent_aborted") is not True
    assert out._debug_checkpoint["debug_status"] == "fixed"
    assert KernelDebugSubstage().resolve_condition(out) == "case_kl_fails"
    assert _load_a5_checkpoint(state)["kernel_debug_round"] == 1


def test_kernel_debug_loads_skill_round_result(tmp_path):
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _extract_a5_debug_checkpoint,
        _load_a5_checkpoint, _save_a5_checkpoint,
    )
    repo, op_dir, head = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    cp = {
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 0, "history": [],
        "initial_commit": head, "best_commit": head,
        "rollback_safe": True, "anchor_error": "",
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 0}],
    }
    _save_a5_checkpoint(state, cp)
    state = state.with_updates(
        _debug_checkpoint=_extract_a5_debug_checkpoint(cp))
    _write_round_result(tmp_path, "kernel-debug", "kernel_debug_round_1_result.json",
                        {"phase": "kernel_debug", "debug_status": "fixed",
                         "is_vf_issue": False, "code_modified": False,
                         "precision_result": {"pass": 1, "total": 1, "max_diff": 0.0,
                                              "failed_cases": []}})
    out = KernelDebugSubstage().transition(state, {})
    assert out._debug_checkpoint.get("agent_aborted") is not True
    assert out._debug_checkpoint["debug_status"] == "fixed"
    # 无 KL summary（agent 未批跑全量 KL）→ 保守路由回 kernel_debug，不直通 baseline
    assert KernelDebugSubstage().resolve_condition(out) == "case_kl_fails"


def test_vf_test_context_injects_target_vf_and_current_case(tmp_path):
    """vf_test must learn WHICH VF to test + under what shape/dtype from the
    kernel_debug hand-off (regression: this used to be discoverable only by
    ad-hoc directory listing in the spawned agent)."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        VfTestSubstage, _extract_a5_debug_checkpoint,
        _load_a5_checkpoint, _save_a5_checkpoint,
    )
    repo, op_dir, head = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    cp = {
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 4, "history": [],
        "initial_commit": head, "best_commit": head,
        "rollback_safe": True, "anchor_error": "",
        "current_case_index": 0,
        "failed_case_queue": [{
            "case_id": 1, "shape": "2x32x64x64x64", "dtype": "float16",
            "error_layer": "op_plugin", "failure_type": "op_plugin_binary_discovery",
            "status": "debugging", "attempt_count": 1,
        }],
    }
    _save_a5_checkpoint(state, cp)
    state = state.with_updates(_debug_checkpoint=_extract_a5_debug_checkpoint(cp))
    # Mimic the real kernel_debug hand-off: vf_functions as a free-form string
    # list, as emitted by the kernel_debug skill in the traced run.
    _write_round_result(tmp_path, "kernel-debug", "kernel_debug_round_4_result.json", {
        "phase": "kernel_debug", "debug_status": "need_vf",
        "is_vf_issue": True,
        "vf_functions": [
            "CustomRegImpl::ReduceSumBinaryFold (fp16->fp32 Cast + fp32 ReduceSum + "
            "fp32 Adds accumulate + fp32->fp16 Cast output)"
        ],
        "dump_evidence": "VF 输入正确但输出错误 (max_diff 7.93e-4)",
    })
    ctx = VfTestSubstage()._common_context(state)
    assert ctx["kernel_debug_result_path"].endswith(
        "kernel-debug/kernel_debug_round_4_result.json")
    vf = ctx["vf_functions"]
    assert len(vf) == 1
    assert vf[0]["name"] == "CustomRegImpl::ReduceSumBinaryFold"
    assert "fp32 ReduceSum" in vf[0]["function"]
    # Enriched from the current failed case — the shape/dtype combination that
    # triggered the VF problem.
    assert vf[0]["dtype"] == "float16"
    assert vf[0]["input_shapes"] == "2x32x64x64x64"
    assert vf[0]["failed_case_id"] == 1
    assert "VF 输入正确但输出错误" in vf[0]["evidence"]
    assert ctx["current_case"]["case_id"] == 1


def test_vf_test_prompt_declares_target_vf_and_copy_rule(tmp_path):
    """The vf_test prompt must name the target VF explicitly and mandate copying
    the ACTUAL VF body from the deployed code (not a rebuilt/verified script)."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        VfTestSubstage, _extract_a5_debug_checkpoint,
        _save_a5_checkpoint,
    )
    repo, op_dir, head = _repo(tmp_path)
    state = _state(tmp_path, repo, op_dir)
    cp = {
        "status": "in_progress", "phase": "vf_test",
        "kernel_debug_round": 4, "vf_round": 0, "history": [],
        "initial_commit": head, "best_commit": head,
        "rollback_safe": True, "anchor_error": "",
        "current_case_index": 0,
        "failed_case_queue": [{
            "case_id": 1, "shape": "2x32x64x64x64", "dtype": "float16",
            "status": "debugging", "attempt_count": 1,
        }],
    }
    _save_a5_checkpoint(state, cp)
    state = state.with_updates(_debug_checkpoint=_extract_a5_debug_checkpoint(cp))
    _write_round_result(tmp_path, "kernel-debug", "kernel_debug_round_4_result.json", {
        "phase": "kernel_debug", "debug_status": "need_vf",
        "is_vf_issue": True,
        "vf_functions": ["CustomRegImpl::ReduceSumBinaryFold (fp32 ReduceSum)"],
        "dump_evidence": "VF 输入正确但输出错误",
    })
    ctx = VfTestSubstage()._common_context(state)
    prompt = VfTestSubstage()._phase_prompt(ctx, 1)
    assert "CustomRegImpl::ReduceSumBinaryFold" in prompt
    assert "float16" in prompt and "2x32x64x64x64" in prompt
    assert "kernel_debug_round_4_result.json" in prompt
    # Copy-the-actual-VF discipline is present; forbidden sources are named.
    assert "原样搬运" in prompt
    assert "vf_verified/" in prompt
    assert "references/examples/" in prompt
    assert "{code_dir}" not in prompt
    assert str(op_dir) in prompt
    assert "op_kernel/*." in prompt and "{h,cpp}" in prompt


def test_vf_test_prompt_failsafe_on_missing_target(tmp_path):
    """Without a parsed vf_functions the prompt must route the agent to the
    kernel_debug result and forbid guessing (no crash on a bare ctx)."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import VfTestSubstage
    ctx = {
        "debug_dir": "/tmp/dbg",
        "code_dir": "/tmp/src",
        "dev_record_dir": "/tmp/rec",
        "phase_round_result_path": "/tmp/dbg/vf-test/vf_round_1_result.json",
        "kernel_debug_result_path": "/tmp/dbg/kernel-debug/kernel_debug_round_4_result.json",
        "vf_functions": [],
        "current_case": {},
    }
    prompt = VfTestSubstage()._phase_prompt(ctx, 1)
    assert "error_type=INP" in prompt
    assert "禁止猜测" in prompt


def test_normalize_vf_functions_accepts_strings_and_dicts():
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _normalize_vf_functions,
    )
    case = {"dtype": "float16", "shape": "2x32x64x64x64", "case_id": 1}
    out = _normalize_vf_functions({
        "vf_functions": ["CustomRegImpl::ReduceSumBinaryFold (fp32 ReduceSum)"],
        "dump_evidence": "ev",
    }, case)
    assert out[0]["name"] == "CustomRegImpl::ReduceSumBinaryFold"
    assert out[0]["dtype"] == "float16" and out[0]["input_shapes"] == "2x32x64x64x64"
    assert out[0]["failed_case_id"] == 1 and out[0]["evidence"] == "ev"
    # Structured dicts pass through; missing fields are enriched, not clobbered.
    out = _normalize_vf_functions({
        "vf_functions": [{"name": "VF2", "function": "f2", "dtype": "fp32"}],
    }, case)
    assert out[0]["function"] == "f2" and out[0]["dtype"] == "fp32"
    assert out[0]["input_shapes"] == "2x32x64x64x64"
    # Empty input → no target.
    assert _normalize_vf_functions({}, case) == []


def test_all_skills_result_filenames_resolvable_by_framework():
    """Drift guard: every ``*_result.json`` a skill tells the agent to write must
    be resolvable by the framework — either the plain latest path (its own
    ``_schema_files``) or the skill round convention (``{stem}*_round_<n>_result.json``).
    """
    import re
    from pathlib import Path
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        BaselineSubstage, KernelDebugSubstage, VfTestSubstage,
        VectorErrorDebugSubstage, OpPluginDebugSubstage,
        _round_result_stem,
    )
    stages = [
        BaselineSubstage(),
        KernelDebugSubstage(),
        VfTestSubstage(),
        VectorErrorDebugSubstage(),
        OpPluginDebugSubstage(),
    ]
    schema_names = {s._schema_files[0] for s in stages if s._schema_files}
    # Framework-owned terminal artifact, not an agent phase output — skills only
    # mention it to forbid writing it.
    framework_owned = {"debug_result.json"}
    # ``perf_result.json`` is the cann-bench-eval evidence artifact the baseline
    # skill produces (Step 6, rc+kl double-pass only); its numbers reach the
    # framework via ``baseline_result.json.summary.performance`` — the framework
    # never reads the file itself, so it is not a schema-resolvable phase output.
    side_artifacts = {"perf_result.json"}
    # ``result_{op_name}_summary.json`` is written by the KernelLaunch script (not
    # the agent) at ``{debug_dir}/baseline/`` and consumed by the framework
    # (baseline/kernel_debug-fixed transitions reconcile queue max_diff_kl from it).
    # It is not matched by the ``*_result.json`` regex below (suffix
    # ``_summary.json``), so it needs no whitelist entry — the requirement lives in
    # the baseline skill's script-generation checklist (Step 1).
    # legacy ``kl_result.json`` is no longer referenced by any skill; removed from
    # the whitelist.
    repo_root = Path(__file__).resolve().parents[3]
    skills_root = repo_root / ".claude" / "skills"
    basenames = set()
    for stage in stages:
        skill_dir = skills_root / stage._assigned_skill()
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.exists(), f"missing skill {skill_md}"
        # Match both plain (baseline_result.json) and round-convention
        # (kernel_debug_round_{round}_result.json) result filenames.
        for m in re.finditer(
                r"([a-z_]+(?:_round_\{[^{}]+\})?)_result\.json",
                skill_md.read_text(encoding="utf-8")):
            basenames.add(f"{m.group(1)}_result.json")
    assert basenames, "no result filenames extracted from skills"
    for name in sorted(basenames - framework_owned - side_artifacts):
        # Strict: plain name equals a schema, or the round prefix before
        # ``_round_`` equals the schema stem exactly (would have caught the
        # op_plugin skill writing ``op_plugin_debug_round_…``).
        round_prefix = re.match(r"(.+)_round_", name)
        round_prefix = round_prefix.group(1) if round_prefix else None
        assert (
            name in schema_names
            or (round_prefix is not None
                and any(round_prefix == _round_result_stem(s) for s in schema_names))
        ), f"skill result filename {name} is not resolvable by the framework"


def test_skill_round_result_path_matches_framework():
    """Drift guard: 每个 round-convention 阶段，skill 声明的结果路径模板
    ``{phase_dir}/{stem}_round_{{round}}_result.json`` 必须与框架推导
    （``_PHASE_STEM_MAP`` + ``_round_result_stem``）完全一致——skill 写的路径
    与框架 transition 读取路径互为镜像，任何一边改名都会在这里炸。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _PHASE_STEM_MAP,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, VfTestSubstage,
        VectorErrorDebugSubstage, OpPluginDebugSubstage,
        _round_result_stem,
    )
    stages = [
        KernelDebugSubstage(),
        VfTestSubstage(),
        VectorErrorDebugSubstage(),
        OpPluginDebugSubstage(),
    ]
    repo_root = Path(__file__).resolve().parents[3]
    skills_root = repo_root / ".claude" / "skills"
    for stage in stages:
        filename = stage._schema_files[0]
        stem = _round_result_stem(filename)
        phase_dir = _PHASE_STEM_MAP.get(filename, filename)
        fw_template = f"{phase_dir}/{stem}_round_{{round}}_result.json"
        skill_md = (skills_root / stage._assigned_skill() / "SKILL.md").read_text(encoding="utf-8")
        assert fw_template in skill_md, (
            f"{stage.name}: skill 未声明框架推导的结果路径模板 {fw_template!r}"
        )


def test_kl_summary_producer_declared_in_skills():
    """Drift guard: KL 全量 per-case 机器可读产物
    ``{debug_dir}/baseline/result_{op_name}_summary.json`` 由 KL 脚本 dump，
    框架 ``_load_latest_kl_data`` 读取调和队列。生产者契约必须同时出现在
    baseline（生成脚本时内置）与 kernel_debug（fixed 后批跑全量说明）skill，且
    kernel_debug 的 ``verification.kl_log`` 指向同一路径——防止某侧不再
    生产/读取造成队列调和空转。"""
    repo_root = Path(__file__).resolve().parents[3]
    skills_root = repo_root / ".claude" / "skills"
    needle = "result_{op_name}_summary.json"
    for name in ("ascendc-precision-baseline", "ascendc-precision-kernel-debug"):
        md = (skills_root / name / "SKILL.md").read_text(encoding="utf-8")
        assert needle in md, f"{name}: 未声明 KL summary 产物 {needle}"
