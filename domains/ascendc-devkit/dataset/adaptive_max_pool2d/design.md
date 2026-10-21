# AdaptiveMaxPool2d 算子设计分析（A5）

> 芯片种类：A5（Ascend 950PR/950DT 系列、3510）。未显式指定芯片，按技能默认取 A5。
> 本文件是内部设计文档，包含 tiling key、源码函数名与目录路径；这些内部标识不得出现在 `desc.md`、`golden.py`、`proto.yaml`、`cases.*` 中。

## 1. 芯片范围与源码布局

### 1.1 芯片范围

| 项目 | 取值 |
|---|---|
| 本次芯片种类 | A5 |
| 产品/SoC | Ascend 950PR/950DT（950DT_9582 实测设备）、3510 |
| arch 目录 | `op_kernel/arch35/` |
| config 目录 | `op_host/config/ascend950` 对应的 `adaptive_max_pool2d_binary.json` |
| op def 配置 | `op_host/adaptive_max_pool2d_def.cpp` 中仅 `this->AICore().AddConfig("ascend950")` |
| 设备实测平台 | `Ascend950DT_9582`（`python3 -m ttk info` 识别） |

被排除的范围：

- A3（Atlas A3 910B/910C）：op def 没有 `ascend910b` / `ascend910_93` 配置，`op_kernel/` 下也没有 `arch22` 实现。
- A2（910B 之外）、Atlas 200I/500 A2、Atlas 推理/训练系列、Kirin 等其他产品：op def 未注册对应配置，文档中也未声明支持。
- `op_kernel_aicpu/`：AICPU 兜底实现，支持 double；本需求的 A5 AI Core 实现不受理 double（见 §8 D2），AICPU 路径不进入需求、golden、cases。
- `test/ut/`：单元测试，仅作分支线索，不作为需求语义来源。

### 1.2 路径映射（用户覆盖）

用户给出的算子源码路径 `/home/cann/ops-nn/pooling/adaptive_max_pool2d` 在环境中不存在。实际源码位于同一仓库的本地检出 `/home/y00893432/work/ops-nn/pooling/adaptive_max_pool2d`，以其作为本次 `PATH`。差异仅限根路径前缀，目录内布局一致，记录为路径解析的用户覆盖。

### 1.3 实际布局

```text
adaptive_max_pool2d/
├── docs/aclnnAdaptiveMaxPool2d.md          # 唯一接口文档候选
├── op_api/
│   ├── aclnn_adaptive_max_pool2d.h/.cpp    # aclnnAdaptiveMaxPool2d 两段式接口
│   └── adaptive_max_pool2d.cpp/.h          # l0op 适配（AiCore/AiCpu 选择）
├── op_host/
│   ├── adaptive_max_pool2d_def.cpp         # OpDef
│   ├── adaptive_max_pool2d_infershape.cpp  # shape / dtype 推导
│   ├── adaptive_max_pool2d_tiling.cpp      # 基础 tiling（单模板，key=0）
│   ├── max_pool2d_with_argmax_v2_simt_tiling.cpp  # SIMT tiling 模板注册
│   ├── adaptive_max_pool2d_tiling_base.h
│   ├── adaptive_max_pool2d_simt_tiling.h
│   └── config/adaptive_max_pool2d_binary.json
├── op_kernel/
│   ├── adaptive_max_pool2d.cpp             # kernel 入口，仅 TILING_KEY_IS(0)
│   └── arch35/adaptive_max_pool2d_simt.h   # SIMT 实现
├── op_kernel_aicpu/                        # 范围外（double 兜底）
├── op_graph/adaptive_max_pool2d_proto.h
├── examples/test_aclnn_adaptive_max_pool2d.cpp
└── test/st/aclnnAdaptiveMaxPool2d/         # atk json + executor golden
```

注意：用例与 golden 位于 `test/st/`（单数 `test`），不是标准布局中的 `tests/st/`；按语义识别并采用。

### 1.4 文档版本选择

