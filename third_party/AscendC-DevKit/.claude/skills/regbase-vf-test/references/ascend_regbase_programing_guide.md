# Ascend RegBase 编程指导

## 1. 概述

RegBase 是 AscendC 向量计算 API 的底层寄存器级实现。通过直接编写 RegBase 代码，开发者可以获得对硬件指令的精细控制，实现更高性能的向量计算。本指导总结 RegBase 编程的核心特点、规范与最佳实践。

---

## 2. 硬件基础

### 2.1 Vector 计算数据流

```
Vector 计算数据流：GM → UB → Reg → Vector → Reg → UB → GM
```

- **Scalar**: 核内调度单元，负责指令发射、循环控制
- **Vector**: 矢量计算单元，执行 SIMD 指令，数据来自 UB, 内部使用 Reg 优化访存。
- **Unified Buffer (UB)**: 矢量计算输入输出存储区

### 2.2 Vector Function (VF)

VF 是 RegBase 实现高性能矢量计算的核心载体，运行在 AIV 上。编译器将整个 VF 函数体视为原子调度单元，进行指令融合和流水线优化。

---

## 3. 三层函数调用链

RegBase 编程采用严格的三层调用链结构，每层对应不同的执行层级和职责：

```
__aicore__  ──>  __simd_vf__  ──>  __simd_callee__
 (调度层)         (融合循环层)       (寄存器指令层)
```

### 3.1 `__aicore__` — AI Core 调度层

- **职责**：接收 `LocalTensor`，提取 `__ubuf__` 物理地址，进行高层分发
- **特点**：是外部代码调用的入口，处理数据类型选择和路径分发，可合入其他 `__aicore__` 层
- **示例**：
  ```cpp
  template <typename T>
  __aicore__ inline void MulImpl(const AscendC::LocalTensor<T> &dst,
      const AscendC::LocalTensor<T> &src0, const AscendC::LocalTensor<T> &src1,
      const int32_t calCount)
  {
      __ubuf__ T *dstUb = (__ubuf__ T *)dst.GetPhyAddr();
      __ubuf__ T *src0Ub = (__ubuf__ T *)src0.GetPhyAddr();
      __ubuf__ T *src1Ub = (__ubuf__ T *)src1.GetPhyAddr();
      MulRegImpl<T>(dstUb, src0Ub, src1Ub, calCount);
  }
  ```

### 3.2 `__simd_vf__` — SIMD 向量融合层

- **职责**：包含 Load → Compute → Store 的循环模板，按寄存器宽度分块处理数据
- **特点**：编译器将整个函数体视为原子调度单元，进行指令融合和流水线优化
- **关键约束**：见第 8 节 Hardware Loop 规范
- **示例**：
  ```cpp
  template <typename T>
  __simd_vf__ inline void MulRegImpl(__ubuf__ T *dst, __ubuf__ T *src0, __ubuf__ T *src1,
      const int32_t calCount)
  {
      AscendC::Reg::RegTensor<T> src0Reg, src1Reg, dstReg;
      uint32_t sreg = static_cast<uint32_t>(calCount);
      AscendC::Reg::MaskReg mask;
      constexpr uint32_t REPEAT_STRIDE_B32 = 64;
      uint16_t repeatTime = static_cast<uint16_t>(
          (static_cast<uint32_t>(calCount) + REPEAT_STRIDE_B32 - 1) / REPEAT_STRIDE_B32);
      for (uint16_t i = 0; i < repeatTime; ++i) {
          mask = AscendC::Reg::UpdateMask<T, AscendC::Reg::RegTensor<T>::trait>(sreg);
          AscendC::Reg::LoadAlign(src0Reg, src0 + i * REPEAT_STRIDE_B32);
          AscendC::Reg::LoadAlign(src1Reg, src1 + i * REPEAT_STRIDE_B32);
          AscendC::Reg::Mul<T, AscendC::Reg::MaskMergeMode::ZEROING>(dstReg, src0Reg, src1Reg, mask);
          AscendC::Reg::StoreAlign(dst + i * REPEAT_STRIDE_B32, dstReg, mask);
      }
  }
  ```

### 3.3 `__simd_callee__` — SIMD 被调用层

- **职责**：执行寄存器级别的原子操作（算术、比较、数据搬运等）
- **特点**：被内联到 `__simd_vf__` 中时参与融合优化；独立调用时不参与融合；可用于提取 `__simd_vf__` 中的公共函数
- **典型函数**：`Reg::Mul`, `Reg::Add`, `Reg::LoadAlign`, `Reg::StoreAlign`, `Reg::UpdateMask` 等
- **示例**：
  ```cpp
  template <typename T>
  __simd_callee__ inline void RsqrtCore(AscendC::Reg::RegTensor<T> &dstReg,
      AscendC::Reg::RegTensor<T> &srcReg, AscendC::Reg::MaskReg &mask)
  {
      AscendC::Reg::Duplicate(dstReg, static_cast<T>(1.0f), mask);
      AscendC::Reg::Compares<T, AscendC::CMPMODE::LT>(cmpMask, srcReg, static_cast<T>(0.0f), mask);
      AscendC::Reg::Sqrt(srcReg, srcReg, mask);
      AscendC::Reg::Div(dstReg, dstReg, srcReg, mask);
      AscendC::Reg::Select<T>(dstReg, srcReg, dstReg, cmpMask);
  }
  ```

### 3.4 三层结构使用规则

| 层级 | 修饰符 | 职责 | 调用关系 |
|------|--------|------|----------|
| Impl 层 | `__aicore__` | 接收 LocalTensor，提取地址 | 被外部调用，调用 `__simd_vf__` |
| RegImpl 层 | `__simd_vf__` | Load-Compute-Store 循环 | 被 `__aicore__` 调用 |
| Core 层 | `__simd_callee__` | 组合 Reg:: 原语的复合逻辑，用于复杂 `__simd_vf__` 逻辑提取公共函数 | 被 `__simd_vf__` 调用 |

> **简单 API**（如 Mul、Adds）只需两层（`__aicore__` + `__simd_vf__`），**复杂 API** 可考虑三层设计。

---

## 4. RegTensor 详解

RegTensor 是 VF 中的矢量寄存器，用于存储向量计算数据。

### 4.1 定义

VF 中的**矢量计算基本单元**，位宽为 VL（Vector Length）：

```
Ascend950 上 VL = 256B
```

### 4.2 模板参数

```cpp
template <typename T, const RegTrait& regTrait = RegTraitNumOne>
struct RegTensor;
```

| 参数 | 说明 |
|------|------|
| T | 数据类型：b8/b16/b32/b64 |
| regTrait | RegTraitNumOne: 1个VL (256B)<br>RegTraitNumTwo: 2个VL (512B) |

