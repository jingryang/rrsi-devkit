# normf

**页面ID:** atlasascendc_api_07_10354  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10354.html

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

获取输入数据a中前n个元素的平方和a[0]^2 + a[1]^2 +...+ a[n-1]^2的平方根。

![](images/atlasascendc_api_07_10354_img_001.png)

#### 函数原型

```
inline float normf(int n, float* a)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| n | 输入 | 源操作数。输入数据a中连续计算的元素个数。 |
| a | 输入 | 源操作数。Unified Buffer、Global Memory或栈空间的地址。 |

#### 返回值说明

a[0]^2 + a[1]^2 + ...+ a[n-1]^2的平方根。

- 若a[0]^2 + a[1]^2 + ...+ a[n-1]^2的平方根超出float最大范围，返回值为inf。
- 若a[0]、a[1] 、... 、a[n-1]任意一个或多个为±inf，返回值为inf。
- 若a[0]、a[1] 、... 、a[n-1]任意一个或多个为nan同时不是±inf，返回值为nan。
- 若n小于1，返回a[0]的绝对值。

#### 约束说明

- 输入数据a的长度必须大于等于参数n。
- 若n过大，接口性能无法保证。
- SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/math_functions.h"头文件。

```
#include "simt_api/math_functions.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

SIMD与SIMT混合编程场景，需要显式使用地址空间限定符表示地址空间：__gm__表示Global Memory内存空间，__ubuf__表示Unified Buffer内存空间，栈空间无需添加地址空间限定符。

```
__simt_vf__ __launch_bounds__(1024) inline void KernelNorm(__gm__ float* dst, __gm__ int* n, __gm__ float* a)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = normf(n[idx], a);
}
```
