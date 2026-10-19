# AscendC-DevKit 工程讲解 —— 快速理解与上手指南

> **定位**：AI 驱动的 AscendC 算子开发平台。接收算子需求，经 LLM Agent 多阶段协作，**直接在目标算子代码仓内**生成、编译、调试可验证的 AscendC 算子代码。
>
> **本文用途**：给新同事一次 ~1 小时的工程串讲底稿，读完能"看懂、能上手、敢改"。
> **与既有文档的关系**：`docs/architecture-overview.md` 是**详尽参考**；本文是**串讲向、图多文少**的互补入口。需要深挖某层/某 stage 再去查 `docs/layers/`、`docs/stages/`。

---

## 0. 怎么读这份文档

| 你是… | 建议阅读顺序 |
|---|---|
| 第一次接触本工程 | §1 → §2 → §3 → §5.1（端到端走一遍）→ §6 |
| 要做框架/编排层开发 | §3（重点）→ §4.2/4.3/4.4 → §6.2 |
| 要写算子知识/skill/agent | §4.7 → §4.2 → §6.2 |
| 要做目标仓适配 | §4.3（RepositoryProfile）→ §6.1 → §6.2「加目标仓」|
| 只想跑起来看看 | §6.1 → §5.1 |

```text
一句话：这是一个「以纯函数状态机为核心、把算子知识全部外置、用事件溯源保证可恢复」
        的 7 层 Agent 编排平台，把"需求文档 → 仓内可编译算子"这条链自动化。
```

---

## 1. 整体设计思路

### 1.1 它解决什么问题

```text
            需求文档 / proto                可编译、可验证的 AscendC 算子代码
            （算子签名 + 用例）             （已落到目标仓 op_dir，git 可回滚）
                  │                                      ▲
                  ▼                                      │
        ┌─────────────────────────────────────────────────────┐
        │                   ascendc-devkit                     │
        │   LLM Agent 多阶段协作  +  仓内编译/精度/性能闭环      │
        └─────────────────────────────────────────────────────┘
                │              │              │             │
            SDK 能力       NPU 硬件      CANN 工具链     目标代码仓
(Claude Agent SDK 等)    (910B/C/D…)   (ops_compile)  (omni-ops…)
```

| 场景 | 输入 | 输出 |
|---|---|---|
| 新算子生成 | 需求描述 + 用例 | 算子仓内新增目录与完整源码 |
| 增量开发 | 目标仓现有算子 + 变更需求 | 仓内就地修改/新增/删除源码 |
| 性能优化 | 已有算子 + perf baseline | 优化版本 + 性能对比 |
| 精度/性能调试 | 算子代码 + 失败用例 | 缺陷定位 + 自动修复 |

> **两类"迭代"要分清**（自进化章节会再讲）：(a) **单算子内**的推理时迭代——编译/精度/性能的自愈回环，**已落地**；(b) **跨算子**的训练时迭代——用一批算子的成败反馈来改进平台自身，**搭建中**（见 §4.6）。

### 1.2 核心设计哲学（七条，每条一句 + 落点）

| # | 原则 | 在工程里的具体落点 |
|---|---|---|
| 1 | **纯函数状态机核心** | L3 `kernel/` 是纯函数；所有副作用集中在 `Runner._execute_actions`（`runner.py:485`）|
| 2 | **知识外置** | 算子怎么写、怎么 tiling 的知识**全在 `.claude/skills` + `.claude/plugins` 的 markdown**，绝不内联进 Python |
| 3 | **配置驱动** | "和某个仓相关"的知识进 `resources/repository-profiles/*.yaml`，不在 Python 写 `if repo==...` |
| 4 | **事件溯源** | `events.jsonl` 是运行历史的**唯一权威**，`State` 可由事件重建，支持中断恢复 |
| 5 | **协议隔离 + 依赖注入** | 层间只持有 ABC/protocol；具体实现（adapter/backend）由上层注入 Runner |
| 6 | **加载期校验优于运行期暴露** | skill/plugin/manifest/profile 合法性在加载时就校验告警，不推迟到运行才炸 |
| 7 | **不考虑向后兼容** | 工程未发布；改 schema/字段直接改干净，不留别名/迁移/deprecated 包装 |

### 1.3 三个关键设计决策的"为什么"

**(A) 为什么是 7 层？** —— 因为有四个**正交的变化维度**，让每层只对一个负责，改一个不牵动其他三个：

| 变化维度 | 例子 | 负责层 |
|---|---|---|
| 用户入口形式 | CLI / TUI / CI 脚本 | L1 |
| 业务场景 | 新生成 / 增量 / 调优 | L3（workflow）|
| 目标代码仓 | omni-ops / ops-nn / cann-bench | L6（profile）|
| 外部基础设施 | LLM provider / NPU 型号 / CANN 版本 | L6 |

**(B) 为什么核心是状态机 + Action + 事件？** —— Agent 任务是**长时、非确定、可中断**的。把"决定下一步做什么"(`actions`)、"执行"(`execute`)、"状态更新"(`transition`)三者分离，才能：迭代收敛、失败回环、超时取消、断点恢复，且全程有据可查（events.jsonl）。

**(C) 为什么算子知识不进 Python？** —— 算子知识（API 签名、tiling 套路、硬件参数）变化快、体量大、且 LLM 直接消费最自然。写进 Python 既膨胀代码又难复用；放进 skill markdown，LLM 按需检索、人也能直接读改。Python 只留**结构化类型 + 确定性翻译/解析胶水**。

---

## 2. 工程框架

### 2.1 顶层目录结构

```text
AscendC-DevKit/
├── src/ascendc_devkit/        # Python 源码，严格按层组织（见 §2.2）
│   ├── cli/                   #   L1 表现层（Click CLI + Rich TUI）
│   ├── application/           #   L2 应用层（dispatch 路由 / Report）
│   ├── orchestration/         #   L3 编排层（核心：状态机 / 图执行 / 9-Stage）
│   ├── domain/                #   L4 领域层（纯数据 dataclass，零依赖）
│   ├── capabilities/          #   L5 能力层（Agent backend / Skill / Knowledge）
│   ├── adapters/              #   L6 适配层（Repository / NPU / Toolchain）
│   ├── infra/                 #   L7 基础设施（Workspace / EventLog / RepoGuard）
│   └── self_evolution/        #   跨算子训练循环（与 orchestration 平级，见 §4.6）
├── .claude/                   # Claude Code 原生发现目录
│   ├── agents/                #   14 个 agent 清单（frontmatter 声明 skill/tool/权限）
│   ├── plugins/               #   8 个插件（skill 的真正载体，见 §4.7）
│   ├── skills/                #   55 个裸 skill（TUI 可见，但 headless SDK 不发现）
│   └── rules/                 #   算子开发总规则（ascendc-dev.md）
├── resources/                 # 声明式配置（不含算子知识 markdown）
│   ├── orchestration-config.json   # 编排调参中枢（模型/超时/迭代/quota）
│   ├── repository-profiles/*.yaml  # 4 个目标仓布局描述
│   └── schemas/                    # profile 的 JSON Schema
├── docs/                      # 设计文档（architecture-overview / layers / stages / plan）
├── tests/                     # ut/（~610 单测）+ st/（~35 系测）
└── pyproject.toml             # 入口 console_script: ascendc-devkit
```

