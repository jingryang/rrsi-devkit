# P1 timeout 归位 pause 家族 — L3 方案分析（2026-08-30）

> 层级：**L3 / 方案分析**。记录选项、取舍、决策。拍板后冻结。
> 问题记录见 `01-problems.md` P1（层产权：证据在 L1，此处只引用）。
> 实施配方见 `03-impl-timeout-pause.md`（L4）。

## 一、决策问题

P1 的可修点收敛为一个语义判定：**`WorkflowTimeoutError` / `StageTimeoutError` 发生时，
op_dir 的处理应属于哪个家族——preserve（保现场，供 resume）还是 rollback（销毁还原）。**

## 二、现状家族分布（dispatcher 终止分支，2026-08-30 代码事实）

| 分支 | 树处理 | 代码内自述理由 |
|---|---|---|
| RunnerCancelledError | preserve | 用户主动中断，禁破坏性自动还原（git_safety） |
| DecisionPendingError | preserve | pause，resume 后继续 |
| **WorkflowTimeoutError / StageTimeoutError** | **rollback** | （无注释——唯一没有自述理由的破坏性分支） |
| PreconditionError | rollback | halt：必需上游产物缺失，下游无法运行 |
| EnvironmentNotAvailableError | preserve | 「非代码缺陷 → 产物保留供检查/复用，而非丢弃」 |
| CardAcquireTimeout | preserve | 「资源短缺不是丢弃产物的理由」 |
| KeyboardInterrupt | preserve | 同 cancel + 打印 resume 提示 |

关键观察：工程已经收敛出明确原则——**「非代码缺陷的终止 → preserve」**（env/card 分支的
注释是明文）。timeout 是预算耗尽，比环境缺失**更不是**代码缺陷，却是该原则下唯一仍走
销毁的分支。同时 timeout 分支**一边落 state snapshot（支撑 resume）一边清树（制造
resume 记忆分叉）**，自相矛盾（L1 P1 已证）。

## 三、选项空间与取舍

| 选项 | 内容 | 结论 | 理由 |
|---|---|---|---|
| **(a) timeout → preserve** ✅ | 分支改走 `_preserve_repo_with_hint` | **选定** | 与 env/card/cancel 的既有原则一致；修复「落 state + 清树」的自相矛盾；改动最小 |
| (b) 真终局 | timeout 时连 state snapshot、session sidecar 一起清 | 否决 | `_load_state_from_run` 无快照回落 `State.empty()`（dispatcher.py:1531-1537）→ resume 退化为整跑重来，前一趟预算（含设计链 ~5h）全部作废；否定既有续跑实践（批对 exit 124 提示 RESUME=1） |
| (c) 维持现状 | 不改 | 否决 | 即 bug 本身：resume 起来 coder 会话记忆「已写完」与空树分叉（step-98 在 stage teardown 层修过的同型问题在此未对齐） |
| (d) 清树 + 只清 sidecar | 回滚树、清 coder 会话锚点 | 否决 | 自洽但把可抢救的 codegen 产物（本批 logcumsumexp 15 文件、interpolate 全套）扔掉——正是 P1 立案要消除的损失 |
| (e) 配置开关二选一 | env var 选择 rollback/preserve | 否决 | §1.4：不留兼容层/过渡态；语义二选一必须拍死 |
| (f) abort 边界读盘验收（讨论早期提案 A） | cut/abort 边界做 sections+manifest 结构验收，合规即视为产物交付 | 否决 | §1.14「控模型」结构；结构性校验判不出重构中间态的内部不一致（kernel 改了 tiling 没跟上）；build/smoke 才是真值仲裁，预验收不承载真值 |
| (g) timeout 前结构验收、合规才 preserve（讨论早期提案 B） | preserve 前加验收门 | 否决 | 同 (f)：画蛇添足；验收通过的 build 也可能挂、不通过的也可能过，这层门不承载真值只添 bug 面 |
| (h) 收尾 nudge / 预算可见性（讨论早期提案 D） | 告知 agent 剩余预算促其收尾 | 否决（本步内） | opencode POST 黑盒无中途注入点，只在 cut/retry 边界可落地；属 P5/P12 领域 |

## 四、选定方案的原则符合性

- **§1.2 四把尺子**：可维护——消除语义错位而非新增机制；可扩展——任意 stage 的 timeout
  自动正确；可诊断——preserve 自带手动回滚命令 + resume 提示；架构合理——改在 dispatcher
  终止处理层，职责正确。
- **§1.10**：判据是业务语义（「预算耗尽 = 没做完 = pause 家族」），不是机制特征
  （不按 worktree/非 worktree、不按是否 spawn 分支）。
- **§1.14**：纯删结构（删除 timeout 分支的销毁行为），不新增任何 gate/checker。
- **§1.15 + §2.5**：preserve 家族 6 个分支重复的 `latest_state → preserve → snapshot`
  收敛为单点 helper（改动时收敛，不复制第 6 份散点）；rollback 家族仅剩 PreconditionError
  一个成员，不抽象（无重复不触发 §1.15）。
- **§1.4**：直接改干净，无开关、无过渡层。
- **§1.13 / §2.x**：不涉及 golden 与 skill，无适用项。

## 五、效果边界（诚实声明）

本方案把 logcumsumexp/interpolate 类失败从「全丢」变为「resume 现场一致地续跑」。**不承诺
resume 后成功**——续跑后 coder 的收尾效率取决于 P5（判定不终止）、P8（吞吐）、P12（预算
可见性），由各自的问题跟踪，效果不计入本方案。

## 六、风险与已知语义

1. 非 worktree 直跑用户仓：timeout 后树留未完成改动。与 cancelled/env/card 分支现状一致
   （先例），preserve 消息自带精确手动回滚命令。
2. resume 后 fresh-run 边界：下一次新 run 启动时重新捕获 baseline，脏树成为新基线——
   记录为已知语义，不加特判（§1.10）。
3. precision 族 resume：precision_debug 有自己的 best-commit 收敛（step-96/98「resume ⇒
   不动树」），与本方案语义一致，无需适配。
