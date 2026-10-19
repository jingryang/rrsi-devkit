# ullmin

**页面ID:** atlasascendc_api_07_10487  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10487.html

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

获取两个输入数据中的最小值。

![](images/atlasascendc_api_07_10487_img_001.png)

#### 函数原型

```
inline unsigned long long int ullmin(const unsigned long long int x, const unsigned long long int y)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |
| y | 输入 | 源操作数。 |

#### 返回值说明

两个输入数据中的最小值。

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
__simt_vf__ __launch_bounds__(1024) inline void KernelUllmin(__gm__ unsigned long long int* dst, __gm__ unsigned long long int* x, __gm__ unsigned long long int* y)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = ullmin(x[idx], y[idx]); 
}
```
