# 变长段求和"贡献转置"（无分支 SIMD 向量化）

## 适用判据

每输出元素对应**长度不等**的输入窗口段（如 `part[ow] += Σ_{w∈[winBnds[ow], winBnds[ow+1])}`），段长不可向量化、循环内需要分支。核心目标：把变长段规约转成**逐输入元素广播 + 窗口掩码累加**，全程无分支。

## 关键实现要点

1. **贡献转置**：不逐 ow 做变长段规约，改为逐输入元素 t 广播、按窗口掩码加到整行 part：
   `partReg[lane] += x[t]·[winBnds[ow] ≤ w′ < winBnds[ow+1]]`（w′=wBlkOff+t）。每条向量指令更新 64 个 ow 累加器，w 维度标量序，零分支。
2. **标量广播取数**：`Duplicate(idxReg, t) + Gather(xBrc, xUb, idxReg, maskAll)`——Gather 全 lane 同索引 = 从 UB 广播单元素；索引单位=元素（16bit 配 uint16、32/64bit 配 uint32）。
3. **DX→fp32 升精度**：寄存器域 `Cast<float, DX, ZERO-layout trait>`。广播寄存器全 lane 同值 → **单 ZERO layout 即得 fp32 广播，无需 Interleave 还原**（全同值 Interleave 恒等退化）。
4. **窗口判定零分支**：`Compares<int32,LE>(bndLo ≤ w′)` + `Compares<int32,GT>(bndHi > w′)` + `And(MaskReg)` + `Select(xBrc, zero)` + `Add`——空段（lo≥hi）自动加 0。
5. **winBnds 读取必须用 Gather**：`winBnds[ow+1]` 在 `bndsAddr+1` 起 +4B 偏移，**LoadAlign 非 32B 对齐地址触发 VEC_ERROR**；Gather 元素索引无对齐要求。
6. **part 紧密布局读写用 Gather/Scatter**：行距=outW 非 8 倍数时行基址非 32B 对齐；`Arange(colIdx, j·64) + Adds(colIdx, rowBase)` 构造元素索引，Scatter 带 partMask 只写有效 lane。
7. **索引域分离**：winBnds 列索引（colIdx）与 part 全局索引（laneIdx=colIdx+rowBase）**必须分开构造**——曾把 rowBase 提前加进 laneIdx 再用于 winBnds Gather，rowBase=0 时掩盖、≠0 时读错表。
8. **pad 区设计**：winBnds 表尾 pad 128 个 int32 填 0（越界 lane 读 0 → GT 恒 false 掩码安全收敛）；part 尾 pad 128 填 777 哨兵（Scatter mask 不写 → 哨兵存活即 mask 正确性反向验证）。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| 全 case VEC_ERROR | LoadAlign 非 32B 对齐地址（+4B 偏移读 winBnds）；empty_block 因输出=输入假 PASS | winBnds 改 Gather 元素索引读取；probe/bisect 定位（单发非对齐加载不炸、组合消费才炸） |
| 多行/多块 max_diff ~2-12 | 索引域混用（rowBase 提前加进 winBnds Gather） | 分离 colIdx 与 laneIdx 两个索引寄存器 |
| `Reg::RoundMode` 编译错 | 枚举在 `AscendC::` | CastTrait 写 `AscendC::RoundMode::UNKNOWN` |
| `Add` 3 参编译错 | Reg::Add 必须带 mask | `Add(dst, s0, s1, maskAll)` |
| OOB data-unchanged 对恒等写回误报 | 写回值与初值相同 | 恒等语义 case 的 unchanged 告警是误报，以 pad 哨兵+golden 判定为准 |

## 可复用模式（最小骨架）

```cpp
Arange<int32_t>(colIdx, j*VL);                          // 列域索引
Adds<int32_t>(idxP1, colIdx, 1, maskAllB32);
Gather(bndLo, bndsAddr, (RegTensor<uint32_t>&)colIdx, maskAllB32);
Adds<int32_t>(laneIdx, colIdx, (int32_t)rowBase, maskAllB32);   // part 域索引
partMask = UpdateMask<float, RegTensor<float>::trait>(sregPart);
Gather(partReg, partAddr, (RegTensor<uint32_t>&)laneIdx, partMask);  // rmw 读
for (uint16_t t = 0; t < wValidU16; ++t) {
    Duplicate(idxU32, (uint32_t)t);
    Gather(xBrcF, xAddr, idxU32, maskAllF);               // x[t] 广播
    Compares<int32_t, LE>(mLo, bndLo, (int32_t)(wBlkOff+t), maskAllB32);
    Compares<int32_t, GT>(mHi, bndHi, (int32_t)(wBlkOff+t), maskAllB32);
    And(mWin, mLo, mHi, maskAllB32);
    Select(selReg, xBrcF, zeroReg, mWin);                 // 空段自动 0
    Add(partReg, partReg, selReg, maskAllF);
}
Scatter(partAddr, partReg, (RegTensor<uint32_t>&)laneIdx, partMask);  // rmw 写
```

## 横切标签

`mask-tail`、`unaligned-2d`、`multi-dtype`。

## 实证来源

- `adaptive_avg_pool_3d` `compute_partial_sum`（30/30 max_diff=0.0，fp32/fp16/bf16 三组合）
