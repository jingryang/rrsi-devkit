# AdaptiveMaxPool3d 算子设计分析（A5）

## 1. 芯片范围与源码布局

### 1.1 芯片范围声明

- 本次芯片种类：**A5**（Ascend 950PR/950DT、3510），默认值，用户未显式覆盖。
- 实际使用的分析范围：
  - arch 目录：`arch35`（A5 的 tiling 与 kernel 实现均在此）；
  - config 目录：`op_host/config/ascend950/`、`op_host/config/ascend350/`；
  - 文档支持行：`docs/aclnnAdaptiveMaxPool3d.md` 的 "Ascend 950PR&950DT系列产品：支持"；
  - kernel 入口：`op_kernel/adaptive_max_pool3d_apt.cpp`（`ExtendCfgInfo("opFile.value", "adaptive_max_pool3d_apt")`，仅在 `ascend950` / `ascend350` 配置下生效）。
- 被排除的芯片与目录（仅记录，不进入 golden / cases / desc / design 结论）：
  - `op_host/config/ascend910b/`、`op_host/config/ascend910_93/`（A3/A2），以及 `op_host/adaptive_max_pool3d_small_pool_tiling.cpp`、`adaptive_max_pool3d_big_pool_tiling.cpp`、`op_kernel/adaptive_max_pool3d.cpp`、`adaptive_max_pool3d_small_pool.h`、`adaptive_max_pool3d_big_pool.h`、`pool_3d_common/arch22/`：这些是 arch22 路径，A5 不会选中（原因见 §3.1，A5 的 arch 闸门会把 arch35 模板全部走完，Simt 模板 `IsCapable()` 恒真，priority 3/4 的 arch22 模板不可达）。
  - `op_host/config/kirin9030/`、`op_host/config/kirinx90/`、`_def.cpp` 中的 `GetKirinCoreConfig()`：Kirin 系列，范围外。
  - 文档中 "Atlas A3/A2 系列" 支持行、`indicesOut` 在 A3/A2 不支持 INT64 的约束行：范围外。
  - `__NPU_ARCH__ == 3003 || __NPU_ARCH__ == 3113` 分支（`op_kernel/adaptive_max_pool3d.cpp` 中 fp16/bf16 的编译期排除）：范围外。
- 共享公共头（`op_kernel` 引用的 `adaptive_pool3d_common/op_kernel/arch35/*`、`pool_utils/arch35/*`）只采纳对 A5 生效的分支。

### 1.2 源码布局

| 内容 | 实际路径 | 说明 |
|---|---|---|
| 接口文档 | `docs/aclnnAdaptiveMaxPool3d.md` | 唯一候选，精确匹配 `aclnnAdaptiveMaxPool3d` |
| 算子定义 | `op_host/adaptive_max_pool3d_def.cpp` | `class AdaptiveMaxPool3d : public OpDef`、`OP_ADD(AdaptiveMaxPool3d)` |
| 图原型 | `op_graph/adaptive_max_pool3d_proto.h` | `REG_OP(AdaptiveMaxPool3d)`，`output_size` REQUIRED ListInt、`indices_dtype` Int 默认 3 |
| shape/dtype 推导 | `op_host/adaptive_max_pool3d_infershape.cpp` | `InferShape4AdaptiveMaxPool3d` / `InferDtype4AdaptiveMaxPool3d` |
| aclnn 实现 | `op_api/aclnn_adaptive_max_pool3d.cpp`、`op_api/aclnn_adaptive_max_pool3d.h` | 位于算子根 `op_api/`（非 `op_host/op_api/`） |
| l0 op 封装 | `op_api/adaptive_max_pool3d.cpp`、`op_api/adaptive_max_pool3d.h` | `l0op::AdaptiveMaxPool3d`，regbase 下多传 `indicesDtype` |
| tiling（A5） | `adaptive_pool3d_common/op_host/arch35/adaptive_max_pool3d_{para,big_kernel,simt}_tiling.cpp`、`adaptive_pool3d_tiling.cpp` | arch35 |
| tiling（A3） | `op_host/adaptive_max_pool3d_{small,big}_pool_tiling.cpp` | arch22，范围外 |
| kernel（A5） | `op_kernel/adaptive_max_pool3d_apt.cpp` → `adaptive_pool3d_common/op_kernel/arch35/adaptive_max_pool3d_{parall_pool,big_kernel,simt}.h` | 按 tiling key 分发 |
| kernel（A3） | `op_kernel/adaptive_max_pool3d.cpp` + `*_small_pool.h` / `*_big_pool.h` | arch22，范围外 |
| golden | `tests/assets/golden.py` | `__golden__ = {"kernel": ..., "aclnn": ...}` |
| 用例种子 | `tests/st/arch35/ttk_aclnn_adaptive_max_pool3d_st.csv`、`tests/st/aclnnAdaptiveMaxPool3d/atk_*.json`、`executor_*.py` | 见 §8.4 |

