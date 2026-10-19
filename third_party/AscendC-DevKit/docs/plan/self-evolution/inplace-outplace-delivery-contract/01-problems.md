# in-place/out-of-place 交付契约缺失 — 问题记录（L1）

> 层级：**L1 问题/需求记录**。只陈述客观事实（哪里坏了、凭什么这么说），不提方案、不排顺序、不写决策。
> 方案见 `02-analysis.md`，实施见 `03-impl-mutation-mode.md`。

## P1 — 生成的 plugin 是真 in-place，违背 cann-bench out-of-place 返回交付契约

### 现象（生成产物）

算子 `advance_step_v2`（run `output/20260721-010537-7c6361/`，batch 8b790c）生成的 plugin
（`artifacts/codegen/op_plugin/advance_step_v2_plugin.cpp`）是真 in-place：

- `m.def("advance_step_v2(...) -> ()")`（line 108-112）—— torch 接口返回空，不通过返回值交付输出。
- `advance_step_v2_npu`（line 64-105）返回 `void`；用 `.contiguous()`（line 76-83）而非 `.clone()` 取副本
  —— 已连续张量时 `contiguous()` 返回 view 非副本；随后 `copy_()`（line 93-104）把结果写回用户传入的原张量本体。
- `codegen/decision_log.json` line 51 明文记录这是有意为之：
  > "In the common case (already-contiguous tensors) the in-place write is directly visible to the caller (no copy)."

### 凭据（cann-bench 的契约是 out-of-place 返回）

cann-bench 权威定义（`cann-bench/tasks/level2/advance_step_v2/`）三方一致要求 out-of-place 返回交付：

- `desc.md` §3 接口原型 + §6 调用示例：`(input_tokens, input_positions, seq_lens, slot_mapping) = cann_bench.advance_step_v2(...)` —— 按返回值 unpack。
- `golden.py`：`clone()` 4 个状态张量 → 在 clone 上算 → `return` 4 个 clone。注释明说设计意图：
  > "The evaluator may share input tensors between golden and AI runs, so in-place updates here would otherwise pollute the AI inputs."

即 cann-bench 要求算子**不污染共享输入、靠返回值交付结果**；生成的真 in-place plugin 既违背返回契约，又会污染 golden/AI 共享输入。

### 凭据（契约在 requirement→design→codegen 传递中丢失）

- **requirement.json**（`artifacts/requirement/`）：`schema` 字面含 `-> (Tensor input_tokens, …)`（out-of-place 返回藏在字面里），
  但同文件 `shape_constraints/output_shape_formula` 写"原位更新"、inputs 标"输入/输出张量" —— **三处描述自相矛盾，且无显式交付契约字段**。
- **design_spec.json**（`artifacts/design/integrate/`）：顶层 keys 为 `op_name, op_type, …, inputs, outputs, attrs, dtype, data_flow, platform`，
  **无任何交付契约字段**；outputs 全是 `"io": "in-place (writeback)"` —— out-of-place 返回契约在 requirement→design 传递中**彻底丢失**。
- **codegen**（`artifacts/codegen/codegen_manifest.json`）：`outputs` 带 `"alias_of": "input_tokens"` 等字段，
  把"output 与 input 存储共享 alias"当成正确目标；codegen 直接输入是 design（只有 in-place），自然生成 in-place plugin。

### 凭据（access_mode 机制存在但未贯穿）

requirement schema（`.claude/skills/ascendc-op-req-analysis/references/op_spec_schema.md` line 107）已定义
per-tensor `access_mode: read_only | write_only | read_write`，但实际 design 产物用的是**非 schema 的 `io` 文字字段**
（"in-place read_write"），`access_mode` 既未被 design 继承、也未被 codegen 消费 —— 机制有半个，没贯穿。

### 与 func=0 的关系（客观边界，避免混淆）

- 该 run 的 eval 结果（`cann-bench-batch/20260721_090523/advance_step_v2/reports/advancestepv2_eval_20260721_124415.json`）：
  `compilation_score=20.00`、`function_score=0.00`。
- **func=0 的直接元凶是另一个独立 bug**：`input_positions/seq_lens/slot_mapping` 几乎 100% mismatch（int64 整数运算、容差 0、要求精确相等），
  属 kernel 整数索引逻辑算错，与 in-place/out-of-place 交付契约**不是同一回事**。
- 本工作（P1）只解决交付契约；kernel 精度 bug 的跟踪见 `batch-20260721-8b790c-issues-handoff.md`（advance_step_v2「20 分精度发散」）。

### 影响面（为什么是真问题，不止当前一例）

in-place/out-of-place 是算子的标准写法特性（同类：AdamW / apply_adamw / scatter_ 等 in-place 语义算子）。
当前 requirement/design 无显式写法特性维度，codegen 每次靠从 design 的 `io`/`alias_of` 文字外推，**同类 in-place 算子必复发**。
