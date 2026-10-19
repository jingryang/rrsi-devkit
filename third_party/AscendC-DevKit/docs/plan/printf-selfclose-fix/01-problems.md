# L1 — 问题记录：printf_location 只定位不修，上下文丢失致 fix 阶段反复空转

## P1 — 上下文丢失（严重）

**事实**：printf_location agent 通过探针二分定位到具体行号的数值发散点后，不修复代码——而是将根因写成 `fix_plan(source="bisect")` 入 `candidate_pool`，交还 fix 阶段。fix 重新 spawn、重建上下文、重读 kernel 代码、重新查知识库才能验证和修复。printf 定位时持有的探针输出、golden 对比、公式拆解、API 文档查询结果在 handoff 中全部丢失。

**证据**：
- `ascendc-precision-printf-locate.md:65-67`：定位到根因后"Generate a new fix_plan; add to control.json.candidate_pool.hits with source='bisect'"
- `precision_debug_tree.py:86`：`"located": ("fix", "corrective")` — 交 fix
- `ai_infra_aggregate_hidden_grad` 实操：fix-03（177 轮）花大量 token 查知识库确认 API、试方案、编译测试，而这些 printf 定位阶段已经做过一遍

**影响**：简单 case（改一行 Cast、调一个参数常量）也至少多花一轮 spawn + 数十轮 LLM 上下文重建。

## P2 — 复杂 case 无人兜底（严重）

**事实**：fix 阶段验证 bisect plan 失败后（如 plan `edf0eb63-kernel-syncall-reduce` 因 optiling 限制不可行），走 `pool_exhausted → need_printf → printf_location` 再进 printf，printf 可能再次二分到同一段代码、生成类似 plan——形成 `fix → printf → fix → printf` ping-pong，靠 `corrective_cycles=8` 兜底。中间每一轮都是真实 LLM 全流程消耗。

**证据**：
- `precision-debug-loop-control/01-problems.md:44`：`fix.need_printf → printf_location.located → fix` 构成无计数器的双向边
- `precision_debug_substages.py:1541-1549`：corrective_cycles=8 才 `_advance_past_failure_type`

## P3 — PRINTF_LOCATED 路由引出的死代码问题（中等）

**事实**：改为 printf 自闭环后，`PRINTF_LOCATED` 和 `"located"` 路由将成为死代码——printf 不再生成 fix_plan 交 fix。受影响文件约 10 处（详见 03-impl.md）。

## 关联问题

- [[precision-debug-loop-control]] P1：闭环不自我收敛
- [[precision-debug-agent-abort]] P1-P3：agent 中断无检测
- [[precision-runtime-comment-bisect]] 同架构的 comment_bisect 也可类推（待后续评估）
