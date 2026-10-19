# Xor

**页面ID:** atlasascendc_api_07_0364  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0364.html

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

本节介绍两种接口，分别用于对RegTensor和MaskReg进行操作：

- 对RegTensor操作：

根据mask对输入数据srcReg0、srcReg1按元素异或（^）操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0364_img_001.png)

- 对MaskReg操作：

将两个输入MaskReg的有效bit进行逻辑异或运算得到新的MaskReg。

#### 函数原型

- 对RegTensor操作

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Xor(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

- 对MaskReg操作

```
__simd_callee__ inline void Xor(MaskReg& dst, MaskReg& src0, MaskReg& src1, MaskReg& mask)
```

#### 参数说明

- 对RegTensor操作

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：bool/uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/uint64_t/int64_t |
| mode | 选择MERGING模式或ZEROING模式。   - ZEROING，mask未筛选的元素在dst中置零。  - MERGING，当前不支持。 |
| U | srcReg0/srcReg1/dstReg RegTensor类型， 例如RegTensor<uint32_t>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

- 对MaskReg操作

**表3 **参数说明

| 参数名 | 描述 |
| --- | --- |
| dst | 目的操作数。 |
| src0 | 源操作数。 |
| src1 | 源操作数。 |
| mask | 指示在计算过程中哪些bit有效。 |

#### 约束说明

无

#### 调用示例

- 对RegTensor操作

```
template <typename T>
__simd_vf__ inline void XorVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);       
        AscendC::Reg::Xor(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 对MaskReg操作

```
template <typename T>
__simd_vf__ inline void XorVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg src0 = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALLF>();
    AscendC::Reg::MaskReg src1 = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg dst;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < (uint16_t)repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Xor(dst, src0, src1, mask);
        AscendC::Reg::Adds(srcReg, srcReg, 0, dst);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, srcReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Xor 实例

### 实例 1：sort::TwiddleInFp16

- **来源类型**: `__aicore__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, Duplicate, MaskReg, Not, PostLiteral, RegTensor, Select, UpdateMask
- **Xor 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask）
- **语义**: radix_sort 的 TwiddleIn fp16 路径中，先用 And+CompareScalar(NE)+Select 组合算出非零标志位向量 finalMaskOne，再用 Xor 将输入与该向量按位异或翻转符号位（twiddle），随后 CompareScalar(EQ) 检测负零并改写为正零。

（行 138-173）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    xorMask = Reg::UpdateMask<uint16_t>(inputNum);
    // load input
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputReg, xValuePtr, VF_LEN_B16);
    // vand
    Reg::RegTensor<uint16_t> andValueOne;
    Reg::And(andValueOne, inputReg, vandMask, maskB16);
    // not equal
    Reg::MaskReg cmpValueOne;
    Reg::CompareScalar<uint16_t, CMPMODE::NE>(cmpValueOne, andValueOne, ZERO_VALUE_FLAG_B16, maskB16);
    // vsel
    Reg::RegTensor<uint16_t> finalMaskOne;
    Reg::Select(finalMaskOne, xorMaskReg, vandMask, cmpValueOne);
    // vxor
    Reg::RegTensor<uint16_t> xorVectorOne;
    Reg::Xor(xorVectorOne, inputReg, finalMaskOne, maskB16);

    // 目前每个round都会做twiddleIn，因此直接在twiddleIn方法将负0转换为正0
    // 如果后期需要改为单次twiddleIn，则需要在提取位数时将负0转换为正0
    // get -0.0 mask
    Reg::MaskReg minusZeroMask;
    Reg::CompareScalar<uint16_t, CMPMODE::EQ>(
        minusZeroMask, xorVectorOne, TWIDDLED_MINUS_ZERO_BITS_FP16, maskB16);
    // change -0.0 to +0.0
    Reg::RegTensor<uint16_t> resultReg;
    Reg::Select(resultReg, twiddledZeroReg, xorVectorOne, minusZeroMask);

    if constexpr (isDescend == 0) {
        Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
            uXValuePtr, resultReg, VF_LEN_B16, xorMask);
    } else {
        Reg::Not(vnotReg, resultReg, xorMask);
        Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
            uXValuePtr, vnotReg, VF_LEN_B16, xorMask);
    }
}
```

**要点**: (1) Xor 第 4 参 maskB16 控制有效元素，与 And/CompareScalar/Select 共用同一 mask 保证按元素一致；(2) Xor 用于按位翻转符号位而非逻辑异或值，配合 Select+CompareScalar 完成负零→正零修正；(3) isDescend 分支用 Not 对结果再取反，体现 Xor/Not 在排序方向控制上的组合使用。

### 实例 2：sort::TwiddleInFp32

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, Duplicate, MaskReg, Not, PostLiteral, RegTensor, Select, UpdateMask
- **Xor 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask）
- **语义**: 实例 1 的 fp32 版本，在 __VEC_SCOPE__ 上下文执行 radix_sort twiddle：And+CompareScalar(NE)+Select 得到 finalMaskOne，Xor 翻转符号位，再检测负零改写为正零，模板参数为 uint32_t。

（行 194-229）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    xorMask = Reg::UpdateMask<uint32_t>(inputNum);
    // load input
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputReg, xValuePtr, VF_LEN_B32);
    // vand
    Reg::RegTensor<uint32_t> andValueOne;
    Reg::And(andValueOne, inputReg, vandMask, maskB32);
    // not equal
    Reg::MaskReg cmpValueOne;
    Reg::CompareScalar<uint32_t, CMPMODE::NE>(cmpValueOne, andValueOne, ZERO_VALUE_FLAG_B32, xorMask);
    // vsel
    Reg::RegTensor<uint32_t> finalMaskOne;
    Reg::Select(finalMaskOne, xorMaskReg, vandMask, cmpValueOne);
    // vxor
    Reg::RegTensor<uint32_t> xorVectorZero;
    Reg::Xor(xorVectorZero, inputReg, finalMaskOne, maskB32);

    // 目前每个round都会做twiddleIn，因此直接在twiddleIn方法将负0转换为正0
    // 如果后期需要改为单次twiddleIn，则需要在提取位数时将负0转换为正0
    // get -0.0 mask
    Reg::MaskReg minusZeroMask;
    Reg::CompareScalar<uint32_t, CMPMODE::EQ>(
        minusZeroMask, xorVectorZero, TWIDDLED_MINUS_ZERO_BITS_FP32, maskB32);
    // change -0.0 to +0.0
    Reg::RegTensor<uint32_t> resultReg;
    Reg::Select(resultReg, twiddledZeroReg, xorVectorZero, minusZeroMask);

    if constexpr (isDescend == 0) {
        Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
            uXValuePtr, resultReg, VF_LEN_B32, xorMask);
    } else {
        Reg::Not(vnotReg, resultReg, maskB32);
        Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
            uXValuePtr, vnotReg, VF_LEN_B32, xorMask);
    }
}
```

**要点**: (1) 与实例 1 仅数据宽度不同（B32 vs B16），模板参数 uint32_t，体现 Xor 对多数据类型的统一支持；(2) 第 4 参 mask 在升序路径 xorMask、降序路径 maskB32 间切换，mask 选择受排序方向影响；(3) Xor 调用次数 2，与 And/Select 配合完成提取符号位→翻转→修正负零三段式处理。

### 实例 3：top_k_v2::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, Select, UpdateMask
- **Xor 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: top_k_v2 基数排序 b16 块排序路径：加载输入后 And+CompareScalar(NE)+Select 构造 finalMaskOne，Xor 将输入与 finalMaskOne 异或得到 xorVectorOne 再写回，用于按位区分键值。

（行 375-393）

```cpp
// load input
Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    inputVectorOne, inputXValuePtr, ONE_TIMES_B16_NUM);
// vxor
Reg::RegTensor<uint16_t> andValueOne;
Reg::And(andValueOne, inputVectorOne, vandMask, predicateDefaultB16);
// not equal
Reg::MaskReg cmpValueOne;
Reg::CompareScalar<uint16_t, CMPMODE::NE>(
    cmpValueOne, andValueOne, ZERO_VALUE_FLAG_B16, predicateDefaultB16);
