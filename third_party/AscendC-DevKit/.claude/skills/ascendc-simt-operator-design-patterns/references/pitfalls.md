# SIMT 踩坑清单（事故记录与成因）

> 从两仓库源码注释与事故修复中提炼的实战坑点，按"症状 → 成因 → 修复"组织。审查/调试 SIMT 算子前必读。

## 1. 507035 vector core exception（blockDim 未封顶）

- **症状**：大 shape 下运行时 507035 vector core exception。
- **成因**：`SetBlockDim(CeilDiv(total, coreNum))` 让 blockDim 随元素数线性膨胀，远超物理核数。
- **修复**：`usedCoreNum = min(CeilDiv(total, coreNum), coreNum)`，SIMT 核内 grid-stride 覆盖全部元素。
- **出处**：`math/atanh/op_host/arch35/atanh_tiling_arch35.cpp`（源码注释明确记录）

```cpp
int64_t usedCoreNum = Ops::Base::CeilDiv(totalNum, coreNum);
if (usedCoreNum > coreNum) { usedCoreNum = coreNum; }
if (usedCoreNum == 0) { usedCoreNum = 1; }
context->SetBlockDim(usedCoreNum);
```

## 2. VEC_ERROR 越界（host-kernel workspace 公式不一致）

- **症状**：M>1M 时排序越界写穿相邻 region（VEC_ERROR）。
- **成因**：host 侧 workspace 计算带 `"+128 margin"` 近似，未精确复算 kernel 的 padding 公式。
- **修复**：host 精确复算 `padM = P2*runLen0`（P2 把 runLen0 压到 ≤8192 的 2 的幂）。
- **出处**：`index/scatter_reduce_common/op_host/arch35/scatter_reduce_common_tiling.cpp:195-213`
- **通用教训**：workspace 分段公式、magic 参数、per-core 区间表、tiling struct 布局，host 与 kernel 两侧必须逐段一致——这是本体系最主要的正确性风险点。

## 3. magic number 溢出（大索引场景）

- **症状**：`add_row_ranges` 大 shape 下索引算错。
- **成因**：`__umulhi(x,m)` 快除的 magic 乘法在**大下标**时溢出。
- **修复**：改回原生除法 `idx / N`（注释明确记录弃用原因）。
- **出处**：`index/add_row_ranges/op_kernel/arch35/add_row_ranges_simt.h`
- **通用教训**：快除适合常规规模；超大索引 / int64 场景评估 magic 位数限制，必要时用原生除法。

## 4. binary 输出假共享（plain store 实测错误）

- **症状**：binary 直方图只有 6.25% 正确。
- **成因**：多核 plain store 同一 cache line 的 false sharing。
- **修复**：必须原子——`read + asc_atomic_exch`（比裸 exch 快 1.27×）；`asc_atomic_or(0x3F800000)` 更慢。
- **出处**：`math/ragged_bin_count/op_kernel/arch35/ragged_bin_count_simt.h`（注释含 4 种写法实测对比）

```cpp
// plain store WRONG；atomic_or 慢；read+exch 最优
if (output[outputOffset] != 1.0F) { (void)asc_atomic_exch(output + outputOffset, 1.0F); }
```

## 5. 多流死锁（SyncAll 未配 SetScheduleMode(1)）

- **症状**：多流场景下算子卡死。
- **成因**：kernel 内 `SyncAll()` 需要 batch 独占调度，未设 `SetScheduleMode(1)` 则与其他流冲突。
- **修复**：凡 kernel 有 `SyncAll()`，tiling 必须 `context->SetScheduleMode(1)`。
- **出处**：`index/sort_lib/op_kernel/arch35/sort_lib.h`（使用契约注释）

## 6. 两级 blockIdx 混用

- **症状**：分核偏移错乱。
- **成因**：VF 内 `blockIdx.x` 是 VF grid 概念，不是算子分核核号；外层 `GetBlockIdx()` 才是核号。
- **修复**：需要核号时在外层 `__aicore__` 读取后显式传参进 VF。
- **出处**：`index/ragged_bin_count/op_kernel/arch35/ragged_bin_count_simt.h`

## 7. VF 间"以为全核同步"

- **症状**：多个 `Simt::VF_CALL` 之间的数据在跨核场景不一致。
- **成因**：VF 间**仅保证 block 内串行**，不保证全核同步。
- **修复**：需要全核同步时 VF 之间加 `SyncAll()`（配合 `SetScheduleMode(1)`）；与 DMA 的依赖用 event。
- **出处**：`references/synchronization.md`

## 8. int32 中间量溢出（非连续布局 / 规约中间乘积）

- **症状**：非连续 gather / pooling 反向结果错乱。
- **成因**：int64 判定只看了总量，没看**中间乘积** `shape[i]*stride[i]` 或 `isize*osize`。
- **修复**：判定条件加中间乘积；`NeedInt64(isize, osize) = isize*osize > INT32_MAX`。
- **出处**：`index/embedding_no_contiguous`、`pooling/adaptive_avg_pool2d_grad`

## 9. 浮点不确定性（未做确定性处理）

- **症状**：同一输入多次运行结果不同 / 与 golden 对不上。
- **成因**：float 原子加顺序不定；编译器 FMA 收缩/重结合改变舍入。
- **修复**：确定性三路线（输出独占 / 两阶段 partial / mask-max）；volatile 阻止 FMA（见深度策略库附录 B）。
- **出处**：`index/scatter_update`（mask-max）、`math/prod_force_se_a`（volatile 阻 FMA）

## 10. fp16/bf16 原子与精度陷阱

- **症状**：int8/uint8/bool/fp16 原子加行为异常或精度丢失。
- **成因**：这些 dtype 无对应原子指令；half 低精度累加误差大。
- **修复**：先 Cast 到 int32/fp32 workspace 原子加再 Cast 回（三段式）；fp16/bf16 一律升 fp32 计算。
- **出处**：`index/scatter_add`（int8 三段式）、`math/ragged_bin_count`（fp32 补偿）

## 11. 拒绝采样 stride 用错（输出留空洞）

- **症状**：truncated_normal 输出有空洞。
- **成因**：stride 用了 tiling 估算值而非运行时真实线程数 `gridDim.x*blockDim.x`。
- **修复**：跨 VF 调用必须用运行时真实线程数。
- **出处**：`random/stateless_truncated_normal_v2/op_kernel/arch35/stateless_truncated_normal_v2_simt.h`

## 12. compileInfo 空指针

- **症状**：单算子路径（nnopbase）tiling 读 compileInfo 崩溃。
- **成因**：TilingParse 可能未被调用，compileInfo 为 null。
- **修复**：null 时 fallback 直读 `context->GetPlatformInfo()`。
- **出处**：`math/cdist/op_host/arch35/cdist_tiling_arch35.cpp`

## 症状 → 成因速查

| 症状 | 优先排查 |
|------|---------|
| 507035 vector core exception | blockDim 未封顶（坑 1） |
| VEC_ERROR / 越界写穿 | workspace 两侧公式不一致（坑 2） |
| 结果错 / 边界算错 | magic 溢出（坑 3）、int32 中间溢出（坑 8） |
| 只有部分 case 错 | binary 假共享（坑 4） |
| 卡死 / 多流冲突 | SyncAll 未配 ScheduleMode(1)（坑 5） |
| 分核偏移错乱 | 两级 blockIdx 混用（坑 6） |
| 跨 VF 数据不一致 | VF 间未全核同步（坑 7） |
| 输出空洞 | 拒绝采样 stride 用错（坑 11） |
| tiling 崩溃 | compileInfo 空指针（坑 12） |
