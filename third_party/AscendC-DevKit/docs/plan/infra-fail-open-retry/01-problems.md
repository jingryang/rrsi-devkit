# infra/未知失败默认有界重试（fail-open）— 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：真实 run `batch 20260813-164600-f65f5b`（`batch_self_evolve.sh` 首跑，2026-08-14 00:45 起，
> 3 算子 grid_sampler_3d / resize_bilinear / unique），日志 `logs/batch_20260814_004541.log`。

## 触发事件：grid_sampler_3d 因 spawn 连接重置直接 halt，无重试

时间线（`batch_20260814_004541.log`）：

```
03:12:40 [ERROR] Agent ascendc-design-generator opencode spawn failed: Remote end closed connection without response
03:12:40  ✓ self_evolve_op/detailed-design/tiling/T2/split/split done (16.2s) [partial]
03:12:40 [WARN] Stage 'split' failed with fail_strategy=halt; stopping pipeline.
03:35:53  ✓ self_evolve_op/detailed-design/tiling/T1/split/split done (1409.9s)
03:35:53 [WARN] ForkJoin 分支 'T2' 失败，join 处停止管线：fork-join 分支 'T2' 失败
03:35:54 [ERROR] Workflow halted: stage 'T2/split' failed with fail_strategy=halt: fork-join 分支 'T2' 失败
```

最终：`[FAIL(exit 65)] grid_sampler_3d  eval=-`（整 run 报废，8 小时白跑）。T2/split 的 opencode serve
起来后，消息 POST 阶段连接被对端提前关闭（`http.client.RemoteDisconnected`，str = "Remote end closed
connection without response"）。

## P1 — spawn 期连接重置没被分类为「可重试瞬时故障」，既无重试也无 infra 诊断，掉进「中性失败」夹缝

失败分类链路（代码实证）：

1. `capabilities/agent/opencode_backend.py:851`：`_aborted = "hard_timeout" if _is_hard_timeout_exc(e) else None`。
   `_is_hard_timeout_exc`（`:173-185`）只认 `_KeepaliveAbort` / `TimeoutError` / `e.reason is TimeoutError`。
   `RemoteDisconnected` 三者皆非 → **`aborted=None`**。
2. `capabilities/agent/base_backend.py:298-311`：`crashed=True` → `error_type = _classify_error_type(crash_reason)`。
   `_INFRA_ERROR_MARKERS`（`_shared.py:371-385`）只含 "No available channel / Usage limit reached / 401 / 403 /
   timed out / price not configured / 价格未配置 / Invalid token"——该连接重置文案一个都不匹配 → **`error_type=None`**；
   `aborted` 也是 None → `error_type` 保持 **None**。
3. `orchestration/kernel/runner.py:362`（P131c 循环）：`_abort = result["agent_result"].aborted` = None → 直接
   `break`，**不重试**。
4. `runner.py:433`（P116）：`error_type == "infra"` 不成立 → 也不走（但 P116 本就是「停」，不是重试）。
5. `runner.py:613-618`：`_last_infra = (error_type=="infra")` = False，但 split 是设计子阶段，
   `design_substages.py:240` 设 `fail_strategy="halt"` → `_stage_failed` 置位 → **halt**。

结论：该失败既没被判为 `aborted`（→P131c 重试），也没被判为 `error_type="infra"`（→P116 干净诊断），
掉进「中性失败」夹缝，叠加 split 的 `fail_strategy="halt"`，变成「不重试、直接 halt」。

## P2 — 反证：同批 unique 的 turn-stall 走了重试，说明是「失败模式」差异不是「代码时间」差异

同批、同时、同一份代码，unique 的失败是 `no new turn for XXXs > turn_stall 120s`（turn-stall 看门狗杀掉
活 spawn）→ 抛 `_KeepaliveAbort` → `_is_hard_timeout_exc=True` → `aborted="hard_timeout"` → 进 P131c 重试
循环（反复 stall→teardown 回滚→重派，`infra_backoff ... infra-retry 1/4`）。二者失败模式不同、分类不同、处理不同。

## P3 — marker 列表是「重试门槛」，新错误文案 = 直接 halt（whack-a-mole）

`_INFRA_ERROR_MARKERS` / `_SOFT_RETRY_MARKERS` / `_RATE_LIMIT_MARKERS` 三套全是**文案匹配**，靠不断往里加
新措辞来覆盖「哪些能重试」。连接异常文案变体几十种（"Remote end closed connection without response" 只是
`RemoteDisconnected` 的一种），marker 永远追不上。当前架构把「重试」做成需命中 marker 的特例、「halt」做成
未知错误的默认——每来一个新文案就废一个 run。P1 就是第一个实例，不是最后一个。

## 影响

- 一次 spawn 期瞬时连接抖动（serve 没干净起来，fresh 重派大概率能好）被判死为整算子 halt，成本是阶跃的
  （8 小时 run 报废），而「有界重试几次」的成本是线性的（几分钟）。
- halt 的默认取向是 fail-closed，对「时间便宜、丢 run 昂贵」的批跑场景方向反了。
