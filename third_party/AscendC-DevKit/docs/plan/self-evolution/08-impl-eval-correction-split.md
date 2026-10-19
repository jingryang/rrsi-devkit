# L4 实施方案 — 分离算子内层修正与 cann-bench 评测

> **性质**：L4 实施方案。改哪个函数、什么顺序、怎么验证。动手前写。
> **上游**：`07-eval-vs-correction-analysis.md`（L3，D1–D5 已拍板）；覆盖 `06-problems.md` P5、P6。
> **P7 分流（2026-12-09）**：本文的 **Step E 已被 `10-generate-ascendc-deploy-impl.md` 推翻**（deploy 退纯确定性、失败全回 codegen，不接 LLM 自救）；本文的 **Step P 的 callable_target 来源修正**为从 `codegen_manifest` 读（原文写"deploy 产出"作废）。deploy 通用化 + generate_ascendc 真 kernel 通路见 `10`。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不写 file:line）。TDD：先改/加测试再改实现（CLAUDE.md 3.1）。

---

## 0. 改动总览（按依赖顺序）

| 步 | 改动 | 归属决策 | 依赖 |
|---|---|---|---|
| A | cannbench_eval 回归"只出分"：删 `resolve_condition` 的 eval_failed + score==0 的 last_error 注入 | 无条件 | — |
| P | 修 P6：`NPURunner` 精度改为导入 deploy 产物、在 NPU 跑真 kernel 比 golden；删静默桩降级 | D5 | — |
| C | self_evolve_op 插入 verify stage（**deploy 之后**）+ 转移表加 verify 回路（golden 走现有纯透传通道，无新增） | D1 + D2 | P |
| D | 删 self_evolve_op 转移表的 `cannbench_eval: eval_failed → codegen` | 无条件 | A |
| E | DeployStage 升级为"确定性链 + 失败 LLM 自救"，核心代码只读；`deploy_failed` **按原因分流**（脚手架自救 / 核心回 codegen） | D3 | — |

A/D/E 相互独立；C 依赖 P（精度须先能跑真 kernel，verify 回路才有效）。建议顺序 A→P→C→D→E（A/C/D 同属 workflow.py + cannbench_eval.py，可合并提交）。

> **步 B 已删除**：D2 定稿为 golden 纯 State 透传（用户 `--golden` → dispatcher → State → verify 直接读），无需 ContextStage 解析、无需 profile 字段。原步 B（golden 解析机制）不存在，其唯一实质——"self_evolve_op 能消费 golden"——由步 C 插入 verify 后自动获得。详见 07 v0.4。

---

## 步 A：cannbench_eval 回归"只出一次分"

**文件**：`stages/cannbench_eval.py`

**改动**：
1. **删除** `CannbenchEvalStage.resolve_condition()` 方法整体——cann-bench 不返回非 default 条件，评测器职责单一。
2. **删除** `transition()` 中 `overall_score == 0` 分支的 `last_error=ErrorFeedback(...)` 注入（含 `deploy 缺失`/`repo_root 解析失败`/`score==0` 三处 last_error）。这些分支保留 `EvalResult(overall_score=0.0)` 产出，但**不写 last_error**（不触发 codegen loopback）。
3. **保留** `EvalResult` 的 compile_score/function_score/performance_score 三维字段（D4：保留区分能力）。
4. **删除** 未再使用的 `from ...state import ErrorFeedback` import。

**验证**：
- UT：`cannbench_eval` 的 transition 在 score==0 时产出 `eval_result.overall_score==0` 且 `state.last_error is None`；`resolve_condition` 属性不再存在（stage 用基类默认返回 default）。
- 断言 EvalResult 三维字段仍在。

## 步 P：修 P6 — NPURunner 精度跑真 kernel（D5）

**文件**：`adapters/npu/runner.py`（`_build_test_harness`、`execute`、`_stub_result`）

**核心约束**：verify 精度必须**导入 deploy 产物、在 NPU 上调用算子注册符号、与 golden 比对**，而非当前的"CPU 跑 golden 自比、`max_diff` 恒 0"桩。复用 deploy 注册的可调用符号，不在 runner 里重造部署（CLAUDE.md 2.7）。

