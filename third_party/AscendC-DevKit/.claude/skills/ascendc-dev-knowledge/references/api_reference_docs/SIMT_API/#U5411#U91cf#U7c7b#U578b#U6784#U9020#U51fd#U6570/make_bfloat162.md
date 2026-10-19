# make_bfloat162

**页面ID:** atlasascendc_api_07_10554  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10554.html

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

使用给定的两个bfloat16_t类型的数据创建一个bfloat16x2_t类型的向量。对于16位类型的数据，底层指令支持一次完成两个数据的计算，通过构造向量类型可以提高数据计算效率。

#### 函数原型

```
inline bfloat16x2_t make_bfloat162(bfloat16_t x, bfloat16_t y)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |
| y | 输入 | 源操作数。 |

#### 返回值说明

由两个bfloat16类型数字构成的新bfloat16x2_t向量。

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
__simt_vf__ __launch_bounds__(1024) inline void kernel_make_bfloat162(__gm__ bfloat16x2_t* dst, __gm__ bfloat16_t* x, __gm__ bfloat16_t* y)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = make_bfloat162(x[idx], y[idx]);
}
```
