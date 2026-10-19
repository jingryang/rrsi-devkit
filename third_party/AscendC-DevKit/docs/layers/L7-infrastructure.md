# L7 Infrastructure — 横切基础

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §2 分层架构
> **依赖**：无（最底层）
> **实现状态**：Workspace / EventLog / Logger / Terminal / FileSystem / RepoGuard ✓

---

## 1. 定位

提供所有上层都需要的横切能力。这一层没有领域知识，不感知"算子"概念。

---

## 2. 子模块

| 模块 | 职责 | 为什么需要它 |
|---|---|---|
| `Workspace` | 管理 `output/<run_id>/` 目录的创建、清理、隔离 | 每次运行产物需要独立隔离的目录，多进程并行不能冲突 |
| `EventLog` | 以 append-only 方式写入 `events.jsonl` | 事件流是系统运行历史的唯一权威记录，支持 resume |
| `Logger` | 结构化日志 + 三层反馈分流（Stage / Action / Heartbeat） | 不同粒度的信息需要不同的输出通道和格式 |
| `Terminal` | 终端能力探测（TTY / 颜色 / 宽度）、spinner、进度条 | CLI 和 TUI 需要知道自己在什么终端环境里运行 |
| `FileSystem` | 原子写、目录同步、临时文件管理 | 避免文件半写、避免并发冲突 |
| `RepoGuard` | 算子仓改动的快照基线与失败回滚（git / 文件备份） | codegen/verify/perf 直接改算子仓，需要可回滚的安全网 |

---

## 3. Workspace

### 3.1 布局

```python
workspace = Workspace.create(run_id="20260525-143022")

workspace.dir               # output/20260525-143022/
workspace.agents_log        # output/20260525-143022/agents/
workspace.subprocess_log    # output/20260525-143022/subprocess/
workspace.events_path       # output/20260525-143022/events.jsonl
workspace.report_path       # output/20260525-143022/report.md
workspace.report_json_path  # output/20260525-143022/report.json
# repo_backup/             # 非 git 仓的算子目录基线备份（RepoGuard）
```

Workspace 持有单次运行的事件流、报告、子进程日志与非 git 仓基线备份。算子代码本身在目标仓 op_dir 内，不落 workspace。

### 3.2 生命周期

```python
class Workspace:
    run_id: str

    @classmethod
    def create(cls, run_id: str | None = None) -> Workspace:
        """创建运行目录。run_id=None 时自动生成。"""
        ...

    def mark_dirty(self) -> None:
        """标记 workspace 异常退出（用于 resume 时警告）。"""
        ...

    def cleanup(self) -> None:
        """删除运行目录。"""
        ...

    @classmethod
    def from_existing(cls, run_id: str) -> Workspace:
        """从已有 run_id 恢复 workspace 引用（resume 场景）。"""
        ...
```

### 3.3 隔离保证

- 不同 `run_id` 的 workspace 完全独立
- 多进程并行时不冲突（每个进程自己的 `run_id`）
- 退出前清理临时文件和子进程

---

## 4. EventLog

```python
class EventLog:
    """append-only 事件写入器。线程安全。"""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()

    def append(self, event: Event) -> None:
        """原子追加一条事件到 events.jsonl。"""
        with self._lock:
            with open(self._path, "a") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
                f.flush()
                os.fdatasync(f.fileno())

    @staticmethod
    def read(path: Path) -> list[Event]:
        """读取全部事件，用于 resume / report。"""
        ...

    @staticmethod
    def replay(path: Path) -> Iterator[Event]:
        """流式读取事件，用于 show --tail。"""
        ...
```

**设计原则**：
- 心跳事件不进 events.jsonl（噪音），只走 stdout
- 所有时间戳 ISO 8601 + 时区
- 所有耗时同时记录 `started_at` / `ended_at` / `duration_ms`

---

## 5. Logger

```python
class Logger:
    """三层反馈分流。"""

    @staticmethod
    def stage_header(stage_name: str, total_stages: int, current_index: int) -> None:
        """━━━━ [codegen] Codegen ━━━━━━━━━━━ 03:42 elapsed"""
        ...

    @staticmethod
    def stage_done(stage_name: str, elapsed_ms: int) -> None:
        """━━━━ ✓ codegen done (02:13)"""
        ...

    @staticmethod
    def action(action_type: str, details: str) -> None:
        """  • spawn_agent ascendc-coder ... [running 00:45]"""
        ...

    @staticmethod
    def heartbeat(message: str) -> None:
        """⠋ ascendc-coder thinking... (45s, tokens=1832)"""
        ...
```

