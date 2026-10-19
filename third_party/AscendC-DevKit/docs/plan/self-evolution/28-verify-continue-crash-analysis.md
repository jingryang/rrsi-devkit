# P51 — verify（continue stage）硬崩溃后照常推进下游 — 方案分析（第三层）

> 状态：**方案冻结**（2026-07-08）。主导方向 = 选项 E（失败根因分类驱动路由）；灰区默认值经用户拍板 = **loopback**（保修复机会优先）+ 最终交用户决策。A/B 降级为被 E 取代的静态策略。待立 L4。
> 层级：**第三层 / 方案分析**。选项 + 取舍 + 待定。
> 覆盖问题：P51（continue stage 硬崩溃的控制流语义）。
> 输入：run `20260707-091803-29a24f` resume 后 verify 崩而 workflow 不停的现象追问 + 用户主导的认知校正（路由应按失败根因分类）。
> **承接**：e2e-stability/02-analysis.md 的 P2+P3 分配表（verify=continue 的判据）+ P46（halt 侧硬崩溃已闭环）+ **P50（codegen 熔断器已做过同形 infra/logic 分类，E 的直接先例）**。P51 是 P46 的 **continue 侧对偶**。
> 约定：按符号定位（不写 file:line）；外部依赖只读。

---

## 1. 定位：P51 是 P46 的 continue 侧对偶

`fail_strategy` 二态（continue / halt）对**所有失败形态**（软失败 + 硬崩溃）的完整语义，目前只闭环了一半：

| | 软失败（gate 不合格 / 迭代耗尽，stage 正常返回） | 硬崩溃（`actions()`/`transition()` 抛异常） |
|---|---|---|
| **halt stage** | P35：runner 设 `_stage_failed` → break | P46：`_execute_atomic` except 分支补设 `_stage_failed` → break（**已修**） |
| **continue stage** | 分配表判据：`resolve_condition` → `TRANSITION_TABLE` 路由（loopback / 放行） | **P51：异常短路 `transition`/`resolve_condition`，loopback 不触发；P46 只给 halt 设 `_stage_failed`，continue 只 mark "failed" + 线性推进下游（待定）** |

P46 堵的是「halt stage 硬崩溃不停」；P51 要问的是「continue stage 硬崩溃照常推进到强依赖它的下游，对不对、要不要干预」。

---

## 2. 现状：分配表判据只覆盖软失败，硬崩溃是盲区

### 2.1 分配表给 verify=continue 的理由（e2e-stability/02-analysis.md 分配表）

```
| 验证型 | verify, perf | continue | 由 TRANSITION_TABLE 路由 |
```

这个「由 TRANSITION_TABLE 路由」**只在软失败路径成立**：`PrecisionGate.evaluate` 返回 `passed=False` → stage 正常返回 → `transition` → `resolve_condition` 读 gate 结果（build_failed/precision_failed）→ `TRANSITION_TABLE` 路由回 codegen（loopback）。

### 2.2 硬崩溃路径把路由短路了（机械层根因）

loopback 依赖 `resolve_condition` 返回 `"build_failed"`/`"precision_failed"`，而这俩 condition 是从 `build_result`/`precision_result.passed` 推出来的——这两个 result 在 `transition()` 里设置。硬崩溃发生在 `transition()` **之前**：

1. `actions()` 返回 `[RunGate(build), RunGate(precision)]`。
2. runner 执行 `_execute_actions` → 跑 precision gate → 崩（本 run 是 `tc.inputs` 访问 dict）。
3. 异常从 `_execute_actions` 传出（只接 `DecisionPendingError`，其它传播）→ 传过 for 循环 → `run_stage` 重抛。
4. **`transition()` 从未执行** → `build_result`/`precision_result` 没更新。
5. 回到 `_execute_sequential`，`resolve_condition` 照样被调用，但读到 **stale/None** 的 result → 返回 `"default"`（线性后继）→ 没回 codegen。

### 2.3 本 run 的具体崩溃根因 ≠ P51（已分离）

本 run verify 的 `'dict' object has no attribute 'inputs'` 是 **P48 类反序列化 bug**（`State.from_snapshot` 把 `list[TestCase]` 重建回 dict），已**单独修复**（`test_cases: list[TestCase]`）。**关键结论（用户追问的事实判定）**：这次失败**既不是算子问题、也不是 codegen 生成的代码问题**——崩在「消费 test_cases 准备精度跑」阶段，生成的 kernel 根本没被执行到。它是框架/状态层 bug。P51 是抽掉该 bug 后仍成立的控制流问题。

