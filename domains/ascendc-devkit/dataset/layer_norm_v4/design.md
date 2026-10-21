# LayerNormV4 内部设计分析

> 本文是内部设计文档，允许记录 tiling key、模板名、源码路径与内部阈值。
> 需求文档（desc.md）、golden.py 与 cases.yaml/csv 中不出现这些内部标识。
> 分析范围：Ascend A3（910B/910C，membase）与 A5（950/3510，arch35 regbase）。
> 310P、Kirin、960 系列配置不纳入分析。

## 1. 实现概览

### 1.1 host 侧

| 环节 | 源码位置 | 行为 |
|---|---|---|
| OpDef | `op_host/layer_norm_v4_def.cpp:23-58` | `x`(FLOAT/FLOAT16/BF16)、`normalized_shape`(INT32)、可选 `gamma`/`beta`、输出 `y`(同 x)、`mean`/`rstd`(FLOAT)；属性 `epsilon` 默认 1e-5 |
| A3/A2 配置 | `layer_norm_v4_def.cpp:59-65` | `ascend910b`/`ascend910_93` 走 membase kernel（opFile=`layer_norm_v4`） |
| A5 配置 | `layer_norm_v4_def.cpp:110-174` | `ascend950`/`ascend350`/`ascend960*` 走 regbase kernel（opFile=`layer_norm_v4_apt`），`normalized_shape` 同时支持 INT32/INT64 |
| Tiling 入口 | `op_host/layer_norm_v4_tiling.cpp:22-60` | `TilingRegistry::DoTilingImpl`；`TilingPrepare4CompileInfo` 取 AIV 核数、UB 大小、blockSize、vectorLength，并置 `isRegBase` |
| Tiling 基类 | `op_host/layer_norm_v4_tiling_base.cpp:111-170` | 读取 dtype/可选输入/eps；融合维度：`colSize = ∏x[0 : rank-j]`（外层行数）、`rowSize = ∏x[rank-j : rank]`（归一化元素数）；`rowAlign` 按 UB block（32B）对齐：fp32 对齐 8、fp16/bf16 对齐 16 |
| 模板注册 | 6 个 `*_tiling.cpp` 末尾 | 每个模板一个注册优先级（见 2.1） |

`GetDTypeKey(tensorDtype, paramDtype) = tensorKey*10 + paramKey`（FLOAT=0/FLOAT16=1/BF16=2，`layer_norm_v4_tiling_base.cpp:33-54`），`paramDtype` 取 gamma（优先）或 beta 的 dtype，两者都为空时按 FLOAT 处理（`layer_norm_v4_tiling_base.cpp:116-122`）。该 key 决定各模板 tiling key 的末位。

### 1.2 device 侧分发

| 平台 | 入口 | 分派方式 |
|---|---|---|
| A3 | `op_kernel/layer_norm_v4.cpp:107-207` | `TILING_KEY_IS()` 精确匹配 100/110/111/120/122、200/210/211/220/222、700/701/702、600/601/602、1600/1601/1602、2600/2601/2602 |
| A5 | `op_kernel/layer_norm_v4_apt.cpp` → `layer_norm_v4_apt.h:79-142` | 匹配 300-322、400-422、500-522；先 `g_coreType == AIC` 直接 return，再 `KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY)` |

数据流统一为：GM(x, gamma, beta) → UB tile → 转 fp32 → 行内求均值/二阶矩 → 得 mean、rstd → 归一化并施加 gamma/beta → 转回输入 dtype → GM(y, mean, rstd)。

## 2. 模板设计

### 2.1 选择机制与优先级（源码事实）

框架用 `std::map<int32_t, TilingClassCase>` 保存模板，`DoTilingImpl` 按 map 的**升序**遍历，执行 `DoTiling()`，返回 `GRAPH_PARAM_INVALID` 表示 `IsCapable()==false` 继续尝试下一个（`common/inc/op_host/tiling_templates_registry.h:93-124`、`common/inc/op_host/tiling_base.h:70-90`）。因此 **注册数值越小越先尝试**，与头文件注释一致。

各模板注册优先级：

