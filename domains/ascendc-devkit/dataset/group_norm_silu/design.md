# GroupNormSilu 内部设计文档

> 本文档记录源码内部实现分析，**不得**回写进 `desc.md` / `golden.py` / `cases.yaml` / `cases.csv`。
> 覆盖范围限定 Ascend A3（910B/910C）与 A5（950/3510）。源码基线：`/home/j00958686/ops-nn`，算子目录 `norm/group_norm_silu/`。
> 硬件参照：A5 = Ascend950DT_9582（`ub_size=253952`、`vector_core_cnt=64`、`NpuArch=3510`）。

## 1. 实现概览

### 1.1 host 侧

| 阶段 | 位置 | 作用 |
|---|---|---|
| OpDef 注册 | `op_host/group_norm_silu_def.cpp:19-150` | 三输入 `x`(必选) / `gamma`(可选) / `beta`(可选)，三输出 `y` / `mean` / `rstd`，属性 `num_groups`(必选) / `eps`(默认 1e-5) / `activate_silu`(默认 true)。`ascend910b`、`ascend910_93` 挂 `aicore_config`；`ascend950`、`ascend960dt`、`ascend350` 挂 `regbase_config`（`opFile.value = group_norm_silu_apt`）。 |
| InferShape | `op_host/group_norm_silu_infershape.cpp:30-48` | `y.shape = x.shape`；`mean/rstd.shape = [x.shape[0], num_groups]`。 |
| InferDataType | 同上 `:58-108` | `y.dtype = x.dtype`。A5（`short_soc_version == "Ascend950"`）上 `mean/rstd` 取 gamma/beta 的 dtype（二者皆在时要求相同），都缺省时取 `x.dtype`；非 A5 一律取 `x.dtype`。 |
| Tiling 入口 | `op_host/group_norm_silu_tiling.cpp:431-432` | `compileInfo->isRegbase == 1` 时转 `Tiling4GroupNormSiluRegBase`（arch35），否则走本文 1.2 的经典路径。`isRegbase` 由 `IsRegbaseSocVersion` 判定（`tiling.cpp:197-198`）。 |
| TilingPrepare | `tiling.cpp:183-222` | 缓存 `totalCoreNum`(AIV 核数)、`ubSizePlatForm`；regbase 额外缓存 `vectorLength`(`GetVRegSize`) 与 `blockSizePlatform`。全部动态取，无硬编码。 |

### 1.2 经典路径（A2/A3）数据流

```
SetAttrParams → SetTilingParams → SetBlockTiling → SetTiling(key) → SetUbTiling
   ↑ numGroups/epsilon/activateSilu   ↑ hwNum/shapeC/shapeD/elemNum
```

```
x ──MTE2──> UB ──V: Σx, Σx²──> mean = Σx/n, rstd = 1/sqrt(Σx²/n − mean² + eps)
                                    │
                                    └─ V: (x−mean)*rstd*γ+β ─> SiLU ─> y ──MTE3──> gm
                                    └─ mean/rstd ──MTE3──> gm
```

经典路径为**一遍流式**：同时累加 `Σx` 与 `Σx²`，用 `E[x²] − E[x]²` 求方差。

### 1.3 arch35 路径（A5）数据流

```
x 全载 ──> 两趟法（two-pass）：第一趟求 mean/var，第二趟归一化 ─> SiLU ─> y
x 部分载入 ─> Welford 在线算法：逐块更新 (count, mean, M2) ─> 收尾 ─> 归一化 ─> SiLU ─> y
```

两条路径最终都用二分累加树（dichotomy-add）完成归约收尾。

### 1.4 kernel 分发

| 入口文件 | 适用 SoC | 分发方式 |
|---|---|---|
| `op_kernel/group_norm_silu.cpp:43-95` | A2/A3 | `TILING_KEY_IS` 匹配 1011/1012/102/1031/1032/104/1051/1052/106/1071/1072/108/109 |
| `op_kernel/group_norm_silu_apt.cpp:25-86` | A5 | `TILING_KEY_IS` 匹配 1000/1001/1100/1101/1110/1111/1120/1121/1130/1131；`g_coreType == AIC` 直接 return（纯 AIV 算子） |

## 2. 模板设计

### 2.1 A3：`GroupNormSiluTilingKey`（`op_host/group_norm_silu_tiling.h:98-122`）

选择逻辑在 `tiling.cpp:337-376::SetTiling`，`hwNum` 为空间维乘积、`shapeC` 为 C、`numPerCore` 为每核组数。

