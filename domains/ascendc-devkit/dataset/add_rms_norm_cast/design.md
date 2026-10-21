# AddRmsNormCast 内部设计文档

> 本文档记录源码内部实现分析，**不得**回写进 `desc.md` / `golden.py` / `cases.yaml` / `cases.csv`。
> 覆盖范围限定 Ascend A3（910B/910C，`__CCE_AICORE__ == 220` 路径）与 A5（950/3510，`ascend950` regbase 路径）。
> 源码基线：`/home/j00958686/ops-nn`（分支 `master`），算子目录 `norm/add_rms_norm_cast/`。

## 1. 实现概览

### 1.1 host 侧

| 阶段 | 位置 | 作用 |
|---|---|---|
| OpDef 注册 | `op_host/add_rms_norm_cast_def.cpp:19-101` | 三个必选输入 `x1/x2/gamma`（FP16/BF16）、四个必选输出 `y1(FP32)/y2/rstd(FP32)/x`、属性 `epsilon` 默认 1e-6。`ascend910b`/`ascend910_93` 挂 A2/A3 配置，`ascend950`/`ascend350`/`ascend960dt` 挂 regbase 配置并指定 `opFile.value = add_rms_norm_cast_apt`（走 `op_kernel/add_rms_norm_cast_apt.cpp`）。 |
| InferShape | `op_host/add_rms_norm_cast_infershape.cpp:28-78` | `y1/y2/x` 直接复制 `x1` shape；`rstd` 取 `x1` 的 `rank(x1)` 维，前 `rank(x1)-rank(gamma)` 维照抄、后 `rank(gamma)` 维置 1（`:67-73`）。rank 未知时置 UnknownRank。 |
| InferDataType | 同上 `:81-92` | `y1=FP32`、`y2=in0 dtype`、`rstd=FP32`、`x=in0 dtype`。 |
| Tiling 入口 | `op_host/add_rms_norm_cast_tiling.cpp:235-345` | 先做 shape 校验，再按 `IsRegbaseSocVersion(context)` 分流：regbase（950）交给 tiling 模板注册表 `TilingRegistry::DoTilingImpl`；A2/A3 走本函数内的过程式分派。 |
| TilingPrepare | 同上 `:347-365` | 缓存 `totalCoreNum = GetCoreNumAiv()`、`totalUbSize`、`socVersion` 到 `AddRmsNormCastCompileInfo`。 |

**关键分流点**：A3 与 950 走两条完全不同的代码路径，tiling key 编码体系也不同（`dtypeKey*10+modeKey` vs `100+tilingType`）。

### 1.2 device 侧数据流

两条路径的计算步骤本质相同，都是「一次搬入 → 求和 → 求 rstd → 复算乘 rstd 与 gamma → 三路搬出」：

```
x1,x2 ──MTE2──> UB ──V: Add──> x ──MTE3──> xOut
                     └─ Cast→FP32 ──V: Mul/Muls(avgFactor) → ReduceSum
                          └─ V: Add(eps) → Sqrt → Div(1) ─> rstd ──MTE3──> rstdOut
                     x(FP32) × rstd ─[×gamma]─> y1(FP32) ──MTE3──> y1Out
                                          └─ Cast→输入dtype─> y2 ──MTE3──> y2Out
```

A3 实现在 FP16 分支上把 `x*rstd` 先 `Cast` 到 FP16 再乘 gamma（`op_kernel/add_rms_norm_cast.h:222-232`），并把 `y1` 写成 `y2` 的 FP32 提升（`:236-241`）；BF16 分支把 `x*rstd` 舍入到 BF16、转回 FP32 后乘 gamma，`y1` 同样是 `y2` 的提升（`:196-214`）。950 regbase 全程 FP32，`y1` 直接存未舍入结果，再单独 `Cast` 出 `y2`（`op_kernel/arch35/add_rms_norm_cast_regbase_common.h:88-127`）。这一差异是本需求第 2 节「中间精度规则」需求决策的直接来源，处理方式见第 7 节。

### 1.3 kernel 分发

| 入口文件 | 适用 SoC | 分发方式 |
|---|---|---|
| `op_kernel/add_rms_norm_cast.cpp:41-64` | A2/A3 | `TILING_KEY_IS(...)` 显式匹配 10/30/11/31/13/33/14 |
| `op_kernel/add_rms_norm_cast_apt.cpp:32-64` | 950/910_93(apt)/960dt | 先按 8200 分流出 reduce-empty，再在 `else` 内按 100/101/102/103/199 匹配 |

## 2. 模板设计

### 2.1 A3：`dtypeKey * 10 + modeKey`

