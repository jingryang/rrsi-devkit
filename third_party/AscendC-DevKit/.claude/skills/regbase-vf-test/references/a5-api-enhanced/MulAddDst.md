# MulAddDst

**页面ID:** atlasascendc_api_07_0380  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0380.html

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

srcReg0与srcReg1相乘再加上dstReg的值， 根据mask将计算结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0380_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void MulAddDst(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 矢量目的操作数和源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：uint16_t/int16_t/uint32_t/int32_t/half/float/bfloat16_t/uint64_t/int64_t |
| mode | 选择MERGING模式或ZEROING模式。- ZEROING，mask未筛选的元素在dst中置零。- MERGING，当前不支持。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void MulAddDstVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::MulAddDst(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

---
## 从 Ascend 950PR / arch35 算子源码提取的 MulAddDst 实例

### 实例 1：lerp::Compute3

- **来源类型**: `__aicore__`
- **共现 API**: Cast, CompareScalar, CreateMask, DataCopy, Duplicate, LoadDist, MaskMergeMode, Select, StoreDist, Sub, UpdateMask
- **MulAddDst 调用次数**: 2
- **参数模式**: `T2_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义**: lerp 算子按输入是否小于 0.5 分两支做线性插值；half 输入先 Cast 到 float，用 Sub 算出权重差项，再用两次 MulAddDst(dst,src0,src1) 完成 dst=src0*src1+dst 的融合乘加拼出两条插值分支，最后 Select 按比较结果选出输出。

（行 152-175）

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = AscendC::Reg::UpdateMask<float>(size);
    AscendC::Reg::DataCopy<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg0, bufferIn0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, half, castTrait0>(vreg1, vreg0, preg0);
    AscendC::Reg::CompareScalar<float, AscendC::CMPMODE::LT>(preg2, vreg1, static_cast<float>(0.5),
                                                                  preg0);
    AscendC::Reg::DataCopy<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg2, bufferIn1Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, half, castTrait0>(vreg3, vreg2, preg0);
    AscendC::Reg::DataCopy<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg4, bufferIn2Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, half, castTrait0>(vreg5, vreg4, preg0);
    AscendC::Reg::Sub<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg6, vreg3, vreg5, preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg5, vreg1, vreg6,
                                                                                   preg0);
    AscendC::Reg::Sub<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg8, vreg1, vreg7, preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg3, vreg8, vreg6,
                                                                                   preg0);
    AscendC::Reg::Select<float>(vreg9, vreg5, vreg3, preg2);
    AscendC::Reg::Cast<half, float, castTrait1>(vreg10, vreg9, preg0);
    AscendC::Reg::DataCopy<half, AscendC::Reg::StoreDist::DIST_PACK_B32>(
        bufferOut0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4), vreg10, preg0);
}
```

**要点**: 1) 显式模板 <float, ZEROING> 指定 float 计算与 ZEROING 模式；2) mask preg0 来自 UpdateMask<float>(size) 处理尾段元素；3) MulAddDst 读改写同一 dstReg，省去额外 Add 指令。

### 实例 2：lerp::Compute3

- **来源类型**: `__aicore__`
- **共现 API**: CompareScalar, CreateMask, DataCopy, Duplicate, LoadDist, MaskMergeMode, Select, StoreDist, Sub, UpdateMask
- **MulAddDst 调用次数**: 2
- **参数模式**: `T2_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义**: lerp 在 float 输入下的同结构实现，DataCopy 直接以 DIST_NORM 加载 float 省去 Cast；两次 MulAddDst 分别构造两条插值分支，Select 按 CompareScalar 结果选支。

（行 148-167）

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = AscendC::Reg::UpdateMask<float>(size);
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(
        vreg0, bufferIn0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::CompareScalar<float, AscendC::CMPMODE::LT>(preg26, vreg0, static_cast<float>(0.5),
                                                                  preg0);
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(
        vreg1, bufferIn1Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(
        vreg2, bufferIn2Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Sub<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg3, vreg1, vreg2, preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg2, vreg0, vreg3,
                                                                                   preg0);
    AscendC::Reg::Sub<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg5, vreg0, vreg4, preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg1, vreg5, vreg3,
                                                                                   preg0);
    AscendC::Reg::Select<float>(vreg6, vreg2, vreg1, preg26);
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_NORM_B32>(
        bufferOut0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4), vreg6, preg0);
}
```

