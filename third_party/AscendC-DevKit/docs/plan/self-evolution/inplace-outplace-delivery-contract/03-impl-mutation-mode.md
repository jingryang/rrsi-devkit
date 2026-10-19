# in-place/out-of-place 交付契约 — 实施方案（L4）

> 层级：**L4 实施方案**。具体改哪个 skill 哪一节、字段定义、校验写法、plugin 形态、验证方式。
> 事实见 `01-problems.md`，方案取舍见 `02-analysis.md`（已冻结：删 access_mode、留 mutation_mode、per-tensor 读写归同名关系）。

## 步骤索引（本工作导航）

| 步骤 | 主题 | 覆盖 | 状态 | 依赖 | 归属 |
|---|---|---|---|---|---|
| step-1 | req-analysis：删 `access_mode` + 加算子级 `mutation_mode` + §1.3 校验 + 判定规则 | P1 | ✅ 已完成 | — | req-analysis（确认用户侧） |
| step-2 | design-integrate：继承 `mutation_mode` + 删 `io` 文字 + per-tensor 读写归同名关系 | P1 | ✅ 已完成 | step-1 | design |
| step-3 | dev-coding(A2/A3)：Plugin 层 clone+return 规则 + 同名=read_write 映射 | P1 | ✅ 已完成 | step-2 | codegen A3 |
| step-4 | dev-coding-regbase(A5)：同 step-3 规则，handoff 同事 | P1 | 📄 handoff 文档已产出（`04-handoff-a5-regbase.md`），A5 未动 | step-2 | ⚠️ handoff |
| step-5 | 验证 | P1 | ✅ UT 2731 passed + req-analysis selfclosure ST PASSED；codegen 端到端待 PR 前（`05-codegen-verify-checklist.md`） | step-1~3 | — |

> **as-built**（commit `9393b1b8`，2026-07-24）：step-1~3 + 自洽校验已落地；`ascendc-op-req-analysis` 归属确认为用户侧。
> step-4（A5）按用户指示暂不动，handoff 文档（`04`）留作同事未来交接。
> step-5 codegen 端到端（clone+return plugin 形态）无自动化 ST（完整 design fixture + ~27min heavy，成本过高），保留 `05` 手动清单作 PR 前验证路径。

---

## 字段定义（mutation_mode 规范）

写进 `.claude/skills/ascendc-op-req-analysis/references/op_spec_schema.md` 顶层 properties：

```json
"mutation_mode": {
  "type": "string",
  "enum": ["in_place", "out_of_place"],
  "description": "算子写法特性（必填）。in_place: 存在与 input 同名的 output（状态张量原地更新）；out_of_place: output 与 input 不同名（独立输出）。决定 plugin 交付契约：in_place 算子的同名状态张量须 clone 后 return。per-tensor 读写与之正交——由 inputs/outputs 同名关系隐式定义，不单列 access_mode。"
}
```

**per-tensor 读写映射**（确定性，写进 design/codegen skill 作核心引导，§2.7）：

| inputs/outputs 关系 | per-tensor 访问 |
|---|---|
| 同名出现在 inputs 和 outputs | `read_write`（状态张量） |
| 只在 inputs | `read_only` |
| 只在 outputs | `write_only` |

---

## step-1 — req-analysis skill

文件：`.claude/skills/ascendc-op-req-analysis/`

1. **`references/op_spec_schema.md`**：顶层加 `mutation_mode`（见上）；**删除** per-tensor `access_mode`（line 107）的定义与示例。
2. **`schema/requirement.json`**：
   - `required_keys` 加 `mutation_mode`（当前为 `["op_name","inputs","outputs"]`）。
   - 加 §1.3 自洽校验：
     - `mutation_mode == "in_place"` ⇔ ∃ output.name ∈ inputs.name（存在同名对）
     - `mutation_mode == "out_of_place"` ⇔ ∀ output.name ∉ inputs.name（无同名对）
     - 不符 → 加载期告警/报错。
3. **`SKILL.md`**：加判定规则 —— requirement-analyst 判定 `mutation_mode` 的依据：
   output 与 input 同名 / golden 对输入做 clone 后 return / 有 read_write 状态张量 ⇒ `in_place`；否则 `out_of_place`。
   判定有结构化依据（同名关系），不纯靠 LLM 理解（§1.3）。

## step-2 — design-integrate skill

文件：`.claude/skills/ascendc-op-design-integrate/SKILL.md`

1. **IO 契约对齐步骤**（当前 line 51-55 描述按 name 并入 `param_type` 等）：扩展为同时把 requirement 的 `mutation_mode` 并入 design_spec 顶层。
2. **删除 `io` 文字字段**：design_spec 的 inputs/outputs 不再写 `"io": "in-place (writeback)"` 这类非 schema 文字
   （§2.5 唯一通路 + §1.4 不留旧债）。per-tensor 读写改从 inputs/outputs 同名关系读。
