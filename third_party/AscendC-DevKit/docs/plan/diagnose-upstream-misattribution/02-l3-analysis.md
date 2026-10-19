# L3 — diagnose 归因误判方案分析

> 四层方案体系 L3：记录有哪些选项、选了哪个、为什么。重点回答：这是不是重构引入的？会不会有其他形式的误判？是不是 precision_debug 阶段设计本身有问题？
> 对应 L1：docs/plan/diagnose-upstream-misattribution/01-l1-facts.md

## 一、误判的完整机制（先把因果说清）

本次 diagnose 的行为轨迹（从会话文本 + 产物还原）：

1. **早期**（环境坏时）：NPU 0 Alarm → 空 kernel 也崩 → 误判"kernel 没问题，环境坏了"。
2. **环境恢复后**：单用例验证，iter-2 起**不崩**（ShiftF32 修复生效），但**输出空 y**（shape [0] vs golden [19058]）。
3. **转折**：diagnose 没消费 iter-2 result.json 的 error_msg（"形状不匹配"），反而去查"系统 OPP 有 stale kernel"——这个观察是**真事实**，但与当前失败**无因果**。
4. **归因**：把"runtime 加载 stale OPP kernel"当成根因 → 上报 upstream(deploy) → halt。

**误判的本质**：diagnose 把**两个独立的真观察**错误关联了——
- 观察 A（真）：系统 OPP 有 stale kernel。
- 观察 B（真）：runtime 实际加载 workspace 修复版（iter-2 不崩）。
- 错误：以为 A 导致 B，实际 A 与当前失败（y 空）无关。

## 二、这是不是重构引入的？—— 判断：不是，但重构让它更显性

### 论证"不是重构引入"

- **重构前（七 phase）**：diagnose 枚举错误类型（Gate1/common-traps），靠枚举表猜根因。它有 `bounds_check`（越界检查）、`scope_guard`（上游归属判断）等**独立 phase**。
- **重构后（两段）**：diagnose 不枚举，比对 golden 找发散点。
- **本次误判的模式**（把无关环境观察当根因）**不是 P3 新增的能力缺陷**——重构前 diagnose 靠枚举表猜，**更容易**被无关现象带偏（枚举表本身可能含 stale kernel 这类"环境陷阱"条目）。
- **证据**：重构前批（20260822-143931）diagnose 49.5min 产 2 候选 0 修复、printf_location 42 实验 0 收敛——**重构前 diagnose 根本没定位到任何根因**（空转），谈不上"误判根因"。本次至少**正确定位并修复了真 kernel bug**（ShiftF32），误判发生在**第二个失败**（y 空）上。

### 但重构让它"更显性"

- 重构前 diagnose 空转（0 修复），**根本没走到"修好第一个 bug 再遇第二个 bug"这一步**——所以不会暴露"第二个失败归因"问题。
- 重构后 diagnose **能修好第一个 bug**，于是**暴露了第二个失败（y 空）的归因能力缺口**。
- 结论：**重构前能力不足掩盖了归因问题，重构后能力提升才让归因问题显现**。不是回归，是"能者多劳"暴露的新面。

## 三、会不会有其他形式的误判？—— 判断：有系统性模式

把本次误判抽象，**共性模式**是：

> **diagnose 观察到某个"真事实"（如系统 OPP 有 stale kernel、NPU 0 Alarm、zombie 进程），把这个真事实当成当前失败的根因，即使它与当前失败无因果。**

这类误判的**触发条件**：
1. **失败是"形状/空输出"类**（output=[0] vs golden=[19058]）——diagnose 的方法论（比对 golden 找数值发散点）对这类失败**无明确指引**（空对 19058 是形状不匹配，不是数值发散）。
2. **环境有"显眼异常"**（stale kernel、Alarm、zombie）——这些真事实**强吸引注意力**，diagnose 容易归因于它们。
3. **result.json 有 error_msg**（"形状不匹配"）但 diagnose **没优先消费它**——它是最直接的失败证据，但被环境现象淹没。

**其他可能的误判形式**（同类模式的变体）：
- **把环境问题当 kernel 问题**：NPU 故障/驱动错误 → 误判 kernel bug（本次早期阶段差点发生）。
- **把 host 问题当 kernel 问题**：tiling/infershape 错 → 误判 kernel。
- **把 kernel 问题当环境问题**（本次）：修好崩溃后遇"输出空"，误判 deploy/stale（本次实际发生）。
- **把单用例通过当全量通过**：单用例过了就标 resolved，但全量有 shape 变体失败。

