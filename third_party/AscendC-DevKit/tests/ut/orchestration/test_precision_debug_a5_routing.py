"""A5 precision_debug routing chain regression tests.

Covers the full routing loop for the new 6-stage A5 flow:

    transition() → _extract_a5_debug_checkpoint(cp) → state._debug_checkpoint
                 → resolve_condition(state) → _A5_TRANSITION_TABLE

Regression guard for 2026-08-01: baseline reported 0/20 with all 20 cases
error_layer=kernel, but ``_extract_a5_debug_checkpoint`` did not carry
``failed_case_queue``, so ``resolve_condition`` saw an empty queue, fell
through to ``all_pass``, and the group wrongly escalated ``passed`` →
cannbench_adapt ran. These tests pin the routing decisions (not the skills).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ascendc_devkit.domain.operator import OperatorIdentity, OperatorSpec
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
    BaselineSubstage,
    KernelDebugSubstage,
    OpPluginDebugSubstage,
    VfTestSubstage,
    _A5_TRANSITION_TABLE,
    _extract_a5_debug_checkpoint,
)


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


@pytest.fixture()
def repo(tmp_path):
    repo = tmp_path / "repo"
    op_dir = repo / "ops" / "softmax"
    op_dir.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "precision-debug@test.invalid")
    _git(repo, "config", "user.name", "Precision Debug Test")
    (repo / "README.md").write_text("repo\n", encoding="utf-8")
    (op_dir / "kernel.cpp").write_text("// initial\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo, op_dir


def _state(tmp_path: Path, repo: Path, op_dir: Path) -> State:
    identity = OperatorIdentity(
        spec=OperatorSpec(name="softmax"), repo_root=repo, op_dir=op_dir)
    return State.empty().with_updates(
        op_identity=identity,
        design_target_chip="A5",
    ).with_field("_workspace", _Workspace(tmp_path))


def _write_baseline_result(
    state: State, *,
    baseline_status: str = "failed",
    cross_compare: list[dict] | None = None,
    error_type: str = "",
    classification: dict | None = None,
    rc_total: int = 20,
    rc_pass: int | None = None,
    kl_total: int = 20,
    kl_pass: int | None = None,
) -> None:
    """Write a baseline_result.json fixture.

    Default tool summaries follow the old all-rc/failed semantics: a ``passed``
    status implies rc+kl full pass; a ``failed`` status defaults to rc/kl 0/20
    (callers that exercise the rc-false-alarm / kl-full edge override pass counts).
    """
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _phase_path,
    )
    p = _phase_path(state, "baseline_result.json", round_suffix=False)
    p.parent.mkdir(parents=True, exist_ok=True)
    if rc_pass is None:
        rc_pass = rc_total if baseline_status == "passed" else 0
    if kl_pass is None:
        kl_pass = kl_total if baseline_status == "passed" else 0
    p.write_text(json.dumps({
        "baseline_status": baseline_status,
        "baseline_total_count": 20,
        "baseline_passed_count": 0,
        "baseline_max_diff": 999.0,
        "rc_result": {"pass": rc_pass, "total": rc_total, "max_diff": 0.0,
                      "failed_cases": []},
        "kl_result": {"pass": kl_pass, "total": kl_total, "max_diff": 0.0,
                      "failed_cases": []},
        "cross_compare": cross_compare or [],
        "classification": classification or {},
        "error_type": error_type,
    }), encoding="utf-8")


def _case(case_id: str, *, rc_pass: bool, kl_pass: bool,
          error_layer: str | None = None, actionable: bool | None = None,
          failure_type: str = "precision") -> dict:
    # 模拟真实 baseline agent 产物：默认 error_layer 按 rc/kl 推导、actionable=True
    # （真缺陷）。测 cann-bench relative-error 误报时显式传 error_layer="none",
    # actionable=False, failure_type="within_abs_tolerance"。
    if error_layer is None:
        error_layer = ("op_plugin" if (rc_pass is False and kl_pass is True)
                       else "kernel")
    if actionable is None:
        actionable = True
    return {
        "case_id": case_id,
        "shape": [1024, 1024],
        "dtype": "float16",
        "rc_pass": rc_pass,
        "kl_pass": kl_pass,
        "max_diff_rc": 999.0 if not rc_pass else 0.0,
        "max_diff_kl": 999.0 if not kl_pass else 0.0,
        "error_layer": error_layer,
        "actionable": actionable,
        "failure_type": failure_type,
    }


# —— bug regression: _extract_a5_debug_checkpoint must carry the queue ——————

def test_extract_a5_routing_snapshot_carries_failed_case_queue():
    queue = [{"case_id": "level2/softmax_1", "status": "pending",
              "attempt_count": 0, "error_layer": "kernel"}]
    dc = _extract_a5_debug_checkpoint({
        "status": "in_progress", "phase": "baseline",
        "failed_case_queue": queue, "current_case_index": 0,
    })
    assert dc["failed_case_queue"] == queue
    assert dc["failed_case_count"] == 1


# —— baseline routing: 20 kernel failures MUST route to kernel_debug ————

def test_baseline_kernel_failures_resolve_has_kernel_failures(
        tmp_path, repo):
    """Faithful reproduction: baseline 0/20 with all kernel failures must
    resolve to ``has_kernel_failures`` (NOT fall through to ``all_pass``)."""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    cases = [_case(f"level2/softmax_{i}", rc_pass=False, kl_pass=False)
             for i in range(1, 21)]
    _write_baseline_result(state, cross_compare=cases)

    stage = BaselineSubstage()
    out = stage.transition(state, None)

    assert out._debug_checkpoint["failed_case_count"] == 20
    assert out._debug_checkpoint["failed_case_queue"][0]["error_layer"] == "kernel"
    assert stage.resolve_condition(out) == "has_kernel_failures"


def test_baseline_op_plugin_failures_resolve_has_op_plugin_failures(
        tmp_path, repo):
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    cases = [_case("level2/softmax_1", rc_pass=False, kl_pass=True),
             _case("level2/softmax_2", rc_pass=False, kl_pass=True)]
    _write_baseline_result(state, cross_compare=cases)

    stage = BaselineSubstage()
    out = stage.transition(state, None)

    # 纯 op_plugin 失败（无 kernel 失败）→ 仍路由 op_plugin_debug
    assert stage.resolve_condition(out) == "has_op_plugin_failures"


def test_baseline_mixed_failures_prefer_kernel_debug(tmp_path, repo):
    """Q6 修订：混合队列（kernel + op_plugin 同时失败）→ 优先调度 kernel_debug。

    出现精度问题时优先让 ascendc-precision-kernel-debug 解 kernel/tiling 层问题；
    op_plugin case 由 per-case 阶段跳过，kernel 工作收敛后回 baseline 重跑分流。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    cases = [_case("level2/softmax_1", rc_pass=False, kl_pass=True),   # op_plugin
             _case("level2/softmax_2", rc_pass=False, kl_pass=False)]  # kernel
    _write_baseline_result(state, cross_compare=cases)

    stage = BaselineSubstage()
    out = stage.transition(state, None)

    assert out._debug_checkpoint["failed_case_count"] == 2
    assert stage.resolve_condition(out) == "has_kernel_failures"


def test_baseline_all_pass_when_baseline_status_passed(tmp_path, repo):
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_baseline_result(state, baseline_status="passed")

    stage = BaselineSubstage()
    out = stage.transition(state, None)

    assert stage.resolve_condition(out) == "all_pass"


def test_baseline_all_pass_clears_stale_queue(tmp_path, repo):
    """baseline 全 pass = 无失败 case → 必须清空旧 failed_case_queue 残留。

    场景：上一轮 precision_debug 残留了 failed_case_queue（如全部 resolved 后回
    baseline 验收），本轮 baseline 全 pass → passed 收尾，checkpoint 不得再显示
    旧错误列表（否则读 checkpoint 的人/诊断误以为还有失败 case）。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "baseline",
        "failed_case_queue": [
            {"case_id": "c18", "error_layer": "kernel", "status": "resolved",
             "attempt_count": 0, "max_diff_kl": 2.98e-07},
            {"case_id": "c19", "error_layer": "kernel", "status": "skipped",
             "attempt_count": 3, "max_diff_kl": 31.0},
        ],
        "current_case_index": 1,
    }), encoding="utf-8")
    _write_baseline_result(state, baseline_status="passed")

    stage = BaselineSubstage()
    out = stage.transition(state, None)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    assert cp["status"] == "passed"
    assert cp["failed_case_queue"] == []
    assert cp["current_case_index"] == 0
    assert out._debug_checkpoint["failed_case_count"] == 0
    assert out._debug_checkpoint["failing_cases"] == []
    assert stage.resolve_condition(out) == "all_pass"


# —— 双工具验收门槛：passed 必须 rc 与 kl 双双全过 ——————

def test_baseline_rc_pass_kl_fail_agent_passed_downgraded_not_all_pass(
        tmp_path, repo):
    """2026-09-02 cumsum_min 轨迹回归：rc 20/20 + kl 19/20（case5 rc 过 kl 挂）。
    agent 自报 baseline_status=passed，但双工具未全过 → transition 机械降级 failed、
    kl-only case 以 kernel 层入队，resolve 必须路由 kernel_debug，绝不 all_pass 结束。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    cases = [_case(f"c{i}", rc_pass=True, kl_pass=True) for i in range(1, 20)]
    cases.append(_case("c5", rc_pass=True, kl_pass=False))  # rc 过 kl 挂
    _write_baseline_result(state, baseline_status="passed",
                           cross_compare=cases,
                           rc_pass=20, kl_pass=19)
    stage = BaselineSubstage()
    out = stage.transition(state, None)

    dc = out._debug_checkpoint
    assert dc["double_tool_passed"] is False
    assert dc["baseline_status"] == "failed"
    q = dc["failed_case_queue"]
    assert len(q) == 1
    assert q[0]["case_id"] == "c5"
    assert q[0]["error_layer"] == "kernel"
    assert q[0]["status"] == "pending"
    assert stage.resolve_condition(out) == "has_kernel_failures"


def test_baseline_kl_only_failure_ignores_agent_classification(
        tmp_path, repo):
    """agent 报 failed 但 classification 谎称无缺陷（把 kl-only 失败剔成非缺陷）：
    框架按 cross_compare 实测把 rc 过/kl 挂 case 以 kernel 层入队，classification
    不能抹掉已入队的 kl 失败直通 all_pass。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    cases = [_case("c5", rc_pass=True, kl_pass=False, error_layer=None)]
    _write_baseline_result(state, baseline_status="failed",
                           cross_compare=cases,
                           classification={"has_kernel_failures": False,
                                           "has_op_plugin_failures": False},
                           rc_pass=20, kl_pass=19)
    stage = BaselineSubstage()
    out = stage.transition(state, None)

    q = out._debug_checkpoint["failed_case_queue"]
    assert len(q) == 1
    assert q[0]["case_id"] == "c5"
    assert q[0]["error_layer"] == "kernel"
    assert stage.resolve_condition(out) == "has_kernel_failures"


def test_baseline_all_pass_requires_both_tools_full(tmp_path, repo):
    """双工具门槛：kl 未全过 → 绝不 all_pass（无 cross_compare 数据时走失败分支
    兜底 → no_case_data escalate exhausted，绝不假 passed）。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_baseline_result(state, baseline_status="passed",
                           rc_pass=20, kl_pass=19)  # kl 未全过
    stage = BaselineSubstage()
    out = stage.transition(state, None)

    assert out._debug_checkpoint["double_tool_passed"] is False
    assert stage.resolve_condition(out) == "no_case_data"


