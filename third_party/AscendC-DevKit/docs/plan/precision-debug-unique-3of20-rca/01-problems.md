# precision_debug `unique` 3/20 早退 — L1 问题记录（2026-08-06）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据 / 现象 / 根因事实 / 产权）。
> **不提方案、不排顺序、不写决策**（§1.8 L1 产权）。方案分析见 `02-analysis.md`（L3）。
>
> 范围：只分析 **precision_debug 未全部通过**的原因；按用户要求，cann-bench 评测不出分（`cannbench_eval` stage error）属独立问题，本文**不展开**。

## 证据来源

- **算子**：`unique`（AscendC，self_evolve_op 流水线）
- **运行**：`output/20260805-152456-8b48b2/20260805-152456-434434/`
- **闭环权威状态**：`artifacts/debug/unique/control.json` + `precision_report.md` + 各 phase 产物 + `events.jsonl` + `run.log`
- **kernel 源码**：`cann-bench-batch/20260805_232439/unique/.../op_kernel/unique.h`（commit `d7ba88e` HEAD）
- **最终结果**：**3 passed / 17 failed / 0 crashed**，best_commit `6dc4159`（best_passed_count=3）

---

## P1（严重 · codegen/详设）：unique kernel 把所有 dtype 经 float 中转 workspace → 17/20 bit-exact 精度失败

### 哪里坏了

codegen 生成的 unique kernel（`op_kernel/unique.h`）对所有 dtype 的值统一走 **float 中转 GM workspace**：输入先 cast 成 `float` 存 `valGm_`，去重后再 cast 回原 dtype 写 `yGm_`。这条「任意 dtype → float → 任意 dtype」的往返对 17/20 用例**有损**，且损失是 bit-exact 级（多数 `max_abs_diff=0`，即"数值看似相等但字节级不一致"）。

### 凭什么这么说（证据）

1. **kernel 源码实证**（`op_kernel/unique.h`，commit `d7ba88e`）：
   - L104-105：`GlobalTensor<float> valGm_;` / `GlobalTensor<float> yFloatGm_;` —— 中转 buffer 一律 float。
   - L200：BF16 输入 `AscendC::ToFloat(xDeq.GetValue(i))`；L336：BF16 输出 `AscendC::ToBfloat16(yF.GetValue(i))` —— 这对标量 cast helper 在本平台产出**全零**。
   - L348-350：FP16 输出 `ScalarCast<float, half, CAST_ODD>` —— float `==` 比较抹掉 IEEE-754 ±0.0 符号，CAST_ODD 又归一化成 +0.0；±inf 符号亦可能翻转。
   - L193-194 / L330-331：int 路径 `int → static_cast<float> → ... → static_cast<int>`，测试区间内 int 在 float 中本可无损，但边界处少量元素错配。

2. **diagnose#3 失败模式分类**（`precision_diagnose_r004_p010.json`，gate=`incremental_diagnose`）：
   | 子类 | 用例 | 现象 |
   |---|---|---|
   | A1 BF16 全零 | unique_3/9/13/18 | kernel 输出全 0 vs golden 正常 |
   | A2 FP16/FP32 符号位 | unique_1/2/7/8/11/12/14/15/17/20 | max_abs_diff=0 但字节级不一致（±0.0、±inf 符号）|
   | B int 边界 | unique_4/5/19 | max_abs_diff>0（10000/100000/998），少量边界元素错配 |
   | 通过 | unique_6/10/16 | uint8/int8 256-bin、int32 全零输入（cast 风险极小）|

3. **失败是纯精度、非崩溃**：diagnose#3 `excluded_hypotheses` 已排除「runtime hang / 算法去重逻辑错 / plugin yLen 推导错 / workspace OOB」——kernel 在所有 20 例上都能正常跑完（~260ms），失败纯属数值。

### 根因（事实陈述）

kernel 的 dtype 策略选了「统一 float 中转」而非「native dtype 比较/去重」。这是 **codegen/详设阶段的 dtype 策略缺陷**——多 dtype 算子的正确性不应依赖一个有损的公共中转类型，尤其不应使用标量 `ToFloat/ToBfloat16` helper（其在 BF16 上产零）与 `CAST_ODD` 归一化（抹 ±0.0 符号）。

### 产权

codegen（生成 cast 路径）+ 详设（dtype 策略选型）。与 §1.5（算子知识不进 Python）、§1.12（不与具体算子耦合：本缺陷对「同类多 dtype 算子」应自动正确归位，而非靠 precision 闭环逐算子兜）同源。

---

## P2（严重 · 框架）：printf_location agent 在「用例已 resolved」时不写 round JSON → 假 abort → abort_exhausted → precision_debug 提前退出

### 哪里坏了