## 四、是不是 precision_debug 阶段设计有问题？—— 判断：设计有缺口，不是根本错误

### 设计合理处（保留）

- **比对 golden 一致即对**（§1.13/§1.14）——方向正确，本次正是靠它定位 ShiftF32。
- **不枚举、不候选池、不回炉**（P3 减法）——避免了上次批的空转。
- **upstream 判据**（如实上报上游缺陷）——方向上对，本次 deploy 阻塞验证确实该上报。

### 设计缺口（需要补，但非推翻）

1. **方法论对"形状/空输出"失败无明确指引**：
   - diagnose 的定位方法是"比对 golden 找数值发散点"（SKILL.md L84）。
   - 当 kernel 输出空数组（shape [0]）时，没有"数值发散点"可比对——**diagnose 不知道该往哪查**。
   - 它退而依赖"环境显眼异常"（stale OPP）作为归因——这是**方法论缺口导致的回避行为**。

2. **失败证据消费顺序未固化**：
   - result.json 的 `error_msg`（"形状不匹配"）是**最直接的失败证据**，但 diagnose 没优先消费。
   - SKILL.md L38 提到读 `max_diff_location`，但**没强调 error_msg 的优先性**（形状/空输出时 max_diff_location 无意义，error_msg 才有意义）。

3. **upstream 上报的"先验证后归因"纪律缺失**：
   - diagnose 上报 upstream 前，应先**确认修复后失败的具体形态**（是 error 还是精度），再归因。
   - 本次它修好崩溃后，**没看 iter-2 的 error_msg 就归因 deploy**——归因前缺验证闭环。

### 关键洞察（避免打补丁）

**这三条缺口的共同根源**：diagnose 的定位方法论是"**数值发散**"单一路径，但 kernel 失败有**多种形态**（崩溃/数值错/形状错/空输出/环境错），P3 减法把"枚举错误类型"删了，**但没有给"按失败形态分诊"的结构化替代**。

**§1.14 的平衡**：不枚举错误类型（不列表猜根因）≠ 不按失败形态分流（先看失败形态再选定位方法）。P3 删的是"枚举表"，但**失败形态分诊**是"帮模型"（给 diagnose 定位起点），不是"控模型"。

## 五、关键追加证据（20260824 深挖）

### 证据 E1：diagnose 完全没有读失败证据就归因

- 扫描 diagnose 会话全部命令：**0 条**提到 `result.json` / `error_msg` / `形状` / `total_count` / `output_comparisons`。
- 即：diagnose 修好崩溃后（iter-2 起），**从未读 iter-2 result.json 的 error_msg**（"形状不匹配: output=torch.Size([0]), golden=torch.Size([19058])"），就直接归因 deploy 上报。
- **关键**：这不是框架限制（模型有工具读 result.json），也不是 skill 没写（SKILL.md L47 明确说"形状 mismatch → 本阶段职责，就地修"），而是 **diagnose 模型行为：跳过失败证据，主动选择环境归因**。

### 证据 E2：SKILL.md 已声明形状 mismatch 是本职责，但未被遵循

- SKILL.md L47 原文：「**数值错**（max_diff / **形状 mismatch** / NaN）→ **本阶段职责**，就地修（kernel 精度缺陷）」。
- 本次失败恰是"形状 mismatch"（output=[0] vs golden=[19058]），skill 已明确归 diagnose 本职责。
- 但 diagnose 未遵循——**说明问题不在 skill 缺指引，在模型未遵循既有指引**。

### 证据 E3：diagnose 的"修好崩溃"产生了错误完成感

- 会话轨迹：修好 507035 → 单用例不崩 → 但输出空 → **它认为"kernel bug 修好了"** → 后续失败倾向归因外部（deploy）。
- 环境异常（系统 OPP 有 stale kernel）是**真事实**且是"合理解释"，模型容易接受；而"输出空"需深挖 kernel 输出逻辑（更难）。

## 十四、增量写 _summary 不会明显增大文件（20260824 实测）

### 关键事实：diagnose 已在增量写 tried_fixes（现状）

- 本次批 `fix_code_log.tried_fixes` 有 **4 条**（ShiftF32 修复成功 + PipeBarrier/FlipSign/GSwap 三次失败尝试）。
- **说明 diagnose 每修一步已在追加 tried_fixes**——增量写已是现状（fix_code_log 部分），只是 `_summary`（symptom/root_cause）收尾才写。