`dtypeKey`：FP16=1、BF16=3（`tiling.cpp:33-35`）；`modeKey`：NORMAL=0、SPLIT_D=1、MERGE_N=2、SINGLE_N=3、MULTI_N=4（`tiling.cpp:40-44`）。最终 key 在 `tiling.cpp:329` 计算。

| tiling key | 模板类（kernel 文件） | 选择条件（`tiling.cpp:313-327`，按此顺序命中即止） | 计算流程要点 |
|---|---|---|---|
| 10 / 30 | `KernelAddRmsNormCast`（`add_rms_norm_cast.h:27`） | 默认起点，且未命中下面两条：`numCol <= ubFactor` 且 `blockFactor > 1` | 外层按 `rowFactor=64` 行一组（`:80-90`），组内逐行 `CopyIn → Computefp16/Computebf16 → CopyOutY`；`inQueueX`/`outQueueY` 用 `BUFFER_NUM` 双缓冲 |
| 11 / 31 | `KernelAddRmsNormCastSplitD`（`add_rms_norm_cast_split_d.h:27`） | `numCol > ubFactor(8704)` | 两趟遍历：第一趟按列块累加平方和并顺带写出 `x`，`ComputeRstd` 后第二趟按列块重算 `y1/y2`；`sumBuf` 承载每行部分和，`BlockReduceSumFP32` 归并 |
| 13 / 33 | `KernelAddRmsNormCastSingleN`（`add_rms_norm_cast_single_n.h:22`） | `blockFactor == 1`（即 `numRow <= numCore`）且非 310P | 一核恰好一行，`MAXBUF=195584` 字节单块 UB 一次装下整行；`rstd` 直接用标量 `GetValue(0)` 参与 `Muls` |
| 14 | `KernelAddRmsNormCastMultiN`（`add_rms_norm_cast_multi_n.h:22`） | 无代码路径置 `modeKey = MODE_MULTI_N` | **不可达**：`MODE_MERGE_N=2`/`MODE_MULTI_N=4` 在 tiling 中从未被赋值，`TILING_KEY_IS(14)` 分支是死代码 |

- 分支优先级存在一个易错点：`blockFactor == 1` 的判断（`tiling.cpp:322`）排在「FP16 且 `numCol == numColAlign` 时重新确认 NORMAL」（`:324`）之前，所以**单行输入一定落到 SINGLE_N**，即使 `numCol` 已对齐。
- `rowFactor=64`（`tiling.cpp:307`）只在 NORMAL/SplitD 的循环组织中使用；SINGLE_N 忽略它（`single_n.h:37` 把 `blockFactor` 强置 1）。

### 2.2 A5：`TILING_OFFSET_REGBASE(100) + tilingType`

`tilingType` 常量在 `op_host/add_rms_norm_cast_tiling.h:75-79`，key 在 `add_rms_norm_cast_tiling_arch35.cpp:476-483` 计算。950 通过模板注册表按优先级分发：ReduceEmpty 优先级 50、Regbase 优先级 100（`tiling.h:87-90`）。

| tiling key | 模板类（kernel 文件） | 选择条件（`tiling_arch35.cpp:276-364`） |
|---|---|---|
| 103 | `KernelAddRmsNormCastRegBaseHighPerformance`（`arch35/add_rms_norm_cast_regbase_high_performance.h:36`） | 「Full Load + 高性能求和」：`tmpUBSize > 0`、`baseNDtypeAlign <= fullLoadRMax = vecLength²*4 = 16384`、算出的 `baseM >= 1` 且 `mPerCore > 1`（`:296-310`）。整行装入且一核可容纳多行，用 binary-add 树归约 |
| 100 | `KernelAddRmsNormCastRegBaseNormal`（`arch35/add_rms_norm_cast_regbase.h:23`） | 兜底分支之一：`CalUBTotalSize(mPerCore, numN) < maxUbSize`（不切分，`:313-319`）或切 M 后 `mPerCore > 1`（`:331-342`） |
| 102 | `KernelAddRmsNormCastRegBaseSingleN`（`arch35/add_rms_norm_cast_regbase_single_n.h:33`） | 与 100 同源，但 `mPerCore == 1`（`numM <= totalCoreNum`），即一核一行（`:316`、`:341`）。`PostTiling` 会 `SetScheduleMode(1)` 开启跨核同步（`:455-457`） |
| 101 | `KernelAddRmsNormCastRegBaseSpiltReduce`（`arch35/add_rms_norm_cast_regbase_spilt_reduce.h:21`） | 整行装不下：`CalUBTotalSize(1, numN) > maxUbSize` 后走「切 N」（`:345-363`）。用 workspace 存中间归约结果，`powerSplit`/`powerLoop` 控制分块宽度与循环次数 |
| 199 | 无（空 kernel，`add_rms_norm_cast_apt.cpp:60-61`） | `numM == 0`（`:175-177`），全空输出由框架处理，不下发计算。**本需求支持域排除空张量，不覆盖** |
| 8200 | `RegbaseReduceEmpty`（`arch35/add_rms_norm_cast_regbase_reduce_empty.h:33`） | `numN == 0 && numM > 0`，只把 `rstd` 按行写 NaN（`tiling_reduce_empty_arch35.cpp:66-72`）。**本需求支持域排除空归约，不覆盖** |

