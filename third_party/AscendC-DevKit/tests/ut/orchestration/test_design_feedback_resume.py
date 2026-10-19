"""step-112 (P14) — design substage feedback-redispatch session resume.

Locks the unified retry shape (§1.15, completing codegen step-100's unification
on the design side):

  - runner captures the stage's latest agent session id into
    ``last_agent_session_id`` (mechanical single point — session_id first
    appears at the spawn return; empty value never clears an existing anchor);
  - ``_DesignSubstage.actions`` resumes that session on feedback-redispatch
    rounds (own-stage product error + targeted feedback + anchor present);
    fresh spawn otherwise (no anchor / loopback shape / no feedback);
    infra errors keep the existing short-circuit (no actions at all);
  - rerun resets the anchor (rerun = new session, mirroring codegen's ruling);
  - codegen's legacy per-stage field is GONE (§2.5 — one capture pathway).
"""

from __future__ import annotations

import pytest

from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import ErrorFeedback, State
from ascendc_devkit.orchestration.stages.design_substages import TilingStage


# —— runner 捕获（机械单点）——

class _CapBackend(AgentBackend):
    def __init__(self, session_id: str = "ses_x"):
        self.session_id = session_id

    def spawn(self, agent_name, prompt, context, skills=None, **kw):
        return AgentResult(agent_name=agent_name, status="ok", artifacts={},
                           session_id=self.session_id)


class _CapStage(Stage):
    name = "cap"
    agent_name = "x"

    def input_contract(self):
        from ascendc_devkit.domain.contract import StageIOContract
        return StageIOContract(requires=[])

    def output_contract(self):
        from ascendc_devkit.domain.contract import StageIOContract
        return StageIOContract(provides=[])

    def actions(self, state, iteration: int = 1) -> list:
        return [SpawnAgent(agent_name="x", prompt="p", context={})]

    def transition(self, state, result):
        return state

    def is_satisfied(self, state) -> bool:
        return True


class TestRunnerSessionCapture:
    def test_captures_session_after_transition(self):
        out = Runner(agent_backend=_CapBackend("ses_x")).run_stage(
            State(mode="new", non_interactive=True), _CapStage())
        assert out.last_agent_session_id == "ses_x"

    def test_empty_session_keeps_existing_anchor(self):
        # backend 异常无 session_id → 不清空既有锚点（宁续旧勿丢）
        out = Runner(agent_backend=_CapBackend("")).run_stage(
            State(mode="new", non_interactive=True,
                  last_agent_session_id="ses_prev"), _CapStage())
        assert out.last_agent_session_id == "ses_prev"

    def test_codegen_legacy_field_deleted(self):
        # §2.5 删净：捕获通路唯一（runner），旧 per-stage 字段不复存在
        assert not hasattr(State(mode="new"), "codegen_coder_session_id")


# —— _DesignSubstage.actions resume 决策（语义单点）——

def _fb_state(tmp_path, *, stage_name="tiling", feedback="补 layout_contract",
              anchor="ses_1", error_type="incomplete_output",
              anchor_stage="tiling"):
    ws = type("W", (), {"artifacts": tmp_path})()
    kwargs = dict(non_interactive=True, _workspace=ws)
    if error_type is not None:
        kwargs["last_error"] = ErrorFeedback(
            stage_name=stage_name, error_type=error_type, message="产物未过")
    if feedback is not None:
        kwargs["user_feedback"] = feedback
    if anchor is not None:
        kwargs["last_agent_session_id"] = anchor
        # M13：锚点归属（runner 捕获时同记 stage 名）
        kwargs["last_agent_stage"] = anchor_stage
    return State.empty().with_updates(**kwargs)