// vsel
Reg::RegTensor<uint16_t> finalMaskOne;
Reg::Select(finalMaskOne, xorMaskVector, vandMask, cmpValueOne);
// vxor
Reg::RegTensor<uint16_t> xorVectorOne;
Reg::Xor(xorVectorOne, inputVectorOne, finalMaskOne, predicateDefaultB16);
// sts
Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    uinputXValuePtr, xorVectorOne, ONE_TIMES_B16_NUM, xorMask);
```

**要点**: (1) 与 sort 的 twiddle 模式同构（And→Compare→Select→Xor→Store），该组合是 radix 类算子通用 pattern；(2) mask 用 predicateDefaultB16 全有效，Xor 第 4 参控制写回范围；(3) 单次加载+单次 Xor+单次 Store，无 repeat 循环包裹，适用于定长块排序。

### 实例 4：top_k_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, Select, UpdateMask
- **Xor 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: top_k_v2 b32 路径的 repeat 循环版本：每轮 UpdateMask 生成 xorMask，加载输入后 And+CompareScalar(NE)+Select 得到 finalMaskOne，Xor 翻转符号位后写回，处理变长输入。

（行 345-363）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg xorMask = Reg::UpdateMask<uint32_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtr, ONE_TIMES_B32_NUM);
    // vxor
    Reg::RegTensor<uint32_t> andValueOne;
    Reg::And(andValueOne, inputVectorOne, vandMask, xorMask);
    // not equal
    Reg::MaskReg cmpValueOne;
    Reg::CompareScalar<uint32_t, CMPMODE::NE>(cmpValueOne, andValueOne, ZERO_VALUE_FLAG_B32, xorMask);
    // vsel
    Reg::RegTensor<uint32_t> finalMaskOne;
    Reg::Select(finalMaskOne, xorMaskVector, vandMask, cmpValueOne);
    // vxor
    Reg::RegTensor<uint32_t> xorVectorZero;
    Reg::Xor(xorVectorZero, inputVectorOne, finalMaskOne, predicateDefault);
    // sts
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(uinputXValuePtr, xorVectorZero, ONE_TIMES_B32_NUM, xorMask);
}
```

