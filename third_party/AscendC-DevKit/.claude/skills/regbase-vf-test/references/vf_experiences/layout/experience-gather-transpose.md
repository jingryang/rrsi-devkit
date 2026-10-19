# 目标行 Gather 转置（索引零搬运 + 双重折叠）

## 适用判据

UB 内 2D tile 就地转置 `y[j][i] = x[i][j]`。A5 RegBase 无 strided store/转置指令（StoreDist 仅 NORM/PACK/INTLV/FIRST_ELEMENT），用 **Gather（UB 源，四参版）按目标行收集源列**。

## 关键实现要点

1. **双重折叠**：行号 j 与段偏移 `s*VL*srcPitchElems` 都折叠进 Gather 的 **baseAddr 指针算术**（`__ubuf__` 指针 64 位域无溢出），寄存器索引只保留 `k*pitch`（k<VL≤128，值域远小于 u16 max）。
2. **索引零搬运**：不依赖 host 索引表、不加额外 tensor 参数。`Arange<IS>(reg,0)` 生成 [0,VL)，`Muls` 乘 pitch 得段内索引；Arange 无 unsigned dtype，用有符号别名 `IS`(int16/int32) 生成，位模式经 `RegTensor<IX>&` reinterpret 为 unsigned 索引读取。
3. **段偏移不进寄存器**：`Adds<u16>` 段偏移溢出（中间值 >32767 即错乱，int8 224×224 实测段 1 全错）；`Muls<u16>` 无符号域问题（域边界用例 51816/52832 >32767 全过）——两者行为不同，勿混淆。
4. **b8 路径**：Gather 四参版不支持 b8→b8（配套表仅 b8→b16 零扩展）：
   `Gather(wideReg_u16, xUb8+..., idx_u16, mask16)`（b16 宽度）→ `DeInterleave(evenReg, oddReg, wideReg, wideReg)` 同源自解交错压紧偶字节 → `StoreAlign(yUb8+..., evenReg, mask8)`。`Pack` 是备选但输出布局不确定，DeInterleave 更可靠。
5. **b8 UpdateMask 计数陷阱（最深坑）**：`UpdateMask<uint8_t>` 按 VL_T=256 递减，但 b8 段每段只产 128 个有效元素——共享计数器跨段 → 段 0 mask 越界（越 evenReg 有效区 128）+ 段 1 计数下溢丢数据。**每段独立 `min(remain,128)`**（`remain - over*(remain-128)` 无分支 min），在 `__simd_callee__` 内、循环体外初始化（满足 static_check）。
6. **2D 对齐搬运**：CopyIn `DataCopyPad(xLocal, xGm, {tm, tn*ds, 0, 0, 0}, pad)` —— `dstStride=0` 时 DMA 自动把每行 pad 到 32B，UB 布局天然 = 契约 pitch 语义；CopyOut 同理 `srcStride=0`。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| 测试 42/42 全过但判 CK-VF 签名失配 | 签名 7 参（多 idxLocal+IDX_T 模板参）≠ 契约 6 参 | 索引改寄存器内 Arange+Muls 生成，签名严格匹配契约（manifest 声明 deviation 不能替代） |
| int8 tm=224 段 1 全错（bad cols 恰从 128 起） | b8 计数器 VL_T=256 递减：段 0 越界写 + 计数下溢段 1 mask 失效 | 每段 callee 内重算 `min(remain,128)` 独立计数 |
| min 公式写错 `remain - over*VL` → bad cols [tm-128,128) | 224-128=96 ≠ min(224,128)=128 | 正确 `remain - over*(remain - VL)` |
| static_check hardware_loop_var_mutation | UpdateMask 计数在循环体内初始化 | 段循环抽到 `__simd_callee__`，计数循环外初始化 |
| `T type is not correct`（b8 Store） | evenReg 声明 uint8_t 而 DX=int8_t | 寄存器声明统一 DX，reinterpret 仅用于 DeInterleave |

## 可复用模式（最小骨架）

```cpp
template <typename DX, typename IX, typename IS>   // IX: u16/u32, IS: int16/int32
__simd_callee__ inline void TransposeRowSegs(__ubuf__ DX* xUb, __ubuf__ DX* yUb,
    uint16_t rowJ, uint16_t tm, uint16_t segCount, uint32_t srcPitchElems, uint32_t dstPitchElems)
{
    constexpr uint16_t VL = GetVecLen() / sizeof(DX);
    RegTensor<IS> arangeReg;  RegTensor<IX> idxReg;  RegTensor<DX> dstReg;
    MaskReg maskFull = CreateMask<IX>();
    uint32_t rem = tm;                       // 循环外初始化（static_check 规约）
    Arange(arangeReg, (IS)0);
    Muls((RegTensor<IS>&)idxReg, arangeReg, (IS)srcPitchElems, maskFull);
    for (uint16_t s = 0; s < segCount; ++s) {
        MaskReg mask = UpdateMask<DX>(rem);  // 自然递减（VL_T==VL 时成立）
        Gather(dstReg, xUb + rowJ + s*VL*srcPitchElems, idxReg, mask);  // 段偏移进基址
        StoreAlign(yUb + rowJ*dstPitchElems + s*VL, dstReg, mask);
    }
}
```

## 横切标签

`multi-dtype`、`mask-tail`。

## 实证来源

- `transpose` `transpose2_d_tile`（53/53 bit-exact：7 dtype × 规范场景 + 4 个 u16 索引域边界用例）
