# precision_debug 编排根治：Proposal vs L4-Impl 方案对比（L3 风格决策依据）

> 本文性质：**方案对比 / 决策依据**——把早期 proposal（`precision_debug_workflow_proposal.md`）与拍板后的 L4 实施方案（`51-precision-debugger-async-fix-impl.md`）做逐维度对照，回答「为什么这么改、为什么不那么改」。
> 不重复 L1 事实与 L3 根因（见 `50-non429-issues-analysis.md` §1），不重复 L4 改行配方（见 `51-…impl.md`）；产权只在「两方案的取舍对比」这一层。
> 关联：L1 运行事实 `batch-runlog-20260715.md` 疑似 10；L3 根因 + 拍板 `50-non429-issues-analysis.md` §1 / §9；L4 实施 `51-precision-debugger-async-fix-impl.md`；早期 proposal `precision_debug_workflow_proposal.md`。

## 0. 一句话结论

两份文档**诊断同一个根因、都正确**（SDK CLI Agent 工具异步 ↔ LLM 编排器 prompt 同步语义失配 → 空转 → context 爆 → halt），但给出**两类不同的修复落点**：

- **Proposal（doc 1）**：把 while 循环从 LLM prompt 挪进 **`PrecisionDebugStage` 内部的 Python async while 循环**（stage 自己当编排器，确定性阶段直调 Python、LLM 阶段 `await spawn`）。
- **L4-Impl（doc 51）**：**删除 `PrecisionDebugStage`**，把 4 个 phase 拆成 **框架 `CompositeGroup` 的 4 个子 stage**，循环交给框架 `GraphExecutor`（框架当唯一编排器）。

用户已拍板（L3 §9）：**采用 doc 51，否决 doc 1**，核心理由「Stage 是阶段节点，框架本身才是编排器」。本文把这条结论背后的工程取舍展开，并指出 **doc 1 中两项被丢弃的独立价值（入口守卫、harness 新鲜度检测）值得并入 doc 51 或另立 L1**。

---

## 1. 共同诊断（两文档一致，无分歧）

两文档对根因的认定高度一致，互为印证：

| 诊断点 | 两文档共识 | 实证出处 |
|---|---|---|
| 编排器 prompt 是同步 LOOP | `ascendc-precision-debugger.md` 设计 `Agent(subagent) → returns → verify → 循环` | doc 1 §1.2；doc 51 §1「问题」 |
| SDK CLI 的 Agent 工具是异步/后台 | tool_result 原文 `"Async agent launched successfully…"` | doc 1 §1.2-1.3；doc 51 §1；L3 §1.2 transcript turn 23/67/188 |
| 失配 → 空转等通知 | 每 dispatch 后空转 ~30 turn × 7 轮 dispatch ≈ 210 turn | doc 1 §1.2（17/208/59 turn）；doc 51 §1（~30 turn×7）；L3 §1.1（实测派发 7 次） |
| 空转 → context 膨胀 → halt | checkpoint + 自写分析堆进 context → 251K chars | doc 1 §1.2；doc 51 §1 |
| 空转 → 漂移违规 | 编排器自己跑 Bash 调试（违反 hard rule 4） | doc 1 §1.2；doc 51 §1（100 次 Bash 里 17 次 inline python） |
| 系统性、与具体算子无关 | clipped_swiglu / dequant_swiglu_quant / ai_infra_moe… 同一缺陷 | doc 1 §1.2；doc 51 §1 |

**结论**：诊断层零分歧，差异**完全在修复落点**。

---

## 2. 核心分歧：while 循环住在哪里？

这是两方案的**唯一本质分歧**，其余差异都由它派生。