### 4.3 支持的数据类型

| 宽度 | 数据类型 |
|------|----------|
| b8 | int8_t, uint8_t, fp8, fp4, bool(仅搬运) |
| b16 | int16_t, uint16_t, half, bfloat16_t |
| b32 | int32_t, uint32_t, float, complex32 |
| b64 | int64_t, uint64_t, complex64 |

### 4.4 使用示例

```cpp
AscendC::Reg::RegTensor<uint32_t> reg;
AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<uint32_t, AscendC::Reg::MaskPattern::ALL>();
AscendC::Reg::LoadAlign<uint32_t>(reg, src, 0);
AscendC::Reg::Adds<uint32_t>(reg, reg, 1);
AscendC::Reg::StoreAlign<uint32_t>(dst, reg, 0, mask);
```

---

## 5. RegBase 核心 API 详解

### 5.1 MaskReg 与 CreateMask

**MaskReg 本质**：MaskReg 是矢量计算中的"开关"数组，用于指示哪些元素参与计算。

```
MaskReg 宽度 = RegTensor 位宽 / 8 = VL / 8

Ascend950 上：
- RegTensor: 256B = 2048 位
- MaskReg:   256B / 8 = 32B = 256 位
- 即：每个 bit 控制一个元素的计算使能
```

**工作原理**：
```
MaskReg bit = 1 → 对应元素参与计算
MaskReg bit = 0 → 对应元素不参与计算（结果保持为0）
```

**CreateMask** 用于创建固定模式的 MaskReg：

| 枚举值 | 说明 |
|--------|------|
| `MaskPattern::ALL` | 全1，所有元素有效 |
| `MaskPattern::ALLF` | 全0，所有元素无效 |
| `MaskPattern::H` | 半mask，前128位有效 |
| `MaskPattern::Q` | 1/4 mask，前64位有效 |
| `MaskPattern::VL1` | 仅lan0有效 |

**regTrait 参数**（CreateMask 和 UpdateMask 支持）：

| regTrait | 说明 |
|----------|------|
| `RegTraitNumOne` | 作用范围 256B（1个VL），b64 数据类型时 mask 每8位有效 |
| `RegTraitNumTwo` | 作用范围 512B（2个VL），b64 数据类型时 mask 每4位有效 |

```cpp
// 创建全 mask
AscendC::Reg::MaskReg maskFull = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();
AscendC::Reg::MaskReg maskNone = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALLF>();
AscendC::Reg::MaskReg maskH    = AscendC::Reg::CreateMask<uint32_t, AscendC::Reg::MaskPattern::H>();
AscendC::Reg::MaskReg maskQ    = AscendC::Reg::CreateMask<uint32_t, AscendC::Reg::MaskPattern::Q>();
AscendC::Reg::MaskReg maskOne  = AscendC::Reg::CreateMask<uint32_t, AscendC::Reg::MaskPattern::VL1>();
```

### 5.2 UpdateMask 自动递减机制

**函数原型**：
```cpp
template <typename T, const RegTrait& regTrait = RegTraitNumOne>
__simd_callee__ inline MaskReg UpdateMask(uint32_t& scalarValue);
```

**核心机制**：
- `scalarValue` 是**传入传出参数**，表示**剩余需要处理的元素数量**
- 函数内部自动计算：本次需要处理的 `VL_T`（VL 能容纳的 T 类型元素个数）
- 返回值：前 `min(count, VL_T)` 个元素为 1，其余为 0 的 mask
- **重要**：调用后 `scalarValue` 会被修改为 `scalarValue - VL_T`，为下次调用做准备

**示例**：处理 300 个 float 元素（每个 float 32bit = 4B，VL = 256B，所以 VL_float = 256/4 = 64 个元素）

```cpp
uint32_t count = 300;
AscendC::Reg::MaskReg mask1 = AscendC::Reg::UpdateMask<float>(count);  // mask1: 前64个元素有效，count 变为 236
AscendC::Reg::MaskReg mask2 = AscendC::Reg::UpdateMask<float>(count);  // mask2: 前64个元素有效，count 变为 172
AscendC::Reg::MaskReg mask3 = AscendC::Reg::UpdateMask<float>(count);  // mask3: 前64个元素有效，count 变为 108
AscendC::Reg::MaskReg mask4 = AscendC::Reg::UpdateMask<float>(count);  // mask4: 前64个元素有效，count 变为 44
AscendC::Reg::MaskReg mask5 = AscendC::Reg::UpdateMask<float>(count);  // mask5: 前44个元素有效，count 变为 0
```

**典型使用场景**：

```cpp
// 场景1：处理尾块（不整除的情况）
uint32_t count = 127;  // 不是 256B 的整数倍
MaskReg mask = AscendC::Reg::UpdateMask<uint32_t>(count);  // 前127个元素有效

// 场景2：条件计算
AscendC::Reg::LoadAlign<uint32_t>(reg, src, 0);
AscendC::Reg::Adds<uint32_t>(reg, reg, 1, mask);  // 只对 mask 为1的位置加1
```

### 5.3 RegTensor 与 MaskReg 配合使用

```
[UB内存] → LoadAlign → [RegTensor] → Compute → [RegTensor] → StoreAlign → [UB内存]
                                      ↓
                                MaskReg 控制哪些元素参与计算
```

| 操作 | RegTensor | MaskReg |
|------|------------|---------|
| LoadAlign | 目标寄存器 | 可选，控制加载有效位 |
| Compute | 源/目标 | 控制有效位 |
| StoreAlign | 源寄存器 | 控制有效位 |

```cpp
MaskReg mask = AscendC::Reg::CreateMask<uint32_t, AscendC::Reg::MaskPattern::ALL>();
AscendC::Reg::LoadAlign<float>(dstReg, srcAddr);
AscendC::Reg::Add<float>(dstReg, srcReg0, srcReg1, mask);
AscendC::Reg::StoreAlign<float>(dstAddr, dstReg, 0, mask);
```

### 5.4 StoreDist 模板参数

`StoreAlign` 通过 `StoreDist` 模板参数控制搬出行为：

**单搬出模式（搬一个 RegTensor）**：

| StoreDist | 含义 | 对齐要求 |
|-----------|------|----------|
| `DIST_NORM` | 正常模式，搬运 VL 数据 | 32B |
| `DIST_FIRST_ELEMENT_*` | 忽略 mask，只搬第一个元素 | 1/2/4B |
| `DIST_PACK_*` | 压缩模式，根据 mask 只搬有效元素的低半部分 bit | min(32, VL/2) |
| `DIST_PACK4_B32` | 压缩模式，只搬低8bit（四分之一） | min(32, VL/4) |

