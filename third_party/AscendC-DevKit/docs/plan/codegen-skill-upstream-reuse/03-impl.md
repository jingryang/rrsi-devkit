# codegen skill 上游源中间产物复用 — 实施（L4）

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md`，事实见 `01-problems.md`。
> 核心原则：codegen 读**源中间产物**（State 字段），**不读派生的详细设计说明书**（§2.5）。

## 改动 1 — 重写 ascendc-op-dev-coding SKILL.md（skill 内容层）
`.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding/SKILL.md`：
- **输入契约表扩为源中间产物集**（02 决策3 表）：`general_design` / `template_division` /
  `tiling_results`（含 `buffer_kernel.kernel.pseudocode`）/ `design_spec` / `tiling_strategy` /
  `kernel_architecture` / `requirement` / `test_cases` / `reference_code` / `meta.json`。
  每项注明「来源 stage + codegen 翻译为哪层代码」。
- **实现蓝图来源**：实现蓝图读源 `tiling_results.buffer_kernel.kernel.pseudocode`（决策 2 已证其为蓝图源头）。
  防 agent 误以为缺蓝图而 grep CANN。
- **复用边界**：codegen = 分步翻译源中间产物为代码；需求分析/概设/详设/tiling/section/验收用例上游已定，
  复用不重做（不照搬 Phase C S2-analysis）。
- **分步翻译顺序**（对应源产物依赖序，落进 Step 4 编码顺序）：
  `general_design`+`template_division` → 骨架 → `tiling_results.kernel.pseudocode` → Kernel/Buffer →
  `design_spec`+`tiling_strategy` → Host Tiling/TilingData → `kernel_architecture` section → ACLNN/Plugin。
- **参考来源纪律**（强化既有 Step3，落 ①）：API 签名查 `ascendc-dev-knowledge` 知识库；禁 grep/cat
  `$ASCEND_TOOLKIT_HOME`、`/usr/local/Ascend/`；查不到用 `ascendc-tips`；仍查不到停下报告，不自搜参考实现。
  **补例外条款 + Why**：`reference_code`（上游显式注入的参考算子）读它受控可追溯（**该读**）；禁的是自行
  grep 目标仓 `ops/`/其他仓/SDK 头文件。Why：自搜抄来的实现产生"看似通过实则通路不符"虚假信号
  （历史 20/20 通过却迁移崩溃根因）。
- **② 字段↔源逐一对应自检**（落 Step6）：生成的 TilingData struct 字段（名/类型/数量）须与
  `tiling_strategy`/`tiling_results` 源字段清单逐一对应，缺失/不符→fail；权威源是 State 源字段（非派生文档）。
- **③ 锁定项入口校验 fail-fast**（落 Step2）：codegen 发现源中间产物缺必要字段（如 tiling 无 workspace
  预算、general_design 无 BUFFER_NUM 决策、design_spec 无 dtype 矩阵）时**停下报告**"上游缺 X"，
  不 grep CANN/不自搜/不猜测补全（§1.3 入口期校验 + §3.7 诚实报缺）。DevKit 无 high_risk_api_registry，
  故为 fail-fast 纪律 + 文档化字段期望，**不做 registry 查询**。

## 改动 2 — codegen._materialize_inputs 物化源中间产物（物化层）
`orchestration/stages/codegen.py` 的 `_materialize_inputs`：在既有 design_spec/tiling_strategy/
kernel_architecture/meta.json/reference_code 之外，**从 State 源字段物化**（best-effort，字段为空跳过，
同 reference_code 机制）：
- `state.tiling_results` → `tiling_results.json`（**关键**：含 kernel.pseudocode）
- `state.general_design` → `general_design.json`
- `state.template_division` → `template_division.json`
- `state.requirement` → `requirement.json`（dataclass → dict 序列化）
- `state.test_cases` → `test_cases.json`
> State 字段全局可读（run_context 注释：无 per-stage _upstream_inputs 声明，非传递丢失向量），codegen
> 直接读，不必扩 input_contract。物化是给 agent 一个 staging 绝对路径入口（既有 P4 机制）。

## 改动 3 — codegen prompt 输入文件清单（prompt 层）
`codegen.py` 的 `_build_codegen_prompt`「设计产物（输入文件）」section：把新增 staging 文件按
「源中间产物 → 翻译为哪层」列进去（与既有 design_spec/tiling_strategy 同格式，指 staging 绝对路径）。
新增一段「**实现蓝图优先级**」：先读 `tiling_results` 的 kernel.pseudocode（源），再 design_spec/
tiling_strategy（契约），API 查知识库，禁 grep CANN。

## 顺序
1. TDD 先写测试（见下）。
2. 改动 2（物化）→ 改动 3（prompt）→ 改动 1（skill 内容，最重）。
3. 跑测试至绿。

## 验证（TDD）
`tests/ut/orchestration/` 增 `test_codegen_upstream_reuse.py`：
- `test_materializes_source_intermediates`：带 tiling_results/general_design/template_division/requirement/
  test_cases 的 State → `_materialize_inputs` 后 staging 有对应 json（含 kernel.pseudocode 透传）。
- `test_skill_doc_declares_source_references`：SKILL.md 含源中间产物集 + 各自翻译为哪层代码
  （grep SKILL.md 文本，防回归漂移）。
- `test_skill_doc_has_reference_exception_clause`：SKILL.md 含 ① 例外条款（reference_code 受控读取 +
  禁自搜 + Why 关键词）。
- `test_skill_doc_has_field_source_correspondence`：SKILL.md 含 ② 字段↔源逐一对应自检。
- `test_skill_doc_has_locked_item_failfast`：SKILL.md 含 ③ 锁定项入口校验 fail-fast。
- 既有 codegen 用例不回归（6 个投递测试 + 物化不破坏既有 staging 文件）。
全量：`pytest -m "not heavy_llm"`，0 回归。

## 后续（不在本轮）
- 重跑 E2E moe_re_routing（heavy_llm，§3.11 跑前用户确认）：确认 codegen 读源中间产物（tiling_results
  kernel.pseudocode）而非 grep CANN、上下文有界、产出可编译代码、出分。
- 决策 4（codegen-skill-delivery）：incremental-developer 同投递该 skill（改存量场景）。
- 评估 `tiling_strategy` 与 `tiling_results` 是否冗余（tiling_strategy 是跨模板整合契约，tiling_results
  是每模板源含 pseudocode；本轮两者都喂，后续视 agent 实际消耗再精简）。
