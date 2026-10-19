# make_uint4

**页面ID:** atlasascendc_api_07_10525  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10525.html

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

使用给定的四个unsigned int类型的数据创建一个uint4类型的向量。

#### 函数原型

```
inline uint4 make_uint4(unsigned int x, unsigned int y, unsigned int z, unsigned int w)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |
| y | 输入 | 源操作数。 |
| z | 输入 | 源操作数。 |
| w | 输入 | 源操作数。 |

#### 返回值说明

由四个unsigned int类型数字构成的新uint4向量。

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/vector_functions.h"头文件。

```
#include "simt_api/vector_functions.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(1024) inline void kernel_make_uint4(__gm__ uint4* dst, __gm__ unsigned int* x, __gm__ unsigned int* y, __gm__ unsigned int* z, __gm__ unsigned int* w)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = make_uint4(x[idx], y[idx], z[idx], w[idx]);
}
```
