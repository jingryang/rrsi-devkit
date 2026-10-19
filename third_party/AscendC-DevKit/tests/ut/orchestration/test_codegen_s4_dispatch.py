"""Direct unit tests for codegen_s4.dispatch (the Stage 4 scheduler decision).

These exercise the real ``dispatch`` decision table — the previous tests only
patched ``dispatch_decision`` away, so a regression in COMPLETED/FAILED/
ROLLBACK branching would pass CI green.  The decision reads
``orchestration_plan.json`` (sub-stage status authority) and ``meta.json``
(retry budgets); both are constructed here per sub-case.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ascendc_devkit.orchestration.stages import codegen_s4


@pytest.fixture
def record_dir(tmp_path):
    """A record_dir with a default plan and an empty meta.json."""
    plan = {
        "sub_stages": [
            {"id": "4.0", "desc": "codegen 前置", "kind": "code",
             "checkpoint_group": "INDEPENDENT", "status": "pending",
             "deliverables": ["op_kernel/*.h"]},
            {"id": "4.A", "desc": "tiling", "kind": "code",
             "checkpoint_group": "HOST", "status": "pending",
             "deliverables": ["op_host/tiling.cpp"]},
            {"id": "4.B1", "desc": "host", "kind": "code",
             "checkpoint_group": "KERNEL", "status": "pending",
             "deliverables": ["op_kernel/kernel.cpp"]},
            {"id": "4.C.2.VT.0", "desc": "VF 验证", "kind": "vf",
             "checkpoint_group": "KERNEL", "status": "pending",
             "deliverables": []},
            {"id": "4.E", "desc": "api", "kind": "code",
             "checkpoint_group": "API", "status": "pending",
             "deliverables": ["op_api/aclnn.cpp"]},
            {"id": "4.F", "desc": "plugin", "kind": "code",
             "checkpoint_group": "LAST", "status": "pending",
             "deliverables": ["op_plugin/xxx_plugin.cpp"]},
        ]
    }
    (tmp_path / "orchestration_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "meta.json").write_text(
        json.dumps({"current_stage": 4, "retries": {}}),
        encoding="utf-8")
    return tmp_path


def _set_statuses(rd: Path, **statuses: str) -> None:
    plan = json.loads((rd / "orchestration_plan.json").read_text(encoding="utf-8"))
    for s in plan["sub_stages"]:
        if s["id"] in statuses:
            s["status"] = statuses[s["id"]]
    (rd / "orchestration_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8")


def _set_execution_groups(rd: Path, **groups: str) -> None:
    plan = json.loads((rd / "orchestration_plan.json").read_text(encoding="utf-8"))
    for step in plan["sub_stages"]:
        if step["id"] in groups:
            step["execution_group"] = groups[step["id"]]
    (rd / "orchestration_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8")


# ── execution group 解析 ───────────────────────────────────────────────

def test_resolve_execution_group_batches_contiguous_same_group(record_dir):
    _set_execution_groups(record_dir, **{
        "4.0": "host_tiling", "4.A": "host_tiling", "4.B1": "host_tiling",
        "4.C.2.VT.0": "vf_0", "4.E": "finalize", "4.F": "finalize",
    })

    assert codegen_s4.resolve_execution_group(str(record_dir), "4.0") == [
        "4.0", "4.A", "4.B1"]


def test_resolve_execution_group_vf_is_always_singleton(record_dir):
    _set_statuses(record_dir, **{"4.0": "done", "4.A": "done", "4.B1": "done"})
    _set_execution_groups(record_dir, **{
        "4.C.2.VT.0": "kernel", "4.E": "kernel", "4.F": "kernel",
    })

    assert codegen_s4.resolve_execution_group(
        str(record_dir), "4.C.2.VT.0") == ["4.C.2.VT.0"]


def test_resolve_execution_group_missing_field_degrades_to_singleton(record_dir):
    assert codegen_s4.resolve_execution_group(str(record_dir), "4.0") == ["4.0"]


# ── COMPLETED 分支 ─────────────────────────────────────────────────────

def test_dispatch_completed_finishes_all_done(record_dir):
    _set_statuses(record_dir, **{s: "done" for s in
                                 ("4.0", "4.A", "4.B1", "4.C.2.VT.0", "4.E", "4.F")})
    d = codegen_s4.dispatch(str(record_dir), "COMPLETED")
    assert d["action"] == "finish"
    assert d["next_sub_stage"] == "DONE"


def test_dispatch_completed_advances_to_next_pending(record_dir):
    # dispatch 语义：agent 报 COMPLETED = 当前第一个 pending sub-stage 已完成，
    # 框架标它 done 并路由到下一个 pending。全部 pending 时消费 4.0 → 返回 4.A。
    d = codegen_s4.dispatch(str(record_dir), "COMPLETED")
    assert d["action"] == "call_s4"
    assert d["next_sub_stage"] == "4.A"
    plan = json.loads((record_dir / "orchestration_plan.json").read_text(encoding="utf-8"))
    assert next(s for s in plan["sub_stages"] if s["id"] == "4.0")["status"] == "done"


def test_dispatch_completed_clears_last_error_md(record_dir):
    """COMPLETED 提交 = 待修问题已解决 → 清除 last_error.md（防陈旧注入后续 group）。"""
    (record_dir / "last_error.md").write_text("boom", encoding="utf-8")
    d = codegen_s4.dispatch(str(record_dir), "COMPLETED")
    assert d["action"] == "call_s4"
    assert not (record_dir / "last_error.md").exists()


def test_dispatch_failed_keeps_last_error_md(record_dir):
    """FAILED 不改提交状态：待修问题未解决，last_error.md 必须保留供重试轮读取。"""
    (record_dir / "last_error.md").write_text("boom", encoding="utf-8")
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="CK")
    assert d["action"] == "retry_s4"
    assert (record_dir / "last_error.md").read_text(encoding="utf-8") == "boom"


def test_dispatch_completed_routes_vf_step_to_vf_test(record_dir):
    # 消费完 4.B1 后，下一个 pending 是 VF 步骤 4.C.2.VT.0 → call_vf_test。
    _set_statuses(record_dir, **{"4.0": "done", "4.A": "done"})
    d = codegen_s4.dispatch(str(record_dir), "COMPLETED")
    assert d["action"] == "call_vf_test"
    assert d["next_sub_stage"] == "4.C.2.VT.0"


def test_dispatch_completed_commits_full_execution_group(record_dir):
    _set_execution_groups(record_dir, **{
        "4.0": "host_tiling", "4.A": "host_tiling", "4.B1": "host_tiling",
    })
    completed = ["4.0", "4.A", "4.B1"]

    d = codegen_s4.dispatch(
        str(record_dir), "COMPLETED", completed_sub_stages=completed)

    assert d["action"] == "call_vf_test"
    assert d["next_sub_stage"] == "4.C.2.VT.0"
    plan = json.loads((record_dir / "orchestration_plan.json").read_text())
    statuses = {step["id"]: step["status"] for step in plan["sub_stages"]}
    assert [statuses[sid] for sid in completed] == ["done", "done", "done"]


# ── PARTIAL 分支 ───────────────────────────────────────────────────────

def test_dispatch_completed_accepts_lowercase_plan_ids(record_dir):
    """小写 plan ID（4.D.api/4.D.plugin）上报后应规范化到 plan 权威 ID 并提交。

    回归：agent 正确上报 plan 里的小写 ID，但解析器 .upper() 后与 plan 精确
    比对失败 → 4.D 段永远无法标记 done。现在校验器大小写不敏感 + 规范化回
    plan ID，dispatch 应提交并推进到下一 sub-stage。
    """
    plan = json.loads((record_dir / "orchestration_plan.json").read_text())
    plan["sub_stages"] = [
        {"id": "4.D.api", "kind": "code", "checkpoint_group": "API",
         "status": "pending", "deliverables": []},
        {"id": "4.D.plugin", "kind": "code", "checkpoint_group": "API",
         "status": "pending", "deliverables": []},
        {"id": "4.E", "kind": "code", "checkpoint_group": "LAST",
         "status": "pending", "deliverables": []},
    ]
    (record_dir / "orchestration_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    _set_execution_groups(record_dir, **{
        "4.D.api": "api_plugin", "4.D.plugin": "api_plugin"})

    d = codegen_s4.dispatch(
        str(record_dir), "COMPLETED",
        completed_sub_stages=["4.D.api", "4.D.plugin"])

    assert d["action"] == "call_s4"
    assert d["next_sub_stage"] == "4.E"
    plan = json.loads((record_dir / "orchestration_plan.json").read_text())
    statuses = {step["id"]: step["status"] for step in plan["sub_stages"]}
    assert statuses["4.D.api"] == statuses["4.D.plugin"] == "done"
    assert statuses["4.E"] == "pending"


def test_dispatch_completed_accepts_case_insensitive_reported_ids(record_dir):
    """agent 以不同大小写上报（4.A vs 4.a）也应通过并规范化到 plan ID。"""
    _set_execution_groups(record_dir, **{
        "4.0": "host_tiling", "4.A": "host_tiling", "4.B1": "host_tiling",
    })

    d = codegen_s4.dispatch(
        str(record_dir), "COMPLETED",
        completed_sub_stages=["4.0", "4.a", "4.b1"])

    assert d["action"] == "call_vf_test"
    assert d["next_sub_stage"] == "4.C.2.VT.0"
    plan = json.loads((record_dir / "orchestration_plan.json").read_text())
    statuses = {step["id"]: step["status"] for step in plan["sub_stages"]}
    assert statuses["4.0"] == statuses["4.A"] == statuses["4.B1"] == "done"


def test_dispatch_partial_continues_next_pending(record_dir):
    _set_statuses(record_dir, **{"4.0": "done"})
    d = codegen_s4.dispatch(str(record_dir), "PARTIAL")
    assert d["action"] == "call_s4"
    assert d["next_sub_stage"] == "4.A"


def test_dispatch_partial_all_done_finishes(record_dir):
    _set_statuses(record_dir, **{s: "done" for s in
                                 ("4.0", "4.A", "4.B1", "4.C.2.VT.0", "4.E", "4.F")})
    d = codegen_s4.dispatch(str(record_dir), "PARTIAL")
    assert d["action"] == "finish"


def test_dispatch_partial_commits_only_contiguous_completed_prefix(record_dir):
    _set_execution_groups(record_dir, **{
        "4.0": "host_tiling", "4.A": "host_tiling", "4.B1": "host_tiling",
    })

    d = codegen_s4.dispatch(
        str(record_dir), "PARTIAL", completed_sub_stages=["4.0", "4.A"],
        failed_sub_stage="4.B1")

    assert d["action"] == "call_s4"
    assert d["next_sub_stage"] == "4.B1"
    plan = json.loads((record_dir / "orchestration_plan.json").read_text())
    statuses = {step["id"]: step["status"] for step in plan["sub_stages"]}
    assert statuses["4.0"] == statuses["4.A"] == "done"
    assert statuses["4.B1"] == "pending"


def test_dispatch_rejects_non_prefix_completion_without_advancing(record_dir):
    _set_execution_groups(record_dir, **{
        "4.0": "host_tiling", "4.A": "host_tiling", "4.B1": "host_tiling",
    })

    d = codegen_s4.dispatch(
        str(record_dir), "COMPLETED", completed_sub_stages=["4.0", "4.B1"])

    assert d["action"] == "paused"
    assert "completed_sub_stages" in d["pause_reason"]
    plan = json.loads((record_dir / "orchestration_plan.json").read_text())
    assert all(step["status"] == "pending" for step in plan["sub_stages"])


# ── FAILED 分支（retry 预算 / vf_exhausted / paused）──────────────────

def test_dispatch_failed_retry_within_budget(record_dir):
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="CK")
    assert d["action"] == "retry_s4"
    assert d["next_sub_stage"] == "4.0"
    assert d["error_type"] == "CK"


def test_dispatch_failed_commits_prefix_and_retries_failed_step(record_dir):
    _set_execution_groups(record_dir, **{
        "4.0": "host_tiling", "4.A": "host_tiling", "4.B1": "host_tiling",
    })

    d = codegen_s4.dispatch(
        str(record_dir), "FAILED", error_type="CK",
        completed_sub_stages=["4.0", "4.A"], failed_sub_stage="4.B1")

    assert d["action"] == "retry_s4"
    assert d["next_sub_stage"] == "4.B1"


def test_dispatch_failed_vf_step_calls_vf_test_retry(record_dir):
    _set_statuses(record_dir, **{"4.0": "done", "4.A": "done", "4.B1": "done"})
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="CK-VF")
    assert d["action"] == "call_vf_test"
    assert d["next_sub_stage"] == "4.C.2.VT.0"


def test_dispatch_failed_selfcheck_exhausted_rolls_back(record_dir):
    """某子阶段自检计数耗尽（retry_count=8）→ rollback_s4（确定性升级）。"""
    _set_step_retry_count(record_dir, "4.0", 8)
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="CK")
    assert d["action"] == "rollback_s4"


def _set_step_retry_count(rd, sid, n):
    """Set one sub-stage's failure retry count in the plan fixture."""
    plan = json.loads((rd / "orchestration_plan.json").read_text(
        encoding="utf-8"))
    for s in plan["sub_stages"]:
        if s["id"] == sid:
            s["retry_count"] = n
            break
    (rd / "orchestration_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8")


