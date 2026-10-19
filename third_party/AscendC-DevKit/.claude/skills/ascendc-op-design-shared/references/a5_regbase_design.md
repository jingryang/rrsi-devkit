# A5 Regbase 详细设计要点

> **定位**：A5（arch35/351x，950PR/950DT）平台的详细设计**判定规则与设计要点**承载者。
> 给出"怎么判、判什么"的规则，**不复制** MicroAPI 签名细节——具体签名/参数/dtype
> 约束一律查 `ascendc-dev-knowledge` 的 `910D_knowledge_extra/` 子库。
>
> **被引用方**：概设层 `ascendc-op-general-design`（仅引「寄存器分配」节的定性可行性层 +
> 「SIMD vs SIMT 选型」节的 SIMD/SIMT 判定表）；详设层 `ascendc-op-tiling-{split,buffer-kernel,precision-perf}`
> 在涉及 A5 推导时引用本文（类比 `platform_diff.md` 的引用方式）；`ascendc-op-tiling-vf-design`
> （VF 编排选型的决策层，仅 A5+SIMD 路径，介于 tiling-split 与 tiling-buffer-kernel 之间）
> 引用「VF 函数划分策略」节的 VF-2/VF-3 作为其决策树的补充约束——本节与该 skill 的分工见
> 「VF 函数划分策略」节说明。

---

## 0. 适用条件

仅当 `target_platform ∈ {A5, arch35, 351x, 950PR, 950DT}` 时本文生效。
A3/910B 路径**忽略本文**，按 Membase 模型设计。所有规则默认带"仅 A5 路径执行"前提。

---

## 1. 数据流模型（A5 vs A3）

```
A5（Regbase）: GM → L1 → UB → Register → 计算 → Register → UB → GM
                                （中间结果驻留寄存器，不占 UB）
A3（Membase）: GM → UB → 计算（中间结果占 UB）→ UB → GM
```

**关键影响**：
- 中间结果不占 UB → UB 占用建模与 A3 不同（详见「寄存器分配」节 + tiling-split 的 ubFactor 平台分支）。
- Vector 计算必须在 **VF 函数**（`__simd_vf__` / `__simt_vf__`）内通过 **RegTensor** 完成。
- **Regbase 是架构（A5 恒成立）**，与 SIMD/SIMT 编程模型选择是**两个独立维度**——
  勿将 Regbase 等同于 SIMT（A5 常规向量计算走 SIMD，详见「SIMD vs SIMT 选型」节）。

---

## 2. VF 函数划分策略（判定规则）

> **与 `ascendc-op-tiling-vf-design` 的分工（避免两处维护同一套划分逻辑）**：
> **VF 数量与编排模式的选型决策**（即 VF-1 的"划出几个 VF、按什么顺序编排"）
> 已迁移为 `ascendc-op-tiling-vf-design` skill 的职责——该 skill 基于 golden 代码展开、
> 聚合边界切分线、变量依赖追踪，产出结构化的 1-5 号编排模式，是比本节 VF-1
> 更完整、已验证的方法论。本节保留 VF-2/VF-3 两条**详设定量层**规则，供
> `ascendc-op-tiling-vf-design`（决定能否合并相邻 VF 时）与 `ascendc-op-tiling-buffer-kernel`
> （呈现 VF_CALL 伪码时）共同引用。**VF-1 判据本身保留于此仅作历史参考**，
> 新的 VF 选型推导一律以 `ascendc-op-tiling-vf-design` 的决策树为准，不再在本节独立判定。

- **规则 VF-1（历史参考，已由 `ascendc-op-tiling-vf-design` 决策树取代）**：划分粒度三选一——
  细粒度（每 Vector 子步骤一个 VF）/ 粗粒度（每 Vector 阶段一个 VF）/
  混合（热点融合，非热点分开，原默认推荐）。**新推导请改用 `ascendc-op-tiling-vf-design`
  的「VF 数量决策」（决策 1）+「模式选择决策树」**，不再套用本条三选一。
- **规则 VF-2（控制流等价才可融合，详设定量层，跨 skill 共用）**：相同循环次数/嵌套、
  无（或相同）条件分支，方可把多个子步骤融进一个 VF。[出处：910D `VF融合优化` /
  evolution `vf_fusion_rules`]。`ascendc-op-tiling-vf-design` 在其"依赖链中是否可合并相邻 VF"
  的 AskUserQuestion 决策点引用本规则作为判定依据。
- **规则 VF-3（编译器"尽可能融合"策略下的友好编码，详设定量层）**：连续计算 API
  （非高维切分）、成员变量先提局部变量、循环不变量外提。供 `ascendc-op-tiling-buffer-kernel`
  呈现 VF_CALL 伪码时遵循。
- **典型分解参考（Softmax）**：`vf_ReduceMax → vf_SubAndExp → vf_ReduceSum → vf_MulWithRcp`
  （对应 `ascendc-op-tiling-vf-design` 的模式 4 推广，5 VF 顺序编排）。

