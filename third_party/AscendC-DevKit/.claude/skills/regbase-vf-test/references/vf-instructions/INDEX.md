# AscendC VF 指令与编排指南

> **概述**：单条 VF 指令（`Cast`、`Interleave`、`LoadAlign`、`StoreAlign`、`Duplicate`、`ShiftRights`、`Pack`、`Add`、`Mul` 等）及其组合模式，用于数据布局变换与类型转换。在设计和调试 AscendC Kernel 的 VF 流水线时使用。

**目录结构**：
- [`INDEX.md`](./INDEX.md) — 本文件。组合模式、使用场景、决策树、常见陷阱、速查表和扩展指南。
- [`ub-basics.md`](./ub-basics.md) — UB 基础知识：内存层级、32B 对齐、DataCopyPad 1D/2D 搬运、各芯片 UB 大小及分配策略。
- [`cast.md`](./cast.md) — `Reg::Cast` 指令：多布局语义、类型转换矩阵、CastTrait 声明及单指令用法。
- [`interleave.md`](./interleave.md) — `Reg::Interleave` 指令：API 语义、粒度控制、参数顺序、自交错及单指令用法。
- [`load-align.md`](./load-align.md) — `Reg::LoadAlign` 指令：单/双寄存器加载、PostLiteral 模式、LoadDist 广播/解交错/解包模式。
- [`store-align.md`](./store-align.md) — `Reg::StoreAlign` 指令：存储模式、StoreDist 模式、掩码用法及对齐要求。
- [`mask-model.md`](./mask-model.md) — Mask 模型：CreateMask/UpdateMask/MaskPattern/MaskMergeMode 的行为原理、粒度对齐、6 个真实场景 + 6 类陷阱。
- [`localmembar.md`](./localmembar.md) — VF 内流水线同步屏障：RAW/WAR/WAW 三种依赖模型、4 种真实组合选型、7 个真实场景（norm/量化/Softmax）+ 6 类陷阱。

*（未来新增指令：在本目录下创建 `{instruction}.md`，并在 INDEX.md 第1节和决策树中引用。）*

---

## 0. 命名空间约定

本知识库统一使用 `AscendC::Reg::` 命名空间前缀（因为 ops-nn 主流代码采用此写法，使用量 18608 vs `Reg::` 1426）。

**重要**：`AscendC::Reg::` 与 `AscendC::Reg::` 是**同一套 API 的两个等价命名**，可能在同一文件内混用。读代码时二者可互相替换，写代码时推荐用 `Reg::`。

涉及的类型/枚举同样适用：
- `RegTensor<T>` / `MaskReg` / `AddrReg`
- `CastTrait` / `RegLayout` / `SatMode` / `MaskMergeMode` / `RoundMode`
- `LoadDist` / `StoreDist` / `PostLiteral` / `MaskPattern` / `HighLowPart`
- `MemType` / `SpecialPurposeReg` / `GatherMaskMode` / `DataCopyMode`

---

## 0.5 引用协议速查（供 S2 填 coding_index.md 使用）

> **适用性**：本协议（`api:` / `vf-instructions:` / `pattern-X.Y` / `a5-api:`）面向 **SIMD Reg VF**。**SIMT VF（`__simt_vf__`）** 的编程参考自成体系，位于 `references/simt/`（`INDEX.md` 导航：编程模型/内存 8KB 窗口/同步/坑位/样例），引用前缀建议用 `simt:`（如 `simt:simt-sync`）。

s2-analysis 在 `coding_index.md` 的"知识/经验"列填入引用时，按**三前缀分工**：

### 类型 A：简单指令 → 用 `api:{函数名}`（指向官方文档）

官方 `ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/**/{函数名}.md` 已充分说明的指令，直接引用：

- **基础算术**：Add, Sub, Mul, Div, Mull, Adds, Muls, Maxs, Mins, Max, Min
- **一元数学**：Abs, Neg, Sqrt, Exp, Log, Ln, Log2, Log10, Relu, LeakyRelu, Prelu
- **逻辑运算**：And, Or, Xor, Not
- **位移**：ShiftLeft, ShiftRight, ShiftLefts, ShiftRights
- **复合计算**：Axpy, MulAddDst, MulDstAdd, AbsSub, ExpSub, MulsCast
- **单指令类型转换**：Truncate
- **广播/复制**：Duplicate, Copy, Move
- **打包/解包（简单场景）**：Pack, UnPack
- **归约**：Reduce, PairReduceElem, ReduceDataBlock
- **比较/选择**：Compare, Compares, Select, Squeeze
- **索引**：Arange
- **离散聚合**：Gather, GatherB, Scatter
- **系统变量**：ClearSpr, GetSpr

**举例**：`api:Muls` `api:Exp` `api:Duplicate`

### 类型 B：深度指令 → 用 `vf-instructions:{文件名}`（指向本目录）

有 Layout 语义、多参数组合、配对陷阱、量化场景反推的指令，需要图示 + 原理讲解：

