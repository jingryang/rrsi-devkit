# clock

**页面ID:** atlasascendc_api_07_10448  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10448.html

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

本接口在SIMD与SIMT混合调试场景中提供Clock时间戳功能，用于记录从程序启动到接口调用时刻所经历的时钟周期数（Cycle Count），便于精确分析执行延迟和性能瓶颈。

#### 函数原型

```
__simt_callee__ inline uint64_t clock(void)
```

#### 参数说明

无

#### 返回值说明

从程序开始到调用时所经历的时钟周期数。

#### 约束说明

无

#### 需要包含的头文件

使用该接口需要包含"utils/debug/asc_time.h"头文件。

```
#include "utils/debug/asc_time.h"
```

#### 调用示例

```
__simt_vf__ __launch_bounds__(1024) inline void SimtKernel(__gm__ uint64_t* dst)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x; 
    dst[idx] = clock();
}
```
