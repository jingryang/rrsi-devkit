# P53/P54 — 精度失败后 in-stage 调试闭环 实施方案（第四层）

> 状态：**已实施**（2026-07-09 立 / 2026-07-09 实施完成，UT 1700 + 非 heavy ST 全绿）。
> 层级：**第四层 / 实施方案**。改哪个符号、什么顺序、怎么验证。
> 覆盖问题：P53（L1 `06-problems.md`）+ P54（L1）。方案分析见 L3（`31-precision-debug-stage-analysis.md`，选项 B，独立精度调试 stage + agent 内闭环迭代）。
> L2：step 28。
> 约定：按符号定位（不写 file:line）；外部依赖只读；TDD 红→绿（§3.1）。
> **实施期冻结决策见 §7（as-built，覆盖 §2.3/§2.4/§6 的待定项）。**

---

## 1. 设计决策（冻结，自 L3 §6 D1–D11）

- **D1 路由分流**：`self_evolve_op` TRANSITION_TABLE 的 `verify` 分支 `precision_failed: ("codegen","corrective")` → `("precision_debug","corrective")`；`build_failed → codegen` 不变；`exhausted → __halt__` 不变。codegen 编译保证由 `VerifyStage.BuildInRepoGate` 兜（build_failed → codegen），codegen 不新增编译门。
- **D2 stage 内 agent 闭环**：`PrecisionDebugStage` 派发 debug agent，单会话内循环 改码→commit→redeploy→run-cases→读日志→再改，不跨 stage loopback。
- **D3 复用 deploy**：抽 `Deployer` 服务，`DeployStage` + `PrecisionDebugStage` 共用，删 `DeployStage` 内联旧通路（§2.5）。
- **D4 编译失败 in-stage 自修**：agent 改坏 → build 失败 stderr 给 agent → in-stage 自修，不回 codegen；轮数耗尽回退最佳 commit + 转人工。
- **D5 skill 输入 = code+cases+golden**：与 codegen/design 解耦，debug workflow 可复用。
- **D6 每轮 git commit**：追踪修复历史，轮数耗尽回退最佳 commit（max_diff 最小/通过用例最多）。
- **D7 dumptensor+print 落盘**：agent 读文件不靠会话记忆，防上下文压缩丢失。
- **D8 修 phantom max_diff**：`VerifyStage.transition` 从 `gate_result["metrics"]` 读 max_diff（独立 bug，B 不绕开）；`PrecisionResult` 扩展承载 per-case diff/bottleneck。
- **D9 收敛兜底**：`debug_iterations >= max → "exhausted" → ("__halt__","escalation")`，复用 P51 止损出口。
- **D10 脚手架外移/核心归 skill**：build/install/smoke/run-cases 封装 CLI（§2.7）；精度调试 skill 承载 dumptensor 定位根因 + 用例优先级 + 修复策略。
- **D11 CLI 命令族**：`redeploy` / `run-cases`，debug agent 经 CLI 调用。

> **P53 第 2、3 点被绕开**（精度失败不再走 verify→codegen loopback，改走 verify→precision_debug；debug stage 是 agent 内迭代自读日志，不需 codegen 侧反馈消费 skill）——不修，修了是死代码。

---

## 2. 改造点

### 2.1 A — 修 phantom max_diff 字段读取（D8）

- `VerifyStage.transition`：`max_diff=float(gate_result.get("max_diff",0.0))` → `max_diff=float(precision_metrics.get("max_diff",0.0))`（与同函数 `stubbed` 读法一致，`precision_metrics = gate_result.get("metrics",{})`）。
- `PrecisionGate.evaluate`：`metrics` 现只放 `max_diff/actual_ms/stubbed`——扩展放 `per_case`（每 case 的 diff/shape/index）+ `bottleneck`（`NPURunner.execute` 已产出，现被丢弃）。
- `PrecisionResult`（`domain/verification.py`）：加 `per_case: list = field(default_factory=list)`、`bottleneck: str = ""`（`passed/max_diff/threshold/stubbed` 不变；§1.4 不留兼容）。
- `VerifyStage.error_signature`：读真实 `precision_result.max_diff`（修后自然正确），停滞检测不再误判。
- **回归守护**：既有 verify 精度用例断言 `max_diff` 来源正确（P6 修过 CPU 桩，本条是字段读取层，不同层——加用例区分）。

