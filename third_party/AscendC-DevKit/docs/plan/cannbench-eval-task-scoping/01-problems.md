# L1 问题记录 — cann-bench 评测任务级 scoping

## P1：评测混入仅差大小写重名的孪生任务，overall 变跨任务求和

**现象（批 20260908-130718-b8ec7a / 20260908-130718-a62158，adaptive_avg_pool_3d）**：

- eval 报告（`subprocess/cannbench_eval_adaptive_avg_pool_3d.partial.json/adaptiveavgpool3d_eval_20260908_222753.json`）
  含 **2 个** operator 条目、40 用例：
  - `level2/task_0258_aten_adaptive_avg_pool3d`（算子名 `AdaptiveAvgPool3d`）：20 用例，得分 33.00；
  - `level3/adaptive_avg_pool_3d`（算子名 `AdaptiveAvgPool3D`，生成目标）：20 用例，得分 49.54。
- `overall_score = 82.54` = 33.00 + 49.54（报告生成器对全部入选 operator 求和）。
- run.log 单行摘要 `overall=82.54 compile=15.00 func=18.00 perf=0.00` 中分项取
  `operators[0]`（恰为 level2），与 overall 不同层级——"总分≠各项之和"的观感由此而来。
- pass_rate 75%（30/40）同样跨两任务混合。

**根因事实**：

- DevKit scorer `--task-dir` 传的是评测集**根**（`_resolve_task_dir` 返回 `tasks/`），
  未激活 kernel_eval 的 filter_prefix 通路；
- kernel_eval 的 `--operator` 过滤为 `c.operator.lower() == args.operator.lower()`
  （`cli.py:447-448`，大小写不敏感纯名字匹配）；
- 两个任务的算子名仅差末字母大小写（`AdaptiveAvgPool3d` vs `AdaptiveAvgPool3D`），
  lower 后同名 → 双双入选。

**危害不止分数混算**：孪生任务的 4D 输入用例触发生成 tiling 的 `rank must be 5`
硬检查（`op_host/adaptive_avg_pool_3d_tiling.cpp:61`）以 EZ1008 失败 5 例；其
NaN/±3e38/±65504 极值用例的执行历史污染同进程后续用例（见 P2）。

## P2：run_tests 全过而 eval 判挂——执行环境历史依赖的间歇性 kernel 错误

**现象**：`artifacts/debug/adaptive_avg_pool_3d/precision_report.md` 报 20/20 全过
（真 golden 比对，`golden_used=true`、`bottleneck=real_kernel_vs_golden`）；eval 对
level3 case_3（bf16）与 case_10（fp16）各判 1 个元素大误差（max_diff 0.37 / 0.875）。

**已排除的假设（逐项实证对齐）**：

- 输入种子公式 `(0 + SHA256(case_id)) % 2^31` 两侧一致（case_id 字符串逐字相同）；
- 输入生成代码（f64 rand → scale → cast）逐字对齐，离线复算两用例输入 **bit 级一致**；
- golden 同文件同 fp64_cpu 权威；comparator 同公式（golden 截断到输出 dtype +
  `|k−g|/(|g|+1e-7)` + mere/mare + 10×阈值）；`enable_accuracy_retry` 默认 False 未开启。

**实证结论**：干净进程 10 连跑 case_3 输出 bit 级完美且确定；模拟 eval 进程历史
（先跑 level2 的 ±65504/±3e38 极值与 NaN 全填充用例）后，case_3 出现同款 1 元素
错误（进程内复现一次，mare=0.188；同序列重试 3 个进程未再触发）——间歇性、依赖
执行历史/内存状态，指向 kernel 读到未初始化/残留 device 数据或竞态。

**边界**：与本缺陷的因果事实——污染源是孪生任务（P1）的 4D/NaN/极值用例执行
历史，该执行路径随 P1 的修复消失；kernel 本身的间歇性缺陷仍在（复现条件与证据
见上文）。处置归属与约束的裁定（不动 cann-bench、不注入极值/特殊值用例）记录在
L3 `02-analysis.md`「约束」段，此处不重复。