| 模板 | 注册优先级 | tiling key 生成 |
|---|---|---|
| Transpose | 100 | 200/210/211/220/222（按 x/param dtype） |
| SingleRead | 1000 | 100/110/111/120/122 |
| MergeN（CustomAlign 系列） | 1220 | 600/601/602 + `1000·[rowSize<=1280]` + `1000·[rowSize==1]`（即 600 族 / 1600 族 / 2600 族） |
| Common | 2000 | 700/701/702 |
| RegBaseTwoPassPerf | 150 | 500/510/511/520/522 |
| RegBaseTwoPass | 200 | 300/310/311/320/322 |
| Welford | 4000 | `4*100 + dtypeKey`（400/410/411/420/422） |

说明：skill 描述里按“数值由大到小”表述优先级，源码实际是升序尝试，两者对 A3 的结论一致（MergeN 1220 先于 Common 2000）。A5 上所有 membase 模板都因 `isRegBase` 直接返回 false，实际顺序为 TwoPassPerf(150) → TwoPass(200) → Welford(4000)，与 `docs/ParallelWelford_and_BinaryAccumulation_LayerNormV4.md` 的“Welford 最高（4000）”表述相反，以代码为准。

### 2.2 各模板条件与计算流程

**Transpose（A3，priority 100，`layer_norm_v4_transpose_tiling.cpp:54-72`）**

- 条件：`!isRegBase` 且 `rowSize <= TRANSPOSE_ROW_LIMIT(64)` 且 `rowSize != rowAlign`；dtype 组合需能生成非 0 key。
- 思路：小 rowSize 时行内归约的向量利用率低，把 `bFormer(≈ceil(ubFormer/16))×16` 行做转置，使“行”方向变成向量连续方向后再归约。
- 分块：`DoBlockTiling` 用 coreNum 求 `blockFormer=ceil(colSize/curBlockNum)`，`numBlocks=ceil(colSize/blockFormer)`，`blockTail=colSize-(numBlocks-1)*blockFormer`；`DoUbTiling` 在 UB 内扣除 2 份 gamma/beta 与 `UB_SIZE_RESERVED=1024` 后，按 `rowSize*4*4 + 4` 的每行开销求 `ubFormer`，再算 `bFormer`、ub 循环数与尾块；若借轴后超出 UB 则回退单核。
- `FindDichotomizeAddDiffSize` 记录 `rowSize` 与小于它的最近 2 的幂之差（如 20→16，差 4），供 kernel 做“非 2 的幂补齐累加”。

**SingleRead（A3，priority 1000，`layer_norm_v4_single_read_tiling.cpp:27-116`）**

- 条件：`rowSize ∈ {ALLOW_COL1=1024, ALLOW_COL2=4096}` 且 `tensorDtype == paramDtype == BF16` 且 `!isRegBase` 且 `rowAlign <= rowMax`，其中 `rowMax = ((UB - 8*32)/4)/2`（≈UB/(2*4)，为 x 的 fp32 副本留一倍空间）。
- 分核：`colSize <= coreNum` 时 `nRow=1`、`numBlocks=colSize`；否则 `nRow = rowMax/rowAlign`（上限 `N_ROW_LIMIT=32`）、`numBlocks=coreNum`，再按 `loopCount/tailLoop` 均分。
- 要点：一次 DataCopy 把 `nRow` 行读入，行内 mean 与 rstd 各做一次 `ReduceSum`，gamma/beta 在首次循环后常驻 UB 复用。

**MergeN / CustomAlign 系列（A3，priority 1220，`layer_norm_v4_merge_n_tiling.cpp:38-71`）**

- 条件：`!isRegBase && !isAscend310P && !isV3`，且 `nRow = ceil(colSize/coreNum) > 2`，同时满足 `rowSize < rowMax` 或 `rowSize <= COL_LIMIT(1280)`；`rowMax = (UB - UB_BUF(2048))/4/2`。
- key 编码：基址 600 + `dtypeKey%10`；`rowSize <= 1280` 再加 1000（走 `LayerNormCustomAlignLimit`，可做对齐/limit 特化）；`rowSize == 1` 再加 1000（走 `LayerNormCustomOne`，单元素特化）。
- 分核：`formerNum = colSize % numBlocks`，前面的核多处理一行（`nRow=ceil`），`tailNum = numBlocks - formerNum` 处理 `tailNRow=floor`，属典型大小核划分。
- 分块：`rowAlign` 按 block 对齐；`ableNRow = ubSize/4/(1+rowAlign)/2`（x 与 y 各一份 fp32），`rowAlign <= N_ROW_LIMIT(32)` 时对齐到 `N_ROW_ALIGN=64` 提升搬运效率；每核再按 `ableNRow` 拆成 `loopCount` 次与剩余行。