**要点**: (1) xorMask 由 UpdateMask<uint32_t>(inputElementNum) 动态生成，处理尾部不满 repeat 的元素；(2) Xor 第 4 参用 predicateDefault 全有效而非 xorMask，mask 仅约束加载/存储范围，体现 mask 作用域精细划分；(3) And/CompareScalar/Select/Xor 四元组在 repeat 循环内逐轮复用，是 radix sort 主循环典型骨架。

### 实例 5：top_k_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Xor 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: top_k_v2 b32 的简化路径：无 And/Compare/Select 前置，UpdateMask 后加载输入，Xor 与固定 xorValueVector 异或得到 xorVectorZero 再写回，用于键值的直接按位翻转。

（行 282-291）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg xorMask = Reg::UpdateMask<uint32_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtr, ONE_TIMES_B32_NUM);
    // vxor
    Reg::RegTensor<uint32_t> xorVectorZero;
    Reg::Xor(xorVectorZero, inputVectorOne, xorValueVector, predicateDefault);
    // sts
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(uinputXValuePtr, xorVectorZero, ONE_TIMES_B32_NUM, xorMask);
}
```

**要点**: (1) 参数模式 T0_A4_M0 无 mask/mode 标记，Xor 第 4 参用 predicateDefault 全有效，不依赖逐元素 mask；(2) 与实例 4 相比省去符号位提取（And/Compare/Select），直接对固定 xorValueVector 异或，适用于无需区分符号的场景；(3) xorMask 仅用于 StoreAlign 写回范围控制，Xor 计算本身不受 mask 约束。

### 实例 6：top_k_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Xor 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: top_k_v2 b64 路径：UpdateMask<uint64_t> 生成 mask，加载 uint64_t 输入后与 xorValueVectorZero 异或得到 vstVectorZero 写回，处理 64 位键值的按位翻转。

（行 281-290）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    Reg::MaskReg xorMask = Reg::UpdateMask<uint64_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorZero, inputXValuePtr, ONE_TIMES_B64_NUM);
    // vxor
    Reg::RegTensor<uint64_t> vstVectorZero;
    Reg::Xor(vstVectorZero, inputVectorZero, xorValueVectorZero, predicateDefaultB64);
    // sts
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(uinputXValuePtr, vstVectorZero, ONE_TIMES_B64_NUM, xorMask);
}
```