def test_baseline_rc_partial_kl_full_no_classification_not_all_pass(
        tmp_path, repo):
    """rc 未全过 + kl 全过 + 无 cross_compare / 无 classification → 不得静默
    all_pass：agent 未用 classification 担保 rc 失败全部为非缺陷（误报剔除），
    rc 失败 case 又未进 cross_compare → 契约缺失，escalate exhausted 而非假 passed。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_baseline_result(state, baseline_status="failed",
                           rc_pass=19, kl_pass=20)  # rc 未全过，kl 全过
    stage = BaselineSubstage()
    out = stage.transition(state, None)

    assert out._debug_checkpoint["double_tool_passed"] is False
    assert out._debug_checkpoint["rc_full_pass"] is False
    assert out._debug_checkpoint["kl_full_pass"] is True
    assert stage.resolve_condition(out) == "no_case_data"


# —— bug regression 2026-08-24: fresh latest 不得被陈旧 round 文件覆盖 ——————

def test_baseline_fresh_latest_not_clobbered_by_stale_round_file(tmp_path, repo):
    """2026-08-24 轨迹：baseline 重入验收 agent 双工具全 pass，写 fresh
    ``baseline_result.json``（latest），但首轮的 ``baseline_round_1_result.json``
    （failed）还在。transition 的 ``_sync_phase_latest`` 兜底用陈旧 round 文件
    覆盖 fresh latest → ``_load_result`` 读到 failed → 假 status_mismatch →
    baseline↔baseline 重试循环（白跑一整轮双工具）。修复后 latest 是权威，必须
    读 fresh passed → ``all_pass`` 直通结束。"""
    import os
    import time
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _phase_path,
    )
    latest = _phase_path(state, "baseline_result.json", round_suffix=False)
    stale_round = latest.parent / "baseline_round_1_result.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    stale_round.write_text(json.dumps({
        "baseline_status": "failed",
        "cross_compare": [], "classification": {},
    }), encoding="utf-8")
    os.utime(stale_round, (time.time() - 7200, time.time() - 7200))
    _write_baseline_result(state, baseline_status="passed")
    os.utime(latest, (time.time(), time.time()))

    stage = BaselineSubstage()
    out = stage.transition(state, None)

    data = json.loads(latest.read_text(encoding="utf-8"))
    assert data["baseline_status"] == "passed"
    assert stage.resolve_condition(out) == "all_pass"


def test_baseline_common_context_points_round_result_path_to_latest(
        tmp_path, repo):
    """非 round 约定阶段（baseline）不注入 round 文件路径：``phase_round_result_path``
    统一指向 plain latest 路径（agent 真实写入目标），消除与任务"写入 latest"冲突，
    杜绝 ``_sync_phase_latest`` 兜底误用陈旧 round 文件。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _phase_path,
    )
    ctx = BaselineSubstage()._common_context(state)
    latest = _phase_path(state, "baseline_result.json", round_suffix=False)
    assert ctx["phase_round_result_path"] == str(latest)
    assert "_round_" not in ctx["phase_round_result_path"]


def test_sync_phase_latest_still_relays_newer_round_file(tmp_path, repo):
    """round 约定阶段（kernel_debug）relay 语义保留：latest 陈旧、round 文件更新
    → 仍应 relay 到 latest。Fix 只防"陈旧 src 覆盖新鲜 latest"，不阻塞正常 relay。"""
    import os
    import time
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _phase_path,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
        KernelDebugSubstage,
    )
    latest = _phase_path(state, "kernel_debug_result.json", round_suffix=False)
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps({"debug_status": "fixed", "round": 2}),
                      encoding="utf-8")
    os.utime(latest, (time.time() - 7200, time.time() - 7200))
    round3 = latest.parent / "kernel_debug_round_3_result.json"
    round3.write_text(json.dumps({"debug_status": "need_vf", "round": 3}),
                      encoding="utf-8")
    os.utime(round3, (time.time(), time.time()))

    KernelDebugSubstage()._sync_phase_latest(state)

    data = json.loads(latest.read_text(encoding="utf-8"))
    assert data["debug_status"] == "need_vf"
    assert data["round"] == 3


def test_baseline_queue_enriches_shape_dtype_from_cases_csv(
        tmp_path, repo):
    """When the baseline agent's cross_compare omits shape/dtype (its contract
    carries only comparison results), the framework must enrich the queue from
    the authoritative cases.csv so injected current_case blocks never show
    `<无>` for shape/dtype (real trace: kernel_debug got shape/dtype empty)."""
    import csv as _csv
    _, op_dir = repo
    cases_path = tmp_path / "cases.csv"
    with cases_path.open("w", encoding="utf-8", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["operator", "case_id", "input_shape", "dtype", "attrs",
                    "value_range", "note"])
        w.writerow(["Op", "1", json.dumps([[8, 32, 64, 64], [32], [32]]),
                    json.dumps(["float16", "float16", "float16"]),
                    json.dumps({}), json.dumps([-1, 1]), "align"])
        w.writerow(["Op", "2", json.dumps([[2, 128, 256, 256], [128], [128]]),
                    json.dumps(["bfloat16", "bfloat16", "bfloat16"]),
                    json.dumps({}), json.dumps([-3, 3]), "big"])
    state = _state(tmp_path, repo[0], op_dir).with_updates(
        cases_path=cases_path)
    cases = [
        {"case_id": 1, "rc_pass": False, "kl_pass": False,
         "error_layer": "kernel", "failure_type": "precision",
         "max_diff_rc": 9.9, "max_diff_kl": 9.9},
        {"case_id": 2, "rc_pass": False, "kl_pass": False,
         "error_layer": "kernel", "failure_type": "vector_error",
         "max_diff_rc": 999.0, "max_diff_kl": None},
    ]
    _write_baseline_result(state, cross_compare=cases)

    stage = BaselineSubstage()
    out = stage.transition(state, None)
    q = out._debug_checkpoint["failed_case_queue"]
    assert q[0]["shape"] == [8, 32, 64, 64]
    assert q[0]["dtype"] == "float16"
    assert q[1]["shape"] == [2, 128, 256, 256]
    assert q[1]["dtype"] == "bfloat16"


def test_baseline_queue_agent_shape_wins_over_cases_csv(tmp_path, repo):
    """When the agent DID include shape/dtype in cross_compare, that value wins
    (agent is data-faithful for metadata it chose to report); cases.csv is only
    the fallback for missing fields."""
    import csv as _csv
    _, op_dir = repo
    cases_path = tmp_path / "cases.csv"
    with cases_path.open("w", encoding="utf-8", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["operator", "case_id", "input_shape", "dtype", "attrs",
                    "value_range", "note"])
        w.writerow(["Op", "1", json.dumps([[8, 8]]), json.dumps(["float16"]),
                    json.dumps({}), json.dumps([-1, 1]), ""])
    state = _state(tmp_path, repo[0], op_dir).with_updates(
        cases_path=cases_path)
    cases = [
        {"case_id": 1, "shape": [64, 64], "dtype": "float32",
         "rc_pass": False, "kl_pass": False,
         "error_layer": "kernel", "failure_type": "precision",
         "max_diff_rc": 9.9, "max_diff_kl": 9.9},
    ]
    _write_baseline_result(state, cross_compare=cases)

    stage = BaselineSubstage()
    out = stage.transition(state, None)
    q = out._debug_checkpoint["failed_case_queue"]
    assert q[0]["shape"] == [64, 64]
    assert q[0]["dtype"] == "float32"


# —— cann-bench relative-error 误报过滤 + classification 路由 ————————————

def test_baseline_filters_non_actionable_cannbench_false_alarms(tmp_path, repo):
    """actionable=false 的 cann-bench relative-error 误报不进 failed_case_queue。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    cases = [
        _case("level2/softmax_1", rc_pass=False, kl_pass=True,
              error_layer="none", actionable=False,
              failure_type="within_abs_tolerance"),
        _case("level2/softmax_4", rc_pass=False, kl_pass=False,
              error_layer="kernel", actionable=True),
    ]
    _write_baseline_result(state, cross_compare=cases,
                           classification={"has_op_plugin_failures": False,
                                           "has_kernel_failures": True})
    stage = BaselineSubstage()
    out = stage.transition(state, None)
    assert out._debug_checkpoint["failed_case_count"] == 1
    assert out._debug_checkpoint["failed_case_queue"][0]["case_id"] == "level2/softmax_4"
    assert stage.resolve_condition(out) == "has_kernel_failures"


def test_baseline_softmax_oscillation_regression(tmp_path, repo):
    """复现 softmax 9bec8c：7 kernel 真缺陷 + 7 cann-bench 误报（rc_fail+kl_pass,
    within_abs_tolerance）→ 必须路由 kernel_debug，不再 baseline↔op_plugin_debug 振荡。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    kernel = [_case(f"level2/softmax_{i}", rc_pass=False, kl_pass=False,
                    error_layer="kernel", actionable=True)
              for i in (4, 5, 6, 11, 16, 17, 19)]
    false_alarms = [_case(f"level2/softmax_{i}", rc_pass=False, kl_pass=True,
                          error_layer="none", actionable=False,
                          failure_type="within_abs_tolerance")
                    for i in (1, 2, 3, 8, 9, 10, 18)]
    _write_baseline_result(state, cross_compare=kernel + false_alarms,
                           classification={"has_op_plugin_failures": False,
                                           "has_kernel_failures": True})
    stage = BaselineSubstage()
    out = stage.transition(state, None)
    assert out._debug_checkpoint["failed_case_count"] == 7  # 7 误报被过滤
    assert stage.resolve_condition(out) == "has_kernel_failures"


def test_baseline_all_non_defect_resolves_all_pass(tmp_path, repo):
    """baseline failed 但全 case actionable=false（cann-bench 全误报）→ all_pass，
    非 no_case_data（不会误 escalate exhausted）。

    双工具门槛下 rc 未全过的唯一放行前提：kl 全过 且 rc 失败全部被 agent 显式标
    actionable=false（within_abs_tolerance / pass_both 误报）。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    cases = [_case("level2/softmax_1", rc_pass=False, kl_pass=True,
                   error_layer="none", actionable=False,
                   failure_type="within_abs_tolerance")]
    _write_baseline_result(state, cross_compare=cases,
                           classification={"has_op_plugin_failures": False,
                                           "has_kernel_failures": False},
                           rc_pass=19, kl_pass=20)
    stage = BaselineSubstage()
    out = stage.transition(state, None)
    assert out._debug_checkpoint["failed_case_count"] == 0
    assert out._debug_checkpoint["kl_full_pass"] is True
    assert stage.resolve_condition(out) == "all_pass"


def test_baseline_queue_fallback_when_no_classification(tmp_path, repo):
    """agent 未提供 classification（旧产物）→ 从 queue 的 error_layer 推导（兜底）。

    Q6 修订：混合队列下 kernel 优先。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    cases = [_case("level2/softmax_1", rc_pass=False, kl_pass=True),   # op_plugin
             _case("level2/softmax_2", rc_pass=False, kl_pass=False)]  # kernel
    _write_baseline_result(state, cross_compare=cases)  # 无 classification
    stage = BaselineSubstage()
    out = stage.transition(state, None)
    assert stage.resolve_condition(out) == "has_kernel_failures"


