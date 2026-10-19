# A5 Regbase codegen — in-place/out-of-place 交付契约 handoff（step-4）

> **归属**：A5 codegen（`ascendc-op-dev-coding-regbase` → s4-coding）归同事维护。本文件是 handoff，**不直接改 A5 skill**。
> **上下文**：本工作事实见 `01-problems.md`、方案见 `02-analysis.md`（已冻结）、A2/A3 实施见 `03-impl-mutation-mode.md`（step-1~3 已落地于 req-analysis / design-integrate / dev-coding）。

## 背景（一句话）

生成的 plugin 做成真 in-place（`m.def ... -> ()` + `copy_()` 写回调用方原张量本体），违背 cann-bench **out-of-place 返回交付契约**（golden 全 `clone()+return`，且 golden/AI run 共享输入——真 in-place 会污染对方）。根因：requirement/design 缺算子写法特性维度。已在 requirement 新增 `mutation_mode`、design 继承、A2/A3 codegen 消费（clone+return）。**A5 codegen 需同步**。

## A5 侧落点

`ascendc-op-dev-coding-regbase` 是编排器，plugin 实际生成在 **s4-coding 分层编码**（regbase SKILL.md:324 `op_plugin` 目录、:341 `plugin_code` section 声明但缺文件 → 派 s4-coding 补全）。需在 s4-coding 的 **plugin 分层引导**里应用下述规则。具体引导文件落点由同事定位（regbase SKILL 或 s4-coding agent 的 plugin 段）。

## 要应用的规则（与 A2/A3 dev-coding step-3 完全等价）

读 `design_spec.mutation_mode`：

- **框架级通用约定**：所有算子 plugin 一律 **out-of-place 返回交付**。
- `in_place`：对每个**同名 input-output 状态张量**（per-tensor 读写由 inputs/outputs 同名关系隐式定义：同名=read_write）**强制 `.clone()`** 作 output（**禁用 `.contiguous()` 充当 clone**——已连续时返回 view 非副本）；clone 同时作 aclnn 的 input 与 output（维持 aclnn 内部 in-place alias 语义，kernel 零改动）；`m.def` 返回值 == 所有 output（非 `-> ()`）；**禁止 `copy_()` 写回调用方原张量本体**。
- `out_of_place`：output 与 input 不同名（独立），直接 return output，无需 clone。

## plugin 正确形态（in-place 示范，与算子无关）

```cpp
// mutation_mode == in_place 的算子：同名状态张量 clone 后 return
static std::tuple<torch::Tensor, /*...outputs...*/> op_npu(
    const torch::Tensor& x /*in-place 状态张量*/, /*其它纯输入...*/) {
    auto out_x = x.clone();                         // 强制 clone，禁 contiguous()
    /*纯输入 contiguous*/
    ACLNN_CMD(aclnnOp, out_x, /*纯输入*/, out_x);   // clone 同时作 input+output（aclnn alias 语义不变，kernel 零改动）
    return {out_x, /*...*/};                        // out-of-place 返回交付
}
// m.def: op(...) -> (Tensor, ...)   // 非 -> ()
```

## 边界（重要）

plugin 层是 **host 侧 torch 绑定**（`TORCH_LIBRARY_FRAGMENT` + meta/npu 实现），与 A5 的 **VF/SIMT 编程模型无关**——交付契约规则跨 A2/A3/A5 通用，**不涉及 VF 红线**（九条 A5 Regbase 约束限定的是 Vector 执行域内，plugin 不在其内）。故本规则可直接套用 step-3 的 dev-coding 规则，无需为 A5 编程模型做特例。

## 验证

A5 侧落地后，任选一个 A5 in-place 算子重跑 codegen，断言 plugin 形态：`m.def` 返回所有 output、用 `.clone()` 非 `.contiguous()`、无 `copy_` 写回本体。func 全分仍依赖各算子 kernel 自身精度（本工作只保证交付契约）。