| 场景 | 前缀 | 状态 |
|---|---|---|
| Cast 多布局 + CastTrait | `vf-instructions:cast` | ✅ 已有 |
| Interleave 粒度 + Src/Dst 顺序 | `vf-instructions:interleave` | ✅ 已有 |
| LoadAlign + LoadDist 分发模式 | `vf-instructions:load-align` | ✅ 已有 |
| StoreAlign + StoreDist 分发模式 | `vf-instructions:store-align` | ✅ 已有 |
| CreateMask + UpdateMask + MaskMergeMode + 粒度 | `vf-instructions:mask-model` | ✅ 已有 |
| LocalMemBar VF 内同步屏障 | `vf-instructions:localmembar` | ✅ 已有 |

**举例**：`vf-instructions:cast` `vf-instructions:mask-model#粒度` `vf-instructions:localmembar#raw`

**深度指令支持 `#锚点` 精准触发**（详见对应文档的 § 引用协议节）。

### 类型 C：组合模式 → 用 `vf-instructions:pattern-{X.Y}`（指向本文档 §1）

多条指令编排的流水线级场景（FP8/FP4 反量化、Softmax、norm、量化等）：

- **1.x** = FP8/FP4 反量化（已有 1.1~1.7）
- **2.x** = element-wise + DAG 编排（待建）
- **3.x** = Reduce+Broadcast（RmsNorm/LayerNorm，待建）
- **4.x** = Softmax 3-pass（待建）
- **5.x** = int8/int32 反量化（待建）
- **6.x** = Dynamic quantization（待建）
- **7.x** = MX quant（Pack+Cast 组合，待建）
- **8.x** = 非对齐搬运 pipeline（待建）
- **9.x** = Gather 索引流水线（待建）
- **10.x** = GatherMask 压缩输出（待建）
- **11.x** = Bitmask 累积（Pooling/Argmax，待建）
- **12.x** = 多 pass + LocalMemBar（待建）

**举例**：`vf-instructions:pattern-1.5`

### 类型 D：A5 增强 API → 用 `a5-api:{函数名}`（指向 `a5-api-enhanced/`）

需要**完整调用示例/参数约束**的单 API 用法（`regbase-vf-test/references/a5-api-enhanced/{函数名}.md`，72 个，见 SKILL.md §5.5）——比官方 `api:` 更具体（官方是签名、增强文档是含可编译示例的用法），A5 Regbase 编码优先查增强文档，找不到再回退官方 `api:`。

- 与 `api:` 的区别：`api:` → 官方签名；`a5-api:` → 增强文档（调用示例/约束/陷阱，A5 实测验证）
- 仅 A5 Regbase 使用（`programming_model == A5`）

**举例**：`a5-api:Gather` `a5-api:Interleave` `a5-api:DeInterleave`

### S2 判断口诀

1. **先看是否有 Pattern 匹配**（多指令流水线场景）→ 优先用 `vf-instructions:pattern-X.Y`
2. **再看单指令类别**：简单指令 → `api:`；深度指令 → `vf-instructions:{文件名}`；**需要调用示例/参数约束的 A5 指令 → `a5-api:{函数名}`**（增强文档优先于官方 `api:`）
3. **Pattern 和单指令可以叠加**（反量化算子的 C.3 行可能同时填 3~4 个引用）

### S4 解析动作

- `api:{函数名}` → Read `ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/**/{函数名}.md`
- `a5-api:{函数名}` → Read `$SKILL_ROOT/references/a5-api-enhanced/{函数名}.md`（无对应文件则回退 `api:{函数名}` 官方签名，并记录 `CTX_DRIFT:minor`）
- `vf-instructions:{文件名}` → Read `{文件名}.md`
- `vf-instructions:{文件名}#{锚点}` → Read `{文件名}.md` 并定位到锚点章节
- `vf-instructions:pattern-{X.Y}` → Read `INDEX.md` 定位 §Pattern X.Y

---


## 1. 组合模式

本节涵盖多条 VF 指令的编排序列。

### 1.1 模式：完全顺序恢复（4-layout Cast → FP32）

**目标**：将 FP8（4-layout）转换为完全顺序的 FP32 输出。

**数据流**：
```
256 FP8 → Cast×4 → [0,4,8...] [1,5,9...] [2,6,10...] [3,7,11...]
         → Mul(scale)
         → Interleave(0+2, 1+3) → [0,2,4...] [1,3,5...] [128,130...] [129,131...]
         → Interleave(0+1, 2+3) → [0..63] [64..127] [128..191] [192..255]
         → Store (sequential)
```

**代码**：
```cpp
// Cast (4 layouts)
Reg::Cast<float, T, trait_0>(vd_0_0, vdFp8_0, mask);
Reg::Cast<float, T, trait_1>(vd_0_1, vdFp8_0, mask);
Reg::Cast<float, T, trait_2>(vd_0_2, vdFp8_0, mask);
Reg::Cast<float, T, trait_3>(vd_0_3, vdFp8_0, mask);
// ... same for vdFp8_1

// Mul with scale (DIST_E2B_B32 broadcast)
// ...

// 第一级 Interleave: cross-pair (0+2, 1+3)
Reg::Interleave(vd_0_0, vd_0_2, vd_0_0, vd_0_2);
Reg::Interleave(vd_0_1, vd_0_3, vd_0_1, vd_0_3);
Reg::Interleave(vd_1_0, vd_1_2, vd_1_0, vd_1_2);
Reg::Interleave(vd_1_1, vd_1_3, vd_1_1, vd_1_3);

// 第二级 Interleave: (0+1, 2+3) — 仅 FP32 输出路径
Reg::Interleave(vd_0_0, vd_0_1, vd_0_0, vd_0_1);
Reg::Interleave(vd_0_2, vd_0_3, vd_0_2, vd_0_3);
Reg::Interleave(vd_1_0, vd_1_1, vd_1_0, vd_1_1);
Reg::Interleave(vd_1_2, vd_1_3, vd_1_2, vd_1_3);

// 顺序存储
Store(yAddr, vd_0_0);  // [0..63]
Store(yAddr, vd_0_1);  // [64..127]
Store(yAddr, vd_0_2);  // [128..191]
Store(yAddr, vd_0_3);  // [192..255]
```

