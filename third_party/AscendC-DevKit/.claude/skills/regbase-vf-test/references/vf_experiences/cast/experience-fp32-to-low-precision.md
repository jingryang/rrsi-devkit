# FP32 → FP16/BF16 出口：单 Cast + PACK_B32 标准形

## 适用判据

VF 尾部把 fp32 中间结果收敛 cast 为低精度输出 dtype（fp16/bf16），或归一化/缩放与 cast 融合的出口。

## 关键实现要点

1. **单次 ZERO Cast + `StoreAlign<DY, DIST_PACK_B32>`**（A5 实测位级正确）：
   - `Cast<DY, float, castTraitF32ToDy>(yReg, tReg, mask)`（ZERO layout + `NO_SAT` + `ZEROING` + `CAST_RINT`）
   - `StoreAlign<DY, DIST_PACK_B32>(yAddr + j*VL, yReg, mask)` 打包存储
   - **禁止** `cast.md` §7.2 的 ZERO/ONE 双 Cast + ZEROING + Add 合并：本芯片实测产生错序数据（Add 后 lane 序不符，多元素全错、单元素因退化布局假通过）；无 PACK 的 16bit Store 按寄存器全宽写出 pad 区全毁。文档与 examples 冲突时以 `examples/cast.cpp` 实测为准。
2. **mask 粒度全程 fp32**（源操作数规则）：`Cast<DY,float>` 与 packed Store 共用同一 `UpdateMask<float>`；`DIST_PACK_B32` 负责把 32bit 槽翻译成 16bit 输出 lane，无需 16bit 粒度 mask。
3. **CastTrait**：`{RegLayout::ZERO, SatMode::NO_SAT, MaskMergeMode::ZEROING, AscendC::RoundMode::CAST_RINT}`——`RoundMode` 在 `AscendC::` 非 `Reg::` 子空间；`NO_SAT` 使溢出透传 ±inf。
4. **fp32→fp32 组合**：`if constexpr` 编译期切纯拷贝（Load/Store），无 Cast 指令。
5. **循环上界 `ceil(outW/VL)`**：64 元素块天然覆盖 8 元素对齐上界，`[outW, outWAlign)` 靠 Store mask 掩掉。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| 16bit 全 case 值错乱、pad 区全毁 | 双 Cast+Add 模式 lane 序错 + 无 PACK 全宽写 | 单 Cast + PACK_B32（见上） |
| bf16 pad 哨兵全数误报 PAD-VIOLATION | 哨兵 777.0 在 bf16 舍入为 776，`==777` 必然失败 | 哨兵选低精度可精确表示值（768.0=1.5×2^9，三态精确） |
| fp32 分支 Store 误写回输入 buffer | 手误 | 编码后立即复查 Store 目标 |

## 可复用模式（最小骨架）

```cpp
for (uint16_t j = 0; j < outBlocks; ++j) {          // outBlocks = ceil(outW / 64)
    Reg::LoadAlign(aReg, acc2Addr + j * 64);
    Reg::Muls<float, float, ZEROING>(tReg, aReg, invKdKh, maskAllF);  // 标量直传
    // ... 计算链 ...
    uint32_t sregOut = outW - j * 64;               // 每轮重置；自动递减 VL
    auto m = Reg::UpdateMask<float, RegTensor<float>::trait>(sregOut);
    if constexpr (!std::is_same<DY, float>::value) {
        Reg::RegTensor<DY> yReg;
        Reg::Cast<DY, float, castTraitF32ToDy>(yReg, tReg, m);
        Reg::StoreAlign<DY, StoreDist::DIST_PACK_B32>(yAddr + j * 64, yReg, m);
    } else {
        Reg::StoreAlign(yAddr + j * 64, tReg, m);
    }
}
```

## 横切标签

`multi-dtype`（DTYPE_CODE 三态）、`mask-tail`。

## 实证来源

- `adaptive_avg_pool_3d` `normalize_cast_out_vf`（30/30 max_diff=0.0）
- `moe_finalize_routing` `cast_output_vf`（24/24 位级一致）