### 2.2 B — 抽 `Deployer` 服务（D3）

- 新 `Deployer`（`domain/deployer.py` 或 `orchestration/services/`，L3/L4 定层——倾向 domain，因 deploy 是领域能力）：承载 `DeployStage` 现有 `_run_profile_chain` / `_per_op_path` / `_template_vars` / `_run_command` / `_run_smoke` / `_cann_lib_paths` / `_callable_target`，签名以 `(op_identity, chip_version, codegen_manifest, profile, workspace, ...)` 入参、返回 `DeployResult`。
- `DeployStage.transition`：改为调 `Deployer.deploy(...)`，行为不变（profile 角色链 build→install_runtime→install_python→smoke）。
- **删旧通路**（§2.5）：`DeployStage` 内联的 deploy 方法体收敛到 `Deployer`，`DeployStage` 只留 stage 契约（actions/transition/gate）+ 调 `Deployer`。不留两套。
- `PrecisionDebugStage`（D）调同一 `Deployer` 做 redeploy。
- 超时常量（`_BUILD_TIMEOUT=600` / `_INSTALL_TIMEOUT=120` / `_SMOKE_TIMEOUT=30`）随方法迁入 `Deployer`。

### 2.3 C — CLI 命令族 `redeploy` / `run-cases`（D11）

- 新 `cli/commands/debug.py`（click），挂到 `cli/main.py` 既有组。
- `redeploy`：对当前 op（从 workspace state 或 CLI 参数取 op_identity/chip_version/codegen_manifest）调 `Deployer.deploy(...)`，per-op 覆盖式安装，输出 `DeployResult` 摘要 + smoke 结果。
- `run-cases`：对当前 op 调 `NPURunner.execute`（复用 `PrecisionGate` 的 runner 组装逻辑，抽共享或直接调 runner），跑全部/`--case` 指定用例，输出 max_diff + per-case diff + dumptensor 日志路径（落盘 D7）。
- **解耦**（D5/D11）：debug agent 经 CLI 调用，不 import 编排内部；CLI 命令可独立复用（独立解 issue 场景）。

### 2.4 D — `PrecisionDebugStage`（D2/D4/D6/D7/D9）

新 `orchestration/stages/precision_debug.py`，`@register_stage`，`name="precision_debug"`：
- `fail_strategy = "continue"`、`default_max_iterations` = L4 定（精度调试轮数，倾向 5——比 verify 的 3 多，因调试需多轮；L4 实施时定）。
- `input_contract.requires`：`op_identity` / `requirement`（取 op_spec+test_cases）/ `golden_path`+`golden_entry`+`golden_input_type` / `deploy_result` / `codegen_manifest`（取 callable_target）/ `repo_root` / `chip_version` / `npu_id`。**不 require codegen 设计上下文**（D5）。
- `actions(state, iteration)`：派发 debug agent（D 的 agent manifest F），prompt 以 `/ascendc-precision-debug` slash command 开头（§4.3 skill 投递），输入契约文件 = code+cases+golden（D5）。agent 内闭环（改码→commit→redeploy→run-cases→读日志→再改）。
- `transition(state, result)`：读 agent 返回（最佳 commit / 通过用例数 / max_diff / 是否全通过），更新 `debug_result` + `debug_iterations`。全通过 → `default`（线性后继 perf/finalize）；未通过 → `resolve_condition` 判 `exhausted`/`precision_unresolved`。
- `resolve_condition(state)`：全通过 → `"default"`；`debug_iterations >= max` → `"exhausted"`；否则 → `"precision_unresolved"`（loopback 回 precision_debug 自身，agent 内迭代已含 loopback 语义，此处 stage 级 loopback 是 agent 会话边界外的兜底——L4 实施时确认是否需要 stage 级 loopback 还是单次 agent 会话内闭环即够，倾向后者：单 agent 会话内跑满 max 轮，stage 只跑一次）。
- `on_uncaught_failure(state, exc)`（P51 hook 模式）：crash 时 `debug_iterations + 1` + `debug_result` crash-failed（让 `resolve_condition` 既有 exhausted 分支生效）。
- `error_signature(state)`：`f"precision_debug:max_diff={...}"` + 失败用例指纹。
- `blocking_issues(state)`：override（修 P53 第 2 点同类可观测性——debug stage 的 loopback/止损日志要显失败原因），返回 `[{"issue": f"精度未通过 max_diff={...}", "failing_cases": [...]}]`。
- **git commit 历史**（D6）：agent 每轮 commit；`transition` 读 git log（最佳 commit = max_diff 最小/通过用例最多的 commit），轮数耗尽回退之。
- **dumptensor 落盘**（D7）：`run-cases` CLI 把日志落到 `<run-artifacts>/debug/<op_name>/iter-N/`，agent 读文件。

