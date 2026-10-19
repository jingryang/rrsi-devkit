# FP4 数据反量化：DIST_UNPACK4_B8 解包 + Scale 自交织广播（Pattern 1.4/1.7）

## 适用判据

FP4_E2M1 packed 数据 × BF16 scale → 目标 dtype（BF16 等）。每字节含 2 个 FP4 值（low nibble first），每 16 元素一个 block、scale 每 block 一个。

## 关键实现要点

1. **FP4 快速解码（DIST_UNPACK4_B8 + Cast ZERO）**：
   ```cpp
   LoadAlign<uint8_t, POST_MODE_UPDATE, DIST_UNPACK4_B8>(vdFp4U8_0, xAddr, 64);  // 64 packed bytes → 256B 布局
   Cast<bfloat16_t, fp4x2_e2m1_t, castTraitFp4ToBf16>(
       vdData0, reinterpret_cast<RegTensor<fp4x2_e2m1_t>&>(vdFp4U8_0), maskU8);
   ```
   源类型必须 `fp4x2_e2m1_t`（非 uint8）；每 half-tile 2 次 Load/Cast（每次 64B → 128 BF16）。
2. **BF16 scale 广播（DIST_E2B_B16 + Self-Interleave）**：
   ```cpp
   LoadAlign<bfloat16_t, POST_MODE_UPDATE, DIST_E2B_B16>(vdScaleTmp, scaleAddr, 8);  // 8×16 reps=128 BF16
   Interleave(vdScale0, vdScale1, vdScaleTmp, vdScaleTmp);   // self-interleave: 16→32 reps
   ```
   得前 4 scale×32（vdScale0）与后 4 scale×32（vdScale1）。
3. **乘法与存储**：`Mul<bf16>` + `StoreAlign<bf16, DIST_NORM_B16>`（BF16 输出无需再 cast）。
4. **FLOAT_OVERFLOW_MODE_CTRL 包裹**（FP4/FP8 Cast 前后）：
   ```cpp
   constexpr int32_t REG = 60;
   int64_t saved = GetCtrlSpr<REG, REG>();
   SetCtrlSpr<REG, REG>(0);
   ...ComputeDataFp4RegImpl(...);
   SetCtrlSpr<REG, REG>(saved);
   ```
5. **padding**：block 数对齐到 16 的倍数，x 清零、scale 填 1.0，全 mask、DataCopyOut 只写实际长度。
6. **half-tile**：16-block/512 元素拆两个 8-block callee；mask 在 `__simd_vf__` 循环外创建经引用传入 callee（循环不变外提）。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| 循环内重复 CreateMask 不合规 | 违反循环不变外提 | 上提到 `__simd_vf__` 循环外，引用传入 callee |
| 高/低 nibble 顺序错 | 打包字节序理解错 | 硬件解包低 nibble 在前、高在后，与 golden 一致 |
| BF16 numpy 比较错 | `.view(np.float32)` 对 uint16 数组元素数减半 | 先 `<< 16` 转 uint32 再 view float32 |

## 横切标签

`multi-dtype`、`mask-tail`。

## 实证来源

- `quant` `compute_data_fp4`（10/10 max_diff=0.0，BF16 输出路径；fp32/fp16 追加 Cast 模板实例化）
