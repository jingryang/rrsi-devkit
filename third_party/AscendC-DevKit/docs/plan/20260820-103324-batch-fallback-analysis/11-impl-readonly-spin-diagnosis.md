# L4 实施方案：read-only 空转诊断（F9）——修正 m1 豁免，补"为什么没写"

> 对应问题：F9（"read-only 空产出"被当作合法静默吞掉——实证 coder 读 30 次
> 文件零写盘，被 m1 豁免放掉）。用户决策（2026-08-21）：按建议实施。
> 与 F5 的关系：F5 已让空转可见（empty_artifacts 删 → codegen 空跑走
> incomplete_output 失败信号）；F9 补另一半——空转**可诊断**（为什么没写）。

## 一、本质

m1 豁免（turn_count>=1 ∧ stalled==0 = "合法 read-only"）用**机制特征**（有
tool_use progress）代理"在干活"，但 tool_use progress ≠ 产出（§1.10）。实证的
思考泥潭（读 30 次零写盘）恰落在这个豁免里，最该干预的信号被放掉。

## 二、改动

- `_shared._transcript_write_targets(transcript)`：单 block 提取器
  `_extract_write_target_shared` 之上的整 transcript 写盘判定（与
  `_transcript_orphan_paths` 同源，单一证据源，best-effort）。
- `opencode_backend._maybe_warn_silent_failure`：签名加 `transcript_path`；
  在 m1 豁免分支内查写盘证据——
  - 零写盘 → 报 **read-only 空转**（message 区分"思考泥潭/只读不写"）；
  - 有写盘尝试（含错位孤儿）→ 不在此层报（归孤儿/空跑体系）。
  - 仍只加 WARN（P114 约束：不改 crashed/status/error_type/重试路径）。
- sdk 侧无需对称：P114 WARN 只在 opencode 挂，sdk 走 cut 检测 + resume 计数。

## 三、行为变化披露

- "读了不写"的空转：从 m1 静默 → WARN 明示（read-only 空转 + 供排查提示）；
  下游空跑熔断行为不变（F5/F8 已兜底）。
- 真 silent（无 assistant / stalled）与有写盘尝试（孤儿/空跑）：行为不变。

## 四、验证

- F9 三用例：零写盘报警 / 有写盘豁免 / 真 silent 保留；m1 原用例改 F9 语义。
- 全量 UT 3670 passed / 0 failed（+1）。
