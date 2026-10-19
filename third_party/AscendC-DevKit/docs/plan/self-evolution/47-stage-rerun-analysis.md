# 43 — 任意 stage 强制重跑入口（L3 方案分析）

> 工作线：self-evolution
> 状态：**已拍板冻结 + 已实施**（2026-07-13）
> 关联 L4：`47-stage-rerun-impl.md`
> L1 问题：`06-problems.md` P77

## 需求（用户 2026-07-13）

「考虑以后对某个 stage 做迭代优化，即使上一版 stage 已经产生了结果，还是想在优化该 stage 之后基于前置 stage 的输出结合重跑，快速验证。」——对指定已完成 stage 做强制重跑（fresh）的新特性。

**rerun ≠ resume（用户强调的核心约束）**：
- `--resume <run>` = 从中断处继续：跳过已完成节点、重跑失败/中断节点、**且 resume 该 agent 的 SDK session** 复用推理记忆（省 token）。
- `--rerun-from <node>` = 对用户选定的**已完成**节点**从零重跑**：**故意丢弃**上一版 agent 的 session 记忆，spawn fresh。用于 stage 迭代优化后的快速验证。

## 机制地图（调研结论：改动量小到中）

底层原语全部就绪，rerun 不是第三个机制，是 loopback/resume 共用原语的第**三**个触发入口：

| 原语 | 位置 | 已有触发点 |
|---|---|---|
| `_invalidate_subtree` | `graph_executor.py:39-63` | loopback / resume |
| `_invalidate_sequential_range` | `graph_executor.py:66-83` | loopback / resume |
| `rerun_selector` | `node_forkjoin.py:43-48` | loopback 模板精确回退 |
| **node_status = resume/rerun 唯一权威** | `graph_executor.py:174` skip-on-completed | resume |

**真实耦合（正确不变式，保留）**：
- P52 clean-prefix 因果级联——上游重跑则下游 stale 必作废（下游消费上游产物）。
- events.jsonl 追加语义（历史权威）。
- session sidecar 在 agent clean finish 时删除（生命周期正确）。
- 产物文件覆盖（可重入）。

**人为耦合（可消除）**：stage 自管累加计数器（`codegen_iterations`/`debug_iterations`/`perf_iterations`）生命周期未对齐 node_status；`codegen_consecutive_failures` 断路器、`perf_iterations>0` 防 verify↔perf 死循环 guard 会卡/误路由 fresh 重跑。

**无物理不可逆副作用阻挡 rerun**（events 追加、文件覆盖、sidecar 删除都可重入/可重建）。

## 选项

### A. 最小 rerun-flag（只翻 node_status）✗ 否决
仅作废目标 + 下游 node_status，不清计数器、不清 sidecar。
- ✗ 不满足用户「fresh」语义：sidecar 仍在 → codegen.actions 读到 → resume 旧 session（违反 rerun ≠ resume 核心约束）；perf guard 误路由；codegen 断路器可能卡。
- 机制层能跑，语义层不干净。

### B. 统一 primitive（`State.reset_for_rerun` + 入口 + fresh 保证）✅ 选定
- ✅ §1.2（合理性：用「正确改动」承担主修复[node_status 因果作废]保住不变式 + 「宽容兜底」清计数器防卡 + 可观测性[log + 命中的 stage 名]）。
- ✅ §2.5（单通路：node_status 是唯一权威；sidecar 删除走 codegen.actions 已有的单一读路径，不新增「ignore sidecar」标志；计数器重置走 `Stage.rerun_reset_fields` 单一声明源）。
- ✅ §1.2 可扩展（新 stage 只需在 `rerun_reset_fields` 声明其重跑需清的字段，自动归位）。
- ✅ fresh-not-resume 核心约束由「删 sidecar」保证（codegen.actions 找不到 sidecar → fresh spawn）。

### C. 根治计数器生命周期（计数器随 node_status 自动归零）✗ 否决（过度）
把所有 stage 自管计数器改成 node_status 派生。
- ✗ 改动面大、收益边际（计数器还有诊断价值——第 N 次重跑）；当前 clean-mode reset 已够。

## 决策

**选 B**。clean-mode only（reset 所有命中 stage 的 `rerun_reset_fields` 到默认；不做 incremental——incremental 有 perf guard 误路由风险且无清晰用例，§1.4 不留 unused flexibility）。

fresh-not-resume 保证 = 删 `<run>/agents/*.session.json`。安全性：sidecar 仅在非 clean-finish 时存在（clean finish 删之）；completed 节点无 sidecar；故 `*.session.json` 里只有被重跑/下游节点的 sidecar，全删=全部 want fresh，upstream completed 无 sidecar 可删。

详见 L4。