def test_baseline_classification_mixed_prefers_kernel(tmp_path, repo):
    """classification 同时标 has_kernel_failures / has_op_plugin_failures →
    kernel 优先（Q6 修订）。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    cases = [_case("level2/softmax_1", rc_pass=False, kl_pass=True,
                   error_layer="op_plugin"),
             _case("level2/softmax_2", rc_pass=False, kl_pass=False,
                   error_layer="kernel")]
    _write_baseline_result(state, cross_compare=cases,
                           classification={"has_op_plugin_failures": True,
                                           "has_kernel_failures": True})
    stage = BaselineSubstage()
    out = stage.transition(state, None)
    assert stage.resolve_condition(out) == "has_kernel_failures"


# —— op_plugin_debug → kernel_debug handoff (need_kernel_debug) ————————
# 适配层排查确认非适配层根因/已修复、残余失败在 kernel/tiling 层时，op_plugin_debug
# 必须有诚实出口直接移交 kernel_debug，而非 retry 烧轮次后 escalated 杀流程。
# 框架在 transition 内改标 kernel_cases 为 error_layer=kernel + pending，
# 并把 current_case_index 指向第一个 pending 的 kernel case。

def _write_a5_checkpoint(state, **overrides):
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    cp = {
        "status": "in_progress",
        "phase": "op_plugin_debug",
        "op_plugin_round": 0,
        "max_op_plugin_rounds": 3,
        "failed_case_queue": [
            {"case_id": "level2/softmax_1", "shape": [1024, 1024],
             "dtype": "float16", "error_layer": "op_plugin",
             "failure_type": "precision", "status": "pending", "attempt_count": 0},
            {"case_id": "level2/softmax_2", "shape": [2048, 1024],
             "dtype": "float16", "error_layer": "op_plugin",
             "failure_type": "precision", "status": "pending", "attempt_count": 0},
        ],
        "current_case_index": 0,
    }
    cp.update(overrides)
    p.write_text(json.dumps(cp), encoding="utf-8")
    return p


def _write_op_plugin_result(state, **fields):
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _expected_round_result_path,
    )
    p = _expected_round_result_path(state, "op_plugin_result.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "phase": "op_plugin_debug",
        "debug_status": "converged",
        "framework_error": "none",
        "code_modified": False,
    }
    result.update(fields)
    p.write_text(json.dumps(result), encoding="utf-8")
    return p


def test_op_plugin_handoff_reroutes_kernel_cases(tmp_path, repo):
    """need_kernel_debug + kernel_cases → 对应 case 改标 error_layer=kernel +
    pending，current_case_index 指向第一个 kernel case，路由 kernel_debug。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_checkpoint(state)
    _write_op_plugin_result(
        state, debug_status="need_kernel_debug",
        kernel_cases=["level2/softmax_2"])

    stage = OpPluginDebugSubstage()
    out = stage.transition(state, None)

    assert out._debug_checkpoint["debug_status"] == "need_kernel_debug"
    queue = out._debug_checkpoint["failed_case_queue"]
    assert queue[0]["error_layer"] == "op_plugin" and queue[0]["status"] == "resolved"
    assert queue[1]["error_layer"] == "kernel" and queue[1]["status"] == "pending"
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    assert cp["current_case_index"] == 1
    assert stage.resolve_condition(out) == "need_kernel_debug"
    assert _A5_TRANSITION_TABLE["op_plugin_debug"]["need_kernel_debug"] == (
        "kernel_debug", "corrective")


def test_op_plugin_handoff_empty_kernel_cases_marks_all_kernel(tmp_path, repo):
    """kernel_cases 缺省/空 → 适配层全局判定正确，全部残余失败视为 kernel 层移交。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_checkpoint(state)
    _write_op_plugin_result(state, debug_status="need_kernel_debug")

    stage = OpPluginDebugSubstage()
    out = stage.transition(state, None)

    queue = out._debug_checkpoint["failed_case_queue"]
    assert all(c["error_layer"] == "kernel" and c["status"] == "pending"
               for c in queue)
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    assert cp["current_case_index"] == 0
    assert stage.resolve_condition(out) == "need_kernel_debug"


def test_op_plugin_handoff_no_pending_falls_back_to_converged(tmp_path, repo):
    """need_kernel_debug 但 kernel_cases 未命中任何 case → 无 pending case →
    退化走 converged 回 baseline 重新交叉对比，不硬闯空队列 kernel_debug。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_checkpoint(state)
    _write_op_plugin_result(
        state, debug_status="need_kernel_debug",
        kernel_cases=["level2/nonexistent"])

    stage = OpPluginDebugSubstage()
    out = stage.transition(state, None)

    assert out._debug_checkpoint.get("_handoff_no_pending") is True
    assert stage.resolve_condition(out) == "converged"


def test_op_plugin_retry_clamped_to_exhausted_at_max_rounds(tmp_path, repo):
    """轮次上限只钳制 retry：agent 在 max_op_plugin_rounds 处仍报 retry → exhausted。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_checkpoint(state, op_plugin_round=2, max_op_plugin_rounds=3)
    _write_op_plugin_result(state, debug_status="retry")

    stage = OpPluginDebugSubstage()
    out = stage.transition(state, None)

    assert out._debug_checkpoint["debug_status"] == "exhausted"
    assert stage.resolve_condition(out) == "exhausted"


def test_op_plugin_need_kernel_debug_not_clamped_at_max_rounds(tmp_path, repo):
    """need_kernel_debug 是正向决策出口，即使已达轮次上限也不被钳成 exhausted。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_checkpoint(state, op_plugin_round=9, max_op_plugin_rounds=10)
    _write_op_plugin_result(state, debug_status="need_kernel_debug",
                            kernel_cases=["level2/softmax_1"])

    stage = OpPluginDebugSubstage()
    out = stage.transition(state, None)

    assert out._debug_checkpoint["debug_status"] == "need_kernel_debug"
    assert stage.resolve_condition(out) == "need_kernel_debug"


def test_op_plugin_debug_known_status_values_include_handoff():
    """need_kernel_debug 必须在已知状态集合内，否则 agent 上报被判 invalid_status。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _KNOWN_STATUS_VALUES_BY_PHASE,
    )
    assert "need_kernel_debug" in _KNOWN_STATUS_VALUES_BY_PHASE["op_plugin_debug"]


def test_op_plugin_debug_transition_table_has_need_kernel_debug():
    tbl = _A5_TRANSITION_TABLE["op_plugin_debug"]
    assert tbl["need_kernel_debug"] == ("kernel_debug", "corrective")
    assert tbl["converged"] == ("baseline", "validation")
    assert tbl["retry"] == ("op_plugin_debug", "corrective")
    assert tbl["exhausted"] == ("__escalate__:exhausted", "validation")


# —— cross-phase conclusion relay (conclusions.json) ————————
# 每个阶段把一段话结论写进自己的 result JSON `conclusion` 字段，框架物化到
# {debug_dir}/conclusions.json（phases[phase][] 保留轮次历史）；后续阶段 agent
# 开工前读 `conclusions_path` 即可看到流程中其他 agent 的结论（§2.3 文件接力）。

def test_phase_conclusion_materialized_to_relay(tmp_path, repo):
    """op_plugin_debug 结果 JSON 的 conclusion 一段话 → 框架物化到 conclusions.json。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_checkpoint(state)
    _write_op_plugin_result(
        state, debug_status="converged",
        conclusion="适配层已修好：dtype 转换误用 FP32 导致精度损失，改回 FP16 后 RC/KL 一致。")

    stage = OpPluginDebugSubstage()
    stage.transition(state, None)

    from ascendc_devkit.orchestration.stages.precision_debug_a5.conclusions import (
        _read_conclusions,
    )
    data = _read_conclusions(state)
    entries = data["phases"]["op_plugin_debug"]
    assert len(entries) == 1
    assert entries[0]["round"] == 1
    assert "适配层已修好" in entries[0]["conclusion"]
    assert entries[0]["updated_at"]


def test_phase_conclusion_accumulates_across_rounds(tmp_path, repo):
    """同阶段多轮结论按轮次追加，历史不丢失。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_checkpoint(state, op_plugin_round=0)
    _write_op_plugin_result(state, debug_status="retry",
                            conclusion="第一轮：dtype 转换可疑，待验证。")
    OpPluginDebugSubstage().transition(state, None)
    _write_a5_checkpoint(state, op_plugin_round=1)
    _write_op_plugin_result(state, debug_status="converged",
                            conclusion="第二轮：确认 dtype 转换是根因并已修复。")
    OpPluginDebugSubstage().transition(state, None)

    from ascendc_devkit.orchestration.stages.precision_debug_a5.conclusions import (
        _read_conclusions,
    )
    entries = _read_conclusions(state)["phases"]["op_plugin_debug"]
    assert [e["round"] for e in entries] == [1, 2]
    assert "第一轮" in entries[0]["conclusion"] and "第二轮" in entries[1]["conclusion"]


def test_phase_without_conclusion_skipped_not_blocking(tmp_path, repo):
    """缺 conclusion 字段 → 不写 relay（留 warn），但不影响路由。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_checkpoint(state)
    _write_op_plugin_result(state, debug_status="converged")  # 无 conclusion

    stage = OpPluginDebugSubstage()
    out = stage.transition(state, None)

    from ascendc_devkit.orchestration.stages.precision_debug_a5.conclusions import (
        _read_conclusions,
    )
    data = _read_conclusions(state)
    assert "op_plugin_debug" not in data.get("phases", {})
    assert stage.resolve_condition(out) == "converged"


def test_baseline_conclusion_materialized_round_0(tmp_path, repo):
    """baseline 用固定 round 0 物化结论。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_baseline_result(state, cross_compare=[])
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _phase_path,
    )
    p = _phase_path(state, "baseline_result.json", round_suffix=False)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["conclusion"] = "基线 20/20 全过，流程直接结束。"
    p.write_text(json.dumps(data), encoding="utf-8")

    stage = BaselineSubstage()
    stage.transition(state, None)

    from ascendc_devkit.orchestration.stages.precision_debug_a5.conclusions import (
        _read_conclusions,
    )
    entries = _read_conclusions(state)["phases"]["baseline"]
    assert entries[0]["round"] == 0
    assert "全过" in entries[0]["conclusion"]


def test_common_context_injects_conclusions_path(tmp_path, repo):
    """_common_context 注入 conclusions_path；paths 块提示 agent 开工前读取。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.baseline import (
        BaselineSubstage,
    )
    state = _state(tmp_path, repo[0], repo[1])
    stage = BaselineSubstage()
    ctx = stage._common_context(state)
    assert str(ctx["conclusions_path"]).endswith("precision_debug_a5/conclusions.json")
    block = stage._format_paths_block(ctx)
    assert "conclusions_path" in block
    assert "conclusions.json" in block


def test_next_agent_prompt_includes_previous_agent_conclusion(tmp_path, repo):
    """上一个 agent 的结论在下一个 agent spawn 的 prompt 中直接可见（构造性保证，
    不依赖 agent 自行 Read 文件）。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_baseline_result(state, cross_compare=[])
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _phase_path,
    )
    p = _phase_path(state, "baseline_result.json", round_suffix=False)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["conclusion"] = "基线发现 3 个 op_plugin 层失败 case，路由适配层修复。"
    p.write_text(json.dumps(data), encoding="utf-8")
    BaselineSubstage().transition(state, None)

    from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
        KernelDebugSubstage,
    )
    stage = KernelDebugSubstage()
    ctx = stage._common_context(state)
    prompt = stage._build_prompt(ctx, 1)
    assert "上一个已完成 agent 的结论" in prompt
    assert "基线发现 3 个 op_plugin 层失败 case" in prompt
    assert "baseline" in prompt


def test_prompt_injection_bounded_to_previous_agent(tmp_path, repo):
    """注入只携带上一个 agent 的结论（不膨胀携带更早历史）；完整历史在文件里。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    # baseline 先跑，结论物化
    _write_baseline_result(state, cross_compare=[])
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _phase_path,
    )
    p = _phase_path(state, "baseline_result.json", round_suffix=False)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["conclusion"] = "基线结论：7 个 kernel 层失败。"
    p.write_text(json.dumps(data), encoding="utf-8")
    BaselineSubstage().transition(state, None)
    # op_plugin_debug 再跑，结论物化（成为"上一个 agent"）
    _write_a5_checkpoint(state)
    _write_op_plugin_result(
        state, debug_status="converged",
        conclusion="适配层结论：dtype 转换已修复。")
    OpPluginDebugSubstage().transition(state, None)

    # 下一个 agent（kernel_debug）prompt：只含 op_plugin_debug（last），不含 baseline
    from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
        KernelDebugSubstage,
    )
    stage = KernelDebugSubstage()
    ctx = stage._common_context(state)
    prompt = stage._build_prompt(ctx, 1)
    assert "适配层结论：dtype 转换已修复。" in prompt
    assert "基线结论：7 个 kernel 层失败。" not in prompt
    # 完整历史仍在文件里，agent 可从 conclusions_path 读取
    from ascendc_devkit.orchestration.stages.precision_debug_a5.conclusions import (
        _read_conclusions,
    )
    file_data = _read_conclusions(state)
    assert len(file_data["phases"]["baseline"]) == 1
    assert len(file_data["phases"]["op_plugin_debug"]) == 1
    assert file_data["last"]["phase"] == "op_plugin_debug"


