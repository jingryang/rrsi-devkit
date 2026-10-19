# step-82: cann-bench 适配收敛到 adapter 边界 — 实施（L4）

> 详细方案见 plan `/root/.claude/plans/smooth-cuddling-aurora.md`；分析见 `82-cannbench-adapter-convergence-analysis.md`。

## 第 1 步：建边界 + scorer + env + 预检 + 止血（治当前 bug）

### 新建文件
- [ ] `src/ascendc_devkit/adapters/evaluation/cannbench_env.py` — 共享环境装配
  - `cann_lib_paths() -> list[str]`（从 cannbench_eval.py 搬，去 runner.py 重复）
  - `cannbench_src_layout_paths(repo_root) -> list[str]` — 扫描 src/ 下 src-layout 嵌套包外层（**根治 namespace 遮蔽**，含 `src/cann_bench_utils/`）+ `src/` 本身（flat 包如 kernel_eval）。顺序：嵌套外层在前、src/ 在后。
  - `resolve_cann_bench_pkg_root(source_dir, repo_root)` — 从 cannbench_eval.py 搬
  - `build_kernel_eval_env(repo_root, source_dir, per_op_python, per_op_opp, deploy_ld, usercustomize_dir) -> dict` — kernel_eval 子进程完整 env（autoload=0 + opp + ld + PYTHONPATH）
- [ ] `src/ascendc_devkit/adapters/evaluation/cannbench_scorer.py` — `CannbenchScorer`（搬迁 _run_eval→run_eval + helpers + 可达性预检）

### 改造文件
- [ ] `src/ascendc_devkit/orchestration/stages/cannbench_eval.py` — 退化为编排（smoke gate → scorer.run_eval → 写 state），删搬迁方法 + 内联 env
- [ ] `src/ascendc_devkit/adapters/npu/runner.py` — 删重复 `_cann_lib_paths`（461-477），改用 `cannbench_env.cann_lib_paths()`；env 其余保持（NPURunner 不在 bug 路径）
- [ ] `resources/repository-profiles/cann-bench.yaml` — 加顶层 `eval_prepare` 段（cann_bench_utils build+install）
- [ ] `resources/schemas/repository/profile.json` — 加 `eval_prepare` schema
- [ ] `src/ascendc_devkit/adapters/repository/profile_loader.py` — 解析 `eval_prepare`

### 测试（TDD）
- [ ] `tests/ut/adapters/evaluation/test_cannbench_env.py` — namespace 遮蔽根治（PYTHONPATH 含 `src/cann_bench_utils/`）、src-layout 扫描、预检通过/失败
- [ ] `tests/ut/adapters/evaluation/test_cannbench_scorer.py` — scorer 单测（mock kernel_eval subprocess + report 解析 + infra/LOSS 分流）
- [ ] 改 `tests/ut/orchestration/test_cannbench_eval.py` — `_run_eval` → `scorer.run_eval`，mock 路径改 scorer 模块，保留 autoload/card/PYTHONPATH/task-dir/infra-LOSS 不变式

## 第 2 步：迁 cannbench_adapt 到 adapter 边界（收口，单独 PR）
- [ ] 搬 `cannbench_adapt.py` wrapper-gen + m.def-rename 到 cann-bench adapter 边界
- [ ] 处理 Deployer 耦合（adapter→domain Deployer）
- [ ] `CannbenchAdaptStage` 退化 + 测试改造

## 验证
- [ ] `pytest tests/ut/orchestration/test_cannbench_eval.py tests/ut/adapters/evaluation/`（UT）
- [ ] `pytest tests/ut/test_layer_dependencies.py`（stage 不再直接 import cann_bench/kernel_eval）
- [ ] heavy_llm 真实链路 ST（重跑 scatter_pa_kv_cache eval）— 跑前向用户确认

## 进度
- step-82 analysis + impl 骨架建好。
- **第 1 步完成**（治当前 bug，已 commit `bcf55c31`）：
  - 新建 `cannbench_env.py`（共享 env 装配 + src-layout 扫描根治 namespace 遮蔽）
  - 新建 `cannbench_scorer.py`（kernel_eval 评分 + 可达性预检 + eval_prepare ensure）
  - `CannbenchEvalStage` 退化为编排（调 scorer，包装 reason→ErrorFeedback）
  - `runner.py` 去重 `_cann_lib_paths` → 共享 `cann_lib_paths()`
  - profile `eval_prepare`（cann-bench.yaml + schema + from_yaml + scorer ensure 触发）
  - 分层合规：scorer(L6) 返回原始 `(EvalResult, reason_str|None)`，stage(L3) 包装 ErrorFeedback
