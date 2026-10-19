# foreach/TensorList 算子 precision_debug 入口卡死 — 方案分析（L3）

> 调研中演进、拍板后冻结。本文列选项 + 取舍 + 理由，**不拍板**。
> 事实依据见同目录 `01-problems.md`（L1，产权所在）；本文只引用不重复。
> 面向三个 ERROR：P1（run_tests transition 崩溃）、P2（TensorList 契约不一致 → upstream halt）、
> P3（顶层 halt 消息误导）。

## 问题本质（一句话）

foreach 算子（`Tensor[]` 输入）的 precision_debug 入口被一条**契约链断点**卡死：requirement 把
TensorList 输入标成 `param_type=REQUIRED`（应为 DYNAMIC）→ runner 的 DYNAMIC 放行分支永不触发 →
用例 list-of-lists 全被 PD-CONTRACT 拒、harness 一个都不跑 → scope_guard 判 upstream → halt。
中途叠加一个框架次生崩溃（`max(real_errs)` 不滤 None）与一条误导性 halt 消息，把真实原因掩盖成
"TypeError 实现 bug"。

## 必须守住的不变式（方案不能破的）

1. **契约不一致要大声失败，不能静默宽容**（§1.13/§1.2）：runner 对「op_spec 声明 REQUIRED、
   用例却给 list-of-lists」的拒绝是**正确的可观测信号**——它暴露了上游契约缺陷，不应改成"吞掉"。
2. **契约的权威源是数据 + CANN 语义**（§1.13）：cann-bench 用例（list-of-lists）是 TensorList
   输入的真实形态；CANN 对动态列表必须 `ParamType(DYNAMIC)`（codegen 已在 op_def 实证）。REQUIRED
   是**需求层的误标**，改源头，不纵容 runner。
3. **判据用结构信号、不认算子**（§1.12/§1.10）：`is_list=true` → DYNAMIC 的派生、runner 的
   DYNAMIC 分支，都是结构信号；禁止为 foreach_norm 之类点名打补丁。
4. **halt 消息必须反映真实 halt 语义**（§1.2 可诊断）：halt 由什么触发（upstream/exhausted/…），
   消息就显示什么；`last_error` 只是 fallback，不能喧宾夺主掩盖语义原因。
5. **frame 层可自愈**：P1 的 TypeError 是"harness 中止"场景下的必然崩溃路径，框架应能在
   `max_err=None` 时正常收口（`best_real_max_err=None`、如实传递 0/20），把判定交给 scope_guard，
   而不是自己崩掉污染 last_error。

---

## P1 — `max(real_errs)` 对全 None 崩溃（框架 bug）

### 选项 A — 列表推导滤 None（最小、确定性）

**做法**：`real_errs` 构造时排除 `None`：
```python
real_errs = [e for c in queue_for_best
             if (e := c.get("max_err")) is not None
             and e != 999.0 and c.get("elapsed_ms", 0) >= 0]
"real_max_err": max(real_errs) if real_errs else None,
```

| 尺子 | 评估 |
|---|---|
| 可维护 | ✅ 一处表达式，语义直白（None=无数值结果，不是合法 diff） |
| 可扩展 | ✅ 任何"harness 中止/未跑出数值"场景自动收口，不依赖算子形态 |
| 可诊断 | ✅ `best_real_max_err=None` + `observed_issues` 如实传递，scope_guard 仍能看到上游信号 |
| 架构合理 | ✅ 修在收口处，不动路由；`best_*` 语义不变（999.0 仍是 crash 哨兵） |

### 选项 B — harness 中止时 transition 走 abort 分支（不解析 best metrics）

**做法**：检测到 `summary` 里有"harness 中止/无用例执行"标志时，走 abort 类似的短路路径，
不构造 `real_errs`。

| 尺子 | 评估 |
|---|---|
| 可维护 | ⚠️ 引入新的"中止"分支 + 标志，与 abort 路径语义重叠、易混 |
| 可扩展 | ⚠️ 需识别所有"中止"形态，漏判即复现 |
| 可诊断 | ⚠️ 把可正常收口的场景引向 abort 退火，可能误伤 |
| 架构合理 | ⚠️ 用控制流特例替代数据清洗，over-engineering |

**评估**：❌ 为"清理数据"引入路由分支，收益 < 复杂度。**否决**。

### 选取 A