diagnose#3 把 P1 route 到 `printf_location` 后，printf_location **连续 3 次 spawn 都没写出框架 relay 监听的 round JSON**，被记为 3 次 abort，触发 `consecutive_aborts=3 ≥ _ABORT_EXHAUST_THRESHOLD(3)` → `abort_exhausted` → **precision_debug 放弃、退出到 cannbench_adapt**。此时精度闭环**远未耗尽预算**：

| 维度 | 实际 | 上限 |
|---|---|---|
| `corrective_cycles` | 3 | 6 |
| loopback count | 6 | 30 |
| `elapsed_sec` | 22555 | 36000 (`time_budget_sec`) |
| `rounds` | — | 未超 `max_iterations`(15) |

### 凭什么这么说（证据）

1. **三次 round JSON 缺失**（`run.log`，本地 UTC+8）：
   ```
   06:47:21  [WARN] [PD-RELAY] .../precision_printf_r004_p011.json round file missing — phase json not synced (agent may have failed before writing)
   06:49:19  [WARN] [PD-RELAY] .../precision_printf_r004_p012.json round file missing — ...
   06:55:18  [WARN] [PD-RELAY] .../precision_printf_r004_p013.json round file missing — ...
   06:56:06  loopback precision_debug → cannbench_adapt (validation 0/2)   ← 放弃退出
   ```
   `control.json` 终值 `consecutive_aborts=3`。

2. **agent 并非崩溃/超时，而是「干了活但只输出文本结论」**：读第 3 次 abort 的 transcript（`agents/ascendc-precision-printf-locate-03.jsonl` turn 16），agent 最终输出是自然语言：
   > 「所有不变式均已满足：debug_state="fresh"、printf_location_result="located_fixed"；当前用例 level3/unique_1 已是 resolved_pending，提交 d7ba88e … 重新验证完成：用例已在上一次会话第 1 轮定位并修复 … **结果：PRINTF_FIXED**」

   且同次 harness `printf_location_iter-8/result.json` 显示 unique_1 **实际通过**（diff=0.0、mismatch 0/19058）。即 agent 正确判断「用例已在上一会话修好、本轮无需新修复」并跑通了单用例验证，但**只输出了一句文本结论，没有写 relay 期望的新 round JSON**。

3. **退出逻辑锚点**（`precision_debug_substages.py`）：`_ABORT_EXHAUST_THRESHOLD = 3`；`_resolve_abort_condition` 在 `consecutive_aborts >= 3` 时返回 `"abort_exhausted"` 升级整个 CompositeGroup。

4. **被「跨会话状态复用」放大**：`precision_printf.json`（round=1）与 `d7ba88e` 来自**上一会话**（其 `_summary` 明文 "prior session"）；本会话 precision_debug 带此遗留状态重入，printf_location 反复撞「已解决、无事可做」→ agent 按「只输出结论」收尾 → 框架按「必须写新 round JSON」判 abort。

### 根因（事实陈述）

**agent 输出契约 vs 框架 relay 期望的失配**：printf_location agent 在「用例已 resolved、无需新修复」的退出路径上，只产出文本结论而不落规范 round JSON；relay（`[PD-RELAY]`）按「找不到 round 文件 = abort」判定，与既有 `precision-debug-agent-abort` 工作假设的「abort = agent 真崩溃/超时/无产出」语义不一致——这里的 abort 是**假 abort**（agent 实际跑通用例）。

### 影响

- precision_debug 在 3/20 时**非自然耗尽**而是**契约失配触发的提前退出**，剩余预算（3 个 corrective cycle、~3.7h 墙钟）未用。
- 退出前**未跑全量 run_tests 回归** → P1（17/20 精度）失去继续修复机会，且 P4 账目缺口由此产生。

### 产权

precision-debug skill/agent 层（printf_location 输出契约）+ relay 判定。与既有 `precision-debug-agent-abort`（P1-P3，abort **机制**）正交：后者解决「如何检测/退火 abort」，本 P 是「abort 语义被契约失配污染（假 abort）」。

---

## P3（中等 · 框架）：diagnose 把「系统性 dtype 策略缺陷」route 到 printf_location（单点二分工具），工具错配

### 哪里坏了

diagnose#3 正确识别了 P1 的根因（float 中转 workspace），但把它 `route_to=printf_location`。printf_location 的职责是**二分定位首个数值发散点**，适合「单点/局部」发散；而 P1 是**系统性、全量级**缺陷（所有 float dtype 用例横跨失败，非某个发散点）。对系统性缺陷，printf_location（定位 + 就地小修）既无法定位（没有"首个发散点"，是整条数据流的 dtype 策略），也无法就地修复（需架构级 native-dtype 改写）。

### 凭什么这么说（证据）

