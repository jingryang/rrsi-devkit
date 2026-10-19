# powf

**页面ID:** atlasascendc_api_07_10349  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10349.html

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

获取输入数据x的y次幂。

![](images/atlasascendc_api_07_10349_img_001.png)

#### 函数原型

```
inline float powf(float x, float y)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数，幂计算的底数。 |
| y | 输入 | 源操作数，幂计算的指数。 |

#### 返回值说明

x的y次幂的结果。

- 若x^y超出float最大范围，返回值为inf。
- 若x为±0，y小于0并且为奇数，返回值为±inf。
- 若x为±0，y小于0并且不为奇数，返回值为inf。
- 若x为±0，y大于0并且为奇数，返回值为±0。
- 若x为±0，y大于0并且不为奇数，返回值为0。
- 若x为-1，y为±inf，返回值为1。
- 若x为1，y为任意值（包括nan），返回值为1。
- 若y为±0，x为任意值（包括nan），返回值为1。
- 若x小于0，y不为整数，返回值为nan。
- 若|x|<1，y为-inf，返回值为inf。
- 若|x|>1，y为-inf，返回值为0。
- 若|x|<1，y为inf，返回值为0。
- 若|x|>1，y为inf，返回值为inf。
- 若x为-inf，y小于0并且为奇数，返回值为-0。
- 若x为-inf，y小于0并且不为奇数，返回值为0。
- 若x为-inf，y大于0并且为奇数，返回值为-inf。
- 若x为-inf，y大于0并且不为奇数，返回值为inf。
- 若x为inf，y小于0，返回值为0。
- 若x为inf，y大于0，返回值为inf。
- 在如下边界场景，返回值为nan。

  - x为nan，y不为0。
  - y为nan，x不为1。
  - x、y均为nan

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
__simt_vf__ __launch_bounds__(1024) inline void KernelPow(__gm__ float* dst, __gm__ float* x, __gm__ float* y)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = powf(x[idx], y[idx]);
}
```
