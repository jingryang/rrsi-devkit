# VF 并行派发跨模板混批 — 问题/需求记录（L1）

> 纯事实快照（哪里坏了 / 需求是什么）。不提方案、不排顺序、不写决策。
> 来源：真实 run `20260831-223250`（log_softmax / A5 Regbase / ascend950，opencode backend），
> `events.jsonl` + 会话 DB + `orchestration_plan.json` 实证；用户需求陈述（2026-09-01）。

## 触发场景

A5 Regbase s4 的 `.VT.{M}` 子步骤采用「先串行后并行」：
plan 首个 VF 步骤（4.C.3.VT.0）done 前只派发它一个（串行建立 `vf_verified` 脚手架），
完成后其余 pending VF 每 iteration 并行派发至多 `max_concurrent_vf=2` 个
`ascendc-vf-test-agent`（`codegen.py:_actions_regbase_vf`）。

## 观察事实（log_softmax run）

- plan 有 5 个 VF 步骤：`4.C.3.VT.0 / 4.C.3.VT.1 / 4.C.6.VT.0 / 4.C.6.VT.1 / 4.C.6.VT.2`，
  夹在普通编码步骤之间（`4.C.3`、`4.C.4/4.C.5` 位于两组 VF 中间）。
- 实际派发批次：
  1. `4.C.3.VT.0`（串行 bootstrap）
  2. `[4.C.3.VT.1, 4.C.6.VT.0]`（跨模板混批：T1 的 VT.1 与 T2 的 VT.0 同一批）
  3. 4.C.3、4.C.4+4.C.5（普通步骤插队）
  4. `[4.C.6.VT.1, 4.C.6.VT.2]`（T2 剩余 VF 才轮到）
- 后果：`4.C.6.VT.0` 在 4.C.3~4.C.5 之前提前并行执行；`4.C.6.VT.1/VT.2` 被排到普通步骤之后，
  与 plan 序的自然归属（T1 VF → 4.C.3 → 4.C.4/5 → T2 VF → 4.C.6）错位。

## 需求（用户陈述）

- VF 并行按**模板组**隔离：`4.C.3.VT.X` 组内并行处理，`4.C.6.VT.X` 组内并行处理；
  不跨模板混批。
- 保留现有「全局首个 VF 串行 canary」规则（plan 第一个 VF 仍单独先跑一遍建脚手架）。

## 边界

- 不改 `max_concurrent_vf` 上限（组内仍受 cap 约束，T2 三 VF 会分批 2+1）。
- 只改并行批次的成员选取（组内过滤），不改 plan 顺序推进语义、不改重试/升级逻辑。
