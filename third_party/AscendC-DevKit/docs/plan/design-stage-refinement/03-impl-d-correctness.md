# step-8 L4-d 正确性/健壮性实施记录（§P7）

> 层级：**L4 / 实施记录**。决策依据见同目录 `02-analysis.md` §P7；问题证据见 `01-problems.md` P7。
> 本份记录 §P7 的正确性底线项。按优先级分批推进，每项配单测/ST。

## §P7.1 失败不再伪装成功（已完成，正确性底线）

### 问题（01-problems.md P7.1）

非控制流异常被吞、stage 仍打 `✓ done`：
- `graph_executor._execute_atomic` 对非控制流异常 `Logger.error` 后**照常标 `completed` 并线性前进**；
- `runner.run_stage` 恒以 `status="ok"` 调 `stage_done` / progress_callback，即使 agent_result 是
  `partial`（崩溃但抢救出文件）/`fatal`；
- 父 group 与 workflow root 无条件标 `completed`，dispatcher 据此返回 0。
- 结果：失败 stage 对外显示成功，CI/调用方无从察觉"未交付"。

### 修复（三层 + 退出码）

1. **`Logger.stage_done(status=)`**：新增 status 参数，glyph 区分 `✓`(ok) / `⚠`(partial) / `✗`(failed)，
   非 ok 追加 `[status]` 便于 grep。默认 `ok` 保持向后兼容。
2. **`runner.run_stage` 状态推导**：从最后一个 agent_result.status（非 ok/empty_artifacts → 失败；
   partial → partial）、`last_error`（schema/缺产物 → failed）、未满足的 output_contract（→ partial）
   推出 stage 真实状态，传给 stage_done + progress_callback。`empty_artifacts` 视为 ok（合法无产出）。
3. **`graph_executor._execute_atomic`**：吞掉非控制异常时标 `node_status[path]="failed"`（**不再 `completed`**）
   并打 `✗`。保留"线性前进不硬崩"语义，但失败可见、且 resume 不会跳过（resume 只跳 `completed`）。
4. **group/root 失败传播**：新增 `_group_status()`——任一直接子节点 `failed` → group 标 `failed`
   （顺序组 + fork-join 组各分支均如此），逐级冒泡到 root；root != `completed` ⇒ dispatcher resume
   视为有未完成工作、重跑落到失败叶子。
5. **dispatcher 退出码**：fresh-run 结束时若 `node_status` 含 `failed` 节点 → 打 error 列出失败 stage
   并返回 `EX_DATAERR`（不再返回 0）。与既有 `is_terminal`（`__halt__` 路径）退出码并存。

### 测试

- `test_logger_artifacts.py` +4：glyph 随 status（ok/partial/failed/默认）。
- `test_stage_failure_status.py`（新建 12 例）：runner 状态推导（ok/empty_artifacts/partial/fatal/
  compile_error/未满足契约）、stage_done glyph、_execute_atomic 标 failed 不标 completed、
  失败叶子向顺序组/root 传播、全 ok 叶子保持 completed。
- ut 全量 1186 passed。

### 副作用：解蔽了两个被吞掉的潜在缺陷（值得记录）

§P7.1 的价值正在于此——把"绿但无效"的伪装拆穿：
1. **`test_loopback_e2e.py::test_validation_route_not_counted`**：该 ST 的 `_PerfTunedStage.transition`
   引用了**未导入**的 `PerformanceResult`（NameError）。旧行为下该异常被吞、perf 标 completed 但
   `perf_iterations` 从未置 1 → `resolve_condition` 永远返回 `default` → 它声称要测的 perf→verify
   validation 路由**从未真正触发**，测试"绿"得毫无意义。修复 import 后该路由首次真正跑起来，暴露出
   其断言（`corrective_count==0`）与现行**reverse-validation guard**（graph_executor 显式把"向后跳的
   validation 边"计为 corrective，防止无限自旋）冲突。该 guard 是后加的正确行为，测试是过时残留 →
   已改名 `test_backward_validation_route_metered_as_corrective` 并更新断言为 `corrective_count==5`
   （max_corrective 上限）/ `escalation_count==0`，使其首次真正校验 reverse-validation 语义。

> 这两处都不是 §P7.1 引入的回归，而是它**应当暴露**的历史掩盖。修复方式为"补正测试使其真正生效"，
> 未削弱 §P7.1 的失败可见性。