> ⚠️ **易混淆点**：算子知识的 markdown 在 **`.claude/skills` + `.claude/plugins`**，**不在** `resources/`。`resources/` 只有**配置**（编排参数、仓布局、schema）。

### 2.2 七层架构总览

```text
┌──────────────────────────────────────────────────────────────────────┐
│ L1  Presentation   CLI / TUI / Slash            把用户输入翻译成 TaskRequest │
│ L2  Application    路由 / Profile 绑定 / Report  解析意图、选 workflow、汇聚事件 │
│ L3  Orchestration  Workflow / Stage / Gate / 图执行 / Runner  纯函数状态机驱动 │
│ L4  Domain         OperatorSpec / Requirement / Profile …  纯数据，零依赖     │
│ L5  Capabilities   Agent backend / Skill / Knowledge  LLM 能力封装            │
│ L6  Adapters       Repository / NPU / Toolchain  隔离外部世界，只暴露 protocol │
│ L7  Infrastructure Workspace / EventLog / RepoGuard / FS  横切关注点          │
└──────────────────────────────────────────────────────────────────────┘
        │                                                          ▲
        └──────────── 严格向下依赖，绝不上向引用 ──────────────────────────┘
```

| 层 | 隔离的变化 | 关键产物 |
|---|---|---|
| L1 | 用户入口形式 | `cli/commands/{run,stage,show,respond,debug-agent,skill,…}` + `tui.py`(4 面板) |
| L2 | 用例编排 | `dispatcher.dispatch()` —— 全链路唯一接线点 |
| L3 | 流程状态机 | `kernel/{state,action,runner,event,gate}` + `graph_executor` + `stages/*` + `workflow.py` |
| L4 | 领域概念定义 | `operator/requirement/repository/contract/artifact/verification/chip.py` |
| L5 | LLM 集成方式 | `agent/{backend,sdk_backend,stub_backend}` + `skill/loader` + `knowledge` |
| L6 | 外部系统交互 | `repository/{base,generic}` + `npu/{runner,slot,detect}` + `toolchain/{cann,pta}` |
| L7 | 横切基础 | `workspace/event_log/repo_guard/logger/log_capture/filesystem` |

### 2.3 一次运行，数据如何穿越七层（端到端）

```text
L1  cli/commands/run.py
      │  解析 argv → task_request（dict）；在 L1→L2 边界 resolve --op-dir
      ▼
L2  application/dispatcher.dispatch(task_request)
      │  Workspace.create() → 解析双 chip → 预检(CANN/NPU/输入拓扑) → 构造 State
      │  注入 adapter/backend → 选 workflow → GraphExecutor.execute(root, state)
      ▼
L3  orchestration/graph_executor + kernel/runner
      │  遍历 StageNode 树 → 对每个 Stage:
      │     stage.actions(state, iter) → [SpawnAgent/RunGate/NoOp/…]
      │     Runner._execute_actions(副作用) → result
      │     stage.transition(state, result) → 新 State（不可变 with_updates）
      │     event_log.append(...) ──────────────┐
      ▼                                          ▼
L5  capabilities/agent/sdk_backend        L7  infra/event_log → events.jsonl
      │  读 .claude/agents/<name>.md 做系统提示  infra/workspace → state_snapshot.json
      │  加载 plugin skills、注入 MCP 工具       infra/repo_guard → op_dir git 基线
      │  cwd=op_dir 起 agent，写码进仓           ▲
      │  自报改动 ∪ git diff → AgentResult ──────┘
      ▼
L6  adapters: repository.build / npu.runner.execute / toolchain.cann
      ▼
L2  application/report.generate(events.jsonl) → report.md / report.json
      ▼
L1  cli/exit_codes → sys.exit(0 / EX_DATAERR / EX_DECISION_PENDING / …)
```

> **L4 不在流程图里当"步骤"** —— 它的类型（`State`/`Action`/`OperatorSpec`/`Requirement`…）作为**数据契约**贯穿所有层。

### 2.4 关键术语速查

| 术语 | 一句话定义 |
|---|---|
| **TaskRequest** | CLI 输入翻译成的不可变结构（L1→L2） |
| **State** | 一次运行的不可变快照（frozen dataclass，~120 字段）；每次 transition 返回新实例 |
| **Action** | Stage 在某状态产出的下一步指令（SpawnAgent / RunGate / NoOp / …）|
| **Stage** | Pipeline 一个步骤：`actions()`+`transition()`+`gate()`+IO 契约 |
| **Workflow** | 一组有序 Stage 的**声明**；内部表示为 StageNode 树 |
| **Gate** | 决定能否进入/退出 stage 的**纯判定函数**：`evaluate(evidence)→GateResult` |
| **StageNode 树** | Workflow 的图表示：AtomicStage/SequentialGroup/ForkJoinGroup/SideTask |
| **op_dir** | 算子在目标仓内的代码目录；codegen/verify/perf 的 agent `cwd` |
| **RepositoryProfile** | 描述目标仓约定的 YAML（算子名前缀 + 构建 variant）|
| **RepoGuard** | op_dir 范围的 git 基线快照 + 失败回滚（**绝不**全仓 reset）|
| **Workspace** | `output/<run_id>/`，单次运行的事件/报告/备份根 |
| **Event** | 写入 `events.jsonl` 的结构化事件，运行历史权威 |
| **chip 命名** | canonical = 代际码 `A2/A3/A5`；编译时由 `chip.py.to_soc_version()` 翻译成 soc_version |

---

## 3. 架构设计

### 3.1 分层与依赖规则

```text
   ✅ 允许                                ❌ 禁止
─────────────────────────────          ─────────────────────────────
L1 → L2, L4                            L4 → L3   (Domain 反查编排)
L2 → L3, L4, L7                        L5 → L3   (能力反查 workflow)
L3 → L4, L5, L6, L7                    L6 → L3   (adapter 反查 workflow)
L4 → 无依赖(纯数据)                     任意层 → L1 (反查 CLI)
L5 → L4, L6, L7                        直接 import 具体实现而非 protocol
L6 → L4, L7
L7 → 无依赖
```

> 合规性有专门测试守护：`tests/ut/test_layer_dependencies.py`。

### 3.2 L3 编排核心：Stage / State / Action 状态机（这是心脏）

