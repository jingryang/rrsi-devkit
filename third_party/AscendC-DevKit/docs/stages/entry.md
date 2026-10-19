
# Entry — 入口解析

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §3 统一 Pipeline
> **实现状态**：已实现 ✓（自动注册, 由 GraphExecutor 经 AtomicStage 驱动）
> **位于 L3**: `orchestration/stages/entry.py`

---

## 1. 定位

解析 TaskRequest，确定本次运行的基本参数：mode（new/incremental）、workflow、目标仓、算子名。entry stage 是共用入口，两类模式逻辑完全一致。

---

## 2. Mode 差异

无差异。new 和 incremental 共用同一 Entry Stage。

---

## 3. IO 契约

### 3.1 input_contract

```python
def input_contract(self) -> StageIOContract:
    return StageIOContract(
        requires=["task_request"],      # TaskRequest (L1→L2→State)
        optional=[]
    )
```

### 3.2 output_contract

```python
def output_contract(self) -> StageIOContract:
    return StageIOContract(
        provides=[
            "mode",                     # "new" | "incremental"
            "workflow_name",            # 选定的 workflow
            "op_name",                  # 算子名
            "target_repo",              # 目标仓路径
            "repo_profile_name",        # 仓画像名称
            "requirement_path",         # 需求文档路径
            "npu_id",                   # NPU 卡 ID
            "non_interactive",          # 是否非交互模式
        ]
    )
```

---

## 4. Gate

无条件进入（`gate() → None`）。entry stage 是所有 workflow 的起点。

---

## 5. Actions

```python
def actions(self, state: State) -> list[Action]:
    return [
        # 解析 TaskRequest，提取运行参数
        ValidateInputs(
            checks=[
                "mode in ('new', 'incremental')",
                "target_repo exists and is a directory",
                "repo_profile exists in repository-profiles/",
                "if mode=='incremental': op_name is set",
                "if resume_run_id: events.jsonl exists and is readable",
            ]
        ),
        # 增量模式：验证目标算子存在于目标仓
        CheckOperatorExists() if state.mode == "incremental" else NoOp(),
    ]
```

---

## 6. Agent 交互

无。entry stage 是纯参数校验，不涉及 LLM 调用。

---

## 7. 错误分类

| 错误 | 类别 | 处理 |
|---|---|---|
| 无效 mode | Fatal | 退出码 64 |
| target_repo 不存在 | Fatal | 退出码 78 |
| profile 文件缺失 | Fatal | 退出码 78 |
| 增量模式缺少 op_name | Fatal | 退出码 64 |
| resume events 损坏 | Fatal | 退出码 65 |

---

## 8. 迭代行为

`max_iterations = 1`。entry stage 无 Recoverable 错误——参数校验失败是 Fatal。

---

## 9. 事件 schema

```jsonl
{"ts":"...","type":"stage_enter","stage":"entry","stage_name":"entry"}
{"ts":"...","type":"action_start","action":"validate_inputs"}
{"ts":"...","type":"action_complete","action":"validate_inputs","result":"ok"}
{"ts":"...","type":"stage_complete","stage":"entry","elapsed_ms":50}
```

---

## 10. 与邻 Stage 的关系

| 方向 | Stage | 传递数据 |
|---|---|---|
| 后置 | context | mode, op_name, target_repo, repo_profile_name |
