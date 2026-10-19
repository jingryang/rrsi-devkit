# Regbase codegen 完成判定信号重构 — L3 方案分析

> 层级：L3（有哪些选项、选了哪个、为什么；调研中演进，拍板后冻结）
> 日期：2026-08-08
> 代码基线：`da2c26d6`（PR #65 head）；覆盖 L1 P1–P5

---

## §1 问题域：三件事被「一刀切」绑在一起

L1 P1–P5 实际是**三件独立的事**，PR #65 的 4 个 commit 把它们一并处理了：

1. **完成信号的可靠来源**（P1/P2/P3）：agent 自报（RETURN 块） vs backend status（empty_artifacts/ok） vs 文件/磁盘产物校验。这是 P1（s4 磁盘误判）、P2（s2 死循环）、P3（VF_TEST_RESULT 漏解析）的直接根因。
2. **plan 内容校验的去留**（P4）：删除 `_orchestration_plan_error` 后，s4 消费端对坏 plan 无结构兜底。
3. **文档跟踪**（P5）：行为变更无 L1/L2/L4 记录（本 L3/L4 即补）。

---

## §2 完成信号：选「agent 自报为主信号 + backend 兜底」

**选项**：
- A. 只信磁盘产物校验（旧 s4）——P1 证明误判：deliverables 命名约定与仓库实际不一致时，磁盘字符串匹配永远报缺，造成白重试。
- B. 只信 `status=="ok"`（508430c9 的 s2）——P2 证明误判：纯分析 stage backend 恒报 empty_artifacts，成功被当失败，死循环。
- C. **agent 自报（RETURN/VF_TEST_RESULT 块）为主信号 + backend status（ok/empty_artifacts→COMPLETED，fatal/partial→硬失败）兜底**——PR #65 采用。

**拍板理由**：
- 完成判定是「agent 是否完成了本阶段」的业务事实，agent 自报（RETURN 块）是唯一携带业务语义的信号；backend status 只反映 spawn/进程层面，不携带业务语义（§1.10 业务语义显式声明，不用机制特征代理）。
- 磁盘交付物校验依赖「plan deliverables 与仓库实际产物命名一致」这个脆弱前提，跨仓（mainline camelCase vs 本仓 snake_case）必炸——属机制特征（文件路径匹配）代理业务事实（是否完成编码），放弃。
- 兜底关系：backend 崩溃（fatal/partial）→ 硬失败，文本自报不得覆盖；有最终回复但无机器可读块 → 不静默抬成 COMPLETED（P3 防线）。
- **补充防线（P3 复盘新增）**：RETURN 块缺失时识别 `## VF_TEST_RESULT` 块（锚定 header 后紧跟 status 行，避免正文误匹配），避免 skill 的失败自报被静默吞掉。

**否决项记录**：保留磁盘交付物校验（A）被否——P1 实锤跨仓命名误判，且校验逻辑（字符串匹配）与仓库约定耦合（§1.7 通用化边界）。

---

## §3 plan 结构校验：只放宽 A 类路径启发式，s4 消费端保留结构兜底

**选项**：
- A. 保留完整 `_orchestration_plan_error`（含 deliverables 必须是真实路径/通配符）——用户决策**否决**：agent 输出的 deliverables 路径无法严格保证正确（P1 同因），严格卡死会误报 INP → s2 被多次重复拉起。**删除 A 类启发式，拍板**。
- B. **删除全部校验，只信 agent 返回**——PR #65 初版采用。但 P4 实锤后果：缺 `id` → `KeyError` 崩溃；`.VT.` kind=code → 静默错路由到 `call_s4`。运行期崩溃/静默错路由 ≠ 「信 agent」，是「s4 消费坏 plan 时该崩溃」，与完成信号决策正交。
- C. **完成信号信 agent + s4 消费端宽容兜底**——本 L3 拍板（组合，§1.2 组合原则）：

**C 方案（采用）**：
- 完成信号：agent 自报 + backend 兜底（§2，PR 已落地）。
- s4 消费端：`_read_plan` 保持「坏 JSON → 空 plan」的容错，但结构层加兜底——
  - `_pending_ids` / `_step_by_id` 对缺 `id` / 非法 kind 条目跳过并 Logger.warn（防 `KeyError` 崩溃）；
  - `.VT.` 步骤在 plan 内 kind≠vf 时回退按正则（`.VT.\d+$`）识别（防静默错路由到普通编码 agent）。
- 校验失败**不**重新拉起 s2（不违背「信 agent 完成信号」决策），只是把「运行期崩溃/静默错路由」降级为「可诊断的跳过/留痕」。

**四把尺子（§1.2）**：
- 可维护：完成判定（agent 自报）与消费端结构兜底（s4 宽容）职责分离，各管各的不变式。
- 可扩展：同类新坏 plan（缺字段/非法 kind）自动被同一条兜底覆盖，无需逐个打补丁。
- 可诊断：崩溃 → warn 留痕 + 跳过，错误不再被静默吞掉（P4 当前是 KeyError/静默错路由，无信号）。
- 架构合理：兜底落在消费端（s4 读 plan 处），不越层（不回 s2、不改完成信号决策）。

> **状态**：C 方案已随本 L3 拍板；落地见 L4 §3。PR #65 初版（B 方案）已合入的代码保持「信 agent」主路径，消费端兜底在后续 L4 实施补齐。

---

## §4 s4-coding 反混淆（P5 附带）

`7521d308` 解决「零交互 + fast_start + auto 被误读为批处理」：agent 一次调用跑完所有 sub-stage 而非当前一个。这是编排器 prompt 与 agent manifest 的协议澄清，不涉及状态机逻辑，随完成信号重构一并记录（属同一 codegen 编排契约域）。

**拍板**：保留该条款（s4-coding manifest + phase-c-prompts.md 反混淆节），无备选争议。

---

## §5 与 L1 的映射

| L1 | 决策 | 状态 |
|---|---|---|
| P1（s4 磁盘误判） | §2 选 C：只信 agent 自报，删磁盘交付物校验 | PR #65 已落地（c41b999e 前置 + 本 PR） |
| P2（s2 死循环） | §2 选 C：empty_artifacts→COMPLETED + RETURN 自报 | PR #65 已落地（da2c26d6） |
| P3（VF_TEST_RESULT 漏解析） | §2 补充防线：识别 VF_TEST_RESULT 块 + 无块不静默 COMPLETED | PR #65 已落地（04eb8a7b） |
| P4（结构校验删除的后果） | §3 选 C：s4 消费端宽容兜底 | 本 L3 拍板；L4 §3 实施 |
| P5（无文档跟踪） | 本 L1/L3/L4 补记录 | 本次补齐 |
