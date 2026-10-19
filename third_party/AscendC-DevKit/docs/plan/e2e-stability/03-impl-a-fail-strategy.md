# L4 实施方案 A — fail_strategy 失败信号管道

> 层级：**L4 / 实施方案**。具体改哪个函数、怎么验证。
> 覆盖问题：P2, P3（见 `01-problems.md`）

## 改动文件 1：`src/ascendc_devkit/orchestration/base.py`

**位置**：`class Stage(StageProtocol)` 定义块

```python
# 新增属性（置于 default_max_iterations 之后）
fail_strategy: str = "continue"  # "continue" | "halt"
```

## 改动文件 2：`src/ascendc_devkit/orchestration/stages/design_substages.py`

**位置 1**：`class _DesignSubstage(Stage)`（第 61 行）

```python
class _DesignSubstage(Stage):
    agent_name: str = ""
    prompt_intro: str = ""
    fail_strategy = "halt"          # 新增：设计阶段默认 halt
    # ↑ _TestDesignSubstage 继承此类，test-analyze/casedesign/casegen 自动 halt
```

**位置 2**：`GeneralDesignReviewStage`（第 423 行附近）

```python
class GeneralDesignReviewStage(_DesignSubstage):
    fail_strategy = "continue"      # 新增：由 blocking_issues 路由
```

**位置 3**：`AnchorCheckStage`（第 614 行附近）

```python
class AnchorCheckStage(_DesignSubstage):
    fail_strategy = "continue"      # 新增
```

**位置 4**：`ValidateStage`（第 810 行附近）

```python
class ValidateStage(_DesignSubstage):
    fail_strategy = "continue"      # 新增
```

## 改动文件 3：`src/ascendc_devkit/orchestration/kernel/runner.py`

**位置**：`run_stage` 方法，`stage_status` 确定之后、`Logger.stage_done` 之前（第 306-312 行区间）

```python
# 在 stage_status 赋值后、Logger.stage_done 前插入
fail_strategy = getattr(stage, "fail_strategy", "continue")
if stage_status != "ok" and fail_strategy == "halt":
    result_state = result_state.with_updates(_stage_failed=(stage_status, stage.name))

# 修复 P8：partial agent 但 contract 已满足 → 不标失败
if agent_status == "partial" and output_contract.provides \
   and result_state.has_all(output_contract.provides):
    stage_status = "ok"
```

**位置 2**：`_execute_spawn_agent` 末尾（第 435 行之后）

```python
# 传 working_dir 给 transition 使用
result["_working_dir"] = action.working_dir
```

## 改动文件 4：`src/ascendc_devkit/orchestration/graph_executor.py`

**位置**：`_execute_sequential` 方法，child 执行后（第 155 行之后）

```python
state = self._execute_node(child, state, scope_prefix=path)

# 新增：读取失败信号并中断
sf = getattr(state, "_stage_failed", None)
if sf is not None:
    sname = sf[1] if isinstance(sf, tuple) else "?"
    Logger.warn(f"Stage '{sname}' failed with fail_strategy=halt; stopping pipeline.")
    state = state.with_updates(is_terminal=True, _stage_failed=None)
    break
```

## 改动文件 5：`src/ascendc_devkit/orchestration/stages/codegen.py`

**位置**：`AscendCCodegenStage` 类

```python
class AscendCCodegenStage(Stage):
    fail_strategy = "halt"    # codegen 失败 → 中断 pipeline
```

## 验证方法

1. 单测：构造 `Stage` 子类分别设 `fail_strategy="continue"`/`"halt"`，验证 `run_stage` 返回的 state 中 `_stage_failed` 字段
2. 集成：用 stub agent 返回 `status="fatal"` 模拟 template-division 失败，验证 `graph_executor` 在 tiling fork-join 前中断
3. 回归：验证 gate 阶段（general-design-review）失败后仍由 transition_table 路由，不被 halt
4. 继承验证：确认 `_TestDesignSubstage` 继承 `_DesignSubstage` 的 `fail_strategy="halt"`，test-analyze 失败 → test_design group 中断

## 全局流程验证（基于 rope-e2e.log 全量日志）

修改后的预期 behavior 与修改前对比：

| 阶段 | 修改前 | 修改后 |
|------|--------|--------|
| gd-generate crash | → review 继续 | → halt |
| general-design-review crash | → dd-intake 继续 | → 检查 contract 满足 → ok |
| template-division crash | → tiling fork-join | → halt |
| split/buffer-kernel crash | → 下一段继续 | → halt（单模板分支内） |
| anchor-check 3 轮全截断 | → integrate 继续 | → continue（gate），blocking_issues 路由 |
| integrate crash | → docgen 继续 | → halt |
| test-analyze crash | → casedesign 继续 | → halt（继承 _DesignSubstage） |
| test-casegen crash | → halt 消息 | → halt（继承 _DesignSubstage） |
