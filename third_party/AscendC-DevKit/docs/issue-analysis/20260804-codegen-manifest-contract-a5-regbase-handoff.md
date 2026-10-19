# codegen manifest 契约强化 —— A5 regbase 侧 handoff（待同事确认）

> 产权：A5 regbase codegen 归同事（memory `codegen-a5-ownership-boundary`）。本仓 A3 codegen 侧
> 已修复（20260804），A5 regbase 有**平行缺口**，需同事确认后收敛。本文件是交接说明，非已实施。

## 背景：dequant codegen HALT 根因 + A3 侧已做的修复

20260804 批 dequant_swiglu_quant codegen HALT，根因：agent 把 `codegen_manifest.json` 当"会话报告"
写（塞 `compile_status`/`runtime_status`/`suspected_root_causes`/`next_steps`），漏契约字段
`callable_target`/`inputs`/`outputs`；框架（membase/A3）检测到 callable_target 缺直接 halt，
**尽管 plugin 正确**（`TORCH_LIBRARY_FRAGMENT+m.def` 完整可解析）。

A3 侧已实施（commit 待提交，文件：`codegen.py`/`state.py`/`runtime_config.py`/`orchestration-config.json`/
`SKILL.md`/`workflow.py`）：
1. **构造性派生**（§2.9）：`_ensure_manifest_callable_target` 从 plugin 注册派生 `callable_target.symbol`
   （kind 由 profile 给）。agent 漏填 symbol 时自动救回，不 halt。
2. **机械校验 + 定向 retry**（§3.4）：`_missing_required_manifest_fields` 按 schema `required_keys`
   校验；缺 authored 字段（inputs/outputs）→ `_artifact_retry`（不 halt、不写 deploy_result → runner
   re-spawn，带 `codegen_artifact_feedback`）；budget（`codegen.artifact_max_retries=5`）耗尽才 halt。
3. **skill 强化**：manifest 内联 JSON 模板 + contract/report 分离 + 维8 自检。
4. **删旧 halt 路径**（§2.5）+ 纠正 workflow.py docstring（"无 manifest"移出结构性 halt 归类）。

## A5 regbase 的平行缺口

`_transition_regbase_s5`（codegen.py:1897-2021）：
- **已有** manifest 整个缺失时的派生（L1954-1963，构造 `{op_name, callable_target, _fallback}`）——
  比 A3 旧代码好（A3 旧代码直接 halt）。
- **缺口**：manifest 在但 `callable_target` 缺（L1968-1982）仍 **halt**（`reason=callable_target_missing`），
  与 A3 旧代码同病。即"plugin 正确、manifest 漏 callable_target"在 A5 仍会 halt。

## 建议同事做的事（收敛到同一 helper，消除 §2.5 分歧）

A3 侧已提取共享 helper `_ensure_manifest_callable_target` + `_missing_required_manifest_fields` +
`_warn_manifest_extra_fields` + `_artifact_retry`（均在 `CodegenStage`，A5 可直接复用）。建议：

1. 把 `_transition_regbase_s5` 的 inline 派生（L1954-1963）+ `callable_target_missing` halt（L1968-1982）
   替换为调用 `_ensure_manifest_callable_target` + `_missing_required_manifest_fields` + `_artifact_retry`
   （与 A3 `_transition_membase` 同一通路）。
2. regbase 的 manifest 产出 skill（`ascendc-op-dev-coding-regbase/SKILL.md`）**已有** symbol 一致性规则
   （L350-351），可补维8 自检 + 内联 JSON 模板（对齐 A3 的 `ascendc-op-dev-coding/SKILL.md`）。

## 不属于本 handoff 的（A3 侧已完成，无需同事动作）

- A3 membase 派生/校验/retry/skill/docstring：已实施 + UT/ST 验证（UT 3541 pass / ST 非-heavy 123 pass）。
- `codegen_artifact_retries`/`codegen_artifact_feedback` State 字段 + `codegen.artifact_max_retries` 配置：
  A5/regbase 共用（已加进 `from_snapshot` 注册 + `rerun_reset_fields`）。
