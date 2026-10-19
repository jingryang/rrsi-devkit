# P51 — verify（continue stage）硬崩溃控制流实施方案（第四层）

> 状态：**已完成 ✅**（2026-07-08）。UT **1653** + 非 llm ST **116** 全绿（0 回归，含 P51 crash-routing slow ST `test_loopback_e2e.py::TestP51VerifyCrashRouting` 2 例：真实 `dispatch` + 故障注入，infra→halt / gray→loopback→`exhausted→__halt__`，均断言下游不跑）；16 heavy_llm 按 §3.11 未默认跑（P51 是控制流非 §3.9 LLM 对象，heavy_llm 不增覆盖）。
> 层级：**第四层 / 实施方案**。改哪个符号、什么顺序、怎么验证。
> 覆盖问题：P51（L1 `06-problems.md`）。方案分析见 L3（选项 E，灰区默认 loopback + 最终 halt 交人）。
> L2：step 26。
> 约定：按符号定位（不写 file:line）；外部依赖只读；TDD 红→绿（§3.1）。

---

## 1. 设计决策（冻结）

### 1.1 二元分类器：非可修 → halt；其余 → loopback（灰区折叠进「其余」）

L3 §6.2 用户拍板「灰区默认 loopback」的直接推论：分类器**只需自信地识别「非可修」类**，其余一律 loopback——

- **非可修**（→ halt）：infra（503/429/401/403，复用 P50 `_INFRA_ERROR_MARKERS`）+ 框架/状态层 crash（反序列化、AttributeError/KeyError/TypeError 访问**非代码对象**）。
- **其余**（→ loopback）：codegen 生成的 kernel 崩（编译错/segfault/精度全错/逻辑错）+ 真·灰区。二者路由相同（回 codegen），由止损（§1.4）兜底。

**不单独建「可修类」探测器**： confidently non-fixable 之外全 loopback，正好实现「宁可浪费 token 不错过修复机会」。这是 §1.2「可扩展」——同类新 crash（未来新 infra 错误码、新框架异常）只要落进「非可修」或「其余」即自动正确归位。

### 1.2 落点：`GraphExecutor._execute_atomic` 的 except 分支（P46 先例）

P46 已确立「硬崩溃的控制流出入口在 `_execute_atomic` except 分支」（halt 侧在那里设 `_stage_failed`）。E 在**同一出口**补 continue 侧：分类异常 → 非可修设 `_stage_failed`（halt，镜像 P46）；其余走 §1.3 hook + 让 `_execute_sequential` 的既有路由接管。

### 1.3 新 Stage hook `on_uncaught_failure(state, exc) -> State`（默认 no-op）

`_execute_atomic` except 分支在「其余」分支调用 `node.stage.on_uncaught_failure(state, e)`。base `Stage` 默认 `return state`（不动，其它 stage 零影响）；**仅 verify override**：自增 `verify_iterations` + 置 `build_result` 为 crash-failed（routing 信号；真实崩因已在 `last_error`）。

为何是 hook 而非「transition 带 crash-result」或「graph_executor 直接改 verify_iterations」：
- transition 契约是 `state + action_result → state`，crash 无 action_result，塞哨兵污染所有 stage 的 transition 契约（更差）。
- graph_executor 改 verify_iterations 跨层泄露 stage 私有字段（违反「stage 拥有自己的 transition/计数」）。
- hook 把「crash 记账」留在拥有 `verify_iterations` 的 stage 里，符合既有 hook 模式（`error_signature`/`loopback_feedback`/`is_satisfied` 等可选 hook 均默认 no-op）。

### 1.4 止损复用 `verify_iterations → "exhausted" → __halt__`（不改）

verify 反复 loopback 的既有止损：`verify_iterations >= effective_max_iterations(3) → resolve_condition 返回 "exhausted" → TRANSITION_TABLE ("__halt__", "escalation")`。hook 在 crash 时自增 `verify_iterations`，故 **crash-loopback 与软失败-loopback 共用同一止损、同一出口**——这正是「最终 halt + 落盘交人」（L3 §6.2）。`resolve_condition` **不改**：hook 置的 crash-failed `build_result` 走其既有 `build_failed`/`exhausted` 分支。