| tiling key | 模板类（kernel 文件） | 选择条件（按顺序命中即止） | 计算流程要点 |
|---|---|---|---|
| 1071 / 1072 / 108 | `KernelGroupNormSiluHWOne`（`hw1_b16.h` / `hw1_b32.h`） | `hwNum < 32/dtypeSize` 且 `hwNum == 1` | 每核处理若干组；`numGroups == shapeC` 时走「每组 1 元素」快速路径：`y = silu(beta)`、`mean = x`、`rstd = 1/sqrt(eps)`，无归约 |
| 1051 / 1052 / 106 | `KernelGroupNormSiluG`（`g16.h` / `g32.h`） | `hwNum < 32/dtypeSize` 且 `hwNum != 1`（或 `shapeD` 也过小） | 归一化维极短，归约退化为逐元素；gamma/beta 单元素搬入 |
| 102 | `KernelGroupNormSiluSmallB32`（`small_b32.h`） | fp32 且 `hwNum % 8 == 0`、`hwNum <= 4096`、`shapeC + numPerCore <= 4000` | 受约束的「小 shape 高性能」：`outQueueSilu` 复用为 x² 暂存 |
| 104 | `KernelGroupNormSiluB32`（`b32.h`） | fp32 且 `shapeC + numPerCore <= 4000`，但不满足上一行 | 同款小 shape 优化但不要求 hw 对齐 |
| 1011 / 1012 | `KernelGroupNormSiluSmallB16`（`small_b16.h`） | fp16 且 `hwNum % 16 == 0`、`hwNum <= 4096`、`shapeC + numPerCore <= 2700` | fp32 归约 + 融合 normalize/silu/cast |
| 1031 / 1032 | `KernelGroupNormSiluHighPerf`（`b16.h`） | fp16 且 `shapeC + numPerCore <= 2700`，但不满足上一行 | 同上，放宽 hw 对齐要求 |
| 1011→通用 / 1031→通用 | `KernelGroupNormSiluBasic`（`b16.h` / `b32.h` 对应分支） | 上述条件都不满足（`shapeC + numPerCore` 超阈值） | 分块循环处理归约维 |
| 109 | `KernelGroupNormSiluSD`（`sd.h`） | **310P only**：`shapeN == 1`、fp16、`hwNum > 1`、`numGroups == 32` | 特殊尾核分布（前 `numLastCore` 核多分 1 组） |

- **x 类型 → key 后缀**：`1011/1031/1051/1071` 为 `x`、`gamma` 同 dtype（b16）；`1012/1032/1052/1072` 为 `gamma` 为 float32 的混合精度（MixType）；`102/104/106/108` 为 x 即 float32。
- 305 行 `Lcm`/`CeilDiv` 对齐、`GAMMA_BETA_UB_NUM=6`、`INPUT_OUTPUT_UB_NUM=20`、`RESERVED_BLOCK_NUM=2` 是 UB 预算常量（`tiling.cpp:35-41`）。

### 2.2 A5：`TILINGKEY_*`（1000–1131）

选择逻辑在 `op_host/group_norm_silu_tiling_arch35.cpp:349-476::SetTilingKey4Regbase`，核心变量：
- `reduceCount = shapeD * hwNum`（每个归约集合的元素数）
- `maxReduceCount = (ubRemain / (DOUBLE_BUFFER * BUFFER_NUM)) / xDtypeSize`（UB 能容下的归约元素数）
- `mixType`：`x` 与 `gamma`/`beta` 的 dtype 不同即为混合精度（`:280-303::isMixType`）

| tiling key | 模板类 | 选择条件（按顺序） | 要点 |
|---|---|---|---|
| 1000 / 1001 | `RegbaseEmptyTensor` | `xShapeSize == 0`（`:379-385`） | 只写 mean/rstd，无数据计算 |
| 1110 / 1111 | `GroupNormSiluTwoPass`（`regbase_two_pass.h`） | `maxReduceCount > reduceCount`（R 轴可全载） | 全载 + 两趟法 + 二分累加树；8 个显式 event id 做 MFU ping-pong |
| 1130 / 1131 | `GroupNormSiluTwoPassGeneralized` | 大通道（`shapeC > 4096`）或 `reduceCount <= vectorLength/4` 且限制 gamma/beta 为 `shapeD` 后 R 可全载（`:439-457`） | R 全载但 gamma/beta 逐组重搬 |
| 1120 / 1121 | `GroupNormSiluWelfordGeneralized` | 大通道且 R 不可全载（`:461-466`） | Welford 在线 + 不 fold gamma/beta |
| 1100 / 1101 | `GroupNormSiluWelford` | R 不可全载且非大通道 | Welford 在线；phase-1 与 phase-2 复用同一块 UB 区域 |

