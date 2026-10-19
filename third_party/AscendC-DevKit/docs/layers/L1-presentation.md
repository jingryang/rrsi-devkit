# L1 Presentation — 入口适配

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §2 分层架构
> **下游依赖**：L2 Application, L4 Domain
> **实现状态**：`cli/main.py` ✓ | `cli/tui.py` (4-Panel Rich TUI: 进度/指标/事件流/Agent 输出) ✓ | `cli/exit_codes.py` (含 EX_TIMEOUT=124) ✓ | `cli/commands/stage.py` (stage run) ✓ | `cli/commands/run.py` (完整 Pipeline + --resume + --workflow-timeout/--stage-timeout/--resume-iteration) ✓ | `cli/commands/verify_env.py` (真实环境检查) ✓ | `cli/commands/verify_repo.py` (真实仓校验) ✓ | `cli/commands/show.py` (事件回放 + --tail) ✓ | `cli/commands/respond.py` (异步决策响应) ✓ | `cli/commands/skill.py` (skill list/validate, 经 L2→L3→L5) ✓ | `cli/commands/debug_agent.py` (agent 交互式调试) ✓

---

## 1. 定位

最薄的一层。只做一件事：**把用户输入翻译成 `TaskRequest`**。

```
用户输入                         L1 输出
────────────────────────────────────────────
CLI args              ──→
TUI 按键               ──→   TaskRequest
CI 环境变量 + args     ──→
Slash command 文本     ──→
```

L1 不做任何业务决策——不判断参数组合是否合法（那是 L2 的职责），不选择 workflow（L2 做），不加载 profile（L2 做）。它只做翻译：用户输入 → TaskRequest。

---

## 2. 职责

| 模块 | 职责 |
|---|---|
| `cli/main.py` | 解析 sys.argv，构造 TaskRequest，调用 L2，映射退出码 |
| `cli/exit_codes.py` | 退出码常量定义 |
| `cli/commands/run.py` | `run` 子命令的参数解析与校验 |
| `cli/commands/stage.py` | `stage run` 子命令：单 Stage 独立运行 |
| `cli/commands/skill.py` | `skill` 子命令：skill 发现与管理 (list/validate, 经 L2→L3→L5) |
| `cli/commands/verify_env.py` | `verify-env` 子命令（CANN/Python/torch_npu/NPU Driver/Device 真实检查） |
| `cli/commands/verify_repo.py` | `verify-repo` 子命令（YAML profile 加载 + 目录校验） |
| `cli/commands/show.py` | `show` 子命令（事件回放 + --tail 实时跟踪） |
| `cli/commands/respond.py` | `respond` 子命令（异步决策响应） |
| `cli/commands/debug_agent.py` | `debug-agent` 子命令（Agent 交互式调试） |

---

## 3. CLI 命令树

### 3.1 命令速查

| 命令 | 用途 | 关键参数 |
|---|---|---|
| `ascendc-devkit run` | 跑单个 workflow | `--workflow` / `--mode` / `--target-repo` / `--repo-profile` / `--npu-id` / `--non-interactive [--max-iterations N] [--on-decision ...]` / `--resume` |
| `ascendc-devkit verify-env` | 验证开发环境 | `--target {local,ssh,docker}` — 检查 CANN Toolkit / Python / torch_npu / NPU Driver / NPU Device |
| `ascendc-devkit verify-repo` | 校验仓 profile | `--profile` / `--repo-root` — 读取 YAML profile + 校验目录结构 |
| `ascendc-devkit list-npus` | 列出 NPU 卡状态 | `--format {table,json}` |
| `ascendc-devkit show` | 回放事件流 | `--run <id>` / `--stage N` / `--tail` |
| `ascendc-devkit respond` | 异步响应决策点 | `--run <id>` / `--choice N` |
| `ascendc-devkit stage run` | 单独跑一个 Stage | `--name <stage>` / `--from-run <id>` / `--state <file>` / `--npu-id` |
| `ascendc-devkit skill list` | 列出可用 skill | 显示 name + description（经 L2→L3→L5） |
| `ascendc-devkit skill validate` | 校验 skill 名称 | 返回不存在的 skill 列表 |
| `ascendc-devkit debug-agent` | Agent 交互式调试 | `--run <id>` / `--stage <name>` — 提取 Agent prompt+skills, 启动 `claude` CLI 交互会话 |

