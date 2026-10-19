# step-8 §P2+§P3+§P6 实施方案 b — 可观测性（日志归属 / loopback 摘要 / 产物清单）

> 层级：**L4 / 实施方案**。精确到改哪个函数、怎么改、怎么验证。
> 决策依据见同目录 `02-analysis.md` §P2/§P3/§P6 + D6/D8；问题证据见 `01-problems.md` P2/P3/P6。
> 范围：D5 四分法的 **L4-b**。依赖 L4-a 已落地的数据流 (c) 路径隔离（`design/tiling/<template>/`）。

## 代码落点核实（2026-06-16 实读）

| 关注点 | 现状 | 文件:行 |
|---|---|---|
| `SpawnAgent` 字段 | 无 `branch_label` / `stage_name` | `kernel/action.py:26-36` |
| backend turn 日志 | `Logger.action("agent_stream", f"{agent_name} turn ...")` 只打 agent 名 | `sdk_backend.py:536` |
| backend.spawn 签名 | 有 skills/plugins/model/working_dir/... 无 branch_label/stage_name | `sdk_backend.py:343,354` |
| runner 调 backend.spawn | 透传 7 个实参，无 branch/stage 标识 | `runner.py:388` |
| loopback 落点 | 仅 `event_log.append(evt.loopback(...))`，无 `Logger` 控制台输出 | `graph_executor.py:196-200` |
| blocking_issues 可达性 | 路由点 state 在手，gate 已把 issues 写进 State 字段 | `graph_executor.py` 路由块 |
| stage 结束日志 | `Logger.stage_done` 只打 `✓ <stage> done (<elapsed>)`，不列产物 | `logger.py:18` |
| agent 产物清单来源 | `agent_result.artifacts`（dict[path]→content） | `runner.py` spawn 结果 |

---

## 任务 1 — 分支/stage 标识透传（§P2 日志归属 + D8）

**目标**：并发 tiling 分支的 turn 日志可归属到具体模板；角色 agent 复用下日志可分辨 stage。

### 1.1 SpawnAgent 加一等字段（决策 P2-b）

`kernel/action.py` `SpawnAgent` 加两个展示用字段（语义干净，不寄生 context）：

```python
stage_name: str = ""    # 当前 stage 名（角色复用下分辨用，D8）
branch_label: str = ""  # fork-join 分支标识（tiling 模板名），非分支为空
```

### 1.2 design substage 填充

- 基类 `actions()` 构造 SpawnAgent 时填 `stage_name=self.name`。
- `_TilingSegmentStage.actions()` 额外填 `branch_label=self._template_name`。

> **模板名唯一性来源（可唯一区分 N 个并发分支）**：`branch_label` = `self._template_name`，
> 取自 `template_division.templates[].name`（如 `T1_HalfFull/T2_InterleaveFull/.../T5_*`）。
> 该名在编排里本就是模板唯一标识：fork-join 用它作分支名（`SequentialGroup(name=name)`，
> node 路径 `pipeline/detailed-design/tiling/<template>/<segment>`），C2 join 对同名模板判冲突
> （R8），rerun_selector 也按 `target_template` 名精确定位。⇒ N 个并发分支打出 N 个不同前缀，
> 一一对应；若 division 异常产出重名模板，编排在 join 阶段先于日志报错，正常流程下前缀必唯一。

### 1.3 backend 签名 + 日志格式

`sdk_backend.spawn/_spawn` 加 `stage_name=""`, `branch_label=""` 形参（默认空，向后兼容）。
turn 日志（`sdk_backend.py:536`）改为带前缀：

```python
label = f"[{stage_name}{'/' + branch_label if branch_label else ''}] " if stage_name else ""
Logger.action("agent_stream", f"{label}{agent_name} turn {turn_count}/{eff_max_turns}, ...")
```

完整前缀 `[<stage/segment>/<template>]` 同时定位「哪个模板的哪一段」：`stage_name` 区分同一
模板内的三段（`split`/`buffer-kernel`/`precision-perf`），`branch_label` 区分模板。
效果：`[split/T3_QuarterFull] ascendc-design-generator turn N`、
`[buffer-kernel/T3_QuarterFull] ... turn N`。非 tiling substage 无 branch_label，前缀退化为
`[gd-generate] ...`。

### 1.4 runner 透传

`runner.py:388` 的 `_agent_backend.spawn(...)` 补 `stage_name=action.stage_name`,
`branch_label=action.branch_label`。

### 1.5 transcript 文件名带标识（§P2 第 3 点）

`_spawn_seq` / transcript 命名加 branch_label，使 5 模板 × 多轮可一一对应。
（落点：backend transcript 写出处；以实读为准。）

