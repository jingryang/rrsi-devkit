# L2 Application — 用例编排

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §2 分层架构
> **上游依赖**：L1 Presentation
> **下游依赖**：L3 Orchestration, L4 Domain, L7 Infrastructure
> **实现状态（graph 重构后）**：`application/dispatcher.py` (dispatch + dispatch_single_stage + dispatch_single_skill, 委托 GraphExecutor 遍历 workflow.root, 薄 dispatch loop, progress_callback, WorkflowTimeoutError/StageTimeoutError 处理, resume_iteration + node_status frontier 恢复) ✓ | `application/report.py` (Report.generate/write_markdown/write_json) ✓ | `application/profile_loader.py` ✓ | `application/skill_service.py` (L2 skill 薄封装, → L3 orchestration/skill 委托) ✓

---

## 1. 定位

把用户的 TaskRequest 翻译成一次完整的运行。L2 不操作状态机（那是 L3 的事），不解析命令行（那是 L1 的事），它做的事是**串联**：选 workflow、绑 profile、驱动 runner、生成报告。

```
L1 传入 TaskRequest
        │
        ▼
┌──────────────────────────────────────────────┐
│ L2 application/dispatcher.py                 │
│                                              │
│  1. 解析意图                                 │
│     workflow = WORKFLOW_REGISTRY[req.kind]   │
│                                              │
│  2. 绑定 RepositoryProfile                   │
│     profile = ProfileLoader.load(req.repo)   │
│     adapter = RepositoryAdapter.from_profile │
│                                              │
│  3. 构造初始 State                           │
│     state = InitialState(                    │
│       mode=req.mode,                         │
│       op=req.op_spec,                        │
│       profile=profile,                       │
│       workspace=Workspace.create()           │
│     )                                        │
│                                              │
│  4. 启动 runner                              │
│     runner = Runner(workflow, adapter)       │
│     final_state = runner.run(state)          │
│                                              │
│  5. 生成报告                                 │
│     report = Report.from_events(             │
│       workspace.events_path                  │
│     )                                        │
│     return report, final_state.exit_code     │
└──────────────────────────────────────────────┘
```

---

## 2. 职责

| 模块 | 职责 |
|---|---|
| `application/task_request.py` | `TaskRequest` schema 定义（import L4 类型） |
| `application/dispatcher.py` | 解析意图 → 选 workflow → 绑 profile → 构造初始 State → 启动 runner |
| `application/report.py` | 读取 `events.jsonl`，生成 `report.md` + `report.json` |
| `application/profile_loader.py` | 加载 `repository-profiles/<name>.yaml`，构造 `RepositoryProfile` |
| `application/skill_service.py` | L2 skill 薄封装，委托 L3 `orchestration/skill`，供 L1 CLI 消费 |

---

## 3. 核心抽象

### 3.1 TaskRequest（L1→L2 契约）

```python
@dataclass(frozen=True)
class TaskRequest:
    """用户请求的不可变表示。L1 构造，L2 消费。"""
    mode: str                   # "new" | "incremental"
    workflow: str               # "generate_ascendc" | "incremental_dev" | ...
    target_repo: Path           # 目标代码仓本地路径
    repo_profile: str           # 仓画像名称
    op_name: str | None         # 增量模式必填
    requirement_path: Path | None
    change_doc_path: Path | None
    non_interactive: bool
    max_iterations: int | None
    on_decision: str | None
    npu_id: int | None
    resume_run_id: str | None
    notify_webhook: str | None
    notify_channels: str | None
```

### 3.2 InitialState（L2→L3 契约）

```python
@dataclass(frozen=True)
class InitialState:
    """L2 构造，传给 L3 runner 的初始状态。"""
    mode: str
    workflow_name: str
    op_spec: OperatorSpec | None       # 新生成模式：从需求文档解析
    op_identity: OperatorIdentity | None  # 增量模式：从目标仓扫描
    profile: RepositoryProfile
    adapter: RepositoryAdapter
    workspace: Workspace
    non_interactive: bool
    max_iterations: int
    on_decision: str
    npu_id: int
```

### 3.3 Dispatcher