- **第 2 步完成**（收口，cannbench_adapt 迁移）：
  - 新建 `adapters/evaluation/cannbench_adapt.py`：wrapper-gen（方案 G）+ m.def schema 对齐（P10）
    下沉到 adapter；`_resolve_cann_bench_pkg_root` 复用 `cannbench_env`（去重）
  - `CannbenchAdaptStage` 退化为编排（解构 state → 调 adapter → Deployer rebuild → AdaptResult）
  - 测试改造：`test_cannbench_adapt_schema.py` import 拆分 + `_gen` 解构 helper；ST import 修复
  - 消除"cann-bench 适配半 stage 半 adapter"—— cann-bench per-repo 适配全归 adapter 边界
- **验证**：全量 UT 3206 passed / 7 skipped（tests/ut），分层依赖通过，0 回归
- **待办**：
  - heavy_llm 真实链路 ST（重跑 scatter_pa_kv_cache eval + cannbench_discovery ST + self_evolution_stages）—— 需 NPU 环境，改完后统一执行（review M1，合并前必须）

## 后续技术债（review 识别，本次不修，记录防遗漏）

> 详见 `reviews/PR-step82-cannbench-adapter-convergence-review.md`（commit `4de7f5a4` 已修 m1/m2）。下列为合理但本次不修的问题，按触发条件排期，防止遗漏。

### TD-1 (review m3, D5) — ErrorFeedback 定义在 L3 致 scorer 绕行
- **问题**：`ErrorFeedback` 定义在 `orchestration/kernel/state.py`（L3），但 L6 `CannbenchScorer` 需返回错误。为不违反 L6→L3 分层，scorer 返回原始 `(EvalResult, reason_str|None)`，stage(L3) 再包装成 `ErrorFeedback`——多一层包装。
- **为什么不修**：移 `ErrorFeedback` 到 `domain/`（L4）牵连 ~30 处 import（src+tests），超出本次范围；本次"scorer 返回 str + stage 包装"是最小改动的正确选择（分层合规、`test_layer_dependencies` 守护通过）。
- **建议修法**：`ErrorFeedback` 移到 `domain/verification.py`（与 `EvalResult` 同层，本就是 domain 概念），`state.py` 改 import；届时 scorer 可直接返回 `ErrorFeedback`，消除 stage 包装层。
- **触发条件**：下次动 `ErrorFeedback`、或分层依赖收紧、或第 3 个 L6 adapter 需返回错误时。

### TD-2 (review m5, D1) — stage `_resolve_source_dir` 硬编码 cann-bench 布局
- **问题**：`cannbench_eval.py` / `cannbench_adapt.py` 的 `_resolve_source_dir` 有 `return repo_root / "examples" / "aclnn_launch_example"` fallback——cann-bench 仓算子默认布局，写在通用 stage 层（§1.6 通用化边界：换仓失效）。
- **为什么不修**：**pre-existing**（非 step-82 引入），且是 fallback（`op_dir`/`op_identity` 优先），实际影响低；本次聚焦 cann-bench 适配收敛，不动这条历史 fallback。
- **建议修法**：仓布局 fallback 下沉到 cann-bench adapter 或 profile（如 `default_op_subdir` 字段），通用 stage 层不假设具体仓布局。
- **触发条件**：第二个算子仓接入 self_evolve_op 流程、或通用化边界专项治理时。

### TD-3 (review n1, D6) — adapter 两公共函数返回元数不一致
- **问题**：`generate_and_inject_wrapper` 返回 3 元 `(injected, errors, files_modified)`；`rename_mdef_schema_if_needed` 返回 2 元 `(schema_renamed, errors)`。
- **为什么不修**：语义合理（前者需 `files_modified`，后者不需要）；调用方 transition 分别解构，可读性略降但不影响正确性。
- **建议修法**：如统一，可让 `rename_mdef_schema_if_needed` 也返回 `files_modified`，或引入轻量结果 dataclass。
- **触发条件**：下次改 cannbench_adapt adapter 签名时顺手统一。

### 已评估为无需修（防未来重复质疑）
- **review m4**（discovery broken 的 `ErrorFeedback.details` 丢 `report` 字段）：查证全仓**无代码消费 `details["report"]`**（`cli/commands/debug.py:57` 只 `echo` 整个 `details` dict），诊断信息已在 `message`（含 `Report: <path>`）。改它需动 scorer 返回契约却无实际收益——判定不修。
