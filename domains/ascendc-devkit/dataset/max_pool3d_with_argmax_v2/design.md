# MaxPool3DWithArgmaxV2 算子设计分析（A5）

> 本文件是内部设计文档，允许出现 tiling key、模板名与源码路径；这些标识不得反向进入
> `desc.md`、`golden.py`、`proto.yaml`、`cases.*`。

## 1. 芯片范围与源码布局

### 1.1 芯片范围声明

- 本次芯片种类：**A5**（Ascend 950PR/950DT、3510），对应 arch 目录 `op_kernel/arch35`，
  config 目录 `op_host/config/ascend950` 与 `op_host/config/ascend350`。
- 实机环境：`npu-smi` 报告 `Ascend950DT`（8 卡），TTK `info` 报告平台 `Ascend950DT_9582`。
- A5 平台参数（`Ascend950DT_9582.ini`）：`ub_size = 253952`（248 KB）、
  `vector_core_cnt = 64`、`vector_reg_width = 256`（字节，即 1 个 vector register = 256B）。
- **本次被排除的范围**（不进入需求、golden、cases、desc）：
  - A2/A3 路径：`op_host/config/ascend910b`、`op_host/config/ascend910_93`，`op_kernel/` 根目录下的
    `max_pool3d_with_argmax_v2_nosplit.h`、`_splitd.h`、`_splith.h`、`_splitw.h`、
    `_huge_kernel.h`、`_no_expand_indices.h`、`max_pool3d_with_argmax_big_kernel.h`，以及
    `op_host` 中同名 tiling（priority 10~16）。
  - kirin 分支：`op_host/config/kirin9030`、`op_host/config/kirinx90` 与 `GetKirinCoreConfig()`。
  - 文档中 `Atlas A2`／`Atlas A3` 专属约束行（`dilation` 仅支持 1、`indices` 不支持 INT64、
    不支持 NDHWC、`D*H*W` 不支持大于 INT32_MAX），这些约束在 A5 上不成立。
  - aclnn 文档中“Atlas 200I/500 A2 推理产品、Atlas 推理系列产品、Atlas 训练系列产品：不支持”的行。
- A5 在 `op_host/max_pool3d_with_argmax_v2_def.cpp` 中有独立 `OpAICoreConfig`（`ascend950`、`ascend350`），
  在 `op_host/config/ascend950|ascend350/*_binary.json` 中有 6 个 dtype 组合的二进制配置，
  在 `op_kernel/max_pool3d_with_argmax_v2.cpp` 中有 `__CCE_AICORE__ == 310 && __NPU_ARCH__ != 3113` 分支，
  因此 A5 实现完整，不存在缺口。

### 1.2 文档版本选择

| 项 | 结论 |
|---|---|
| 采用文档 | `docs/aclnnMaxPool3dWithArgmax.md` |
| 被排除候选 | `docs/aclnnMaxPool2dWithIndices.md`（2D 算子入口，算子名不匹配）、`docs/aclnnMaxPool2dWithMask.md`（2D + mask 入口） |
| 算子名推导 | 目录 `max_pool3d_with_argmax_v2` → 默认 `MaxPool3dWithArgmaxV2`；源码 `OP_ADD(MaxPool3DWithArgmaxV2)` 与 `class MaxPool3DWithArgmaxV2 : public OpDef` 注册名为 **MaxPool3DWithArgmaxV2**，以源码为准，记录该差异 |
| 反向确认 | `op_api/aclnn_max_pool3d_with_argmax.h` 中唯一入口 `aclnnMaxPool3dWithArgmaxGetWorkspaceSize`；`tests/st/aclnnMaxPool3dWithArgmax/executor_aclnnMaxPool3dWithArgmax.py` 使用 `torch.nn.MaxPool3d(..., return_indices=True)`；`examples/test_aclnn_max_pool3d_with_argmax.cpp` 调用同名接口。三者一致 |

### 1.3 目录落位

