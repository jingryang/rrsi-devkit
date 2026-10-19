
# Finalize — 收尾

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §3 统一 Pipeline
> **实现状态**：已实现 ✓（自动注册, 由 GraphExecutor 经 AtomicStage 驱动）
> **位于 L3**: `orchestration/stages/finalize.py`

---

## 1. 定位

在目标仓内编译验证算子代码，生成最终报告。增量模式额外更新 `dev_record.md`。成功收尾保留算子仓内的代码改动，不自动 commit。

---

## 2. Mode 差异

| 维度 | mode=new | mode=incremental |
|---|---|---|
| 在目标仓编译 | `adapter.build()` | `adapter.build()`（共用） |
| dev_record | 不更新 | 更新 `dev_record.md` 记录变更 |

---

## 3. IO 契约

### 3.1 input_contract

```python
def input_contract(self) -> StageIOContract:
    return StageIOContract(
        requires=["target_files", "integration_result", "adapter", "op_identity", "mode", "workspace"],
        optional=["dev_record_path"]
    )
```

### 3.2 output_contract

```python
def output_contract(self) -> StageIOContract:
    return StageIOContract(
        provides=[
            "final_build_result",        # BuildResult (目标仓内编译)
            "report_generated",          # bool
            "dev_record_updated",        # bool (incremental only)
        ]
    )
```

---

## 4. Gate

`IntegrationCompleteGate`：integrate stage 校验通过（op_dir 文件齐备）。

---

## 5. Actions

```python
def actions(self, state: State) -> list[Action]:
    actions = [
        # 1. 在目标仓内编译算子代码（共用 BuildInRepoGate）
        RunGate(
            gate_name="build_in_repo",
            gate=BuildInRepoGate(),
            evidence={
                "adapter": state.adapter,
                "op_identity": state.op_identity,
                "chip_version": state.chip_version,
            },
        ),
    ]

    # 2. 增量模式：更新 dev_record.md
    if state.mode == "incremental":
        actions.append(
            UpdateDevRecord(
                path=state.dev_record_path,
                stage_status="finalize",
                requirement_path=state.requirement_path,
                change_summary=state.change_summary or "",
                target_files=state.target_files or [],
            )
        )

    # 3. 生成报告
    actions.append(
        GenerateReport(workspace=state.workspace)
    )

    return actions
```

成功收尾不自动 commit——代码改动保留在算子仓工作区，提交时机交给用户。

---

## 6. Agent 交互

无。finalize stage 是编译验证 + 报告生成 + 清理，不涉及 LLM 调用。

---

## 7. 错误分类

| 错误 | 类别 | 处理 |
|---|---|---|
| 目标仓编译失败 | Recoverable | 错误信息反馈（可能是 Integrate 步骤文件放错位置） |
| 报告生成失败（磁盘满等） | Fatal | 退出码 1 |
| dev_record 写入失败 | User-input | 警告用户，不影响退出码 |

---

## 8. 迭代行为

`max_iterations = 1`。编译失败异常再分析，但通常不需要迭代——如果 compile error 是因为文件放错位置，应回 integrate stage 修正（Integrate 和 Finalize 之间的迭代由 Runner 协调）。

---

## 9. 事件 schema

```jsonl
{"ts":"...","type":"stage_enter","stage":"finalize","stage_name":"finalize"}
{"ts":"...","type":"action_start","action":"run_gate","gate":"build_in_repo"}
{"ts":"...","type":"action_complete","action":"run_gate","gate":"build_in_repo","result":"ok"}
{"ts":"...","type":"action_start","action":"update_dev_record"}
{"ts":"...","type":"action_complete","action":"update_dev_record","result":"ok"}
{"ts":"...","type":"action_start","action":"generate_report"}
{"ts":"...","type":"action_complete","action":"generate_report","result":"ok"}
{"ts":"...","type":"stage_complete","stage":"finalize","elapsed_ms":60000}
{"ts":"...","type":"workflow_complete","workflow":"generate_ascendc","total_elapsed_ms":600000}
```

---

## 10. 后续路由

编译完成后，本 workflow 职责结束。后续可按需调用：

| 后续需求 | 调用资源 |
|---|---|
| 精度验证 / 跑测试 | `ascendc-testing` agent（Simple/ATK/TTK 三模式） |
| 精度问题排查 | `ascendc-dumptensor` skill |
| 性能分析 / 优化 | `ascendc-profiling` skill |
| PTA 接口适配 | `ascendc-pta` skill |

---

## 11. 问题迭代循环

如果后续测试/调试发现精度或性能问题，需要回到开发流程修改代码：

1. 将问题现象记录到 `dev_record.md`"迭代记录"章节
2. 回退到 requirement stage（需求澄清）——分析问题是否涉及需求理解偏差
3. 如果问题原因明确 → 可直接进入 design stage 进行修复
4. 修复后重新执行 verify stage → finalize stage
5. 所有迭代的修改和决策写回 `dev_record.md`

---

## 12. 与邻 Stage 的关系

| 方向 | Stage | 传递数据 |
|---|---|---|
| 前置 | integrate | target_files, integration_result |
| 后置 | — | 终态：final_build_result + report |