---

## 3. 认知校正（用户主导）：路由应按失败根因分类，而非静态 continue/halt

> **这是本 L3 的理论基石，由用户在讨论中提出，推翻了「A/B 二选一」的伪命题。**

### 3.1 错误的二分：verify 该 continue 还是 halt

前序讨论一度把问题框成「verify 策略选 continue（A）还是 halt（B）」。**这个二分是错的**。错在它把「失败后怎么办」当成 stage 的静态属性，而忽略了：**loopback 回 codegen 的唯一机制是「重新生成代码」，它只在失败属于「重生成能修」这一类时才有价值**。

### 3.2 正确的判据：失败根因分类驱动路由

> loopback 的价值命题是「代码错了就重写」。只有当失败根因在「codegen 生成的代码/文件」这一类时，重写才可能修好。失败根因不在这类（infra / 框架状态层 / 环境不可用）时，loopback 必然空转——重生成代码修不好一个反序列化 bug、也修不好一个 503。

按根因把失败分两类，路由随之分流：

| 失败根因类别 | codegen 能修？ | 正确路由 | 本 run 实例 |
|---|---|---|---|
| kernel 本身：编译错 / segfault / 精度差 / 精度全错 / 逻辑错（运行时崩在生成的 kernel 代码内） | 是 | **loopback** 回 codegen | （本 run 不是这类——崩在消费 test_cases，kernel 没被执行到） |
| infra：503 channel / 429 / 401 / 403 | 否 | **halt** | P50 已在 codegen 侧做 |
| 框架/状态层 crash：反序列化、AttributeError/KeyError/TypeError 访问非代码对象 | 否 | **halt** | **P48 反序列化（本 run）** |
| 环境不可用（CANN/NPU 缺） | 否 | 走既有 `EnvironmentNotAvailableError` 控制异常路径（已是另一套机制） | — |

### 3.3 这不是新架构——P50 已经拍过同一原则

**P50（codegen 熔断器）已经做了完全同形的分类**：把错误分成 `error_type="infra"`（agent 根本没跑过逻辑）vs 逻辑失败；infra 不计数、直接 halt；逻辑失败才计数/loopback。E 就是**把同一条分类原则从 codegen 熔断边界扩到 verify 路由边界**。已有先例、已被项目接受，符合 [[avoid-overdesign-prefer-reuse]]，符合 §1.2（同类新情况自动正确归位，而非每次打补丁）。

---

## 4. 选项（E 主导，A/B/C/D 为背景）

### 选项 E —— 失败根因分类驱动的 halt/loopback 路由（主导方向）

- **判据**：见 §3.2。codegen 可修 → loopback；不可修 → halt。
- **落点**：verify 的 `resolve_condition` 按分类返回 condition——可修类照旧 `"build_failed"`/`"precision_failed"`（loopback）；不可修类返回一个 halt condition（路由到 `__halt__`）。
- **吸收**：B 的 halt（给不可修类）+ 保留 loopback 价值（给可修类）+ C 的路由机制，但 condition **来自根因分类而非 stale state**。
- **为何主导**：它是唯一符合 §3.2 判据的选项——既不空转（不像 A），也不误杀 loopback（不像 B）。且复用 P50 已有分类模式。

### 选项 A —— 维持现状（continue + 接受硬崩溃推进下游）❌ 被 E 取代
continue 的韧性在「不可修类」失败上是空转 + 污染 loss 信号；E 保留 continue 的韧性价值（可修类 loopback）同时堵住空转。

### 选项 B —— verify 改 `fail_strategy="halt"` ❌ 被 E 取代
粒度太粗：halt 会把「可修类该 loopback」一起杀掉，丢 loopback 价值，且翻案分配表。E 只对不可修类 halt，可修类仍 loopback。

### 选项 C —— 异常路径也经 `resolve_condition` 路由（异常映射成 condition）⚠️ 被 E 收编为子机制
E 的「不可修类 halt」需要 crash 也能产生可分类的 condition——这正是 C 的机制。但 C 原表述「异常映射成 loopback」错了（不可修类不该 loopback）；E 把 C 的机制用在正确的分流上。

