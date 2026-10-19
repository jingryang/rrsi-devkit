# step-63 — SKILL 文档漂移收敛 — 实施方案（第四层）

> L3 见 `63-skill-doc-drift-analysis.md`；L1 见 `06-problems.md` P86。

## 1. design pipeline 6 SKILL 文件名收敛（op_spec.json/md → requirement.json）

- **req-analysis SKILL**（10 处）：description / 职责 / 输出表 / 步骤6 / 步骤9 / --from-general-design 步骤4 / 自检 / 约束 / 下游契约。
- **general-design SKILL**（5 处文件名 L17/25/375/574/578）；概念词 op_spec（L64/72/176/373/590，指 requirement.json 内算子规格字段）保留。
- **general-design-review SKILL** L187 / **general_design_template.md** L49 / **design-intake SKILL** L31（"不读"声明）/ **design-validate SKILL** L23/136/192/198（--stage req 模式）。

## 2. checkpoints/{step}.json 降级

- req-analysis SKILL + code-analysis SKILL："必须写 checkpoints/{step}.json" → "可选，工程不消费"。

## 3. op_spec_schema.md 字典化

- 头部 "op_spec 输出格式规范" → "requirement.json 算子规格（op_spec）字段语义"；md 章节段标"历史参考"（agent 不再产独立 op_spec.md）。

## 4. 验证

- design pipeline 6 SKILL 的 op_spec.json/md 文件名引用 = 0（grep 实证）；残留仅 op_spec_schema.md（字典）+ precision-debug（独立）。
- 全量 UT 2318 passed/7 skip 零回归。
- **heavy_llm**：文档漂移收敛不影响工程行为（工程早读 requirement.json、agent 早写 requirement.json，真实 run 实证），无需新 heavy_llm；既有 design pipeline e2e（test_design_*_selfclosure）继续守护。
