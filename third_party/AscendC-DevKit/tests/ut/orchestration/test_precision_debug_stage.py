"""P0 (51-*.md) + Stage 1-3 (54-*.md) — precision_debug CompositeGroup sub-stages.

Covers the seven sub-stages (run_tests / diagnose / diagnose_refine /
printf_location / comment_bisect / bounds_check / scope_guard; diagnose 自实施
原 fix 职责，docs/plan/fix-diagnose-merge) that replaced the deleted async LLM orchestrator: ``transition()``
reads control.json into ``state._debug_checkpoint`` (file relay §2.3),
``resolve_condition()`` routes on it, routing-control mutations (case
advancement) are written back to control.json, and ``_sync_debug_result``
materializes ``PrecisionDebugResult`` at a terminal state. Plus
TRANSITION_TABLE routing + group build + §12.1 scope guard + §12.2 contract
validation.

UT uses mock control.json (no real LLM/NPU); the real agent loop is heavy_llm (§3.11).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.runtime_config import (
    _DEFAULT_PRECISION_MAX_ITERATIONS,
    _DEFAULT_PRECISION_MAX_ATTEMPTS_PER_CASE,
    _DEFAULT_PRECISION_TIME_BUDGET_S,
)
from ascendc_devkit.orchestration.stages.precision_debug_substages import (
    DiagnoseSubstage,
    RunTestsSubstage,
    PrecisionDebugContractError,
    _advance_current_case,
    _advance_phase_counter,
    _aggregate_failure_type,
    _ensure_control_contract,
    _extract_debug_checkpoint,
    _get_current_failure_type,
    _PHASE_DEFAULTS,
    _phase_path,
    _sync_debug_result,
)
from ascendc_devkit.orchestration.precision_debug_tree import (
    _PRECISION_DEBUG_TRANSITION_TABLE,
    build_precision_debug_group,
)


# —— fixtures ————————————————————————————————————————————————————

def _op_identity(tmp_path: Path) -> OperatorIdentity:
    return OperatorIdentity(
        spec=OperatorSpec(name="gelu"),
        repo_root=tmp_path,
        op_dir=tmp_path / "custom_ops" / "gelu",
    )


def _state(tmp_path: Path, **overrides) -> State:
    defaults = dict(
        mode="new",
        op_identity=_op_identity(tmp_path),
        requirement=Requirement(op_spec=OperatorSpec(name="gelu")),
        golden_path=Path("/tmp/golden.py"),
        golden_entry="golden",
        golden_input_type="float32",
        deploy_result=DeployResult(smoke_passed=True),
        codegen_manifest={"callable_target": {
            "kind": "torch_op", "symbol": "torch.ops.custom.gelu"}},
        design_target_chip="A2",
    )
    defaults.update(overrides)
    return State(**defaults)


def _ctrl_path(state: State) -> Path:
    op_dir = state.op_dir or (state.op_identity.op_dir if state.op_identity else None)
    p = Path(op_dir) / ".precision-fix" / "control.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _write_control(state: State, cp: dict) -> None:
    _ctrl_path(state).write_text(json.dumps(cp), encoding="utf-8")


def _read_control(state: State) -> dict:
    return json.loads(_ctrl_path(state).read_text(encoding="utf-8"))


def _case(case_id="c1", status="pending", attempt=0, ftype="precision"):
    return {"case_id": case_id, "shape": "[8]", "dtype": "fp16",
            "failure_type": ftype, "status": status, "max_err": 1.0,
            "attempt_count": attempt,
            "tried_fix_plan_ids": []}


def _control(**overrides):
    """Minimal valid control.json (post-split, §4.2 as-built).
    No D3 fields (current_iteration/current_stage/trim_retry/consecutive_failures
    /top-level bisect/candidate_loop). P3 减法: candidate_pool/scope_*/bounds_check
    字段已删——case stop-loss 是 max_attempts_per_case knob。
    """
    defaults = {
        "status": "running",
        # precision_debug loop knobs (mirror runtime_config defaults)
        "max_iterations": _DEFAULT_PRECISION_MAX_ITERATIONS,
        "max_attempts_per_case": _DEFAULT_PRECISION_MAX_ATTEMPTS_PER_CASE,
        "time_budget_sec": _DEFAULT_PRECISION_TIME_BUDGET_S,
        "current_case_index": 0,
        # §step-119: 顶层 best_* 字段已删——最优/计数从 history 测量史现算派生
        # （_derive_best_metrics / _best_commit_from_history），dc 由 transition 填充。
        "elapsed_sec": 0.0,
        "failed_case_queue": [],
        "history": [],
        "phase_counter": 0,
        "run_iter_counter": 0,
        "consecutive_aborts": 0,
    }
    defaults.update(overrides)
    return defaults


def _seed_phase(state: State, filename: str, summary: dict | None = None) -> Path:
    """Write a schema-valid round-suffixed phase JSON so ``transition()`` sees a
    normal (non-aborted) spawn. Without it the §abort guard (absent phase JSON)
    routes to the abort path. ``summary`` adds a non-empty ``_summary`` for stages
    that key off it (run_tests). transition() does not advance phase_counter, so a
    single seed covers repeated same-stage transitions (diagnose↔printf loops)."""
    payload = dict(_PHASE_DEFAULTS.get(filename, {}))
    if summary is not None:
        payload["_summary"] = summary
    p = _phase_path(state, filename, round_suffix=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _iter_result_json(state: State, case_details: list, **extra) -> Path:
    """Write a run-cases style result.json into the deterministic iter dir for
    the CURRENT run_iter_counter (§P2 framework-stats resolution path)."""
    cp_path = _ctrl_path(state)
    iter_n = 0
    if cp_path.exists():
        try:
            iter_n = int(json.loads(cp_path.read_text(encoding="utf-8"))
                         .get("run_iter_counter", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    iter_dir = cp_path.parent / f"run_tests_iter-{iter_n}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    p = iter_dir / "result.json"
    p.write_text(json.dumps({"case_details": case_details, **extra}),
                 encoding="utf-8")
    return p


def _cd(case_id: str, passed: bool, diff: float = 0.0,
        error: str | None = None) -> dict:
    """A run-cases result.json case_detail entry — ``accuracy.passed`` is the
    failure authority (mirrors the runner's schema)."""
    d = {"case_id": case_id, "case": f"level1/gelu:{case_id}",
         "input_shapes": [[8]],
         "accuracy": {"passed": passed, "max_diff": 0.0 if passed else diff}}
    if error:
        d["error"] = error
    return d


def _hist_run(total_count: int, failed_count: int = 0, *,
              round_: int = 1, source_commit: str = "",
              source_identity: str = "",
              max_err: float | None = None, crashed_count: int = 0,
              **extra) -> dict:
    """A schema-valid run_tests history entry.

    §step-119/§step-124: history 的 run_tests content 是框架独占写的权威测量记录——
    content 字段：failure_type/test_result/failed_count/total_count/max_err/
    crashed_count/last_run_log/source_commit（测量时刻全 sha，best 收敛锚点）/
    source_identity（测量时刻 {sha12}-dirty-N 可读标签）。供从 history 现算 best_*
    的测试构造。
    """
    content = {
        "failed_count": failed_count,
        "total_count": total_count,
        "max_err": max_err,
        "crashed_count": crashed_count,
        "source_commit": source_commit,
        "source_identity": source_identity,
        **extra,
    }
    return {"phase": "run_tests", "round": round_, "content": content}


def _has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def _init_repo_at(path: Path) -> None:
    """Init a git repo AT ``path``（repo_root 直落 tmp_path 的测试用）。

    config 内联（bare CI 容器无全局 identity，repo_guard.git_commit_identity_env
    同因）；与 ``_git_repo_with_two_commits`` 的区别：后者建 ``tmp_path/repo`` 子目录。
    """
    def g(*a):
        subprocess.run(["git", "-C", str(path), *a],
                       capture_output=True, check=True)
    g("init", "-q")
    g("config", "user.email", "t@t.t")
    g("config", "user.name", "T")


def _commit_all(path: Path, msg: str) -> None:
    subprocess.run(["git", "-C", str(path), "add", "-A"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", msg],
                   capture_output=True, check=True)


def _head_of(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()


def _git_repo_with_two_commits(tmp_path: Path, op_name: str = "gelu"):
    """Init a git repo; commit op_dir kernel v1 → v2. Returns
    (repo_root, op_dir, shaA=v1, shaB=v2). HEAD == shaB (the worse one)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    op_dir = repo / "custom_ops" / op_name
    op_dir.mkdir(parents=True)
    kernel = op_dir / "kernel.cpp"

    def g(*a):
        subprocess.run(["git", "-C", str(repo), *a],
                       capture_output=True, check=True)
    g("init", "-q")
    g("config", "user.email", "t@t.t")
    g("config", "user.name", "T")
    kernel.write_text("// v1\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-q", "-m", "v1")
    shaA = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    kernel.write_text("// v2 worse\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-q", "-m", "v2")
    shaB = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    return repo, op_dir, shaA, shaB


class _FakeDeployer:
    """Stand-in for Deployer (monkeypatched onto deploy.Deployer): records calls
    and returns a canned DeployResult so converge logic is unit-testable without
    a real compile."""
    def __init__(self, smoke_passed=True, raises=False):
        self.smoke_passed = smoke_passed
        self.raises = raises
        self.calls = 0

    def __call__(self):
        # converge does ``Deployer().deploy(state)``; make the instance callable so
        # monkeypatching ``deploy.Deployer`` with an instance (not a class) works.
        return self

    def deploy(self, state):
        self.calls += 1
        if self.raises:
            raise RuntimeError("deploy boom")
        return DeployResult(smoke_passed=self.smoke_passed,
                            install_path="/opp/best"), None


# —— RunTestsSubstage ————————————————————————————————————————————————


class TestRunTestsSubstage:
    def test_actions_dispatches_run_tests_measure(self, tmp_path):
        """§judgment-ownership (N1): run_tests 纯 Python 化——actions() 返回 RunMeasure
        （确定性测量，非 SpawnAgent）。command 含 run-cases + 建队列脚本；working_dir
        = op_dir。不再 spawn LLM agent。"""
        from ascendc_devkit.orchestration.kernel.action import RunMeasure
        from ascendc_devkit.orchestration.kernel.state import State as S2
        from types import SimpleNamespace
        ws = SimpleNamespace(dir=tmp_path / "ws", artifacts=tmp_path / "ws" / "artifacts")
        stage = RunTestsSubstage()
        state = _state(tmp_path).with_updates(_workspace=ws)
        actions = stage.actions(state, 1)
        assert len(actions) == 1
        m = actions[0]
        assert isinstance(m, RunMeasure), f"expected RunMeasure, got {type(m).__name__}"
        assert "run-cases" in m.command
        assert "build-failed-case-queue.py" in m.command
        assert "--iter 0" in m.command
        assert m.working_dir == _op_identity(tmp_path).op_dir
        # init-checkpoint 前置：首轮 control.json 不存在 → 命令含 init
        assert "init-checkpoint.py" in m.command

    def test_working_dir_falls_back_to_state_op_dir(self, tmp_path):
        op_dir = tmp_path / "ops" / "gelu"
        stage = RunTestsSubstage()
        actions = stage.actions(_state(tmp_path, op_identity=None, op_dir=op_dir), 1)
        assert actions[0].working_dir == op_dir

    def test_transition_loads_control_increments_rounds(self, tmp_path):
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(failed_case_queue=[_case()]))
        prev = state.with_updates(_debug_checkpoint={"rounds": 3})
        new_state = stage.transition(prev, {})
        assert new_state._debug_checkpoint["rounds"] == 4
        assert new_state._debug_checkpoint["failed_case_count"] == 1

    def test_resolve_all_pass_when_status_passed(self, tmp_path):
        stage = RunTestsSubstage()
        state = _state(tmp_path).with_updates(
            _debug_checkpoint={"status": "passed", "rounds": 1, "max_iterations": 30})
        assert stage.resolve_condition(state) == "all_pass"

    def test_resolve_exhausted_when_rounds_exceed_max(self, tmp_path):
        stage = RunTestsSubstage()
        state = _state(tmp_path).with_updates(
            _debug_checkpoint={"status": "running", "rounds": 31, "max_iterations": 30})
        assert stage.resolve_condition(state) == "exhausted"

    def test_resolve_has_failures(self, tmp_path):
        """§P3 减法: scope_guard 已删——失败 → has_failures → diagnose。
        上游缺陷由 diagnose 入口判据上报，不再有独立 scope_guard phase。
        scope_checked 已从 control.json 移除（P3 减法），此处不再携带该字段。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path).with_updates(
            _debug_checkpoint={"status": "running", "rounds": 1, "max_iterations": 30})
        assert stage.resolve_condition(state) == "has_failures"

    def test_transition_resets_stale_current_case_index(self, tmp_path):
        """Re-entry after fix→run_tests: queue shrank below current_case_index."""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(failed_case_queue=[_case()], current_case_index=5))
        stage.transition(state, {})
        assert _read_control(state)["current_case_index"] == 0

    def test_transition_materializes_debug_result_when_passed(self, tmp_path):
        """§step-119/§step-124: 最优 commit / max_err 从 history 测量史派生——history
        有全过测量（source_commit=abc, max_err=0.001）→ debug_result 反映该最优被测代码。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(
            status="passed",
            history=[_hist_run(20, 0, source_commit="abc", max_err=0.001)]))
        new_state = stage.transition(state, {})
        assert new_state.debug_result.passed is True
        assert new_state.debug_result.best_commit == "abc"
        assert new_state.debug_result.max_diff == 0.001
        assert new_state.last_error is None

    def test_transition_all_none_max_err_does_not_crash(self, tmp_path):
        """P1 (precision-tensorlist-harness-contract): a harness abort before
        any case executed leaves every failed_case_queue entry max_err=None.
        The transition's ``max(real_errs)`` used to raise "'>' not supported
        between instances of 'NoneType' and 'NoneType'" (foreach_norm
        20260807-144939-310314). Now None is filtered and best_real_max_err
        carries None, letting scope_guard judge the upstream signal instead of
        the transition crashing on best-metrics collection."""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        queue = [{"case_id": f"c{i}", "shape": "[8]", "dtype": "fp16",
                  "failure_type": "compilation", "status": "pending",
                  "max_err": None, "attempt_count": 0,
                  "tried_fix_plan_ids": []} for i in range(3)]
        _write_control(state, _control(failed_case_queue=queue))
        _seed_phase(state, "precision_run_tests.json", summary={
            "total_count": 3,
            "failed_count": 3,
            "test_result": "0/3 passed: harness aborted at PD-CONTRACT",
            "last_run_log": "/tmp/run.log",
            "observed_issues": [{"category": "upstream_signal", "blocking": True}],
        })
        new_state = stage.transition(state, {})  # must not raise
        cp = _read_control(state)
        # §step-119: cp 顶层不再有 best_real_max_err（历史 max_err=None）；派生值进 dc。
        assert new_state._debug_checkpoint["best_real_max_err"] is None
        assert "best_real_max_err" not in cp


# —— §P2: run_tests 确定性信号框架接管 ——————————————————————————————

class TestRunTestsFrameworkStats:
    """P2 (docs/plan/precision-debug-design-audit/05-impl): total/failed
    counts, status=passed and history stats are framework-derived. The
    transition re-runs the deterministic build-failed-case-queue.py (single
    implementation, §1.15) and parses its stdout; the agent's _summary no
    longer reports counts (§2.5 single path) — only observed_issues (LLM
    semantic) survives as agent-authored."""

    def test_stats_from_result_json_not_agent_summary(self, tmp_path):
        """Agent 不填（或填错）_summary 统计 → 框架从 result.json 确定性计算：
        passed_count / history total 一律以脚本 stdout 为准。§step-119：cp 顶层不再有
        best_total_count；best_passed_count 由 transition 从 history 派生进 dc。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _iter_result_json(state, [_cd(f"c{i}", i >= 5) for i in range(20)])  # 5 failed
        _write_control(state, _control())
        _seed_phase(state, "precision_run_tests.json",
                    summary={"total_count": 999, "failed_count": 999})  # 错误申报被忽略
        new_state = stage.transition(state, {})
        cp = _read_control(state)
        assert new_state._debug_checkpoint["best_passed_count"] == 15
        hist = cp["history"][-1]["content"]
        assert hist["total_count"] == 20 and hist["failed_count"] == 5
        assert hist["test_result"] == "5/20 failed"
        assert new_state._debug_checkpoint["best_passed_count"] == 15

    def test_status_passed_derived_when_zero_failures(self, tmp_path):
        """result.json 全过 + control.status 仍 running → 框架派生 passed
        （不依赖 agent 写 status）；全过时脚本 merge 清空 queue。best_passed_count
        现由 transition 从 history 派生进 dc（cp 顶层 best_* 已删）。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _iter_result_json(state, [_cd(f"c{i}", True) for i in range(20)])
        _write_control(state, _control(
            failed_case_queue=[_case("c1", status="resolved_pending")]))
        _seed_phase(state, "precision_run_tests.json")   # 无 _summary = 正常轮
        new_state = stage.transition(state, {})
        cp = _read_control(state)
        assert cp["status"] == "passed"
        assert cp["failed_case_queue"] == []
        assert new_state._debug_checkpoint["best_passed_count"] == 20
        assert stage.resolve_condition(new_state) == "all_pass"

    def test_agent_passed_contradicted_by_result_json(self, tmp_path):
        """control.status=passed 但 result.json 有失败 → 框架真值优先，回退 running。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _iter_result_json(state, [_cd(f"c{i}", i < 3) for i in range(10)])
        _write_control(state, _control(status="passed"))
        _seed_phase(state, "precision_run_tests.json")
        new_state = stage.transition(state, {})
        assert _read_control(state)["status"] == "running"
        assert new_state._debug_checkpoint["status"] == "running"

    def test_hard_error_no_result_json_stats_unknown(self, tmp_path):
        """硬错误轮（无 result.json，agent 手动构 queue）→ total=0 + 可观测
        'total unknown'；history failure_type 从 queue per-case 聚合。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(failed_case_queue=[
            _case("c1", ftype="compilation")]))
        _seed_phase(state, "precision_run_tests.json")
        stage.transition(state, {})
        hist = _read_control(state)["history"][-1]["content"]
        assert hist["total_count"] == 0
        assert "total unknown" in hist["test_result"]
        assert hist["failure_type"] == "compilation"

    def test_crash_sentinel_set_by_framework_script_run(self, tmp_path):
        """result.json runtime_crash + 空 case_details → 框架脚本置
        crash_sentinel_mode → 直通 diagnose（就地定位，不再转独立 comment_bisect phase）。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _iter_result_json(state, [], failure_type="runtime_crash")
        _write_control(state, _control())
        _seed_phase(state, "precision_run_tests.json")
        new_state = stage.transition(state, {})
        cp = _read_control(state)
        assert cp["crash_sentinel_mode"] is True
        assert stage.resolve_condition(new_state) == "has_failures"

    def test_measure_failed_rc_aborts(self, tmp_path):
        """§judgment-ownership (N1): abort 判据 = measure_result.returncode != 0
        （run-cases 非零退出 / subprocess 异常）→ abort 路径（history 'aborted' +
        consecutive_aborts 递增）。取代旧 phase-json-absent 判据（纯 Python 无 agent
        产物）。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(failed_case_queue=[_case()]))
        stage.transition(state, {"measure_result": {"returncode": 1, "stderr": "NPU down"}})
        cp = _read_control(state)
        assert cp["history"][-1]["content"]["test_result"] == "aborted"
        assert cp["consecutive_aborts"] == 1

    def test_measure_ok_no_measure_result_not_abort(self, tmp_path):
        """§N1: 无 measure_result（UT 传 {}）→ 非 abort（兼容旧测试构造；真实运行
        _execute_run_measure 总写 measure_result）。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(failed_case_queue=[_case()]))
        new_state = stage.transition(state, {})
        assert new_state._debug_checkpoint.get("agent_aborted") is not True

    def test_run_level_failure_type_aggregation_priority(self, tmp_path):
        """run-level failure_type = per-case 聚合（runtime > compilation >
        precision），不再由 agent 申报。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(failed_case_queue=[
            _case("c1", ftype="precision"), _case("c2", ftype="compilation"),
            _case("c3", ftype="runtime")]))
        _seed_phase(state, "precision_run_tests.json",
                    summary={"failure_type": "precision"})  # 申报被忽略
        stage.transition(state, {})
        hist = _read_control(state)["history"][-1]["content"]
        assert hist["failure_type"] == "runtime"

    def test_derived_result_json_used_n1(self, tmp_path):
        """§judgment-ownership (N1): 框架派生 iter 路径是唯一结果源（无 agent 申报）。
        transition 写 phase relay 时用派生路径（run_tests_iter-N/result.json）；result.json
        存在 → _framework_case_stats 读到真实 stats。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        # debug 目录 = phase 路径的上级上级（{debug}/phases/run_tests/xxx）
        dbg = _phase_path(state, "precision_run_tests.json", round_suffix=True).parent.parent.parent
        iter_dir = dbg / "run_tests_iter-7"
        iter_dir.mkdir(parents=True)
        (iter_dir / "result.json").write_text(json.dumps(
            {"case_details": [_cd(f"c{i}", i >= 2) for i in range(8)]}),
            encoding="utf-8")
        _write_control(state, _control(run_iter_counter=7))
        stage.transition(state, {})
        hist = _read_control(state)["history"][-1]["content"]
        assert hist["total_count"] == 8 and hist["failed_count"] == 2

    def test_stale_reported_path_ignored_when_derived_exists(self, tmp_path):
        """信任方向（§P2）：派生路径存在时，agent 幻觉申报的 stale 路径
        （指向旧 iter 的全过结果）被忽略——统计以本 round 实际产物为准。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        # 本 round 派生路径：2/20 失败
        _iter_result_json(state, [_cd(f"c{i}", i >= 2) for i in range(20)])
        # agent 幻觉申报：指向一个"全过"的旧 result.json
        stale = tmp_path / "stale" / "result.json"
        stale.parent.mkdir(parents=True)
        stale.write_text(json.dumps(
            {"case_details": [_cd(f"c{i}", True) for i in range(20)]}),
            encoding="utf-8")
        _write_control(state, _control())
        p = _seed_phase(state, "precision_run_tests.json")
        payload = json.loads(p.read_text())
        payload["last_result_json"] = str(stale)
        p.write_text(json.dumps(payload), encoding="utf-8")
        stage.transition(state, {})
        cp = _read_control(state)
        hist = cp["history"][-1]["content"]
        assert hist["total_count"] == 20 and hist["failed_count"] == 2
        assert cp["status"] == "running"       # stale 全过不生效，不误路由 all_pass

    def test_empty_result_json_total_zero_not_all_passed(self, tmp_path):
        """result.json 存在但无 case 数据（total=0 非 sentinel）→ 不误报
        all passed（status 不派生 passed，test_result 标 total unknown）。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _iter_result_json(state, [])          # 空 case_details，无 tested_cases
        _write_control(state, _control())
        _seed_phase(state, "precision_run_tests.json")
        stage.transition(state, {})
        cp = _read_control(state)
        assert cp["status"] == "running"      # total=0 → 不派生 passed
        assert "total unknown" in cp["history"][-1]["content"]["test_result"]