# —— queue 按最新测量回写（max_diff_kl 不再冻结在 baseline）——————
# 注入的 current_case 块展示 queue 值；kernel_debug 修复后全量重测后必须回写，
# 否则修复后 agent 仍看到 baseline 冻结的大 diff（误导判定）。

def _write_a5_kernel_debug_result(state, **fields):
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _expected_round_result_path,
    )
    p = _expected_round_result_path(state, "kernel_debug_result.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    result = {"phase": "kernel_debug", "round": 1, "debug_status": "fixed"}
    result.update(fields)
    p.write_text(json.dumps(result), encoding="utf-8")
    return p


def _write_a5_kernel_debug_kl_result(state, *, kl_result, new_failed_cases=None,
                                     error_type="", **fields):
    """Write a kernel_debug fixed result carrying the full-KL summary (Step 7)."""
    return _write_a5_kernel_debug_result(
        state,
        debug_status="fixed",
        is_vf_issue=False,
        code_modified=True,
        kl_result=kl_result,
        new_failed_cases=new_failed_cases or [],
        error_type=error_type,
        verification={"after_max_diff_kl": 0.0},
        **fields,
    )


def _write_a5_kernel_debug_kl_summary(state, payload: dict) -> None:
    """Write the KL script's authoritative per_case summary JSON."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _debug_artifacts_dir,
    )
    kl_path = _debug_artifacts_dir(state) / "baseline" / "result_softmax_summary.json"
    kl_path.parent.mkdir(parents=True, exist_ok=True)
    kl_path.write_text(json.dumps(payload), encoding="utf-8")


def _write_a5_kernel_debug_checkpoint(state, queue, *, index=0, **overrides):
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    cp = {
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 0, "max_op_plugin_rounds": 10,
        "failed_case_queue": queue,
        "current_case_index": index,
    }
    cp.update(overrides)
    p.write_text(json.dumps(cp), encoding="utf-8")
    return p


def test_kernel_debug_writes_back_after_max_diff_kl(tmp_path, repo):
    """kernel_debug 重测后的 after_max_diff_kl 回写 queue[current].max_diff_kl。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_checkpoint(state)
    _write_a5_kernel_debug_result(
        state,
        verification={"after_max_diff_kl": 0.0009765625,
                      "before_max_diff_kl": 65506.017578125},
    )

    from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
        KernelDebugSubstage,
    )
    out = KernelDebugSubstage().transition(state, None)

    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    assert cp["failed_case_queue"][0]["max_diff_kl"] == 0.0009765625
    assert out._debug_checkpoint["debug_status"] == "fixed"


def test_kernel_debug_without_verification_keeps_queue_untouched(tmp_path, repo):
    """无 verification 字段（旧产物/未重测）→ 不回写，queue 保持原值。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_checkpoint(state)
    _write_a5_kernel_debug_result(state, debug_status="retry")  # 无 verification

    from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
        KernelDebugSubstage,
    )
    KernelDebugSubstage().transition(state, None)

    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    assert "max_diff_kl" not in cp["failed_case_queue"][0]


def test_kernel_debug_fixed_refreshes_queue_kl_diffs(tmp_path, repo):
    """kernel_debug fixed 后批跑全量 KL（原 regression 职责）：从 baseline/kl_result.json
    刷新全部 case 的 max_diff_kl。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _control_path
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_kernel_debug_checkpoint(state, [
        {"case_id": 1, "error_layer": "kernel", "status": "debugging",
         "attempt_count": 1, "max_diff_kl": 65506.017578125},
        {"case_id": 2, "error_layer": "kernel", "status": "pending",
         "attempt_count": 0, "max_diff_kl": 101.95899784},
    ])
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _debug_artifacts_dir,
    )
    kl_path = _debug_artifacts_dir(state) / "baseline" / "kl_result.json"
    kl_path.parent.mkdir(parents=True, exist_ok=True)
    kl_path.write_text(json.dumps({"all_results": [
        {"case_id": 1, "max_diff": 0.0009765625},
        {"case_id": 2, "max_diff": 999.0},
    ]}), encoding="utf-8")
    _write_a5_kernel_debug_kl_result(state, kl_result={
        "pass": 1, "total": 2, "max_diff": 999.0, "failed_cases": []})

    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage,
    )
    out = KernelDebugSubstage().transition(state, None)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    q = cp["failed_case_queue"]
    assert q[0]["max_diff_kl"] == 0.0009765625
    assert q[1]["max_diff_kl"] == 999.0
    assert KernelDebugSubstage().resolve_condition(out) == "case_kl_fails"


def test_kernel_debug_fixed_reconciles_kl_passing_cases_into_queue(tmp_path, repo):
    """fixed 后全量 KL 调和队列：最新 KL 全量中已通过的 kernel 层 case 标 resolved，
    max_diff_kl 刷新为真实测量值（不再用 baseline 冻结值误导调度）。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _control_path
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_kernel_debug_checkpoint(state, [
        {"case_id": 15, "error_layer": "kernel", "status": "debugging",
         "attempt_count": 1, "max_diff_kl": 3.0},
        {"case_id": 16, "error_layer": "kernel", "status": "pending",
         "attempt_count": 0, "max_diff_kl": 10.0},
        {"case_id": 18, "error_layer": "kernel", "status": "pending",
         "attempt_count": 0, "max_diff_kl": 127.0},
        {"case_id": 19, "error_layer": "kernel", "status": "pending",
         "attempt_count": 0, "max_diff_kl": 31.0},
    ])
    _write_a5_kernel_debug_kl_summary(state, {
        "pass": 2, "total": 4, "max_diff": 31.0,
        "per_case": [
            {"case_id": 15, "passed": True, "max_diff": 5.96e-08},
            {"case_id": 16, "passed": False, "max_diff": 10.0},
            {"case_id": 18, "passed": True, "max_diff": 2.98e-07},
            {"case_id": 19, "passed": False, "max_diff": 31.0},
        ],
    })
    _write_a5_kernel_debug_kl_result(state, kl_result={
        "pass": 2, "total": 4, "max_diff": 31.0, "failed_cases": []})

    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage,
    )
    stage = KernelDebugSubstage()
    out = stage.transition(state, None)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    q = cp["failed_case_queue"]
    # case 18 精度已通过 → 直接 resolved，max_diff_kl 刷新（不再显示 127.0）
    assert q[2]["case_id"] == 18
    assert q[2]["status"] == "resolved"
    assert q[2]["max_diff_kl"] == 2.98e-07
    # 当前 case（15）修复后 KL 通过 → 被调和标 resolved；仍失败的保持 pending
    assert q[0]["case_id"] == 15
    assert q[0]["status"] == "resolved"
    assert q[0]["attempt_count"] == 2   # kernel_debug 每轮 attempt_count++
    assert q[1]["status"] == "pending"
    assert q[3]["status"] == "pending"
    # kernel_debug 不推进 index——由 spawn 的 reconcile 跳过已 resolved case
    assert cp["current_case_index"] == 0
    # KL 有失败 → 回 kernel_debug 修下一个失败 case
    assert stage.resolve_condition(out) == "case_kl_fails"


def test_kernel_debug_fixed_marks_regressed_resolved_case_debugging(tmp_path, repo):
    """fixed 后全量 KL 从 KL 实测推导队列（与 baseline 同构）：队列中已 resolved 的 case
    本轮 KL 重新失败 → 标 debugging（regressed，改原条目，不新增副本）。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _control_path
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_kernel_debug_checkpoint(state, [
        {"case_id": 15, "error_layer": "kernel", "status": "debugging",
         "attempt_count": 1, "max_diff_kl": 3.0},
        {"case_id": 18, "error_layer": "kernel", "status": "resolved",
         "attempt_count": 0, "max_diff_kl": 2.98e-07},
    ])
    _write_a5_kernel_debug_kl_summary(state, {
        "pass": 1, "total": 2, "max_diff": 31.0,
        "per_case": [
            {"case_id": 15, "passed": True, "max_diff": 5.96e-08},
            {"case_id": 18, "passed": False, "max_diff": 31.0},
        ],
    })
    _write_a5_kernel_debug_kl_result(state, kl_result={
        "pass": 1, "total": 2, "max_diff": 31.0, "failed_cases": []})

    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage,
    )
    KernelDebugSubstage().transition(state, None)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    q = cp["failed_case_queue"]
    assert q[0]["case_id"] == 15
    assert q[0]["status"] == "resolved"   # 当前 case KL 通过
    assert q[1]["case_id"] == 18
    assert q[1]["status"] == "debugging"  # regressed：resolved → debugging
    assert len(q) == 2                     # 不新增重复副本


def test_kernel_debug_fixed_regressed_op_plugin_case_flips_to_kernel(tmp_path, repo):
    """regressed 的 op_plugin case 翻转为 kernel：KL 直测 kernel binary 失败 = kernel
    层证据（绕过适配层），不能让 kernel_debug 接到 error_layer=op_plugin 的误标 case。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _control_path
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_kernel_debug_checkpoint(state, [
        {"case_id": 15, "error_layer": "kernel", "status": "debugging",
         "attempt_count": 1, "max_diff_kl": 3.0},
        {"case_id": 18, "error_layer": "op_plugin", "status": "resolved",
         "attempt_count": 0, "max_diff_kl": 1e-7},
    ])
    _write_a5_kernel_debug_kl_summary(state, {
        "pass": 1, "total": 2, "max_diff": 31.0,
        "per_case": [
            {"case_id": 15, "passed": True, "max_diff": 5.96e-08},
            {"case_id": 18, "passed": False, "max_diff": 31.0},
        ],
    })
    _write_a5_kernel_debug_kl_result(state, kl_result={
        "pass": 1, "total": 2, "max_diff": 31.0, "failed_cases": []})

    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage,
    )
    KernelDebugSubstage().transition(state, None)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    q = cp["failed_case_queue"]
    assert q[1]["case_id"] == 18
    assert q[1]["status"] == "debugging"
    assert q[1]["error_layer"] == "kernel"  # KL 直测失败 → 证据指向 kernel 层


def test_kernel_debug_fixed_appends_kl_failed_new_case_to_queue(tmp_path, repo):
    """fixed 后全量 KL 从 KL 实测推导：KL 失败且不在队列的 case → 追加队尾 pending
    （error_layer=kernel、attempt_count=0），不再依赖 agent 手工 new_failed_cases。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _control_path
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_kernel_debug_checkpoint(state, [
        {"case_id": 15, "error_layer": "kernel", "status": "debugging",
         "attempt_count": 1, "max_diff_kl": 3.0},
    ])
    _write_a5_kernel_debug_kl_summary(state, {
        "pass": 1, "total": 2, "max_diff": 31.0,
        "per_case": [
            {"case_id": 15, "passed": True, "max_diff": 5.96e-08},
            {"case_id": 20, "passed": False, "max_diff": 31.0},
        ],
    })
    _write_a5_kernel_debug_kl_result(state, kl_result={
        "pass": 1, "total": 2, "max_diff": 31.0, "failed_cases": []})

    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage,
    )
    KernelDebugSubstage().transition(state, None)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    q = cp["failed_case_queue"]
    assert len(q) == 2
    assert q[0]["case_id"] == 15
    assert q[0]["status"] == "resolved"
    assert q[1]["case_id"] == 20
    assert q[1]["status"] == "pending"
    assert q[1]["error_layer"] == "kernel"
    assert q[1]["attempt_count"] == 0
    assert q[1]["max_diff_kl"] == 31.0


