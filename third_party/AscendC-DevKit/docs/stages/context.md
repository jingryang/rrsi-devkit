
# Context — 上下文收集

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §3 统一 Pipeline
> **实现状态**：已实现 ✓（自动注册, 由 GraphExecutor 经 AtomicStage 驱动）
> **位于 L3**: `orchestration/stages/context.py`

---

## 1. 定位

加载 RepositoryProfile，初始化 RepositoryAdapter。新生成模式下 context 为空；增量模式下扫描目标仓中已有算子代码，构造 OperatorIdentity。进入写仓阶段前，在算子仓建立 git 基线快照，供失败回滚使用。

---

## 2. Mode 差异

| 维度 | mode=new | mode=incremental |
|---|---|---|
| 仓交互 | 仅加载 profile，不扫描代码 | 先询问定位方式，再定位已有算子代码 |
| 产出 | profile + adapter + 基线 | profile + adapter + OperatorIdentity + 基线 |
| 参考代码 | 可选（用户提供的参考算子路径） | 已有算子代码即参考 |
| 编译预检查 | 无（没有存量代码） | 可选：编译一次建立基线 |

增量模式下的代码定位有三种路径，优先级从高到低：

1. **CLI 已传入** `--reference-op-path <path>` → 直接用，跳过询问和扫描
2. **交互模式** → `AskUserQuestion` 让用户选择"自动搜索"或"手动指定路径"
3. **非交互模式** → 默认自动扫描（`--on-decision abort` 时直接报错退出）

这样既保证了 CLI 脚本的可自动化（非交互 + from-run），又保证了交互开发时的用户掌控感。

两种模式都在 op_identity 就绪后建立写仓前的 git 基线（见 §11）。

---

## 3. IO 契约

### 3.1 input_contract

```python
def input_contract(self) -> StageIOContract:
    return StageIOContract(
        requires=["mode", "op_name", "target_repo", "repo_profile_name", "non_interactive"],
        optional=[
            "reference_op_path",     # 用户通过 CLI 或交互直接指定的算子代码路径
            "code_source",           # "auto" | "manual" — 交互模式中用户的选择
        ]
    )
```

### 3.2 output_contract

```python
def output_contract(self) -> StageIOContract:
    return StageIOContract(
        provides=[
            "profile",                    # RepositoryProfile 实例
            "adapter",                    # RepositoryAdapter 实例
            "op_identity",                # OperatorIdentity (incremental only)
            "reference_code",             # 参考算子代码 (dict[str, str])
            "build_baseline",             # 基线编译结果 (incremental, optional)
            "repo_baseline_ref",          # 写仓前 git 基线 ref（有 target_repo 时）
        ]
    )
```

---

## 4. Gate

`gate() → None`（无条件进入）。

`ScanCompleteGate` 作为本 Stage 内部的 sub-stage gate：确保 `scan_existing_operator()` 找到了有效的算子代码再进入本 Stage 的后续步骤。

---

## 5. Actions

### mode=new

```python
def actions(self, state: State) -> list[Action]:
    return [
        LoadProfile(profile_name=state.repo_profile_name),
        InitAdapter(profile=state.profile, repo_root=state.target_repo),
        CollectReferenceCode(ref_path=state.reference_op_path),
    ]
```

### mode=incremental

```python
def actions(self, state: State, iteration: int) -> list[Action]:
    # 基础 actions：两个 iteration 都需要
    base = [
        LoadProfile(profile_name=state.repo_profile_name),
        InitAdapter(profile=state.profile, repo_root=state.target_repo),
    ]

    # 路径一：CLI 已传入路径 → 直接用
    if state.reference_op_path:
        return base + [
            ReadOperatorFromPath(path=state.reference_op_path),
        ]

    # 路径二：非交互模式 → 自动扫描
    if state.non_interactive:
        if state.on_decision == "abort":
            raise FatalError("非交互模式下必须提供 --reference-op-path")
        return base + self._scan_and_read(state)

    # 路径三：交互模式 → 先问用户
    if iteration == 1:
        return base + [
            AskUserQuestion(
                question=f"如何定位算子 '{state.op_name}' 的已有代码？",
                options=[
                    Option(label="自动搜索",
                           description=f"在 {state.target_repo} 中按 profile 约定搜索"),
                    Option(label="手动指定路径",
                           description="输入已有代码的目录路径"),
                ],
            ),
        ]

    # iteration == 2：根据用户选择执行
    if state.code_source == "manual":
        # 用户选择"手动指定路径"时，AskUserQuestion 的 Other 字段已收集路径
        return [
            ReadOperatorFromPath(path=state.manual_code_path),
        ]
    else:
        return self._scan_and_read(state)

def _scan_and_read(self, state: State) -> list[Action]:
    return [
        ScanExistingOperator(
            adapter=state.adapter,
            op_name=state.op_name,
            repo_root=state.target_repo,
        ),
        ReadOperatorCode(op_identity=state.op_identity),
        BuildBaseline(
            adapter=state.adapter,
            op=state.op_identity,
            chip_version=state.chip_version,
        ) if state.build_baseline_enabled else NoOp(),
    ]
```