`[--max-iterations N]` 和 `[--on-decision ...]` 仅在 `--non-interactive` 下生效；交互模式下这些参数被忽略。

### 3.2 TaskRequest 构造

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

### 3.3 NPU 卡分配

四种方式，优先级从高到低：

```
--npu-id  >  --npu-auto (flock)  >  ASCEND_RT_VISIBLE_DEVICES  >  settings.json  >  默认(0)
```

| 方式 | 用法 | 适用场景 |
|---|---|---|
| CLI 参数 | `--npu-id 2` | 调度器有完整控制权 |
| 环境变量 | `ASCEND_RT_VISIBLE_DEVICES=2` | 容器编排 |
| 自动选择 | `--npu-auto --lock-dir /var/lock/ascendc-devkit/` | 谁先空闲谁跑 |
| 配置文件 | `.lingxi/settings.json` 的 `npu_id` | 开发期固定卡 |

### 3.4 脚本化契约

| 契约项 | 要求 |
|---|---|
| 非交互模式 | `--non-interactive` 下绝不阻塞 stdin，所有决策走自动策略 |
| 非交互模式子参数 | `--max-iterations N` 和 `--on-decision {abort,default}` 仅在 `--non-interactive` 下生效 |
| 明确退出码 | 严格语义（见 §4），外层脚本 grep `$?` 即知结果 |
| 结构化产物 | `output/<run_id>/report.json` 机器可读 |
| workspace 隔离 | 不同 `run_id` 完全独立，多进程并行不冲突 |
| 退出前清理 | NPU 锁、临时文件、子进程一律清理 |

### 3.5 外部调度参考模式

| 场景 | 推荐方式 |
|---|---|
| 本机 ≤ 8 张卡，临时跑几个 | GNU parallel |
| 本机 N 张卡，需要灵活控制 | Shell 显式 slot 分配 |
| CI 集成 | Makefile `-j` 并行 |
| 算子数远多于卡数 | Auto-NPU + 信号量队列 |
| 跨主机、生产环境 | K8s Job + device plugin |
| NPU 在远端独立机器 | SSH 池 |

没有 `ascendc-devkit batch`。批量场景走外层脚本。

### 3.6 Stage/Skill 独立运行

除了跑完整 workflow，平台支持将单个 Stage 或 Skill 拆出来独立执行。这是 StageProtocol IO 契约隔离 + L5 Skill 独立注册的自然延伸——不是新架构能力，而是已有组合性的反向使用。

#### 3.6.1 Stage 独立运行

Stage 独立运行需要满足该 Stage `input_contract().requires` 中声明的所有必需字段。参数传入有三种来源，按优先级从高到低：

```
CLI 显式标志  >  --state <file>  >  --from-run <id>
    (最高)          (中等)            (基础)
```

**来源一：`--from-run <run_id>`（从历史 run 注入）**

L2 读取 `output/<run_id>/state_snapshot.json`（Runner 在每个 Stage 完成后自动写入），将其中的 State 字段作为基础值。适用于"pipeline 跑到一半失败了，修完后重跑当前 stage"的场景。

```bash
ascendc-devkit stage run --name codegen --from-run <run_id>
```

**来源二：`--state <file>`（显式 State JSON）**

用户提供一个完整的 State JSON 文件。适用于需要精确控制 State 每个字段的场景，或从外部系统集成。

```bash
ascendc-devkit stage run --name verify --state ./my_state.json
```

**来源三：CLI 显式标志（最高优先级）**

以上两种方式都要求用户理解 State 数据结构。对于常见场景——特别是"代码是我手写的，不是 pipeline 生成的"——平台提供按语义命名的 CLI 标志，L2 自动映射到 State 字段：

```bash
# 手写代码，直接验证编译+精度
ascendc-devkit stage run --name verify \
    --sources ./my_kernel/ \
    --requirement ./test_cases.yaml \
    --npu-id 0

# 已有编译产物，跑性能基准
ascendc-devkit stage run --name perf \
    --build-artifacts ./build/ \
    --sources ./my_kernel/ \
    --requirement ./perf_baseline.yaml \
    --npu-id 0

# 只跑编译（不需要测试用例）
ascendc-devkit stage run --name verify \
    --sources ./my_kernel/ \
    --npu-id 0 \
    --skip-precision
```

