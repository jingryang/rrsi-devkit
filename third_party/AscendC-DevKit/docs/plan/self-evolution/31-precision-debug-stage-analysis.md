# P53/P54 — 精度失败后 in-stage 调试闭环 — 方案分析（第三层）

> 状态：**方案冻结**（2026-07-09）。主导方向 = 选项 B（独立精度调试 stage，agent 内闭环迭代，不回 codegen）。选项 A（patch verify→codegen 反馈链路）被 B 取代为静态策略。待立 L4。
> 层级：**第三层 / 方案分析**。选项 + 取舍 + 待定。
> 覆盖问题：P53（精度失败反馈链路三连断裂）+ P54（精度失败后无 in-stage 调试闭环需求）。
> 输入：run `20260707-091803-29a24f` verify `precision_failed` loopback 回 codegen 但反馈失真（P53）+ 用户提出精度失败应 in-stage 闭环调试、debug workflow 可复用（P54）。
> **承接**：self-evolution-design.md §2.2 (a) inference-time 单算子自我修正 + **P45/P47（设计侧 in-stage 闭环 + 反馈消费自检，本条是其精度调试边界的对偶）** + **P51（灰区 loopback + `exhausted → __halt__` 止损交人，本条复用同一止损出口）** + **P50/P46（分类驱动路由的先例）**。
> 约定：按符号定位（不写 file:line）；外部依赖只读。

---

## 1. 定位：P53 是「回 codegen」路径的具体缺陷，P54 是对该路径的整体重设计

精度失败后怎么办，目前只有一条路：`verify precision_failed → codegen (corrective)` loopback。P53 诊断出这条路**三处断裂**（反馈失真 + 不可见 + 不被消费）；P54 不修这条路、而是**重设计绕开它**——精度失败改走独立精度调试 stage，agent 在 stage 内闭环迭代，不再跨 stage loopback 回 codegen。

二者的产权边界（§1.8）：
- **P53（L1 事实）**：回 codegen 路径的三连断裂是客观缺陷。**重设计后该路径不再被精度失败走**，故 P53 的「loopback 无原因 / codegen 无消费自检」两点**被绕开**（不再有 verify→codegen 这段 loopback）；但 **phantom max_diff 字段读取 bug 是独立的**——`verify.transition` 产出的 `precision_result` 要被新 debug stage 消费，读错字段照样失真，**仍需修**。
- **P54（L1 需求）**：in-stage 调试闭环 + debug workflow 复用的目标态。本 L3 + L4 落地。

---

## 2. 现状：精度失败→codegen loopback 的三处断裂（P53 事实，简引 L1）

精度失败 loopback 回 codegen，反馈链路三处断裂（详证见 L1 P53）：

1. **phantom max_diff=0.0**：`VerifyStage.transition` 读 `gate_result.get("max_diff")`（顶层），但 max_diff 在 `gate_result["metrics"]`（`PrecisionGate.evaluate` / `NPURunner.execute` 组装）。同函数内 `stubbed` 却正确从 `metrics` 读——两读法不一致。结果 `PrecisionResult.max_diff` 恒 0.0，`CodegenStage._build_codegen_prompt` 拿到 phantom 0.0，`VerifyStage.error_signature` 恒 `precision:max_diff=0.000000`（停滞检测 `same>=2` 误判）。
2. **loopback 日志无失败原因**：`VerifyStage` 不 override `blocking_issues()`（base 默认 `[]`），`_log_loopback` 打不出"精度不达标 max_diff=?"。
3. **codegen 无反馈消费自检**：P47 给设计侧加了 `ascendc-op-design-feedback-selfcheck`（逐条 acceptance 全量回验），codegen 侧无等价物——精度反馈进 prompt 但「是否被消费」是 LLM 概率行为。

**根因**：P45/P47 闭环了**设计侧**的反馈消费，**codegen 侧**未同步——同一类缺口在 codegen 边界重现。