**要点**: 1) float 路径无 Cast、LoadDist 用 DIST_NORM；2) 模板仍显式 <float, ZEROING>；3) 存储用 DIST_NORM_B32。

### 实例 3：tanh_grad::Compute2

- **来源类型**: `__aicore__`
- **共现 API**: Cast, DataCopy, Duplicate, LoadDist, MaskMergeMode, Mul, Muls, StoreDist, UpdateMask
- **MulAddDst 调用次数**: 1
- **参数模式**: `T2_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义**: tanh 反向梯度计算：Muls 把输入乘 -1 得 -x，MulAddDst(vreg4, vreg2, vreg1) 在 Duplicate 预置的 1.0 初值上累加 (-x)*x+1 = 1-x²，再与梯度 Mul 得到 (1-x²)·grad。

（行 128-145）

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = AscendC::Reg::UpdateMask<float>(size);
    AscendC::Reg::DataCopy<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg0, bufferIn0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, half, castTrait0>(vreg1, vreg0, preg0);
    AscendC::Reg::Duplicate<float, float>(vreg4, 1.0);
    AscendC::Reg::Muls<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(
        vreg2, vreg1, static_cast<float>(-1), preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(
        vreg4, vreg2, vreg1, preg0);
    AscendC::Reg::DataCopy<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg5, bufferIn1Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, half, castTrait0>(vreg6, vreg5, preg0);
    AscendC::Reg::Mul<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg7, vreg4, vreg6, preg0);
    AscendC::Reg::Cast<half, float, castTrait1>(vreg8, vreg7, preg0);
    AscendC::Reg::DataCopy<half, AscendC::Reg::StoreDist::DIST_PACK_B32>(
        bufferOut0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4), vreg8, preg0);
}
```

**要点**: 1) Duplicate(vreg4, 1.0) 预置 1.0 作为 MulAddDst 的 dst 初值；2) 仅 1 次 MulAddDst 调用；3) 与 lerp 共现 API 不同（Mul/Muls 而非 Select/Sub）。

### 实例 4：softmax_grad_ext::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, DataCopy, LoadDist, LocalMemBar, MaskReg, MemType, RegTensor, StoreDist, UpdateMask
- **MulAddDst 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: softmax_grad_ext 的逐通道累加：每轮 UpdateMask<float>(sreg) 生成尾段 mask，MulAddDst(vregSum, vregX0, vregX1, pregMask) 把 x0*x1 累加进 vregSum，循环结束后写回 xSum。

（行 240-261）

```cpp
for (uint16_t k = 0; k < loopA0Num; k++) {
    pregMask = Reg::UpdateMask<float>(sreg);
    uint32_t xOffset = i * aLen + k * VL_FP32;
    Reg::DataCopy<float, Reg::LoadDist::DIST_NORM>(vregSum,
                                                             (__ubuf__ float*)xSumLocalAddr + k * VL_FP32);
    if constexpr (xIsFp32_) {
        Reg::DataCopy<float, Reg::LoadDist::DIST_NORM>(vregX0,
                                                                 (__ubuf__ float*)gradLocalAddr + xOffset);
        Reg::DataCopy<float, Reg::LoadDist::DIST_NORM>(vregX1,
                                                                 (__ubuf__ float*)x1LocalAddr + xOffset);
    } else { // fp16, bf16
        Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(vregX0B16,
                                                                   ((__ubuf__ T*)gradLocalAddr + xOffset));
        Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(vregX1B16,
                                                                   ((__ubuf__ T*)x1LocalAddr + xOffset));
        Reg::Cast<float, T, castTraitFp16ToFp32>(vregX0, vregX0B16, pregMask);
        Reg::Cast<float, T, castTraitFp16ToFp32>(vregX1, vregX1B16, pregMask);
    }
    Reg::MulAddDst(vregSum, vregX0, vregX1, pregMask);
    Reg::DataCopy<float, Reg::StoreDist::DIST_NORM>((__ubuf__ float*)xSumLocalAddr + k * VL_FP32,
                                                              vregSum, pregMask);
}
```

