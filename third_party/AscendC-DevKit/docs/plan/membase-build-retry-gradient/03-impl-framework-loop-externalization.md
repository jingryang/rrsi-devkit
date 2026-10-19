# L4: Membase codegen build-retry 循环外提到框架级（阶段 3，方案 Z）

> 接续 step 81（阶段 1 footer 富化 / 阶段 2 deploy 层 classify+gradient）。
> L1 `01-problems.md`（P1/P5）、L3 `02-analysis.md`（决策 6）。本文件 = 实施方案 + as-built。

## 目标

把 build-retry 循环从单个 `ascendc-coder` agent 的**会话内自跑**搬到**框架 iteration 驱动**：
每轮 spawn 一个短 coder agent（只改代码）→ transition 直调 `Deployer().deploy(state)` 做 build+smoke
→ 跨轮状态走 State 字段 + 磁盘文件（不靠 agent 上下文）→ 消除 compaction 丢里程碑、消除 in-session
build 不可观测。

触发：run `20260802-171400-794e81` 的 `multi_add_rms_norm_dynamic_quant` codegen **726 turn/158min**，
4 次 compaction，turn 308 已 smoke passed 被 compaction 抹掉 → turn 310 从头重来（约 410 turn 重复攻坚）。
阶段 1/2（commit `0aed1aee`）让 agent 看到分类/gradient（974→726 turn 下降），但循环仍在 agent
in-session，框架对每轮 build-retry 仍不可见（P1 未触及）+ 跨轮里程碑靠 agent 上下文（P5）。

## 已验证的关键机制（命门复核通过）

- **runner iteration 循环**（`kernel/runner.py:277-449`）本就支持普通 Stage 多轮 spawn：
  `output_contract.provides` 不满足 → 不设 `is_terminal` → for 循环重 spawn。**不需 CompositeGroup、
  不需改 fail_strategy**。
- **stage_status 计算**（`runner.py:515-564`）在 for 循环 **break 之后**才跑——重 spawn 期间到不了；
  到上限写 `deploy_result` → `has_all=True` → `stage_status="ok"` → 不 halt → D4 交下游。
- **`last_error` 触发 halt**（`fail_strategy="halt"`）——编译错误**不**经 last_error，改经新 State 字段
  + Deployer 自动写的磁盘文件。
- **`Deployer().deploy(state)`**（`deploy.py:219`）纯数据 I/O，可在 transition 直调；build 失败时
  `classify_build_error`/`_bump_retry_state`/`build_retry_gradient_section` 在 `_run_command` 失败分支
  **全自动**。
- **`err.details["step"]`**（`deploy.py:388 _err`）是三分支判据：`build`/`install_*` = 编译失败；
  `smoke` = 编译过但不可调用；`None` = 全过。

## 实施步骤（as-built）

### 1. State 新字段（`kernel/state.py`）
在 codegen 字段区（`codegen_vf_previous_error` 后）追加：
- `codegen_build_retries: int = 0` — 编译失败重试计数（仅 Membase；smoke 失败走 D4 不计数）
- `codegen_build_feedback: dict | None = None` — 上轮编译错误反馈（error_class/log_path/gradient_hint），
  注入下轮 prompt；**不触发 halt**
- `from_snapshot` 的 new_field 列表追加 `("codegen_build_retries", 0)`、`("codegen_build_feedback", None)`

### 2. 配置（`resources/orchestration-config.json`）
- 新增顶层 `codegen.build_max_retries` = **1000**（用户拍板「尽量解决」，默认从初版 5 改 1000）
- `iterations.stages.codegen` 从 40 改 **1000**（**必须 ≥ build_max_retries**，否则 runner 在 40 处
  break 且 `has_all=False` → partial-passed → halt，1000 失效）+ `_comment` 说明对齐要求

### 3. `codegen.py` — 核心改动
- **`_transition_membase`**：structural 校验通过后（manifest 完整 + callable_target 正确），**删** membase
  对 `_read_deploy_result` 的调用，改为直调 `Deployer().deploy(state)`，按 `err` 三分支：
  - `err is None` → done：写 `deploy_result`（smoke_passed=True）+ 归零计数器
  - `err.details["step"] == "smoke"` → D4：写 `deploy_result`（smoke_passed=False），不 halt，交下游
  - `err.details["step"]` ∈ {build, install_*} → build-retry：`retries += 1`；`retries >= limit` → D4
    逃生（写 deploy_result smoke_passed=False）；否则收集 feedback → **不写 deploy_result、不设 last_error**
    （contract 不满足 → runner 重 spawn）
- **`_actions_membase`**：context 删 `max_rounds`，加 `build_feedback`（从 `state.codegen_build_feedback` 读）
- **`_build_codegen_prompt`**：删 in-session build 循环段（§2.5 唯一通路）；加「上轮编译失败反馈」段
  （当 `codegen_build_feedback` 非空：注入 error_class + `subprocess/build_*.log` 路径 + gradient hint
  + stderr_tail + 「不要自己 build/redeploy，框架会自动编译验证」）
- 新增 `_build_retry_limit()`（读 config `codegen.build_max_retries`，默认 1000）+ `_collect_build_feedback`
  （读 `Deployer._read_retry_state(ws)` + `build_retry_gradient_section`）
