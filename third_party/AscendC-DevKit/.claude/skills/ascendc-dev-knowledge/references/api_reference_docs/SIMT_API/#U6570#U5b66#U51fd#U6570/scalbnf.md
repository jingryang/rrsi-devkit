# scalbnf

**页面ID:** atlasascendc_api_07_10478  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10478.html

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

获取输入数据x与2的n次方的乘积。

![](images/atlasascendc_api_07_10478_img_001.png)

#### 函数原型

```
inline float scalbnf(float x, int32_t n)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |
| n | 输入 | 源操作数。 |

#### 返回值说明

输入数据x乘以2的n次幂的结果。

- 当x为nan时，返回值为nan。
- 当x为inf时，返回值为inf。
- 当x为-inf时，返回值为-inf。

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/math_functions.h"头文件。

```
#include "simt_api/math_functions.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(1024) inline void KernelScalbn(__gm__ float* dst, __gm__ float* x, __gm__ int* n)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = scalbnf(x[idx], n[idx]);
}
```
