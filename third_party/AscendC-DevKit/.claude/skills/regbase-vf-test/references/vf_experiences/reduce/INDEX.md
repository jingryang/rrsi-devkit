# reduce — 归约 / 累加 VF 范式

> 类别范式总纲：判据 → 指令链选型 → 结构模板 → 陷阱。检索先读本文件，再读下方条目。

## 判据（结构信号）

VF 核心是**把一段/多段输入收敛为更少的输出**（N:1 或 N:M, M<N）：行归约 sum/max/min/mean、变长段求和、等长段向量累加、softmax 两遍归一。**累加目标常是持久/跨调用状态**（见 `stateful-accumulator` 生命周期，二者常成对出现）。

## 指令链选型

| 形态 | 标准链 | 要点 |
|------|--------|------|
| 等长段向量规约 | `for j(出块){ segReg=0; for s(段){LoadAlign+Add}; Load(acc2)+Add+Store }` | 段累加在**寄存器域**完成再一次性并入；段起点行距必须 32B 对齐 |
| 变长段（无分支转置） | `Gather 广播 x[t] + 窗口掩码(Compares+And+Select) + Add 到整行 partReg` | "贡献转置"：逐输入元素广播、按窗口掩码加到 64 个累加器 lane，w 维度标量序无分支 |
| 行归约（softmax） | `ReduceMax → Sub → Exp → ReduceSum`，中间全 fp32 | 每行 sumExp 用 `StoreAlign<DIST_FIRST_ELEMENT_B32> + VL1` 写首元素 |
| max+argmax 行内配对归约 | `Compare(GT)+Compare(NE 自比)+Select`（值/idx **双 Select**）→ `Reduce(MAX)` + NaN 首见 + `Reduce(MIN)` 取首见 idx | idx 走独立 int64 通路，与值同 mask 双 Select 严格同步；不用 `PairReduceElem`（仅 SUM + half/float） |
| 折叠保护 | main（maskFull）+ tail（maskTail + Select）分离 | 累积操作防 partial mask 下 ZEROING 清零已累加值 |

## 结构模板

两层 SIMD（`__aicore__` + `__simd_vf__`）或 SIMT（`__simt_vf__`，见 `gather-scatter/experience-simt-async-infra.md`）。r×j×t 多层 `uint16_t` 硬件循环，循环不变量外提。

## 横切标签

`mask-tail`（尾块 mask 只挂 Store）、`unaligned-2d`（非对齐行距→Gather/Scatter）、`simt-async`（SIMT 窗口累加）、`multi-dtype`。

## 常见陷阱（最高频）

1. **LoadAlign 非 32B 对齐地址 → VEC_ERROR**：紧密布局行基址非 8 倍数时，行读取/索引读取必须用 `Gather`（元素索引，无对齐要求），不可 LoadAlign 偏移 +1 之类。
2. **浮点折叠序**：`acc2 + (((0+w0)+w1)+…)` 左折叠序必须与 golden 逐序一致（fp32 不结合，可差 1 ulp）。
3. **LoadAlign 过读余量**：末块读可越出实际长度，UB 分配留 `+128 元素` PAD_ELEMS 余量。
4. **首段禁 `pregFull`（ALL mask）**：`dimSize < VL` 时首段必须 `UpdateMask(dimSize)`，每段统一递减。
5. **winBnds 索引域与累加器索引域分离**：Gather 读表用列索引、part 用行基址+列索引，两域混用会被 rowBase=0 掩盖、≠0 时读错。
6. **跨批持久**：kernel 入口 batch 循环调 VF 模拟链式调用，验证 rmw 位级正确。

## 条目索引

| 条目 | 内容 | 标签 |
|------|------|------|
| `experience-contribution-transpose.md` | 变长段求和"贡献转置"（Gather 广播 + 窗口掩码 + Select），Gather/Scatter 元素索引、winBnds 索引域分离 | `mask-tail`, `unaligned-2d` |
| `experience-equal-length-reduce.md` | 等长段向量规约、对齐行距选型、折叠序位级锁定、LoadAlign 过读余量 | `mask-tail` |
| `experience-max-argmax-reduce.md` | max+argmax 值/idx 双 Select 配对归约、NaN 首见、int64 下标、6 dtype、PairReduceElem 仅 SUM 的坑 | `reduce`, `argmax`, `multi-dtype`, `nan-aware`, `int64-index` |
| `experience-softmax-normalize.md` | 两遍归一化、fp32 中间精度、首段 mask、DIST_FIRST_ELEMENT、buffer +256 guard | `multi-dtype`, `mask-tail` |
| `experience-online-softmax-columnblock.md` | 跨步列块 online-softmax（统计 pass+输出 pass）、mRun/sRun 跨 tile 常驻、行内中间量寄存器化、rescale −inf 初值 | `multi-dtype`, `reduce`, `stateful-accumulator`, `unaligned-2d` |

## 实证来源

`adaptive_avg_pool_3d/compute_partial_sum_vf_lesson.md`、`adaptive_avg_pool_3d/merge_partial_sum_vf_lesson.md`、`softmax/*_lesson.md`（已迁移，原 lesson 在算子 record dir）。