**要点**: 1) 无显式模板参数，类型由 RegTensor 推导；2) mask 变量名 pregMask（pattern 捕获为 Mask）；3) fp16/bf16 经 Cast 转 float 再参与乘加，与 LocalMemBar 共现。

### 实例 5：tanh_grad::Compute2

- **来源类型**: `__aicore__`
- **共现 API**: DataCopy, Duplicate, LoadDist, MaskMergeMode, Mul, Muls, StoreDist, UpdateMask
- **MulAddDst 调用次数**: 1
- **参数模式**: `T2_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义**: tanh 反向梯度的 float 版本，结构与实例 3 一致：Muls(-1) 取负、MulAddDst 在 1.0 初值上累加得到 1-x²，再 Mul 梯度。

（行 125-139）

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = AscendC::Reg::UpdateMask<float>(size);
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(
        vreg0, bufferIn0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Duplicate<float, float>(vreg3, 1.0);
    AscendC::Reg::Muls<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(
        vreg2, vreg0, static_cast<float>(-1), preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(
        vreg3, vreg2, vreg0, preg0);
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(
        vreg4, bufferIn1Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Mul<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg5, vreg3, vreg4, preg0);
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_NORM_B32>(
        bufferOut0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4), vreg5, preg0);
}
```

**要点**: 1) float 路径无 Cast、LoadDist=DIST_NORM；2) Duplicate(vreg3,1.0) 提供 dst 初值；3) with_loops 循环结构。

### 实例 6：scale::ScaleMulAddVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, CreateAddrReg, LoadAlign, MaskReg, RegTensor, StoreAlign, UpdateMask
- **MulAddDst 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: scale 算子的 ScaleMulAddVF：用 Reg:: 命名空间 API，CreateAddrReg 生成地址、LoadAlign 取三路源/目的，MulAddDst(dstReg, srcReg0, srcReg1, mask) 做 dst=src0*src1+dst 的 in-place 乘加，StoreAlign 写回。

（行 381-395）

```cpp
{
    AscendC::Reg::RegTensor<T> srcReg0, srcReg1, dstReg;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::AddrReg aReg;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
        uint32_t remain = count - (uint32_t)i * oneRepeatSize;
        mask = AscendC::Reg::UpdateMask<T>(remain);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr, aReg);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr, aReg);
        AscendC::Reg::LoadAlign(dstReg, dstAddr, aReg);
        AscendC::Reg::MulAddDst(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr, dstReg, aReg, mask);
    }
}
```

**要点**: 1) Reg:: 旧式 API（与 Reg 路径对照）；2) mask 由 UpdateMask<T>(remain) 按剩余元素生成；3) LoadAlign 对齐加载三路 src0/src1/dst。

### 实例 7：adam_apply_one_assign::MulAddVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, CreateAddrReg, LoadAlign, MaskReg, RegTensor, StoreAlign, UpdateMask
- **MulAddDst 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: Adam 优化器一步更新中的 MulAddVF：结构与实例 6 相同的 Reg:: 三路 LoadAlign + MulAddDst + StoreAlign 封装，用于把梯度与动量的乘积累加进目的寄存器。

（行 411-424）

```cpp
{
    AscendC::Reg::RegTensor<T> srcReg0, srcReg1, dstReg;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::AddrReg aReg;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr, aReg);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr, aReg);
        AscendC::Reg::LoadAlign(dstReg, dstAddr, aReg);
        AscendC::Reg::MulAddDst(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr, dstReg, aReg, mask);
    }
}
```

**要点**: 1) mask 用 UpdateMask<T>(count)（整块，非 remain）；2) 与实例 6 对比可见同一封装套用在不同算子；3) Reg:: 路径，无显式模板参数。

### 实例 8：softmax_grad::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, MaskMergeMode, MaskPattern, MaskReg, RegTensor, UpdateMask
- **MulAddDst 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: softmax 反向 full-load 路径：对满段用 pFull、尾段用 pMask，两次 MulAddDst(reg1, reg0, reg2, mask) 完成 (-x)*sum + reg1 形式的梯度计算，Neg 先取负。

（行 190-221）