---

## 3. 认知校正（用户主导）：精度调试属 inference-time 自我修正，应在 stage 内闭环

> **本 L3 的理论基石，由用户在讨论中提出，推翻了「A：patch 反馈链路就够了」的隐含前提。**

### 3.1 错的前提：精度失败 = 代码错 = 重生成能修

前序讨论一度把问题框成「精度失败回 codegen 是对的，只是反馈链路断了，修好 P53 三连断裂即可」。**这个框定太窄**。它假设精度调试的信息需求 = codegen 重生成所需信息（一个 max_diff + 失败原因）。但精度调试真正需要的是**全链诊断信息**：哪个 case 失败、哪个元素差多少、为什么（dumptensor 中间值、print 日志、bottleneck 定位）。这些经 loopback 的 prompt 注入承载不了——loopback 上下文必然损失。

### 3.2 正确的判据：精度调试是 inference-time 单算子自我修正，应 in-stage 闭环

> self-evolution-design.md §2.2 (a)：inference-time 单算子自我修正——给定算子代码 + 用例 + golden，在不动训练 loss 的前提下迭代修正精度。

精度调试天然符合这个形态：
- **输入**：算子代码 + 测试用例 + golden（最小输入集，与 codegen/design 产物无关）。
- **过程**：改代码 → 重新部署 → 跑用例 → 看日志（dumptensor + print）→ 定位根因 → 再改。**同一 agent 内迭代**，上下文不丢、不频繁重启。
- **输出**：精度通过的代码（git 历史 + 最佳 commit）。

跨 stage loopback 回 codegen 的三个硬伤（用户论证，P54 事实）：
1. **上下文损失**：loopback 的 prompt 注入承载不了全链诊断信息。
2. **频繁启 agent 耗时**：每轮重启 codegen agent 丢上文、重建会话，比同 agent 内迭代慢。
3. **debug workflow 不可复用**：未来「别人对算子代码提精度 issue」场景只有 代码仓 + 算子代码 + 用例 + golden，**没有 codegen stage**。精度调试绑死在 codegen loopback 里 → 独立解 issue 场景无法复用。

### 3.3 这不是新架构——P45/P47 已经做过同形 in-stage 闭环

**P45/P47（设计侧）已经做了完全同形的 in-stage 闭环 + 反馈消费自检**：设计阶段三 tiling skill 在 stage 内迭代，`ascendc-op-design-feedback-selfcheck` 读全部历史轮 issue 的 acceptance 逐条全量回验、修不了如实标 unresolved、复用既有停滞 halt。B 就是**把同一条 in-stage 闭环原则从设计边界扩到精度调试边界**。已有先例、已被项目接受，符合 [[avoid-overdesign-prefer-reuse]]、§1.2（同类新情况自动正确归位）。

---

## 4. 选项（B 主导，A 为背景）

### 选项 B —— 独立精度调试 stage，agent 内闭环迭代（主导方向）

- **判据**：见 §3.2。精度调试 = inference-time 自我修正，in-stage 闭环。
- **落点**：新 `PrecisionDebugStage`（`fail_strategy="continue"`），`verify precision_failed → precision_debug`（不再 → codegen）。stage 内 agent 闭环迭代：改码 → git commit → redeploy → 跑用例 → dumptensor 日志 → 再改。轮数耗尽或全部解决。
- **复用**：deploy 能力抽 `Deployer` 服务（§2.5 单一通路），`DeployStage` + debug stage 共用；止损复用 P51 的 `exhausted → __halt__`；灰区/可修分类复用 P50/P51 先例。
- **为何主导**：唯一符合 §3.2 判据——既不损失上下文（不像 loopback）、又让 debug workflow 可复用（输入契约 = code+cases+golden，与 codegen 解耦）。

### 选项 A —— patch verify→codegen 反馈链路（修 P53 三连断裂）❌ 被 B 取代

