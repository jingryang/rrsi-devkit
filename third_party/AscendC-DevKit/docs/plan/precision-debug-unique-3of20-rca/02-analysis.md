# precision_debug `unique` 3/20 早退 — L3 方案分析（2026-08-06）

> 层级：**L3 / 方案分析**。回答「有哪些选项、选了哪个、为什么」。
> 问题事实见 `01-problems.md`（L1，产权：证据/根因）。本文只做选项取舍 + 决策。
> **未修改任何代码**（本轮只落文档）；L4 实施方案待拍板后另起。

## 分析范围与优先级

| 问题 | 是否本轮给方案 | 理由 |
|---|---|---|
| **P2** printf 假 abort → 提前退出 | ✅ 主方案 | 框架级、可立即收敛、直接决定"为何停在 3/20" |
| **P3** diagnose 系统性缺陷误 route 到 printf | ✅ 主方案 | 框架级、与 P2 同源（route 决策） |
| **P1** float 中转 → 17/20 精度 | ⚠️ 给方向，非本轮改 | 根在 codegen/详设 dtype 策略，属另一产权线（见末节） |
| **P4** best_commit/report 不一致 | ✅ 轻方案 | 随 P2 收敛自然消解 + 小修 |

四把尺子（§1.2）：**可维护**（维持/澄清既有不变式）/ **可扩展**（同类新情况自动归位）/ **可诊断**（异常留可观测信号）/ **架构合理**（落在职责正确的层）。

---

## P2：printf_location「假 abort」→ 提前退出

### 问题本质

`consecutive_aborts` 机制的**前提假设**（见 `precision-debug-agent-abort`）：abort = agent 真崩溃/超时/无产出（context limit / infra crash）。本 P 暴露该假设不成立：agent **正常跑通用例**但**未落 round JSON**（只给文本结论），relay 仍按「round 文件缺失 = abort」判定 → 假 abort 三连 → `abort_exhausted` 提前退出。

即：**abort 判据（round JSON 存在性）与 abort 语义（agent 是否真失败）脱钩**。

### 选项

#### 选项 A：relay 判据下沉——区分「无产出」与「有产出但未落 round 文件」
- **做法**：relay（`[PD-RELAY]`）在 round JSON 缺失时，先看 agent 是否有**实质产出**（harness `result.json` 已生成 / transcript 末轮有结构化结论 / git 有新 commit）。有实质产出 → 按「契约违规但非崩溃」处理（重写 round JSON 兜底 + WARN，**不计入 `consecutive_aborts`**）；无实质产出 → 真 abort，计数。
- **四把尺子**：
  - 可维护 ✅：澄清了 abort 语义（真崩溃 vs 契约违规），不变式更准。
  - 可扩展 ✅：同类新 phase（comment_bisect 等）只要遵守「实质产出」判据就自动归位。
  - 可诊断 ✅：契约违规走 WARN（可观测），不静默。
  - 架构合理 ✅：落在 relay（产物同步层），正是 round JSON 产权所在。
- **代价**：需定义「实质产出」的客观信号（result.json 存在 / git diff / transcript 末轮结构化），有判定成本。

#### 选项 B：agent 契约硬化——强制「任何退出路径都落 round JSON」
- **做法**：在 `ascendc-precision-printf` skill 硬规则 + agent manifest 里强制：**任何退出路径**（含「用例已 resolved、无需新修复」）都必须写规范 round JSON（标 `located_fixed` / `no_new_fix` / `already_resolved`），禁止「只输出文本结论」收尾。加载期校验（§1.3）兜住漏写。
- **四把尺子**：
  - 可维护 ✅：单一契约（必须落 round JSON），无例外路径。
  - 可扩展 ✅：新 case 类型只要落 JSON 就归位。
  - 可诊断 ✅：round JSON 记录「为何无需修复」，可追溯。
  - 架构合理 ✅：落在 skill/agent（产出契约产权方）。
