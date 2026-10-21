# AvgPool3D 算子设计分析（A5）

> 芯片种类：**A5**（Ascend 950PR&950DT / 3510）。本文件只描述 A5 范围内的实现、配置与分支，其他芯片一律视为范围外。

## 1. 芯片范围与源码布局

### 1.1 芯片范围

| 项 | 本次范围 | 源码位置 | 状态 |
|---|---|---|---|
| A5（Ascend 950PR&950DT、3510） | 采用 | kernel: `op_kernel/avg_pool3_d_apt.cpp` + `op_kernel/arch35` 等价路径（实际为 `pooling/pool_3d_common/op_kernel/arch35/`）；tiling: `pooling/pool_3d_common/op_host/arch35/`；config: `op_host/config/ascend950/`、`op_host/config/ascend350/` | 生效 |
| A2（Atlas A2 910B） | 范围外 | `op_kernel/avg_pool3_d.cpp`（NDHWC/NCDHW 多模板向量版）、`op_host/config/ascend910b/` | 排除 |
| A3（Atlas A3 910_93） | 范围外 | 同上向量版 + `op_host/config/ascend910_93/` | 排除 |
| Kirin x90 / 9030 | 范围外 | `op_host/config/kirinx90/`、`op_host/config/kirin9030/`、`GetKirinCoreConfig()` 分支 | 排除 |
| Atlas 310P / Atlas 训练系列 / Atlas 200I 500 A2 | 范围外 | 文档「产品支持情况」中标注为不支持或仅推理系列 | 排除 |

`op_host/avg_pool3_d_def.cpp` 中 A5 的注册为：

- `AICore().AddConfig("ascend950", aiCoreConfig)` 与 `AddConfig("ascend350", aiCoreConfig)`；
- `aiCoreConfig` 使用 `ExtendCfgInfo("opFile.value", "avg_pool3_d_apt")`，即 A5 上 kernel 入口是 `avg_pool3_d_apt.cpp`，而不是 `avg_pool3_d.cpp`；
- A5 的 dtype 集合为 `{DT_FLOAT16, DT_FLOAT, DT_BF16}`（`AvgPool3DXDataType`），格式 `FORMAT_ND`，`PrecisionReduceFlag(true)`。

源码检查确认：A5 在 `op_host/*_def.cpp`、`op_kernel/`（apt 入口及其 arch35 头文件）、`op_host/config/ascend950|ascend350/` 三处均有对应实现与配置，无缺口。

### 1.2 `PATH` 实际布局

```text
ops-nn/pooling/avg_pool3_d/
├── docs/aclnnAvgPool3d.md          # 主接口文档（采用）
├── docs/aclnnAvgPool2d.md          # 同目录兄弟算子文档
├── examples/test_aclnn_avgpool3d.cpp
├── framework/avg_pool3d_tf_plugin.cpp
├── op_api/aclnn_avgpool3d.{h,cpp}  # aclnn 入口（采用）
├── op_api/aclnn_avgpool2d.{h,cpp}  # 2d 版本
├── op_api/avgpool3d.{h,cpp}        # l0op 内部接口
├── op_graph/avg_pool3_d_proto.h    # REG_OP(AvgPool3D)
├── op_host/avg_pool3_d_def.cpp
├── op_host/avg_pool3_d_infershape.cpp
├── op_host/avg_pool3_d_tiling.{h,cpp}      # A2/A3 向量版 tiling（范围外）
├── op_host/avg_pool_cube_tiling.{h,cpp}
├── op_host/config/ascend950|ascend350|ascend910b|ascend910_93|kirin*/
├── op_kernel/avg_pool3_d.cpp               # A2/A3 kernel 入口（范围外）
├── op_kernel/avg_pool3_d_apt.cpp           # A5 kernel 入口（采用）
├── op_kernel/avg_pool3d_*.h                # A2/A3 模板实现
└── tests/
    ├── assets/golden.py                    # golden 首选来源
    ├── st/aclnnAvgPool3d/{atk_*.json,executor_*.py}
    └── st/arch35/ttk_*.csv
```

与标准布局的差异：A5 的 kernel 实现被抽到**兄弟目录** `pooling/pool_3d_common/` 下（`op_kernel/arch35/` 与 `op_host/arch35/`），由 `avg_pool3_d_apt.cpp` 以相对路径 `../pool_3d_common/arch35/*.h` 引入；tiling 由 `op_host/avg_pool3_d_tiling.cpp` 里的 `Tiling4AvgPool3DNNRegBase` 委派给 `PoolTilingRegistry::GetInstance().DoTilingImpl(context)`，实际模板类都注册在 `pool_3d_common/op_host/arch35/`。这两个目录是只读参考，未做任何修改。

### 1.3 文档版本选择

| 候选 | 判定 | 理由 |
|---|---|---|
| `docs/aclnnAvgPool3d.md` | **采用** | 文件名精确匹配 `ops_pascal = AvgPool3D`；接口名 `aclnnAvgPool3dGetWorkspaceSize` 与 `op_api/aclnn_avgpool3d.h` 中的声明逐参一致 |
| `docs/aclnnAvgPool2d.md` | 排除 | 对应兄弟算子 `aclnnAvgPool2d`，与 `op_host/avg_pool3_d_def.cpp` 的注册无关 |
| `README.md` | 排除（仅背景） | 算子级说明，非接口契约 |

`ops_pascal` 校验：`op_host/avg_pool3_d_def.cpp` 中 `class AvgPool3D : public OpDef` + `OP_ADD(AvgPool3D)`，`op_graph/avg_pool3_d_proto.h` 中 `REG_OP(AvgPool3D)`，目录名 `avg_pool3_d` 与类名一致，无需改名。

无版本歧义（目录内没有 `aclnnAvgPool3dV2.md` 之类候选），未触发询问用户。

### 1.4 aclnn 接口映射