**相关文件**：`cast.md`（多 layout Cast）、`interleave.md`（两级 Interleave）

---

### 1.2 模式：多布局 Cast + Add（4-layout → BF16/FP16）

**目标**：将 FP8（4-layout）转换为 BF16 或 FP16，无需完全 Interleave 恢复。

**核心思路**：第一级 cross-pair Interleave 后，偶数和奇数下标分别位于不同寄存器中。使用 ZERO/ONE Cast 配合 ZEROING 掩码 + Add 合并。

**第一级 Interleave 后的数据流**：
- `vd_0_0 = [val0, val2, val4, ...]`（偶数下标）
- `vd_0_1 = [val1, val3, val5, ...]`（奇数下标）

**代码**：
```cpp
// 第一级 Interleave (cross-pair)
Reg::Interleave(vd_0_0, vd_0_2, vd_0_0, vd_0_2);
Reg::Interleave(vd_0_1, vd_0_3, vd_0_1, vd_0_3);

// 不做第二级 Interleave！
// 使用独立的寄存器对以最大化 ILP
Reg::RegTensor<bfloat16_t> vdZ0, vdO0, vdZ1, vdO1;

// Group 0: _0_0(偶数下标) + _0_1(奇数下标)
Reg::Cast<bf16, float, trait_0>(vdZ0, vd_0_0, mask);  // ZERO → 偶数槽位
Reg::Cast<bf16, float, trait_1>(vdO0, vd_0_1, mask);  // ONE → 奇数槽位
Reg::Add(vdZ0, vdZ0, vdO0, mask);  // 合并 → 顺序 bf16[0..127]
Store(yAddr, vdZ0);

// Group 1: _0_2 + _0_3
Reg::Cast<bf16, float, trait_0>(vdZ1, vd_0_2, mask);
Reg::Cast<bf16, float, trait_1>(vdO1, vd_0_3, mask);
Reg::Add(vdZ1, vdZ1, vdO1, mask);  // 合并 → 顺序 bf16[128..255]
Store(yAddr, vdZ1);
```

**原理**：ZERO layout 配合 ZEROING 掩码只写入偶数输出槽位，奇数槽位为 0。ONE layout 只写入奇数槽位。Add 将两者合并为完整的顺序寄存器。

**相关文件**：`cast.md`（ZERO/ONE Cast 配合 ZEROING）、`interleave.md`（第一级 cross-pair Interleave）

---

### 1.3 模式：FP4 解码流水线（手动）

**目标**：将 FP4 原始字节（每字节2个值）解码为顺序的 BF16 值。

**流水线**：Interleave → Cast low → ShiftRights → Cast high → Interleave merge

**数据流**：
```
256 bytes = 512 FP4 values
Interleave(data, zero) → [b0,0, b1,0, ...]
Cast low → vdLow = [fp4_0, fp4_2, fp4_4, ...]  (每个 uint16 的低 4bit)
ShiftRights(4) → [b0>>4, 0, b1>>4, 0, ...]
Cast high → vdHigh = [fp4_1, fp4_3, fp4_5, ...]
Interleave(vdLow, vdHigh) → [fp4_0, fp4_1, fp4_2, fp4_3, ...]
```

**代码**：
```cpp
Reg::LoadAlign<uint8_t>(vdFp4U8, xAddr, vfLen8);

// Step 1: Interleave with zero（data 必须是 Src0 才能到低字节位置）
Reg::Interleave(vdInter0, vdInter1, vdFp4U8, vdZero);

// Step 2: Cast low 4bit（UNKNOWN layout 取每个 16bit 的低 4bit）
Reg::Cast<bf16, uint16_t, traitFp4>(vdLow0, (uint16_t&)vdInter0, mask);
Reg::Cast<bf16, uint16_t, traitFp4>(vdLow1, (uint16_t&)vdInter1, mask);

// Step 3: 右移 4 位，将高 4bit 移到低位置
Reg::ShiftRights((uint16_t&)vdInter0, (uint16_t&)vdInter0, 4, maskAll);
Reg::ShiftRights((uint16_t&)vdInter1, (uint16_t&)vdInter1, 4, maskAll);

// Step 4: Cast high 4bit（现在位于低位置）
Reg::Cast<bf16, uint16_t, traitFp4>(vdHigh0, (uint16_t&)vdInter0, mask);
Reg::Cast<bf16, uint16_t, traitFp4>(vdHigh1, (uint16_t&)vdInter1, mask);

// Step 5: Interleave 恢复原始顺序
Reg::Interleave(vdMerged0, vdMerged1, vdLow0, vdHigh0);
Reg::Interleave(vdMerged2, vdMerged3, vdLow1, vdHigh1);
```