`ops_snake = adaptive_max_pool3d`（目录名），`ops_pascal = AdaptiveMaxPool3d`（与 `OP_ADD(AdaptiveMaxPool3d)`、`REG_OP(AdaptiveMaxPool3d)` 一致，无需修正）。

### 1.3 文档版本选择

- 候选收集：`docs/` 下只有 `aclnnAdaptiveMaxPool3d.md`。
- 排除候选：`README.md`（背景/约束说明，非接口文档，仅用于补充 "D*H*W 不得超 int32" 一类约束）。
- 反向确认：
  1. `op_api/aclnn_adaptive_max_pool3d.h` 中接口名为 `aclnnAdaptiveMaxPool3dGetWorkspaceSize`，与文档一致；
  2. `examples/test_aclnn_adaptive_max_pool3d.cpp` 与文档调用示例使用同一接口；
  3. `tests/st/aclnnAdaptiveMaxPool3d/executor_aclnnAdaptiveMaxPool3d.py` 的 `get_format` 返回 `ACL_FORMAT_NCDHW`，`atk_*.json` 的 `aclnn_name = "AdaptiveMaxPool3d"`；
  4. `_def.cpp` 与 `op_graph/*_proto.h` 未出现 `.Version(N)` 或多版本属性。
- 结论：采用 `docs/aclnnAdaptiveMaxPool3d.md`，aclnn 接口映射为 `aclnnAdaptiveMaxPool3d`（无 V2/V3 变体）。

### 1.4 aclnn 接口映射

```Cpp
aclnnStatus aclnnAdaptiveMaxPool3dGetWorkspaceSize(
  const aclTensor   *self,       // 张量槽 0（输入）
  const aclIntArray *outputSize, // [Do, Ho, Wo]，非张量槽
  aclTensor         *outputOut,  // 张量槽 1（输出 y）
  aclTensor         *indicesOut, // 张量槽 2（输出 indices）
  uint64_t          *workspaceSize,
  aclOpExecutor     **executor)
```

- `indicesOut` 的 dtype 由张量自身决定（regbase 下 `indicesDavSupportList = {INT32, INT64}`），aclnn 头文件无 `indices_dtype` 形参；`indices_dtype` 只是图算子属性，取值 3→int32、9→int64（`InferDtype4AdaptiveMaxPool3d`）。
- `outputSize` 在 regbase（A5）下允许长度为 0、1、3；长度为 0/1 时会先归一化为 3 元组（`op_api/aclnn_adaptive_max_pool3d.cpp:411-423`）。本需求把 `output_size` 固定为长度 3 的外部契约（与 op def 的 `output_size` 完整语义一致），长度为 0/1 的入口形态不进入用例。

## 2. 实现概览

数据流（A5）：

```
aclnnAdaptiveMaxPool3dGetWorkspaceSize
  CheckParams（维度 4/5、dtype、format、outputSize 长度与取值、D*H*W ≤ INT32_MAX）
  → Contiguous(self)
  → 4D 输入时 Unsqueeze+ReFormat 成 5D NCDHW
  → SelectAdaptiveMaxPool3D：
       空间维全部整除 → l0op::MaxPool3DWithArgmaxV2Ncdhw（固定窗口路径）
       否则          → l0op::AdaptiveMaxPool3d（图算子，attributes = output_size + indices_dtype）
  → ViewCopy 回原输出张量（支持非连续输出）
```

图算子 `AdaptiveMaxPool3d` 的 host 侧入口为 `IMPL_OP_OPTILING(AdaptiveMaxPool3d).Tiling(Tiling4AdaptiveMaxPool3d)`（`op_host/adaptive_max_pool3d_tiling.cpp:142-144`），内部调用 `TilingRegistry::DoTilingImpl`，按 priority 升序尝试 tiling 模板；device 侧按 `GET_TPL_TILING_KEY(TEMPLATE_MODE, DYTPE_MODE, MULTI_MODE, FORMAT_MODE)` 分发到三个 kernel 类之一（`op_kernel/adaptive_max_pool3d_apt.cpp:32-73`）。

## 3. 模板设计

### 3.1 模板注册与可达性

`adaptive_pool3d_common/op_host/arch35/` 为 A5 注册了 3 个 tiling 模板（`REGISTER_OPS_TILING_TEMPLATE`，priority 越小越先尝试）：

| priority | 类 | 文件 | tiling key 前缀 | kernel 类 |
|---|---|---|---|---|
| 0 | `AdaptiveMaxPool3dParaPoolTiling` | `adaptive_max_pool3d_para_tiling.cpp:317` | `TPL_MODE_0` | `AdaptiveMaxPool3dParaPool<T,U>` |
| 1 | `AdaptiveMaxPool3dBigKernelTiling` | `adaptive_max_pool3d_big_kernel_tiling.cpp:143` | `TPL_MODE_1` | `AdaptivePool3dBigKernel<T>` |
| 2 | `AdaptiveMaxPool3DTilingSimt` | `adaptive_max_pool3d_simt_tiling.cpp:104` | `TPL_MODE_2` | `AdaptivePool3DSimt<T,U,F,D>` |