---

## 6. Agent 交互

无。context stage 纯文件 I/O，不涉及 LLM 调用。

---

## 7. 错误分类

| 错误 | 类别 | 处理 |
|---|---|---|
| profile 文件不存在或格式错误 | Fatal | 退出码 78 |
| target_repo 路径不存在 | Fatal | 退出码 78 |
| 非交互模式且未提供 `--reference-op-path` | Fatal | 提示用户：非交互模式下必须显式指定路径 |
| 手动指定的路径不存在 | User-input | 提示用户重新输入路径 |
| 自动搜索：算子不在目标仓中 | Fatal | 提示用户检查 op_name |
| 自动搜索：算子目录存在但无源文件 | Fatal | 退出码 65 |
| 基线编译失败 | User-input | 提示用户：存量代码已有编译问题，是否先修复 |

---

## 8. 迭代行为

`max_iterations = 1`（mode=new）、`max_iterations = 2`（mode=incremental 交互模式）。

增量交互模式的两次迭代：
```
iteration 1: LoadProfile → InitAdapter → AskUserQuestion
  → 用户选择 "自动搜索" or "手动指定路径"
iteration 2: ScanExistingOperator + ReadOperatorCode + BuildBaseline
             或 ReadOperatorFromPath
```

非交互模式或 CLI 已传入 `--reference-op-path` 时，一次迭代完成所有动作。

---

## 9. 事件 schema

### mode=new / 非交互

```jsonl
{"ts":"...","type":"stage_enter","stage":"context","stage_name":"context"}
{"ts":"...","type":"action_start","action":"load_profile","profile":"omni-ops"}
{"ts":"...","type":"action_complete","action":"load_profile","result":"ok"}
{"ts":"...","type":"action_start","action":"init_adapter"}
{"ts":"...","type":"action_complete","action":"init_adapter","result":"ok"}
{"ts":"...","type":"stage_complete","stage":"context","elapsed_ms":500}
```

### mode=incremental 交互模式

```jsonl
{"ts":"...","type":"stage_enter","stage":"context","stage_name":"context"}
{"ts":"...","type":"iteration_start","stage":"context","iteration":1}
{"ts":"...","type":"action_start","action":"load_profile","profile":"omni-ops"}
{"ts":"...","type":"action_complete","action":"load_profile","result":"ok"}
{"ts":"...","type":"action_start","action":"init_adapter"}
{"ts":"...","type":"action_complete","action":"init_adapter","result":"ok"}
{"ts":"...","type":"action_start","action":"ask_user_question","question":"code_location"}
{"ts":"...","type":"action_complete","action":"ask_user_question","choice":"auto"}
{"ts":"...","type":"iteration_complete","stage":"context","iteration":1,"result":"ok"}
{"ts":"...","type":"iteration_start","stage":"context","iteration":2}
{"ts":"...","type":"action_start","action":"scan_existing_operator","op":"gelu"}
{"ts":"...","type":"action_complete","action":"scan_existing_operator","files":5}
{"ts":"...","type":"action_start","action":"read_operator_code"}
{"ts":"...","type":"action_complete","action":"read_operator_code","files":5}
{"ts":"...","type":"iteration_complete","stage":"context","iteration":2,"result":"ok"}
{"ts":"...","type":"stage_complete","stage":"context","total_iterations":2}
```

---

## 10. 与邻 Stage 的关系

| 方向 | Stage | 传递数据 |
|---|---|---|
| 前置 | entry | mode, op_name, target_repo, repo_profile_name |
| 后置 | requirement | profile, adapter, op_identity, reference_code, repo_baseline_ref |

---

## 11. 写仓前基线建立

codegen/verify/perf 直接在算子仓 op_dir 内改代码。Context 在 op_identity 就绪后、返回前，经 `RepoGuard` 建立写仓前的基线（写入 `repo_baseline_ref`），供失败回滚使用。

```
有 target_repo 且 op_identity 就绪
        │
        ├─ 前置干净校验 RepoGuard.is_clean(repo_root, op_dir)
        │     ├─ 干净 → 基线 = HEAD，回滚精确
        │     └─ 不干净 → 交互模式提示确认（回滚会波及未提交改动）；
        │                  非交互模式记 warn 继续
        │
        └─ RepoGuard.create_baseline(repo_root, op_dir)
              ├─ git 仓 → HEAD sha
              └─ 非 git 仓 → op_dir 文件备份，返回 filebackup:<path>
```

无 target_repo / 纯设计交付（SE workflow）跳过基线建立，`repo_baseline_ref` 为空。回滚策略由 dispatcher 各出口按结果分流：硬失败/超时自动回滚 op_dir，成功保留，主动中止保留改动并提示。
