# precision_debug agent 中断 → 重试保障 — L3 方案分析（2026-07-22）

> 层级：**L3 方案分析**。每个问题列举候选方案 + 四尺子评估 + 选取结论。
> 实施方案见 `03-impl.md`（L4）。

## 文件简称映射

| 简称 | 实际路径 |
|------|---------|
| `substages` | `src/ascendc_devkit/orchestration/stages/precision_debug_substages.py` |
| `tree` | `src/ascendc_devkit/orchestration/precision_debug_tree.py` |

---

## P1 — run_tests agent 中断后 scope_guard 被跳过

### 方案

| 选项 | 描述 | 四尺子评估 |
|------|------|-----------|
| O1 交换判断顺序 | `scope_checked` 移到 `agent_aborted` 之前 | 不可维护（中断时无可信数据给 scope_guard 判，scope_guard 拿空数据判大概率误判或崩）；不可诊断（scope_guard contract 校验遇到空 verdict 直接抛异常） |
| **O2 agent_aborted → retry run_tests** ✅ | `resolve_condition` 返回 `"agent_aborted"`，transition_table 显式路由回 `run_tests`（corrective） | 可维护（中断=数据不可信→重试，语义清晰）；可扩展（同模式可用于其他 stage）；可诊断（history 中记录 abort 事件）；架构合理（路由在 transition_table，不靠判断顺序） |
| O3 agent_aborted → scope_guard | 中断时也先过 scope_guard | 不可行（scope_guard 需要 failed_case_queue/run.log 等产物，中断时这些可能不完整） |

**选取 O2**。中断意味着 agent 未产出可信数据——正确行为是**重试**，而非继续前进或交给 scope_guard 盲判。重试成功后 run_tests 正常完成 → `needs_scope_check` → scope_guard 正常判定。

### 退火

连续中断 3 次 → `abort_exhausted` → escalate 退出。防止同一环境问题导致无限重试。

---

## P2 — 其他 5 个 substage 缺少 agent 中断检测

### 方案

| 选项 | 描述 | 四尺子评估 |
|------|------|-----------|
| **O1 基类统一检测 + 各 stage 路由回自身** ✅ | `_PrecisionDebugSubstage` 加 `_agent_produced_output()` 方法；每个 `transition()` 开头调此方法检测中断；每个 `resolve_condition()` 开头调 `_resolve_abort_condition()` 统一路由 | 可维护（单一检测点 + 统一路由入口）；可扩展（新 stage 自动继承）；可诊断（每个 stage 的 abort 事件都进 history）；架构合理（检测逻辑在基类，路由在各自 resolve_condition） |
| O2 各 stage 各自实现 | 每个 transition 手写检测逻辑 | 重复代码，不一致风险 |
| O3 graph_executor 层统一检测 | 在 spawn→wait 后检查 agent 退出码 | 不够——agent 可能正常退出但未写文件（LLM 幻觉导致跳过写步骤） |

**选取 O1**。检测判据：round-suffixed phase JSON 文件存在且非空 → agent 正常完成。文件缺失/为空/不可解析 → agent 中断。

各 stage 的 abort 行为：
- `diagnose`：中断 → retry diagnose（不消费数据、不写 candidate_pool）
- `fix`：中断 → retry fix（递增 corrective_cycles 防止死循环）
- `diagnose_refine`：中断 → retry diagnose_refine
- `printf_location`：中断 → retry printf_location（递增 corrective_cycles）
- `scope_guard`：中断 → retry scope_guard（`_resolve_abort_condition` 在 contract 校验**之前**，避免空 verdict 触发 `PrecisionDebugContractError`）

---

## P3 — 连续中断退火

### 方案

| 选项 | 描述 | 四尺子评估 |
|------|------|-----------|
| **O1 独立 `consecutive_aborts` 计数器** ✅ | 框架全局计数器，存在 control.json。任何 stage 中断 → +1；任何 stage 正常完成 → 归零。≥3 → `abort_exhausted` → escalate | 可维护（单一计数点，语义独立）；可扩展（对所有 stage 通用）；可诊断（checkpoint 可见）；架构合理（退火属框架职责） |
| O2 复用 corrective_cycles | 中断时也递增 corrective_cycles | 语义混淆——corrective_cycles 用于 fix↔printf 小循环收敛，与中断退火是不同概念 |
| O3 复用 rounds | 同 O2 问题——rounds 语义是「经 run_tests 的轮次」 | 不选 |

**选取 O1**。`consecutive_aborts` 与现有计数器正交：

- `rounds`：经 run_tests 的轮次（语义收敛）
- `corrective_cycles`：fix↔printf 小循环计数（小循环收敛）
- `consecutive_aborts`：**连续中断计数（中断退火）** ← 新增

行为：
```
场景 A：连续中断
  run_tests 中断 → aborts=1 → retry
  run_tests 中断 → aborts=2 → retry
  run_tests 中断 → aborts=3 → abort_exhausted → escalate ✅

场景 B：中断后恢复
  run_tests 中断 → aborts=1 → retry
  run_tests 正常 → aborts=0 → 正常流程 ✅

场景 C：不同 stage 交叉中断
  diagnose 中断 → aborts=1 → retry
  diagnose 正常 → aborts=0 → diagnose→fix
  fix 中断     → aborts=1 → retry
  fix 正常     → aborts=0 → 正常流程 ✅
```

---

## 总体策略

四把尺子综合评估：**正确改动（主修复）** = 基类统一检测 + 各 stage 路由回自身 + 独立退火计数器。

两层防御：
1. **检测层**：`_agent_produced_output()` — 判断 agent 是否正常产出
2. **路由层**：`_resolve_abort_condition()` — 统一判定「重试当前 stage」还是「连续中断超限 → 退出」

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-07-22 | 初版：P1–P3 方案分析，选取 O2（run_tests retry）+ O1（基类统一检测）+ O1（独立 consecutive_aborts） |