```
doc 1：PrecisionDebugStage（单一原子 stage）
        └─ actions() 返回一个会跑完整个 while 的「动作」
             └─ 内部 Python async while：
                  run_tests   → 直调 run_precision_cases()      ← 确定性，不 spawn
                  redeploy    → 直调 Deployer                     ← 确定性，不 spawn
                  diagnose    → await sdk_backend.spawn(...)      ← LLM
                  fix         → await sdk_backend.spawn(...)      ← LLM
                  printf      → await sdk_backend.spawn(...)      ← LLM
                  stage_transition → Python 内联函数
        （stage 自己 = 编排器，在一个 stage 调用内跑完多轮）

doc 51：CompositeGroup(name="precision_debug", children=[4 个子 stage])
        └─ run_tests / diagnose / fix / printf 各为独立子 stage
             └─ 每个子 stage actions() 返回 SpawnAgent（含 run_tests 也是 agent）
             └─ resolve_condition() 读 state._debug_checkpoint → 路由条件
             └─ _PRECISION_DEBUG_TRANSITION_TABLE（corrective 边）驱动回环
        （框架 GraphExecutor = 唯一编排器，spawn→wait→transition 是既有机制）
```

派生差异一览：

| 维度 | doc 1（Proposal） | doc 51（L4-Impl） |
|---|---|---|
| **编排权归属** | stage 内部 Python while（stage 自任编排器） | 框架 `GraphExecutor`（框架唯一编排器） |
| **抽象层级** | 仍是单一 `PrecisionDebugStage`，内部塞 while | 删 stage，拆为 `CompositeGroup` + 4 子 stage |
| **run_tests / redeploy 形态** | Python 直调（`run_precision_cases()` / `Deployer`），不进 agent | 子 stage → `SpawnAgent("ascendc-precision-run-tests")`（仍是 agent） |
| **子 agent 输出解析** | JSON Schema 校验 + retry（`_spawn_and_wait`） | 子 stage `transition()` 读 checkpoint.json → 提取到 State |
| **状态机载体** | `_stage_transition()` Python 函数（doc 1 §3.3 给的是 stub） | `_PRECISION_DEBUG_TRANSITION_TABLE`（doc 51 §5 给出完整编码） |
| **跨阶段反馈** | 无显式机制（都在一个 stage 内，Python 局部变量传递） | `loopback_feedback()` → `state._loopback_feedback` → 下游子 stage prompt 的「## 上次反馈」段 |
| **改动范围** | 单文件 `precision_debug.py`（~+240 行） | 多文件新增（2 新建 + 2 修改 + 3 删除 + UT 重写） |
| **是否删 LLM 编排器 agent** | 是（不再 spawn `ascendc-precision-debugger`） | 是（物理删除 `.md` + A5 变体） |
| **是否删 `stage-transition.py`** | 否（逻辑「内联」进 `_stage_transition`） | 是（删除外部脚本，逻辑进 `resolve_condition`） |
| **A5 路径** | 未覆盖 | §8 单列 A5 同法改造 |

---

## 3. 四把尺子评估（CLAUDE.md §1.2）

### 3.1 可维护（是否维持/澄清既有不变式）

- **doc 51**：把 `precision_debug` 纳入「一个子 stage = 一个 spawn = 一段文件→State transition」的既有不变式，与 design / test_design 组**完全同构**。`state._debug_checkpoint` 对标 `state.anchor_report`/`validation_report`，checkpoint.json 的 A/B 类归属（§7）划清了「子 agent 操作数据 vs 框架路由数据」边界——不变式被**澄清**而非新造。
- **doc 1**：保住「`PrecisionDebugStage` 是一个 stage」的外壳，但内部 while 使其成为**异质 stage**（一半 phase 是 Python 直调、一半是 spawn），与仓内其它 stage 形态不一致；该不变式被**弱化**（"stage = actions 返回 Action 由 executor 执行" 在这里被 stage 自己接管执行打破）。

→ **doc 51 胜**。

### 3.2 可扩展（同类新情况能否自动归位）

- **doc 51**：新增一个 phase（如「memcheck 子阶段」）= 加一个子 stage + 一行 transition_table 条目，自动归位到既有模式；A5 路径（不同阶段名 pipeline_sync/dump_debug/vf/finalize）用**同一套模式**改造（§8）。
- **doc 1**：新增 phase = 在 `_run_debug_workflow` 的 if/elif 链里加分支 + 写一个 `_spawn_and_wait` 调用；A5 路径要复制一整份 while 循环（doc 1 完全没提 A5）。

→ **doc 51 胜**（同类扩展零摩擦，A5 自动复用）。

### 3.3 可诊断（异常路径是否留可观测信号）

