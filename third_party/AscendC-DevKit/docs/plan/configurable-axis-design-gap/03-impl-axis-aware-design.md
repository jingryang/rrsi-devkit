# commit 1 实施 — 可配置轴设计（加性）(L4)

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md`。本 commit 严格加性：不动 `required_keys`、不动主伪代码（dim=末轴快路径），不提交 commit 2 也不影响运行。

## 改动清单（全部加性）

### 1. `general-design/SKILL.md` 步骤 3.2 —— 新增「轴参算子识别」
在提取三维分类特征处，加一条轴参识别：**当算子的拆分/计算轴是运行时属性（如 `dim`，默认 -1）而非固定轴时，标记为轴参算子**。判定依据：op_spec/requirement 含运行时可配置的轴属性 + 算子语义沿该轴做 split/reduce/concat 等。

### 2. `general-design/SKILL.md` —— 轴参算子须填可选字段 `axis_param_design`
轴参算子须在 `general_design.json` 填**可选**顶层字段 `axis_param_design`（轴参泛化规格，见下）；非轴参算子不填。**主 `tiling_data`/`loop_framework`/`split_axis_priority` 仍按 dim=末轴快路径给出（当前行为不变）。**

### 3. `general-design/schema/general_design.json` —— 文档化可选字段
`description` + `example` 增 `axis_param_design`（**可选，不入 `required_keys`**）。

### 4. `tiling-buffer-kernel/SKILL.md` —— 主伪代码边界 + 泛化归属
加一条：**轴参算子的主 Kernel 伪代码（本 skill 产出）= dim=末轴快路径；dim≠末轴的轴参泛化寻址规格见上游 `axis_param_design`，不在主伪代码展开**（避免 codegen 误把泛化塞进主路径；泛化发射属 commit 2 / codegen 责任）。

### 5. `design-docgen/SKILL.md` —— 渲染轴参泛化小节
`general_design.json` 含 `axis_param_design` 时，在第 3 章「总体设计」渲染「轴参泛化设计」小节（明示：主路径 dim=末轴、泛化路径需 codegen 支持、当前 codegen 仅实现主路径）。

## `axis_param_design` 字段内容规格（commit 2 codegen 据此发射）

```json
"axis_param_design": {
  "is_axis_param_op": true,
  "axis_attr": "dim",
  "axis_default": -1,
  "fast_path": "dim==末轴：x0/x1 为同连续区间的两半，主伪代码覆盖（连续 DataCopy + VF 计算）",
  "generalization": "dim≠末轴：host TilingFunc 按实际 dim 推导 x0/x1 的 GM offset/stride/blockLen/blockCount → kernel CopyIn 用 strided DataCopy 按 dim 搬 x0/x1 → VF 计算（轴无关）不变 → CopyOut 按输出布局",
  "tiling_data_extensions": ["<需新增的可选 TilingData 轴描述符字段，如 x0GmOffset/x1GmOffset/axisStride...>"]
}
```

## UT（非 heavy_llm，grep 契约断言）

- `test_general_design_axis_param_recognition`：SKILL 含「轴参算子」识别 + `axis_param_design` 指引。
- `test_general_design_schema_axis_param_optional`：schema example 含 `axis_param_design` 且 `required_keys` **不变**（仍 5 个）。
- `test_tiling_buffer_kernel_axis_param_boundary`：SKILL 含「主伪代码=dim 末轴快路径、泛化见上游 `axis_param_design`」。
- `test_docgen_renders_axis_param`：SKILL 含 `axis_param_design` 渲染规则。
- 回归：`required_keys` 四/五字段不变 + 既有 codegen/design 用例不回归。

## 顺序

1→2→3（general-design SKILL + schema）→ 4（tiling-buffer-kernel）→ 5（docgen）→ 写 UT → `pytest tests/ut -m "not heavy_llm"` 相关用例。

## 不在本 commit

- commit 2（codegen axis-aware 发射）：读 `axis_param_design` + `tiling_data_extensions` → 产 host TilingFunc（算 stride）+ kernel strided CopyIn。本地两笔合跑 heavy_llm 验证 dim=0 用例 diff→pass，作合入证据交 codegen 责任人。
- heavy_llm e2e（依赖 commit 1+2）。