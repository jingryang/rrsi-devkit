# asc_stwt

**页面ID:** atlasascendc_api_07_10559  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10559.html

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

将指定数据存储到Global Memory的地址address中，并缓存至Data Cache和L2 Cache。

#### 函数原型

```
inline void asc_stwt(long int* address, long int val)
```

```
inline void asc_stwt(unsigned long int* address, unsigned long int val)
```

```
inline void asc_stwt(long long int* address, long long int val)
```

```
inline void asc_stwt(unsigned long long int* address, unsigned long long int val)
```

```
inline void asc_stwt(long2* address, long2 val)
```

```
inline void asc_stwt(ulong2* address, ulong2 val)
```

```
inline void asc_stwt(long4* address, long4 val)
```

```
inline void asc_stwt(ulong4* address, ulong4 val)
```

```
inline void asc_stwt(longlong2* address, longlong2 val)
```

```
inline void asc_stwt(ulonglong2* address, ulonglong2 val)
```

```
inline void asc_stwt(longlong4* address, longlong4 val)
```

```
inline void asc_stwt(ulonglong4* address, ulonglong4 val)
```

```
inline void asc_stwt(signed char* address, signed char val)
```

```
inline void asc_stwt(unsigned char* address, unsigned char val)
```

```
inline void asc_stwt(char2* address, char2 val)
```

```
inline void asc_stwt(uchar2* address, uchar2 val)
```

```
inline void asc_stwt(char4* address, char4 val)
```

```
inline void asc_stwt(uchar4* address, uchar4 val)
```

```
inline void asc_stwt(short* address, short val)
```

```
inline void asc_stwt(unsigned short* address, unsigned short val)
```

```
inline void asc_stwt(short2* address, short2 val)
```

```
inline void asc_stwt(ushort2* address, ushort2 val)
```

```
inline void asc_stwt(short4* address, short4 val)
```

```
inline void asc_stwt(ushort4* address, ushort4 val)
```

```
inline void asc_stwt(int* address, int val)
```

```
inline void asc_stwt(unsigned int* address, unsigned int val)
```

```
inline void asc_stwt(int2* address, int2 val)
```

```
inline void asc_stwt(uint2* address, uint2 val)
```

```
inline void asc_stwt(int4* address, int4 val)
```

```
inline void asc_stwt(uint4* address, uint4 val)
```

```
inline void asc_stwt(float* address, float val)
```

```
inline void asc_stwt(float2* address, float2 val)
```

```
inline void asc_stwt(float4* address, float4 val)
```

```
inline void asc_stwt(bfloat16_t* address, bfloat16_t val)
```

```
inline void asc_stwt(bfloat16x2_t* address, bfloat16x2_t val)
```

```
inline void asc_stwt(half* address, half val)
```

```
inline void asc_stwt(half2* address, half2 val)
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
__simt_vf__ __launch_bounds__(1024) inline void kernel_asc_stwt(__gm__ float* src, __gm__ float* val)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    asc_stwt(src + idx, val[idx]);
}
```