def test_kernel_debug_fixed_ignores_reported_new_failed_cases_when_kl_passes(
        tmp_path, repo):
    """fixed 后队列以 KL 实测为准：agent 报告的 new_failed_cases 若 KL 实测通过 →
    不入队（去重由 KL 真值保证，不复用 agent 手写 dict 追加）；KL 全过 → kl_all_pass。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _control_path
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_kernel_debug_checkpoint(state, [
        {"case_id": 15, "error_layer": "kernel", "status": "debugging",
         "attempt_count": 1, "max_diff_kl": 3.0},
    ])
    _write_a5_kernel_debug_kl_summary(state, {
        "pass": 2, "total": 2, "max_diff": 1e-7,
        "per_case": [
            {"case_id": 15, "passed": True, "max_diff": 5.96e-08},
            {"case_id": 18, "passed": True, "max_diff": 1e-7},
        ],
    })
    _write_a5_kernel_debug_kl_result(
        state, kl_result={"pass": 2, "total": 2, "max_diff": 1e-7, "failed_cases": []},
        # agent 误报 case 18 失败（KL 实测通过）——框架不得据此入队
        new_failed_cases=[{"case_id": 18, "error_layer": "kernel",
                           "status": "pending", "attempt_count": 0}])

    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage,
    )
    out = KernelDebugSubstage().transition(state, None)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    q = cp["failed_case_queue"]
    assert len(q) == 1            # 不入队 case 18
    assert q[0]["case_id"] == 15
    assert q[0]["status"] == "resolved"
    assert KernelDebugSubstage().resolve_condition(out) == "kl_all_pass"


def test_kernel_debug_spawn_skips_reconciled_passing_case(tmp_path, repo):
    """kernel_debug 调度前调和：current_case_index 指向的 case 已由最新 KL 确认
    通过 → 直接跳过（绝不派给调试 agent）。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path, _debug_artifacts_dir,
    )
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 0, "max_op_plugin_rounds": 10,
        "failed_case_queue": [
            {"case_id": 17, "error_layer": "kernel", "status": "pending",
             "attempt_count": 0, "max_diff_kl": 241.0},
            {"case_id": 18, "error_layer": "kernel", "status": "pending",
             "attempt_count": 0, "max_diff_kl": 127.0},
            {"case_id": 19, "error_layer": "kernel", "status": "pending",
             "attempt_count": 0, "max_diff_kl": 31.0},
        ],
        "current_case_index": 1,
    }), encoding="utf-8")
    kl_path = _debug_artifacts_dir(state) / "baseline" / "result_softmax_summary.json"
    kl_path.parent.mkdir(parents=True, exist_ok=True)
    kl_path.write_text(json.dumps({
        "pass": 1, "total": 3, "max_diff": 31.0,
        "per_case": [
            {"case_id": 17, "passed": False, "max_diff": 241.0},
            {"case_id": 18, "passed": True, "max_diff": 2.98e-07},
            {"case_id": 19, "passed": False, "max_diff": 31.0},
        ],
    }), encoding="utf-8")

    from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
        KernelDebugSubstage,
    )
    KernelDebugSubstage()._reconcile_queue_for_spawn(state)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    q = cp["failed_case_queue"]
    assert q[1]["status"] == "resolved"
    assert cp["current_case_index"] == 2   # 跳过已通过的 18，落到 19


def test_reconcile_queue_kl_ignores_op_plugin_cases():
    """op_plugin 层 case 即使 KL 通过也不标 resolved（RC 才是其验收工具）。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
        _reconcile_queue_from_kl,
    )
    cp = {"failed_case_queue": [
        {"case_id": "op", "error_layer": "op_plugin", "status": "pending"},
        {"case_id": "kernel", "error_layer": "kernel", "status": "pending"},
    ]}
    marked = _reconcile_queue_from_kl(cp, {
        "op": {"passed": True, "max_diff": 1e-7},
        "kernel": {"passed": True, "max_diff": 1e-7},
    })
    assert marked == 1
    assert cp["failed_case_queue"][0]["status"] == "pending"
    assert cp["failed_case_queue"][1]["status"] == "resolved"
    assert cp["failed_case_queue"][1]["max_diff_kl"] == 1e-7


def test_advance_past_resolved_skips_op_plugin_cases():
    """Q6 修订（kernel 优先）：per-case 阶段队列推进跳过 op_plugin case。

    kernel-first baseline 路由可能把 op_plugin case 留在同一队列；kernel_debug 等
    per-case 阶段只解 kernel 层，推进必须跳过 op_plugin case（其 kernel 在
    KernelLaunch 下已被证明正确），绝不把适配层 case 派给调试 agent。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
        _advance_past_resolved,
    )
    cp = {"current_case_index": 0, "failed_case_queue": [
        {"case_id": "op1", "error_layer": "op_plugin", "status": "pending"},
        {"case_id": "k1", "error_layer": "kernel", "status": "pending"},
        {"case_id": "op2", "error_layer": "op_plugin", "status": "pending"},
    ]}
    _advance_past_resolved(cp, skip_op_plugin=True)
    assert cp["current_case_index"] == 1  # 跳过 op1，落到 k1
    cp["current_case_index"] = 1
    cp["failed_case_queue"][1]["status"] = "resolved"
    _advance_past_resolved(cp, skip_op_plugin=True)
    assert cp["current_case_index"] == 3  # 跳过 k1(resolved)+op2 → len(queue)


def test_has_pending_debuggable_excludes_op_plugin_cases():
    """per-case stop-loss 的 more_cases 判定只数 kernel 层 pending case。

    剩余失败全为 op_plugin 层 → 不算有更多可解 case（回 baseline 重跑分流，
    不硬闯 op_plugin case）。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
        _has_pending_debuggable,
    )
    cp = {"failed_case_queue": [
        {"case_id": "op1", "error_layer": "op_plugin", "status": "pending"},
        {"case_id": "op2", "error_layer": "op_plugin", "status": "pending"},
    ]}
    assert _has_pending_debuggable(cp, skip_op_plugin=True) is False
    assert _has_pending_debuggable(cp) is True  # 不带 skip 时 op_plugin 也算


def test_kernel_debug_spawn_reconcile_skips_op_plugin_case(tmp_path, repo):
    """混合队列（op_plugin case 在队首）→ kernel_debug 调度前调和跳过它，
    current_case_index 落到第一个 kernel case。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 0, "max_op_plugin_rounds": 10,
        "failed_case_queue": [
            {"case_id": "op1", "error_layer": "op_plugin", "status": "pending",
             "attempt_count": 0, "max_diff_kl": 1e-7},
            {"case_id": "k1", "error_layer": "kernel", "status": "pending",
             "attempt_count": 0, "max_diff_kl": 241.0},
        ],
        "current_case_index": 0,
    }), encoding="utf-8")

    from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
        KernelDebugSubstage,
    )
    KernelDebugSubstage()._reconcile_queue_for_spawn(state)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    assert cp["failed_case_queue"][0]["status"] == "pending"  # op_plugin 原样保留
    assert cp["current_case_index"] == 1                     # 落到 kernel case


def test_per_case_kl_results_requires_full_list():
    """仅 failed_cases 子集不携带通过证据 → 不判 resolved（只刷新数值）。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.case_loop import (
        _per_case_kl_results, _case_diffs_from_kl_result,
    )
    data = {"failed_cases": [{"case_id": 1, "max_diff": 10.0}]}
    assert _per_case_kl_results(data) == {}
    assert _case_diffs_from_kl_result(data) == {"1": 10.0}
    data2 = {"per_case": [{"case_id": 1, "passed": True, "max_diff": 10.0}]}
    assert _per_case_kl_results(data2) == {"1": {"passed": True, "max_diff": 10.0}}


def test_baseline_reconciles_kl_passing_cases(tmp_path, repo):
    """baseline 构建队列后调和：最新 KL 已通过的 kernel 层 case 直接标 resolved，
    仍失败的保持 pending 进入 per-case 调试。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _debug_artifacts_dir,
    )
    kl_path = _debug_artifacts_dir(state) / "baseline" / "result_softmax_summary.json"
    kl_path.parent.mkdir(parents=True, exist_ok=True)
    kl_path.write_text(json.dumps({
        "pass": 1, "total": 2, "max_diff": 10.0,
        "per_case": [
            {"case_id": "1", "passed": True, "max_diff": 1e-7},
            {"case_id": "2", "passed": False, "max_diff": 10.0},
        ],
    }), encoding="utf-8")
    cases = [_case("1", rc_pass=False, kl_pass=False, error_layer="kernel"),
             _case("2", rc_pass=False, kl_pass=False, error_layer="kernel")]
    _write_baseline_result(state, cross_compare=cases)

    stage = BaselineSubstage()
    out = stage.transition(state, None)

    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    q = cp["failed_case_queue"]
    assert q[0]["case_id"] == "1"
    assert q[0]["status"] == "resolved"     # KL 已通过 → 不再调试
    assert q[0]["max_diff_kl"] == 1e-7
    assert q[1]["status"] == "pending"      # 仍失败 → 保留在队列
    assert stage.resolve_condition(out) == "has_kernel_failures"


# —— bug regression: 已 resolved 的 case 不得被 relabel 成 skipped ——————
# 2026-08-11 轨迹：旧流程 regression 用 `_advance_current_case` 无条件把当前 case
# 覆盖成 `skipped`，使已通过 case 被 failing_cases（pending/skipped）误计为仍失败。
# 现 kernel_debug（合入 regression 职责）不做 per-case 推进（index 由 spawn
# reconcile 推进），resolved 状态由框架 KL 调和标出并保持。

