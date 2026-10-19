# u64 键双 u32 流折叠（DeInterleave 拆流 + 树形折叠替代 UB 往返）

## 适用判据

排序/选择 VF 的 key 或 val 是 64-bit（int64/uint64），需要在 u32 域工作流中处理。**Gather 仅支持 1/2/4 字节源**（`Gather<u64,...>` 编译期 static_assert 拒绝，dav_3510 实测），64-bit 数据必须拆成 hi/lo 双 u32 流。

## 关键实现要点

1. **u64 寄存器 u32 视图**：`[lo0, hi0, lo1, hi1, ...]`（little-endian 相邻 b32 槽）。
2. **拆流**：`DeInterleave<u32>(lo, hi, (u32&)k64, (u32&)z64)` → lo=低流/hi=高流（lanes 0..31 有效，32..63=0）；反向 `Interleave<u32>(m0, m1, lo, hi)` 完美还原 u64 布局（split 逆操作）。
3. **树形折叠（替代 u64 Reduce + UB 往返）**：每级 `Gather×2 + hi 两级比较(GT/EQ) + lo(GE/LE) + MaskAnd/MaskOr + Select 双流同步`——**全纯寄存器**。u64 的 Reduce→Store lane0→LocalMemBar→Gather UB 往返在主 kernel 环境（寄存器压力/软件流水）下会吞写（key 写 idx 不写/提取=lane0 原值），必须消除。
4. **双流联动**：比较结果（树形折叠、插入判定）同时作用于 hi/lo 双流，保证 64 位序正确。
5. **负 idx 哨兵无损还原**：idx 流全程 u32（`~idx_lo`），出口还原 int64 需**符号扩展**——`Xor 0xFFFFFFFF` 取 lo 后 `Interleave(lo, zero)` 高 32 位恒 0，哨兵 -1 的 lo=0xFFFFFFFF 需要 hi=0xFFFFFFFF：`And(0x80000000)+Compare NE → Select(hi) → Interleave(lo, hi)`。真实 idx<2^31 的 bit31=0 不受影响。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| `Gather<u64,u64,u32>` static_assert | dav_3510 Gather 不支持 B64 | 全流 u32 化（u64 拆双 u32 流）；配对 `Gather<u32,u32,u32>` |
| int64 插入链失效（key 写 idx 不写） | u64 每轮 UB 往返 Fold（≥5 次）被寄存器压力/软件流水吞写 | hi/lo 双 u32 流树形折叠（probe17 验证） |
| 哨兵 key 后半槽写失败 | u64 下 `Select dst=src0` 两态不可靠 | 独立 dst Select + Xor 物化 |
| 出口 idx 输出 4294967295 ≠ -1 | 零扩展还原哨兵 -1（高 32 位恒 0） | bit31 符号位检测 + Interleave 符号扩展 |
| `ShiftLefts/ShiftRights` 标量 static_assert | U 模板参数仅支持 int16_t | `static_cast<int16_t>(32)` |

## 可复用模式（最小骨架）

```cpp
// 拆流 + 双流树形折叠（任何 u64 键值比较 VF 的标准入口）
DeInterleave<u32>(lo, hi, (u32&)key64, (u32&)zero64);   // lo=低 32 流, hi=高 32 流
// 每级折叠（strides 32..1）：
Gather(x, lo, lane^d, mask);  Gather(y, hi, lane^d, mask);
// hi 两级比较 + lo 相应比较 + MaskAnd/Or + Select 双流同步
```
- `UpdateMask<u64>` count ≤ 32 才精确（u64 VL=32）：所有 64 位窗按 32 元素或 64-lane(u32) 设计，保持递减同构。
- probe17 四项实证：P1 u32 视图布局 / P2 拆流 / P3 Interleave 还原 / P4 双流树形折叠。

## 横切标签

`mask-tail`、`multi-dtype`。

## 实证来源

- `top_k` `top_k_select`（第 3 轮 60/60；根因#8 经 u64 双流化根治 + probe17）
- `top_k` `sort_emit_top_k`（int64 三流 `[kHi,kLo,k3=~idx]`，谓词 4 级级联）
- `top_k` `local_top_k_seg`（坑 36a 负 idx 符号扩展还原）
