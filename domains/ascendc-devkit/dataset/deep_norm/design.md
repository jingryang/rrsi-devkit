# DeepNorm 算子设计分析（A5）

## 1. 芯片范围与源码布局

### 1.1 芯片范围

本次芯片种类为 **A5（Ascend 950PR / 950DT 系列）**，只分析并产出该芯片范围内的实现与结论。

采用的源码路径：

| 内容 | 路径 |
|---|---|
| 接口文档 | `docs/aclnnDeepNorm.md` |
| device kernel | `op_kernel/arch35/deep_norm.cpp`、`deep_norm.h`、`deep_norm_partial_load.h`、`deep_norm_tiling_data.h` |
| host tiling | `op_host/arch35/deep_norm_tiling_arch35.cpp`、`deep_norm_tiling_arch35.h` |
| 公共 shape/dtype 校验 | `op_host/deep_norm_shape_check.h` |
| 算子原型 | `op_host/deep_norm_def.cpp`（`OpAICoreConfig config950`）、`op_graph/deep_norm_proto.h` |
| 芯片二进制配置 | `op_host/config/ascend950/deep_norm_binary.json` |
| 构建映射 | `op_host/CMakeLists.txt`（`ascend950 → arch35`）、`op_kernel/CMakeLists.txt`（`ascend950 → arch35/deep_norm.cpp`） |

排除在范围外的内容（不进入需求、golden、cases、desc）：

- `op_host/arch22/deep_norm_tiling.cpp/.h`：A3/A2/310p/Kirin 使用的旧 tiling 路径；
- `op_kernel/deep_norm.cpp`：为 `ascend910b`、`ascend910_93`、`ascend310p`、`kirinx90`、`kirin9030` 编译的旧 kernel；
- `op_host/config/ascend910b`、`ascend910_93`、`ascend310p`、`kirin9030`、`kirinx90`：非 A5 的二进制配置；
- 文档中 Atlas A3 / A2 / Atlas 推理 / Atlas 训练 / 200I 等支持行；
- `tests/ut/**`：仅作分支线索，未作为需求语义来源。

源码中 A5 具备完整链路：`deep_norm_def.cpp` 通过 `AddConfig("ascend950", config950)` 注册，kernel/tiling/config 均有 arch35/ascend950 对应物，因此不存在芯片缺口。源码没有 `ascend350` 的独立配置，A5 范围内以 `ascend950` 路径为准。

### 1.2 文档版本选择

`docs/` 下只有一个候选 `aclnnDeepNorm.md`，文件名与 `ops_pascal = DeepNorm` 精确匹配，无版本后缀歧义。

接口名由三处交叉确认，唯一确定为 `aclnnDeepNorm`：

1. 文档函数原型 `aclnnDeepNormGetWorkspaceSize(x, gx, beta, gamma, alpha, epsilon, meanOut, rstdOut, yOut, workspaceSize, executor)`；
2. 已安装头文件 `/usr/local/Ascend/cann-9.1.0/aarch64-linux/include/aclnnop/aclnn_deep_norm.h` 中的同名签名；
3. `tests/st/aclnnDeepNorm/executor_aclnnDeepNorm.py` 的 `get_cpp_func_signature_type()` 与 `api_type = aclnn_deep_norm`。

被排除的文档候选：`README.md`（背景说明，仅用于核对约束冲突）；不存在 `*FusionPass*.md`、`ascendir*.md`、`torchapi_*.md` 等候选。目录名 `deep_norm` 与接口名 `aclnnDeepNorm` 版本一致，无需记录版本映射。

关键契约（来自文档 + `deep_norm_def.cpp`）：

| 项 | 值 |
|---|---|
| 输入顺序 | `x, gx, beta, gamma` |
| 输出顺序 | `mean, rstd, y`（op def `Output(mean) → Output(rstd) → Output(y)`；aclnn 输出槽索引 4/5/6） |
| 属性 | `alpha`（float，默认 0.3）、`epsilon`（float，默认 1e-6）；aclnn 形参为 `double`，host 侧按 float 使用 |
| 输入 dtype | FLOAT16 / FLOAT32 / BFLOAT16，且 x/gx/beta/gamma 必须一致 |
| 输出 dtype | mean/rstd 固定 FLOAT32；y 与 x 一致 |
| 维度 | x 2-8 维；gamma/beta 1-7 维且严格小于 x 维度数 |
| 格式 | ND |