`max()` 对含 None 列表崩溃是纯数据质量问题，选项 A 最小、确定性、可扩展（任何全 None 场景
自动归位），不动路由语义；不变式 5 直接满足。补充：**加 UT**——构造 failed_case_queue 全
`max_err=None` 的 `_summary`，断言 transition 不崩、`best_real_max_err=None`、
`passed_count=0`、`observed_issues` 透传。

---

## P2 — TensorList 契约不一致（op_spec REQUIRED vs 用例 list-of-lists）

> **为何单枚举（CANN 原生，非框架选择）**：REQUIRED/OPTIONAL（必选性）与 DYNAMIC（动态性）
> 本是两维度，但 CANN `OpParamDef::ParamType` 压成三值枚举（权威
> `ascendc-dev-knowledge/.../OpParamDef/ParamType.md`），一次只能填一个。对 `Tensor[]`（变长列表）
> 输入，唯一合法填值是 DYNAMIC——REQUIRED 是无效值，非"必选且非动态"的合法表达。框架 `param_type`
> 是对该枚举的忠实映射（§1.9），故派生 DYNAMIC = 修无效枚举值，非两维度二选一；"必选"对动态参数
> 在 CANN 层无独立通道（DYNAMIC 已隐含必作变长列表处理），各消费点（runner 闸门/codegen 渲染/
> deploy smoke）均不需"必选且非动态"组合。若未来需区分"必选/可选变长"，再引入独立 `required` 字段。

### 选项 A — 源头修正：requirement/op_spec 对 `is_list=true` 输入派生 `param_type=DYNAMIC`

**做法（两个层次，可叠加）**：
- **A1（LLM 引导）**：req-analysis skill/prompt 明确"TensorList 输入（`is_list=true`）必须标
  `param_type=DYNAMIC`（CANN 语义）"。软约束，依赖 agent 纪律。
- **A2（确定性派生）**：在 `OperatorSpec.from_dict`（或 `TensorSpec.from_dict`）加派生规则——
  原始 entry 声明 `is_list=true` 且 `param_type` 非 DYNAMIC 时，**强制派生为 DYNAMIC** 并
  WARN 暴露改写（§1.3 不留静默）。这是结构信号（§1.12），不认算子名。

| 尺子 | 评估 |
|---|---|
| 可维护 | ✅ A2 是单点派生（`from_dict` 唯一通路，§2.5），一处修、所有 op_spec 消费者（runner/cannbench 对齐）一起对 |
| 可扩展 | ✅ 同类 TensorList 新算子自动归位；A2 不依赖 LLM 纪律（A1 只是锦上添花） |
| 可诊断 | ✅ A2 WARN 暴露"REQUIRED→DYNAMIC 派生"，契约源头失真可追溯；与 codegen decision_log 已记录的矛盾互证 |
| 架构合理 | ✅ 修在契约产权层（requirement→op_spec），与"op_def 已是 DYNAMIC"对齐；runner 的 DYNAMIC 闸门保持正确不动 |

**风险**：A2 只覆盖"有 `is_list` 字段的 entry"。cann-bench proto/requirement 若没写 `is_list`
但实际是 TensorList，派生不触发——但那是另一个上游缺陷（缺结构声明），A2 对已声明的先纠正。
**后续增强（见 L4 §2b）已收敛该风险**：requirement 阶段从 proto.yaml 结构信号
（`inputs[].is_list` **或** `schema` 签名 `Tensor[]`）确定性判定 TensorList 并派生
DYNAMIC——即使 proto/requirement 无 `is_list` 字段，只要 proto 签名声明 `Tensor[]` 即触发。
另需核查 A2 不误伤：`is_list=true` 且显式 `param_type=OPTIONAL`（矛盾的边缘声明）——派生置 DYNAMIC
并 WARN，不静默。

### 选项 B — runner 宽容：REQUIRED 输入也放行 list-of-lists

**做法**：`runner.py:197` 的 `is_dynamic` 判据放宽为"param_type==DYNAMIC **或** 用例 shape 是
list-of-lists 就放行"。

| 尺子 | 评估 |
|---|---|
| 可维护 | ⚠️ 放宽判据会**静默掩盖上游契约缺陷**（REQUIRED 本不该收到多张量数据） |
| 可扩展 | ⚠️ 任何"误标 REQUIRED 但发多张量"的算子都被吞，坏信号不再可见 |
| 可诊断 | ❌ 违反不变式 1——把该大声失败的契约不一致改成静默接受 |
| 架构合理 | ❌ 用 runner 宽容掩盖 requirement 误标，把可解释的上游缺陷变成不可诊断的静默接受 |

