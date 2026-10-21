# AdaptiveMaxPool3DGrad 算子设计分析（A5）

> 芯片范围：**A5**（Ascend 950PR/950DT 系列，arch35 / DAV_3510）。本文所有源码分析、模板结论与用例均限定在该范围内。
> 用户未显式指定芯片种类，按技能规则取默认 A5。TTK 实测设备为 Ascend950DT_9582，与 A5 匹配。

## 1. 芯片范围与源码布局

### 1.1 路径与芯片

| 项 | 值 | 说明 |
|---|---|---|
| 用户给出的源码路径 | `/home/cann/ops-nn/pooling/adaptive_max_pool3d_grad` | 该路径在本机不存在 |
| 实际采用路径 | `/home/y00893432/work/ops-nn/pooling/adaptive_max_pool3d_grad` | 全盘检索到的唯一同名算子目录，布局与技能约定一致；用户路径应为环境内另一挂载点，按“同一算子源码”处理 |
| `ops_snake` | `adaptive_max_pool3d_grad` | 目录名 |
| 源码注册名 | `AdaptiveMaxPool3DGrad` | `op_host/adaptive_max_pool3d_grad_def.cpp` 的 `OP_ADD(AdaptiveMaxPool3DGrad)` |
| 目录推导名 | `AdaptiveMaxPool3dGrad` | 与源码注册名仅 `3D`/`3d` 大小写不同；按“源码注册名为准”采用 `AdaptiveMaxPool3DGrad` |
| 输出目录 | `/home/y00893432/work/ops-dataset/adaptive_max_pool3d_grad` | 用户指定，原本为空 |
| TTK 仓库 | `/home/y00893432/work/ops-test-kit` | 用户指定，`python3 -m ttk info` 识别到 8 张 Ascend950DT_9582 |

### 1.2 源码布局

| 内容 | 实际路径 | 备注 |
|---|---|---|
| 接口文档 | `docs/aclnnAdaptiveMaxPool3dBackward.md` | 另有 `docs/aclnnAdaptiveMaxPool2dBackward.md`（2D 算子，排除） |
| aclnn 接口 | `op_api/aclnn_adaptive_max_pool3d_backward.{h,cpp}`、`op_api/adaptive_max_pool_common.cpp` | 入口 `aclnnAdaptiveMaxPool3dBackwardGetWorkspaceSize(gradOutput, self, indices, gradInput, ...)` |
| l0 接口 | `op_api/adaptive_max_pool3d_backward.{h,cpp}` | `l0op::AdaptiveMaxPool3DGrad` |
| op def | `op_host/adaptive_max_pool3d_grad_def.cpp` | 输入 `x`、`grad`、`argmax`，输出 `y` |
| A5 tiling | `op_host/adaptive_max_pool3d_grad_simt_tiling.cpp`、`op_host/adaptive_max_pool3d_grad_tiling_arch35.h`、`op_host/adaptive_max_pool3d_grad_tiling_base_arch35.cpp` | 模板 `AdaptiveMaxPool3dGradTilingSimt`，优先级 1 |
| A3/A2 tiling | `op_host/adaptive_max_pool3d_grad_tiling_base.cpp`、`..._normal_tiling.cpp`、`..._scatter_tiling.cpp` | arch22 路径，本需求范围外 |
| A5 kernel | `op_kernel/arch35/adaptive_max_pool3d_grad_simt.h`、`op_kernel/arch35/adaptive_max_pool3d_grad_struct.h` | `__CCE_AICORE__ == 310` 时进入 |
| A3/A2 kernel | `op_kernel/adaptive_max_pool3d_grad_normal.h`、`..._scatter.h`、`..._scatter_overlap.h` | 本需求范围外 |
| 芯片配置 | `op_host/config/ascend950/` | 6 组二进制配置（3 种 x dtype × argmax int32/int64） |
| 测试 | `tests/st/aclnnAdaptiveMaxPool3dBackward/{atk_*.json,executor_*.py}`、`tests/ut/**` | 用例种子池与 tiling/kernel UT |

### 1.3 文档版本选择

