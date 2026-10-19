# fmaf

**页面ID:** atlasascendc_api_07_10465  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10465.html

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

对输入数据x、y、z，计算x与y相乘加上z的结果。

![](images/atlasascendc_api_07_10465_img_001.png)

#### 函数原型

```
inline float fmaf(float x, float y, float z)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |
| y | 输入 | 源操作数。 |
| z | 输入 | 源操作数。 |

#### 返回值说明

x * y+ z的值。

- x为±inf，y为±0，返回nan。
- x为±0，y为±inf，返回nan。
- x*y为inf，z为-inf，返回nan。
- x*y为-inf，z为inf，返回nan。
- x*y+z超出对应类型范围的最大值，返回inf。
- x*y+z小于对应类型范围的最小值，返回-inf。
- x、y、z任意一个为nan，返回nan。

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
__simt_vf__ __launch_bounds__(1024) inline void KernelFma(__gm__ float* dst, __gm__ float* x, __gm__ float* y, __gm__ float* z){
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = fmaf(x[idx], y[idx], z[idx]);
}
```