- `docs/` 下唯一候选为 `aclnnAdaptiveMaxPool2d.md`，文件名归一化后与 `ops_pascal = AdaptiveMaxPool2d` 精确匹配。
- `ops_snake = adaptive_max_pool2d`（目录名），`ops_pascal` 由 `op_host/adaptive_max_pool2d_def.cpp` 的 `class AdaptiveMaxPool2d : public OpDef` 与 `OP_ADD(AdaptiveMaxPool2d)` 校验，一致。
- aclnn 接口名由 `op_api/aclnn_adaptive_max_pool2d.h` 的 `aclnnAdaptiveMaxPool2dGetWorkspaceSize` 与 `examples/test_aclnn_adaptive_max_pool2d.cpp` 的调用确认。
- 排除候选：`README.md`（背景/参数表，非 aclnn 接口文档）、`docs` 下无其他版本、无 FusionPass 文档。

## 2. 实现概览

外部入口是两段式 aclnn 接口：

```cpp
aclnnStatus aclnnAdaptiveMaxPool2dGetWorkspaceSize(
    const aclTensor* self, const aclIntArray* outputSize,
    aclTensor* outputOut, aclTensor* indicesOut,
    uint64_t* workspaceSize, aclOpExecutor** executor);
```

参数校验（`CheckParams`）：dtype 支持列表、`outputOut` 与 `self` 同 dtype、`indicesOut` 必须为 int64、`self` 维度为 3 或 4、`indicesOut` 与 `outputOut` shape 相同、非首维大于 0、`outputSize` 长度为 2 且元素大于 0。空 Tensor 直接返回成功且不写入输出。

A5 上 `IsSocVersion910D()` 为真（`AclnnUtil::IsRegbase` 覆盖 `DAV_3510`、`DAV_5102`、`DAV_9201`、`DAV_9202`），非 double 输入进入 `Handle910DCase`：

1. `l0op::Contiguous(self)` 连续化；
2. `self` 为 NHWC 时按 perm `{0,3,1,2}` 转置为 NCHW（`ConvertNHWCtoNCHW`）；
3. 取 `Hi = shape[-2]`、`Wi = shape[-1]`，计算 `Hi % Ho == 0 && Wi % Wo == 0`；
4. 整除时：3 维输入 `View3Das5D`、4 维输入 `View4Das5D`，reshape 为 NCDHW（D=1），调用 `MaxPool3DWithArgmaxV2`，kernel = stride = `{1, Hi/Ho, Wi/Wo}`，padding=0，dilation=1，ceilMode=false；
5. 不整除时：3 维输入先 `View3Das4D`，再调用 `l0op::AdaptiveMaxPool2d`，进入 arch35 SIMT kernel；
6. 两条路径的 indices 均 Cast 为 int64，再 Reshape/ViewCopy 到 `outputOut`、`indicesOut`。

`l0op::AdaptiveMaxPool2d` 在 A5（regbase）且 dtype ∈ {float32, float16, bfloat16} 时分配 int32 indices 并下发 AiCore；否则走 AiCpu（double 等）。

kernel 入口只有一条通路：

```cpp
if (TILING_KEY_IS(0)) {
    AdaptiveMaxPool2DSimt<DTYPE_X, DTYPE_ARGMAX, int32_t, uint32_t> op(&pipeBase, &tilingData);
    op.Init(x, y, indices);
    op.Process();
}
```

`Process()` 中每个线程处理一个输出元素，按 `index = blockIdx*threadNum + threadIdx` 起步、以 `blockNum*threadNum` 为步长网格遍历 `totalSize = N*C*Ho*Wo`，用 magic 除法分解出 `ncId`、`hId`、`wId`，再按自适应窗口扫描取最大值。

## 3. 模板设计

### 3.1 device 侧模板

- 只有 `AdaptiveMaxPool2DSimt<VALUE_T, INDICES_T, FORMAT_T, DIV_T>` 一个模板，内部按 `VALUE_T`（float32/float16/bfloat16）、`INDICES_T`（int32/int64）实例化。
- kernel 入口固定实例化 `<DTYPE_X, DTYPE_ARGMAX, int32_t, uint32_t>`：`FORMAT_T` 与 `DIV_T` 不是外部可选项。
- `Process()` 中的 `if constexpr` 对 `int32_t/uint32_t` 恒走直接传 magic 参数的分支；从 UB 读取 SIMT 参数的分支不会被编译进该实例，属于不可外部触发的死分支。
- `GetTilingKey()` 恒返回 0，不存在按 dtype/shape 切换的 tiling key。

