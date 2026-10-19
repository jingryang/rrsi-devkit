# L4 — 减 substage + 删门 实施评估（合并边界 + 合成 agent 契约）

> 依据：`05-final-architecture.md`（最终架构）+ `CLAUDE.md` §1.14（最小结构）。
> 本文是 L4 评估：盘点现状 → 定合并边界 → 定合成 agent 契约 → 列影响面 → 给实施顺序。**评估完再动手**，本文件不含最终代码。

---

## 0. 现状盘点（13 个 stage，4 个门）

| stage | skill | 角色 | 处置 |
|---|---|---|---|
| general-design-generator | ascendc-op-general-design | 概设 | 合并 |
| **general-design-review** | ascendc-op-general-design-review | **门** | **删** |
| template-division | ascendc-op-design-template-division | 模板切分 | 合并 |
| tiling/split | ascendc-op-tiling-split | 核间切分 | 合并（per template） |
| tiling/vf-design | ascendc-op-tiling-vf-design | A5 VF 编排（A3 自跳） | 合并 |
| tiling/buffer-kernel | ascendc-op-tiling-buffer-kernel | Buffer+Kernel 伪代码 | 合并 |
| tiling/precision-perf | ascendc-op-tiling-precision-perf | 精度+性能 | 合并 |
| **anchor-per-template** | ascendc-op-design-anchor-per-template | **门** | **删** |
| **anchor-consistency** | ascendc-op-design-anchor-consistency | **门** | **删** |
| integrate | ascendc-op-design-integrate | 聚合 | 合并为合成 agent |
| docgen | ascendc-op-design-docgen | 文档 | 并入合成 agent |
| **validate** | ascendc-op-design-validate | **门** | **删** |
| dd-intake | ascendc-op-design-intake | --detailed-design 短路 | 保留 |

---

## 1. 合并目标（13 → 4+N stage，N=模板数）

```
概设 agent      = general-design-generator（保留独立，暂不合并）
模板切分 agent   = template-division（保留独立，暂不合并）
tiling agent（×N）= split + vf-design + buffer-kernel + precision-perf（每模板一个，编排层合并：一个会话 tail-call 4 skill）
合成 agent      = integrate + docgen（owner：组装 + 检查 + 原地修 + 文档）
dd-intake       （保留，短路专用）
```

- 单模板 5 stage；双模板（grid_sampler_3d）6 stage（从 13 降下来）。
- **合并的收益**：跨 segment 不一致（buffer-kernel vs precision-perf，正是 anchor 抓的错）**构造性消解**——同一 agent 一个上下文里写完整 tiling，不可能自相矛盾到需要跨边界修。

**串行合并、并行保留（关键边界）**：

| 拆分 | 性质 | 收益 | 副作用 | 处置 |
|---|---|---|---|---|
| 模板内部（split→vf→buffer→precision） | **串行链**（无并行，依次跑） | 无墙钟收益 | 产生跨段不一致 | **合并**（4 段 → 1 agent） |
| 模板之间（T1 vs T2） | **并行**（ForkJoin 同时跑） | 有墙钟收益（多模板省时） | 无（各模板独立） | **保留**（ForkJoin 并发） |

- **不同模板不合并**：仍是独立 branch，ForkJoin 并发跑（起 N 个并发 agent）。
- **agent 总数 4N → N**（4 倍减少），但并发路数仍 N（墙钟收益不丢）。

---

## 2. 合成 agent 契约（owner，不是 gate）

| 项 | 内容 |
|---|---|
| **输入（读）** | golden + requirement + 概设产物 + N 个 tiling 产物的结构化输出 |
| **输出（写）** | `design_spec.json` + `tiling_strategy.json` + 详细设计说明书（docgen 并入） |
| **职责** | 组装 → 检查跨模板一致性（TilingKey 路由 / workspace 分配 / dtype 路由）→ **发现不一致就地改自己的合成产物** → 生成文档 |
| **禁止** | 报 issue → 回炉 producer（那是 gate，不是 owner） |

**判据**：合成 agent 的产物是最终设计产物的唯一 owner；它的"检查"是"组装过程中发现就改"，不是"只读查完报给上游"。

---

## 3. 影响面（skill / agent / code / config / test）

### 3.0 先迁移、后删除（关键顺序，防漏迁）

