# ShiftLeft

**页面ID:** atlasascendc_api_07_0374  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0374.html

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

根据mask对输入数据srcReg0，按照srcReg1对应元素进行左移操作，将结果写入dstReg。

#### 函数原型

```
template <typename T = DefaultType, typename U = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S, typename V>
__simd_callee__ inline void ShiftLeft(S& dstReg, S& srcReg0, V& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 源操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/uint64_t/int64_t |
| U | 左移参数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/int16_t/int32_t/int64_t 源操作数和目的操作数的数据类型约束参考表3 源操作数和目的操作数的数据类型约束。 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零。- MERGING，当前不支持。 |
| S | srcReg0/dstReg的RegTensor类型， 例如RegTensor<uint32_t>，由编译器自动推导，用户不需要填写。 |
| V | srcReg1的RegTensor类型， 例如RegTensor<int32_t>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 不支持设置为负数。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

**表3 **源操作数和目的操作数的数据类型约束

| srcReg0/dstReg数据类型 | srcReg1数据类型 |
| --- | --- |
| uint8_t | int8_t |
| uint16_t | int16_t |
| uint32_t | int32_t |
| uint64_t | int64_t |
| int8_t | int8_t |
| int16_t | int16_t |
| int32_t | int32_t |
| int64_t | int64_t |

#### 约束说明

- 对于逻辑位移（无符号数据类型），如果位移量大于数据类型位宽，则输出为0。
- 对于算术位移（有符号数据类型），如果srcReg0小于0，srcReg1小于0，并且位移量大于数据类型位宽，则输出-1；如果srcReg0大于0，并且位移量大于数据类型位宽，则输出0。

#### 调用示例

```
template<typename T, typename U>
__simd_vf__ inline void ShiftLeftVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ U* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<U> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);       
        AscendC::Reg::ShiftLeft(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 ShiftLeft 实例

### 实例 1：pow::ComputeCopy

- **来源类型**: `__aicore__`
- **共现 API**: (无)
- **ShiftLeft 调用次数**: 3
- **参数模式**: `T0_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: uint32_t, int32_t）
- **语义（待补充）**: pow 算子的 ComputeCopy 按 `sizeof(T1)` 分发：把 src/dst Tensor 经 `ReinterpretCast` 转为 uint32_t 或 uint16_t，以标量左移量 `scalarValue(=0)` 和元素数 `dataLength` 调用 ShiftLeft，借"左移 0 位"完成跨位宽数据的等长搬运。

（行 178-192）

```cpp
{
    if constexpr (sizeof(T1) == sizeof(int32_t)) {
        uint32_t scalarValue = 0;
        ShiftLeft(dstTensor.template ReinterpretCast<uint32_t>(), srcTensor.template ReinterpretCast<uint32_t>(),
                  scalarValue, static_cast<int32_t>(dataLength));
    } else if constexpr (sizeof(T1) == sizeof(int16_t)) {
        uint16_t scalarValue = 0;
        ShiftLeft(dstTensor.template ReinterpretCast<uint16_t>(), srcTensor.template ReinterpretCast<uint16_t>(),
                  scalarValue, static_cast<int32_t>(dataLength));
    } else {
        uint16_t scalarValue = 0;
        ShiftLeft(dstTensor.template ReinterpretCast<uint16_t>(), srcTensor.template ReinterpretCast<uint16_t>(),
                  scalarValue, static_cast<int32_t>((dataLength + 1) / B8_TO_B16));  // 将数据长度B8转换为B16长度
    }
}
```

**要点**:
- 此处 ShiftLeft 以"左移 0 位"作为无副作用搬运手段，配合 `ReinterpretCast` 实现整型数据在 32 位 / 16 位位宽间的等长拷贝。
- 第四个实参为元素个数 `dataLength`（非 mask），对应 Tensor 级 ShiftLeft 的高层调用形式，与 API 文档中 Reg 级 `ShiftLeft(dstReg, srcReg0, srcReg1, mask)` 签名不同。
- 通过 `if constexpr (sizeof(T1) == ...)` 选择 uint32_t / uint16_t 路径，保证搬运粒度与数据位宽匹配；16 位分支用 `(dataLength + 1) / B8_TO_B16` 做 B8→B16 长度换算。

### 实例 2：pow::ComputeCopy

- **来源类型**: `__aicore__`
- **共现 API**: (无)
- **ShiftLeft 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: uint32_t, int32_t）
- **语义（待补充）**: pow 算子标量浮点分支的 ComputeCopy：对 `sizeof(T1)==sizeof(float)` 走 uint32_t 路径、其余走 uint16_t 路径，均以 `scalarValue=0`、`static_cast<int32_t>(dataLength)` 调用 ShiftLeft，实现 float 与 16 位数据间的无损搬运。

（行 288-298）

```cpp
{
    if constexpr (sizeof(T1) == sizeof(float)) {
        uint32_t scalarValue = 0;
        ShiftLeft(dstTensor.template ReinterpretCast<uint32_t>(), srcTensor.template ReinterpretCast<uint32_t>(),
                  scalarValue, static_cast<int32_t>(dataLength));
    } else {
        uint16_t scalarValue = 0;
        ShiftLeft(dstTensor.template ReinterpretCast<uint16_t>(), srcTensor.template ReinterpretCast<uint16_t>(),
                  scalarValue, static_cast<int32_t>(dataLength));
    }
}
```

**要点**:
- 与实例 1 同属 ComputeCopy 的类型分发分支，本分支覆盖 `float`(32 位) 与其余(16 位) 两种位宽路径。
- `scalarValue=0` 表示左移 0 位，结果等于源数据，用于纯搬运 / 类型重解释场景，不改变数值内容。
- 使用 `static_cast<int32_t>(dataLength)` 将元素数显式转为移位参数类型，与实例 1 的 uint16_t B8→B16 换算形成对照。

### ShiftLeft 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| pow |  | 按 `sizeof(T1)` 分发 + `ReinterpretCast` + 左移 0 位搬运（uint32_t / uint16_t 路径，含 B8→B16 换算） | __aicore__ |
| pow |  | 按 `sizeof(T1)` 分发 + `ReinterpretCast` + 左移 0 位搬运（float / 16 位 路径） | __aicore__ |

