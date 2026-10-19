# L3：P10 方案分析——设计产物「物理级不变式」层（step-111）

> 状态：**冻结**（2026-09-01 拍板）。归因取证结论、五轮质询（完整性/全貌/原则符合性/
> 反向质疑/负面影响/通用性）与两项待裁定（F2 在位检查、≥80k 块归因）均已收敛。
> L1 事实：`01-problems.md` P10。L4：`11-impl-design-physical-invariants.md`。

## 1. 来龙去脉（问题全貌）

### 1.1 现象链

批 49134b 中复杂族算子（unique_dim/logcumsumexp/interpolate）的 coder 会话产生
100k 级单体 thinking 块并反复撞 32k token/步输出墙（P6 域），归因取证（L1）显示
**codegen 侧 29 块 ≥80k thinking 中 19 块（66.9%）是补设计**——coder 在编码期重推
本应在设计期交付的物理层内容：workspace 平面布局公式、跨核前缀基址、tile 状态布局、
broadcast stride 复合映射、host↔kernel 公式对、跨管同步边界。unique_dim 单个
codegen 会话 8 块 874k chars 中 7 块为补设计（118k 块内容=「T1 伪代码 vs 自己的
v3 改进」的对齐再设计——**设计在 coder 脑内迭代、不落地**，1.7M thinking 只落盘
2 个 tiling 头文件）。

### 1.2 根因（制度性豁免，非能力缺失）

设计 agent **并不缺物理推导能力**——design 侧 21 块 ≥80k（2.04M chars）深推理真实
存在且高质量。缺口在**产物契约止步于逻辑层**，两处制度性豁免让物理内容合法地不落地：

1. **tiling-buffer-kernel SKILL 边界条款**（:84 一带）：主伪代码只覆盖快路径、
   「泛化发射属 codegen 责任」——允许留白但**不问留白内容的性质**。T2（scan 族）
   据此把「两阶段兜底= F1 同构扩展」一句带过，而该「同构扩展」实际是**新物理层**
   （workspace 跨核平面布局 + publish/fold 地址恒等式 + SyncAll 相位），必须展开
   却未展开。**「同构扩展」判定失手是本批最大单点漏洞。**
2. **workspace 契约字段只到字节**（:109）：`{user_workspace_bytes, rationale}` 两字段
   ——rationale 是自由文本，公式写在里面**不可被确定性消费**（coder 无法用字段路径
   取到布局公式，只能读 prose 再自己重推）；布局/stride/地址恒等式无载体字段。

后果三连：coder 付 98k 级重推导（P11 上下文经济恶化）→ 推导在 compaction 中冲失、
重读蓝图重推循环 → host/kernel 公式漂移风险（coder 原文自评「FRAGILE (host/kernel
formula drift)」）。

### 1.3 明确不是什么（边界澄清）

- **不是「schema 装不下」**：rationale 自由文本能写下字节公式——缺的不是容量是
  **可确定性消费的结构化载体 + 必须交付的判据**。
- **不是设计能力问题**：设计期已产出 4.68M thinking 物理推导，只是输出时被
  产物契约压缩掉。
- **不由本方案覆盖**：设计「错了/次优」（unique_dim v3 反复推翻）是设计质量域，
  由设计自检闭环（§2.9）兜；设计内生深推理撞墙是 P6 域（cut 分类恢复，step-110
  已落）；coder 期 API 验证（3 块知识库级纠错）属知识前置域（§1.5），本方案不
  处理但在 §6 观测项留信号。

## 2. 方案选型

| 选项 | 内容 | 否决/采纳理由 |
|---|---|---|
| A. 教 coder 更快地推 | 给 coding skill 加「高效推导指引」 | 治标：推导总量不降，FRAGILE 风险不消，违反「源头解决」 |
| B. 设计产物全量公式化 | 所有物理推导全部结构化交付 | 过度结构化（§1.14）：elementwise 族无此需求，全量交付加重全部算子负担 |
| **C. 判据 + 载体 + 消费端 + 机械兜底（选定）** | A1 判据（何时必须展开）+ A2 载体（落哪）+ F1 消费（coder 直译）+ F2 在位检查（机械兜底） | 分层：复杂族自动归位、简单族零负担；单一权威（契约字段）；有明确反馈消费渠道（§2.9②） |
| D. 下游门查设计产物 | validate 加门查 layout 完整性 | 门越界查上游（§2.9 第四条）：发现问题修不了，纯噪音 |

选定 C。四把尺子过堂：**可维护**（复用 axis_param_design 既有表达，不造第二套）；
**可扩展**（判据是结构信号，新算子族自动归位）；**可诊断**（缺契约=机械可判+留信号）；
**架构合理**（判据/载体在设计 skill 产权、消费在 coder skill 产权、机械检查在
orchestration 产权，各归其位）。

