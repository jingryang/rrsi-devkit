
# Integrate — op_dir 校验与收尾

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §3 统一 Pipeline
> **实现状态**：已实现 ✓（自动注册, 由 GraphExecutor 经 AtomicStage 驱动）
> **位于 L3**: `orchestration/stages/integrate.py`

---

## 1. 定位

代码自 codegen 起已在算子仓 op_dir 内。Integrate 不做物化，只校验 op_dir 内文件齐备并记录收尾：扫描 op_dir 得到本算子的源文件清单作为 `target_files`，校验期望文件存在，产出 `integration_result`。

---

## 2. Mode 差异

无差异。new 与 incremental 共用同一路径——代码都已在 op_dir 内，integrate 统一做完整性校验 + 收尾。

---

## 3. IO 契约

### 3.1 input_contract

```python
def input_contract(self) -> StageIOContract:
    return StageIOContract(
        requires=["mode", "op_identity", "profile", "adapter"],
        optional=["generated_sources"],
    )
```

### 3.2 output_contract

```python
def output_contract(self) -> StageIOContract:
    return StageIOContract(
        provides=[
            "integration_result",       # {"status": "ok"|"error"|"skipped", "files": int}
            "target_files",             # 从 op_dir 读取的本算子源文件清单
        ]
    )
```

---

## 4. Gate

`VerifyCompleteGate`：verify stage 验证通过（编译 + 精度均 passed）。

---

## 5. Actions

```python
def actions(self, state: State, iteration: int = 1) -> list[Action]:
    # 不物化——校验/收尾在 transition() 内读取 op_dir 完成。
    # new 与 incremental 共用此路径。
    return [NoOp(reason="in-repo: integrate validates op_dir, no materialization")]
```

校验逻辑在 `transition()`：

```python
def transition(self, state: State, result: dict) -> State:
    op = state.op_identity
    op_dir = Path(op.op_dir)
    # 从 op_dir 读取本算子源文件（.cpp/.h/.hpp/.py）
    target_files = self._scan_op_dir(op_dir)
    # 期望文件完整性校验（复用 codegen 的 _expected_code_files）
    expected = CodegenStage._expected_code_files(state)
    missing = [f for f in expected if not (op_dir / f).is_file()]
    if missing:        # 缺文件 → integration_incomplete
        return self._fail(state, f"missing expected files: {missing}")
    return state.with_updates(
        integration_result={"status": "ok", "files": len(target_files)},
        target_files=target_files,
    )
```

---

## 6. Agent 交互

无直接 Agent 调用。

---

## 7. 错误分类

| 错误 | 类别 | 处理 |
|---|---|---|
| op_dir 不存在 | Recoverable | 记 `integration_incomplete` last_error |
| 期望文件缺失 | Recoverable | 记 `integration_incomplete`，列出缺失文件 |
| op_dir 内无源文件 | Recoverable | 记 `integration_incomplete` |
| 无 op_identity（纯设计交付） | skipped | `integration_result.status = "skipped"` |

---

## 8. 迭代行为

`max_iterations = 1`。校验失败记录 last_error，由 Runner 协调是否回到 codegen 修复。

---

## 9. 事件 schema

```jsonl
{"ts":"...","type":"stage_enter","stage":"integrate","stage_name":"integrate"}
{"ts":"...","type":"action_complete","action":"integrate","result":"ok","files":5}
{"ts":"...","type":"stage_complete","stage":"integrate","elapsed_ms":200}
```

---

## 10. 与邻 Stage 的关系

| 方向 | Stage | 传递数据 |
|---|---|---|
| 前置 | perf | build_result, precision_result |
| 后置 | finalize | target_files, integration_result |
