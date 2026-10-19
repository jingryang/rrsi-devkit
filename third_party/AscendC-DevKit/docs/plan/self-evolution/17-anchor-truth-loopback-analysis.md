# anchor 真值表漂移 + 迭代/loopback 可观测性 + read-only gate 正向修正 — 方案分析（第三层）

> 状态：方案已定（三决策已拍板，待用户确认 §6 待确认点后冻结）
> 日期：2026-07-04
> 层级：**第三层 / 方案分析**。选项 + 取舍 + 拍板理由。
> 覆盖问题：P24（硬件参数单源）、P25（迭代/loopback 失败原因不可读）、P26（read-only gate 自迭代空转 + 路由被绕过）、P27（无统一运行环境上下文——地基）。
> 输入：run `20260704_040953` 复盘 + L1 `06-problems.md` P24-P27。
> 配套 L4：`18-anchor-truth-loopback-impl.md`。

---

## 1. 背景：一次撞超时回滚、零产出的 run

run `20260704_040953`（cann-bench profile，exp 算子）整条 design pipeline 跑到 `anchor-consistency` 后撞 workflow 3600s 预算（实际 4279s）、`integrate` 被 abort、repo 全量回滚、零产出。复盘定位到三个**同源**问题：

1. **P24**：`anchor-consistency` 误报 AC2 阻断——per-template anchor 的内置真值表 P6-a 标 A3 UB=240KB，与产物（192KB，来自 `platform_diff.md` + chip spec + 真实硬件）冲突。**根因是硬件参数无唯一来源**，仓内 UB 至少四值（192/240/248/256KB）。
2. **P26**：`anchor-consistency` 靠 `is_satisfied` 自迭代 3 轮（ceiling=3）：前 2 轮「原样合并」传播 AC2 → False → 同 stage 重跑（fresh agent、同输入、同结论、零产物进展）；第 3 轮 agent 推翻默认聚合、清空 blocking_issues → True → 通过。**read-only gate 既无自修复能力、又被允许自迭代 = 结构性空转**；末轮 override 还静默掉了本该 forward 给 tiling 的 corrective 路由。
3. **P25**：全程日志只有 `iteration 2/3 (quality check not satisfied)`，不携带 issue 的 code/target/detail——**空转既发生又看不见**，只能事后翻产物。

三问题因果链：**P24（假阳性 issue）→ 触发 P26（gate 空转 + 路由失效）→ P25（空转不可观测）**。修 P24 去假阳性、修 P26 让真问题正向修正、修 P25 让过程可诊断，三者合起来才闭环。

---

## 2. 根因链（为什么是这三个一起修）

```
硬件参数多源（P24）─ 漂移 ─▶ anchor 误报 AC2（假阳性）
                                      │
                                      ▼
              read-only gate 自迭代（P26）── 空转 2 轮 ──▶ 末轮 override 清空 issue
                                      │                        │
                                      │                        ▼
                                      │              corrective 路由被静默（不触发）
                                      │
                                      ▼
              日志只打固定串（P25）── 空转不可观测 ──▶ 撞超时回滚才暴露
```

只修 P24（把 240 改 192）：治标，下次再漂移仍炸；且 P26 的控制结构缺陷对真 issue 依然存在。
只修 P26（max_iter=1）：消灭空转，但若 P24 不修，AC2 假阳性会 forward 给 tiling，tiling 的 R0 又强制 192KB → 循环矛盾、闭环闭不上。
只修 P25：看得见了，但问题还在。
**三者同修才闭环**：P24 让 issue 是真的 → P26 让真 issue forward 给能修的 tiling → P25 让每一步可诊断。

---

## 3. 决策〇（P27，地基）：RunContext 统一运行环境上下文

### 问题

run 不变的环境事实散落三处、无单一内聚对象（P27）：设计目标硬件（`chip_version` 是 State 字段、`hw_params` 不存在）、当前硬件环境（`npu_id` 是 State 字段、检测芯片在 `npu/detect.py` 不回存、驱动版本只在 `verify_env.py`）、运行软件环境（`ASCEND_TOOLKIT_HOME`/CANN/版本散读 `os.environ` 于 CannAdapter + verify_env + verify.preflight_diagnostic）。逐 stage `_upstream_inputs` 声明 = **传递丢失载体**（忘声明则静默丢失、无加载期校验）。

### 选项

- **A. 引入 frozen RunContext（三段：hardware_target / hardware_env / software_env），State 增 `run_context` 单字段，context 阶段一次填充、全程不变、各 stage 直接访问；materialization 自动物化 run_context 片段到每个 design substage cwd（不经 `_upstream_inputs` 声明）。**
- **B. 仅把 hw_params 作为一个新 State 字段，靠各 stage `_upstream_inputs` 声明消费。**
- **C. 不动 State，把硬件/software env 收进一个全局单例/module 变量。**