**模板选择优先级（regbase `SetTilingParams`）**：HighPerformance → 不切分(Normal/SingleN) → 切 M(Normal/SingleN) → 切 N(SpiltReduce)。前一步命中即 `return`，所以高行数 + 窄 N 优先走 HighPerformance 而不是 Normal。

## 3. 分核设计

### 3.1 A3

```
tileNum      = CeilDiv(numRow, numCore * 1)          # tiling.cpp:300
blockFactor  = tileNum                                # :302 每核行数
useCoreNum   = CeilDiv(numRow, blockFactor)           # :303 实际启用核数
SetBlockDim(useCoreNum)
```

- 并行维度是**行（numRow）**，`numRow = prod(x1.shape[:-rank(gamma)])`、`numCol = prod(gamma.shape)`（`:283-296`）。
- 每核行数相同（`blockFactor`），尾核 = `numRow - (useCoreNum-1)*blockFactor`，在 kernel 内用 `rowWork` 体现（`add_rms_norm_cast.h:52-58`）。行数不能整除时不回退到「每核 1 行」，而是把余数集中给最后一个核，属**尾核负载不均**的取舍：避免块数爆炸导致 tiling 复杂度上升。
- SINGLE_N（`blockFactor == 1`）时 `useCoreNum == numRow`，即一核一行；若 `numRow < numCore` 则部分核空闲。
- `numCore` 取 `GetCoreNumAiv()`：910B1/B2/B2C 为 48 个 AIV，910B3/B4 为 40 个 AIV（硬件规格）。同一 shape 在不同子型号上可能落不同核数，但 `blockFactor==1` 的判定阈值也随之变化——这是 cases 设计中单行用例必须单独覆盖的原因。

### 3.2 A5

```
mPerCore   = CeilDiv(numM, totalCoreNum)              # tiling_arch35.cpp:378
usedCoreNum= CeilDiv(numM, mPerCore)                  # :379
mLastCore  = numM - (usedCoreNum-1)*mPerCore          # :380
```

- 仍是**按行切核**，但每核行数先按「均分」计算再回填 `mLastCore`，尾核在 kernel 里用 `blockIdx == blockNum-1` 判定（`regbase.h:59-60`）。
- `baseM` 参与「Magic and Wonderful」判定：`baseM >= mPerCore` 时（实际被 `std::min` 压到 `mPerCore`）走 HighPerformance；`mPerCore == 1` 时退化为 SingleN 并启用 `ScheduleMode(1)`。
- 950 AIV 数按 Tier 不同（8/28/32/36 核，vector_core_cnt = 2×cube_core_cnt），因此 `mPerCore` 也随 SKU 变化。
- **无跨核结果合并**：归约只在行内进行，行与行完全独立，不需要 `SyncAll`/`IBSet` 之类的核间同步；只有 Magic-and-Wonderful 模式因为一核一行且需要保证「确实有核在跑」才设置 `ScheduleMode(1)`（`:455-457`）。

## 4. 分块设计

### 4.1 A3 的 ubFactor

| 常量 | 值 | 含义 |
|---|---|---|
| `UB_USED` | 1024 B | 预留给框架的 UB 扣除量（`tiling.cpp:26`、`:266`） |
| `UB_FACTOR_B16` | 8704 元素 | 非切列路径的列块宽度，FP16/BF16 下即 17408 B/块（`:29`、`:267`） |
| `UB_FACTOR_B16_CUTD` | 12096 元素 | 切列路径的初始上界（`:31`、`:319`） |
| `BLOCK_ALIGN_NUM` | 16 | 32B / sizeof(bf16) 的元素对齐数（`:37`） |

切列（SplitD）时不是简单取 12096，而是**先按 12096 求列块个数再回算对齐宽度**：

```
colTileNum = CeilDiv(numCol, 12096)                      # :320
ubFactor   = CeilDiv(numCol, colTileNum * 16) * 16        # :321  按 16 元素（32B）对齐
```