### 3.2 外部可触发的执行分支

device 模板唯一，但 aclnn 适配层存在可由外部输入触发的两条执行路径：

| 分支 | 触发条件（外部可观察） | 计算差异 |
|---|---|---|
| B1 均匀窗口路径 | `Hi % Ho == 0` 且 `Wi % Wo == 0` | 窗口等大且不重叠，转成 NCDHW（D=1）后按 kernel=stride=(1, Hi/Ho, Wi/Wo) 做 3 维最大池化；索引仍为平面内 `h*Wi+w` |
| B2 自适应窗口路径 | `Hi % Ho != 0` 或 `Wi % Wo != 0` | SIMT kernel 按 `floor(oh*Hi/Ho)`、`ceil((oh+1)*Hi/Ho)` 计算每个窗口，窗口大小可随位置变化并重叠 |
| B1-3D | B1 且输入为 3 维 | 先 reshape 为 `[1, C, 1, Hi, Wi]` 再执行 B1 |
| B2-3D | B2 且输入为 3 维 | 先 reshape 为 `[1, C, Hi, Wi]` 再执行 B2 |

两条分支在整除条件下数学等价：`floor(oh*Hi/Ho) = oh*k`、`ceil((oh+1)*Hi/Ho) = (oh+1)*k`，k = Hi/Ho。

## 4. 分核设计

`AdaMaxPool2dTilingSIMT::DoOpTiling()`（`op_host/max_pool2d_with_argmax_v2_simt_tiling.cpp`）：

```text
outputDataCount = N * C * Hi * Wi
threads        = min(outputDataCount, MAX_THREAD_NUM=256)
blockNum       = ceilDiv(outputDataCount, threads)
blockNum       = min(blockNum, coreNum)
SetBlockDim(blockNum)
threadNums = threads; blockNums = blockNum   // 仅写入 tilingData
```

- 分核粒度按输入元素总数 `N*C*Hi*Wi` 估算，单核线程数上限 256、核数上限为平台 AIV 核数。
- device 侧实际并行度来自启动配置（`Simt::Dim3(THREAD_DIM=1024)`）与 `Simt::GetBlockNum()/GetThreadNum()`；`tilingData.threadNums/blockNums` 在 kernel 中未被读取。
- kernel 的工作量是输出元素总数 `N*C*Ho*Wo`，采用网格步长循环，尾块由 `index < count` 条件自然截断，没有单独的尾核分支。
- 当 `N*C*Hi*Wi <= 256` 时只有 1 个 block；超过 `256 * coreNum` 后 block 数饱和为 coreNum。

## 5. 分块设计

- SIMT kernel 不切 UB：每次从 GM 直接读取窗口元素，没有 `DataCopy` 分块、没有 32B/VL 对齐要求，窗口大小任意。
- 窗口边界：
  - `startIndexNoMagic(hId, Ho, Hi) = floor(hId*Hi/Ho)`，实现为 `(x/y)*z + ((x%y)*z)/y`；
  - `endIndexNoMagic(hId, Ho, Hi) = ceil((hId+1)*Hi/Ho) = 1 + ((hId+1)*Hi - 1)/Ho`；
  - 中间量使用 64 位，避免 `Hi*Wi` 接近 int32 上限时溢出。
- 每个 `(N,C)` 平面基址 `ncStartData = bottomData + ncId*ncSize`，`ncSize = Hi*Wi`；窗口内偏移 `idxOffset = h*Wi + w`，输出索引与之一致。
- 除法换算：`hw = Ho*Wo`、`Ho`、`Wo` 的 magic/shift 由 `GetUintDivMagicAndShift` 预先计算，用于线程内的 `ncId`、`hId` 拆分。
- 容量约束：tiling 要求 `Hi*Wi <= INT32_MAX`；kernel 中 `totalSize`、`ncSize`、索引均为 `int32_t`，因此输出元素总数也受 int32 表示范围限制。用例规模远低于该上限。
- 无尾块掩码、无 UB 预算、无 full-load/partial-load 阈值。