| 内容 | 实际位置 | 说明 |
|---|---|---|
| 接口文档 | `docs/aclnnMaxPool3dWithArgmax.md` | 另有 2 份 2D 文档，已排除 |
| kernel 入口 | `op_kernel/max_pool3d_with_argmax_v2.cpp` | A5 分支 include `op_kernel/arch35/*.h` |
| kernel 实现（A5） | `op_kernel/arch35/max_pool3d_with_argmax_v2_{base,gather,simt,nc_transpose,ksize_one,big_kernel_regbase,tiling_struct}.h` | 只读这些 |
| tiling（A5） | `op_host/max_pool3d_with_argmax_v2_{ksize_one,nc_transpose,gather,big_kernel_regbase}_tiling.cpp`、`_tiling.cpp`、`_tiling_base.*`、`_infershape.cpp` | 其余 tiling 为 A2/A3 路径 |
| aclnn 接口 | `op_api/aclnn_max_pool3d_with_argmax.{h,cpp}` + `op_api/max_pool3d_with_argmax_v2.cpp`（l0op） | 唯一入口 |
| 算子原型 | `op_graph/max_pool3d_with_argmax_v2_proto.h` | |
| golden | `tests/assets/golden.py` 的 `max_pool3d_with_argmax_v2_golden`（kernel 入口） | 见第 8 节 |
| 用例种子 | `tests/st/arch35/ttk_aclnn_max_pool3d_with_argmax_st.csv`、`tests/st/aclnnMaxPool3dWithArgmax/executor_*.py` | `atk_*.json` 为空文件，无可用内容 |

## 2. 实现概览

### 2.1 外部接口

- 算子原型 `MaxPool3DWithArgmaxV2`：输入 `x`；属性 `ksize`、`strides`、`pads`（必选），
  `dilation`（默认 `[1,1,1]`）、`ceil_mode`（默认 false）、`data_format`（默认 `"NCDHW"`）、
  `dtype`（默认 3，即 int32，仅 A5 配置声明）；输出 `y`、`argmax`。
- aclnn 入口 `aclnnMaxPool3dWithArgmaxGetWorkspaceSize(self, kernelSize, stride, padding, dilation,
  ceilMode, out, indices, workspaceSize, executor)`，张量槽顺序 **self → out → indices**，输出索引 `(1, 2)`。
- aclnn 层的 `dtype` 不作为入参：索引类型由调用方分配的 `indices` 张量 dtype 决定（int32/int64），
  `op_api/max_pool3d_with_argmax_v2.cpp` 将其翻译为算子属性 `dtype`（3/9）。
- aclnn 层的 `data_format` 同样不作为入参：由 `self->GetStorageFormat()` 推导（`NDHWC` → `"NDHWC"`，
  其他 → `"NCDHW"`）。

### 2.2 主机侧预处理（`op_api/aclnn_max_pool3d_with_argmax.cpp`）

1. 平台校验（仅 A2/regbase 通过）、空指针/ dtype / format / 属性合法性校验。
2. 空张量直接返回（算子不支持空张量）。
3. 输入做 `Contiguous`；4 维输入 `Unsqueeze(dim=0)` 成 5 维再 `ReFormat(NCDHW)`。
4. 计算结果 squeeze/reformat 回原秩与目标 format，最后 `ViewCopy` 到调用方传入的 `out`/`indices`（支持非连续输出）。
5. 4 维输入通过该层归一化为 5 维，因此**所有 tiling 模板看到的一定是 5 维 shape**。

### 2.3 设备侧数据流

- `y` 与 `argmax` 同 shape；`argmax` 是「通道内 D×H×W 展平偏移」：
  `d_in * H_in * W_in + h_in * W_in + w_in`，与 batch/channel 位置、`data_format` 无关。
  该语义由三个实现共同保证：SIMT 直接用 `d*height*width + h*width + w` 生成索引；
  gather/nc_transpose 先在 UB 内以 `wInputActualPad` 对齐坐标计算，再换算回真实输入坐标；
  大窗口模板同理。
- `float16` / `bfloat16` 输入在 SIMT 路径用 `isnan` + 严格大于比较；补零位置不参与比较
  （gather 走 IS_PAD 分支，把负索引钳到 0 并按 -inf 语义处理；SIMT 直接把窗口起点推向输入内部）。

## 3. 模板设计

### 3.1 模板注册与分发顺序（A5 实际生效）

`op_host/max_pool3d_with_argmax_v2_tiling.cpp` 用 `TilingRegistry::DoTilingImpl` 按 priority
**升序**逐个尝试，`GetShapeAttrsInfo` 返回 `GRAPH_PARAM_INVALID` 时继续下一个。A5 上实际生效的链路：