## 3. 方案详设计（三层形态：约定 / 机械 / 观测）

### 3.1 A1——物理层展开边界判据（约定层，源头）

位置：`ascendc-op-tiling-buffer-kernel/SKILL.md`「与上游的一致性约束」段新增条款。
内容（结构断言，可判定）：

> **物理层展开边界（留白纪律）**：本 skill 产物允许把部分实现细节留给 codegen，
> 但留白必须满足以下二选一：
> 1. **点名载体**——被留白的物理推导若可由产物字段承载，必须已写进对应字段
>    （GM 布局/偏移/stride → `workspace.layout_contract`；轴参寻址 → 上游
>    `axis_param_design`），不得只存在于推导过程；
> 2. **同构测试**——无载体字段的留白必须与既有伪代码**同构**（仅变量重命名/
>    循环重排级对应）。凡引入下列任一**新物理层**的推导，不得以「同构扩展」
>    「属 codegen」留白，必须展开为结构化字段：
>    - **新 GM 布局**：workspace 内平面划分、跨核可见区域布局、slot 复用；
>    - **新跨界契约**：host tiling 公式 ↔ kernel 寻址公式对、字段 ↔ 地址恒等式、
>      发布/汇聚操作的地址恒等式；
>    - **新同步边界**：跨核 SyncAll 相位、跨管 flag 依赖、生产者-消费者次序。

三条结构信号即「同构测试」的可判定形态——判「该不该展开」用**内容性质**（是否新
物理层），不用机制特征代理（§1.10）。:84 既有边界条款补一句载体指名（其载体本就是
`axis_param_design`，条款已点名，仅需与新判据衔接），不推翻。

### 3.2 A2——载体字段 `layout_contract`（约定层，落点）

位置：`ascendc-op-tiling-buffer-kernel/SKILL.md` :109 GM workspace 预算条款 +
`schema/tiling_buffer_kernel.json` description/example。

- workspace 契约从 `{user_workspace_bytes, rationale}` 扩为
  `{user_workspace_bytes, rationale, layout_contract}`。
- `layout_contract`：字符串数组，每条一段「平面/区域 → 布局公式或地址恒等式」，
  **表达沿用 `axis_param_design.tiling_data_extensions` 的既有形态**（概设 schema
  example 已有先例 `["x0GmOffset", "x1GmOffset", "axisStride"]`）——不造第二套
  表达（§1.15 唯一通路精神）。
- 覆盖要求：每条至少覆盖一个跨界事实——平面字节公式与 stride、跨核 base 偏移
  公式、发布/汇聚地址恒等式、（如有）slot 复用图。**workspace 在位 ⇒
  layout_contract 非空**（布局平凡=单一连续 scratch 时给一条公式即可——公式
  本身就是跨界契约）。
- schema example 用**通用占位符**（`planeA: blockDim*rows*sizeof(T)` 级），
  禁实例公式（§1.11/§2.12：skill 不耦合本批算子的具体推导）。

### 3.3 F1——coder 消费端（约定层，A3 侧）

位置：`ascendc-op-dev-coding/SKILL.md` GM workspace 设置节（:203 一带，已有
「userWorkspaceSize 优先取设计产物」的消费行，同族扩展）。

> 设计产物 `tiling_results.buffer_kernel.workspace.layout_contract` 在位时：
> kernel 侧跨核 GM 布局（平面划分/偏移/stride）与 host tiling 公式**按契约直译**，
> 禁止现场重推布局（历史实证：重推=100k 级深推理 + host/kernel 公式漂移风险）。
> 契约与实现冲突、或 kernel 需要 GM 布局而契约缺位时：最小推导 +
> decision_log 记「layout_contract 缺失/冲突，codegen 现场推导（应在设计期交付）」
> + `known_issues` 交棒——不自推后静默吸收。

**A5 边界**：`ascendc-op-dev-coding-regbase`（A5 coder）归同事产权，本步不动；
其等价消费行需与 A5 侧同事确认后另行落（设计侧 skill 为两 chip 共用，A1/A2/F2
自动覆盖 A5 设计链）。

### 3.4 F2——机械在位检查（机械层，用户已裁定要做）

位置：`TilingStage.transition`（design_substages.py）schema 解析后、segment 汇总前。