---

## 3. Scalar 前移（判定规则）

- **规则 SC-1**：`__simd_vf__` 内**禁止 Scalar 计算**（打断 Vector 流水，停 1~2 cycle）。
- **规则 SC-2（可前移项，以参数/constexpr 传入）**：`repeatTimes`、
  `oneRepSize = VL/sizeof(T)`、scale 系数、地址偏移基址。
- **规则 SC-3（不可移出项，保留在 VF 内）**：VF 内 for 循环计数器、
  依赖 VF 计算结果的标量。[出处：a5-fa `checklist_regbase` R2]

---

## 4. 寄存器分配（判定规则 + 硬约束）

> 本节分**定性可行性层**（供概设 general-design 引用）与**定量分配层**（供详设
> buffer-kernel 引用），与概设/详设对 UB 的"能否放得下 / 怎么放"分层完全同构。

### 4.1 定性可行性层（概设级引用）

- **判据 REG-Q1**：概设只答"按驻留意图，单 VF 的活跃 RegTensor 是否**大概率** ≤ 32、
  MaskReg 是否 ≤ 8"——定性"能否放得下"，**不逐个算字节**（类比概设对 UB 的处理）。
- **判据 REG-Q2（粗估口径）**：单 VF 活跃 RegTensor ≈ 输入分量 + 输出分量 + 主要中间量
  （按驻留意图计数，UB 中转的不计）。明显超阈（如 > 32）→ 概设标"压力高，详设需拆 VF"风险点。
- **判据 REG-Q3**：概设**不做** spill/fill 决策、**不定** VF 划分粒度——这些是定量层职责。

### 4.2 定量分配层（详设级引用）

- **硬约束**（来自 910D / evolution INDEX）：
  - 每 VF ≤ **32 RegTensor**；≤ **8 MaskReg**；≤ **4 UnalignRegLoad**；≤ **4 UnalignRegStore**。
  - RegTensor 宽度 = VL = **256B**；元素数 = 256/sizeof(T)（b8=256 / b16=128 / b32=64 / b64=32）。
  - RegTraitNumTwo（2×VL）仅 b64/complex32 使用。
  - 超 32 RegTensor → 编译器插 **spill/fill + sync**，显著掉性能。
- **规则 REG-1（申请顺序）**：MaskReg → RegTensor\<dst\> → RegTensor\<src\>。
- **规则 REG-2（估算每个 VF 的 RegTensor 数）**：输入 + 输出 + 中间临时，> 32 时三选一处理：
  拆 VF / UB 中转中间结果 / 减少同时活跃 RegTensor（布尔代数化简、指令重排）。

---

## 5. SIMD vs SIMT 选型（判定规则表，概设层与详设层共同引用）

> **权威说明（2026 集成 template-select 后）**：SIMD/SIMT/MIXED 判定的**唯一运行时权威**
> 是 `ascendc-op-design-template-select` skill 的规则库（能力规则 C-01 + 方向性规则
> R-01~R-07 + 冲突仲裁 → MIXED，见该 skill 的 `references/selection_strategy.md`）。
> 下方 LP → 编程模型映射表降级为**定性参考 / 技术依据**（概设 narrative 用），不再承担
> 选型结论——结论由概设「SIMD/SIMT 编程模型判定」步骤（A5 路径）产出 `template_decision.json`
> 落定；与本表冲突时以 R 规则判定为准。

> 选型**结论**由概设层（general-design 架构设计章）依 **LP 分类**直接落定；
> 详设层（buffer-kernel）**继承**该结论、**不重新选型**。本表是双方共用的判据出处。

**LP → 编程模型映射**（核心判据）：

| LP 类型 | 语义 | 推荐 |
|--------|------|------|
| LP1 全轴独立（逐元素） | 逐元素加减乘除、矩阵逐行 | **SIMD** |
| LP3 规约轴内嵌非D / LP4 D轴规约 | Reduce / 顺序依赖 | **SIMD** |
| LP5 范围迭代（滑窗/前缀） | 窗口规约 / 前缀扫描 | **SIMD** |
| LP6 矩阵乘积 | MatMul（Cube + 向量后处理） | **SIMD**（向量后处理部分） |
| LP2 索引间接（Gather/Scatter） | 随机访问、动态索引 | **SIMT** |
| LP7 选择排序 | 条件分支密集、TopK/Sort | **SIMT** |

**按语义特征的等价判据表**：

| 算子语义特征 | 推荐 | 原因 |
|------------|------|------|
| 逐元素加减乘除、矩阵逐行 | SIMD | 规则连续，向量化效率高 |
| Reduce / Scan | SIMD | 顺序依赖，向量化处理 |
| Gather / Scatter、动态索引 | SIMT | 随机访问，线程级并行 |
| 条件分支密集、Attention mask | SIMT | 每线程独立分支 |