**双搬出模式（两个 RegTensor 交错输出）**：

| StoreDist | 含义 |
|-----------|------|
| `DIST_INTLV_B8` | 两个 RegTensor 元素交错存储到 dst |
| `DIST_INTLV_B16` | 同上 |
| `DIST_INTLV_B32` | 同上 |

```cpp
// 正常模式：完整写出 VL 数据
AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_NORM>(dstAddr, reg, mask);

// 压缩模式：根据 mask 只写出有效元素（用于 skip invalid 的场景）
AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_PACK_B32>(dstAddr, reg, mask);

// 双搬出：两个 RegTensor 交错输出
AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_INTLV_B32>(dstAddr, reg0, reg1, mask);
```

### 5.5 POST_MODE 地址更新模式

StoreAlign/LoadAlign 支持 `PostLiteral` 模板参数控制地址更新：

| PostLiteral | 含义 |
|-------------|------|
| `POST_MODE_NORMAL` | 固定地址，每次操作地址不变 |
| `POST_MODE_UPDATE` | 每次操作后自动更新地址：`addr += stride` |

```cpp
// POST_MODE_NORMAL：地址固定
for (uint16_t i = 0; i < repeatTimes; ++i) {
    AscendC::Reg::LoadAlign(reg, srcAddr + i * oneRepeatSize);      // 手动计算地址
    AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, reg, mask);
}

// POST_MODE_UPDATE：自动更新地址（更高效）
for (uint16_t i = 0; i < repeatTimes; ++i) {
    AscendC::Reg::LoadAlign<T, PostLiteral::POST_MODE_UPDATE>(reg, srcAddr, oneRepeatSize);
    AscendC::Reg::StoreAlign<T, PostLiteral::POST_MODE_UPDATE>(dstAddr, reg, oneRepeatSize, mask);
}
```

### 5.6 数据搬运模式总结

#### 模式 1：从 UB 加载指定地址的数据到 Reg（标量加载 + 广播）

将 UB 中**单个元素**加载到 RegTensor，并**广播**到整个寄存器宽度。

```cpp
template <typename T_IN>
__simd_callee__ inline void LoadScalarForDtypeTIn(
    __ubuf__ T_IN* src, AscendC::Reg::RegTensor<float>& dst,
    AscendC::Reg::MaskReg& preg, uint32_t offset)
{
    if constexpr (AscendC::IsSameType<T_IN, float>::value) {
        // float：直接加载并广播到整个 256B 寄存器
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_BRC_B32>(dst, src + offset);
    } else if constexpr (AscendC::IsSameType<T_IN, int8_t>::value) {
        // int8：先以 B8 广播加载到 int8 RegTensor，再分步 Cast 到 float
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::RegTensor<half> xInTmp;
        AscendC::Reg::LoadAlign<T_IN, AscendC::Reg::LoadDist::DIST_BRC_B8>(xIn, src + offset);
        AscendC::Reg::Cast<half, T_IN, castTraitI82F16>(xInTmp, xIn, preg);
        AscendC::Reg::Cast<float, half, castTraitF162F32>(dst, xInTmp, preg);
    } else if constexpr (AscendC::IsSameType<T_IN, int32_t>::value) {
        // int32：直接广播加载到 int32 RegTensor，再 Cast 到 float
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::LoadAlign<int32_t, AscendC::Reg::LoadDist::DIST_BRC_B32>(xIn, src + offset);
        AscendC::Reg::Cast<float, T_IN, castTraitInt322Fp32>(dst, xIn, preg);
    } else {
        // half / bfloat16：以 B16 广播加载，再 Cast 到 float
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::LoadAlign<T_IN, AscendC::Reg::LoadDist::DIST_BRC_B16>(xIn, src + offset);
        AscendC::Reg::Cast<float, T_IN, castTraitF162F32>(dst, xIn, preg);
    }
}
```

**关键点**：
- `LoadDist::DIST_BRC_B32/B16/B8` 实现**单元素广播加载**，将 UB 中 1 个元素复制到整个 RegTensor
- 若输入 dtype 不是 float，需通过中间 RegTensor 分步 Cast（如 `int8 → half → float`）

#### 模式 2：从 UB 加载连续数据到 RegTensor（向量加载）

将 UB 中**连续一段数据**加载到 RegTensor，支持自动解包（unpack）以适配不同位宽 dtype。

```cpp
template <typename T_IN>
__simd_callee__ inline void LoadTensorForDtypeTIn(
    __ubuf__ T_IN* src, AscendC::Reg::RegTensor<float>& dst,
    AscendC::Reg::MaskReg& preg, uint32_t offset)
{
    if constexpr (AscendC::IsSameType<T_IN, float>::value) {
        // float：正常加载 64 个 float（256B）
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(dst, src + offset);
    } else if constexpr (AscendC::IsSameType<T_IN, int8_t>::value) {
        // int8：解包加载 64 个 int8 → 扩展为 64 个 float
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::RegTensor<half> xInTmp;
        AscendC::Reg::LoadAlign<T_IN, AscendC::Reg::LoadDist::DIST_UNPACK4_B8>(xIn, src + offset);
        AscendC::Reg::Cast<half, T_IN, castTraitI82F16>(xInTmp, xIn, preg);
        AscendC::Reg::Cast<float, half, castTraitF162F32>(dst, xInTmp, preg);
    } else if constexpr (AscendC::IsSameType<T_IN, int32_t>::value) {
        // int32：正常加载 64 个 int32（256B），再 Cast 到 float
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::LoadAlign<int32_t, AscendC::Reg::LoadDist::DIST_NORM>(xIn, src + offset);
        AscendC::Reg::Cast<float, T_IN, castTraitInt322Fp32>(dst, xIn, preg);
    } else {
        // half / bfloat16：解包加载 128 个 half → 64 个 float
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::LoadAlign<T_IN, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(xIn, src + offset);
        AscendC::Reg::Cast<float, T_IN, castTraitF162F32>(dst, xIn, preg);
    }
}
```

**关键点**：
- `LoadDist::DIST_NORM`：正常加载，UB 数据位宽与 RegTensor 位宽一致
- `LoadDist::DIST_UNPACK_B16`：从 UB 加载 2B 元素，解包为 4B（half → float）
- `LoadDist::DIST_UNPACK4_B8`：从 UB 加载 1B 元素，解包为 4B（int8 → float）
- 不同 dtype 的解包倍数不同，需配合 `Cast` 完成类型转换

#### 模式 3：存储 RegTensor 到 UB（向量存储）

