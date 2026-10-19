# foreach/TensorList 算子 precision_debug 入口被三层问题卡死 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：self_evolve_op 批跑 `20260807-144939-310314`（foreach_norm，
> 工作区 `output/foreachnorm/`），run.log + 精度产物 + 框架源码。
> 方案取舍见同目录 `02-analysis.md`（L3），本文只固化客观事实。

## 背景：卡在哪

entry→context→requirement→design（概设/详设/tiling/anchor/integrate/docgen/validate）→
test_design→codegen 全部 ok，codegen 构建出包（9619s，407 轮）。precision_debug 首轮
run_tests 的 `ascendc-devkit run-cases` 在 **PD-CONTRACT 数据契约校验处中止**（20/20 用例一个
都没执行），scope_guard 判 `upstream` → precision_debug 以 `upstream` 终止 → workflow halt
（`report.md`：run_tests=aborted、scope_guard=ok，无 perf/integrate/finalize，也无 cannbench_eval）。

- 算子本身可部署可调用：`last_deploy.json` smoke_passed=true；`run_tests_iter-0/run.log:2`
  `torch.ops.cann_bench.foreach_norm` 可调。**不是算子编译/注册/kernel 运行时缺陷**。
- 算子形态：**TensorList 输入**（`Tensor[] x`，foreach 家族），输入是"张量列表"。

---

## P1 — run_tests transition 崩溃：`max(real_errs)` 对全 None 列表抛 TypeError（框架 bug）

**现象**：`run.log:8291` `Stage 'run_tests' failed: '>' not supported between instances of
'NoneType' and 'NoneType'`。run_tests substage transition 抛异常。

**证据**：
- `precision_debug_substages.py:1906-1919`：
  ```python
  crashed = sum(1 for c in queue_for_best if c.get("max_err") == 999.0 or c.get("elapsed_ms", 0) < 0)
  real_errs = [c["max_err"] for c in queue_for_best
               if c.get("max_err") != 999.0 and c.get("elapsed_ms", 0) >= 0]
  ...
  "real_max_err": max(real_errs) if real_errs else None,
  ```
  过滤条件 `c.get("max_err") != 999.0` 对 `None` 成立、`c.get("elapsed_ms", 0) >= 0` 对缺省 0
  成立 → `max_err=None` 的条目全部进 `real_errs`。
- `control.json`：harness 中止，20/20 条 `failed_case_queue` 均 `max_err: null`（无任何用例执行）
  → `real_errs = [None]*20` → `max([None, ...])` 逐对 `None > None` → 精确复现报错原文。
- 报错出现在正常路径（agent 有产出 `_summary`，`precision_run_tests.json` 存在），非 abort 路径。

**触发条件**：任何「harness 在用例执行前中止、failed_case_queue 全 `max_err=null`」的场景
（本批 PD-CONTRACT 中止即一类；不依赖具体算子形态）。

**影响**：transition 崩溃；其异常被记为 `state.last_error`，被 `__halt__` 误用为顶层 halt 消息
（见 P3）。

## P2 — TensorList 输入契约不一致：op_spec 标 REQUIRED、用例给 list-of-lists → PD-CONTRACT 中止 → upstream halt

**现象**：`run_tests_iter-0/run.log:3` `Error: [PD-CONTRACT] test_cases[0].inputs[0].shape must
be list[int] (got [[1024, 1024], [1024, 1024]])`。20/20 用例同型，harness 未执行任何用例。
scope_guard 判 upstream，halt 原因指向 `test_design`（`control.json.scope_reason`）。

**证据**（三层不一致）：
1. **用例数据**：`state.test_cases`（`cases_source=cannbench`，经 `cann_bench_cases_loader`
   忠实转写 cann-bench CSV）中 `inputs[0].shape = [[1024,1024],[1024,1024]]`（list-of-lists，
   TensorList 语义：列表内每个张量一个内层 shape）。
