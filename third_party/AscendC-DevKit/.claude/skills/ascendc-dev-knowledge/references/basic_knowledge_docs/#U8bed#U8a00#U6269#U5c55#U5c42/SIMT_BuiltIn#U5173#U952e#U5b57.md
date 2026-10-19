# SIMT BuiltIn关键字

**页面ID:** atlas_ascendc_10_10054  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/programug/Ascendcopdevg/atlas_ascendc_10_10054.html

---

#### 函数执行空间限定符

函数执行空间限定符（Function Execution Space Qualifier）指示函数是在Host侧执行还是在Device侧执行，以及能被调用的空间范围。

**表1 **函数执行空间限定符概览

| 函数执行空间限定符 | 执行空间 | 允许调用函数空间 |  |  |
| --- | --- | --- | --- | --- |
| Host | Device | Host | Device |  |
| __host__， 无限定符 | √ | x | √ | x |
| __aicore__ | x | √ | x | √ |
| __global__ | x | √ | √ | x |

__global__修饰的函数是核函数入口，有以下使用约束：

- 函数返回类型必须为void，不能是class、struct或者union的成员函数。
- 不支持递归调用。
- 对__global__函数的调用是异步的，调用后即返回Host侧的主机线程。
- 只能被Host侧函数调用，在Device上执行。

__aicore__修饰的函数只能在Device侧执行，只能被__global__函数，或者其他__aicore__函数调用。

__host__修饰的函数只能在Host侧被调用和执行。

#### 内存空间限定符

使用内存空间限定符__ubuf__来表示动、静态内存，静态内存的大小在编译期是确定的，动态内存的大小在核函数执行时确定。

> **注意:** 

当前版本暂未支持动、静态内存，请关注后续版本。

- 静态内存通过数组分配：

```
__ubuf__ half staticBuf[1024];
```

- 动态内存通过以下方式申请使用：

```
extern __ubuf__ half dynamicBuf[];
```

动态内存的实际内存大小需要在核函数启动时配置，详见核函数配置。

#### 内置变量

- dim3

用于指定和获取线程网格（grid）、线程块（block）在x、y、z维度上的内置结构体。

dim3由3个无符号整数组成，结构体定义为{dimx，dimy，dimz}，用于指定3个不同维度的大小，三维总数为dimx * dimy * dimz。开发者可以通过如下方式创建dim3结构。

```
dim3(x); // 创建一维结构，dimy和dimz为默认值1
dim3(x, y); // 创建二维结构，dimz为默认值1
dim3(x, y, z); // 创建三维结构
```

当前提供了以下仅在Device上可用的dim3结构的内置变量：

- gridDim

内置全局变量，只能在核函数中使用，表示整个计算任务在各个维度上分别由多少个线程块构成。

  - gridDim.x是x维度上的线程块数量。
  - gridDim.y是y维度上的线程块数量，目前只能返回1。
  - gridDim.z是z维度上的线程块数量，目前只能返回1。

- blockDim

内置全局变量，在核函数中可以直接使用，用于获取线程块中配置的线程的三维层次结构，即启动VF时配置的dim3结构体实例值。blockDim.x，blockDim.y，blockDim.z分别表示线程块中三个维度的线程数。

- blockIdx

内置全局变量，只能在核函数中使用，用于获取块索引。表示当前线程所在的线程块在整个网格中的位置坐标。

  - blockIdx.x的范围是0到gridDim.x - 1。
  - blockIdx.y的范围是0到gridDim.y - 1，目前只能返回0。
  - blockIdx.z的范围是0到gridDim.z - 1，目前只能返回0。

- threadIdx

内置全局变量，在核函数中可以直接使用，用于获取当前线程在线程块内部的索引。threadIdx.x，threadIdx.y，threadIdx.z分别表示当前线程在3个维度的索引，threadIdx.x的范围为[0, blockDim.x)，threadIdx.y的范围为[0, blockDim.y)，threadIdx.z的范围为[0, blockDim.z)。线程块内线程的索引与线程ID对应关系如下：

  - 对于一维线程块，其线程ID为threadIdx.x。
  - 对于二维线程块，其线程ID为（threadIdx.x + threadIdx.y * blockDim.x）。
  - 对于三维线程块，其线程ID为（threadIdx.x + threadIdx.y * blockDim.x + threadIdx.z * blockDim.x * blockDim.y）。

当前提供了以下仅在Device上可用的int类型的内置变量：

- warpSize

运行时变量，表示一个线程束（warp）中的线程数量，当前为固定值32。

#### 内置数据类型

目前提供了一系列适用于Device侧的数据类型，包括标量和短向量。短向量是由多个元素组成的简单向量。

**表2 **标量数据类型

