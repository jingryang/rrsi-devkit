# L4 实施方案 — CodegenStage Mixin 拆分（刀序执行记录）

- 层级：**L4 / 实施方案**。具体改哪个函数、什么顺序、怎么验证。
- 上游：`02-analysis.md`（L3 已拍板 Mixin 族方案）；`01-problems.md` P1。
- 状态：**刀 1-5 全部完成**（2026-09-08/09）。全量 UT 回归绿，收尾完成（2026-09-09）。

## 目标形态

`stages/codegen.py`（仅留编排壳）+ `stages/codegen_stage_mixin/` 子包：

| 文件 | 承载 | 状态 |
|---|---|---|
| `codegen.py` | `CodegenStage` 编排壳（`transition`/`_transition_membase`/`rerun_reset_*`/`_bash`）+ 模块级函数 `classify_smoke_failure_phase` | **刀1-5后 726 行** |
| `codegen_stage_mixin/__init__.py` | 包标记（空） | 已建 |
| `codegen_stage_mixin/regbase.py` | `RegbaseMixin`（27 方法 + `ERROR_WEIGHTS`/`RETRY_LIMITS`/`_FakeAgentResult` 常量迁入） | **刀1完成** |
| `codegen_stage_mixin/contract.py` | `ContractMixin`（契石门 30 方法 + `_scalar_contract_violations` 壳 + 模块级 `_first_host_roundtrip`/`_registrations_from_artifacts`/`_validate_scalar_contract` + `_SCALAR_*`/`_OP_ADD_RE`/`_LAUNCHER_LIST_RE`/`_HOST_ROUNDTRIP_RE`/`_TORCH_LIBRARY_FRAGMENT_RE`/`_SMOKE_OWNERSHIP_HOST_RETRY_BEFORE_DECLINE`） | **刀2完成** |
| `codegen_stage_mixin/feedback.py` | `FeedbackMixin`（反馈/retry 22 方法 + `_SMOKE_MARKER_RE` 类常量 + `_SMOKE_ERROR_STOP_LOSS_STREAK` 模块常量） | **刀3完成** |
| `codegen_stage_mixin/deploy.py` | `DeployMixin`（`_read_deploy_result`/`_persist_sources`） | **刀4完成** |
| `codegen_stage_mixin/prompt.py` | `PromptMixin`（`actions`/`_actions_membase`/`_materialize_inputs`/`_programming_model_for`/`_build_codegen_prompt` + `_json_text`） | **刀5完成** |

`CodegenStage(RegbaseMixin, ContractMixin, FeedbackMixin, DeployMixin, PromptMixin, Stage)` 多继承串联——**mixin 必须排在 `Stage` 之前**（否则 MRO 中 `StageProtocol` 的 abstractmethod 遮蔽 mixin concrete，实例化报 `TypeError: Can't instantiate abstract class`）。

## 每刀配方与验证

### 刀 1（已完成）：regbase mixin

- 方法级逐条切割（AST 行区间），27 方法迁至 `regbase.py`。
- 跟随修正：
  - `ERROR_WEIGHTS` / `RETRY_LIMITS` / `_FakeAgentResult` 迁入 `regbase.py`（仅 regbase 方法使用；测试虽 import 但**未实际使用**，未破坏 import 面）。
  - `_regbase_skill_root` 的 `devkit_root = Path(__file__)...parent` 从 5 层改为 **6 层**（新文件在 `stages/codegen_stage_mixin/` 子目录，深一层）。
- 验证：regbase 簇 100 例全绿 → codegen 全簇 **524 passed**。

### 刀 2：契石门 mixin（已完成）

- 迁出方法（29）：
  `input_contract` / `output_contract` / `artifact_contract` / `_expected_code_files` / `validate_inputs` /
  `_check_section_dirs_have_files` / `_profile_scaffolding_kind` / `_required_codegen_sections` /
  `_plugin_sources` / `_resolve_torch_registration` / `_torch_plugin_contract_error` /
  `_plugin_host_offload_error` / `_aicore_registration_mismatch_error` / `_code_path_has_source_files` /
  `_update_meta_retries` / `_return_verdict` / `_plugin_return_schema_mismatch` / `_read_smoke_ownership` /
  `_ownership_honored` / `_classify_smoke_schema_mismatch` / `_warn_manifest_name_drift` /
  `_check_plugin_schema_consistency` / `_check_opdef_optional_output` / `_inject_scaffolding_kind` /
  `_ensure_manifest_callable_target` / `_missing_required_manifest_fields` / `_warn_manifest_extra_fields` /
  `_scaffold_contract_summary` / `_emit_domain_gap_signal`