这样保证 `numCol / ubFactor` 的块数尽量少且每块宽度是 32B 的整数倍，尾块宽度 = `numCol - (j_max-1)*ubFactor`，在 `split_d.h:88-102` 由 `col_tail` 处理。

`ubFactor` 与 UB 占用的关系（NORMAL，`add_rms_norm_cast.h:72-79`）：`inQueueX` + `outQueueY` 各 `BUFFER_NUM × ubFactor × sizeof(T)`，另加 `xFp32Buf`/`sqxBuf`/`tmpBuf`（各 `ubFactor×4B`）与 `tmpBuf2`（`ubFactor×3×sizeof(T)`）。8704 × 2B 的单块约 17KB，全量约 187KB，落在 910B Gen2 的 192KB UB 内。

### 4.2 A5 的 baseN / baseM

`CalUBTotalSize`（`tiling_arch35.cpp:239-274`）给出两种布局的字节数模型：

- `TILING_TYPE_NORMAL`：按 `baseM × baseN` 的二维块分配 3 份 dtype 输入/输出 + 1 份 FP32 临时 + reduceBuf + gamma + y1 + y2 + rstd。
- 切 N 布局：按 `1 × baseN` 分配，额外加 3 份 `ONCE_VECTOR_SIZE(=256)` 的 level 缓冲与 1 份 `vecLength` 的 tempBuf。

求解顺序（`SetTilingParams`）：

1. 令 `baseN = numN`，先扣掉 `UB_RESERVE_FOR_RSTDALIGN = 1024` 字节与一份 gamma（`tiling_arch35.cpp:280-283`）。
2. 若 `baseNDtypeAlign <= fullLoadRMax`，反解 `baseM = tmpUBSize / (对齐列宽 × dtype × 双缓冲 × 队列数 + …)`（`:296-305`）。分母中的 `DOUBLE_BUFFER_NUM(=2) × QUE_MODE_NORMAL_NUM(=4)` 就是「4 个队列 × 2 深」的显式 UB 预算。
3. `baseM` 被 `std::min(baseM, mPerCore)` 压住，避免单次装入超过本核实际行数（`:308`）。
4. 整行装不下时先试「切 M」：`CalUBTotalSize(1, numN) <= maxUbSize` 则用差分公式估算 `baseM`（`:328-342`，注释里给出了由 `CalUBTotalSize(M,N) = c·M·Align2(N) + b·Align1(N) + rstdCount·AlignB32(M)` 推出来的近似式）。
5. 连一行都装不下才「切 N」：`powerSplit` 从 `xReduceAlignNum (=512B/dtypeSize = 256)` 起倍增，直到再加倍就超 UB（`:348-353`）；`powerLoop` 取不超过 `numN/powerSplit` 的最大 2 的幂（`:354-357`）。剩余尾部由 `SubProcessRstd` 里的 `powerTailLoop`/`powerTailTail` 处理（`spilt_reduce.h:96-104`、`:233-256`）。
6. NORMAL / MAGIC_AND_WONDERFUL 额外把 `powerSplit` 规整到 `baseNReduceAlign` 的 2 的幂（`:389-392`），供 binary-add 树归约使用。

`isNddma = (numN < 512)`（`:191`）：窄 N 时用 ND-to-ND 的 `NdDma` 带 padding 搬运（`regbase.h:161-179`），宽 N 时退回 `DataCopyPad` + 手动 `Duplicate` 补零（`:182-205`、`:246-254`）。

## 5. 性能调优技巧（仅列源码中确实存在的机制）