- **规则 ST-1**：一个 AIV 核某时刻只能 SIMD 或 SIMT，可按 **VF 粒度切换**（UB Cache 保持）。
- **规则 ST-2（SIMT 寄存器随线程数降）**：1~256→127，257~512→64，513~1024→32，1025~2048→16。
  [出处：910D `SIMD与SIMT混合` / evolution `simd_simt_hybrid`]
- **融合算子（LP8 多阶段异构）**：按各 SubOp 的 LP 性质**分别判定**（逐元素/规约 SubOp 走
  SIMD，gather/scatter/选择 SubOp 走 SIMT），可按 VF 粒度切换。

---

## 6. MicroAPI 选型（导航，不复制签名）

- 算术：Add/Adds/Mul/Muls/Sub/Div/Abs/Max/Min/Duplicate
- 比较选择：Compare(CMPMODE: LT/GT/GE/EQ/NE/LE) / Select
- 类型转换：Cast(CastTrait = RegLayout + SatMode + MaskMergeMode + RoundMode)
- 访存：LoadAlign/StoreAlign + CreateAddrReg/UpdateMask/CreateMask
- **规则 API-1**：具体签名/参数/dtype 限制一律查 `ascendc-dev-knowledge` 的
  `910D_knowledge_extra`，**禁止凭记忆虚构**（遵守 `knowledge_policy.md` 的 Tier3
  查证 + 「A5 Regbase 强制查证门」）。

---

## 7. Cast 时机（A5 更灵活）

- A3：CopyIn 后立即升精度，CopyOut 前降精度。
- A5：可在 **VF 函数内部**完成 Cast，时机更灵活（升精度后直接在寄存器计算）。
- **规则 CAST-1**：Buffer 表/伪码必须**显式标注** Cast 方向与时机。

---

## 8. A5 RegBase 编码红线（位宽变化 Cast 布局 / LoadDist 选型 / 异常值手法）

> **定位**：本节是 A5 RegBase 上**含位宽转换 / 含异常值（NaN/Inf/溢出）处理**的
> Vector 算子的**共性编码红线**。被 `tiling-buffer-kernel`（VF 伪码与布局）、
> `tiling-precision-perf`（异常值手法与精度规则）**强制引用**。规则均为**通用判定 +
> 强制查证**，具体 API 签名/dtype 支持/trait 取值一律按 `API-1` 查 910D，禁止凭记忆写死。

### 8.1 位宽变化 Cast 的寄存器布局红线（头号）

- **事实 RB-CAST-1（布局错位风险）**：在 RegBase 上，**源/目的元素位宽不同**的 Cast
  （如 b8↔b32、b8↔b16、b16↔b32、b4→b16 等）会改变单 RegTensor 内的元素打包密度，
  产物按 **交织布局（interleaved，常表述为 ZERO/ONE/TWO/THREE 等分量组）** 排布，
  **逻辑相邻的元素在物理寄存器中不再连续**。若直接把交织结果当连续序列继续算或搬出，
  会发生**数据错位（功能性错误，非精度抖动）**。
- **规则 RB-CAST-R1（必须显式还原布局）**：凡 VF 内出现**位宽变化 Cast**，伪码**必须**：
  1. 标注该 Cast 的 **layout-group / 分量组**（哪些 lane 落 ZERO/ONE/…）；
  2. 给出**布局还原步骤**——按查证结果选用 `Reg::Interleave` 类还原 API
     或带正确 **CastTrait（RegLayout 维度）** 的 Cast 变体，使后续计算/搬出回到连续序列；
  3. 不得默认"Cast 后即连续"。**缺失还原步骤的位宽 Cast = 红线违例**。
- **规则 RB-CAST-R2（窄→宽 与 宽→窄 都要查）**：升精度（窄→宽，元素数减半/分组）与
  降精度（宽→窄，元素数翻倍/合并）的布局规则**不同且都需查证**；不得用一个方向的经验套另一方向。
- **规则 RB-CAST-R3（落 verifiable_claims）**：每个位宽 Cast 的「使用的 CastTrait 取值 +
  是否需 Interleave + 还原 API 名」三项必须各自带 910D 查证出处，写入 `verifiable_claims`；
  任一项查不到出处 → 该 claim 标 **UNVERIFIED**（由 anchor-check 阻断，见门禁规则）。

### 8.2 LoadDist（搬运分发模式）选型（判定 + 强制查证）

- **事实 RB-LD-1**：RegBase 的 Load/搬运可带 **分发模式（LoadDist）**，在搬入时即完成
  去交织 / 解包 / 广播等重排，避免事后再用 Vector 指令搬数据。**选错分发模式 = 布局错位**。
