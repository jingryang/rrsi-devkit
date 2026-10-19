# L1 问题记录：upstream/main 缺 artifact_recovery.py（rebase 继承缺陷）

> 事实快照（2026-08-27）。起因：demo 分支 rebase 到 upstream/main（c80a2365）
> 后框架无法 import。

## P1：orchestration 层 6 个生产模块 import 一个不存在于任何分支的模块

- `src/ascendc_devkit/orchestration/stages/{codegen,perf,requirement,design_substages,
  precision_debug_substages}.py` 均 `from ascendc_devkit.orchestration.artifact_recovery
  import ...`（codegen/perf 用 `orphan_path_feedback`；requirement/design_substages/
  precision_debug_substages 用 `recover_orphan_artifact`）。
- **模块文件不存在**：`git ls-tree <任何分支> src/ascendc_devkit/orchestration/
  artifact_recovery.py` 全部为空；`git log --all -- <该路径>` 为空（从未被提交）。
  clean checkout `upstream/main` 后 `import ascendc_devkit.orchestration.stages.codegen`
  → `ModuleNotFoundError`。
- 上游提交 `9a883cc9`（孤儿产物全局收口）只提交了 import、检测层
  （`_shared.py` 的 `_transcript_orphan_paths` 等）、事件构造器
  （`event.py::artifact_relocated`）、测试（`test_artifact_recovery.py` 等 3 份）
  与 L4 文档，**漏提交实现文件本体**。`upstream/v0.2.0` 同缺。

## P2：demo 分支自带的测试陈旧/回归（rebase 前已存在，非冲突引入）

- `tests/ut/orchestration/test_runtime_config.py::test_real_config_default_10_and_getter`
  断言 hw_probe_sec=10，但 demo commit 把 config 改 30（慢卡冷启动实证 8-12s/卡）后
  未同步测试。
- `tests/ut/cli/test_run_batch.py`（3 用例）：demo commit 的 batch_runner 新增 NPU 卡
  健康探针（`_filter_healthy_cards`）后，旧测试未 mock 探针 → 无 NPU 环境全卡被拒 →
  ConfigError（demo 自己的 `test_batch_runner.py` 已 mock，此文件漏改）。
- `tests/ut/orchestration/test_forkjoin.py::TestForkJoinBranchFailure`：P128 分支取消
  与失败分类之间的调度竞态，间歇性失败（merge-base 上 5/6 过，demo commit 后变脆）。

## P3：upstream 自带 3 个失败用例（非 demo 引入）

- `test_capabilities.py`（2 用例）与 `test_opencode_backend.py::test_concurrent_ops_...`
  在 clean `upstream/main` 上同样失败（opencode `_resolve_model` fail-fast 后旧测试
  fixture 未提供 top-level model 等）。
