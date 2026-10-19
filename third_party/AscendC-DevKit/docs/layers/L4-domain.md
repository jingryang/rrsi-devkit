# L4 Domain — 领域模型

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §2 分层架构
> **依赖**：零依赖（Python stdlib only）
> **实现状态**：纯数据层 ✓ | 含 `operator.py`, `requirement.py`, `repository.py`, `contract.py`, `transition.py`, `exceptions.py` (DecisionPendingError/WorkflowTimeoutError/StageTimeoutError/EnvironmentNotAvailableError), `exit_codes.py` (EX_TIMEOUT=124 等), `skill.py` (SkillSpec/AgentManifest), `verification.py` (BuildResult/PrecisionResult/PerformanceResult, 含 stubbed 字段)

---

## 1. 定位

纯数据类型定义。这一层是整个系统中**唯一零依赖**的层——不 import 任何其他层，不做任何 I/O，不包含任何行为逻辑。

**为什么需要这一层**：当 `OperatorSpec`、`OperatorIdentity`、`RepositoryProfile` 等概念散落在各模块时，同一个概念在不同模块会有不同字段名、不同字段子集。把领域类型集中在 L4 确保**整个系统对"算子是什么"只有一种定义**。

---

## 2. 核心类型

```
domain/
├── __init__.py
├── operator.py        # OperatorSpec, TensorSpec, AttrSpec, OperatorIdentity
├── requirement.py     # Requirement, Constraint, TestCase, UnclearItem
├── repository.py      # RepositoryProfile, BuildConfig, ReferenceConfig
├── verification.py    # BuildResult, PrecisionResult, CasePrecision, PerformanceResult
├── contract.py        # StageIOContract（IO 契约校验）
├── skill.py           # SkillSpec, AgentManifest（Skill/Agent 纯数据描述）
├── exceptions.py      # DecisionPendingError（跨层共享异常）
└── exit_codes.py      # EX_OK/EX_DECISION_PENDING 等退出码
```

---

## 3. 详细类型定义

### 3.1 OperatorSpec — 算子签名

```python
@dataclass(frozen=True)
class OperatorSpec:
    """算子的静态身份：名字、输入输出、属性。"""
    name: str                       # "gelu" / "matmul"
    inputs: list[TensorSpec]        # 输入张量描述
    outputs: list[TensorSpec]       # 输出张量描述
    attrs: dict[str, AttrSpec]      # 算子属性

@dataclass(frozen=True)
class TensorSpec:
    name: str                       # "x" / "weight"
    dtype: str                      # "fp16" / "fp32" / "int8"
    shape: list[int | str]          # [128, "N"] —— 字符串表示动态维度
    optional: bool = False
```

### 3.2 OperatorIdentity — 存量算子实例

```python
@dataclass(frozen=True)
class OperatorIdentity:
    """已存在算子在目标仓中的实例——由 RepositoryAdapter 扫描得到。"""
    spec: OperatorSpec              # 算子签名
    repo_root: Path                 # 目标仓根路径
    op_dir: Path                    # 算子代码目录（绝对路径）
    files: dict[str, Path]          # 文件类型 → 绝对路径
    # 例: {"tiling_h": ".../op_host/gelu_tiling.h",
    #      "tiling_cpp": ".../op_host/gelu_tiling.cpp",
    #      "kernel_h": ".../op_kernel/gelu.h",
    #      "kernel_cpp": ".../op_kernel/gelu.cpp"}
```

### 3.3 RepositoryProfile — 代码仓画像

```python
@dataclass(frozen=True)
class RepositoryProfile:
    """描述目标代码仓的最小必要信息。"""
    name: str                       # "omni-ops"
    display_name: str               # "自定义算子仓 (omni-ops)"
    op_root_template: str           # "{repo_root}/custom_ops/{op_name}"
    build: BuildConfig

@dataclass(frozen=True)
class BuildConfig:
    command_template: str           # "bash build.sh -c {chip_version} -n {op_name}"
    artifacts_ignore: list[str]     # 构建产物 glob，排除出改动收集与回滚
    # 例: ["*.o", "*.so", "*.a", "build/", "*.log"]
```

`artifacts_ignore` 声明构建中间物的 glob 模式。算子仓内编译产生的 `.o`/`.so`/`build/` 等不算本轮代码改动，由它从 git diff 改动收集和失败回滚范围中排除。

### 3.4 Requirement — 需求描述

#### 3.4.1 Python 类型定义

