# 并行 VF 测试并发逻辑缺陷 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：真实 run `20260821-111638-ce8166`（mhc_sinkhorn / A5 Regbase / ascend950，opencode backend
> deepseek-v4-flash），`events.jsonl` + `run.log` + 会话 DB（`<run>/.opencode_home/data/opencode/opencode.db`）
> + 代码实证。时间均为本地时区（UTC+8）。

## 触发场景

A5 Regbase 的 s4 阶段 `.VT.{M}` 子步骤（VF 精度预验证）采用「先串行后并行」：
`codegen.py:914-920` 在 plan 首个 VF 步骤（VT.0）done 前只派发它一个（串行建立 `vf_verified` 脚手架），
完成后其余 pending VF 每 iteration 并行派发至多 `max_concurrent_vf=2` 个 `ascendc-vf-test-agent`，
由 runner 线程池并发执行（`runner.py:917-951`）。

本 run 的实际时序（events.jsonl）：

```
20:46:14  iteration 7：并行派发 [VT.1, VT.2]（两个 spawn）
20:57:22  agent_aborted hard_timeout（VT.2 RowDiv；其 24/24 用例已在 20:57 全部 PASS 落盘）
21:02:03  VT.1 RowShiftExp COMPLETED（会话 ses_fdba456c6f）
21:04:43  整批重派 [VT.1, VT.2]（VT.1 明明已 COMPLETED 仍被重跑）
21:09:00  agent_aborted hard_timeout（VT.2 再次）
21:09:02  VT.1 重跑确认 COMPLETED（会话 ses_fdb936eadf）
21:09:02  iteration 7 结束；codegen stage 以 partial 收场，触发 batch run_resumed
```

## P1 — 并行 VF 共享同一 NPU 设备，无设备隔离

- 所有 vf-test-agent 生成的 `test_*.py` 默认 `--device_id 0`（`test_row_div.py:79`），
  `SingleOperatorLaunch/source_module.py:593,627,694` 统一 `set_device(0)`。
- 并行两个 VF 测试同时在同一设备上编译+启动 kernel → 设备层竞争。
- 实证：`vf_verified/kernel_test/row_div_test/result_row_div.txt` 中出现
  `Runtime API Call rtStreamCreate() Failed: ACL_ERROR_RT_DRV_INTERNAL_ERROR`（RETRY 1 后 PASS），
  是并发抢占 device 0 的运行时错误直接证据。
- 影响：并行批中设备级错误注入「需要重试」的抖动，加剧 infra 失败面。

## P2 — 并行批中任一成员 infra 失败 → 整批重跑，成功成员的产物被丢弃（本轮最重缺陷）

- `runner.py:351-390`（P131c 重试循环）：只要批内任一成员 `is_infra_failure`（含 hard_timeout），
  就把该成员提升为 `_ares`，然后 `runner.py:390` 调 `stage.actions(result_state, iteration)` **整批重新派发**。
- 关键：此时 transition 尚未跑（transition 在循环结束后 `runner.py:397` 才执行），plan 中
  VT.1 仍是 pending → `codegen.py:920` `batch = pending[start:start+2]` 重新选入 VT.1 → **已 COMPLETED 的 VT.1 被原样重跑**。
- 实证：VT.1 RowShiftExp 在 21:02 已 COMPLETED（`ses_fdba456c6f` 含 RETURN 块，history.log `STAGE_COMPLETE`），
  却被 21:04 整批重派重跑（`ses_fdb936eadf`，history.log 记为「重跑确认」）。
- 附带后果：成功成员浪费一轮完整编译+NPU 测试；失败成员的 `previous_error` 反馈被新开成员误消费
  （`codegen.py:924-933` 已对此做 retry_target 隔离，但整批重派使该隔离只能兜底同批）。

## P3 — 并行成员分同一 deadline 硬墙，慢者/已完成者被硬墙杀

- `runner.py:987`：`_deadline = min(workflow_deadline, stage_deadline)` 是**同一个绝对值**，
  两个并行 spawn 各自 `_execute_spawn_agent` 都拿到该值；VF 测试是编译+多 case 真机慢任务，
  谁慢谁撞墙 → `sdk_backend.py:240` `anyio.fail_after` 硬超时 → `aborted="hard_timeout"`。
- 实证：VT.2 RowDiv 在 20:57 已完成全部 24/24 case（`result_row_div.txt`），但会话在
  20:57:22 被 hard_timeout 杀掉（run.log：`no new turn for 128s > turn_stall 120s ... killing opencode serve`），
  **final message 长度 0、无 RETURN 块** → 框架只见 partial/aborted，按 infra 失败处理。
- 即：物理工作已做完、只差 RETURN 一步，却因硬墙/看门狗被杀，结果被 P2 的整批重跑进一步放大。

## P4 — `previous_vf_results` 是派发时静态快照，并行兄弟互不可见

- `codegen.py:901-905`：spawn 前一次性 `vf_dir.rglob("*.cpp")` 快照，同批所有成员共享。
- 并行批 [VT.1, VT.2] 同时拿到只有 VT.0 产物的快照 →「算子内接力」（SKILL §2 层次 B：读已通过 VF 的
  `vf_lesson.md`）在并行下退化为「只接力 VT.0」。
- 重试批次也不含本批新完成的产物（快照取自计划派发时刻）。语义上可接受为「并行加速的已知折损」。

## 影响

- s4 阶段 VF 预验证在 4 个 VF 函数上多次整批重跑：history.log 出现多次「重跑确认」，
  单算子 codegen 实际耗时被并发重试拉长；本次 batch 以 `run_resumed`（commit/skill 指纹变化）收场。
- 并发批对 infra 抖动（turn-stall / 设备竞争）高度敏感：一个成员被杀 → 整批重跑 → 重新分硬墙 →
  下一轮再杀，形成「重试风暴」而非收敛。

## 范围备注与状态

- P1（设备共享）暂不处理；P4（快照）按「只拿到 VT.0」的现状可接受。
- P2 与 P3 为已修复（2026-08-22，见 `04-implementation.md`）：
  - P2 修复：P131c 循环按成员分区，干净成员结果保留、只重跑 infra 失败成员。
  - P3 修复：turn-stall 看门狗对工具在飞（`tool:*` block 未归位）豁免，defer 给
    keepalive/message_timeout。