**CLI 标志 → State 字段映射表**：

| CLI 标志 | 映射的 State 字段 | 适用 Stage |
|---|---|---|
| `--sources <dir>` | `generated_sources: dict[str, str]` — 读取目录下所有 `.cpp/.h/.py` 文件 | verify, perf, integrate |
| `--requirement <file>` | `requirement: Requirement` — 从 YAML/JSON 解析测试用例 + 约束 | verify, perf, codegen |
| `--build-artifacts <dir>` | `build_result: BuildResult` — 已有的 `.o` 编译产物 | perf |
| `--npu-id <N>` | `npu_id: int` | verify, perf |
| `--chip-version <str>` | `chip_version: str` | verify, perf |
| `--skip-precision` | 标记跳过精度验证（verify stage 只跑编译 gate） | verify |

**合并规则**：三种来源可以混合使用。最终 State 按优先级逐层覆盖——先加载 `--from-run` 的基础 State，再用 `--state <file>` 中的字段覆盖，最后用 CLI 显式标志覆盖。任何覆盖后仍为 None 的 `input_contract().requires` 字段都会导致启动前报错。

**典型场景**：

| 场景 | 命令 | State 来源 |
|---|---|---|
| 调试失败 stage | `stage run --name codegen --from-run <id>` | 历史 run 的 state_snapshot |
| 手写代码验证 | `stage run --name verify --sources ./src/ --requirement ./tc.yaml --npu-id 0` | CLI 标志 |
| 精确控制 | `stage run --name codegen --state ./state.json` | 手工 State JSON |
| 从中间接手 | `stage run --name perf --from-run <id> --npu-id 1` | 基础来自历史 run，npu_id 覆盖为 1 |
| 只编译不测 | `stage run --name verify --sources ./src/ --npu-id 0 --skip-precision` | CLI 标志，跳过精度 gate |

#### 3.6.2 Skill 直接调用

Skill 本来是 Agent 的工具，但也可以绕过 Stage/Agent 直接从 CLI 调用——适合 ad-hoc 分析和人工辅助场景。

```bash
# 对已有 kernel 二进制跑性能分析
ascendc-devkit skill run --name ascendc-profiling \
    --input '{"kernel_path": "/path/to/kernel.o", "npu_id": 0}'

# 对代码做 code review
ascendc-devkit skill run --name ascendc-code-review \
    --input '{"sources": {"gelu_tiling.h": "...", "gelu_kernel.cpp": "..."}}'

# 调用 tiling strategy 分析
ascendc-devkit skill run --name ascendc-tiling-strategy \
    --input '{"op_type": "gelu", "shape": [1024, 2048], "dtype": "float16"}'
```

`--input` 接受 JSON 文件路径或 JSON 字符串。Skill 的输入 schema 由 SKILL.md frontmatter 的 `input_schema` 字段声明，L1 做基本类型校验后交给 L2。

**与 Agent 调用的区别**：

| 维度 | Agent 内调用 | CLI 直接调用 |
|---|---|---|
| 触发方 | Agent 在 prompt 中决定调用 | 用户显式指定 |
| 上下文 | Agent 持有完整对话上下文 | 只有 `--input` 提供的数据 |
| 迭代 | Agent 可根据结果修改策略 | 单次调用，无迭代 |
| 产物 | 写入 Agent transcript | stdout + 可选 `--output <file>` |

#### 3.6.3 对架构的影响

**零冲击**。Stage 独立运行复用 `StageProtocol` → `Runner.run()` 路径——Runner 不区分自己在跑 1 个 Stage 还是 9 个 Stage 的 Workflow。Skill 直接调用复用 L5 的 `SkillRegistry` + `SkillDispatcher`——只是调用方从 Agent 变为 L2。

唯一新增的是 L1/L2 的两组 CLI 入口 + State 注入机制。L3-L7 无改动。

---

## 4. 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 一般错误 |
| 64 | 参数错误 |
| 65 | 输入数据错误 |
| 78 | 环境配置错误 |
| 75 | 瞬时错误 |
| 130 | SIGINT（优雅停止） |
| 137 | SIGKILL（强制退出） |

---

## 5. 三层反馈机制

不同粒度的事件用不同的反馈通道：

