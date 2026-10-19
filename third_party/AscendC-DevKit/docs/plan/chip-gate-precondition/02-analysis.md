# L3 — chip-gate 前置条件化：方案分析

> 选项、决策、理由。调研中演进、拍板后冻结。
> 问题事实见 `01-problems.md`（L1）；halt/feedback 全局机制见 `halt-feedback-global-policy.md`（专题）。

## 决策（已与用户确认）：Option D — chip-match 作为 `codegen.validate_inputs` 前置条件

**一句话**：chip-match 检查落在 `codegen.validate_inputs`（precondition 的家），返回 reason 串 → runner `raise PreconditionError` → dispatcher 干净 halt，codegen 永不 spawn。共享 helper `chip_mismatch_reason` 是判断+消息的单一来源（§2.5）。不新增 stage、不接线、不背债。

### 为什么是 precondition 语义（而非 task-node）

用户原话判据：*"stage 是承担重任的任务节点，这只是个判断"*。chip-match 是「构建前置条件」——它不产出任何工件、不消费 iteration、不 spawn agent，本质是「能不能开始构建」的 yes/no。precondition 的家是 `validate_inputs`（runner.py:188 在 spawn 之前、迭代循环之前执行），语义完全对齐。

### 为什么 PreconditionError 是干净的 halt 通道（不是 traceback）

逐行核实 `dispatcher.py:677-688`：dispatcher 捕获 `PreconditionError` → `Logger.error(stage_name + reason)` + `_rollback_repo_if_needed` + `_write_state_snapshot` + `_generate_report` → `return EX_DATAERR`。**全程无 Python traceback**，操作者看到的是「Stage 'codegen' aborted: <具体 reason>」+ 一份报告。这与 `requirement.py` 的 `raise PreconditionError`（underspec→终止→补需求重跑，`requirement.py:398` 附近）同构。

## 候选选项与取舍

| 选项 | 机制 | 取舍 |
|---|---|---|
| **A** 独立 `ChipGateStage` | 新 stage（registry + workflow 四列表 + after_names 接线），`fail_strategy=halt`，reason 落 `state.last_error` | reason 落 last_error 略优，但代价是 4 列表 + 3 after_names 接线（§2.5 接线债）；且 chip-match 是 precondition 不是 task-node，过重。**用户判「太重」否决。** |
| **B** 挂 `codegen.actions` | actions 里先检查，mismatch → 返回特殊 action / 标记 | `actions()` 写不了 State（返回 list[Action]），且检查在 spawn 边界附近，不如 validate_inputs 早。**否决。** |
| **C** deploy 内保留 + smart transition | gate 留 deploy，codegen.transition 识别 chip-gate reason 路由 halt | 治标：gate 仍困服务（P3 未解），且 transition 在 spawn 之后（已空转一轮）。**否决。** |
| **D** `codegen.validate_inputs` 前置条件 | reason 进 errors 列表 → runner `PreconditionError` → dispatcher halt | **采纳。** 详见上。 |

Agent 1 已证 `actions()`/`transition()` 都不能干净承载（actions 写不了 State；transition 在 spawn 之后太晚）；`gate()` 也能 raise PreconditionError 但语义与 validate_inputs 同、且 gate 更偏「上游产物是否就绪」而非「环境前置条件」。**`validate_inputs` 是唯一正确的 pre-spawn 钩子。**

## 四把尺子（§1.2）

- **可维护**：precondition 住 precondition 的家（`validate_inputs`），与 `requirement.py` precedent 一致；helper 单一来源，判断+消息不分散。
- **可扩展**：新环境前置条件（CANN 版本不够、UB 不达标等）自动归位 `validate_inputs` 同一模式，无需新 stage / 新接线。
- **可诊断**：reason 串具名两个值（`'A5'` / `'A2'`）+ 可操作建议（`design_target_chip` 改声明 / 换硬件），非抽象 jargon；dispatcher `Logger.error` + report 完整打出。
- **架构合理**：判断落 L4 adapter helper（`detect.chip_mismatch_reason`），前置条件落 L3 codegen（`validate_inputs`），halt 通道落 L3 kernel（`PreconditionError`）→ dispatcher。各层职责正确，不越层兜底。

## 两个权衡点

### (1) reason 不落 `state.last_error` —— 实际影响 ≈0

PreconditionError 走 control-exception 通道（dispatcher 捕获），reason **不**进 `state.last_error`（与 requirement.py 的 PreconditionError 同模式——precondition 类 reason 本就不落 last_error）。核实影响：
- `events.jsonl` 记 `stage_aborted(error_type="PreconditionError")`（异常类名）；halt 路径也只记 `stage_done(failed)`（无 reason 串）——粒度相当，不更差。
- state snapshot 不存 chip_mismatch last_error；但 dispatcher `Logger.error` + report 把 reason 完整打出，操作者不丢。
- 下游 stage 不跑（halt）；resume 时 `validate_inputs` 重新检查（precondition 是无状态的，重跑必然再判出）。
- 无下游消费者因此受损。

### (2) deploy 保留 SECONDARY 深度防御入口

`Deployer.deploy()` 仍调 `chip_mismatch_reason` 复检，因为 deploy 经 `redeploy` CLI（`cli/commands/debug.py` → `application/debug_service.py`）与直接调用方（`tests/st/test_npu.py` fixture）可达，**绕过流水线**（无 `codegen.validate_inputs`）→ deploy 是另一条入口，需自守。helper 共享使「判断+消息」单一来源（§2.5 精神）。新 `error_type="chip_mismatch"`（halt 类，deploy 路径专用），永不与 `deploy_failed`（compile/smoke 可修）混淆——解 P2。

## 实施（L4 摘要）

1. helper `chip_mismatch_reason(target_chip) -> str|None` 落 `adapters/npu/detect.py`（挨着 `detect_chip_version`，同属 chip 检测关注点；调同模块 `detect_chip_version`，无环）。
2. `codegen.validate_inputs` 在 design_spec 形状检查后追加 chip-match 检查（非空 → runner `PreconditionError`）。
3. `Deployer.deploy()` 内联 gate 替换为调 helper + `ErrorFeedback(error_type="chip_mismatch", details={"target_chip": ...})`；`_resolve_fail("chip-gate")` 分支退役（其它 `_resolve_fail` 不变）。
4. `state.py:23` 死词注释（列了 5 个从未赋值的 error_type）改为指向真实词表 + 专题文档。
5. TDD：helper / deploy / codegen.validate_inputs / runner-level PreconditionError 四组测试红→绿。

## 不改（范围边界）

- `precision_debug` 自修循环（用户明确否决大调整）。
- workflow.py 四列表 / 三 after_names / TRANSITION_TABLE（Option D 不新增 stage，零接线）。
- registry.py（不注册新 stage）。

## 验证结果

TDD 全程红→绿；`test_deploy.py::TestChipGate`（chip_mismatch error_type + target_chip details + 具体消息）、`test_stages.py` codegen.validate_inputs 两组 + runner-level `test_runner_raises_precondition_on_chip_mismatch`（断言 `PreconditionError` raise 且 `backend.spawn_calls == []`，证明 pre-spawn halt）、`test_adapters.py::TestChipMismatchReason` 全绿；回归 `test_deploy/test_stages/test_fail_strategy/test_graph_executor` 203 passed（0 回归）。
