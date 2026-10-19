# diagnose 流不进二分 — L3 方案分析（2026-08-12）

> 层级：**L3 / 方案分析**。记录「有哪些选项、选了哪个、为什么」。调研演进、拍板后冻结。
> 问题事实见同目录 `01-problems.md`（L1）；具体代码配方见 `03-impl.md`（L4）。

## 目标

在框架层恢复 precision_debug 闭环里「diagnose 静态手段停滞 → 流入设备级二分
（precision → printf_location / runtime → comment_bisect）」的保证，同时：

- **不误伤**有进展的 case（需要多次 diagnose 逐步逼近根因的不应被过早转走）；
- **不依赖** agent 行为改写（框架层确定性保证，而非靠 skill 自觉）；
- **贴近**合并前「diagnose 分析一次 + 轻量实施、用完即转」的快时序。

## 候选选项

### 选项 ① — stall 连续无进展早转二分（业务语义驱动）

新增 diagnose 专属计数器 `diagnose_stalls`：每轮 diagnose 实施后若无任何进展
（case 未解决 + 无 partial output 改善 + 无 runtime 剥皮进展）计一次 stall；连续 **2 次** stall =
「静态手段停滞」→ 立即按 failure_type 降级二分（precision→printf / runtime→comment_bisect / compilation→advance）。
有进展则 stall 清零、继续 diagnose。

- **语义**：判据是「有无进展」（业务语义），不是「spawn 了多少次」（机制特征）。
- **时序**：stall=2 让「需二分」的 bug 在 2 次 diagnose 后即转（对比 cc=6 的 6 次重型 spawn）。
- **与 cc 并存**：cc 仍是 diagnose↔printf 共享的小循环预算（有进展时 stall reset、cc 继续 +1，cc 满=6 仍兜底 advance 换 case）；stall 是「早」判据，cc 是「晚」兜底，各司其职。

### 选项 ② — 固定低 cc 阈值

把 diagnose 转 printf 的 cc 阈值从 6 调到更低（如 2），让 cc 更快耗尽触发转出。

- 问题：cc 是「spawn 次数」机制特征代理——**有进展**的 retry 与**无进展**的 retry 共享同一 cc 计数，
  低阈值会误伤「需要多次逼近才能修好」的 case（每次逼近都有进展，但 cc 仍 +1，未达根因就被转走）。

### 选项 ③ — 限制 B2 增量生成

改 SKILL B2 行为：retry 时不再生成新候选，让 pool 回到单调递减、`pool_exhausted` 重新生效。

- 问题：① 改 skill 行为属「治标」，且 B2 增量生成是另一条产权线（低效来源，非「流不进 printf」产权）；
  ② 依赖 agent 自觉遵守，框架层无构造性保证；③ 增量生成在「症状演化需要新假设」场景有正面价值，
  一刀切禁掉会损失该能力。

## 决策：选 ①（stall 连续无进展早转）

### 选 ① 的理由

1. **§1.10 一致性（决定性）**：横切控制流判据用业务语义（「有无进展」）显式声明，不用机制特征
   （spawn 次数 / 含 subprocess）隐式代理。语义相反的单元会共享同一机制特征——「有进展的 retry」
   与「无进展的 retry」共享 cc，靠 cc 必有一类被静默误判；stall 区分二者。这是 ② 被否决的根本原因。
2. **不误伤有进展的 case**：stall 在有进展时清零，只在「连续多次确实无进展」时才转，保护逐步逼近路径。
3. **框架层确定性保证**：stall 计数与早转分流全在 `transition`（Python）确定性维护，不依赖 agent 行为，
   不受 B2 是否增量生成影响（③ 的依赖问题）。
4. **贴近旧架构时序**：旧 fix 轻量实施用完候选（1~3 次）即转 printf；stall=2 在「无进展」语境下
   同样是「少量尝试即转」，恢复合并前的快时序，而非 cc=6 的慢路径。
5. **不阻塞 B2 优化**：B2 增量生成的低效（每次 retry 都重新假设）属另一条线，本方案不动它；
   若后续优化 B2，stall 早转与低 cc 兜底依旧各自正确归位（可扩展性）。

### 四把尺子复核（§1.2）

| 尺子 | stall 早转方案 |
|---|---|
| **可维护** | 维持 precision_debug 既有的「diagnose 搞不定 → 二分」不变式；与 cc/run_iter/refine 等既有计数器同族，同生命周期 reset |
| **可扩展** | 同类新情况（新 failure_type）自动正确归位——按 failure_type 分流（compilation 仍 advance、precision/runtime 降级二分），不为已知算子/已知 case 打补丁（§1.12） |
| **可诊断** | 早转走既有的 `need_printf`/`need_comment_bisect` 路由（转换表已有），可观测；瞬态标志 `_stalled_to_bisect` 只活一次 resolve_condition、不持久，无 sticky misfire |
| **架构合理** | 落在职责正确的层——「该不该降级二分」是控制流裁决，归 `transition`/`resolve_condition`（编排层），不越层让 agent 或 skill 决定 |

### 致命约束（实施必须守住）

diagnose 与 printf **共享同一个 `cp["corrective_cycles"]`**（diagnose `transition` 与 printf `transition` 均读写，
max=6；printf `resolve_condition` cc 满 → printf_done）。故 diagnose stall 达阈转 printf 时，
**必须 reset cc=0**，给 printf 全新预算，否则 printf 一接手 cc 就已近满、瞬间 printf_done 出组。
该 reset 在 `transition` 早转块内完成，瞬态标志 `_stalled_to_bisect` 写 dc（非 cp），下轮
`_extract_debug_checkpoint` 重建即丢，避免标志误触发。

### 收敛性证明（框架层 backstop 链）

- **precision 需二分 case**：diagnose#1 无进展 stall=1 → retry；diagnose#2 无进展 stall=2 →
  reset cc + need_printf；printf cc=0 全新预算二分（自带 cc 耗尽 advance）→ printf_done → run_tests
  （reset stall=0、cc=0）。每轮 2 corrective，`max_corrective=30` → ≥15 轮保证。
- **precision 可逼近 case**：diagnose 有 partial/case_resolved → stall reset 0 继续逼近；
  若多次逼近仍耗满 cc，cc 耗尽 advance 块（保留原样）兜底换 case，run_tests 回归后 cc reset 再处理。
- **stall 与 cc 不互扰**：无进展时二者同步 +1，stall（阈 2）必先于 cc（阈 6）达阈触发降级（此时 cc 仅=2）；
  有进展时 stall reset 而 cc 继续，只有「逐步逼近」路径让 cc 单独达 6 走兜底 advance。
- **runtime 对称**：comment_bisect 共享同一 cc，方案完全对称，无需改 CommentBisectSubstage。

## 不在本次范围

- B2 增量生成的 skill 行为优化（低效来源，非「流不进 printf」产权）——留独立工作线。
- scope_guard / bounds_check 路由不动（本问题仅限 diagnose → 二分的流入保证）。

> 具体改哪个函数、什么顺序、怎么验证见 `03-impl.md`（L4）。