| 候选 | 结论 | 理由 |
|---|---|---|
| `docs/aclnnAdaptiveMaxPool3dBackward.md` | **采用** | 文件名与 aclnn 头文件入口 `aclnnAdaptiveMaxPool3dBackward` 精确匹配；文档参数表与头文件签名一致 |
| `docs/aclnnAdaptiveMaxPool2dBackward.md` | 排除 | 2D 算子，入口 `aclnnAdaptiveMaxPool2dBackward` 与本算子不同 |
| `README.md` | 仅辅助 | 算子级功能/参数说明，不构成接口契约 |
| `tests/st/aclnnAdaptiveMaxPool2dBackward/**` | 排除 | 2D 算子用例 |

目录名与文档版本无需做版本映射：目录 `adaptive_max_pool3d_grad` 对应接口 `aclnnAdaptiveMaxPool3dBackward`，op def 中无 `.Version(N)` 后缀。

### 1.4 被排除的芯片范围

| 排除对象 | 内容 | 理由 |
|---|---|---|
| A3（Atlas A3 910B/910C）与 A2 | `op_host/*_tiling_base.cpp`、`*_normal_tiling.cpp`、`*_scatter_tiling.cpp`；`op_kernel/adaptive_max_pool3d_grad_normal.h`、`*_scatter*.h`；`op_host/config/ascend910b/`、`ascend910_93/`；文档中 A3/A2 支持行 | 用户未选择 A3，按默认 A5 只分析 A5 实现 |
| A3/A2 专有约束 | `argmax` 仅 int32；`D*H*W ≤ INT32_MAX`；整除场景由 aclnn 改走 `MaxPool3DGradWithArgmax`；默认非确定性 | 只对 A3/A2 成立，不写入 A5 需求与用例 |
| `ascend960*`、`ascend310p`、`kirin*` | 未在本算子源码/配置中出现 | 范围外 |

补充：A5 的 op def 只注册了 `ascend950` 配置，未注册 `ascend350`；tiling 侧 `NpuArch::DAV_3510` 同时覆盖 950 与 350。本需求按 `ascend950` 配置与 950 实测设备为准，不在需求中宣称 350 的行为。

## 2. 实现概览

外部调用链（A5）：

```text
aclnnAdaptiveMaxPool3dBackwardGetWorkspaceSize(gradOutput, self, indices, gradInput)
  └─ 参数校验（dtype/维度/shape/空张量）
  └─ Contiguous(gradOutput/self/indices)
  └─ 4D 输入 ViewCDHWas5D（纯视图，N=1）；5D 输入 ReFormat(NCDHW)
  └─ selectLevelZeroOperation：A5 为 regbase，恒走 l0op::AdaptiveMaxPool3DGrad
       └─ op AdaptiveMaxPool3DGrad(x=self, grad=gradOutput, argmax=indices) -> y
          └─ tiling：AdaptiveMaxPool3dGradTilingSimt（arch35）
          └─ kernel：arch35 SIMT（零初始化 + 按 argmax 散射累加）
  └─ 4D 输出 View5DasCDHW；ViewCopy 到 gradInput
```

算子级语义要点（源码事实）：

1. `y` 先整体置 0，再把 `grad` 的每个元素累加到 `argmax` 指定的位置；`argmax` 是每个 `(N, C)` 平面内 `D*H*W` 上的一维偏移。
2. `x` 的数值不参与计算：kernel 只用 `x` 的 shape 计算输入平面大小与输出元素总数，`grad`、`argmax` 与 `y` 才是实际数据通路。
3. A5 不使用 `MaxPool3DGradWithArgmax` 替代路径（该分支带 `!IsRegbase()` 条件），因此无论空间维是否整除都走本算子的 SIMT kernel。

## 3. 模板设计

### 3.1 tiling 模板选择

`op_host/adaptive_max_pool3d_grad_tiling.cpp` 通过 `TilingRegistry::GetInstance().DoTilingImpl(context)` 按优先级从小到大尝试模板：

| 优先级 | 模板 | 注册位置 | 选用条件 |
|---|---|---|---|
| 1 | `AdaptiveMaxPool3dGradTilingSimt` | `adaptive_max_pool3d_grad_simt_tiling.cpp` | `GetShapeAttrsInfo` 要求 `IsRegbaseSocVersion()` 且 `NpuArch == DAV_3510`，否则返回 `GRAPH_PARAM_INVALID` 被跳过；`IsCapable()` 恒为 true |
| 10 | `AdaptiveMaxPool3DGradNormalTiling` | `..._normal_tiling.cpp` | arch22（A2/A3）路径，本需求范围外 |
| 20 | `AdaptiveMaxPool3DGradScatterTiling` | `..._scatter_tiling.cpp` | arch22（A2/A3）路径，本需求范围外 |