| 技巧 | 位置 | 说明与取舍 |
|---|---|---|
| 双缓冲 | A3 `add_rms_norm_cast.h:73-74`（`BUFFER_NUM`）；950 `regbase_high_performance.h:66-76`（`DOUBLE_BUFFER_NUM=2`，6 个队列都开双缓冲） | MTE2 搬入与 Vector 计算重叠。代价是 UB 里每队列 ×2，直接压缩了可用的 `baseM`/`ubFactor` |
| 三算子融合 | 整个 kernel 结构 | 一次搬入 `x1/x2/gamma` 同时产出 4 个输出，省掉 Cast 算子的二次搬入搬出；`x` 复用同一份加法结果，不需要重新读 GM |
| SplitD 两趟复用 | `split_d.h:104-131` | 第一趟算平方和时顺带把 `x` 写出，第二趟直接从 GM 读 `x` 复算 y——用一次 GM 往返换取 UB 里不必保留整行 |
| binary-add 树归约 | 950 `regbase_high_performance.h` `CalculateSquareReduceSum(..., binAddQuotient, ...)`；A3 `ReduceSumCustom` | 把 `numN` 级串行归约改成 log 级树形加，减少向量指令条数；需要按 `powerSplit` 规整长度并额外分配 `binAddBufferOneline` 大小的缓冲 |
| 多级归约缓冲 | `spilt_reduce.h:88-90`、`:205-266` | 切 N 时把每段结果先落到 level1/2/3 三级缓冲再合并，避免 workspace 反复读写 |
| NDDMA | `regbase.h:161-179` | 窄 N 时用维度描述符一次完成多行搬入 + 尾部 padding，减少指令数与 `Duplicate` 补零开销 |
| 寄存器向量（regbase/VF） | `regbase_common.h:88-127`、`:146-190` | `__VEC_SCOPE__` 内用 `RegTensor` + `LoadAlign/StoreAlign` 直接算，`ComputeY` 里按 `count/2` 手工展开两路；`rstd` 用 `DIST_BRC_B32` 一次广播到整条向量 |
| Unroll 与打包写 | `regbase_common.h:88-127` | `calCount = count/2` 双路展开；`y2` 用 `StoreDist::DIST_PACK_B32` 把 FP32 寄存器直接打包成 16bit 写出，省一次 UB 中转 |
| Newton-Raphson 求倒数 | 950 `regbase_high_performance.h` `NormCommon::ComputeRstdNewtonRaphson` | 用迭代法代替 `Sqrt`+`Div` 两条指令链 |
| 标量广播 rstd | A3 `add_rms_norm_cast.h:63-67`（`Brcb`）、`single_n.h:180-192`（`GetValue(0)` + `Muls`）；`multi_n.h:204-206`（`Gather` 展开到列宽） | 一核一行时完全用标量，省掉整条向量的 rstd 广播 |
| 对齐搬入搬出 | `regbase.h:182-205`（`DataCopyPadExtParams` 的 `dtypeBlockStride_`）；A3 `DataCopyCustom` | 按 32B 对齐的 stride 描述符搬运多行，非对齐尾块用 rightPadding 补零，避免逐行发起小搬运 |
| 负载均衡 | A3 尾核模型（§3.1）；950 MAW 的 `SetScheduleMode(1)` | 前者把余数集中到最后一个核；后者允许核间按完成情况取任务 |

**未验证**：以上机制只做了静态阅读，没有 profiler 数据，不宣称任何具体加速比。`op_kernel/add_rms_norm_cast_multi_n.h` 虽然含 `Gather`/`ReduceSumCustom` 等优化写法，但因为 tiling 从不产生 `MODE_MULTI_N`，实际不会被编入可执行路径。

## 6. 模板与测试用例覆盖映射

### 6.1 A3（910B/910C）

判定复算依据：`numRow = prod(x1.shape[:-rank(gamma)])`、`numCol = prod(gamma.shape)`、`ubFactor = 8704`（B16）、`blockFactor = CeilDiv(numRow, numCore)`。核数取 910B3/B4 的 40 AIV（`blockFactor` 更大，结论同向）与 910B1/B2 的 48 AIV 都复核过，仅极少数边界用例的 `blockFactor==1` 判定会变，下表已标注。

| 模板 | 源码依据 | 外部触发条件 | case_id | 验证状态 |
|---|---|---|---|---|
| SINGLE_N（13/33） | `tiling.cpp:322-323`；`add_rms_norm_cast.cpp:53-59` | `numRow <= numCore` 且 `numCol <= 8704` | 1（FP16，numRow=1）、2（BF16）、4（BF16，numCol=7166 非对齐）、5（BF16，numCol=152）、6（BF16，numRow=32 ≤ 40/48）、11（FP16，numCol=256）、19（BF16，numCol=6048, numRow=2）、20（FP16，numRow=30 ≤ 40/48） | 静态推断 |
| NORMAL（10/30） | `tiling.cpp:313-326`；`add_rms_norm_cast.h:27` | `numRow > numCore` 且 `numCol <= 8704` | 3（FP16，numRow=64）、8（FP16，numRow=4015，numCol=117）、13（FP16，numRow=4096）、16（FP16，numCol=7167 非对齐）、18（FP16，numCol=182） | 静态推断 |
| SPLIT_D（11/31） | `tiling.cpp:317-321`；`split_d.h:27` | `numCol > 8704` | 7（FP16，numCol=10950，ubFactor=10960）、9（BF16，numCol=40320）、10（FP16，numCol=16384）、12（BF16，numCol=16384）、14（FP16，numCol=204800，colTileNum=17）、15（BF16，numCol=10370）、17（BF16，numCol=10950） | 静态推断 |
| MULTI_N（14） | `tiling.cpp:40-44` 中 `MODE_MULTI_N=4` 从未赋值 | 无 | — | 不可达（死代码） |
| MERGE_N（modeKey=2） | 同上 | 无 | — | 不可达 |
| 全空 / 空归约 | `tiling.cpp:204-237` 拒绝 `numCol==0` | `numCol == 0` | — | 不在支持域（desc.md §3「规则与约束」已排除） |

