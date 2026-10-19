# Fill

**页面ID:** atlasascendc_api_07_0891  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0891.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

将Global Memory上的数据初始化为指定值。该接口可用于对workspace地址或输出数据进行清零。

#### 函数原型

```
template <typename T>
__aicore__ inline void Fill(GlobalTensor<T>& gmWorkspaceAddr, const uint64_t size, const T value)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 含义 |
| --- | --- |
| T | 操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：uint8_t、int8_t、uint16_t、int16_t、bfloat16_t、half、uint32_t、int32_t、float、uint64_t、int64_t。 Atlas A3 训练系列产品/Atlas A3 推理系列产品，支持的数据类型为：uint16_t、int16_t、half、uint32_t、int32_t、float。 Atlas A2 训练系列产品/Atlas A2 推理系列产品，支持的数据类型为：uint16_t、int16_t、half、uint32_t、int32_t、float。 Atlas 推理系列产品AI Core，支持的数据类型为：uint16_t、int16_t、half、uint32_t、int32_t、float。 |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 含义 |
| --- | --- | --- |
| gmWorkspaceAddr | 输入 | gmWorkspaceAddr为用户定义的全局Global空间，是需要被初始化的空间，类型为GlobalTensor。GlobalTensor数据结构的定义请参考GlobalTensor。 |
| size | 输入 | 需要初始化的空间大小，单位为元素个数。 |
| value | 输入 | 初始化的值，数据类型与gmWorkspaceAddr保持一致。 |

#### 约束说明

- 单核调用此接口时，如果后续操作涉及Unified Buffer的使用，则需要在调用接口后，设置MTE2流水等待MTE3流水（MTE3_MTE2）的同步。
- 单核上连续多次调用此接口且初始化的值不一致时，需要在接口之间设置V流水等待MTE3流水（MTE3_V）的同步。由于该接口内部使用同一块Unified Buffer作为中转空间进行值初始化，连续调用接口时若不进行流水同步，后一次写操作可能覆盖前一次未完成写入的数据，导致前一次初始化Global Memory的结果非预期。
- 当多个核调用此接口对Global Memory进行初始化时，所有核对Global Memory的初始化未必会同时结束，也可能存在核之间读后写、写后读以及写后写等数据依赖问题。这种使用场景下，可以在本接口后调用SyncAll接口保证多核间同步正确。
- 该接口仅支持在程序内存分配InitBuffer接口前使用。

#### 调用示例

本调用示例使用8个核，每个核用当前blockIdx的值初始化zGm上的65536个数。完整的算子样例请参考[fill算子样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/08_transpose/fill)。

```
// 带初始化的元素个数
constexpr int32_t INIT_SIZE = 65536;

// 设置源操作数在Global Memory上的起始地址为z+INIT_SIZE*blockIdx，所占外部存储的大小为INIT_SIZE个float
zGm.SetGlobalBuffer((__gm__ float*)z + INIT_SIZE * AscendC::GetBlockIdx(), INIT_SIZE);
// 将起始地址为z+INIT_SIZE*blockIdx和大小为INIT_SIZE个float源操作数zGm的值，初始化为每个核用当前blockIdx
AscendC::Fill(zGm, INIT_SIZE, (float)(AscendC::GetBlockIdx()));
```

结果示例如下：

```
初始化后zGm数据：
[0. 0. 0. ... 0. 0. 0.
 1. 1. 1. ... 1. 1. 1.
 2. 2. 2. ... 2. 2. 2.
 ...
 5. 5. 5. ... 5. 5. 5.
 6. 6. 6. ... 6. 6. 6.
 7. 7. 7. ... 7. 7. 7.]
```
