# 最终架构 — 设计阶段（最小结构 + 原地修改 + golden 兜底）

> 本文是 `design-gate-inplace-fix/` 的最终收敛（authoritative），取代此前所有版本（含三 layer / resume 阶梯 / checker / claim schema / 访问契约补丁——均已撤回）。
> 关联：`CLAUDE.md` §1.14（最小结构优先）、§1.13（golden 权威）、§2.9（就地修可修项）。
> `01-problems.md`（L1 证据）仍有效；`02/03/04` 的"checker/访问契约/回炉"方向已作废。

---

## 0. 决策摘要（一句话）

**设计阶段从「8 substage + 3 门 + loopback 回炉」改为「少数必要 agent + 一个 owner 型合成 agent + golden 兜底」，全程原地修改、无门、无回炉。**

---

## 1. 四条原则（对齐 CLAUDE.md §1.14）

| 原则 | 含义 |
|---|---|
| **最小结构** | 留「帮模型」的知识 +「框架骨架」；删「控模型」的结构（gate/checker/claim schema/回炉） |
| **R3 帮不控** | 给模型知识（API 约束/gather 范式），不加规则 |
| **原地修改** | 谁发现谁改、只改那一处、不重填表、不回炉 |
| **golden 兜底** | golden 比对是唯一不枚举错误类型的确定性判据，precision 阶段就地修 code |

---

## 2. 设计阶段结构：减 substage + 删门 + owner 型合成 agent

### 现状（过度拆分，删）

```
template-division → tiling[split→vf-design→buffer-kernel→precision-perf]
  → anchor(per-template) → anchor-consistency → integrate → docgen → validate
```

### 目标（减结构）

```
少数必要 agent（按模板 / 按职责，各自产出自己的部分，自检+原地自改）
  → 合成 agent（owner：组装 + 全面检查 + 发现不一致就原地改自己的合成产物）
```

### 三个硬决策

1. **删门**：review / anchor / validate 全部删除。它们存在唯一理由是"查跨 substage 一致性"，substage 减少后失去对象；且它们自身是 bug 源（branch 命名 / stale 复验 / discover+regenerate，见 `01-problems.md`）。

2. **合成 agent 必须是 owner，不是 gate**（关键精化）：
   - ✅ 对：合成 agent = 最终设计产物 owner，组装时发现 `buffer-kernel` 与 `precision-perf` 矛盾 → **就地改自己的合成产物** → 一致。
   - ❌ 错：合成 agent = gate，检查发现矛盾 → 报 issue → 回炉 producer → 又是 loopback（§1.14 反对）。否则"3 门合并成 1 门"，换汤不换药。

3. **无跨 stage/substage 修改**：每个 agent 只改自己的产物（P62 隔离不触碰）。跨边界不一致问题**消解**——因为边界少到不需要"跨边界改"：单 agent 内 = 构造性一致；少数 agent 间 = 合成 agent 组装时原地修（它是最终产物 owner）。

---

## 3. 三方案对比 + 决策

| 维度 | A：单 design agent | B：少数必要 agent + 合成 agent（选中） | C：8 substage + 3 门（现状） |
|---|---|---|---|
| 上下文峰值 | 极高（golden+知识+需求+完整产出） | 中：生产中；合成大但**无需知识** | 低 |
| 压缩风险 | **高**（超窗→有损丢信息） | 低-中 | 低 |
| 跨边界不一致 | 零 | 中（少数边界，合成收敛） | 高（8 边界+3 门） |
| 结构复杂度/错误面 | 最简 | 低-中 | **最高**（门+loopback+rerun_selector+gate_scope） |
| 并行性 | 无（串行） | 有（按模板） | 有（forkjoin） |
| 谁保证正确 | golden 兜底 | golden 兜底 + 合成原地修 | 门查（不可靠）+ golden 兜底 |

**决策：B**。它是"上下文压力"和"跨边界不一致"两个坏方向的平衡点——上下文比 A 小一整个知识库（合成 agent 查一致性不需知识），结构复杂度比 C 低得多（无门）。

**关键洞察**：B 把「生产（需知识）」和「检查（只需产物+golden）」分开——合成 agent 读「golden + 各 agent 已产出的结构化产物 + 需求」，**不装知识库**，所以上下文峰值比 A 低一档。

---

## 4. 上下文管理（三手段，与 B 正交）

压缩是有损的，任务固有大小超窗则压缩不可避免——**任何方案都不能"保证"不压缩**。能做的是最小化风险 + 让损害可诊断：

1. **知识按需检索，不整库加载**：`ascendc-dev-knowledge` 已按 INDEX 按需查；设计 agent 只查本算子相关范式（unique 查 sort、grid 查 gather），不把 212K 全塞上下文。
2. **结构化 checkpoint = 压缩只丢过程、不丢结论**：每个 agent 落盘 `decision_log.json` + 产物。压缩丢的是中间推理，结论已落盘，合成 agent 读落盘结论。
3. **压缩可观测**：`session.compacted` 事件 + `time_compacting` 列（实测存在于 opencode），框架感知"发生过压缩"而非静默。

---

## 5. 原地修改如何消解跨边界问题

| 错在哪层 | 谁发现 | 谁改 | 改谁的产物 |
|---|---|---|---|
| 设计错（bf16→fp16） | 设计 agent 自检（对照 golden） | 设计 agent 自己 | 自己的 design 产物 |
| 跨模板不一致 | 合成 agent（组装时） | 合成 agent 自己 | 自己的合成产物 |
| code 错 | codegen 编译自检 | codegen 自己 | 自己的 code |
| 残留错 | precision golden 比对 | precision 自己 | 自己的 code（就地修，design 略陈旧可接受） |

**全程"发现者 = 修复者 = 产物 owner"，无跨 stage/substage 修改，P62 隔离不触碰。**

---

## 6. golden 兜底（唯一不枚举的确定性判据）

- golden 是唯一权威（§1.13），比对一致即对、不一致就地修。
- 不靠枚举规则（错误类型无界，枚举 = 打补丁）；不靠"从 codegen 回设计"（动作太大、代价大）。
- 残留错在 precision 就地修 code，目标是"operator 与 golden 一致"，不追求"设计文档永远完美"。

---

## 7. 完成判据

1. 设计阶段无 review/anchor/validate 门（grep 断言）。
2. substage 减到少数必要 agent + 一个 owner 型合成 agent（组装+原地修，无 gate 语义）。
3. 全程无跨 stage/substage 修改（每 agent 只写自己产物）。
4. 上下文管理三手段落地（知识按需 / decision_log 落盘 / 压缩可观测）。
5. events.jsonl 实证 design 阶段零 loopback、产物可进 codegen。
6. 全量 UT + 非 heavy_llm ST 通过；operator 与 golden 一致。