- **代价**：依赖 agent 遵守；LLM 偶发不遵守时仍可能漏写（需 A 的兜底）。

#### 选项 C：abort_exhausted 阈值/重置放宽
- **做法**：抬升 `_ABORT_EXHAUST_THRESHOLD`，或在「agent 实际跑通用例」时重置 `consecutive_aborts`。
- **四把尺子**：
  - 可维护 ❌：治标——假 abort 仍发生，只是延后退出。
  - 可扩展 ❌：不同 case 触发条件不同，调阈值是打补丁。
  - 可诊断 ⚠️：不解决根因，只延长空转。
  - 架构合理 ❌：落在错误层（用阈值掩盖契约失配）。

### 决策：**A + B 组合**（A 主修 + B 源头硬化 + C 不取）

- **B 是源头正确改动**（§1.2「正确改动」承担主修复）：让 agent 永远落 round JSON，消灭假 abort 的产生源——保住「round JSON 存在 = agent 产出」的不变式。
- **A 是宽容兜底**（last resort）：LLM 偶发漏写时，relay 不把它误判为崩溃 abort，而是兜底重写 + WARN——防止契约偶发违转化为提前退出（§1.2「再加可观测性确保错误不被掩盖」）。
- **C 不取**：阈值调参是机制特征代理（§1.10），掩盖根因。
- **与既有 `precision-debug-agent-abort` 的边界**：那里建的是 abort **机制**（计数/退火/升级），本方案不动机制，只修「abort 判据的语义」——补「实质产出」判据（A）+ agent 契约（B），机制本身不变。

---

## P3：diagnose 把系统性缺陷 route 到单点 printf

### 问题本质

diagnose 的 route 决策缺「**系统性 vs 单点**」判据。printf_location 是单点二分工具（定位首个发散点），对全量级 dtype 策略缺陷（横跨多 dtype、多 case 的同源失败）既无法定位也无能修复，只会空转/假 abort（P2 的三连 abort 部分根因即此）。

### 选项

#### 选项 A：diagnose route 增加「系统性缺陷」分支
- **做法**：diagnose 识别「失败模式横跨多 dtype 族 + 同源根因（如统一中转类型）」时，route 到「**架构级重写信号**」——回溯 codegen/详设（带 root_cause + 修复方向交还上游产权方），而非进 printf 单点循环。
- **判据用业务语义**（§1.10）：如 `failure_categories` 多族同源 / `affects_cases` 跨 dtype / 根因定位在「数据流公共路径」而非「某 case 某点」→ 声明 `systemic`，不靠「是否多 case」这类机制特征代理。
- **四把尺子**：
  - 可维护 ✅：route 决策与缺陷尺度对齐。
  - 可扩展 ✅：同类「公共路径」缺陷自动 route 到上游，不进单点循环。
  - 可诊断 ✅：`systemic` route 留信号 + root_cause 交还产权方（§1.13 golden/上游产权）。
  - 架构合理 ✅：落在 diagnose（route 决策产权方），且尊重「精度闭环不兜 codegen 缺陷」边界（§2.9 门不越界）。

#### 选项 B：保持 route 到 printf，但 printf 识别「无单点可定位」快速让出
- **做法**：printf_location 进入后发现「发散是全量级、无首个发散点」时，快速返回 `unresolved`（而非空转/假 abort），让框架 advance/escalate。
- **四把尺子**：可维护 ⚠️（printf 承担了它不该承担的"系统性"判定）；其余尚可。
- **代价**：把系统性判定的职责放错了层（printf 是定位工具，不该判系统性）。

### 决策：**A**

- route 决策是 diagnose 的职责（§2.9 门的本职 + 路由产权），系统性判定就该在 diagnose 用业务语义声明（§1.10），不下放给 printf（B 越层）。
- A 让 P1 这类缺陷**回溯 codegen/详设**交还产权方（§1.13），而非在精度闭环里兜——符合「门的边界」（§2.9 门不越界查上游、构造性保证优先）。

