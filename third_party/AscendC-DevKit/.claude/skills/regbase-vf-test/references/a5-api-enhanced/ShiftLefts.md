# ShiftLefts

**页面ID:** atlasascendc_api_07_0386  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0386.html

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

源操作数内每个元素做逻辑左移，逻辑左移的位数由输入参数scalarValue决定。

所谓逻辑左移，是指去掉最高位，最低位补0，例：二进制数 1010101010101010，逻辑左移一位结果为 0101010101010100。

#### 函数原型

```
template <typename T = DefaultType, typename U, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void ShiftLefts(S& dstReg, S& srcReg, U scalarValue, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 矢量目的操作数和源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/int32_t/uint32_t/int64_t/uint64_t |
| U | 标量源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：int16_t |
| mode | 选择MERGING模式或ZEROING模式。当前仅支持ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零。 |
| S | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| scalarValue | 输入 | 逻辑左移的位数。 类型为标量。 不支持设置为负数。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T, typename U>
__simd_vf__ inline void ShiftLeftsVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, U scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::LoadAlign(srcReg, src0Addr + i * oneRepeatSize);
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::ShiftLefts(dstReg, srcReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 ShiftLefts 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, Sub, UnalignReg, UpdateMask
- **ShiftLefts 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 dynamic_mx_quant 求 1/scale 阶段，将提取出的指数左移 FP32_SHR_NUM 位，把 E8M0 scale 对齐到 BF16 指数域以便后续做 bias 相减得到倒数。

（行 523-541）

```cpp

Reg::MaskOr(p0, p0, p1, mask);
Reg::Adds(extractExpRegTensor, expFP32RegTensor, 1, mask);
// 根据情况选择指数位是否加一
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, expFP32RegTensor, p0);

Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, invMaxRegTensor, infMask);
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, fp32ZeroRegTensor, zeroMask);
Reg::Pack(tmp16RegTensor, extractExpRegTensor);
Reg::Pack(outZero, tmp16RegTensor);
// 搬出mxScale
Reg::DataCopyUnAlign(mxScaleAddr, outZero, u1, dataLen);
Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);

// 求1/scale
Reg::ShiftLefts(extractExpRegTensor, extractExpRegTensor, FP32_SHR_NUM, mask);
Reg::Sub(extractExpRegTensor, scaleBias, extractExpRegTensor, mask);
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, nan, infMask);
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, fp32ZeroRegTensor, zeroMask);
```

**要点**: 1）scalarValue 用常量 FP32_SHR_NUM，与 ShiftRights 先右移提取指数、再 ShiftLefts 左移复位，形成"提取-对齐"位操作对；2）使用 mask（ZEROING）模式，未选中元素置零，保证异常/零值通道不参与 1/scale 计算；3）与 Sub、Select 组合：左移后做 scaleBias-exp 得 halfScale，再 Select 处理 NaN/0。

### 实例 2：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **ShiftLefts 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: 在 grouped_dynamic_mx_quant 输出 mxScale 后求 1/scale 阶段，将 E8M0 指数左移 SHR_NUM_FOR_BF16 位对齐到 BF16 指数域，再与 bias 做减法得到 scale 的倒数。

（行 599-617）

```cpp
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p3, manAndmxScaleFP32RegTensor, NUMBER_HALF, preMaskScale);
Reg::MaskAnd(p2, p2, p3, preMaskScale);
Reg::MaskXor(p1, p1, p2, preMaskScale);
Reg::Adds(expMaxAndAddOneFP32RegTensor, expAndreShareExpFP32RegTensor, 1, preMaskScale);
Reg::Select(manAndmxScaleFP32RegTensor, expMaxAndAddOneFP32RegTensor, expAndreShareExpFP32RegTensor, p1);
// 7. 异常值处理
Reg::Select<uint32_t>(manAndmxScaleFP32RegTensor, manAndmxScaleFP32RegTensor, fp8NanRegTensor32, infMask);
Reg::Select<uint32_t>(manAndmxScaleFP32RegTensor, manAndmxScaleFP32RegTensor, zeroRegTensor32, zeroMask);
// 8. 输出 mxscale（E8M0）
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(expScaleMxYZeroRegTensor,
                                                        manAndmxScaleFP32RegTensor);
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(outZeromxScaleFp8, expScaleMxYZeroRegTensor);
Reg::StoreUnAlign(mxScaleAddr, outZeromxScaleFp8, u1, vfNum32);
Reg::StoreUnAlignPost(mxScaleAddr, u1, 0);
// 9. 求 1/scale
Reg::ShiftLefts(manAndmxScaleFP32RegTensor, manAndmxScaleFP32RegTensor, SHR_NUM_FOR_BF16, preMaskScale);
Reg::Sub(expAndreShareExpFP32RegTensor, biasRegTensor32, manAndmxScaleFP32RegTensor, preMaskScale);
Reg::Select<uint32_t>(expAndreShareExpFP32RegTensor, expAndreShareExpFP32RegTensor, nanRegTensor32,
                      infMask);
