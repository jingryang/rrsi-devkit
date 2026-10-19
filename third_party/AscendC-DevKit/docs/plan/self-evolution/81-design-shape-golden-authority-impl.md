# step-81 — design input shape 契约（需求描述权威 + golden cross-check）— L4 实施方案

> 性质：self-evolution 线 L4，step 81。修 P121（design 流程 input shape 无权威源）。
> 纪律：TDD（§3.1）；全覆盖（§3.2 UT 全绿）；符号级落点 + producer 自检（§2.9）。
> 承接：P119/P120（design 段产物质量）/ step-60（设计门不 halt，shape 不确定问人）/ §2.9（构造性保证 > 检查门）。
> 触发：batch `20260728-134831-ccda3b/9d6e61` advance_step_v2 precision_debug halt（`aclnn input_tokens is null` EZ1001）。

---

## 0. 实施总览

| slice | 内容 | 状态 |
|---|---|---|
| S1-物化 | req-analysis `_materialize_inputs` 物化 golden.py + `input_contract.requires` 加 golden_path + prompt 点名 | ✅ |
| S1-校验 | `_validate_golden_alignment` validator（拒 pending/畸形）+ `golden_alignment` 进 required_keys（与 mutation_mode 平行）+ schema example | ✅ |
| S1-SKILL | SKILL.md golden 段补 shape_equiv_golden 自检 + checklist 项 | ✅ |
| S2 | integrate `_reconcile_shape_ranks` producer shape-rank 保留性自检 + 接入 transition | ✅ |

S1 是真根因修复（物化 golden.py = agent 终于能读 → 产 pass，pending 自然消失；validator 兜残余）。S2 是 producer 自检兜 mid-chain LLM 漂移（§2.9）。validate GV11 gate 经审计判 §2.9 冗余 + 需 plumbing，**丢弃**（用户决策）。

> **实施完成（2026-07-29）**：S1+S2 全绿。UT 全量 **3186 passed / 7 skipped**（较 step-80 baseline 3170 +16 = 新增 13 golden + 3 S2，零连带回归）。heavy_llm e2e 待用户确认（§3.11）。

---

## 1. S1-物化 — req-analysis 收 golden.py（真根因）

文件 `src/ascendc_devkit/orchestration/stages/requirement.py`。

- `input_contract.requires` 加 `golden_path`（:37）：契约诚实 + early validation（§1.3：golden 缺失 preflight 早炸，非静默瞎猜 shape）。**零影响论证**：triple 校验 `if "golden_path" in candidates`（dispatcher.py:226，`candidates = required_by_stages & _USER_INPUT_FIELDS`）——三含 requirement 的 workflow（generate_ascendc/SE/self_evolve_op）全经 `_design_root` 挂 general-design（早已 requires golden_path），golden_path 本就在 candidates、triple 早触发、batch 早提供完整三件套（batch_self_evolve.sh:243-245）；req-analysis 加 requires 不改 candidates、不新触发 triple。
- `_materialize_inputs`（:127-145）加 golden.py 物化块：镜像 `reference_code` 文件拷贝（单 `Path`，非 dict）。`if state.golden_path and state.golden_path.exists(): (wd/"golden.py").write_text(...)`。
- `_build_analysis_prompt` 加 "## Golden 参考实现" 段点名 golden.py + shape rank 引导（镜像 requirement_doc.md 点名写法，不注入内容）。
- 依据：SKILL.md:175-198 早要求 agent 读 golden.py 做 math-equiv，但工程层从不物化 → agent 找不到 → 猜 shape（advance_step_v2 真根因）。golden_path 是 CLI `--golden` 注入的 State 字段（state.py:141），早于一切 stage 就位。

## 2. S1-校验 — golden_alignment required_keys + validator（与 mutation_mode 平行）

- `schema/requirement.json`：`golden_alignment` 加入 `required_keys`（presence；ArtifactContract.parse 的 required_keys 检查兜缺失 → schema_violation）+ `example` 补 golden_alignment 示例。
- 新增 `_validate_golden_alignment(req_data)`（镜像 `_validate_mutation_mode_consistency` 范式 :346，**presence+校验器双保险与 mutation_mode 平行**）：从 raw parsed 读 `golden_alignment`——缺失/None → defer（required_keys 兜，不重复报）；非 dict 畸形值 → 报；`status="pending"`（未检）/ 非 pass|diff → 报，强制重试让 agent 真读 golden.py 做 shape_equiv。接入 `transition` parse 后（:247 旁，早于 `OperatorSpec.from_dict` :267 丢弃未知键）。
- **四把尺子（§1.2）选 required_keys + validator，否决 validator-only**：可维护（与兄弟字段 mutation_mode 的 presence+校验器范式一致）、可扩展（漏写/错值都自动归位）、可诊断（漏字段 req-analysis 当场报，不推迟到下游 precision 才炸）、架构合理（完整契约）。曾考虑 validator-only 省 fixture 改动，但判为 §1.2「为了省事采用规避方案」否决——fixture 改动是正确修复的合理成本（test_stages 9 处 + proto/design_target 用 `_with_golden_alignment` helper 包装，DRY）。

## 3. S1-SKILL — shape_equiv_golden 显式自检

文件 `.claude/skills/ascendc-op-req-analysis/SKILL.md` golden 段（:175-198 后）。