- 奇数后缀（xxxx1）为 MixType，偶数后缀（xxxx0）为 b16/fp32 同精度。
- `NDDMA_MAX_SIZE = 32`：`hwNum <= 32` 时尝试用 NDDMA 搬 gamma/beta，腾出 UB 后**重新尝试**全载模板（`:411-426`）。

## 3. 分核设计

### 3.1 A3 / A5 共用的并行模型

```
totalGroups = shapeN * numGroups                       # 把 (n, g) 展平
numPerCore  = CeilDiv(totalGroups, totalCoreNum)
realCoreNum = CeilDiv(totalGroups, numPerCore)
numLastCore = totalGroups - numPerCore * (realCoreNum - 1)
SetBlockDim(realCoreNum)
```

- 并行维度是 **(n, g) 组**，不是行也不是通道；每组独立归约，**无跨核归约、无原子累加、无 workspace 合并**。
- 尾核负载不均：最后一个核少跑 `numPerCore - numLastCore` 组；A3 的 `sd.h` 反而把多出的组给**前** `numLastCore` 个核（`sd.h:104-116`）。
- A5 每核内部再按 `MAX_NUM_PER_CORE = 2048` 组切块循环（`arch35_tiling.cpp:361`）。
- 特殊收缩（A3，`tiling.cpp:267-284`）：`hwNum < 32/dtypeSize` 且非「hw=1 且 shapeD 足够」时强制 `realCoreNum = 1`，避免极短归约下分核得不偿失；`hwNum == 1 && numGroups == shapeC` 时改为按 N 分核。

### 3.2 A5 的 UB 预算

```
otherUbSize = gammaUb + betaUb + meanUb + rstdUb (+ mean/rstd 的 b16 中转缓冲) + dichotomyAddExtra
ubRemain    = ubSize - otherUbSize
maxReduceCount = ubRemain / (DOUBLE_BUFFER * BUFFER_NUM) / xDtypeSize
```
`DOUBLE_BUFFER = 2`、`BUFFER_NUM = 2`，即 x 的 UB 侧按 4 份预算。`MAX_CHANNEL_SIZE = 4096` 是「大通道」分界。

## 4. 分块设计

| 维度 | A3 | A5 |
|---|---|---|
| 核内循环 | `loopNum/loopTail`（按 `elemNum` 与 `processSize`）、`innerLoopNum/innerLoopTail`（按 `hwNum` 与 `processSize`）——`tiling.cpp:319-325` | `innerNumPerCore = 2048` 组一批；R 轴按 `parallelN`/`processSize` 切 |
| 块大小 | `processSize` 默认 8192（Kirin 5120），`sd` 路径按剩余 UB 重算（`tiling.cpp:369-393`） | `processSize` 由 UB 余额推导 |
| 对齐 | 32B `BLOCK_SIZE`；fp32 reduce 的 `mask = 64`；非对齐尾块用 `DataCopyPad`（220/3003/3113）或 32B 重叠重算 | 32B `BLOCK_SIZE`、`FP32_ONE_REPEAT = 64`、`VL_FP32 = VECTOR_REG_WIDTH/4`，全部 GM 访问走 `DataCopyPad` |
| 尾块 | `loopTail` / `innerLoopTail` 显式记录；`b16.h:398-425`、`b32.h:357-385` 用重叠重算保精度 | `parallelNAlign` 对齐后尾块单独处理 |

- UB 预算常量（A3）：`GAMMA_BETA_UB_NUM = 6`、`INPUT_OUTPUT_UB_NUM = 20`、`RESERVED_BLOCK_NUM = 2`（`tiling.cpp:39-41`），含义是 gamma/beta 占 6 份、输入输出占 20 份、预留 2 个 block。
- A5 的 `mean`/`rstd` 若输出为低精度，额外分配 `meanUbExtraSize`/`rstdUbExtraSize` 做中转（`arch35_tiling.cpp:369-376`）。

## 5. 性能调优技巧

