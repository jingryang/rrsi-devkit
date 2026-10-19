# cannbench_adapt 超时盲区 — L3 方案分析

> 层级：**L3 / 方案分析**。记录有哪些选项、选了哪个、为什么。**拍板后冻结**。
> 问题陈述见 `01-problems.md`（L1）；实施方案见 `03-impl.md`（L4）。

## 一句话问题

软放行链路（workflow 级超时 → precision_debug converge → cannbench_adapt → cannbench_eval → finalize）在 cannbench_adapt 入口断裂：workflow_deadline 超时后不重置 + cannbench_adapt 非 uninterruptible + workflow_deadline 无 Option A → cannbench_adapt 进门即 raise，cannbench_eval 不可达。

## 判据纠偏（核心，驱动方案选择；对应 CLAUDE.md §1.10）

初版候选「把 deadline 检查从 iteration 顶部（`runner.py:283`）移到 spawn 前（`:685`），让不 spawn 的确定性 stage 自动豁免」（曾称 full-α）—— **否决**。它用「是否 spawn agent」这个**机制特征**当「该不该受 deadline 约束」的判据，是**错位代理**：

- **情况 A**（后加 spawn agent 的 stage）：full-α 能支持（spawn 前 `:685` 受检查）。
- **情况 B**（后加「不 spawn 但超时也不该执行」的确定性 stage）：full-α **失效** —— 不 spawn 即豁免，与「超时也不执行」意图相反，且**静默误放行**。

根因：cannbench_adapt（收尾、该豁免）与情况 B 的 stage（非收尾、该拦）**机制特征相同（都不 spawn）但业务语义相反**，spawn 判据区分不出。真正判据是「是否属于软放行收尾」，这必须**显式声明**，不能靠 spawn 推断。

## 冻结方案：保留 `uninterruptible` 显式声明 + 退役 per-node deferred-raise 兑现

### 判据：`uninterruptible` 显式声明（业务语义）

软放行链路的 stage（cannbench_adapt / cannbench_eval）声明 `uninterruptible=True` 表达「我属于超时后仍要执行的收尾」。deadline 机制消费这个声明，不靠 spawn 启发式。

- 收尾链路内 stage（声明 uninterruptible）：豁免。
- 非收尾 stage（不声明，**无论 spawn 与否**）：受 deadline 约束。
- 新加 stage 按是否属于收尾声明 → 自动归位（情况 A/B 都对）。

### 机制：退役 per-node deferred-raise 兑现

现状 deferred-raise-per-node（c2b807e6 / 162c7f4e）：uninterruptible stage 跑过 deadline → `_check_timeout` 记 `_pending_timeout_reason` 不 raise → `_execute_node` 末尾 `raise_deferred_timeout()` 兑现 raise。**陷阱**：per-node 兑现使「至多一个 uninterruptible stage 能跑过 deadline」—— 软放行链路有两个（adapt→eval），第一个跑完即 raise，第二个到不了（01-problems.md 关联事实已实证）。

**冻结修法：退役 per-node 兑现**。uninterruptible stage 跑过 deadline 仅记 overrun（`Logger.warn`，可诊断），**不在 `_execute_node` 末尾 raise**。于是：

- 连续 uninterruptible 链（adapt→eval→…）全部跑完（每个 defer 不 raise），链路贯通。
- 链路后第一个**非 uninterruptible** stage 入口 `_check_timeout`（`:283`）真实检查 deadline → 过期 raise `WorkflowTimeoutError` → 自然终止。**这个入口 raise 本身就是「链路结束」的兑现**，无需显式兑现 deferred reason、无需 lookahead 图结构。
- precision_debug 内部子 stage（非 uninterruptible）：入口 `:283` 真实检查 → 过期 raise → precision_debug catch（`graph_executor.py:366`）→ converge + bubble。**行为不变**。

### 退出码语义（无需新决策）

`dispatcher.py:958` catch 传播出 `execute()` 的 `(Workflow|Stage)TimeoutError` → `EX_TIMEOUT`。新方案下：

- **precision_debug 超时**：内部 raise 被 `graph_executor.py:366` catch（converge + bubble），不传播出 `execute()`；软放行链路不 raise → `execute()` 正常返回 → **非 EX_TIMEOUT**（report 标 overrun）。语义自洽：软放行目的就是「超时也拿一次性 loss」，拿到 = 这次 run 有产出。
- **其他超时**（codegen 等、或软放行链路后的普通 stage）：传播到 `dispatcher:958` → `EX_TIMEOUT`（不变）。

现成 catch 结构天然给出语义，**不需新增退出码决策**（原 L3 子决策 B 消解）。

## 四把尺子

- **可维护**：判据 = `uninterruptible` 显式声明（语义对齐）；退役 per-node 兑现的有害复杂度（B1「deferred raise 丢产物」整类 bug 表面消失）。
- **可扩展**：情况 A（新 agent stage，非 uninterruptible）入口拦；情况 B（新确定性 stage，非 uninterruptible）入口拦；新收尾 stage（声明 uninterruptible）豁免。按声明自动归位。
- **可诊断**：uninterruptible 漏声明 → 入口 `:283` 显式 raise（可诊断）；defer 时 `Logger.warn` 标 overrun（不静默）。
- **架构合理**：deadline 兑现点从 per-node（图遍历边界，错位）回归「stage 入口检查 + run 边界（dispatcher）」；`uninterruptible` 落在 stage（业务语义 owner）。

## 否决方案

| 方案 | 否决理由 |
|---|---|
| **full-α**（deadline 只在 spawn 前 `:685`，删 `:283`） | 判据错位（§1.10）：用 spawn 机制特征代理「该不该受约束」语义；情况 B 静默误放行。 |
| **β**（新 per-stage flag） | 与冻结方案殊途但更重；冻结方案直接复用现有 `uninterruptible`，无需新机制。 |
| **reset/extend workflow_deadline**（原方案 1） | 全局 clear 过度放行（链路后 stage 也豁免）；extend 靠 grace 赌大小。二者都不精确，且仍绑 deadline 数值而非语义。 |
| **方案 2**（跨链压制 deferred-raise + lookahead 图结构） | 需感知图结构，耦合重；冻结方案（退役 per-node 兑现）无需 lookahead，更简。 |

## 不在本次范围

- **P2**（`_converge_to_best_commit` 调用点分裂 + graph_executor 越层 import）：相邻架构债，单独跟踪（见 `01-problems.md` P2）。
- **uninterruptible 漏声明的加载期校验**（§1.3 增强）：后续。本次靠运行期入口 raise 的可诊断性兜底。
- **precision_debug 收敛逻辑**（step-73）：上游已正确。
- **D5 teardown 机制本身**：对单 stage 中断清理仍正确，不动。