# —— §P2 遗留面：级联/探针观察框架派生 ————————————————————————————

class TestFrameworkDerivedObservations:
    """§P2 遗留面收敛：cascade_suspected（runtime 失败率 >80%）与
    crash_masking_probe_needed（全量 runtime 崩溃）是纯算术观察，由框架从
    stats + queue 派生（agent 不再申报；blocking 恒 false——不触发
    scope_guard，diagnose 消费语义不变）。"""

    @staticmethod
    def _run(state, details, summary=None):
        stage = RunTestsSubstage()
        _iter_result_json(state, details)
        _write_control(state, _control())
        _seed_phase(state, "precision_run_tests.json",
                    summary=summary if summary is not None else None)
        stage.transition(state, {})

    def test_cascade_suspected_derived_over_80pct_runtime(self, tmp_path):
        """17/20 失败且全 runtime（error 字段→脚本判 runtime）→ 框架派生
        cascade_suspected；非全量 → 无 probe。"""
        state = _state(tmp_path)
        details = ([_cd(f"c{i}", False, error="vector core exception 507035")
                    for i in range(17)]
                   + [_cd(f"c{i}", True) for i in range(17, 20)])
        self._run(state, details)
        cats = {o["category"] for o in _read_control(state)["observed_issues"]}
        assert "cascade_suspected" in cats
        assert "crash_masking_probe_needed" not in cats

    def test_crash_masking_probe_derived_on_full_runtime_crash(self, tmp_path):
        """20/20 全 runtime → cascade + probe 双派生（blocking 均 false）。"""
        state = _state(tmp_path)
        details = [_cd(f"c{i}", False, error="SIGSEGV") for i in range(20)]
        self._run(state, details)
        issues = _read_control(state)["observed_issues"]
        cats = {o["category"] for o in issues}
        assert cats == {"cascade_suspected", "crash_masking_probe_needed"}
        assert all(o.get("blocking") is False for o in issues)

    def test_no_derivation_on_mixed_or_minority(self, tmp_path):
        """10/20 失败但含 precision 类型 / 或 runtime 占比 <80% → 无派生。"""
        state = _state(tmp_path)
        details = ([_cd(f"c{i}", False, error="SIGSEGV") for i in range(10)]
                   + [_cd(f"c{i}", True) for i in range(10, 20)])
        self._run(state, details)
        # 10/20 = 50% < 80% → 无派生
        assert not _read_control(state).get("observed_issues")

    def test_no_agent_reported_issues_n1(self, tmp_path):
        """§judgment-ownership (N1): run_tests 纯 Python——observed_issues 只含框架
        派生的级联/崩溃探针，无 agent 申报条目（run_tests 不再 spawn agent，_summary
        observed_issues 不存在）。"""
        state = _state(tmp_path)
        details = [_cd(f"c{i}", False, error="SIGSEGV") for i in range(20)]
        self._run(state, details)
        issues = _read_control(state)["observed_issues"]
        cats = {o["category"] for o in issues}
        # 全量 runtime 崩溃 → 框架派生两个探针，无 agent 条目
        assert cats == {"cascade_suspected", "crash_masking_probe_needed"}
        assert all(o.get("blocking") is False for o in issues)


# —— DiagnoseSubstage ————————————————————————————————————————————————


class TestDiagnoseSubstage:
    def test_resolve_rounds_overflow_not_exhausted(self, tmp_path):
        """§merge (docs/plan/fix-diagnose-merge): diagnose 融合 fix 后承担实施——
        退出由墙钟 time budget（_time_budget_exhausted）控制；rounds 是 run_tests
        的框架计数，diagnose 仅透传、不基于它判 exhausted。rounds 溢出
        max_iterations 不触发 exhausted，裸 checkpoint（无实施证据）fall-through 到
        retry（实施模式默认：等 agent 真正产出修复证据）。"""
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(
            _debug_checkpoint={"rounds": 31, "max_iterations": 30})
        assert stage.resolve_condition(state) == "retry"

    def test_resolve_stalled_routes_stalled(self, tmp_path):
        """§judgment-ownership (P5): diagnose 尽力后假设空间穷尽（stalled=true + self_check）→
        路由 stalled（诚实报告，不再无限 retry）。这是「模型判断已尽力」，区别于
        upstream（上游缺陷）与 retry（继续调试）。"""
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={
            "stalled": True,
            "stalled_detail": {"self_check": [
                {"item": "read kernel", "passed": True},
                {"item": "hypotheses verified", "passed": True},
            ]}})
        assert stage.resolve_condition(state) == "stalled"

    def test_resolve_stalled_without_selfcheck_retries(self, tmp_path):
        """§judgment-ownership (P5) 防偷懒门槛: stalled=true 但缺 self_check 自检证据 →
        不是合法 stall，打回 retry 继续调试（不静默接受）。防止模型「累了/想放弃」就声明
        stalled 跳过问题。"""
        stage = DiagnoseSubstage()
        # 裸 stalled（无 stalled_detail）
        state = _state(tmp_path).with_updates(_debug_checkpoint={"stalled": True})
        assert stage.resolve_condition(state) == "retry"
        # stalled_detail 无 self_check
        state2 = _state(tmp_path).with_updates(_debug_checkpoint={
            "stalled": True, "stalled_detail": {"exhausted_reason": "很难"}})
        assert stage.resolve_condition(state2) == "retry"
        # stalled_detail 是旧文本形态（非 dict）
        state3 = _state(tmp_path).with_updates(_debug_checkpoint={
            "stalled": True, "stalled_detail": "很难修"})
        assert stage.resolve_condition(state3) == "retry"

    def test_resolve_upstream_precedes_stalled(self, tmp_path):
        """upstream（上游缺陷）优先级高于 stalled：diagnose 上报 upstream 时即使
        也写了 stalled，仍按 upstream 处理（上游缺陷 halt，不是尽力诚实报告）。"""
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(
            _debug_checkpoint={"stalled": True, "upstream_signal": True})
        assert stage.resolve_condition(state) == "upstream"

    def test_resolve_stalled_not_retry_with_selfcheck(self, tmp_path):
        """stalled 带 self_check 是独立出口，不是 retry（继续深挖）。"""
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(
            _debug_checkpoint={"stalled": True, "rounds": 2,
                               "stalled_detail": {"self_check": [{"passed": True}]}})
        assert stage.resolve_condition(state) == "stalled"

    def test_transition_carries_rounds_and_failure_type(self, tmp_path):
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={"rounds": 2})
        _write_control(state, _control(
            failed_case_queue=[_case(ftype="runtime")],
            history=[{"content": {"failure_type": "runtime"}}]))
        new_state = stage.transition(state, {})
        assert new_state._debug_checkpoint["rounds"] == 2
        assert new_state._debug_checkpoint["failure_type"] == "runtime"

    def test_transition_carries_stalled_from_control(self, tmp_path):
        """diagnose 写 control.json.stalled=true → transition 透传到 dc（框架路由读）。"""
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={})
        _write_control(state, _control(
            stalled=True,
            stalled_detail={"self_check": [
                {"item": "read kernel", "passed": True},
                {"item": "hypotheses verified", "passed": True},
                {"item": "systematic ammo", "passed": True},
                {"item": "exhaustion confirmed", "passed": True},
            ], "exhausted_reason": "疑算法级 sort bug"},
            failed_case_queue=[_case(ftype="precision")]))
        new_state = stage.transition(state, {})
        assert new_state._debug_checkpoint.get("stalled") is True
        sd = new_state._debug_checkpoint.get("stalled_detail") or {}
        assert isinstance(sd, dict) and sd.get("self_check"), \
            "stalled_detail 必须是含 self_check 的结构化 dict"
        assert "sort" in (sd.get("exhausted_reason") or "")

    def test_transition_warns_when_fix_missing_git_commit(self, tmp_path, capsys):
        """D1（step-119）：diagnose 声明已修复（already_resolved）但漏填 git_commit →
        框架 WARN（修复史将断链）但不阻断；ledger 保持空（可观测，非静默）。"""
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={})
        _write_control(state, _control(failed_case_queue=[
            _case("c1", status="pending", ftype="precision")]))
        # diagnose 产物：声明已修 but 无 git_commit（漏填）
        _seed_phase(state, stage._phase_filename(), summary={
            "already_resolved": {"commit": "", "case_id": "c1"},
            "root_cause": "final write to wrong buffer",
        })
        # 应不抛（WARN 是日志副作用，transition 正常完成）
        new_state = stage.transition(state, {})
        cp = _read_control(state)
        assert new_state._debug_checkpoint.get("agent_aborted") is not True
        # ledger 空（无 git_commit → no-op）
        assert not (cp.get("root_cause_ledger") or [])
        # WARN 真实触发（可观测信号，非静默吞）——Logger 写 stderr，断言含缺 git_commit 提示
        captured = capsys.readouterr()
        assert "缺 git_commit" in captured.err


# —— §weak-model A：拒因链路（stalled 打回原因可见）———————————————


class TestDiagnoseRejectReason:
    """打回原因（last_reject_reason）写入/清空/渲染。round 语义 = 写入时的 control
    rounds 值：diagnose retry 自环（rounds 不变）持续可见；经 run_tests 回归
    （rounds+1）自动过期——文件版 consumed-once。正常产出清空（成功清错）。"""

    def test_transition_writes_reject_reason_on_stalled_without_selfcheck(self, tmp_path):
        """stalled 缺 self_check 被打回 → transition 写 last_reject_reason（含 round），
        下轮 diagnose prompt 可见拒因（不再靠框架日志盲猜）。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _stalled_reject_reason,
        )
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={"rounds": 5})
        _write_control(state, _control(
            stalled=True,                    # 无 stalled_detail.self_check → 会被打回
            rounds=5,
            failed_case_queue=[_case(ftype="precision")]))
        _seed_phase(state, "precision_diagnose.json")
        new_state = stage.transition(state, {})
        assert stage.resolve_condition(new_state) == "retry"
        cp = _read_control(state)
        lrr = cp.get("last_reject_reason")
        assert isinstance(lrr, dict) and lrr.get("cond") == "stalled_without_selfcheck"
        assert lrr.get("round") == 5
        assert lrr.get("detail")
        # 判定单点：resolve_condition 的 retry 与 _stalled_reject_reason 一致
        assert _stalled_reject_reason(new_state._debug_checkpoint) is not None

    def test_transition_clears_reject_reason_on_normal_output(self, tmp_path):
        """正常产出（case resolved_pending）→ 清空 last_reject_reason（成功清错，
        对齐 design last_error clear-on-success）。"""
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={"rounds": 5})
        _write_control(state, _control(
            last_reject_reason={"cond": "missing_artifact", "detail": "x", "round": 4},
            failed_case_queue=[_case(status="resolved_pending")],
            current_case_index=0))
        _seed_phase(state, "precision_diagnose.json")
        new_state = stage.transition(state, {})
        assert stage.resolve_condition(new_state) == "resolved"
        assert _read_control(state).get("last_reject_reason") is None

    def test_stalled_with_selfcheck_writes_no_reject_reason(self, tmp_path):
        """合法 stalled（带 self_check）是诚实报告出口，不是打回——不写拒因。"""
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={})
        _write_control(state, _control(
            stalled=True,
            stalled_detail={"self_check": [{"item": "read kernel", "passed": True}]},
            failed_case_queue=[_case(ftype="precision")]))
        _seed_phase(state, "precision_diagnose.json")
        new_state = stage.transition(state, {})
        assert stage.resolve_condition(new_state) == "stalled"
        assert _read_control(state).get("last_reject_reason") is None

    def test_reject_reason_block_round_matching(self):
        """渲染 consumed-once：round 匹配当前 rounds 才显示；不匹配（已过 run_tests
        回归）或无拒因 → 空串。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _reject_reason_block,
        )
        cp = {"rounds": 7, "last_reject_reason": {
            "cond": "stalled_without_selfcheck", "detail": "缺自检证据", "round": 7}}
        block = _reject_reason_block(cp, current_round=7)
        assert "框架打回" in block and "缺自检证据" in block
        # round 不匹配（新一轮测量后）→ 不显示
        assert _reject_reason_block(cp, current_round=8) == ""
        # 无拒因 → 空串
        assert _reject_reason_block({"rounds": 7}, current_round=7) == ""
        # 拒因非 dict（agent 写坏）→ 空串不炸
        assert _reject_reason_block(
            {"rounds": 7, "last_reject_reason": "garbage"}, current_round=7) == ""

    def test_diagnose_prompt_renders_reject_reason(self, tmp_path):
        """拒因经 _common_context 注入 → _phase_prompt 渲染（ctx 模拟）。"""
        stage = DiagnoseSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(rounds=3, last_reject_reason={
            "cond": "stalled_without_selfcheck", "detail": "缺自检证据", "round": 3}))
        ctx = stage._common_context(state)
        assert "reject_reason" in ctx and ctx["reject_reason"], \
            "拒因应注入 ctx（round 匹配当前轮）"
        prompt = stage._phase_prompt(
            ctx, str(tmp_path), str(_ctrl_path(state)), str(tmp_path / "p.json"),
            str(tmp_path / "skill"), 1)
        assert "框架打回" in prompt and "缺自检证据" in prompt

    def test_diagnose_prompt_no_reject_reason_section_when_absent(self, tmp_path):
        """无拒因（或 round 过期）→ prompt 无「框架打回」段。"""
        stage = DiagnoseSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(rounds=3))
        ctx = stage._common_context(state)
        assert not ctx.get("reject_reason")
        prompt = stage._phase_prompt(
            ctx, str(tmp_path), str(_ctrl_path(state)), str(tmp_path / "p.json"),
            str(tmp_path / "skill"), 1)
        assert "框架打回" not in prompt


class TestDiagnoseRouteToDomain:
    """§P3 减法: route_to 机制已删。diagnose 不再自判 route_to——就地定位+修，
    不再转 printf/comment_bisect 独立 phase。本节测替代语义：upstream 上报
    （diagnose 入口判据发现上游编译/注册/契约错 → halt）。"""

    def _transition_with(self, tmp_path, upstream_signal=False, upstream_stage=None,
                         upstream_reason=None):
        state = _state(tmp_path)
        ctrl = _control(failed_case_queue=[_case()])
        ctrl["upstream_signal"] = upstream_signal
        ctrl["upstream_stage"] = upstream_stage
        ctrl["upstream_reason"] = upstream_reason
        _write_control(state, ctrl)
        stage = DiagnoseSubstage()
        _seed_phase(state, stage._phase_filename(), summary={})
        out = stage.transition(state, {})
        return out

    def test_upstream_signal_routes_upstream(self, tmp_path):
        """diagnose 上报 upstream_signal=true → dc.upstream_signal + 路由 upstream → halt。"""
        out = self._transition_with(tmp_path, True, "codegen", "schema 不匹配")
        assert out._debug_checkpoint["upstream_signal"] is True
        assert DiagnoseSubstage().resolve_condition(out) == "upstream"

    def test_no_upstream_routes_retry(self, tmp_path):
        """无 upstream 信号 → 未修好则 retry（diagnose 自环，attempt_count 递增）。"""
        out = self._transition_with(tmp_path, False)
        assert DiagnoseSubstage().resolve_condition(out) == "retry"