| 顺序 | 模板类 | 注册 priority | tiling key | 关键触发条件（内部判定） |
|---|---|---|---|---|
| 1 | `MaxPool3DWithArgmaxV2KsizeOneTiling` | 0 | 700001 | `ksize == (1,1,1)` 且 `stride == (1,1,1)` 且 format NCDHW |
| 2 | `MaxPool3DWithArgmaxV2NcTransposeTiling` | 1 | 500001 | NCDHW；`dilation == 1`；无 padding（`ceil_mode` 造成的隐式 padding 也算）；`D*H*W <= INT32_MAX`；`kD*kH*kW <= 128`；`N*C >= 3072`；`D_out*H_out*W_out >= 32`；UB 预算足够；fp16/bf16 时 `maxDelta <= 32767` |
| 3 | `MaxPool3DWithArgmaxV2GatherTiling` | 2 | 400001/400002/400011/400012/400021/400022 | NCDHW；`dilation == 1`；`W_in > 1`；不是 `(ksize=(1,1,1) 且 stride=(1,1,1))`；不满足「归约退化」与「稀疏/小窗口」启发式；`W_kernel * itemsize < 128B` |
| 4 | `MaxPool3DWithArgmaxV2BigKernelRegbaseTiling` | 3 | 611110 | NCDHW；`dilation == 1`；`W_kernel * itemsize >= 64`；`maxCount > 1024` |
| 5 | `MaxPool3DWithArgmaxV2TilingSIMT` | 4 | 600001/600002/600011/600012/600101/600102 | `IsCapable()` 恒真（兜底），format 允许 NCDHW 与 NDHWC |

priority 10~16 的 `NoExpandIndices`、`BigKernel`、`NoSplit`、`SplitD`、`SplitH`、`SplitW`、`HugeKernel`
在 regbase（A5）上 `IsCapable()` 直接返回 false 或 `GetShapeAttrsInfo` 返回 `GRAPH_PARAM_INVALID`，
因此 A5 永不进入这些模板。

### 3.2 各模板的计算差异

- **KsizeOne（700001）**：窗口与步长均为 1，结果等于输入本身，索引等于自身展平偏移；
  设备侧只做 `DataCopy` 与 `Arange` 生成索引，按 512B 对齐切块、按 NC 平面批量搬运。
- **NcTranspose（500001）**：把 `N*C` 视为高轴、把空间维视为内轴。先按 `ncInner = vlNumT1`
  （256B / itemsize，fp32 为 64、fp16/bf16 为 128）把高轴切块，做一次 NC→空间 的转置载入，
  在 UB 内用向量寄存器完成整窗比较，再转置回 NC 布局写出。索引以 int16/int32 增量（delta）形式
  记录，最后统一换算；fp16/bf16 的 delta 用 int16 存储，因此有 `maxDelta <= 32767` 的限制，
  超出时该模板不可用。fp32 或 `indices` 为 int64 时走 int32/int64 计算路径。
- **Gather（400001~400022）**：按 `W` 方向生成 gather 索引向量，一次向量比较覆盖多个输出点。
  tiling key 的低位编码「是否带 padding」与「索引计算位宽」：
  - `base = 400001`（无 padding）/ `400002`（有 padding，含 `ceil_mode` 造成的隐式 padding）；
  - 再加 `10 * calIndexType`：`0` = 32 位计算，`1` = 16 位计算（仅 fp16/bf16 且
    `D*H*W <= 32767`），`2` = 64 位计算（`D*H*W > INT32_MAX`）。
  设备侧对应 6 个模板实例，带 padding 的实例会把负坐标钳到 0 并按 -inf 语义比较。
- **BigKernelRegbase（611110）**：面向「窗口 W 方向很长」的场景（`W_kernel * itemsize >= 64B`），
  单个窗口的数据量超过一个向量寄存器，先算局部最大值与真实索引，再汇总到 workspace。
  当输出点数量不足以占满一半核（`totalIdx <= coreNum/2`）时，按 `W` 方向把一个窗口拆给多个子核，
  通过 workspace 做二阶段归约（`multiCoreNum > 1`）。
- **SIMT（600001~600102）**：标量线程模型，一个线程算一个输出点，天然支持任意 dilation、任意 format
  与 int64 索引。tiling key 由三个维度编码：
  `format`（NCDHW=0 / NDHWC=1）、`是否 int32 计数`（`N*C*D_out*H_out*W_out <= INT32_MAX`）、
  线程数（256 / 512）。

### 3.3 与文档语义的对应

