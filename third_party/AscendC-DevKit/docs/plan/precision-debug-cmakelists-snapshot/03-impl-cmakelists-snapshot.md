# L4 实施方案(as-built)— 快照排除表豁免构建清单 + 现场重建验证

> 对应 L3 方案 A。日期:2026-10-12。全部改动已落地并验证。

## 改动清单

### 1. `src/ascendc_devkit/orchestration/stages/precision_debug_a5/git_safety.py`(根修,单点)

`_allowed_operator_files` 中:

- 新增 `_BUILD_MANIFEST_BASENAMES = ("CMakeLists.txt",)`(附注释:机制代理误杀的因果与后果);
- veto 判定改为:`basename not in _BUILD_MANIFEST_BASENAMES and _matches_globs(rel_to_op, _DEBUG_EXCLUDES)` 才排除;
- `import PurePosixPath`(函数内,与既有 `import fnmatch` 同位)。

排除表仍拦截一切其他 `*.txt`;豁免发生在 include/exclude 过滤之后,不产生新暴露面。

### 2. 现场修复(cann-bench 批次 worktree,不提交)

- 重建 `examples/aclnn_launch_example/csrc/ops/mse_loss_cross_entropy_loss/CMakeLists.txt`(参照同仓 sqrt/add 模板:`register_aclnn_op(MseLossCrossEntropyLoss, HOST_SRCS, API_SRCS, mse_loss_cross_entropy_loss/op_kernel, mse_loss_cross_entropy_loss_kernel.cpp, op_kernel, op_api)` + `register_aclnn_plugin`);
- 重建包安装到旁路 `verify-dfa6242/{opp,python}`,**不动** run 的 `artifacts/per-op`。

## 验证(as-built)

| 项 | 结果 |
|---|---|
| TDD 红 | `test_entry_snapshot_keeps_build_manifest_despite_txt_debug_veto`:改前失败,且复现事故机制(提交为空、`op_dir still dirty (2 changes)`) |
| TDD 绿 | 同用例通过:CMakeLists.txt 入快照提交,`stderr_case.txt` 留在未跟踪 |
| 既有行为回归 | `test_entry_snapshot_commits_only_profile_allowed_production_files`(调试 `*.txt` 仍排除)等 source_safety + precision_debug_stage 235 passed |
| 全量回归 | `tests/ut/orchestration/` **2239 passed / 0 failed** |
| 现场构建 | dfa6242 工作树 `bash build.sh --soc=ascend910b` → **成功**(12:36 失败的同一步),产出 `dist/cann_bench_20261012_linux_aarch64.run` + `cann_bench-1.0.0-cp38-abi3-linux_aarch64.whl` |
| 旁路安装+smoke | `.run --install-path=verify-dfa6242/opp` SUCCESS + whl 安装;NPU 上 `torch.ops.cann_bench.mse_loss_cross_entropy_loss(logits, targets, pred)` 真实执行,产出有限标量 y=5.54 → **SMOKE PASSED** |

## 边界与遗留

- 现场 worktree 的 CMakeLists.txt 保持未跟踪(瞬态批次仓,提交会改已完结 run 的提交史);若该 worktree 再次被 rollback checkout+clean 会再丢——根治靠快照修复,下一批次入口快照自然携带。
- 本次 run 的 `debug_result.converge_mismatch` 标记保留(历史事实如实记录);物理复验已由旁路重建+smoke 补齐。
- 收尾元数据滞后(交付记录 identity `a8c0900a8937-dirty-2` ≠ 物理安装 `4b435489aa6a-dirty-6`)未在本案处理——agent 侧重装不走 Deployer 时 deploy_result 元数据不刷新,属另一条线(观察项,未立题)。
- 950 侧:git_safety.py 为 950 起源文件,本改动进入「A3 侧已演进文件」分叉清单(台账追记),下轮合并按 P8 口径处理。
