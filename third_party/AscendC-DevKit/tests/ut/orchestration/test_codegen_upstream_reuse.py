"""UT: codegen skill 上游源中间产物复用 — docs/plan/codegen-skill-upstream-reuse/。

根因：即便 codegen skill 已投递（见 test_codegen_skill_delivery.py），agent 手里仍只有 3 个紧凑设计
JSON（design_spec/tiling_strategy/kernel_architecture），缺实现蓝图（Kernel 伪代码/Buffer/split 的源
`tiling_results`）+ general_design/template_division/requirement/test_cases → 转 grep CANN。
本测试守护三件事：
  ① _materialize_inputs 物化上游源中间产物到 staging（含 dataclass 字段 requirement/test_cases 正确序列化）；
  ② _build_codegen_prompt 把源产物按「翻译为哪层」列入输入清单；
  ③ SKILL.md 声明源参考集 + ①例外条款 / ②字段↔源逐一对应 / ③锁定项入口校验 fail-fast（决策5）。
"""

import json
from pathlib import Path

from ascendc_devkit.domain.operator import OperatorSpec
from ascendc_devkit.domain.requirement import Requirement, TestCase
from ascendc_devkit.orchestration.kernel.state import State

SKILL_MD = (Path(__file__).resolve().parents[3] /
            ".claude/skills/ascendc-op-dev-coding/SKILL.md")


def _state_with_sources() -> State:
    """State carrying the upstream source intermediates codegen must materialize."""
    return State(
        mode="new",
        design_target_chip="A5",
        design_spec={"inputs": [{"name": "x"}], "outputs": [{"name": "y"}]},
        tiling_strategy={"split": {"tile": 128}},
        kernel_architecture={"host_code": {"directory": "op_host"}},
        tiling_results={
            "T1": {"buffer_kernel": {"kernel": {
                "pseudocode": "Init/Process/CopyIn/Compute/CopyOut"}}},
        },
        general_design={"op_class": "elementwise", "sections": ["host", "kernel"]},
        template_division={"templates": ["T1"], "locked": {"BUFFER_NUM": 2}},
        requirement=Requirement(op_spec=OperatorSpec(name="moe_re_routing")),
        test_cases=[TestCase(name="case1")],
    )