### 2.5 E — TRANSITION_TABLE 分流 + stage 名单（D1）

- `Workflow.self_evolve_op` TRANSITION_TABLE：`verify` 分支加 `"precision_failed": ("precision_debug","corrective")`（替原 `("codegen","corrective")`）。
- `precision_debug` 分支：`{"exhausted": ("__halt__","escalation"), "precision_unresolved": ("precision_debug","corrective")}`（后者仅当 stage 级 loopback 需要，见 D 的 `resolve_condition` 说明）。
- `_SELF_EVOLVE_STAGE_NAMES`：在 `verify` 后插 `"precision_debug"`。
- **一致性**：`generate_ascendc` / `generate_ascendc_dev` 的 `verify precision_failed → codegen` 是否同步改 —— L4 实施时判定：这俩是单算子生成流，精度失败回 codegen 合理（无独立 debug workflow 需求）还是也走 debug stage？倾向**只改 `self_evolve_op`**（self-evolve 才有 in-stage 闭环需求 + debug workflow 复用目标）；`generate_*` 保留 → codegen。L3 未明确，L4 实施时确认（静态核对：grep `precision_failed` 消费者）。

### 2.6 F — State 字段（E）

- `State`（`orchestration/kernel/state.py`）加：`debug_iterations: int = 0`、`debug_result: PrecisionDebugResult | None = None`。
- `PrecisionDebugResult`（`domain/verification.py`）：`passed: bool`、`max_diff: float`、`best_commit: str`、`failing_cases: list`、`iterations_used: int`、`stubbed: bool = False`。
- `State.from_snapshot` 的 `new_field` 列表同步 `debug_iterations`/`debug_result`（防 P48 类反序列化漏建字段）。
- `State.to_snapshot`：`debug_iterations` 持久化；`debug_result` 若含不可序列化对象则转 dict（参照既有 `precision_result` 处理）。
- 瞬态字段（`_loopback_feedback`/`is_terminal`/`_stage_failed`/`_bubble_condition`）pop 不变。

### 2.7 G — registry 注册（D 依赖）

- `orchestration/registry.py` `_ensure_stages_loaded()`：加 `from ascendc_devkit.orchestration.stages.precision_debug import PrecisionDebugStage`（`@register_stage` 已在模块内）。

### 2.8 H — debug skill + agent manifest（D5/D10）

- skill：`.claude/plugins/stage-precision-debug/skills/ascendc-precision-debug/SKILL.md`（§2.2 资源归属——schema 等放 skill 目录内）。内容 = dumptensor 定位根因方法 + 失败用例优先级（先修最大 diff / 同方向偏差→系统性错 / 单 case→边界）+ 修复策略引导 + 每轮 git commit 约定 + 读 `run-cases` 日志路径约定。**不写脚手架**（build/install 命令参考目标仓，§2.7）。plugin 归属见 §7.8。
- agent manifest：`.claude/agents/ascendc-precision-debugger.md`（§4.1 frontmatter 声明 skill/工具/权限），工具含 Bash（git/deploy CLI/run-cases CLI）+ Read/Edit（改算子代码）+ Grep/Glob。
- skill 投递（§4.3）：`PrecisionDebugStage.actions` 的 agent 消息以 `/ascendc-precision-debug` 开头。
- **即插即用**（§2.1）：skill 从本仓取出可直接 `/<skill>` 跑，不依赖工程注入上下文、不读自身目录外资源、不依赖 DevKit 专有 MCP。