| 类型 | **数据类型** | **描述** | Size（bit） | 取值范围 |
| --- | --- | --- | --- | --- |
| 布尔型 | bool | 布尔类型，占8比特，全0时代表false，否则代表true。 | 8 | true, flase |
| 整形 | uint8_t | unsigned char | 8 | [0, 255] |
| int8_t | signed char | 8 | [-128, 127] |  |
| uint16_t | unsigned short | 16 | [0, 65535] |  |
| int16_t | signed short | 16 | [-32768, 32767] |  |
| uint32_t | unsigned int | 32 | [0, 4294967295] |  |
| int32_t | signed int | 32 | [-2147483648, 2147483647] |  |
| uint64_t | unsigned long | 64 | [0,18446744073709551615] |  |
| int64_t | signed long | 64 | [-9223372036854775808, 9223372036854775807] |  |
| 浮点型 | float8_e4m3_t | 符号位宽1，指数位宽4，尾数位宽3 | 8 | [26 - 29, 29 - 26] |
| float8_e5m2_t | 符号位宽1，指数位宽5，尾数位宽2 | 8 | [213 - 216, 216 - 213] |  |
| hifloat8_t | 符号位宽1，点域位宽2，指数与尾数位宽由点域编码决定 | 8 | 点域编码决定数据精度与取值范围 |  |
| half | 符号位宽1，指数位宽5，尾数位宽10 | 16 | [25 - 216, 216 - 25] |  |
| bfloat16_t | 符号位宽1，指数位宽8，尾数位宽7 | 16 | [2120 - 2128, 2128 - 2120] |  |
| float | 符号位宽1，指数位宽8，尾数位宽23 | 32 | [2104 - 2128, 2128 - 2104] |  |

短向量数据类型分为Vector X2、Vector X4，表示一个短向量变量有2、4个元素，当前支持的类型分布如下：

| 元素数据类型 | Vector X2 | Vector X4 |
| --- | --- | --- |
| unsigned char | uchar2 | uchar4 |
| signed char | char2 | char4 |
| unsigned short (16bit) | ushort2 | ushort4 |
| signed short (16bit) | short2 | short4 |
| unsigned int | uint2 | uint4 |
| signed int | int2 | int4 |
| 无符号的长整型 (64bit) | ulonglong2 | ulonglong4 |
| 有符号的长整型 (64bit) | longlong2 | longlong4 |
| 无符号的长整型 (32bit) | ulong2 | ulong4 |
| 有符号的长整型 (32bit) | long2 | long4 |
| 浮点型，1符号位，2指数位，1尾数位 | float4_e2m1x2_t | - |
| 浮点型，1符号位，1指数位，2尾数位 | float4_e1m2x2_t | - |
| 浮点型，1符号位，4指数位，3尾数位 | float8_e4m3x2_t | - |
| 浮点型，1符号位，5指数位，2尾数位 | float8_e5m2x2_t | - |
| 浮点型 hif8 | hifloat8x2_t | - |
| 浮点型，1符号位，5指数位，10尾数位 | half2 | - |
| 浮点型，1符号位，8指数位，7尾数位 | bfloat16x2_t | - |
| 浮点型，1符号位，8指数位，23尾数位 | float2 | float4 |

**表3 **短向量数据类型

| 数据类型 | 内存大小（字节） | 地址对齐（字节） |
| --- | --- | --- |
| char2, uchar2 | 2 | 2 |
| char4, uchar4 | 4 | 4 |
| short2, ushort2 | 4 | 4 |
| short4, ushort4 | 8 | 8 |
| int2, uint2 | 8 | 8 |
| int4, uint4 | 16 | 16 |
| long2，ulong2 | 8 | 8 |
| long4，ulong4 | 16 | 16 |
| longlong2，ulonglong2 | 16 | 16 |
| longlong4，ulonglong4 | 32 | 32 |
| float2 | 8 | 8 |
| float4 | 16 | 16 |
| float4_e2m1x2_t， float4_e1m2x2_t | 1 | 1 |
| float8_e4m3x2_t，float8_e5m2x2_t、hifloat8x2_t | 2 | 2 |
| half2，bfloat16x2_t | 4 | 4 |

#### 运算符

SIMT编程提供了一系列运算符，用于执行数学运算。以下是支持的运算符列表。

**表4 **SIMT编程支持的运算符列表