class TestMaterializeSourceIntermediates:
    """codegen 必须把上游源中间产物物化进 staging，供 agent 按绝对路径读取。"""

    def test_materializes_all_source_intermediates(self, tmp_path):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        artifacts = tmp_path / "artifacts"
        (artifacts / "requirement").mkdir(parents=True)
        (artifacts / "requirement" / "requirement.json").write_text(
            json.dumps({"op_spec": {"name": "moe_re_routing"},
                        "mutation_mode": "out_of_place"}, ensure_ascii=False),
            encoding="utf-8")
        state = _state_with_sources()
        object.__setattr__(
            state, "_workspace", type("WS", (), {"artifacts": artifacts})())
        stage = CodegenStage()
        stage._materialize_inputs(state, tmp_path)
        for fn in ["tiling_results.json", "general_design.json",
                   "template_division.json", "requirement.json",
                   "test_cases.json"]:
            assert (tmp_path / fn).exists(), f"未物化源中间产物 {fn}"

    def test_tiling_results_pseudocode_passes_through(self, tmp_path):
        # kernel.pseudocode 是实现蓝图源头，必须原样透传（不被摘要/截断）
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        stage._materialize_inputs(_state_with_sources(), tmp_path)
        tr = json.loads((tmp_path / "tiling_results.json").read_text(encoding="utf-8"))
        assert tr["T1"]["buffer_kernel"]["kernel"]["pseudocode"] == \
            "Init/Process/CopyIn/Compute/CopyOut"

    def test_requirement_authority_missing_does_not_materialize_reduced(self, tmp_path):
        # §3.12: 无 _workspace → 权威 on-disk requirement.json 不可达 → 不物化
        # reduced（last-resort asdict 兜底已删）。不拿有损数据冒充权威输入——
        # agent 输入缺失应显式暴露，而非静默降级。
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        stage._materialize_inputs(_state_with_sources(), tmp_path)
        assert not (tmp_path / "requirement.json").exists(), \
            "权威不可达时不应物化 reduced requirement.json（§3.12）"

    def test_requirement_reaches_back_to_full_ondisk_file(self, tmp_path):
        # B1 fix: when the authoritative on-disk requirement.json is reachable
        # (via _workspace.artifacts), codegen must materialize the FULL flat file
        # — carrying mutation_mode/math_formula/shape_formula the reduced
        # dataclass drops — NOT asdict(state.requirement). This is the same
        # reach-back the general-design review gate uses (§2.5 single pathway).
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        artifacts = tmp_path / "artifacts"
        (artifacts / "requirement").mkdir(parents=True)
        full = {
            "op_spec": {"name": "moe_re_routing",
                        "inputs": [{"name": "x1", "param_type": "DYNAMIC"}]},
            "mutation_mode": "in_place",
            "math_formula": "y = f(x)",
            "shape_formula": "[S,B,H]",
        }
        (artifacts / "requirement" / "requirement.json").write_text(
            json.dumps(full, ensure_ascii=False), encoding="utf-8")
        state = _state_with_sources()
        object.__setattr__(  # frozen dataclass private slot
            state, "_workspace", type("WS", (), {"artifacts": artifacts})())
        stage = CodegenStage()
        staging = tmp_path / "staging"
        staging.mkdir()
        stage._materialize_inputs(state, staging)
        got = json.loads((staging / "requirement.json").read_text(encoding="utf-8"))
        # Flat form with the design-time fields the dataclass would have dropped.
        assert got["mutation_mode"] == "in_place"
        assert got["math_formula"] == "y = f(x)"
        assert got["shape_formula"] == "[S,B,H]"

    def test_test_cases_serialize_as_list_of_dicts(self, tmp_path):
        # list[TestCase] 必须序列化为 list[dict]，而非 str() 列表
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        stage._materialize_inputs(_state_with_sources(), tmp_path)
        tcs = json.loads((tmp_path / "test_cases.json").read_text(encoding="utf-8"))
        assert isinstance(tcs, list) and isinstance(tcs[0], dict)
        assert tcs[0]["name"] == "case1"

    def test_empty_source_fields_skipped(self, tmp_path):
        # best-effort：空字段不物化（不写空文件），与设计侧 _materialize_inputs 一致
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = State(mode="new", design_target_chip="A5")  # 无任何源产物
        stage._materialize_inputs(state, tmp_path)
        assert not (tmp_path / "tiling_results.json").exists()
        assert not (tmp_path / "requirement.json").exists()


class TestPromptListsSourceIntermediates:
    """prompt 的输入文件清单须列出新物化的源产物（按「翻译为哪层」标注）。"""

    def test_prompt_lists_source_intermediates(self):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        # _build_codegen_prompt 不依赖 staging_dir 物化结果，但需要 workspace 才走 staging 分支；
        # 用 actions() 间接验证 prompt 含源产物指引更接近真实。这里直接构造 prompt：
        state = _state_with_sources()
        ws = _FakeWorkspace()
        object.__setattr__(state, "_workspace", ws)  # frozen dataclass 私有槽
        stage._materialize_inputs(state, ws.staging)
        prompt = stage._build_codegen_prompt(state, 1, ws.staging)
        # step-113 (P11-B1)：指针改指切片目录（读通路唯一），不再注入单体路径
        assert "tiling_results" in prompt
        assert "tiling_results.json" not in prompt
        assert "general_design.json" in prompt
        assert "kernel.pseudocode" in prompt or "伪代码" in prompt  # 蓝图优先级指引

    def test_prompt_wires_scaffolding_reference_roots(self):  # 机制⓪/E0
        """reference_roots（脚手架参考通路）须被 codegen prompt 消费——Q10 根：
        通路被 context 填充但 codegen 从不读，coder 遂 fallback 浏览带毒 sibling。"""
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = _state_with_sources()
        object.__setattr__(state, "reference_roots",
                           ["/repo/examples/aclnn_launch_example/csrc/ops/add"])
        ws = _FakeWorkspace()
        object.__setattr__(state, "_workspace", ws)
        stage._materialize_inputs(state, ws.staging)
        prompt = stage._build_codegen_prompt(state, 1, ws.staging)
        # 声明的根出现在 prompt
        assert "csrc/ops/add" in prompt, "reference_roots 未被 codegen prompt 消费（Q10 根）"
        # 归为脚手架/仓约定，非算法蓝图
        assert "脚手架" in prompt and "仓约定" in prompt
        # 禁浏览未声明兄弟
        assert "兄弟" in prompt and ("禁" in prompt)

    def test_prompt_no_scaffolding_section_when_no_roots(self):
        """无 reference_roots 时不产生脚手架参考段（不无中生有）。"""
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage
        stage = CodegenStage()
        state = _state_with_sources()  # reference_roots 默认空
        ws = _FakeWorkspace()
        object.__setattr__(state, "_workspace", ws)
        stage._materialize_inputs(state, ws.staging)
        prompt = stage._build_codegen_prompt(state, 1, ws.staging)
        # 脚手架参考段的正文标志（区别于蓝图优先级里对该段的引用性提及）
        assert "干净样例算子目录" not in prompt


