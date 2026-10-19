# Unsqueeze

**页面ID:** atlasascendc_api_07_0421  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0421.html

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

将dstReg中数据根据mask进行解压缩。解压缩方式：dstReg中第0个元素置为0，dstReg中的第i个元素等于mask中从第0个到第(i-1)个元素中1的数量。mask最高位被忽略不参与统计。以uint8_t类型为例，算法逻辑表示如下：

```
dstReg[0] = 0;
for(int i = 1; i < AscendC::GetVecLen() / sizeof(uint8_t); i++){
dstReg[i] = mask[i - 1] ? (dstReg[i - 1] + 1) : dstReg[i - 1];
}
```

其中AscendC::GetVecLen() / sizeof(uint8_t)为dstReg包含的元素个数。

#### 定义原型

```
template <typename T = DefaultType, typename U>
__simd_callee__ inline void Unsqueeze(U& dstReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t、uint8_t、int16_t、uint16_t、int32_t、uint32_t。 |
| U | 目的操作数的RegTensor类型，由编译器自动推导，用户不需要填写。 |

**表2 **函数参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数和源操作数。 类型为RegTensor。 |
| mask | 输入 | mask用于提供dstReg解压缩信息。 类型为MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void UnsqueezeVF(__ubuf__ T* dstAddr, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    mask = AscendC::Reg::CreateMask<T>();
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::Unsqueeze(dstReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```
