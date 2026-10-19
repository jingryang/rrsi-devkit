# VF 并行批次并发缺陷修复 — 实施方案（L4）

> 产权：本文件对应 L1 `01-problems.md` 的 P2 与 P3。P1/P4 按范围备注暂不处理。
> 状态：已实施 + UT 通过（2026-08-22）。

## P2 — 并行批中单个成员 infra 失败 → 只重跑失败成员，保留成功成员

### 根因

`runner.py` P131c 重试循环（`_run_stage_body`）把并行批次当原子单元：批内**任一**成员
infra 失败（`is_infra_failure`）→ 整批 teardown + 退避后 `stage.actions(result_state,
iteration)` **整批重新派生**。而 transition 在循环外才执行，成功成员的 plan 状态仍是
pending → 重派生时 `_actions_regbase_vf` 用 `pending_vf_ids` 把它重新选入批次 → 重跑。
已 COMPLETED 的成员（如 RowShiftExp）被整批重跑，产物丢弃。

### 改动（`src/ascendc_devkit/orchestration/kernel/runner.py`）

P131c 内循环改为**按成员分区**：

1. 扫描 `result["agent_results"]`（顺序无关，延续 P9）：
   - infra 失败成员 → 其 `action` 收集进 `_failed_actions`，并 promote `_ares`（保持
     串行对齐的整批 infra 语义）。
   - 干净成员 → 收集进 `_clean_entries`，**不重跑**。
2. 单成员路径（无 `agent_results`，`len(actions)==1` 且 infra）→ 继续重跑该 action
   （`_replay_actions`），与串行重试语义一致。
3. 重派生决策：
   - 有 `_failed_actions` → `actions = _failed_actions`（只重跑失败成员）。
   - 单成员子集持续失败 → 保持重跑该成员（`_replay_actions`）。
   - 否则 → 仍走 `stage.actions()` 整批重派生（全失败/串行场景的原始语义）。
4. 循环干净退出后：把 `_preserved_results`（各轮累计的干净成员 `{agent_result, action}`
   条目）合并回 `result["agent_results"]`，使 transition 能提交它们（标 done）——成功
   成员的产物不再被丢弃。

### 验证

- `tests/ut/orchestration/test_infra_backoff_resume.py` 三个并行批测试改为断言新语义：
  - aborted 成员 → spawns 3（首批 2 + 只重跑 p2 1），teardown 1 次，transition 结果含 p1+p2。
  - infra_transient 成员 → spawns 3，不 teardown，transition 结果含 p1+p2。
  - 持续 infra → spawns 6（初始批 2 + cap(4) 次只重跑失败成员），干净成员不被反复重跑。
- 新增断言：干净成员 p1 的结果确实进入 transition（`_recorded["result"]["agent_results"]`）。

## P3 — turn_stall 看门狗误杀长工具调用

### 根因

opencode 在**工具调用期间不产生任何 SSE 进度**（源码注释即此语义）。并行 VF 批成员
长时间跑 `tool:bash`（编译 + 24 个 NPU 用例）时，`turn_ts` 不 bump 且 chars 静态 →
P137 的 producer-liveness 守卫（chars 增长才放行）不生效 → 超过 `turn_stall_s`（120s）
被误杀。实际 run：RowDiv 24/24 用例已在 20:57 落盘，20:57:22 被 `no new turn for 128s
> turn_stall 120s` 杀死，final message 长度 0 → 被当 infra 失败，再被 P2 整批重跑放大。

### 改动（`src/ascendc_devkit/capabilities/agent/opencode_backend.py`）

turn-stall gate 增加**工具在飞豁免**：当 `sse.state["block_types"]` 含 `tool:*`（该 turn
已发出 tool_use、其 role=user 结果尚未到达 = 工具仍在执行）→ 不 trip，defer 给 keepalive
（`keepalive_idle_s`）+ message_timeout 作真挂起工具的后盾。仅 warn 一次（`_tool_stall_warned`）
保证可观测（§1.2）而不刷屏。

### 验证

`tests/ut/capabilities/test_p117_turn_stall_watchdog.py`：
- 既有 trip 用例的 `block_types` 从 `tool:*` 改为非工具块（`thinking`/`text`）——它们测的
  是「真挂起」语义，不再被工具在飞豁免误放。
- 新增 `test_turn_stall_tool_in_flight_defers_trip`：`block_types={"tool:bash"}` + 陈旧
  turn_ts + 静态 chars + 慢 worker → 返回正常消息，不 abort（P3 回归）。
- 新增 `test_turn_stall_tool_in_flight_still_bounded_by_keepalive`：工具在飞但无 SSE 超过
  `keepalive_idle_s` → keepalive 仍会杀（豁免不是无限豁免）。

## 回归

- `tests/ut/orchestration/`（`PYTHONPATH=src`，`--quick`）：无新增失败。forkjoin 的
  `TestForkJoinBranchFailure` 存在**基线即有的**线程竞态抖动（10 次采样 7 pass/3 fail，
  stash 前后一致），与本改动无关。
- `tests/ut/capabilities/`（`PYTHONPATH=src`，`--quick`）：与基线一致，2 个
  `test_capabilities.py` 失败为**基线已有**（项目路径解析，与本改动无关）。

## 环境注意

- 本仓为 editable install，但 `.pth` 指向 `AscendC-DevKit-BatchRun/workdir_0818/...`
  旧快照；本地 UT 需 `PYTHONPATH=src` 才会测到工作区源码。后续如希望默认指向工作区，
  需重跑 `pip install -e .`（不在本次改动范围）。
