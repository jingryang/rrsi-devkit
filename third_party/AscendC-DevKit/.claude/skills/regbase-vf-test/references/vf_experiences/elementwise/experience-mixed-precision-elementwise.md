# 混合精度逐元素链（低精度入→fp32 中间→低精度出）

## 适用判据

逐元素计算但输入/输出为 fp16/bf16，需要 fp32 中间精度（exp/silu/swiglu/gelu 等激活链、`y = f(scale*x + shift)` 类标量链）。

## 关键实现要点

1. **计算粒度**：统一按 fp32 的 `oneRepSize = GetVecLen()/sizeof(float) = 64` 元素/轮推进；fp16/bf16 每轮处理 64 个 DX 元素。
2. **位宽变化 Cast（DX=fp16/bf16 → fp32）**：`LoadAlign<DX, DIST_UNPACK_B16>` 解包加载 + `Cast<float, DX, castTraitF162F32>`（ZERO, ZEROING）升 fp32。
3. **位宽变化 Cast（fp32 → DX）**：`Cast<DX, float, castTraitF322F16>`（ZERO, ZEROING, `CAST_RINT`）+ `StoreAlign<DX, DIST_PACK_B32>` 打包存储。
4. **fp32 输入**：首尾 Cast 为编译期 no-op（`if constexpr (IsSameType<DX, float>)` 直 Load/Store，零开销）。
5. **标量直传**：`scale/shift` 直接作 `Muls/Adds` 标量实参，禁止先广播到 UB 再 Load。
6. **silu 四指令链**：`Muls(x0f, -1.0f)` → `Exp` → `Adds(1.0f)` → `Div(x0f, denom)`（Reg 级 Div 直接得 silu，替代 Reciprocal+Mul；910D 无 Reg 级 Reciprocal）。
7. **CastTrait 双 trait**（升/降各一），`RoundMode` 在 `AscendC::` 非 `Reg::`。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| `no member named 'RoundMode' in namespace 'AscendC::Reg'` | RoundMode 在全局 AscendC 命名空间 | `AscendC::RoundMode::UNKNOWN` / `CAST_RINT` |
| half VF 输出全错/OOB | DX=half 的 UNPACK+Cast 两条指令 buffer 越界风险大 | **先 fp32 验证通过再泛化 half/bf16** |
| npy 精度对不上（误差远超容差） | half 回路 Cast 往返精度损失放大 | 中间全程 fp32，只在入/出 UB cast |
| 组合链顺序错 | Rsqrt=Sqrt+Div 等复合 | 组合逻辑封装 `__simd_callee__`（仅操作 RegTensor） |

## 可复用模式（最小骨架）

```cpp
if constexpr (sizeof(DX) == 2) {
    Reg::LoadAlign<DX, LoadDist::DIST_UNPACK_B16>(srcReg, xUb + i * oneRepSize);
    Reg::Cast<float, DX, castTraitDXToF32>(xF32Reg, srcReg, mask);
} else {
    Reg::LoadAlign<float>(xF32Reg, xUb + i * oneRepSize);
}
Reg::Muls<float, float, ZEROING>(t1, xF32Reg, scaleEff, mask);
Reg::Adds<float, float, ZEROING>(t2, t1, shiftEff, mask);
Reg::Exp<float, ZEROING>(t3, t2, mask);
if constexpr (sizeof(DX) == 2) {
    Reg::Cast<DX, float, castTraitF32ToDX>(yReg, t3, mask);
    Reg::StoreAlign<DX, StoreDist::DIST_PACK_B32>(yUb + i * oneRepSize, yReg, mask);
} else {
    Reg::StoreAlign<float>(yUb + i * oneRepSize, t3, mask);
}
```

## 横切标签

`multi-dtype`（DTYPE_CODE 0/1/2 三态）、`mask-tail`。

## 实证来源

- `exp` `compute_exp`（10/10 位级，fp16/bf16/fp32 三组合）
- `swi_glu` `compute_swi_glu`（silu 四指令链 + 位宽 Cast）
