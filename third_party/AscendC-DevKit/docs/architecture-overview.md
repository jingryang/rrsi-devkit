# ascendc-devkit 架构总览

> **定位**：面向 Ascend NPU 的 AI 驱动 AscendC 算子开发平台，支持新算子生成与存量算子增量开发，在目标算子代码仓内直接生成、编译、调试代码。
> **能力**：7 层分层架构 | 9-Stage Pipeline | 图化编排 (GraphExecutor / StageNode 树 / ForkJoinGroup 并行 / SideTask 旁路) | 作用域化路由 (per-scope quota + 升级冒泡 + stagnation 检测) | 内置 Workflow (generate_ascendc / _se / _dev / full_test) | per-stage 模型配置 | ExecContext/CancelToken 并行安全 | 仓内代码生成 (cwd=op_dir) + RepoGuard git 基线快照/回滚 | 仓内编译 (adapter.build) | L1 CLI 全命令(含 debug-agent) | L6 Adapters(含 NPU Slot/PTA) | Runner Action 执行引擎 | PrecisionGate/NPU/CANN 真实 | Workflow + IO 验证 | --enable-stubbed | Skill/Knowledge 子系统 | verify-env/verify-repo | 双模式 + 非交互自动化 | --resume (含并行/嵌套 node_status frontier) | 4-Panel TUI 实时进度 | Progress Callback | Workflow/Stage Timeout | Stage 迭代 Resume | debug-agent 交互式调试 | NPU Slot 管理 | PTA Toolchain | DecisionPendingError 生命周期 | dev_record | LLM Provider 多态 | Webhook | CompositeStage | 三层分级路由(corrective/escalation/validation) | Decision Log 结构化决策传递 | 交互模式 loopback 用户反馈注入 | .claude/skills + .claude/agents 双发现

本文档是架构总览。详细设计分布在独立文件中——7 个 Layer 设计 + 9 个 Stage 设计。

---

## 0. 项目概览

**ascendc-devkit** 是一个 AI 驱动的 AscendC 算子开发平台。它接收算子需求描述，通过 LLM Agent 多阶段协作，在指定的目标算子代码仓内直接生成、编译、调试可验证的 AscendC 算子代码。

### 0.1 服务场景

| 场景 | 输入 | 输出 |
|---|---|---|
| 新算子生成 | 需求描述 + 用例 | 全新算子完整代码（在算子仓内新增算子目录与源码） |
| 增量算子开发 | 目标仓现有算子 + 变更需求 | 在算子仓内直接修改/新增/删除源码 |
| 性能优化 | 已有算子 + 性能 baseline | 优化后版本 + 性能对比 |
| 调试与分析 | 算子代码 + 失败用例 | 缺陷定位 + 修复方案 |

### 0.2 系统上下文

```
                ┌─────────────────────────────────────┐
                │         算子开发工程师               │
                │  (CLI / TUI / 自动化脚本)            │
                └────────────────┬────────────────────┘
                                 │
                  TaskRequest    ▼
              ┌──────────────────────────────────┐
              │                                  │
              │         ascendc-devkit           │
              │   (AI 驱动算子开发平台)            │
              │                                  │
              └─┬────────┬────────┬────────┬─────┘
                │        │        │        │
        ┌───────▼──┐ ┌───▼───┐ ┌──▼──┐ ┌───▼──────┐
        │ LLM      │ │ NPU   │ │CANN │ │ 目标算子  │
        │ Provider │ │Runner │ │Tool │ │ 代码仓    │
        └──────────┘ └───────┘ └─────┘ └──────────┘
```

平台对外接入四类外部资源，所有外部交互通过 `adapters/` 隔离。

---

## 1. 设计目标

### 1.1 功能目标