- 新增 **shape 对齐自检（shape_equiv_golden，必做）**：**需求描述是 shape 权威**（正常开发 shape 在需求描述里；cases 是从需求描述派生的下游产物、非 shape 源，cann-bench cases-first 是异常、框架不耦合非常态）。agent 先从需求描述提取 rank，golden.py 作 cross-check 旁证（`x[:n]`→1D；`view(-1,k)` 内部 reshape 不改 input rank）；**不符时 golden 明确指示且需求描述残缺→以 golden 修正，否则（golden 也判断不了/与明确需求描述冲突）→ resolve_ambiguity 问人，不自动用 golden 覆盖 doc**。golden_alignment.status 仅 pass|diff。
- checklist 加 "inputs[*].shape rank 与 golden 一致已验证" 项。

## 4. S2 — integrate producer shape-rank 保留性自检（§2.9）

文件 `src/ascendc_devkit/orchestration/stages/design_substages.py`。

- 新增模块级 `_reconcile_shape_ranks(design_spec, requirement)`（紧随 `_route_scalar_params` :1822）：建 requirement.op_spec inputs/outputs 的 name→shape 权威表；对 design_spec inputs/outputs 按 name 比 `len(shape)`，不符 → 以 requirement 为准 `item["shape"] = list(req_shape)`（确定性修正）+ 返回修正项。requirement None/无 op_spec/无 auth → 跳过（不崩）。
- 接入 `IntegrateStage.transition`（`_route_scalar_params` 后，:1694）：修正非空 → `Logger.warn`（mid-chain LLM 漂移可观测）。
- producer 自检（非下游门）：发现即修到权威源（requirement），§2.9 自洽，不 halt/loopback。内部 tiling reshape 在 tiling_results 不在 design_spec.inputs，故对齐 IO rank 正确。

## 5. 测试（TDD，纯逻辑 UT §3.8）

- `tests/ut/orchestration/test_requirement_golden.py`（新建，13 用例）：
  - 物化：`test_materialize_writes_golden_py_when_present` / `_preserves_golden_content_verbatim`；prompt：`test_prompt_names_golden_py_when_present` / `_omits_golden_section_when_absent`。
  - validator：`rejects_pending` / `accepts_pass` / `accepts_diff` / `rejects_bogus_status` / `none_and_missing_deferred_to_required_keys` / `non_dict_value_rejected`。
  - transition：`rejects_pending_golden_alignment` / `missing_golden_alignment_schema_violation`（required_keys 兜 presence）/ `accepts_pass_golden_alignment`。
- `tests/ut/orchestration/test_design_substages.py`（+3 用例）：`test_integrate_reconciles_drifted_shape_rank`（2D→1D 修正）/ `_preserves_matching_shape_rank`（一致不动）/ `_reconcile_skips_when_no_requirement`（无权威不崩）。
- 回归：现有 req-analysis/integrate UT 行为不变；required_keys 加严 → test_stages 9 处 + proto/design_target requirement.json fixture 用 `_with_golden_alignment` helper 包装补 golden_alignment。

## 6. 验证

- **即时逻辑（零 token）**：advance_step_v2 `golden.py`（`input_tokens[:num_seqs]`+`view(-1,token_each_reqs)`）→ LLM 能推断 rank 1（shape_equiv 自检引导）。
- **UT 全量 3186 passed / 7 skipped**（197.87s），零连带回归。
- **heavy_llm（§3.11）**：
  - **golden_alignment 强制 e2e — ✅ PASS**（`test_req_analysis_selfclosure`，真 glm-5.2 网关：agent 产带 golden_alignment 的 requirement.json、过 required_keys、mutation_mode 自洽、不产旧 op_spec.json）。证 required_keys+校验器强制在真 LLM 全流程下工作。**reframe（shape 权威由 golden → 需求描述 + golden 旁证）后复跑仍 PASS（231s）**——证文案 reframe 未破坏 e2e（初始 448s）。
  - **shape-rank 推断（advance_step_v2 真根因）— ⚠️ 未覆盖，留待下一新算子**：该测试用 `add`（shape 平凡无歧义）不验证 1D-vs-2D 推断；advance_step_v2 既有 req-analysis 已 completed（resume 不重跑）→ 真根因 e2e 最干净验证是下一含 shape 漂移的新算子（req-analysis 物化 golden → 推 input_tokens rank 1 → design_spec 1D → codegen op_plugin 接受 1D → 不再 EZ1001 halt）。

## 7. scope 边界（不做）

- 不加 validate GV11 gate / 不改 gate_scope.json / 不动 ValidateStage（§2.9 冗余 + 避免 plumbing；shape 保留性自检放 producer integrate）。
- golden_alignment **进 required_keys**（与 mutation_mode 平行：presence + 校验器双保险；四把尺子论证见 §2）。
- 不动 proto.yaml（cann-bench task 源，非本仓）；不做 codegen 兜底；shape 不确定问人（step-60「设计门不 halt」）。
- **shape 权威 = 需求描述**（正常开发 shape 在此）；golden 作 cross-check 旁证；**cases 是 cann-bench 异常 fixture（cases-first 倒置），框架不消费、不耦合非常态**。entry/input_type 另两件只给精度路径消费。
