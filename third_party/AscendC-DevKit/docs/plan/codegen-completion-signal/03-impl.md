# Regbase codegen 完成判定信号重构 — L4 实施方案（as-built）

> 层级：L4（改哪个函数、什么顺序、怎么验证；as-built 记录）
> 日期：2026-08-08
> 代码基线：`da2c26d6`（PR #65 head）；覆盖 L1 P1–P5，设计依据 `02-analysis.md` §2/§3

---

## 目标

PR #65 的 codegen 完成信号重构已合入；本 L4 记录其**实际落地内容**（as-built，供追溯），并把 review 提出的后续项（M1 消费端兜底、M2 宽松兜底收口）单列为待办，不与已完成内容混淆。

## as-built 总览（PR #65 已落地）

| # | 主题 | 关键文件 | 验证 |
|---|---|---|---|
| 1 | 完成信号主路径：RETURN 自报 + VF_TEST_RESULT 识别 + empty_artifacts 兜底 + 无块不静默 COMPLETED | `codegen.py` `_transition_regbase_s2/_s4`、`codegen_s4.py` `parse_return_signal` | UT：`test_codegen_regbase_phases.py` + `test_codegen_s4_dispatch.py` 全绿 |
| 2 | s2 去除文件/占位符校验（`_orchestration_plan_error` 删除），完成判定只信 agent 返回 | `codegen.py`、`.claude/agents/ascendc-dev-s2-analysis.md`、skill schema/template | UT：`test_codegen_regbase_phases.py`（`test_s2_*_advances_*` 6 例）全绿 |
| 3 | s4-coding 反混淆：一次只处理一个 sub-stage | `.claude/agents/ascendc-dev-s4-coding.md`、`phase-c-prompts.md` | 协议澄清，人工评审 |

### 改动 1 落地细节 — `parse_return_signal`

- 优先 `## RETURN:` 块（等号分隔）；其次 `## VF_TEST_RESULT` 块（冒号分隔，锚定 header 后紧跟 status 行避免正文误匹配）；皆无 → 走**宽松兜底**（`_extract_fields(final_response[:600], _RETURN_FIELD_RES)`）。
- 测试：`test_parse_return_signal_standard_return_block` / `_vf_test_result_block_only` / `_prefers_return_over_vf_result` / `_ignores_prose_vf_result_mention` 守护。

### 改动 1 落地细节 — `_transition_regbase_s2/_s4`

- `dispatch_status`：`ok/empty_artifacts→COMPLETED`、`failed/fatal→FAILED`、`partial→PARTIAL`、`paused→PAUSED`、未知→FAILED。
- `_backend_status in ("fatal","partial")` → 硬失败，文本自报不得覆盖。
- 有 `final_response` 但无机器可读块 → 不静默抬成 COMPLETED，按 FAILED 处理并 `Logger.warn`。
- 测试：`test_s2_empty_artifacts_advances_via_return_signal` / `test_s2_empty_artifacts_without_return_treats_as_failed` / `test_vf_test_result_block_only_failed_retries_vf` 等守护。

### 改动 2 落地细节 — 删除校验门

- 删除 `_orchestration_plan_error`（A 类路径启发式 + B 类结构检查一并删除）与 `coding_index.md` 存在性校验。
- deliverables 降级为「供人读/审计的说明列表」；s2/s4 完成判定只信 agent 返回（决策依据见 `02-analysis.md` §2/§3）。

---

## Review 后续项（已实施）

以下由 PR #65 review（`reviews/PR-65-review.md`）提出，随本 L4 一并补齐：

### TODO-1（原 M1）— s4 消费端结构兜底 ✅

已实施（决策冻结于 `02-analysis.md` §3 选 C）：
- `_pending_ids` / `_step_by_id`（`codegen_s4.py`）：非 dict / 缺 `id` / id 非 str → `Logger.warn` + 跳过，防 `KeyError`（原 `s["id"]` 崩溃）。
- `_is_vf_step`（`codegen_s4.py`）：plan 内查到 `.VT.` 步骤但 kind≠vf 时回退按 `.VT.\d+$` 正则识别（防静默错路由到 `call_s4`），并留痕 warn。
- 全部 sub_stage 结构异常 → `resolve_sub_stage` 返回 DONE + warn（不崩溃、不制造新分支）。
- 测试：`test_pending_ids_skips_missing_id_without_crash` / `test_resolve_sub_stage_all_broken_returns_done` / `test_is_vf_step_falls_back_to_regex_on_kind_mismatch`。

### TODO-2（原 M2）— `parse_return_signal` 宽松兜底收口 ✅

已实施：删除「RETURN/VF_TEST_RESULT 块皆无 → 扫正文前 600 字符」的宽松兜底（`codegen_s4.py`），与 A5 `parse_agent_return_block` 严格语义对齐（无块 → `{}` → 调用方判 FAILED）；补正文 `status=` 误匹配 UT（`test_parse_return_signal_ignores_prose_status_mention`）。

---

## 验证（as-built 状态）

- `tests/ut/orchestration/test_codegen_s4_dispatch.py`（33）+ `test_codegen_regbase_phases.py`（94）全绿。
- 回归：`test_precision_debug_a5_routing.py` + `test_precision_debug_a5_source_safety.py` + `test_precision_debug_stage.py` + `test_precision_debug_runtime_refine.py` + `test_graph_executor.py` 全绿（516 passed / 3 skipped，skip 为既有声明）。
- skill shell 测试：`.claude/skills/ascendc-op-dev-coding-regbase/tests/test_dispatch_behavior.sh` 18 passed。
- 运行方式（本机 PYTHONPATH 被 batchrun workdir 遮蔽，须显式前置 src）：
  `PYTHONPATH=/root/workspace/AscendC-DevKit/src:$PYTHONPATH python -m pytest tests/ut/orchestration/test_codegen_s4_dispatch.py tests/ut/orchestration/test_codegen_regbase_phases.py -q --no-env-check`

---

## 边界

- **不恢复 s2 的 INP 校验门**：完成信号只信 agent 返回是拍板决策，`orchestration-plan.schema.json` 保留为生成规范 + 人读，框架不做严格内容校验（`02-analysis.md` §3）。
- TODO-1/TODO-2 已实施并验证；完成信号决策保持不变。
