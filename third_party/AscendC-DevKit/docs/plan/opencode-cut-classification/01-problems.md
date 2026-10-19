# opencode 硬切分类协议假设失效（P6 分类生产零产出）— L1 问题记录（2026-09-14）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/根因/影响）。
> **不提方案**。方案分析见 `02-analysis.md`（L3）；实施方案见 `03-impl.md`（L4）。

## 证据来源

- **批**：`20260911-172304-501e35`（2026-09-12 本地，worktree `cann-bench-batch/20260912_012248`）
- **算子/执行**：adaptive_avg_pool_3d exec `20260911-172304-e80ca9`（5 次 cut → halt）、
  transpose exec `20260911-172304-45b56b`（4 次 cut 后走出并出分 51.15）
- **日志**：`logs/batch_20260912_012248.log`；transcript
  `output/20260911-172304-501e35/20260911-172304-e80ca9/agents/ascendc-coder-01/05.jsonl`；
  sidecar `agents/ascendc-coder-codegen.session.json`
- **opencode 二进制**：`/root/.opencode/bin/opencode` 内嵌源码 strings 提取（bun bundle）；
  SDK 类型 `@opencode-ai/sdk/dist/v2/gen/types.gen.d.ts` `EventMessagePartDelta`

## 事实（客观，已实证）

### F1：cut 放弃日志的取证清单恒空

`Stage 'codegen' cut-recovery 放弃：…各次 thinking chars：[]`（2026-09-12 02:35:27，
adaptive）。P7/step-110 设计的「各次截断 thinking 体量清单」在 opencode 侧从未产出过数据。

### F2：分类 facts 在生产从未产出（非本批新事）

- 本批 9/9 次 cut（两算子合计）全走**通用降级文案**（`agent silent-cut (no artifact,
  thinking-only terminal)`），详细版（`agent 终止：thinking-only 终态（thinking X chars…`）零次。
- 全部历史批日志（`logs/batch_*.log`）grep 详细版文案 **0 命中**——opencode 侧 P6 分类
  自落地起从未在生产成功过，非近期改动引入的回归。

### F3：根因 = delta 事件的协议假设错误（死分支）

- `opencode_backend.py` `_handle_sse_event` 的 `message.part.delta` 分支：
  `if props.get("field", "text") == "reasoning"` 才累计 `step_reasoning_chars` /
  打点 `last_reasoning_delta_ts`。
- opencode v2 二进制内嵌发射源码（text part 与 reasoning part 两个分支）均硬编码
  `field:"text"`——**`field` 指的是 part 上被流的属性名**（text/reasoning part 的属性
  同名 `text`），不区分内容类型；SDK 类型 `field: string` 亦未约束值域。
- 故该分支生产永不命中 → `step_reasoning_chars` 恒 0、`last_reasoning_delta_ts` 恒
  None → `classify_cut`（`base_backend.py` 守卫 `thinking_chars <= 0`）恒返回 None。

### F4：transcript 排除「step-start 重置吞证据」竞争假说

截断轮 block 序列（coder-01 turn 36 / coder-05 turn 62）均为
`step-start → thinking(100,791 / 74,756 chars) → step-finish`：重置发生在 thinking
**之前**；且 SSE 合计字符（text+reasoning 双分支）确实累计到了 74,756——delta 流经
handler 而唯独 reasoning 侧累计为 0，只能是 `field` 判别失效。

### F5：UT fixture 编码了同一错误协议（test-drift）

`test_sse_reasoning_delta_stamps_classification_evidence` /
`test_sse_step_start_resets_step_reasoning_chars`（tests/ut/capabilities/
test_opencode_backend.py）fixture 喂 `field:"reasoning"`——按代码同样的假设造数而非从
真实发射体提取，绿灯掩盖死分支。判切点分类测试（`test_opencode_hard_cut_…`）直接注入
state，不经 handler，测不到累计链。

### F6：控制流后果——P6 的硬切恢复设计整体落空

`cut_hard` 恒 False 导致：

1. **硬切恢复提示路由永不生效**：`_HARD_CUT_RESUME_PROMPT` 专为「输出墙截断」设计，
   从未被使用；所有 cut 的 resume 都用通用 continue nudge。
2. **「硬切不 bump resume_fails」豁免永不生效**：所有 cut（含硬切）都按未知中断累计
   无效 resume → 3 次即触发 fresh 退化。而 P6 代码注释明确警告：硬切退化 fresh =
   丢上下文、重放同一深推理再撞墙。
3. **sidecar 观测歧义**：`cut_hard:false` 无法区分「判为软切」与「未分类」。

### F7：批实证（用错恢复路径的完整案例）

adaptive 5 次 cut 全同签名（单轮思考膨胀至输出墙：100,791 / 96,444 / … / 74,756
chars）：3 次通用 resume 全撞墙 → fresh 退化 → 新会话 turn 62 在同一难题再陷 74,756
chars 截断 → cut_streak 5/5 + artifact-retry 5/5 耗尽 → halt。
**归因注记**：模型侧沉思膨胀是上游病因（F7 的事实原因）；本问题（分类失明）的产权是
**恢复策略选择错误 + 取证缺失**，二者独立——分类修好后不保证救活，但恢复路径正确、
证据如实。

### F8：影响范围

仅 opencode backend（SSE delta 路径）。sdk backend 走 SDK 流式 consumer 直接对
thinking block 计数打点（`base_backend.py` IRConsumer），不经 `field` 判别，不受此病。

### F9：同源的第二个消费点（评审补，2026-09-14）

同一错误协议假设在仓内**还有第二处**：`opencode_sse.py` 的
`_DELTA_FIELD_KIND = {"text": "text", "reasoning": "thinking"}` 及其消费点
`sse_event_to_ir_records` —— 该处注释原文「Spike saw field="text"; "reasoning" is
opencode's thinking field — **best-effort until a thinking-bearing spike confirms the
exact name**」，即当初就按「未实证」记下。

该函数属**被否决方案 A 的残留**：`opencode-streaming-transport/03-impl-streaming.md`
明载「`sse_event_to_ir_records` + 信号访问器…（**A 收敛时用；B 仅用前两个**）」，
实际实现走 B（`_handle_sse_event`），故该函数**生产零调用点**（仅 `test_opencode_sse.py`
自证）。首版修复只改了 `opencode_backend.py` 一处，遗留此点未处理 —— 属 §2.5
「同一职责只允许一条实现通路」违例（两处各持一份协议知识，修一处留一处）。

同源的死符号：`is_idle_completion` / `event_error`（同样生产零引用，属方案 A 残留）。
