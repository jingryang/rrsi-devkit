# y1f

**页面ID:** atlasascendc_api_07_10372  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10372.html

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

获取输入数据x的1阶第二类贝塞尔函数y1的值。

![](images/atlasascendc_api_07_10372_img_001.png)

#### 函数原型

```
inline float y1f(float x)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |

#### 返回值说明

输入数据的1阶第二类贝塞尔函数y1的值。

- 当x<0时，返回值为nan。
- 当x=0时，返回值为-inf。
- 当x=inf时，返回值为0。
- 当x=nan时，返回值为nan。

#### 约束说明

使用本接口时，配置的线程数不应超过256，否则有栈溢出风险。

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/math_functions.h"头文件。

```
#include "simt_api/math_functions.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(256) inline void KernelY1(__gm__ float* dst, __gm__ float* x)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = y1f(x[idx]);
}
```
