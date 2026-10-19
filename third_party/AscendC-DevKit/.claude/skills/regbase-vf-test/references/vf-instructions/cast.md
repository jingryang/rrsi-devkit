# Reg::Cast

> **概述**：多布局语义（ZERO/ONE/TWO/THREE/UNKNOWN）、类型转换寄存器扩展矩阵、`CastTrait` 声明模式及单指令用法。
>
> ⚡ **要写 Cast 代码？先去 [`../examples/cast_index.md`](../examples/cast_index.md)** —— 按「源 dtype → 目标 dtype」一行定位到 `cast_common.h` 中**已验证可直接搬运的 helper**（`LoadTensorForDtypeTIn` / `StoreTensorForDtypeTOut` / `LoadScalarForDtypeTIn`），覆盖 fp32/fp16/bf16/int8/int32/fp8/hifp8/fp4。
> **本文档讲原理**（为什么这么写、多布局语义、陷阱成因）；**cast_index.md**（[`../examples/cast_index.md`](../examples/cast_index.md)）给代码（照抄即可）。自行声明 `CastTrait` 手写 Cast 也可以，只是 index 里多数常见 dtype 组合已有现成 helper，优先复用更省事。

## 1. 用途

进行数据类型转换，并可选地基于布局选择元素。`Reg::Cast` 的核心特性是**多布局**能力：单个源寄存器可以 Cast 到多个目标寄存器，每个目标寄存器根据 `CastTrait` 中的 `RegLayout` 字段接收不同的元素子集。

---

## 2. API 签名

```cpp
Reg::Cast<DstType, SrcType, CastTrait>(dstReg, srcReg, maskReg);
```

| 参数 | 说明 |
|-----------|-------------|
| `DstType` | 目标元素类型（如 `float`、`bfloat16_t`、`half`） |
| `SrcType` | 源元素类型（如 `uint8_t`、`bfloat16_t`、`float`） |
| `CastTrait` | 静态特性，定义布局、饱和模式、掩码合并模式、舍入方式 |
| `dstReg` | 目标 `RegTensor` |
| `srcReg` | 源 `RegTensor` |
| `maskReg` | 控制哪些元素被处理的掩码 |

---

## 3. 多布局行为

### 3.1 Layout 定义

| Layout | 选中的下标 | 模式 | 典型用途 |
|--------|-----------------|---------|-------------|
| `ZERO` | 0, 2, 4, 6, ... | 偶数下标 | 拆分数据的前半部分 |
| `ONE` | 1, 3, 5, 7, ... | 奇数下标 | 拆分数据的后半部分 |
| `TWO` | 2, 6, 10, 14, ... | 4k+2 | 4-layout Cast 的第三组 |
| `THREE` | 3, 7, 11, 15, ... | 4k+3 | 4-layout Cast 的第四组 |
| `UNKNOWN` | 每个元素的低半部分 | 16bit 的低 4bit | FP4 解码（文档提及，见下方注释） |

**关键规则**：多布局 Cast 将 N 个源元素分散到 M 个目标寄存器中。没有 `Interleave` 时，每个寄存器中的数据**不是顺序的**。

**关于 UNKNOWN layout**：部分硬件文档提到 `UNKNOWN` layout 用于提取每个 16-bit 元素的低 4 位（用于 FP4 解码）。但在参考算子（`AntiMxQuant`）中，FP4 解码是通过 `LoadAlign` 配合 `DIST_UNPACK4_B8`，然后使用 `ZERO` layout 的 `Cast` 实现的（见第 4.2 节和 `INDEX.md` 模式 1.4）。`UNKNOWN` layout 的行为可能因芯片代际而异——优先使用 `DIST_UNPACK4_B8 + ZERO`（若可用）。

### 3.2 图示：2-Layout Cast（1B → 2B 通用模式）