- 判据（纯结构信号，2026-09-02 二轮收紧）：workspace 合法形态集（封闭）=
  {缺省, null, `'none'`, object}——null/缺省=显式/隐式未使用，'none'=实践中等义
  写法（容忍）；object 须含非空字符串数组 `layout_contract`；**其余形态（裸数字/
  list/任意字符串）=载体畸形，同样打回**（初版只查「dict 在位而字段缺」对畸形
  载体静默——§1.2 可诊断点名反模式「推迟到更难定位的下游」；查内不查外的不一致
  经用户质询修正）。命中 → artifact-retry：`ErrorFeedback(incomplete_output) +
  user_feedback`，反馈文案点名缺什么/怎么改。
- 产权归属（§2.9②）：只查**在位性**（机械可判），不查内容正确性（内容归设计
  agent 自检 + A1 判据）；反馈经既有 user_feedback 通道被责任 agent 确定性消费
  （补一个字段即解）——不是「只发现问题修不了」的噪音门。
- **不越界**：不查上游概设/切分产物（那是上游自检）；不查 coder 消费（那是
  F1 约定 + 维9 既有自检域）。
- 成本：首个批次存量产物会触发一次性补全 retry（有界一轮，反馈精确）；此后
  常态零触发。

### 3.5 观测层

- F2 retry 本身留 events 痕迹（error_type=`incomplete_output`，实施期修正：R1 语义「产物已交付、字段漏写、喂提示可确定性纠正」→ artifact-retry 桶（独立预算不烧 iteration），非 `schema_violation` 的迭代语义）。
- F1 的 decision_log/known_issues 记录 = coder 侧契约缺口信号（下批复盘可统计
  「设计契约覆盖率」——不做实时门，纯观测，§1.14）。

## 4. 反向质疑（五轮质询沉淀）

| 质疑 | 回应 |
|---|---|
| 「设计加了推导，设计侧不是更重、更容易撞墙？」 | 是诚实代价：设计块本就 99–105k（内生深推理），增量是把**已做的推导从脑内搬到字段**（写出即交付），非新增推导总量；撞墙由 P6 域兜（step-110 已落）。真实收益=FRAGILE 消除 + 推导持久化（compaction 冲不掉）+ coder 侧上下文大幅减负 |
| 「上下文变大导致输出质量下降？」 | 净变化为**负**：coder 侧省 ~1.86M chars 重推导（本批 6 算子），设计侧每模板只增一个字符串数组（per-template 会话隔离，T1/T2/T3 各自携带、互不叠加）；schema example 增 3 行 |
| 「耦合具体算子？」（§1.12） | 全部结构信号：workspace 在位、layout_contract 非空、三条新物理层信号。删除测试：删掉任何算子名不影响判定。族遍历：elementwise（无 ws→零变化）/ reduce 跨核（1–2 条公式）/ scan-carry（平面布局+恒等式）均自动归位 |
| 「F2 是控模型的门？」（§1.14） | F2 查的是**产物契约在位性**（R1 artifact-retry 族，error_type=incomplete_output），反馈可确定性消费（§2.9② 正当理由②），非「抓模型错」的回炉门 |
| 「为什么不教 split skill？」 | 布局产权在 buffer-kernel 的 workspace 契约（split 是逻辑层，止步协议正确）；最小改动落在产权正确的层 |
| 「老批次 resume 会炸？」 | 会触发一次有界 retry 补全（反馈精确指向缺字段），非失败；已在 L4 记录预期 |

## 5. 预期效果与不承诺

**承诺**（下批可验证判据见 L4 §5）：复杂族 coder 会话 ≥80k 补设计块占比显著下降
（本批 66.9% → 目标 <20%）；FRAGILE 自评消失；`known_issues` 出现契约缺口信号
（存量知识暴露）。

**不承诺**：设计侧 thinking 总量下降（内生推导不减，只是落盘）；设计撞墙次数下降
（P6 域）；「设计错/次优」形态消除（unique_dim v3 推翻属设计质量，本方案只保证
「已定的设计被结构化交付」）；F4 anchoring 风险消除（契约锁死错误布局时靠 F1
冲突信号交棒回设计，未量化）。

## 6. 遗留观测项（不在本步实施）

- coder 期 API 事实纠错（3 块）：count 形态 ReduceSum A2/A3 无、isPad dummy 填
  首元素值、Cast FLOOR/CEIL fp32→fp32 存疑——属知识库事实层（§1.5），是否补录
  `ascendc-dev-knowledge` 另行立题（下一批 self-evolve 扫知识库缺口时合并评估）。

## 附录：50 块 ≥80k reasoning 逐块分类表

（op / 会话阶段 / 块尾缀 / chars / 分类；C1=补设计 C2=编码期本职 D1=设计期本职。
判定依据=头 360 + 中 240 字符采样人工判读；样本全文存档于归因取证运行记录。）

