# L1 问题记录 — TensorSpec.dtype 截断致多 dtype 信息丢失

## P1：requirement.json 声明多 dtype 支持，下游只收到首个 dtype

**现象**：run `20260721-063136-dc2210`（Exp 算子，self_evolve_op 全流程），`requirement.json` 声明 input/output
支持 `["fp16", "fp32", "bf16"]` 三种 dtype，但 `general-design-generator` 产出的 `general_design.json`
中仅支持 `fp16`，fp32 和 bf16 被标为"未来扩展"。

**证据链**：

1. `artifacts/requirement/requirement.json` — inputs/outputs dtype 为 `["fp16", "fp32", "bf16"]`
2. `artifacts/design/general-design-generator/requirement.json`（materialize 副本）— inputs/outputs
   dtype 为 `"fp16"`（单字符串，非列表）
3. `state_snapshot.json` 中 `requirement.op_spec.inputs[0].dtype` = `"fp16"`（单字符串）
4. `general_design.json` narrative §2.3 写明 "dtype：fp16（与现有 TilingKey 一致；未来扩展 fp32/bf16
   需新增 dtype 模板分支）"
5. review 阶段未发现此偏差（`general_design_reviewed.json` 中 `issues_found: 0`）

**根因定位**：`OperatorSpec.from_dict()` 在解析时检测到 `dtype` 是 list，取 `dtype[0]` 覆盖，
其余元素静默丢弃。此截断发生在领域模型解析层，信息在进入 `state.requirement` 之前已丢失。
prompt 注入的 `_requirement_summary` 和 materialize 到工作目录的副本都从 `state.requirement` 派生，
因此 agent 从两个渠道均只看到 `"fp16"`，无法感知原始需求中的多 dtype 声明。

**影响面**：任何多 dtype 算子（Exp、Add、Mul、Gelu 等）均受影响，非 Exp 个例。

**严重程度**：阻塞级 — 需求信息在解析层静默丢失，下游产物系统性缺功能，且无日志/告警信号。