| 目标 | 含义 |
|---|---|
| 统一新生成与增量开发 | 同一 9-Stage Pipeline，mode 参数化区分两类场景 |
| 不绑定代码仓 | `RepositoryProfile`(YAML) + `RepositoryAdapter`(Python ABC) 双层解耦 |
| 多 LLM Provider | `adapters/llm/` 协议化，环境变量切换 |
| 结构化产物 | 事件流（`events.jsonl`）为权威记录；代码在算子仓内，git 基线快照保证可回滚 |
| 明确扩展点 | 加 workflow / 加目标仓 / 加 LLM provider / 加 agent/skill 都不改核心 |
| 长任务可观测、可中断、可恢复 | 三层反馈 + 信号处理 + event sourcing |
| 单算子粒度 + 外部可批量编排 | 工具只跑单算子；通过 NPU 资源契约 + 非交互模式支持外层调度 |

### 1.2 架构红线

- 引擎核心是纯函数状态机，**不感知** LLM / 编译器 / NPU 等外部世界
- 算子业务知识（如何写 AscendC、如何 tiling）只活在 agent prompt 与 skill 资源里，**不内联进 Python 代码**
- 与外部世界的所有交互通过 Adapter 层；业务层只持有 protocol/ABC
- 凡是"和某个代码仓相关"的知识，都进 `repository-profiles/<repo>.yaml`，**不在 Python 里写 `if repo == "omni-ops"` 仓名分支**
- 资源路径不在代码中硬编码；增删资源只改资源清单文件

---

## 2. 分层架构

### 2.1 设计动机：为什么需要七层

算子开发平台面临四类彼此正交的变化维度：

| 变化维度 | 例子 | 变化频率 |
|---|---|---|
| 用户入口形式 | CLI / TUI / CI 脚本 / IDE 插件 | 低（加一种入口） |
| 业务场景 | 新生成 vs 增量开发 vs 性能优化 vs 调试 | 中（加一种 workflow） |
| 目标代码仓 | omni-ops / ops-transformer / ops-nn / ops-math / ... | 高（每仓一套约定） |
| 外部基础设施 | LLM Provider / NPU 型号 / CANN 版本 | 高（环境升级） |

如果把这些维度混在同一个模块里，改一个维度就可能牵动其他三个。分层架构的核心思想是：**让每一层只对一个变化维度负责**。

### 2.2 七层总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  L1   Presentation        CLI / TUI / Slash command                  │
│                           ── 把用户输入翻译成 TaskRequest             │
│                                                                      │
│  L2   Application         TaskRequest 路由、Profile 绑定、最终汇报   │
│                           ── 解析意图、选择 workflow、汇聚事件        │
│                                                                      │
│  L3   Orchestration       Workflow 编排 / Stage / Gate / Kernel      │
│                           ── 纯函数状态机驱动多阶段协作               │
│                                                                      │
│  L4   Domain              OperatorSpec / OperatorIdentity / Profile  │
│                           ── 纯数据，零依赖，无副作用                 │
│                                                                      │
│  L5   Capabilities        LLM Agent / Skill / Knowledge              │
│                           ── LLM 能力封装，不感知算子业务             │
│                                                                      │
│  L6   Adapters            Repository / NPU / LLM / Toolchain         │
│                           ── 隔离所有外部世界，只暴露 protocol        │
│                                                                      │
│  L7   Infrastructure      Workspace / Event / Logging / FS           │
│                           ── 横切关注点，被所有上层使用               │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
         │                                                ▲
         └────── 严格向下依赖，绝不允许向上引用 ──────────┘
```

**各层隔离的关注点**：

| 层 | 隔离的关注点 | 如果这一层不存在会怎样 |
|---|---|---|
| L1 Presentation | 用户入口形式 | CLI / TUI / CI 三种入口各自重复解析逻辑 |
| L2 Application | 用例编排 | 每个 workflow 各自处理 profile 加载、报告生成 |
| L3 Orchestration | 流程状态机 | Stage 编排逻辑散落在各个 workflow 里，无法复用 |
| L4 Domain | 领域概念定义 | `OperatorSpec` / `OperatorIdentity` 等类型定义散落各处，不一致 |
| L5 Capabilities | LLM 集成方式 | Agent/Skill/Knowledge 调用逻辑内联在 workflow 里 |
| L6 Adapters | 外部系统交互 | 换一个 LLM provider 或代码仓需要改 workflow 代码 |
| L7 Infrastructure | 横切基础能力 | Workspace/日志/事件 的实现细节污染业务代码 |

### 2.3 层间数据流

以"新算子生成 + 落 omni-ops 仓"为例，一次完整运行中数据如何穿越七层：

```
L1  cli/commands/run.py
    │  解析 sys.argv → 构造 TaskRequest
    ▼
