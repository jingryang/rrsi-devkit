# Brcb

**页面ID:** atlasascendc_api_07_0089  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0089.html

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

给定一个输入张量，每一次取输入张量中的8个数填充到结果张量的8个datablock（32Bytes）中去，每个数对应一个datablock。

#### 函数原型

```
template <typename T>
__aicore__ inline void Brcb(const LocalTensor<T>& dst, const LocalTensor<T>& src0, const uint8_t repeatTime, const BrcbRepeatParams& repeatParams)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/int32_t/uint32_t/half/float/bfloat16_t/uint64_t/int64_t Atlas A3 训练系列产品/Atlas A3 推理系列产品，支持的数据类型为：int16_t/uint16_t/int32_t/uint32_t/half/bfloat16_t/float Atlas A2 训练系列产品/Atlas A2 推理系列产品，支持的数据类型为：int16_t/uint16_t/int32_t/uint32_t/half/bfloat16_t/float Atlas 推理系列产品AI Core，支持的数据类型为：int16_t/uint16_t/int32_t/uint32_t/half/float |

**表2 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 LocalTensor的起始地址需要32字节对齐。 |
| src0 | 输入 | 源操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 LocalTensor的起始地址需要32字节对齐。 数据类型和dst保持一致。 每一次迭代读取src0中的8个元素，所以src0的元素个数不小于8 * repeatTime。 |
| repeatTime | 输入 | 指令迭代次数，每次迭代完成8个datablock的数据收集，数据范围：repeatTime∈[0,255]。 |
| repeatParams | 输入 | 用于控制指令迭代的相关参数。 类型为BrcbRepeatParams，具体定义可参考${INSTALL_DIR}/include/ascendc/basic_api/interface/kernel_struct_brcb.h。${INSTALL_DIR}请替换为CANN软件安装后文件存储路径。 其中dstBlkStride、dstRepStride支持用户配置，参数说明参考表3。 |

**表3 **BrcbRepeatParams结构体参数说明

| 参数名称 | 含义 |
| --- | --- |
| dstBlkStride | 单次迭代内，矢量目的操作数不同datablock间地址步长。 **注意事项:**当dstBlkStride值为0时，默认按照1来处理。 |
| dstRepStride | 相邻迭代间，矢量目的操作数相同datablock地址步长。 |
| blockNumber | 预留参数。为后续的功能做保留，开发者暂时无需关注，使用默认值即可。 |
| src0BlkStride |  |
| src1BlkStride |  |
| src0RepStride |  |
| src1RepStride |  |
| repeatStrideMode |  |
| strideSizeMode |  |

#### 约束说明

- 不支持src0与dst为同一块内存地址。
- 针对Atlas 推理系列产品AI Core，使用时需要预留8K的Unified Buffer空间，作为接口的临时数据存放区。

#### 调用示例

```
// repeatTime = 4, 128 elements one repeat, 512 elements total
// srcLocal数据类型为half，dstLocal数据类型为half
// dstBlkStride = 1, no gap between blocks in one repeat
// dstRepStride = 8, no gap between repeats 
AscendC::Brcb(dstLocal, srcLocal, 4, {1,8});
```

结果示例如下：

```
输入数据(srcLocal):
[1 2 3 ... 16]
输出数据(dstLocal)初始值:
[0. 0. 0. 0. 0. 0. ... 0.]
进行Brcb计算后，输出数据(dstLocal):
[1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2 ... 15 15 15 15 15 15 15 15 15 15 15 15 15 15 15 15 16 16 16 16 16 16 16 16 16 16 16 16 16 16 16 16]
```