```python
# application/dispatcher.py

def dispatch(task_request: TaskRequest) -> int:
    """L1 的唯一入口。返回退出码。"""
    # 1. 参数校验
    _validate(task_request)

    # 2. 选择 workflow
    workflow = WORKFLOW_REGISTRY[task_request.workflow]

    # 3. 加载 profile + 构造 adapter
    profile = ProfileLoader.load(task_request.repo_profile)
    adapter = RepositoryAdapter.from_profile(profile)

    # 4. 构造初始 state
    state = _build_initial_state(task_request, profile, adapter)

    # 5. 创建 runner，委托 GraphExecutor 遍历 StageNode 树执行
    runner = Runner(adapter=adapter, progress_callback=progress_callback)
    executor = GraphExecutor(runner, event_log=event_log,
                             route_decision_handler=..., progress_callback=...)
    final_state = executor.execute(workflow.root, state)

    # 6. 生成报告
    report = Report.generate(state.workspace)
    report.write(state.workspace.report_path)

    return _map_to_exit_code(final_state)


def _validate(req: TaskRequest) -> None:
    """参数组合校验。失败抛 ValueError → L1 映射退出码 64。"""
    if req.mode == "incremental" and not req.op_name:
        raise ValueError("增量模式必须指定 --op-name")
    if req.non_interactive and req.on_decision not in ("abort", "default"):
        raise ValueError("--on-decision 必须是 abort 或 default")
```

---

## 4. Report 生成

```python
# application/report.py

class Report:
    """从 events.jsonl 生成人类可读 + 机器可读报告。"""

    @staticmethod
    def generate(workspace: Workspace) -> Report:
        events = EventLog.read(workspace.events_path)
        return Report(
            run_id=workspace.run_id,
            workflow=_extract_workflow(events),
            stages=_summarize_stages(events),
            total_elapsed=_compute_total_elapsed(events),
            exit_code=_derive_exit_code(events),
            errors=_collect_errors(events),
        )

    def write_markdown(self, path: Path) -> None: ...
    def write_json(self, path: Path) -> None: ...
```

---

## 5. 错误处理

| 场景 | 处理方式 | 退出码 |
|---|---|---|
| 无效 workflow 名称 | `ValueError` → 退出码 64 | 64 |
| profile 文件不存在 | `FileNotFoundError` → 退出码 78 | 78 |
| 增量模式缺少 op_name | `ValueError` → 退出码 64 | 64 |
| resume_run_id 对应 events 损坏 | `DataError` → 退出码 65 | 65 |
| Runner 返回 Fatal | 穿透 Runner 的退出码 | 对应错误码 |

---

## 6. 扩展点

| 扩展类型 | 方式 |
|---|---|
| 新增 workflow | `WORKFLOW_REGISTRY` 加一条条目，不改 dispatcher |
| 新增 report 格式 | `Report` 加 `write_<format>()` 方法 |
| 新增 profile 校验规则 | `_validate` 加检查逻辑 |

---

## 7. Stage 独立运行

Stage 独立运行是 StageProtocol IO 契约隔离的直接应用。Runner 不区分自己在跑 1 个 Stage 还是 9 个 Stage 的 Workflow——一切可组合单元都是 StageProtocol。

### 7.1 StageRequest（L1→L2 契约）

```python
@dataclass(frozen=True)
class StageRequest:
    """单个 Stage 独立运行请求。L1 构造，L2 消费。"""
    stage_name: str              # "codegen" | "verify" | "perf" | ...

    # State 注入源（三选一或组合，见 §7.2）
    from_run_id: str | None      # 从 workspace 提取基础 State
    state_file: Path | None      # 显式 State JSON 路径
    cli_overrides: CliOverrides  # CLI 标志直接映射

    max_iterations: int | None
    non_interactive: bool = False

@dataclass(frozen=True)
class CliOverrides:
    """CLI 显式标志 → State 字段映射。每个字段为 None 表示未通过 CLI 指定。"""
    sources_dir: Path | None        # → generated_sources
    requirement_file: Path | None   # → requirement
    build_artifacts_dir: Path | None # → build_result
    npu_id: int | None              # → npu_id
    chip_version: str | None        # → chip_version
    skip_precision: bool = False    # → 标记跳过精度 gate
```

### 7.2 State 构造：三层合并

State 构造是 Stage 独立运行的核心逻辑。三种来源按优先级逐层覆盖：

```
Layer 3 (最高)  CLI 显式标志    --sources / --requirement / --npu-id / ...
Layer 2          state_file      --state <file>
Layer 1 (基础)   from_run_id     --from-run <id>
```

