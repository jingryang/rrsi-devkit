# P57 — 能力下沉 + 删冗余 stage（deploy/verify）— 实施方案（第四层）

> 范围：**Option II 全局一致**（全 5 workflow：generate_ascendc/dev/se、full_test、self_evolve_op）。codegen 共享 stage 的 build 闭环是 all-or-nothing（L3 §12.1），用户 2026-07-09 改拍全局一致，P58 吸收进本步（不再 follow-up）。
> 层级：**第四层 / 实施方案**。改哪个符号、什么顺序、怎么验证（TDD）。
> 依据：L3 `33-capability-sink-redundant-stages-analysis.md`（冻结 + §12 范围修订，D1-D8 + §9 + §12 决策）。
> 约定：按符号定位（不写 file:line）；外部依赖只读。

---

## 0. 基线（已存在，复用，不重建）

- `Deployer`（domain/service，P54 D3 抽出）：build→install→smoke 单一通路；`Deployer.deploy(state) → (DeployResult, ErrorFeedback|None)`。**本步保留**（`redeploy` CLI + codegen/precision_debug agent 都经它）；删的是 `DeployStage`（stage 壳），非 `Deployer`。
- CLI `redeploy` / `run-cases`（`cli/commands/debug.py`，P54 D11）。
- `DebugService`（`application/debug_service.py`）：`redeploy(run_dir)` 写 `<run>/debug/last_deploy.json`；`read_last_deploy(debug_dir)` 读回（文件接力）；`run_cases(...)` 读 last_deploy + 写 `<run>/debug/<iter>/result.json`。
- `CodegenStage`（`stages/codegen.py`，**共享**）：spawn `ascendc-coder`/`incremental-developer`，现状不调 Deployer；output_contract provides=`generated_sources`/`codegen_iterations`、optional `codegen_manifest`；有 stage iteration（`default_max_iterations=5`）+ circuit breaker（`max_consecutive_failures=3`）+ P50 infra 处理；现状消费 `build_result`/`precision_result` 作 loopback 反馈（B5 删）。
- `PrecisionDebugStage`（P54，**共享**）：agent 经 `redeploy`/`run-cases` in-session 闭环；`_build_prompt` 读 `state.precision_result` 作启动 guard（C 删）。
- `precision_result` 消费者全貌（L3 §12.2 取证）：verify（producer，随删）、codegen 反馈（B5 删）、precision_debug guard（C 删）、**perf 硬依赖**（requires + `PrecisionPassedGate` 门槛，换源 debug_result）、**integrate 死读**（删）、dispatcher 报告（换源）、runner 进度回调（换源）。
- `VerifyStage` 被 **full_test** 复用（test_suite 占位）+ ~10 测试文件直接 import（随类删见 F）。

---

## 1. 设计决策（实施前明确，避免返工）

### 1.1 build 闭环 = agent-driven（镜像 P54 precision_debug）

codegen 的 `ascendc-coder` agent 写完代码后**在会话内**调 `redeploy` CLI、读 build/smoke 结果、自修、再 redeploy，直到 smoke 过或 `max_rounds` 耗尽。**不**由 stage transition 调 Deployer。客观性由确定性 CLI 保，`transition` 读 `last_deploy.json` 做确定性断言兜底（D5）。

### 1.2 两类失败语义分离（关键，避免双 retry 混乱）

| 失败类型 | 含义 | 处理 |
|---|---|---|
| **结构不完整**（缺 section / manifest 缺 callable_target） | agent 没写出文件 | **现有 stage iteration re-spawn**（不变） |
| **build/smoke 失败**（编译错 / 符号解析失败） | agent 写了文件但跑不起来 | **agent 内 max_rounds 自修 → 耗尽 halt**（**不** stage iteration） |

两类失败判据互斥（结构完整才进 build 判定）。

### 1.3 `max_rounds` vs stage iteration 共存

- `_max_rounds(state)`（新增，镜像 precision_debug P55：user > config > default）= agent 内 build/smoke 自修上限，注入 prompt。
- `default_max_iterations=5`（stage iteration）保留，仅服务结构不完整 re-spawn。
- 两者维度不同（agent 内 vs stage 重启），与 P56 同形，可后续随 P56 一并治理。

### 1.4 `precision_result` 字段 + `PrecisionResult` 类：干净删除（§1.4 不留兼容/死代码）