- **选型导航表（语义 → 候选模式族，具体枚举名/适用 dtype 查 910D 后落定）**：

  | 数据排布需求 | 候选模式族（示意，须查证确名） | 典型场景 |
  |---|---|---|
  | 去交织 / 还原打包元素 | `DIST_DINTLV_B*`（de-interleave） | 位宽 Cast 后或交织源还原为连续 |
  | 子字节解包（如 4bit→字节） | `DIST_UNPACK4_B*` / 解包族 | FP4/INT4 等亚字节类型展开 |
  | 元素→块/分组扩展 | `DIST_E2B_B*`（element-to-block） | 每元素扩展到块、与块级标量配对 |
  | 标量/单值广播到全 lane | `DIST_BRC_B*`（broadcast） | scale/bias 等共享系数广播 |

- **规则 RB-LD-R1（禁止用 Vector 指令替代分发）**：能用 LoadDist 在搬入阶段完成的去交织/
  解包/广播，**优先用 LoadDist**，不要在 VF 内用额外 Compare/Select/搬移指令硬凑——
  后者既慢又易错位。但**具体模式名与 dtype 支持必须查 910D 确认**，不得凭表中示意名直接写死。
- **规则 RB-LD-R2（广播勿误用）**：把"逐块/逐组共享的系数"广播到元素，应选 `*BRC*` 或
  `*E2B*` 族中**查证适配**者；**不得**默认用某一固定广播 API 而不核对其 lane 语义。

### 8.3 异常值（NaN/Inf/溢出）硬件手法（供 precision-perf 引用，按输出 dtype 条件化）

- **规则 RB-EXC-R1（NaN/特殊值优先靠硬件 Cast 隐式映射）**：当"低精度输出对 NaN/Inf 的
  处理"可由 **Cast 的 SatMode / 目标 dtype 的隐式映射**完成时，**优先用硬件 Cast 语义**，
  **不要**默认用 `Compare + Select` 软件分支去识别再替换（软件分支更慢且易遗漏边界）。
  是否能隐式映射、映射成什么值，**按目标 dtype 查证**后落规则。
- **规则 RB-EXC-R2（溢出/clip 优先用溢出模式寄存器）**：饱和/溢出处理优先评估
  **`SetCtrlSpr` 类溢出模式 / Cast 的 SatMode**，而非默认 `Max + Min` 两条 Vector 指令夹逼；
  仅当查证确认无硬件饱和路径时才退化为 `Max/Min`。
- **规则 RB-EXC-R3（异常值规则必须按输出 dtype 条件化，占位不写死数值）**：精度章必须给出
  **「按输出 dtype 分支」的异常值处理规则模板**（如不同浮点输出对 NaN 是否保留 / 是否归零、
  溢出是否 clip 各不相同），以**占位 + 查证出处**形式表达，**不得**把某一具体 dtype 的
  结论当全局默认。同一算子内不同输出 dtype 的 NaN/溢出行为**必须各自单列、彼此不矛盾**。

---

## 8bis. 树形/二分累加设计要点（归一化类 mean/var 规约，A5 全载路径）

> **定位**：沿规约轴（A,R 范式的 R 轴）计算 sum/mean/var/均方和时，R 轴全载场景下的
> **累加方式设计知识**。二分累加（树形规约）相比顺序累加有两重收益：**精度**（超长 R 的
> 顺序浮点累加误差发散，二分折叠把累加深度从 O(R) 降为 O(log R)）与**并行度**（整块/尾块
> 一次并行算完再折叠）。R 轴超全载上限时走 §8ter 块级并行 Welford。被概设层
> `ascendc-op-general-design`（B01 模式 + Tiling 设计章）、详设层
> `ascendc-op-design-template-division`（模板分层判据）与
> `ascendc-op-tiling-vf-design`（vf_archetypes VF_0 接口契约）共同引用。

### 8bis.1 使能判据（host tiling 选路）

全部满足 → 走全载 + 二分累加路径；任一不满足 → 沿 R 轴切分（非二分路径）：

| # | 判据 | 说明 |
|---|------|------|
| 1 | Regbase 平台 | A5（arch35/351x）恒成立 |
| 2 | 算子类型 | 规约（norm）类算子 |
| 3 | **R_align ≤ 4·VL²** | fp32 VL=64 → R ≤ 16384。此为该算法默认支持的全载上限 |
| 4 | UB 容纳 | 扣除 x（双缓冲）、常驻参数、rstd、二分 tmp 后 `ubFactor >= 1` |

### 8bis.2 二分折叠点与四分支结构

**计算域与 VL 口径（二分全章的前提）**：mean/var 类规约**固定在 fp32 域计算**——DX 为
fp16/bf16 时在 Load 后立即 Cast↑，其后平方、配对、折叠、收尾全部是 fp32 运算。
因此**二分的分段单位 VL 恒为 64**（256B ÷ 4B），与输入 dtype 无关；fp16 一次可载
128 个元素（DIST_UNPACK_B16 物理读 256B）是**搬运口径**，不是计算分段口径——
禁止 `VL = 256/sizeof(DX)` 的 dtype 派生（那会把段与 256B chunk 错开，迫使所有
分支引入二级 chunk 循环）。分支判据与 fold_point 均按**真实规约长度 R** 计算
（num_col_align 仅用于搬运/寻址）。**若 mean/var 是输出**：折叠中间结果须先乘修正
因子（RG-B2）、Cast↓ 到输出 dtype 写 UB/GM 供输出，再继续参与后续计算（同一份
中间值两用，不重复折叠）；仅求和/均方时直接 ReduceSum 收尾，无此开销。

