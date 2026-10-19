# 平台目标与演进设计（草案）

> 状态：草案 v0.7（2026-06-29），分层展开，分多次细化。
> **主线是 §1–§5（北极星 / 心智模型 / 分层 / 原则 / 现状定位）**；§6 积木清单是候选实现细节，**非主线**，待上层契约定后再细化。
> **文档纪律**：方案只承载稳定物（北极星 / 心智模型 / 原则 / 目标态契约 / 优先级 / 待定问题）；**不写 `file:line` 行号、不维护代码现状快照**——与仓 CLAUDE.md「以代码为准、避免维护易滞后快照」纪律一致（本仓多人活跃修改，行号与现状随时漂移，固化进方案实施时必然对不上）。引用代码一律用语义锚点（类名 / 方法名 / 接口签名）。

---

## 1. 北极星

**通过当前工程，生成可直接应用到生产的 AscendC 算子代码。**

「生产可用」隐含一套标准（精度 / 性能 / 多平台 / 与主线仓集成 / 合规等），这套标准本身需要后续定义（见 §8）。cann-bench 的三维度（编译 / 功能 / 性能）是这套标准的一个候选量化形式，不是全部。

---

## 2. 核心心智模型：把「算子生成能力」当作一个可训练的系统

借鉴模型训练的「求 loss → 迭代减小 loss」思想，但不追求 100% 正确，而是**大概率生成正确、或经少量人工干预即可使用**的算子。

### 2.1 训练要素 ↔ 本工程

| 训练要素 | 本工程对应 | 说明 |
|---|---|---|
| 训练目标 | 生成生产级算子 | 北极星 |
| **模型（待优化参数）** | **生成能力 = skill + agent + 框架编排 + 资源** | 改进对象（改 DevKit 自己） |
| **训练 / 验证集** | **评测算子集**（cann-bench 算子，可扩展） | 必须**固定、可复现**，否则 loss 无从比较 |
| **loss 函数** | **评测器**（cann-bench 三维度打分；可插拔） | 可替换为更好的 bench |
| 前向传播 | 跑一次生成 pipeline 产出算子 | inference |
| **单步 self-correction** | **inference-time**：单算子内 评测→局部修复 | 不改「参数」，已有（verify/perf loopback） |
| **梯度更新** | **training-time**：跨算子复盘归因 → 改 skill / 框架 | 改「参数」，本方案核心 |
| 收敛判据 | loss 足够小（大概率正确 / 少人工干预） | 不求 100% |
| 防过拟合 / 防跑偏 | 人工审核关卡 + 回归基线 | 见 §2.5 / §4 P6 |

### 2.2 关键区分：两层迭代

| 层 | 名称 | 作用域 | 是否改「参数」 | 现状 |
|---|---|---|---|---|
| **(a) inference-time** | 单算子内自我修正 | 一个算子 | 否（只改这个算子的代码） | **已有**：verify build/precision → codegen、perf → design 的 loopback |
| **(b) training-time** | 跨算子改进生成能力 | 一批算子（评测集） | **是**（改 skill/agent/框架，惠及未来所有算子） | **本方案要建** |

用户说的「求 loss 不断迭代」主要是 **(b)**。(a) 是已有能力。(b) 是真正让平台「越用越准」的机制，也是 §4「减少模型依赖」的落点——用工程的迭代 + 回归弥补模型单次能力不足。

### 2.3 评测算子集是整个方案的「锚」

没有**固定、可复现**的评测算子集，「loss 下降」无从谈起（每次跑不同算子无法比较）。因此「评测算子集的选型与固化」是优先级很高的基础设施，优先于单个 Stage 的实现。它同时承担「训练集」（驱动改进）和「验证集」（防回归）双重角色。

### 2.4 中间评测（dense supervision，解决 credit assignment）

**问题**：若只有最终评测一个 loss 点，从最终 loss 反推「哪个 stage/skill 出错」跨度太大、噪声大、不稳定（credit assignment / 稀疏奖励）。

**方向（成立）**：在中间 stage 加**独立、可算的局部 loss**，让小阶段能独立评测改进——dense supervision / 密集监督。