**要点**: (1) 数据类型 uint64_t（B64），Xor 模板参数随键宽变化，覆盖 b8/b16/b32/b64 全宽度；(2) 无 mask 模式 T0_A4_M0，第 4 参 predicateDefaultB64，xorMask 只约束 StoreAlign；(3) 与实例 5 结构一致仅宽度不同，体现 Xor 对不同整数宽度的统一调用形式。

### 实例 7：top_k_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Xor 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: top_k_v2 b8 路径：UpdateMask<uint8_t> 生成 xorMask，加载 uint8_t 输入后与 xorValueVector 异或得到 xorVectorZero 写回，用于 8 位键值的按位翻转。

（行 241-250）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg xorMask = Reg::UpdateMask<uint8_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtr, ONE_TIMES_B8_NUM);
    // vxor
    Reg::RegTensor<uint8_t> xorVectorZero;
    Reg::Xor(xorVectorZero, inputVectorOne, xorValueVector, xorMask);
    // sts
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(uinputXValuePtr, xorVectorZero, ONE_TIMES_B8_NUM, xorMask);
}
```

**要点**: (1) 参数模式 T0_A4_M1 含 Mask，Xor 第 4 参直接用 xorMask，mask 同时约束计算与写回；(2) 数据类型 uint8_t（B8）是 top_k 支持的最窄宽度，mask 实现字节级元素的有效控制；(3) 与实例 5/6 无 mask 版本对比，本例 mask 传入 Xor 本身，适用于需逐字节筛选的场景。

### 实例 8：bitwise_xor::XorCompute

- **来源类型**: `__aicore__`
- **共现 API**: DataCopy, LoadDist, MaskReg, RegTensor, StoreDist, UpdateMask
- **Xor 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: bitwise_xor 算子主体 XorCompute：按 loopTimes 循环，UpdateMask 生成 preg，分别 LoadDist 加载两个源操作数 src1/src2，Xor 按元素异或得到 resValue，再 StoreDist 写回，是 Xor 作为按位异或算子最直接的用法。

（行 51-59）

```cpp
for (uint16_t j = 0; j < loopTimes; j++) {
    preg = Reg::UpdateMask<T>(sregMask);
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(src1Value, inputX1Addr + VL_T * j);
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(src2Value, inputX2Addr + VL_T * j);

    Reg::Xor(resValue, src1Value, src2Value, preg);

    Reg::DataCopy<T, Reg::StoreDist::DIST_NORM>(dstAddr + VL_T * j, resValue, preg);
}
```

**要点**: (1) 这是 Xor 的本义用法——两个独立源操作数按位异或，区别于排序场景的符号位翻转；(2) 第 4 参 preg 由 UpdateMask<T>(sregMask) 生成，模板参数 T 使其适配多宽度；(3) LoadDist::DIST_NORM/StoreDist::DIST_NORM 与 Xor 配合，构成加载-异或-存储三步数据流。

### 实例 9：sort::Twiddle

- **来源类型**: `__aicore__`
- **共现 API**: DataCopy, MaskReg, Not, PostLiteral, RegTensor, UpdateMask
- **Xor 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: sort 通用 Twiddle 模板：UpdateMask<UT> 生成 xorMask，加载输入后 Xor 与 xorReg 异或翻转符号位；isDescend 分支用 Not 再取反实现降序，是 sort 符号位处理的最简骨架。

（行 42-52）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    xorMask = Reg::UpdateMask<UT>(inputNum);
    Reg::DataCopy<UT, Reg::PostLiteral::POST_MODE_UPDATE>(inputReg, xValuePtr, vfLen);
    Reg::Xor(xorResult, inputReg, xorReg, xorMask);
    if constexpr (isDescend == 0) {
        Reg::DataCopy<UT, Reg::PostLiteral::POST_MODE_UPDATE>(uXValuePtr, xorResult, vfLen, xorMask);
    } else {
        Reg::Not(vnotReg, xorResult, xorMask);
        Reg::DataCopy<UT, Reg::PostLiteral::POST_MODE_UPDATE>(uXValuePtr, vnotReg, vfLen, xorMask);
    }
}
```