另有 arch22 的 `AdaptiveMaxPool3dSmallPoolTiling`(3) / `AdaptiveMaxPool3dBigPoolTiling`(4)（`op_host/`），它们与上述模板注册在同一个（非 arch 感知的）`TilingRegistry` 中，但：

- arch35 三个模板的 `GetShapeAttrsInfo()` 首先判断 `ascendcPlatform.GetCurNpuArch() != NpuArch::DAV_3510` 就返回 `GRAPH_PARAM_INVALID`（`adaptive_pool3d_tiling.cpp:107-109`），因此它们只在 A5 生效；
- `AdaptiveMaxPool3DTilingSimt::IsCapable()` 直接 `return true`（`adaptive_max_pool3d_simt_tiling.cpp:34`），所以在 A5 上前两个模板不匹配时，priority 2 必定接住，priority 3/4 不可达。

⇒ A5 的实际路由恒为：**ParaPool → BigKernel → Simt** 三级回退。

### 3.2 ParaPool（`TPL_MODE_0`）

触发条件（`IsCapable`，`adaptive_max_pool3d_para_tiling.cpp:29-58`，全部满足）：

| 条件 | 源码表达式 | 含义 |
|---|---|---|
| 窗口规模 | `kernelDMax * kernelHMax * kernelWMax < 128` | 单窗口元素数小于 128 |
| 索引可表示 | `dIn*hIn*wIn < INT32_MAX` | 索引能用 int32 表达 |
| NC 向量化 | `nIn*cIn >= vfLen/2` | NC 至少覆盖半个向量寄存器（fp32 时 vfLen=64，fp16/bf16 时 128） |
| UB 容量 | `occupyUbSize <= availableUbSize` | 见 §5.1 |

计算方式：把 NC 维度铺到向量 lane（`ncFactor = vfLen`），输入转置为 `[D,H,W,VL]`，再按 W→H→D 三段做带索引的 Select 级联归约，最后转置回 `[VL,D,H,W]` 并 cast 输出。fp32 走 `CustomSelect`，B16 走 `CustomSelectOnW`（`adaptive_max_pool3d_parall_pool.h:140-280`）。索引在 W 级由标量递增给出，H/D 级直接复用上一层索引张量。

### 3.3 BigKernel（`TPL_MODE_1`）

触发条件（`adaptive_max_pool3d_big_kernel_tiling.cpp:33-54`），按最大窗口元素数 `kernelMaxDHW` 分三档：

| 档位 | 附加约束 |
|---|---|
| `128 ≤ kernelMaxDHW < 256` | `totalOutSize = N*C*Do*Ho*Wo < 5120` |
| `256 ≤ kernelMaxDHW < 1024` | `totalOutSize < 10240` |
| `kernelMaxDHW ≥ 1024` | 无附加约束 |

计算方式：一个输出点一次循环（`AdaptiveMaxPool3dBigKernel::Process`，`adaptive_max_pool3d_big_kernel.h:494-520`），先用 `CalcWindowSize` 求出窗口在 DHW 上的起点与三向长度，再按"单次能否装下"选择搬运/归约路径：

| 子路径 | 触发条件 | 实现 |
|---|---|---|
| 不分段 | `AlignDHW <= maxCount` | `NoSplitProcess`：`AdaptivePool3dBigKernel::CopyIn` 一次搬完整窗口，`ComputeMax<NO_SPLIT>` 一次归约 |
| 按 D 分段 | `AlignDHW > maxCount && AlignHW <= maxCount` | `ComputeSplitD`：每段覆盖完整 HW，按 D 切片 |
| 按 H 分段 | `AlignHW > maxCount && AlignW <= maxCount` | `ComputeSplitH`：每段覆盖完整 W，按 H 切片 |
| 按 W 分段 | `AlignW > maxCount` | `ComputeSplitW`：最细粒度，按 W 切片 |

分段后由 `UpdateMaxAndIndex` 把各段结果合并（`adaptive_max_pool3d_big_kernel.h:188-218`）。索引在 `ComputeMax<SPLIT_MODE>` 中按 SPLIT_W / SPLIT_H / 其余 三种模式用 `CalcDivAndMod` 从段内下标还原为 `d*H_in*W_in + h*W_in + w` 的单通道展平偏移（同文件 `:152-182`）。搬运走 `AdaptivePool3dBigKernel::CopyIn` 的 `DataCopyPad` + `SetLoopModePara`，越界用 dtype 最小值（`-inf`）padding。

fp16 的 `maxUB` 复用为 int16 存放索引（`ComputeMax<NO_SPLIT, half, int16_t>`），并在 `Init` 中临时打开 half 溢出模式控制位（`SetCtrlSpr<HALF_OVERFLOW_MODE_CTRL, ...>(1)`，同文件 `:478-484`）。