```text
                         ┌──────────────────────────────┐
                         │   State（不可变 frozen 快照）   │
                         │   with_updates(**) → 新实例    │
                         └──────────────┬───────────────┘
                                        │
                 ① 决策                  ▼                ② 执行
        ┌────────────────────────┐   ┌─────────────────────────────┐
        │ stage.actions(state, i)│ → │ Runner._execute_actions     │
        │ → list[Action]         │   │  SpawnAgent → L5 backend     │
        │ （纯函数，无副作用）     │   │  RunGate    → gate.evaluate  │
        └────────────────────────┘   │  NoOp/Integrate/AskUser…     │
                                      │  （唯一有副作用的地方）        │
                                      └──────────────┬──────────────┘
                                                     │ result(dict)
                                ③ 状态更新            ▼
                          ┌──────────────────────────────────┐
                          │ stage.transition(state, result)  │
                          │ → 新 State（纯函数）              │
                          └──────────────┬───────────────────┘
                                         │
                          ④ 判定终止：output_contract 满足？ is_satisfied？
                                         │  否 → ① 进入下一 iteration
                                         │  是 → stage 结束
                                         ▼
                          ⑤ resolve_condition(state) → 路由键
                                         │
                                         ▼
                          GraphExecutor 查 TRANSITION_TABLE → 下一节点 / 回环 / 升级
```

**Stage 协议**（`orchestration/base.py`）核心方法：

| 方法 | 职责 | 默认/可覆盖 |
|---|---|---|
| `input_contract()/output_contract()` | 声明 requires/provides 的 State 字段（硬前置/早终止）| 必须实现 |
| `actions(state, iter)` | 产出本轮 Action 列表（纯函数）| 必须实现 |
| `transition(state, result)` | result → 新 State（纯函数）| 默认返回原 state |
| `gate()` | 进入前的纯判定 | 默认 None |
| `is_satisfied(state)` | 质量自检（早终止条件）| 默认 True |
| `resolve_condition(state)` | 回环路由键 | 默认 "default"(线性后继) |
| `fail_strategy` | 失败策略 `"continue"`/`"halt"` | 默认 continue |
| `artifact_contract()` | 声明落盘产物（spec/code/doc）| 默认空 |

### 3.3 图化编排：StageNode 树 + GraphExecutor

Workflow 不是"扁平 stage 列表"，而是一棵 **StageNode 树**，由 `GraphExecutor` 统一遍历驱动。

| 节点类型 | 作用 |
|---|---|
| `AtomicStage` | 叶子，包装单个 Stage，由 Runner 驱动 |
| `SequentialGroup` | 顺序执行子节点，**作用域内**支持 corrective/escalation 回环 |
| `ForkJoinGroup` | 并行 fork 多个子节点，join 时**合并各子状态**（冲突检测）|
| `SideTask` | fire-and-forget 旁路任务，对主遍历透明，return 前 join |

```text
   generate_ascendc 的 root 树（示意）：

   SequentialGroup(根)
   ├─ Atomic(entry) ─ Atomic(context) ─ Atomic(requirement)
   ├─ SequentialGroup[general-design]   ← 作用域 1（概念设计 + review）
   ├─ SequentialGroup[detailed-design]  ← 作用域 2（含 tiling ForkJoin）
   │     └─ ForkJoinGroup[tiling]       ← 每个 template 一条并行分支
   │           ├─ split → buffer-kernel → precision-perf
   │           └─ split → buffer-kernel → precision-perf
   ├─ Atomic(test_design) ─ Atomic(codegen_init) ─ Atomic(codegen)
   ├─ Atomic(precision_debug) ─ Atomic(perf) ─ Atomic(integrate) ─ Atomic(finalize)
```

**GraphExecutor 遍历要点**（`graph_executor.py`）：

- 按 node 类型分派：Atomic→`run_stage`、Sequential→顺序+回环、ForkJoin→并行+合并、SideTask→旁路。
- **恢复权威**是 `State.node_status[path]`：`completed` 跳过、`failed` 上冒。每节点结束原子写 state 快照，硬杀也能续。
- **ForkJoin 合并**（`node_forkjoin.merge_forkjoin`）：dict 字段按键浅合并进 base（如每个 template 贡献 `tiling_results["T1"]`），兄弟间同名冲突 → `StateConflictError`。

### 3.4 三层路由与回环（工程最精巧的部分）

当某 stage 失败或质量不达标，不是简单"重试"，而是**分级路由**：

| 层级 | 类型 | 含义 | 配额（默认）|
|---|---|---|---|
| L1 | **corrective** | 同策略修复（如 codegen→重写、tiling→重切）| `max_corrective=5` |
| L2 | **escalation** | 架构级返工（→design、→requirement）| `max_escalations=2` |
| — | **validation** | 反向校验（如 perf 调完 → 回 precision_debug 复验精度）| 计入 corrective |
| — | **advisory** | 纯前向信息携带（把 issue 交给下游 owner），**不改控制流、不耗配额**| 无 |

```text
   例：perf 阶段的两种回环

   perf ──redesign──►  detailed-design   (escalation：架构返工，升 1 级)
   perf ──tuned────►  precision_debug    (validation：调完码要复验精度)
   perf ──default──►  integrate          (线性后继，正常往下)
```

**机制关键点**：

1. 每个**作用域**（scope_path，如 `detailed-design/tiling`）独立维护 `{corrective, escalation, history, last_sig}` 计数器（`State.routing_scopes`），根作用域镜像到顶层字段。
2. **停滞检测**：同一 `(from→to, error_signature)` 出现 ≥2 次 → 第 3 次直接停（避免死循环）。
3. **范围失效**：回环时 `_invalidate_sequential_range` 清掉 `[target, 当前)` 的 `node_status`，保证续跑不会跳过回环节点；支持 **template 精准回滚**（只重跑出问题的那条 ForkJoin 分支）。
4. **升级冒泡**：子 group 内部表查不到的条件 → `__escalate__:<cond>` 冒泡到父作用域解析。
5. 特殊目标：`__halt__`（终止）、`__escalate__:`（冒泡）。

### 3.5 Gate 机制

`Gate` 是**纯判定函数**：`evaluate(evidence: dict) → GateResult(passed, reason, metrics)`，无副作用。Stage 从 `gate()` 返回它，Runner 通过 `RunGate` action 执行，结果喂给 `transition()`。

| Gate | 位置 | 作用 |
|---|---|---|
| `BuildInRepoGate` | `stages/gates.py` | 用仓自身构建系统编译算子（finalize 用）|
| `PrecisionPassedGate` | `stages/perf.py` | 精度没过就不许测性能 |
| `PerformanceGate` | `stages/perf.py` | NPU 计时 vs baseline |
| `VerifyCompleteGate` | `stages/integrate.py` | 检查 build_result.passed |
| `IntegrationCompleteGate` | `stages/finalize.py` | 校验 integrate 落了文件（设计-only workflow 优雅跳过）|

> ⚠️ "能力下沉"后，编译/精度的 in-session 闭环**不再**是 runner 跑的 Gate 对象，而是 agent 自己读 `last_deploy.json` / `run-cases` 自愈（见 §5.2）。上表的 Gate 是剩下的**确定性**检查。

### 3.6 事件溯源与可恢复性

```text
   每个动作都写一行 events.jsonl（append-only，每行 fdatasync，硬杀最多丢在途那 1 行）

   events.jsonl   ←运行历史权威（stage_enter/iteration/spawn_context/loopback/chip_decision…）
   state_snapshot.json  ←原子写（temp+os.replace），恢复权威
   node_status[path]    ←图恢复前沿：completed 跳过 / failed 上冒

   中断（Ctrl-C / 超时 / 崩溃 / DecisionPending）→ exit 非零
        │
        ▼  ascendc-devkit run --resume <run_id>
   dispatcher:  from_snapshot(state) → Workspace.from_existing → bind_run_log
                → 按 node_status 续跑未完成节点
```