- 两者都优于现状（消除空转/halt）。
- **doc 51**：每轮一个独立子 stage 会话，events.jsonl 记录每次 `resolve_condition` 返回值 + transition；子 stage 的 `last_error` / `error_signature`（design 组已验证的 same≥2 停滞判定）可直接复用，**回环不收敛有明确停滞信号**。
- **doc 1**：异常时写 partial `debug_result.json` 兜底（§2），但 while 在单 stage 内跑，跨轮的「为何卡在 fix↔printf 横跳」信号不如框架级 events 清晰；停滞判定要自己实现（design 组已有成熟实现可抄，doc 1 未提）。

→ **doc 51 略胜**（复用既有停滞判定 + events 可观测）。

### 3.4 架构合理（修复是否落在职责正确的层）

这是**决定性**的一把尺子，也是 L3 §9 拍板的直接依据：

- **doc 51**：编排权归还框架（§1.1「Stage 是标准扩展入口，框架才是编排器」、§2.5「唯一通路不留旧债」——删 LLM 编排器 agent + 删外部脚本，单一编排器）。落点在**正确的层**。
- **doc 1**：编排权落在 stage 内部 Python（stage 越权当编排器），与 §1.1 / §2.5 相悖。虽然技术上能跑通（见 §4），但**架构职责错位**——这是它被否决的根本原因。

→ **doc 51 决定性胜**。

---

## 4. SDK 模型澄清：为什么 doc 1「技术上可行」却「架构上劣」

这一节澄清一个容易被表象掩盖的事实，避免把 doc 1 误判成「不成立」。

**事实**（实证 `capabilities/agent/sdk_backend.py`）：
- 框架用的 `SDKBackend.spawn()`（`:538`）是**同步**的，直接返回 `AgentResult`——它本就阻塞到子 agent 完成。
- 另有 `async _spawn()`（`:554`）。
- `max_turns=10000`（`:496`）是**单 query 的 turn 预算**，非 token 预算，不防 context 字节膨胀（L3 §1.2 已指出）。

**含义**：
1. async/sync 失配的「异步」特指 **Claude Code CLI 的 Agent 工具**（LLM 编排器在 TUI 里调的那个），**不是**框架后端的 `spawn`。框架后端从来都是同步 spawn→wait。
2. 所以 doc 1 的 `await sdk_backend.spawn(...)` **确实能真正阻塞**、确实能消除空转与 context 爆——它的主修复在功能上成立。
3. 但「能跑通」≠「落点对」：doc 1 把 while 留在 stage 内，等于让一个 stage 绕过框架、自己直接持后端做编排循环。这违反 §1.1（stage 不自任编排）与 §1.6（业务层持 protocol，不经 stage 内部直连后端长循环）。
4. doc 51 不依赖任何「打开 foreground 开关」之类的 SDK 魔法——它只是用框架**本就存在的**同步 spawn→wait→transition，让 GraphExecutor 来跑回环。L3 §9 拍板原文：「否决了 L3 原建议的方向 A1/A2（SDK foreground 开关 / DevKit kernel 内自派发），理由：Stage 是阶段节点，框架本身才是编排器。」

**一句话**：doc 1 与 doc 51 都消灭了 LLM 编排器这条异步通路；区别在于消灭后**由谁来跑那个 while**——doc 1 让 stage 自己跑（可行但越权），doc 51 让框架跑（架构正位）。

---

## 5. 各自独有、对方缺失的价值

这是做「最终落地建议」的关键输入：两文档不是纯粹的好坏关系，doc 1 有 doc 51 没覆盖的正交特性。

### 5.1 doc 1 独有（doc 51 丢弃，值得回捞）

