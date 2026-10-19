# diagnose 流不进二分（printf / comment_bisect）— L1 问题记录（2026-08-12）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据 / 现象 / 根因 / 影响）。
> 不提方案、不排序、不写决策——修复方案见同目录 `02-analysis.md`（L3）。
>
> **直接前置工作**：本问题是 `fix-diagnose-merge/`（fix 子阶段并入 diagnose 子阶段）引入的回归。
> 该融合本身正确（省上下文重建 + 空转 spawn），但合并改变了 candidate_pool 的生成行为，
> 间接破坏了「diagnose 搞不定 → 流入二分定位」的保证。
>
> 证据基于源码（`orchestration/stages/precision_debug_substages.py`）+ skill 正文
> （`.claude/skills/ascendc-precision-diagnose/SKILL.md`）+ 合并前 `FixSubstage`
> （`943cc222^`）逐条比对确认。

> 结论速览：合并后 diagnose 从 candidate_pool 的「纯消费者」变为「生产者+消费者」，
> 候选池不再单调递减，「候选用完 → pool_exhausted → need_printf」的兜底路径失效；
> 只剩 cc(6) 耗尽出口，而该出口走 `_advance_past_failure_type` 换 case、**绕过 printf**，
> 且合并后 diagnose 每次 retry 都是重型 spawn，等 cc 耗尽代价过大。共四项事实 P1–P4。

---

## P1：diagnose cc 耗尽走 `_advance_past_failure_type` 换 case，绕过 printf_location（合并回归）

### 证据

- `DiagnoseSubstage.transition` 的 cc 耗尽分支（`precision_debug_substages.py`，cc 耗尽 advance 块）
  在 `corrective_cycles >= max_corrective_cycles(=6)` 时调 `_advance_past_failure_type(cp)` 跳过当前 case。
- 对应 `resolve_condition` 的 cc 耗尽 safety-net 返回 `skip_more`（还有 case）/ `skip_done`（无 case）→
  转换表驱动回 `run_tests`。**该路径不经过 printf_location / comment_bisect**。
- 即：当 diagnose 对某个 precision/runtime 类失败用尽静态手段仍未解决时，框架**跳过该 case**，
  而非降级到设备级二分（printf 数值二分 / comment_bisect 崩溃二分）取证。

### 根因

cc 耗尽出口的语义被设计成「换 case」（advance past failure_type），而非「降级二分」。
合并前这条路径**几乎走不到**——因为更早的 `pool_exhausted → need_printf` 兜底会先触发（见 P4）。
合并后 pool_exhausted 失效（见 P2），cc 耗尽成了**唯一**兜底出口，于是「绕过 printf」从偶发
变成 precision/runtime 类「diagnose 搞不定」场景的**必然归宿**。

### 影响

- precision 类失败若 diagnose 静态分析无法定位根因（典型：需要 on-device printf 取证才能确认
  数值发散点），将被直接跳过、回退全量 run_tests，**从不做一次 printf 二分**。
- runtime 类失败（崩溃）同理，从不做一次 comment_bisect。
- 这违背 precision_debug 闭环的设计意图——二分定位本应是「静态分析停滞时的设备级后手」。

---

## P2：B2「增量复用」使 candidate_pool 非单调，pool_exhausted 兜底永久失效

### 证据

- `.claude/skills/ascendc-precision-diagnose/SKILL.md` B2「增量复用」段（约 `:125-138`）：
  diagnose 在 retry 且「最佳匹配 < 0.6」（即上轮候选未命中根因）时，**生成新的候选**补入 pool。
- `_candidate_pool_exhausted` 判据为 `pending == 0`（`precision_debug_substages.py` helper）。
- 因 B2 持续往 pool 补入新候选，`pending` 几乎不会归零 → `_candidate_pool_exhausted` 永不成立 →
  `resolve_condition` 的 `pool_exhausted → need_printf` 兜底**永不触发**。
- 源码比对：合并前 `FixSubstage.resolve_condition` 与合并后 `DiagnoseSubstage.resolve_condition`
  **逐字相同**——`pool_exhausted → need_printf` 两版都在；差异不在路由代码，而在 pool 的生成行为。

### 根因

合并把 fix 的「纯消费者」职责并入 diagnose：旧 fix 只读 diagnose 产的 pool 逐个实施、**不生成新候选**；
合并后 diagnose 既是生产者（B2 增量生成）又是消费者（实施候选）。pool 从「单调递减」变成「动态增减」，
`pending == 0` 的耗尽判据失去成立前提。

