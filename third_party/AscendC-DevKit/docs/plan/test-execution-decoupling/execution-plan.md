# P0 + step-40 自主执行计划

> **目的**：自主跑完 P0（precision_debug 编排根治）+ step-40（测试执行外部化），用户最后一次性 check。
> **方式**：串行编码（P0 先 + 各自验证）+ 阶段并行预备（step-40 协议/backend 可与 P0 并行）。heavy_llm 前停下汇总（§3.11）。
> **方案依据**：P0 L4 `self-evolution/51-*.md`、step-40 L3 `test-execution-decoupling/02-analysis.md`（v3 冻结）、step-40 L4 `03-impl-evaluation-backend.md`。

---

## 执行顺序与验证点

### 阶段 1：P0 编排重构（task #5）

**编码（TDD 红→绿）**：
1. `state.py` 加 `_debug_checkpoint: dict | None = None`
2. `precision_debug_substages.py`：`_load_checkpoint` / `_extract_debug_checkpoint` + 4 子 stage（RunTests/Diagnose/Fix/PrintfLocate）—— 各 transition/resolve_condition/loopback_feedback
3. `precision_debug_tree.py`：`build_precision_debug_group` + `_PRECISION_DEBUG_TRANSITION_TABLE`
4. `workflow.py`：`AtomicStage(PrecisionDebugStage())` → `build_precision_debug_group()`
5. `precision_debug.py`：删 PrecisionDebugStage / `_build_prompt` / `_build_a5_prompt` / `_actions_legacy` / `_actions_a5`；保留 `run_precision_cases` / `try_load_cannbench_task`（暂留）/ `DEBUG_RESULT_CONTRACT`
6. 删 `.claude/agents/ascendc-precision-debugger.md` + `-a5.md` + `stage-transition.py`

**验证（task #6）**：
- 重写 `test_precision_debug_stage.py`（4 子 stage transition/resolve_condition/loopback + TRANSITION_TABLE 路由）
- 全量 UT 绿 + 非 heavy ST 绿（重点 `test_self_evolution_stages`）
- **heavy_llm 不自动跑**（§3.11），记入 task #9 汇总

### 阶段 2：step-40 执行外部化（task #7，可与阶段 1 并行预备）

**编码（TDD 红→绿，4 Phase，step-40 L4 §8）**：
- Phase A：`domain/evaluation.py`（EvalRequest/TestReport/CaseReport/RunMode/OpRef）+ `adapters/evaluation/__init__.py`（协议 + select_backend）
- Phase B：`adapters/evaluation/devkit.py`（DevkitBackend，迁 runner.execute + DevkitComparer）
- Phase C：`adapters/evaluation/cannbench.py`（CannbenchBackend 模块形态，内化 DataGenerator/compare_tensors；双向 adapter）
- Phase D：`state.py` 加 `cases_source`；`test_design_substages._load_external_cases` 标 source；`run_precision_cases` 改调 `select_backend().run()`；删 `try_load_cannbench_task` + `task_loader.py`

**验证（task #8）**：
- backend 协议 UT + DevkitBackend/CannbenchBackend UT（mock 外部 import）+ run_precision_cases 接入 UT
- 全量 UT + 非 heavy ST 绿
- **heavy_llm 不自动跑**，记入 task #9

### 阶段 3：集成 + heavy_llm 汇总（task #9）

P0 + step-40 各自 UT/ST 绿后，汇总 heavy_llm 待跑项给用户：
- **P0 编排 heavy_llm**：真实 precision_debug 全流程（子 agent 派发/checkpoint 读写/loopback 收敛）
- **step-40 执行 heavy_llm**：CannbenchBackend 标准对齐（scatter per-input value_range 正确 + 与权威评测一致）+ DevkitBackend 通用（ops-nn 算子零 cann-bench 依赖）
- 列清单 + 预估耗时/成本，用户决策跑/不跑/跑哪些（§3.11）

---

## 自主决策规则（不停下来问）

实施中遇 L3 §9 已转决策的 4 项，按默认执行（check 可推翻）：
1. TestReport 分层（精度必需 + 性能可选 + 三维分 Optional + extra 透传）
2. CannbenchBackend 默认模块形态（含"实测 CLI 延迟"探查步骤；可接受则改 CLI）
3. ② 不统一为 backend.run(BATCH)
4. EvalRequest 直接用 domain TestCase

**遇以下才停**：
- 设计冲突（L4 与实际代码不符，需调整方案）
- heavy_llm（§3.11，阶段 3 汇总）
- 测试失败且根因非当前改动（§3.4 诚实记录，不掩盖）

---

## 用户 check 要点（最后一次性 review）

1. **方案合理性**：P0 L4 §1-§12 + step-40 L3/L4 是否符合预期
2. **4 个可推翻决策**（L3 §9）：TestReport schema / CannbenchBackend 形态 / ② 统一 / EvalRequest 格式
3. **接口契合**：P0 run_tests 子 stage ↔ step-40 backend.run（§11.2）；cases_source 上游标记（step-40 L4 §7.1）
4. **删除项**（§2.5 唯一通路）：PrecisionDebugStage / 2 agent / stage-transition.py / task_loader / try_load_cannbench_task
5. **验证诚实性**：UT/ST 结果如实、heavy_llm 覆盖范围如实记录

---

## 关键文档索引

- P0 L4：`docs/plan/self-evolution/51-precision-debugger-async-fix-impl.md`
- step-40 L1：`docs/plan/test-execution-decoupling/01-problems.md`
- step-40 L3：`docs/plan/test-execution-decoupling/02-analysis.md`（v3 冻结）
- step-40 L4：`docs/plan/test-execution-decoupling/03-impl-evaluation-backend.md`
- 上游 L1（批跑事实）：`docs/plan/self-evolution/batch-runlog-20260715.md`
- 上游 L3（非 429 根因）：`docs/plan/self-evolution/50-non429-issues-analysis.md`
