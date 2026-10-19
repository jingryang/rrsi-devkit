# Regbase codegen 完成判定信号重构 — L1 问题记录

> 层级：L1（事实快照，不提方案、不排顺序、不写决策）
> 日期：2026-08-08
> 代码基线：`7a1cf788`（PR #65 merge-base）→ `da2c26d6`（PR #65 head）

---

## P1. s4 磁盘交付物校验误判「缺失」→ 3 个 session 白重试 4.E

**事实**：
- `run 20260805_224038 add_rms_norm_dynamic_quant`：s4 完成判定依赖磁盘交付物校验（`dispatch COMPLETED` 前按 `orchestration_plan.json` 的 `deliverables` 字符串匹配磁盘文件）。plan 的 `deliverables` 用 mainline 仓 camelCase 命名（`op_plugin/OpXxx.cpp`），而 s4-coding 按本仓 flat snake_case 约定正确产出（`op_plugin/xxx_plugin.cpp`）→ 磁盘匹配永远报「缺失」→ 3 个 session 全部白重试 Stage 4.E（`ses_02cc1722`/`02cb8a9f`/`02cb435a`）。
- `_check_deliverables_on_disk` / `_bump_deliverable_fuse` / `_fuzzy_keyword` 位于 `codegen_s4.py`（c41b999e 已删除）。

**凭什么这么说**：commit `c41b999e` 消息引用 run id 与 session id；`codegen_s4.py` 删除函数 diff。

---

## P2. s2 完成判定只认 `status=="ok"` → 纯分析 stage 死循环

**事实**：
- s2-analysis 是**纯分析 stage**：交付物（`orchestration_plan.json` / `coding_index.md`）全部写在 staging `record_dir`，spawn `working_dir`（op_dir）无新增文件 → SDK backend 恒报 `empty_artifacts`。
- commit `508430c9` 把 s2 完成判定改成只认 `agent_result.status=="ok"` → 每次成功都被判失败 → 反复 spawn s2 死循环。
- `run 20260807-100841-d9de37`：连续 4 次 empty_artifacts 重试，s2 永不推进 s4。

**凭什么这么说**：commit `da2c26d6` 消息引用 run id；`_transition_regbase_s2` 死循环现象。

---

## P3. vf-test-agent 漏写 RETURN 块 → 失败被静默吞掉并标 done 推进

**事实**：
- `ascendc-vf-test-agent`（Stage 4 的 VF 步骤）实际可能漏写自己的 `## RETURN:` 块，只把 regbase-vf-test skill 的 `## VF_TEST_RESULT` 块（`status:`/`error_type:` 冒号分隔）原样带到最终回复。
- 旧 `parse_return_signal` 只识别 RETURN 块 → 返回 `{}` → s4 transition 按 backend `ok` 兜底成 `COMPLETED`，把 `FAILED/PREC` 静默吞掉并标 done 推进，不触发重试。
- `run 2026-08-06 group_norm` `4.C.3.VT.0`：VF 测试失败无重试的根因。

**凭什么这么说**：commit `04eb8a7b` 消息引用 run 与步骤 id；`test_codegen_regbase_phases.py` 新增测试 `test_vf_test_result_block_only_failed_retries_vf`。

---

## P4. orchestration_plan.json 结构校验（`_orchestration_plan_error`）被整体删除

**事实**：
- 旧 `_transition_regbase_s2` 用 `_orchestration_plan_error` 做加载期校验：`sub_stages` 非空、id 唯一且 `4.` 前缀、kind ∈ {code/vf/check}、checkpoint_group ∈ 固定集、初始 status=pending、`.VT.` 步骤必须 kind=vf、deliverables 不得为概念占位符；不合规 → INP → s2 带反馈重跑。
- PR #65 删除 `_orchestration_plan_error` 及 `coding_index.md` 存在性校验，s2/s4 完成判定只信 agent RETURN 自报 + backend status 兜底（含 `empty_artifacts→COMPLETED`）。
- 删除后 s4 消费端 `_read_plan` 仅容错 JSON 解析、不容错结构：`sub_stages` 项缺 `id` → `_pending_ids`（`codegen_s4.py:83` `s["id"]`）直接 `KeyError: 'id'`；`.VT.` 步骤 kind=code → `_is_vf_step`（`codegen_s4.py:248`）返回 False → 该 VF 步骤被 dispatch 到 `call_s4` 普通编码 agent（静默错路由，无重试无留痕）。

**凭什么这么说**：`_orchestration_plan_error` 在 PR #65 diff 中被删除（`git show 041e3ead`）；运行期实测 `KeyError: 'id'` 崩溃与 `.VT.` 错路由（`PYTHONPATH=src python -c` 复现）。

---

## P5. codegen 完成判定重构无 docs/plan L1/L2/L4 记录

**事实**：
- PR #65 内 4 个 commit（`04eb8a7b` VF_TEST_RESULT 解析、`041e3ead` s2 去除文件/占位符校验、`da2c26d6` s2 RETURN+empty_artifacts、`7521d308` s4-coding 反混淆）对框架 codegen orchestration 层做了显著行为变更。
- 这些变更在 PR #65 中**没有任何** L1 问题文档、L2 步骤或 L4 实施方案记录；commit 消息仅引用 run id，未落 `docs/plan`。
- PR #65 的 docs/plan 仅覆盖 precision_debug_a5 的 P7/P8/P9（`a5-precision-refactor/`）。

**凭什么这么说**：`grep "交付物校验\|empty_artifacts\|RETURN 自报\|20260807-100841" docs/plan/` 在非 runlog 文档中 0 命中；`git show <4 commits> --name-only | grep docs/plan` 均无输出。