---

## 6. Terminal

```python
class Terminal:
    """终端能力探测与适配。"""

    @staticmethod
    def is_tty() -> bool: ...
    @staticmethod
    def width() -> int: ...
    @staticmethod
    def supports_color() -> bool: ...
    @staticmethod
    def supports_unicode() -> bool: ...

class Spinner:
    """终端 spinner（TTY 时动态，非 TTY 时降级为定时输出）。"""
    def start(self, message: str) -> None: ...
    def update(self, message: str) -> None: ...
    def stop(self) -> None: ...
```

---

## 7. FileSystem

```python
class FileSystem:
    """原子文件操作。"""

    @staticmethod
    def atomic_write(path: Path, content: str) -> None:
        """先写临时文件，再 rename——避免文件半写。"""
        ...

    @staticmethod
    def sync_dir(src: Path, dst: Path) -> None:
        """目录同步（copytree，目标已存在时合并）。"""
        ...

    @staticmethod
    def ensure_dir(path: Path) -> None:
        """确保目录存在（mkdir -p）。"""
        ...

    @staticmethod
    def temp_dir(prefix: str) -> Path:
        """创建临时目录，上下文管理器退出时自动清理。"""
        ...
```

---

## 8. RepoGuard

codegen/verify/perf 直接在算子仓 op_dir 内生成、编译、调试代码。RepoGuard 提供写仓前的快照基线与失败回滚，保证仓的干净状态不被半成品污染。所有破坏性操作严格限定 op_dir 范围。

```python
class RepoGuard:
    """算子仓改动的快照/回滚。范围严格限定 op_dir。"""

    def __init__(self, backup_root: Path | str | None = None,
                 ignore_globs: list[str] | None = None,
                 enabled: bool = True): ...

    def is_git_repo(self, repo_root) -> bool: ...

    def is_clean(self, repo_root, op_dir) -> bool:
        """op_dir 无已跟踪改动且无未跟踪文件（构建产物按 ignore_globs 排除）。"""
        ...

    def create_baseline(self, repo_root, op_dir) -> str:
        """确立写仓前基线。git 仓返回 HEAD sha；非 git 仓拷贝 op_dir
        到 backup_root，返回 "filebackup:<path>" 标识。"""
        ...

    def changed_paths(self, repo_root, op_dir, baseline_ref) -> list[str]:
        """op_dir 内自基线以来的改动文件（git diff ∪ 未跟踪，排除 ignore_globs）。"""
        ...

    def rollback(self, repo_root, op_dir, baseline_ref) -> bool:
        """把 op_dir 还原到基线。git 仓两步 checkout + clean；
        非 git 仓从文件备份还原。"""
        ...
```

### 8.1 基线与回滚策略

- **基线**：git 仓 = HEAD sha（写仓前由前置干净校验保证 HEAD 即运行前状态）；非 git 仓 = op_dir 文件备份到 `output/<run_id>/repo_backup/`。
- **回滚**：git 仓两步 `git checkout <baseline> -- <op_dir>`（还原已跟踪改动）+ `git clean -fd <op_dir>`（删未跟踪新增），模式无关统一调用；非 git 仓从备份还原。
- **范围**：回滚 blast radius 严格限定 op_dir，绝不 `reset --hard` 整仓、绝不动 git config 或分支。
- **构建产物**：`ignore_globs`（来自 profile 的 `build.artifacts_ignore`）从改动收集与回滚中排除 `.o`/`.so`/`build/` 等中间物。

### 8.2 安全约束

- 所有 git 子进程用列表参数调用（非 shell 字符串拼接），防注入。
- git 不可用或超时时记 warn 并降级，不抛断流程。
- `enabled=False` 时所有方法为 no-op，便于无 git 依赖的单元测试。

---

## 9. 边界

L7 不知道"算子"是什么，不知道"Stage"是什么，不知道"Agent"是什么。它只知道目录、文件、日志、终端、git 仓。

## 10. 与邻层的关系

| 方向 | 层 | 关系 |
|---|---|---|
| 向下 | — | 无依赖（最底层） |
| 向上 | L1-L6 全部 | 被所有上层使用 |