文档给出的输出 shape 推导（含 `ceil_mode` 修正）由 `op_api` 的 `PoolingOutShape` 与
`op_host/max_pool3d_with_argmax_v2_infershape.cpp` 的 `UpdateMaxShape` 实现，二者与 golden 中的
`torch.nn.functional.max_pool3d` 完全一致（含 `ceil_mode` 时丢弃落在右侧 padding 的窗口）。
`padding` 填充值按文档为负无穷，与 golden 的 `-inf` 语义一致。

## 4. 分核设计

| 模板 | 核数策略 |
|---|---|
| KsizeOne | 按 `N*C` 平面数在核间均分，尾核处理剩余平面；块内再按 512B 对齐细分 |
| NcTranspose | 基本块 = `ncOuter * dOutputOuter * hOutputOuter * wOutputOuter`，`normalCoreProcessNum = ceil(基本块数 / 总核数)`，`usedCoreNum = ceil(基本块数 / normalCoreProcessNum)`，尾核少处理一个基本块 |
| Gather | 同上：`totalBaseBlockNum` 均分到 `totalCoreNum`，前 `usedCoreNum - 1` 个核各处理 `normalCoreProcessNum` 块，最后一个核处理 `tailCoreProcessNum` 块 |
| BigKernelRegbase | `totalIdx = N*C*D_out*H_out*W_out`，`blockFactor = totalIdx / coreNum`，`blockTail = totalIdx % coreNum`；当 `totalIdx <= coreNum/2` 时改为「多子核协作一个窗口」，按 `W` 方向拆分，`blockDim = coreNums * multiCoreNum` 并开启 `SetScheduleMode(1)` |
| SIMT | `threads = min(outputDataCount, 256)`；当 `kD*kH*kW >= 64` 且 `outputDataCount > 512*coreNum`，或 fp32 且各轴 `stride >= kernel` 且 `outputDataCount > 512*coreNum` 时提升到 512 线程；`blockNum = min(ceil(outputDataCount / threads), coreNum)` |

`coreNum` 全部从平台接口读取（`GetCoreNumAiv()`），未硬编码。

## 5. 分块设计

- **UB 预算**：A5 `ub_size = 253952` B；gather 模板保留 0 B（`UB_RESERVED_SIZE = 0`）后按
  输入缓冲 + 最大值缓冲 + 索引缓冲精确计算；ksize_one 保留 1024 B 并做双缓冲；
  SIMT/大窗口不做 UB 分块。
- **切分优先级**（gather / nc_transpose 共用）：先尝试「高轴（N*C）整块 + 空间不切」，
  不行则 `TrySplitD` → `TrySplitH` → `TrySplitW`，每级用二分求满足 UB 与目标核数约束的最大 Inner 值。
  因此优先保住空间局部性，最后才切 W。
- **对齐**：W 方向 Inner 长度按 UB block（32B / itemsize）对齐；nc_transpose 的 NC 内块按 16 元素对齐
  （`TRANS_ALIGN = 16`）；索引缓冲按 `max(4, indexBytes)` 与 itemsize 中较大者对齐。
- **尾块**：`wOutputTail / hOutputTail / dOutputTail / highAxisTail` 分别记录各轴最后一个 Inner 块，
  设备侧用 `DataCopyPad` 处理不对齐尾部；SIMT 用线程步长 `index < count` 自然裁尾。
- **关键阈值**（全部来自源码常量）：

| 常量 | 值 | 含义 |
|---|---|---|
| `MAX_KERNEL_VOLUME` | 128 | nc_transpose 只处理窗口元素数不超过 128 的场景 |
| `MIN_NC_FOR_TRANSPOSE` | 48*64 = 3072 | nc_transpose 的最小 `N*C` |
| `NC_TRANSPOSE_MIN_OUT_SPATIAL` | 32 | nc_transpose 的最小输出空间体积 |
| `INT16_MAX_LIMIT` / `INT16_INDEX_MAX` | 32767 | fp16/bf16 delta 与 16 位索引上限 |
| `SMALL_KERNEL_ELEMENTS_THRESHOLD` / `BIG_KERNEL_ELEMENTS_THRESHOLD` | 512 / 1024 | gather 归约退化判定区间 |
| `KERNEL_ELEMENTS_LIMIT` / `OVERLAP_SPARSE_LIMIT` | 25 / 64 | gather 稀疏窗口判定 |
| `CACHE_LINE_SIZE` | 128 B | `W_kernel * itemsize` 超过缓存行时 gather 放弃 |
| `MIN_OUTPUT_THRESHOLD` | 4 | gather 最终 UB 预算的比例系数 |
| `KW_THRESHOLD` / `MIN_COUNT` | 64 / 1024 | 大窗口模板的 W 窗口字节数与最大向量计数下限 |
| `KERNEL_SIZE_THRESHOLD` / `MAX_THREAD_NUM` | 64 / 512 | SIMT 线程数提升阈值 |