**关键事件类型**（`kernel/event.py`）：`stage_enter/complete/aborted/skipped`、`iteration_start/complete`、`action_start/complete`、`spawn_context`（debug-agent 重放用）、`loopback/workflow_loopback`、`stagnation`、`chip_decision`、`decision_pending`、`workflow_complete`。

---

## 4. 模块设计

### 4.1 L4 Domain：纯数据层

**纪律**：29 个 `@dataclass(frozen=True)`，**零框架依赖**（仅 stdlib + 域内相对导入）。Python 只存"形状/身份/翻译"，不存算子语义。

| 文件 | 核心类型 | 作用 |
|---|---|---|
| `operator.py` | `OperatorSpec`/`OperatorIdentity`/`TensorSpec` | 算子静态身份（签名/dtype）+ 磁盘位置 |
| `requirement.py` | `Requirement`/`TestCase`/`UnclearItem` | TDD 验收用例 + 不明确项澄清 |
| `repository.py` | `RepositoryProfile`/`BuildVariant`/`BuildStage` | 仓布局的"不变事实"（前缀+variant）|
| `contract.py` | `StageIOContract` | requires/optional/provides 的 State 字段契约 |
| `artifact.py` | `ArtifactSpec`/`ArtifactContract` | 落盘产物契约（spec/code/doc 三类）|
| `verification.py` | `Build/Precision/Performance/Deploy/Eval/Adapt Result` | 各 stage 的度量结果 |
| `chip.py` | `A2/A3/A5` + `_SOC_VERSION` + `to_soc_version()` | **芯片命名唯一权威源** |
| `evolution.py` | `OpEvalResult`/`TrainingLoss`/`AttributionItem` | 自进化训练记录 |

**两份契约 = Stage 的接口边界**（缺一不可）：

```text
   StageIOContract   ── 声明 State 字段级别的 requires/provides（类型化握手）
   ArtifactContract  ── 声明落盘文件级别的要求（spec JSON / code / doc）
                          artifact.to_prompt_block() → agent 看到的"输出要求"
                          artifact.parse(artifacts)  → orchestrator 读回校验
                          （同一份 schema 既生成 prompt 又校验输出，永不对不上）
```

**chip.py 命名分层**（`CLAUDE.md §1.9` 的单一权威源）：

```text
   canonical:  A2 / A3 / A5   （贯穿 CLI / profile / state / 日志 / 文档）
                                  │ to_soc_version()  ← 唯一编译翻译点
                                  ▼
   soc_version: ascend910b / ascend910_93 / ascend950   （进 CANN/build.sh 的字面量）
```

| 代际 | soc_version | 编程模型 | 兼容性 |
|---|---|---|---|
| A2 | `ascend910b` | Membase (Vector/SIMD) | — |
| A3 | `ascend910_93` | Membase | — |
| A5 | `ascend950` | Membase **+** Regbase (SIMT) | A5 能跑 A2/A3 的 Membase 设计；反之不行 |

> State 用**双字段分离权威**：`design_target_chip`（设计/编译意图）与 `runtime_target_chip`（真机硬件真相），都默认 `""`（未解析=诚实留空，不假装 A2）。

### 4.2 L5 Capabilities：Agent / Skill / Knowledge

#### AgentBackend 契约（`capabilities/agent/backend.py`）

```text
   backend.spawn(agent_name, prompt, context, *,
                 skills, plugins, model, working_dir,
                 repo_baseline, repo_root, stage_name, branch_label,
                 resume_session_id) → AgentResult
```

| 实现 | 用途 |
|---|---|
| `SDKBackend` | 真实：包 `claude_agent_sdk`，读 `.claude/agents/<name>.md` 当系统提示，加载 plugin skills，注入 MCP `engine`，`cwd=op_dir` 起子进程，流式收 token + 崩溃重试 |
| `StubBackend` | 测试：返回预设 `AgentResult`，并把 artifacts 落盘到 working_dir（让磁盘读取路径也得到真实产物）|

**AgentResult.status 语义**（关键）：`ok`/`partial`(崩了但有产物，**按失败处理**)/`empty_artifacts`/`compile_error`/`precision_fail`/`fatal`。`error_type="infra"`（配额/鉴权/无通道）= **本次运行内不可重试**。

#### Skill 加载：**plugin 是加载器，skills 字段是过滤器**（极易混）

```text
   .claude/skills/<name>/SKILL.md       ← 裸 skill：TUI 可见，但 headless SDK 不发现
   .claude/plugins/<plugin>/skills/<name>/SKILL.md  ← 插件 skill：SDK 发现，命名 <plugin>:<skill>

   agent.md frontmatter:
     plugins: [stage-codegen, shared]   ←【加载器】决定哪些 skill 进入 SDK 发现空间
     skills:  [...]                     ←【过滤器】白名单：允许调用哪些已发现的 skill
   options.skills=  (SDK 参数)          ←【过滤器】None=继承默认 / []=全禁 / list=子集
```

> 一句话：**`plugins:` 让 skill 可被调用；`skills:` 决定本次允许调哪些**。本仓 agent 大多只声明 `plugins:`，由编排按 stage 传 `skills=` 子集。

#### Knowledge（`capabilities/knowledge/`）

`KnowledgeBase` 把 AscendC 官方文档语料（在 `.claude/plugins/shared/skills/ascendc-dev-knowledge/references/`）解析成 `INDEX.md` 树，按 API 名检索返回文档。三层知识策略（见 `.claude/skills/ascendc-op-design-shared/references/knowledge_policy.md`）：

| 层 | skill | 内容 |
|---|---|---|
| Tier 1 | `ascend-hardware` | 硬件参数（UB/核数/带宽/对齐）|
| Tier 2 | `evolution-knowledge` | 设计模式、tiling 策略、精度策略 |
| Tier 3 | `ascendc-dev-knowledge` | 具体 API 签名、存储层级、dtype/format |

铁律："只做有理论依据的推理，禁止猜测；每个数值必须有命名来源"。

### 4.3 L6 Adapters：隔离一切外部世界

纯 `数据进 → 结果出`，无 State、无事件、无 workflow 感知。

#### Repository（仓交互）

`RepositoryAdapter`(ABC, `adapters/repository/base.py`) 四方法：`materialize_new_operator` / `scan_existing_operator` / `build` / `write_dev_record`。`GenericRepositoryAdapter` 是 YAML 驱动默认实现（覆盖 ~95% 仓）：文件靠**递归扫描**发现而非固定 pattern，`build` 按 variant 的 `enabled_stages()` 顺序跑 `command_template`。

**RepositoryProfile 只描述两个不变事实**：算子名**前缀** + 构建 **variant 集合**。可变路径信息不写死，运行时由 `--op-dir` 解析 + 扫描得到。