---

## P4：best_commit / report 不一致

### 问题本质

P2 的提前退出跳过了「代码修改后跑全量 run_tests 回归更新 best_commit」的收尾步；`resolved_pending` 用例无确认通道。

### 选项与决策：**随 P2 收敛 + 收尾步显式化**

- P2（A+B）修复后，precision_debug 不会再被假 abort 提前退出 → 收尾步（全量回归确认 resolved_pending）有机会跑 → P4 自然消解。
- **补强（小修，待 L4）**：printf_location 的 `located_fixed` / `already_resolved` 路径在 commit 后，应由框架补一次全量 run_tests（确认 `resolved_pending` → `resolved`），与 `printf-selfclose-fix` 的「printf 自闭环修复后 → run_tests」路由对齐——避免「单用例过但全量未确认」悬挂。
- **四把尺子**：可维护 ✅（best_commit 单一来源 = 全量回归）；可诊断 ✅（resolved 状态有全量证据）。

---

## P1：float 中转 → 17/20 精度（方向，非本轮改）

### 问题本质

codegen/详设为多 dtype 算子选了「统一 float 中转」策略，对 BF16（标量 helper 产零）/ FP16·FP32（±0.0 符号抹除）/ int（边界）有损。

### 选项（方向）

- **A（根治·codegen/详设层）**：多 dtype 算子生成 **native-dtype 比较/去重路径**——BF16 用 vector Cast（非标量 ToFloat）、FP16 直接 half 比较、int 不过 float。在 codegen 阶段按 dtype 分派，不让算子语义正确性后置给 precision 闭环（§1.5/§1.12）。
- **B（精度闭环兜·不取）**：在 precision fix 里逐 dtype 打补丁——违反 §1.12（与具体算子/dtype 耦合）、§2.9（精度闭环不兜 codegen 缺陷）。

### 决策：**A（方向），产权移交 codegen/详设，本轮不动**

- P1 根因在 codegen/详设 dtype 策略，**不是 precision_debug 的职责**（§2.9 门不越界）。本轮 precision_debug 侧的方案是 P2/P3/P4；P1 仅记录方向，移交 codegen/详设产权线另立工作项。
- **注意（诚实）**：即便 P1 用 A 根治，unique 在 NPU 上的算法本身（去重需排序）已暴露两层结构性硬伤（UB 容量、标量复杂度），fix#2 的「host 预排序 + O(n) 流式去重」是当前可行解；P1 的 float 中转是叠加其上的第三层，A 可解。

---

## 决策汇总

| 问题 | 决策 | 性质 | 落点 |
|---|---|---|---|
| P2 假 abort | **A（relay 实质产出判据）+ B（agent 强制落 round JSON）** | 主修 + 源头硬化 | relay + skill/agent |
| P3 误 route | **A（diagnose 系统性分支，业务语义判据）** | route 决策修正 | diagnose routing |
| P4 账目 | 随 P2 收敛 + resolved_pending 收尾步显式化 | 小修 | transition（待 L4）|
| P1 float 中转 | **方向 A（native-dtype 路径），移交 codegen/详设** | 不在本轮 | codegen/详设（另立）|

## 未决项 / 后续

1. **L4 实施方案**：P2/P3/P4 拍板后另起 `03-impl-*.md`（具体改哪个函数、TDD 用例、验证）。本轮按用户要求**只落文档、不改代码**。
2. **P1 移交**：codegen/详设 dtype 策略（native-dtype 分派）需另立工作项；本文只记方向。
3. **回归验证**：P2/P3 修复后，应能复现「precision_debug 在 unique 上不再提前退出」——但 P1 的 17/20 精度需 codegen 侧 native-dtype 改写后才能真正转绿，非本 RCA 闭环可达成。

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-08-06 | 初版：P2(A+B)/P3(A)/P4/P1(方向) 决策 + 四把尺子评估。未改代码 |