State 删 `precision_result` 字段；消费者换源 `debug_result`（perf 门槛/dispatcher/runner）或删死读（integrate）/删消费（codegen 反馈 B5、precision_debug guard C）。`PrecisionResult` 类无 producer（verify 删）→ 一并删。`BuildResult`/`DeployResult`/`PrecisionDebugResult` 类保留。旧 run snapshot 含 `precision_result` key：`from_snapshot` 若 lenient 自然兼容；若 strict 旧 run 不可 resume（可接受，§1.4 无历史数据）——**不写迁移分支/别名**。实施时核对 `from_snapshot` leniency。

---

## 2. 改动点（A→F，TDD 每步红→绿）

### A. `Deployer` 落盘完整子进程输出（前置，两路径共用）

**改 `Deployer._run_command`**：失败分支把完整 stdout+stderr 写 `<run>/subprocess/<role>_<stagename>.log`（best-effort mkdir parents），返回的 err 描述含 **log 路径** + stderr 尾部（不再 `r.stderr[:1500]` 截断丢失全文）。

**改 `Deployer._err`**：`details = {"step", "log": <path>, "stderr_tail": <tail>}`——agent 经 log 路径读完整输出（D7）。`_resolve_fail` 同形。

复用面：codegen + precision_debug agent 都经此读完整 build stderr。

**TDD**：`test_deployer_persists_full_subprocess_output`——注入一条产出 >1500 字符 stderr 的失败命令，断言 log 文件含**完整** stderr、`_err` details 含 log 路径、stderr_tail 仅尾部摘要。

---

### B. `CodegenStage` in-session build 闭环（核心，**全局共享 stage**）

**B1. `_build_codegen_prompt`**：新增一节，注入 `run_dir`（经 `state._workspace`）+ 指令——写完代码后调 `ascendc-devkit redeploy --workspace <run_dir>`，读 `<run>/debug/last_deploy.json` 的 `smoke_passed` + build log（`<run>/subprocess/*.log`），编译/smoke 失败则读完整 stderr 自修、再 redeploy，直到 smoke 过或达 `max_rounds`。

**B2. `_max_rounds(state)`**（新增 helper）：优先级 `user_max_iterations` > config > default（同 precision_debug P55），注入 prompt。

**B3. `output_contract().provides`** 加 `build_result`、`deploy_result`。

**B4. `transition`**：成功分支（sections + manifest callable_target 完备）后，读 `<run>/debug/last_deploy.json`（经 `DebugService.read_last_deploy`）→ 组装 `deploy_result` + `build_result`；**断言 `smoke_passed`**——不过则 `last_error = ErrorFeedback(deploy_failed)` → halt 语义（不 re-spawn）。

**B5. 移除旧 loopback 反馈消费（全局影响）**：`actions` 的 context 与 `_build_codegen_prompt` 中对 `state.build_result` / `state.precision_result` 的 `build_failure`/`precision_failure` 段**删除**——redesign 后 codegen 自闭环 build、精度归 precision_debug，不再跨 stage 接收 build/precision 反馈。**全局生效**：generate_* 的 `verify→codegen` loopback（build/precision 反馈）随之失效——但 generate_* 图同步删 verify（E），无残留 loopback。保留对 `last_error`（codegen 自身 incomplete_output / infra）的处理。

**TDD**：
- `test_codegen_transition_reads_deploy_result`——stub `last_deploy.json`(smoke_passed=True)，断言 transition 设 `build_result`/`deploy_result`、smoke 断言过。
- `test_codegen_transition_halts_on_smoke_fail`——`last_deploy.json`(smoke_passed=False)，断言 `last_error.error_type=deploy_failed` + halt 语义。
- `test_codegen_prompt_injects_redeploy_loop`——断言 prompt 含 `run_dir` + `redeploy` 指令 + `max_rounds` 值。
- `test_codegen_no_legacy_loopback_feedback`——断言 prompt/context 不再含 build_failure/precision_failure 段。

---

### C. `PrecisionDebugStage` 去 `precision_result` guard + owns 功能+精度（全局）

**改 `input_contract`**：optional 去 `precision_result`。
**改 `_build_prompt`**：删 `pr = state.precision_result` 启动判断——总是接 codegen 之后，首轮 `run-cases` 即首量门（已过则短路退出）。
**全局语义**：generate_* 精度失败从「回 codegen」变「precision_debug agent 自修」（P54 原则推广）。

**TDD**：`test_precision_debug_runs_without_precision_result`——state 无 `precision_result`，断言 stage 正常派发 agent（不因缺 guard 失败）。

---

### D. relocate `precision_result` 消费者 → `debug_result`（D1–D4；D5/D6 见 E）

