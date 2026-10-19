# L4 实施方案 — P42 升级退出状态归属 + scorer 超时文案（TDD）

> 对应 L3 冻结方案（选项②处置点标记 / 文案分流）。

## 改动 1：State transient 字段（kernel/state.py）

`_bubble_origin: str = ""`（声明于 `_bubble_signature` 后）+ `to_snapshot`/`from_snapshot`
双侧 strip（与 `_bubble_condition` 同块）——per-pass 路由信号不持久化。

## 改动 2：graph_executor.py 升级发射分支

删 P40 无条件 `node_status[child_path]="failed"`；改为 with_updates 携带
`_bubble_origin`（原子叶=发射点；组再升级=保留更深层 origin）。

## 改动 3：graph_executor.py bubble 消费点 + `__halt__` 分支

- 消费点（组 child 带 bubble 进入路由）：捕获 `bubble_origin` 局部变量并清 transient
  （防 stale 泄漏到后续路由）；
- `__halt__` 分支：标记 direct child（原 P40）后，`bubble_origin` 非空则**追加标记 origin
  原子叶**——halt ⇒ 组+源双标，resume 重入 halt 源契约保留。

## 改动 4：cannbench_scorer.py 超时分支

`TimeoutExpired` → 独立超时 message（含 hang 类排查指引），不走 `_infra_error` 前缀。

## 验证

1. **UT**（`tests/ut/orchestration/test_escalation_exit_status.py`，6 用例）：
   all_pass 升级干净退出（零 failed）/ 软门 exhausted 前进零 failed / halt 升级标
   组+origin / 直接原子 halt 只标自身 / 组再升级保深层 origin / snapshot 剥离。
2. **UT**（`test_cannbench_scorer.py` 追加）：超时 reason 含「超时」且不含「前置环境缺失」。
3. 全量 `tests/ut --quick`；相关非 LLM ST。
4. heavy_llm 批跑属既有待办（step-90 已列），本步骤不新增独立 heavy 用例（无新 LLM 链路）。

## 不做清单

1. 不按条件名枚举 halt-class（L3 ①否决）。
2. 不动 A5 代码（共享层单点修复自动惠及）。
3. 不修 eval 超时本身（外部 infra，fail-open 边界）；超时无 stderr 留档仅 L1 P3 声明。
4. 不动 dispatcher 出口判定（`failed_nodes` 读 node_status 本身正确，脏源头已治）。

## as-built（2026-08-26）

- 改动 1-4 全部按上述落地；发射分支注释改为 P42（说明为何不在此标 + 何处标）。
- 验证：
  - `test_escalation_exit_status.py` **6 passed**（含直接原子 halt 断言修正：root 组传播
    使 failed = `[pipeline, pipeline/codegen]` 两项，符合 `_group_status` 设计）；
  - `test_cannbench_scorer.py` **23 passed**（+1 超时文案）；
  - 全量 `tests/ut --quick` **3639 passed / 0 failed**（3631 基线 + 8 新增，零回归）；
  - 相邻路由套件（composite_loopback / precision_debug_routing / state_routing /
    graph_executor / design_workflow_integration / precision_debug_agent_abort）
    **108 passed**；
  - 非 LLM ST（self_evolution_stages + precision_diagnose_inplace_loop）**36 passed**。
- 事故回放对照：ccad38 形态（run_tests all_pass → 根表无 passed 条目线性前进）即用例 1
  的树形；halt 形态（upstream → `__halt__`）即用例 3，resume 权威与 P40 一致。
- **过程记录（诚实）**：本步骤实现先于用例落盘（§3.1 字面顺序偏离）——「红」由生产事故
  本身承担（ccad38 即 P1 的失败实证）；`test_acquire_never_creates_control_json` 按构造
  对 step-90 旧码必红（旧 acquire 无条件建 control.json），未回滚演示。

## as-built 追加（2026-08-26，P4/P5 修复）

