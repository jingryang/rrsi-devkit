# L6 Adapters — 外部世界隔离

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §2 分层架构
> **上游依赖**：L3 Orchestration, L5 Capabilities
> **下游依赖**：L4 Domain, L7 Infrastructure
> **实现状态**：`repository/base.py` (RepositoryAdapter(ABC)) ✓ | `repository/generic.py` (YAML 驱动, materialize/scan/build/write_dev_record) ✓ | `repository/profile_loader.py` (ProfileLoader) ✓ | `toolchain/cann.py` (CANNToolchain, 环境检测 + CMakeLists 生成) ✓ | `toolchain/pta.py` (PTAToolchain, torch.ops.custom 代码生成) ✓ | `npu/runner.py` (NPURunner, 真实执行 + harness 生成) ✓ | `npu/slot.py` (NPUSlotManager, 线程安全多卡分配) ✓ | `llm/base.py` (LLMProvider(ABC)) ✓ | `llm/anthropic.py` ✓ | `llm/bedrock.py` ✓ | `llm/vertex.py` ✓

---

## 1. 定位

所有与外部系统（代码仓、NPU、LLM Provider、CANN 编译器）的交互都在这一层。上层只通过 protocol/ABC 调用，不感知具体实现。

**这是架构中最关键的一层**：它决定了平台能否接入新的代码仓、新的 LLM Provider、新的 NPU 型号而不改核心。

---

## 2. 四大 Adapter 子模块

```
adapters/
├── repository/  (base.py / generic.py / profile_loader.py / <repo>.py)
├── npu/         (runner.py / slot.py)
├── llm/         (anthropic.py / bedrock.py / vertex.py)
└── toolchain/   (cann.py / pta.py)
```

---

## 3. Repository Adapter

### 3.1 设计原则

系统真正需要提前知道的只有两件事：算子目录放在哪里、怎么编译。其余所有"代码怎么写"的知识由 Agent 在运行时从参考算子学习。

### 3.2 双层解耦

```
       接入新代码仓
              │
              ▼
   ┌──────────────────────┐
   │ 写 3 行 YAML profile   │  ← 95% 的仓只需要这步
   │ (路径模板 + 编译命令)   │
   └──────────┬───────────┘
              │
              ▼
   ┌─────────────────────────┐
   │ GenericRepositoryAdapter │  ← 纯配置驱动
   │   - scan:                │
   │     按 op_root_template  │
   │     定位算子目录          │
   │   - build:               │
   │     执行 command_template │
   │   - materialize:         │
   │     standalone 落盘入口   │
   └──────────┬──────────────┘
              │
              │ 只有极少数场景需要 escape hatch
              ▼
   ┌──────────────────────────┐
   │ adapters/repository/      │
   │   <repo>.py               │  ← 继承 GenericAdapter
   │   只覆盖差异方法           │      覆盖 <5% 场景
   └──────────────────────────┘
```

### 3.3 RepositoryAdapter ABC

```python
class RepositoryAdapter(ABC):
    """所有代码仓适配器的协议。GenericRepositoryAdapter 是默认实现。"""
    profile: RepositoryProfile

    # —— 新生成场景 —— #
    @abstractmethod
    def materialize_new_operator(
        self, op: OperatorSpec, sources: dict[str, str], dest_root: Path,
        category: str | None = None,
    ) -> list[Path]:
        """按 op_root_template 在目标仓创建算子目录并写入源文件，返回落盘文件列表。"""

    # —— 存量算子 —— #
    @abstractmethod
    def scan_existing_operator(
        self, repo_root: Path, op_name: str, category: str | None = None
    ) -> OperatorIdentity:
        """从目标仓里找到已有算子，返回其文件布局。"""

    # —— 构建 —— #
    @abstractmethod
    def build(
        self, repo_root: Path, op: OperatorIdentity, chip_version: str
    ) -> BuildResult:
        """调用仓自身构建系统，在目标仓内原地编译指定算子。"""

    # —— 开发记录 —— #
    @abstractmethod
    def write_dev_record(self, op_dir: Path, entry: dict) -> Path:
        """写一条 dev_record 记录到 op_dir/.lingxi/，返回记录文件路径。"""
```

### 3.4 接入新代码仓的步骤

1. 写 `resources/repository-profiles/<repo>.yaml`（~5 行）
2. Agent 在 Stage 5 读参考算子代码，自学文件命名和代码风格
3. 编译失败时错误反馈自动注入 Agent 迭代，无需手写 convention 规则

**不需要改**：`kernel/` / `orchestration/` / `domain/` 任何文件。

### 3.5 上层调用方式

```python
# L3 Orchestration 中，完全不感知底层是哪个仓
adapter = GenericRepositoryAdapter(profile)
identity = adapter.scan_existing_operator(repo_root, "gelu")
result = adapter.build(repo_root, identity, chip_version="ascend910b")
```

上层只依赖 `RepositoryAdapter` ABC（`adapters/repository/base.py`），不 import 具体实现。具体实现的选择通过依赖注入完成。

---

## 4. NPU Runner

```
adapters/npu/runner.py

上层                             外部
spawn_agent
call_skill    ──→  NPURunner.execute(       ┌──────────┐
run_gate              operator, test_cases,  │ NPU 硬件  │
                      npu_id)                │ (本地/SSH/ │
                       │                     │ Docker)   │
                       ├─ 编译 (via CANN)     └──────────┘
                       ├─ 加载 opp
                       ├─ 逐用例执行
                       └─ 收集结果 → VerificationResult
```

### 4.1 环境检测

`NPURunner.__init__()` 调用 `_check_environment()` 静态检测 NPU 运行时可用性：