L2  application/dispatcher.py
    │  加载 RepositoryProfile → 选择 workflow → 构造初始 State
    ▼
L3  orchestration/kernel/runner.py
    │  ┌─ next_action(state) → SpawnAgent("ascendc-coder", working_dir=op_dir, ...)
    │  ├─ execute(SpawnAgent) ──────────────────────────────┐
    │  │                                                     │
    │  ▼                                                     ▼
    │ L5  capabilities/agent/sdk_backend.py              L6 adapters/llm/anthropic.py
    │     加载 system prompt + 白名单                      发送 API 请求
    │     cwd=op_dir 启动 agent（Write/Edit 直接改仓）     接收 streaming response
    │     收集本轮改动（自报 ∪ op_dir git diff）           │
    │     │                                                │
    │     └────────── AgentResult ←────────────────────────┘
    │  │
    │  ├─ transition(state, AgentResult) → 新 State
    │  ├─ event_log.append(...) ──→ L7 infra/workspace.py → events.jsonl
    │  └─ terminal_state → 返回 final_state
    ▼
L2  application/report.py
    │  events.jsonl → report.md + report.json
    ▼
L1  cli/exit_codes.py → sys.exit(0)
```

**L4 Domain 不在流程图中作为"处理步骤"出现**——它的类型（`TaskRequest`, `State`, `Action`, `OperatorSpec`, `OperatorIdentity` 等）贯穿所有层，作为各层之间的数据契约。

### 2.4 跨层调用规则

```
✅ 允许                                    ❌ 禁止
───────────────────────────────────        ──────────────────────────────────
L1 → L2, L4                                L4 → L3    (Domain 反查 Orchestration)
L2 → L3, L4, L7                            L5 → L3    (Capabilities 反查 Workflow)
L3 → L4, L5, L6, L7                        L6 → L3    (Adapter 反查 Workflow)
L4 → (无依赖，纯数据)                       任意层 → L1 (不能反查 CLI)
L5 → L4, L6, L7                            跨层 import "../../.."
L6 → L4, L7                                直接 import 具体实现而非 protocol
L7 → (无依赖)
```

**协议依赖 vs 实现依赖**：上层可以 import 下层的 protocol/ABC，但不能 import 下层的具体实现。具体实现的选择通过依赖注入完成。

### 2.5 架构原则总结

| # | 原则 | 在架构中的体现 |
|---|---|---|
| 1 | 单向依赖 | 七层自下而上，严格向下依赖。依赖方向 = 变化频率方向（底层稳定，上层多变） |
| 2 | 协议隔离 | 层与层之间通过 protocol/ABC 通信，不依赖具体实现 |
| 3 | 纯函数核心 | L3 kernel 是纯函数状态机，所有副作用集中在 `execute(action)` |
| 4 | 知识外置 | 算子业务知识不进 Python 代码，全在 `.claude/` 和 `resources/` 的 markdown/YAML 文件中 |
| 5 | 配置驱动 | 代码仓差异不进 Python 分支，全在 YAML profile 中 |
| 6 | 事件溯源 | `events.jsonl` 是运行历史的唯一权威，State 可由事件重建 |

---

## 3. 9-Stage 统一 Pipeline

### 3.1 图化编排（StageNode 树）

Workflow 内部表示为 StageNode 树，由 GraphExecutor 统一驱动：
- AtomicStage（叶子，包装 Stage）/ SequentialGroup（顺序+作用域 loopback）
- ForkJoinGroup（并行）/ SideTask（fire-and-forget 支线）
路由计数器按作用域路径存入 `State.routing_scopes`，支持嵌套 loopback 与并行/嵌套 resume。
详见 `docs/superpowers/specs/2026-05-30-workflow-graph-design.md`。

新生成与增量开发不是两条独立链路，而是同一 pipeline 在 mode 维度上的两种实例化。

```
                        mode = new                  mode = incremental
                        ─────────                   ─────────────────