---

## 3. 实施顺序（TDD 红→绿）

1. **红**：写 §4 全部用例（先失败——现 `precision_failed → codegen`、无 debug stage、phantom max_diff）。
2. **绿-A**：phantom max_diff 字段读取 + `PrecisionResult` 扩展 + `PrecisionGate.evaluate` metrics 扩展（纯逻辑，verify 单测先行）。
3. **绿-B**：抽 `Deployer`，`DeployStage` 改调 `Deployer`（行为不变回归——DeployStage 既有 ST 全绿）。
4. **绿-C**：CLI `redeploy`/`run-cases`（单测：mock `Deployer`/`NPURunner`，断言命令路由 + 输出契约）。
5. **绿-F**：`State` 字段 + `PrecisionDebugResult` + `from_snapshot`/`to_snapshot`（反序列化用例，防 P48 类）。
6. **绿-D**：`PrecisionDebugStage`（actions/transition/resolve_condition/on_uncaught_failure/error_signature/blocking_issues）——用 StubBackend mock agent。
7. **绿-E+G**：TRANSITION_TABLE 分流 + `_SELF_EVOLVE_STAGE_NAMES` + registry 注册（路由用例：`precision_failed → precision_debug`；`exhausted → __halt__`）。
8. **绿-H**：debug skill + agent manifest（skill 即插即用性校验：取出不缺 schema、不读外部路径）。
9. **回归**：UT 全量 + 非 heavy ST（§5）。

---

## 4. TDD 用例（红→绿）

| # | 用例 | 场景 | 期望 |
|---|---|---|---|
| 1 | `test_verify_max_diff_reads_metrics_not_toplevel` | precision gate 返回 `metrics.max_diff=0.42` | `VerifyStage.transition` 产 `PrecisionResult.max_diff=0.42`（非 0.0）；`error_signature` 含 `0.420000` |
| 2 | `test_precision_result_carries_per_case_and_bottleneck` | runner 返回 per_case/bottleneck | `PrecisionGate.evaluate` 的 `metrics` 含 per_case/bottleneck；`PrecisionResult` 承载之 |
| 3 | `test_deployer_extract_behavior_unchanged` | `DeployStage` 调 `Deployer.deploy` | `DeployResult` 与抽前一致（run_package/wheel/smoke_passed 等）；既有 DeployStage ST 全绿 |
| 4 | `test_cli_redeploy_calls_deployer` | `redeploy` CLI | 调 `Deployer.deploy`，per-op 覆盖安装，输出 DeployResult 摘要 |
| 5 | `test_cli_run_cases_outputs_diff_and_logpath` | `run-cases` CLI | 调 `NPURunner.execute`，输出 max_diff+per-case diff+dumptensor 日志路径（落盘） |
| 6 | `test_state_debug_fields_roundtrip` | State 加 `debug_iterations`/`debug_result` | `to_snapshot`→`from_snapshot` 往返不丢字段（防 P48 类反序列化漏建） |
| 7 | `test_precision_debug_stage_actions_dispatches_agent` | `PrecisionDebugStage.actions` | 派发 debug agent，消息以 `/ascendc-precision-debug` 开头，输入契约=code+cases+golden |
| 8 | `test_precision_debug_transition_all_pass_advances` | agent 返回全通过 | `debug_result.passed=True`；`resolve_condition → "default"`（线性后继） |
| 9 | `test_precision_debug_exhausted_halts` | `debug_iterations >= max` | `resolve_condition → "exhausted"` → route `("__halt__","escalation")`；回退最佳 commit |
| 10 | `test_precision_debug_best_commit_rollback` | 轮数耗尽、最后一轮更差 | `transition` 回退到 max_diff 最小的 commit（非最后一轮） |
| 11 | `test_precision_debug_compile_fail_instage_selffix` | agent 改坏、build 失败 | stderr 给 agent，in-stage 自修，不回 codegen（TRANSITION_TABLE 无 `precision_debug → codegen`） |
| 12 | `test_precision_debug_crash_on_uncaught_failure` | actions crash | `on_uncaught_failure` 自增 `debug_iterations` + `debug_result` crash-failed；`resolve_condition` 走 exhausted 分支 |
| 13 | `test_precision_debug_blocking_issues_visible` | 精度未通过 | `blocking_issues` 返回含 max_diff + failing_cases 的 issue（loopback/止损日志显原因，修 P53 第 2 点同类） |
| 14 | `test_route_precision_failed_to_debug_stage` | `self_evolve_op` verify precision_failed | route `("precision_debug","corrective")`（非 codegen） |
| 15 | `test_route_build_failed_still_codegen` | verify build_failed | route `("codegen","corrective")` 不变（编译保证不变） |
| 16 | `test_debug_skill_self_contained` | skill 取出校验 | schema 在 skill 目录内、不读自身目录外资源、不依赖 DevKit MCP（§2.1/§2.2） |

