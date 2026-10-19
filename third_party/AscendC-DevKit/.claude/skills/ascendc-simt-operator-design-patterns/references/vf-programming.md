# VF 声明与调用规范

## 1. 三层结构：`__simt_callee__` → `__simt_vf__` → `__aicore__` Process

```cpp
// __simt_callee__: 被 VF 调用的设备函数（只能进入 VF 调用链）
__simt_callee__ __aicore__ inline float ComputeOne(float v) { ... }

// __simt_vf__: SIMT 向量化函数（VF），LAUNCH_BOUND 限定每核线程数以控制寄存器占用
template <typename T>
__simt_vf__ __aicore__ LAUNCH_BOUND(1024) inline void OpSimtKernel(int64_t total, __gm__ T* x, __gm__ T* y) { ... }

// __aicore__ Process: 外层标量控制流 + TPipe/UB 管理 + 发射 VF
__aicore__ inline void Process(...) {
    Simt::VF_CALL<OpSimtKernel<T>>(Simt::Dim3(THREAD_NUM), total, x_gm, y_gm);
}
```

- 所有被 VF 调用的 helper 必须标 `__simt_callee__`，否则无法进入 VF 调用链（foreach 公共库注释明确）。

## 2. LAUNCH_BOUND 与寄存器/线程数选择

| 线程数 | 典型场景 | 说明 |
|--------|---------|------|
| 2048 | 纯搬运/少变量（roll、pad、trans_data） | arch35 单核上限 |
| 1024 | 坐标分解多变量（batch_to_space_nd、diag、concat） | 默认档 |
| 512 | 寄存器密集、64 位索引（as_strided、ball_query、pooling） | 512 = 64 寄存器/线程 |
| 256/128/64 | 高维累加、int64 归约（pad_grad_replication、trace） | 随维度递减控寄存器 |

```cpp
// 常见写法：按索引位宽自动分档（int32 索引 1024 线程，int64 砍半）
template <typename IDX_T> constexpr uint32_t THREAD_NUM = (sizeof(IDX_T) == 4) ? 1024 : 512;
template <typename IDX_T> constexpr uint32_t THREAD_NUM_VF = (sizeof(IDX_T) == 4) ? 1024 : 512;
// 注意：LAUNCH_BOUND(n) 与 Simt::Dim3(n) 必须用同一个 constexpr 常量
```

- 出处：`math/tan/op_kernel/arch35/tan_simt.h`、`pooling/dilation2_d/op_kernel/arch35/dilation2_d_simt.h`

## 3. 参数类型支持与限制

| 类型类别 | 支持 |
|---------|------|
| 指针 | `__gm__ T*`、`__ubuf__ T*`、`GM_ADDR` |
| 标量 | bool/int8~int64/uint8~uint64/float/half/bfloat16_t |
| 返回值 | 必须 void |

**高维降参数技巧**：VF 参数个数有限，维度 ≥5 时 shape/stride 数组放不下，改用以下方式：
- 只传 `GM_ADDR tiling`，VF 内用 `GET_TILING_DATA_PTR_WITH_STRUCT` 宏直接从 GM 读 tiling 结构体；
- magic/shift 等高频小参数仍走寄存器传参；
- VF 内需数组时用 `__ubuf__` 指针传 LocalTensor 物理地址。

```cpp
template <typename T, uint16_t Dim>
__simt_vf__ LAUNCH_BOUND(THREAD_NUM) inline void SimtStridedDim5(
    __gm__ T* inputGmAddr, __gm__ T* outputGmAddr, GM_ADDR tiling, uint32_t outputBasicIndex, uint32_t count, ...) {
    GET_TILING_DATA_PTR_WITH_STRUCT(AsStridedSimtTilingData, tdGmPtr, tiling);   // 从 GM 读 tiling
    ...
}
```

- 出处：`conversion/as_strided/op_kernel/arch35/as_strided_simt.h`、`pad_v3`（Dim6-8）

## 4. 参数传递三种方式

```cpp
// ① 按值传（标量/half 位转换）：host 读出转计算类型后按值传
__aicore__ 入口里读 alpha → float alphaVal;   // 半精度手动位展开成 fp32
Simt::VF_CALL<K>(Simt::Dim3(n), alphaVal, ...);

// ② GM 指针 + 索引（scalar_list）：VF 内按 tensor 序号读
__simt_vf__ void Compute(..., __gm__ T1* scalars_gm, uint32_t tensorIdx, ...) {
    float s = static_cast<float>(scalars_gm[tensorIdx]);
}

// ③ UB 数组（__ubuf__）：shape/stride/magic 参数打包进 UB 再传指针
//    host: SetValue 写入 → DataSyncBarrier<MemDsbT::UB>() → asc_vf_call(..., (__ubuf__ uint64_t*)paramBuf.GetPhyAddr());
```

- 出处：`foreach/*`（①②③）、`pooling/max_pool3d_grad_with_argmax`（③ 14 个 magic 参数）

## 5. GM_ADDR 直接转换（纯 SIMT 算子）

```cpp
// ✅ 推荐：直接转换 GM_ADDR，避免 GlobalTensor 中转
__gm__ T* x_gm = (__gm__ T*) x;
// ❌ 避免：不必要的 GlobalTensor 中转
GlobalTensor<T> xGlobal; xGlobal.SetGlobalBuffer((__gm__ T*)x, count); auto p = xGlobal.GetPhyAddr();
```

- 出处：`activation/threshold/op_kernel/arch35/threshold_simt.h`（纯 GM→GM 直读写，无 UB）

## 6. 两级 blockIdx 不可混用

外层 `__aicore__` 的 `GetBlockIdx()` 是**算子分核核号**；VF 内的 `blockIdx.x` 是 **VF grid 概念**。需要算子核号时必须在外层读取后显式传参进 VF：

```cpp
const uint32_t launchCoreIdx = static_cast<uint32_t>(AscendC::GetBlockIdx());
asc_vf_call<ScatterByRow<...>>(dim3(THREAD_NUM), launchCoreIdx, usedCoreNum, ...);  // 显式传核号
```

- 出处：`index/ragged_bin_count/op_kernel/arch35/ragged_bin_count_simt.h`（注释明确记录）