**折叠点**：`fold = 2^floor(log2(R − 1))`，即从 R 向下找最近的 2 的幂
（R=5000 → fold=4096）。**整数循环乘 2 实现，禁用浮点 `std::log`**（R 恰为 2 的幂时
天然折半，防尾区空转）。

**设计理念（二分的两条核心机理）**：

1. **并行**：fold_point 把行切成等长的前半（fold，fold/VL 段）与尾区（R − fold），
   尾区第 j 段与前半第 j 段**天然等长、可同寄存器配对**——尾段与折叠段平方后立即
   逐元素 Add，Add 输出直接参与本轮局部归约写 tmp[j]，尾区在同一轮循环里被"吸收"，
   无独立的后处理折叠阶段。fold_point 由此必须参与折叠循环的地址计算（配对偏移
   = fold/VL 段），而非只做分支判别。
2. **免尾块**：VF 算术/加载指令的 ZEROING 掩码语义 = **mask 外 lane 恒为 0**——
   Cast、Mul、Add 在尾掩码下自动把不足 VL 的部分补零。**尾块因此不需要任何
   专门的补零/掩码循环/独立分支**，直接以满段形态参与计算。唯一的例外是 **DataCopy
   载入**（如收尾从 tmp 读数）：DataCopy 无自动补零，此时才需 ShiftLefts(x,x,0,mask)
   显式清尾。判别口诀：**寄存器域算术 = 自动补零；UB 载入 = 需显式清尾**。

**VF 调用粒度（批形态）**：规约 VF 签名收 `xUb/sumUb/tmpUb + batchRows + numColAlign`，
**行循环在 VF 内、每 tile 只调一次**——掩码/常量寄存器等序言成本由 batchRows 行摊销，
禁止 `__aicore__` 层逐行调用 VF（调用与掩码构造开销 × 行数，窄行 B1 每行仅 4 条
指令时占比最大）。VAG 合规要领：行基址 `xRow = xUb + r*numColAlign` 是循环体外
标量运算（VAG 只约束硬件循环内 Load/Store 的地址参数），段内地址一律"派生指针 +
j*VL 常量系数"；foldPoint 等派生标量在 wrapper 一次算好传入。VAG 仍拒时的单行
fallback 详见 `regbase-vf-test` 等长段规约经验（fallback 形态节）。

**R > 2VL 后的通用折叠循环骨架**（B1/B2 一步并行完成不经过本骨架；配对相加融合在
局部归约的同一轮，tmp[j] 由配对轮直接产生；两段均满 VL 形态，末轮尾段由 ZEROING
自动补零，无任何尾块特判）：

```
tail          = R − fold                    # 尾区长度
tailLoops     = ceil(tail / VL)             # 配对轮次数
foldLoops     = fold / VL                   # 折叠点内整段总数
headWithOutAddLoops     = foldLoops − tailLoops       # 无需配对的剩余整段数
① 循环 tailLoops（配对轮，循环体恒定）：
     s0 = LoadCast(x, base + j*VL)              # 满载
     s0 = Mul(s0, s0, fullmask)                 # 平方：两操作数同寄存器
     s1 = LoadCast(x, base + (fold/VL + j)*VL)  # 满载，末轮尾 lane 自动补零
     s1 = Mul(s1, s1, fullmask)
     Add(s0, s1, fullmask) → ReduceSum → tmp[j]           # 一轮消化两段
② 循环 headWithOutAddLoops（无配对轮）：
     seg = LoadCast(x, base + (tailLoops+j)*VL)
     seg = Mul(seg, seg, fullmask)
     ReduceSum → tmp[tailLoops+j]
③ 折叠循环与收尾循环之间插一次 LocalMemBar<VEC_STORE,VEC_LOAD>（等全部写完再读）
④ 对 tmp[0..foldLoops] 收尾 → 最终标量（形状见分支表，B3 一步 / B4 两条 VL 相加）
```

> **机理对照**：① 两条 Load 独立发射、Add 消耗两条流水，一轮消化两段，累加树深
> O(R)→O(log R)；tmp 长度因此被压到 foldLoops（B3 ≤ VL、B4 ≤ 2VL），收尾 ④ 最多
> 再折一次。tmp 规模、fold_point 寻址、tmp 写读只等一次这三者是同一不变式的三个
> 投影，结构复杂度超出来（多轮折叠 / 折叠中途落盘再回读 / 循环内反复等写读）即说明
> 不变式被打破（RG-B5 自检问题）。

按 R 分四分支（**同一个 TILING_KEY、同一个 kernel 模板内实现**，运行时按 R 值分派）：

