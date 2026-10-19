# L3 — chip 目标代际选择：方案分析

> 选项、决策、理由。调研中演进、拍板后冻结。
> 问题事实见 `01-problems.md`（L1）；相关已结工作 `chip-gate-precondition/`（step-32）、`chip-version-generation/`（step-17）。

## 总览（一句话）

把「为哪个代际设计」与「本机是哪个代际」拆成两个独立字段、各挂对的权威源；探机在能产出真相时是最高权威；老 `--assume-chip`（值携带、同时顶替两侧的 footgun）拆成两个职责分明的 flag 退役。前置确认闸在 design 前拦「想跑本机却设错代际」，run gate 在 build/run 前诚实拦「产物代际 ≠ 本机硬件」。

## 实施期核实修正（对 D1-D8 的精化，L4 落实时发现）

下列 7 条是对 D1-D8 原叙述的精化/纠正，落 L4 时已逐条核实符号与调用点，是本方案的最终实施口径（原 D 段落不再逐句改写，以此节为准）。

1. **gate 简化（精化 D2）**：`runtime_target_chip` 已在 dispatch 期一次性解析，run gate 无需再探机。`chip_mismatch_reason` 改纯双参 `(design_target, runtime_target) -> str|None`——删 `assume_chip` / `timeout_sec` / 内部 `detect_chip_version` 调用。消除 dispatch 与 gate 的**双重探机**；gate 变纯函数（UT 无需 monkeypatch detect）。原 D2「比较 design_target vs 探机」按「比较 design_target vs dispatch 已解析的 runtime_target」理解。
2. **design_target 全序纳入 profile-default（补 D1）**：context stage 此前把仓库构建变体 `default_chip` 作未列出的第 4 源覆盖 target。集中化为单一全序 **`CLI > 需求文档 constraint > profile-default > 探机(if known)`**，在 context stage 一处落地；requirement stage 只做 req 覆盖（既有 `_apply_design_target_chip` 保留、改写字段名）。位次理由：用户显式意图 > 算子需求意图 > 仓库设计默认 > 本机碰巧的硬件。
3. **前置闸落 `GeneralDesignStage.actions`（补 D3）**：`validate_inputs` 硬绑 `PreconditionError`（不可恢复），**不能**用于可恢复闸；前置闸在 design 组第一个 stage 的 `actions()` 开头返回 `[AskUserQuestion(...)]`，走 runner abort→pending→`DecisionPendingError` 链。transition 消费 decision：「改打本机」→design_target 改写为 runtime_target；「跨代设计」→置确认标记继续。
4. **前置闸强依赖 decision_response 回放（前置修复）**：runner `_execute_ask_user_question` 全程不读 `decision_response.json`，路径 A 在非交互+resume 下会重写 pending 死循环。实施先于前置闸给 runner 加 decision_response 回放分支（镜像 `capabilities/mcp_tools` 的回放逻辑）——这是前置闸可恢复 resume 的硬前提。
5. **schema 真正驱动产出的是 requirement.json 的 example（补 D4）**：`op_spec_schema.md` 是不被 enforce 的参考文档；真正经 `ArtifactSpec.to_prompt_block` 渲染进 prompt 的是 `schema/requirement.json` 的 `example.constraints`。两份都改，但 example 是关键。
6. **events 必须在 dispatcher 层写（补 D8）**：stage 层拿不到 `_event_log`；芯片决策 event 在 dispatcher 解析完两字段后写（`chip_decision` helper，复用 `make_event`），字段含 design/runtime 双值 + 各自 source（cli/probe/timeout-fallback）+ mismatch 标记。
7. **L1 P3 措辞纠正（已改 L1）**：`_apply_design_target_chip` 实际有 `Logger.info`/`Logger.warn`，P3「无日志」不准确；L1 P3 已改为「有日志但压成单字段、设计/运行两语义无法分别表达」。

## D1 — 双字段：design_target_chip（意图）+ runtime_target_chip（真相）

**选项**：(a) 维持单 `target_chip` + requirement 阶段 silent override；(b) 拆双字段，设计意图与运行真相各得其所。

**选 b**。理由：单字段无法表达跨代设计（P6：设计代际可能 ≠ 本机硬件），且 silent override 违反可诊断（P3）。两个正交事实——「为谁设计」（人/需求决定）与「本机是啥」（硬件决定）——本就该两个字段。

| 字段 | 语义 | 赋值优先级 | 权威源性质 |
|---|---|---|---|
| `design_target_chip` | 设计/编译目标代际（意图） | `--design_target_chip` > 需求文档 > 真实探机 | 声明型：最显式的人为声明优先；探机仅作「未指定时按本机设计」的默认 |
| `runtime_target_chip` | 运行期在场硬件代际（真相） | 真实探机 > `--runtime_target_chip` | 探测型：探机在场即权威；`--runtime_target_chip` 仅探机超时兜底 |