### 取舍

- **B 不解决传递丢失**：新 stage 忘声明 hw_params → 静默丢失（正是本次多源漂移的机制）。且 hw/software env 仍散落，未统一查证。**不选**。
- **C 破坏 frozen State / 依赖注入模型**（§1.6）：全局可变单例与 frozen dataclass + `with_updates` 的不可变语义冲突，且无法随 State 序列化/resume。**不选**。
- **A 直击结构根因**：RunContext 是 frozen、随 State 流转、一次填充全程不变；各 stage 直接 `state.run_context.*` 访问（无需逐 stage 声明）；materialization 自动物化消除「忘声明」漏洞；复用既有检测（CannAdapter / npu/detect.py / verify_env），**只收口、不重做**。三段一次性全做（用户拍板）。

### 拍板：A（三段一次性全做）

```
RunContext (frozen)
├─ hardware_target     # 设计目标硬件 — 设计 FOR 什么
│   ├─ chip            # "ascend910b"（+ variant）
│   └─ hw_params       # chip spec 单源载入：ub/l1/bw/reg/align…
├─ hardware_env        # 当前硬件环境 — 跑在什么上
│   ├─ npu_id
│   ├─ detected_chip   # 复用 npu/detect.py
│   └─ driver_version  # 复用 npu-smi 检测
└─ software_env        # 运行软件环境
    ├─ cann_toolkit_path / cann_version / compiler   # 复用 CannAdapter
    └─ python_version / torch_npu_version            # 复用 verify_env 检测
```

- **State**：增 `run_context: RunContext | None = None`；既有 `chip_version`/`npu_id` 字段**迁移**进 RunContext 对应段（§1.4 不留兼容），原读处改读 `state.run_context.*`。
- **填充落点**：context 阶段（已解析 chip_version/npu_id），调用既有 CannAdapter / npu/detect.py / 新增 chip-spec loader 收口产出。纯设计/cross-compile 场景 hardware_env/software_env 可为 None（不强制真实硬件）。
- **消除传递丢失**：materialization 层自动把 `hw_params.json`（首期）写进每个 design substage cwd——**不经 `_upstream_inputs` 声明**；新 stage 自动获得。

### 与决策一的关系

hw_params 住 `run_context.hardware_target`——决策一（单源）由此承载：anchor/tiling 读 `state.run_context.hardware_target.hw_params`，而非各自声明/副本。决策一不再讨论「字段加哪、谁声明」，只讨论「chip spec 为唯一源、删 skill 副本」。

---

## 4. 决策一（P24）：硬件参数唯一数据来源

### 问题

硬件参数（UB / L1 / 带宽 / 核数 / reg 上限 / 对齐）在仓内多处复制，必然漂移。需要一个**唯一源**，且各 skill（尤其 anchor gate）能在不重新引入副本的前提下拿到 ground truth。

### 选项

- **A. chip spec JSON 为唯一源，各 skill 运行期经 `hw_params` 注入消费；删除所有内置硬件常量表**（P6-a、`check_feasibility.py` 的 `196608` default、`general_design_common_knowledge.md` 的 UB 数值列等）。
- **B. 把 `platform_diff.md` 升格为唯一权威源**（机器可读化，加 total/usable 字段），各 skill 引用它。
- **C. 只把 P6-a 的 240 改成 192，不动结构**。

### 取舍

- **C 治标**：多源仍在，下次再漂移。用户已明确否决（「应保证唯一数据来源，否则后面很可能因为再次修改而出错」）。**不选**。
- **B 角色错位**：`platform_diff.md` 的定位是「A3 vs A5 定性架构对比」（Membase vs Regbase、同步模型、Cast 时机…），让它承载机器可读常量违反 §2.7（核心引导归 skill、脚手架/常量外移）；且它现有的「~192KB / ~248KB」是约数、本身就不精确。**不选**。
- **A 真单源**：`ascend-hardware` 的 chip spec（`references/chips/*.json`，如 `ascend_910b.json` 的 `ub size_bytes=196608`）已是机器可读、已是 `ascend-hardware` skill 产 `hw_params` 的来源、已被框架认定为硬件权威。anchor 的「独立性」通过「直接读注入的 `hw_params`」实现——**独立 = 我自己读权威源，而非我手抄一份**。符合 §1.5（硬件知识不进 skill 代码）。

### 拍板：A

