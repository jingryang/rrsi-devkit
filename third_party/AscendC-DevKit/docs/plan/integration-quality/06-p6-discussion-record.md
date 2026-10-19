# P6 讨论记录 — 阶段性结论

> 逐个问题讨论，确认后再动代码。

---

## 讨论进程

- [x] P6-a（agent stall）
- [x] P6-b（空操作 stage）
- [x] P6-c（schema 不对齐 → loopback）
- [x] P6-d（test-casedesign 重复产出）
- [x] P6-e（halt→loopback 可观测性）

---

## P6-a：agent stall + crash — 已确认

### 核心结论

**不做参数调优，不引入生命周期标记，不放在 SKILL.md 里。** 这些方向都依赖"某种阈值"或"某种算子行为假设"，不可靠。

真正的修复方向是两层的：

| 层 | 位置 | 职责 | 触发信号 |
|---|------|------|---------|
| A（早期） | sdk_backend.py | 快速发现死锁 | 相同 tool call + 相同参数，连续 N 轮全部 error |
| B（兜底） | orchestration | 文件产出超时 | artifact_contract 声明的文件，时间内未产出 |

两层不是替代是互补：A 快但覆盖窄，B 慢但覆盖一切。

### A 层 fix

**问题**：`last_tool_results_errored` 是一个全局跨-turn flag。上一轮任何工具失败会污染下一轮完全不同操作的 progress 判定。bootstrap 阶段 agent 逐文件 Read 时，个别文件的临时 failure（文件未写完等）不应牵连全新的操作。

**修正**：把 `last_tool_results_errored` 从"全局跨 turn"改为"与 tool call 签名绑定"。只有**同一个签名的操作连续 error**才算非进展。

```
当前：   had_new_tool_use and not last_tool_results_errored [污染下一轮]
修正后： had_new_tool_use  [新操作就是进展，不管上一轮报没报错]
         + 同签名连续 error → 死锁判定
```

偶尔的工具错误不触发计数器也不重置计数器。只记 log。

### A 层不改动的地方

① stall 阈值保持现有逻辑，不动；② 不引入 agent 生命周期标记；③ 不在 SKILL.md 中声明预期轮数。

### B 层

放到后续讨论，不在本轮 P6 范围内优先实现。

### 波及文件

- `src/ascendc_devkit/capabilities/agent/sdk_backend.py`：`_scan_tool_results` + progress 判定逻辑
- 改动量：约 15-20 行

---

## P6-b：空操作 stage — 已确认

### 核心结论

`dd-intake` 和 `perf` 设计上会在特定条件下跳过（无 `--detailed-design` / 无性能约束），但日志输出 `✓ done (0.0s)` 与正常 stage 无法区分。需要分级：

- **跳过了** → `○ skipped (reason)`
- **跑了空** → `⚠ no actions (possible bug)`

这样以后出现"本该执行但跳过了"的异常能被及时发现。

### 实现方向

**Stage 基类增加 `skip_reason` 方法**，声明性契约：

```python
def skip_reason(self, state: State) -> str | None:
    """返回 str 表示有意跳过（作为 `○ skipped` 的原因），返回 None 表示不跳过。"""
    return None  # 默认：不跳过
```

- `dd-intake` 覆写：无 doc 时返回 `"no --detailed-design supplied"`
- `perf` 覆写：无性能约束时返回 `"no performance constraint in requirement"`

**runner 日志逻辑**：

| actions() | skip_reason() | 日志 |
|-----------|--------------|------|
| 空 | 有原因 | `○ skipped (reason)` |
| 空 | 无原因 | `⚠ no actions (possible bug)` |
| 非空 | - | `✓ done`（不变） |

### 不改动的地方

① 不删除 dd-intake/perf —— 它们的 pass-through / skip 行为正确；② 不把判定逻辑交给 runner 推断 —— Stage 自己声明意图。

### 波及文件

