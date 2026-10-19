# sort-select — 排序 / 选择 VF 范式

> 类别范式总纲：判据 → 指令链选型 → 结构模板 → 陷阱。检索先读本文件，再读下方条目。

## 判据（结构信号）

VF 核心是**优先级序维护**：Top-K 选择/归并/终排序、字典序 (key, idx) 决胜、哨兵候选区管理。特征：需要把比较语义编码进位流，用 bitonic 网络或流式蓄水池在寄存器域完成排序。

## 指令链选型（标准三件套）

| 部件 | 标准链 | 要点 |
|------|--------|------|
| **构键**（比较语义→u32 位流） | `INT_SIGN_FLIP(bits^sign)` / `UINT_IDENTITY` / `FLOAT_TOTAL_ORDER` + `NaN→KEY_MAX(NAN_ON)` + `largest=0 整体 Not`；`Interleave-with-zero` 升域（u8 2级/u16 1级） | 全流 u32 域（Gather 不支持 B64）；python golden 与 kernel 逐位同构 |
| **bitonic 网络** | `SortPassIn`（窗内：Gather 自旋转 `lane^d` + 谓词 + Select 双流）+ `SortPassCross`（跨窗：**双窗写回**） | 调度 `s/t/w`：`kUp=AlignUp(k,2 幂)`，stage `s`、stride `t`、`d=2^(s-t)`、`dirBit=2^(s+1)`；跨窗 `if(w>=w^dw) continue` 每对窗单次 |
| **出口** | 原值窄化（`DeInterleave` 取 lo / int64 `Interleave` 重组）+ idx 还原（`Not` + `Interleave-with-zero` 第一输出） | **一个 `__simd_vf__` 只做一个目的的出口链** |

## 结构模板

四层：`__aicore__`（官方签名 + u32 KW 流 TBuf 注入）→ 编译期 Dispatch（CmpMode/Largest/Nan → 模板）→ 调度循环 → `__simd_vf__` 单窗函数 → `__simd_callee__`（构键/widen/流写回）。

## 横切标签

`multi-dtype`、`mask-tail`、`stateful-accumulator`（候选区持久）、`unaligned-2d`。

## 常见陷阱（最高频，top_k 系列 39 坑中跨算子最高价值）

1. **跨窗轮双窗写回**（根因#6）：跨窗 bitonic 要求同一快照对称交换；单窗独立写回会让后处理窗读到已覆盖值，min 侧永久丢失。python 模拟的原子交换天然无此问题——"模拟全过、kernel 多窗挂"是写回语义差异，非编译器 bug。
2. **UpdateMask 递减污染**（坑 31/37）：count 是**传入传出参数**（自动递减 VL_T）；同函数内二次 `UpdateMask` 拿到污染值。**所有 UpdateMask 调用先拷贝到局部变量**；probe 必须复刻生产 mask 形态。
3. **谓词布尔化顺序**（坑 33）：布尔链必须在 `wM=MaskOr(...)` 计算之后，读未初始化 MaskReg 会随机交换。
4. **ZEROING 清零后 store 用窄 mask**（坑 34）：无效 lane 需 allM 全宽写出（被下一窗覆盖）。
5. **单 VF 多目的链静默失效**（坑 35）：一个 `__simd_vf__` 内合体 val 窄化+idx int64 链，后位链结果被静默丢弃（无警告无报错）——多输出出口必须分函数。
6. **部分 mask 禁忌**（坑 4）：树形折叠/边界化用全窗 mask，禁部分 mask（垃圾 key 赢 max 导致整块空转）。
7. **升域构键域对齐**（坑 39）：扩域后的位级变换（取反/符号翻转）必须在原宽有效域内做（`Xor 掩码` 而非全宽 Not），保证跨段 key 值域逐位对齐。
8. **golden NaN 口径镜像**（坑 36）：kernel 有语义开关（模板 bool nanMode），golden 必须显式镜像同一开关。
9. **u64→int64 保序平移**（坑 36b）：`(x - 2^63).view(np.int64)`，禁 `astype`（wrap 破坏 u64 字典序）。
10. **ShiftLefts/ShiftRights 标量必须 int16_t**（坑 38）：U 模板参数仅支持 int16_t。

## 条目索引

| 条目 | 内容 | 标签 |
|------|------|------|
| `experience-key-lexicographic.md` | 构键三模式 + NaN + largest、padding 三元组、u8/u16 升域、域对齐、golden 口径（NaN 镜像/保序平移/bit-exact） | `multi-dtype`, `mask-tail` |
| `experience-bitonic-network.md` | bitonic 调度、跨窗双窗写回、谓词布尔化、单 VF 单目的出口、probe 轮次截断方法论 | `multi-dtype` |
| `experience-u64-dual-stream.md` | u64 键拆 hi/lo 双 u32 流（DeInterleave）、树形折叠替代 UB 往返、负 idx 符号扩展还原 | `mask-tail` |

## 实证来源

`top_k/` 9 份 lesson（top_k_select / sort_emit_top_k / init_candidates / init_cand_region / local_top_k_merge / local_top_k_seg / merge_ws_batch / final_sort / final_sort_cand，已迁移，原 lesson 在算子 record dir）。