```
Source (256 elements, 1 byte each):  [b0, b1, b2, b3, ..., b254, b255]

Cast ZERO:  vdDst_0 = [cast(b0), cast(b2), cast(b4), ..., cast(b254)]
Cast ONE:   vdDst_1 = [cast(b1), cast(b3), cast(b5), ..., cast(b255)]

After Interleave(vdDst_0, vdDst_1):
vdDst_0 = [cast(b0), cast(b1), ..., cast(b127)]  // 顺序
vdDst_1 = [cast(b128), cast(b129), ..., cast(b255)]  // 顺序
```

**重要（FP8_E8M0）**：此通用 ZERO/ONE 模式不适用于 FP8_E8M0 → BF16。FP8_E8M0 使用不同流水线：先 Interleave-with-zero，然后每半寄存器只用 ZERO layout。详见 Section 7.6 和 INDEX.md 模式 1.5/1.6。

### 3.3 图示：4-Layout Cast（256 FP8 → 4 FP32）

```
Source (256 FP8 per register, 2 registers = 512 values):

Cast ZERO:   vd_0 = [v0, v4, v8, ..., v508]
Cast ONE:    vd_1 = [v1, v5, v9, ..., v509]
Cast TWO:    vd_2 = [v2, v6, v10, ..., v510]
Cast THREE:  vd_3 = [v3, v7, v11, ..., v511]

After 1st Interleave (cross-pair 0+2, 1+3):
vd_0 = [v0, v2, v4, ..., v254]   (前半部分偶数)
vd_1 = [v1, v3, v5, ..., v255]   (前半部分奇数)
vd_2 = [v256, v258, ..., v510]   (后半部分偶数)
vd_3 = [v257, v259, ..., v511]   (后半部分奇数)

After 2nd Interleave (0+1, 2+3) — FP32 路径：
vd_0 = [v0..v63], vd_1 = [v64..v127]
vd_2 = [v128..v191], vd_3 = [v192..v255]
```

---

## 4. 类型转换寄存器扩展矩阵

### 4.1 标准转换

| 转换 | 源寄存器数 | 目标寄存器数 | 所需 Layout | 目标容量 |
|------------|--------------|---------------|----------------|---------------|
| FP8_E8M0 → BF16 | 1 (256 bytes) | 2 (128 bf16) | 仅 ZERO（需先 Interleave-with-zero） | 256 bf16 |
| BF16 → FP32 | 1 (128 bf16) | 2 (64 float) | ZERO, ONE | 128 float |
| FP8 → FP32 | 2 (128 fp8 each) | 4 (64 float) | ZERO, ONE, TWO, THREE | 256 float |
| FP32 → BF16 | 1 (64 float) | 2 (64 bf16 total) | ZERO, ONE + ZEROING | 64 bf16 |
| FP32 → FP16 | 1 (64 float) | 2 (64 fp16 total) | ZERO, ONE + ZEROING | 64 fp16 |
| BF16 → FP32 | 1 (128 bf16) | 2 (64 float) | ZERO, ONE | 128 float |
| BF16 → FP16 | 1 (128 bf16) | 1 (128 fp16) | ZERO (单) | 128 fp16 |

### 4.2 特殊转换

| 转换 | 源寄存器数 | 目标寄存器数 | Layout | 说明 |
|------------|--------------|---------------|--------|-------|
| FP4 → BF16 (硬件解包) | 1 (256 bytes unpacked) | 1 (128 bf16) | ZERO | 配合 `LoadAlign<DIST_UNPACK4_B8>`；硬件处理解包 |
| FP4 → BF16 (手动) | 1 (256 bytes) | 1 + shift/interleave | ZERO | `Interleave(data,zero) → Cast low → ShiftRights(4) → Cast high → Interleave merge` |
| FP8_E8M0 → BF16 | 1 (256 bytes) | 2 (128 bf16) | 仅 ZERO | 需 Interleave-with-zero 预处理；源类型必须是 `fp8_e8m0_t` |