`op_api/aclnn_avgpool3d.h` 声明的唯一入口（与文档一致）：

```cpp
aclnnStatus aclnnAvgPool3dGetWorkspaceSize(
    const aclTensor* self, const aclIntArray* kernelSize, const aclIntArray* stride,
    const aclIntArray* padding, bool ceilMode, bool countIncludePad, int64_t divisorOverride,
    aclTensor* out, uint64_t* workspaceSize, aclOpExecutor** executor);
```

| aclnn 形参 | 需求包对应 | 说明 |
|---|---|---|
| `self` | `x` | 4D 或 5D，ND，fp16/fp32/bf16，支持空 tensor 与非连续 |
| `kernelSize` | `kernelSize` | aclIntArray，长度 1 或 3 |
| `stride` | `stride` | aclIntArray，长度 0、1 或 3 |
| `padding` | `padding` | aclIntArray，长度 1 或 3；注意图模式属性 `pads` 还允许长度 6 |
| `ceilMode` | `ceilMode` | bool |
| `countIncludePad` | `countIncludePad` | bool |
| `divisorOverride` | `divisorOverride` | int64，0 表示不生效 |
| `out` | `y` | 与 `self` 同 dtype 同 format |

aclnn 层会把长度 1/0 的 `kernelSize`/`stride`/`padding` 统一展开成 3 元组再下发给 l0op（`aclnn_avgpool3d.cpp` 中 `newKernel`/`newStride`/`newPad`），因此设备侧的属性长度语义是「已展开」。需求包的 `kernelSize`/`stride`/`padding` 保留外部原始长度语义（0/1/3），由 golden 展开。

## 2. 实现概览

A5 通路：`aclnnAvgPool3d` → `BuildAvgPool3dGraph` → `l0op::AvgPool3D` → kernel `avg_pool3_d_apt.cpp`（`ExtendCfgInfo("opFile.value", "avg_pool3_d_apt")`）→ `pool_3d_common/op_kernel/arch35/` 下各模板类。

主要数据流：

1. host 侧 `CheckParams` 校验 dtype/format/shape，`CheckOutputShape` 用与文档一致的公式推导 `D_out/H_out/W_out` 并与传入 `out` 比对；空 tensor 直接返回。
2. host 侧决定 `data_format`：
   - `IsDimDDownsamping`（kH=kW=sH=sW=1）为真 → 保持 `NCDHW`；
   - 否则若 `IsEnableNCDHW` 为真 → 保持 `NCDHW`；
   - 否则 → `dataFormat = "NDHWC"`，并插入一次 `Transpose(N,C,D,H,W → N,D,H,W,C)`，算完再 `Transpose` 回来。
   `IsEnableNCDHW` = `(isCapable && isSamePoolSize && enableNC) || isBigKernelFlag || isRegbaseBatchMerge`，其中 `isCapable = (kD*kH*align8(kW) <= 128) && (kW <= 16)`。**A5 是 regbase，`isRegbaseBatchMerge = IsRegbase() && !IsBatchMergeBigKernel(...)` 大多数情况下为真**，因此实际上多数非 `IsDimDDownsamping` 的用例仍会走 NCDHW。
3. 4D 输入先 `Reshape` 成 5D（`C,D,H,W → 1,C,D,H,W`），算完再 `Reshape` 回来；这正是「4D 输入 batch=1」的语义来源。
4. device 侧 `avg_pool3_d_apt.cpp` 按 **tiling key** 分发到不同模板类，模板内 `Init → Process`，输出经 `ViewCopy` 写回 `out`。

A5 tiling 入口链：`Tiling4AvgPool3D`（`op_host/avg_pool3_d_tiling.cpp`）→ `compileInfo->is_regbase` 为真 → `Tiling4AvgPool3DNNRegBase` → `PoolTilingRegistry::DoTilingImpl` → 按优先级遍历 `pool_3d_common/op_host/arch35/` 中注册的模板类。

## 3. 模板设计

A5 的模板由 `pool_3d_common/op_host/arch35/pool_3d_*_tiling.cpp` 以 `REGISTER_POOL_TILING_TEMPLATE("AvgPool3D", <类>, <优先级>)` 注册；`DoTilingImpl` 按优先级**升序**依次调用 `DoTiling()`，第一个返回非 `GRAPH_PARAM_INVALID` 的模板胜出。因此「优先级数字越小越先尝试」，而不是"最高优先级永远选中"。

| 优先级 | 模板类 | 触发条件（源码） | tiling key | kernel 类 |
|---|---|---|---|---|
| 0 | `Pool3DOneKsizeTiling` | `kD == kH == kW == 1`；NDHWC 且 `channels * dtypeSize > 256` 时放弃 | `100001` | `pool_3d_ksize_one_kernel.h` |
| 10 | `Pool3DNcdhwSmallKernelTiling` | `NCDHW`（任意通道）或 `NDHWC && dtypeSize*channels < VReg/4 && 无 padding`；且 `batches*outD*outH*outW >= coreNum`；且 `IsBufferCapable()` | `300001` 无 pad、`300004` 无 pad 稀疏、`300002` 有 pad、`300003` 有 pad 且 avg 且 `divisor==0` | `pool_3d_ncdhw_small_kernel{,_pad}.h` |
| 11 | `Pool3DNcdhwBigKernelTiling` | `NCDHW`；`batches*outD*outH*outW < coreNum*2` 时直接命中；否则要求 `kD*kH*kW*dtypeSize >= 256` 且三维中至少一维满足 `5*stride < kernel`（强重叠） | `511110` | `pool_3d_ncdhw_big_kernel.h` |
| 12 | `Pool3DSmallKernelNDHWCTiling` | `NDHWC`；`batches*outD*outH*outW*channels >= coreNum`；任一维 `stride >= 2*effectiveKsize` 时放弃；`IsBufferCapable()` | `200001` / `211110`（pad）/`211111`（pad+div）/`222220` / `222221` / `222222` | `pool_3d_ndhwc_small_kernel{,_pad}.h`、`pool_3d_ndhwc_big_channel{,_pad}.h` |
| 13 | `Pool3DBigKernelNDHWCTiling` | `NDHWC`；`batches*outD*outH*outW < totalCoreNum*2` 时直接命中；否则要求 `kD*kH*kW*channels*dtypeSize >= 256` | `411110` | `pool_3d_big_kernel_ndhwc.h` |
| 19 | `Pool3DSimtTiling` | `IsCapable()` 恒为 `true`（兜底） | `911100/911101/911110/911111`（NCDHW/NDHWC × int32/int64 索引） | `avg_pool_3d_simt.h` |

