# rnorm3df

**页面ID:** atlasascendc_api_07_10351  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10351.html

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

获取输入数据a、b、c的平方和a^2 + b^2 + c^2的平方根的倒数。

![](images/atlasascendc_api_07_10351_img_001.png)

#### 函数原型

```
inline float rnorm3df(float a, float b, float c)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| a | 输入 | 源操作数。 |
| b | 输入 | 源操作数。 |
| c | 输入 | 源操作数。 |

#### 返回值说明

a^2 + b^2 + c^2的平方根的倒数。

- 若a^2 + b^2 + c^2的平方根超出float最大范围，返回值为0。

- 若a^2 + b^2 + c^2平方根的倒数超出float最大范围，返回值为inf。

- 若a、b、c都为0，返回值为inf。

- 若a、b、c任意一个或多个为±inf，返回值为0。

- 若a、b、c任意一个或多个为nan同时不是±inf，返回值为nan。

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
__simt_vf__ __launch_bounds__(1024) inline void KernelRnorm3d(__gm__ float* dst, __gm__ float* a, __gm__ float* b, __gm__ float* c) 
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = rnorm3df(a[idx], b[idx], c[idx]);
}
```