- `precision_diagnose_r004_p010.json`：`gate_used=incremental_diagnose`，`route_to=printf_location`，`root_cause` 明述「ALL values pass through float intermediate … MULTIPLE distinct root causes coexist」。
- 失败模式横跨 3 个 dtype 族（BF16/FP16/FP32/int）、14+3=17 例，是结构性而非局部分布。
- printf_location 实际三连 abort（P2）也反证：它在该 case 上找不到新工作（用例已 resolved），对剩余 16 例的系统性缺陷无能为力。

### 根因（事实陈述）

diagnose 的 route 决策缺少「**系统性 vs 单点**」判据：当失败模式是全量级 dtype 策略问题（非单点数值发散）时，应触发「架构级重写/回溯 codegen」信号，而非进 printf 单点二分循环。

### 产权

precision-debug diagnose routing（route 决策的判据）。

---

## P4（轻 · 账目）：`d7ba88e` 修好 unique_1 但未跑全量回归 → best_commit 与 report 不一致

### 哪里坏了

`d7ba88e`（printf_location 上一会话产物）实际修好了 unique_1（消除 Step 3 的 MTE2→PIPE_S 竞争 + DataCache 一致性 gap），但本会话退出前**未跑一次完整 run_tests 回归**确认，导致：
- `control.json.best_commit` 停在 `6dc4159`（3/20），未更新到 `d7ba88e`；
- `precision_report.md`「最优 commit」却写 `d7ba88e` —— **两处不一致**；
- `failed_case_queue` 中 unique_1 状态为 `resolved_pending`（单用例已过、待全量确认），从未转正。

### 凭什么这么说（证据）

- `control.json`：`best_commit=6dc4159...`、`best_passed_count=3`；`failed_case_queue[0]`（unique_1）`status=resolved_pending`、`last_fix_commit=d7ba88e`。
- `precision_report.md`：「最优 commit `6dc4159`」与「修复历史 #4 `6dc4159`」并列，但 git HEAD 实为 `d7ba88e`。
- events.jsonl：最后一次 `run_tests` 在 printf_location 之前（loopback count=3 之前）；printf_location 之后直接 `precision_debug → cannbench_adapt`，**无全量 run_tests**。

### 根因（事实陈述）

abort_exhausted 提前退出（P2）跳过了「代码修改后跑全量回归更新 best_commit」的收尾步；`resolved_pending` 的用例无确认通道。

### 产权

precision-debug transition（best_commit 语义 / resolved_pending 收尾）。与 `precision-debug-closure-hardening`（best_commit 仅 RunTestsSubstage 全量回归后记录）相关但正交：那里解决「何时记 best_commit」，本 P 是「提前退出致收尾步缺失」。

---

## 问题汇总矩阵

| 问题 | 影响严重度 | 性质 | 核心锚点 | 产权 |
|------|-----------|------|---------|------|
| P1 unique kernel float 中转 → 17/20 精度失败 | 严重 | codegen/详设 dtype 策略缺陷 | `unique.h` L104/200/336/348 float 中转 + 标量 cast helper | codegen + 详设 |
| P2 printf_location 假 abort → abort_exhausted 提前退出 | 严重 | agent 输出契约 vs relay 失配 | round JSON 未写 + `_ABORT_EXHAUST_THRESHOLD=3` | precision-debug skill/agent + relay |
| P3 diagnose 把系统性缺陷 route 到单点 printf | 中等 | route 决策缺「系统 vs 单点」判据 | `precision_diagnose_r004_p010` route_to=printf | diagnose routing |
| P4 d7ba88e 未回归 → best_commit/report 不一致 | 轻 | 提前退出跳过收尾 | `best_commit=6dc4159` vs report `d7ba88e` | precision-debug transition |

## 与既有工作的关系（避免重复产权）

- **`precision-debug-agent-abort`**（P1-P3）：解决 abort **检测/退火机制**（`consecutive_aborts` 计数器、`_handle_abort`、`_resolve_abort_condition`）。本 RCA 的 **P2 是其下游新问题**：机制正确，但「假 abort」（契约失配）污染了 abort 语义——机制无法区分「真崩溃」与「agent 干了活但没落 round JSON」。
- **`precision-debug-closure-hardening`**：best_commit 收敛语义。本 RCA **P4 与其正交**：那里定义「何时记 best_commit」，P4 是「提前退出致收尾步根本没跑」。
- **`precision-runtime-comment-bisect` / `printf-selfclose-fix`**：printf 自闭环定位即修复。本 RCA **P3 与其相关**：printf 工具能力边界（单点）对系统性缺陷不适用。

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-08-06 | 初版：基于 `20260805-152456-434434`（unique）一次运行记录 P1-P4。方案见 `02-analysis.md`（L3）|