---

## 5. CastTrait 声明

### 5.1 基本模式

```cpp
static constexpr AscendC::Reg::CastTrait castTraitName = {
    AscendC::Reg::RegLayout::ZERO,           // 布局选择
    AscendC::Reg::SatMode::UNKNOWN,          // 饱和模式
    AscendC::Reg::MaskMergeMode::ZEROING,    // 掩码合并模式
    AscendC::RoundMode::UNKNOWN};       // 舍入模式
```

### 5.2 2-Layout 对（最常用）

```cpp
// 用于拆分为 2 个目标寄存器的转换
static constexpr AscendC::Reg::CastTrait castTrait_0 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN};

static constexpr AscendC::Reg::CastTrait castTrait_1 = {
    AscendC::Reg::RegLayout::ONE,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN};
```

### 5.3 4-Layout 集合

```cpp
// 用于 FP8 → FP32（1 字节 → 4 字节，256 元素 → 4 个寄存器）
static constexpr AscendC::Reg::CastTrait castTrait_0 = {
    AscendC::Reg::RegLayout::ZERO, ...};
static constexpr AscendC::Reg::CastTrait castTrait_1 = {
    AscendC::Reg::RegLayout::ONE, ...};
static constexpr AscendC::Reg::CastTrait castTrait_2 = {
    AscendC::Reg::RegLayout::TWO, ...};
static constexpr AscendC::Reg::CastTrait castTrait_3 = {
    AscendC::Reg::RegLayout::THREE, ...};
```

### 5.4 单 Layout（不拆分）

```cpp
// 用于同宽或不拆分的转换
static constexpr AscendC::Reg::CastTrait castTraitSingle = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT};
```

### 5.5 UNKNOWN Layout（FP4 — 文档提及但芯片相关）

```cpp
// 部分文档提到 UNKNOWN 用于低 4bit 提取。
// 在支持 DIST_UNPACK4_B8 的芯片上，改用 ZERO layout。
static constexpr AscendC::Reg::CastTrait castTraitFp4ToBf16 = {
    AscendC::Reg::RegLayout::ZERO,  // 不是 UNKNOWN — 见下方注释
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN};
```

**重要**：参考算子（`AntiMxQuant`）对 FP4→BF16 的 Cast 使用 `ZERO` layout（而非 `UNKNOWN`）。前置的 `LoadAlign` 配合 `DIST_UNPACK4_B8` 重新排列了打包字节，使 `ZERO` layout 能正确寻址每个 FP4 值。不要假设 `UNKNOWN` 是必需的或可用的——请先检查芯片的 LoadDist 支持。

### 5.6 FP4 解码 Trait（硬件解包路径）

```cpp
// 用于 LoadAlign<uint8_t, ..., DIST_UNPACK4_B8> 之后
// 解包的 LoadDist 将每个 FP4 值放到正确位置，
// 使 ZERO-layout Cast 能提取并转换它。
static constexpr AscendC::Reg::CastTrait castTraitFp4ToBf16_hw = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN};
```

---

## 6. 关键规则：ZEROING 掩码

**对于多布局 Cast 到同一目标寄存器，`MaskMergeMode::ZEROING` 是必需的。**

没有 ZEROING：
```cpp
// 错误：MaskMergeMode::MERGE 在未写入槽位保留旧数据
// Cast ZERO 写入偶数槽位，但奇数槽位保留垃圾值
// Cast ONE 写入奇数槽位，但偶数槽位保留垃圾值
```

使用 ZEROING：
```cpp
// 正确：MaskMergeMode::ZEROING 将未写入槽位清零为 0
// Cast ZERO：偶数槽位 = 转换值，奇数槽位 = 0
// Cast ONE：奇数槽位 = 转换值，偶数槽位 = 0
// After Add：两部分合并为完整数据
```

这对 BF16/FP16 输出路径中使用的 **Cast + Add** 模式至关重要。

