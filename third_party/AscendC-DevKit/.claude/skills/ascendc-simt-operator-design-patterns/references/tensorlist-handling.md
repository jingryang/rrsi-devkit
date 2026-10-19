# TensorList 动态输入处理

> tensor-list 类算子（foreach、concat、split_v、embedding_hash_table_import 等）需要处理数量不定的张量列表。两仓库实践出两套地址解析方案 + 4 种"扁平空间→tensor"定位模式。

## 1. ListTensorDesc 内存布局

```
ListTensorDesc:
├── ptrOffset (uint64_t)           // dataPtr 的偏移量
├── tensorDesc[0] (TensorDesc)      // 第 0 个 tensor 描述（dim/index/shape[8]）
├── tensorDesc[1] ...
└── dataPtr[TENSOR_DESC_NUM] (uintptr_t[])  // 数据指针数组
```

## 2. Device 侧解析两种方式

```cpp
// 方式一：SIMT VF 内部手工解析（不用 ListTensorDesc 的手工方案，__simt_callee__ 内联）
__simt_callee__ inline __gm__ T* SimtGetTensorAddr(GM_ADDR tensorListPtr, int64_t idx) {
    __gm__ uint64_t* dataAddr = reinterpret_cast<__gm__ uint64_t*>(tensorListPtr);
    uint64_t tensorPtrOffset = *dataAddr;              // 首 8 字节存指针表偏移
    __gm__ uint64_t* tensorPtr = dataAddr + (tensorPtrOffset >> 3);  // >>3 = /8 转 uint64 下标
    return reinterpret_cast<__gm__ T*>(*(tensorPtr + idx));
}
// 方式二：SIMT VF 外部解析（__aicore__ 上下文用官方 ListTensorDesc）
#include "kernel_operator_list_tensor_intf.h"
ListTensorDesc xList(reinterpret_cast<__gm__ void*>(x));
__gm__ T* input0Addr = xList.GetDataPtr<T>(0);          // 取第 0 个 tensor 指针
TensorDesc<T> desc; xList.GetDesc(desc, 0);             // 取 shape
```

- 出处：`foreach/foreach_log/op_kernel/arch35/foreach_log_simt.h`（方式一）、`foreach_binary_op`（方式二）
- **注意**：tensor 的地址信息必须在 kernel 侧解析，禁止在 host 侧解析后通过 tilingdata 传递。

## 3. Host 侧获取 tensorlist 信息

```cpp
auto computeNodeInfoPtr = tilingContext_->GetComputeNodeInfo();
auto idxInstanceInfoPtr = computeNodeInfoPtr.GetInputInstanceInfo(INPUT_IDX);
uint64_t tensorNum = idxInstanceInfoPtr->GetInstanceNum();
for (uint64_t i = 0; i < tensorNum; i++) {
    auto shape = tilingContext_->GetDynamicInputShape(INPUT_IDX, i)->GetStorageShape();
    auto dtype = tilingContext_->GetDynamicInputDesc(INPUT_IDX, i)->GetDataType();
}
```

## 4. 四种"扁平空间 → tensor"定位模式

把 N 个 tensor 拼接成 flatIdx 逻辑空间后，有 4 种定位方式（foreach 家族）：

```cpp
// (a) per-core 区间表（tiling 预计算每核 startT/endT + 首尾偏移，kernel 零查找）
for (t = startT; t <= endT; t++) {
    localStart = (t == startT) ? tensorStartOffsetList[coreId] : 0;
    localEnd   = (t == endT)   ? tensorEndOffsetList[coreId] + 1 : tensorElements[t];
    auto x1t = x1List.GetDataPtr<T>(t) + localStart;   // 边界 tensor 裁剪
    asc_vf_call<BinaryKernel<T, IDX_T, OP>>(dim3(THREAD_NUM), localEnd - localStart, x1t, x2t, yt);
}
// (b) 全局扁平 + 线程级线性扫累计偏移表（tensor ≤256 可接受）
while (flatIdx >= cumulativeOffsets[t]) t++;
localIdx = flatIdx - (t > 0 ? cumulativeOffsets[t - 1] : 0);
// (c) core range ∩ tensor range 求交（pow_list）
int64_t myStart = max(tStart, coreStart), myEnd = min(tEnd, coreEnd);
if (myStart < myEnd) { PowElementRange<T>(..., myStart - tStart, myEnd - tStart, tid, stride); }
// (d) 全核遍历全 tensor + grid-stride（log / maximum_scalar / addcdiv）
for (index = blockIdx*threadNum + threadIdx; index < perTensorElementNum; index += threadNum*blockNum) { ... }
```

- 出处：`foreach/*`（add_list 用 a、lerp_list 用 b、pow_list 用 c、log 用 d）

## 5. scalar / scalar_list 三种传入方式

```cpp
// 方式1 按值：entry（__aicore__）读 alpha 转 float 按值传 VF（半精度位级转换）
// 方式2 GM 指针 + tensorIdx：VF 内按 tensor 序号读 scalars_gm[tensorIdx]
__simt_vf__ void Compute(..., __gm__ T1* scalars_gm, uint32_t tensorIdx, ...) {
    float s = static_cast<float>(scalars_gm[tensorIdx]);
}
// 方式3 循环内读：for (t in tensors) { float s = scalarsGm[t]; asc_vf_call<K>(..., s); }
```

- scalar list 一致性在 **tiling 期校验**：`CheckScalarList` 要求 `scalars.shapeSize == totalTensorCount`，dtype 白名单 {F32/F32, F16/F16, F16/F32, BF16/F32, INT32/INT32}。

## 6. 选择建议

| tensor 个数 | 推荐方式 | 原因 |
|------------|---------|------|
| 有限且已知 | host 侧获取 shape → tilingdata 传递 | 简单直接 |
| 不限或大量 | kernel 内直接解析 | 避免 tilingdata 传递大量 shape |
| 定位开销敏感 | per-core 区间表（tiling 预计算） | kernel 零查找 |
| 实现最简 | 只发 count 数组 + grid-stride | 无偏移计算 |