模板之间的计算差异：

- `Pool3DOneKsizeTiling`：kernel 全为 1，等价于按 stride 采样，不需要窗口求和，只做 UB 分块搬运。
- `Pool3DNcdhwSmallKernelTiling`：按 NCDHW 的通道维做向量化 gather/scatter，区分「无 pad / 有 pad / 有 pad 且需要真实除数（`divisor==0`）/ 稀疏 stride」四种路径。
- `Pool3DNcdhwBigKernelTiling`：`kD*kH*kW*dtypeSize >= 256` 且窗口强重叠，用 UB 缓存一行的方式复用重叠数据；`batches*outD*outH*outW < coreNum*2` 的小规模直接走该模板以保证并行度。
- `Pool3DSmallKernelNDHWCTiling`：按 NDHWC 末维连续做向量化，通道大时切到 big-channel 变体。
- `Pool3DBigKernelNDHWCTiling`：`kD*kH*kW*C*dtypeSize >= 256`，按输出索引切分，每核独立完成一个输出点的完整窗口求和。
- `Pool3DSimtTiling`：标量 SIMT 实现，逐输出点四路展开累加（源码中 `float s0..s3`），索引宽度按总元素数选择 int32/int64，是所有模板都不匹配时的兜底。

### 3.1 输出形状推导（host 与 device 一致）

`pool_3d_tiling_common.cpp:InferCalculateOutShape` 与 `avg_pool3d.md` 公式、`avg_pool3d_infershape.cpp:CalcAvgPool3DOutputShape`、`aclnnAvgPool3d.cpp:PoolingOutShape` 四处实现完全一致：

```text
ceil_mode=False: out = (in + padL + padR - k) / s + 1
ceil_mode=True : out = (in + padL + padR - k + s - 1) / s + 1
                 若 (out - 1) * s >= in + padL，则 out -= 1
```

aclnn 侧 `padding` 只允许长度 1 或 3（`CheckShape` 中 `padding->Size() != 1 && != PAD_SIZE` 即报错），因此 `padL = padR = pads[d]/2` 的实际语义是「两侧各 `pads[d]` 层」——即 `PoolingOutShape` 中的 `inputSize + padL * 2`。需求包与 golden 采用同一解释。

### 3.2 会改变计算结果的 host 侧量

- `RefineShape`（`avg_pool3d_tiling_common.cpp`）：当某维 `outShape == 1` 时，把该维 `kernelSize` 裁剪到 `<= inputShape + pad`，并把 `stride` 置为裁剪后的 `kernelSize`。**这是提效改写，不改变数学结果**（输出只有 1 个位置，窗口取多大都只影响除数，而除数相应同步收窄）。
- aclnn 侧 `IsDimDDownsamping` 只在 `kH = kW = sH = sW = 1` 时为真，此时 D 方向是纯归约、后两维原样，走 NCDHW 直通路径。

## 4. 分核设计

A5 各模板的分核策略：

| 模板 | 并行度来源 | 分核公式 |
|---|---|---|
| OneKsize（0） | 输出点的 `batches × outD × outH × outW` | `ubFactorN_` 由 UB 容量决定，其余维全载或按 UB 切；核数由 `totalIdx / coreNum` 均分 |
| NcdhwSmallKernel（10） | `batches*outD*outW*outH` | `DoUBTiling` 按输出点总数均分到 `coreNum`，`blockFactor_ = totalIdx / coreNum`、`blockTail_ = totalIdx % coreNum` |
| NcdhwBigKernel（11） | `batches*outD*outH*outW` | 同上；`blockFactor_ == 0`（输出点少于核数）时 `coreNums_ = totalIdx_`，多余核空转 |
| NdhwcSmallKernel（12） | `batches*outD*outW*outH*channels` | 按 `ndhwc` 的连续块切分 |
| NdhwcBigKernel（13） | `batches*outD*outH*outW` | `coreNums_ = blockFactor_ == 0 ? totalIdx_ : totalCoreNum_` |
| Simt（19） | 输出元素总数 `N*C*outD*outH*outW` | `avg_pool_3d_simt.h` 中按 `blockIdx` 切分，索引宽度按 `xSize/ySize <= INT32_MAX` 选 int32/int64 |

两条「规模小于核数」的短路规则值得注意：

- 优先级 11 的 `IsCapable`：`batches*outD*outH*outW < coreNum*2` 时**无条件命中**（不要求大 kernel 或强重叠），目的就是保证小规模用例也能铺满核；
- 优先级 13 同理：`batches*outD*outH*outW < totalCoreNum*2` 时直接命中。

A5 上 `coreNum` 取 `ascendcPlatform.GetCoreNumAiv()`。实测平台 `Ascend950DT_9582` 的 AIV 核数为 64（`vector_core_cnt`），UB 256KB（`248KB` 可用的 shared 值），UB block size 32B。

小规模用例（如 case 6 的最小输入 `1×1×1×1×1`）会因 `batches*outD*outH*outW = 1 < coreNum*2` 而落到 NcdhwBigKernel，只启 1 个核。