```text
   RepositoryProfile (domain/repository.py)
     ├ op_naming.prefix        例 "ai_infra_"
     ├ build_variants[]        按 match_prefix 最长匹配选 variant
     │    └ stages[]           name/cwd/command_template/role
     │       role ∈ {build, install_runtime, install_python, smoke}  ← 部署能力分类
     └ artifacts_ignore        git-diff 收集产物时排除 *.o/*.so/build/
```

现有 4 个 profile：`omni-ops`（双 variant：inference/training）、`cann-bench`（全部署链）、`ops-nn`、`ops-transformer`。`has_deploy_capability()` = variant 同时声明 `install_runtime`+`smoke`。

#### NPU（硬件）

| 组件 | 职责 |
|---|---|
| `NPUSlotManager` | 线程安全多卡分配（`threading.Lock`），acquire/release/list |
| `detect.py` | 硬件设备名 → canonical A2/A3/A5（带超时的守护线程探测，超时抛 `EnvironmentProbeTimeout` **不**伪装成错的芯片）|
| `NPURunner` | 在 NPU 跑算子：生成 Python harness，subprocess 注入 `ASCEND_NPU_ID/CHIP_VERSION/…`，CPU 跑 golden 比对，返回 cann-bench 对齐的逐输出判定 |
| `precision_compare.py` | 自实现的 cann-bench 精度方法（零 cann-bench 依赖），按 dtype 选 bit-exact/equal/MERE/MARE + 小值/抵消二级阈值 |

#### Toolchain

- `CANNToolchain`：**仅存在性探针**（`ASCEND_TOOLKIT_HOME` + 编译器 sentinel 在 PATH）；本工程从不直接调 ccec，仓内算子走自己的 `build.sh`。`diagnostic_hint()` 区分"装了没 source"vs"没装"。
- `PTAToolchain`：生成 `torch.ops.custom` 注册样板（PTA = PyTorch Adapter）。

#### Schema loader

`SchemaLoader` 把 stage 产物 schema 外置成 JSON，**让 agent prompt 和输出解析器共用一份 schema**（"schema 跟着 skill 走"）。两根：`load_spec_from_skill(plugin,skill,file)` / `load_spec_from_plugin(plugin,file)`。缺失 → 硬报错 `SchemaNotFoundError`。

### 4.4 L7 Infrastructure：横切关注点

#### Workspace（`infra/workspace.py`）—— 单次运行的隔离目录

```text
   output/<run_id>/                  run_id = <UTC时间戳>-<uuid>
   ├── artifacts/                    agent 写入、设计产物、debug 迭代日志
   ├── agents/                       每次 spawn 的 jsonl 转录 + *.session.json 续跑 sidecar
   ├── subprocess/                   子进程日志
   ├── events.jsonl                  append-only 事件流（权威）
   ├── state_snapshot.json           原子写状态（恢复权威）
   ├── report.md / report.json
   ├── run.log                       控制台 tee
   └── .dirty                        mark_dirty 哨兵
```

#### EventLog（`infra/event_log.py`）

append-only、`threading.Lock` 保护、每行 `fdatasync`（硬杀最多丢在途 1 行）。`read`/`replay` 读取/流式回放。

#### RepoGuard（`infra/repo_guard.py`）—— op_dir 范围的 git 安全网

```text
   硬约束：所有破坏性操作只限 op_dir；绝不全仓 git reset --hard；绝不碰 git config/用户分支
   create_baseline(repo_root, op_dir) → HEAD sha（git）/ "filebackup:<path>"（非 git）
   rollback(...)                       → git checkout <ref> -- op_dir + git clean -fd op_dir
   changed_paths(...)                  → git diff ∪ 未跟踪文件（排除 ignore globs）
```

#### 其余

`logger.py`（三层反馈 + 每行 `[时间戳]` + ✓/⚠/✗/○ 图标）、`log_capture.py`（stderr tee 到 run.log，硬杀不丢尾）、`filesystem.py`（atomic_write = temp+os.replace）、`terminal.py`（tty/颜色/unicode 探测）。

### 4.5 L1/L2：CLI / TUI / Dispatcher

#### L1 命令树（`cli/main.py`）

```text
ascendc-devkit
├── run                 完整 workflow（~30 选项：mode/op-dir/golden三件套/chip/timeout/resume…）
├── stage run           单 stage 独立跑（三层 state 合并：from-run 快照→设计产物→--state→CLI）
├── show [--tail]       回放/实时轮询 events.jsonl
├── respond             回答挂起的非交互决策（写 decision_response.json）
├── debug-agent         从 spawn_context 事件重建 agent 上下文，交互式重放
├── skill list/validate/run
├── verify-env          6 项检查（Python/CANN/LLM/torch_npu/驱动/设备）
├── verify-repo         校验 profile + 目录
├── redeploy            构建+装+冒烟（debug 用）
└── run-cases           跑精度用例（debug 用）
```

**TUI**（`cli/tui.py`）：Rich 2×2 四面板 —— 左上 stage 进度表 / 右上指标 / 左下事件流 / 右下 agent 输出。

#### L2 Dispatcher（`application/dispatcher.py`）—— 全链路唯一接线点

`dispatch(task_request) → int(exit_code)` 的流程：

```text
   ① resume? ─是→ from_snapshot + Workspace.from_existing + node_status 续跑
        │否
        ② Workspace.create → 解析双 chip → 构造 State
        ③ 预检：用户输入 / 输入拓扑 / 部署能力 / 运行时(CANN+NPU，失败 EX_CONFIG 早退)
   ─────┼─────────────────────────────────────────────────────────────
        ④ 建 SDKBackend(回退 StubBackend) → Runner(注入 backend/workspace/progress)
        ⑤ 发 chip_decision 事件（每 run 一次）
        ⑥ GraphExecutor.execute(workflow.root, state)
        ⑦ 异常映射：Cancelled→SIGINT / DecisionPending→73 / Timeout→124+回滚
                    Precondition→DATAERR+回滚 / EnvNotAvailable→CONFIG+保仓
        ⑧ Report.generate → report.md/json
        ⑨ exit：halt 或任一 node failed → EX_DATAERR，否则 0
```

**依赖注入缝**：Runner 构造接收 `agent_backend`(L5)、`adapters` dict(L6)、`decision_handler`、`gate_registry`、`progress_callback`。`state.adapter`（由 ContextStage 用 profile 构造）在 dispatch 时注入 `runner._adapters["repository"]`。

### 4.6 Self-Evolution 子系统（与 orchestration 平级）

> **诚实定位**：这是**跨算子训练循环**——把平台**自己的 skill/agent/framework** 当作可训练的"模型"，用 cann-bench 三维分（编译 0.2 + 功能 0.3 + 性能 0.5）作为 loss。目前是**完整的"度量 + 归因"脚手架**，但**执行器缺位**（改进实际未写回，LLM 归因未建，无 CLI 入口）。内部的单算子 workflow `self_evolve_op` **已可跑**。