---

## 7. 单指令使用示例

### 7.1 BF16 → FP32（2-layout）

```cpp
Reg::Cast<float, bfloat16_t, castTrait_0>(vdFp32_0, vdBf16, mask);
Reg::Cast<float, bfloat16_t, castTrait_1>(vdFp32_1, vdBf16, mask);
// vdFp32_0 = [偶数 bf16 转 float], vdFp32_1 = [奇数 bf16 转 float]
```

### 7.2 FP32 → BF16（2-layout 配合 ZEROING）

```cpp
Reg::Cast<bfloat16_t, float, castTrait_0>(vdBf16_z, vdFp32, mask);
Reg::Cast<bfloat16_t, float, castTrait_1>(vdBf16_o, vdFp32, mask);
Reg::Add(vdBf16_z, vdBf16_z, vdBf16_o, mask);
// vdBf16_z = [全部 64 个 bf16 值，顺序]
```

### 7.3 FP8 → FP32（4-layout）

```cpp
Reg::Cast<float, fp8_e4m3fn_t, trait_0>(vd_0, vdFp8, mask);
Reg::Cast<float, fp8_e4m3fn_t, trait_1>(vd_1, vdFp8, mask);
Reg::Cast<float, fp8_e4m3fn_t, trait_2>(vd_2, vdFp8, mask);
Reg::Cast<float, fp8_e4m3fn_t, trait_3>(vd_3, vdFp8, mask);
// 每个 vd 持有每第 4 个元素：_0=[0,4,8...], _1=[1,5,9...], 等等
```

### 7.4 FP4 → BF16（硬件解包路径）

```cpp
// LoadAlign 配合 DIST_UNPACK4_B8 后：硬件解包 FP4 字节
Reg::LoadAlign<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE,
               Reg::LoadDist::DIST_UNPACK4_B8>(vdFp4U8, xLocalAddr, vfLen32);

// 使用 ZERO layout 将每个 FP4 值转换为 BF16
Reg::Cast<bfloat16_t, fp4x2_e2m1_t, castTraitFp4ToBf16>(
    vdBf16, (Reg::RegTensor<fp4x2_e2m1_t>&)vdFp4U8, maskU8);
// vdBf16 现在持有 128 个顺序 BF16 值，从 64 个 FP4 字节解码而来
```

### 7.5 FP4 → BF16（手动解码路径 — 无硬件解包）

```cpp
// 当 DIST_UNPACK4_B8 不可用时，使用手动流水线：
Reg::Interleave(vdInter0, vdInter1, vdFp4U8, vdZero);  // data 作为 Src0
Reg::Cast<bfloat16_t, uint16_t, castTraitFp4Manual>(
    vdLow, (uint16_t&)vdInter0, mask);  // 每个 uint16 的低 4bit
Reg::ShiftRights((uint16_t&)vdInter0, (uint16_t&)vdInter0, 4, mask);
Reg::Cast<bfloat16_t, uint16_t, castTraitFp4Manual>(
    vdHigh, (uint16_t&)vdInter0, mask);  // 高 4bit（现在位于低位置）
Reg::Interleave(vdMerged0, vdMerged1, vdLow, vdHigh);  // 恢复顺序
```

---

## 8. 常见陷阱

### 8.1 多布局 Cast + Add 缺少 ZEROING

```cpp
// 错误：MERGE 模式 → 数据损坏
static constexpr auto traitBad = {
    RegLayout::ZERO, SatMode::UNKNOWN,
    MaskMergeMode::MERGE, RoundMode::UNKNOWN};

// 正确：ZEROING 模式 → 干净合并
static constexpr auto traitGood = {
    RegLayout::ZERO, SatMode::UNKNOWN,
    MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
```

### 8.2 FP8_E8M0 源类型错误

