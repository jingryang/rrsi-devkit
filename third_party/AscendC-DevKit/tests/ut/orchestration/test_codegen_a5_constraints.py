"""UT: codegen skill A5 编码硬约束 — docs/plan/codegen-skill-a5-constraints/。

根因：codegen skill 对 A5 Regbase 仅 Step4 路由表一句「VF 入口 + RegTensor + 910D 约束」，
无可执行编码红线 → agent 不知 Vector 执行域内什么禁写 → A5 kernel 极易编译失败
（Regbase 约束强，违反即编译报错）。本测试守护四件事（grep SKILL.md 文本，防回归漂移，
写法同 test_codegen_upstream_reuse.py::TestSkillDocSourceContract）：
  ① Step3 A5 知识查阅指向 ascendc-dev-knowledge（SIMD_API/Reg矢量计算 + 910D_knowledge_extra），
     复用已加载知识库，不复制 ascendskills regbase-vf-test；
  ② Step4 含 A5 Regbase 编码红线（Vector 执行域定义 + 九条强制约束）；
  ③ Step4 含 A5 专属规则（RegTensor≤32 / MaskReg≤8 / GetPhyAddr / DCache 预留）；
  ④ Step6 含 A5 专属自检行；且不引入 full-pipeline driver 机制
     （regbase-vf-test / vf_verified / coding_index / RECORD_DIR / CTX_DRIFT）。
"""

from pathlib import Path

SKILL_MD = (Path(__file__).resolve().parents[3] /
            ".claude/skills/ascendc-op-dev-coding/SKILL.md")


class TestSkillDocA5Constraints:
    """SKILL.md 须含 A5 Regbase 编码红线 + 专属规则 + 自检，且不引入 driver 机制。"""

    def setUp(self):
        self.text = SKILL_MD.read_text(encoding="utf-8")

    def test_step3_points_a5_knowledge_to_ascendc_dev_knowledge(self):  # ①
        self.setUp()
        t = self.text
        # A5 知识查阅指向 ascendc-dev-knowledge 两处：VF 指令签名 + Regbase 编程模型
        assert "SIMD_API" in t, "Step3 未指向 VF 指令签名库 SIMD_API"
        assert "Reg矢量计算" in t, "Step3 未指向 SIMD_API/Reg矢量计算（VF 指令参考）"
        assert "910D_knowledge_extra" in t, "Step3 未指向 910D_knowledge_extra（Regbase 编程模型）"

    def test_step4_has_vector_execution_domain_definition(self):  # ②
        self.setUp()
        t = self.text
        # Vector 执行域定义是九条约束的前提
        assert "Vector 执行域" in t or "执行域" in t, "未定义 Vector 执行域（九条约束前提）"
        assert "__simd_vf__" in t or "VF" in t, "未提及 VF 函数执行域"

    def test_step4_has_nine_mandatory_constraints(self):  # ②
        self.setUp()
        t = self.text
        # 九条强制约束关键词（违反即编译失败）
        assert "禁" in t and "DataCopy" in t, "缺约束：禁 A3 DataCopy"
        assert "ASCENDC_TPL" in t, "缺约束：TilingKey 模板参数化正向引导（ASCENDC_TPL）"
        assert "GetPhyAddr" in t, "缺约束：LocalTensor 须经 GetPhyAddr 转换"
        assert "MicroAPI" in t, "缺约束：须用 MicroAPI 命名空间（禁 A3 高阶 API）"
        assert "inline" in t, "缺约束：VF 必须 inline"
        assert "void" in t, "缺约束：VF 必须 void"
        assert "__ubuf__" in t, "缺约束：VF 参数仅 __ubuf__ T*/PoD（禁 pass-by-reference）"
        # SIMD/SIMT 隔离
        assert "SIMD" in t and "SIMT" in t, "缺约束：SIMD/SIMT 隔离"

    def test_step4_has_a5_quota_rules(self):  # ③
        self.setUp()
        t = self.text
        # 专属规则：RegTensor≤32 / MaskReg≤8 / DCache 预留
        assert "RegTensor" in t, "缺专属规则：RegTensor 数量上限"
        assert "32" in t, "缺专属规则：RegTensor≤32"
        assert "MaskReg" in t, "缺专属规则：MaskReg 数量上限"
        assert "8" in t, "缺专属规则：MaskReg≤8"
        assert "DCache" in t or "Cache" in t, "缺专属规则：UB DCache 预留"

    def test_step6_has_a5_selfcheck_rows(self):  # ④
        self.setUp()
        t = self.text
        # Step6 A5 专属自检项
        assert "VF 函数签名" in t or "VF 签名" in t, "Step6 缺 A5 自检：VF 签名合规"
        assert "RegTensor" in t, "Step6 缺 A5 自检：RegTensor 数量"
        assert "MaskReg" in t, "Step6 缺 A5 自检：MaskReg 数量"
        assert "Membase API 入侵" in t or "Membase 入侵" in t or "A3 API 入侵" in t, \
            "Step6 缺 A5 自检：Membase API 入侵"
        assert "SIMD" in t and "SIMT" in t and "隔离" in t, "Step6 缺 A5 自检：SIMD/SIMT 隔离"

    def test_no_external_driver_mechanism(self):  # ④ 不吸收 driver
        self.setUp()
        t = self.text
        # 不引入 full-pipeline driver 机制（§2.5/§2.6：当前框架等价物 = staging + skill 投递 + Event Sourcing）
        for forbidden in ["regbase-vf-test", "vf_verified", "coding_index",
                          "RECORD_DIR", "CTX_DRIFT"]:
            assert forbidden not in t, (
                f"SKILL.md 引入了 driver 机制 {forbidden!r}（应只用 staging+skill投递+Event Sourcing）")
