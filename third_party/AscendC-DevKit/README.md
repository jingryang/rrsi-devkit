# AscendC-DevKit

AI 驱动的 AscendC 算子开发平台。接收需求描述，通过 LLM Agent 多阶段协作生成可编译、可验证的 AscendC 算子代码，并落到目标代码仓。

## 架构

7 层分层 + 9-Stage Pipeline，严格向下依赖。

```
L1  Presentation    CLI / TUI
L2  Application     路由、Profile 绑定、报告
L3  Orchestration   Workflow 编排 / Graph 执行 / Stage / Gate / Runner
L4  Domain          纯数据 dataclass（零依赖）
L5  Capabilities    LLM Agent / Skill / Knowledge
L6  Adapters        Repository / NPU / LLM / Toolchain
L7  Infrastructure  Workspace / Event / Log / FS
```

### 9-Stage Pipeline

```
entry → context → requirement → design → codegen → verify → perf → integrate → finalize
```

支持 `new`（新算子生成）和 `incremental`（增量开发）两种模式。

### Graph 执行模型

L3 编排基于统一的 `StageNode` 树，由 `GraphExecutor` 遍历驱动，支持作用域化（scoped）的 loop-back 路由：

| 节点类型 | 说明 |
|---|---|
| `AtomicStage` | 单个 Stage，由 Runner 驱动执行 |
| `SequentialGroup` | 顺序执行子节点，支持 scope 内 corrective/escalation 路由 |
| `ForkJoinGroup` | 并行 fork 多个子节点，join 时合并各子状态（冲突检测） |
| `SideTask` | fire-and-forget 旁路任务，对主遍历透明，return 前 join |

### 内置 Workflow

| 名称 | 说明 |
|---|---|
| `generate_ascendc` | 完整 9-Stage 管线（默认） |
| `generate_ascendc_se` | SE 管线：requirement → 概要设计 → 交付物 |
| `generate_ascendc_dev` | Dev 管线：详细设计 → codegen → verify → perf → integrate → 交付 |
| `full_test` | Graph-native：通过 ForkJoinGroup 并行测试套件 |

## 快速开始

### 环境要求

- Python >= 3.11
- CANN (Ascend 算子编译环境)
- NPU 设备 (Ascend 910B/910D)
- Claude Code CLI (`claude`)
- 系统需存在 `/lib64/libc.so.6`（BISHENG 链接器 `ld.lld` 硬依赖）。部分机器（如缺 `/lib64` 的
  Ubuntu 22.04 aarch64）会导致 cannbench_eval 性能打分阶段的 `cann_bench_utils` 编不出 `_C.so`
  （表象为误导性的 `ImportError: ... circular import`）。缺失时执行
  `sudo ln -sfn /usr/lib64/libc.so.6 /lib64/libc.so.6`。
  详见 [docs/plan/self-evolution/83-cannbench-eval-env-gotchas.md](docs/plan/self-evolution/83-cannbench-eval-env-gotchas.md)。

### 安装

```bash
pip install -e .
```

### 基本用法

```bash
# 环境检查
ascendc-devkit verify-env
ascendc-devkit verify-repo --repo-profile omni-ops

# 新算子生成（完整 Pipeline）
ascendc-devkit run \
  --target-repo /path/to/omni-ops \
  --repo-profile omni-ops \
  --op-name gelu \
  --non-interactive \
  --max-iterations 5

# 增量开发
ascendc-devkit run \
  --target-repo /path/to/omni-ops \
  --repo-profile omni-ops \
  --op-name gelu \
  --mode incremental \
  --non-interactive

# 指定 Workflow（默认 generate_ascendc）
ascendc-devkit run --workflow full_test --target-repo /path/to/omni-ops ...

# 单 Stage 运行
ascendc-devkit stage run codegen \
  --state state.json \
  --non-interactive

# 中断恢复
ascendc-devkit run --resume <run-id>

# 查看运行事件
ascendc-devkit show --run <run-id>
ascendc-devkit show --run <run-id> --tail

# 异步决策响应
ascendc-devkit respond --run <run-id> --choice 1

# Agent 调试
ascendc-devkit debug-agent --run <run-id> --agent-name ascendc-coder

# Skill 管理
ascendc-devkit skill list
ascendc-devkit skill validate <skill-name>
```