## 6. 性能调优技巧（源码实际存在）

1. **模板级快速路径**：`ksize=stride=1` 走纯拷贝 + `Arange` 生成索引，避免逐窗口扫描。
2. **NC 转置批量比较**：NcTranspose 把 `N*C` 高轴搬到向量维，一次寄存器操作完成 64/128 个通道的
   同位置窗口比较，极大提升小窗口 + 大 NC 场景的向量利用率。
3. **Gather 索引预生成**：按 W 方向一次性生成 gather 偏移向量，`ProcessW` 中以未对齐 store
   (`StoreUnAlign`) 直接写出，减少标量化开销。
4. **索引增量存储**：nc_transpose 用 int16/int32 delta 表示窗口内索引，降低索引缓冲占用
   （fp16/bf16 场景尤其明显），搬出前再统一还原为绝对偏移。
5. **多核协作单窗口**：BigKernel 在输出点不足以填满核时，沿 W 把一个窗口拆给多个子核做两阶段归约，
   避免大窗口场景只有 1~2 个核工作。
6. **线程数自适应**：SIMT 依据窗口元素数与输出点规模把 256 提升到 512 线程。
7. **双缓冲 / 流水**：ksize_one 使用 `BUFFER_NUM=2` 的 VECOUT 队列；gather/nc_transpose 使用
   `TQue<VECIN/VECOUT, BUFFER_NUM>` 形成 MTE2→V→MTE3 流水。
8. **fp32 带宽保护**：gather 对 fp32 把 `coreUsedForBestPerformance` 降为总核数的一半，
   避免访存带宽成为瓶颈。

## 7. 模板与测试覆盖映射

> 验证状态：`已运行验证` 表示该 case 在 TTK `result.csv` 中真实运行且 PASS（证明外部行为与 golden 一致）；
> 内部模板归属仍为 `静态推断`（依据第 1.1 节硬件参数与源码阈值推导，TTK 不输出 tiling key）。
> 两者分开标注，避免把「行为验证」冒充成「分支覆盖验证」。