**Common（A3 兜底，priority 2000，`layer_norm_v4_common_tiling.cpp:35-95`）**

- 条件：`!isRegBase && !isAscend310P && !isV3`（任何未命中前面模板的 A3 场景）。
- 分核：`numBlocks = min(colSize, coreNum)`；`tileLength_ = min(rowSize, maxtileLength/2)`，`maxtileLength = (UB - 3KB)/4`；若 `maxtileLength - tileLengthAlign16 < tileCount` 则报“normalized shape too big”。
- 注意：该模板对 tiling 字段的 `colSize/rowSize` 赋值与其余模板相反（`td_.set_colSize(rowSize)`、`td_.set_rowSize(colSize)`），kernel 按该约定解释。
- 计算走 `NormKernel::KernelLayerNormBasic`（`op_kernel/kernel/kernel_layer_norm.h`）配合 block/subblock 的 copy-in/copy-out 模板。

**RegBaseTwoPassPerf / TwoPass / Welford（A5）**

- 全部要求 `isRegBase == true`（`compileInfo->isRegBase = IsRegbaseSocVersion(context) || npuArch == DAV_5102`）。
- Welford 无额外 shape 约束；TwoPassPerf 要求 `rowAlign <= 2*VL_FP32²*2`（950 上 VL_FP32=64，即 ≤16384）且不同时满足 `colSize>=4096 && rowAlign>=8192` 且 `CanFitInBuffer(1)`；TwoPass 要求二分搜索能放下至少 1 行，否则返回 false 交给 Welford。

### 2.3 tiling key 常量含义汇总

| key | 含义 |
|---|---|
| 100/110/111/120/122 | SingleRead：x/param dtype = F32/F32、F16/F32、F16/F16、BF16/F32、BF16/BF16 |
| 200/210/211/220/222 | Transpose：同上五组 dtype |
| 300/310/311/320/322 | RegBaseTwoPass：同上五组 dtype |
| 400/410/411/420/422 | Welford：`LNTemplateKey::WELFORD(4)*100 + dtypeKey` |
| 500/510/511/520/522 | RegBaseTwoPassPerf |
| 600/601/602 | MergeN 基础族（rowSize > 1280 且命中 MergeN 条件）：param=F32/F16/BF16 |
| 1600/1601/1602 | MergeN + `rowSize <= 1280`（AlignLimit 路径） |
| 2600/2601/2602 | MergeN + `rowSize == 1`（One 路径） |
| 700/701/702 | Common：param=F32/F16/BF16 |

dtypeKey 与 key 末位对应关系：`%10` = paramKey（0=F32、1=F16、2=BF16）。

## 3. 分核设计

| 模板 | 并行维度 | 核数选择 | 负载均衡 / 尾核 |
|---|---|---|---|
| Transpose | 外层行（colSize） | 从 `coreNum` 递减试 `blockFormer`，使 `numBlocks<=coreNum` | `blockTail` 收尾；UB 切分失败时退化为单核 |
| SingleRead | 外层行 | `colSize<=coreNum` 时按行开核，否则固定 `coreNum` | `loopCount` 整循环 + `tailLoop` 余核；行内余量 `tailNRow` |
| MergeN | 外层行 | `numBlocks = min(colSize, coreNum)` | 大小核：`formerNum` 个核处理 `nRow` 行、`tailNum` 个核处理 `tailNRow` 行，再有 `formerRemainNum/tailRemainNum` 尾行 |
| Common | 外层行 | `numBlocks = min(colSize, coreNum)` | 每核处理 `colSize/numBlocks` 行，行内按 tile 循环 |
| Welford / TwoPass / TwoPassPerf | 外层行（M 或 a） | `blockFactor = ceil(colSize/coreNum)`，`numBlocks = ceil(colSize/blockFactor)`；Welford 另有 `mainBlockCount` 与 `tailBlockFactor` | 首 `mainBlockCount` 个核为整核，最后一个为尾核 |

跨核无通信：LayerNorm 的归约只发生在一行内部，而行不会跨核拆分，因此不需要核间同步或结果合并。

## 4. 分块设计