def _step_retry_count(rd, sid):
    plan = json.loads((rd / "orchestration_plan.json").read_text(
        encoding="utf-8"))
    for s in plan["sub_stages"]:
        if s["id"] == sid:
            return s.get("retry_count", 0)
    return 0


def test_dispatch_failed_bumps_substage_counter(record_dir):
    """s4 FAILED(CK) 递增**失败子阶段**的重试计数（per-substage，§6 编排层计数）。

    回归：log_softmax 批 4.C.6 连续 FAILED 32 次但重试计数恒 0 —— s4 串行 FAILED
    路径只读不写，升级门失效。
    """
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="CK")
    assert d["action"] == "retry_s4"  # 未超限
    assert _step_retry_count(record_dir, "4.0") == 1  # 当前失败子阶段（first pending）


def test_dispatch_failed_bumps_until_rollback(record_dir):
    """同一子阶段连续 FAILED(CK) 8 次 → 第 8 次 used=8 → rollback_s4（回退 s2）。"""
    for _ in range(7):
        d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="CK")
        assert d["action"] == "retry_s4"
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="CK")
    assert d["action"] == "rollback_s4"
    assert _step_retry_count(record_dir, "4.0") == 8


def test_dispatch_failed_env_does_not_bump(record_dir):
    """环境错误恒 pause，不递增任何计数器。"""
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="ENV")
    assert d["action"] == "paused"
    assert _step_retry_count(record_dir, "4.0") == 0