### 6.2 A5（950/3510）

判定复算依据（按 28 核 Tier、`maxUbSize = 253952`、`vecLength = 64`、`xReduceAlignNum = 256` 计算）：
`fullLoadRMax = 64×64×2×2 = 16384`，`UB_RESERVE_FOR_RSTDALIGN = 1024`。
`baseM_H` = `(253952-1024-baseNDtypeAlign×2) / (baseNDtypeAlign×2×2×4 + baseNDtypeAlign×4×2 + baseNDtypeAlign×4 + 12 + binAddBufferOneline×4)`。

| 模板 | 源码依据 | 外部触发条件 | case_id | 验证状态 |
|---|---|---|---|---|
| HIGN_PERFORMANCE（103） | `tiling_arch35.cpp:296-310`；`regbase_high_performance.h:36` | `numM > totalCoreNum`（`mPerCore > 1`）且 `numN <= 16384` 且 `baseM_H >= 1` | 3（numM=64/numN=7168/mPerCore=3）、6（32/7168/2）、7（15/10950/2）、8（4015/117/144）、13（4096/7168/147）、16（128/7167/5）、17（15/10950/2）、18（140/182/5）、20（30/168/2） | 静态推断 |
| NORMAL（100） | `tiling_arch35.cpp:313-319 / 331-342`；`regbase.h:23` | `mPerCore > 1` 且整行装得下但 `baseM_H == 0` | 15（numM=64/numN=10000/mPerCore=3：`baseM_H` 分母 237824 > 剩余预算 229952 → `baseM_H=0`；而 `CalUBTotalSize(1,10000)=183552 < 253952`，落不切分包）。该路径需要 `numN` 落在「多行装不下、单行装得下」的窄窗口（约 9500 ~ 13900），是 20 个用例里最容易漏掉的一档 | 静态推断 |
| MAGIC_AND_WONDERFUL / SINGLE_N（102） | `tiling_arch35.cpp:316 / 341`、`:455-457`；`regbase_single_n.h:33` | `numM <= totalCoreNum`（`mPerCore == 1`）且整行装得下（`CalUBTotalSize(1, numN) < maxUbSize`） | 1（numM=1/numN=7168）、2（1/7168）、4（1/7166）、5（3/152）、11（1/256）、19（2/6048）。`mPerCore==1` 时即便 `baseM_H >= 1` 也落到本模板，因为 `:308` 的 `std::min(baseM, mPerCore)` 把 `baseM` 压到 1，`:309` 的 `mPerCore > 1` 条件不成立 | 静态推断 |
| SPILT（101） | `tiling_arch35.cpp:345-363`；`spilt_reduce.h:21` | 单行都装不下：`CalUBTotalSize(1, numN) > maxUbSize`。按 `19×Align(N) + 3360` 反推，窄 N 下该阈值为 `numN ≳ 13900` | 9（numN=40320，`CalUBTotalSize(1,40320)=765504`，powerSplit=8192、powerLoop=2）、10（numN=16384，`CalUBTotalSize=308784`）、12（numN=16384，同 10）、14（numN=204800，`powerSplit=8192`、`powerLoop=16`） | 静态推断 |
| UNRUN（199） | `tiling_arch35.cpp:175-177`、`:477-480` | `numM == 0` | — | 不在支持域 |
| REDUCE_EMPTY（8200） | `tiling_reduce_empty_arch35.cpp:66-72`；`regbase_reduce_empty.h:33` | `numN == 0 && numM > 0` | — | 不在支持域（仅 950 支持该语义，A3 会拒绝，无法用同一份需求约束） |

说明：

- 同一个用例在两条后端上覆盖的模板不同是预期内的：例如 7/17（`numCol=10950`）在 A3 落 SPLIT_D（`> 8704`），在 950 因整行装得下而落 102。映射表按 SoC 分列正是为了记录这一点。
- 950 的判定对核数 Tier 敏感：上表按 28 核 Tier（56 AIV）计算。若目标核数更多（36 核 Tier），6（numM=32）会从 103 变回 102；若核数更少（8 核 Tier），几乎所有 `mPerCore==1` 的用例都会升到 103，同时 15 也可能因为剩余预算变大而挪到别的分支。105 行以下、其余用例的判定与 Tier 无关。

### 6.3 一致的覆盖缺口

