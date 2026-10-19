# Duplicate

**页面ID:** atlasascendc_api_07_0410  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0410.html

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

支持Scalar和Tensor两种模式：

- Scalar模式：将scalarValue广播到寄存器，并保存在dstReg中（如果有mask，则保存在dstReg中被mask筛选的位置）。
- Tensor模式：将srcReg的最低位元素广播到寄存器，并保存在dstReg中被mask筛选的位置。

#### 定义原型

- 将scalarValue广播到寄存器，不支持mask

```
template <typename T = DefaultType, typename U, typename S>
__simd_callee__ inline void Duplicate(S& dstReg, U scalarValue);
```

- 将scalarValue广播到寄存器，支持mask

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U, typename S>
__simd_callee__ inline void Duplicate(S& dstReg, U scalarValue, MaskReg& mask);
```

- 将srcReg的最低位元素广播到寄存器

```
template <typename T = DefaultType, HighLowPart pos = HighLowPart::LOWEST, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void Duplicate(S& dstReg, S& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：bool、int8_t、uint8_t、fp4x2_e2m1_t、fp4x2_e1m2_t、hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t、fp8_e8m0_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、complex32、int64_t、uint64_t、complex64。 |
| U | scalar的数据类型。 Atlas 350 加速卡，支持的数据类型为：bool、int8_t、uint8_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、complex32、int64_t、uint64_t、complex64。 |
| mode | 选择MERGING模式或ZEROING模式。 - MERGING，mask未筛选的元素在dst中保留原值。- ZEROING，mask未筛选的元素在dst中置零。 |
| pos | 默认为LOWEST，表示将srcReg中的最低位广播至dstReg（暂不支持其他取值）。 |
| S | 目的操作数的RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **函数参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| scalarValue | 输入 | 源操作数。 类型为标量。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

**表3 **源操作数和目的操作数的数据类型约束

| dstReg数据类型 | scalar/srcReg数据类型 |
| --- | --- |
| bool | bool |
| int8_t | int8_t |
| uint8_t | uint8_t |
| fp4x2_e2m1_t | int8_t |
| fp4x2_e1m2_t | int8_t |
| hifloat8_t | int8_t |
| fp8_e5m2_t | int8_t |
| fp8_e4m3fn_t | int8_t |
| fp8_e8m0_t | int8_t |
| int16_t | int16_t |
| uint16_t | uint16_t |
| half | half |
| bfloat16_t | bfloat16_t |
| int32_t | int32_t |
| uint32_t | uint32_t |
| float | float |
| complex32 | complex32 |
| int64_t | int64_t |
| uint64_t | uint64_t |
| complex64 | complex64 |

#### 约束说明

无

#### 调用示例

- 示例一

```
template<typename T>
__simd_vf__ inline void DuplicateVF(__ubuf__ T* dstAddr, T scalarValue, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<T>();    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::Duplicate(dstReg, scalarValue);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 示例二

```
template<typename T>
__simd_vf__ inline void DuplicateVF(__ubuf__ T* dstAddr, T scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, src0Addr + i * oneRepeatSize);
        AscendC::Reg::Duplicate(dstReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 示例三

```
template<typename T>
__simd_vf__ inline void DuplicateVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, src0Addr + i * oneRepeatSize);
        AscendC::Reg::Duplicate(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```