def test_dispatch_failed_vf_bumps_vf_substage(record_dir):
    """s4 VF 步骤 FAILED(CK-VF) 递增**该 VF 子阶段**的重试计数。"""
    _set_statuses(record_dir, **{"4.0": "done", "4.A": "done", "4.B1": "done"})
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="CK-VF")
    assert d["action"] == "call_vf_test"  # 未超限
    assert _step_retry_count(record_dir, "4.C.2.VT.0") == 1


def test_dispatch_failed_counts_isolated_per_substage(record_dir):
    """失败计数按 sub_stage 隔离：4.B1 的失败不消耗 4.A 的预算。"""
    _set_statuses(record_dir, **{"4.0": "done", "4.A": "done"})
    _set_step_retry_count(record_dir, "4.B1", 7)
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="CK")
    assert d["action"] == "rollback_s4"  # 4.B1 used=8 ≥ limit 8
    assert _step_retry_count(record_dir, "4.B1") == 8
    # 其他子阶段不受本次失败影响（per-substage 隔离）
    assert _step_retry_count(record_dir, "4.A") == 0


def test_dispatch_failed_env_always_pauses(record_dir):
    """环境错误恒 paused（人工修复环境，不回退）。"""
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="ENV")
    assert d["action"] == "paused"
    assert "env" in d["pause_reason"]


