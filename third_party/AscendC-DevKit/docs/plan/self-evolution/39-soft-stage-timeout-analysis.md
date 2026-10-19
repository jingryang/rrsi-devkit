# 39 — Option A：软 stage timeout（成功 iteration 不假杀）（L3 方案分析）

> 工作线：self-evolution（六算子批跑收口）
> 状态：**已拍板冻结**（2026-07-12）
> 关联 L4：`39-soft-stage-timeout-impl.md`；L1：`batch-sixops-runlog.md` 问题 4/7
> 上游 plan：`/root/.claude/plans/lovely-painting-aurora.md` 方案三

## 问题（L1 事实引用）

`_check_timeout` 是 post-hoc 迭代边界判定（`runner.py`）：agent 跑过 deadline 不被硬中断，返回后下个检查点才 raise。swi_glu codegen 跑 4484s（budget 3600s）被判 `StageTimeoutError`，**但产物完整可用**（salvage 77.42, 20/20）——timeout 扔掉了成功结果。同理 swi_glu 首跑 2976s>1200s budget 也是产物完整被判 exit 124。

## 选项

### A. 软 stage timeout（上一 iteration agent ok 则不 raise）✅ 选定
- 落点：`runner.run_stage` 记 `self._last_iter_ok`（上一 iteration agent 是否 ok），`_check_timeout` stage 段 raise 条件加 `and not self._last_iter_ok`——上一 iteration agent ok（成功但慢）则 soft（`Logger.warn` 不 raise，继续迭代）；失败/卡死（partial/infra/fatal）仍 raise。
- 优点：最小改动（runner.py 一处）；成功但慢的 run 不被假杀，产物不丢；失败/卡死仍被硬墙 + 断路器 + max_iterations 兜底。
- 语义：成功但慢（agent ok 产出构建物，transition 未满足要再迭代）→ soft 继续 → 有机会修 smoke 或到 max_iterations 自然停；失败/卡死 → 仍 raise + `codegen_consecutive_failures` 3 次 halt + infra actions guard + max_iterations 兜底；不收敛但每次 ok → 被 max_iterations（codegen=5）兜住，global timeout 是最终硬墙。

### B. 硬 stage timeout + 中断（asyncio 取消）❌ 不选
- 落点：mid-spawn 取消 `asyncio query()` async generator。
- 缺点：mid-tool-use 取消会让文件半写、session 半成品；`sdk_backend.py` 的 `aclose()` race 已示取消路径脆弱；对 swi_glu 这类慢但成功的 run，硬中断反而阻止成功（多一次中断+续接）。
- 否决理由：其「bounded + recoverable」诉求由 A + global timeout + 提案#1 共同满足，不需硬中断的复杂度与脆弱性。

## 决策

**选 A**。理由（§1.2）：
- **可维护**：维持「stage timeout 是迭代边界判定」语义，只细化 raise 条件（成功 vs 失败），不引入新的中断机制。
- **可扩展**：任何「成功但慢」的 stage 自动受益，不需逐 stage 配置。
- **可诊断**：soft 超时 `Logger.warn` 留信号（不静默）；hard 超时仍 raise + event log。
- **架构合理**：改动落在 runner（stage 执行层），不越层。

## 剩余防线已确认覆盖（不假杀 ≠ 无界）

- **SDK stall 检测**：`sdk_backend.py` 内容级 `MAX_STALLED_TURNS`（卡死——内容不变——被抓，"Time is never a factor"）。
- **codegen 断路器**：`codegen_consecutive_failures` 3 次 halt。
- **max_iterations**：iteration_ceiling（codegen=5）兜不收敛。
- **global `WorkflowTimeoutError`**：硬墙（`_check_timeout` workflow 段不变，461 之前先判 workflow deadline）。

即：soft 路径有四道兜底，不会无限跑。
