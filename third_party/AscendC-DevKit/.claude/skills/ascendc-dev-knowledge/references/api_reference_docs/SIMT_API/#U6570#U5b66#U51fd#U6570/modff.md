# modff

**页面ID:** atlasascendc_api_07_10480  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10480.html

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

将输入参数分解为小数部分和整数部分。

#### 函数原型

```
inline float modff(float x, float *n)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |
| n | 输出 | Unified Buffer、Global Memory或栈空间的地址，用于存储输入数据的的整数部分。 |

#### 返回值说明

输入参数的小数部分。

- 当x为nan时，返回值为nan。
- 当x为inf时，返回值为0。
- 当x为-inf时，返回值为0。

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/math_functions.h"头文件。

```
#include "simt_api/math_functions.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

SIMD与SIMT混合编程场景，需要显式使用地址空间限定符表示地址空间：__gm__表示Global Memory内存空间，__ubuf__表示Unified Buffer内存空间，栈空间无需添加地址空间限定符。

```
__simt_vf__ __launch_bounds__(1024) inline void KernelModff(__gm__ float* dst, __gm__ float* out, __gm__ float* x)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = modff(x[idx], out + idx); 
}
```