```cpp
{
    uint32_t count = static_cast<uint32_t>(rSize - VL_FP32);
    AscendC::Reg::RegTensor<float> reg0, reg1, reg0_1, reg1_1, reg2, reg2_1;
    AscendC::Reg::MaskReg pMask = AscendC::Reg::UpdateMask<float>(count);
    AscendC::Reg::MaskReg
        pFull = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg maskOri;
    for (uint16_t i = 0; i < loopTimes; i++) {
        LoadTensorForDtypeTIn(x0, reg0, pFull, i * rAligned);
        LoadTensorForDtypeTIn(x1, reg1, pFull, i * rAligned);
        LoadTensorForDtypeTIn(x0_1, reg0_1, pMask, i * rAligned);
        LoadTensorForDtypeTIn(x1_1, reg1_1, pMask, i * rAligned);

        Mul(reg2, reg0, reg1, pFull);
        Mul(reg2_1, reg0_1, reg1_1, pMask);

        Add<float, AscendC::Reg::MaskMergeMode::ZEROING>(reg2_1, reg2, reg2_1, pMask);
        Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(reg2, reg2_1, pMask);
        ReduceSum(reg2, reg2, pFull);
        Duplicate(reg2, reg2, pFull);

        Mul(reg1, reg0, reg1, pFull);
        Neg(reg0, reg0, pFull);
        MulAddDst(reg1, reg0, reg2, pFull);
        StoreTensorForDtypeTOut(dst, reg1, pFull, i * rAligned);

        Mul(reg1_1, reg0_1, reg1_1, pMask);
        Neg(reg0_1, reg0_1, pMask);
        MulAddDst(reg1_1, reg0_1, reg2, pMask);
        StoreTensorForDtypeTOut(dst, reg1_1, pMask, i * rAligned + VL_FP32);
    }
}
```

**要点**: 1) 无显式模板参数；2) 同时使用 pFull(CreateMask ALL) 与 pMask(UpdateMask count) 两套 mask；3) VEC_SCOPE 内裸名调用 MulAddDst。

### 实例 9：softmax_grad::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, MaskPattern, MaskReg, RegTensor, UpdateMask
- **MulAddDst 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: softmax 反向的逐行 recompute 段：内层按 UpdateMask<float>(sreg0) 生成 maskOri，Neg 取负后 MulAddDst(reg1, reg0, reg2, maskOri) 累加 (-x)*sum，循环覆盖每行尾段。

（行 363-379）

```cpp
for (uint16_t i = 0; i < loopTimes; i++) {
    DataCopy(reg0, (__local_mem__ float*)sumTmp + i * static_cast<uint32_t>(stride));
    ReduceSum(reg1, reg0, pMask);
    Duplicate(reg2, reg1, pFull);

    uint32_t sreg0 = static_cast<uint32_t>(oriR);
    for (uint16_t j = 0; j < rLoopCount; j++) {
        maskOri = AscendC::Reg::UpdateMask<float>(sreg0);
        uint32_t offset = j * VL_FP32 + i * oriRAligned;
        LoadTensorForDtypeTIn(x0, reg0, maskOri, offset);
        LoadTensorForDtypeTIn(x1, reg1, maskOri, offset);
        Mul(reg1, reg0, reg1, maskOri);
        Neg(reg0, reg0, maskOri);
        MulAddDst(reg1, reg0, reg2, maskOri);
        StoreTensorForDtypeTOut(dst, reg1, maskOri, offset);
    }
}
```

**要点**: 1) 与实例 8 同文件不同段，mask 变量 maskOri（捕获为 mask）；2) 嵌套 for（外层行、内层尾段）；3) 裸名调用，无模板参数。

### 实例 10：softmax_grad::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: DataCopy, LoadDist, MaskReg, RegTensor, UpdateMask
- **MulAddDst 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: softmax 反向 recompute 版本：DataCopy 把 sum 广播进 sumReg，逐段 UpdateMask 生成 pregMask，Neg + MulAddDst(x1Reg, x0Reg, sumReg, pregMask) 算 (-x)*sum + x1。

（行 265-285）

