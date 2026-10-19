# 简介

**页面ID:** atlasascendc_api_07_0427  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0427.html

---

> **注意:** 

**SIMT API当前仅支持SIMD与SIMT混合编程，SIMT编程场景待正式发布支持****，请关注后续版本**。

SIMT API是面向AI处理器的并行计算编程接口，基于SIMT编程模型实现高效的数据并行计算，具体API分类请参考表1。在SIMT编程中，每32个线程被分为一组，这一组线程称为Warp。Warp level接口负责处理单个Warp内32个线程的数据操作。Warp中的每个线程称为Lane，每个线程在Warp内的编号为LaneId，LaneId的范围是[0, 31]。

**表1 **SIMT C API分类列表

| 类别 | 功能 |
| --- | --- |
| 核函数定义 | 在SIMD与SIMT混合编程场景，用于启动SIMT VF子任务，启动指定数目的线程，执行指定的SIMT核函数。 |
| 同步函数 | 内存管理与同步接口，解决不同核内的线程间可能存在的数据竞争以及线程的同步问题。 |
| 数学函数 | 用于处理数学运算的函数集合。 |
| 精度转换 | 不同精度类型之间转换功能的一系列接口。 |
| 比较函数 | 用于判断数据是否为有限数、无穷或nan。 |
| Atomic函数 | 对Unified Buffer或Global Memory上的数据与指定数据执行原子操作的一系列接口。 |
| Warp函数 | 对单个Warp内32个线程的数据进行处理的相关操作的一系列API接口。 |
| 类型转换 | 根据源操作数和目的操作数的数据类型进行精度转换。 |
| 向量类型构造函数 | 向量类型构造相关接口。 |
| 使能Cache Hints的Load/Store函数 | 数据加载和数据缓存相关接口。 |
| 调测接口 | SIMT VF调试场景下使用的相关接口。 |

Ascend C SIMT API支持通过包含simt_api/asc_simt.h文件来调用输入数据为除half、half2、bfloat16_t、bfloat16x2_t、hifloat8x2_t、float8_e4m3x2_t、float8_e5m2x2_t以外类型的接口，调用输入数据为half和half2类型的SIMT API需要包含simt_api/asc_fp16.h文件，调用输入数据为bfloat16_t和bfloat16x2_t类型的SIMT API需要包含simt_api/asc_bf16.h文件，调用输入数据为hifloat8x2_t、float8_e4m3x2_t和float8_e5m2x2_t类型的SIMT API需要包含simt_api/asc_fp8.h文件。

```
#include "simt_api/asc_simt.h"
#include "simt_api/asc_fp16.h"
#include "simt_api/asc_bf16.h"
#include "simt_api/asc_fp8.h"
```

**表2 **SIMT C API需要包含的头文件

| 类别 | 除half、half2、bfloat16、bfloat16x2_t之外的类型需要包含的头文件 | half、half2类型需要包含的头文件 | bfloat16_t、bfloatx2_t类型需要包含的头文件 | hifloat8x2_t、float8_e4m3x2_t、float8_e5m2x2_t类型需要包含的头文件 |
| --- | --- | --- | --- | --- |
| 核函数定义 | #include "simt_api/common_functions.h" | #include "simt_api/asc_fp16.h" | #include "simt_api/asc_bf16.h" | #include "simt_api/asc_fp8.h" |
| 同步函数 | #include "simt_api/device_sync_functions.h" |  |  |  |
| 数学函数 精度转换 | #include "simt_api/math_functions.h" |  |  |  |
| Atomic函数 | #include "simt_api/device_atomic_functions.h" |  |  |  |
| Warp函数 | #include "simt_api/device_warp_functions.h" |  |  |  |
| 类型转换 Load/Store函数 | #include "simt_api/device_functions.h" |  |  |  |
| 向量类型构造函数 | #include "simt_api/vector_functions.h" |  |  |  |
