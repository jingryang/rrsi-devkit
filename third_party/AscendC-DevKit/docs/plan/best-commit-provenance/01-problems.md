# L1 问题记录 — best 收敛锚点 provenance 失真（20260915 批 RCA）

> 产权：本文件只记客观事实（哪里坏了、凭什么这么说）。方案/取舍见 `03-analysis.md`，改动配方见 `04-impl-measured-source.md`。
> 前史：step-119（`precision-control-ownership/`）引入「测量行 source_identity + 从测量史现算 best」——本问题是该机制在精度调试真实生命周期下的组合缺陷，非设计初衷推翻。

## P1 测量行 source_identity 全程陈旧（抄 deploy stamp，调试期间从不刷新）

**事实**：批 `20260914-163856-397936`（worktree `20260915_003839`，2026-09-15 00:38–04:22，2/2 eval-passed）：

- 两算子（adaptive_avg_pool_3d / transpose，**两个独立 worktree、各自独立 HEAD 链**）的 control.json 中**全部** run_tests 测量行携带一字不差的 `source_identity="94c716aecb9d-dirty-1"`：
  - transpose：`output/20260914-163856-397936/20260914-163856-648f03/artifacts/debug/transpose/control.json`，首行（UTC 17:41:17，20/20 failed）与末行（UTC 19:59:39，0/20 all passed）同 stamp；
  - adaptive：`…-e67141/artifacts/debug/adaptive_avg_pool_3d/control.json`，18/20→0/20 两行同 stamp。
- 测量时刻 worktree 真实状态（git log 实证）：
  - transpose：entry snapshot `158f484`（2026-09-15 01:39:53 +0800）、diagnose 修复 `5f7d4bf`（03:56:44）；末次测量（03:59:39）时 HEAD=5f7d4bf；
  - adaptive：entry snapshot 于 01:38:43 后落地，43min diagnose 修复后 02:24:46 全过测量。
- `94c716ae` 是两 worktree 共同的基线（cann-bench HEAD，2026-08-18 提交，**不含任何算子实现**：`git ls-tree 94c716ae -- …/csrc/ops/` 仅 add/sqrt/_common/CMakeLists）。

**根属**：`precision_debug_substages.py` 行写入（RunTestsSubstage.transition）读 `state.deploy_result.source_identity`；该字段只在框架侧 Deployer 运行时刷新（codegen 末次部署、converge 自身重部署），而精度调试期间 diagnose agent 在会话内自建包（build→单用例验证→commit），**不流经框架 Deployer** → stamp 停留在 codegen 时代（构建于 entry commit 前 19s、HEAD=94c716ae+脏树——`-dirty` 后缀对**当时那个包**是准确的）。`probe_git_head_and_dirty` 探测函数本身正确（批后手动实测返回 5f7d4bf）。

**两 worktree 全行同 stamp** 是「没刷新」的判别性证据：两棵不同的树不可能在多个时刻真实处于同一 `{HEAD,dirty}` 状态。

## P2 best 收敛锚点非法 → RepoGuard.rollback no-op 却打成功日志

**事实链**：

- `_best_identity_from_history`（step-119）从测量行取 `source_identity` 作「最优被测 identity」→ 本批返回 `94c716aecb9d-dirty-1`（P1 陈旧值）。
- `_converge_to_best_commit` 把它传给 `RepoGuard.rollback(repo_root, op_dir, baseline_ref)`；`{sha}-dirty-N` 是**溯源标签不是 git ref**：`git ls-tree 94c716aecb9d-dirty-1` rc≠0，rollback 的 Step-1 checkout 被当「无 tracked 内容（harmless）」跳过，Step-2 `clean -fd op_dir` 只清 untracked（生成代码已被 entry snapshot 提交为 tracked，无物可清）→ **整个回滚是 no-op**。
- 日志打出 `repo_rollback op_dir restored to 94c716aecb9d (checkout+clean)` 与 `converge_best_commit op_dir → 94c716aecb9d + redeployed (smoke ok)` ——成功文案描述了一次实际未发生的还原；`baseline_ref[:12]` 截断令 dirty 标签在日志里**伪装成 sha**。
- 本批交付未受损的原因：converge 的重部署从**当前树**（恰为 5f7d4bf 修复态）重建 → eval 跑的代码正确、分数有效。属「树恰在最优态」的运气，非机制保证。

## P3 既有通路里的可触发缺口（当前实现行为，非假设）

- **非全过退出**：`_best_identity_from_history` 路径二（argmax）会指向**更早轮次**的测量；该轮代码若要恢复，依赖 rollback checkout——P2 已证锚点非法时 checkout 永不执行 → eval 跑最终态而非 best 态，无信号。
- **收尾脏树**：diagnose 结束若留下比 best 更差的未提交改动，rollback 无法恢复（no-op），无信号。
- **`_converge_check_handoff`**：deploy stamp 与 best identity 做**精确字符串相等**比对；两者形态/时刻本不同（stamp=部署时刻标签、best=测量来源），正常路径也几乎必不相等——比对语义与数据形态未对齐（本批因成功路径不触发而未暴露）。

## 证据索引

- 批日志：`logs/batch_20260915_003839.log`（rollback/converge 行：03:59:39、04:00:31）
- control.json：见 P1 路径
- 代码位点（修复前）：`src/ascendc_devkit/orchestration/stages/precision_debug_substages.py:2318-2331`（行写入抄 deploy stamp）、`:1155-1193`（best 取 source_identity）、`:1283-1315`（锚点传 rollback）、`:1222-1249`（handoff 精确相等）；`src/ascendc_devkit/infra/repo_guard.py:263-301`（非法 ref 静默跳过 checkout + `[:12]` 截断日志）；`src/ascendc_devkit/orchestration/stages/deploy.py:90-111`（stamp 语义，函数本身正确）

## 状态

- P1/P2/P3：**已修复（2026-09-15，step-124）**——测量行写入时刻现探 git（`source_commit` 全 sha 作收敛锚点 + `source_identity` 测量时刻标签）；`_best_commit_from_history` 只认 `source_commit`；RepoGuard.rollback 入口 `rev-parse --verify` 拒非法 ref（响亮失败）；handoff 改 sha 前缀比对。详见 `04-impl-measured-source.md`。
- Review 整改（2026-09-15）：M1 补 converge 测量史锚点端到端守护；m1 `_current_head` 探测单点收口；m2 probe 增 `scope`（dirty 口径 op_dir 化）。全量 UT 4354 绿。
