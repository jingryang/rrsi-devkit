# A5 Precision Debug 编排层重构 — L1 问题记录

> 层级：L1（事实快照，不提方案、不排顺序、不写决策）  
> 日期：2026-08-01  
> 代码基线：`80af908e`（2026-07-30）

---

## P1. 单文件巨石，认知负担高、改动易冲突

**事实**：
- `src/ascendc_devkit/orchestration/stages/precision_debug_a5.py` = **1895 行**。
- 单文件内含：6 个 Substage 类（`InitBaseline`/`PipelineSync`/`DumpDebug`/`VfTest`/`VectorErrorDebug`/`Finalize`）+ 全部 checkpoint I/O 函数（`_load_a5_checkpoint`/`_save_a5_checkpoint`/`_validate_a5_checkpoint`/`_restore_framework_routing_fields`/`_load_expected_loop_result`）+ best_snapshot 合并逻辑（`_snapshot_better`/`_merge_best_snapshot`/`_build_snapshot_from_result`/`_has_valid_numeric_result`/`_commit_modified_numeric_phase`）+ 提取器（`_extract_max_diff`/`_extract_passed_count`/`_extract_total_count`/`_extract_failed_cases`/`_extract_error_type`/`_extract_vector_error_evidence`/`_record_phase_error`）+ converge（`_a5_sync_debug_result`/`_converge_a5_to_best_commit`）+ 转移表 `_A5_TRANSITION_TABLE`。
- 对比 A3：`precision_debug_substages.py` = 2790 行但含 8 个 substage + abort annealing + time budget + bounds_check + scope_guard，密度更高但分属不同职责。
- git blame 显示该文件近 10 次提交（`b51317dd`→`4fdd7ffa`）每次都改动跨多职责区块，冲突概率高。

**凭什么这么说**：`wc -l` + `grep "^class \|^def "` 实测。

---

## P2. 无 per-case 维度，框架无法控进度、无法判定单 case 止损

**事实**：
- A5 的 `dump_debug`/`vf_test` 收到的 `failing_cases` 是一个 **list**（见 `DumpDebugSubstage._extract_loop_info` 第 1166-1169 行：`failing_cases = snap.get("failed_cases") ... or cp.get("baseline_failed_cases", [])`），prompt 把整个 list 注入（第 1188-1191 行拼成 `failing_summary` 取前 10 个）。
- **没有** `current_case_index`、**没有** per-case `attempt_count`、**没有** per-case `status`（pending/debugging/resolved/skipped）、**没有** per-case stop-loss。
- 对比 A3：A3 有完整的 case queue 状态机（`_CONTROL_DEFAULTS` 含 `current_case_index`/`max_attempts_per_case`/`failed_case_queue[].status`/`_advance_current_case`/`_advance_past_failure_type`，见 `precision_debug_substages.py` 第 280-560 行）。
- A5 的 `best_snapshot.failed_cases` 是**全量回归视角**（每次全跑后的失败集），不是**调试进度视角**——它递减反映"总共还剩几个失败"，但不追踪"当前在调哪个、调了几轮"。

**后果**：
- Agent 看到一坨失败用例，要么全跑、要么自己挑哪个调——框架无法控进度。
- 无法判定"这个 case 调不动了该跳"——只能靠 `max_dump_rounds`/`max_vf_rounds` 的阶段级总轮数兜底，一个难 case 烧光预算后其余 case 无机会。
- 进度不可观测：checkpoint 的 `history` 只记阶段轮次（`{"phase":"dump_debug","round":1,...}`），无 per-case 维度。

**凭什么这么说**：grep `current_case_index`/`attempt_count`/`case.*status` 在 `precision_debug_a5.py` 中 0 命中；A3 同名字段在 `precision_debug_substages.py` 中 30+ 命中。

---

## P3. agent prompt 混入框架实现细节，违反 §2.7/§2.8

**事实**：
- `_A5PrecisionDebugSubstage.actions` 在每个 phase 的 prompt 末尾统一追加 ~7 行「checkpoint 写入边界」硬编码字符串（第 773-779 行）：
  ```python
  prompt += (
      "\n\n## checkpoint 写入边界（强制）\n"
      "你只允许写本 phase 的 result JSON；仅在本 phase 明确允许且有"
      "有效数值结果时，可原子更新 checkpoint.json.best_snapshot。"
      "禁止修改 checkpoint.json 的 status、phase、任何 *_round、"
      "任何 *_status、history；这些字段只由框架 transition 维护。"
  )
  ```
  这段内容与 `.claude/agents/ascendc-precision-*.md` 的 `## Orchestration Contract` **You must NOT** 段完全重复。