### 选项 D —— 区分「下游依赖型 continue」局部阻断下游 ⏸️ 正交，可叠加
D 解决的是「下游保护」（P52 的领域，见关联）；E 解决的是「本 stage 失败后该 halt 还是 loopback」。两者正交：E 决定 verify 自己的走向，P52/D 决定 verify 失败后下游怎么办。可叠加，不互斥。

---

## 5. 取舍（E 主导）

| 选项 | 落点 | 评价 |
|---|---|---|
| **E 根因分类路由（主导）** | verify `resolve_condition` 按分类 halt/loopback | ✅ 主导。唯一符合 §3.2 判据；复用 P50 分类模式；不空转不误杀 |
| A 维持现状 | 不改 | ❌ 空转 + 污染 loss，被 E 取代 |
| B verify→halt | 一声明 | ❌ 杀 loopback，被 E 取代 |
| C 异常→condition | 异常映射 | ⚠️ 机制被 E 收编（C 原述「映射成 loopback」错） |
| D 局部阻断下游 | 下游依赖图 | ⏸️ 正交，归 P52，可叠加 |

---

## 6. 落地约束（E 落地必须先过的两关）

### 6.1 约束一：机械 bug 必须先修（否则分类器没有真实 condition 可读）

§2.2 的机械根因——crash 跳过 `transition()` → `resolve_condition` 读 stale result → 返回假 `"default"`——**必须在 E 之前或同时修**。否则即便有完美的分类器，crash 之后 `resolve_condition` 拿到的还是 stale condition（其取值取决于 state 里残留的 `build_result` 是什么，非确定）。**正确的分类必须先能被产生出来，才能被路由消费**。

更尖锐的点是**可诊断性**：当前 crash 的路由后果（停/loopback/推进）取决于 stale state，而非 crash 本身——事后看不出为什么走了某条路。这本身是独立于 E 的可诊断性缺陷，无论 E 怎么定都该修。

修法方向：让 crash 也产生一个可分类的 condition（异常类型/标记 → condition），交 `resolve_condition` 按 §3.2 分流。具体落点（runner 还是 graph_executor 的 except 分支）待 L4 定。

### 6.2 约束二：分类可靠性 + 灰区默认值（已拍板）

**灰区的正确边界**（用户校正后）：分类其实相当干净，真灰区**极窄**——

- **明确可修**：编译错、segfault、精度差/精度全错、逻辑错（崩/错在 codegen 生成的 kernel 代码内）→ loopback。前版误把 segfault 当灰区是错的：segfault 几乎总是 codegen 生成了坏代码，**本就该 loopback**。
- **明确不可修**：infra（503/429/401/403）、框架/状态层 crash（反序列化、AttributeError/KeyError/TypeError 访问**非代码对象**）→ halt。
- **真灰区**：分类器确判不出属于上述哪一类的、极少见的情形。

**灰区默认值（用户拍板）**：**loopback**。理由（用户）：宁可浪费 token 也不想错过可能的修复机会——灰区判错时，loopback 最多空转烧 budget（且有熔断止损，见下），halt 则会直接扼杀一次本可成功的修复。机会不对称 → **偏 loopback**。

**「最终交给用户决策」的落地形态**（用户要求）：灰区**不**由系统自动判死。控制流为：灰区 → loopback（给修复机会）→ 若 loopback 反复修不好（被既有**验证侧止损** `verify_iterations >= max(3) → "exhausted" → TRANSITION_TABLE("__halt__", "escalation")` 止损）→ **halt + 完整根因落盘** → **把决策权交人**（用户离线看 events.jsonl / last_error，决策改需求 / 改代码 / 重跑 / resume）。即「halt 不是放弃，是带着完整诊断上下文移交人工」。`exhausted → __halt__` 本就是 verify 软失败耗尽迭代后的既有出口（workflow.py TRANSITION_TABLE 注释明示「human triage」），灰区 loopback 的最终止损复用它即可。