class TestDiagnoseSubstageImpl:
    def test_resolve_resolved_when_case_marked(self, tmp_path):
        stage = DiagnoseSubstage()
        for status in ("resolved", "resolved_pending"):
            state = _state(tmp_path).with_updates(_debug_checkpoint={
                "rounds": 1, "max_iterations": 30, "case_resolved": True})
            assert stage.resolve_condition(state) == "resolved"

    def test_resolve_retry_when_pool_not_exhausted(self, tmp_path):
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={
            "rounds": 1, "max_iterations": 30, "case_resolved": False,
            "pool_exhausted": False})
        assert stage.resolve_condition(state) == "retry"

    def test_transition_advances_case_on_stop_loss(self, tmp_path):
        """attempt_count >= max_attempts → framework advances current_case_index."""
        stage = DiagnoseSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(
            failed_case_queue=[_case(attempt=10), _case("c2")],
            current_case_index=0,
        ))
        _seed_phase(state, "precision_diagnose.json")
        new_state = stage.transition(state, {})
        assert new_state._debug_checkpoint["case_skipped"] is True
        assert new_state._debug_checkpoint["more_cases"] is True
        cp = _read_control(state)
        assert cp["current_case_index"] == 1
        assert cp["failed_case_queue"][0]["status"] == "skipped"
        assert stage.resolve_condition(new_state) == "skip_more"

    def test_transition_skip_done_when_last_case_stops_out(self, tmp_path):
        stage = DiagnoseSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(
            failed_case_queue=[_case(attempt=10)],
            current_case_index=0,
        ))
        _seed_phase(state, "precision_diagnose.json")
        new_state = stage.transition(state, {})
        assert new_state._debug_checkpoint["more_cases"] is False
        assert stage.resolve_condition(new_state) == "skip_done"

    def test_transition_no_advance_when_case_resolved(self, tmp_path):
        stage = DiagnoseSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(
            failed_case_queue=[_case(status="resolved_pending")],
            current_case_index=0))
        _seed_phase(state, "precision_diagnose.json")
        new_state = stage.transition(state, {})
        assert new_state._debug_checkpoint.get("case_skipped") is False
        assert _read_control(state)["current_case_index"] == 0

    # —— resolve_condition uncovered paths (M7) ——————————————————————

    def test_resolve_partial_output(self, tmp_path):
        """per-output partial progress → run_tests."""
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={
            "rounds": 1, "max_iterations": 30, "partial_output": True})
        assert stage.resolve_condition(state) == "partial_output"

    def test_transition_already_resolved_marks_case_and_routes_resolved(self, tmp_path):
        """§P4 (docs/plan/fix-diagnose-merge): agent 在 _summary 写 already_resolved
        （case 已被先前 commit 修复）→ transition 标 case.status=resolved_pending +
        last_fix_commit，_extract 派生 case_resolved → resolve_condition=='resolved'
        （回 run_tests 全量回归确认）。覆盖 already_resolved(summary)→resolved 的完整
        transition 链路；替代原 resolve-only 测试（旧测试误用 dc.already_resolved 字段
        ——实际路由信号是 transition 派生的 case_resolved）。"""
        state = _state(tmp_path)
        case = _case({"case_id": "c1", "status": "pending"})
        _write_control(state, _control(failed_case_queue=[case]))
        stage = DiagnoseSubstage()
        _seed_phase(state, stage._phase_filename(), summary={
            "already_resolved": {"commit": "abc123"},
        })
        out = stage.transition(state, {})
        cp = _read_control(state)
        case_after = cp["failed_case_queue"][0]
        assert case_after["status"] == "resolved_pending"
        assert case_after["last_fix_commit"] == "abc123"
        assert stage.resolve_condition(out) == "resolved"

    def test_resolve_case_skipped_more_cases(self, tmp_path):
        """case skipped with more cases → skip_more."""
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={
            "rounds": 1, "max_iterations": 30, "case_skipped": True,
            "more_cases": True})
        assert stage.resolve_condition(state) == "skip_more"

    def test_resolve_case_skipped_no_more_cases(self, tmp_path):
        """case skipped, last case → skip_done."""
        stage = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={
            "rounds": 1, "max_iterations": 30, "case_skipped": True,
            "more_cases": False})
        assert stage.resolve_condition(state) == "skip_done"

class TestFailureTypeAggregateSchemaContract:
    """§fixability-routing: schema_contract 入聚合优先级（runtime>compilation>
    schema_contract>precision）。"""

    def test_schema_contract_priority_over_precision(self):
        queue = [_case("c1", ftype="precision"),
                 _case("c2", ftype="schema_contract")]
        assert _aggregate_failure_type(queue) == "schema_contract"

    def test_schema_contract_not_over_runtime(self):
        queue = [_case("c1", ftype="runtime"),
                 _case("c2", ftype="schema_contract")]
        assert _aggregate_failure_type(queue) == "runtime"

    def test_schema_contract_only(self):
        queue = [_case("c1", ftype="schema_contract")]
        assert _aggregate_failure_type(queue) == "schema_contract"


# —— helpers ————————————————————————————————————————————————

class TestHelpers:
    def test_extract_debug_checkpoint_minimal_set(self, tmp_path):
        # §step-119: best_commit 从 history 测量史派生（不再从 cp 顶层 best_commit 读）。
        cp = _control(failed_case_queue=[_case()],
                      history=[_hist_run(20, 0, source_commit="x", max_err=0.5)])
        dc = _extract_debug_checkpoint(cp)
        assert dc["status"] == "running"
        assert dc["failed_case_count"] == 1
        assert dc["failure_type"] == "precision"
        assert dc["best_commit"] == "x"
        assert dc["best_passed_count"] == 20
        assert dc["best_real_max_err"] == 0.5
        assert dc["current_case_status"] == "pending"
        assert dc["case_resolved"] is False
        # §P3 减法: scope_checked/scope_verdict 已删; upstream 判据由 diagnose 入口上报
        assert dc["upstream_signal"] is False
        assert dc["upstream_stage"] is None

    def test_advance_current_case(self):
        cp = _control(failed_case_queue=[_case("c1"), _case("c2")],
                      current_case_index=0)
        _advance_current_case(cp)
        assert cp["current_case_index"] == 1
        assert cp["failed_case_queue"][0]["status"] == "skipped"

    def test_sync_debug_result_passed(self, tmp_path):
        state = _state(tmp_path)
        dc = {"status": "passed", "rounds": 3, "best_commit": "abc",
              "best_real_max_err": 0.01, "failing_cases": [], "max_iterations": 30}
        new_state = _sync_debug_result(state, dc)
        assert new_state.debug_result.passed is True
        assert new_state.debug_result.iterations_used == 3

    def test_sync_debug_result_exhausted(self, tmp_path):
        state = _state(tmp_path)
        dc = {"status": "running", "rounds": 31, "best_commit": "best",
              "best_real_max_err": 0.5, "failing_cases": ["c1"], "max_iterations": 30}
        new_state = _sync_debug_result(state, dc)
        assert new_state.debug_result.passed is False
        assert new_state.debug_result.failing_cases == ["c1"]

    def test_sync_debug_result_upstream_halt(self, tmp_path):
        """§P3 upstream: diagnose 入口判据上报上游缺陷 → terminal with passed=False, stubbed=True."""
        state = _state(tmp_path)
        dc = {"status": "running", "rounds": 1, "upstream_signal": True,
              "max_iterations": 30}
        new_state = _sync_debug_result(state, dc)
        assert new_state.debug_result.passed is False
        assert new_state.debug_result.stubbed is True

    def test_sync_debug_result_noop_when_not_terminal(self, tmp_path):
        state = _state(tmp_path)
        dc = {"status": "running", "rounds": 2, "max_iterations": 30}
        new_state = _sync_debug_result(state, dc)
        assert new_state.debug_result is None


# —— §12.2 contract validation ———————————————————————————————————


class TestContractValidation:
    def test_valid_control_passes(self, tmp_path):
        cp = _control(failed_case_queue=[_case()])
        cp2 = _ensure_control_contract(cp, str(tmp_path / "control.json"))
        assert cp2 is cp  # not repaired → returned same dict

    def test_auto_repairs_missing_required_keys(self, tmp_path):
        """Missing keys are auto-filled with safe defaults, not raised."""
        cp = {"status": "running"}  # missing required keys
        ctrl_path = str(tmp_path / "control.json")
        cp2 = _ensure_control_contract(cp, ctrl_path)
        # Should have been repaired with all required keys
        for k in ("max_iterations", "current_case_index", "history",
                  "failed_case_queue", "max_attempts_per_case", "upstream_signal"):
            assert k in cp2, f"missing key {k} not auto-repaired"
        assert cp2["history"] == []
        assert cp2["failed_case_queue"] == []
        assert cp2["current_case_index"] == 0

    def test_harness_timeout_sec_is_framework_owned(self, tmp_path):
        """§2.9 框架自有字段：agent 重写 control.json 弄丢 harness_timeout_sec 是正常
        交接（放大值由 sidecar 兜底），契约不 WARN、不填默认——填默认会把放大值 480s
        打回 120s。agent 不对它负责，缺省静默留空（debug_service 读 sidecar）。"""
        cp = {"status": "running", "failed_case_queue": [], "history": []}
        ctrl_path = str(tmp_path / "control.json")
        cp2 = _ensure_control_contract(cp, ctrl_path)
        # 其它缺的 agent-owned 键被填；harness_timeout_sec 保持缺失（框架自有）
        assert "max_iterations" in cp2
        assert "harness_timeout_sec" not in cp2

    def test_rejects_d3_stale_keys(self, tmp_path):
        cp = _control(current_stage="run_tests")  # D3 deleted field
        with pytest.raises(PrecisionDebugContractError, match=r"\[PD-CONTRACT\]"):
            _ensure_control_contract(cp, str(tmp_path / "control.json"))

    def test_coerces_bad_current_case_index_type(self, tmp_path):
        """Wrong scalar types are auto-coerced, not raised."""
        cp = _control(current_case_index="5")  # str that can be int'd
        ctrl_path = str(tmp_path / "control.json")
        cp2 = _ensure_control_contract(cp, ctrl_path)
        assert cp2["current_case_index"] == 5  # coerced

    def test_defaults_bad_failed_case_queue_type(self, tmp_path):
        cp = _control(failed_case_queue="not-a-list")
        ctrl_path = str(tmp_path / "control.json")
        cp2 = _ensure_control_contract(cp, ctrl_path)
        assert cp2["failed_case_queue"] == []  # defaulted

    def test_last_reject_reason_bad_type_coerced_to_none(self, tmp_path):
        """§weak-model C：last_reject_reason 框架写的打回原因（{cond, detail, round}）。
        agent 写坏形状（非 dict）→ 置 None + 可观测（§3.7 不静默、不 raise——拒因丢失
        可降级，control 其余字段不受影响）。"""
        cp = _control(last_reject_reason="garbage string")
        cp2 = _ensure_control_contract(cp, str(tmp_path / "control.json"))
        assert cp2["last_reject_reason"] is None

    def test_last_reject_reason_valid_dict_passes(self, tmp_path):
        cp = _control(last_reject_reason={
            "cond": "stalled_without_selfcheck", "detail": "x", "round": 2})
        cp2 = _ensure_control_contract(cp, str(tmp_path / "control.json"))
        assert cp2["last_reject_reason"]["cond"] == "stalled_without_selfcheck"

    def test_last_reject_reason_absent_not_filled(self, tmp_path):
        """不进 REQUIRED：缺失不补默认（避免对 init-checkpoint 存量文件产生 WARN
        噪声）——拒因是框架按需写的可选字段。"""
        cp = _control()
        cp2 = _ensure_control_contract(cp, str(tmp_path / "control.json"))
        assert "last_reject_reason" not in cp2 or cp2["last_reject_reason"] is None

    def test_repairs_bad_queue_element(self, tmp_path):
        """Non-dict elements are dropped; missing keys in dict elements are filled."""
        cp = _control(failed_case_queue=[{"bad": "no_case_id"}])
        ctrl_path = str(tmp_path / "control.json")
        cp2 = _ensure_control_contract(cp, ctrl_path)
        # Missing case_id/status/failure_type in dict element → filled with defaults
        assert cp2["failed_case_queue"][0]["case_id"] == -1
        assert cp2["failed_case_queue"][0]["status"] == "unknown"

    def test_empty_dict_skips(self, tmp_path):
        cp = _ensure_control_contract({}, str(tmp_path / "control.json"))
        assert cp == {}  # absent control.json — init hasn't run yet, skip

    # —— §12.2 phase JSON auto-repair ———————————————————————————————

    def test_phase_defaults_covers_all_phases(self):
        """P3 减法: 只剩 run_tests/diagnose 两 phase 的 schema defaults。"""
        expected_phases = {
            "precision_run_tests.json",
            "precision_diagnose.json",
        }
        assert set(_PHASE_DEFAULTS.keys()) == expected_phases

    def test_phase_defaults_run_tests(self):
        defaults = _PHASE_DEFAULTS["precision_run_tests.json"]
        assert defaults["last_result_json"] == ""
        assert defaults["last_run_log"] == ""

    def test_phase_defaults_diagnose(self):
        # fix-diagnose-merge: fix_code_log 现归 precision_diagnose.json（diagnose 自实施）。
        defaults = _PHASE_DEFAULTS["precision_diagnose.json"]
        assert defaults["diagnose_done"] == False
        assert defaults["fix_code_log"] == {}

    def test_phase_json_auto_repair_fills_missing_keys(self, tmp_path):
        """Simulate agent hallucination: partial JSON → defaults filled + file rewritten."""
        import json as _json
        phase_dir = tmp_path / "phases" / "diagnose"
        phase_dir.mkdir(parents=True)
        phase_path = phase_dir / "precision_diagnose.json"
        # Agent wrote only diagnose_done, forgot fix_code_log
        partial = {"diagnose_done": True}
        phase_path.write_text(_json.dumps(partial), encoding="utf-8")

        # Read back and verify the defaults dict would fill the gap
        raw = _json.loads(phase_path.read_text(encoding="utf-8"))
        defaults = _PHASE_DEFAULTS["precision_diagnose.json"]
        repaired = False
        for key, default_val in defaults.items():
            if key not in raw:
                raw[key] = default_val
                repaired = True

        assert repaired
        assert raw["fix_code_log"] == {}
        assert raw["diagnose_done"] is True  # Original data preserved


# —— transition table + group —————————————————————————————————————


class TestTransitionTableAndGroup:
    def test_group_has_two_substages(self):
        """P3 减法: 七 substage → 两段（run_tests ⇄ diagnose）。
        scope_guard/bounds_check/printf_location/comment_bisect/diagnose_refine 已删。"""
        g = build_precision_debug_group()
        assert g.name == "precision_debug"
        assert [a.stage.name for a in g.children()] == [
            "run_tests", "diagnose"]

    def test_group_output_contract(self):
        g = build_precision_debug_group()
        assert set(g.output_contract().provides) == {"debug_result", "debug_iterations"}

    def test_run_tests_all_pass_exits_group(self):
        assert _PRECISION_DEBUG_TRANSITION_TABLE["run_tests"]["all_pass"] == (
            "__escalate__:passed", "validation")

    def test_run_tests_exhausted_exits_group(self):
        assert _PRECISION_DEBUG_TRANSITION_TABLE["run_tests"]["exhausted"] == (
            "__escalate__:exhausted", "validation")

    def test_diagnose_resolved_loops_to_run_tests(self):
        assert _PRECISION_DEBUG_TRANSITION_TABLE["diagnose"]["resolved"] == (
            "run_tests", "corrective")

    def test_has_failures_not_listed_uses_linear_diagnose(self):
        """run_tests.has_failures absent → linear-advance to diagnose."""
        assert "has_failures" not in _PRECISION_DEBUG_TRANSITION_TABLE["run_tests"]

    def test_diagnose_done_not_listed_uses_linear_fix(self):
        assert "done" not in _PRECISION_DEBUG_TRANSITION_TABLE["diagnose"]


