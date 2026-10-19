# GetBlockIdx

**页面ID:** atlasascendc_api_07_0185  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0185.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | √ |

#### 功能说明

获取当前核的index，用于代码内部的多核逻辑控制及多核偏移量计算等。

#### 函数原型

```
__aicore__ inline int64_t GetBlockIdx()
```

#### 参数说明

无

#### 返回值说明

GetBlockIdx返回当前核的索引，index的范围为[0, 用户配置的NumBlocks数量)。

同时启动AIC和AIV的场景：

当AIC和AIV比例为1:2时，AIC上取值范围为[0, 用户配置的NumBlocks数量), AIV上取值范围为[0, 2 * 用户配置的NumBlocks数量)；

当AIC和AIV比例为1:1时，AIC上取值范围为[0, 用户配置的NumBlocks数量)，AIV上取值范围为[0, 用户配置的NumBlocks数量)。

#### 约束说明

GetBlockIdx为一个系统内置函数，返回当前核的index。

#### 调用示例

```
// srcGm、dstGm为外部输入的gm空间
AscendC::GlobalTensor<float> srcGlobal;
AscendC::GlobalTensor<float> dstGlobal;
blockNum = AscendC::GetBlockNum(); // 获取核总数
perBlockSize = srcDataSize / blockNum; // 每个核平分处理相同个数
blockIdx = AscendC::GetBlockIdx(); // 获取当前工作的核ID
srcGlobal.SetGlobalBuffer(reinterpret_cast<__gm__ float*>(srcGm + blockIdx * perBlockSize * sizeof(float)), perBlockSize);    // 分配每个核上的srcGlobal的内存地址
dstGlobal.SetGlobalBuffer(reinterpret_cast<__gm__ float*>(dstGm + blockIdx * perBlockSize * sizeof(float)), perBlockSize);    // 分配每个核上的dstGlobal的内存地址
```