```

**要点**: 1）使用预计算掩码 preMaskScale 配合 ZEROING 模式（默认，文档标注当前仅支持 ZEROING），未选中元素置零；2）移位位数常量 SHR_NUM_FOR_BF16（7），对应 E8M0 到 BF16 指数域位宽差；3）调用 4 次，贯穿「提取指数到 Pack 输出到左移求倒数」链路。

### 实例 3：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **ShiftLefts 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: 在 flat_quant 的 fp4 量化 scale 计算中，将提取出的指数左移 SHR_NUM_FOR_BF16 位对齐到 BF16 指数域，用于后续 bias 减法求得 1/scale。

（行 517-535）

```cpp
AscendC::Reg::CompareScalar<uint32_t, AscendC::CMPMODE::LT>(p1, exp32, NUMBER_TWO_FIVE_FOUR,
                                                                 preMaskScale);
AscendC::Reg::CompareScalar<uint32_t, AscendC::CMPMODE::GT>(p2, man32, NUMBER_ZERO, preMaskScale);
AscendC::Reg::MaskAnd(p0, p0, p1, preMaskScale);
AscendC::Reg::MaskAnd(p0, p0, p2, preMaskScale);

AscendC::Reg::Adds(expAddOne32, exp32, 1, preMaskScale);
AscendC::Reg::Select(extractExp, expAddOne32, exp32, p0);
AscendC::Reg::Select<uint32_t>(extractExp, extractExp, fp4NanRegTensor, cmpResult);
AscendC::Reg::Select<uint32_t>(extractExp, extractExp, zeroRegTensor32, zeroMask);
AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(expOut, extractExp);

AscendC::Reg::StoreAlign<uint16_t, AscendC::Reg::StoreDist::DIST_PACK_B16>(
    dstPtr + i * SCALE_STORE_STRIDE, expOut, dataMaskB16Half);

AscendC::Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, preMaskScale);
AscendC::Reg::Sub(halfScale, scaleBias, extractExp, preMaskScale);
AscendC::Reg::Select<uint32_t>(halfScale, halfScale, nanRegTensor, cmpResult);
AscendC::Reg::Select<uint32_t>(halfScale, halfScale, zeroRegTensor32, zeroMask);
```

**要点**: 1）使用 AscendC::Reg:: 带命名空间前缀调用，ZEROING 模式（默认）配合预计算掩码 preMaskScale；2）与 ShiftRights、And(尾数掩码)、Adds(指数+1)、Select(条件舍入) 组成 MX 量化 scale 提取流水线；3）移位位数常量 SHR_NUM_FOR_BF16。

### 实例 4：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **ShiftLefts 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 在 complex_abs 求复数绝对值时，先 ShiftRights 右移 SHR_NUM_FOR_FP32 位抹掉尾数得到指数对齐值，再 ShiftLefts 左移相同位数复原，从而分离出指数因子供后续尾数相减。

（行 120-139）

```cpp
Reg::Select<float>(vB, vAbsSrcReg0, vAbsSrcReg1, preg2);

// 0的处理
Reg::Compare<uint32_t, CMPMODE::EQ>(preg4, (AscendC::Reg::RegTensor<uint32_t>&)vB, vZero,
                                    preg);

// subnormal处理
Reg::Compare<uint32_t, CMPMODE::LT>(preg3, (AscendC::Reg::RegTensor<uint32_t>&)vA,
                                    vMinNormalFloat, preg);
Reg::Mul(vAS, vA, vSCALE_UP, preg);
Reg::Mul(vBS, vB, vSCALE_UP, preg);
Reg::Select(vA, vAS, vA, preg3);
Reg::Select(vB, vBS, vB, preg3);
// 提取A的指数因子（对vAForExp操作）
Reg::ShiftRights(vA0, (AscendC::Reg::RegTensor<uint32_t>&)vA, SHR_NUM_FOR_FP32, preg);
Reg::ShiftLefts(vA0, vA0, SHR_NUM_FOR_FP32, preg);
Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA, vA0,
         preg);
Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB, vA0,
         preg);
