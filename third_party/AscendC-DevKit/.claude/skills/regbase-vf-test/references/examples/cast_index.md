# Cast 参考与索引（cast_index.md）

> **这是 agent 写 Cast 代码的唯一入口。** 查下面的**查询矩阵**（源 dtype × 目标 dtype）定位转换，拿到**可直接搬运的 helper 名 + 文件:行号**，照抄进生成的代码即可。
>
> 与代码本体分工：
> - **本文件（`cast_index.md`）** — 查询矩阵 + Trait 全集 + 红线 + 搬运模板。各场景的**使用详解（代码片段/分支/红线）已作为内联注释写在 `cast_common.h` 对应 helper 上方**，写代码时 Read 头文件即得完整上下文。
> - [`cast_common.h`](./cast_common.h) — **代码本体**，按【位宽变换】组织（§1 Trait / §2 同宽 / §3 窄化 / §4 扩宽 / §5 int64 拆位 / §6 标量专项），直接 `#include` 或复制 helper 进生成的代码。

---

## 1. 三步用法

```
① 查下面 §2 矩阵 → 找到「源 dtype × 目标 dtype」的格子 → 取 helper 名 + 行号
② 优先「直接调用」列的 helper（已验证，无需自己拼 Trait/LoadDist）
③ 需要该 helper 的用法/红线 → Read cast_common.h 对应函数上方注释（场景详解已内联）
   需要原理/Trait 明细 → 看 §4 Trait 全集
```

**最省事的做法**：VF 内需要类型转换时，可优先用 `cast_common.h` 的主入口 helper（也可自行写 `Cast<>`，二者皆可）：

| 你要做 | 调这个 |
|--------|--------|
| 任意窄 dtype 张量 → fp32 计算域（扩宽） | `LoadTensorForDtypeTIn<T_IN>(src, dstReg, preg, offset)` |
| fp32 计算域 → 任意窄 dtype 输出（窄化） | `StoreTensorForDtypeTOut<T_OUT>(dst, srcReg, preg, offset)` |
| 任意 dtype 标量 → fp32 广播 | `LoadScalarForDtypeTIn<T_IN>(src, dstReg, preg, offset)` |
| fp32 累加器 → 单元素写出（0 维/每行一个值） | `StoreScalarForDtypeTOut<T_OUT>(dst, srcReg, pregFull)` |

---

## 2. 转换查询矩阵

> 格子里是**直接调用**的 helper（`cast_common.h` 行号）。标 **—** 的格子无此转换。特殊场景（int64、scale 因子、量化解码前置）见矩阵下方说明。

### 2.1 主矩阵

| 源 \ 目标 | bf16 | fp16 | fp32 | int8 | int32 | int4b | fp8(e4m3/e5m2) | hifp8 |
|-----------|------|------|------|------|-------|-------|----------------|-------|
| **fp32** | §3.1:358<br>`StoreTensor`<br>量化: §3.5:465 | §3.1:358<br>`StoreTensor` | §2:269<br>`CastFp32ToInt32` | §3.1:358<br>量化: §3.3:425 | §2:269<br>`CastFp32ToInt32` | §3.4:444<br>`CastFp32ToInt4Quant` | §3.1:358 | §3.1:358 |
| **fp16** | §2:290<br>`CastFp16ToBf16`<br>TRUNC: §2:298<br>`CastFp16ToBf16Trunc` | — | §4.1:524<br>`LoadTensor` | 直连: §3.6:478<br>`CastFp16ToInt8Direct`<br>中转: §3.1:358 | §2:313<br>`CastFp16ToInt16` | — | — | — |
| **bf16** | — | §2:283<br>`CastBf16ToFp16` | §4.1:524<br>`LoadTensor` | — | — | — | — | — |
| **int8** | — | 直连: §4.1b:552<br>`CastInt8ToFp16`<br>中转: §4.1:524 | §4.1:524<br>`LoadTensor` | — | — | — | — | — |
| **int16** | — | §2:306<br>`CastInt16ToFp16` | — | — | — | — | — | — |
| **int32** | — | — | §2:276<br>`CastInt32ToFp32` | — | — | — | — | — |
| **fp8(e4m3/e5m2)** | — | — | §4.3.2:617<br>`CastFp8ToFp32Quad` | — | — | — | — | — |
| **fp8_e8m0**（scale 字节） | §4.3.1:605<br>`CastFp8E8m0ToBf16` | — | — | — | — | — | — | — |
| **fp4x2**（打包字节） | §4.3.3:632<br>`CastFp4ToBf16` | §4.1b:566<br>`CastInt4x2ToFp16` | — | — | — | — | — | — |
| **uint8** | — | 直连: §4.1b:558<br>`CastUint8ToFp16`<br>解码: §4.3.1/3 | — | — | — | §3.1:358<br>`StoreTensor` | — | — |
| **int64** | — | — | — | — | — | — | — | — |