### 影响

- `pool_exhausted` 这条「候选用完 → 需要二分」的兜底通道在合并后形同虚设。
- 与 P1 叠加：原本由 pool_exhausted 提前触发的 printf 流入路径消失，只剩 cc 耗尽（换 case、绕过 printf）。

---

## P3：合并后 diagnose 每次 retry 是重型 spawn，等 cc(6) 耗尽代价过大

### 证据

- 合并前：diagnose **分析一次**（产出 pool），fix **轻量反复实施**（Edit→build→test→commit/rollback，
  读既定 pool，不重新分析）。fix 候选用完（cc=1~3 < 6）即触发 pool_exhausted 转 printf，**时序快**。
- 合并后：diagnose 每次 retry 都是**重型 spawn**——重新分析 + Edit + build + redeploy + 单用例验证。
  `cc` 每次 retry +1，等 cc=6 耗尽 = **6 次重型 diagnose spawn**。
- `adaptive_avg_pool_3d` run（`output/20260811-141809-49c6ca/.../control.json`）实证：
  diagnose round 1 `corrective_cycles=1`（框架 abort）→ round 1 `corrective_cycles=2`（重入验证），
  单次 diagnose 耗时即 10+ 分钟（`elapsed_sec=10121`）。

### 根因

合并把「轻量反复实施的 fix」并入「重型分析的 diagnose」，使 retry 的单次成本从「轻量实施」
升级为「重新分析+全链路 build/redeploy」。cc 的阈值 6 是在合并前「fix 轻量 retry」语境下设定的，
合并后仍沿用 6 → 对「需要二分」的 bug 白白消耗 6 次重型 spawn 才转。

### 影响

- 对那些静态分析注定无法定位、必须二分取证的 case，每多等一次 cc = 一次完整的重型 diagnose spawn
  开销（分析 + build + redeploy + 验证），而这些 spawn 在「本就该转二分」的意义上是**空耗**。
- 「不能一直 diagnose，diagnose 搞不定要流入二分」——用户对等待代价的直接诉求在此未被满足。

---

## P4：合并前 fix 是 pool 的纯消费者，need_printf 必然到达且时序快（对照事实，反证 P1–P3 是回归）

### 证据

- 合并前 `FixSubstage`（`943cc222^`）只读 diagnose 产的 candidate_pool 逐个实施，**不生成新候选**。
- 故 pool **单调递减**：pending 从 N 逐个减到 0。实施若干候选（cc=1~3，远 < 6）即耗尽 →
  `pool_exhausted` 成立 → `resolve_condition` 返回 `need_printf` → **printf_location 必然到达**。
- 且 fix 实施是轻量操作（读既定 pool，Edit/build/test/commit），不像 diagnose 那样每次重新分析。
- 用户原话佐证（对照基准）：「之前 fix 和 diagnose 独立时并没有流不进 printf 二分的问题。」

### 根因

合并前的架构里，diagnose（生产者，分析一次）与 fix（消费者，反复实施）职责分离，
使 pool 单调递减、pool_exhausted 在 cc 耗尽**之前**必然先触发——这正是「流入二分」的保证来源。

### 影响（对照结论）

- P4 是 P1–P3 的**反证基线**：合并前「流入 printf」是构造性保证（pool 单调 → 耗尽 → need_printf），
  合并后该保证丢失（pool 非单调 → pool_exhausted 失效 → 唯一出口 cc 耗尽绕过 printf）。
- 即「流不进 printf」是 fix-diagnose 合并的**直接回归**，而非独立的新缺陷。

---

## 问题关系（事实层，不含方案）

| # | 事实 | 与其他问题关系 |
|---|---|---|
| P1 | cc 耗尽出口绕过 printf | 合并后成为「diagnose 搞不定」的唯一归宿（因 P2） |
| P2 | B2 增量生成使 pool_exhausted 失效 | 使 P1 的 cc 耗尽从「几乎走不到」变为「必然走到」 |
| P3 | diagnose 重型 retry 致等 cc 满过慢 | 放大 P1 的代价（6 次重型 spawn 才转） |
| P4 | 合并前 fix 纯消费，need_printf 必达且快 | P1–P3 的反证基线：证明这是合并引入的回归 |

> 方案（如何在框架层恢复「diagnose 搞不定 → 流入二分」的保证，同时不误伤有进展的 case）
> 见同目录 `02-analysis.md`（L3）；具体代码配方见 `03-impl.md`（L4）。