**关键约束——ground truth 粒度必须收敛到「结构化事实集」，不能用「整份自然语言详设文档」**。原因：
1. **语义错位**：逆向整份详设编码的是「代码现状」而非「需求意图」；已上库代码可信但非最优，用它当「正向详设」的裁判会把「忠于需求」扭曲成「模仿某实现」，与「需求是源头、代码是参考」冲突。
2. **字面比对假阳性高**：详设是半结构化自然语言，「语义等价但字面不同」极常见，整体 diff 会把等价项误判为缺陷，反成噪声。
3. **违背 P5**：整份详设比对无法机器确定性完成，只能靠 LLM 主观打分——中间 loss 依赖模型能力，违反「减少模型依赖」。

**修正方案**：中间 loss 的 ground truth 用**从代码确定性提取的结构化事实集**（属性级逐项比对，非字面 diff），来源优先级：**代码事实（确定性提取） > 需求忠实度（需求是源头） > 逆向详设（仅弱参考）**。

| 事实维度 | 提取来源 | 喂给哪个 stage 的 loss |
|---|---|---|
| TilingData 字段集（名/类型/数量/host 预计算） | `op_host/*_tiling_data.h` + `*_tiling.cpp` | 详设 ↔ 代码 字段一致 |
| Buffer 表（名/类型/数量/大小表达式） | `op_kernel/*.h` InitBuffer | 详设 ↔ 代码 buffer 一致 |
| dtype 支持矩阵 | `op_host/*_def.cpp` `.DataType()` | 需求 ↔ 代码 dtype 忠实度 |
| 运行时硬件参数查询 vs 硬编码 | `*_tiling.cpp` | 代码事实红线（P5） |
| Kernel 函数签名/拆分 + API 调用序列 | `op_kernel/*.cpp` `Compute()` | 详设伪代码 ↔ 代码 |

**逆向能力的正确定位**：从已上库代码提取结构化事实集，用于 (1) per-stage 一致性 loss 的 ground truth；(2) **补全存量算子中间产物，扩充评测/训练集**（让已上库但无详设的算子也能进入训练循环）。**不充当正向详设的裁判**。

**本质**：把 `ascendc-full-pipeline-eval`（参考 skill 2）的 Phase 6/6.5/7「一次性全链复盘」**拆成 per-stage 的在线 loss**——从「事后归因」变成「事中 loss」。

**约束**：中间 loss 不是越多越好（有权重与冲突），且**必须服从 P5——确定性、可机器校验优先，禁止用 LLM 主观打分当 loss**。

**方法论一致性（重要）**：本节反对「用代码现状 / 逆向详设当 ground truth 裁判」。同一原则**适用于框架设计文档本身**——`l1-framework-contract.md` 不用「当前代码现状」当方案地基（现状实施时现场读），只承载稳定的目标态契约。避免出现「反对用代码现状当裁判」却「用代码现状当方案地基」的方法论不一致：凡是易腐的（行号、此刻实现长什么样），都不进方案。

### 2.5 人工参与的两层模型

人工审核不是单一概念，按「推理 / 训练」两层精确化：

| 层 | 语境 | 目的 | 现状 | 默认值偏好 |
|---|---|---|---|---|
| **推理时** | 生成单算子（inference） | 保证方案不偏离**原始需求** | **已有**：requirement 澄清 + review_points + 默认决策契约 / 非交互开关 | 兜底可用，更倾向真人把关需求 |
| **训练时** | 跨算子改进工程（training） | 保证优化不偏离**改进方向** | **新建**：独立 Stage（issue / 方案 / PR 审核） | **框架代选默认值为主**（批量 / 无人值守），仅关键方向决策人工 |

**共享三层结构，差异只在「关键点」语义**——两层不是「一个用默认值、一个用真人」，而是建立在同一套机制上：

1. **默认决策契约（基础层）**：未指定时框架自动选默认值，避免卡死。推理时已有雏形（参考 skill1 的默认决策表：framework / target_repo_type / 精度标准 / device_id 等）；训练时**要新建一张**（如：默认改 skill md 不改 `src/`、默认 issue 优先级、PR 描述模板）。
2. **非交互开关（模式层）**：`--non-interactive --on-decision {default, abort, notify-webhook}` 已存在，两层复用同一套。
3. **真人关卡（关键点叠加，独立 Stage）**：默认值兜不住的方向性决策点。推理时=需求方向（已有 requirement 澄清 + review），训练时=优化方向（新建 issue/方案/PR 审核 Stage）。

> 与 D4/P6 一致：真人关卡由**独立 Stage** 承载；`resolve_ambiguity` / `__halt__` 不用于此（它们是 Stage 内部的运行期抉择）。两层都建在「默认决策契约 + 非交互开关」之上，差异只在关键点语义。

