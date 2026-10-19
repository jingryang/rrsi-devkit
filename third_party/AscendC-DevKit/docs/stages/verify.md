
# Verify — 编译+精度验证

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §3 统一 Pipeline
> **实现状态**：已实现 ✓（自动注册, 由 GraphExecutor 经 AtomicStage 驱动）
> **位于 L3**: `orchestration/stages/verify.py`

---

## 1. 定位

对算子仓 op_dir 内的代码进行编译验证和精度验证。new 和 incremental 共用同一验证逻辑——调用算子仓自身的构建系统编译，在 NPU 上跑测试用例，验证精度门禁。

性能验证不在本 Stage 内——由后续的 perf stage 独立负责（见 [`perf.md`](perf.md)）。Verify 只管两件事：代码能不能编译 + 计算结果对不对。

---

## 2. Mode 差异

无差异。两类模式都调算子仓自身构建系统编译 op_dir 内代码并验证，逻辑完全一致。

---

## 3. IO 契约

### 3.1 input_contract

```python
def input_contract(self) -> StageIOContract:
    return StageIOContract(
        requires=["adapter", "op_identity", "requirement", "npu_id"],
        optional=["generated_sources", "last_error", "chip_version", "skip_precision"]
    )
```

代码在算子仓内，编译走 `adapter.build`，因此 requires 是 `adapter` + `op_identity`，不依赖内存 `generated_sources`。

### 3.2 output_contract

```python
def output_contract(self) -> StageIOContract:
    return StageIOContract(
        provides=[
            "build_result",              # BuildResult (passed + artifacts)
            "precision_result",          # PrecisionResult (passed + max_diff)
            "verify_iterations",         # int: 实际迭代次数
        ]
    )
```

---

## 4. Gate

`CodegenCompleteGate`：codegen 已把代码留在算子仓——`op_identity` 存在且 op_dir 内有源文件。

---

## 5. Actions

```python
def actions(self, state: State, iteration: int) -> list[Action]:
    actions = [
        # 1. 调算子仓自身构建系统编译 op_dir 内代码
        RunGate(
            gate_name="build",
            gate=BuildInRepoGate(),
            evidence={
                "adapter": state.adapter,
                "op_identity": state.op_identity,
                "chip_version": state.chip_version,
            },
        ),
        # 2. 精度验证
        RunGate(
            gate_name="precision",
            evidence={
                "compiled_kernel": state.build_result.artifacts,
                "test_cases": state.requirement.test_cases,
                "npu_id": state.npu_id,
            },
        ),
    ]

    # 3. 如果有性能要求 → 交由 perf stage 处理（不在本 Stage 内）
    # Perf stage 会在 Verify 通过后执行
    return actions
```

---

## 6. Gate 实现

### BuildInRepoGate（共用）

与 finalize 共用，定义在 `orchestration/stages/gates.py`。调算子仓自身构建系统编译，复用仓内 aclnn/GEIR/pytorch 适配。

```python
class BuildInRepoGate(Gate):
    def evaluate(self, evidence: dict) -> GateResult:
        adapter = evidence["adapter"]
        op = evidence["op_identity"]
        result = adapter.build(
            repo_root=op.repo_root,
            op=op,
            chip_version=evidence.get("chip_version", "ascend910b"),
        )
        return GateResult(
            passed=result.passed,
            reason=result.stderr if not result.passed else "Build in repo passed",
            metrics={"stubbed": getattr(result, "stubbed", False)},
        )
```

### PrecisionGate

```python
class PrecisionGate(Gate):
    def evaluate(self, evidence: dict) -> GateResult:
        npu_runner = NPURunner.create()
        results = npu_runner.execute(
            compiled_kernel=evidence["compiled_kernel"],
            test_cases=evidence["test_cases"],
            npu_id=evidence["npu_id"],
        )
        return GateResult(
            passed=all(r.passed for r in results),
            reason=self._summarize(results),
            metrics={"max_diff": max(r.max_diff for r in results)},
        )
```

---

## 7. Agent 交互

无直接 Agent 调用。但 Gate 的评估结果（编译错误信息、精度 diff 值）作为 feedback 注入 codegen stage 的 Agent（在 self-healing loop 中）。

错误分类和 feedback 提取：
- 编译错误 → 提取：未定义符号名、错误行号、编译器错误信息
- 精度失败 → 提取：失败用例 index、期望值 vs 实际值、最大 diff

---

## 8. 错误分类

| 错误 | 类别 | 处理 |
|---|---|---|
| 编译失败 | Recoverable | 错误信息注入 codegen stage → Agent 修复 |
| 精度不达标（diff > threshold） | Recoverable | diff 信息注入 codegen stage → Agent 修复 |
| NPU 不可用 | Fatal | 退出码 78 |
| 测试用例格式错误 | Fatal | 退出码 65 |
| 编译超时 | Transient | 自动重试 |

---

## 9. 迭代行为

