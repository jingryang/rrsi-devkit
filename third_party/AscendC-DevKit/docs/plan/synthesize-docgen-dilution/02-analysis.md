# 02 — 方案分析（L3）

> 本工作：`docs/plan/synthesize-docgen-dilution/`。回答「有哪些选项、选了哪个、为什么」。
> 实施配方（改哪个函数、什么顺序、怎么验证）归 L4，拍板后另产出。

## 现状

- synthesize 阶段 = 门面 `ascendc-op-design-synthesize`，tail-call integrate + docgen
  （`orchestration-config.json` 的 `tail_calls`）。
- 缺 md 时 `fail_strategy = "halt"`（`design_substages.py` 缺 md → halt）。

## 候选方案

### 方案 B — 强化门面 SKILL.md 指令（否决）

在门面正文更强调「必须 tail-call docgen、md 必需」。否决：指令再强调，长上下文下仍会被
稀释，不根治（P1 根因不是指令不清，是稀释）。

### 方案 A — docgen 独立成段（选，根治）

docgen 从 synthesize 门面拆出，独立成一个 stage，独立 spawn、独立上下文。新会话重新注入
docgen 指令，不受 integrate 长上下文稀释。文档与契约一致性由「docgen 消费 synthesize 既定
产物（design_spec / tiling_strategy）派生 md」构造性保证（§2.9），不需同会话。

### 方案 C — 通用定向 respawn 兜底（选，兜底）

gate/transition 发现产物缺失时，不直接 halt，而是 respawn agent 并注入：
1. **客观错误原因**（缺什么产物——gate 确定的客观事实）；
2. **推测性 skill 提示**（不武断断言 skill 未调用）：

   > 可能是因为 XXX skill 未能正确调用和执行，如果确认请继续完成 skill 任务。

措辞要点（用户拍板）：gate 只观测到「产物缺失」，无法区分根因是「skill 未调用」还是
「调用了但输出 schema 有偏差」。武断断言「skill 未调用」会与 agent 自身记忆冲突（若它
实际调用了），制造困惑、降低补救效果；用「可能 + 未能正确调用和执行」的宽泛措辞覆盖
两种情况，把根因判断权交还给有完整上下文的 agent。

硬约束：**必须设重试上限**（防死循环空转）；每次重试都注入「上次为什么失败 + 必须产出什么」。

**skill 提示来源（不新增映射）**：不维护「产物 → skill」的中央映射。skill 提示由已有三份
信息组合：
- 缺什么产物（客观）：`output_contract().provides`（如 `design_doc`）；
- 本阶段 skill 范围：`STAGE_SKILL_MAP[stage]`（primary skill）+ `STAGE_TAIL_CALL_MAP[primary]`
  （门面 tail-call 的子 skill 列表）。

框架只给「缺什么 + skill 候选范围」，不精确到「哪个 skill 产哪个产物」——定位权交给有完整
上下文（门面 SKILL.md）的 agent。无 schema 的独立产物（md 等给人读的文档）不新增 schema、
不新增「产物→skill」映射，避免过度耦合与散弹式修改（§1.14 / §1.5）。

## 选择

方案 A（根治）+ 方案 C（兜底）组合。

## 理由（四把尺子）

- **可维护**：A 让 docgen 职责独立、边界清晰；C 是通用兜底（任何产物缺失都走同一通路），
  不针对 unique 打补丁。
- **可扩展**：同类「串行多子任务被长上下文稀释」的情况，A 的「独立成段」与 C 的
  「定向 respawn」都能自动正确归位，不靠为已知算子加特判。
- **可诊断**：A 让 docgen 产物独立检查；C 报客观事实（缺什么）+ 温和提示，不制造误导
  信号（§1.3）。
- **架构合理**：A 符合 stage 扩展点 + 文件接力（§2.3）；C 与 codegen build-retry 同模式，
  应收敛为一条通用通路（§2.5 唯一通路）。

## 与 codegen build-retry 的关系

C 的「产物缺失 → respawn + 注入原因/skill」与 codegen build-retry（build 失败 → re-spawn
coder + feedback）是同一模式。实施时评估复用/统一，而非在 design 阶段另造并行重试机制
（§2.5）。