> 静态核对（L3 §6.2 已纠正）：codegen 的 `codegen_consecutive_failures` 熔断**不**承接口 verify-loopback 止损（codegen 在 verify-loopback 里多半成功、清 0）。止损职责：codegen breaker 管 codegen 自身连续崩；verify `verify_iterations→exhausted` 管 verify 反复不过。P51 用后者。

### 1.5 「最终交给用户决策」= 既有 `exhausted → __halt__`（escalation）

非可修 crash → `_stage_failed`（halt）；灰区/可修 crash 反复 → `exhausted → __halt__`（escalation，workflow.py 注释明示 human triage）。二者都落 `__halt__`/terminal + `last_error` 完整落盘 = 移交人工。**不新增「交互式挂起问人」出口**（[human-review-as-stage] 独立方向，L3 §8 已划界）。

---

## 2. 改造点

### 2.1 A：`_execute_atomic` except 分支（graph_executor）

现 continue 分支：mark node `"failed"`、return。改为（在 mark failed 之前/同时）：

1. `cls = _classify_uncaught(e)`（新模块级谓词，复用 P50 `_INFRA_ERROR_MARKERS` + 加框架/状态层 marker）。
2. `state = state.with_updates(last_error=ErrorFeedback(stage_name=node.name, error_type=cls, message=_safe_msg(e)))`（可诊断 §1.2——崩因落盘）。
3. `if _is_non_fixable(cls): state = state.with_updates(_stage_failed=("aborted", node.name))`（halt，镜像 P46 halt 分支格式）。
4. `else: state = node.stage.on_uncaught_failure(state, e)`（hook 记账；base no-op）。
5. mark node `"failed"`（既有）；return。

> halt stage（`fail_strategy=="halt"`）既有 P46 分支保留不变——P46 设 `_stage_failed` 无条件；本 A 只对 **continue** stage 加分类。判断顺序：先 P46 的 `fail_strategy=="halt"` → `_stage_failed`（不变）；else（continue）→ 走 §1.2 分类。

### 2.2 B：`Stage.on_uncaught_failure`（base + verify override）

- base `Stage`：加 `def on_uncaught_failure(self, state, exc): return state`（默认 no-op）。
- `VerifyStage.on_uncaught_failure`：`return state.with_updates(verify_iterations=state.verify_iterations + 1, build_result=_crash_build_result(exc))`。
  - `_crash_build_result(exc)`：`BuildResult(passed=False, stderr=<safe msg>)`——routing 信号（让 `resolve_condition` 既有 `build_failed`/`exhausted` 分支生效）；真实崩因在 `last_error`。

### 2.3 C：分类谓词 `_classify_uncaught` / `_is_non_fixable`（graph_executor 模块级，复用 P50）

- `_INFRA_ERROR_MARKERS` 直接 import 自 P50（codegen 侧）；加 `_FRAMEWORK_STATE_MARKERS`（反序列化词、`AttributeError`/`KeyError`/`TypeError`/`TypeError` 在 dict/list/None 上访问 `.inputs`/`.xxx` 等 framework 对象的模式）。
- `_classify_uncaught(e) -> str`：infra marker → `"infra"`；framework marker → `"framework"`；else → `"unclassified"`。
- `_is_non_fixable(cls) -> bool`：`cls in {"infra", "framework"}`。
- 单一分类源（[avoid-overdesign-prefer-reuse]）：P50 已有 infra 分类，E 扩同源到 verify 边界 + 补 framework 维度。

---

## 3. 实施顺序（TDD 红→绿）

1. **红**：写 §4 全部用例（先失败——现 continue-crash 推进下游、不分类、不止损）。
2. **绿-C**：`_classify_uncaught`/`_is_non_fixable` + framework markers（纯函数，单测先行）。
3. **绿-B**：`Stage.on_uncaught_failure`（base no-op）+ `VerifyStage` override。
4. **绿-A**：`_execute_atomic` except 分支接分类 + hook + halt/loopback 分流。
5. **回归**：UT 全量 + 非 heavy ST（§5）。