- `VectorErrorDebugSubstage._phase_prompt` 达 **~95 行**（第 1582-1675 行），内含：
  - P1/P2/P3 guard 层的完整流程指令（第 1621-1653 行，~33 行）——这些是 skill 的 workflow 内容（§2.8），应在 SKILL.md 而非 prompt。
  - 16 个 `a5_*_script`/`a5_*_output` 路径参数（第 1606-1617 行）——脚本路径是 skill 的资源（§2.2），应由 skill 自解析或用相对路径，不该由框架拼绝对路径注入。
  - 完整的 result JSON schema 字段列表（第 1658-1667 行，~10 行）——schema 应在 skill 的 `schema/` 目录（§2.2），不该内联进 prompt。
- 其他 phase 的 `_phase_prompt` 同样把参数列表（operator_dir/checkpoint_path/skill_dir/op_name/build_command/test_command/device_id/deploy_*/cases_csv/golden_module/record_dir/debug_dir）逐行 f-string 拼接，每个 phase 重复一遍（~15 行 × 5 phase = ~75 行重复）。

**凭什么这么说**：读 `precision_debug_a5.py` 第 773-779、1582-1675 行；对比 `.claude/agents/ascendc-precision-vector-error-debug.md` 的 Contract 段。

---

## P4. 过渡态字段穿透到 checkpoint.json（持久化污染）

**事实**：
- `_restore_framework_routing_fields` 在 checkpoint 里写入 `_framework_previous_best_snapshot` 键（第 170 行：`cp["_framework_previous_best_snapshot"] = previous.get("best_snapshot")`），用于后续 `_merge_best_snapshot` 比较。该键在 `transition()` 末尾 `cp.pop("_framework_previous_best_snapshot", None)` 清除（各 substage transition 末尾均有）。
- 但在 `_load_expected_loop_result` 抛异常的路径（第 194、203、210 行），**先 pop 再 save**；在正常路径则在各 transition 内 pop。**问题**：`_save_a5_checkpoint` 在 `_load_expected_loop_result` 内部被调（第 195 行，异常路径），此刻 pop 已执行所以无污染；但若 transition 在 pop **之前**因任何原因被中断（如进程强杀），该键会残留在 checkpoint.json 落盘。
- `_commit_modified_numeric_phase` 在 phase_result 上写 `_framework_reject_snapshot` 键（第 441、463 行），该键随后被 `_merge_best_snapshot` 读取（第 306 行：`phase_result.pop("_framework_reject_snapshot", False)`）并 pop。但 phase_result 来自磁盘 JSON（`_load_expected_loop_result` 读 `*_result.json`），若 agent 已落盘该 result 文件，框架写入的 `_framework_reject_snapshot` 不会回写磁盘（phase_result 是内存 dict），**但语义上框架内部标记混入了 phase 产物 dict**，调试时易混淆。
- `best_commit` 同时存在于三处：`checkpoint.best_commit`、`checkpoint.best_snapshot.commit`、`phase_result.best_commit`。`_merge_best_snapshot` 第 341-342 行强制 `candidate["commit"] = result_snap.get("commit", "")`，而 `_commit_modified_numeric_phase` 第 465 行 `phase_result["best_commit"] = commit`（框架生成），但第 433 行 `phase_result.pop("best_commit", None)` 先删 agent 自报——说明真相是框架生成的 commit，但**三个位置都可能不同步**，靠多处 pop/overwrite 维持一致性，脆弱。

**凭什么这么说**：grep `_framework_previous_best_snapshot`/`_framework_reject_snapshot` 在 `precision_debug_a5.py` 中分别 10/4 命中。

---

## P5. helper 函数重复定义、文件归属混乱

**事实**：
- `_operator_dir(state)` 在三处重复定义：
  - `precision_debug_a5.py` 第 66-72 行
  - `precision_debug_a5_git.py` 第 29-36 行
  - `precision_debug_substages.py` 第 105-111 行（A3 同名函数）
  三份实现等价（`state.op_dir` 优先，`op_identity.op_dir` 兜底），但分别独立维护。
