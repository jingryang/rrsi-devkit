# asc_any

**页面ID:** atlasascendc_api_07_10388  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10388.html

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

判断是否有活跃线程的输入不为0。

当Warp内所有活跃线程执行本接口后，对所有活跃线程的输入操作数predicate进行判断，所有活跃线程的predicate均为0，返回0，否则返回1。Warp内所有活跃线程返回相同的结果。

#### 函数原型

```
inline int32_t asc_any(int32_t predicate)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| predicate | 输入 | 操作数。 |

#### 返回值说明

当Warp内所有活跃线程的输入均为0，返回0，否则返回1。

#### 约束说明

无

#### 需要包含的头文件

使用该接口需要包含"simt_api/device_warp_functions.h"头文件。

```
#include "simt_api/device_warp_functions.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(1024) inline void KernelAny(__gm__ int32_t* dst)
{
    // asc_vf_call参数：dim3{1024, 1, 1}
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    int32_t laneId = idx % 32;
    int32_t result = asc_any(laneId); // 返回值为1
    dst[idx] = result;
}
```
