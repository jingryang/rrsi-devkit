# 01 — 问题记录（L1）

> 本工作：`docs/plan/turn-stall-pretrip-evidence/`。只记**客观事实**（哪里坏、凭什么
> 这么说），不提方案、不排顺序、不写决策（那些归 L3/L4）。
>
> 实证：批 20260826-114823-99c4c0 unique（execution 0f7ba0）precision_debug diagnose
> 会话 `ses_fc1107a51ffePowfT1kY3rkBO4` 的四次外部 kill（2026-08-27 00:37–05:49 CST）。
> 证据源：execution run.log、opencode per-execution db
> （`.opencode_home/data/opencode/opencode.db` part 表）、算子 worktree git log。

## P0 — 四杀分类总表（每杀都有 db 取证）

| kill | 时刻/判据 | 被杀前最后事实（db part 表） | 定性 |
|---|---|---|---|
| kill-1 | 02:10:09，no new turn 608s > 600s | 01:55–01:59 连续 12 次 edit（S1MergeRank 重做）+ redeploy 编译通过；01:59:48 bash（env export）6ms 完成；**02:00:01 step-finish 后再无任何 part** | 工具已完、静默 608s（模型静默 or opencode 内部静默重试，不可分） |
| kill-2 | 02:22:18，609s | bash 已完成（dlopen OSError 回栈），之后静默 | 同 kill-1 人群 |
| kill-3 | 03:58:16，691s | **bash part `status:"running"`**（03:48:11 起 605s），部分输出已落盘：`n=458752 run1: ⏎ run2: ⏎`（空结果 = kernel 挂死在设备上） | **工具在飞被判死** |
| kill-4 | 05:49:11，exceeded 2331s hard cap | 05:48:03 仍在 commit（42a4905），05:48:00 还在编辑 tiling.cpp | 2331s = workflow 墙（见 P4） |

每次 kill 后均发生：`repo_rollback`（工作树还原到 best_commit=0/20 入口 a5af7431）→
re-spawn + resume 同一 session。后果链见
[`precision-teardown-turnstall-mismatch/01-problems.md`](../precision-teardown-turnstall-mismatch/01-problems.md) P2/P3。

## P1 — 看门狗判死只有传输观测面：bash 执行期三信号同时失明，而事实躺在同机 db 里无人消费

- 判死代码：`opencode_backend.py:1650-1700`（turn_stall 门）+ `:1701-1705`（keepalive
  门）。观测面 = SSE 流的三个信号：`turn_ts`（新 turn）、`chars`（文本增量）、
  `last_event_ts`（任意帧）。
- 代码自认（`:1655`）：「opencode emits no SSE progress during a tool call」——bash
  执行期三个信号**同时**静止，turn_stall 与 keepalive 双盲。
- 同机可查的事实（kill-3 实证）：opencode 自己的 db 里，tool part 在执行期即携带
  `status:"running"` + `time.start` + **增量输出**（`metadata.output`）——「正在跑哪条
  命令、跑了多久、已吐什么」全在盘上。框架从未读它。
- §P9 语义修复被配置收敛**数值清零**：`:1671-1675` 对 tool 活跃 turn 放宽
  `stall_bound = max(turn_stall_s, keepalive_idle_s)`，但 P9 复盘把两旋钮「收敛为一个
  语义」、都=600（`runtime_config.py:786-789`）——`max(600,600)=600`，让位公式恒等于
  零效果。本批 kill-1/2/3 的 kill 消息均显示 `stall bound 600s`（blocks 含
  `tool:bash`）。

## P2 — kill 对象错误：该杀挂死的工具子进程，实际杀了整个 serve+session

- kill-3 形态下正确处置对象 = 挂死在设备上的 bash 子进程：杀掉后 opencode 把工具
  错误交还 agent，agent 带事实继续（session/上下文/工作树全保住）。
- 现状 `_stop_serve`（`opencode_backend.py:1721+`）kill 整个 opencode serve：
  session 终止、上下文靠 sidecar resume 重建、工作树随后被 teardown rollback（另案）。
- 机制事实：SIGKILL serve 不杀其子进程（POSIX 孤儿化）——挂死的验证进程**继续占卡**。
  本批收尾时人工清理的「后台挂死算子进程」中即含此类孤儿（精确逐个溯源未做，机制
  归属成立）。

## P3 — 静默归属不可分：kill-1/2 的「模型静默」无法与 opencode 内部静默重试区分

- `.opencode-serve-36449.log` 全文仅 2 行（启动 banner）——serve 不记请求日志；
  opencode 内部限流重试只在 opencode.log/内部 db（既往 P117/盲区记忆已坐实）。
- kill-1：最后一个 part 是 02:00:01 `step-finish`（工具结果已交还、已 POST 模型），
  之后 608s 零 part——模型侧静默成立，但**网关重试退避 vs 真死**不可分。

## P4 — kill-4 的「2331s hard cap」= workflow 墙，非 spawn 预算

- `dispatcher.py:488-502`：每次 spawn 的 eff_msg_timeout =
  `min(max(remaining_deadline,1.0), message_timeout_default=14400)` ——deadline 为
  workflow/stage 剩余预算。
- w4 于 05:10:03 spawn，10h workflow 墙约 05:48–05:49 到期 → mt=2331s：**w4 出生时
  全部剩余寿命 39 分钟**，杀在其最高产的编辑流中间（39min 内 7 commits 收敛到
  507035 真根因修复 6d59046，随后被 rollback 剥掉）。
- 截断态本身的一等化问题归
  [`converge-tail-reverification/`](../converge-tail-reverification/01-problems.md)
  P6/D4，本工作只取「墙前不该杀正在产出的会话」这一事实。

## P5 — opencode 工具层超时行为未证实

- kill-3 的 bash 至少 605s 无工具层终止（03:48:11 起，03:58:16 框架 kill 时刻仍
  `running`）——opencode bash 是否有内建超时、多长，未验证（实施期查证）。

## 待调研问题（L3 调研态）

1. pre-trip 取证的工程细节：per-spawn XDG（`opencode_backend.py:1364`）→ db 路径
   可从 backend 实例派生；sqlite 只读并发（WAL？busy 风险）；查询失败的退化语义；
2. 「杀工具不杀 serve」的进程定位：serve pid 已知 → 子进程 cmdline 与 db part 的
   command 文本匹配；匹配失败的退化路径；
3. 工具容忍界（tool grace）的量级与配置位（设备验证合法时长上限的实证基线）；
4. opencode bash 工具是否支持超时配置（版本查证）；
5. **SDK 后端（claude）平行面（2026-08-27 审计补记，未实证）**：`sdk_backend` 有
   同名 turn_stall 看门狗（网关静默 trip）——SDK 路径工具执行期是否同样无流事件
   未实证；差异点：SDK 无 opencode db 可作证据通道、其 Bash 工具层自带超时、
   无误杀事故记录。**不机械照搬**（§1.2/§1.14：无实证不预建）；若 SDK 侧出现
   同形态误杀（kill 时工具在飞），按本工作方法重开（证据通道需另行设计）。
