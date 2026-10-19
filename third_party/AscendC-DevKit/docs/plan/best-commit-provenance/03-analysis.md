# L3 方案分析 — best 收敛锚点 provenance 失真（step-124）

> 输入：`01-problems.md`（P1-P3）。拍板后冻结。

## 0 问题本质（一句话）

「被测来源标识」被一个字段承担了两个职责：**溯源标签**（诚实标记「测于哪棵树」，允许 `-dirty`）与**收敛锚点**（converge/teardown 要 checkout 回去的 git ref，必须合法）。step-119 的 stamp 设计（B）与测量史 best 设计（A）各自正确，但拼装处（行写入抄 deploy stamp、锚点直取标签字符串）让两个职责互相污染。

## 1 候选方案

### 方案 A：测量时刻现探 + 锚点/标签分字段（选定）

- 行写入（RunTestsSubstage.transition）不再抄 `state.deploy_result`，改在**测量时刻**现探 `probe_git_head_and_dirty(repo_root)`：
  - `source_commit` = **全 sha**（合法 git ref，作 converge/teardown/report/_sync_debug_result 的收敛锚点）；
  - `source_identity` = `{sha12}-{clean|dirty-N}`（测量时刻可读标签，dirty 标记保留「测于未提交改动」的诚实信号）。
- `_best_identity_from_history` → `_best_commit_from_history`：只认 `source_commit`（§1.4 不留旧字段 fallback）。
- `probe_source`（commit+标签格式化）收口到 `infra/provenance.py` 单点，`deploy._source_identity` 委托（§1.15：同一探测+格式化不再两处实现）。
- 加固（宽容兜底+可诊断）：`RepoGuard.rollback` 入口 `git rev-parse --verify` 校验 baseline_ref，非法 → `Logger.error` + return False（converge 走既有 `not rolled` 分支 WARN + handoff 标记），消灭「no-op 却打 restored 成功日志」。
- `_converge_check_handoff` 比对改 **sha 前缀**（deploy 标签取首段 vs best 全 sha 前缀）：同 commit 视为一致（deploy 时刻的 dirty 不构成「用错包」信号），不同 commit 才标记。

### 方案 B：仅 converge 侧提取 sha（不动行写入）

strip `-dirty` 后缀取 sha12 + rev-parse 校验。
**否决**：修不了 P1 陈旧——best 仍指向 codegen 时代 commit（94c716ae 处无算子代码，checkout 恢复的是空目录），测量史对「哪轮代码最优」的区分度完全丢失。

### 方案 C：每轮测量后强制框架 deploy 刷新 stamp

**否决**：每诊断轮全量重部署 ~60s 空烧，重蹈 step-96 D1 已否决的「用重部署重新发现已知事实」；且 stamp 刷新的语义是「部署产物来源」，不是「测量对象」。

## 2 取舍审计（四把尺子）

- **可维护**：锚点与标签职责分字段显式化；探测+格式化单点（provenance）；step-119 的双路径 best 逻辑不动（只换数据源）。
- **可扩展**：任何未来写入测量行的 phase 都能复用 `_measured_source`；非法锚点在任何调用方（converge/teardown/A5 侧若接入）都被 rollback 入口校验拦截，不依赖调用方自觉。
- **可诊断**：行同时携带 commit（机器锚点）与 dirty 标签（人读信号）；rollback 拒非法 ref 响亮报错；handoff 语义（同 commit=一致）与数据形态对齐。
- **架构合理**：探测归 L7 provenance（与 probe_git_head_and_dirty 同居）；行写入/锚点派生归 substage（测量史产权方）；ref 合法性校验归 RepoGuard（git 操作的唯一入口，§1.15）。

## 3 边界与不做

- **deploy stamp 职责不变**：`deploy_result.source_identity` 仍是「这份编译产物从哪棵树编出来」的溯源标签（deploy 先于 commit 的 `-dirty` 编码保留原语义），只是**不再被测量行转抄**。
- **A5 侧不动**（`precision_debug_a5.py` 的 best_snapshot 自带 commit 字段，无本缺陷；A5 产权归同事）。
- **不给 `-dirty` 锚点做恢复**：脏树本就不可 checkout 恢复（clean 语义即删），dirty 期间测量的 best 用其基线 commit 作锚点 + 标签留信号，是诚实且可执行的折中。
- **不迁移既有 control.json**：per-run 临时产物，无历史数据要兼容（§1.4）。

## 4 验证策略

TDD（§3.1）：新 UT 四组（`_measured_source` 真实 git repo 三态 / 行写入现探断言（预置陈旧 deploy stamp 证不转抄）/ `_best_commit_from_history` 双路径只认 source_commit / RepoGuard 非法 ref 拒绝+合法 ref 恢复+新算子 no-op 语义）+ handoff sha 前缀两组；既有 step-96/step-119 测试同步到新契约。全量 UT 回归。端到端验证待下批真实 run（converge 日志应打出真实 fix-commit sha 而非 baseline-dirty 标签）。
