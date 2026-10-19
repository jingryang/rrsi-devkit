# 棘手点设计落地 — codegen 框架化三个关键契约

> **性质**：self-evolution 线工作记录（L3 方案设计），承接 `03-codegen-frameworkization.md` §5 三个棘手点。
> **状态**：设计落地（本文 + 配套 skill 文件已创建），下一步进 L4 实施方案。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不照搬外部脚本、不引用会话临时文件）。
> **修正记录**：
> - 2026-06-30 初版 #2 schema 错误地将通用 codegen 产出耦合到具体算子文件名（`exp_tiling.cpp` 等），已修正。
> - 2026-07-01 最小环路实跑验证通过（exp 算子，overall_score=31.40）。暴露问题 → L1 [[06-problems]]。讨论产出三项结构修正：pipeline 插入 codegen_init + cannbench_adapt；codegen 新增 manifest 产出；禁止跨 stage 读 design_spec。详见 §4。

---

## 设计原则（防再犯）

**codegen 的产出是通用代码目录，不耦合具体算子/具体文件**：
- 框架已有正确机制：`ArtifactSpec(kind="code")` = 动态文件名无固定 schema；`_expected_code_files()` 运行时从 `kernel_architecture` 动态解析文件清单
- codegen stage 和 skill 都通过 `kernel_architecture`（design 阶段的产物）获知要产出哪些文件——文件名由设计阶段决定，codegen 只负责按清单生成
- schema/contract 绝不枚举具体文件名；`exp_tiling.cpp` / `aclnn_exp.cpp` 这类是算子实例，不能写进通用契约

---

## 棘手点 #1：codegen stage 产出契约扩展

### 1.1 现状

`CodegenStage._expected_code_files()` 从 `kernel_architecture` 动态读取：

```
host_code.directory / files[]  → op_host/<file>
kernel_code.directory / files[] → op_kernel/<file>
```

产出 `generated_sources = {rel_path: content}`。文件清单由 integrator（design 阶段）写入 `kernel_architecture`，codegen 不写死文件名。

### 1.2 扩展目标

当前 `kernel_architecture` 只有 `host_code` / `kernel_code` 两个 section，不足以表达完整 ACLNN 工程（cann-bench 还需要 `op_api/` / `op_plugin/` 等子目录）。

扩展后 `kernel_architecture` 支持四个 section（所有 section 的 `directory` 语义一致；**具体文件名由 codegen 参考目标仓确定，不进契约**）：

| section | 含义 | 示例 directory | 由谁产出 |
|---------|------|---------------|---------|
| `host_code` | host 侧 tiling/infershape/def | `op_host` | integrator（已有） |
| `kernel_code` | kernel 实现 + tiling 数据 | `op_kernel` | integrator（已有） |
| `api_code` | ACLNN L0/L2 API | `op_api` | integrator（新增） |
| `plugin_code` | torch plugin 注册 | `op_plugin` | integrator（新增） |

每个 section 结构：`{directory: "op_xxx"}`。section 不存在 → 不需要产出。
**`files[]` 字段已废弃**——具体文件命名由 codegen agent 参考目标仓现有算子学习（与 CMakeLists.txt 同机制），不进设计契约。

### 1.3 核心/非核心边界

| 产出 | 性质 | 落点 |
|------|------|------|
| `host_code/files[]` / `kernel_code/files[]` | 核心 | skill 引导 LLM 生成 |
| `api_code/files[]`（参数校验/workspace/attrs/dtype dispatch） | 核心 | skill 引导 LLM 生成 |
| `plugin_code/files[]`（TORCH_LIBRARY_FRAGMENT） | 核心 | skill 引导 LLM 生成 |
| CMakeLists.txt | 非核心（脚手架） | LLM 自身能力，不进 kernel_architecture 文件清单，不进 artifact 校验 |

> 核心/非核心判断依据：参数校验 / workspace 计算 / dtype dispatch / InferShape / Tiling 策略 含算子语义，需要质量引导（跨算子/跨仓通用）。CMakeLists.txt 是仓特定脚手架，LLM 参考目标仓现有算子模式生成即可。

