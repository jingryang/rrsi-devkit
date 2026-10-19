# 39 — Option A：软 stage timeout（成功 iteration 不假杀）（L4 实施方案）

> 工作线：self-evolution
> 状态：**已实施**（2026-07-12）
> 关联 L3：`39-soft-stage-timeout-analysis.md`
> 上游 plan：`/root/.claude/plans/lovely-painting-aurora.md` 方案三

## 改动（函数级，仅 `orchestration/kernel/runner.py`）

1. **`__init__`**（83-86）：新增实例变量 `self._last_iter_ok: bool = False`。注释说明：soft timeout 判据——慢但成功的 run（如 swi_glu 4484s vs 3600s budget 但产物完整可 salvage）不应被 StageTimeoutError 假杀。
2. **`run_stage`**（98）顶部（152）：`self._last_iter_ok = False`（每次 stage 开始重置——第一次 iteration 顶部 check 时 deadline 未到，不会误 raise）。
3. **`run_stage` 迭代循环**（306）：transition 后设 `self._last_iter_ok = (_agent_res.status == "ok")`——记录上一 iteration agent 是否 ok。
4. **`_check_timeout`**（448-483）stage 段（461-483）：
   - workflow 段（451-460）**不变**（global 硬墙先判）。
   - stage 段（461）：`if self._stage_deadline is not None and now > self._stage_deadline:` 内：
     - **`if self._last_iter_ok:`**（469）→ `Logger.warn("stage '...' overran its stage deadline but the last agent iteration succeeded — continuing (soft timeout, Option A)")` + `return`（soft，不 raise）。
     - 否则（475-483）→ `event_log.append(evt.stage_timeout(...))` + `raise StageTimeoutError(...)`（hard，失败/卡死仍 raise）。

## 语义矩阵

| 上一 iteration agent | stage 超时行为 | 兜底 |
|---|---|---|
| ok（成功但慢） | soft：warn + 继续 | max_iterations + global WorkflowTimeout |
| partial/infra/fatal（失败/卡死） | hard：raise StageTimeoutError | 断路器 + infra guard + max_iterations |

## 验证（前台 pytest，§3.3/§3.8）

- **UT**（`tests/ut/orchestration/test_kernel.py`，6 用例）：fake deadline + `_last_iter_ok=True` 不 raise / `=False` raise；workflow timeout 仍硬 raise；stage 开始时 `_last_iter_ok=False` 不误 raise。全绿。
- **回归**：全量 UT 1839 passed，0 回归。
- **ST**（§3.9，非 heavy）：`test_integration.py` 慢 stage 场景（fake 长 spawn + 短 stage budget + agent ok → 不假杀）随非 heavy ST 94 passed。
- **heavy_llm**：Option A 是 runner 确定性逻辑，无 LLM 全流程依赖，无 heavy_llm 用例。

## 诚实边界

- soft 路径不假杀「成功但慢」的 run，但**不加速**——swi_glu 真·慢（0×429，3 iter 未收敛）仍需抬 STAGE_TIMEOUT 或认 codegen 算力不足（P7 用户裁定不动 429 本身，但 STAGE_TIMEOUT 是可调参）。
- soft 不替代 global timeout——workflow deadline 仍是硬墙。