**要点**: (1) 模板参数 UT 使该片段支持多种整数宽度，Xor 调用形式与宽度无关；(2) isDescend==0 升序直接写回 xorResult，降序先 Not 再写回，Xor/Not 配对实现方向控制；(3) 与实例 1/2 的 TwiddleIn 相比省去负零修正（无 CompareScalar(EQ)+Select），是最简 twiddle 形式。

### 实例 10：bitwise_xor::Vec::ElemwiseBinaryOP

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: DataCopy, LoadDist, MaskReg, RegTensor, StoreDist, UpdateMask
- **Xor 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: bitwise_xor 的 VEC_SCOPE 内联版本 Vec::ElemwiseBinaryOP：与实例 8 逻辑相同（LoadDist 加载双源→Xor 异或→StoreDist 写回），运行在 __VEC_SCOPE__ 上下文，作为元素级二元位运算的 vector 内联实现。

（行 51-59）

```cpp
for (uint16_t j = 0; j < loopTimes; j++) {
    preg = Reg::UpdateMask<T>(sregMask);
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(src1Value, inputX1Addr + VL_T * j);
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(src2Value, inputX2Addr + VL_T * j);

    Reg::Xor(resValue, src1Value, src2Value, preg);

    Reg::DataCopy<T, Reg::StoreDist::DIST_NORM>(dstAddr + VL_T * j, resValue, preg);
}
```

**要点**: (1) 与实例 8 代码一致仅来源类型 __VEC_SCOPE__ 不同，体现同一算子在 aicore 与 VEC_SCOPE 两种上下文复用；(2) Xor 第 4 参 preg 控制有效元素，UpdateMask<T> 适配模板宽度 T；(3) 作为 ElemwiseBinaryOP 通用框架的 Xor 特化，可与 And/Or 等其他位运算共用同一骨架。

### 实例 11：scatter_nd_update::IndexStatisticInt32Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: ShiftRight
- **Xor 调用次数**: 5
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: scatter_nd_update 的索引统计 Int32 路径：主循环并行处理 4 路索引，先 ShiftRight 右移取高位维度，再 Xor 与 xorOffset 异或混入扰动，随后 Muls 乘 FNV 质数做哈希，DeInterleave+Histograms 统计直方图；尾循环用 maskReg 处理剩余元素。

**片段 1** (行 52-88):