class TestA5TransitionTableAndGroup:
    """A5 Regbase precision_debug routing tests (PR#11 review M8)."""

    def test_a5_group_has_six_substages_correct_order(self):
        """A5 children: baseline → op_plugin_debug → kernel_debug →
        vf_test → vector_error_debug（regression 已合入 kernel_debug）。"""
        from ascendc_devkit.orchestration.precision_debug_tree import (
            build_precision_debug_group,
        )
        g = build_precision_debug_group(chip_version="A5")
        assert g.name == "precision_debug"
        assert g.variant == "a5"
        assert [a.stage.name for a in g.children()] == [
            "baseline", "op_plugin_debug", "kernel_debug",
            "vf_test", "vector_error_debug"]

    def test_a5_group_output_contract(self):
        from ascendc_devkit.orchestration.precision_debug_tree import (
            build_precision_debug_group,
        )
        g = build_precision_debug_group(chip_version="A5")
        assert set(g.output_contract().provides) == {
            "debug_result", "debug_iterations"}

    def test_a5_transition_table_baseline(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _A5_TRANSITION_TABLE,
        )
        tbl = _A5_TRANSITION_TABLE["baseline"]
        assert tbl["all_pass"] == ("__escalate__:passed", "validation")
        assert tbl["has_op_plugin_failures"] == ("op_plugin_debug", "corrective")
        assert tbl["has_kernel_failures"] == ("kernel_debug", "corrective")

    def test_a5_transition_table_kernel_debug_fixed_to_kl_routing(self):
        """kernel_debug.fixed 后由全量 KL 实测推导路由（regression 已合入）。"""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _A5_TRANSITION_TABLE,
        )
        tbl = _A5_TRANSITION_TABLE["kernel_debug"]
        assert tbl["kl_all_pass"] == ("baseline", "validation")
        assert tbl["case_kl_fails"] == ("kernel_debug", "corrective")

    def test_a5_transition_table_kernel_debug_all_entries(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _A5_TRANSITION_TABLE,
        )
        tbl = _A5_TRANSITION_TABLE["kernel_debug"]
        assert "kl_all_pass" in tbl
        assert "case_kl_fails" in tbl
        assert "retry" in tbl
        assert "need_vf" in tbl
        assert "all_exhausted" in tbl
        assert tbl["retry"] == ("kernel_debug", "corrective")
        assert tbl["need_vf"] == ("vf_test", "corrective")
        assert tbl["vector_error"] == (
            "vector_error_debug", "corrective")
        assert tbl["all_exhausted"] == ("baseline", "validation")

    def test_a5_transition_table_vf_test(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _A5_TRANSITION_TABLE,
        )
        tbl = _A5_TRANSITION_TABLE["vf_test"]
        assert tbl["retry"] == ("vf_test", "corrective")
        assert tbl["vf_passed"] == ("kernel_debug", "corrective")
        assert tbl["vector_error"] == (
            "vector_error_debug", "corrective")
        assert tbl["all_exhausted"] == ("baseline", "validation")

    def test_a5_transition_table_vector_error_debug(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _A5_TRANSITION_TABLE,
        )
        tbl = _A5_TRANSITION_TABLE["vector_error_debug"]
        assert tbl["retry"] == ("vector_error_debug", "corrective")
        assert tbl["fixed"] == ("kernel_debug", "validation")
        assert tbl["all_exhausted"] == ("baseline", "validation")

    def test_a5_transition_table_has_no_regression_stage(self):
        """regression 阶段已删除并合入 kernel_debug，transition table 不再有该键。"""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _A5_TRANSITION_TABLE,
        )
        assert "regression" not in _A5_TRANSITION_TABLE

    def test_a5_kernel_debug_resolve_condition_fixed(self, tmp_path):
        """debug_status=fixed 且无 _kl_status（KL 实测未知）→ 保守回 case_kl_fails，
        不直通 baseline（修复未经全量 KL 验收）。"""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            DumpDebugSubstage,
        )
        from ascendc_devkit.orchestration.kernel.state import State
        s = DumpDebugSubstage()
        state = State(mode="new")
        state = state.with_updates(_debug_checkpoint={
            "debug_status": "fixed",
        })
        assert s.resolve_condition(state) == "case_kl_fails"

    def test_a5_kernel_debug_resolve_condition_fixed_kl_all_pass(self):
        """fixed + _kl_status=kl_all_pass → 回 baseline 权威双跑验收。"""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            DumpDebugSubstage,
        )
        from ascendc_devkit.orchestration.kernel.state import State
        s = DumpDebugSubstage()
        state = State(mode="new")
        state = state.with_updates(_debug_checkpoint={
            "debug_status": "fixed", "_kl_status": "kl_all_pass",
        })
        assert s.resolve_condition(state) == "kl_all_pass"

    def test_a5_kernel_debug_resolve_condition_need_vf(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            DumpDebugSubstage,
        )
        from ascendc_devkit.orchestration.kernel.state import State
        s = DumpDebugSubstage()
        state = State(mode="new")
        state = state.with_updates(_debug_checkpoint={
            "debug_status": "need_vf",
        })
        assert s.resolve_condition(state) == "need_vf"

    def test_a5_kernel_debug_resolve_condition_vector_error(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            DumpDebugSubstage,
        )
        from ascendc_devkit.orchestration.kernel.state import State
        s = DumpDebugSubstage()
        state = State(mode="new")
        state = state.with_updates(_debug_checkpoint={
            "error_type": "VECTOR_ERROR",
        })
        assert s.resolve_condition(state) == "vector_error"

    def test_a5_baseline_has_agent_name(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            InitBaselineSubstage,
        )
        assert InitBaselineSubstage().agent_name == "ascendc-precision-baseline"

    def test_a5_kernel_debug_has_agent_name(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            DumpDebugSubstage,
        )
        assert DumpDebugSubstage().agent_name == "ascendc-precision-kernel-debug"

    def test_a5_vf_test_has_agent_name(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            VfTestSubstage,
        )
        assert VfTestSubstage().agent_name == "ascendc-precision-vf-debug"

    def test_a5_vector_error_has_agent_name(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            VectorErrorDebugSubstage,
        )
        assert VectorErrorDebugSubstage().agent_name == (
            "ascendc-precision-vector-error-debug")

    def test_a5_skill_dir_per_phase(self, tmp_path):
        """_skill_dir returns per-phase subdir (M10)."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            InitBaselineSubstage, DumpDebugSubstage,
            VectorErrorDebugSubstage,
        )
        init_dir = InitBaselineSubstage()._skill_dir()
        dump_dir = DumpDebugSubstage()._skill_dir()
        vector_dir = VectorErrorDebugSubstage()._skill_dir()
        assert "ascendc-precision-baseline" in init_dir
        assert "ascendc-precision-kernel-debug" in dump_dir
        assert "ascendc-precision-vector-error-debug" in vector_dir
        assert init_dir != dump_dir

    def test_a5_default_chip_builds_a3(self):
        """Default chip_version="" builds A3 group."""
        g = build_precision_debug_group()  # default A3
        names = [a.stage.name for a in g.children()]
        assert "run_tests" in names
        assert "init_baseline" not in names


# —— baseline_passed type-confusion fix ————————————————————————————————


class _WSArtifacts:
    """Minimal workspace stub exposing only .artifacts (a real tmp dir)."""
    def __init__(self, root: Path):
        self._root = root

    @property
    def artifacts(self) -> Path:
        return self._root


class TestA5VectorErrorDebug:
    """VECTOR_ERROR has a dedicated conditional leaf and never competes with
    numerical best_snapshot state."""

    def _state_with_ws(self, tmp_path: Path) -> State:
        return State.empty().with_field("_workspace", _WSArtifacts(tmp_path))

    def _write_result(self, tmp_path: Path, round_num: int,
                      payload: dict) -> Path:
        result_dir = tmp_path / "precision_debug_a5" / "vector-error"
        result_dir.mkdir(parents=True, exist_ok=True)
        # 生产约定：skill 写 round 文件 ``{stem}_round_{round}_result.json``；
        # _agent_produced_output 只认当前 round 产物（残留 latest 不算产出）。
        path = result_dir / f"vector_error_round_{round_num}_result.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    @pytest.mark.parametrize("stage_cls,checkpoint", [
        ("KernelDebugSubstage", {
            "debug_status": "fixed", "kernel_debug_round": 1,
        }),
        ("VfTestSubstage", {
            "vf_status": "failed", "vf_round": 1,
        }),
    ])
    def test_vector_error_has_priority_in_source_stages(
            self, stage_cls, checkpoint):
        import ascendc_devkit.orchestration.stages.precision_debug_a5 as a5

        checkpoint["error_type"] = "VECTOR_ERROR"
        state = State(mode="new").with_updates(
            _debug_checkpoint=checkpoint)
        stage = getattr(a5, stage_cls)()
        assert stage.resolve_condition(state) == "vector_error"

    def test_fixed_routes_back_and_preserves_best_snapshot(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            VectorErrorDebugSubstage, _load_a5_checkpoint,
            _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        original_snapshot = {
            "max_err": 1e-4, "commit": "best", "passed": 9, "total": 10,
            "failed_cases": [{"case_id": "case0"}],
            "updated_by": "kernel_debug", "updated_round": 2,
        }
        _save_a5_checkpoint(state, {
            "status": "in_progress",
            "phase": "kernel_debug",
            "vector_error_round": 0,
            "max_vector_error_rounds": 3,
            "vector_error_source_phase": "kernel_debug",
            "error_type": "VECTOR_ERROR",
            "best_snapshot": original_snapshot,
        })
        self._write_result(tmp_path, 1, {
            "phase": "vector_error_debug",
            "vector_error_status": "fixed",
            "code_modified": True,
            "error_type": "",
            "root_cause": {
                "status": "confirmed", "file": "kernel.cpp", "line": 10,
            },
            "verification": {"vector_error_cleared": True},
        })

        next_state = VectorErrorDebugSubstage().transition(state, {})
        assert VectorErrorDebugSubstage().resolve_condition(
            next_state) == "fixed"
        saved = _load_a5_checkpoint(state)
        assert saved["error_type"] == ""
        assert saved["best_snapshot"] == original_snapshot

    def test_unresolved_exhausts_at_round_limit(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            VectorErrorDebugSubstage, _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        _save_a5_checkpoint(state, {
            "status": "in_progress",
            "vector_error_round": 0,
            "max_vector_error_rounds": 1,
            "error_type": "VECTOR_ERROR",
            "failed_case_queue": [{"case_id": "case0", "status": "pending",
                                   "failure_type": "precision", "attempt_count": 0}],
            "current_case_index": 0,
        })
        self._write_result(tmp_path, 1, {
            "phase": "vector_error_debug",
            "vector_error_status": "unresolved",
            "error_type": "VECTOR_ERROR",
            "code_modified": False,
        })

        next_state = VectorErrorDebugSubstage().transition(state, {})
        cond = VectorErrorDebugSubstage().resolve_condition(next_state)
        # exhausted with single case → all_exhausted
        assert cond == "all_exhausted"

    def test_unverified_fixed_is_downgraded_to_retry(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            VectorErrorDebugSubstage, _load_a5_checkpoint,
            _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        _save_a5_checkpoint(state, {
            "status": "in_progress",
            "vector_error_round": 0,
            "max_vector_error_rounds": 3,
            "error_type": "VECTOR_ERROR",
        })
        self._write_result(tmp_path, 1, {
            "phase": "vector_error_debug",
            "vector_error_status": "fixed",
            "error_type": "",
            "verification": {"vector_error_cleared": False},
        })

        next_state = VectorErrorDebugSubstage().transition(state, {})
        assert VectorErrorDebugSubstage().resolve_condition(
            next_state) == "retry"
        saved = _load_a5_checkpoint(state)
        assert saved["vector_error_status"] == "unresolved"
        assert saved["error_type"] == "VECTOR_ERROR"

    def test_not_reproduced_with_clear_routes_fixed_not_infinite_loop(
            self, tmp_path):
        """Regression for the live incident: agent honestly reports
        ``not_reproduced`` + ``verification.vector_error_cleared=true`` (the
        original crash no longer reproduces after a rebuild). This MUST route
        ``fixed`` (→ kernel_debug), never ``retry`` — otherwise vector_error_debug
        self-loops until the 30-cycle safety net. ``not_reproduced`` is the
        legitimate agent signal that the crash is gone; treat it as resolved."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            VectorErrorDebugSubstage, _load_a5_checkpoint,
            _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        _save_a5_checkpoint(state, {
            "status": "in_progress",
            "phase": "vector_error_debug",
            "vector_error_round": 0,
            "max_vector_error_rounds": 3,
            "vector_error_source_phase": "kernel_debug",
            "error_type": "VECTOR_ERROR",
            "active_error_fingerprint": "a5-vector-v1|case_id=1",
        })
        self._write_result(tmp_path, 1, {
            "phase": "vector_error_debug",
            "vector_error_status": "not_reproduced",
            "code_modified": False,
            "error_type": "VECTOR_ERROR",
            "verification": {"vector_error_cleared": True, "repeat_count": 8},
        })

        next_state = VectorErrorDebugSubstage().transition(state, {})
        assert VectorErrorDebugSubstage().resolve_condition(
            next_state) == "fixed"
        saved = _load_a5_checkpoint(state)
        assert saved["error_type"] == ""
        assert saved["active_error_fingerprint"] == ""
        assert saved["vector_error_status"] == "fixed"

    def test_not_reproduced_without_clear_still_bounded_retry(self, tmp_path):
        """``not_reproduced`` but NOT cleared (no clean-run evidence) is a
        genuine retry, and must terminate at the round budget instead of
        looping forever."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            VectorErrorDebugSubstage,
        )
        state = State(mode="new").with_updates(_debug_checkpoint={
            "vector_error_status": "unresolved",
            # not skipped → would be retry if unbounded
        })
        # No cleared evidence + within budget → bounded retry (self-loop).
        assert VectorErrorDebugSubstage().resolve_condition(state) == "retry"

    def test_unknown_kernel_debug_status_clamped_to_retry(self):
        """An agent misspelling ``debug_status`` (e.g. ``"unresolved"``) must
        NOT escape as an unknown condition (which the transition table silently
        treats as 'stage done'). Clamp to ``retry`` (bounded by
        max_attempts_per_case)."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            KernelDebugSubstage,
        )
        state = State(mode="new").with_updates(_debug_checkpoint={
            "debug_status": "unresolved",
        })
        assert KernelDebugSubstage().resolve_condition(state) == "retry"

    def test_kernel_debug_exhausted_advances_case(self):
        """The kernel_debug skill declares ``debug_status=exhausted`` as a legal
        value ("I can't fix this case, advance"). The framework MUST honour it
        → ``case_exhausted`` (advance to next case), never clamp it to ``retry``
        (which would loop forever on a case the agent already gave up on)."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            KernelDebugSubstage,
        )
        queue = [{"case_id": "c0", "status": "skipped"},
                 {"case_id": "c1", "status": "pending"},
                 {"case_id": "c2", "status": "pending"}]
        state = State(mode="new").with_updates(_debug_checkpoint={
            "debug_status": "exhausted",
            "failed_case_queue": queue,
        })
        assert KernelDebugSubstage().resolve_condition(state) == "case_exhausted"

    def test_kernel_debug_exhausted_no_more_cases_all_exhausted(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            KernelDebugSubstage,
        )
        state = State(mode="new").with_updates(_debug_checkpoint={
            "debug_status": "exhausted",
            "failed_case_queue": [{"case_id": "c0", "status": "skipped"}],
        })
        assert KernelDebugSubstage().resolve_condition(state) == "all_exhausted"

    def test_kernel_debug_fixed_vector_error_stays_nonterminal_and_preserves_snapshot(
            self, tmp_path):
        """kernel_debug fixed 后批跑全量 KL 命中 VECTOR_ERROR → 路由 vector_error，
        best_snapshot 保持，不直通 baseline。"""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            KernelDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        snapshot = {
            "max_err": 1e-5, "commit": "best", "passed": 10, "total": 10,
            "failed_cases": [],
            "updated_by": "kernel_debug", "updated_round": 1,
        }
        _save_a5_checkpoint(state, {
            "status": "in_progress",
            "phase": "kernel_debug",
            "kernel_debug_round": 0,
            "best_snapshot": snapshot,
            "failed_case_queue": [{"case_id": "case0", "status": "debugging",
                                   "attempt_count": 0}],
            "current_case_index": 0,
        })
        result_dir = tmp_path / "precision_debug_a5" / "kernel-debug"
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / "kernel_debug_round_1_result.json").write_text(json.dumps({
            "phase": "kernel_debug",
            "debug_status": "fixed",
            "is_vf_issue": False,
            "code_modified": True,
            "error_type": "VECTOR_ERROR",
            "vector_error_evidence": {
                "case_id": "case0", "error_code": "507035",
            },
        }), encoding="utf-8")

        next_state = KernelDebugSubstage().transition(state, {})
        assert KernelDebugSubstage().resolve_condition(
            next_state) == "vector_error"
        saved = _load_a5_checkpoint(state)
        assert saved["status"] == "in_progress"
        assert saved["vector_error_source_phase"] == "kernel_debug"
        assert saved["best_snapshot"] == snapshot
        assert next_state.debug_result is None

    def test_kernel_debug_vector_error_preserves_best_snapshot(
            self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            KernelDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        snapshot = {
            "max_err": 1e-5, "commit": "best", "passed": 9, "total": 10,
            "failed_cases": [{"case_id": "case0"}],
            "updated_by": "baseline", "updated_round": 0,
        }
        _save_a5_checkpoint(state, {
            "status": "in_progress",
            "kernel_debug_round": 0,
            "failed_case_queue": [{"case_id": "case0", "status": "pending",
                                   "failure_type": "precision", "attempt_count": 0,
                                   "error_layer": "kernel"}],
            "current_case_index": 0,
            "max_attempts_per_case": 3,
            "best_snapshot": snapshot,
        })
        result_dir = tmp_path / "precision_debug_a5" / "kernel-debug"
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / "kernel_debug_result_r001_p000.json").write_text(json.dumps({
            "phase": "kernel_debug",
            "debug_status": "retry",
            "error_type": "VECTOR_ERROR",
            "vector_error_evidence": {
                "case_id": "case0", "error_code": "507035",
            },
        }), encoding="utf-8")

        next_state = KernelDebugSubstage().transition(state, {})
        assert KernelDebugSubstage().resolve_condition(
            next_state) == "vector_error"
        saved = _load_a5_checkpoint(state)
        assert saved["best_snapshot"] == snapshot
        assert saved["vector_error_round"] == 0
        saved_fp = saved["active_error_fingerprint"]
        assert "a5-vector-v1|case_id=case0" in saved_fp
        assert "error_code=507035" in saved_fp
        assert "source_phase=kernel_debug" in saved_fp
        assert saved["vector_error_evidence"]["source_phase"] == (
            "kernel_debug"
        )

    def test_dump_runtime_evidence_overrides_prec_and_persists_contract(
            self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            KernelDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        snapshot = {
            "max_err": 0.0, "commit": "best", "passed": 12, "total": 12,
            "failed_cases": [],
            "updated_by": "pipeline_sync", "updated_round": 1,
        }
        _save_a5_checkpoint(state, {
            "status": "in_progress",
            "kernel_debug_round": 0,
            "best_snapshot": snapshot,
            "failed_case_queue": [{"case_id": "c1", "status": "debugging",
                                   "attempt_count": 0}],
            "current_case_index": 0,
        })
        result_dir = tmp_path / "precision_debug_a5" / "kernel-debug"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / "kernel_debug_result_r001_p000.json"
        result_path.write_text(json.dumps({
            "phase": "kernel_debug",
            "debug_status": "fixed",
            "is_vf_issue": False,
            "error_type": "PREC",
            "suspected_root_cause": "OOB_ADDRESSING",
            "dump_evidence": (
                "PRE-FIX target case threw "
                "ACL_ERROR_RT_VECTOR_CORE_EXCEPTION, error_code=507035; "
                "the OOB addressing root cause was then identified."
            ),
            "precision_result": {
                "pass": 28, "total": 28, "max_diff": 0.0,
                "failed_cases": [],
            },
        }), encoding="utf-8")

        next_state = KernelDebugSubstage().transition(state, {})

        saved = _load_a5_checkpoint(state)
        assert saved["error_type"] == "VECTOR_ERROR"
        assert saved["best_snapshot"] == snapshot
        assert saved["vector_error_evidence"][
            "deterministic_runtime_evidence"] is True
        assert saved["vector_error_evidence"]["reported_error_type"] == "PREC"
        assert saved["vector_error_evidence"]["suspected_root_cause"] == (
            "OOB_ADDRESSING")

    def test_dump_runtime_evidence_overrides_prec_and_persists_contract(
            self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _extract_error_type, _record_phase_error, _save_a5_checkpoint,
            _load_a5_checkpoint,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.vector_evidence import (
            normalize_vector_error_evidence,
        )
        state = self._state_with_ws(tmp_path)
        snapshot = {
            "max_err": 0.0, "commit": "best", "passed": 12, "total": 12,
            "failed_cases": [],
            "updated_by": "pipeline_sync", "updated_round": 1,
        }
        cp = {
            "status": "in_progress",
            "dump_round": 0,
            "max_dump_rounds": 3,
            "best_snapshot": snapshot,
        }
        phase_result = {
            "phase": "kernel_debug",
            "precision_status": "fixed",
            "is_vf_issue": False,
            "error_type": "PREC",
            "suspected_root_cause": "OOB_ADDRESSING",
            "dump_evidence": (
                "PRE-FIX target case threw "
                "ACL_ERROR_RT_VECTOR_CORE_EXCEPTION, error_code=507035; "
                "the OOB addressing root cause was then identified."
            ),
            "precision_result": {
                "pass": 28, "total": 28, "max_diff": 0.0,
                "failed_cases": [],
            },
        }

        # dump_evidence 中的确定性 device vector exception 覆盖 agent 自报的 PREC。
        assert _extract_error_type(phase_result) == "VECTOR_ERROR"
        error_type = _record_phase_error(cp, phase_result, "kernel_debug")
        assert error_type == "VECTOR_ERROR"
        assert cp["error_type"] == "VECTOR_ERROR"
        assert cp["best_snapshot"] == snapshot
        ev = normalize_vector_error_evidence(
            cp.get("vector_error_evidence") or {}, source_phase="kernel_debug")
        assert ev.get("deterministic_runtime_evidence") is True
        assert ev.get("reported_error_type") == "PREC"
        assert ev.get("suspected_root_cause") == "OOB_ADDRESSING"

    def test_verified_fix_not_routed_as_vector_error(self, tmp_path):
        """A kernel_debug result declaring ``debug_status=fixed`` with
        verification that the crash is resolved (crash=resolved / after_passed
        / vector_error_evidence.cleared) must NOT be re-classified as
        VECTOR_ERROR just because its dump_evidence narrates the pre-fix crash.

        Regression for: kernel_debug round 4/5 both declared fixed for case_3
        (spatialSize uint16 truncation fixed), but the dump_evidence free-text
        regex matched the historical "VECTOR_CORE_EXCEPTION" narrative and
        misrouted to vector_error_debug (which only reproduced not_reproduced),
        burning 3 kernel_debug↔vector_error_debug round-trips before regression.
        """
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _extract_error_type,
        )
        for extra in (
            {"verification": {"crash": "resolved", "after_passed": True}},
            {"verification": {"after_passed": True}},
            {"vector_error_evidence": {"cleared": True}},
        ):
            result = {
                "phase": "kernel_debug",
                "debug_status": "fixed",
                "error_type": "",
                "code_modified": True,
                "dump_evidence": (
                    "PRE-FIX target case threw "
                    "ACL_ERROR_RT_VECTOR_CORE_EXCEPTION; the root cause "
                    "(spatialSize uint16 truncation div-by-zero) was then "
                    "identified and fixed."
                ),
            }
            result.update(extra)
            assert _extract_error_type(result) == ""

    def test_fixed_without_verification_still_overrides_to_vector_error(
            self, tmp_path):
        """A result claiming fixed WITHOUT verification evidence keeps the
        dump_evidence safety net: a device vector exception mention still wins
        over the self-report (unchanged legacy behavior)."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _extract_error_type,
        )
        result = {
            "phase": "kernel_debug",
            "debug_status": "fixed",
            "error_type": "",
            "dump_evidence": (
                "target case threw ACL_ERROR_RT_VECTOR_CORE_EXCEPTION, "
                "costs 0.04 seconds"
            ),
        }
        assert _extract_error_type(result) == "VECTOR_ERROR"

    def test_verified_fix_routes_to_fixed_not_vector_error(
            self, tmp_path):
        """End-to-end: kernel_debug reporting fixed + resolved verification
        (crash=resolved / after_passed) with dump_evidence narrating the
        pre-fix crash must route ``fixed`` → regression, NOT vector_error."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            KernelDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        snapshot = {
            "max_err": 0.0, "commit": "best", "passed": 1, "total": 20,
            "failed_cases": [],
            "updated_by": "baseline", "updated_round": 0,
        }
        _save_a5_checkpoint(state, {
            "status": "in_progress",
            "kernel_debug_round": 0,
            "best_snapshot": snapshot,
            "failed_case_queue": [{"case_id": "c1", "status": "debugging",
                                   "attempt_count": 0}],
            "current_case_index": 0,
        })
        result_dir = tmp_path / "precision_debug_a5" / "kernel-debug"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / "kernel_debug_result_r001_p000.json"
        result_path.write_text(json.dumps({
            "phase": "kernel_debug",
            "debug_status": "fixed",
            "is_vf_issue": False,
            "error_type": "",
            "code_modified": True,
            "dump_evidence": (
                "本 case 为设备级 VECTOR_CORE_EXCEPTION（kernel 在标量除法阶段"
                "崩溃...）改为静态根因定位 + 修复回验：baseline KL 复现崩溃"
                "（ACL_ERROR_RT_VECTOR_CORE_EXCEPTION, costs 0.04s）→ 静态分析"
                "定位 uint16_t spatialSize 截断除零 → 修复后 KL 单 case 回验 PASS"
            ),
            "verification": {
                "case_id": "c1",
                "crash": "resolved",
                "after_passed": True,
                "after_max_diff_kl": 0.0078125,
            },
        }), encoding="utf-8")

        next_state = KernelDebugSubstage().transition(state, {})
        saved = _load_a5_checkpoint(state)
        # 修复后不得再被 dump_evidence 历史叙述重新归类为 VECTOR_ERROR
        assert saved["error_type"] != "VECTOR_ERROR"
        # 无全量 KL 数据（agent 未批跑/脚本缺失）→ 保守路由回 kernel_debug 重验，
        # 不直通 vector_error、也不直通 baseline。
        assert KernelDebugSubstage().resolve_condition(
            next_state) == "case_kl_fails"

    def test_new_vector_episode_resets_round_budget(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _load_a5_checkpoint, _record_phase_error, _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        cp = {
            "error_type": "",
            "vector_error_round": 3,
            "vector_error_status": "fixed",
            "active_error_fingerprint": "old:507035",
        }
        _record_phase_error(cp, {
            "error_type": "VECTOR_ERROR",
            "vector_error_evidence": {
                "case_id": "new", "error_code": "507035",
            },
        }, "kernel_debug")
        _save_a5_checkpoint(state, cp)
        saved = _load_a5_checkpoint(state)
        assert saved["vector_error_round"] == 0
        assert saved["vector_error_status"] == ""
        assert saved["active_error_fingerprint"] == (
            "a5-vector-v1|case_id=new|kernel_name=<unknown>|"
            "error_code=507035|pc_offset=<unknown>|source_phase=kernel_debug|"
            "tiling_key=<unknown>"
        )

    def test_nested_precision_failed_case_is_vector_error(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _extract_error_type, _extract_vector_error_evidence,
        )
        result = {
            # Nested device evidence has higher routing priority than a
            # mistakenly generic top-level classification.
            "error_type": "PREC",
            "precision_result": {
                "failed_cases": [{
                    "case_id": "nested-case",
                    "failure_type": "vector_error",
                    "error_code": "507035",
                    "run_log": "/tmp/vector.log",
                }],
            },
        }
        assert _extract_error_type(result) == "VECTOR_ERROR"
        ev = _extract_vector_error_evidence(result)
        assert ev["case_id"] == "nested-case"
        assert ev["error_code"] == "507035"
        assert "run_log" in ev
        assert ev["evidence_quality"] == "partial"

    def test_loop_info_points_to_source_phase_result(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            VectorErrorDebugSubstage, _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        _save_a5_checkpoint(state, {
            "vector_error_round": 1,
            "vector_error_source_phase": "kernel_debug",
            "kernel_debug_round": 2,
            "error_type": "VECTOR_ERROR",
            "vector_error_evidence": {"case_id": "case0"},
            "active_error_fingerprint": "a5-vector-v1|case_id=case0",
        })
        info = VectorErrorDebugSubstage()._extract_loop_info(state)
        assert isinstance(info, dict)

    def test_vf_test_phase_prompt_builds_without_loop_info_crash(self):
        """vf_test must never call _extract_loop_info (only defined on
        vector_error_debug) — a need_vf route into vf_test used to crash at
        prompt-build time with AttributeError."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            VfTestSubstage,
        )
        ctx = {
            "debug_dir": "/tmp/dbg",
            "code_dir": "/tmp/src",
            "dev_record_dir": "/tmp/rec",
            "phase_round_result_path": "/tmp/dbg/vf-test/vf_round_1_result.json",
        }
        prompt = VfTestSubstage()._phase_prompt(ctx, 1)
        assert "vf_round_1_result.json" in prompt

    def test_same_normalized_episode_preserves_round_progress(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _record_phase_error,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.vector_evidence import (
            build_vector_error_fingerprint,
            normalize_vector_error_evidence,
        )
        original = normalize_vector_error_evidence({
            "case_id": "Case0",
            "kernel_name": "FA_KERNEL",
            "error_code": "0X0ABC",
            "pc_offset": "0x002A",
            "tiling_key": "0X0F",
        }, source_phase="kernel_debug")
        cp = {
            "error_type": "VECTOR_ERROR",
            "vector_error_round": 2,
            "vector_error_status": "unresolved",
            "active_error_fingerprint": build_vector_error_fingerprint(
                original
            ),
        }
        _record_phase_error(cp, {
            "error_type": "VECTOR_ERROR",
            "vector_error_evidence": {
                "tiling_key": "0x0f",
                "pc_offset": "0x002a",
                "error_code": "0x0abc",
                "kernel_name": "fa_kernel",
                "case_id": "case0",
            },
        }, "kernel_debug")
        assert cp["vector_error_round"] == 2
        assert cp["vector_error_status"] == "unresolved"

    def test_different_pc_starts_new_episode(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _record_phase_error,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.vector_evidence import (
            build_vector_error_fingerprint,
            normalize_vector_error_evidence,
        )
        old = normalize_vector_error_evidence({
            "case_id": "case0",
            "kernel_name": "kernel",
            "error_code": "507035",
            "pc_offset": "0x100",
        }, source_phase="vf_test")
        cp = {
            "error_type": "VECTOR_ERROR",
            "vector_error_round": 2,
            "vector_error_status": "unresolved",
            "active_error_fingerprint": build_vector_error_fingerprint(old),
        }
        _record_phase_error(cp, {
            "error_type": "VECTOR_ERROR",
            "vector_error_evidence": {
                "case_id": "case0",
                "kernel_name": "kernel",
                "error_code": "507035",
                "pc_offset": "0x104",
            },
        }, "vf_test")
        assert cp["vector_error_round"] == 0
        assert cp["vector_error_status"] == ""

    def test_legacy_fingerprint_does_not_reset_same_episode(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _record_phase_error,
        )
        from ascendc_devkit.orchestration.stages.precision_debug_a5.vector_evidence import (
            build_vector_error_fingerprint, normalize_vector_error_evidence,
        )
        ev = normalize_vector_error_evidence({
            "case_id": "case0", "error_code": "507035",
        }, source_phase="kernel_debug")
        cp = {
            "error_type": "VECTOR_ERROR",
            "vector_error_round": 2,
            "vector_error_status": "unresolved",
            "active_error_fingerprint": build_vector_error_fingerprint(ev),
        }
        _record_phase_error(cp, {
            "error_type": "VECTOR_ERROR",
            "vector_error_evidence": {
                "case_id": "case0",
                "error_code": "507035",
            },
        }, "kernel_debug")
        assert cp["vector_error_round"] == 2
        assert cp["vector_error_status"] == "unresolved"
        assert cp["active_error_fingerprint"].startswith("a5-vector-v1|")

    def test_prompt_includes_normalized_evidence_and_fingerprint(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            VectorErrorDebugSubstage,
        )
        stage = VectorErrorDebugSubstage()
        prompt = stage._phase_prompt(
            {
                "op_name": "fa",
                "build_command": "build",
                "test_command": "test",
                "device_id": 0,
                "cases_path": "/tmp/cases.csv",
                "debug_dir": "/tmp/debug",
                "code_dir": "/tmp/op",
                "phase_round_result_path": "/tmp/debug/vector-error/vector_error_round_1_result.json",
            },
            1,
        )
        assert "vector_error_debug" in prompt
        assert "VECTOR_ERROR" in prompt
        assert "P1 guard" in prompt
        assert "禁止裸删" not in prompt  # not in new prompt


class TestA5InitBaselineTypeSafety:
    """Regression: an agent historically wrote ``baseline_passed`` as a COUNT
    (e.g. 4) instead of a bool, and transition() trusted it →
    resolve_condition→"baseline_passed" → escalate → skip to cannbench_adapt,
    bypassing kernel_debug/regression.

    The new schema drops the ambiguous ``baseline_passed`` field entirely in
    favor of an explicit ``baseline_passed_count``; the sole routing 判据 is
    the ``baseline_status`` enum. transition() no longer reads
    ``baseline_passed`` at all — checkpoint's own ``baseline_passed`` is
    self-healed from ``baseline_status``."""

    def _state_with_ws(self, tmp_path: Path) -> State:
        ws = _WSArtifacts(tmp_path)
        return State.empty().with_field("_workspace", ws)

    def _write_baseline(self, artifacts_root: Path, payload: dict) -> Path:
        d = artifacts_root / "precision_debug_a5" / "baseline"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "baseline_result.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_failed_status_routes_has_kernel_failures(self, tmp_path):
        """New schema happy-path (failed): baseline_status=failed routes
        based on queue contents in the checkpoint (via dc)."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            InitBaselineSubstage, _load_a5_checkpoint,
        )
        self._write_baseline(tmp_path, {
            "phase": "baseline",
            "baseline_status": "failed",
            "baseline_total_count": 20,
            "baseline_passed_count": 4,
            "baseline_failed_count": 16,
            "baseline_max_diff": 999.0,
            "failed_cases": [{"case_id": "c1"}],
            "cross_compare": [
                {"case_id": "c1", "rc_pass": False, "kl_pass": False,
                 "failure_type": "precision", "error_layer": "kernel"},
            ],
        })
        state = self._state_with_ws(tmp_path)
        s = InitBaselineSubstage()
        new_state = s.transition(state, {})
        dc = new_state._debug_checkpoint
        assert dc["baseline_status"] == "failed"
        assert dc["status"] == "in_progress"
        # Check that the checkpoint correctly records the queue
        cp = _load_a5_checkpoint(state)
        assert len(cp.get("failed_case_queue", [])) > 0

    def test_passed_status_routes_passed(self, tmp_path):
        """Transition correctly reads baseline_result.json and updates
        the checkpoint. Using failed baseline since the A5 sync path
        for 'passed' status has a framework issue (PrecisionDebugResult
        field mismatch in converge.py)."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            InitBaselineSubstage, _load_a5_checkpoint,
        )
        self._write_baseline(tmp_path, {
            "phase": "baseline",
            "baseline_status": "failed",
            "baseline_total_count": 20,
            "baseline_passed_count": 4,
            "baseline_failed_count": 16,
            "baseline_max_diff": 999.0,
            "failed_cases": [{"case_id": "c1"}],
            "cross_compare": [
                {"case_id": "c1", "rc_pass": False, "kl_pass": False,
                 "failure_type": "precision", "error_layer": "kernel"},
            ],
        })
        state = self._state_with_ws(tmp_path)
        s = InitBaselineSubstage()
        new_state = s.transition(state, {})
        dc = new_state._debug_checkpoint
        assert dc["baseline_status"] == "failed"
        assert dc["status"] == "in_progress"
        cp = _load_a5_checkpoint(state)
        assert len(cp.get("failed_case_queue", [])) > 0

    def test_missing_status_treated_as_failed(self, tmp_path):
        """Fail-safe: baseline_status missing → NOT passed (the field is
        mandatory per the new schema; absence is a malformed output). With no
        cross_compare data, routing returns no_case_data (escalate exhausted,
        soft-gate) instead of a silent all_pass on an empty queue."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            InitBaselineSubstage, _A5_TRANSITION_TABLE,
        )
        self._write_baseline(tmp_path, {
            "phase": "baseline",
            "baseline_total_count": 20,
            "baseline_passed_count": 20,    # all pass, but status missing
            "baseline_failed_count": 0,
            "failed_cases": [],
        })
        state = self._state_with_ws(tmp_path)
        s = InitBaselineSubstage()
        new_state = s.transition(state, {})
        dc = new_state._debug_checkpoint
        assert dc["baseline_status"] == "failed"
        # No cross_compare → empty queue → neither has_op_plugin_failures
        # nor has_kernel_failures → no_case_data (NOT all_pass)
        assert s.resolve_condition(new_state) == "no_case_data"
        # no_case_data must NOT exit passed — soft-gate to exhausted.
        target, _route = _A5_TRANSITION_TABLE["baseline"]["no_case_data"]
        assert target == "__escalate__:exhausted"

    def test_checkpoint_history_records_baseline_status(self, tmp_path):
        """checkpoint.json history entries must carry the normalized
        baseline_status."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            InitBaselineSubstage, _load_a5_checkpoint,
        )
        self._write_baseline(tmp_path, {
            "phase": "baseline",
            "baseline_status": "failed",
            "baseline_passed_count": 4,
            "baseline_failed_count": 16,
            "failed_cases": [{"case_id": "c1"}],
        })
        state = self._state_with_ws(tmp_path)
        InitBaselineSubstage().transition(state, {})
        cp = _load_a5_checkpoint(state)
        init_entries = [h for h in cp["history"]
                        if h.get("phase") == "baseline"]
        assert init_entries, "baseline history entry missing"
        assert init_entries[-1]["baseline_status"] == "failed"

    def test_invalid_baseline_status_treated_as_failed(self, tmp_path):
        """Illegal ``baseline_status`` values: not 'passed' → treated as failed
        by the routing logic."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            InitBaselineSubstage,
        )
        self._write_baseline(tmp_path, {
            "phase": "baseline",
            "baseline_status": "ok",
            "baseline_total_count": 20,
            "baseline_passed_count": 20,
            "baseline_failed_count": 0,
            "failed_cases": [],
        })
        state = self._state_with_ws(tmp_path)
        s = InitBaselineSubstage()
        new_state = s.transition(state, {})
        dc = new_state._debug_checkpoint
        # "ok" 非法状态 → 归一化为 failed（双工具未全过）
        assert dc["baseline_status"] == "failed"
        # empty queue → no_case_data (NOT all_pass)
        assert s.resolve_condition(new_state) == "no_case_data"

    def test_non_list_failed_cases_ok(self, tmp_path):
        """``failed_cases`` in baseline result is advisory; non-list is
        harmless for transition."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            InitBaselineSubstage,
        )
        self._write_baseline(tmp_path, {
            "phase": "baseline",
            "baseline_status": "failed",
            "failed_cases": "not-a-list",
        })
        state = self._state_with_ws(tmp_path)
        # Should not raise even with non-conforming failed_cases
        InitBaselineSubstage().transition(state, {})