## 5. 分块设计

| 量 | 源码 | 含义 |
|---|---|---|
| `UB_RESERVED_SIZE` | `pool_3d_ncdhw_small_kernel_tiling.cpp` 中 `UB_RESVERVED_SIZE`（512 / 1024，各模板不同） | UB 中留给系统与索引的保留区 |
| `oneBlockNum_` | `GetUbBlockSize(context_) / dtypeSize` | 一个 UB block（32B）能放的元素数：fp32 为 8，fp16/bf16 为 16 |
| `VReg` | `GetVRegSize(context_)` | 一个 vector register 的字节数，决定一次向量指令处理的元素数 |
| `availableUb_` | `(ubSize_ - divisorUbSize_ - UB_RESERVED_SIZE) / dtypeSize` | 单核可用于数据搬运的元素数 |
| `divisorUbSize_` | `CalcDivsiorUbSize(isPadding_)` | 需要逐点计算除数时预留的 UB（最大 64KB，`MAX_DIVISOR_UB = 64 * 1024`） |
| `isSparseD/H/W_` | stride 与 effectiveKsize 的比较 | `stride >= 2 * effectiveKsize` 且 `outShape > 1` 时视为稀疏窗口，可用更省 UB 的 gather 路径；W 维在 NCDHW 下的阈值额外带 `SPARSEW_THR / dtypeSize` 修正 |
| `effectiveKsize_[i]` | `(kernelSize[i] - 1) * dilation[i] + 1` | 本算子 `dilation` 恒为 `{1,1,1}`，故 `effectiveKsize == kernelSize` |
| `isPadding_` | 六向 pad 任一非 0；或 `ceilMode` 且 `(out-1)*s + k > in`（窗口会越过输入边界） | 决定是否走带 padding 的模板变体 |

对齐：所有 UB 内搬运按 32B（`base_alignment_bytes`）对齐，元素侧即 fp32 8 元素、fp16/bf16 16 元素。输出末块用 mask 或长度参数处理尾块，不做越界写。

A5 与 A2/A3 的差异：A2/A3 走 `avg_pool3_d.cpp` 的向量模板（tiling 在 `op_host/avg_pool3_d_tiling.cpp`，采用 `RESERVED_UB_SIZE = 10KB`、`INDEX_BUF_SIZE = 9KB`、`INDEX_BUF_NUM = 9`、`BLOCK_LEN = 256`、`MAX_TILE_NUM = 4095` 等常量，模式编号 `MODE_SPLIT_C=1 / SPLIT_W=2 / MULTI_W=3 / REDUCE_D=4 / NORMAL=5 / BIG_KERNEL=6`，tiling key = `mode * 10 + dtypeKey`）。这些常量与分支在本需求中不采用。

## 6. 性能调优技巧

只列源码里真实存在、且对 A5 生效的机制：

1. **模板优先级串行试探**：`DoTilingImpl` 按优先级 0→19 依次尝试，小 kernel 单 ksize 的用例（优先级 0）先被截走，避免走通用模板的额外开销。
2. **四种 NCDHW 路径**：无 pad / 有 pad / 有 pad 且真实除数 / 稀疏 stride 分别对应 `300001` / `300002` / `300003` / `300004`，其中 `300004` 依赖 `isSparseD/H/W_` 判断窗口不重叠，可用更小的 UB 占用。
3. **强重叠大 kernel 复用**：优先级 11 的 `IsStrongOverlap(k, s) = 5*s < k`，窗口强重叠时按「缓存一行 + 滑动」的方式复用数据，减少 GM 流量。
4. **小规模铺满核**：优先级 11/13 的 `< coreNum*2` 短路，避免核不饱和。
5. **NDHWC 直通判断**：`IsEnableNCDHW` 中的 `enableNC = 256 < N*C < 960`、`isCapable = kD*kH*align8(kW) <= 128 && kW <= 16`；不满足时插一次 Transpose 换成 NDHWC 通道连续布局，换取 gather/scatter 效率。这是「结果不变、布局变」的取舍。
6. **精确保留 dtype 的累加**：`pool_3d_common.h` 中 fp16/bf16 一律 `Cast` 到 `float32_t` 累加再转回（`castTraitB16ToB32` / `castTraitB32ToB16`），SIMT 路径同样是 `static_cast<float>` 累加后 `static_cast<X_T>(sum / divisorFactor)`。这是 A5 上 fp16/bf16 精度的关键前提。

## 7. 模板与测试覆盖映射

目标芯片固定为 **A5**。`case_id` 对应 `cases.csv`；「已运行验证」只在 TTK `debug/result.csv` 中真实出现该 case 后才可标注，否则为「静态推断」。