| 分支 | 条件 | 结构（形状级约束） | 收尾 |
|------|------|------|------|
| B1 | R ≤ VL | **一步**：单次 Load（末段尾掩码，ZEROING 自动补零）→ 平方 → ReduceSum。**无 chunk/尾块循环** | ReduceSum 即结果 |
| B2 | VL < R ≤ 2VL | **恰好两条 VL 段并行**：第一条满载 [0,VL)，第二条 [VL,R)（不足 64 的 lane 自动补零）→ 各自平方 → Add → 一次 ReduceSum。**两条指令对，无任何尾块特判** | Add 后一次 ReduceSum 即结果 |
| B3 | 2VL < R ≤ 2VL² | ①②折叠循环（配对偏移 = fold/VL） | fold/VL **恰 ≤ VL** → **一次 ReduceSum 吃掉 tmp[0..foldLoops]**，零循环 |
| B4 | 2VL² < R ≤ 4VL² | 同 B3 | fold/VL **恰 ≤ 2VL** → 从 tmp **DataCopy 两条 VL**（第二条 ShiftLefts 清尾——DataCopy 无自动补零）→ Add → 一次 ReduceSum。**收尾是固定二段式，禁止通用 chunk 累加循环** |

> 实现形态：B1~B4 是同一模板内的分支函数（`LessThanVL` / `LessThanTwoVL` /
> `Common<1>` / `Common<2>`），统一入口按 R 分派；B3/B4 共享同一套①②折叠循环，仅
> 收尾 ④ 不同（编译期常量 1 或 2 个 VL 特化），**不产生新的 TILING_KEY 或新模板类**。
> B3/B4 同构源于数学：分支边界（2VL²）两侧折叠循环的产出都是 foldLoops ≤ 2VL 个
> 部分和，承载规模不变，变的只是收尾一次能消化的长度。若发现两分支数据流结构趋异
> （缓冲规模、循环形态、等待点数量不同），说明承载不变式被打破，回推折叠循环设计
> （RG-B5 自检问题）。

### 8bis.3 TilingData 契约字段

| 字段 | 计算 | 用途 |
|------|------|------|
| `fold_point`（核心新增） | 8bis.2 整数法 | 分支分派 + 折叠循环配对偏移。**单一来源**：host 算好、kernel 只解包消费，禁止 kernel 侧重算或等价二次推导；传导链与寻址职责见 8bis.2 设计理念与 RG-B5 |
| `num_col_align` | R 按 32B 对齐 | 搬运行距/掩码长度 |
| `ub_factor` | UB 估算公式（须**计入二分 tmp**：`rows × ceil(fold/VL) 对齐 32B × 4B`。tmp 只承载折叠循环的部分和，收尾就地归约、不落盘中转，故 B4 也无需额外的收尾缓冲区） | 核内每次迭代处理的 A 行数 |
| `avg_factor`（如输出 mean/rms） | `1/R` | 归一化因子 |

### 8bis.4 模板形态（单一性能二分模板）

二分累加**不作为独立模板划分概念**：命中 8bis.1 判据时，规约走**单一的性能二分全载模板**，
四分支（8bis.2）是该模板 kernel 内部的运行时分派，**不按分支拆 TILING_KEY**。
R 轴全载不可行（判据不满足）时按既有非二分路径处理，不在本节展开。

### 8bis.5 红线与注意

- **规则 RG-B1（尾块补零）**：尾块不足 VL 的部分参与归约前必须保证为 0——DataCopyPad 开
  `isPad` 自动补 0，或寄存器内用 tail-mask 的 `ShiftLefts(x,x,0,mask)` 清尾；未开 isPad 且
  未清尾 = 脏数据进和，功能性错误。
- **规则 RG-B2（mean/var 修正因子）**：折叠循环内先乘 `n = 1/powerOfTwo`（向上取的 2 的幂），
  收尾后乘修正因子 `powerOfTwo/R` 还原真实均值/方差；只需求和结果时可直接 ReduceSum 收尾，
  无需修正链。
- **规则 RG-B3（双统计量复用中间结果）**：第二遍 var 计算复用第一遍写回 UB 的 `(x−mean)`
  中间结果，避免重复搬运/重复减法（两遍共享同一套折叠 scratch 布局）。
- **规则 RG-B4（跨 VEC_SCOPE 冒险）**：Σx 与 Σx² 使用**独立的两块 scratch**（或显式
  LocalMemBar），消除写后读冒险。