> **实施时发现的顺序修正**：`precision_result` 字段（D5）+ `PrecisionResult` 类（D6）的删除与 verify 的删除强耦合——`State.with_updates` 经 `dataclasses.replace`（strict，非预期 kwarg 即 TypeError），而 verify.transition 仍写 `with_updates(precision_result=...)`；且 verify 是 `precision_result` 唯一 producer。故 D5/D6 不能先于 verify 删除（E）。**D5/D6 随 E 一起做**（verify 删除时，最后 producer + 最后 self-消费者同时消失，字段/类一并删干净，§1.4/§2.5）。本步 D 只做消费者 relocate（D1–D4）：relocate 后 precision_result 仅剩 state 字段 + verify（自身产自身读），无下游消费者——transient 干净，待 E 收口。

**D1. perf**（硬依赖）：`PerfStage.input_contract().requires` 把 `precision_result` 换 `debug_result`；`PrecisionPassedGate.evaluate` 读 `evidence.get("debug_result")` 的 `.passed`。Option II 下 precision_debug 排 perf 前、产 `debug_result`，门槛语义不变（精度不过不测性能）。
**D2. integrate**（死读）：`VerifyCompleteGate.evaluate` 删 `precision = evidence.get("precision_result")` 死代码（只判 `build_result`）。
**D3. dispatcher**：精度报告读 `state.debug_result`（max_diff/passed）替代 `state.precision_result`（两处：`_route_reason` + `_format_error_for_display`）。
**D4. runner**：stage gate evidence dict 的 key `precision_result` 换 `debug_result`（runner 仅此一处引用 precision_result；perf/integrate 两 gate 的 evidence 同源，D1+D2 已让两 gate 都不读旧 key）。
**D5. State 字段删除**（→ 随 E）：删 `precision_result` 字段 + import（`state.py`）。`to_snapshot` 用 `asdict`（删字段即从快照消失）；`from_snapshot` 经 `cls(**data)`（strict，旧快照含 precision_result key 不可 resume——§1.4 无历史数据可接受，**不写** `data.pop("precision_result")` 迁移分支）。
**D6. `PrecisionResult` 类删除**（→ 随 E）：verify（唯一 producer）删后无引用 → 删（§1.4 不留死类）。`BuildResult`/`DeployResult`/`PrecisionDebugResult` 保留。

**TDD**（D1–D4）：
- `test_perf_gate_reads_debug_result`——perf 门槛读 `debug_result.passed`，缺则不过。
- `test_perf_input_contract_requires_debug_result`——requires 含 debug_result、不含 precision_result。
- `test_dispatcher_precision_report_reads_debug_result`——报告读 `debug_result`。
（`test_state_has_no_precision_result` 随 D5/E，本步不立。）

---

### E. workflow 全 5 摘除 deploy/verify + 删 stage 类 + transition（全局）

**E1. generate_ascendc / generate_ascendc_dev**：`_PIPELINE_STAGE_NAMES`/`_DEV_STAGE_NAMES` + `_design_root` after_names 去 `deploy`、`verify`，加 `precision_debug`（位置：codegen → precision_debug → perf → integrate）；TRANSITION_TABLE 删 `deploy`/`verify` 分支，加 `codegen`/`precision_debug` `exhausted: ("__halt__","escalation")`，`perf.tuned` 由 `verify` 改 `precision_debug`（perf 改码后重验精度）。
**E2. self_evolve_op**：`_SELF_EVOLVE_STAGE_NAMES` + after_names 去 `deploy`、`verify` → `...codegen → precision_debug → cannbench_adapt → cannbench_eval → finalize`；TRANSITION_TABLE 删 `deploy`/`verify` 分支，`codegen` 加 `exhausted→__halt__`。
**E3. full_test**：`test_suite` ForkJoin 现用 `verify` 占位 → 改 `precision_debug` 占位（保留 graph-native demo 结构；仍是占位，真实 test-stage 另立 follow-up）。
**E4. generate_ascendc_se**：无需改（design-only，无 codegen/deploy/verify/perf）。
**E5. 删 stage 类 + 吸收 D5/D6（字段/类）**：`VerifyStage`（`stages/verify.py`）+ `DeployStage`（`stages/deploy.py` 的 stage 壳，**保留 `Deployer`**）+ 其 gate 类（`PrecisionGate`/`CodegenCompleteGate`/`BuildInRepoGate` 等若仅 verify 用）；`registry.py` 去 `verify`/`deploy` 模块 import + 注册；`get_stage("deploy")`/`get_stage("verify")` 调用清零。**同步 D5/D6**：verify 删除后 `precision_result` 无 producer、`PrecisionResult` 无引用 → 删 `state.py` 的 `precision_result` 字段 + import、删 `domain/verification.py` 的 `PrecisionResult` 类（§1.4/§2.5，不留死字段/死类；不写 from_snapshot 迁移分支）。