- **行内对齐**：`rowAlign = ceil(rowSize/alignment)*alignment`，`alignment = 32B / sizeof(dtype)`（fp32→8，fp16/bf16→16），来自 `GetCommonShapeAttrsInfo`。
- **UB 预算**（各模板口径不同，均预留临时/参数空间）：
  - Transpose：扣除 2 份 gamma/beta 与固定 `UB_SIZE_RESERVED=1024`；每行开销按 `rowSize*4` 的 4 份（x 双份 + y + tmp）+ 1 个 float 计；借轴后额外校验 `bFormer*16*4 + 16*alignBAndRow*4*4 + alignB*16*4*2`。
  - SingleRead：`rowMax = ((UB - 8*32)/4)/2`，`nRow = rowMax/rowAlign`（上限 32），`tileLength = nRow*rowAlign`、`blockLength = nRow*rowSize`。
  - MergeN：`UB_BUF = 2048` 为固定预留；`ableNRow = (UB-2048)/4/(1+rowAlign)/2` 表示“x 的 fp32 版 + 结果”各占一份；`rowAlign<=32` 时对齐到 64 行。
  - Common：`OTHERS_UB_SIZE=3KB`、`TMP_UB_SIZE=1KB`、`MEAN_UB_SIZE=512B`、`NORMAL_UB_SIZE=128KB`、`NEED_UB_SIZE=188KB` 用于描述典型 UB 规模；`tileLength` 上限为 `(UB-3KB)/4/2`，并校验 `maxtileLength - tileLengthAlign16 >= tileCount`。
  - Welford：按 `x*2 + y*2 + mean/rstd(各 2*256*4) + welfordTemp(2*tileLength*4 + 256*4) + gamma/beta(2*tileLength*elem) + apiTemp` 求上限，`tileLength` 以 64 元素步进增长到刚好放得下（`WELFORD_TILELENGTH_STEP_SIZE=64`）。
  - TwoPassPerf：`aUbFactor = (UB - 2*VL*4*2*2) / (rowAlign * rowWeight)` 再逐减直到 `CanFitInBuffer`，`rowWeight = 2*betaElem + 2*xElem + 2*xElem + 4`。
- **尾块**：所有模板都用“整循环 + 尾循环”两级组织（`loopCount/tailLoop`、`ubLoopOfFormerBlock/ubTailOfFormerBlock`、`welfordUpdateTimes/welfordUpdateTail`），尾块用带掩码或 `DataCopyPad` 的不等长搬运处理。
- **关键阈值含义**：`TRANSPOSE_ROW_LIMIT=64`（转置收益边界）、`COL_LIMIT=1280`（AlignLimit 与基础 MergeN 的分界）、`ALLOW_COL1=1024`/`ALLOW_COL2=4096`（SingleRead 特化尺寸）、`N_ROW_LIMIT=32` / `N_ROW_ALIGN=64`（单次处理行数与其对齐）、`MAX_ROW_LIMIT=2040`（One 路径行上限）、`UB_BUF=2048`、`UB_SIZE_RESERVED=1024`、`B32/B16_BLOCK_ALIGN_NUM=8/16`。

## 5. 性能调优技巧（均为源码存在项）