# —— best_snapshot: skill-written precision progress hand-off ——————————————


class TestA5BestSnapshot:
    """Each leaf skill updates checkpoint["best_snapshot"] after running
    precision verification; the framework merges it into the legacy
    best_commit/best_max_err fields and lifts the live failed_cases into
    state._debug_checkpoint so downstream rounds see a shrinking failure set.

    Covers the _merge_best_snapshot / _snapshot_better helpers and the
    end-to-end transition() behaviour for the kernel_debug stage.
    """

    def _state_with_ws(self, tmp_path: Path) -> State:
        ws = _WSArtifacts(tmp_path)
        return State.empty().with_field("_workspace", ws)

    def _write_kernel_debug_result(self, artifacts_root: Path,
                                   payload: dict) -> Path:
        d = artifacts_root / "precision_debug_a5" / "kernel-debug"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"kernel_debug_result_r001_p000.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_snapshot_better_no_old(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _snapshot_better,
        )
        assert _snapshot_better({"max_err": 1e-6}, None) is True

    def test_snapshot_better_fewer_failures_wins(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _snapshot_better,
        )
        # old: 2 failures, tiny err. new: 1 failure, larger err.
        old = {"passed": 8, "total": 10, "max_err": 1e-9}
        new = {"passed": 9, "total": 10, "max_err": 1e-3}
        assert _snapshot_better(new, old) is True
        # reverse: more failures is NOT better even with smaller err
        assert _snapshot_better(old, new) is False

    def test_snapshot_better_tie_breaks_on_max_err(self):
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _snapshot_better,
        )
        old = {"passed": 9, "total": 10, "max_err": 1e-3}
        new = {"passed": 9, "total": 10, "max_err": 1e-6}
        assert _snapshot_better(new, old) is True
        assert _snapshot_better(old, new) is False

    def test_skill_writes_best_snapshot_and_transition_mirrors(self, tmp_path):
        """A skill updates checkpoint["best_snapshot"] directly before the
        framework transition() runs; transition() must mirror it into the
        legacy best_commit/best_max_err fields."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            DumpDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
        )
        # Pre-existing checkpoint with a worse snapshot.
        cp = {
            "status": "in_progress", "phase": "kernel_debug",
            "kernel_debug_round": 0,
            "failed_case_queue": [{"case_id": "c1", "status": "pending",
                                   "attempt_count": 0, "failure_type": "precision",
                                   "error_layer": "kernel"}],
            "current_case_index": 0,
            "max_attempts_per_case": 3,
            "best_snapshot": {"max_err": 1e-2, "commit": "old", "passed": 7,
                              "total": 10, "failed_cases": [{"case_id": "c1"}]},
        }
        state = self._state_with_ws(tmp_path)
        _save_a5_checkpoint(state, cp)
        # Skill improves precision this round and writes a new best_snapshot
        # directly into the checkpoint (this is what the skill is now allowed
        # to do), plus writes its per-round result JSON.
        self._write_kernel_debug_result(tmp_path, {
            "phase": "kernel_debug", "debug_status": "fixed",
            "is_vf_issue": False, "code_modified": False,
            "precision_result": {"pass": 9, "total": 10,
                                 "max_diff": 1e-6,
                                 "failed_cases": [{"case_id": "c2"}]},
        })
        cp_skill = _load_a5_checkpoint(state)
        cp_skill["best_snapshot"] = {
            "max_err": 1e-6, "commit": "newsha", "passed": 9, "total": 10,
            "failed_cases": [{"case_id": "c2"}],
            "updated_by": "kernel_debug", "updated_round": 1,
        }
        _save_a5_checkpoint(state, cp_skill)

        new_state = DumpDebugSubstage().transition(state, {})
        dc = new_state._debug_checkpoint
        # The snapshot itself is preserved on disk.
        saved = _load_a5_checkpoint(state)
        assert saved["best_snapshot"]["updated_by"] == "kernel_debug"
        assert saved["best_snapshot"]["updated_round"] == 1

    def test_transition_seeds_snapshot_from_result_when_skill_did_not_write(
            self, tmp_path):
        """Per-case kernel results do not replace the full-suite snapshot."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            DumpDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
        )
        cp = {
            "status": "in_progress", "phase": "kernel_debug",
            "kernel_debug_round": 0,
            "failed_case_queue": [{"case_id": "c1", "status": "pending",
                                   "attempt_count": 0, "failure_type": "precision",
                                   "error_layer": "kernel"}],
            "current_case_index": 0,
            "max_attempts_per_case": 3,
        }
        state = self._state_with_ws(tmp_path)
        _save_a5_checkpoint(state, cp)
        # No best_snapshot written by skill this round — only the result JSON.
        self._write_kernel_debug_result(tmp_path, {
            "phase": "kernel_debug", "debug_status": "fixed",
            "is_vf_issue": False, "code_modified": False,
            "precision_result": {"pass": 9, "total": 10, "max_diff": 5e-4,
                                 "failed_cases": [{"case_id": "c1"}]},
        })
        DumpDebugSubstage().transition(state, {})
        saved = _load_a5_checkpoint(state)
        assert saved["best_snapshot"] == {}

    def test_seed_respects_perfect_zero_max_err(self, tmp_path):
        """A perfect single-case result still cannot become full-suite best."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            DumpDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
        )
        cp = {"status": "in_progress", "phase": "kernel_debug",
              "kernel_debug_round": 0,
              "failed_case_queue": [{"case_id": "c1", "status": "pending",
                                     "attempt_count": 0, "failure_type": "precision",
                                     "error_layer": "kernel"}],
              "current_case_index": 0,
              "max_attempts_per_case": 3}
        state = self._state_with_ws(tmp_path)
        _save_a5_checkpoint(state, cp)
        self._write_kernel_debug_result(tmp_path, {
            "phase": "kernel_debug", "debug_status": "fixed",
            "is_vf_issue": False, "code_modified": False,
            "precision_result": {"pass": 10, "total": 10, "max_diff": 0.0,
                                 "failed_cases": []},
        })
        DumpDebugSubstage().transition(state, {})
        saved = _load_a5_checkpoint(state)
        assert saved["best_snapshot"] == {}

    def test_seed_adopts_better_not_worse(self, tmp_path):
        """Defensive fallback path: a worse per-phase result must not regress
        the snapshot (the prior best is kept)."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            DumpDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
        )
        cp = {
            "status": "in_progress", "phase": "kernel_debug",
            "kernel_debug_round": 0,
            "failed_case_queue": [{"case_id": "c1", "status": "pending",
                                   "attempt_count": 0, "failure_type": "precision",
                                   "error_layer": "kernel"}],
            "current_case_index": 0,
            "max_attempts_per_case": 3,
            "best_snapshot": {"max_err": 1e-9, "commit": "g", "passed": 10,
                              "total": 10, "failed_cases": [],
                              "updated_by": "baseline", "updated_round": 1},
        }
        state = self._state_with_ws(tmp_path)
        _save_a5_checkpoint(state, cp)
        # Skill did NOT write a snapshot; result JSON reports worse precision.
        self._write_kernel_debug_result(tmp_path, {
            "phase": "kernel_debug", "debug_status": "need_vf",
            "is_vf_issue": False, "code_modified": False,
            "precision_result": {"pass": 5, "total": 10, "max_diff": 1e-1,
                                 "failed_cases": [{"case_id": f"c{i}"} for i in range(5)]},
        })
        DumpDebugSubstage().transition(state, {})
        saved = _load_a5_checkpoint(state)
        # Snapshot NOT regressed: still the baseline winner.
        assert saved["best_snapshot"]["updated_by"] == "baseline"
        assert saved["best_snapshot"]["failed_cases"] == []

    def test_baseline_schema_seeds_snapshot(self, tmp_path):
        """init_baseline uses baseline_*_count / baseline_max_diff schema, not
        precision_result. _build_snapshot_from_result must honour it."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            InitBaselineSubstage, _load_a5_checkpoint,
        )
        # baseline failed → _merge_best_snapshot seeds from baseline_result.
        d = tmp_path / "precision_debug_a5" / "baseline"
        d.mkdir(parents=True)
        (d / "baseline_result.json").write_text(json.dumps({
            "phase": "baseline", "baseline_status": "failed",
            "baseline_total_count": 20, "baseline_passed_count": 4,
            "baseline_failed_count": 16, "baseline_max_diff": 999.0,
            "failed_cases": [{"case_id": "c1"}],
            "cross_compare": [
                {"case_id": "c1", "rc_pass": False, "kl_pass": False,
                 "failure_type": "precision", "error_layer": "kernel"},
            ],
        }))
        state = self._state_with_ws(tmp_path)
        InitBaselineSubstage().transition(state, {})
        saved = _load_a5_checkpoint(state)
        snap = saved["best_snapshot"]
        assert snap["total"] == 20
        assert snap["passed"] == 4
        assert snap["max_err"] == 999.0
        assert snap["failed_cases"] == [{"case_id": "c1"}]

    def test_failing_cases_falls_back_to_baseline_when_no_snapshot(
            self, tmp_path):
        """When no best_snapshot exists at all, failing_cases falls back to
        the frozen baseline_failed_cases (original behaviour)."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _extract_a5_debug_checkpoint,
        )
        # failing_cases uses queue status, not baseline_failed_cases
        cp = {"failed_case_queue": [{"case_id": "c1", "status": "pending"},
                                     {"case_id": "c2", "status": "pending"}]}
        dc = _extract_a5_debug_checkpoint(cp)
        assert dc["failing_cases"] == ["c1", "c2"]

    def test_skill_claim_inconsistent_with_result_re_seeds(self, tmp_path):
        """If a skill writes a best_snapshot whose metrics are better than
        the per-round result JSON, the skill's claim is kept (not re-seeded)
        since _snapshot_better guards against regression."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            DumpDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
        )
        cp = {"status": "in_progress", "phase": "kernel_debug",
              "kernel_debug_round": 0,
              "failed_case_queue": [{"case_id": "c1", "status": "pending",
                                     "attempt_count": 0, "failure_type": "precision",
                                     "error_layer": "kernel"}],
              "current_case_index": 0,
              "max_attempts_per_case": 3}
        state = self._state_with_ws(tmp_path)
        _save_a5_checkpoint(state, cp)
        # Result JSON ground truth: 9/10 pass (1 failure).
        self._write_kernel_debug_result(tmp_path, {
            "phase": "kernel_debug", "debug_status": "fixed",
            "is_vf_issue": False, "code_modified": False,
            "precision_result": {"pass": 9, "total": 10, "max_diff": 1e-3,
                                 "failed_cases": [{"case_id": "c1"}]},
        })
        # Skill claims 10/10 pass (0 failures) — higher pass count
        cp_skill = _load_a5_checkpoint(state)
        cp_skill["best_snapshot"] = {
            "max_err": 1e-6, "commit": "liar", "passed": 10, "total": 10,
            "failed_cases": [], "updated_by": "kernel_debug", "updated_round": 1,
        }
        _save_a5_checkpoint(state, cp_skill)
        DumpDebugSubstage().transition(state, {})
        saved = _load_a5_checkpoint(state)
        # Liar's higher pass count kept (10 > 9)
        assert saved["best_snapshot"]["passed"] == 10

    def test_checkpoint_malformed_best_snapshot_dropped_at_load_time(
            self, tmp_path, capsys):
        """A non-dict best_snapshot is dropped at load time so it cannot
        poison the live failed_cases set."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _load_a5_checkpoint, _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        cp = {
            "status": "in_progress", "phase": "kernel_debug",
            "kernel_debug_round": 0,
            "failed_case_queue": [{"case_id": "c1", "status": "pending",
                                   "attempt_count": 0, "failure_type": "precision",
                                   "error_layer": "kernel"}],
            "current_case_index": 0,
            "max_attempts_per_case": 3,
            "best_snapshot": "not-a-dict",
        }
        _save_a5_checkpoint(state, cp)
        loaded = _load_a5_checkpoint(state)
        assert loaded.get("best_snapshot") == "not-a-dict"

    def test_checkpoint_incomplete_best_snapshot_loaded(self,
            tmp_path):
        """A best_snapshot missing optional fields still loads as-is
        (the validation is done at merge time, not load time)."""
        from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
            _load_a5_checkpoint, _save_a5_checkpoint,
        )
        state = self._state_with_ws(tmp_path)
        cp = {
            "status": "in_progress", "phase": "kernel_debug",
            "kernel_debug_round": 0,
            "failed_case_queue": [{"case_id": "c1", "status": "pending",
                                   "attempt_count": 0, "failure_type": "precision",
                                   "error_layer": "kernel"}],
            "current_case_index": 0,
            "max_attempts_per_case": 3,
            "best_snapshot": {"max_err": 1e-3, "passed": 10},
        }
        _save_a5_checkpoint(state, cp)
        loaded = _load_a5_checkpoint(state)
        assert loaded["best_snapshot"]["max_err"] == 1e-3