A 修 phantom 字段读取 + 给 verify 加 `blocking_issues` override + 给 codegen 加反馈消费自检 skill。三处都是对「回 codegen」路径打补丁。**被 B 取代的理由**：A 假设「精度失败回 codegen 是对的」（§3.1 错前提），即便补丁打满，loopback 的上下文损失 + debug workflow 不可复用两个硬伤仍在（§3.2）。A 只修了症状（反馈失真），没解决结构问题（跨 stage loopback 不该承载精度调试）。

> **A 的合理部分被 B 吸收**：phantom max_diff 字段读取 bug 是**独立的纯 bug**，B 不绕开它——`verify.transition` 产出的 `precision_result` 仍被 debug stage 消费，读错字段照样失真。B 的 L4 必须修这个字段读取（A 的第 1 点）。A 的第 2、3 点（loopback 可见性 / codegen 消费自检）被 B 绕开（精度失败不再走 verify→codegen loopback，改走 verify→precision_debug；debug stage 是 agent 内迭代、自读日志确认，不需要 codegen 侧 skill）。

---

## 5. 取舍

| 选项 | 落点 | 评价 |
|---|---|---|
| **B 独立精度调试 stage（主导）** | 新 `PrecisionDebugStage` + `verify precision_failed → precision_debug` | ✅ 主导。唯一符合 §3.2 判据；上下文不丢；debug workflow 可复用；复用 P45/P47 in-stage 闭环 + P51 止损 |
| A patch 反馈链路 | 修 verify→codegen 三连断裂 | ❌ 修症状不修结构（loopback 上下文损失 + 不可复用仍在）；被 B 取代。A 第 1 点（phantom 字段）被 B 吸收为独立 bug 修复 |

---

## 6. 决策冻结（D1–D11）

### D1 — 路由分流：`verify precision_failed → precision_debug`（不再 → codegen）

`self_evolve_op` TRANSITION_TABLE 的 `verify` 分支：`precision_failed: ("codegen", "corrective")` 改为 `("precision_debug", "corrective")`。`build_failed → codegen` 不变（编译失败仍回 codegen，因 codegen 是代码生成源、有生成上下文）。`exhausted → __halt__` 不变。

**codegen 编译保证不变**：进入 precision_debug 前代码必可编译——由 `VerifyStage` 的 `BuildInRepoGate` 兜（build_failed → codegen）。precision_debug 内的编译失败是 agent 自己改坏的，in-stage 自修（D4），不回 codegen（codegen 无调试上下文）。

### D2 — stage 内 agent 闭环迭代（不回 codegen）

`PrecisionDebugStage.actions` 派发一个 debug agent，agent 内部循环：改代码 → git commit（D6）→ redeploy（D3）→ 跑用例（D11）→ 读 dumptensor+print 日志（D7）→ 按失败用例优先级排修复（D10）→ 再改。轮数耗尽（D9）或全部用例通过为止。**整轮在单 agent 会话内完成**，不跨 stage loopback。

### D3 — 复用 deploy 能力：抽 `Deployer` 服务（§2.5 单一通路）

把 `DeployStage` 的 `_run_profile_chain` / `_per_op_path` / `_template_vars` / `_run_command` / `_run_smoke` / `_cann_lib_paths` / `_callable_target` 抽成 `Deployer` 服务（domain 或 service 层）。`DeployStage` 与 `PrecisionDebugStage` 共用同一 `Deployer`——per-op 覆盖式安装（新 .so 即时生效），不重写 deploy 链。**删除被取代的旧通路**（§2.5）：`DeployStage` 内联的 deploy 逻辑收敛到 `Deployer`，不留两套。

### D4 — 编译失败 in-stage 闭环（不回 codegen）

agent 改代码引入编译错 → redeploy 的 build 步骤失败 → stderr 给 agent → agent 在 debug stage 内自修（改对再 commit）。**不回 codegen**：代码是 debug stage 改的，codegen 无调试上下文。轮数耗尽（D9）→ 回退最佳 commit（D6）+ 转人工。

