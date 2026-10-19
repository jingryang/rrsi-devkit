# FP8_E8M0 Scale 解码（BF16 / FP32 两路径）

## 适用判据

把 FP8_E8M0（8-bit exponent-only, bias=127）编码的 scale 解码为 BF16 或 FP32，供后续反量化乘法。

## 关键实现要点

### 路径 A：FP8_E8M0 → BF16（Pattern 1.6，简化版）

```
LoadAlign(u8, 256B) → Interleave-with-zero → Cast<bf16, fp8_e8m0_t, ZERO+ZEROING> ×2 → StoreAlign<bf16> ×2
```
Interleave-with-zero 已正确放置每个字节，ZERO layout Cast 后输出天然顺序，**无需二次 Interleave**。

### 路径 B：FP8_E8M0 → FP32（Pattern 1.5，完整版）

```
LoadAlign(u8, 256B) → Interleave-with-zero → Cast<bf16, fp8_e8m0_t, ZERO>(×2 半寄存器)
  → Cast<f32, bf16, ZERO/ONE 双 layout>(×4 寄存器) → Interleave(恢复顺序, ×2 对) → StoreAlign(4×64 float)
```

### 公共规则

- **源类型必须 `fp8_e8m0_t`**（非 uint8_t），否则硬件做整数转浮点而非 E8M0 解码。
- **多 layout Cast 的 mask 粒度必须与源类型一致**（窄→宽用源类型 mask）。
- 每次 VF 循环处理 256 个 scale；`loopNum = ceil(scaleNum/256)`；UB 按 `ceil(scaleNum/256)*256` 对齐。
- `RoundMode` 用 `AscendC::RoundMode::UNKNOWN`。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| BF16→FP32 ONE-layout 在 partial mask 下高奇数 lane 输出 0；输入值小被 atol 掩盖"假通过" | `UpdateMask<uint8_t>(count)` 粒度不匹配（窄→宽应源类型 mask） | `CreateMask<bfloat16_t, ALL>()` 全 mask |
| 尾块数据异常 | partial mask 多 layout Cast 不稳 | `__aicore__` 层把最后 loop 逻辑上扩展到 **255**（`calCount += 255 - tail`）；UB 尾部 CopyIn 前清零；DataCopyOut 只回写实际长度 |
| 整数转换而非解码 | Cast 源类型写 uint8_t | 写 `fp8_e4m3fn_t` / `fp8_e8m0_t` |

## 可复用模式（最小骨架）

- `Interleave-with-zero` + ZERO layout 是 FP8_E8M0→BF16 标准模式（源类型 `fp8_e8m0_t`）。
- 多 layout Cast（ZERO/ONE 取偶/奇 bf16）+ Interleave 是 BF16→FP32 标准模式。
- 尾块 padding 到硬件稳定整数边界（255），循环内全 mask。

## 横切标签

`multi-dtype`、`mask-tail`。

## 实证来源

- `quant` `compute_scale_fp8`（15/15，max_diff=2^-127，BF16 中间精度最小舍入）
- `quant` `compute_scale_fp4`（15/15 max_diff=0.0；FP8 路径的严格子集）