A5（DAV_3510）上优先级 1 的 SIMT 模板命中；A2/A3 上它因 arch 不匹配被跳过，落到优先级 10/20 的 arch22 模板。

### 3.2 kernel 模板参数与分支

`op_kernel/adaptive_max_pool3d_grad_struct.h` 声明：

```text
ASCENDC_TPL_ARGS_DECL(AdaptiveMaxPool3DGrad,
    ASCENDC_TPL_UINT_DECL(TEMPLATE_MODE, ASCENDC_TPL_4_BW, ASCENDC_TPL_UI_LIST, TPL_SIMT_KERNEL),
    ASCENDC_TPL_DTYPE_DECL(INDEX_DTYPE, TPL_INT32, TPL_INT64));
```

- `TEMPLATE_MODE = TPL_SIMT_KERNEL = 2`：A5 唯一实现。
- `INDEX_DTYPE = TPL_INT32(1) / TPL_INT64(2)`：由 `argmax` 的 dtype 决定；tiling 侧 `GetTilingKey()` 用 `GET_TPL_TILING_KEY(TPL_SIMT_KERNEL, idxDtype, 0)` 编码模板参数，kernel 侧 `if constexpr` 实例化 `AdaptiveMaxPool3dGradSimt<VALUE_T, int32_t|int64_t>`。

运行期分支（同一实例内）：

| 分支 | 触发条件（A5） | 行为 |
|---|---|---|
| 输出零初始化 | 恒执行 | 全部线程按 grid-stride 把 `y` 写 0，随后 `SyncAll()` |
| `IsDeterministic = true` | `deterministicFlag == 1`，即执行上下文开启确定性且 `isOverLap == 1` | 每个线程独占一个 `(N,C)` 平面，按输出位置顺序串行累加，无原子操作，累加顺序固定 |
| `IsDeterministic = false` 且 `isOverLap == 1` | 默认上下文或未开启确定性 | 线程并行遍历全部输出元素，对同一地址使用 `asc_atomic_add` |
| `IsDeterministic = false` 且 `isOverLap == 0` | 空间维全部整除 | 线程并行遍历，直接 `+=`（窗口互不相交，目标地址唯一） |

`isOverLap = (Di % Do != 0) || (Hi % Ho != 0) || (Wi % Wo != 0)`，其中 `Di/Hi/Wi` 为 `x` 的空间维、`Do/Ho/Wo` 为 `grad` 的空间维（tiling 中变量命名按“输入/输出”互换，已按 kernel 实际用法核对）。

索引位宽分支：`int32` 用 `uint32_t` 做整除/取模，`int64` 用 `uint64_t`，仅影响地址计算宽度，不改变语义。

## 4. 分核设计

A5 SIMT 模板不使用 AI Core 的 UB 分块流水，而是按线程并行：

- 每 block `THREAD_DIM = 512` 个线程；线程全局编号 `threadStart = blockIdx * 512 + threadIdx`，步长 `threadStride = blockNum * 512`。
- 非确定性路径：`blockNum = min(outDataCount, coreNum)`，`outDataCount = N*C*Do*Ho*Wo`；最后夹到 `[1, coreNum]`。输出元素少于核数时按元素数开 block，多于核数时每个核处理多轮。
- 确定性路径：`blockNum = ceil(totalNC / 512)`，同样夹到 `[1, coreNum]`；每个线程承担整数个 `(N,C)` 平面。
- `coreNum_` 来自平台 `GetCoreNumAiv()`（`GetPlatformInfo`）。
- 输出零初始化同样使用 grid-stride，覆盖全部 `N*C*Di*Hi*Wi` 个元素。
- workspace：仅 16 MB 系统 workspace，无用户 workspace。
- UB 配置：`SetLocalMemorySize(ubSize - 128KB)`，128 KB 作为 DCACHE 预留。

## 5. 分块设计

A5 路径没有传统意义上的 UB 分块/多缓冲：