### 3.4 Simt（`TPL_MODE_2`）

`IsCapable()` 恒真，是 A5 的兜底模板。用 `asc_vf_call` 发起 SIMT 线程，每个线程独立处理一个输出点，用魔数除法（`GetUintDivMagicAndShift`）计算 `ncId / dId / hId / wId` 与窗口起止（`adaptive_max_pool3d_simt.h:62-111`）。

按整型宽度走四个 tiling key 变体（`adaptive_max_pool3d_simt_tiling.cpp:64-75`），依据是 `indexNeedNum = N*C*Di*Hi*Wi` 与 `divNeedNum = max(Di*Do, Hi*Ho, Wi*Wo, outputCount)` 是否超过 `INT32_MAX`：

| 条件 | DYTPE_MODE | `DIV_T` / `FORMAT_T` |
|---|---|---|
| `indexNeedNum ≤ INT32_MAX && divNeedNum < INT32_MAX` | `TPL_INT32_UINT32` | uint32 / int32 |
| `indexNeedNum > INT32_MAX && divNeedNum < INT32_MAX` | `TPL_INT64_UINT32` | uint32 / int64 |
| `indexNeedNum ≤ INT32_MAX && divNeedNum > INT32_MAX` | `TPL_INT32_UINT64` | uint64 / int32 |
| 其余 | `TPL_INT64_UINT64` | uint64 / int64 |

## 4. 分核设计

| 模板 | 切分粒度 | 分核公式 | 尾核处理 |
|---|---|---|---|
| ParaPool | 一个 UB 块（`ncOuter × doOuter × hoOuter × woOuter`） | `blockFactor = CeilDiv(totalOuter, coreNum)`，`useCoreNum = CeilDiv(totalOuter, blockFactor)`，`blockTail = totalOuter - (useCoreNum-1)*blockFactor`（`adaptive_max_pool3d_para_tiling.cpp:80-96`） | 最后一核处理 `blockTail` 块；`GetBlockIdx() >= useCoreNum` 直接返回 |
| BigKernel | 一个输出点 | `blockFactor = totalIdx / coreNum`（向下取整），`blockTail = totalIdx % coreNum`；`blockFactor == 0` 时 `coreNums = totalIdx`（`adaptive_max_pool3d_big_kernel_tiling.cpp:61-71`） | **前** `blockTail` 个核各多处理 1 个输出点（`Process()` 中 `cBlockIdx < blockTail` 分支） |
| Simt | 一个输出点（SIMT 线程） | `blockNum = min(CeilDiv(outputCount, threadNum), coreNum)`，`threadNum` 在 `kernelWMax > 32` 时取 512，否则取 1024（`adaptive_max_pool3d_simt_tiling.cpp:56-60`） | 线程按 `blockIdx.x*blockDim.x + threadIdx.x` 跨步遍历，天然处理余尾 |

分核数来自 `context_->SetBlockDim(...)`（各模板 `PostTiling`），平台核数由 `GetPlatformInfo()` 动态获取（`platform_ascendc::PlatformAscendC::GetCoreNumAiv()`），源码未硬编码核数。

## 5. 分块设计

### 5.1 ParaPool 的 UB 预算

`CalOccupySize()`（`adaptive_max_pool3d_para_tiling.cpp:108-115`）按 5 份缓冲估算：

```text
maxDhw       = CeilAlign(max(doNum, kD) * max(hoNum, kH) * max(woNumAlign, wiDataLenAlign), 16)
maxInputSize = maxDhw * ncFactor                 # ncFactor = vfLen
occupy       = maxInputSize * sizeof(T) * 3      # inputQue / maxQue / maxTransQue
             + maxInputSize * 4                  # maxIndexQue(int32)
             + maxInputSize * sizeof(indicesDtype)  # maxIndexTransQue
```

- 起始 `doFactor = hoFactor = woFactor = 1`、`ncFactor = vfLen`；
- UB 不足时按 `doFactor → hoFactor → woFactor` 的顺序二分收缩（`SearchUbFactor`）；
- 再按 `doFactor → hoFactor → woFactor` 顺序收缩外层以提升 `useCoreNum`（`SearchOuter`）；
- 对齐粒度：向量寄存器 256B（host 侧 `Ops::Base::GetVRegSize()` 返回 256），UB block 32B，转置要求按 16 对齐（`TRANS_ADDR_LEN`）。

### 5.2 BigKernel 的 UB 预算

`DoBlockTiling()`（`adaptive_max_pool3d_big_kernel_tiling.cpp:73-82`）：

```text
ubAvailable = ubSize - (sizeof(T) + sizeof(indices)) * 1024
defaultMax  = FloorAlign(ubAvailable / 2, vRegSize)       # 双缓冲
maxCount    = min(defaultMax / sizeof(T), 32640)          # fp16 上限 32640
            | defaultMax / sizeof(T)                       # fp32/bf16
batchCount  = maxCount / kernelMaxDHW                     # 一次可并行的输出点数
```