---

## 4. TDD 用例（红→绿）

| # | 用例 | 场景 | 期望 |
|---|---|---|---|
| 1 | `test_classify_infra_crash` | 503/channel/429 异常 | `_classify_uncaught → "infra"`；`_is_non_fixable → True` |
| 2 | `test_classify_framework_state_crash` | AttributeError `'dict' has no attribute 'inputs'`（P48 实例形） | `→ "framework"`；`_is_non_fixable → True` |
| 3 | `test_classify_codegen_crash_unclassified` | segfault / 自定义 RuntimeError（kernel 崩） | `→ "unclassified"`；`_is_non_fixable → False`（→ loopback） |
| 4 | `test_continue_crash_non_fixable_halts` | verify continue stage 抛 infra 异常 | `_stage_failed` 被设（halt），不推进下游；node `"failed"` |
| 5 | `test_continue_crash_framework_halts` | verify 抛框架/状态层异常 | 同 4（halt） |
| 6 | `test_continue_crash_codegen_loopbacks` | verify 抛 kernel 崩（unclassified） | 不设 `_stage_failed`；`verify_iterations` +1；`build_result.passed=False`；`resolve_condition → "build_failed"`（route→codegen loopback） |
| 7 | `test_continue_crash_gray_defaults_loopback` | 无法归类的异常 | 同 6（默认 loopback，非 halt）—— §6.2 灰区 loopback |
| 8 | `test_crash_loopback_stop_loss_exhausted_halt` | 同一 unclassified crash 反复（mock verify_iterations 达 max） | `resolve_condition → "exhausted"` → route `("__halt__","escalation")`（止损交人） |
| 9 | `test_halt_stage_crash_still_halt_unconditional` | halt stage 抛任意异常 | `_stage_failed` 无条件设（P46 行为不变，回归守护） |
| 10 | `test_on_uncaught_failure_default_noop` | base Stage（非 verify）crash | hook 返回 state 不变（其它 stage 零影响） |

用例 6/7 是 §1.1 灰区折叠的核心：unclassified（codegen + 灰区）统一 loopback。用例 8 守护止损交人。用例 9 回归守护 P46 不被 E 回归。

测试落点：复用既有 graph_executor / verify 测试文件（能合并不新开）。纯逻辑/编排用例，StubBackend，标 UT（§3.5/§3.8）。

---

## 5. 验证

- **UT 全量绿**（含 §4 的 10 个新 P51 用例 + 既有 `_execute_atomic`/verify/runner/P46 回归 0 退化）。
- **非 heavy ST 全绿**：含 continue-stage crash 端到端（`TestP51VerifyCrashRouting`：infra crash→halt 下游不跑；gray crash→loopback→`exhausted→__halt__` 止损 + 下游不跑，真实 `dispatch`+故障注入）+ 既有 loopback/stagnation/escalation e2e + resume。
- **heavy_llm（按 §3.11 不默认跑）**：P51 是确定性控制流（分类谓词 + 路由分流），非 §3.9 LLM 行为对象，UT 充分覆盖；特性交付/PR 合并前由用户决策是否跑一次含真实 verify-crash 的 self-evolve e2e。

---

## 6. 不在本次范围

- **P52（resume 因果有效性，已闭环）**：P51 从源头减少「downstream completed on stale」（非可修 halt → 下游不跑）；P52 防御性兜底无论状态怎么来。互引用。
- **「交互式挂起问人」人工决策 Stage**：[human-review-as-stage] 独立方向，P51 用既有 `__halt__`+落盘交人，不预占。
- **不改 `fail_strategy` 声明、不改 TRANSITION_TABLE、不改 verify `resolve_condition`**（hook 置 build_result 让既有分支生效）。
- **不改 codegen 侧 `_classify_error_type`/熔断**（E 只**复用**其 infra marker，不修改 P50 已闭环逻辑）。