```

**要点**: 1）无 mask 参数（M0 全量元素操作），preg 仅作常规 predicate；2）与 ShiftRights 成对使用：右移清尾数+左移复原=构造"仅含指数位、尾数清零"的掩码值；3）移位位数 SHR_NUM_FOR_FP32（23）对应 FP32 尾数位宽。

### 实例 5：abs::AbscomplexCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **ShiftLefts 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 在 abs 求复数绝对值（complex 版本）中，ShiftRights 先右移清尾数、ShiftLefts 再左移复原，构造仅含指数位的掩码值用于分离指数因子。

（行 120-138）

```cpp
Reg::Select<float>(vB, vAbsSrcReg0, vAbsSrcReg1, preg2);

// 0的处理
Reg::Compare<uint32_t, CMPMODE::EQ>(
    preg4, (AscendC::Reg::RegTensor<uint32_t>&)vB, vZero, preg);

// subnormal处理
Reg::Compare<uint32_t, CMPMODE::LT>(
    preg3, (AscendC::Reg::RegTensor<uint32_t>&)vA, vMinNormalFloat, preg);
Reg::Mul(vAS, vA, vSCALE_UP, preg);
Reg::Mul(vBS, vB, vSCALE_UP, preg);
Reg::Select(vA, vAS, vA, preg3);
Reg::Select(vB, vBS, vB, preg3);
// 提取A的指数因子（对vAForExp操作）
Reg::ShiftRights(vA0, (AscendC::Reg::RegTensor<uint32_t>&)vA, SHR_NUM_FOR_FP32, preg);
Reg::ShiftLefts(vA0, vA0, SHR_NUM_FOR_FP32, preg);
Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA, vA0, preg);
Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB, vA0, preg);
```

**要点**: 1）无 mask（M0 全量模式），与实例 4 同模式但来自 abs 算子的 complex 变体；2）移位位数 SHR_NUM_FOR_FP32（23）= FP32 尾数位宽；3）与 Sub 配合：vA-vA0 得到去指数后的尾数部分。

### 实例 6：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreDist, Sub
- **ShiftLefts 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在双轴 dynamic 量化中，将 Pack 后的 E8M0 scale 左移 SHR_NUM_FOR_BF16 位对齐到 BF16 指数域，供后续 1/scale 计算与 inf/invalid 判定。

**片段 1** (行 1223-1241):

```cpp
Reg::ShiftRights(expFP32_0, maxFP32_0, SHR_NUM_FOR_FP32, maskFP32);
// 提取FP32尾数: 与尾数掩码
Reg::And(manFP32_0, maxFP32_0, manMaskFP32, maskFP32);
// 条件舍入: 仅normal场景 (exp>0 && exp<254 && man>0) → exp+1
// 注意: 与CuBALS不同，DynamicDtypeRange Custom不处理subnormal场景
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32_0, NUMBER_ZERO_U32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32_0, NUMBER_TWO_FIVE_FOUR, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32_0, NUMBER_ZERO_U32, p0);
// 执行条件加1
Reg::Adds(maxFP32_0, expFP32_0, 1, maskFP32);
Reg::Select(manFP32_0, maxFP32_0, expFP32_0, p0);
// Pack到uint16 (INF/NAN→0xFF, zero→0 自然通过条件舍入保持, 在BF16域1/scale中统一处理)
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_0, manFP32_0);

// 左移7位，将E8M0值定位到BF16指数域 (用于计算1/scale)
Reg::ShiftLefts(scale1BF16, scale1B16_0, SHR_NUM_FOR_BF16, maskAll);

// --- 输出-1轴scale (uint8) ---
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, scale1B16_0);
```

**片段 2** (行 1284-1301):

```cpp
Reg::Mul((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<float>&)maxFP32_1, invDstTypeMaxReg,
              maskFP32);
Reg::ShiftRights(expFP32_1, maxFP32_1, SHR_NUM_FOR_FP32, maskFP32);
Reg::And(manFP32_1, maxFP32_1, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32_1, NUMBER_ZERO_U32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32_1, NUMBER_TWO_FIVE_FOUR, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32_1, NUMBER_ZERO_U32, p0);
Reg::Adds(maxFP32_1, expFP32_1, 1, maskFP32);
Reg::Select(expFP32_1, maxFP32_1, expFP32_1, p0);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_1, expFP32_1);

// 合并Zero和One，恢复原始列顺序 — scale输出寄存器复用
Reg::Interleave(scale1B16_0, scale1B16_1, scale1B16_0, scale1B16_1);
// 左移7位得到BF16指数格式 — scale1BF16复用
Reg::ShiftLefts(scale1BF16, scale1B16_0, SHR_NUM_FOR_BF16, maskAll);
// 输出scale (uint8) — mxScale1B8复用为mxScale2ZeroB8
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, scale1B16_0);
```

**片段 3** (行 1331-1346):

```cpp
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32_1, NUMBER_ZERO_U32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32_1, NUMBER_TWO_FIVE_FOUR, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32_1, NUMBER_ZERO_U32, p0);
Reg::Adds(maxFP32_1, expFP32_1, 1, maskFP32);
Reg::Select(expFP32_1, maxFP32_1, expFP32_1, p0);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_1, expFP32_1);

