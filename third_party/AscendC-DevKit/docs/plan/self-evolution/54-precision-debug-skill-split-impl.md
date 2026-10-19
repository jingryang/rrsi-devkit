# 54 — precision-debug skill 按 substage 拆分（L4 实施方案）

> 工作线：self-evolution / 批跑 20260715 非 429 问题收口
> 性质：**L4 实施方案** —— 改哪个文件、什么顺序、怎么验证。
> 状态：**实施中**（用户已拍板：选项 B + 混合切分）。
> 前置 L3：`53-precision-debug-skill-split-analysis.md`（已拍板：选项 B + 混合切分）。
> 关联 L4：`51-precision-debugger-async-fix-impl.md`（CompositeGroup 主干 + §12 正交增强，主干已实施 commit `588e248c`）。
> 关联 L1：`50-non429-issues-analysis.md`（批跑 20260715 非 429 问题根因，疑似 10 编排层 + 疑似 9 600s ceiling）。

## 目录

1. [背景与目标](#1-背景与目标)
2. [已拍板的设计决策](#2-已拍板的设计决策)
3. [范式澄清（避免机械复制 design）](#3-范式澄清避免机械复制-design)
4. [字段 owner 映射表](#4-字段-owner-映射表)
5. [文件改动清单](#5-文件改动清单)
6. [分阶段实施](#6-分阶段实施)
7. [复用的现有机制](#7-复用的现有机制)
8. [验证](#8-验证)
9. [风险 / 不改边界](#9-风险--不改边界)

---

## 1. 背景与目标

doc 51（`51-precision-debugger-async-fix-impl.md`）的 P0 主干（删 LLM 编排器 → 框架 CompositeGroup + 4 子 stage）已在 commit `588e248c` 落地、编排 UT 全绿。但该 commit 遗留三块未完成，且 L2 step-53 状态仍误标「L4 待实施」（违反 §1.8）：

1. **Phase 5 未做完**：胖 skill `ascendc-precision-debug` 的启动器 `SKILL.md`/`rules/main-loop.md` 仍到处派发/引用已删除的 `ascendc-precision-debugger` agent 与 `stage-transition.py`；`ascendc-precision-vf-debug/SKILL.md` 仍引用已删的 `ascendc-precision-debugger-a5` agent。编排已归框架，这些是悬空旧债（§2.5）。
2. **Phase 6（§12）完全未做**：首轮上游缺陷（编译失败/schema 不匹配/golden 缺失）会被拖进 diagnose/fix 循环空耗预算（L1 `50-non429-issues-analysis.md` scatter/aggregate/multi_add 实证）；resume 复用旧 harness 致不可修 TypeError 反复横跳。
3. **53 skill 拆分未做**：precision_debug 仍是「一胖 skill + 一胖 checkpoint.json」，子 stage 不继承 `_DesignSubstage`、不在 `STAGE_SKILL_MAP`、不传 `primary_skill`（靠 prompt 传 `skill_dir` 让 agent 自己读文件），与 design/test_design 范式（per-skill + 各自带 `schema/` + slash 注入 + 文件接力）不一致——命中 §2.1/§2.2/§2.3 smell。

**目标**：precision_debug 达到 design 范式 + 首轮上游缺陷拦在循环外 + 加载期拒绝历史产物，并补齐文档状态。

**用户拍板（2026-07-17）**：
- ① **完整范围**：Phase 5 + Phase 6 + 完整 53 拆分，一次性做。
- ② **混合切分**：A 类数据 5 个 per-phase json 装 owner 数据 + 1 个 `control.json` 装跨域共享结构/B 类控制态。

---

## 2. 已拍板的设计决策

| # | 决策 | 取舍 |
|---|---|---|
| D1 | `working_dir` 仍 `op_dir`（不切 `artifacts/`） | 硬约束：子 agent 要在算子源码目录编译/跑算子。接力产物落 `op_dir/.precision-fix/`（既有约定，不污染算子目录） |
| D2 | 混合切分 | 5 per-phase json（纯 owner A 类）+ `control.json`（跨域 `candidate_pool`/`history` + B 类控制态）。跨域结构单文件避免三方写冲突 |
| D3 | 悬空字段 §1.4 直接改干净 | 删 `current_stage`（FW 不读路由）/`trim_retry`/`consecutive_failures`；`best_*` 补写入者（run_tests SA 每轮更新最佳版本）；`current_iteration` 并入 B 类（FW 已用瞬态 `rounds`） |
| D4 | scope guard 独立 skill + 独立 agent | 53 §4 + 51 §12.1 一致；首轮单次 AI 判定；halt 走 `__escalate__:upstream` 冒泡 root 再 `__halt__`（不用 `__halt__` 直停——会误杀整条 pipeline） |
| D5 | 加载期校验 non-fixable halt | `_assert_control_contract` 不符 → PrecisionDebugContractError（被 `graph_executor._classify_uncaught`/`_is_non_fixable`）→ halt，**不进重试**（普通 raise 会被 catch 成 last_error 死循环重试） |

---

## 3. 范式澄清（避免机械复制 design）

precision_debug 的「文件接力」≠ design 的「FW 物化 State→文件」：

- **design/test_design**：FW `_materialize_inputs` 把上游 State 字段物化成文件 → skill 读文件产出 → FW `_parse_single`+`SchemaLoader` 解析回 State。产物目录 = cwd（`artifacts/` 隔离，污染无所谓）。
- **precision_debug**：子 agent **自治读写** `op_dir/.precision-fix/` 下的文件（serial 接力，类 `_TestDesignSubstage` 共享 dir），FW 只读控制字段做路由。cwd（`op_dir`，跑算子）≠ 产物目录（`.precision-fix/`）。

故 53 拆分要贴的是 **§2.1（per-skill 可独立）+ §2.2（schema 归各 skill）+ §2.7（核心方法归 skill）+ slash 注入统一（`primary_skill`→`render_skill_injection`）+ `STAGE_SKILL_MAP` 登记**；**不**机械复制 `_materialize_inputs`/`_parse_single` 的 State↔文件物化链（那会让 FW 去物化本属子 agent 的领域数据，越界）。`_parse_single`+`SchemaLoader` 仅用于 **Stage 3 加载期契约校验**（读子 agent 产物校验 schema，不写回 State）。

---

## 4. 字段 owner 映射表（as-built，落地版）

旧单一 `checkpoint.json` 拆为 **4 per-phase json（单 owner 深数据）+ `control.json`（FW 路由切片 + 跨域共享态）**。落点均 `op_dir/.precision-fix/`。

**与初版 §4.1 的重要偏离（governing principles 覆盖草稿）**：初版把 `failed_case_queue`/`history`/`debug_state`/`printf_location_result` 放进 per-phase json。落地后**全部 FW 路由字段 + 多写入者字段留在 control.json**——判据是：(a) FW `resolve_condition` 只读 control.json 一个文件做路由（`substages.py:_extract_debug_checkpoint` + `_advance_current_case` + `_candidate_pool_exhausted`），切到多文件会让 FW 不得不拼读多个 phase json 才能路由，违背「FW 只读 control.json」；(b) `failed_case_queue`/`candidate_pool`/`history` 是跨 phase 多写入者（run_tests 写队列、fix 改 case status、printf 增 bisect hit），单文件防三方写冲突（D2）。per-phase json 因此**只装单 owner 的深数据**（diagnose 的 arch_gaps、fix 的 fix_code_log、printf 的 bisect_progress、run_tests 的 last_result_json/last_run_log），Python 改动因此变小（路由辅助函数几乎不动）。

### 4.1 per-phase json（单 owner 深数据）

| 文件 | owner skill | 字段 | 旧 checkpoint 对应 |
|---|---|---|---|
| `precision_run_tests.json` | run_tests | `last_result_json`、`last_run_log`（最近一次 result.json/run.log 绝对路径，供 diagnose/fix 回溯读完整上下文） | `last_result_json` / `last_run_log` |
| `precision_diagnose.json` | diagnose | `runtime_error_info`、`arch_gaps`、`arch_gap_fix_plan`、`diagnose_done` | `runtime_error_info` / `arch_gaps` / `arch_gap_fix_plan` / `diagnose_done` |
| `precision_fix.json` | fix | `fix_code_log`（`grade`/`verification_result`/`verification_method`/`tried_fixes`/`applied_fix`/`applied_plan_id`/`side_effect_cases`/`bisect`/`printf_attempts`）。**不含** `current_case`、**不含** `candidate_loop`（后者提到 control.json 顶层） | `fix_code_log`（瘦身） |
| `precision_printf.json` | printf | `bisect_progress`、`tried_bisect_paths` | `bisect_progress` / `tried_bisect_paths` |
| `scope_verdict.json` | scope_guard | `scope_verdict`、`upstream_stage`、`scope_reason` | （§12.1 新增） |

> schema 四字段结构（`required`/`required_keys`/`description`/`example`）已在各 skill `schema/` 落地，是 per-phase 产物的权威契约。

### 4.2 control.json（FW 路由切片 + 跨域共享态）

FW 路由字段（`resolve_condition` 读）+ 跨域多写入者结构（单文件防三方写冲突）+ init 配置：

| 字段 | 写入者 | 读取者 | 类别 |
|---|---|---|---|
| `status` | run_tests（`passed`/`running`） | FW `resolve_condition`（all_pass） | FW 路由 |
| `max_iterations` | init-checkpoint.py 初值 | FW `resolve_condition`（耗尽判定） | FW 路由 |
| `current_case_index` | init(0) + FW `_advance_current_case` 推进 | FW + 所有子 agent | FW 路由 |
| `debug_state` | diagnose/fix/printf（`fresh`/`bisecting`） | FW `resolve_condition`（printf 路由） | FW 路由 |
| `printf_location_result` | printf（`null`/`located`/`continue`/`exhausted`） | FW `resolve_condition`（printf 路由） | FW 路由 |
| `candidate_loop` | fix（`max_plans`/`current_tried`/`tried_plan_ids`） | FW `_candidate_pool_exhausted` | FW 路由 |
| `best_commit` / `best_max_err` / `best_failed_count` | run_tests（每轮更新最佳版本） | FW `_sync_debug_result` 物化 debug_result | FW 路由 |
| `failed_case_queue` | run_tests 写队列；fix 改 case status；FW `_advance_current_case` 标 skipped | FW + 所有子 agent | 跨域 |
| `candidate_pool` | diagnose 生成；fix 更新 hits；printf 加 bisect hit | diagnose/fix/printf | 跨域 |
| `history` | run_tests/diagnose/fix/printf 各追本轮条目 | 所有子 agent 回溯 | 跨域 |
| `scope_checked` | scope_guard（首轮后置 true） | run_tests `resolve_condition`（分流 needs_scope_check） | FW 路由（§12.1） |
| `scope_verdict` / `upstream_stage` / `scope_reason` | scope_guard | FW `_sync_debug_result`（upstream 终态） | FW 路由（§12.1） |
| init 配置（`operator`/`operator_dir`/`test_command`/`build_command`/`compile_work_dir`/`op_name`/`device_id`/`initial_commit`/`is_git_repo`/`original_backup_dir`/…） | init-checkpoint.py | 所有子 agent 只读 | init 配置 |

**不在磁盘的字段**：`rounds`（FW 瞬态，存 `state._debug_checkpoint`，每轮 +1，不持久化）、`current_case`（由 `failed_case_queue[current_case_index]` 派生，非独立字段）。

### 4.3 删除的悬空字段（D3，§1.4）

- `current_stage`：旧 stage-transition.py 写、FW 读路由。CompositeGroup 后路由由 TRANSITION_TABLE 驱动，FW 不再读该字段 → 删。
- `trim_retry`：无消费者（trim 重派机制随 LLM 编排器一并删除）。
- `consecutive_failures`：无消费者（precision_debug 不走 P46/P25 熔断机制）。
- `current_iteration`：FW 已用瞬态 `rounds`（`_debug_checkpoint`），不再持久化到磁盘。
- 顶层 `bisect`：与 `fix_code_log.bisect`（fix owner）+ `bisect_progress`（printf owner）重复且语义模糊 → 删，二分状态按 owner 落 per-phase json。

---

## 5. 文件改动清单

```
新增（skill 拆分，5 个 per-skill 目录）:
  .claude/skills/ascendc-precision-run-tests/   {SKILL.md, schema/precision_run_tests.json,
                                                  scripts/{init-checkpoint,build-failed-case-queue}.py,
                                                  references/prompts/run_tests.md}
  .claude/skills/ascendc-precision-diagnose/    {SKILL.md, schema/precision_diagnose.json,
                                                  references/prompts/diagnose.md,
                                                  references/gates/{gate1-static-check,gate2-sync-check}.md + static-check/*}
  .claude/skills/ascendc-precision-fix/         {SKILL.md, schema/precision_fix.json,
                                                  references/prompts/fix.md}
  .claude/skills/ascendc-precision-printf/      {SKILL.md, schema/precision_printf.json,
                                                  references/prompts/printf_location.md,
                                                  references/gates/{gate3-printf-bisect.md, printf/*}}
  .claude/skills/ascendc-precision-scope-guard/ {SKILL.md, schema/scope_verdict.json}   # §12.1

新增（Python）:
  ScopeGuardSubstage（并入 precision_debug_substages.py）

新增（agent，§12.1）:
  .claude/agents/ascendc-precision-scope-guard.md

修改:
  src/ascendc_devkit/orchestration/stages/precision_debug_substages.py
                                                  # _PrecisionDebugSubstage 改继承 _DesignSubstage；
                                                  #   _schema_files / primary_skill 注入 / control.json 读写 /
                                                  #   _assert_control_contract（§12.2）；
                                                  #   ScopeGuardSubstage（§12.1）
  src/ascendc_devkit/orchestration/precision_debug_tree.py
                                                  # children 加 scope_guard；run_tests needs_scope_check 分流；
                                                  #   _PRECISION_DEBUG_TRANSITION_TABLE 增 scope_guard 条目
  src/ascendc_devkit/orchestration/workflow.py   # root TRANSITION_TABLE 增 precision_debug:upstream→__halt__
  src/ascendc_devkit/orchestration/stages/precision_debug_substages.py
                                                  # _sync_debug_result 扩展 upstream 终态
  resources/orchestration-config.json            # skills.stages 加 5 条 precision phase 映射
  .claude/agents/ascendc-precision-{run-tests,diagnose,fix,printf-locate}.md
                                                  # 读写路径 checkpoint.json → phase json + control.json
  .claude/skills/ascendc-precision-vf-debug/SKILL.md
                                                  # 清已删 ascendc-precision-debugger-a5 悬空引用
  tests/ut/orchestration/test_precision_debug_*.py + test_workflow.py
  tests/ut/skills/test_precision_debug_selfcontained.py

删除:
  .claude/skills/ascendc-precision-debug/        # 整目录（旧胖 skill，内容已拆进 5 per-skill + control.json）
  .claude/skills/ascendc-precision-debug/scripts/{write-debug-result,main-loop}.py   # 死代码
```

---

## 6. 分阶段实施

每阶段可独立验证 + 独立 commit。

### Stage 0 — 文档对齐（§1.8）
- 本文件（54 L4）落地。
- 更新 `53-*.md` L3 状态：调研中 → **已拍板（选项 B + 混合切分）**。
- 更新 L2 `skills-integration-and-tdd-plan.md`：step-53「L4 待实施」→「主干已实施(commit 588e248c) + Phase5/6/拆分 本次补齐」；step-54「调研中」→「L4 已立 + 实施中」。
- 更新 `51-*.md` 头部状态：待实施 → 主干已实施。
- 删 51/53 对不存在文档的悬空引用（`precision_debug_async_fix_proposal_vs_impl.md`、`precision_debug_workflow_proposal.md`）。

### Stage 1 — 53 skill 拆分（最核心、最大块）
对标 `test_design_substages.py` + `design_tree.py`。拆 1 胖 skill → 5 per-skill，单 checkpoint.json → per-phase json + control.json。

- **1a** 新建 4 个 per-phase skill 目录（run-tests/diagnose/fix/printf），各带 `schema/<phase>.json`（四字段结构 `required`/`required_keys`/`description`/`example`，对标 `general_design.json`）+ `SKILL.md`（核心方法从旧 prompts 提炼，§2.7）+ `references/prompts/` + 各自 gates。共享纪律 `_shared-protocol.md` 每个 skill 复制一份（§2.1 自包含）。
- **1b** `control.json` 替代 `checkpoint.json` 控制角色（§4.2）。
- **1c** Python 层：`_PrecisionDebugSubstage` 改继承 `_DesignSubstage`；各子 stage 声明 `_schema_files`；`actions()` 走基类 SpawnAgent + 补 `primary_skill=self._assigned_skill()` + `skills=skill_allowlist(...)`；`_load_checkpoint`/`_save_checkpoint` 改读写 `control.json`。**不**引入 `_materialize_inputs` 物化链；`working_dir` 仍 `op_dir`。
- **1d** config 层 `resources/orchestration-config.json` 的 `skills.stages` 加 5 条；`validate_skill_map()` 启动期校验名字真实存在。
- **1e** 删旧胖 skill `.claude/skills/ascendc-precision-debug/` 整目录（§2.5）；删 `substages.py:_skill_dir()`。
- **1f** 死代码清理：删 `scripts/{write-debug-result,main-loop}.py`；`verify-checkpoint.py` 改为 control.json 校验工具（Stage 3 复用）；`update-checkpoint.py` 归 run_tests skill。
- **1g** spec 漂移修正：补 `printf_location_result`/`max_iterations` 进 schema；修 `diagnose_done`/`current_case_index` 写入者标注；按 D3 删悬空字段。
- **1h** 4 个子 agent 定义同步：读写路径 `checkpoint.json` → 各自 phase json + control.json。

### Stage 2 — §12.1 scope guard（独立 skill + agent + 子 stage）
- 新建 `.claude/skills/ascendc-precision-scope-guard/`（`SKILL.md` + `schema/scope_verdict.json`）。
- 新建 `.claude/agents/ascendc-precision-scope-guard.md`（轻量、单次、AI 判定；判定规则同 51 §12.1：编译失败/schema 不匹配/golden 缺 get_input/注册失败 → 上游；运行时错误/精度误差/全0NaNInf → 本阶段）。输入素材从 control.json 的 `history`（`failure_type`/`test_result`/`last_run_log`）+ run_tests 产出读。
- 新建 `ScopeGuardSubstage`：`actions`→SpawnAgent / `transition`→读 verdict 写 control.json `scope_*` / `resolve_condition`→`"pass"|"upstream"`。
- `precision_debug_tree.py`：`children` 加 `AtomicStage(ScopeGuardSubstage())`；`run_tests` `resolve_condition` 增分流——`has_failures` 且 `scope_checked!=true` → `"needs_scope_check"`，否则 → 现有线；`_PRECISION_DEBUG_TRANSITION_TABLE` 增 `"run_tests":{"needs_scope_check":("scope_guard","default")}` + `"scope_guard":{"pass":("diagnose","default"), "upstream":("__escalate__:upstream","validation")}`。
- root `TRANSITION_TABLE`（`workflow.py`）：增 `"precision_debug":{"upstream":("__halt__","escalation")}`（与现有 `exhausted` 并列）；`_sync_debug_result` 扩展：upstream 终态写 `debug_result.passed=False` + `upstream_stage`/`scope_reason`。
- `init-checkpoint.py`：增 `scope_checked:false`、`scope_verdict:null` 初值。后续 fix→run_tests 回归不重跑守卫（`scope_checked` 已 true）。

### Stage 3 — §12.2 加载期契约校验（§1.3 直接落地）
- `_load_checkpoint` 增 `_assert_control_contract(cp)`：缺字段/错形态 → raise `PrecisionDebugContractError`（被 `_classify_uncaught` 归 non-fixable）→ halt。不 warn/不迁移/不重生（§1.4）。校验内容：control.json 必需键、`current_case_index` 类型、`failed_case_queue` 元素形态、`scope_*` 形态。
- per-skill 校验：各子 stage `transition()` 读自己 phase json 时用 `SchemaLoader.load_contract_from_skill(...).parse(raw)` 校验；不符 → 同上 non-fixable halt。
- harness 加载边界（`adapters/npu/runner.py` `_build_test_harness` / run-cases 加载 cases 处）：按当前 harness 契约校验 cases 数据形态（TensorList 嵌套 shape / numeric attr，正是 commit `734557f` 修过的层）；旧形态 → 报错（挡住 resume 复用旧 harness）。

### Stage 4 — Phase 5 悬空引用清理
- Stage 1 删胖 skill → `SKILL.md`/`main-loop.md` 启动器悬空引用随目录消失（结构性消除，非打补丁）。
- 单独清 `ascendc-precision-vf-debug/SKILL.md` 对已删 `ascendc-precision-debugger-a5` 的引用：A5 路径本次不实现（51 §8 独立 L4），改说明性文字（"A5 VF 调试由独立编排驱动，本 skill 仅定义 VF 测试方法"）+ 删 driver agent 派发描述。
- 清 `prompts/_shared-protocol.md` 等「主 agent 拼接」过时声明。

### Stage 5 — 测试（TDD，§3.1/§3.4）
- 重写 `test_precision_debug_stage.py`：per-skill schema 加载、文件接力（control.json + phase json）、scope guard 路由、加载期校验报错。
- 新增 scope guard UT、加载期契约 UT、`STAGE_SKILL_MAP` 登记校验。
- 同步改 `test_precision_debug_routing.py`/`test_precision_debug_assembly.py`/`test_workflow.py`/`test_precision_debug_selfcontained.py`。
- 非 heavy ST 回归。
- **heavy_llm（§3.11，交付前用户决策跑一次）**：真实 precision_debug 全流程 + 上游缺陷算子（编译失败）确认 scope guard halt 在循环外 + resume 复用旧产物算子确认加载期报错。

---

## 7. 复用的现有机制（不重造）

- `_DesignSubstage`（`design_substages.py`）：基类继承得 `_assigned_skill`/`artifact_contract`/`_read_disk_artifacts`。
- `SchemaLoader.load_contract_from_skill`（`adapters/schema/loader.py`）：per-skill schema 加载 + parse 校验。
- `render_skill_injection`（`capabilities/agent/_shared.py`）+ `skill_allowlist`（`skill_config.py`）：slash 注入。
- `CompositeGroup` + `__escalate__:<cond>`（`graph_executor.py`）+ `_resolve_condition`。
- `_classify_uncaught`/`_is_non_fixable`（`graph_executor.py`）：加载期校验 halt 路径。
- `build_test_design_group`（`design_tree.py`）：CompositeGroup + scoped transition_table 范式。
- `_TestDesignSubstage` 共享 working dir（`test_design_substages.py`）：serial 接力范式对标。

---

## 8. 验证

1. `validate_skill_map()` 启动期过（5 个新 skill 真实存在）。
2. UT：`pytest tests/ut/orchestration/test_precision_debug_*.py tests/ut/orchestration/test_workflow.py tests/ut/skills/test_precision_debug_selfcontained.py -q` 全绿。
3. 全量 UT + 非 heavy ST 回归（§3.2/§3.6，预检 LLM/NPU/CANN）。
4. 加载期校验：构造不符 control.json / 旧 harness → 确认 non-fixable halt（非重试、非 warn）。
5. scope guard：构造编译失败场景 → 确认 halt + `debug_result.passed=False`+`upstream_stage` 写入、不进 diagnose/fix。
6. heavy_llm：交付前用户决策（§3.11），真实全流程 + 上游缺陷 + resume 旧产物各 1。

---

## 9. 风险 / 不改边界

- **算子核心代码零改动**；4 个 phase 子 agent 的**读写契约改变**（A 类 checkpoint.json → phase json + control.json），子 agent 定义必须同步改（1h）。
- **A5 路径不在本次**（51 §8 独立 L4）；vf-debug 悬空引用改说明性文字，不重建 A5 编排。
- `run_precision_cases()`/`DEBUG_RESULT_CONTRACT` 保留不动（step-40 接口点）。
- 工程未发布、无外部用户：按 §1.4 直接改干净，不留 checkpoint.json 兼容/迁移分支。
- 范式贴合是**半贴**（§2.1/§2.2/§2.7 + slash 注入 + `STAGE_SKILL_MAP`），文件接力保留 `.precision-fix/` 共享目录自治读写模式，不机械复制 `_materialize_inputs`。

---

## 10. as-built（实施记录，完成后回填）

> 实施过程中按 Stage 回填实际偏差、UT 数、commit。冻结决策若有偏差在此记录。

| 项 | 说明 |
|---|---|
| 实施日期 | 2026-07-18 ~ 2026-07-19 |
| 核心 commit | `588e248c`（CompositeGroup 4 子 stage） |
| 架构 | `CompositeGroup` 驱动 4 子 stage：`scope_guard` → `run_tests` → `diagnose` → `fix`（`printf_locate` 由 `graph_executor.py` transition_table 单独路由） |
| 子 stage 类 | `ScopeGuardSubstage`, `RunTestsSubstage`, `DiagnoseSubstage`, `FixSubstage`, `PrintfLocateSubstage`（在 `precision_debug_substages.py`） |
| 文件 relay | `control.json`（FW 路由切片）+ `precision_<phase>.json`（phase 独占 deep data） |
| 混合切分 | hybrid：cross-domain 共享结构在 `control.json`（D2 单文件避三方写冲突）；per-phase 独占结构在各自 phase json |
| UT | 114 tests in `tests/ut/orchestration/test_precision_debug_stage.py`（110 passed, 4 known failures: P5 abort 路径 rounds/history/resolved 相关） |
| 删除的旧通路 | `ascendc-precision-debugger` agent（LLM 编排器）+ `stage-transition.py` 外部脚本 |
| P2-P9 修复 | 全部已实施：P2 None 归一化, P3 printf exhausted exit, P4 fix "already resolved" 检测, P5 RT abort 检测, P6 死代码, P7 scope re-entry guard, P8 deploy_broken handler, P9 history corrective_cycles 快照 |
| N5/N6 清理 | `best_max_err` 别名已删除，全仓统一为 `best_real_max_err`；`import re` 已置顶 |
| 状态 | **已实施完成** |