- **规则 RG-B5（二分折叠单遍性）**：折叠循环须维持 8bis.2 的部分和承载不变式
  （前缀和恒以 ≤ foldLoops 个"等长两段之和"存在）。设计期自检问题（逐条可判）：
  - VL 是否恒为 64（fp32 计算域口径），而非 256/sizeof(DX) 派生？
  - tmp 长度公式是 `ceil(fold/VL)` 还是 `ceil(R/VL)`？（二分设计应为前者）
  - fold_point 在折叠循环体内是否出现在地址计算中（配对偏移），还是只用于分支分派？
  - 各分支是否存在尾块/chunk 特判循环？（寄存器域 ZEROING 自动补零，B1/B2/配对轮
    均不应有；仅 B4 收尾 DataCopy 载入的第二条 VL 需 ShiftLefts 清尾）
  - B3 与 B4 的折叠循环是否同一套（B4 仅收尾多一次 VL 间相加）？
  - 规约 VF 是否批形态（行循环在 VF 内、每 tile 调用一次，掩码循环外构造一次）？
  - fold_point 是否只在 host 计算一次、kernel 仅解包消费？
  - 折叠循环与收尾循环之间是否只等一次（见下条 tmp 写读等待）？
  任一答不上或答错 → 不变式已被打破，回推折叠循环设计。
- **tmp 写读等待（RG-B1 同源）**：收尾循环读 tmp 前，须等折叠循环全部写完——插一次
  `LocalMemBar<VEC_STORE, VEC_LOAD>`（折叠循环与收尾循环之间，B3/B4 相同）。折叠循环
  内部不应有等待：出现即说明循环内反复落盘/回读 tmp，属数据流设计问题，回推结构。

### 8bis.6 自检清单增补（并入「自检清单」节使用）

- [ ] R 轴全载设计已声明累加方式（二分/顺序）；二分时 TilingData 含 `fold_point` 且 tmp 空间公式已入 UB 估算
- [ ] 折叠点用整数法计算（无浮点 log）；R 为 2 的幂时 quotient 已折半防空尾区
- [ ] 尾块补零路径明确（isPad 或 mask 清尾，RG-B1）；需 mean/var 时修正因子链完整（RG-B2）
- [ ] 模板形态为单一性能二分全载模板（8bis.4），二分四分支未拆成多个 TILING_KEY
- [ ] **RG-B5 八个自检问题全过**（§8bis.5）；VF 接口参数含 fold_point（或派生量）且逐字传导进 `__simd_vf__` 签名

---

## 8ter. 非全载流式规约：块级并行 Welford（归一化类 mean/var，A5）

> **定位**：8bis 的姊妹节，处理 8bis.1 判据不满足的另一半——**R 轴超全载上限**
> （R_align > 4·VL² 或 UB 装不下一次规约）时，mean/var 沿 R 切 tile 流式计算的设计。
> 两遍式（先 Σx/Σx² 再中心化）在大 R 下 `E[x²]−mean²` 灾难性相消，故非全载 norm
> 统一采用 **Chan 块级并行 Welford**。仅限 norm 类 mean/var 规约；求和/极值类规约
> 不适用（无相消问题，顺序/tile 内二分累加即可）。

### 8ter.1 核心机理（两条）

1. **lane 向状态（向量化载体）**：朴素 Welford 是标量串行链，无法向量化。把状态从
   2 个标量升级为 **`[parallel_n]` 个 fp32 lane 的数组**（tmpMean/tmpVar，UB 常驻），
   每条 lane 独立维护自己位置上的 Welford 链——块内 VL=64 个位置并行增量更新，
   全程零标量往返；不同 lane 的链到 finalize 才合并。块间更新（Chan 等价向量式，
   `scale = 1/count`）：

   ```
   delta1 = x − tmpMean;  tmpMean += delta1 × scale
   delta3 = x − tmpMean;  tmpVar += delta1 × delta3      # 后因子必须用更新后的 mean
   ```
   顺序红线：delta1 用旧 mean、delta3 用新 mean，两步不可换序/合并（这就是
   S_k = S_{k−1} + (x−μ_{k−1})(x−μ_k)）。首块状态清零起步，后续块增量。

2. **finalize 链合并 = 二分累加回归**：块循环结束后，每条 lane 上是 welford_loop_count
   条链的终值（各含 partial mean 与 M2），跨链合并在 fp32 域按 Chan 公式：

   ```
   mean_g   = Σ(mean_i × w_i) / N              # w_i = 链 i 的元素数
   delta_i  = mean_i − mean_g
   var      = Σ(M2_i + w_i × delta_i²) / N      # 跨链修正项
   rstd     = 1/√(var + ε)
   ```
   合并的计算组织**原样复用 8bis 二分骨架**：对链数组先配对轮（链 j ⊕ 链 j+power，
   power = host 预计算的链数向上 2 幂 `dichotomy_add_power`）再剩余整链局部归约写
   dichotomy 缓冲，最后对 UB 数组二分对折（外层 log2 轮：相邻两 VL 段 Add 回写，
   段间插一次写读等待）+ 末次 ReduceSum。**链数取代 R 成为新的规约长度**——
   8bis 的形状约束（配对轮满段免尾块、tmp 承载、单次写读等待）全部继承；
   非对齐链尾用 counts 权重数组（尾链 +1）走 Chan 加权推广。

### 8ter.2 结构选型（按 A 轴形态二选一）