// 合并Zero和One — scale输出寄存器复用
Reg::Interleave(scale1B16_0, scale1B16_1, scale1B16_0, scale1B16_1);
// scale1BF16复用
Reg::ShiftLefts(scale1BF16, scale1B16_0, SHR_NUM_FOR_BF16, maskAll);
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale2OneB8, scale1B16_0);

// 计算1/scale — absMax0复用为reversedShareExp2One (循环后死亡，与reversedShareExp1不冲突)
// (与原始DynamicMxQuant一致: 无零值检查)
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, scale1BF16, maxEleBF16, maskAll);
```

**要点**: 1）mode=mask（ZEROING），maskAll 全有效，6 次调用覆盖 -1 轴与 0 轴两路 scale 输出；2）与 Pack(提取最低字节)、Interleave(双路合并) 组合，先 Pack 成 uint16 再左移成 BF16 指数；3）移位位数常量 SHR_NUM_FOR_BF16（7）。

### 实例 7：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, RegTensor, Select, ShiftRights, StoreDist, Sub
- **ShiftLefts 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 swiglu_mx_quant 的 scale 计算中，将 Interleave 合并后的 uint16 scale 左移 SHR_NUM_FOR_BF16 位对齐到 BF16 指数域，用于 inf/invalid 判定与 1/scale 计算。

（行 337-354）

```cpp
Reg::Mul((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<float>&)maxFP32_1,
              (Reg::RegTensor<float>&)invMax, maskFP32);
Reg::ShiftRights(expFP32_1, maxFP32_1, SHR_NUM_FOR_FP32, maskFP32);
Reg::And(manFP32_1, maxFP32_1, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, expFP32_1, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0Odd, expFP32_1, EXP_254, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, manFP32_1, ZERO_FOR_ALL, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1Odd, expFP32_1, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1Odd, manFP32_1, SPECIAL_EXP_THRESHOLD_FP32, p1Odd);
Reg::MaskOr(p0Odd, p0Odd, p1Odd, maskFP32);
Reg::Adds(maxFP32_1, expFP32_1, 1, maskFP32);
Reg::Select(manFP32_1, maxFP32_1, expFP32_1, p0Odd);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_1, manFP32_1);
Reg::Interleave(scale1B16_0, scale1B16_1, scale1B16_0, scale1B16_1);
Reg::ShiftLefts(scale1BF16, scale1B16_0, SHR_NUM_FOR_BF16, maskAll);
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, scale1B16_0);
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, scale1BF16, maxEleBF16, maskAll);
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, scale1BF16, biasE8M0, maskAll);
```

**要点**: 1）mode=mask（ZEROING），maskAll 全有效；与 Interleave、Pack 链式组合处理双路 scale；2）左移后立即用 Compare(NE/EQ) 做 inf 与 invalid 检测；3）移位位数常量 SHR_NUM_FOR_BF16。

### 实例 8：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftRights, StoreDist, Sub
- **ShiftLefts 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: 在 rms_norm_dynamic_mx_quant 求 1/scale 阶段，将提取出的指数左移 SHR_NUM_FOR_BF16 位对齐到 BF16 指数域，再用 scaleBias 减得到 scale 倒数。

（行 440-458）

```cpp
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, exp32, zeroForAll, preMaskScale);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32, halfForMan, preMaskScale);
AscendC::Reg::MaskAnd(p1, p1, p2, preMaskScale);
AscendC::Reg::MaskOr(p0, p0, p1, preMaskScale);

AscendC::Reg::Adds(expAddOne32, exp32, 1, preMaskScale);
AscendC::Reg::Select(extractExp, expAddOne32, exp32, p0);
AscendC::Reg::Select<uint32_t>(extractExp, extractExp, fp8NanRegTensor, cmpResult);
AscendC::Reg::Select<uint32_t>(extractExp, extractExp, zeroRegTensor32, zeroMask);
AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(expOut, extractExp);

AscendC::Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                            AscendC::Reg::StoreDist::DIST_PACK_B16>(mxScaleLocalAddr, expOut,
                                                                         VL_FP32 / NUM_TWO, maskHalf);