| 目标芯片 | 内部模板/分支 | 源码依据 | 完整外部触发条件 | case_id | 验证状态 |
|---|---|---|---|---|---|
| A5 | KsizeOne（700001） | `_ksize_one_tiling.cpp::IsCapable` | kernelSize=(1,1,1) 且 stride=(1,1,1)，NCDHW | 5, 6 | 已运行验证（行为）/ 模板归属静态推断 |
| A5 | NcTranspose（500001） | `_tiling_nc_transpose.cpp::IsCapable` | NCDHW、dilation=1、无 padding、`D*H*W<=INT32_MAX`、kD*kH*kW<=128、`N*C>=3072`、输出空间体积>=32 | 7, 8 | 已运行验证（行为）/ 模板归属静态推断 |
| A5 | Gather 无 padding + 32 位索引（400001） | `_gather_tiling.cpp::GetTilingKey` + `InitializationVars` | NCDHW、dilation=1、无 padding、fp32 或 `D*H*W>32767` 的 fp16/bf16 | 9, 10, 19 | 已运行验证（行为）/ 模板归属静态推断 |
| A5 | Gather 有 padding + 32 位索引（400002） | 同上 | 同上且 padding 非零或 `ceil_mode` 造成隐式 padding | 10, 17 | 已运行验证（行为）/ 模板归属静态推断 |
| A5 | Gather 有 padding + 16 位索引（400012） | 同上 | NCDHW、fp16/bf16 且 `D*H*W<=32767` 且存在 padding | 12、18、20 | 已运行验证（行为）/ 模板归属静态推断 |
| A5 | Gather 无 padding + 16 位索引（400011） | 同上 | NCDHW、fp16/bf16 且 `D*H*W<=32767` 且无 padding | 2、11 | 已运行验证（行为）/ 模板归属静态推断 |
| A5 | BigKernelRegbase（611110） | `_tiling_big_kernel_regbase.cpp::IsCapable` | NCDHW、dilation=1、`W_kernel*itemsize>=64`（fp32 需 W_kernel>=16，fp16/bf16 需 >=32） | 13, 14 | 已运行验证（行为）/ 模板归属静态推断 |
| A5 | SIMT NCDHW（600001 / 600101） | `_simt_tiling.cpp::GetTilingKey` | 兜底：dilation>1，或窗口体积/输出点规模不满足其余模板 | 1, 15 | 已运行验证（行为）/ 模板归属静态推断 |
| A5 | SIMT NDHWC（600002 / 600102） | 同上 | data_format=NDHWC（其余模板均要求 NCDHW） | 3, 4 | 已运行验证（行为）/ 模板归属静态推断 |
| A5 | int64 索引输出 | `op_api` 把 indices dtype 翻译为属性 `dtype=9` | indices_dtype=9 | 4, 6, 8, 12, 14, 20 | 已运行验证 |
| A5 | 4 维输入（aclnn 层 unsqueeze/squeeze，ND 排布） | `aclnn_max_pool3d_with_argmax.cpp::View4Das5D` | 输入为 (C,D,H,W) | 16 | 已运行验证 |
| A5 | 非连续输入（aclnn 层 Contiguous） | 同上 | 输入是带步长视图 | 17 | 已运行验证 |
| A5 | 4 维输入 + NCDHW 排布 | `View5Das4D` → `ReFormat(NCDHW)` | 4 维 self 且 storage format 为 NCDHW | 不适用 | **已运行验证的设备限制**：TTK 复现 `transdata.cpp:152 rank does not match format`（format=NCDHW, shape=[16,4,4,4]），改用 ND 后 PASS；需求契约按 ND 描述 4 维输入 |
| A5 | 归约退化分支（`SMALL/BIG_KERNEL_ELEMENTS_THRESHOLD` 且 `H_out*W_out==1`） | `_gather_tiling.cpp::IsBasicConfigUnsupported` | 窗口元素数在 [512,1024] 且输出 H_out=W_out=1 | 未覆盖 | 未覆盖：该组合要求极大输入与极小输出，与 20 条名额冲突 |
| A5 | 稀疏窗口分支（`strictNoOverlap>=2` 且窗口元素数 < 25/64） | `_gather_tiling.cpp::IsExcludedByKernelHeuristics` | 至少 2 个方向 stride>kernel 且窗口元素数很小 | 9（近似）、11（近似） | 已运行验证（行为）/ 静态推断：case 9/11 的 stride=kernel 属于 `noOverlap` 而非 `strictNoOverlap`，严格分支未覆盖 |
| A5 | 64 位索引计算（400021/400022） | `InitializationVars` | `D*H*W > INT32_MAX` | 未覆盖 | 未覆盖：需要单通道超过 2^31 元素（>8GB），超出常规用例规模 |
| A5 | NcTranspose 的 fp16 delta 溢出回退 | `IsCapable` 的 `maxDelta > INT16_MAX_LIMIT` | fp16/bf16 且 `(kD-1)*H_in*W_in+(kH-1)*W_in+(kW-1) > 32767` | 未覆盖 | 未覆盖：需要极大空间尺寸的 fp16 输入 |
| A5 | BigKernel 多子核协作（`multiCoreNum > 1`） | `DoUBTiling` 的 `totalIdx <= coreNum/2` | 输出点极少但窗口很长 | 14（近似） | 已运行验证（行为）/ 静态推断：case 14 输出点 96 > 32，未触发协作分支 |
| A5 | SIMT 512 线程分支（600101/600102） | `DoOpTiling` 的 `isThreadNum512` | 窗口元素数>=64 且输出点数 > 512*64，或 fp32 全非重叠且输出点数 > 512*64 | 未覆盖 | 未覆盖：需要输出点超过 32768 且窗口体积>=64 的组合 |
| A5 | 空张量 | `aclnn_max_pool3d_with_argmax.cpp` 的 `IsEmpty` 提前返回 | 任一维为 0 | 不适用 | 需求契约为非空输入，不生成异常用例 |
| A5 | 全 padding 窗口丢弃（ceilMode） | `infershape::UpdateMaxShape` | ceilMode=True 且 `(D_out-1)*sD >= D_in+pD` | 12、17 | 已运行验证（行为）/ 模板归属静态推断 |

## 8. 源码依据与需求决策

### 8.1 golden 来源与提取

- 来源：`tests/assets/golden.py` 的 **kernel 入口** `max_pool3d_with_argmax_v2_golden`
  （`__golden__["kernel"]`），并参考同文件 aclnn 入口 `aclnn_max_pool3d_with_argmax_golden`
  与 `tests/st/aclnnMaxPool3dWithArgmax/executor_aclnnMaxPool3dWithArgmax.py`。
