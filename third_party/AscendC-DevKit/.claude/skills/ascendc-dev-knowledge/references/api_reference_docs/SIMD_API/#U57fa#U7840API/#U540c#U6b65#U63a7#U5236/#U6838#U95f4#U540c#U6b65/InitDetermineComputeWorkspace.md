# InitDetermineComputeWorkspace

**页面ID:** atlasascendc_api_07_0206  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0206.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

初始化GM共享内存的值，完成初始化后才可以调用WaitPreBlock和NotifyNextBlock。

#### 函数原型

```
__aicore__ inline void InitDetermineComputeWorkspace(GlobalTensor<int32_t>& gmWorkspace, LocalTensor<int32_t>& ubWorkspace)
```

#### 参数说明

**表1 **接口参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| gmWorkspace | 输入 | 临时空间，初始化核间同步的共享内存，类型为GlobalTensor。 |
| ubWorkspace | 输入 | 临时空间，用于操作gmWorkspace，类型为LocalTensor。 |

#### 约束说明

- gmWorkspace申请的空间最少要求为：blockNum * 32Bytes；ubWorkspace申请的空间最少要求为：blockNum * 32 + 32Bytes；其中blockNum为调用的核数，可调用GetBlockNum获取。
- 使用该接口进行多核控制时，算子调用时指定的逻辑numBlocks必须保证不大于实际运行该算子的AI处理器核数，否则框架进行多轮调度时会插入异常同步，导致Kernel“卡死”现象。

#### 调用示例

如下示例模拟8个核进行数据处理，使用确定性计算接口保证核间运行顺序，进行原子累加。

```
// m_gmWorkspace为初始化核间同步的共享内存，类型为GlobalTensor；ubWorkspace为操作m_gmWorkspace的临时空间，类型为LocalTensor
int64_t m_tileCount = 256 * sizeof(int32_t); // 参与计算的元素总数所占的空间，单位为bytes
// 初始化GM共享内存的值
AscendC::InitDetermineComputeWorkspace(m_gmWorkspace, ubWorkspace);
// copy in
// srcLocal为int32_t类型的LocalTensor，m_srcGlobal为int32_t的GlobalTensor
AscendC::DataCopy(srcLocal, m_srcGlobal[m_tileCount], m_tileCount);
// copy out
// 调用WaitPreBlock读GM地址中的值，确认是否需要继续等待
AscendC::WaitPreBlock(m_gmWorkspace, ubWorkspace);
// 开启原子累加
AscendC::SetAtomicAdd<int32_t>();
// m_dstGlobal为int32_t的GlobalTensor
AscendC::DataCopy(m_dstGlobal[m_tileCount], srcLocal, m_tileCount);
AscendC::DisableDmaAtomic();
// 调用NotifyNextBlock写GM地址，通知下一个核当前核的操作已完成，下一个核可以进行操作
AscendC::NotifyNextBlock(m_gmWorkspace, ubWorkspace);
```

```
//每个核的输入数据为: 
[1,1,1,1,1,...,1] // 256个1
//最终输出数据:
[8,8,8,8,8,...,8] // 256个8
```
