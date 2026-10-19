# Membase codegen build-retry 空转根治 — 实施方案（L4）

> 改哪个函数 / 什么顺序 / 怎么验证。动手前写。问题事实见 `01-problems.md`，选项/取舍见 `02-analysis.md`。
> 关联：阶段 1 已落地（`deploy.py` build 失败 footer 富化，记忆 `codegen-signature-footer-phase1`）。

## 0 实现选型：deploy 层 advisory（不整体搬 agent 循环）

L3 决策 1 选「框架驱动 build-retry」。本 L4 取其**最轻实现**：不动 codegen 的 in-session redeploy 循环
（`_actions_membase` + prompt 1199-1219），而是在 **`deploy.py` 的 build 失败路径**加「错误分类 + per-op
计数 + gradient 策略提示」，经阶段 1 的 footer 通道送达 agent 每轮读的 `subprocess/*.log`。

- **为什么最轻**（四把尺子）：可维护（复用阶段 1 footer + `build_log_scanner`，单一改动面 `deploy.py`）；
  可扩展（新错误类加一条正则）；可诊断（分类+计数都进 log，框架可见）；架构合理（build 失败分类归
  L3 deploy 层，agent 仍只管生成，职责不变）。
- **advisory 而非硬 gate**：框架不拒绝 redeploy，只把「这是第 N 次同类失败 + 当前该修复/换策略/预算告急」
  写进 agent 必读的 log。契合用户「有修复可能就不 halt」原则——硬 gate（拒绝 redeploy）作为后续可收紧项，
  当前不做（避免误伤合法的同策略修复）。
- **不干扰 precision_debug**：precision 自有 `corrective_cycles` 约束其循环；本机制只追加信息到 build 失败
  日志，不改控制流，precision 的 build 失败同样得到分类（有益无害）。

## 1 改动清单（顺序 = 实施顺序）

### 改动 1 — `domain/build_log_scanner.py`：新增 `classify_build_error`

纯函数 `classify_build_error(text: str | None) -> str`，返回 `C-API` / `C-SYM` / `C-TYP` / `C-LNK` /
`unknown`。正则口径对齐 `.claude/skills/ascendc-op-dev-coding-regbase/scripts/classify_compile_error.sh`
的 C-API/C-SYM/C-TYP/C-LNK 桶，但**用 Python 实现**（不复用 shell 脚本——框架不耦合 skill 脚本，§2.1；
两源一致性问题登记为后续 tech debt，统一收敛到 domain 层）：
- `C-API`：`no matching function for call to` / `no member named` / `too many arguments` / `too few arguments`
  （签名/重载不匹配——阶段 1 签名指路的主簇）。
- `C-SYM`：`undefined reference` / `undeclared identifier` / `has not been declared`。
- `C-TYP`：`cannot convert` / `no viable conversion` / `incompatible type` / `static assertion`。
- `C-LNK`：`ld returned` / `undefined symbol` / `cannot open .*\.so`（注意：纯链接器 `cannot open .o`
  已被 `scan_kernel_compile_errors` 的结构化 marker 覆盖；这里只补 `.so`/symbol 类）。
- 多类命中时按 **C-API > C-TYP > C-SYM > C-LNK** 优先级返回（签名类最可修、最值得指路）。

### 改动 2 — `domain/build_log_scanner.py`：新增 `build_retry_gradient_section`

纯函数 `build_retry_gradient_section(error_class, class_count, total_count, budget) -> str`，按
Regbase retry-gradient（`ascendc-dev-s5-compile.md:112-122`）产出策略提示：
- `class_count == 1`：「同类首次：定位错误→修复→重编译（同策略）」
- `class_count == 2`：「同类第 2 次：**换策略**——重新审视设计决策/实现方案，勿重复同一改法」
- `class_count >= 3` 或 `total_count >= budget`：「预算告急（同类 N 次/共 M 次）——若仍无进展考虑升级
  （回上游设计 / 报告 halt 由编排器决策）」
- 返回带标注段（与阶段 1 footer 同一 `=== 框架错误分析 ===` 围栏内）。无错误类（`unknown`）→ 返回 ""。

### 改动 3 — `orchestration/stages/deploy.py`：retry-state 文件 + 接线

- retry-state 文件：`ws.subprocess_log / "build_retry_state.json"`（per-run 单文件，JSON：
  `{"per_class": {<class>: <count>}, "total": <count>, "last_class": <class>}`）。
  - **已知简化**：per-run 单文件；若一个 run 跑多 op（批跑非典型，batch 通常 per-op 独立 run）会共享计数。
    后续按需加 op key（需 op_name 传入 `_run_command`）。
- `Deployer` 新增 `_read_retry_state(ws)` / `_bump_retry_state(ws, error_class) -> (class_count, total)`：
  best-effort 读写（文件缺失/损坏 → 视作空状态，不崩；§1.2 宽容兜底）。
- `_build_failure_footer(stage, stdout, stderr)` 扩展：在阶段 1 footer（clang 摘要 + 签名指路）基础上，
  追加 `classify_build_error` + `build_retry_gradient_section` 的产出（需 `ws`——签名扩展 `_build_failure_footer`
  入参加 `ws`，调用点 `_run_command` 两条失败路径传 `ws`）。