**Interleave 后的数据布局**：
```
vdMerged0: bf16[  0 .. 127]  <- FP4 values [  0 .. 127] (blocks 0..3)
vdMerged1: bf16[128 .. 255]  <- FP4 values [128 .. 255] (blocks 4..7)
vdMerged2: bf16[256 .. 383]  <- FP4 values [256 .. 383] (blocks 8..11)
vdMerged3: bf16[384 .. 511]  <- FP4 values [384 .. 511] (blocks 12..15)
```

**相关文件**：`interleave.md`（Interleave 参数顺序、Src0/Src1）、`cast.md`（ZERO layout Cast）

**注意**：这是 `DIST_UNPACK4_B8` 不可用时的人工回退方案。在支持 `DIST_UNPACK4_B8` 的芯片上，请使用 **模式 1.4**。

---

### 1.4 模式：FP4 快速解码（DIST_UNPACK4_B8 + Cast）

**目标**：使用硬件解包支持将 FP4 原始字节解码为 BF16。

**前提**：芯片支持 `LoadDist::DIST_UNPACK4_B8`。

**数据流**：
```
64 FP4 bytes → LoadAlign(DIST_UNPACK4_B8) → sparse 256B layout
             → Cast(ZERO layout) → 128 BF16 values
```

**代码**：
```cpp
// Step 1: 加载并解包 FP4 字节（硬件扩展打包字节）
Reg::LoadAlign<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE,
               Reg::LoadDist::DIST_UNPACK4_B8>(
    vdFp4U8_0, xLocalAddr, vfLen32);  // 64 bytes → 256B register layout

// Step 2: 直接 Cast 为 BF16（ZERO layout 寻址每个 FP4 值）
Reg::Cast<bfloat16_t, fp4x2_e2m1_t, castTraitFp4ToBf16>(
    vdMerged0, (Reg::RegTensor<fp4x2_e2m1_t>&)vdFp4U8_0, maskU8);
// vdMerged0 现在持有 128 个顺序 BF16 值
```

**Cast 后的数据布局**：
```
vdMerged0: bf16[  0 .. 127]  <- FP4 values [  0 .. 127] (blocks 0..3)
vdMerged1: bf16[128 .. 255]  <- FP4 values [128 .. 255] (blocks 4..7)
vdMerged2: bf16[256 .. 383]  <- FP4 values [256 .. 383] (blocks 8..11)
vdMerged3: bf16[384 .. 511]  <- FP4 values [384 .. 511] (blocks 12..15)
```

**相比模式 1.3 的优势**：无需 Interleave、ShiftRights 或第二次 Cast。2 条指令代替 6+ 条。

**相关文件**：`load-align.md`（DIST_UNPACK4_B8）、`cast.md`（ZERO layout for FP4）

---

### 1.5 模式：Scale 预处理（FP8_E8M0 → BF16 → FP32）

**目标**：将 mxscale 从 FP8_E8M0 转换为 FP32，用于反量化。

**关键**：源类型必须是 `fp8_e8m0_t`（不是 `uint8_t`）。Cast 指令需要根据类型正确解析 E8M0 位模式。使用 `uint8_t` 会导致整数转浮点，而非正确的 FP8_E8M0 解码。

**代码**：
```cpp
// CastTrait: 只需 ZERO layout（Interleave-with-zero 预处理后无需 ZERO/ONE 对）
static constexpr CastTrait castTraitFp8E8M0ToBf16_0 = {
    RegLayout::ZERO, SatMode::UNKNOWN, MaskMergeMode::ZEROING, RoundMode::UNKNOWN};

// Step 1: 加载 256 字节原始数据
RegTensor<uint8_t> vdScale0, vdScale1, vdu8Zero;
Reg::LoadAlign<uint8_t, PostLiteral::POST_MODE_UPDATE>(vdScale0, scaleAddr, VF_LEN_8);

// Step 2: Interleave with zero — 将每字节填充到 16-bit slot
// Before: vdScale0=[b0, b1, ..., b255]
// After:  vdScale0=[b0,0, b1,0, ..., b127,0], vdScale1=[b128,0, ..., b255,0]
Reg::Duplicate(vdu8Zero, static_cast<uint8_t>(0));
Reg::Interleave(vdScale0, vdScale1, vdScale0, vdu8Zero);

// Step 3: Cast FP8_E8M0 → BF16（ZERO layout，源类型为 fp8_e8m0_t）
// 每个半寄存器独立将 128 个 FP8_E8M0 值转为 128 个 BF16
RegTensor<bfloat16_t> vdBf16_0, vdBf16_1;
Reg::Cast<bfloat16_t, fp8_e8m0_t, castTraitFp8E8M0ToBf16_0>(
    vdBf16_0, (RegTensor<fp8_e8m0_t>&)vdScale0, maskU8);
Reg::Cast<bfloat16_t, fp8_e8m0_t, castTraitFp8E8M0ToBf16_0>(
    vdBf16_1, (RegTensor<fp8_e8m0_t>&)vdScale1, maskU8);
// vdBf16_0=[s0..s127], vdBf16_1=[s128..s255] — 已经是顺序的！

// Step 4: BF16 → FP32（标准 2-layout，每 128 bf16 产生 2x64 fp32）
Reg::Cast<float, bfloat16_t, castTraitBf16ToFp32_0>(vdFp32_0_0, vdBf16_0, maskU8);
Reg::Cast<float, bfloat16_t, castTraitBf16ToFp32_1>(vdFp32_0_1, vdBf16_0, maskU8);
Reg::Cast<float, bfloat16_t, castTraitBf16ToFp32_0>(vdFp32_1_0, vdBf16_1, maskU8);
Reg::Cast<float, bfloat16_t, castTraitBf16ToFp32_1>(vdFp32_1_1, vdBf16_1, maskU8);

// Step 5: Interleave 恢复每对 FP32 的顺序
Reg::Interleave(vdFp32_0_0, vdFp32_0_1, vdFp32_0_0, vdFp32_0_1);
Reg::Interleave(vdFp32_1_0, vdFp32_1_1, vdFp32_1_0, vdFp32_1_1);
```