### 膨胀模型：只有"追加条目"线性增长，"覆盖更新"恒定

| 增量类型 | 载体 | 膨胀模型 |
|---|---|---|
| 覆盖更新（symptom/root_cause 更新为最新结论） | `_summary` | **大小恒定**（~1KB，不追加） |
| 追加条目（每修一步加一条） | `fix_code_log.tried_fixes` | 线性增长（**已有现状**） |

### 实际大小（本次批实测）

- `_summary`：**1031B**（覆盖更新，不膨胀）
- `fix_code_log`：**899B**（4 条 tried_fixes，每条 ~200-500B）
- precision_diagnose.json 整体：**2-3KB**

### 最坏情况估算

- 诊断 20 次修复 → tried_fixes 20 条 ≈ **4-10KB**（每次 ~200-500B）
- `_summary` 覆盖更新 → **~1KB 恒定**
- **总计 ~10KB，对 JSON 完全可接受**

### 关键区分：增量写 ≠ 追加全部

- `_summary`（symptom/root_cause）：**覆盖更新**（最新结论），不追加 → 大小恒定。
- `fix_code_log.tried_fixes`：**追加**（每修一步一条）→ 已是现状，线性但单条小。
- **方案 F 的增量写只涉及 `_summary` 的覆盖更新 + tried_fixes 追加**——都不会显著增大。

### 可选保险（非必需）

若担心 tried_fixes 极端增长（几百次修复），设上限（如保留最近 30 条）。**可选优化**，本次 4 条、最坏 20 条远低于阈值。

### 传递的状态信息（resume 后注入 diagnose 上下文）

| 状态 | 来源 | 用途 |
|---|---|---|
| diagnose 自身进度（已修/已试/当前假设） | `_summary`（现有字段，改造为增量写） | 让 diagnose 知道"之前查到哪" |
| 当前代码状态（git diff/status） | 实时读取 | 让 diagnose 知道"代码被改到哪"（二分残留） |
| 当前失败状态（崩/输出空/精度） | result.json 的 error_msg 实时读 | 让 diagnose 知道"当前失败是什么" |
| 上次 aborted 标记 | control.json history（现有） | 让 diagnose 知道"我是续跑" |

### 新增 vs 原有

**已有（无需新增）**：
- `_summary` schema（symptom/root_cause/tried_fixes）+ 写入契约
- `_append_history`（框架从 _summary 物化 history）
- control.json history（含 `diagnose: aborted`）

**新增（需要加）**：
- `_summary` 中途增量写（现在是收尾写）——改变写时机
- resume 时框架把状态注入 diagnose prompt（现在是完整 round 1 prompt）——prompt 构造附加状态

### 工作量评估：小到中（不做大改）

| 改动点 | 内容 | 工作量 |
|---|---|---|
| 1. SKILL.md/prompt | 引导 diagnose 增量写 `_summary`（每修一步写一次，非收尾） | 小（文本修改） |
| 2. prompt 构造 | resume 时附加"当前 git 状态 + 上次 _summary + aborted 标记" | 小（改拼接，复用 `_read_agent_summary`） |
| 3. 框架检测残留 | 不需要（diagnose 增量写后，resume 能读到自己进度） | 0（方案 F 核心是状态传递，非检测） |

**关键**：
- **不做 rollback**（改动大 + 丢进度——best_commit 9934d0b 会丢 ShiftF32 修复）。
- **做状态传递**（改动小 + 通用——对齐 codegen resume_point）。
- 不动框架核心路由/transition，只改 SKILL.md/prompt + prompt 拼接。

### 用户约束：resume 机制是通用的，不能为 diagnose 特设 rollback

- resume 是跨所有 stage 的通用机制：设计阶段 resume 直接继续（不 rollback），codegen 用 `resume_point`（状态传递）。
- **若为 diagnose 加"resume 时 rollback"**：违反 §1.15（通用行为统一抽象）+ §2.5（唯一通路），且只堵 diagnose。

### 决定性论据：rollback 对 diagnose 是致命的（丢进度）

- `best_commit = 9934d0b`（precision_debug entry 快照 = codegen 产物）。
- diagnose 修复 ShiftF32 后 commit（7839265）若被杀，rollback 到 best_commit（9934d0b）**会丢 ShiftF32 修复**。
- **rollback 恢复的是 best_commit，不是"被杀前最新状态"**——对 diagnose 丢所有修复，重来。**不是通用机制，且有进度损失。**

