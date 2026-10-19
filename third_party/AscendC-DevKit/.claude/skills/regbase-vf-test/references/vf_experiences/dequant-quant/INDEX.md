# dequant-quant — 反量化 / 量化 VF 范式

> 类别范式总纲：判据 → 指令链选型 → 结构模板 → 陷阱。检索先读本文件，再读下方条目。

## 判据（结构信号）

VF 核心是 **低精度浮点格式解码/编码**（FP8_E8M0 / FP8_E4M3FN / FP4_E2M1 / MX 数据格式），配合 scale 广播做反量化乘法。典型家族：`compute_scale_*`（解码 scale）+ `compute_data_*`（数据 × scale）。

## 指令链选型

| 数据格式 | 解码链 | 要点 |
|----------|--------|------|
| FP8_E8M0 → BF16/FP32 | `LoadAlign(u8)` → `Interleave-with-zero` → `Cast<bf16/f32, fp8_e8m0_t, ZERO>` | **源类型必须 `fp8_e8m0_t`**（非 uint8，否则整数转换）；BF16→FP32 需 ZERO/ONE 双 layout + 二次 Interleave |
| FP8_E4M3FN → FP32 | `Cast<float, fp8_e4m3fn_t, {ZERO,ONE,TWO,THREE}>` ×4 | 4-layout 全布局 Cast，每 block 贡献 8 元素 |
| FP4_E2M1 → BF16 | `LoadAlign(u8, DIST_UNPACK4_B8)` → `Cast<bf16, fp4x2_e2m1_t, ZERO>` | **源类型必须 `fp4x2_e2m1_t`**；硬件解包 packed 字节，低 nibble 在前 |
| Scale 广播 | `LoadAlign<float, DIST_E2B_B32>`（8 scale × 8 reps）或 `DIST_E2B_B16` + `Self-Interleave`（16→32 reps） | 广播向量与 4-layout/block 结构对齐，单个 scale reg 可复用于全部 layout |

## 结构模板

三层：`__aicore__` Impl（LocalTensor→`__ubuf__` + **FLOAT_OVERFLOW_MODE_CTRL 包裹**）→ `__simd_vf__`（Hardware Loop + 循环外建全 mask）→ `__simd_callee__`（half-tile，指针用**引用**推进）。

## 横切标签

`multi-dtype`（多 dtype 组合）、`mask-tail`、`unaligned-2d`（非 32B 尾块）。

## 常见陷阱（最高频）

1. **Cast 源类型用错**：`uint8_t` → 硬件整数转换；必须 fp8/fp4 专用类型。
2. **多 layout Cast 的 mask 粒度**：窄→宽必须用**源类型 mask**（`CreateMask<bfloat16_t,ALL>`），`UpdateMask<uint8_t>` 在 partial mask 下高奇数 lane 输出为 0（被小输入 atol 掩盖的"假通过"）。
3. **尾块 padding 到 loop 粒度**：`__aicore__` 层把 block 数对齐到 16/256 的整数倍；x padding 清零、scale padding 置 1.0（0×1=0）；DataCopyOut 只回写实际长度——循环内全 mask，免尾块分支。
4. **FLOAT_OVERFLOW_MODE_CTRL**：FP4/FP8 Cast 前后 `GetCtrlSpr/SetCtrlSpr(0)` 包裹，转后恢复。
5. **`__simd_callee__` 指针不推进**：`POST_MODE_UPDATE` 只改形参局部副本，half-tile helper 的 UB 指针必须声明为引用（`__ubuf__ T*&`）。
6. **两个连续运行时条件循环触发 ccec 后端 segfault**（clang exit 139）：主循环+尾循环拆两个 for 即崩——用"对齐到 loop 粒度 + 单一循环 + 全 mask"消除尾部分支。
7. **FP32→BF16 Cast 参数**：`UNKNOWN` 不合法，必须 `CAST_RINT` + `NO_SAT`/`SAT`。

## 条目索引

| 条目 | 内容 | 标签 |
|------|------|------|
| `experience-fp8-scale-decode.md` | FP8_E8M0 scale 解码（BF16/FP32 两路径）、Interleave-with-zero、partial mask 粒度陷阱、tail padding 到 255 | `multi-dtype`, `mask-tail` |
| `experience-fp8-data-dequant.md` | FP8 4-layout Cast + DIST_E2B_B32 scale 广播 + BF16 合并、half-tile 拆分 | `multi-dtype` |
| `experience-fp4-dequant.md` | FP4 DIST_UNPACK4_B8 解包 + E2B_B16 self-interleave 广播、FLOAT_OVERFLOW_MODE_CTRL | `multi-dtype` |

## 实证来源

`quant/compute_scale_fp8/fp4_lesson.md`、`quant/compute_data_fp8/fp4_lesson.md`（已迁移，原 lesson 在算子 record dir）。