```python
def _check_environment(self) -> dict:
    info = {"torch_available": False, "torch_npu_available": False, "device_count": 0}
    try:
        import torch
        info["torch_available"] = True
        try:
            import torch_npu
            info["torch_npu_available"] = True
            info["device_count"] = torch_npu.npu.device_count()
        except ImportError:
            pass
    except ImportError:
        pass
    return info
```

- 结果存入 `self._env_info` dict 和 `self._torch_npu_available: bool` flag
- `execute()` 根据 `_torch_npu_available` 分发到真实执行或 stub 降级

### 4.2 execute() 双路径

```python
def execute(self, operator, test_cases, npu_id=0) -> dict:
    if not self._torch_npu_available:
        Logger.warn("NPU environment not available, falling back to stub execution")
        return self._stub_execute(operator, test_cases, npu_id)
    return self._execute_real(operator, test_cases, npu_id)
```

- 无 NPU 环境 → `_stub_execute()` 返回 `{"passed": True, "bottleneck": "stubbed"}` + Logger.warn
- 有 NPU 环境 → `_execute_real()` 执行完整验证流程

### 4.3 Test Harness 生成

`_build_test_harness()` 根据 `TestCase` 内容生成更真实的 Python 测试脚本：

- 支持 `test_case.generator`（`random_uniform` / `arange`）生成张量初始化代码
- 支持 `test_case.shape` / `test_case.dtype` 定制张量规格
- `test_cases` 为空时默认 `shape=[1024]`
- 输出结构包含 per-shape timing 和精度数据的 JSON

```python
class NPURunner:
    """NPU 算子执行器。封装 torch_npu 调用、环境检测、stub 降级。"""
    def __init__(self, chip_version: str = "ascend910b"): ...
    def _check_environment(self) -> dict: ...
    def execute(self, operator, test_cases, npu_id=0) -> dict: ...
    def _stub_execute(self, operator, test_cases, npu_id) -> dict: ...
    def _execute_real(self, operator, test_cases, npu_id) -> dict: ...
    def _build_test_harness(self, operator, test_cases) -> str: ...
```

---

## 5. LLM Provider

```
adapters/llm/
├── anthropic.py    # Anthropic API (Claude)
├── bedrock.py      # AWS Bedrock
└── vertex.py       # GCP Vertex AI
```

所有 provider 实现同一 `LLMProvider` protocol。上层（L5 Capabilities）通过环境变量选择 provider，不写死任何一个。

---

## 6. Toolchain (CANN / PTA)

本地工具调用（编译、安装、PTA 生成），属于"本地外部世界"——不走网络，但会调用 subprocess。

### 6.1 环境检测

`CANNToolchain.__init__()` 调用 `_detect_cann()` 检测 CANN 工具链可用性：

```python
def _detect_cann(self) -> None:
    self._cann_home = os.environ.get("ASCEND_TOOLKIT_HOME", "")
    self._cann_available = bool(self._cann_home) and shutil.which("ops_compile") is not None

@property
def is_available(self) -> bool:
    return self._cann_available
```

### 6.2 compile()

```python
class CANNToolchain:
    def __init__(self): ...
    def _detect_cann(self) -> None: ...
    @property
    def is_available(self) -> bool: ...
    def compile(self, sources: Path | list[Path], chip_version: str, work_dir: Path | None = None) -> BuildResult: ...
    @staticmethod
    def _generate_cmake(sources: list[Path]) -> str: ...
    def install(self, build_result: BuildResult, opp_path: Path) -> None: ...
```

- CANN 不可用 → Logger.warn + 返回 `BuildResult(passed=True, stdout="[stub] CANN not available")`（不阻断 pipeline）
- `work_dir` 支持 CMakeLists.txt 自动生成（`_generate_cmake()` 静态方法，sources 包含 .cpp/.h 时生成）
- `install()` 把编译产物安装到 `ASCEND_OPP_PATH`

---

## 7. 边界

L6 不做业务决策。Repository Adapter 只知道"文件应该放到哪个目录"，不知道"为什么要放那里"；NPU Runner 只知道"怎么在 NPU 上执行用例"，不知道"什么算精度通过"。判断逻辑在上层（L3 Gate）。

---

## 8. 扩展点

六类扩展，都有"无需改核心"保证：

| 扩展类型 | 加什么 | 改什么 | 不改什么 | 估算 |
|---|---|---|---|---|
| 新增目标代码仓 | `repository-profiles/<repo>.yaml` | 无（默认走 GenericAdapter） | 一切核心代码 | 0.5-2 天 |
| 新增 LLM Provider | `adapters/llm/<provider>.py` | `config/env.py` | 业务层 | 0.5-1 天 |
| 新增 Agent/Skill | `resources/agents/<name>.md` / `resources/skills/<name>/` | `plugin.json` | Python 代码 | 0.5-3 天 |
| 新增 Stage | `orchestration/stages/<name>.py` | 无（自动发现） | `kernel/` 引擎核心 | 0.5-1 天 |
| 新增 Workflow | `registry.py` 声明式追加 | `registry.py` 一行 | Stage 实现 | 0.5 天 |
| Workflow 嵌套 | `CompositeStage` 包装 | 注册子 Workflow + 引用 | `kernel/runner.py` | 1-2 天 |

---

## 9. 与邻层的关系

| 方向 | 层 | 关系 |
|---|---|---|
| 向上 | L3/L5 | 提供 `RepositoryAdapter`、`NPURunner`、`LLMProvider` protocol 给上层调用 |
| 向下 | L4 Domain | import `BuildResult`、`OperatorIdentity`、`OperatorSpec` 等类型 |
| 向下 | L7 Infrastructure | 使用 `Workspace`、`FileSystem`、subprocess 管理 |