单窗口超过 `maxCount` 时按 `maxCount` 步长分段归约。搬运用 `DataCopyPad` + `SetLoopModePara`（loop1 = 图像行、loop2 = 深度切片），越界部分用 dtype 最小值（`-inf`）padding，保证不污染最大值（`adaptive_pool3d_big_kernel.h:127-154`）。

### 5.3 Simt 的 UB 预算

Simt 不切 UB：线程直接读写 GM，仅在 `PostTiling` 中把 UB 留给 DCache（`ubSize = input_.ubSize - DCACHE_SIZE`，`DCACHE_SIZE = 128KB`），用 `context_->SetLocalMemorySize` 设置（`adaptive_max_pool3d_simt_tiling.cpp:77-86`）。分块完全由 `threadNum`（512 / 1024）与 `blockNum` 决定。

## 6. 性能调优技巧

以下为源码中真实存在的机制，不包含推测性优化：

1. **三级模板回退**：先试高并行的 ParaPool（NC 铺满向量），再试低搬运的 BigKernel（窗口大时只搬必要窗口），最后用 Simt 兜底，避免大窗口场景按元素逐个向量归约。
2. **双缓冲**：BigKernel `USE_BUFFER_NUM = 2`，`inputQue_` 双缓冲，搬运与归约重叠（`adaptive_pool3d_big_kernel.h:29,168`）。
3. **Loop 模式搬运**：BigKernel 用 `SetLoopModePara` 把 H/D 两级的跨步访问压成一次 `DataCopyPad`，减少 MTE2 指令数；`srcStride` 用 `wInDim` 对齐宽度计算。
4. **索引随归约一起产出**：ParaPool 在 W 级用标量递增生成索引，H/D 级复用索引张量；BigKernel 把索引 float 化后与 max 值同放 `maxUB`，避免第二轮扫描。
5. **魔数除法**：Simt 在 host 侧预算 `magic/shift`，device 侧用 `Simt::UintDiv` 替代整除指令；当 `DIV_T=uint32 && FORMAT_T=int32` 时走直接传参的快速版本，其余走 UB 参数版（`adaptive_max_pool3d_simt.h:184-206`）。
6. **NC 向量化宽度自适应**：ParaPool 的 `ncFactor = vfLen = 256/sizeof(T)`，fp32 与 fp16/bf16 自动取 64 / 128。
7. **整除短路**：aclnn 层在空间维全部整除时改走 `MaxPool3DWithArgmaxV2`（固定窗口、无自适应边界计算），避免自适应路径的逐窗口边界计算开销（`op_api/aclnn_adaptive_max_pool3d.cpp:427-430`）。
8. **核数自适应**：三个模板都用 `GetCoreNumAiv()` 取平台核数，`blockFactor==0`（输出点少于核数）时退化为按输出点数开核（BigKernel）。

## 7. 模板与测试覆盖映射

目标芯片固定 **A5**。验证状态取值：静态推断 / 已运行验证 / 已运行验证（豁免）/ 未覆盖 / 不适用。

### 7.1 A5 可达分支

