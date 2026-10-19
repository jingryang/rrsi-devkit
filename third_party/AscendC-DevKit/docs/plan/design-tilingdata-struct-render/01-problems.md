# L1 问题记录 — Design 链 TilingData 旧宏渲染

> 本层只记客观事实（哪里坏了、凭什么这么说）。不提方案、不排顺序、不写决策。

## 现象

排查 `output/20260722-104126-5c841b-codegen-pass`（算子 swi_glu）中间产物，发现**详设 docgen 阶段把 TilingData 渲染成了 CANN 过时宏写法**，而正确写法应为 plain C struct（POD）。

## 凭据（文件路径 + 行号，2026-07-23 核查）

### A. 详设说明书确凿渲染旧宏

`output/20260722-104126-5c841b-codegen-pass/artifacts/design/docgen/swi_glu详细设计说明书.md` **L296-310**：

```cpp
BEGIN_TILING_DATA_DEF(SwiGLUTilingData)
    TILING_DATA_FIELD_DEF(uint32_t, inputDtypeSize);
    ...
    TILING_DATA_FIELD_DEF_ARR(int64_t, blockSplitOffsets, vectorCoreNum + 1);
    TILING_DATA_FIELD_DEF_ARR(int64_t, coreLoopTimes,    vectorCoreNum);
    TILING_DATA_FIELD_DEF_ARR(int64_t, coreTailRows,     vectorCoreNum);
END_TILING_DATA_DEF;
REGISTER_TILING_DATA_CLASS(SwiGLU, SwiGLUTilingData)
```

### B. codegen 输入把旧宏列为「关键 API」

`artifacts/staging/coding_index.md` **L20**：TilingData 步骤「关键 API」列写 `BEGIN_TILING_DATA_DEF / REGIST_TILING_DATA_FIELD`。

### C. 实际算子代码侥幸正确（struct 写法）

`artifacts/per-op/swi_glu/.../swi_glu/op_kernel/swi_glu_tiling_data.h`：`struct SwiGluTilingData {...}` + kernel 用 `GET_TILING_DATA_WITH_STRUCT`（现代写法）。

### D. docgen 模板自带旧宏占位

`.claude/skills/ascendc-op-design-docgen/references/doc_template_v2.0.md` **L96-98**：TilingData 设计章节代码块占位为 `// BEGIN_TILING_DATA_DEF ... END_TILING_DATA_DEF + CompileInfo struct`，且**无数组字段示例**。

### E. docgen SKILL.md 对 TilingData 渲染完全空白

`.claude/skills/ascendc-op-design-docgen/SKILL.md`：grep `tiling_data_fields`/`struct`/`POD`/`BEGIN_TILING` 零命中（仅 L22/L52 散文式提到「共享 TilingData」，无渲染写法引导）。

### F. 字段产出层是中性 JSON（无写法倾向）

`artifacts/design/tiling/SwiGLU_ND/tiling_split.json`：`tiling_data_fields[]` 每元素仅 `field`/`dtype`/`source`/`length`（数组字段才带 length），不携带「宏 vs struct」写法倾向。

### G. codegen skill 已有 TilingData 铁律（事后兜底）

`.claude/skills/ascendc-op-dev-coding/SKILL.md` **L215-223**（Step 5 TilingData 归一化校验）：`铁律：plain C struct，不使用 CANN 宏`，`违规 → 自动修正为 plain C struct`；L231 字段↔源逐一对应。参考算子 `artifacts/staging/ref_cache/op_kernel/add_tiling_data.h` 也是 struct。

### H. 知识库旧宏文档量大且无废弃标注

`.claude/skills/ascendc-dev-knowledge/references/` 下含 `BEGIN_TILING_DATA_DEF` 的文档约 77 篇（api_reference_docs 42 + 编程指南 10 + 910D_knowledge_extra 25）。权威 API 文档 `api_reference_docs/Utils_API/Tiling数据结构注册/TilingData结构定义.md` 把旧宏当「函数原型」正经教，**无废弃标注**。而 `basic_knowledge_docs/附录/.../使用标准C++语法定义Tiling结构体.md` L86/L277 自己已说宏方式是旧方式、struct 才是推荐。

### I. docgen/validate 均为 LLM 驱动（非确定性渲染器）

`src/ascendc_devkit/orchestration/stages/design_substages.py` L186-193：`spawn one skill agent`。`tests/ut/orchestration/test_docgen_render.py` `TestDeterministicRenderRemoved`：docgen 确定性渲染路径已删除、是 LLM 驱动。但 `ascendc-op-design-validate/SKILL.md` L92-93/L102 仍把 docgen 称为「确定性渲染器」（文档漂移）。

## 传导链（事实陈述，非方案）

```
知识库 ~77 篇旧宏文档（权威 API 文档无废弃标注，H）
  → docgen 渲染时被带偏（SKILL.md 空白 E + 模板旧宏占位 D）
  → 详设说明书渲染旧宏（A）+ coding_index 把旧宏列为关键 API（B）
  → codegen 概率性生成旧宏
  → 本次靠 codegen 铁律（G）+ ref_cache struct（G）事后兜底侥幸正确（C）
```

## 影响面

- 详设交付件（人读）呈现过时写法。
- codegen 输入持续被喂旧宏「关键 API」信号，自检门属事后兜底非源头根治，字段形态（如数组）旧宏也能表达时有翻车风险。
- testdesign few-shot 案例文档亦含旧宏（见 L4 实施清单），经「知识库自学习」机制可能传播进新 testdesign 产物。

## codegen 侧事实（2026-07-23 补充，归属 A5/同事）

- **A3 codegen**（`ascendc-op-dev-coding` + `ascendc-coder`，用户负责）：已有 Step 5「TilingData 归一化校验」自检门（`SKILL.md:215-223`，禁旧宏+就地修）；**不读 coding_index.md**（grep 零命中，A3 直读 design 产物）。→ A3 无缺口，swi_glu 实际 struct 代码即此自检门生效（本次 design 链 docgen/validate 镜像的就是这条铁律）。
- **A5 coding_index 生成**（`ascendc-dev-s2-analysis`，同事负责）：产 coding_index.md，其「关键 API」列写旧宏（swi_glu `artifacts/staging/coding_index.md` L20 `BEGIN_TILING_DATA_DEF / REGIST_TILING_DATA_FIELD`）；s2-analysis 引导（`ascendc-op-dev-coding-regbase/references/phase-c-prompts.md` 等）无「TilingData 关键 API 须 struct 形态」约束。
- **A5 codegen 编码**（`ascendc-op-dev-coding-regbase` + `ascendc-dev-s4-coding`，同事负责）：有 4.A TilingData 定义编码步骤（progress.md L225），但 `ascendc-op-dev-coding-regbase/SKILL.md` 全文 grep `TilingData` 仅进度表 1 处命中——**无 TilingData 写法引导 / `stage4_selfcheck` 无禁旧宏自检**（未镜像 A3 Step 5）。
- **传导**：A5 s2-analysis 产 coding_index 旧宏 → A5 s4-coding 按 coding_index 生成 tiling_data（无自检门兜底，概率性产旧宏）；swi_glu 侥幸 struct 是 s4-coding 跟了 ref_op，非确定性保证。
- **结论**：codegen 侧旧宏问题全在 A5（归同事），A3 无缺口。本次 design 链根治已切断「详设产物→codegen」旧宏输入，但 A5 s2-analysis 在 coding_index **二次引入**旧宏是 A5 内部独立缺口。处置：用户自行与同事沟通（不另起 handoff 文档）。