> **修正（2026-12-09，承 `10`）**：调用符号**不写死 `torch.ops.cann_bench`**，改从 `state.codegen_manifest.callable_target`（`kind`/`symbol`）读——符号由 codegen（其作者）在 manifest 声明（P7/D7）。deploy 只提供路径+env，不产 callable_target。下方"取 `torch.ops.cann_bench.<op>`"应按此修正为"取 `callable_target.symbol`"。

**改动**：
1. **harness 真跑 kernel**：`_build_test_harness` 生成的脚本，除加载 golden 外，须：
   - 设置 deploy 产物的 `PYTHONPATH`（per-op python dir）、`ASCEND_CUSTOM_OPP_PATH`、`LD_LIBRARY_PATH`（与 DeployStage smoke 一致，复用其路径约定）。
   - `import torch; import cann_bench`，取 `torch.ops.cann_bench.<op_name>`，在 NPU 上以相同输入调用 kernel。
   - `diff = |kernel_output_cpu - golden_out|`，写回 `max_diff`（真实值，非恒 0）。
   - 删除 `results[shape] = 0.0` 的 golden-自比占位与 `# TODO` 注释。
2. **deploy 产物路径入参**：`execute()` / harness 需要 deploy 产出的 per-op python dir + opp dir。这些在 `State.deploy_result`（`python_path`/`install_path`/`ld_library_path_add`）里——verify.actions() 组 evidence 时透传给 PrecisionGate → NPURunner。
   - verify.py 的 evidence 增加 deploy 产物路径（从 `state.deploy_result` 读）。这是 verify 在 deploy **之后**的必然结果（deploy_result 已就位）。
3. **删静默桩降级**：`_stub_result` 仅在显式 `--enable-stubbed` 时可用；默认 torch_npu/产物缺失 → 抛 `EnvironmentNotAvailableError` 诚实报错（CLAUDE.md 3.7/3.10）。

**验证**：
- ST（@pytest.mark.npu）：对一个已 deploy 的算子，正确 kernel → `max_diff` 在容差内 `passed=True`；故意改错 kernel → `max_diff` 超容差 `passed=False`。**这是 P6 的核心守护**：证明精度不再恒真。
- UT：harness 生成脚本含 `torch.ops.cann_bench` 调用 + deploy 产物环境变量（字符串断言）。
- UT：无 `--enable-stubbed` 且 torch_npu 缺失 → `execute()` 抛 `EnvironmentNotAvailableError`（不返回桩）。

## 步 C：self_evolve_op 插入 verify（D1 + D2，verify 位于 deploy 之后）

**文件**：`workflow.py`

**改动**：
1. `_SELF_EVOLVE_STAGE_NAMES`：在 `deploy` 与 `cannbench_adapt` 之间插入 `"verify"`（verify 在 deploy **之后**）。
2. `SelfEvolveOpWorkflow.root` 的 `after_names`：`["codegen_init", "codegen", "deploy", "verify", "cannbench_adapt", "cannbench_eval", "finalize"]`。
3. `SelfEvolveOpWorkflow.TRANSITION_TABLE` 增加 verify 条目（复用 generate_ascendc 的语义）：
   ```
   "verify": {
       "build_failed":     ("codegen", "corrective"),
       "precision_failed": ("codegen", "corrective"),
       "exhausted":        ("__halt__", "escalation"),
   },
   ```
4. 更新 `SelfEvolveOpWorkflow` 的 docstring/root 注释，反映 verify 插入于 deploy 之后。

**golden 来源（D2 定稿 — 纯透传，无新增代码）**：verify 的 golden 从 `State.golden_path` 读取（**必选**）。该字段是 State 的种子字段，由用户 `--golden` 经 dispatcher 填入，一路透传——**generate_ascendc 已在用此通道**。self_evolve_op 插入 verify 后**自动复用同一通道**，零新增：
- 用户传 `--golden` → `dispatcher` 填 `State.golden_path` → `verify.actions()` 直接读 `state.golden_path` → `PrecisionGate`。
- 插入 verify 后，dispatcher 的 `_preflight_input_topology`（"`--golden` 需 verify stage"规则）**自动放行** self_evolve_op 的 `--golden`——该规则本身不改。
- **不改 ContextStage、不改 profile、不改 verify.py**。用户未传 `--golden` → verify 入参契约校验诚实报错（golden 必选，CLAUDE.md 3.7），不降级。
- **不代为供给/执行 golden**：cann-bench 的 `tasks/level<N>/<op_name>/golden.py` 是评测框架资产，DevKit 只透传用户显式给的 golden，绝不解析/伪造/执行（避免污染 ② 打分）。

