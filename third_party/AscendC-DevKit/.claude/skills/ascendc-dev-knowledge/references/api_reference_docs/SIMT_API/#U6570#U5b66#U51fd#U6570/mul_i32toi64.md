# __mul_i32toi64

**页面ID:** atlasascendc_api_07_10495  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10495.html

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

计算输入32位整数x和y的乘积，返回64位结果。

#### 函数原型

```
long long __mul_i32toi64(int x, int y)
```

```
unsigned long long __mul_i32toi64(unsigned int x, unsigned int y)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数，乘数。 |
| y | 输入 | 源操作数，乘数。 |

#### 返回值说明

输入数据x和y乘积的64位结果。

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/device_functions.h"头文件。

```
#include "simt_api/device_functions.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(1024) inline void KernelMmul_i32toi64(__gm__ long long* dst, __gm__ int* x, __gm__ int* y)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = __mul_i32toi64(x[idx], y[idx]);
}
```

```
__simt_vf__ __launch_bounds__(1024) inline void KernelMmul_i32toi64(__gm__ unsigned long long* dst, __gm__ unsigned int* x, __gm__ unsigned int* y)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = __mul_i32toi64(x[idx], y[idx]);
}
```
