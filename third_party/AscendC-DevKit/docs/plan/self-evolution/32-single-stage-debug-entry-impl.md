# L4 实施方案 — 单 stage 调试入口对 in-stage 闭环 stage 可用化（P55）

> 关联：L1 `06-problems.md` P55、L2 总纲 step 29。本文只记改动配方与验证，不重复事实/取舍（产权在 L1）。

## 0. 背景一句话

P54 的 `PrecisionDebugStage` 本身正确，但 `ascendc-devkit stage run -n precision_debug --from-run <run_id>` 单跑必崩——`dispatch_single_stage` 的 workspace 构造与主 `dispatch` resume 分支范式分叉（新建 vs 复用、不注入 vs 注入 `_workspace`）。前置流程过长，需要一个能反复单跑 precision_debug 的入口。

## 1. 改动点（单一函数：`application/dispatcher.py::dispatch_single_stage`）

把 workspace 构造**提前到 `_build_state_for_stage` 之前**，并按是否 `--from-run` 分流：

```python
if from_run_id:
    try:
        workspace = Workspace.from_existing(from_run_id, output_root)   # 复用原 run + 存在性校验
    except FileNotFoundError as e:
        Logger.error(f"--from-run 指定的 run 不存在: {e}")
        Logger.info(f"可用 run 见 {Path(output_root).resolve()} 目录，"
                    f"--from-run 传 run_id（output/ 下的目录名）。")
        return EX_USAGE                                                 # §3.7 诚实报错，不 warn+empty
else:
    workspace = Workspace.create(output_root=output_root)

state = _build_state_for_stage(...)   # from-run 时 run 已确认存在，_load 不 warn

# 契约校验不变（缺字段仍 return 64）

state = state.with_updates(run_id=workspace.run_id, _workspace=workspace)  # 两路径都注入
_write_state_snapshot(workspace, state)
```

### 为什么这么改（四把尺子）

- **可维护**：消除「主 resume 复用 + 单 stage 新建」两范式分叉，二者本质同构（从某 run 恢复跑 stage），收敛到 `from_existing + 挂回 _workspace` 一套（§2.5）。
- **可扩展**：任何依赖 `state._workspace` 或「复用原 run 产物」的 stage（requirement / context / precision_debug / 未来 in-stage 闭环 stage）自动受益，无需逐 stage 打补丁。
- **可诊断**：`from_existing` 自带存在性校验，run 不存在前置报错 EX_USAGE；且**早于** `_load_state_from_run`，不触发其 warn+empty（否则会把「run 不存在」掩盖成下游「缺字段」）。
- **架构合理**：修复落在 dispatcher（L2 application），workspace 构造本就是其职责；不在 stage 内 fallback（越层兜底）。

### 不改 `_load_state_from_run` 的理由

它被主 `dispatch` resume 也调用；收紧成 raise 会改变主 resume 的冒泡行为、波及其测试。本次只让 `from_existing` 在单 stage 路径前置做存在性校验——run 不存在早在 `_load` 之前就 EX_USAGE 退出，`_load` 根本不被调用，零影响主 resume。

## 2. 不变式

- `state._workspace` 在 stage 执行前必须非 None（requirement / context / precision_debug 等经它取 run 目录）。主 dispatch 的 new-run / resume 两分支早已满足；本次补齐单 stage 路径。
- `--from-run` 语义 = 复用该 run（目录 + snapshot + 已 deploy 算子），不为单 stage 新建。

## 3. 取舍（已在 L1 冻结，用户拍板）

单 stage 重跑的 stage 事件**追加进原 run 的 `events.jsonl`**（runner 持有 `from_existing` 的 workspace）——事件流连续、调试连贯。不隔离到新 run（隔离须重建 deploy 环境，违背省时初衷）。

## 4. 验证

- 新增 UT（`tests/ut/application/test_application.py::TestDispatcherSingleStage`）：
  1. `test_from_run_reuses_existing_run_and_injects_workspace` —— from-run 复用原 run（不新建额外目录）+ `_workspace` 挂回（`run_id == from_run_id`）。
  2. `test_from_run_missing_returns_usage` —— from-run 指向不存在 run → `EX_USAGE`。
  3. `test_no_from_run_still_injects_workspace` —— 无 from-run（新建）也注入 `_workspace`（修复非 from-run 单 stage 路径）。
- 回归：`test_application.py` 全量 63 绿（含 `TestDispatcherResume` 主 resume 路径）；precision_debug 相关 38 绿。0 回归。
- heavy_llm：本改动是确定性控制流（workspace 构造 + 字段注入），非 §3.9 LLM 行为对象，无需 heavy e2e 守护。

## 5. 用户工作流（改动收益）

```bash
# 一次性：跑前置到 verify 判定 precision_failed（产出 output/<run_id>/）
ascendc-devkit run ...

# 之后反复单跑 precision_debug，秒级拉起 agent 闭环，不再走前置
# --max-iterations N 控制 agent 内循环轮数（precision_debug 不 loopback，
# 借用为 agent 内循环；不传则用 config/default 5）
ascendc-devkit stage run -n precision_debug --from-run <run_id> [--non-interactive] [--max-iterations N]
```

## 6. max_rounds 受 --max-iterations 控制（P55 延续）

precision_debug 的 agent 内循环轮数（`max_rounds`）由 `_max_rounds(state)` 决定，优先级
`user_max_iterations`（CLI `--max-iterations`）> config（`orchestration-config.json`
`iterations.stages.precision_debug`）> `default_max_iterations=5`：

```python
def _max_rounds(self, state):
    if state.user_max_iterations is not None:
        return state.user_max_iterations
    return self.effective_max_iterations()
```

`actions`（传进 agent prompt/context 的 `max_rounds`）与 `transition`（agent 未产出时的
fallback `debug_iterations` 记账）共用此 helper，保证两者一致。

**为什么 `--max-iterations` 对 precision_debug 生效**：precision_debug 是 halt stage、
不 loopback，stage 自循环恒 1 次，`--max-iterations` 作 stage 循环上限对它本无意义——
借用为 agent 内循环轮数（零冲突），并兑现 config `_comment`「CLI --max-iterations wins
over these」对 precision_debug 的意图，让 agent 内循环 per-run 可调（防轮数不足无法收敛）。

**trade-off**：`--max-iterations` 语义随 stage 分裂（verify/perf = stage loopback 次数；
precision_debug = agent 内循环轮数）。无功能冲突（precision_debug 不 loopback），但语义
不统一——见 L1 P56（低优先级，待后续 L3 展开分析方向）。

UT 守护：`test_actions_max_rounds_honors_user_max_iterations`（不传→default / 传→覆盖）、
`test_transition_max_rounds_consistent_with_user_override`（transition 一致性）。