将 RegTensor 中**全部数据**存储到 UB，支持压缩（pack）以适配低位宽 dtype。

```cpp
template <typename T_OUT>
__simd_callee__ inline void StoreTensorForDtypeTOut(
    __ubuf__ T_OUT* dst, AscendC::Reg::RegTensor<float>& xRegFp32,
    AscendC::Reg::MaskReg& preg, uint32_t offset)
{
    if constexpr (AscendC::IsSameType<T_OUT, float>::value) {
        // float：正常存储 64 个 float（256B）
        AscendC::Reg::StoreAlign<T_OUT, AscendC::Reg::StoreDist::DIST_NORM>(dst + offset, xRegFp32, preg);
    } else if constexpr (AscendC::IsSameType<T_OUT, half>::value || AscendC::IsSameType<T_OUT, bfloat16_t>::value) {
        // half / bfloat16：先 Cast 到 half，再压缩存储
        AscendC::Reg::RegTensor<T_OUT> xOut;
        AscendC::Reg::Cast<T_OUT, float, castTraitF322F16>(xOut, xRegFp32, preg);
        AscendC::Reg::StoreAlign<T_OUT, AscendC::Reg::StoreDist::DIST_PACK_B32>(dst + offset, xOut, preg);
    } else if constexpr (AscendC::IsSameType<T_OUT, int8_t>::value) {
        // int8：先 Cast 到 half，再 Cast 到 int8，最后压缩存储
        AscendC::Reg::RegTensor<T_OUT> xOut;
        AscendC::Reg::RegTensor<half> xRegFp16;
        AscendC::Reg::Cast<half, float, castTraitFp322Fp16>(xRegFp16, xRegFp32, preg);
        AscendC::Reg::Cast<int8_t, half, castTraitFp162Int8>(xOut, xRegFp16, preg);
        AscendC::Reg::StoreAlign<T_OUT, AscendC::Reg::StoreDist::DIST_PACK4_B32>(dst + offset, xOut, preg);
    }
}
```

**关键点**：
- `StoreDist::DIST_NORM`：正常存储，RegTensor 位宽与 UB 数据位宽一致
- `StoreDist::DIST_PACK_B32`：将 4B 元素压缩为 2B（float → half）
- `StoreDist::DIST_PACK4_B32`：将 4B 元素压缩为 1B（float → int8）
- 存储前需先将 float32 Cast 为目标 dtype，再通过 pack 模式写入 UB

#### 模式 4：存储 RegTensor 中的一个元素到 UB（标量存储）

将 RegTensor 中**第一个有效元素**存储到 UB 指定地址，常用于归约结果输出。

```cpp
// 归约结果存储：将 ReduceSum 后的单个 float 值存到 UB
AscendC::Reg::RegTensor<float> vMean;
AscendC::Reg::MaskReg pregOne = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::VL1>();

// 执行归约
AscendC::Reg::ReduceSum(vMean, xReg, mask);

// 只存储第一个元素（忽略 mask，仅搬 1 个 float = 4B）
AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
    dstUb + rowIndex, vMean, pregOne);
```

**关键点**：
- `StoreDist::DIST_FIRST_ELEMENT_B32`：忽略 mask，仅搬运 RegTensor 的**第一个元素**
- `B32` 后缀表示按 4B（32bit）对齐存储，适用于 float
- 必须配合 `MaskPattern::VL1` 使用，确保只存储 1 个元素
- 常用于 `ReduceSum`、`ReduceMax` 等归约操作的结果输出

---

## 6. 非对齐数据处理

### 6.1 UnalignReg 概念

当数据地址**不满足 32B 对齐**时，需要使用 UnalignReg 处理：

- `UnalignRegForLoad`：加载侧非对齐寄存器，长度 32B
- `UnalignRegForStore`：存储侧非对齐寄存器，长度 32B

### 6.2 连续非对齐处理流程

```cpp
// 连续非对齐搬入
AscendC::Reg::LoadUnAlignPre(uregLoad, srcAddr + i * stride);    // 预处理
AscendC::Reg::LoadUnAlign(reg, uregLoad, srcAddr + i * stride);  // 正式加载

// 连续非对齐搬出
AscendC::Reg::StoreUnAlign(dstAddr, reg, uregStore, stride);     // 正式存储
AscendC::Reg::StoreUnAlignPost(dstAddr, uregStore, 0);           // 处理尾块
```

**关键点**：
- `StoreUnAlign` 和 `StoreUnAlignPost` **必须成对使用**
- `StoreUnAlignPost` 处理最后一次非对齐操作的剩余数据

### 6.3 非对齐场景选择

| 场景 | 搬入API | 搬出API |
|------|---------|---------|
| 地址对齐（32B） | LoadAlign | StoreAlign |
| 地址非对齐 | LoadUnAlign (+ LoadUnAlignPre) | StoreUnAlign + StoreUnAlignPost |

---

## 7. AddrReg 地址寄存器

### 7.1 概念

**AddrReg** = Address Register，用于存储地址偏移量的寄存器。

- 编译器自动识别循环中的地址计算模式，生成硬件地址寄存器，不需要显式实现
- 每层循环根据所设置的 stride 进行自增
- 减少 Scalar 计算开销，提升地址计算效率

### 7.2 自动优化条件

编译器自动生成 AddrReg 的模式：

```cpp
for (uint16_t i = 0; i < extent1; i++) {
    for (uint16_t j = 0; j < extent2; j++) {
        for (uint16_t k = 0; k < extent3; k++) {
            for (uint16_t m = 0; m < extent4; m++) {
                AscendC::Reg::LoadAlign(reg, srcAddr + i*const1 + j*const2 + k*const3 + m*const4);
            }
        }
    }
}
```

**要点**：
- 最多支持 **4 层循环**寻址
- 循环变量必须是 `uint16_t`
- 地址表达式必须是**线性组合**：`i*stride_i + j*stride_j + ...`
- 推荐让编译器自动识别，手动使用 AddrReg 可能限制优化

---

## 8. Hardware Loop 规范

`__simd_vf__` 和 `__simd_callee__` 修饰的函数中，`for` 循环必须满足以下全部条件，才能被编译器识别为 Hardware Loop：

| 要求 | 说明 |
|------|------|
| 迭代变量类型 | **必须为 `uint16_t`** |
| 起始值 | **必须从 0 开始** |
| 步长 | **必须递增 1**（`++i`） |
| 禁止分支 | **不允许 `if/else`、三元运算符 `?:`**，`if constexpr` 除外 |
| 循环边界不可变 | 一旦进入循环，边界值不能被修改 |
| 嵌套层数 | **最多 4 层** |