| 技巧 | 位置 | 说明 |
|---|---|---|
| 单次读入整行 | `layer_norm_v4_single_read.h` | 对 1024/4096 这类常见 norm 长度，一次性把整行读入 UB，行内 mean/rstd 全部驻留，避免二次读取 x |
| UB 内 gamma/beta 复用 | `layer_norm_v4_single_read.h:208-247` | gamma/beta 只在首次循环搬入并 cast 成 fp32，后续循环复用 |
| 转置提升小 row 利用率 | `layer_norm_v4_transpose.h:197-497` | 用 `Copy` 做 16×16 块转置，把行方向变为连续方向后归约；`dichotomizeAddDiffSize` 处理非 2 的幂行 |
| 二分累加 | `arch35/layer_norm_v4_two_pass.h`（key 300 族） | `binaryAddQuotient` 取不超过 rowSize 的 2 次幂，`binaryAddK`/`binaryAddLastNum` 描述按 VL 分段的 `vcadd` 归并层级，降低长轴逐元素累加的误差与耗时 |
| Parallel Welford 在线算法 | `arch35/layer_norm_v4_welford.h:126-186`、`docs/ParallelWelford_and_BinaryAccumulation_LayerNormV4.md` | 单遍扫描同时维护 mean 与 M2，避免 `E[x²]-E[x]²` 的灾难性抵消；`WelfordUpdate` 按 tileLength 分段，`WelfordFinalize` 合并，再 `Normalize` |
| TwoPassPerf 极致性能路径 | `arch35/layer_norm_v4_two_pass_perf.h` | 以寄存器驻留与少量 temp 换取吞吐，要求 rowAlign 与 colSize 不触发联锁阈值 |
| regbase 寻址 | `arch35/*` + `KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY)` | A5 上仅用 AIV，数据经寄存器中转，减少 UB 往返 |
| 双缓冲 | `layer_norm_v4_welford.h:60-72`（`WELFORD_DOUBLE_BUFFER=2`）、`layer_norm_v4_two_pass*.h` | x/y、mean/rstd、gamma/beta 均按 2 份计容量，实现搬运与计算重叠 |
| 对齐搬运用 Pad | 各 kernel 的 `DataCopyPad`/`DataCopyExtParams` | 非对齐尾块用 pad 参数搬运，避免逐元素循环 |
| mean/rstd 向量化输出 | `layer_norm_v4_welford.h:186-232`、`layer_norm_v4_apt.h` | mean/rstd 在 UB 内先 cast 到目标宽度再 `DataCopyPad` 写出，并带 cache 刷新 |
| 融合维度减少索引开销 | `layer_norm_v4_tiling_base.cpp:159-167` | 把 `[A1..Ai]` 融合成 colSize、`[R1..Rj]` 融合成 rowSize，kernel 内只处理二维下标 |

未做的声明：本次分析未在任何设备上运行，未取得性能测量数据，因此不宣称任何具体加速比。

## 6. 模板与用例覆盖映射

触发条件均按外部可见参数（x shape、normalized_shape、dtype、epsilon、impl_mode）表达；case_id 对应 cases.yaml。状态：**静态推断**（依据源码条件手工推导，未运行）。