**关键约束**：`runtime_target_chip` 与需求文档**无任何关联**——req 表达「设计给谁」，runtime 是「这台机器是啥」，正交不该串（用户拍板）。

**消费面归属**：`design_target_chip` 承接现 `target_chip` 的消费角色（codegen / precision_debug / Deployer 都读它——build 跟 design_target）；`runtime_target_chip` 是 run gate 的硬件侧。**不变式：build 跟 `design_target_chip`**（编译产物 soc = 设计目标代际）——设计给 A5 就按 A5 的 soc 编译，绝不拿 A5 的 tiling 编进 A2 二进制（A5 分块在 A2 UB 越界 / A5 独有指令在 A2 不存在）。`soc_version` 仍是 `to_soc_version` 的纯函数派生，不作为 state 冗余字段（step-17 不变式延续）。

## D2 — run gate：本地能跑 ⟺ design_target == runtime_target

`design_target != runtime_target`（= 探机）= **跨代构建**（A5 产物在本机 A2 跑不了，拿去 A5 硬件跑），是合法分支、非报错。run gate 只诚实告诉操作者「这产物跟本机硬件不匹配，别在本机跑」。

复用既有 `chip_mismatch_reason`（单一来源 §2.5），比较 `design_target` vs 探机（即 runtime_target）。

**纠正前几轮错误认知**：在「build 跟 design_target」前提下，`design_target != runtime` **不是**「设计过期要 loopback 重跑 design」——设计永远与其 design_target 自洽，产物也跟 design_target 自洽。divergence 是合法跨代路径，不是 staleness。（早前「设计过期信号 → 重跑」的 loopback 框架建立在「build 跟 runtime」的错假设上，作废。）

## D3 — 前置确认闸（design 前，吸收用户建议 1）

requirement 之后、design 之前（`design_target_chip` 在此终态化），若 `design_target != 探机` **且** workflow 含本地 build/run，先问用户：你在跨代设计（产物拿别处跑）还是其实想跑本机（那 design_target 该设成探机代际）？默认 halt。

**机制**：复用既有 `AskUserQuestion` / `DecisionPendingError`（**可恢复暂停**，respond + run --resume），**不是** `__halt__`（终态不可恢复）。术语上「默认 halt」= AskUserQuestion 默认选项 abort，机制本身是可恢复的那个。

这闸把用户最初的坑（想跑本机却设成 A5）在 design 前拦下，不用等 design 全做完。

## D4 — 接通 design_target_chip schema（解 P2）

D1 能被需求文档**驱动产出**的前提：requirement 机器校验 schema 加 `design_target_chip` 字段（挂在 hardware-kind constraint）；人读 schema 词表对齐 canonical A2/A3/A5、位置挪进 constraints。否则 D1 再漂亮也吃不到 agent 产出（加载期校验 §1.3；不留旧词表 §1.4）。这是整个方案的**主修复前置**——不接通，design_target 永远不会被需求文档驱动产出。

## D5 — 探机为最高真相 + 修 missing-hardware 静默 fallback（解 P5）

`_probe_chip_blocking` 的 missing-hardware 分支（torch_npu 缺失 / 0 设备 / 未知名）返回 distinct `unknown`，**非**伪装 A2——让「无硬件」可识别，与 §3.7「不静默回落到猜测芯片」对齐（口径统一 hang 与 missing 两类）。探机成功即真，在该校验硬件处能跑就跑。

## D6 — --assume-chip 退役，拆为两 flag（解 P3/P4）

老 `--assume-chip` 是 footgun 的根因：一个值携带的 flag 同时想当「设计意图」又当「硬件断言」，且经 dispatcher 兜底泄漏进 target 侧，使 gate 退化为恒等式。

拆为职责分明的两个 flag（与 D1 两字段一一对应）：
- `--design_target_chip`：design 侧意图，design_target_chip 赋值最高优先级。
- `--runtime_target_chip`：runtime 侧，**仅**探机超时兜底（探机成功时无效，不可撒谎）。

删 `--assume-chip`（值携带断言）+ dispatcher `resolved_chip` 兜底里 assume_chip 流入 target_chip 的泄漏。

**flaky-timeout 场景**（用户确认真实存在）：探机超时 → `runtime_target_chip` 退回 `--runtime_target_chip`（带 warning，标「硬件未校验」）；探机成功 → 用真值，`--runtime_target_chip` 无机会生效。即「探机扛不住时给你兜底，但探机能跑时不替你背书 target 对不对」。老 footgun（值同时顶替两侧）随之消失。