- **P5**：GE 升级分支 passed 短路（`escalation_cond != "passed"` 才 `_converge_precision_debug`）。
  passed 收敛在 transition 内由 `_sync_debug_result` 完成；GE 只兜底中途升级
  （architecture-timeout 经 except 通道，保持既有行为）。收敛函数对 passed 的语义由
  `test_passed_also_converges_for_binary_consistency` 守护不变。
- **P4**：`_dump_partial_output` + `_write_stream`（单点落盘，`_log_eval_failure` 复用，
  §1.15）——超时分支把异常携带的 stdout/stderr 全量写 `ws.subprocess_log/`。
- **验证**：`test_passed_escalation_does_not_reconverge`（GE spy calls==0）+ `_dump_partial_output`
  用例先红后绿；既有 `test_passed_converge_is_safe_via_internal_short_circuit` 断言随新契约
  更新（calls 1→0，注明收敛语义由 converge 独立测试守护）。全量 `tests/ut --quick`
  **3641 passed / 0 failed**（含 graph_executor 43 全绿）。

## as-built 追加 2（2026-08-26，P5 审计修正：条件名代理 → 业务语义标记）

审计发现前一版 P5 的 `escalation_cond != "passed"` 是「按条件名枚举」——正是本线修 P42 时
批判的反模式（§1.10），且只覆盖 passed，exhausted/stalled 同样走 transition 终态收敛、
依旧双收敛。修正：

- State 新 transient `_converged_this_pass: bool`（snapshot 双侧剥离）；
- `_sync_debug_result` 终态收敛块设 `True`（声明已收敛）；abort/timeout 早退未设 →
  False → GE 兜底收敛保留；
- GE 升级分支按 `not getattr(state, "_converged_this_pass", False)` 跳重复收敛
  （业务语义标记，uniform 覆盖 passed/exhausted/stalled）；
- 测试：`test_no_ge_converge_when_transition_declared_converged`（声明→calls==0）+
  `test_ge_converges_when_transition_did_not`（未声明→GE 兜底收敛 + __halt__ 标 origin）；
  既有 `test_passed_converge_is_safe_via_internal_short_circuit` 断言回写 calls==1
  （孤立调用场景未设标记 → GE 兜底收敛语义不变）。
- 全量 `tests/ut --quick` **3642 passed / 0 failed**。

## as-built 追加 3（2026-08-26，P6：回放实证 bytes + dump 防护）

- 回放 ccad38（`--resume`）实测：eval 超时点 `_write_stream` 写 bytes → uncaught →
  stage failed/aborted。修复：`_write_stream` bytes→decode("utf-8", errors="replace")；
  超时分支 dump 外包 try/except（失败 WARN 留痕，超时仍按 infra 返回，§1.2 宽容兜底）。
- TDD：`test_timeout_dump_handles_bytes_output` + `test_dump_failure_does_not_break_timeout_route`
  先红后绿。全量 `tests/ut --quick` **3644 passed / 0 failed**。

## 回放验证记录（20260825-153847-ccad38，2026-08-26）

- **P-A 验证**：run_tests all_pass 干净退出，`failed stages` 不再含 run_tests
  （残留的 `[.../cannbench_eval]` 是超时本身的诚实标记，正确）——此前是
  `[..., run_tests]`（误标）。
- **P-B 验证**：全程**无** PD-CONTRACT WARN、init-checkpoint 正常执行（config 种子值完整）。
- **P5 验证**：`converge_best_commit` 仅**一次**（11:11:38）——此前背靠背两次。
- **P4/P6 验证**：eval 30 分钟超时 → `eval timed out (30 min)` 文案（非「前置环境缺失」）；
  subprocess/ 目录未见 dump 文件（bytes 炸 + dump 未防护，即 P6 本体）。
- eval 超时本身（外部 infra）未变：child 重启重试 ~30 分钟仍不退出，属 kernel/driver
  hang 类，resume 语义不变。