**为何先 Interleave-with-zero**：FP8_E8M0 是单字节格式。Interleave 步骤将每字节填充到 16-bit slot（byte + 0x00），使 Cast 指令可以在 BF16 寄存器粒度下用单个 ZERO layout 操作，无需 ZERO/ONE 对。

**相关文件**：`cast.md`（FP8_E8M0 Cast，Section 4.2 & 7.6）、`interleave.md`（原地 Interleave）

---

### 1.6 模式：Scale 预处理（FP8_E8M0 → BF16 only）

**目标**：将 mxscale 从 FP8_E8M0 转换为 BF16，用于 FP4 反量化。

**关键**：与 Pattern 1.5 相同 — 源类型必须是 `fp8_e8m0_t`，不能用 `uint8_t`。

**代码**：
```cpp
// CastTrait: 只需 ZERO layout
static constexpr CastTrait castTraitFp8E8M0ToBf16_0 = {
    RegLayout::ZERO, SatMode::UNKNOWN, MaskMergeMode::ZEROING, RoundMode::UNKNOWN};

RegTensor<uint8_t> vdScale0, vdScale1, vdu8Zero;
Reg::LoadAlign<uint8_t, PostLiteral::POST_MODE_UPDATE>(vdScale0, scaleAddr, VF_LEN_8);

// Interleave with zero — 将每字节填充到 16-bit slot
Reg::Duplicate(vdu8Zero, static_cast<uint8_t>(0));
Reg::Interleave(vdScale0, vdScale1, vdScale0, vdu8Zero);

// Cast FP8_E8M0 → BF16（ZERO layout，fp8_e8m0_t 源类型）
RegTensor<bfloat16_t> vdBf16_0, vdBf16_1;
Reg::Cast<bfloat16_t, fp8_e8m0_t, castTraitFp8E8M0ToBf16_0>(
    vdBf16_0, (RegTensor<fp8_e8m0_t>&)vdScale0, maskU8);
Reg::Cast<bfloat16_t, fp8_e8m0_t, castTraitFp8E8M0ToBf16_0>(
    vdBf16_1, (RegTensor<fp8_e8m0_t>&)vdScale1, maskU8);

// 直接存储 256 个 BF16 scale（已经是顺序的，不需要 Interleave）
Reg::StoreAlign<bfloat16_t, PostLiteral::POST_MODE_UPDATE>(
    scaleBufAddr, vdBf16_0, VF_LEN_16, storeMask);
Reg::StoreAlign<bfloat16_t, PostLiteral::POST_MODE_UPDATE>(
    scaleBufAddr, vdBf16_1, VF_LEN_16, storeMask);
```

**为何 Cast 后不需要 Interleave**：Interleave-with-zero 步骤已将每个 FP8_E8M0 字节正确定位。ZERO layout Cast 后，BF16 输出在每个寄存器内已经是顺序的 — vdBf16_0 存 [s0..s127]，vdBf16_1 存 [s128..s255]。

**相关文件**：`cast.md`（FP8_E8M0 Cast，Section 4.2 & 7.6）、`interleave.md`（原地 Interleave）、`store-align.md`（StoreAlign）

---

### 1.7 模式：Scale 广播扩展（Self-Interleave）

**目标**：将广播后的 scale 值从 16 次重复块扩展到 32 次重复块，用于 FP4 反量化。

**上下文**：`LoadAlign<DIST_E2B_B16>` 后，每个 scale 占据 16 个连续槽位。FP4 反量化每 block 需要 32 个 scale 重复（每字节 2 个值 × 每 block 16 字节）。Self-Interleave 将 16 次重复块扩展为 32 次重复块。

**数据流**：
```
LoadAlign(DIST_E2B_B16) → [A×16, B×16, C×16, D×16, E×16, F×16, G×16, H×16]
Self-Interleave(src,src)  → [A×32, B×32, C×32, D×32] + [E×32, F×32, G×32, H×32]
```

**代码**：
```cpp
// Step 1: 加载 8 个 BF16 scale，每个广播到 16 个槽位
Reg::LoadAlign<bfloat16_t, Reg::PostLiteral::POST_MODE_UPDATE,
               Reg::LoadDist::DIST_E2B_B16>(
    vdScaleTmp0, scaleBufAddr, elementAfterReduce_);  // 8 scales × 16 reps

// Step 2: Self-Interleave 将重复数翻倍：16 → 32
Reg::Interleave(vdScale0, vdScale1, vdScaleTmp0, vdScaleTmp0);
// vdScale0: 4 scales × 32 reps (covers blocks 0..3, 128 BF16 values)
// vdScale1: 4 scales × 32 reps (covers blocks 4..7, 128 BF16 values)

// Step 3: 与 FP4 解码后的数据相乘
Reg::Mul(vdMerged0, vdMerged0, vdScale0, maskAll16);
Reg::Mul(vdMerged1, vdMerged1, vdScale1, maskAll16);
```

