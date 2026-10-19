# Mull

**页面ID:** atlasascendc_api_07_0365  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0365.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品            /             Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品            /             Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品            AI Core | x |
| Atlas 推理系列产品            Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

根据mask对输入数据srcReg0、srcReg1按元素相乘操作，将结果写入dstReg0，溢出部分写入dstReg1。

![](images/atlasascendc_api_07_0365_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, typename U>
__simd_callee__ inline void Mull(U& dstReg0, U& dstReg1, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。          Atlas 350 加速卡，支持的数据类型为：uint32_t/int32_t |
| U | 源操作数和目的操作数为RegTensor类型， 例如RegTensor<uint32_t>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg0 | 输出 | 目的操作数。          类型为RegTensor。 |
| dstReg1 | 输出 | 目的操作数。          类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。          类型为RegTensor。          两个源操作数的数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。          类型为RegTensor。          两个源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void MullVF(__ubuf__ T* dst0Addr, __ubuf__ T* dst1Addr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg0;
    AscendC::Reg::RegTensor<T> dstReg1;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);        
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Mull(dstReg0, dstReg1, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dst0Addr + i * oneRepeatSize, dstReg0, mask);
        AscendC::Reg::StoreAlign(dst1Addr + i * oneRepeatSize, dstReg1, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Mull 实例

### 实例 1：non_zero::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, Arange, MaskReg, Mul, Muls, RegTensor, Sub, UpdateMask
- **Mull 调用次数**: 2
- **参数模式**: `T0_A5_M0_TYPEnone`（实参 5 个）
- **语义（待补充）**: non_zero 算子中用 Mull 计算「被乘数 × 倒数魔数」的全宽乘积，配合 Add + ShiftRights 实现按不变除数的快速整数除法，用于把线性索引分解为多维坐标。

**片段 1** (行 795-823):

```cpp
for (uint16_t i = 0; i < repeatTimes; i++) {
    preg = AscendC::Reg::UpdateMask<int32_t>(sreg);
    DataCopy(srcReg, srcPtr + i * repeatElmB32);
    // first output
    Mull(divReg0, divReg, srcReg, mReg, preg);
    Add(divReg0, srcReg, divReg, preg);
    ShiftRights(divReg, divReg0, kValue, preg);
    Mul(mulReg, divReg, shape12Reg, preg);
    Sub(subReg, srcReg, mulReg, preg);
    Muls(idxTransReg, (AscendC::Reg::RegTensor<uint32_t>&)idxReg, shapeDim_, preg);
    DataCopyScatter(dstPtr, divReg, idxTransReg, preg);
    AscendC::Reg::Adds(idxReg, idxReg, repeatElmB32, preg);
    // middle outputs
    for (uint16_t j = 0; j < loopShape; j++) {
        Duplicate(shape2Reg, multipDim.GetValue(j + 1));
        Duplicate(mReg1, multipDim.GetValue(j + IDX_NUM_16 + 1));
        Mull(divReg0, divReg1, subReg, mReg1, preg);
        Add(divReg0, subReg, divReg1, preg);
        ShiftRights(divReg1, divReg0, (int16_t)(multipDim.GetValue(j + IDX_NUM_8 + 1)), preg);
        Mul(mul2Reg, divReg1, shape2Reg, preg);
        Sub(subReg, subReg, mul2Reg, preg);
        Adds(addidxReg, idxTransReg, j + 1, preg);
        DataCopyScatter(dstPtr, divReg1, addidxReg, preg);
    }
    // last output
    Adds(addidxReg, idxTransReg, loopShape + 1, preg);
    DataCopyScatter(dstPtr, subReg, addidxReg, preg);
}
```

**片段 2** (行 809-819):

```cpp
for (uint16_t j = 0; j < loopShape; j++) {
    Duplicate(shape2Reg, multipDim.GetValue(j + 1));
    Duplicate(mReg1, multipDim.GetValue(j + IDX_NUM_16 + 1));
    Mull(divReg0, divReg1, subReg, mReg1, preg);
    Add(divReg0, subReg, divReg1, preg);
    ShiftRights(divReg1, divReg0, (int16_t)(multipDim.GetValue(j + IDX_NUM_8 + 1)), preg);
    Mul(mul2Reg, divReg1, shape2Reg, preg);
    Sub(subReg, subReg, mul2Reg, preg);
    Adds(addidxReg, idxTransReg, j + 1, preg);
    DataCopyScatter(dstPtr, divReg1, addidxReg, preg);
}
```

**要点**:
1. Mull 的 5 个实参对应 `(dstReg0=低位积, dstReg1=高位积/溢出, srcReg0=被乘数, srcReg1=魔数, preg=mask)`；本例中高位积 `divReg` 才是除法商的来源。
2. `Mull → Add(divReg0, srcReg, divReg) → ShiftRights(divReg, divReg0, kValue)` 是 Granlund-Möller「乘法替代除法」的舍入校正写法，必须同时用到 Mull 输出的低/高两半。
3. mask(`preg`) 由 `UpdateMask<int32_t>(sreg)` 生成本 repeat 的有效元素掩码，控制 Mull 仅作用于有效位。

### 实例 2：non_zero::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, CreateMask, MaskPattern, MaskReg, Mul, RegTensor, Sub, UpdateMask
- **Mull 调用次数**: 6
- **参数模式**: `T0_A5_M0_TYPEnone`（实参 5 个）
- **语义（待补充）**: non_zero 算子 4 维转置主循环：连续 3 次 Mull 用不同魔数 mReg0/mReg1/mReg2 做快速除法，分别取商与余数把线性索引拆成 4 维坐标，再用 Interleave 完成转置写出。

**片段 1** (行 705-736):

```cpp
for (uint16_t i = 0; i < repeatTimes; i++) {
    DataCopy(srcReg, srcPtr + i * repeatElm);
    Mull(divReg0, divReg, srcReg, mReg0, preg);
    Add(divReg0, srcReg, divReg, preg);
    ShiftRights(divReg, divReg0, kValue0, preg);

    Mul(mulReg, divReg, shapeReg0, preg);
    Sub(subReg, srcReg, mulReg, preg);

    Mull(divReg0, divReg1, subReg, mReg1, preg);
    Add(divReg0, subReg, divReg1, preg);
    ShiftRights(divReg1, divReg0, kValue1, preg);
    Mul(mulReg, divReg1, shapeReg1, preg);
    Sub(subReg, subReg, mulReg, preg);

    Mull(divReg0, divReg2, subReg, mReg2, preg);
    Add(divReg0, subReg, divReg2, preg);
    ShiftRights(divReg2, divReg0, kValue2, preg);
    Mul(mulReg, divReg2, shapeReg2, preg);
    Sub(subReg, subReg, mulReg, preg);
    // 4维度转置
    Interleave(trans1Reg, trans2Reg, divReg, divReg2);
    Interleave(trans3Reg, trans4Reg, divReg1, subReg);
    Interleave(divReg, divReg1, trans1Reg, trans3Reg);
    Interleave(divReg2, subReg, trans2Reg, trans4Reg);

    DataCopy(dstPtr + i * repeatElm * 4, divReg, preg);
    DataCopy(dstPtr + i * repeatElm * 4 + repeatElm, divReg1, preg);
    DataCopy(dstPtr + i * repeatElm * 4 + repeatElm * 2, divReg2, preg);
    DataCopy(dstPtr + i * repeatElm * 4 + repeatElm * 3, subReg, preg);
}
```

**片段 2** (行 738-772):

```cpp
for (uint16_t i = 0; i < tailLoop; i++) {
    DataCopy(srcReg, srcPtr + repeatTimes * repeatElm);
    Mull(divReg0, divReg, srcReg, mReg0, preg);
    Add(divReg0, srcReg, divReg, preg);
    ShiftRights(divReg, divReg0, kValue0, preg);

    Mul(mulReg, divReg, shapeReg0, preg);
    Sub(subReg, srcReg, mulReg, preg);

    Mull(divReg0, divReg1, subReg, mReg1, preg);
    Add(divReg0, subReg, divReg1, preg);
    ShiftRights(divReg1, divReg0, kValue1, preg);
    Mul(mulReg, divReg1, shapeReg1, preg);
    Sub(subReg, subReg, mulReg, preg);

    Mull(divReg0, divReg2, subReg, mReg2, preg);
    Add(divReg0, subReg, divReg2, preg);
    ShiftRights(divReg2, divReg0, kValue2, preg);
    Mul(mulReg, divReg2, shapeReg2, preg);
    Sub(subReg, subReg, mulReg, preg);

    Interleave(trans1Reg, trans2Reg, divReg, divReg2);
    Interleave(trans3Reg, trans4Reg, divReg1, subReg);
    Interleave(divReg, divReg1, trans1Reg, trans3Reg);
    Interleave(divReg2, subReg, trans2Reg, trans4Reg);
    preg1 = AscendC::Reg::UpdateMask<int32_t>(sreg);
    preg2 = AscendC::Reg::UpdateMask<int32_t>(sreg);
    preg3 = AscendC::Reg::UpdateMask<int32_t>(sreg);
    preg4 = AscendC::Reg::UpdateMask<int32_t>(sreg);
    DataCopy(dstPtr + repeatTimes * repeatElm * 4, divReg, preg1);
    DataCopy(dstPtr + repeatTimes * repeatElm * 4 + repeatElm, divReg1, preg2);
    DataCopy(dstPtr + repeatTimes * repeatElm * 4 + repeatElm * 2, divReg2, preg3);
    DataCopy(dstPtr + repeatTimes * repeatElm * 4 + repeatElm * 3, subReg, preg4);
}
```

**要点**:
1. 一次循环内 Mull 串联 3 次（魔数 mReg0/mReg1/mReg2 对应 3 个不同除数），每次都遵循 `Mull → Add → ShiftRights → Mul → Sub` 取商取余的固定模板。
2. Mull 的高位输出（dstReg1，此处 divReg/divReg1/divReg2）放商，配合 `Sub(subReg, srcReg, mulReg)` 得到对应维余数 subReg。
3. tailLoop 分支用独立的 `preg1~preg4` 重建 mask，处理尾部不满一个 repeat 的残块元素。

### 实例 3：non_zero::VecScope_L641

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, CreateMask, MaskPattern, MaskReg, Mul, RegTensor, Sub, UpdateMask
- **Mull 调用次数**: 2
- **参数模式**: `T0_A5_M0_TYPEnone`（实参 5 个）
- **语义（待补充）**: non_zero 算子 2 维转置：单次 Mull 做快速除法得到一维商与余数，再用 Interleave 把商/余两半拼成 2 维转置结果写出。

**片段 1** (行 650-661):

```cpp
for (uint16_t i = 0; i < repeatTimes; i++) {
    DataCopy(srcReg, srcPtr + i * repeatElmB32_);
    Mull(divReg0, divReg, srcReg, mReg, preg);
    Add(divReg0, srcReg, divReg, preg);
    ShiftRights(divReg, divReg0, kValue, preg);
    Mul(mulReg, divReg, shapeReg, preg);
    Sub(subReg, srcReg, mulReg, preg);
    // 2维转置
    Interleave(trans1Reg, trans2Reg, divReg, subReg);
    DataCopy(dstPtr + i * repeatElmB32_ * 2, trans1Reg, preg);
    DataCopy(dstPtr + i * repeatElmB32_ * 2 + repeatElmB32_, trans2Reg, preg);
}
```

**片段 2** (行 662-675):

```cpp
for (uint16_t i = 0; i < tailLoop; i++) {
    preg1 = AscendC::Reg::UpdateMask<int32_t>(sreg);
    preg2 = AscendC::Reg::UpdateMask<int32_t>(sreg);
    DataCopy(srcReg, srcPtr + repeatTimes * repeatElmB32_);
    Mull(divReg0, divReg, srcReg, mReg, preg);
    Add(divReg0, srcReg, divReg, preg);
    ShiftRights(divReg, divReg0, kValue, preg);
    Mul(mulReg, divReg, shapeReg, preg);
    Sub(subReg, srcReg, mulReg, preg);
    // 2维转置
    Interleave(trans1Reg, trans2Reg, divReg, subReg);
    DataCopy(dstPtr + repeatTimes * repeatElmB32_ * 2, trans1Reg, preg1);
    DataCopy(dstPtr + repeatTimes * repeatElmB32_ * 2 + repeatElmB32_, trans2Reg, preg2);
}
```

**要点**:
1. 是实例 2 的 2 维退化版：`Mull → Add → ShiftRights → Mul → Sub` 取商 divReg 与余数 subReg，再 Interleave 两半。
2. Mull 高位(dstReg1=divReg)进商，低位(dstReg0)配合 Add 做舍入校正后右移复原商。
3. 主循环用 `preg`，尾部 tailLoop 用 `preg1/preg2` 重建 mask 处理残块。

### 实例 4：non_zero::VecScope_L879

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, MaskReg, Mul, RegTensor, Sub, UpdateMask
- **Mull 调用次数**: 2
- **参数模式**: `T0_A5_M0_TYPEnone`（实参 5 个）
- **语义（待补充）**: non_zero 算子多输出索引分解：Mull 在主循环和中间 j 循环里分别做首输出与中间输出的快速除法，把索引按 multipDim 逐维拆解后分散写回 DataCopy。

**片段 1** (行 888-911):

```cpp
for (uint16_t i = 0; i < repeatTimes; i++) {
    preg = AscendC::Reg::UpdateMask<int32_t>(sreg);
    DataCopy(srcReg, srcPtr + i * repeatElmB32_);
    // first output
    Mull(divReg0, divReg, srcReg, mReg0, preg);
    Add(divReg0, srcReg, divReg, preg);
    ShiftRights(divReg, divReg0, kValue, preg);
    DataCopy(dstPtr + i * repeatElmB32_, divReg, preg);
    Mul(mulReg, divReg, shapeReg0, preg);
    Sub(subReg, srcReg, mulReg, preg);
    // middle outputs
    for (uint16_t j = 0; j < loopShape; j++) {
        Duplicate(shape2Reg, multipDim.GetValue(j + 1));
        Duplicate(mReg1, multipDim.GetValue(j + IDX_NUM_16 + 1));
        Mull(divReg0, divReg1, subReg, mReg1, preg);
        Add(divReg0, subReg, divReg1, preg);
        ShiftRights(divReg1, divReg0, (int16_t)(multipDim.GetValue(j + IDX_NUM_8 + 1)), preg);
        DataCopy(dstPtr + processSize_ * (j + 1) + i * repeatElmB32_, divReg1, preg);
        Mul(mul2Reg, divReg1, shape2Reg, preg);
        Sub(subReg, subReg, mul2Reg, preg);
    }
    // last output
    DataCopy(dstPtr + processSize_ * (shapeDim_ - 1) + i * repeatElmB32_, subReg, preg);
}
```

**片段 2** (行 899-908):

```cpp
for (uint16_t j = 0; j < loopShape; j++) {
    Duplicate(shape2Reg, multipDim.GetValue(j + 1));
    Duplicate(mReg1, multipDim.GetValue(j + IDX_NUM_16 + 1));
    Mull(divReg0, divReg1, subReg, mReg1, preg);
    Add(divReg0, subReg, divReg1, preg);
    ShiftRights(divReg1, divReg0, (int16_t)(multipDim.GetValue(j + IDX_NUM_8 + 1)), preg);
    DataCopy(dstPtr + processSize_ * (j + 1) + i * repeatElmB32_, divReg1, preg);
    Mul(mul2Reg, divReg1, shape2Reg, preg);
    Sub(subReg, subReg, mul2Reg, preg);
}
```

**要点**:
1. 首输出与中间输出各用一次 Mull（魔数 mReg0 / mReg1），中间循环按 `multipDim` 动态 `Duplicate` 魔数与形状。
2. 写出用 `DataCopy(dstPtr + processSize_*(j+1) + i*repeatElmB32_, ...)` 按维偏移落址，体现 Mull 结果（商）直接驱动多维寻址。
3. 每轮 `UpdateMask<int32_t>(sreg)` 重建 preg，保证 tail 与中间段的有效元素位正确。

### 实例 5：pool_3d_common::FastDivImpl

- **来源类型**: `__aicore__`
- **共现 API**: Add, RegTensor, ShiftRights
- **Mull 调用次数**: 2
- **参数模式**: `T0_A5_M1_TYPEnone_MASKmask`（实参 5 个，含 mask/mode: mask）
- **语义（待补充）**: pool_3d_common 的 FastDivImpl：用 Mull 计算 src×magic 的全宽乘积，配合 Add + ShiftRights 实现「除以不变除数」的快速整数除法，mask 控制参与运算的元素。

（行 875-880）

```cpp
{
    Reg::RegTensor<uint32_t> tmp;
    Reg::Mull(tmp, res, src, magic, mask);
    Reg::Add(tmp, src, res, mask);
    Reg::ShiftRights(res, tmp, shift, mask);
}
```

**要点**:
1. 最简洁的 Mull 快速除法范式：`Mull(tmp, res, src, magic, mask) → Add(tmp, src, res, mask) → ShiftRights(res, tmp, shift, mask)`，三行即 `res = src / divisor`。
2. tmp 接低位积、res 接高位积（溢出半），随后 `tmp = src + res`、`res = tmp >> shift` 完成商的舍入校正。
3. 显式 mask 形参使该 helper 可在任意有效元素掩码下复用，是池化算子里做整除下采样的标准片段。

### 实例 6：avg_pool::FastDivImpl

- **来源类型**: `__aicore__`
- **共现 API**: Add, RegTensor, ShiftRights
- **Mull 调用次数**: 2
- **参数模式**: `T0_A5_M1_TYPEnone_MASKmask`（实参 5 个，含 mask/mode: mask）
- **语义（待补充）**: avg_pool 的 FastDivImpl：与 pool_3d_common 相同的 Mull 快速除法实现，用于平均池化中按 kernel 体积做整除缩放。

（行 821-826）

```cpp
{
    Reg::RegTensor<uint32_t> tmp;
    Reg::Mull(tmp, res, src, magic, mask);
    Reg::Add(tmp, src, res, mask);
    Reg::ShiftRights(res, tmp, shift, mask);
}
```

**要点**:
1. 与实例 5 逐字相同的 `Mull → Add → ShiftRights` 三件套，说明该范式在池化算子间被当作通用整除工具复用。
2. magic / shift 由外部按除数预计算后传入，Mull 只负责「一次乘法拿到全宽积」这一步。
3. mask 形参让 helper 兼顾满块与尾部残块两种场景。

### Mull 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| non_zero | Add, Adds, Arange, MaskReg, Mul | 快速整数除法（乘魔数 + Add + ShiftRights），把线性索引分解为多维坐标 | __VEC_SCOPE__ |
| non_zero | Add, CreateMask, MaskPattern, MaskReg, Mul | 连续 3 次 Mull 快速除法取商/余，配合 Interleave 做 4 维转置 | __VEC_SCOPE__ |
| non_zero | Add, CreateMask, MaskPattern, MaskReg, Mul | 单次 Mull 快速除法取商/余，配合 Interleave 做 2 维转置 | __VEC_SCOPE__ |
| non_zero | Add, MaskReg, Mul, RegTensor | Mull 快速除法驱动多输出索引分解，按维偏移 DataCopy 落址 | __VEC_SCOPE__ |
| pool_3d_common | Add, RegTensor, ShiftRights | FastDivImpl——Mull + Add + ShiftRights 三件套实现除以不变除数，显式 mask | __aicore__ |
| avg_pool | Add, RegTensor, ShiftRights | 同实例 5 的 FastDivImpl 范式，用于平均池化整除缩放 | __aicore__ |