### 1.6 验证

- 单测：tiling segment 的 SpawnAgent 带 `stage_name="split"` + `branch_label=<template>`。
- 单测：非 tiling substage 的 `branch_label` 为空、`stage_name` 为 stage 名。
- 单测：backend 日志格式（捕获 stderr 或 spy Logger.action）含 `[stage/branch]` 前缀。

---

## 任务 2 — loopback 控制台摘要（§P3 + D6）

**目标**：回退原因上控制台（前 2 条 blocking_issues 摘要），全量留 events.jsonl。

### 2.1 确定性摘要函数（Python，非 LLM）

新增 `_summarize_issue(issue) -> str`（决策 §P3 给了实现）：
`[{code}→{target}{/template}] {截断 detail}`，detail > 80 字符截断。

### 2.2 路由点双写

`graph_executor.py:196-200` loopback 落点：除 `event_log.append(evt.loopback(...))`，
新增 `Logger.action("loopback", ...)`。摘要来源 = 路由点在手的 State 里 gate 写的
`blocking_issues`（anchor_report / general_design_reviewed / design_doc.validation_report
按 condition/target 取）。控制台打前 2 条 + `(+k more, see events.jsonl)`（D6）。

### 2.3 验证

- 单测：`_summarize_issue` 字段选择 + 截断正确。
- 单测：loopback 触发时 Logger.action("loopback", ...) 被调用，含前 2 条摘要 + 余数提示。
- 单测：全量 issues 仍写 events.jsonl（不因控制台截断而丢失）。

---

## 任务 3 — stage 产物清单（§P6）

**目标**：stage 结束打印产出/改动文件清单，与 (c) 物化路径 + branch_label 对齐。

### 3.1 stage_done 增产物清单

`logger.py` 加 `stage_done` 的产物清单参数（或新增 `stage_artifacts(files)`）：
打印相对路径 + 行数/字节。数据来自 `agent_result.artifacts` 或 working_dir 扫描。

### 3.2 runner 收集并传入

`runner.py:282` `Logger.stage_done(...)` 处，从该 stage 的 `agent_result.artifacts`
收集文件清单传入。并行分支各自列清单（用 branch_label 归属）。

### 3.3 验证

- 单测：stage 完成后日志含产物相对路径清单。
- 单测：无产物时不报错（打印"无产物"或跳过）。

---

## 实施顺序与边界

1. 任务 1（标识透传）—— 动 action/substage/backend/runner 签名，先做（任务 3 的分支归属依赖它）。
2. 任务 2（loopback 摘要）—— 独立，graph_executor 局部。
3. 任务 3（产物清单）—— 依赖任务 1 的 branch_label。

边界：不碰 L4-a 已定的路径隔离/回灌；不碰 L4-c（skill 精选/designer 删除）、L4-d（正确性）。

## 实施进度（跨会话同步用）

| 任务 | 状态 | 备注 |
|---|---|---|
| 1 分支/stage 标识透传（SpawnAgent + backend + runner + 日志格式） | 已完成 | SpawnAgent 加 `stage_name`/`branch_label`；base.actions 填 stage_name + `_branch_label()` hook，tiling segment override 返回模板名；backend spawn/_spawn 加两形参 + turn 日志前缀 `[stage/branch]` + transcript 文件名带 branch_label（独立 seq）；runner 透传；AgentBackend 协议 + StubBackend 同步；新增 TestAttribution 3 例 + TestSpawnAgentAttributionPassthrough 2 例 + transcript branch 命名 1 例；修 5 处测试 stub 签名；ut+st 1203 passed |
| 2 loopback 控制台摘要（_summarize_issue + 双写） | 已完成 | graph_executor 加 `_summarize_issue`/`_summarize_issues`（确定性字段选择+截断，前 2 条 + `(+k more)`）；Stage 基类加 `blocking_issues(state)` hook，三个 gate（anchor-check/review/validate）override 读各自 report；路由点新增 `_log_loopback`（Logger.action 双写，best-effort 不阻塞路由）；新增 test_loopback_summary.py 12 例（摘要/截断/hook/executor 控制台回显）；ut+st 1215 passed |
| 3 stage 产物清单（stage_done + runner 收集） | 已完成 | Logger.stage_done 加 `artifacts` 参数（列相对路径 + 行数/字节，空则不列）；runner 从最后一次迭代的 agent_result.artifacts 收集传入（result 在循环前初始化 `{}` 防 resume 零迭代 NameError）；新增 test_logger_artifacts.py 3 例 + TestStageDoneArtifactListing 2 例；ut+st 1220 passed |
