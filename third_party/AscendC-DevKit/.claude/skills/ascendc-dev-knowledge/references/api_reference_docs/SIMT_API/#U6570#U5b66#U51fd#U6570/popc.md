# __popc

**页面ID:** atlasascendc_api_07_10499  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10499.html

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

统计输入数据从二进制的高位到低位比特位为1的数量。

#### 函数原型

```
int __popc(unsigned int x)
```

```
int __popc(unsigned long long x)
```

```
int __popc(unsigned long x)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |

#### 返回值说明

输入数据二进制中比特位为1的数量。

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
__simt_vf__ __launch_bounds__(1024) inline void KernelPopc(__gm__ int* dst, __gm__ unsigned int* x)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = __popc(x[idx]);
}
```

```
__simt_vf__ __launch_bounds__(1024) inline void KernelPopc(__gm__ int* dst, __gm__ unsigned long long* x)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = __popc(x[idx]);
}
```