class TestDesignActionsResume:
    def test_feedback_round_resumes_session(self, tmp_path):
        actions = TilingStage(template={"name": "T1"}).actions(
            _fb_state(tmp_path), iteration=2)
        sp = next(a for a in actions if isinstance(a, SpawnAgent))
        assert sp.resume_session_id == "ses_1"
        # resume 消息=首句（同一会话继续修复）+ 定向反馈全文（§1.14 不重发全量）
        assert "同一会话" in sp.resume_prompt
        assert "补 layout_contract" in sp.resume_prompt

    def test_no_anchor_fresh_fallback(self, tmp_path):
        actions = TilingStage(template={"name": "T1"}).actions(
            _fb_state(tmp_path, anchor=""), iteration=2)
        sp = next(a for a in actions if isinstance(a, SpawnAgent))
        assert sp.resume_session_id is None
        assert sp.resume_prompt is None

    def test_other_stage_error_fresh(self, tmp_path):
        # loopback 形态：错误属门/他阶段 → 条件不命中 → fresh（语义边界由
        # stage_name 承载，不新增机制）
        actions = TilingStage(template={"name": "T1"}).actions(
            _fb_state(tmp_path, stage_name="validate"), iteration=2)
        sp = next(a for a in actions if isinstance(a, SpawnAgent))
        assert sp.resume_session_id is None

    def test_no_feedback_fresh(self, tmp_path):
        actions = TilingStage(template={"name": "T1"}).actions(
            _fb_state(tmp_path, feedback=None), iteration=2)
        sp = next(a for a in actions if isinstance(a, SpawnAgent))
        assert sp.resume_session_id is None

    def test_first_round_fresh(self, tmp_path):
        # 首轮（无 last_error）零注入——fresh 是正确语义
        actions = TilingStage(template={"name": "T1"}).actions(
            _fb_state(tmp_path, error_type=None), iteration=1)
        sp = next(a for a in actions if isinstance(a, SpawnAgent))
        assert sp.resume_session_id is None

    def test_infra_error_short_circuits(self, tmp_path):
        # 既有短路不变：infra 不自愈，不 spawn（resume 决策根本不触及）
        actions = TilingStage(template={"name": "T1"}).actions(
            _fb_state(tmp_path, error_type="infra_transient"), iteration=2)
        assert actions == []


class TestRerunReset:
    def test_rerun_resets_session_anchor(self):
        fields = TilingStage(template={"name": "T1"}).rerun_reset_fields
        assert "last_agent_session_id" in fields


class TestResumePromptCarriesCurrentError:
    """M12（review 整改）：resume 轮并入**当前** last_error.message。

    可达序列（整改前）：轮1 F2 打回（feedback=补 layout_contract）→ 轮2 回填
    但引入 schema 违规（_error 只置 last_error 不清旧 feedback）→ 轮3 resume
    唯一新指令是过期反馈，真实 schema 错误文本全程不可达 agent。"""

    def test_stale_feedback_plus_new_error_both_visible(self, tmp_path):
        state = _fb_state(tmp_path)  # feedback="补 layout_contract"，error="产物未过"
        prompt = TilingStage(
            template={"name": "T1"})._render_retry_resume_prompt(state)
        assert "补 layout_contract" in prompt
        assert "当前阶段错误" in prompt and "产物未过" in prompt

    def test_error_equal_to_feedback_not_duplicated(self, tmp_path):
        # missing_artifact 形态 msg==feedback：同文不重复渲染
        state = State.empty().with_updates(
            non_interactive=True,
            last_error=ErrorFeedback(
                stage_name="tiling", error_type="missing_artifact", message="M"),
            user_feedback="M",
            last_agent_session_id="ses_1")
        prompt = TilingStage(
            template={"name": "T1"})._render_retry_resume_prompt(state)
        assert prompt.count("M") == 1
        assert "当前阶段错误" not in prompt


class TestAnchorOwnershipGuard:
    """M13（review 整改）：锚点归属——他 stage 的 spawn 覆盖锚点后，反馈
    重派不得 resume 外来会话（fresh 兜底）。"""

    def test_foreign_anchor_falls_back_to_fresh(self, tmp_path):
        actions = TilingStage(template={"name": "T1"}).actions(
            _fb_state(tmp_path, anchor_stage="smoke"), iteration=2)
        sp = next(a for a in actions if isinstance(a, SpawnAgent))
        assert sp.resume_session_id is None
        assert sp.resume_prompt is None

    def test_runner_capture_records_stage_name(self):
        # 捕获单点同记归属（M13）：session_id 与 stage 名成对落 State
        out = Runner(agent_backend=_CapBackend("ses_x")).run_stage(
            State(mode="new", non_interactive=True), _CapStage())
        assert out.last_agent_session_id == "ses_x"
        assert out.last_agent_stage == "cap"