- 唯一驻留 UB 的数据是 10 个 `int64` 的 tiling 参数（80 B，`simtTilingDataBuf_`），kernel 启动时从 tiling 数据拷贝到 UB 供 SIMT 段读取。
- 标量索引计算全部在寄存器/SIMT 线程内完成，不依赖 32B 对齐、VL 对齐或尾块处理；非对齐形状只影响 grid-stride 的分配，不影响结果。
- `x` 平面大小 `Di*Hi*Wi` 与输出元素总数均以 `int64` 计算；int32 索引实例用 `uint32_t` 除法，int64 索引实例用 `uint64_t` 除法。
- 对照排除项：arch22 的 `CalUBTotalSize`/`CalBestBaseSize`、按 `baseDo/baseHo/baseWo` 的 UB 切分与 `TILING_UB_CUT_*` 常量只服务 A2/A3 的 normal/scatter 模板，与 A5 无关，未写入需求。

## 6. 性能调优技巧

源码中实际存在的机制与取舍如下：

1. **零初始化与散射分离**：先用全体线程把 `y` 清零并 `SyncAll`，再统一散射；避免了 2-pass 归约或缓存中间结果。
2. **原子操作按需启用**：只有 `isOverLap` 为真时才使用 `asc_atomic_add`；窗口互不相交时直接 `+=`，省去原子开销，这也是“非重叠”这一外部条件在实现上唯一可观察的取舍点。
3. **确定性模式牺牲并行度换可复现性**：确定性路径把整个 `(N,C)` 平面交给单线程串行累加，消除原子与累加顺序的不确定性；代价是平面内不能多线程并行。
4. **按索引位宽特化**：`int32` 索引用 32 位整除，`int64` 用 64 位整除，避免所有场景都付 64 位除法成本。
5. **block 数按输出元素数伸缩**：小规模用例不会开满核，大规模用例按核数饱和，减少空转。
6. **4D 输入仅做视图变换**：`ViewCDHWas5D`/`View5DasCDHW` 不拷贝数据；连续化只在输入本身非连续时发生。

## 7. 模板与测试覆盖映射

目标芯片固定为 A5。TTK 已全量执行，下表“已运行验证”表示该 case 出现在 `ttk/debug/result.csv` 且判为 PASS；“静态推断”仅用于 TTK 无法触发的分支。

| 内部模板/分支 | 源码依据 | 外部触发条件 | case_id | 验证状态 |
|---|---|---|---|---|
| SIMT 模板，`INDEX_DTYPE = TPL_INT32` | `adaptive_max_pool3d_grad_struct.h`；`adaptive_max_pool3d_grad.cpp` 的 `if constexpr` | `argmax.dtype == int32` | 1,2,3,4,5,6,7,11,13,14,15,16,17,18,19,20 | 已运行验证 |
| SIMT 模板，`INDEX_DTYPE = TPL_INT64` | 同上 | `argmax.dtype == int64` | 8,9,10,12 | 已运行验证 |
| `isOverLap == 1`（重叠：原子加 / 确定性串行） | `simt_tiling.cpp` 的 `isOverLap`；kernel `asc_atomic_add` 分支 | `x` 空间维未被 `grad` 空间维整除 | 5,6,7,9,11,15,17,19,20 | 已运行验证 |
| `isOverLap == 0`（非重叠：直接累加） | kernel `else` 分支 | 三个空间维均整除 | 1,2,3,4,8,10,12,13,14,16,18 | 已运行验证 |
| `deterministicFlag == 1`（确定性串行） | `simt_tiling.cpp` 的 `deterministicFlag`；kernel `IsDeterministic` | 执行上下文开启确定性且发生重叠；aclnn 入参无法表达 | — | 未覆盖（环境开关，非用例可触发） |
| 输出零初始化 + `SyncAll` | kernel `InitOutputZeroSimt` | 所有用例（未选中坐标必须为 0） | 全部 | 已运行验证 |
| `x` 取值不参与计算 | kernel `Init` 只绑定 `grad`/`argmax`/`y` | 用例 19：`x` 显式取稀疏值，结果只由 `grad`/`argmax` 决定 | 19 | 已运行验证 |
| 4D CDHW 输入（N=1 视图） | `op_api` `ViewCDHWas5D` / `View5DasCDHW` | `x`、`grad`、`argmax` 为 4 维 | 11,12 | 已运行验证 |
| 非连续输入连续化 | `op_api` `l0op::Contiguous` | `x` 为非连续视图 | 18 | 已运行验证 |
| 小规模：`blockNum` 由输出元素数决定 | `PostTiling` 的 `blockNum` 计算 | 输出元素数 ≤ 48（1、6、8、15、16、27、32 等） | 1,2,5,6,8,9,10,12,19,20 | 已运行验证 |
| 较大规模：按核数饱和 | 同上 | 输出元素数 ≥ 64（64、72、162、192、256、257、512、5049、16384） | 3,4,7,11,13,14,15,16,17,18 | 已运行验证 |
| dtype float16 / float32 / bfloat16 | op def 的 `DataType` 列表；kernel `VALUE_T = DTYPE_X` | `x`/`grad`/`y` dtype | f16：3,6,9,12,14,18；f32：1,2,5,8,11,15,17,19,20；bf16：4,7,10,13,16 | 已运行验证 |
| 空张量（N=0）短路 | `op_api` 的 `IsEmpty()` 提前返回 | 5 维 N=0 | — | 未覆盖（用例不含空张量，见 D6） |