### D5 — debug skill 输入契约 = code + cases + golden（debug workflow 可复用）

debug skill 的输入契约 = 算子代码（仓内 op_dir）+ 测试用例（cases）+ golden（参考实现）。**不依赖 codegen/design 产物**（不读 codegen_manifest 的设计上下文，只读 callable_target 用于部署）。→ 未来「独立解精度 issue」场景（只有 代码仓 + 算子代码 + 用例 + golden，无 codegen stage）可直接复用该 stage / skill。符合 §2.1（skill 即插即用、不耦合工程框架）、§2.3（文件接力契约）。

### D6 — 修复历史追踪：每轮 git commit（防震荡不收敛）

agent 每轮修改 git commit（commit message 带修改说明 + 失败用例 + 根因假设）。目的：(1) 追踪修复历史，agent 可回看前几轮改了什么、为何没修好，避免重复试错；(2) 轮数耗尽（D9）时回退到**精度最好的 commit**（max_diff 最小或通过用例最多）作为最终产物，而非保留最后一轮可能更差的代码。防「越改越差」震荡。

### D7 — dumptensor + print 日志落盘（防上下文压缩丢失）

每轮跑用例的 dumptensor 中间值 + agent 加的 print 日志落盘到工作目录（per-run artifacts）。agent 读文件而非靠会话记忆——长调试会话上下文可能被压缩，落盘保证中间观测不丢。符合 §1.2 可诊断（异常路径留可观测信号）。

### D8 — 修 P53 phantom max_diff 字段读取（独立 bug，B 不绕开）

`VerifyStage.transition` 的 `max_diff` 改从 `gate_result["metrics"]` 读（与同函数 `stubbed` 读法一致）。`PrecisionResult` 扩展承载 debug stage 所需的 per-case diff / bottleneck 信息（precision gate 已产出，现被丢弃，L4 定字段）。`error_signature` 读到真实 max_diff，停滞检测不再误判。

> P53 第 2、3 点（loopback 无 blocking_issues / codegen 无消费自检）**被 B 绕开**：精度失败不再走 verify→codegen loopback，改走 verify→precision_debug；debug stage 是 agent 内迭代、自读 dumptensor 日志确认修复，不需要 codegen 侧反馈消费 skill。故这两点不单独修（修了也是死代码——路径不走）。

### D9 — 收敛兜底：`debug_iterations >= max → exhausted → __halt__`（复用 P51 止损）

`PrecisionDebugStage` 复用 P51 的止损形态：`debug_iterations >= effective_max_iterations → resolve_condition 返回 "exhausted" → TRANSITION_TABLE ("__halt__", "escalation")`。轮数耗尽 → 回退最佳 commit（D6）+ 完整根因落盘 + 移交人工（与 P51 灰区止损同出口）。**不新增交互式挂起问人出口**（[human-review-as-stage] 独立方向）。

### D10 — skill 内容职责边界（§2.7）：确定性脚手架外移，核心引导归 skill

- **脚手架外移（CLI 命令，D11）**：build / install / smoke / run-cases 是确定性操作，封装成 CLI 命令，agent 通过 CLI 调用（不直接 Python import 编排内部）。LLM 通用能力参考目标仓模式生成调用，不写进 skill。
- **核心引导归 skill**：精度调试 skill 承载 dumptensor 定位根因的方法 + 失败用例优先级排序 + 修复策略引导（如「先修最大 diff 的 case」「同方向偏差→系统性 tiling/计算错」「单 case 错→边界条件」）。这是跨实例（跨算子）通用的领域核心，符合 §2.7。

### D11 — CLI 命令族：`redeploy` / `run-cases`（同族，debug agent 调用）