| 目标芯片 | 内部模板/分支 | 源码依据 | 完整外部触发条件 | case_id | 验证状态 |
|---|---|---|---|---|---|
| A5 | 优先级 10 无 pad 路径（`300001`） | `pool_3d_ncdhw_small_kernel_tiling.cpp:IsCapable/GetTilingKey` | 5D NCDHW 语义，`padding=0`，`stride=kernel`，输出点数 ≥ 核数 | 1, 18 | 已运行验证 |
| A5 | 优先级 10 有 pad，`divisor==0` 的真实除数路径（`300003`） | 同上 `GetTilingKey` 中 `isPadding_ && poolMode==AVG && divisor_==0` | 5D，`padding` 非 0（含等于 `kernel/2`），`countIncludePad=False` 或 `divisorOverride=0` | 5, 14 | 已运行验证 |
| A5 | 优先级 10 有 pad，指定除数路径（`300002`） | 同上，`isPadding_ && divisor_ != 0` | 5D，`padding` 非 0，`divisorOverride` 非 0 | 9 | 已运行验证 |
| A5 | 优先级 10 稀疏 stride（`300004`） | 同上 `isSparseW_/isSparseH_/isSparseD_`：`stride >= 2*effectiveKsize && outShape > 1` | 5D，某一维 `stride >= 2*kernel` 且该维输出 > 1 | 12 | 已运行验证 |
| A5 | 优先级 11 小规模短路（`511110`） | `pool_3d_ncdhw_big_kernel_tiling.cpp:IsCapable` 首条 `batches*outD*outH*outW < coreNum*2 → true` | 5D，输出点数 < 2 × AIV 核数 | 6 | 已运行验证 |
| A5 | 优先级 11 强重叠大 kernel 的窗口循环（`511110`） | 同上 `IsStrongOverlap` = `5*stride < kernel` | 三维中至少一维 `5*s < k`（case 20 的 D 维：`5*1 < 110`） | 20 | 已运行验证 |
| A5 | 优先级 12 NDHWC 小 kernel（`200001`） | `pool_3d_small_kernel_ndhwc_tiling.cpp:IsCapable`：`NDHWC`、`batches*outD*outH*outW*C >= coreNum`、无 `stride >= 2*k`、`IsBufferCapable()` | aclnn 判定走 NDHWC 后，按 NDHWC 语义满足上述条件 | 20 | 已运行验证 |
| A5 | 优先级 0 ksize 全 1（`100001`） | `pool_3d_one_kize_tiling.cpp:IsCapable` | `kernelSize = [1,1,1]`（或长度 1 的 `[1]`） | 19（`kernelSize=[2]` 不命中，见下） | 未覆盖（见备注 R1） |
| A5 | aclnn 侧 `IsDimDDownsamping` 为真的 NCDHW 直通 | `aclnn_avgpool3d.cpp:IsDimDDownsamping`（`kH=kW=sH=sW=1`） | `kernelSize=[kD,1,1]`，`stride=[s,...]` 后两维为 1 且 kernel 后两维为 1 | 无（见备注 R2） | 未覆盖 |
| A5 | aclnn 侧插入 Transpose 换 NDHWC 的通路 | `aclnn_avgpool3d.cpp:BuildAvgPool3dGraph` 中 `dataFormat = "NDHWC"` 分支 | 非 `IsDimDDownsamping` 且 `IsEnableNCDHW` 为假：需要 `kW > 16`，或 `kD*kH*align8(kW) > 128`，且不是 big kernel | 无（见备注 R3） | 未覆盖 |
| A5 | 4D 输入 Reshape 为 5D 再 Reshape 回 | `aclnn_avgpool3d.cpp` 中 `selfDimNum == DIM_NUM_4D` 两处、`avg_pool3d_d_golden` 的 4D 语义 | 4D 输入 | 4, 5 | 已运行验证（4D 通路，见备注 R4） |
| A5 | 优先级 19 SIMT 兜底 | `pool_3d_simt_tiling.cpp:IsCapable` 恒 true | 以上模板全部不匹配时的任意合法输入 | 无（见备注 R5） | 未覆盖 |
| A5 | 非连续输入 | aclnn 文档 `self`/`out` 标注「非连续Tensor √」；`BuildAvgPool3dGraph` 先 `Contiguous` | `self` 为非连续视图 | 17 | 已运行验证 |

### 覆盖备注

- **R1（ksize 全 1 未覆盖）**：优先级 0 要求 `kD = kH = kW = 1`。现有 20 个用例中没有任何一条 `kernelSize` 全为 1（case 19 是 `kernelSize=[2]` 广播成 `[2,2,2]`，不命中），因此该模板路径**完全未覆盖**。取舍原因是 20 个名额要优先保证 dtype 三态、4D/5D、对齐/非对齐、padding 小于/等于 kernel/2、ceilMode、countIncludePad、divisorOverride、非连续视图等外部维度；`kernelSize` 全 1 只改变计算复杂度不改变数学语义，且相邻的「无重叠窗口」语义已由 case 1/12/18 覆盖。
- **R2（`IsDimDDownsamping` 未覆盖）**：触发需要 `kH = kW = sH = sW = 1`，即 `kernelSize=[kD,1,1]` 且 `stride` 后两维为 1。原 plan 中的 case `(1,1,4,4,4), k=[1,3,1]` 实际不满足（`kH=3`），已从 20 个用例中移除。该分支只影响布局选择，不改变数学结果。
- **R3（Transpose 通路，由 case 20 覆盖）**：触发条件是 `kD*kH*align8(kW) > 128` 或 `kW > 16`（`isCapable` 为假）、`CheckBigKernel` 为假、且 `IsBatchMergeBigKernel` 为真。case 20（`k=[110,1,2]`、`s=[1,1,2]`、输入 `1×4×120×3×3`）逐条满足：`110*1*8 = 880 > 128`；`bigKernel` 要求某维 `> 1024`，不成立；`IsBatchMergeBigKernel` 中 D 维 `overlap = 109 > 100` 且 `outD = 11 > 10` 使 `bigDimCount = 1`，H/W 两维 `kernel <= 2` 使 `smallKCount = 2`，故返回真。三者叠加使 `IsEnableNCDHW` 为假，`BuildAvgPool3dGraph` 插入 `Transpose` 换 NDHWC。**此前 §8.2 中「case 20 仍走 NCDHW」的判断是错的**（把 `isBatchMergeBigKernel` 为真误读成 `isRegbaseBatchMerge` 为真），已在此更正。真机 PASS 说明该 Transpose 通路结果正确。
- **R4（4D 支持，已由真机确认）**：`op_api/aclnn_avgpool3d.h` 声明 `self` 支持 4 维或 5 维。TTK 实测 case 4（4D float32）与 case 5（4D float16 + `countIncludePad=False`）均 PASS，说明 aclnn 层 `C,D,H,W → 1,C,D,H,W` 的补齐与回 `Reshape` 通路可用，此前「device 模板按 5D 取维可能导致 4D 走不通」的推断不成立。
- **R5（SIMT 兜底未覆盖）**：SIMT 是所有模板都不匹配时的兜底，且部分模板（如优先级 10）在 `IsBufferCapable()` 为假时会让位给 SIMT。TTK 真机跑出的 tiling key 可用于确认实际命中关系；本轮不构造专门触发 SIMT 的用例。

