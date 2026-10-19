# step-82: cann-bench 适配收敛到 adapter 边界 — 分析（L1 + L3）

> L4 实施方案见 `82-cannbench-adapter-convergence-impl.md` + plan `/root/.claude/plans/smooth-cuddling-aurora.md`。

## L1 问题记录（客观事实）

### 事实 1：CannbenchEvalStage 全 0 分，根因是 PYTHONPATH namespace 遮蔽
- batch `20260728_214817` scatter_pa_kv_cache：`CannbenchEvalStage` overall=0.00，20/20 case `compile_runtime_error`（report `scatterpakvcache_eval_20260729_002631.json`）。
- 每 case error_msg 相同：`ImportError: cannot import name 'cann_bench_warmup' from 'cann_bench_utils' (unknown location)`，发生在 `perf_eval.py:237 _boost_freq_and_clear_cache`。
- 机制：cann-bench 是 src-layout（`src/cann_bench_utils/cann_bench_utils/__init__.py`，外层无 `__init__.py`）。`CannbenchEvalStage` PYTHONPATH 只放 `src/`（`cannbench_eval.py:246,254`）→ Python 把 `src/cann_bench_utils/`（外层）当 namespace package（报错 "(unknown location)"）→ 取不到内层真实包的 `cann_bench_warmup`。
- 凭据：主 run.log `output/20260728-134831-ccda3b/20260728-134831-1108f1/run.log:5270`（exited 20）；report JSON 每 case error_msg；`src/cann_bench_utils/` 外层无 `__init__.py`（实测）。

### 事实 2：cann_bench_utils 的 `_C` 编译扩展从未构建（第二层）
- cann_bench_utils 是 cann-bench 仓独立可编译组件（`src/cann_bench_utils/`，有 build.sh/setup.py/CMakeLists），提供 `cann_bench_warmup`/`cann_bench_cache_clean`（反作弊 warmup/cache_clean），kernel_eval 的硬依赖（`perf_eval.py:237,255`）。
- `resources/repository-profiles/cann-bench.yaml` 的 build_variants 只声明算子 build（ascendc/install_opp/install_whl/smoke，4 stage，`match_prefix: examples/aclnn_launch_example/csrc/ops`），**未声明 cann_bench_utils**。devkit 对 cann_bench_utils 零感知（grep src/resources 无返回）。
- 今天 cann_bench_utils 靠**外部 batch shell** `run_evaluation.sh::ensure_cann_bench_utils()` 预装，devkit 流程不跑它。
- 当前 ImportError 停在第一层（namespace 遮蔽），把第二层挡在后面；修了第一层会暴露 `No module named cann_bench_utils._C`。

### 事实 3：cann-bench 适配散落在 stage/domain/adapter 三层，环境装配各处自行拼装且漂移
- `CannbenchEvalStage`（stage）自己 subprocess 调 `kernel_eval.cli` + 自己拼 PYTHONPATH（`cannbench_eval.py:225-277`），绕过 adapter 边界。
- `CannbenchBackend.run()`（adapter，`adapters/evaluation/cannbench.py`）走 NPURunner（精度预检，另一职责），不调 kernel_eval。
- precision_debug harness 用 inline `sys.path` hook（`CannbenchComparer.harness_setup_lines`，`precision_comparer.py:106-131`，`golden_source_path` 启发式推 src/）。
- 重复/漂移：`_cann_lib_paths()` 逐字节重复（`runner.py:461-477` vs `cannbench_eval.py:495-510`）；`ASCEND_CUSTOM_OPP_PATH`、LD 装配重复；cann-bench `src/` 可达性两种推导（`golden_source_path.rsplit('tasks/')` vs `repo_root/src`）。
- `cannbench_adapt.py` 自述 per-repo 适配器，文档明写"第二个 per-repo adapter 出现即提取 `adapters/per-repo/`"——`CannbenchScorer` 是第二个。

## L3 方案分析（四把尺子决策，已拍板）

### 决策 1：cann_bench_utils `_C` 缺失如何处理 → **C（profile eval_prepare + 预检兜底）**
- A（纳入 profile eval_prepare）：cann_bench_utils 是 cann-bench 仓内代码，profile 是仓 build 链权威声明 → 自闭环。但需扩 profile 加 `eval_prepare` 段（非 match_prefix variant，避免语义滥用）。
- B（预检+诚实报，不 build）：cann_bench_utils 是固定评测工具组件（类比 CANN toolkit 环境依赖），devkit 只预检可达性、缺了诚实报。符合 `external-infra` 边界。
- **选 C**：profile `eval_prepare` 主修复（devkit 经通用 profile 机制 build+install cann_bench_utils）+ 可达性预检兜底（build 后仍不可达则 infra error 诚实报，不 overall=0 掩盖）。兼顾自闭环与可诊断。

### 决策 2：cannbench_adapt 是否一并迁移 → **A（一并迁移，分步实施）**
- B（仅收敛 scorer+env）：留"cann-bench 适配半 stage 半 adapter"新隐患，违 adapt 自述契约。
- **选 A**：第 1 步建 cann-bench adapter 边界 + scorer + env + 预检 + 止血（治当前 bug，独立可测、可单独合入）；第 2 步紧随迁 cannbench_adapt 到同边界（收口，单独 PR 降回归风险）。

### 关键设计约束（四把尺子导出）
- `CannbenchScorer` **不入** `EvaluationBackend` Protocol（返回 `EvalResult` 非 `TestReport`；Protocol v3 frozen，不为单点需求破例——尺 1 可维护）。
- `CannbenchScorer` 与 `CannbenchBackend.run()`（NPURunner 精度预检）**不合并**（两职责，尺 4 架构合理）；只共享环境装配底座。
- `CannbenchScorer` **无** `available()` 守卫（stage 私有依赖，不经 select_backend，调度由 workflow 图保证）。
- 环境装配 `_build_cannbench_env` 共享底层（src-layout 扫描根治 namespace 遮蔽 + `_cann_lib_paths` 去重），但 **runner（NPURunner）路径不强行统一 env**（它不在 bug 路径、env 需求不同；尺 1/2 最小改动只消重复）。
- 可达性预检忠实复用 env（预检环境 = 真实 kernel_eval 环境，§1.11）。

## 状态
- 进行中（第 1 步）。