**评估**：❌ 与 §1.13（golden/数据权威，错也可解释、不静默纠偏）冲突。**否决**——runner 该做的
不是接受，是报得更准。

### 选项 C — 仅增强 PD-CONTRACT 错误文案（可观测性辅修）

**做法**：`runner.py:217` 的 `must be list[int]` 报错，在"用例 shape 是 list-of-lists 但
op_spec param_type 非 DYNAMIC"时追加 hint：
`（op_spec 对该输入声明 param_type=REQUIRED，但用例给了多张量 list-of-lists —— 疑似 requirement
将 TensorList 输入误标 REQUIRED，应派生 DYNAMIC）`。

| 尺子 | 评估 |
|---|---|
| 可维护 | ✅ 纯文案，无行为改变 |
| 可扩展 | ✅ 对任何同类误标算子，错误都自解释 |
| 可诊断 | ✅ 直接指向 P2 根因，scope_guard/人一眼定位 |
| 架构合理 | ✅ 不改放行语义，只把已拒的坏信号讲清楚 |

### 推荐组合（§1.2：正确改动主修复 + 可观测性）

**主修复 = A2**（确定性派生 `is_list→DYNAMIC`）：构造性修正契约源头，runner DYNAMIC 分支自然
触发，cases 正常进精度循环；对齐 op_def 已有 DYNAMIC，消掉 codegen decision_log 记录的矛盾。
**辅修 = A1**（req-analysis 引导写 DYNAMIC）：让源头生产者直接写对，A2 只是确定性兜底。
**可观测性 = C**：PD-CONTRACT 报错自带根因 hint，即使 A2 覆盖不到的边缘场景（无 `is_list` 声明）
也能一眼定位。
**不采纳 B**：runner 保持大声失败（不变式 1/§1.13）。

**前置核查**（待决策点 1）：cannbench_eval / DevkitBackend 对 list-of-lists 的接受度——修完 A2 后
foreach 算子会真正进精度循环 + 走到 eval，需确认 eval 侧能吃 list-of-lists（cann-bench 自家
eval 能跑，devkit 侧是否一致待核）。若 eval 侧同样卡，则 A2 之外 eval 侧也要对齐（可能复用同一
DYNAMIC 派生后的 op_spec，或 loader 已规范化——见待决策点 1）。

---

## P3 — 顶层 halt 消息误用 last_error（掩盖真实原因）

### 选项 A — `__halt__` 分支优先用语义化 halt 原因

**做法**：`graph_executor.py:531-540` 的 `__halt__` 分支，构造 `halt_msg` 时先查
`state.debug_result.halt_reason`（precision_debug 已把 scope_reason 放进去，
`precision_debug_substages.py:1242`）或 stage 结构化 halt 原因；`last_error.message` 降为 fallback
（仅当无语义原因时用）。

| 尺子 | 评估 |
|---|---|
| 可维护 | ✅ 把「halt 消息 = 触发 halt 的语义」设为单一规则，不靠碰巧的 last_error |
| 可扩展 | ✅ 任何带 `debug_result.halt_reason` 的 halt 都自动透传（upstream 场景通用） |
| 可诊断 | ✅ 顶层消息直接显示 `upstream defect in [test_design]: <scope_reason>`，消除误导（不变式 4） |
| 架构合理 | ✅ 修在 halt 消息组装点，不动路由；`__escalate__:upstream` 分支（`graph_executor.py:485`）已示范该模式，A 把同一模式补到 `__halt__` |

**风险**：`state.debug_result` 在 `__halt__` 时是否已物化？`_sync_debug_result` 在
RunTestsSubstage/ScopeGuardSubstage transition 末端调用并 `state.with_updates(debug_result=dr)`
（`precision_debug_substages.py:1234-1253`），scope_guard halt 时应在。需 L4 时核查时序（若某路径
未物化，则 A 的 fallback 到 last_error 仍是安全的）。

### 选项 B — 把 `upstream` 路由改为经 `__escalate__:upstream`

**做法**：`workflow.py:563` `"upstream": ("__halt__","escalation")` → 走
`__escalate__:upstream`，让 `graph_executor.py:485-493` 的 upstream_defect 分支接管。

| 尺子 | 评估 |
|---|---|
| 可维护 | ⚠️ 改路由形态，`precision_debug` 组表 + `__escalate__` 分支都动，牵连其他 workflow |
| 可扩展 | ⚠️ 路由特例增多 |
| 可诊断 | ✅ 复用既有 upstream_defect 消息 |
| 架构合理 | ⚠️ 为"消息"改路由拓扑，把消息问题塞进控制流 |