## 8. 源码依据与需求决策

### 8.1 源码事实

1. A5 的 kernel 入口是 `avg_pool3_d_apt.cpp`（`ExtendCfgInfo("opFile.value", "avg_pool3_d_apt")`），A2/A3 走 `avg_pool3_d.cpp`；tiling 侧 `compileInfo->is_regbase` 为真时走 `Tiling4AvgPool3DNNRegBase`。
2. A5 支持 dtype `{float16, float32, bfloat16}`，format `FORMAT_ND`（`op_host/avg_pool3_d_def.cpp` 的 `AvgPool3DXDataType`/`AvgPool3DXFormat`）。
3. `op_api/aclnn_avgpool3d.h` 明确 `self`/`out` 支持 4 维或 5 维、支持非连续、支持空 tensor。
4. `op_api/aclnn_avgpool3d.cpp:CheckShape` 只接受 `padding` 长度 1 或 3，`kernelSize` 长度 1 或 3，`stride` 长度 0/1/3。
5. `PoolingOutShape` 用 `inputSize + padL * 2`，配合 `padL = pads[d]`（展开后）——即 padding 语义是「两侧各 `pads[d]` 层」。
6. `pool_3d_tiling_common.cpp:GetPadInfo` 的约束是 `0 <= pad < kernelSize[d]`（tiling 侧），而 aclnn 侧 `CheckAttrValue` 是 `0 <= pad <= kernelSize[d] / 2`。二者取交集后，需求契约取 aclnn 的 `[0, kernelSize/2]`（更严），文档同义。
7. `golden`（`tests/assets/golden.py` 的 `aclnn_avg_pool3d_golden`）在 `pads` 全部 `pads[i] < ksize[i]/2` 时直接调 `torch.nn.functional.avg_pool3d(..., padding=pads)`；否则先按输出的最大范围补零再手工算除数。
8. `RefineShape` 只在 `!(divisorOverride == 0 && countIncludePad)` 时触发，属于提效改写。

### 8.2 基于代码的推断

| 推断 | 依据 | 置信度 |
|---|---|---|
| A5 上多数用例走 NCDHW，但「批量合并型大窗口」会被拦下并改走 NDHWC | `IsEnableNCDHW` 中 `isRegbaseBatchMerge = IsRegbase() && !isBatchMergeBigKernel`；A5 是 regbase，因此多数用例 `isRegbaseBatchMerge` 为真 → NCDHW。但 case 20 的 `IsBatchMergeBigKernel` 为真 → `isRegbaseBatchMerge` 为假，叠加 `isCapable`/`isBigKernelFlag` 均为假 → 走 NDHWC + Transpose | 高（case 20 真机 PASS，通路已被覆盖） |
| 4D 输入在 aclnn 层被补齐成 5D 后再进 device | `BuildAvgPool3dGraph` 中 4D 分支显式 `Reshape`；TTK case 4/5 真机 PASS | 高（已实测） |
| 优先级 10 在 `IsBufferCapable()` 为假时让位给 11/12/13/19 | `DoTilingImpl` 的优先级遍历语义 + `IsCapable` 返回值 | 高 |

### 8.3 AI 自行确定的规则（非源码事实）

| 规则 | 取值 | 理由 |
|---|---|---|
| `stride` 长度为 0 时按 `kernelSize` 取值 | golden 与 `cases.yaml` 均采用 | 与 acln 文档「长度为0（数值与kernelSize数值保持一致）」一致 |
| `padding` 三维解释为「两侧各 `padding[d]` 层」 | golden 采用 | 与 `PoolingOutShape` 的 `padL * 2` 一致 |
| `note.layout` 统一写 `"ND"` | 全部 20 个用例 | `op_host/*_def.cpp` 的 format 只有 `FORMAT_ND`；`data_format` 属性只出现在图模式（`op_graph/avg_pool3_d_proto.h`），aclnn 通路不暴露 |
| 用例中 `kernelSize`/`stride`/`padding` 保留外部原始长度 | 长度 0/1/3 | 与 aclnn 形参语义一致，展开由 golden 完成 |
| 不构造 NaN / Inf 用例 | 全部 value_range 有限 | aclnn 未对特殊值做契约要求；本算子对 NaN 无特殊语义（NaN 会自然传播），单独构造收益低 |

### 8.4 需求决策与来源覆盖

| 项 | 来源 | 说明 |
|---|---|---|
| 芯片种类 | 用户显式（本次未传，取默认） | **A5**；未被任何源码发现覆盖 |
| `PATH` | 用户显式 | `/home/s00940212/RSI/ops-nn/pooling/avg_pool3_d` |
| 输出路径 | 用户显式 | `/home/s00940212/RSI/requirement_new` → 需求文件夹 `avg_pool3_d/` |
| `TTK_REPO` | 用户显式 | `/home/s00940212/RSI/requirement_new/.claude/skills/ops-test-kit` |
| 接口文档 | 源码发现 | `docs/aclnnAvgPool3d.md` |
| golden 来源 | 源码发现 | `tests/assets/golden.py` 的 `aclnn_avg_pool3d_golden`（aclnn 入口，与需求契约一致），辅以 `avg_pool3_d_golden` 作对照 |
| aclnn 接口 | 源码发现 | `aclnnAvgPool3d`（`op_api/aclnn_avgpool3d.h`） |
| 输出数量/顺序 | 源码事实 | `op_host/avg_pool3_d_def.cpp` 只有一个 `Output("y")` |
| 属性名 | 源码事实（图模式）+ aclnn 形参 | 取 aclnn 形参名 `kernelSize`/`stride`/`padding`/`ceilMode`/`countIncludePad`/`divisorOverride` |