```cpp
for (uint16_t i = 0; i < mainLoop; i++) {
    RegTensor<uint32_t> vectorIndex0, vectorIndex1, vectorIndex2, vectorIndex3;
    RegTensor<uint16_t> vectorB16Tmp0, vectorB16Tmp1, vectorB16Tmp2, vectorB16Tmp3;
    RegTensor<uint8_t> vectorB8Hash0, vectorB8Hash1;

    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex1, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex2, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex3, srcM, 64);

    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex1, vectorIndex1, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex2, vectorIndex2, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex3, vectorIndex3, lastDimShiftAmount, patAllB32);

    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Xor(vectorIndex1, vectorIndex1, xorOffset, patAllB32);
    Xor(vectorIndex2, vectorIndex2, xorOffset, patAllB32);
    Xor(vectorIndex3, vectorIndex3, xorOffset, patAllB32);

    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex1, vectorIndex1, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex2, vectorIndex2, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex3, vectorIndex3, FNV_PRIME_B32, patAllB32);

    DeInterleave(vectorB16Tmp0, vectorB16Tmp1, (RegTensor<uint16_t>&)vectorIndex0,
                 (RegTensor<uint16_t>&)vectorIndex1);
    DeInterleave(vectorB16Tmp2, vectorB16Tmp3, (RegTensor<uint16_t>&)vectorIndex2,
                 (RegTensor<uint16_t>&)vectorIndex3);
    DeInterleave(vectorB8Hash0, vectorB8Hash1, (RegTensor<uint8_t>&)vectorB16Tmp0,
                 (RegTensor<uint8_t>&)vectorB16Tmp2);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(histVector0, vectorB8Hash0,
                                                                                      patAllB8);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(histVector1, vectorB8Hash0,
                                                                                      patAllB8);
}
```

**片段 2** (行 90-102):

```cpp
for (uint16_t i = 0; i < tailLoop; i++) {
    MaskReg maskReg = UpdateMask<uint32_t>(tailNum);
    RegTensor<uint32_t> vectorIndex0;
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
}
```

**要点**: (1) Xor 用于哈希扰动——与常量 xorOffset 异或打乱索引位，配合 Muls(FNV_PRIME) 完成哈希散列，区别于符号位翻转；(2) 参数模式 T0_A4_M0，第 4 参 patAllB32 全有效，主循环无逐元素 mask，尾循环片段 2 用 maskReg 处理尾部；(3) Xor 调用次数 5（主循环 4 路+尾循环 1），与 ShiftRight/Muls/DeInterleave/Histograms 构成索引哈希统计流水线。

### 实例 12：scatter_nd_common::IndexStatisticInt32VF

- **来源类型**: `__simd_vf__`
- **共现 API**: ShiftRight
- **Xor 调用次数**: 5
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: scatter_nd_common 的索引统计 Int32 路径，与实例 11 结构同构（ShiftRight→Xor(xorOffset)→Muls(FNV)→DeInterleave→Histograms），仅所属算子不同，主循环 4 路并行加尾循环 maskReg 处理剩余。

**片段 1** (行 51-87):

```cpp
for (uint16_t i = 0; i < mainLoop; i++) {
    RegTensor<uint32_t> vectorIndex0, vectorIndex1, vectorIndex2, vectorIndex3;
    RegTensor<uint16_t> vectorB16Tmp0, vectorB16Tmp1, vectorB16Tmp2, vectorB16Tmp3;
    RegTensor<uint8_t> vectorB8Hash0, vectorB8Hash1;

    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex1, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex2, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex3, srcM, 64);

    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex1, vectorIndex1, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex2, vectorIndex2, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex3, vectorIndex3, lastDimShiftAmount, patAllB32);

    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Xor(vectorIndex1, vectorIndex1, xorOffset, patAllB32);
    Xor(vectorIndex2, vectorIndex2, xorOffset, patAllB32);
    Xor(vectorIndex3, vectorIndex3, xorOffset, patAllB32);

    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex1, vectorIndex1, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex2, vectorIndex2, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex3, vectorIndex3, FNV_PRIME_B32, patAllB32);

    DeInterleave(vectorB16Tmp0, vectorB16Tmp1, (RegTensor<uint16_t>&)vectorIndex0,
                 (RegTensor<uint16_t>&)vectorIndex1);
    DeInterleave(vectorB16Tmp2, vectorB16Tmp3, (RegTensor<uint16_t>&)vectorIndex2,
                 (RegTensor<uint16_t>&)vectorIndex3);
    DeInterleave(vectorB8Hash0, vectorB8Hash1, (RegTensor<uint8_t>&)vectorB16Tmp0,
                 (RegTensor<uint8_t>&)vectorB16Tmp2);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(histVector0, vectorB8Hash0,
                                                                                      patAllB8);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(histVector1, vectorB8Hash0,
                                                                                      patAllB8);
}
```

