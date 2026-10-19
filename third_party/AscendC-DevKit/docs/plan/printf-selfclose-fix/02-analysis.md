# L3 — 方案分析：printf_location 自闭环修复

## 判定准则（§1.2 四尺子）

| 方案 | 可维护 | 可扩展 | 可诊断 | 架构合理 |
|---|---|---|---|---|
| O1 printf 自闭环（本方案） | ✓ 单一通路，printf 自闭环到 commit | ✓ comment_bisect 可同理改造 | ✓ commit/rollback 全在 printf agent 内可见 | ✓ 职责内聚：定位+修在同一 agent 闭环 |
| O2 保持现状 + 加 stagnation 签名 | ✗ 仍有上下文丢失 | ✓ | ✗ 空转仍需 cycles 兜底 | ✗ 两层 agent 重复查知识库 |

**选 O1**。

## 核心决策

### D1 — 修好 → run_tests，修不好 → skip case → fix

printf 定位到根因后必须自己修。修好 commit → `located_fixed → run_tests`（全量回归）。连续 3 次重试无好转 → exhausted → skip case → `printf_more/printf_done → fix`（让 fix 判断是否还有其他 case）。不再有 `located → fix` 路由。

**理由**：printf 持有完整上下文（探针输出、golden 对比、知识库查询结果），修起来成本远低于 fix 重新理解。修不好就跳过——不让 fix 再做一遍 printf 已经做过的事。

### D2 — 重试策略：有好转不限次数，连续 3 次无好转放弃

不硬编码 3 次上限。diff 逐次下降说明方案在收敛 → 继续。diff 不变或上升连续 3 次 → 放弃。

**理由**：复杂 fix 可能需要多轮调整（改了 A 发现还要改 B），不应在有好转时强行掐断。但无限循环需要出口——"连续无好转"是比"总次数"更合理的出口。

### D3 — printf_done 从 run_tests 改为 fix

当前 `printf_done → run_tests`，但同 failure_type 的 case 被 skip 后直接 run_tests 会重跑出未修复的 case → 又进 fix→printf→skip 循环。改为 `printf_done → fix`，由 fix 判定是否还有 case 可处理。

**理由**：run_tests 是"全量回归确认"，应该在 case 被实质修复后才跑。skip 不是修复——不应该触发全量回归。

## 变更影响分析

### printf agent（自闭环核心）
- 删掉所有 `source="bisect"` fix_plan 生成逻辑
- 新增自闭环修复流程（Edit → build → test → commit/rollback → retry）
- 新增 `PRINTF_FIXED` 返回码

### comment_bisect（不在此次范围）
- comment_bisect 的 `located → fix` 路由和 `COMMENT_BISECT_LOCATED` 返回码**保持不变**——本次只改 printf_location，comment_bisect 后续独立评估是否需要同理改造

### fix 阶段
- fix skill 中 `source="bisect"` 的专门处理（`fix.md:70,119`、`SKILL.md:123`）将因 printf 不再生成此类 plan 而成为死代码——**不在本次删除范围**，留待后续清理（§2.5 单通路收口）
