# Not

**页面ID:** atlasascendc_api_07_0353  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0353.html

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

对输入srcReg中的每个有效数据按位取反，将结果写入dstReg。

- 对MaskReg操作：

对输入src中的每个有效位（bit）取反，将结果写入dst。

#### 函数原型

- 对RegTensor进行操作

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Not(U& dstReg, U& srcReg, MaskReg& mask)
```

- 对MaskReg进行操作

```
__simd_callee__ inline void Not(MaskReg& dst, MaskReg& src, MaskReg& mask)
```

#### 参数说明

- 对RegTensor进行操作

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/int32_t/uint32_t/int64_t/uint64_t/half/float |
| mode | 选择MERGING模式或ZEROING模式。   - ZEROING，mask未筛选的元素在dst中置零。  - MERGING，当前不支持。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

- 对MaskReg进行操作

**表3 **参数说明

| 参数名 | 描述 |
| --- | --- |
| dst | 目的操作数。 |
| src | 源操作数。 |
| mask | 指示在计算过程中哪些bit有效。 |

#### 约束说明

无

#### 调用示例

- 对RegTensor进行操作

```
template <typename T>
__simd_vf__ inline void NotVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, 
 uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Not(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 对MaskReg进行操作

```
template <typename T>
__simd_vf__ inline void NotVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg src = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALLF>();
    AscendC::Reg::MaskReg dst;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Not(dst, src, mask);
        AscendC::Reg::Adds(srcReg, srcReg, 0, dst);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, srcReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Not 实例

### 实例 1：sort::TwiddleInFp16

- **来源类型**: `__aicore__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, Select, UpdateMask, Xor
- **Not 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义**: radix sort 降序分支——当 `isDescend == 1` 时，对经 Xor 处理后的 fp16 比较键 resultReg 用 Not 按位取反，再搬出到目的地址，实现降序排序的键翻转。

（行 165-172）

```cpp
if constexpr (isDescend == 0) {
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        uXValuePtr, resultReg, VF_LEN_B16, xorMask);
} else {
    Reg::Not(vnotReg, resultReg, xorMask);
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        uXValuePtr, vnotReg, VF_LEN_B16, xorMask);
}
```

**要点**:
- `Not(vnotReg, resultReg, xorMask)`：dst=vnotReg、src=resultReg、mask=xorMask，对 mask 选中元素按位取反。
- 仅在 `isDescend == 1`（降序）分支调用；升序分支直接搬出 resultReg，不经 Not。
- xorMask 由 `UpdateMask<T>` 生成，控制本 repeat 内有效元素数（VF_LEN_B16）。

### 实例 2：sort::TwiddleInFp32

- **来源类型**: `__aicore__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, Select, UpdateMask, Xor
- **Not 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: radix sort fp32 降序分支——降序时对 32 位比较键 resultReg 用 Not 取反，mask 使用 maskB32，翻转后搬出。

（行 221-228）

```cpp
if constexpr (isDescend == 0) {
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        uXValuePtr, resultReg, VF_LEN_B32, xorMask);
} else {
    Reg::Not(vnotReg, resultReg, maskB32);
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        uXValuePtr, vnotReg, VF_LEN_B32, xorMask);
}
```

**要点**:
- `Not(vnotReg, resultReg, maskB32)`：fp32 路径，mask 变量名为 maskB32（与 fp16 的 xorMask 同为 MaskReg）。
- 与实例 1 同构，仅数据位宽（B32 vs B16）与 mask 命名不同。
- 倒序键取反是 radix sort 降序实现的惯用手法。

### 实例 3：sort::TwiddleInFp16

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, Select, UpdateMask, Xor
- **Not 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义**: 同实例 1 的代码，但提取自 `__VEC_SCOPE__`（矢量函数作用域），展示同一 TwiddleInFp16 在不同编译作用域下的 Not 用法。

（行 165-172）

```cpp
if constexpr (isDescend == 0) {
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        uXValuePtr, resultReg, VF_LEN_B16, xorMask);
} else {
    Reg::Not(vnotReg, resultReg, xorMask);
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        uXValuePtr, vnotReg, VF_LEN_B16, xorMask);
}
```

**要点**:
- 代码与实例 1 逐字一致，差异在来源作用域 `__VEC_SCOPE__`（而非 `__aicore__`）。
- 说明 Not 在 VF 作用域内同样可用，调用形式不受作用域影响。
- 倒序分支语义同实例 1。

### 实例 4：sort::TwiddleInFp32

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, Select, UpdateMask, Xor
- **Not 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 同实例 2 的代码，提取自 `__VEC_SCOPE__` 作用域，fp32 降序分支取反。

（行 221-228）

```cpp
if constexpr (isDescend == 0) {
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        uXValuePtr, resultReg, VF_LEN_B32, xorMask);
} else {
    Reg::Not(vnotReg, resultReg, maskB32);
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        uXValuePtr, vnotReg, VF_LEN_B32, xorMask);
}
```

**要点**:
- 与实例 2 代码一致，来源作用域为 `__VEC_SCOPE__`。
- mask 仍为 maskB32，位宽 B32。
- 验证 Not 在不同作用域的调用一致性。

### 实例 5：sort::ReverseInputData

- **来源类型**: `__aicore__`
- **共现 API**: CreateMask, DataCopy, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Not 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 输入数据翻转——将加载到的 inputVectorOne 用 Not 配合默认谓词 predicateDefaultB8 取反得到 vnotVectorZero，再以 vnotMask 搬出到翻转目的地址。

（行 246-252）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    Reg::MaskReg vnotMask = Reg::UpdateMask<UT>(inputElementNum);
    Reg::DataCopy<UT, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtr, vfLen);
    Reg::Not(vnotVectorZero, inputVectorOne, predicateDefaultB8);
    Reg::DataCopy<UT, Reg::PostLiteral::POST_MODE_UPDATE>(
        reverseInputXPtr, vnotVectorZero, vfLen, vnotMask);
}
```