- 跟随修正：
  - 模块级 `_first_host_roundtrip` / `_registrations_from_artifacts` / `_OP_ADD_RE` / `_LAUNCHER_LIST_RE` /
    `_HOST_ROUNDTRIP_RE` / `_TORCH_LIBRARY_FRAGMENT_RE` / `_SMOKE_OWNERSHIP_HOST_RETRY_BEFORE_DECLINE` 随迁。
  - `_expected_code_files` 被 `integrate.py:97` 调用（原样在 mixin 上，无需动作）。
- 验证：契约簇 **83 passed**（MRO 修复后）。

### 刀 3：反馈渲染 mixin（已完成）

- 迁出方法（22）：`_render_retry_resume_prompt` / `_build_retry_limit` / `_collect_build_feedback` /
  `_artifact_retry_limit` / `_collect_artifact_feedback` / `_artifact_retry` / `_is_manifest_exhausted_halt` /
  `is_satisfied` / `stop_in_stage_retry` / `_collect_schema_feedback` / `_plugin_schema_retry` /
  `_first_smoke_error_line` / `_smoke_last_marker` / `_smoke_facts` / `_render_smoke_facts_lines` /
  `_collect_smoke_host_feedback` / `_collect_smoke_owner_judge_feedback` / `_collect_smoke_feedback` /
  `_smoke_retry` / `_smoke_error_signature` / `_render_build_feedback_section` / `_render_artifact_feedback_section`
- 跟随修正：`_SMOKE_MARKER_RE` 类常量随迁；`_SMOKE_ERROR_STOP_LOSS_STREAK = 3` 模块常量迁入（codegen.py 原定义删除，不再重复）。
- 验证：反馈簇 **108 passed**（`--no-env-check`）。

### 刀 4：部署 mixin（已完成）

- 迁出方法（2）：`_read_deploy_result` / `_persist_sources`。
- 跟随修正：`deploy.py` 补 `import json` + `DeployResult` import。
- 验证：`CodegenStage._persist_sources → DeployMixin._persist_sources` 解析验证。

### 刀 5：prompt 组装 mixin（已完成）

- 迁出方法（5）：`actions` / `_actions_membase` / `_materialize_inputs` / `_programming_model_for` / `_build_codegen_prompt`。
- 跟随修正：
  - 模块级 `_json_text` 迁入 prompt.py（`_materialize_inputs` 消费端）；`_validate_scalar_contract` + `_SCALAR_USAGE_EXEMPT`/`_SCALAR_TOKENS` **最终落于 contract.py**（scalar 契约归契约 mixin 域，测试 import 面 `test_codegen_scalar_contract.py` 改指 `codegen_stage_mixin.contract`）。
  - `_transition_membase` 的 scalar 门内联判定抽成 `ContractMixin._scalar_contract_violations`（契石门判定归契约 mixin；`_plugin_schema_retry` 在 feedback mixin 经 MRO 可达）。
  - `ERROR_WEIGHTS`/`RETRY_LIMITS`/`_FakeAgentResult` 死定义从编排壳删除（定义与使用全在 regbase.py）；测试 import 面改指 `codegen_stage_mixin.regbase`。
  - 编排壳死 import 清理：`namedtuple`（常量迁走）、顶层 `shutil`（仅局部 import 遮蔽内使用）、`re`（仅注释提及）。
- 验证：scalar 契约簇 13 + smoke backstop 21 + test_stages **216 passed**。

### 收尾（已完成）

- **修复重建残留**：contract.py 曾经历一次重建（DAMAGE 后从 `git show HEAD:...codegen.py` 还原），重建时 AST 行号从 `def` 行起、**漏掉 `@staticmethod` 装饰器行**，且多方法粘连单行（`return ...def ...` 同行）导致语法错。逐处修复：
  - 9 个契约方法补回 `@staticmethod`：`_expected_code_files` / `_profile_scaffolding_kind` / `_plugin_sources` / `_code_path_has_source_files` / `_update_meta_retries` / `_return_verdict` / `_read_smoke_ownership` / `_ownership_honored` / `_classify_smoke_schema_mismatch`。
  - 拆分 5 处「方法粘连单行」（`_code_path_has_source_files`↔`_update_meta_retries`、`_read_smoke_ownership`↔`_ownership_honored`、`_return_verdict`↔`_plugin_return_schema_mismatch`、`_check_section_dirs_have_files`↔`validate_inputs`、`_profile_scaffolding_kind`↔`_required_codegen_sections`、`_plugin_sources`↔`_resolve_torch_registration`、`_classify_smoke_schema_mismatch`↔`_warn_manifest_name_drift`）。
  - 删除 `_aicore_registration_mismatch_error` 的重复定义（重建时文件被二次写入产生，两份 body 逐字节一致，last-def-wins 遮蔽前者）。
