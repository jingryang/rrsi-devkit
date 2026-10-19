# 01 — 问题记录（L1）

> 本工作：`docs/plan/precision-teardown-turnstall-mismatch/`。只记**客观事实**（哪里坏、
> 凭什么这么说），不提方案、不排顺序、不写决策（那些归 L3/L4）。

## P1 — teardown 回退的触发条件错配：turn_stall（网关静默）被误触发「清理半成品」回退

### 现象

- unique 单算子 resume（execution `20260816-163138-e26179`）的 precision_debug diagnose
  阶段，`turn_stall`（网关静默，120s 无新 turn + chars static）触发后，框架执行：
  `precision-debug teardown (hard_timeout): rolled back op_dir to best_commit`
  （`git checkout <best> -- op_dir` + `git clean -fd -- op_dir`）。
- 随后 `infra_backoff` re-spawn + `agent_resume` 续同一 session（上下文保留）。
- 结果：agent 的记忆上下文（「我改了 XXX」）与代码状态（已回退到 best_commit，XXX 没了）
  **不一致**——resume 续跑的 agent 以为自己的修改还在，实际已被回退。

### 根因（事实层）

- teardown 的**设计意图**（`base.py:114` docstring + `precision_debug_substages.py:1389`）：
  「hard-timeout interruption 的 cleanup——precision debug 还在执行被中断，回退到相对
  完整的代码」。即 teardown 回退 = 清理「**超时中断时的半成品代码**」。
- 但实现的**触发条件用 `aborted`**（`runner.py` `if _abort: _run_stage_teardown(...)`），
  把 `aborted="turn_stall"`（网关静默）也囊括了。
- `turn_stall` 的本质 = **网关静默**（agent POST 后 chars static，在等网关响应），上一个
  `tool:edit`/`tool:bash` 已原子完成，**代码完整、无半成品**。teardown 的「清理半成品」
  目的对 turn_stall 不适用。

### 正确判据（用户拍板）

- teardown 回退应只由「**超时类中断**」触发：**硬超时**（`hard_timeout`）+ **软超时**
  （`soft_timeout`，现无对外暴露实现，但语义同属「超时」）。
- 超时类 = agent 执行中被超时杀，**可能半成品** → teardown 清理。
- `turn_stall`（网关静默）= 代码完整、无半成品 → **不该 teardown**。

### 连带影响（事实）

- turn_stall 被误回退 + 随后 resume 续 session，导致「记忆 vs 代码」不一致（agent 以为
  改了，实际被回退）。teardown 只对超时类触发后，turn_stall 不再回退，resume 续跑时代码
  与记忆一致。

## P2 — 同一问题 11 天后在批 99c4c0 复现 ×5（含超时类 abort 同样制造发散）

- 本 L1 记录于 2026-08-16（execution e26179）；2026-08-27 批 20260826-114823-99c4c0
  unique diagnose 四次 kill（3× turn_stall + 1× hard cap）**每次都执行**
  `repo_rollback op_dir restored to a5af7431f917 (checkout+clean)` 后 resume 同一
  session（run.log 5701/5720/7213/7871），最终 teardown 再回退一次（7875）。
- 代码现状未变：`runner.py:383` 对**一切** aborted 触发 `_run_stage_teardown`；
  precision teardown（`precision_debug_substages.py:1479`）**收到
  `interrupt_reason` 参数但完全不用**，无条件 rollback。
- 后果实证：kill-1（02:10）销毁 01:55–01:59 共 12 次 edit 的 S1MergeRank 重做
  （未提交）；w3（03:11–03:45）重做同族工作（9 commits，含提前返回/探针/yLen 兜底
  ——与 w1 已做的高度重叠）；kill-4（05:49）把 39min 内收敛到 507035 真根因的
  修复 6d59046 从工作树剥掉。

## P3 — 2026-08-16 的拍板判据（按 abort 种类分）不完备：hard_timeout 也会 resume

- 该拍板：teardown 回退只由「超时类中断」（hard_timeout/soft_timeout）触发。
- 99c4c0 反例：kill-4 是 hard cap（workflow 墙），若按 0816 判据照样 rollback——
  但 runner 的 infra-retry 对 hard_timeout 后**同样 re-spawn + resume**（05:10 形态），
  发散照旧（w4 的 6d59046 被剥）。
- 事实层结论：**判据不是 abort 种类，是「循环是否还要继续」**——resume ⇒ 任何
  rollback 都制造「记忆 vs 代码」发散；只有 debug 真退出（halt/预算尽/abort 耗尽/
  正常收敛）进最终 teardown 才该回退。（用户 2026-08-27 表述：「普通的 resume 根本
  不应该动代码，只有 debug 真的要退出、进入 teardown 才需要 rollback」。）

## P4 — 跟踪体系失效事实：本 L1 孤儿化 11 天，未进 L2、未实施、git 未跟踪

- 本目录自 2026-08-16 起只有本文件：无 L3/L4；
- 未进 L2 索引（`skills-integration-and-tdd-plan.md` 查无此工作）；
- git untracked 至今。期间同族问题至少再发作 5 次（P2）。
- 过程事实：分析正确、拍板在案，但「L1 写完不入 L2」= 从实施视野消失——本身是
  step-96「事实不流转」家族的跟踪层实例。