### 通用机制：agent 显式记录进度 + resume 时传递状态

**对齐 codegen 的 `resume_point` 模式**（codegen_pending_resume_point：agent 显式声明 resume 点，resume 时框架传给 agent）：

1. **agent 显式记录进度**：diagnose 工作时把"当前假设 / 已修 / 正在验证"写到 control.json 的 `diagnose_progress` 字段（类比 codegen 的 `resume_point`）。
2. **resume 时框架传递状态**：把 `diagnose_progress` + 当前工作区状态（git diff/status）注入 resume 后的 diagnose 上下文。
3. **diagnose 感知后决定**：看到"我之前在查 X，当前代码被改到 Y" → 基于**当前真实状态**决定继续/修正，不重头认知。

**通用性验证**：
- **设计阶段**：写产物到 artifacts/，resume 读已有产物继续——**已是状态传递**，兼容，不加 rollback。
- **codegen**：已有 `resume_point`——兼容，diagnose 对齐。
- **diagnose**：加 `diagnose_progress`——对齐 codegen 模式。

**为什么是根治**：
- 不丢进度（agent 的已修/假设保留）。
- 通用（各 stage 靠"agent 显式记录进度 + resume 传递"），不特设 diagnose。
- diagnose resume 后基于**真实当前状态**（代码残留 + 自己的进度记录）决策，而非 round 1 重头认知 + 过时环境结论。

### 与方案 A-E 的关系

- 方案 E（resume 状态重校准）升级为**方案 F（状态传递）**：不靠"diagnose 自觉重新校准"，而是框架**显式传递**当前状态（diagnose_progress + git 状态），让 diagnose 感知。
- 方案 A（强制读失败证据）/ B（矛盾检测）/ C（上报前验证）/ D（失败形态变化检测）仍是 diagnose 定位纪律。
- **F 是框架层通用机制，A-E 是 diagnose 定位纪律**——两者互补，F 解决"resume 认知错位"，A-E 解决"定位归因"。

### 证据 E9：框架有 teardown/rollback 机制，但 SIGKILL 时无法执行

- `precision_debug_substages.py:1245 teardown`：diagnose 收尾时 `RepoGuard.rollback`（git checkout best_commit + clean，HEAD 不动）。
- **触发条件**：diagnose 正常收尾（resolve_condition 判定收敛/exhausted/中断信号可捕获时）。
- **SIGKILL 场景**：进程直接死（137），teardown 不执行 → 二分残留留在工作区。
- **resume 场景**：框架重新 spawn diagnose（单次），未主动 reset（diagnose 收尾才 rollback）→ diagnose 看到残留。

### 澄清结论

- **不是 diagnose 破坏环境**：环境是外部故障（NPU 0 Alarm + devmm + zombie）。diagnose 只是观察到并记录了"环境坏了"（会话文本），未破坏环境。
- **不是框架主动 reset 代码**：框架有 teardown/rollback 机制，但 SIGKILL 时无法执行（进程死了）；resume 时也未主动 reset。
- **真正问题**：**SIGKILL 使框架 teardown/rollback 无法兜住中间状态**（二分残留 + "环境坏了"旧认知），resume 续会话后 diagnose 看到残留和旧认知，基于过时环境结论重新开始。

### 修正后的根因表述

> 首跑被 SIGKILL 时，框架 teardown/rollback 无法执行（SIGKILL 不可捕获），diagnose 中间状态（二分残留 + "环境坏了"旧认知）未清理。resume 续会话后，diagnose 看到残留 + 旧认知，基于过时的环境结论重新开始，最终归因误判。

这是 **框架 teardown 在 SIGKILL 场景的缺口** + **diagnose 未做 resume 状态重校准（方案 E）** 的复合问题。

### 证据 E7：resume 确实续用了会话（agent_resume + "继续"）

- run.log：`[08:47] agent_resume [unique/precision_debug] ascendc-precision-diagnose auto-resuming session ses_fd03e559 (sidecar present — silent-cut recovery)`。
- ses_fd03e559 会话尾部有 `T:继续`（`_RESUME_PROMPT`）。
- **机制**：opencode_backend L608-624 silent-cut auto-resume 设置 `resume_session_id` → L658 `first_prompt = _RESUME_PROMPT`（"继续"）→ 复用会话。

