# asc_threadfence

**页面ID:** atlasascendc_api_07_10307  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10307.html

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

在SIMT编程范式中，来自不同线程对同一份内存的读写操作可能造成数据竞争（Data Race）。asc_threadfence接口用于保证不同线程对同一份全局、共享内存的访问过程中，写入操作的时序性。它不会阻塞线程，仅保证内存操作的可见性顺序。

#### 函数原型

```
inline void asc_threadfence()
```

#### 参数说明

无

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/device_sync_functions.h"头文件。

```
#include "simt_api/device_sync_functions.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(1024) inline void KernelThreadFence(__gm__ float* dst, __gm__ float* src)
{
    src[0] = src[0] + 1;
    asc_threadfence(); // asc_threadfence()保证本线程的写操作顺序对全局可见
    dst[0] = src[0];
}
```