- 提取方式：源码 golden 是 numpy 输入 + `**kwargs` 测试框架参数，核心是
  `torch.nn.MaxPool3d(kernel_size, stride, padding, dilation, ceil_mode, return_indices=True)`。
  规范化后改成纯 torch、单公开函数 `max_pool3d_with_argmax_v2`，去掉 `__golden__`、`**kwargs`、
  `input_formats/output_formats` 等框架钩子，把 NDHWC 转置、4D unsqueeze/squeeze、dtype 升精度与回写
  固化为显式逻辑。
- 参数命名按 aclnn 表（`kernelSize/stride/padding/dilation/ceilMode`）+ 算子属性 `data_format`；
  索引类型用 `indices_dtype`（3=int32、9=int64）表达，对应算子属性 `dtype`，与源码 golden 的
  `dtype` 语义一致（源码：3 → int32，9 → int64）。

### 8.2 语义核对

| 语义点 | 结论 | 依据 |
|---|---|---|
| 索引含义 | 通道内 D×H×W 展平偏移 | SIMT kernel `idxOffset = d*H*W + h*W + w`；gather/nc_transpose 换算回真实输入坐标；torch `max_pool3d(return_indices=True)` 语义相同 |
| NDHWC 下索引语义 | 与 NCDHW 相同（与内存排布无关） | kernel 先按 NCDHW 逻辑视图计算，再转置输出；torch channels_last_3d 与 contiguous 的 indices 实测一致 |
| 4 维输入 | 视为 (C,D,H,W)，batch=1；按 ND/NCHW 排布声明，NCDHW 排布在算子内部 `View5Das4D` 处失败 | aclnn `View4Das5D`；torch 4D 输入实测与 unsqueeze 后一致；TTK probe 证据见 9.4 |
| 升精度 | fp16/bf16 按 fp32 比较，输出转回原 dtype | 源码 golden 与 executor 均先转 float32 |
| padding 取值 | 负无穷，越界点不参与比较 | 文档“补充的位置填写负无穷”；gather IS_PAD 分支与 SIMT 起点钳制 |
| ceilMode 修正 | 输出 shape 减 1，丢弃完全落在右侧 padding 的窗口 | `PoolingOutShape` / `UpdateMaxShape` 与 torch 一致 |
| 并列最大值 | 取扫描顺序第一个（gather/SIMT 用严格大于比较）；torch 同样取第一个；用例使用连续均匀分布避免并列 | 源码比较逻辑 + torch 实测 |
| NaN | SIMT `CycleUpdate` 中 `isnan` 优先命中；torch 亦传播 NaN | 未纳入用例（契约未要求） |
| 空张量 | 算子直接返回（不报错） | `IsEmpty` 提前返回；需求契约为非空输入 |

### 8.3 CPU 对照结果

- 用 7 组代表性配置（NCDHW/NDHWC × fp16/fp32 × 4D/5D × ceilMode × dilation>1 × int32/int64）
  在 CPU 上同时运行规范化 golden 与源码 golden，`y` 与 `argmax` 均**逐元素完全一致**（无误差）。
- 用 20 个用例的实际输入再跑一遍规范化 golden，输出 shape/dtype 与 `note.expected` 全部一致。

### 8.4 需求决策（AI 自行确定，非源码事实）

1. 需求契约以 **aclnn 入口**为外部行为基准（4 维归一化、NDHWC 支持、int32/int64 索引、非连续输入）
   而不是仅 kernel 入口；kernel 入口同语义。
2. `indices_dtype` 作为 golden 参数暴露（对应算子属性 `dtype`），默认 3；取值仅允许 3/9。
3. 用例统一使用有限均匀分布 `[-1,1]` 或 `[-2,2]`，避免并列最大值导致索引歧义。
4. 20 个名额优先覆盖「模板 × dtype × 布局 × 索引类型」，不再分配异常输入用例。
5. 输出 `argmax` 要求与 golden 二进制一致（不做容差），`y` 按生态精度标准判定。

### 8.5 用户覆盖与来源冲突