```python
@dataclass(frozen=True)
class Constraint:
    """算子约束。由 perf stage 消费（performance 约束）和 verify stage 消费（precision 约束）。"""
    kind: str                      # "precision" | "performance" | "hardware"
    threshold: float | None        # 精度阈值 或 性能上限(ms)
    comparison: str | None         # "abs_diff" | "cosine" | "relative"
    baseline_ms: float | None      # 性能基线耗时
    shapes: list[list[int]] | None # 性能测试的 shape 列表
    chip_version: str | None       # 限制芯片型号

@dataclass(frozen=True)
class TestCase:
    """单个测试用例。YAML 格式及字段详细说明见 verify stage §附录。"""
    name: str                      # 用例名称
    inputs: list[dict]             # [{"name": "input", "shape": [N], "data": [...]}, ...]
    expected: dict | None          # {"max_diff": 1e-5} or explicit data
    generator: str | None          # "random_uniform" | "arange" | None
    generator_params: dict | None  # {"seed": 42, "low": -1.0, "high": 1.0}

@dataclass(frozen=True)
class UnclearItem:
    """需求文档中的不明确项，由 requirement stage 的 Agent 提取。"""
    question: str                  # 待澄清的问题
    context: str                   # 在文档中的上下文
    resolution: str | None         # 用户确认后的答案（None = 待澄清）

@dataclass(frozen=True)
class Requirement:
    """解析后的需求 DSL。由 requirement stage 的 Agent 产出，或通过 YAML 文件反序列化。"""
    op_spec: OperatorSpec
    design_doc_path: Path | None       # 详设文档路径
    constraints: list[Constraint]      # 性能/精度/硬件约束
    test_cases: list[TestCase]         # 验证用例
    reference_op: OperatorIdentity | None  # 参考算子（增量/新增模式）
    unclear_items: list[UnclearItem]   # 待澄清项

    @staticmethod
    def from_file(path: Path) -> "Requirement":
        """从 YAML 文件反序列化。格式见 verify.md §附录。"""
        ...
```

#### 3.4.2 Requirement 的两个来源

```
完整 workflow                         standalone stage
─────────────                         ────────────────
                                      
详设文档 (.md / .docx)                  requirement.yaml
    │                                       │
    ▼                                       ▼
requirement stage                        L2 Requirement.from_file()
Agent 解析 → Requirement                直接反序列化 → Requirement
    │                                       │
    └──────────┬────────────────────────────┘
               ▼
         写入 State.requirement
               │
               ▼
         后续 Stage 消费
```

完整 workflow 中，`Requirement` 由 `requirement` stage 的 Agent 解析详设文档产出，不经过 YAML 文件。Standalone stage 中，用户手写 `requirement.yaml`，L2 直接反序列化注入 State。

**YAML 格式说明**：
- `test_cases` 字段的详细写法和 generator 模式 → 见 [`stages/verify.md`](../stages/verify.md) §附录
- `constraints` + `op` 字段用于 perf/codegen/design stage → 见各 Stage 文档的 `input_contract`

### 3.5 验证结果

```python
@dataclass(frozen=True)
class PrecisionResult:
    passed: bool
    max_diff: float
    threshold: float
    per_case: list[CasePrecision]

@dataclass(frozen=True)
class PerformanceResult:
    passed: bool
    baseline_ms: float
    actual_ms: float
    speedup: float

@dataclass(frozen=True)
class BuildResult:
    passed: bool
    stdout: str
    stderr: str
    artifacts: list[Path]
```

### 3.6 Skill 与 Agent 描述

```python
@dataclass(frozen=True)
class SkillSpec:
    """Skill 的静态描述——由 SkillLoader 从 SKILL.md 发现。"""
    name: str                       # SKILL.md 所在目录名
    path: Path                      # SKILL.md 所在目录的绝对路径
    description: str = ""           # SKILL.md 第一行（去掉 # 前缀）

@dataclass(frozen=True)
class AgentManifest:
    """Agent 的 manifest——从 resources/agents/<name>.md frontmatter 解析。"""
    name: str                       # Agent 名称
    skills: list[str] = field(default_factory=list)   # frontmatter 声明的 skill 白名单
    description: str = ""           # 正文第一个非空段落
```

`SkillSpec` 是纯数据——不包含任何文件 I/O 或解析逻辑。`AgentManifest` 同样只描述 Agent 元数据，解析逻辑在 L5 `capabilities/skill/loader.py` 中。

---

## 4. RepositoryProfile YAML schema

```yaml
# resources/repository-profiles/omni-ops.yaml
name: omni-ops
display_name: 自定义算子仓 (omni-ops)

# 唯一必填：算子放在仓库的哪个目录下
op_root_template: "{repo_root}/custom_ops/{op_name}"

# 唯一必填：怎么编译
build:
  command_template: "bash build.sh -c {chip_version} -n {op_name}"
  # 构建产物 glob，排除出改动收集与回滚范围
  artifacts_ignore:
    - "*.o"
    - "*.so"
    - "*.a"
    - "build/"
    - "*.log"
```

Profile 记路径模板、编译命令和构建产物排除规则。代码怎么写由 Agent 在运行时从参考算子学习，不在 YAML 里枚举。

---

## 5. 边界

L4 没有任何 import（除了 Python stdlib 的 `dataclass` / `enum` / `pathlib`）。它不读文件、不发网络请求、不调 LLM、不跑编译。它**只是数据的形状定义**。

## 6. 与邻层的关系

| 方向 | 层 | 关系 |
|---|---|---|
| 向下 | — | 零依赖 |
| 向上 | L1-L7 全部 | 所有层都可以 import L4 的类型作为数据契约 |