> **int32 → int64**（同宽 4B→8B）：§2:321 `CastInt32ToInt64`（配 `DIST_UNPACK_B32` 展开加载）—— 见 cast_common.h §2 函数上方注释。

### 2.2 矩阵使用说明

- **fp32 → fp16/bf16 窄化**（§3.1 `StoreTensorForDtypeTOut<T>`）：`castTraitF322F16` + **`DIST_PACK_B32`** —— 4B→2B 窄化红线见 §6。
- **fp32 → int8 量化编码**（§3.3 `CastFp32ToInt8Quant`）：`Truncate(CAST_RINT)` 先在 fp32 域取整，再 fp16 中转 —— 与通用 §3.1 int8 分支（直接 fp16 中转 RINT）的区别：动态量化需精确取整时用 §3.3。
- **fp32 → int4b 量化编码**（§3.4 `CastFp32ToInt4Quant`）：`Fp322Int16` → `Int162Half` → `Pack` → `F162I8` → `DIST_PACK4_B32`(H mask)，内部自动 `/2` 字节偏移。
- **fp32 → bf16 量化 SAT 截断**（§3.5 `CastFp32ToBf16Sat`）：与通用 bf16 行的区别是 SAT clip 超值域结果。
- **fp16 → int8 直连**（§3.6 `CastFp16ToInt8Direct`，TRUNC）vs **fp32 → int8 中转**（§3.3，Truncate+RINT）：直连是 fp16 输入直接量化；中转是 fp32 计算域输出。uint8 同理（§3.6 RINT）。
- **int8/uint8 → fp16 直连**（§4.1b）：比走 §4.1 fp32 中转省一步 Cast；配 `DIST_UNPACK4_B8`（向量）或 `DIST_BRC_B8`（标量）加载。
- **量化 scale 因子**：`MulQuantScaleFactor<T_Y>`（§3.2:400）—— int8:1/127，fp8e4m3:1/448，fp8e5m2:1/57344，hifp8:1/32768，int4:1/7。
- **整寄存器 2B→4B de-interleave**（§4.2:583 `CastF16ToF32Pair`）：一个寄存器 128 元素一次展开成 2 个 fp32，需 Interleave 恢复顺序 —— 与 §4.1 按 64 元素段循环的区别。
- **fp16 → bf16 两种舍入**：默认 `CastFp16ToBf16`（RINT，§2:290）；OCP/MX 路径用 `CastFp16ToBf16Trunc`（TRUNC，§2:298）。
- **量化解码前置**：`CastFp8E8m0ToBf16` 需先 `Interleave-with-zero` 铺 16-bit slot；`CastFp4ToBf16` 需 `LoadAlign<DIST_UNPACK4_B8>`。两者源类型必须转成 `fp8_e8m0_t` / `fp4x2_e2m1_t` 引用（写 `uint8_t` 会做整数转浮点）。

### 2.3 标量方向