- **`rerun_reset_fields`**：追加 `codegen_build_retries`、`codegen_build_feedback`

### 4. 测试
- **`tests/ut/orchestration/test_stages.py`**：新增 `_patch_deploy` contextmanager（mock
  `Deployer.deploy` 返回受控 `(DeployResult, err)`，4 模式：smoke_passed / smoke_failed / build_fail /
  resolve_fail）；10 个测试包 `with _patch_deploy(...)`；重写 2（halts_on_unfixable=resolve_fail、
  prompt_no_longer_injects_redeploy_loop）；新增 4（build_failure_triggers_respawn /
  build_retry_exhausted_escapes_to_d4 / smoke_passed_resets_build_retry_counters /
  build_feedback_injected_into_prompt）
- **`tests/ut/orchestration/test_plan_a_inrepo.py`**：加 `_patch_deploy` + 包 2 个 codegen transition 调用点
- **`tests/st/test_self_evolution_stages.py`**：加 `_patch_deploy` + 包 `:154`（唯一碰 deploy 的 codegen
  transition）；`:196/:225` 走 route-back（structural 校验在 deploy 前 return）不碰 deploy，无需改

## 复用的现有设施（不重造）
- `Deployer.deploy(state)`（`deploy.py:219`）— 框架级 build+smoke 入口
- `classify_build_error` / `build_retry_gradient_section`（`build_log_scanner.py`）— classify + 策略
- `Deployer._read_retry_state` / `_bump_retry_state`（`deploy.py`）— 自动持久化 `build_retry_state.json`
- runner iteration 循环 + circuit breaker（`codegen_consecutive_failures`）— 已有

## 约束核对
- **§2.5**：删 in-session build prompt + 删 membase 对 `_read_deploy_result` 调用 → `Deployer.deploy` 是
  唯一 build 通路
- **§2.1/§2.8**：build 循环契约在框架 prompt 不在 `ascendc-op-dev-coding/SKILL.md`（已 grep 确认）→ 不碰 skill
- **不碰 Regbase**：`_actions_regbase`/`_transition_regbase*` 同事产权，完全不动；新字段默认值对 Regbase 透明
- **§1.10**：retry 判据用 `classify_build_error` 业务语义（C-API/C-TYP/...），不用机制特征
- **保留 D4（step-84）**：编译过但 smoke 失败 / build-retry 达上限 → 带 smoke_passed=False 交下游，不阻断

## as-built 偏差（与 L3/L4 蓝图的差异）
1. **`build_max_retries` 默认 5 → 1000**：用户会话中拍板「我们要尽量解决，所以默认改成 1000」。
   同步把 `iterations.stages.codegen` 40 → 1000（对齐，否则 runner@40 截断使 1000 失效）。
2. **`_read_deploy_result` 保留不删**：L4 蓝图原计划删，实施时发现 Regbase 路径（`codegen.py:1998`
   `_actions_regbase` 用 + regbase 测试 mock）依赖它——只删 membase 的调用，函数保留（§不越界同事产权）。
3. **保留 `_attach_passing_deploy`**：UT/ST 测试 helper，仍用于挂 workspace（`_persist_sources` 需要）；
   它写的 `last_deploy.json` 不再被 membase codegen 读（无害，仅 workspace 挂载用途）。

## 风险
- transition 直调 `Deployer.deploy` 是**同步阻塞**（build 1-5min + smoke 10-60s）；与 cannbench_eval 的
  kernel_eval subprocess 同模式，`stage_timeout` 仍在 iteration 边界生效。单次 build 在 transition 内
  不可中断（可接受）。
- `last_deploy.json` 不再由 membase codegen 写（删 `_read_deploy_result` 调用）；precision_debug 经 CLI
  `redeploy` 的 `DebugService.redeploy` 仍独立写/读，两路径不冲突。

## 验证结果
1. **`tests/ut/orchestration/test_stages.py::TestCodegenStage`**：45 passed（TDD 红→绿）
2. **全量 `tests/ut/`**：**3532 passed / 7 skipped / 0 failed**（402s）— 零回归 + 修 2 pre-existing：
   - `test_harness_matches_golden`：更新 golden 同步已 committed 的 `_to_np` bf16→f32 cast（commit
     `014707a0`）+ exception TRACEBACK 诊断（harness 生成代码不在我 working tree，golden 过时）
   - `test_passed_does_not_converge` → `test_passed_also_converges_for_binary_consistency`：反映 commit
     `88dbae9e` 删 `_converge_to_best_commit` 的 passed early-return（precision_debug 编译产物 vs deploy
     重编译 binary 可能不同，passed 也须 rollback+redeploy 确保 eval 用验证过的 binary）
3. **ST**：`test_self_evolution_stages`（唯一调 codegen transition 的 ST）**35 passed** + 编排 ST
   （integration/predesign GeneralDesignStage/design_pipeline）**38 passed** 无回归
4. **heavy_llm**：`tests/st/test_smoke.py::TestCodegenStageEndToEnd`（真实 codegen 端到端，`@slow+@llm+
   @heavy_llm`）**§3.11 待用户决策跑**——特性交付/PR 合并前用户在关键节点跑一次，验证「codegen turn 数
   /耗时下降 + 无 compaction 丢里程碑」真实生效（非 PR 前硬门）
