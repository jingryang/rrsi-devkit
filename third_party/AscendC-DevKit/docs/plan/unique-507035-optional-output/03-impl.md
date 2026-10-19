# 03 — 实施方案（L4）：P2 可选输出契约改「Tensor[] 返回」

> 本工作：`docs/plan/unique-507035-optional-output/`。回答「改哪个函数、什么顺序、怎么验证」。
> 依据 `02-analysis.md` 冻结的方案 C + 用户拍板「cann-bench 仓不能改」「只做返回结构、不提 kernel 直调」。
> 实证锚点：`/home/x00584171/temp/unique` 的 plugin 用 `-> Tensor[]` + 条件 push 通过了 cann-bench 评测。

## 一、改动目标

把可选输出算子（proto `outputs[*].optional: true`，由输入参数控制是否返回）的 plugin 返回结构，从「固定元组 `-> (Tensor, Tensor?)` + 空占位」改成「`-> Tensor[]` + `std::vector<Tensor>` 条件 push」，使 raw op 返回数量随控制参数变、与 golden 一致。

- 判据是结构信号（proto OPTIONAL 输出 + 控制参数），不认算子名（§1.12）。
- 忠实 golden 返回语义（§1.13），构造性对齐（§2.9），删「裁剪 wrapper」死代码（§1.14/§2.5）。

## 二、改动清单

### 1. `SKILL.md` 维11 正文（`.claude/skills/ascendc-op-dev-coding/SKILL.md:337-357`）

**现状**：两层产出契约 =「内核层 schema 固定 `(Tensor, Tensor?)` + 调用入口层裁剪 wrapper」+「两套消费路径（①评测经 wrapper ②harness 经 raw op）」。

**改为**：
- 「内核 / 宿主层恒算全输出」保留。
- 「调用入口层裁剪 wrapper」→ 删，改为「plugin 层（raw op）schema `-> Tensor[]` + `std::vector<Tensor>` 条件 push」。
- 「两套消费路径」→ 删，改为单一 raw op 路径（评测层 `cann_matcher` 优先 `torch.ops` 调 raw op，裁剪 wrapper 是死代码；对齐必须落在 raw op 返回结构本身）。
- 自检 (d)/(e)：从「schema 可选输出显式带 `?` / `-> (A,B)` 定长元组对应 tuple」改为「可选输出算子 schema 用 `-> Tensor[]`，C++ 返回 `std::vector<Tensor>`，条件 push 数量随参数变」。
- 自检 (a)/(b)/(c) 语义不变（对齐 golden / 无空占位冒充省略 / plugin 无算子内部逻辑），措辞从「裁剪逻辑」改为「条件 push」。

### 2. `SKILL.md` 维11 表格行（`.claude/skills/ascendc-op-dev-coding/SKILL.md:334`）

同步改表格描述：删「调用入口层必须做输出裁剪」「schema 声明 `?`」，改为「raw op schema `-> Tensor[]` + 条件 push，禁固定元组 + 空占位」。

### 3. `SKILL.md` 维5b 引用（`.claude/skills/ascendc-op-dev-coding/SKILL.md:317`）

维5b 两处引用「可选性只表达在 torch schema `-> (Tensor, Tensor?)` + plugin 返回层（absent → `c10::nullopt`）」「可选性归 schema `Tensor?` + plugin 返回 None」→ 改为「`-> Tensor[]` + plugin 条件 push」。

### 4. `cannbench_adapt.py`（`src/ascendc_devkit/adapters/evaluation/cannbench_adapt.py`）

删「保留 codegen 裁剪 wrapper」这条已废弃的机制（对象消失）：
- `_existing_contract_wrapper`（104-118）
- `_is_pure_pass_through`（74-89，仅被 `_existing_contract_wrapper` 调用）
- `_calls_forward_target`（92-101，仅被 `_existing_contract_wrapper` 调用）
- `generate_and_inject_wrapper` 里的保留逻辑（233-240：`preserved = _existing_contract_wrapper(...)` + 跳过注入）
- 63 行 docstring 里对 `_is_pure_pass_through` / `_calls_forward_target` 的引用注释

保留：`_build_wrapper`（确定性直通 wrapper 生成，仍用于非条件输出算子）+ `_inject_wrapper_block` + `generate_and_inject_wrapper` 的直通注入主路径。

### 5. UT `test_cannbench_adapt_schema.py`

删 `TestPreserveCodegenContractWrapper` 类（153-203：`test_detects_non_pass_through_trimming_wrapper` / `test_pass_through_wrapper_not_preserved` / `test_comment_mentioning_target_not_preserved` / `test_assignment_call_wrapper_preserved`）+ `test_generate_inject_preserves_codegen_wrapper`（205 起）+ import `_existing_contract_wrapper`（37 附近）。

### 无需改（已确认）

- **harness `_normalize_outputs(out, proto_len)`**（`_harness_template.py:100-112`）：非 tuple/list 包单元素、右补 None 到 proto_len，对 `Tensor[]` 返回（`[y]`/`[y, inverse]`）天然兼容，无需改。
- **cann-bench 评测层**：不改（用户约束）。

## 三、验证

- **UT**：全量 `tests/ut/` 绿——**3616 passed / 0 failed**（`--no-env-check`）。重点确认：
  - 删 `_existing_contract_wrapper`/`_is_pure_pass_through`/`_calls_forward_target`/`_is_cann_bench_call` 后**全仓零残留引用**（grep 确认）。
  - 删「保留裁剪 wrapper」后，`generate_and_inject_wrapper` 退化为「读 existing + `_inject_wrapper_block`（替换/追加）」，该行为由 `TestGenerateWrapper`（W2 错版→替换 / W3 无→追加 / 幂等）与 `TestInjectWrapperBlock`（AST 定位替换 robustness）**充分覆盖**。
- **skill 一致性**：grep 全仓确认无残留旧措辞；维11 正文/表格行/维5b 引用已同步为 `-> Tensor[]` + 条件 push。
- **UT/ST 覆盖结论（是否需要补）**：
  - **UT 不需补**：删的 5 个测试测的是「保留裁剪 wrapper」这一**已删除行为**；删后新行为「总是注入/替换」由上述「错版→替换」测试覆盖，是行为替换、测试随之替换，非留空白。
  - **ST/heavy_llm 不需补（本次）**：改动是确定性逻辑删除 + skill 措辞，不涉及 LLM/NPU 真实链路（§3.9 不触发）。
  - **可选的 heavy_llm 验证**（非本次回归覆盖）：用「可选输出」结构（非 unique 特判）复现 codegen 生成 `-> Tensor[]` + 条件 push，验证 skill 引导生效——属 §3.11 用户决策项，不默认跑。
