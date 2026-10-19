# 51 — precision_debug 编排器根治：LLM 编排器 → 框架 CompositeGroup（L4 实施方案）

> 工作线：self-evolution / 批跑 20260715 非 429 问题收口
> 状态：**主干已实施（commit `588e248c`：删 LLM 编排器 → 框架 CompositeGroup + 4 子 stage，编排 UT 全绿）**；Phase 5 清理 + Phase 6（§12）+ 53 skill 拆分 由 L4 `54-precision-debug-skill-split-impl.md` 本次补齐。
> 关联 L3：`50-non429-issues-analysis.md` §1（疑似 10 双根因）+ §2.3（aggregate 600s ceiling 同源）
> 关联 L4：`54-precision-debug-skill-split-impl.md`（53 skill 拆分 + Phase 5/6 补齐）
> 上游 L1：`06-problems.md`（self-evolution 问题记录，疑似 10 事实见 `50-non429-issues-analysis.md`）

## 目录

1. [架构决策](#1-架构决策) — 为什么 CompositeGroup、为什么删除 LLM 编排器
2. [对标设计阶段](#2-对标设计阶段) — 精确对标现有模式，不自己发明
3. [文件改动清单](#3-文件改动清单) — 增/删/改哪些文件
4. [子 stage 详设](#4-子-stage-详设) — 每个子 stage 的 actions / transition / resolve_condition / loopback_feedback
5. [TRANSITION_TABLE](#5-transition_table) — 状态机编码
6. [State 字段](#6-state-字段) — `_debug_checkpoint` 定义
7. [checkpoint.json 归属](#7-checkpointjson-归属) — 文件接力 vs State 的边界
8. [A5 路径](#8-a5-路径) — A5 RegBase 同法改造
9. [实施顺序](#9-实施顺序) — TDD 步骤
10. [验证](#10-验证)
11. [不改 / 关键边界](#11-不改--关键边界)
12. [正交增强：scope guard + harness 新鲜度](#12-正交增强scope-guard--harness-新鲜度) — additive，源自被否决 proposal 的独立价值

---

## 1. 架构决策

### 问题

`PrecisionDebugStage` 产出一个 `SpawnAgent(agent_name="ascendc-precision-debugger")`，该 LLM agent 内部做 checkpoint-driven 循环：读 checkpoint → stage-transition.py → Agent(run_tests) → Agent(diagnose) → ... → 循环。编排逻辑在 LLM 里，框架只看到一个 SpawnAgent。

SDK 的 Agent 工具是异步/后台派发（tool_result = "Async agent launched successfully"），编排器 prompt 设计的是同步 LOOP（dispatch → sub-agent returns → verify）。失配导致：
- 编排器 dispatch 后空转 ~30 turn 等通知（每轮 ~30 turn × 7 轮 dispatch ≈ 210 turn）
- 空转期漂移到违规自己做调试（实测 100 次 Bash 里有 17 次 inline python 自检）
- context 膨胀到 251K chars → halt
- 600s BG-wait ceiling 杀 aggregate session（与 async 派发同源）

### 决策（用户拍板）

**用框架 CompositeGroup + 子 stage 模式替换单一的 PrecisionDebugStage + LLM 编排器。**

| 组件 | 现状 | 改造后 |
|------|------|--------|
| `PrecisionDebugStage` | 单一原子 stage | **删除**，替换为 CompositeGroup |
| `ascendc-precision-debugger` agent | LLM 编排器，内部 loop | **删除**（§2.5） |
| `ascendc-precision-debugger-a5` agent | A5 LLM 编排器 | **删除**（同法改造） |
| 4 个 phase 子 agent | 被 LLM 编排器 Agent() 派发 | **保留**，由框架 SpawnAgent 直接派发 |
| `stage-transition.py` | 外部脚本，LLM 编排器调用 | **删除**，逻辑内联到各子 stage 的 `resolve_condition()` |
| `checkpoint.json` | LLM 编排器读/写，子 agent 读/写 | **保留**为子 agent 间文件接力（§2.3）；路由字段经 `transition()` 提取到 State |
| 编排权 | LLM agent | **框架 GraphExecutor**（唯一编排器，§1.1） |

### 收益

- **根治 async/sync 失配**：框架用同步 `spawn → wait → transition`，不依赖 Agent 工具的异步通知。每次 `SpawnAgent` 后框架等待 `query()` 返回再推进。
- **根治 context 膨胀**：每轮一个独立 agent 会话，context 不跨轮累积。
- **根治 600s BG-wait ceiling**：不依赖后台任务等待，不触发 CLI 的 BG-wait 超时。
- **§2.5 对齐**：消灭 LLM 编排器这条通路，框架是唯一编排者。
- **§1.1 对齐**：`Stage.actions(state, iteration) → list[Action]`、`Stage.transition(state, result) → State` 标准入口。

---

## 2. 对标设计阶段

本方案精确对标 `design_tree.py` + `design_substages.py` 的现有模式，不自己发明任何机制。

### 2.1 路由 State 字段

对标 `state.anchor_report` / `state.validation_report` —— agent 写文件，transition() 解析后写入 State，resolve_condition() 读 State。

```python
# AnchorConsistencyStage (对标参考)
def transition(self, state, result):
    raw, _ = self._read_disk_artifacts(state, result, ["anchor_report.json"])
    parsed = json.loads(raw["anchor_report.json"])
    return state.with_updates(anchor_report=parsed)   # ← agent 文件 → State

def resolve_condition(self, state) -> str:
    mapping = {"tiling": "infeasible", "integrate": "advisory_integrate"}
    return _route_from_issues(
        state.anchor_report.get("blocking_issues", []),  # ← 读 State
        mapping
    )
```

precision_debug 对标：

```python
# RunTestsSubstage (对标实现)
def transition(self, state, result):
    cp = _load_checkpoint(state)                           # 读 agent 文件
    return state.with_updates(_debug_checkpoint={          # → State 字段
        "status": cp["status"],
        "current_iteration": cp.get("current_iteration", 1),
        "max_iterations": cp.get("max_iterations", 30),
        "failed_case_count": len(cp.get("failed_case_queue", [])),
        ...
    })

def resolve_condition(self, state) -> str:
    dc = state._debug_checkpoint or {}                     # ← 读 State
    if dc["status"] == "passed":      return "all_pass"
    if dc["iteration"] > dc["max"]:   return "exhausted"
    return "has_failures"
```

### 2.2 Loopback/Feedback

对标 `AnchorConsistencyStage.loopback_feedback()` —— gate 子 stage 从 State 返回结构化反馈，GraphExecutor 注入 `state._loopback_feedback`，目标 stage 的 `_build_prompt()` 读它注入提示。

```python
# 对标: ValidateStage
def loopback_feedback(self, state) -> dict | None:
    issues = state.validation_report.get("blocking_issues", [])
    return {"blocking_issues": issues} if issues else None

# precision_debug 对标:
class FixSubstage(Stage):
    def loopback_feedback(self, state) -> dict | None:
        """当 fix→run_tests 时，把修复摘要传递给 run_tests 子 agent。"""
        dc = state._debug_checkpoint or {}
        return {"fix_applied": dc.get("fix_applied", ""),
                "best_commit": dc.get("best_commit", "")}
```

### 2.3 TRANSITION_TABLE + CompositeGroup

对标 `build_detailed_design_group()` —— CompositeGroup + scoped transition_table + `max_corrective` 配额。

```python
# 对标: design_tree.py
def build_detailed_design_group() -> CompositeGroup:
    return CompositeGroup(
        name="detailed-design",
        children=[AtomicStage(...), ...],
        transition_table=_DETAILED_DESIGN_TRANSITION_TABLE,
        max_corrective=quota["max_corrective"],
    )

# precision_debug 对标:
def build_precision_debug_group(max_rounds: int) -> CompositeGroup:
    return CompositeGroup(
        name="precision_debug",
        children=[
            AtomicStage(RunTestsSubstage()),
            AtomicStage(DiagnoseSubstage()),
            AtomicStage(FixSubstage()),
            AtomicStage(PrintfLocateSubstage()),
        ],
        transition_table=_PRECISION_DEBUG_TRANSITION_TABLE,
        max_corrective=max_rounds,
    )
```

---

## 3. 文件改动清单

```
新增:
  src/ascendc_devkit/orchestration/stages/precision_debug_substages.py  # 4 个 phase 子 stage（+ §12.1 scope guard 子 stage）；§12.2 契约校验在 _load_checkpoint 内
  src/ascendc_devkit/orchestration/precision_debug_tree.py              # CompositeGroup builder
  .claude/agents/ascendc-precision-scope-guard.md                       # §12.1 入口守卫 agent（轻量、单次）

修改:
  src/ascendc_devkit/orchestration/stages/precision_debug.py            # 删 PrecisionDebugStage，
                                                                        #   保留 run_precision_cases()、
                                                                        #   DEBUG_RESULT_CONTRACT；
                                                                        #   try_load_cannbench_task() 暂留
                                                                        #   （step-40 落地后删除，见 §13）
  src/ascendc_devkit/orchestration/workflow.py                          # 用 build_precision_debug_group()
                                                                        #   替换 AtomicStage(PrecisionDebugStage())
  src/ascendc_devkit/orchestration/kernel/state.py                      # 新增 _debug_checkpoint 字段
  tests/ut/orchestration/test_precision_debug_stage.py                  # 重写为子 stage UT

删除:
  .claude/agents/ascendc-precision-debugger.md                          # LLM 编排器 agent
  .claude/agents/ascendc-precision-debugger-a5.md                       # A5 LLM 编排器 agent
  .claude/plugins/stage-precision-debug/skills/ascendc-precision-debug/scripts/stage-transition.py
                                                                        # 外部状态机脚本

不变（保留）:
  .claude/agents/ascendc-precision-run-tests.md                         # 4 个 phase 子 agent 全部保留
  .claude/agents/ascendc-precision-diagnose.md
  .claude/agents/ascendc-precision-fix.md
  .claude/agents/ascendc-precision-printf-locate.md
  .claude/plugins/stage-precision-debug/skills/ascendc-precision-debug/scripts/init-checkpoint.py
  .claude/plugins/stage-precision-debug/skills/ascendc-precision-debug/scripts/verify-checkpoint.py
  .claude/plugins/stage-precision-debug/skills/ascendc-precision-debug/scripts/write-debug-result.py
  .claude/plugins/stage-precision-debug/skills/ascendc-precision-debug/scripts/build-failed-case-queue.py
  .claude/plugins/stage-precision-debug/skills/ascendc-precision-debug/rules/{main-loop,checkpoint-spec}.md
  .claude/plugins/stage-precision-debug/skills/ascendc-precision-debug/references/prompts/{run_tests,diagnose,fix,printf_location}.md
```

`precision_debug.py` 瘦身为**纯能力模块**：保留 `run_precision_cases()`（NPU 执行）、`DEBUG_RESULT_CONTRACT`（契约常量）、`try_load_cannbench_task()`（用例加载，**暂留**——step-40 测试执行外部化落地时删除，见 §13）。删除 `PrecisionDebugStage` 类（stage 逻辑）、`_build_prompt()` / `_build_a5_prompt()`（prompt 拼装）、`_actions_legacy()` / `_actions_a5()`（编排派发）。

> **`run_precision_cases()` 是 P0 与 step-40 的接口点**：P0 的 run_tests 子 stage 调用它做判定，**只调接口、不绑内部实现**。step-40 会把其内部从"内化 runner + cann-bench 模块"换为 `EvaluationBackend.run()` 抽象——这一替换对 P0 的 run_tests 子 stage **透明**（接口签名不变）。故 P0 设计 run_tests 子 stage 时，保持"调用 `run_precision_cases()`"而非内联执行逻辑，给 step-40 留干净的替换面。

---

## 4. 子 stage 详设

每个子 stage 对标 `design_substages.py` 的模式：读 checkpoint.json → 更新 State → resolve_condition 读 State。

### 4.0 共享基础

```python
# precision_debug_substages.py

def _load_checkpoint(state: State) -> dict:
    """从 op_dir 读取 checkpoint.json。文件接力（§2.3）——子 agent 写，框架读。"""
    op_dir = state.op_dir or (state.op_identity.op_dir if state.op_identity else None)
    cp_path = op_dir / ".precision-fix" / "checkpoint.json"
    return json.loads(cp_path.read_text()) if cp_path.exists() else {}

def _save_checkpoint(state: State, cp: dict) -> None:
    """写回 checkpoint.json。"""
    op_dir = state.op_dir or (state.op_identity.op_dir if state.op_identity else None)
    cp_path = op_dir / ".precision-fix" / "checkpoint.json"
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    cp_path.write_text(json.dumps(cp, indent=2, ensure_ascii=False))

def _extract_debug_checkpoint(cp: dict) -> dict:
    """从 checkpoint.json 提取框架路由所需的最小字段集。

    对标 design 子 stage 的 transition() 从 agent 文件提取结构化字段到 State。
    只提取路由/loopback 需要的字段；详细数据（failed_case_queue、candidate_pool
    等）留在 checkpoint.json 中由子 agent 直接读/写。
    """
    return {
        "status": cp.get("status", "running"),
        "current_stage": cp.get("current_stage", "run_tests"),
        "current_iteration": cp.get("current_iteration", 1),
        "max_iterations": cp.get("max_iterations", 30),
        "best_commit": cp.get("best_commit", ""),
        "best_max_err": cp.get("best_max_err", 0.0),
        "best_failed_count": cp.get("best_failed_count", 0),
        "failed_case_count": len(cp.get("failed_case_queue", [])),
        "diagnose_done": cp.get("diagnose_done", False),
        "debug_state": cp.get("debug_state", "fresh"),
        "printf_location_result": cp.get("printf_location_result"),
        "failure_type": _get_current_failure_type(cp),
        "case_resolved": _current_case_resolved(cp),
        "pool_exhausted": _candidate_pool_exhausted(cp),
    }
```

### 4.1 RunTestsSubstage

```python
class RunTestsSubstage(Stage):
    """Phase 子 stage：执行测试套件，解析结果。
    
    对标：_DesignSubstage —— 一个 SpawnAgent + 文件→State transition。
    """
    name = "run_tests"
    fail_strategy = "continue"  # 由 TRANSITION_TABLE 路由，不 halt

    def actions(self, state, iteration):
        op_dir = state.op_dir or (state.op_identity.op_dir if state.op_identity else None)
        return [SpawnAgent(
            agent_name="ascendc-precision-run-tests",
            prompt=self._build_prompt(state, iteration),
            working_dir=op_dir,
            stage_name=self.name,
        )]

    def transition(self, state, result):
        cp = _load_checkpoint(state)
        # 子 agent 已更新 checkpoint.json（写 failed_case_queue / history / status 等）
        return state.with_updates(
            _debug_checkpoint=_extract_debug_checkpoint(cp))

    def resolve_condition(self, state) -> str:
        dc = state._debug_checkpoint or {}
        if dc["status"] == "passed":
            return "all_pass"
        if dc["current_iteration"] > dc["max_iterations"]:
            return "exhausted"
        return "has_failures"
```

### 4.2 DiagnoseSubstage

```python
class DiagnoseSubstage(Stage):
    name = "diagnose"
    fail_strategy = "continue"

    def actions(self, state, iteration): ...
    def transition(self, state, result): ...
        # 子 agent 更新 checkpoint.json（candidate_pool / diagnose_done）
    def resolve_condition(self, state) -> str:
        dc = state._debug_checkpoint or {}
        if dc["current_iteration"] > dc["max_iterations"]:
            return "exhausted"
        return "done"

    def loopback_feedback(self, state) -> dict | None:
        """将诊断结果传递给 FixSubstage。"""
        dc = state._debug_checkpoint or {}
        return {"failure_type": dc.get("failure_type", ""),
                "failed_case_count": dc.get("failed_case_count", 0)}
```

### 4.3 FixSubstage

```python
class FixSubstage(Stage):
    name = "fix"
    fail_strategy = "continue"

    def actions(self, state, iteration): ...
    def transition(self, state, result): ...
        # 子 agent 更新 checkpoint.json（fix_code_log / debug_state / best_commit）

    def resolve_condition(self, state) -> str:
        dc = state._debug_checkpoint or {}
        if dc["case_resolved"]:
            return "case_resolved"
        if dc["pool_exhausted"]:
            if dc["failure_type"] in ("compilation", "runtime"):
                return "pool_exhausted_nobisect"
            return "pool_exhausted"
        return "retry"

    def loopback_feedback(self, state) -> dict | None:
        """当 fix→run_tests 时，把修复信息传递给回归测试。"""
        dc = state._debug_checkpoint or {}
        return {"best_commit": dc.get("best_commit", ""),
                "best_max_err": dc.get("best_max_err", 0.0)}
```

### 4.4 PrintfLocateSubstage

```python
class PrintfLocateSubstage(Stage):
    name = "printf_location"
    fail_strategy = "continue"

    def actions(self, state, iteration): ...
    def transition(self, state, result): ...
        # 子 agent 更新 checkpoint.json（printf_location_result / debug_state）

    def resolve_condition(self, state) -> str:
        dc = state._debug_checkpoint or {}
        result = dc.get("printf_location_result")
        if result == "located":    return "located"
        if result == "exhausted":  return "exhausted"
        return "continue"

    def loopback_feedback(self, state) -> dict | None:
        """当 printf→fix 时，把定位信息传递给修复阶段。"""
        dc = state._debug_checkpoint or {}
        return {"printf_located": dc.get("printf_location_result") == "located"}
```

---

## 5. TRANSITION_TABLE

对标 `_DETAILED_DESIGN_TRANSITION_TABLE`，编码 stage-transition.py 的完整状态机：

```python
_PRECISION_DEBUG_TRANSITION_TABLE: dict = {
    "run_tests": {
        "all_pass":    ("__halt__", "completion"),       # 全部通过 → 组成功退出
        "exhausted":   ("__halt__", "completion"),       # 轮数耗尽 → 组退出（best_commit 已记录）
        "has_failures": ("diagnose", "corrective"),       # 有失败 → 诊断
    },
    "diagnose": {
        "done":        ("fix", "default"),                # 诊断完成 → 修复
        "exhausted":   ("__halt__", "completion"),        # 轮数耗尽 → 退出
    },
    "fix": {
        "case_resolved":       ("run_tests", "corrective"),   # 修好一个 → 回归验证
        "pool_exhausted":      ("printf_location", "corrective"),  # 候选池耗尽 → printf 二分
        "pool_exhausted_nobisect": ("run_tests", "corrective"),  # 编译/运行错误，跳过当前用例
        "retry":               ("fix", "corrective"),       # 继续试下一个 fix_plan
    },
    "printf_location": {
        "located":   ("fix", "corrective"),                # 定位到 → 回去修
        "exhausted": ("run_tests", "corrective"),          # 无法定位 → 跳过当前用例
        "continue":  ("printf_location", "corrective"),    # 继续插桩
    },
}
```

CompositeGroup 构建：

```python
# precision_debug_tree.py

def build_precision_debug_group(max_rounds: int = 30) -> CompositeGroup:
    from ascendc_devkit.orchestration.stages.precision_debug_substages import (
        RunTestsSubstage, DiagnoseSubstage, FixSubstage, PrintfLocateSubstage,
    )
    return CompositeGroup(
        name="precision_debug",
        children=[
            AtomicStage(RunTestsSubstage()),
            AtomicStage(DiagnoseSubstage()),
            AtomicStage(FixSubstage()),
            AtomicStage(PrintfLocateSubstage()),
        ],
        transition_table=_PRECISION_DEBUG_TRANSITION_TABLE,
        output_contract_override=StageIOContract(
            provides=["debug_result", "debug_iterations"]),
        max_corrective=max_rounds,
    )
```

`max_corrective=max_rounds` 控制总的 corrective loopback 次数，等同于原来的 `_max_rounds`（agent 内循环轮数）。框架在每次 corrective 边触发时递增计数器，达到上限后不再 loopback。

### 5.1 group 对外路由（反查 graph_executor 发现的机制，已解决）

`graph_executor._resolve_condition` 对 `SequentialGroup`（CompositeGroup）**恒返回 "default"**（不像 AtomicStage 转发给 stage）。precision_debug 从 AtomicStage（现状 `resolve_condition` 返回 default/exhausted）变 CompositeGroup 后，"未通过→exhausted→cannbench_adapt 软门"路由看似丢失。

**反查结论：功能等价，无需改 `_resolve_condition`**：
- `cannbench_adapt.input_contract.requires = ["generated_sources", "codegen_manifest", "repo_root"]`——**不读 debug_result**，不区分上游 passed/exhausted，总是跑
- 故 group 对外恒 default → 线性 → cannbench_adapt，与现状 exhausted 软门**功能等价**（cannbench_adapt 反正都跑）
- 组内"通过/止损"用 `__halt__ completion` 退出（§5 TRANSITION_TABLE 的 all_pass/exhausted → `("__halt__", "completion")`），组完成后 root 线性推进
- root `TRANSITION_TABLE["precision_debug"]["exhausted"]` 条目：group 不再触发 exhausted，**该条目失效可删**（保留亦无害，不会被触发）

**落地**：P0 编码时在 `SelfEvolveOpWorkflow.TRANSITION_TABLE` 删除 `"precision_debug": {"exhausted": ...}` 条目（group 化后由 default 线性接管）。`generate_ascendc` 同理（若其 TRANSITION_TABLE 有 precision_debug 条目）。

---

## 6. State 字段

### `state._debug_checkpoint: dict | None`

```python
# state.py 新增字段
_debug_checkpoint: dict | None = None
# transition() 从 checkpoint.json 提取的只读快照。包含：
# {
#   "status": str,               # "running" | "passed"
#   "current_iteration": int,    # 当前循环轮数
#   "max_iterations": int,       # 轮数上限
#   "best_commit": str,          # 最佳 commit sha
#   "best_max_err": float,       # 最小 max_diff
#   "best_failed_count": int,    # 最少失败数
#   "failed_case_count": int,    # 当前失败用例数
#   "diagnose_done": bool,       # 诊断是否完成
#   "debug_state": str,          # "fresh" | "bisecting" | "exhausted"
#   "printf_location_result": str | None,  # "located" | "exhausted" | "continue"
#   "failure_type": str | None,  # "compilation" | "runtime" | "precision" | None
#   "case_resolved": bool,       # 当前用例是否已修复
#   "pool_exhausted": bool,      # candidate_pool 是否耗尽
# }
```

对标 `state.anchor_report` / `state.validation_report`：agent 写文件 → transition() 提取到 State → resolve_condition() 读 State。`_debug_checkpoint` 不进 events payload（瞬态，类似 `_loopback_feedback`），但 resolve_condition 的返回值会写入 events.jsonl。

### `state.debug_result` / `state.debug_iterations`

已有字段，保持不变。在 finalize 子 stage（或组退出时的过渡处理）写入。

### 正交增强字段（§12）

`scope_checked` / `scope_verdict` / `upstream_stage` / `scope_reason`（§12.1）以只读快照形式经 `_debug_checkpoint` 中转，详见 §12。§12.2（加载期契约校验）不新增 State 字段——不符即报错，不落路由数据。

---

## 7. checkpoint.json 归属

```
checkpoint.json 全部字段分为两类：

A 类（子 agent 操作数据 —— 保留在 checkpoint.json）:
  ├── failed_case_queue          ← run_tests 写，所有子 agent 读
  ├── candidate_pool             ← diagnose 写，fix/printf 读
  ├── current_case / current_case_index
  ├── history[]                  ← run_tests 写
  ├── fix_code_log               ← fix 写
  ├── build_command / test_command / compile_work_dir
  └── last_updated

B 类（框架路由数据 —— 经 State 中转）:
  ├── status                     → _debug_checkpoint["status"]
  ├── current_stage              → _debug_checkpoint["current_stage"]
  ├── current_iteration          → _debug_checkpoint["current_iteration"]
  ├── max_iterations             → _debug_checkpoint["max_iterations"]
  ├── best_commit / best_max_err → _debug_checkpoint["best_*"]
  ├── debug_state               → _debug_checkpoint["debug_state"]
  ├── printf_location_result    → _debug_checkpoint["printf_location_result"]
  ├── diagnose_done             → _debug_checkpoint["diagnose_done"]
  └── scope_checked / scope_verdict / upstream_stage / scope_reason   # §12.1（§12.2 不落字段，加载期报错）
```

边界规则：
- **checkpoint.json 是 A 类 + B 类的唯一权威源**。子 agent 只读写 checkpoint.json，不知道 State 的存在（§2.1）。
- **State `_debug_checkpoint` 是 B 类的只读派生视图**。`transition()` 从 checkpoint.json 提取，`resolve_condition()` / `loopback_feedback()` 读 State。
- **`_build_prompt()` 从 State 读取 `_loopback_feedback`** 注入 `## 上次反馈` 段——对标 `_DesignSubstage._feedback_section()` 读 `state._loopback_feedback`。

---

## 8. A5 路径

A5 RegBase 的 `ascendc-precision-debugger-a5` agent 同法改造。A5 状态机阶段不同（pipeline_sync → dump_debug → vf_test(条件) → finalize），但改造模式一致：

```
新增:
  src/ascendc_devkit/orchestration/precision_debug_a5_tree.py
  src/ascendc_devkit/orchestration/stages/precision_debug_a5_substages.py
    - PipelineSyncSubstage    → SpawnAgent("ascendc-pipeline-sync-debug")
    - DumpDebugSubstage       → SpawnAgent("ascendc-precision-dump-debug")
    - VFTestSubstage          → SpawnAgent("ascendc-precision-vf-debug")  # 条件触发
    - FinalizeSubstage        → 写 debug_result.json + 恢复 double buffer

删除:
  .claude/agents/ascendc-precision-debugger-a5.md
```

A5 路径的详设在独立 L4 文档中展开，本 L4 只覆盖 A2/A3（现有路径）。实施时先做 A2/A3，验证通过后再做 A5。

---

## 9. 实施顺序

### Phase 1：precision_debug_substages.py + precision_debug_tree.py

1. 新建 `precision_debug_substages.py`：4 个子 stage 类 + `_load_checkpoint` / `_extract_debug_checkpoint`。
2. 新建 `precision_debug_tree.py`：`build_precision_debug_group(max_rounds)` + `_PRECISION_DEBUG_TRANSITION_TABLE`。
3. `state.py` 新增 `_debug_checkpoint: dict | None = None`。

### Phase 2：接入 workflow

4. `workflow.py`：将 `AtomicStage(PrecisionDebugStage())` 替换为 `build_precision_debug_group(max_rounds)`。
5. `precision_debug.py`：删除 `PrecisionDebugStage` 类、`_build_prompt()`、`_build_a5_prompt()`、`_actions_legacy()`、`_actions_a5()`。保留 `run_precision_cases()`、`try_load_cannbench_task()`、`DEBUG_RESULT_CONTRACT`。

### Phase 3：删除旧通路（§2.5）

6. 删除 `ascendc-precision-debugger.md` agent。
7. 删除 `stage-transition.py` 外部脚本。
8. 删除 `ascendc-precision-debugger-a5.md` agent。

### Phase 4：TDD（§3.1）

9. 重写 `tests/ut/orchestration/test_precision_debug_stage.py`：覆盖 4 个子 stage 的 transition + resolve_condition + loopback_feedback，以及 TRANSITION_TABLE 路由正确性。
10. 全量 UT + 非 heavy ST 回归。
11. A5 子 stage UT + 回归。

### Phase 5：清理

12. 删除 `SKILL.md`（ascendc-precision-debug 启动器）中的 orchestrator 派发逻辑——该 skill 不再需要（编排由框架完成，不经过 TUI 启动器）。
13. 清理 `main-loop.py` 等 orchestrator 相关脚本中对 `ascendc-precision-debugger` agent 的引用。

### Phase 6：正交增强（§12，主干验证通过后；additive，可降级）

14. `precision_debug_substages.py` 增 `ScopeGuardSubstage`（§12.1）；在 `_load_checkpoint` / harness 加载边界加契约校验（§12.2，不符即报错、不重生）；`precision_debug_tree.py` 接入 scope guard 的 children 与 TRANSITION_TABLE。
15. 新增 `.claude/agents/ascendc-precision-scope-guard.md`。
16. `init-checkpoint.py` 增 `scope_checked: false` 初值；`verify-checkpoint.py` 把「校验不符 → 报错」做实（不做兼容兜底/迁移）。

---

## 10. 验证

- **UT**：`test_precision_debug_stage.py` 重写（子 stage transition + resolve_condition + TRANSITION_TABLE 路由），`test_graph_executor.py`（CompositeGroup loopback 正确性），`test_workflow.py`（workflow 接入正确）。
- **ST（非 heavy）**：全量非 heavy ST 回归，确保编排改动不破坏既有流程，特别是 `test_self_evolution_stages.py`。
- **heavy_llm（§3.11）**：真实 precision_debug 全流程（含 NPU）验证框架编排生效——子 agent 正常派发、checkpoint.json 读写正确、loopback 收敛、debug_result.json 产出正确。**交付前用户决策跑一次**。

---

## 11. 不改 / 关键边界

- **算子核心代码**：零改动。
- **4 个 phase 子 agent**：零改动。它们的输入/输出契约（checkpoint.json）完全不变。
- **checkpoint.json schema**：零改动。`decide_next_stage()` 的逻辑分散到 resolve_condition 后，checkpoint.json 的字段集不变，只是 `current_stage` 字段不再由外部脚本写回（改由框架 TRANSITION_TABLE 驱动状态推进）。
- **`run_precision_cases()` / `DEBUG_RESULT_CONTRACT`**：保留不动。`run_precision_cases()` 是 P0 与 step-40 的接口点（见 §13），P0 只调接口不绑内部。
- **`try_load_cannbench_task()`**：P0 **暂留**（不删），step-40 落地时删除（它是 step-40 要外部化的 `task_loader` 目录嗅探的调用者，见 §13）。P0 不动它，避免与 step-40 的执行层改造抢改同一函数。
- **子 agent 的 `SKILL.md` 和 rules/ 目录**：保留不动。
- **SDK backend**：不改。框架同步 spawn→wait→transition 是现有机制，不需 foreground 开关。

---

## 12. 正交增强：scope guard + 产物加载期契约校验

> 本节是 §1–§11 主干之外的**两项正交增强**（scope guard + 加载期契约校验），二者与编排重构**正交**：可独立立项、独立验证、可降级（不阻塞主干交付）。落地配方见 L4 `54-precision-debug-skill-split-impl.md` Stage 2 / Stage 3。
>
> - 不改 §1–§11 的编排主干：§12.1 additive（加 1 个 scope guard 子 stage + checkpoint 字段 + 1 个轻量 agent）；§12.2 在产物**加载边界**做实契约校验（不改 schema、只 enforcement）。4 个 phase 子 agent 与 checkpoint.json schema 零改动。
> - 实证动机（L1 `batch-runlog-20260715.md`）：scatter（`task_loader.py:180` per-input value_range bug）、aggregate（GAP-A `mask=None` schema 漏 token）是「上游 codegen 缺陷被拖进精度循环」；multi_add（L3 根因 B）是「resume 复用旧 DevKit（pre-`734557f`）生成的 harness 致不可修 TypeError 反复横跳」。
>
> **框架基底 vs 新增（诚实标注，对标 §1.2/§2.5）**：§12.1 以既有能力为基底——sub-stage 模式（§4）+ 标准 agent manifest（§4.1），唯一新增是「首轮条件性单次门」（复用 state 依赖路由，**无新原语、仅新用法**）。§12.2 是 §1.3「加载期校验优于运行期暴露」的直接落地（校验位点 `verify-checkpoint.py` 已存在），**无新机制、无新锚点**——原稿的「构建时间锚点」已否决：wall-clock 在本环境不对齐（有主机慢数小时、不强制对时）+ 自动重生属历史债兼容层（§1.4 禁）。

### 12.1 入口守卫 ScopeGuardSubstage

**职责**：首轮 run_tests 报失败后、进 diagnose→fix 循环前，用**一次轻量 AI 调用**判定失败是**本阶段职责**（kernel 精度 / 运行时缺陷）还是**上游产物缺陷**（编译失败 / op_plugin schema 不匹配 / golden.py 不全 / 算子注册失败）。命中上游缺陷 → 直接 halt 并写 `debug_result.json=failed` + 上游归属，**不浪费 diagnose/fix 预算**。

**为何 AI 而非正则**：正则只能匹配已知错误模板（`Unknown keyword argument`、`expected at most N but received M`），新错误措辞 / CANN 版本差异会漏；组合型错误（部分 schema 错 + 部分精度错）正则判不准比例。AI 读整体 error 分布 + 语义，能区分「全上游 → halt」/「混合 → 标记上游 case、本阶段 case 继续」/「全本阶段 → 正常进入」。

**设计（对标 §4 子 stage 模式：actions→SpawnAgent / transition→checkpoint→State / resolve_condition→路由）**：

```python
class ScopeGuardSubstage(Stage):
    name = "scope_guard"
    fail_strategy = "continue"   # 由 verdict 路由，不 halt

    def actions(self, state, iteration):
        op_dir = state.op_dir or (state.op_identity.op_dir if state.op_identity else None)
        return [SpawnAgent(
            agent_name="ascendc-precision-scope-guard",   # 新增轻量 agent
            prompt=self._build_prompt(state),   # 注入 compile_result + run_result 失败摘要
            working_dir=op_dir,
            stage_name=self.name,
        )]

    def transition(self, state, result):
        cp = _load_checkpoint(state)   # agent 已写 scope_verdict/upstream_stage/scope_reason
        return state.with_updates(
            _debug_checkpoint={**_extract_debug_checkpoint(cp), "scope_checked": True})

    def resolve_condition(self, state) -> str:
        dc = state._debug_checkpoint or {}
        return "upstream" if dc.get("scope_verdict") == "FAIL" else "pass"
```

**首轮触发**靠 checkpoint 字段 `scope_checked`（`init-checkpoint.py` 置 `false`）。run_tests 的 resolve_condition 在「有失败」时按 `scope_checked` 分流——未检查 → `needs_scope_check` → scope_guard；已检查 → `has_failures` → diagnose。**后续 fix→run_tests 回归不重跑守卫**（已在精度循环内，失败是预期的）。

**TRANSITION_TABLE 增量**（叠在 §5 之上）：

```python
"run_tests": {
    "all_pass":          ("__halt__", "completion"),
    "exhausted":         ("__halt__", "completion"),
    "needs_scope_check": ("scope_guard", "default"),   # 首轮失败 → 先守卫（NEW）
    "has_failures":      ("diagnose", "corrective"),   # 已守卫过 → 进循环
},
"scope_guard": {                                      # NEW node
    "pass":     ("diagnose", "default"),
    "upstream": ("__halt__", "completion"),   # finalize 写 debug_result=failed + upstream_stage
},
```

halt 路径需 finalize 把 `scope_reason` / `upstream_stage` 写进 `debug_result.json`（对标 §7 finalize）。

**新增 agent**：`.claude/agents/ascendc-precision-scope-guard.md`（轻量、单次调用、输出 `scope_verdict` + `upstream_stage` + `reason`，schema 校验；判定规则同 proposal §3.4：运行时错误 / 精度误差 / 全 0/NaN/Inf 属本阶段；编译失败 / schema 不匹配 / golden 缺 get_input / 注册失败 属上游）。

### 12.2 产物加载期契约校验（不认历史产物，不符即报错）

**职责**：当前版本的 precision_debug 在**加载**持久化产物（`checkpoint.json` + `harness.py`）时，按**当前契约**校验；内容不符 → **直接报错**。不做任何「识别旧版本 + 自动重生/迁移」的兜底——不为历史产物买单（§1.4）。

**为何不走「时间新鲜度 + 重生」**（订正：原稿提过 harness freshness / 构建时间锚点，**已否决**）：
- **时间不可靠**：wall-clock 在本环境不对齐（实测有主机慢数小时），且不强制全员对时——任何 mtime / 构建时间锚点都建在不可靠地基上。
- **自动重生 = 给历史产物铺兼容层**：检测到 stale 就偷偷重生，是 §1.4「不考虑向后兼容…禁止迁移分支/兼容代码」禁的，也违背 §1.2「不静默吞错」。
- **本质是契约演进，不是时间**：`734557f`（TensorList 嵌套 shape + numeric attr 强制转换）改的是 harness 的**生成契约**；旧 harness 不符新契约，应由**内容校验**抓出，不由时间比较抓出（后者还免疫不了 touch / 时钟回拨）。

**设计（§1.3「加载期校验优于运行期暴露」的实例；不是子 stage，是加载边界的断言）**：

```python
# precision_debug_substages.py —— _load_checkpoint（§4.0）加载边界加契约校验
def _load_checkpoint(state: State) -> dict:
    cp_path = _checkpoint_path(state)
    if not cp_path.exists():
        return {}
    cp = json.loads(cp_path.read_text())
    _assert_checkpoint_contract(cp)   # NEW：不符即抛，不 warn、不迁移、不重生
    return cp

def _assert_checkpoint_contract(cp: dict) -> None:
    """当前版本要求的 checkpoint 契约；缺字段 / 错形态直接 raise。
    例：current_stage ∈ 已知阶段集、failed_case_queue 元素形态、best_* 类型……
    随契约演进收紧。不符 = 历史产物，报错让用户重跑（自然重生）。"""
    ...
```

- harness 侧同理：run-cases 加载 / 执行 harness 前，按当前 harness 契约校验 cases 数据形态（正是 `734557f` 修过的 TensorList 嵌套 shape / numeric attr 那层）；旧形态 → 报错。
- harness.py 由 `adapters/npu/runner.py:259-264` 在 run-cases 时生成并随日志 per-iteration 持久化——这是「旧 harness 会被 resume 复用」的来源，校验就挡在这个复用入口。
- **recovery = 重跑，不是 in-band 修复**：报错后用户用当前 DevKit 重跑（自然重生 checkpoint/harness），精度循环不在内部偷偷修历史产物。L3 根因 B 那个 resume 复用 iter-1 旧 harness 的场景，若有此校验，加载即报「harness 契约不符」直接停，根本不会进 fix/printf 空转 246 turn。

**框架基底 vs 新增**：加载期校验是 §1.3 既有原则的直接落地（**非新机制**）；`verify-checkpoint.py`（§3 保留脚本）已是 checkpoint 校验的现成位点，本项是把「校验不符 → 报错」**做实、不做兼容兜底**。无新原语、无新锚点、无时间源。

### 12.3 落地节奏与验证

- **降级策略**：两项增强均 additive。主干（§1–§11）交付不依赖它们；时间紧则先合主干，§12 作为紧随的独立 PR。
- **实施**：并入 §9 作为 **Phase 6（正交增强）**，主干验证通过后做。
- **验证**（并入 §10）：
  - **UT**：scope_guard 的 PASS / FAIL 路由 + run_tests 首轮 `needs_scope_check` 分流；加载期契约校验——构造不符契约的 checkpoint/harness 确认**报错**（而非 warn/迁移/重生）。
  - **ST（非 heavy）**：构造上游缺陷场景（编译失败 / schema 不匹配）确认 halt + `debug_result` 写上游归属、不进循环；构造不符契约的持久化产物确认加载期报错、不进循环。
  - **heavy_llm（§3.11，交付前用户决策跑一次）**：真实上游缺陷算子 + 「resume 复用旧产物」算子各 1 个，端到端确认：上游 halt 在循环外 / 不符契约产物加载期报错 + 用户重跑后精度可正常推进。

---

## 13. 与 step-40（测试执行外部化）的协同关系

> 本节建立 P0 与 step-40（`docs/plan/test-execution-decoupling/02-analysis.md`）的整体实施视图。两者改的是 precision_debug 的**不同层**，代码接触面极小，但有明确的依赖序。

### 13.1 分工：编排层 vs 执行层

| | P0（本 L4） | step-40 |
|---|------------|---------|
| **改的层** | 编排层（PrecisionDebugStage → CompositeGroup + 4 子 stage + 状态机） | 执行层（`run_precision_cases` 内化 → `EvaluationBackend.run()` 抽象） |
| **解决** | async/sync 失配、context 爆、600s ceiling（批跑 halt 直接原因） | cann-bench 知识内化、标准不一致、per-input value_range bug、ATK/TTK 可接入 |

### 13.2 接口点：`run_precision_cases()`

两者共享**唯一一个函数接口**——`run_precision_cases()`：

- **P0**：run_tests 子 stage（§4.1）调用它做判定。P0 **只调接口、不绑内部实现**。
- **step-40**：把 `run_precision_cases()` 的内部从"内化 runner + import cann-bench 模块"替换为 `select_backend().run()`。

这一替换对 P0 的 run_tests 子 stage **透明**（函数签名不变）。故 P0 设计 run_tests 子 stage 时保持"调用 `run_precision_cases()`"，给 step-40 留干净替换面——**不存在返工**。

### 13.3 依赖序：P0 先行，step-40 阶段 4 依赖 P0

- **P0 不依赖 step-40**：run_tests 子 stage 调 `run_precision_cases()`，内化版或 backend 版都行，P0 只用接口。
- **step-40 阶段 4（① 本地预检接入 `backend.run(SINGLE_CASE)`）依赖 P0**：它的落点就是 P0 拆出的 `run_tests` 子 stage。P0 没做时，step-40 的 backend.run() 没有直接 stage 落点，只能经 debug_service / LLM 编排器间接接，**无法完整落地**。
- **step-40 阶段 1-3（协议 + DevkitBackend + CannbenchBackend）不依赖 P0**，可与 P0 并行预备。

### 13.4 `try_load_cannbench_task()` 的归属

P0 **暂留不删**（§3、§11）。它是 step-40 要外部化的 `task_loader` 目录嗅探的调用者——删它是 step-40 执行层改造的一部分。P0 若抢先删，会和 step-40 的 `task_loader`/`runner` 重构抢改同一区域；留给 step-40 统一处理，职责更清晰。

### 13.5 推荐推进顺序

1. **P0 先行**（本 L4）：根治批跑 halt（紧迫）+ 拆出 run_tests 子 stage 作 step-40 落点。
2. **step-40 阶段 1-3 可与 P0 并行**：协议设计（`EvaluationBackend`/`TestReport`）+ DevkitBackend + CannbenchBackend 不依赖 P0。
3. **step-40 阶段 4 等 P0 完成**：run_tests 子 stage 接入 `backend.run(SINGLE_CASE)`。

### 13.6 per-input value_range bug（scatter）的归属

该 bug 在 `task_loader` 通路（执行层），**P0 不碰**（P0 是编排层）。它由 step-40 消灭——CannbenchBackend 用 cann-bench DataGenerator 正确处理 per-input range，bug 随 `task_loader` 外部化自然消失。P0 交付前若需验证 scatter，用 redeploy 重生 harness 的零成本路径（见 L3 `50-non429-issues-analysis.md` §9）临时绕过，不向 task_loader 打局部补丁。