### 高级选项

```bash
# TUI 实时进度
ascendc-devkit run --tui ...

# 超时控制
ascendc-devkit run --workflow-timeout 600 --stage-timeout 120 ...

# 迭代恢复
ascendc-devkit run --resume <run-id> --resume-iteration 3

# Stub 模式（无 CANN/NPU 环境时允许降级）
ascendc-devkit run --enable-stubbed ...

# 非交互决策策略
ascendc-devkit run --non-interactive --on-decision default  # 自动选默认
ascendc-devkit run --non-interactive --on-decision abort    # 挂起等待 respond

# Webhook 通知
ascendc-devkit run --webhook-url https://hooks.example.com/notify ...
```

## 项目结构

```
src/ascendc_devkit/
├── cli/                  # L1 Presentation (Click CLI + Rich TUI)
│   ├── main.py
│   ├── tui.py            # 4-Panel TUI (进度/指标/事件流/Agent输出)
│   └── commands/         # run, stage, verify-env, verify-repo, show, respond, skill, debug-agent
├── application/          # L2 Application
│   ├── dispatcher.py     # dispatch() + dispatch_single_stage() + dispatch_single_skill()
│   ├── report.py         # Report.generate()
│   └── skill_service.py
├── orchestration/        # L3 Orchestration
│   ├── kernel/           # State, Action, Event, Gate, Runner
│   ├── stages/           # Stage 实现 (9-Stage + smoke / build_and_verify)
│   ├── graph_executor.py # GraphExecutor — StageNode 树遍历 + scoped 路由
│   ├── node.py           # StageNode / AtomicStage / SequentialGroup
│   ├── node_forkjoin.py  # ForkJoinGroup — 并行 fork/join + 状态合并
│   ├── node_sidetask.py  # SideTask — fire-and-forget 旁路任务
│   ├── exec_context.py   # 执行上下文
│   ├── model_config.py   # 模型配置
│   ├── base.py           # StageProtocol, Stage, CompositeStage
│   ├── registry.py       # Stage + Workflow 注册中心
│   └── workflow.py       # Workflow 声明式编排 (4 内置 workflow)
├── domain/               # L4 Domain (纯数据, 零依赖)
├── capabilities/         # L5 Agent/Skill/Knowledge
├── adapters/             # L6 Repository/NPU/LLM/Toolchain
│   ├── repository/       # RepositoryAdapter(ABC) + GenericRepositoryAdapter
│   ├── npu/              # NPURunner + NPUSlotManager
│   ├── toolchain/        # CANNToolchain + PTAToolchain
│   └── llm/              # LLMProvider(ABC) + Anthropic/Bedrock/Vertex
└── infra/                # L7 Workspace/EventLog/Logger/FS
```

## 测试

测试默认走"全量真实环境模式"：跑 UT + ST 全部，并预检 LLM/NPU/CANN。任一缺失时报错并列出缺失项，由用户决定是否继续（非交互/CI 默认中止），绝不静默打桩。开发内环用 `--quick` 排除 `llm`/`slow`/`npu`/`cann` 并跳过预检。

```bash
# 默认全量真实环境 — UT + ST 全部，预检 LLM/NPU/CANN，缺失则询问/中止
python -m pytest

# 快速开发模式 — 排除 llm/slow/npu/cann，跳过预检，秒级反馈
python -m pytest --quick

# 仅单元测试（天然无依赖、不预检）/ 仅系统测试
python -m pytest --ut
python -m pytest --st

# 标记筛选
python -m pytest --st -m llm
python -m pytest --st -m npu
python -m pytest --st -m cann

# 跳过环境预检（自担风险，相关用例可能失败）
python -m pytest --no-env-check
```

详细测试约定见 `tests/README.md`。

## 设计文档

详见 `docs/` 目录：

| 文件 | 内容 |
|------|------|
| `architecture-overview.md` | 架构总览 |
| `layers/L1-L7-*.md` | 7 层详细设计 |
| `stages/*.md` | 9 Stage 详细设计 |
| `test-map.md` | 测试用例地图 |