**原理**：当 `src0 == src1` 时，交错相同的元素会合并相邻的相同块。寄存器的前半部分（64 个 BF16 槽位 = 4×16）进入 `dst0` 变为 4×32，后半部分进入 `dst1` 变为 4×32。

**相关文件**：`interleave.md`（Self-Interleave，第 5.6 节）、`load-align.md`（DIST_E2B_B16）

---

## 2. 使用场景速览

### 2.1 UC-1: FP8 反量化 → FP32 输出

**输入**：FP8 张量（每循环 512 个值），FP32 scale（每 block 16 个值）
**输出**：FP32 张量
**流水线**：ComputeScale（模式 1.5）→ ComputeData（模式 1.1）

---

### 2.2 UC-2: FP8 反量化 → BF16 输出

**输入**：FP8 张量，FP32 scale
**输出**：BF16 张量
**流水线**：ComputeScale（模式 1.5）→ ComputeData（模式 1.2）

与 UC-1 的关键区别：不做第二级 Interleave。第一级 cross-pair Interleave 后，使用 ZERO/ONE Cast + Add 合并。

---

### 2.3 UC-3: FP4 反量化 → FP32 输出

**输入**：FP4 原始字节（每循环 256 字节），BF16 scale
**输出**：FP32 张量
**流水线**：ComputeScale（模式 1.6）→ ComputeData（模式 1.4 → Cast BF16→FP32 with multi-layout + Interleave）

FP4 快速解码（模式 1.4）后，BF16 值与 BF16 scale 相乘（模式 1.7 用于广播扩展），然后 Cast 到 FP32 并做 multi-layout + Interleave。

---

### 2.4 UC-4: FP4 反量化 → BF16 输出

**输入**：FP4 原始字节，BF16 scale
**输出**：BF16 张量
**流水线**：ComputeScale（模式 1.6）→ ComputeData（模式 1.4 → Mul → 直接 Store）

快速解码后无需额外 Cast。vdMerged0-3 已经是 BF16。

---

### 2.5 UC-5: FP4 反量化 → FP16 输出

**输入**：FP4 原始字节，BF16 scale
**输出**：FP16 张量
**流水线**：ComputeScale（模式 1.6）→ ComputeData（模式 1.4 → Mul → Cast BF16→FP16 → Store）

Mul 之后单 layout Cast 从 BF16 到 FP16。

---

## 3. 常见陷阱

### 3.1 Pack 丢失数据

```cpp
// 错误
Reg::Pack(vdDst, vdSrc0, vdSrc1);  // 只保留低半部分！

// 正确
Reg::Cast<bf16, float, trait_0>(vdEven, vdSrc, mask);
Reg::Cast<bf16, float, trait_1>(vdOdd, vdSrc, mask);
Reg::Add(vdEven, vdEven, vdOdd, mask);
```

**相关**：`cast.md`（多 layout Cast 配合 ZEROING）

---

### 3.2 多布局 Cast 后忘记 Interleave

```cpp
// 错误：寄存器包含非顺序数据
Reg::Cast<float, fp8_e4m3fn_t, trait_0>(vdA, vdSrc, mask);
Reg::Cast<float, fp8_e4m3fn_t, trait_1>(vdB, vdSrc, mask);
Store(addr, vdA);  // 只有偶数下标
Store(addr, vdB);  // 只有奇数下标

// 正确
Reg::Interleave(vdA, vdB, vdA, vdB);
Store(addr, vdA);  // 顺序 [0..63]
Store(addr, vdB);  // 顺序 [64..127]
```

**注意**：FP8_E8M0 → BF16 使用 Interleave-with-zero 流水线（模式 1.5/1.6）后输出已经是顺序的，不需要 Cast 后再 Interleave。

**相关**：`cast.md`（多布局行为）、`interleave.md`（原地 Interleave）

---

### 3.3 复用寄存器破坏 ILP

```cpp
// 错误：WAW 依赖
Reg::RegTensor<bf16> vdZ, vdO;  // 复用
Reg::Cast(vdZ, ...); Reg::Cast(vdO, ...); Add(vdZ, vdZ, vdO, mask); Store(vdZ);
Reg::Cast(vdZ, ...);  // 必须等待前一条 Add 完成

// 正确：独立寄存器
Reg::RegTensor<bf16> vdZ0, vdO0, vdZ1, vdO1;
Reg::Cast(vdZ0, ...); Reg::Cast(vdO0, ...); Add(vdZ0, vdZ0, vdO0, mask); Store(vdZ0);
Reg::Cast(vdZ1, ...);  // 可与 Add(vdZ0) 并行执行
```

---

### 3.4 Interleave Src0/Src1 顺序错误

```cpp
// 错误：用于 FP4 解码
Reg::Interleave(vdInter0, vdInter1, vdZero, vdFp4U8);
// 结果：uint16[i] = 0 | (byte[i] << 8), low 4bit = 0

// 正确
Reg::Interleave(vdInter0, vdInter1, vdFp4U8, vdZero);
// 结果：uint16[i] = byte[i] | 0, low 4bit = byte[i] & 0xF
```