AscendC::Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, preMaskScale);
AscendC::Reg::Sub(halfScale, scaleBias, extractExp, preMaskScale);
AscendC::Reg::Select<uint32_t>(halfScale, halfScale, nanRegTensor, cmpResult);
AscendC::Reg::Select<uint32_t>(halfScale, halfScale, zeroRegTensor32, zeroMask);
```

**要点**: 1）ZEROING 模式（默认，文档当前仅支持 ZEROING）配合预计算掩码 preMaskScale，未选中元素置零；2）与 Adds(指数+1)、Select(条件舍入)、Pack 组成 scale 提取链，ShiftLefts 负责域对齐；3）移位位数常量 SHR_NUM_FOR_BF16。

### 实例 9：add_rms_norm_dynamic_mx_quant::ComputeFP4FromHalf

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Compare, CompareScalar, CreateMask, Duplicate, MaskAnd, MaskOr, MaskPattern, MaskReg, Maxs, Mul, Muls, RegTensor, Select, ShiftRights, Truncate
- **ShiftLefts 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 在 add_rms_norm 量化把 half 转为 fp4 时，将修正后的指数左移 SHR_NUM_FOR_FP32 位回填到 FP32 指数位，构造用于尾数缩放的指数因子。

（行 589-611）

```cpp
if constexpr (IsSame<T_Y, fp4x2_e1m2_t>::value) {
    AscendC::Reg::Muls(Reg, Reg, FOUR, pregAll32);
    AscendC::Reg::CompareScalar<float, CMPMODE::LT>(specialMask, Reg, 0, pregAll32);
    AscendC::Reg::Truncate<float, roundMode>(Reg, Reg, pregAll32);
    AscendC::Reg::Muls(Reg, Reg, ONE_FOURTH, pregAll32);
} else {
    AscendC::Reg::Duplicate(maxExpFP32, MAX_EXP_FOR_FP32);
    AscendC::Reg::And(exp0FP32, (AscendC::Reg::RegTensor<int32_t>&)Reg, maxExpFP32, pregAll32);
    AscendC::Reg::ShiftRights(exp0FP32, exp0FP32, SHR_NUM_FOR_FP32, pregAll32);
    AscendC::Reg::Adds(exp0FP32, exp0FP32, FP32_BIAS_NEG, pregAll32);
    AscendC::Reg::Maxs(exp0FP32, exp0FP32, 0, pregAll32);
    AscendC::Reg::Adds(exp0FP32, exp0FP32, NEG_ONE, pregAll32);
    AscendC::Reg::Muls(exp1FP32, exp0FP32, NEG_ONE, pregAll32);
    AscendC::Reg::Adds(exp1FP32, exp1FP32, FP32_BIAS, pregAll32);
    AscendC::Reg::ShiftLefts(exp1FP32, exp1FP32, SHR_NUM_FOR_FP32, pregAll32);

    AscendC::Reg::Mul(Reg, Reg, (AscendC::Reg::RegTensor<float>&)exp1FP32, pregAll32);
    AscendC::Reg::Adds(exp0FP32, exp0FP32, FP32_BIAS, pregAll32);
    AscendC::Reg::ShiftLefts(exp0FP32, exp0FP32, SHR_NUM_FOR_FP32, pregAll32);
    AscendC::Reg::CompareScalar<float, CMPMODE::LT>(specialMask, Reg, 0, pregAll32);
    AscendC::Reg::Truncate<float, roundMode>(Reg, Reg, pregAll32);
    AscendC::Reg::Mul(Reg, Reg, (AscendC::Reg::RegTensor<float>&)exp0FP32, pregAll32);
}
```

**要点**: 1）无 mask（M0 全量），pregAll32 全有效 predicate；2）两次 ShiftLefts 分别构造 exp1（去 bias 指数）和 exp0（带 bias 指数）的左移版本，配合 Mul 做尾数缩放；3）移位位数 SHR_NUM_FOR_FP32（23）。

### 实例 10：cast::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CreateMask, DataCopy, DeInterleave, Duplicate, MaskMergeMode, MaskReg, Or, PostLiteral, RegTensor, UpdateMask
- **ShiftLefts 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 cast 算子把两个 4-bit 元素合并为一个 8-bit 元素时，对 DeInterleave 拆出的高 4 位寄存器左移 SHIFT_FOUR_BITS 位，再用 Or 与低 4 位拼接。

（行 1473-1485）

```cpp
for (uint16_t loopIdx = 0; loopIdx < regLoop; loopIdx++) {
    Reg::DataCopy<MST, Reg::PostLiteral::POST_MODE_UPDATE, ldDist>(vregIn1, srcAddr, regCopyInStep);
    Reg::DataCopy<MST, Reg::PostLiteral::POST_MODE_UPDATE, ldDist>(vregIn2, srcAddr, regCopyInStep);

    Reg::DeInterleave<MMT>(vregDeinter1, vregDeinter2, vregIn1, vregIn2);
    Reg::And<MMT, Reg::MaskMergeMode::ZEROING>(vregMid1, vregDeinter1, vreg4Bit, maskAll);
    Reg::ShiftLefts(vregMid2, vregDeinter2, SHIFT_FOUR_BITS, maskAll);
    Reg::Or<MMT, Reg::MaskMergeMode::ZEROING>(vregOut, vregMid1, vregMid2, maskAll);

    mask = Reg::UpdateMask<MMT>(count);
    Reg::DataCopy<MMT, Reg::PostLiteral::POST_MODE_UPDATE, stDist>(dstAddr,
        vregOut, regCopyOutStep, mask);
}
```

**要点**: 1）mode=mask（ZEROING），maskAll 全有效；与 DeInterleave、And(取低4位)、Or(拼接) 组成 4-bit到8-bit 打包流水线；2）移位位数常量 SHIFT_FOUR_BITS（4）= 4-bit 元素位宽；3）左移+Or 是"位拼接"经典模式：高位左移让出低位，低位 Or 填入。

### 实例 11：swiglu_group_quant::VFProcessSwigluGroupQuantVf

- **来源类型**: `__simd_vf__`
- **共现 API**: And, LoadDist, MaskPattern, ShiftRights, StoreDist
- **ShiftLefts 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint32_t`（实参 1 个，类型: int32_t）
- **语义**: 在 swiglu_group_quant 的 round scale 计算中，将指数位左移 23 位回填到 FP32 指数域，构造 scale 与 invScale 的 FP32 位视图。

