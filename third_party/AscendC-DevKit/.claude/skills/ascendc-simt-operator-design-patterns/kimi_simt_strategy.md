# SIMT 设计策略提取

> 基于多个 AscendC 算子仓库（涵盖 math 数学类与 nn 神经网络类算子）的 arch35（Ascend 950）SIMT 实现提取。
> 覆盖范围：Tiling（`op_host/arch35/*tiling*.cpp`）与 Kernel（`op_kernel/arch35/*.h`），按算子类别组织，每条策略附源码片段与出处。
> 算子目录约定：Kernel 位于 `<op>/op_kernel/arch35/`（`__simt_vf__` VF 函数、`*_tiling_data.h`、`*_tiling_key.h`），Tiling 位于 `<op>/op_host/arch35/`。

---

## 〇、SIMT 编程模型与跨类别通用设计约定

### 0.1 SIMT 定位（为什么用 SIMT）

Ascend 950 系列新增 SIMT 单元。SIMT 在处理**非规整离散访问**方面相比 SIMD 有较大优势，适合地址不连续、访存跨度变化大、分支路径不一致的场景（scatter/gather、索引重排、稀疏更新等）。

实践中需重点关注：一是线程任务切分要与数据稀疏性匹配，避免线程负载极不均衡；二是减少高频随机访存导致的流水空转，尽量在上游完成索引规整与分桶；三是将边界处理与主路径解耦，避免在热点循环中引入过多分支。建议同时对比"纯 SIMD 实现"和"SIMD+SIMT 混合实现"，按数据分布选择最优策略，而非固定单一路径。

- 来源：`docs/zh/develop/cross_platform_migration_guide.md`

### 0.2 SIMT Kernel 通用骨架（所有算子的最小范式）

```cpp
constexpr uint32_t THREAD_NUM = 1024;

// __simt_callee__: 被 VF 调用的设备函数
__simt_callee__ __aicore__ inline float ComputeOne(float v) { ... }

// __simt_vf__: SIMT 向量化函数（VF）；LAUNCH_BOUND 限定每核线程数以控制寄存器占用
template <typename T>
__simt_vf__ __aicore__ LAUNCH_BOUND(THREAD_NUM) inline void OpSimtKernel(int64_t total, __gm__ T* x, __gm__ T* y)
{
    // grid-stride 循环：全程 uint64 防 blockIdx*threadNum 32-bit 溢出
    uint64_t stride = static_cast<uint64_t>(Simt::GetThreadNum()) * Simt::GetBlockNum();
    for (uint64_t index = static_cast<uint64_t>(Simt::GetBlockIdx()) * Simt::GetThreadNum() + Simt::GetThreadIdx();
         index < total; index += stride) {
        y[index] = ComputeOne(x[index]);
    }
}

// AICore 侧发射
Simt::VF_CALL<OpSimtKernel<T>>(Simt::Dim3(THREAD_NUM), totalNum, x_gm, y_gm);
// 等价形式：asc_vf_call<Kernel>(dim3(THREAD_NUM), ...);
```

- 线程索引 API 两套等价：`Simt::GetThreadIdx()/GetThreadNum()/GetBlockIdx()/GetBlockNum()` 或 CUDA 风格 `threadIdx.x/blockDim.x/blockIdx.x/gridDim.x`。
- **两级 blockIdx 不可混用**：外层 `__aicore__` 的 `GetBlockIdx()` 是算子分核核号；VF 内的 `blockIdx.x` 是 VF grid 概念。需要算子核号时必须在外层读取后显式传参进 VF（ragged_bin_count 注释明确记录）。
- 来源：`math/atanh/op_kernel/arch35/atanh_simt.h`、`index/ragged_bin_count/op_kernel/arch35/ragged_bin_count_simt.h`

### 0.3 通用 Tiling 约定

| 约定 | 内容 | 代表出处 |
|---|---|---|
| blockDim 封顶物理核数 | `usedCoreNum = min(CeilDiv(total, coreNum), coreNum)`，下限 1；SIMT 核内 grid-stride 覆盖全部元素，blockDim 不随元素数膨胀（旧实现膨胀会触发 507035 vector core exception） | `math/atanh/op_host/arch35/atanh_tiling_arch35.cpp` |
| 每核最小工作量钳制 | `perCoreElements = max(CeilDiv(total, coreNum), PER_CORE_MIN=1024)`（或 128B/核），反推 needCoreNum，避免小 shape 空转核 | pooling/optim/foreach 各算子 |
| DCache 预留 | SIMT 线程需 UB 内预留 DCache 区，三档并存：32KB（sort/elementwise 系）/ 64KB / 128KB（foreach、polling、ragged 系），one_hot 58KB；host 用 `SetDynUBufSize(ubSize - DCACHE_SIZE)`（主线仓源码片段里的 `SetLocalMemorySize` 是同一函数的废弃旧名，语义一致——生成代码写新名） | 全仓库统一 |
| 平台参数动态化 | `PlatformAscendC.GetCoreNumAiv()` / `GetCoreMemSize(UB)`，禁止硬编码核数/UB | 全部 tiling |
| compileInfo 空指针回退 | TilingParse 缓存的 compileInfo 可能为 null（nnopbase 路径），fallback 直读 `context->GetPlatformInfo()` | `math/cdist/op_host/arch35/cdist_tiling_arch35.cpp` |
| 模板注册表竞选 | `REGISTER_OPS_TILING_TEMPLATE(Op, TilingClass, priority)` 注册多模板，入口只调 `TilingRegistry::DoTilingImpl`，按优先级遍历 `IsCapable()` 探测；SIMT 模板常作恒真兜底（priority 最大，如 SegmentSum=60、AvgPool=19） | `math/mul`、`index/unsorted_segment_max`、`pooling/avg_pool` |
| workspace 惯例 | 16MB 系统区（RESERVED_WS_SIZE / ASCENDC_TOOLS_WORKSPACE）打底 + 算子专属区追加 | `index/segment_sum/op_host/arch35/segment_sum_simt_tiling.cpp` |
| **host-kernel 强契约（主要工程风险点）** | workspace 分段公式、magic 参数、per-core 区间表、tiling struct 布局两侧必须逐段一致。事故教训：scatter_reduce_common 旧实现 host 侧 workspace "+128 margin" 近似，M>1M 时 kernel 越界（VEC_ERROR）；修复方式是 host 精确复算 kernel 的 `padM = P2*runLen0`（P2 把 runLen0 压到 ≤8192 的 2 的幂） | `index/scatter_reduce_common/op_host/arch35/scatter_reduce_common_tiling.cpp:195-213` |
| tilingKey 编译期分发 | 三代编码并存：①老式大数段（`基数 2000000000 + dtype 提升档，int64 加 100`）②组合式（`opCode*4 + dtypeIdx`）③新式声明式 ASCENDC_TPL 树（`GET_TPL_TILING_KEY(schMode, 特性位...)`，同 key 树两分支可挂不同 tiling struct）；kernel `if constexpr` 或模板特化展开 | 全部算子 |

### 0.4 通用 Kernel 约定

| 约定 | 内容 | 代表出处 |
|---|---|---|
| grid-stride 三范式 | A. 核内段循环 `for(idx=threadIdx.x; idx<count; idx+=blockDim.x)`；B. 全局跨核 `idx = blockIdx*blockDim+threadIdx; idx += gridDim*blockDim`；C. 等价变体 `idx += blockNum*blockDim` | conversion 各类算子 |
| 索引位宽双路径 | 偏移 ≤ INT32_MAX 用 int32 索引 + 1024 线程（寄存器压力小）；超限切 int64 + 512 线程；`THREAD_NUM = sizeof(IDX_T)==4 ? 1024 : 512` 为常见写法 | `math/tan`、`pooling/max_pool_v3_grad` |
| magic number 快除 | host/aicore 侧 `GetUintDivMagicAndShift(m, s, divisor)` 预计算，VF 内 `Simt::UintDiv(x, m, s)` 或手写 `q = (__umulhi(x,m)+x) >> s` 替代硬件除法 | conversion/index/pooling 全部 |
| 低精度升 fp32 计算 | half/bf16 经 `__half2float/__bfloat162float` 升 fp32 计算，`__float2half_rn/__float2bfloat16_rn` 写回；`AccType/ComputeType` traits 集中定义提升规则 | 全部浮点算子 |
| 线程数分档 | arch35 单核最大 2048 线程；按寄存器压力选 2048/1024/512/256/128/64，`LAUNCH_BOUND(n)` 标注；`__DAV_FPGA__` 下统一降档 | conversion K29 |
| SIMT+SIMD 混合流水 | 连续批量数据移动用 SIMD/DMA（Duplicate/DataCopyPad/SetAtomicAdd），不规则核心（随机读+算下标+随机原子写）交 SIMT VF；`SetFlag/WaitFlag<HardEvent::V_MTE3/S_V>` 做依赖同步 | histogram、one_hot_mix、sort 小轴 |
| 跨核协作 | `SyncAll()` 核间屏障必须配合 tiling 侧 `SetScheduleMode(1)`（batch mode 全核同时驻留）；GM workspace 中转 + `__builtin_cce_dcci`/`DataCacheCleanAndInvalid` 刷 cache | histogram、deformable_offsets_grad、sparse_mm |
| 原子操作谱系 | `asc_atomic_add/max/min/cas/exch/or`（VF 内）、`Simt::AtomicMax/Min/Cas`、`SetAtomicAdd<T>()+DataCopyPad+SetAtomicNone()`（SIMD DMA 整块原子加，仅支持部分 dtype） | scatter/histogram 各算子 |
| shuffle/warp 原语 | `asc_reduce_add`（warp 归约，仅支持部分 dtype）、手写 `asc_shfl_down` 循环（兼容 double/bf16/complex）、`__shfl` 广播、`asc_shfl_up` Kogge-Stone 扫描 | cosine_similarity、trace、hash、radix_sort |
| 特殊内存访问 | `asc_ldcg/asc_stcg` 绕 L1 cache 的 GM 读写（随机读带宽榨取）；`__gm__ volatile` 防编译器重排 | histogram_fixed_width、coalesce_sparse、max_pool_v3_grad |

### 0.5 写冲突解决方案谱系（scatter 类通用）

| 方案 | 确定性 | 适用条件 | 代表算子 |
|---|---|---|---|
| SIMT 逐元素原子（asc_atomic_add/max/min） | 否（浮点顺序不定） | 尾轴小、访存离散 | scatter_add、inplace_scatter_add |
| 无原子指令时的 CAS 自旋 | 否 | atomicMul 不存在等 | unsorted_segment_prod |
| 小位宽 dtype 升精度 workspace 三段式（Cast→atomic→Cast 回） | 否 | int8/uint8/int16/bool 无原子加 | scatter_add、inplace_index_add、sparse_mm(B16) |
| 排序归并：排序使同目标相邻 + 段内寄存器折叠 + 每唯一行一次原子 | 段内确定 | 重复索引率高 | scatter_add_simt_sort、index_put_with_sort_v2 |
| 输出侧 gather 重建（每输出元素反向扫描输入） | 是 | 输出小/输入小、N 不大 | bincount_determine、sparse_segment_sum_grad、chamfer_distance_grad、avg_pool_grad |
| 按行/槽位切核 + 核内串行 | 是 | 行归属可静态划分 | scatter_max_with_argmax（GT 严格大于 tie-break）、inplace_update |
| 跨界段 workspace 暂存 + 单核按序归并 | 是 | 排序已知且段可能跨核 | segment_sum、scatter_add_with_sorted 确定性模式 |
| 无别名语义免原子 | 是 | indices 唯一由语义保证 | scatter_non_aliasing_add |
| SIMD `SetAtomicAdd` 整块原子拷贝 | 否 | 尾轴连续大块 | scatter_add SIMD 路径、histogram UB 折叠 |

---
## 一、逐元素数学函数类（Elementwise Math）

> 分析范围：`math/` 下 acos, asin, atanh, cos, sin, tan, expm1, mod, floor_div, floor_mod, truncate_div, mul, gcd, polar, sinc, select, eye, one_hot 的 arch35 实现。
> 总体观察：这批算子收敛为**三种工程形态**：
> 1. **DAG 表达式模板 + 内嵌 SIMT 自定义节点**（acos/asin/cos/sin/sinc/expm1/mod/floor_div/floor_mod/truncate_div/mul/gcd/select 主路径）：tiling 与搬运交给 `ElewiseBaseTiling`/`BroadcastBaseTiling` 框架，计算节点内部用 `asc_vf_call`/`Simt::VF_CALL` 在 UB tile 上启动 `__simt_vf__` 微 kernel；
> 2. **纯 SIMT 大 kernel**（atanh/tan）：`Simt::VF_CALL` 直接对 GM 做 grid-stride 循环，手工分核；
> 3. **SIMD+SIMT 混合/双路径 kernel**（one_hot/eye/select）：SIMD 做批量填充，SIMT 做稀疏散写或特殊 shape。

### Tiling 策略

#### T1. 一元算子统一走 `ElewiseBaseTiling` + DAG 模板，按 dtype 选 `OpDag` 实例

- 适用算子：asin、acos、cos、sin、sinc、expm1
- 策略说明：一元 elementwise 不涉及广播，直接复用基础库的 `ElewiseBaseTiling` 框架完成分核与 UB 切分；tiling 侧只负责三件事：校验 dtype/shape、按输出 dtype 实例化对应的 `XxxDAG<T>::OpDag` 模板传给 `DoTiling`、回写 `SetBlockDim(tiling->baseTiling.blockNum)`。分核公式（按 UB 容量折叠、尾块处理）全部收敛到框架，避免每个算子重复实现。

```cpp
ge::graphStatus AsinTiling::RunTiling()
{
    ElewiseBaseTiling elewiseBaseTiling(tilingContext);
    ...
    if (this->outputDtype == ge::DT_FLOAT16) {
        res = elewiseBaseTiling.DoTiling<AsinOpWithCast<half>::OpDag>(tiling->baseTiling, ASCEND_API_BUFFER + DCACHE_SIZE);
    } else if (this->outputDtype == ge::DT_FLOAT) {
        res = elewiseBaseTiling.DoTiling<AsinOpDirect<float>::OpDag>(tiling->baseTiling, ASCEND_API_BUFFER + DCACHE_SIZE);
    } else if (this->outputDtype == ge::DT_BF16) {
        res = elewiseBaseTiling.DoTiling<AsinOpWithCast<bfloat16_t>::OpDag>(tiling->baseTiling, ASCEND_API_BUFFER + DCACHE_SIZE);
    }
}
```

- 来源：`math/asin/op_host/arch35/asin_tiling_arch35.cpp`（acos/sin/cos/sinc/expm1 同构）

#### T2. UB 预算：预留框架缓冲 + DCache，LocalMemorySize 扣除 DCache

- 适用算子：asin、acos、cos、sin、sinc、expm1、mod、floor_div、floor_mod、truncate_div、mul、gcd、one_hot
- 策略说明：arch35 上 SIMT 需要使用一块 DCache 作为线程本地存储，因此给 DAG 框架的 UB 可用量要加上 `ASCEND_API_BUFFER(120K) + DCACHE_SIZE(32K)` 的预留参数；同时通过 `SetDynUBufSize`（主线仓源码片段仍写其废弃旧名 `SetLocalMemorySize`，同一函数）把 DCache 从 UB 中扣除，防止 SIMD 侧越界。one_hot 的 SIMT DCache 更大（58K）。

```cpp
const int64_t DCACHE_SIZE = 32768;
const int64_t ASCEND_API_BUFFER = 122880; //120K
...
ascendcPlatform.GetCoreMemSize(platform_ascendc::CoreMemType::UB, ubSizePlatForm);
tilingContext->SetLocalMemorySize(static_cast<uint32_t>(ubSize - DCACHE_SIZE));
// one_hot: SIMT DCache 占用更大
constexpr int64_t SIMT_DCACHE_SIZE = static_cast<int64_t>(58 * 1024);
tilingData_.set_ubSize(ubSize_ - SIMT_DCACHE_SIZE);
```

- 来源：`math/asin/op_host/arch35/asin_tiling_arch35.cpp`、`math/one_hot/op_host/arch35/one_hot_tiling_arch35.cpp`

#### T3. 二元/广播算子走 `BroadcastBaseTiling<OpDag>`，tilingKey 取 schMode

- 适用算子：mul、mod、floor_div、floor_mod、truncate_div、gcd、select（DAG 主路径）
- 策略说明：带广播的二元算子使用 `BroadcastBaseTiling<OpDag>` 模板完成广播 shape 推导、分核与 schMode（调度模式）选择；tilingKey 直接用 `GET_TPL_TILING_KEY(brcBaseTiling.GetSchMode())` 编码调度模式，kernel 入口再用同一 schMode 实例化 `BroadcastSch`。同时向框架传递高阶 API 需要的临时 buffer 参数（如 mod 的 Fmod 临时空间、int64 分支的 DCACHE_SIZE）。

```cpp
ge::graphStatus ModTiling::DoOpTiling()
{
    // kernel中所有输入类型均cast到float32后进入高阶API计算，因此临时buffer按float大小计算
    AscendC::GetFmodTmpBufferFactorSize(sizeof(float), maxLiveNodeCnt, extraBuf);
    ...
    } else if (input0Dtype == ge::DT_INT64) {
        BroadcastBaseTiling<ModOp::ModIntOp<int64_t>::OpDag> brcBaseTiling(
            context_, static_cast<uint32_t>(BROADCAST_KERNEL_TYPE::KERNEL_TYPE_NDDMA));
        extraBuf = DCACHE_SIZE;
        ret = brcBaseTiling.DoTiling(extraBuf, 0, true);
        tilingKey = GET_TPL_TILING_KEY(brcBaseTiling.GetSchMode());
    }
```

- 来源：`math/mod/op_host/arch35/mod_tiling_arch35.cpp`

#### T4. `math_tiling_templates_registry` 模板注册 + 优先级竞选机制

- 适用算子：mul、mod、floor_div、floor_mod、truncate_div、gcd、select
- 策略说明：tiling 不直接写死在 `IMPL_OP_OPTILING` 的入口函数里，而是通过 `REGISTER_OPS_TILING_TEMPLATE(Op, TilingClass, PRIORITY)` 把每个 tiling 实现注册进全局 `TilingRegistry`；入口函数只调用 `TilingRegistry::GetInstance().DoTilingImpl(context)`，由注册表按优先级遍历各模板并调用其 `IsCapable()` 选出能处理当前 shape/dtype 的实现。select 注册了两个模板：SIMT 特化（priority 0，`IsCapable` 检查 condition 是否 `(a,1,...,1)` 形态）+ 通用 DAG 模板（priority 1，恒 capable 兜底）。

```cpp
ge::graphStatus TilingForMul(gert::TilingContext* context)
{
    return Ops::Math::OpTiling::TilingRegistry::GetInstance().DoTilingImpl(context);
}
IMPL_OP_OPTILING(Mul).Tiling(TilingForMul).TilingParse<BroadcastCompileInfo>(TilingPrepareForMul);
REGISTER_OPS_TILING_TEMPLATE(Mul, MulTiling, MUL_COMMON_TILING_PRIORITY);

// select_simt_tiling.cpp —— SIMT 特化路径，priority=0（高于 DAG 的 1）
REGISTER_OPS_TILING_TEMPLATE(Select, SelectSimtTiling, SELECT_COMMON_TILING_PRIORITY);
bool SelectSimtTiling::IsCapable()
{
    if (!IsMatchAB()){ return false; }   // condition 形如 (a, 1, ..., 1)
    if (!XDtypeImprove()){ return false; } // 末轴字节数需 >=512 且可按 8B 对齐提升
    return true;
}
```

- 来源：`math/mul/op_host/arch35/mul_tiling_arch35.cpp`、`math/select/op_host/arch35/select_simt_tiling.cpp`

#### T5. dtype 组合 → DAG 结构的哈希映射表派发

- 适用算子：mul
- 策略说明：mul 支持 16 种 (in0, in1, out) dtype 组合（含混合精度），用 `unordered_map<DtypeCombination, TilingFunc>` 把每个 dtype 三元组直接映射到"实例化哪个 DAG 模板"的 lambda，避免超长 if-else 链。

```cpp
const std::unordered_map<DtypeCombination, TilingFunc, DtypeCombinationHash> DTYPE_MAP = {
    {{ge::DT_INT8, ge::DT_INT8, ge::DT_INT8},
     [](MulTiling* tiling) { return DoTiling<MulInt8Op::OpDag>(tiling->GetContext(), tiling->tilingKey_); }},
    {{ge::DT_BF16, ge::DT_FLOAT, ge::DT_FLOAT},
     [](MulTiling* tiling) { return DoTiling<MulMixFpOp<bfloat16_t, float, float>::OpDag>(...); }},
    {{ge::DT_DOUBLE, ge::DT_DOUBLE, ge::DT_DOUBLE},
     [](MulTiling* tiling) { return DoTiling<MulDoubleOp<double>::OpDag>(..., DCACHE_SIZE, 0); }},
    ... };
```

- 来源：`math/mul/op_host/arch35/mul_tiling_arch35.cpp`

#### T6. 纯 SIMT 算子手写分核：blockDim 封顶物理核数，防 vector core exception

- 适用算子：atanh
- 策略说明：纯 SIMT kernel 内部用 grid-stride 循环覆盖全部元素，因此 blockDim 不需要随元素数增长；`usedCoreNum = min(CeilDiv(totalNum, coreNum), coreNum)` 并下限为 1。源码注释明确指出：旧实现 `SetBlockDim(CeilDiv(totalNum, coreNum))` 让 blockDim 随元素数线性膨胀，大 shape 下远超可用核数，触发 507035 vector core exception。

```cpp
    tiling->totalNum = totalNum;
    // blockDim 必须封顶在物理 AIV 核数；SIMT 核内用 grid-stride 覆盖全部元素。
    // 原实现 SetBlockDim(CeilDiv(totalNum, coreNum)) 会让 blockDim 随元素数线性膨胀，
    // 大 shape 下远超可用核数，触发 507035 vector core exception。
    int64_t usedCoreNum = Ops::Base::CeilDiv(totalNum, coreNum);
    if (usedCoreNum > coreNum) { usedCoreNum = coreNum; }
    if (usedCoreNum == 0) { usedCoreNum = 1; }
    context->SetBlockDim(usedCoreNum);
```

- 来源：`math/atanh/op_host/arch35/atanh_tiling_arch35.cpp`

#### T7. 按"每线程最少元素数"计算核需求（线程感知分核）

- 适用算子：tan
- 策略说明：tan 的 tiling 以 `THREAD_NUM(512) × MIN_ELEMENTS_PER_THREAD(4) = 2048` 元素作为单核起步工作量，再向上取整得 needCoreNum 并封顶物理核数，保证每个 SIMT 线程至少分到 4 个元素、避免线程空转。

```cpp
constexpr int32_t THREAD_NUM = 512;
constexpr int32_t MIN_ELEMENTS_PER_THREAD = 4;
int64_t perCoreElements = THREAD_NUM * MIN_ELEMENTS_PER_THREAD;
int32_t needCoreNum = static_cast<int32_t>((totalElements + perCoreElements - 1) / perCoreElements);
if (needCoreNum > static_cast<int32_t>(coreNum)) { needCoreNum = static_cast<int32_t>(coreNum); }
```

- 来源：`math/tan/op_host/arch35/tan_tiling_arch35.cpp`

#### T8. dtype → tilingKey 的模板参数编码（ASCENDC_TPL 机制）

- 适用算子：atanh、tan
- 策略说明：host 侧把 dtype 映射为 schMode 常量（0=fp32,1=fp16,2=bf16），`GET_TPL_TILING_KEY(...)` 生成 key；kernel 侧 `ASCENDC_TPL_ARGS_DECL` 声明 schMode 为模板参数，使 `__global__` 函数按 `template <uint32_t schMode>` 编译出多个实例，运行时由框架按 tilingKey 选择对应二进制。

```cpp
// atanh_tiling_key.h
ASCENDC_TPL_ARGS_DECL(
    Atanh,
    ASCENDC_TPL_UINT_DECL(schMode, 8, ASCENDC_TPL_UI_LIST, ATANH_TPL_SCH_MODE_FLOAT,
                          ATANH_TPL_SCH_MODE_FLOAT16, ATANH_TPL_SCH_MODE_BFLOAT16));
ASCENDC_TPL_SEL(ASCENDC_TPL_ARGS_SEL(...));
// atanh_tiling_arch35.cpp
uint64_t tilingKey = 0;
if (dataType == ge::DT_FLOAT) { tilingKey = GET_TPL_TILING_KEY(ATANH_TPL_SCH_MODE_FLOAT); }
else if (dataType == ge::DT_FLOAT16) { tilingKey = GET_TPL_TILING_KEY(ATANH_TPL_SCH_MODE_FLOAT16); } ...
context->SetTilingKey(tilingKey);
```

- 来源：`math/atanh/op_kernel/arch35/atanh_tiling_key.h`、`math/atanh/op_host/arch35/atanh_tiling_arch35.cpp`

#### T9. one_hot：SIMT 写值分核 + UB 填充分核 两段式，阈值切换混合模式

- 适用算子：one_hot
- 策略说明：one_hot 把输出拆成"先整体填 off_value、再按 indices 散写 on_value"两步。当 `depth > 3 且 prefixDim*suffixDim*depth > 1024` 时启用 UB 混合路径（tilingKey=1001）：单独为 off_value 填充计算 `offValueUsedCoreNum/offValuePerCoreCalSize`，SIMT 写值部分按 `MIN_FACTOR=1024` 元素/核分核；`SetBlockDim(max(usedCoreNum, offValueUsedCoreNum))` 取两者最大值，并用 `SetScheduleMode(1)` 保证所有核同时启动以便 SyncAll 同步。

```cpp
// PostTiling:
context_->SetBlockDim(std::max(tilingData_.get_usedCoreNum(), tilingData_.get_offValueUsedCoreNum()));
if (GetTilingKey() == TILING_KEY_WITH_UB) {
    context_->SetLocalMemorySize(ubSize_ - SIMT_DCACHE_SIZE);
    context_->SetScheduleMode(1); // 设置为batch mode模式，所有核同时启动
}
```

- 来源：`math/one_hot/op_host/arch35/one_hot_tiling_arch35.cpp`

#### T10. eye：按"单 batch 字节数"在 SIMD / SIMT 两条路径间切换，tilingKey 复合编码

- 适用算子：eye
- 策略说明：`numRows*numColumns*typeSize > 32K` 时走 SIMT 大矩阵路径（先清零再对角写 1，按全部元素分核），否则走 SIMD 路径（UB 内构造一个 batch 的眼矩阵再整块 DataCopyPad 循环写出，按 batch 分核）。tilingKey 为 `模式基值(1000 SIMD / 2000 SIMT-uint32 / +100 SIMT-int64) + dtype 序号(0~8)` 的复合编码，kernel 入口用 `TILING_KEY_IS` 逐一匹配。

```cpp
uint64_t EyeTiling::GetTilingKey() const
{
    int64_t tilingKey = SIMD_TILING_KEY;                    // 1000
    if (numRows_ * numColumns_ * typeSize_ > TMP_SIMD_CONDITION) {
        tilingKey = LARGE_SHAPE_TILING_KEY;                 // 2000
        if (allAxis_ > MAX_UINT32_NUM) { tilingKey += LARGE_AXIS_TAG; }  // +100 → int64 索引
    }
    return tilingKey + EYE_SUPPORTED_DTYPE.find(dType_)->second;
}
```

- 来源：`math/eye/op_host/arch35/eye_tiling_arch35.cpp`

#### T11. select_simt：threadNum 自适应收缩 + perCoreElements 对齐线程数

- 适用算子：select（SIMT 特化路径）
- 策略说明：当 condition 是 `(a, 1, 1, ..., 1)` 广播形态时，y 的每 `bSize` 个元素共享一个 condition 值，用 SIMT 直接读 GM 比 SIMD 广播搬运更优。tiling 在小规模下把 threadNum 从默认 1024 逐次减半，直到 `CeilDiv(ySize, threadNum) >= aivNum/2`，保证核数与线程数均衡；perCoreElements 向上对齐到 threadNum 的整数倍。

```cpp
while ((threadNum_ >= NUM_TWO * SMALL_CASE_THREAD_NUM) && (Ops::Base::CeilDiv(ySize_, threadNum_) < (aivNum_ / NUM_TWO))) {
    threadNum_ = threadNum_ / NUM_TWO;
}
perCoreElements = (perCoreElements + threadNum_ - 1) / threadNum_ * threadNum_;  // 对齐到threadNum_的倍数
needCoreNum_ = Ops::Base::CeilDiv(ySize_, perCoreElements);
tilingKey = GET_TPL_TILING_KEY(TILING_KEY, USER_DEF);   // (999, 1) 标识 SIMT 路径
```

- 来源：`math/select/op_host/arch35/select_simt_tiling.cpp`

#### T12. polar：前 formerCore 个核多算一个元素的均衡切分 + 广播 stride 预算

- 适用算子：polar
- 策略说明：polar 支持 abs/angle 广播，tiling 侧在 host 把 shape 对齐到统一 dimNum、预计算 merged/abs/angle/y 四套 stride（广播维度 stride 置 0），使 kernel 内仅需一次"线性下标 → 多维坐标 → 加权和"换算；分核采用经典 `elementsPerCore = total/coreNum`、`formerCore = total%coreNum`，前 formerCore 个核各多分 1 个元素。

```cpp
int64_t elementsPerCore = totalElements_ / coreNum;
int64_t formerCore = totalElements_ % coreNum;
blockDim_ = (totalElements_ < coreNum) ? totalElements_ : coreNum;
// CalcStride：广播维度 stride 置 0
absStride_[i] = (absDims_[i] == 1) ? 0 : strideAbs;
```

- 来源：`math/polar/op_host/arch35/polar_tiling.cpp`

### Kernel 策略

#### K1.【重点】DAG 表达式模板代码生成模式：`Bind<Op, Inputs...>` 描述计算图，`DAGSch` 编译期展开

- 适用算子：asin、acos、cos、sin、sinc、expm1、mod、floor_div、floor_mod、truncate_div、mul、gcd、select
- 策略说明：核心是 atvoss 基础库的表达式模板：每个 DAG 文件用 `Bind<Vec::CopyInBrc<T>, Placeholder::In0<T>>` 等类型别名声明节点（节点 = 操作 + 输入依赖），`Elems<OpCopyOut>` 声明输出集合，`DAGSch<Outputs, void, MemOptCfg<MemLevel::LEVEL_2>>` 在编译期把整条链展开成融合 kernel（CopyIn→Cast→计算→Cast→CopyOut 全部在一个 UB tile 流水内完成，无中间 GM 往返）。Host 侧 tiling 把 `XxxOp<T>::OpDag` 作为模板参数传给 `ElewiseBaseTiling::DoTiling` / `BroadcastBaseTiling`，kernel 入口用 `ElementwiseSch<0, OpDag>` 或 `BroadcastSch<schMode, OpDag>` 实例化调度器执行。

```cpp
// asin_dag.h —— fp32 直通 / fp16、bf16 升精度两条 DAG
template <typename T>
struct AsinOpWithCast {
    using OpCopyIn = Bind<Vec::CopyIn<T>, Placeholder::In0<T>>;
    using Cast0 = Bind<Vec::Cast<float, T, AsinDag::CastModeToFp32>, OpCopyIn>;
    using OpAsin = Bind<AsinDag::AsinCustom<float>, Cast0>;
    using Cast1 = Bind<Vec::Cast<T, float, AsinDag::CastModeToBf16>, OpAsin>;
    using OpCopyOut = Bind<Vec::CopyOut<T>, Placeholder::Out0<T>, Cast1>;
    using Outputs = Elems<OpCopyOut>;
    using MemCfg = MemOptCfg<MemLevel::LEVEL_2>;
    using OpDag = DAGSch<Outputs, void, MemCfg>;
};
// asin_apt.cpp —— kernel 入口按 DTYPE_X 选 DAG，交给 ElementwiseSch 调度
if constexpr (std::is_same<DTYPE_X, half>::value) {
    ElementwiseSch<0UL, AsinDag::AsinOpWithCast<half>::OpDag> sch(&(tilingData.baseTiling), &pipe);
    sch.Init(x, y); sch.Process();
}
```

- 来源：`math/asin/op_kernel/arch35/asin_dag.h`、`math/asin/op_kernel/asin_apt.cpp`

#### K2. DAG 内嵌 SIMT 自定义节点：`ElemwiseUnaryOP` 包装 `asc_vf_call`，SIMT 处理 UB tile

- 适用算子：asin、acos、cos、sin、sinc、expm1、mod、floor_div、truncate_div、mul、gcd
- 策略说明：DAG 中的自定义计算节点继承 `Vec::ElemwiseUnaryOP/BinaryOP/TernaryOP`，构造函数拿到框架切好的 `LocalTensor`（位于 UB），取出物理地址后用 `asc_vf_call<XxxSimtCompute<T>>(dim3(THREAD_NUM), ...)` 在 UB 上启动 `__simt_vf__` 微 kernel；微 kernel 内用 `threadIdx.x / blockDim.x` 做块内循环。把"框架负责搬运/分块 + SIMT 负责超越函数/整数除法等向量指令不擅长的计算"统一起来，实现 SIMD-SIMT 融合流水。

```cpp
// cos_dag.h
template<typename T>
__simt_vf__ __aicore__ LAUNCH_BOUND(THREAD_NUM) inline void CosSimtCompute(
    __ubuf__ T* x, __ubuf__ T* y, const int64_t totalNum)
{
    for(int64_t i = threadIdx.x; i < totalNum; i += blockDim.x){ y[i] = Simt::Cos(x[i]); }
}
template<class T>
struct CosCustom : public Vec::ElemwiseUnaryOP<T, T> {
    __aicore__ inline CosCustom(LocalTensor<T> &dst, LocalTensor<T> &src, uint32_t count) {
        __ubuf__ T* srcAddr = (__ubuf__ T*)src.GetPhyAddr();
        __ubuf__ T* dstAddr = (__ubuf__ T*)dst.GetPhyAddr();
        Simt::VF_CALL<CosSimtCompute<T>>(Simt::Dim3(THREAD_NUM), srcAddr, dstAddr, count);
    }
};
// floor_div_dag.h —— int32/int64 走 SIMT 除法（向量核无整数除法指令），floor 修正：异号且余数非零，商减 1
bool signs_differ = ((src1[index] < 0) != (src2[index] < 0));
if (signs_differ) {
    const auto quot = src1[index] / src2[index];
    const auto rem = src1[index] - src2[index] * quot;
    dst[index] = rem ? quot - 1 : quot;
} else { dst[index] = src1[index] / src2[index]; }
```

- 来源：`math/cos/op_kernel/arch35/cos_dag.h`、`math/floor_div/op_kernel/arch35/floor_div_dag.h`

#### K3. 纯 SIMT 大 kernel：GM 直读直写 + grid-stride 循环 + 全程 uint64 防溢出

- 适用算子：atanh（tan、select_simt、polar、one_hot、eye 同模式）
- 策略说明：与 DAG 模式不同，atanh/tan 不经 UB，`Simt::VF_CALL` 直接对 GM 启动网格。kernel 内用 `blockIdx*threadNum + threadIdx` 得全局下标、`threadNum*blockNum` 为步长的 grid-stride 循环，一线程处理多元素；**全程 uint64** 计算 index/stride，避免 `blockIdx*threadNum` 在 32-bit 下溢出。

```cpp
uint64_t threadNum = static_cast<uint64_t>(Simt::GetThreadNum());
uint64_t blockNum = static_cast<uint64_t>(Simt::GetBlockNum());
uint64_t stride = threadNum * blockNum;
for (uint64_t index = static_cast<uint64_t>(Simt::GetBlockIdx()) * threadNum +
         static_cast<uint64_t>(Simt::GetThreadIdx());
     index < total; index += stride) {
    if constexpr (std::is_same_v<T, float>) { y[index] = AtanhFloat(x[index]); }
    else if constexpr (std::is_same_v<T, half>) {
        y[index] = __float2half_rn(AtanhFloat(__half2float(x[index])));
    } ...
}
```

- 来源：`math/atanh/op_kernel/arch35/atanh_simt.h`

#### K4. 索引位宽模板化：int32/int64 双实例，LAUNCH_BOUND 随位宽降档

- 适用算子：tan（one_hot、eye 同思路）
- 策略说明：索引类型 IDX_T 做成模板参数：元素数 ≤ INT32_MAX 时用 int32 索引开 1024 线程（寄存器压力小、占用率高），超过时退化到 int64 索引开 512 线程（64 位索引寄存器翻倍，降低 LAUNCH_BOUND 防寄存器溢出）。

```cpp
template <typename IDX_T>
static constexpr uint32_t THREAD_NUM = (sizeof(IDX_T) == 4) ? 1024 : 512;
if (totalElements <= static_cast<int64_t>(INT32_MAX)) {
    AscendC::Simt::VF_CALL<OpTanSimtKernel<T, int32_t>>(AscendC::Simt::Dim3(THREAD_NUM<int32_t>), ...);
} else {
    AscendC::Simt::VF_CALL<OpTanSimtKernel<T, int64_t>>(AscendC::Simt::Dim3(THREAD_NUM<int64_t>), ...);
}
```

- 来源：`math/tan/op_kernel/arch35/tan_simt.h`

#### K5. 精度策略：atanh 小输入泰勒展开替代 log 公式

- 适用算子：atanh
- 策略说明：`atanhf` 的 log 公式 `0.5*ln((1+x)/(1-x))` 在 |x| 接近 0 时分子分母相消丢失有效位；对 |x| < 0.125 改用 `x + x³/3 + x⁵/5 + x⁷/7` 泰勒展开（省略项已低于 FP32 精度），`__simt_callee__` 标记表示被 SIMT kernel 调用的设备函数。

```cpp
__simt_callee__ __aicore__ inline float AtanhFloat(float value)
{
    if (value > -SMALL_INPUT_BOUND && value < SMALL_INPUT_BOUND) {
        float square = value * value;
        return value + value * square * (1.0f / 3.0f + square * (1.0f / 5.0f + square * (1.0f / 7.0f)));
    }
    return atanhf(value);
}
```

- 来源：`math/atanh/op_kernel/arch35/atanh_simt.h`

#### K6. 精度策略：expm1 手写 fmaf 多项式 + exp2f 缩放还原 + 特殊值收尾

- 适用算子：expm1
- 策略说明：expm1 要求 x→0 时高精度（直接 `expf(x)-1` 灾难性抵消）。SIMT kernel 手写完整算法：`k=round(x/ln2)` 规约，`fmaf` 链计算余数多项式，`exp2f(k)` 精确还原数量级（`expm1(x) = 2^k*(1+p(r)) - 1` 拆成 `fmaf(poly, 2^k, 2^k - 1)`），k=128 时特判防溢出，最后处理 ±inf、x<-25→-1、x==0 等特殊值；|x|>2 时直接调库函数 `expm1f`。

```cpp
float f3 = roundf(f1 * INV_LN2_APPROX);          // k
float f8 = fmaf(-f5, LN2_APPROX, f1);
float f10 = fmaf(-f5, ONE_MINUS_LN2_APPROX, f8); // 高低两段减 ln2 保精度
float f23 = fmaf(f10 * f21, f10, f10);           // 多项式 p(r)
float f24 = exp2f(f12);
float f26 = fmaf(f23, f24, f24 - 1.0f);          // 2^k*(1+p)-1
y[i] = fabsf(x[i]) > FLOAT_2 ? f0 : f32;         // 大 |x| 直接用库函数
```

- 来源：`math/expm1/op_kernel/arch35/expm1_dag.h`

#### K7. 精度策略：tan 大输入/特殊值 NaN 语义 + 升精度计算

- 适用算子：tan、asin/acos/cos/sin/sinc（DAG Cast 节点）、mod/floor_div/truncate_div（升 float 除法）
- 策略说明：tan 保留算子既有语义：`|x| >= 1e7` 或 Inf/NaN 直接返回 NaN（`INF/INF` 构造），正常路径用 SIMT 数学库 `tanf`（带高精度规约与奇数象限倒数误差补偿）。fp16/bf16 升精度两种位置：纯 SIMT kernel 内在循环里 `__half2float/__float2half_rn`；DAG 模式用 `Vec::Cast` 节点在 UB 内完成。

```cpp
float abs_x = fabsf(x);
bool is_special = (abs_x >= LARGE_THRESHOLD) || isinf(x) || isnan(x);
float special_result = ASCRT_INF_F / ASCRT_INF_F; // NaN
float result = tanf(x);
float final_result = is_special ? special_result : result;
// floor_div_dag.h —— fp16/bf16 升 fp32 做高精度除法再 floor
using DivRes = Bind<Vec::DivHighPrecision<T2>, CastX1, CastX2>;
using FloorRes = Bind<Vec::Truncate<T2, DIV_CAST_MODE_FLOOR>, DivRes>;
```

- 来源：`math/tan/op_kernel/arch35/tan_simt.h`、`math/floor_div/op_kernel/arch35/floor_div_dag.h`

#### K8. mul-double：无硬件 double 乘法，SIMT 位运算软实现（尾数 53×53 位乘法 + 规格化）

- 适用算子：mul（DT_DOUBLE 分支）
- 策略说明：向量核不支持 fp64 乘法，在 SIMT 微 kernel 里用 union 拆 double 的符号/指数/尾数，尾数 21+32 位拆成高低 32 位做 4 次 32×32→64 乘法（利用 IMAD 的 `u32*u32+u64` 指令处理进位），再经 MSB 查找、桶式左移对齐、CLZ 块内对齐、舍入进位、subnormal 右移降级，手工拼回 IEEE754 double。Inf/NaN/0 按 IEEE 语义提前返回。

```cpp
res[0].il = (unsigned long long)ma_low * (unsigned long long)mb_low;
res[1].il += (unsigned long long)ma_low * (unsigned long long)mb_high;
res[1].il += (unsigned long long)ma_high * (unsigned long long)mb_low;
res[2].il += (unsigned long long)ma_high * (unsigned long long)mb_high;
int n = NOSIGN_OFFSET_32 - __builtin_clz(s3);      // CLZ 计算块内单比特对齐
int ec = ea + (n - BIT_ALIGN) + eb + EXP_BIAS + bias;
if (ec >= MAX_EXP) { ec = MAX_EXP; }               // 输出 inf
else if (ec <= 0) { ... subnormal 右移降级 ... }
```

- 来源：`math/mul/op_kernel/arch35/mul_dag.h`

#### K9. gcd：SIMT 实现二进制 GCD（Stein 算法），按 dtype 调整 launch 线程数

- 适用算子：gcd
- 策略说明：gcd 是带 while 循环的收敛型算法，无法用向量指令表达，天然适合 SIMT。kernel 用二进制 GCD：`__builtin_ffs` 提取公因子 2 的幂、两数各自去除因子 2 后循环"去偶-交换-相减"直到收敛。int64 因寄存器压力大用 `LAUNCH_BOUND(512)`，其余用 1024。

```cpp
uint8_t shift = __builtin_ffs(a | b) - 1;
a >>= __builtin_ffs(a) - 1; b >>= __builtin_ffs(b) - 1;
while (b != 0) {
    b >>= __builtin_ffs(b) - 1;
    if (a > b) { T2 temp = a; a = b; b = temp; }
    b = b - a;
}
dst[index] = a << shift;
if constexpr (IsSameType<T, int64_t>::value) { asc_vf_call<GcdVecInt64<int64_t>>(dim3(512), ...); }
else { asc_vf_call<GcdVec<int32_t, uint32_t>>(dim3(1024), ...); }
```

- 来源：`math/gcd/op_kernel/arch35/gcd_dag.h`

#### K10. DAG 内的寄存器级 SIMD 自定义节点：`__VEC_SCOPE__` + `Reg::` API 做除法后处理

- 适用算子：mod、floor_mod、floor_div（int8 后处理）、truncate_div
- 策略说明：DAG 节点也可用 `__VEC_SCOPE__` 内的寄存器 API（`Reg::LoadAlign/Cast/Compare/Select/StoreAlign`）手写向量逻辑。典型模式是"框架 Div 节点算商 → 自定义三元节点算 `r = a - b*q` 并处理除零/符号修正"：mod 对除数为 0 输出 -1；floor_mod 用符号位异或判断余数与除数异号时 `res += x2`；truncate_div 的 TruncCustom 用 `CAST_TRUNC` 截断后把原符号位 Or 回去（保 -0.0 语义）。

```cpp
// mod_dag.h —— r = x1 - x2*div，除零输出 -1
Reg::Mul(mulValue, input2Value, divValue, preg);
Reg::Sub(subValue, input1Value, mulValue, preg);
Reg::Compare<T2, CMPMODE::NE>(cmpValue, input2Value, zeroValue, preg);
Reg::Select(resValue, subValue, defaultValue, cmpValue);   // defaultValue = -1
// floor_mod_dag.h —— 余数与除数异号且余数非零 → res += x2
Reg::Compare<uint32_t, CMPMODE::NE>(signNegValue, fmodSignValue, inputX2signValue, preg);
Reg::Select(resValue, addValue, fmodResValue, resMaskValue);
```

- 来源：`math/mod/op_kernel/arch35/mod_dag.h`、`math/floor_mod/op_kernel/arch35/floor_mod_dag.h`

#### K11. one_hot 混合 kernel：SIMD `Duplicate` 批量填 off_value + SIMT 稀疏写 on_value

- 适用算子：one_hot（one_hot_mix.h，tilingKey=1001 路径）
- 策略说明：one_hot 输出中 99% 是 off_value。混合模式先由各核用 SIMD `Duplicate` 在 UB 构造 off_value 块、循环 `DataCopyPad` 写出覆盖整个输出，`SyncAll<true>()` 后再由 SIMT kernel 按 indices 散写 on_value（O(N) 次随机写）。SIMT 部分把 `idx / suffixDim` 的整数除法换成 host 预算好的 magic number（`__umulhi + shift`），并按 `endOffset > INT32_MAX` 选择 32/64 位索引版本。

```cpp
// 先 SIMD 填充主体
Duplicate(offValueTensor, offValue_, initSize);
SetFlag<HardEvent::V_MTE3>(eventIdV2Mte3); WaitFlag<HardEvent::V_MTE3>(eventIdV2Mte3);
for (int64_t idx = 0; idx < offValueInitLoop_ - 1; idx++) { CopyOut(offValueTensor, offValueOffset, copyNum); ... }
if (blockIdx_ < tiling->offValueUsedCoreNum) { InitOffValueAndCopyOut(); }
SyncAll<true>();
// 再 SIMT 散写：magic number 快速除法定位 (i,j)
uint32_t t = __umulhi(gmIdx, m); t = t + gmIdx;
int32_t i = t >> shift; int32_t j = gmIdx - i * factor1;
if (inputData[gmIdx] < depth && inputData[gmIdx] >= 0) {
    outputData[i * factorOut1 + inputData[gmIdx] * factorOut2 + j] = onValue;
}
```

- 来源：`math/one_hot/op_kernel/arch35/one_hot_mix.h`

#### K12. one_hot 纯 SIMT 路径：2D 线程块（x=depth 维、y=indices 维）与 depth==1 特化

- 适用算子：one_hot（one_hot.h，tilingKey=1000 路径）
- 策略说明：不经 UB 的纯 SIMT 路径中，每个线程负责"一个输入元素 × 一段 depth"：1024 线程拆成 `(dimX, dimY)` 二维，`threadIdx.y` 遍历输入元素、`threadIdx.x` 遍历 depth 写 off_value；dimX/dimY 按 coreFactor 比例分配并对齐到 32（warp 对齐）。`depth==1` 时每个输出位置恰好对应一个输入元素，用特化 kernel 单线程单元素直接写，省掉内层循环。

```cpp
for (uint32_t idx = static_cast<int32_t>(threadIdx.y); idx < coreFactor; idx += static_cast<int32_t>(blockDim.y)) {
    int32_t gmIdx = startOffset + idx;
    int32_t i = ...; int32_t j = ...; // magic 分解
    for (int64_t axisIdx = static_cast<int64_t>(threadIdx.x); axisIdx < depth; axisIdx += static_cast<int64_t>(blockDim.x)) {
        outputData[i * factorOut1 + axisIdx * factorOut2 + j] = offValue;
    }
    if (inputData[gmIdx] < depth && inputData[gmIdx] >= 0) {
        outputData[i * factorOut1 + inputData[gmIdx] * factorOut2 + j] = onValue;
    }
}
```

- 来源：`math/one_hot/op_kernel/arch35/one_hot.h`

#### K13. eye：SIMD `DataCopyScatter` 打对角 1 / SIMT 清零+对角写 1 双实现

- 适用算子：eye
- 策略说明：小矩阵（SIMD 路径）用 `Reg::Arange` 生成连续序号，向量除法/乘加算出每个 batch 内对角元素的一维散列下标（`batch*rows*cols + row*(cols+1)`），`DataCopyScatter` 一次性把全 1 向量散写到 UB 零 buffer，再整块拷出。大矩阵（SIMT 路径）先用 `Duplicate(0)` + `DataCopyPad` 循环清零 GM，`SyncAll()` 后 SIMT 线程只对 `allAxis = batch*min(rows,cols)` 个对角位置写 1（写次数从 O(N²) 降到 O(N)），用 magic 除法求 batchIdx。

```cpp
// SIMT 大矩阵路径：先清零再对角写 1
for (U i = blockIdx.x * blockDim.x + threadIdx.x; i < allAxis; i += gridDim.x * blockDim.x) {
    uint32_t t1 = __umulhi(i, magic); t1 = t1 + i;
    uint32_t batchIdx = t1 >> shift;
    uint32_t rowIdx = i - batchIdx * perBatchAxis;
    y[batchIdx * numRows * numColumns + rowIdx * numColumns + rowIdx] = static_cast<T>(1);
}
// Process: if (blockIdx_ < td_.usedCoreNum) { DumpGmZero(); } SyncAll(); asc_vf_call<EyeSimt<T, U>>(...);
```

- 来源：`math/eye/op_kernel/arch35/eye_simd.h`、`math/eye/op_kernel/arch35/eye.h`

#### K14. polar：SIMT 直读 GM + host 预算 stride 的广播下标展开，交错写 complex64

- 适用算子：polar
- 策略说明：kernel 不做 UB 搬运，每线程处理一个输出元素：对 host 预算好的 mergedStride 做逐维除法/取余得到坐标，再乘各输入的 stride（广播维 stride=0 自动复用首元素）得 GM 偏移；`Simt::Cos/Sin` 计算后按 `2*yBase, 2*yBase+1` 交错写复数实部/虚部。

```cpp
int64_t v = startIdx + i;
int64_t absBase = 0, angleBase = 0, yBase = 0;
for (int64_t d = 0; d < dimNum; d++) {
    int64_t c = vv / para.ms[d]; vv -= c * para.ms[d];
    absBase += c * para.absS[d]; angleBase += c * para.angleS[d]; yBase += c * para.yS[d];
}
U absVal = absGm[absBase];
yGm[2 * yBase] = absVal * Simt::Cos(angleGm[angleBase]);
yGm[2 * yBase + 1] = absVal * Simt::Sin(angleGm[angleBase]);
```

- 来源：`math/polar/op_kernel/arch35/polar_simt.h`

#### K15. select：DAG（Compare+Select 向量）与 SIMT（magic 除法映射 condition）双 kernel 共存

- 适用算子：select
- 策略说明：select 同时注册两个 kernel 路径。通用路径是纯向量 DAG：`condition` 与常量 1 做 `Compare(NE)` 生成 mask，再 `Select(mask, x1, x2)`；SIMT 特化路径针对 condition 为 `(a,1,...,1)` 形态，`conditionIdx = xyIndex / bSize` 用 `Simt::UintDiv(m, shift)` magic 除法求得，直接读 GM 三选一。kernel 入口用模板参数 `userDef` 分流。

```cpp
// select_simt.h
uint64_t conditionIdx = Simt::UintDiv(xyIndex, m, shift);
y[xyIndex] = condition[conditionIdx] ? x1[xyIndex] : x2[xyIndex];
// select_apt.cpp —— userDef==1 走 SIMT，否则走 DAG
if constexpr(userDef == 1) { SelectOp::SelectSimt<int64_t> selectOp; selectOp.Init(...); selectOp.Process(); }
else { Ops::Base::BroadcastSch<schMode, OpDag> sch(tiling); sch.Process(condition, x1, x2, y); }
```

- 来源：`math/select/op_kernel/arch35/select_dag.h`、`math/select/op_kernel/arch35/select_simt.h`

#### K16. sinc：SIMT 节点内做零点特判的 sin(πx)/(πx)

- 适用算子：sinc
- 策略说明：sinc 在 x=0 处是可去奇点（极限为 1），SIMT 微 kernel 内逐元素特判 `x == 0 → 1`，其余用 `Simt::Sin(PI*x)/(PI*x)`。

```cpp
for (int64_t i = Simt::GetThreadIdx(); i < totalNum; i += Simt::GetThreadNum()) {
    if (x[i] == 0.0f) { y[i] = 1.0f; } else { y[i] = Simt::Sin(PI * x[i]) / (PI * x[i]); }
}
```

- 来源：`math/sinc/op_kernel/arch35/sinc_dag.h`

### 附：Elementwise 类共性速查

| 共性点 | 覆盖算子 | 做法 |
| --- | --- | --- |
| `LAUNCH_BOUND(1024)`（int64/寄存器重时 512） | 全部 SIMT kernel | 限制每核线程数，控制寄存器占用 |
| fp16/bf16 → fp32 升精度 | 全部浮点算子 | DAG 模式用 Cast 节点；纯 SIMT 模式用 `__half2float` 内联转换 |
| 整数除法/取模/gcd 走 SIMT，浮点除法走向量 `DivHighPrecision` | mod、floor_div、floor_mod、truncate_div、gcd | 向量核无整数除法指令 |
| magic number 快速除法 | one_hot、eye、select | host 预计算 m/shift，kernel 免整数除法 |
| `SyncAll` 分隔"SIMD 填充 → SIMT 散写"两阶段 | one_hot_mix、eye | 配合 `SetScheduleMode(1)` batch 模式保证全核同时驻留 |

---
## 二、规约与扫描类（Reduce/Scan）

> 调研对象（均为 arch35 SIMT 实现）：
> | 算子 | 语义 | Kernel 主体 | 并行粒度 |
> |---|---|---|---|
> | prod_force_se_a | DeepMD 力场规约 | `__simt_vf__` 单 VF | 每线程一帧，帧内全串行 |
> | prod_virial_se_a | DeepMD virial 规约（3×3） | `__simt_vf__` 单 VF | 帧间多核 + 帧内 9 线程 |
> | cummin | 累积最小 + argmin | SIMT + 矢量寄存器双路径 | 每线程一条扫描线 |
> | cumulative_logsumexp | 累积 logsumexp | `__simt_vf__` | 每线程一个输出元素 |
> | cosine_similarity | 沿 dim 余弦相似度 | `__simt_vf__` warp 协作 | 每 warp 一个输出元素 |
> | cdist | 成对 p-范数距离 | SIMT / 矢量 / Broadcast / HL-Reduce 四路径 | 每线程一个 (p,r) 输出 |
> | cross | 三维叉积 | `__simt_vf__` | 每线程一个 3 向量 |
> | trace | 矩阵对角线求和 | `__simt_vf__` 两级归约 | 单核全线程分摊对角元 |

### Tiling 策略

**共性归纳**：
1. **所有算子都不沿"规约轴/扫描轴"切核**：规约轴由单个线程/warp/核在内部顺序消化，核间只切外轴（帧/batch/输出行/输出元素），避免跨核部分和合并。
2. **核数估算采用"每核最小工作量"钳制**：`PER_CORE_MIN = 1024` 元素或 `SIMT_MIN_BYTE = 128B`，防止小 shape 下过度分核。
3. **尾块统一用"前多后少"former/tail 模型或"末核拿剩余"模型**。
4. **LocalMemorySize 一律扣除 DCache**（现接口名 `SetDynUBufSize`；旧名主线仓仍用，同一函数）。
5. **索引位宽 32/64 双路径**：按最大地址偏移是否超 `INT32_MAX` 分发。

#### T1. 按"最大工作量子循环"估算核数

- 适用算子：prod_force_se_a
- 策略说明：kernel 单线程处理一整帧，帧内有清零/中心力/邻居力三个工作量悬殊的阶段。tiling 取三者最大值作为每核工作量基准除以核数，再钳制到每核最少 1024 元素，反推实际核数。

```cpp
int64_t maxWorkload = initTotal;
if (centerTotal > maxWorkload) { maxWorkload = centerTotal; }
if (neighborTotal > maxWorkload) { maxWorkload = neighborTotal; }
int64_t perCoreElements = Ops::Base::CeilDiv(maxWorkload, aivCoreNum);
if (perCoreElements < PER_CORE_MIN_ELEMENTS) { perCoreElements = PER_CORE_MIN_ELEMENTS; }
int32_t needCoreNum = static_cast<int32_t>(Ops::Base::CeilDiv(maxWorkload, perCoreElements));
```

- 来源：`math/prod_force_se_a/op_host/arch35/prod_force_se_a_tiling.cpp`

#### T2. 帧间均分 + perCoreFrames 尾帧钳制

- 适用算子：prod_virial_se_a
- 策略说明：以帧（batch 维）为核间切分单位，`perCoreFrames = CeilDiv(nframes, coreNum)` 后用 `needCoreNum = CeilDiv(nframes, perCoreFrames)` 反推实际核数；最后一核尾帧 kernel 侧 `min(frameEnd, nframes)` 钳制。帧间输出互不重叠，无需跨核合并。

```cpp
int64_t perCoreFrames = Ops::Base::CeilDiv(nframes, coreNum);
int64_t needCoreNum = Ops::Base::CeilDiv(nframes, perCoreFrames);
context->SetBlockDim(static_cast<int32_t>(needCoreNum));
```

- 来源：`math/prod_virial_se_a/op_host/arch35/prod_virial_se_a_tiling.cpp`

#### T3. 输出元素总数线性均分 + 尾核单独因子

- 适用算子：cdist（SIMT 标量路径，M≤256）
- 策略说明：输出 `B*P*R` 视为一维元素流，按 `SIMT_MIN_BYTE/dtypeSize`（128B 对应元素数）决定最少核数；`perCoreElement = total/usedCoreNum`，**最后一个核拿全部剩余**。SIMT kernel 内线程按 `index += blockDim.x` 网格步进，单核内部已能均衡，核间粗粒度即可。

```cpp
int64_t minPerCoreElement = SIMT_MIN_BYTE / dtypeSize_;
int64_t minRequiredCores = Ops::Base::CeilDiv(totalElements, minPerCoreElement);
int64_t usedCoreNum = std::min(coreNum_, minRequiredCores);
int64_t perCoreElement = totalElements / usedCoreNum;
int64_t tailCoreElement = totalElements - perCoreElement * (usedCoreNum - 1);
```

- 来源：`math/cdist/op_host/arch35/cdist_tiling_arch35.cpp`

#### T4. 多实现路径的实测标定路由（SIMT / 矢量 Normal / Broadcast / HL-Reduce 四选一）

- 适用算子：cdist
- 策略说明：按 M（规约轴长度）与 P·R（输出平面）路由到 4 种 KERNEL_MODE：`M==1` 且 broadcast 谓词胜出走 Broadcast 快路径；`M∈[2,256]` 且 `hlVectorWins`（一组 msprof 实测标定常量排除劣化场景）走 broadcast+高层 ReduceRepeat；`M≤256` 其余走 SIMT 标量；`M>256` 走矢量 Normal。体现"规约轴短时 SIMT 标量灵活、规约轴长时矢量吞吐占优"的交叉点思想。

```cpp
// msprof 实测标定的路由谓词（含 6 个硬编码劣化带，摘要）
if (M == 1) {
    if (plane == 1 || P > 64 || R > 64 || (plane >= 256 && min(P,R) >= 9 && ...)) { return BroadcastPath; }
    return SimtPath;
} else if (M <= 256) {
    // 实测劣化带硬编码排除：R ≤ 10、(p==2 且 M<24)、(M∈(66,70) 且 R≥300 且 B≤112) 等
    if (R <= 10 || (p == 2 && M < 24) || (M > 66 && M < 70 && R >= 300 && B <= 112) || ...) { return SimtPath; }
    return (M >= 32 || (M >= 16 && P * R <= 262144)) ? HlPath : SimtPath;
}
```

```cpp
bool hlVectorWins = !isInf && !smallRBad && ... &&
    ((M_ >= kHlVectorMMin) || (M_ >= kHlVectorMEx && (P_ * R_) <= kHlVectorMaxPR));
if (M_ >= 2 && M_ <= M_SIZE && hlVectorWins) {
    ubSize_ = ubSize_ - HL_UB_RESERVE;   // 预留两块 8192-elem fp32 计算平面
    DoNormalTiling();
    CapUbFactorRForHL();
} else if (M_ <= M_SIZE) { DoSimtTiling(); } else { DoNormalTiling(); }
```

- 来源：`math/cdist/op_host/arch35/cdist_tiling_arch35.cpp`

#### T5. 三轴折叠 (M, R, N) + 按 UB 容量选择切分方向（M→R→N 逐级降级）

- 适用算子：cummin
- 策略说明：任意维输入按 dim 折叠为 M（外）×R（扫描轴）×N（内）。UB 装得下 `alignedN * R` 多行时走 tilingKey=0（RN 全载，切 M）；装不下看能否一次载多行 N：能则 key=1（切 R），否则 key=2（切 N）。核心思想：扫描轴 R 的顺序依赖不能跨 UB tile 打断时优先整载，装不下才分段并由 kernel 跨段传递 running min。

```cpp
if (Ops::Base::FloorDiv(ubSize_ / dSize_ - alignedN_, alignedN_ * R) >= 1) {
    tilingKey_ = 0; DoUBSliceForM(tilingData_.mRowsPerCore);
} else {
    DoUBSlice(tilingData_.generalProcessInfo, N);
    tilingKey_ = 2 - tilingData_.generalProcessInfo.isNFullyLoad;
}
```

- 来源：`math/cummin/op_host/arch35/cummin_tiling.cpp`

#### T6. 余数行（reservedRows）按 cacheline 将 N 轴二次分核

- 适用算子：cummin
- 策略说明：`M % coreNum != 0` 时余数行不再每行一核，而是把 N 轴按 cacheline 粒度切成 `perGroupCoreNum` 段，让一个行组内多个核并行处理不同 N 段（扫描沿 R 进行，N 是无关内轴可自由切）。不足 2 个 cacheline 不值得切分。这是"行数不足、核有富余"场景的补救式二维分核。

```cpp
if (tilingData_.reservedRows > 0) {
    tilingData_.perGroupCoreNum = tilingData_.coreNum / tilingData_.reservedRows;
    tilingData_.formerCore = N % tilingData_.perGroupCoreNum;
    tilingData_.formerCoreComputeLength = N / tilingData_.perGroupCoreNum + 1;
    DoUBSlice(tilingData_.formerCoreProcessInfo, tilingData_.formerCoreComputeLength);
    ...
}
```

- 来源：`math/cummin/op_host/arch35/cummin_tiling.cpp`

#### T7. 小 N 大 M 场景直接切换 SIMT 模板

- 适用算子：cummin
- 策略说明：`N < 128 且 M > 12800 且 R < 12800` 时（内轴极短、外轴巨大，矢量 DataCopyPad 对齐开销占比过高），tilingKey 切到 `COMPUTE_SIMT=3`，blockDim 直接取 `min(M, coreNum)`，由 SIMT kernel 每线程一条扫描线处理——按形状特征在矢量与 SIMT 间做模板级选择。

```cpp
if (N < MIN_N && M > MAX_COUNT && R < MAX_COUNT) {   // MIN_N=128, MAX_COUNT=12800
    tilingKey_ = COMPUTE_SIMT;
    blockDim_ = M > compileInfo_->coreNum ? compileInfo_->coreNum : M;
}
```

- 来源：`math/cummin/op_host/arch35/cummin_tiling.cpp`

#### T8. 广播合并形状 + 预计算四组 stride 下发

- 适用算子：cross
- 策略说明：tiling 把 x1/x2 广播后的 mergedShape、x1/x2/y 各自 stride、mergedStride 全部预计算成定长 8 数组写进 tilingData，kernel 只做"线性下标 → 多维坐标 → 三组基址"的纯整数分解，零分支处理广播。`ySize > INT_MAX` 时置 `usedInt64` 切换 64 位 kernel。

```cpp
for (int64_t i = dimNum1_ - 1; i >= 0; i--) {
    x1Stride_[i] = (x1Dims_[i] == 1) ? 0 : stride[0];   // 广播维 stride 置 0
    x2Stride_[i] = (x2Dims_[i] == 1) ? 0 : stride[1];
    ...
}
tilingData_.usedInt64 = ySize_ > INT_MAX;
```

- 来源：`math/cross/op_host/arch35/cross_tiling.cpp`

#### T9. 单核全线程策略（trace 不做核间切分）

- 适用算子：trace
- 策略说明：trace 输出只有 1 个标量，规约轴（对角线）是唯一能并行的维度。tiling 直接 `SetBlockDim(1)`，把全部并行度交给单核内 256/512 个 SIMT 线程 + 两级归约（warp shuffle → 跨 warp UB buffer），避免多核部分和的原子/workspace 合并开销。

```cpp
int64_t diagSize = (M < N) ? M : N;
int64_t diagStride = stride0 + stride1;   // N + 1
tiling->diagSize = diagSize; tiling->diagStride = diagStride;
context->SetBlockDim(1);
```

- 来源：`math/trace/op_host/arch35/trace_tiling.cpp`

#### T10. 按索引位宽选择 tiling key / 模板（32 vs 64 bit）

- 适用算子：cosine_similarity、prod_force_se_a、cross、trace
- 策略说明：规约类算子地址偏移 = 元素总数 × 规约长度，最容易溢出 int32。cosine 在 host 侧按 `totalOutputElements <= INT32_MAX` 生成两个 tiling key（分别绑定 1024/512 线程的 kernel）；prod_force_se_a 在 kernel Process 里按最大偏移动态选 UINT_T 模板实参。64 位路径线程数减半，因为寄存器压力翻倍。

```cpp
// host: cosine_similarity_tiling.cpp
uint64_t tilingKey = (tiling->totalOutputElements <= static_cast<int64_t>(INT32_MAX)) ?
                         COSINE_SIMILARITY_TPL_KEY_32BIT : COSINE_SIMILARITY_TPL_KEY_64BIT;
// kernel: prod_force_se_a_simt.h
int64_t maxOffset = std::max(maxInOffset, maxForceOffset);
if (maxOffset <= static_cast<int64_t>(INT32_MAX)) { asc_vf_call<OpProdForceSeASimt<T, uint32_t>>(...); }
else { asc_vf_call<OpProdForceSeASimt<T, uint64_t>>(...); }
```

- 来源：`math/cosine_similarity/op_host/arch35/cosine_similarity_tiling.cpp`、`math/prod_force_se_a/op_kernel/arch35/prod_force_se_a_simt.h`

#### T11. 广播 stride 以 UB 定长数组形式传递（shape/strides 入 UB）

- 适用算子：cosine_similarity
- 策略说明：ndim≤8 的 shape 与两套 stride 共 24 个整数，Process 阶段从 tilingData 拷进 UB（`3 * MAX_NDIM` 个元素、32B 对齐），`DataSyncBarrier<MemDsbT::UB>` 后以 `__ubuf__` 指针传入 VF，使 kernel 内多维坐标分解全部读 UB 而非 GM/参数。

```cpp
LocalMemAllocator<AscendC::Hardware::UB> ubAlloc;
LocalTensor<UbT> ubBuf = ubAlloc.Alloc<UbT>(AlignAllocN(UB_TOTAL_ELEMS, sizeof(UbT)));
for (int32_t d = 0; d < tilingData->ndim; d++) {
    ubBuf.SetValue(OFF_BCAST_SHAPE + d, static_cast<UbT>(tilingData->broadcastShape[d]));
    ubBuf.SetValue(OFF_X1_STRIDES + d, static_cast<UbT>(tilingData->x1Strides[d]));
    ...
}
DataSyncBarrier<MemDsbT::UB>();
```

- 来源：`math/cosine_similarity/op_kernel/arch35/cosine_similarity_simt.h`

#### T12. compileInfo 空指针回退直读平台（健壮性）

- 适用算子：cdist
- 策略说明：nnopbase 单算子路径可能不调 TilingParse 导致 compileInfo 为 null，tiling 的 Init 做 fallback：直接从 `context->GetPlatformInfo()` 读 coreNum/ubSize，保证两条入口路径行为一致。

```cpp
auto compileInfo = reinterpret_cast<const CdistCompileInfo*>(tilingContext_->GetCompileInfo());
if (compileInfo != nullptr) { coreNum_ = compileInfo->coreNum; ubSize_ = compileInfo->ubSize; }
else {
    auto platformInfo = tilingContext_->GetPlatformInfo();
    auto ascendcPlatform = platform_ascendc::PlatformAscendC(platformInfo);
    coreNum_ = static_cast<int64_t>(ascendcPlatform.GetCoreNumAiv());
    ascendcPlatform.GetCoreMemSize(platform_ascendc::CoreMemType::UB, ubSize);
}
```

- 来源：`math/cdist/op_host/arch35/cdist_tiling_arch35.cpp`

### Kernel 策略

**共性归纳**：
1. 线程↔数据映射全部是 grid-stride / block-stride 循环；
2. **规约轴全部由"线程内顺序累加"消化，无跨核部分和**：cosine 是 warp 内 lane 分摊 + shuffle；trace 是线程分摊 + 两级 shuffle/UB；其余纯线程内串行。跨线程只用 shuffle 或 UB buffer + syncthreads，没有跨核归约；
3. 累加器普遍提升精度到 float32/int64；
4. 坐标分解用 magic number 除法或预计算 stride；
5. `__launch_bounds__` 线程数按寄存器压力分档（64 位索引一律减半）。

#### K1. 每线程一帧、帧内完全串行的确定性规约（精度优先）

- 适用算子：prod_force_se_a
- 策略说明：力场输出中同一原子被"中心项减、多个邻居项加"，并行累加会引入不确定性且与 golden 不一致。kernel 让每线程独占一帧，帧内先清零再严格按 golden 循环顺序串行累加；并用 `volatile` 局部变量阻止编译器把乘加融合成 FMA，保证"乘后一次舍入、加减再一次舍入"的两步舍入与 CPU 一致。

```cpp
for (UINT_T frame = blockIdx.x * blockDim.x + threadIdx.x; frame < nframes; frame += blockDim.x * gridDim.x) {
    for (UINT_T i = 0; i < frameForceSize; i++) { force[frameForceBase + i] = static_cast<T>(0); }
    for (UINT_T atom = 0; atom < nloc; atom++) {
        for (UINT_T a = 0; a < ndescrpt; a++) {
            for (UINT_T d = 0; d < COORD_DIM; d++) {
                volatile T prod = net_deriv[netBase + a] * in_deriv[inBase + a * COORD_DIM + d];
                volatile T oldVal = force[atomForceBase + d];
                force[atomForceBase + d] = oldVal - prod;   // 阻止 FMA：两步舍入
            }
        }
    }
}
```

- 来源：`math/prod_force_se_a/op_kernel/arch35/prod_force_se_a_simt.h`

#### K2. 帧内 idz（9 元素）线程并行 + UB float32 缓冲一次性写回

- 适用算子：prod_virial_se_a
- 策略说明：virial 输出是 3×3=9 元素矩阵，天然 9 路并行（`COMPUTE_THREAD_NUM=32` 对齐 warp，仅前 9 线程有效，`idz>=9` 直接返回）。每个 idz 线程负责 `(idz/3, idz%3)` 分量，串行 (i,j) 循环逐项累加（对齐竞品 CPU 累加粒度）。atom_virial 是 scatter 写，先在 UB float32 buffer 按 idz 列累加，帧末一次性转 T 写回 GM；virial 用寄存器 float 累加直接写 GM。

```cpp
int32_t idz = threadIdx.x;
if (idz >= static_cast<int32_t>(VIRIAL_ELEM_NUM)) { return; }
int32_t dd1 = idz % 3; int32_t dd0 = idz / 3;
for (int32_t i = 0; i < nloc; i++) {
    for (int32_t j = 0; j < nnei; j++) {
        int32_t jIdx = nlistGm[nlistBase + iNlist + j];
        if (jIdx < 0 || jIdx >= nall) { continue; }
#pragma unroll
        for (int32_t mu = 0; mu < DESCRPT_PER_NEI; mu++) {
            float tmp = ToFloat32<T>(netDerivGm[netOff + mu]) * rijVal * ToFloat32<T>(inDerivGm[inOff + mu * 3 + dd0]);
            avBuf[jIdx * VIRIAL_ELEM_NUM + idz] += tmp;   // UB fp32 累加
            virialSum += tmp;                             // 寄存器 fp32 累加
        }
    }
}
WritebackAvBuf<T>(nall, idz, avBase, avBuf, atomVirialGm);   // 一次性量化写回
```

- 来源：`math/prod_virial_se_a/op_kernel/arch35/prod_virial_se_a_simt.h`

#### K3. 每线程一个输出元素的"重算前缀"扫描（免同步）

- 适用算子：cumulative_logsumexp
- 策略说明：把输出逐元素分配给线程，每个线程从扫描起点**重新顺序累加 count 项**得到自己的前缀值。不做分段扫描+前缀传播，因为 LogAddExp 结合算子代价低、重算消除了任何跨线程同步；exclusive/reverse 只需调整 `count/start/step` 三个量。累加以 float 进行，初始 `-inf`。

```cpp
int64_t count = exclusive != 0 ? axisIdx : axisIdx + 1;
int64_t start = 0, step = 1;
if (reverse != 0) { start = axisNum - 1; step = -1; count = exclusive != 0 ? (axisNum - 1 - axisIdx) : (axisNum - axisIdx); }
float acc = negInf;
for (int64_t i = 0; i < count; ++i) {
    float cur = LoadAsFloat<T>(x, base + (start + step * i) * innerNum);
    acc = LogAddExp(acc, cur);   // max + log1p(exp(min-max))，NaN/Inf 特判
}
```

- 来源：`math/cumulative_logsumexp/op_kernel/arch35/cumulative_logsumexp_simt.h`

#### K4. 每 warp 一个输出元素，lane 分摊规约轴 + shuffle 归约；分子分母分别规约

- 适用算子：cosine_similarity
- 策略说明：每个输出元素由一个 warp 负责：32 个 lane 按 `r = laneId; r += 32` 分摊规约轴，`asc_reduce_add` 做 warp 归约。**两遍扫描**：第一遍只算 w1=Σv1²、w2=Σv2²，归约后 sqrt+eps 钳制得 norm；第二遍累加 w12=Σ(v1/norm1)(v2/norm2) 再归约。先归一化再累加避免 FLT_MAX 平方在 sqrt 前溢出。`reduceSize==1` 特判走 lane0 单线程。

```cpp
for (IdxT outIdx = blockIdx.x*numWarps + warpId; outIdx < totalOutputElements; outIdx += gridDim.x*numWarps) {
    float w12 = 0.0f, w1 = 0.0f, w2 = 0.0f;
    for (IdxT r = laneId; r < reduceSize; r += WARP_SIZE) {
        float v1 = static_cast<float>(x1[baseOffsetX1 + r * reduceStride]);
        float v2 = static_cast<float>(x2[baseOffsetX2 + r * x2ReduceStride]);
        w1 += v1 * v1; w2 += v2 * v2;
    }
    w1 = asc_reduce_add(w1); w2 = asc_reduce_add(w2);
    float norm1 = sqrtf(w1); norm1 = (norm1 > eps) ? norm1 : eps;
    float norm2 = sqrtf(w2); norm2 = (norm2 > eps) ? norm2 : eps;
    for (IdxT r = laneId; r < reduceSize; r += WARP_SIZE) {
        w12 += (static_cast<float>(x1[baseOffsetX1 + r * reduceStride]) / norm1) *
               (static_cast<float>(x2[baseOffsetX2 + r * x2ReduceStride]) / norm2);
    }
    w12 = asc_reduce_add(w12);
    if (laneId == 0) { output[outIdx] = static_cast<T>(w12); }
}
```

- 来源：`math/cosine_similarity/op_kernel/arch35/cosine_similarity_simt.h`

#### K5. 对角线索引 arithmetic + 两级归约（warp shuffle → UB 跨 warp）

- 适用算子：trace
- 策略说明：对角元地址 = `i * diagStride`（`diagStride = N+1`），线程 `i = tid; i += NumThreads` 分摊对角线。第一级用**手写 `asc_shfl_down` 循环**做 warp 归约（`asc_reduce_add` 不支持 double/bf16/complex，手写 shuffle 统一接口）；lane0 把 warp 和写入 UB warpBuf，`asc_syncthreads` 后 warp0 再归约 numWarps 个部分和。三条模板路径：float 累加（half/bf16/float）、int64 累加（整型）、complex64（实虚部当两个 float 通道）。

```cpp
__simt_callee__ __aicore__ inline float FloatManualReduce(float val)
{
    for (int32_t offset = WARP_SIZE / 2; offset > 0; offset >>= 1) { val += asc_shfl_down(val, offset); }
    return val;
}
...
float warpSum = FloatManualReduce(localSum);
if (laneId == 0) { wfBuf[warpId] = warpSum; }
asc_syncthreads();
if (warpId == 0) {
    float fs = (laneId < numWarps) ? wfBuf[laneId] : 0.0f;
    fs = FloatManualReduce(fs);
    if (laneId == 0) { WriteFloatResult<T, OutT>(fs, output); }
}
```

- 来源：`math/trace/op_kernel/arch35/trace_simt.h`

#### K6. 每线程一个 (p,r) 输出对 + 线程内 M 维串行规约（cdist SIMT）

- 适用算子：cdist（SIMT 路径）
- 策略说明：输出 B×P×R 展平，线程领取输出元素，用 magic-number 除法分解出 (B,P,R) 坐标，线程内 for 循环 M 维做 p-范数累加后直接写出。规约轴 M 完全线程私有，零同步。

```cpp
for(uint64_t index = threadIdx.x; index < count; index += blockDim.x) {
    uint64_t outputIdx = outputBasicIndex + index;
    uint64_t Bidx = Simt::UintDiv(outputIdx, m0, s0);   // ÷(P*R)
    uint64_t Pidx = Simt::UintDiv(outputIdx - Bidx*P*R, m1, s1);
    uint64_t Ridx = outputIdx - Bidx*P*R - Pidx*R;
    float sumNum = 0;
    for(int64_t i = 0; i < M; i++) {
        float absNum = x1[Bidx*P*M + Pidx*M + i] - x2[Bidx*R*M + Ridx*M + i];
        sumNum += absNum * absNum;
    }
    yGmAddr[outputIdx] = sqrtf(sumNum);
}
```

- 来源：`math/cdist/op_kernel/arch35/cdist_simt.h`

#### K7. p 值特化的五个 kernel 分发 + 原子规约特例

- 适用算子：cdist
- 策略说明：p=0/1/2/inf/其他 五个独立 `__simt_vf__` kernel 避免通用路径 pow/exp/log 开销。p=0 时 `asc_atomic_add`（计数语义），p=inf 时 `asc_atomic_max`。一般 p 用 `logf/expf` 代替 powf，且当 `logf(absNum)*p < -87`（float exp 下溢界）时拆成 `0.5*pow` 平方两次再累加，防下溢丢精度。

```cpp
// p==0: asc_atomic_add(yGmAddr + outputIdx, min(ceil(|d|), 1));
// p==inf: asc_atomic_max(yGmAddr + outputIdx, |d|);
// 一般 p：
float powNum = logf(absNum) * p;
if(powNum < LN_MIN_FLOAT) {           // -87.0f
    powNum *= 0.5f;
    float temp = expf(powNum);
    sumNum += temp * temp;
} else { sumNum += expf(powNum); }
```

- 来源：`math/cdist/op_kernel/arch35/cdist_simt.h`

#### K8. 每线程一条扫描线的串行 cummin（SIMT 模板路径）

- 适用算子：cummin（COMPUTE_SIMT 路径）
- 策略说明：N<128 时矢量路径对齐搬运不划算。SIMT kernel 中线程 `blockId` 映射到 (m, n)，沿 R 维纯串行推进 running min（扫描轴顺序依赖的直接表达），边算边写 y 与 argmin；`blockId += threadNum` 网格步进处理下一条扫描线。

```cpp
int64_t blockId = threadIdx.x;
int64_t idx = (blockId / N) * RN + (blockId % N);
while (idx < count) {
    X minVal = xGm[idx];
    ARGMIN minIdx = static_cast<ARGMIN>(0);
    for (int64_t j = 1; j < R; ++j) {          // 扫描轴串行
        const X curr_val = xGm[idx + j * N];
        bool is_not_smaller = (minVal < curr_val);
        minVal = is_not_smaller ? minVal : curr_val;
        minIdx = is_not_smaller ? minIdx : static_cast<ARGMIN>(j);
        yGm[idx + j * N] = minVal; argminGm[idx + j * N] = minIdx;
    }
    blockId += threadNum;
    idx = (blockId / N) * RN + (blockId % N);
}
```

- 来源：`math/cummin/op_kernel/arch35/cummin.h`

#### K9. 矢量路径的寄存器级扫描（RegTensor Compare+Select，跨 UB tile 传递 running min）

- 适用算子：cummin（RN_FULLY_LOAD / N_FULLY_LOAD / N_NOT_FULLY_LOAD 矢量路径）
- 策略说明：矢量路径把 running min 与 argmin 驻留 `RegTensor`，用 `Reg::Compare<LT>` 产 mask、`Reg::Select` 同时更新 min 值与 argmin（`Duplicate(dupReg, j)` 把当前行号作为候选索引），一步完成"比较-选值-选索引"。扫描轴 R 分多段时，tmp buffer 保存上一段的 running min/idx，实现"分段扫描 + 前缀传播"。

```cpp
for (int j = 0; j < computeTimes; j++) {
    AscendC::Reg::Duplicate(dupReg, j + duplicate);            // 候选 argmin = 行号
    AscendC::Reg::Compare<X, CMPMODE::LT>(cmpReg, xReg, yReg, yMaskReg);
    AscendC::Reg::Select(xReg, xReg, yReg, cmpReg);            // running min
    AscendC::Reg::Select(argminReg, argminReg, dupReg, cmpReg);// running argmin
    AscendC::Reg::DataCopy(yAddr + yOffset, xReg, yMaskReg);   // 原位写回前缀 min
}
```

- 来源：`math/cummin/op_kernel/arch35/cummin.h`

#### K10. 每线程一个 3 向量，广播坐标三分量完全展开计算（cross）

- 适用算子：cross
- 策略说明：叉积规约维恒为 3，kernel 不做循环：线程领到向量序号 v 后，用预计算 mergedStride 逐维取模分解出坐标，累加 x1/x2/y 三组基址（广播维 stride=0 自动生效），取三个元素完全展开计算 a×b 直接写三次。

```cpp
for (int d = 0; d < dimNum; d++) {
    int32_t c = v / para.ms[d]; v -= c * para.ms[d];
    x1b += c * para.x1s[d]; x2b += c * para.x2s[d]; yb += c * para.ys[d];
}
float a0 = x1Gm[x1b], a1 = x1Gm[x1b + sx1], a2 = x1Gm[x1b + 2*sx1];
float b0 = x2Gm[x2b], b1 = x2Gm[x2b + sx2], b2 = x2Gm[x2b + 2*sx2];
yGm[yb] = a1*b2 - a2*b1; yGm[yb + sy] = a2*b0 - a0*b2; yGm[yb + 2*sy] = a0*b1 - a1*b0;
```

- 来源：`math/cross/op_kernel/arch35/cross.h`

#### K11. 类型提升 traits（AccType/OutputType）与加载转换 helper

- 适用算子：trace（最完整）、cumulative_logsumexp、prod_virial_se_a
- 策略说明：规约累加精度与输入/输出精度解耦：trace 用两组模板 traits——`AccType`（half/bf16→float，所有整型/bool→int64）决定累加器，`OutputType`（整型一律 int64 输出）决定输出类型；配合 `LoadAsFloat/LoadAsInt64` helper 在 `if constexpr` 下零开销分发。一份 kernel 模板覆盖 12 种 dtype。

```cpp
template <typename T> struct AccType { using type = T; };
template <> struct AccType<half> { using type = float; };
template <> struct AccType<int8_t> { using type = int64_t; };
template <> struct AccType<bool> { using type = int64_t; };
```

- 来源：`math/trace/op_kernel/arch35/trace_simt.h`

#### K12. 线程数按寄存器压力/索引位宽分档

- 适用算子：trace（512/256）、cosine_similarity（1024/512）、cross（1024/512）、prod_virial_se_a（32 中对齐 9 有效）、cummin SIMT（2048）
- 策略说明：64 位索引或 int64 累加器使每线程寄存器用量翻倍，`__launch_bounds__` 相应减半以避免寄存器溢出；低压路径提升线程数增加并行度。prod_virial 更极端：算法本身只有 9 个并行分量，仍按 warp 对齐到 32 线程、无效线程立即 return。

```cpp
constexpr uint32_t THREAD_NUM_HIGH = 512;  // float/complex paths (low register pressure)
constexpr uint32_t THREAD_NUM_LOW = 256;   // int64 path (high register pressure)
static constexpr uint32_t THREAD_NUM_32 = 1024;
static constexpr uint32_t THREAD_NUM_64 = 512;   // R006: 按索引位宽
```

- 来源：`math/trace/op_kernel/arch35/trace_simt.h`、`math/cosine_similarity/op_kernel/arch35/cosine_similarity_simt.h`

#### K13. HL-Reduce 路径——Broadcast + ReduceRepeat 的 M 轴矢量归约（SIMT 对照设计）

- 适用算子：cdist（KERNEL_MODE=3，M∈[2,256] 且矢量胜）
- 策略说明：与 SIMT 的"线程内串行 M 循环"形成对照：x1/x2 各行只搬入 UB 一次，p×r 网格在 UB 内复用（GM 流量 ÷(P·R)）；逐 (b,p) 用 `Broadcast` 把 `x1[b,p,:M]` 扩成 `[rSize, M]` 平面，`Sub/Abs/Mul` 后 `ReduceRepeat<SUM>` 一次归约出 rSize 个距离。M 分段时部分和以 fp32 累加，末段再归一化。

```cpp
// 逐 (b,p): Broadcast x1[b,p,:M] [1,M]->[rSize,M]；
// Sub(diff, x1exp, x2[b], rSize*MAlign)；Abs/Mul（按 p）；
// ReduceRepeat<SUM>(acc[b,p,0:rSize], diff, mask=mSize, repeat=rSize, ...)
// M-split 时把段和累加到 yFp32_（p!=inf: Add; p==inf: Max），末段再归一。
```

- 来源：`math/cdist/op_kernel/arch35/cdist_reduce_hl.h`

---
## 三、排序类（Sort/TopK）

> 范围：`math/{sort, sort_with_index, top_k_v2, kth_value}` + `experimental/math/radix_sort`。
> 共性背景：host 侧统一为 SIMT kernel 预留 32KB UB（`SIMT_UB`/`CONST_SIMT_SPACE`）；kernel 通过 `asc_vf_call` 发起 SIMT 并行，`asc_syncthreads()` 块内同步，`SyncAll()` 跨核同步，`asc_atomic_add` 全局原子。

### Tiling 策略

#### T1. 分层 Schedule 路由树（按轴大小/dtype/布局逐级 Try 选择模板）

- 适用算子：sort
- 策略说明：Tiling 不直接计算，而是按优先级依次尝试各候选模板：`小轴(TWO_STAGE/INSERTION) → 非尾轴小轴免转置 → 单核归并/多核归并 → 单核基数 → 核内归并 → 默认多核基数`。每个 Try 内部做支持性检查（dtype、轴长阈值、UB 估算），命中即写入 schId（0~11），最终 `GET_TPL_TILING_KEY(schId, isInt32, isDescend)` 选择 kernel 二进制。非尾轴若所有免转置方案都不命中，直接报错。

```cpp
if (TrySmallAxis(context, sortTileInfo, schId)) { return ge::GRAPH_SUCCESS; }
if (TryNonLastSmallAxis(context, sortTileInfo, schId)) { return ge::GRAPH_SUCCESS; }
if (sortTileInfo.isNonLastAxis) { OP_LOGE_FOR_INVALID_VALUE_WITH_REASON(...); return ge::GRAPH_FAILED; }
if (TryMerge(context, sortTileInfo, schId) || TryRadixOneCore(context, sortTileInfo, schId) ||
    TryMergeIntraCore(context, sortTileInfo, schId)) { return ge::GRAPH_SUCCESS; }
schId = SORT_SCHID_2;   // 默认多核基数
```

- 来源：`math/sort/op_host/arch35/sort_tiling_arch35.cpp`

#### T2. 小轴双路选择：Two-Stage 优先、Insertion 兜底（dtype 规则表 + 满核段数阈值）

- 适用算子：sort、kth_value
- 策略说明：轴长 ≤ `SMALL_AXIS_THRESHOLD` 时进入小轴路由。每种 dtype 有一张 `SmallAxisRule` 规则表（`twoStageMaxN`、`insertionMaxN` 及分段阈值），先尝试两阶段方案（SIMD Sort API 排序 + SIMT 还原行序），要求轴长不超 `twoStageMaxN` 且每核分到的段数达到该轴长档位的最小段数（保证多核利用率）；不满足再退化到 SIMT 插入排序。

```cpp
const SmallAxisRule* rule = FindSmallAxisRule(info.dataType);
if (rule->twoStageMaxN > 0U && axisLen <= rule->twoStageMaxN && axisLen <= SMALL_AXIS_THRESHOLD &&
    fullCoreSegs >= LookupMinSegs(rule->twoStageTiers, axisLen) &&
    EstimateSmallAxisTwoStageBatching(...)) { plan.kind = SmallAxisRouteKind::TWO_STAGE; return true; }
if (axisLen > rule->insertionMaxN || fullCoreSegs < LookupMinSegs(rule->insertionTiers, axisLen)) { return false; }
```

- 来源：`math/sort/op_host/arch35/sort_tiling_common.cpp`

#### T3. 两阶段小轴 batch 搜索：UB 约束 + uint16 key 不溢出约束 + 空闲槽最小化

- 适用算子：sort、kth_value
- 策略说明：两阶段方案每批处理 `batchSize × axisLen` 个元素。batch 上限三重约束：(1) UB 容量；(2) 非 rank-inverse 路径的 stage-2 使用 uint16 排序 key，`batch² × axisLen ≤ UINT16_MAX`（开平方+微调求解）；(3) 从最大候选往下搜索，在每核批次数相同的候选中选空闲槽最少者。

```cpp
uint32_t MaxTwoStageU16SafeBatch(uint32_t axisLen)
{
    uint32_t maxBatch = static_cast<uint32_t>(std::sqrt(static_cast<double>(UINT16_MAX) / axisLen));
    while (static_cast<uint64_t>(maxBatch) * maxBatch * axisLen > UINT16_MAX) { --maxBatch; }
    while (static_cast<uint64_t>(maxBatch + 1U) * (maxBatch + 1U) * axisLen <= UINT16_MAX) { ++maxBatch; }
    return maxBatch;
}
```

- 来源：`math/sort/op_host/arch35/sort_tiling_common.cpp`

#### T4. 非尾轴小轴免转置：innerChunk 候选搜索（dtype 分组 2 幂候选表，优先大 chunk/多核）

- 适用算子：sort、kth_value、top_k_v2
- 策略说明：非尾轴排序把相邻 `innerChunk` 个 inner 位置批成一组排序行，避免转置整个张量。Tiling 按 dtype 字节数给出递减 2 幂候选表（8B 类型 {4,2,1}，1B 类型 {32,16,8,4,2,1}），逐个评估对齐后 UB 峰值，优先选「激活核数最多、其次 chunk 最大」者。

```cpp
static constexpr uint32_t kChunkCandidates[][kMaxChunkCandidates] = {
    {4, 2, 1, 0, 0, 0},      // 8-byte types
    {8, 4, 2, 1, 0, 0},      // 4-byte types
    {16, 8, 4, 2, 1, 0},     // 2-byte types
    {32, 16, 8, 4, 2, 1},    // 1-byte types
};
bool betterCoreUse = cur.activeCore > best.activeCore;
bool sameCoreUseLargerChunk = cur.activeCore == best.activeCore && cur.innerChunk > best.innerChunk;
if (betterCoreUse || sameCoreUseLargerChunk) { best = cur; }
```

- 来源：`math/sort/op_host/arch35/sort_tiling_common.cpp`

#### T5. 非尾轴 UB 布局：bank 旋转 padding + 排序/索引双阶段峰值复用

- 适用算子：sort（sch 9/10）
- 策略说明：(1) 当归并行跨距是 4 个 32B block 的整数倍时会反复命中同一 bank 组，加一个 block 的 padding 旋转行起始地址；(2) 利用"输入/value/tmp 区在 value MTE3 拷出后即死亡"的生命周期特征，把 sortedIndex 放在分配尾部、前缀复用为转置输出索引，取两阶段峰值最大值。

```cpp
// A merge row stride spanning a multiple of four 32-byte blocks repeatedly addresses the same bank groups.
if (rowBytes % (4U * blockBytes) == 0U) { rowBytes += blockBytes; }
// The input/value/tmp region is dead after the value MTE3 copy. Keep sortedIndex at the end of one
// allocation and reuse the prefix for the transposed output indices.
peakUb = std::max(sortPhaseUb, sortedIndexBytes + outputIndexBytes);
```

- 来源：`math/sort/op_host/arch35/sort_tiling_arch35.cpp`

#### T6. 多核 radix 的 tileData 计算与 B/H 二维分核调整

- 适用算子：sort、kth_value、sort_with_index、top_k_v2（同源实现）
- 策略说明：大轴基数排序先按 UB 反解每 tile 元素数：`tileData = (usableUb - ubExtra) / tileFactor`，向 256（BIN_NUM）对齐；再用 Sort API 的 tmp UB 查询反复递减直至容纳。随后按 B（行数）/H（tile 数）分四种形态调整分核：单行单 tile 均分到全部核；单行多 tile 按 tile 数分核；多行单 tile 时 H 方向补核；多行多 tile 时优先 H 分核、剩余核给 B。

```cpp
tileData = ((usableUb - ubExtra) / tileFactor) / BIN_NUM * BIN_NUM;
while (tmpUbSize > remainUb) {
    if (tileData <= BIN_NUM) { return false; }
    tileData -= BIN_NUM;
    if (!QuerySortTmpSizeRadix(ge::DT_UINT8, tileData, tmpUbSize)) { return false; }
}
info.unsortedDimParallel = info.maxCoreNum / lastDimTileNum;  // H 方向补核
```

- 来源：`math/sort/op_host/arch35/sort_tiling_common.cpp`

#### T7. 多核 radix workspace 六段划分与清零任务分核

- 适用算子：sort、sort_with_index、top_k_v2
- 策略说明：workspace 六段：全局 exclusive bin 前缀、全局直方图（带状态位）、排序索引双缓冲、每 tile 直方图/前缀、抽取的 radix 字节（xB8）、排序值双缓冲，各段 32B 对齐。两块 GM 直方图区域的清零工作按核数均分（keyParams 记录每核清零大小），kernel 启动时先清零再 `SyncAll()`。

```cpp
workspaceSize = excusiveBins + globalHist + sortedIdx + histTile + xB8 + sortedValue;
```

- 来源：`math/sort/op_host/arch35/sort_tiling_common.cpp`

#### T8. SIMT UB 预留（所有 SIMT 模板的统一约定）

- 适用算子：sort、kth_value、top_k_v2、sort_with_index
- 策略说明：SIMT kernel 的运行时栈/寄存器溢出等需要固定 32KB UB scratch，所有模板在计算可用 UB 前先扣除 `SIMT_UB`；平台 UB ≤ SIMT_UB 直接判失败。这是 SIMT+SIMD 混合模板共存于同一 UB 的前提。

```cpp
uint64_t ComputeUbAfterSimtReserve(uint32_t ubSize)
{
    if (usableUb <= static_cast<uint64_t>(SIMT_UB)) { return 0; }
    return usableUb - SIMT_UB;   // reserve 32KB for SIMT kernel scratch
}
```

- 来源：`math/sort/op_host/arch35/sort_tiling_common.cpp`

#### T9. Merge sort 单核多行 tiling（TILE_DATA_NUM=4096 元素预算）

- 适用算子：sort（sch 0/8）、kth_value
- 策略说明：中小轴采用单核归并：以 4096 元素为 UB 预算反推每核行数，行数多于一核一轮能装的部分按 `sortLoopTimes` 循环；轴长大于 `ONE_CORE_DATA_SIZE` 时关双缓冲。

```cpp
constexpr uint32_t TILE_DATA_NUM = 4096;
ComputeMergeSortPlan(info.lastAxis, info.unsortedDim, info.blockUbSize, TILE_DATA_NUM, info.maxCoreNum, plan);
info.keyParams4 = info.lastAxis > ONE_CORE_DATA_SIZE ? 1 : DOUBLE_BUFFER_NUM;
```

- 来源：`math/sort/op_host/arch35/sort_tiling_common.cpp`

#### T10. TopK 模式选择树（7 级 if-else 链）

- 适用算子：top_k_v2
- 策略说明：尾轴场景按序匹配：小轴归并优化 → 单 block（整轴装 UB）→ fp32 归并 → 单核基数 → 核间优化（每核局部 TopK 再集中二次 TopK，要求 `k × lastDimTileNum ≤ tileData`）→ 自有核间 radix（轴长 < 1000 万）→ 兜底 `SortAndTopK`（先全排序再取前 k，超大轴）。

```cpp
if (IsSmallSizeMergeSortMode(dataType, lastAxisNum)) { TileModeSmallSizeOptim(...); }
else if (IsSingleBlockMode(...)) { TileModeSmallSize(...); }
else if (IsFp32MergeSortMode(...)) { return TileModeFp32MergeSort(...); }
else if (IsSingleCoreMode(...)) { TileModeSingleCore(...); }
else if (IsMultiCoreOptimMode(...)) { TileMultiCoreOptimSize(...); }
else if (IsTopkRadixMoreCoreMode(...)) { TileTopkMoreCoreMode(...); }
else { return TileModeSortAndTopK(...); }  // sortAndTopk模板处理超大尾轴
```

- 来源：`math/top_k_v2/op_host/arch35/top_k_v2_tiling_arch35.cpp`

#### T11. kth_value 路由树：radix select 缩桶（不排序）

- 适用算子：kth_value
- 策略说明：在 sort 路由基础上针对"只要第 k 个"语义增加专属路径：轴长 ≤32 且 k≤8 时用 SIMT 短轴部分选择；中大轴优先 `TryRadixSelect`（MSB→LSB 每轮直方图缩桶，不做全排序），其后才是归并/单核基数/多核基数。

```cpp
if (TrySmallAxisShortRankSelect(info, ...)) { ... }
if (TrySmallAxis(context, info, ...)) { ... }
if (TryMerge(...) || TryRadixOneCore(...) || TryRadixSelect(...) || TryMergeIntraCore(...)) { ... }
schId = KTH_VALUE_SCHID_RADIX_MORE_CORE;
```

- 来源：`math/kth_value/op_host/arch35/kth_value_tiling_arch35.cpp`

#### T12. sort_with_index：索引 dtype 因子计入 UB/Workspace 折算

- 适用算子：sort_with_index、top_k_v2（needSortWithIndex 时复用）
- 策略说明：UB 元素代价因子把索引 dtype 计入：`tileFactor = CONST_6 + dtypeSize + y2DtypeSize`；索引是否 int64 由轴长是否超 int32 决定，workspace 与清零参数按 `dtypeSizeWk = 4/8` 折算。三模式：≤ SMALL_SORT_MAX_DATA_SIZE 单核归并优化、≤ tileData single-block（SIMD Sort API 每核多行）、更大 multi-block radix。

```cpp
if (sortTileInfo.isInt32 == 0U) { ubExtra = UB_CONST_INT64; tileFactor = CONST_6 + dtypeSize + y2DtypeSize; }
else { ubExtra = UB_CONST_INT32; tileFactor = CONST_6 + dtypeSize + y2DtypeSize; }
```

- 来源：`math/sort_with_index/op_host/arch35/sort_with_index_tiling.cpp`

#### T13. 实验 radix_sort：按核数/UB 容量四选一 pathType，pass 数=字节数

- 适用算子：experimental/math/radix_sort
- 策略说明：纯 SIMT 的 device-wide LSD radix。`perCore = ceil(total/cores)`（下限 PER_CORE_MIN）反推 needCore。pathType：1=单核且元素 ≤ UB 缓冲；2=多核但每核 ≤ UB 缓冲（全局直方图）；3=单核装不下（分 tile 多 pass）；4=多核且每核装不下。64 位类型 UB 缓冲减半。pass 数 = `sizeof(T)`（每 pass 8 bit / 256 bin）。

```cpp
int64_t perCore = CeilDiv(totalElements, physicalCoreNum);
if (perCore < PER_CORE_MIN) { perCore = PER_CORE_MIN; }
int64_t needCore = CeilDiv(totalElements, perCore);
if (needCore == 1) { pathType = (totalElements <= ubSortBuf) ? 1 : 3; }
else { pathType = (perCore <= ubSortBuf) ? 2 : 4; }
```

- 来源：`experimental/math/radix_sort/op_host/arch35/radix_sort_tiling.cpp`

#### T14. 轴长=1 直通 copy 退化

- 适用算子：sort、kth_value
- 策略说明：排序轴长为 1 时结果即输入本身，走纯搬运路径：按 `ubSize / (2×(dtypeSize+idxDtypeSize))` 计算每轮搬运元素数，多核均分 loop，kernel 只做 DataCopy + 生成索引 0。

```cpp
bool IsAxisOneCopy(const SortKthTileInfo& sortTileInfo) { return sortTileInfo.lastAxis == 1; }
uint64_t copyElemsPerLoop64 = ubSize / (2 * (dtypeSize + idxDtypeSize));
```

- 来源：`math/sort/op_host/arch35/sort_tiling_arch35.cpp`

### Kernel 策略

#### K1. 两阶段小轴排序：SIMD Sort API 全局排序 + SIMT rank-inverse 行序还原

- 适用算子：sort、kth_value（sch 6/11）
- 策略说明：把 `batchSize` 条短行拼成扁平数组，阶段 1 用 SIMD 高阶 Sort API（RADIX_SORT）一次性排序得到全局有序值与原始扁平位置；阶段 2 不再排序，用 SIMT kernel 建立 rank 逆映射 `rankInverse[flatIdx]=rank`，再统计"同段内 rank 更小者的个数"得到段内落点，直接散射出每行有序结果。内层统计循环 8 路展开隐藏访存延迟。

```cpp
for (uint32_t rank = threadIdx.x; rank < totalElems; rank += TWO_STAGE_THREAD_NUM) {
    rankInversePtr[stage1OrderPtr[rank]] = rank;
}
asc_syncthreads();
for (uint32_t flat = threadIdx.x; flat < totalElems; flat += TWO_STAGE_THREAD_NUM) {
    uint32_t segId = flatIdx / segmentLen;
    uint32_t rank = rankInversePtr[flatIdx];
    uint32_t pos = 0;
    for (; lane + 7U < segmentLen; lane += 8U) {   // 8 路展开
        pos0 += (rankInversePtr[scanBase] < rank) ? 1U : 0U; ... // pos1..pos7
    }
    finalValuePtr[segBase + pos] = stage1ValuePtr[rank];
    finalIdxPtr[segBase + pos] = static_cast<OutIdxT>(laneId);
}
```

- 来源：`math/sort/op_kernel/arch35/common/small_axis_two_stage_base.h`

#### K2. 两阶段备选：打包 uint16 key 二次 radix 排序 + Gather 还原

- 适用算子：sort、kth_value（轴长超过 rank-inverse 阈值）
- 策略说明：阶段 2 改用"排序换计数"：SIMT 打包 `key = segId × totalElems + rank`（uint16），同时把 stage1Order 改写为行内 laneId；再用一次 uint16 Sort API 排序把同段 rank 聚到一起；最后用 `Muls + Gather` 按排序后置换收集值与索引。

```cpp
stage2KeyPtr[rank] = static_cast<uint16_t>(segId * totalElems + rank);
stage1OrderPtr[rank] = laneId;
AscendC::Sort<uint16_t, false, kStage2SortConfig>(stage2KeysOut_, stage2Order_, stage2KeysIn_, tmp_, totalElems);
Muls(gatherOffsetsInt, stage2Order_.ReinterpretCast<int32_t>(), sizeof(T), totalElems);
Gather(finalValues_, stage1Values_, gatherOffsets, 0, totalElems);
```

- 来源：`math/sort/op_kernel/arch35/common/small_axis_two_stage_base.h`

#### K3. UB buffer 别名复用（生命周期驱动的零额外开销布局）

- 适用算子：sort、kth_value 小轴模板
- 策略说明：`finalValues_` 直接别名 `inputValues_`（阶段 1 后输入不再被读）；非 rank-inverse 路径中 `finalIdxBuf_` 先当 uint16 的 stage2KeysIn_ 用，`rankInverseBuf_` 先当 stage2KeysOut_、后再 reinterpret 为 uint32 gather 偏移 scratch。host 侧 UB 估算按同一别名规则计算。

```cpp
// finalValues_ intentionally aliases inputValues_. After Stage1Sort finishes, inputValues_ is no longer read.
finalValues_ = inputValues_;
stage2KeysIn_ = finalIdxBuf_.template Get<uint16_t>();
stage2KeysOut_ = rankInverseBuf_.template Get<uint16_t>();
```

- 来源：`math/sort/op_kernel/arch35/common/small_axis_two_stage_base.h`

#### K4. 非尾轴 NDDMA 转置加载 + SIMT 散射回写

- 适用算子：sort（sch 11 非尾轴两阶段）
- 策略说明：非尾轴 GM 布局是 `[axis, inner]`，排序需要 `[inner, axis]`。加载侧用 2 维 NDDMA 让 MTE2 引擎直接把跨步 GM tile 聚集成 UB 致密布局；回写侧用 1024 线程 SIMT kernel 按 `gmOffset = outerBase + axis*innerSize + innerStart + seg` 散射回原布局，省去显式转置。

```cpp
NdDmaParams<T, 2> params{loopInfo, static_cast<T>(0)};
DataCopy<T, 2, config>(this->inputValues_, inputXGm_[outerBaseOffset + innerStart], params);
...
for (uint32_t idx = threadIdx.x; idx < totalElems; idx += TWO_STAGE_THREAD_NUM) {
    uint32_t axis = idx / validSegs;
    uint32_t seg = idx - axis * validSegs;
    uint32_t ubOffset = seg * segmentLen + axis;
    uint64_t gmOffset = outerBaseOffset + axis * innerSize + innerStart + seg;
    outputValue[gmOffset] = inputValue[ubOffset];
    outputIdx[gmOffset] = inputIdx[ubOffset];
}
```

- 来源：`math/sort/op_kernel/arch35/sort_small_axis_two_stage.h`

#### K5. 非尾轴免转置排序：inner 批处理 + 寄存器 Gather 转置 + SIMT 写回

- 适用算子：sort（sch 9/10）、kth_value、top_k_v2 非尾轴模板
- 策略说明：把 `innerChunk` 个 inner 位置按列批成排序行，直接在原布局上加载 `[axisLen, innerChunk]` tile，逐 inner 位置调用 Sort API；排序后用向量寄存器 Gather（`Arange` 生成行基址 × valueAxisElems）把 `[inner, axis]` 转回 `[axis, inner]`；索引转置与最终跨步 GM 写回由 SIMT kernel 完成（`curInnerChunk==1` 时直接 SIMT 按 axis 写，跳过转置）。

```cpp
AscendC::Reg::Arange(valueIdxReg, 0);
AscendC::Reg::Muls(valueIdxReg, valueIdxReg, this->valueAxisElems_, valueIdxMask);
for (uint16_t axis = 0; axis < this->axisLen_; ++axis) {
    AscendC::Reg::Gather(valueReg, sortedValueAddr + axis, valueIdxReg, valueMask);
    AscendC::Reg::StoreAlign(outputValueAddr + axis * this->inputRowElems_, valueReg, valueMask);
}
```

- 来源：`math/sort/op_kernel/arch35/sort_non_last_small_axis.h`

#### K6. 多核 radix LSD 主流程：pass 数 = 字节数，twiddle 编码映射到无符号序

- 适用算子：sort、kth_value、sort_with_index、top_k_v2（多核 radix 系）
- 策略说明：LSD 每 pass 处理 8 bit（256 bin），pass 数 = `sizeof(T1)`。有符号/浮点类型先做 twiddle 编码转成可按位比较的无符号 key（int32 翻符号位、fp32 按符号选择 XOR 掩码、降序再按位取反），排序结束后反映射。值与索引各维护一份 GM 双缓冲，每 pass 交换。

```cpp
for (uint32_t round = 0; round < static_cast<uint32_t>(sizeof(T1)); round++) {
    this->GetGlobalExcusiveSum(round, sortLoopRound, inputXGm);
    SyncAll();
    this->ComputeOnePass(round, sortLoopRound, inputXGm);
    SyncAll();
}
if constexpr (IsSameType<int32_t, T1>::value) { TwiddleInB32<T1, UT, isDescend>(...); }
else if constexpr (IsSameType<float, T1>::value) { TwiddleInFp32<T1, UT, isDescend>(...); }
```

- 来源：`math/sort/op_kernel/arch35/common/radix_more_core_base.h`

#### K7. SIMD 直方图指令：FREQUENCY + ACCUMULATE 一次扫描双产出

- 适用算子：sort、kth_value、top_k_v2（多核 radix 系）
- 策略说明：每 pass 的"直方图统计 + 前缀和"用硬件向量指令完成：逐向量把 key 右移出当前 radix 字节、DeInterleave 压缩成 uint8 流（同时存到 xB8 workspace 供散射复用），再对同一字节流分别发射 `Histograms<FREQUENCY>`（得 hist）与 `Histograms<ACCUMULATE>`（得 inclusive 累加 chist）；`excusive = chist - hist` 即段内 exclusive 前缀，逐级 widen（u16→u32→u64）累加到块级 bin 总计。

```cpp
Reg::Histograms<uint8_t, uint16_t, BIN0, FREQUENCY>(hist0, deInter0B8, histMask);
Reg::Histograms<uint8_t, uint16_t, BIN0, ACCUMULATE>(chist0, deInter0B8, histMask);
Reg::Sub(excusiveSumZero, chist0, hist0, maskB16);
```

- 来源：`math/sort/op_kernel/arch35/common/radix_more_core_base.h`

#### K8. 跨 tile 软同步 lookback：状态位内嵌直方图高 2 bit

- 适用算子：sort、kth_value、sort_with_index、top_k_v2（多核 radix 系）
- 策略说明：一行被切成多个 tile 由不同核处理时，跨 tile 前缀和用 decoupled lookback 实现：每个 tile 把本地直方图加状态位（高 2 bit：0 未就绪/1 aggregate-ready/2 prefix-ready）发布到 GM；后续 tile 轮询前驱状态，aggregate-ready 则累加继续向前看，prefix-ready 则累加后停止；本 tile 得出前缀后打 prefix-ready 再发布。

```cpp
// Soft synchronization state is packed in the highest two bits of each bin value:
//   0: not initialized, retry   1: aggregate ready   2: prefix ready
for (int i = tileId - 1; i >= 0; --i) {
    while (true) {
        CopyGlobalDataIn<T3>(allTileHistBuffer[unSortIdOffset], xLocal, histTileOffset, RADIX_SORT_NUM);
        if (aggReadyCountScalar == RADIX_SORT_NUM) { mode = AGGREGATE_READY_FLAG; break; }
        if (PrefixReadyCountScalar == RADIX_SORT_NUM) { mode = PREFIX_READY_FLAG; break; }
    }
    Reg::And(nowTileHistVal, nowTileHistVal, histMask, predicateDefault);   // Strip state bits
    Reg::Add(nowTileHistVal, nowTileHistVal, prevTileHistVal, predicateDefault);
    if (mode == PREFIX_READY_FLAG) { break; }
}
```

- 来源：`math/sort/op_kernel/arch35/common/radix_more_core_base.h`

#### K9. SIMT 按 key 散射回写：per-key 基址 + 段内 rank

- 适用算子：sort、sort_with_index、top_k_v2（多核 radix 系）
- 策略说明：重排阶段分两段 SIMT 循环。第一段 256 线程为每个 radix key 计算本 tile 的 GM 起始位置：`finalpos = 全局key前缀 + lookback前缀 - 本tile该key计数 - 本tile该key内exclusive`；同步后第二段每线程处理若干元素，按 8bit 排序结果取 `blockDataInGlobalPos[key] + i` 得最终 GM 位置，值与索引一起散射。

```cpp
for (int i = threadIdx.x; i < RADIX_SORT_NUM; i += THREAD_DIM_NUM) {
    T3 finalpos = excusiveBinsGmAddr[unSortIdOffset + i] + blockHistCumsumVal - blockHistVal - blockExcusiveSumVal;
    blockDataInGlobalPosAddr[i] = finalpos;
}
asc_syncthreads();
for (int i = threadIdx.x; i < cureTileSize; i += THREAD_DIM_NUM) {
    T3 dataFinalGlobalPos = blockDataInGlobalPosAddr[sortedValueLocalAddr[i]] + i;
    inputXDoubleBufferAddr[dataFinalGlobalPos + ...] = xInputValueLocalAddr[localDataIndex];
    indexDoubleBufferGmAddr[dataFinalGlobalPos + ...] = static_cast<IdxT>(dataInitIndex);
}
```

- 来源：`math/sort/op_kernel/arch35/common/radix_more_core_base.h`

#### K10. 全局直方图聚合：int32 用 MTE 原子加，int64 用 SIMT 原子加

- 适用算子：sort、kth_value（多核 radix 系）
- 策略说明：计数类型为 uint32 时直接 `SetAtomicAdd<int32_t>() + DataCopyPad + SetAtomicNone()` 走 MTE 原子通路；计数类型为 int64 时硬件原子通路不支持，改由 SIMT kernel 用 `asc_atomic_add` 逐 bin 原子加。

```cpp
if constexpr (sizeof(T3) == sizeof(uint32_t)) {
    SetAtomicAdd<int32_t>();
    DataCopyPad(this->excusiveBinsGmWk_[excusiveBinOffset], blockExcusiveUb, this->copyParams);
    SetAtomicNone();
} else {
    // int64 counters can exceed the int32 atomic path, so use the SIMT int64 atomic-add helper.
    asc_vf_call<SimtGlobalOffset<T3>>(dim3(RADIX_SORT_NUM), ...);  // asc_atomic_add(...)
}
```

- 来源：`math/sort/op_kernel/arch35/common/radix_more_core_base.h`

#### K11. 单核一行 Sort API：int64 索引先 uint32 排序再 Cast

- 适用算子：sort（sch 1）、kth_value
- 策略说明：轴长能装进 UB 且计数在 int32 范围时一核处理整行。索引输出为 int64 时，Sort API 先产出 uint32 索引放 UB 后半，再 `Cast` 到 int64 写前半，tiling 侧 `keyParams2=halfNum` 记录偏移。

```cpp
if constexpr (sizeof(T2) == sizeof(int64_t)) {
    LocalTensor<uint32_t> sortIdxUbHalf = sortIdxUb[halfIndex_];
    AscendC::Sort<T1, false, sortConfigMuti>(sortValueUb, sortIdxUbHalf, xLocal, tmpUb, numTileData_);
    AscendC::Cast(sortIdxUb.ReinterpretCast<int64_t>(), sortIdxUbHalf.ReinterpretCast<int32_t>(), CAST_NONE, numTileData_);
}
```

- 来源：`math/sort/op_kernel/arch35/sort_radix_sort_one_core.h`

#### K12. 小轴 SIMT 插入排序（一线程一段，O(n²) 换零同步）

- 适用算子：sort、kth_value（sch 5）
- 策略说明：轴长很小且段数足够多时，每线程独立对一段做插入排序，完全无线程间同步与 SIMD 调用；bf16 先 Cast 到 fp32 再比较。非尾轴场景用 SIMT gather 把 `[axis, inner]` 收成 `[inner, axis]` 排序主序。

```cpp
for (int32_t seg = threadIdx.x; seg < validSegs; seg += INSERTION_THREAD_NUM) {
    for (uint32_t elem = 1; elem < segmentLen; ++elem) {
        T keyValue = valueBase[valueBaseOffset + elem];
        uint32_t insertPos = elem;
        while (insertPos > 0) {
            bool needMove = IsDescend ? (prevValue < keyValue) : (prevValue > keyValue);
            if (!needMove) { break; }
            valueBase[valueBaseOffset + insertPos] = prevValue; --insertPos;
        }
        valueBase[valueBaseOffset + insertPos] = keyValue;
    }
}
```

- 来源：`math/sort/op_kernel/arch35/common/small_axis_insertion_base.h`

#### K13. Merge intra-core 三阶段：UB 块排序 → GM ping-pong 多路归并 → 抽取输出

- 适用算子：sort、kth_value（sch 4）
- 策略说明：一核处理整行超大轴 fp32 排序。Phase 1 把行切成 blockSortSize 块，每块 UB 内 `Concat+Sort` 成 sort-struct 写入 per-core GM cache；Phase 2 用 `MrgSort` 做最多 4 路增量归并，GM ping-pong 多级合并；Phase 3 由派生类决定输出语义（sort 输出整行，kth_value 只抽取第 k 个）。升序浮点先翻符号位（`Adds 0x80000000`）使位序=数值序，输出前翻回。

```cpp
static_cast<Derived*>(this)->SortSingleBatchInUb(this->inputXGm_, batchIdx * this->sortAxisNum_);
PhaseBarrierAndReset();
uint32_t resultRegion = this->MergeSingleBatch();
static_cast<Derived*>(this)->ExtractAndCopyOut(batchIdx, resultRegion);
// Adds(castTensor, castTensor, 0x80000000, alignSize); // Flip sign bit for ascending float order
```

- 来源：`math/sort/op_kernel/arch35/common/merge_intra_core_base.h`

#### K14. Merge more-core：每核排序一段 + 多级 4 路合并树

- 适用算子：sort、kth_value（sch 3）
- 策略说明：一行按 `ONE_CORE_DATA_SIZE` 切成多段每核排序一段写 workspace；`SyncAll` 后每轮把 4 路有序段归并为 1 路，listNum 按 4 倍收缩，workspace 双缓冲交替，直到剩 ≤4 路后一次性归并输出。

```cpp
while (this->listNum_ > MERGE_LIST_MAX_NUM) {
    this->workspaceInput_ = this->workspaceGm_[this->workSpaceFlag_];
    this->workspaceOutput_ = this->workspaceGm_[1 - this->workSpaceFlag_];
    this->SortInMultiCore();
    this->listNum_ = Ops::Base::CeilDiv(this->listNum_, MERGE_LIST_MAX_NUM);
    this->currentElements_ = this->currentElements_ * MERGE_LIST_MAX_NUM;
    this->workSpaceFlag_ = (this->workSpaceFlag_ + 1) % MERGE_WORKSPACE_BUFFER_NUM;
}
this->FinalSortAndCopy();
```

- 来源：`math/sort/op_kernel/arch35/common/merge_more_core_base.h`

#### K15. merge_sort_with_index：vbs 归并排序 + SIMT 按排序索引 gather 回写

- 适用算子：sort_with_index（single block）、top_k_v2
- 策略说明：int32 索引走 UB 内归并；int64 索引逐行调 Sort API 得 uint32 排序索引，再用 SIMT kernel 以 `sortedIndexLocal[i] + rowNumber×aglinNum` 为 gather 位置，把值与 int64 预置索引并发写回 GM（线程级 gather 散射，典型 SIMT 优势点）。

```cpp
for (int i = Simt::GetThreadIdx(); i < oneCoreTotalNum; i += THREAD_DIM_NUM) {
    uint32_t localSortedPosition = static_cast<uint32_t>(sortedIndexLocalAddr[i]) + rowNumber * aglinNum;
    valueGmAddr[dataFinalGlobalPos] = inputValueLocalAddr[localSortedPosition];
    indexGmAddr[dataFinalGlobalPos] = inputIndexLocalAddr[localSortedPosition];
}
```

- 来源：`math/sort_with_index/op_kernel/arch35/merge_sort_with_index.h`

#### K16. radix_sort_with_index_multi_block：继承多核 radix 基类 + 索引随行搬运

- 适用算子：sort_with_index（multi block）
- 策略说明：CRTP 继承 `SortRadixMoreCore` 复用整套直方图/lookback/散射框架，差异仅在：额外一条索引队列与索引 GM 双缓冲（int64 时 factor=2）；round 0 从输入索引 GM 读入，之后各轮索引随值一起散射——"索引跟着值走"，避免最终二次 gather。

```cpp
class RadixSortWithIndexMultiBlock : public Sort::SortRadixMoreCore<XType, IndexType, UnsignedType, XRangeType, IsDescend> {
    if (sortRound == 0) { CopyInputIndexDataIn(indexGm[xUnsortOffset], xIndexLocal, ...); }
    else { CopyInputIndexDataIn(idxDbGm_.Current()[xUnsortOffset], xIndexLocal, ...); }
};
```

- 来源：`math/sort_with_index/op_kernel/arch35/radix_sort_with_index_multi_block.h`

#### K17. kth radix select：MSB→LSB 每轮选一个桶，多核分组 reduce + 前缀广播

- 适用算子：kth_value（KTH_VALUE_SCHID_RADIX_SELECT）
- 策略说明：不排序而逐字节缩桶：每轮各核对本行分片内满足当前前缀的 key 建 256 桶直方图，组内 leader 跨核归约直方图，按 k 定位目标桶并广播新前缀，非目标桶元素被永久排除。优化：(1) retained tile——分片一 tile 装下时不重复加载；(2) active mode——匹配数 ≤512 时用 SIMT `CollectActiveIndices`（128 线程计数+单线程前缀）把活跃下标压实，后续轮次只扫活跃下标。

```cpp
// Selects one radix bucket per byte instead of scattering a fully sorted row.
CountPrefixMatchesInThread(keys, begin, end, prefixMask, prefixKey, threadCounts);
asc_syncthreads();
if (tid == 0U) {
    uint32_t accumulated = 0;
    for (uint32_t thread = 0; thread < RADIX_SELECT_FIND_THREADS; ++thread) {
        threadCounts[thread] = accumulated; accumulated += countInThread;
    }
    result[1] = accumulated <= RADIX_SELECT_ACTIVE_INDEX_CAP ? 1 : 0;
}
```

- 来源：`math/kth_value/op_kernel/arch35/kth_value_radix_select.h`

#### K18. kth 短轴 SIMT 部分排序：每线程维护 size-K 有序候选数组（插排式堆）

- 适用算子：kth_value（轴 ≤32，k ≤8）
- 策略说明：每线程独立处理一行：先把前 K 个元素初始化候选数组并插排有序（`candidateValues[K-1]` 最差=阈值），之后扫行内剩余元素，优于阈值则替换最差者并 bubble-up。第 K 小即 `candidateValues[K-1]`。`CandidateNum` 为编译期常量（1~8 递归模板分发），循环完全展开；相等时用 index 大小做确定性 tie-break。1024 线程、每行 O(n·k)，无任何同步。

```cpp
for (uint32_t col = CandidateNum; col < segmentLen; ++col) {
    T value = input[rowOffset + col];
    if (!IsShortRankSelectBetter<T, SelectLargest>(value, col, candidateValues[CandidateNum - 1U], ...)) { continue; }
    candidateValues[CandidateNum - 1U] = value;
    candidateIndices[CandidateNum - 1U] = col;
    for (uint32_t pos = CandidateNum - 1U; pos > 0U; --pos) {
        PromoteShortRankSelectCandidate<T, SelectLargest>(candidateValues, candidateIndices, pos);
    }
}
outputValue[row] = candidateValues[CandidateNum - 1U];
```

- 来源：`math/kth_value/op_kernel/arch35/kth_value_small_axis_short_rank_select.h`

#### K19. TopK radix 部分排序：边界桶二分 + 跨 tile 边界计数累计

- 适用算子：top_k_v2（single core / multi core radix）
- 策略说明：TopK 不做全排序：每 pass 只对当前 radix 字节建直方图，二分查找定位使累计计数恰好跨过 k 的边界桶；边界桶之前的元素直接入选，边界桶内的元素需跨 tile 协调——各 tile 把边界桶内计数写 GM，leader 累加出"本 tile 之前各 tile 边界桶计数和"，据此决定本 tile 还能贡献多少名额，SyncAll 后写出。

```cpp
T_INDEX nowTileBoundaryHistValue = tileCusumBuffer(boundaryBin) - tileBoundaryBinPrevCuSum;
T_INDEX prevTileTopkCumSum = tileTopkCumSum - nowTileBoundaryHistValue;
if (topkValueInput_ >= tileTopkCumSum) {
    tileTopkValue_(tileTopkValueIndex) += nowTileBoundaryHistValue;
    StoreKToGm(...);
} else if (topkValueInput_ > prevTileTopkCumSum) {
    T_INDEX stillNeedTopkValue = topkValueInput_ - prevTileTopkCumSum;
    ...
}
```

- 来源：`math/top_k_v2/op_kernel/arch35/radix_sort_top_k.h`

#### K20. TopK 核间优化：每核局部 TopK → 集中二次 TopK

- 适用算子：top_k_v2（MULT_CORE_OPTIM_MODE）
- 策略说明：满足 `k × tileNum ≤ tileData` 时，每核对自己 tile 调 TopK 高阶 API 得局部 top-k 写 GM 临时区；再由单核把 `lastDimTileNum × k` 个候选读入 UB 再调一次 TopK API 得全局结果，最后转换索引 dtype 输出。避免了大轴全排序。

```cpp
pipe.InitBuffer(topkOutIndexQueue_, 1, ROUND_UP_AGLIN(topkValueInput_ * sizeof(int32_t)));
uint32_t sortResultOffset = CeilDivMul(unsortedDimParallel_ * topkValueInput_ * lastDimTileNum_, oneBlockNum);
tempSortResultDataGm_.SetGlobalBuffer((__gm__ T*)workspace_, sortResultOffset);
```

- 来源：`math/top_k_v2/op_kernel/arch35/radix_sort_top_k_inter_core_template_optimization.h`

#### K21. SortAndTopK：先全排序再按 tile 抽取前 k（超大轴兜底）

- 适用算子：top_k_v2（SORT_AND_TOP_K_MODE）
- 策略说明：轴长超 1000 万等极端场景，直接 CRTP 继承 `SortRadixMoreCore` 把整行排序到 GM，再把前 k 个结果分 tile、多核并行从排序结果头部搬运出来；workspace 在 sort 六段基础上追加排序结果 value/index 两段。

```cpp
template <typename T1, typename T2, typename UT, typename T3, uint64_t isDescend>
class SortAndTopKMoreCore : public Sort::SortRadixMoreCore<T1, T2, UT, T3, isDescend> { ... };
```

- 来源：`math/top_k_v2/op_kernel/arch35/sort_and_top_k_more_core.h`

#### K22. TopK 非尾轴免转置：局部转置 + RADIX_SELECT/MERGE_SORT + SIMT scatter 写回

- 适用算子：top_k_v2（非尾轴小轴）
- 策略说明：输入 `[outer][inner][axis]` 按 inner 分 chunk，每 chunk 在 UB 内局部转置为 `[innerChunk, axis]` 行主序，逐行调 TopK API（`UseMergeSort=false` 用 RADIX_SELECT，bf16 用 MERGE_SORT 并转 fp32），结果由 SIMT kernel 按 `gmOffset = base + rank*innerSize + innerStart + inner` 散射回 `[outer][k][inner]` 输出布局，全程无全局转置。

```cpp
for (uint32_t idx = threadIdx.x; idx < total; idx += threadNum) {
    uint32_t rank = idx / curInnerChunk;
    uint32_t inner = idx - rank * curInnerChunk;
    uint64_t gmOffset = baseOffset + rank * innerSize + innerStart + inner;
    outputValue[gmOffset] = topkValue[inner * valueRowElems + rank];
    outputIndex[gmOffset] = topkIndex[inner * indexRowElems + rank];
}
```

- 来源：`math/top_k_v2/op_kernel/arch35/top_k_non_last_small_non_transpose.h`

#### K23. 实验 radix_sort（纯 SIMT）：device-wide LSD 三阶段流水线

- 适用算子：experimental/math/radix_sort（pathType 2/4）
- 策略说明：每 8-bit pass 分四步，全部 SIMT kernel + `SyncAll()` 串联：Phase 0 全核清全局直方图；Phase 1 各核 UB 内建局部直方图（`asc_atomic_add` 聚合到 UB），写 per-core 直方图并非零桶原子加到全局直方图（首 pass 顺带 Encode 为无符号 key）；Phase 2 单 kernel 256 线程用 `asc_shfl_up` Kogge-Stone warp 内扫描 + UB 跨 warp 扫描算出 256 bin 全局 inclusive 前缀，并累加 per-core 直方图得每核每桶起点；Phase 3 散射（K24）。

```cpp
int64_t warpPrefix = localSum;
warpPrefix += ShflUpMask(warpPrefix, 1, laneId);
warpPrefix += ShflUpMask(warpPrefix, 2, laneId); ... // 4, 8, 16
if (laneId == PREFIX_WARP_SZ - 1) { ubWarpBuf[warpId] = warpPrefix; }
asc_syncthreads();
for (uint32_t offset = 1; offset < PREFIX_NUM_WARPS; offset <<= 1) {
    int64_t prev = (warpId >= offset) ? ubWarpBuf[warpId - offset] : 0;
    asc_syncthreads();
    if (warpId >= offset) { ubWarpBuf[warpId] = prev + ubWarpBuf[warpId]; }
    asc_syncthreads();
}
prefixSum[tid] = interWarpCarry + warpPrefix;
```

- 来源：`experimental/math/radix_sort/op_kernel/arch35/radix_sort_global.h`

#### K24. 实验 radix_sort 散射：per-strip UB 数字共享 + leader 原子分配

- 适用算子：experimental/math/radix_sort
- 策略说明：散射以 `STRIP_SIZE`（=线程数）为条带：每线程把本元素 digit 写入 UB 共享数组，同步后各自扫描条带统计同 digit 元素中排在自己之前的个数 `popc` 与同 digit 总数 `groupCnt`；每条 digit 的 leader（`popc==0`）用 `asc_atomic_add` 为该 digit 整组一次性分配基址；再同步后各元素按 `全局bin前缀 + coreStarts + leader基址 + popc` 算出稳定的全局位置。把每元素一次原子加压缩成每 digit 一次，并保持稳定性。

```cpp
if (valid) {
    for (int32_t j = 0; j < stripSize; j++) {
        if (ubDigits[j] == myDigit) { groupCnt++; if (j < localTid) { popc++; } }
    }
}
if (valid && popc == 0) {
    int32_t base = asc_atomic_add(&sharedCounter[myDigit], groupCnt);
    leaderBase[myDigit] = base;
}
asc_syncthreads();
int64_t globalPos = prevBins + coreStarts[coreBase + myDigit] + base + popc;
asc_stcg(&dstKeysGm[globalPos], key);
asc_stcg(&dstIdxGm[globalPos], idx);
```

- 来源：`experimental/math/radix_sort/op_kernel/arch35/radix_sort_global.h`

#### K25. 实验 radix_sort：每核排序一段 + SIMT 2 路合并树

- 适用算子：experimental/math/radix_sort（pathType 3/4 收尾）
- 策略说明：各核先把本段基数排序到 workspace，然后按 `gap = 1,2,4,...` 倍增做 2 路合并树——`coreIdx % (2gap)==0` 的核作为合并者调用 `RadixSortMerge2WayParallelKernel` 合并左右两段（合并核内部多线程并行划分合并路径）；每轮 `SyncAll()`、ping-pong 交换源/目的缓冲。

```cpp
int64_t gap = 1;
while (gap < needCore) {
    if (coreIdx % (gap * 2) == 0) {
        if (partnerBase < totalElements) {
            asc_vf_call<RadixSortMerge2WayParallelKernel<T, descending>>(dim3(SCATTER_THREAD_NUM), ...);
        } else if (segBase < totalElements) {
            asc_vf_call<RadixSortCopySegmentKernel<T, descending>>(dim3(COPY_THREAD_NUM), ...);
        }
    }
    SyncAll();
    gap *= 2;
}
```

- 来源：`experimental/math/radix_sort/op_kernel/arch35/radix_sort_simt.h`

#### K26. CRTP 基类复用：sort/kth_value/topk 共享一套排序基础设施

- 适用算子：sort、kth_value、top_k_v2、sort_with_index（横切设计）
- 策略说明：arch35 排序 kernel 大量采用 CRTP：基类持有缓冲、队列与主流程（Process 循环、阶段编排），派生类只实现算子特有部分。例如 `RadixMoreCoreBase`（四轮 pass 编排）、`SmallAxisTwoStageBase`、`MergeIntraCoreBase`、`MergeMoreCoreBase`、`NonLastSmallAxisBase`。kth_value 与 sort 共享同一份实现仅输出环节分化；SortAndTopK 直接继承 `SortRadixMoreCore`。

```cpp
// radix_more_core_base.h
static_cast<Derived*>(this)->ScatterKeysGlobal(xLocal, sortedValueIndexLocal, ...);
// merge_intra_core_base.h —— Phase 3: derived writes either the full sorted row or the kth pair.
static_cast<Derived*>(this)->ExtractAndCopyOut(batchIdx, resultRegion);
```

- 来源：`math/sort/op_kernel/arch35/common/radix_more_core_base.h`、`math/sort/op_kernel/arch35/common/merge_intra_core_base.h`

#### K27. 混合流水同步：MTE2/V/MTE3/SIMT 事件链

- 适用算子：sort 全系小轴/非尾轴模板（横切设计）
- 策略说明：SIMT VF 调用在向量流水线上执行，与 MTE2（GM→UB）、MTE3（UB→GM）之间的数据依赖全部用显式 event 同步：`MTE2_V`（加载完成才能算）、`V_MTE3`（产出完成才能写回）、`MTE3_MTE2`（写回完成才能覆盖输入缓冲）、`V_S`（SIMT 直写 GM 后标量可见）。

```cpp
event_t eventIdVToMte3 = static_cast<event_t>(this->pipe_->FetchEventID(HardEvent::V_MTE3));
SetFlag<HardEvent::V_MTE3>(eventIdVToMte3); WaitFlag<HardEvent::V_MTE3>(eventIdVToMte3);
DataCopyPad(outValueGm_[gmOffset], finalValues_, valueCopyParam);
// finalValues_ aliases inputValues_; next LoadBatch uses MTE2 to overwrite that UB.
event_t eventIdMte3ToMte2 = ...;
SetFlag<HardEvent::MTE3_MTE2>(eventIdMte3ToMte2); WaitFlag<HardEvent::MTE3_MTE2>(eventIdMte3ToMte2);
```

- 来源：`math/sort/op_kernel/arch35/sort_small_axis_two_stage.h`

### 附：策略-算子-模板对应速查

| 模板/schId | sort | kth_value | sort_with_index | top_k_v2 | radix_sort(exp) |
|---|---|---|---|---|---|
| 轴长=1 直通 copy | sch7 | 有 | - | - | - |
| 小轴两阶段（SIMT 还原行序） | sch6/11 | 有 | - | - | - |
| 小轴 SIMT 插入排序 | sch5 | 有 | - | - | - |
| 非尾轴免转置小轴 | sch9/10 | 有 | - | 有 | - |
| 单核归并（vbs/Sort API） | sch0/8 | 有 | small optim | small merge sort | - |
| 单核基数一行 | sch1 | 有 | single block | single block/core | path 1/3 |
| 核内归并三阶段 | sch4 | 有 | - | fp32 intra-core | - |
| 多核归并合并树 | sch3 | 有 | - | fp32 more-core | tree merge |
| 多核 radix（hist+lookback+scatter） | sch2 | 有 | multi block | radix more core/sortAndTopK | path 2/4 |
| radix select（缩桶不排序） | - | 有 | - | （TopK API 内部） | - |
| 短轴 SIMT 部分选择/堆 | - | 有 | - | （核间优化二次 TopK） | - |

---
## 四、直方图与计数类（Histogram/Bincount）

> 范围：`math/{histogram_fixed_width, histogram_v2, bincount, sparse_bincount, ragged_bin_count}`。
> 通用架构：外层 `__aicore__` 代码负责 TPipe/UB 分配、DMA 搬运、核间 `SyncAll`；内层 SIMT VF（每核 512/1024 线程）负责随机读输入、计算 bin 下标、原子累加——**随机写是 SIMT 相对 SIMD 的核心优势场景**。

### Tiling 策略

#### T1. 三档模板选择——bin 数 vs UB 容量 vs 输入密度

- 适用算子：histogram_fixed_width、histogram_v2（判据一致）
- 策略说明：先算 UB 能容纳的 int32 桶数 `ubNumCanUse`，再按两级条件分流：
  1. `bins < ubNumCanUse` → `FULL_LOAD`：整个直方图常驻 UB，线程只写 UB；
  2. 放不下但 `totalLength > bins / GM_ATOMIC_ADD_FACTOR(=100)`（输入密度高，平均每桶命中 >100 次）→ `NOT_FULL_LOAD`：UB 分块轮转累加，块间 DMA 原子加写回 GM；
  3. 桶多且输入稀疏（GM 原子冲突率低）→ `NOT_FULL_LOAD_SIMT`：完全放弃 UB 副本，SIMT 直接对 GM 原子加，连 `SetLocalMemorySize` 都不设置（UB 全留给 DCache）。

```cpp
uint64_t ubSizeAvail = ubSize_ - HFW_SIMT_DCACHE_SIZE;
int64_t ubNumCanUse = static_cast<int64_t>(ubSizeAvail / HFW_SIZE_OF_INT32);
if (bins_ < ubNumCanUse) {
    loadMode_ = HFW_TPL_LOAD_MODE_UB_FULL;
    context_->SetLocalMemorySize(ubSizeAvail);
} else if (totalLength_ > bins_ / HFW_GM_ATOMIC_ADD_FACTOR) {
    loadMode_ = HFW_TPL_LOAD_MODE_UB_NOT_FULL;
    context_->SetLocalMemorySize(ubSizeAvail);
} else {
    loadMode_ = HFW_TPL_LOAD_MODE_UB_NOT_FULL_SIMT;
}
```

- 来源：`histogram_fixed_width/op_host/arch35/histogram_fixed_width_tiling_arch35.cpp`、`histogram_v2/op_host/histogram_v2_simt_tiling.cpp`

#### T2. UB 预算统一扣除 SIMT DCache 预留

- 适用算子：全部 5 个算子
- 策略说明：histogram_fixed_width/histogram_v2/bincount 扣 32KB，sparse_bincount/ragged_bin_count 扣 128KB，并用 `SetLocalMemorySize/SetDynUBufSize` 把净预算下发 kernel，保证 host 私有化决策与 device TPipe 分配使用同一个数。

```cpp
OP_CHECK_IF(ubSize <= DCACHE_SIZE + STATIC_UB_ESTIMATE, ...);
// Everything the SIMT DCache does not claim is the dynamic UB budget TPipe allocates the private
// histogram from, so the privatisation decision and SetDynUBufSize must use the same number.
budget.localMemorySize = ubSize - DCACHE_SIZE - STATIC_UB_ESTIMATE;
```

- 来源：`ragged_bin_count/op_host/arch35/ragged_bin_count_tiling.cpp`

#### T3. 双维度核数划分——按输入分核与按输出清零分核取最大值

- 适用算子：histogram_fixed_width、histogram_v2、bincount（非确定路径）
- 策略说明：kernel 有两个阶段的并行度需求：清零输出按 bins 划分（`clearYCoreNum`），统计阶段按输入划分（`needXCoreNum`）。tiling 分别计算后取 max 作为最终 blockDim，并 `SetScheduleMode(1)` 以支持 `SyncAll` 核间同步。

```cpp
formerLength_ = Ops::Base::CeilDiv(totalLength_, coreNum_);
needXCoreNum_ = Ops::Base::CeilDiv(totalLength_, formerLength_);
clearYFactor_ = Ops::Base::CeilDiv(bins_, coreNum_);
clearYCoreNum_ = Ops::Base::CeilDiv(bins_, clearYFactor_);
needCoreNum_ = std::max(needXCoreNum_, clearYCoreNum_);
```

- 来源：`histogram_v2/op_host/histogram_v2_simt_tiling.cpp`

#### T4. bincount 四档调度 + batch_load 上限保护

- 适用算子：bincount
- 策略说明：确定性需求优先走 `SCH_ID_SIMT_DETERMIN`；int64 输出不支持 UB 原子累加强制 `NOT_FULL_LOAD`；`bins < ubNumCanUse` 走 `FULL_LOAD`；输入密度达标且 `ubLoopNum <= MAX_UB_LOOP_FOR_BATH(=8)` 走 `BATCH_LOAD`，分块次数过多则退回 GM 原子（重复扫描输入 8 次以上得不偿失）。

```cpp
if (isDetermine_) { schId_ = SCH_ID_SIMT_DETERMIN; return ComputeTilingSimtDetermine(); }
if (binsDataType_ == ge::DT_INT64) { schId_ = SCH_ID_SIMT_NOT_FULL_LOAD; ... }
if (binsShapeSize_ < ubNumCanUse_) { schId_ = SCH_ID_SIMT_FULL_LOAD; }
else if (IsMatchSimtBatchLoadMode()) {
    int64_t ubLoopNum = Ops::Base::CeilDiv(binsShapeSize_, ubNumCanUse_);
    schId_ = (ubLoopNum <= MAX_UB_LOOP_FOR_BATH) ? SCH_ID_SIMT_BATCH_LOAD : SCH_ID_SIMT_NOT_FULL_LOAD;
} else { schId_ = SCH_ID_SIMT_NOT_FULL_LOAD; }
```

- 来源：`bincount/op_host/arch35/bincount_tiling.cpp`

#### T5. tilingKey 复合编码——loadMode × fp32 输出 × 确定性 × 输入 dtype

- 适用算子：histogram_v2（最典型），bincount/sparse_bincount/ragged_bin_count 为位域变体
- 策略说明：histogram_v2 用十进制位段：`百位=loadMode(100/200/300)`、`十位=fp32 输出(+10)`、`千位=确定性(+1000)`、`个位=输入 dtype(1~7)`。确定性只作用于 fp32 输出路径（int32 原子本身确定）。sparse_bincount 用 3 个 bit（is1D<<2 | binary<<1 | hasWeights）编 8 个场景；ragged_bin_count 的编解码常量放在 kernel 侧共享头文件防漂移。

```cpp
int64_t outputOffset = isFp32Output_ ? OUTPUT_FP32_KEY_OFFSET : 0;
// 只有输出为fp32才会走确定性逻辑的tilingKey
int64_t determOffset = isFp32Output_ ? isDeterministic_ * DETERM_OFFSET : 0;
context_->SetTilingKey(TILING_KEY_UB_FULL + outputOffset + determOffset + inputDtypeVal);
```

- 来源：`histogram_v2/op_host/histogram_v2_simt_tiling.cpp`

#### T6. ragged_bin_count 的映射模式与私有化代价模型

- 适用算子：ragged_bin_count
- 策略说明：两个核心决策：
  1. **ROW vs VALUE 映射**：行数不足以喂满按值分核的并行度（`numRows < valueCoreNum`）且平均行很长（`numValues/numRows > 1024`）时切换为 VALUE 映射（按值全局 grid-stride + 二分找行），否则 ROW 映射（核间按行轮转）；
  2. **UB 私有化决策**：整幅输出在每核 UB 放私有副本的条件——输出 32B 对齐后能放进 UB 净预算，且回写流量 `outputElements * coreNum` 不超过省下的散列 GM 原子数 `numValues * PRIVATE_WRITEBACK_FACTOR(=8)`（连续原子 DMA 每元素代价远低于竞争下的散列原子）。

```cpp
uint32_t DecidePrivateHistElems(const ProblemSize& problem, const PlatformBudget& budget, int64_t coreNum)
{
    const uint64_t alignedHistBytes = CeilAlign(outputElements * OUTPUT_ELEMENT_BYTES, UB_ALIGN_BYTES);
    if (alignedHistBytes > budget.localMemorySize) { return 0U; }
    if (problem.outputElements * coreNum > problem.numValues * PRIVATE_WRITEBACK_FACTOR) { return 0U; }
    return static_cast<uint32_t>(problem.outputElements);
}
```

- 来源：`ragged_bin_count/op_host/arch35/ragged_bin_count_tiling.cpp`

#### T7. 确定性分段归约的 workspace 划分（ragged precise-VALUE）

- 适用算子：ragged_bin_count
- 策略说明：VALUE 映射 + 有权重 + 非 binary + 高竞争子域（`numBins<=2 且 numValues*numBins<=262144`）时启用确定性分段归约。workspace 布局：32B 头部（invalidFlag）+ `coreNum × outputElements × 16 分区 × 16B(high/low/flags/pad)`，host 逐级 uint64 溢出检查。

```cpp
constexpr int64_t PRECISE_VALUE_PARTITIONS_PER_CORE = 16;
uint64_t entryCount = coreNum * outputElements * PRECISE_VALUE_PARTITIONS_PER_CORE;
userWorkspaceSize += entryCount * PRECISE_VALUE_PARTIAL_BYTES;   // 16B
```

- 来源：`ragged_bin_count/op_kernel/arch35/ragged_bin_count_precision_policy.h`

#### T8. sparse/ragged 的两步核数钳制（每核最小 1024 元素）

- 适用算子：sparse_bincount、ragged_bin_count
- 策略说明：先按 `CeilDiv(numValues, maxCoreNum)` 得每核量，钳到至少 1024，再反推 needCoreNum。ragged 用 `max(numSplits, numValues, outputElements)` 作为工作量口径。

```cpp
int64_t perCoreElements = (numValues > 0) ? Ops::Base::CeilDiv(numValues, maxCoreNum) : 0;
if (perCoreElements > 0 && perCoreElements < PER_CORE_MIN) { perCoreElements = PER_CORE_MIN; }
int64_t needCoreNum = (numValues > 0) ? Ops::Base::CeilDiv(numValues, perCoreElements) : MIN_CORE_NUM;
```

- 来源：`sparse_bincount/op_host/arch35/sparse_bincount_tiling.cpp`

### Kernel 策略

#### K1. full_load——UB 私有直方图 + 线程级 UB 原子加 + DMA 原子归并

- 适用算子：histogram_fixed_width、histogram_v2、bincount 的 full_load 模板
- 策略说明：每核在 UB 开辟整幅直方图（`Duplicate` 清零），SIMT VF 内线程按 `threadIdx.x` 步进读 GM 输入、算 bin 下标，`asc_atomic_add` 到 UB 地址（UB 原子在核内 SRAM 解决，不跨 GM）；结束后 `SetAtomicAdd<int32_t>() + DataCopyPad` 把整段 UB 以原子加方式一次性折叠进 GM——**散列随机写全部留在 UB，GM 上只有每核一次连续原子 DMA**。这是"每核私有部分直方图再归并"的基础形态。

```cpp
__simt_callee__ __aicore__ inline void DoBin(__ubuf__ int32_t* yLocalAddr, const COMPUTE_TYPE v, ...)
{
    if (v == INFINITY || v != v || (v == -INFINITY && minValue != -INFINITY)) { return; }
    ...
    asc_atomic_add(yLocalAddr + binIndex, 1);
}
// Process():
Duplicate(this->yLocal_, 0, this->bins_);
asc_vf_call<UbSimtComputeWsReduce<X_TYPE, COMPUTE_TYPE>>(dim3{THREAD_NUM, 1, 1}, xGmAddr, yLocalAddr, ...);
this->yQue_.EnQue(this->yLocal_);
SetAtomicAdd<int32_t>();
DataCopyPad(this->yGm_, this->yQue_.DeQue<int32_t>(), dataCopyExtParamsAdd);
SetAtomicNone();
```

- 来源：`histogram_fixed_width/op_kernel/arch35/histogram_fixed_width_simt_full_load.h`

#### K2. not_full_load——UB 分块轮转 + bin 窗口掩码过滤

- 适用算子：histogram_fixed_width、histogram_v2、bincount(batch_load)
- 策略说明：直方图放不进 UB 时切成 `ubNumCanUse` 大小的窗口，每轮：清零 UB 块 → SIMT VF 全量扫描本核输入，仅对落在当前窗口 `[ubLoop*ubNumCanUse, ...)` 内的 bin 做 UB 原子加 → 原子 DMA 写回对应 GM 段。代价是输入被扫描 ubLoopNum 遍，所以要求输入密度足够高才选它。

```cpp
if (binIndex >= ubBase && binIndex < ubEnd) {
    asc_atomic_add(yLocalAddr + (binIndex - ubBase), 1);
}
for (uint32_t ubLoop = 0; ubLoop < ubLoopNum_; ubLoop++) {
    Duplicate(yLocal_, 0, yLocalNum);
    asc_vf_call<UbSimtComputeNotFull<X_TYPE, COMPUTE_TYPE>>(..., ubLoop, ubNumCanUse_);
    AtomicAddToGm(ubLoop, yLocalNum);
}
```

- 来源：`histogram_fixed_width/op_kernel/arch35/histogram_fixed_width_simt_not_full_load.h`

#### K3. not_full_load_simt——放弃 UB 副本，SIMT 直接对 GM 原子加

- 适用算子：histogram_fixed_width、histogram_v2、bincount(not_full_load_gm)
- 策略说明：桶极多且输入稀疏时，GM 原子冲突率低，UB 分块轮转的"多遍扫描输入"反而更贵。kernel 不分配任何 UB 缓冲，SIMT VF 直接 `asc_atomic_add(yGmAddr + binIndex, 1)`，利用 SIMT DCache 吸收散列写。这是 SIMT 最纯粹的优势场景：随机地址标量原子写在 SIMD 上无法表达。

```cpp
__simt_callee__ __aicore__ inline void DoBinAtomic(__gm__ int32_t* yGmAddr, const COMPUTE_TYPE v, ...)
{
    if (v == INFINITY || v != v || ...) { return; }
    int32_t binIndex; ... // clamp 到 [0, binsM1]
    asc_atomic_add(yGmAddr + binIndex, static_cast<int32_t>(1));
}
```

- 来源：`histogram_fixed_width/op_kernel/arch35/histogram_fixed_width_simt_not_full_load_simt.h`

#### K4. 两阶段清零-累加 + SyncAll，清零与统计共用同一批核

- 适用算子：全部 5 个算子
- 策略说明：输出必须先清零再累加，阶段间用 `SyncAll()` 保证（tiling 必须 `SetScheduleMode(1)`）。清零本身也是 SIMT VF（按 clearYFactor 分段）；`blockIdx >= clearYCoreNum` 的核提前返回。

```cpp
asc_vf_call<SimtCleanY<...>>(dim3{THREAD_NUM, 1, 1}, yGmAddr, blockIdx_, clearYCoreNum_, ...);
SyncAll();
asc_vf_call<SimtComputeAtomic<...>>(dim3{THREAD_NUM, 1, 1}, xGmAddr, yGmAddr, ...);
```

- 来源：`histogram_fixed_width/op_kernel/arch35/histogram_fixed_width_simt_common.h`

#### K5. SIMT 与 SIMD/标量的分工混合骨架

- 适用算子：全部
- 策略说明：统一骨架：`__aicore__` 外层做标量控制流（读 range/min/max、min==max 保护、ComputeType 提升 int32→int64、fp16→float）、TPipe 管理、`Duplicate` 向量清零、`SetAtomicAdd/DataCopyPad` DMA-SIMD 协同、`SetFlag/WaitFlag<HardEvent::V_MTE3>` 在 SIMT VF 完成与 MTE3 搬出间建同步；只有"随机读+下标计算+随机原子写"交给 `__simt_vf__`。VF 内 GM 读用 `asc_ldcg`（绕 L1 直取）。**外层块序号 GetBlockIdx() 必须在外层读取后显式传入 VF**（VF 内 blockIdx 是 VF grid 概念，不是算子分核）。

```cpp
// Read the logical block identity in outer __aicore__ code and pass it into the SIMT VF explicitly:
// blockIdx/gridDim inside a VF describe the VF grid, not the kernel's outer work partition.
const uint32_t launchCoreIdx = static_cast<uint32_t>(AscendC::GetBlockIdx());
asc_vf_call<ScatterByRow<...>>(dim3(THREAD_NUM), launchCoreIdx, usedCoreNum, ...);
event_t eventId = static_cast<event_t>(GetTPipePtr()->FetchEventID(HardEvent::V_MTE3));
SetFlag<HardEvent::V_MTE3>(eventId); WaitFlag<HardEvent::V_MTE3>(eventId);
```

- 来源：`ragged_bin_count/op_kernel/arch35/ragged_bin_count_simt.h`

#### K6. 主循环 6 路展开 + asc_ldcg——GM 随机读带宽榨取

- 适用算子：histogram_fixed_width（三个模板共用）
- 策略说明：每线程循环按 `blockDim.x` 步进，主体 6 路展开（UNROLL_FACTOR=6），先连续 6 次 `asc_ldcg` 再连续 6 次 DoBin，把加载延迟与原子加流水交叠；不足一轮的尾部走单路循环。

```cpp
constexpr int64_t UNROLL_FACTOR = 6;
for (; base < limitN; base += stepN) {
    COMPUTE_TYPE v0 = asc_ldcg(xGmAddr + xIndexBase + base);
    COMPUTE_TYPE v1 = asc_ldcg(xGmAddr + xIndexBase + base + stride);
    ... // v2~v5
    DoBin<X_TYPE, COMPUTE_TYPE>(yLocalAddr, v0, ...); ...
}
```

- 来源：`histogram_fixed_width/op_kernel/arch35/histogram_fixed_width_simt_full_load.h`

#### K7. 确定性 det_fp32out——用 int32 原子替代 float 原子的三阶段法

- 适用算子：histogram_v2（full_load_det_fp32out / not_full_load_det_fp32out）
- 策略说明：float 的 GM 原子加顺序不定导致 fp32 输出不确定。方案：全程不做任何 float 原子——Phase 1 把 y 的 GM 当 int32 视图清零；Phase 2 UB 内 int32 原子累加 + `SetAtomicAdd<int32_t>` DMA 折叠（整数加可交换，天然确定）；SyncAll 后 Phase 3 把 GM 段原地从 int32 位模式读值再 cast 成 float 写回（int→fp32 是确定函数）。

```cpp
this->yGmInt_.SetGlobalBuffer(reinterpret_cast<__gm__ int32_t*>(y));   // 同一块 GM 的双视图
this->yGmFloat_.SetGlobalBuffer(reinterpret_cast<__gm__ float*>(y));
SetAtomicAdd<int32_t>();
DataCopyPad(yGmInt_[0], yLocalInt, dataCopyExtParamsAdd);   // Phase 2: int32 atomic
// Phase 3: yGmFloatAddr[yIndex] = static_cast<float>(yGmIntAddr[yIndex]);
```

- 来源：`histogram_v2/op_kernel/arch35/histogram_v2_simt_full_load_det_fp32out.h`

#### K8. bincount determine——输出 bin 并行的"倒置遍历"彻底消除原子

- 适用算子：bincount（determine 模板）
- 策略说明：把并行轴从"输入元素"换成"输出桶"：每核负责一段 bins，每线程负责一个桶，串行扫描整个输入数组、命中即普通 `+=`（无线程竞争、遍历顺序固定 → 完全确定）。代价是 O(bins × arraySize) 重复读，适用于 array 较小或确定性优先场景。

```cpp
for (int64_t index = Simt::GetThreadIdx(); index < binsDataLength; index += Simt::GetThreadNum<0>()) {
    binsGmAddr[binsHeadIndex + index] = 0;
    for (int64_t arrayIndex = 0; arrayIndex < arraySize; arrayIndex++) {
        if (static_cast<int64_t>(arrayGmAddr[arrayIndex]) == binsHeadIndex + index) {
            binsGmAddr[arrayValue] += weightsGmAddr[arrayIndex];
        }
    }
}
```

- 来源：`bincount/op_kernel/arch35/bincount_determine.h`

#### K9. ragged 不规则行边界——ROW 映射边界校验 + VALUE 映射二分找行

- 适用算子：ragged_bin_count
- 策略说明：桶是二维 `(row, bin)`，行边界由变长 splits 给出。ROW 映射：核按行轮转，每行先校验 rowBegin/rowEnd 合法性（负值、倒挂、越界跳过）；VALUE 映射：全局 grid-stride 扫值，用 upper-bound 语义二分查找定位所属行，可正确跳过重复 splits 表示的空行。另有独立 VF `ValidateInputs` 校验 splits 单调性，异常时通过 workspace invalidFlag（`asc_atomic_or`）让全核提前退出。

```cpp
__simt_callee__ inline int64_t FindRaggedRow(__gm__ int64_t* splits, int64_t numRows, int64_t valueIndex)
{
    // upper-bound semantics correctly skips empty rows represented by repeated splits.
    int64_t low = 0, high = numRows;
    while (low < high) {
        const int64_t middle = low + ((high - low) >> 1);
        if (splits[middle + 1] <= valueIndex) { low = middle + 1; } else { high = middle; }
    }
    return (low < numRows && splits[low] <= valueIndex && valueIndex < splits[low + 1]) ? low : -1;
}
```

- 来源：`ragged_bin_count/op_kernel/arch35/ragged_bin_count_simt.h`

#### K10. binary 输出的 read-before-exchange 与 false-sharing 实证

- 适用算子：ragged_bin_count（SparseWrite）、sparse_bincount（add+clamp 变体）
- 策略说明：binary 模式每桶只需置 1 一次且所有写者写同值，先读再 `asc_atomic_exch` 可跳过绝大多数原子。源码注释给出四种写法实测对比：plain store 因核间 cache line false sharing **实测错误**（只有 6.25% 正确）；`atomic_or` 更慢；read+exch 比裸 exch 快 1.27×。

```cpp
//   asc_atomic_exch            correct   424 us
//   read + asc_atomic_exch     correct   1.27x faster    <- 采用
//   plain store                WRONG     75x faster, 0/32
//   asc_atomic_or(0x3F800000)  correct   0.6x, SLOWER
if (output[outputOffset] != 1.0F) { (void)asc_atomic_exch(output + outputOffset, 1.0F); }
```

- 来源：`ragged_bin_count/op_kernel/arch35/ragged_bin_count_simt.h`

#### K11. 每核 UB 私有直方图的私有化散写与批量折叠

- 适用算子：ragged_bin_count（full-output 私有化）
- 策略说明：`privateHistElems > 0` 时每核从动态 UB 预算分配整幅输出副本（32B 块向上取整防 `Duplicate` 越界），散写改打 UB（原子仍在——同核 1024 线程仍会撞桶——但在核内 SRAM 解决且不与他核共享 cache line）；最后一次性 `DataCopyPad` 折叠到已清零 GM：计数/加权用 `SetAtomicAdd<float>`，binary 用 `SetAtomicMax<float>`（max 即 0/1 的 OR，用 add 会因多核同桶得到 2.0）。

```cpp
LocalTensor<float> histogram = histogramQueue.template AllocTensor<float>();
Duplicate(histogram, 0.0F, privateHistElems);
LaunchScatter<..., true, ...>(..., (__ubuf__ float*)histogram.GetPhyAddr(), ...);
histogramQueue.EnQue(histogram); histogramQueue.template DeQue<float>();
if constexpr (BINARY_OUTPUT) { SetAtomicMax<float>(); } else { SetAtomicAdd<float>(); }
DataCopyPad(outputGlobal, histogram, copyParams);
SetAtomicNone();
```

- 来源：`ragged_bin_count/op_kernel/arch35/ragged_bin_count_simt.h`

#### K12. ragged 确定性分段归约 + fp32 补偿/精确累加器

- 适用算子：ragged_bin_count（precise-ROW / precise-VALUE）
- 策略说明：位级确定结果分三层：(1) **分段归约**：每个输出元素切成 `coreNum×16` 个固定顺序分区，各分区线程独立累加 `(high, low, flags)` 部分和写 workspace（`asc_atomic_exch` 保证可见性），SyncAll 后 core0 按固定 (core, partition) 顺序归并；(2) **Knuth TwoSum 补偿**：high/low 双分量逼近精确和，检测到非有限/次正规/低指数带风险时升级；(3) **五 limb 精确累加器**（5×64bit）：把 fp32 看作 2^-149 的整数倍做纯整数精确累加，最后手动舍入回 fp32。

```cpp
__simt_callee__ inline bool CompensatedAccumulate(float value, float& high, float& low)
{
    bool requiresExact = RequiresExactAddition(high, value);
    CompensatedTwoSum(high, value, sum, error);
    ...
    CompensatedTwoSum(sum, correction, high, low);
    return requiresExact || !IsFiniteFloat(high);
}
```

- 来源：`ragged_bin_count/op_kernel/arch35/ragged_bin_count_simt.h`

#### K13. sparse_bincount 三阶段 + binary 后处理 clamp + 索引宽度/线程数自适应

- 适用算子：sparse_bincount
- 策略说明：bin 下标直接来自 values（无需 range 映射）：Phase 1 grid-stride 清零输出 → SyncAll → Phase 2 散点原子加（1D 直接 `output[binIdx]`，ND 先读 indices 得 batch 再算 `batch*size+bin`）；binary 模式 Phase 2 仍用 atomic_add 防 WAW，SyncAll 后 Phase 3 把 >0 钳成 1.0。索引宽度按 numValues/outputSize 是否超 0xFFFFFFFF 在 uint32（1024 线程）与 uint64（512 线程）间切换。

```cpp
for (IDX_T idx = blockIdx.x * blockDim.x + threadIdx.x; idx < numValues; idx += blockDim.x * gridDim.x) {
    int64_t binIdx = static_cast<int64_t>(values[idx]);
    if (binIdx >= 0 && binIdx < sizeVal) {
        if constexpr (IS_1D) { ScatterWrite1D<BINARY_OUTPUT, HAS_WEIGHTS>(output, binIdx, idx, weights); }
        else { ScatterWriteND<BINARY_OUTPUT, HAS_WEIGHTS>(output, indices, idx, ...); }
    }
}
// Phase 3: output[i] = (output[i] > 0.0f) ? 1.0f : 0.0f   (仅 BINARY_OUTPUT)
```

- 来源：`sparse_bincount/op_kernel/arch35/sparse_bincount_simt.h`

### 附：直方图类设计规律小结

1. **模板选择统一公式**：`bins < UB容量` → UB 全载；否则看输入密度 `totalLength vs bins/100` 决定"UB 分块多遍扫描"还是"GM 直接原子"；bincount 额外以 `ubLoopNum ≤ 8` 限制多遍扫描。
2. **原子加三级落点**：同核线程间 → UB SRAM 原子（最快）；核间归并 → 连续 DMA 级 `SetAtomicAdd`（每核一次）；输入稀疏 → SIMT 直接 GM 散列原子（交给 DCache）。
3. **确定性三条路线**：int32 原子代 float 原子 + 后 cast（histogram_v2）、并行轴倒置逐桶扫描（bincount）、固定顺序分段归约 + TwoSum/大整数补偿（ragged_bin_count），分别对应输出小/输入小/高竞争小子域。

---
## 五、数据转换与重排类（Conversion）

> 范围：`conversion/`（as_strided、ball_query、batch_to_space_nd、coalesce_sparse、concat、diag、diag_flat、diag_v2、dynamic_stitch、im2col、matrix_diag、matrix_diag_part、matrix_set_diag_v2、pad_v3、pad_v3_grad、pad_v3_grad_replication、roll、sparse_reshape、split_v、strided_slice、strided_slice_grad、trans_data、transpose、view_copy）+ `math/diag_part`。
> 共性：访存主导、地址计算密集，普遍提供 SIMT 模板——每线程独立用快速除法把线性 index 分解为多维坐标，再合成源/目的 GM 地址做离散访存；SIMD/MoveAlign/NDDMA/Gather 模板处理连续大块，SIMT 作为小 shape、高维、负步长、离散步长场景的兜底或首选。

### Tiling 策略

#### T1. 小数据量 SIMT 兜底模板（字节数阈值触发）

- 适用算子：transpose、as_strided、pad_v3、pad_v3_grad
- 策略说明：总数据量低于阈值时，UB 中转的 DMA 开销不划算，直接选 SIMT 模板 GM→GM 直读直写；pad 系另以"维数 > 5"作为 SIMT 触发条件（MoveAlignV2 指令对轴数有限制）。

```cpp
// pad_v3：小输出或高维 → SIMT
static constexpr uint64_t SIMT_BRANCH_SIZE = 4 * 1024;
if (outShapeSize_ <= SIMT_BRANCH_SIZE || dimNum_ > CONST5) {
    tilingKey_ = padMode_ == ModeNum::SYMMETRIC ? SYMMETRIC_SIMT_BRANCH : REFLECT_SIMT_BRANCH;
}
// as_strided
if (totalOutElement * sizeofDtype <= SMALL_SHAPE_BYTES_THRESHOLD) { return true; }  // Need SIMT
```

- 来源：`conversion/pad_v3/op_host/arch35/pad_v3_tiling_arch35.cpp`、`conversion/as_strided/op_host/arch35/as_strided_tiling_arch35.cpp`

#### T2. 按输出元素数一维均分分核（SIMT 只关心 element 数）

- 适用算子：im2col、matrix_diag、diag、matrix_diag_part、batch_to_space_nd、ball_query、sparse_reshape、as_strided
- 策略说明：SIMT 路径不经 UB 矩形搬运，分核退化为纯一维：`blockFactor = CeilDiv(总输出元素, 核数)`；im2col/matrix_diag 先按 `VRegSize/2/dtype` 对齐成边长因子再均分；ball_query 将每核处理量向上对齐到 WARP_SIZE(32) 并设下限 64。

```cpp
// im2col Tiling4SIMT：SIMT只关注element，所以分核简化为一维
uint32_t sideLengthFactor = Ops::Base::GetVRegSize(context_) / SIMT_BUFFER_NUM / dSize_;
uint64_t alignEleBlockCount = Ops::Base::CeilDiv(outputTotalElement, sideLengthFactor);
uint64_t cores = std::min(static_cast<uint64_t>(coreNum_), alignEleBlockCount);
tilingData->blockFactor = Ops::Base::CeilDiv(alignEleBlockCount, cores) * sideLengthFactor;
tilingData->threadNum = Ops::Base::GetSimtMaxThreadNum(context_) / SIMT_THREAD_FACTOR;
```

- 来源：`conversion/im2col/op_host/arch35/im2col_tiling_arch35.cpp`、`conversion/ball_query/op_host/arch35/ball_query_tiling.cpp`

#### T3. SIMT 分核按 cacheline(128B) 对齐

- 适用算子：transpose（SMALL_SHAPE 分支）
- 策略说明：SIMT 直写 GM 时为保证跨核写边界对齐 cacheline，取 `blkFactor = total/coreNum` 的 128B 向上/向下对齐两个候选：floor 对齐能开满核则用 floor，否则用 ceil 重算核数；总元素小于对齐粒度或核数时只开 1 核。

```cpp
int64_t alignElements = SMALL_SHAPE_SPLIT_BYTES_ALIGN_SIZE / shapeInfo_.eleLenInBytes;
int64_t blkFactor = totalElements / coreNum_;
int64_t ceilAlignFactor = Ops::Base::CeilAlign(blkFactor, alignElements);
int64_t floorAlignFactor = Ops::Base::FloorAlign(blkFactor, alignElements);
if (totalElements - floorAlignFactor * (coreNum_ - 1) <= floorAlignFactor) {
    realCoreNum_ = coreNum_; blkFactor_ = floorAlignFactor;
} else {
    realCoreNum_ = Ops::Base::CeilDiv(totalElements, ceilAlignFactor); blkFactor_ = ceilAlignFactor;
}
```

- 来源：`conversion/transpose/op_host/arch35/transpose_tiling_arch35.cpp`

#### T4. SIMT 准入启发式（数据量 + 负载偏斜 + tensor 数）

- 适用算子：concat、split_v
- 策略说明：SIMT 每个核以 tensor 为粒度轮询，负载均衡取决于各 tensor 大小差异。tiling 用启发式拒绝 SIMT：总量 ≥ 64K×核数、tensor 数 > 128、各 tensor dim1 最大/最小比 ≥ 2 且绝对量大、余数分布不均等；split_v 额外拒绝等长模式和 numSplit ≤ coreNum/4。

```cpp
static bool IsEnableUsedSimt(ConcatTilingParam& param)
{
    if (totalDataNum >= useCoreNum * SIMT_PER_CORE_THRESHOLD) { return false; }     // 总数据量过大
    if (param.isAllTensorAlign == 1 || param.inputShapeSame == 1) { return false; } // 对齐/相同shape走SIMD
    if (param.tensorNum > TILING_COLS_OFFSET_LENGTH) { return false; }              // tensor数 > 128
    // 单个tensor数据量大于1024且波动2倍以上，不用simt
    if (maxDim1 / minDim1 >= 2 && maxDim1 * param.catDim0 * param.dtypeSize > SIMT_COMPARE_THRESHOLD) { return false; }
    return true;
}
```

- 来源：`conversion/concat/op_host/arch35/concat_tiling_arch35.cpp`、`conversion/split_v/op_host/arch35/split_v_tiling_arch35.cpp`

#### T5. 不等长分段的前缀和偏移（colOffset）与每段独立快速除法

- 适用算子：concat（SIMT）、split_v（SIMT_KEY=200）
- 策略说明：把拼接/切分轴折叠为二维 (M, N)，tiling 预计算每个 tensor 在 N 方向的前缀和 `colOffset`，kernel 内按当前 tensor 段长现场算 magic/shift 做 (row, col) 分解。dtype > 8 字节时按 int64 拆分使 concat 轴元素数翻倍。

```cpp
for (auto dimPtr = param.tensorListDim1.begin(); dimPtr != param.tensorListDim1.end(); ++dimPtr) {
    curConcatDimOffset = curConcatDimOffset + *dimPtr * digitSize;
    param.tensorColsOffset.push_back(curConcatDimOffset);
}
```

- 来源：`conversion/concat/op_host/arch35/concat_tiling_arch35.cpp`

#### T6. split_v 单个输出 tensor 内部再切核（SIMT_KEY_SPLIT_TENSOR=202）

- 适用算子：split_v
- 策略说明：当 `numSplit <= coreNum/2` 且 `mSize × maxFuseSize > 1024` 时 tensor 数太少不足以喂满核，把每个输出 tensor 的 N 段再均分给 `perBlkSize = coreNum/numSplit` 个核，colOffset 扩展为 per-block 前缀和。

```cpp
if (numSplit_ <= maxCoreNum / 2 && mSimtSize_ * maxFuseSizeAfterSplit_ > SIMT_THREAD_NUM) {
    int32_t perBlkSize = maxCoreNum / numSplit_;
    for (int32_t i = 0; i < numSplit_; i++) {
        int32_t curBlkFactor = Ops::Base::CeilDiv(curNLen, perBlkSize);
        for (int32_t j = 0; j < perBlkSize; j++) { /* 累加 colOffset */ }
    }
    tilingKey_ = SIMT_KEY_SPLIT_TENSOR;
}
```

- 来源：`conversion/split_v/op_host/arch35/split_v_tiling_arch35.cpp`

#### T7. split_v 全局 chunk 均衡模板（SIMT_CHUNK_KEY=204）：tiling 预计算 per-block 描述符

- 适用算子：split_v
- 策略说明：针对 SIMT 因偏斜被拒但偏差不大的场景，tiling 把全部输出元素的拷贝任务切成全局逻辑 block（128 线程 × 16 block/核），为每个输出 tensor 预计算 `qPerBlk/rPerBlk`（商余均分）、`divMagic/divShift`、`strideDiff`、`blockPrefix`，kernel 标量侧仅查表填 UB 描述符，VF 纯执行，彻底消除核间负载不均。

```cpp
int64_t bStart = j * q + (j < r ? j : r);
int64_t bEnd = bStart + q + (j < r ? 1 : 0);
uint64_t magic = tilingData_->divMagic[oi];
ubTensor.SetValue(k * CHUNK_PRE_UB_FIELD_PER_BLOCK + 3, magic);  // 描述符写入 UB
```

- 来源：`conversion/split_v/op_kernel/arch35/split_v_simt_chunk_pre.h`

#### T8. strided_slice 模板优先级（MoveAlign/NDDMA/Gather 优先，SIMT 兜底）

- 适用算子：strided_slice
- 策略说明：按尾轴 stride 和有效字节数逐级判定：尾轴 stride==1 且足够长 → MoveAlignV2；cacheline 内有效元素够 → NDDMA；负步长走负 stride 专用路径；都不满足（高维、元素少、shape 超 uint32 走 BIG_SHAPE）→ SIMT。空 tensor 直接置 SIMT 空跑。

```cpp
if (isEmptyTensor_) { SetSIMTTilingMode(); }
else if (isStrideNeg_) { CalMaxSplitDimNeg(); ... SetTilingModeNeg(); }
else { CalMaxSplitDim(); ... }
void SetSIMTTilingMode() { tilingKey_ = isShapeExceedUint32_ ? STRIDED_SLICE_KEY_SIMT_BIG_SHAPE : STRIDED_SLICE_KEY_SIMT; }
```

- 来源：`conversion/strided_slice/op_host/arch35/strided_slice_tiling_arch35.cpp`

#### T9. strided_slice_grad 计算模式选择 + 双段分核（清零与回写分离）

- 适用算子：strided_slice_grad
- 策略说明：tilingKey 三位编码：百位=清零模式（全量清零 vs NDDMA 免清零）、十位=计算模式（SIMT=1/前轴 MoveAlign/全轴 MoveAlign/NDDMA）、个位=dtype 字节数。SIMT 模式按 dy 总元素均分分核；另按输出 inShape 单独均分一套清零分核参数（先清 0 再 scatter 回写）。

```cpp
int64_t hundredDigit = (caluMode == NDDMA模式) ? NO_CLEAR_MODE : ALL_CLEAR_MODE;
inputParams.tilingKey = hundredDigit * 100 + caluMode * 10 + bytesForOneData;
if (caluMode == MODE_SIMT) {
    auto result = AverageTiling(inputParams.dyShapeOutSize, inputParams.totalCoreNum);
}
```

- 来源：`conversion/strided_slice_grad/op_host/arch35/strided_slice_grad_tiling_arch35.cpp`

#### T10. dynamic_stitch 跨 tensor 均分：按元素总数给每核划 (tensorIdx, offset) 区间

- 适用算子：dynamic_stitch
- 策略说明：以全部 tensor 的第 0 维元素总数为工作量，`blockFactor = CeilDiv(totalTensorSum, coreNum)`，扫描每个 tensor 元素数为每核记录 `[tensorStart, tensorEnd, startOffset, endOffset]`（允许一个 tensor 被两核切开）；按 slice 字节数可被 8/4/2/1 整除分类 sliceType 提升搬运效率。负/重复 index 先 atomic_max 去重再 scatter。

```cpp
for (uint16_t i = 0; i < totalTensorCnt_; i++) {
    currCoreBorder = (coreIndex < usedCoreNum_) ? blockFactor_ : tailBlockFactor_;
    int64_t tempCount = tensorCntList_[i] - curDataPos;
    if (dataCount + tempCount < currCoreBorder) { dataCount += tempCount; curDataPos = 0; continue; }
    tensorEndList_[coreIndex] = i;
    curDataPos = curDataPos + currCoreBorder - dataCount;
    ...
}
```

- 来源：`conversion/dynamic_stitch/op_host/arch35/dynamic_stitch_tiling_arch35.cpp`

#### T11. coalesce_sparse：DAV_3510 特化均分 + 确定性模式单核串行

- 适用算子：coalesce_sparse
- 策略说明：按 indices 行数分核，arch35 用简单 CeilDiv 均分（老平台按 256 对齐）；`deterministic` 模式强制 `usedCoreNum=1` 保证写出顺序确定。

```cpp
bool isAscend950 = ascendcPlatform.GetCurNpuArch() == NpuArch::DAV_3510;
if (isAscend950) { taskNum = (n + coreNum - 1) / coreNum; usedCoreNum = (n + taskNum - 1) / taskNum; }
if (ret != 0) { usedCoreNum = 1; taskTail = n; deterministicFlag = 1; }
```

- 来源：`conversion/coalesce_sparse/op_host/coalesce_sparse_tiling.cpp`

#### T12. trans_data：按 int32 是否越界选 SIMT 位宽模板与线程数

- 适用算子：trans_data
- 策略说明：ND↔fractal_NZ 转换全量走 SIMT。折叠后 `shapeSize = h * CeilAlign(n,16) * CeilAlign(c,c0)` 超 int32 上限用 LARGE_SHAPE（uint64 索引、256 线程），否则 uint32、512 线程。

```cpp
int64_t shapeSize = h_ * CeilAlign(n_, 16) * CeilAlign(c_, c0_);
tilingKey_ = (shapeSize > MAX_INT32_SIZE) ? TILING_MODE_SIMT_LARGE_SHAPE : TILING_MODE_SIMT;
tNum_ = (tilingKey_ == TILING_MODE_SIMT) ? tNum512 : tNum256;
```

- 来源：`conversion/trans_data/op_host/arch35/transdata_tiling_arch35.cpp`

#### T13. batch_to_space_nd：高维/小尾轴/空 tensor → SIMT，blockSize 向下对齐线程数

- 适用算子：batch_to_space_nd
- 策略说明：合并维度后 `rank >= 6`、dtype 1 字节、输出为空时直接走 SIMT；尾轴 ≥ cacheline 元素走 LargeC（MoveAlign）。SIMT 路径把 UB 预留 Dcache(32K) 后对半双缓冲，`blockSize = FloorAlign(bufSize/dSize, threadNum)` 保证 VF 内循环按线程整除。

```cpp
if (mergedInput_.rank >= MIN_RANK_FOR_SIMT) { return Tiling4SIMT(); }
uint32_t validBufSize = (ubSize_ - SIMT_DCACHE_SIZE) / SIMT_BUFFER_NUM;
tilingData->blockSize = std::max(1U, Ops::Base::FloorAlign(usedBufSize / dSize_, threadNum));
```

- 来源：`conversion/batch_to_space_nd/op_host/arch35/batch_to_space_nd_tiling_arch35.cpp`

#### T14. diag / matrix_diag：对角线算子一维化分核

- 适用算子：diag、matrix_diag
- 策略说明：输出 n×n 大部分为 0，SIMT 只负责写对角线（共 n 或 batch×n 个），分核按"边长因子 = HALF_VL(128B)/dtype"对齐后均分。

```cpp
int64_t sideLengthFactor = HALF_VL_LEN / dtypeSize;
int64_t blockNum = Ops::Base::CeilDiv(nSize, sideLengthFactor);
int64_t cores = std::min(coreNum, blockNum);
int64_t mainFactor = Ops::Base::CeilDiv(nSize, cores);
```

- 来源：`conversion/diag/op_host/arch35/diag_tiling_arch35.cpp`

#### T15. matrix_diag_part / diag_part：按对角线长度分核，`inputRowStride = N+1` 预计算

- 适用算子：matrix_diag_part、math/diag_part
- 策略说明：对角抽取的地址规律固化为常量：`inputRowStride = N + 1`、`diagLen = min(M,N)`，按输出元素总数均分（每核下限 1024）。math/diag_part 按 dtype 选边长因子，blockNum > coreNum 才用 SIMT（否则 gather 模板）。

```cpp
tiling->diagLen = d; tiling->inputRowStride = N + 1; tiling->matrixSize = matrixSize;
int64_t perCoreElements = Ops::Base::CeilDiv(totalOutputElements, coreNum);
if (perCoreElements < PER_CORE_MIN) { perCoreElements = PER_CORE_MIN; }
// math/diag_part：blockNum 超过核数走 SIMT，否则 gather
if (blockNum_ > coreNum_) { tilingContext_->SetTilingKey(TILING_KEY_SIMT); }
```

- 来源：`conversion/matrix_diag_part/op_host/matrix_diag_part_tiling_arch35.cpp`

#### T16. view_copy：尾轴连续字节数决定 SIMT；tilingKey 三位编码

- 适用算子：view_copy
- 策略说明：`IsEnableSimt` 沿 dst 从尾轴向前合并连续段（`dstSize[i+1]*dstStride[i+1]==dstStride[i]` 即连续），连续段字节数低于阈值或尾轴 stride≠1 → SIMT（DMA 拷入 UB 连续数据，SIMT 按 dstStride 散写 GM）。tilingKey = 百位(1非SIMT/2 SIMT)×100 + 十位(维度)×10 + 个位(dtype 字节)。

```cpp
for (int64_t i = dstSize.size() - 2; i >= 0; i--) {
    if (dstSize[i+1] * dstStride[i+1] == dstStride[i]) { tailAxisByteNum *= dstSize[i]; } else { break; }
}
bool isSimt = tailAxisByteNum * byteNum < BYTE_THRESHOLD_TAIL_AXIS;
int64_t hundredDigit = tilingParam.isSimt ? 2 : 1;  // tilingKey = 百位(SIMT)×100 + 十位(维度)×10 + 个位(dtype)
```

- 来源：`conversion/view_copy/op_host/arch35/view_copy_tiling_arch35.cpp`

#### T17. sparse_reshape：identity 检测 + 按 nnz 均分

- 适用算子：sparse_reshape
- 策略说明：tiling 读取 shape/new_shape 常量张量，若 reshape 前后坐标不变（identity）走纯拷贝；否则下传 inputStrides/outputStrides，kernel 内合成 flatId 再分解。按非零元个数 nnz 均分开核。

```cpp
int32_t isIdentity = DetectIdentityReshape(shapeData, resolvedShape, ...);
tiling->isIdentityReshape = isIdentity;
int64_t perCore = (nnz > 0) ? Ops::Base::CeilDiv(nnz, coreNum) : 0;
```

- 来源：`conversion/sparse_reshape/op_host/arch35/sparse_reshape_tiling_arch35.cpp`

#### T18. roll：负 shift 归一化 + 每维 shapes/strides/shifts 直接下传

- 适用算子：roll
- 策略说明：tiling 用带符号安全的 Mod 把负 shift 归一到 [0, shape)；SIMT 模板按总元素均分，每维 shapes/strides/shifts 原样写入 tilingData，kernel 内直接用除/模做循环移位（维度少用 int64，不做 magic 预计算）。

```cpp
inline static int64_t Mod(int64_t a, int64_t b) { int64_t r = a % b; if (r < 0) { r += (b < 0) ? -b : b; } return r; }
perCoreElements_ = (totalEmelents_ + numBlocks - 1) / numBlocks;
for (int32_t i = 0; i < dimNum_; i++) { tilingData_->shapes[i] = shapes_[i]; tilingData_->shifts[i] = shifts_[i]; ... }
```

- 来源：`conversion/roll/op_host/arch35/roll_tiling_arch35.cpp`

#### T19. pad_v3 负 pad 转 slice + 合轴优化（DimensionCollapse）

- 适用算子：pad_v3
- 策略说明：两个 shape 预处理策略：(1) **负 pad 即切片**——`isPadAllNegative_` 时不走 pad 逻辑，转成 begin/end/stride 调 Slice 的 tiling（key=10000）；(2) **合轴**——pad 为 0 的连续维度合并、消除尺寸 1 轴，leftPad/rightPad 同步折叠，降低 kernel 的维度分解开销。`totalElements > INT32_MAX` 切 BIG_SIZE 模板。

```cpp
if (isPadAllNegative_) { DoTilingWithSliceOp(); }   // 负 pad = 切片, key=10000
for (d = 0; d < dimNum; d++) {
    if (leftPad[d] == 0 && rightPad[d] == 0 && d + 1 < dimNum) {
        shape[d] *= shape[d + 1];  /* 折叠 */ removeDim(d + 1);
    }
}
if (totalElements > INT32_MAX) { tilingKey = BIG_SIZE_BRANCH; }
```

- 来源：`conversion/pad_v3/op_host/arch35/pad_v3_tiling_arch35.cpp`

#### T20. pad_v3 核数均衡调优（GetOptimizeTiling）

- 适用算子：pad_v3
- 策略说明：防"开满核每核一点数据"：当 `usedCoreNum / coreNum < 0.8`（MIN_USED_CORES_RATIO）且 tile ≥ 4KB 时，逐轴逐 factor 搜索新的切分方式，使启用核数比例提升到 80% 以上。tilingKey 个/十位还编码"UB 切到倒数第几根轴"（`(dimNum - ubAxis) * DIM_OFFSET_SCALE`）。

```cpp
if (usedCoreNum / coreNum < 0.8 && tile >= 4KB) {
    for (axis in dims) for (factor in candidates) {
        if (NewSplit(axis, factor) 使分核数 >= 80%) { 采用; break; }
    }
}
tilingKey_ += (dimNum_ - ubAxis_) * DIM_OFFSET_SCALE;   // 编码切分轴位置
```

- 来源：`conversion/pad_v3/op_host/arch35/pad_v3_tiling_arch35.cpp`

#### T21. concat 按 tensor 数分核 + dtype 字节折算 B64

- 适用算子：concat
- 策略说明：SIMT 模板下 `usedCoreNum = min(tensorNum, totalCoreNum)`——按 tensor 数而非元素数分核（每核轮询若干个 tensor）；`tensorNumPerCore = CeilDiv(tensorNum, usedCoreNum)`；>64bit dtype 折算成 B64 单位（`catDim1 = dtypeSize/8 * catDim1`）扩大搬运粒度；tilingKey = 30000 + dtypeSize。

```cpp
usedCoreNum = std::min(tensorNum, totalCoreNum);
tensorNumPerCore = CeilDiv(tensorNum, usedCoreNum);
CalcTensorColsOffset();                    // 各 tensor 在拼接轴的累计列偏移
tilingKey = SIMT_TILINGKEY_PREFIX /*30000*/ + dtypeSize;
```

- 来源：`conversion/concat/op_host/arch35/concat_tiling_arch35.cpp`

### Kernel 策略

#### K1. 通用坐标变换：线性 index → 多维坐标 → 乘 stride 累加出目标地址

- 适用算子：as_strided、pad_v3、transpose、strided_slice、batch_to_space_nd 等全部 SIMT 模板
- 策略说明：SIMT VF 标准骨架——线程按 `idx = threadIdx.x; idx < count; idx += blockDim.x` 遍历本核输出元素，逐维 `Simt::UintDiv` 求商、`idx -= dim*stride` 求余，得各维坐标后乘各自 stride 累加成源地址，一次 GM 读 + 一次 GM 写。按维度数模板展开成 Dim1~Dim8 避免运行期循环。

```cpp
for(uint32_t index = threadIdx.x; index < count; index += blockDim.x) {
    uint32_t inputCurIdx = outputBasicIndex + index;
    uint32_t inputDimIdx[Dim] = {0};
    inputDimIdx[0] = Simt::UintDiv(inputCurIdx, m0, s0);
    inputCurIdx -= inputDimIdx[0] * sizeStride0;
    inputDimIdx[1] = Simt::UintDiv(inputCurIdx, m1, s1);
    inputCurIdx -= inputDimIdx[1] * sizeStride1;
    inputDimIdx[2] = inputCurIdx;
    uint32_t inputIdx = strideArr0 * inputDimIdx[0] + strideArr1 * inputDimIdx[1] + strideArr2 * inputDimIdx[2];
    outputGmAddr[outputIdx] = inputGmAddr[inputIdx];
}
```

- 来源：`conversion/as_strided/op_kernel/arch35/as_strided_simt.h`

#### K2. 快速除法：GetUintDivMagicAndShift 预计算 + Simt::UintDiv / __umulhi 内联

- 适用算子：几乎全部（as_strided、pad_v3、transpose、concat、split_v、im2col、matrix_diag、view_copy、strided_slice_grad、sparse_reshape、ball_query、matrix_diag_part）
- 策略说明：标量侧先对每个除数调 `GetUintDivMagicAndShift(magic, shift, divisor)`，magic/shift 作为 VF 参数（或写入 UB 数组）传入；线程内用 `Simt::UintDiv(x, m, s)` 替代硬件除法，或手写 `q = (__umulhi(x,m)+x) >> s`。

```cpp
// as_strided Process：按输出 stride 预计算
for(int32_t dim = 0; dim < dimNum_ - 1; dim++) {
    GetUintDivMagicAndShift(magic[dim], shift[dim], tilingData_->outSizeStride[dim]);
}
// concat kernel 内联 __umulhi 快速除（i / colsSize, i % colsSize）
uint32_t t1 = __umulhi(i, magic);
uint32_t numRows = (t1 + i) >> shift;
uint32_t numCols = i - numRows * colsSize + colsOffset;
```

- 来源：`conversion/as_strided/op_kernel/arch35/as_strided_simt.h`、`conversion/concat/op_kernel/arch35/one_axis_concat_simt.h`

#### K4. 按工作量自适应线程数 dispatch（LAUNCH_BOUND 多档）

- 适用算子：matrix_set_diag_v2、math/diag_part
- 策略说明：同一计算逻辑用 `template <uint32_t NUM_THREADS>` 实例化多档（128/256/512/1024/2048），按本次工作量 workSize 选刚好够用的线程数，减少小任务的线程启动/同步浪费。

```cpp
template <template <uint32_t> class FuncT, typename... Args>
__aicore__ inline void SimtDispatch(uint32_t workSize, Args... args)
{
    if (workSize <= SIMT_THREAD_NUM_1_16) { asc_vf_call<FuncT<SIMT_THREAD_NUM_1_16>::Run>(dim3(SIMT_THREAD_NUM_1_16), args...); }
    else if (workSize <= SIMT_THREAD_NUM_1_8) { ... }
    else { asc_vf_call<FuncT<SIMT_THREAD_NUM_LAUNCH_BOUND>::Run>(dim3(SIMT_THREAD_NUM_LAUNCH_BOUND), args...); }
}
```

- 来源：`conversion/matrix_set_diag_v2/op_kernel/arch35/matrix_set_diag_v2_simt.h`

#### K5. pad 常量模式：越界判定 + 填充值，常量与数据拷贝同一 VF 内分区完成

- 适用算子：pad_v3（constant）
- 策略说明：每线程处理一个输出元素，坐标减 leftPad 得输入坐标，任一维越界即写 constValue，否则读输入——填充区与数据区天然按输出位置分区，无需两次扫描。fp4 类型把低 4bit 复制成高 4bit 组成一字节填充值。

```cpp
int32_t inIndex2 = Index2 - left2; ...
if (inIndex2 >= 0 && inIndex2 < inShape2 && inIndex1 >= 0 && inIndex1 < inShape1 && inIndex0 >= 0 && inIndex0 < inShape0) {
    outputGM[idx] = inputGM[inIndex0 * inShape1 * inShape2 + inIndex1 * inShape2 + inIndex2];
} else { outputGM[idx] = fillValue; }
```

- 来源：`conversion/pad_v3/op_kernel/arch35/pad_simt.h`

#### K6. pad edge / reflect / symmetric：clamp 与 abs 无分支折叠公式

- 适用算子：pad_v3（edge / reflect / symmetric）
- 策略说明：edge 把越界坐标 `min(max(idx,0),shape-1)` 钳到边界；reflect/symmetric 用纯算术 abs 公式把任意 int 坐标折叠回 [0, shape)，完全无分支、线程间无分叉，非常适合 SIMT。

```cpp
// edge：inIndex[i] = min(max(inIndex[i] - left[i], 0), inShape[i] - 1);
// reflect / symmetric 折叠公式：
if constexpr (IS_REFLECT) {
    inIndex0 = abs(inIndex0) - abs(inIndex0 - (inShape0 - 1)) - inIndex0 + inShape0 - 1;
} else {
    inIndex0 = (abs(inIndex0*2 + 1) - abs((inIndex0 - (inShape0-1))*2 - 1)) / 2 - inIndex0 + inShape0 - 1;
}
```

- 来源：`conversion/pad_v3/op_kernel/arch35/pad_edge_simt.h`、`pad_mirror_simt.h`

#### K7. pad_v3_grad 常量模式：反向偏移 + 越界写 0（切片回写）

- 适用算子：pad_v3_grad（constant）
- 策略说明：前向 pad 的逆：每线程负责一个 grad_input 元素，`inIndex = outIndex + leftPad`，落在 padded 范围内则读回否则写 0。strides/shapes/leftPads 先搬到 UB 数组，高维模板减少 VF 参数个数。

```cpp
inIndex[0] = inIndex[0] + lefts[0];
if (inIndex[0] < 0 || inIndex[0] >= inShapes[0] || ...) { outputGM[idx] = 0; }
else { outputGM[idx] = inputGM[U(inIndex[0]) * inStrides[0] + U(inIndex[1])]; }
```

- 来源：`conversion/pad_v3_grad/op_kernel/arch35/pad_v3_grad_constant_simt.h`

#### K8. pad_v3_grad edge / replication：每线程一个输出点，按 scope 范围累加（scatter 转 gather）

- 适用算子：pad_v3_grad（edge/mirror/circular）、pad_v3_grad_replication
- 策略说明：edge 类 pad 的梯度是"多个 padded 位置映射到同一输入位置"，SIMT 把 scatter-add 转成 gather-sum：每线程负责一个 grad_input 元素，`CalScope` 算出该输入点在 padded 张量每维上的累加区间 `[scope[i][0], scope[i][1]]`（含左右 pad 与 clamp 折叠），多重循环累加（half/bf16 升 fp32），最后单次写回，**无需原子操作**。线程数随维度递减（2048→64）控制寄存器压力。

```cpp
for (uint8_t i = 0; i < DIM; i++) {
    U paddedPos = outIndex[i] + leftPads[i];
    if (outIndex[i] == 0) { scope[i][0] = 0; } else { scope[i][0] = paddedPos + flag; }
    if (outIndex[i] == outShapes[i] - 1) { scope[i][1] = paddedPos + rightPads[i]; } else { scope[i][1] = paddedPos - flag; }
}
CastType total = 0;
for (U a0 = scope[0][0]; a0 <= scope[0][1]; ++a0)
    for (U a1 = scope[1][0]; a1 <= scope[1][1]; ++a1)
        total += static_cast<CastType>(gradOutGM[a0 * paddedStrides[0] + a1]);
CopyOut<T, CastType>(idx, gradInGM, total);
```

- 来源：`conversion/pad_v3_grad_replication/op_kernel/arch35/pad_v3_grad_replication_edge_simt.h`

#### K9. diag / matrix_diag：先 UB 刷零写 GM，再 SIMT 只写对角线

- 适用算子：diag、matrix_diag
- 策略说明：输出 n×n 大部分为 0。向量核用 `Duplicate` 在 UB 造零块并 `DataCopyPad` 分段刷到 GM，`MTE3_V` 同步后 SIMT VF 每线程一个对角元按 `yIdx = xIdx*(n+1)`（批处理版先除出 batch）写入。写量从 n² 降到 n。

```cpp
for (uint32_t idx = threadIdx.x; idx < curCoreElements; idx += blockDim.x) {
    uint32_t xIdx = xBaseIdx + idx;
    uint32_t xDivVal = Simt::UintDiv(xIdx, magic0, shift0);
    uint64_t yIdx = (xIdx - xDivVal * nSize) * (nSize + 1) + xDivVal * (nSize * nSize);
    y[yIdx] = x[xIdx];
}
```

- 来源：`conversion/matrix_diag/op_kernel/arch35/matrix_diag_simt.h`

#### K10. diag_part：对角抽取 `idx*(N+1)` 一式地址

- 适用算子：math/diag_part、conversion/matrix_diag_part
- 策略说明：对角元地址就是 `idx * sideLen + idx`，无需除法。matrix_diag_part 支持 batch：UintDiv 分出 batchIdx 后 `inputOffset = batchIdx*matrixSize + diagIdx*inputRowStride`，按输出/输入规模选 uint32/uint64 索引。

```cpp
for (int64_t idx = startSideLen + threadIdx.x; idx < startSideLen + processNum; idx += blockDim.x) {
    outputGM[idx] = inputGM[idx * sideLen + idx];
}
```

- 来源：`math/diag_part/op_kernel/arch35/diag_part_simt.h`

#### K11. diag_flat / diag_v2：SIMT 内层填 UB + SIMD 外壳 DMA 混合流水

- 适用算子：diag_flat、diag_v2
- 策略说明：SIMT 不直接写 GM，而是向 UB buffer 写结果（diag_flat 用无分支 select：`doRead ? gmVal : 0`，每线程恒定写一次避免分叉），再通过队列与 `DataCopy` 整块 DMA 到 GM，兼顾离散计算与连续写出。

```cpp
uint64_t row = Simt::UintDiv(globalPos, outWidthMagic, outWidthShift);
uint64_t col = globalPos - row * outWidth;
bool onDiag = (static_cast<int64_t>(col) - static_cast<int64_t>(row) == diagonal);
bool doRead = onDiag && inRange;
yUb[pos] = doRead ? xGm[doRead ? inputIdx : 0] : static_cast<T>(0);
```

- 来源：`conversion/diag_flat/op_kernel/arch35/diag_flat_simd.h`

#### K12. im2col：卷积展开六维坐标逆映射 + padding 越界补 0

- 适用算子：im2col（NCHW / NHWC 两个 SIMT 模板）
- 策略说明：输出元素 6 维 (b, c, kh, kw, hOut, wOut)，每线程沿输出线性 index 用 4~5 级 UintDiv 逐级分解，再用 `imRow = hOut*hStride - padBefore + kH*dilation` 映射回输入坐标，越界写 0（等效隐式 padding）。

```cpp
U imRow = hOut * hStride - hPaddingBefore + kH * hDilation;
U imCol = wOut * wStride - wPaddingBefore + kW * wDilation;
if (imRow >= 0 && imRow < H && imCol >= 0 && imCol < W) { y[yIdx] = x[(batchAndChannel * H + imRow) * W + imCol]; }
else { y[yIdx] = 0; }
```

- 来源：`conversion/im2col/op_kernel/arch35/im2col_simt_NCHW.h`

#### K13. batch_to_space_nd：输出坐标 → (c, block 内/外坐标) 逆映射，SIMT 写 UB 再 DataCopyPad 连续落盘

- 适用算子：batch_to_space_nd
- 策略说明：每个输出元素：除 channel 得 c；对每个空间维先除输出形状得坐标、加 crops 还原、再除 blockShape 分出块内坐标与块号，块号按 bStride 累乘进 batch 维。SIMT 写入 UB（输出连续），外壳 `DataCopyPad` 整块写 GM——离散读、连续写。

```cpp
U tmp = Simt::UintDiv(yIdx, m0, s0); U cOut = yIdx - tmp * channel; yIdx = tmp; xIdx += cOut;
U indexDivH = yIdx - tmp * yShape1; indexDivH += crops0;
U xCol = Simt::UintDiv(indexDivH, m2, s2);
U indexDivB = indexDivH - xCol * bShape0;
xIdx += xCol * xStride; bIdx += indexDivB * bStride;
y[idx] = x[xIdx + yIdx * xStride + bIdx * xStride];
```

- 来源：`conversion/batch_to_space_nd/op_kernel/arch35/batch_to_space_nd_simt.h`

#### K14. concat：ListTensor 地址解析 + 每核轮询 tensor + 行内快速除法分列

- 适用算子：concat
- 策略说明：每核按 `tensorIdx = i*blockNum + blockIdx` 轮询多个输入 tensor；VF 内线程遍历该 tensor 的 `m*colsSize` 个元素，`__umulhi` 快速除分解 (row, col) 写到 `dst[row*n + col + colsOffset]`。tensor 地址用 `GetTensorSimtAddr` 从 ListTensorDesc 指针表解析。

```cpp
__simt_callee__ inline __gm__ T *GetTensorSimtAddr(uint16_t index, GM_ADDR tensorPtr)
{
    __gm__ uint64_t *dataAddr = reinterpret_cast<__gm__ uint64_t *>(tensorPtr);
    uint64_t tensorPtrOffset = *dataAddr;
    __gm__ uint64_t *retPtr = dataAddr + (tensorPtrOffset >> 3);
    return reinterpret_cast<__gm__ T *>(*(retPtr + index));
}
```

- 来源：`conversion/concat/op_kernel/arch35/one_axis_concat_simt.h`

#### K15. split_v：不等长逐输出分段拷贝与全局 chunk 描述符执行

- 适用算子：split_v
- 策略说明：基础模板对每个输出 tensor 单独发一次 VF：线程遍历该输出 `mLen × nCurLen` 元素，UintDiv 分解 row，`inputIndex = row*nLen + col + preSumN`。chunk 模板（204）把每 128 线程编为一个逻辑 block，从 UB 读取 7 字段描述符（bStart/bEnd/strideDiff/magic/shift/inAddr/outAddr），`threadIdx.x >> 7` 选 block、`& 127` 块内分工，实现跨输出全局均载。

```cpp
__ubuf__ uint64_t* b = e + (threadIdx.x >> 7) * CHUNK_PRE_UB_FIELD_PER_BLOCK;
int64_t bStart = (int64_t)b[0]; int64_t bEnd = (int64_t)b[1];
for (int64_t idx = bStart + (threadIdx.x & 127); idx < bEnd; idx += 128) {
    int64_t row = Simt::UintDiv<uint64_t>((uint64_t)idx, magic, shift);
    outBase[idx] = inBase[idx + row * strideDiff];
}
```

- 来源：`conversion/split_v/op_kernel/arch35/split_v_simt_chunk_pre.h`

#### K16. strided_slice：begin + strides 折叠的正/负步长统一地址合成

- 适用算子：strided_slice
- 策略说明：负步长不做特判——Init 时把动态 begin 读取并 clamp 到 [0, shape)，Process 把每维 `begin[i]*inputShapeProd[i+1]` 预累加成 beginSum、`strides[i]*inputShapeProd[i+1]` 预合成有效步长，VF 内 `inputIndex = beginSum + Σ stride_i * outCoord_i`，负 stride 自然纳入。shape 超 uint32 走 BigShape 版本（uint64 索引 + uint64 fastDiv 参数经 UB 传入）。

```cpp
for (uint32_t i = 0; i < inputDims - 1; i++) {
    beginSum += begin_[i] * tilingData_->inputShapeProd[i + 1];
    strideTmp[i] = tilingData_->strides[i] * tilingData_->inputShapeProd[i + 1];
}
// VF（Dim3）：
inputIndex += (begin0 + strides0 * outputIndex[0]) * inputShapeProd1;
inputIndex += (begin1 + strides1 * outputIndex[1]) * inputShapeProd2;
outputGM[idx] = inputGM[inputIndex];
```

- 来源：`conversion/strided_slice/op_kernel/arch35/strided_slice_simt.h`

#### K17. strided_slice_grad：dy 连续读入 UB，SIMT 按 begin/stride 散写回 GM

- 适用算子：strided_slice_grad
- 策略说明：输出先由 all_clear 模板清 0；CopyOut 阶段每核把本段 dy 用 `DataCopyPad` 连续搬进 UB，SIMT VF 每线程处理一个 dy 元素：`__umulhi` 逐维分解输出坐标，`dstIndex += (begin[k] + coord*strides[k]) * fusedOutputInnerShape[k]` 合成梯度地址后单点写回（slice 输出坐标与目标一一对应，无原子）。

```cpp
for (int32_t i = threadIdx.x; i < curLoopBlockNum; i += blockDim.x) {
    int32_t idx = blockIdx * normalCoreProcessNum + loopNum * normalLoopBlockNum + i;
    int64_t dstIndex = 0;
#pragma unroll
    for (int32_t k = (8 - inputDimNum); k <= DIM0; k++) {
        uint32_t t2 = __umulhi(idx, simtB32Local[k]) + idx;
        uint32_t newIndex = t2 >> simtB32Local[k + MAX_SUPPORT_DIM];
        dstIndex += ((simtB64Local[k + 8] + newIndex * simtB64Local[k + 16]) * simtB64Local[k + 24]);
        idx = idx - simtB64Local[k] * newIndex;
    }
    dstGm[dstIndex] = srcLocal[i];
}
```

- 来源：`conversion/strided_slice_grad/op_kernel/arch35/copy_out_simt.h`

#### K18. trans_data：ND↔fractal 的 (h, c1, padN, c0) 多级分解与补零

- 适用算子：trans_data
- 策略说明：ND→NZ 按输出线性 idx 依次 UintDiv 出 hIdx、c1Idx、nIdx、cIdx，`nIdx >= oriN || cIdx >= oriC` 时写 0（分形 padding）；NZ→ND 反向分解五层地址。magic/shift 对 padN*c0、c1*c0、c1、c0、padN 五个除数预计算。

```cpp
hIdx = Simt::UintDiv(idxU, mPNC, sPNC);
U c1Cnt = Simt::UintDiv(idxU, mPNC0, sPNC0);
U c1Idx = c1Cnt - Simt::UintDiv(c1Cnt, mC1, sC1) * c1;
...
if (nIdx >= oriN || cIdx >= oriC) { dst[idx] = T(0); }
else { dst[idx] = src[hIdx * oriNC + nIdx * oriC + cIdx]; }
```

- 来源：`conversion/trans_data/op_kernel/arch35/trans_data_with_simt.h`

#### K19. transpose 小 shape：输出驱动一维线程映射 + 逆 perm 步长合成

- 适用算子：transpose（SMALL_SHAPE，TilingKey=10001）
- 策略说明：每线程一个输出元素，先按输出维度从尾到头混合基分解，再用 `dstStride[d] = 输入在 perm 后第 d 维的步长` 加权合成输入地址——perm 信息被前置折叠进 dstStride，VF 内只剩乘加。GM→GM 直写（volatile 防重排），无 UB。

```cpp
// Process 内由 perm 预合成 dstStride
dstStride[i] = dstStrideTmp[permSize - 1 - tilingData_->perm[permSize - 1 - i]];
// VF（3 维）
uint32_t xIdx = inputIndex0 * dstStride0 + inputIndex1 * dstStride1 + inputIndex2 * dstStride2;
outputGM[coreOffset + idx] = inputGM[xIdx];
```

- 来源：`conversion/transpose/op_kernel/arch35/transpose_small_shape.h`

#### K20. view_copy：DMA 连续拷入 UB + SIMT 按 dstStride 散写 GM（读连续/写离散分工）

- 适用算子：view_copy（simt_dim1~dim8）
- 策略说明：源视图连续段走 ND-DMA/MoveAlign 进 UB（保证读带宽），写侧因 dst stride 不规则改由 SIMT 完成：每线程处理 UB 内一个元素，`__umulhi` 分解 UB 内多维坐标，同时累加 srcIndex（UB 内连续 stride）和 dstIndex（GM 上 ubDstStride）实现散写。

```cpp
for (uint32_t i = threadIdx.x; i < batchSize; i += blockDim.x) {
    uint32_t t2 = __umulhi(idx, magic0) + idx;
    uint32_t dim2Index = t2 >> shift0;
    srcIndex += (dim2Index * srcStrideDim2); dstIndex += (dim2Index * dstStrideDim2);
    ...
    dst[dstIndex] = src[srcIndex];
}
```

- 来源：`conversion/view_copy/op_kernel/arch35/view_copy_simt_dim3.h`

#### K21. roll：逐维 `(coord + shift) % shape` 循环移位

- 适用算子：roll
- 策略说明：每线程一个输入元素，沿各维 `coord = idx / strides[d]` 分解后，输出地址按 `(coord + shifts[d]) % shapes[d] * strides[d]` 累加（tiling 已把负 shift 归一），实现任意多维循环移位。维度少用 int64 直除，不用 magic。

```cpp
for (int64_t dim = 0; dim < dimNum; dim++) {
    int64_t curDimInputIndex = inputDimIndex / strides[dim];
    inputDimIndex = inputDimIndex % strides[dim];
    outputIndex += (curDimInputIndex + shifts[dim]) % shapes[dim] * strides[dim];
}
yGmAddr[outputIndex] = xGmAddr[inputIndex];
```

- 来源：`conversion/roll/op_kernel/arch35/roll_simt.h`

#### K22. ball_query：每线程一个查询点的近邻搜索

- 适用算子：ball_query
- 策略说明：grid-stride 遍历全部查询点（B×npoint），每线程：UintDiv 分解 `(m, b)`，读中心点坐标（half 升 float 防溢出），内层遍历 batch 全部 N 个点做距离判定 `d2==0 || (minR² ≤ d2 < maxR²)`，命中即顺序写 idx 并在达到 sampleNum 时提前 break；未命中写 0、不足 sampleNum 用首命中点填充。半径平方在 host 侧预计算。

```cpp
for (int32_t k = 0; k < N; ++k) {
    float d2 = dx*dx + dy*dy + dz*dz;
    if (d2 == 0.0f || (d2 >= minRadius2 && d2 < maxRadius2)) {
        if (cnt == 0) { firstResult = k; }
        idxBase[cnt] = k;
        if (++cnt >= sampleNum) { break; }
    }
}
```

- 来源：`conversion/ball_query/op_kernel/arch35/ball_query_simt.h`

#### K23. dynamic_stitch：三维线程块 + workspace 间接索引的稀疏 scatter

- 适用算子：dynamic_stitch
- 策略说明：两阶段。阶段一 DeduplicateIndices：对重复/非法目标 index 用 `asc_atomic_max` 在 workspace 保留"最后写入者"。阶段二 SimtDataCopy：按 `(x=tensor 数, y=元素, z=sliceSize)` 三维线程块协作，经 tensorCumsum 前缀和与 workspace 查表得目标 index 后拷贝整条 slice。

```cpp
int64_t workspaceIndex = tensorCumsum[tensorIndex] + index;
int32_t dstIndex = workspaceGmAddr[workspaceIndex];
if (dstIndex < 0) { continue; }
for (int32_t sliceIndex = threadIdx.z; sliceIndex < sliceSize; sliceIndex += blockDim.z) {
    yGmAddr[dstIndex * sliceSize + sliceIndex] = inputTensor[index * sliceSize + sliceIndex];
}
// 去重阶段：asc_atomic_max(deDuplicateIndices + dstIndex, dstValue);
```

- 来源：`conversion/dynamic_stitch/op_kernel/arch35/dynamic_stitch_scatter_simt.h`

#### K24. coalesce_sparse：ldcg/stcg 绕缓存 scatter + atomic_add 值聚合

- 适用算子：coalesce_sparse
- 策略说明：每线程处理 (unique 索引行 × 值分量) 扁平任务：indices 用 `asc_ldcg/asc_stcg`（绕 L1）拷到新位置；values 用 `asc_atomic_add` 聚合相同坐标的值。确定性模式改为"每线程负责一行 + 内层循环 valueSize"。

```cpp
for (uint64_t index = threadIdx.x; index < taskLen * valueSize; index += blockDim.x) {
    uint64_t outputIdx = *(uniqueIndices + (index / valueSize));
    asc_atomic_add(newValue + outputIdx * valueSize + index % valueSize, asc_ldcg(values + index));
}
```

- 来源：`conversion/coalesce_sparse/op_kernel/coalesce_sparse_simt.h`

#### K25. sparse_reshape：稀疏坐标 flatId 合成 + UintDiv 再分解

- 适用算子：sparse_reshape
- 策略说明：每线程一个非零元：先把输入多维坐标乘 inputStrides 合成 flatId，再对输出各维用预计算 uint64 magic/shift 逐维 UintDiv 拆出新坐标。identity reshape 直接拷贝跳过全部计算。

```cpp
for (int64_t i = blockIdx.x * blockDim.x + threadIdx.x; i < nnz; i += blockDim.x * gridDim.x) {
    int64_t flatId = 0;
    for (int32_t j = 0; j < inputRank; j++) { flatId += indices[i * inputRank + j] * inputStrides[j]; }
    for (int32_t j = 0; j < outputRank; j++) {
        int64_t quotient = Simt::UintDiv<uint64_t>(flatId, divMagic[j], divShift[j]);
        yIndices[i * outputRank + j] = quotient;
        flatId -= quotient * outputStrides[j];
    }
}
```

- 来源：`conversion/sparse_reshape/op_kernel/arch35/sparse_reshape_simt.h`

#### K26. matrix_set_diag_v2：k 序 × 行/列序的二维任务分解写对角线

- 适用算子：matrix_set_diag_v2
- 策略说明：cut-tail 场景把 UB 内矩形区域的对角线写入任务组织成 `(row, kOffset)` 二维循环，线程 UintDiv 分解后计算 `curK = endK - kOffset`、目标列 `gmXCol = gmXRow + curK`，越界（出 UB 矩形）直接 continue；写入目标是 UB，由外层 DMA 落 GM。

```cpp
U rowOffset = Simt::UintDiv(idx, magic, shift);
U kOffset = idx - rowOffset * kLen;
int32_t curK = endK - kOffset;
U gmXCol = gmXRow + curK;
if (gmXCol < startCol || gmXCol > endCol) { continue; }
x[curX] = diag[kOffset * maxDiagLen + (curK >= 0 ? gmXRow : gmXCol)];
```

- 来源：`conversion/matrix_set_diag_v2/op_kernel/arch35/matrix_set_diag_v2_simt.h`

#### K27. 高维模板的降参数技巧：tiling 经 GM 传入（GET_TILING_DATA_PTR_WITH_STRUCT）

- 适用算子：as_strided（Dim5-8）、pad_v3（Dim6-8）、strided_slice（Dim5-8/BigShape）、im2col
- 策略说明：SIMT VF 参数个数有限，维度 ≥5 时 shape/stride 数组参数放不下，改为只传 `GM_ADDR tiling`，VF 内用 `GET_TILING_DATA_PTR_WITH_STRUCT` 宏直接从 GM 读 tiling 结构体；magic/shift 等高频小参数仍走寄存器传参；VF 内需 UB 数组时用 `__ubuf__` 指针传 LocalTensor 物理地址。

```cpp
__simt_vf__ LAUNCH_BOUND(THREAD_NUM) inline void SimtStridedDim5(__gm__ T* inputGmAddr, __gm__ T* outputGmAddr,
                                                                 GM_ADDR tiling, uint32_t outputBasicIndex, uint32_t count, ...)
{
    GET_TILING_DATA_PTR_WITH_STRUCT(AsStridedSimtTilingData, tdGmPtr, tiling);
    ... inputCurIdx -= inputDimIdx[0] * tdGmPtr->outSizeStride[0]; ...
}
```

- 来源：`conversion/as_strided/op_kernel/arch35/as_strided_simt.h`

#### K28. SIMT 内层 + SIMD 外壳流水线的组合模式

- 适用算子：batch_to_space_nd、diag_flat、diag_v2、strided_slice_grad、view_copy
- 策略说明：当一侧访存天然连续、另一侧离散时，采用"连续侧走 DMA、离散侧走 SIMT"的混合结构，通过 `TQue`（AllocTensor/EnQue/DeQue）双缓冲流水化；同步用 `SetFlag/WaitFlag<HardEvent::S_V>`（标量写 UB→VF 读）和 `MTE3_V`（DMA→VF）。这是 arch35 上 SIMT 与 Vector/DMA 协同的标准范式。

```cpp
for (int64_t i = 0; i < ubLoopNum; ++i) {
    inTensorY_ = que_.AllocTensor<T>();
    asc_vf_call<SimtComputeDimOne<T, U>>(dim3(threadNum_), ..., (__ubuf__ T*)inTensorY_.GetPhyAddr());
    que_.EnQue(inTensorY_);
    DataCopyPad(yGm_[startIdx], que_.DeQue<T>(), copyOutParams);
    que_.FreeTensor(inTensorY_);
}
```

- 来源：`conversion/batch_to_space_nd/op_kernel/arch35/batch_to_space_nd_simt.h`

#### K29. 线程数常量分级：2048/1024/512/256/128/64 按算子寄存器压力选取

- 适用算子：全部 SIMT kernel
- 策略说明：arch35 单核最大 2048 线程；纯搬运/少变量用 2048（roll、pad、trans_data），坐标分解多变量用 1024（batch_to_space_nd、diag、concat），寄存器密集或 64 位索引用 512（as_strided、ball_query、sparse_reshape），pad_grad_replication 高维累加降到 64。`__DAV_FPGA__` 下统一降档到 512/256。

```cpp
#ifdef __DAV_FPGA__
constexpr uint32_t THREAD_NUM_LAUNCH_BOUND = 512;
#else
constexpr uint32_t THREAD_NUM_LAUNCH_BOUND = 2048;
#endif
```

- 来源：`conversion/pad_v3_grad_replication/op_kernel/arch35/pad_v3_grad_replication_edge_simt.h`、`conversion/im2col/op_kernel/arch35/im2col_simt_NCHW.h`

### 附：Conversion 类设计规律

1. **输出驱动的 gather 是 SIMT 主范式**：除 pad_grad 边缘模式（scatter→gather 转换）外，均按"每线程一个输出元素 → 逆向算输入地址"，写侧连续、读侧离散，避免写冲突与原子操作（仅 coalesce_sparse/dynamic_stitch 这类本质多对一场景用 atomic）。
2. **快速除法贯穿始终**：`GetUintDivMagicAndShift` + `Simt::UintDiv` / 手写 `__umulhi`；roll 是唯一例外（int64 直除，维度少）。
3. **模板爆炸式展开**：按维度数（Dim1~Dim8）、索引位宽（u32/u64）、线程数档位（64~2048）三轴编译期展开。
4. **SIMT 与其它模板协同**：SIMT 多作为小 shape/高维/负步长/不等长场景的兜底，或与 DMA 组成"连续侧 DMA + 离散侧 SIMT"混合流水线；选择依据集中在字节阈值、cacheline 对齐、负载偏斜三类指标。

---
## 六、随机数生成类（Random）

> 范围：`random/`（drop_out_v3、random_common、random_standard_normal_v2、random_uniform_int_v2、sim_thread_exponential、stateless_bernoulli、stateless_exponential、stateless_normal、stateless_random、stateless_random_choice_with_mask、stateless_randperm、stateless_sample_multinomial、stateless_truncated_normal_v2、stateless_uniform、truncated_normal_v2）。
> 总体架构：`random_common` 提供统一 Tiling 模板类（`RandomTilingArch35` + `OpTilingConfig` 回调式配置）与 Kernel 公共库（`random_kernel_base.h`：Philox4x32-10 计数器型 RNG、Box-Muller 变换、SIMT kernel 模板）；各算子仅声明 dtype/shape 校验规则、seed/offset 提取回调与 Transform 仿函数即可接入。

### Tiling 策略

#### T1. OpTilingConfig 回调式统一 Tiling 框架（双模式 SIMD/SIMT）

- 适用算子：几乎全部随机类算子
- 策略说明：公共基类 `RandomTilingArch35::DoTiling()` 固化 8 步流程，算子通过 `OpTilingConfig` 注入差异：输入/输出/属性校验、`getOutputSize`、`getKeyAndCounter`（SIMD 模式）、`getSeedAndOffset`（SIMT 模式）、`getBufferNum` 四个回调，以及 `kernelMode`、`coreAlignSize`、`unrollFactor`、`enableSplitBlocks` 开关。`kernelMode` 选择填充 `RandomUnifiedTilingDataStruct`（SIMD，携带 key/counter）或 `RandomUnifiedSimtTilingDataStruct`（SIMT，携带 seed/offset + 分块信息）。

```cpp
ge::graphStatus RandomTilingArch35::DoTiling()
{
    auto ret = CheckInputsOutputsAndAttrs();      // 步骤1
    ret = GetPlatformInfo();                       // 步骤2
    ret = BeforeProcess();                         // 步骤3
    ret = config_.kernelMode == RandomKernelMode::SIMD ? FillUnifiedTilingData() : FillUnifiedSimtTilingData();
    ret = CalcTilingKeyAndWorkspace();             // 步骤5
    ret = UniqueProcess(); ret = WriteBackToContext();
}
```

- 来源：`random/random_common/op_host/arch35/random_tiling_arch35.cpp`

#### T2. 统一分核策略（按输出元素数均分 + 对齐 + 尾核）

- 适用算子：random_common 框架下所有算子
- 策略说明：SIMD 模式按 `outputSize / totalCoreNum` 向上取整后按 coreAlignSize 对齐，保证每核最少 256 元素；usedCoreNum 反推，尾核单独记录，空 tensor 至少开 1 核。SIMT 模式同样按输出元素数分核。

```cpp
tilingData_.normalCoreProNum = Ops::Base::CeilDiv(tilingData_.outputSize, totalCoreNum_);
tilingData_.normalCoreProNum = CeilAlign(normalCoreProNum, config_.coreAlignSize);
tilingData_.normalCoreProNum = std::max(tilingData_.normalCoreProNum, MIN_CORE_PRO);  // 256
tilingData_.usedCoreNum = Ops::Base::CeilDiv(tilingData_.outputSize, tilingData_.normalCoreProNum);
tilingData_.usedCoreNum = std::max(1L, tilingData_.usedCoreNum); // 空tensor至少开1核
tilingData_.tailCoreProNum = outputSize - normalCoreProNum * (usedCoreNum - 1);
```

- 来源：`random/random_common/op_host/arch35/random_tiling_arch35.cpp`

#### T3. 种子展开为 Philox key/counter（seed→key、seed2→counter 高 64 位）

- 适用算子：random_standard_normal_v2、random_uniform_v2 等 SIMD 模式 attr 型种子算子
- 策略说明：`seed` 拆成 key[0..1]，`seed2` 填入 counter[2..3]，counter[0..1] 清零。`seed==0 && seed2==0` 时用 host 端 `std::mt19937_64`（纳秒时间戳 ⊕ 线程 id 哈希做种子）生成随机种子，实现"未指定种子则每次不同"。

```cpp
if (seed == 0 && seed2 == 0) { seed = static_cast<int64_t>(New64()); seed2 = static_cast<int64_t>(New64()); }
key[0] = static_cast<uint32_t>(seed);
key[1] = static_cast<uint32_t>(seed >> 32);
counter[2] = static_cast<uint32_t>(seed2);
counter[3] = static_cast<uint32_t>(seed2 >> 32);
```

- 来源：`random/random_common/op_host/arch35/random_tiling_base.h`

#### T4. 大张量 32bit 索引不可达时的递归对半切分（SplitBlocks）

- 适用算子：stateless_normal、stateless_uniform、stateless_random、sim_thread_exponential 等（`enableSplitBlocks=true`）
- 策略说明：SIMT kernel 内部用 32bit 索引寻址，当 numel 或最大字节偏移超 `INT32_MAX` 时，tiling 把输出张量按"跨度最大维度"递归对半切分（先去 size=1 维、合并连续维），直到每个子块 32bit 可索引，最多 8 块。每块记录 `numel/gmOffset/grid/totalThreads/kernelOffset`，kernel 侧逐块启动一次 VF。

```cpp
while (top > 0 && simtTilingData.splitBlockCount < MAX_SPLIT_BLOCKS) {
    TensorSliceState cur = stack[--top];
    if (cur.Is32bitIndexable()) {
        simtTilingData.splitBlocks[blockIdx] = {cur.numel, cur.gmOffset, ...};
    } else {
        int64_t dim = cur.GetDimToSplit();
        cur.PartitionDim(dim, other);
        stack[top++] = cur; stack[top++] = other;
    }
}
```

- 来源：`random/random_common/op_host/arch35/random_tiling_arch35.cpp`

#### T5. 每块 Philox counter 偏移预计算（kernelOffset 累加推进）

- 适用算子：同 T4
- 策略说明：保证"同一 (seed, offset) 无论是否分块都产生相同序列"：tiling 为每个 split block 预计算 Philox counter 增量——grid 按 `numel/256` capped 到 `78 簇 × 2048/256`，每轮 `totalThreads × unrollFactor` 个元素、每个 Philox 调用推进 counter 4 步，由轮数算出本块消耗的 counter 量累加到下一块 kernelOffset。kernel 侧把 `realOffset + kernelOffset` 传给 Philox 初始化。

```cpp
for (int64_t i = 0; i < splitBlockCount; i++) {
    int64_t grid = (numel + SIMT_THREAD_GROUP_SIZE - 1) / SIMT_THREAD_GROUP_SIZE;
    grid = std::min(grid, AIC_CLUSTER_COUNT * (MAX_THREADS_PER_AIC / SIMT_THREAD_GROUP_SIZE));
    int64_t roundsNeeded = CeilDiv(numel, grid * SIMT_THREAD_GROUP_SIZE * unrollFactor);
    splitBlocks[i].kernelOffset = accumulatedOffset;
    accumulatedOffset += roundsNeeded * MAX_PRNG_COUNTER_INCR;
}
```

- 来源：`random/random_common/op_host/arch35/random_tiling_arch35.cpp`

#### T6. stateless 系列 seed/offset 为 device tensor 时 tiling 填 0 占位

- 适用算子：stateless_uniform、stateless_normal、stateless_random、stateless_sample_multinomial 等
- 策略说明：seed/offset 是 GM 上的 tensor 输入，且常是上游算子在 device 上算出的中间结果，tiling 阶段 host 侧读其值会触发未映射页 fault。因此 `getSeedAndOffset` 回调直接填 0 占位，只完成形状相关 tiling；真实值由 kernel 运行时从 GM 读取并叠加 kernelOffset，既避免 host 读 device 内存，又保持 (seed, offset) 确定性语义。

```cpp
config.getSeedAndOffset = [](gert::TilingContext*, int64_t& seed, int64_t& offset) -> ge::graphStatus {
    seed = 0; offset = 0;   // 填0占位，kernel 运行时从 GM 读
    return ge::GRAPH_SUCCESS;
};
config.kernelMode = RandomKernelMode::SIMT;
config.enableSplitBlocks = true;
```

- 来源：`random/stateless_uniform/op_host/arch35/stateless_uniform_tiling_arch35.cpp`

#### T7. drop_out_v3 的 keep_prob 提取、offset 4 对齐校验与 mask workspace

- 适用算子：drop_out_v3
- 策略说明：offset 必须为 4 的倍数（对应 Philox 一组 4 输出）；keep_prob 输入（支持 double/fp32/fp16/bf16）转成 `prob = 1 - keep_prob` 写入 tilingData；mask 输出按 `CeilAlign(xSize, 128)/8` 字节校验，workspace 按 `CeilAlign(outputSize, 32)` 字节申请（SIMT 生成 0/1 字节 mask 后再由 SIMD 压成 bit）。

```cpp
if (offset % OFFSET_LIMIT != 0) { /* error: The offset must be a multiple of 4 */ }
prob = static_cast<float>(double(1) - pTensor->GetData<double>()[0]);
workspaceSize_ = Ops::Base::CeilAlign(outputSize, 32) * sizeof(uint8_t) + ascendcPlatform.GetLibApiWorkSpaceSize();
```

- 来源：`random/drop_out_v3/op_host/arch35/drop_out_v3_tiling_arch35.cpp`

#### T8. stateless_random 按取值范围动态选择 unrollFactor（int32/int64 双模式）

- 适用算子：stateless_random
- 策略说明：range ≥ 2^28 时按 int64 模式每输出消耗 2 个 Philox uint32（unrollFactor=2），否则 int32 模式每输出 1 个（=4）。该选择同时影响每块 counter 消耗量预计算和 kernel 取模路径，保证大 range 数值正确、小 range 吞吐翻倍。

```cpp
config_.unrollFactor = ((toData[0] - fromData[0]) >= RAND_INT64_THRESHOLD) ? UNROLL_2 : UNROLL_4;
simtTilingData_.extraInt64Param1 = config_.unrollFactor;
```

- 来源：`random/stateless_random/op_host/arch35/stateless_random_tiling_arch35.cpp`

#### T9. stateless_randperm 的 sort-by-key tiling（randomBits 估算 + Sort tiling 桥接）

- 适用算子：stateless_randperm
- 策略说明：洗牌采用"随机键排序 + 岛内 Fisher-Yates"。tiling 用公式 `randomBits = ceil(log2(n - 6n²/(12·ln0.9)))`（截断到 64）估计键位宽使冲突概率受控，按位宽把随机键压缩成 uint8/uint16/int32/int64 减少 radix 轮数；随后用 `OpTilingContextBuilder` 伪造 Sort 的 TilingContext，**直接调用 sort 算子的 SortTilingSimt 复用其 tiling**；n 超 int32 范围时按 2 的幂对半切子段，每段独立累加 counterOffset。

```cpp
randomBits_ = std::min(64, static_cast<int>(std::ceil(std::log2(nd - (6*nd*nd + 1) / (std::log(0.9) * 12)))));
if (randomBits_ <= 8) { randomDtype_ = ge::DT_UINT8; }
else if (randomBits_ <= 16) { randomDtype_ = ge::DT_UINT16; }
else if (randomBits_ <= 32) { randomDtype_ = ge::DT_INT32; } else { randomDtype_ = ge::DT_INT64; }
```

- 来源：`random/stateless_randperm/op_host/arch35/stateless_randperm_tiling_arch35.cpp`

#### T10. stateless_sample_multinomial 的 outputSize 换算与索引位宽选择

- 适用算子：stateless_sample_multinomial
- 策略说明：分核用的 size = `numDist × num_samples / 4`（每 counter 产 4 个随机数）；`from/range/extraInt64Param1` 字段复用传递 num_samples/numCategories/总数；`splitBlockCount` 借用为"是否用 uint64 索引"标记。

```cpp
int64_t realSize = numDist * (*numsamplesPtr);
size = (realSize + RANDOM_NUM_PER_COUNTER - 1) / RANDOM_NUM_PER_COUNTER;
simtTilingData_.splitBlockCount = (numDist * numCategories > UINT32_MAX || realSize > UINT32_MAX) ? 1 : 0;
```

- 来源：`random/stateless_sample_multinomial/op_host/arch35/stateless_sample_multinomial_tiling.cpp`

#### T11. stateless_random_choice_with_mask：按线程数分核与三段 workspace

- 适用算子：stateless_random_choice_with_mask
- 策略说明：分核按 `inputSize / 512` 向上取整 cap 到物理核数；workspace 三段：noZeroWorkspace（每线程非零计数及前缀和）、输出暂存、randomWorkspace（洗牌随机数）。seed/offset 从 const tensor 读取后 offset 放入 Philox counter 高 64 位。

```cpp
blockNum_ = Ops::Base::CeilDiv(inputSize_, THREAD_NUM);
if (blockNum_ > coreNum_) { blockNum_ = coreNum_; normalCoreProNum_ = Ops::Base::CeilDiv(inputSize_, blockNum_); }
workspace[0] = noZeroWorkspaceSize_ * INT64_SIZE + randomWorkspaceSize_ * 2 * INT32_SIZE + ...;
```

- 来源：`random/stateless_random_choice_with_mask/op_host/arch35/stateless_random_choice_with_mask_simt_tiling.cpp`

#### T12. truncated_normal_v2 按"线程组"分核与双种子兜底

- 适用算子：truncated_normal_v2（stateful）
- 策略说明：拒绝采样导致每输出消耗随机数不固定，无法按元素均分；按 `CeilAlign(outputSize, 4) / 512线程` 估算核数（每线程固定生成 4 个有效样本），seed/seed2 全 0 时 host RNG 兜底，复用 offset 字段传 seed2。

```cpp
int64_t threadNum = Ops::Base::CeilAlign(simtTilingData_.outputSize, THREAD_DISPOSAL_NUM);
int64_t coreNum = Ops::Base::CeilAlign(threadNum, MAX_THREAD_NUM);
simtTilingData_.usedCoreNum = std::min(coreNum, totalCoreNum_);
```

- 来源：`random/truncated_normal_v2/op_host/arch35/truncated_normal_v2_tiling_arch35.cpp`

### Kernel 策略

#### K1. Philox4x32-10 SIMT 实现（10 轮 feistel + key 自增）

- 适用算子：全部 SIMT 随机算子（random_common 公共库）
- 策略说明：单轮用 32×32→64 乘法拆高低位后异或 key，每轮 key 按 `PHILOX_W32_A/B` 自增，迭代 10 轮输出 4×uint32。性能要点：用 `__mul_i32toi64` 并 reinterpret 成 `uint2` 访问高低位（比 uint64 移位写法编译结果更优）；迭代在临时副本上进行不修改传入状态。

```cpp
__simt_callee__ __aicore__ inline void Philox4x32Round(uint32_t* counter, const uint32_t* key)
{
    uint64_t res0_u64 = __mul_i32toi64(PHILOX_M4X32_A, counter[0]);
    uint64_t res1_u64 = __mul_i32toi64(PHILOX_M4X32_B, counter[2]);
    // 使用uint2和uint32功能等价，但是编译器的编译结果不一样，性能差异很大，使用性能更好的uint2
    uint2& res0 = reinterpret_cast<uint2&>(res0_u64);
    uint2& res1 = reinterpret_cast<uint2&>(res1_u64);
    counter[0] = res1.y ^ counter[1] ^ key[0]; counter[1] = res1.x;
    counter[2] = res0.y ^ counter[3] ^ key[1]; counter[3] = res0.x;
}
```

- 来源：`random/random_common/op_kernel/arch35/random_kernel_base.h`

#### K2. 计数器快进原语 SkipLo / SkipHi / FlashCounter

- 适用算子：全部 SIMT 随机算子
- 策略说明：Philox 128bit counter 分两段：低 64 位承载 offset/组内推进（SkipLo），高 64 位承载全局线程号/子序列号（SkipHi），即 `counter = (globalThreadIdx << 64) | offset`，与 PyTorch/CUDA `philox_offset_per_thread` 语义对齐。`FlashCounter(threadIdx, offset)` 一次性定位任意线程的子序列起点，无需顺序迭代——**无状态并行的关键**。

```cpp
__simt_callee__ __aicore__ inline void SkipLo(uint32_t* counter, uint64_t n)
{
    counter[0] += (uint32_t)n;
    if (counter[0] < (uint32_t)n) { nhi++; }   // 手工进位链
    counter[1] += nhi;
    if (nhi <= counter[1]) return;
    if (++counter[2]) return;
    ++counter[3];
}
__simt_callee__ __aicore__ inline void FlashCounter(uint64_t globalThreadIdx, uint64_t offset, uint32_t* counter)
{
    SkipHi(counter, globalThreadIdx); SkipLo(counter, offset);
}
```

- 来源：`random/random_common/op_kernel/arch35/random_kernel_base.h`

#### K3. 每线程子序列初始化 PhiloxAlgParsInit（offset 按 4 对齐进 counter 低位）

- 适用算子：所有调用方
- 策略说明：seed 拆 key[0..1]；offset（单位"Philox 输出个数"）除以 4 换成 counter 组数经 SkipLo 加进 counter 低 64 位。tiling 要求 offset 为 4 的倍数（T7），保证不同调用边界不共享同一组 4 输出——这正是 stateless (seed, offset) 确定性语义的落点。

```cpp
__simt_callee__ inline void PhiloxAlgParsInit(uint32_t* key, uint32_t* counter, int64_t seed, int64_t offset)
{
    key[0] = (uint32_t)seed; key[1] = (uint32_t)(seed >> 32);
    offset = (offset + 3) / 4;
    SkipLo(counter, offset);
}
```

- 来源：`random/random_common/op_kernel/arch35/random_kernel_base.h`

#### K4. 线程↔输出元素映射 ThreadMappingAndSkip（连续/跨步双模式 + magic 快除）

- 适用算子：全部 SIMT 随机算子
- 策略说明：给定线性元素索引 i 反推"该组 4 个元素属于哪个线程的第几轮"：`globalThreadIdx = (i/STEP) % totalThreads`、`repeat = (i/STEP) / totalThreads`，然后 FlashCounter 定位 counter。两种布局：`CONTINUOUS_USE`（每线程连续 Vec 个元素，利于向量化写回）与 `DIS_CONTINUOUS_USE`（stride=totalThreads 跨步，随机性分布对齐 GPU）。除法用 magic/shift 快除。

```cpp
uint64_t idxTmp = idx / STEP;
uint64_t repeat = Simt::UintDiv(idxTmp, magic, shift);
if constexpr (ARANGE_MODE == CONTINUOUS_USE) { globalThreadIdx = idxTmp - repeat * totalThreads; }   // 0000 1111 ...
else { globalThreadIdx = idx - Simt::UintDiv(idx, magic, shift) * totalThreads; }                    // 0123 0123 ...
FlashCounter(globalThreadIdx, repeat, counter);
```

- 来源：`random/random_common/op_kernel/arch35/random_kernel_base.h`

#### K5. 通用 SIMT 模板 PhiloxSimtKernelDiscontinuous/Continuous + Transform 仿函数注入

- 适用算子：stateless_uniform（UniformTransform）、stateless_normal（NormalTransform）、stateless_random、exponential 系列
- 策略说明：公共库把"Philox 状态定位 + 循环 + 边界检查"固化成两个 `__simt_vf__` 模板 kernel，分布特有逻辑以 TransformFunc 仿函数注入：`transform(outputGm, li, results, iStep, randPerOutput)` 拿到第 li 个输出对应的 uint32 随机数自行变换。配合 `ProcessWithSplitBlocks` 逐块启动，tiling 分块对 kernel 透明。

```cpp
for (uint64_t loopIdx = 0; loopIdx < repeatTime; loopIdx++) {
    for (uint64_t linearIndex = idx; linearIndex < totalThreads; linearIndex += blockDim.x * gridDim.x) {
        uint32_t counterTmp[ALG_COUNTER_SIZE] = {0};
        CopyArray<ALG_COUNTER_SIZE>(counterTmp, counter);
        FlashCounter(linearIndex, loopIdx, counterTmp);
        uint32_t results[SIMT_STEP];
        PhiloxRandomSimt(key, counterTmp, results);
        for (uint32_t iStep = 0; iStep < UNROLL; iStep++) {
            uint64_t li = linearIndex + loopIdx * totalThreads * UNROLL + totalThreads * iStep;
            if (li < outputSize) { transform(outputGm, li, results, iStep, SIMT_STEP / UNROLL); }
        }
    }
}
```

- 来源：`random/random_common/op_kernel/arch35/random_kernel_base.h`

#### K6. stateless 确定性语义——kernel 运行时从 GM 读 seed/offset 并叠加 kernelOffset

- 适用算子：stateless_normal、stateless_uniform、stateless_random、stateless_exponential、stateless_sample_multinomial
- 策略说明：与 T6 配套：每个 AIC 核直接从 GM 读真实 seed/offset（此时上游已执行完毕），分块时把 tiling 预计算的块间 counter 增量 kernelOffset 加在 realOffset 之上。(seed, offset) 完全决定输出，与核数、分块数无关。

```cpp
int64_t realSeed = *(reinterpret_cast<__gm__ int64_t*>(seed));
int64_t realOffset = *(reinterpret_cast<__gm__ int64_t*>(offset));
Simt::VF_CALL<PhiloxSimtKernelDiscontinuous<T, NormalTransform<T>>>(
    Simt::Dim3(DEFAULT_SIMT_THREAD_NUM), gmPtr, realOffset_ + kernelOffset, seed_, ...);
```

- 来源：`random/stateless_normal/op_kernel/arch35/stateless_normal.h`

#### K7. Box-Muller 正态变换三件套（标量安全版 / torch 对齐版 / SIMD 向量版）

- 适用算子：random_common、stateless_normal、truncated_normal_v2、random_standard_normal_v2
- 策略说明：`BoxMullerFloatSafe` 对 u1 做 1e-7 下限钳制（对齐 TF），`BoxMullerFloat` 不钳制（对齐 torch）；`sincosf` 一条指令同时得 sin/cos。NormalTransform 中每对 Philox 输出 (u1,u2) 产出一对 (z0,z1)，按 iStep%2 取用，保证与 GPU 消耗随机数次序一致。

```cpp
__simt_callee__ inline void BoxMullerFloatSafe(float u1, const float u2, float* z0, float* z1)
{
    if (u1 < 1.0e-7f) { u1 = 1.0e-7f; }
    float v = 2.0f * PI * u2;
    float r = sqrtf(-2.0f * logf(u1));
    sincosf(v, z0, z1);
    *z0 *= r; *z1 *= r;
}
```

- 来源：`random/random_common/op_kernel/arch35/random_kernel_base.h`

#### K8. uint32 → float/half/bf16 的 IEEE754 尾数拼接（免除法归一化）

- 适用算子：random_common 公共库（SIMD 通路）
- 策略说明：不用乘除法做归一化，直接位操作：`u & 0x7fffff | (127<<23)` 拼出 [1,2) 的 float 位型再减 1.0 得 [0,1)；half 用 10bit 尾数、bf16 用 7bit 尾数。全程 `Reg::` 向量寄存器流水。标量版 `Uint32ToFloat` 逻辑相同。

```cpp
// (u & 0x7fffff) | (127 << 23) → [1,2) float；减 1.0 → [0,1)
Reg::And<int32_t, ZEROING>(vReg2, vReg0, vReg1, mask);
Reg::Or<int32_t, ZEROING>(vReg4, vReg2, vReg3, mask);
Reg::Adds<float, float, ZEROING>(vReg6, (RegTensor<float>&)vReg4, sReg4 /*-1.0f*/, mask);
```

- 来源：`random/random_common/op_kernel/arch35/random_kernel_base.h`

#### K9. drop_out_v3 的 keep_prob 掩码生成（SIMT 生成字节 mask + SIMD 压 bit）

- 适用算子：drop_out_v3
- 策略说明：阶段一 SIMT：每线程 Vec(2/4/8/16，按 outputSize 整除性选取) 个元素，Philox 均匀数 `< p` 得 mask bit，同时 `y = x * fMaskBit * (1/p)` 原地缩放；mask 按每元素 1 字节写 workspace。阶段二 SIMD：对字节 mask 做 `CompareScalar(==1)` 得 bit 图，`DataCopyPad` 按 8 元素/字节写回 GM。`p==0` 走快路径。

```cpp
uint8_t maskBit = (resultsAll[iVec] < p) ? 1 : 0;
outputGM[linearIndex + iVec] = inputGM[linearIndex + iVec] * fMaskBit * scale;
maskGM[linearIndex + iVec] = maskBit;
// SIMD 侧：AscendC::CompareScalar(maskOut, maskIn, 1, CMPMODE::EQ, countAlign256); DataCopyPad(...);
```

- 来源：`random/drop_out_v3/op_kernel/arch35/drop_out_v3_impl.h`

#### K10. random_standard_normal_v2 的 SIMD+SIMT 混合与 offset 状态回写

- 适用算子：random_standard_normal_v2（stateful）
- 策略说明：每核先按 `normalCoreProNum * blockIdx / 4` 用 Skip 快进 counter 到本核起点；UB 内用 SIMD `PhiloxRandom<10>` 批量产均匀数，再 `asc_vf_call<SimtBoxMuller>`（512 线程）在 UB 上原地 Box-Muller；最后 cast 目标 dtype 写出。末尾最后一个核把 `offset += outputSize * 256` 写回 GM 并刷 cache，实现 stateful 推进。

```cpp
auto blockOffSet = tiling_->normalCoreProNum * blockIdx_;
RandomKernelBaseOp::Skip(blockOffSet / RESULT_ELEMENT_CNT);
PhiloxRandom<10>(yOutputTmp, {key_[0], key_[1]}, {counter_[0], ...}, uniformResCount);
asc_vf_call<SimtBoxMuller>(dim3{USED_THREAD}, (__ubuf__ float*)(yOutputTmp.GetPhyAddr()), uniformResCount);
if (blockIdx_ == tiling_->usedCoreNum - 1) {
    offsetGm_(0) = offsetGm_(0) + tiling_->outputSize * K_Reserved_Per_Output;
    DataCacheCleanAndInvalid<int64_t, CacheLine::SINGLE_CACHE_LINE, DcciDst::CACHELINE_OUT>(offsetGm_);
}
```

- 来源：`random/random_standard_normal_v2/op_kernel/arch35/random_standard_normal_v2.h`

#### K11. random_uniform_int_v2 的防溢出取模（b/2 + (b-b/2) 拆加法）

- 适用算子：random_uniform_int_v2
- 策略说明：均匀整数映射 `res = lo + philox % range`。为避免 int32 下 `lo + b` 溢出，把 b 拆成 `b>>1` 与 `b-(b>>1)` 两次加。

```cpp
UINT_T b = randomRes - (randomRes / range) * range;
UINT_T b_div_2 = b >> 1;
yOutput[index] = low + static_cast<T>(b_div_2) + static_cast<T>(b - b_div_2);
```

- 来源：`random/random_uniform_int_v2/op_kernel/arch35/random_uniform_int_v2.h`

#### K12. stateless_random_choice_with_mask 的计数-前缀和-抽取-洗牌流水线

- 适用算子：stateless_random_choice_with_mask
- 策略说明：五步混合流水：(1) 每线程扫一段 bool 统计 true 个数写 workspace；(2) 单线程串行前缀和 + block0 用 SIMD DataCopyGather/Scatter 做 32×32 块向量化前缀和；(3) 按前缀和把 true 元素扁平索引写到输出槽位并置 mask，多余槽位补 0/false；(4) SIMD Philox 批量生成洗牌随机数（offset 放 counter 高 64 位）；(5) 单线程 Fisher-Yates 洗牌，多维输入用 SplitDim（magic 快除）拆成多维坐标。

```cpp
counter_[2] = static_cast<uint32_t>(tiling_->offset);        // offset 放 counter 高 64 位
counter_[3] = static_cast<uint32_t>(tiling_->offset >> 32);
for (int32_t idx = outputNonzeroCount - 1; idx > 0; idx--) {
    uint32_t randomIdx = workspaceRandomData[idx] % static_cast<uint32_t>(idx);
    swap(outputGM[idx], outputGM[randomIdx]);
}
```

- 来源：`random/stateless_random_choice_with_mask/op_kernel/arch35/stateless_random_choice_with_mask.h`

#### K13. stateless_randperm 的 sort-by-key 洗牌（随机键 + 基数排序 + 岛内 Fisher-Yates）

- 适用算子：stateless_randperm
- 策略说明：并行 Fisher-Yates 的正确性方案：(1) Philox kernel 给每个下标生成 randomBits 位随机键（位宽由 T9 公式保证碰撞可控），线程子序列定位用 `StateIncrHi(counter, tid)`（counter 高 64 位装线程号，与 CUDA `curand_init(seed, subsequence, offset)` 同构）；(2) 调 sort 算子按随机键稳定排序下标；(3) 找排序后键值相同的"岛"，每个岛内由发现岛的线程做串行 Fisher-Yates 消除同键非均匀性；(4) cast 到输出 dtype。

```cpp
if ((y1WorkSpace_[tid] & mask) != (y1WorkSpace_[tid + 1] & mask)) continue;
if (tid != 0 && ((y1WorkSpace_[tid] & mask) == (y1WorkSpace_[tid - 1] & mask))) continue;
int islandSize = 0;
do { islandSize++; } while (同键);
RandInit(state, tid, offset, key, counter, last);
for (int j = islandSize - 1; j > 0; j--) {
    Rand1(state, key, counter, results, last);
    T r = results % (j + 1);
    if (j != r) { swap(indexWorkSpace_[dataOffset + j], indexWorkSpace_[dataOffset + r]); }
}
```

- 来源：`random/stateless_randperm/op_kernel/arch35/stateless_randperm.h`

#### K14. stateless_sample_multinomial 的 CDF 二分搜索采样（每样本独立子序列）

- 适用算子：stateless_sample_multinomial
- 策略说明：输入 x 是各行 CDF。每线程处理 4 个样本，magic 快除拆 `(d, s)`；子序列号 `subsequence = d * samplesAligned + s`（samplesAligned 按 128 对齐保证行内/行间 counter 不重叠）装 counter 高 64 位，offset/4 装低 64 位——TF 语义 `counter = (offset, subsequence)`。每次 Philox 取 counter[0] 转 (0,1] 均匀数，CDF 行内二分找首个 `>= u` 的类别，跳过零概率类/平台，末尾钳到 numCat-1。

```cpp
uint64_t subsequence = static_cast<uint64_t>(d) * samplesAligned + s;
uint32_t counterTmp[4] = {baseOffsetLo, baseOffsetHi, (uint32_t)subsequence, (uint32_t)(subsequence >> 32)};
PhiloxRandomSimt(key, counterTmp, counterTmp);
XT u = counterTmp[0] * RAND_2POW32_INV + RAND_2POW32_INV_HALF;
while (end > start) { IndexT mid = start + ((end - start) >> 1); if (x[mid] < u) { start = mid + 1; } else { end = mid; } }
```

- 来源：`random/stateless_sample_multinomial/op_kernel/arch35/stateless_sample_multinomial_impl.h`

#### K15. truncated_normal 的拒绝采样与每线程 256 预留配额

- 适用算子：truncated_normal_v2、stateless_truncated_normal_v2
- 策略说明：拒绝采样下每输出消耗 Philox 次数不定，无法用静态映射。改用"每线程独立配额"：线程 groupIndex 的 counter 区域起点为 `groupIndex * 256`，线程在自己配额内反复 Philox→BoxMullerFloatSafe→保留 |z|<2 的样本直到攒满 4 个。确定性由"线程号→固定 counter 区间"保证。stride 必须用运行时真实线程数 `gridDim.x*blockDim.x` 而非 tiling 估算值（否则输出留空洞）。stateful 版最后把 `offset += outputNum*256` 回写 GM。

```cpp
SkipLo(counterThread, groupIndex * RESERVED_SAMPLES_PER_OUTPUT);   // 256
while (validCount < GROUP_SIZE) {
    PhiloxRandomSimt(key, counterThread, philoxOut);
    SkipOne(counterThread);
    BoxMullerFloatSafe(Uint32ToFloat(philoxOut[0]), Uint32ToFloat(philoxOut[1]), &z0, &z1);
    if (fabsf(z0) < TRUNCATE_VALUE) { results[validCount++] = z0; }
}
```

- 来源：`random/stateless_truncated_normal_v2/op_kernel/arch35/stateless_truncated_normal_v2_simt.h`

#### K16. stateless_bernoulli 的双概率模式与 32/64bit 索引模板分派

- 适用算子：stateless_bernoulli
- 策略说明：编译期 PROB_MODE 区分标量概率（读 probGm[0]）与逐元素概率张量（读 probGm[i+j]），Philox 均匀数 `<= prob` 输出 1 否则 0，覆盖 12 种输出 dtype。按 outputSize 选 uint32/uint64 索引模板，对齐 CUDA bernoulli 分块方式保证数值一致。

```cpp
RandomKernelBase::ThreadMappingAndSkip<STEP, CONTINUOUS_USE>(i, counter, magic, shift, totalThreads);
RandomKernelBase::PhiloxRandomSimt(key, counter, results);
for (uint8_t j = 0; j < 4; ++j) {
    float probFp32 = (PROB_MODE == PROB_SCALAR) ? float(probGm[0]) : float(probGm[i + j]);
    outGm[i + j] = results[j] <= probFp32 ? 1 : 0;
}
```

- 来源：`random/stateless_bernoulli/op_kernel/arch35/stateless_bernoulli_simt.h`

#### K17. exponential 的 -log(u)/λ 变换与边界保护

- 适用算子：sim_thread_exponential、stateless_exponential（复用同一 Transform）
- 策略说明：Transform 仿函数最小示例：uint32 转 (0,1] 均匀数 u，逆变换 `x = -log(u)/λ`；`u >= 1-ε/2` 时钳到 `-ε/2` 避免 log(1)=0 异常。stateless 版与 sim 版差别仅在种子来源（GM 读 + kernelOffset），体现"变换与状态管理解耦"。

```cpp
struct ExponentialTransform {
    __simt_callee__ inline void operator()(__gm__ volatile T* outputGm, uint64_t li, const uint32_t* results, uint32_t iStep, ...)
    {
        float u = results[iStep] * RAND_2POW32_INV + RAND_2POW32_INV_HALF;
        float logVal = (u >= 1.0f - halfEpsilon_) ? -halfEpsilon_ : AscendC::Simt::Log(u);
        outputGm[li] = static_cast<T>(-1.0f / lambda_ * logVal);
    }
};
```

- 来源：`random/sim_thread_exponential/op_kernel/arch35/sim_thread_exponential_simt.h`

#### K18. stateless_uniform 的 CUDA 对齐边界翻转（value==to 时折回 from）

- 适用算子：stateless_uniform
- 策略说明：对标 CUDA `_curand_uniform4`：随机数取 (0,1]，映射 `value = rand*(to-from)+from` 后若恰等于 to 则折回 from，保证输出 ∈ [from, to) 且与 CUDA 逐位一致。half/bf16 路径先在低精度下算 range/from 再提升 float 计算、降回并做同样边界判断，模拟 GPU 的多次舍入次序。

```cpp
float value = rand * range + from_;
if (value == to_) { value = from_; }
outputGm[li] = value;
```

- 来源：`random/stateless_uniform/op_kernel/arch35/stateless_uniform.h`

#### K19. stateless_random 的 int64 拼接取模

- 适用算子：stateless_random
- 策略说明：int64 模式下每输出消耗相邻 2 个 uint32 拼成 uint64（results[iStep*2] 为高 32 位）再对 range 取模；int32 模式直接用 1 个。randPerOutput 由模板传入，保证 counter 推进与 tiling 预计算一致。

```cpp
if constexpr (RangeMode == RANGE_MODE_INT64) {
    uint64_t randU64 = (static_cast<uint64_t>(results[iStep * 2]) << 32) | results[iStep * 2 + 1];
    outputGm[li] = static_cast<T>(randU64 % range_ + from_);
} else { outputGm[li] = static_cast<T>(results[iStep] % range32 + from_); }
```

- 来源：`random/stateless_random/op_kernel/arch35/stateless_random_impl.h`

### 附：随机类设计脉络

1. **分层复用**：random_common 把种子展开、分核/分块/counter 预计算、Philox 快进、SIMT 循环模板全部公共化；算子只写"校验规则 + Transform 仿函数"。
2. **确定性三条路线**：索引可静态映射的（uniform/normal/bernoulli/dropout）用 `counter = (threadIdx 高64) | (offset/4 低64)`；stateless + device 种子用 tiling 填 0 + kernel 读 GM 叠加 kernelOffset；消耗不定长的（拒绝采样）用每线程 256 组配额独占 counter 区间。
3. **性能要点**：magic/shift 快除；uint2 reinterpret 优化 Philox 单轮；IEEE754 尾数拼接替代浮点除法做 U(0,1)；CONTINUOUS_USE 布局 + 每线程 Vec 连续元素实现对齐向量化 store；Sort/前缀和等重逻辑桥接复用 sort 算子。

---
## 七、索引收集类（Gather/Index）

> 范围：`index/` 下 gather_v2、gather_nd、gather_elements、embedding、embedding_bag、reverse_sequence、reverse_v2、masked_scatter、masked_scatter_with_position、sparse_slice、sparse_to_dense、unique_dim、linear_index_v2、index、index_fill、inplace_index_add、inplace_index_fill、inplace_sub、inplace_update。
> 公共模式：整除普遍用 `GetUintDivMagicAndShift` 预计算 magic/shift，VF 内 `Simt::UintDiv` 快速除法。

### Tiling 策略

#### T1. 尾轴字节数决定 SIMT/SIMD 模板选择（gather_v2 核心分流）

- 适用算子：gather_v2
- 策略说明：形状折叠为 `[batch, outer, gatherDim, inner]`。尾轴 `innerSize * dtypeSize` 达到 SIMD 阈值（通用 2048B，B8=218 / B16=360 / B32=620，按 dtype 取最严）且 gather 行数足以喂饱半核数时走 SIMD 向量搬运；否则（尾轴小、访存离散）走 SIMT（每线程一个输出元素）。依据：SIMD 按 32B block 批量搬尾轴连续块才有收益，低于阈值时向量搬运的 padding/对齐开销大于收益。

```cpp
const static int64_t SIMD_TWO_DIM_THRES = 2048;
const static int64_t SIMD_B8_THRES = 218;  // B16=360, B32=620
bool Gatherv2TilingBase::IsSimdTwoDim()
{
    bool isTwoDim = batchSize_ == 1 && outerSize_ == 1;
    bool isSimd = (innerSize_ * improveDtypeSize_ >= SIMD_TWO_DIM_THRES || (按 dtype 收紧)) &&
                  batchSize_ * outerSize_ * gatherSize_ >= aivNum_ / 2;
    return isTwoDim && isSimd;
}
if (IsSimdTwoDim()) { tilingMode_ = TILING_SIMD_TWO_DIM; return SimdTwoDimTiling(); }
if (IsSimtTwoDim()) { tilingMode_ = TILING_SIMT_TWO_DIM; return SimtTwoDimTiling(); }
```

- 来源：`index/gather_v2/op_host/arch35/gather_v2_tiling.cpp`

#### T2. 尾轴 dtype 提升（XDtypeImprove）扩大拷贝粒度

- 适用算子：gather_v2、embedding、gather_nd、index
- 策略说明：若尾轴字节数可被 8/4/2 整除，把小 dtype "提升"为 B64/B32/B16 搬运，减少每行拷贝的元素数与地址计算次数；提升后再参与 T1 的阈值判定，直接影响 SIMT/SIMD 分流。

```cpp
int64_t Gatherv2TilingBase::XDtypeImprove()
{
    int64_t lastAxisBytes = innerSize_ * xDtypeSize;
    if (xDtypeSize < INPUT_DTYPE_B64 && lastAxisBytes % INPUT_DTYPE_B64 == 0) { improveDtypeSize_ = INPUT_DTYPE_B64; ... }
    if (xDtypeSize < INPUT_DTYPE_B32 && lastAxisBytes % INPUT_DTYPE_B32 == 0) { ... }
    ...
}
```

- 来源：`index/gather_v2/op_host/arch35/gather_v2_tiling.cpp`

#### T3. SIMT 线程数自适应收缩 + 按输出元素总数分核

- 适用算子：gather_v2、embedding、index_fill 等
- 策略说明：线程数默认 2048，当 `CeilDiv(ySize, threadNum) < aivNum/2`（核数利用不足一半）时线程数减半，最低 64/128；每核处理量向上对齐到 threadNum 整数倍保证 warp 满发射；`ySize < threadNum` 只用 1 核。

```cpp
int32_t threadNum = MAX_THREAD_NUM;   // 2048
while (threadNum >= 2 * SMALL_CASE_THREAD_NUM && CeilDiv(ySize_, threadNum) < aivNum_ / 2) {
    threadNum = threadNum / 2;
}
perCoreElements = (perCoreElements + threadNum - 1) / threadNum * threadNum;
needCoreNum_ = CeilDiv(ySize_, perCoreElements);
```

- 来源：`index/gather_v2/op_host/arch35/gather_v2_tiling.cpp`

#### T4. 全载类模板前置判定（UB 容量 / vgather 上界 / bank 冲突规避）

- 适用算子：gather_v2、gather_nd
- 策略说明：走 SIMT 之前先尝试更优的 UB 驻留模板：(a) `LAST_GATHER`：innerSize==1 且 gatherDim 整列可入 UB 且支持 vgather；(b) `GA_ALL_LOAD`：`gatherDim × 尾轴` 全量入 UB，要求尾轴字节在 (32, 2048)、`gatherSize/gatherDimSize > 1`（有重复读才划算），对齐后恰为 256B/128B 时额外加一个 ubBlock **规避 gather bank 冲突**。优先级高于 SIMT。

```cpp
if (aSizeAligned == SIMD_VECTOR_REG || aSizeAligned == SIMD_VECTOR_REG / 2) {
    aSizeAligned += ubBlockSize;      // 规避 gather bank 冲突
}
if (aSize <= WARP_THREAD_NUM || aSize >= SIMD_THRES) { return false; }
return batchSize_ == 1 && gatherSize_ / gatherDimSize_ > 1 && remainSpace >= 0;
```

- 来源：`index/gather_v2/op_host/arch35/gather_v2_tiling.cpp`

#### T5. embedding 的 SIMT 唯一模板选择

- 适用算子：embedding
- 策略说明：embedding 仅支持二维；"非 SIMD 大尾轴"全部走 SIMT_TWO_DIM（`innerSize*dtype >= 2048 且 gatherSize >= 32` 的反面），否则报错。分核/线程数逻辑同 T3。

```cpp
bool EmbeddingTilingBase::IsSimtTwoDim()
{
    bool isTwoDim = batchSize_ == 1 && outerSize_ == 1;
    bool isSimd = innerSize_ * improveDtypeSize_ >= SIMD_TWO_DIM_THRES && gatherSize_ >= RATIO_THRES;
    return isTwoDim && (!isSimd);
}
```

- 来源：`index/embedding/op_host/arch35/embedding_tiling_simt.cpp`

#### T6. embedding_bag 按 embeddingDim 字节数选 SIMT，1D/2D 分 tiling key

- 适用算子：embedding_bag
- 策略说明：`embeddingDim * weightTypeSize <= 512` 时置 isSimt（小 embedding 行聚合访存离散）；有 offsets 走 1D（key=300），无 offsets 走 2D（key=400）；mode（sum/mean/max）写入 tilingData 供 kernel 分发。

```cpp
if (embeddingDim_ * weightTypeSize_ <= MAX_SIMT_EMBDDING_BYTES /*512*/) { isSimt_ = 1; }
tilingKey = (isNeedOffset_ == 1 ? TILING_KEY_SIMT_1D : TILING_KEY_SIMT_2D);
```

- 来源：`index/embedding_bag/op_host/embedding_bag_regbase_tiling.cpp`

#### T7. gather_nd 的 GaAllLoad 前置过滤

- 适用算子：gather_nd
- 策略说明：SIMT 模板恒 capable 兜底，之前先判 GaAllLoad：每核 indices 数大于 gatherDimSize（重复读≥2 才值得全载）、rank ≤ 3、indices 必须 int32、尾轴在 (32,2048)。

```cpp
if (indicesNum_ / coreNum_ <= gatherDimSize_) { return false; }
if (rank_ > K_THRES) { return false; }
if (indicesDtypeSize_ != INPUT_DTYPE_B32) { return false; }
```

- 来源：`index/gather_nd/op_host/arch35/gather_nd_tiling_arch35.cpp`

#### T8. masked_scatter 两阶段调度：先掩码前缀和、SyncAll、再 SIMT 散布

- 适用算子：masked_scatter
- 策略说明：按 `xEleNums/totalCoreNum` 均分核；workspace = 每核计数槽 + 每元素前缀和槽。第一阶段每核对本核 mask 做 UB 内前缀和并把"本核 true 总数"写到 `maskSumGm[blockIdx]`，`SyncAll()`；第二阶段归约前序各核 maskSum 得 `preCoreMaskSum_` 再启动 SIMT。低比特 dtype 数据经 UB 中转。

```cpp
normalCoreData_ = std::max(Ops::Base::CeilDiv(xEleNums_, totalCoreNum_), MIN_DATA_SIZE);
workspaceSize_ = ASCENDC_TOOLS_WORKSPACE + usedCoreNum_ * maskDataTypeSize + xEleNums_ * maskDataTypeSize;
```

- 来源：`index/masked_scatter/op_host/arch35/masked_scatter_tiling_arch35.cpp`

#### T9. masked_scatter_with_position 的 AB/BA 广播模式识别

- 适用算子：masked_scatter_with_position
- 策略说明：仅支持 mask 与 x 呈 `(M,1)→(M,N)`（AB）或 `(1,N)→(M,N)`（BA）两种广播；tiling key 按 `PATTERN × BASE + int64mask` 区分；position 尾部为 0 时 kernel 直接返回。

```cpp
uint64_t tilingKey = TILING_KEY_BASE * (isBA_ ? PATTERN_BA : PATTERN_AB) + (isInt64Mask_ ? PATTERN_INT64 : PATTERN_INT32);
```

- 来源：`index/masked_scatter_with_position/op_host/masked_scatter_with_position_tiling.cpp`

#### T10. index_fill 的 SIMT 遍历空间二选一（indices 稀疏度）

- 适用算子：index_fill、inplace_index_fill
- 策略说明：x 折叠为 `[P, N, Q]`。x 很小（< 256B）或 `indicesNum <= n/5`（稀疏）时遍历空间取 `indicesNum * P * Q`（只写被命中行）；否则先建 n 大小 0/1 掩码再遍历 `n * P * Q`。核数 `min(coreNum, numel/threadNum)`，不足半核降 threadNum。

```cpp
simtComputeMode_ = (numel * dtypeSize < 256 || indicesNum <= N / 5) ? SIMT_COMPUTE_MODE_BY_INDICES : SIMT_COMPUTE_MODE_BY_N;
```

- 来源：`index/index_fill/op_host/arch35/index_fill_tiling_simt.cpp`

#### T11. inplace_index_add 模板选择：重复度排序 / SIMT / 确定性

- 适用算子：inplace_index_add（inplace_index_fill 同构）
- 策略说明：`updatesInAxis/varInAxis >= THRESHOLD_USE_SORT`（重复度高）时用"先排序再累加"规避原子加；排序路径再按 `afterAxis <= 1024` 与 dtype 决定 SIMT-sort 或 SIMD-sort；重复度低按 afterAxis 大小选 SIMD/SIMT-no-sort（原子加）；Deterministic 时直接走确定性模板。

```cpp
bool useSort = (updatesInAxis_ / varInAxis_ >= THRESHOLD_USE_SORT);
bool useSortSimt = useSort && afterAxis_ <= SIMT_SORT_LASTDIM_LIMIT;
if (context_->GetDeterministic() == 1 && 支持dtype) { isDeterminstic_ = 1; return; }
```

- 来源：`index/inplace_index_add/op_host/arch35/inplace_index_add_base_tiling.cpp`

#### T12. inplace_update / inplace_sub 按行（N 轴）均分分核

- 适用算子：inplace_update、inplace_sub
- 策略说明：var 视作 `[n, rowSize]`，`perCoreN = CeilDiv(n, coreNum)`；每核负责连续行区间，indices 指向本核区间才执行更新——**并发安全由分核保证而非原子指令**。

```cpp
perCoreN = CeilDiv(n, coreNum);
needCoreNum = CeilDiv(n, perCoreN);
context->SetBlockDim(needCoreNum);
```

- 来源：`index/inplace_update/op_host/arch35/inplace_update_tiling_arch35.cpp`

#### T13. sparse_to_dense 双核组分工：default 填充核 + sparse 写核

- 适用算子：sparse_to_dense
- 策略说明：两组核数分别计算：`defaultValueUsedCoreNum` 负责先 Duplicate 填默认值；`sparseUsedCoreNum` 负责按 indices scatter 真实值；默认值填充覆盖全部输出时 `isNeedSyncall_=true`，kernel 内 SyncAll 保证先填后写。

```cpp
defaultValueUsedCoreNum_ = std::min(totalCoreNum_, CeilDiv(outSize_, MIN_THREAD_NUM));
isNeedSyncall_ = numValues_ == 0 ? false : true;
```

- 来源：`index/sparse_to_dense/op_host/sparse_to_dense_tiling.cpp`

#### T14. sparse_slice 按 nnz 均分到核再到线程

- 适用算子：sparse_slice
- 策略说明：`usedCoreNum = CeilDiv(valueNumbers, valuePerCore)`，尾核单独记；kernel 内把本核 nnz 段均分给线程，每线程标记切片窗口内非零元，块内 SIMT 前缀和 + 跨块 workspace 归约定位输出位置。

```cpp
tilingParams.usedCoreNum = (valueNumbers + valuePerCore - 1) / valuePerCore;
tilingParams.valuePerTail = ...;
```

- 来源：`index/sparse_slice/op_host/arch35/sparse_slice_tiling_arch35.cpp`

#### T15. reverse_sequence SIMT 分核：按总元素均分，最小 128 元素/核

- 适用算子：reverse_sequence
- 策略说明：SIMT 模板（优先级第 9，另有多种 UB 模板按轴位置择优）按 `xShapeSize/coreNum` 均分，下限 128；UB 预留 128K DCACHE 与 256B 快除参数区；每核把分片搬入 UB，SIMT 在 UB 内写回反转结果。

```cpp
perCoreHandleNums_ = std::max(CeilDiv(xShapeSize, coreNum), MIN_UB_SIZE /*128*/);
usedCoreNums_ = CeilDiv(xShapeSize, perCoreHandleNums_);
```

- 来源：`index/reverse_sequence/op_host/arch35/reverse_sequence_simt_tiling.cpp`

#### T16. reverse_v2：尾轴反转且尾轴字节 ≥128 走 SIMD，否则 SIMT 按 dim 数模板化

- 适用算子：reverse_v2
- 策略说明：反转维含尾轴且尾轴字节 ≥128 走 SIMD 反转；否则 SIMT，形状合并到 ≤8 维，按维度数（1~8）与反转轴奇偶性实例化 kernel；每维 stride 与 7 组 fast-div magic/shift 经 31 个 SIMT 参数槽（UB 512B）传给 VF。

```cpp
constexpr int64_t SIMD_THRESHOLD = 128;
if (reversedDims_[reverseDimNum - 1] == dimNum_ - 1 || inputShape_[dimNum-1] * dtypeSize_ < SIMD_THRESHOLD) { /* SIMT */ }
```

- 来源：`index/reverse_v2/op_host/arch35/reverse_v2_tiling_arch35.cpp`

#### T17. index（高级索引）SIMT tiling：dtype 提升到 B128 + 模板注册

- 适用算子：index
- 策略说明：`IndexSimtTiling` 以优先级 30 注册；尾轴 dtype 可提升到 B128/B64/B32/B16；收集每个索引维的 `indexList/indexedShape/indexedDimStride` 与非索引维 stride，按索引维是否连续选择两套 kernel，预计算 fast-div 参数。

```cpp
if (dataTypeBytes < DTYPE_SIZE_B128 && lastDimSize % DTYPE_SIZE_B128 == 0) { return DTYPE_SIZE_B128; }
REGISTER_OPS_TILING_TEMPLATE(Index, IndexSimtTiling, 30);
```

- 来源：`index/index/op_host/arch35/index_tiling_arch35.cpp`

#### T18. unique_dim 的 workspace 分区（排序缓冲/标志位/前缀和）

- 适用算子：unique_dim
- 策略说明：按 N（dim 轴长度）划分 workspace：排序索引、sortBuf、flags（相邻差分标志）各 N×4B，64B 对齐；多阶段 SIMT 流水线（排序→相邻差分→核内扫描→跨核前缀→scatter/gather）全部在 workspace 原地推进，配 `__builtin_cce_dcci` 保证 GM 一致性。

```cpp
sortBufOffset_ = CeilAlign(N * IDX_SIZE, ALIGNMENT);
flagsOffset_ = CeilAlign(sortBufOffset_ + N * IDX_SIZE, ALIGNMENT);
```

- 来源：`index/unique_dim/op_host/op_tiling/unique_dim_tiling_arch35.cpp`

#### T19. embedding_no_contiguous 独立模板：stride 显式下传 + 按 shape×stride 判 int64

- 适用算子：embedding（no_contiguous 模板）
- 策略说明：非连续输入（x 或 indices 带 stride）走独立模板：`IsCapable` 要求 `(!xContiguous || !indicesContiguous) && 二维`；tiling 把各维 stride 显式下传（不再假设紧凑布局）；int64 判定必须用 `shape[i] * stride[i] > INT32_MAX`（而非 shape 本身），因为非连续张量的最大地址由 stride 决定。tilingKey = `100 + enableInt64*10 + xDtypeSize`，int64 路径线程数减半。

```cpp
bool IsCapable() { return (!xContiguous || !indicesContiguous) && xDims == 2 && indicesDims == 2; }
tilingData.xDim0Stride = GetInputStride(x, 0); ...
bool enableInt64 = false;
for (i in dims) { if (shape[i] * stride[i] > INT32_MAX) { enableInt64 = true; } }
tilingKey = 100 + enableInt64 * 10 + xDtypeSize;   // int64 时线程数减半
```

- 来源：`index/embedding/op_host/arch35/embedding_no_contiguous_tiling.cpp`

### Kernel 策略

#### K1. "每线程一个输出元素"的间接寻址 gather（多维分解 + 负回绕 + 越界填 0）

- 适用算子：gather_v2（SIMT 通用路径）
- 策略说明：线程对本核输出区间步进；对每个输出下标用 3 组 magic/shift 分解出 `(batchI, outerI, gatherI, innerI)` → 读 indices → 负索引加 gatherDimSize 回绕（模板参 NIS 控制，无负索引场景零开销）→ 计算源地址 → 越界写 0。地址宽度 int32/int64 模板化。

```cpp
for (INDEX_SIZE_T index = threadIdx.x; index < currentCoreElements; index += blockDim.x) {
    INDEX_SIZE_T yIndex = yIndexBase + index;
    INDEX_SIZE_T tmp = Simt::UintDiv(yIndex, m0, shift0);
    INDEX_SIZE_T tmp1 = Simt::UintDiv(tmp, m1, shift1);
    INDEX_SIZE_T gatherI = tmp - tmp1 * gatherSize;
    INDEX_SIZE_T batchI = Simt::UintDiv(tmp1, m2, shift2);
    INDEX_SIZE_T innerI = yIndex - tmp * innerSize;
    INDICES_T indicesValue = indices[batchI * gatherSize + gatherI];
    if constexpr (NIS) { if (unlikely(indicesValue < 0)) { indicesValue += gatherDimSize; } }
    INDEX_SIZE_T xIndex = (tmp1 * gatherDimSize + indicesValue) * innerSize + innerI;
    bool idxOutOfBound = indicesValue < 0 || indicesValue >= gatherDimSize;
    y[yIndex] = idxOutOfBound ? 0 : x[xIndex];
}
```

- 来源：`index/gather_v2/op_kernel/arch35/gather_v2.h`

#### K2. 二维特化 SIMT gather：一次除法定位行，尾轴线性偏移

- 适用算子：gather_v2（SIMT_TWO_DIM）、embedding（同构）
- 策略说明：二维场景只需 1 次 UintDiv 分解 `yIndex = gatherI*innerSize + innerI`，同行内 innerI 连续——**同一 warp 覆盖尾轴连续块，行内连续、行间离散，SIMT 最适合的形态**。尾轴拷贝粒度由 dtype 提升放大到 8B。

```cpp
INDEX_SIZE_T gatherI = Simt::UintDiv(yIndex, m0, shift0);
INDEX_SIZE_T innerI = yIndex - gatherI * innerSize;
y[yIndex] = idxOutOfBound ? 0 : x[indices[gatherI] * innerSize + innerI];
```

- 来源：`index/gather_v2/op_kernel/arch35/gather_v2_simt_two_dim.h`

#### K3. embedding 的免检 SIMT gather

- 适用算子：embedding
- 策略说明：与 K2 同构但去掉负回绕与越界判断（embedding 语义保证 indices 在词表内），单 VF 无分支：`xIndex = indices[gatherI]*innerSize + innerI`——间接寻址模式的最简形态。

```cpp
INDEX_SIZE_T xIndex = static_cast<INDEX_SIZE_T>(indices[gatherI]) * innerSize + innerI;
y[yIndex] = x[xIndex];
```

- 来源：`index/embedding/op_kernel/arch35/embedding_simt_two_dim.h`

#### K4. gather_nd SIMT：rank 循环累乘求源地址 + UB 暂存输出

- 适用算子：gather_nd
- 策略说明：indices 分片搬入 UB，SIMT 结果先写 UB 输出块再 DataCopyPad 连续写出（写合并）；每线程处理一个输出元素：分解出 indicesCurrentIdx 与尾轴偏移，对 rank 个索引分量循环"负回绕 + 越界检查 + `srcIdx = srcIdx*shape[i] + index`"累乘；越界写 0。

```cpp
for (uint8_t i = 0; i < rank; i++) {
    T2 index = src1Tensor[indicesCurrentIdx * rank + i];
    if (index < 0) { index += inputShape[i]; }
    if (index >= inputShape[i] || index < 0) { idxOutOfBound = true; break; }
    srcIdx = srcIdx * inputShape[i] + index;
}
if (idxOutOfBound) { SetOutOfBoundValue<T1>(dstTensor, idx); }
else { dstTensor[idx] = src2Tensor[srcIdx * lastDimSize + gatherAxisIdx]; }
```

- 来源：`index/gather_nd/op_kernel/arch35/gather_nd_simt.h`

#### K5. embedding_bag 1D：bag×chunk 二维线程网格，bag 内串行聚合

- 适用算子：embedding_bag
- 策略说明：线程块二维：x 维对应 embeddingDim 特征列，y 维 + blockIdx 遍历 `numBags * chunkPerBag` 个 chunk；每线程对本 bag 的 `[offsets[bag], offsets[bag+1])` 行串行累加 `weights[indices[e]*embeddingDim + featureDim]`，paddingIdx 行置 0 且不计入 bagSize；featureDim==0 的线程顺带写 offset2bag；mean 除以有效 bagSize。

```cpp
COMP_T bag = Simt::UintDiv(chunk, magic, shift);
COMP_T begin = (bag == 0 ? 0 : offsets[bag]);
COMP_T end = (bag < numBags - 1 ? offsets[bag + 1] : numIndices);
for (COMP_T embedIdx = begin; embedIdx < end; embedIdx++) {
    bool pad = (indices[embedIdx] == paddingIdx);
    W weightValue = weights[featureDim + indices[embedIdx] * embeddingDimSize];
    weightValue = pad ? 0 : weightValue;
    weightSum += static_cast<float>(weightValue);
    eachBagSize += pad ? 0 : 1;
}
y[bag * embeddingDimSize + featureDim] = static_cast<W>(weightSum);
```

- 来源：`index/embedding_bag/op_kernel/arch35/embedding_bag_regbase_1d_simt.h`

#### K6. embedding_bag max 模式与 2D 模式

- 适用算子：embedding_bag
- 策略说明：max 模式初始化 `maxVal = begin==end ? 0 : -inf`（空 bag 输出 0、maxIdx=-1），循环内更新并记录 maxIndices；2D 模式把 indices 视作定长 bag（`begin = bag*indicesSize`），均值除以有效（非 pad）行数。

```cpp
W maxVal = begin == end ? 0 : negInf;
if (eachBagSize == 0 || weightValue > maxVal) { if (!pad) { maxIdx = indices[embedIdx]; maxVal = weightValue; } }
if (eachBagSize == 0) { maxVal = 0; }
```

- 来源：`index/embedding_bag/op_kernel/arch35/embedding_bag_regbase_1d_simt.h`

#### K7. reverse_v2：对称索引 `idx = dim - idx - 1` + 维度模板展开

- 适用算子：reverse_v2
- 策略说明：每线程一个输出元素，7 组 magic/shift 分解 8 维坐标，仅对反转维做镜像（反转轴规整到奇偶位，`isReverse` 模板参区分两组），再按 stride 重组源地址。dim1~8 各特化避免循环开销；dim ≤2 用 2048 线程，否则 1024。

```cpp
idx0 = Simt::UintDiv(idx, magic0, shift0); y1 = idx - idx0 * param0;
idx1 = Simt::UintDiv(y1, magic1, shift1); ...
if constexpr (isReverse) { idx0 = dim0 - idx0 - 1; idx2 = dim2 - idx2 - 1; ... }
inputIdx = idx0 * param0 + idx1 * param1 + ... + idx7;
output[idx] = input[inputIdx];
```

- 来源：`index/reverse_v2/op_kernel/arch35/reverse_v2_simt.h`

#### K8. reverse_sequence：逐元素查 seqLengths 的动态对称反转

- 适用算子：reverse_sequence
- 策略说明：4 组 fast-div 分解坐标；按 batchDimIdx 读该行反转长度 reverseNum（截断到 seqDim）；`seqDimIdx < reverseNum` 的元素从对称位置 `(reverseNum - seqDimIdx - 1) * reverseSize + ...` 读，否则原样拷贝——变长反转由每元素独立判断完成，无线程间协作。

```cpp
CompType reverseNum = min(seqGm[batchDimIdx], seqDim);
if (seqDimIdx < reverseNum) {
    outLocal[i] = xGm[(reverseNum - seqDimIdx - 1) * reverseSize + seqIdx * seqDim * reverseSize + reverseSizeMod];
} else { outLocal[i] = xGm[xOffset]; }
```

- 来源：`index/reverse_sequence/op_kernel/arch35/reverse_sequence_simt.h`

#### K9. masked_scatter：SIMD VF 前缀和 + SIMT 消费定位第 k 个 true

- 适用算子：masked_scatter
- 策略说明：第一阶段纯 SIMD（MicroAPI）：bool mask unpack 成 int32，列内+行间两段式前缀和在 UB 完成，加滚动基址后经 GM workspace 落盘；SyncAll 后每核归约前序核 maskSum；第二阶段 SIMT 每线程查 `prefixSumGm[i] + preCoreMaskSum_` 即"全局第 k 个 true"，从 updates[k] 取值。

```cpp
// SIMT 侧：
for (int64_t i = threadIdx.x; i < curCoreHandleData; i += blockDim.x) {
    if (maskGm[i] == 0) { yGm[i] = xGm[i]; }
    else { yGm[i] = updatesGm[prefixSumGm[i] + preCoreMaskSum]; }
}
```

- 来源：`index/masked_scatter/op_kernel/arch35/masked_scatter.h`

#### K10. masked_scatter_with_position：直接读 position（前缀和）定位

- 适用算子：masked_scatter_with_position
- 策略说明：position 输入本身即掩码前缀和（外部算好），单趟 SIMT：AB 模式 `prefixSum = (position[row]-1)*xInner + col`；BA 模式 `prefixSum = position[col]-1 + row*position[xInner-1]`（行基址 = 行号 × 每行 true 总数）。

```cpp
// AB: prefixSum = (positionGm[rowidx] - 1) * xInner + colidx;
// BA: prefixSum = positionGm[colidx] - 1 + rowidx * positionGm[xInner - 1];
xGm[i] = updatesGm[prefixSum];
```

- 来源：`index/masked_scatter_with_position/op_kernel/masked_scatter_with_position.h`

#### K11. sparse_slice：线程标记 + SIMT 块内前缀和 + 跨块归约 + 紧凑写出

- 适用算子：sparse_slice
- 策略说明：两遍 VF。第一遍：nnz 均分到线程，逐非零元判是否在切片窗口内打标并计数，Hillis-Steele 双缓冲 `asc_syncthreads` 算块内前缀和，块和写 GM；第二遍：归约前序块和得块基址，加线程级前缀得每线程写出起点，按标记紧凑写出 yIndices（减 start 偏移）与 yValues。

```cpp
SimtComputePrefixSum<int64_t>(tmpValNum);   // 块内
int64_t addrThreadOut = tmpValNumBlock[0] + addrThreadOffset;
for (...) {
    if (tmpValBlock_[i]) {
        for (int64_t j = 0; j < rankNum; j++) { yIndices[addrThreadOut * rankNum + j] = indices[i*rankNum+j] - start[j]; }
        yValues[addrThreadOut] = values[i + startNNZ];
        addrThreadOut += 1;
    }
}
```

- 来源：`index/sparse_slice/op_kernel/arch35/sparse_slice_simt_local.h`

#### K12. sparse_to_dense：坐标逐维乘 stride 求线性偏移后 scatter

- 适用算子：sparse_to_dense
- 策略说明：default 核组先 Duplicate 填默认值；SyncAll 后 SIMT 每线程一个稀疏条目：从末维起累乘 stride 得线性地址写值（isScalar 写 values[0]）。写冲突（重复坐标）由"后者覆盖"语义容忍。

```cpp
COMP_T outputIdx = indices[idx * numDims + numDims - 1];
COMP_T strides = 1;
for (int i = numDims - 2; i >= 0; i--) {
    strides *= outputShape[i + 1];
    outputIdx += indices[idx * numDims + i] * strides;
}
y[outputIdx] = values[idx];
```

- 来源：`index/sparse_to_dense/op_kernel/arch35/sparse_to_dense_simt.h`

#### K13. index_fill：掩码标记 + 双遍历空间的 SIMT 填充

- 适用算子：index_fill、inplace_index_fill
- 策略说明：BY_INDICES（稀疏）：遍历 `indicesNum*P*Q`，分解 `(sliceId, pIdx, qOffset)`，nIdx 负回绕 + 越界 skip，写 `y[pIdx*n*q + nIdx*q + qOffset] = value`（同 nIdx 重复写同值无害）。BY_N（稠密）：先 VF 建 `mask[n]=1`（ZeroMemory + SyncAll），再遍历 `n*P*Q` 按掩码填。均不依赖原子。

```cpp
COM_T sliceId = Simt::UintDiv(i, magic, shift);
COM_T innerId = i - sliceId * slice_size;
nIdx = nIdx >= 0 ? nIdx : nIdx + n;
if (nIdx < 0 || nIdx >= n) { continue; }
COM_T pIdx = Simt::UintDiv(innerId, magic_q, shift_q);
y[pIdx * n * q + nIdx * q + (innerId - pIdx * q)] = value;
```

- 来源：`index/index_fill/op_kernel/arch35/index_fill_simt.h`

#### K14. inplace_index_add：asc_atomic_add 并发安全，低比特 dtype workspace 升精度

- 适用算子：inplace_index_add
- 策略说明：遍历 updates 全量，两次 fast-div 分解 `(dim0, dim1, dim2)`，读 indices 得目标行，`asc_atomic_add` 累加（WITH_ALPHA 先乘 alpha）。int8/uint8/int16 无原子加：先把 var 全量 Cast 到 int32/fp16 workspace → SyncAll → SIMT 对 workspace 原子加 → SyncAll → Cast 回原 dtype，三段式保证精度与正确性。

```cpp
COMP_T varOffset = dim0Idx * varStride0 + indices[dim1Idx] * afterAxis + dim2Idx;
if constexpr (int8/uint8) { asc_atomic_add(varWorkspaceGm + varOffset, static_cast<CAST_T>(updates[i])); }
else { asc_atomic_add(var + varOffset, updates[i]); }
// Process: CopyVarToWs() -> SyncAll() -> SimtCompute -> SyncAll() -> CopyWsToVar()
```

- 来源：`index/inplace_index_add/op_kernel/arch35/inplace_index_add_simt.h`

#### K15. inplace_update / inplace_sub：拷贝-覆写两阶段行更新（分核隔离免原子）

- 适用算子：inplace_update、inplace_sub
- 策略说明：每核负责 `[startRow, endRow)` 行区间。Phase1 线程把 x 行区间拷到 y；Phase2 串行扫 k 个 indices，仅当目标行落在本核区间时线程并行覆写/累减该行。同一行只归属一个核，多核并发无写冲突，无需原子；inplace_sub 对负索引 `%n` 归一化。

```cpp
for (int64_t idx = startElem + threadIdx.x; idx < endElem; idx += THREAD_NUM) { y_gm[idx] = x_gm[idx]; }
for (int32_t kIdx = 0; kIdx < k; kIdx++) {
    int32_t dstRow = indices_gm[kIdx];
    if (dstRow >= startRow && dstRow < endRow) {
        for (int64_t offset = threadIdx.x; offset < innerSize; offset += THREAD_NUM) {
            y_gm[dstRow * innerSize + offset] = v_gm[kIdx * innerSize + offset];
        }
    }
}
```

- 来源：`index/inplace_update/op_kernel/arch35/inplace_update_simt.h`

#### K16. index（高级索引）：索引维连续/非连续两套 SIMT 寻址

- 适用算子：index
- 策略说明：索引维相邻：输出下标 i 两级 fast-div 分解，`secondLoop` 同时索引 Dim 个 indexList（广播语义），各 curIdx 负回绕后乘 indexedDimStride 累加；索引维被非索引维隔开：外循环分解出 outLoopIdx 读索引，余数按 NoneIndexedDim 融合 stride 逐级分解。`#pragma unroll` 展开维度循环。

```cpp
T2 secondLoopIdx = Simt::UintDiv(remLength, m_[1], shift_[1]);
T2 thirdLoopIdx = remLength - thirdLoopLength_ * secondLoopIdx;
#pragma unroll
for (uint16_t j = 0; j < Dim; ++j) {
    int64_t curIdx = localIndexList[j][secondLoopIdx];
    if (curIdx < 0) { curIdx += localIndexedShape[j]; }
    inputIndex += curIdx * localIndexedDimStride[j];
}
inputIndex += thirdLoopIdx;
```

- 来源：`index/index/op_kernel/arch35/index.h`

#### K17. gather_elements：按 dim 数模板展开的轴替换寻址

- 适用算子：gather_elements
- 策略说明：index 与输出同形状，线程遍历输出下标 i，读 indexVal，用 fast-div 分解各维坐标后仅将 AXIS 维坐标替换为 indexVal 重组源地址（AXIS 为编译期模板参）；dim1 直连 `x[index[i]]`；线程数随 dim 数降低（2048→512）控制寄存器压力。

```cpp
U indexVal = indexAddr[i];
U dim0Index = Simt::UintDiv(i, magic, shift);
U dim1Index = i - dim0Index * indexStride;
if constexpr (AXIS == 0) { yAddr[i] = xAddr[indexVal * xStride + dim1Index]; }
else { yAddr[i] = xAddr[dim0Index * xStride + indexVal]; }
```

- 来源：`index/gather_elements/op_kernel/arch35/gather_elements.h`

#### K18. linear_index_v2：多索引张量的线性地址逐张量累加

- 适用算子：linear_index_v2
- 策略说明：输出先 Duplicate(0) 到 UB，再对每个有效索引张量调一次 VF：每线程读 indexValue，按 valueSize 负回绕 `((v % size + size) % size)`，乘 stride 后**累加**进 UB 输出缓冲——多个 Fancy 索引合成一个线性偏移。

```cpp
for (int64_t i = threadIdx.x; i < calcNum; i += blockDim.x) {
    T indexValue = indexAddr[i];
    outputUbAddr[i] += static_cast<T>(((indexValue % valueSize + valueSize) % valueSize) * stride);
}
```

- 来源：`index/linear_index_v2/op_kernel/arch35/linear_index_v2_simt.h`

#### K19. unique_dim：排序 + 相邻差分 + 分核扫描的多阶段 SIMT 流水线

- 适用算子：unique_dim
- 策略说明："排序后相邻比较"。各阶段独立 VF，阶段间 `__syncthreads` + `__builtin_cce_dcci`：Phase0 生成 [0,N)；排序后 Phase3 相邻差分打 flags（按 rowLen 逐元素比较前后两行）；Phase4 每核 thread0 串行 inclusive scan 写 partialSum，跨核前缀后广播回写；最后按前缀和位置紧凑写出 unique 行、inverse 索引与 counts。非 dim 轴先转置成 `[dk, outer, inner]` 再处理。

```cpp
// Phase 3: flags[i] = (row[indices[i-1]] != row[indices[i]]) ? 1 : 0;
// Phase 4: thread0 串行 inclusive scan
if (tid == 0) {
    int64_t runningSum = 0;
    for (int64_t i = 0; i < coreLen; i++) { runningSum += flags[coreStart + i]; flags[coreStart + i] = runningSum; }
    partialSum[coreId * psStride] = runningSum;
}
```

- 来源：`index/unique_dim/op_kernel/arch35/unique_dim_simt.h`

#### K20. unique_dim 排序阶段的 merge-path 并行归并

- 适用算子：unique_dim
- 策略说明：排序采用 merge-path 并行归并：每线程对"合并对角线"二分找分区点（O(log n)），分区内顺序归并（O(n/K)，保稳定性）；UB tile 双缓冲轮转；跨核用 `SimtMergePathPair` 配对归并 + `__builtin_cce_dcci` 显式刷缓存。比逐元素插入排序在大 N 下更优。

```cpp
int64_t diag = threadIdx.x * partitionSize;
int64_t p = BinarySearchPartition(diag, a, b);      // merge-path 分区二分
SequentialMerge(a + pA, b + pB, out + diag, len);   // 分区内顺序归并（保稳定）
// 跨核 SimtMergePathPair 配对归并 + __builtin_cce_dcci 显式刷缓存
```

- 来源：`index/unique_dim/op_kernel/arch35/unique_dim_simt_sort.h`

#### K21. embedding_no_contiguous 两遍协作（UB 做核内聚合）

- 适用算子：embedding（no_contiguous）
- 策略说明：strided indices 直接逐线程访问 GM 会导致同一 cache line 被反复穿行。改为两遍：第一遍线程级把 strided indices 按 `i * indicesDim1Stride` 搬进 UB 致密化，`asc_syncthreads()` 后第二遍按 magic 快除读 UB 做 gather；x 侧按 stride 寻址（`indicesUb[gatherI] * xDim1Stride + innerI`）。

```cpp
// 第一遍: strided indices → UB 致密化
for (i = tid; i < indicesNum; i += blockDim.x) { indicesUb[i] = indicesGm[i * indicesDim1Stride]; }
asc_syncthreads();
// 第二遍: 按快除读 UB 做 gather
uint32_t gatherI = Simt::UintDiv(index, m0, shift0);
y[yIndex] = x[indicesUb[gatherI] * xDim1Stride + innerI];
```

- 来源：`index/embedding/op_kernel/arch35/embedding_simt_no_contiguous.h`

### 附：Gather/Index 类共性小结

1. **SIMT/SIMD 分流第一判据是"尾轴连续块字节数"**：gather_v2/embedding（2048B，按 dtype 收紧）、embedding_bag（512B）、reverse_v2（128B）——连续块够大走 SIMD，离散小颗粒走 SIMT 一线程一元素。
2. **整除消除**：`GetUintDivMagicAndShift` + `Simt::UintDiv` / `__umulhi` 替代硬件除法。
3. **负索引回绕与越界**三种形态：模板参 NIS 编译期消除（gather_v2/gather_nd）、`((v%n)+n)%n` 归一化（linear_index_v2）、越界填 0 或 skip（gather_v2/index_fill）。
4. **并发安全**三路线：原子加（inplace_index_add）、行区间分核隔离（inplace_update/sub）、排序合并重复索引；低比特 dtype 用 workspace 升精度三段式。
5. **前缀和定位**是 masked_scatter/sparse_slice/unique_dim 的公共骨架：块内扫描 → 跨块归约 → 加基址紧凑写出。

---
## 八、索引散布类（Scatter）

> 范围：`index/` 下 scatter、scatter_add、scatter_elements(_v2)、scatter_max_with_argmax、scatter_nd(_add/_sub/_update)、scatter_nd_common、scatter_non_aliasing_add、scatter_reduce_common、scatter_update、inplace_scatter_add。
> 总体格局：**Tiling 按 updates/indices/输出三种粒度分核并选择模板（SIMT 原子 / SIMD / 排序 / 确定性）；Kernel 以"每线程一个 update 元素 → 快除拆索引 → 算目标地址 → 原子写/直接写"为基本范式**。

### Tiling 策略

#### T1. 维度合并为 4 维 + 按 updates 总元素数分核（scatter）

- 适用算子：scatter
- 策略说明：任意维输入沿 axis 合并成 `[B, O, S, I]` 4 维，axis 归一为 -2/-1 两种模板；按 updates 总元素数分核：`≤1024` 单核，`≤ coreNum*1024` 部分核（每核至少 1024），否则全核均分记尾核。尾轴连续块大（`srcStride*dtypeSize > 1024`）时改用 SIMD 搬运模板。UB 预留 32K SIMT 区。

```cpp
if (totalDims <= MIN_FACTOR) { aivCoreNum = 1; }
else if (totalDims <= aivCoreNum * MIN_FACTOR) { blockFactor = MIN_FACTOR; aivCoreNum = CeilDiv(totalDims, MIN_FACTOR); }
else { blockFactor = CeilDiv(totalDims, aivCoreNum); tailCoreNum = aivCoreNum * blockFactor - totalDims; }
context_->SetLocalMemorySize(ubSize - SIMT_RESERVED_SIZE);
```

- 来源：`scatter/op_host/arch35/scatter_tiling_arch35.cpp`

#### T2. 确定性模式判定与按列分核（scatter）

- 适用算子：scatter
- 策略说明：`GetDeterministic()` 且 indices 为 2 维时进入确定性 tiling（key=1000）；按 updates 尾轴列数切核（下限 `DETERM_MIN_COL/dtypeSize`），保证同列所有 indices 更新由同一核串行处理，消除冲突。

```cpp
if (context_->GetDeterministic() && indicesDimSize == TWO_DIM_SIZE) { isDeterministic_ = true; }
normBlockColNum_ = std::max(DETERM_MIN_COL / dtypeSize, CeilDiv(updateColSize, aivCoreNum));
```

- 来源：`scatter/op_host/arch35/scatter_tiling_arch35.cpp`

#### T3. SIMT/SIMD/排序/确定性四路模板选择（scatter_add）

- 适用算子：scatter_add（scatter_sub 共用模板）
- 策略说明：核心判据是 var 尾轴字节数：`< VAR_TAIL_DIM_SIZE(128B)` 走 SIMT（尾轴窄、原子友好）；SIMT AtomicAdd 硬件不支持 int8/uint8 → 这类 dtype 回退 SIMD 或走 workspace 提升；排序场景阈值提高到 512B（`VAR_TAIL_DIM_SIZE_SORT`，SIMT 排序优于 SIMD 排序）。重复索引极多（`indicesNum > varShape[0]*10`，尾轴 ≥10 万时阈值 3 倍）时排序更优。Deterministic 时强制关排序 + 走确定性模板。

```cpp
isSimt_ = varShape_[1] * varTypeSize_ < VAR_TAIL_DIM_SIZE /*128B*/;
if (isSort_) {
    // 排序场景阈值提到 512B；int8/uint8 SIMT atomic 不支持 → 回 SIMD
    isSimt_ = varShape_[1] * varTypeSize_ < 512 && varTypeSize_ != 1;
}
isSort_ = indicesNum_ > varShape_[0] * TEN ? 1 : 0;
if (context_->GetDeterministic() == 1 && isFloatFamily(dtype)) {
    isSort_ = 0;                 // 确定性模式强制关 sort
    isDeterminTemplate_ = 1;     // 走两阶段确定性模板
}
```

- 来源：`scatter_add/op_host/arch35/scatter_add_tiling_base.cpp`

#### T3a. scatter_add 排序模板：UB 内二分求最大 indicesFactor

- 适用算子：scatter_add（simt_sort 路径）
- 策略说明：UB 要同时装下 `indices + sortedIdx + originIdx + sortTmpSize`，tiling 用二分查找求每轮能排序的最大 indices 条数 `indicesFactor_`；随后下发 `normBlockIndices_ / indicesFactor_ / normBlockLoop_` 三层循环结构给 kernel。

```cpp
uint64_t lo = 1, hi = maxIndicesPerLoop;
while (lo < hi) {                    // 二分: indices+sortedIdx+originIdx+sortTmp 全塞进 UB 的最大值
    uint64_t mid = (lo + hi + 1) / 2;
    if (mid * (idxSize * 3 + sortTmpSize) <= ubSize) { lo = mid; } else { hi = mid - 1; }
}
indicesFactor_ = lo;                 // 每轮排序的 indices 条数
```

- 来源：`scatter_add/op_host/arch35/scatter_add_tiling_base.cpp`

#### T4. scatter_nd_common 公共 tiling：按 updates 元素数分核 + slice 粒度 UB 切分

- 适用算子：scatter_nd_max/min（公共库），被 scatter_nd/add/update 同构复用
- 策略说明：updateShapeSize 均分到核，块大小按 UB block 对齐且不低于 128；UbTiling 以一个 scatter slice（`sliceSize*updateTypeSize + rankSize*indiceTypeSize`）为最小粒度在半 UB（双缓冲，预留 128K DCache）内装尽可能多 slice。tilingKey 编码 `(SIMT=8, indiceCastMode, addrMode)`。

```cpp
auto blockTilingSize_ = std::max(CeilAlign(CeilDiv(updateShapeSize_, totalCoreNum_), alignFactor_), MIN_TILING_SIZE);
auto halfUbSize = (ubSize_ - DCACHE_SIZE - RESERVE_SIZE) / DB_BUFFER;
auto sliceUb = sliceSize_ * updateTypeSize + rankSize_ * indiceTypeSize;
ubTilingSize_ = (sliceUb > halfUbSize) ? (halfUbSize - rankSize_ * indiceTypeSize) / updateTypeSize
                                       : (halfUbSize / sliceUb) * sliceSize_;
```

- 来源：`scatter_nd_common/op_host/arch35/scatter_nd_common_simt_tiling.cpp`

#### T5. scatter_reduce_common：按 indices 条目均分 + workspace 精确复算排序 padding

- 适用算子：scatter_reduce_common（scatter_mul/div/max/min 公共）
- 策略说明：按 indices 条目均分到核（每核整数个 slice）；排序用 int32 key，host 拒绝 `varFirstDim > INT32_MAX`。workspace = `sortedIdx | originPos | scratchKeys | scratchPos | per-core partials`，host 必须复算 kernel 内归并排序的 `padM`（P2 翻倍直至 runLen0 ≤ 8192），否则大 M 时排序越界写穿相邻 region。

```cpp
constexpr uint64_t SORT_TILE_HOST = 8192UL; // MUST match SORT_TILE in scatter_reduce_common_sort.h
uint64_t padM = indicesNum;
if (indicesNum > SORT_TILE_HOST) {
    uint64_t p2 = 1UL;
    while (p2 * 2UL <= blockNum) { p2 *= 2UL; }
    while ((indicesNum + p2 - 1UL) / p2 > SORT_TILE_HOST) { p2 *= 2UL; }
    padM = p2 * ((indicesNum + p2 - 1UL) / p2);
}
```

- 来源：`scatter_reduce_common/op_host/arch35/scatter_reduce_common_tiling.cpp`

#### T6. scatter_max_with_argmax：按输出第 0 维 N 行两步法均分

- 适用算子：scatter_max_with_argmax
- 策略说明：按 y 的行切核——**不同核写不同行，天然无跨核冲突**，这是确定性方案的 tiling 基础。两步法 `perCoreRows = CeilDiv(N, coreNum)` 再反推 needCoreNum；空 tensor 保护。

```cpp
perCoreRows = Ops::Base::CeilDiv(N, coreNum);
needCoreNum = Ops::Base::CeilDiv(N, perCoreRows);
context->SetBlockDim(needCoreNum);
```

- 来源：`scatter_max_with_argmax/op_host/arch35/scatter_max_with_argmax_tiling.cpp`

#### T7. scatter_non_aliasing_add：按"输出槽位数"分核

- 适用算子：scatter_non_aliasing_add
- 策略说明：利用 indices 互不重复的语义保证，把**输出空间**按槽位均分到核；每核至少覆盖 `1024/updateDataNum` 个槽位并 32 对齐。每个输出槽位只属于一个核，kernel 免原子。

```cpp
maxIndice = totalElements / updateDataNum;
perCoreSlots = std::max(CeilDiv(maxIndice, coreNum), minSlots);
perCoreSlots = Ops::Base::CeilAlign(perCoreSlots, SLOT_ALIGN);   // 32
needCoreNum = CeilDiv(maxIndice, perCoreSlots);
```

- 来源：`scatter_non_aliasing_add/op_host/arch35/scatter_non_aliasing_add_tiling_arch35.cpp`

#### T8. inplace_scatter_add：N/K 双切轴选择

- 适用算子：inplace_scatter_add
- 策略说明：var `[M, N]`，indices 长度 K。沿 N、K 中较大者切核获得最大并行度：N≥K 切 N（每核一段列、遍历全部 K），否则切 K。更多核 = 更多并发原子操作 = 更好的延迟隐藏。

```cpp
if (N >= K) { splitAxis = 0; splitDim = N; } else { splitAxis = 1; splitDim = K; }
uint32_t blockDim = min(splitDim, coreNum);
uint64_t blockLength = CeilDiv(splitDim, blockDim);
```

- 来源：`inplace_scatter_add/op_host/arch35/inplace_scatter_add_tiling_arch35.cpp`

#### T9. scatter_elements：reduction 编码进 tilingKey + 小位宽 add 的 workspace 扩容

- 适用算子：scatter_elements、scatter_elements_v2
- 策略说明：reduction（none/add/mul → 0/1/2）编入 tilingKey；确定性仅 none 或 add 且 dtype 支持时生效（mul 不可确定化）。reduction=add 且 dtype 为 int8/uint8/int16 时需 int32 workspace 做原子加，host 扩大 workspace。

```cpp
static const std::map<std::string, uint64_t> SCAT_ELE_REDUCTION = {{"none", 0}, {"add", 1}, {"mul", 2}};
bool isDeterminType = reduction_ == 0 || (reduction_ == 1 && 确定性dtype集合.count(dtype_));
if (context_->GetDeterministic() && isDeterminType) { isDeterministic_ = 1; }
if (reduction_ == REDUCTION_ADD && (int16/int8/uint8)) { workspaceSize_ += dataWsSize + updatesWsSize; }
```

- 来源：`scatter_elements/op_host/arch35/scatter_elements_tiling_base.cpp`

#### T10. scatter_update：尾轴阈值选 SIMT + 重复率触发排序 + 确定性分列

- 适用算子：scatter_update
- 策略说明：同 scatter_add 判据；`indicesSize > varShape[0] && >= 64` 启用排序模板（先排序使同目标行 update 相邻再归并）；确定性时若需按列切则强制关闭 SIMT 走 SIMD。

```cpp
isSimt_ = varShape_[1] * varTypeSize_ < VAR_TAIL_DIM_SIZE;
isSort_ = (indicesSize_ > varShape_[0]) && (indicesSize_ >= MIN_SIZE_SORT_INDICES_64);
if (isDeterministicSplitCol_) { isSimt_ = 0; }   // 分列不涉及simt
```

- 来源：`scatter_update/op_host/arch35/scatter_update_tiling_arch35.cpp`

#### T11. scatter_nd_common 排序模板准入：重复率 + dtype 双门限

- 适用算子：scatter_nd_max/min
- 策略说明：SIMT-sort 模板仅在 `indicesAxis / varInAxis >= SORT_LIMIT`（每目标行平均更新次数足够多）且 dtype 支持时启用；UB 预算按 indicesAlignSize 与 sortTmpSize 紧凑/宽裕两档求解。

```cpp
bool IsCapable() { return indicesAxis_ / varInAxis_ >= SORT_LIMIT && IsSimtSortSupportType(updateDtype_); }
int64_t restSize = halfUbSize - indicesFactor_ * indicesAlignSize - GetSortTmpSize(sortTmpType, indicesFactor_, false);
```

- 来源：`scatter_nd_common/op_host/arch35/scatter_nd_common_simt_sort_tiling.cpp`

### Kernel 策略

#### K1. SIMT 基本范式：每线程一个 update 元素 → magic 除法拆 (行, 列) → ND 偏移 → 写

- 适用算子：scatter_nd_update、scatter_nd、scatter_nd_add、scatter_nd_max/min、scatter_update
- 策略说明：VF 线程对 UB 内 updates 元素 grid-stride；`Simt::UintDiv` 拆出"第几个索引行"与"slice 内尾轴列"；rank 循环累加 `indiceVal * strideList[dim]` 得 ND 扁平偏移并累积越界标志；不越界才写（update 直接写 / add 原子加）。

```cpp
for (uint32_t index = threadIdx.x; index < currUbTilingSize; index += blockDim.x) {
    TYPE_T globalIdx = xOffSet + index;
    TYPE_T quotient = Simt::UintDiv(globalIdx, magic, shift);
    TYPE_T scatterAxisIdx = globalIdx - quotient * sliceSize;
    OFFSET_T idx = 0; bool outOfBound = false;
    for (TYPE_T dim = 0; dim < rankSize; ++dim) {
        INDICES_T indiceVal = idxLocalAddr[quotient * rankSize + dim - indiceOffSet];
        outOfBound |= (indiceVal < 0 || indiceVal > outputShapeAddr[dim]);
        idx += static_cast<OFFSET_T>(indiceVal) * strideListAddr[dim];
    }
    if (!outOfBound) { outputGmAddr[idx + scatterAxisIdx] = xLocalAddr[index]; }
}
```

- 来源：`scatter_nd_update/op_kernel/arch35/scatter_nd_update_simt.h`

#### K2. scatter_nd_common：Simt::AtomicMax/Min 原子比较写 + bool 特化

- 适用算子：scatter_nd_max、scatter_nd_min
- 策略说明：reduce 语义用 `Simt::AtomicMax/AtomicMin`（GM 原子比较交换，无需读改写），Mode 编译期分发；bool 无原子 max/min，特化为条件直写（max：value>0 才写）。rankSize==1 时省掉 indices UB 搬运。

```cpp
if constexpr (IsSameType<PARAMS_T, bool>::value) {
    if constexpr (Mode == MODE_MAX) { if (value > 0) { outputGmAddr[dstIndex] = value; } }
    else { if (value <= 0) { outputGmAddr[dstIndex] = value; } }
} else {
    if constexpr (Mode == MODE_MAX) { Simt::AtomicMax(outputGmAddr + dstIndex, xLocalAddr[index]); }
    else { Simt::AtomicMin(outputGmAddr + dstIndex, xLocalAddr[index]); }
}
```

- 来源：`scatter_nd_common/op_kernel/arch35/scatter_nd_common_simt.h`

#### K3. 非确定性原子加 + 小位宽 int32 workspace 提升

- 适用算子：scatter_add（scatter_sub 以取负复用）
- 策略说明：每线程处理 `(indices行, 尾轴列)` 元素，边界检查后 `asc_atomic_add`。int8/uint8 硬件不支持 SIMT 原子加：var 整段 Cast 到 int32 workspace → SyncAll → workspace 上原子加 → SyncAll → Cast 回原 dtype。SUB 用取负复用原子加指令。

```cpp
if constexpr (scatterOp == ADD) {
    if constexpr (int8/uint8) { asc_atomic_add(varWorkspaceGm + varDataIdx, static_cast<CAST_T>(updates[i])); }
    else { asc_atomic_add(var + varDataIdx, updates[i]); }
} else if constexpr (scatterOp == SUB) { asc_atomic_add(var + varDataIdx, -updates[i]); }
// Process: CopyVarToWs() -> SyncAll() -> SimtCompute -> SyncAll() -> CopyWsToVar()
```

- 来源：`scatter_add/op_kernel/arch35/scatter_add_simt.h`

#### K4. 排序归并消冲突：同索引段寄存器折叠 + 每唯一行一次原子加

- 适用算子：scatter_add（simt_sort）、scatter_nd_*_simt_sort
- 策略说明：radix sort 排序 indices 得 sortedOriginIndex 与唯一值 cumSum 区间；VF 内 threadIdx.y 按唯一索引分块、threadIdx.x 覆盖尾轴列，同一目标行的多个 updates **寄存器内串行累加**，每唯一行只做一次原子加——原子操作次数从 M 降到唯一索引数。

```cpp
for (int32_t i = threadIdx.y; i < uniqueIndexNum; i += blockNum) {
    VAR_T result = 0;
    for (int32_t tid = 0; tid < cumSumAddr[i+1] - cumSumAddr[i]; tid++) {
        result += inputAddr[sortedOriginIndexAddr[cumSumAddr[i] + tid] * lastDim + threadIdx.x];
    }
    asc_atomic_add(outputAddr + sortedAddr[cumSumAddr[i]] * lastDim + threadIdx.x, result);
}
```

- 来源：`scatter_add/op_kernel/arch35/scatter_add_simt_sort.h`

#### K5. scatter_max_with_argmax 确定性：行切核 + 核内串行扫描 + GT 严格大于

- 适用算子：scatter_max_with_argmax
- 策略说明：**未采用"值+索引打包 64bit atomicMax"**，而是：tiling 按 N 行切核使跨核无冲突；核内串行遍历全部 M 个 indices，命中本核行时用 GT（严格大于）比较更新 y 和 argmax——严格大于保证"值相等时先到的 i 获胜"，串行保证处理顺序即 i 顺序，完全确定。三阶段：初始化 y=-3.4e38、argmax=M（哨兵）→ scatter max → 未覆盖位置补 0。

```cpp
for (INDEX_T i = 0; i < M; i++) {
    int32_t idx = indicesGm[i];
    if (idxVal >= coreRowStart && idxVal < coreRowEnd) {
        for (INDEX_T p = localTid; p < D; p += threadNum) {
            if (updatesGm[i*D + p] > yGm[idxVal*D + p]) {   // GT 严格大于，相等不更新 → tie 取先到的 i
                yGm[idxVal*D + p] = updatesGm[i*D + p];
                argmaxGm[idxVal*D + p] = i;
            }
        }
    }
    asc_syncthreads();
}
```

- 来源：`scatter_max_with_argmax/op_kernel/arch35/scatter_max_with_argmax_simt.h`

#### K6. scatter_non_aliasing_add：无别名保证的快速路径（免原子）

- 适用算子：scatter_non_aliasing_add
- 策略说明：indices 唯一 → 每个输出槽位至多被一个 update 命中，无需原子。两阶段：先全核 grid-stride 拷贝 x→y，`DataCacheCleanAndInvalid` 刷 DCache；再每核串行扫全部 scatter，只处理落在本核输出区间的槽位，槽内 slice 线程并行普通加。

```cpp
for (IDX_T i = 0; i < totalScat; i++) {
    IDX_T offset = ComputeScatterOffset(K, i, indices, stridesUb);
    if (offset >= coreStart && offset < coreEnd) {   // 仅本核拥有的槽位
        ScatterAddSlice(offset, i, updateNum, updates, y);   // 普通加，无原子
    }
}
```

- 来源：`scatter_non_aliasing_add/op_kernel/arch35/scatter_non_aliasing_add_simt.h`

#### K7. inplace_scatter_add：纯 SIMT 全量原子加 + N/K 双切四 kernel

- 适用算子：inplace_scatter_add
- 策略说明：不做排序/去重，直接对 `(k, col)` 网格逐元素 `asc_atomic_add`（非确定性）。N-split 每核一段列循环全部 K；K-split 反之。越界索引跳过。`canUse32Bit` 时走 32 位 kernel。

```cpp
for (uint32_t i = threadIdx.x; i < totalElements; i += blockDim.x) {
    uint32_t k = Simt::UintDiv<uint32_t>(i, magic, shift);
    uint32_t col = blockOffset + (i - k * blockLength);
    IDX_T idx = indices[k];
    if (idx >= 0 && idx < M) {
        asc_atomic_add(&var[idx * N + col], updates[k * N + col]);
    }
}
```

- 来源：`inplace_scatter_add/op_kernel/arch35/inplace_scatter_add_simt.h`

#### K8. scatter_nd_sub：两阶段（多核拷贝 + SyncAll + 单核串行 slice）换确定性

- 适用算子：scatter_nd_sub
- 策略说明：减法不满足交换律 → Phase1 全核拷贝 var→output；SyncAll；Phase2 **仅 block 0** 串行遍历全部 slice（重复 indices 按 s 顺序依次作用，确定性），slice 内线程并行 `output -= updates`，slice 间 syncthreads。

```cpp
if (blockIdx.x != 0) { return; }
for (int64_t s = 0; s < numSlices; s++) {          // 串行 slice → 确定性
    int64_t flatOffset = Σ indices[s][j] * strides[j];
    for (int64_t e = threadIdx.x; e < sliceSize; e += blockDim.x) {
        output[flatOffset + e] -= updates[updatesBase + e];
    }
    asc_syncthreads();
}
```

- 来源：`scatter_nd_sub/op_kernel/arch35/scatter_nd_sub_simt.h`

#### K9. scatter_reduce_common：公共 reduce 分发，无 SIMT 原子路径

- 适用算子：scatter_mul/div/max/min（公共底座）
- 策略说明：全部走**排序 + 确定性归并**：① sliceSize==1 且规模小 → 单核 UB scalar 折叠；② sliceSize>=2 → 排序 + 各核按计数均衡切段 + 跨核 partial combine（MUL/MAX/MIN 满足结合交换律可切可合）；③ DIV 不可跨核切（除数积溢出），用行 ownership 方案，整数 /0 换 1、浮点 /0→inf。AccT 提升：fp16→float、int8→int32。

```cpp
using AccT = Conditional<sizeof(PARAMS_T)==4, PARAMS_T, Conditional<half→float, int8→int32>>;
if constexpr (Mode == MODE_MUL || MODE_MAX || MODE_MIN) {
    if (sliceSize == 1 && 小规模) { ScalarReduce1D(...); }
    if (sliceSize >= 2) { SortReduceProcess(...); }
}
if constexpr (Mode == MODE_DIV) { SortDivRowProcess(...); }  // 行ownership，无combine
```

- 来源：`scatter_reduce_common/op_kernel/arch35/scatter_reduce_common_simt.h`

#### K10. scatter_elements：1~8 维分级 kernel + UintDiv 逐级拆维 + REDU 三分支

- 适用算子：scatter_elements、scatter_elements_v2
- 策略说明：按 rank 提供 SimtComputeDim1~8 模板（rank>4 时 magic/shift 打包成 UB 数组）；每线程处理 indices 一个元素，分解各维坐标后按模板参数 DIM 把 `indices[i]` 插入对应轴算 yOffset；`ReplaceOut` 按 REDU 分发：ADD → asc_atomic_add（小位宽走 workspace）、MUL → 普通乘、none → 覆盖写。

```cpp
if constexpr (DIM == 0) { yOffset = indices[i] * dataStride[0] + dim1Idx; }
// ReplaceOut:
if constexpr (REDU == REDU_ADD) { asc_atomic_add(y + yOffset, updates[updatesOffset]); }
else if constexpr (REDU == REDU_MUL) { y[yOffset] = y[yOffset] * updates[updatesOffset]; }
else { y[yOffset] = updates[updatesOffset]; }
```

- 来源：`scatter_elements/op_kernel/arch35/scatter_elements.h`

#### K11. scatter（update 语义）：coef 预计算修正项 + 4 种模板

- 适用算子：scatter
- 策略说明：每线程处理一个 updates 元素，`CalcIndex2/3`（magic 除法）拆坐标，目标地址 = 线性地址 + 各维 shape 差修正项（coef 在 Init 预计算）+ indices 替换 scatter 轴坐标；按 indicesDim × axis 组合 4 个 VF。参数表经 UB（simtBuf_）传入避免 VF 函数传大结构体。

```cpp
uint32_t i, j;
CalcIndex2<T3>(addr, i, j, factorArr, shiftArr, mArr);
int32_t dstOffset = addr + i * coefArr[0] + j * coefArr[1] + indicesGm[i] * coefArr[7];
outputGm[dstOffset] = updatesGm[startOffset + idx];
```

- 来源：`scatter/op_kernel/arch35/scatter_simt.h`

#### K12. UB 暂存 + asc_vf_call 发射模式（SIMT 与 SIMD 数据通路协作）

- 适用算子：scatter_nd_common、scatter_nd_add/update、scatter（共性架构）
- 策略说明：VF 线程直接访问 GM 离散地址，但**连续数据（updates、indices、strideList、outputShape）先经 DataCopyPad 双缓冲搬入 UB**，VF 通过 `__ubuf__` 指针读 UB；每个 UB 循环按 xOffSet/sliceSize 反推所需 indices 区间一并搬入。发射前 `DataSyncBarrier<UB>` 保证可见性。

```cpp
DataCopyPad(idxLocal, idxGm[indiceOffSet_], idxCopyParams, idxPadParams);
DataCopyPad(xLocal, xGm[xOffSet_], xCopyParams, xPadParams);
GetUintDivMagicAndShift(magic, shift, sliceSize);
asc_vf_call<SimtCompute<...>>(dim3(THREAD_NUM), (__ubuf__ INDICES_T*)idxLocal.GetPhyAddr(), ...);
```

- 来源：`scatter_nd_common/op_kernel/arch35/scatter_nd_common_simt.h`

#### K13. scatter_update：全核 grid-stride 直写（update 最简形态）

- 适用算子：scatter_update
- 策略说明：var 视为 `[varFirstDim, totalCol]`，总任务 `indicesSize*totalCol` 由所有核所有线程平摊（全核一次性 grid-stride，无 UB 搬运）；UintDiv 求 indices 行，越界行跳过；isUpdateScalar 时 updates 为标量广播写。

```cpp
ADDR_T totalSize = indicesSize * totalCol;
for (ADDR_T i = blockIdx * blockDim.x + threadIdx.x; i < totalSize; i += blockNum * blockDim.x) {
    ADDR_T varRow = indices[Simt::UintDiv(i, magic, shift)];
    ADDR_T varDataIdx = varRow * varStride + (i % totalCol);
    if (!(varRow >= 0 && varRow < varFirstDimSize)) { continue; }
    var[varDataIdx] = isUpdateScalar ? updateScalarValue : updates[i];
}
```

- 来源：`scatter_update/op_kernel/arch35/scatter_update_simt.h`

#### K13a. scatter_update 确定性：mask-max 全局序号胜出（确定性 last-write）

- 适用算子：scatter_update（deterministic 模板）
- 策略说明：update 语义要求"重复索引时后者覆盖"。确定性实现用 workspace 掩码数组做**写权限竞争**：阶段一每个线程对自己的目标地址 `asc_atomic_max(workspaceMask + idx, globalUpdateSeq)`（全局序号 = 更新顺序编码），`asc_syncthreads` 后阶段二只有 `mask[idx] == mySeq` 的线程（即序号最大者=最后更新者）才真正写 var。两次遍历换确定性 last-write，无锁无回滚。

```cpp
// 阶段1: 竞争写权限——原子取最大序号
asc_atomic_max(workspaceMask + idx, globalUpdateSeq);
asc_syncthreads();
// 阶段2: 只有 mask==自己序号 的线程才写 var（最后写入者胜出，顺序确定）
if (workspaceMask[idx] == mySeq) { var[idx] = myValue; }
```

- 来源：`scatter_update/op_kernel/arch35/scatter_update_common.h`

#### K13b. inplace_index_add 的 indices 降位 Cast 缩短排序 key

- 适用算子：inplace_index_add（simt_sort 路径）
- 策略说明：与 unsorted_segment 的 T5 同思想：按 varInAxis（目标行数）实际值域把 indices 从 int32/int64 降为 uint8/int16/int32 再排序——`varInAxis < 255 → uint8`、`< 32767 → int16`，减少 radix sort 的 pass 数。castMode 编入 tilingKey。

```cpp
if      (varInAxis < 255)       { castType = CAST_UINT8; }
else if (varInAxis < 32767)     { castType = CAST_INT16; }
else if (varInAxis < INT32_MAX) { castType = CAST_INT32; }
// tilingKey = GET_TPL_TILING_KEY(TEMPLATE_MODE_SIMT_SORT, indiceCastMode, addrMode)
```

- 来源：`inplace_index_add/op_host/arch35/inplace_index_add_base_tiling.cpp`

#### K14. scatter_nd：清零/复用输出 + ND 原子加（空输出场景特化）

- 适用算子：scatter_nd
- 策略说明：输出由 shape 属性全新构造（无 var 输入），kernel 内含清零阶段（按 clrBlockNum 分核清零 output），再进入 ND 偏移 + `asc_atomic_add`（对零初始化累加，重复索引不影响加法结果值，仅浮点舍入序非确定）。

```cpp
if (!outOfBound) {
    uint64_t dst = idx * sliceSize + scatterAxisIdx;
    asc_atomic_add(outputGmAddr + dst, xLocalAddr[index]);
}
```

- 来源：`scatter_nd/op_kernel/arch35/scatter_nd.h`

#### K15. 尾轴连续块粒度：SIMD 大块原子拷贝与 SIMT 的边界分工

- 适用算子：scatter_add（SIMD 路径）
- 策略说明：尾轴连续大块（≥阈值字节）时 SIMT 逐元素原子加不如 SIMD：`SetAtomicAdd<T>()` 打开 GM 原子加模式后 `DataCopyPad` 整块把 updates 原子加到 var 行，一次搬运完成整行累加。tiling_mode 按整除关系与半 UB 容量决定整行/分行/跨行搬运；不支持 SIMD 原子加的 dtype 回退 UB 内 read-modify-write。

```cpp
SetAtomicAdd<T>();
DataCopyPad(varGm[varRefOffset], updatesLocal, outParams);  // 整块原子加到 var 行
SetAtomicNone();
```

- 来源：`scatter_add/op_kernel/arch35/scatter_add_simd_support_atomicadd.h`

### 附：写冲突方案横向对比

| 方案 | 算子 | 确定性 | 适用条件 |
|---|---|---|---|
| asc_atomic_add（逐元素） | scatter_add/sub、scatter_nd、inplace_scatter_add、scatter_elements(add) | 否 | 尾轴小、离散；int8/uint8 需 workspace 提升 |
| Simt::AtomicMax/Min | scatter_nd_max/min | 结果值确定（tie 不确定） | 最值 reduce、无 argmax |
| 排序归并 + 段内寄存器折叠 | scatter_add_sort、scatter_nd_*_sort、scatter_reduce_common | 段内确定 | 重复索引率高 |
| 按行切核 + 核内串行扫描 | scatter_max_with_argmax | 是（GT + i 顺序 tie-break） | 需 argmax |
| 单核串行 slice | scatter_nd_sub | 是 | 减法语义 |
| 无别名免原子 | scatter_non_aliasing_add | 是 | indices 唯一（语义保证） |
| 直接覆盖写 | scatter、scatter_update、scatter_elements(none/mul) | 否（语义允许） | 非归约 |
| SetAtomicAdd + DataCopyPad 整块原子拷贝 | scatter_add（SIMD 路径） | 否 | 尾轴连续大块 |

---
## 九、段聚合与稀疏聚合类（Segment）

> 范围：`index/` 下 segment_sum、unsorted_segment_max/min/prod/sum、unsorted_segment_common、sparse_segment_mean、sparse_segment_sum_grad、sorted_sparse_segment_mean_grad、scatter_add_with_sorted、index_put_with_sort_v2、sort_lib、add_row_ranges、bucketize_v2、concat_offset。

### Tiling 策略

#### T1. 模板注册表 + 优先级调度（SIMT 原子模板恒 capable 兜底）

- 适用算子：unsorted_segment_max/min/prod/sum（共用 unsorted_segment_common）
- 策略说明：每个模板（OutFullLoad=1、SimdSplitCol=20、SimdNonSort=30、SimdDynSort=50、SortSimt=60、Simt=100）实现 `IsCapable()`，注册表按优先级从小到大探测，SIMT 原子模板恒 true 兜底。TilingPrepare 把 coreNum/maxThread/ubSize 写入 CompileInfo 共享。

```cpp
REGISTER_OPS_TILING_TEMPLATE(UnsortedSegmentMax, UnsortedSegmentMaxOutFlTiling, 1);
REGISTER_OPS_TILING_TEMPLATE(UnsortedSegmentMax, UnsortedSegmentMaxSimdSplitColTiling, 20);
REGISTER_OPS_TILING_TEMPLATE(UnsortedSegmentMax, UnsortedSegmentMaxSimdDynSortTiling, 50);
REGISTER_OPS_TILING_TEMPLATE(UnsortedSegmentMax, UnsortedSegmentMaxSortSimtTiling, 60);
REGISTER_OPS_TILING_TEMPLATE(UnsortedSegmentMax, UnsortedSegmentMaxSimtTiling, 100);   // 兜底
```

- 来源：`index/unsorted_segment_max/op_host/arch35/unsorted_segment_max_tiling.cpp`

#### T2. 公共 tiling 基类：shape 扁平化与公共校验

- 适用算子：unsorted_segment 全系列
- 策略说明：`UnsortedSegmentBaseTiling` 把任意维输入按 segment_ids 维数扁平化为 `[inputOuterDim, innerDim]`，计算 `ratio_ = inputOuterDim / outputOuterDim`（入出比，选 Sort 模板的关键指标）；校验 num_segments 一致、inputOuterDim < 2^48（radix sort key 上限）。

```cpp
std::tie(inputOuterDim_, innerDim_) = FlatInput(dataShape, segmentIdsShape);
uint64_t bound = static_cast<int64_t>(1ULL << 48);
OP_TILING_CHECK(inputOuterDim_ > bound, ...);
ratio_ = inputOuterDim_ / outputOuterDim_;
```

- 来源：`index/unsorted_segment_common/op_host/arch35/unsorted_segment_tiling_common.cpp`

#### T3. 纯 SIMT 原子模板：按数据条数分核，兼顾输出初始化分核

- 适用算子：unsorted_segment 系列（tilingKey=1000）
- 策略说明：分核数取两者最大值：计算需求 `CeilDiv(dataShapeSize, maxThread)`；输出初始化需求（先填幺元，每核至少 `2048/dtypeBytes` 元素）。`SetScheduleMode(1)` 因为 kernel 内有 SyncAll（初始化后再聚合）。

```cpp
usedCoreNum_ = std::min(CeilDiv(dataShapeSize_, maxThread_), totalCoreNum_);
uint64_t normBlockData = std::max(CeilDiv(outSize, totalCoreNum_), UB_MIN_FACTOR / dataTypeBytes_);
uint64_t initUsedCore = CeilDiv(outSize, normBlockData);
usedCoreNum_ = std::max(usedCoreNum_, initUsedCore);
```

- 来源：`index/unsorted_segment_common/op_host/arch35/unsorted_segment_simt_tiling.cpp`

#### T4. Sort+SIMT 模板：高聚合比场景启用，UB 容量二分求单次排序行数

- 适用算子：unsorted_segment_max/min/sum（tilingKey=4100）
- 策略说明：仅当"入出比 >= 5 且 innerDim < 512"启用（排序收益大于开销）。host 侧**二分查找**求 rowUb——单次能放进 UB 的最大行数：UB 需容纳双倍缓冲 x 数据 + 原始/排序 index + origin index + radix sort 临时空间。随后按 rowUb 切成批次均分到核；核利用率不足一半时 rowUb 减半重切。

```cpp
bool IsCapable() { return inputOuterDim_ / outputOuterDim_ >= 5 && innerDim_ < 512; }
while (end - start > 1) {
    mid = (end + start) / 2;
    int64_t tmpTotalSize = totalIndexSize + GetSortTmpSize(idType_, mid, false) + CeilAlign(mid * innerDim_ * dataTypeBytes_, ubBlock) * 2;
    if (tmpTotalSize <= ubSize_) { start = mid; } else { end = mid; }
}
```

- 来源：`index/unsorted_segment_common/op_host/arch35/unsorted_segment_sort_simt_tiling.cpp`

#### T5. 排序前索引降位 Cast：缩短 radix sort key 宽度

- 适用算子：unsorted_segment 系列（SimdDynSort/SortSimt 模板）
- 策略说明：radix sort 代价与 key 字节数成正比。按 outputOuterDim 实际值域把 segment_ids 从 int32/int64 降为 uint8/int16/int32（如 <255 时一轮 radix 排完），`idCastMode_` 写入 tiling data，kernel 按 cast mode 实例化模板。

```cpp
if (idType_ == ge::DT_INT64) {
    if (outputOuterDim_ < UINT8_MAX) { idCastMode_ = CAST_INT64_TO_UINT8; }
    else if (outputOuterDim_ < INT16_MAX) { idCastMode_ = CAST_INT64_TO_INT16; }
    else { idCastMode_ = CAST_INT64_TO_INT32; }
}
```

- 来源：`index/unsorted_segment_common/op_host/arch35/unsorted_segment_tiling_common.cpp`

#### T6. segment_sum SIMT tiling：输出清零与输入均分分离 + 确定性标记

- 适用算子：segment_sum（tilingKey=1000）
- 策略说明：segment_ids 保证非降序，按行均分到核，但每核**首段和尾段**可能被相邻核切开需原子加。tiling 计算：输出清零份额、每核 segment_ids 按 UB 容量 `maxSegIdsInUb = (ubSize/2 - ubBlock)/idBytes` 切 loop；`GetDeterministic()` 且浮点时置 isDeterministic 并追加 workspace（128 行 tmp row + 128 id）。

```cpp
if (context_->GetDeterministic() && deterministicType.count(dataType_)) { isDeterministic_ = 1; }
maxSegIdsInUb = (ubSize_ / 2 - ubBlockSize_) / idTypeBytes_;
if (isDeterministic_ == 1) { ws += ROWS_IN_WORKSPACE * innerDim_ * valueTypeBytes_ + ROWS_IN_WORKSPACE * idTypeBytes_; }
```

- 来源：`index/segment_sum/op_host/arch35/segment_sum_simt_tiling.cpp`

#### T7. scatter_add_with_sorted：按 indices 条数均分 + tilingKey 位域编码

- 适用算子：scatter_add_with_sorted
- 策略说明：SIMT 模板仅在 `varShape[1] * dtypeSize < 512B`（内轴小）时启用。tilingKey 位域编码：`isUpdateScalar`、`isDetermin`（确定性时追加 `usedCoreNum*2*(varShape[1]+1)` workspace）、地址位宽（32/64）。

```cpp
bool isSimt = varShape_[1] * updatesDtypeSize_ < SIMT_INNER_THRES;   // 512B
uint64_t addrType = (varShape_[1] * indicesNum_ > INT32_MAX || varSize_ > INT32_MAX) ? TPL_ADDR_B64 : TPL_ADDR_B32;
return GET_TPL_TILING_KEY(TPL_MODE_SIMT, isScalar, isDeterm, addrType);
```

- 来源：`index/scatter_add_with_sorted/op_host/scatter_add_with_sorted_simt_tiling.cpp`

#### T8. sparse_segment_mean：SIMT/SIMD 双路阈值矩阵 + 线程/block 两级切分

- 适用算子：sparse_segment_mean
- 策略说明：经验阈值矩阵界定 isSimt（innerSize、segmentNum、平均每段 id 数三元组）。线程切分三形态：(1) **small inner**（innerPow2<64 且平均段长>1）：x 维给 inner（向上 pow2），y 维给段内 id 并行规约，每核段数向 16 对齐；(2) **simt loop**（innerSize>2048）：x 维循环；(3) **large inner**：x=innerSize、y 摊给多个段。

```cpp
if (innerPow2 < 64 && avgReduceSizePow2 > 阈值) {
    threadNumX_ = innerPow2;
    threadNumY_ = std::min(avgReduceSizePow2, threadNum_ / innerPow2);
    isSmallInner_ = true;
} else if (innerSize > 2048) { isSimtLoop_ = true; }
else { threadNumX_ = innerSize; threadNumY_ = threadNum_ / threadNumX_; }
```

- 来源：`index/sparse_segment_mean/op_host/arch35/sparse_segment_mean_tiling_simt_tiling.cpp`

#### T9. sorted_sparse_segment_mean_grad：tilingKey 按 32/64 位组合 + inner 维多核拆分

- 适用算子：sorted_sparse_segment_mean_grad
- 策略说明：先按 outputDim0 均分；核用不满且 innerSize>64 时把 inner 维切给空闲核（`innerCore_ = coreNum / needCoreNum_`），行列二维分核。tilingKey 编码 small/large inner × inner/outer 是否超 UINT32_MAX 共 6 种组合。

```cpp
if (needCoreNum_ < coreNum && innerSize > MAX_CORE_NUM) {
    innerCore_ = coreNum / needCoreNum_;
    perCoreInnerSize_ = innerSize / innerCore_;
    needCoreNum_ *= innerCore_;
}
```

- 来源：`index/sorted_sparse_segment_mean_grad/op_host/arch35/sorted_sparse_segment_mean_grad_tiling_simt_tiling.cpp`

#### T10. sparse_segment_sum_grad：按 indices 条数 N 定核

- 适用算子：sparse_segment_sum_grad
- 策略说明：kernel 采用"每输出元素扫描全部 N 个 indices"的确定性算法，工作量正比 `outputDim0*innerSize*N`；tiling 极简：`needCoreNum = min(coreNum, N)`，N=0 时 1 核只清零。`SetScheduleMode(SCHEDULE_MODE_SERIAL)`。

```cpp
int64_t needCoreNum = (n == 0) ? 1 : std::min(coreNum, n);
context->SetBlockDim(needCoreNum);
context->SetScheduleMode(SCHEDULE_MODE_SERIAL);
```

- **来源**：`index/sparse_segment_sum_grad/op_host/arch35/sparse_segment_sum_grad_tiling.cpp`

#### T11. index_put_with_sort_v2：索引轴/非索引轴解耦 + 五种线程分配场景

- 适用算子：index_put_with_sort_v2
- 策略说明：linear_index 已由上游排序并给出 pos_idx。维度拆为索引轴（indexedDimSize）与非索引轴（nonIndexedDimSize，预计算 stride 数组）。tilingKey 编码 `accumulate / allIndexed / indexedBlockMode`。线程分配按两轴与核数关系分五种场景（索引轴大→线程全给索引轴；非索引轴大→线程全给非索引轴等）。

```cpp
if (indexedBlockMode_) {
    if (indexedDimSize_ >= aivCoreNum_ * threadNumPerBlock || allIndexed) {
        indexedThreadNum_ = threadNumPerBlock; nonIndexedThreadNum_ = 1;
    } else if (indexedDimSize_ >= aivCoreNum_) {
        indexedThreadNum_ = indexedDimSize_ / aivCoreNum_;
        nonIndexedThreadNum_ = threadNumPerBlock / indexedThreadNum_;
    } else { indexedThreadNum_ = 1; nonIndexedThreadNum_ = nonIndexedDimSize_; }
}
```

- 来源：`index/index_put_with_sort_v2/op_host/arch35/index_put_with_sort_v2_tiling_arch35.cpp`

#### T12. sort_lib 公共 host 接口：单核快路径 / 多核 LSD radix

- 适用算子：sort_lib（供 index 域需要"排序+permutation"的算子复用）
- 策略说明：对外只暴露 `SortTilingCompute(...)`：(1) 空输入单核语义；(2) **单核快路径** `2*xUb + idxUb + sortTmp <= usableUb` 时直接单核 Sort API，0 次 SyncAll、0 GM workspace；(3) 否则多核 LSD radix，按 UB 预算求 tileData（每元素代价 = dtype + idx + 4 + 1 + 1 字节），workspace 六段布局。元素数 > 2^30 时计数器升 64 位。

```cpp
if (detail::TrySingleCore(r, totalElements, usableUb, dtypeSize, indexSize, valueType, blockUbSize)) { return r; }
uint32_t counterSize = use64BitCounters ? INT64_BYTES : UINT32_BYTES;
uint32_t radixRounds = dtypeSize; // radix sort passes: sizeof(ValT) per round
r.workspaceBytes = detail::ComputeWorkspaceBytes(totalElements, tileCount, numTileData, dtypeSize, counterSize, radixRounds, blockUbSize);
```

- 来源：`index/sort_lib/op_host/arch35/sort_lib_tiling.h`

#### T13. bucketize_v2：小 bound 让给 SIMD，SIMT 预计算二分迭代次数

- 适用算子：bucketize_v2
- 策略说明：bound 很小（b32≤16、b64≤8）时 SIMD 可把 bound 载入 UB 向量化比较，SIMT 让位。SIMT 路径按 `ceil(xSize / 2048)` 分核，`maxIter = ceilLog2(boundSize)` 预计算二分最大迭代轮数（kernel 固定轮数循环利于调度）；boundSize 超 int32 升 int64 编入 key。

```cpp
bool IsCapable() {
    if (b16 || (b32 && boundSize_ <= 16) || (b64 && boundSize_ <= 8)) { return false; }
    return true;
}
maxIter_ = GetUpLog2(boundSize_);
IsUsedInt64_ = boundSize_ >= INT32_MAX;
```

- 来源：`index/bucketize_v2/op_host/arch35/bucketize_v2_simt_tiling.cpp`

#### T14. add_row_ranges：最小核粒度兜底 + int32 上限硬校验

- 适用算子：add_row_ranges
- 策略说明：kernel 每线程一个输出元素串行累加 `src[start:end, c]`。tiling 按 CeilDiv 均分但设 1024 下限；`totalElements/N/K` 均要求 ≤ INT32_MAX（kernel 循环变量 uint32_t），超限直接报错而非降级。

```cpp
OP_CHECK_IF(totalElements > INT32_MAX, OP_LOGE(context, "...exceeds INT32_MAX"), return ge::GRAPH_FAILED);
if (perCoreElements < PER_CORE_MIN_ELEMENTS) { perCoreElements = PER_CORE_MIN_ELEMENTS; }
```

- 来源：`index/add_row_ranges/op_host/arch35/add_row_ranges_tiling_arch35.cpp`

#### T15. concat_offset：数据依赖 tiling + 单核小任务

- 适用算子：concat_offset
- 策略说明：输出 = tensor 个数 × 维数，很小。tiling 声明 `TilingInputsDataDependency({0})`；kernel 只用 0 号核，内部 SIMT 线程并行。计算量小但访存不规则（tensor list 指针间接寻址）的算子：放弃多核换实现简单与确定性。

```cpp
IMPL_OP_OPTILING(ConcatOffset).TilingInputsDataDependency({0}).Tiling(Tiling4ConcatOffset)...;
int32_t blockIdxLocal = GetBlockIdx();
if (blockIdxLocal >= 1) { return; }
```

- 来源：`index/concat_offset/op_host/arch35/concat_offset_tiling_arch35.cpp`

### Kernel 策略

#### K1. unsorted_segment 纯 SIMT 原子聚合主循环

- 适用算子：unsorted_segment_max/min/sum
- 策略说明：`SimtComputeSegment` 是核心无序聚合 VF：grid-stride 遍历全部输入元素，magic 快除分解（行, 行内偏移），读 segmentIds 得目标段；段 id 越界直接丢弃；合法则用注入的 `SimtAtomicFunc` 原子写输出。模板参数 COM_T 按总元素数选 uint32/uint64。多写者冲突完全交给硬件原子单元，实现最简、无需排序。

```cpp
for (COM_T inputIndex = blockIdx.x * blockDim.x + threadIdx.x; inputIndex < inputLength; inputIndex += blockNums * blockDim.x) {
    COM_T inputSegmentIndex = Simt::UintDiv(inputIndex, magic, shift);
    COM_T segmentOffset = inputIndex - inputSegmentIndex * innerDimSize;
    const Index outputSegmentIndex = segmentIdsGm[inputSegmentIndex];
    if (outputSegmentIndex < 0 || outputSegmentIndex >= outputOuterDimSize) { continue; }
    SimtAtomicFunc()(outputGm, outputSegmentIndex * innerDimSize + segmentOffset, xGm[inputIndex]);
}
```

- 来源：`index/unsorted_segment_common/op_kernel/arch35/unsorted_segment_base.h`

#### K2. 公共模板机制：reduce op 以 Functor 注入实现"类型擦除"

- 适用算子：unsorted_segment 全系列
- 策略说明：公共 kernel 不硬编码归约语义，全部模板参数注入：`SimtAtomicFunc`（原子写）、`GmInitFunc`（幺元填充）、`SimtGatherFunc`（UB 内归并）、`InitValueType`（幺元：max→最小值、sum→0、prod→1）。每个算子定义自己的特化，.cpp 入口按 tilingKey 分发到公共模板实例。"段聚合框架"与"归约语义"完全解耦。

```cpp
template <typename T>
struct SimtComputeSegmentMax {
    __simt_callee__ inline void operator()(__gm__ T* outputGm, uint64_t outputIndex, T value) {
        Simt::AtomicMax(outputGm + outputIndex, value);
    }
};
// 分发：KernelUnsortedSegment<X_T, IDS_T, SimtComputeSegmentMax<X_T>, InitGmMinValue<X_T>> op(...)
```

- 来源：`index/unsorted_segment_max/op_kernel/unsorted_segment_max.h`

#### K3. 输出 GM initial value 预填充（InitGm + SyncAll）

- 适用算子：unsorted_segment 全系列
- 策略说明：原子聚合前必须把输出填成归约幺元，否则空段是脏数据。`InitGm` 在 kernel Init 阶段完成：按核对输出均分、512B 对齐、2KB 最小粒度，用 `InitGlobalMemory`（MTE 批量填充），最后 `SyncAll()` 保证填充对后续原子写可见。

```cpp
uint64_t initPerCore = Aligned(CeilDiv(totalNum, GetBlockNum()), GM_ALIGN / sizeof(T));
initPerCore = std::max(initPerCore, MIN_FACTOR / sizeof(T));
if (GetBlockIdx() < coreNum) { GmInitFunc()(yGmInit, initCoreReal); }
SyncAll();
```

- 来源：`index/unsorted_segment_common/op_kernel/arch35/unsorted_segment_base.h`

#### K4. prod 的 AtomicCas 乘法循环（无原生 atomicMul 的兜底）

- 适用算子：unsorted_segment_prod
- 策略说明：SIMT 原子指令无 atomicMul，用"读-乘-CAS"自旋循环：读旧值→算 old*cur→AtomicCas 尝试写回，成功退出否则重试。half/bf16 走"提升到 uint32 位模式 CAS"特化。高冲突时 CAS 自旋退化，因此 prod 更依赖排序模板兜底。

```cpp
while (true) {
    TX oldVal = outputGm[outputIndex];
    TX newVal = oldVal * curGmValue;
    TX cas = Simt::AtomicCas(outputGm + outputIndex, oldVal, newVal);
    if (cas == oldVal) { break; }
}
```

- 来源：`index/unsorted_segment_prod/op_kernel/unsorted_segment_prod.h`

#### K5. Sort+SIMT 段内归并：UB 内排序 → 相邻比较找段边界 → 段内串行 reduce

- 适用算子：unsorted_segment_max/min/sum（高聚合比）
- 策略说明：每核把 rowUb 行 ids 与 x 数据搬入 UB，`AscendC::Sort<RADIX_SORT>` UB 内排序产出 sortedIndexLocal；`GetUniqueCount` 求 unique 段边界；`SegmentReduceSortSimt` 二维线程（x=innerDim，y=unique 段）段内串行归并（sortedOriginIndex 间接寻址），**每段只做一次原子写 GM**——"每元素一次原子"降为"每段一次原子"。

```cpp
for (int32_t i = threadIdx.y; i < uniqueIndexNum; i += blockNum) {
    TX result = InitValueType::Get();
    for (int32_t tid = 0; tid < cumSumAddr[i+1] - cumSumAddr[i]; tid++) {
        result = SimtGatherFunc()(result, inputAddr[sortedOriginIndexAddr[cumSumAddr[i]+tid] * lastDim + threadIdx.x]);
    }
    SimtAtomicFunc()(outputAddr, sortedAddr[cumSumAddr[i]] * lastDim + threadIdx.x, result);
}
```

- 来源：`index/unsorted_segment_common/op_kernel/arch35/unsorted_segment_sort_simt.h`

#### K6. 向量指令找段边界通用件：Compare(NE) + Squeeze + AR 寄存器计数

- 适用算子：unsorted_segment（SortSimt/SimdDynSort）、segment_sum
- 策略说明：排序后 ids 找段边界用 SIMD 微指令一次完成：排序数组与"左移一位"版本 `Compare<NE>` 得边界掩码；`Arange` 生成序号；`Squeeze<STORE_REG>` 按掩码紧凑压入；读特殊寄存器 `AR`（累加写计数器）直接得 unique 个数。segment_sum（输入已排序）直接用同一段代码对原始 ids 找边界，无需排序。

```cpp
MicroAPI::LoadUnAlign(indicesShiftOneReg, u0, sortedIndicesAddr - 1);
MicroAPI::Compare<Index, CMPMODE::NE>(cmpMask, indicesReg, indicesShiftOneReg, maskReg);
MicroAPI::Squeeze<int32_t, STORE_REG>(selReg, orderReg, cmpMask);
return ((MicroAPI::GetSpr<SpecialPurposeReg::AR>()) / sizeof(int32_t)) - 1;
```

- 来源：`index/unsorted_segment_common/op_kernel/arch35/unsorted_segment_sort_simt.h`

#### K7. segment_sum SIMT：sorted ids 段归并 + 首/尾段跨界原子加

- 适用算子：segment_sum（segment_ids 非降序）
- 策略说明：输入已排序：每核按行连续切分，UB 内 K6 求 unique 段边界；每个 y 线程串行累加完整段后写输出——**中间段**（完全落在本核内）直接普通写（无原子），只有**首段和尾段**可能被相邻核切开用 `asc_atomic_add`。原子操作从 N 次降到每 loop 最多 2 次。

```cpp
for (uint32_t i = threadIdx.y; i < uniqueIdNum; i += blockDim.y) {
    TX res = 0;
    for (int32_t j = uniqueIdPosAddr[i]; j < nextIdPos; j++) { res += xAddr[(baseOffset + j) * colSize + threadIdx.x]; }
    if (i == 0 || i == uniqueIdNum - 1) { asc_atomic_add(outputAddr + outputOffset, res); }
    else { outputAddr[outputOffset] = res; }
}
```

- 来源：`index/segment_sum/op_kernel/arch35/segment_sum_simt.h`

#### K8. segment_sum 确定性模式：workspace 暂存跨界段 + 二次归并

- 适用算子：segment_sum（deterministic）
- 策略说明：K7 的原子加对浮点非确定。确定性模式：每核把跨界首/尾段结果连同段 id 写 GM workspace（每核 2 行），中间段直接写；SyncAll 后 0 号核按核序（即 id 序）遍历 workspace，相邻比较跳过重复 id，同 id 多段按固定顺序串行累加后原子加一次——累加顺序全局固定，结果可复现。

```cpp
if (i > 0 && segmentIdsWs[i] == segmentIdsWs[prevId]) { continue; }   // 与前一行同 id，由前一行线程处理
TX res = tmpRowWs[i * colSize + threadIdx.x];
for (Index j = i + 1; j < TMP_ROWS_TOTAL; j++) {
    if (segmentIdsWs[j] == -1) { continue; }
    if (segmentIdsWs[i] != segmentIdsWs[j]) { break; }
    res += tmpRowWs[j * colSize + threadIdx.x];
}
asc_atomic_add(outputAddr + segmentIdsWs[i] * colSize + threadIdx.x, res);
```

- 来源：`index/segment_sum/op_kernel/arch35/segment_sum_simt.h`

#### K9. scatter_add_with_sorted：排序后段内规约，仅段首线程写

- 适用算子：scatter_add_with_sorted
- 策略说明：每线程负责 updates 一个元素；先与前一索引比较——相同则 continue（由段首线程代劳）；段首线程向后扫描整个等值段串行累加，最后对每个目标行只做一次 `asc_atomic_add`。重复索引越多，跳过线程越多、原子冲突越少。另有 CutIndices 变体：indices 远多于 var 行数时 y 维线程各扫一段连续 indices 区间。

```cpp
U varRow = sortedIndices[indiceRow];
if (indiceRow != startIndices && varRow == sortedIndices[indiceRow - 1]) { continue; }  // 非段首跳过
T sumRes = 0;
for (ADDR_T j = indiceRow; j < endIndices && sortedIndices[j] == varRow; j++) { sumRes += updates[j * totalCol + colIdx]; }
asc_atomic_add(var + varRow * totalCol + colIdx, sumRes);
```

- 来源：`index/scatter_add_with_sorted/op_kernel/arch35/scatter_add_with_sorted_simt.h`

#### K10. scatter_add_with_sorted 确定性两阶段：跨界段落 workspace，二次按序归并

- 适用算子：scatter_add_with_sorted（deterministic）
- 策略说明：Step1 每核只把完全落在本核内的段直接原子加；核边界首段/尾段的 partial sum 连同 id 写 workspace（每核 2 行），并特判"整核都是同一段且前后都跨核"（flag1&&flag2）。Step2 单核按核序遍历 workspace 把同 id 部分和按固定顺序累加后写 var。与 K8 同构，是 sorted 类聚合算子的通用确定性范式。

```cpp
if (isCoreFirstIndices && varRow == sortedIndices[startIndices - 1]) { flag1 = 1; }  // 头索引与前核尾索引相同
if (isCoreLastIndices && varRow == sortedIndices[endIndices]) { flag2 = 1; }        // 尾索引与后核头索引相同
if (flag1 && flag2) { /* 整核同段：两行都写 workspace */ }
else if (flag1) { /* 写 workspace 前半 */ } else if (flag2) { /* 后半 */ }
else { asc_atomic_add(var + varGmOffset, sumRes); }
```

- 来源：`index/scatter_add_with_sorted/op_kernel/arch35/scatter_add_with_sorted_simt_determ.h`

#### K11. sparse_segment_mean：段偏移数组（searchsorted 式）+ 先 sum 后除 + 空段保护

- 适用算子：sparse_segment_mean
- 策略说明：第一阶段在 workspace 生成 `segment_offset[segmentNum+1]`：每线程负责位置 i，比较 segment_ids[i] 与前值，把 `(prevId, curId]` 之间所有段的起始位置都填为 i——**空段由此获得 begin==end**（一次并行 searchsorted）；第二阶段按段归并：`[begin,end)` 内逐行 gather x 累加（非法 indices 按 0 计），`res/(end-begin)` 求均值，begin>=end 写 0 防除零。small inner 形态用 y 维线程段内并行 + UB 树形规约。

```cpp
const SEGMENTIDS_T curId = (i < outterSize) ? Clip(segment_ids[i], segmentNum) : segmentNum;
const SEGMENTIDS_T prevId = (i == 0) ? -1 : Clip(segment_ids[i - 1], segmentNum);
for (SEGMENTIDS_T id = prevId + 1; id <= curId; ++id) { segment_offset[id] = i; }
// 计算阶段：
res = empty ? 0 : (res / (end - begin));
```

- 来源：`index/sparse_segment_mean/op_kernel/arch35/sparse_segment_mean_simt_base.h`

#### K12. sorted_sparse_segment_mean_grad：weight 预计算（除零保护）+ 梯度按段广播回

- 适用算子：sorted_sparse_segment_mean_grad
- 策略说明：mean 的梯度是 `grad[seg]/seg_size`。复用 K11 的段偏移生成（对 segment_ids 和 indices 各做一次 searchsorted）；`weight[seg] = 1/max(seg_size,1)` 预计算防除零。主计算按输出行分核：对行 globalIndex，遍历 `[begin,end)` 内 location，经 `segmentIds[location[loc]]` 找梯度来源段，累加 `x[seg]*weight[seg]`，空行写 0。

```cpp
OUTTER_T seg_size = segment_offset[i] - segment_offset[i - 1];
seg_size = (seg_size > 0) ? seg_size : 1;
weight[i - 1] = 1.0f / seg_size;
// 主计算：res += segValid ? x[seg*innerSize + col] * weight[seg] : 0;
```

- 来源：`index/sorted_sparse_segment_mean_grad/op_kernel/arch35/sorted_sparse_segment_mean_grad_simt_base.h`

#### K13. sparse_segment_sum_grad：确定性 gather-add + double 位运算加法

- 适用算子：sparse_segment_sum_grad
- 策略说明：与"scatter 到输出"相反的"按输出 gather"思路：每线程负责一个输出元素 `(row, k)`，顺序扫描全部 N 个 `(indices[j], segmentIds[j])`，凡 `indices[j]==row` 则累加。**每个输出元素由唯一线程写，零原子、天然确定性**（代价 O(outputDim0×N)，适合 N 小）。针对 arch950 不支持 double 运算，内置 `DoubleAddBits`——uint64 位操作完整实现 IEEE754 双精度加法（含 NaN/Inf/非规格化）。

```cpp
for (IDX_T elemIdx = blockIdx.x * blockDim.x + threadIdx.x; elemIdx < totalOutputElements; elemIdx += blockDim.x * gridDim.x) {
    IDX_T row = elemIdx / innerSize, k = elemIdx % innerSize;
    float sum = 0.0f;
    for (IDX_T j = 0; j < n; ++j) {
        if (indices[j] == row) { sum += grad[segmentIds[j] * innerSize + k]; }
    }
    output[elemIdx] = static_cast<T>(sum);
}
```

- 来源：`index/sparse_segment_sum_grad/op_kernel/arch35/sparse_segment_sum_grad_simt.h`

#### K14. index_put_with_sort_v2：预排序 indices + do-while 聚合重复项，确定性写

- 适用算子：index_put_with_sort_v2
- 策略说明：输入 sortIndices（已排序）+ posIdx（原始位置）。每线程负责一个排序后位置：与前一项相同则 continue；段首线程用 do-while 沿等值段推进，经 posIdx 间接寻址 values 累加——重复项排序后相邻，聚合无需原子，单写者天然确定性。`AccumType` 提升小位宽类型（int8/bool→int32，half→float）；bool accumulate 特化为按位或。

```cpp
uint64_t idxedSelfIdx = sortIndices[curIdxedIdx];
if (curIdxedIdx != 0 && sortIndices[curIdxedIdx - 1] == idxedSelfIdx) { continue; }
AccumT accumValue = 0;
do {
    uint64_t idxedValueIdx = posIdx[curIdxedIdx] * idxedValueStride;
    if constexpr (std::is_same_v<TX, bool>) { accumValue |= values[idxedValueIdx]; }
    else { accumValue += values[idxedValueIdx]; }
} while (ACCUMULATE && ++curIdxedIdx < indexedDimSize && sortIndices[curIdxedIdx] == idxedSelfIdx);
WriteBack<TX, AccumT, ACCUMULATE>(output, idxedSelfIdx, accumValue);
```

- 来源：`index/index_put_with_sort_v2/op_kernel/arch35/index_put_with_sort_v2.h`

#### K15. sort_lib 多核 LSD radix sort：逐字节 pass + decoupled lookback + SIMT scatter

- 适用算子：sort_lib（公共排序库）
- 策略说明：对 `sizeof(ValT)` 个字节各做一轮 LSD pass：(1) GetGlobalExclusiveSum——各核把 tile 当前字节抽成 uint8 key（signed/fp 先 Twiddle 翻转保序），建 256 bin 直方图落 GM 并原子加汇总；(2) ComputeOnePass——tile 内 Sort<uint8_t> 排序得局部 permutation，跨 tile 全局偏移用 decoupled lookback（AGGREGATE_READY/PREFIX_READY 状态发布-轮询）；最后 SIMT VF 按 `全局bin偏移 + tile前序 + tile内cumsum` 散射 (value, index) 到双缓冲 GM，轮间乒乓。

```cpp
for (int i = tileId - 1; i >= 0; --i) {
    while (true) {
        CopyGmToUb(allTileHistBuffer, xLocal, roundOffset + histTileOffset, RADIX_SORT_NUM);
        asc_vf_call<LookbackCheckStateVF<CountT>>(...);
        if (aggReadyCountScalar == RADIX_SORT_NUM) { mode = AGGREGATE_READY_FLAG; break; }
        if (PrefixReadyCountScalar == RADIX_SORT_NUM) { mode = PREFIX_READY_FLAG; break; }
    }
    if (mode == PREFIX_READY_FLAG) { break; }
}
```

- 来源：`index/sort_lib/op_kernel/arch35/sort_lib/sort_lib_core.h`

#### K16. bucketize_v2：每线程一个查询的二分查找（固定迭代轮数 + RIGHT 语义）

- 适用算子：bucketize_v2
- 策略说明：每个查询值一个线程 grid-stride；在 GM 有序 bound 数组上二分：循环次数为 tiling 预计算 maxIter（固定轮数代替 while，线程间无发散提前退出），`mid = left + ((right-left)>>1)` 防溢出；RIGHT 模板参数区分 lower_bound/upper_bound。bound 留 GM 靠 DCache 吸收随机访存——SIMT 相对 SIMD 在大 bound 场景的优势。

```cpp
for (int64_t i = 0; i < innerMaxIter; i++) {
    if (left >= right) { break; }
    INDICES_T mid = left + ((right - left) >> 1);
    bool cond = RIGHT ? !(bound[mid] > value) : !(bound[mid] >= value);
    left = cond ? mid + 1 : left;
    right = cond ? right : mid;
}
return left;
```

- 来源：`index/bucketize_v2/op_kernel/arch35/bucketize_v2_common_simt.h`

#### K17. add_row_ranges：numpy 负索引语义 + Kahan 补偿求和

- 适用算子：add_row_ranges
- 策略说明：每线程处理输出元素 `y[r,c] = x[r,c] + sum(src[start:end, c])`：线性下标用**原生整数除法**分解（注释明确记录弃用 UintDiv 快除的原因——magic 乘法在大下标时溢出）；行范围完整实现 numpy 切片语义（负索引解析为 K+value 再 clip）；非空范围用 float32 + **Kahan 补偿求和**（对齐 numpy pairwise summation 精度，O(n·eps) → O(eps)）。

```cpp
uint32_t r = idx / uN;   // 原生除法：magic number 乘法在大下标时溢出
int32_t start = indicesGm[rowBase], end = indicesGm[rowBase + 1];
if (start < 0) { start = (start + K < 0) ? 0 : start + K; }
if (end > K) { end = K; }
float sum = 0.0f, kahanC = 0.0f;
for (int32_t j = start; j < end; j++) {
    float val = ToFloat<T>(srcGm[j * N + c]);
    float y = val - kahanC; float t = sum + y;
    kahanC = (t - sum) - y; sum = t;
}
```

- 来源：`index/add_row_ranges/op_kernel/arch35/add_row_ranges_simt.h`

#### K18. concat_offset：前缀和式偏移计算（UB 中转 + syncthreads）

- 适用算子：concat_offset
- 策略说明：输出 y[t][d] 为第 t 个 tensor 在第 d 维的前缀偏移。二维线程（y=tensor 序号，x=维号）：x==0 的线程经 tensor list 指针间接寻址读出该 tensor 的 shape[concatDim] 存 UB，syncthreads 后负责 concatDim 列的线程对 `tmpLocal[0..y)` 串行累加得前缀偏移。tensor list 用"首元素存偏移 → 偏移>>3 得指针表"的间接寻址协议。

```cpp
if (curCalIdx_x == 0) {
    __gm__ uint64_t* xDataAddr = reinterpret_cast<__gm__ uint64_t*>(x);
    __gm__ uint64_t* xDataPtr = xDataAddr + (*xDataAddr >> 3);
    tmpLocal[curCalIdx_y] = reinterpret_cast<__gm__ T*>(*(xDataPtr + curCalIdx_y))[concatDim];
}
asc_syncthreads();
if (curCalIdx_x == concatDim) { for (int32_t i = 0; i < curCalIdx_y; ++i) { value += tmpLocal[i]; } }
```

- 来源：`index/concat_offset/op_kernel/arch35/concat_offset_simt.h`

---
## 十、Foreach 多张量逐元素类（Foreach）

> 范围：`foreach/`（约 50 个算子）。公共件在 `foreach/foreach_utils/`（kernel 侧 `foreach_regbase_*.h`、tiling 侧 `foreach_regbase_tiling.{h,cpp}`）；每个算子自带 `*_simt.h`、`*_tiling_data.h`。
> arch35 上 foreach 存在两条实现路线：**SIMT 新路径**（`*_simt.h`，线程级并行，GM 直读写，无 UB 搬运）与 **regbase 矢量路径**（`*_regbase.h`，CRTP 基类，UB 队列 + DataCopyPad）。

### Tiling 策略

#### T1. 扁平化一维逻辑空间 + 每核 tensor 区间表

- 适用算子：foreach_add_list、foreach_binary_op 等二元 tensor-list
- 策略说明：把所有 tensor 按列表顺序拼接成长度 totalElements 的一维逻辑空间；均分后 tiling 为**每个核**预计算覆盖的 tensor 区间：起始/终止 tensor 下标 + 首/尾 tensor 内局部偏移。kernel 无需再定位 tensor，直接按表迭代。分核点可落在 tensor 内部。

```cpp
class ForeachAddListTilingData {
    int64_t tensorDataCountList[256];       // 每 tensor 元素数
    uint16_t tensorStartList[80];           // 每核起始 tensor
    uint16_t tensorEndList[80];
    int64_t tensorStartOffsetList[80];      // 首 tensor 内偏移
    int64_t tensorEndOffsetList[80];        // 尾 tensor 内偏移
};
// tiling：均分 + 32 对齐 + 反推核数，然后对每个核两次线性扫描定位首尾 tensor
int64_t perCoreElements = CeilAlign(CeilDiv(totalElements, needCoreNum), 32);
for (int64_t core = 0; core < needCoreNum; core++) { /* 扫 tensorDataCountList 填表 */ }
```

- 来源：`foreach/foreach_add_list/op_host/arch35/foreach_add_list_tiling_arch35.cpp`

#### T2. 扁平化累计偏移表（cumulativeOffsets，全局形态）

- 适用算子：foreach_lerp_list、foreach_pow_list
- 策略说明：tiling 只输出全局累计偏移表 `cumulativeOffsets[i] = 前 i 个 tensor 元素数之和`，不预计算 per-core 区间；核内边界由 kernel 用 `coreId * perCoreElements` 推导，线程运行时查表定位 tensor。tiling 更轻，复杂度转移到 kernel。

```cpp
for (uint64_t i = 0; i < tensorNum; i++) {
    totalElements += tensorShapePtr->GetStorageShape().GetShapeSize();
    tilingData->cumulativeOffsets[i] = totalElements;   // 边扫边累计
}
int64_t perCoreElements = CeilAlign(std::max(1024L, CeilDiv(totalElements, coreNum)), 32);
```

- 来源：`foreach/foreach_lerp_list/op_host/arch35/foreach_lerp_list_tiling.cpp`

#### T3. 仅记录 per-tensor 元素数表（不做扁平化切分）

- 适用算子：foreach_log、foreach_maximum_scalar(list)、foreach_addcdiv_scalar_list
- 策略说明：tiling 只填 `tensorElements[i]` 和 tensorCount，**不计算任何偏移**；所有核共同遍历全部 tensor，核间靠 SIMT grid-stride 自然分摊。addcdiv_scalar_list 按**最大单 tensor 元素数**决定核数，保证最大 tensor 内部有足够并行度。

```cpp
int64_t maxTensorElements = 0;
for (i...) { tilingData->perTensorElementNum[i] = numel; maxTensorElements = std::max(maxTensorElements, numel); }
int64_t needCoreNum = std::min(coreNum, CeilDiv(maxTensorElements, 1024));
```

- 来源：`foreach/foreach_addcdiv_scalar_list/op_host/arch35/foreach_addcdiv_scalar_list_tiling.cpp`

#### T4. 分核数计算：下限 1024 元素/核 + 32 对齐 + 80 核上限

- 适用算子：全系列
- 策略说明：`needCoreNum = min(coreNum, CeilDiv(totalElements, 1024))`；每核元素数向上对齐 32 后反推真实核数；上限为平台 AIV 核数（arch35 为 80）。

```cpp
constexpr int64_t SINGLE_CORE_MIN_ELEMENTS = 1024;
constexpr int64_t ALIGN_SIZE = 32;
int64_t needCoreNum = std::min(coreNum, CeilDiv(totalElements, SINGLE_CORE_MIN_ELEMENTS));
int64_t perCoreElements = CeilAlign(CeilDiv(totalElements, needCoreNum), ALIGN_SIZE);
needCoreNum = CeilDiv(totalElements, perCoreElements);
```

- 来源：`foreach/foreach_add_list/op_host/arch35/foreach_add_list_tiling_arch35.cpp`

#### T5. 空列表/零元素的退化早退

- 适用算子：全系列
- 策略说明：`totalElements == 0` 时 `needCoreNum = 0`、`SetBlockDim(1)`、跳过偏移计算；kernel 入口判 `needCoreNum == 0` 或 `coreId >= needCoreNum` 早退；kernel 内对空 tensor `continue` 跳过。

```cpp
if (totalElements == 0) {
    tilingData->needCoreNum = 0;
    context->SetBlockDim(1);
    currentWorkspace[0] = 0;
    return ge::GRAPH_SUCCESS;
}
```

- 来源：`foreach/foreach_add_list/op_host/arch35/foreach_add_list_tiling_arch35.cpp`

#### T6. TilingKey 编码：dtype 一维编码 与 op_code×4+dtype 二维编码

- 适用算子：dtype 编码用于 add_list/lerp_list 等；二维编码用于 foreach_binary_op
- 策略说明：普通算子 tilingKey = dtype 序号（FP16=0/FP32=1/INT32=2/BF16=3）；foreach_binary_op 把算子类别也编进 key：`schMode = op_code * 4 + dtypeIdx`，kernel 内 `schMode/4`、`schMode%4` 拆出两个编译期常量，一个 kernel 二进制覆盖 add/sub/mul/div × 4 dtype 共 16 种实例。

```cpp
constexpr uint32_t opCode = schMode / 4;
constexpr uint32_t dtypeIdx = schMode % 4;
if constexpr (dtypeIdx == 0) { ForeachBinaryOpProcessFp16<opCode>(...); }
```

- 来源：`foreach/foreach_binary_op/op_kernel/arch35/foreach_binary_op.cpp`

#### T7. regbase tiling 基类继承体系

- 适用算子：mul_scalar、add_scalar_list、addcmul/addcdiv 系列等 regbase 路线
- 策略说明：`ForeachRegbaseTiling` 继承 `ForeachBaseClass`，固化模板方法；派生类按运算数形态细分：Unary / UnaryScalar / UnaryScalarList / BinaryScalar / Binary / TernaryScalar / TernaryScalarList，50 个算子的 tiling 只需实例化对应类。

```cpp
class ForeachRegbaseTiling : public ForeachBaseClass {
    bool IsCapable() override { return Ops::NN::OpTiling::IsRegbaseSocVersion(context_); }
    void AssignDataToEachCore(int64_t needCoreNum, int64_t elementsPerBlock);
};
class ForeachRegbaseTilingTernaryScalarList : public ForeachRegbaseTilingTernaryScalar {
    ge::graphStatus CheckScalarParam() override;   // 仅标量校验换成列表校验
};
```

- 来源：`foreach/foreach_utils/op_host/foreach_regbase_tiling.h`

#### T8. 元数据全部走 tilingData，workspace 恒为 0

- 适用算子：SIMT 路线全系列
- 策略说明：per-tensor 元数据全部以定长数组（256/80 上限）内嵌在 tilingData 随 tiling 下发，不占 workspace；kernel 侧直接把 tiling GM 指针 reinterpret 成结构体，用 `offsetof` 取数组字段地址传给 VF。

```cpp
__gm__ int64_t* elemCounts = reinterpret_cast<__gm__ int64_t*>(
    reinterpret_cast<__gm__ char*>(tilingGm) + offsetof(ForeachLogTilingData, tensorElements));
asc_vf_call<OpForeachLogSimt<T>>(dim3(THREAD_NUM), tensorCount, elemCounts, x, y);
```

- 来源：`foreach/foreach_log/op_kernel/arch35/foreach_log_simt.h`

### Kernel 策略

#### K1. SimtGetTensorAddr：tensor list 可变参数的 GM 地址表解析

- 适用算子：SIMT 路线全系列
- 策略说明：tensor list 入参指向 GM 元数据：首 8 字节是"指针数组相对起点的字节偏移"，其后是按 idx 索引的 64 位 tensor 首地址数组。`__simt_callee__` 内联函数在 **VF 线程内**直接解引用，实现变长 tensor 列表作为单个 kernel 参数传递。

```cpp
template <typename T>
__simt_callee__ inline __gm__ T* SimtGetTensorAddr(GM_ADDR tensorListPtr, int64_t idx)
{
    __gm__ uint64_t* dataAddr = reinterpret_cast<__gm__ uint64_t*>(tensorListPtr);
    uint64_t tensorPtrOffset = *dataAddr;
    __gm__ uint64_t* tensorPtr = dataAddr + (tensorPtrOffset >> 3);
    return reinterpret_cast<__gm__ T*>(*(tensorPtr + idx));
}
```

- 来源：`foreach/foreach_log/op_kernel/arch35/foreach_log_simt.h`

#### K2. ListTensorDesc：AICore 侧的等价地址表封装

- 适用算子：foreach_add_list、foreach_binary_op 及 regbase 基类
- 策略说明：`__aicore__` 上下文用官方 `ListTensorDesc` 包装同一 GM 布局，`GetDataPtr<T>(t)` 取第 t 个 tensor 指针；Process 先解析出裸指针与局部偏移，再把连续子段基地址传给 VF，VF 内完全无 tensor 概念。

```cpp
ListTensorDesc x1List(reinterpret_cast<__gm__ void*>(x1));
for (int32_t t = startT; t <= endT; t++) {
    __gm__ float* x1_t = x1List.GetDataPtr<float>(t);
    int64_t localStart = (t == startT) ? tilingData->tensorStartOffsetList[coreId] : 0;
    int64_t localEnd = (t == endT) ? tilingData->tensorEndOffsetList[coreId] + 1 : totalCount;
    ...
}
```

- 来源：`foreach/foreach_add_list/op_kernel/arch35/foreach_add_list_simt.h`

#### K3. 四种"扁平空间 → tensor"定位模式

- (a) **per-core 区间表 + 逐 tensor VF 调用**（add_list、binary_op）：核内 for 循环 [startT, endT]，每 tensor 段发射一次 VF，tensor 边界对齐在 tiling 完成，kernel 零查找；
- (b) **全局扁平 + 线程级线性扫描偏移表**（lerp_list）：每线程拿全局 flatIdx 后顺序扫 cumOffsets（≤256 可接受），`localIdx = flatIdx - prevCumSum`；
- (c) **core range ∩ tensor range 求交**（pow_list）：VF 遍历全部 tensor，取交集段分摊；
- (d) **全核遍历全 tensor + grid-stride**（log、maximum_scalar、addcdiv_scalar_list）：不按 tensor 切核，全局线程 id 在每个 tensor 内分摊。

```cpp
// (b) lerp_list：线程定位 tensor 的线性扫描
int32_t tensorId = tensorCount - 1;
for (int32_t t = 0; t < tensorCount; t++) {
    if (flatIdx < cumOffsets[t]) { tensorId = t; prevCumSum = (t > 0) ? cumOffsets[t-1] : 0; break; }
}
// (c) pow_list：区间求交
int64_t myStart = std::max(tStart, coreStart), myEnd = std::min(tEnd, coreEnd);
if (myStart < myEnd) { PowElementRange<T>(x1, x2, y, myStart - tStart, myEnd - tStart, tid, stride); }
```

- 来源：`foreach/foreach_lerp_list/op_kernel/arch35/foreach_lerp_list_simt.h`、`foreach/foreach_pow_list/op_kernel/arch35/foreach_pow_list_simt.h`

#### K4. IDX_T 32/64 位索引双路径 + 线程数随索引宽度切换

- 适用算子：foreach_add_list、foreach_binary_op、foreach_lerp_list
- 策略说明：单 tensor 段 ≤ INT32_MAX 用 int32 + 1024 线程，否则 int64 + 512 线程。`THREAD_NUM_VF` 为 `sizeof(IDX_T)` 的 constexpr 函数。

```cpp
template <typename IDX_T> constexpr uint32_t THREAD_NUM_VF = (sizeof(IDX_T) == 4) ? 1024 : 512;
if (localCount <= INT32_MAX) { Simt::VF_CALL<OpForeachAddListDirectSimt<float, int32_t>>(Simt::Dim3(1024), ...); }
else { Simt::VF_CALL<OpForeachAddListDirectSimt<float, int64_t>>(Simt::Dim3(512), ...); }
```

- 来源：`foreach/foreach_add_list/op_kernel/arch35/foreach_add_list_simt.h`

#### K5. dtype 计算路径：低精度提升 fp32 + `__simt_callee__` cast 链

- 适用算子：全系列
- 策略说明：FP16/BF16 一律升 fp32 计算再降回；`ComputeType<T>` traits 集中定义提升规则。所有被 VF 调用的 helper 必须标 `__simt_callee__` 才能进入 VF 调用链。add_list FP16 路径用 `__hfma` 单舍入对齐 PyTorch FMA 行为。

```cpp
template <typename T> struct ComputeType { using type = T; };
template <> struct ComputeType<half> { using type = float; };
template <> struct ComputeType<int32_t> { using type = int64_t; };
__simt_callee__ inline float CastBf16ToFloat(bfloat16_t val) { return __bfloat162float(val); }
```

- 来源：`foreach/foreach_maximum_scalar_list/op_kernel/arch35/foreach_maximum_scalar_list_simt.h`

#### K6. 三种运算数形态的传递与读取：scalar / scalar_list / tensor_list

- 适用算子：maximum_scalar、maximum_scalar_list、add_list 等
- 策略说明：单 scalar 以 1 元素 GM tensor 传入，AICore 侧读出转计算类型后按值传给 VF（FP16 alpha 甚至手工位展开成 fp32）；scalar_list 整个数组留 GM，VF 内按 tensorIdx 取 `scalars_gm[t]`；tensor_list 经地址表逐 tensor 取指针。

```cpp
// 单 scalar：入口位展开 fp16 alpha → fp32
uint16_t alphaRaw = *((__gm__ uint16_t*)alpha);
uint32_t fbits = (sign << 31) | ((exp + 112) << 23) | (mant << 13);
// scalar_list：VF 内按 tensor 下标取 scalar
S scalarVal = scalarsGm[t];
```

- 来源：`foreach/foreach_add_list/op_kernel/arch35/foreach_add_list.cpp`

#### K7. op 逻辑模板化复用：编译期 OP 派发 与 regbase CRTP 谓词基类

- 适用算子：foreach_binary_op（SIMT）；约 20 个 regbase 算子
- 策略说明：SIMT 侧 `BinaryApply<T, OP>` 用 `if constexpr` 编译期分支 add/sub/mul/div（整数除零显式 guard，浮点走 IEEE inf/nan）；regbase 侧 CRTP：基类封装 Init/Process/CopyIn/Compute/CopyOut 全流程，派生类只实现 `Compute`，基类通过 `Predicate&` 引用派生类——50 个算子的搬运/分核/遍历逻辑零重复。

```cpp
template <typename T, uint32_t OP>
__simt_callee__ inline T BinaryApply(T a, T b)
{
    if constexpr (OP == OP_CODE_ADD) { return a + b; }
    else if constexpr (std::is_integral_v<T>) { return (b == 0) ? 0 : (a / b); }  // 整数除零 guard
    else { return a / b; }
}
// regbase CRTP：
class ForeachMulScalarRegbase : public ForeachRegbaseUnary<T, Tiling, ForeachMulScalarRegbase<...>> {
    __aicore__ inline ForeachMulScalarRegbase() : Base(*this) {}
    __aicore__ inline void Compute(...) { Muls(outLocal, inLocal, this->scalarVal_, dataCount); }
};
```

- 来源：`foreach/foreach_binary_op/op_kernel/arch35/foreach_binary_op_simt.h`、`foreach/foreach_mul_scalar/op_kernel/arch35/foreach_mul_scalar_regbase.h`

#### K8. 语义级特殊值与数值稳定性处理

- 适用算子：foreach_pow_list、foreach_maximum_*、foreach_lerp_list
- 策略说明：pow 的 IEEE 754 判定树必须**内联**在 VF 中（独立的 SafePowf 会被 SIMT 编译器优化掉）；maximum 实现 IEEE 754-2019——NaN 优先传播，相等且为 0 时返回 a+b（区分 +0/-0）；lerp 按 `|w| < 0.5` 选两条数值稳定路径。

```cpp
__simt_callee__ inline float SimtMaximum(float a, float b)
{
    if (isnan(a)) { return a; } if (isnan(b)) { return b; }
    if (a == 0.0f && b == 0.0f) { return a + b; }  // +0 vs -0
    return a > b ? a : b;
}
// lerp：|w|<0.5 → start + w*(end-start)；否则 → end + (w-1)*(end-start)
```

- 来源：`foreach/foreach_maximum_scalar_list/op_kernel/arch35/foreach_maximum_scalar_list_simt.h`

#### K9. SIMT VF 启动与循环约定

- 适用算子：SIMT 路线全系列
- 策略说明：VF 用 `__simt_vf__ __aicore__ LAUNCH_BOUND(THREAD_NUM)` 声明；AICore 侧 `Simt::VF_CALL` 发射；blockIdx 两个层级（AICore 的 GetBlockIdx 核号 vs VF 内 Simt::GetBlockIdx）不可混用。addcdiv 把 `x1 + scalar*(x2/x3)` 写成单表达式帮助编译器融合 FMA。入口双层防御：needCoreNum==0 早退 + 多余核早退。

```cpp
template <typename T, typename IDX_T>
__simt_vf__ __aicore__ LAUNCH_BOUND(THREAD_NUM_VF<IDX_T>) inline void OpForeachAddListDirectSimt(...)
{
    for (IDX_T index = Simt::GetThreadIdx(); index < count; index += Simt::GetThreadNum()) {
        y[index] = x1[index] + x2[index] * alphaVal;
    }
}
// addcdiv：// Single expression: enables compiler FMA fusion for x1 + scalar*(x2/x3)
```

- 来源：`foreach/foreach_add_list/op_kernel/arch35/foreach_add_list_simt.h`

### 附：两条路线的取舍

| 维度 | SIMT 路线（`*_simt.h`） | regbase 路线（`*_regbase.h`） |
|---|---|---|
| 数据通路 | 线程直接读写 GM，无 UB 搬运 | UB 双缓冲队列 + DataCopyPad |
| tensor 定位 | 地址表 + 4 种模式（K3） | T1 per-core 区间表，基类统一迭代 |
| 复用方式 | 模板 traits + tilingKey 编码 | CRTP 谓词基类 + tiling 基类继承 |
| 适用 | 大多数新写算子 | scalar/inplace 等沿用矢量管线算子 |

补充两点（源自参考文档交叉校验）：
- **scalar list 一致性在 tiling 期校验**：`CheckScalarList` 要求 `scalars.shapeSize == totalTensorCount`，scalar dtype 白名单 {F32/F32, F16/F16, F16/F32, BF16/F32, INT32/INT32}（`foreach/foreach_utils/op_host/foreach_regbase_tiling.cpp`）。
- **foreach 全族无原子、无同步**：对 foreach 全目录 grep `asc_atomic_add|asc_syncthreads|SetScheduleMode` 均无匹配（reduce 类 foreach_norm 除外）——纯 embarrassingly parallel，是 SIMT 最省心的算子族。

---
## 十一、池化类（Pooling）

> 范围：`pooling/`（adaptive_avg/max_pool2d/3d 及 grad、avg_pool 系列、max_pool 系列、dilation2_d，及公共目录 adaptive_pool3d_common、pool_3d_common、pool_grad_common）。
> 骨架：Tiling 侧"输出（或 gradX）总元素数分核 + magic 除法位宽/布局/重叠编码进 tilingKey + 多模板 IsCapable 仲裁"；Kernel 侧"每线程一个元素 + Grid-Stride + UintDiv 快除坐标分解 + floor/ceil(In2Out/Out2In) 窗口公式"。

### Tiling 策略

#### T1. 按输出（或梯度输入）元素总数分核，threads × blockNum 二级映射

- 适用算子：adaptive_avg_pool2d/3d、max_pool_with_argmax_v3、max_pool3d_grad、avg_pool_v2_grad 等
- 策略说明：`totalSize = N*C*(D*)H*W`（前向算输出数，反向算 gradX 输入数），`threads = min(totalSize, MAX_THREAD)`，`blockNum = min(CeilDiv(totalSize, threads), coreNum)`。SIMT kernel 内部 grid-stride，tiling 只需保证总线程数覆盖数据量。adaptive_avg_pool2d 在「H/W 窗口比悬殊且窗口大」时把 threads 从 MIN_THREAD 提升到 MAX_THREAD 摊薄单线程窗口循环。

```cpp
int64_t outputSize = nDim * cDim * hOutDim * wOutDim;
threads_ = std::min(outputSize, MIN_THREAD);
if (FloorDiv(kernelHMax, kernelWMax) >= KERNEL_SIZE_RATIO && kernelHMax * kernelWMax >= KERNEL_SIZE_THRESHOLD &&
    outputSize > MAX_THREAD * coreNum) {
    threads_ = MAX_THREAD;
}
int64_t blockNum = std::min(CeilDiv(outputSize, threads_), coreNum);
context_->SetBlockDim(blockNum);
```

- 来源：`adaptive_avg_pool2d/op_host/arch35/adaptive_avg_pool2d_simt_tiling.cpp`

#### T2. 32/64 位索引与布局编码进 tilingKey

- 适用算子：adaptive_avg_pool2d/3d、avg_pool、max_pool_with_argmax_v3、dilation2_d 等
- 策略说明：以「参与除法/索引的最大数」（含 in*out 乘积与全量元素数）是否超 INT32_MAX 决定 int32/int64 路径；NCHW/NHWC 同样编入 key。avg_pool 用字面 key 911100/911101/911110/911111 区分 {NCHW,NHWC}×{INT32,INT64}；avg_pool_v2_grad 还把 countIncludePad、divisorOverride 编入 key 编译期去分支。

```cpp
if (FORMAT_NCHW) {
    if (xSize <= INT32_MAX && ySize <= INT32_MAX) { return POOL_TILING_KEY_SIMT_NCHW_INT32; }  // 911100
    return POOL_TILING_KEY_SIMT_NCHW_INT64;                                                      // 911110
}
// avg_pool_v2_grad: GET_TPL_TILING_KEY(schMode, format, isInt32Meet, NO_PAD, NO_CHECK, countIncludePad, hasDivisor)
```

- 来源：`avg_pool/op_host/arch35/avg_pool_simt_tiling.cpp`、`avg_pool_v2_grad/op_host/arch35/avg_pool_v2_grad_simt_tiling.cpp`

#### T3. 窗口重叠检测决定 grad 的 scatter（atomic）还是 gather 双 pass 路径

- 适用算子：max_pool_v3_grad、adaptive_max_pool3d_grad、max_pool3d_grad
- 策略说明：`overlap = (sh < kh) || (sw < kw)`：非重叠时多个输出窗口不写同一输入位置，可逐输出位置 first-wins 直写；重叠时必须走「ForwardPass 存 argmax → SyncAll → GatherPass 寄存器累加」两阶段，且仅为重叠模式申请 `totalOutputPos * sizeof(int32_t)` 的 argmax workspace。adaptive_max_pool3d_grad 用「输入不能被输出整除」判定 isOverLap，并叠加确定性标志。

```cpp
bool overlap = (sh < kh) || (sw < kw);
if (overlap) { userWorkspaceSize = totalOutputPos * sizeof(int32_t); }
context->SetScheduleMode(1);  // 两条路径 Process 均使用 SyncAll()，必须 batch mode
// adaptive: isOverLap = (dX % dGrad != 0 || hX % hGrad != 0 || wX % wGrad != 0);
//           deterministicFlag = (GetDeterministic() == 1 && isOverLap) ? 1 : 0;
```

- 来源：`max_pool_v3_grad/op_host/arch35/max_pool_v3_grad_tiling.cpp`、`adaptive_max_pool3d_grad/op_host/adaptive_max_pool3d_grad_simt_tiling.cpp`

#### T4. 多模板注册 + IsCapable 优先级仲裁（SIMT 兜底）

- 适用算子：adaptive_avg_pool2d（7 个模板）、avg_pool/avg_pool_v2、max_pool3d_grad
- 策略说明：框架按优先级数字从小到大尝试 `IsCapable()`：adaptive_avg_pool2d 依次 UpsampleH(0) → SplitH(1) → SplitW(2) → SmallKernel(3) → SplitC(4) → BigKernel(5) → SIMT(100，恒 true 兜底）；avg_pool 为 NCHW SmallKernel(0) → NHWC SmallKernel(1) → BigKernel(2/4) → SIMT(19)。SmallKernel 内部做阈值过滤（kernel 面积上限、stride 离散场景剔除、UB 容量检查），不满足才回落 SIMT。

```cpp
REGISTER_TILING_TEMPLATE("AvgPool", AvgPoolNCHWSmallKernelTiling, 0);
REGISTER_TILING_TEMPLATE("AvgPool", AvgPoolNHWCSmallKernelTiling, 1);
REGISTER_TILING_TEMPLATE("AvgPool", AvgPoolNHWCBigKernelTiling, 4);
REGISTER_TILING_TEMPLATE("AvgPool", AvgPoolSimtTiling, 19);
```

- 来源：`avg_pool/op_host/arch35/avg_pool_*_tiling.cpp`

#### T5. 小窗口 UB 驻留 vs 大窗口分块/分核的阈值判定

- 适用算子：adaptive_avg_pool2d/3d、max_pool3d_with_argmax_v2
- 策略说明：`kernelMinHW < 256` 不进 BigKernel；`kernelHMax*kernelWMax < 128` 才允许 SmallKernel（UB 放得下整个窗口块）；窗口越大越走 BigKernel/分维切分。BigKernel 按 `maxCount / kernelMinHW` 反推每批输出批数，UB 双缓冲。

```cpp
if (avgBigKernelInfo.kernelMinHW < 256) { return false; }
int64_t ubAvailable = ubSize - xDtypeSize * UB_MAX_INDICES_USE_COUNT - 4 * STORE_ADD_SIZE;
avgBigKernelInfo.maxCount = FloorAlign(ubAvailable / BUFFER_NUM, vRegSize) / FLOAT32_BYTES;
avgBigKernelInfo.batchCount = maxCount / kernelMinHW;
```

- 来源：`adaptive_avg_pool2d/op_host/arch35/adaptive_avg_pool2d_big_kernel_tiling.cpp`

#### T6. 每核最小处理量下限 + warp(32) 对齐反推实际核数

- 适用算子：dilation2_d、max_pool_v3_grad、max_pool_grad_grad_with_argmax、avg_pool1_d
- 策略说明：`perCore = CeilDiv(totalElements, maxCoreNum)`，下限 1024，再 32 对齐，最后反推 needCoreNum。零维 tensor 提前走 HandleZeroDimTiling（blockDim=1）。

```cpp
int64_t perCore = (totalElements + maxCoreNum - 1) / maxCoreNum;
perCore = std::max(perCore, PER_CORE_MIN);                    // 1024
perCore = ((perCore + ALIGNMENT - 1) / ALIGNMENT) * ALIGNMENT; // 32 对齐
params.needCoreNum = (totalElements + perCore - 1) / perCore;
```

- 来源：`dilation2_d/op_host/arch35/dilation2_d_tiling.cpp`

#### T7. 反向算子 workspace 预分配 argmax + 批同步调度模式

- 适用算子：max_pool_grad、max_pool3d_grad
- 策略说明：没有 argmax 输入时，tiling 预申请 `n*c*hOut*wOut * indicesSize` 的 GM workspace 供 kernel 第一遍（ComputePos）回写自搜 argmax，第二遍（ComputeBack）消费；`SetScheduleMode(BATCH_MODE)` 保证两次 VF 间 SyncAll 跨核可见。

```cpp
int64_t argmaxCount = gradShapeInfo.GetShapeSize();
currentWorkspace[0] = argmaxCount * indicesSize + WS_SYS_SIZE;
// PostTiling: context_->SetScheduleMode(BATCH_MODE);
```

- 来源：`max_pool_grad/op_host/arch35/max_pool_grad_tiling_simt.cpp`

#### T8. padding 模式（SAME/VALID/CALCULATED）与 ceil_mode 在 host 侧统一推导

- 适用算子：max_pool_v3_grad、dilation2_d、max_pool3d_grad、avg_pool1_d
- 策略说明：host 侧按 paddingMode 推导输出尺寸与 pad（SAME 补半、VALID 不补、CALCULATED 用 pads 属性），kernel 只接收最终标量避免设备端分支。dilation2_d 用「有效卷积核尺寸」`filterHEff = filterH + (filterH-1)*(rateH-1)` 折算膨胀率。

```cpp
int32_t filterHEff = params.filterH + (params.filterH - 1) * (params.rateH - 1);
if (params.paddingMode == "SAME") {
    params.oH = (params.H + params.strideH - 1) / params.strideH;
    params.padTop = std::max((params.oH - 1) * params.strideH + filterHEff - params.H, 0) / 2;
}
```

- 来源：`dilation2_d/op_host/arch35/dilation2_d_tiling.cpp`

#### T9. avg_pool1_d 的 ND 维度折叠与 L_out 裁剪

- 适用算子：avg_pool1_d
- 策略说明：3~8 维 ND 输入前 dimNum-1 维乘积折叠为 NC、最后一维为 L；`ComputeLOut` 支持 ceilMode 并处理「ceil 后最后一个窗口起点越过 L+padLeft 需减 1」的边界裁剪。

```cpp
if (ceilMode) { LOut = (L + padLeft + padRight - ksize + strides - 1) / strides + 1; }
if (padLeft > 0 && (LOut - 1) * strides >= L + padLeft) { LOut -= 1; }
```

- 来源：`avg_pool1_d/op_host/arch35/avg_pool1_d_tiling.cpp`

#### T10. adaptive grad 按 gradX（输入侧）元素数分核 + int64 精细判定

- 适用算子：adaptive_avg_pool2d_grad、adaptive_avg_pool3d_grad、avg_pool_v2_grad
- 策略说明：avg 类反向采用「按输入元素反算输出窗口集合」的 gather 模式（无写冲突），故分核基数是 gradX 大小而非 gradY。int64 判定除了总数还检查 `isize*osize` 乘积（StartIndex 公式里 `outIdx*inLen` 中间量），防 32 位中间溢出。

```cpp
int64_t outDataCount = nX * cX * hX * wX;
int64_t threads = std::min(outDataCount, MAX_THREAD_NUM);
context_->SetBlockDim(std::min(CeilDiv(outDataCount, threads), coreNum_));
bool NeedInt64(int64_t isize, int64_t osize) { return isize * osize > INT32_MAX; }
```

- 来源：`adaptive_avg_pool2d_grad/op_host/arch35/adaptive_avg_pool2d_grad_simt_tiling.cpp`

#### T11. max_pool_with_argmax：NaN 传播语义位编入 tilingKey + 满核 PostTiling

- 适用算子：max_pool_with_argmax、max_pool_grad_with_argmax 系列
- 策略说明：tilingKey 在布局×位宽之上再叠加 NaN 传播语义位（`+= NAN_BASE(100) * nanProp`），把"NaN 是否持续获胜"的行为差异做成编译期模板参数。pool_grad_common 的公共 tiling 类只填 shape，PostTiling 直接 `SetBlockDim(coreNum)` 满核——SIMT kernel 自己 grid-stride，tiling 完全不做 per-core 切分（grid-stride 对分核零依赖的最简形态）。

```cpp
tilingKey = 500001 + nhwc;                                  // NCHW/NHWC × int32
if (outputDataCount > INT32_MAX) { tilingKey = 500011 + nhwc; }  // int64
tilingKey += NAN_BASE /*100*/ * nanProp;                    // NaN 传播语义叠位
// pool_grad_common: PostTiling() { context_->SetBlockDim(coreNum); }  // 满核，kernel 内 grid-stride
```

- 来源：`max_pool_with_argmax/op_host/max_pool_with_argmax_simt_tiling.cpp`、`pool_grad_common/op_host/arch35/max_pool_grad_with_argmax_simt_tiling_common.cpp`

#### T12. 线程数按窗口大小自适应

- 适用算子：adaptive_max_pool3d
- 策略说明：窗口大 → 单线程串行循环长、寄存器驻留中间结果多 → 线程数降到 512（64 寄存器/线程）；窗口小 → 1024 线程提高并行度。

```cpp
// 窗口串行长 → 线程少（寄存器压力大）
threads = (CalKernelSizeOneDimMax(wIn, wOut) > 32) ? 512 : 1024;
```

- 来源：`adaptive_pool3d_common/op_host/arch35/adaptive_max_pool3d_simt_tiling.cpp`

### Kernel 策略

#### K1. 每线程一个输出元素，floor/ceil 公式反算输入窗口（magic 快除）

- 适用算子：adaptive_avg/max_pool2d/3d（前向）
- 策略说明：adaptive pooling SIMT 核心模式：线程 index 对应一个输出元素，`start = floor(oy*inLen/outLen)`、`end = ceil((oy+1)*inLen/outLen)` 反算输入窗口，所有除法由 host 预计算 magic/shift + VF 内 `Simt::UintDiv` 完成。窗口大小 `div = kH*kW` 每线程独立计算——窗口天然不均，无需额外分支。

```cpp
__simt_callee__ inline static DIV_T CalStartIdx(DIV_T outIdx, DIV_T inLen, DIV_T magicOutLen, DIV_T shiftOutLen) {
    return Simt::UintDiv<DIV_T>(outIdx * inLen, magicOutLen, shiftOutLen);           // floor(oy*inLen/outLen)
}
__simt_callee__ inline static DIV_T CalEndIdx(DIV_T outIdx, DIV_T inLen, DIV_T outLen, ...) {
    return Simt::UintDiv<DIV_T>((outIdx + 1) * inLen + outLen - 1, magicOutLen, shiftOutLen);  // ceil
}
// 主循环：gradient = sum / (kH * kW);
```

- 来源：`adaptive_avg_pool2d/op_kernel/arch35/adaptive_avg_pool2d_simt.h`

#### K2. 边界窗口的等价变形——`(x+1)*in-1)/out + 1` 与 NoMagic 变体

- 适用算子：adaptive_max_pool2d/3d
- 策略说明：max 版用 `(outIdx+1)*inLen - 1` 整除再加 1 实现 ceil；`startIndexNoMagic` 把 `floor(x*in/out)` 拆成 `(x/y)*z + ((x%y)*z)/y`，避免 x*in 超 32 位而不必上 64 位 magic——针对「32 位 FORMAT_T 但 x*in 可能溢出」的精度/性能折中。

```cpp
DIV_T pEnd = Simt::UintDiv<DIV_T>((outIdx + 1) * inLen - 1, magicOutLen, shiftOutLen);
return pEnd + 1;
// startIndexNoMagic: return (x / y) * z + ((x % y) * z) / y;
```

- 来源：`adaptive_max_pool2d/op_kernel/arch35/adaptive_max_pool2d_simt.h`

#### K3. avg_pool 前向——pad 裁剪双区间（poolSize 含 pad、求和不含 pad）与 divisorOverride

- 适用算子：avg_pool、avg_pool_v2、avg_pool1_d
- 策略说明：先按 `ph*sH - tPad` 求窗口，用 `min(hStart+kH, hIn+bPad)` 得含 pad 的 poolSize（countIncludePad 用），再 clamp 到 `[0, hIn)` 得实际求和区间；空窗口写 0。除数三态：divisorOverride 优先，否则按 countIncludePad 选 poolSize 或裁剪后面积。NHWC 坐标分解顺序 C→W→H→N 保证最内维 C 连续。

```cpp
TYPE_T hEnd = min(hStart + kH, hInDim + bPad);
TYPE_T poolSize = (hEnd - hStart) * (wEnd - wStart);
hStart = max(hStart, 0); hEnd = min(hEnd, hInDim);
if (hStart >= hEnd || wStart >= wEnd) { y[i] = 0; continue; }
divisorFactor = divisorOverride ? divisorOverride : (countIncludePad ? poolSize : (hEnd-hStart)*(wEnd-wStart));
```

- 来源：`avg_pool/op_kernel/arch35/avg_pool_simt.h`

#### K4. avg_pool grad——按输入元素反算输出窗口集合，寄存器累加免原子

- 适用算子：avg_pool_v2_grad、adaptive_avg_pool2d_grad、adaptive_avg_pool3d_grad
- 策略说明：反向不走 scatter/atomic：线程绑定一个输入（gradX）元素，用 `(h+pad-k)/stride+1`（下界）与 `min((h+pad)/stride+1, pooledH)`（上界）反算覆盖该输入的所有输出窗口，逐窗口累加 `gradY/divisor`，**天然无写冲突**。每个窗口的 divisor 在累加前按同样的 pad 裁剪规则重算。

```cpp
IDX_T phStart = (h < kernelH) ? 0 : (h - kernelH) / strideH + 1;
IDX_T phEnd = min(h / strideH + 1, pooledHeight);
for (ph...) for (pw...) {
    // 重算该输出窗口的 divisor（pad 裁剪）
    *gradient += static_cast<ACC_VALUE_T>(xDataSlice[i * pooledWidth + j]) / divideFactor;
}
```

- 来源：`avg_pool_v2_grad/op_kernel/arch35/avg_pool_v2_grad_simt.h`

#### K5. adaptive avg grad——In2Out/Out2In 双向窗口公式嵌套

- 适用算子：adaptive_avg_pool3d_grad、adaptive_avg_pool2d_grad
- 策略说明：线程对应一个输入元素；先用 In2Out 公式求「该输入被哪些输出窗口覆盖」（od/oh/ow 范围），再对每个输出位置用 Out2In 公式求该输出窗口尺寸 `kD*kH*kW` 作除数，累加 `gradY/div`。NCDHW 与 NDHWC 两个 VF 仅坐标分解顺序不同。

```cpp
DIV_T odStarts = StartIndexIn2Out<DIV_T>(d, outD, magicInD, shiftInD);
for (od = odStarts; od < odEnds; ++od) {
    DIV_T kD = EndIndexOut2In(od,...) - StartIndexOut2In(od,...);
    for (oh...) for (ow...) {
        DIV_T div = kD * kH * kW;
        gradient += static_cast<float>(gradY[outputIdx]) / static_cast<float>(div);
    }
}
```

- 来源：`adaptive_avg_pool3d_grad/op_kernel/arch35/adaptive_avg_pool3d_grad_simt.h`

#### K6. adaptive_avg_pool2d_grad 的特化 kernel 家族（按输出形状选 fastest 变体）

- 适用算子：adaptive_avg_pool2d_grad
- 策略说明：通用 In2Out 之外还有形状特化：`SmallOutWRow`（OUT_W 编译期常量，预计算 `iw0/iw1/invKW[OUT_W]` 数组 + 行级 owSum 复用）；`SmallOutWSegFast`（W 维划分为 `2*OUT_W-1` 个段，段元信息 scalar 侧预计算到 UB，段内所有 w 共享同一梯度值）；`HExpandExactOutWSmallFast`（H 整数倍放大时 `#pragma unroll` 展开）——「小输出窗口 → 线程内展开复用中间结果」。

```cpp
OFFSET_T iw0[OUT_W], iw1[OUT_W]; float invKW[OUT_W];
for (uint32_t ow = 0; ow < OUT_W; ++ow) {
    iw0[ow] = StartIndexOut2In(ow, inW, ...);
    invKW[ow] = 1.0f / (iw1[ow] - iw0[ow]);
}
for (uint32_t ow = 0; ow < OUT_W; ++ow) { owSum[ow] += gradY[yBase + ow] * invKH * invKW[ow]; }
```

- 来源：`adaptive_avg_pool2d_grad/op_kernel/arch35/adaptive_avg_pool2d_grad_simt.h`

#### K7. max_pool grad（无 argmax 输入）两阶段——先重搜 argmax 再回传

- 适用算子：max_pool_grad、max_pool3d_grad
- 策略说明：`Process() = ComputePos(); SyncAll(); ComputeBack();`。ComputePos：每输出元素一个线程扫描窗口，`CycleUpdate`（大于更新，NaN 恒胜）重算最大值并把 argmax 写 workspace（`while(start<0) start+=dilation` 跳过 pad）。ComputeBack：每输入元素一个线程，反算输出窗口集合，仅当 `argmax[outputIdx] == inputIdx` 时累加——gather 免原子结构。

```cpp
hStart = ph * strideH - padH;
while (hStart < 0) { hStart += dilationH; }   // pad 对齐到 dilation 栅格
// ComputeBack:
if (argmax[outputIdx] == inputIdx) { gradient += gradY[outputIdx]; }
```

- 来源：`max_pool_grad/op_kernel/arch35/max_pool_grad_simt.h`

#### K8. max_pool grad（有 argmax）——gather 回查 vs scatter 原子加 vs 确定性串行

- 适用算子：max_pool_grad_with_argmax_v3、max_pool3d_grad_with_argmax（gather）；adaptive_max_pool3d_grad（scatter/确定性）
- 策略说明：(a) gather：每输入元素一线程，`topMask[输出] == 局部输入偏移` 命中才累加；(b) scatter（adaptive）：每输出元素一线程读 argmax 定位，非重叠直接 `+=`、重叠 `asc_atomic_add`；(c) 确定性：线程按 nc 分片、nc 内串行遍历所有输出位置做 `+=`，用串行化换可复现。

```cpp
if constexpr (IsDeterministic) {
    for (ncIdx...) { for (dhwIdx...) { xGradData[ncXGradOffset + argmaxData[ncGradOffset + dhwIdx]] += gradData[...]; } }
} else {
    if (isOverLap) { asc_atomic_add(&xGradData[inputIdx], gradVal); } else { xGradData[inputIdx] += gradVal; }
}
```

- 来源：`adaptive_max_pool3d_grad/op_kernel/arch35/adaptive_max_pool3d_grad_simt.h`

#### K9. scatter 前的 GM 清零 VF + DCache 维护

- 适用算子：adaptive_max_pool3d_grad、max_pool_v3_grad
- 策略说明：scatter/原子加路径要求 gradX 先清零：专用 `InitOutputZeroSimt` VF（grid-stride 写 0），末尾 `__syncthreads()` 后线程 0 执行 `__builtin_cce_dcci` 刷 DCache；两个 VF 间 `SyncAll()`。写路径用 `__gm__ volatile` 修饰防 DCache 脏数据覆盖。

```cpp
for (INDEX_T i = threadStart; i < outputSize; i += threadStride) { xGradData[i] = 0; }
__syncthreads();
if (Simt::GetThreadIdx() == 0) { __builtin_cce_dcci(nullptr, 1, 0); }
```

- 来源：`adaptive_max_pool3d_grad/op_kernel/arch35/adaptive_max_pool3d_grad_simt.h`

#### K10. max_pool_v3_grad 双路径——非重叠 first-wins 直写 / 重叠 Forward+Gather 两 VF

- 适用算子：max_pool_v3_grad
- 策略说明：无 argmax 输入且 orig_output 可用。非重叠：逐输出位置扫窗口，第一个等于 outVal 的输入位置即最大值位置（first-wins，与 CPU 参考一致）直接写。重叠：ForwardPass 把每个输出的 argmax volatile 写 GM；GatherPass 每输入元素一线程反算输出集合，`argmax[outPos]==spatialOffset` 则寄存器 FP32 累加一次性写回——**把随机写冲突转为确定性 gather**。32 位索引 1024 线程、64 位 512。

```cpp
for (ki...) for (kj...) {
    if (origInput[inAddr] == outVal) { matched = true; RouteGrad<T>(inAddr, outAddr, grad, outGrad); }
}
// OVERLAP_MODE: asc_vf_call<Forward>(...); SyncAll(); asc_vf_call<Gather>(...);
```

- 来源：`max_pool_v3_grad/op_kernel/arch35/max_pool_v3_grad_simt.h`

#### K11. max_pool_grad_grad（二阶导）——纯 gather：`output[idx] = grad[argmax[idx]]`

- 适用算子：max_pool_grad_grad_with_argmax
- 策略说明：二阶导本质是把 grad 按前向 argmax 位置重新收集：单趟 grid-stride gather。`include_batch_in_index=false`（Local 模式）时 argmax 存 batch 内偏移，需拆批后拼 `batchId * gradBatchStride + argmax[idx]`。每线程一次 GM 读一次写，甚至不需 magic 快除——最简 SIMT kernel。

```cpp
for (uint64_t idx = globalThreadId; idx < totalElements; idx += globalThreadNum) {
    uint64_t batchId = idx / argmaxBatchStride;
    output[idx] = grad[batchId * gradBatchStride + argmax[idx]];
}
```

- 来源：`max_pool_grad_grad_with_argmax/op_kernel/arch35/max_pool_grad_grad_with_argmax_simt.h`

#### K12. max pool 前向 + argmax——CycleUpdate 逐点比较、dilation 步进与 pad 的 while 对齐

- 适用算子：max_pool_with_argmax(_v3)、max_pool3d_with_argmax_v2
- 策略说明：每输出元素一线程，窗口内以 dilation 为步长标量扫描；`CycleUpdate` 用「严格大于或 NaN」更新保证 first-wins（并列取索引最小）。**NaN 传播有两种实现由编译期模板参 `NANPROP_T` 选择**：`NANPROP_T==1` 时 NaN 持续获胜（`if (!(val <= maxVal))` 更新），否则运行期 `isnan` 判断——行为差异在 tiling 期编入 key（见 T11）。argmax 存 channel 内空间偏移（`h*W+w`），配合反向 O(1) 比对。pad 处理用 `while (start < 0) start += dilation` 对齐到第一个 ≥0 且在 dilation 栅格上的位置——比 `max(start,0)` 更精确。小维数坐标分解可直接用普通除法（`index % outW`），只有大 shape 才需要 magic 快除。

```cpp
while (hstart < 0) hstart += dilationH;
float maxval = -INF;
for (h = hstart; h < hend; h += dilationH)
    for (w = wstart; w < wend; w += dilationW)
        SimtProc::CycleUpdate(val, idxOffset, &maxval, &maxidx);
// NaN 两实现：NANPROP_T==1 → if (!(val <= maxVal)) 更新（NaN 恒胜）；否则 if (val > maxVal || isnan(val))
topData[index] = maxval; topMask[index] = maxidx;
```

- 来源：`max_pool_with_argmax_v3/op_kernel/arch35/max_pool_with_argmax_v3_simt.h`

#### K13. NCDHW/NHWC 布局的线程映射——最内维连续、坐标分解顺序随格式切换

- 适用算子：全部
- 策略说明：原则「相邻线程处理相邻 GM 地址」：NCHW 从 W 开始除（W 最内），NHWC 从 C 开始除（C 最内）。dilation2_d 把 `IsNCHW` 做成模板 bool + `if constexpr`，32/64 位再各拆一份共 4 个 VF 变体，编译期消除格式分支。

```cpp
// NHWC 坐标分解：globalIdx = b*oH*oW*C + oh*oW*C + ow*C + c（C 最内先除）
int32_t c = globalIdx - Simt::UintDiv(globalIdx, magicC, shiftC) * C;
// xIdx = IsNCHW ? b*C*H*W + c*H*W + ih*W + iw : b*H*W*C + ih*W*C + iw*C + c;
```

- 来源：`dilation2_d/op_kernel/arch35/dilation2_d_simt.h`

#### K14. dilation2_d 膨胀窗口 offsets 内联计算 + 越界跳过

- 适用算子：dilation2_d
- 策略说明：`y = max_{fh,fw}(x[b, ih, iw, c] + filter[fh, fw, c])`，膨胀采样 offsets 不预计算成表，每线程在线计算 `ih = oh*strideH + fh*rateH - padTop`，边界 if 跳过 pad 区（等价 pad 处贡献 -inf）。`ih/iw/xIdx` 用 int64_t 防溢出；整数 dtype 先 int64 相加再饱和回窄类型。统一 512 线程（64 寄存器/线程）。

```cpp
for (fh...) for (fw...) {
    int64_t ih = oh * strideH + fh * rateH - padTop;
    int64_t iw = ow * strideW + fw * rateW - padLeft;
    if (ih >= 0 && ih < H && iw >= 0 && iw < W) { maxVal = max(maxVal, x[xIdx] + filter[fIdx]); }
}
```

- 来源：`dilation2_d/op_kernel/arch35/dilation2_d_simt.h`

#### K15. avg_pool1_d 单维窗口轻量化

- 适用算子：avg_pool1_d
- 策略说明：1D 窗口求和只需 `[start,end)` 区间：求和循环里 real_idx 越界跳过、divisor 用裁剪后长度，count_include_pad 时 divisor 用含 pad 区间。half 升 float 累加。magic/shift 经 UB 传给 VF（`DataSyncBarrier<UB>` 保证可见）。

```cpp
int32_t start = strides * w;
int32_t end = min(start + ksize, count_include_pad ? L + padL + padR : L + padL);
if (!count_include_pad) { start = max(start, pad_left); }
int32_t divisor = max(end - start, 1);
for (i = start; i < end; i++) { if (real_idx >= 0 && real_idx < L) { sum += x[input_base + real_idx]; } }
```

- 来源：`avg_pool1_d/op_kernel/arch35/avg_pool1_d_simt.h`

#### K16. SIMT 参数经 UB 传递 + asc_vf_call 启动的通用骨架

- 适用算子：全部
- 策略说明：三段式：(1) scalar 侧 `GetUintDivMagicAndShift` 预计算，`SetValue` 进 UB（TBuf）；(2) `DataSyncBarrier<UB>()` 保证可见；(3) `asc_vf_call<VF>(dim3(THREAD_DIM), ...)` 启动，VF 从 `__ubuf__` 参数读 magic。参数少且全 32 位时直接走寄存器传参变体，省掉 UB 分配与同步。

```cpp
GetUintDivMagicAndShift<DIV_T>(magicC, shiftC, SimtTilingData(1));
SimtParam.SetValue(0, magicH); ...
DataSyncBarrier<MemDsbT::UB>();
asc_vf_call<MaxPoolGradWithArgmaxNchw<...>>(dim3(SimtProc::THREAD_DIM), (__ubuf__ FORMAT_TYPE*)SimtParam.GetPhyAddr(), ...);
```

- 来源：`pool_grad_common/op_kernel/arch35/max_pool_grad_with_argmax_kernel_simt.h`

#### K17. 大窗口的 UB 向量模板路线（SIMT 的互补面）

- 适用算子：adaptive_avg_pool2d（big/small_kernel 等）、adaptive_avg_pool3d、avg_pool
- 策略说明：单输出窗口 ≥256 元素时，SIMT「单线程扫全窗口」负载不均且失去向量化机会，改走 UB 向量模板：窗口块拷入 UB 用 MicroAPI 归约；`adaptive_avg_pool3d_parall_pool.h` 把窗口 startIdx/kernelSize 预计算成表存 UB，按 D→H→W 三维逐级池化 + 转置。SIMT 负责通用形状兜底。

```cpp
__aicore__ inline void CalKernelSize(..., LocalTensor<int32_t> startIdxLocal, LocalTensor<int32_t> kernelSizeLocal);
__aicore__ inline void AvgPoolOnW/H/D(...);   // 三维逐级池化
```

- 来源：`adaptive_pool3d_common/op_kernel/arch35/adaptive_avg_pool3d_parall_pool.h`

#### K18. 索引位宽模板分派与线程数联动

- 适用算子：max_pool_v3_grad、max_pool_with_argmax_v3、adaptive_max_pool2d
- 策略说明：`OFFSET_T`(int32/int64，防负值) 与 `DIV_T`(uint32/uint64，快除) 双模板；线程数绑定位宽（32 位 1024 / 64 位 512）；adaptive_max_pool2d 在 int32×uint32 时免 UB 直接寄存器传参。

```cpp
template <typename IDX_T> static constexpr uint32_t THREADS = (sizeof(IDX_T) == 4) ? 1024 : 512;
if (maxElements <= INT32_MAX) { RunWithIdxType<T, OVERLAP_MODE, FORMAT, int32_t>(...); }
else { RunWithIdxType<T, OVERLAP_MODE, FORMAT, int64_t>(...); }
```

- 来源：`max_pool_v3_grad/op_kernel/arch35/max_pool_v3_grad_simt.h`

---
## 十二、哈希表 / 稀疏优化器 / 损失函数类（Hash/Optim/Loss）

> 范围：`hash/`（embedding_hash_table 系列 5 个）、`optim/`（sparse_apply 系列 6 个 + lars_v2_update）、`loss/`（ctc_loss_v2(+grad)、nll_loss(+grad)、chamfer_distance_grad、sparse_softmax_cross_entropy_with_logits）。

### Tiling 策略

#### T1. SIMT 二维线程块（threadX × threadY）按 embeddingDim 划分

- 适用算子：embedding_hash_table_lookup_or_insert、embedding_hash_table_apply_adam_w
- 策略说明：每核 512 线程划二维：threadX 覆盖 embedding 维（`nextPowerOf2(embeddingDim)`，上限 32，保证一组 threadX 在同一 warp 内可 `__shfl` 广播），threadY 每线程负责一个 key 的查找/插入控制流。

```cpp
uint32_t threadXNum = nextPowerOf2(embeddingDim);
if (threadXNum > WARP_SIZE) { threadXNum = WARP_SIZE; }   // 不超过32的2的幂
uint32_t threadYNum = MAX_THREAD_NUM / threadXNum;
// adam_w: embeddingDim < 512 时 blockX 对齐 32、blockY=512/blockX；否则 blockX=512、blockY=1
```

- 来源：`hash/embedding_hash_table_lookup_or_insert/op_host/arch35/embedding_hash_table_lookup_or_insert_tiling_arch35.cpp`

#### T2. TilingKey 模板分发：通用 kernel 与 embeddingDim 特化 kernel

- 适用算子：embedding_hash_table_lookup_or_insert
- 策略说明：embeddingDim ∈ {1,2,4,8,16,32} 走 OPT_DIM 模板（key=1002），embedding 维作编译期常量、threadX 组大小=warp 内 lane 数=embeddingDim，消除内层循环与取模；其余走 GENERAL（key=1001）。

```cpp
const std::unordered_set<int64_t> optEmbeddingDims = {1, 2, 4, 8, 16, 32};
context->SetTilingKey(optEmbeddingDims.count(embeddingDim) ? TILING_KEY_OPT_DIM : TILING_KEY_GENERAL);
```

- 来源：`hash/embedding_hash_table_lookup_or_insert/op_host/arch35/embedding_hash_table_lookup_or_insert_tiling_arch35.cpp`

#### T3. 按 bucketSize / key 数 / 表数分核（hash 表类）

- 适用算子：init_embedding_hash_table、import、export
- 策略说明：init 按 `CeilDiv(bucketSize, threadDim)` 求核数（每线程一个 bucket）；import 固定全核逐表循环；export 固定 `min(coreNum, 64)` 核 × `min(maxThread, 256)` 线程并 `SetScheduleMode(1)`（kernel 用 SyncAll 做计数→前缀和→导出三段式）。

```cpp
int64_t numBlocks = std::min(CeilDiv(bucketSize, threadDim), coreNum);
// export:
context->SetScheduleMode(1); // kernel 使用 SyncAll，需设置为 batch mode，所有核同时启动
workspace[0] = ASCENDC_TOOLS_WORKSPACE + maxCoreNum * 8 * tableHandlesShapeVal;   // coreSyncWorkspace
```

- 来源：`hash/init_embedding_hash_table/op_host/arch35/init_embedding_hash_table_tiling_arch35.cpp`、`hash/embedding_hash_table_export/op_host/arch35/embedding_hash_table_export_tiling_arch35.cpp`

#### T4. 稀疏优化器：按稀疏元素总数（N × innerDim）分核，最小每核 1024

- 适用算子：sparse_apply_adagrad_v2 / ftrl / ftrl_v2 / rms_prop / adadelta / proximal_adagrad
- 策略说明：高度同构：`totalElements = indices数 × innerSize` 一维工作量，按 1024 元素/核（ftrl 加 32 对齐）算核数与物理核数取 min；tiling 只下行列尺寸，地址划分全交给 kernel grid-stride。

```cpp
int64_t totalElements = N * innerDim;
int32_t calcCoreNum = (totalElements + 1024 - 1) / 1024;
tiling->needCoreNum = std::max(std::min(calcCoreNum, maxCoreNum), 1);
context->SetBlockDim(tiling->needCoreNum);
context->SetLocalMemorySize(ubSize - DCACHE_SIZE - STATIC_UB_ESTIMATE);
```

- 来源：`optim/sparse_apply_adagrad_v2/op_host/arch35/sparse_apply_adagrad_v2_tiling_arch35.cpp`

#### T5. lars_v2_update：广播规范化 + UB 容量驱动切轴 + RANK 模板

- 适用算子：lars_v2_update
- 策略说明：先 PadAndSqueeze + CheckBroadcastShape 得 max_bro_shape；按 effective_rank 选 RANK=4/8 模板；`FindSplitAxis` 按 UB 容量选切分轴，`MultiCoreSplit` 按轴把 tile 均分到核（主尾核模型）；广播轴 stride 置 0 交给 NDDMA 硬件复用元素。

```cpp
int64_t tilingKey = ChooseTilingKey(eff_rank);
FindSplitAxis(max_bro, dtypeSize, ubSize, kPhysNodes, split);
MultiCoreSplit(max_bro, split, coreNum, mc);
// 广播轴 stride=0：if (normal[d] == 1 && bro[d] > 1) { strides[d] = 0; }
```

- 来源：`optim/lars_v2_update/op_host/arch35/lars_v2_update_tiling_arch35.cpp`

#### T6. nll_loss：SIMT / SIMD / EMPTY 三模式按 shape 与 reduction 选择

- 适用算子：nll_loss
- 策略说明：空 tensor 走 EMPTY 直接填零；xDims==1、reduction==none、2D 小 batch、或 4D 走 SIMT（每核 512 线程）；2D 大 batch 需归约走 SIMD mix。sum/mean 额外申请 `maxCoreNum × 2 × sizeof(float)` workspace 存跨核部分和；`calNumInterBlock` 取不超过核数的最大 2 的幂用于跨核二叉树规约对齐。

```cpp
if (xDims == 1 || reduction == 0 || (xDimN < MIX_MODE_THRESHOD && xDims == 2) || xDims == 4) {
    Tiling4NLLLossSimt(context, tilingParams);
} else { Tiling4NLLLossSimd(context, tilingParams); }
if (reduction == SUM || reduction == MEAN) { usrSize = maxCoreNum * sizeof(float) * 2; }
tilingParams.calNumInterBlock = LargestPowerOfTwo(tilingParams.coreNum);
```

- 来源：`loss/nll_loss/op_host/arch35/nll_loss_tiling_arch35.cpp`

#### T7. nll_loss_grad：memset 核与计算核双角色划分

- 适用算子：nll_loss_grad
- 策略说明：输出 x_grad 需先整体清零（只有目标类位置被 scatter 写）。tiling 计算 memset 核数 `min(totalOutElements, aivCoreNum)` 并按 blockPerCore/blockTailCore 均摊清零区间；计算核按 batch 维 grid-stride。两角色可重叠。

```cpp
notVeryImportantProcessCoreNums_ = std::min(totalOutElements, aivCoreNum_);
blockPerCore_ = FloorDiv(totalOutElements, notVeryImportantProcessCoreNums_);
blockTailCore_ = totalOutElements - blockPerCore_ * notVeryImportantProcessCoreNums_;
```

- 来源：`loss/nll_loss_grad/op_host/arch35/nll_loss_grad_tiling_arch35.cpp`

#### T8. ctc_loss_v2：按 batch 分核 + (s 状态 × batch) 二维线程 + 数据依赖触发 host 预取

- 适用算子：ctc_loss_v2
- 策略说明：`InputsDataDependency({INPUT_LENGTHS_IDX, TARGET_LENGTHS_IDX})` 声明数据依赖，tiling host 侧读 target_lengths 求 maxTargetLength 确定 `laInputStride = 2*maxTargetLength+1`。线程块二维化：blockDimX 覆盖状态维 s（上限 512/1024），blockDimY 覆盖 batch。小尺寸启用 1024 线程 + int32 寻址，大尺寸 512 + int64。

```cpp
int64_t dim2 = 2 * maxTargetLength + 1;
if (!IsLargeSize(...)) { MAX_THREAD = 1024; threadTypeInt32 = TRUE; }
int32_t threadsTarget = std::min(MAX_THREAD, dim2);
blockDimX = threadsTarget;
blockDimY = std::min(threadsPerBlockBatch, MAX_THREAD / threadsTarget);
context->SetBlockDim(std::min(gridY, totalCoreNum));
```

- 来源：`loss/ctc_loss_v2/op_host/arch35/ctc_loss_v2_tiling_arch35.cpp`

#### T9. ctc_loss_v2_grad：workspace 三段划分 + 逐段初始化责任到核

- 适用算子：ctc_loss_v2_grad
- 策略说明：workspace 分 logBetaGm（B×T×S，初值 -inf）与 tempGradGm（B×T×C，初值 -inf）两段，tiling 计算每段 initStartBlock/EndBlock/SizePerBlock 把 GM 初始化任务按核区间分摊；三阶段（LogBeta→UpdateLcab→CalGrad）各用不同线程配置。

```cpp
initGradGmSizePerBlock = (batchSize * symbolSet * maxInputLength) / perBlockNum;
initGradGmSizeLastBlock = initGradGmSizePerBlock + (...) % perBlockNum;
```

- 来源：`loss/ctc_loss_v2_grad/op_host/arch35/ctc_loss_v2_grad_tiling_arch35.cpp`

#### T10. chamfer_distance_grad：按 batch 分核 + 严格溢出校验

- 适用算子：chamfer_distance_grad
- 策略说明：**一个 batch 只由一个核处理**（核数 = min(coreNum, batch)），保证每个输出元素只有一个写者，从 tiling 层面支撑 kernel 的"无原子确定性"设计。显式校验各维度不超 INT32_MAX，用 IsMulOverflow/IsAddOverflow 检查溢出。

```cpp
// 一个 batch 只由一个 AICore 处理，因此核数不能超过 batch。
const int32_t needCoreNum = std::min<int64_t>(coreNum_, batch_);
OP_CHECK_IF(IsMulOverflow(batchU64, numNU64), ..., return ge::GRAPH_FAILED);
```

- 来源：`loss/chamfer_distance_grad/op_host/arch35/chamfer_distance_grad_tiling.cpp`

#### T11. sparse_softmax_cross_entropy：A 轴分核 + R 轴全载/切分双模板 + UB 容量反推

- 适用算子：sparse_softmax_cross_entropy_with_logits
- 策略说明：features 看作 A（样本数）× R（类别数）。A 轴按核均分（主尾核）。先试 R 轴全载（用 `GetReduceSumMaxMinTmpSize` 反推临时空间算一次能放的行数）；放不下降级 SPLIT_R：R 轴按 cache line 对齐循环切分，预计算"完全二分累加"参数 kTimes/kTimesTail（R 循环次数分解为 2^k 主块 + 尾块）供 kernel 树形累加。double buffer 标志编进 tilingKey。

```cpp
int64_t aNum_res = (allUbSize - maxValue) / (arBuf + aBuf);
if (aNum_res < perBlock) {
    // 双 buffer 放不下 → 改单 buffer 再试 → 还不行 → SCHID_SPLIT_R
    if (aNum_res < perBlock) { CalTilingDataRSplit(); schIdNum = SCHID_SPLIT_R; }
}
baseTiling_.kTimes = exp2(floor(log2(mainTile)));
baseTiling_.kTimesTail = rLoopTime - kTimes;
```

- 来源：`loss/sparse_softmax_cross_entropy_with_logits/op_host/sparse_softmax_cross_entropy_with_logits_tiling_arch35.cpp`

### Kernel 策略

#### K1. MurmurHash3 作为 key 哈希函数（SIMT callee）+ bucket 布局约定

- 适用算子：hash 全部算子
- 策略说明：哈希计算封装成 `__simt_callee__`（仅可被 VF 上下文调用），对 GM 上 int64 key 按 4 字节块做 MurmurHash3（seed=0）再对 tableSize 取模。bucket 布局：`key(8B) + counter(8B) + flag/state(8B) + values[embeddingDim×4B]`；flag 的最高字节（大端 int32 偏移 20）存放 valid/filter/export/evicted 位，偏移 16 存"key 已发布"状态位。

```cpp
__simt_callee__ inline uint32_t MurmurHash3(__gm__ int64_t* key, int len, uint32_t seed)
{
    for (uint16_t i = 0; i < nblocks; ++i) {
        uint32_t k = blocks[i]; k *= c1; k = rotl(k, r1); k *= c2;
        hash ^= k; hash = rotl(hash, r2) * m + n;
    }
    hash ^= len; hash ^= hash >> 16; hash *= 0x85ebca6b; ...
}
// bucket 布局：TABLE_FLAG_OFFSET_FOR_B32=20（大端高位 flag）、TABLE_STATE_OFFSET=16、COUNTER_OFFSET=8、VALUES_OFFSET=24
constexpr int32_t BIG_ENDIAN_ONE = 16777216; // 0x01000000
```

- 来源：`common/inc/op_kernel/hashtable_common.h`、`hash/embedding_hash_table_lookup_or_insert/op_kernel/arch35/lookup_or_insert_base.h`

#### K2. 开放寻址 + atomicCAS 抢槽 + 状态位发布的并发插入

- 适用算子：embedding_hash_table_lookup_or_insert、import
- 策略说明：线性探测三步协议：(1) 对 bucket 第 20~23 字节 `asc_atomic_cas(flag, 0, BIG_ENDIAN_ONE)`，返回 0 抢到空槽；(2) 抢到后先写 key，再 `__threadfence()`，最后写 state=1（**发布语义**，保证他线程看到 state=1 时 key 一定可见）；(3) 没抢到则自旋等 state==1 再读 key 比较：相等=命中，不等 `(idx+1)%tableSize` 继续探测。CAS 用 int32 是因 AtomicCas 位宽限制，故 valid 位放在大端 int32 最高字节。

```cpp
const int32_t casOrigFlag = asc_atomic_cas((__gm__ int32_t*)(pCurrBucket + TABLE_FLAG_OFFSET_FOR_B32), 0, BIG_ENDIAN_ONE);
if (casOrigFlag == 0) {
    *(__gm__ int64_t*)pCurrBucket = insertKey;
    __threadfence();
    *(__gm__ int32_t*)(pCurrBucket + TABLE_STATE_OFFSET) = 1;   // 发布
    succ = true; break;
} else {
    while (*(__gm__ volatile int32_t*)(pCurrBucket + TABLE_STATE_OFFSET) != 1) { /* 自旋等待 */ }
    if (*(__gm__ volatile int64_t*)pCurrBucket == insertKey) { succ = true; break; }
}
currIdx = (currIdx + 1) % tableSize;
```

- 来源：`hash/embedding_hash_table_lookup_or_insert/op_kernel/arch35/kernel_lookup_or_insert_general.h`

#### K3. 控制线程 + warp shuffle 广播 + threadX 并行拷贝 value

- 适用算子：embedding_hash_table_lookup_or_insert
- 策略说明：每组 threadX（≤32，同 warp）里只有 lane0 执行哈希与线性探测控制流，结果通过 `__shfl(var, 0, threadXNum)` 广播全组；lane0 对 bucket counter 原子加（频率统计），全组 threadX 按 `j = threadXIdx; j += threadXNum` 并行拷 values——避免每线程重复探测，把 GM 读放大到 warp 级并行。

```cpp
succ = __shfl(succ, 0, threadXNum);
currIdx = __shfl(currIdx, 0, threadXNum);
if (threadXIdx == 0) { asc_atomic_add((__gm__ int64_t*)(pCurrBucket + COUNTER_OFFSET), 1); }
for (size_t j = threadXIdx; j < embeddingDim; j += threadXNum) {
    pValues[i * embeddingDim + j] = *(pCurrBucket + VALUES_OFFSET + j * 4);
}
```

- 来源：`hash/embedding_hash_table_lookup_or_insert/op_kernel/arch35/kernel_lookup_or_insert_general.h`

#### K4. evict 标志的 CAS 恢复（与 evict 算子语义互操作）

- 适用算子：embedding_hash_table_lookup_or_insert
- 策略说明：命中已存在 key 时若 bucket 带 EVICTED 位（此前被 evict 算子标记驱逐），CAS 把该位清掉，只有真正完成翻转的线程把 insertCounts++（视为重新插入）。

```cpp
if ((currFlag & EVICTED_FLAG_MASK) != 0) {
    auto oldFlag = asc_atomic_cas(flagAddr, currFlag, currFlag ^ EVICTED_FLAG_MASK);
    if ((oldFlag & EVICTED_FLAG_MASK) != 0) { insertCounts++; }
}
```

- 来源：`hash/embedding_hash_table_lookup_or_insert/op_kernel/arch35/kernel_lookup_or_insert_general.h`

#### K5. 线程级插入计数 → UB → SIMD 规约 → 原子加统计字段

- 适用算子：embedding_hash_table_lookup_or_insert
- 策略说明：每个 Y 线程把私有 insertCounts 写 UB 对应槽；VF 返回后用 `__simd_vf__` 函数（MicroAPI 寄存器级 LoadAlign/Add/Reduce）把 threadYNum 个计数规约成一个 int64，再对 tableHandle 的统计字段做一次 `AtomicAdd<int64_t>`。**SIMT 算、SIMD 规约、单点原子写回三级结构，全局原子降到每核一次**。

```cpp
if (threadXIdx == 0) { pThreadInsertCounts[threadYIdx] = insertCounts; }
VF_CALL<ComputeInplaceReduceSumB64>(pThreadInsertCounts, VL_FOR_B64, threadYNum_, vfLoopNum);
SetWaitFlag<HardEvent::V_S>();
if (insertCounts > 0) { AtomicAdd<int64_t>(pTableHandle_ + HANDLE_SIZE_ALL_OFFSET, insertCounts); }
```

- 来源：`hash/embedding_hash_table_lookup_or_insert/op_kernel/arch35/kernel_lookup_or_insert_general.h`

#### K6. import：逐表循环 + grid-stride 插入 + handle 统计原子维护

- 适用算子：embedding_hash_table_import
- 策略说明：aicore 侧对 tablesCount 张表逐个解析 ListTensorDesc，每表发一次 512 线程 VF；线程 grid-stride 分摊 key，独立完成 hash→CAS 抢槽→写 counter/flag/values 全流程。handle 统计区分新 key（`atomic_add(size_all)`）与已存在 key（export 位未置则 `atomic_sub(size_all_noexport)`）。

```cpp
for (int64_t i = blockIdx * blockDim.x + threadIdx.x; i < keyNum; i += blockNum * blockDim.x) {
    uint32_t hashValue = Hashtbl::MurmurHash3(keyGm + i, 8, 0);
    if (isInsertSucc) {
        if (isNewKey) { asc_atomic_add(tableHandle + HANDLE_SIZE_ALL_OFFSET, 1); }
        else if (!(*filterFlagValue & EXPORT_FLAG_MASK)) { asc_atomic_sub(tableHandle + HANDLE_SIZE_ALL_NOEXPORT_OFFSET, 1); }
    }
}
```

- 来源：`hash/embedding_hash_table_import/op_kernel/arch35/embedding_hash_table_import.h`

#### K7. export：线性扫描全表 + 计数/前缀和/紧凑写出三段式（跨核 SyncAll）

- 适用算子：embedding_hash_table_export
- 策略说明：导出不知道哪些 bucket 非空，按"每核一段 bucket 区间、每线程一段子区间"线性扫描，三阶段：(1) CountPerThread 统计每线程满足条件（valid 未 evicted，new 模式还要未导出）的 key 数写 UB；(2) 核内 ReduceSum + 写 workspace，SyncAll 后每线程对前面所有核/线程计数做前缀和得输出起始偏移；(3) ExportPerThread 二次扫描紧凑写出，同时把 EXPORT 位置位并计数，最后单线程 `asc_atomic_sub` 更新 handle。**用全局同步换确定性紧凑布局，零原子竞争**。

```cpp
int64_t offset = 0;
for (int32_t i = 0; i < blockIdx; i++) { offset += coreSyncWorkspaceGm[tableIndx * maxCoreNum + i]; }
for (int32_t i = 0; i < threadIdx.x; i++) { offset += threadCountKeysToExportUB[i]; }
if (!(flag & EXPORT_FLAG_MASK)) { tableAddrU8[...] |= EXPORT_FLAG_MASK; curThreadRefreshExportFlagNum++; }
```

- 来源：`hash/embedding_hash_table_export/op_kernel/arch35/embedding_hash_table_export.h`

#### K8. init：每线程一个 bucket，顺序写 key/counter/flag/values

- 适用算子：init_embedding_hash_table
- 策略说明：最简 SIMT 模式——512 线程 grid-stride 覆盖 bucketSize，每线程负责一个 bucket 全部字段：key=-1、counter=0、flag=0（配合 K2 的 CAS 初始条件），values 按 initializerMode 从 sampled_values 拷贝或填常量。各 bucket 地址不相交，无需同步。

```cpp
for (int64_t i = blockIdx * blockDim.x + threadIdx.x; i < bucketSize; i += blockNum * blockDim.x) {
    *key = DEFAULT_KEY; *counter = 0; *flag = 0;
    for (int64_t j = 0; j < embeddingDim; ++j) {
        tableValue[j] = (initializerMode == RANDOM_MOD) ? sampledValuesGm[i * embeddingDim + j] : constantValue;
    }
}
```

- 来源：`hash/init_embedding_hash_table/op_kernel/arch35/init_embedding_hash_table.h`

#### K9. apply_adam_w：只读线性探测定位 + threadX 分量级 AdamW 更新 + 块 0 更新 beta power

- 适用算子：embedding_hash_table_apply_adam_w
- 策略说明：更新阶段不再 CAS（表已建好），threadY 线程读 key、hash、按 valid flag 只读线性探测（遇空 bucket 即停），命中后同组 threadX 线程按 `xOffset = threadXNum*xLoopIdx + threadXIdx` 并行更新 embeddingDim 个分量：读 m/v/maxGradNorm 与表内 value，按 AdamW 公式（weight decay 解耦、amsgrad、maximize）更新写回。beta1Power/beta2Power 只由 block 0 更新并 `DataCacheCleanAndInvalid` 刷 cache。

```cpp
while (detectCounts++ < tableSize) {
    if ((currFlag & VALID_FLAG_MASK) == 0) { break; }        // 空bucket，找不到
    else if (currKey == updateKey) { found = true; break; }
    currentIdx = (currentIdx + 1) % tableSize;
}
if (found) {
    float mOutLocal = mLocal * beta1Local + (1 - beta1Local) * gtLocal;
    float vOutLocal = vLocal * beta2Local + (1 - beta2Local) * gtLocal * gtLocal;
    value = value + (lrLocal * mOutLocal / (beta1PowerLocal - 1)) / denom;
}
```

- 来源：`hash/embedding_hash_table_apply_adam_w/op_kernel/arch35/embedding_hash_table_apply_adam_w.h`

#### K10. sparse_apply 系列统一骨架：flat grid-stride + (行,列) 解码 + 读-改-写状态

- 适用算子：sparse_apply_adadelta/adagrad_v2/ftrl/ftrl_v2/proximal_adagrad/rms_prop
- 策略说明：共用骨架：总工作量 = indices 数 × innerSize，grid-stride 取扁平元素，`i = idx / innerSize; j = idx % innerSize` 解码；读 indices[i] 越界检查；按 `rowOffset = index*innerSize + j` gather 优化器状态，行内完成读→更新→写回闭环。**不做任何原子/锁**——重复 index 的正确性依赖调用侧语义（TF sparse apply 对重复 index 未定义顺序），kernel 以吞吐为先。

```cpp
for (uint64_t idx = globalTid; idx < totalU64; idx += stride) {
    int64_t i = idx / innerDim, j = idx % innerDim;
    Tindex index = indices[i];
    if (index < 0 || index >= firstDim) { continue; }
    int64_t rowOffset = index * innerDim + j;
    float accumNew = CastToFloat32<T>(accum[rowOffset]) + gradF32 * gradF32;
    accum[rowOffset] = CastFromFloat32<T>(accumNew);
    var[rowOffset] = CastFromFloat32<T>(varF32 - lr * gradF32 / (sqrtf(accumNew) + epsilon));
}
```

- 来源：`optim/sparse_apply_adagrad_v2/op_kernel/arch35/sparse_apply_adagrad_v2_simt.h`（rms_prop/proximal_adagrad 同构，公式各异）

#### K11. sparse_apply_ftrl：两阶段 out-of-place（先全量拷贝，再稀疏覆盖）

- 适用算子：sparse_apply_ftrl
- 策略说明：ftrl 是 out-of-place 语义（varOut 与输入不同地址），未被索引的行必须保持原值。Phase 1 独立 copy VF 把 var/accum/linear 全量拷到输出；Phase 2 按 K10 骨架只覆盖被索引行。powf 与 TF Eigen 对齐：`sigma = (accum^-lrPower - accumNew^-lrPower)/lr`、`x = clamp(linearNew,±l1) - linearNew`、`varNew = x / (accumNew^-lrPower/lr + 2*l2)`。

```cpp
asc_vf_call<OpSparseApplyFtrlCopyKernel<T>>(dim3(THREAD_NUM), totalVarElements, varGm, accumGm, linearGm, varOutGm, ...);
if (numIndices == 0) { return; }
asc_vf_call<OpSparseApplyFtrlSimtKernel<T, IdxT>>(dim3(THREAD_NUM), numIndices, innerSize, ...);
```

- 来源：`optim/sparse_apply_ftrl/op_kernel/arch35/sparse_apply_ftrl_simt.h`

#### K12. ftrl_v2：特例分支常量折叠 + 防御性 clamp

- 适用算子：sparse_apply_ftrl_v2
- 策略说明：`lr_power == -0.5` 时用 `sqrtf` 替代 `powf`（最常见配置快路径）；`l2_shrinkage == 0` 跳过 shrinkage 项；`fmaf` 融合乘加；对 accum 做 `fmaxf(accum, 0)` 防 powf 对负值产 NaN。

```cpp
float accumOldPow = isLrpNegHalf ? sqrtf(safeAccumVal) : powf(safeAccumVal, -fLrp);
float gradShrink = isL2sZero ? gradVal : fmaf(twoL2s, varVal, gradVal);
float linearNew = fmaf(delta, varVal, linearVal + gradShrink);
```

- 来源：`optim/sparse_apply_ftrl_v2/op_kernel/arch35/sparse_apply_ftrl_v2_simt.h`

#### K13. lars_v2_update：L2 范数标量收尾 + MulAddDst 融合的元素级主链

- 适用算子：lars_v2_update
- 策略说明：L2 范数平方和规约**不在本算子内完成**——wSquareSum/gSquareSum 是前序规约算子的标量输入；本算子只做收尾：每核一次 ComputeCoeff 用 UB Vector API（单元素 LocalTensor 上 Abs→Sqrt→Muls→Add→Adds→Div）算 `coeff = η·‖w‖ / (‖g‖ + wd·‖w‖ + ε)`。主计算链 `g_new = (w*wd + g) * coeff` 用 `__simd_vf__` 的 `MulAddDst`（dst=src0*src1+dst 融合指令）+ Muls 完成。RANK>5 时按 NDDMA 5 维上限拆 CopyIn。

```cpp
AscendC::Sqrt(wNormT, wAbsT, SCALAR_ELEM_COUNT);
AscendC::Div(coeffT, numT, denomT, SCALAR_ELEM_COUNT);
if (td_->use_clip) { AscendC::Mins(coeffT, coeffT, 1.0f, ...); AscendC::Maxs(coeffT, coeffT, 0.0f, ...); }
// 主链：
AscendC::Reg::MulAddDst(gReg, wReg, wdReg, mask);  // gReg = w*wd + g
AscendC::Reg::StoreAlign(gAddr + off, gReg, mask);
```

- 来源：`optim/lars_v2_update/op_kernel/arch35/lars_v2_update_kernel.h`

#### K14. nll_loss：每线程一个样本 gather 目标类 logit + 三级确定性规约

- 适用算子：nll_loss
- 策略说明：none 模式：每线程一个样本，读 target，跳过 ignoreIndex，`y[i] = -weight[target] * x[i*C + target]`；4D 场景结果先由 VF 写 UB outQueue、再由 vector 侧 `DataCopyPad` 搬出（SIMT 写 UB + DMA 搬出的混合管线，输出连续化）。sum/mean 模式：每线程把经手样本累加进 **UB 私有槽**（`ubIdx = 全局样本序号 % 线程数`，天然无冲突），syncthreads 后 UB 内二叉树规约，线程 0 把核级部分和写 GM workspace；SyncAll 后 block 0 跨核规约（先处理非 2 幂尾部再二叉树）。**UB 线程内累加→核内二叉树→GM 跨核二叉树的三级确定性规约**，不用 atomicAdd，浮点结果可复现；归约末尾按 dtype 指定舍入模式（bf16 用 `CAST_EVEN`）。

```cpp
int64_t ubIdx = (i % (blockNums_ * blockDim.x)) % THREAD_DIM;
tmpOut_[ubIdx] -= weight[target] * x[i * C + target];
asc_syncthreads();
SimtComputeBinaryReduction(tmpOut_, tmpWeight_);   // UB 内二叉树
if (threadIdx.x == 0) { tmpSumGm_[blockId_] = tmpOut_[0]; }
// block 0: 跨核二叉树后 yGm_[0] = mean ? Simt::Cast<bf16, float, CAST_EVEN>(tmpSum/tmpWeight) : tmpSum;
// 4D none 模式混合管线：
LocalTensor<T> outUb = outQueue_.AllocTensor<T>();
asc_vf_call<SimtComputeNLLLoss4dNone<U, T>>(dim3{THREAD_DIM}, ..., (__ubuf__ T*)outUb.GetPhyAddr(), ...);
outQueue_.EnQue(outUb);
SimdDataCopyOutFor4d(nhwNum, offset);   // vector 侧 DataCopyPad UB→GM
```

- 来源：`loss/nll_loss/op_kernel/arch35/nll_loss_simt.h`

#### K15. nll_loss_grad：先清零再 scatter 写目标类梯度，mean 模式先广播商

- 适用算子：nll_loss_grad
- 策略说明：memset 核先把 x_grad 清零并 SyncAll；计算核先用微型 VF 把 total_weight/yGrad 搬 UB 算 `tmpOut = yGrad/totalWeight`（mean）；主 VF 每线程一个样本把 `-scale * weight[chosenClass]` 写到目标类位置。输出只写目标类一个位置，依赖前置清零，无并发写冲突。

```cpp
outputGm_[chosenClass + i * localClassNum] = -static_cast<T>(yGrad_[i] * weight_[chosenClass]);
// mean 模式：scale = tmpOut_[0] = singleGrad_(0) / totalWeight_(0)
```

- 来源：`loss/nll_loss_grad/op_kernel/arch35/nll_loss_grad.h`

#### K16. ctc_loss_v2：前向 DP 的线程分配——threadY 一条序列、threadX 一个状态位、t 维串行同步推进

- 适用算子：ctc_loss_v2
- 策略说明：DP log_alpha 规模 (T × S)，S = 2*targetLength+1（target 与 blank 交替展开，`idx&1` 奇偶位取 blank 或 target[idx>>1]）。**threadX 每线程固定负责状态位 s**，t 维串行推进，每个 t 步前 `asc_syncthreads()` 保证全组看到上一行；用 log-sum-exp（先取 max 再 `log1pf(expf(la1-m)+...-1)+m+x`，-1 修正 log1p 精度）更新写 GM。log_alpha 驻留 GM 供 grad 算子复用。targetsDim==1 时 batch 偏移由 aicore 侧对 targetLengths 串行前缀和预算到 UB。

```cpp
for (int32_t t = 1; t < maxInputLength; t++) {
    asc_syncthreads();
    if (t < inputLength && s < 2 * targetLength + 1) {
        float la1 = logAlphaGm[laBatchOffset + laInputStride * (t - 1) + s];
        float la2 = (s > 0) ? logAlphaGm[... + s - 1] : neginf;
        float la3 = haveThree ? logAlphaGm[... + s - 2] : neginf;
        float lamax = fmaxf(la1, fmaxf(la2, la3));
        logAlphaGm[... + t * laInputStride + s] = log1pf(expf(la1-lamax) + expf(la2-lamax) + expf(la3-lamax) - 1) + lamax + x;
    }
}
```

- 来源：`loss/ctc_loss_v2/op_kernel/arch35/ctc_loss_v2_fp32.h`

#### K17. ctc_loss_v2_grad：反向 DP → alpha+beta 累加 → 梯度合成三阶段

- 适用算子：ctc_loss_v2_grad
- 策略说明：阶段间 SyncAll。LogBeta 与前向镜像（t 从 T-2 递减）。UpdateLcab 按 `T×B` 扁平分配线程，每线程对固定 (b,t) 遍历 s∈[0,S) 把 log_alpha+log_beta 以 log-sum-exp 累加进 tempGradGm[b,t,target'(s)]——**同一 (b,t) 内单线程串行、不同线程写不同槽，用"空间换原子"**。CalGrad 按 T×B×C 扁平做 `grad = (expf(lp) - expf(res + nll - lp)) * gradOut[b]`；zeroInfinity 模式跳过 nll==INF 样本。

```cpp
float lcab = tempGradGm[batchOffset + inputOffset + currentTargetPrime];
tempGradGm[...] = (lcab == neginf) ? logAlphaBetaSum
                                   : __logf(__expf(lcab - max) + __expf(logAlphaBetaSum - max)) + max;
// CalGrad: gradGm[...] = (__expf(lp) - __expf(res + nll - lp)) * gr;
```

- 来源：`loss/ctc_loss_v2_grad/op_kernel/arch35/ctc_loss_v2_grad.h`

#### K18. chamfer_distance_grad：以确定性 gather 重建 scatter，彻底避免原子加

- 适用算子：chamfer_distance_grad
- 策略说明：梯度含"所有满足 idx2[b,m]==n 的 m 点贡献之和"（本质是 scatter）。本算子**刻意不用原子**：每个输出元素由唯一线程持有，反向遍历全部 m 做 gather 累加，把 scatter 重建为确定性 gather 循环；配合按 batch 分核（T10）。用位级 IEEE 辅助函数手工处理 ±Inf/NaN 传播（Inf+(-Inf)=NaN 等），与 PyTorch3D CPU 参考逐位一致。

```cpp
float scatterGrad = 0.0f;
for (uint64_t m = 0; m < numM; ++m) {
    if (idx2[point2Index] != n) { continue; }
    scatterGrad = FloatAddIeee(scatterGrad, NegativeGradientIeee(ComputeGradientIeee(...)));
}
const float finalGradient = FloatAddIeee(directGrad, scatterGrad);
// FloatAddIeee：位级判断 NaN/Inf 传播，lhs+rhs 仅在均有限时执行
```

- 来源：`loss/chamfer_distance_grad/op_kernel/arch35/chamfer_distance_grad_simt.h`

#### K19. sparse_softmax_cross_entropy：SIMD 求 max/sum/exp 主链 + SIMT 处理 label scatter/gather

- 适用算子：sparse_softmax_cross_entropy_with_logits
- 策略说明：混合范式：行最大值、`exp(x-max)`、行和、softmax 归一化等规则向量计算全部用 SIMD（MicroAPI + UpdateMask 尾块掩码）；label 相关的**不规则访存**（每行一次 `backprop[label] -= 1`、gather label 位置 logit）交给 1024 线程 SIMT VF，每线程一行。split_r 模板中 label 落在当前 R 分块内才处理；行和跨分块累加用按 2 的幂次索引（`cacheID = CountOfValue<1>(index ^ (index+1)) - 1`）的树形部分和缓存。

```cpp
for (int64_t index = threadIdx.x; index < tileNum; index += blockDim.x) {
    if (labelsAddr[index] >= rMainNum * ci && labelsAddr[index] < rMainNum * ci + rOnceNum) {
        int64_t offset = index * rOnceNumAlign + labelsAddr[index] - rMainNum * ci;
        backPropAddr[offset] -= 1.0f;
        gatherAddr[index] = temp2Addr[offset];
    }
}
```

- 来源：`loss/sparse_softmax_cross_entropy_with_logits/op_kernel/arch35/sparse_softmax_cross_entropy_with_logits_split_r.h`

#### K20. 横切策略：SIMT/SIMD 混合编排公共模式

- 适用算子：全部
- 策略说明：通用编排：(1) `asc_vf_call<VF>(dim3{...}, ...)` 从 aicore 发射 VF，VF 内 grid-stride；(2) VF 后的标量/小向量收尾交还 SIMD/aicore（`__simd_vf__` 或 GetValue/SetValue），中间 `SetFlag/WaitFlag<V_S>` 或 `PipeBarrier<PIPE_ALL>` 同步；(3) 跨核 `SyncAll()` + GM workspace，tiling 必须 `SetScheduleMode(1)`；(4) 表地址等间接指针两级解引用；(5) 半精度统一升 fp32 计算，`if constexpr` 分派降级。

```cpp
asc_vf_call<ComputeAdamW<T>>(dim3{blockX_, blockY_}, tableSize_, keyNum_, ..., gmTableIn_.GetPhyAddr(0), ...);
SyncAll();
// 间接指针：int64_t handleAddr = *(__gm__ int64_t*)tableHandles; pTable_ = *pTableHandle_; ...
```

- 来源：`hash/embedding_hash_table_apply_adam_w/op_kernel/arch35/embedding_hash_table_apply_adam_w.h`

---
## 十三、其他 NN 算子类（Misc）

> 范围：`activation/erfinv`、`activation/threshold`、`control/sleep`、`conv/deformable_offsets(_grad)`、`matmul/sparse_tensor_dense_mat_mul`、`quant/swiglu_group_grad`、`vfusion/multi_scale_deformable_attn_function`。

### Tiling 策略

#### T1. 逐元素算子复用 ElewiseBaseTiling + DAG 模板化分核

- 适用算子：erfinv
- 策略说明：纯逐元素算子 Tiling 直接复用公共 `ElewiseBaseTiling::DoTiling<DAG>`；只负责按输出 dtype 选模板参数、预留 16M workspace 与 120K API buffer、UB 扣 32K DCache。tilingKey 由 schMode × dType 组合。

```cpp
const uint64_t tilingKey = GET_TPL_TILING_KEY(tiling->scheMode, dType);
baseTilingResult = elewiseBaseTiling.DoTiling<ErfinvOp::ErfinvDAG<half>::OpDag>(*tiling, ASCEND_API_BUFFER + DCACHE_SIZE);
```

- 来源：`activation/erfinv/op_host/arch35/erfinv_tiling_arch35.cpp`

#### T2. 轻量自研分核——均分 + 每核最小粒度保护 + 零维短路

- 适用算子：threshold
- 策略说明：`perCoreElements = max(CeilDiv(total/coreNum), 1024)`；`totalElements==0` 强制 blockDim=1 空转返回。threshold 属性在 Tiling 阶段取出直接烘焙进 TilingData（标量随 tiling 下发，kernel 不再解析 attr）。UB 只扣 DCache（128K），无实际 UB 占用。

```cpp
if (totalElements == 0) { tiling.needCoreNum = 1; context->SetBlockDim(1); return ...; }
int64_t perCoreElements = std::max(Ops::Base::CeilDiv(totalElements, physicalCoreNum), PER_CORE_MIN);
tiling.needCoreNum = Ops::Base::CeilDiv(totalElements, perCoreElements);
```

- 来源：`activation/threshold/op_host/arch35/threshold_tiling_arch35.cpp`

#### T3. 值依赖 Tiling（ValueDepend）+ 参数直通 + 固定单核

- 适用算子：sleep
- 策略说明：休眠时长来自输入 tensor 的值，`TilingInputsDataDependency({0})` 声明值依赖，Tiling 阶段 `GetRequiredInputTensor(0)->GetData<int64_t>()` 读出 cycles 校验后透传——不做频率换算（SIMT `clock()` 语义与 CUDA `clock64()` 一致）。固定 `SetBlockDim(1)`，硬性校验 SoC 必须 ASCEND950。

```cpp
IMPL_OP_OPTILING(Sleep).TilingInputsDataDependency({0}).Tiling(SleepTilingFunc)...;
const int64_t* cyclesPtr = cyclesTensor->GetData<int64_t>();
tiling->cycles = *cyclesPtr;
context->SetBlockDim(1);
```

- 来源：`control/sleep/op_host/sleep_tiling.cpp`

#### T4. 按"输出通道点"总数分核 + int32/int64 双模板防溢出

- 适用算子：deformable_offsets（前向）
- 策略说明：每输出元素 `(n, h_out, w_out, c)` 视作采样点，`blockDim = min(ceil(numKernels / 512), maxCoreNum)`；kernel 每线程一点、循环 kh×kw 采样偏移，tiling 只需一维切分。预计算 NHWC 三套 stride 写入 TilingData；按元素总数是否超 int32 选 1000/1001 两套 kernel 模板。

```cpp
numKernels = imgOutWidth * imgOutHeight * imgChannel * imgBatchNum;
blockDimValue = std::min(CeilDiv(numKernels, 512), maxCoreNum);
tilingKey = (input0Size > INT32_MAX || ...) ? SIMT_COMMON_TILING_KEY + 1 : SIMT_COMMON_TILING_KEY;
```

- 来源：`conv/deformable_offsets/op_host/arch35/deformable_offsets_tiling_arch35.cpp`

#### T5. 双阶段分核（清零 + 计算）+ ScheduleMode(1) 核间同步

- 适用算子：deformable_offsets_grad
- 策略说明：「先清零、后 atomicAdd 累加」两阶段分别算分核：清零阶段按 gradX 元素数（clearGradXCoreNum），计算阶段按采样点数 `N*Ho*Wo*G*Kh*Kw`（realCoreNum），BlockDim 取两者最大值；每核内部"均分 + 前 tail 个核多 1 个"。kernel 两阶段间有 `SyncAll()`，必须 `SetScheduleMode(1)`。

```cpp
realUseCoreNum_ = std::max(realCoreNum_, clearGradXCoreNum_);
context_->SetBlockDim(realUseCoreNum_);
context_->SetScheduleMode(1); // kernel 使用 SyncAll，需 batch mode 全核同时启动
```

- 来源：`conv/deformable_offsets_grad/op_host/arch35/deformable_offsets_grad_tiling_arch35.cpp`

#### T6. 三阶段异构分核（init/compute/output 各算各的）+ dtype×adjoint 组合 tilingKey

- 适用算子：sparse_tensor_dense_mat_mul
- 策略说明：① init/output 按输出元素数 `m*p` 分核且每核至少搬 16KB；② compute 按工作量 `nnz*p` 分核（每核 2048 线程）；③ `BlockDim = max(init, compute, 1)`。tilingKey：`1xxxx/2xxxx` 区分 fp16/fp32，末两位编码 adjointA×adjointB，`30000` 空输出、`40000` n=0 全零输出。B16 需 `m*p*4` 的 fp32 workspace 中转。涉及 SyncAll，`SetScheduleMode(1)`。

```cpp
initAndOutUsedCoreNum_ = std::min(CeilDiv(m_*p_, 16KB/4B), aivCoreNum_);
computeUsedCoreNum_ = std::min(CeilDiv(nnz_*p_, 2048), aivCoreNum_);
globalBlockDim_ = std::max({initAndOutUsedCoreNum_, computeUsedCoreNum_, 1LL});
```

- 来源：`matmul/sparse_tensor_dense_mat_mul/op_host/op_tiling/sparse_tensor_dense_mat_mul_tiling_arch35.cpp`

#### T7. 按行分核为主、超宽行场景切换按元素分核；功能开关全量编入 tilingKey

- 适用算子：swiglu_group_grad
- 策略说明：默认 `usedCoreNum = min(totalRows, coreNum)`；但 `totalRows<=2 且 H>=256K` 时按行分核只起 1~2 核严重欠载，特判切换为按总元素数估算核数。模板维度 5 个：`SCHMODE × HAS_CLAMP × IS_WEIGHT × IS_Y_ORIGIN × IS_GROUP_INDEX`，全用 `if constexpr` 编译期裁剪。

```cpp
bool useUltraWideSimt = totalRows <= 2 && H >= 256 * 1024 && isWeight && isYOrigin;
if (useUltraWideSimt) { simtUsedCoreNum = std::min(CeilDiv(totalRows * H, 1024), coreNumAll_); }
uint64_t key = GET_TPL_TILING_KEY(schMode_, hasClamp, isWeight, isYOrigin, isGroupIndex);
```

- 来源：`quant/swiglu_group_grad/op_host/arch35/swiglu_group_grad_simt_tiling.cpp`

#### T8. 按通道数路由 SIMT/Generic 双实现 + SIMT 按输出元素数分核

- 适用算子：multi_scale_deformable_attn_function
- 策略说明：融合大算子保留两套实现：`embedDims >= 64` 走 Generic/SIMD 向量化路径（TPipe/UB 流水）；`< 64` 走 SIMT 路径，`BlockDim = min(ceil(B*Q*H*D / 512), coreNum)`。路由结果编码进 schMode。deterministic 标志下强制 coreNum=1。

```cpp
if (embedDims >= CHANNELS_SIMD_THRESHOLD) {   // 64
    context->SetBlockDim(coreNum); context->SetScheduleMode(1);
    return MSDA_MODE_GENERIC;
}
uint64_t needCoreNum = std::max(std::min((totalOutput + 511) / 512, coreNum), 1UL);
return MSDA_MODE_SIMT;
```

- 来源：`vfusion/multi_scale_deformable_attn_function/op_host/multi_scale_deformable_attn_function_tiling_arch35.cpp`

### Kernel 策略

#### K1. erfinv——SIMT 内置 `erfinvf` 逐元素映射，嵌入 atvoss DAG 流水

- 适用算子：erfinv
- 策略说明：不手写近似公式，直接调 SIMT 数学库 `erfinvf`（设备库提供完整特殊值语义）。设计点在于把 SIMT 调用封装成 DAG 节点（继承 `Vec::ElemwiseUnaryOP`），在 UB 上 1024 线程逐元素映射，前后由 DAG 的 CopyIn/Cast/CopyOut 完成搬运与精度升降——「SIMT 只做计算，搬运与 cast 复用向量化 DAG 基础设施」。

```cpp
template <typename T>
__simt_vf__ LAUNCH_BOUND(1024) inline void ErfinvSimtCompute(__ubuf__ T* x, __ubuf__ T* y, int64_t totalNum) {
    for (int64_t i = threadIdx.x; i < totalNum; i += blockDim.x) { y[i] = erfinvf(x[i]); }
}
template <class T>
struct ErfinvCustom : public Vec::ElemwiseUnaryOP<T, T> {
    __aicore__ inline ErfinvCustom(LocalTensor<T>& dst, LocalTensor<T>& src, uint32_t count) {
        asc_vf_call<ErfinvSimtCompute<T>>(dim3(THREAD_NUM), src.GetPhyAddr(), dst.GetPhyAddr(), count);
    }
};
```

- 来源：`activation/erfinv/op_kernel/arch35/erfinv_dag.h`

#### K2. threshold——Grid-Stride 逐元素 + fp32 升精度比较对齐 golden

- 适用算子：threshold
- 策略说明：典型 grid-stride；为与 golden 严格一致，输入升 fp32 与 fp32 阈值比较，输出常量 0/1 直接以目标 dtype 构造（0.0/1.0 在所有 FP 格式精确可表示，避免 cast 误差）。纯 GM→GM 直读写，无 UB。

```cpp
for (uint64_t idx = blockIdx.x * blockDim.x + threadIdx.x; idx < totalElements; idx += blockDim.x * gridDim.x) {
    output[idx] = (static_cast<float>(input[idx]) > threshold) ? one : zero;
}
```

- 来源：`activation/threshold/op_kernel/arch35/threshold_simt.h`

#### K3. sleep——`clock()` 忙等自旋，单线程模拟 CUDA `<<<1,1>>>`

- 适用算子：sleep
- 策略说明：全仓库最特殊算子：唯一语义是占用 AI Core 若干 cycle。对标 CUDA `clock64()` 忙等，`asc_vf_call<SleepSpin>(dim3(1), ...)` 单线程；`LAUNCH_BOUND(1)`。`#if __NPU_ARCH__ == 3510 && !__CCE_KT_TEST__` 包裹，UT 环境跳过。

```cpp
__simt_vf__ __aicore__ LAUNCH_BOUND(1) inline void SleepSpin(int64_t cycles) {
    uint64_t startClock = clock();
    while (clock() - startClock < static_cast<uint64_t>(cycles)) { }
}
asc_vf_call<SleepSpin>(dim3(1), sleepCycles);
```

- 来源：`control/sleep/op_kernel/sleep.cpp`

#### K4. deformable_offsets 前向——每线程一个输出通道点 + magic 除法多维分解 + 4 邻域双线性 gather

- 适用算子：deformable_offsets
- 策略说明：线程 → 输出元素 `(n, h_out, w_out, c)`，每线程负责 kh×kw 个采样点。magic/shift 分解坐标；每个采样点从 offsets 取 (dh, dw, weight) → 采样坐标 → `DeformableOffsetBilinear` 中对 floor 后 4 邻域分别边界检查后 gather（越界取 0），四权重加权后乘调制权重写回。全 fp32 中间精度。边界策略「邻域点出界则该点贡献为 0」而非整体丢弃。

```cpp
batchNum = Simt::UintDiv(index, mB_, shiftB_); ...
float pointHeight = heightInput + i * dilationH + offsetsGmAddr[offsetAdrr + heightOffset];
float bilinearValue =
      GetInputPointValue(..., heightFloor,   widthFloor,   ...) * (1-hd)*(1-wd)
    + GetInputPointValue(..., heightFloor,   widthFloor+1, ...) * (1-hd)*wd
    + GetInputPointValue(..., heightFloor+1, widthFloor,   ...) * hd*(1-wd)
    + GetInputPointValue(..., heightFloor+1, widthFloor+1, ...) * hd*wd;
y[...] = bilinearValue * offsetPointWeight;
```

- 来源：`conv/deformable_offsets/op_kernel/arch35/deformable_offsets.h`

#### K5. deformable_offsets_grad 反传——每线程一个采样点 + 4 邻域 atomicAdd + 先清零后 SyncAll

- 适用算子：deformable_offsets_grad
- 策略说明：线程 → (batch, h_out, w_out, group, kh, kw) 六维采样点。一个输入像素被多个采样点命中，gradX 累加有写冲突，两阶段：清零 → SyncAll → 计算（每线程对 4 个邻域位置分别 `asc_atomic_add(gradX + 邻域偏移, grad*mask*wi)`，同时用解析公式累加该采样点的 gradOffsetH/W/Mask）。采样点整体越界时 gradOffsets 三项写 0。

```cpp
if (lowH >= 0 && lowW >= 0) {
    for (c...) {
        asc_atomic_add(yGradXGmAddr + (yGradXIdx + posOffset + c), gradGmAddr[gradPrevIdx + c] * gradXW1);
        ComputeForGetFloorValueDeformableGrad(...);   // dOffH/dOffW/dMask 解析式
    }
}
// Process: ComputeSetValueGradX → SyncAll() → ComputeDeformableOffsetGrad
```

- 来源：`conv/deformable_offsets_grad/op_kernel/arch35/deformable_offsets_grad.h`

#### K6. sparse_tensor_dense_mat_mul——每线程一个 (非零元 × p) 工作单元 + COO gather + atomicAdd；B16 走 fp32 workspace

- 适用算子：sparse_tensor_dense_mat_mul
- 策略说明：COO 稀疏 × 稠密：并行单位 `nnz*p`，`elemIdx → (x1VecIdx = elemIdx/p, j = elemIdx%p)`，`asc_atomic_add(y + i*p + j, values[x1VecIdx] * x2[k*p+j])`；adjA/adjB 用 `if constexpr` 展开。**B32 路径**直接对输出原子加（前置清零 + SyncAll）；**B16 路径**硬件无 fp16 原子加：fp32 workspace 清零 → SIMT 原子加进 workspace → SyncAll → SIMD 队列 Cast 回 fp16 写出。

```cpp
for (int32_t elemIdx = currCoreIdx * blockDim.x + threadIdx.x; elemIdx < elemNum; elemIdx += usedCoreNum * blockDim.x) {
    int32_t x1VecIdx = elemIdx / p, j = elemIdx % p;
    int32_t i = ADJ_A ? x1Indices[2*x1VecIdx+1] : x1Indices[2*x1VecIdx];
    int32_t k = ADJ_A ? x1Indices[2*x1VecIdx] : x1Indices[2*x1VecIdx+1];
    asc_atomic_add(y + i*p + j, x1Values[x1VecIdx] * (ADJ_B ? x2[j*n+k] : x2[k*p+j]));
}
```

- 来源：`matmul/sparse_tensor_dense_mat_mul/op_kernel/arch35/sparse_tensor_dense_mat_mul_b32.h`、`..._b16.h`

#### K7. swiglu_group_grad——数值稳定重写的 silu′ 反传 + 开区间 mask + 位级复刻 NumPy pairwise 归约

- 适用算子：swiglu_group_grad
- 策略说明：MoE 风格分组 SwiGLU 反传，每线程一行。三层数值策略：① **公式重写防爆**：`silu'(g̃) = s + f − f·s`，对 `isinf(g)` 特判（+inf→1，-inf→0），避免 `∞·0=NaN`；② **开区间 mask 对齐语义**：全部用浮点 0/1 乘法注入而非分支跳过；③ **gradWeight 位级复刻 NumPy fp32 pairwise summation**：128 元素内 8 累加器 + 固定二叉合并，超过 128 用显式迭代（pathBits + leftPartial 栈）模拟递归二分树，`volatile` 阻止 FMA 收缩与重结合，保证舍入点与 golden 完全一致。gradX 与 gradWeight 乘积融合在同一趟遍历。

```cpp
__simt_callee__ inline float SimtSiluPrime(float g, float s, float f) {
    if (isinf(g)) { return (g > 0.0f) ? 1.0f : 0.0f; }
    return s + f - f * s;
}
// volatile 阻止乘加收缩与重结合，锁定 FP32 舍入点和二叉树加法顺序
__simt_callee__ inline float SimtFp32Mul(float lhs, float rhs) { volatile float r = lhs * rhs; return r; }
// NumPy pairwise 叶子：((r0+r1)+(r2+r3)) + ((r4+r5)+(r6+r7))
```

- 来源：`quant/swiglu_group_grad/op_kernel/arch35/swiglu_group_grad_simt.h`

#### K8. multi_scale_deformable_attn——线程 → (b,q,h,d) 四维分解，内层 (level × point) 双线性采样聚合

- 适用算子：multi_scale_deformable_attn_function（SIMT 路径）
- 策略说明：输出元素为最外层：`idx ∈ [0, B*Q*H*D)`，连续取模分解出 `(d, h, q, b)`——embedDims 最内，相邻线程访问 value 相邻通道，天然合并访存。每线程预算三个基址，内层双重循环 `numLevels × numPoints`：读归一化采样坐标反归一化（`x = xNorm*wL - 0.5`），floor 取 4 邻域**逐点独立边界检查**（越界丢弃），双线性加权后乘注意力权重累加进 fp32 sum。变长 level 用 `levelStartIndex*headEmbed` 摊平寻址。无 UB、无原子（输出元素间无写冲突），纯 gather 型负载。

```cpp
for (int64_t idx = blockIdx*blockDim + threadIdx; idx < totalOutput; idx += gridDim*blockDim) {
    int64_t d = idx % embedDims, h = (idx/embedDims) % numHeads, q = ..., b = ...;
    float sum = 0.0f;
    for (l < numLevels) for (p < numPoints) {
        sum += SampleBilinearPoint(valueGm, samplingLocGm, attnWeightGm, valBase, locBase, weightBase, ...);
    }
    outputGm[idx] = FromFloat<T>(sum);
}
```

- 来源：`vfusion/multi_scale_deformable_attn_function/op_kernel/arch35/ms_deform_attn_simt.h`

### 附：Misc 类共性要点

| 要点 | 体现算子 |
| --- | --- |
| Grid-stride + 模除多维分解（必要时 magic 快除） | threshold、deformable_offsets、sparse_mm、msda、swiglu |
| `if constexpr` 编译期裁剪可选子图 | swiglu_group_grad、sparse_mm |
| 写冲突 → asc_atomic_add +「清零 kernel + SyncAll + 累加 kernel」+ ScheduleMode(1) | deformable_offsets_grad、sparse_mm |
| fp16 无原子加 → fp32 workspace 中转 + SIMD Cast 回写 | sparse_mm (B16) |
| 中间计算升 fp32，输出前一次性降精度 | threshold、erfinv、deformable_offsets、msda、swiglu |
| 数值对齐 golden：公式重写防 ∞·0、volatile 防 FMA 收缩、复刻 NumPy pairwise 树 | swiglu_group_grad |
| 值依赖 Tiling（TilingInputsDataDependency） | sleep、sparse_mm |

---

## 附录 A：SIMT vs SIMD 模板选择的经验阈值汇总

| 判据 | 阈值 | 出处 |
|---|---|---|
| gather 尾轴字节数（SIMT↔SIMD 分界） | 通用 2048B；按 dtype 收紧 B8=218/B16=360/B32=620 | gather_v2 |
| embedding_bag SIMT 准入 | embeddingDim×dtype ≤ 512B | embedding_bag |
| reverse_v2 SIMD 准入 | 尾轴 ≥128B | reverse_v2 |
| scatter_add/update SIMT 准入 | var 尾轴 < 阈值字节；排序场景 <512B | scatter_add |
| histogram 全载/分块/纯 GM 分界 | bins < UB 容量；输入密度 > bins/100；分块 ≤8 轮 | histogram_fixed_width 等 |
| select SIMT 特化 | condition 形如 (a,1,...,1) 且末轴 ≥512B | select |
| pad_v3 SIMT 兜底 | 输出 ≤4KB 或维数 >5 | pad_v3 |
| cummin SIMT 模板 | N<128 且 M>12800 且 R<12800 | cummin |
| cdist SIMT 路径 | M ≤ 256（且矢量路径谓词不胜出） | cdist |
| msda SIMT 路径 | embedDims < 64 | multi_scale_deformable_attn |
| unsorted_segment Sort+SIMT | 入出比 ≥5 且 innerDim < 512 | unsorted_segment_common |
| inplace_index_add 排序 | updates/var ≥ 阈值（重复度高） | inplace_index_add |
| split_v/concat SIMT 准入 | 总量 < 64K×核数、tensor ≤128、大小比 <2 | concat/split_v |

## 附录 B：确定性（deterministic）实现谱系

| 路线 | 机制 | 代表算子 |
|---|---|---|
| 整数原子代浮点原子 | int32 原子加天然可交换确定，最后 cast 回 fp32 | histogram_v2 det_fp32out |
| 并行轴倒置 | 输出侧逐元素 gather 扫描输入，每输出唯一写者 | bincount_determine、sparse_segment_sum_grad、chamfer_distance_grad、avg_pool_grad |
| 排序归并 | indices 排序使同目标相邻，段内串行，段间单写/一次原子 | index_put_with_sort_v2、scatter_reduce_common、segment_sum |
| 跨界段二次归并 | 边界段 partial 写 workspace，单核按固定顺序合并 | segment_sum、scatter_add_with_sorted |
| 行/槽位 ownership | 按行切核 + 核内串行 + 确定性 tie-break（GT 严格大于） | scatter_max_with_argmax、inplace_update |
| mask-max 序号胜出 | `asc_atomic_max(mask+idx, 全局序号)` 竞争写权限，序号最大者（最后更新者）写——确定性 last-write | scatter_update |
| 分段归约 + 补偿 | 固定 (core, partition) 顺序 + TwoSum/五 limb 精确累加 | ragged_bin_count precise |
| 三级树形规约 | UB 线程内 → 核内二叉树 → GM 跨核二叉树（不用原子） | nll_loss |
| 单核串行 | 直接 BlockDim=1 | coalesce_sparse(deterministic)、msda(deterministic)、scatter_nd_sub(Phase2) |
| 串行扫描线 | 扫描轴顺序依赖，每线程一条线 | cummin SIMT、ctc_loss（t 维） |

## 附录 C：性能优化技巧速查

| 技巧 | 说明 | 代表出处 |
|---|---|---|
| magic number 快除 | `GetUintDivMagicAndShift` + `Simt::UintDiv` / `__umulhi` | 全仓库 |
| 索引位宽双路径 | int32+1024 线程 / int64+512 线程 | tan、pooling、gather |
| 循环展开 | 6 路展开交叠加载与原子加延迟；8 路展开 rank 统计 | histogram_fixed_width、sort 两阶段 |
| asc_ldcg/stcg | 绕 L1 cache 的 GM 读写 | histogram、coalesce_sparse、radix_sort |
| UB 别名复用 | 按生命周期复用 buffer 压 UB 峰值 | sort 小轴 |
| bank 冲突 padding | 行跨距为 4×32B 整数倍时加 1 block padding | sort 非尾轴 |
| warp shuffle 规约 | `asc_reduce_add` / 手写 `asc_shfl_down` / `__shfl` 广播 | cosine_similarity、trace、hash |
| dtype 提升扩大拷贝粒度 | 尾轴字节可整除时 fp16→B64 搬运 | gather_v2、index |
| 线程数自适应收缩 | 小规模减半 threadNum 保证核利用率 | gather_v2、select |
| 二维线程块 | (threadX=特征列, threadY=key/bag) 映射 | hash、embedding_bag、segment |
| 边界桶名额协商 | 跨 tile 边界桶计数 + leader 累加 | top_k_v2 radix |
| lookback 软同步 | 状态位内嵌直方图高 2bit 发布-轮询 | sort 多核 radix、sort_lib |
| VF 参数瘦身 | 高维参数经 GM tiling 结构体 / UB 数组传入，寄存器只留热参数 | as_strided、pooling |

---

> 提取完成。覆盖 math 数学类（elementwise/规约扫描/排序/直方图/转换/随机）与 nn 神经网络类（gather/scatter/segment/foreach/pooling/hash/optim/loss/其他）共 13 个算子类别、380+ 条 SIMT 设计策略，每条附源码片段与出处路径。
> 已与另一份 SIMT 策略文档交叉校验融合：重复策略已去重，其独有策略（embedding_no_contiguous、scatter_update mask-max、unique_dim merge-path、pad_v3 合轴/核数调优、concat 按 tensor 数分核、max_pool NaN 语义位、nll_loss UB 混合管线等）已合并入对应章节；跨类别横向归纳（SIMT 定位、冲突谱系、确定性实现、异构协作、host-kernel 强契约）已拆解到 skill 的 tiling-advanced / template-routing / workspace-contract / synchronization / data-movement 等参考文档及本文件附录 B 中。