- 验证：契约簇 + 编排簇 + duplicate_defs/import_guard **全绿** → 全量 UT **4303 passed / 0 failed**（2026-09-09，`--no-env-check`）。VT 边界修复（`_first_vt_in_group` 步骤列去 `4.` 前缀，commit `23a4ae60`）的 9 例标定测试 + 带前缀表兼容用例守护（24 passed）见 `docs/plan/codegen-regbase-vt-boundary-gap/01-problems.md`（L1）。

## 公共 API 不变核对清单

- `registry.py:32` `from stages.codegen import CodegenStage` ✓（未动）
- `integrate.py:96-97` `CodegenStage._expected_code_files(state)` ✓（ContractMixin 上可达）
- `precision_debug_substages.py:1341` `from stages.codegen import classify_smoke_failure_phase` ✓（模块级函数留在编排壳）
- `test_codegen_output_paths.py` `inspect.getsource(codegen)` 断言（内容守卫，不依赖类方法归属）✓
- 测试全部经 `from stages.codegen import CodegenStage` 取类 ✓

## 已修正的迁移陷阱记录

| 陷阱 | 现象 | 处置 |
|---|---|---|
| 范围过大 | 首刀误把 10 个契石门方法（`_check_section_dirs`~`_update_meta_retries` 沿线）切入 regbase | git checkout 回滚，AST 方法级重切 |
| 模块级常量缺失 | `NameError: RETRY_LIMITS` | `ERROR_WEIGHTS`/`RETRY_LIMITS`/`_FakeAgentResult` 迁入 regbase.py |
| `__file__` 深度 | `_regbase_skill_root` 5 层 parent 指向 `src/` 而非仓库根 | 改为 6 层（新文件深一层的子目录） |
| MRO 顺序 | `(Stage, RegbaseMixin, ...)` 实例化 `TypeError: Can't instantiate abstract class`（`StageProtocol` 的 abstractmethod 遮蔽 mixin concrete） | **mixin-first**：`(RegbaseMixin, ..., Stage)` |
| 模块级函数缺失 | 契石门方法引用 `_first_host_roundtrip`/`_registrations_from_artifacts` → NameError | `git show HEAD:...codegen.py` 提取原文本迁入 contract.py |
| 死 import | 刀5 后 `Action`/`STAGE_SKILL_MAP`/`re` 等仅被迁走的 prompt 域使用 | 从编排壳删除（`re` 仅注释提及，误判为使用后确认删） |
| 内联判定抽壳 | scalar 门判定留在 `_transition_membase` 引用已迁出的模块级函数 → NameError | 抽成 `ContractMixin._scalar_contract_violations`，shell 调 `self.` |
| 死定义 | `ERROR_WEIGHTS`/`RETRY_LIMITS`/`_FakeAgentResult` 在编排壳有定义但无使用 | 删定义，测试 import 面改指 regbase.py（§1.4 不留兼容层） |
| 重建丢失 `@staticmethod` | AST 提取方法文本从 `def` 行号起，`@staticmethod` 装饰器行在前一行被漏掉 → `TypeError: ... takes 1 positional argument but 2 were given`（prompt.py `_expected_code_files` 消费端） | 从 HEAD 提取含装饰器定义逐方法补回；校验全文件无重复装饰器 |
| 重建方法粘连单行 | 多个方法尾行与下个方法 `def` 粘连同一行（`return results    def validate_inputs(...)`）→ 语法错 | grep `^\s{0,8}(\}|return).*(def )` 扫描，逐处拆行 |
| 重建重复定义 | `_aicore_registration_mismatch_error` 定义两份（body 逐字节一致）→ duplicate_defs_guard 拦 | 删靠前一份，保留靠后（last-def-wins 一致） |