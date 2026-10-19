# L4 实施方案：重建 artifact_recovery.py + 修 demo 自带测试陈旧

## 改动 1：新增 `src/ascendc_devkit/orchestration/artifact_recovery.py`

按上游 `05-impl-inplace-relocation.md`（改动点 2）与 `09-impl-code-tree-orphan-feedback.md`
重建，契约与上游 6 处调用点 / 3 份测试完全一致：

- `recover_orphan_artifact(transcript, filename, wd, state, stage_name) -> bool`
  - 检测复用 `_shared._harvest_relocation_evidence_detailed`（四重约束）；
  - move 防御：target 缺 → `shutil.move` + WARN + `artifact_relocated(moved)`；
    samefile → 幂等 True；target 冲突 → `refused_target_exists` 返 False；证据文件
    没了 → `orphan_gone` 返 False；跨 batch → 拒返 False；`wd=None`/无证据 → False；
  - 事件经 `EventLog.for_path(ws.events_path)` 共享实例（跨写者显式锁，F3 加固）；
    workspace 不可达 → 跳过事件不炸（WARN 即信号）。
- `orphan_path_feedback(agent_result, working_dir, stage_name, locator_name)` →
  `(orphan_paths, feedback)`：证据源 `_shared._transcript_orphan_paths`，无证据返回
  `([], "")`；文案含 locator_name 供 codegen/perf 消费。

## 改动 2：`tests/ut/orchestration/test_runtime_config.py`

`test_real_config_default_10_and_getter` → `..._30_and_getter`，断言 30.0（对齐 demo
commit 的刻意 config：慢卡冷启动 8-12s/卡，10s 误杀健康卡）。

## 改动 3：`tests/ut/cli/test_run_batch.py`

加 autouse fixture `_noop_card_health_filter`：mock
`batch_runner._filter_healthy_cards` 为 identity（与 demo 自己的
`test_batch_runner.py` 同惯例；UT 不依赖 NPU，§3.5）。

## 验证

- 锁定测试：`test_artifact_recovery` 10 + `test_global_orphan_recovery` 4 +
  `test_perf_orphan_feedback` 4 = **18 passed**（首跑即绿）。
- 全量 UT（`-m "not llm and not npu and not cann and not slow and not heavy_llm
  and not external_repo"`，`--no-env-check`）：**3995 passed / 16 skipped / 4 failed**。
- 4 个残留失败均为 **rebase 前已存在**、非本改动引入：
  - `test_capabilities` ×2 + `test_opencode_backend` ×1：clean `upstream/main` 上同样
    失败（上游 `_resolve_model` fail-fast 后旧 fixture 未适配）→ 建议反馈上游。
  - `test_forkjoin::TestForkJoinBranchFailure`：P128 分支取消 vs 失败分类调度竞态，
    间歇性（merge-base 亦不干净），属框架级独立产权线。
- 真实环境（LLM/NPU/CANN）未跑：本机无硬件/凭据（§3.6/§3.7 诚实披露）。