（行 597-622）

```cpp
if constexpr (!hasRoundScale) {
    Div(invScale, invCoeff, clampScale, pregMerge);
    StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        (__ubuf__ float*)scaleLocalAddr + j + i * scaleColNum, scale, pregMerge); // copy out scale
} else {
    // bits == (RegTensor<uint32_t>&)scale
    ShiftRights(scale2, (RegTensor<uint32_t>&)scale, static_cast<int16_t>(FAST_LOG_SHIFT_BITS), pregMerge);
    And(scale2, scale2, tmp0, pregMerge);                      // exp
    And(scale3, (RegTensor<uint32_t>&)scale, tmp1, pregMerge); // man_bits
    Compare<uint32_t, AscendC::CMPMODE::NE>(compareMask0, scale3, zeroUint32, pregMerge);
    Select(tmp2, oneUint32, zeroUint32, compareMask0); // man_bits != 0
    Sub(scale3, scale2, tmp3, pregMerge);              // exp - 127
    // exp_scale-uint32 = exp - 127 + (man_bits != 0)
    Add((RegTensor<uint32_t>&)scale4, scale3, tmp2, pregMerge);

    Adds(scale5, scale4, 127, pregMerge); // sf_uint32
    ShiftLefts((RegTensor<int32_t>&)scale, scale5, static_cast<int16_t>(23), pregMerge);
    StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        (__ubuf__ float*)scaleLocalAddr + j + i * scaleColNum, scale, pregMerge); // copy out scale

    Sub(scale5, tmp4, scale4, pregMerge); // 127 - exp_scale
    // ((127 - exp_scale) << 23).view(float32)
    ShiftLefts((RegTensor<int32_t>&)invScale, scale5, static_cast<int16_t>(23), pregMerge);
}
Duplicate(dupInvScale, invScale, pregMain);
```

**要点**: 1）无 mask 参数（A1 模式：仅 1 个标量移位值 23），用 (RegTensor<int32_t>&) 强制按整型位视图操作；2）两次 ShiftLefts：一次构造 scale（exp+127 后左移），一次构造 invScale（127-exp 后左移），形成倒数对；3）移位位数硬编码 23 = FP32 尾数位宽，配合 Adds(±127 bias) 还原 IEEE754 指数。

### 实例 12：rms_norm_grad_quant::MultiReduceSum

- **来源类型**: `__aicore__`
- **共现 API**: MaskPattern
- **ShiftLefts 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: uint32_t, int32_t）
- **语义**: 在 rms_norm_grad_quant 的 reduce 尾部处理中，用 ShiftLefts 对非对齐尾元素左移 0 位并配合 pregTail 掩码，实现"非对齐位置补 0"的对齐写回。

**片段 1** (行 342-351):

```cpp
for (uint16_t r = 0; r < (uint16_t)rows; r++) {
    DataCopy(xTailReg, srcAddr + static_cast<uint32_t>(r * colsAlign2VL_ + colsStartLastTwoVL));
    // 利用shiftleft将非对齐位置补0
    ShiftLefts((RegTensor<uint32_t>&)xTailRegshiftLeft, (RegTensor<uint32_t>&)xTailReg,
               static_cast<int16_t>(0), pregTail);
    DataCopy(srcAddr + static_cast<uint32_t>(r * colsAlign2VL_ + colsStartLastTwoVL), xTailRegshiftLeft,
             maskRegAll);
    DataCopy(srcAddr + static_cast<uint32_t>(r * colsAlign2VL_ + colsStartLastOneVL), srcReg,
             maskRegAll);
}
```