**TDD**：
- `test_generate_workflows_no_deploy_verify`——generate_ascendc/dev 图节点序列无 deploy/verify、codegen→precision_debug→perf。
- `test_self_evolve_op_graph_no_deploy_verify`——codegen 直连 precision_debug。
- `test_workflows_codegen_precision_debug_exhausted_halts`——两 stage `exhausted→__halt__`。
- `test_perf_tuned_routes_to_precision_debug`——perf `tuned→precision_debug`。
- `test_no_deploy_verify_stage_registered`——registry 无 deploy/verify。

---

### F. 删 `DeployStage`/`VerifyStage` 类的测试 churn + 新增 A-E UT

**删/重写**（直接 import 已删类的）：
- `test_stages.py`：`TestVerifyStage`/`TestVerifyStageStubbed` 整类删；verify 相关 import 清理。
- `test_verify_precision_feedback.py`（P53）：verify 已删 → 整文件删（P53 被 P54 绕开，无 verify 守护对象）。
- `test_loopback.py`：verify 用例迁移为 precision_debug/codegen 等价用例或删。
- `test_plan_a_inrepo.py` / `test_verify_testcase_source.py` / `test_verify_golden_contract.py`：VerifyStage 依赖部分删/迁移。
- `test_stage_failure_status.py`：verify hook 部分迁移（crash bookkeeping 语义归 precision_debug）。
- `test_test_design_e2e.py`：VerifyStage 引用换 precision_debug 或删。
- `test_npu.py`：`DeployStage` 真部署用例 → 改经 `redeploy` CLI / `Deployer.deploy` 直调（保留真部署守护）。
- `test_self_evolution_stages.py`：`TestDeployStageContracts` 删（DeployStage 类删）；`Deployer` 内部 helper 测试保留。
- `test_domain.py` / `test_state_*.py`：`precision_result`/`PrecisionResult` 引用清理。

**新增**：A-E 各步 UT（见各步 TDD + §3 矩阵）。

**TDD**：无独立新断言；回归守护——全量 `pytest`（UT 全量 + 非 heavy ST + LLM/NPU/CANN 预检，§3.6）通过。

---

## 3. TDD 验证矩阵（汇总）

| 改动点 | 新增 UT（红→绿） |
|---|---|
| A | `test_deployer_persists_full_subprocess_output` |
| B | `test_codegen_transition_reads_deploy_result` / `..._halts_on_smoke_fail` / `..._prompt_injects_redeploy_loop` / `..._no_legacy_loopback_feedback` |
| C | `test_precision_debug_runs_without_precision_result` |
| D | `test_perf_gate_reads_debug_result` / `test_perf_input_contract_requires_debug_result` / `test_dispatcher_precision_report_reads_debug_result`（字段/类删除随 E） |
| E | `test_generate_workflows_no_deploy_verify` / `test_self_evolve_op_graph_no_deploy_verify` / `test_workflows_codegen_precision_debug_exhausted_halts` / `test_perf_tuned_routes_to_precision_debug` / `test_no_deploy_verify_stage_registered` / `test_state_has_no_precision_result`（吸收 D5） |
| F | （删/迁移 ~10 文件 + 新增 A-E UT；全量回归） |

---

## 4. 边界 / 不改

- **generate_ascendc_se**：不动（design-only）。
- **full_test 的真实 test-stage**：本步只把 verify 占位换 precision_debug 占位（保 demo 可编译）；真正 test-stage 另立 follow-up。
- **`Deployer` 服务 / `redeploy`/`run-cases` CLI / `DebugService`**：不动（复用 P54）。
- **heavy_llm e2e**（真实 codegen agent + NPU redeploy + run-cases 全流程，跨 workflow）：确定性逻辑（图/transition/字段/门槛）由 UT 守护；真实 LLM+NPU 全流程属 heavy_llm（§3.11），**特性交付 / PR 合并前由用户决策跑一次**（self_evolve_op + generate_ascendc 各端到端一遍：codegen 内闭环 build → precision_debug 精度 → perf/integrate）。
- **codegen circuit breaker / P50 infra 处理**：不变（build/smoke halt 走新 exhausted 路径，不冲突）。