def test_dispatch_failed_vf_retry_exhausted(record_dir):
    _set_statuses(record_dir, **{"4.0": "done", "4.A": "done", "4.B1": "done"})
    _set_step_retry_count(record_dir, "4.C.2.VT.0", 4)
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="CK-VF")
    assert d["action"] == "vf_exhausted"
    assert d["exhausted_sub_stage"] == "4.C.2.VT.0"


def test_dispatch_failed_compile_retry_exhausted_rolls_back(record_dir):
    """某子阶段编译错误计数耗尽（retry_count=24）→ rollback_s4 回退 s2。"""
    _set_step_retry_count(record_dir, "4.0", 24)
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="C-SYM")
    assert d["action"] == "rollback_s4"


def test_dispatch_failed_env_error_always_pauses(record_dir):
    d = codegen_s4.dispatch(str(record_dir), "FAILED", error_type="ENV")
    assert d["action"] == "paused"
    assert "env error always pauses" in d["pause_reason"]


# ── ROLLBACK 分支 ──────────────────────────────────────────────────────

def test_dispatch_rollback_intra_stage_retries_target(record_dir):
    d = codegen_s4.dispatch(str(record_dir), "ROLLBACK",
                            rollback_target="4.B1")
    assert d["action"] == "retry_s4"
    assert d["next_sub_stage"] == "4.B1"


