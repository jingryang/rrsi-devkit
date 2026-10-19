# L3 方案分析：缺失 artifact_recovery.py 的处理

## 选项

| 选项 | 形态 | 裁决 |
|---|---|---|
| A | 只完成 rebase，向上游报告漏提交，等上游补 | 分支在等待期无法 import，demo 交付阻塞 |
| B | **TDD 重建实现文件**（按上游自带的 L4 文档 + 锁定行为测试），独立 commit | **采纳**（用户拍板）：模块契约完全被上游自己的 `05-impl-inplace-relocation.md`、`09-impl-code-tree-orphan-feedback.md` 与 3 份测试（`test_artifact_recovery` / `test_global_orphan_recovery` / `test_perf_orphan_feedback`）钉死，重建不是"猜"而是"还原"；另建议反馈上游补提交 |
| C | 只重建 `orphan_path_feedback`（codegen/perf 可 import），`recover_orphan_artifact` 不建 | 框架仍部分不可用（design/requirement/precision 全炸），弃 |

## 为什么 B 可行且正确（四把尺子）

- **可维护**：签名与行为与上游 6 处调用点、3 份测试、`event.py::artifact_relocated`
  事件契约一一对齐；检测层复用 `_shared.py` 单一权威源，处置层不重复解析（§2.5）。
- **可扩展**：新建小产物 stage 照 design 模式一行接入 `recover_orphan_artifact`；
  代码树 stage 照 codegen/perf 模式接入 `orphan_path_feedback`——矩阵闭类。
- **可诊断**：WARN + events.jsonl `artifact_relocated` 事件（moved /
  idempotent_skip / refused_target_exists / orphan_gone）双通道，搬回全可审计。
- **架构合理**：处置归 orchestration（搬回决策要 stage 语境）、检测归
  capabilities/agent（transcript 解析属 agent 层），依赖方向合法。

## P2 附带处理

- `test_runtime_config`：对齐 demo 的刻意 config（10→30），改测试不改回 config。
- `test_run_batch`：照 demo 自己 `test_batch_runner.py` 的惯例 mock
  `_filter_healthy_cards` 为 identity（UT 不得依赖 NPU，§3.5）。
- `test_forkjoin` 竞态：框架级 P128 语义问题，独立产权线，本次不修、如实披露。
- P3 上游 3 用例：上游自身缺陷，独立产权线，如实披露 + 建议反馈上游。