## 6. 性能调优技巧

以下机制均来自源码，未做额外推断：

1. **SIMT 网格步长循环**：`index += blockNum*threadNum` 让固定线程数覆盖任意规模输出，避免按 shape 重新编译。
2. **magic 除法**：用乘加与移位替代线程内的整数除法（`Simt::UintDiv`），降低每元素开销。
3. **整除时复用 3 维池化**：`Hi % Ho == 0 && Wi % Wo == 0` 时把二维问题 reshape 成 D=1 的三维最大池化，复用 `MaxPool3DWithArgmaxV2` 的成熟实现，避免自适应窗口的逐位置边界计算。
4. **索引窄化**：A5 AICore 路径内部使用 int32 indices，最后统一 Cast 为 int64 输出，降低中间写带宽。
5. **按需转置**：只有 view format 为 NHWC 时才做 `Transpose`；连续化 `Contiguous` 也在最前面完成，后续 kernel 只面对连续内存。

## 7. 模板与测试覆盖映射

目标芯片固定为 A5。验证状态在 TTK 执行前为“静态推断”，执行后按 `result.csv` 升级。

| 目标芯片 | 内部模板/分支 | 源码依据 | 完整外部触发条件 | case_id | 验证状态 |
|---|---|---|---|---|---|
| A5 | B1 均匀窗口（`MaxPool3DWithArgmaxV2`，D=1，kernel=stride） | `op_api/aclnn_adaptive_max_pool2d.cpp` `Handle910DCase` 整除分支 | `Hi % Ho == 0` 且 `Wi % Wo == 0`，4 维输入 | 1, 3, 5, 6, 12, 17, 18, 20 | 已运行验证 |
| A5 | B2 自适应窗口（arch35 SIMT，`TILING_KEY_IS(0)`） | `op_kernel/adaptive_max_pool2d.cpp`、`op_kernel/arch35/adaptive_max_pool2d_simt.h`、`op_host/max_pool2d_with_argmax_v2_simt_tiling.cpp` | `Hi % Ho != 0` 或 `Wi % Wo != 0`，4 维输入 | 2, 4, 7, 8, 13, 14, 15, 16, 19 | 已运行验证 |
| A5 | B1-3D：3 维输入 + 整除，`View3Das5D` | `Handle910DCase`、`pool_3d_common/op_api/pool_3d_util.cpp` | 输入 3 维 `[C,H,W]`，H/W 均整除 | 10, 11 | 已运行验证 |
| A5 | B2-3D：3 维输入 + 不整除，`View3Das4D` | `Handle910DCase`、`AdaptiveMaxPool2d` l0op | 输入 3 维 `[C,H,W]`，H 或 W 不整除 | 9 | 已运行验证 |
| A5 | dtype = float32 | op def `DataType({DT_FLOAT, ...})`、tiling dtype 检查 | `dtype=float32` | 1, 2, 4, 7, 8, 9, 12, 15, 16, 19 | 已运行验证 |
| A5 | dtype = float16 | op def、tiling dtype 检查（输入 4 字节对齐由 tiling 保证） | `dtype=float16` | 5, 10, 13, 17, 20 | 已运行验证 |
| A5 | dtype = bfloat16 | op def、tiling dtype 检查 | `dtype=bfloat16` | 3, 6, 11, 14, 18 | 已运行验证 |
| A5 | 非连续输入连续化 | `l0op::Contiguous(self)` 在两条路径前均执行 | x 为非连续视图（末维加倍存储），逻辑 9x11 | 15 | 已运行验证 |
| A5 | 索引并列取第一个最大值 | arch35 `executeFunc` 的严格 `>` 比较 | 窗口内存在并列最大值（显式值构造） | 16 | 已运行验证 |
| A5 | 最大值初值 -inf（负值域） | `NumericLimits<VALUE_T>::NegativeInfinity()` | 输入全为负值 | 17 | 已运行验证 |
| A5 | 输出空间大于输入（窗口重叠） | `startIndex/endIndex` 对 `Ho>Hi` 仍有非空窗口 | `Hout > Hin` 或 `Wout > Win` | 7, 8 | 已运行验证 |
| A5 | 多核/多 block 规模 | `DoOpTiling` 的 `blockNum = min(ceilDiv(N*C*Hi*Wi, min(N*C*Hi*Wi,256)), coreNum)` | `N*C*Hi*Wi` 远大于 256 | 4, 6, 12, 13, 14, 18 | 已运行验证 |
| A5 | 3 维输入单 batch | `View3Das4D` / `View3Das5D` 的 unsqueeze | 3 维 `[C,H,W]` | 9, 10, 11 | 已运行验证 |
| A5 | 均不整除 | 两个维度的 `%` 都非 0，走 B2 | `Hi%Ho!=0 && Wi%Wo!=0` | 2, 4, 13, 14, 15, 16 | 已运行验证 |
| A5 | 混合整除（一维整除、一维不整除） | B2 条件需两个维度同时整除 | 仅 H 或仅 W 整除 | 19（H 不整除、W 整除） | 已运行验证 |
| A5 | NHWC 物理格式转置 | `ConvertNHWCtoNCHW` 的 perm `{0,3,1,2}` | aclnn 张量 format = NHWC | — | 未覆盖：需求 golden 按通道优先逻辑布局定义，不携带 format 参数；该分支只是转置，不改变逻辑语义 |
| A5 | double → AiCpu 兜底 | `IsSelfDtypeDouble`、`GetDtypeSupportList` | `dtype=float64` | — | 不适用：ascend950 的 op def 未声明 DT_DOUBLE，不属于 A5 需求范围 |
| A5 | argmax int32（`argmax_dtype=3`） | `op_host/adaptive_max_pool2d_infershape.cpp` | 图模式属性 `argmax_dtype=3` | — | 不适用：aclnn 接口固定要求 int64 indices，且不暴露 `argmax_dtype`，本需求以 aclnn 契约定义 |
| A5 | UB 参数广播分支（`if constexpr` 另一侧） | `op_kernel/arch35/adaptive_max_pool2d_simt.h` | 需要 `FORMAT_T/DIV_T` 非 int32/uint32 | — | 不适用：kernel 入口只实例化 int32/uint32 |