**相关**：`interleave.md`（参数顺序陷阱）

---

### 3.5 多布局缺少 ZEROING 掩码

```cpp
// 错误
static constexpr auto trait = {
    RegLayout::ZERO,
    SatMode::UNKNOWN,
    MaskMergeMode::MERGE,  // ← 保留旧数据！
    RoundMode::UNKNOWN};

// 正确
static constexpr auto trait = {
    RegLayout::ZERO,
    SatMode::UNKNOWN,
    MaskMergeMode::ZEROING,  // ← 清空未使用槽位
    RoundMode::UNKNOWN};
```

**相关**：`cast.md`（CastTrait 声明）

---

### 3.6 误以为 FP4 必须使用 UNKNOWN Layout

```cpp
// 错误：假设 FP4 必须使用 UNKNOWN layout
static constexpr auto traitFp4 = {
    RegLayout::UNKNOWN,  // 可能不可用或不需要！
    SatMode::UNKNOWN,
    MaskMergeMode::ZEROING,
    RoundMode::UNKNOWN};

// 正确：使用 ZERO layout 配合 DIST_UNPACK4_B8（若可用）
static constexpr auto traitFp4 = {
    RegLayout::ZERO,  // 硬件解包已将数据放到正确位置
    SatMode::UNKNOWN,
    MaskMergeMode::ZEROING,
    RoundMode::UNKNOWN};
// 配合：Reg::LoadAlign<uint8_t, ..., DIST_UNPACK4_B8>(...)
```

**相关**：`cast.md`（FP4 解码 Trait）、`load-align.md`（DIST_UNPACK4_B8）

---

### 3.7 忘记 LoadAlign/StoreAlign 的 PostLiteral

```cpp
// 错误：地址永不前进，每次加载/存储同一位置
for (i = 0; i < loopNum; i++) {
    Reg::LoadAlign<uint8_t, Reg::PostLiteral::POST_MODE_KEEP>(vd, addr, 256);
    // ... compute ...
    Reg::StoreAlign<float, Reg::PostLiteral::POST_MODE_KEEP>(dst, vd, 64, mask);
}

// 正确：地址自动前进
for (i = 0; i < loopNum; i++) {
    Reg::LoadAlign<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(vd, addr, 256);
    // ... compute ...
    Reg::StoreAlign<float, Reg::PostLiteral::POST_MODE_UPDATE>(dst, vd, 64, mask);
}
```

**相关**：`load-align.md`（PostLiteral）、`store-align.md`（PostLiteral）

---

### 3.8 LoadDist/StoreDist 类型不匹配

```cpp
// 错误：对 16-bit 元素使用 DIST_E2B_B32
Reg::LoadAlign<bfloat16_t, ..., DIST_E2B_B32>(vd, addr, 8);

// 正确：LoadDist 与元素宽度匹配
Reg::LoadAlign<bfloat16_t, ..., DIST_E2B_B16>(vd, addr, 8);

// 错误：对 bfloat16_t 存储使用 DIST_NORM_B32
Reg::StoreAlign<bfloat16_t, ..., DIST_NORM_B32>(dst, vd, 128, mask);

// 正确
Reg::StoreAlign<bfloat16_t, ..., DIST_NORM_B16>(dst, vd, 128, mask);
```

**相关**：`load-align.md`（LoadDist 表）、`store-align.md`（StoreDist 表）

---

## 4. 决策树

```
起点：寄存器中有原始数据，需要类型转换或布局变换
│
├─→ 数据是 FP4 打包字节？
│   ├─→ 芯片支持 DIST_UNPACK4_B8？
│   │   └─→ LoadAlign(DIST_UNPACK4_B8) → Cast(ZERO) → Mul → 输出
│   │       └─→ 输出 BF16？直接 Store
│   │       └─→ 输出 FP16？Cast BF16→FP16
│   │       └─→ 输出 FP32？Cast BF16→FP32 with multi-layout + Interleave
│   └─→ 无硬件解包？
│       └─→ Interleave(data, zero) → Cast low → ShiftRights(4) → Cast high → Interleave merge
│           └─→ 输出 BF16？直接 Store
│           └─→ 输出 FP16？Cast BF16→FP16
│           └─→ 输出 FP32？Cast BF16→FP32 with multi-layout + Interleave
│
├─→ 数据是 FP8（单字节每值）？
│   └─→ 需要 scale 预处理？
│       ├─→ Scale 转 FP32：Interleave-with-zero → Cast(fp8_e8m0_t→BF16)×2 → Cast(BF16→FP32)×4 → Interleave×2（模式 1.5）
│       └─→ Scale 转 BF16：Interleave-with-zero → Cast(fp8_e8m0_t→BF16)×2（模式 1.6）
│   └─→ 主反量化：
│       ├─→ Cast×4 (FP8→FP32, ZERO/ONE/TWO/THREE)
│       ├─→ Mul(scale, DIST_E2B_B32)
│       ├─→ Interleave level 1 (cross-pair: 0+2, 1+3)
│       └─→ 输出类型？
│               ├─→ FP32：Interleave level 2 (0+1, 2+3) → 顺序 Store
│               └─→ BF16/FP16：Cast ZERO+ONE + Add → Store（不做 level 2 Interleave！）
│
├─→ 数据是 BF16，需要转换？
│   ├─→ BF16 → FP32：Cast×2 (ZERO/ONE) → Interleave → Store
│   └─→ BF16 → FP16：单 layout Cast
│
├─→ 需要合并拆分的数据？
│   ├─→ 同宽类型？Interleave
│   └─→ 缩窄类型？Multi-layout Cast + Add
│
└─→ 需要拆分偶/奇？
    └─→ Multi-layout Cast（ZERO 取偶，ONE 取奇）
```