| 源/目标 | 直接调用 | 路径 | 代码位置 |
|---------|---------|------|---------|
| 标量 → fp32 ×64 广播 | `LoadScalarForDtypeTIn<T>` | fp32: `DIST_BRC_B32`；fp16/bf16: `DIST_BRC_B16`+`F162F32`；int8: `DIST_BRC_B8`+两级；int32: `DIST_BRC_B32`+`Int322Fp32` | cast_common.h:704 |
| fp32 标量 → 单元素写出 | `StoreScalarForDtypeTOut<T_OUT>` | fp32: `DIST_FIRST_ELEMENT_B32`；fp16/bf16: Cast+`DIST_FIRST_ELEMENT_B16`；int32: Cast+`DIST_FIRST_ELEMENT_B32` | cast_common.h:746 |
| int64 单元素写出 | `StoreScalarInt64AsLoHi` | 拆 2×int32，高 32 位 `ShiftRights(31)` 符号扩展（`static_cast<int16_t>(31)`） | cast_common.h:650 |
| int64 比较（x ≤ ref） | `CompareInt64LessEqual` | hi<int32>LT + (hi EQ && lo<uint32>LE) | cast_common.h:665 |

---

## 3. 各场景详解（代码片段）

> **每个 helper 的使用场景、典型代码片段、分支说明、红线已作为内联注释写在 [`cast_common.h`](./cast_common.h) 对应函数上方**。本节约略，写代码时直接 Read 头文件对应函数即可获得完整上下文：
>
> - `StoreTensorForDtypeTOut` → cast_common.h §3.1 函数上方注释（4B→2B 窄化红线、int8/fp4/fp8/hifp8 全分支）
> - `LoadTensorForDtypeTIn` → cast_common.h §4.1 函数上方注释（2B→4B 扩宽 / int8 / int32 + 循环骨架）
> - `CastFp32ToInt8Quant` / `CastFp32ToInt4Quant` / `CastFp32ToBf16Sat` / `MulQuantScaleFactor` → cast_common.h §3.2-3.5 函数上方注释（dynamic quant 输出，Truncate-first / int16 中转 / bf16 SAT / scale 因子）
> - `CastFp16ToInt8Direct` / `CastFp16ToUint8Direct` → cast_common.h §3.6 函数上方注释（fp16 直连窄化，不经 fp32）
> - `CastInt8ToFp16` / `CastUint8ToFp16` / `CastInt4x2ToFp16` → cast_common.h §4.1b 函数上方注释（int8/uint8/int4x2 直连扩宽）
> - `CastFp16ToBf16Trunc` / `CastInt16ToFp16` / `CastFp16ToInt16` / `CastInt32ToInt64` → cast_common.h §2 函数上方注释（同宽 2B↔2B / 4B→8B）
> - `CastF16ToF32Pair` → cast_common.h §4.2 函数上方注释（整寄存器 de-interleave）
> - `CastFp8E8m0ToBf16` / `CastFp8ToFp32Quad` / `CastFp4ToBf16` → cast_common.h §4.3 函数上方注释（FP8_E8M0 / FP8 4-layout / FP4 解码）
> - `StoreScalarInt64AsLoHi` / `CompareInt64LessEqual` → cast_common.h §5 函数上方注释（int64 拆位）
> - `LoadScalarForDtypeTIn` / `StoreScalarForDtypeTOut` → cast_common.h §6 函数上方注释（标量广播 / norm 收尾单元素写出）

## 4. CastTrait 全集（cast_common.h 第 30-261 行）