## 2. 实现概览

host 侧 `DeepNormTilingFunc` 的执行顺序（`op_host/arch35/deep_norm_tiling_arch35.cpp:256`）：

1. `CheckDeepNormShapeDim`：校验 x 维度 [2,8]、gamma 维度 [1,7]、gx 与 x 同维、y/mean/rstd 与 x 同维、beta 与 gamma 同维、x 维数大于 gamma 维数；
2. `CheckDeepNormShapeValue`：任一维不得为 0；gx/y 与 x 同 shape；mean/rstd 前导维等于 x；gamma/beta 等于 x 的尾部维；
3. `CheckReduceOutputTail`：mean/rstd 的尾部归一化维必须全为 1（仅 arch35 强制）；
4. `CheckDeepNormDtype`：x/gx/beta/gamma/y 必须同为 FLOAT16/FLOAT32/BFLOAT16；
5. `GetPlatformInfo`：取 AIV 核数与 UB 大小；
6. `GetShapeInfo`：`numCol = Π gamma.shape`（归一化维展平长度），`numRow = Π x 前导维`；
7. `GetAttrInfo`：读取 alpha/epsilon，缺省分别取 0.3、1e-6；
8. `CalcTilingParams`：`rowPerCore = CeilDiv(numRow, coreNum)`，`usedCoreNum = CeilDiv(numRow, rowPerCore)`，`numColAlign = CeilAlign(numCol, 64)`，并计算 `powerSplit`；
9. 按 `numCol` 与 UB 预算选择整行载入（tiling key 0）或分块载入（tiling key 1）；
10. `SetTilingData`：写入 `DeepNormTilingData`，设置 `BlockDim = usedCoreNum` 与 `SetTilingKey`。

device 侧数据流：

```text
h = alpha * x + gx                    (fp32)
sum = reduce_sum(h)
mean = sum / numCol
hc = h - mean
var = reduce_sum(hc * hc) / numCol
rstd = 1 / sqrt(var + epsilon)        (Newton-Raphson)
y = hc * rstd * gamma + beta          (转回输入 dtype)
```

整行载入路径逐行复用已载入的 gamma/beta，把 `h` 以 fp32 保存在 UB 内并原地中心化；分块载入路径按 tile 三次遍历 x/gx，不保存整行。

## 3. 模板设计

### 3.1 分发入口

`op_kernel/arch35/deep_norm.cpp:35-43` 按 tiling key 分发：

```cpp
if (TILING_KEY_IS(0)) {
    NsDeepNorm::DeepNorm<DTYPE_X, 0> op; ...
} else if (TILING_KEY_IS(1)) {
    NsDeepNorm::DeepNormPartialLoad<DTYPE_X> op; ...
}
```

- key 0 → `NsDeepNorm::DeepNorm<T, 0>`（`op_kernel/arch35/deep_norm.h`），整行载入；
- key 1 → `NsDeepNorm::DeepNormPartialLoad<T>`（`op_kernel/arch35/deep_norm_partial_load.h`），分块载入；
- 模板参数 `T` 由框架按 `DTYPE_X` 展开，同一 tiling key 覆盖 fp16/fp32/bf16 三种 dtype，dtype 差异只体现在元素字节宽度与 UB 预算。

### 3.2 路径选择条件

`deep_norm_tiling_arch35.cpp:308-315`：

```text
fullLoadLimit = (dtypeSize == 4) ? 8192 : 15360
useFullLoad   = numCol <= fullLoadLimit
                && CalcFullLoadUbRequired(numColAlign, dtypeSize) <= ubSize
tilingKey     = useFullLoad ? 0 : 1
```

UB 需求模型（`CalcFullLoadUbRequired`，第 195 行）：

```text
foldLoops        = CeilDiv(numColAlign, 64)
reduceTmpElems   = max(CeilAlign(foldLoops, 8), 128)
requiredBytes    = numColAlign * (5 * dtypeSize + 4)   // x/gx/gamma/beta/y + h(fp32)
                 + reduceTmpElems * 4                  // 二分归约临时区
                 + 3 * 32                              // mean/rstd 队列 + sum 缓冲
```

