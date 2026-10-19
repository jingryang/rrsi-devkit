"""step-100 — schema/build/artifact 反馈重派 resume 原 coder 会话（非全新 spawn）。

背景（docs/plan/codegen-schema-retry-session-resume/）：schema mismatch 等产物
不合格的定向重派原走 stage iteration 循环全新 spawn（turn 1 重计、重载 skill），
原会话 152 turns 的决策上下文被丢弃，修复动作实为改一处却重付 ~7.5min 冷启动。
跨 iteration 会话续接此前在框架中不存在。修复：transition 写回 coder session_id
进 State；feedback 重派轮 actions 构造 SpawnAgent 时带 resume_session_id +
简短 resume_prompt（原会话已有完整任务书，不重发全量 prompt）。

（step-112：锚点字段统一为 runner 捕获的 last_agent_session_id，旧
codegen_coder_session_id 删除——§2.5 捕获通路唯一。）

统一抽象（§1.15）：build_feedback（编译失败）/ artifact_feedback（manifest 缺
字段）/ schema feedback（scalar 契约）同属「coder 会话内可修的产物不合格带反馈
重派」——同一行为统一 resume，不逐类分支。
"""

from types import SimpleNamespace

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.codegen import CodegenStage


def _stage() -> CodegenStage:
    return CodegenStage()


SCHEMA_FB = {
    "kind": "scalar_contract",
    "reason": "scalar_access_contract",
    "violations": ["op_kernel/unique.h:291 无 reference/证据"],
    "hint": "三选一：向量化 / 补 reference / 补 deviation_evidence",
    "retry_count": 1,
}

BUILD_FB = {
    "kind": "compile",
    "error_class": "unknown",
    "log_path": "/tmp/build.log",
    "error_lines": ["op_host/foo.cpp:12 'X' does not name a type"],
}


class TestActionsResumeOnFeedback:
    def test_actions_fresh_spawn_first_round(self):
        """首轮（无 feedback）不带 resume——全新会话是正确语义。"""
        actions = _stage().actions(State(mode="new"), 1)
        assert len(actions) == 1
        assert actions[0].resume_session_id is None
        assert actions[0].resume_prompt is None

    def test_actions_resume_on_schema_feedback(self):
        """schema/build/artifact 反馈轮 + 有上轮 session → resume 原会话：
        resume_session_id 透传，resume_prompt 是简短反馈（非全量任务书）。"""
        state = State(
            mode="new",
            codegen_build_feedback=SCHEMA_FB,
            last_agent_session_id="ses_prev_round",
            last_agent_stage="codegen",
        )
        actions = _stage().actions(state, 2)
        assert len(actions) == 1
        assert actions[0].resume_session_id == "ses_prev_round"
        assert actions[0].resume_prompt
        # step-103：resume 消息携带 kind 专属反馈段（scalar-contract 段 +
        # violations 条目），与 fresh prompt 同一渲染（§1.15）
        assert "scalar-contract retry" in actions[0].resume_prompt
        assert "op_kernel/unique.h:291" in actions[0].resume_prompt

    def test_actions_resume_on_build_feedback(self):
        """build_feedback（编译失败）同属「会话内可修的产物不合格」——统一
        resume（§1.15 同一行为统一抽象，不逐 feedback 类型分支）。"""
        state = State(
            mode="new",
            codegen_build_feedback=BUILD_FB,
            last_agent_session_id="ses_prev_round",
            last_agent_stage="codegen",
        )
        actions = _stage().actions(state, 2)
        assert actions[0].resume_session_id == "ses_prev_round"
        assert actions[0].resume_prompt

    def test_actions_resume_on_artifact_feedback(self):
        state = State(
            mode="new",
            codegen_artifact_feedback={"missing_fields": ["callable_target"],
                                       "hint": "补 manifest 字段"},
            last_agent_session_id="ses_prev_round",
            last_agent_stage="codegen",
        )
        actions = _stage().actions(state, 2)
        assert actions[0].resume_session_id == "ses_prev_round"
        # missing_fields 摘录进 resume 消息（artifact 反馈的可执行载体）
        assert "callable_target" in actions[0].resume_prompt

    def test_actions_no_resume_without_session(self):
        """有 feedback 但无上轮 session（如旧 snapshot 恢复）→ fresh spawn
        兜底（backend 层另有 session-gone 自动降级，双保险）。"""
        state = State(mode="new", codegen_build_feedback=SCHEMA_FB)
        actions = _stage().actions(state, 2)
        assert actions[0].resume_session_id is None


class TestSessionAnchorUnified:
    """step-112 (§2.5)：会话锚点捕获上收 runner（last_agent_session_id，
    Runner.run_stage transition 后统一写入）——codegen 的 per-transition 回写
    已删。捕获语义（写入/空值不清空）锁定在 test_design_feedback_resume.py 的
    TestRunnerSessionCapture；此处锚定旧字段删净 + rerun 重置迁移。"""

    def test_legacy_field_gone(self):
        assert not hasattr(State(mode="new"), "codegen_coder_session_id")

    def test_rerun_resets_session_anchor(self):
        """rerun_reset_fields 含 last_agent_session_id——重跑 = 新会话。"""
        assert "last_agent_session_id" in _stage().rerun_reset_fields()


class TestAnchorOwnershipGuard:
    """M13（review 整改）：锚点归属校验——锚点是 runner 对所有 stage 统一
    捕获的单点字段，他 stage（smoke/perf）spawn 会覆盖它。stale 反馈 +
    外来锚点不得 resume（fresh 兜底），否则会把 coder 修复提示注入别
    agent 的会话。"""

    def test_foreign_anchor_falls_back_to_fresh(self):
        state = State(
            mode="new",
            codegen_build_feedback=SCHEMA_FB,
            last_agent_session_id="ses_smoke_round",
            last_agent_stage="smoke",  # 锚点属 smoke 的 spawn
        )
        actions = _stage().actions(state, 2)
        assert actions[0].resume_session_id is None
        assert actions[0].resume_prompt is None

    def test_rerun_reset_includes_anchor_stage(self):
        assert "last_agent_stage" in _stage().rerun_reset_fields()