**要点**:
- `Not(vnotVectorZero, inputVectorOne, predicateDefaultB8)`：第三参数为默认全有效谓词 predicateDefaultB8，对所有元素取反。
- 搬出时用 `UpdateMask<UT>(inputElementNum)` 生成的 vnotMask 控制尾部有效元素。
- 实现输入按位翻转（reverse）的核心一步。

### 实例 6：sort::Twiddle

- **来源类型**: `__aicore__`
- **共现 API**: DataCopy, MaskReg, PostLiteral, RegTensor, UpdateMask, Xor
- **Not 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义**: radix sort Twiddle——先 Xor 再在降序分支 Not 取反，组合 Xor + Not 实现比较键翻转。

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

**要点**:
- `Not(vnotReg, xorResult, xorMask)`：对 Xor 结果 xorResult 取反，mask=xorMask。
- 与 Xor（`Xor(xorResult, inputReg, xorReg, xorMask)`）形成"异或再取反"序列。
- `isDescend == 1` 分支专属；升序直接搬 xorResult。

### 实例 7：top_k_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Not 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义**: top_k radix 排序中的 reverse op——对加载的 inputVectorOne 用 Not 配合 vnotMask 取反后搬出，实现键翻转。

（行 458-468）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg vnotMask = Reg::UpdateMask<uint16_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        inputVectorOne, inputXValuePtrCopy, ONE_TIMES_B16_NUM);
    // reverse op
    Reg::Not(vnotVectorZero, inputVectorOne, vnotMask);
    // sts
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        reverseInputXPtr, vnotVectorZero, ONE_TIMES_B16_NUM, vnotMask);
}
```

**要点**:
- `Not(vnotVectorZero, inputVectorOne, vnotMask)`：vnotMask=`UpdateMask<uint16_t>(inputElementNum)`，按实际元素数取反。
- 注释标明 `// reverse op`，是 top_k 倒序的显式步骤。
- 位宽 B16（uint16_t）。

### 实例 8：top_k_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Not 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: top_k b64 路径 reverse op——用默认谓词 predicateDefaultB64 对 inputVectorOne 取反后搬出。

（行 311-319）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    Reg::MaskReg vnotMask = Reg::UpdateMask<uint64_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtrCopy, ONE_TIMES_B64_NUM);
    // ~
    Reg::Not(vnotVectorZero, inputVectorOne, predicateDefaultB64);
    // sts
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(reverseInputXPtr, vnotVectorZero, ONE_TIMES_B64_NUM, vnotMask);
}
```

**要点**:
- `Not(vnotVectorZero, inputVectorOne, predicateDefaultB64)`：第三参数为默认谓词，全元素取反。
- 搬出 mask 用 `UpdateMask<uint64_t>` 的 vnotMask。
- 位宽 B64（uint64_t）。

### 实例 9：top_k_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Not 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: top_k b8 路径 reverse op，用默认谓词 predicateDefaultB8 对 inputVectorOne 取反后搬出。

（行 306-314）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg vnotMask = Reg::UpdateMask<uint8_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtrCopy, ONE_TIMES_B8_NUM);
    // ~
    Reg::Not(vnotVectorZero, inputVectorOne, predicateDefaultB8);
    // sts
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(reverseInputXPtr, vnotVectorZero, ONE_TIMES_B8_NUM, vnotMask);
}
```