| 目标芯片 | 内部模板 / 分支 | 源码依据 | 完整外部触发条件 | case_id | 验证状态 |
|---|---|---|---|---|---|
| A3 | Transpose（200） | `layer_norm_v4_transpose_tiling.cpp:54-95` | fp32，rowSize=20 ≤64 且 ≠rowAlign(24) | 4 | 静态推断 |
| A3 | Transpose（211） | 同上 | fp16，rowSize=20 | 5 | 静态推断 |
| A3 | Transpose（222） | 同上 | bf16，rowSize=20 | 6 | 静态推断 |
| A3 | Transpose（222） | 同上 | bf16，rowSize=8（norm=[2,2,2]），≠rowAlign(16) | 18 | 静态推断 |
| A3 | SingleRead（122） | `layer_norm_v4_single_read_tiling.cpp:27-51` | bf16 且 param 为 bf16，rowSize=1024 | 7 | 静态推断 |
| A3 | SingleRead（122） | 同上 | bf16 且 param 为 bf16，rowSize=4096 | 8 | 静态推断 |
| A3 | MergeN + AlignLimit（1600） | `layer_norm_v4_merge_n_tiling.cpp:51-68` | bf16 输入 + fp32 gamma/beta（key 末位取 param dtype = F32 → 0），rowSize=88 ≤1280，nRow=ceil(10656/核数)>2 | 10 | 静态推断 |
| A3 | MergeN 基础族（601） | 同上 | fp16，rowSize=2000 >1280 且 <rowMax，nRow>2 | 11 | 静态推断 |
| A3 | MergeN + AlignLimit（1600） | 同上 | fp32，rowSize=1280（取等号进 ≤1280 分支），colSize=1024，nRow>2 | 9 | 静态推断 |
| A3 | MergeN + AlignLimit（1600） | 同上 | fp32，rowSize=768 ≤1280，colSize=8192，nRow>2 | 15 | 静态推断 |
| A3 | MergeN + AlignLimit（1601） | 同上 | fp16，rowSize=32（=rowAlign，转置条件不成立），colSize=512，nRow>2 | 20 | 静态推断 |
| A3 | Transpose（200） | `layer_norm_v4_transpose_tiling.cpp:59` | fp32，rowSize=1（norm=[1]）≤64 且 ≠rowAlign(8)，先于 MergeN 命中 | 12 | 静态推断 |
| A3 | MergeN + AlignLimit（1601） | 同上 | fp16，rowSize=1024（impl_mode=1 只改 aclnn 侧策略，V4 路径不变），colSize=1024 | 17 | 静态推断 |
| A3 | MergeN + AlignLimit（1601） | 同上 | fp16，rowSize=512（impl_mode=2 仅对 fp16 合法），colSize=256 | 16 | 静态推断 |
| A3 | Common（700） | 同上 + `layer_norm_v4_common_tiling.cpp:35-49` | fp32，rowSize=1280，colSize=77：`nRow=ceil(77/AIV核数)`，A3 的 AIV 核数为 40/48 时为 2，不满足 MergeN 的 `nRow>2`，回落 Common | 1 | 静态推断 |
| A3 | Common（702） | `layer_norm_v4_common_tiling.cpp:35-49` | bf16，rowSize=40960 > rowMax，不满足 SingleRead/MergeN | 3 | 静态推断 |
| A3 | Common（701） | 同上 | fp16，rowSize=2000，nRow=2 不 >2 | 2 | 静态推断 |
| A3 | Common（700） | 同上 | fp32，rowSize=20000，colSize=1 不 >2 | 13 | 静态推断 |
| A3 | Common（700） | 同上 | fp16 输入但 gamma/beta 均省略，paramDtype 回落 FLOAT（key 末位 0）；rowSize=23308，colSize=6，nRow≤2 不满足 MergeN | 14 | 静态推断 |
| A3 | Common（701） | 同上 | fp16，rowSize=57600（8 维全归一化），nRow=1 | 19 | 静态推断 |
| A5 | RegBaseTwoPass（310/320/…） | `layer_norm_v4_regbase_two_pass_tiling.cpp:45-98` | isRegBase 且能放下至少 1 行；受其优先级(200)先于 Welford(4000) 影响 | 4,5,6,18（小 rowSize）等 | 静态推断 |
| A5 | RegBaseTwoPassPerf（5xx） | `layer_norm_v4_regbase_two_pass_perf_tiling.cpp:56-77` | isRegBase，rowAlign ≤ 16384，非(colSize≥4096 且 rowAlign≥8192)，单行放得下 | 9,11,17,20,1,15 等 | 静态推断 |
| A5 | Welford（4xx） | `layer_norm_v4_welford_tiling.cpp:26-28` | isRegBase 且前两者 IsCapable 返回 false（长 rowSize / UB 装不下） | 3,7,8,13,14,19 等 | 静态推断 |
| A5 | memory/regbase AIV-only | `layer_norm_v4_apt.h:91-94` | 全部 A5 用例 | 全部 | 静态推断 |

说明：
- A3 分支的模板判定依据 `isRegBase=false`、`isAscend310P=false`、`isV3=false`，上述组合可静态推出；A5 的三个 regbase 模板之间是“先到先得”，最终落到哪个取决于运行期核数与 UB，故只列为候选。
- `impl_mode` 在 aclnn 层只对非 V4 设备生效（`op_host/op_api/aclnn_layer_norm.cpp:430-497`：`forwardV4Compute` 为真时走 `LayerNormV4`，不传 implMode；为假时才走 `LayerNormV3WithImplMode`）。因此 case 16/17 在 A3/A5 上不会改变 kernel 选择，只作为接口级分支保留；这一点在需求中表现为“只影响精度、不改数学定义”。
- 未覆盖：`rowSize` 恰为 1024/4096 但 param 为 FLOAT 的 SingleRead（120）分支、`rowSize > 1280` 且 bf16 参数的 MergeN 基础族（602），均因 20 个用例上限排除；310P/Kirin/960 配置不在目标范围。
- 不可达：MergeN 的 One 族（2600/2601/2602）要求 `rowSize == 1`，但 `rowSize=1` 必然满足 Transpose 的 `rowSize<=64 && rowSize!=rowAlign(8/16)` 且 Transpose 优先级(100)高于 MergeN(1220)，故该族在 A3 上不可达（静态推断）。`isV3` 路径同样不可达：该字段仅在 `layer_norm_v4_tiling.h:220` 声明为默认 false，`GetShapeAttrsInfo` 未赋值。
- 不可达项依据：`commonParams.isV3` 仅声明默认 false（`layer_norm_v4_tiling.h:220`），`GetShapeAttrsInfo` 未对其赋值，故 MergeN/Common 中的 `isV3` 判断恒不成立。