**片段 2** (行 89-101):

```cpp
for (uint16_t i = 0; i < tailLoop; i++) {
    MaskReg maskReg = UpdateMask<uint32_t>(tailNum);
    RegTensor<uint32_t> vectorIndex0;
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
}
```

**要点**: (1) 与实例 11 代码近乎一致，说明 scatter 系列算子共享同一 IndexStatistic 工具函数，Xor 用法（哈希扰动）可复用；(2) 主循环 Xor 第 4 参 patAllB32 全有效，尾循环改用 maskReg 适配变长尾部；(3) Xor 与 ShiftRight 紧邻，先移位取维度再异或扰动，是索引哈希的固定两步预处理。

### 实例 13：scatter_nd_common::IndexStatisticInt64VF

- **来源类型**: `__simd_vf__`
- **共现 API**: ShiftRight
- **Xor 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: maskReg, mask）
- **语义**: scatter_nd_common 的索引统计 Int64 路径：UpdateMask<uint64_t> 生成 maskReg，加载索引后 ShiftRight 取高位维度，Xor 与 xorOffset 异或扰动，Muls 乘 FNV_PRIME_B64 哈希，再 Histograms 统计、Max 取直方图峰值。

（行 157-169）

```cpp
for (uint16_t i = 0; i < loopSize; i++) {
    MaskReg maskReg = UpdateMask<uint64_t>(dataLen);
    DataCopy(vectorIndex0, srcM);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, maskReg);
    Xor(vectorIndex0, vectorIndex0, xorOffset, maskReg);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B64, maskReg);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Max(maxValue, histVector0, histVector1, patAllB16);
}
```

**要点**: (1) 参数模式 T0_A4_M1 含 maskReg+mask，Xor 第 4 参 maskReg 由 UpdateMask<uint64_t>(dataLen) 动态生成，处理 64 位变长数据；(2) 与 Int32 路径（实例 12）对应，仅宽度 64 位、质数常量 FNV_PRIME_B64，Xor 调用形式不变；(3) Xor 调用次数 1（单路处理无 4 路并行），maskReg 贯穿 ShiftRight/Xor/Muls/Histograms 全流程。

### 实例 14：inplace_index_add::IndexStatisticInt64Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: ShiftRight
- **Xor 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: maskReg, mask）
- **语义**: inplace_index_add 的索引统计 Int64 路径，与实例 13 结构同构（UpdateMask→ShiftRight→Xor(xorOffset)→Muls(FNV_PRIME_B64)→Histograms→Max），仅所属算子不同。

（行 155-167）

```cpp
for (uint16_t i = 0; i < loopSize; i++) {
    MaskReg maskReg = UpdateMask<uint64_t>(dataLen);
    DataCopy(vectorIndex0, srcM);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, maskReg);
    Xor(vectorIndex0, vectorIndex0, xorOffset, maskReg);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B64, maskReg);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Max(maxValue, histVector0, histVector1, patAllB16);
}
```

**要点**: (1) 与实例 13 代码一致，体现 scatter/inplace_index 系列共享 IndexStatisticInt64Vf 工具函数；(2) maskReg 同时约束 Xor 计算与后续 Histograms，保证尾部元素正确统计；(3) Xor 用于索引哈希扰动（与 xorOffset 异或）而非符号位翻转，是 scatter 类算子共性用法。