- 用户显式给出的 `PATH`、输出目录、golden 路径、文档路径优先于自动发现，均按用户值采用。
- 用户提示「文档与 st 代码有多个版本，注意选对版本」：`docs/` 下三份文档中只有
  `aclnnMaxPool3dWithArgmax.md` 与算子名匹配；`tests/st/` 下 `aclnnMaxPool2dWithIndices`、
  `aclnnMaxPool2dWithMask` 属 2D 兄弟算子，已排除；只使用 `tests/st/aclnnMaxPool3dWithArgmax/`
  与 `tests/st/arch35/ttk_aclnn_max_pool3d_with_argmax_st.csv`。
- 算子名 `MaxPool3DWithArgmaxV2` 与目录推导的 `MaxPool3dWithArgmaxV2` 不一致，以源码注册名为准。

### 8.6 TTK 执行状态

见第 9 节。

## 9. TTK 验证状态与遗留事项

### 9.1 执行状态

| 项 | 值 |
|---|---|
| TTK_REPO | `/home/s00940212/RSI/requirement_new/.claude/skills/ops-test-kit`（`python3 -m ttk info` 识别到 8 张 `Ascend950DT_9582`） |
| TTK 技能 | `/home/s00940212/RSI/requirement_new/.claude/skills/ttk-aclnn-adapt`（契约要求的 `<TTK_REPO>/.claude/skills/ttk-aclnn-adapt` 在 ops-test-kit 内不存在，经用户此前的同类任务确认改用该副本） |
| 状态 | **executed** |
| 用例数 | 20 |
| PASS / FAIL / SKIP | **20 / 0 / 0** |
| 结果文件 | `ttk/debug/result_final.csv`（修复前的全量记录保留为 `ttk/debug/result.csv`） |
| 交接文件 | `ttk/debug/handoff.json`（`status=executed`，`failures=[]`） |

### 9.2 精度分布

- `y`：所有用例 `max_abs_error = 0.0`，`matched_ratio = 1.0`，按 `mix_tolerance` 判定 PASS。
- `argmax`：所有用例按 `binary_equal` 判定，与 golden 逐元素完全一致。

### 9.3 回流修正记录（第五步）

| 轮次 | 触发 | 归因 | 动作 | 结果 |
|---|---|---|---|---|
| 1 | case 16（4D 输入 + NCDHW）返回 `ACLNN_EXECUTE_FAILED` | 首轮归因为 `operator_defect`；复跑与 NCHW/ND probe 证明 golden 与数据无误 | 按 `case` 归因修订：4D 输入是 (C,D,H,W)，aclnn 语义下其 storage format 为 ND/NCHW，`note.layout` 与 `expected.*.layout` 由 `NCDHW` 改为 `ND`，shape/dtype 不变；`cases.yaml` 与 `cases.csv` 同步，仍 20 条 | 复跑 `precision_status=PASS`（y maxdiff=0，argmax binary_equal） |

未放宽任何 tolerance，未删除用例，未修改 golden。

### 9.4 遗留事项与未验证项

1. **4 维输入 + NCDHW 排布不可用**：算子 `View5Das4D` → `ReFormat(NCDHW)` 在 rank-4 张量上失败
   （`transdata.cpp:152 input tensor shape's rank does not match format, format is: NCDHW, shape is: [16,4,4,4]`）。
   证据：`ttk/debug/rerun_16.log`、`ttk/debug/result_rerun_16.csv`；同 shape 改 NCHW/ND 均 PASS
   （`ttk/debug/probe_4d_result.csv`）。需求契约因此规定 4 维输入按 ND/NCHW 声明。
2. **`stride = []`**：TTK 的 attributes 无法无歧义表达空 `aclIntArray`，适配时展开为等价的
   `[kD, kH, kW]`（文档语义：长度 0 时取 kernelSize），需求契约仍保留空列表语义。
3. **`indices_dtype` 不是 aclnn 形参**：适配时只映射为输出槽 `indices` 的 dtype。
4. **TTK 的 `Memory check` 行**是 OOB 探针结果，不参与精度判定（全部用例均为 UNKNOWN）。
5. **未覆盖分支**（见第 7 节）：64 位索引计算、归约退化区间、严格稀疏窗口、nc_transpose 的 fp16 delta
   溢出回退、BigKernel 多子核协作、SIMT 512 线程。这些分支需要 GB 级张量或极端 shape，与 20 条名额冲突，
   未做实测，仅由源码静态推导。
6. **模板归属未实测**：TTK 走 aclnn 通路且不输出 tiling key，第 7 节的模板归属为静态推断；
   已验证的是「该外部条件下 aclnn 行为与 golden 一致」。