3. **区分两层**：kernel 计算语义（in-place 读写，从同名关系）vs plugin 交付契约（从 `mutation_mode`）——
   在 design_spec 显式承载 `mutation_mode`，供 codegen 构造性消费（§2.9）。

## step-3 — dev-coding skill（A2/A3）

文件：`.claude/skills/ascendc-op-dev-coding/SKILL.md`，「ACLNN API 层 / Plugin 层 核心质量要求」节（line 179 附近）补规则：

> **In-place 算子（`mutation_mode=in_place`）的 plugin 交付契约**：
> - 读 design 的 `mutation_mode`；对每个同名 input-output 状态张量**强制 `.clone()`**（**禁用 `.contiguous()` 充当 clone**——已连续时返回 view 非副本）作 output；
> - **禁止 `copy_()` 写回调用方传入的原张量本体**（cann-bench golden/AI 共享输入，真 in-place 会污染）；
> - `m.def` 返回值 == 所有 output（out-of-place 返回交付）；
> - aclnn/kernel 层 in-place 计算保持不变（clone 同时作 input+output 传给 aclnn，维持 alias 语义，kernel 零改动）。
> - 框架级通用约定：所有算子 plugin 一律 out-of-place 返回交付（cann-bench golden 全 clone+return）。

### plugin 正确形态（advance_step_v2 示范）

```cpp
static std::tuple<torch::Tensor, torch::Tensor, torch::Tensor, torch::Tensor>
advance_step_v2_npu(const torch::Tensor& input_tokens, const torch::Tensor& sampled_token_ids,
                    const torch::Tensor& input_positions, const torch::Tensor& seq_lens,
                    const torch::Tensor& slot_mapping, const torch::Tensor& block_tables,
                    const torch::Tensor& spec_token, const torch::Tensor& accepted_num,
                    int64_t num_seqs, int64_t num_queries, int64_t block_size) {
    // mutation_mode=in_place：4 个同名状态张量强制 clone（交付副本，不污染调用方输入）
    auto out_tokens    = input_tokens.clone();
    auto out_positions = input_positions.clone();
    auto out_lens      = seq_lens.clone();
    auto out_slot      = slot_mapping.clone();
    // 纯输入（read_only）contiguous
    auto sampled = sampled_token_ids.contiguous();
    auto bt = block_tables.contiguous(), st = spec_token.contiguous(), an = accepted_num.contiguous();
    // aclnn 保持原 in-place alias 语义：clone 同时作 input 和 output（kernel 一行不改）
    ACLNN_CMD(aclnnAdvanceStepV2,
              out_tokens, sampled, out_positions, out_lens, out_slot, bt, st, an,
              num_seqs, num_queries, block_size,
              out_tokens, out_positions, out_lens, out_slot);
    return {out_tokens, out_positions, out_lens, out_slot};
}
// m.def: advance_step_v2(...) -> (Tensor, Tensor, Tensor, Tensor)
```

## step-4 — dev-coding-regbase（A5）handoff

`ascendc-op-dev-coding-regbase` 是编排器，plugin 实际生成在 s4-coding subagent（归同事）。
产出 handoff 文档，交付与 step-3 等价的规则（mutation_mode 消费 + clone+return + 同名=read_write 映射），
指明 s4-coding 的 plugin 生成落点。**不直接改**（记忆：A5 codegen 归同事）。

## step-5 — 验证

- **UT**：req-analysis schema 校验 —— `mutation_mode` 必填 + 自洽（in_place⇔同名对）。
  构造 out_of_place / in_place 两类 fixture（如 add=outs-pace、advance_step_v2=in-place）断言通过/拒收。
- **ST**（属 heavy_llm，跑前确认）：重跑 advance_step_v2 codegen，断言 plugin 形态：
  `m.def` 返回 `(Tensor×4)`、用 `.clone()` 非 `.contiguous()`、无 `copy_` 写回本体。
- **边界说明**：func 全分仍依赖 kernel int64 精度 bug（P1 之外的独立问题，见 `batch-20260721-8b790c-issues-handoff.md`）修复；
  本工作只保证交付契约正确（plugin 不再真 in-place、不污染共享输入），不保证 func=满分。

---

## 实施顺序与依赖

step-1（req-analysis，**阻塞于归属确认**）→ step-2（design-integrate）→ step-3（dev-coding A2/A3）→ step-5 验证；
step-4（A5 handoff）与 step-3 并行（独立交付同事）。每步完成后更新本表状态 + `02-analysis.md` 无需改（已冻结）。