def test_dispatch_rollback_vf_target_calls_vf_test(record_dir):
    d = codegen_s4.dispatch(str(record_dir), "ROLLBACK",
                            rollback_target="4.C.2.VT.0")
    assert d["action"] == "call_vf_test"
    assert d["next_sub_stage"] == "4.C.2.VT.0"


def test_dispatch_rollback_cross_stage(record_dir):
    d = codegen_s4.dispatch(str(record_dir), "ROLLBACK",
                            rollback_target="Stage 3")
    assert d["action"] == "rollback_stage"
    assert d["rollback_target"] == "Stage 3"


def test_dispatch_rollback_no_target_uses_last_pending(record_dir):
    d = codegen_s4.dispatch(str(record_dir), "ROLLBACK")
    # No explicit target → falls back to the last pending sub-stage.
    assert d["action"] == "retry_s4"
    assert d["next_sub_stage"] == "4.F"


# ── 其它分支 ───────────────────────────────────────────────────────────

def test_dispatch_needs_agent(record_dir):
    d = codegen_s4.dispatch(str(record_dir), "NEEDS_AGENT",
                            agent_name="some-agent")
    assert d["action"] == "call_agent"
    assert d["agent_name"] == "some-agent"


def test_dispatch_paused(record_dir):
    d = codegen_s4.dispatch(str(record_dir), "PAUSED")
    assert d["action"] == "paused"
    assert "PAUSED" in d["pause_reason"]


def test_dispatch_unknown_status_pauses(record_dir):
    d = codegen_s4.dispatch(str(record_dir), "BOGUS")
    assert d["action"] == "paused"
    assert "unknown status" in d["pause_reason"]


def test_dispatch_error_detail_writes_last_error_md(record_dir):
    codegen_s4.dispatch(str(record_dir), "FAILED", error_type="CK",
                        error_detail="boom: cast failed")
    md = record_dir / "last_error.md"
    assert md.exists()
    assert "boom: cast failed" in md.read_text(encoding="utf-8")


# ── 其它公共 API 冒烟 ──────────────────────────────────────────────────

# ── parse_return_signal：RETURN / VF_TEST_RESULT 块 ───────────────────────

def test_parse_return_signal_standard_return_block():
    text = ("所有 sub-stage 已完成。\n"
            "## RETURN: status=COMPLETED, next_stage=4, next_sub_stage=4.F")
    assert codegen_s4.parse_return_signal(text) == {
        "status": "COMPLETED", "next_sub_stage": "4.F"}


def test_parse_return_signal_chinese_fields_ok():
    """中文字段名（编排层宽容兜底）解析为正确的英文枚举值。

    与 A5 precision_debug_a5.base.parse_agent_return_block 同源：agent 把字段名
    意译成中文（`状态=` / `错误类型=`）时仍能正确解析，且 `status=` 不得被子串
    误配（`failed_sub_stage=` 等 *_stage= 值不得污染 status）。
    """
    text = ("## RETURN: 状态=FAILED, 错误类型=CK-VF, 下一子阶段=4.A, "
            "失败子阶段=4.B1, completed_sub_stages=[4.0, 4.A]")
    assert codegen_s4.parse_return_signal(text) == {
        "status": "FAILED",
        "error_type": "CK-VF",
        "next_sub_stage": "4.A",
        "failed_sub_stage": "4.B1",
        "completed_sub_stages": ["4.0", "4.A"],
    }


