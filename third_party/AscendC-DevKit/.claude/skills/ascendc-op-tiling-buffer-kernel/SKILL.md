---
name: ascendc-op-tiling-buffer-kernel
description: 对单个算子计算模板执行 Buffer 设计 + Kernel 伪代码
triggers:
  - tiling-buffer-kernel
  - Buffer 设计
  - Kernel 伪代码
---

# AscendC 算子 Buffer / Kernel 设计

## 职责

对单个算子计算模板执行 Buffer 设计 + Kernel 伪代码生成。

**职责边界**：本 skill 的输入依赖 `ascendc-op-tiling-split` 的输出（切分方案、ubFactor）。Buffer 分配和 Kernel 伪代码都是"构造型"工作——切分方案确定后，Buffer 的 TQue/TBuf 分配和 Kernel 函数拆分是机械式填充，不涉及新的切分决策。**A5 Regbase 下，VF 编排（VF 数/依赖/模式 + per-VF 函数接口）由上游 `ascendc-op-tiling-vf-design` 决定，本 skill 消费其结论做寄存器级定量核算，不重新划分 VF。**

## 输入

从当前工作目录读取上游产物文件：

- `general_design.json`：概设产物（Buffer 可行性共存约束）。
- `template_division.json`：模板划分（锁定决策）。
- `tiling_current_template.json`：本模板已完成段（含 split 的切分方案/ubFactor/循环结构/常驻数据清单；**A5 下还含 `vf_design` 段——VF 编排既定前提，见步骤 3**）。
- 当前模板已在 prompt 提供（「## 当前模板」段）。
- 算子身份已在 prompt 提供（「## 算子」段）。

> 不读其它模板或其它设计步骤写出的中间文件。
## 输出（用 Bash（`cat`）写到当前工作目录）