**验证**：
- UT：self_evolve_op 的 flat_stages 序列含 verify，位置在 **deploy 后、cannbench_adapt 前**。
- UT：转移表含 verify 三条目。
- UT：`test_real_workflows_have_correct_flags` 等既有断言更新。

## 步 D：删 cannbench_eval 回灌路由（无条件）

**文件**：`workflow.py`

**改动**：删除 `SelfEvolveOpWorkflow.TRANSITION_TABLE` 的 `"cannbench_eval": {"eval_failed": ("codegen", "corrective")}` 整个条目。

**验证**：UT 断言转移表无 cannbench_eval 键。

## 步 E：DeployStage LLM 自救 + 按原因分流（D3）—— ⚠️ 已被 `10` 推翻

> **状态（2026-12-09）**：本步整体作废。deploy 不接 LLM 自救、不做归因分流；改为**纯确定性 stage，任一步失败 → `last_error(step+stderr)` → 回 codegen**（唯一 LLM 作者点）。deploy 通用化（按 profile role stages 跑）+ 失败回 codegen 见 `10-generate-ascendc-deploy-impl.md` 步 G4/G5。下方原文保留仅供追溯。

**文件**：`stages/deploy.py`、新增 agent manifest `.claude/agents/deploy-fix.md`

**正当性（D3）**：deploy 在 pipeline 最前，失败又不修 → verify 跑不起来 → cann-bench 打分被**脚手架故障**污染，错怪算子降分。故 deploy 失败**必须** LLM 自救修脚手架，让 verify 能跑、让 loss 反映算子本身。核心代码只读是**归因正确性**的保证。

**改动**：
1. **`resolve_condition` 改为按原因分流**（不删、不一刀切回灌）：
   - 脚手架问题（LLM 自救后仍失败，或判定为非核心）→ 由 deploy 自身重试消化，不路由回 codegen。
   - **核心代码问题**（build.sh 因 op_host/op_kernel/op_api/op_plugin 编译错失败，LLM 禁改核心 → 修不了）→ 返回 `"core_build_failed"`（或复用 `build_failed` 语义）→ 转移表路由回 codegen（等价真实算子缺陷）。
2. deploy 链失败时（build/opp/whl/smoke 任一失败），不再直接返回 `DeployResult(smoke_passed=False)` 终止，而是**接入 LLM agent 自救**：
   - `actions()`：检测到需修复（上一 iteration deploy_result 失败）时，返回 deploy-fix agent Action，注入失败上下文（哪一步失败 + stderr）。
   - **硬约束**：agent 可写范围限**非核心脚手架**（build.sh、CMakeLists.txt、`__init__.py` wrapper、env/安装脚本）；**核心代码只读**。
   - `default_max_iterations` 从 1 提到允许自救重试（如 2–3）。
3. **失败原因分类**：deploy-fix agent 判定失败根因是脚手架还是核心代码（依据 stderr 指向的文件路径 / 编译错所在 section），据此决定"自救修复"还是"上报核心缺陷回 codegen"。
4. deploy 的确定性链逻辑（`_run_deploy_chain` 等）保留，作为首次尝试；失败才触发 LLM。
5. 转移表：`SelfEvolveOpWorkflow.TRANSITION_TABLE` 增加 `deploy: {"core_build_failed": ("codegen", "corrective")}`（核心缺陷回灌）；脚手架失败不进转移表（deploy 内部消化）。

**核心代码只读的落地手段**（组合）：
- agent manifest 声明 `tools` 白名单不含核心目录写权限；
- deploy transition 在 agent 完成后校验核心 section 文件的 mtime/hash 未变，若被改则拒绝并报错（可诊断信号，符合 CLAUDE.md 1.2 可诊断尺子）。

