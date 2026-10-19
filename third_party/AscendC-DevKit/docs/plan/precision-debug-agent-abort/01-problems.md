# precision_debug agent 中断 → 重试保障 — L1 问题记录（2026-07-22）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/根因/影响）。
> **不提方案**。方案分析见 `02-analysis.md`（L3）；实施方案见 `03-impl.md`（L4）。

## 证据来源

- **算子**：`advance_step_v2`（AscendC，A2/ascend910b）
- **闭环权威状态**：`artifacts/debug/advance_step_v2/control.json` + `report.json` + 各 phase 产物
- **运行特征**：`run_tests` agent 中断 → 直接进入 `diagnose → fix → printf_location` 循环，`scope_guard` 从未运行，4 个 case 全部 skipped（根因是 `golden.py` 签名不匹配——上游缺陷，本应在首轮被 scope_guard 拦截）

---

## P1（严重）：`run_tests` agent 中断后 scope_guard 被跳过，上游缺陷未被拦截

### 证据

- `control.json`：`scope_checked: false`、`scope_verdict: null`——scope_guard 从未执行
- `phases/` 目录：存在 `run_tests`、`diagnose`、`fix`、`printf_location` 四个 phase 目录，**不存在 `scope_guard` 目录**
- `control.json.history`：共 10 条记录，全部 round=1，phase 分布为 `run_tests(1) → diagnose(1) → fix(1) → printf_location(1) → fix(1) → printf_location(1) → fix(1) → printf_location(1) → fix(1) → printf_location(1)`——scope_guard 从未出现
- 首条 history 记录：`phase=run_tests, failure_type=unknown, test_result=aborted`
- `failed_case_queue`：20 个 case，4 个 skipped，16 个 pending，全部 `max_err=999.0`（crash）
- 根因 `golden.py` 签名不匹配（`TypeError advance_step_v2() got multiple values for argument 'num_seqs'`）是**上游缺陷**（外部只读 task 文件），本应在首轮被 scope_guard 判定 `upstream` 后 halt

### 根因

`RunTestsSubstage.resolve_condition` 的判断顺序：

1. `agent_aborted` = True → `return "has_failures"` ← **在此返回**
2. `status == "passed"` → （未到达）
3. `rounds > max_iterations` → （未到达）
4. `scope_checked` = False → `return "needs_scope_check"` ← **永远走不到**

`agent_aborted` 在 `scope_checked` 之前被检查，直接返回 `"has_failures"`。而 transition_table 中 `"has_failures"` 未注册 → graph_executor 走 linear successor → **直接进入 `diagnose`**，scope_guard 被跳过。

`scope_checked` 始终为 `False`（scope_guard 从未被运行，无法写入），但 `needs_scope_check` 永远不会被返回。

### 影响

- 上游缺陷（golden 签名不匹配、编译失败、schema 不匹配等）无法被 scope_guard 拦截
- diagnose→fix→printf 在盲态下空转，浪费精度循环预算（本例 10 轮 agent spawn）
- 与 scope_guard 的设计意图（§12.1「首轮入口守卫——命中上游 → halt，不浪费精度循环预算」）直接矛盾

---

## P2（严重）：其他 5 个 substage 完全没有 agent 中断检测

### 证据

- `DiagnoseSubstage.transition`：不检查 agent 是否产出 phase JSON，直接消费数据
- `FixSubstage.transition`：同上
- `DiagnoseRefineSubstage.transition`：同上
- `PrintfLocateSubstage.transition`：同上
- `ScopeGuardSubstage.transition`：同上
- 全仓 `agent_aborted` 检测**仅存在于 `RunTestsSubstage`**

### 根因

设计假设「agent 永远正常完成」——各 substage 的 `transition()` 直接消费 phase JSON 数据，不做存在性检查。agent 中断时 phase JSON 缺失/为空 → 后续逻辑在空数据上运行 → 静默产生错误结果或空转。

### 影响

- `diagnose` agent 中断 → candidate_pool 为空 → fix 无计划可用 → 空转
- `fix` agent 中断 → case 状态未更新 → 同 case 反复 spawn fix agent
- `scope_guard` agent 中断 → verdict 为空 → 当前代码会抛 `PrecisionDebugContractError`（contract 校验：verdict 不在 {upstream, pass} → raise），直接 halt 整个 pipeline

---

## P3（中等）：无退火机制——连续中断会死循环

### 证据

- 如果某 stage 的 agent 反复中断（如同一个环境问题导致每次 spawn 都 crash），retry 会无限进行
- 无「连续中断 N 次后放弃」的熔断机制
- 当前 `run_tests` 的中断路径依赖 `rounds` 递增提供隐式退火（每次 abort 也递增 rounds），但其他 stage 没有等价机制

### 根因

缺少独立的「连续中断计数」——各 stage 的计数器（`rounds`、`corrective_cycles`）在 abort 路径上是否递增不一致，且语义不专用于中断退火。

### 影响

- 同一环境问题导致 agent 反复中断 → 无限重试 → 最终靠 workflow 超时终止
- 无法区分「偶发中断」（应重试）与「系统性中断」（应放弃）

---

## 问题汇总矩阵

| 问题 | 影响严重度 | 性质 | 核心锚点 |
|------|-----------|------|---------|
| P1 run_tests 中断后 scope_guard 被跳过 | 严重 | resolve_condition 判断顺序 bug | `agent_aborted` 在 `scope_checked` 之前被检查 |
| P2 其他 5 个 substage 无中断检测 | 严重 | 机制缺失 | 仅 RunTestsSubstage 有 `agent_aborted` 检测 |
| P3 无连续中断退火 | 中等 | 机制缺失 | 无独立 `consecutive_aborts` 计数器 |

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-07-22 | 初版：基于 `advance_step_v2` 一次运行（`artifacts/debug/advance_step_v2/`）记录 P1–P3 |