def test_parse_return_signal_completed_sub_stages_and_failed_stage():
    text = (
        "## RETURN: status=FAILED, error_type=CK, next_sub_stage=4.B1, "
        "completed_sub_stages=[4.0, 4.A], failed_sub_stage=4.B1")
    assert codegen_s4.parse_return_signal(text) == {
        "status": "FAILED",
        "error_type": "CK",
        "next_sub_stage": "4.B1",
        "completed_sub_stages": ["4.0", "4.A"],
        "failed_sub_stage": "4.B1",
    }


def test_parse_return_signal_preserves_lowercase_sub_stage_ids():
    """小写 sub-stage ID（如 4.D.api）必须原样保留，不得被 .upper() 改写。

    回归：解析器曾对 completed_sub_stages 无条件 .upper()，把 plan 里合法的小写
    ID（4.D.api→4.D.API）改写成与 plan 精确比对永远不匹配 → 4.D 段校验死循环。
    """
    text = (
        "## RETURN: status=COMPLETED, next_sub_stage=4.E, "
        "completed_sub_stages=[4.D.api, 4.D.plugin]")
    assert codegen_s4.parse_return_signal(text) == {
        "status": "COMPLETED",
        "next_sub_stage": "4.E",
        "completed_sub_stages": ["4.D.api", "4.D.plugin"],
    }


def test_parse_return_signal_failed_with_error_type():
    text = "## RETURN: status=FAILED, error_type=CK-VF, next_sub_stage=4.A"
    assert codegen_s4.parse_return_signal(text) == {
        "status": "FAILED", "error_type": "CK-VF", "next_sub_stage": "4.A"}


def test_parse_return_signal_vf_test_result_block_only():
    """ascendc-vf-test-agent 只输出 regbase-vf-test skill 的 VF_TEST_RESULT 块
    （漏写自己的 RETURN 块）时，仍能识别出 FAILED + error_type。"""
    text = ("## VF_TEST_RESULT\n"
            "status: FAILED\n"
            "error_type: PREC\n"
            "error_info: |\n"
            "  ReduceSum 数值错误\n"
            "output_paths:\n"
            "  - vf_verified/kernel_test/vf_reduce_update_test/...")
    assert codegen_s4.parse_return_signal(text) == {
        "status": "FAILED", "error_type": "PREC"}


def test_parse_return_signal_vf_test_result_completed():
    text = ("## VF_TEST_RESULT\n"
            "status: COMPLETED\n"
            "output_paths:\n"
            "  - vf_verified/kernel_test/vf_reduce_update_test/...")
    assert codegen_s4.parse_return_signal(text) == {"status": "COMPLETED"}


def test_parse_return_signal_prefers_return_over_vf_result():
    """两者并存时 RETURN 块优先（编排契约主信号），VF_TEST_RESULT 作兜底。"""
    text = ("## VF_TEST_RESULT\n"
            "status: FAILED\n"
            "error_type: PREC\n"
            "## RETURN: status=COMPLETED, next_sub_stage=4.C.3\n")
    assert codegen_s4.parse_return_signal(text) == {
        "status": "COMPLETED", "next_sub_stage": "4.C.3"}


def test_parse_return_signal_ignores_prose_vf_result_mention():
    """正文里普通提及 VF_TEST_RESULT（无紧随的 status 行）不得触发解析。"""
    text = ("VF_TEST_RESULT 是 skill 的返回块，没有紧随的 status 行。"
            "这里全是普通叙述，没有机器可读信号。")
    assert codegen_s4.parse_return_signal(text) == {}


def test_parse_return_signal_ignores_prose_status_mention():
    """正文里碰巧出现 status=COMPLETED（无 RETURN/VF_TEST_RESULT 块）不得触发解析
    ——否则「无 RETURN 块 → FAILED」防线被架空（2026-08-06 VT.0 失败无重试根因的
    对偶防线）。与 A5 parse_agent_return_block 严格语义一致。"""
    text = ("我们分析了一下，日志里显示上次运行 status=COMPLETED 的结论，"
            "但本次没有机器可读的完成信号。")
    assert codegen_s4.parse_return_signal(text) == {}