| 未覆盖项 | 原因 |
|---|---|
| 空张量（`m==0`、`n==0`）与空归约（`n==0 && m>0`） | 各代际产品语义不一致（950 给 `rstd` 填 NaN，A3 直接拒绝），无法用同一份需求约束；按 SKILL 要求不生成异常/预期报错用例，故整体排除在支持域外 |
| `MODE_MERGE_N` / `MODE_MULTI_N`（key 2/14） | tiling 中无赋值路径，不可达 |
| `MODE_SPILT` 在 950 上 `powerTailTail != 0` 的极端尾部 | 需要 `numN` 落在 `powerSplit` 的非整数倍区间（如 `numN = 20000` 且 `powerSplit = 8192` 时 `powerTailTail = 7712`）。20 个上限下优先覆盖主路径；当前 9/14 两个切 N 用例已分别覆盖 `powerLoop>1` 与 `powerTailLoop>1`，未细拆尾部分支 |
| 910B1/B2（48 AIV）与 910B3/B4（40 AIV）的 `blockFactor` 差异 | 未做逐子型号用例。case 20（numRow=30）与 case 6（numRow=32）正好落在 40 与 48 的中间：在 40 AIV 上 `blockFactor==1` 落 SINGLE_N，在 48 AIV 上同样 `blockFactor==1`，但 numRow=64 的 case 3 在两种核数下都是 NORMAL。两档阈值的分界行为由这组用例间接体现，未单独构造 numRow=41~48 的用例 |
| 非 16 元素对齐的 `numCol` 在 SPLIT_D 下的多次列块 | case 14（numCol=204800）给出 `colTileNum=17`，但仍然是 16 的整数倍；质数宽度的大 `numCol` 未覆盖 |
| 实测（真机运行） | 本轮只做静态推断，未在 NPU 上执行任何用例；`tests/st/arch35/ttk_kernel_add_rms_norm_cast_st.csv` 中的既有用例可作为后续实测的起点 |

## 7. 源码依据与需求决策

### 7.1 可直接由源码确认的事实

| 结论 | 依据 |
|---|---|
| 输入 dtype 仅 FP16/BF16，输出 `y1`/`rstd` 为 FP32，`y2`/`x` 随输入 | `def.cpp:23-67`；`proto.h:66-73`；`infershape.cpp:87-90` |
| `epsilon` 为可选属性，默认 1e-6 | `def.cpp:68`；`proto.h:74` |
| `rstd` shape = 前若干维照抄 `x1`、归约维置 1 | `infershape.cpp:67-73`；文档 `aclnnAddRmsNormCast.md` 的 `rstdOut` 行 |
| 归约范围 = `gamma` 覆盖的末尾各维 | `tiling_arch35.cpp:158-172`（`numM`/`numN` 的乘法范围） |
| A3 的 `epsilon < 0` 被显式拒绝 | `tiling.cpp:279-283` |
| 维度数上限 8、`rank(gamma) <= rank(x1)`、`gamma` 必须是 `x1` 的末尾维 | `tiling.cpp:75-130`、`:204-237` |
| A3 中间舍入规则：FP16 先舍入 `x*rstd` 再乘 gamma；BF16 舍入到 BF16 再转回 FP32 乘 gamma；`y1` 为 `y2` 的 FP32 提升 | `add_rms_norm_cast.h:222-241`（FP16）、`:196-214`（BF16）；`split_d.h:284-310` / `:313-347` |
| 950 全程 FP32，`y1` 未舍入，`y2` 单独 `Cast` | `regbase_common.h:88-127` |

### 7.2 来源冲突与最终决策

