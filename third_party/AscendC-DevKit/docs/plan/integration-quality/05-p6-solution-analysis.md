# P6 方案分析（L3 — 可行方案与取舍）

> 基于 [`04-p6-root-cause-analysis.md`](./04-p6-root-cause-analysis.md) 的根因证据，
> 提出细化到代码层次的修复方案，含影响评估与取舍。

---

## 总体策略

P6 五个子问题可归纳为三条修复主线：

| 主线 | 覆盖子问题 | 核心动作 | 预计代码改动量 |
|------|-----------|---------|---------------|
| **A. Agent 可靠性** | P6-a | stall 阈值阶梯化 + skill load verify | sdk_backend.py ~20行 |
| **B. Pipeline 可观测性** | P6-b, P6-e | empty-stage 日志分级 + halt→retry 链路追踪 | graph_executor.py ~30行, perf.py ~5行 |
| **C. Schema 防漂移** | P6-c, P6-d | hardware API 锁定 + agent prompt 写保护 | design_substages.py ~15行, SKILL.md prompt 增强 |

---

## 方案 A: Agent Stall 修复

### A1: 阶梯化 stall 阈值（推荐）

**现状**：`MAX_STALLED_TURNS = 3`，对所有 agent 的所有阶段一刀切。

**方案**：bootstrap 保护期 + 自适应阈值。

```python
# sdk_backend.py: 替代固定 MAX_STALLED_TURNS
BOOTSTRAP_GRACE_TURNS = 6       # 前 6 个 turn 内豁免 stall 检测
BOOTSTRAP_MAX_STALLED = 5       # grace 期内放宽到 5 个连续无进展 turn
NORMAL_MAX_STALLED_TURNS = 4    # grace 期后收紧到 4 个

# 判定逻辑
max_stalled = (BOOTSTRAP_MAX_STALLED if turn_count <= BOOTSTRAP_GRACE_TURNS
               else NORMAL_MAX_STALLED_TURNS)
if stalled_turns >= max_stalled:
    break
```

**影响**：
- HalfRotation buffer-kernel 的 7-turn bootstrap（turns 1-7 全是 Read 操作）将安全通过，不会在 turn 3 被误杀
- 保守估计减少 50% 的 false-positive stall（InterleaveRotation/HalfRotation 两个案例均可避免）
- 风险：真正死循环的 agent 在 grace 期内多跑 3-6 个 turn → ~30s 额外损失，远小于 loopback 的 ~1000s

**替代方案**：简单提高 `MAX_STALLED_TURNS` 到 5-6（不引入 grace 期概念）。代码改动更小但无法区分 bootstrap 和后期 dead-loop。

**建议**：A1（阶梯化），代码清晰且低风险。

### A2: Skill load 验证

**现状**：slash command 注入 skill，无反馈是否成功。

**方案 1**：在 agent 的第 1-2 个 assistant message 中检查是否出现 SKILL.md 特征文本（如 `## 核心规则`、`## 执行步骤`）。

```python
# sdk_backend.py: 在 assistant turn 2 且 full_response < 500 chars 时
if turn_count == 2 and len(full_response) < 500:
    skill_indicators = ["## 核心规则", "## 执行步骤", "步骤 1.", "自检失败"]
    if not any(indicator in full_response for indicator in skill_indicators):
        Logger.warn(f"Agent {agent_name}: skill may not have loaded (response too short)")
```

**影响**：提前发现 skill-load 失败，避免 agent 进入 Read-loop → stall 的消耗性路径。WARN 可触发提前 cancel+retry。

**风险**：误判（agent 用简短回答也能正确工作）→ 只是 WARN，不中断。可接受。

**方案 2**：在 spawn 时用 CLI `--check-skill` 或类似机制显式验证 slash 展开，但依赖 CLI 能力。

**建议**：方案 1（agent response 检测），零外部依赖。

### A3: aclose guard 修复

**现状**：guard 条件不成立，裸 traceback 被当作错误输出。

**修复**：加固条件判断。

```python
# sdk_backend.py:648-656 修复
_ACLOSE_ERROR_MARKER = "asynchronous generator is already running"  # 不变
...
if _stall_break and isinstance(e, RuntimeError):
    err_str = str(e)
    if _ACLOSE_ERROR_MARKER in err_str:
        Logger.warn(f"Agent {agent_name} stall aclose race (non-fatal): {e}")
        # continue (mark as non-crash)
    else:
        crashed = True
        last_exc = e
```

**修复点**：`_ACLOSE_ERROR_MARKER in str(e)` 而非 `_ACLOSE_ERROR_MARKER in e`。确认 `_stall_break` 在 break→except 路径上未被重置。

---

## 方案 B: Pipeline 可观测性增强

### B1: 空操作 stage 日志分级

**现状**：`return []`（零 action）和正常完成的 stage 都输出 `✓ done (0.0s)`。

**方案**：在 Stage 基类添加 `is_noop` 标记，Runner 据此输出不同日志。

```python
# base.py Stage 类
@property
def is_noop(self) -> bool:
    """True when this stage intentionally produces no actions."""
    return False  # 默认：非 noop

# perf.py PerfStage
@property
def is_noop(self) -> bool:
    return not self._has_perf_constraint(state)  # 需要 state 引用，改用方法

# 替代：在 actions() 返回 [] 时由 Runner 判断
```

**更简单的实现**：Runner 在 `run_stage` 中检测 `actions() == []` 且结果为 pass → 输出 `○ skipped` 而非 `✓ done`。

```python
# runner.py: 在 stage_done 前判断
if not produced_actions and elapsed < 0.5:
    Logger.stage_done(stage_name, elapsed, status="skipped")
else:
    Logger.stage_done(stage_name, elapsed, status="ok")
```