```python
# application/dispatcher.py

def dispatch_single_stage(req: StageRequest) -> int:
    """单独运行一个 Stage。返回退出码。"""
    # 1. 从 StageRegistry 查找 Stage 类
    stage_cls = STAGE_REGISTRY[req.stage_name]
    stage = stage_cls()

    # 2. 三层合并构造 State
    state = _build_state_for_stage(req, stage)

    # 3. IO 契约校验
    _validate_state_fulfills_contract(state, stage.input_contract())

    # 4. 构造最小 Workflow + 执行
    workflow = Workflow(name=f"standalone/{req.stage_name}", stages=[stage_cls])
    runner = Runner(workflow=workflow)
    final_state = runner.run(state)

    # 5. 写 state snapshot
    _write_state_snapshot(final_state)
    return _map_to_exit_code(final_state)


def _build_state_for_stage(req: StageRequest, stage: Stage) -> State:
    """三层合并构造 State。"""
    # Layer 1: from_run_id 为基础
    if req.from_run_id:
        state = _load_state_from_run(req.from_run_id)
    else:
        state = State.empty()  # 所有字段为 None 的初始 State

    # Layer 2: state_file 覆盖
    if req.state_file:
        file_state = State.from_json(req.state_file.read_text())
        state = state.merge(file_state)  # 非 None 字段覆盖

    # Layer 3: CLI 显式标志覆盖（最高优先级）
    overrides = req.cli_overrides
    if overrides.sources_dir:
        state = state.with_field(
            "generated_sources",
            _read_sources_dir(overrides.sources_dir)
        )
    if overrides.requirement_file:
        state = state.with_field(
            "requirement",
            Requirement.from_file(overrides.requirement_file)
        )
    if overrides.build_artifacts_dir:
        state = state.with_field(
            "build_result",
            BuildResult.from_artifacts_dir(overrides.build_artifacts_dir)
        )
    if overrides.npu_id is not None:
        state = state.with_field("npu_id", overrides.npu_id)
    if overrides.chip_version is not None:
        state = state.with_field("chip_version", overrides.chip_version)
    if overrides.skip_precision:
        state = state.with_field("skip_precision", True)

    return state


def _read_sources_dir(dir: Path) -> dict[str, str]:
    """读取目录下所有源码文件，返回 {相对路径: 文件内容}。"""
    sources = {}
    for f in dir.rglob("*"):
        if f.suffix in (".cpp", ".h", ".hpp", ".py"):
            sources[str(f.relative_to(dir))] = f.read_text()
    return sources
```

**关键设计点**：
- `State.merge()` 只覆盖非 None 字段——不会用 state_file 中的 null 值抹掉 from_run 的有效数据
- `State.with_field()` 是覆盖写入（无论原值是否为 None）
- `_read_sources_dir()` 只收集源码文件，不包含二进制或构建产物
- 合并后的 State 是新的不可变实例（frozen dataclass），不修改任何输入

### 7.3 CLI 标志组合的实际效果

以 verify stage（`input_contract().requires = ["adapter", "op_identity", "requirement", "npu_id"]`）为例：

**场景 A：指定算子仓内算子，第一次验证**
```bash
ascendc-devkit stage run --name verify \
    --target-repo ./omni-ops --repo-profile omni-ops --op-name gelu \
    --requirement ./test_cases.yaml \
    --npu-id 0
```
→ `_build_state_for_stage`：Layer 3 填充仓信息与 npu_id；context 构造 `adapter`/`op_identity`，verify 调 `adapter.build` 编译 op_dir → 满足 contract ✓

**场景 B：Pipeline 跑到 verify 失败，仓内修复代码后重跑**
```bash
ascendc-devkit stage run --name verify --from-run abc123
```
→ Layer 1 从 `output/abc123/state_snapshot.json` 加载完整 State（含 `adapter`、`op_identity`、`requirement` 等），代码已在算子仓 op_dir 内 → 满足 contract ✓

**场景 C：从 run 取基础，但换了张 NPU 卡**
```bash
ascendc-devkit stage run --name verify --from-run abc123 --npu-id 2
```
→ Layer 1 加载 run state，Layer 3 覆盖 `npu_id=2` → 满足 contract ✓

**场景 D：只跑编译，不跑精度（手写代码快速检查编译）**
```bash
ascendc-devkit stage run --name verify \
    --sources ./my_gelu/ \
    --requirement ./test_cases.yaml \
    --npu-id 0 \
    --skip-precision
```
→ State 中 `skip_precision=True`，verify stage 在 `actions()` 中检查此标志，跳过 PrecisionGate → 只跑 BuildGate

### 7.4 State Snapshot 自动落盘

Runner 在每个 Stage 完成后自动将 `final_state` 写入 `output/<run_id>/state_snapshot.json`。