Stage  entry          解析 TaskRequest，确定 mode / target_repo / op_name
                        共用入口

Stage  context        加载 RepositoryProfile        scan_existing_operator()
                        建立写仓前 git 基线           读 target_repo/<op>/ 代码

Stage  requirement    详设文档 → Requirement        详设 + 现状 → ChangeRequirement
                                                     + 不明确项澄清循环

Stage  design         完整算子设计                  在已有设计上做 delta
                        Tiling 策略                   只改受影响部分

Stage  codegen        在算子仓 op_dir 内新增源码    在算子仓 op_dir 内修改源码
                        （cwd=op_dir，直接写仓，自报改动 ∪ git diff 收集）

Stage  verify          调算子仓自身构建系统编译 + 精度验证（共用）

Stage  perf            性能基准测试 + 战术调优（共用，仓内改码）
                        tactical tuning: loop unrolling / UB 双缓冲 / 数据预取

Stage  integrate      校验 op_dir 文件齐备 + 收尾（共用，不落盘）
                        target_files 从 op_dir 读取

Stage  finalize       编译 in target_repo（共用）
                        生成 report
                        增量模式更新 dev_record.md
```

只有 3 个 Stage 有 mode 差异：context、requirement、codegen。其余 Stage 逻辑完全一致；代码自 codegen 起就在算子仓内，integrate 在落盘层统一为「校验 + 收尾」。失败/超时由 git 基线回滚 op_dir，成功保留，主动中止保留改动并提示。

---

## 4. 目录结构

```
ascendc-devkit/
├── pyproject.toml
├── .gitignore
├── src/ascendc_devkit/               # Python 源（按层组织）
│   ├── cli/                      # L1 Presentation（Click CLI）
│   │   ├── main.py
│   │   ├── tui.py                 # Rich TUI 4-Panel (2×2 grid + Live auto-refresh)
│   │   ├── exit_codes.py          # L1 exit codes（从 domain/exit_codes.py re-export）
│   │   └── commands/
│   │       ├── run.py            # 完整 9-Stage Pipeline + --workflow-timeout/--stage-timeout/--resume-iteration
│   │       ├── stage.py          # 单 Stage 独立运行
│   │       ├── verify_env.py     # 真实环境检查 (CANN/Python/torch_npu/NPU Driver/Device)
│   │       ├── verify_repo.py    # 真实仓校验 (YAML profile + 目录检查)
│   │       ├── show.py           # 回放 events（支持 --tail 实时 polling）
│   │       ├── respond.py        # 异步决策响应（读 pending → 写 decision_response）
│   │       ├── skill.py          # skill 发现与管理 (list/validate, 经 L2→L3→L5)
│   │       └── debug_agent.py    # debug-agent: 从 events.jsonl 重建 agent 上下文交互式调试
│   ├── application/              # L2 Application
│   │   ├── dispatcher.py         # dispatch() + dispatch_single_stage()
│   │   ├── report.py             # Report.generate() / write_markdown / write_json
│   │   ├── profile_loader.py
│   │   └── skill_service.py      # L2 skill 封装 (→ L3 orchestration/skill 委托)
│   ├── orchestration/            # L3 Orchestration
│   │   ├── base.py               # StageProtocol, Stage, CompositeStage, validate_inputs
│   │   ├── registry.py           # STAGE_REGISTRY + WORKFLOW_REGISTRY
│   │   ├── workflow.py           # Workflow + generate_ascendc / _se / _dev / full_test
│   │   ├── node.py               # StageNode / AtomicStage / SequentialGroup + node_paths
│   │   ├── node_forkjoin.py      # ForkJoinGroup (并行) + merge_forkjoin (冲突检测)
│   │   ├── node_sidetask.py      # SideTask (fire-and-forget 旁路)
│   │   ├── graph_executor.py     # GraphExecutor — StageNode 树遍历 + 作用域路由
│   │   ├── exec_context.py       # ExecContext + CancelToken (并行安全)
│   │   ├── model_config.py       # per-stage 模型映射
│   │   ├── skill.py              # L3 skill 封装 (→ L5 SkillLoader 委托)
│   │   ├── kernel/
│   │   │   ├── state.py          # State (含 routing_scopes / node_status)
│   │   │   ├── action.py         # Action 类型 (SpawnAgent/RunGate/Integrate 等)
│   │   │   ├── event.py          # Event schema (含作用域 graph 事件)
│   │   │   ├── gate.py           # GateResult, Gate(ABC)
│   │   │   └── runner.py         # Runner.run_stage() + cancel + ExecContext
│   │   └── stages/
│   │       ├── entry.py          # Stage 1: 请求校验
│   │       ├── context.py        # Stage 2: profile/adapter/参考代码
│   │       ├── requirement.py    # Stage 3: 需求解析 (Agent)
│   │       ├── design.py         # Stage 4: 算子/Tiling 设计 (Agent)
│   │       ├── codegen.py        # Stage 5: 仓内代码生成 (Agent, cwd=op_dir)
│   │       ├── verify.py         # Stage 6: 仓内编译 + 精度验证
│   │       ├── perf.py           # Stage 7: 性能基准测试
│   │       ├── integrate.py      # Stage 8: op_dir 校验 + 收尾
│   │       ├── finalize.py       # Stage 9: 报告+清理
│   │       ├── gates.py          # 共用 Gate (BuildInRepoGate)
│   │       └── smoke.py          # 最小测试 Stage
│   ├── domain/                   # L4 Domain (纯数据)
│   │   ├── operator.py           # OperatorSpec, OperatorIdentity, TensorSpec
│   │   ├── requirement.py        # Requirement, UnclearItem
│   │   ├── repository.py         # RepositoryProfile, BuildConfig, ReferenceConfig
│   │   ├── contract.py           # StageIOContract
│   │   ├── transition.py         # StageTransition
│   │   ├── exceptions.py         # DecisionPendingError（跨层共享异常）
│   │   ├── exit_codes.py         # EX_OK/EX_DECISION_PENDING 等退出码
│   │   ├── skill.py              # SkillSpec, AgentManifest (纯数据)
│   │   └── verification.py       # BuildResult, PrecisionResult, PerformanceResult
│   ├── capabilities/             # L5 Capabilities
│   │   ├── mcp_tools.py          # build_engine_mcp_server()
│   │   ├── skill/
│   │   │   ├── __init__.py       # SkillLoader + load_agent_manifest 导出
│   │   │   └── loader.py         # SkillLoader (discover→SkillSpec, load_agent_manifest, resolve_skills)
│   │   ├── knowledge/
│   │   │   └── __init__.py       # IndexNode + KnowledgeBase (load_index/search_api/load_document)
│   │   └── agent/
│   │       ├── backend.py        # AgentBackend(ABC), AgentResult
│   │       ├── sdk_backend.py    # SDKBackend (claude_agent_sdk)
│   │       └── stub_backend.py   # StubBackend (测试用)
│   ├── adapters/                 # L6 Adapters
│   │   ├── repository/
│   │   │   ├── base.py           # RepositoryAdapter(ABC)
│   │   │   ├── generic.py        # GenericRepositoryAdapter (YAML 驱动)
│   │   │   └── profile_loader.py # ProfileLoader (从 YAML 解析 RepositoryProfile)
│   │   ├── toolchain/
│   │   │   ├── cann.py           # CANNToolchain (CANN 环境检测 + CMakeLists 生成)
│   │   │   └── pta.py            # PTAToolchain (torch.ops.custom 注册代码生成)
│   │   ├── npu/
│   │   │   ├── runner.py         # NPURunner (真实 NPU 执行 + harness 生成)
│   │   │   └── slot.py           # NPUSlotManager (线程安全多卡分配 acquire/release)
│   │   └── llm/
│   │       ├── base.py           # LLMProvider(ABC)
│   │       ├── anthropic.py      # AnthropicProvider
│   │       ├── bedrock.py        # BedrockProvider
│   │       └── vertex.py         # VertexProvider
│   └── infra/                    # L7 Infrastructure
│       ├── workspace.py          # Workspace 管理
│       ├── event_log.py          # EventLog (events.jsonl)
│       ├── logger.py             # Logger (结构化日志)
│       ├── terminal.py           # 终端能力检测
│       ├── filesystem.py         # 文件系统操作
│       └── repo_guard.py         # RepoGuard (算子仓 git 基线快照 + 回滚)
├── .claude/                      # Claude Code 原生发现目录
│   ├── agents/
│   │   ├── ascendc-coder.md
│   │   ├── ascendc-design-generator.md   # 设计角色 A (生成)
│   │   ├── ascendc-design-reviewer.md    # 设计角色 B (评审)
│   │   ├── ascendc-design-anchor.md      # 设计角色 C (外部锚点)
│   │   ├── incremental-developer.md
│   │   ├── requirement-analyst.md
│   │   └── perf-tuner.md
│   └── skills/                   # Skill 定义 (Claude Code + DevKit 双发现)
├── resources/                    # 资源文件
│   └── repository-profiles/
│       ├── omni-ops.yaml
│       ├── omni-ops-full.yaml
│       ├── ops-nn.yaml           # 含 {category} 模板变量
│       └── ops-transformer.yaml
├── tests/
│   ├── fixtures/                 # 测试数据
│   ├── ut/                       # 单元测试 (无需 LLM/NPU)
│   │   ├── domain/               # L4 Domain UT
│   │   ├── infra/                # L7 Infra UT
│   │   ├── orchestration/        # L3 Kernel + Stages + Workflow UT
│   │   ├── adapters/             # L6 Adapters UT (含 NPU Slot/PTA/LLM)
│   │   ├── application/          # L2 Application UT
│   │   ├── capabilities/         # L5 Capabilities UT (含 Knowledge)
│   │   └── cli/                  # L1 CLI UT (含 TUI/DebugAgent)
│   └── st/                       # 集成测试 (decision-loop/timeout/incremental/loopback)
├── docs/                         # 设计文档
├── scripts/
│   └── spike_mcp_verify.py
```

纯 Python 包，入口 `ascendc-devkit`（`pyproject.toml` 声明 console_script）。L5 通过 `claude_agent_sdk` 包管理 Claude Code 子进程，无需额外 Rust binary。

---

## 5. 详细设计索引

### 纵向 — 7 层详细设计

| 文件 | 核心内容 |
|---|---|
| [`layers/L1-presentation.md`](layers/L1-presentation.md) | CLI 命令树、TUI 面板协议、输出格式化、L1→L2 TaskRequest 构造、三层反馈、退出码 |
| [`layers/L2-application.md`](layers/L2-application.md) | dispatcher 路由、workflow/mode 解析、TaskRequest schema、L2→L3 调用契约、Report 生成 |
| [`layers/L3-orchestration.md`](layers/L3-orchestration.md) | StageProtocol/CompositeStage、事件状态机、Runner loop、中断/恢复、Event Sourcing、Stage 内迭代循环 |
| [`layers/L4-domain.md`](layers/L4-domain.md) | OperatorSpec、OperatorIdentity、RepositoryProfile、Requirement 领域模型 |
| [`layers/L5-capabilities.md`](layers/L5-capabilities.md) | Agent/Skill 抽象、prompt 构造协议、tool 契约、L5↔L6 边界 |
| [`layers/L6-adapters.md`](layers/L6-adapters.md) | RepositoryAdapter/NPU/LLM/Build 四类 adapter ABC + 实现注册、扩展点 |
| [`layers/L7-infrastructure.md`](layers/L7-infrastructure.md) | workspace 布局、subprocess 管理、event 持久化、文件锁、终端能力 |

### 横向 — 9 Stage 详细设计

| 文件 | 核心内容 |
|---|---|
| [`stages/entry.md`](stages/entry.md) | 需求描述解析、用例验证、mode 判定 |
| [`stages/context.md`](stages/context.md) | 目标仓分析、参考代码收集、RepositoryAdapter 初始化 |
| [`stages/requirement.md`](stages/requirement.md) | 设计文档分析、不明确项提取、需求澄清循环 |
| [`stages/design.md`](stages/design.md) | 算子/Tiling 设计、增量模式 delta 设计 |
| [`stages/codegen.md`](stages/codegen.md) | Agent 调度、代码生成迭代、自愈循环 |
| [`stages/verify.md`](stages/verify.md) | 编译验证、精度验证、错误分类与反馈注入 |
| [`stages/perf.md`](stages/perf.md) | 性能基准测试、战术调优（loop unrolling/UB 双缓冲）、战略性修改回退路径 |
| [`stages/integrate.md`](stages/integrate.md) | op_dir 文件完整性校验、收尾标记 |
| [`stages/finalize.md`](stages/finalize.md) | 产物汇总、report 生成、清理、dev_record 更新 |

---

## 附录 A：关键术语

| 术语 | 定义 |
|---|---|
| **TaskRequest** | 用户 CLI 输入翻译后的不可变结构（L1→L2） |
| **Workflow** | 一组有序 Stage 的声明（L3） |
| **Stage** | Pipeline 的一个步骤，由 Gate 控制进入与退出（L3） |
| **Gate** | 决定是否进入下一 stage 的纯判定函数（L3） |
| **OperatorSpec** | 算子的静态身份（name, signature, dtype）（L4） |
| **OperatorIdentity** | 已存在算子在某 repo 中的实例（含文件路径）（L4） |
| **RepositoryProfile** | 描述目标仓约定的 YAML 配置（L4/L6） |
| **RepositoryAdapter** | 实现仓库操作的 Python ABC（L6） |
| **GenericRepositoryAdapter** | 默认 adapter，纯 YAML 配置驱动（L6） |
| **RepoGuard** | 算子仓改动的 git 基线快照与失败回滚，范围限定 op_dir（L7） |
| **op_dir** | 算子在目标仓内的代码目录；codegen/verify/perf 的 agent cwd（L4 OperatorIdentity.op_dir） |
| **changed_files.json** | agent 在 op_dir 内自报本轮改动文件的清单（相对路径 + created/modified/deleted） |
| **Workspace** | `./output/<run_id>/`，单次运行的事件/报告/备份根（L7） |
| **Event** | 写入 `events.jsonl` 的结构化事件，运行历史的权威记录（L3/L7） |
| **Action** | Workflow 在某状态下产出的下一步指令（L3） |
| **DecisionPendingError** | 非交互模式下需要用户决策时抛出的异常，由 Runner→Dispatcher→exit(73) 传递（L4 domain） |
| **pending_decision.json** | 非交互 abort 模式写入 workspace.dir 的决策挂起文件 |
| **decision_response.json** | 用户通过 `respond` 命令写入的决策回复文件，resume 时读取 |
| **WorkflowTimeoutError** | 工作流整体超时时抛出，由 `_check_timeout()` 在迭代边界检测（L4 domain, EX_TIMEOUT=124） |
| **StageTimeoutError** | 单 Stage 超时时抛出，每个 Stage 独立的 monotonic 截止时间 |
| **Progress Callback** | `Callable[[str, str, dict|None], None]` DI 注入模式，Runner/dispatcher 在 stage 生命周期边界同步回调 |
| **NPUSlotManager** | 线程安全的多 NPU 卡分配管理器（acquire/release/list_available），基于 threading.Lock |
| **PTAToolchain** | PyTorch Ascend adapter，生成 `torch.ops.custom` 注册代码 |
| **debug-agent** | 从 events.jsonl 的 spawn_context 事件重建 agent 上下文，启动 `claude` 子进程进行交互式调试 |
| **Event Sourcing** | events.jsonl 是真权威，State 可由事件流重建的设计模式 |

## 附录 B：缩写

| 缩写 | 全称 |
|---|---|
| CANN | Compute Architecture for Neural Networks |
| PTA | PyTorch Adapter |
| NPU | Neural Processing Unit |
| UB | Unified Buffer |
| LLM | Large Language Model |
| ABC | Abstract Base Class |
