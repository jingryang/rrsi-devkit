# L3 方案分析 — 升级退出状态归属（P42）

> 对应 L1 P1/P2。调研演进稿；拍板后冻结。

## P1：升级 failed-mark 的归属层

### 选项 ①：按条件名枚举 halt-class

升级分支里对 `escalation_cond ∈ {"upstream", "stalled"}` 标 failed，其余不标。

**否决**：
- 同名条件跨树处置不同——`exhausted` 在 self_evolve 根表是软门（cannbench_adapt），在
  design 根表是 `__halt__`。按条件名枚举必有一侧错（§2.12 枚举边界 + 本质是拿条件名字面量
  代理「根表怎么路由它」的机制特征代理反模式，§1.10）。
- graph_executor 需要感知各业务树的条件语义——层越权。

### 选项 ②：处置点标记（选定）

failed-mark 的语义是「resume 必须重入的 halt 源」（P40 原始目的），而**是否 halt 由根表
路由决定**——标记与处置决策放同一层：

- 发射点（升级分支）：只记录 origin——State 新 transient 字段 `_bubble_origin`
  （发射的原子叶路径；组再升级时保留更深层 origin），不再写 node_status；
- 处置点（根表路由到 `__halt__` 的分支）：标记 direct child（原 P40 行为）+ `_bubble_origin`
  指向的原子叶（保住「resume 重入 halt 源」契约）；
- 线性前进（passed 无条目）/软门前进（exhausted→cannbench_adapt）/回炼（loopback，
  invalidate 管重跑）：零标记——干净退出读干净。

**四把尺子**：
- 可维护：标记紧跟处置，语义不再依赖注释解释「为什么这里标」；
- 可扩展：新业务树新增任何升级条件自动正确归位（处置即标记），无需改 GE；
- 可诊断：成功退出不再产生 failed 噪音，真 halt 仍三处可见（halt_reason/`✗`/node_status）；
- 架构合理：路由决策（根表）与状态判定（GE）职责边界清晰，GE 不解析业务条件语义。

### 选项 ③：dispatcher 出口过滤

出口侧把 bubble-origin 类 failed 从 `failed_nodes` 剔除。**否决**：失真发生在 GE 层，
出口打补丁掩盖而非纠正；resume 权威（node_status）仍是脏的。

## P2：超时文案分流（选定）

`TimeoutExpired` 分支独立 message（`cann-bench eval 超时 (op ...)` + hang 类排查指引），
不再走 `_infra_error` 的「前置环境缺失」前缀。error_type 仍 infra（外部故障类别正确）。
备选「统一重写 _infra_error」过度——该前缀对真实 env 缺失场景仍然准确。

## 边界与不做

- eval 30 分钟超时本身（外部 infra）不修——fail-open 边界（用户既有取向）。
- P-B 租约排序回归不在此线（产权 `card-isolation-subprocess-fix/`）。
- A5 树（precision_debug_a5）同形升级**自动受益**（GE 层单点修复）——无需也不应动 A5 代码。
