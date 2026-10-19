# e2e-self-evolve 跑 moe_re_routing — 实施（L4）：harness 6 gap + 软门

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md`，事实见 `01-problems.md`。

## 改动 1 — precision_debug 软门（P2）
- `orchestration/workflow.py` SelfEvolveOpWorkflow.TRANSITION_TABLE：
  `precision_debug.exhausted` 由 `(__halt__, escalation)` → `(cannbench_adapt, validation)`。
- `orchestration/stages/precision_debug.py` 模块 docstring + `resolve_condition` docstring 同步。
- 仅 self_evolve_op；generate_ascendc/_dev 不动（无 ②）。

## 改动 2 — harness 6 gap（P3a–f），`adapters/npu/runner.py` `_build_test_harness`
- **P3a/b**：新增 `_to_np(x)` / `_to_np_list(out)`（单 Tensor 或 tuple/list → numpy 列表）；
  `_golden_wrap` 改用 `_to_np_list`；case 循环 `_kernel_nps = _to_np_list(kernel_out)`，
  与 `_golden_nps` 逐对 zip 比 max_diff，arity 不等判 999。
- **P3d**：golden 加载后 `_get_input = getattr(golden_mod, 'get_input', None)`；
  case 循环若存在则 `_get_input(*torch_inputs, **attrs)` 修结构约束，过滤 None 槽（可选输入缺省）。
- **P3e**：`gen_input` 增 `value_range` 参，优先每输入值域，否则回落 GEN_LOW/HIGH；
  serial_cases 透传每输入 `value_range`。
- **P3f**：`_NP` 补 `int32`/`int64`/`bool`。

## 改动 3 — cases 解析（P3c/e），`domain/cann_bench_cases_loader.py`
- **P3c**：`parse_cann_bench_csv` 输入循环 `if shape is None: continue`（丢弃 null 可选输入）。
- **P3e**：新增 `_per_input_value_range(value_range, i)`，每输入挂自己的 `[low,high]`；
  `_value_range_to_gen` 降级为 GEN_LOW/HIGH 回落（语义注释更新）。

## 验证
- TDD：先加测试再实现。新增 6 个 UT（cases_loader 2：null 丢弃 + 每输入值域；
  harness 4：多输出比对 / get_input / golden tuple→numpy / int dtype）。
- 契约同步：`test_precision_debug_routing.py` 断言改为软门目标；`test_precision_debug_stage.py` 注释更正。
- 全量 UT：1722 passed；4 个失败（P4）经 `git stash` 验证为 pre-existing，与本轮无关。
- 生成 harness 喂 `py_compile` 通过；6 个 gap 标记（_to_np_list / get_input / int64 / value_range / zip 比对）均在。
- 单输出算子向后兼容：exp/add/sqrt 走长度 1 的 list 路径，老 harness UT 全绿。

## 后续（不在本轮）
- 运行 E2E：`bash scripts/e2e_self_evolve.sh`（heavy_llm，跑前需用户确认）。
- P4：4 个 chip-UT 失败的修法（mock 探测 vs 对齐 A5）单开 follow-up。