```text
   self_evolution/（上层：跨算子 epoch 循环）         orchestration/（下层：单算子推理）
   ┌──────────────────────────────┐                  ┌──────────────────────────────┐
   │ TrainingRunner.run()          │   每 op 一个      │ SelfEvolveOpWorkflow          │
   │  ┌─ epoch 0：基线            │   subprocess ──→  │  entry→…→codegen→precision_   │
   │  │  eval_all(operators)       │   ascendc-devkit  │  debug→cannbench_adapt→       │
   │  │  LossAggregator.aggregate  │   run --workflow  │  cannbench_eval→finalize      │
   │  │  AttributionEngine.attribute│  self_evolve_op │  （cannbench_eval = 一次性    │
   │  │  _check_regression(<50%基线)│                 │    loss，故意不回灌 codegen）  │
   │  │  _apply_improvements ⚠️no-op│                 └──────────────────────────────┘
   │  └─ 收敛 / patience / max_epoch│
   └──────────────────────────────┘
```

| 组件 | 现状 |
|---|---|
| `TrainingState`（frozen，仿 State）| ✅ 真实：epoch 进度/loss_history/op_baselines/review_queue |
| `LossAggregator` | ✅ 真实：等权均值，失败 op 计 0 拖低分 |
| `AttributionEngine` | ⚠️ 仅规则归因（按失败类型→组件 + 严重级），LLM 归因待建 |
| `OpScheduler` | ✅ 真实：ThreadPool + NPU slot，subprocess fan-out |
| `_apply_improvements` | ❌ **no-op**：只记 `ImprovementRecord(applied=False)`，不改任何文件 |
| CLI 入口 | ❌ 无 `ascendc-devkit train`，仅被测试调用 |

> 注意：`.claude/skills/evolution-*`（world-model/strategies/knowledge）是**单算子 kernel 优化工具包**，与此训练循环**无强制关系**，别混为一谈（设计文档 P8 明确）。

### 4.7 `.claude` 生态：skills / agents / plugins

**规模**：14 个 agent + 84 个 skill（55 裸 + 29 插件）+ 8 个插件。

**插件 = skill 的"按 stage 分组打包"**：

| 插件 | skill 数 | 典型 skill |
|---|---|---|
| `shared` | 4 | `ascendc-dev-knowledge`、`ascend-hardware` |
| `stage-design` | 13 | `ascendc-op-general-design`、`-tiling-split`、`-design-validate`… |
| `stage-codegen` | 2 | `ascendc-op-dev-coding`、`ascendc-dumptensor` |
| `stage-perf` | 3 | `ascendc-profiling`、`-tiling-strategy` |
| `stage-precision-debug` | 3 | `ascendc-precision-debug`、`-sync-static-check` |
| `stage-testdesign` | 3 | `AIInfra-OP-testdesign-*` |
| `stage-requirement` | 1 | `ascendc-op-req-analysis` |
| `codegen-coder-extra` | 1 | `ascendc-code-review` |

**Agent 清单**（按角色）：

| Agent | 角色 | 特点 |
|---|---|---|
| `requirement-analyst` | 需求分析 | 只管 WHAT，用 MCP `resolve_ambiguity` 澄清 |
| `ascendc-design-generator`（角色 A）| 设计生成 | 通用设计生产者，按 stage-design skill 方法产结构化产物 |
| `ascendc-design-reviewer`（角色 B）| 设计评审 | 质量门，可就地 Edit 修可修项 |
| `ascendc-design-anchor`（角色 C）| 外部锚点 | **只读**（`disallowed_tools:[Write,Edit,Glob]`），独立对照真实硬件 API 判 tiling 可行性 |
| `ascendc-coder` / `incremental-developer` | 代码生成 | 新生成 / 增量改 |
| `test-designer` | TDD 用例设计 | codegen 前固定验收用例 |
| `perf-tuner` | 性能调优 | 战术优化（展开/双缓冲/预取）|
| `cannbench-adapt` | 仓胶水适配 | 只改 `__init__/CMakeLists/registry`，**绝不碰算子源码** |
| `ascendc-precision-debugger`（+4 phase agent）| 精度调试 | **thin-orchestrator + 单 phase 执行器**模式：编排器只管 checkpoint 状态机 |

> 设计阶段 A/B/C 三角色 + 动态 ForkJoin 是本工程**多 agent 协作**的范式样本（见 §5.3）。

---

## 5. 典型功能设计

### 5.1 新算子生成全链路（9-Stage 端到端）

概念上的 9 stage 与代码实现对照（注意"能力下沉"后的实际形态）：

| 概念 stage | 代码实现 | 角色 | mode 差异 |
|---|---|---|---|
| entry | `entry` | 解析 TaskRequest、定 mode/仓/chip（确定性）| 共用 |
| context | `context` | 加载 profile、建 adapter、收参考码、**建 git 基线**、构造 RunContext | 共用 |
| requirement | `requirement`（agent: requirement-analyst）| 详设→Requirement + 澄清循环 | 增量：详设+现状→ChangeReq |
| design | `[general-design]`+`[detailed-design]` 两个 CompositeGroup | 算子/Tiling 设计（见 §5.3）| 增量：在已有设计上做 delta |
| (test_design) | `[test_design]` group | TDD 验收用例（codegen 前固定）| — |
| (codegen_init) | `codegen_init` | 确定性声明 kernel 分节 | — |
| codegen | `codegen`（agent: ascendc-coder / incremental-developer）| **仓内** op_dir 直接写码，agent 自闭环 build+smoke | new/incremental |
| verify | `precision_debug`（agent: ascendc-precision-debugger）| **in-stage** 精度调试闭环（verify 已删，精度归此）| 共用 |
| perf | `perf`（agent: perf-tuner，条件触发）| 性能基准 + 战术调优 | 共用 |
| integrate | `integrate` | 校验 op_dir 文件齐备 + 收尾（不落盘）| 共用 |
| finalize | `finalize` | 仓内编译 + dev_record + report | 共用 |

> **只有 3 个 stage 有 mode 差异**：context、requirement、codegen。代码自 codegen 起就在算子仓内；失败/超时由 git 基线回滚 op_dir，成功保留。

```text
   generate_ascendc 完整拓扑（requires_npu=True）：

   entry → context → requirement
     → [general-design 概念设计+review]
     → [detailed-design: intake→template-division→tiling(ForkJoin)→anchor→integrate→docgen→validate]
     → [test_design: analyze→casedesign→casegen]
     → codegen_init → codegen ──(build+smoke 自愈)─┐
     → precision_debug ─(精度自愈)────────────────┤  失败分级路由
     → perf ──(tuned→回 precision_debug 复验)──────┤  (corrective/escalation)
     → integrate → finalize                        │
     └─────────────────────────────────────────────┘
```

### 5.2 精度调试闭环（precision_debug）

"能力下沉"后，精度不再是独立 verify stage + 回环 codegen，而是 **agent 单 session 闭环自愈**：

