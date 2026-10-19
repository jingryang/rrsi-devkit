# 状态张量初始化 / 常量 / 哨兵填充标准形

## 适用判据

VF 职责是**填充/初始化状态张量**：清零累加器（`acc[i]=0.0f`）、常量填充、或**哨兵位模式**填充候选区（`candVal 全 k 槽=方向反侧极值位模式`、`candIdx 全 0/-1`）。不依赖输入张量，只写不读（或读输入 cast 后填充）。

## 关键实现要点

1. **递减掩码填充标准形**（零分支）：`Duplicate(reg, 常量)`（循环外外提，2 参不带 mask 整寄存器广播）+ 循环内 `mask = UpdateMask<T,trait>(cnt)`（cnt 传入传出自动递减 VL_T）+ `StoreAlign(ub + i*VL, reg, mask)`——各流按 `VL(T)` 满窗滚动（u8:256/u16:128/u32:64/u64:32），尾窗部分掩码天然不越写；双流独立同型 mask（DX 域管 val、int64 域管 idx）。
2. **位模式标量传递**：uint64 参数在 `__aicore__` 层按字节拷贝 bit-cast 到 DX 标量（小端低位=DX 位模式），再作 `__simd_vf__` 标量参数 + `Duplicate` 广播——全程无数值 Cast，float 系 -inf/-NaN 位模式无损。
3. **哨兵位模式类型路由——指针 tag dispatch**（无宏环境最稳）：`Ret SentinelBitsOf(const DXType*, largest)` 重载函数族 + `SentinelBitsOf(static_cast<const DX*>(nullptr), largest)` 调用，编译期零开销；不依赖文件级宏、`<type_traits>`/IsSameType（ccec 兼容性最稳）。
4. **运行时 flag 分发**：useSkip/useBias 等运行时标量不能进 `__simd_vf__` 循环体——`__aicore__` 层 if/else 分发到多条无分支 `__simd_vf__`（如 4 路径）。
5. **越写检测三件套**：GM 背景 CopyIn（val=0xA5、idx=0x5A5A..）→ VF 覆写 [0:k) → **全长 AU256 搬出**，Python 验证 `[k:AU]` 背景不变——比仅验 [0:k) 严格（抓尾窗 mask 失效越写）。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| 清零输出与"未写"不可区分 | 写 0 与初值 0 无差异 | **双重哨兵**：GM 预填 777 + kernel 先把 UB buffer 脏化填 777 再测被测 VF（partial mask 漏写留下 777）；输出 0xCC 魔数初始化防 data-unchanged 假阳性 |
| `for(uint16_t t=0; t<hasTail; ++t){ Callee(...); }` 编译 exit 139（clang crash） | ccec 后端对"运行时 0/1 次循环 + VF callee 调用"的调度缺陷 | 尾窗用 **UpdateMask 递减模式**替代条件调用（凡"尾窗单独处理"优先递减掩码而非条件循环） |
| OOB data-unchanged 假阳性（输出恰全 0 且初始化全 0） | 检测=前后快照对比，全 0 未变化误判 | 输出数组初始化非零魔数 0xCC（真未写保持 0xCC FAIL；正确写 0 有变化） |
| float 哨兵方向反转 | 哨兵用 NaN 位模式被构键 KEY_MAX 捕获反转为最优侧 | float 系哨兵取 ±inf（见 sort-select key 条目位模式表） |
| `#if/#else` 在 `__simd_vf__` 体内被 static_check 当 runtime 分支 | 检查器扫描文本无法区分预处理 | `#if` 移到函数定义级别（包裹整个函数） |

## 可复用模式（最小骨架）

```cpp
constexpr uint32_t REPEAT_STRIDE = AscendC::GetVecLen() / sizeof(T);  // fp32=64
__simd_vf__ inline void InitFillImpl(__ubuf__ T* addr, const T scalar, const uint32_t totalElems)
{
    RegTensor<T> zReg; MaskReg mask;
    uint32_t sreg = totalElems;
    uint16_t repeatTime = static_cast<uint16_t>((totalElems + REPEAT_STRIDE - 1) / REPEAT_STRIDE);
    AscendC::Reg::Duplicate(zReg, scalar);           // loop-invariant hoist
    for (uint16_t i = 0; i < repeatTime; ++i) {
        mask = AscendC::Reg::UpdateMask<T, RegTensor<T>::trait>(sreg);
        AscendC::Reg::StoreAlign(addr + i * REPEAT_STRIDE, zReg, mask);
    }
}
```

## 横切标签

`mask-tail`、`multi-dtype`（DTYPE_CODE 三态）。

## 实证来源

- `adaptive_avg_pool_3d` `init_acc`（10/10 max_diff=0.0，双重哨兵可观察性）
- `moe_finalize_routing` `init_accumulator`（flags 分发 4 路径 + 2B→4B Cast 填充）
- `top_k` `init_candidates`（450/450，越写检测三件套 + 坑 31/32）
- `top_k` `init_cand_region`（210/210，指针 tag dispatch + 哨兵位模式表）