## 8. 源码依据与需求决策

### 8.1 源码事实

1. **计算公式**：`op_kernel/arch35/adaptive_max_pool2d_simt.h` 的 `startIndexNoMagic` / `endIndexNoMagic` 与 `op_kernel_aicpu/adaptive_max_pool2d_aicpu.cpp` 的 `StartIndex` / `EndIndex` 均为 `floor(o*in/out)` 与 `ceil((o+1)*in/out)`，与接口文档一致。
2. **索引基准**：两套 kernel 都计算 `h*Wi + w`（每个 (N,C) 平面内的一维偏移），不包含 N、C 偏移。
3. **并列最大值**：比较条件是严格 `>`，因此扫描顺序（h 外层、w 内层）中的第一个最大值胜出。
4. **NaN**：条件是 `val > maxVal || IsNan(val)`，每个 NaN 都会覆盖当前最大值，最终指向窗口内最后一个 NaN。
5. **空窗口不存在**：`output_size` 元素大于 0 且输入空间维大于 0 时，`start < end` 恒成立，窗口至少包含一个元素。
6. **dispatch**：A5 走 `Handle910DCase`；整除时走 `MaxPool3DWithArgmaxV2`（NCDHW、D=1），否则走 `AdaptiveMaxPool2d` 的 arch35 SIMT kernel。
7. **indices dtype**：aclnn 层 `CheckDtypeValid` 要求 `indicesOut` 为 int64；A5 AICore 内部先用 int32，再 Cast 为 int64。
8. **dtype 声明**：`op_host/adaptive_max_pool2d_def.cpp` 对 ascend950 只声明 `DT_FLOAT`、`DT_FLOAT16`、`DT_BF16`；tiling 也仅接受这三类。
9. **shape 约束**：`adaptive_max_pool2d_infershape.cpp` 允许 3 或 4 维；`output_size` 长度必须为 2；`op_host/adaptive_max_pool2d_tiling.cpp` 要求 4 维（3 维由 aclnn 适配层补维）、各维不小于 1、`Hi*Wi` 不超过 int32 最大值。
10. **输出 shape**：`infershape` 把输入前 `rank-2` 维与 `output_size` 拼接，等价于把后两维替换为 `[Ho, Wo]`。