### 2.6 多算子生成与 NPU 资源调度

**问题**：`generate_ascendc` 是为**单算子**设计的 pipeline；cann-bench 评测集有大量算子，training-time 需要批量跑；NPU 有限且一个 NPU 不能同时跑两个算子任务。

**核心原则**：**不改单算子 pipeline，用「外层调度器 + per-stage NPU slot 申请/释放」**。

- 单算子 pipeline 保持不变（一个 requirement → 一个算子）。
- 多算子 = 外层调度器为每个算子发起一次独立的单算子 workflow run。
- NPU 稀缺资源由框架的 `NPUSlotManager` 统一调度（**待集成到执行流程**——是否已接入以代码为准，见 `l1-framework-contract.md` §7）：NPU-bound stage 执行前 `acquire()`，执行后 `release()`。
- 调度器用**单进程多线程**（slot 锁需 in-process 共享，只能 in-process 做并发；其具体类型、以及多线程下共享资源——events.jsonl 写入 / workspace 落盘 / agent 会话 / subprocess 日志——的隔离与并发安全，实施时核实与专门设计，不可默认安全）。

**哪些 stage 是 NPU-bound**：
- `verify` 的 precision 部分
- `perf`
- `cannbench_eval` 的 precision_loop / cannbench_score

其余（design / codegen / build / deploy 安装等）都是 CPU-bound，可任意并行。

**training-time 闭环形态**：
- `TrainingController` 外层循环：调度器跑评测集 → baseline loss → 归因 → 修复 → 调度器再跑 → new loss → 对比。
- training-time workflow 只编排 meta 阶段（归因 / 修复 / 对比）。
- 「跑算子」交给外层 `BenchmarkScheduler` 并行调度多个 `dispatch(task_request)`（dispatcher 入口，位置以代码为准）。

---

## 3. 分层架构

```
┌─────────────────────────────────────────────────────┐
│ L1 框架基石：通用状态机编排平台                       │  ← 第一层交付物
│   能添加任意 stage/substage，编排任意 workflow        │
│   + Stage 资源需求契约 + NPU slot 调度               │
├─────────────────────────────────────────────────────┤
│ L2 训练闭环：生成 → 评测(loss) → 归因 → 改进 → 再评测 │  ← 求 loss 迭代
│   ├ 最终 loss：评测器(bench) = 可插拔（cann-bench 首个）│
│   └ 中间 loss：per-stage 事实集比对（dense supervision）│
├─────────────────────────────────────────────────────┤
│ L3 兜底机制：减少模型依赖 + 人工审核（推理/训练两层）  │  ← 防自动化跑偏
├─────────────────────────────────────────────────────┤
│ L4 skill 解耦：可插拔插件，脱离框架可用（第一准则）   │  ← 贯穿所有层
├─────────────────────────────────────────────────────┤
│ L5 外层调度器：多算子并行 + NPU 资源池                │  ← 承接 L1，服务 L2
└─────────────────────────────────────────────────────┘
        ↑ 所有层服务于 §1 北极星：生成生产级算子
```

### L1 框架基石（第一层交付物）
通用状态机编排平台：stage / substage / workflow 可任意添加与编排；**新增 Stage 资源需求契约 + 执行器资源申请/释放钩子**。**当前工程已基本具备**（Workflow + Runner + Stage + Gate + 节点树 fork-join/sidetask + 转移表 loopback + 已有 `NPUSlotManager`）。L1 的任务是**确认并补强它的通用性与扩展契约**，使后续任意 workflow 都能在此之上编排，而不必每次改框架。详见 `docs/plan/l1-framework-contract.md`。

### L2 训练闭环（求 loss 迭代）
两层 loss：**最终 loss**（评测器/bench，可插拔，cann-bench 首个）+ **中间 loss**（per-stage 事实集比对，dense supervision，§2.4）。生成 → 评测（算两层 loss）→ 复盘归因（找 loss 来源）→ 改进（更新「参数」= skill/agent/框架）→ 再评测（看 loss 是否降）。含两层迭代（§2.2）。

### L3 兜底机制（防跑偏）
- **减少模型依赖**：靠框架的客观校验（编译/精度/性能 Gate、三方一致性、中间事实集 loss）、迭代、回归基线兜底，而非寄望模型一次写对。工程价值 = 在「任意模型」下都能产出可用算子。
- **人工审核（两层）**：推理时需求把关（已有）+ 训练时优化把关（新建独立 Stage）；都建在默认决策契约 + 非交互开关之上（§2.5）。

