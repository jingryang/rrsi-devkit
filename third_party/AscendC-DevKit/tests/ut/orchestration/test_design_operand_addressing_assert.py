"""UT: 设计期操作数寻址对齐断言 — docs/plan/design-blueprint-feasibility/03-impl-1a。

根因（批 20260911-172304-501e35 adaptive_avg_pool_3d，5-cut 零落盘 halt）：T1 蓝图指定
Hillis-Steele 移位向量 Add 扫描，fp32 步长 1/2/4 = 4/8/16B 违反 Add.md 操作数 32B 起始地址
对齐——物理不可实施；claim 的 source_pointer 引用知识库不存在的内容（"向量 Add 支持
LocalTensor 偏移访问"）却标 derived 放行；现行对齐类自检作用域止于 Buffer 尺寸表，无任何
自检项把 R1 伸入算法内部的操作数偏移/移位形态。

本测试守护两件事（grep skill 文本防漂移，写法同 test_codegen_a5_constraints.py）：
  ① checkpoint_convention.md A2 节含「操作数寻址断言」——向量 API 偏移/移位寻址 claim 的
     evidence 必含逐步长字节换算（step × sizeof(T)）对照 API 文档操作数对齐条款，违约步长
     须给对齐安全变形或改选路径，结论落 self_check_summary 既有通道；
  ② buffer-kernel SKILL.md 红队自检镜像该要求（执行锚点，指向 convention 单源）。
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CONVENTION_MD = (REPO /
                 ".claude/skills/ascendc-op-design-shared/references/checkpoint_convention.md")
BUFFER_KERNEL_MD = (REPO / ".claude/skills/ascendc-op-tiling-buffer-kernel/SKILL.md")


class TestOperandAddressingAssertion:
    """convention 单源定义 + buffer-kernel 执行锚点均在位。"""

    def test_convention_a2_has_operand_addressing_rule(self):
        t = CONVENTION_MD.read_text(encoding="utf-8")
        assert "操作数寻址断言" in t, "A2 节缺「操作数寻址断言」规则"
        assert "step × sizeof(T)" in t, "断言缺字节换算公式 step × sizeof(T)"
        assert "操作数对齐条款" in t, "断言未要求引用 API 文档操作数对齐条款"
        # 违约不放行：必须变形或换路径
        assert "对齐安全的变形" in t, "违约步长未要求对齐安全变形"
        assert "改选路径" in t, "违约步长未允许改选路径"
        # 触发范围窄：仅偏移/移位寻址（不与 Buffer 尺寸对齐/R8 strided DataCopy 重叠）
        assert "偏移/移位寻址" in t, "触发条件未写窄为偏移/移位寻址"
        # 结论落既有通道，不加新字段
        assert "self_check_summary" in t, "断言结论未落 self_check_summary 既有通道"

    def test_buffer_kernel_redteam_mirrors_assertion(self):
        t = BUFFER_KERNEL_MD.read_text(encoding="utf-8")
        assert "操作数寻址断言" in t, "红队自检未镜像 convention 断言"
        assert "step × sizeof(T)" in t, "镜像句缺字节换算公式"
        assert "checkpoint_convention.md" in t, "镜像句未指向 convention 单源"
        # 镜像挂在既有红队自检项上（执行锚点，非新增自检条目）
        assert "骨架级断言红队复核" in t, "既有红队自检项被误删"

    def test_mirror_scope_not_bound_to_closed_enum(self):
        """M1 防复发（review 2026-09-15）：镜像句触发不得绑定 gather/scatter/reduce
        封闭枚举——写入侧指令（SKILL.md 步骤4 + schema）用开放枚举「gather/scatter/
        reduce 等」，本次事故的移位扫描 claim 凭「等」进 verifiable_claims 却不在
        封闭三元组内；自检若用「其中」限定即写入会记、自检不查。"""
        t = BUFFER_KERNEL_MD.read_text(encoding="utf-8")
        assert "任何依赖向量 API 操作数偏移/移位寻址" in t, \
            "镜像句须以「任何依赖…」（独立触发），不得用「其中」绑定封闭枚举"
        assert "不限 gather/scatter/reduce" in t, "镜像句须显式声明不限三元组"

    def test_mirror_scope_not_bound_to_closed_enum(self):
        """M1 防复发（review 2026-09-15）：镜像句触发不得绑定 gather/scatter/reduce
        封闭枚举——写入侧指令（SKILL.md 步骤4 + schema）用开放枚举「gather/scatter/
        reduce 等」，本次事故的移位扫描 claim 凭「等」进 verifiable_claims 却不在
        封闭三元组内；自检若用「其中」限定即写入会记、自检不查。"""
        t = BUFFER_KERNEL_MD.read_text(encoding="utf-8")
        assert "任何依赖向量 API 操作数偏移/移位寻址" in t, \
            "镜像句须以「任何依赖…」（独立触发），不得用「其中」绑定封闭枚举"
        assert "不限 gather/scatter/reduce" in t, "镜像句须显式声明不限三元组"
