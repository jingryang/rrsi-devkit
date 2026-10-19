---
name: ascendc-op-tiling-precision-perf
description: 对单个算子计算模板执行精度分析 + 性能分析
triggers:
  - tiling-precision-perf
  - 精度分析
  - 性能分析
---

# AscendC 算子精度 / 性能分析

## 职责

对单个算子计算模板执行精度分析 + 性能分析，并进行跨 3 段产物的一致性校验。

**职责边界**：本 skill 是 tiling 推导的最后一环。精度分析和性能分析属于"评估型"工作，需要前两段（split + buffer-kernel）的完整输出作为输入。本 skill 不做新的切分或 Buffer 决策。

## 输入

从当前工作目录读取上游产物文件：

- `template_division.json`：模板划分产物（精度决策部分）。
- `tiling_current_template.json`：本模板已完成段（含 split 的切分方案/ubFactor/循环结构 + buffer_kernel 的 Buffer 分配表/Kernel 伪代码/TilingData 字段）。
- 当前模板已在 prompt 提供（「## 当前模板」段）。
- 算子身份已在 prompt 提供（「## 算子」段）。

> 不读其它模板或其它设计步骤写出的中间文件。
## 输出（用 Bash（`cat`）写到当前工作目录）

| 产物 | 必需 | required_keys | schema |
|---|---|---|---|
| `tiling_precision_perf.json` | 是 | `template, precision_perf` | `schema/tiling_precision_perf.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |

> 契约的机器校验来源：`schema/tiling_precision_perf.json`（JSON，含 required_keys + example）。
> 产出不符合 schema → DevKit 适配层拒绝，重试。
## 核心规则

- R1: Cast 时机 = CopyIn 后立即升精度，CopyOut 前降精度。**「升精度」（宽 FP 尾数减算术舍入）只对浮点算术累加有意义**；**整数运算本就精确**（仅溢出风险，扩宽是防溢出、非升精度），**int→FP 必丢精度（>2²⁴），禁止**。**非计算算子**（仅比较/搬运/重排/去重/掩码）**默认 native dtype**——升精度无累加可保、零收益。原语约束（如 Sort API 仅 half/float）强制更宽类型时**不属"升精度"**：FP 用 vector `Cast` + 验往返 bit-exact，**int 不得过 FP**、换原生 int 路径。判据按"算子是否对值做算术"，不认算子名。A5 下 Cast 时机更灵活，详见 `ascendc-op-design-shared/references/platform_diff.md`
- R2: 精度验收标准按 dtype 分别给出 atol/rtol
- R3: 每个数值必须有命名来源，禁止裸数字
- R4: **kernel 算术公式 vs golden 算术等价性（目标 dtype 强制，非仅 fp64）**
  精度分析必须核对 kernel 伪代码的算术公式与 golden 的计算在**真实 dtype**（fp16/bf16/fp32）下等价，
  **不得只验 fp64**——不同分解在非 fp64 下中间舍入不同（历史实证：两趟 lerp 形 `A+(B-A)*w` 与直接
  加权和形在 fp32 下可差 ~1 ULP，落 small_value/cancel 兜底判据触发整轮返工；"fp64 可分性已验证"
  是错误安心）。
  - **golden 算术来源**（按优先级，均为 tiling 段既有输入，不跨层跳上游）：
    ① `general_design.json` 的 narrative/公式段（概设描述了 golden 的算术/权重量化）→
    ② 工作目录 `requirement.json` 的 `golden_alignment`（若该子阶段物化了它）→
    ③ 可直接读的 golden.py。三处都取不到 → **显式标注「golden 算术未核对」为设计风险**
    （§1.2 可诊断），不得静默跳过。
  - kernel 若用与 golden 不同的分解（如 lerp 形 vs 加权和形），须**逐目标 dtype**给出等价性证据
    （bit-exact 或 ≤ 验收容差）。**形式对齐的主责在 buffer-kernel R9（书写期主自检，§2.9——问题在
    书写处就地修，不外推下游门）；本步是校验/第二道：正常情况下 R9 已对齐，本步确认算术达成目标
    dtype 精度。若发现形式仍不对齐（= R9 违约，异常），记录差异证据 + 需改的算术形式于自检并标注
    「R9 违约」，validate GV8 仅作兜底拦截（不依赖它作主发现点）。**
  - **golden 的权重量化是硬约束**：golden 把插值权重量化到输入 dtype（fp16/bf16）时，kernel 必须同量化；
    用更宽权重偏离 golden 的量化行为 → 逐元素输出偏差（历史实证）。
  - **硬件 FMA 语义纳入**：A2 FusedMulAdd 为两步舍入 vs golden 合成 FMA 单次舍入 → 1 ULP 差异；
    设计精度分析须覆盖此差异（是否需要软件 FMA 仿真 / 改累加顺序）。
## 与上游的一致性约束

> 下列上游内容均来自本次对话已提供的结构化产物（本模板切分 / buffer_kernel / 模板划分），不读 `.md` 中间文件。

- 精度策略必须与模板划分产物中的锁定决策一致（是否升 FP32、Subnormal 处理）。**策略合理性**（不只查"与锁定一致"）：锁定不得与算子语义矛盾——非计算算子锁定"升 FP32"无累加可保（违 R1），就地修正为 native dtype
- Cast 时机必须与 Kernel 伪代码（buffer_kernel 产物）中实际的 Cast 位置一致
- 性能分析中的循环次数必须与切分产物的 ubFactor 一致

## 执行步骤

> **不校验上游完成状态**：直接消费已提供的本模板切分 / buffer_kernel / 概设产物即可。**不去找
> checkpoint 判断上游"完成没"**——跨步骤搜寻"本应存在"的中间文件正是要铲除的死循环病根。

1. 从已提供的本模板切分 + buffer_kernel 产物提取：
   - 切分方案、ubFactor、循环结构（来自切分产物）
   - Buffer 分配表、Kernel 伪代码、TilingData 字段（来自 buffer_kernel 产物）
2. 精度分析：
   - 精度链条表（全部数据类型组合）
   - **golden 算术等价性（R4 强制）**：核对 kernel 算术公式与 golden 在**目标 dtype**下等价（非仅
     fp64）；golden 算术来源按 R4 优先级取，取不到则显式标「golden 算术未核对」为设计风险。
     不同分解（lerp 形 vs 加权和形）、golden 权重量化、硬件 FMA 语义逐项覆盖。
   - Cast 时机（A5 下更灵活，详见 `ascendc-op-design-shared/references/platform_diff.md`）
   - 验收标准（按 dtype 分别给出 atol/rtol）
   - 异常值策略（A5 Subnormal 软仿需确认对精度的影响）
   - **中转往返 bit-exact 验证（强制）**：凡含 `src→intermediate→src` 往返（intermediate ≠ IO dtype），逐 dtype **验证**（非断言）保号 / 保 ±0.0 / 保 subnormal / 保整数范围；任一不保 → CRITICAL → 消中转（改 native）或换路径。FP 类宽化（BF16/FP16→FP32）本身无损，损失来自用错 helper / 比较抹符号 / int 超范围——验证即证伪。
   - **特殊值保真（bit-exact 算子）**：±0.0 符号 / NaN / Inf 在比较与中转路径的保真须给 **kernel 级落点**（位掩码比较等），不得只写决策不落地。
3. 性能分析：
   - Tile 级计算/搬运时间估算
   - 流水线有效性验证（同步模型因平台而异，详见 `ascendc-op-design-shared/references/platform_diff.md`）
   - 整体吞吐估算
   - 性能瓶颈分析
   - **标量通路风险项（交叉印证）**：buffer_kernel 产物声明了 `scalar_access_points[]` 的点逐条列入瓶颈分析——标量逐元素搬送相对向量化 DataCopy 是数量级级性能差，须出现在瓶颈清单或给出可忽略论证；若性能推演显示某点的「无向量化等价物」排除论证可疑，如实记入自检（跨段一致性信号，交 integrate 如实标注），不得静默
4. 一致性自检（跨 3 段产物联合校验）：
   - [ ] TilingData ↔ Kernel（来自 buffer-kernel）
   - [ ] Buffer 表 ↔ Kernel（来自 buffer-kernel）
   - [ ] 核间切分轴 ↔ 核内切分轴无冲突
   - [ ] 覆盖验证通过
   - [ ] 精度验收有具体 atol/rtol
   - [ ] golden 算术等价性已核对（目标 dtype，非仅 fp64）；golden 不可得已显式标「未核对」（R4）
   - [ ] 中转往返已逐 dtype **验证** bit-exact（非断言）；bit-exact 算子 ±0.0/NaN/Inf 保真有 kernel 级落点
   - [ ] 跨段一致性：ubFactor ↔ Buffer 大小无矛盾
   - [ ] 跨段一致性：切分公式 ↔ Buffer 约束无矛盾
   - [ ] 硬件常量（带宽/UB/向量宽度/算力）均有命名来源且记入 verifiable_claims（`evidence.source_pointer` 指向 Tier1 硬件 json，verification=`api_checked`；性能瓶颈结论 verification=`derived`，`evidence.attempt_log` 写清可复算推导链）
   - [ ] hardware_api_capability 字段每个数值已与 `ascendc-op-design-shared/references/platform_diff.md` 真值表对比，不一致的已修正
   - 自检失败 → 就地修正直到通过
   - 自检通过后，用 Bash（`cat`）把单模板精度/性能的结构化产物写到当前工作目录（字段以本 skill「## 输出」段声明的 required_keys 为准，含精度方案、性能评估）。
   - `verifiable_claims` / `key_parameters`：放进 **`precision_perf` 段对象内层**（即 `precision_perf.verifiable_claims` / `precision_perf.key_parameters`），**不要**作为顶层兄弟字段。schema 已闭合（`allowed_top_level_keys`），顶层只允许 `template/precision_perf/step/status/decisions/external_verification/self_check_summary`（纯簿记 + 过程元数据）；gate-relevant 设计内容放顶层会在 DevKit 适配层被拒（重试）。

## 知识引用策略

通用知识引用策略（三层优先级 + 禁止猜测 + AskUserQuestion 兜底）详见 `ascendc-op-design-shared/references/knowledge_policy.md`。

平台差异化参考（A3 vs A5）详见 `ascendc-op-design-shared/references/platform_diff.md`。

**类目特定套路**：命中已知类目（按**结构判据**，不认算子名）时先查共享类目参考
`ascendc-op-design-shared/references/tiling-patterns/index.md` 路由到对应 `<类目>/patterns.md`
的精度/算法选型（如 reduction 的 Welford/Group Reduce/二分累加精度策略），
再落到本 skill 的精度分析与性能评估。

本 skill 特有的查询场景：

| 层级 | 查询场景 | 对应执行步骤 |
|------|---------|-------------|
| Tier 1 | 带宽、算力、A5 寄存器约束（32 RegTensor/8 MaskReg） | 步骤 3（性能分析） |
| Tier 2 | 流水线有效性判断、精度验收标准、Double Buffer 规则 | 步骤 2（精度）、步骤 3（流水线验证） |
| Tier 3 | Cast API 细节、Subnormal 行为（A5 软仿）、对齐 API 的 dtype 限制 | 步骤 2（Cast 时机、异常值） |

**查询约束**：
- API 使用方法必须来自 `ascendc-dev-knowledge` 的明文文档，禁止凭记忆虚构（"命名来源、禁止裸数字"见核心规则 R3）

## 约束

- 只推导当前模板，不修改其他模板文件或产物文件
- 不做切分设计或 Buffer 分配（不越界到前两段职责）
- 发现前两段产物的不一致时，记录到自检结论中，不直接修改前两段产物
- 推导中遇到需要用户决策的点，直接 AskUserQuestion