### L4 skill 解耦（贯穿）
所有 skill 是可插拔插件，脱离工程框架也能在 TUI 独立 `/skill` 跑通（仓 CLAUDE.md 第一准则）。框架是「可选外层驱动器」，沿用 skill 的文件契约，不耦合。

### L5 外层调度器（承接 L1，服务 L2）
- 批量跑单算子 workflow（评测集）。
- 管理 NPU 资源池（acquire/release）。
- 收集多算子 loss，驱动 training-time 闭环。

---

## 4. 设计原则

| # | 原则 | 含义 |
|---|---|---|
| P1 | 北极星优先 | 一切服务于「生成生产级算子」；进化/迭代是手段不是目标 |
| P2 | 框架通用性是第一交付物 | 第一层分解 = 搭可编排任意 workflow 的状态机平台 |
| P3 | loss 迭代思想 | 把生成能力当可训练系统，求 loss 不断减小（两层迭代） |
| P4 | 评测器可插拔 | cann-bench 只是首个 loss 公式；bench 与评测算子集都可扩展 |
| P5 | 减少模型依赖 | 用工程机制（校验/迭代/回归）弥补模型单次能力不足；越依赖模型，工程价值越低 |
| **P6a** | **推理时需求把关** | 生成算子时保证方案/方向不偏离原始需求（已有：requirement 澄清 + review_points；建在默认决策契约之上） |
| **P6b** | **训练时优化把关** | 改进工程时保证优化不偏离改进方向（新建：issue/方案/PR 审核独立 Stage；**框架代选默认值为主**，仅关键方向决策人工） |
| P7 | skill 解耦 | skill 像插件，脱离框架可用（第一准则） |
| P8 | evolution skill 无关 | 仓内 `.claude/skills/evolution-*` 与本方案无强制关系，仅巧合可复用则复用 |
| P9 | 中间评测（dense supervision） | 在中间 stage 加可机器校验的局部 loss，收敛 credit assignment；ground truth 用结构化事实集，不用整份详设文档；中间 loss 禁止用 LLM 主观打分 |
| **P10** | **嵌套克制** | substage/group 默认只一层嵌套；ForkJoin 并行分支是数据并行（不计控制流嵌套），分支内尽量只挂 atomic/浅串行；深嵌套需显式记录理由。多算子评测用「外层循环多次扁平 workflow」而非「单 workflow 内深嵌套 fork-join」 |
| **P11** | **多算子调度与 NPU 资源池** | **不改单算子 pipeline**；多算子由外层调度器并发驱动多个单算子 workflow；NPU-bound stage 通过 `NPUSlotManager` per-stage 申请/释放（**待集成到执行流程**，见 `l1-framework-contract.md` §7）；调度器单进程多线程（slot 锁需 in-process 共享，实施时核实类型与并发安全） |

> **洞察**：P3（loss 迭代）与 P5（减少模型依赖）是同一枚硬币的两面——loss 迭代本质就是「用工程机制弥补模型单次不足」。P9 的「中间 loss 必须可机器校验」正是 P5 在评测层的具体落实。P6a/P6b 把"人工审核"在推理/训练两层精确化。P11 把 NPU 调度从「workflow 内改造」转向「外层调度 + slot 复用」。

---

## 5. 当前工程在分层中的位置

| 层 | 目标态 | 待建能力（交付物） |
|---|---|---|
| **L1 框架基石** | 通用状态机编排平台：任意 stage/substage/workflow 声明式编排 + Stage 资源需求契约 + NPU slot 调度 | 扩展契约落地（见 `l1-framework-contract.md`）：registry 自动发现、State 产物袋、节点树统一、Stage 资源需求契约 + slot 集成。**落地进度以代码为准，本文不维护体检快照** |
| **L2 训练闭环** | 生成→评测(loss)→归因→改进→再评测；含两层迭代 | (b) training-time 闭环；最终 loss 接入；中间 loss（事实集比对）；评测算子集固化（phase0 已起步）。**inference-time (a) loopback 是已有前提，是否完整以代码为准** |
| **L3 兜底** | Gate（build/precision/performance）+ 决策工具 + 两层人工审核 + 回归基线 | 训练时人工审核（issue/方案/PR Stage）；回归基线机制；减少模型依赖的强校验。**推理时人工机制（requirement 澄清 + review_points）是已有前提** |
| **L4 skill 解耦** | skill 可插拔、脱离框架可在 TUI 独立跑通（第一准则） | 新增 skill 须逐一符合；确定性脚本须进 skill 目录 |
| **L5 外层调度器** | 多算子并行调度 + NPU 资源池 + loss 聚合 | 多算子调度器、loss 聚合、与 training-time workflow 的边界 |