```cpp
{
    AscendC::Reg::RegTensor<float> sumReg, x0Reg, x1Reg;
    AscendC::Reg::MaskReg pregMask;

    uint32_t sreg = ubFactor;
    uint16_t loopTimes = CeilDivision(ubFactor, VL_FP32);

    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_BRC_B32>(sumReg, xSumLocal);

    for (uint16_t j = 0; j < loopTimes; j++) {
        pregMask = AscendC::Reg::UpdateMask<float>(sreg);
        uint32_t offset = j * VL_FP32;
        LoadTensorForDtypeT(x0Local, x0Reg, pregMask, offset);
        LoadTensorForDtypeT(x1Local, x1Reg, pregMask, offset);

        Mul(x1Reg, x0Reg, x1Reg, pregMask);
        Neg(x0Reg, x0Reg, pregMask);
        MulAddDst(x1Reg, x0Reg, sumReg, pregMask);
        StoreTensorForDtypeTOut(yLocal, x1Reg, pregMask, offset);
    }
}
```

**要点**: 1) 与实例 9 模式相同但来自 recompute kernel；2) mask 变量 pregMask（捕获为 Mask）；3) LoadTensorForDtypeT 封装加载。

### 实例 11：softmax_grad::CalcOutput

- **来源类型**: `__aicore__`
- **共现 API**: Cast, DataCopy, StoreDist
- **MulAddDst 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: softmax 反向小 r 的 CalcOutput：Neg 取负 x0，MulAddDst(x1Reg, x0Reg, sumReg, pregMask) 把 (-x0)*sum 累加进 x1，再按精度 Cast 回 fp16/bf16 存储。

（行 178-193）

```cpp
for (uint16_t i = 0; i < curTileRLenVl; i++) {
    uint32_t xOffset = i * tileA0LenLocal + k * VL_FP32;
    LoadTensorForDtypeT(x0Local, x0Reg, pregMask, xOffset);

    DataCopy(x1Reg, tmpAddr2 + xOffset);
    Neg(x0Reg, x0Reg, pregMask);
    MulAddDst(x1Reg, x0Reg, sumReg, pregMask);

    if constexpr (xToFp32_) {
        Reg::DataCopy(tmpAddrTy + xOffset, x1Reg, pregMask);
    } else { // fp16、bf16
        RegTensor<T> xFp16;
        Reg::Cast<T, float, castTraitFp32ToFp16>(xFp16, x1Reg, pregMask);
        Reg::DataCopy<T, Reg::StoreDist::DIST_PACK_B32>(tmpAddrTy + xOffset, xFp16, pregMask);
    }
}
```

**要点**: 1) __aicore__ 上下文（与 VEC_SCOPE 对照）；2) mask 变量 pregMask；3) if constexpr 分支区分 fp32/fp16 存储路径。

### 实例 12：group_norm_grad::StoreDist::DIST_NORM

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: MaskMergeMode, MulDstAdd
- **MulAddDst 调用次数**: 1
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: group_norm 反向按余段计算 dgamma/dbeta：MulAddDst(vregXQ, vregXR, vregDyR, pregLoop) 把 xR*dyR 累加进 vregXQ，配合 Add、ReduceSum 求规约梯度。

（行 1512-1525）

```cpp
for (uint16_t i = 0; i < remainderGeneral; i++) {
    MaskReg pregLoop = UpdateMask<float>(sreg0);
    LoadUnAlignOneTensor<T>(curUbX, vregXQ, uSrcX, pregMain, sregvl);
    LoadUnAlignOneTensor<T>(curUbXR, vregXR, uSrcXR, pregLoop, sregvl);
    LoadUnAlignOneTensor<T>(curUbDy, vregDyQ, uSrcDy, pregMain, sregvl);
    LoadUnAlignOneTensor<T>(curUbDyR, vregDyR, uSrcDyR, pregLoop, sregvl);
    Mul(vregXQ, vregXQ, vregDyQ, pregMain);
    MulAddDst(vregXQ, vregXR, vregDyR, pregLoop);
    Add(vregDyQ, vregDyQ, vregDyR, pregLoop);
    ReduceSum(vregDgamma, vregXQ, pregLoop);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(ubBinaryDgamma + i, vregDgamma, pregMerge);
    ReduceSum(vregDbeta, vregDyQ, pregLoop);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(ubBinaryDbeta + i, vregDbeta, pregMerge);
}
```

**要点**: 1) 与 MulDstAdd 共现（同一算子内两种复合乘加对照）；2) pregLoop/pregMain 双 mask；3) 裸名调用，无模板参数。