删门 ≠ 丢知识。门的 **agent manifest 是通用工作流（无可移植领域知识）**，但 **skill 里有领域知识（检查标准 / 硬件真值表 / 一致性规则）必须迁走**——否则删 skill 就把知识一起删了。

**迁移映射表**：

| 删的门 skill | 有价值的领域知识 | 迁往 |
|---|---|---|
| ascendc-op-general-design-review | CR1 四字段非空 + 对齐 golden 的 nan_semantics/boundary_handling/空输入 | 概设 agent 的 skill（加产出约束 + 自检清单） |
| ascendc-op-design-anchor-per-template | 硬件 API 真值表（bf16 指数域 8位 vs fp16 5位 / int64 chunk ≤24 / API 存在性 / hw 常量） | tiling agent 的 R3 知识（api-best-practices）+ 自检 |
| ascendc-op-design-anchor-consistency | 跨模板一致性（TilingKey 路由完备 / workspace 不重叠 / dtype 路由） | 合成 agent 的组装检查清单 |
| ascendc-op-design-validate | schema 校验 + GV10-a TilingData 旧宏→POD struct 机械重写 + GV7-B 公式↔伪代码对齐 | 合成 agent（schema/公式）+ tiling agent（TilingData struct） |

**原则**：删门 = 把"门替 producer 检查"的职责还给 producer 的"自检"，领域知识迁进 producer skill 作为"产出约束 + 自检项"（§2.9 自检闭环 + §1.14 帮不控）。

**反向提醒**：anchor 的 `disallowed_tools: [Write, Edit, Glob]` 是"只读门"强制约束，随 manifest 删除而消失——需确认无残余逻辑依赖"anchor 只读"假设（删 manifest 时的连带清理项）。

**实施顺序约束**：每删一个门，**先迁移其领域知识 → 再删 skill/manifest/code/config/test**（迁移在前，删除在后，不可颠倒）。

### 3.1 删（4 门 + 配套）

- **skill**：`ascendc-op-general-design-review`、`ascendc-op-design-anchor-per-template`、`ascendc-op-design-anchor-consistency`、`ascendc-op-design-validate`（4 个）+ 各自 `schema/gate_scope.json`。
- **agent**：`ascendc-design-reviewer`、`ascendc-design-anchor`（2 个 manifest）。
- **code**：`design_substages.py` 删 4 个 gate Stage 类；`design_tree.py` 删 gate 节点 + transition table 的 corrective 边（`redo_generator`/`infeasible→tiling`/`redo_tiling`）。
- **config**：`orchestration-config.json` 删 4 个 gate 的 stage_skill_map 条目 + `tail_calls` 里的 feedback-selfcheck（若无消费者）。
- **test**：`test_anchor_closure.py`、`test_validate_gate_scope.py`、`test_validate_skill_scope_contract.py`、`test_tiling_precise_rollback.py`（rerun_selector 若不再被 design 组用）、`test_anchor_forkjoin.py`（Step 1 修的分支命名，若 anchor 删了则此测试一并删）。

### 3.2 合并（producer 合并）

- **概设 agent**：`ascendc-op-general-design` + `ascendc-op-design-template-division` → 一个 agent（策略级连续决策）。
- **tiling agent**：4 个 tiling skill → 一个 agent（每模板）。
- **合成 agent**：`ascendc-op-design-integrate` + `ascendc-op-design-docgen` → 一个 agent。

**合并方式（待拍板，见 §5）**：skill 层合并（新建合并 skill）vs 编排层合并（一个 agent 串行 tail-call 多个现有 skill）。

### 3.3 保留

- `dd-intake`（--detailed-design 短路）。
- `graph_executor.py` 的 loopback 机制（precision/perf 仍用，只是 design 组不再接线）。
- Step 1 的 branch 命名修复——**若 anchor 删除则此修复连同测试一并作废**（不再有 anchor forkjoin）。

---

## 4. 实施顺序 + 验证（TDD，每步跑绿再进）

| 步 | 内容 | 验证 |
|---|---|---|
| 1 | 删 4 门（skill/agent/code/config/test） | UT 全绿；design 组无 gate 节点（grep 断言）；transition table 无 corrective 边 |
| 2 | 合并 tiling 4 段 → 每模板 1 agent | UT：tiling 分支 = 1 AtomicStage；ST：单模板算子 tiling 产出完整 |
| 3 | 合并概设 + 模板切分 | UT：概设组 = 1 节点；ST：策略级连续产出 |
| 4 | 合并 integrate + docgen → 合成 agent（owner） | UT：合成 agent 契约（输入/输出）；ST：跨模板不一致被就地修而非回炉 |
| 5 | 端到端验收 | events.jsonl 零 loopback、产物进 codegen、operator 与 golden 一致 |

