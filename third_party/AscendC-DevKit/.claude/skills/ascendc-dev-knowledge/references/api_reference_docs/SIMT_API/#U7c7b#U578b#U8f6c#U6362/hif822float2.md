# __hif822float2

**页面ID:** atlasascendc_api_07_10776  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10776.html

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

将hifloat8x2_t类型数据的两个分量转换为浮点数，返回转换后的float2类型数据。

#### 函数原型

```
inline float2 __hif822float2(const hifloat8x2_t x)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |

#### 返回值说明

将hifloat8x2_t类型输入转换成的float2类型数据。

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/asc_fp8.h"头文件。

```
#include "simt_api/asc_fp8.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
// 使用小向量可提升数据搬运效率
__simt_vf__ __launch_bounds__(1024) inline void simt_hif822float2(__gm__ hifloat8x2_t* input, __gm__ float2* output, uint32_t input_total_length)
{
    uint32_t idx = blockIdx.x * blockDim.x + threadIdx.x;
    // 每个线程处理1个hifloat8x2_t类型的数据，即2个hifloat8_t类型的数据，因此idx >= input_total_length / 2的线程不处理数据
    if (idx > input_total_length /2) {
        return;
    }
    output[idx] = __hif822float2(input[idx]);
}
__global__ __vector__ void cast_kernel(__gm__ uint8_t* input,  __gm__ float* output, uint32_t input_total_length)
{
    asc_vf_call<simt_hif822float2>(dim3(1024), (__gm__ hifloat8x2_t*)input, (__gm__ float2*)output, input_total_length);
}
```
