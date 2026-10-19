# IBSet

**页面ID:** atlasascendc_api_07_0202  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0202.html

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
| Atlas 训练系列产品 | √ |

#### 功能说明

当不同核之间操作同一块全局内存且可能存在读后写、写后读以及写后写等数据依赖问题时，通过调用该函数来插入同步语句来避免上述数据依赖时可能出现的数据读写错误问题。调用IBSet设置某一个核的标志位，与IBWait成对出现配合使用，表示核之间的同步等待指令，等待某一个核操作完成。

#### 函数原型

```
template <bool isAIVOnly = true>
__aicore__ inline void IBSet(const GlobalTensor<int32_t>& gmWorkspace, const LocalTensor<int32_t>& ubWorkspace, int32_t blockIdx, int32_t eventID)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| isAIVOnly | 控制是否为AIVOnly模式，默认为true。 |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| gmWorkspace | 输出 | 外部存储核状态的公共缓存，类型为GlobalTensor。GlobalTensor数据结构的定义请参考GlobalTensor。 |
| ubWorkspace | 输入 | 存储当前核状态的公共缓存。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| blockIdx | 输入 | 表示等待核的idx号，取值范围：[0, 核数-1]。 |
| eventID | 输入 | 用来控制当前核的set、wait事件。 |

#### 约束说明

- gmWorkspace申请的空间最少要求为：核数 * 32Bytes * eventID_max + blockIdx_max * 32Bytes + 32Bytes。（eventID_max和blockIdx_max分别指eventID、blockIdx的最大值 ）；
- 注意：如果是AIVOnly模式，核数 = GetBlockNum()；如果是MIX模式，核数 = GetBlockNum() * 2；
- ubWorkspace申请的空间最少要求为：32Bytes；
- gmWorkspace缓存的值需要初始化为0。
- 使用该接口进行多核控制时，算子调用时指定的逻辑numBlocks必须保证不大于实际运行该算子的AI处理器核数，否则框架进行多轮调度时会插入异常同步，导致Kernel“卡死”现象。

#### 调用示例

本示例实现功能为使用2个核进行数据处理，每个核均是处理256个half类型数据。核0实现x+y的操作，并将结果放入z的前半部分，核1将核0的计算结果放入x，之后与y相加，结果存入z的后半部分，因此多个核之间需要进行数据同步。

```
// sync_gm为外部存储核状态的公共缓存，类型为GlobalTensor；sync_buf为存储当前核状态的公共缓存，类型为LocalTensor
int32_t blockIdx = AscendC::GetBlockIdx(); // 获取当前核
if (blockIdx == 1) { // 在核1设置IBWait，将阻塞指令执行直到核0操作完成
    AscendC::IBWait(sync_gm, sync_buf, 0, 0);
}
...
if (blockIdx == 0) { // 在核0设置IBSet，当核0的操作完成后再执行核1的指令
    AscendC::IBSet(sync_gm, sync_buf, 0, 0);
}
```
