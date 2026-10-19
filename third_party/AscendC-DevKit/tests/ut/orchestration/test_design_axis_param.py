"""UT: 可配置轴（axis-param）设计加性改动 — docs/plan/configurable-axis-design-gap/。

根因：设计流水线无"运行时可选计算轴（dim）"概念，SwiGLU 这类轴参算子的拆分轴被当固定末轴
→ dim≠末轴用例算错（详见 01-problems.md P1）。commit 1 的加性修复：general-design 识别轴参算子
并填可选字段 axis_param_design（主路径仍 dim=末轴、当前 codegen 忽略该字段 → 零回归）；
tiling-buffer-kernel 界定主伪代码只覆盖 dim=末轴快路径；docgen 渲染轴参泛化小节。

本测试守护四件事（grep SKILL.md / schema 文本，防回归漂移，写法同 test_codegen_a5_constraints.py）：
  ① general-design SKILL 含「轴参算子」识别 + axis_param_design 指引 + 主路径不变声明；
  ② general-design schema example 含 axis_param_design 且 required_keys 仍为 5 个（加性、不破契约）；
  ③ tiling-buffer-kernel SKILL 含「主伪代码只覆盖 dim=末轴快路径、泛化见上游 axis_param_design」；
  ④ docgen SKILL 含 axis_param_design 条件渲染规则。
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GENERAL_DESIGN_SKILL = REPO / ".claude/skills/ascendc-op-general-design/SKILL.md"
GENERAL_DESIGN_SCHEMA = REPO / ".claude/skills/ascendc-op-general-design/schema/general_design.json"
BUFFER_KERNEL_SKILL = REPO / ".claude/skills/ascendc-op-tiling-buffer-kernel/SKILL.md"
DOCGEN_SKILL = REPO / ".claude/skills/ascendc-op-design-docgen/SKILL.md"


class TestAxisParamDesignAdditive:
    """轴参算子设计为纯加性：主路径不变 + 新可选字段 axis_param_design。"""

    def test_general_design_recognizes_axis_param_op(self):  # ①
        t = GENERAL_DESIGN_SKILL.read_text(encoding="utf-8")
        assert "轴参算子" in t, "general-design 未识别「轴参算子」"
        assert "axis_param_design" in t, "general-design 未指引填 axis_param_design"
        # 主路径不变声明（加性核心不变式）
        assert "dim=末轴" in t or "dim == 末轴" in t, "general-design 未声明主路径仍按 dim=末轴"

    def test_general_design_schema_axis_param_optional_and_required_unchanged(self):  # ②
        s = json.loads(GENERAL_DESIGN_SCHEMA.read_text(encoding="utf-8"))
        # required_keys 不变（仍是 5 个强校验字段，加性不破契约）
        assert s["required_keys"] == [
            "op_name", "split_axis_priority", "tiling_data", "loop_framework", "buffer_eval",
        ], f"required_keys 被改动（应保持 5 字段）：{s['required_keys']}"
        # example 含 axis_param_design（文档化可选字段）
        assert "axis_param_design" in s["example"], "schema example 未含 axis_param_design"
        apd = s["example"]["axis_param_design"]
        assert apd.get("is_axis_param_op") is True
        # e3b6c8df: fast_path/generalization 为双路径 dict（各含可落地 tiling_data_fields
        # + loop_sketch），不再有顶层 tiling_data_extensions 列表——强制双路径覆盖而非
        # 只声明末轴快路径（否则 dim!=末轴 case tiling 设计缺失 → codegen 无蓝图可译）。
        for path_key in ("fast_path", "generalization"):
            assert path_key in apd, f"axis_param_design 缺 {path_key} 路径"
            assert isinstance(apd[path_key], dict), f"{path_key} 应为双路径 dict"
            assert "condition" in apd[path_key], f"{path_key} 缺 condition"
            assert "tiling_data_fields" in apd[path_key], f"{path_key} 缺 tiling_data_fields"
            assert "loop_sketch" in apd[path_key], f"{path_key} 缺 loop_sketch"

    def test_buffer_kernel_main_pseudocode_boundary(self):  # ③
        t = BUFFER_KERNEL_SKILL.read_text(encoding="utf-8")
        assert "轴参算子双路径伪代码" in t, "tiling-buffer-kernel 未界定轴参算子双路径伪代码"
        assert "axis_param_design" in t, "tiling-buffer-kernel 未引用上游 axis_param_design"
        assert "dim=末轴" in t, "tiling-buffer-kernel 未声明主伪代码覆盖 dim=末轴快路径"
        assert "generalized" in t, "tiling-buffer-kernel 未要求 generalized(dim≠末轴) 路径伪代码"

    def test_docgen_renders_axis_param(self):  # ④
        t = DOCGEN_SKILL.read_text(encoding="utf-8")
        assert "axis_param_design" in t, "docgen 未含 axis_param_design 渲染规则"
        assert "轴参泛化设计" in t, "docgen 未定义「轴参泛化设计」小节渲染"