- Stage 独立运行时自动分配新的 `run_id`（格式：`standalone/<stage_name>/<timestamp>`）
- `--from-run <id>` 始终读取该 run 最后一个 Stage 完成后的完整 State 快照
- State 快照包含所有历史 Stage 的累积字段，不只是最后一个 Stage 的 output

---

## 8. Skill 直接调用

Skill 本质是 L5 注册的独立能力单元。Agent 通过 SDK 的 Skill 工具调用它，但 Skill 本身不依赖 Agent——它的输入输出是纯数据，可以从 CLI 直接驱动。

### 8.1 SkillRequest（L1→L2 契约）

```python
@dataclass(frozen=True)
class SkillRequest:
    """单个 Skill 直接调用请求。L1 构造，L2 消费。"""
    skill_name: str              # "ascendc-profiling" | "ascendc-code-review" | ...
    input_data: dict             # skill 的输入参数（JSON）
    context_dir: Path | None     # 附加上下文目录（kernel 文件、日志等）
    output_file: Path | None     # 结果输出路径（默认 stdout）
```

### 8.2 Dispatch

```python
# application/dispatcher.py

def dispatch_single_skill(req: SkillRequest) -> int:
    """直接调用一个 Skill，绕过 Stage/Agent。"""
    # 1. 从 SkillRegistry 查找 Skill
    skill = SkillRegistry.lookup(req.skill_name)
    if not skill:
        raise ValueError(f"Unknown skill: {req.skill_name}")

    # 2. 校验输入 schema（如果 SKILL.md frontmatter 声明了 input_schema）
    if skill.input_schema:
        _validate_skill_input(req.input_data, skill.input_schema)

    # 3. 构造最小 Agent session——Skill 需要 Agent 作为执行宿主
    backend = AgentBackend.create(stub_mode=False)
    result = backend.execute_skill(
        skill=skill,
        input_data=req.input_data,
        context_dir=req.context_dir,
    )

    # 4. 输出结果
    if req.output_file:
        req.output_file.write_text(json.dumps(result, indent=2))
    else:
        print(json.dumps(result, indent=2))

    return 0 if result.status == "ok" else 1
```

### 8.3 Skill 输入 Schema 声明

每个 Skill 的 `SKILL.md` frontmatter 可选声明 `input_schema`——描述该 skill 作为独立工具时的输入参数：

```yaml
# runtime/claude_resources/skills/ascendc-profiling/SKILL.md
---
name: ascendc-profiling
description: AscendC 算子性能分析
input_schema:
  type: object
  required: [kernel_path, npu_id]
  properties:
    kernel_path: {type: string, description: "编译后的 kernel 文件路径"}
    npu_id: {type: integer, description: "NPU 卡号"}
    shapes: {type: array, description: "要测试的 shape 列表"}
    baseline: {type: object, description: "性能基线（可选）"}
---
```

L2 的 `_validate_skill_input` 据此做基本类型校验，不满足时退出码 64。

### 8.4 与 Agent 内调用的关系

```
Agent 内调用                              CLI 直接调用
───────────                              ────────────
Agent 读取 prompt                        用户输入 CLI 参数
  ↓                                       ↓
Agent 决定调用 Skill                     L2 直接查找 Skill
  ↓                                       ↓
SDK Skill 工具执行                       AgentBackend.execute_skill()
  ↓                                       ↓
结果返回 Agent                          结果输出到 stdout/文件
  ↓
Agent 根据结果决策下一步
```

两条路径在 L5 的 `SkillDispatcher` 汇合——Skill 的执行逻辑完全一致，区别只在上层调度方。

---

## 9. 与邻层的关系

| 方向 | 层 | 关系 |
|---|---|---|
| 向上 | L1 Presentation | 接收 `TaskRequest` / `StageRequest` / `SkillRequest`，返回退出码 |
| 向下 | L3 Orchestration | 选择 workflow、构造初始 State、启动 runner（含单 Stage workflow） |
| 向下 | L4 Domain | import `TaskRequest`、`StageRequest`、`SkillRequest`、`RepositoryProfile`、`OperatorSpec` 等类型 |
| 向下 | L5 Capabilities | 通过 `SkillRegistry.lookup()` + `AgentBackend.execute_skill()` 直接调度 Skill |
| 向下 | L6 Adapters | 通过 `RepositoryAdapter.from_profile()` 获取 adapter 实例 |
| 向下 | L7 Infrastructure | 通过 `Workspace.create()` 创建运行的事件/报告/备份目录 |