```
Layer 1 — Stage 层（粗粒度）
  ━━━━ [codegen] Codegen ━━━━━━━━━━━ 03:42 elapsed
  ━━━━ ✓ codegen done (02:13)

Layer 2 — Action 层（中粒度）
  • spawn_agent ascendc-coder ... [running 00:45]
  • run_gate precision ... ✓ PASS (12s)

Layer 3 — Heartbeat 层（细粒度 / 时间触发）
  ⠋ ascendc-coder thinking... (45s, tokens=1832)
  ⠹ compiling kernel ... 32%
```

Heartbeat 不进 `events.jsonl`，只走 stdout。

---

## 6. 流式输出

| 子系统 | 流式策略 |
|---|---|
| LLM Agent | SDK streaming token 转发到 stdout（带 agent 标识前缀） |
| 编译输出 | `subprocess.Popen` + 实时 readline，按 INFO/WARN/ERROR 着色 |
| 精度验证 | 每跑完一个用例输出一行 |
| 性能基准 | 每跑完一个 shape 输出一行 |

---

## 7. 纯 CLI 的可视性边界

### 7.1 CLI 能做到的

**前缀分流**：每个子系统输出带固定前缀，配合 `grep` 可在另一个终端按子系统过滤。

```
[ascendc-coder] 生成 op_host/gelu_tiling.h ...
[compile]       [WARN] implicit cast at gelu_tiling.cpp:42
[verify]        case 1/10 PASS  diff=1.2e-6
```

**Heartbeat 防止静默**：长 Action（Agent 调用 >10s、编译 >30s）内定时输出心跳。

```
⠋ ascendc-coder thinking... (45s, tokens=1832)
⠹ compiling kernel ... 32%
```

**AskUserQuestion 在 CLI 中的呈现**：格式化阻塞 prompt——清晰列出选项，等待键盘输入。

```
━━ ⚠ 需要你的决策 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Stage: requirement
  问题: shape 不能被 tile_size 整除时如何处理？

  [1] 添加 tail block 处理
      → 在最后一个 block 使用 mask 处理不对齐部分

  [2] 假设 shape 总是对齐
      → 不处理 tail block，调用方保证对齐

  [3] 跳过此问题，继续下一步
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
请选择 [1-3] (默认 1):
```

**日志兜底**：所有子系统的完整输出都落盘——Agent transcript、编译/验证 stdout/stderr、结构化事件流。CLI 上漏看的，事后都能查。

### 7.2 CLI 的局限与妥协

| 场景 | CLI 的局限 | 妥协方案 |
|---|---|---|
| 同时监控 pipeline 进度 + Agent 输出 + 编译日志 | 线形输出，信息流交织滚动 | 前缀分流 + `grep` 过滤 + 另一个终端 tail 日志 |
| 快速定位历史编译错误 | 需要往上翻，没有搜索面板 | 日志文件在 `subprocess/` 下，用 `grep` / `less` 检索 |
| 看 pipeline 整体进度和耗时分布 | 只能看到当前 Stage | `ascendc-devkit show --run <id>` 回放事件流 |
| 多个 task 并行跑时监控全局 | 每个 task 一个终端 | 外层调度器聚合 `events.jsonl` |

---

## 8. TUI（可选扩展）

TUI 是可选扩展，非必做。它解决的不是"能不能用"的问题，是"好不好用"的问题。

### 8.1 任务启动入口

CLI 和 TUI 都走到同一个 `TaskRequest` → L2 dispatcher → L3 runner，区别只在 L1 如何构造 `TaskRequest`。

**CLI 模式**：
```bash
ascendc-devkit run --workflow generate_ascendc --mode new \
    --target-repo /path/to/omni-ops --repo-profile omni-ops \
    --requirement /path/to/req.yaml --npu-id 0
```

**TUI 模式**：用户启动 `ascendc-devkit`（无子命令）进入 TUI，交互式配置后启动任务。