2. **op_spec 声明**：`requirement.json` inputs[0] `param_type="REQUIRED"` 且 `is_list=true`
   （语义矛盾——TensorList 输入标 REQUIRED）。`Requirement.op_spec` 由 `OperatorSpec.from_dict`
   构建（`requirement.py:107`）；`TensorSpec`（`operator.py:172-193`）**没有 `is_list` 字段**，
   `filter_known_fields` 把 `is_list` 丢弃，仅保留 `param_type="REQUIRED"`。
3. **runner 闸门**：`runner.py:197-212` 仅在 `operator.inputs[j].param_type == "DYNAMIC"` 时放行
   `list[list[int]]`，否则要求 `list[int]`。op_spec 是 REQUIRED → `is_dynamic=False` → 报
   `must be list[int]`。

**旁证**：codegen `decision_log.json` known_issues 已记录此矛盾——"design_spec/requirement 将
TensorList 输入 x 的 param_type 声明为 REQUIRED（is_list=true 却标 REQUIRED，语义矛盾）：CANN
框架对动态列表必须声明 ParamType(DYNAMIC)…故 op_def 采用 DYNAMIC（harness 的 DYNAMIC 分支亦按此
校验 list[list[int]] shape）"。即 **op_def 层已用 DYNAMIC**，只有 requirement/design_spec 层还是
REQUIRED；runner 读的是后者 → DYNAMIC 分支永不触发。

**影响**：foreach/TensorList 类算子（`Tensor[]` 输入）**无法进入精度循环**，harness 一个用例
都不跑即 upstream halt。scope_guard 判 upstream 本身正确（非 kernel 精度问题）。

## P3 — workflow 顶层 halt 消息误用 last_error(TypeError)，掩盖真实上游原因

**现象**：`run.log:8414` `Workflow halted: stage 'precision_debug' exhausted its correction
budget on an unresolved build/precision failure (TypeError: '>' not supported between instances
of 'NoneType' and 'NoneType')`。而真实原因是 scope_guard 的 upstream 判定，仅在
`run.log:8382/8411` 以 `precision_debug HALTED — upstream defect in [test_design]...` 单独打了一
条，未进入 dispatcher 终端消息。

**证据**：
- `graph_executor.py:531-540` `__halt__` 分支：`halt_msg = last_err.message if last_err else
  "corrective/escalation quota exhausted..."` → 用 `state.last_error`（P1 的 TypeError）作 message。
- `graph_executor.py:485-493` 有 `__escalate__:upstream` 专用分支会把 `debug_result.halt_reason`
  （= scope_reason）透传到 `halt_reason.message`，但 **self_evolve_op 的 precision_debug 组路由
  `"upstream": ("__halt__","escalation")`（`workflow.py:563`）直连 `__halt__`，不经该分支**。
- `_sync_debug_result`（`precision_debug_substages.py:1217-1233`）已把 scope_reason 写进
  `debug_result.halt_reason` 并打 ERROR 日志——数据在，只是 `__halt__` 没读它。

**影响**：可诊断性缺陷（§1.2 违背）——顶层只看到"TypeError 实现 bug"，诱导误诊为 codegen/kernel
实现缺陷，掩盖 P2 的真实契约不一致。

---

## 排除项 / 相邻低优先（不在本包主修，另述）

- **W3 m.def 自检假阳性**：`codegen.py:1467` 正则 `Tensor\??\s+(\w+)` 不认 `Tensor[]`
  （TensorList）语法 → `tensor_params=[]` vs manifest `['x']` 误报 phantom mismatch；同时也漏检
  真实 `Tensor[]` 同类 bug。诊断完整性缺口，低优先，单独修。
- **W4 codegen 阶段 smoke 假阴性**：codegen 会话内 `ascendc-devkit redeploy` 时
  `callable_target=None`（transcript 自述 "missing callable_target in state"），`runner.py:688`
  对空 kind 抛 ValueError → smoke_passed=False（D4 不 halt、留给 scope_guard）。后续 precision_debug
  redeploy 从 manifest 解析到 callable_target → smoke_passed=true。属状态中继缺口，低优先，单独修。
- **P2 的 scope_guard 归属表述**：halt 文案把上游归属写成 `test_design`，但更精确的契约源头是
  requirement 层 param_type 误标（op_spec 是 runner 实际读取源）。归属判定本身（upstream）正确。
