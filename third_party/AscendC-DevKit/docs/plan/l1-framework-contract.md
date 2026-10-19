# L1 框架基石 — 扩展契约

> 状态：草案 v0.5（2026-06-29）。L1 = 通用状态机编排平台。
> 本文是 `self-evolution-design.md` §L1 的细化。
> **本文档纪律**：只承载稳定的「目标态契约」与「补强优先级」。**不维护代码现状快照、不写 file:line 行号、不下「已完备」断言**——
> 理由：本仓由多人活跃修改，行号与"现状"会随时漂移；把易腐快照固化进方案，实施时必然对不上。
> 任何"此刻代码长什么样"的问题，**实施时现场读 `src/ascendc_devkit/orchestration/` 核对**，方案文档不负责体检。
> 引用代码时一律用**语义锚点**（类名 / 方法名 / 接口签名），不用行号。

---

## 0. 三个问题（本文要回答的）

- ① 添加 stage / substage / workflow 应该改几处？→ 用**目标态承诺**回答（§2），不基于今天的耦合去数"改几个文件"。
- ② 哪里耦合阻碍「零改框架加能力」？→ 转成**目标态契约缺口**（§3），描述"想要它长什么样"，而非"今天它坏在哪一行"。
- ③ 用最小 training-time 闭环验收会暴露什么？→ §4 保留这个视角，但不绑定当前实现细节。

---

## 1. L1 应提供的原语意图（类别清单，非体检表）

L1 作为通用状态机编排平台，应提供下列类别的原语。**是否已落地、落到什么程度，以代码为准，本文不维护**——下表只列"应该有哪几类"，不列"此刻在哪一行"。

| 类别 | 意图 |
|---|---|
| Stage 契约 | `Stage` 承载 actions / transition / gate / validate_inputs / loopback feedback / decision log 钩子 |
| 节点树 | 原子 stage、串行 group（可嵌套）、动态 fork-join、旁支（fire-and-forget） |
| 转移路由 | workflow 转移表 + group 局部表 + 跨层冒泡；corrective / escalation / validation 三类 loopback |
| 图执行 | 节点树遍历 + resume 前沿 + 动态分叉 |
| 加载期校验 | IO 链兼容性 + agent manifest 存在性，启动 fail-fast |
| 不可变 State | frozen，`with_updates` / `with_field` / snapshot |
| 注册表 | 装饰器副作用注册 + 查询 |
| 交互关卡 | 配置驱动的 approve/revise/abort 插桩 |
| NPU 资源池 | 多设备 acquire/release/available（**待集成到执行流程**，见 §3.4 / §7） |

> 设计纪律：substage / group 构建应是**声明式、零改框架**的（`AtomicStage` + group 组装 + transition_table / branch_factory 纯数据/回调）。
> 「复用一段能力」= 把它做成**节点树里可嵌套的 stage group**，**不是**「Stage 内调 Workflow 对象」（后者是过度设计，L1 不必支持）。

---

## 2. 目标态：零改框架加能力的承诺

补强到位后，扩展 L1 应满足（这是承诺，不是当前体检结论）：

| 扩展 | 应满足 | 改的框架文件 |
|---|---|---|
| 加原子 Stage | 新建 stage 模块（`@register_stage`）+ agent.md；产物入 `stage_outputs` 袋 | **0** |
| 加 substage / 复用能力段 | 写 group 构建器（声明式） | **0** |
| 加 Workflow | 新建 workflow 文件（`@register_workflow` + root 节点树）；`--workflow <name>` 自动路由 | **0** |
| 产物流转 | contract `provides` / `requires` 以 `stage_outputs` 袋 key 或框架级字段为媒介；加载期 `validate_chain` 兜底 | — |

---

## 3. 待补强的契约缺口（目标态，非现状考古）

下列是"为了让 §2 承诺成立"还需要的契约。每条只描述**目标态契约 + 价值**，不指责当前代码具体位置（位置实施时读代码）。

### 3.1 registry 自动发现