---

## 5. 拍板结论（已冻结）

1. **合并方式 → 选 B（编排层合并）**：保留 4 个 tiling skill，一个 agent 串行 tail-call。核心理由（不止"改动小"）：**保住 per-skill 的 schema 文件 checkpoint = 压缩免疫粒度**（§6.7）——skill 越独立、schema 越细，上下文压缩后能找回的结论越多；A（skill 层合并）会粗化 checkpoint 粒度。先删门、合并编排，不急着改 skill。
2. **概设 + 模板切分 → 暂保留独立**：不真合并，先只做"删门 + 合成 agent"最小一刀。模板切分是概设的形式化派生，日后若要减结构可再评估真合并。
3. **Step 1 修复 → 随删门一并删除**：anchor 删除后 `_anchor_branch_factory` 死变量修复失去对象，连同 `test_anchor_forkjoin.py` 在删门 step 一并清掉。

---

## 6. 关键边界与易漏点（排查补充）

### 6.1 合成 agent 的"最终裁决"边界

合成 agent 是 design_spec/tiling_strategy 的 owner，发现上游不一致时**只在自己产物里选正确解释、不回炉上游**。但它只能兜「解释冲突」，**兜不了「上游缺失」**（如模板切分漏写一个模板、tiling 少做一个模板的详设——补出缺失需重跑上游）。后者靠 **golden 兜底**（codegen 后比对才暴露）。

**诚实代价**：这是"暂保留概设/模板切分独立"的残余风险——「概设↔模板切分↔tiling」的跨边界不一致（含缺失）未被完全消解，只有 golden 兜底（晚）。若要根除，需日后"真合并概设+模板切分"（构造性保证）。

### 6.2 dd-intake 短路目标

现在 `dd-intake` 短路到 `validate`（`design_tree.py`）。validate 删除后，短路目标改为**合成 agent**（用户提供详设时，合成 agent 直接消费 → 组装 design_spec/tiling_strategy），否则短路路径断裂。

### 6.3 feedback-selfcheck 去留

`orchestration-config.json` 的 tail_calls：4 个 tiling skill → `ascendc-op-design-feedback-selfcheck`（消费门反馈）。门删后无反馈可消费 → **feedback-selfcheck 一并删除**（§2.5 唯一通路，不留死消费者）。

### 6.4 ForkJoin merge 回归验证

合并后每 branch 从 4 段 SequentialGroup 变为 1 个 tiling agent，`tiling_results` 的 dict-merge 需回归验证（`test_tiling_forkjoin.py` / `test_forkjoin_dict_merge.py` / `test_tiling_precise_rollback.py`）。

### 6.5 配置更新（orchestration-config.json）

- `iterations`：`validate=3` 删；`tiling=2` 随合并改为 per-template 的 tiling agent 迭代；其余核对。
- `tail_calls`：删 feedback-selfcheck 接线。
- ForkJoin `concurrency`：合并后并发路数仍 N，核对 concurrency 参数。

### 6.6 gate_scope 加载校验去留

`skill_config.py` 的 `validate_gate_scope()`（校验 gate_scope.json）随门删除而更新/删除——门删后无 gate_scope.json 可校验，此加载校验需一并处理（§1.3 加载期校验的对应清理）。

### 6.7 schema 文件交接 = 压缩免疫（合并的红线）

200K 模型实际 ~140K（70%）即触发压缩，否则生成质量跳水。**架构必须按"压缩必然发生"设计，不按"上下文装得下"赌。** 真正的保证是 schema 文件交接（§2.3 I/O 契约 = 文件 + §2.10 结构化输出 + P62 落盘读回）——每 skill 的结论以 schema JSON 落盘，压缩只丢上下文里的推理过程，**结论在盘上、永远可读回**；下一个 agent 读盘上的 schema 文件，不读上下文残片。

**红线**：任何减结构都**不得合并掉 skill 的 schema 文件输出**。编排层合并（B）只合并 agent 会话，不合并 schema 输出——4 个 tiling skill 仍各自写 schema 文件，压缩后逐份读回。skill 层合并（A）会粗化 checkpoint 粒度（可能只剩一个合并 schema），故暂不做 A。