| Trait 常量 | 方向 | RegLayout | SatMode | RoundMode | 用途 |
|-----------|------|-----------|---------|-----------|------|
| `castTraitFp322Hifp8` | float→hifloat8_t | ZERO | SAT | CAST_ROUND | fp32 → hifp8（§3.1） |
| `castTraitFp322Fp8` | float→fp8 | ZERO | SAT | CAST_RINT | fp32 → fp8(e4m3fn/e5m2)（§3.1） |
| `castTraitF322F16` | float→bf16/half | ZERO | **NO_SAT** | CAST_RINT | 4B→2B 窄化（§3.1 / §6.2） |
| `castTraitFp322Bf16Sat` | float→bf16 | ZERO | **SAT** | CAST_RINT | 量化截断（§3.5） |
| `castTraitF162F32` | bf16/half→float | ZERO | UNKNOWN | UNKNOWN | 2B→4B 扩宽（§4.1 / §4.2） |
| `castTraitF162F32One` | bf16/half→float | ONE | UNKNOWN | UNKNOWN | 2B→4B 整寄存器 de-interleave 配对（§4.2） |
| `castTraitI82F16` | int8→half | ZERO | NO_SAT | CAST_RINT | int8→half 中转（§4.1 / §6.1） |
| `castTraitI322F16` | int32→half | ZERO | NO_SAT | CAST_RINT | int32→half 中转 |
| `castTraitFp322Int32` | float→int32 | UNKNOWN | NO_SAT | CAST_RINT | fp32→int32（§2 / §6.2） |
| `castTraitInt322Fp32` | int32→float | UNKNOWN | NO_SAT | CAST_RINT | int32→fp32（§2 / §4.1 / §6.1） |
| `castTraitFp322Fp16` | float→half | ZERO | NO_SAT | CAST_ODD | fp32→fp16（ODD 舍入，打包链路中转，§3.1/§3.3/§3.4） |
| `castTraitFp162Int8` | half→int8 | ZERO | NO_SAT | CAST_RINT | half→int8（§3.1 / §3.3） |
| `castTraitBf162Fp16` | bf16↔fp16 | ZERO | NO_SAT | CAST_RINT | 同宽 16-bit 互转（§2） |
| `castTraitFp162Bf16Trunc` | fp16→bf16 | UNKNOWN | UNKNOWN | **CAST_TRUNC** | fp16→bf16 OCP/TRUNC 变体（§2） |
| `castTraitI82F16Direct` | int8→fp16 | ZERO | UNKNOWN | UNKNOWN | int8→fp16 直连（§4.1b / §6.1） |
| `castTraitU8ToF16` | uint8→fp16 | ZERO | UNKNOWN | UNKNOWN | uint8→fp16 直连（§4.1b / §6.1） |
| `castTraitI162F16` | int16→fp16 | UNKNOWN | UNKNOWN | CAST_RINT | int16→fp16 直连（§2） |
| `castTraitFp162Int8Trunc` | fp16→int8 | ZERO | NO_SAT | **CAST_TRUNC** | fp16→int8 直连窄化（§3.6） |
| `castTraitF162U8` | fp16→uint8 | ZERO | NO_SAT | CAST_RINT | fp16→uint8 直连窄化（§3.6） |
| `castTraitI322I64` | int32→int64 | ZERO | UNKNOWN | UNKNOWN | int32→int64（§2，配 DIST_UNPACK_B32） |
| `castTraitFp8E8m0ToBf16` | fp8_e8m0→bf16 | ZERO | UNKNOWN | UNKNOWN | scale 解码（源类型必须 fp8_e8m0_t，§4.3.1） |
| `castTraitFp8ToFp32Zero~Three` | fp8→fp32 | ZERO/ONE/TWO/THREE | UNKNOWN | UNKNOWN | FP8 4-layout 反量化（§4.3.2） |
| `castTraitFp4ToBf16` | fp4x2→bf16 | ZERO | UNKNOWN | UNKNOWN | FP4 解码（配 DIST_UNPACK4_B8，§4.3.3） |
| `castTraitFp322Int16` | float→int16 | ZERO | NO_SAT | CAST_RINT | 量化编码 int4 中转（fp32 域取整，§3.4） |
| `castTraitInt162Half` | int16→half | UNKNOWN | NO_SAT | CAST_RINT | int16→half（Pack 前中转，§3.4） |
| `castTraitF162I8` | half→int4x2 | ZERO | NO_SAT | CAST_RINT | int4 打包 Cast（§3.4） |

> 命名空间：`CastTrait`/`RegLayout`/`SatMode`/`MaskMergeMode` 在 `AscendC::Reg::`；**`RoundMode` 在 `AscendC::` 命名空间**（`AscendC::RoundMode`），不在 `Reg::` 下。
> 窄化 Trait（`F322F16`/`Fp322Fp16`/`Fp322Bf16Sat` 等）`SatMode` 必须显式 `NO_SAT`/`SAT`，用 `UNKNOWN` 会 `static assertion failed`。