**片段 2** (行 376-383):

```cpp
for (uint16_t r = 0; r < (uint16_t)rows; r++) {
    DataCopy(xTailReg, srcAddr + static_cast<uint32_t>(r * colsAlign2VL_ + colsStartLastOneVL));
    // 利用shiftleft将非对齐位置补0
    ShiftLefts((RegTensor<uint32_t>&)xTailRegshiftLeft, (RegTensor<uint32_t>&)xTailReg,
               static_cast<int16_t>(0), pregTail);
    DataCopy(srcAddr + static_cast<uint32_t>(r * colsAlign2VL_ + colsStartLastOneVL), xTailRegshiftLeft,
             maskRegAll);
}
```

**要点**: 1）移位位数为 0：本质不是移位，而是借助 mask predicate 把超出有效长度的元素置零，再 DataCopy 写回原地址完成对齐；2）无 mask 参数（A1 模式），pregTail 是按 lastTailNum 生成的尾部掩码；3）两次调用分别处理最后两 VL 和最后一 VL 的尾部对齐。

### 实例 13：layer_norm_v4::CalculateMeanVarRCommon

- **来源类型**: `__aicore__`
- **共现 API**: (无)
- **ShiftLefts 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: uint32_t, int32_t）
- **语义**: 在 layer_norm_v4 的 mean/var 归约尾部，用 ShiftLefts 对第二段 x2 左移 0 位并配合 pregLast 掩码补零，再与 x1 相加完成跨 VL 边界的两段归约。

**片段 1** (行 369-381):

```cpp
for (uint16_t a = 0; a < currentANum; a++) {
    uint32_t lastTailNum = lastBinaryAddNum - VL_B32;
    MaskReg pregLast = UpdateMask<float>(lastTailNum);
    RegTensor<float> shlReg;
    DataCopy(x1, tmpUb + static_cast<uint32_t>(a * lastBinaryAddNumAlign));
    DataCopy(x2, tmpUb + static_cast<uint32_t>(a * lastBinaryAddNumAlign + VL_B32));
    ShiftLefts((RegTensor<uint32_t>&)shlReg, (RegTensor<uint32_t>&)x2, static_cast<int16_t>(0),
               pregLast);
    Add(x1, x1, shlReg, pregFull);
    ReduceSum(mean, x1, pregFull);
    Muls(mean, mean, nCorrectionFactor, pregOne);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(meanInUb + a, mean, pregOne);
}
```

**片段 2** (行 470-479):

```cpp
for (uint16_t a = 0; a < currentANum; a++) {
    DataCopy(x1, tmpUb + static_cast<uint32_t>(a * lastBinaryAddNumAlign));
    DataCopy(x2, tmpUb + static_cast<uint32_t>(a * lastBinaryAddNumAlign + VL_B32));
    ShiftLefts((RegTensor<uint32_t>&)shlReg, (RegTensor<uint32_t>&)x2, static_cast<int16_t>(0),
               pregLast);
    Add(x1, x1, shlReg, pregFull);
    ReduceSum(var, x1, pregFull);
    Muls(var, var, nCorrectionFactor, pregOne);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(rstdInUb + a, var, pregOne);
}
```

**要点**: 1）移位位数 0 + pregLast 掩码 = 把 x2 超出 lastTailNum 的元素置零，避免脏数据进入 Add/ReduceSum；2）无 mask 参数（A1 模式），(RegTensor<uint32_t>&) 按整型位视图处理 float 数据；3）两次调用分别用于 mean 和 var 的尾部两段相加归约。

### 实例 14：batch_norm::WelfordRARFinalizeVarVF

- **来源类型**: `__aicore__`
- **共现 API**: (无)
- **ShiftLefts 调用次数**: 1
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: uint32_t, int32_t）
- **语义**: 在 batch_norm 的 Welford 方差归约中，用 ShiftLefts 对第二段 xReg2 左移 0 位配合 pregLast 掩码补零，再 Add+ReduceSum 完成两段相加归约。

（行 909-918）

```cpp
for (uint16_t i = 0; i < curAloops; i++) {
    DataCopy(xReg1, tmpLocalUbAddr + static_cast<uint32_t>(i * firstVcaddNumCeilAlign));
    DataCopy(xReg2, tmpLocalUbAddr + static_cast<uint32_t>(i * firstVcaddNumCeilAlign + VL_F32));
    ShiftLefts((RegTensor<uint32_t>&)shiftLeft, (RegTensor<uint32_t>&)xReg2, static_cast<int16_t>(0),
               pregLast);
    Add(addReg, xReg1, shiftLeft, pregFull);
    ReduceSum(sumReg, addReg, pregFull);
    Muls(sumReg, sumReg, scaleCorrection, pregOne);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(batchRstdInUbAddr + i, sumReg, pregOne);
}
```

