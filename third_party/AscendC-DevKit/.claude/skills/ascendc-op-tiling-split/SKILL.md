---
name: ascendc-op-tiling-split
description: 对单个算子计算模板执行核间切分 + 核内切分推导
triggers:
  - tiling-split
  - 核间切分设计
  - 核内切分设计
---

# AscendC 算子 Tiling 切分设计

## 职责

对单个算子计算模板执行核间切分设计 + 核内切分设计（ubFactor 推导）。

**职责边界**：本 skill 属于 Tiling 推导的"执行层"。上游 `ascendc-op-general-design`（策略层）已给出多核切分轴优先级和循环框架方向，`ascendc-op-design-template-division`（决策层）已锁定精度策略、BUFFER_NUM、多阶段 UB 方案等全局决策。本 skill 不重新决策切分轴优先级，而是基于上游给出的方向和锁定决策，代入具体数值完成推导。

## 输入

从当前工作目录读取上游产物文件：

- `general_design.json`：概设产物（轴优先级、各模板循环结构、Tiling 级数）。
- `template_division.json`：模板划分（锁定决策：精度策略、BUFFER_NUM、多阶段 UB 方案）。
- `tiling_current_template.json`：当前模板的已完成段（本模板 split 之前段）。
- 当前模板已在 prompt 提供（「## 当前模板」段，你只处理这一个）。
- 算子身份已在 prompt 提供（「## 算子」段）。

> 不读其它模板或其它设计步骤写出的中间文件。
## 输出（用 Bash（`cat`）写到当前工作目录）

