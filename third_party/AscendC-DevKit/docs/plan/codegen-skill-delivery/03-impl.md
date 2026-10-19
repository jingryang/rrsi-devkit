# codegen skill 投递缺失 — 实施（L4）

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md`，事实见 `01-problems.md`。

## 改动 1 — STAGE_SKILL_MAP 加 codegen（决策 2）
`resources/orchestration-config.json` 的 `skills.stages` 增：
```json
"codegen": "stage-codegen:ascendc-op-dev-coding"
```
`validate_skill_map()` 加载期自动校验该 skill 存在（§1.3）。

## 改动 2 — CodegenStage 投递 skill + 物化 meta.json（决策 1/3）
`orchestration/stages/codegen.py`：
- **投递**：`actions()` 构造 prompt 后，用 `_with_trigger(body)` 把 `/{STAGE_SKILL_MAP["codegen"]}`
  作首行 prepend（镜像 `design_substages.py:326-334`）。新增 `_skill_trigger()`/`_with_trigger()`
  小方法（与设计侧同形；不复用设计侧基类——CodegenStage 继承 Stage，不继承 design substage 基类，
  且这俩方法仅 3 行，提取 mixin 属过度设计 [[avoid-overdesign-prefer-reuse]]）。
- **meta.json**：`_materialize_inputs` 增写 `meta.json` 到 staging，含
  `programming_model`/`chip_code`/`soc_version`。新增 `_programming_model_for(chip)`：
  `A2/A5→"<gen> Regbase"`、`A3→"A3 Membase"`（据 SKILL.md Step4 表）。
  `chip_code`=canonical 代际；`soc_version`=`to_soc_version(chip)`（domain/chip.py）。
- prompt 里把 meta.json 加进「设计产物（输入文件）」清单，指向 staging 绝对路径。

## 改动 3 — ascendc-coder.md Coding Rules 加指针（双保险，决策 1）
`.claude/agents/ascendc-coder.md` Coding Rules 增一条：
「本会话已加载 `stage-codegen:ascendc-op-dev-coding` skill——按其流程执行
（Step3 编码前查 `ascendc-dev-knowledge` 知识库 INDEX.md 拿 API 签名/约束；
**禁止 grep/cat/find `$ASCEND_TOOLKIT_HOME`、`/usr/local/Ascend/`**——SDK 头文件千行，
读入即撑爆上下文；查不到用 ascendc-tips，仍查不到停下报告，不翻 SDK 源码）。」
agent.md 是 agent 行为基线（§4.1 manifest 驱动），与 prompt 投递双保险。

## 顺序
1. TDD 先写测试（见下）。
2. 改动 1（config）→ 改动 2（codegen.py）→ 改动 3（agent.md）。
3. 跑测试至绿。

## 验证（TDD）
`tests/ut/orchestration/` 既有 codegen stage 测试增：
- `test_codegen_prompt_leads_with_skill_slash`：`actions()` 返回的 prompt 首行 ==
  `/stage-codegen:ascendc-op-dev-coding`。
- `test_codegen_materializes_meta_json`：staging 有 `meta.json`，A5→programming_model 含
  `Regbase`、A3→`Membase`、soc_version==`to_soc_version(chip)`。
- 既有 codegen 用例不回归（slash prepend 不破坏 sections 结构）。
- `validate_skill_map()` 含 codegen 条目且通过（加载期校验）。

全量 UT：`pytest -m "not heavy_llm"`，0 回归。

## 后续（不在本轮）
- 重跑 E2E moe_re_routing（heavy_llm，跑前用户确认 §3.11）：确认 codegen 不再 grep CANN、
  上下文有界（远低于 331K）、产出可编译代码、最终出分。
- 决策 4：incremental-developer 同投递该 skill（改存量场景）。