| 技巧 | 位置 | 适用条件 | 取舍 |
|---|---|---|---|
| 双缓冲 / 多缓冲 | `small_b16.h:53`、A5 `BUFFER_NUM=2` | 常规路径 | 占用 2 份 UB 换流水重叠 |
| 融合 normalize + SiLU + Cast | `small_b16.h:216`、`b16.h:358-387` | 所有路径 | 一次搬出，省一趟访存 |
| 一遍流式求 Σx / Σx² | `small_b16.h:210-215` | A3 全部路径 | 只读一次 x；但 `E[x²]−E[x]²` 在均值远大于方差时有相消风险 |
| Welford 在线算法 | `arch35/group_norm_silu_regbase_welford.h:129` → `regbase_base.h:297` | A5，R 不可全载 | 数值稳定，但每块要更新 (count, mean, M2)，算力换精度 |
| 两趟法（two-pass） | `regbase_two_pass.h` | A5，R 可全载 | 读两遍 x，换取与现代价数值精度 |
| 二分累加树 | `regbase_base.h:149-170, 1068-1122` | A5 全部归约收尾 | 降低长归约的累加误差 |
| NDDMA 搬 gamma/beta | `regbase_base.h:1578-1597` | `hwNum <= 32` 或有可选输入 | 腾出 UB 让部分用例升级到全载模板 |
| UB 区域复用 | `welford.h:370-380`（phase-1/phase-2 重叠）、`small_b32.h:286-310`（y 队列当 x² 暂存） | 对应模板 | 省 UB；实现上更易出错 |
| 快速路径（每组 1 元素） | `hw1_b16.h:204-281`、`hw1_b32.h:137-160` | `hwNum == 1 && numGroups == shapeC` | 跳过全部归约，直接 `y=silu(beta)` |
| 纯 AIV 下发 | `group_norm_silu.cpp:30-31`、`_apt.cpp:40-42` | 全部 | 不占 cube 核 |
| DataCopyPad | `base.h:61-98` | 架构 220 / 3003 / 3113 | 非对齐尾块免重算 |

## 6. 模板与测试覆盖映射

测试用例的外部命名与描述均不暴露下述内部标识；本表仅用于内部核对。

| 目标芯片 | 内部模板/分支 | 源码依据 | 完整外部触发条件 | case_id | 验证状态 |
|---|---|---|---|---|---|
| A5 | TwoPass（1110/1111） | `arch35_tiling.cpp:404-410` | fp16/bf16/fp32，N=2、C=64、HW=256、group=8 → reduceCount=2048 可全载 | 1,2,3,4,5,6,16,17 | 静态推断 |
| A5 | TwoPass（全载） | 同上 | bf16，N=8、C=128、HW=256、group=16 | 9 | 静态推断 |
| A5 | TwoPass（全载） | 同上 | fp16，N=2、C=32、HW=4096、group=8 | 19 | 静态推断 |
| A5 | Welford（1100/1101） | `arch35_tiling.cpp:468-475` | fp16，N=1、C=32、HW=200000、group=32 → reduceCount=200000 不可全载 | 10 | 静态推断 |
| A5 | Welford | 同上 | fp32，N=1、C=64、HW=131072、group=64 | 11 | 静态推断 |
| A5 | Welford | 同上 | fp16+fp32 gamma，N=2、C=32、HW=65536、group=8（MixType） | 12 | 静态推断 |
| A5 | Welford | 同上 | bf16，N=1、C=128、HW=65536、group=32 | 18 | 静态推断 |
| A5 | WelfordGeneralized（1120/1121）或 Welford | `arch35_tiling.cpp:461-466` | fp16，C=8192 > MAX_CHANNEL_SIZE=4096 且 R 不可全载 | 13 | 静态推断 |
| A5 | WelfordGeneralized | 同上 | fp16，C=65536、group=65536（每组 1 通道）、HW=64 | 14 | 静态推断 |
| A5 | TwoPassGeneralized（1130/1131）或 Welford | `arch35_tiling.cpp:439-457` | fp32，C=128 > 4096?（否）但 reduceCount=131072 不可全载 → 落 Welford | 20 | 静态推断 |
| A5 | TwoPass（全载）+ 核数打满 | `arch35_tiling.cpp:725-729` | fp16，N=512、C=64、group=8 → totalGroups=4096，远超 64 核 | 15 | 静态推断 |
| A5 | hw=1 快速路径（Host 端无专门 key，由 R 极短自然落入 Welford） | `hw1_b16.h:204-281` 为 A3 路径 | fp16，N=64、C=32、HW=1、group=8 → 每组 4 元素 | 7 | 静态推断（A3 专属模板，A5 不适用） |
| A5 | 同上 | 同上 | fp16，N=64、C=32、HW=1、group=32 → 每组 1 元素 | 8 | 静态推断（A3 专属模板，A5 不适用） |
| A3 | SmallB16 / SmallB32 / HWOne / G / B16 / B32 | `tiling.cpp:337-376` | 与上述 case 相同的外部条件（A3 的另一套 key 体系） | 全部 | 未覆盖（本轮无 A3 设备） |
| A3/A5 | SD（109） | `tiling.cpp:395-425` | 310P 专属 | — | 不适用 |
| A3/A5 | EmptyTensor（1000/1001） | `arch35_tiling.cpp:379-385` | x 元素个数为 0 | — | 未覆盖（desc.md D3 声明支持但非必测） |

