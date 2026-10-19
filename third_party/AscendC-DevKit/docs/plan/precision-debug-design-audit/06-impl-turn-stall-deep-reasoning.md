# L4 实施方案：turn_stall 看门狗误杀修正（P9）

> 对应 L1 [01-problems.md](01-problems.md)（P9）+ [issues/P9-turn-stall-kills-deep-reasoning.md](issues/P9-turn-stall-kills-deep-reasoning.md)。
> 范围：opencode 后端看门狗（横切基础设施）；sdk 后端无实证误杀，不动。

## 0. 取证结论（20260821 批 moe_re_routing 完整升级链）

```
01:00:07 trip#1 (turn 24, chars static 130s) → infra-retry 1/4
01:06:44 trip#2 (turn 16) → infra-retry 2/4
01:09:42 trip#3 (turn 2)  → infra-retry 3/4
01:11:09 resume_fails 3x → 退化 fresh spawn
01:13:19 trip#4 (fresh, turn 2) → infra-retry 4/4
01:18:16 trip#5 → 预算耗尽 → halt（整算子失败 exit 65）
```

三个关键事实：

1. **`chars` 已计入 reasoning 增量**（`_handle_sse_event`: field ∈ text/reasoning）——
   被杀时的静默是**连思考 token 都不吐**的窗口（非流式推理段/网关背压），属深推理正常形态。
2. **22:32 的 comment_bisect trip reason 是 `last turn 50: thinking,tool:bash`**——
   agent 正在跑 bash（编译）就被杀。看门狗自己的注释写着 "opencode emits no SSE
   progress during a tool call … the honest signal that a long-looking stall is
   a tool, **not a hang**"，但门**不看这个信号照样杀**——§1.10 机制特征代理的纯实证。
3. **升级链系统性放大**：每次 resume 后模型重新思考 → 再 trip → resume_fails 3 次
   退化 fresh → fresh 再 trip → infra-retry 4/4 耗尽 → halt。阈值系统性偏低时，
   重试链把"慢模型"变成"整算子死亡"。另有**错误冒充**：turn_stall 中断被
   `_is_hard_timeout_exc` 统一标 `aborted="hard_timeout"`。

## 1. 方案（三处修正）

### 修正 1：tool 活跃 turn 的 stall 界让位 keepalive 容忍（§1.10 业务语义）

判据修正：turn 内出现过 `tool:*` block（agent 发起过工具调用）→ 模型静默是
**预期的**（等自己的工具跑完，编译/测试分钟级合法）→ 该群体的 stall 界取
`max(turn_stall_s, keepalive_idle_s)`（keepalive 的文档语义本就是"容忍长工具调用"）。
无 tool block 的 turn（纯模型思考/生成静默）维持 `turn_stall_s` 界。

- P117 噪声挂死群体不受影响：那是 fresh-session 无任何产出（无 block）→ 仍走
  `turn_stall_s` 界。
- P131 永久静默群体不受影响：同样无 block。

### 修正 2：默认阈值 120s → 600s（与 keepalive_idle_s 一个语义）

两个看门狗收敛为**一个语义、两个信号**："生产者静默 > 600s = 死"
（turn_stall 看 turn/chars 真进展，keepalive 看任何 SSE 帧——P117 噪声场景靠前者）。

- P131 的 11 次永久 stall 静默均 ≥610s，600s 界仍全部捕获（代价：每个死会话
  多等 480s 才判死）。
- P9 的思考静默（实证 ≥130s，量级未知）获得 4.6× 余量；moe 类深推理不再死亡螺旋。
- 误杀（整算子小时级）与晚杀（每死会话 8 分钟）代价不对称，宽容优先
  （"把成功误判为失败是最坏情形"）。
- 同步改 `resources/orchestration-config.json` 的 `opencode_turn_stall_s: 120 → 600`
  （config 显式钉了 120，只改代码默认无效）。

### 修正 3：aborted 标签去冒充（§1.10 + 错误不冒充原则）

`_KeepaliveAbort` 携带 `kind`（"turn_stall" / "keepalive" / "hard_timeout"），
crash-salvage 的 `aborted=` 用真实 kind（对齐 sdk_backend 既有的
`aborted="turn_stall"` 值域），不再统一标 "hard_timeout"。下游 `is_infra_failure`
只判 `aborted is not None`（值无关），路由零影响；日志/事件说真话。

## 2. 改动清单

| 文件 | 改动 |
|---|---|
| `capabilities/agent/opencode_backend.py` | trip 判据 tool-aware（max 界）；`_KeepaliveAbort` 带 kind；`_abort_kind` 替代 `_is_hard_timeout_exc` 作标签源 |
| `orchestration/runtime_config.py` | `_DEFAULT_OPENCODE_TURN_STALL_S` 120→600 + P9 注记 |
| `resources/orchestration-config.json` | `opencode_turn_stall_s` 120→600 + 注记 |
| `orchestration/kernel/event.py` | agent_aborted 值域文档补 "turn_stall" |
| 测试 | 既有 2 测改非 tool block；新增：tool 延界不误杀/超 keepalive 界仍杀、aborted kind 三值、config 默认 600 |

## 3. 明确不做

- **sdk_backend 的 turn_stall（180s，无事件判据）**：无实证误杀，不动。
- **升级链预算（resume_attempts/infra_retry）**：600s 界内每轮 trip≈10min+退避，
  4 次重试 ≈50min 宽限，message_timeout 4h 是真预算；halt 仅预算耗尽符合
  fail-open 原则，不再加结构（§1.14）。
- **keepalive_idle_s 本身**：工具 >600s 被杀是它自己的文档化权衡，非本问题。

## 4. 验证

- [x] 新增 UT：tool 延界不误杀（`test_turn_stall_tool_active_not_killed_at_model_silence_bound`）/ 超 keepalive 界仍杀（`..._trips_at_keepalive_tolerance`）/ `_abort_kind` 三值 + socket timeout（2 处）
- [x] 改写 UT：既有 2 测的 `tool:read` block 断言（编码了旧缺陷）改为非 tool block；`_is_hard_timeout_exc` 测试重写为 `_abort_kind`
- [x] 守护 UT：默认 600（`test_default_turn_stall_600_p9`）+ 发运 config 钉 600（`test_shipped_config_pins_turn_stall_600`）
- [x] 回归：capabilities + orchestration 全量 **2247 passed**

## 5. 完成判据对照（fail-open 三问）

- **能修的不 halt**：工具运行/≤600s 思考静默不再被杀（死亡螺旋根因消除）；真死会话 600s 判死 → 既有 resume/退化/infra-retry 链不变（有界），halt 仍仅预算耗尽。
- **兜底逃生**：`0` 禁用语义不变；config `timeouts.opencode_turn_stall_s` 可调；keepalive/hard-cap 双界保留（P117 噪声场景靠 turn_stall 的 turn/chars 信号）。
- **消费者**：trip reason → run.log（人读，含 stalled turn + block types）；`aborted` kind → `is_infra_failure`（程序化，值无关）→ infra 重试路由；events.jsonl `agent_aborted.reason` 现在说真话。