### 证据 E8：diagnose 收到"继续"后的第一个动作 = 基于过时环境认知"回滚重来"

- diagnose 收到"继续"后的第一个动作文本：
  `I need to conclude this diagnosis. The environment (NPU 0 Alarm, 103 zombie processes, driver devmm errors) is broken, preventing verification. Let me [revert bisect]`
- 它**没有继续二分**，而是：
  1. 认定"环境坏了，验证被阻塞"
  2. **git checkout 回滚**二分残留
  3. 重新应用 ShiftF32 修复 → 重新验证
- **"环境坏了"是首跑（02:17）时的结论**，resume 时（08:47）环境状态可能已变——**会话历史里过时的环境认知污染了 resume 决策**。

### 最终根因判定：你的判断成立

**不是"清理中间状态"本身错**（回滚二分残留是合理的），**而是"清理的依据是过时的环境认知"**：

1. **resume 续会话保留旧上下文**（包括首跑的"环境坏了"误判）——这是"agent 上下文与代码、环境不一致"的根源。
2. **diagnose resume 后基于旧环境认知决策**（"环境坏了→回滚重来"），**未先重新校准环境/代码状态**。
3. **代码残留（二分注释）+ 过时认知（环境坏了）→ diagnose 重新开始**，但重新开始的依据是过时的。

### 这比"失败状态变化检测"（方案 D）更根本

- 方案 D 解决"diagnose 未跟踪失败状态随时间变化"（崩→不崩输出空）。
- **但更深的问题是**：**resume 续会话时，diagnose 依赖的上下文（环境认知/失败状态）可能过时**——它 resume 后基于旧上下文决策，而非重新校准。
- **需要补方案 E**：**resume 续会话后，diagnose 必须先"重新校准当前状态"**（重新检查环境/代码/失败状态，对比会话历史里的旧认知），再决定继续还是回滚。

### 方案 E（新增）：resume 后强制"状态重校准"

- **触发**：diagnose 检测到"这是 resume/续会话"（会话历史非空）。
- **动作**：先重新校准三件事——
  1. **环境**：NPU 状态 / 驱动 / zombie 进程是否与历史一致？
  2. **代码**：工作区代码是否与历史记录的"我改到哪"一致？（git status / diff）
  3. **失败状态**：当前 run-cases 失败是什么？（崩/输出空/精度）与历史记录的失败是否一致？
- **决策**：若三者与历史一致 → 继续历史进度；若不一致（环境恢复/代码被改/失败形态变化）→ 基于**当前真实状态**重新定位，不沿用旧认知。
- **为什么是根治**：这是"resume 语义的完整性"——续会话不是为了保留过时上下文，而是为了在**当前真实状态**下继续。状态重校准确保 diagnose 的决策基于最新状态，而非首跑的旧认知。

### 证据 E6：resume 后 diagnose 从 run_tests 重新开始认知

- resume 后 diagnose 第一个认知：`All 20 cases crash with 507035... Let me examine the operator source code`。
- **它完全重新开始**——从 run_tests 的 20/20 崩溃作为起点，重新读代码、重新定位。**没有"我是 resume 的，之前二分到 X"的任何认知**。
- ShiftF32 修复 commit（7839265）是 **09:03**（resume 后 diagnose 重新定位后 commit），首跑被杀（02:17）时**修复未完成未 commit**。

### 判定：不是"状态错位"，是"复合根因"

**排除"resume 状态错位"**：
- resume 后的代码/部署状态**保留了被杀前的真实状态**（二分残留 + 系统 OPP stale kernel + 20/20 崩溃 history）——这是准确的，不是被 resume 搞乱。
- diagnose 看到二分残留后自己 git checkout 回滚——它看到了真实状态，主动清理。

**真正的复合根因**（按权重排序）：
1. **环境故障**（NPU 0 Alarm + devmm 泄漏 + stale OPP kernel）——外部，非框架。首跑 diagnose 在环境故障期间做的大量二分**不可靠**（空 kernel 也崩 → 误判"不是 kernel 问题"）。
2. **diagnose 未跟踪失败状态变化**（方案 D 核心）：环境恢复后 iter-2 起 kernel 不崩（ShiftF32 修复生效）但输出空，diagnose 未及时看到/理解这个变化，仍基于 iter-1 崩溃 + stale OPP 假设上报。
3. **resume 重置诊断认知**（不是错位）：resume 让 diagnose 从 run_tests 重新开始，丢失被杀前二分进度。但这**不是坏事**——被杀前的二分在环境故障期间不可靠，重新开始反而避开污染。
4. **stale OPP kernel 的"强吸引"**：系统 OPP 有 stale kernel 是真事实且是"合理解释"，diagnose 容易归因它。

