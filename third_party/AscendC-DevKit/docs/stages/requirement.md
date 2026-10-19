
# Requirement — 需求分析

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §3 统一 Pipeline
> **实现状态**：已实现 ✓（自动注册, 由 GraphExecutor 经 AtomicStage 驱动）
> **位于 L3**: `orchestration/stages/requirement.py`

---

## 1. 定位

将详设文档（设计文档/变更文档）转化为结构化的需求规格。增量模式额外分析现状代码，提取不明确项并触发澄清循环。

---

## 2. Mode 差异

| 维度 | mode=new | mode=incremental |
|---|---|---|
| 输入 | 详设文档 | 详设文档 + 已有算子代码 + OperatorIdentity |
| 分析目标 | 完整算子设计 | 变更需求 (ChangeRequirement) |
| 不明确项 | 设计歧义 | 设计歧义 + 与现状代码的矛盾/缺失细节 |
| 产出 | Requirement | ChangeRequirement + 不明确项清单 |

---

## 3. IO 契约

### 3.1 input_contract

```python
def input_contract(self) -> StageIOContract:
    return StageIOContract(
        requires=["requirement_path", "mode"],
        optional=["op_identity", "reference_code", "design_doc_path"]
    )
```

### 3.2 output_contract

```python
def output_contract(self) -> StageIOContract:
    return StageIOContract(
        provides=[
            "requirement",               # Requirement 或 ChangeRequirement
            "unclear_items",             # 不明确项清单
            "requirement_clarified",     # bool: 是否所有不明确项均已澄清
        ]
    )
```

---

## 4. Gate

`gate() → None`（无条件进入）。

内部 sub-stage gate：`ClarificationCompleteGate`——所有不明确项标记为"已澄清"后才进入 Stage 的 action 产出步骤。

---

## 5. Actions

```python
def actions(self, state: State) -> list[Action]:
    actions = [
        # 1. 调用 Agent 分析详设文档
        SpawnAgent(
            agent_name="requirement-analyst",
            prompt=self._build_analysis_prompt(state),
            context={
                "design_doc": state.design_doc_content,
                "reference_code": state.reference_code,
                "mode": state.mode,
            },
        ),
    ]

    # 2. 如果不明确项清单非空 → 逐项澄清
    if state.unclear_items:
        for item in state.unclear_items:
            actions.append(
                AskUserQuestion(
                    question=item.question,
                    options=item.options,
                    default_index=item.default_index,
                )
            )

    # 3. 如果提供了参考算子 → 确认映射关系
    if state.reference_op_path:
        actions.append(
            SpawnAgent(
                agent_name="requirement-analyst",
                prompt=self._build_mapping_prompt(state),
                context={"reference_code": state.reference_code},
            )
        )

    return actions
```

---

## 6. Agent 交互

| Agent | 调用场景 | prompt 关键内容 |
|---|---|---|
| `requirement-analyst` | 分析详设文档，提取不明确项 | 详设全文 + 参考代码 + mode |
| `requirement-analyst` | 确认变更点到参考代码的映射 | 变更点清单 + 参考代码片段 |

---

## 7. 不明确项维度

Agent 分析时需覆盖的常见盲区：

| 维度 | 常见盲区 |
|---|---|
| 条件分支 | 对齐 vs 非对齐、可选输入有无、不同 dtype 处理 |
| 边界情况 | tail blocks、空 tensor、零长度维度、单元素输入 |
| 回退行为 | 可选输入缺失时的行为、属性不存在时的默认行为 |
| 并行策略 | 单核 vs 多核、分核策略、核间数据依赖 |
| 默认值 | 新增属性的默认值、新增配置项的初始值 |

---

## 8. 错误分类

| 错误 | 类别 | 处理 |
|---|---|---|
| 详设文档不存在 | Fatal | 退出码 65 |
| 文档格式无法解析 | Recoverable | Agent 重试（调整解析策略，max 2 iterations） |
| 不明确项存在 | User-input | AskUserQuestion 逐项澄清 |
| Agent 分析超时 | Transient | 自动重试 |
| 增量模式：现状代码与文档矛盾 | User-input | 提示用户确认以谁为准 |

---

## 9. 迭代行为

`max_iterations = 10`（代码默认；可在 `resources/orchestration-config.json` 的 `iterations.stages.requirement` 全局调整）。需求理解偏差通常 1-2 次澄清即可收敛；配额给得宽是为了让 agent 驱动的澄清有足够余量，正常情况远不会用满。多次迭代仍不收敛说明输入文档本身有问题，应提示用户修订文档而非继续迭代。

---

## 10. 事件 schema

```jsonl
{"ts":"...","type":"stage_enter","stage":"requirement","stage_name":"requirement"}
{"ts":"...","type":"action_start","action":"spawn_agent","agent":"requirement-analyst"}
{"ts":"...","type":"action_complete","action":"spawn_agent","result":"ok","unclear_items":3}
{"ts":"...","type":"action_start","action":"ask_user","question":"shape 不能被 tile_size 整除..."}
{"ts":"...","type":"action_complete","action":"ask_user","choice":1,"label":"添加 tail block 处理"}
{"ts":"...","type":"stage_complete","stage":"requirement","elapsed_ms":135000}
```

---

## 11. 与邻 Stage 的关系

| 方向 | Stage | 传递数据 |
|---|---|---|
| 前置 | context | profile, adapter, op_identity, reference_code |
| 后置 | design | requirement, unclear_items(已澄清), op_identity |