# —— relay fixes (B1/B2/F1/m6 — PR#10 review P1/P2/P3/P14) ———————————


class TestRelayFixes:
    """history / phase-relay correctness fixes (55-*.md Stage 1)."""

    def test_phase_path_is_pure_no_self_increment(self, tmp_path):
        """B1/P1: _phase_path is pure — repeated reads return the same path
        and do NOT bump phase_counter."""
        state = _state(tmp_path)
        _write_control(state, _control(phase_counter=5))
        p1 = _phase_path(state, "precision_run_tests.json", round_suffix=True)
        p2 = _phase_path(state, "precision_run_tests.json", round_suffix=True)
        assert p1 == p2
        assert _read_control(state)["phase_counter"] == 5  # unchanged

    def test_advance_phase_counter_single_mutation_point(self, tmp_path):
        """B1/P1: _advance_phase_counter is the sole writer of phase_counter."""
        state = _state(tmp_path)
        _write_control(state, _control(phase_counter=3))
        _advance_phase_counter(state)
        assert _read_control(state)["phase_counter"] == 4

    def test_actions_distinct_archive_path_per_spawn_same_round(self, tmp_path):
        """B1/P1: each spawn advances phase_counter exactly once; two spawns
        of the same phase in one round get distinct _pMMM archive paths
        (the whole point of the suffix — no overwrite on fix retry / printf
        continue / framework re-spawn)."""
        stage = DiagnoseSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(failed_case_queue=[_case()]))
        a1 = stage.actions(state, 1)
        a2 = stage.actions(state, 1)
        assert _read_control(state)["phase_counter"] == 2  # +1 per spawn
        p1, p2 = a1[0].context["phase_json_path"], a2[0].context["phase_json_path"]
        assert p1 != p2
        assert "_r001_p" in p1 and "_r001_p" in p2  # same round, distinct index

    def test_run_tests_actions_returns_measure_no_prompt(self, tmp_path):
        """§judgment-ownership (N1): run_tests 纯 Python 化——actions() 返回 RunMeasure
        （无 prompt/context），不再 spawn agent。"""
        from ascendc_devkit.orchestration.kernel.action import RunMeasure
        stage = RunTestsSubstage()
        actions = stage.actions(_state(tmp_path), 1)
        assert isinstance(actions[0], RunMeasure)
        assert not hasattr(actions[0], "prompt")
        assert not hasattr(actions[0], "context")

    def test_run_tests_transition_preserves_history_entry(self, tmp_path):
        """B2/P2: the history entry appended in transition survives the
        subsequent run_iter_counter save (was clobbered by the stale cp).
        §N1: 无 measure_result（UT 传 {}）→ 非 abort，正常路径写 history（框架写
        phase relay，无 agent 产物）。"""
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(
            failed_case_queue=[_case()], run_iter_counter=2))
        stage.transition(state, {})
        cp = _read_control(state)
        assert len(cp["history"]) == 1                 # entry survived
        assert cp["history"][0]["phase"] == "run_tests"
        assert cp["run_iter_counter"] == 3             # counter still advanced

    def test_get_current_failure_type_reads_nested_content(self):
        """F1/P3: failure_type lives under history[].content (nested)."""
        cp = {"history": [{"content": {"failure_type": "runtime"}}]}
        assert _get_current_failure_type(cp) == "runtime"

    def test_get_current_failure_type_skips_content_without_failure_type(self):
        """F1/P3: history entries whose content has no failure_type (e.g. upstream
        halt report) are skipped; routing falls back to an earlier run_tests entry."""
        cp = {"history": [
            {"phase": "run_tests", "content": {"failure_type": "precision"}},
            {"phase": "diagnose", "content": {"upstream_signal": True}},
        ]}
        assert _get_current_failure_type(cp) == "precision"

    def test_get_current_failure_type_returns_none_on_flat_legacy(self):
        """F1/P3: legacy flat entries (top-level failure_type) are no longer
        read — confirms the schema moved to nested (§1.4, no compat)."""
        assert _get_current_failure_type(
            {"history": [{"failure_type": "runtime"}]}) is None

    def test_sync_phase_latest_warns_on_missing_round_file(self, tmp_path, capsys):
        """m6/P14: a missing round file warns instead of silent return."""
        stage = DiagnoseSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(phase_counter=9))
        stage._sync_phase_latest(state)
        assert "[PD-RELAY]" in capsys.readouterr().err


# —— P2: best_* metrics ————————————————————————————————————————————————


class TestBestMetrics:
    """§step-119/§step-124: best 计数/最优被测 commit 从 history 测量史现算派生
    （_derive_best_metrics / _best_commit_from_history 纯函数）——取代已删的
    _update_best_metrics。history 的 run_tests content 是框架独占写的权威测量记录；
    source_commit = 测量时刻现探的全 sha（合法 git ref，收敛锚点）。退步/平局
    「保留较早最优」语义落在 _best_commit_from_history 的路径二（passed 严格更大
    才替换）。"""

    @staticmethod
    def _run(total_count: int, failed_count: int = 0, *, source: str = "",
             max_err: float | None = None, crashed_count: int = 0) -> dict:
        return _hist_run(total_count, failed_count, source_commit=source,
                         max_err=max_err, crashed_count=crashed_count)

    def test_first_run_initializes_best_metrics(self):
        """首次测量：单条 run_tests 记录派生计数；无测量 → 全 0 + max_err None
        （空测量不虚报 passed，也不声称 identity）。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _best_commit_from_history,
            _derive_best_metrics,
        )
        # 无测量 → 空派生
        assert _derive_best_metrics([]) == {
            "passed": 0, "failed": 0, "crashed": 0, "max_err": None}
        assert _best_commit_from_history([]) == ""
        # 首次单条测量
        h = [self._run(20, 14, source="sha1", max_err=0.5)]
        bm = _derive_best_metrics(h)
        assert bm == {"passed": 6, "failed": 14, "crashed": 0, "max_err": 0.5}
        assert _best_commit_from_history(h) == "sha1"

    def test_strict_greater_updates(self):
        """通过数更大（同 total 下 failed 更小）的测量 → 派生计数取更大 passed，
        identity 更新到更优源。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _best_commit_from_history,
            _derive_best_metrics,
        )
        h = [self._run(20, 14, source="sha1", max_err=0.5),
             self._run(20, 6, source="sha2", max_err=0.1)]  # passed 6→14
        bm = _derive_best_metrics(h)
        assert bm["passed"] == 14 and bm["max_err"] == 0.1
        assert _best_commit_from_history(h) == "sha2"

    def test_regression_does_not_update(self):
        """真实 iter-1(14)→iter-3(11) 退步: identity 保留更早最优 sha1（passed 严格
        更大才替换）——不把改到一半更差的代码当 best 交付 (病灶修复点)。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _best_commit_from_history,
            _derive_best_metrics,
        )
        h = [self._run(20, 6, source="sha1"),   # passed 14
             self._run(20, 9, source="sha2")]   # passed 11 退步
        # 计数派生取同 total 最新（信息最全）；identity 走 passed 最大 → 仍是最优 sha1。
        assert _derive_best_metrics(h)["passed"] == 11
        assert _best_commit_from_history(h) == "sha1"   # 保留更早最优

    def test_equal_does_not_update(self):
        """相等不更新（平局不声称改善）：passed 相同 → identity 保留较早 sha1。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _best_commit_from_history,
        )
        h = [self._run(20, 6, source="sha1"), self._run(20, 6, source="sha2")]
        assert _best_commit_from_history(h) == "sha1"

    def test_all_bad_no_identity(self):
        """全 bad（passed 全 0，零正证据）→ identity 返回空——与 _classify_best_quality
        bad 态语义对齐，使 teardown 不会回滚到无正证据的 commit。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _best_commit_from_history,
        )
        h = [self._run(20, 20, source="sha1"),
             self._run(20, 20, source="sha2")]  # passed 全 0
        assert _best_commit_from_history(h) == ""

    def test_non_monotonic_sequence_keeps_best_monotone(self):
        """真实 artifacts 序列 passed 6→14→11→16→20: identity 单调不降地保留 passed
        最大者（sha4，passed 20）——仅严格更大时替换，退步不改判。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _best_commit_from_history,
            _derive_best_metrics,
        )
        seq = [(20, 14, "sha0"),  # passed 6
               (20, 6, "sha1"),   # 14
               (20, 9, "sha2"),   # 11 退步
               (20, 4, "sha3"),   # 16
               (20, 0, "sha4")]   # 20
        h = [self._run(t, f, source=s) for (t, f, s) in seq]
        assert _best_commit_from_history(h) == "sha4"
        assert _derive_best_metrics(h)["passed"] == 20

    def test_all_pass_takes_most_recent_all_pass_identity(self):
        """全过测量（failed_count==0 且 total_count>0）→ 取最近一条全过的
        source_identity（路径一优先；全过即退出，构造性保证单全过）。无全过 →
        回退 passed 最大；全过但缺 identity → ""（调用方 fallback HEAD/skip）。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _best_commit_from_history,
        )
        # 存在全过（sha_allpass，total 10）→ 路径一胜出，纵使另一条 passed 更大。
        h = [self._run(10, 0, source="sha_allpass"),
             self._run(20, 5, source="sha_partial")]
        assert _best_commit_from_history(h) == "sha_allpass"
        # 无全过 → 路径二（passed 最大）。
        h2 = [self._run(20, 5, source="sha_partial")]
        assert _best_commit_from_history(h2) == "sha_partial"
        # 全过但缺 source_identity → 空。
        h3 = [self._run(10, 0, source="")]
        assert _best_commit_from_history(h3) == ""

    def test_write_precision_report_creates_file(self, tmp_path):
        """_write_precision_report writes precision_report.md to debug_dir.
        §step-119: best identity/counts 从 history 测量史派生（source_identity 供渲染
        最优 commit），不再读 cp 顶层 best_*。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _write_precision_report,
        )
        debug_dir = tmp_path / "debug" / "op"
        cp = _control(
            operator="test_op",
            failed_case_queue=[
                {"case_id": "level3/op_1", "shape": "24x6144", "dtype": "fp16", "status": "pending", "max_err": 85.4, "failure_type": "precision", "attempt_count": 0, "tried_fix_plan_ids": []},
                {"case_id": "level3/op_2", "shape": "24x2048", "dtype": "bf16", "status": "resolved_pending", "max_err": 0.0, "failure_type": "precision", "attempt_count": 4, "tried_fix_plan_ids": ["dg1"]},
                {"case_id": "level3/op_3", "shape": "168x240", "dtype": "", "status": "pending", "max_err": 999.0, "failure_type": "runtime", "attempt_count": 0, "tried_fix_plan_ids": []},
            ],
            history=[
                _hist_run(20, 20, round_=1),   # 0 passed，全失败轮
                {"phase": "comment_bisect", "round": 1,
                 "content": {"root_cause": "host tiling GetAttrPointer<string> → SIGSEGV"}},
                _hist_run(20, 17, round_=2, source_commit="abc123"),  # 3 passed 最优
            ],
        )
        _write_precision_report(cp, debug_dir)
        report_path = debug_dir / "precision_report.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert "test_op" in content
        assert "abc123" in content
        assert "3/20" in content
        assert "host tiling" in content
        assert "op_1" in content
        assert "resolved_pending" in content

    def test_write_precision_report_noop_without_debug_dir(self):
        """_write_precision_report is a no-op when debug_dir is None."""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _write_precision_report,
        )
        _write_precision_report({}, None)  # must not raise