---

## 5. 速查表

### 5.1 寄存器容量

| 类型 | 每 256B 寄存器元素数 | 每元素字节数 |
|------|----------------------|-------------|
| uint8_t / fp8 | 256 | 1 |
| uint16_t / bf16 / fp16 | 128 | 2 |
| uint32_t / float | 64 | 4 |
| uint64_t | 32 | 8 |

### 5.2 Cast 寄存器扩展

| 源 | 目标 | 源寄存器数 | 目标寄存器数 | Layout |
|-----|-----|----------|----------|---------|
| 1B | 2B | 1 | 2 | ZERO, ONE |
| 1B | 4B | 1 | 4 | ZERO, ONE, TWO, THREE |
| 2B | 4B | 1 | 2 | ZERO, ONE |
| 4B | 2B | 1 | 2 (共) | ZERO, ONE + ZEROING |
| 4B | 2B | 1 | 1 | ZERO (单) |

### 5.3 Interleave 粒度

| RegTensor 类型 | Interleave 单元 | 每次交换字节数 |
|---------------|-----------------|----------------|
| `uint8_t` | 1 字节 | 1 |
| `uint16_t` | 2 字节 | 2 |
| `uint32_t` / `float` | 4 字节 | 4 |
| `uint64_t` | 8 字节 | 8 |

### 5.4 LoadAlign LoadDist 速查

| LoadDist | 元素类型 | 加载元素数 | 效果 |
|----------|-------------|----------------|--------|
| (无) | Any | `elementNum` | 顺序加载 |
| `DIST_DINTLV_B8` | `uint8_t` | `elementNum` (50/50 分到 2 个寄存器) | 解交错到 2 个寄存器 |
| `DIST_UNPACK4_B8` | `uint8_t` | `elementNum` (解包 4×) | 解包 FP4 字节 |
| `DIST_E2B_B32` | `float` | `elementNum` (广播 ×8) | 广播 float scale |
| `DIST_E2B_B16` | `bfloat16_t` / `half` | `elementNum` (广播 ×16) | 广播 16-bit scale |

### 5.5 StoreAlign StoreDist 速查

| StoreDist | 元素类型 | 用途 |
|-----------|-------------|---------|
| (无) | Any | 默认顺序存储 |
| `DIST_NORM_B32` | `float` | 正常 32-bit 顺序 |
| `DIST_NORM_B16` | `bfloat16_t` / `half` | 正常 16-bit 顺序 |

### 5.6 VF 流水线指令数参考

| 流水线 | 指令数（约） | 关键 VF 操作 |
|----------|----------------------|------------|
| FP8 → FP32 (完整) | 4 Cast + 1 Mul + 8 Interleave + 8 Store | Cast×4, Interleave×2 级 |
| FP8 → BF16 | 4 Cast + 1 Mul + 4 Interleave + 4 Cast(Add) + 4 Store | Cast×4, Interleave L1, Cast+Add×4 |
| FP4 → BF16 (快速) | 1 LoadAlign + 1 Cast + 1 Mul + 1 Store | LoadAlign(DIST_UNPACK4_B8), Cast |
| FP4 → BF16 (手动) | 1 Load + 2 Interleave + 2 Cast + 2 Shift + 2 Interleave + ... | 见模式 1.3 |
| Scale FP8_E8M0 → FP32 | 1 Load + 1 Dup + 1 Interleave + 2 Cast(E8M0→BF16) + 4 Cast(BF16→FP32) + 2 Interleave + 4 Store | 见模式 1.5 |
| Scale FP8_E8M0 → BF16 | 1 Load + 1 Dup + 1 Interleave + 2 Cast(E8M0→BF16) + 2 Store | 见模式 1.6 |

---

## 6. 扩展本 Skill

### 6.1 添加新的 VF 指令

1. 在本目录下创建 `{instruction}.md`
2. 包含：用途、签名、行为、单指令使用场景、陷阱
3. 在 INDEX.md 第1节（指令文件）中添加链接
4. 在相关组合模式中引用
5. 如适用，更新决策树

### 6.2 添加新的组合模式

1. 在 **第1节**（组合模式）下新增子节
2. 包含：目标、数据流图、代码、涉及的指令
3. 引用各单指令文件
4. 如适用，更新决策树和使用场景

### 6.3 新指令文件模板

```markdown
---
name: ascendc-vf-{instruction}-zh
description: AscendC Reg::{Instruction} VF 指令。涵盖 API 语义、使用模式和常见陷阱。
---

# Reg::{Instruction}

## 1. 用途

## 2. API 签名

## 3. 行为

## 4. 使用示例

## 5. 常见陷阱

## 6. 相关模式
- 见 `INDEX.md` 第 X.X 节了解使用该指令的组合模式。
```