| # | 内部模板/分支 | 源码依据 | 完整外部触发条件 | case_id | 验证状态 |
|---|---|---|---|---|---|
| 1 | ParaPool（fp32） | `adaptive_max_pool3d_para_tiling.cpp:29-58`；kernel `adaptive_max_pool3d_parall_pool.h:128-134`（`CustomSelect` fp32 分支） | `x` dtype=float32，`kernelDMax*kernelHMax*kernelWMax < 128`，`N*C >= 32`，窗口占用 UB ≤ 248KB | 1, 6, 7 | 已运行验证 |
| 2 | ParaPool（fp16） | 同上，`adaptive_max_pool3d_parall_pool.h:132-133`（`TransposeB16`）+ `CustomSelectOnW` | dtype=float16，`N*C >= 64`，窗口 < 128 | 3, 5 (idx int64) | 已运行验证 |
| 3 | ParaPool（bf16） | 同上 | dtype=bfloat16，`N*C >= 64`，窗口 < 128 | 4 | 已运行验证 |
| 4 | ParaPool 的 `indices=int64` 输出槽 | `adaptive_max_pool3d_parall_pool.h:439-446`（`Cast` 到 `U=int64`） | `indicesOut` dtype=int64（`indices_dtype=9`） | 5 | 已运行验证 |
| 5 | ParaPool 多核均分（`useCoreNum == coreNum`，无尾核） | `CalUbBlockFactor` + `SearchOuter` | `totalOuter` 恰能被分核整除 | 7 | 已运行验证 |
| 6 | BigKernel（`128 ≤ k < 256` 档） | `adaptive_max_pool3d_big_kernel_tiling.cpp:44-45` | `128 ≤ kernelMaxDHW < 256` 且 `totalOut < 5120` | 8 | 已运行验证 |
| 7 | BigKernel（`256 ≤ k < 1024` 档） | 同上 `:46-47` | `256 ≤ kernelMaxDHW < 1024` 且 `totalOut < 10240` | 9, 10 | 已运行验证 |
| 8 | BigKernel（`k ≥ 1024` 档） | 同上 `:48-49` | `kernelMaxDHW ≥ 1024` | 11, 12, 14 | 已运行验证 |
| 9 | BigKernel 不分段子路径（`NoSplitProcess`） | `BaseCompute` 的 `AlignDHW <= maxCount` 分支（`adaptive_max_pool3d_big_kernel.h:441-450`） | 整个窗口一次装得下（`AlignDHW ≤ maxCount`） | 8, 9, 10, 12, 14 | 已运行验证 |
| 10 | BigKernel 按 D 分段子路径（`ComputeSplitD`） | `SplitProcess`（同文件 `:455-464`） | `AlignDHW > maxCount` 且 `AlignHW ≤ maxCount` | 11, 13 | 已运行验证 |
| 11 | BigKernel 按 H / 按 W 分段子路径（`ComputeSplitH` / `ComputeSplitW`） | `SplitProcess` 的另两个分支 | `AlignHW > maxCount`（H 分段）或 `AlignW > maxCount`（W 分段） | 未覆盖 | 需单窗口高/宽方向超过 `maxCount`（约 3 万元素）才能触发，见 §7.3 |
| 12 | BigKernel 段间合并（`UpdateMaxAndIndex`） | 同文件 `:188-218` | 仅在 H/W 分段时出现多段 | 未覆盖 | 随 #11 一并未覆盖 |
| 13 | Simt（int32 索引 + uint32 除法） | `adaptive_max_pool3d_simt_tiling.cpp:66-67` | 兜底：窗口 ≥ 128 但 `totalOut` 超档位上限，或 `N*C < vfLen/2`，或 UB 不足 | 16, 17, 18, 19, 20 | 已运行验证 |
| 14 | Simt（`indices=int64`） | `adaptive_max_pool3d_simt.h` 的 `INDICES_T` | 兜底 + `indices_dtype=9` | 19 | 已运行验证 |
| 15 | 核间尾核（BigKernel 前 `blockTail` 核多算 1 点） | `adaptive_max_pool3d_big_kernel.h:494-520` | `totalIdx % coreNum != 0` | 12 | 已运行验证（`blockTail` 分支被遍历） |
| 16 | aclnn 整除短路 → `MaxPool3DWithArgmaxV2` | `op_api/aclnn_adaptive_max_pool3d.cpp:427-430` | `Di%Do==0 && Hi%Ho==0 && Wi%Wo==0` | 2, 15 | 已运行验证 |
| 17 | 4 维输入（Unsqueeze/Squeeze 路径） | `op_api/aclnn_adaptive_max_pool3d.cpp:292-318, 478-481` | `x` 为 4 维 `(C,D,H,W)` | 6 | 已运行验证 |
| 18 | dtype 与 `indices_dtype` 组合矩阵 | `_def.cpp:50-81`（A5 配置 6 组 dtype 组合） | 见 §7.2 | 全量 | 已运行验证 |

### 7.2 dtype 覆盖矩阵（A5）

| dtype | `indices_dtype=3`（int32） | `indices_dtype=9`（int64） |
|---|---|---|
| float32 | case 1, 2, 6, 7, 8, 9, 10, 11, 12, 16, 20 | 未覆盖（见 §7.3） |
| float16 | case 3, 13, 15, 17 | case 5 |
| bfloat16 | case 4, 18 | case 14, 19 |

### 7.3 未覆盖 / 不适用分支与取舍理由

| 分支 | 状态 | 理由 |
|---|---|---|
| Simt 的 `TPL_INT64_UINT32` / `TPL_INT32_UINT64` / `TPL_INT64_UINT64` 三个变体 | **未覆盖** | 触发条件是 `indexNeedNum` 或 `divNeedNum` 超过 2147483647，即 `D*H*W` 或 `D*D_out` 级别达到 2^31；这样的张量在 GB 量级，无法在 20 条可执行用例内构造并跑通。属大 shape 边界，已记录为遗留项。 |
| BigKernel 的 `ComputeSplitH` / `ComputeSplitW` 子路径与段间合并 | **未覆盖** | 需要单窗口在 H 或 W 方向的元素数超过 `maxCount`（本机实测 30720/32640），即窗口至少 3 万元素且形状极端狭长；20 条名额内该类 shape 与"大窗口多核"用例（case 11/12/13）互斥，优先保证后者。已记录为遗留项。 |
| float32 + `indices_dtype=9` | **未覆盖** | 20 条名额内优先保证 dtype × 模板组合；int64 索引路径已由 float16（case 5）与 bfloat16（case 14, 19）覆盖。 |
| 非连续输入视图（`noncontiguous_input`） | **未覆盖** | aclnn 入口对 `self` 先做 `Contiguous`，非连续视图在算子外部被消除，不构成算子内部可分支的路径。输出为非连续张量的场景由 `ViewCopy` 处理，本需求把输出固定为连续张量。 |
| `output_size` 长度为 0 或 1 | **未覆盖** | 需求把 `output_size` 固定为长度 3 的外部契约（与 op def `ListInt` 完整语义一致）；长度 0/1 只存在于 regbase 的 aclnn 归一化入口，不属于图算子契约。 |
| 输入含 NaN/Inf 的特殊值路径 | **未覆盖** | BigKernel 有专门的 NaN 索引重选逻辑（`GetMask` + `GetIndexWithLastNan`），但不同实现对"窗口内多个 NaN 取哪个索引"的取舍不统一，无法作为 `indices` 逐元素相等的判定依据；按需求契约，特殊值只在契约明确要求时纳入，本需求不要求。 |
| arch22（A3/A2）的 SmallPool / BigPool 模板 | **不适用** | 芯片范围外（§1.1）。 |