在 A5（`Ascend950DT_9582`，平台配置 `ub_size = 253952`）上的代入结果：

| dtype | numCol | numColAlign | 需求字节 | 结论 |
|---|---:|---:|---:|---|
| float32 | 8192 | 8192 | 197216 | 整行载入（长度上限恰好取到） |
| float32 | 8193 | 8256 | — | 超过 8192，分块载入 |
| float16/bfloat16 | 15360 | 15360 | 216096 | 整行载入（长度上限恰好取到） |
| float16/bfloat16 | 15361 | 15424 | — | 超过 15360，分块载入 |

即在本平台上长度上限先于 UB 上限生效；若平台 UB 更小，UB 条件会把部分本可整行载入的 shape 提前推入分块路径。

### 3.3 归约折叠点

`CalcTilingParams`（第 152 行）计算 `powerSplit`：

```text
powerSplit = 64
if numCol > 64:
    while powerSplit < numCol: powerSplit *= 2
    powerSplit /= 2
```

即 `numCol ≤ 64` 时固定 64；否则取严格小于 `numCol` 的最大 2 的幂（且为 64 的整数倍）。该值传给 `CalculateReduceSum` 作为二分归约的折叠点，不改变数学结果，只影响归约顺序与临时区大小。分块路径的每个 tile 另有 `GetPowerSplit(count)`，取不大于 `count/2` 的最大 2 的幂（至少 64）。

### 3.4 无其他模板分支

arch35 下没有 dtype 专属模板、没有属性触发的模板（alpha/epsilon 只作为标量参与计算）、没有多输出差异化模板；输出顺序固定为 mean、rstd、y。

## 4. 分核设计

- 分核维度是行（`numRow`），每核处理一段连续行：`rowStart = blockIdx * rowPerCore`，`rowWork = min(numRow - rowStart, rowPerCore)`；`rowStart >= numRow` 的核直接返回（`deep_norm.h:116-123`、`deep_norm_partial_load.h:100-106`）。
- `rowPerCore = CeilDiv(numRow, coreNum)`，`usedCoreNum = CeilDiv(numRow, rowPerCore)`，`BlockDim = usedCoreNum`（tiling 第 156-161、251 行）。行数少于核数时，只有前 `numRow` 个核各处理 1 行；行数不能被核数整除时，最后一个核处理不足 `rowPerCore` 行。
- kernel 使用 `KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY)`，只使用 AIV 核。
- 归一化维不跨核切分：同一行的 mean/rstd 必须由单核完整归约，因此分块路径也只在一个核内按 tile 串行遍历。
- A5（`Ascend950DT_9582`）平台配置 `vector_core_cnt = 64`，即 tiling 中 `GetCoreNumAiv()` 的可用核数为 64。

用例对分核的覆盖：用例 16 为 256 行（64 核 × 4 行，整除）；用例 17 为 257 行（`rowPerCore = 5`、`usedCoreNum = 52`，末核处理 2 行）；用例 1/2/3 等行数远小于核数，覆盖大量核空转。

## 5. 分块设计

### 5.1 整行载入路径（key 0）

单行完整放入 UB，缓冲区分配（`deep_norm.h:133-151`）：

| 缓冲区 | 大小 | 说明 |
|---|---|---|
| x / gx / gamma / beta / y 队列 | 各 `numColAlign * sizeof(T)` | gamma/beta 在行循环外载入一次 |
| h | `numColAlign * sizeof(float)` | `alpha*x+gx` 的 fp32 中间结果 |
| sum | 32 B | 单元素归约结果 |
| 二分归约临时区 | `max(CeilAlign(CeilDiv(numColAlign,64),8), 128) * 4` B | 至少 2×VL |
| mean / rstd 队列 | 各 32 B | 每行一个标量 |

- `numColAlign` 是 `numCol` 按 fp32 向量长度 64 元素（256 B）向上对齐，保证向量循环整块；
- `DataCopyPad` 的右填充按 32 B 块对齐（`blockElems = 32/sizeof(T)`），而不是按 VL 对齐，避免填充超过一个块导致越界；
- 归约只统计真实 `numCol` 个元素（`CalculateReduceSum(..., numCol, powerSplit)`；平方归约传 `numColAlign` 但有效长度 `numCol`），填充区不参与统计；
- `CalcY` 与中心化循环同样只处理 `[0, numCol)`。