未覆盖说明：

- 确定性开关只能通过 `aclrtCtxSetSysParamOpt` 一类执行上下文配置开启，aclnn 入参与用例数据无法表达，故不作为用例覆盖项；其对数值的影响仅为累加顺序，Golden 的 `scatter_add_` 语义不受影响。
- 空张量（N=0）虽由 aclnn 层短路为成功返回，但本需求把“所有维度 > 0”作为正常输入域，20 条用例不包含空张量；该边界未运行验证。
- 输出空间大于输入空间（用例 20）与元素总数超过单核容量的超大形状只做了代表点覆盖，未穷举。

## 8. 源码依据与需求决策

### 8.1 源码事实

1. op def：输入顺序 `x`、`grad`、`argmax`，输出 `y`；`x`/`grad`/`y` dtype 为 fp16/fp32/bf16，`argmax` 在 `ascend950` 配置下为 int32 或 int64；`x`/`grad`/`argmax` 均为 REQUIRED，无属性。
2. aclnn 接口：`aclnnAdaptiveMaxPool3dBackwardGetWorkspaceSize(gradOutput, self, indices, gradInput, workspaceSize, executor)`，输出张量为第 4 个形参 `gradInput`；支持 4~5 维、ND、非连续 Tensor；A5 上 `indices` 支持 int32/int64；空输入直接返回。
3. A5 走 `AdaptiveMaxPool3DGrad` 算子 + arch35 SIMT kernel；tiling 模板优先级 1，`isOverLap`、`deterministicFlag`、`INDEX_DTYPE` 决定运行分支。
4. kernel 零初始化 `y` 后按 `argmax` 累加 `grad`；`x` 的数值不被读取。
5. `argmax` 是每个 `(N,C)` 平面内 `D*H*W` 上的一维偏移（kernel 的 `inputIdx = nc_offset + maxIdx`）。
6. A5 不在 aclnn 层把整除场景替换为 `MaxPool3DGradWithArgmax`（该分支要求非 regbase）。
7. 现有 ST `executor_aclnnAdaptiveMaxPool3dBackward.py` 的 CPU 参考实现：把 `self` 升 float32 做正向池化得到 indices，再调用 aten 的反向，最后转回原 dtype。

### 8.2 基于代码的推断

1. `isOverLap` 的语义等价于“正向自适应窗口是否重叠”，可用于把内部条件翻译成外部 shape 条件。
2. 非确定性路径下同一坐标的多次原子加顺序不定，Golden 采用 float32 有序累加后一次性 cast，二者差异应落在 dtype 对应的精度阈值内。
3. 4D 输入在算子内部被补成 5D，索引语义仍按 `(N,C)` 平面偏移，与 5D 一致。

### 8.3 AI 需求决策

