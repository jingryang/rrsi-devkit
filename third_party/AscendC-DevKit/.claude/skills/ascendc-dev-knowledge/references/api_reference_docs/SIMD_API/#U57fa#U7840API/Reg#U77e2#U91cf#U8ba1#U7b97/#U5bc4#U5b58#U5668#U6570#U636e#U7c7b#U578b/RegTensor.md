# RegTensor

**页面ID:** atlasascendc_api_07_0314  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0314.html

---

#### 功能说明

Reg矢量计算基本单元，RegTensor位宽为VL（Vector Length），具体值可能因不同AI处理器型号而异。

#### 定义原型

```
template <typename T, const RegTrait& regTrait = RegTraitNumOne> struct RegTensor;
```

#### 函数说明

模板参数T，支持的数据类型(宽度)为b8/b16/b32/b64。

| 数据类型宽度 | 数据类型 |
| --- | --- |
| b8 | 支持的数据类型为：bool/int8_t/uint8_t/fp4x2_e2m1_t/fp4x2_e1m2_t/hifloat8_t/fp8_e5m2_t/fp8_e4m3fn_t/fp8_e8m0_t（ fp4x2_e2m1_t/fp4x2_e1m2_t这两个b4类型在Vector侧的内存排布需要为两个一组，表现为b8类型；int4b_t也使用b8类型表达；bool数据类型只支持数据搬运）。 |
| b16 | 支持的数据类型为：int16_t/uint16_t/half/bfloat16_t。 |
| b32 | 支持的数据类型为：int32_t/uint32_t/float/complex32。 |
| b64 | 支持的数据类型为：int64_t/uint64_t/complex64。 |

模板参数regTrait，表示该RegTensor类型内部包含的矢量Reg数量。regTrait为RegTraitNumOne时，该RegTensor类型中包含1个相应数据类型的矢量Reg，长度为VL。regTrait为RegTraitNumTwo时，该RegTensor类型中包含2个相应数据类型的矢量Reg，总长度为2 * VL，每个矢量Reg长度为VL。

| 模板参数regTrait | 支持的数据类型宽度 |
| --- | --- |
| RegTraitNumOne | Atlas 350 加速卡，支持的数据类型宽度为：b8/b16/b32/b64。 |
| RegTraitNumTwo | Atlas 350 加速卡，支持的数据类型宽度为：b64/complex32。 |

#### 支持的型号

Atlas 350 加速卡（VL=256B）

#### 约束说明

无

#### 调用示例

- 示例一

```
AscendC::Reg::RegTensor<uint32_t> reg;
AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<uint32_t>();
AscendC::Reg::LoadAlign(reg, src, 0);
AscendC::Reg::Adds(reg, reg, 1);
AscendC::Reg::StoreAlign(dst, reg, 0, mask);
```

- 示例二

```
// 针对B64,可以传入RegTraitNumTwo
template<typename T, const AscendC::Reg::RegTrait& Trait = AscendC::Reg::RegTraitNumOne>
__simd_vf__ inline void AddVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T,Trait> srcReg0;
    AscendC::Reg::RegTensor<T,Trait> srcReg1;
    AscendC::Reg::RegTensor<T,Trait> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T,Trait>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Add(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```
