"""UT: codegen skill 投递修复（§4.3）— docs/plan/codegen-skill-delivery/。

根因：CodegenStage 违反 §4.3，codegen 专用 skill ascendc-op-dev-coding 加载但从未投递，
agent 自行 grep CANN 头文件撑爆上下文。本测试守护三件事：
  ① SpawnAgent.primary_skill 携带方法论 skill（D2：投递下沉到 backend 边界，
     由 render_skill_injection 原生渲染；claude=/<skill> slash，opencode=first-call）；
  ② codegen 物化 meta.json 满足 skill 输入契约（programming_model 驱动编码路径）；
  ③ STAGE_SKILL_MAP 含 codegen 条目且加载期校验通过（§1.3）。
"""

from pathlib import Path

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.skill_config import (
    STAGE_SKILL_MAP, validate_skill_map,
)


class TestCodegenSkillDelivery:
    """codegen agent 必须收到其方法论 skill（含「禁 grep CANN、查知识库」纪律）。"""

    def test_skill_map_includes_codegen(self):
        # 决策 2：codegen 进 STAGE_SKILL_MAP（单源），与设计侧同机制
        assert STAGE_SKILL_MAP.get("codegen") == "ascendc-op-dev-coding"

    def test_skill_map_validates_at_load_time(self):
        # §1.3：投递的 skill 必须落盘存在，否则 slash 展开为空 → agent 又 skill-dead
        errors = validate_skill_map()
        assert not any("codegen" in e for e in errors), (
            f"codegen skill 未通过加载期校验: {errors}")

    def test_codegen_delivers_skill_via_primary_skill(self):
        # §4.3 + D2：投递不再由 stage 前置 slash，而是经 SpawnAgent.primary_skill
        # 结构化携带，backend 边界 render_skill_injection 原生渲染（claude 展开
        # /<skill> 注入 SKILL.md；opencode first-call）。prompt body 不含前置 slash。
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = State(mode="new")
        actions = stage.actions(state, 1)
        assert len(actions) == 1
        assert actions[0].primary_skill == "ascendc-op-dev-coding", (
            f"codegen 未经 primary_skill 投递方法论 skill，实得: "
            f"{actions[0].primary_skill!r}")
        # skills 保持 None（OPEN allowlist）—— coder 仍可 Skill-call 知识库/tips
        assert actions[0].skills is None
        # prompt body 自身不再前置 slash（投递已下沉到 backend）
        assert not actions[0].prompt.startswith("/ascendc-op-dev-coding")


class TestCodegenMetaJsonContract:
    """ascendc-op-dev-coding skill 要 meta.json（缺 programming_model → status=fail），
    codegen 必须物化它。programming_model 由 canonical 代际派生（SKILL.md Step4 表）。"""

    def test_materializes_meta_json(self, tmp_path):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        import json
        stage = CodegenStage()
        state = State(mode="new", design_target_chip="A5")
        stage._materialize_inputs(state, tmp_path)
        meta_path = tmp_path / "meta.json"
        assert meta_path.exists(), "codegen 未物化 meta.json（skill 契约要求）"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "programming_model" in meta
        assert "chip_code" in meta
        assert "soc_version" in meta

    def test_programming_model_mapping(self):
        # SKILL.md Step4：A5 → Regbase（路径三 VF+RegTensor）；A2/A3 → Membase（路径二）。
        # A2 与 A3 同属 Membase/SIMD 架构代（general_design_common_knowledge.md：
        # 「A2 行为与 A3 一致」），仅 A5(910D) 为 Regbase/VF 代。codegen 曾误把 A2 归入
        # Regbase → 910B 算子被引向 VF/RegTensor 路径三、生成 910B 无法编译的代码；
        # 此断言锁死正确映射、防回归。
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        assert "Regbase" in stage._programming_model_for("A5")
        assert "Membase" in stage._programming_model_for("A2")
        assert "Membase" in stage._programming_model_for("A3")

    def test_meta_json_soc_version_matches_chip(self, tmp_path):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        from ascendc_devkit.domain.chip import to_soc_version
        import json
        stage = CodegenStage()
        state = State(mode="new", design_target_chip="A5")
        stage._materialize_inputs(state, tmp_path)
        meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
        assert meta["soc_version"] == to_soc_version("A5")

    def test_meta_json_dual_source_forward_compat_mode(self, tmp_path):
        # P65 dual source: design=A2 drives programming_model (code STYLE),
        # runtime=A5 drives chip_code + soc_version (COMPILE target). On an A5
        # box validating A2 Membase codegen, meta.json must say "A2 Membase" for
        # the coding path BUT compile for the A5 box (ascend950).
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        import json
        stage = CodegenStage()
        state = State(mode="new", design_target_chip="A2", runtime_target_chip="A5")
        stage._materialize_inputs(state, tmp_path)
        meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
        assert meta["programming_model"] == "A2 Membase"   # design-driven style
        assert meta["chip_code"] == "A5"                    # runtime-driven compile
        assert meta["soc_version"] == "ascend950"           # runtime-driven soc


class TestRegbaseLastErrorDiagnosticInjection:
    """last_error.md 诊断注入（s2/s4 重试轮）——守护 s5→s4 回退诊断修复。

    编译验证收敛到 s5 后，s4 重做 agent 拿到上轮失败诊断的唯一确定性通道就是
    last_error.md（写入端：_handle_regbase_failure 的 s2/s5 失败 message +
    dispatch 的 error_detail；清除端：dispatch COMPLETED 提交）。s2/s4 prompt
    必须在文件存在时注入「上次失败诊断」段，否则回退/重试是盲目重跑。
    """

    @staticmethod
    def _s4_prompt(rd: Path, state: State | None = None) -> str:
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        return stage._build_s4_prompt(
            state or State(mode="new"), str(rd),
            ["4.C.2"], "kernel_base", "KERNEL", "/tmp/code")

    def test_s4_prompt_injects_last_error_diagnostic(self, tmp_path):
        (tmp_path / "last_error.md").write_text(
            "CMakeLists.txt missing on disk", encoding="utf-8")
        prompt = self._s4_prompt(tmp_path)
        assert "【上次失败诊断 — 必须先修复】" in prompt
        assert str(tmp_path / "last_error.md") in prompt
        # 注入只给路径，不内联内容——agent 读文件获取诊断（防 prompt 膨胀）
        assert "CMakeLists.txt missing" not in prompt

    def test_s4_prompt_no_file_no_injection(self, tmp_path):
        prompt = self._s4_prompt(tmp_path)
        assert "上次失败诊断" not in prompt

    def test_s2_prompt_injects_last_error_diagnostic(self, tmp_path):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        (tmp_path / "last_error.md").write_text(
            "orchestration_plan.json 缺失", encoding="utf-8")
        prompt = CodegenStage()._build_s2_prompt(
            State(mode="new"), str(tmp_path), "", "", "/tmp/code")
        assert "【上次失败诊断 — 必须先修复】" in prompt