### 5.2 分块载入路径（key 1）

`CalcPartialTileLength`（tiling 第 205 行）：

```text
bytesPerElement = 5 * dtypeSize + 4
maxElements     = (ubSize - 2048) / bytesPerElement
maxElements     = min(maxElements, 4096)
maxElements     = floor(maxElements / 64) * 64
```

A5 上 `ubSize = 253952`：fp32 为 `(253952-2048)/24 = 10496`，fp16/bf16 为 `17993`，两者都被上限截到 **4096**，再按 64 对齐仍为 4096。因此 A5 的分块长度固定为 4096 个元素。

- 单行按 `tileLength` 切成若干 tile，末 tile 用 `min(tileLength, numCol-col)` 取实际长度；
- 每行三遍遍历：第一遍求 `Σh` 得 mean，第二遍求 `Σ(h-mean)²` 得方差并算 rstd，第三遍重新载入 x/gx/gamma/beta 计算 y（`deep_norm_partial_load.h:335-396`）；
- 每个 tile 累加进 32 B 的标量缓冲，跨 tile 的累加仍是 fp32 顺序加法；
- 缓冲区为 5 个 dtype 队列 + 1 个 fp32 calc 队列 + 32 B tileSum + 128 个 fp32 的 reduceTmp。

### 5.3 对齐与尾块

- 归一化长度按 64 元素（fp32 VL）对齐；32 B 块对应 fp32 8 元素、fp16/bf16 16 元素，因此低精度 dtype 的尾块粒度更细；
- 末尾 tile/向量使用 `UpdateMask` 屏蔽无效 lane，输出拷贝按真实 `numCol` 长度写回；
- `numCol ≤ 64` 时分块载入路径的 `GetPowerSplit` 固定返回 64，与整行路径的 `powerSplit` 一致。

## 6. 性能调优技巧

以下均为源码中实际存在的机制：

1. **整行载入避免重复读取**：当一行能放进 UB 时，x/gx/gamma/beta 只读一次，h 以 fp32 保存在 UB 内原地中心化，第二次归约直接复用（`deep_norm.h:322-363`）。
2. **gamma/beta 跨行复用**：整行路径在行循环外载入 gamma/beta 一次，行内只重复载入 x/gx（`deep_norm.h:318-320`）。
3. **二分折叠归约**：用 `powerSplit` 把长归约折成树形求和，减少串行累加链（`CalculateReduceSum` / `CalculateSquareReduceSum`）。
4. **Newton-Raphson 求 rstd**：`ComputeRstdNewtonRaphson<true, true>` 用迭代代替开方/除法，降低标量路径延迟。
5. **按行多核并行**：行之间完全独立，按行切分到最多 64 个 AIV 核，尾核按剩余行数收缩。
6. **分块路径以重读换取 UB 占用**：超长归约不保存整行，改为三遍遍历，用额外两次全局读换取 O(tile) 的 UB 占用（`deep_norm_partial_load.h`）。
7. **寄存器级向量化**：arch35 kernel 使用 `RegTensor` + `__VEC_SCOPE__`，按 fp32 向量长度 64 元素成块处理，`DataCopyPad` 处理 32 B 尾块。

## 7. 模板与测试覆盖映射

目标芯片固定为 A5。验证状态按 `<TTK_WORKDIR>/debug/result.csv` 与 `debug/verify_fp64.log` 升级：20 条用例均在设备上实际执行，按需求包 MERE/MARE 判据 20/20 PASS（golden 为用户指定 float32 计算）。