用例 1-2 守护 D8（phantom 修复）；3 守护 D3（Deployer 抽取无回归）；4-5 守护 D11（CLI）；6 守护 P48 类反序列化（F）；7-13 守护 D（stage 行为）；14-15 守护 D1（路由分流）；16 守护 §2.1（skill 即插即用）。

测试落点：复用既有 verify/deploy/state/graph_executor 测试文件（能合并不新开）；CLI 测试落 `cli/commands/` 既有测试模式；stage 测试用 StubBackend mock agent（UT，§3.5/§3.8）。

---

## 5. 验证

- **UT 全量绿**（含 §4 的 16 个新用例 + 既有 verify/deploy/state/registry/TRANSITION_TABLE 回归 0 退化）。
- **非 heavy ST 全绿**：含 `precision_failed → precision_debug` 端到端路由（真实 `dispatch` + mock agent，断言进 debug stage 不进 codegen）+ debug stage 收敛兜底（mock agent 轮数耗尽 → `exhausted → __halt__` + 回退最佳 commit）+ CLI `redeploy`/`run-cases`（mock `Deployer`/`NPURunner`）+ resume（debug 字段往返）+ 既有 verify/deploy/loopback/stagnation/escalation e2e 0 退化。
- **heavy_llm（按 §3.11 不默认跑）**：`PrecisionDebugStage` 是真实 LLM agent 全流程迭代 + 真实 NPU 部署验证 = heavy_llm（§3.11 判据：真实 LLM 全流程、分钟级、token 高）。UT/非 heavy ST 用 mock agent + 故障注入覆盖编排逻辑（路由/状态/收敛/回退）；**特性交付/PR 合并前由用户决策跑一次真实 self-evolve e2e**（真实 agent 迭代修精度，§3.9 真实链路守护不缺席）。执行前向用户列待跑项 + 预估耗时/成本。

---

## 6. 不在本次范围

- **P53 第 2、3 点**（loopback 无 blocking_issues / codegen 无消费自检）：被 B 绕开（精度失败不走 verify→codegen），不修（修了是死代码）。D8 只修第 1 点（phantom 字段，独立 bug）。
- **`generate_ascendc` / `generate_ascendc_dev` 的 `precision_failed → codegen`**：倾向不改（单算子生成流无 in-stage 闭环 + debug workflow 复用需求），L4 实施时静态核对确认。
- **「交互式挂起问人」人工决策 Stage**：[human-review-as-stage] 独立方向，B 用既有 `__halt__`+落盘交人（D9），不预占。
- **training-time loss 迭代**（self-evolution-design.md §2.2 (b)）：正交，B 只做 inference-time (a)。
- **codegen 编译门**：不新增（编译保证由 `VerifyStage.BuildInRepoGate` 兜，D1）。
- **debug stage 的 stage 级 loopback**：倾向单 agent 会话内跑满 max 轮（stage 只跑一次），是否需要 stage 级 `precision_unresolved → precision_debug` loopback 待实施时确认（D 的 `resolve_condition` 说明）。