新增 CLI 命令（click，`cli/commands/` 下）：
- `redeploy`：对当前 op 重新 build + install + smoke（复用 D3 `Deployer`，per-op 覆盖式安装）。
- `run-cases`：对当前 op 跑全部/指定用例，输出 max_diff + per-case diff + dumptensor 日志路径（复用 `NPURunner`，落盘 D7）。

debug agent 通过这两个 CLI 完成部署+验证循环，不直接 import 编排内部（解耦、可独立复用，呼应 D5）。

---

## 7. 待澄清（已收敛）

1. **A vs B（§4）**：✅ **已拍板 = B**（in-stage 闭环）。A 被 B 取代，但 A 第 1 点（phantom 字段）被 B 吸收为独立 bug 修复（D8）。
2. **codegen 编译保证**（D1）：✅ 进入 debug stage 前必可编译，由 `VerifyStage.BuildInRepoGate` 兜（build_failed → codegen 不变）。codegen 不新增编译门。
3. **debug stage 内编译失败**（D4）：✅ in-stage 自修，不回 codegen（codegen 无调试上下文）。轮数耗尽回退最佳 commit + 转人工。
4. **止损出口**（D9）：✅ 复用 P51 `exhausted → __halt__`（escalation），不新增交互式挂起问人。
5. **deploy 复用**（D3）：✅ 抽 `Deployer` 服务单一来源，`DeployStage` + debug stage 共用，删旧内联通路（§2.5）。
6. **debug workflow 复用**（D5）：✅ skill 输入 = code+cases+golden，与 codegen 解耦。

---

## 8. 与现有工作的关系

- **P45/P47（设计侧 in-stage 闭环 + 反馈消费自检，已闭环）**：B 是其精度调试边界的对偶。同形原则（stage 内迭代 + 确定性消费自检）从设计边界扩到精度调试边界。设计侧用 `feedback-selfcheck` skill 做 acceptance 全量回验；精度调试侧用 dumptensor 日志 + 跑用例做修复确认（不同载体，同确定性消费思路）。
- **P51（灰区 loopback + `exhausted → __halt__` 止损，已闭环）**：B 复用其止损出口（D9）+「halt+落盘交人」形态。P51 是 verify 硬崩溃的控制流；B 是 verify 精度软失败的调试闭环——同属 verify 失败后的处理，但 P51 管崩、B 管精度差。
- **P50/P46（分类驱动路由先例，已闭环）**：B 的路由分流（precision_failed → debug stage）是 TRANSITION_TABLE 既有模式的自然扩展，不引入新路由机制。
- **P53（反馈链路三连断裂，本 L3 覆盖）**：B 绕开「回 codegen」路径（第 2、3 点不修）；phantom 字段读取（第 1 点）是独立 bug，B 的 D8 修（debug stage 也要读对 max_diff）。
- **P54（in-stage 调试闭环需求，本 L3 覆盖）**：B 是其直接落地。
- **self-evolution-design.md §2.2 (a)**：B 属 inference-time 单算子自我修正，独立于 (b) training-time loss 迭代。
- **CLAUDE.md §2.5（唯一通路）**：D3 抽 `Deployer` 单一来源，删 `DeployStage` 内联旧通路。
- **CLAUDE.md §2.7（核心归 skill、脚手架外移）**：D10/D11 确定性 build/install/smoke/run-cases 封装 CLI，精度调试引导归 skill。
- **[human-review-as-stage]（独立方向）**：B 的「轮数耗尽转人工」复用既有 `__halt__`+落盘，不新增交互式挂起问人 Stage。若未来要把人工决策建模为主动 Stage，归 [human-review-as-stage]，B 不预占。

---

状态：**方案冻结**（2026-07-09）。主导方向 = 选项 B（独立精度调试 stage，agent 内闭环迭代）；phantom 字段读取 bug 由 D8 修；止损复用 P51 `exhausted → __halt__`。下一步立 L4（`31-precision-debug-stage-impl.md`）。L2 step 28 跟踪本条。