```cpp
// ✅ 正例：符合 Hardware Loop 规范
for (uint16_t i = 0; i < LoopBound; i++) {
    for (uint16_t j = 0; j < LoopBound; j++) {
        for (uint16_t k = 0; k < LoopBound; k++) {
            // 计算
        }
    }
}

// ❌ 反例：循环内包含 if 判断
for (uint16_t i = 0; i < LoopBound; i++) {
    if (condition) { ... }  // 破坏 Hardware Loop
}
```

### 8.1 条件替代方案

#### 方案 A：使用 `for(1)` 替代运行时 if（数据相关条件）

```cpp
// ❌ 反例：使用 if 判断
uint16_t tailK = srcK % floatRepSize;
if (tailK > 0) {
    // 尾块处理
}

// ✅ 正例：使用 for(1) 替代 if
uint16_t tailK = srcK % floatRepSize;
uint16_t hasTail = !!tailK;
for (uint16_t i = 0; i < hasTail; i++) {
    // 尾块处理
}
```

**原理**：for(1) 会被编译器优化为条件执行，无跳转开销，优于分支判断。

**注意**：上述规则仅适用于 VF 内部循环。VF 外层（如 Process 函数中的尾块判断）是允许的。

#### 方案 B：使用模板参数 + `if constexpr`（配置相关条件）

```cpp
// ❌ 反例：VF 内使用运行时 if
__simd_vf__ inline void ComputeVF(..., int mode) {
    for (uint16_t i = 0; i < repeatTime; ++i) {
        if (mode == 0) {  // ❌ 运行时 if 阻碍 Hardware Loop
            // mode 0 计算
        } else {
            // mode 1 计算
        }
    }
}

// ✅ 正例：使用模板参数 + if constexpr
template <int Mode>
__simd_vf__ inline void ComputeVFImpl(...) {
    for (uint16_t i = 0; i < repeatTime; ++i) {
        if constexpr (Mode == 0) {  // ✅ 编译期求值，零开销
            // mode 0 计算
        } else {
            // mode 1 计算
        }
    }
}

// __aicore__ 层分发
__aicore__ inline void ComputeVF(..., int mode) {
    if (mode == 0) {
        ComputeVFImpl<0>(...);
    } else {
        ComputeVFImpl<1>(...);
    }
}
```

### 8.2 嵌套循环层数

- **最多 4 层嵌套**
- 每层可包含多个串行循环
- 支持非循环的向量操作和标量操作

---

## 9. VF 融合优化

**VF 融合是 RegBase 性能优化中最关键的手段。**

### 9.1 核心原则

> **让所有数据（包括标量）以最高效的方式到达计算寄存器，消除一切不必要的 UB 往返。**

### 9.2 融合方法

将多个独立的 `__simd_vf__` 调用**手动合并为单个 `__simd_vf__` 函数**，在循环内完成全部 Load → Compute → Store：

```cpp
// ❌ 反例：多个独立 VF 调用，中间结果通过 UB 传递
CustomRegImpl::CastImpl<float, T>(aF, aL, len);   // VF-1: Load+Cast+Store
CustomRegImpl::CastImpl<float, T>(bF, bL, len);   // VF-2: Load+Cast+Store
CustomRegImpl::SwiGLUImpl(yF, aF, bF, len);       // VF-3: Load+Compute+Store
CustomRegImpl::CastImpl<T, float>(yL, yF, len);   // VF-4: Load+Cast+Store

// ✅ 正例：融合为单个 __simd_vf__，全程在 RegTensor 上完成
template <typename T>
__simd_vf__ inline void FusedSwiGLUImpl(__ubuf__ T *dstY, __ubuf__ T *srcA,
    __ubuf__ T *srcB, uint32_t calCount)
{
    // ... Load → (Unpack/Cast to float) → Compute → (Cast/Pack to T) → Store
    // 消除所有中间 UB round-trip
}
```

### 9.3 融合要点

1. **统一循环粒度**：以 float 的 `repeatStride`（通常为 64）作为循环步长
2. **模板函数支持多数据类型**：将 Cast 融合入 VF 函数
3. **`if constexpr` 处理类型分支**：`if constexpr (sizeof(T) == 2)` 包裹 Cast/Unpack 逻辑
4. **寄存器预算**：融合后 `RegTensor` 总数需控制在 **32 个以内**
5. **融合前置/后置计算**：不仅融合主路径，还应将 area 计算、类型转换等一并纳入

### 9.4 融合后清理

VF 融合后，原来独立的 RegBase 实现可能变为死代码，应及时删除：
- [ ] 删除不再被调用的 `__simd_vf__` RegBase 实现
- [ ] 删除不再被调用的 `__aicore__` 包装函数
- [ ] 删除不再需要的中间 buffer（TBuf/LocalTensor）

---

## 10. 同步机制

Ascend 950 采用多流水线并行架构（`PIPE_V` 向量、`PIPE_M` 搬运、`PIPE_S` 标量），各流水线独立发射、异步执行。

### 10.1 跨流水线同步

| 场景 | 同步方式 | 说明 |
|------|----------|------|
| Vector ↔ Scalar | `SetFlag/WaitFlag` (V_S) | **必须使用**，禁止用 `PipeBarrier` |
| Vector ↔ Vector | 无需同步 | 相邻 Vector 计算天然保序 |
| 搬运 ↔ Vector（无依赖） | 无需同步 | 确认无 RAW/WAR/WAW 依赖 |
| 同一流水线内部 | `PipeBarrier` | 仅用于同流水线同步 |

### 10.2 Vector → Scalar 同步示例

```cpp
// ❌ 反例：Vector 后直接用 Scalar 读取结果
AscendC::ReduceMax(ubTensor, ubSrc, ubWorkBuffer, params);
float maxVal = ubTensor.GetValue(0);  // 可能读到旧数据

// ✅ 正例：插入 V_S 同步
AscendC::ReduceMax(ubTensor, ubSrc, ubWorkBuffer, params);
int32_t eventIdVToS = static_cast<int32_t>(
    GetTPipePtr()->FetchEventID(AscendC::HardEvent::V_S)
);
AscendC::SetFlag<AscendC::HardEvent::V_S>(eventIdVToS);
AscendC::WaitFlag<AscendC::HardEvent::V_S>(eventIdVToS);
float maxVal = ubTensor.GetValue(0);  // 安全读取
```

### 10.3 去除过度同步

```cpp
// ❌ 反例：相邻 Vector 之间插入全流水屏障（下一条仍是 Vector，屏障多余）
for (...) { /* Vector 计算 */ }
// 冗余的全流水屏障调用，应删除
for (...) { /* Vector 计算 */ }

// ✅ 正例：相邻 Vector 之间无需任何屏障
for (...) { /* Vector 计算 */ }
for (...) { /* Vector 计算 */ }
```

