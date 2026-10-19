"""§abort (precision-debug-agent-abort) — agent-abort annealing UT.

Covers the recovered annealing logic that was lost from the worktree (git log -S
showed the symbols never committed):
- transition_table routing: every agent-spawning sub-stage declares
  ``agent_aborted`` (self-loop re-spawn, corrective) and ``abort_exhausted``
  (escalate the group).
- ``_resolve_abort_condition`` priority: abort_exhausted (≥ threshold) beats
  agent_aborted beats fall-through None.
- ``_bump_consecutive_aborts`` / ``_reset_consecutive_aborts`` disk round-trip.
- ``_agent_produced_output`` verdict: absent / corrupt / empty-shell → False;
  non-empty payload → True.
- ``_handle_abort`` (bump_counters=True for redeploy-heavy stages
  diagnose/printf/comment_bisect; False for light refine/scope).
  §merge: diagnose 融合 fix 后从 light 迁入 redeploy-heavy。
- RunTests own abort path (summary-absent) still bumps the counter + advances
  framework-owned rounds.
- anneal escalation: consecutive_aborts ≥ 2 → ``abort_exhausted`` → 非
  run_tests 阶段路由 run_tests 走主循环（§abort-relay，不直接退出组）；
  触发即清零（§abort-reset）。run_tests / scope_guard 保持 escalate。
- normal output resets the streak.
- ScopeGuard abort must NOT raise PrecisionDebugContractError (regression: the
  §abort guard precedes the verdict contract check).

UT uses mock control.json (no real LLM/NPU); the real agent loop is heavy_llm (§3.11).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.precision_debug_substages import (
    DiagnoseSubstage,
    RunTestsSubstage,
    _ABORT_EXHAUST_THRESHOLD,
    _PHASE_DEFAULTS,
    _phase_path,
)
from ascendc_devkit.orchestration.precision_debug_tree import (
    _PRECISION_DEBUG_TRANSITION_TABLE,
)


# —— self-contained helpers (mirror test_precision_debug_stage.py) ——————————

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


def _control(**overrides) -> dict:
    defaults = {
        "status": "running",
        "max_iterations": 30,
        "current_case_index": 0,
        # §step-119: 顶层 best_* 字段已删——最优/计数从 history 测量史现算派生。
        "failed_case_queue": [],
        "history": [],
        "phase_counter": 0,
        "run_iter_counter": 0,
    }
    defaults.update(overrides)
    return defaults


def _seed_phase(state: State, filename: str, summary: dict | None = None) -> Path:
    """Write a schema-valid round-suffixed phase JSON (non-aborted spawn)."""
    payload = dict(_PHASE_DEFAULTS.get(filename, {"any": "payload"}))
    if summary is not None:
        payload["_summary"] = summary
    p = _phase_path(state, filename, round_suffix=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# —— transition-table routing ————————————————————————————————————————

class TestTransitionTableAborts:
    """Every sub-stage that spawns an agent must declare both abort conditions:
    a transient abort self-loops (re-spawn), a persistent one escalates the group
    (so the loop can never spin forever on a dead agent).

    P3 减法: 只剩 run_tests/diagnose 两 phase。"""
    STAGES = ["run_tests", "diagnose"]
    # §abort-relay: 熔断路由——非 run_tests 阶段 abort 熔断后回 run_tests 走主循环
    # （run_tests→diagnose→run_tests），不直接退出组；触发时 consecutive_aborts
    # 清零（§abort-reset）从 0 重计，终止由 rounds/max_iterations + time budget 兜底。
    # run_tests 保持 escalate：自身熔断 = 测试环境死亡（回 run_tests 无意义）。
    RELAY_STAGES = ["diagnose"]
    ESCALATE_STAGES = ["run_tests"]

    @pytest.mark.parametrize("stage", STAGES)
    def test_agent_aborted_self_loop(self, stage):
        target, label = _PRECISION_DEBUG_TRANSITION_TABLE[stage]["agent_aborted"]
        assert target == stage, f"{stage}.agent_aborted must re-spawn itself"
        assert label == "corrective", f"{stage}.agent_aborted must burn quota"

    @pytest.mark.parametrize("stage", RELAY_STAGES)
    def test_abort_exhausted_relays_to_run_tests(self, stage):
        """熔断后回 run_tests（linear）重进主循环，不退出组；abort 是瞬态
        （agent 死亡/超时），熔断不代表调试失败，当前 best_commit 需回归验证。"""
        assert _PRECISION_DEBUG_TRANSITION_TABLE[stage]["abort_exhausted"] == (
            "run_tests", "linear")

    @pytest.mark.parametrize("stage", ESCALATE_STAGES)
    def test_abort_exhausted_escalates(self, stage):
        target, label = _PRECISION_DEBUG_TRANSITION_TABLE[stage]["abort_exhausted"]
        assert target == "__escalate__:exhausted"
        assert label == "validation"


# —— _resolve_abort_condition priority ————————————————————————————————

class TestResolveAbortCondition:
    """Priority: abort_exhausted (persistent, ≥ threshold) > agent_aborted
    (transient, this spawn) > None (fall through to normal routing)."""

    def test_escalation_wins_over_transient_at_threshold(self):
        s = DiagnoseSubstage()
        dc = {"consecutive_aborts": _ABORT_EXHAUST_THRESHOLD, "agent_aborted": True}
        # Both flags set → escalation must win (a persistent abort must not be
        # mistaken for a transient retry).
        assert s._resolve_abort_condition(dc) == "abort_exhausted"

    def test_escalation_above_threshold(self):
        s = DiagnoseSubstage()
        assert s._resolve_abort_condition({"consecutive_aborts": 99}) == "abort_exhausted"

    def test_transient_below_threshold(self):
        s = DiagnoseSubstage()
        dc = {"consecutive_aborts": _ABORT_EXHAUST_THRESHOLD - 1, "agent_aborted": True}
        assert s._resolve_abort_condition(dc) == "agent_aborted"

    def test_no_abort_falls_through(self):
        s = DiagnoseSubstage()
        assert s._resolve_abort_condition({"consecutive_aborts": 0}) is None
        assert s._resolve_abort_condition({}) is None


# —— counter disk round-trip ——————————————————————————————————————————

class TestConsecutiveAbortsCounter:
    def test_bump_increments_and_persists(self, tmp_path):
        state = _state(tmp_path)
        _write_control(state, _control(consecutive_aborts=0))
        s = DiagnoseSubstage()
        assert s._bump_consecutive_aborts(state) == 1
        assert s._bump_consecutive_aborts(state) == 2
        assert _read_control(state)["consecutive_aborts"] == 2

    def test_reset_clears_and_persists(self, tmp_path):
        state = _state(tmp_path)
        _write_control(state, _control(consecutive_aborts=2))
        s = DiagnoseSubstage()
        assert s._reset_consecutive_aborts(state) == 0
        assert _read_control(state)["consecutive_aborts"] == 0

    def test_reset_is_noop_when_already_zero(self, tmp_path):
        # Already 0 → no disk write needed (mtime must not change).
        state = _state(tmp_path)
        _write_control(state, _control(consecutive_aborts=0))
        s = DiagnoseSubstage()
        assert s._reset_consecutive_aborts(state) == 0


# —— _agent_produced_output verdict ————————————————————————————————————

class TestAgentProducedOutput:
    """The phase JSON is the agent's only durable proof of progress: absent /
    corrupt / empty-shell all mean the agent died before producing usable output."""
    def test_absent_file_is_false(self, tmp_path):
        assert DiagnoseSubstage()._agent_produced_output(_state(tmp_path)) is False

    def test_empty_shell_is_false(self, tmp_path):
        state = _state(tmp_path)
        s = DiagnoseSubstage()
        p = _phase_path(state, s._phase_filename(), round_suffix=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
        assert s._agent_produced_output(state) is False

    def test_corrupt_json_is_false(self, tmp_path):
        state = _state(tmp_path)
        s = DiagnoseSubstage()
        p = _phase_path(state, s._phase_filename(), round_suffix=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not valid json", encoding="utf-8")
        assert s._agent_produced_output(state) is False

    def test_nonempty_payload_is_true(self, tmp_path):
        state = _state(tmp_path)
        s = DiagnoseSubstage()
        p = _phase_path(state, s._phase_filename(), round_suffix=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"fix_code_log": "applied"}), encoding="utf-8")
        assert s._agent_produced_output(state) is True

    # §P6-FIX: latest-fallback branch
    def test_latest_fallback_true_and_auto_copies(self, tmp_path):
        """round-suffixed 缺失但 latest 有内容 → True，且自动 copy latest→round。"""
        state = _state(tmp_path)
        s = DiagnoseSubstage()
        p_round = _phase_path(state, s._phase_filename(), round_suffix=True)
        p_latest = _phase_path(state, s._phase_filename(), round_suffix=False)
        p_latest.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fix_code_log": "applied"}
        p_latest.write_text(json.dumps(payload), encoding="utf-8")
        assert not p_round.exists()
        assert s._agent_produced_output(state) is True
        # auto-repair: round-suffixed 应已被 copy 过来
        assert p_round.exists()
        assert json.loads(p_round.read_text()) == payload

    def test_latest_fallback_empty_is_false(self, tmp_path):
        """round-suffixed 缺失且 latest 也是 empty-shell → False。"""
        state = _state(tmp_path)
        s = DiagnoseSubstage()
        p_latest = _phase_path(state, s._phase_filename(), round_suffix=False)
        p_latest.parent.mkdir(parents=True, exist_ok=True)
        p_latest.write_text("{}", encoding="utf-8")
        assert s._agent_produced_output(state) is False

    def test_latest_fallback_corrupt_is_false(self, tmp_path):
        """round-suffixed 缺失且 latest JSON 损坏 → False。"""
        state = _state(tmp_path)
        s = DiagnoseSubstage()
        p_latest = _phase_path(state, s._phase_filename(), round_suffix=False)
        p_latest.parent.mkdir(parents=True, exist_ok=True)
        p_latest.write_text("{bad json", encoding="utf-8")
        assert s._agent_produced_output(state) is False


# —— _handle_abort: bump_counters distinguishes stage weight ———————————————

class TestHandleAbortCounters:
    """Redeploy-heavy stages (diagnose) still burn a budget slot on abort (an
    abort consumes a budget entry, just like a real spawn).

    §merge (docs/plan/fix-diagnose-merge): diagnose 融合 fix 后承担实施职责，
    abort 配额对齐原 FixSubstage（bump_counters=True）。P3 减法：corrective_cycles
    已删，budget slot 由 run_iter_counter 递增承载。"""

    def test_diagnose_abort_bumps_run_iter_counter(self, tmp_path):
        state = _state(tmp_path)
        _write_control(state, _control())
        fix = DiagnoseSubstage()
        assert fix._agent_produced_output(state) is False  # no phase JSON → abort
        out = fix.transition(state, {})
        cp = _read_control(state)
        assert cp["consecutive_aborts"] == 1
        assert cp["run_iter_counter"] == 1          # bump_counters=True
        assert fix.resolve_condition(out) == "agent_aborted"  # transient (< 2)


# —— RunTests own abort path ——————————————————————————————————————————

class TestRunTestsAbort:
    """RunTests detects abort via an absent ``_summary`` (its agent owns a richer
    path than the base ``_agent_produced_output``), but it too bumps the
    annealing counter and still advances framework-owned rounds."""

    def test_summary_absent_aborts_and_bumps(self, tmp_path):
        """§judgment-ownership (N1): abort 判据 = measure_result.returncode != 0
        （run-cases 非零退出）→ abort 路径。取代旧 phase-json-absent 判据（纯 Python
        无 agent 产物）。"""
        state = _state(tmp_path)
        _write_control(state, _control())
        run = RunTestsSubstage()
        out = run.transition(state, {"measure_result": {"returncode": 1}})  # 测量失败 → abort
        cp = _read_control(state)
        assert cp["consecutive_aborts"] == 1
        # framework-owned invariants advance even on abort (else stale rounds=0
        # can never exit via exhausted).
        assert out._debug_checkpoint["rounds"] == 1
        assert out._debug_checkpoint["agent_aborted"] is True
        assert run.resolve_condition(out) == "agent_aborted"

    def test_max_err_none_queue_with_summary_no_typeerror(self, tmp_path):
        """unique TypeError 根因回归：crash fallback 的 queue 条目 max_err=None
        （无数值结果），agent 在 abort 前已写完整 _summary → 走正常分支时
        best_* 计算不得 max([None, ...]) 抛 TypeError；None 须计入 crashed、
        排除出 real_errs。"""
        state = _state(tmp_path)
        _write_control(state, _control(failed_case_queue=[
            {"case_id": f"level3/unique_{i}", "shape": "1048576", "dtype": "",
             "status": "pending", "max_err": None, "failure_type": "runtime",
             "attempt_count": 0, "tried_fix_plan_ids": [], "last_fix_commit": None}
            for i in range(1, 3)
        ]))
        run = RunTestsSubstage()
        _seed_phase(state, run._phase_filename(), summary={
            "test_result": "2/2 runtime crash",
            "failed_count": 2, "total_count": 2, "max_err": None,
            "failure_type": "runtime", "last_run_log": "/tmp/run.log",
        })
        out = run.transition(state, {})  # 修复前：max([None, None]) TypeError
        cp = _read_control(state)
        # §step-119: cp 顶层不再有 best_* 字段——crashed 派生计进 history content，
        # 最优派生进 dc（_derive_best_metrics 取 history 测量史）。无 result.json →
        # total_count=0（total unknown，不虚报分母）。
        hist = cp["history"][-1]["content"]
        assert hist["crashed_count"] == 2          # None 计入 crashed，不抛 TypeError
        assert hist["max_err"] is None             # 排除出 real_errs
        assert hist["failed_count"] == 2
        assert hist["total_count"] == 0            # 无 result.json → total unknown
        dc = out._debug_checkpoint
        assert dc["best_crashed_count"] == 2
        assert dc["best_real_max_err"] is None
        assert dc["best_passed_count"] == 0        # total-failed 如实降级不虚高
        # 走正常分支（有 _summary），非 abort——abort 键只出现在 abort 路径
        assert dc.get("agent_aborted") is not True


# —— anneal escalation: ≥ threshold consecutive aborts ————————————————————

class TestAbortAnnealingEscalation:
    def test_threshold_is_two(self):
        """abort 熔断阈值 = 2（连续 2 次 spawn 无产出即触发）。"""
        assert _ABORT_EXHAUST_THRESHOLD == 2

    def test_threshold_abort_escalates(self, tmp_path):
        # Pre-seed the streak one below threshold; one more abort crosses it.
        state = _state(tmp_path)
        _write_control(state, _control(consecutive_aborts=_ABORT_EXHAUST_THRESHOLD - 1))
        diag = DiagnoseSubstage()
        out = diag.transition(state, {})  # no phase JSON → abort (the 2nd in a row)
        # §abort-reset: 熔断触发即清零（cp），下一轮从 0 重计；dc 保留触发值供判定。
        assert _read_control(state)["consecutive_aborts"] == 0
        # 熔断路由 abort_exhausted → 回 run_tests 走主循环（非直接退出组）。
        assert diag.resolve_condition(out) == "abort_exhausted"


# —— normal output resets the streak ————————————————————————————————————

class TestNormalOutputResetsStreak:
    def test_diagnose_normal_output_clears_counter(self, tmp_path):
        state = _state(tmp_path)
        _write_control(state, _control(consecutive_aborts=2))
        diag = DiagnoseSubstage()
        # Seed a valid phase JSON → normal (non-aborted) spawn → reset the streak.
        _seed_phase(state, diag._phase_filename())
        diag.transition(state, {})
        assert _read_control(state)["consecutive_aborts"] == 0


# —— ScopeGuard regression: abort must not trip the verdict contract —————————


# —— §weak-model B：diagnose abort 分流 + 定向提示 + 死线复活 ————————————

def _ar(status="ok", error_type=None, transcript=None, failure_reason=""):
    """假 AgentResult——transition 只读 error_type / metrics.failure_reason /
    transcript（getattr 容错，SimpleNamespace 足够）。"""
    from types import SimpleNamespace
    metrics = {"failure_reason": failure_reason} if failure_reason else {}
    return SimpleNamespace(status=status, error_type=error_type,
                           transcript=transcript, metrics=metrics)


def _fake_transcript(tmp_path, file_path, name="diag-1.jsonl"):
    """Write tool_use 证据 transcript（design 侧同款序列化格式）。"""
    p = tmp_path / name
    p.write_text(json.dumps({
        "ts": "t", "type": "AssistantMessage", "turn": 1,
        "blocks": [{"kind": "tool_use", "tool_name": "Write",
                    "tool_input": {"file_path": str(file_path),
                                   "content": "{}"}}]}) + "\n",
        encoding="utf-8")
    return p


class TestDiagnoseAbortWeakModel:
    """§weak-model B：产物缺失（非 infra）走 rounds 预算 + 定向提示（不进 3 次熔断
    ——「能解决尽量解决」）；infra 死亡才走 abort 退火熔断（fail-open 有界）。"""

    def test_infra_abort_no_user_feedback_bumps_annealing(self, tmp_path):
        """P93 分流：infra（网关/鉴权死）→ 不写 user_feedback（重试无意义，不教
        agent 修路径——design 侧真实事故教训）+ consecutive_aborts 熔断计数 + 拒因
        记 agent_infra + resolve=agent_aborted 自环 + transcript setter 复活。"""
        state = _state(tmp_path)
        _write_control(state, _control())
        tr = _fake_transcript(tmp_path, tmp_path / "stray.json")
        out = DiagnoseSubstage().transition(state, {"agent_result": _ar(
            error_type="infra", failure_reason="gateway 429", transcript=tr)})
        assert out.user_feedback == ""            # infra 不教修路径
        cp = _read_control(state)
        assert cp["consecutive_aborts"] == 1      # 熔断退火计数
        lrr = cp.get("last_reject_reason") or {}
        assert lrr.get("cond") == "agent_infra"
        assert "gateway 429" in str(lrr.get("detail"))
        assert DiagnoseSubstage().resolve_condition(out) == "agent_aborted"
        # 死线复活：transcript 挂上 state（control.json 孤儿恢复的证据源）
        assert str(out._last_agent_transcript) == str(tr)

    def test_missing_artifact_no_evidence_targeted_hint_rounds_budget(self, tmp_path):
        """非 infra 产物缺失（模型没写）→ 定向提示 + rounds 预算推进（不进熔断）
        + resolve=retry（对齐 design「iteration budget 为产物纠错而存在」）。"""
        state = _state(tmp_path)
        _write_control(state, _control(rounds=3, consecutive_aborts=0))
        out = DiagnoseSubstage().transition(state, {"agent_result": _ar()})
        assert out.user_feedback and "precision_diagnose.json" in out.user_feedback
        cp = _read_control(state)
        assert cp["consecutive_aborts"] == 0           # 不熔断（rounds 预算兜底）
        assert cp["rounds"] == 4                        # 正常轮推进
        assert (cp.get("last_reject_reason") or {}).get("cond") == "missing_artifact"
        assert DiagnoseSubstage().resolve_condition(out) == "retry"
        assert "aborted_no_product" in json.dumps(cp.get("history"))  # 可观测

    def test_orphan_relocated_zero_abort(self, tmp_path):
        """孤儿搬回零迭代自愈：agent 把 phase json 写到 wd 外（transcript 证据在）
        → recover_orphan_artifact 搬回 → 重判通过 → 走正常 transition（非 abort）。"""
        state = _state(tmp_path)
        _write_control(state, _control())
        stray = tmp_path / "stray_precision_diagnose.json"
        stray.write_text(json.dumps(
            {"diagnose_done": True, "fix_code_log": {}}), encoding="utf-8")
        tr = _fake_transcript(tmp_path, stray)
        out = DiagnoseSubstage().transition(state, {"agent_result": _ar(transcript=tr)})
        cp = _read_control(state)
        assert cp["consecutive_aborts"] == 0
        assert not (out._debug_checkpoint or {}).get("agent_aborted")
        assert DiagnoseSubstage().resolve_condition(out) != "agent_aborted"

    def test_normal_output_clears_user_feedback(self, tmp_path):
        """成功清错（对齐 design L1065 先例）：正常产出轮清 user_feedback——
        防残留旧提示误导后续轮。"""
        state = _state(tmp_path).with_updates(user_feedback="上轮：产物写错位置")
        _write_control(state, _control())
        _seed_phase(state, "precision_diagnose.json")
        out = DiagnoseSubstage().transition(state, {})
        assert out.user_feedback == ""
        assert _read_control(state).get("last_reject_reason") is None

    def test_prompt_renders_product_feedback(self, tmp_path):
        """「上次产物问题」段：ctx.product_feedback 注入 + prompt 渲染（弱模型
        定向提示的消费端）。"""
        s = DiagnoseSubstage()
        state = _state(tmp_path).with_updates(
            user_feedback="precision_diagnose.json 未在正确目录找到")
        ctx = s._common_context(state)
        assert ctx.get("product_feedback")
        prompt = s._phase_prompt(
            ctx, str(tmp_path), str(tmp_path / "ctrl"),
            str(tmp_path / "p.json"), str(tmp_path / "skill"), 1)
        assert "上次产物问题" in prompt
        assert "未在正确目录" in prompt
