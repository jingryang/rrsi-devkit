# asc_stcg

**页面ID:** atlasascendc_api_07_10558  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10558.html

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

将指定数据存储到Global Memory的地址address中，并缓存到L2 Cache，但不缓存至Data Cache。

#### 函数原型

```
inline void asc_stcg(long int* address, long int val)
```

```
inline void asc_stcg(unsigned long int* address, unsigned long int val)
```

```
inline void asc_stcg(long long int* address, long long int val)
```

```
inline void asc_stcg(unsigned long long int* address, unsigned long long int val)
```

```
inline void asc_stcg(long2* address, long2 val)
```

```
inline void asc_stcg(ulong2* address, ulong2 val)
```

```
inline void asc_stcg(long4* address, long4 val)
```

```
inline void asc_stcg(ulong4* address, ulong4 val)
```

```
inline void asc_stcg(longlong2* address, longlong2 val)
```

```
inline void asc_stcg(ulonglong2* address, ulonglong2 val)
```

```
inline void asc_stcg(longlong4* address, longlong4 val)
```

```
inline void asc_stcg(ulonglong4* address, ulonglong4 val)
```

```
inline void asc_stcg(signed char* address, signed char val)
```

```
inline void asc_stcg(unsigned char* address, unsigned char val)
```

```
inline void asc_stcg(char2* address, char2 val)
```

```
inline void asc_stcg(uchar2* address, uchar2 val)
```

```
inline void asc_stcg(char4* address, char4 val)
```

```
inline void asc_stcg(uchar4* address, uchar4 val)
```

```
inline void asc_stcg(short* address, short val)
```

```
inline void asc_stcg(unsigned short* address, unsigned short val)
```

```
inline void asc_stcg(short2* address, short2 val)
```

```
inline void asc_stcg(ushort2* address, ushort2 val)
```

```
inline void asc_stcg(short4* address, short4 val)
```

```
inline void asc_stcg(ushort4* address, ushort4 val)
```

```
inline void asc_stcg(int* address, int val)
```

```
inline void asc_stcg(unsigned int* address, unsigned int val)
```

```
inline void asc_stcg(int2* address, int2 val)
```

```
inline void asc_stcg(uint2* address, uint2 val)
```

```
inline void asc_stcg(int4* address, int4 val)
```

```
inline void asc_stcg(uint4* address, uint4 val)
```

```
inline void asc_stcg(float* address, float val)
```

```
inline void asc_stcg(float2* address, float2 val)
```

```
inline void asc_stcg(float4* address, float4 val)
```

```
inline void asc_stcg(bfloat16_t* address, bfloat16_t val)
```

```
inline void asc_stcg(bfloat16x2_t* address, bfloat16x2_t val)
```

```
inline void asc_stcg(half* address, half val)
```

```
inline void asc_stcg(half2* address, half2 val)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| address | 输入 | Global Memory的地址。 |
| val | 输入 | 源操作数。 |

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用除half、half2、bfloat16_t、bfloat16x2_t类型之外的接口需要包含"simt_api/device_functions.h"头文件，使用half和half2类型接口需要包含"simt_api/asc_fp16.h"头文件，使用bfloat16_t和bfloat16x2_t类型接口需要包含"simt_api/asc_bf16.h"头文件。

```
#include "simt_api/device_functions.h"
```

```
#include "simt_api/asc_fp16.h"
```

```
#include "simt_api/asc_bf16.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(1024) inline void kernel_asc_stcg(__gm__ float* src, __gm__ float* val)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    asc_stcg(src + idx, val[idx]);
}
```