## 7. 源码依据与需求决策

### 7.1 源码可确认的事实

- 输出 dtype：`y` 跟随 `x`，`mean`/`rstd` 恒为 DT_FLOAT（`layer_norm_v4_infershape.cpp:98-113`）。
- 输出 shape：`y = x.shape`；`mean`/`rstd = x.shape` 且后 `j` 维置 1（`layer_norm_v4_infershape.cpp:61-92`）。
- 可选输入为空时按全 1/全 0 处理（`docs/aclnnLayerNorm&aclnnLayerNormWithImplMode.md` 使用说明；aclnn 侧 `op_api/aclnn_layer_norm.cpp:437-462` 在非 V4 设备上显式 `Fill` 构造）。
- `epsilon` 默认 1e-5（`layer_norm_v4_def.cpp:58`）。
- gamma/beta 可独立为空（`layer_norm_v4_tiling_base.cpp:116-124`）。
- `impl_mode` 合法值 0/1/2，2 要求全部输入 FLOAT16（`op_api/aclnn_layer_norm.cpp:270-288`）。

### 7.2 基于代码的推断

- 归约为总体方差：kernel 用 `Σx/N` 与 `Σx²/N` 组合（如 `layer_norm_v4_single_read.h:154-208`），无 N-1 修正，与 `torch.nn.LayerNorm` 一致。
- fp16/bf16 计算路径升 fp32：kernel 中 `Cast(... CAST_NONE ...)` 到 float 后计算再转回（各 kernel 的 "cast xLocal to float" / "cast xLocal to Tfm" 段）。
- `rowAlign` 决定 UB 预算，因此 rowSize 是否 32B 对齐是显著的性能分界。

### 7.3 AI 自行确定的需求规则（需求决策，非源码事实）

| 编号 | 规则 | 依据与来源歧义 | 对产物的影响 |
|---|---|---|---|
| D1 | `mean`/`rstd` dtype 固定 FLOAT32 | 接口文档允许 FLOAT32/FLOAT16/BFLOAT16，但 OpDef 与 infershape 固定 FLOAT32，接口文档与 IR 定义存在歧义 | golden 恒返回 fp32 统计量；用例 dtype 列不出现其他 dtype |
| D2 | 低精度输入按 FLOAT32 累加统计量，`y` 转回原 dtype | 参考实现 `executor_aclnnLayerNorm_noFunctional.py:30-35` 只在 CPU 上做此转换，GPU/NPU 上直接调用 `torch.nn.LayerNorm`；需求统一为始终升 fp32 | golden 统一升 fp32；精度阈值可按标准表判定 |
| D3 | gamma/beta 独立省略且等价全 1/全 0 | 接口文档明确“内部构造”，但算子定义文档未在公式层面展开 | golden 用 None 表示恒等；用例覆盖全给/仅 gamma/仅 beta/都不给 |
| D4 | `impl_mode` 不改变数学定义与输出规范 | 接口文档只承诺“策略选择”，V4 路径实际不透传该参数 | golden 签名保留 `impl_mode` 但语义不变；用例中作为 attrs 出现 |
| D5 | impl_mode=1/2 的精度阈值放宽为 8 倍 | 文档称“有精度损失”“精度最低”但未量化 | 判据写法写入 desc.md 第 4 节；其他用例仍按标准表 |
| D6 | 总体方差 | 文档公式写 `Var = E[x²] - E[x]²`，与 `torch.nn.LayerNorm` 的总体方差一致 | golden 用 `mean` 后平方再平均 |
| D7 | 允许极小 epsilon（如 1e-20） | 现有 ST 用例 `LayerNormV4_st_103` 已使用 1e-20 | 用例 14 采用 1e-20 |

### 7.4 未验证与未执行

- 全部 20 个用例均未在设备上运行，`design.md` 中的模板归属为静态推断，未经实测确认。
- 未做性能测量；文中性能相关的描述均来自源码结构与随仓文档，不代表实测加速。
- A5 三模板的最终落点依赖运行期核数/UB 实测值（950DT 标称 UB 248KB、AIV 核数按型号 16/56/64/72 不等），未在本机取实测 tiling 日志核对。
