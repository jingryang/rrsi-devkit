# GetSpr

**页面ID:** atlasascendc_api_07_00233  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00233.html

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

获取指定特殊寄存器的值，当前仅为预留接口。

#### 函数原型

```
template <SpecialPurposeReg spr>
__aicore__ inline int64_t GetSpr()
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| spr | 特殊寄存器，类型为SpecialPurposeReg枚举类，具体的取值请参考表2，当前暂不支持任何SpecialPurposeReg类型的取值。 |

**表2 **SpecialPurposeReg模板参数说明

| 取值 | 含义 |
| --- | --- |
| AR | 一个特殊的地址寄存器，通常配合SqueezeReg矢量计算API一起使用，SqueezeReg矢量计算API会存储有效元素的总字节数到AR寄存器。 |

#### 返回值说明

返回int64_t类型的特殊寄存器中的数值。

#### 约束说明

无

#### 调用示例

预留接口，无调用示例。


---
## 从 Ascend 950PR / arch35 算子源码提取的 GetSpr 实例

### 实例 1：broadcast_gradient_args::CalcReduceAxes

- **来源类型**: `__aicore__`
- **共现 API**: AR, Adds, Arange, Cast, ClearSpr, CompareScalar, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, GatherMask, GatherMaskMode, MaskPattern, MaskReg, Pack, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: reduce 轴计算循环结束后，读取 AR 寄存器累积的有效元素字节数，除以 sizeof(int32_t) 换算为有效元素个数，作为函数返回值。

（行 103-134）

```cpp
            for (uint16_t i = 0; i < vLoopT; i++) {
                maskCalc = Reg::UpdateMask<int32_t>(srg0);
                Reg::Adds(calc_index_reg, init_index_reg, i * vlInput, maskAll);
                Reg::DataCopy(in_reg, x + i * vlInput);
                Reg::CompareScalar<int32_t, CMPMODE::EQ>(maskCompare, in_reg, 1, maskCalc);
                Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(dst_reg, calc_index_reg,
                                                                                   maskCompare);
                Reg::DataCopyUnAlign<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(y, dst_reg, ureg);
            }
        }
        Reg::DataCopyUnAlignPost(y, ureg);
    }
    return ((Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t));
}