**覆盖取舍说明**：
1. 20 个用例优先覆盖「归约集合能否装入 UB」这条主分界线（全载 → TwoPass；不可全载 → Welford），它是 A5 上影响最大、分支最深的决策点。
2. dtype 组合覆盖 fp16 / bf16 / fp32 单精度 + fp16/bf16×fp32 两种混合精度。
3. `gamma`/`beta` 省略组合覆盖「都省略」「仅 gamma」两种；「仅 beta」与「都省略」在 dtype 推导上等价，故未单列。
4. A3 的 6 个模板因本轮无 A3 设备无法实测，映射状态标记为「未覆盖」，不宣称已验证。
5. `activate_silu` 属性固定为默认 true，未覆盖 false 分支（该分支只改变最后一次逐元素运算，不影响本需求第 2 节的输出定义）。

## 7. 源码依据与需求决策

### 7.1 可从源码确认的事实

| 结论 | 位置 |
|---|---|
| `y.shape = x.shape`，`mean/rstd.shape = [N, num_groups]` | `group_norm_silu_infershape.cpp:42-47` |
| 非 A5 时 `mean/rstd.dtype = x.dtype`；A5 时取 gamma/beta dtype，都缺省取 x | `group_norm_silu_infershape.cpp:79-104` |
| gamma/beta 必须为 1 维且长度等于 C | `tiling.cpp:104-119`、`arch35_tiling.cpp:127-145` |
| `num_groups > 0` 且 `C % num_groups == 0` | `arch35_tiling.cpp:231-245` |
| gamma/beta 同时存在时 dtype 必须同 size | `arch35_tiling.cpp:120-127` |
| 混合精度只允许「x 为 fp16/bf16 且 gamma/beta 为 fp32」 | `arch35_tiling.cpp:262-277` |
| 经典路径用 `Σx`/`Σx²` 一遍求方差 | `small_b16.h:210-215` |
| A5 用 two-pass 或 Welford | `regbase_two_pass.h`、`regbase_welford.h` |
| SiLU 为 `z/(1+exp(-z))` | `b16.h:358-387`、`base.h:1235-1238` |
| 并行维度为展平的 `(n, g)` 组，无跨核归约 | `tiling.cpp:264-276`、`arch35_tiling.cpp:724-730` |

### 7.2 需求决策

| 编号 | 决策 | 来源冲突/歧义 | 处理 |
|---|---|---|---|
| D1 | `mean`/`rstd` dtype 依次取 gamma → beta → x | 接口文档写「与 self 保持一致」，A5 章节又补充「与 gamma/beta 相同」；两处不完全一致 | 统一为按优先级推导，覆盖两种表述；纯低精度调用行为不变 |
| D2 | 低精度输入统计量按不低于 fp32 累加 | 源码经典路径确实用 fp32 accumulator，但 A5 的 Welford 各模板写法不同 | 采用对所有路径都成立的表述 |
| D3 | 空张量属支持域，但统计量数值不做约束 | 接口文档未定义空输入下 mean/rstd 的取值；A5 有 `regbase_empty_tensor.h` 会写值，但未说明语义 | 声明支持但不约束数值，且不作必测 |
| D4 | 不引入绝对误差兜底 | desc 引用的生态标准只有 MERE/MARE；`y` 在 `x≈mean` 处存在相消放大 | 保持判据单一；区分「相消」与「缺陷」的方法写入第 4 节 |
| D5 | `z = (x-mean)*rstd` 后再乘 gamma 加 beta，无中间低精度舍入 | 源码部分路径先算 `scale = rstd*gamma`、`bias = -scale*mean+beta`（`b32.h`、`small_b32.h`），数学等价但舍入顺序不同 | 以数学定义为准；两种写法在阈值内均可通过 |

### 7.3 未执行的验证

- 本轮**未做任何真机运行**。上表覆盖映射中的「静态推断」全部来自代码阅读，未用运行日志佐证。
- 未验证项：A3 的 6 个模板、空张量路径、`activate_silu=false` 分支。
- 未做性能测量，因此本文档不宣称任何具体加速比。