| 编号 | 决策 | 依据与影响 |
|---|---|---|
| D1 | 需求包采用 op def 输入顺序 `(x, grad, argmax)`，并在 `design.md` 记录与 aclnn `(gradOutput, self, indices, gradInput)` 的映射 | op def 是算子原型事实源；TTK 适配时必须按 aclnn 槽位重排为 `grad→slot0, x→slot1, argmax→slot2, y→slot3` |
| D2 | 支持 4 维 CDHW 与 5 维 NCDHW，4 维按 N=1 处理 | aclnn 文档与实现均支持 4D（`ViewCDHWas5D`）；Golden 统一按平面组织计算并还原维数 |
| D3 | `y` 的 dtype 恒等于 `x`，`grad` 必须与 `x` 同 dtype | op def 与 `CheckDtypeValid` 均要求三者同 dtype |
| D4 | `argmax` 语义为 `(N,C)` 平面内 `D*H*W` 一维偏移，越界即非法输入 | kernel 坐标计算与 aten 语义一致；Golden 对越界显式报错 |
| D5 | 输出按“累加”而非“赋值”定义：同一坐标可被多个输出位置选中 | 重叠窗口与 upsampling 场景的必然结果，kernel 用原子加/串行加实现 |
| D6 | 正常输入域要求所有维度 > 0；N=0 的空张量不作为正常用例 | host tiling 对 `x` 每维有非零校验，aclnn 对空输入短路；两者组合下空张量不进入 kernel，故不作为功能用例，只记录未覆盖 |
| D7 | Golden 以 float32 累加后 cast 回 `x` dtype | 与源码 ST 参考实现（升 float32 计算）一致；16bit 输入的设备实现按输入 dtype 累加，差异由精度阈值吸收 |
| D8 | 用例的 `argmax` 取 `x` 的正向池化 argmax（`index_source=forward_argmax`） | 满足“indices 是正向输出”的语义，且在非重叠窗口下自动保证索引互不相同；重叠窗口下自然出现重复索引，覆盖累加 |
| D9 | 只分析 A5；A3/A2 的 normal/scatter 模板、int32-only 索引与 INT32 平面上限不进入需求与用例 | 用户未指定芯片，按默认 A5 |

### 8.4 用户覆盖项

- 源码路径：用户给的是 `/home/cann/...`，实际解析到 `/home/y00893432/work/ops-nn/...`（见 1.1）。
- 输出路径：用户指定 `/home/y00893432/work/ops-dataset`。
- TTK_REPO：用户指定 `/home/y00893432/work/ops-test-kit`。

### 8.5 TTK 状态

TTK 环节状态：**已执行**（`ttk/debug/handoff.json` 的 `status=executed`）。

- 环境：`/home/y00893432/work/ops-test-kit`，`ttk info` 识别 Ascend950DT_9582（A5），`python3 -m ttk` 在仓库根目录串行执行。
- 契约：按 `ttk/debug/signature.txt` 确认张量槽 `gradOutput, self, indices, gradInput`，输出索引 3，无 attributes/scalars；`ttk aclnn --validate` 通过，`ttk list` 为 20 条。
- 用例转换：需求包 `(x, grad, argmax)` 顺序重排为 aclnn 槽序 `grad→0, x→1, argmax→2, y→3`；`indices` 不使用随机值，而由 `customize_inputs` 用 `self` 的正向 `adaptive_max_pool3d` 结果覆写（对应 D8 与需求包 note 的 `index_source`）。case 18 以 `tensor_view_strides/tensor_storage_shapes` 表达非连续 `self`，case 19 用 `attributes` 的显式 `self` 值保证确定的重叠累加。
- 结果：最终 `ttk/debug/result.csv` **20/20 PASS**，全部 `matched_ratio=1.0`；误差为 0 或 1 ULP 量级（fp16 最大绝对误差 4.9e-4、bf16 7.8e-3、fp32 3.7e-7），均在 TTK 默认 `mix_tolerance` 内。
- 首轮全量中 case 15 出现 `rtStreamCreate() Failed: ACL_ERROR_RT_DRV_INTERNAL_ERROR`（设备瞬时错误，未进入精度比对）；清 dump 后单条复跑 PASS，第二轮全量 20/20 PASS。归因为 `environment`，未修改用例、未放宽 tolerance。
- 回流：**未发生**。没有 `golden`/`case` 归因项，需求包 `golden.py`、`cases.yaml`、`cases.csv` 保持 TTK 前的版本；需求包 `cases.csv` 仍为七列，`pass`/`note` 只存在于 `ttk/cases.csv`。
- 遗留：`deterministicFlag` 分支（执行上下文开关）与 N=0 空张量未覆盖，原因见第 7 节。

### 8.6 其他差异记录

- 安装头文件 `aclnn_adaptive_max_pool3d_backward.h` 的注释把 `indices` 描述为 int64，而文档参数表为 INT32/INT64 且仅 A2/A3 不支持 INT64；A5 实测 int32、int64 均通过（case 8~10、12 为 int64）。需求以文档 + op def 的 A5 配置为准。
- `tests/st` 的 297 条 atk 用例 dtype 字段把 `indices` 也写成浮点（执行器在 `init_by_input_data` 中再转 int32），属于用例框架表达，不作为 `argmax` 的 dtype 依据。
