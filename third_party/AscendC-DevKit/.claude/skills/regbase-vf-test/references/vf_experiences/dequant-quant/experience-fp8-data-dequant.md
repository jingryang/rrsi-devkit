# FP8 数据反量化：4-layout Cast + Scale 广播（Pattern 1.1/1.2）

## 适用判据

FP8（E4M3FN 等）量化数据 × FP32 scale → 目标 dtype（BF16/FP16/FP32）。`y = decode_fp8(x) × scale`，每 32 元素一个 block，scale 每 block 一个。

## 关键实现要点

1. **FP8 → FP32 四布局 Cast**：
   ```cpp
   Cast<float, fp8_e4m3fn_t, ZERO>(vd0, vdFp8, maskU8);    // [0,4,8,...,252]
   Cast<float, fp8_e4m3fn_t, ONE>(vd1, vdFp8, maskU8);     // [1,5,9,...,253]
   Cast<float, fp8_e4m3fn_t, TWO>(vd2, vdFp8, maskU8);     // ...
   Cast<float, fp8_e4m3fn_t, THREE>(vd3, vdFp8, maskU8);   // [3,7,11,...,255]
   ```
   源类型必须 `fp8_e4m3fn_t`（非 uint8）。
2. **Scale 广播 `DIST_E2B_B32`**：`LoadAlign<float, POST_MODE_UPDATE, DIST_E2B_B32>(vdScale, scaleAddr, 8)` —— 8 个 FP32 scale × 8 reps = 64 FP32，恰好匹配一个 layout register 的 8-block 结构；同一个 vdScale 可复用于全部 4 个 layout 的 Mul。
3. **BF16 输出合并（Pattern 1.2）**：第一级 cross-pair Interleave（`Interleave(vd0,vd2,vd0,vd2)` + `Interleave(vd1,vd3,vd1,vd3)`）→ ZERO/ONE Cast → `Add` 合并——**无需第二级 Interleave**。
4. **half-tile 拆分**：16-block tile 拆两个 8-block `__simd_callee__`，降寄存器压力。
5. **尾块 padding**：block 数对齐到 16 的倍数；x padding 清零（FP8 0x00=0.0）、scale padding 填 1.0（0×1=0）；DataCopyOut 只回写实际长度。
6. **`__simd_callee__` 指针推进**：`POST_MODE_UPDATE` 只改形参局部副本，helper 的 UB 指针必须声明为**引用**（`__ubuf__ T*&`），否则两 half-tile 重复处理同地址。
7. **FP32→BF16 Cast**：`UNKNOWN` 不合法，须 `CAST_RINT` + `SAT/NO_SAT`。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| `__simd_vf__` 调 `__simd_vf__` 编译错 | 只能调 callee | HalfTile 改 `__simd_callee__` |
| 多 block 输出重复/错误 | callee 指针未同步推进 | 指针参数改引用 |
| 大 scale 场景 max_diff=inf | scale×max_fp8 > FP32_MAX | 测试数据限制 scale 指数 ≤ 240 |
| max_diff=nan | 测试含 FP8 NaN 字节（0x7F/0xFF） | 生成数据剔除 E4M3FN NaN 模式 |
| `MaskReg&` 加 const 编译错 | Reg API 要求非 const 引用 | callee mask 参数非 const |
| `POST_MODE_KEEP` 不存在 | PostLiteral 无此枚举 | 用 `POST_MODE_UPDATE` |

## 横切标签

`multi-dtype`、`mask-tail`。

## 实证来源

- `quant` `compute_data_fp8`（10/10 max_diff=0.0，BF16 输出路径；fp32/fp16 同流程模板实例化）