```text
   ascendc-precision-debugger（编排器，只管状态机）
        │ dispatch
        ▼
   phase agent（单任务执行器，返回 RESULT:）
   ├─ run-tests     跑用例、解析、写 failed_case_queue 到 checkpoint
   ├─ diagnose      静态分析 + 候选池（Gate1/2 精度，或 error-code 解码+arch 对比）
   ├─ fix           按 fix_plan 改码、compile+test 验、commit/rollback
   └─ printf-locate 二分定位首个数值发散点

   闭环：改码 → git commit → redeploy(CLI) → run-cases(CLI) → 读 dumptensor 日志 → 再改
   终止：全部用例过 / 轮次耗尽 → debug_result.json（文件接力，transition 解析）
   resolve_condition：passed→default；未过→exhausted
     · generate_ascendc：exhausted → __halt__
     · self_evolve_op：  exhausted → cannbench_adapt（软门，给出分）
```

**关键设计**（P54）：精度闭环**不回灌 codegen**，自成闭环；fail_strategy=`halt`。`redeploy`/`run-cases` 是暴露给 agent 的 CLI（`application/debug_service.py`，经 `last_deploy.json` 文件接力解耦）。

### 5.3 设计阶段多角色协作（A/B/C + ForkJoin）

detailed-design 是工程里最复杂的子树，也是**多 agent + 并行 + 分级路由**的集大成：

```text
   SequentialGroup[detailed-design]（fail_strategy=halt 的作用域）
   ├─ dd-intake            短路入口（--detailed-design 直接跳 validate）
   ├─ template-division    模板清单 + 锁定全局决策
   ├─ ForkJoinGroup[tiling]  ← 动态：每个 template 一条并行分支
   │     branch(T1): split → buffer-kernel → precision-perf   ┐ 各自产
   │     branch(T2): split → buffer-kernel → precision-perf   ┘ tiling_results[T]
   ├─ anchor-forkjoin      每 template 一条 anchor-per-template（角色 C 只读判可行性）
   ├─ anchor-consistency   跨模板一致性门（infeasible→回 tiling 修正/corrective）
   ├─ integrate            聚合 → design_spec/tiling_strategy/data_flow
   ├─ docgen               渲染设计文档
   └─ validate             一致性门（redo_tiling→回 tiling；redo_doc→halt）
```

| 角色 | agent | fail_strategy | resolve_condition 路由 |
|---|---|---|---|
| 生成 A | ascendc-design-generator | halt（默认）| — |
| 评审 B | ascendc-design-reviewer | continue | `design_input_invalid→requirement` |
| 锚点 C | ascendc-design-anchor | continue（anchor-consistency）| `infeasible→tiling`(corrective)、`advisory_integrate→前向` |

**ForkJoin 状态合并**：每个 template 分支产 `tiling_results["Tn"]`，join 时按 key 浅合并；兄弟同名冲突 → `StateConflictError`。回环支持 **template 精准回滚**（`rerun_selector` 读 `anchor_report.blocking_issues[].target_template`，只重跑出问题的分支）。

### 5.4 仓内代码生成 + RepoGuard 安全网（Plan-A）

```text
   设计：代码不先进 workspace 再物化，而是 agent 直接 cwd=op_dir 写进目标仓（Plan-A）
        ┌─────────────────────────────────────────────────┐
        │  context 阶段：建基线 repo_baseline_ref           │
        │     git 仓 → HEAD sha；非 git → filebackup:<path> │
        │                                                  │
        │  codegen/perf/precision_debug：agent 在 op_dir 改码│
        │     自报改动 ∪ git diff → changed_paths           │
        │                                                  │
        │  失败/超时/Precondition → RepoGuard.rollback       │
        │     git checkout <ref> -- op_dir + git clean -fd  │
        │  成功 → 保留改动；主动中止 → 保留改动并提示         │
        └─────────────────────────────────────────────────┘
   约束：所有破坏性操作只限 op_dir，绝不全仓 reset，绝不碰用户分支
```

### 5.5 中断恢复（resume）

```text
   运行中 Ctrl-C / 超时 / DecisionPending / 崩溃  → exit 非零 + events.jsonl 已落盘
        │
        ▼  ascendc-devkit run --resume <run_id>
   ① from_snapshot(state_snapshot.json) 重建 State（泛型 _rebuild_value 反 asdict+JSON 往返）
   ② Workspace.from_existing(run_id) 重挂 _workspace
   ③ bind_run_log 续写 run.log
   ④ 按 node_status 续跑：completed 跳过、failed 上冒、其余重跑
   ⑤ CLI 可覆盖字段（None=未传→用快照值；非 None=覆盖）
   ⑥ --rerun-from <node>：失效该节点+因果下游 + 删 session sidecar（rerun≠resume，全新 spawn）
   ⑦ 非交互 abort 的决策：respond --choice N 写 decision_response.json，resume 时消费
```

> `State.to_snapshot` 刻意剥掉瞬时控制流信号（`is_terminal`/`_stage_failed`/`_bubble_condition`/`_loopback_feedback`）——它们只描述上一轮，`node_status` 才是唯一持久恢复权威。

### 5.6 自进化训练循环（进阶，诚实呈现）

见 §4.6。核心：cann-bench 分 = loss；失败 op 计 0 拖低总分；规则归因把失败映射到 skill/agent/framework 组件 + 严重级（framework=高，永不自动改）；回归护栏 = 任一 op 跌破基线 50% 告警。**当前止步于"度量+归因"，执行器（把改进写回）是 future work**。

---

## 6. 如何参与开发

### 6.1 环境准备 + 首次跑通

```bash
# 0. 硬性要求：Python>=3.11、CANN(ops_compile 在 PATH)、NPU(910B/C/D)、Claude Code CLI(claude)
pip install -e .

# 1. 环境自检（6 项：Python/CANN/LLM/torch_npu/驱动/设备）
ascendc-devkit verify-env
ascendc-devkit verify-repo --op-dir /path/to/omni-ops/inference/.../gelu

# 2. 新算子生成（完整 pipeline）
ascendc-devkit run --target-repo /path/to/omni-ops --repo-profile omni-ops \
  --op-name gelu --non-interactive --max-iterations 5

# 3. 增量开发
ascendc-devkit run ... --mode incremental --op-dir <绝对算子目录>

# 4. 实时进度（TUI）/ 中断恢复 / 查事件
ascendc-devkit run --tui ...
ascendc-devkit run --resume <run-id>
ascendc-devkit show --run <run-id> --tail
ascendc-devkit respond --run <run-id> --choice 1          # 回答挂起决策
ascendc-devkit debug-agent --run <run-id> --agent-name ascendc-coder
```

LLM 凭据在 `.claude/settings.json` 的 `env`（`ANTHROPIC_API_KEY`/`AUTH_TOKEN`/`BASE_URL`）。

### 6.2 扩展点地图（你要加东西，改哪里）