### 实例 15：scatter_nd_add::IndexStatisticInt64Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: ShiftRight
- **Xor 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: maskReg, mask）
- **语义**: scatter_nd_add 的索引统计 Int64 路径，与实例 13/14 同构（UpdateMask<uint64_t>→ShiftRight→Xor(xorOffset)→Muls(FNV_PRIME_B64)→Histograms→Max），仅算子归属不同。

（行 129-141）

```cpp
for (uint16_t i = 0; i < loopSize; i++) {
    MaskReg maskReg = UpdateMask<uint64_t>(dataLen);
    DataCopy(vectorIndex0, srcM);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, maskReg);
    Xor(vectorIndex0, vectorIndex0, xorOffset, maskReg);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B64, maskReg);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Max(maxValue, histVector0, histVector1, patAllB16);
}
```

**要点**: (1) 三处 Int64 scatter 算子（实例 13/14/15）共用同一 Xor 哈希扰动 pattern，差异仅在调用上下文；(2) maskReg 由 UpdateMask<uint64_t>(dataLen) 生成，Xor 第 4 参传入，与 ShiftRight/Muls 共享同一 mask；(3) Xor 与 xorOffset 异或实现索引位扰动，配合 FNV 质数乘法完成哈希散列，是索引去重统计的预处理步骤。

### Xor 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| sort | And, CompareScalar, CreateMask, DataCopy, Duplicate | And+Compare(NE)+Select 构造符号位向量，Xor 翻转符号位，配合负零修正 | __aicore__ |
| sort | And, CompareScalar, CreateMask, DataCopy, Duplicate | 同上 fp32 版本，VEC_SCOPE 上下文，mask 随排序方向切换 | __VEC_SCOPE__ |
| top_k_v2 | And, CompareScalar, CreateMask, DataCopy, Duplicate | And+Compare(NE)+Select→Xor 翻转符号位→Store，定长块排序 | __VEC_SCOPE__ |
| top_k_v2 | And, CompareScalar, CreateMask, DataCopy, Duplicate | repeat 循环版，UpdateMask 动态 mask 处理变长输入 | __VEC_SCOPE__ |
| top_k_v2 | CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral | 无 And/Compare 前置，直接 Xor 与固定向量异或翻转（b32） | __VEC_SCOPE__ |
| top_k_v2 | CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral | 同左 b64 版本，predicateDefault 全有效 | __VEC_SCOPE__ |
| top_k_v2 | CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral | b8 版本，mask 传入 Xor 控制逐字节有效 | __VEC_SCOPE__ |
| bitwise_xor | DataCopy, LoadDist, MaskReg, RegTensor, StoreDist | 双源 LoadDist→Xor 按位异或→StoreDist，Xor 本义用法 | __aicore__ |
| sort | DataCopy, MaskReg, Not, PostLiteral, RegTensor | 最简 Twiddle，Xor 翻转符号位，降序配 Not | __aicore__ |
| bitwise_xor | DataCopy, LoadDist, MaskReg, RegTensor, StoreDist | 同实例 8 的 VEC_SCOPE 内联版本 | __VEC_SCOPE__ |
| scatter_nd_update | ShiftRight | ShiftRight 取维度→Xor(xorOffset) 哈希扰动→Muls(FNV)→Histograms（Int32） | __simd_vf__ |
| scatter_nd_common | ShiftRight | 同实例 11 结构，scatter 系列共用（Int32） | __simd_vf__ |
| scatter_nd_common | ShiftRight | Int64 版哈希扰动，maskReg 动态 mask | __simd_vf__ |
| inplace_index_add | ShiftRight | 同实例 13，inplace_index_add 算子（Int64） | __simd_vf__ |
| scatter_nd_add | ShiftRight | 同实例 13，scatter_nd_add 算子（Int64） | __simd_vf__ |