### 1.4 CodegenStage 改造（已完成；2026-07-01 简化）

**① `_expected_code_files()` 退到 section-level**：

```python
@staticmethod
def _expected_code_files(state: State) -> list[str]:
    """Return expected section directories (not individual filenames)."""
    arch = state.kernel_architecture or {}

    def _section_dir(kind: str, default_dir: str) -> str | None:
        if kind not in arch:
            return None                     # section not declared → skip
        section = arch[kind]
        if not isinstance(section, dict):
            return default_dir
        return section.get("directory", "") or default_dir

    results: list[str] = []
    for kind, default_dir in [
        ("host_code", "op_host"), ("kernel_code", "op_kernel"),
        ("api_code", "op_api"),   ("plugin_code", "op_plugin"),
    ]:
        d = _section_dir(kind, default_dir)
        if d:
            results.append(d)
    return results
```

② **`_build_codegen_prompt()` 文件放置规则**（section 级指导）：

```
- host_code → op_host/，kernel_code → op_kernel/，
  api_code → op_api/，plugin_code → op_plugin/
- 每个 section 的具体文件名参考目标仓现有算子确定，不进契约约束
```

③ **CMakeLists.txt + 算子导出/发现**（均属非核心脚手架，不进文件清单校验）

### 1.5 向后兼容

- `kernel_architecture` 不提供 `api_code`/`plugin_code` → 回到现有行为（仅 op_host + op_kernel），零回归
- 由 integrator 按需产新 section（self-evolution cann-bench 场景驱动）

---

## 棘手点 #2：codegen LLM skill 的 schema 逆写

### 2.1 核心洞察：codegen 产出的 spec artifact 只有 decision_log

codegen 产出分两类：

