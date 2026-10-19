# SyncAll

**页面ID:** atlasascendc_api_07_0204  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0204.html

---

#### 产品支持情况

| 产品 | 是否支持（软同步原型） | 是否支持（硬同步原型） |
| --- | --- | --- |
| Atlas 350 加速卡 | √ | √ |
| Atlas A3 训练系列产品            /             Atlas A3 推理系列产品 | √ | √ |
| Atlas A2 训练系列产品            /             Atlas A2 推理系列产品 | √ | √ |
| Atlas 200I/500 A2 推理产品 | x | x |
| Atlas 推理系列产品            AI Core | √ | x |
| Atlas 推理系列产品            Vector Core | x | x |
| Atlas 训练系列产品 | √ | x |

#### 功能说明

当不同核之间操作同一块全局内存且可能存在读后写、写后读以及写后写等数据依赖问题时，通过调用该函数来插入同步语句来避免上述数据依赖时可能出现的数据读写错误问题。目前多核同步分为硬同步和软同步，硬件同步是利用硬件自带的全核同步指令由硬件保证多核同步，软件同步是使用软件算法模拟实现。

#### 函数原型

- 软同步

```
template <bool isAIVOnly = true>
__aicore__ inline void SyncAll(const GlobalTensor<int32_t>& gmWorkspace, const LocalTensor<int32_t>& ubWorkspace, const int32_t usedCores = 0)
```

- 硬同步

```
template <bool isAIVOnly = true, const SyncAllConfig& config = DEFAULT_SYNC_ALL_CONFIG>
__aicore__ inline void SyncAll()
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| isAIVOnly | 控制SyncAll作用于纯Vector算子或融合（Cube和Vector融合）算子。可选值：                     - **true**（默认值）：纯Vector算子的全核同步，仅执行Vector核的全核同步。           - **false**：融合算子的全核同步，先分别完成Vector核和Cube核的全核同步，再执行两者之间的同步（软同步接口不支持此功能）。 |
| config | 控制SyncAll函数的行为 ，在多个AI Core之间进行流水线同步时，指定哪些管道（pipe）用于触发和等待。                     - **triggerPipe**：指定哪个管道用于“发送触发信号”。           - **waitPipe**：指定哪个管道用于“接收等待信号”。                    默认为SyncAllConfig DEFAULT_SYNC_ALL_CONFIG= {PIPE_ALL, PIPE_ALL} ，使用全部管道来进行触发和等待行为。          该参数仅支持如下型号：          Atlas 350 加速卡 |

**表2 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| gmWorkspace | 输入 | gmWorkspace为用户定义的全局Global空间，作为所有核共用的缓存，用于保存每个核的状态标记，类型为GlobalTensor，支持的数据类型为int32_t。GlobalTensor数据结构的定义请参考GlobalTensor。          所需空间大小和使用注意项参见约束说明。          硬同步接口不支持该参数。 |
| ubWorkspace | 输入 | ubWorkspace为用户定义的局部Local空间，每个核单独自用，用于标记当前核的状态。          类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT，支持的数据类型为int32_t。          所需空间大小参见约束说明。          硬同步接口不支持该参数。 |
| usedCores | 输入 | 指定多少个核之间的同步，传入数值不能超过算子调用时指定的逻辑numBlocks。此参数为默认参数，不传此参数表示全核软同步。          仅在软同步接口中支持，硬同步接口不支持该参数。 |

#### 约束说明

- gmWorkspace缓存申请的空间大小要求大于等于核数*32Bytes，并且缓存的值需要初始化为0。目前常见的有两种初始化方式：

  - 通过在host侧进行初始化操作，确保传入该接口时，gmWorkspace缓存已经初始化为0；
  - 在kernel侧初始化的时候对gmWorkspace缓存初始化，需要注意的是，每个核上都需要初始化全部的gmWorkspace缓存空间。

- ubWorkspace申请的空间大小要求大于等于核数*32Bytes。
- 针对Atlas 350 加速卡，对于软同步接口，连续使用（Polling）该接口，用于进行多核同步，会造成Bus被长期占用，导致其他核无法访问该GM，导致多核读同一GM出现卡死现象，若需要Polling，建议在该使用接口间，增加Nop指令，指令量建议为800个，一般为需要同步的核数 * 200。
- 使用该接口进行多核控制时，算子调用时指定的逻辑numBlocks必须保证不大于实际运行该算子的AI处理器核数，否则框架进行多轮调度时会插入异常同步，导致Kernel“卡死”现象。
- 在分离模式下，建议使用硬同步接口而非软同步接口。软同步接口仅适用于纯Vector场景，且性能较低。使用硬同步接口时，需根据场景设置Kernel类型：

  - 在纯Vector/Cube场景下，需设置Kernel类型为KERNEL_TYPE_MIX_AIV_1_0或KERNEL_TYPE_MIX_AIC_1_0。
  - 对于Vector和Cube混合场景，需根据实际情况灵活配置Kernel类型。

- 使用该接口时，建议开启batchmode模式，使算子独占全部所需核资源，否则可能因满足以下条件导致死锁：

  - 多流并发场景（≥2条执行流）。
  - ≥2个算子并发执行。
  - 所有并发算子的核数总和超过物理核数。
  - ≥2个并发算子使用了核间同步功能。

具体而言，在多流场景下，某条流的核间同步算子虽分配到n个物理核，但可能仅有n-m个核先被调度执行，而其余m个核因被其他流的核间同步算子抢占而尚未启动。先启动的n-m个核执行到核间同步时等待剩余m核完成，而剩余m核因被其他流的核间同步算子占用而无法释放，形成死锁。

Kernel直调场景下通过__schedmode__(mode)限定符来设置batchmode模式；工程化算子开发场景下，通过TilingContext的SetScheduleMode接口来设置batchmode模式，具体请参考《基础数据结构和接口》《基础数据结构和接口》。

#### 调用示例

本示例实现功能为使用8个核进行数据处理，每个核均是处理32个float类型数据，对该数据乘2后再与其他核上进行同样乘2的数据进行相加，中间结果保存到workGm，因此多个核之间需要进行数据同步。此样例中，使用软同步，入口函数传入的syncGm里的值都已经在host侧初始化为0。若以下用例改成使用硬同步，则不需要传入syncGm，并且不需要使用workQueue。

```
...
// syncGlobal为用户定义的全局Global空间，作为所有核共用的缓存，类型为GlobalTensor；workLocal为用户定义的局部Local空间，每个核单独自用，类型为LocalTensor
int srcDataSize = 256; // 参与计算的元素个数
int32_t blockNum = AscendC::GetBlockNum(); // 获取核总数
int32_t blockIdx = AscendC::GetBlockIdx(); // 获取当前工作的核ID
uint32_t perBlockSize = srcDataSize / blockNum; // 每个核平分处理相同个数
// 当前工作核计算后的数据先保存到外部工作空间，workGlobal为GlobalTensor，dstLocal为LocalTensor
AscendC::DataCopy(workGlobal[blockIdx * perBlockSize], dstLocal, perBlockSize);
// 等待所有核都完成计算
AscendC::SyncAll(syncGlobal, workLocal);
...
```