### 结论

- **不是 resume 状态错位**——resume 准确保留了被杀前状态，diagnose 主动回滚二分残留。
- **核心是可修问题**：diagnose 未跟踪"失败状态随时间变化"（崩→不崩输出空），固守旧失败认知。这由方案 D（失败状态变化检测）解决。
- **环境故障是外部**：NPU 0 Alarm / stale OPP 非框架可控，框架只需确保不误报（方案 B 矛盾检测）。

### 证据 E4：iter-1 与 iter-2 的崩溃状态对比

- **iter-1（08:50）**：崩溃——run.log 37 处 `errorStr`/`507035`，diff=999。
- **iter-2（09:26）**：不崩——0 处 `errorStr`，diff=0，输出空（shape [0] vs golden [19058]）。
- 36 分钟间隔，ShiftF32 修复在 iter-1→iter-2 之间生效。

### 证据 E5：diagnose 基于 iter-1 的崩溃 + stale OPP 假设上报，未意识到 iter-2 起修复已生效

- diagnose 在 iter-2（09:26）之前的验证（08:50-09:26）看到的都是 iter-1 的崩溃（37 处 errorStr）。
- 它同时发现"系统 OPP 有 stale kernel"（真事实）。
- 它基于"kernel 仍崩 + 系统 OPP stale"上报 upstream(deploy)。
- **它没有重新验证 iter-2 起"kernel 是否已不崩"**——被 stale OPP 假设带偏，未消费 iter-2 的"不崩但输出空"信号。

### 修正结论：误判的本质

- **不是"没坐实就报"**：diagnose 坐实了 iter-1 的崩溃（真实存在）。
- **而是"基于过时的失败状态归因"**：它坐实的是**旧的失败状态（崩）**，没意识到失败状态已变化（iter-2 起修复生效不崩）。它在"修复已生效但自己不知道"的情况下上报 upstream。
- **触发因素**：diagnose 连续多次验证（iter-1 崩 → redeploy → 二分 → 又崩），未在**每次验证前重新确认当前失败状态**，导致它带着"kernel 仍崩"的旧认知继续。

### 对方案的修正

- 方案 A（强制读 error_msg）**不够**：即使 diagnose 读了 iter-2 的 error_msg（形状不匹配），它可能仍认为"stale OPP 导致我验证的还是旧 kernel"（因为它 iter-1 看到崩）。
- **需要补一条纪律（方案 D）**：**每次单用例验证后，必须确认"当前失败状态"（崩/输出空/精度错），并与上一次对比**——若失败形态变化（崩→不崩输出空），说明修复生效，应重新校准归因（从"kernel 仍崩"改为"kernel 已修但输出错"）。
- **这就是"失败状态变化检测"**：diagnose 应跟踪"当前失败是什么"随时间的变化，而不是固守一个旧假设。

### 根治：能，靠"强制消费失败证据"这一确定性入口，非靠模型自觉

**根因不是 skill 没写，是模型没读失败证据**。所以根治点是**确定性入口**：

1. **强制第一步**：diagnose 每次 spawn，**必须先读 result.json 的 `error_msg` / `output_comparisons` / `total_count`**，基于失败证据分诊，再选定位方法。把"读失败证据"从"模型自觉"变成"结构化强制"。
2. **框架兜底**：即使 diagnose 漏读（模型不遵循），框架侧加**矛盾检测**——diagnose 报 upstream 时，若 result.json 的 error_msg 显示"形状 mismatch / 精度错"（本职责信号），WARN 并打回（§1.2 可观测性兜底）。**这是兜底能力，不是逐例补丁**：检测的是"上报理由与失败证据矛盾"这一结构性信号，覆盖所有"误报上游"形式。

**为什么这是根治而非补丁**：
- 补丁 = 加一条"遇到 stale OPP 别报 upstream"（只堵本次）。
- 根治 = "读失败证据 → 按形态分诊"（覆盖所有失败形态的归因）+ "上报理由与证据矛盾即打回"（结构性兜底，不枚举具体错误类型）。