### 8.2 基于源码的推断

- **A5 命中 910D 分支**：`IsSocVersion910D()` 使用 `AclnnUtil::IsRegbase`，包含 `DAV_3510`；A5 的 op def 与 arch35 kernel 也印证这一点。因此 A5 的 aclnn 路径按 `Handle910DCase` 分析。
- **整除路径等价性**：整除时自适应窗口退化为等大不重叠窗口，与 `MaxPool3DWithArgmaxV2`（kernel=stride、padding=0、D=1）结果一致；索引在 D=1 时同为 `h*Wi+w`。
- **int32 上限**：tiling 只检查 `Hi*Wi`，但 kernel 把 `totalSize = N*C*Ho*Wo` 存为 int32；这是源码推断出的规模上限，不是需求新增约束。

### 8.3 需求决策（AI 决策）

- **D1 外部契约为 aclnn 两段式接口**。`proto.yaml`/`golden.py`/`cases.*` 的输入为 `x`、属性为 `output_size`、输出为 `y` 与 `indices`，与 `aclnnAdaptiveMaxPool2dGetWorkspaceSize` 的张量槽（self、outputOut、indicesOut）和 `outputSize` 参数对应。op def 中额外的图模式属性 `argmax_dtype`（可选、默认 3=int32）不进入本需求：aclnn 接口不暴露该属性，且 aclnn 校验强制 `indicesOut` 为 int64。
- **D2 范围只含 float32/float16/bfloat16**。接口文档列出 DOUBLE，但 ascend950 的 op def 未声明 `DT_DOUBLE`，AI Core tiling 也拒绝 double；double 仅走 AICPU 兜底，属于范围外的另一实现。需求与用例因此只覆盖三种 AICore dtype。
- **D3 逻辑布局为通道优先**。4 维按 `[N,C,H,W]`、3 维按 `[C,H,W]` 解释；NHWC 是接口层的物理格式，经转置后语义等价，需求 golden 不携带 layout 参数，用例不覆盖 NHWC（记为未覆盖，不影响数值契约）。
- **D4 3 维输入按单 batch 处理**，输出保持 3 维。该行为由 aclnn 适配层的 unsqueeze/squeeze 保证，需求契约与 golden 直接包含。
- **D5 `output_size` 建模为属性**。op def 中是 `ListInt` 属性，aclnn 中是 `aclIntArray` 参数；需求原型统一写成 `int[] output_size` 属性，便于在 cann_bench 中调用。
- **D6 golden 直接调用 torch 内置实现并升 float32**。需求 golden 调用 `torch.nn.functional.adaptive_max_pool2d(x.float(), output_size, return_indices=True)`，再把 `y` 转回输入 dtype、`indices` 转 int64，与源码 ST 参考实现的做法一致。升 float32 是正确性前提：PyTorch CPU 在原生 float16/bfloat16 上对非整除窗口会返回越界索引（实测 127x129→32x33 返回 16384 > 16382），升精度是无损且保序的，不影响最大值与并列关系。代价是并列/NaN 的索引行为依赖 torch CPU 实现的隐含约定，已在 §8.4 记录风险。
- **D7 正常用例不含 NaN/Inf**。接口文档未把 NaN/Inf 列为必须支持的契约，20 个名额用于 dtype、分支、规模、布局与索引规则。并列最大值用显式值用例（case 16）覆盖。

### 8.4 Golden 验证记录

- 需求 golden 直接调用 `torch.nn.functional.adaptive_max_pool2d`，输入先升 float32、`y` 转回原 dtype、`indices` 转 int64。
- **升 float32 是必须的**：PyTorch CPU 在原生 float16/bfloat16 上直接调用该 API 时，对非整除窗口会返回越界索引（已复现：case 13 的 `127x129→32x33` 返回 index=16384 > `Hi*Wi-1=16382`；case 14、18 同样越界）。升精度后与设备输出完全一致。
- 20/20 用例与设备实测一致：`y` 最大绝对误差 0、`indices` 逐元素相等；输出 shape/dtype 与算子原型一致。
- 额外边界对照：并列最大值（取扫描顺序第一个）、全 `-inf`、含 `+inf` 与设备一致；NaN 行为未纳入正常用例。
- 20 个用例的 golden 总运行时间约 2 秒（CPU）。
- 风险项：并列最大值取第一个、NaN 传播的具体索引属于 PyTorch CPU 实现的隐含行为，API 文档未作承诺；golden 的数值契约（最大值、索引基准）不依赖它，但若未来 torch 版本改变该行为，需重新对照。