chip spec 为唯一源；删除 P6-a 内置真值表，anchor 改为消费运行期注入的 `hw_params`；`platform_diff.md` 降级为纯定性架构对比（数值列删除或改为「见 ascend-hardware chip spec」）；`check_feasibility.py` 等脚本的硬编码 default 改为必由 `hw_params` 注入。

**子决策（总量 vs 可用预算）**：历史措辞混用了「物理总量 / 可用预算」（P6-a 240KB 含「可用=UB 减 TilingData 与系统保留」注解；common_knowledge「256KB 物理 / ~192KB 可用」）。**决策**：在 chip spec 用明确字段区分二者（如 `size_bytes`=物理总量，另注「可用预算 = 总量 − 系统保留，TilingData 占用由 tiling 现场算」），把措辞统一到唯一一处。具体字段名在 L4 定。

**子决策（anchor 注入可达性）**：A 的前提是 design 阶段各 substage（含 anchor-per-template / anchor-consistency）能在运行期拿到 `hw_params`。当前是否注入需在 L4 核实；若未注入，补注入通路（复用 ascend-hardware 产出，不新造源）。

---

## 5. 决策二（P25）：迭代 + loopback 失败原因必须可直读

### 问题

失败原因要在「日志行」和「feed 给下游 stage 的 loopback payload」两处都**人 + LLM 可直读、无需二次查证**。当前两者都不达标：日志只打固定串；现有 issue 摘要渲染只在 routing 触发、且 detail 截断到 80 字符太短。

### 选项

- **A. 统一确定性 issue 渲染器，迭代 reason 行 + loopback 摘要共用；日志行 detail 给足可读长度，loopback payload 不截断**。
- **B. 迭代行仍短（code+target），detail 另起一行/另一事件**。
- **C. 用 LLM 把 issue 压成一句话**。

### 取舍

- **C 引入幻觉/延迟/成本**，违反 graph_executor 既有的「非 NLP 压缩、确定性 field-select」不变式（源码注释明确反对 LLM 压缩日志）。**不选**。
- **B 仍需跳转**，没解决「人不知道 code 指什么、LLM 收到 loopback 还得查证」。**不选**。
- **A 复用已有 field-select 机制**（零幻觉），把两套日志面统一；日志行给足 detail（人直读），loopback payload 携完整 issue 结构注入下游 prompt（LLM 直读可直接行动）。

### 拍板：A

- 共用一个确定性渲染器，输出形如 `[AC2→tiling/T1] <detail>`。
- **迭代 reason 行**（runner 构造）：quality 失败时拼上各 blocking issue 的渲染（detail 适中上限，如 240 字符/issue；多 issue 取前 N 个 + 总数）。替换现在的固定串「quality check not satisfied」。
- **loopback payload**（gate 的 `loopback_feedback` → 下游 prompt）：携带完整 issue 结构（code/target/target_template/detail 原文），注入下游 prompt 时用同款渲染、不截断——保证下游 LLM 拿到的是「可直接行动的上下文」而非「还得查证的 code」。
- 两者共用底层渲染、不同长度策略。

---

## 6. 决策三（P26）：read-only gate 闭环——不自迭代即正向修正

### 问题（用户给定的 Either/Or 框架）

> 「如果 anchor 没有自我修复能力，自我循环迭代次数应该设置为 1，要么就放开它的修改权限，方案逻辑要能够闭环。」

这是一个**充要的闭环判据**：任一 gate stage，要么能自修复（则自迭代有意义），要么不能（则 `max_iterations=1`、首轮产出即交出、由能修的 stage 接手）。**不存在「无自修复却自迭代」的中间态**——那正是当前的空转。

### 选项

- **A. anchor 无自修复 → `max_iterations=1`；blocking issue 经 transition_table forward-route 到 tiling（边已存在、模板精确），tiling 修复后重跑 anchor 收敛。**
- **B. 放开 anchor 的修改权限**，让它就地改 tiling 产物修 issue，自迭代才有意义。
- **C. 保留自迭代，仅禁末轮 override**（堵静默，但不治空转）。

### 取舍

- **B 破坏 anchor 的存在意义**：anchor 的角色定义是「**只读产物 + 写锚点报告，禁止修改任何设计产物**」「独立对照真实硬件 API 判可行性」。放开写权限 = 既当裁判又下场 = 自审自批，丧失独立性，违反 §1.2（可维护性：维持/澄清既有不变式）。**不选**。
- **C 治标**：堵住了 override 静默，但前 2 轮空转依旧。**不选**。
- **A 干净闭环**：anchor 结构性只读、无自修复 → `max_iterations=1`，首轮报告产出即交 graph_executor，按已有 `anchor-consistency → tiling corrective` 边 forward（selector 按 `target_template` 只 rerun 失败分支，与 P21 同机制）。**不新造路由，只把「何时交出」从「自迭代 ceiling 耗尽/override 后」提前到「首轮报告产出后」**。