> **注意**：Ascend 950 上 `PipeBarrier<PIPE_V>()` 不需要，应全部删除。

### 10.4 VF 内同步操作 LocalMemBar

**功能**：Reg 矢量计算宏函数内不同流水线之间的同步指令。目的流水线将等待源流水线上所有指令完成才执行。

**函数原型**：
```cpp
template <MemType src, MemType dst>
__simd_callee__ inline void LocalMemBar()
```

**MemType 取值**：

| MemType | 含义 |
|---------|------|
| `VEC_STORE` | SIMD_VF 函数内矢量写 UB 流水线（StoreAlign/StoreUnAlign/Store） |
| `VEC_LOAD` | SIMD_VF 函数内矢量读 UB 流水线（LoadAlign/LoadUnAlign/Load） |
| `SCALAR_STORE` | SIMD_VF 函数内标量写 UB 流水线（Duplicate） |
| `SCALAR_LOAD` | SIMD_VF 函数内标量读 UB 流水线（GetValue） |
| `VEC_ALL` | SIMD_VF 函数内所有矢量读写 UB 流水线 |
| `SCALAR_ALL` | SIMD_VF 函数内所有标量读写 UB 流水线 |

**src 和 dst 有效组合**：

| src | dst |
|-----|-----|
| VEC_STORE | VEC_LOAD |
| VEC_LOAD | VEC_STORE |
| VEC_STORE | VEC_STORE |
| VEC_STORE | SCALAR_LOAD |
| VEC_STORE | SCALAR_STORE |
| VEC_LOAD | SCALAR_STORE |
| SCALAR_STORE | VEC_LOAD |
| SCALAR_STORE | VEC_STORE |
| SCALAR_LOAD | VEC_STORE |
| VEC_ALL | VEC_ALL |
| VEC_ALL | SCALAR_ALL |
| SCALAR_ALL | VEC_ALL |

**使用场景**：
- 当读指令使用的寄存器和写指令使用的寄存器相同时，可以触发寄存器保序，不需要插入同步指令
- 当使用的寄存器不同时，如果要确保读写指令顺序执行，则需要插入同步指令

**典型使用场景**：循环中访问同一 UB 地址空间时，需要确保写完成后再读。

---

## 11. 寄存器资源管理

| 资源类型 | 最大数量 | 超限后果 |
|----------|----------|----------|
| `RegTensor` | 32 个 | 编译器插入换入换出，性能劣化 |
| `MaskReg` | 8 个 | 同上 |
| `UnalignRegForLoad` | 4 个（读） | 同上 |
| `UnalignRegForStore` | 4 个（写） | 同上 |

超出会导致寄存器溢出，性能严重劣化。

### 11.1 优化 MaskReg 使用

```cpp
// ❌ 反例：!(a && b) 需要额外 MaskReg
AscendC::Reg::MaskAnd(noNaNMask, dstMask, tmpMask0, mask);
AscendC::Reg::MaskNot(noNaNMask, noNaNMask, mask);

// ✅ 正例：布尔代数化简 → !a || !b
AscendC::Reg::MaskNot(dstMask, dstMask, mask);
AscendC::Reg::MaskOr(tmpMask0, tmpMask0, dstMask, mask);
```

### 11.2 利用 Compare 的 mask 参数级联

```cpp
// ❌ 反例：两次 Compare + 一次 MaskAnd
AscendC::Reg::Compares<uint64_t, CMPMODE::EQ>(tmpMask0, part0, 0, mask);
AscendC::Reg::Compares<uint64_t, CMPMODE::EQ>(dstMask, part1, 0, mask);
AscendC::Reg::MaskAnd(tmpMask0, tmpMask0, dstMask, mask);

// ✅ 正例：第二次 Compare 的 mask 用第一次结果
AscendC::Reg::Compares<uint64_t, CMPMODE::EQ>(tmpMask0, part0, 0, mask);
AscendC::Reg::Compares<uint64_t, CMPMODE::EQ>(tmpMask1, part1, 0, tmpMask0);
// tmpMask1 等效于 (part0 == 0) && (part1 == 0)
```

---

## 12. 标量数据传递

**标量应直接传入 VF 函数，禁止走 UB 中转。**

```cpp
// ❌ 反例：标量先广播到 UB，再从 UB 加载
float gtX1 = ...;
CustomRegImpl::DuplicateImpl(gtX1Local_, gtX1, blockN);  // 标量→UB
ComputeIouFusedVF(..., gtX1Ub, ...);  // UB→寄存器

// ✅ 正例：标量直接传入 VF
__simd_vf__ inline void ComputeIouFullyFusedVF(
    ..., float gtX1Scalar, ...) {
    AscendC::Reg::RegTensor<float> gtX1Reg;
    AscendC::Reg::MaskReg fullMask = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::Duplicate(gtX1Reg, gtX1Scalar, fullMask); // 标量→寄存器（无UB）
    for (...) {
        AscendC::Reg::Max(ltXReg, x1Reg, gtX1Reg, mask);
    }
}
```

---

## 13. 循环内优化

### 13.1 loopTimes 计算公式

```cpp
// count: 本次需要处理的元素个数
// VL_FP32: 256B / 4 = 64 个 float 元素

// 方式1：通用公式（向上取整）
uint16_t loopTimes = CeilDiv(count * sizeof(float), platform::GetVRegSize());

// 方式2：已知类型时的简化写法
uint16_t loopTimes = (count + VL_FP32 - 1) / VL_FP32;
```

**为什么用 count * sizeof(float)**：
- RegTensor 容量是按 **字节** 算的（VL = 256B）
- count 是元素个数，需要转换为字节再除以 VL

### 13.2 成员变量预取到局部变量

```cpp
// ❌ 反例：循环内直接访问成员变量
for (uint16_t i = 0; i < (uint16_t)tiling.srcM; i++) {
    AscendC::ReduceMax(maxAddr + i * FLOAT_NUM_PER_BLK,
                       srcAddr + i * tiling.srcK,
                       workAddr, (uint16_t)originalSrcShape.k);
}

// ✅ 正例：通过局部变量传递
uint16_t srcK = tiling.srcK;
uint16_t srcM = tiling.srcM;
uint16_t originK = (uint16_t)originalSrcShape.k;
for (uint16_t i = 0; i < srcM; i++) {
    AscendC::ReduceMax(maxAddr + i * FLOAT_NUM_PER_BLK,
                       srcAddr + i * srcK,
                       workAddr, originK);
}
```

### 13.3 循环不变指令外提

