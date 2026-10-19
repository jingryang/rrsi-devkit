# 01 — 问题记录（L1）

> 本工作：`docs/plan/codegen-smoke-real-execution/`。本文件只记**客观事实**（哪里坏、
> 凭什么这么说），不提方案、不排顺序、不写决策（那些归 L3/L4）。

## P1 — codegen smoke 只做符号解析、从不真实调用算子

- `src/ascendc_devkit/orchestration/stages/deploy.py` 的 smoke（经 `redeploy` CLI 暴露，
  由 codegen agent 在会话内 in-session 调用）对 `callable_target.kind=="torch_op"` 只做：
  `getattr(torch.ops, ns)` → `getattr(ns, op)` → `assert fn is not None`。
  **全程只查符号能不能解析到，从不拿真实 tensor 调它。** pybind 分支同理（`import_module`
  + `getattr` + `callable` 断言，不调用）。
- 这是 `step-31`（P57，2026-07-09 冻结）的有意设计：`docs/plan/self-evolution/
  33-capability-sink-redundant-stages-analysis.md` §5.1 原文「全程只查符号能不能解析到，
  从不拿真实 tensor 调它……不喂真实输入，不可能触发算子逻辑错或精度错」——smoke 被定义为
  「codegen 接线门」，与 run-cases（precision_debug 的功能+精度门）正交分工。

## P2 — `DeployResult.smoke_passed` 字段语义与 smoke 实现不一致

- `src/ascendc_devkit/domain/verification.py:65`（改动前）字段语义原文：
  `smoke_passed: 冒烟测试是否通过（实际调用一次算子验证可调用）`。
- 但 P1 的 smoke 实现只验「符号注册成功」，**从不实际调用算子**。字段语义承诺「实际调用
  验证可调用」，实现只做到「注册可解析」——契约不一致。
- 下游 `cannbench_eval.py:85`（`if deploy is None or not deploy.smoke_passed:`）、
  `cannbench_adapt.py:133` 把 `smoke_passed` 当「算子可调用」的前置门。

## P3 — codegen↔precision_debug 断裂点（同事反馈现象）

- 同事反馈：codegen 的 smoke 通过了，但到 precision_debug 实际调用算子时不能正常调用。
- 证据链：
  - codegen smoke（P1）只 getattr → `smoke_passed=True` 只代表注册成功。
  - precision_debug 的 run-cases 经 `NPURunner` 真实调用算子：
    `src/ascendc_devkit/adapters/npu/_harness_template.py` 的 harness 脚本里
    `kernel_fn(*_npu_inputs, **_attrs)`（真实上 NPU 执行 kernel，触发 InferShape/Tiling/
    kernel runtime/op-plugin converter 全链路）。
  - 两端验证强度不同：smoke=符号解析级，run-cases=真实执行级。注册成功 ≠ 可执行。
  - 故执行类缺陷（meta/tiling/kernel runtime/converter）被 smoke 放行（绿灯），原封不动
    推到 precision_debug 首轮 run-cases 才暴露——这就是「断裂点」。

## P4 — deploy「包的方式」一致，不一致在「验证强度」

- 澄清同事原判断「deploy 方式不一致」：codegen 的 redeploy 与 precision_debug 的 redeploy
  **走同一个 `Deployer.deploy()`**（`deploy.py:60` 注释 + `:69-142`），install 到**同一个
  per-op 目录**（`_per_op_path`），用**同一个 callable_target**（都来自 codegen_manifest）。
  install/deploy 包的方式一致。
- 真正不一致 = 验证强度（P3）：smoke 只 getattr，run-cases 真实调用。

## P5（边界，本工作不覆盖）— A5 codegen 伪造 smoke_passed

- A5（Regbase）路径 `codegen.py:_transition_regbase_s5`（约 1658-1666 行）：s5-compile agent
  只编译、不调 redeploy/smoke，transition 在 `deploy_result is None` 时硬编码
  `DeployResult(smoke_passed=True, run_package="codegen-s5")`——零验证伪造绿灯。
- 这是独立问题（A5 codegen 侧），本工作**不覆盖**（用户定调「只管 A3」）。本工作的 smoke
  真实执行改动落 deploy 边界，A5 codegen 不受益（仍伪造），但 A5 precision_debug 入口的
  redeploy 会连带得到真实 smoke（正向副作用，不额外处理）。

## P6 — smoke 子进程未设 NPU 卡 + `_run_smoke` 零 UT 覆盖（连带硬伤）

- 改动前 `_run_smoke`（`deploy.py:438-479`）env 不设 `ASCEND_NPU_ID`，subprocess 用
  `["python","-c",script]`（非 `sys.executable`）；只 getattr 不需卡故未暴露。
- `_run_smoke` 在全仓 `tests/` 零 UT 覆盖（returncode 分支/timeout/log 落盘全无测）；仅
  `tests/st/test_npu.py::TestNPURunnerRealExecution` 真机覆盖（常因 NPU/仓门控 skip）。