**验证**：
- UT：deploy 失败注入的 agent action 携带失败步骤 + stderr；核心代码路径不在可写范围。
- UT：核心代码编译错 → deploy 返回 `core_build_failed` → 转移表路由回 codegen；脚手架失败 → 不回灌、deploy 内部重试。
- ST（@pytest.mark.llm/heavy_llm）：deploy 遇 `__init__.py` wrapper 缺失（P1 场景）能自救修复，且核心代码未被改动。

---

## 测试影响面（TDD 先行）

- `tests/st/test_self_evolution_stages.py`：deploy/cannbench_eval 的 resolve_condition 相关断言删除/改写；新增 verify 在 SE pipeline（deploy 之后）的断言。
- `tests/ut/orchestration/test_workflow.py`：self_evolve_op stage 序列（deploy→verify→cannbench_adapt）+ 转移表断言更新。
- `tests/ut/application/test_application.py`：`test_real_workflows_have_correct_flags`（requires_npu 不变）；`--golden` 拓扑预检对 self_evolve_op（现有 verify）放行的断言。
- verify 契约 golden 仍 required 的回归断言（防误删）；self_evolve_op 未传 `--golden` 时 verify 诚实报错的断言。
- **P6 守护（步 P）**：NPURunner 真跑 kernel 的 ST（正确 kernel `passed`、错误 kernel `max_diff` 超容差 `not passed`）；桩降级仅 `--enable-stubbed` 生效的 UT。
- deploy LLM 自救 + 按原因分流的新 UT + ST（步 E：核心编译错 → `core_build_failed` 回 codegen；脚手架失败 → 内部重试）。

全量：UT + ST 必须全绿（CLAUDE.md 3.2），npu/llm/heavy_llm 标签不跳过。

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-01 | 初版：A–E 五步实施方案，承接 07 分析 D1–D4 拍板。步 B 标注共享 verify 行为变更风险。 |
| 2026-07-01 | **步 B 重写**（承接 07 v0.3）：golden 必选、两 workflow 对齐。verify.py 不改；改为 ContextStage 从 profile 约定解析 golden 进 State + profile 新增 golden 位置声明。删除"golden 可选降级"及其风险注记。步 C golden 注记同步。 |
| 2026-07-01 | **步 B 删除**（承接 07 v0.4）：D2 定稿为 golden 纯 State 透传（用户 `--golden` → dispatcher → State → verify 直接读）。核实此通道 generate_ascendc 已在用，self_evolve_op 插入 verify 后自动复用，零新增代码。删除 ContextStage 解析 + profile 字段方案（过度设计 + 触碰 golden 产权边界）。步 B 并入步 C；总览表与依赖关系更新（C 不再依赖 B）。 |
| 2026-07-01 | **顺序修正 + 新增步 P + 步 E 重写**（承接 07 v0.5）：① 步 C 的 verify 从"deploy 之前"改到 **deploy 之后**（`deploy→verify`），精度复用 deploy 产物。② 新增 **步 P**（修 P6）：NPURunner 精度改为导入 deploy 产物、跑真 kernel 比 golden，删静默桩降级；C 依赖 P。③ 步 E 重写：删"一刀切删 `deploy_failed`"，改为**按原因分流**——脚手架 LLM 自救、核心编译错 `core_build_failed` 回 codegen。测试影响面 + 总览表同步。 |
| 2026-12-09 | **步 E 被 `10` 推翻 + 步 P callable_target 来源修正**（承接 09/10，P7）：① **步 E 作废**——deploy 退纯确定性、失败全回 codegen、不接 LLM 自救（deploy 通用化 + 失败回 codegen 见 `10` 步 G4/G5）。② **步 P 修正**——真 kernel 调用符号不写死 `torch.ops.cann_bench`，改从 `codegen_manifest.callable_target` 读（符号由 codegen 声明，见 `10` 步 G1/G7）。deploy 通用化到三条 pipeline + generate_ascendc 真 kernel 通路整体见 `09`（L3）/`10`（L4）。 |