### 8.5 golden 提取与规范化的具体改动

1. 以 `aclnn_avg_pool3d_golden`（`self` 为 `torch.Tensor`，形参名与 aclnn 一致）为语义核心，删除 `**kwargs`、`attributes`、`tensor_formats` 等测试框架钩子。
2. 入口改名 `avg_pool3_d`（等于需求文件夹名），去掉 `self` 形参，补 `x: torch.Tensor` 与 `List[int]` 标注。
3. 去掉了源码 golden 的 `data_format` 形参与其 `ND`/`NCDHW` 转置分支——需求契约固定 ND，4D/5D 的秩差异用「4D 补 batch / 末尾去 batch」表达，语义等价。
4. `np.pad(inputx, ...)` 改为 `torch.nn.functional.pad(x_compute, (pW_l, back_w, pH_l, back_h, pD_l, back_d))`，并加 `[..., :out_d, :out_h, :out_w]` 切片。源码 golden 补零后直接用 `out_d/out_h/out_w` 算除数，padding 较小时 `avg_pool3d` 会额外输出一行/列，切片后与源码取到的位置一致（已用 21 组 NCDHW/NDHWC × 5D/4D 与两个分支对照，最大误差 0）。
5. `out / torch.tensor(divisor_override, dtype=torch.float32)` 改为 `window_sum / divisor`，数值路径等价（对照误差 0）。
6. 去掉了源码 golden 中 `divisor_override` 被 `attrs.get` 重新取值的兜底链——需求契约里属性值由调用方直接给出。
7. `float16` 分支由 `astype(np.float32)` 改为 `x.to(torch.float32)`；`bf16` 不在源码 golden 的升精度分支里，但设备侧一律按 fp32 累加（`pool_3d_common.h` 的 `castTraitT2Fp32`、SIMT 的 `static_cast<float>`），需求 golden 对 bf16 也升 fp32，与设备一致。

### 8.6 CPU 对照结果

- 对照对象：`tests/assets/golden.py` 的 `avg_pool3_d_golden`（把 `pads < ksize/2` 的分支条件用 `os.environ["BRANCH"]` 强制成两个变体，分别代表两条路径的真实算法）。
- 对照用例：21 组配置 × 5D/4D × NDHWC/NCDHW，覆盖 `padding` 小于/等于 `kernel/2`、`countIncludePad` 两种、`divisorOverride` 0 与非 0、`ceilMode` True/False、kernel 长度 1 与 3、stride 为空/等长/离散、全局池化、ksize 全 1、单通道、批次 2。
- 结果：**全部 0 误差**（`max |mine - source| == 0`）。
- 另外用 CPU `torch.nn.functional.avg_pool3d` 直接校验「padding < kernel/2」分支的 10 组配置（5D 与 4D），同样 0 误差。
- 未覆盖的对照：`kernelSize` 长度为 5 的图模式形态（aclnn 通路不接受，未纳入）；输出 dtype 只对照到 fp16/fp32/bf16 的 cast（fp16/bf16 在 CPU 上无法直接跑 `avg_pool3d`，通过与 fp32 结果 cast 后比对）。

### 8.7 TTK 环节状态

见 §9。状态：**已执行**（用户确认改用相邻技能副本后执行），逐条结果与归因记录在 §9。

## 9. TTK 适配与测试结果

### 9.1 技能来源偏差（记录在案）

规程要求 TTK 子代理只读 `<TTK_REPO>/.claude/skills/ttk-aclnn-adapt/SKILL.md`。实际检查发现该路径**不存在**：ops-test-kit 的 git 索引中只跟踪 `ttk-how-diagnose`、`ttk-how-run-test`、`ttk-how-write-case`、`ttk-how-write-plugin`、`ttk-prof2case` 五个技能，没有 `ttk-aclnn-adapt`。仓库外另有一份相邻副本 `/home/s00940212/RSI/rrsi-devkit/.claude/skills/ttk-aclnn-adapt/`。

已向用户确认（AskUserQuestion），用户选择「用相邻副本执行」，并接受在本次记录中明确标注「技能来源为相邻副本，非 TTK_REPO 内路径」。实际采用的是 `/home/s00940212/RSI/requirement_new/.claude/skills/ttk-aclnn-adapt/`（与本需求包同仓的技能目录，同为 TTK_REPO 之外的副本）；所有 `python3 -m ttk` 命令仍在 `<TTK_REPO>` 根目录执行。

一处命令细节：`dump_aclnn_signature.py` 需要 `PYTHONPATH=<TTK_REPO>` 才能在仓库根目录导入 `ttk`，已在 `debug/signature.txt` 的产出命令中带上。

### 9.2 执行结果

**状态：已执行（真机）**。设备 `Ascend950DT_9582`（8 卡，`python3 -m ttk info` 确认）。

| 阶段 | 结果 | 产物 |
|---|---|---|
| Step 0 签名抽取 | `tensor_count = 2`，槽 0 `self`（输入）、槽 1 `out`（输出），6 个属性，与 `contract.md` 一致 | `debug/contract.md`、`debug/signature.txt` |
| Step 1 用例转换 | `--validate` 通过：20 total / 20 valid / 0 invalid | `debug/validate.log` |
| Step 2 TestSpec | 注册名 `aclnnAvgPool3d`，`golden(self, kernelSize, stride, padding, ceilMode, countIncludePad, divisorOverride, out)` 覆盖全部 C 形参（含输出槽） | `ttk/golden.py` |
| Step 3 冒烟 | 最小用例 `avg_pool3_d_06`（`1×1×1×1×1`）PASS，无 `GOLDEN_FAILURE`，输出 shape/dtype 与契约一致 | `debug/smoke.log`、`debug/smoke_result.csv`、`debug/dump/avg_pool3_d_06/` |
| Step 4 全量 | **20 / 20 PASS，0 FAIL，0 SKIP，PassRate 100.00%** | `debug/result.csv`、`debug/full_run.log` |
| Step 5 回流 | 无 FAIL，**未触发** golden/cases 修正；golden 与用例均未改动 | `debug/notes.json`、`debug/handoff.json` |