---

## 5. 搬运模板（复制即用）

### 5.1 最常见：多 dtype 输入 → fp32 计算 → 多 dtype 输出

```cpp
#include "cast_common.h"   // 提供 LoadTensorForDtypeTIn / StoreTensorForDtypeTOut

template <typename T_OUT, typename T_IN>
__simd_vf__ inline void MyComputeVF(__ubuf__ T_OUT* dst, __ubuf__ T_IN* src,
                                    const uint32_t calCount)
{
    constexpr uint32_t VL_FP32 = 64;                       // 256B / sizeof(float)
    uint32_t sreg = calCount;
    AscendC::Reg::MaskReg preg;
    AscendC::Reg::RegTensor<float> xFp32;
    uint16_t repeatTime = static_cast<uint16_t>((calCount + VL_FP32 - 1) / VL_FP32);

    for (uint16_t i = 0; i < repeatTime; ++i) {
        preg = AscendC::Reg::UpdateMask<float>(sreg);
        CustomRegImpl::LoadTensorForDtypeTIn<T_IN>(src, xFp32, preg, i * VL_FP32);
        // ===== 这里写 fp32 域的计算逻辑 =====
        CustomRegImpl::StoreTensorForDtypeTOut<T_OUT>(dst, xFp32, preg, i * VL_FP32);
    }
}
```

> 若不方便 `#include`（VF 单测常见），把 `cast_common.h` 里**用到的 Trait 常量 + 对应 helper 函数**整段复制进你的 `.cpp`（保持 `namespace CustomRegImpl`）即可——`compute_row_max_vf_custom.cpp` 等已验证 VF 就是这么做的。

### 5.2 只需单向 fp32→fp16/bf16（最易错场景，§3 窄化）

```cpp
constexpr AscendC::Reg::CastTrait castTraitF322F16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,          // ← 必须显式，不能 UNKNOWN
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,          // ← RoundMode 在 AscendC:: 下
};

AscendC::Reg::RegTensor<T_OUT> xOut;
AscendC::Reg::Cast<T_OUT, float, castTraitF322F16>(xOut, xRegFp32, preg);
AscendC::Reg::StoreAlign<T_OUT, AscendC::Reg::StoreDist::DIST_PACK_B32>(dst + offset, xOut, preg);
```

### 5.3 量化输出（dynamic quant，§3.3-3.5）

```cpp
// fp32 → int8（Truncate-first）
CustomRegImpl::CastFp32ToInt8Quant(i8Out, yFp32, preg, segOffset);

// fp32 → int4（int16 中转）
CustomRegImpl::CastFp32ToInt4Quant(u8Out, yFp32, preg, segOffset);

// fp32 → bf16（SAT 截断）
CustomRegImpl::CastFp32ToBf16Sat(bf16Reg, yFp32, preg);

// scale = absmax(y) / MAX_ABS
CustomRegImpl::MulQuantScaleFactor<T_Y>(scaleReg, maskOne);
```

### 5.4 fp32 累加器收尾写单元素（norm/loss 类算子，§6）

```cpp
// 读 0 维标量（广播到 fp32 寄存器）
CustomRegImpl::LoadScalarForDtypeTIn<float>(accUb, accReg, pregFull, 0);

// ... 计算后写回 1 个元素（fp16/bf16 输出）
CustomRegImpl::StoreScalarForDtypeTOut<DY>(yAddr, yF32Reg, pregFull);
```

### 5.5 完整可编译样例（cast.cpp）

`cast.cpp` 提供 fp32↔fp16 两个方向**完整可编译 kernel**（含 Tiling/DataCopy 脚手架），需要最小改动验证时可直接抄：

| 函数 | 方向 | 行号 |
|------|------|------|
| `CastRegImplF32ToF16` | fp32 → fp16（`castTraitF322F16` + `DIST_PACK_B32`） | cast.cpp:26-42 |
| `CastRegImplF16ToF32` | fp16 → fp32（`DIST_UNPACK_B16` + `castTraitF162F32`） | cast.cpp:44-60 |
| `cast`（kernel 入口，mode 0/1 路由） | 完整示例 | cast.cpp:111-181 |