```cpp
// ❌ 反例：Duplicate 在循环内
for (uint16_t i = 0; i < repeatTimes; i++) {
    AscendC::Reg::Duplicate(dstReg, scalarValue);  // 每次循环重复
    AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
}

// ✅ 正例：Duplicate 提到循环外
AscendC::Reg::Duplicate(dstReg, scalarValue);  // 仅执行一次
for (uint16_t i = 0; i < repeatTimes; i++) {
    AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
}
```

---

## 14. 指令双发优化

利用硬件双发（Dual-Issue）特性，使处理器在同一时钟周期内同时发射两条**无依赖**的指令。

### 14.1 基本原则

- 同一周期可发射两条无依赖指令
- 循环内减少数据依赖

```cpp
// ❌ 反例：链式依赖
Adds(dstReg, dstReg, 10);  // 依赖前一条
Adds(dstReg, dstReg, 10);  // 依赖前一条

// ✅ 正例：拆分循环，减少依赖
for (...) { Load; Add; Store; }  // Loop 1
for (...) { Adds; Adds; Store; } // Loop 2
```

### 14.2 合理拆分长依赖链

当单循环内依赖链过长时，拆分为多个 VF 函数：

```cpp
// ❌ 反例：单循环内依赖链过长
for (uint16_t i = 0; i < 32; ++i) {
    Load; Load; Add;
    Adds(dstReg, dstReg, 10, mask);  // 链式依赖
    Adds(dstReg, dstReg, 10, mask);
    Adds(dstReg, dstReg, 10, mask);
    // ... 更多依赖
    Store;
}

// ✅ 正例：拆分为两个 VF 循环
for (uint16_t i = 0; i < 32; ++i) {  // VLoop-1
    Load; Load; Add; Adds; Adds; Adds; Store;
}
for (uint16_t i = 0; i < 32; ++i) {  // VLoop-2
    Load; Adds; Adds; Adds; Store;
}
```

---

## 15. 计算顺序调整

在 `__aicore__` 层调整无数据依赖的 VF 调用顺序，把独立的 `CustomRegImpl::XxImpl` 调用变得相邻，从而创造融合条件。

### 15.1 输出目标不同导致的"虚假串行"

```cpp
// ❌ 反例：按逻辑顺序书写，实际上两者无依赖
CustomRegImpl::SubVF(tmpA, x2, x1, len);   // VF-1
CustomRegImpl::AddVF(tmpB, y2, y1, len);   // VF-2
// 两个 VF 分别写不同 UB 地址，完全可以合并

// ✅ 正例：融合为一个 VF
__simd_vf__ inline void FusedABVF(...) {
    for (uint16_t i = 0; i < repeatTime; ++i) {
        LoadAlign(x1Reg, x1 + i * stride);
        LoadAlign(x2Reg, x2 + i * stride);
        LoadAlign(y1Reg, y1 + i * stride);
        LoadAlign(y2Reg, y2 + i * stride);
        Sub(tmpAReg, x2Reg, x1Reg, mask);
        Add(tmpBReg, y2Reg, y1Reg, mask);
        StoreAlign(tmpA + i * stride, tmpAReg, mask);
        StoreAlign(tmpB + i * stride, tmpBReg, mask);
    }
}
```

### 15.2 重排原则

1. **依赖分析优先**：确认两个 VF 调用是否存在 RAW/WAR/WAW 依赖
2. **先重排再融合**：第一步调整到相邻位置，第二步合并为单个 `__simd_vf__`
3. **寄存器代价评估**：融合后 `RegTensor` 超过 32 个时，可尝试"部分融合"
4. **避免跨流水线同步增加**：重排后重新评估同步需求

---

## 16. 多数据类型支持

对于需要支持多种数据类型或精度要求的场景，推荐将输入转换为 float32 计算后输出：

```cpp
#include "cast_common.h"  // 提供 LoadScalarForDtypeTIn, StoreTensorForDtypeTOut

template <typename DST_TYPE, typename SRC_TYPE>
__simd_vf__ inline void XXXRegImpl(__ubuf__ DST_TYPE *dst, __ubuf__ SRC_TYPE *src,
    const uint32_t calCount)
{
    uint16_t repeatTime = static_cast<uint16_t>((calCount + REPEAT_STRIDE_B32 - 1) / REPEAT_STRIDE_B32);
    uint32_t sreg = calCount;
    AscendC::Reg::MaskReg preg;
    AscendC::Reg::RegTensor<float> xfp32;
    for (uint16_t i = 0; i < repeatTime; ++i) {
        preg = AscendC::Reg::UpdateMask<float>(sreg);
        LoadScalarForDtypeTIn<SRC_TYPE>(src, xfp32, preg, i * REPEAT_STRIDE_B32);
        // ... float32 计算逻辑
        StoreTensorForDtypeTOut<DST_TYPE>(dst, xfp32, preg, i * REPEAT_STRIDE_B32);
    }
}
```

---

## 17. 常见错误与纠正

### 错误 1：仅做 API 替换，未做 VF 融合

```cpp
// ❌ 把 AscendC API 换成 RegBase API，但仍是多个独立 VF 调用
CustomRegImpl::SubImpl(area1Local_, x2Local_, x1Local_, blockN);
CustomRegImpl::AddsImpl(area1Local_, area1Local_, bias, blockN);
CustomRegImpl::MulImpl(area1Local_, area1Local_, denomLocal_, blockN);

// ✅ 融合为单个 __simd_vf__ 函数
__simd_vf__ inline void ComputeArea1FusedVF(...) {
    for (uint16_t i = 0; i < repeatTime; ++i) {
        LoadAlign(x1Reg, x1 + i * stride);
        LoadAlign(x2Reg, x2 + i * stride);
        Sub(tmpXReg, x2Reg, x1Reg, mask);
        Adds(tmpXReg, tmpXReg, biasReg, mask);
        // ... 全部计算在寄存器完成
        StoreAlign(area1 + i * stride, area1Reg, mask);
    }
}
```

### 错误 2：VF 内使用运行时 if/else

参见第 8.1 节，使用 `for(1)` 或模板参数 + `if constexpr` 替代。

### 错误 3：标量走 UB 中转

参见第 12 节，标量直接传入 VF 函数。

### 错误 4：忽视前置/后置计算

```cpp
// ❌ 只融合主计算路径，忽视前置计算
ComputeArea1();         // 独立的 VF 调用（前置计算）
ComputeIouFusedVF(...); // 融合的主计算

// ✅ 将前置计算也纳入融合
ComputeIouFullyFusedVF(...);  // 包含 area1 计算 + 主计算
```

