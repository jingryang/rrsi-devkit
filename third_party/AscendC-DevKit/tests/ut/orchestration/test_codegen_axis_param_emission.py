"""UT: codegen axis-aware 发射（commit 2）— docs/plan/configurable-axis-design-gap/。

commit 2（codegen，可与 commit 1 合并验证、单独合入休眠）：ascendc-op-dev-coding skill 读
general_design.json:axis_param_design，对轴参算子发射 axis-aware host TilingFunc + kernel strided
CopyIn；不含 axis_param_design 则维持 dim=末轴行为（休眠）。

本测试守护 commit 2 的 skill 文本（grep 防漂移）。注意：本测试属 commit 2——commit 2 未合时
ascendc-op-dev-coding SKILL 无本节内容，本测试会 fail（故随 commit 2 一起提交/合入）。
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CODING_SKILL = REPO / ".claude/skills/ascendc-op-dev-coding/SKILL.md"


class TestAxisParamCodegenEmission:
    """commit 2：codegen 对轴参算子发射 axis-aware，gate 在 axis_param_design 存在。"""

    def test_coding_skill_has_axis_aware_emission_section(self):
        t = CODING_SKILL.read_text(encoding="utf-8")
        assert "轴参算子 axis-aware 发射" in t, "ascendc-op-dev-coding 未含 axis-aware 发射小节"
        assert "axis_param_design" in t, "ascendc-op-dev-coding 未引用 axis_param_design 触发条件"

    def test_coding_skill_covers_host_tilingfunc_and_kernel_copyin(self):
        t = CODING_SKILL.read_text(encoding="utf-8")
        # Host TilingFunc 推导轴描述符
        assert "Host TilingFunc" in t and "轴描述符" in t, "未指引 Host TilingFunc 填轴描述符"
        # Kernel CopyIn 用 strided DataCopyPad
        assert "DataCopyPad" in t and "strided" in t, "未指引 Kernel CopyIn 用 strided DataCopyPad"
        # VF 计算不变（轴无关）
        assert "VF 计算" in t and "轴无关" in t, "未声明 VF 计算轴无关/不变"

    def test_coding_skill_gated_and_dormant_without_commit1(self):
        t = CODING_SKILL.read_text(encoding="utf-8")
        # 必须明示 gate：无 axis_param_design 则维持当前行为（休眠 no-op）
        assert "维持当前 dim=末轴行为" in t or "休眠" in t, "未声明无 axis_param_design 时休眠（加性/dormant）"

    def test_coding_skill_a5_redline_compatibility_note(self):
        t = CODING_SKILL.read_text(encoding="utf-8")
        # A5 兼容说明：strided DataCopyPad 属 MTE2 CopyIn（Vector 域外），不违红线 #1
        assert "MTE2" in t and "红线 #1" in t, "未声明 A5 红线 #1 兼容性（strided DataCopyPad 属 MTE2 域外）"