def test_kernel_debug_fixed_resolved_case_not_relabeled_skipped(tmp_path, repo):
    """KL 已通过的 case 由框架调和标 resolved 且保持（不得被覆盖成 skipped），
    failing_cases 只含真实失败 case。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _control_path
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_kernel_debug_checkpoint(state, [
        {"case_id": 15, "error_layer": "kernel", "status": "debugging",
         "attempt_count": 1, "max_diff_kl": 3.0},
        {"case_id": 16, "error_layer": "kernel", "status": "pending",
         "attempt_count": 0, "max_diff_kl": 10.0},
    ])
    _write_a5_kernel_debug_kl_summary(state, {
        "pass": 1, "total": 2, "max_diff": 10.0, "per_case": [
            {"case_id": 15, "passed": True, "max_diff": 0.0001},
            {"case_id": 16, "passed": False, "max_diff": 10.0},
        ]})
    _write_a5_kernel_debug_kl_result(state, kl_result={
        "pass": 1, "total": 2, "max_diff": 10.0, "failed_cases": []})

    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage,
    )
    out = KernelDebugSubstage().transition(state, None)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    q = cp["failed_case_queue"]
    assert q[0]["case_id"] == 15
    assert q[0]["status"] == "resolved"   # KL 通过 → 框架调和标 resolved，保持不被覆盖
    assert q[1]["status"] == "pending"    # KL 失败 → 保留待调试
    # kernel_debug 不推进 index（由 spawn reconcile 跳过已 resolved case）
    assert cp["current_case_index"] == 0
    assert out._debug_checkpoint["failing_cases"] == [16]  # 不含已通过 case 15


def test_kernel_debug_fixed_kl_all_pass_not_skipped(tmp_path, repo):
    """KL 全过（kl_all_pass）：框架调和把所有 pending/debugging kernel case 标
    resolved、failing_cases 清空，resolve kl_all_pass 回 baseline 验收；已通过 case
    保持 resolved（不被误标 skipped 导致假 failing）。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import _control_path
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_kernel_debug_checkpoint(state, [
        {"case_id": 15, "error_layer": "kernel", "status": "debugging",
         "attempt_count": 1, "max_diff_kl": 3.0},
        {"case_id": 16, "error_layer": "kernel", "status": "debugging",
         "attempt_count": 2, "max_diff_kl": 5.0},
    ])
    _write_a5_kernel_debug_kl_summary(state, {
        "pass": 2, "total": 2, "max_diff": 1e-7, "per_case": [
            {"case_id": 15, "passed": True, "max_diff": 1e-7},
            {"case_id": 16, "passed": True, "max_diff": 1e-7},
        ]})
    _write_a5_kernel_debug_kl_result(state, kl_result={
        "pass": 2, "total": 2, "max_diff": 1e-7, "failed_cases": []})

    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage,
    )
    out = KernelDebugSubstage().transition(state, None)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    q = cp["failed_case_queue"]
    assert all(c["status"] == "resolved" for c in q)
    assert out._debug_checkpoint["failing_cases"] == []
    assert KernelDebugSubstage().resolve_condition(out) == "kl_all_pass"


# —— bug regression: spawn 时调和的队列不得被 transition guard-restore 回滚 ——————
# 2026-08-11 轨迹：actions() 里 guard 在 _reconcile_queue_for_spawn 之前保存，
# transition 的 _restore_framework_routing_fields 从 guard 恢复 → 调和结果（标
# resolved + 推进 current_case_index）被回滚成预调和状态：agent 被告知处理的是
# reconcile 后的当前 case（如 17），transition 却按预调和索引落到已 pass 的 case 18。
# 修复后 guard 在 reconcile 之后保存，恢复时保留调和结果。

def test_kernel_debug_spawn_reconcile_survives_guard_restore(tmp_path, repo):
    """kernel_debug spawn 调和（跳过已 pass 的 case 18、推进 index 到 17）后，
    transition 的 guard-restore 不得把它回滚——guard 必须在 reconcile 之后保存。

    走真实 actions()（reconcile→guard→_common_context）→ transition 全链路，
    验证 agent 被告知的当前 case 与 transition 实际处理的 case 一致。
    """
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path, _debug_artifacts_dir, _expected_round_result_path,
    )
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "kernel_debug", "kernel_debug_round": 0,
        "max_op_plugin_rounds": 10,
        "failed_case_queue": [
            {"case_id": 18, "error_layer": "kernel", "status": "pending",
             "attempt_count": 0, "max_diff_kl": 127.0},
            {"case_id": 17, "error_layer": "kernel", "status": "pending",
             "attempt_count": 0, "max_diff_kl": 241.0},
            {"case_id": 19, "error_layer": "kernel", "status": "pending",
             "attempt_count": 0, "max_diff_kl": 31.0},
        ],
        "current_case_index": 0,
    }), encoding="utf-8")
    kl_path = _debug_artifacts_dir(state) / "baseline" / "result_softmax_summary.json"
    kl_path.parent.mkdir(parents=True, exist_ok=True)
    kl_path.write_text(json.dumps({"pass": 2, "total": 3, "max_diff": 31.0, "per_case": [
        {"case_id": 18, "passed": True, "max_diff": 2.98e-07},
        {"case_id": 17, "passed": False, "max_diff": 241.0},
        {"case_id": 19, "passed": False, "max_diff": 31.0},
    ]}), encoding="utf-8")

    from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
        KernelDebugSubstage,
    )
    kd = KernelDebugSubstage()

    # 真实 actions()：内部顺序为 reconcile → guard → _common_context
    actions = kd.actions(state, 1)
    assert len(actions) == 1
    ctx = actions[0].context
    assert ctx["current_case"]["case_id"] == 17  # 注入的是调和后的当前 case
    assert ctx["current_case_index"] == 1

    # guard 快照（transition 的恢复源）必须包含调和结果：index=1、case18=resolved
    guard_path = p.parent / ".framework_checkpoint_guard.json"
    guard = json.loads(guard_path.read_text(encoding="utf-8"))
    assert guard["current_case_index"] == 1
    assert guard["failed_case_queue"][0]["status"] == "resolved"

    # agent 完成并写 result → transition 按 guard 恢复后必须仍处理 case 17（index 1）
    r = _expected_round_result_path(state, "kernel_debug_result.json")
    r.parent.mkdir(parents=True, exist_ok=True)
    r.write_text(json.dumps({
        "phase": "kernel_debug", "debug_status": "fixed",
        "is_vf_issue": False, "code_modified": False,
        "verification": {"after_max_diff_kl": 1e-5},
    }), encoding="utf-8")
    out = kd.transition(state, None)

    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    assert cp["current_case_index"] == 1
    assert cp["failed_case_queue"][0]["status"] == "resolved"  # case18 不被回滚/重调
    assert cp["failed_case_queue"][1]["status"] == "debugging"  # case17 才是调试对象
    assert cp["failed_case_queue"][1]["attempt_count"] == 1


# —— transition table wiring (authoritative source) ————

def test_baseline_transition_table_wiring():
    assert _A5_TRANSITION_TABLE["baseline"] == {
        "all_pass": ("__escalate__:passed", "validation"),
        "has_op_plugin_failures": ("op_plugin_debug", "corrective"),
        "has_kernel_failures": ("kernel_debug", "corrective"),
        # baseline ran but produced no case data (empty cross_compare) →
        # soft-gate to exhausted, NOT a silent false-pass to passed.
        "no_case_data": ("__escalate__:exhausted", "validation"),
        "commit_failed": ("__escalate__:exhausted", "validation"),
        # agent 自报状态异常 → 重试该 agent。
        "retry": ("baseline", "corrective"),
        # STATUS=FAILED（ENV/OTH 硬失败）→ escalate，不重试。
        "hard_failed": ("__escalate__:exhausted", "validation"),
        "agent_aborted": ("baseline", "corrective"),
        "abort_exhausted": ("__escalate__:exhausted", "validation"),
    }
    # kernel_debug fixed 后由全量 KL 实测推导路由（regression 已合入）：全过 →
    # baseline 权威双跑验收；有失败 → 回 kernel_debug 修下一个失败 case。
    assert _A5_TRANSITION_TABLE["kernel_debug"]["kl_all_pass"] == ("baseline", "validation")
    assert _A5_TRANSITION_TABLE["kernel_debug"]["case_kl_fails"] == ("kernel_debug", "corrective")
    assert "regression" not in _A5_TRANSITION_TABLE
    # all_exhausted（队列全部 case 已处理、最后一个 exhausted）→ 回 baseline 做权威
    # 双跑验收，不再提前 escalate 杀流程（避免仍有 case 未通过精度时终止）。
    assert _A5_TRANSITION_TABLE["kernel_debug"]["all_exhausted"] == ("baseline", "validation")
    assert _A5_TRANSITION_TABLE["vf_test"]["all_exhausted"] == ("baseline", "validation")
    assert _A5_TRANSITION_TABLE["vector_error_debug"]["all_exhausted"] == (
        "baseline", "validation")
    assert _A5_TRANSITION_TABLE["op_plugin_debug"]["converged"] == ("baseline", "validation")


def test_kernel_debug_last_case_exhausted_routes_back_to_baseline(tmp_path, repo):
    """最后一个 case exhausted 后不再 escalate 杀流程，而是回 baseline 做权威双跑
    验收（2026-08-10 轨迹：case_20 最后一个 exhausted → 整个 A5 终止，14 个仍挂）。"""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    _write_a5_checkpoint(state, phase="kernel_debug",
                         failed_case_queue=[
                             {"case_id": "c1", "error_layer": "kernel",
                              "status": "pending", "attempt_count": 0},
                         ], current_case_index=0)
    _write_a5_kernel_debug_result(state, debug_status="exhausted")

    from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
        KernelDebugSubstage,
    )
    out = KernelDebugSubstage().transition(state, None)

    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    cp = json.loads(_control_path(state).read_text(encoding="utf-8"))
    assert cp["failed_case_queue"][0]["status"] == "skipped"
    # 队列无更多 pending case → all_exhausted，但路由目标是 baseline（权威验收）
    assert out._debug_checkpoint["_case_skipped"] is True
    assert KernelDebugSubstage().resolve_condition(out) == "all_exhausted"
    assert _A5_TRANSITION_TABLE["kernel_debug"]["all_exhausted"] == (
        "baseline", "validation")


def test_kernel_debug_exhausted_resolve_ignores_op_plugin_cases():
    """Q6 修订：agent 报 exhausted 但队列仅剩 op_plugin pending case →
    all_exhausted 回 baseline，不硬闯空队列 kernel_debug。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
        KernelDebugSubstage,
    )
    dc = _extract_a5_debug_checkpoint({
        "status": "in_progress", "phase": "kernel_debug",
        "failed_case_queue": [
            {"case_id": "op1", "error_layer": "op_plugin", "status": "pending"},
        ],
        "current_case_index": 1,
    })
    dc["debug_status"] = "exhausted"
    state = State.empty().with_updates(_debug_checkpoint=dc)
    assert KernelDebugSubstage().resolve_condition(state) == "all_exhausted"


def test_kernel_debug_exhausted_resolve_counts_kernel_cases():
    """Q6 修订：混合队列下 exhausted 的 more-cases 只数 kernel 层 pending case。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.kernel_debug import (
        KernelDebugSubstage,
    )
    dc = _extract_a5_debug_checkpoint({
        "status": "in_progress", "phase": "kernel_debug",
        "failed_case_queue": [
            {"case_id": "op1", "error_layer": "op_plugin", "status": "pending"},
            {"case_id": "k1", "error_layer": "kernel", "status": "pending"},
        ],
        "current_case_index": 1,
    })
    dc["debug_status"] = "exhausted"
    state = State.empty().with_updates(_debug_checkpoint=dc)
    assert KernelDebugSubstage().resolve_condition(state) == "case_exhausted"


# —— kernel_debug fixed 后路由：由框架从全量 KL 实测推导（kl_all_pass / case_kl_fails）——

@pytest.mark.parametrize("status", ["case_kl_fails", "kl_all_pass"])
def test_kernel_debug_fixed_resolve_kl_routing(status):
    """debug_status=fixed 时 resolve_condition 透传框架推导的 _kl_status。"""
    dc = _extract_a5_debug_checkpoint({
        "status": "in_progress", "phase": "kernel_debug",
        "failed_case_queue": [], "current_case_index": 0,
    })
    dc["debug_status"] = "fixed"
    dc["_kl_status"] = status
    state = State.empty().with_updates(_debug_checkpoint=dc)

    assert KernelDebugSubstage().resolve_condition(state) == status


def test_kernel_debug_fixed_missing_kl_status_defaults_case_kl_fails():
    """fixed 但 _kl_status 缺失（KL 实测未知）→ 保守回 case_kl_fails，不直通 baseline。"""
    dc = _extract_a5_debug_checkpoint({
        "status": "in_progress", "phase": "kernel_debug",
        "failed_case_queue": [], "current_case_index": 0,
    })
    dc["debug_status"] = "fixed"
    state = State.empty().with_updates(_debug_checkpoint=dc)

    assert KernelDebugSubstage().resolve_condition(state) == "case_kl_fails"