---

## 7. 实施期冻结决策（as-built，2026-07-09，覆盖 §2.3/§2.4/§6 待定项）

实施期就原 spec 的若干待定项拍板，记录如下（L4 产权，冻结）：

### 7.1 D — `fail_strategy="halt"` + 不 override `on_uncaught_failure`（方案 a）

- 原 spec §2.4 倾向 `fail_strategy="continue"` + `on_uncaught_failure` 自增 `debug_iterations`。
- **冻结**：`fail_strategy="halt"`，**不** override `on_uncaught_failure`。agent 崩 → 走 P46 `_stage_failed` 既有止损路径 → `resolve_condition` 走 `exhausted` → `("__halt__","escalation")` 交人。
- **理由**：精度调试 agent 崩溃（如 OOM / tool 不可用）属灰区，halt 交人优于 continue 反复重试空耗；复用 P51/P46 既有止损出口，不为本 stage 新增 crash 处理分支（§1.2 架构合理 + [[failure-routing-loopback-under-uncertainty]] —— 崩溃这种不确定性最终交人）。

### 7.2 D — 无 stage 级 loopback（单 agent 会话内闭环）

- 原 spec §2.4/§6 待定：是否需要 stage 级 `precision_unresolved → precision_debug` loopback。
- **冻结**：**不需要**。`PrecisionDebugStage.resolve_condition` 只返 `"default"`（全通过，线性后继）/`"exhausted"`（未通过）；`TRANSITION_TABLE["precision_debug"] = {"exhausted": ("__halt__","escalation")}`，无 `precision_unresolved` 边。
- **理由**：闭环在**单次 agent 会话内**跑满 `default_max_iterations=5` 轮（改码→commit→redeploy→run-cases→日志→再改），stage 只派发一次 agent。stage 级 loopback = 跨会话重启 agent，丢上下文 + 频繁启 agent 耗时（P54 三硬伤之二），与 in-stage 闭环初衷相悖。轮数耗尽即交人，不无限循环。

### 7.3 C — 分层修正：L1 CLI → L2 `DebugService` → L3（§1.1）

- 原 spec §2.3 倾向 CLI「直接调 `NPURunner.execute`」。
- **冻结**：L1 `cli/commands/debug.py` 是薄壳 click wrapper，**只 import L2 `application.debug_service.DebugService`**（+ L1/L4），不直接 import L3/L6/L7。逻辑落 L2 `DebugService`：
  - `redeploy` → `Deployer.deploy`（L3）+ 落盘 `last_deploy.json`；
  - `run_cases` → `run_precision_cases`（L3，见下）+ 落盘 `result.json`/`run.log`。
- **理由**：§1.1 七层分层硬约束 L1→{L2,L4}，L1 直连 `adapters.npu.runner`（L6）/`orchestration.*`（L3）/`infra.workspace`（L7）= 4 处越层，`test_layer_dependencies` 拦截。L2 可达 L3/L4/L7，是 CLI 的正确 delegate 层（同 `run_cmd`→`dispatcher`、`VerifyStage.preflight_*`「L3 持有 L6 探针供 L2 调」既有模式）。

### 7.4 C/§2.5 — 抽 `run_precision_cases`（L3 单一 runner 装配路径）