- budget 默认值复用 codegen `max_rounds` 语义（不强引入新配置；取 `min(class_count>=3, total>=?)`，
  total budget 用阶段 1 已有的 `max_rounds` 上限作软参照，不硬 gate）。

### 改动 4 — 测试（TDD，先红后绿）

`tests/ut/domain/test_build_log_scanner.py`：
- `classify_build_error` 各桶命中 + 优先级（多类命中）+ `unknown` + None/空。
- `build_retry_gradient_section` 三档（1/2/≥3）+ unknown→"" + 标注段格式。
`tests/ut/orchestration/test_deploy.py`：
- `_bump_retry_state` 读写（首次/累加/文件损坏容错）。
- 端到端：`_run_command` build 失败（mock RC≠0 + C-API stderr）→ 持久化 log 含「分类 C-API」+「gradient 策略」+
  计数（第 2 次同类→「换策略」文案）。

## 2 验证

- TDD 先红后绿：改动 4 全部 UT。
- 回归：`tests/ut/` 全量 `--quick` 绿（阶段 1 已验证 3480 baseline，本步不回归）。
- **不跑 heavy_llm**：分类/计数/gradient 是确定性逻辑（非 §3.9 LLM 行为对象），UT 守护根因；
  端到端「codegen 签名类失败 turn 数下降」留真实批跑观测（非 PR 前硬门）。
- ST：deploy 真实 build 失败链路需 source CANN（§3.7 前置，本 shell 未 source）——UT 已 mock 覆盖。

## 3 不做（登记留存）

- **advisory 不够时的升级 = 框架驱动换策略，非 halt**：Phase 2 是 advisory（只提示不干预）。
  若实测 agent 无视提示仍同策略盲重试到 `max_rounds` 耗尽，符合原则的升级**不是**拒绝 redeploy
  （那是对「还有修复可能」的问题主动 halt，违反用户原则「可解决不 halt，只认外部超时/用户打断/
  预算耗尽」），而是把 build-retry 进一步移向框架驱动——同类失败 ≥N 次时框架**自动改变下一轮输入**
  （强制重查权威签名 / 切实现路径 / 回上游设计重新派生），继续试而非终止。即 L3 决策 1 选项 C
  的完整形态（本 L4 取其最轻实现 advisory，完整版是它的升级路径）。
- **op-keyed retry-state**：见改动 3 已知简化。
- **统一 classify 来源**（Python `build_log_scanner` vs skill `classify_compile_error.sh`）：登记 tech debt，
  后续把 skill 脚本收敛到调 domain Python（消除两源）。
- **真静默链接器案例**（70× `cannot open .o` 无 clang 行）：分类为 `unknown`、gradient 仍给「换策略/升级」提示，
  但无具体签名可指路——需 kernel_meta 信号，单列后续。

## 4 as-built（2026-08-02 落地）

实现与 §1-§2 一致，3 处与 L4 草案文字的偏差（均合理、已记测试）：

1. **`build_retry_gradient_section` 去掉 `budget` 形参**：草案文字列了 `budget`，但 §1 的 gradient
   判据实际只看 `class_count >= 3`（`_GRADIENT_ESCALATE_CLASS_COUNT`），`budget` 未进任何分支。
   删冗余形参（§1.4 不留过渡层），函数签名收敛为 `(error_class, class_count, total_count)`。
2. **gradient 用独立围栏 `=== 框架重试梯度 ===`，不并入阶段 1 的 `=== 框架错误分析 ===`**：
   阶段 1 footer 是 domain 纯函数（`build_log_scanner`，不依赖 ws/计数），gradient 是 deploy 层
   （需 ws + 持久计数）。并入会把 deploy 层状态塞进 domain 纯函数，越层；分两段围栏保持职责边界。
3. **`unknown` 一视同仁给 gradient**（非草案默认的 `return ""`）：L4 §3 明确要求真静默链接器案例仍给
   「换策略/升级」nudge；四把尺子（统一处理/新类自动归位/更可观测/无特判）也支持去掉 unknown 特判。
   generic「定位错误 → 修复」文本适用 unknown（错误未暴露，去查）。仅空串 `error_class`（实践中不会
   出现——`classify_build_error` 恒返回非空标签）返回 `""`。

落地文件：
- `src/ascendc_devkit/domain/build_log_scanner.py`：`classify_build_error` + `build_retry_gradient_section`
  + `_BUILD_ERROR_CLASSES` + `_GRADIENT_ESCALATE_CLASS_COUNT`。
- `src/ascendc_devkit/orchestration/stages/deploy.py`：`_BUILD_RETRY_STATE_FILENAME` +
  `_read_retry_state` / `_bump_retry_state` + `_build_failure_footer(stage, ws, stdout, stderr)` 扩参 +
  `_run_command` 两处失败路径传 `ws`。
- `tests/ut/domain/test_build_log_scanner.py`：`TestClassifyBuildError`(6) + `TestBuildRetryGradientSection`(4)。
- `tests/ut/orchestration/test_deploy.py`：`TestBuildRetryState`(9) + Phase 1 调用点改 `ws=None`。

回归：全量 `tests/ut/` **3499 passed / 7 skipped / 1 deselected**（baseline 3480 → +19），零回归。