```cpp
// 错误：uint8_t 让 Cast 执行整数→浮点转换，而非 FP8 解码
Reg::Cast<bfloat16_t, uint8_t, trait>(vdDst, vdSrc, mask);
// 产生错误值！硬件将位模式解释为无符号整数，
// 而非 FP8_E8M0 纯指数格式。

// 正确：使用 fp8_e8m0_t 让 Cast 正确解析 E8M0 位模式
Reg::Cast<bfloat16_t, fp8_e8m0_t, castTraitFp8E8M0ToBf16_0>(
    vdDst, (RegTensor<fp8_e8m0_t>&)vdSrc, mask);
// 寄存器引用转换 (RegTensor<fp8_e8m0_t>&) 是必须的，
// 因为源数据通常以 uint8_t 加载，然后重新解释。
```

**完整正确流水线**（见 INDEX.md 模式 1.5/1.6）：
```cpp
// 1. 以 uint8 加载
RegTensor<uint8_t> vdScale, vdScaleHalf, vdZero;
Reg::LoadAlign<uint8_t, PostLiteral::POST_MODE_UPDATE>(vdScale, addr, VF_LEN_8);

// 2. Interleave with zero（将每字节定位到 16-bit slot）
Reg::Duplicate(vdZero, static_cast<uint8_t>(0));
Reg::Interleave(vdScale, vdScaleHalf, vdScale, vdZero);

// 3. 以 fp8_e8m0_t 源类型和 ZERO layout Cast
Reg::Cast<bfloat16_t, fp8_e8m0_t, castTraitFp8E8M0ToBf16_0>(
    vdBf16_0, (RegTensor<fp8_e8m0_t>&)vdScale, maskU8);
Reg::Cast<bfloat16_t, fp8_e8m0_t, castTraitFp8E8M0ToBf16_0>(
    vdBf16_1, (RegTensor<fp8_e8m0_t>&)vdScaleHalf, maskU8);
```

### 8.3 未做 Interleave 就期望顺序输出

```cpp
// 错误：多布局 Cast 后每个寄存器是非顺序的
Reg::Cast<float, fp8_e4m3fn_t, trait_0>(vdA, vdSrc, mask);
Reg::Cast<float, fp8_e4m3fn_t, trait_1>(vdB, vdSrc, mask);
Store(addr, vdA);  // 只有原始偶数下标元素！
Store(addr, vdB);  // 只有原始奇数下标元素！

// 正确：Interleave 恢复顺序
Reg::Interleave(vdA, vdB, vdA, vdB);
Store(addr, vdA);  // 顺序 [0..63]
Store(addr, vdB);  // 顺序 [64..127]
```

**例外**：FP8_E8M0 → BF16 使用 Interleave-with-zero 预处理（模式 1.5/1.6）后输出已经是顺序的，不需要 Cast 后再 Interleave。

### 8.4 使用 Pack 代替 Cast + Add

```cpp
// 错误：Pack 只保留每个元素的低半部分
Reg::Pack(vdDst, vdSrc0, vdSrc1);

// 正确：多布局 Cast + Add 保留所有数据
Reg::Cast<DstType, SrcType, trait_0>(vdEven, vdSrc, mask);
Reg::Cast<DstType, SrcType, trait_1>(vdOdd, vdSrc, mask);
Reg::Add(vdEven, vdEven, vdOdd, mask);
```

---

## 9. 相关模式

见 `INDEX.md` 了解使用 Cast 的组合模式：
- **模式 1.1**：完全顺序恢复（4-layout → FP32）
- **模式 1.2**：多布局 Cast + Add（→ BF16/FP16）
- **模式 1.3**：FP4 解码流水线（手动，无 DIST_UNPACK4_B8）
- **模式 1.4**：FP4 快速解码（DIST_UNPACK4_B8 + Cast）
- **模式 1.5**：Scale 预处理（FP8_E8M0 → BF16 → FP32）
- **模式 1.6**：Scale 预处理（FP8_E8M0 → BF16 only）