def test_resolve_sub_stage_first_enter_vs_retry(record_dir):
    assert codegen_s4.resolve_sub_stage(str(record_dir), "first_enter") == "4.0"
    _set_statuses(record_dir, **{"4.0": "done", "4.A": "done", "4.B1": "done"})
    # retry 取最后一个 pending；continue/first_enter 取第一个 pending。
    assert codegen_s4.resolve_sub_stage(str(record_dir), "retry") == "4.F"
    assert codegen_s4.resolve_sub_stage(str(record_dir), "continue") == "4.C.2.VT.0"


def test_pending_ids_skips_missing_id_without_crash():
    """坏 plan 的 sub_stage 缺 id（s2 校验门已删，消费端兜底）→ 跳过不崩溃
    （旧实现 `s["id"]` 直接 KeyError）。"""
    plan = {"sub_stages": [
        {"kind": "code", "checkpoint_group": "INDEPENDENT",
         "deliverables": [], "status": "pending"},   # 缺 id
        {"id": "4.A", "kind": "code", "checkpoint_group": "HOST",
         "deliverables": [], "status": "pending"},
        "garbage",                                     # 非对象
        {"id": 123, "kind": "code", "checkpoint_group": "KERNEL",
         "deliverables": [], "status": "pending"},   # id 非 str
    ]}
    assert codegen_s4._pending_ids(plan) == ["4.A"]


def test_resolve_sub_stage_all_broken_returns_done(tmp_path):
    """全部 sub_stage 结构异常 → resolve 不崩溃，返回 DONE（消费端宽容兜底）。"""
    rd = tmp_path / "rec"
    rd.mkdir()
    (rd / "orchestration_plan.json").write_text(json.dumps({
        "sub_stages": [
            {"kind": "code", "checkpoint_group": "INDEPENDENT",
             "deliverables": [], "status": "pending"},
            "garbage",
        ]}), encoding="utf-8")
    assert codegen_s4.resolve_sub_stage(str(rd), "first_enter") == "DONE"


def test_is_vf_step_falls_back_to_regex_on_kind_mismatch(tmp_path):
    """.VT. 步骤在 plan 内 kind 漏标/误标 code → 回退正则识别（防静默错路由到
    普通编码 agent；s2 校验门已删，此处为消费端兜底）。"""
    rd = tmp_path / "rec"
    rd.mkdir()
    (rd / "orchestration_plan.json").write_text(json.dumps({
        "sub_stages": [
            {"id": "4.C.3.VT.0", "kind": "code", "checkpoint_group": "KERNEL",
             "deliverables": [], "status": "pending"},
            {"id": "4.D", "kind": "code", "checkpoint_group": "API",
             "deliverables": [], "status": "pending"},
        ]}), encoding="utf-8")
    assert codegen_s4._is_vf_step(str(rd), "4.C.3.VT.0") is True
    assert codegen_s4._is_vf_step(str(rd), "4.D") is False


def test_check_gate_ready_only_when_all_terminal(record_dir):
    _set_statuses(record_dir, **{s: "done" for s in
                                 ("4.0", "4.A", "4.B1", "4.C.2.VT.0", "4.E", "4.F")})
    assert codegen_s4.check_gate(str(record_dir)) == "READY"


def test_check_gate_not_ready_with_pending(record_dir):
    assert codegen_s4.check_gate(str(record_dir)).startswith("NOT_READY: ")


def test_set_status_marks_exhausted_and_regenerates_progress(record_dir):
    assert codegen_s4.set_status(str(record_dir), "4.C.2.VT.0", "exhausted") is True
    plan = json.loads((record_dir / "orchestration_plan.json").read_text(encoding="utf-8"))
    vf = next(s for s in plan["sub_stages"] if s["id"] == "4.C.2.VT.0")
    assert vf["status"] == "exhausted"
    progress = (record_dir / "progress.md")
    assert progress.exists()
    assert "4.C.2.VT.0" in progress.read_text(encoding="utf-8")
    assert codegen_s4.set_status(str(record_dir), "nope", "done") is False