# —— abort annealing: no phase output → agent_aborted, never all_pass —————

def test_extract_carries_consecutive_aborts():
    dc = _extract_a5_debug_checkpoint({"status": "in_progress", "phase": "baseline",
                                       "consecutive_aborts": 2})
    assert dc["consecutive_aborts"] == 2


def test_baseline_abort_resolves_agent_aborted_not_all_pass(tmp_path, repo):
    """An aborted baseline spawn (no phase output) must route agent_aborted →
    self-loop, NOT fall through to all_pass (which would wrongly escalate passed)."""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    stage = BaselineSubstage()

    out = stage.transition(state, None)  # no baseline_result.json written

    assert out._debug_checkpoint["agent_aborted"] is True
    assert stage.resolve_condition(out) == "agent_aborted"


def test_baseline_abort_exhausted_after_threshold_consecutive(tmp_path, repo):
    from ascendc_devkit.orchestration.runtime_config import (
        precision_debug_a5_abort_exhaust_threshold,
    )
    threshold = precision_debug_a5_abort_exhaust_threshold()
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "baseline",
        "consecutive_aborts": threshold - 1,
    }), encoding="utf-8")
    stage = BaselineSubstage()

    out = stage.transition(state, None)

    assert out._debug_checkpoint["consecutive_aborts"] == threshold
    assert stage.resolve_condition(out) == "abort_exhausted"


def test_successful_baseline_spawn_resets_abort_streak(tmp_path, repo):
    """A normal spawn (result written) clears the streak and routes normally."""
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "baseline",
        "consecutive_aborts": 2,
    }), encoding="utf-8")
    cases = [_case("level2/softmax_1", rc_pass=False, kl_pass=False)]
    _write_baseline_result(state, cross_compare=cases)

    stage = BaselineSubstage()
    out = stage.transition(state, None)

    assert out._debug_checkpoint["consecutive_aborts"] == 0
    assert stage.resolve_condition(out) == "has_kernel_failures"


def test_a5_transition_table_has_abort_entries():
    for stage_name in ("baseline", "kernel_debug", "vf_test",
                       "vector_error_debug", "op_plugin_debug"):
        table = _A5_TRANSITION_TABLE[stage_name]
        assert table["agent_aborted"] == (stage_name, "corrective")
        assert table["abort_exhausted"] == ("__escalate__:exhausted", "validation")


# —— per-case abort → advance to next failed case (2026-08-11 轨迹) ——
#
# 回归：kernel_debug / vf_test / vector_error_debug 连续 abort 达阈值后必须
# 推进到下一个失败 case（走 case_exhausted → kernel_debug 处理下一个 case），
# 而不是自旋 agent_aborted 直到 graph_executor 的通用 stagnation 守卫把它
# 线性后继到语义错误的兄弟阶段（vf_test）—— 见 _abort_advances_case。

def test_kernel_debug_abort_below_threshold_keeps_same_case(tmp_path, repo):
    """连续 abort 未达阈值 → 仍停留当前 case，路由 agent_aborted（吸收瞬态 infra）。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "kernel_debug",
        "consecutive_aborts": 1,
        "current_case_index": 0,
        "failed_case_queue": [
            {"case_id": "c1", "status": "debugging", "attempt_count": 0},
            {"case_id": "c2", "status": "pending", "attempt_count": 0},
        ],
    }), encoding="utf-8")
    stage = KernelDebugSubstage()

    out = stage.transition(state, None)

    cp = _load_a5_checkpoint(state)
    assert out._debug_checkpoint["agent_aborted"] is True
    assert out._debug_checkpoint["consecutive_aborts"] == 2
    assert cp["current_case_index"] == 0  # 未达阈值，不推进
    assert stage.resolve_condition(out) == "agent_aborted"


def test_kernel_debug_abort_at_threshold_advances_next_failed_case(tmp_path, repo):
    """连续 abort 达阈值 → 当前 case skipped，推进到下一个失败 case（case_exhausted），
    不再落入 vf_test / 不再 escalate。"""
    from ascendc_devkit.orchestration.runtime_config import (
        precision_debug_a5_abort_exhaust_threshold,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    threshold = precision_debug_a5_abort_exhaust_threshold()
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "kernel_debug",
        "consecutive_aborts": threshold - 1,
        "current_case_index": 0,
        "failed_case_queue": [
            {"case_id": "c1", "status": "debugging", "attempt_count": 0},
            {"case_id": "c2", "status": "pending", "attempt_count": 0},
        ],
    }), encoding="utf-8")
    stage = KernelDebugSubstage()

    out = stage.transition(state, None)

    cp = _load_a5_checkpoint(state)
    assert out._debug_checkpoint["agent_aborted"] is True
    assert cp["current_case_index"] == 1            # 推进到下一个失败 case
    assert cp["failed_case_queue"][0]["status"] == "skipped"
    assert out._debug_checkpoint["_case_skipped"] is True
    assert out._debug_checkpoint["_more_cases"] is True
    assert stage.resolve_condition(out) == "case_exhausted"


def test_kernel_debug_abort_last_case_all_exhausted_to_baseline(tmp_path, repo):
    """最后一个失败 case 也 abort 达阈值 → all_exhausted → baseline 权威复验。"""
    from ascendc_devkit.orchestration.runtime_config import (
        precision_debug_a5_abort_exhaust_threshold,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        KernelDebugSubstage, _load_a5_checkpoint, _save_a5_checkpoint,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    threshold = precision_debug_a5_abort_exhaust_threshold()
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "kernel_debug",
        "consecutive_aborts": threshold - 1,
        "current_case_index": 0,
        "failed_case_queue": [
            {"case_id": "c1", "status": "debugging", "attempt_count": 0},
        ],
    }), encoding="utf-8")
    stage = KernelDebugSubstage()

    out = stage.transition(state, None)

    cp = _load_a5_checkpoint(state)
    assert cp["failed_case_queue"][0]["status"] == "skipped"
    assert cp["current_case_index"] == 1            # 越过队列末尾（len=1）
    assert out._debug_checkpoint["_case_skipped"] is True
    assert out._debug_checkpoint["_more_cases"] is False
    assert stage.resolve_condition(out) == "all_exhausted"


def test_non_per_case_baseline_abort_exhausted_still_escalates(tmp_path, repo):
    """非 per-case 阶段（baseline）abort 达阈值仍走 abort_exhausted → escalate，
    不因 per-case 推进逻辑而改变。"""
    from ascendc_devkit.orchestration.runtime_config import (
        precision_debug_a5_abort_exhaust_threshold,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    threshold = precision_debug_a5_abort_exhaust_threshold()
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "baseline",
        "consecutive_aborts": threshold - 1,
        "current_case_index": 0,
        "failed_case_queue": [
            {"case_id": "c1", "status": "debugging", "attempt_count": 0},
        ],
    }), encoding="utf-8")
    stage = BaselineSubstage()

    out = stage.transition(state, None)

    assert out._debug_checkpoint["agent_aborted"] is True
    assert out._debug_checkpoint.get("_case_skipped") is False
    assert stage.resolve_condition(out) == "abort_exhausted"


def test_vf_test_abort_at_threshold_advances_case(tmp_path, repo):
    """vf_test 同属 per-case：abort 达阈值 → 推进下一个失败 case（case_exhausted）。"""
    from ascendc_devkit.orchestration.runtime_config import (
        precision_debug_a5_abort_exhaust_threshold,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import (
        VfTestSubstage, _load_a5_checkpoint,
    )
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    threshold = precision_debug_a5_abort_exhaust_threshold()
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "vf_test",
        "consecutive_aborts": threshold - 1,
        "current_case_index": 0,
        "failed_case_queue": [
            {"case_id": "c1", "status": "debugging", "attempt_count": 0},
            {"case_id": "c2", "status": "pending", "attempt_count": 0},
        ],
    }), encoding="utf-8")
    stage = VfTestSubstage()

    out = stage.transition(state, None)

    cp = _load_a5_checkpoint(state)
    assert cp["current_case_index"] == 1
    assert cp["failed_case_queue"][0]["status"] == "skipped"
    assert stage.resolve_condition(out) == "case_exhausted"


# —— agent 自报 RETURN 状态解析与异常重试 ——

class _FakeAgentResult:
    def __init__(self, final_response):
        self.final_response = final_response


def _result_with_return(return_line: str) -> dict:
    return {"agent_result": _FakeAgentResult(return_line)}


def test_parse_agent_return_block_ok():
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        parse_agent_return_block,
    )
    ret = parse_agent_return_block(
        "## RETURN: status=COMPLETED, phase=kernel_debug, "
        "debug_status=fixed, code_modified=false"
    )
    assert ret["status"] == "COMPLETED"
    assert ret["phase"] == "KERNEL_DEBUG"
    assert ret["debug_status"] == "FIXED"


def test_parse_agent_return_block_chinese_fields_ok():
    """中文字段名（编排层宽容兜底）解析为正确的英文枚举值。

    历史实证回归：agent 把字段名意译成中文（`状态=COMPLETED`）后，ASCII status=
    缺失、`debug_status=fixed` 里的 status=fixed 子串被误读为状态 → 整轮废弃重派。
    现在中文 `状态=` 必须正确解析为 COMPLETED，且不得被子串误配污染。
    """
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        parse_agent_return_block,
    )
    ret = parse_agent_return_block(
        "## RETURN: 状态=COMPLETED, 阶段=kernel_debug, debug_status=fixed, "
        "code_modified=true, error_type="
    )
    assert ret["status"] == "COMPLETED"
    assert ret["phase"] == "KERNEL_DEBUG"
    assert ret["debug_status"] == "FIXED"


def test_parse_agent_return_block_english_not_substring_misread():
    """英文 `status=` 不得被子串误配：即使 `debug_status=` 出现在 `status=` 之前，
    status 也必须是 COMPLETED 而非 FIXED（\b 词边界隔离，左起匹配不会吞入
    *_status= 字段值）。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        parse_agent_return_block,
    )
    ret = parse_agent_return_block(
        "## RETURN: 阶段=kernel_debug, debug_status=fixed, "
        "status=COMPLETED"
    )
    assert ret["status"] == "COMPLETED"
    assert ret["debug_status"] == "FIXED"


def test_parse_agent_return_block_chinese_return_marker_heading_only():
    """中文 `## 返回:` 标题形式可触发解析；正文 prose 中的普通 `返回:` 不得误触发。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        parse_agent_return_block,
    )
    assert parse_agent_return_block(
        "## 返回: 状态=COMPLETED, 阶段=vf-test, vf状态=passed"
    )["status"] == "COMPLETED"
    assert parse_agent_return_block(
        "根据分析请返回: 无完成信号"
    ) == {}


def test_parse_agent_return_block_missing_returns_empty():
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        parse_agent_return_block,
    )
    assert parse_agent_return_block("done") == {}
    assert parse_agent_return_block("") == {}
    assert parse_agent_return_block(None) == {}


def test_validate_agent_return_missing_block_is_abnormal():
    """agent 没输出 RETURN 完成信号 → 判异常（要求重试），不留默认值兜底。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _STATUS_KEY_BY_PHASE,
    )
    stage = KernelDebugSubstage()
    ret = stage._validate_agent_return(
        _result_with_return("## KERNEL_DEBUG_RESULT\nstatus: FAILED"),
        {"debug_status": "fixed"})
    assert ret and ret.get("reason") == "missing_return_block"