- A5 的 Git 安全逻辑在独立文件 `precision_debug_a5_git.py`（355 行），但**被 `precision_debug_a5.py` 用函数内 import 调用**（第 767-769 行 `from ascendc_devkit.orchestration.precision_debug_a5_git import ensure_entry_snapshot`，第 445-447 行 `from ... import commit_operator_phase`，第 652-654 行 `from ... import validated_rollback_anchor`），原因是「打破循环依赖」（见 `_converge_precision_debug` 注释 `graph_executor.py` 第 161 行）。但 `precision_debug_a5_git` 并不被 `graph_executor` 直接 import，这个循环依赖论证是否成立存疑。
- `vector_error_evidence.py`（468 行）是纯函数模块（无 state 循环依赖风险），却被放在 `orchestration/` 根而非 `stages/` 子目录，与 `precision_debug_a5.py` 同级——归属不一致。
- `_extract_max_diff`/`_extract_passed_count`/`_extract_total_count`/`_extract_failed_cases`（第 468-506 行）是一组从异构 phase_result schema 提取数值的 helper，与 best_snapshot 逻辑强耦合但散落在文件中部，无内聚边界。

**凭什么这么说**：`grep -n "_operator_dir" src/ascendc_devkit/orchestration/` 实测 3 处定义。

---

## P6. `_common_context` 与 `_phase_prompt` 参数拼装重复且不可扩展

**事实**：
- `_common_context`（第 730-761 行）产出 16 键 dict，各 phase 的 `_phase_prompt` 再从中逐键取值拼成 `- key: {ctx['key']}` 格式字符串。每个 phase 重复拼 ~10-15 行参数段。
- 新增一个上下文参数（如 per-case 的 `current_case`）需要：(1) `_common_context` 加键；(2) 每个 phase 的 `_phase_prompt` 加一行 f-string。改动面 = N（phase 数）+ 1，违反开闭原则。
- 参数拼装与 phase 职责描述混在同一个 `_phase_prompt` 方法里，无法单独测试参数组装逻辑。

**凭什么这么说**：对比 6 个 substage 的 `_phase_prompt`，参数段高度雷同（operator_dir/checkpoint_path/skill_dir/op_name/build_command/test_command/record_dir/debug_dir 在每个 phase 都出现）。

---

## P7. op_plugin_debug 无移交 kernel_debug 的出口，适配层误判时流程必死或空转

**事实**：
- `op_plugin_debug` 阶段只有三个出口：`converged → baseline`、`retry → 自循环`、`exhausted → __escalate__:exhausted`（`transition_table.py` `_A5_TRANSITION_TABLE["op_plugin_debug"]`）。
- 当 op_plugin agent 逐项排查确认**适配层不是根因**（注册/签名/dtype/shape/attr/tiling 映射全部一致、KL 与 op_plugin 传参无差异），或已修好适配层后，残余失败 case 在 **run-cases 与 KernelLaunch 下都失败**（即真实问题在 kernel/tiling 层）时，没有任何诚实出口：
  - 报 `retry` → 自循环烧光 `max_op_plugin_rounds` 后被钳为 `exhausted` → escalate 杀死整个 precision_debug 流程，即使 kernel_debug 本来可以修好；
  - 报 `converged`（RC/KL 一致但都失败）→ 回 baseline 全量重跑重新交叉对比才进 kernel_debug——绕一圈且不携带 op_plugin agent 已排查完适配层的证据。
- 真实案例：baseline 把某 case 标 `error_layer=op_plugin`（RC fail + KL pass），实际是 KL 脚本用了不触发 kernel bug 的简化参数，真实参数经 run-cases 暴露 kernel 层缺陷。op_plugin 层排查无果后只能 retry→exhausted，流程死亡。

**凭什么这么说**：读 `transition_table.py` `_A5_TRANSITION_TABLE["op_plugin_debug"]`（仅 converged/retry/exhausted 三出口）；`base.py` `_KNOWN_STATUS_VALUES_BY_PHASE["op_plugin_debug"] = {converged, retry, exhausted}`（第四值 `need_kernel_debug` 不在已知集）。

---

## P8. 各阶段结论无跨阶段接力文件，下游 agent 难以看到上游排查结论

**事实**：
- A5 precision_debug 的 6 个阶段（baseline / kernel_debug / vf_test / vector_error_debug / op_plugin_debug / regression）各自把结果写入 `{debug_dir}/{phase_dir}/*_result.json`，但**没有共享的结论接力文件**：每个阶段只读特定上游文件（如 kernel_debug 只读 `baseline_result.json`），无法看到流程中其他 agent 的一段落结论。
- 结论性信息（`root_cause` / `fix_summary` / `diff_analysis` / `dump_evidence`）散落在各阶段自己的 result JSON 里，字段名不统一（有的叫 `fix_summary`、有的叫 `root_cause`、有的叫 `diff_analysis`），下游 agent 需逐个翻文件才能拼出"流程到哪了、发现了什么"。
- A3 流程有 `_summary → history`（agent 写 `_summary` 到自己的 phase JSON，框架物化进 control.json `history`）供跨阶段可见；A5 无等价物。
- 对比：`checkpoint.json.history` 只记 `{"phase", "round", "debug_status"}` 状态值，不含自然语言结论。