> `cast.cpp` 仅覆盖 fp32/fp16；其余路径以 `cast_common.h` helper 为准（测试用例见 `test_cast.py`）。

---

## 6. 红线（写之前必看）

| 🚫 禁止 | ✅ 正确 |
|---------|--------|
| 4B→2B 窄化用 `Cast ZERO + Cast ONE + Add` | 单 ZERO Cast + `StoreAlign<DIST_PACK_B32>` |
| fp32→bf16/fp16 用 `SatMode::UNKNOWN` | 显式 `SatMode::NO_SAT`（否则 static assert 编译失败） |
| 写 `AscendC::Reg::RoundMode` | `AscendC::RoundMode`（RoundMode 不在 Reg:: 下） |
| 多布局 Cast 后直接 Store | Interleave 恢复顺序 或 用 `DIST_PACK_B32/PACK4_B32` |
| 多布局 Cast 用 `MaskMergeMode::MERGE` | `MaskMergeMode::ZEROING` |
| FP8_E8M0 用 `uint8_t` 作源类型 | `fp8_e8m0_t` + 先 Interleave-with-zero |
| FP4 解码用 `uint8_t` 作源类型 | `fp4x2_e2m1_t`（配 `DIST_UNPACK4_B8` 加载） |
| int64 用 `DIST_BRC`/`FIRST_ELEMENT` 直接广播/写 | 拆低/高 32 位，`ShiftRights` 移位量必须 `static_cast<int16_t>` |
| `Pack` 代替多布局 Cast+Add 合并拆分数据 | `Pack` 只留每元素低半，丢数据；Cast+Add 仅宽化/同宽可用 |

---

## 7. cast_common.h 内部章节地图（位宽变换分类）

| § | 内容 | 行号 |
|---|------|------|
| §1 | CastTrait 常量全集 | 30-261 |
| §2 | 同宽互转（4B↔4B fp32↔int32、2B↔2B bf16↔fp16/int16↔fp16、4B→8B int32→int64） | 263-327 |
| §3 | 窄化（4B→2B/1B）：§3.1 通用输出 / §3.2 scale 因子 / §3.3 int8 / §3.4 int4 / §3.5 bf16-SAT / §3.6 fp16→int8/uint8 直连 | 328-490 |
| §4 | 扩宽（2B→4B / 1B→2B/4B）：§4.1 通用输入 / §4.1b int8/uint8/int4x2→fp16 / §4.2 整寄存器 de-interleave / §4.3 量化解码 | 491-640 |
| §5 | 拆位 / 组合（int64 写回 / 比较 / int32→int64 展开） | 641-680 |
| §6 | 标量专项（§6.1 广播读 / §6.2 单元素写） | 681-766 |

---

## 8. 深入阅读

| 需求 | 去哪 |
|------|------|
| `Reg::Cast` 指令语义、多布局原理、寄存器扩展矩阵 | [`../vf-instructions/cast.md`](../vf-instructions/cast.md) |
| FP8/FP4 反量化等多指令组合流水线 | [`../vf-instructions/INDEX.md`](../vf-instructions/INDEX.md) §1 |
| int64 拆位背景（LoadDist/StoreDist 无 B64） | [`../vf_experiences/_generic/reg_scalar_carry_and_int64_lesson.md`](../vf_experiences/_generic/reg_scalar_carry_and_int64_lesson.md) |
| 量化 lesson（FP8/FP4 实战） | [`../vf_experiences/quant/`](../vf_experiences/quant/) |
| dynamic quant 量化输出编码（int8/int4 取整-打包链） | ops-nn `add_rms_norm_dynamic_quant/op_kernel/arch35/add_rms_norm_dynamic_quant_regbase_perf.h` `ComputeMutlY`/`ComputeY` |
| `StoreDist` / `LoadDist` 完整取值表 | [`../vf-instructions/store-align.md`](../vf-instructions/store-align.md) / [`load-align.md`](../vf-instructions/load-align.md) |