def test_validate_agent_return_failed_is_hard_failed_not_retry():
    """STATUS=FAILED（ENV/OTH 硬失败）→ reason=hard_failed（编排层 escalate，
    不得转为 retry，否则硬失败会被错误地反复重试）。"""
    stage = KernelDebugSubstage()
    ret = stage._validate_agent_return(
        _result_with_return("## RETURN: status=FAILED, phase=kernel_debug, "
                            "error_type=ENV"),
        {"debug_status": "fixed"})
    assert ret and ret.get("reason") == "hard_failed"


def test_validate_agent_return_inp_is_input_gap_not_retry():
    """STATUS=FAILED, error_type=INP（框架输入/注入缺漏）→ reason=input_gap：
    仍 escalate（重试不修复缺字段），但留独立 reason 供诊断区分。"""
    stage = KernelDebugSubstage()
    ret = stage._validate_agent_return(
        _result_with_return("## RETURN: status=FAILED, phase=kernel_debug, "
                            "error_type=INP"),
        {"debug_status": "fixed"})
    assert ret and ret.get("reason") == "input_gap"


def test_agent_inp_routes_escalate_via_hard_failed_flag(tmp_path, repo):
    """agent 自报 STATUS=FAILED, error_type=INP → transition 注入
    agent_hard_failed（与 ENV/OTH 同出口）→ resolve_condition 路由 hard_failed。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 2,
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 1}],
    }), encoding="utf-8")
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _expected_round_result_path,
    )
    p = _expected_round_result_path(state, "kernel_debug_result.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "phase": "kernel_debug", "round": 3,
        "debug_status": "fixed",
    }), encoding="utf-8")

    stage = KernelDebugSubstage()
    out = stage.transition(state, _result_with_return(
        "## RETURN: status=FAILED, phase=kernel_debug, error_type=INP"))

    assert out._debug_checkpoint.get("agent_hard_failed")
    assert stage.resolve_condition(out) == "hard_failed"


def test_validate_agent_return_invalid_status_is_abnormal():
    """agent 上报值不在已知集合内（拼写错误/越界值）→ 判 invalid_status（重试）。"""
    stage = KernelDebugSubstage()
    ret = stage._validate_agent_return(
        _result_with_return("## RETURN: status=COMPLETED, phase=kernel_debug, "
                            "debug_status=all_good"),
        {"debug_status": "fixed"})
    assert ret and ret.get("reason") == "invalid_status"
    # result JSON 侧非法值同样判 invalid_status
    ret2 = stage._validate_agent_return(
        _result_with_return("## RETURN: status=COMPLETED, phase=kernel_debug, "
                            "debug_status=fixed"),
        {"debug_status": "kl_all_good"})
    assert ret2 and ret2.get("reason") == "invalid_status"


def test_agent_hard_failed_routes_escalate(tmp_path, repo):
    """agent 自报 STATUS=FAILED（ENV/OTH 硬失败）→ transition 注入
    agent_hard_failed → resolve_condition 路由 hard_failed → escalate。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 2,
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 1}],
    }), encoding="utf-8")
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _expected_round_result_path,
    )
    p = _expected_round_result_path(state, "kernel_debug_result.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "phase": "kernel_debug", "round": 3,
        "debug_status": "fixed",
    }), encoding="utf-8")

    stage = KernelDebugSubstage()
    out = stage.transition(state, _result_with_return(
        "## RETURN: status=FAILED, phase=kernel_debug, error_type=ENV"))

    assert out._debug_checkpoint.get("agent_hard_failed")
    assert not out._debug_checkpoint.get("agent_status_abnormal")
    assert stage.resolve_condition(out) == "hard_failed"
    assert _A5_TRANSITION_TABLE["kernel_debug"]["hard_failed"] == (
        "__escalate__:exhausted", "validation")


def test_validate_agent_return_unknown_status_is_abnormal():
    """非 COMPLETED 且非 FAILED 的未知 status → 判异常。"""
    stage = KernelDebugSubstage()
    ret = stage._validate_agent_return(
        _result_with_return("## RETURN: status=WAT, phase=kernel_debug, "
                            "error_type=ENV"),
        {"debug_status": "fixed"})
    assert ret and ret.get("reason") == "non_completed"


def test_validate_agent_return_phase_mismatch_is_abnormal():
    stage = KernelDebugSubstage()
    ret = stage._validate_agent_return(
        _result_with_return("## RETURN: status=COMPLETED, phase=vf_test, "
                            "vf_status=passed"),
        {"debug_status": "fixed"})
    assert ret and ret.get("reason") == "phase_mismatch"


def test_validate_agent_return_status_mismatch_is_abnormal():
    """自报状态与 result JSON 冲突 → 判异常。"""
    stage = KernelDebugSubstage()
    ret = stage._validate_agent_return(
        _result_with_return("## RETURN: status=COMPLETED, phase=kernel_debug, "
                            "debug_status=need_vf"),
        {"debug_status": "fixed"})
    assert ret and ret.get("reason") == "status_mismatch"


def test_validate_agent_return_ok_is_empty():
    stage = KernelDebugSubstage()
    ret = stage._validate_agent_return(
        _result_with_return("## RETURN: status=COMPLETED, phase=kernel_debug, "
                            "debug_status=fixed"),
        {"debug_status": "fixed"})
    assert ret == {}


def test_validate_agent_return_body_mentions_status_not_matched():
    """正文里无关的 status=/debug_status= 不得被宽松兜底误判为自报状态
    （无 RETURN 块 → 必须判 missing_return_block，而非误放行/误 mismatch）。"""
    stage = KernelDebugSubstage()
    ret = stage._validate_agent_return(
        _result_with_return(
            "analysis: we saw debug_status=fixed in a prior log, "
            "but current KL still fails"),
        {"debug_status": "fixed"})
    assert ret and ret.get("reason") == "missing_return_block"


def test_validate_agent_return_stub_no_final_response_is_lenient():
    """无 agent_result / 无 final_response（stub/老 backend）→ 不校验。"""
    stage = KernelDebugSubstage()
    assert stage._validate_agent_return({}, {"debug_status": "fixed"}) == {}
    assert stage._validate_agent_return(
        {"agent_result": _FakeAgentResult(None)},
        {"debug_status": "fixed"}) == {}


def test_validate_agent_return_vf_hyphen_phase_normalized():
    """vf-test 自报 phase=vf-test 与本阶段 vf_test 视为一致（归一化）。"""
    stage = VfTestSubstage()
    ret = stage._validate_agent_return(
        _result_with_return("## RETURN: status=COMPLETED, phase=vf-test, "
                            "vf_status=passed"),
        {"vf_status": "passed"})
    assert ret == {}


def test_kernel_debug_abnormal_return_routes_retry(tmp_path, repo):
    """agent 自报状态异常 → transition 注入 agent_status_abnormal →
    resolve_condition 路由 retry（重试该 agent），而非默认值静默通过。"""
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _control_path,
    )
    _, op_dir = repo
    state = _state(tmp_path, repo[0], op_dir)
    p = _control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "status": "in_progress", "phase": "kernel_debug",
        "kernel_debug_round": 2,
        "current_case_index": 0,
        "failed_case_queue": [{"case_id": "c1", "status": "debugging", "attempt_count": 1}],
    }), encoding="utf-8")
    from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
        _expected_round_result_path,
    )
    p = _expected_round_result_path(state, "kernel_debug_result.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "phase": "kernel_debug", "round": 3,
        "debug_status": "fixed",
    }), encoding="utf-8")

    stage = KernelDebugSubstage()
    # agent 最后回复没有 RETURN 完成信号 → 异常
    out = stage.transition(state, _result_with_return(
        "## KERNEL_DEBUG_RESULT\ndebug_status: fixed"))

    assert out._debug_checkpoint.get("agent_status_abnormal")
    assert stage.resolve_condition(out) == "retry"
    assert _A5_TRANSITION_TABLE["kernel_debug"]["retry"] == ("kernel_debug", "corrective")


# —— current-case injection: framework must tell per-case agents WHICH case ————

def _prompt_ctx(tmp_path, repo, op_dir, *, queue=None, index=0):
    """Craft the same ctx fields ``_common_context`` builds for the prompt,
    so ``_format_paths_block`` / ``_phase_prompt`` can be exercised in isolation."""
    _, op_dir_path = repo
    return {
        "debug_dir": str(tmp_path / "artifacts" / "precision_debug_a5"),
        "code_dir": str(op_dir_path),
        "op_name": "softmax",
        "golden": {"entry": "softmax", "input_type": "torch"},
        "phase_filename": "kernel_debug_result.json",
        "current_case": (queue or [None, None])[index],
        "current_case_index": index,
        "failed_case_queue": queue or [],
    }


def test_current_case_block_renders_injected_case(tmp_path, repo):
    """The prompt must carry the authoritative current case (case_id/shape/dtype),
    so kernel_debug agents verify the SAME case the framework routes."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import BaselineSubstage
    ctx = _prompt_ctx(tmp_path, repo, repo[1], queue=[
        {"case_id": "level2/softmax_1", "shape": [1024, 1024],
         "dtype": "float16", "error_layer": "kernel",
         "failure_type": "precision", "attempt_count": 2},
    ])
    block = BaselineSubstage()._format_current_case_block(ctx)
    assert "current_case.case_id" in block
    assert "level2/softmax_1" in block
    assert "float16" in block
    assert "attempt_count" in block


def test_current_case_block_empty_falls_back_to_checkpoint(tmp_path, repo):
    """When no queue exists yet (baseline first round), the block must not crash
    and must point the agent at checkpoint.json as the fallback source."""
    from ascendc_devkit.orchestration.stages.precision_debug_a5 import BaselineSubstage
    ctx = _prompt_ctx(tmp_path, repo, repo[1], queue=[], index=0)
    block = BaselineSubstage()._format_current_case_block(ctx)
    assert "checkpoint.json" in block
    assert "current_case_index" in block


def test_kernel_debug_prompt_injects_current_case(tmp_path, repo):
    """kernel_debug 是 per-case 调试阶段（修复后批跑全量 KL），prompt 必须注入
    "当前待处理 case"——agent 先解当前 case，fixed 后跑全量 KL。"""
    stage = KernelDebugSubstage()
    ctx = _prompt_ctx(tmp_path, repo, repo[1], queue=[
        {"case_id": "level2/softmax_1", "shape": [1024, 1024],
         "dtype": "float16", "error_layer": "kernel",
         "failure_type": "precision", "attempt_count": 1},
    ])
    prompt = stage._build_prompt(ctx, 3)
    assert "当前待处理 case" in prompt
    assert "current_case.case_id" in prompt


def test_op_plugin_debug_prompt_omits_current_case(tmp_path, repo):
    """op_plugin_debug 是全局适配层修复循环，不针对单个 case 解精度——prompt 不得注入
    "当前待处理 case"（current_case_index / case_id / shape / dtype / error_layer /
    failure_type / attempt_count / max_diff_rc / max_diff_kl）。max_diff_* 是动态回写值
    （kernel_debug 修复后全量重测、baseline 双跑更新），不是修复前的冻结值。"""
    stage = OpPluginDebugSubstage()
    ctx = _prompt_ctx(tmp_path, repo, repo[1], queue=[
        {"case_id": 2, "shape": [[64, 4, 4]], "dtype": ["float32"],
         "error_layer": "kernel", "failure_type": "precision",
         "attempt_count": 0, "max_diff_rc": 0.000293,
         "max_diff_kl": 0.0009210705757141113},
    ])
    prompt = stage._build_prompt(ctx, 1)
    assert "当前待处理 case" not in prompt
    assert "current_case_index" not in prompt
    assert "current_case.case_id" not in prompt
    assert "current_case.max_diff_rc" not in prompt
    assert "current_case.max_diff_kl" not in prompt