**评估**：❌ 只为消息修路由，牵连大。**否决**——消息应在 `__halt__` 内部修（选项 A）。

### 选项 C — 消息里同时打 last_error + 语义原因（观测兜底）

**做法**：A 之外，把 `debug_result.halt_reason`（若存在）也打进日志/消息，两条都可见。

| 尺子 | 评估 |
|---|---|
| 可维护 | ✅ 纯追加，零风险 |
| 可诊断 | ✅ 即使 A 的优先级有边界 case 漏判，语义原因也不丢 |
| 架构合理 | ✅ 观测性辅修 |

### 推荐组合

**主修复 = A**（`__halt__` 优先语义化原因，last_error 降 fallback）。**观测辅修 = C**（语义原因
与 last_error 并存可见）。**不采纳 B**（不为消息动路由拓扑）。加 **UT**：构造 upstream halt 场景
（`debug_result.halt_reason` 非空 + `last_error` 非空），断言顶层 halt_reason.message 用语义原因。

---

## 总体策略（三问题一并收口）

| 问题 | 主修复 | 辅修 | 验证 |
|---|---|---|---|
| P1 TypeError | 滤 None（选项 A） | — | UT：全 None 收口不崩 |
| P2 TensorList 契约 | 源头派生 `is_list→DYNAMIC`（A2） | A1 引导 + PD-CONTRACT hint（C） | UT：is_list 输入 op_spec 派生 DYNAMIC；runner 放行 list-of-lists；REQUIRED 输入仍拒 list-of-lists |
| P3 halt 消息 | `__halt__` 语义原因优先（A） | last_error 并存（C） | UT：upstream halt 消息含 scope_reason |

**两层防御**（§1.2）：
1. **正确改动**：P1 数据清洗、P2 源头派生、P3 消息语义——各自修在责任正确的层。
2. **可观测性兜底**：PD-CONTRACT hint + 消息并存，异常路径留信号（§1.3）。

**不变量核验**：P2 不改 runner 放行语义（不变式 1 保留，契约不一致仍大声失败，只是错误文案更准）；
P2 用 `is_list` 结构信号派生（不变式 3 保留）；P3 消息反映语义（不变式 4 满足）；P1 让框架自愈
（不变式 5 满足）。

## 待决策点（不拍板，需用户/后续讨论）

1. **P2 前置核查 cannbench_eval 接受度**：修 A2 后 foreach 算子会走到 eval；需确认
   `cannbench_eval` / `DevkitBackend` 对 list-of-lists 用例的接受度与精度比较（cann-bench 自家
   eval 能跑，devkit 侧是否一致）。若 eval 侧也卡，A2 之外补 eval 侧对齐。
2. **A2 的 WARN 还是静默**：派生 REQUIRED→DYNAMIC 时 WARN 暴露（建议，§1.3）；若噪音大可降级为
   DEBUG，但**不静默**。
3. **A2 覆盖范围**：仅 requirement 层，还是 design_spec 层一起（integrate 按 name 对齐，改
   requirement 后 design_spec 同步或派生点统一放 `from_dict` 一处）。
4. **P1/P3 是否并入本轮**：都是确定性小改 + 低风险，建议与 P2 同批；若只想最小化，P2 可先单发。
5. **W3（m.def 正则）/ W4（callable_target 中继）**：低优先独立项，是否顺带修（建议各单开小
   L4，不并入本包主线）。

## 与相邻工作的边界

- **`precision-scope-upstream-halt-eval-loss/`（apply_rotary_pos_emb）**：同源「upstream →
  整 run 终止」机制（`workflow.py:696`），但那是"kernel 已对、剩 harness 边角 → 0 评分"的**评分
  丢失**问题；本包是"harness 一个用例都不跑 → upstream halt"的**入口契约**问题。两者都涉及
  upstream 路由/消息，但**正交**：本包 P2 修的是入口能进来（契约对齐），那边修的是进来后终止的
  评分语义。不重复产权。
- **`precision-debug-abort-false-positive/`**：abort 判据误杀，与本包 P1（transition 收口）
  正交。
- **`precision-harness-nullable-attrs/`**：Optional attr 的 harness 校验，与本包 TensorList
  输入契约正交。
- **W3/W4**：非本包主修（见 01-problems.md 排除项），建议另立小工作或并入后续批。
