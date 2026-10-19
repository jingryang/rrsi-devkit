# __bfloat162bfloat162

**页面ID:** atlasascendc_api_07_10783  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10783.html

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

将输入数据填充为bfloat16x2前后两个分量，返回转换后的bfloat16x2类型数据。

#### 函数原型

```
inline bfloat16x2_t __bfloat162bfloat162(const bfloat16_t x)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |

#### 返回值说明

输入的数据填充为bfloat16x2的数据。

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/asc_bf16.h"头文件。

```
#include "simt_api/asc_bf16.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
// 使用小向量可提升数据搬运效率
__simt_vf__ __launch_bounds__(1024) inline void simt_bfloat162bfloat162(__gm__ bfloat16_t* input, __gm__ bfloat16x2_t* output, uint32_t input_total_length)
{
    uint32_t idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx > input_total_length) {
        return;
    }
    output[idx] = __bfloat162bfloat162(input[idx]);
}
__global__ __vector__ void cast_kernel(__gm__ bfloat16_t* input, __gm__ bfloat16_t* output, uint32_t input_total_length)
{
    asc_vf_call<simt_bfloat162bfloat162>(dim3(1024), input, (__gm__ bfloat16x2_t*)output, input_total_length);
}
```
