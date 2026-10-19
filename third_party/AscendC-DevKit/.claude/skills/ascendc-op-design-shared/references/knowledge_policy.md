# 知识引用策略（共享定义）

> 本文件定义了 `ascendc-op-*` 系列所有 skill 通用的知识引用策略。各 skill 在 SKILL.md 中只需保留特有的查询场景表格和约束，通用策略部分引用本文件即可。

## 核心原则

**只做有理论依据的推理，禁止猜测。**

当推导需要领域知识支撑时，按以下三层优先级查询。三层均无结果时兜底向用户提问。

## 三级知识源体系

| 层级 | 知识源 Skill | 通用用途 |
|------|------------|---------|
| **Tier 1** | `ascend-hardware` | 目标芯片硬件参数查询（UB 大小、核数、带宽、向量宽度、对齐要求、寄存器约束等）；**代际/产品名映射**（950PR/950DT/950=Atlas 350 加速卡=A5；910D 目录即该系；SKU 跨档 8/28/32/36）也以 ascend-hardware 为准，**不要在推理中反复猜测命名** |
| **Tier 2** | `evolution-knowledge` | 设计模式参考、Tiling 策略选择、BUFFER_NUM 选择、精度策略、瓶颈判断、通信模式选择 |
| **Tier 2.5** | `ascendc-api-best-practices` | API 正确用法 + 避坑（如间接采样用 Gather 非逐元素 DataCopyPad、越界钳制、粒度/dtype 约束）；查 API 用法时优先于 Tier 3 裸签名 |
| **Tier 3** | `ascendc-dev-knowledge` | 具体 API 签名与参数约束、存储层级细节、数据格式转换开销、dtype/format 兼容性 |

## 查询约束

- **按需查询**，不做全量加载：仅在遇到具体知识缺口时查询对应层级
- 查询结果仅用于当前 skill 职责范围内的推导
- 每个数值必须有命名来源——来源可以是知识库、op_spec、概设文档或用户输入，禁止裸数字

## 骨架级 API 强制查证门（mandatory，与"按需查询"并列）

"按需查询"由 agent 主观感知缺口触发；本门由**客观语义特征**触发，不依赖 agent 是否自信，用于杜绝"自信的错误前提从不查证"。

**触发条件（客观，与 agent 主观判断无关）**：算子语义包含 gather / scatter / reduce / sort / topk / broadcast / transpose 等**决定计算结构的骨架级 API**。

**强制动作**：在"选用"或"排除"任一骨架级 API 前，**无条件**完成明文查证，得出"可用 / 不可用 + 出处"结论，并写入对应 checkpoint 的 `verifiable_claims`（见 `checkpoint_convention.md`）。查证顺序：**先查 Tier 2.5（`ascendc-api-best-practices`，API 用法 + 避坑）→ 查不到再查 Tier 3（`ascendc-dev-knowledge`，裸签名细节）**——裸签名只讲参数约束，不讲"该怎么用 / 别怎么用"，用法坑在 best-practices 层（如 gather 的"分块搬入 + 越界钳制" vs 裸签名的"srcOffset 是字节"）。

**禁止能力外推**：不得以"同类指令缺失"推断目标 API 能力。例："无 Scatter 指令" → "无 Gather" 为**非法外推**；gather 与 scatter 的硬件支持是两个独立结论，必须分别查证。

**查不到的兜底**：Tier 3 无明文 → 按下方兜底策略 `AskUserQuestion`，以用户答案为准，并在 claim 的 `evidence` 中标注来源为用户输入。

**发现知识源本身有信息遗漏时的处理（禁止自行猜测填补，先下沉再上报）**：
- 若某层知识源（含 best-practices）发现**该 API 的关键约束（dtype 支持、精度边界、对齐要求等）文档未覆盖或描述不清**，**不得自行猜测、不得默认"文档没提就是没限制"**——文档没提 ≠ 无约束，很可能只是漏写了。
- **处理顺序（遵循分层查询，不下沉就是漏查）**：① 先向**下一层知识源下沉探索**（best-practices 漏 → 查 Tier 3 dev-knowledge 裸签名/支持矩阵；dev-knowledge 漏 → 查更底层来源），看下层是否有该约束的明文；② 只有**所有相关层级都没有**该约束的明文时，才显式暴露：在产物 `known_limitations` / `verifiable_claims` 标注「API X 的 <约束> 未被知识库覆盖，未确认」，涉及决定计算正确性的约束（如跨 dtype 转换是否有损、Select 支持哪些 dtype）时按兜底策略 `AskUserQuestion`；③ 不猜测填补，留给知识库维护者补充或用户裁决。
- 判据：一项 API 约束缺失影响正确性判断时，"没查到"必须显式暴露（§1.2 可诊断），不能静默假设"没写就是没限制"；但暴露前必须已完整下沉探索过各层，不能只查一层就报"缺失"。

## 特殊值语义对齐门（mandatory，elementwise Max/Min 类算子）

"骨架级查证门"管 gather/scatter/reduce 等**结构**类 API；本门管**语义**类选型。当算子需与
golden **逐位对齐**（precision threshold=0 / bit-exact）且语义属 elementwise "取较大/较小"
（`maximum`/`minimum` 及 foreach 变体）时：

- **触发即默认安全选型**：`compute_ops`/kernel API 序列写 `Compare(NE,self,self)` +
  `Compare(NE,other,other)` + `Compare(GT,other,self)` + `Select` 复合原语（逐位复现 golden
  "NaN 传播 + tie 取 self"），而非裸 `Max`/`Maxs`。
- **确需用 `Max`/`Min`/`Maxs`/`Mins`**：必须明文支撑——SIMD Max 的 NaN 语义未文档化、±0 tie
  仅写明 `-0/+0→+0`（≠ golden tie 取 self），**不得**默认其与 golden 一致，**不得**借 SIMT
  `fmax`/`__hmax` 的忽略-NaN 文档为其 NaN 行为背书（二者语义相反）。
- 规则、语义对照表与锚点（`Max-43.md` / `__hmax.md` / `fmaxf.md`）见
  `ascendc-op-design-shared/references/special-value-semantics-max-min.md`；决策写入
  decisions / `verifiable_claims`（带锚点），不留编码阶段重推。

## 兜底策略

当三层知识源均无法提供推理所需的关键信息时，**必须通过 `AskUserQuestion` 向用户提问**，以用户答案为准继续推导。用户已明确回答的问题不再重复查询知识库。

在输出文件中，基于用户输入的结论应标注 `<!-- 本结论基于用户输入 -->`。