- **目标态**：扫描 `stages/*.py` 与 workflow 目录，import 全部模块靠装饰器副作用注册；加 stage/workflow 不再手写 import。
- **价值**：让「加能力自动归位」，加能力彻底不改 registry。
- **为何重要**：注册靠手写 import 会让"忘记 import → 不注册"成为加能力的默认失败模式。

### 3.2 State 产物袋

- **目标态**：引入通用产物袋 `stage_outputs: dict[stage_name, dict]`，stage 私有产物默认进袋；State 只保留**被多 stage 强类型消费的框架级字段**（如 `op_spec` / `build_result` / `precision_result`）。
- **价值**：State 不随业务产物字段膨胀；多数新 stage 不再碰 dataclass。
- **联动**：training-time 的「loss 载体入 State」「多算子产物收集（`loss_results: {op: score}`）」直接依赖此解耦。

### 3.3 节点树为唯一事实源

- **目标态**：workflow 以 root 节点树为唯一事实源；扁平 stage 列表退化为它的派生缓存；转移路由统一基于节点树。
- **价值**：消除"扁平 stages 与 root 节点树"两套表达并存的冗余与踩坑面。

> 三条都过了仓 CLAUDE.md 四把尺子（可维护 / 可扩展 / 可诊断 / 架构合理）。

### 3.4 Stage 资源需求契约 + NPU slot 集成

- **目标态**：`Stage` 声明 `resource_requirements(state) -> dict`（默认 `{}`）；执行器在 stage 前后据需求 `acquire` / `release` NPU slot；`state.npu_id` 从「固定输入」变成「分配结果」。
- **价值**：多算子并行时框架知道哪些 stage 抢 NPU，能做 per-stage 调度而非全靠用户指定一个固定设备。
- **详见** §7。

---

## 4. 最小 training-time 闭环验收缺口

最小 (b) 闭环 = 评测集 → 生成 → 算 loss(最终+中间) → 归因 → 改 skill → 回归对比。用它验收 L1 通用性会暴露以下缺口（缺口是**能力维度**，不绑当前实现）：

1. **跨 run 持久物缺位**：issue 池、loss 历史、评测集版本都是**跨 run** 的，单 run 的 State / workspace 不够。需要跨 run infra（L1 之外，但验收立刻撞上）。
2. **loss 载体入 State + 多算子产物收集**：overall_score、中间事实集比对分、评测集多算子各自的 loss 都要随 State 流转 → 依赖 §3.2。多算子并行评测时各算子产物进 dict 袋避免 fork-join merge 冲突。
3. **group 可复用 + 回归段重跑**：`verify_fix` 的"再跑一遍生成 + 评测、对比改前改后 loss"靠 training-time workflow **复用节点树 group**（生成段 / 评测段抽成可复用 group）+ loopback / fork-join，**不需要 Stage 内嵌套 Workflow 对象**。
4. **人工 gate Stage 原语**：`human_review` 要"暂停 → 落盘 → 外部输入 → resume"。当前 cancel / snapshot / resume 机制在，但"等外部输入再继续"的通用 Stage I/O 模式还需立（按 P6b 用独立 Stage，不用 `resolve_ambiguity` / `__halt__`）。
5. **NPU 资源调度集成**：见 §7。

---

## 5. 补强优先级

| 优先级 | 项 | 理由（目标态价值） |
|---|---|---|
| **P0** | registry 自动发现（§3.1） | 改动最小、收益最大、风险最低；立刻让「加 stage/workflow 零改框架」成立 |
| **P1** | State 产物袋（§3.2） | 解最大耦合；且 §4 缺口 2/3 直接依赖它 |
| P2 | 节点树统一（§3.3） | 较大重构，清冗余，可在 P0/P1 稳定后做 |

> **优先级前置条件**：P0/P1/P2 的"做到什么程度"应**用最小 baseline loss（§4）校准**——先用 phase0 的 35 算子跑通一次 baseline，看真实约束暴露在哪，再回头决定补强的深浅，而非凭空优化框架。
> 这与 `self-evolution-design.md §7` 路线图（baseline 验证先于 L1 精修）一致。

