# Codegen — 代码生成

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §3 统一 Pipeline
> **位于 L3**: `orchestration/stages/codegen.py`
> **实现状态**：已实现 ✓（自动注册, 由 GraphExecutor 经 AtomicStage 驱动）

---

## 1. 定位

将设计规格转化为可编译的 AscendC 代码。这是最常见的迭代 Stage——编译错误多轮修复发生在这里。

---

## 2. Mode 差异

| 维度 | mode=new | mode=incremental |
|---|---|---|
| 操作 | 在算子仓 op_dir 内新增/补齐源文件（Write） | 在算子仓 op_dir 内修改存量源文件（Edit），必要时 Write 新增 |
| Agent | `ascendc-coder` | `incremental-developer` |
| 文件生成策略 | 从零写全部算子文件 | 基于已有代码做最小改动 + 选择性新建 |
| 参考代码 | 用户提供的参考算子 | 目标仓中已有算子的完整代码 |

两类模式的 agent cwd 都是算子仓 op_dir，改动直接落在仓里。

---

## 3. IO 契约

### 3.1 input_contract

```python
def input_contract(self) -> StageIOContract:
    return StageIOContract(
        requires=["design_spec", "tiling_strategy", "kernel_architecture", "mode", "profile"],
        optional=["op_identity", "reference_code", "last_error"]
    )
```

### 3.2 output_contract

```python
def output_contract(self) -> StageIOContract:
    return StageIOContract(
        provides=[
            "generated_sources",         # dict[str, str] 本轮在 op_dir 内改动文件（相对路径 → 内容）
            "codegen_iterations",        # int: 实际迭代次数
        ]
    )
```

`generated_sources` 是本轮改动文件的视图（供上下文注入与报告），代码权威态在算子仓 op_dir 内。

---

## 4. Gate

`DesignCompleteGate`：设计规格已产出。

---

## 5. Actions

```python
def actions(self, state: State, iteration: int) -> list[Action]:
    prompt = self._build_codegen_prompt(state, iteration)
    # iteration=1 时不包含 last_error
    # iteration>=2 时 prompt 中包含上次编译/验证错误的 feedback
    agent_name = "ascendc-coder" if state.mode == "new" else "incremental-developer"
    skills = (["ascendc-translator", "ascendc-debug"] if state.mode == "new"
              else ["ascendc-debug"])

    return [
        SpawnAgent(
            agent_name=agent_name,
            prompt=prompt,
            context={
                "design_spec": state.design_spec,
                "tiling_strategy": state.tiling_strategy,
                "kernel_architecture": state.kernel_architecture,
                "reference_code": state.reference_code,
                "mode": state.mode,
            },
            skills=skills,
            # cwd = 算子仓 op_dir，agent 直接改仓；
            # repo_baseline/repo_root 供 backend 用 git diff 收集本轮改动
            working_dir=state.op_identity.op_dir if state.op_identity else None,
            repo_baseline=state.repo_baseline_ref or None,
            repo_root=state.op_identity.repo_root if state.op_identity else None,
        ),
    ]
```

prompt 要求 agent：当前工作目录即算子仓 op_dir，只动本算子相关文件，构建中间物不上报，完成后写 `changed_files.json`（相对 op_dir 路径 + 操作类型 created/modified/deleted）。

---

## 6. Agent 交互

| Agent | 关联 Skill | 用途 |
|---|---|---|
| `ascendc-coder` | `ascendc-translator`（API 翻译）、`ascendc-debug`（错误定位） | 全新生成算子代码 |
| `incremental-developer` | `ascendc-debug`（错误定位） | 在已有代码上生成 patch |

Agent 在 codegen stage 启动时读参考算子代码（由 context stage 传入的 `reference_code`），自学文件命名和代码风格——按照 `RepositoryProfile` 的约定不需要硬编码在 Python 里。

---

## 7. 编码规则（注入 Agent prompt）

- **保持现有风格**：遵循存量代码的命名规范、缩进风格
- **最小改动**（增量模式）：只改受影响的部分，原有逻辑保持不变
- **不动无关代码**：除非明确需要重构
- **禁止硬编码硬件参数**：UB 大小、核数等从 `ascend-hardware` 传入
- **TILING_KEY_IS 分支覆盖**：每个 TilingKey 值都有对应分支，禁止裸 `else`
- **32 字节对齐**：DataCopy、Vector ops 基地址 32 字节对齐

---

## 8. 错误分类

| 错误 | 类别 | 处理 |
|---|---|---|
| 编译错误（未定义符号、类型不匹配等） | Recoverable | Agent 自我修复，注入 feedback |
| 生成的代码使用了不存在的 API | Recoverable | Agent 查知识库修正 |
| Agent 生成了不完整的文件 | Recoverable | 注入 feedback，要求补充 |
| Agent 响应超时 | Transient | 自动重试 |
| 连续 5 次编译失败 | Fatal/User-input | 交互模式询问用户；非交互按 --on-decision |

---

## 9. 迭代行为

`max_iterations = 5`（代码默认；可在 `resources/orchestration-config.json` 的 `iterations.stages.codegen` 全局调整）。编译错误多轮修复是最常见的迭代场景。

```
iteration 1: 首次生成 → 编译失败
iteration 2: 修复编译错误 → 编译失败（新错误）
iteration 3: 修复新错误 → 编译通过
→ Stage 完成
```

每次迭代，`state.last_error` 被注入，Agent 的 prompt 中包含上次失败的反馈。因此 Agent 第二次调用时看到的上下文不同，能针对性地修复。

---

## 10. 事件 schema

```jsonl
{"ts":"...","type":"stage_enter","stage":"codegen","stage_name":"codegen"}
{"ts":"...","type":"iteration_start","stage":"codegen","iteration":1}
{"ts":"...","type":"action_start","action":"spawn_agent","agent":"ascendc-coder"}
{"ts":"...","type":"action_complete","action":"spawn_agent","result":"compile_error"}
{"ts":"...","type":"iteration_complete","stage":"codegen","iteration":1,"result":"recoverable_error"}
{"ts":"...","type":"iteration_start","stage":"codegen","iteration":2}
{"ts":"...","type":"action_start","action":"spawn_agent","agent":"ascendc-coder","context":"last_error=undefined symbol"}
{"ts":"...","type":"action_complete","action":"spawn_agent","result":"ok"}
{"ts":"...","type":"iteration_complete","stage":"codegen","iteration":2,"result":"ok"}
{"ts":"...","type":"stage_complete","stage":"codegen","total_iterations":2}
```

---

## 11. 与邻 Stage 的关系

| 方向 | Stage | 传递数据 |
|---|---|---|
| 前置 | design | design_spec, tiling_strategy, kernel_architecture |
| 后置 | verify | op_identity（代码已在 op_dir 内）, generated_sources（改动视图） |
