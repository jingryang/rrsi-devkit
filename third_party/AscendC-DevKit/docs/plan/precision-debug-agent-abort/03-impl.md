# precision_debug agent 中断 → 重试保障 — L4 实施方案（2026-07-22）

> 层级：**L4 实施方案**。具体改哪个函数、什么顺序、怎么验证。
> 问题记录见 `01-problems.md`；方案分析见 `02-analysis.md`。

## 改动范围

| 文件 | 改动类型 |
|------|---------|
| `substages` | 主要改动：基类加 5 个 helper（含 `_handle_abort` DRY 封装）+ 7 个 substage 各改 `transition()` 和 `resolve_condition()` |
| `tree` | transition_table 加 `agent_aborted` / `abort_exhausted` 条目 |

---

## 实施步骤

### Step 1: control.json contract 加 `consecutive_aborts`

| # | 位置 | 改法 |
|---|------|------|
| S1a | `substages._CONTROL_REQUIRED_KEYS` | 新增 `"consecutive_aborts"` |
| S1b | `substages._CONTROL_DEFAULTS` | 新增 `"consecutive_aborts": 0` |
| S1c | `substages._extract_debug_checkpoint` | 新增 `"consecutive_aborts": cp.get("consecutive_aborts", 0)` |

### Step 2: 基类 `_PrecisionDebugSubstage` 加 5 个 helper

| # | 方法 | 职责 |
|---|------|------|
| S2a | `_agent_produced_output(state) → bool` | 检查 round-suffixed phase JSON 是否存在且非空。False = agent 中断 |
| S2b | `_bump_consecutive_aborts(state)` | `consecutive_aborts += 1` 写入 control.json |
| S2c | `_reset_consecutive_aborts(state)` | `consecutive_aborts = 0` 写入 control.json（仅在当前值 ≠ 0 时写，减少磁盘 IO） |
| S2d | `_resolve_abort_condition(dc) → str \| None` | `consecutive_aborts >= 3` → `"abort_exhausted"`；`agent_aborted` → `"agent_aborted"`；否则 `None` |
| S2e | `_handle_abort(state, *, bump_counters=False) → State` | 非 RunTests substage 的通用 abort 转移体（恢复时新增，§1.2 DRY）：bump `consecutive_aborts` + 可选 bump `corrective_cycles`/`run_iter_counter` + append history + 置 `agent_aborted` flag + `_sync_debug_result`。替代 Step 5 各 stage 内联块 |

**`_agent_produced_output` 判据**：

```
文件不存在           → False（agent 没跑到写文件就死了）
文件存在但 JSON 损坏  → False（写了一半被 kill）
文件存在、JSON 合法但 {} → False（空壳/占位文件）
文件存在、JSON 合法、非空 → True（agent 正常完成）
```

**`_resolve_abort_condition` 逻辑**：

```python
def _resolve_abort_condition(self, dc: dict) -> str | None:
    if dc.get("consecutive_aborts", 0) >= 3:
        return "abort_exhausted"
    if dc.get("agent_aborted"):
        return "agent_aborted"
    return None
```

每个 `resolve_condition()` 开头统一调用：
```python
if (c := self._resolve_abort_condition(dc)) is not None:
    return c
```

### Step 3: transition_table 加 `agent_aborted` / `abort_exhausted` 条目

| # | 位置 | 改法 |
|---|------|------|
| S3 | `tree._PRECISION_DEBUG_TRANSITION_TABLE` 每个 stage | 新增 `"agent_aborted": ("<stage>", "corrective")` 和 `"abort_exhausted": ("__escalate__:exhausted", "validation")` |

```python
"run_tests":       {"agent_aborted": ("run_tests", "corrective"),       "abort_exhausted": ...}
"diagnose":        {"agent_aborted": ("diagnose", "corrective"),        "abort_exhausted": ...}
"fix":             {"agent_aborted": ("fix", "corrective"),             "abort_exhausted": ...}
"diagnose_refine": {"agent_aborted": ("diagnose_refine", "corrective"), "abort_exhausted": ...}
"printf_location": {"agent_aborted": ("printf_location", "corrective"), "abort_exhausted": ...}
"scope_guard":     {"agent_aborted": ("scope_guard", "corrective"),     "abort_exhausted": ...}
```

### Step 4: `RunTestsSubstage` 改造

已有中断检测（`_read_agent_summary` 返回空 → `agent_aborted=True`），**只改两处**：

| # | 位置 | 改法 |
|---|------|------|
| S4a | `transition()` abort 路径 | 加 `self._bump_consecutive_aborts(state)`（在 `Logger.warn` 之后） |
| S4b | `transition()` normal 路径 | 加 `self._reset_consecutive_aborts(state)`（在正常路径开头） |
| S4c | `resolve_condition()` | 替换 `if dc.get("agent_aborted"): return "has_failures"` 为 `if (c := self._resolve_abort_condition(dc)) is not None: return c` |