### 拍板：A

- **不变式（泛化，适用于所有 gate）**：gate 要么有自修复能力（可就地修产物，允许 `is_satisfied` 自迭代），要么无自修复能力（`max_iterations=1`，blocking issue 立即 forward-route）。`validate` 能就地 Edit → 可自迭代；`anchor`（per-template + consistency）只读 → `max_iterations=1`。
- anchor 两 stage 的 `default_max_iterations` 由继承的 3 改为 1。
- 配合 P24（issue 是真的、不是假阳性）+ P25（forward 时带可读 detail），tiling 拿到的是真问题 + 可行动上下文，修完重跑 anchor 即收敛。

---

## 7. 闭环验证（三决策合起来如何保证收敛）

把三决策代入同一个 issue 的生命周期，验证不死循环、不空转：

| 场景 | issue 性质 | 闭环路径 |
|---|---|---|
| AC2（UB 192 vs 240） | **假阳性**（P24 漂移所致） | P24 修后 anchor 读 `hw_params`=192KB、产物也是 192KB → 无冲突 → anchor 首轮 pass、不触发路由。**根除，不进入 loopback。** |
| 真·产物级不可行（如 buffer 超 UB） | **真阳性** | anchor 首轮报 issue（target=tiling）→ `max_iter=1` 不自迭代 → forward-route 到 tiling（带 P25 完整 detail）→ tiling 改 tiling → 重跑 anchor → pass。**正向修正收敛。** |
| gate 自身报告格式问题 | gate 可自修类 | 不适用于 anchor（只读）；适用于 validate → validate 自迭代修。 |

**死循环免疫**：唯一可能的死循环是「anchor 报假阳性 → tiling 改不动 → 回 anchor → 再报」。P24 消灭了假阳性的源头（单源后 anchor 与 tiling 读同一 `hw_params`，对 UB 这类常量不可能再冲突），故 forward 通路只在真阳性触发、且 tiling 真能修。`max_corrective` 配额仍是兜底。

---

## 8. 澄清/新增的不变式

- **不变式 I（单源，P24）**：硬件常量只存在于 chip spec；运行期经 `hw_params` 注入；任何 skill 内置硬件常量表都是债。
- **不变式 II（闭环，P26）**：gate「自迭代」与「forward-route」互斥——能自修才自迭代，不能自修则 `max_iter=1` 即 forward。无「无自修复却自迭代」。
- **不变式 III（可观测，P25）**：每次迭代与每次 corrective 路由都必须携带可直读的 issue detail（确定性渲染、非 LLM 压缩）；下游 prompt 收到的是可行动上下文。
- **不变式 IV（继承 step-14 P15）**：corrective loopback 的 target 必须可达且重跑能变。本步把它从「target 可达性」延伸到「source gate 不该对指向他处的 issue 自迭代」。

---

## 9. 与现有工作的关系

- **step-13（anchor 拆 per-template + consistency + ForkJoin 并行）**：本步改的是 anchor 的**控制流与数据源**（max_iter、hw_params 单源、loopback detail），不动 step-13 的并行拆分结构。
- **step-14 / P21（validate→tiling loopback 丢模板精度）**：P21 让 validate→tiling 模板精确；P26 让 anchor gate 真正把 issue forward 出去（不再被自迭代/override 绕过）。两者合起来 corrective loopback 对所有 gate 都既「触发得到」又「模板精确」——是闭环的两半。
- **step-12（pipeline 可观测性）**：P25 是该主题在「迭代/loopback 行 detail」上的延伸。

---

## 10. 待确认点（拍板前）

1. **anchor 的 `hw_params` 注入可达性**：design 阶段 anchor-per-template / anchor-consistency 当前是否已能拿到 `hw_params`？若否，补注入通路的落点（L4 核实）。这决定决策一 A 的前置工作量。
2. **chip spec 的「总量/可用」字段命名**：用 `size_bytes` + 注释，还是新增 `usable_budget_bytes`？倾向前者（TilingData 占用本就由 tiling 现场算，chip spec 只给物理总量）。
3. **loopback detail 日志长度上限**：日志行 240 字符/issue 是否合适（P25）？loopback payload 不截断无异议。
4. **`max_iterations=1` 的范围**：仅 anchor 两 stage，还是把「无自修复 gate」判据做成通用配置项（按 stage 声明 self_repairable）？倾向先硬改 anchor 两 stage（最小正确改动），通用化留后续。