| 目标芯片 | 内部模板/分支 | 源码依据 | 完整外部触发条件 | case_id | 验证状态 |
|---|---|---|---|---|---|
| A5 | tiling key 0 / `DeepNorm<T,0>` 整行载入，fp32 | `deep_norm_tiling_arch35.cpp:308` | dtype=float32 且 numCol ≤ 8192 且 UB 预算足够 | 1, 4, 7, 16, 19, 20 | 已运行验证 |
| A5 | tiling key 0 / 整行载入，fp16 | 同上 | dtype=float16 且 numCol ≤ 15360 | 2, 5, 9, 14, 18 | 已运行验证 |
| A5 | tiling key 0 / 整行载入，bf16 | 同上 | dtype=bfloat16 且 numCol ≤ 15360 | 3, 6, 11, 15, 17 | 已运行验证 |
| A5 | tiling key 1 / `DeepNormPartialLoad`，fp32 | `deep_norm_tiling_arch35.cpp:315` | dtype=float32 且 numCol > 8192 | 8, 13 | 已运行验证 |
| A5 | tiling key 1 / 分块载入，fp16 | 同上 | dtype=float16 且 numCol > 15360 | 10 | 已运行验证 |
| A5 | tiling key 1 / 分块载入，bf16 | 同上 | dtype=bfloat16 且 numCol > 15360 | 12 | 已运行验证 |
| A5 | 分块路径多 tile（tile=4096） | `deep_norm_tiling_arch35.cpp:205-222` | numCol > 4096 且走分块载入（20000 → 5 个 tile） | 13 | 已运行验证 |
| A5 | `numColAlign` 64 元素对齐 + 尾块掩码 | `deep_norm.h:133-151`、`deep_norm_partial_load.h:136-143` | numCol 非 64 倍数（1/63/65/257/500/8193/15361/20000 等） | 1, 2, 3, 4, 5, 8, 10, 12, 13 | 已运行验证 |
| A5 | 32 B 块粒度尾块（低精度更细） | 同上 | fp16/bf16 的 numCol 非 16 倍数（8/63/65/85/257/15361） | 2, 3, 5, 10, 12, 14, 18 | 已运行验证 |
| A5 | 多轴归一化（gamma 维数 > 1） | `deep_norm_tiling_arch35.cpp:118-126` | gamma 为 2 维或 3 维，numCol 为各维乘积 | 14, 19, 20 | 已运行验证 |
| A5 | 最大维度组合（x 8 维、gamma 7 维） | `deep_norm_shape_check.h:27-30` | x.ndim=8 且 gamma.ndim=7 | 20 | 已运行验证 |
| A5 | 多核行切分、整倍数 | `deep_norm_tiling_arch35.cpp:156-161` | numRow=128（64 核 × 2 行）、256（64 核 × 4 行） | 16, 18 | 已运行验证 |
| A5 | 多核行切分、尾核 | 同上 | numRow=257 → rowPerCore=5、usedCoreNum=52、末核 2 行 | 17 | 已运行验证 |
| A5 | 行数远小于核数、空转核提前返回 | `deep_norm.h:116-120` | numRow ∈ {1,2,3,4,5,6,8}（远小于 64 核） | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 19, 20 | 已运行验证 |
| A5 | 方差为 0 的数值稳定分支 | `deep_norm.h:344-348`（`var+epsilon`） | 每行 h 恒定，var=0，rstd=1/√epsilon | 15 | 已运行验证 |
| A5 | 非默认 alpha/epsilon | `deep_norm_tiling_arch35.cpp:140-149` | alpha=0.5、epsilon=1e-5 | 19 | 已运行验证 |
| A5 | 非连续输入（x） | `deep_norm_def.cpp` `.AutoContiguous()` | x 为末维步长 2 的视图 | 16 | 已运行验证 |

未覆盖/不适用的分支：

- NaN/Inf 特殊值未纳入用例（TTK 的 `input_data_ranges` 无法表达 NaN），仅在第 6 节记录无特殊值覆盖；
- 空 Tensor（任一维为 0）被 tiling 拒绝，不属于合法功能用例；
- gamma/beta 的非连续视图未单独构造（x 已覆盖非连续语义）；
- fp16/bf16 的分块多 tile（numCol>8192 且走分块）没有独立用例，仅用例 13 覆盖 fp32 多 tile。

## 8. 源码依据与需求决策

### 8.1 源码事实