`max_iterations = 3`（可在 `resources/orchestration-config.json` 的 `iterations.stages.verify` 全局调整）。Verify 本身的迭代只处理 Transient 错误（重新编译/跑用例）。

Recoverable 错误（编译失败、精度失败）的修复迭代发生在 codegen stage——Verify 将错误信息作为 feedback 返回，L3 Runner 决定跳回 codegen stage 让 Agent 修复代码（`build_failed` / `precision_failed` → codegen，corrective 路由）。

**穷尽修复配额后停机（不回退 design）**：当 codegen↔verify 的 corrective 修复仍无法通过编译/精度，且达到迭代上限时，Verify 返回 `exhausted`，路由到终态 `__halt__`——**停机并报告，而不是自动跳回 design 重写设计**。理由：survive 了 codegen 修复配额的编译/精度失败，绝大多数是实现层 bug 而非设计缺陷；自动改写一个大概率正确的设计反而会扩大错误面。此时由人工判断根因（仅当确属设计问题时再手动从 design 重启）。停机会让 dispatcher 返回 `EX_DATAERR(65)` 并打印清晰提示，CI/调用方能据此识别"未交付"。

> 与 perf 的对比：性能问题才是真正与设计强相关的失败类，因此只有 `perf` 在穷尽战术调优后的 `redesign` 会升级回 design。

---

## 10. 事件 schema

```jsonl
{"ts":"...","type":"stage_enter","stage":"verify","stage_name":"verify"}
{"ts":"...","type":"action_start","action":"run_gate","gate":"build"}
{"ts":"...","type":"action_complete","action":"run_gate","gate":"build","result":"ok","elapsed_ms":45000}
{"ts":"...","type":"action_start","action":"run_gate","gate":"precision"}
{"ts":"...","type":"action_complete","action":"run_gate","gate":"precision","result":"ok","max_diff":1.2e-6}
{"ts":"...","type":"stage_complete","stage":"verify","elapsed_ms":120000}
```

---

## 11. 与邻 Stage 的关系

| 方向 | Stage | 传递数据 |
|---|---|---|
| 前置 | codegen | op_identity（代码在 op_dir 内） |
| 后置 | perf | build_result, precision_result |

---

## 附录：requirement.yaml — TestCase 字段说明

verify stage 独立运行时，通过 `--requirement` 注入测试用例。以下为 `requirement.yaml` 中 `test_cases` 和 `constraints`(precision) 的完整字段说明。

### 最小示例

```yaml
# requirement.yaml — verify stage 独立运行
constraints:
  - kind: precision
    threshold: 1e-5
    comparison: abs_diff

test_cases:
  - name: basic_fp16
    inputs:
      - name: input
        shape: [4]
        data: [1.0, 2.0, 0.0, -1.0]
    expected:
      max_diff: 1e-5
```

### test_cases 字段

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `name` | string | 是 | 用例名称，用于日志和报告 |
| `inputs` | list[dict] | 是 | 输入张量列表。每个元素含 `name`(str)、`shape`(list[int])、`data`(list[float]，仅非 generator 模式需要) |
| `expected` | dict | 否 | `{"max_diff": 1e-5}`——只做精度阈值比较，不逐值比对。不填则不验证精度 |
| `generator` | string | 否 | `"random_uniform"` / `"arange"`——数据生成器，设置后 `inputs[].data` 可省略 |
| `generator_params` | dict | 否 | 生成器参数，如 `{"seed": 42, "low": -1.0, "high": 1.0}` |

**generator 模式**：`generator` 设置后，inputs 只需声明 `name` + `shape`，不需要显式 `data`。PrecisionGate 在 NPU 上运行时自动生成随机数据，用于大 shape 的冒烟测试。

**显式 data 模式**：`generator` 为空时，每个 input 必须提供 `data` 数组。适用于精确比对的小用例。

### constraints 字段（precision）

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `kind` | string | 是 | 固定值 `"precision"` |
| `threshold` | float | 是 | 容忍的最大 diff。PrecisionGate 把每条 case 的 max_diff 与它比较 |
| `comparison` | string | 否 | `"abs_diff"`(默认) / `"cosine"` / `"relative"`——diff 的比较方式 |

### 完整示例

```yaml
constraints:
  - kind: precision
    threshold: 1e-5
    comparison: abs_diff

test_cases:
  # 显式数据：精确比对小用例
  - name: basic_fp16
    inputs:
      - name: input
        shape: [4]
        data: [1.0, 2.0, 0.0, -1.0]
    expected:
      max_diff: 1e-5

  # generator：大 shape 冒烟
  - name: random_large
    generator: random_uniform
    generator_params:
      seed: 42
      low: -1.0
      high: 1.0
    inputs:
      - name: input
        shape: [1024, 2048]
    expected:
      max_diff: 1e-5

  # 边界用例
  - name: edge_zero_input
    inputs:
      - name: input
        shape: [1]
        data: [0.0]
    expected:
      max_diff: 1e-6

  # 只跑编译不验精度
  - name: smoke_no_verify
    generator: arange
    inputs:
      - name: input
        shape: [512]
```