---

## 6. 嵌套纪律（稳定的设计纪律）

- workflow root 下命名子流程（group）默认**只一层**；ForkJoin 并行分支是数据并行（不计控制流嵌套深度），分支内尽量只挂 AtomicStage / 浅串行，不再套命名子流程 group；深嵌套需显式记录理由。
- 多算子评测等"批量"场景用"外层循环多次扁平 workflow"而非"单 workflow 内深嵌套 fork-join"。

---

## 7. NPU 调度契约

> 草案不在此断言 `NPUSlotManager` "已存在 / 已完备"——它是否存在、是否已接入执行流程，**实施时读代码核对**。本节只给契约目标。

- **核心原则**：不改单算子 pipeline，用「外层调度器 + per-stage NPU slot 申请/释放」。
- **Stage 契约**：`resource_requirements(state) -> dict` 声明 NPU 需求（是否扩展 cpu/memory 待定）。
- **集成点**：执行器在 NPU-bound stage 前后 `acquire` / `release` slot；申请失败策略（阻塞 / 超时 / 降级）待定；异常安全 release（NPU-bound stage 失败时必须 release）。
- **NPU-bound 判定**（实施时需核实，下表是**假设**，不保证与当前 stage 实现一致）：verify 的 precision 部分、perf、`cannbench_eval` 的 precision_loop / score 为 NPU-bound；design / codegen / build / deploy 安装为 CPU-bound。
  - **务必现场核实 build 是否真 CPU-bound**：若 AscendC 编译依赖 driver/toolkit，build 也可能 NPU-bound，归类错了会让 slot 调度出错。
- **`state.npu_id`**：从"用户/CLI 固定输入"改为"分配到的设备"。
- **调度器形态**：单进程多线程（slot 锁是 in-process，只能 in-process 共享）；多算子由外层调度器并发驱动多个单算子 workflow run。多线程下共享资源（events.jsonl 写入、workspace 落盘、agent 会话、subprocess 日志）的隔离与线程安全需专门设计，不可默认安全。

---

## 8. 待确认（衔接主草案 §8）

- P0 自动发现的目录约定（`stages/` 平铺 vs 子目录；workflow 独立目录时机）
- P1 产物袋与现有强类型字段的迁移边界（哪些字段留 dataclass、哪些入袋）
- P2 节点树统一后扁平路由的去留
- 生成段 / 评测段抽成可复用 group 构建器的边界；多算子评测的 State 隔离与 dict 袋产物收集范式
- Stage `resource_requirements()` 接口 shape；NPU 申请失败策略
- slot 集成点：在 Runner 还是 GraphExecutor 做 acquire/release
- 外层调度器形态：独立 CLI / 独立 workflow / training-time workflow 的某个 stage

---

## 变更记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-06-28 | v0.1 | 初稿：原语盘点 + Q1 改动面 + 3 耦合点 + Q3 验收缺口 + 补强优先级 + 目标态契约 |
| 2026-06-28 | v0.2 | 修正 Q3 缺口 3：「子 workflow 可重入」是过度设计，删除；改为「group 可复用 + 节点树重跑」。明确「复用能力 = 嵌套 stage group，不是嵌套 Workflow 对象」 |
| 2026-06-28 | v0.3 | 新增嵌套纪律（§6）；修正「任意深度嵌套」措辞为「支持嵌套但纪律默认一层」 |
| 2026-06-28 | v0.4 | 新增 §3.4 资源需求契约 + NPU slot；§4.5 NPU 调度验收缺口；§6 NPU 契约 |
| 2026-06-29 | **v0.5** | **现状剥离重构**：删除所有 file:line 行号与"已具备/已完备"现状体检结论（易腐、与仓「以代码为准、不维护快照」纪律冲突）；原语盘点表降为"类别意图清单"；耦合点考古转为目标态契约缺口；NPU 部分去"已有 NPUSlotManager"断言改"待集成 + 实施时核实"；新增优先级前置条件（baseline loss 校准补强深浅） |
