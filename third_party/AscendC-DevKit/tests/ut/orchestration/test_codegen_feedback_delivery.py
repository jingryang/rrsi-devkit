"""step-103 — codegen 反馈投递单点化 + context 死键删除。

L1 勘误后的真实事实（docs/plan/codegen-feedback-dead-channel/）：fresh 路径的
build_feedback / artifact_feedback **一直有** prompt 侧 kind 专属反馈段（阶段3
方案 Z 建的，此前 L1 误判为被 B5 删除——误判源于 grep 范围截断了 prompt builder
函数体）；真实缺口是 (a) `context[...]` 注入是死通道（backend 零消费），
(b) step-100 的 resume_prompt 通用摘要丢失 kind 专属上下文。

拍板（L3 方案 a 精化版）：
- kind 专属段提取为 `_render_build_feedback_section` / `_render_artifact_
  feedback_section`（§1.15 单点），fresh prompt 反馈段与 resume 消息共用同一
  渲染——两条投递路径内容严格一致；
- context 死键全删（§2.5，mode 同为死键一并删）。
"""

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.codegen import CodegenStage


def _stage() -> CodegenStage:
    return CodegenStage()


SCHEMA_FB = {
    "kind": "scalar_contract",
    "reason": "scalar_access_contract",
    "violations": ["op_kernel/foo.h:291 无 reference/证据"],
    "hint": "三选一：向量化 / 补 reference / 补 deviation_evidence",
    "retry_count": 1,
}

COMPILE_FB = {
    "kind": "compile",
    "error_class": "C-API",
    "log_path": "/r/build.log",
    "stderr_tail": "no matching function",
    "retry_count": 1,
}


class TestFreshPromptFeedbackSection:
    def test_fresh_prompt_carries_kind_section(self):
        """fresh prompt 反馈段经提取后的渲染函数注入（既有行为保持：
        kind 专属上下文 + 修复指引进 prompt）。"""
        state = State(mode="new", codegen_build_feedback=SCHEMA_FB)
        prompt = _stage()._build_codegen_prompt(state, 2)
        assert "scalar-contract retry" in prompt
        assert "foo.h:291" in prompt
        assert "三选一" in prompt

    def test_fresh_prompt_compile_branch(self):
        state = State(mode="new", codegen_build_feedback=COMPILE_FB)
        prompt = _stage()._build_codegen_prompt(state, 2)
        assert "C-API" in prompt
        assert "/r/build.log" in prompt
        assert "不要自己运行 build" in prompt

    def test_compile_branch_injects_structured_first_error(self):
        """2026-09-10：结构化首错注入——error_lines 直接进反馈文本，
        agent 不读日志也能看到根错误（silent-cut 轮只 thinking 不读文件）。"""
        fb = dict(COMPILE_FB)
        fb["error_lines"] = [
            "/home/x/transpose_infershape.cpp:40  "
            "'TypedContinuousVector' does not name a type",
            "/home/x/transpose_tiling.cpp:69  "
            "'TypedContinuousVector' does not name a type",
        ]
        state = State(mode="new", codegen_build_feedback=fb)
        prompt = _stage()._build_codegen_prompt(state, 2)
        assert "首错误（框架从编译日志结构化提取）" in prompt
        assert "TypedContinuousVector" in prompt
        assert "transpose_infershape.cpp:40" in prompt

    def test_compile_branch_without_error_lines_unchanged(self):
        """无 error_lines（日志读不到/无 clang 行）→ 不渲染首错误段，也不渲染
        stderr 尾巴摘要（截断残影已删）——完整信息在 log_path，agent 需要时 Read。"""
        state = State(mode="new", codegen_build_feedback=COMPILE_FB)
        prompt = _stage()._build_codegen_prompt(state, 2)
        assert "首错误（框架从编译日志结构化提取）" not in prompt
        assert "stderr 摘要" not in prompt
        assert "/r/build.log" in prompt  # 完整日志指针仍在

    def test_compile_branch_log_path_still_readable(self):
        """删 stderr 摘要后，log_path 指针必须保留——agent 需要全量信息时 Read。"""
        state = State(mode="new", codegen_build_feedback=COMPILE_FB)
        prompt = _stage()._build_codegen_prompt(state, 2)
        assert "读此文件" in prompt

    def test_fresh_prompt_artifact_feedback(self):
        state = State(mode="new", codegen_artifact_feedback={
            "missing_fields": ["callable_target"], "hint": "补 manifest 字段"})
        prompt = _stage()._build_codegen_prompt(state, 2)
        assert "callable_target" in prompt

    def test_fresh_prompt_without_feedback_untouched(self):
        """首轮（无 feedback）无反馈段——不误伤正常交付。"""
        prompt = _stage()._build_codegen_prompt(State(mode="new"), 1)
        assert "框架 build-retry" not in prompt
        assert "框架 artifact-retry" not in prompt


