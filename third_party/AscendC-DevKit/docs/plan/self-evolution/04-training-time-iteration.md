# training-time 迭代方案 — self-evolution 的训练闭环

> **性质**：self-evolution 线工作记录（L3），承接 `01`/`02`/`03`（inference-time 基建）。
> **核心命题**：01/02/03 是 inference-time（单算子生成+评测+并发隔离）；**training-time 是 self-evolution 的灵魂**——跨算子用 loss 反哺改"模型"、验 loss 下降。前者是后者的基建；不设计 training-time，前三份方案意义悬空。
> **纪律**：遵守 `plan-doc-discipline`；本文聚焦设计决策，不展开实现（留 L4）。

---

## 1. 训练循环（外层，内层调 inference-time）

```
for epoch:
  1. 推理评测：训练集每算子跑 inference-time 闭环（01/02/03）→ 各算子 loss（overall_score 三维度）
  2. 聚合：全算子 loss → training loss（epoch 级）
  3. 归因：失败算子共因分析 → 定位"模型"该改的部位
  4. 改进：改"模型"（低风险优先，见 §2）
  5. 验证：下 epoch 再评测；loss 不降 → 回滚改动 + 标记
收敛：loss < 阈值 或 连续 N epoch 无改善 → 停止 / 人工介入
```

## 2. "模型"边界 + 风险分级（改什么）

"模型" = 生成能力 = skill + agent + 框架 + 资源。改进对象分级（决定 training-time 优先改什么）：

| 对象 | 风险 | 说明 |
|---|---|---|
| resources 知识库 | 最低 | 补算子知识，不改逻辑/提示 |
| skill prompt 引导（SKILL.md） | 低 | 改核心质量引导（CLAUDE.md 2.7 范围内） |
| agent manifest（`.claude/agents/`） | 低中 | 改 agent 的 skill/工具/权限 |
| 框架 Python（stage/workflow） | **高** | 改编排逻辑，回归风险大 |

**原则**：training-time 优先改低风险对象（resources/skill/agent）；框架 Python 谨慎（人工 review + 回归集，见 `human-review-as-stage`）。

## 3. 归因（training-time 的"梯度"）

失败模式 → 改进对象映射（规则骨架）：

- 编译失败多 → codegen skill prompt / resources API 知识
- 精度失败多 → kernel 逻辑引导 / tiling 知识
- 性能不足多 → tiling 策略 / 性能优化知识
- 流程失败（部署/评测）→ 框架 stage（高风险）

**策略**：LLM 归因为主（喂失败错误 + 当前 skill/agent 内容，分析共因提改进；吸收非确定性但不得退化成 mock，类比测试原则 3.10）+ 规则兜底 + 人工关卡（防跑偏）。

## 4. loss 聚合 + 收敛 + 回归保护

- **loss** = 全算子 `overall_score` 聚合（编译/功能/性能三维度加权；权重视训练目标）。
- **收敛**：loss 趋势下降；连续 N epoch 无改善 → 停 / 人工。
- **回归保护**（铁律）：训练集 = 回归集，每次改"模型"后**全量评测**；loss 不降或某算子退化超阈值 → 回滚改动（防"修好 A 搞坏 B"）。
- **过拟合**：训练集（phase0 35 算子）改 skill 可能过拟合 → 留验证集（cann-bench 更多算子）定期验泛化。

## 5. 与 inference-time 的关系

training-time 是外层 epoch 循环；每 epoch 内调 inference-time（`01`/`02`/`03` 的生成→部署→评测）跑全算子 + 收 loss。改进发生在 epoch 间（改"模型"），下 epoch 用新"模型"再推理。`01`/`02` 的并发隔离让单 epoch 的全算子评测高效。

---

## 6. 待定

- 改进自动化程度（全自动改 skill vs 人工辅助）
- 验证集选型（cann-bench 哪些算子作泛化验证）
- 收敛阈值 / epoch 上限
- 归因→改进的 LLM prompt 设计（L4）
