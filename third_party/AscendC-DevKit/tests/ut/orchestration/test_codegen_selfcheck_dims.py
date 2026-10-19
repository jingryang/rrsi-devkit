"""UT: codegen skill 多维编码自检 — docs/plan/codegen-skill-selfcheck-dims/。

根因：codegen skill Step6 自检仅 7 项泛化检查（32B 对齐 / TilingData 一致性 / 字段↔源 /
API 签名 / 文件完整性 / ACLNN 符号 / TILING_KEY_IS 分支），缺禁硬编码硬件参数、buffer-pipeline
红线、dtype 一致性等维度。本测试守护三件事（grep SKILL.md 文本，防回归漂移，写法同
test_codegen_upstream_reuse.py::TestSkillDocSourceContract）：
  ① Step6 含维3（禁硬编码硬件参数 → 运行时查询）；
  ② Step6 含维4 buffer-pipeline 红线（AR-1 主循环禁 GetValue/SetValue 搬送 / AR-2 嵌套 GM 单点 / AR-3 非对齐 DataCopyPad）；
  ③ Step6 含维5 dtype 一致性（OpDef dtype ⊇ IO spec / Tiling dtype ⊆ OpDef / Plugin cast 兜底）；
  且不依赖 DevKit 不存在的 buffer_pipeline_redline / high_risk_api_registry（判定规则内联）。
"""

from pathlib import Path

SKILL_MD = (Path(__file__).resolve().parents[3] /
            ".claude/skills/ascendc-op-dev-coding/SKILL.md")


