# 问题记录：设计蓝图不可实施 + coder 无合法处置出口

> L1 问题记录 —— 只记录客观事实（哪里坏了、凭什么这么说），不提方案、不排顺序、不写决策。
> 轨迹层事实（零落盘 / cut 形态 / 文字度量无区分度）产权在 `thinking-budget-convergence/01-problems.md`
> （P1/P9/P10/P11），本文件只记录其下游根因链上的新事实。

## F1 设计蓝图含物理不可实施的算法路径

**事实**

批 `20260911-172304-501e35` exec `20260911-172304-e80ca9`（adaptive_avg_pool_3d）的 T1 设计产物
将 W 维窗口和指定为「Hillis-Steele 向量化扫描：⌈log2(W)⌉ 步**移位向量 Add**（LocalTensor 偏移访问）」。

该路径违反知识库明文约束：`api_reference_docs/基础API/矢量计算/基础算术/Add.md:72-73` ——
向量 Add 的 dst/src0/src1「LocalTensor 的起始地址需要 32 字节对齐」。fp32 下移位 1/2/4 个元素 =
4/8/16 字节偏移，对 32B 取余非零，**必然违约**；移位 8/16/32/… 步（32/64/128 字节）才满足。

**证据**

- `output/20260911-172304-501e35/20260911-172304-e80ca9/artifacts/staging/tiling_results/T1.json`
  → `buffer_kernel.verifiable_claims[1]`（claim 原文 + evidence + `verification: derived`）
- 同目录 `artifacts/design/tiling/T1/decision_log.json` → `key_decisions[2]`（选型动机为性能：
  「标量累加每行 256 次，最坏 13.4M 行×256 = 3.4B 标量操作不可接受」——**动机成立，路径违约**）
- `.claude/skills/ascendc-dev-knowledge/references/api_reference_docs/基础API/矢量计算/基础算术/Add.md:72-73`
- coder 会话 `agents/ascendc-coder-05.jsonl` turn 39 原文：
  *"the design's claim '每步为向量 Add 带移位操作数（LocalTensor 偏移访问）' has an alignment issue for small steps"*

## F2 该 claim 的查证引用了知识库中不存在的内容，verification 仍标 derived 放行

**事实**

T1 该 claim 的 `evidence.source_pointer` 写的是「ascendc-dev-knowledge（**向量 Add API 支持
LocalTensor 偏移访问**）」——知识库中不存在这句话；`Add.md` 说的是反面（起始地址须 32B 对齐）。
即：产出方声称已查证（标 `derived`，属"文档映射推导"等级），引用内容却不支撑结论。

同一产物内的 Gather 选型 claim 是正经 `api_checked`（source_pointer 指向 `api-gather.md` 真实
章节、attempt_log 写了查证过程）——**查证纪律在同一产物内有正确执行实例**，本条属个案失守而非
机制缺失。现行自检边界（`ascendc-op-tiling-buffer-kernel/SKILL.md:153`，P82 step-58 刻意划定）：
selfcheck 只验「有出处、非裸数」，**不验引用内容是否支撑结论**——本条恰好从此边界下漏过。

**证据**：T1.json 两条 claim 的 evidence/verification 对照；`checkpoint_convention.md`
「selfcheck 边界（P82 step-58）」与「证据契约字段规则（A2）」两节。

## F3 设计期对齐类自检的作用域止于 Buffer 尺寸表，不覆盖算法内部向量操作的操作数寻址

**事实**

`ascendc-op-tiling-buffer-kernel/SKILL.md` 的对齐类自检现状：

| 自检项 | 作用域 |
|---|---|
| `:147` 对齐验证通过 | Buffer 分配（尺寸够不够） |
| `:152` Buffer 表含 `AlignUp(x,32)` 列 | Buffer 字节数建模 |
| 「骨架级断言红队复核（A3-轻）」自检项 | 问「凭什么**排除备选**」，不问「**所选路径**的用法形态是否满足 API 约束」 |

R1（32B 对齐红线，`:42`「所有 Vector 计算和 DataCopy」）在 skill 里存在，但**没有任何自检项把它
伸入算法内部的操作数偏移/移位形态**。T1 的 Hillis-Steele claim 按上述全部自检**合规通过**。

**证据**：`ascendc-op-tiling-buffer-kernel/SKILL.md:42,147,152,153,154`；T1 产物通过设计期全部
自检与产物校验、进入 staging 的事实（run 无 design 侧 retry 记录）。

## F4 coder 对明显蓝图缺陷无合法处置出口，正确诊断无法转化为行动

**事实**

coder 会话（`agents/ascendc-coder-05.jsonl`，fresh 退化后的第 5 次尝试）按时间序：