> **止损机制澄清**（静态核对纠正前版误述）：verify→codegen→verify 反复 loopback 时，**codegen 多半是成功的**（只是产出的新代码 verify 又拒），故 codegen 侧的 `codegen_consecutive_failures` 熔断**不会**因此 trip（它在 codegen 自身失败才 +1，codegen 成功就清 0）。真正给 verify 反复 loopback 兜底的是 **verify 自己的 `verify_iterations → "exhausted" → __halt__`**（`default_max_iterations=3`）。这两条止损职责不同：codegen breaker 管「codegen agent 自己连续崩」，verify exhausted 管「verify 怎么修都不过」。P51 灰区止损靠后者。
>
> **与 §6.1 机械 bug 的耦合（L4 必须处理）**：`verify_iterations` 在 `transition()` 里自增（verify.py），而硬崩溃发生在 `actions()`、`transition()` 根本没跑——故**裸 crash 路径连 verify 自己的止损都绕过了**（既不增 `verify_iterations`、也不设 result、`resolve_condition` 读 stale → "default" 线性推进）。L4 的机械修复必须保证：crash 被分类为「可修类 loopback」时**仍要推进 `verify_iterations`**，否则灰区 loopback 的止损形同虚设。

> **不需要新机制**：灰区默认 loopback 复用既有路由（"build_failed"/"precision_failed"）；止损复用既有 `verify_iterations → exhausted → __halt__`；halt+落盘移交复用既有 `__halt__`。P51 不新增「交互式挂起问人」出口（那是 [human-review-as-stage] 独立方向的范畴，见 §8）。

---

## 7. 待澄清（已收敛）

1. **灰区默认值**（§6.2）：✅ **已拍板 = loopback**（保修复机会优先）+ 最终 halt+落盘移交用户决策。前版「倾向 halt」被用户否决。
2. **分类器落点**：✅ 倾向复用 P50 的 `_classify_error_type`（单一分类源，[avoid-overdesign-prefer-reuse]）——把同形 infra/logic 分类从 codegen 边界扩到 verify 路由边界。L4 定具体形态。
3. **机械 bug（§6.1）的修法落点**：✅ 让 verify 的 crash 也产生一个可分类的 condition（runner 还是 graph_executor except 分支），L4 定。
4. **E 与 P52 的边界**：✅ 正交。E 管「verify 自己 halt 还是 loopback」；P52 管「verify 失败后下游 completed 是否作废」。分开落、互引用。P52 已先行完成（29-*.md）。

---

## 8. 与现有工作的关系

- **P50（E 的直接先例，已闭环）**：P50 在 codegen 熔断器做了 infra/logic 分类。E 把同形分类扩到 verify 路由边界。分类机制（`error_type` / `_classify_error_type` / `_INFRA_ERROR_MARKERS`）可复用。**注意止损职责不同**（§6.2 已澄清）：codegen 的 `codegen_consecutive_failures` 管「codegen agent 自己连续崩」；verify 反复 loopback 的止损是 verify 自己的 `verify_iterations → exhausted → __halt__`，**不是** codegen breaker（codegen 在 verify-loopback 里多半成功、清 0）。
- **P46（halt 侧对偶，已闭环）**：P46 让 halt stage 的硬崩溃设 `_stage_failed` 停住。E 的「不可修类 halt」复用 P46 的 `_stage_failed` 机制——halt 触发从「静态 fail_strategy=halt」变成「动态分类=不可修」。
- **e2e-stability/02-analysis.md 分配表**：E 不推翻 verify=continue（continue 在可修类域的 loopback 价值成立），但要求判据补「不可修类 halt」分支。是给判据补维度，不是翻案。
- **P48（本 run verify 崩的具体根因，已修）**：P48 类反序列化是 E「不可修类」的典型实例。修了 P48 不消除 E 的必要性（其它不可修类 crash 仍会触发同类控制流）。
- **P52（resume 因果有效性，正交，已闭环）**：P52 问「verify 失败后下游 completed 是否作废」。E 从源头避免「downstream completed on stale」产生（不可修类 halt → 下游不跑）；P52 是防御性不变式，无论状态怎么来的都兜住。互补。
- **[human-review-as-stage]（独立方向，不在 P51 范围）**：用户「最终交给用户决策」在本 L3 落地为「halt+落盘，离线交人」（复用既有出口，不新增机制）。若未来要把「人工决策」建模为**主动交互 Stage**（挂起问人、暂停 run 等用户裁决），那是 [human-review-as-stage] 独立设计方向的范畴，P51 不预占。

---

状态：**方案冻结**（2026-07-08）。主导方向 = 选项 E；灰区默认 = loopback（用户拍板）+ 最终 halt+落盘交人。下一步立 L4。L2 step 26 跟踪本条。