| 结构 | 适用 | 组织 |
|---|---|---|
| A 行内链式 | A 轴行多、每行 R 长（LayerNorm 类：逐行独立统计） | 状态 `[tile_len]` 每行复用：行内 tile 循环 WelfordUpdate（nRec=1/++count）→ 行 finalize → 行内第二遍归一化（x 重复载入，状态/tile 参数缓存供两遍共享） |
| B 块并行流式 | A 轴行少、R 极长（GroupNorm/InstanceNorm 类：N×G 小） | 状态 `[parallel_n]`，块 ping-pong 双缓冲流入；`parallel_n` 由 UB 预算反推（`ubRemain/(xBufNum×dtype) DownAlign 32B`，cap 到 R），块尾由 ZEROING 补零 |

**核间切分红线**：B 结构下 A 轴很小（如 groups=1 时 N×G=N），**不得只按 A 轴切核**
（否则并行度塌缩为 N 核，其余空转）——group 内 R 还要跨核分段：各核算部分链、
写 workspace，SyncAll 后单核（或树形）做跨核 Chan 合并。核数 = min(coreNum, 分段
数 × A 轴)。

### 8ter.3 TilingData 契约字段

| 字段 | 含义 |
|---|---|
| `parallel_n` | 块并行宽度（lane 向状态长度，32B 对齐） |
| `welford_loop_count / tail` | R/parallel_n 的块数与尾块长 |
| `dichotomy_add_power / k / last_num` | finalize 二分参数（**对链数**取向上 2 幂/轮数/尾长，同全载 fold_point 语义） |
| `num_per_core / inner_num_per_core` | A 轴核间/核内分配 |

### 8ter.4 红线与自检

- 状态更新在 fp32 域（DX≠fp32 时块内 Load 即 Cast↑，与 8bis.2 计算域口径一致）；
- 跨 tile/跨链合并全在 fp32 域；标量汇总链（如逐 tile GetValue 回收）会成为误差源，
  状态应留在 UB 数组直到 finalize，标量域只做极浅的最终合并；
- 归一化遍复用统计遍的 tile 划分（同 tile 边界重复载入 x），不重算统计量；
- [ ] 自检：状态是 lane 向数组而非标量？delta 两步顺序正确（旧 mean 求差/新 mean 收尾）？
  finalize 是否对链数复用二分骨架（dichotomy_add_power 参与配对寻址）？B 结构是否
  有 group 内 R 跨核切分（无并行度塌缩）？同步/标量回收是 O(1) 次而非 O(tiles) 次？

---

### 9. 自检清单（供详设 buffer-kernel/precision-perf 引用；SIMD/SIMT 选型项另供概设层引用）

- [ ] **R 轴规约已声明全载（二分，8bis.6）或非全载（Welford，8ter.4）路径，对应清单全过**
- [ ] 所有 Vector 计算在 `__simd_vf__`/`__simt_vf__` 内，经 RegTensor 完成
- [ ] VF 编排（数量/依赖/模式）继承自 `ascendc-op-tiling-vf-design` 产物（`vf-design-{name}.json` + `template_{name}_vf_design.yaml`），本段未重新选型；SIMT 路径或无该产物时，按 VF-1 三选一自行判定并记依据
- [ ] VF 内无 Scalar 计算，可前移项已作参数/constexpr（SC-1/SC-2）
- [ ] 每 VF RegTensor ≤ 32、MaskReg ≤ 8（REG），超限有处理方案（REG-2）
- [ ] SIMD/SIMT 选型有判定表依据（「SIMD vs SIMT 选型」节，LP 驱动）
- [ ] MicroAPI 选型来自 910D 明文查证，写入 verifiable_claims（API-1）
- [ ] Cast 时机已标注（CAST-1）
- [ ] **每个位宽变化 Cast 已标 layout-group + 布局还原步骤（Interleave/CastTrait），三项均带 910D 出处（RB-CAST-R1/R3）**
- [ ] **去交织/解包/广播优先用 LoadDist，模式名经 910D 查证（RB-LD-R1/R2）**
- [ ] **NaN/特殊值优先靠硬件 Cast 隐式映射、溢出优先 SetCtrlSpr 溢出模式（RB-EXC-R1/R2）**
- [ ] **异常值规则按输出 dtype 分支条件化、占位带出处、彼此不矛盾（RB-EXC-R3）**

---

## 10. 素材出处（仅编写参考，非运行时知识源）

- evolution-knowledge/references/a5/INDEX.md（硬件约束）
- evolution-knowledge/references/a5/vf_programming/{simd_vf_basics,vf_fusion_rules,simd_simt_hybrid}.md
- evolution-knowledge/references/a5/regbase_api/{reg_tensor,mask_reg,load_store}.md
- a5-fa-detailed-design/references/checklist_regbase.md（R1/R2/R3 范本）
- **运行时唯一知识源**：ascendc-dev-knowledge/references/910D_knowledge_extra/（~2000 篇）