```
┌─ New Task ──────────────────────────────────────────────────────────┐
│  Workflow:   [generate_ascendc  ▼]  ← 从 WORKFLOW_REGISTRY 读取列表 │
│  Mode:       (●) new  ( ) incremental                               │
│  Target Repo: /path/to/omni-ops        [Browse...]                   │
│  Repo Profile: [omni-ops  ▼]           ← 从 repository-profiles/ 读取│
│  Requirement: /path/to/req.yaml         [Browse...]                  │
│  NPU:        (●) --npu-id  [0]                                       │
│  ───────────────────────────────────────────────────────────────     │
│  Preview: ascendc-devkit run --workflow generate_ascendc --mode new \    │
│           --target-repo /path/to/omni-ops --repo-profile omni-ops \  │
│           --requirement /path/to/req.yaml --npu-id 0                 │
│                              [ Run ]  [ Save Config ]  [ Cancel ]    │
└──────────────────────────────────────────────────────────────────────┘
```

**设计要点**：
- **下拉选项动态读取**：Workflow 列表从 `WORKFLOW_REGISTRY`，Repo Profile 从 `repository-profiles/` 自动发现
- **预览区实时更新**：用户每改一个字段，CLI preview 同步更新——随时可复制到脚本里跑
- **Save Config**：保存为 YAML/JSON，后续 `ascendc-devkit run --config task.yaml` 复现
- **本质是同一个 TaskRequest**：TUI 内调用 `dispatcher.dispatch(task_request)`，与 CLI 走完全相同代码路径

### 8.2 TUI 监控面板

任务启动后，TUI 从"配置模式"切换到"监控模式"（四面板布局）：

```
┌─ Pipeline ──────────────────────┐ ┌─ NPU Status ──────────┐
│  ✓ Entry            00:01       │ │  NPU 0: busy (85%)   │
│  ✓ Context          00:02       │ │  NPU 1: idle         │
│  ✓ Requirement      02:15       │ └──────────────────────┘
│  ▶ Codegen          04:32       │
│  ⬡ Verify                       │ ┌─ Events ───────────────┐
│  ⬡ Integrate                    │ │  14:30:22 stage_enter │
│  ⬡ Finalize                     │ │  14:30:23 spawn_agent │
└─────────────────────────────────┘ └───────────────────────┘
┌─ Agent Output ───────────────────────────────────────────────┐
│  [ascendc-coder] 解析详设文档 gelu_design.md ...             │
│  [ascendc-coder] 开始生成 op_host/gelu_tiling.h ...         │
└──────────────────────────────────────────────────────────────┘
```

### 8.3 UI 渲染与 Agent 上下文严格隔离

TUI 面板上的所有内容——CLI preview、下拉列表、进度条、事件面板——是客户端纯渲染产物。它们不进入 `events.jsonl`，不进 Agent prompt，不消耗 LLM 上下文。Agent 能看到的只有 L3 在 `spawn_agent` 时构造的 prompt 文本，与 TUI 面板无关。

### 8.4 技术选型

**TUI 不基于 claude-code-rust**：claude-code-rust 是为对话式 TUI 设计的，与 ascendc-devkit 的流水线监控场景重叠度低。如果要实现 TUI，使用轻量框架（如 Rust 的 Ratatui）从头实现更合适。

### 8.5 工作量

| 范围 | 产出 | 估算 |
|---|---|---|
| 不做 TUI | CLI + `show` 命令 + `grep`/`tail` 过滤 | 0 周（CLI 已覆盖） |
| 最小 TUI | Pipeline 进度面板 + Agent 输出面板 | 1-2 周 |
| 完整 TUI | 四面板 + NPU Status + Events | 3-4 周 |

---

## 9. 公开接口

### 9.1 入口函数

```python
# cli/main.py
def main(argv: list[str] | None = None) -> int:
    """解析命令行参数，构造 TaskRequest，调用 L2，返回退出码。"""
    ...

# cli/commands/run.py
def parse_run_args(argv: list[str]) -> TaskRequest:
    """解析 run 子命令的参数。"""
    ...
```

### 9.2 对 L2 的调用契约

```python
# L1 → L2: 构造 TaskRequest 后调用
from application.dispatcher import dispatch
exit_code = dispatch(task_request)
```

---

## 10. 与邻层的关系

| 方向 | 层 | 关系 |
|---|---|---|
| 向下 | L2 Application | 构造 `TaskRequest` / `StageRequest` / `SkillRequest`，调用 `dispatch()` / `dispatch_single_stage()` / `dispatch_single_skill()` |
| 向下 | L4 Domain | import `TaskRequest`、`StageRequest`、`SkillRequest` 类型定义 |
| 向上 | — | 无上层依赖（L1 是顶层） |