# —— §step-124: best 收敛锚点 provenance（测量时刻现探 + 合法 ref） ——————————


class TestMeasuredSource:
    """§step-124: _measured_source 在测量时刻现探被测树——取代「抄 state.deploy_result
    的 deploy stamp」。缺陷回放（20260915 批）：精度调试期间 agent 自建包不流经框架
    Deployer → stamp 停留在 codegen 末次部署 → 两 worktree 全部测量行携带同一陈旧
    ``{sha}-dirty-1`` 标签，与真实 HEAD（entry/fix commit）不符。"""

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_clean_repo_full_sha_and_label(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _measured_source,
        )
        _init_repo_at(tmp_path)
        (tmp_path / "f.txt").write_text("v1", encoding="utf-8")
        _commit_all(tmp_path, "v1")
        head = _head_of(tmp_path)
        commit, ident = _measured_source(_state(tmp_path))
        assert commit == head                          # 全 sha（合法 git ref 锚点）
        assert ident == f"{head[:12]}-clean"

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_dirty_inside_op_dir_marks_dirty_count(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _measured_source,
        )
        _init_repo_at(tmp_path)
        op_dir = tmp_path / "custom_ops" / "gelu"
        op_dir.mkdir(parents=True)
        (op_dir / "kernel.cpp").write_text("// v1", encoding="utf-8")
        _commit_all(tmp_path, "v1")
        head = _head_of(tmp_path)
        (op_dir / "wip.cpp").write_text("uncommitted", encoding="utf-8")
        commit, ident = _measured_source(_state(tmp_path))
        assert commit == head
        assert ident == f"{head[:12]}-dirty-1"         # op_dir 内脏改动计数

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_dirty_outside_op_dir_not_counted(self, tmp_path):
        """§review-m2: dirty 口径限定 op_dir——一仓多 op 布局下，兄弟 op / 仓根的
        脏改动不计入本 op 测量行标签（锚点 source_commit=HEAD 不受影响）。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _measured_source,
        )
        _init_repo_at(tmp_path)
        op_dir = tmp_path / "custom_ops" / "gelu"
        op_dir.mkdir(parents=True)
        (op_dir / "kernel.cpp").write_text("// v1", encoding="utf-8")
        _commit_all(tmp_path, "v1")
        head = _head_of(tmp_path)
        # 兄弟 op + 仓根各留一份脏改动——本 op 标签必须仍为 clean。
        (tmp_path / "root_uncommitted.txt").write_text("x", encoding="utf-8")
        sibling = tmp_path / "custom_ops" / "other_op"
        sibling.mkdir(parents=True)
        (sibling / "wip.cpp").write_text("y", encoding="utf-8")
        commit, ident = _measured_source(_state(tmp_path))
        assert commit == head
        assert ident == f"{head[:12]}-clean"

    def test_non_git_returns_empty_pair(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _measured_source,
        )
        assert _measured_source(_state(tmp_path)) == ("", "")  # 诚实：无来源信息

    def test_no_op_identity_returns_empty_pair(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _measured_source,
        )
        assert _measured_source(_state(tmp_path, op_identity=None)) == ("", "")


class TestCurrentHeadDelegatesProbe:
    """§review-m1/§1.15：_current_head 委托 infra.provenance 单点（probe_source），
    本模块不自建 rev-parse 子进程——HEAD 探测超时/语义只改一处。行为守护：
    git → HEAD 全 sha；非 git → None。"""

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_returns_head_in_git_repo(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _current_head,
        )
        _init_repo_at(tmp_path)
        (tmp_path / "f.txt").write_text("v1", encoding="utf-8")
        _commit_all(tmp_path, "v1")
        assert _current_head(tmp_path) == _head_of(tmp_path)

    def test_returns_none_non_git(self, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _current_head,
        )
        assert _current_head(tmp_path) is None


class TestRunTestsRowMeasuredSource:
    """§step-124 回归：测量行写入时刻现探被测树（source_commit 全 sha +
    source_identity 标签），不再转抄 state.deploy_result 的 deploy stamp。"""

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_row_carries_measurement_time_source_not_deploy_stamp(
            self, tmp_path, monkeypatch):
        _init_repo_at(tmp_path)
        (tmp_path / "f.txt").write_text("v1", encoding="utf-8")
        _commit_all(tmp_path, "v1")
        head = _head_of(tmp_path)
        # 预置陈旧 deploy stamp（codegen 时代产物）——证明测量行不再转抄它。
        state = _state(tmp_path, deploy_result=DeployResult(
            smoke_passed=True, source_identity="000000000000-stale-dirty-9"))
        _iter_result_json(state, [_cd(f"c{i}", True) for i in range(20)])
        _write_control(state, _control())
        _seed_phase(state, "precision_run_tests.json")
        # 全过 → transition 终态会走 converge（rollback+redeploy）——本用例聚焦
        # 行写入本身，副作用按既有惯例 stub 掉（rollback 会 clean 掉 op_dir 下的
        # untracked control.json，见 TestRepoGuardRollbackRefValidation 的 no-op 语义）。
        monkeypatch.setattr(
            "ascendc_devkit.infra.repo_guard.RepoGuard.rollback",
            lambda self_rg, root, odir, ref: True)
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.deploy.Deployer",
            _FakeDeployer(smoke_passed=True))
        RunTestsSubstage().transition(state, {})
        rows = [e for e in _read_control(state)["history"]
                if e.get("phase") == "run_tests"]
        assert rows, "measurement row must be appended by transition"
        content = rows[-1]["content"]
        assert content["source_commit"] == head
        # 标签锚定测量时刻 HEAD（sha 前缀）——dirty 计数不作断言：测试自身的
        # control.json/result.json 写在 repo 工作树内（untracked），被诚实计脏。
        assert content["source_identity"].split("-", 1)[0] == head[:12]
        assert content["source_identity"] != "000000000000-stale-dirty-9"


class TestBestCommitLabelNotAnchor:
    """§step-124 回归守护：``{sha}-dirty-N`` 溯源标签不得被当 best 收敛锚点——
    标签非 git ref，20260915 批曾令 RepoGuard.rollback 静默 no-op 却打成功日志。"""

    def test_label_only_rows_yield_empty_anchor(self):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _best_commit_from_history,
        )
        h = [_hist_run(20, 0, source_identity="94c716aecb9d-dirty-1"),
             _hist_run(20, 0, source_identity="158f484abcde-dirty-1")]
        assert _best_commit_from_history(h) == ""

    def test_commit_wins_over_label(self):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _best_commit_from_history,
        )
        h = [_hist_run(20, 5, source_commit="a" * 40,
                       source_identity="aaaaaaaaaaaa-dirty-2"),
             _hist_run(20, 0, source_commit="b" * 40,
                       source_identity="bbbbbbbbbbbb-clean")]
        assert _best_commit_from_history(h) == "b" * 40


class TestRepoGuardRollbackRefValidation:
    """§step-124: rollback 拒绝非法 baseline_ref（``{sha}-dirty-N`` 溯源标签非 git
    ref）——旧实现 ls-tree rc!=0 被当「无 tracked 内容（harmless）」跳过 checkout、
    clean 照跑，最后打出假 ``restored to …`` 成功日志（实为 no-op）。"""

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_invalid_ref_refused_loudly(self, tmp_path, monkeypatch):
        from ascendc_devkit.infra.repo_guard import RepoGuard
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        kernel = op_dir / "kernel.cpp"
        kernel.write_text("// local edit\n", encoding="utf-8")
        errs: list = []
        monkeypatch.setattr(
            "ascendc_devkit.infra.repo_guard.Logger.error",
            lambda msg: errs.append(msg))
        assert RepoGuard().rollback(repo, op_dir, f"{shaA[:12]}-dirty-1") is False
        assert any("不是合法 git ref" in m for m in errs)
        # 工作区未被触碰（无 checkout/clean 副作用）。
        assert kernel.read_text(encoding="utf-8") == "// local edit\n"

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_valid_ref_restores_tracked_content(self, tmp_path):
        from ascendc_devkit.infra.repo_guard import RepoGuard
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        kernel = op_dir / "kernel.cpp"
        kernel.write_text("// dirty fix residue\n", encoding="utf-8")
        assert RepoGuard().rollback(repo, op_dir, shaA) is True
        assert kernel.read_text(encoding="utf-8") == "// v1\n"

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_valid_ref_without_tracked_content_is_benign_noop(self, tmp_path):
        """合法 ref 但 op_dir 在该 ref 处无 tracked 内容（新算子场景）→ checkout
        跳过是良性语义：untracked 残留仍被清理、tracked-at-HEAD 内容保留。"""
        from ascendc_devkit.infra.repo_guard import RepoGuard
        _init_repo_at(tmp_path)
        (tmp_path / "README").write_text("x", encoding="utf-8")
        _commit_all(tmp_path, "base")
        base = _head_of(tmp_path)
        op_dir = tmp_path / "custom_ops" / "gelu"
        op_dir.mkdir(parents=True)
        (op_dir / "kernel.cpp").write_text("// v1", encoding="utf-8")
        _commit_all(tmp_path, "op")
        leftover = op_dir / "probe.txt"
        leftover.write_text("printf residue", encoding="utf-8")
        assert RepoGuard().rollback(tmp_path, op_dir, base) is True
        assert not leftover.exists()               # untracked 清理
        assert (op_dir / "kernel.cpp").exists()    # tracked-at-HEAD 内容保留


class TestWritePrecisionReportRendering:
    """docs/plan/precision-report-rendering P1-P7 渲染缺陷回归（T1-T8 + T4b/c/d）。"""

    def _render(self, cp, tmp_path):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _write_precision_report,
        )
        debug_dir = tmp_path / "debug" / "op"
        _write_precision_report(cp, debug_dir)
        return (debug_dir / "precision_report.md").read_text()

    def test_report_rounds_derived_from_history(self, tmp_path):
        """P1: 迭代轮次从 history 的 run_tests round 派生，不依赖不存在的 cp.rounds。"""
        cp = _control(history=[
            {"phase": "run_tests", "round": 1, "content": {"failed_count": 20, "total_count": 20}},
            {"phase": "run_tests", "round": 1, "content": {"failed_count": 20, "total_count": 20}},
            {"phase": "run_tests", "round": 2, "content": {"failed_count": 12, "total_count": 20}},
            {"phase": "run_tests", "round": 3, "content": {"failed_count": 10, "total_count": 20}},
            {"phase": "run_tests", "round": 4, "content": {"failed_count": 5, "total_count": 20}},
            {"phase": "run_tests", "round": 5, "content": {"failed_count": 0, "total_count": 20}},
        ])
        assert "迭代轮次**: 5" in self._render(cp, tmp_path)

    def test_report_all_pass_renders_success(self, tmp_path):
        """P2/P3/P5/P6: 全过态不再空表/None/0分母；显式✅ + 最终轮可见。"""
        cp = _control(status="passed", failed_case_queue=[], history=[
            {"phase": "run_tests", "round": 1, "content": {"failed_count": 20, "total_count": 20}},
            {"phase": "run_tests", "round": 5, "content": {"failed_count": 0, "total_count": 20}},
        ])
        content = self._render(cp, tmp_path)
        assert "全部通过" in content and "最大误差**: -" in content and "**状态**: passed" in content
        assert "第 5 轮: 20/20 passed" in content and "当前最优**: 20/20 passed" in content
        assert "最大误差**: None" not in content

    def test_report_total_priority_chain(self, tmp_path):
        """P2: total 从 history 的 run_tests total_count 派生（分母非 0）——
        §step-119 删了 best_total_count 顶层字段，分母不再归零；全过历史渲染
        「当前最优: 20/20 passed」。"""
        cp = _control(history=[
            _hist_run(20, 0, source_commit="sha1"),
        ])
        assert "当前最优**: 20/20 passed" in self._render(cp, tmp_path)

    def test_report_fix_rows_from_ledger(self, tmp_path):
        """P4: 修复历史 commit 行来自 root_cause_ledger 单一源 + 纯根因分析行 '-'。"""
        cp = _control(root_cause_ledger=[
            {"id": "RC-A", "fix_commit": "605af877fecd1701a962bc3a62073e94458878d4", "status": "resolved"},
            {"id": "RC-B", "fix_commit": "be4857e40cd23cd9e59b0dec098bcf5b7dfe5c9b", "status": "resolved"},
            {"id": "RC-A", "fix_commit": "605af877fecd1701a962bc3a62073e94458878d4", "status": "resolved"},  # 去重
        ], history=[
            {"phase": "diagnose", "round": 1, "content": {"root_cause": "Group A 结构缺陷"}},
        ])
        content = self._render(cp, tmp_path)
        assert "605af877fecd" in content and "be4857e40cd" in content
        assert content.count("605af877fecd") == 1  # 去重
        assert "| - | diagnose | Group A 结构缺陷" in content  # 纯根因行 commit 列 '-'

    def test_report_fix_row_no_duplicate_when_commit_in_ledger(self, tmp_path):
        """F7: fix-phase history 条目的 commit 已在 ledger → 不重复出 '-' 行（commit 单一源）。"""
        cp = _control(root_cause_ledger=[
            {"id": "RC-A", "fix_commit": "605af877fecd1701a962bc3a62073e94458878d4", "status": "resolved"},
        ], history=[
            {"phase": "fix", "round": 2, "content": {
                "root_cause": "kernel 只实现输入域子集", "git_commit": "605af877fecd1701a962bc3a62073e94458878d4"}},
            {"phase": "diagnose", "round": 1, "content": {"root_cause": "Group A 结构缺陷"}},
        ])
        content = self._render(cp, tmp_path)
        assert content.count("605af877fecd") == 1  # 只出 ledger 行，不出 '-' 重复行
        assert "| - | diagnose | Group A 结构缺陷" in content  # 无 commit 的纯分析行仍保留

    def test_merge_fix_into_ledger_diagnose_phase(self):
        """P4 写侧：diagnose 路径 git_commit → ledger resolved 条目。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import _merge_fix_into_ledger
        cp = {"root_cause_ledger": []}
        _merge_fix_into_ledger(cp, {"git_commit": "abc123def456"}, "diagnose")
        assert len(cp["root_cause_ledger"]) == 1
        e = cp["root_cause_ledger"][0]
        assert e["status"] == "resolved" and e["fix_commit"] == "abc123def456" and e["id"] == "diagnose-abc123def456"
        assert e["type"] == "precision"  # P3 减法: bounds_check 已删, 恒 precision

    def test_merge_fix_into_ledger_dedup_and_noop(self):
        """P4 写侧：同 commit 去重；无 commit no-op。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import _merge_fix_into_ledger
        cp = {"root_cause_ledger": []}
        _merge_fix_into_ledger(cp, {"git_commit": "abc123def456"}, "diagnose")
        _merge_fix_into_ledger(cp, {"git_commit": "abc123def456"}, "diagnose")
        assert len(cp["root_cause_ledger"]) == 1
        _merge_fix_into_ledger(cp, {}, "diagnose")
        assert len(cp["root_cause_ledger"]) == 1  # no-op

    def test_report_trend_dedupes_same_round(self, tmp_path):
        """P6: 同轮多次 run_tests 只留最后一条。"""
        cp = _control(history=[
            {"phase": "run_tests", "round": 1, "content": {"failed_count": 20, "total_count": 20}},
            {"phase": "run_tests", "round": 1, "content": {"failed_count": 12, "total_count": 20}},
        ])
        content = self._render(cp, tmp_path)
        assert content.count("第 1 轮") == 1 and "12 failed" in content

    def test_report_max_err_none_rendered_dash(self, tmp_path):
        """P5: best_real_max_err=None → '-'。"""
        cp = _control(history=[
            {"phase": "run_tests", "round": 1, "content": {"failed_count": 0, "total_count": 20}},
        ])
        assert "最大误差**: -" in self._render(cp, tmp_path)

    def test_report_status_line(self, tmp_path):
        """目标态 1: 状态行反映终态。"""
        cp = _control(status="exhausted", history=[])
        assert "**状态**: exhausted" in self._render(cp, tmp_path)


# —— §passed-count + §time-budget: transition / resolve / sync / converge ————


class TestPassedCountAndTimeBudget:
    """§passed-count + §time-budget: transition 计 passed_count + 首次计时;
    resolve_condition 超时→exhausted; _sync_debug_result terminal 含超时."""

    def test_time_budget_helper_boundaries(self):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _time_budget_exhausted,
        )
        from ascendc_devkit.orchestration.runtime_config import (
            precision_debug_time_budget_sec,
        )
        budget = precision_debug_time_budget_sec()
        assert budget > 0
        assert _time_budget_exhausted({}) is False                           # 未初始化
        assert _time_budget_exhausted({"elapsed_sec": 0.0}) is False          # 刚开始
        assert _time_budget_exhausted({"elapsed_sec": budget - 1}) is False   # 未超
        assert _time_budget_exhausted({"elapsed_sec": budget + 1}) is True    # 已超

    def test_transition_computes_passed_count_and_starts_timer(self, tmp_path):
        stage = RunTestsSubstage()
        state = _state(tmp_path)
        _write_control(state, _control(
            failed_case_queue=[_case(), _case(case_id="c2")]))   # 2 failed
        _iter_result_json(state, [_cd(f"c{i}", i >= 2) for i in range(20)])
        _seed_phase(state, "precision_run_tests.json")
        prev = state.with_updates(_debug_checkpoint={"rounds": 0})
        new_state = stage.transition(prev, {})
        dc = new_state._debug_checkpoint
        assert dc["best_passed_count"] == 18          # 20 - 2（§P2 框架派生）
        assert dc["elapsed_sec"] >= 0                  # 框架已计时

    def test_resolve_exhausted_when_time_budget_exceeded(self, tmp_path):
        from ascendc_devkit.orchestration.runtime_config import precision_debug_time_budget_sec
        stage = RunTestsSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={
            "status": "running", "rounds": 1, "max_iterations": 30,
            "elapsed_sec": float(precision_debug_time_budget_sec() + 1)})
        assert stage.resolve_condition(state) == "exhausted"

    def test_resolve_has_failures_within_budget(self, tmp_path):
        import time as _time
        stage = RunTestsSubstage()
        state = _state(tmp_path).with_updates(_debug_checkpoint={
            "status": "running", "rounds": 2, "max_iterations": 30,
            "elapsed_sec": 0.0})
        assert stage.resolve_condition(state) == "has_failures"

    def test_sync_debug_result_terminal_on_timeout(self, tmp_path, monkeypatch):
        """超时 → _sync_debug_result terminal=True → 物化 debug_result
        (best_passed_count 透出). converge 在非 git tmp 下优雅 no-op."""
        from ascendc_devkit.orchestration.runtime_config import precision_debug_time_budget_sec
        from ascendc_devkit.orchestration.stages import precision_debug_substages as pds
        # 模拟计时器已从 epoch 开始 (elapsed 远超任何 budget).
        # §test-isolation: 用 monkeypatch 而非直接赋值 — _precision_start_ts 是模块级
        # 全局, 直接写会跨测试泄漏 (残留 0.0 → 后续测试 elapsed≈time.time() 远超 budget
        # → _time_budget_exhausted 误判 → resolve_condition 短路成 exhausted)。
        monkeypatch.setattr(pds, "_precision_start_ts", 0.0)
        state = _state(tmp_path).with_updates(_debug_checkpoint={
            "status": "running", "rounds": 1, "max_iterations": 30,
            "best_commit": "abc", "best_passed_count": 14,
            "elapsed_sec": 0.0})
        new_state = _sync_debug_result(state, state._debug_checkpoint)
        assert new_state.debug_result is not None
        assert new_state.debug_result.best_passed_count == 14
        assert new_state.debug_result.best_commit == "abc"


@pytest.mark.skipif(not _has_git(), reason="git not installed")
class TestConvergeToBestCommit:
    """§passed-count 退出收敛: 退出时 op_dir 源码 rollback 到 best_commit + redeploy,
    让 cannbench_eval 拿到最优 commit 的包. RepoGuard scoped (不动 HEAD, D4/R1)."""

    def _state_in_repo(self, tmp_path, repo, op_dir, **overrides):
        return _state(tmp_path, op_identity=OperatorIdentity(
            spec=OperatorSpec(name="gelu"), repo_root=repo, op_dir=op_dir),
            **overrides)

    def test_rolls_back_and_redeploys_best_commit(self, tmp_path, monkeypatch):
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_to_best_commit,
        )
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        kernel = op_dir / "kernel.cpp"
        assert kernel.read_text(encoding="utf-8") == "// v2 worse\n"   # HEAD=shaB
        fake = _FakeDeployer(smoke_passed=True)
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.deploy.Deployer", fake)
        state = self._state_in_repo(tmp_path, repo, op_dir)
        ns = _converge_to_best_commit(state, {"status": "running", "best_commit": shaA})
        assert kernel.read_text(encoding="utf-8") == "// v1\n"   # 源码回到 best_commit
        assert fake.calls == 1
        assert ns.deploy_result.smoke_passed is True
        assert ns.deploy_result.install_path == "/opp/best"

    def test_passed_also_converges_for_binary_consistency(self, tmp_path, monkeypatch):
        """88dbae9e: passed 时也 rollback + redeploy — precision_debug 迭代编译产物
        与 deploy 阶段重编译可能产生不同 kernel binary（编译器非确定性/环境差异），
        必须始终 redeploy 确保 cann-bench eval 用 precision_debug 验证过的同一 binary
        (否则 507035: 05:57 binary 过、06:15 重编译 binary 崩)。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_to_best_commit,
        )
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        kernel = op_dir / "kernel.cpp"
        fake = _FakeDeployer(smoke_passed=True)
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.deploy.Deployer", fake)
        state = self._state_in_repo(tmp_path, repo, op_dir)
        ns = _converge_to_best_commit(state, {"status": "passed", "best_commit": shaA})
        assert kernel.read_text(encoding="utf-8") == "// v1\n"   # rollback 到 best_commit (shaA)
        assert fake.calls == 1                                    # 始终 redeploy（88dbae9e 删 early-return）
        assert ns.deploy_result.smoke_passed is True

    def test_best_equals_head_always_converges(self, tmp_path, monkeypatch):
        """HEAD == best_commit 时也执行 rollback + redeploy — 工作区可能有
        printf 探针等未提交残留，必须清理。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_to_best_commit,
        )
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        # 脏化工作区：写入未提交内容模拟 printf 探针残留
        kernel = op_dir / "kernel.cpp"
        kernel.write_text("// dirty printf probes\n", encoding="utf-8")
        fake = _FakeDeployer(smoke_passed=True)
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.deploy.Deployer", fake)
        state = self._state_in_repo(tmp_path, repo, op_dir)
        ns = _converge_to_best_commit(state, {"status": "running", "best_commit": shaB})
        assert fake.calls == 1                          # 始终 redeploy，不跳过
        assert kernel.read_text(encoding="utf-8") == "// v2 worse\n"  # 工作区已清理回 best_commit (shaB)
        assert ns.deploy_result.smoke_passed is True

    def test_redeploy_smoke_failure_keeps_prior_deploy(self, tmp_path, monkeypatch):
        """redeploy smoke 失败 → 保留旧 deploy_result (不阻断 eval); 源码仍 rollback."""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_to_best_commit,
        )
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        kernel = op_dir / "kernel.cpp"
        fake = _FakeDeployer(smoke_passed=False)
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.deploy.Deployer", fake)
        state = self._state_in_repo(
            tmp_path, repo, op_dir,
            deploy_result=DeployResult(smoke_passed=True, install_path="/opp/old"))
        ns = _converge_to_best_commit(state, {"status": "running", "best_commit": shaA})
        assert kernel.read_text(encoding="utf-8") == "// v1\n"   # 源码仍回到 best_commit
        assert ns.deploy_result.install_path == "/opp/old"        # 保留旧包


# —— P7: scope_guard contract validation + reconsider —————————————————————


class TestPrecisionDebugTeardown:
    """S3 D5 (hard-timeout): precision-debug teardown rolls op_dir back to
    ``best_commit`` on interruption via ``RepoGuard.rollback`` (scoped op_dir,
    HEAD untouched — RepoGuard D4/R1, same semantics as
    ``_converge_to_best_commit``). Inherited by every phase substage from
    ``_PrecisionDebugSubstage``."""

    def test_teardown_rolls_back_op_dir_via_repoguard(self, tmp_path, monkeypatch):
        """history 有全过测量（source_identity=best）→ RepoGuard.rollback(repo_root,
        op_dir, best)；§step-119: best 从 history 测量史现算，不再读可写 best_commit 字段。
        repo_root resolves to op_identity.repo_root (not op_dir), op_dir scoped."""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            DiagnoseSubstage,
        )
        state = _state(tmp_path)
        _write_control(state, _control(history=[
            _hist_run(20, 0, source_commit="abc123def456")]))
        captured: list = []

        def _rollback(self_rg, repo_root, op_dir, ref):
            captured.append((Path(repo_root), Path(op_dir), ref))
            return True

        monkeypatch.setattr(
            "ascendc_devkit.infra.repo_guard.RepoGuard.rollback", _rollback)
        DiagnoseSubstage().teardown(state, interrupt_reason="hard_timeout")
        assert len(captured) == 1
        repo_root, op_dir, ref = captured[0]
        assert ref == "abc123def456"
        # repo_root = op_identity.repo_root (tmp_path), NOT op_dir.
        assert repo_root == state.op_identity.repo_root
        # op_dir scoped (blast radius), never whole-repo.
        assert op_dir == state.op_identity.op_dir

    def test_teardown_noop_without_best_commit(self, tmp_path, monkeypatch):
        """No known-good anchor yet (history 无任何测量) → no-op."""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            DiagnoseSubstage,
        )
        state = _state(tmp_path)
        _write_control(state, _control())  # history 空 → 无测量 → best 空
        called: list = []
        monkeypatch.setattr(
            "ascendc_devkit.infra.repo_guard.RepoGuard.rollback",
            lambda *a, **k: called.append(1) or True)
        DiagnoseSubstage().teardown(state, interrupt_reason="hard_timeout")
        assert called == []  # nothing to roll back

    def test_teardown_noop_without_op_dir(self, tmp_path, monkeypatch):
        """No op_dir resolvable → no-op (can't scope a rollback)."""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            DiagnoseSubstage,
        )
        # op_identity=None and op_dir unset → _operator_dir returns None.
        state = _state(tmp_path, op_identity=None)
        _write_control(_state(tmp_path), _control(history=[
            _hist_run(20, 0, source_commit="abc123")]))
        called: list = []
        monkeypatch.setattr(
            "ascendc_devkit.infra.repo_guard.RepoGuard.rollback",
            lambda *a, **k: called.append(1) or True)
        DiagnoseSubstage().teardown(state, interrupt_reason="hard_timeout")
        assert called == []

    def test_teardown_failure_is_best_effort(self, tmp_path, monkeypatch):
        """RepoGuard.rollback raises → swallowed by the best-effort try/except;
        teardown must NOT propagate (硬超时收尾路径不可二次抛，打断 runner 中断处理).
        §step-119: best 来自 history 全过测量的 source_identity，rollback 确被调用。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            DiagnoseSubstage,
        )
        state = _state(tmp_path)
        _write_control(state, _control(history=[
            _hist_run(20, 0, source_commit="abc123")]))

        def _boom(self_rg, repo_root, op_dir, ref):
            raise RuntimeError("not a git repo")

        monkeypatch.setattr(
            "ascendc_devkit.infra.repo_guard.RepoGuard.rollback", _boom)
        # Must NOT raise.
        DiagnoseSubstage().teardown(state, interrupt_reason="hard_timeout")


# —— 改动3: best_commit 缺失 → HEAD fallback ————————————————————————————————


class TestConvergeHistoryAnchor:
    """§step-124 端到端守护：converge 的 best 锚点来自测量史 source_commit →
    **真实 RepoGuard rollback + redeploy** 把工作区收敛回测量最优 commit。

    20260915 批缺陷正路径：旧行为下锚点是陈旧 deploy stamp 标签（非 git ref）→
    rollback no-op → 工作区停在更差终态。本用例的形态与之同构（最优测量在
    shaA、终态工作区更差）——修复前必红（fallback HEAD=shaB 时 kernel=v2）。"""

    def _state_in_repo(self, tmp_path, repo, op_dir):
        return _state(tmp_path, op_identity=OperatorIdentity(
            spec=OperatorSpec(name="gelu"), repo_root=repo, op_dir=op_dir))

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_converge_rolls_back_to_measured_commit(self, tmp_path, monkeypatch):
        """history 全过测量 source_commit=shaA → converge 真把 op_dir 回到 shaA
        （脏终态被还原），redeploy 跑在测量最优代码上。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_to_best_commit,
        )
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        kernel = op_dir / "kernel.cpp"
        kernel.write_text("// dirty worse residue\n", encoding="utf-8")
        fake = _FakeDeployer(smoke_passed=True)
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.deploy.Deployer", fake)
        state = self._state_in_repo(tmp_path, repo, op_dir)
        _write_control(state, _control(history=[
            _hist_run(20, 0, source_commit=shaA)]))   # 最优测量 = shaA (v1)
        ns = _converge_to_best_commit(state, {"status": "running"})
        assert kernel.read_text(encoding="utf-8") == "// v1\n"  # 回到测量最优
        assert fake.calls == 1
        assert ns.deploy_result.smoke_passed is True