### §P7.1 修订：last_error 是 sticky 的，状态判定只认"本阶段自己的错误"（真实 e2e 暴露）

用 rope fixture 跑真实 e2e 时发现:requirement 阶段(非交互下 6 个 blocking unclear_items 无人解答→
合理的 partial)之后,**每一个下游 stage 都显示 ✗ failed**(gd-generate / general-design-review /
dd-intake 空跑 / template-division / split / ...)。根因:`State.last_error` 是 **sticky** 字段
(上游设了之后一直留在 State,直到某个 stage 成功 parse 才清),而 §P7.1 初版的判定
`elif last_error is not None → failed` 不区分"本阶段产生的错误"和"上游继承来的错误",于是上游一旦
失败,所有下游(哪怕是 dd-intake 这种 no-op 空跑)都被误标 failed。

**修复**:状态判定的 last_error 分支加 stage 归属校验——只有 `last_error.stage_name == 本 stage.name`
才计为失败;继承自上游的 error 不影响本 stage 的 glyph。测试 `test_stage_failure_status.py` +2:
stale 上游 error 不误标 no-op 阶段 / 本阶段自身 error 仍正确标 failed。

> 该 bug 是 §P7.1 引入的(初版判定过宽),已在同一工作内修正——这正是真实 e2e 验证的价值。
> 注:glyph 是显示信号,不改 routing/产物;真实 run 里产物链完整产出(见下"e2e 验证")。

### e2e 验证(rope fixture,真实链路)

用 `tests/fixtures/rope_requirements.md` + 真实算子仓跑 incremental/non-interactive e2e,验证 §P1 + L4
在真实链路的端到端效果(代理中转慢,设计阶段单 turn 数十秒~分钟):

- **§P1 闭环(对照 baseline 的 layernorm 幻觉)**:gd-generate→general-design-review→template-division→
  tiling fork-join 全部按 rope 真实语义产出;template-division 正确切出 **4 个模板对应 fixture 的 4 种
  rotary mode**(TPL_MODE0_HALF / MODE1_INTERLEAVE / MODE2_QUARTER / MODE3_INTERLEAVE_HALF),各模板
  `tiling_split/buffer_kernel/precision_perf.json` 落在**按模板隔离的子目录**(§P1 数据流 c + §P2 路径隔离)。
- **§P7.3 慢≠停滞**:设计阶段多个 turn 字符数短时不变但间隔很长(代理慢),停滞检测**未误杀**(只在
  真正无效重复时才触发),符合"内容信号、不掺时间"的设计。
- **§P7.4**:确认 `turn N/15` 的 N 会超过 15(如 `turn 23/15`)且与 resume 无关——SDK 不在 max_turns
  硬截 assistant 消息流。据此把显示改为 `turn N (budget M/query)`,不再用误导性的 `/M` 分数。
- **§P7.1 stale-error**:如上,真实 run 暴露并修正。
- requirement 的 partial(6 个 blocking unclear_items 非交互无解)是合理的"未完全澄清"信号;其
  requirement.json 内容质量高(op_type/mode/change_requirements/generalization_scenarios/test_cases +
  6 条切中要害的澄清问题)。

## §P7.3 / §P7.4（已完成）

### §P7.3 停滞检测复核 —— 进展判定收紧为"有实质效果"，且绝不掺时间

**问题**：`made_progress = 新文本 or had_tool_use`，`had_tool_use` 太宽松——只要调了任何工具就算
进展。于是"无文本但反复发无效工具调用"（反复 `ls/cat/grep` 同一目标、或工具调用持续报错）每轮
都把 `stalled_turns` 清零，停滞检测永不触发，agent 空转到撞 max_turns（如 split turn 13~16 均
3553 chars）。与 AC0 病根同源（反复找不存在的 checkpoint）。

**关键约束（用户提出）**：慢 ≠ 停滞。当前经代理访问 LLM、服务器中转慢，turn 间隔可能很长，但
只要内容在推进就不能掐。停滞判定**必须纯内容信号、绝不掺 wall-clock**。核查确认 backend 的
`stalled_turns` 本就只看内容、不看时间（elapsed 仅用于日志显示），修复保持这条底线。

