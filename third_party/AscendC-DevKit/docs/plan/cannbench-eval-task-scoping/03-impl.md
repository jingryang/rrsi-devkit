# L4 实施方案 — cann-bench 评测任务级 scoping

改动文件：`src/ascendc_devkit/adapters/evaluation/cannbench_scorer.py` +
`tests/ut/adapters/evaluation/test_cannbench_scorer.py`。TDD：红测先行。

## 1. `_resolve_task_dir`（scorer）

命中 `(level / op_name / "cases.yaml")` 时返回 `str(level / op_name)`（任务目录）
而非 `str(root)`（评测集根）。候选集遍历（`bench_lab/kernel_bench` 优先、`tasks/`
回退）与未命中回退 `tasks/` 根的行为不变。docstring 记根因与 filter_prefix 语义。

## 2. `_parse_report` 多 operator 守卫（scorer）

`summary` 解析后、`if operators:` 分支前插入：`len(operators) > 1` →
`Logger.error` + `return EvalResult(overall_score=0.0, report_json=...), <infra
reason 含全部 rel_path>`。reason 走既有 string 通路（stage 包装为 infra
ErrorFeedback；scorer 保持 L3-type-free）。

**整改补充（2026-09-11 review N1，坐实即修）**：守卫之前再加**解析点单点结构
校验**——`operators` 非 list 或元素非 dict → infra reason（含报告路径），不进入
守卫/per-dimension 读取。此前畸形报告会在新守卫（`op.get`）与既有
`first.get` 两条路径以 AttributeError 炸穿 stage（两形态复现坐实）；单点校验把
同暴露面一起收（§1.15）。UT +3 参数化
（`test_parse_report_infra_when_operators_malformed`，先红后绿）。

## 3. `run_eval` 诊断日志（scorer）

`task_dir` 解析后追加一条 INFO：`eval <op> task_dir=... (task-level scoping —
filter_prefix limits cases to the target task)`。

## 4. UT（test_cannbench_scorer.py）

- 更新 `TestTaskDirDiscovery.test_run_eval_injects_task_dir_flag`：期望
  `--task-dir` 值为任务目录（`.../level2/rms_norm`）；
- 新增 `_resolve_task_dir` 四用例：bench_lab 命中 / tasks 命中 / bench_lab 优先 /
  未命中回退根（现状守护）；
- 新增 `TestDiscoveryAndLossSplit.test_parse_report_infra_when_multiple_operators`：
  2 operator 报告 → err 非空（含两个 rel_path）+ overall 0。

stage 层不为新 reason 加变体用例：`transition` 对任意非 None reason 统一包 infra
ErrorFeedback（`cannbench_eval.py:117-123`，无内容分支），机制已由
`test_transition_injects_last_error_on_discovery_broken` 守护，按 reason 变体重复。

## 5. ST（test_cannbench_discovery_st.py 追加 TestTaskDirScopingContract）

跨仓契约守护（DevKit 改不动 cann-bench，其行为漂移只能靠真实代码测出）：
- `test_devkit_resolves_task_dir_and_cannbench_decomposes_it`：synthetic 孪生任务
  树上断言契约两半——(a) DevKit `_resolve_task_dir` 返回任务目录；(b) 真实
  cann-bench `resolve_task_dir` 分解为 bench_root=评测集根 + filter_prefix=任务
  rel_path。复用该文件既有的 CANN_BENCH_SRC 发现 + §3.7 skip 机制（§1.15 不复制
  helper）；秒级、无 NPU/LLM。
- `test_twin_names_are_name_indistinguishable`：前提事实守护（孪生算子名 lower
  相等——名字过滤无法区分，路径是唯一判据）；cann-bench 若改过滤语义则连同
  scoping 依据重评。
- **mutation 验证**：临时还原 `_resolve_task_dir` 旧行为（返回根）→ ST 红；
  还原后 ST 6 + scorer UT 42 全绿。

## 验证

1. UT：`PYTHONPATH=src pytest tests/ut/adapters/evaluation/test_cannbench_scorer.py
   tests/ut/orchestration/test_cannbench_eval.py`（红 5 → 绿 42）；
   全量 `tests/ut/adapters/evaluation/ + tests/ut/orchestration/` **2055 passed** 无回归。
2. 端到端冒烟（2026-09-11 已跑，真实 worktree
   `/home/x00584171/code/cann-bench-batch/20260908_210659/adaptive_avg_pool_3d`，
   空闲卡 7）：`python -m kernel_eval.cli eval --source-dir <examples/aclnn_launch_example>
   --operator AdaptiveAvgPool3d --task-dir <worktree>/tasks/level3/adaptive_avg_pool_3d
   --case-id 3 --device-id 0 --skip-install --eval-seed 0 --output /tmp/eval_smoke_out`。
   **结果**：`筛选路径: level3/adaptive_avg_pool_3d` 激活，`算子数: 1, 用例数: 1`；
   报告 `operators = ['level3/adaptive_avg_pool_3d']`（对照本批旧报告 2 operators）；
   case_3 ✅ MERE=0/MARE=0（干净进程，与 L1 P2 复现结论一致——间歇性缺陷未触发）；
   综合得分 50.72（单任务量纲）。报告存 `/tmp/eval_smoke_out/`。
3. 回归语义：该算子重评期望分 ≈ 49.5~50.7（仅目标任务、随 perf 波动），pass_rate =
   18/20；与 precision_report 20/20 的差异属已定位的间歇性 kernel 缺陷（L1 P2，
   另行产权）。