## 8. 源码依据与需求决策

### 8.1 源码事实（可追溯到具体文件/行）

1. 算子注册名 `AdaptiveMaxPool3d`，输入 `x`、输出 `y`/`indices`、属性 `output_size`(REQUIRED, ListInt) 与 `indices_dtype`(OPTIONAL, Int, 默认 3)（`_def.cpp:20-81`、`op_graph/*_proto.h`）。
2. A5 配置声明 6 组 dtype 组合：{fp16, bf16, fp32} × {int32, int64} 索引（`_def.cpp:51-71`，`config/ascend950|ascend350/*.json`）。
3. `y` 与 `x` 同 dtype；`indices` dtype 由 `indices_dtype` 决定（`infershape.cpp:114-131`）。
4. 输出 shape 为输入前导维 + `(Do,Ho,Wo)`（`infershape.cpp:86-109`）。
5. 索引语义为单通道 `D*H*W` 内展平偏移（Simt 明确写 `maxIdx = d*height*width + h*width + w`，`adaptive_max_pool3d_simt.h:78,89,108`）。
6. 单窗口比较使用 `>`（严格大于），并列时保留首次出现（`adaptive_max_pool3d_simt.h:95-98`；`CustomSelect` 用 `CMPMODE::GT`，`adaptive_max_pool3d_parall_pool.h:182`）。
7. A5 三个 tiling 模板的优先级与 arch 闸门（`adaptive_pool3d_tiling.cpp:107-109`；三个 `REGISTER_OPS_TILING_TEMPLATE`）。
8. `D*H*W` 不得超过 int32（`adaptive_pool3d_tiling.cpp:35-40` 与 aclnn `checkExceptiveValue`）。
9. aclnn 在整除时改走 `MaxPool3DWithArgmaxV2`（`op_api/aclnn_adaptive_max_pool3d.cpp:424-438`）。

### 8.2 基于代码的推断

1. **A5 上 priority 3/4（arch22 模板）不可达**：依据是 Simt 的 `IsCapable()` 恒真 + registry 按 priority 升序且第一个非 `GRAPH_PARAM_INVALID` 即返回。属于对注册顺序与 `DoTiling` 流程（`common/inc/op_host/tiling_base.h:70-102`）的推断。**已由真机日志证实**：20 条用例上实际命中的 tiling key 只有 0 / 1 / 6 三种（对应 ParaPool / BigKernel / Simt），从未出现 arch22 的 310000/320000 系列。
2. **`kernelMaxDHW` 与三档阈值的关系**：`CalKernelSizeOneDimMax` 逐维取最大窗口长度，三者相乘得到单窗口元素上限；这是"最大可能窗口"而非某具体输出点的窗口。用例的档位归属按该上界计算。
3. **ParaPool 的 UB 估算在 `doFactor=hoFactor=woFactor=1` 时成立**：`CalOccupySize` 在 `IsCapable` 阶段只用到该初值，后续二分会继续收缩。

### 8.3 AI 自行确定的规则（需求决策）

1. **`output_size` 统一为长度 3**：即使 A5 的 aclnn 允许长度 0/1，需求契约固定为 `[Do,Ho,Wo]`，理由是它与 op def 的 `ListInt` 语义一致，且长度 0/1 只是入口归一化细节。
2. **`indices` 判定为逐元素完全相等**：整数输出不做相对误差判定。
3. **不纳入 NaN/Inf 用例**：见 §7.3。
4. **不纳入非连续输入视图**：见 §7.3。
5. **golden 的 dtype 处理**：fp16/bf16 先升 fp32 计算再回转，与源码 golden（`tests/assets/golden.py` 的 `adaptive_max_pool3d_golden` 对 `float16`/`bfloat16` 做 `astype(np.float32)`）一致；索引统一按 `indices_dtype` 输出 int32/int64，与 `aclnn_adaptive_max_pool3d_golden` 的语义一致。
6. **4 维输入的 golden 处理**：先 `unsqueeze(0)` 再计算，最后 `squeeze(0)`，保证索引仍是单通道 `D*H*W` 展平偏移（已用 torch 实测确认）。