### 8.5 TTK 环节状态

- **状态：已执行（`status=executed`）**。设备 `Ascend950DT_9582`（A5），`TTK_REPO=/home/y00893432/work/ops-test-kit`，产物目录 `ttk/`（默认 `<需求文件夹>/ttk/`）。
- **最终结果（内置 API 版 golden）：20/20 PASS，0 FAIL，0 SKIP**，在 device 3 上完成；`y` 的 `max_abs_error=0.0`、`matched_ratio=1.0`，`indices` 的 `binary_equal` 全部通过。
- 历史记录：首轮用手写公式版 golden 在 device 0 上同样 20/20 PASS；切换为内置 API 版后重跑，结果不变。两份结果分别保留为 `debug/result_manual_golden.csv` 与 `debug/result.csv`。
- **环境备注**：device 0 当时被其他进程占用（`npu-smi` 可见约 4.4GB 占用），直接运行会报 `aclrtSetDevice() Failed: 507033`；这不是精度问题，改在 device 3 执行后通过。该现象属于环境项，未据此修改 golden 或用例。
- **独立复算**：用 float64 窗口公式对抽查用例（01/13/14/15/16/17/18）复算，设备输出 == 需求 golden == fp64 参考。
- **关键构造验证**：
  - case 15（非连续输入）：view `(2,3,9,11)`、storage `(2,3,9,22)`、strides `(594,198,22,2)`、offset 0；`aclCreateTensor` 记录确认 stride/storage 生效，设备按逻辑元素计算，PASS。
  - case 16（显式 25 值）：通过 TTK 张量覆写表达，dump 校验 25 个值逐元素一致；并列最大值 25 位于 `(3,3)` 与 `(4,4)`，设备 `indices[1,1]=18`（取扫描顺序第一个），与 golden 一致。
  - 3 维 NCL（09/10/11）、fp16/bf16、输出大于输入（07/08）等分支均 PASS。
- **回流修正**：无 FAIL 归因；本轮只按用户要求把需求 golden 从手写公式版切换为内置 API 版（升 float32），`cases.*`、`proto.yaml` 的语义未变，`desc.md` 第 5 节同步更新。
- 需求包 `cases.csv` 仍为七列；TTK 的 `pass`/`note` 只存在于 `ttk/cases.csv`（20 行，全部 PASS）。
- 交接文件：`ttk/debug/handoff.json`（`failures=[]`）。

### 8.6 其余需求决策与遗留

- 4 维用例按通道优先 `[N,C,H,W]`，3 维用例按 `[C,H,W]`；用例 `note` 只在一句话描述中点明 dtype、规模、整除/重叠、值域形态与非默认构造，不再承载机器字段。
- case 16 的显式值序列在 TTK 侧以张量覆写实现并已验证；该项不再是遗留。
- case 15 的非连续输入由 TTK 的 `tensor_view_strides` / `tensor_view_offsets` / `tensor_storage_shapes` 表达并已验证；该项不再是遗留。
- 遗留事项：
  1. TTK 不支持逐用例 seed：用例约定的 `seed = case_id` 随机序列无法逐值复现，TTK 仅保证 shape/dtype/value_range 一致。由于最大值选择是精确拷贝，不影响 y/indices 的判定。
  2. NHWC 物理格式分支未覆盖（见 D3，golden 不携带 layout 参数）。
  3. double dtype 未覆盖（见 D2，A5 op def 未注册 `DT_DOUBLE`）。
  4. NaN/Inf 特殊值未覆盖（见 D7）。
  5. 内置 API 版 golden 的并列/NaN 索引行为依赖 torch CPU 实现（见 §8.4 风险项）。
