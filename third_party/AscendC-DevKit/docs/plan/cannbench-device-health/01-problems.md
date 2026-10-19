# L1 问题记录：cann-bench 评测 device 故障被当 LOSS 静默吞 + 选卡 hard-pin 0

> 层级：L1（事实快照，写定即冻结）。仅记录「哪里坏、凭什么这么说」，不提方案、不排顺序、不写决策。
> 来源 run：`20260727-144633-2a1db8`（gather，cannbench_eval 撞 507033 被当 0 分）。
> 关联：`op-plugin-schema-arg-order/01-problems.md`（同一 run，记录 schema 缺陷；其末注已指出 507033 是
> 并存的独立环境问题）；memory `npu-device-context-exhaustion-zombie`。

## P1 — cannbench_eval 把 NPU device 故障（507033）归因为算子精度 LOSS，不上报、不 halt

**现象**：
- run `20260727-144633-2a1db8` 末尾 cannbench_eval：`kernel_eval exited 20`，连续 3 次重试
  全部 `open device 0 failed, runtime result = 507033` / `TsdOpen failed` / `Failed to start the device`
  （`subprocess/cannbench_eval_gather.stderr.log`，PID 87573→87752）。
- 但 stage 标 `✓ ok`、`overall=0.00 compile=0 func=0 perf=0 pass_rate=0.00%`、`report.json` 的 `errors=[]`。
- 报告呈现「算子 0 分」，实际是「设备坏了」——设备级故障被静默降级成被测对象缺陷。

**凭什么这么说（证据）**：
- `cannbench_eval.py:283-285`：`returncode != 0` 只 `_log_eval_failure` 打 WARN，注释
  「Non-zero exit = some cases failed, but report may still exist」——默认所有非0退出=用例失败，
  从不怀疑设备。
- `cannbench_eval.py:421-427`：`_is_discovery_broken` 只认 `operators==[]`；device 炸了但
  operator 仍能被 `scan_interfaces` 发现 → 判定「链没断」→ discovery_err=None。
- `cannbench_eval.py:329-331`：注释「zero score IS the loss, never route back to codegen」——
  device 故障 → overall=0 被当合法 LOSS。
- `cannbench_eval.py:117-119`：discovery_err=None → 不设 last_error → transition 返回 ok。
- 全仓 grep 无 `507033` / `TsdOpen` / `device retain error` 识别点（只以 stderr 文本存在）。
- `report.py:96-97`：errors 只读 events.jsonl 的 `type=="error"` 事件；device 故障未 emit
  该事件 → errors=[]。`events.jsonl`（451 条）无 device error 结构化事件。

**根因事实**：
- cannbench_eval 是 `actions=[]` 纯 transition stage（`fail_strategy="continue"`、无 agent），
  `runner.py:510-512` 的 infra halt 分支依赖 `last_agent.error_type`，对此 stage 恒不适用——
  返回 last_error=infra 也不会 halt（只会标 failed 后继续跑 finalize）。
- device 故障（驱动 context pool 耗尽，见 memory `npu-device-context-exhaustion-zombie`：
  zombie 累积、8 卡都在、board 正常、context pool 全局耗尽）与算子精度失败在退出码上无区分层，
  且全仓无错误码识别。
- `NPUSlotManager`（`slot.py`）是纯 in-memory 卡号记账（`_acquired: set[int]`），与驱动 device
  context pool 是两个独立池——卡在内存记账里「空闲」≠ 驱动侧能 open device。

## P2 — e2e 脚本默认 hard-pin 卡 0，未用 card pool 自动选卡

**现象**：
- 同一 run，cannbench_eval 日志 `npu_id=0 device_id=0`——写死卡 0。

**凭什么这么说（证据）**：
- `scripts/e2e_self_evolve.sh`：`NPU="${NPU_ID:-0}"` + `--npu-id "$NPU"`；
  `scripts/e2e_run.sh`：`NPU_ID="${NPU_ID:-0}"` + `--npu-id "$NPU_ID"`——脚本默认 hard-pin 0。
- 框架本身无此问题：`state.py:81-84` `npu_id: int | None = None`、CLI `--npu-id default=None`、
  `card_context.py:36-43` preferred=None 时走 pool 自动选卡——hard-pin 0 来自脚本层。

**根因事实**：
- 脚本默认 hard-pin 0 源于历史确定性偏好（每次同卡复现），牺牲了「卡 0 被占/局部坏时换卡」的健壮性。
- P1 与 P2 是两类不同故障：P2 改为自动选卡对 P1 无效（context pool 全局耗尽时，任意卡
  `set_device` 均 507033——context pool 是驱动级全局、非 per-card）。