- 输入/输出顺序、属性默认值与 dtype 约束来自 `op_host/deep_norm_def.cpp:22-62` 与 `op_graph/deep_norm_proto.h`；
- 形状推导来自 `op_host/deep_norm_infershape.cpp`：mean/rstd 维数等于 x，尾部归一化维为 1，y 与 x 同 shape；
- 合法 shape/dtype 校验来自 `op_host/deep_norm_shape_check.h`（x 维 [2,8]、gamma 维 [1,7]、x 维数 > gamma 维数、所有维 > 0、dtype 一致）；
- 路径切换阈值 8192 / 15360、UB 预算公式、tile 上限 4096 来自 `op_host/arch35/deep_norm_tiling_arch35.cpp:39-51、195-222、308-315`；
- 计算顺序 `h → mean → var → rstd → y` 与 fp32 升精度来自 `op_kernel/arch35/deep_norm.h:189-295` 与 `deep_norm_partial_load.h:220-332`；
- rstd 使用 Newton-Raphson 迭代（`ComputeRstdNewtonRaphson`），并非直接 `1/sqrt`。

### 8.2 golden 来源与重写

- 来源：`tests/assets/golden.py` 的 `_compute_deep_norm`（`__golden__` 中 kernel 与 aclnn 两个入口共享该计算核心）。
- 重写：删除 `__golden__`/`__spec__`/`__input__`/容差注册、`**kwargs`、`output_dtypes` 分支和空输入回退；保留按 gamma 维度确定归约轴、mean/rstd 转 fp32、y 转输入 dtype 的语义；入口命名为 `deep_norm`，返回 `[mean, rstd, y]`。
- **计算精度按用户显式要求改为 float32**（源码 golden 原为 float64）：四个输入先转 `torch.float32`，全部中间量在 float32 下计算，`mean/rstd` 直接以 float32 输出，`y` 再转输入 dtype。该变更属于用户覆盖，不是源码事实。
- 源码 golden 对非法/空 shape 返回零张量；需求契约中所有输入维度必须大于 0，因此去掉该回退（AI 决策，理由：回退会掩盖非法输入，且不属于合法功能用例）。
- CPU 对照（20 条用例的 TTK 生成输入，fp32 golden 对源码 float64 参考）：
  - `mean` 最大相对误差 ≤ 5.9e-6（MERE ≤ 3.5e-6）；
  - `rstd` 最大相对误差 ≤ 1.3e-7；
  - `y` 的正常值域误差 ≈0，近零点的最大相对误差 ≤ 6.7e-3，来源是 fp32 计算与最终 dtype 舍入；
  - 20 条用例的输出 shape/dtype 全部与 `proto.yaml` 的 shape 规则一致；
  - 该对照只说明 fp32 golden 与高精度参考的偏差量级，不代表 fp32 golden 更准确。
- 输出顺序 mean、rstd、y 按 op def 与 aclnn 输出槽确定。

### 8.3 需求决策与冲突处理

| 项 | 依据/决策 |
|---|---|
| 空 Tensor | `aclnnDeepNorm.md` 写“支持空Tensor”，但 `README.md` 写“不支持空Tensor”，且 `CheckDeepNormShapeValue` 明确拒绝任何 0 维。以源码为准：不支持空 Tensor，用例不覆盖 0 维。 |
| alpha/epsilon 类型 | op def 与图原型为 Float；aclnn 形参为 double。proto/golden 使用 float 语义，aclnn 的 double 入参按 float 规约，不改变契约。 |
| 输出顺序 | 按 op def 的 `mean → rstd → y`，与 aclnn 输出槽 4/5/6 一致。 |
| 用例 15 的构造 | 取 x≡0、gx≡1，使每行 h≡1.0（fp32/bf16 均可精确表示），sum=257 与 mean=1 在 fp32 下精确，var 严格为 0，`rstd = 1/sqrt(epsilon)`；不使用 0.3·x+gx 这类不可精确表示的常量，避免近零抵消。 |
| 用例 16 的非连续构造 | 仅 x 使用末维步长 2 的视图；gx/beta/gamma 连续。文档声明 x 支持非连续输入，输出按连续张量写回。 |
| 用例 20 | x 取 8 维、gamma 取 7 维，覆盖文档允许的维度上限组合。 |
| 阈值取点 | 8192/8193（fp32）、15360/15361（fp16/bf16）分别覆盖路径切换两侧；4096 的 tile 上限由用例 13（20000）以多 tile 覆盖。 |
| golden 计算精度 | **用户显式覆盖**：统一改为 float32 计算。源码 `tests/assets/golden.py` 原为 float64；本需求按用户要求改为 float32，属于用户覆盖而非源码事实。 |
| 用户覆盖 | 除 golden 计算精度外，未收到 dtype/布局/属性等显式覆盖；芯片种类取默认 A5。 |