- 原 spec §2.3 提「复用 `PrecisionGate` 的 runner 组装逻辑，抽共享或直接调 runner」。
- **冻结**：抽 L3 模块函数 `orchestration.stages.verify.run_precision_cases(op_spec, test_cases, npu_id, golden_contract, deploy_result, callable_target, chip_version, log_dir=None) → dict`，承载 `NPURunner(chip_version)` 实例化 + `execute(...)` 调用。`PrecisionGate.evaluate` 与 `DebugService.run_cases` **共用**它（§2.5 单一通路）。
- **职责切分**：runner 装配归 `run_precision_cases`；**stub 兜底策略归调用方**——gate 在 `enable_stubbed` 时 try/except 回 stub（`_stub_result`），CLI `run-cases` 不 stub、异常如实上抛（§3.4/§3.7 不掩盖）。`log_dir`（D7）经此函数透传给 `NPURunner.execute`。
- **未动 `perf.py`**：perf 的 `runner.execute` 签名不同（无 golden/deploy/callable_target，perf 测量），非同一装配职责，不强行合并（[[avoid-overdesign-prefer-reuse]]）。

### 7.5 E — `generate_*` 不改（L4 §6 静态核对确认）

- 静态核对 `precision_failed` 消费者：`generate_ascendc` / `generate_ascendc_dev` 的 `verify precision_failed → codegen` **保持不变**（`test_precision_debug_routing` + `test_loopback.test_generate_ascendc_transition_table` 守护）。仅 `self_evolve_op` 改走 `precision_debug`。
- **理由**：单算子生成流无 in-stage 闭环 + debug workflow 复用需求；`generate_*` 精度失败回 codegen 合理。

### 7.6 绿-A — as-built 与 §2.1 一致

- `VerifyStage.transition` 从 `gate_result["metrics"]` 读 `max_diff`（修 phantom 0.0）；`PrecisionResult` 扩 `per_case: list[CasePrecision]` + `bottleneck: str` + `stubbed`；`PrecisionGate.evaluate` metrics 含 `max_diff/actual_ms/stubbed/bottleneck`；`VerifyStage.error_signature` 读真实 `precision_result.max_diff`。与 §2.1 一致，用例 1-2 守护。

### 7.8 H — skill 归独立 plugin `stage-precision-debug`（plugin=stage 惯例）

- 初版把 `ascendc-precision-debug` 塞进 `stage-codegen` plugin。核对后发现既定惯例是 **plugin 边界 = stage 边界**（`stage-codegen`/`stage-design`/`stage-perf`/`stage-requirement`/`stage-testdesign` 各对应一个 stage），而 `precision_debug` 是独立 stage（独立 `name`、独立进 `_SELF_EVOLVE_STAGE_NAMES`、独立 TRANSITION_TABLE 分支），塞进 stage-codegen = plugin 名与 stage 名错位。
- **冻结**：新建 `stage-precision-debug` plugin（`.claude-plugin/plugin.json` + `skills/ascendc-precision-debug/SKILL.md`），skill 迁入。agent manifest `plugins: [stage-precision-debug, stage-codegen, shared]`——核心 skill 在 stage-precision-debug；复用 stage-codegen 的 `ascendc-dumptensor`（dump API 用法）+ `ascendc-op-dev-coding`（改算子代码参考）；shared 提供硬件参数/API 知识。
- **即插即用不受影响**（§2.1）：skill 文本对 `ascendc-dumptensor` 是 skill-name 软指针（TUI 经 plugin 加载解析，非文件路径读），核心方法论（三段法/用例优先级/缺陷模式）自包含于 SKILL.md。`test_precision_debug_selfcontained` 守护。

### 7.7 验证结果

- **UT 全量**：1700 passed（含 §4 的 16 用例 + `test_layer_dependencies` + 既有 verify/deploy/state/registry/TRANSITION_TABLE 0 退化）。
- **非 heavy ST**：125 passed（`precision_failed → precision_debug` e2e 路由 + debug stage 收敛兜底 + CLI redeploy/run-cases + resume debug 字段往返 + 既有 verify/deploy/loopback/stagnation/escalation 0 退化）；7 heavy_llm 按 §3.11 deselected。
- **heavy_llm（未跑，§3.11）**：`PrecisionDebugStage` 真实 LLM agent 全流程迭代 + 真实 NPU 部署 = heavy_llm，特性交付/PR 合并前由用户决策跑一次真实 self-evolve e2e（§3.9 真实链路守护）。本次未覆盖 heavy_llm：`PrecisionDebugStage` 真实 e2e。
