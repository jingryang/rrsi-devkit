# L4 实施方案 — Design 链 TilingData 旧宏渲染

> 具体改哪个文件、什么顺序、怎么验证。动手前写，按需产出。

## 实施清单

### A. docgen 渲染层（构造性保证，核心）

- **A1** `.claude/skills/ascendc-op-design-docgen/SKILL.md`
  - 执行步骤「4.x.2 装载」条目（L54 附近）旁加**渲染铁律**：TilingData 设计章节必须渲染为 plain C struct（POD），禁用 `BEGIN_TILING_DATA_DEF`/`TILING_DATA_FIELD_DEF[_ARR]`/`END_TILING_DATA_DEF`/`REGISTER_TILING_DATA_CLASS` 等 CANN 旧宏；遍历 `tiling_strategy.json.tiling_data_fields[]`（field/dtype/source/length）按 `dtype field;`（数组 `dtype field[length];`）逐行生成 struct 成员；字段与源逐一对应。
  - `## 执行步骤` 第 5 步「输出自检」清单（L64-72）加一条。
  - 措辞镜像 `ascendc-op-dev-coding/SKILL.md:215-223,231`。
- **A2** `.claude/skills/ascendc-op-design-docgen/references/doc_template_v2.0.md` **L96-98**：占位从旧宏注释改为 struct 骨架（含标量 + 数组字段示例），保留其后字段表（L100-101）。

### B. validate 校验门（last-resort 兜底）

- **B1** `.claude/skills/ascendc-op-design-validate/SKILL.md`：
  - GV 规则集（GV9 之后、SR 之前）加 **GV10 TilingData 写法合规**（旧宏禁用清单 + 就地修正为 struct + 适用条件）。
  - Stage 映射表（L133-140）`all`/`tiling`/`doc` 三行加 GV10。
- **B2** `.claude/skills/ascendc-op-design-validate/references/validation_rules.md`：追加 `## GV10 TilingData 写法合规`（2-3 bullet 极简版）。注意该文件仅 GV1-6、与 SKILL.md 不同步（文档漂移），GV10 两处都加。

### C. testdesign 案例清理（消除 few-shot 污染源）

- **C1** `AIInfra-OP-testdesign-analyze-skill/references/测试分析/Tiling设计-TilingData设计/案例1_TilingData等价类分析.md`：1 代码块 → struct。
- **C2** `AIInfra-OP-testdesign-generate-casedesign-skill/references/红线用例/案例3_红线用例设计_轴向对齐_数据类型存在依赖组合.md`：3 行 FIELD_DEF → struct 字段。
- **C3** `AIInfra-OP-testdesign-generate-casedesign-skill/references/红线用例/案例4_红线用例设计_轴向对齐_数据类型全组合.md`：3 行 FIELD_DEF → struct 字段。
- **C4** `AIInfra-OP-testdesign-analyze-skill/references/原始信息提取/案例7_Tiling设计提取.md`：2 代码块 → struct + 提取规则 #6 措辞改（「原样保留宏定义结构」→「原样保留 struct 字段定义」）。

## 顺序

A1 → A2 → B1 → B2 → C1..C4 → 验证。A/B/C 互不依赖，可并行；建议 A 先行（核心）。

## 验证（D6）

1. **静态 grep（主，确定性）**：改完后 grep 确认 docgen skill 正文+模板、validate 规则、testdesign 4 案例不再把旧宏当推荐写法/占位。
2. **守护 UT（可选，确定性）**：参照 `tests/ut/skills/test_testdesign_selfcontained.py` 先例，加一个 UT 守护 docgen 模板 TilingData 占位为 struct（防回归）。
3. **heavy ST（需用户确认，§3.11）**：`tests/st/test_design_docgen_tui_selfclosure.py` 端到端验证 docgen 产出 struct（真实 LLM，分钟级）。

## 不在本次范围（边界）

- 知识库 `ascendc-dev-knowledge`（爬虫覆盖）。
- codegen skill `ascendc-op-dev-coding`（已有自检门）。
- `coding_index.md` 生成 / s2-analysis（A5 codegen 侧，单独讨论）。
- anchor 门（只读正交）。
- `ascendc-tiling-strategy/SKILL.md`、`ascendc-migration` 等非主链 skill 旧宏（后续单列）。