### 9.3 逐用例结果

判据为 TTK 默认 `mix_tolerance`（按 dtype 路由 rtol/atol），`matched_ratio` 全部为 1.0。

| case | 用例要点 | dtype | max_abs_error | 判据上限 | 结论 |
|---|---|---|---|---|---|
| 1 | float32 基线，stride=kernel 无重叠 | float32 | 7.65e-08 | 0.01 | PASS |
| 2 | fp16，padding 三维不等长 | float16 | 2.08e-04 | 0.1 | PASS |
| 3 | bf16，padding = kernel/2 | bfloat16 | 1.95e-03 | 1.0 | PASS |
| 4 | **4 维输入**，无 padding | float32 | 1.71e-07 | 0.01 | PASS |
| 5 | **4 维输入** + `countIncludePad=False` | float16 | 1.86e-04 | 0.1 | PASS |
| 6 | 最小规模 `1×1×1×1×1` | float32 | 0 | 0.01 | PASS |
| 7 | kernel 长度 1 + **stride 为空** | float16 | 0 | 0.1 | PASS |
| 8 | kernel=4 / stride=2 重叠窗口，padding=kernel/2 | bfloat16 | 4.86e-04 | 1.0 | PASS |
| 9 | `divisorOverride=5` | float32 | 3.02e-06 | 0.01 | PASS |
| 10 | N*C = 264 的小空间输入 | float16 | 2.44e-04 | 0.1 | PASS |
| 11 | `2×8×32×32×32` 多核 | float32 | 9.54e-08 | 0.01 | PASS |
| 12 | stride 远大于 kernel（离散窗口） | float16 | 2.39e-04 | 0.1 | PASS |
| 13 | 全局平均池化 | float32 | 2.33e-09 | 0.01 | PASS |
| 14 | `ceilMode=True` | float16 | 1.21e-04 | 0.1 | PASS |
| 15 | `ceilMode=True` + 三维 kernel/stride 各异 + `countIncludePad=False` | bfloat16 | 9.73e-04 | 1.0 | PASS |
| 16 | **mixed 显式取值列表** | float32 | 0 | 0.01 | PASS |
| 17 | **非连续视图输入** | float32 | 5.71e-08 | 0.01 | PASS |
| 18 | 单通道、无重叠 | float16 | 1.21e-04 | 0.1 | PASS |
| 19 | kernel/stride/padding 全部长度 1 广播 | bfloat16 | 1.83e-03 | 1.0 | PASS |
| 20 | D 方向 110 大窗口 + 小 H/W 窗口 | float16 | 2.74e-05 | 0.1 | PASS |

**FAIL 归因：无**。`handoff.json` 的 `failures` 为空数组。

### 9.4 由实测关闭/确认的推断

| 项 | 结论 |
|---|---|
| 4D 输入通路（原 R4） | **关闭**：case 4/5 真机 PASS，aclnn 层 `C,D,H,W → 1,C,D,H,W` 的补齐与回 `Reshape` 可用 |
| 空 `stride`（长度 0）语义 | **确认**：case 7 PASS，`stride=[]` 等价 `stride=kernelSize` 的契约成立 |
| 非连续输入 | **确认**：case 17 PASS，`tensor_view_strides/offsets/storage_shapes` 构造被 aclnn + `Contiguous` 正确接收 |
| `mixed` 显式取值 | **确认**：case 16 PASS，TestSpec 的 `customize_inputs` 精确落值，golden 逐元素一致 |
| `divisorOverride` / `countIncludePad` / `ceilMode` 三条属性语义 | **确认**：case 5/9/14/15 PASS，golden 与设备一致 |
| aclnn 内部 Transpose 换 NDHWC 的通路（原 R3） | **关闭**：case 20 满足 `IsBatchMergeBigKernel` 的触发条件，真机 PASS，Transpose + NDHWC 小 kernel 路径结果正确 |

### 9.5 遗留事项

1. TTK 不暴露 tiling key，§7 覆盖表中的「case → 内部模板」对应关系**仍为源码静态推断**，未由运行期证据直接确认；状态列已按「用例确实跑过」更新为「已运行验证」，但模板归属本身仍是推断。
2. 未构造专门触发以下内部通路的用例：优先级 0（`ksize` 全 1）、`IsDimDDownsamping`（`kH=kW=sH=sW=1`）、优先级 19 SIMT 兜底。20 个名额已满，取舍理由见 §7 备注 R1/R2/R5。aclnn 内部 Transpose 到 NDHWC 的通路已由 case 20 覆盖（见 R3）。
3. 无 FAIL 用例，未发生 golden / cases 的回流修正，仅更新了 `design.md` 的验证状态与备注。
4. `handoff.json` 完整内容：

```json
{
  "status": "executed",
  "skip_reason": "",
  "failures": [],
  "leftovers": [
    "TTK 不暴露 tiling key，design.md 覆盖表中的 case -> 内部模板归属仍为源码静态推断，未由运行期证据直接确认。",
    "未构造专门触发优先级 0（ksize 全 1）、IsDimDDownsamping（kH=kW=sH=sW=1）、aclnn 内部 Transpose 到 NDHWC 的通路、优先级 19 SIMT 兜底的用例；20 个名额已满，理由见 design.md 覆盖备注 R1/R2/R3/R5。",
    "无 FAIL 用例，未触发 Step 5 的回流修正。"
  ]
}
```