**影响**：3 个 0.0s stage 从 `✓ done (0.0s)` 变为 `○ skipped (reason)`，消除用户困惑。

### B2: halt→retry 链路透明度

**现状**：halt 只输出 WARN，无"将在 loopback 中重试"提示。

**方案**：halt 时提示重试路径 + loopback 时显示 progress。

```python
# graph_executor.py:162-171 halt 增强
Logger.warn(
    f"Stage '{sname}' failed with fail_strategy=halt; "
    f"stopping pipeline. "
    f"The failure will be retried automatically via anchor-check loopback "
    f"unless the corrective budget is exhausted.")
```

```python
# graph_executor.py: loopback 时显示进度
# 将 _log_loopback 改为也输出进度
Logger.action("loopback",
    f"{from_name} → {target_name} ({route_type} {count}/{cap}) "
    f"[estimated rerun time: ~{est_seconds}s based on stage history]")
```

**可选增强**：最终通过时输出汇总行：
```
✓ All anchor-check blocking issues resolved after 3 corrective retries (3012s)
```

### B3: _SUMMARY_MAX_ISSUES 提升

**现状**：`_SUMMARY_MAX_ISSUES = 2`，loopback 的 blocking_issues 摘要被截断。

**方案**：提升到 5，或按 issue severity 分层显示。

```python
_SUMMARY_MAX_ISSUES = 5  # 从 2 提升
```

**影响**：用户能看到更多 "为什么会 loopback" 的细节，不需翻找 events.jsonl。

---

## 方案 C: Schema 防漂移

### C1: Hardware API capability 锁定

**问题**：agent 在 tiling 产物中声称的硬件参数（UB size、DDR 带宽等）与 anchor-check 的 ground truth 不一致。

**方案**：在 tiling SKILL.md 中嵌入硬件阈值常量表，禁止 agent 自行推导。

在 `ascendc-op-tiling-buffer-kernel/SKILL.md` 和 `ascendc-op-design-anchor-check/SKILL.md` 的 `## 核心规则` 段增加：

```markdown
- R-hw: **硬件参数锁定**。禁止凭记忆估算 UB/DDR/reg 容量值。
  所有硬件参数从以下锁定表取值，不得自行修改：
  | 参数 | A3 (Ascend910B) 值 | A5 值 |
  |------|-------------------|-------|
  | UB 总大小 | 245760 B (240 KB) | ... |
  | L1 Buffer 大小 | ... | ... |
  | DDR 带宽 | ... | ... |
  | Max RegTensor per core | ... | 32 |
  | Max MaskReg per core | ... | 8 |
```

**影响**：消除 QuarterRotation 的 UB=253952B 错误 claims，减少 1 次 loopback (~1000s)。

### C2: Agent prompt 写保护规则

**问题**：test-casedesign agent 将上游 design 产物重新写回 test_design/ 目录（P6-d）。

**方案**：在所有 agent prompt 的 `## 约束` 段增加写保护规则。

在 `_build_prompt` 的 artifact contract 部分增加：

```python
# design_substages.py: _build_prompt 增加输出隔离提示
sections.append(
    "## 输出隔离规则\n"
    "- 只产出本步骤声明的产物文件（见上文输出要求）。\n"
    "- 禁止复制/重写上游产出的文件到当前工作目录。\n"
    "- 需要引用上游产物时直接 Read 原始位置，不要复制副本。")
```

**影响**：消除 test-casedesign 的 ~150KB 重复产出，减少 token 浪费。

### C3: rerun_selector 对 loopback 的 fork-join 支持

**问题**：anchor→tiling loopback 重跑整个 tiling fork-join，而非仅重跑有问题的模板。

**现状**：`_tiling_rerun_selector`（`design_tree.py:109-117`）已从 anchor_report 提取受影响模板名，但需确认在 loopback 路径上生效。

**验证点**：`graph_executor.py:284-301` 中：
```python
sel = getattr(child_node, "rerun_selector", None)
targets = sel(state) if callable(sel) else None
prefix = child_path + "/"
for k in [k for k in cleared if k.startswith(prefix)]:
    if targets is None:
        cleared.pop(k, None)
    elif k[len(prefix):].split("/", 1)[0] in targets:
        cleared.pop(k, None)
```

需确认 anchor→tiling loopback 进入此路径，且 `rerun_selector` 返回 `{"InterleaveRotation", "QuarterRotation"}` 时，仅清除这两个分支的 node_status，HalfRotation 保持 completed 并跳过。

**方案**：如果当前路径不正确覆盖，在 loopback handler 中显式调用 `rerun_selector`。

---

## 方案优先级与实施顺序

| 优先级 | 方案 | 预计耗时减少 | 代码改动量 | 风险 |
|--------|------|-------------|-----------|------|
| **P0** | A1 (阶梯 stall) + A3 (aclose fix) | ~2000s (消除 2 次 stall false positive) | sdk_backend.py ~15行 | 低 |
| **P0** | C1 (hardware API 锁定) | ~1000s (消除 1 次 schema loopback) | 2 个 SKILL.md ~20行 | 极低 |
| **P1** | B2 (halt→retry 链路) + B3 (issue上限) | 0 (不减少时间，但改善体验) | graph_executor.py ~20行 | 极低 |
| **P1** | A2 (skill load verify) | ~500s (提前发现并重试 skill 加载失败) | sdk_backend.py ~10行 | 低 (仅 WARN) |
| **P2** | B1 (空操作日志) | 0 | runner.py ~10行, perf.py ~5行 | 极低 |
| **P2** | C2 (agent 写保护) | 0 | design_substages.py ~5行 | 极低 |
| **P2** | C3 (rerun_selector) | ~500s (仅重跑受影响模板) | graph_executor.py 验证 | 中 (需测试) |
