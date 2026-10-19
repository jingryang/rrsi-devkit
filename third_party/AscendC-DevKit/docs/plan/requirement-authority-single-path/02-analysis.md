# L3 方案分析 — 需求权威单一通路（P1/P2/P3/P4 取舍）

## 决策问题

设计链各阶段消费的需求规格，存在**两条事实线**：权威磁盘文件（`artifacts/requirement/requirement.json`，含 domain/公式）与 reduced `State.Requirement`（单 dtype op_spec，无 domain）。本次要确定：如何让设计链 agent 拿到完整需求、且收窄成为知情决策、且兜底链条不丢。

## 选项

| 选项 | 做法 | 优点 | 缺点 / 违反原则 |
|---|---|---|---|
| **A. 输入路接权威回读** | `_materialize_inputs` 对 `requirement` 字段统一走 `materialize_authoritative_requirement`（codegen/reconcile 既有模式） | 最小改动（基类一处 + 已有 helper）；与 §2.5 唯一通路、§2.3 文件契约一致；agent 一开始看到全量 domain，收窄变知情决策 | 需按 §3.12 处理 helper 的 last-resort fallback（见 A2） |
| B. `Requirement` dataclass 扩容为无损 | 补齐 domain/公式等字段进 dataclass | reduced 变完整，机械消费方受益 | 改动面大（dataclass/from_dict/全部消费方/asdict/schema/UT）；§1.14 最小结构优先反对为少数消费方撑大公共模型 |
| C. 设计 validate 门加 `support_domain ⊆ requirement.domain` 阻断对质 | 下游门校验 | 约束强 | §2.9「门不越界查上游」：对质纯凭 requirement 即可做，不属下游门，归上游自检；§1.14 禁为抓模型错搭 gate；discover+regenerate 反模式风险 |
| D. integrate 把 requirement.domain **机械并入** support_domain（强制 = 需求域） | 声称域恒等于需求域 | 消除告警 | support_domain 语义是「设计声称实现的域」；机械撑大 → 虚假声称 → kernel 实际只实现 fp16 却声称全 dtype → domain-gap 永不告警 → **显式缺口变静默缺口**，违反 §1.2 可诊断 |

## 选择：A + 三个附属修正

**主修 A**：设计链输入路统一走权威回读。依据 §2.5（与 codegen/reconcile 收束到同一 helper）、§2.3（agent 从文件读全量契约）、§3.12（目标 = 高质量算子 → agent 必须基于完整需求决策）。

**A2（§3.12 修正）**：helper 的 last-resort fallback（为 "isolated UT" 存在）不作为设计约束。权威源缺失 = 需求链断裂 → **诚实 fail / 告警**，不拿有损数据继续。测试隔离由真实 fixture 解决（§3.12），不为测试便利保留降级路径。codegen 侧同步评估。

**A3（§2.9 定位修正）**：support_domain ⊆ requirement.domain 的对质是**设计链内自检**（放 `SynthesizeStage.transition` 既有 reconcile 区，那里已有 `_load_authoritative_requirement` 先例），不是下游 validate 门。收窄（子集）允许但须显式留痕；超集（声称超需求域）告警。绝不机械撑大（反对 D）。

**A4（§1.3 接线）**：`validate_support_domain_structure` 结构校验器接线到设计加载期校验，兑现既有承诺。

### resume 维度（State 字段的持久化职责）

`State.to_snapshot/from_snapshot`（state.py:428/459）→ `state_snapshot.json` 服务 **resume**：中断后重建 State、不用重跑上游。产物字段（requirement 等）存 State 也是为 resume 服务——但 **State.Requirement（reduced）作为 resume 载体同样有损**，若 resume 后靠 snapshot 重建 agent 输入，拿到的仍是单 dtype 需求。

推论：物化源统一到磁盘产物文件，**正常路径与 resume 路径走同一段 `_materialize_inputs`**，统一改源后 resume 同样回读磁盘权威文件（run 目录保留产物，可得），不再从 state_snapshot 的 reduced 快照重建 agent 输入。**State 退出 agent 输入源角色，只留「运行状态推进 + resume 快照 + 框架机械消费」**。边界：resume 时磁盘产物文件不可得（run 目录异常清理）→ 明确告警，不静默从 reduced 恢复（§3.12/§1.2）。

## 验证判据（§3.12：用真实 fixture 表达业务不变式）

1. 设计链任一 stage 物化的 `requirement.json` **必须含 `domain.dtypes` 全量**（构造 workspace + 含 domain 的权威文件断言），非 `{op_spec: 单 dtype}` wrap。
2. 权威文件缺失 → stage **fail / 明确告警**，不落 reduced 文件。
3. support_domain 超需求域 → 告警；收窄 → 留痕（decision_log）。
4. 既有 codegen / reconcile 行为零回归（它们已走权威回读）。