**修复**（sdk_backend.py）：进展收紧为
`新文本 OR (新的非重复工具调用 AND 其前序 tool_results 未全部报错)`：
- `_tool_use_signature(block)`：tool name + 规范化 input 指纹；近 `_TOOL_SIG_WINDOW=6` 个指纹里
  出现过的视为 verbatim 重复，不算进展。
- `_scan_tool_results(event)`：从 UserMessage 的 ToolResultBlock 读 `is_error`；一个 turn 的工具
  调用若 tool_results 全错，不算进展。
- 二者均零时间维度 → 慢但在推进的 agent 绝不会被误判停滞。

**测试**：`test_stall_detection.py`（15 例）：signature 一致性/参数序无关/不可序列化不崩；tool_result
全错/部分 OK/无结果；进展谓词六组合；模拟 idle-spin 最终触发停滞；模拟"慢但每轮有新调用"永不停滞。

### §P7.4 turn 计数口径对齐 —— 不再用误导性的 `turn N/M` 分数

**问题**：日志出现 `turn 31/15`、`turn 23/15`。**初版假设**(累计跨 resume 导致溢出)被真实 e2e
证伪:`turn 23/15` 在**单次 query、无 resume** 时就出现——SDK 的 `max_turns` 并**不硬截**流式
assistant 消息数,一次 query 常常吐出多于 max_turns 的 turn。所以问题不是"累计/单次"口径,而是
"`/M` 分数本身在撒谎"——它暗示 M 是分母上限,而分子根本不遵守它。

**修复**:不再渲染 `turn N/M` 分数。改为 `turn {turn_count} (budget {eff_max_turns}/query[, attempt K])`
——turn_count 是累计的诚实进度信号,max_turns 明确标注为"每 query 预算"而非硬上限分母,resume 时
注明 attempt。`turn_count` 仍用于 transcript 排序(语义不变)。纯显示改动,不影响停滞/transcript/产物。

> 这是一次"先假设、被真实 run 证伪、再以事实修正"的过程:初版的 `query_turn` 方案基于错误的
> 根因假设,实测发现单 query 也溢出后,改为不假设硬上限的诚实显示。

## §P7.5 跨 stage 上下文链端到端核对（已完成）

### 问题（01-problems.md P7.5）

P1 的同源表现：`gd-generate` 猜成 layernorm，因 requirement 没作为强上下文喂给概设 agent；
跨 stage 的产物传递链需端到端核对——确保每个 spawn stage 的 `input_contract.requires` 都真正注入。

### 核对结论（以代码为准，full-state 渲染逐个 substage 的 prompt）

设计链已**端到端完整**（得益于 L4-c 的上游产物注入链补齐）：

| substage | requires | 注入情况 |
|---|---|---|
| gd-generate | requirement | ✓（`_operator_section` 注 op + 需求摘要）|
| general-design-review | general_design | ✓ |
| template-division | general_design | ✓ |
| split / buffer-kernel / precision-perf | template_division (+本模板已完成段) | ✓ |
| anchor-check | tiling_results | ✓ |
| integrate | tiling_results, anchor_report | ✓ |
| validate | design_doc (+tiling_results/anchor_report 证据) | ✓ |

- **requirement 作为链根**：requirement → general_design → template_division → tiling → ... 逐级以
  结构化产物传递，下游拿的是其派生产物（语义更聚焦），无需再拿原始 requirement。
- **design→codegen 交接**：codegen 的 `_build_codegen_prompt` 已注入 design_spec / tiling_strategy /
  kernel_architecture（codegen.py:156-161），三件套契约完整流入，非裸提示词。

### 守护测试

- `test_context_chain_e2e.py`（新建 10 例）：参数化遍历 9 个 spawn 型设计 substage，断言其
  `input_contract.requires` 的每个字段 marker 都出现在 spawn prompt 里（契约级守护——新增 substage
  或新增 required 输入却忘接线注入时，在此处而非昂贵真实 LLM run 中被截获）；外加 gd-generate 拿到
  requirement detail 的专项断言（pin 住原 P1 layernorm 症状）。

> 其余 spawn 阶段（codegen/perf/test_design/requirement）属 step-3「其余阶段 skill plugin 化」范围，
> 不在 step-8 设计链核对内（§P5 已界定）。本节确认 design 链 + design→codegen 交接齐备即闭环 §P7.5。

## §P7.2（已定：暂不修改）

per-stage max_turns 依赖 §P1 闭环后的真实重测数据，且不影响正确性，暂不动（见 02-analysis）。