### 8.4 golden 来源与 CPU 对照

- 来源优先级命中：`tests/assets/golden.py`（第一优先级）。
- 源码 golden 形态：`__golden__` 注册表，含 `kernel`（`adaptive_max_pool3d_golden`，numpy 入参、`nn.AdaptiveMaxPool3d(output_size, True)`、索引强制 int32）与 `aclnn`（`aclnn_adaptive_max_pool3d_golden`，torch 入参、`F.adaptive_max_pool3d(..., return_indices=True)`）两套。
- 重写方式：以 aclnn 语义为主契约，等价于 `nn.AdaptiveMaxPool3d`；重写为单公开函数 `adaptive_max_pool3d(x, output_size, indices_dtype=3)`，去掉 `**kwargs`、`outputOut`/`indicesOut` 槽位等测试框架参数，补 `List[int]` / 类型标注，输出改为按 `output_size`/`indices_dtype` 生成。
- 对照方法：对 10 组代表性 shape/dtype（含 4 维、输出大于输入、`Do=Di` 全窗口、bf16、int64 索引）在同一输入上与源码 golden 的等价路径逐输出比对。
- 对照结果：`y` 与 `indices` 全部 `array_equal`，最大绝对误差 0；shape 与 dtype 一致。
- 对照的局限：源码 golden 对 fp16/bf16 输入先 `astype(np.float32)`，因此 `y` 的比对是在 fp32 计算后 cast 回原 dtype 的口径下进行的，与 `nn.AdaptiveMaxPool3d` 直接吃 fp16 的舍入路径可能不同；本需求以 fp32 升精度计算为契约（见 §8.3 第 5 条）。

### 8.5 TTK 实测结果

**状态：已执行**（全量 20 条，真机 Ascend950DT_9582）。

- 执行方式：`python3 -m ttk aclnn -i <ttk>/cases.csv --plugin <ttk> -o <ttk>/debug/result.csv --dump-on-fail`，TTK_REPO 根目录执行。冒烟用 case 03 先验链路。
- 交接契约偏离（已与用户确认）：`references/ttk-integration.md` 要求使用 `<TTK_REPO>/.claude/skills/ttk-aclnn-adapt`，但 ops-test-kit 仓库内无该目录；实际使用 `requirement_new/.claude/skills/ttk-aclnn-adapt`（同源，含 SKILL.md + 4 个 references + 3 个脚本）。同时首次启动的子代理进程被中断，其 Step 0 产物（`contract.md`、`signature.txt`、`cases.csv` 转换）经复核后保留，Step 2~5 由主控完成。
- 结果：**20/20 PASS，0 FAIL，0 SKIP**。
  - `y` 槽：全部用例 `max_abs_error = 0`（判据 `mix_tolerance`），matched_ratio 1.0；
  - `indices` 槽：全部用例判据为 `binary_equal` 且通过，即与 golden **逐元素完全一致**。
- 逐模板命中（真机日志中的 `Get function handle by tiling key [...]`）：

| tiling key | 模板 | case |
|---|---|---|
| 0 | ParaPool | 1, 3, 4, 5, 6, 7 |
| 1 | BigKernel | 8, 9, 10, 11, 12, 13, 14 |
| 6 | Simt | 16, 17, 18, 19, 20 |
| 400001 / 600001 | aclnn 整除短路 → `MaxPool3DWithArgmaxV2` | 2, 15 |

- 注意：**case 15 未进入本算子 kernel**，而是由 aclnn 整除短路发往 `MaxPool3DWithArgmaxV2`；它验证的是 aclnn 入口行为与索引语义一致性，不计为本算子模板覆盖。
- BigKernel 真机 tiling 数据（`PrintTilingData`）抽样：case 10 `maxCount=30720, batchCount=53`；case 13 `maxCount=32640`；case 14 `blockFactor=15, blockTail=40`（尾核分支实际被遍历）。
- 未发生回流修正：没有 golden 错误、没有用例违规、没有伪失败、没有算子缺陷、没有环境错误。`handoff.json` 的 `failures` 为空。

### 8.6 遗留事项

1. Simt 的三个大整数 tiling 变体（`indexNeedNum`/`divNeedNum` 超 int32）未覆盖，需 ≥ GB 级张量才能触发。
2. float32 + int64 索引组合未覆盖。
3. BigKernel 的 `ComputeSplitH` / `ComputeSplitW` 子路径未覆盖，需窗口单方向元素数超过 `maxCount`（约 3 万）。
4. `output_size` 长度为 0/1、NaN/Inf 特殊值、非连续输入视图未纳入用例（理由见 §7.3）。