| 特性 | doc 1 出处 | 价值 | doc 51 是否覆盖 |
|---|---|---|---|
| **入口守卫（scope guard）** | §3.4：首轮 run_tests 后用轻量 AI 判定失败是否属本阶段职责（编译失败/schema 不匹配/golden 不全 → halt 写明上游归属，不进 diagnose→fix 循环） | **高**：把上游 codegen 缺陷挡在循环外，省 agent 预算；L1 实证里 scatter（task_loader bug）、aggregate（GAP-A schema 漏 token）正是这类「不是精度问题却被拖进精度循环」的 case | ❌ 未覆盖 |
| **harness 新鲜度检测** | §3.5：`iter-1/harness.py` mtime < DevKit 构建时间 → 强制 redeploy 刷新 | **高**：直击 L3 根因 B（stale harness 致不可修 TypeError，multi_add 反复横跳的触发器） | ❌ 未覆盖（doc 51 只说 finalize 写 debug_result） |
| **run_tests / redeploy 去 agent 化** | §2 表格：确定性逻辑直调 Python，不 spawn | **中**：符合「确定性逻辑无 LLM」原则，省一次 agent 往返；但破坏「一 phase = 一 spawn」均匀性 | ⚠️ doc 51 反向选择（run_tests 仍是 agent，保均匀性） |

### 5.2 doc 51 独有（doc 1 缺失，构成实施主干）

| 特性 | doc 51 出处 | 价值 | doc 1 是否覆盖 |
|---|---|---|---|
| **完整状态机编码** | §5 `_PRECISION_DEBUG_TRANSITION_TABLE`：run_tests/diagnose/fix/printf 全条件（all_pass/exhausted/has_failures/case_resolved/pool_exhausted/pool_exhausted_nobisect/retry/located/continue） | **高**：把 `stage-transition.py` 的语义 1:1 落进 transition_table，不丢分支（尤其 fix 的 `pool_exhausted_nobisect`——编译/运行错误跳过当前用例） | ❌ doc 1 §3.3 只给 stub |
| **A5 路径完整改造** | §8：pipeline_sync/dump_debug/vf(条件)/finalize 同法拆子 stage + 删 `ascendc-precision-debugger-a5.md` | **高**：A2/A3 与 A5 一次性收口 | ❌ doc 1 未提 A5 |
| **子 stage 间 loopback_feedback** | §4.2-4.4：fix→run_tests 传 best_commit/best_max_err、diagnose→fix 传 failure_type、printf→fix 传 located 标志 | **高**：复用 design 组 `_loopback_feedback` + `_feedback_section` 机制，下游 agent 看到「上次反馈」而非盲目重试 | ❌ doc 1 无显式机制 |
| **checkpoint.json A/B 类归属** | §7：A 类（子 agent 操作数据）留文件 / B 类（框架路由数据）经 State 中转，子 agent 不感知 State | **高**：明确文件接力 vs State 的边界，子 agent 零改动（§11） | ⚠️ doc 1 提到「保留 checkpoint 接力」但未划边界 |
| **State 字段 `_debug_checkpoint`** | §6：对标 `anchor_report`，瞬态不进 events payload | **中**：路由数据有标准载体 | ❌ |
| **TDD 实施顺序 + 验证** | §9（5 Phase）/ §10（UT+ST+heavy_llm） | **高**：符合 §3.1 TDD、§3.2 全覆盖、§3.11 heavy_llm 决策 | ❌ doc 1 只给改动量估算 |

---

## 6. 对框架原则的逐条对齐

| 原则 | doc 1 | doc 51 |
|---|---|---|
| §1.1 Stage 契约（`actions→Action`、`transition→State`、框架是编排器） | ✗（stage 内 while 越权编排） | ✓（标准子 stage + 框架跑回环） |
| §1.2 方案合理性（落点在正确层） | ✗（编排权错位） | ✓ |
| §2.5 唯一通路不留旧债（删旧编排通路） | △（删 LLM 编排器 agent，但 while 仍是 stage 内新通路，非框架标准通路） | ✓（物理删 agent + 脚本，编排唯一收敛到框架） |
| §1.6 依赖注入（业务层持 protocol） | ✗（stage 内直连后端长循环 spawn） | ✓（spawn 经框架 Action 协议） |
| §3.1/§3.2 TDD + 全覆盖 | △（无测试设计） | ✓（§9 Phase 4 重写 UT） |

---

## 7. 决策史与落地建议

### 7.1 已确定的决策（L3 §9 拍板，无需再议）

- **编排根治**：采用 doc 51（CompositeGroup + 子 stage），否决 doc 1（stage 内 while）。理由：框架是唯一编排器。
- **`stage-transition.py`**：删除，逻辑进各子 stage `resolve_condition`。
- **checkpoint 路由字段**：State 字段 `_debug_checkpoint`，对标 `anchor_report`。