---

## 5. 实施顺序与依赖

```
A（Deployer 落盘）  ← B/C/E 都依赖完整 stderr 可读
   ↓
B（codegen 闭环）   ← 产 build_result/deploy_result；移除 precision_result 消费（全局）
   ↓
C（precision_debug 去 guard）← 与 B 并行可，D 依赖两者移除消费
   ↓
D（D1–D4：relocate perf/integrate/dispatcher/runner → debug_result）← 依赖 B/C 移除消费
   ↓
E（全 5 workflow 图 + transition + 删 VerifyStage/DeployStage 类 + registry ＋ 吸收 D5/D6：删 precision_result 字段 + PrecisionResult 类）← 依赖 B 产 deploy_result、D 清空下游消费者、verify 删后字段/类无 producer
   ↓
F（测试 churn + 新增 UT + 全量回归）
```

每步 TDD 红→绿；全量 `pytest`（UT 全量 + 非 heavy ST + LLM/NPU/CANN 可达性预检，§3.6）。heavy_llm e2e（§3.11）PR 前用户决策。

---

## 6. as-built 冻结（实施完成 2026-07-09）

> Option II 全局一致已落地：全 5 workflow 摘除 deploy/verify；build 闭环归 codegen（in-session Deployer redeploy），精度归 precision_debug（in-session run-cases）。deploy/verify 确定性 shell stage 连同跨 stage 错误传递一并删除（P57 根因消除）。

### 6.1 源码改动（实际符号）

- **删**：`stages/verify.py`（整文件 + `VerifyStage` 及其 gate）；`stages/deploy.py` 的 `DeployStage` stage 壳（**保留 `Deployer`** domain service）；`state.py` 的 `precision_result` 字段 + import；`domain/verification.py` 的 `PrecisionResult` 类；`registry.py` 的 verify/deploy 模块 import + 注册。
- **改**：
  - `Deployer._run_command`/`_err`/`_resolve_fail`：失败落盘完整子进程输出到 `<run>/subprocess/<role>_<stage>.log`，err details 含 log 路径 + stderr 尾部（A）。
  - `CodegenStage`：`_build_codegen_prompt` 注入 run_dir + redeploy loop + max_rounds；`_max_rounds(state)` 新增（user>config>default）；`output_contract().provides` 加 build_result/deploy_result；`transition` 读 `last_deploy.json` 组装 deploy_result + 断言 smoke_passed（不过→deploy_failed halt）；删 build_result/precision_result 旧 loopback 反馈消费（B5）。
  - `PrecisionDebugStage`：`input_contract` 去 precision_result；`_build_prompt` 删启动 guard（首轮 run-cases 即首量门）（C）。
  - perf/integrate/dispatcher/runner：`precision_result` 消费 relocate → `debug_result`（D1–D4）；integrate `VerifyCompleteGate` 删死读。
  - 全 5 workflow（generate_ascendc/dev/se、full_test、self_evolve_op）：stage 名单 + transition table 摘 deploy/verify，codegen→precision_debug→perf，两 stage `exhausted→__halt__`，`perf.tuned→precision_debug`（E1–E3）。
  - `application/dispatcher.py`：`_preflight_deploy_capability` 触发条件由 `"deploy" not in stage_names` 改 `"codegen" not in stage_names`（codegen 在会话内经 Deployer redeploy；精确对应 codegen workflow，非 codegen workflow 不部署）。

### 6.2 L4 §F 之外发现的 3 处偏差（实施期取证后回填）

1. **`tests/st/test_loopback_e2e.py` 整文件删除**——L4 §F 仅列「loopback 用例迁移或删」，未点名该 e2e 文件。判定：该文件全部用例驱动已删的 verify corrective-loopback 机制（verify_iterations 增计、verify→codegen 反馈）；corrective-loopback 机制本身由 UT 全覆盖（composite_loopback / graph_executor / precision_debug_routing / design_routing / loopback_summary），无守护缺口。
2. **`_preflight_deploy_capability` 触发改 codegen**——L4 未提及该 preflight。`"deploy" not in stage_names` 在 deploy 删除后恒真，会把所有 workflow 误判为不可部署而拒绝。改为 `"codegen" not in stage_names`（codegen workflow 在会话内 redeploy；full_test/generate_ascendc_se 无 codegen 且确实不部署）。
3. **`tests/ut/orchestration/test_precision_debug_routing.py` 整文件重写**——L4 §F 列「迁移或删」，实际重写：删 verify 路由分流用例 + generate_ascendc 表断言（verify 删除后这些路由不存在），保留 precision_debug 自身路由不变式（exhausted→halt、passed 线性后继）+ registry 注册 + stage 名单，新增 `test_no_verify_in_table`/`test_no_deploy_verify_in_stage_names`。