**要点**: 1）移位位数 0 + pregLast 掩码 = 尾部脏元素置零，保证跨 VL 边界 ReduceSum 正确；2）无 mask 参数（A1 模式），1 次调用，(RegTensor<uint32_t>&) 整型位视图操作 float；3）与 Add、ReduceSum、Muls(scaleCorrection) 组成 RAR 方差归约尾段。

### 实例 15：batch_norm_v3::WelfordRARFinalizeVarVF

- **来源类型**: `__aicore__`
- **共现 API**: (无)
- **ShiftLefts 调用次数**: 1
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: uint32_t, int32_t）
- **语义**: 在 batch_norm_v3 的 Welford 方差归约中，ShiftLefts 对第二段 xReg2 左移 0 位并配合 pregLast 掩码补零，再 Add+ReduceSum 完成两段相加归约。

（行 806-815）

```cpp
for (uint16_t i = 0; i < curAloops; i++) {
    DataCopy(xReg1, tmpLocalUbAddr + static_cast<uint32_t>(i * firstVcaddNumCeilAlign));
    DataCopy(xReg2, tmpLocalUbAddr + static_cast<uint32_t>(i * firstVcaddNumCeilAlign + VL_F32));
    ShiftLefts((RegTensor<uint32_t>&)shiftLeft, (RegTensor<uint32_t>&)xReg2, static_cast<int16_t>(0),
               pregLast);
    Add(addReg, xReg1, shiftLeft, pregFull);
    ReduceSum(sumReg, addReg, pregFull);
    Muls(sumReg, sumReg, scaleCorrection, pregOne);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(batchRstdInUbAddr + i, sumReg, pregOne);
}
```

**要点**: 1）与实例 14 同模式，来自 batch_norm_v3 算子变体，移位位数 0 + pregLast 掩码补零；2）无 mask 参数（A1 模式），1 次调用；3）与 Add、ReduceSum、Muls(scaleCorrection) 组成 RAR 方差归约尾段。

### ShiftLefts 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | mask(ZEROING)+ShiftRights配对，指数左移对齐BF16域求1/scale | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | mask(ZEROING)+预计算掩码，指数左移到BF16域求1/scale | __VEC_SCOPE__ |
| flat_quant | Adds, And, Cast, CastTrait, Compare | mask(ZEROING)+预计算掩码，Reg左移指数对齐BF16域求1/scale | __simd_vf__ |
| complex_abs | Abs, Add, Cast, CastTrait, Compare | 无mask，与ShiftRights配对清尾数-复原指数，分离FP32指数因子 | __aicore__ |
| abs | Abs, Add, Cast, CastTrait, Compare | 无mask，与ShiftRights配对分离FP32指数因子（复数abs） | __aicore__ |
| dynamic_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | mask(ZEROING)，Pack+Interleave后左移scale到BF16域，双轴多路 | __VEC_SCOPE__ |
| swiglu_mx_quant | Adds, And, Cast, Compare, CompareScalar | mask(ZEROING)，Interleave后左移scale到BF16域，配合Compare做inf判定 | __aicore__ |
| rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | mask(ZEROING)+预计算掩码，左移指数到BF16域求1/scale | __aicore__ |
| add_rms_norm_dynamic_mx_quant | Adds, And, Compare, CompareScalar, CreateMask | 无mask，左移指数回填FP32指数域，用于fp4尾数缩放 | __aicore__ |
| cast | And, CreateMask, DataCopy, DeInterleave, Duplicate | mask(ZEROING)，左移高4位+Or拼接低4位，4-bit到8-bit位打包 | __VEC_SCOPE__ |
| swiglu_group_quant | And, LoadDist, MaskPattern, ShiftRights | 无mask单实参，左移23位构造FP32指数域位视图，scale/invScale对 | __simd_vf__ |
| rms_norm_grad_quant | MaskPattern | 无mask单实参，左移0位+尾部掩码补0对齐写回 | __aicore__ |
| layer_norm_v4 |  | 无mask单实参，左移0位+尾部掩码补零，跨VL两段归约 | __aicore__ |
| batch_norm |  | 无mask单实参，左移0位+尾部掩码补零，Welford方差归约 | __aicore__ |
| batch_norm_v3 |  | 无mask单实参，左移0位+尾部掩码补零，Welford方差归约(v3) | __aicore__ |