| # | op | 阶段 | part | chars | 类 |
|---|---|---|---|---|---|
| 1 | unique_dim | codegen | Rgomprdn | 118,132 | C1 |
| 2 | unique_dim | tiling | k20w9slC | 116,574 | D1 |
| 3 | unique_dim | 概设 | R6NA2h56 | 115,695 | D1 |
| 4 | unique_dim | codegen | Hz92cJmx | 115,114 | C2 |
| 5 | take_along | tiling | islxfxAR | 114,332 | D1 |
| 6 | unique_dim | codegen | nsmW0OAp | 109,787 | C1 |
| 7 | unique_dim | codegen | paXCTQGE | 107,969 | C1 |
| 8 | unique_dim | codegen | 7gxaOXkj | 107,275 | C1 |
| 9 | unique_dim | codegen | tUQOTsuk | 106,906 | C1 |
| 10 | interpolate | tiling | 8HE556St | 106,770 | D1 |
| 11 | unique_dim | codegen | Vj01pJhd | 105,297 | C1 |
| 12 | logcumsumexp | tiling | ROqJAQ86 | 104,916 | D1 |
| 13 | unique_dim | codegen | 5CW8sRLJ | 103,071 | C1 |
| 14 | logcumsumexp | tiling | aUXxF5Cc | 102,855 | D1 |
| 15 | take_along | codegen | KiYkI557 | 100,926 | C1 |
| 16 | logcumsumexp | tiling | cjkGq3MC | 98,801 | D1 |
| 17 | logcumsumexp | codegen | UvAe0J0N | 98,692 | C1 |
| 18 | interpolate | codegen | kfNTVEEb | 98,488 | C1 |
| 19 | interpolate | codegen | 4u4N4scN | 97,605 | C2 |
| 20 | interpolate | tiling | lfoVap3Z | 97,116 | D1 |
| 21 | logcumsumexp | tiling | L1INOoM9 | 96,190 | D1 |
| 22 | upsample | tiling | Y0bjz0bk | 96,176 | D1 |
| 23 | logcumsumexp | tiling | zqt3eBim | 95,944 | D1 |
| 24 | interpolate | codegen | IfnOwdSv | 95,938 | C1 |
| 25 | logcumsumexp | tiling | 5XVGik2O | 95,912 | D1 |
| 26 | upsample | codegen | rWuCXJEq | 95,898 | C2 |
| 27 | take_along | 概设 | mqmQUfMz | 95,084 | D1 |
| 28 | interpolate | tiling | IWpl1sU8 | 94,014 | D1 |
| 29 | logcumsumexp | codegen | 8zI71SlO | 93,902 | C2 |
| 30 | logcumsumexp | tiling | 2HKljyyV | 92,939 | D1 |
| 31 | logcumsumexp | codegen | BSCsJqmj | 92,420 | C1 |
| 32 | upsample | docgen | HV2OhTto | 92,027 | D1 |
| 33 | logcumsumexp | codegen | YM1oGU7P | 91,449 | C1 |
| 34 | interpolate | codegen | f5Z87JPG | 90,526 | C1 |
| 35 | take_along | codegen | uA9PbTQo | 90,128 | C1 |
| 36 | logcumsumexp | tiling | TmcgGjq8 | 89,912 | D1 |
| 37 | interpolate | codegen | WKVdX1qZ | 89,507 | C1 |
| 38 | mse | synthesize | yP4PWSoJ | 89,159 | D1 |
| 39 | interpolate | codegen | 7pKZmQkE | 89,105 | C2 |
| 40 | interpolate | codegen | hLpRZXO0 | 88,764 | C2 |
| 41 | interpolate | codegen | q0G1m9WN | 87,815 | C1 |
| 42 | logcumsumexp | tiling | 4I7xpj82 | 87,698 | D1 |
| 43 | interpolate | codegen | 587F6BNu | 87,335 | C2 |
| 44 | interpolate | codegen | 0Hh9g9zE | 86,282 | C2 |
| 45 | take_along | codegen | IbtGOVpd | 84,070 | C2 |
| 46 | logcumsumexp | codegen | myxkOM8t | 81,130 | C1 |
| 47 | logcumsumexp | tiling | boDSYV6C | 80,804 | D1 |
| 48 | logcumsumexp | codegen | 7JbfT8Nr | 80,606 | C1 |
| 49 | interpolate | codegen | t085bMv2 | 80,398 | C2 |
| 50 | logcumsumexp | tiling | Uqan5nri | 80,034 | D1 |

**汇总**：C1=19 块 1,856,062 chars；C2=10 块 918,473 chars；D1=21 块 2,042,952
chars。C2 中含 3 块 API 事实纠错（#43/#44/#49，均 interpolate codegen）；
D1 中 5 块为 resume 重锚定续块（#20/#21/#30/#36/#42 一带，内容为继续真实推导）。
