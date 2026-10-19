# remquof

**页面ID:** atlasascendc_api_07_10472  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10472.html

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

获取输入数据x除以y的余数r。r=x-ny，其中n是x除以y的商，n取最接近x除以y浮点数结果的整数，当x除以y的浮点数结果与左右最接近的整数距离相等时，商取偶数，同时将商赋值给指针变量quo。

#### 函数原型

```
inline float remquof(float x, float y, int *quo)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |
| y | 输入 | 源操作数。 |
| quo | 输出 | Unified Buffer、Global Memory或栈空间的地址，用于存储除法运算的商。 |

#### 返回值说明

输入数据x除以y的余数。

- x，y任意一个为nan时，返回值为nan。
- y=0时，返回值为nan。
- x=inf或-inf时，返回值为nan。
- x为有限值，y=inf或-inf时，返回x。

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/math_functions.h"头文件。

```
#include "simt_api/math_functions.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

SIMD与SIMT混合编程场景，需要显式使用地址空间限定符表示地址空间：__gm__表示Global Memory内存空间，__ubuf__表示Unified Buffer内存空间，栈空间无需添加地址空间限定符

```
__simt_vf__ __launch_bounds__(1024) inline void KernelRemQuo(__gm__ float* dst, __gm__ float* x, __gm__ float* y, __gm__ int* quo)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = remquof(x[idx], y[idx], quo + idx);
 }
```