| 想做的事 | 改哪里 | 不改哪里 |
|---|---|---|
| **加一个 Stage** | `orchestration/stages/<x>.py`（继承 `Stage`，实现 IO 契约/actions/transition）+ `@register_stage` + 挂进 workflow 的 root 树 | 不要在 Python 写算子业务逻辑 |
| **加一个 Workflow** | `orchestration/workflow.py` + `@register_workflow`，override `root` 拼 StageNode 树 + TRANSITION_TABLE | 不要新写一套编排引擎 |
| **加一个 Agent** | `.claude/agents/<name>.md`（frontmatter 声明 plugins/skills/tools/max_turns）| 不要在 Python 硬编码 agent 名 |
| **加一个 Skill** | `.claude/plugins/<plugin>/skills/<name>/SKILL.md`（**必须**进 plugin 才能被 SDK 发现）+ `.claude-plugin/plugin.json` | 不要放裸 `.claude/skills/` 还指望 headless 能用 |
| **适配一个新目标仓** | `resources/repository-profiles/<repo>.yaml`（前缀 + variant + build stage）+ 必要时 `schemas/` | 不要在 Python 写 `if repo==...` |
| **调收敛/超时/模型** | `resources/orchestration-config.json`（iterations/timeouts/models/skills.stages）| 不要改代码 |
| **加算子知识** | `.claude/skills/` 或 plugin skill 的 markdown（按 knowledge_policy 三层）| 不要进 Python |
| **加一个 Gate** | `Gate` 子类（纯 `evaluate`）+ stage 的 `gate()` 返回它 + RunGate action | 不要把副作用写进 Gate |

### 6.3 测试约定（TDD + 默认全量真实环境）

```bash
pytest                  # 默认：UT 全量 + 非 heavy_llm 的 ST + 预检 LLM/NPU/CANN
pytest --quick          # 快速内环：排除 llm/slow/npu/cann，跳过预检，秒级
pytest --ut / --st      # 仅 UT（无外部依赖）/ 仅 ST
pytest -m llm           # 标记筛选
pytest tests/ut/test_layer_dependencies.py   # 架构合规守护
```

> **cann-bench parity 用例默认真跑**：`tests/conftest.py` 启动时按单一解析路径（env `ASCENDC_TEST_CANN_BENCH` → `tests/.testrepos.local.json` → 兄弟目录）解析外部参考仓 cann-bench，可用则把 `<cann-bench>/src` 自动挂进 `sys.path`。因此 `test_precision_compare.py::TestParityCannBench`（devkit 标准方法 vs cann-bench `compare_tensors` 逐 case 对拍）**无需手动 `PYTHONPATH` 即可运行**（`TORCH_DEVICE_BACKEND_AUTOLOAD=0` 也由 conftest 统一 setdefault）。cann-bench 真缺失时才按 §3.7 诚实 skip（可选外部前置，非缺陷）。

| 红线 | 含义 |
|---|---|
| **失败必修根因** | 禁止 `skip`/`try-except pass`/条件跳过绕过失败 |
| **标记=运行时真实依赖** | `@llm/@npu/@cann/@slow` 只标"缺了会失败"的用例；mock 掉的不标 |
| **环境缺失诚实报错** | 报错并列缺失项，绝不改测试/代码强行变绿 |
| **heavy_llm 不默认跑** | 真实 LLM 全流程、分钟级+高 token；跑前需用户确认，不跑须诚实记录 |

UT 用 `StubBackend`（纯逻辑/编排），ST 走 `dispatch()` 真实链路。涉及 SDK/CLI/MCP/agent 真实行为的链路必须有 `@llm` 真实用例兜底（§3.9）。

### 6.4 问题跟踪：四层方案体系（`docs/plan/`）

所有"怎么做"的内容按**回答什么问题**分层（不是按粗细）：

| 层 | 回答 | 组织 | 文件 |
|---|---|---|---|
| L1 问题记录 | **哪里坏了？凭什么这么说？** | 按问题 Pn | `<work>/NN-problems.md` |
| L2 总纲 | **做哪几件事、什么顺序、到哪了？** | 按工作步骤 | `skills-integration-and-tdd-plan.md`（全局唯一）|
| L3 方案分析 | **有哪些选项、选哪个、为什么？** | 按步骤 | `<work>/NN-analysis.md` |
| L4 实施方案 | **改哪个函数、什么顺序、怎么验证？** | 按步骤 | `<work>/NN-impl-*.md` |

> 规则：每个事实只在一层有"产权"，其他层只引用；L1 只陈述客观事实，不提方案/不排序/不决策。改 bug 先定位根因，再在"最小改动"与"正确改动"间按工程价值取舍。

### 6.5 工程红线（`CLAUDE.md` 精华，改动前自检）

1. **框架完整性**：7 层严格向下依赖；State 是不可变 frozen dataclass，用 `with_updates` 建新实例；events.jsonl 是权威。
2. **方案合理性优先**：过四把尺子——可维护 / 可扩展 / 可诊断 / 架构合理；单一方案不够就**组合**（正确改动保不变式 + 宽容兜底防崩 + 可观测性防掩盖）。
3. **加载期校验 > 运行期暴露**。
4. **不考虑向后兼容**：要么彻底改、要么不改，不留过渡层。
5. **资源路径不硬编码 / 仓自闭环**：禁 `Path.home()`/`~/.claude/`，只指向项目自身。
6. **Skill 即插即用**：任一 skill 取出后能在 TUI 直接 `/<skill>` 跑通，不依赖工程注入。
7. **唯一通路，不留旧债**：同一职责只允许一条通路，改造时删掉被取代的旧通路，新旧并存只能是限时手段。

### 6.6 常见开发任务速查

| 任务 | 入口文件 |
|---|---|
| 理解一次运行的全程 | `application/dispatcher.py:dispatch` |
| 看状态机核心 | `orchestration/kernel/{state,runner,action}.py` |
| 看图执行/回环 | `orchestration/graph_executor.py` + `node*.py` |
| 看某 stage 逻辑 | `orchestration/stages/<name>.py` |
| 看 workflow 拓扑 | `orchestration/workflow.py`（5 个内置 workflow）|
| 看 agent 怎么被起 | `capabilities/agent/sdk_backend.py:_spawn` |
| 看 skill 怎么加载 | `capabilities/skill/loader.py` |
| 看仓怎么编译 | `adapters/repository/generic.py:build` + `resources/repository-profiles/*.yaml` |
| 看事件/恢复 | `infra/{event_log,workspace,repo_guard}.py` + `kernel/event.py` |
| 调参 | `resources/orchestration-config.json` |

---

## 7. 延伸阅读

| 想深入了解 | 去看 |
|---|---|
| 架构全貌（详尽参考）| `docs/architecture-overview.md` |
| 某一层的细节 | `docs/layers/L1..L7-*.md` |
| 某 stage 的细节 | `docs/stages/*.md` |
| 测试约定全貌 | `tests/README.md` |
| 问题/方案体系 | `docs/plan/README.md` + `docs/plan/00-status-summary.md` |
| 自进化设计 | `docs/plan/self-evolution-design.md` + `docs/plan/self-evolution/04|05-*.md` |
| 算子开发总规则 | `.claude/rules/ascendc-dev.md` |
| 工程原则 | `CLAUDE.md` |

---

> **串讲建议节奏**（~1h）：§1+§2（20min 建立全景）→ §3.2+§3.3+§3.4（20min 讲透状态机与回环，这是核心）→ §5.1+§5.3（15min 走一遍端到端 + 设计多角色）→ §6（5min 上手路径）→ 现场答疑。
