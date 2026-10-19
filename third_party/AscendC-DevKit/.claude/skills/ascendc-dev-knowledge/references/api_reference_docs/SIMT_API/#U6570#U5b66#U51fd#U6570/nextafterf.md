# nextafterf

**页面ID:** atlasascendc_api_07_10477  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10477.html

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

对于两个数据x、y：

如果y大于x，返回比x大的下一个可表示的浮点值。

如果y小于x，返回比x小的下一个可表示的浮点值。

如果y等于x，返回x。

#### 函数原型

```
inline float nextafterf(float x, float y)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |
| y | 输入 | 源操作数。 |

#### 返回值说明

- x不等于y时，返回y方向上x之后下一个可表示的浮点值。
- x等于y时，返回x。
- 若x、y任意一个为nan，返回nan。
- 若x=+inf，y不为nan，返回3.4028235e+38。
- 若x=-inf，y不为nan，返回-3.4028235e+38。

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
__simt_vf__ __launch_bounds__(1024) inline void KernelNextAfter(__gm__ float* dst, __gm__ float* x, __gm__ float* y)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = nextafterf(x[idx], y[idx]);
    printf("x[%d] = %f, y[%d] = %f, dst[%d] = %f, 输入x的16进制表示为: 0x%x, 输出dst的16进制表示为: 0x%x\n", idx, x[idx], idx, y[idx], idx, dst[idx], x[idx], dst[idx]);
}
```

程序输入为：

```
x:[10.0f 10.0f -10.0f -10.0f ...]
y:[20.0f -20.0f 20.0f -20.0f ...]
```

程序前4个线程的运行时打印效果如下：

```
x[0] = 10.000000, y[0] = 20.000000, dst[0] = 10.000001, 输入x的16进制表示为: 0x41200000, 输出dst的16进制表示为: 0x41200001
x[1] = 10.000000, y[1] = -20.000000, dst[1] = 9.999999, 输入x的16进制表示为: 0x41200000, 输出dst的16进制表示为: 0x411fffff
x[2] = -10.000000, y[2] = 20.000000, dst[2] = -9.999999, 输入x的16进制表示为: 0xc1200000, 输出dst的16进制表示为: 0xc11fffff
x[3] = -10.000000, y[3] = -20.000000, dst[3] = -10.000001, 输入x的16进制表示为: 0xc1200000, 输出dst的16进制表示为: 0xc1200001
```