| 冲突 | 各方说法 | 最终决策（已写入 desc.md） |
|---|---|---|
| **`y1` 的数值口径** | golden（`add_rms_norm/…/golden.py` 的 `add_rms_golden_v1`）在 A2/A3 分支里 `y1 = y2.float()`，即 `y1` 带一次输入 dtype 舍入；`add_rms_golden_v2`（950）`y1 = tmpX * gamma` 全 FP32。kernel 侧与各自 golden 分支一致。 | 统一为 **全 FP32、不做中间低精度舍入**（desc.md §2「中间精度规则」）。理由：①只有全精度口径能与 950 实现逐位对齐，也符合 `proto.h:22-26` 与接口文档的公式；②A3 侧的一次舍入偏差可以由输入 dtype 阈值吸收（§7.3 已核算），反向选择（要求 `y1` 带舍入）则会让 950 实现必然超 FP32 阈值。兼容性影响：A3 实现在 `y1` 上相对新 golden 有约 1 ulp 的固定偏差。 |
| **`y1` 的判定阈值** | 按 dtype 表面看是 FLOAT32 → 2^-13；但若按 2^-13 判定，A3 的中间舍入偏差必然判不通过 | `y1` 按**输入 dtype** 阈值判定（FP16 2^-10、BF16 2^-7），在 desc.md §4.2 明示为需求决策。核算：FP16 一次舍入相对误差 ≤ 2^-11，叠加一次乘法舍入后 MARE 上界约 2^-10、MERE 远小于阈值；BF16 单次 2^-8、两次后 MARE 上界 2^-7，仍在 2^-7（MERE）/2^-6（MARE，=10×Threshold）之内，且 BF16 平均误差约 2^-9，留有 4× 余量。 |
| **空张量 / 空归约** | 接口文档：950 支持空归约（`rstd` 填 NaN），A3 不支持；A3 tiling 直接拒绝 `numCol==0` | 支持域内**排除**空张量与空归约（desc.md §3「规则与约束」）。理由：无法用一份需求在两个后端上给出统一期望值，且 SKILL 要求不生成预期报错的异常用例。 |
| **`epsilon` 有效域** | 接口文档只说「建议 1e-6」，`tiling.cpp:279` 拒绝负数；`tiling_arch35.cpp` 未校验负值 | 明确为 `epsilon >= 0`，且以 A3 的显式校验为准（desc.md §3）。950 侧对负值的行为不做承诺（不在支持域）。 |
| **`gamma` 是否允许 0 维** | OpDef 未限制；`tiling.cpp:79` 要求 `gammaDimNum >= 1` | 取 `rank(gamma) ∈ [1, 8]`。 |

### 7.3 AI 自行确定的需求规则清单及对产物的影响

| 规则 | 影响到的产物 | 说明 |
|---|---|---|
| R1：`y1` 全 FP32 计算，`y2 = cast(y1)`，`x = cast(FP32 sum)` | desc.md §2、§4.2；golden.py 的 `y1`/`y2`/`x` 计算；proto.yaml 的 `note` | golden.py 与原始 `add_rms_golden_v1` 的 A3 分支数值路径不同（不再做中间舍入）；与 `add_rms_golden_v2` 等价 |
| R2：`y1` 按输入 dtype 阈值判定，`rstd` 按 FP32 阈值判定 | desc.md §4.1、§4.2 | 避免 `y1` 被 FP32 阈值必然判失败 |
| R3：支持域排除空张量与空归约 | desc.md §3；cases 中不出现含 0 维的 shape | 与既有 ST 数据（含 `(16,0)`、`(8388609,0)` 等空归约用例）刻意不同 |
| R4：`epsilon >= 0` 为有效域，测试覆盖 1e-6 / 1e-5 / 1e-3 | desc.md §3、§3「支持范围」；cases 12/14/17 | 1e-3 是常规范围外的大补偿项，用于验证 `Adds(sqx, epsilon)` 的数值路径，仍属有效输入 |
| R5：每个用例的 `value_range` 按 `[x1, x2, gamma]` 三元给出 | cases.yaml / cases.csv | 与 `input_shape` 的三元组一一对应，避免三输入共用一个区间导致 `x1 ≈ -x2` 时和恒为 0、`rstd` 退化为 `1/sqrt(eps)` 而失去区分度 |
| R6：`rstd` 只要求数值匹配、不要求 `y2 == cast(y1)` 逐位成立 | desc.md §4.2 | 实测层面 `y2` 与 `y1` 的舍入关系应在 golden 侧保证，但不应作为独立的通过判据，否则会把 R1 的偏差放大成双重判定 |

### 7.4 未证实项

- 未在 910B/910C/950 真机上运行任何用例；§6 表中的「静态推断」全部来自 tiling 公式的手工复算，核数取的是硬件规格里的典型值（910B 40/48 AIV、950 28 核 Tier 的 56 AIV），实际 `GetCoreNumAiv()` 返回值可能随固件/编译配置不同。
- 950 上 `fullLoadRMax`、`binAddBufferOneline`、`CalUBTotalSize` 的具体数值依赖 `GetVRegSize()`（源码注释标注为 256B @ 950）与 `GetUbBlockSize()`（32B），若目标平台的 vreg 宽度不同，§6.2 的部分判定（如 case 7/15 落 100 还是 101）需要重算。
- §5 的性能技巧没有 profiler 数据支撑，不宣称任何量化收益。
- `add_rms_norm_cast_apt.cpp` 中的 `TILING_KEY_IS(8200)` 分支与 `AddRmsNormCastReduceEmptyTilingData`（32B）和通用 tiling data（96B）的长度差异，源码注释已提示「8200 场景 tiling 缓冲仅容纳专用结构，通用解包会越界读」；本需求不覆盖该场景，未做进一步验证。