**要点**:
- `Not(vnotVectorZero, inputVectorOne, predicateDefaultB8)`：B8 默认谓词全取反。
- 搬出用 `UpdateMask<uint8_t>` 的 vnotMask 控制尾元素。
- 位宽 B8（uint8_t）。

### 实例 10：top_k_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Not 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: top_k b32 路径 reverse op，用默认谓词 predicateDefaultB32 对 inputVectorOne 取反后搬出。

（行 425-433）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg vnotMask = Reg::UpdateMask<uint32_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtrCopy, ONE_TIMES_B32_NUM);
    // ~
    Reg::Not(vnotVectorZero, inputVectorOne, predicateDefaultB32);
    // sts
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(reverseInputXPtr, vnotVectorZero, ONE_TIMES_B32_NUM, vnotMask);
}
```

**要点**:
- `Not(vnotVectorZero, inputVectorOne, predicateDefaultB32)`：B32 默认谓词全取反。
- 搬出用 `UpdateMask<uint32_t>` 的 vnotMask。
- 位宽 B32（uint32_t）。

### 实例 11：sort::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Not 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 同实例 5 代码（ReverseInputData），提取自 `__VEC_SCOPE__` 作用域，输入翻转取反。

（行 246-252）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    Reg::MaskReg vnotMask = Reg::UpdateMask<UT>(inputElementNum);
    Reg::DataCopy<UT, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtr, vfLen);
    Reg::Not(vnotVectorZero, inputVectorOne, predicateDefaultB8);
    Reg::DataCopy<UT, Reg::PostLiteral::POST_MODE_UPDATE>(
        reverseInputXPtr, vnotVectorZero, vfLen, vnotMask);
}
```

**要点**:
- 代码与实例 5 一致，来源作用域 `__VEC_SCOPE__`。
- 用 predicateDefaultB8 全取反，搬出用 vnotMask 控制有效元素。
- 体现 Not 在不同作用域的相同调用模式。

### Not 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| sort | And, CompareScalar, CreateMask, DataCopy, Duplicate | radix sort 降序分支：Xor 后 Not 取反 fp16 比较键 | __aicore__ |
| sort | And, CompareScalar, CreateMask, DataCopy, Duplicate | radix sort 降序分支：Not 取反 fp32 比较键 | __aicore__ |
| sort | And, CompareScalar, CreateMask, DataCopy, Duplicate | 同上行，VF 作用域内 fp16 倒序取反 | __VEC_SCOPE__ |
| sort | And, CompareScalar, CreateMask, DataCopy, Duplicate | 同上行，VF 作用域内 fp32 倒序取反 | __VEC_SCOPE__ |
| sort | CreateMask, DataCopy, MaskReg, PostLiteral | 输入翻转：默认谓词全取反后搬出 | __aicore__ |
| sort | DataCopy, MaskReg, PostLiteral, RegTensor | Twiddle：Xor 后降序分支 Not 取反 | __aicore__ |
| top_k_v2 | CreateMask, DataCopy, MaskReg, PostLiteral | top_k b16 reverse：UpdateMask 按元素数取反 | __VEC_SCOPE__ |
| top_k_v2 | CreateMask, DataCopy, MaskReg, PostLiteral | top_k b64 reverse：默认谓词全取反 | __VEC_SCOPE__ |
| top_k_v2 | CreateMask, DataCopy, MaskReg, PostLiteral | top_k b8 reverse：默认谓词全取反 | __VEC_SCOPE__ |
| top_k_v2 | CreateMask, DataCopy, MaskReg, PostLiteral | top_k b32 reverse：默认谓词全取反 | __VEC_SCOPE__ |
| sort | CreateMask, DataCopy, MaskReg, PostLiteral | 同实例 5，VF 作用域内输入翻转 | __VEC_SCOPE__ |
