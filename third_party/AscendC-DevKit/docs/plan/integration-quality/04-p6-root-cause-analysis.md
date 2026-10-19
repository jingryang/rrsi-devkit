# P6 源码级根因分析（L1+ 深度证据）

> 基于对源码的完整追踪分析。追踪路径：
> `sdk_backend.py` → `design_substages.py` → `design_tree.py` → `skill_config.py` →
> agent manifest (`.claude/agents/ascendc-design-generator.md`) → tiling SKILL.md

---

## P6-a: agent stall + crash 根因

### 现象摘要

| 模板 | Segment | 日志行 | Stall turn | Total chars | 结果 |
|------|---------|--------|------------|-------------|------|
| InterleaveRotation | buffer-kernel | 388-401 | turn 9 | 663 (vs 成功模板 59342) | crash, missing tiling_buffer_kernel.json |
| HalfRotation | precision-perf | 553-577 | turn 10 | 628 | crash, missing tiling_precision_perf.json |
| HalfRotation | buffer-kernel | 404-414 | 未触发 (tool_use 判定有效) | 1120→26724 | 成功 |

### 关键对照证据

HalfRotation buffer-kernel 在 turns 1-3 同样经历了 3 轮 flat（727→727→727 chars），但 stall 检测未触发。
原因：它的 tool_use 被判定为 "had_new_tool_use and not last_tool_results_errored" → 有效 Read 重置 stall 计数器。

InterleaveRotation buffer-kernel 在 turn 7-9 的工具调用被判定为重复/error → stall 累积 → break。
**同一 agent 同一 segment 的存亡取决于工具调用的"签名是否重复"——这是运气，不是设计保证。**

### 根因 1: MAX_STALLED_TURNS=3 对 bootstrap 阶段过窄

文件：`src/ascendc_devkit/capabilities/agent/sdk_backend.py`

```python
# Line 161
MAX_STALLED_TURNS = 3

# Line 622-636: stall detection
made_progress = (
    len(full_response) > prev_len
    or (had_new_tool_use and not last_tool_results_errored))
if made_progress:
    stalled_turns = 0
else:
    stalled_turns += 1
    if stalled_turns >= MAX_STALLED_TURNS:
        Logger.warn(f"Agent {agent_name} stalled: ...")
        _stall_break = True
        break
```

**问题**：tiling agent 在 bootstrap 阶段必须 Read 4+ 个文件（general_design / template_division / tiling_split / prompt-embedded context）。每个 Read 可能花费 1 turn 且不产生新文本。如果某个 Read 的 tool_result 返回 error 或与之前 Read 签名重复，stall 计数器递增。**3 turn 窗口对需要多步 I/O 的 bootstrap agent 来说太短。**

### 根因 2: slash-command skill injection 可能静默失败

文件：`src/ascendc_devkit/orchestration/stages/design_substages.py`

```python
# Line 242-250: _with_trigger prepends slash command
def _with_trigger(self, body: str) -> str:
    trigger = self._skill_trigger()  # "/stage-design:ascendc-op-tiling-buffer-kernel"
    return f"{trigger}\n\n{body}" if trigger else body
```

skill 通过 prompt 首行 slash command 注入。事件日志 `events.jsonl` 确认格式正确：
```json
{"prompt": "/stage-design:ascendc-op-tiling-buffer-kernel\n\n## 任务\n推导单模板..."}
```

Agent manifest 告诉 agent："设计方法和规范已在当前会话给出"。

**如果 CLI 未能展开此 slash command**（静默失败），agent 看到任务描述但没有方法论 → 无法生成设计 → Read-loop 自救 → stall。

**为何 loopback 能成功**：
- 工作目录已有 stall 遗留的部分产物 → agent 可从已有 JSON shape 推断 schema
- Prompt 含 `## 重试上下文`（Line 292-297）→ 引导增量补全
- 并行成功的模板产物可参考 → 跨模板学习

### 根因 3: aclose race guard 未命中

```python
# sdk_backend.py:648-656
if (_stall_break and isinstance(e, RuntimeError)
        and _ACLOSE_ERROR_MARKER in str(e)):
    Logger.warn(f"Agent {agent_name} stall aclose race (non-fatal): {e}")
```

日志第 393 行显示裸 `RuntimeError: aclose(): asynchronous generator is already running`，**没有** "stall aclose race" WARN。guard 条件不成立——可能 `_stall_break` 被 reset 或字符串匹配失败。

---

## P6-b: 0.0s 空操作 stage（设计意图 vs 用户感知）

| Stage | 行号 | 代码路径 | 设计意图 |
|-------|------|----------|----------|
| dd-intake | 151-152 | `design_substages.py:558-560` `if not self._has_doc: return []` | 无 --detailed-design 时 pass-through |
| perf | 3222-3223 | `perf.py:177-178` `if not has_perf_target: return []` | 需求无性能约束时跳过 |

都是**正确设计**，但 `✓ done (0.0s)` 与正常完成 stage 输出完全相同 → 用户困惑。
改进：空操作用 `○ skipped (reason)` 替代 `✓ done`。

---

## P6-c: anchor-check → tiling loopback（3次，~3000s）

### 根因 1: C1 分支隔离 + stall = tiling_results 不完整

`design_substages.py:1062-1085`：
```python
name = self._template_name
tmpl_entry = dict((state.tiling_results or {}).get(name, {}))
tmpl_entry[self.segment_key] = payload.get(self.segment_key)
return state.with_updates(tiling_results={name: tmpl_entry}, ...)
```

每个 segment transition 只 emit 自己模板的 key（C1 保证并行安全）。当 buffer-kernel/precision-perf stall+crash → transition 不执行 → segment_key 不写入 → anchor-check 看到 partial data。

### 根因 2: rerun_selector 需与 loopback 正确协作

`design_tree.py:109-117` 已有 `_tiling_rerun_selector` 从 anchor_report.blocking_issues 提取受影响模板名，但 anchor→tiling loopback transition 目前重跑整个 tiling fork-join。需确认 rerun_selector 在 loopback + fork-join 路径上正确生效。

### 根因 3: hardware_api_capability 数值漂移

QuarterRotation 的 claims 中 UB=253952B（应为 245760B=240KB）。SKILL.md 有 `platform_diff.md` 参考但 agent 未正确引用。

---

## P6-d: test-casedesign 重复产出 design schema

`test_design_substages.py:48-51` — 三个 substage 共享 `test_design/` dir。test-casedesign 的 `_upstream_inputs` 只物化 `test_analysis.json`，但 agent manifest 允许自由 Read → agent 读 design 产物后又写回 test_design/。

`_parse_single` 只解析 `test_casedesign.json` → 副本不影响 State，但浪费 ~150KB + 在 loopback 修正上游后副本可能过时。

---

## P6-e: pipeline halt→loopback 自救可观测性不足

`graph_executor.py:162-171` halt 只输出一行 WARN，不说明"将在 anchor loopback 中重试"。
`_log_loopback:309-327` 被 `_SUMMARY_MAX_ISSUES=2`（Line 20）截断，其余 mark 在 events.jsonl。
用户视角 = "crash 了，又莫名其妙好了"。