class TestSkillDocSelfcheckDims:
    """SKILL.md Step6 须含维3/维4/维5 自检，且不引用 DevKit 不存在的 registry。"""

    def setUp(self):
        self.text = SKILL_MD.read_text(encoding="utf-8")

    def test_step6_has_dim3_no_hardcoded_hardware(self):  # ① 维3
        self.setUp()
        t = self.text
        assert "维3" in t or "禁硬编码" in t, "Step6 缺维3：禁硬编码硬件参数"
        # 运行时查询替代裸常数
        assert "GetBlockNum" in t or "GetUBSize" in t, \
            "维3 未指引改运行时查询（GetBlockNum/GetUBSize）"
        assert "sizeof" in t or "GetSizeByDataType" in t, \
            "维3 未指引 sizeof(T)/GetSizeByDataType 兜底"

    def test_step6_has_dim4_buffer_pipeline_redline(self):  # ② 维4
        self.setUp()
        t = self.text
        assert "维4" in t or "buffer" in t.lower() or "AR-1" in t, \
            "Step6 缺维4：buffer-pipeline 红线"
        # AR-1 主循环禁 GetValue/SetValue 数据搬送
        assert "AR-1" in t or "主循环" in t, "维4 缺 AR-1：主循环数据搬送"
        assert "GetValue" in t or "SetValue" in t, "维4 缺 AR-1：GetValue/SetValue 单点搬送"
        # AR-2 嵌套循环 GM 单点
        assert "AR-2" in t or "嵌套" in t, "维4 缺 AR-2：嵌套循环 GM 单点访问"
        # AR-3 非对齐 DataCopyPad
        assert "AR-3" in t or "DataCopyPad" in t, "维4 缺 AR-3：非对齐 DataCopyPad"

    def test_step6_has_dim5_dtype_consistency(self):  # ③ 维5
        self.setUp()
        t = self.text
        assert "维5" in t or "dtype 一致" in t or "dtype一致" in t, \
            "Step6 缺维5：dtype 一致性"
        # OpDef dtype ⊇ IO spec
        assert "OpDef" in t, "维5 缺：OpDef dtype ⊇ IO spec"
        assert "IO spec" in t or "IOspec" in t, "维5 缺：IO spec dtype 矩阵"
        # Plugin cast 兜底
        assert "Plugin" in t, "维5 缺：Plugin cast 兜底检测"
        assert "cast" in t.lower(), "维5 缺：cast 兜底"

    def test_step6_has_dim6_infershape_registration(self):  # ④ 维6（机制①）
        self.setUp()
        t = self.text
        assert "维6" in t or "InferShape" in t, "Step6 缺维6：InferShape 注册自检"
        # 结构信号驱动，不认算子名（§1.12）
        assert "GetStorageShape" in t or "storage shape" in t.lower(), \
            "维6 未指引结构信号：tiling 读 GetStorageShape → 需 InferShape"
        assert "elementwise" in t.lower() or "逐元素同形" in t or "同形" in t, \
            "维6 未给『不需要 InferShape』的判据（纯 elementwise 同形）"
        assert "EZ1008" in t, "维6 未点明缺失后果（坍缩 1-D shape → EZ1008）"
        assert "SetInferShape" in t, "维6 未指引注册点（{op}_def.cpp .SetInferShape）"

    def test_dim6_no_operator_name_coupling(self):  # 维6 禁算子名耦合（§1.12）
        self.setUp()
        t = self.text
        # 维6 判据必须凭结构信号，不得点名具体算子做分类锚点
        for line in t.splitlines():
            if "维6" in line:
                assert "output" in line.lower() or "输出" in line, \
                    "维6 判据须基于 output/input 结构关系，非算子身份"
                break

    def test_tilingkey_datatype_vs_dtype_decl_guidance(self):  # 机制②（V3 降级为 skill 引导）
        self.setUp()
        t = self.text
        # 两宏都出现 + 结构信号判据（来源绑定 IO vs 私有枚举）
        assert "ASCENDC_TPL_DATATYPE_DECL" in t and "ASCENDC_TPL_DTYPE_DECL" in t, \
            "缺 DATATYPE_DECL vs DTYPE_DECL 选择引导（Q1a 6 路震荡根）"
        # DATATYPE = 原生/IO 派生（INPUT/OUTPUT 绑定）
        assert "ASCENDC_TPL_INPUT" in t or "ASCENDC_TPL_OUTPUT" in t, \
            "DATATYPE_DECL 判据未指 IO 派生（INPUT/OUTPUT 绑定）"
        assert "原生" in t, "DATATYPE_DECL 未说明=原生 DataType"
        # DTYPE = 自定义枚举
        assert "自定义枚举" in t or "私有枚举" in t or "自定义" in t, \
            "DTYPE_DECL 判据未指自定义枚举"
        # 判据凭结构不凭算子名（§1.12）
        assert "凭参数来源" in t or "结构信号" in t or "凭来源结构" in t, \
            "宏选择判据未声明凭结构信号（非算子名，§1.12）"

    def test_macro_choice_no_operator_name_coupling(self):  # 机制② 禁算子名耦合
        self.setUp()
        t = self.text
        # 定位宏选择自检行（维5b），确保判据是来源结构而非算子清单
        assert "非算子名" in t, "宏选择自检未显式声明判据非算子名（§1.12）"

    def test_step6_has_dim7_kernel_api_literal(self):  # 维7（step-84 问题1）
        self.setUp()
        t = self.text
        assert "维7" in t, "Step6 缺维7：Kernel API 字面量正确性（codegen 本职）"
        # RoundMode 真实枚举集 + 禁造虚构方向枚举
        assert "RoundMode" in t and "CAST_FP16_TO_FP32" in t, \
            "维7 未点明 Cast RoundMode 虚构枚举反例"
        assert "CAST_NONE" in t or "CAST_RINT" in t, "维7 未给真实 RoundMode 枚举集"
        # 明确是 codegen 本职、非上游设计门
        assert "codegen 本职" in t or "codegen 产权" in t, \
            "维7 未声明产权归 codegen（非 anchor/上游门）"
        assert "SetScalarValue" in t, "维7 未覆盖虚构 API 调用形式反例"

    def test_no_external_registry_dependency(self):  # 不补 registry（决策 1/3）
        self.setUp()
        t = self.text
        # DevKit 无此二 registry；判定规则内联，不引用外部文件
        assert "buffer_pipeline_redline" not in t, \
            "SKILL.md 引用了 DevKit 不存在的 buffer_pipeline_redline（应内联 AR-1/2/3 判定）"
        assert "high_risk_api_registry" not in t, \
            "SKILL.md 引用了 DevKit 不存在的 high_risk_api_registry（workspace 准入已由 ③ 入口校验承担）"