## D7 — CANN 跨代编译可行性区分

跨代**设计**自由（只需 chip-spec 静态资源，A2/A3/A5 都有）；跨代**编译**需本地 CANN 对目标 soc_version 有编译支持——本机 CANN 通常只装本机芯片的 soc。故 `design_target != 探机` 时，跨代编译可能因 CANN 不支持该 soc 而失败（CANN 能力问题，**非**芯片一致性错）。build 闸把两类分开报：「硬件不匹配」vs「CANN 编不了这个 soc」。

## D8 — 可观测性：芯片决策入 events.jsonl

`design_target_chip` / `runtime_target_chip` 的**来源**（CLI / req / probe-default / timeout-fallback）+ 任何 mismatch + 用户在前置闸的选择，全部记 `events.jsonl`（Event Sourcing 权威记录），不只打 stdout（满足「必须打印在日志上」，且可 resume / 审计）。

## 四把尺子（§1.2）

- **可维护**：两个正交事实两个字段，消除单字段 silent override 的歧义；schema 接通后 design_target 由需求驱动产出，不再悬空。
- **可扩展**：新代际只改 canonical 单源（`domain/chip.py`，step-17 已立）；前置闸 / run gate / 两 flag 模式对任意代际自动归位。
- **可诊断**：前置闸 + run gate 各具名两个代际值 + 可操作建议；芯片决策来源入 events.jsonl；missing-hardware 不再伪装 A2。
- **架构合理**：意图（design_target）落 requirement/CLI（人决定），真相（runtime_target）落 adapter 探机（硬件决定），判断复用 `chip_mismatch_reason`（L4 adapter），前置条件落 stage（L3），halt 通道落 DecisionPendingError / PreconditionError → dispatcher。各层职责正确，不越层兜底。

## 候选选项汇总

| 决策点 | 选项 | 取舍 |
|---|---|---|
| 单/双字段 | (a) 单 target_chip + silent override / (b) 双字段 | 选 b：跨代设计（P6）+ 可诊断（P3） |
| `--assume-chip` 去留 | (a) 保留翻转语义（值作预期值供探机校验）/ (b) 去值化只留超时放行口 / (c) 拆成两 flag 退役 | 选 c：两 flag 与两字段一一对应、职责最清；flaky 兜底由 `--runtime_target_chip` 承接 |
| 前置闸机制 | (a) `__halt__` 终态 / (b) `DecisionPendingError` 可恢复暂停 | 选 b：用户要「决策是否继续」，需可恢复 |
| 探机 missing-hardware | (a) 维持伪装 A2 / (b) 返回 unknown | 选 b：与 §3.7 口径一致、可识别 |

## 不改（范围边界）

- `to_soc_version` 翻译点（step-17 已立，A2→ascend910b / A3→ascend910_93 / A5→ascend950）不动。
- `chip_mismatch_reason` helper 保留并复用（step-32 已立，单一来源）。
- precision_debug 自修循环不动。
- TRANSITION_TABLE / workflow stage 注册：前置闸复用既有 DecisionPendingError 通道，不新增 stage（对齐 step-32「precondition 不新增 stage」先例）。

## 实施摘要（L4 待写，本次不改代码）

变更落点（符号级，L4 详化时展开 + TDD）：
1. **domain**：`design_target_chip` / `runtime_target_chip` 双字段进 State；`design_target_chip` 承接现 `target_chip` 消费面（codegen/precision_debug/Deployer 读它），`runtime_target_chip` 作 run gate 硬件侧；`soc_version` 仍 `to_soc_version` 纯函数派生不冗余。
2. **requirement schema**：机器校验 + 人读对齐 `design_target_chip`（D4）。
3. **adapters/npu/detect**：`_probe_chip_blocking` missing-hardware 返 `unknown`（D5）；`chip_mismatch_reason` 比较改 design_target vs 探机。
4. **CLI**：删 `--assume-chip`，加 `--design_target_chip` / `--runtime_target_chip`（D6）；删 dispatcher 兜底泄漏。
5. **前置闸**：requirement→design 边界加 design_target≠探机 的 AskUserQuestion（D3）。
6. **events**：芯片决策来源入 events.jsonl（D8）。

## 开放项

- 跨代编译在本机 CANN 单 soc 时是否 fail-fast（build 前探 CANN 能力，避免浪费 build）——D7 的实现细节，L4 定。
- design_target 走「默认 = 探机」时前置闸不触发（design_target == probe），此时跨代只能靠显式 CLI/req 触发闸——确认这是期望行为。