> 「现状 / 已具备」在本表中刻意弱化：分层地图只标**目标态 + 待建**，实现进度一律「以代码为准」。某能力是否已落地，实施时读代码核实，不靠本表（本表会滞后）。

---

## 6. 候选实现积木（附录 · 非主线）

> L2/L3/L5 的**候选**实现单元，仅作参考。**待 §3 各层契约定稿后再细化**。

- **评测样本生产**：`cannbench_eval` Workflow（deploy / precision_loop / cannbench_score Stage）
- **逆向事实提取**：`code_facts_extract` skill（定位：从已上库代码提取结构化事实集 + 补全存量算子中间产物扩充评测集；**不当正向详设裁判**）
- **per-stage 中间评测器**：一致性 / 需求忠实度 / 代码事实，per-stage 在线 loss（事实集 schema 见 §2.4）
- **复盘归因**：`eval_review` / `root_cause` Stage
- **问题处理**：`issue_triage` / `diagnose` / `human_review` Stage
- **修复回归**：`fix_self` / `verify_fix` Stage
- **PR 闭环**：`prepare_pr` / `await_merge` Stage + `GitAdapter`（L6，平台只提 PR 不合）
- **外层调度器**：`BenchmarkScheduler` / `TrainingSetRunner`（L5，单进程多线程调度多个 `dispatch(task_request)`，管理 NPU slot）
- **NPU 调度集成**：Stage `resource_requirements()` + Runner/GraphExecutor acquire/release hook

---

## 7. 分层讨论路线图（建议）

按「先定抽象/契约，后填实现」推进，每次聚焦一层：

| 次序 | 讨论主题 | 产出 | 依赖 |
|---|---|---|---|
| 已完成 | 大方向 + 心智模型 + 分层 + 中间评测 + 人工两层 + NPU 调度 | 本文档 §1–§5 | — |
| **进行中（最优先）** | **最小 baseline loss 验证** | 用 phase0 的 35 算子 + 最糙方式跑通一次「生成→评测」，产出 baseline loss；**先证明 loss 迭代这条路有信号**，再谈精修；同时暴露 L1 真实约束（供下一步精修对齐） | phase0-ops.json、现有 dispatch 入口 |
| 之后 | **L1 框架基石扩展契约（在 baseline 真实约束上精修）** | stage/substage/workflow 扩展契约；3 缺口补强（自动发现 / 产物袋 / 节点树统一）；Stage 资源需求契约 + slot 集成方案；最小 training-time 闭环验收缺口 | baseline 验证暴露的约束 |
| 再下一次 | **评测器抽象（loss 公式接口）+ 评测集固化** | 可插拔 bench 统一契约；评测算子集选型与固化（phase0 已起步）；**事实集 schema** | L1 契约 |
| 之后 | **两层迭代 + 中间 loss 建模** | (b) training-time 闭环形式化；per-stage 中间 loss 维度与权重 | 评测器抽象 + 事实集 |
| 之后 | **人工审核两层落地** | 训练时默认决策契约表；`human_review` Stage 契约；推理时 review 评估 | L1 契约 |
| 之后 | **外层调度器 + NPU 集成落地** | `BenchmarkScheduler` 设计；slot 与执行器集成 | L1 契约 |
| 最后 | **实现细节** | §6 积木逐一落地、GitAdapter、跨 run infra（issue 池 / loss 历史） | 以上全部 |

> **调序理由**：原路线图把 L1 框架精修排在最前。但 §2.3 自己说「评测算子集是整个方案的锚」——锚已现成（phase0）。在 baseline loss 尚未验证「loss 迭代有信号」之前，凭空精修框架等于在黑暗里优化；P0/P1/P2 补强做到什么程度，应由 baseline 暴露的真实约束校准。**验收判据先于补强动作**。

---

## 8. 待定关键问题（后续逐层拍板）