class _FakeWorkspace:
    def __init__(self):
        import tempfile
        root = Path(tempfile.mkdtemp())
        self.dir = root
        self.staging = root / "staging"
        self.staging.mkdir(parents=True, exist_ok=True)


class TestSkillDocSourceContract:
    """SKILL.md 须声明源参考集 + 决策5 的 ①②③ 内容（防回归漂移）。"""

    def setUp(self):
        self.text = SKILL_MD.read_text(encoding="utf-8")

    def test_declares_source_references(self):
        self.setUp()
        t = self.text
        # 输入契约含源中间产物集（02 决策3 表）
        for key in ["tiling_results", "general_design", "template_division",
                    "requirement", "test_cases"]:
            assert key in t, f"SKILL.md 未声明源参考 {key}"

    def test_reference_exception_clause(self):  # ①
        self.setUp()
        t = self.text
        assert "reference_code" in t
        assert "受控可追溯" in t or "受控" in t
        assert "禁止自行" in t or "禁止自搜" in t
        # Why：自搜产生虚假信号
        assert "虚假信号" in t or "看似通过" in t

    def test_field_source_correspondence(self):  # ②
        self.setUp()
        assert "逐一对应" in self.text

    def test_locked_item_failfast(self):  # ③
        self.setUp()
        t = self.text
        assert "锁定项" in t
        assert "停下报告" in t or "上游缺" in t


class TestCodegenFreshPromptBuildOwnership:
    """L4 改动 4 (方案 2 D5/D7): fresh prompt 不再把 build 命令当「可执行约定」，改声明
    构建归框架 + 引导 ccec 验 API。P1 病根之一是首轮 fresh prompt 无 build 归属，agent 真空
    自研。"""

    def _prompt_with_build_cmds(self):
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage

        class _Profile:
            """轻量 profile stub（非 frozen，仅提供 prompt builder 需要的两个方法）。"""
            def scaffolding_kind(self):
                return "torch_op"
            def build_commands(self, *a, **k):
                return ["bash build.sh --soc={soc_version}"]

        state = State(mode="new", design_target_chip="A5", profile=_Profile())
        stage = CodegenStage()
        return stage._build_codegen_prompt(state, 1, None)

    def test_fresh_prompt_declares_build_framework_owned(self):
        """fresh prompt 声明「构建归框架」+「勿手动整仓构建」——首轮即堵 P1 自研土壤。"""
        text = self._prompt_with_build_cmds()
        assert "整仓编译/部署/冒烟由" in text and "框架" in text
        assert "不要在会话内自行执行整仓构建" in text
        assert "勿手动执行" in text

    def test_fresh_prompt_no_longer_bare_build_command_injection(self):
        """build 命令不再以裸「编译命令:」注入（那暗示 agent 可用它）——改标注框架用。"""
        text = self._prompt_with_build_cmds()
        assert "## 目标仓约定\n编译命令:" not in text  # 旧标题没了
        assert "bash build.sh --soc={soc_version}" in text  # 命令仍列（供了解）

    def test_fresh_prompt_does_not_guide_ccec(self):
        """fresh prompt（首轮无编译）**不含 ccec 引导**——ccec 只在编译签名错反馈段给，首轮给会
        诱导模型「一遇 API 就 ccec」/误解成自己编译。首轮只声明「禁整仓构建」+「编译后框架指引」。"""
        text = self._prompt_with_build_cmds()
        assert "ccec" not in text              # 首轮无编译，不预置 ccec
        assert "不要在会话内自行执行整仓构建" in text  # 禁整仓构建仍在
        assert "读" in text or "Read" in text    # 读写/搜索可用
        assert "尚未编译" in text               # 明示本会话还没编译（不制造编译预期）