### 7.2 本对比给出的增量建议

doc 51 作为主干已定，但 doc 1 的两项正交价值**不应随方案否决一起丢弃**，建议作为独立增强处理：

1. **入口守卫（scope guard）** → 建议并入 doc 51，或另立 L1 问题跟踪。
   - 落点候选：作为 `RunTestsSubstage` 的前置判定，或 `precision_debug` 组入口的一个轻量 guard 子 stage（首轮 run_tests 后、进 diagnose 前）。
   - 价值佐证：L1 实证 scatter（DevKit `task_loader.py:180` bug）、aggregate（GAP-A `mask=None` schema 漏 token）都是「被精度循环拖住的上游缺陷」，guard 能省大量无效 diagnose/fix 轮次。
   - 注意：doc 1 用 AI 判定（理由：正则匹配漏新错误模板、组合型错误判不准比例）——这条理由成立，保留 AI 判定。
2. **harness 新鲜度检测** → 建议另立 L1（直击 L3 根因 B，与编排重构正交）。
   - 落点候选：`_init_checkpoint` / 首轮 run_tests 前检查 `iter-1/harness.py` mtime vs DevKit 构建时间，stale 则强制 redeploy。
3. **run_tests 去不去 agent 化** → 不建议改 doc 51 的选择。
   - doc 51 让 run_tests 仍是 agent 是为了保「一 phase = 一 spawn」均匀性、与 design 组同构；doc 1 的 Python 直调虽更省，但破坏均匀性。**均匀性优先**（§3.1 可维护）。
   - 若实测 run_tests agent 成了瓶颈，再单点优化（子 stage 内部确定性 action 化），不在此重构范围。

### 7.3 给执行者的清单

- 按 doc 51 §9 的 5 个 Phase 实施（A2/A3 先行，A5 验证通过后跟进）。
- 实施时**回捞** doc 1 §3.4（scope guard）与 §3.5（harness freshness）作为独立增强项，在 doc 51 的「不改 / 关键边界（§11）」之外单列，避免它们被「否决 doc 1」连带埋没。
- 两者都是**正交于编排重构**的增强，可独立立项、独立验证，不阻塞 doc 51 主干。

---

## 8. 关键路径索引

- 早期 proposal（被否决方向）：`docs/plan/self-evolution/precision_debug_workflow_proposal.md`
- L4 实施（拍板主干）：`docs/plan/self-evolution/51-precision-debugger-async-fix-impl.md`
- L3 根因 + 拍板：`docs/plan/self-evolution/50-non429-issues-analysis.md` §1（双根因）/ §9（拍板表）
- L1 运行事实：`docs/plan/self-evolution/batch-runlog-20260715.md` 疑似 10
- 现状代码（待重构）：
  - `src/ascendc_devkit/orchestration/stages/precision_debug.py:185`（`PrecisionDebugStage` 单 stage，`_actions_legacy:251` / `_actions_a5:301` → `SpawnAgent`，`_build_prompt:361`，`transition:488` 缺 `debug_result.json` 即 halt）
  - `.claude/agents/ascendc-precision-debugger.md` / `ascendc-precision-debugger-a5.md`（待删 LLM 编排器）
  - `.claude/plugins/stage-precision-debug/skills/ascendc-precision-debug/scripts/stage-transition.py`（待删外部状态机脚本）
- 对标模式（doc 51 复用、已实证存在）：
  - `src/ascendc_devkit/orchestration/design_tree.py`（`build_detailed_design_group` → `CompositeGroup(children, transition_table, output_contract_override, max_corrective)`）
  - `src/ascendc_devkit/orchestration/stages/design_substages.py`（`_DesignSubstage`：`actions`→SpawnAgent / `transition`→磁盘产物→State / `resolve_condition`→路由 / `loopback_feedback`→`state._loopback_feedback`→`_feedback_section` 渲染「## 上次反馈」）
- SDK 模型（澄清 doc 1 为何技术可行）：`src/ascendc_devkit/capabilities/agent/sdk_backend.py:538`（同步 `spawn`→`AgentResult`）/ `:554`（`async _spawn`）/ `:496`（`max_turns` 单 query 预算）
