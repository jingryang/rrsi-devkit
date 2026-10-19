# P9: turn_stall 看门狗误杀深推理模型

**状态**: ✅ 已修（2026-08-22，三处修正：① tool 活跃 turn 的 stall 界让位 keepalive 容忍 `max(turn_stall, keepalive_idle)`——工具运行期无 SSE 是预期，§1.10；② 默认 120s→600s（与 keepalive_idle 一个语义"P131 永久静默均 ≥610s 仍全捕获"），代码默认 + 发运 config 同改；③ `_KeepaliveAbort` 带 kind，`aborted=` 标真实 turn_stall/keepalive/hard_timeout 不再冒充。方案见 [06-impl](../06-impl-turn-stall-deep-reasoning.md)；UT 2247 全绿）
**层归**: L1 问题记录（只述事实，方案在 L3）

## 哪里坏了？

opencode turn_stall 看门狗以"无新 stream 事件超 120s"判 agent 卡死并中断。但 deep-reasoning 模型（pangu_ultra_moe）单 turn 深推理可达 1300-1700s，`chars` 长时间不增长是**正常现象**。moe_re_routing 20260822 实证：diagnose 阶段 `chars static 130s > turn_stall 120s` 被误杀 → hard_timeout halt → 整算子失败。

## 凭什么这么说？（证据）

### 事实 1：turn_stall 默认 120s

`runtime_config.py:792`:
```python
_DEFAULT_OPENCODE_TURN_STALL_S = 120.0        # no new turn this long → trip
```

`runtime_config.py:816-818`:
```python
"turn_stall_s": _non_negative_float(
    raw.get("opencode_turn_stall_s", _DEFAULT_OPENCODE_TURN_STALL_S),
    "timeouts.opencode_turn_stall_s"),
```

### 事实 2：pangu 单 turn 深推理可达 1300-1700s

本批 agent_stream 实证（前面分析）：
```
rms_norm comment_bisect turn 81: 115354 chars, 2616.9s   // 单 turn 43 分钟
rms_norm comment_bisect turn 40:  1112.9s                // 单 turn 18 分钟
moe codegen turn 68: 1473.6s                             // 单 turn 24 分钟
```

这些长 turn 中 `chars` 会长时间不增长（模型在思考，未吐 token）。

### 事实 3：moe 被误杀（20260822 01:18 实证）

```
[ERROR] ascendc-precision-diagnose: no new turn for 128s > turn_stall 120s (chars static 130s) — last turn 2
[WARN] precision-debug teardown (hard_timeout): rolled back op_dir to best_commit 857aca4
[ERROR] Workflow halted: stage 'diagnose' failed with fail_strategy=halt
```

diagnose agent 思考 130s 无 token → 看门狗判"卡死" → 中断 → teardown 回滚 → halt。整算子失败（exit 65）。

### 事实 4：看门狗判据是机制特征，非业务语义（§1.10 反模式）

`sdk_backend.py` docstring:
```python
"""turn-stall 看门狗触发：网关静默（无任何 stream 事件）超过 turn_stall_s 秒。
```
用"无新 stream 事件"（机制特征）当"卡死"判据。但 deep-reasoning 模型的正常思考就是"长时间无 token 输出"——**业务语义（在思考）与机制特征（无 token）矛盾**，违反 §1.10"判据用业务语义，不用机制特征代理"。

## 影响

- **深推理模型（pangu 等）在长单 turn 思考时被误杀**：moe 实证，整算子失败。
- **越聪明的模型越容易触发**：思考越深，chars static 越久，越可能超 120s。
- **hard_timeout → teardown 回滚**：误杀后回滚 op_dir，浪费已修的部分。

## 与既有问题边界

- **P1-P8**（precision_debug 内部问题）：P9 是**通用 agent 基础设施**问题（opencode 看门狗），不限于 precision_debug，但当前在 precision_debug 深推理场景暴露。
- 修复涉及 `runtime_config.py`（turn_stall 默认值/判据）——是横切基础设施，非 precision_debug 专属。

## 修复方向（L3 待详）

- **调大 turn_stall**：120s → 适配 deep-reasoning（如 300-600s），或按模型可配置。
- **改进判据**：区分"网关静默"（真卡死）与"模型在思考"（可探测：思考中可能有 thinking 事件，只是无 text）——用 §1.10 业务语义。
- **或对 deep-reasoning 模型禁用 turn_stall**（靠 message_timeout 兜底）。