- `src/ascendc_devkit/orchestration/base.py`：Stage 基类新增 `skip_reason` 方法 ~5 行
- `src/ascendc_devkit/orchestration/stages/design_substages.py`：`DetailedDesignIntakeStage` 覆写 ~3 行
- `src/ascendc_devkit/orchestration/stages/perf.py`：`PerfStage` 覆写 ~3 行
- `src/ascendc_devkit/orchestration/kernel/runner.py`：stage_done 日志分级 ~5 行

---

## P6-c：schema 不对齐 → 3 次 loopback — 已确认

### 核心结论

**loopback 不是 bug，是设计保证。**

真正的问题有两个：

1. **自检清单缺项**：tiling-buffer-kernel / tiling-precision-perf 的 SKILL.md 自检清单没有 hardware_api_capability 与 platform_diff.md 真值表的对比项。Agent 逐条打了勾但 UB=253952B 这种错误值从来没被要求自查。

2. **信息回路断裂**：第 2、3 次 loopback 都是同一个 InterleaveRotation Gather API 问题，tiling agent 修了两次没修掉。根本原因是 loopback 没有把 anchor-check 的 blocking_issues 喂回给 tiling agent —— agent 看到的是通用的 `## 重试上下文`，不知道上次具体错在哪，用同样的推理路径又输出了同样的错误方案。

### 修复方向

#### 修复 1：SKILL.md 自检清单补漏

在 tiling-buffer-kernel 和 tiling-precision-perf 的 `## 核心规则` 段增加 hardware_api_capability 校准项：

```
- [ ] hardware_api_capability 字段每个数值已与 platform_diff.md 真值表对比，不一致的已修正
```

所有硬件参数真值统一写在 `shared/platform_diff.md`，两个 SKILL.md 同时引用，不各写一份。

#### 修复 2：loopback 通用 feedback 通道（公共机制，非 tiling 专用）

**设计**：State 新增 transient 字段 `_loopback_feedback: dict | None`，Stage 基类新增可选 hook `loopback_feedback(state) -> dict | None`。任何 gate stage 覆写此 hook 即可产出结构化 feedback（JSON dict），loopback 路由层在跳转前将其写入 state，目标 stage 的 `_build_prompt` 检测到非空则自动追加 `## 上次反馈` 段落。现有 `validate → tiling`、`anchor-check → tiling`，以及未来任何 corrective loopback 自动继承，不需要每条 transition 各自写一份 wiring。

**feedback 格式**：producer 产出任意 JSON dict，consumer 用 Python 一行代码格式化追加到 prompt。producer 不负责生成 prompt 文本——数据是 JSON 的，格式是 Python 管的。

```python
# producer（gate stage）
def loopback_feedback(self, state):
    return {"blocking_issues": self.blocking_issues(state)}

# consumer（_DesignSubstage._build_prompt）
fb = getattr(state, '_loopback_feedback', None) or {}
issues = fb.get("blocking_issues", [])
if issues:
    text = "\n".join(f"[{i['code']}] {i['detail']}" for i in issues)
    sections.append(f"## 上次反馈\n{text}")
```

**路由层 wiring**（`GraphExecutor._execute_sequential`）：在 `resolve_condition` 判定非 default 后、counter + history 写入前，从源 stage 取 feedback 写入 state。消费后由目标 stage 清零。

**对架构的影响**：

| 位置 | 改动 | 说明 |
|------|------|------|
| State | 新增 `_loopback_feedback` ~3 行 | transient，不持久化，消费后清零 |
| Stage 基类 | 新增 `loopback_feedback` hook ~5 行 | 默认返回 None，不覆写不生效 |
| GraphExecutor | `_execute_sequential` 加 ~5 行 | 在已有 resolve + 路由跳转之间插入 |
| `_DesignSubstage._build_prompt` | ~6 行 | 检测 feedback 非空则追加 |

transition_table、dispatch 层、resolve_condition 全部不动。

**波及文件**：