### 实例 13：lerp::Compute3

- **来源类型**: `__aicore__`
- **共现 API**: Cast, CompareScalar, CreateMask, DataCopy, Duplicate, LoadDist, MaskMergeMode, Select, StoreDist, Sub, UpdateMask
- **MulAddDst 调用次数**: 2
- **参数模式**: `T2_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义**: lerp 的 bfloat16 版本：DataCopy 用 DIST_UNPACK_B16 加载 bf16，Cast 到 float 后与实例 1 同样的两次 MulAddDst + Select 分支结构。

（行 155-178）

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = AscendC::Reg::UpdateMask<float>(size);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg0, bufferIn0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, bfloat16_t, castTrait0>(vreg1, vreg0, preg0);
    AscendC::Reg::CompareScalar<float, AscendC::CMPMODE::LT>(preg48, vreg1, static_cast<float>(0.5),
                                                                  preg0);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg2, bufferIn1Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, bfloat16_t, castTrait0>(vreg3, vreg2, preg0);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg4, bufferIn2Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, bfloat16_t, castTrait0>(vreg5, vreg4, preg0);
    AscendC::Reg::Sub<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg6, vreg3, vreg5, preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg5, vreg1, vreg6,
                                                                                   preg0);
    AscendC::Reg::Sub<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg8, vreg1, vreg7, preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg3, vreg8, vreg6,
                                                                                   preg0);
    AscendC::Reg::Select<float>(vreg9, vreg5, vreg3, preg48);
    AscendC::Reg::Cast<bfloat16_t, float, castTrait1>(vreg10, vreg9, preg0);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::StoreDist::DIST_PACK_B32>(
        bufferOut0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4), vreg10, preg0);
}
```

**要点**: 1) bf16 路径经 Cast<float, bfloat16_t> 升精度；2) without_loops 单段处理；3) 存储用 DIST_PACK_B32。

### 实例 14：lerp::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CompareScalar, CreateMask, DataCopy, Duplicate, LoadDist, MaskMergeMode, Select, StoreDist, Sub, UpdateMask
- **MulAddDst 调用次数**: 2
- **参数模式**: `T2_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义**: lerp 的 Ops::Base/__VEC_SCOPE__ 版本，与实例 1（Compute3/__aicore__）计算逻辑相同，但位于 VEC_SCOPE 上下文、以 AscendC::Reg:: 调用，体现同一算子在不同 kernel 层的复用。

（行 152-175）

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = AscendC::Reg::UpdateMask<float>(size);
    AscendC::Reg::DataCopy<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg0, bufferIn0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, half, castTrait0>(vreg1, vreg0, preg0);
    AscendC::Reg::CompareScalar<float, AscendC::CMPMODE::LT>(preg2, vreg1, static_cast<float>(0.5),
                                                                  preg0);
    AscendC::Reg::DataCopy<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg2, bufferIn1Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, half, castTrait0>(vreg3, vreg2, preg0);
    AscendC::Reg::DataCopy<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg4, bufferIn2Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, half, castTrait0>(vreg5, vreg4, preg0);
    AscendC::Reg::Sub<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg6, vreg3, vreg5, preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg5, vreg1, vreg6,
                                                                                   preg0);
    AscendC::Reg::Sub<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg8, vreg1, vreg7, preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg3, vreg8, vreg6,
                                                                                   preg0);
    AscendC::Reg::Select<float>(vreg9, vreg5, vreg3, preg2);
    AscendC::Reg::Cast<half, float, castTrait1>(vreg10, vreg9, preg0);
    AscendC::Reg::DataCopy<half, AscendC::Reg::StoreDist::DIST_PACK_B32>(
        bufferOut0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4), vreg10, preg0);
}
```

**要点**: 1) 与实例 1 同文件同行段但来源类型 __VEC_SCOPE__；2) 对比可见 aicore Compute3 与 VEC_SCOPE Ops::Base 两种封装；3) half 路径，两次 MulAddDst。

### 实例 15：lerp::Compute3

