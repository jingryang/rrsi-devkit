# asc_atomic_cas

**页面ID:** atlasascendc_api_07_10382  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10382.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

对Unified Buffer或Global Memory上address的数值进行原子比较赋值操作，如果address上的数值等于指定数值compare，则对address赋值为指定数值val，否则address的数值不变。

#### 函数原型

```
inline float asc_atomic_cas(float *address, float compare, float val)
```

```
inline int32_t asc_atomic_cas(int32_t *address, int32_t compare, int32_t val)
```

```
inline uint32_t asc_atomic_cas(uint32_t *address, uint32_t compare, uint32_t val)
```

```
inline int64_t asc_atomic_cas(int64_t *address, int64_t compare, int64_t val)
```

```
inline uint64_t asc_atomic_cas(uint64_t *address, uint64_t compare, uint64_t val)
```

```
inline half2 asc_atomic_cas(half2 *address, half2 compare, half2 val)
```

```
inline bfloat16x2_t asc_atomic_cas(bfloat16x2_t *address, bfloat16x2_t compare, bfloat16x2_t val)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| address | 输出 | Unified Buffer或Global Memory的地址。 |
| compare | 输入 | 源操作数，做比较的值。 |
| val | 输入 | 源操作数，用于赋值的值。 |

不同数据类型支持的内存范围说明如下：

**表2 **不同数据类型支持的内存范围

| 参数数据类型 | 支持的内存空间 |
| --- | --- |
| int32_t、uint32_t、float、half2、bfloat16x2_t | Unified Buffer、Global Memory |
| int64_t、uint64_t | Global Memory |

#### 返回值说明

Unified Buffer或Global Memory上的初始数据。

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用除half2、bfloat16x2_t类型之外的接口需要包含"simt_api/device_atomic_functions.h"头文件，使用half2类型接口需要包含"simt_api/asc_fp16.h"头文件，使用bfloat16x2_t类型接口需要包含"simt_api/asc_bf16.h"头文件。

```
#include "simt_api/device_atomic_functions.h"
```

```
#include "simt_api/asc_fp16.h"
```

```
#include "simt_api/asc_bf16.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

SIMD与SIMT混合编程场景，需要显式使用地址空间限定符表示地址空间：__gm__表示Global Memory内存空间，__ubuf__表示Unified Buffer内存空间。

```
__simt_vf__ __launch_bounds__(1024) inline void KernelAtomicCas(__gm__ int32_t* dst, __gm__ int32_t* src0, __gm__ int32_t* src1)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    asc_atomic_cas(dst + idx, src0[idx], src1[idx]);
}
```
