# ForkJoin 分支失败在 join 点无处理 — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。
> 用户已拍板（2026-07-18）：① 记录落点＝独立目录 `forkjoin-branch-halt/`；② 修复范围＝ A+B+C 组合根治。

## 问题本质：一个根缺陷，两个正交面

P1（merge 崩溃）与 P2（join 丢 halt 信号）不是两个孤立 bug，而是同一架构缺口的两面——
**fork-join 的 join 点缺失「失败分支处理」**：

- 控制流层面：join 不检查分支的 failed/terminal 状态，无差别进入 merge、也不把停止意图传出（P2）。
- 数据层面：merge 本身对失败分支从未写入的字段（None）不设防，把它当合法冲突写入而崩溃（P1）。

因此单独修任一面都不完整：只修 P1（让 merge 宽容）会把崩溃换成「静默带病前进到 anchor」（见
`01-problems.md` P2 推论），更糟；只修 P2（传 halt 信号）而不动 merge，则 merge 仍可能对某些
失败形态崩在信号传播之前。故按 CLAUDE.md §1.2 **组合修复**：正确改动承担主修复保不变式，
宽容兜底做 last resort 防崩，可观测性确保不静默。

## 决策 1（P1+P2）— 修复范围：仅止崩 / 仅传信号 / A+B+C 组合 → **选 A+B+C 组合**

| 动作 | §1.2 角色 | 内容 |
|---|---|---|
| **A. join 传播 halt 信号** | 正确改动（保不变式） | `_execute_forkjoin` 检测到任一 ran 分支 failed / `is_terminal` 时，把该分支的 `is_terminal=True` + `halt_reason`（点名 `<模板>/<segment>` + 原因，沿用分支 state 已算出的信息）提升到 merged state，使 `fail_strategy=halt` 语义在 fork-join 内成立、父 sequential 据 `is_terminal` 停、不进 anchor |
| **B. merge 对失败分支设防** | 宽容兜底（last resort） | `merge_forkjoin` 跳过 failed 分支 / 值为 None（从未写入）的字段，只把**成功分支**的真实 dict 折叠进 base；既不崩，又把成功兄弟（T2）结果并入 state 落盘 → resume 只重跑失败的 T1、跳过已成功的 T2 |
| **C. join 可观测** | 可观测性（不静默） | 失败分支进 join 时 `Logger.warn` 点名分支 + 原因；`halt_reason` 落 snapshot 供 dispatcher 终止文案与事后复盘 |

**选 A+B+C 的理由（四把尺子）**：
- **可维护**：与既有 halt 机制一致——P46（硬崩溃给 halt stage 补 `_stage_failed`）、step-50 P3
  （`halt_reason` 字段 + dispatcher 消费）已在**顺序链**上建立「halt 干净停 + 点名 + 落盘」范式，
  本方案是同一范式在 **fork-join 边界**的补齐，不新造机制。
- **可扩展**：修在通用的 `_execute_forkjoin`/`merge_forkjoin`，对任何 fork-join（tiling / anchor /
  未来新增并行组）自动生效，不为 tiling 单点打补丁。
- **可诊断**：C 把「哪个分支、什么原因」从崩溃 traceback 变为结构化 `halt_reason` + WARN，
  正是本次事故最缺的信号；B 不掩盖错误（失败分支照样使 group failed + halt），只避免把错误
  推迟到更下游（§1.2「不把错误静默吞掉、推迟到更难定位的下游」）。
- **架构合理**：修复落在 join 点（fork-join 的职责边界），不在分支线程里跨线程兜底、也不在 dispatcher
  层猜测。成功分支结果仍正常 merge 落盘（resume 语义正确），失败分支只影响停止与重跑。

**否决**：
- **仅 A+C（不动 merge B）**：merge 仍可能对某些失败形态（字段值恰为其他非 dict 类型）崩在
  信号传播之前，兜底不全；且「失败分支的 None 字段参与 merge」这一数据面缺口未闭合。
- **仅 B（只止崩）**：见 `01-problems.md` P2 推论——把崩溃换成静默带病前进到 anchor，比现状更糟。

## 决策 2 — 是否在分支失败时中止其兄弟线程 → **不中止，只在 join 处理**

fork-join 用 `ThreadPoolExecutor.map` 已**等全部分支返回**，无早退取消机制。可选「T1 halt 时抢跑
中止 T2」，但**不采纳**：
- T2 的工作是有效的、其结果应落盘供 resume 跳过（本 run T2 确实成功，resume 时正应跳过它）。
- 抢跑中止需引入跨线程取消信号，复杂且违背「成功分支结果不浪费」。
- 正确形态就是 Run 2 实际发生并成功的路径：join 干净 halt → 落盘成功分支 → resume 从失败分支
  重跑。故修复只落在 **join 点**，不动分支并发模型（沿用 step-12 Phase 3 的 ForkJoin 骨架）。

## 决策 3 — `halt_reason` 复用 step-50 已建字段，不另立

step-50 P3 已在 `State` 上建 `halt_reason: dict|None`（`{"kind","stage","message"}`）+ dispatcher
终止分支消费。本方案 A 直接复用该字段与消费路径：`kind` 沿用 `"fail_strategy_halt"`，`stage` 填
`<模板>/<segment>`（如 `T1_large_reduce_split/split`），`message` 沿用分支 state 已有的失败原因。
不新增 State 字段、不改 dispatcher 消费逻辑——只是让 fork-join 边界也能写入这个既有字段。

## 决策 4 — Run 2 的 anchor 阶段中断：不登记为代码问题

`01-problems.md` 已界定 Run 2 在 anchor-forkjoin 两个 agent 运行中被中断（`state_snapshot`
`is_terminal=None`/`halt_reason=None`/`anchor_template_reports=None`，events 末条是 `spawn_context`，
无结束/崩溃/halt）——是进程被杀/容器停的运行环境问题，非框架缺陷。resume 可从 anchor 继续。
不安排修复，仅作事实留存。