### Step 5: 其余 6 个 substage 改造

> **实施偏离（2026-07-23 恢复时落实，§1.2 可维护）**：原 L4 写每个 stage 内联 abort 块。实际用 `_handle_abort(state, bump_counters=...)`（S2e）封装通用路径，各 stage 仅传 `bump_counters` 区分重量级（fix/printf_location/comment_bisect=True，烧 corrective_cycles 预算）与轻量级（diagnose/diagnose_refine/scope_guard=False）。等价但消除 6 处重复。下文内联块为逻辑等价描述。

每个 stage 的改造模式相同：

**`transition()`**：在业务逻辑之前加中断检测块：
```python
if not self._agent_produced_output(state):
    self._bump_consecutive_aborts(state)
    # [stage-specific counter bumps]
    dc["agent_aborted"] = True
    state = state.with_updates(_debug_checkpoint=dc)
    return _sync_debug_result(state, dc)
self._reset_consecutive_aborts(state)
```

**`resolve_condition()`**：开头加：
```python
if (c := self._resolve_abort_condition(dc)) is not None:
    return c
```

各 stage 的 stage-specific 处理：

| Stage | abort 时额外操作 |
|-------|-----------------|
| `DiagnoseSubstage` | 无（不递增计数器，diagnose 没有独立计数器） |
| `FixSubstage` | 递增 `corrective_cycles` + `run_iter_counter`（防止死循环） |
| `DiagnoseRefineSubstage` | 无 |
| `PrintfLocateSubstage` | 递增 `corrective_cycles` + `run_iter_counter` |
| `CommentBisectSubstage` | 递增 `corrective_cycles` + `run_iter_counter`（同 printf_location，runtime 定位也是 redeploy-heavy） |
| `ScopeGuardSubstage` | 无。**关键**：`_resolve_abort_condition` 必须在 contract 校验（verdict ∈ {upstream, pass}）**之前**，否则空 verdict 触发 `PrecisionDebugContractError` |

---

## 退火行为矩阵

| 阶段 | 计数器 | 耗尽后 |
|------|--------|--------|
| `run_tests` | `consecutive_aborts`（≥3）+ `rounds`（> max_iterations） | abort_exhausted 或 exhausted → escalate |
| `diagnose` | `consecutive_aborts`（≥3） | abort_exhausted → escalate |
| `fix` | `consecutive_aborts`（≥3）+ `corrective_cycles`（≥8） | 先到先触发 |
| `diagnose_refine` | `consecutive_aborts`（≥3）+ `refine_cycles`（> 3） | 先到先触发 |
| `printf_location` | `consecutive_aborts`（≥3）+ `corrective_cycles`（≥8） | 先到先触发 |
| `comment_bisect` | `consecutive_aborts`（≥3）+ `corrective_cycles`（≥8） | 先到先触发 |
| `scope_guard` | `consecutive_aborts`（≥3） | abort_exhausted → escalate |

graph_executor 的 stagnation 检测（同一 from→to pair ≥2 次 → halt）作为额外安全网。

---

## 验证

### UT

- `_agent_produced_output`：文件不存在/空文件/损坏 JSON/正常 JSON → 各返回预期值
- `_resolve_abort_condition`：consecutive_aborts=0,1,2,3 + agent_aborted=True/False → 各返回预期值
- `_bump_consecutive_aborts` / `_reset_consecutive_aborts`：读写 control.json 正确
- 各 stage `resolve_condition`：abort 条件优先级高于业务条件
- ScopeGuardSubstage：abort 路由在 contract 校验之前（不抛异常）

### ST（npu）

- 模拟 run_tests agent 中断（空 phase JSON）→ 验证 retry 而非进 diagnose
- 连续 3 次中断 → 验证 abort_exhausted escalate

### 回归

- 现有 precision_debug 相关 UT 全量通过
- 非 heavy ST 全量通过

---

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-07-22 | 初版：5 步实施计划，覆盖 2 文件、6 个 substage |
| 2026-07-23 | **恢复实施**：代码曾因未提交丢失（`git log -S consecutive_aborts`=0 证实从未入库）。按本 L4 落实 2 文件 7 个 substage，两处合理偏离：① Step 2 实为 5 helper（增 `_handle_abort` S2e，DRY 封装，替代 Step 5 内联块）；② 实际覆盖 7 个 substage（补 comment_bisect，同 fix/printf 走 `bump_counters=True`）。TDD 守护 `test_precision_debug_agent_abort.py`（31 用例：transition_table 路由 / `_resolve_abort_condition` 优先级 / 计数器磁盘往返 / `_agent_produced_output` 判据 / `_handle_abort` bump_counters 区分 / RunTests 自有路径 / 退火升级 / 正常产出清零 / ScopeGuard abort 不触发契约错误）+ 全量 orchestration UT 1450 passed/0 回归。heavy_llm 真实中断链路 ST 待用户决策（§3.11） |