| 产出类型 | 框架模型 | 特点 |
|---------|---------|------|
| 源代码文件（op_host/*, op_kernel/*, ...） | `ArtifactSpec(kind="code")` | 动态文件名，**无固定 schema**；框架通过 `kernel_architecture` 运行时校验完整性 |
| 决策记录 | `ArtifactSpec(kind="spec")` | 固定文件名 `decision_log.json`，固定 schema（key_decisions + known_issues + assumptions） |

**skill 的 `schema/` 只需要定义 decision_log.json**——源代码文件的契约由 `kernel_architecture.json`（设计阶段产出、codegen 读取）天然承载，不需要再写一份 schema 来耦合文件名。

### 2.2 skill 定位

**归属**：`.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding/`

**输入**（文件契约，当前工作目录下）：
- `design_spec.json` — 算子定义/接口/张量规格
- `tiling_strategy.json` — 切分策略
- `kernel_architecture.json` — Kernel 架构 + 待产出文件清单（各 section 的 `directory/files[]`）
- `meta.json` — 编程模型/芯片信息
- `op_name` — 上下文变量（由调用方注入）

**输出**（文件契约）：
- 源代码文件：按 `kernel_architecture` 各 section 清单产出到对应子目录
- `decision_log.json` — 关键决策记录（schema 见 `schema/decision_log.json`）

**文件完整性判据**：`kernel_architecture` 声明的每个 file 在对应 directory 下存在且非空。

### 2.3 schema 定义

已在 `.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding/schema/decision_log.json` 创建。

```json
{
  "required": true,
  "required_keys": ["key_decisions", "known_issues", "assumptions"],
  "description": "codegen skill 的 spec artifact——关键决策+已知问题+假设。供框架提取进 State.decision_logs 用于 loopback 上下文注入",
  "example": {
    "key_decisions": [
      {
        "decision": "选择双缓冲减少 UB 占用",
        "reason": "UB 仅 192KB，三缓冲不可行",
        "constraints": ["UB_LIMIT=192KB"]
      }
    ],
    "known_issues": ["kernel.cpp 浮点边界值可能溢出"],
    "assumptions": ["输入 shape N%256==0"]
  }
}
```

### 2.4 SKILL.md 内容边界（CLAUDE.md 2.7 落地）

**写进 skill**（核心质量引导，跨算子/跨仓通用）：
- 分层编码顺序（TilingData → Host → Kernel → ACLNN → Plugin）
- TilingData 归一化铁律（plain C struct，不用 CANN 宏）
- 编程模型路由（Regbase/Membase/Cube 三条路径）
- ACLNN API 核心质量红线（参数校验/workspace/attrs/dtype dispatch 的正确做法）
- 编码自检规范（32-byte alignment / TILING_KEY_IS 分支覆盖 / TilingData 一致性）
- 精度修复模式（读 error_info → Edit 修复，不重写全部文件）

**不写进 skill**（脚手架/仓特定，LLM 参考目标仓现有算子）：
- CMakeLists.txt 模板、`register_aclnn_op` 宏、仓特定 include 路径
- 仓目录布局（cann-bench vs omni-ops 的具体路径）
- 算子特定 shape / dtype / 公式（来自 design_spec.json 输入）

### 2.5 即插即用验证判据

此 skill 从 DevKit 仓取出后，在任意目录下：
1. 准备好四个输入文件（design_spec.json / tiling_strategy.json / kernel_architecture.json / meta.json）
2. `/<skill-name>` 发出，LLM 按 SKILL.md 引导生成代码 + decision_log.json
3. 生成的源文件清单与 kernel_architecture.json 声明的 files[] 一致
4. 不依赖 DevKit 框架注入的上下文、不依赖仓内该 skill 目录之外的文件

### 2.6 已创建的文件

```
.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding/
├── SKILL.md                     # 核心质量引导（分层编码 + 自检 + 红线）
└── schema/
    └── decision_log.json        # spec artifact schema
```

---

## 棘手点 #3：DeployStage / CannbenchEvalStage I/O 契约

### 3.1 定位

这两个 Stage 是 **框架代码**（`src/ascendc_devkit/orchestration/stages/`），不是 skill。属于「命令编排」层——确定性 shell 命令链，不需 LLM。

在单算子 pipeline 中的位置：

```
... → CodegenStage → DeployStage → CannbenchEvalStage
                         ↑                ↑
                    新增 Stage        新增 Stage
```

### 3.2 DeployStage

**职责**：把编译产物部署到可调用态——`build.sh → 装 .run → pip install wheel → smoke_test`。

**input_contract**：
```python
StageIOContract(
    requires=[
        "generated_sources",   # codegen 产出（定位源码目录）
        "op_name",
        "repo_root",
    ],
    optional=[
        "device_id",           # NPU 卡号（smoke test 用）
    ],
)
```

**output_contract**：
```python
StageIOContract(
    provides=["deploy_result"],
)
```

**新增 State 字段**：
```python
deploy_result: DeployResult | None = None
```

```python
@dataclass(frozen=True)
class DeployResult:
    run_package: str = ""          # .run 包路径
    wheel_package: str = ""        # .whl 包路径
    ld_library_path_add: str = ""  # opp lib 路径（后续 Stage 需 re-export）
    smoke_passed: bool = False     # 冒烟测试是否通过
    install_path: str = ""         # per-op opp install-path（02 D 方案）
    python_path: str = ""          # pip --target 路径（02 D 方案）
```

**actions()**：调子进程执行确定性命令链（不派 agent）：
1. `bash {repo_root}/.../build.sh` → 产 .run + .whl
2. `bash dist/*.run --install-path=<per-op-opp-dir>`（装 opp 到 per-op）
3. `pip install --target=<per-op-python-dir> --force-reinstall --no-deps dist/*.whl`
4. `LD_LIBRARY_PATH=<opp-lib> ASCEND_CUSTOM_OPP_PATH=<per-op-opp>  python smoke_test.py`

**与 01/02 衔接**：
- 01 NPU：`device_id` 从 `NPUSlotManager.acquire()`（smoke test 可选用）
- 02 opp+whl D 方案：`--install-path` + `pip --target` 由外层 runner 注入 per-op 隔离路径

**fail_strategy**：`"halt"`（部署失败 → 评测不可进行）

### 3.3 CannbenchEvalStage

**职责**：拉起 cann-bench `kernel_eval` CLI（`--skip-install` 模式），出 `overall_score`（编译 0.2 + 功能 0.3 + 性能 0.5）。

**非侵入边界**：不改 cann-bench 任何代码。所有控制通过 CLI 参数 + 环境变量传入。

**input_contract**：
```python
StageIOContract(
    requires=[
        "deploy_result",        # 含 per-op opp/python 路径
        "generated_sources",    # 源码路径
        "op_name",
        "repo_root",
    ],
    optional=[
        "device_id",            # NPU 卡号（由 NPUSlotManager 分）
        "no_perf",              # 跳过性能（default: false）
    ],
)
```

**output_contract**：
```python
StageIOContract(
    provides=["eval_result"],
)
```

**新增 State 字段**：
```python
eval_result: EvalResult | None = None
```

```python
@dataclass(frozen=True)
class EvalResult:
    overall_score: float = 0.0      # 三维度加权总分（0-100）
    pass_rate: float = 0.0          # 功能用例通过率
    compile_score: float = 0.0
    function_score: float = 0.0
    performance_score: float = 0.0
    report_json: str = ""           # cann-bench 评测报告 JSON 路径
    baseline_source: str = ""       # "inherited" | "fallback"
    num_cases: int = 0
    num_passed: int = 0
```

**actions()**：调子进程起 cann-bench Python CLI（非 shell wrapper，因为 shell 不暴露 `--skip-install`）：

```bash
export PYTHONPATH=<per-op-python-dir>
export ASCEND_CUSTOM_OPP_PATH=<per-op-opp-dir>/vendors/custom_ops
export ASCEND_OPP_PATH=<真实CANN opp>  # 只读共享内置 opp

python -m kernel_eval eval \
  --source-dir <source-dir> \
  --operator <op_pascal> \
  --device-id <slot> \
  --skip-install
```

评测完成后定位最新 `reports/<bench_name>/eval_*.json`，解析 `overall_score` 进 `EvalResult`。

**与 01/02 衔接**：
- 01 NPU：`device_id` 从 `NPUSlotManager.acquire()` → `--device-id <slot>`
- 02 opp+whl D 方案：per-op `PYTHONPATH` + `ASCEND_CUSTOM_OPP_PATH` 注入评测子进程 env

**fail_strategy**：`"continue"`（评测失败记录 loss=0，不阻塞其他算子）

### 3.4 与 training-time loss 的关系

- CannbenchEvalStage 产出 per-op `EvalResult` → State 持久化
- training-time loss 聚合器（04 §4）从多个算子的 `eval_result.overall_score` 聚合 epoch 级 loss
- 驱动归因 + 改进循环（04 §3）

---

## 4. 修正后的 pipeline（2026-07-01，最小环路实跑后讨论产出）

### 4.0 原方案暴露的三个设计问题

最小环路实跑验证暴露的不只是代码 bug——三个结构性问题在讨论中被识别：

| 问题 | 发现过程 |
|------|---------|
| ① section 声明（`kernel_architecture`）放在设计阶段不合理——section 需求取决于目标仓，不是算子设计 | integrator 过设计讨论 |
| ② `__init__.py` wrapper 缺失在 eval 才暴露，归因到 codegen，但它是仓适配问题不是代码质量问题 | P1 修复讨论 |
| ③ cannbench_adapt 如果读 `design_spec` 跨 stage 取签名，codegen 已修正的内容（如 bf16→移除）会被 revert | codegen_manifest 讨论 |

### 4.1 修正后的 pipeline

```
entry
  ↓
context                        # repo_profile 检测（下游共享，设计阶段不读）
  ↓
[design]                       # 只依赖算子规格，不依赖 repo_profile
  产出: design_spec, tiling_strategy, kernel_structure
  不产出: kernel_architecture（移到 codegen_init）
  ↓
codegen_init (新 substage)     # 读 repo_profile + 参考算子 → 确定 section + 文件布局
  产出: kernel_architecture（section 声明，无 files[]）
  ↓
codegen                        # 按 section + 参考算子生成代码
  产出: generated_sources + decision_log + codegen_manifest（新增）
  ↓
deploy                         # build + install + smoke（确定性 shell）
  ↓
cannbench_adapt (新 stage)     # LLM 补全仓胶水文件，禁止动算子代码
  读: generated_sources + codegen_manifest（不跨 stage 读 design_spec）
  ↓
cannbench_eval                 # kernel_eval → overall_score
  ↓
finalize
```

### 4.2 新增 Stage：codegen_init（substage）

**定位**：codegen 的初始化步骤，替代 integrator 的 section 声明职责。不是新 LLM agent——是 `_build_codegen_prompt()` 的前置确定性逻辑 + 必要时 lightweight agent 调用来参考目标仓。

**输入**：
- `repo_profile`（从 State 读）——目标仓是什么、有哪些参考算子
- `design_spec` / `tiling_strategy`（从 State 读）——算子规模/复杂度（是否影响 section 选择）

**输出**：
- `kernel_architecture`（section 声明，无 files[]）

**为什么不用 LLM agent**：section 决定是机械规则——所有算子都需要 host/kernel；api/plugin 取决于目标仓是否要求。决定是二值的，不需要 LLM 做权衡判断。

### 4.3 新增 Stage：CannbenchAdaptStage

**定位**：deploy 和 eval 之间的仓适配层。**用 LLM 但 scope 极窄**——只读写仓胶水文件，不动算子代码。

**为什么需要 LLM**：不同仓的发现/注册机制不同（`__init__.py` wrapper / registry.py / 其他），不同版本的仓格式可能变化。枚举所有仓用 Python 确定性覆盖不现实——会随仓版本膨胀，违反"不进 Python 代码"原则。

**LLM 约束**（硬性，写进 prompt / agent manifest）：
- ✅ 可读：generated_sources、codegen_manifest、参考算子、目标仓胶水文件
- ✅ 可写：仓胶水文件（`__init__.py` / CMakeLists.txt / registry 文件）
- ❌ **禁止**写：op_host/、op_kernel/、op_api/、op_plugin/（算子代码文件）
- ❌ **禁止**改：算子签名、dtype 列表、参数定义（以 codegen_manifest 为准）

**输入**（StageIOContract）：
```python
StageIOContract(
    requires=["generated_sources", "codegen_manifest", "repo_root"],
    optional=[],
)
```

**输出**：
```python
StageIOContract(
    provides=["adapt_result"],
)
```

**新增 State 字段**：
```python
adapt_result: AdaptResult | None = None

@dataclass(frozen=True)
class AdaptResult:
    adapted: bool = False        # 是否执行了适配修改
    files_modified: list[str]    # 修改的文件列表
    errors: list[str]            # 适配错误（与算子代码无关）
```

**fail_strategy**：`"continue"`（适配失败不阻塞 eval——eval 会因找不到算子而得 0 分，归因链可区分"适配失败" vs "算子质量差"）

**与 codegen 的关系**：
- codegen 的 prompt 仍保留"⑥ 算子导出检查"指引（P1 修复）——正常路径由 codegen 完成
- CannbenchAdaptStage 是**兜底**——codegen 漏掉了 wrapper，adapt 补上
- 两者都读 `codegen_manifest`，签名一致，不会互相覆盖

### 4.4 新增 codegen 产出：codegen_manifest

**问题**：`cannbench_adapt` 如果读 `design_spec` 取签名，codegen 中途可能修正（如发现 Ascend950 不支持 bf16 → 移除），adapt 会按旧签名生成 wrapper，造成不一致。

**解决**：codegen 新增结构化产出 `codegen_manifest`——记录 codegen 实际采纳的签名。下游 stage 只读此文件，不跨 stage 读 `design_spec`。

**新增 State 字段**：
```python
codegen_manifest: dict | None = None  # codegen 实际产出的算子签名
```

**schema**（资源文件放在 skill 目录下）：
```json
{
  "op_name": "exp",
  "op_pascal": "Exp",
  "inputs": [{"name": "x", "type": "Tensor"}],
  "outputs": [{"name": "y", "type": "Tensor"}],
  "attrs": [
    {"name": "base",  "type": "float", "default": -1.0},
    {"name": "scale", "type": "float", "default": 1.0},
    {"name": "shift", "type": "float", "default": 0.0}
  ],
  "supported_dtypes": ["float32", "float16"]
}
```

**产出时机**：codegen agent 在完成所有源文件后，根据实际生成的代码填写 manifest。不是从 `design_spec` 拷贝——是 codegen 确认后的最终签名。

**与 decision_log 的区别**：
| | decision_log | codegen_manifest |
|---|---|---|
| 目的 | 决策追溯，loopback context 注入 | 下游 stage 读实际签名 |
| 读者 | codegen loopback 时的自身上下文 | cannbench_adapt、eval、其他下游 |
| schema | `schema/decision_log.json` | `schema/codegen_manifest.json`（需新建） |

### 4.5 修正后的 Stage I/O 流向（信息不跨 stage）

```
         design_spec ──→ codegen（读，参考）──→ codegen_manifest
                                │                      │
                                │ generated_sources    │
                                ↓                      ↓
                              deploy ←─────────────────┘
                                │                      │
                                │ deploy_result        │
                                ↓                      │
                           cannbench_adapt ←───────────┘ （读 manifest，不读 design_spec）
                                │
                                │ adapt_result
                                ↓
                           cannbench_eval
```

**硬性规则**：
- `cannbench_adapt` 的签名来源只能是 `codegen_manifest`，禁止读 `design_spec`
- `design_spec` 的设计契约是"算子应该是什么"——codegen 只是参考
- `codegen_manifest` 的契约是"算子实际是什么"——下游以此为准
- 跨 stage 直接读上游的上游 = 信息不一致的根因，发现即改

### 4.6 实施优先级

| 步 | 内容 | 依赖 |
|----|------|------|
| 9 | **codegen_init substage**：section 声明从 design 移到 codegen 初始化 | 依赖步 8（integrator 简化已完成） |
| 10 | **codegen_manifest**：新增 schema + codegen output_contract 扩展 + State 字段 | 无依赖 |
| 11 | **CannbenchAdaptStage**：新建 LLM stage（窄 scope，禁动算子代码） | 依赖步 9 + 步 10 |
| 12 | **设计阶段去 repo_profile 依赖**：移除 design agent 对 repo_profile 的读取 | 依赖步 9 |
| 13 | **P1 补充**：CannbenchAdaptStage 落成后，codegen prompt 中"⑥ 算子导出检查"可降为 best-effort 提示 | 依赖步 11 |

---

## 5. 与已有决策的关系

- 承接 03 §2 核心/非核心边界：op_api/op_host/op_kernel/op_plugin 核心归 skill，CMakeLists 非核心归 LLM
- 承接 03 §4 schema/第一准则落点：skill 叶子有 `schema/decision_log.json`（即插即用），Python Stage 有 `StageIOContract`（框架契约）
- 承接 01 §3.2 非侵入 cann-bench：Stage 只调 CLI + 设 env
- 承接 02 §2.3 D 方案：DeployStage 外层 install 到 per-op，CannbenchEvalStage `--skip-install` 评测
- 承接 CLAUDE.md 2.5 唯一通路：full-pipeline 独立 skill 通路不保留
- **修正**：codegen 产出 = 通用代码目录，不耦合具体算子/文件名；文件清单由 kernel_architecture runtime 决议
