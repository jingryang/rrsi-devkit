# L4 实施方案 — 测量时刻现探 + 合法收敛锚点（step-124）

> 输入：`03-analysis.md` 方案 A。改动五处 + 测试两组文件。

## 改动清单（按依赖序）

1. **`src/ascendc_devkit/infra/provenance.py`**：`probe_git_head_and_dirty` 后新增
   ```python
   def probe_source(repo_dir) -> tuple[str | None, str]:
       """HEAD+dirty 探测 → (完整 commit sha, {sha12}-{clean|dirty-N} 标签)。单点（§1.15）。"""
   ```
   标签是溯源标识非 git ref；需 rollback 锚点用返回的完整 sha。

2. **`src/ascendc_devkit/orchestration/stages/deploy.py`** `_source_identity`（:90）：主体委托 `probe_source` 取标签（行为不变，格式化单点化）。

3. **`src/ascendc_devkit/orchestration/stages/precision_debug_substages.py`**：
   - 新增模块级 `_measured_source(state) -> tuple[str, str]`（放 `_current_head` 旁）：从 `state.op_identity.repo_root` 现探；无 repo / 非 git → `("", "")`。
   - RunTestsSubstage.transition 行写入（:2315-2331）：删「读 `state.deploy_result.source_identity`」块，改 `_m_commit, _m_ident = _measured_source(state)`；行增 `"source_commit": _m_commit`，`"source_identity": _m_ident`（语义改为测量时刻树标签）。
   - `_best_identity_from_history`（:1155）更名 `_best_commit_from_history`：两路径（全过取最近 / argmax 平局较早）均改读 `content.get("source_commit")`；docstring 注明返回合法 ref。**同步 6 个调用点**（:735 报告 / :902 / :1283 converge / :1442 _sync_debug_result / :1535 / :2371）。
   - `_history_run_tests` docstring（:1111-1116）：「B 的 deploy stamp」→「测量时刻现探（_measured_source）」。
   - `_converge_check_handoff`（:1222-1249）：精确相等 → sha 前缀比对（`_src.split("-", 1)[0]` vs `best_identity.startswith(...)`）；mismatch 记录保留原值双方。

4. **`src/ascendc_devkit/infra/repo_guard.py`** `rollback`（:263）：Step-1 前增 ref 合法性校验
   ```python
   v = self._git(repo_root, "rev-parse", "--verify", "-q", baseline_ref)
   if not (v and v.returncode == 0 and (v.stdout or "").strip()):
       Logger.error(f"rollback refused: baseline_ref {baseline_ref!r} 不是合法 git ref（如 {{sha}}-dirty-N 溯源标签）— op_dir 未还原")
       return False
   ```
   （文件备份前缀路径 `_FILE_BACKUP_PREFIX` 在此校验之前分流，不受影响。）

## 测试（TDD，先红后绿）

- **`tests/ut/orchestration/test_precision_debug_stage.py`**：
  - `_hist_run` 增 `source_commit=""` 参数；
  - `TestMeasuredSource`：真实 tmp git repo 三态（clean / dirty-1 / 非 git → ("","")）；
  - `test_run_tests_row_records_measured_source`：git repo + control seeded（status=passed）+ `deploy_result.source_identity` 预置陈旧值 → transition 后末行 `source_commit == HEAD 全 sha`、`source_identity == {sha12}-clean`（证明不转抄 stamp）；
  - `TestBestCommitFromHistory`：全过取最近 source_commit / argmax 平局较早 / 仅标签行 → ""（回归守护：标签不再被当锚点）；
  - 既有 `test_transition_materializes_debug_result_when_passed` 等按新契约改 `source_commit`。
- **`tests/ut/orchestration/test_step96_converge_quality.py`**：
  - `TestConvergeCheckHandoff` 增：同 commit（deploy 标签 sha12 == best 全 sha 前缀）→ 无标记；异 commit → 标记；
  - `TestRepoGuardRollbackRefValidation`：非法 ref（`…-dirty-1`）→ False + Logger.error + 不动工作区；合法 ref + tracked 改动 → True + 还原；合法 ref + 新算子（ref 处无 tracked）→ True + untracked 清理（良性 no-op 语义保留）。

## 验证

1. 定向：两测试文件全绿；
2. 全量 UT（§3.6）；
3. 端到端（下批真实 run）：converge 行应打印真实修复 commit sha；报告 best_commit 列为合法 sha。

## As-built（2026-09-15）

实施完成，见 git commit；**全量 UT 4350 passed / 0 failed**（定向两文件 296 绿）。实施备注：行写入现探的 UT 断言锚定 sha 前缀而非 dirty 计数（测试自身的 control.json/result.json 落 repo 工作树内被诚实计脏）；该 UT 顺带实证了全链端到端（transition→行现探→converge→合法锚点 rollback→redeploy）。

## Review 整改（2026-09-15，M1/m1/m2）

- **M1（D3）**：补 `TestConvergeHistoryAnchor::test_converge_rolls_back_to_measured_commit`——history 全过行 `source_commit=shaA` + 更差脏终态 + **真实 RepoGuard** → 断言 kernel 真回 v1（修复前必红：锚点空 → fallback HEAD=shaB）。
- **m1（§1.15）**：`_current_head` 委托 `probe_source` 单点，删除本模块自建 rev-parse 子进程；行为守护 UT ×2（git→HEAD / 非 git→None）。
- **m2（§1.2 可扩展）**：`probe_git_head_and_dirty` / `probe_source` 增 `scope` 参数（dirty 口径限定子路径）；`_measured_source` 以 `_operator_dir(state)` 限定 op_dir——一仓多 op 布局下兄弟 op/仓根脏改动不计入本 op 标签（锚点 HEAD 不受影响）。红→绿守护 UT：op_dir 内脏计入 dirty-N / op_dir 外脏不计。
- 全量 UT **4354 passed / 0 failed**；review 报告 `reviews/step124-125a2bac-review.{md,json}`（本地）。