| 产物 | 必需 | required_keys | schema |
|---|---|---|---|
| `tiling_split.json` | 是 | `template, split` | `schema/tiling_split.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |

> 契约的机器校验来源：`schema/tiling_split.json`（JSON，含 required_keys + example）。
> 产出不符合 schema → DevKit 适配层拒绝，重试。
## 核心规则

- R1: 32B 对齐（所有 Vector 计算和 DataCopy）
- R2: 核间优先切独立轴，避免规约轴
- R3: 核利用率 ≥ 50%，负载均衡 ≥ 85%。均衡度按**元素口径**精确衡算（不是简单 unit 比）；
  round-robin 余数分配的闭式公式、含尾 unit 不齐时的精确 balance 公式与判定，见
  `ascendc-op-design-shared/references/load-balance-formula.md`（**先查再推，禁止从零重推**）
- R4: 每个数值必须有命名来源，禁止裸数字
- R5: **TilingData 字段设计原则——Host 侧预计算，Kernel 侧零除法**
  Kernel 在主处理循环内不应执行整除（/）或取模（%）操作来推算循环边界。
  凡是 Kernel 运行时能从 TilingData 直接读取的边界参数，均应由 Host 侧 Tiling
  函数预先计算并存入 TilingData。典型字段模式：
    - `{coreName}LoopTimes`：该类核的循环次数，= ceil(rowsPerCore / baseRows)
    - `{coreName}TailRows`：该类核最后一次循环的实际行数，= rowsPerCore - (loopTimes-1) * baseRows
  通常至少覆盖"主核"和"尾核"两类，当两者参数不同时必须分开存储。
- R6: **TilingData 字段——混合精度场景记录 dtype 字节数**
  若算子有输入张量的数据类型为多态（如支持 FP16/BF16/FP32 的输入），
  且该输入参与 Buffer 大小计算，则 TilingData 中必须包含对应的
  `{tensorName}DtypeSize` 字段（单位：字节），由 Host 侧从 dtype 枚举推导。
  禁止在 Buffer 分配公式中硬编码单一 dtype 的字节数。
## 与上游的一致性约束

> 下列上游内容均来自本次对话已提供的结构化产物（概设 / 模板划分），不读 `.md` 中间文件。

- 核间切分必须与概设产物的「并行分解策略」中的多核切分轴优先级一致
- 循环结构框架必须遵循概设产物的「各模板循环结构」给出的嵌套结构
- Tiling 级数（Core-level / UB-level）必须与概设产物的「Tiling 级数与切分策略」一致
- 与模板划分产物中的锁定决策（精度策略、BUFFER_NUM、多阶段 UB 方案）无矛盾

发现不一致时（只记录/标注，不自行回退）：
- 如果是概设遗漏（概设未覆盖当前模板的特定场景）→ 按本 skill 推导执行，并在结论中标注差异
- 如果是设计演进（推导中发现概设策略可优化）→ AskUserQuestion 确认是否更新概设
- 如果是矛盾（推导证明概设轴优先级不可行）→ 在产物结论中明确标注矛盾，告知用户

## 执行步骤

> **不校验上游完成状态**：直接消费已提供的模板划分 / 概设产物即可。**不去找 checkpoint 判断
> 上游"完成没"**——跨步骤搜寻"本应存在"的中间文件正是要铲除的死循环病根。

1. 从已提供的产物提取当前模板相关信息：
   - 从概设产物提取 **「并行分解策略」的轴优先级** 和 **「各模板循环结构」的循环框架**作为推导约束
   - 从模板划分产物读取本模板范围、锁定决策（精度策略、BUFFER_NUM、多阶段 UB 方案）
   - 目标平台 / 精度偏好来自「## 算子」段，用于后续 hardware skill 查询与精度推导
   - 概设轴优先级 > template-division 的切分相关描述（如有矛盾，以概设为基准并 AskUserQuestion）
2. 核间切分设计：
   - 基于概设给出的轴优先级，确认当前模板的可切分轴集合
    - 枚举切分方案并对比（核利用率、负载均衡）。均衡度直接用
      `ascendc-op-design-shared/references/load-balance-formula.md` 的闭式（§2/§3）算，
      **禁止无公式地凭估 + 多轮脚本反推**
    - AskUserQuestion 确认最优方案
    - 推导 blockIdx 映射公式
    - 覆盖完整性验证
   - block_dim / blockIdx 公式**禁止读 hw_params 核数字段**（`ai_core_cnt`/`cube_core_cnt`/`vector_core_cnt`）的字面值——核数须运行时取（`GetCoreNumAiv()` 等），`block_dim = min(运行时核数, ⌈totalLength/tileLength⌉)`。代际内 SKU 跨档（A5: 8/28/32/36；A2/A3: 20/24），design target 是代际级而非 SKU 级，任何静态核数换 SKU 必失效（P1）。hw_params 的核数仅供性能预估，非分核约束。A5 动态核数适配细节见 `ascendc-op-design-shared/references/platform_diff.md`
3. 核内切分设计：
   - 根据概设「Tiling 级数与切分策略」节的 Tiling 级数确定核内切分轴和优先级
   - 识别常驻数据（定量验证可行性）。常驻数据的 UB 占用因平台架构不同（Membase vs Regbase），详见 `ascendc-op-design-shared/references/platform_diff.md`
   - 推导 ubFactor / baseRows（推荐方法：枚举验证法）：

     **方法**：以 F（每次循环处理的行数）为自由变量，
     逐一列出所有 Buffer 的字节表达式（含 32B 对齐），
     求满足 `Σ bytes(F) ≤ UB_SIZE` 的最大整数 F。

     **步骤**：
     1. 列举所有 Buffer（TQue × BUFFER_NUM + TBuf × 1 + API 临时 Buffer）
     2. 每个 Buffer 给出精确字节表达式：`AlignUp(elemCount(F) × dtype_bytes, 32)`
     3. 列出约束：`Σ bytes(F) ≤ UB_SIZE`，化简为关于 F 的不等式
     4. 对 F 求最大整数解（可符号化简，也可直接代入验证）
     5. 用至少一个典型 shape 代入数值，验证 UB 不溢出

     **常见遗漏项**（每个必须逐一检查是否适用）：
     - `ReduceSum` 等规约 API 使用的内部临时 Buffer（通常为 256B~2KB，查 API 文档）
     - **reduce 轴补零 buffer**：若 reduce 最内层轴元素数 `D` 非 32B 对齐（`D × sizeof(T) % 32 != 0`），CopyIn buffer 元素数须取 `AlignUp(D, 32/sizeof(T))`（补零在 DataCopyPad 搬运时由 GM 端自然完成）。详见 `ascendc-op-design-shared/references/reduce_align_strategy.md`。
     - `BroadCast` 等广播 API 的临时 Buffer（同上）
     - 多 dtype 输入的对齐差异（FP32 对齐到 8 元素，FP16 对齐到 16 元素）

   - 数值代入验证
   - 确定循环嵌套结构（填入概设「各模板循环结构」节框架的具体循环次数）
   - 数据复用层级分析
4. 输出自检：
   - [ ] ubFactor 推导包含所有 TQue/TBuf/临时 API Buffer 的精确字节表达式（枚举验证法）
   - [ ] 每个 Buffer 的字节表达式含显式 AlignUp(x, 32) 调用
   - [ ] 典型 shape 下数值验证通过（UB 占用 ≤ UB_SIZE）
   - [ ] 所有数值有命名来源（非裸数字）
   - [ ] 核利用率 ≥ 50%，负载均衡 ≥ 85%
   - [ ] 32B 对齐约束满足
   - [ ] 核间切分方案与概设「并行分解策略」节轴优先级一致（如有差异已 AskUserQuestion 确认）
   - [ ] block_dim/blockIdx 公式来源是运行时核数 API（`GetCoreNumAiv()` 等），**非 hw_params 核数字段字面值**（P1：代际内 SKU 跨档，静态核数换 SKU 必失效）；`source_pointer` 不得指向 `hw_params.ai_core_cnt` 等核数字段
   - [ ] TilingData 字段包含 loopTimes / tailRows 类预计算字段（R5）
   - [ ] 分核方案与 loop 字段一致性（R5，举证制）：已判定"是否存在两类及以上行数不同的核"。若存在（ceil+尾核 / 余数前置+1 等）→ loopTimes/tailRows 必须按分组分别命名存储（per*/last* 或 main*/tail*）；单组字段仅当所有核行数完全相同时允许。结论落到 verifiable_claims（claim_type=numeric_derivation）
   - [ ] 多态 dtype 输入的 dtypeSize 字段已包含在 TilingData 中（R6，若适用）
   - 自检失败 → 就地修正直到通过
   - 自检通过后，用 Bash（`cat`）把单模板切分的结构化产物写到当前工作目录（字段以本 skill「## 输出」段声明的 required_keys 为准，含切分方案、ubFactor 推导、循环结构）。
   - `verifiable_claims` / `key_parameters`：放进 **`split` 段对象内层**（即 `split.verifiable_claims` / `split.key_parameters`），**不要**作为顶层兄弟字段。schema 已闭合（`allowed_top_level_keys`），顶层只允许 `template/split/step/status/decisions/external_verification/self_check_summary`（纯簿记 + 过程元数据）；gate-relevant 设计内容放顶层会在 DevKit 适配层被拒（重试）。`verifiable_claims`：分核行数分组结论、ubFactor 推导等记入 `split.verifiable_claims`（claim_type 多为 `numeric_derivation`，verification 多为 `derived`）。**产出方即查证（P82 step-58）**：推导结论须在 `evidence.attempt_log` 写清可复算推导链（前提→结论），前提指向已查证源；仅设计推断、未对照任何源时不得直接标 `UNVERIFIED`——先查证（查到 `derived`，查不到才 `UNVERIFIED` 必填 `evidence.why_unverifiable`）。

## 知识引用策略

通用知识引用策略（三层优先级 + 禁止猜测 + AskUserQuestion 兜底）详见 `ascendc-op-design-shared/references/knowledge_policy.md`。

**类目特定套路**：命中已知类目（按**结构判据**，不认算子名）时先查共享类目参考
`ascendc-op-design-shared/references/tiling-patterns/index.md` 路由到对应 `<类目>/patterns.md`
的场景分支树与切分/UB 预算公式（规约/排序/逐元素/广播/布局转换），再代入本 skill
的核间/核内切分推导。

平台差异化参考（A3 vs A5）详见 `ascendc-op-design-shared/references/platform_diff.md`。

**模板族参数公式（SoftmaxFamily 跨步列块 / 非尾轴归一族，命中即查再推）**：softmax(dim=1) 融合
算子 route 为跨步列块（`rDim>1`）时，N 整轴驻留 + colTileElem/cap/均衡的**已验证封闭公式与
真值表**见 `ascendc-op-design-shared/references/online-softmax-strided-columnblock.md`——先查再推，
禁止从零重推同族参数。

本 skill 特有的查询场景：

| 层级 | 查询场景 | 对应执行步骤 |
|------|---------|-------------|
| Tier 1 | UB 大小、核数、向量宽度、对齐要求、A5 寄存器约束（32 RegTensor/8 MaskReg） | 步骤 2（核间切分）、步骤 3（ubFactor） |
| Tier 2 | ubFactor 推导模式、Tiling 策略选择、数据复用层级原则 | 步骤 3（核内切分） |
| Tier 3 | 对齐规则、dtype 限制、轴合并的格式限制 | 步骤 3（循环结构） |

**查询约束**：
- 含 gather/scatter/reduce 等骨架级 API 时，遵守 `knowledge_policy.md` 的"骨架级 API 强制查证门"（"命名来源、禁止裸数字"见核心规则 R4）

## 约束

- 只推导当前模板，不修改其他模板文件
- 推导中遇到需要用户决策的点，直接 AskUserQuestion
- 发现注入的 `general_design` 中的轴优先级不可行时，在产物结论标注并告知用户
- 发现注入的 `template_division` 中的锁定决策不可行时，在产物结论标注并告知用户