### 错误 5：函数修饰符使用不当

```
fatal error: error in backend: Do not know how to split the result of this operator!
```

出现此错误时，检查 `__aicore__` / `__simd_vf__` / `__simd_callee__` 是否正确使用。常见原因是使用 `AscendC::Reg` API 的函数未被修饰为 `__simd_vf__` / `__simd_callee__`。

### 错误 6：partial mask 下累积寄存器被 ZEROING 清零

当对累积寄存器（如 max、sum）使用 partial mask 进行 `Reg::Max`、`Reg::Add` 等操作时，ZEROING 模式会将 mask 外的 lane 清零，**静默破坏之前累积的值**。编译器不报错，运行时产生数量级偏差或 overflow。

```cpp
// ❌ UpdateMask 单循环模式用于累积操作：最后一轮 tail mask 清零之前的累积
Reg::Duplicate(maxReg, -3.4028235e+38f, maskFull);
uint32_t sreg = numCol;
for (uint16_t j = 0; j < repeatTimes; j++) {
    mask = Reg::UpdateMask<float>(sreg);
    Reg::LoadAlign(srcReg, src + j * REPEAT_STRIDE);
    Reg::Max(maxReg, maxReg, srcReg, mask);  // tail 轮 mask 外 lane 被清零！
}
// 如果 numCol=199，最后一轮 mask=7，位置 7-63 的累积 max 全部被清零

// ✅ main + tail 分离 + Select 保护
uint16_t mainRepeatTime = static_cast<uint16_t>(numCol / REPEAT_STRIDE);
uint32_t tailCount = numCol % REPEAT_STRIDE;
uint16_t tailRepeatTime = static_cast<uint16_t>(
    (tailCount + REPEAT_STRIDE - 1) / REPEAT_STRIDE);
Reg::MaskReg maskFull = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
Reg::MaskReg maskTail = Reg::UpdateMask<float>(tailCount);
Reg::RegTensor<float> maxTailReg;

Reg::Duplicate(maxReg, -3.4028235e+38f, maskFull);
for (uint16_t j = 0; j < mainRepeatTime; j++) {
    Reg::LoadAlign(srcReg, src + j * REPEAT_STRIDE);
    Reg::Max(maxReg, maxReg, srcReg, maskFull);  // maskFull 不破坏任何 lane
}
for (uint16_t j = 0; j < tailRepeatTime; j++) {     // 循环次数 0-1 次
    Reg::LoadAlign(srcReg, src + mainRepeatTime * REPEAT_STRIDE);
    Reg::Max(maxTailReg, maxReg, srcReg, maskTail);   // 结果写入临时寄存器
    Reg::Select(maxReg, maxTailReg, maxReg, maskTail); // 只更新有效 lane
}


// 或者在循环中每次 Select
uint16_t repeatTime = static_cast<uint16_t>((numCol + REPEAT_STRIDE - 1) / REPEAT_STRIDE);
Reg::MaskReg maskFull = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
Reg::MaskReg mask = Reg::UpdateMask<float>(tailCount);
Reg::RegTensor<float> maxReg, maxRegTmp;

Reg::Duplicate(maxReg, -3.4028235e+38f, maskFull);
for (uint16_t j = 0; j < repeatTime; j++) {
    Reg::LoadAlign(srcReg, src + j * REPEAT_STRIDE);
    Reg::Max(maxRegTmp, maxReg, srcReg, maskFull);
    Reg::Select(maxReg, maxRegTmp, maxReg, mask);   // 确保被 ZEROING 模式清理的 lane 被复原
}
```

### 错误 7：numCol 与 numColAlign 混淆

当输入数据按 32B 对齐分配时，内存中每行的 stride（`numColAlign * sizeof(T) 满足 32B 对齐`）大于有效元素数（`numCol`）。将两者混用会导致 padding 区域的零参与 reduce 计算。

```cpp
// ❌ 用对齐后的 stride 做 mask 计算：padding 零参与 softmax 的 sum
uint32_t colNumAlign = AlignUp(colNum, 8);  // 199 -> 200
uint16_t repeatTimes = (colNumAlign + 63) / 64;  // 错：应该用 numCol=199
// mask 会多覆盖 1 个 padding 零，softmax 分母偏大，结果偏小

// ✅ 分离 numCol（mask 计算）和 numColAlign（地址偏移）
uint16_t mainRepeatTime = static_cast<uint16_t>(numCol / REPEAT_STRIDE);  // 用 numCol
// ...
Reg::LoadAlign(srcReg, src + row * numColAlign + j * REPEAT_STRIDE);  // 用 numColAlign
```

**规则**：
- `numCol` → mask 计算（`mainRepeatTime`、`tailCount`、`UpdateMask` 参数）
- `numColAlign` → 内存地址偏移（`src + row * numColAlign + j * 64`）

---

## 18. 编程检查清单

编写或优化 RegBase 代码时，逐条检查：

### 结构规范
- [ ] 三层调用链是否正确（`__aicore__` → `__simd_vf__` → `__simd_callee__`）？
- [ ] `__simd_vf__` / `__simd_callee__` 中循环变量是否为 `uint16_t`，从 0 开始，步长 1？
- [ ] 循环内是否有 `if/else` 或三元运算符（`if constexpr` 除外）？
- [ ] 循环边界是否在循环内被修改？
- [ ] 嵌套层数是否超过 4 层？

### VF 融合
- [ ] 是否还有多个独立的 `__simd_vf__` 调用连续执行？
- [ ] 这些调用的循环结构是否一致（相同的 repeatTime）？
- [ ] 前置/后置计算（如 Cast）是否可以与主 VF 融合？
- [ ] 融合后 `RegTensor` 是否超过 32 个？

### 寄存器与性能
- [ ] 循环内是否有可外提的不变指令（如 `Duplicate`）？
- [ ] 成员变量是否预取到局部变量？
- [ ] 标量是否直接传入 VF，而非走 UB 中转？
- [ ] `MaskReg` 使用是否可优化（布尔代数化简、级联 Compare）？
- [ ] 指令依赖链是否过长？是否需要拆分 VF？

### 同步
- [ ] 相邻 Vector 指令之间是否有不必要的 `PipeBarrier`？
- [ ] 是否存在冗余的全流水屏障？是否可删除？
- [ ] Vector 写 UB 后是否有数据依赖的 Scalar 读写？是否插入了 `SetFlag/WaitFlag`？

### 清理
- [ ] 是否有未使用的 `__simd_vf__` 函数？
- [ ] 是否有未使用的 `__aicore__` 包装函数？
- [ ] 是否有未使用的 TBuf/LocalTensor？
- [ ] 代码是否简洁清晰？