| 类别 | 运算符 | bool | int8_t/uint8_t/int16_t/uint16_t/int32_t/uint32_t/int64_t/uint64_t | half/bfloat16_t/float | half2/bfloat16x2_t | hifloat8_t |
| --- | --- | --- | --- | --- | --- | --- |
| 算术运算符 | + | x | √ | √ | √ | x |
| - | x | √ | √ | √ | x |  |
| * | x | √ | √ | √ | x |  |
| / | x | √ | √ | √ | x |  |
| % | x | √ | x | x | x |  |
| ++ | x | √ | √ | √ | x |  |
| -- | x | √ | √ | √ | x |  |
| - (取反) | x | √ | √ | √ | x |  |
| 比较运算符 | < | x | √ | √ | x | x |
| <= | x | √ | √ | x | x |  |
| > | x | √ | √ | x | x |  |
| >= | x | √ | √ | x | x |  |
| == | x | √ | √ | x | x |  |
| != | x | √ | √ | x | x |  |
| 位运算符 | & | x | √ | x | x | x |
| \| | x | √ | x | x | x |  |
| ^ | x | √ | x | x | x |  |
| ~ | x | √ | x | x | x |  |
| << | x | √ | x | x | x |  |
| >> | x | √ | x | x | x |  |
| 逻辑运算符 | && | √ | √ | √ | x | x |
| \|\| | √ | √ | √ | x | x |  |
| ! | √ | √ | √ | x | x |  |
| 条件运算符 | a ? b : c | √ | √ | √ | √ | x |

运算符使用示例如下所示：

```
// 加法运算
res[idx] = x[idx] + y[idx]; 

// 取反运算
x[idx] = (-x[idx]);

// 比较运算
if (x[idx] > y[idx]) {
    res[idx] = x[idx];
} else {
    res[idx] = y[idx];
}

// 按位与运算
res[idx] = x[idx] & y[idx];

// 逻辑或运算
if (x[idx] || y[idx]) {
    res[idx] = 1;
}

// 条件运算
res[idx] = x[idx] > y[idx] ? x[idx] : y[idx];
```

#### 核函数配置

在调用__global__限定符修饰的函数时必须指定执行配置。执行配置通过在函数名后带括号的参数列表之间插入，形如：

```
<<<grid_dim, block_dim, dynamic_mem_size, stream>>>
```

其中：

- grid_dim：int或dim3类型，用于指定网格（grid）的维度与规模，grid_dim.x * grid_dim.y * grid_dim.z等于启动的线程块总数。
- block_dim：int或dim3类型，用于指定每个线程块（block）的维度与规模，block_dim.x * block_dim.y * block_dim.z等于每个线程块包含的线程数。
- dynamic_mem_size：size_t类型，该参数指定除静态分配的内存外，本次调用为每个线程块动态分配的共享内存字节数。
- stream：aclrtStream类型指针，指定关联的流，用于维护异步操作的执行顺序。

以下示例展示了内核函数的声明与调用方式。

```
// 声明
__global__ void add_custom(float* x, float* y, float* z, uint64_t total_length);
// 调用
add_custom<<<block_num, thread_num_per_block, dyn_ubuf_size, stream>>>(x, y, z, 1024);
```

在执行函数之前，会先对上述配置参数进行校验。如果grid_dim或block_dim超出设备的最大允许规模，或dynamic_smem_bytes超过分配静态内存后剩余的可用共享内存，该函数将会执行失败。

在多线程并发执行时，每个线程使用较少的寄存器可以让更多的线程和线程块驻留在AI处理器上，从而提升性能。因此，编译器会采用启发式算法，将寄存器溢出（register spilling）和指令数量控制在最低水平，同时尽量减少寄存器的使用量。应用程序可以通过在__global__函数定义中使用__launch_bounds__()限定符来限制启动边界（launch bounds），提供附加信息辅助编译器优化这一过程，这属于可选配置。

- __launch_bounds__(N)是函数标记宏，在SIMT VF入口函数上可选配置，用于在编译期指定SIMT VF启动的最大线程数。若未配置__launch_bounds__，最大线程数默认为1024。参数N需要满足：

  - N >= dimx * dimy * dimz；dimx，dimy，dimz为表示线程的dim3结构体。
  - N的取值范围为1到2048。

最大线程数决定了每个线程可分配的寄存器数量，具体对应关系请见下表，寄存器用于存储线程中的局部变量，若局部变量的个数超出寄存器个数，容易出现栈溢出等问题。建议最大线程数与启动VF任务的dim3线程数保持一致。

**表5 **__launch_bounds__的Thread数量与每个Thread可用寄存器数

| Thread的个数(个) | 每个Thread可用寄存器个数(个) |
| --- | --- |
| 1025~2048 | 16 |
| 513~1024 | 32 |
| 257~512 | 64 |
| 1~256 | 127 |

配置SIMT函数最大线程数为512，示例如下：

```
__simt_vf__ __launch_bounds__(512) inline void add(__gm__ uint8_t* x, __gm__ uint8_t* y, __gm__ uint8_t* z)
```
