# L3 方案分析 — refine_cycles 主动路径计数 + abort 熔断路由 run_tests

> 层约定：L3 记录选项与取舍（调研中演进、拍板后冻结）。

## 步骤 1：refine_cycles 计数语义

**问题**：剥皮链配额该对哪些进入路径计量？

**选项 A（采用）**：只对主动路径（`fix.applied_partial`）计数。
- 实现：fix 判定 `applied_partial` 后置持久化标记 `refine_pending`；diagnose_refine 消费式读取（`pop`）——有标记才 +1，消费后移除防跨轮残留。
- 理由：主动剥皮 = 真正的「洋葱剥一层」，被动线性落点是路由兜底（不剥皮），不该烧配额——业务语义显式声明（§1.10），不用机制特征代理。
- 风险：标记接力依赖跨 stage 文件持久化（§2.3）——必须落盘（B1：曾因 `_append_history` 磁盘重载而丢失）。

**选项 B（否决）**：维持无条件 +1。
- 否决理由：P1 后果①②原样保留。

## 步骤 2：链满路由

**问题**：`refine_cycles > 3`（链剥到头）后去哪？

**选项 A（采用）**：回 `run_tests` 全量回归（`refine_done` → `("run_tests", "linear")`）。
- 理由：链剥到头 ≠ run 失败，当前 best_commit 需回归验证；run_tests §P2 清零 refine_cycles 使下一条链从 0 重计（跨回归单链语义，同 corrective_cycles）。linear（§quota-exempt）对齐 printf_done/bounds_check fixed 先例——回归验证不受框架 corrective quota 计量。
- 墙钟预算（`_time_budget_exhausted`）仍走 `exhausted` 出组——墙钟上限是全 run 止损，语义不变。

**选项 B（否决）**：`exhausted` 出组。
- 否决理由：P1 后果③（验证通道丢失）。

## 步骤 3：abort 熔断路由

**问题**：`consecutive_aborts ≥ 阈值` 后去哪？

**选项 A（采用）**：非 run_tests 阶段路由 `run_tests`（`("run_tests", "linear")`），触发即清零。
- 理由：abort 是瞬态（agent 死亡/超时），熔断 ≠ 调试失败——回 run_tests 走主循环（run_tests→diagnose→fix→run_tests）让 best_commit 重新接受回归验证；触发清零（§abort-reset：cp 归 0、dc 保留触发值供判定）防单链累计误杀后续路径。
- 终止兜底：rounds/max_iterations（run_tests 每次 spawn 推进）+ time_budget_sec（36000s），不靠 abort 计数出组。
- 例外：`run_tests` 自身熔断仍 escalate（测试环境死亡，回 run_tests 无意义）；`scope_guard` 仍 escalate（回 run_tests 会立即再 needs_scope_check 循环，守卫失败即出组）。

**选项 B（否决）**：全部保持 escalate。
- 否决理由：P2 后果①。

## 步骤 4：abort 阈值

**问题**：`_ABORT_EXHAUST_THRESHOLD` 取多少？

**选项 A（采用）**：2。
- 理由：用户指定（run 实测中 abort 频发，1 次瞬态自环重试已足够吸收抖动，第 2 次即熔断回主循环——回主循环本身就是重试，无需像旧设计（出组）那样多留余量）。
- 说明：未配置化（保持常量）；语义从「出组前重试次数」变为「回主循环前的重试次数」，余量需求降低。