**凭什么这么说**：grep `conclusions` 在 `src/ascendc_devkit/orchestration/stages/precision_debug_a5/` 中 0 命中；读 6 个 A5 skill 的 result JSON schema，结论性字段名不统一；`checkpoint.py` `_A5_CONTROL_DEFAULTS["history"]` 只存状态值。

---

## P9. failed_case_queue 的 max_diff 字段冻结在 baseline，迭代后注入块展示过时值误导 agent

**事实**：
- `failed_case_queue[i].max_diff_rc / max_diff_kl` 在 baseline transition 建队列时写入一次，之后**没有任何阶段回写**（kernel_debug / regression / vf_test / vector_error_debug 的 transition 只改 `status` / `attempt_count` / `current_case_index`）。
- 注入每个 phase prompt 的「当前待处理 case」块直接渲染 `queue[current]` 的 `max_diff_rc` / `max_diff_kl`。修复后这些值仍是 baseline 冻结值。
- 真实轨迹（group_norm batch 20260806_154927，2026-08-07）：`kernel_debug_round_1_result.json` `verification.after_max_diff_kl = 0.0009765625`（已修复、KL 通过），但 queue case 1 仍显示 `max_diff_kl = 65506.017578125`；regression round 1 注入块原样展示 65506，会误导 agent 认为修复未生效。
- `best_snapshot`（baseline/regression 全量高水位）不涉及 per-case 的 queue 回写，两者数据源不同。

**凭什么这么说**：读 6 个 A5 transition（kernel_debug.py / regression.py / vf_test.py / vector_error_debug.py / op_plugin_debug.py / baseline.py）对 `failed_case_queue[i]` 的写操作——仅 `status`/`attempt_count`/`error_layer`(handoff)；读 trace viewer 最新两条 regression 轨迹的 checkpoint + kernel_debug result。

## P10. dump_evidence 历史叙述被 regex 误判为当前 VECTOR_ERROR，导致 fixed 结果误路由回 vector_error_debug 空转

**事实**：
- `vector_evidence.py::_extract_error_type` 在 `dump_evidence` 自由文本上跑 regex `(VECTOR_EXCEPTION|VECTOR_CORE_EXCEPTION|ACL_ERROR_RT_VECTOR)`，命中即返回 `VECTOR_ERROR`，**先于** agent 结构化声明的 `debug_status` / `error_type` 被消费。
- kernel_debug 的 `dump_evidence` 是**修复前崩溃的叙述文本**（"本 case 为设备级 VECTOR_CORE_EXCEPTION（...）→ 静态分析定位 ... → 修复后 KL 单 case 回验 PASS"）。agent 已结构化声明 `debug_status=fixed` + `error_type=""` + `verification.crash="resolved"` + `verification.after_passed=true`，但 regex 命中叙述里的 `VECTOR_CORE_EXCEPTION`，`_record_phase_error` 把 `cp["error_type"]` 覆写为 `VECTOR_ERROR`。
- `KernelDebugSubstage.resolve_condition` 在 `debug_status` 检查**之前**先判 `if dc.get("error_type") == "VECTOR_ERROR": return "vector_error"` → 固定好的 case 被路由回 vector_error_debug。vector_error_debug 只能复现 `not_reproduced`，又回 kernel_debug → 死循环。
- 真实轨迹（group_norm batch 20260808_090335，2026-08-08）：`kernel_debug_round_4/5/6` 全部 `debug_status=fixed`（case_3 spatialSize uint16 截断除零已修，KL 回验 PASS），却被连续 3 次误路由到 vector_error_debug（events.jsonl `kernel_debug→vector_error_debug` 出现 3 次，各耗时 ~8 分钟），每次 vector_error_debug 报 `not_reproduced` 弹回，最终第 4 次才到 regression。浪费 3 轮 agent 调度。

**凭什么这么说**：`_extract_error_type`（vector_evidence.py:62）regex 先于结构化字段消费；`kernel_debug.py:154` `error_type` 判据先于 `debug_status`；用真实 `kernel_debug_round_4_result.json` 复现 `_extract_error_type` 返回 `VECTOR_ERROR`；events.jsonl 记录 count 6/8/10 三次 kernel_debug→vector_error_debug 往返。