### 8.4 TTK 环节状态

**已执行**（`status = executed`），产物目录 `<需求文件夹>/ttk/`。

- 环境：`python3 -m ttk info` 实测 8 张 `Ascend950DT_9582`（A5）；device 6/7 出现 `aclrtSetDevice 507033`（HBM 被占用），改用 `--devices 0,1,2,3,4,5` 后完整跑通，该现象未归因为算子问题（environment）。
- 签名：7 个张量槽，`output_tensor_indexes = (4,5,6)`，与安装头文件 `aclnn_deep_norm.h` 一致（`debug/contract.md`、`debug/signature.txt`）。
- golden：按用户显式要求改为 float32 计算；TTK 侧 `ttk/golden.py` 的 `_compute` 已同步为 float32（形参适配层，不写入需求包）。
- 结果：**PASS 20 / FAIL 0 / SKIP 0**（需求包 MERE/MARE 判据，阈值取 fp32 2^-13、fp16 2^-10、bf16 2^-7，未放宽）。
- 同一批数据用 TTK 默认 `mix_tolerance` 判据同样 20/20 PASS（`debug/result_mixed_tolerance.csv`）；另用独立 fp64 参考按需求包判据逐槽复算，20/20 在阈值内（`debug/verify_fp64.log`）。
- 无 FAIL 归因，无 golden/case 回流修正。

关键覆盖取证：

- 用例 8（此前 fp64 golden 下的唯一超阈值点）：改用 float32 golden 后，同一 seed、同一数据下 y 槽 MARE=6.77e-4、MERE=1.84e-7，PASS；该点仍是近零抵消点（\|y\|/\|beta\|≈1.3e-4），设备相对 fp64 参考的偏差 1.23e-3 属于 fp32 固有舍入，不是算子缺陷。
- 用例 15（mixed，x≡0、gx≡1）：以常量区间 `(0,0)/(1,1)` 精确表达，实测 mean=1.0、rstd≈1000.00006（=1/√1e-6）、y==beta，方差为 0 分支成立。
- 用例 16（noncontiguous_input）：以 view=(256,64)、stride=(128,2)、storage=(256,128)、offset=0 表达，`ttk.log` 中 `aclCreateTensor` 实际收到该 stride 与 storage shape，gx/beta/gamma 保持连续，PASS。
- 分块路径（用例 8、10、12、13）与整行路径（其余）均在设备上实际执行并 PASS。

### 8.5 遗留事项

- **参考精度取舍（用户覆盖）**：golden 已按用户要求改为 float32。相对 fp64 参考，fp32 golden 自身在 `y` 近零点的最大相对偏差约 6.7e-3（主要为最终 dtype 舍入），`mean/rstd` ≤ 5.9e-6/1.3e-7；该选择使参考精度与被测实现的 fp32 计算同档，判定更宽松，属于已知取舍而非源码事实。
- **seed 与随机序列不可逐值复现**：需求包约定 seed 固定为 case_id（全局约定，不写入 note），TTK 无逐用例 seed 字段，统一用 `--seed 20251021`；`[lo,hi]` 区间忠实映射，但具体随机值与需求包约定序列不是逐值同源。数值结论只对 TTK 生成的这组数据成立（已用 fp64 独立参考复核）。
- **平台名未固定**：芯片种类由 `--chip A5` 统一决定、未逐用例映射为 `soc_series`，运行按默认平台 `Ascend950DT_9582`；如需锁定平台应加 `--plat` 重跑。
- **非恒定 mixed 逐值序列**：TTK CSV 无逐值字段；本轮用例 15 为常量列表已精确表达，按物理行循环的非常量序列需 `customize_inputs` 插件，本轮未覆盖。
- **用例覆盖缺口**：NaN/Inf 传播、空 Tensor、gamma/beta 非连续视图未纳入 20 个用例；fp16/bf16 的分块多 tile（numCol>8192 且走分块）没有独立用例，仅用例 13 覆盖 fp32 多 tile。
- **平台差异**：本平台 UB=253952 下长度阈值先于 UB 条件生效；其他 A5 平台若 UB 更小，实际路径切换点会提前，用例仍合法但覆盖映射中的路径归属可能变化。