| 轮 | 行为 |
|---|---|
| turn 39 | **正确诊断**对齐违约（引 Add.md 约束） |
| turn 45 | *"**Decision: Use CumSum for the W-axis prefix sum.**"* → 紧接 *"Actually, wait. Let me reconsider once more."* |
| turn 52 | *"**FINAL DECISION on prefix sum: Use CumSum** … I've spent too much time on this."* → *"Actually, let me reconsider ONE more time."* |
| turn 58 | 列完 13 个待写文件：*"Let me write them now."* |
| turn 62（终轮） | 74,756 字符 thinking、12-gram 重复率 86.8%（内容为给自己重证 Hillis-Steele 数学正确性），被输出上限截断。**全程零 Write** |

coder skill 纪律现状（`ascendc-op-dev-coding/SKILL.md`）对这一处境**无分支可走**：

- 「忠实翻译上游蓝图」（实现蓝图主源 = `buffer_kernel.kernel.pseudocode`）→ 蓝图即 Hillis-Steele；
- 「无法确定编码路径 → 报错退出」（`:30-34` 零交互纪律）→ 该条款为**输入缺失**设计；本例输入齐全，
  是蓝图与约束**冲突**，语义上够不着；
- 唯一同构条款「GM workspace 设置」节内 layout_contract 条款（：契约冲突 → 最小推导 + decision_log + known_issues 交棒）
  **仅覆盖 GM 布局冲突**，不覆盖算法路径冲突。

结果：诊断在手、变形方案（标量头部 + 8/16/32 向量步）一度推出，但无被许可的动作 → 静态分析
反复自我推翻 → thinking 膨胀截断 ×5（4 resume + 1 fresh）→ 39.4 分钟 `incomplete_output` halt。

**证据**：`agents/ascendc-coder-0{1..5}.jsonl`（工具统计：5 次尝试 write/edit 均为 0）；
`run.log:1132-1589`（5 次 cut-retry 与 halt 全记录）；skill 条款行号同上。

## F5 静态可行性判断在弱模型上不可靠，不能单独作为改方案的依据

**事实**

- 同批同模型（pangu_ultra_moe）的 transpose 成功案例同样存在「反复宣布落盘却不落盘」形态
  （P10：宣布写文件 241 次，比失败案例 42 次更多）——文字层打转度量**无成败区分度**；
- 模型的静态结论可能正确（本例对齐违约为真）也可能过度保守（未生成 ground truth 前不可知）；
  本 run coder **从未写过一版代码、从未编译过一次**——其「不可行」结论从未经过实测检验；
- 下游实测层（build 结构化首错 / smoke / precision golden 对照）是已存在的机械权威
  （`154ce60f` build 反馈携带结构化首错已落地）。

**证据**：`thinking-budget-convergence/01-problems.md` P9/P10；`154ce60f` commit。

## F6 既有可复用模式（处置授权的证据纪律先例）

**事实**

- `ascendc-op-dev-coding/SKILL.md`「GM workspace 设置」节内 layout_contract 条款： 冲突 → 最小推导 + decision_log 记因 +
  known_issues 交棒设计侧，**不得自推后静默吸收**——「契约冲突」处置的既有模板；
- 维4 AR-1（自检维度表 + Step 6 登记规则两处）：标量数据搬送默认禁 + 逐点授权，data-move 类须 `reference` 命中设计声明
  或 `deviation_evidence` 三键齐备（failure_signature / repro_or_log 真实存在路径 /
  why_no_vector_equivalent）——**偏离授权必须带证据**的既有纪律；
- step-92 反例：coder 调试期窄豁免扩张成**全标量化 + 单核**，性能差 baseline 4 个数量级——
  无证据纪律的偏离授权必然被滥用；
- R8 先例（`ascendc-op-tiling-buffer-kernel/SKILL.md:65,124,155`）：strided DataCopyPad 的
  「搬运行距 == 寻址行距」结构断言——**地址形态约束类自检的既有形态**（本 work 1a 是其在
  Vector API 操作数侧的同类补全）；
- step-93：kernel 错误走 known_issues 交棒 precision 阶段——**跨阶段交棒通道**已存在。

**证据**：上述各条款与 commit（step-92 `codegen-perf-eval-gap`、step-93 `codegen-faithfulness`、
R8 `datacopy-stride-consistency.md`）。

---

## 需求记录（用户 2026-09-14 提出，同日修正）

- **R1**：方案必须**源头解决**；如有必要可以多层兜底。
- **R2**（初版）：codegen 第一版可以按设计实现；但实际测试发现问题，**必须以测试为准，不以设计
  为准**；也不要出现完全不做测试就直接改方案。
  **修正（2026-09-14）**：如果是设计蓝图的**明显问题**，允许**先改再测试**。目的始终是写出高质量的
  算子代码，不是为了控制模型——**帮助模型而不是限制模型**；如果修改方案帮不到模型，那就不需要修改。
- **R3**：新增的自检内容必须能够**闭环消费解决**；能解决的问题不要轻易 halt。
- **R4**：决策上不要出现冲突或者矛盾，让弱模型难以决策。