class TestSingleSourceRendering:
    def test_resume_and_fresh_share_kind_section(self):
        """§1.15 单点守护：同一 feedback → fresh prompt 的反馈段与 resume
        消息的反馈体是**同一段文本**（同一渲染函数产出，无两套拼装）。"""
        state = State(
            mode="new", codegen_build_feedback=SCHEMA_FB,
            last_agent_session_id="ses_prev",
            last_agent_stage="codegen")
        actions = _stage().actions(state, 2)
        section = _stage()._render_build_feedback_section(SCHEMA_FB, "<run_dir>")
        assert section in actions[0].prompt          # fresh 路径
        assert section in actions[0].resume_prompt   # resume 路径
        # resume 场景首句分离（两场景语义相反，不共用整文案）
        assert "同一会话" in actions[0].resume_prompt
        assert "同一会话" not in section

    def test_resume_artifact_feedback_shares_section(self):
        state = State(
            mode="new",
            codegen_artifact_feedback={"missing_fields": ["callable_target"],
                                       "hint": "补 manifest 字段"},
            last_agent_session_id="ses_prev",
            last_agent_stage="codegen")
        actions = _stage().actions(state, 2)
        section = _stage()._render_artifact_feedback_section(
            state.codegen_artifact_feedback)
        assert section in actions[0].prompt
        assert section in actions[0].resume_prompt


class TestDeadContextKeysRemoved:
    def test_actions_context_has_no_dead_keys(self):
        """§2.5：context 死键全删——SpawnAgent.context 不再携带任何
        「看似注入实为死代码」的键（backend 零消费）。"""
        state = State(
            mode="new", codegen_build_feedback=SCHEMA_FB,
            last_agent_session_id="ses_prev",
            last_agent_stage="codegen")
        actions = _stage().actions(state, 2)
        ctx = actions[0].context or {}
        for dead in ("build_feedback", "artifact_feedback", "last_error",
                     "previous_sources", "existing_code", "mode"):
            assert dead not in ctx, f"dead context key survives: {dead}"


class TestCompileFeedbackCcecGuidance:
    """方案 2 + ccec 措辞收敛：ccec 单文件验证指引**只在编译签名错(C-API + no matching
    function)反馈段给**——fresh 首轮无编译不给(见 upstream_reuse)，smoke/runtime/非签名
    类不给（那不是编译期签名问题）。"""

    def test_c_api_signature_error_guides_api_verification(self):
        fb = {
            "kind": "compile", "error_class": "C-API",
            "log_path": "/r/build.log",
            "stderr_tail": "no matching function for call to 'Cast'",
            "retry_count": 1, "class_count": 1, "total_failures": 1,
        }
        section = _stage()._render_build_feedback_section(fb, "<run_dir>")
        assert "no matching function" in section
        # 签名错 → 给判据指针（指向 references 知识），不展开方法/路径（ccec 知识化收敛）
        assert "最小单文件编译验证" in section
        assert "references" in section or "ascendc-op-dev-coding skill 的 references" in section
        assert "知识库/ascendc-tips" in section    # 先查正确签名
        assert "到 /tmp" not in section            # 不写死具体临时路径

    def test_non_signature_compile_error_no_api_verification(self):
        fb = {
            "kind": "compile", "error_class": "C-LNK",
            "log_path": "/r/build.log",
            "stderr_tail": "undefined reference to 'foo'",
            "retry_count": 1, "class_count": 1, "total_failures": 1,
        }
        section = _stage()._render_build_feedback_section(fb, "<run_dir>")
        assert "最小单文件编译验证" not in section    # 链接错非签名错 → 不给验证指引
        # stderr 尾巴摘要不再渲染（截断残影删了）；错误内容走 error_lines/log_path
        assert "stderr 摘要" not in section
        assert "/r/build.log" in section             # 完整日志指针保留

    def test_c_api_without_matching_function_marker_no_guidance(self):
        """C-API 但 stderr 无 no matching function 标记 → 不给验证指引（条件双保险，防误给）。"""
        fb = {
            "kind": "compile", "error_class": "C-API",
            "log_path": "/r/build.log",
            "stderr_tail": "invalid use of incomplete type",
            "retry_count": 1, "class_count": 1, "total_failures": 1,
        }
        section = _stage()._render_build_feedback_section(fb, "<run_dir>")
        assert "最小单文件编译验证" not in section
