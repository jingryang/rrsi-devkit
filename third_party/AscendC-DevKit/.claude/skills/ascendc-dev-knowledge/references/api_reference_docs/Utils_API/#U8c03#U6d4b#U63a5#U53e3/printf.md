# printf

**页面ID:** atlasascendc_api_07_10426  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10426.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

本接口提供SIMD和SIMT VF（SIMT VF仅支持Atlas 350 加速卡）调试场景下的格式化输出功能。

在算子Kernel侧的实现代码中，需要输出日志信息时，调用printf接口打印相关内容。

#### 函数原型

```
template <class... Args>
__aicore__ inline void printf( const __gm__char* fmt, Args&&... args)
```

#### 参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| fmt | 输入 | 格式控制字符串，包含两种类型的对象：普通字符和转换说明。 - 普通字符将原样不动地打印输出。- 转换说明并不直接输出而是用于控制printf中参数的转换和打印。每个转换说明都由一个百分号字符（%）开始，以转换说明结束，从而说明输出数据的类型 。支持的转换类型包括：  - %d / %ld / %lld / %i / %li / %lli：输出十进制数，支持打印的数据类型：int8_t、int16_t、int32_t、int64_t  - %f / %F：输出浮点数，支持打印的数据类型：float、half、bfloat16_t  - %x / %lx / %llx：输出十六进制整数，支持打印的数据类型：int8_t、int16_t、int32_t、int64_t、uint8_t、uint16_t、uint32_t、uint64_t  - %s：输出字符串  - %u / %lu /%llu：输出unsigned类型数据，支持打印的数据类型：uint8_t、uint16_t、uint32_t、uint64_t  - %p：输出指针地址  **注意**：上文列出的数据类型是NPU域调试支持的数据类型，CPU域调试时，支持的数据类型和C/C++规范保持一致。 |
| args | 输入 | 附加参数，个数和类型可变的参数列表：根据不同的fmt字符串，函数可能需要一系列的附加参数，每个参数包含了一个要被插入的值，替换了fmt参数中指定的每个%标签。参数的个数应与%标签的个数相同。 |

#### 约束说明

- 本接口不支持打印除换行符之外的其他转义字符。
- SIMD场景下，单次调用本接口打印的数据总量不可超过打印大小限制，默认为32KB。使用时应注意，如果超出这个限制，则数据不会被打印。您可以通过acl.json中的"simd_printf_fifo_size_per_core"字段进行配置，配置范围最小为1KB，最大为64MB。当打印数据量较大时，建议增加缓存空间。
- SIMT VF中printf功能需要占用额外的Global Memory空间用于数据缓存，缓存空间大小默认为2MB。您可以通过acl.json中的"simt_printf_fifo_size"字段进行配置，配置范围最小为1MB，最大为64MB。当打印数据量较大时，建议增加缓存空间。
- printf在SIMT VF中调用，会占用SIMT栈空间，请合理控制调用printf次数，防止SIMT栈溢出。
- 在仿真环境下，使用printf接口会增加算子运行时间，通过在VF代码中判断线程ID，可以仅在部分线程中打印调试信息，减少重复内容的打印，更有利于调试。

#### 需要包含的头文件

使用该接口需要包含"utils/debug/asc_printf.h"头文件。

```
#include "utils/debug/asc_printf.h"
```

#### SIMD调用示例

```
#include "utils/debug/asc_printf.h"

// SIMD printf
__global__ __mix__(1, 2) void hello_world()
{
    // print string
    printf("hello world device\n");
    // print int
    printf("fmt string int: %d\n", 0x123);
    // print float
    float b = 3.14;
    printf("fmt string float: %f\n", b);
}
```

NPU模式下，程序运行时打印效果如下：

```
hello world device
fmt string int: 291
fmt string float: 3.140000
hello world device
fmt string int: 291
fmt string float: 3.140000
hello world device
fmt string int: 291
fmt string float: 3.140000
hello world device
fmt string int: 291
fmt string float: 3.140000
......
```

#### SIMT调用示例

```
#include "kernel_operator.h"
#include "simt_api/asc_simt.h"
#include "utils/debug/asc_printf.h"

// asc_vf_call调用时dim3参数：dim3(8, 2, 8)
__simt_vf__ __launch_bounds__(128) inline void SimtCompute()
{
    int x = threadIdx.x;
    int y = threadIdx.y;
    int z = threadIdx.z;
    printf("simt vf: d: (%d, %d, %d), f: %f, s: %s\n", x, y, z, 3.14f, "pass");
}
```

NPU模式下，程序运行时打印效果如下：

```
simt vf: d: (0, 0, 0), f: 3.140000, s: pass
simt vf: d: (0, 0, 1), f: 3.140000, s: pass
simt vf: d: (0, 0, 2), f: 3.140000, s: pass
simt vf: d: (0, 0, 3), f: 3.140000, s: pass
simt vf: d: (0, 0, 4), f: 3.140000, s: pass
simt vf: d: (0, 0, 5), f: 3.140000, s: pass
simt vf: d: (0, 0, 6), f: 3.140000, s: pass
simt vf: d: (0, 0, 7), f: 3.140000, s: pass
simt vf: d: (0, 1, 0), f: 3.140000, s: pass
simt vf: d: (0, 1, 1), f: 3.140000, s: pass
......
```