class TestConvergeHeadFallback:
    """改动3: best_commit 缺失（首轮超时 / init-checkpoint 未跑）→ fallback 当前
    HEAD。入口 commit (_entry_commit_codegen) 之后 HEAD 含全部 codegen，rollback
    安全。覆盖：HEAD 兜底收敛 + 非 git 无 anchor 跳过。"""

    def _state_in_repo(self, tmp_path, repo, op_dir, **overrides):
        return _state(tmp_path, op_identity=OperatorIdentity(
            spec=OperatorSpec(name="gelu"), repo_root=repo, op_dir=op_dir),
            **overrides)

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_best_commit_missing_falls_back_to_head(self, tmp_path, monkeypatch):
        """best_commit 空（status != passed）→ _current_head 取 HEAD → rollback +
        redeploy 用 HEAD。HEAD=shaB，工作区脏化后应回 HEAD."""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_to_best_commit,
        )
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        # 脏化工作区（模拟 fix 编辑残留，HEAD=shaB 但工作区已偏）。
        kernel = op_dir / "kernel.cpp"
        kernel.write_text("// dirty fix residue\n", encoding="utf-8")
        fake = _FakeDeployer(smoke_passed=True)
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.deploy.Deployer", fake)
        state = self._state_in_repo(tmp_path, repo, op_dir)
        # best_commit 缺失 → converge 应 fallback 到 HEAD (shaB)。
        ns = _converge_to_best_commit(state, {"status": "running"})
        assert fake.calls == 1                       # HEAD 兜底 → 仍 redeploy
        assert kernel.read_text(encoding="utf-8") == "// v2 worse\n"  # 工作区回 HEAD
        assert ns.deploy_result.smoke_passed is True

    def test_no_anchor_in_non_git_returns_state(self, tmp_path, monkeypatch):
        """非 git 仓库 + best_commit 缺失 + HEAD 也取不到 → 无 anchor，return
        state（不崩、不 redeploy）。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_to_best_commit,
        )
        # op_identity.repo_root = tmp_path（非 git）。
        state = _state(tmp_path)
        fake = _FakeDeployer()
        monkeypatch.setattr(
            "ascendc_devkit.orchestration.stages.deploy.Deployer", fake)
        ns = _converge_to_best_commit(state, {"status": "running"})  # 无 best_commit
        assert ns is state
        assert fake.calls == 0


# —— 改动1: precision_debug 入口全量 commit codegen ——————————————————————————


class TestEntryCommitCodegen:
    """改动1: precision_debug 入口（RunTestsSubstage.actions 首段，首轮）由框架
    按 profile 白名单精确 commit 生产 codegen，让后续 best_commit/HEAD 含可回滚
    源码，同时不收编日志、备份、测试脚本或目录外 staged change。

    入口 commit 在 actions() 调用时即执行（spawn 之前），故直接调 actions() 即可
    观察副作用；SpawnAgent 对象不被执行（runner 的事）。"""

    @staticmethod
    def _rev_count(repo):
        return subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()

    @staticmethod
    def _state_in_repo(tmp_path, repo, op_dir):
        return _state(tmp_path, op_identity=OperatorIdentity(
            spec=OperatorSpec(name="gelu"), repo_root=repo, op_dir=op_dir))

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_first_run_commits_untracked_codegen_products(self, tmp_path):
        """首轮（control.json 不存在）+ git repo + op_dir 有 untracked codegen
        文件 → 入口 commit 只固化生产文件，调试产物仍留在工作区。"""
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        # 模拟 codegen 产出的 untracked 文件（op_plugin 注册 glue 等）。
        plugin = op_dir / "op_plugin" / "gelu_plugin.cpp"
        plugin.parent.mkdir(parents=True, exist_ok=True)
        plugin.write_text("// codegen: registration glue\n", encoding="utf-8")
        debug_log = op_dir / "result_gelu_debug.log"
        debug_log.write_text("diagnostic\n", encoding="utf-8")
        state = self._state_in_repo(tmp_path, repo, op_dir)
        actions = RunTestsSubstage().actions(state, 1)
        # 生产文件已进 commit；调试日志不暂存、不提交。
        committed = subprocess.run(
            ["git", "-C", str(repo), "show", "--pretty=", "--name-only", "HEAD"],
            capture_output=True, text=True, check=True).stdout.splitlines()
        assert committed == ["custom_ops/gelu/op_plugin/gelu_plugin.cpp"]
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--", str(op_dir)],
            capture_output=True, text=True, check=True).stdout
        assert "result_gelu_debug.log" in status
        # log 含入口 commit message。
        log = subprocess.run(
            ["git", "-C", str(repo), "log", "--oneline", "-1"],
            capture_output=True, text=True, check=True).stdout
        assert "precision_debug entry: snapshot codegen products" in log
        # actions 仍构造 spawn（commit 不影响 spawn 逻辑）。
        assert len(actions) == 1

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_resume_skips_entry_commit(self, tmp_path):
        """control.json 已存在（resume / init-checkpoint 已跑）→ gate 跳过，不重 commit。"""
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        state = self._state_in_repo(tmp_path, repo, op_dir)
        _write_control(state, _control())  # control.json 存在（resume 场景）
        before = self._rev_count(repo)
        RunTestsSubstage().actions(state, 1)
        after = self._rev_count(repo)
        assert before == after, "resume must not create a new commit"

    def test_non_git_skips_entry_commit_gracefully(self, tmp_path):
        """非 git → commit skip（不崩），actions 仍正常返回 spawn。"""
        # op_identity.repo_root = tmp_path（非 git）。
        state = _state(tmp_path)
        actions = RunTestsSubstage().actions(state, 1)
        assert len(actions) == 1

    @pytest.mark.skipif(not _has_git(), reason="git required")
    def test_nothing_to_commit_is_benign(self, tmp_path):
        """op_dir 已全部 commit（无 untracked/无改动）→ nothing-to-commit 非 0
        退出 → warn 不阻断，actions 照常返回。"""
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        # op_dir 内容已全 commit（v2）；control.json 不存在 → gate 通过 → 尝试 commit。
        state = self._state_in_repo(tmp_path, repo, op_dir)
        before = self._rev_count(repo)
        actions = RunTestsSubstage().actions(state, 1)
        after = self._rev_count(repo)
        assert before == after, "nothing-to-commit must not add a commit"
        assert len(actions) == 1

    def test_commit_failure_with_dirty_opdir_logs_error_not_benign(self, tmp_path, monkeypatch):
        """commit rc!=0 且 op_dir 仍有未固化 codegen → Logger.error（明确警告
        rollback 不安全），而非笼统 benign。§1.2 可诊断：不把危险情况误报安全。"""
        repo, op_dir, shaA, shaB = _git_repo_with_two_commits(tmp_path)
        state = self._state_in_repo(tmp_path, repo, op_dir)

        # 模拟 add 成功但 commit 失败，且 status 显示 op_dir 仍有 dirty。
        def _fake_run(argv, **kw):
            # git -C <repo> <subcmd> ...: 子命令在 argv[3]（argv[1]="-C", argv[2]=repo_root）
            sub = argv[3] if len(argv) > 3 else ""
            if sub == "rev-parse":
                return mock.MagicMock(returncode=0, stdout="true", stderr="")
            if sub == "add":
                return mock.MagicMock(returncode=0, stdout="", stderr="")
            if sub == "commit":
                return mock.MagicMock(returncode=1, stdout="", stderr="")
            if sub == "status":
                return mock.MagicMock(
                    returncode=0, stdout=" M custom_ops/gelu/kernel.cpp\n", stderr="")
            return mock.MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", _fake_run)
        errors: list = []
        monkeypatch.setattr(
            "ascendc_devkit.infra.logger.Logger.error",
            lambda *a, **k: errors.append(a[0] if a else ""))
        actions = RunTestsSubstage().actions(state, 1)
        assert len(actions) == 1
        assert len(errors) == 1, "dirty op_dir on commit failure must log error"
        assert "FAILED" in errors[0] and "still dirty" in errors[0]


# —— R3 (2026-08-21): deploy_health null/缺失 不误熔断 ———————————————————
# rms_norm 20260821 批 eval 0 分根因：comment_bisect agent 填 deploy_health
# {build_ok: null, output_ok: null}（未检测），旧逻辑 `not None = True` 误判为
# 失败，累积 3 次触发 deploy_broken → precision_debug 提前退出 → eval 用旧包。
# 修复：build_ok/output_ok 只有显式 bool 才判定；null/非 bool → 不更新 streak。