| 产物 | 必需 | required_keys | schema |
|---|---|---|---|
| `tiling_buffer_kernel.json` | 是 | `template, buffer_kernel` | `schema/tiling_buffer_kernel.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |

> 契约的机器校验来源：`schema/tiling_buffer_kernel.json`（JSON，含 required_keys + example）。
> 产出不符合 schema → DevKit 适配层拒绝，重试。
## 核心规则

- R0: **硬件参数锁定**。所有硬件容量/带宽/寄存器参数必须从 `ascendc-op-design-shared/references/platform_diff.md` 的硬件参数真值表取值，禁止凭记忆推算或使用裸数字。
  当产物中需要填写 hardware_api_capability 字段时，直接引用该表对应平台的值。
  32B 对齐步长：32B（全平台统一）。
- R1: 32B 对齐（所有 Vector 计算和 DataCopy）
- R2: TQue 用于流水线数据（×BUFFER_NUM），TBuf 用于常驻数据（×1）。A5 Regbase 差异详见 `ascendc-op-design-shared/references/platform_diff.md`
- R3: Cast 时机 = CopyIn 后立即升精度，CopyOut 前降精度。**升精度只对浮点算术累加有意义；整数不升精度（int→FP 丢精度禁止）；非计算算子默认 native dtype**（详见 precision-perf R1）。原语强制更宽类型须 vector `Cast` + 验往返。A5 下 Cast 时机更灵活，详见 `ascendc-op-design-shared/references/platform_diff.md`
- R4: Kernel 函数职责单一（Init/CopyIn/Compute/CopyOut 分离）
- R5: 每个数值必须有命名来源，禁止裸数字
- R6: **循环不变量提取**
  在生成 Kernel 伪代码前，检查主处理循环中是否存在循环不变量
  （每次迭代结果相同但被重复计算的量）。发现后必须提取到循环外作为
  `Init()` 末尾或 `Process()` 开头的一次性预计算。
  常见循环不变量类型：
    - 地址偏移索引（如 Gather/Scatter 的坐标矩阵，用 `Arange + BroadCast` 生成）
    - 常数掩码（如"前 K 列为 1，其余为 0"的 mask 矩阵）
    - 从 TilingData 派生的固定标量（如固定缩放系数的倒数等）
- R7: **Cast 时机与方向必须显式标注**
  Buffer 分配表中，若某 Buffer 涉及精度转换（升精度或降精度），
  必须在"说明"列标注：`Cast from <src_dtype> at <时机>` 或
  `Cast to <dst_dtype> at <时机>`。
  时机候选值：`CopyIn 后立即`、`Compute 末尾`、`CopyOut 前`。
  禁止在 Buffer 表或伪代码中使用隐含精度假设（如将 TQue Buffer
  同时标注为 FP16 和 FP32 但不说明转换时机）。
  **Buffer/workspace 元素 dtype 须与 precision-perf `compute_dtype` 决策一致**；
  非计算算子按 R3 用 native dtype，不得借 workspace 名义引入 intermediate 中转。
- R8: **stride 搬运行距一致性 + 批量搬运优先**：凡 strided `DataCopyPad`（`blockCount>1` 或含
  `srcStride`/`dstStride`）且存在尾块/非 32B 对齐行，必须满足不变式
  **「搬运行距 == 寻址行距」**——kernel 用行索引×行步长寻址读入的行，行距必须与
  `DataCopyPad` 在 UB 侧的实际排布一致。触发条件、机制与代码模板见
  `ascendc-op-design-shared/references/datacopy-stride-consistency.md`。
  **批量优先**：行距均匀的行块（主块、行分块尾块、整 tile）在伪代码中必须表达为
  **单条批量**（`blockCount=rows` 或行尾块 `blockCount=curRows` + 显式 `srcStride`/`dstStride`
  ——行分块尾块的 GM 布局与主块同构，仅 blockCount 数值变小，仍恒单条指令，
  逐行 `for`+`blockCount=1` 仅限**列分块尾块**（同一行切成
  多个列块、块间 GM 不连续且块宽互异）——逐行微事务是行级搬运的性能红线。
## 与上游的一致性约束

> 下列上游内容均来自本次对话已提供的结构化产物（本模板切分 / 概设 / 模板划分），不读 `.md` 中间文件。

- Buffer 分配必须基于本模板切分产物中的 ubFactor 和循环结构
- TQue/TBuf 分配必须遵循概设产物「Buffer 可行性评估」中的共存约束清单（定性判断）
- BUFFER_NUM 必须与模板划分产物中的锁定决策一致
- Kernel 伪代码中的循环嵌套结构必须与切分产物的循环结构一致
- **轴参算子双路径伪代码（强制）**：若上游标记为轴参算子（含 `axis_param_design`），本 skill **必须为 `route_condition` 声明的每个 dim 路径产出独立的 Kernel 伪代码**——fast_path（dim=末轴：连续 DataCopy 搬 x0/x1 + VF 计算）与 generalized（dim≠末轴：按 axis 描述符 strided DataCopyPad 搬 x0/x1，blockCount/blockLen/srcStride 取自概设 `axis_param_design.generalization` 的描述符规格 + VF 计算）。两路径各自走完整的 Buffer 设计（对齐 AlignUp(,32)、TQue/TBuf、BUFFER_NUM）+ R6 循环不变量提取 + R7 Cast 时机 + TilingData 字段对应，记入 `kernel_structure.paths.{fast_path, generalized}` 与 `kernel_pseudo_code`。VF 计算（轴无关）与 CopyOut 两路径共享。**严禁只产末轴伪代码、把 dim≠末轴 推给"上游承载 / codegen 责任"**——那是已废弃的降级规则，会导致 codegen 无蓝图可译、凭规格自由发挥拼 strided CopyIn，引发 host tiling 执行失败（EZ1008）。
- **物理层展开边界（留白纪律）**：本 skill 产物允许把部分实现细节留给 codegen，但留白必须满足以下二选一，否则不得留白：
  1. **点名载体**——被留白的物理推导若可由产物字段承载，必须已写进对应字段（GM 布局/偏移/stride/地址恒等式 → `workspace.layout_contract`；轴参寻址 → 上游 `axis_param_design`），不得只存在于推导过程而未交付；
  2. **同构测试**——无载体字段的留白必须与既有伪代码**同构**（仅变量重命名/循环重排级对应）。凡引入下列任一**新物理层**的推导，不得以「同构扩展」「属 codegen」留白，必须展开为结构化字段：
     - **新 GM 布局**：workspace 内平面划分、跨核可见区域布局、slot 复用；
     - **新跨界契约**：host tiling 公式 ↔ kernel 寻址公式对、字段 ↔ 地址恒等式、发布/汇聚操作的地址恒等式；
     - **新同步边界**：跨核 SyncAll 相位、跨管 flag 依赖、生产者-消费者次序。
  判据用留白**内容性质**（是否引入新物理层），不用「是否类似既有结构」的印象判断——两阶段方案若引入跨核可见布局或发布/汇聚恒等式，即属新物理层，必须展开。

发现不一致时 AskUserQuestion 确认。

## 执行步骤

> **不校验上游完成状态**：直接消费已提供的本模板切分 / 模板划分 / 概设产物即可。**不去找
> checkpoint 判断上游"完成没"**——跨步骤搜寻"本应存在"的中间文件正是要铲除的死循环病根。

1. 从本模板切分产物提取切分方案、ubFactor、循环嵌套结构、常驻数据清单；
   **A5 下**：从 `tiling_current_template.json` 的 `vf_design` 段提取 VF 编排既定前提（VF 数/依赖/模式 + per-VF 函数接口 `vfs[]`），供步骤 3 的 Compute 表达使用（不重新划分 VF）
2. Buffer 设计：
   - 端到端数据流追踪
   - TQue/TBuf 分配（基于复用层级，参考概设产物「Buffer 可行性评估」的共存约束）
   - **Buffer 大小建模规范**：Buffer 分配表必须包含以下三列：

     | Buffer 名 | 逻辑元素数表达式 | 对齐后字节数表达式 |
     其中"对齐后字节数"列固定使用 `AlignUp(elemCount × dtype_bytes, 32)` 形式，
     不得直接写 `elemCount × dtype_bytes`（除非已证明必然对齐）。
     混合 dtype 场景（如 FP16 输入 + FP32 中间结果）中，两种 dtype 对应
     不同的 AlignUp 粒度，必须分开建模，不得合并简化。
     - **reduce 轴补零 buffer 建模**（仅当算子含 `ReduceSum`/`ReduceMax` 且 reduce 最内层轴非 32B 对齐时）：CopyIn buffer 逻辑元素数取实际值 `D`、对齐后字节数取 `AlignUp(AlignUp(D, 32/sizeof(T)) × sizeof(T), 32)`；reduce 内部临时 buffer（sharedTmpBuf）单独列行，字节数取 `GetReduceXxxMaxMinTmpSize` 查询值（禁止写死常量）。补零范式与精度影响见 `ascendc-op-design-shared/references/reduce_align_strategy.md`（A5 Regbase 不适用）

   - ubFactor 公式最终确认
   - 对齐验证。A5 Regbase 下 Buffer 分配的差异见 `ascendc-op-design-shared/references/platform_diff.md`
   - **GM workspace 预算（当 kernel 用 GM workspace 时）**：跨核 reduce / UB 不够暂存 / SyncAll-as-GM 等场景需在 GM 上开 workspace。计算**用户 workspace** 字节数（如跨核 reduce：`sCoreNum × W × dAlignF32 × sizeof(float)`——此处 reduce 做累加，FP32 workspace 合理；非计算算子按 R3 用 native dtype，勿照搬此 FP32 范式），记入产物 `buffer_kernel.workspace = {user_workspace_bytes, rationale, layout_contract}`。**layout_contract（布局契约，数组形态沿用 `axis_param_design.tiling_data_extensions` 表达）**：每条字符串形如 `name: expr`（字节/偏移公式）或 `lhs === rhs`（地址恒等式），记录一个跨界事实——平面/区域的字节公式与 stride、跨核寻址的 base 偏移公式、发布/汇聚操作的地址恒等式、slot 复用关系；**workspace 在位 ⇒ layout_contract 非空**（布局平凡=单一连续 scratch 时给一条字节公式即可——公式本身就是 host↔kernel 跨界契约；缺字段或空数组视为未交付，须补全后重交）。**边界**：此处只算**用户 workspace**；**系统 workspace（`GetLibApiWorkSpaceSize()`，平台/CANN 版本相关）由 codegen 在 host tiling 函数末尾加，不在设计产物体现**（非设计期可定）。不用 GM workspace 则省略该字段。参考知识库 `如何使用workspace.md` + `GetLibApiWorkSpaceSize.md`。
3. Kernel 伪代码：
   - **循环不变量提取（R6）**：生成伪代码前，检查主处理循环中是否存在每轮迭代结果相同的预计算量；发现后提取到 `Init()` 末尾或 `Process()` 开头
   - Init/CopyIn/Compute/CopyOut 函数拆分，每函数 ≤ 30 行
   - 确保 TilingData 字段和 Buffer 在伪代码中有对应使用
   - **reduce 非对齐搬运**（仅当含 `ReduceSum`/`ReduceMax` 且最内层轴非 32B 对齐时）：CopyIn/CopyOut 用 `DataCopyPad`（非 DataCopy），reduce `srcShape` 传对齐后元素数，参考 `ascendc-op-design-shared/references/reduce_align_strategy.md` 
   - **多核写同一 GM 地址的累加**（跨核 reduce / segment scatter-add，输出 dtype 不在 `SetAtomicAdd` 支持列表时，如 int64）：`SetAtomicAdd` 不可用，须改走 per-core workspace + reduce kernel 两阶段方案，不得只写注释。方案结构见 `ascendc-op-design-shared/references/atomicadd_dtype_fallback.md`（查证 `SetAtomicAdd.md` 发现 dtype 缺口时触发）
   - **数值稳定性改写**（当算子公式/golden 含 `1 + tanh(...)` 结构（GELU tanh 近似等）或 `tanh原语` 时）：用多项式展开形式（exp/sigmoid 等价）替代 `Tanh` 原语，避免 catastrophic cancellation。机制与代码模板见 `ascendc-op-design-shared/references/numerical-stability-guide.md`。
    - **stride 行距一致性 + 批量优先**（凡 strided `DataCopyPad` 时）：满足「搬运行距 == 寻址行距」，尾块分支与主块共用 `rowStrideElems_`（默认方案一）或各自对称寻址（方案二）；行距均匀的行块（主块、行分块尾块、整 tile）伪代码必须写**单条批量**（`blockCount=rows`/行尾块 `curRows` + 显式 stride），逐行 `for`+`blockCount=1` 仅限**列分块尾块**。触发条件/机制/模板见 `ascendc-op-design-shared/references/datacopy-stride-consistency.md`（R8）
   - **A5 Regbase：消费 vf-design 既定前提**。若 `tiling_current_template.json` 含 `vf_design` 段（A5），其 VF 数量/依赖/编排模式与 per-VF 函数接口为**既定前提**（由上游 `ascendc-op-tiling-vf-design` 决定），本步骤**不重新划分 VF**——直接按 `vf_design.vfs[]` 的 `function_signature` / `interface_params`，把 Compute 表达为对各 VF 的 `VF_CALL` 调用序列（调用顺序遵循 `vf_design.data_flow`），并把 per-VF 的 `pseudocode` 落进 Kernel。寄存器级定量（RegTensor ≤32、MaskReg ≤8、MicroAPI 910D 查证、Cast 布局红线）在本步骤完成并记入 `verifiable_claims`。**A3（无 vf_design）维持现状**：Compute 为常规 Vector 伪代码，不涉及 VF_CALL。A5 差异详见 `ascendc-op-design-shared/references/platform_diff.md`
   - **反向传播公式自验证（当算子含 normalization / softmax / sigmoid-norm 等归一化层时）**：

     生成归一化层的梯度公式后，执行以下两项检查，任一失败则修正后重新生成：

     **检查 A：减法项独立性**
     归一化层梯度公式中，若存在从上游梯度导出的"修正项"（通常在减法右侧），
     检查该项是否是**与当前输出位置无关的标量**。
     判断方式：令修正项 = X，检查 X 对不同的位置下标 p 是否取同一值。
     若 X 仍含位置下标 p → 公式有误，重新从链式法则推导。

     **检查 B：公式与伪代码语义一致**
     若文档中同时存在公式（LaTeX）和伪代码（Kernel 计算步骤），
     逐步验证伪代码实现是否与公式等价：
     - 公式中的求和项 → 对应伪代码中的 ReduceSum / InnerProduct
     - 公式中的标量除法 → 对应伪代码中的 Divs / Muls(1/x)
     - 公式中的逐元素操作 → 对应伪代码中的 Adds / Muls（带广播）
     若发现公式与伪代码不一致，以**数学推导（链式法则）**为准修正公式。
4. 输出自检：
   - [ ] Buffer 表与 Kernel 伪代码一致
   - [ ] TilingData 字段在伪代码中有对应使用
   - [ ] TQue/TBuf 分配基于复用层级，合理解释
   - [ ] 对齐验证通过
   - [ ] 若 kernel 用 GM workspace（跨核 reduce / UB 不够暂存等），`buffer_kernel.workspace.user_workspace_bytes` 已推导且 >0；不用则省略（系统 workspace `GetLibApiWorkSpaceSize()` 由 codegen 加，不在设计产物）
   - [ ] 循环不变量已主动排查（R6，举证制）：对 gather/scatter/reduce 类算子，已**先假设向量化路径可用**，列出其偏移矩阵/掩码等循环不变量，再逐条说明"提取"或"经查证排除"。禁止以"idx 为运行期数据"为由直接判定"无循环不变量"（偏移矩阵的行基址等差数列与 idx 无关，恒可预计算）。**排除成立的点（确实无向量化等价物、须走标量数据通路的 gather/scatter 访问）进入产物 `buffer_kernel.scalar_access_points[]`**：每条 `{name, location_semantic, reason, derivation, verification}`（derivation = R6 排除论证摘要，verification 对齐 verifiable_claims 的取值），供 integrate 汇总进 `tiling_strategy.scalar_access_points[]`；全部向量化、无排除成立的点则省略该字段
   - [ ] 骨架级断言红队复核（A3-轻）：对每条骨架级 API 选型（gather/scatter/reduce 等），已回答"假设我的排除判断是错的，设计会如何变？我凭什么排除？出处是？"；**任何依赖向量 API 操作数偏移/移位寻址的 claim**（移位扫描/交错/滑窗等，不限 gather/scatter/reduce），已按 `checkpoint_convention.md` A2「操作数寻址断言」逐步长算过字节对齐（`step × sizeof(T)` vs API 文档操作数对齐条款），违约步长已给对齐安全变形或改选路径；结论落到 verifiable_claims
   - [ ] Cast 时机已在 Buffer 表中显式标注（R7）
   - [ ] Buffer 分配表包含"对齐后字节数"列，使用 AlignUp(x,32) 形式
   - [ ] hardware_api_capability 字段每个数值**有命名来源、非凭记忆裸数字**（指向 `platform_diff.md` 真值表 / `ascendc-dev-knowledge` 锚点）。**selfcheck 边界（P82 step-58）**：此处只判"有出处、非裸数"，**不判数值对错**——数值是否与真值表一致归 `verifiable_claims.verification`（产出方即查证的职责），不在此自检（selfcheck 不越界判查证充分性）
   - [ ] 若含归一化层梯度，已执行公式自验证（检查 A + 检查 B）
   - [ ] **轴参算子路径覆盖度**：若为轴参算子，`route_condition` 声明的每个 dim 路径（fast_path + generalized）是否都有独立、带代码块的 kernel 伪代码（记入 `kernel_structure.paths` + `kernel_pseudo_code`）？generalized 路径的 strided 搬运是否用了 axis 描述符字段（blockCount/blockLen/srcStride）且经 Buffer 对齐校验？只产出末轴伪代码 = 自检失败。非轴参算子跳过此项。
   - [ ] **stride 行距一致性 + 批量优先（R8）**：凡 strided `DataCopyPad` 含尾块/非 32B 对齐行，是否显式写了尾块分支且满足「搬运行距 == 寻址行距」？CopyIn 尾块与 CopyOut 尾块是否共用同一 `rowStrideElems_`（方案一）或各自对称寻址（方案二）？是否满足 `AlignUp(尾宽×s,32) == AlignUp(主宽×s,32)` 的天然一致或显式分支？行块搬运（主块、行分块尾块、整 tile）伪代码是否为单条批量（`blockCount=rows`/行尾块 `curRows`），无逐行 `for`+`blockCount=1`（列分块尾块除外）？结论落到 verifiable_claims
   - [ ] **A5（有 vf_design）**：Compute 已按 `vf_design.vfs[]` 接口表达为 `VF_CALL` 调用序列、未重新划分 VF；**A3（无 vf_design）**：Compute 维持常规 Vector 伪代码、无 VF_CALL
   - 自检失败 → 就地修正直到通过
   - 自检通过后，用 Bash（`cat`）把单模板 Buffer/Kernel 的结构化产物写到当前工作目录（字段以本 skill「## 输出」段声明的 required_keys 为准，含 Buffer 分配方案、Kernel 结构）。
   - `verifiable_claims` / `key_parameters` / `kernel_structure`：放进 **`buffer_kernel` 段对象内层**（即 `buffer_kernel.verifiable_claims` 等），**不要**作为顶层兄弟字段。schema 已闭合（`allowed_top_level_keys`），顶层只允许 `template/buffer_kernel/step/status/decisions/external_verification/self_check_summary`（纯簿记 + 过程元数据）；gate-relevant 设计内容放顶层会在 DevKit 适配层被拒（重试）。`verifiable_claims`：将 gather/scatter/reduce 等骨架级 API 选型逐条记入 `buffer_kernel.verifiable_claims`（claim / claim_type / evidence / verification / alternatives_ruled_out）。**产出方即查证（P82 step-58）**：标 `UNVERIFIED` 前**必须先查证源**（`platform_diff.md` / `ascendc-dev-knowledge` / 产品表）——查到升 `derived`（文档映射推导）或 `api_checked`，附 `evidence.source_pointer` + `attempt_log`；查不到才标 `UNVERIFIED` 并**必填 `evidence.why_unverifiable`**（查证尝试 + 卡点）。`UNVERIFIED` 是 last resort，不是默认：不得粉饰，也不得"未查证就直接标 UNVERIFIED"。

## 知识引用策略

通用知识引用策略（三层优先级 + 禁止猜测 + AskUserQuestion 兜底）详见 `ascendc-op-design-shared/references/knowledge_policy.md`。

**类目特定套路**：命中已知类目（按**结构判据**，不认算子名）时先查共享类目参考
`ascendc-op-design-shared/references/tiling-patterns/index.md` 路由到对应 `<类目>/patterns.md`
的 Buffer/UB 预算模型与算法选型（如 reduction 的 AR/ARA 全载/分载、多输出 Buffer 方程；sort 的
`sortBytesPerElem` 建模；transpose 的 `tileNA*(16*C+32)`），再落到本 skill 的 TQue/TBuf 分配与 Kernel 伪代码。

**特殊值语义必读（elementwise Max/Min 类 API 序列 / verifiable_claims 查证）**：SIMD `Max`/`Min`
（`Maxs`/`Mins`）的 NaN 语义未文档化、±0 tie 仅写明 `-0/+0→+0`（≠ golden tie 取 self），对其作
能力断言时须带锚点（`Max-43.md` / `__hmax.md` / `fmaxf.md`），不得默认与 golden 一致或借
SIMT `fmax` 的忽略-NaN 文档背书。规则见
`ascendc-op-design-shared/references/special-value-semantics-max-min.md`。

平台差异化参考（A3 vs A5）详见 `ascendc-op-design-shared/references/platform_diff.md`。

本 skill 特有的查询场景：

| 层级 | 查询场景 | 对应执行步骤 |
|------|---------|-------------|
| Tier 1 | UB 大小、A5 寄存器约束（32 RegTensor/8 MaskReg） | 步骤 2（Buffer）、步骤 3（Kernel） |
| Tier 2 | Double Buffer 规则、TQue/TBuf 分配模式 | 步骤 2（TQue/TBuf） |
| Tier 3 | 具体 API 签名与参数约束、对齐规则、dtype 限制 | 步骤 2（Buffer API）、步骤 3（Kernel 伪代码） |
| Tier 3 | GM workspace 契约（系统 vs 用户 workspace、`GetLibApiWorkSpaceSize`、host tiling `ws[0]` 须含 sysWorkspaceSize） | 步骤 2（GM workspace 预算） |

**查询约束**：
- API 使用方法必须来自 `ascendc-dev-knowledge` 的明文文档，禁止凭记忆虚构
- 含 gather/scatter/reduce 等骨架级 API 时，遵守 `knowledge_policy.md` 的"骨架级 API 强制查证门"：无条件查证，结论写入 `verifiable_claims`（"命名来源、禁止裸数字"见核心规则 R5）

## 约束

- 只推导当前模板，不修改其他模板文件
- 不做切分设计（不涉及核间/核内切分决策）
- 推导中遇到需要用户决策的点，直接 AskUserQuestion
- Kernel 伪代码中所有 Buffer 引用必须与 Buffer 分配表一致
