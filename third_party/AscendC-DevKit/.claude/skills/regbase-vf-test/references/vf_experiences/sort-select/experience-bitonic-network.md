# bitonic 排序网络（调度 + 跨窗双窗写回 + 单 VF 单目的出口）

## 适用判据

候选区/窗口内排序：`SortPassIn`（窗内轮）+ `SortPassCross`（跨窗轮）的 bitonic 网络。适用任意"全排序取前 k / 终序校准 / 归并"类 VF（独立输出或就地写回变体共享同一网络基座，仅出口目标指针不同）。

## 关键实现要点

1. **调度参数化**：`kUp = AlignUp(k, 2 幂)`（最小 2）；stage `s∈[0,log2kUp)`，合并长度 `2^(s+1)`、`dirBit=2^(s+1)`；stride `t∈[0,s]`、`d=2^(s-t)`；窗 = u32 域前 32 lanes。
2. **窗内轮（d<32）**：`offPair = lane ^ d`（Gather 自旋转）；`p = lane&d`、`h = lane&dirBit`；`winXH = ((offSelf&d)!=0) ^ ((offSelf&dirBit)!=0)` 编码窗基方向位。
3. **跨窗轮（d≥32）**：`dw=d/32`、`offPair=(w^dw)*32`；p/h 恒 0；**`if (w >= (w^dw)) continue` 每对窗只处理一次 + 双窗写回**。
4. **swap 谓词合成**：`swap = wM ^ p ^ h ^ winXH` 布尔链（u32 域 0/1 Xor，`NE+Select` 数据化）→ 1 次 Compare 得 swapM → 每流 1 次 Select。
5. **流布局**：非 int64 3 流 `[kHi=key_widened, kLo=~idx_lo, v=val_widened]`；int64 5 流（key_hi/key_lo/~idx_lo/val_lo/val_hi）。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| 多窗（kUp≥64）单点错@窗对末 lane → 大片错 | **跨窗轮单窗独立写回破坏对称性**：w 先写窗 w（max 侧），w^dw 后 Load 到已覆盖值 → 判定 EQ → 也取 max → min 侧永久丢失。python 模拟原子交换天然无此问题 | **每对窗一次调用 + 双窗写回**（同一快照对称交换）；模拟与 kernel 的写回语义差异是"模拟全过、kernel 挂"的假象，勿误诊为编译器调度 |
| swap 谓词随机、交换网络大面积失效 | 布尔链放在 `wM = MaskOr(...)` 计算之前——读未初始化 MaskReg | 布尔链必须在 wM 计算之后（照搬代码保持原语句序） |
| 构键后 idx 无效 lane 残留 UB 旧垃圾被当真值交换 | ZEROING 已清 0 但 `StoreAlign(..., mW)` 只写 winElems lane——无效 lane 区没被写过 | ZEROING + **store 用 allM 全宽写出**（无效 lane 写 0 可被下一窗覆盖，顺序执行无冲突） |
| 合体出口链后位静默失效（idx 恒输出 0，无警告无报错） | 一个 `__simd_vf__` 内合体 val 窄化链 + idx int64 链，寄存器/调度冲突丢结果；各种外围调整无效 | **拆分为独立 `__simd_vf__`**（WriteValWin + WriteIdxWin）；一个 VF 只做一个目的的出口链 |
| log2kUp 算错 → kUp 越界写坏相邻 TBuf | `kUp=2` 边界 | `while(v>1){++l;v>>=1;}` |
| 方向位用配对距离位而非合并块位 | 值两两复制 | dirBit=2^(s+1) + 对称交换公式 |

## 可复用模式

- **调试方法链**：python 全轮次模拟（64/64）→ 轮次截断 probe（stopS/stopT + KW 流全量 dump + 逐截断点对比）→ 首分歧轮定位——多窗/多轮网络类 VF 标准定位手段。
- **读路径 swap 试验**：idx 源临时改读已知正确的 kHi 流，是区分"上游数据错 vs 本函数链路坏"的决定性手段（比 dump 流内容更快）。
- **跨 seg/批链式测试**：kernel 入口 for 循环调官方签名（cand 在 UB 跨调用迭代）模拟真实链式使用。
- **单模板签名 DK 推导**：`DkOf<DX>` sizeof 条件类型映射，适配单模板签名而内部复用双模板基座。

## 横切标签

`multi-dtype`、`mask-tail`。

## 实证来源

- `top_k` `sort_emit_top_k`（2 轮 119/119；根因#6 跨窗双窗写回 + 坑 25-30）
- `top_k` `local_top_k_merge`（140/140；坑 33/34/35）
- `top_k` `local_top_k_seg` / `merge_ws_batch` / `final_sort` / `final_sort_cand`（154/154、154/154、168/168、168/168）