### "是不是限制太多"：不是限制太多，是缺少一个"最小引导"

**证据**：diagnose 有能力继续探索（工具齐全），但**没读失败证据就归因**。自由探索**并未发生**——它过早收敛到环境归因。

**为什么模型跳过失败证据**：
1. **"修好崩溃"给了错误完成感**——后续失败倾向归因外部。
2. **环境异常强吸引**——stale OPP 是真事实且是"合理解释"，比深挖 kernel 输出逻辑成本低。
3. **归因环境 = "诚实报告"**——模型觉得这是合理停止点，不违反"如实上报"。

**"自由探索能解决"的成立条件**：如果 diagnose 读了 error_msg（"形状不匹配"），它会发现"不是 deploy，是输出逻辑"，从而继续修。**所以引导它读失败证据（最小引导）= 让探索发生在正确方向**，不是更多限制。

**反直觉之处**：不是"限制太多压制了探索"，而是"没有确定性入口让探索从正确起点开始"。自由探索若无失败证据入口，会发散到环境假设；有入口则收敛到真因。

## 七、方案选项（更新）

### 方案 A：结构化失败分诊（推荐，升级为"强制入口"）
- **强制第一步**：diagnose 每次 spawn 先读 result.json 的 `error_msg` / `output_comparisons` / `total_count`。
- 按失败形态分诊（不枚举具体错误类型，只分流定位方法）：
  - `error`（崩溃/507035）→ 解码错误码 → 查越界/对齐/同步。
  - `形状不匹配/空输出` → 比对 shape（output vs golden）→ 查输出写入/元素数/host tiling 的 y shape 计算。
  - `精度错`（max_diff>0）→ 数值发散点 → 查 API 约束。
  - `环境错`（NPU Alarm/驱动/无 error）→ 上报 upstream。
- **为什么不是打补丁**：补的是"读失败证据→按形态分诊"的方法论，覆盖所有失败形态，非单点规则。
- **判据（§1.14）**：分诊是"帮模型"（给定位起点），不枚举具体错误类型——符合删控模型留帮模型。

### 方案 B：框架兜底矛盾检测（升级为"结构性兜底"）
- diagnose 报 upstream 时，框架校验：result.json 的 error_msg 是否显示"本职责信号"（形状 mismatch/精度错/崩溃）？
  - 若显示本职责信号但 diagnose 报 upstream → **WARN + 打回 diagnose**（不给框架 halt）。
  - 若 error_msg 是环境类（无本职责信号）→ 放行 upstream。
- **为什么是兜底不是补丁**：检测"上报理由与失败证据矛盾"是**结构性信号**，覆盖所有"误报上游"形式（环境当 kernel、kernel 当环境、host 当 kernel），非逐例规则。

### 方案 C：upstream 上报前强制"归因验证"
- 上报 upstream 前必须写：当前失败的具体形态（error 文本/精度值/形状），以及"为什么这不是 diagnose 能修的"。
- 优点：防止"没看失败形态就归因"（本次 diagnose 正是没写失败形态）。
- 缺点：单独用是治标（若没 A 的分诊，diagnose 仍不知看什么）；与 A/B 组合则形成完整闭环。

### 方案 A+B+C 组合（推荐）
- **A 为主**（强制失败证据入口 + 形态分诊），**B 为兜底**（矛盾检测），**C 为纪律**（上报前写失败形态）。
- 按 §1.2 组合：A 承担主修复（方法论），B 承担宽容兜底（防误报上游），C 承担可观测性（上报理由可核）。
- **判据**：三者共同确保"失败证据先于归因"，从结构上消灭"跳过证据归因环境"这类误判，而非逐例打补丁。

## 六、验证（TDD）

- **UT**：diagnose 的失败分诊逻辑（error/形状/精度/环境的分类）确定性测。
- **ST 非 heavy**：用构造的"输出空"失败场景，验证 diagnose 分诊到"形状/空输出"定位路径（不归因环境）。
- **heavy_llm**：真实跑一个"输出空"算子，验证 diagnose 能定位到输出写入/元素数问题而非归因环境。

## 七、回退与边界

- 方案 A 只改 diagnose 的方法论描述（SKILL.md + prompt），不动框架路由——可独立回退。
- 不碰 §1.14（不枚举错误类型）——分诊不枚举，只是给定位起点。
- 不碰 §1.13（比对 golden）——分诊后仍比对 golden，只是先看失败形态。