__aicore__ inline void CheckInput(__local_mem__ T* x1, __local_mem__ T* x2, __local_mem__ T* invalidFlag,
                                  __local_mem__ T* equalFlag, uint32_t calcLen)
{
    __VEC_SCOPE__
    {
        Reg::RegTensor<T> x1_reg, x2_reg, one_reg, zero_reg, eq_flag_reg, bool_reg1, bool_reg2, out_eq_reg,
            out_invalid_reg;
        Reg::MaskReg maskCompare0, maskCompare1, maskCompare2;
        Reg::MaskReg maskCalc;
        Reg::MaskReg maskMerge = Reg::CreateMask<T, Reg::MaskPattern::VL1>();
        Reg::MaskReg maskAll = Reg::CreateMask<T, Reg::MaskPattern::ALL>();
        Reg::Duplicate(one_reg, 1, maskAll);
        Reg::Duplicate(zero_reg, 0, maskAll);
        Reg::Duplicate(out_eq_reg, 0, maskAll);
        Reg::Duplicate(out_invalid_reg, 0, maskAll);
        for (uint16_t i = 0; i < vLoopT; i++) {
            maskCalc = Reg::UpdateMask<T>(calcLen);
```

**要点**:
1. GetSpr<AR>() 读取的是"有效元素总字节数"，需除以元素大小（sizeof(int32_t)）换算成元素个数。
2. AR 在 mask 比较 + GatherMask 循环中被累加，前序已 ClearSpr<AR>() 清零（共现 API 含 ClearSpr）。
3. 返回值直接用 GetSpr 结果换算，是"读取计算结果计数"的典型用法。

### 实例 2：scatter_nd_add::ComputeUniqueIdNum

- **来源类型**: `__aicore__`
- **共现 API**: AR, ClearSpr
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 先 ClearSpr<AR>() 清零，按 CAST_T 类型分发调用 ComputeUniqueIdNumInt* 计算唯一 ID，再用 GetSpr<AR>()/sizeof(int32_t) 读取有效元素数，减 1 得到唯一 ID 个数。

（行 406-430）

```cpp
{
    __local_mem__ CAST_T* indicesAddr = (__local_mem__ CAST_T*)indicesLocal[(UB_AGLIN_VALUE / sizeof(CAST_T))]
                                            .GetPhyAddr();
    __local_mem__ int32_t* uniqueIdCountsAddr = (__local_mem__ int32_t*)uniqueIdCountLocal.GetPhyAddr();

    int64_t vfLen = platform::GetVRegSize() / sizeof(CAST_T);
    uint16_t loopCnt = ops::CeilDiv(dataLen + 1, vfLen);
    uint32_t counter = dataLen + 1;
    __VEC_SCOPE__
    {
        AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();
        if constexpr (std::is_same<int64_t, CAST_T>::value) {
            ComputeUniqueIdNumInt64(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
        } else if constexpr (std::is_same<int32_t, CAST_T>::value) {
            ComputeUniqueIdNumInt32(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
        } else if constexpr (std::is_same<int16_t, CAST_T>::value) {
            ComputeUniqueIdNumInt16(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
        } else {
            ComputeUniqueIdNumUint8(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
        }
    }
    uint32_t uniqueIdNum = ((AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t)) - 1;
    return uniqueIdNum;
}
```

**要点**:
1. ClearSpr<AR>() 与 GetSpr<AR>() 成对使用：先清零、计算、再读取。
2. AR 存字节数，/sizeof(int32_t) 换算为 int32 元素个数。
3. 结果减 1 是因为计算过程含一个哨兵元素（counter=dataLen+1）。

### 实例 3：unsorted_segment_sum::ComputeUniqueIdNum

- **来源类型**: `__aicore__`
- **共现 API**: AR, ClearSpr
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: ClearSpr<AR>() 清零后按 IDX_T 类型分发 ComputeUniqueIdNumInt* 计算，GetSpr<AR>()/sizeof(int32_t) 取有效数；为 0 时返回 1，否则减 1。

（行 331-355）

```cpp
{
    __local_mem__ IDX_T* indicesAddr = (__local_mem__ IDX_T*)indicesLocal[(UB_AGLIN_VALUE_32 / sizeof(IDX_T))]
                                           .GetPhyAddr();
    __local_mem__ int32_t* uniqueIdCountsAddr = (__local_mem__ int32_t*)uniqueIdCountLocal.GetPhyAddr();

    constexpr int64_t vfLen = Ops::Base::GetVRegSize() / sizeof(IDX_T);
    uint16_t loopCnt = Ops::Base::CeilDiv(dataLen + 1, vfLen);
    __VEC_SCOPE__
    {
        AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();

        if constexpr (std::is_same<int64_t, IDX_T>::value) {
            ComputeUniqueIdNumInt64<IDX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
        } else if constexpr (std::is_same<int32_t, IDX_T>::value) {
            ComputeUniqueIdNumInt32<IDX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
        } else if constexpr (std::is_same<int16_t, IDX_T>::value) {
            ComputeUniqueIdNumInt16<IDX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
        } else { // uint8
            ComputeUniqueIdNumUint8<IDX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
        }
    }
    uint32_t uniqueIdNum = ((AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t));
    return uniqueIdNum == 0 ? 1 : (uniqueIdNum - 1);
}
```

**要点**:
1. 对结果做 0 值兜底（==0?1:uniqueIdNum-1），避免空输入返回负数/下溢。
2. ClearSpr+GetSpr 成对，AR 字节数 /sizeof(int32_t) 换算元素数。
3. 不同 IDX_T（int64/int32/int16/uint8）走不同分支但共用同一 AR 读取换算逻辑。

### 实例 4：embedding_dense_grad::ProcessIndices

- **来源类型**: `__aicore__`
- **共现 API**: AR
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 对排序去重后的索引调用 UniqueGetElm 写入 AR，再用 GetSpr<AR>()/sizeof(int32_t)-1 得到去重后的唯一索引数 arNum，传给 UniqueStat 做后续统计。

（行 212-221）

```cpp
static constexpr SortConfig sortConfig{SortType::RADIX_SORT, false};
AscendC::Sort<U, false, sortConfig>(sortedDstLocal, sortedIndexLocal, indicesLocal, sharedTmpBuffer,
                                    static_cast<uint32_t>(indicesFactorReal));

Duplicate(noDupRes, 0, indicesFactorReal);
UniqueGetElm(sortedIndice, noDupRes, indicesFactorReal, arNum);
arNum = ((AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t)) - 1;
UniqueStat(noDupRes, arNum);

inQueueIndice_.FreeTensor(indicesLocal);
```

**要点**:
1. GetSpr 紧跟 UniqueGetElm 之后，读取去重过程写入 AR 的有效字节数。
2. arNum 作为"算子间计数传递"被 UniqueStat 消费，体现 AR 寄存器跨 API 传递计数。
3. 结果 -1 去掉哨兵元素。

### 实例 5：scatter_nd_update::ComputeUniqueIdNum

- **来源类型**: `__aicore__`
- **共现 API**: AR
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 调用 ComputeUniqueIdNumVf 计算后，GetSpr<AR>()/sizeof(int32_t) 取元素数；大于 0 时减 1 返回，否则返回 0。

（行 228-240）

```cpp
__local_mem__ int32_t* uniqueIdCountsAddr = (__local_mem__ int32_t*)uniqueIdCountLocal.GetPhyAddr();

int64_t vfLen = Ops::Base::GetVRegSize() / sizeof(OFFSET_T);
uint16_t loopCnt = Ops::Base::CeilDiv(dataLen + 1, vfLen);
uint32_t counter = dataLen + 1;
ComputeUniqueIdNumVf<OFFSET_T>((__ubuf__ OFFSET_T*)indicesAddr, (__ubuf__ int32_t*)uniqueIdCountsAddr, vfLen,
                               loopCnt, counter);
uint32_t elementCount = AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>() / sizeof(int32_t);
if (elementCount > 0) {
    return static_cast<uint32_t>(elementCount - 1);
} else {
    return 0;
}
```

**要点**:
1. 对 elementCount>0 做判空保护，避免空输入减 1 下溢。
2. AR 字节数 /sizeof(int32_t) 换算为 int32 元素个数。
3. 本例未显式 ClearSpr，依赖 ComputeUniqueIdNumVf 内部对 AR 的初始化/累加。

### 实例 6：scatter_nd_common::ComputeUniqueIdNum

- **来源类型**: `__aicore__`
- **共现 API**: AR
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 调用 ComputeUniqueIdNumVF 计算后，GetSpr<AR>()/sizeof(int32_t)-1 得到唯一 ID 个数返回。

（行 457-470）

```cpp
{
    __local_mem__ CAST_T* indicesAddr = (__local_mem__ CAST_T*)indicesLocal[(UB_AGLIN_VALUE / sizeof(CAST_T))]
                                            .GetPhyAddr();
    __local_mem__ int32_t* uniqueIdCountsAddr = (__local_mem__ int32_t*)uniqueIdCountLocal.GetPhyAddr();

    int64_t vfLen = platform::GetVRegSize() / sizeof(CAST_T);
    uint16_t loopCnt = ops::CeilDiv(dataLen + 1, vfLen);

    ComputeUniqueIdNumVF(indicesAddr, uniqueIdCountsAddr, dataLen, loopCnt);

    uint32_t uniqueIdNum = ((AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t)) - 1;
    return uniqueIdNum;
}
```

**要点**:
1. ComputeUniqueIdNumVF 在内部累加 AR，GetSpr 读取后换算。
2. 结果 -1 去哨兵元素。
3. 与实例 7 结构一致，属"通用唯一计数"标准模式。

### 实例 7：inplace_index_add::ComputeUniqueIdNum

- **来源类型**: `__aicore__`
- **共现 API**: AR
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 调用 ComputeUniqueIdNumVf 计算后，GetSpr<AR>()/sizeof(int32_t)-1 取唯一 ID 数返回。

（行 477-490）

```cpp
{
    __local_mem__ CAST_T* indicesAddr = (__local_mem__ CAST_T*)indicesLocal[(UB_AGLIN_VALUE / sizeof(CAST_T))]
                                            .GetPhyAddr();
    __local_mem__ int32_t* uniqueIdCountsAddr = (__local_mem__ int32_t*)uniqueIdCountLocal.GetPhyAddr();

    constexpr int64_t vfLen = platform::GetVRegSize() / sizeof(CAST_T);
    uint16_t loopCnt = ops::CeilDiv(dataLen + 1, vfLen);

    ComputeUniqueIdNumVf(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);

    uint32_t uniqueIdNum = ((AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t)) - 1;
    return uniqueIdNum;
}
```

**要点**:
1. 与实例 6 同模式：Vf 计算 + GetSpr 读取换算 -1。
2. vfLen 由 GetVRegSize()/sizeof(CAST_T) 推导，决定循环次数。
3. AR 在 ComputeUniqueIdNumVf 内部被累加，外部直接读取。

### 实例 8：scatter_nd_add::ComputeUniqueIdNumDeter

- **来源类型**: `__aicore__`
- **共现 API**: AR
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 确定性变体 ComputeUniqueIdNumDeterVf 计算后，GetSpr<AR>()/sizeof(int32_t)-1 取唯一 ID 数返回。

（行 433-445）

```cpp
{
    __local_mem__ U* indicesAddr = (__local_mem__ U*)indicesLocal[shiftOffset_].GetPhyAddr();
    __local_mem__ int32_t* uniqueIdCountsAddr = (__local_mem__ int32_t*)uniqueIdCountLocal.GetPhyAddr();

    int64_t vfLen = platform::GetVRegSize() / sizeof(U);
    uint16_t loopCnt = ops::CeilDiv(dataLen + 1, vfLen);
    uint32_t counter = dataLen + 1;
    ComputeUniqueIdNumDeterVf<U>((__ubuf__ U*)indicesAddr, (__ubuf__ int32_t*)uniqueIdCountsAddr, vfLen, loopCnt,
                                 counter);
    uint32_t uniqueIdNum = ((AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t)) - 1;
    return uniqueIdNum;
}
```

**要点**:
1. "Deter" 变体走 ComputeUniqueIdNumDeterVf，但 AR 读取换算方式与普通变体一致。
2. 与实例 2 同算子不同函数（deterministic vs 普通），共用 AR 计数协议。
3. counter=dataLen+1 含哨兵，对应结果 -1。

### 实例 9：scatter_add::ComputeUniqueIdNum

- **来源类型**: `__aicore__`
- **共现 API**: AR
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 调用 ComputeUniqueIdNumVf 计算后，GetSpr<AR>()/sizeof(int32_t)-1 取唯一 ID 数返回。

（行 369-381）

```cpp
{
    __local_mem__ IDX_T* indicesAddr = (__local_mem__ IDX_T*)indicesLocal[(UB_AGLIN_VALUE / sizeof(IDX_T))]
                                           .GetPhyAddr();
    __local_mem__ int32_t* uniqueIdCountsAddr = (__local_mem__ int32_t*)uniqueIdCountLocal.GetPhyAddr();

    constexpr int64_t vfLen = platform::GetVRegSize() / sizeof(IDX_T);
    uint16_t loopCnt = ops::CeilDiv(dataLen + 1, vfLen);

    ComputeUniqueIdNumVf(indicesAddr, uniqueIdCountsAddr, dataLen, loopCnt);
    uint32_t uniqueIdNum = ((AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t)) - 1;
    return uniqueIdNum;
}
```

**要点**:
1. 通用唯一计数模式：Vf 计算 + GetSpr 换算 -1。
2. IDX_T 类型决定 vfLen 与循环次数。
3. AR 字节数 /sizeof(int32_t) 换算为 int32 元素个数。

### 实例 10：inplace_index_fill::ComputeUniqueIdNum

- **来源类型**: `__aicore__`
- **共现 API**: AR
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 调用 ComputeUniqueIdNumVf<INDEX_TYPE> 计算后，GetSpr<AR>()/sizeof(int32_t)-1 取唯一索引数返回。

（行 129-141）

```cpp
{
    __local_mem__ INDEX_TYPE*
        sortedInputAddr = (__local_mem__ INDEX_TYPE*)sortedInput[(UB_AGLIN_VALUE / sizeof(INDEX_TYPE))].GetPhyAddr();
    __local_mem__ int32_t* uniqueIndicesAddr = (__local_mem__ int32_t*)uniqueIndicesOut.GetPhyAddr();

    constexpr int64_t vfLen = platform::GetVRegSize() / sizeof(INDEX_TYPE);
    uint16_t loopCnt = ops::CeilDiv(dataLen + 1, vfLen);
    ComputeUniqueIdNumVf<INDEX_TYPE>((__ubuf__ INDEX_TYPE*)sortedInputAddr, (__ubuf__ int32_t*)uniqueIndicesAddr,
                                     loopCnt, dataLen);
    uint32_t uniqueIdNum = ((AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t)) - 1;
    return uniqueIdNum;
}
```

**要点**:
1. 模板显式指定 INDEX_TYPE，与 GetSpr 的 int32 换算相互独立。
2. 通用唯一计数模式。
3. 结果 -1 去哨兵元素。

### 实例 11：unsorted_segment_common::UniqueGetElm

- **来源类型**: `__aicore__`
- **共现 API**: AR
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 调用 UniqueGetElmVf 计算后，GetSpr<AR>()/sizeof(int32_t) 取有效数；大于 0 时减 1，否则返回 0。

（行 425-435）

```cpp
{
    __ubuf__ IDX_T* indicesAddr = (__ubuf__ IDX_T*)sortedIndice[(ONE_BLOCK_SIZE / sizeof(IDX_T))].GetPhyAddr();
    __ubuf__ int32_t* uniqueIdCountsAddr = (__ubuf__ int32_t*)noDupRes.GetPhyAddr();

    constexpr int64_t vfLen = platform::GetVRegSize() / sizeof(IDX_T);
    uint16_t loopCnt = ops::CeilDiv(dataLen + 1, vfLen);
    UniqueGetElmVf<IDX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    int64_t uniqueIdNum = ((AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t));
    uniqueIdNum = uniqueIdNum > 0 ? uniqueIdNum - 1 : 0;
    return uniqueIdNum;
}
```

**要点**:
1. 函数名 UniqueGetElm（非 ComputeUniqueIdNum），但 AR 读取换算方式一致。
2. 做 >0 判空保护，避免减 1 下溢。
3. 返回 int64_t，与其它实例的 uint32_t 返回类型不同。

### 实例 12：index_fill::ComputeUniqueIdNum

- **来源类型**: `__aicore__`
- **共现 API**: AR
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 调用 ComputeUniqueIdNumVf<INDEX_TYPE> 计算后，GetSpr<AR>()/sizeof(int32_t)-1 取唯一索引数返回。

（行 191-200）

```cpp
{
    constexpr int64_t vfLen = platform::GetVRegSize() / sizeof(INDEX_TYPE);
    uint16_t loopCnt = ops::CeilDiv(dataLen + 1, vfLen);
    ComputeUniqueIdNumVf<INDEX_TYPE>(
        (__ubuf__ INDEX_TYPE*)sortedInput[(UB_AGLIN_VALUE / sizeof(INDEX_TYPE))].GetPhyAddr(),
        (__ubuf__ int32_t*)uniqueIndicesOut.GetPhyAddr(), loopCnt, dataLen);
    uint32_t uniqueIdNum = ((AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t)) - 1;
    return uniqueIdNum;
}
```

**要点**:
1. 通用唯一计数模式，INDEX_TYPE 模板参数化。
2. AR 字节数 /sizeof(int32_t) 换算元素数后 -1 去哨兵。
3. 与实例 10 结构一致。

### 实例 13：scatter_update::ComputeUniqueIdNum

- **来源类型**: `__aicore__`
- **共现 API**: AR
- **GetSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 调用 ComputeUniqueIdNumVf<INX_T> 计算后，GetSpr<AR>()/sizeof(int32_t)-1 取唯一 ID 数返回。

（行 212-220）

```cpp
{
    int64_t vfLen = platform::GetVRegSize() / sizeof(INX_T);
    uint16_t loopCnt = ops::CeilDiv(dataLen + 1, vfLen);
    ComputeUniqueIdNumVf<INX_T>((__ubuf__ INX_T*)indicesLocal[(UB_AGLIN_VALUE / sizeof(INX_T))].GetPhyAddr(),
                                (__ubuf__ int32_t*)uniqueIdCountLocal.GetPhyAddr(), loopCnt, dataLen);
    uint32_t uniqueIdNum = ((AscendC::Reg::GetSpr<AscendC::SpecialPurposeReg::AR>()) / sizeof(int32_t)) - 1;
    return uniqueIdNum;
}
```

**要点**:
1. 通用唯一计数模式，INX_T 模板参数化。
2. AR 字节数 /sizeof(int32_t) 换算元素数后 -1 去哨兵。
3. 函数体最精简，体现 GetSpr 作为"计数读取"的标准用法。

### GetSpr 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| broadcast_gradient_args | AR, Adds, Arange, Cast, ClearSpr | reduce 循环后 GetSpr<AR>()/sizeof(int32_t) 取有效元素数返回 | __aicore__ |
| scatter_nd_add | AR, ClearSpr | ClearSpr<AR>() 清零→按 CAST_T 分发 ComputeUniqueIdNumInt*→GetSpr<AR>()/4-1 取唯一 ID 数 | __aicore__ |
| unsorted_segment_sum | AR, ClearSpr | ClearSpr<AR>()→按 IDX_T 分发 ComputeUniqueIdNumInt*→GetSpr<AR>()/4（0 则返 1 否则 -1） | __aicore__ |
| embedding_dense_grad | AR | Sort+UniqueGetElm 后 GetSpr<AR>()/4-1 取去重索引数 | __aicore__ |
| scatter_nd_update | AR | ComputeUniqueIdNumVf→GetSpr<AR>()/4（>0 则 -1 否则 0） | __aicore__ |
| scatter_nd_common | AR | ComputeUniqueIdNumVF→GetSpr<AR>()/4-1 取唯一 ID 数 | __aicore__ |
| inplace_index_add | AR | ComputeUniqueIdNumVf→GetSpr<AR>()/4-1 取唯一 ID 数 | __aicore__ |
| scatter_nd_add | AR | ComputeUniqueIdNumDeterVf→GetSpr<AR>()/4-1 取唯一 ID 数（确定性变体） | __aicore__ |
| scatter_add | AR | ComputeUniqueIdNumVf→GetSpr<AR>()/4-1 取唯一 ID 数 | __aicore__ |
| inplace_index_fill | AR | ComputeUniqueIdNumVf<INDEX_TYPE>→GetSpr<AR>()/4-1 取唯一索引数 | __aicore__ |
| unsorted_segment_common | AR | UniqueGetElmVf→GetSpr<AR>()/4（>0 则 -1 否则 0） | __aicore__ |
| index_fill | AR | ComputeUniqueIdNumVf<INDEX_TYPE>→GetSpr<AR>()/4-1 取唯一索引数 | __aicore__ |
| scatter_update | AR | ComputeUniqueIdNumVf<INX_T>→GetSpr<AR>()/4-1 取唯一 ID 数 | __aicore__ |