### 6.3 测试 churn 清单

**删除**（4 文件）：`test_verify_golden_contract.py`、`test_verify_precision_feedback.py`、`test_verify_testcase_source.py`、`tests/st/test_loopback_e2e.py`（见 §6.2 偏差 1）。

**改写**：`test_loopback.py`（transition 表断言改 precision_debug 拓扑）、`test_precision_debug_routing.py`（见 §6.2 偏差 3）、`test_test_design_workflow.py`（root children 序列）、`test_stages.py`（删 TestVerifyStage/TestVerifyStageStubbed）、`test_precision_debug_stage.py`（C guard）、`test_stage_failure_status.py`（verify hook 迁移，verify_iterations 删）、`test_state_machine_dispatcher.py`（D3 报告源）、`test_golden_input_role.py`（golden→precision_debug context）、`test_adapters.py`/`test_application.py`/`test_domain.py`（docstring/DeployStage 引用）、`tests/st/test_self_evolution_stages.py`（TestDeployStageContracts 删，helper 测试迁 TestDeployerHelpers；stage 名单 transition）、`tests/st/test_test_design_e2e.py`（TestVerifyConsumesCases 删）、`tests/st/test_npu.py`（deployed_add fixture 改直调 Deployer.deploy；删冗余 PrecisionGate 用例）、`tests/README.md`。

**新增 A–E UT**（按 §3 矩阵）：`test_deployer_persists_full_subprocess_output`（A）；codegen 4 件（B）；`test_precision_debug_runs_without_precision_result`（C）；perf/dispatcher 3 件（D）；workflow 图/transition/registry/字段 6 件（E，含吸收 D5 的 `test_state_has_no_precision_result`）。

### 6.4 回归结果

- **UT 全量**：1670 passed（tests/ut，16.6s）。
- **非 heavy ST**：106 passed, 7 deselected（tests/st `-m "not heavy_llm"`，270.5s；含 @npu 真核 test_npu 8 + @llm 探活 6）。
- **heavy_llm e2e（§3.11）**：跑 1 件（用户决策 2026-07-10）—— `test_smoke.py::TestCodegenStageEndToEnd::test_full_pipeline` **passed**（2099.9s / ~35min）。**注**：该用例 dispatch 单 codegen stage（`max_iterations=1`），断言的是 harness 机制（workspace 落盘 / events.jsonl / state_snapshot.json / `current_stage==codegen`），**非**算子编译成功（用例注释明示 exit code 可 0 可非 0）。实测 codegen agent 跑了 267 turn in-session redeploy/build 自修闭环、未达 smoke_pass → transition 干净产出 `deploy_failed` + halt（P57 B4 机制端到端验证：build 归 codegen 会话内、读完整 stderr[经 A 的 `<run>/subprocess/*.log`]、耗尽即 deploy_failed 止损、无跨 stage 错误传递、无静默吞）。LLM 未在预算内编译出 add 属已知质量特征（用例 docstring「routinely exceeds turn budget」），非 P57 机制缺陷。其余 6 件 design-chain TUI 自闭环用例（test_anchor_hwparams / test_design_docgen_tui / test_design_tui×3 / test_testdesign_tui）与 P57 正交（未改 design stage 接线），本次未跑。

### 6.5 heavy_llm e2e（§3.11）执行情况

- **已跑**（用户 PR 前决策 2026-07-10）：`test_smoke.py::TestCodegenStageEndToEnd::test_full_pipeline` — passed（见 §6.4）。
- **未跑**（与 P57 正交，留待后续单独覆盖）：`test_anchor_hwparams_selfclosure` / `test_design_docgen_tui_selfclosure` / `test_design_tui_selfclosure`(×3) / `test_testdesign_tui_selfclosure`——均 design-chain TUI 自闭环，P57 未触及 design stage 接线。

### 6.6 与 L3 §12 决策的偏差

无。Option II 全局一致（全 5 workflow、P58 吸收）按 L3 冻结版执行；超出 L4 §F 原始清单的仅 §6.2 三处，均为实施期取证后的必要收口（删死文件 / 修恒真触发 / 重写失效用例），非决策变更。