- **来源类型**: `__aicore__`
- **共现 API**: CompareScalar, CreateMask, DataCopy, Duplicate, LoadDist, MaskMergeMode, Select, StoreDist, Sub, UpdateMask
- **MulAddDst 调用次数**: 2
- **参数模式**: `T2_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义**: lerp 的 float without_loops 版本，与实例 2（with_loops）计算结构相同，区别在于不展开 repeat 循环、单段处理。

（行 150-169）

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = AscendC::Reg::UpdateMask<float>(size);
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(
        vreg0, bufferIn0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::CompareScalar<float, AscendC::CMPMODE::LT>(preg26, vreg0, static_cast<float>(0.5),
                                                                  preg0);
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(
        vreg1, bufferIn1Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(
        vreg2, bufferIn2Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Sub<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg3, vreg1, vreg2, preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg2, vreg0, vreg3,
                                                                                   preg0);
    AscendC::Reg::Sub<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg5, vreg0, vreg4, preg0);
    AscendC::Reg::MulAddDst<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg1, vreg5, vreg3,
                                                                                   preg0);
    AscendC::Reg::Select<float>(vreg6, vreg2, vreg1, preg26);
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_NORM_B32>(
        bufferOut0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4), vreg6, preg0);
}
```

**要点**: 1) float 路径无 Cast；2) without_loops 单段；3) 与实例 2 对照 with/without loops 差异。

### MulAddDst 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| lerp | Cast, CompareScalar, CreateMask, DataCopy, Duplicate | half 输入 Cast→float，Sub 算差项，两次 MulAddDst 拼双分支 + Select 选支 | __aicore__ |
| lerp | CompareScalar, CreateMask, DataCopy, Duplicate, LoadDist | float 直加载，两次 MulAddDst 拼双分支 + Select 选支 | __aicore__ |
| tanh_grad | Cast, DataCopy, Duplicate, LoadDist, MaskMergeMode | Duplicate 置 1.0 作 dst 初值，Muls 取负后 MulAddDst 算 1-x² | __aicore__ |
| softmax_grad_ext | Cast, DataCopy, LoadDist, LocalMemBar, MaskReg | 逐通道 UpdateMask，MulAddDst 把 x0*x1 累加进 sum | __VEC_SCOPE__ |
| tanh_grad | DataCopy, Duplicate, LoadDist, MaskMergeMode, Mul | float 版，Duplicate 置 1.0，MulAddDst 算 1-x² | __aicore__ |
| scale | AddrReg, CreateAddrReg, LoadAlign, MaskReg | Reg:: 三路 LoadAlign + MulAddDst + StoreAlign，mask 按剩余元素 | __simd_vf__ |
| adam_apply_one_assign | AddrReg, CreateAddrReg, LoadAlign, MaskReg | Reg:: 三路 LoadAlign + MulAddDst + StoreAlign，mask 按整块 count | __simd_vf__ |
| softmax_grad | CreateMask, MaskMergeMode, MaskPattern, MaskReg | pFull/pMask 双 mask，Neg+MulAddDst 算 (-x)*sum | __VEC_SCOPE__ |
| softmax_grad | CreateMask, MaskPattern, MaskReg, RegTensor | maskOri 尾段 mask，Neg+MulAddDst 累加 (-x)*sum | __VEC_SCOPE__ |
| softmax_grad | DataCopy, LoadDist, MaskReg, RegTensor | DataCopy 广播 sum，pregMask 尾段，Neg+MulAddDst | __VEC_SCOPE__ |
| softmax_grad | Cast, DataCopy, StoreDist | Neg+MulAddDst 算 (-x0)*sum，按精度 Cast 回存 | __aicore__ |
| group_norm_grad | MaskMergeMode, MulDstAdd | MulAddDst 累加 xR*dyR 进 dgamma，双 mask pregLoop/pregMain | __VEC_SCOPE__ |
| lerp | Cast, CompareScalar, CreateMask, DataCopy, Duplicate | bf16 Cast→float，两次 MulAddDst+Select 双分支 | __aicore__ |
| lerp | Cast, CompareScalar, CreateMask, DataCopy, Duplicate | 与实例1同逻辑，VEC_SCOPE/Ops::Base 上下文复用 | __VEC_SCOPE__ |
| lerp | CompareScalar, CreateMask, DataCopy, Duplicate, LoadDist | float 单段，两次 MulAddDst+Select 双分支 | __aicore__ |
