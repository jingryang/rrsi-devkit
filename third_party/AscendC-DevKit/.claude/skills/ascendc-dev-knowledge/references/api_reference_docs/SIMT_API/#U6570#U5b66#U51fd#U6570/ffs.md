# __ffs

**页面ID:** atlasascendc_api_07_10498  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10498.html

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

从二进制输入数据的最低位开始，查找第一个值为1的比特位的位置，并返回该位置的索引，索引从1开始计数；如果二进制数据中没有1，则返回0。

#### 函数原型

```
int __ffs(int x)
```

```
int __ffs(long long x)
```

```
int __ffs(long x)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |

#### 返回值说明

数据二进制低位开始的第一个比特位为1的位置。

- 当x=0时，返回0。
- 当x=1时，返回1。

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
__simt_vf__ __launch_bounds__(1024) inline void KernelFfs(__gm__ int* dst, __gm__ int* x)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = __ffs(x[idx]);
}
```

```
__simt_vf__ __launch_bounds__(1024) inline void KernelFfs(__gm__ int* dst, __gm__ long long* x)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = __ffs(x[idx]);
}
```