- `src/ascendc_devkit/orchestration/kernel/state.py`：State 新增 `_loopback_feedback` ~3 行
- `src/ascendc_devkit/orchestration/base.py`：Stage 基类新增 `loopback_feedback` hook ~5 行
- `src/ascendc_devkit/orchestration/graph_executor.py`：`_execute_sequential` 中读写 feedback ~5 行
- `src/ascendc_devkit/orchestration/stages/design_substages.py`：
  - `_DesignSubstage._build_prompt`：消费 feedback 并追加 prompt ~6 行
  - `AnchorCheckStage.loopback_feedback`：覆写产出 blocking_issues ~3 行
  - `ValidateStage.loopback_feedback`：覆写从 `design_doc.validation_report` 产出 ~3 行

**波及文件（修复 1 — SKILL.md 自检补漏，与修复 2 并行）**：

- `.claude/plugins/stage-design/skills/ascendc-op-tiling-buffer-kernel/SKILL.md`：自检清单加 hardware_api_capability 对比项 ~3 行
- `.claude/plugins/stage-design/skills/ascendc-op-tiling-precision-perf/SKILL.md`：同上 ~3 行
- `.claude/plugins/stage-design/shared/references/platform_diff.md`：锁定硬件参数真值表 ~10 行

---

## P6-d：test-casedesign / codegen 重复产出上游 schema — 已确认

### 核心结论

test-casedesign 的 working dir 里出现了 `design_spec.json` / `kernel_architecture.json` / `tiling_results.json` / `tiling_strategy.json`。codegen 同样。skill 的方法论本身没问题（正确产出了各自声明的产物），问题在于 agent 在"传递文件"的过程中把上游产物复制进了当前目录。

### 不做的事

不改 SKILL.md（方法论 OK），不改 agent manifest（工具权限不需要动），不立刻升级为 CLAUDE.md 的架构硬约束（过早，等更多案例收敛后再系统化）。

### 修复方案

在 `_DesignSubstage._build_prompt` 的 artifact_contract 渲染之后追加一句温和的定向约束：

```
只产出上列文件。不要将上游产物（如 design_spec / tiling_strategy 等）
复制到当前工作目录。
```

放在基类里，所有 agent-based stage 自动继承。后续如果发现其他 stage 也有类似问题，这条约束已经在覆盖范围内。是一个基于现状的定向收敛，不是过度抽象的架构禁令。

### 波及文件

- `src/ascendc_devkit/orchestration/stages/design_substages.py`：`_DesignSubstage._build_prompt` 追加 ~3 行

---

## P6-e：pipeline 失败行为不透明 — 已确认

### 核心结论

halt→loopback→success 自救链路对用户不可见。loopback 概率降低（由 P6-a + P6-c 驱动）与可观测性提升是独立维度，同时做。

### 修复 1：halt 时输出具体失败原因

**现状**：`graph_executor.py:167-169` 只输出 `Stage '{sname}' failed with fail_strategy=halt; stopping pipeline.`。`state.last_error` 有完整 `ErrorFeedback(stage_name, error_type, message)`，但 halt 段没读它。

**修复**：halt 时追加 `state.last_error.message`：

```
Stage 'buffer-kernel' failed with fail_strategy=halt; stopping pipeline.
  reason: buffer-kernel: missing tiling_buffer_kernel.json
```

波及：`graph_executor.py` ~2 行。

### 修复 2：loopback 时提升 issue 摘要上限

**现状**：`_SUMMARY_MAX_ISSUES = 2`（`graph_executor.py:20`）。loopback 触发时用户只看到 2 条 blocking_issues 摘要，其余埋入 events.jsonl。

**修复**：提升到 5。

波及：`graph_executor.py` ~1 行。

### 修复 3：所有 blocking issues 解决后输出汇总

**现状**：loopback 多次后 anchor-check 通过，无任何提示——用户只能看到 `✓ verify done` 才知道 pipeline 最终成功了，整个自救过程看不到收尾。

**修复**：在 loopback 成功（gate 的 `is_satisfied()` 从 False 变为 True）时输出一行：

```
✓ anchor-check passed after 3 corrective retries (3012s)
```

波及：`graph_executor.py` `_execute_sequential` 中 gate 通过路径 ~5 行。

### 波及文件汇总

- `src/ascendc_devkit/orchestration/graph_executor.py`：`_SUMMARY_MAX_ISSUES` 调整 + halt 原因 + 汇总行 ~10 行
