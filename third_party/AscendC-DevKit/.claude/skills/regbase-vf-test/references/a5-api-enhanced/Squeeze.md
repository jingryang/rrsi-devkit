# Squeeze

**页面ID:** atlasascendc_api_07_0420  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0420.html

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

将传入的srcReg中被mask选择的有效元素依次复制到dstReg中，有效元素在dstReg中从低到高连续排列。dstReg中剩余位置元素置为0。

#### 定义原型

```
template <typename T = DefaultType, GatherMaskMode store = GatherMaskMode::NO_STORE_REG, typename U>
__simd_callee__ inline void Squeeze(U& dstReg, U& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数和源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/half/float |
| store | GatherMaskMode选择是否将有效元素的总字节数存入AR寄存器，AR寄存器描述参考表1。 - NO_STORE_REG，有效元素的总字节数不存入AR寄存器；- STORE_REG，有效元素的总字节数存入AR寄存器。 |
| U | srcReg/dstReg RegTensor类型， 例如RegTensor<uint32_t>，由编译器自动推导，用户不需要填写。 |

**表2 **函数参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor |
| mask | 输入 | mask用于控制每次迭代内参与计算的元素。 |

#### 约束说明

当store取值为STORE_REG时，由于硬件约束，StoreUnAlign指令和Squeeze指令必须交替使用，例如：

```
Squeeze(dstVreg, srcVreg, mask);
StoreUnAlign(dstAddr, dstVreg, ureg);
Squeeze(dstVreg, srcVreg, mask);
StoreUnAlign(dstAddr, dstVreg, ureg);
```

#### 调用示例

```
template<typename T>
__simd_vf__ inline void SqueezeVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::UnalignRegForStore ureg;
    AscendC::Reg::MaskReg sqzMask = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::H>();
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        AscendC::Reg::LoadAlign<T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(srcReg0, srcAddr, oneRepeatSize);
        AscendC::Reg::Squeeze<T, AscendC::Reg::GatherMaskMode::STORE_REG>(srcReg1, srcReg0, sqzMask);
        AscendC::Reg::StoreUnAlign<T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(dstAddr, srcReg1, ureg);
     }
     AscendC::Reg::StoreUnAlignPost(dstAddr, ureg);
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Squeeze 实例

未发现使用实例。扫描范围：ops-math、ops-nn，仅 arch35 / `_apt` 路径，已排除 Cube 相关算子（路径含 matmul/conv/cube 或内容含 Mmad/MatMul/Cube/mmad）；共 0 处使用。