1. **「生产可用」标准的定义**：除 cann-bench 三维度外，是否含多平台、PTA 接口、主线仓集成、code review 等？
2. **评测算子集的选型与固化**：用 cann-bench 哪批算子？如何版本化保证可复现？存量算子如何经逆向纳入？
3. **L1 扩展契约边界**：添加一个 stage/substage/workflow 是否真的零改框架？哪里还要补强？（3 耦合点）
4. **loss 公式可插拔接口**：不同 bench 如何统一成同一个 loss 接口？
5. **(b) training-time 改进的对象与边界**：改 skill md / agent manifest / 资源（低风险）vs 改 `src/` 编排代码（高风险）的分级。
6. **GitAdapter 目标仓/协议**：DevKit 自仓 remote（GitHub/Gitee/内部 GitLab）？`gh` CLI 还是 API？
7. **收敛判据**：loss 降到什么程度算「大概率可用」？何时触发人工介入？
8. **中间 loss 维度与权重**：选哪些事实维度作 per-stage loss？多个中间 loss 如何加权、如何处理冲突？
9. **事实集 schema**：`code_facts_extract` 产出的结构化事实集 schema；per-stage 比对算法。
10. **训练时默认决策契约表**：哪些抉择可默认、默认值是什么（如默认改 skill md 不改 `src/`、默认 issue 优先级、PR 描述模板）。
11. **训练时「必须真人 vs 可默认」边界**：如改 `src/` Python 必真人、改 skill md / agent manifest 可默认。
12. **推理时需求把关机制评估**：现有 requirement 澄清 + review_points 是否足够覆盖「需求方向把关」，还是要增强。
13. **（v0.6 新增）Stage 资源需求契约**：`resource_requirements()` 接口 shape；是否只声明 npu 还是扩展 cpu/memory；NPU 申请失败的策略（阻塞 / 超时 / 降级）。
14. **（v0.6 新增）slot 集成点**：在 Runner 还是 GraphExecutor 里做 acquire/release；NPU-bound stage 失败时 release 的异常安全；多线程与 slot 的边界。
15. **（v0.6 新增）外层调度器形态**：`BenchmarkScheduler` 是独立 CLI 命令、独立 workflow，还是 training-time workflow 的某个 stage？多算子任务队列/优先级策略。

---

## 变更记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-06-28 | v0.1 | 初稿：积木清单为主（偏细节，主线不清） |
| 2026-06-28 | v0.2 | 重构：北极星 + loss 训练心智模型 + 5 层架构为主线；积木降附录；纠正「进化是手段不是目标」；evolution skill 降为无关可选 |
| 2026-06-28 | v0.3 | 新增中间评测（dense supervision）：采纳「中间 stage 独立评测」，但 ground truth 粒度从「整份逆向详设」收敛到「结构化事实集」；逆向能力定位为事实提取 + 评测集扩充；新增原则 P9 |
| 2026-06-28 | v0.4 | **新增人工参与两层模型（§2.5）**：推理时需求把关（已有）vs 训练时优化把关（新建 stage，框架代选默认值为主）；P6 拆为 P6a/P6b；明确两层共享「默认决策契约 + 非交互开关」基础，差异在关键点语义 |
| 2026-06-28 | v0.5 | 新增 P10 嵌套克制：默认一层嵌套，ForkJoin 分支不计控制流嵌套，多算子评测用外层循环而非内层深嵌套；同步修正 L1 文档「任意嵌套是强项」的过度措辞 |
| 2026-06-28 | v0.6 | **新增多算子生成与 NPU 资源调度（§2.6 / P11 / L5）**：不改单算子 pipeline，外层调度器并发驱动多个单算子 workflow；复用 `NPUSlotManager` 做 per-stage acquire/release；调度器单进程多线程 |
| 2026-06-29 | v0.7 | **现状剥离 + 去 file:line + 弃用易失脚本**：① §5「现状/缺口」表改「目标态/待建」（进度以代码为准，不维护体检快照）；② §2.6 去 slot 行号、dispatcher 入口行号与「已有 `NPUSlotManager`」断言，改「待集成、实施时核实」；③ §2.4 加方法论一致性呼应（框架契约同样不用代码现状当裁判）；④ §7 路线图调序——最小 baseline loss 验证提前到 L1 精修之前（先证 loss 迭代有信号，再据真实约束精修框架）。与 `l1-framework-contract.md` v0.5 / `phase0-run-strategy.md` 同步；弃用易失会话脚本 `batch_run_vector_ops.sh`（非 git、跨会话丢失），cann-bench 作只读外部依赖、不修改其仓 |
