# LocalMemBar —— VF 内流水线同步屏障

> **概述**：`LocalMemBar` 是 A5 Regbase VF 函数内的**显式同步屏障**，用于跨流水线的读写依赖保护。它是 norm 类算子的"心脏"——ops-nn 全库 304 处真实使用中 69% 集中在 norm 目录，是多 pass 归一化算法的必备构件。

**本文档定位**：这是一份**行为原理型**指南，不重复官方 API 参考。官方文档见：
- [LocalMemBar](../../../ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/同步控制/LocalMemBar.md)（含 API 签名 + 12 种合法组合）

---

## 1. 为什么 VF 内需要显式 barrier

### 1.1 硬件视角：VF 内的并行流水

A5 芯片在一个 VF 函数内部**同时有多条独立流水线**运转：

| 流水线 | 处理指令类型 | 触发的 MemType |
|---|---|---|
| Vector Store | 寄存器 → UB 的向量搬运 | `VEC_STORE` |
| Vector Load  | UB → 寄存器的向量搬运 | `VEC_LOAD` |
| Scalar Store | 标量写入 UB | `SCALAR_STORE`（Duplicate 等） |
| Scalar Load  | 标量从 UB 读取 | `SCALAR_LOAD`（C 数组下标访问） |

**关键事实**：这些流水线是**独立发射、异步执行**的。一条 `StoreAlign` 指令进入 Vector Store 队列后并不会立即完成写入 UB——它可能在几个周期后才 commit。**在这几个周期内，如果 Vector Load 流水线去读同一 UB 地址，会拿到旧值**。

### 1.2 编程视角：编译器只对"同一寄存器"做保序

编译器能做的同步是有限的：

```cpp
// ✅ 编译器能保序：同一寄存器的读写依赖
Add(dstReg, srcReg0, srcReg1, mask);
StoreAlign(dstAddr, dstReg, mask);       // 依赖 dstReg，等 Add 完成才 store
```

```cpp
// ❌ 编译器不保序：跨迭代的同 UB 地址访问
for (i = 0; i < N; i++) {
    // 上一轮的 store 与本轮的 load 通过 UB 地址间接依赖
    StoreAlign(workAddr + i, resReg, mask);      // 上一轮 store
    LoadAlign(loadReg, workAddr + i - 1);        // 本轮 load 前一位置
}
```

编译器**看不出**"上一轮 store 的地址就是本轮 load 的地址"——因为地址是**运行时值**，静态分析无能为力。**这就是 LocalMemBar 存在的原因**。

### 1.3 与 mask 的分工关系

Mask 和 barrier 是 A5 VF 编程的两大控制机制，分工明确：

| 机制 | 决定什么 | 影响什么 |
|---|---|---|
| **Mask**（CreateMask/UpdateMask） | 哪些 lane 参与计算 | 空间维度 |
| **Barrier**（LocalMemBar） | 指令的执行顺序 | 时间维度 |

**判定口诀**：
- **一段 UB 只被写、不被后续读** → 只需 mask（tail 处理）
- **一段 UB 被写完后被后续读** → 必须 barrier（依赖同步）

### 1.4 陷阱视角：barrier 错了会静默出错

Barrier 相关的错误**编译器不报错**，只在精度测试时暴露：

- **缺 barrier**：数据竞争，读到旧值，精度错乱
- **方向反了**：`STORE→LOAD` 与 `LOAD→STORE` 语义完全不同
- **多余 barrier**：性能损失（norm 类算子实测吞吐下降 20~30%）

---

## 2. API 签名（自包含参考）

### 2.1 函数原型

```cpp
namespace AscendC::Reg {
    template <MemType src, MemType dst>
    __simd_callee__ inline void LocalMemBar();
}
```

**特征**：
- 编译期确定 src/dst 组合（模板参数）
- 无运行时开销的指令级屏障
- **只能在 `__simd_vf__` / `__simd_callee__` 函数内使用**（`__aicore__` 层用 PipeBarrier）

### 2.2 MemType 六种取值语义

```cpp
enum class MemType {
    VEC_STORE,      // Vector 写 UB（StoreAlign / StoreUnAlign / DataCopy(reg→UB)）
    VEC_LOAD,       // Vector 读 UB（LoadAlign / LoadUnAlign / DataCopy(UB→reg)）
    SCALAR_STORE,   // Scalar 写 UB（Duplicate 等）
    SCALAR_LOAD,    // Scalar 读 UB（GetValue、C 数组下标访问）
    VEC_ALL,        // Vector 所有读写流水线
    SCALAR_ALL      // Scalar 所有读写流水线
};
```

### 2.3 官方 12 种合法组合 vs 真实 4 种

**官方文档列出 12 种合法组合**（表 3），但 ops-nn 全库真实使用高度集中：

| MemType 组合 | 官方合法 | ops-nn 使用次数 | 备注 |
|---|---|---|---|
| `VEC_STORE → VEC_LOAD` | ✅ | **245** | 写后读，主流场景（RAW） |
| `VEC_LOAD → VEC_STORE` | ✅ | **28** | 读后写（WAR），in-place 保护 |
| `VEC_STORE → VEC_STORE` | ✅ | **16** | 写后写（WAW），pad+data 双写 |
| `VEC_STORE → SCALAR_LOAD` | ✅ | **1**（ops-math） | 跨流水线，极稀有 |
| `VEC_STORE → SCALAR_STORE` | ✅ | 0 | 未见工程使用 |
| `VEC_LOAD → SCALAR_STORE` | ✅ | 0 | 未见工程使用 |
| `SCALAR_STORE → VEC_LOAD` | ✅ | 0 | 未见工程使用 |
| `SCALAR_STORE → VEC_STORE` | ✅ | 0 | 未见工程使用 |
| `SCALAR_LOAD → VEC_STORE` | ✅ | 0 | 未见工程使用 |
| `VEC_ALL → VEC_ALL` | ✅ | 0 | 粗粒度同步，工程未采用 |
| `VEC_ALL → SCALAR_ALL` | ✅ | 0 | 同上 |
| `SCALAR_ALL → VEC_ALL` | ✅ | 0 | 同上 |

**关键推论**：**掌握前 4 种就覆盖了 99%+ 场景**。SCALAR_STORE / SCALAR_ALL / VEC_ALL 属于"理论合法但工程未采用"——`VEC_ALL` 太粗粒度会伤性能，SCALAR 系列涉及场景本身在 A5 里少见。

---

## 3. 行为本质【核心】

### 3.1 VF 内的三条流水线并行模型

```
   __simd_vf__ 函数内的并行流水（时序自左向右）
   
   Vector 流水  │  LoadAlign ──► Compute ──► StoreAlign  ─────────────────────►
                │                                        ▲
                │                        ┌───────────────┘
   LocalMemBar  │       ★═══════════════ 屏障 ═══════════════★
                │                        │
                │                        ▼
   Vector 流水  │                                        LoadAlign ──► ...  ──►
   （下一 pass）│                                        
   
   Scalar 流水  │  GetValue ──►  ─────────►  Duplicate ──►  ────────────────────►
                │                                        独立流水，与 Vector 无关
                │                                        除非跨流水 barrier
```

**关键理解**：
- Vector 和 Scalar 是**两条独立的流水线**，各自有独立队列
- 同一流水线内的指令**未必按代码顺序完成**（硬件可乱序发射）
- **只有 barrier 能强制"屏障之前的所有 src 类型指令完成后，才允许 dst 类型指令开始"**

### 3.2 三种依赖类型 —— RAW / WAR / WAW

CPU 领域用 RAW/WAR/WAW 描述指令间的三种数据依赖，这个模型在 A5 上完全适用：

**RAW（Read-After-Write）—— 写后读**

```
时序：  ...  STORE addr[X]  ...  LOAD addr[X]  ...
             │                    │
             ▼                    ▼
        写入 UB              读取 UB
        （异步）             （必须读到写完的值）

barrier: VEC_STORE → VEC_LOAD
用途：   protect_read_sees_write
```

**代表场景**：树形 reduce（每轮结果写回 UB，下一轮读回来继续合并）

**WAR（Write-After-Read）—— 读后写**

```
时序：  ...  LOAD addr[X]  ...  STORE addr[X]  ...
             │                    │
             ▼                    ▼
        读取 UB              覆盖同一地址
        （必须读完）         （不能覆盖未读完的值）

barrier: VEC_LOAD → VEC_STORE
用途：   protect_read_from_overwrite
```

**代表场景**：in-place 累加更新（读旧值 → 加新值 → 写回同一位置）

**WAW（Write-After-Write）—— 写后写**

```
时序：  ...  STORE addr[X]  ...  STORE addr[X]  ...
             │                    │
             ▼                    ▼
        第一次写入            第二次写入
        （不能被后写覆盖）    （必须在第一次之后）

barrier: VEC_STORE → VEC_STORE
用途：   protect_write_order
```

**代表场景**：Pool 类算子的 pad+data 双写（先写 padding 值填满，再用有效数据部分覆盖）

### 3.3 编译器保序 vs 手动 barrier 的边界

不是所有依赖都需要 barrier，编译器能自动处理一部分：

| 场景 | 编译器保序？ | 需要手动 barrier？ |
|---|---|---|
| 同一寄存器的读写依赖 | ✅ 是 | ❌ 不需要 |
| 同一段代码内的静态可分析地址 | ✅ 是（简单场景） | ❌ 不需要 |
| **跨迭代的同 UB 地址访问** | ❌ 否 | ✅ **需要** |
| **不同寄存器但同 UB 地址** | ❌ 否（编译器不做地址别名分析） | ✅ **需要** |
| **跨流水线（Vec ↔ Scalar）** | ❌ 否 | ✅ **需要** |
| 循环内 store 后紧接 load 同地址 | ❌ 否 | ✅ **需要** |

**判定原则**：**只要 UB 地址依赖的"两端"分别在不同的循环迭代 / 不同流水线 / 不同函数调用**，就必须手动 barrier。

### 3.4 Store Buffer Forwarding 陷阱

有一种反直觉的场景：**"读后立刻写"也需要 barrier**。

原理：A5 硬件有 **store buffer forwarding** 优化——store 指令进入 store buffer 后，如果后续 load 检测到地址匹配，会**直接从 store buffer 转发**，跳过 UB 读取。但如果编译器发射顺序是：

```
LOAD addr[X]  → r1     # 期望读旧值
STORE addr[X] → r2     # 立刻覆盖
LOAD addr[X]  → r3     # ???
```

硬件可能让第 3 条 load 从 store buffer forwarding，读到 r2（新值），而不是 UB 里的旧值。**这在 in-place 累加场景是灾难**——本该保留的旧累积值被冲掉。

因此需要 `VEC_LOAD → VEC_STORE` barrier：强制 store 只能在 load 完全完成后才启动。

---

## 4. 关键参数深度解析

### 4.1 MemType 六种取值场景表

| MemType | 触发的指令 | ops-nn 使用 | 典型场景 |
|---|---|---|---|
| `VEC_STORE` | `DataCopy`(reg→UB) / `StoreAlign` / `StoreUnAlign` / `Store` | 高频 | 反量化写出、reduce 中间结果 |
| `VEC_LOAD` | `DataCopy`(UB→reg) / `LoadAlign` / `LoadUnAlign` / `Load` | 高频 | 数据搬入、tree-reduce 输入 |
| `SCALAR_STORE` | `Duplicate` 到 UB | 未见工程使用 | 理论存在，暂无高频场景 |
| `SCALAR_LOAD` | `GetValue` / C 数组下标访问 | 1 次 | 混合 vec+scalar 编程 |
| `VEC_ALL` | 所有 Vector 流水 | 未见工程使用 | 粗粒度同步（会伤性能） |
| `SCALAR_ALL` | 所有 Scalar 流水 | 未见工程使用 | 粗粒度同步 |

### 4.2 四种真实组合的选型决策表

| 组合 | 频次 | 语义 | 典型场景 | 常见算子 |
|---|---|---|---|---|
| `VEC_STORE → VEC_LOAD` | 245 | RAW 保护 | 树形 reduce 各轮之间、多 pass 之间 | `add_rms_norm`、`softmax_v2`、`layer_norm` |
| `VEC_LOAD → VEC_STORE` | 28 | WAR 保护 | in-place 累加、split 累积 | `adaptive_avg_pool2d`、`layer_norm_v3` |
| `VEC_STORE → VEC_STORE` | 16 | WAW 保护 | Pool 的 pad+data 双写 | `max_pool_v3`、`avg_pool` |
| `VEC_STORE → SCALAR_LOAD` | 1 | 跨流水 | Vector 写 + C 下标读 | 极稀有 |

**选型口诀**：**"上一段代码最后一条 VF 指令"→"下一段代码第一条 VF 指令"**。看这两条指令属于哪个流水线，直接决定 src/dst。

**示例**：
```cpp
DataCopy(workAddr + i, resReg, mask);     // 最后是 store  → src = VEC_STORE
LocalMemBar<..., ...>();                   // barrier
DataCopy(loadReg, workAddr + i - 1);      // 第一条是 load → dst = VEC_LOAD

// 结果：LocalMemBar<VEC_STORE, VEC_LOAD>()
```

### 4.3 barrier 插入位置策略

**位置 1：循环内每轮末尾/开头**（当循环内有 store→load 依赖）

```cpp
for (i = 0; i < N; i++) {
    DataCopy(workAddr + i * VL, resReg, mask);     // 本轮 store
    LocalMemBar<VEC_STORE, VEC_LOAD>();             // 本轮 barrier
    DataCopy(nextReg, workAddr + (i-1) * VL);      // 依赖上轮结果
}
```

**位置 2：Pass 边界**（不同算法阶段之间）

```cpp
// Pass 1: 累加
for (...) { DataCopy(workAddr + i, sum, mask); }

LocalMemBar<VEC_STORE, VEC_LOAD>();  // pass 边界 barrier

// Pass 2: 归并
for (...) { DataCopy(reg, workAddr + i); ... }
```

**位置 3：循环开头**（保护跨迭代的调用之间）

```cpp
for (int nIdx = 0; nIdx < N; nIdx++) {
    LocalMemBar<VEC_STORE, VEC_LOAD>();  // 保护上一 nIdx 尾部 store
    LoadAlign(reg, colMaxAddr + nIdx);   // 本 nIdx 头部 load
    // ...
    DataCopy(colMaxAddr + nIdx, resReg); // 本 nIdx 尾部 store
}
```

**性能优化原则**：
- **不要"到处插一遍"**——每个 barrier 都会阻塞流水
- **合并**能合并的 barrier（两个连续 store 只用一个 barrier）
- **避免循环外无用 barrier**（编译器保序已经覆盖）

---

## 5. 场景化使用示例（基于 ops-nn 真实代码）

### 5.1 场景 A：RmsNorm 树形二分累加（RAW barrier）

**来源**：`norm/add_rms_norm/op_kernel/arch35/add_rms_norm_regbase_common.h:401-435`

```cpp
// Pass 1: 每行独立累加，把局部 ReduceSum 结果写入 workAddr[i]
for (uint16_t i = 0; i < remainRepeats; ++i) {
    pregMask = UpdateMask<float>(remainSreg);
    LoadForHandleRemainV2(...);
    Add(mainA, mainA, tailA, pregMask);
    Add(mainB, mainB, tailB, pregMask);
    Add(mainA, mainA, mainB, pregMask);
    ReduceSum(vMean, mainA, pregMask);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(
        workAddr + i, vMean, pregMerge);        // ← 写 workAddr[i]
}
for (uint16_t i = 0; i < masterRepeats; ++i) {
    // ... 类似逻辑 ...
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(
        workAddr + remainRepeats + i, vMean, pregMerge);  // ← 写 workAddr[remainRepeats+i]
}

// ★ Pass 1 → Pass 2 barrier
LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();

// Pass 2: 二分合并 —— 读 workAddr[2i]/workAddr[2i+1]，Add，写回 workAddr[i]
for (uint16_t i = 0; i < mergeRepeats; ++i) {
    pregMask = UpdateMask<float>(mergeSreg);
    DataCopy(mainA, workAddr + (i*2+0) * V_LENGTH);        // ← 读之前写的
    DataCopy(mainB, workAddr + (i*2+1) * V_LENGTH);
    Add(mainA, mainA, mainB, pregMask);
    ReduceSum(vMean, mainA, pregMask);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(
        workAddr + i, vMean, pregMerge);        // ← 又写回 workAddr
}

// ★ Pass 2 → Pass 3 barrier
LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();

// Pass 3: 最终合并到 vMean 一个寄存器
DataCopy(mainA, workAddr + 0);
ReduceSum(vMean, mainA, pregMask);
DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(
    dstAddr + offset, vMean, pregMerge);
```

**要点分析**：
- **依赖关系**：Pass1 中 `DataCopy(workAddr+i, ...)` 写入 workAddr，Pass2 立刻用 `DataCopy(mainA, workAddr+2i)` 读同一段 UB。经典的 **多阶段 RAW 依赖**
- **不插的后果**：VF store 进队列后异步执行，Pass2 的 load 可能被硬件提前发射到 store 完成之前，读到旧值 → rstd 计算全错
- **MemType 选择**：Pass1 最后一条是 store → src = `VEC_STORE`；Pass2 第一条是 load → dst = `VEC_LOAD`

### 5.2 场景 B：动态量化外层循环（跨迭代 RAW）

**来源**：`quant/dynamic_quant/op_kernel/arch35/dynamic_quant_regbase_perchannel_recompute.h:485-513`

```cpp
for (uint16_t nIdx = 0; nIdx < nLoopNum; nIdx++) {
    mask = Reg::UpdateMask<float>(currColNum);

    // ★ barrier：保护上一 nIdx 尾部写入的 colMax
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();

    // 头部：读入上一分块 nIdx 位置的历史 colMax
    Reg::DataCopy<float>(vregColMax,
        (__ubuf__ float*)(colMaxLocalAddr + nIdx * elementNumPerLoop));

    // 中间：遍历 M 行，Abs + Max 累积
    for (uint16_t mIdx = 0; mIdx < mLoopNum; mIdx++) {
        Reg::DataCopy<xDtype, Reg::LoadDist::DIST_UNPACK_B16>(vregIn, ...);
        Reg::Cast<float, xDtype, castTraitB16ToB32>(vregInFp32, vregIn, mask);
        // ... smooth scale + abs + max
        Reg::Abs<float>(vregAbs, vregInFp32, mask);
        Reg::Max<float>(vregColMax, vregAbs, vregColMax, mask);
    }

    // 尾部：写回累积后的 colMax，供下一 M 块继续累积
    Reg::DataCopy<float>(
        (__ubuf__ float*)colMaxLocalAddr + nIdx * elementNumPerLoop,
        vregColMax, mask);
}
```

**要点分析**：
- **依赖关系**：外层 nIdx 每轮开始读入 colMax[nIdx]，而**上一轮** nIdx 迭代末尾写过它（虽然是不同 offset，但硬件不保证跨迭代的顺序）
- **不插的后果**：多次外层调用累积同一 colMaxLocalAddr 时，本轮读到未更新的历史值 → per-channel scale 偏小 → 反量化溢出
- **barrier 位置**：**循环内的最前面**——同时覆盖首轮进入 + 每轮跨迭代
- **常见变体**：也可以放在循环末尾，效果等价

### 5.3 场景 C：Softmax 补零 + 二分树 reduce

**来源**：`activation/softmax_v2/op_kernel/arch35/softmax_v2_ara_full_load.h:263-273`

```cpp
__VEC_SCOPE__ {
    RegTensor<float> x1, nextRow, rem, remNextRow;
    MaskReg pregMain = CreateMask<float, MaskPattern::ALL>();
    RegTensor<float> zero;
    Duplicate(zero, 0.0, pregMain);
    MaskReg pregLoop;
    uint32_t sreg0 = curTileA0Len;

    for (uint16_t k = 0; k < aLoopCount; k++) {
        pregLoop = UpdateMask<float>(sreg0);
        uint32_t aLoopOffset = k * VL_FP32;

        // Step A：把 xTmpLocal 尾部"虚拟行" 位置写 0（补齐 2 的幂）
        DataCopy(
            ((__local_mem__ float*)xTmpLocal + validNumInXUb + aLoopOffset),
            zero, pregLoop);

        // ★ 关键 barrier
        LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();

        // Step B：TwoRowAddWithTail 内部读同 offset 的"零行"
        TwoRowAddWithTail(x1, xTmpLocal, pregLoop, aLoopOffset,
                          remainderTailOffset0 + aLoopOffset,
                          aLength + aLoopOffset,
                          remainderTailOffset1 + aLoopOffset,
                          rem, nextRow, remNextRow);

        DataCopy(
            ((__local_mem__ float*)xReduceLocal + aLoopOffset),
            x1, pregLoop);
    }
}
```

**要点分析**：
- **依赖关系**：`Duplicate + DataCopy` 把 xTmpLocal 某段写 0（用零行补齐 2 的幂），下一句 TwoRowAddWithTail 内部就会读回来
- **不插的后果**：Add 先执行读到脏数据（可能是上一 tile 的 exp 值）→ 补零失败 → sum 里叠加错误行 → softmax 分母错
- **场景特殊性**：这不是"完整 3-pass 之间"，而是"pass 内的 mini-pass"——展示了 barrier 也用于 pass 内部的短距离依赖保护

### 5.4 场景 D：MX quant in-place 二分归约

**来源**：`quant/dynamic_mx_quant/op_kernel/arch35/dynamic_mx_quant_not_tail_axis_optimize.h:263-285`

```cpp
// 二分法：初始 expOffset = dataLenSingleLoop/2, 每轮 expOffset /= 2
// 每轮：把 maxExpAddr[0..offset) 和 maxExpAddr[offset..2offset) 求 Max 后写回 [0..offset)

Reg::DataCopy(maxExpAddr, xMaxReg, pnumMask);              // 写 maxExpAddr
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();

uint32_t maskNum = dataLenSingleLoop - expOffset;
Reg::MaskReg mask = Reg::UpdateMask<calcTypeInt>(maskNum);
Reg::DataCopyUnAlignPre(u0, maxExpAddr);
Reg::DataCopyUnAlign(xMaxReg, u0, maxExpAddr);              // 读 [0..)
Reg::DataCopyUnAlignPre(u0, maxExpAddr + expOffset);
Reg::DataCopyUnAlign(absReg, u0, maxExpAddr + expOffset);   // 读 [expOffset..)
Reg::Max(absReg, xMaxReg, absReg, mask);
Reg::Copy<calcTypeInt, Reg::MaskMergeMode::MERGING>(xMaxReg, absReg, mask);

for (uint16_t i = 0; i < loopSize; i++) {                  // 循环内 store+load 交替
    Reg::DataCopy(maxExpAddr, xMaxReg, pnumMask);           // 写 maxExpAddr[0..pnum)

    // ★ 每轮必须的 barrier
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();

    expOffset /= DIGIT_TWO;
    maskNum = expOffset;
    mask = Reg::UpdateMask<calcTypeInt>(maskNum);
    Reg::DataCopyUnAlignPre(u0, maxExpAddr);
    Reg::DataCopyUnAlign(xMaxReg, u0, maxExpAddr);          // 读 [0..)
    Reg::DataCopyUnAlignPre(u0, maxExpAddr + expOffset);
    Reg::DataCopyUnAlign(absReg, u0, maxExpAddr + expOffset); // 读 [expOffset..)
    Reg::Max(xMaxReg, xMaxReg, absReg, mask);
}
```

**要点分析**：
- **依赖关系**：**极其典型的 in-place 二分归约**。`maxExpAddr[0..pnum)` 每一轮既是写目标，又是**下一轮**的读源。写-读物理地址完全重叠，间隔只有一条指令
- **不插的后果**：VF store 尚未 commit，DataCopyUnAlign(load) 读到旧值 → 二分归约失效 → MX scale 全错 → 4bit 量化输出爆炸性偏差
- **教科书意义**：这是**编译器自动同步无法覆盖的场景**——同一段代码内的 store/load 编译器能保序，但**跨迭代**的依赖必须手动 barrier

### 5.5 场景 E：VEC_LOAD → VEC_STORE 反向保护

**来源**：`pooling/adaptive_pool2d/op_kernel/arch35/adaptive_avg_pool2d_big_kernel.h:91-103`

```cpp
template <typename U>
__aicore__ inline void UpdateSum(
    Reg::RegTensor<U>& res,
    const __local_mem__ U* storeLocalAddr,
    int32_t offset)
{
    Reg::MaskReg pregOne = Reg::CreateMask<U, Reg::MaskPattern::VL1>();
    Reg::RegTensor<U> lastRes;

    // ① 读旧累加值（这段 UB 之前被别的路径写过）
    LoadOneValue<U>(storeLocalAddr, lastRes, pregOne, offset);   // VEC_LOAD

    // ② 累加到 res 寄存器
    Reg::Add(res, res, lastRes, pregOne);

    // ★ WAR barrier：保证 ① 的 load 已完成，
    //   调用方接下来的 StoreOneValue 才允许写回同一地址
    Reg::LocalMemBar<Reg::MemType::VEC_LOAD, Reg::MemType::VEC_STORE>();
}

// 调用方（同文件 232-235 行）：
if constexpr (SPLIT_MODE != NO_SPLIT) {
    UpdateSum<U>(res, storeLocalAddr, 0);            // 内部读 storeLocalAddr
}
StoreOneValue<U, U>(storeLocalAddr, res, sumMask, 0); // 立刻写 storeLocalAddr
```

**要点分析**：
- **依赖关系**：`storeLocalAddr[0]` 先被 LoadOneValue 读到 lastRes，返回后调用者立刻 StoreOneValue 写回同一地址。这不是"写后读"，而是**"读后写"**——barrier 保护 load 一定要读到旧值，不能被后续 store 覆盖
- **不插的后果**：VF 硬件允许后续 store 提前发射到前面 load 之前（store buffer forwarding），lastRes 会拿到本次 res 的值而不是历史累加值 → split pool 累积错误
- **教科书意义**：**方向和场景 A 完全相反**。这类 barrier 在全库出现 28 次，主要在 layer_norm_v3、adaptive_pool、pooling 中——都是"用完某段 UB 数据后紧接着要重新写覆盖"的场景

### 5.6 场景 F：VEC_STORE → VEC_STORE Pad+Data 双写

**来源**：`pooling/max_pool_v3/op_kernel/arch35/max_pool_v3_small_kernel_pad.h:329-336`

```cpp
__VEC_SCOPE__ {
    // ① 先把整块 xLocalAddr 用 -inf / 特殊值填满（padding value）
    CustomDuplicate<M>(xLocalAddr, totalDupNum, dupLoop);            // VEC_STORE 全区

    // ★ WAW barrier：保证 pad 已经先写下去，
    //   随后的有效数据 copy 才能覆盖指定 offset
    Reg::LocalMemBar<Reg::MemType::VEC_STORE,
                          Reg::MemType::VEC_STORE>();

    // ② 用有效数据覆盖 xLocalAddr 中间的合法区域，其余保留 pad 值
    CustomCopy(xLocalAddr, inLocalAddr,
               srcBatchStride, srcColStride, oneChannelElements, dstColStride,
               rowOffsetInUb, colOffsetInUb, ubFactorN, hInUb,
               preColsLoop, tailPreCols, repeatElm);                 // VEC_STORE 部分区
}
```

**要点分析**：
- **依赖关系**：两次 store 目标是**同一段 UB**（xLocalAddr），只是 offset 范围不同——第一次覆盖整块，第二次只写"图像有效区域"。VF store 无序则第二次的有效数据可能被后到达的 duplicate 覆盖成 pad 值
- **不插的后果**：max pool 的窗口边界像素被误写为 -inf → max 结果不受"边界外无效"约束的算法失效
- **场景特殊性**：这是全库使用第 3 多的组合（16 次），**几乎都在 pooling 的 pad+data 双写场景**。它是 Pool 边界处理的标志性结构

### 5.7 场景 G：VEC_STORE → SCALAR_LOAD 跨流水（全库唯一实例）

**来源**：`ops-math/random/stateless_random_choice_with_mask/op_kernel/arch35/stateless_random_choice_with_mask.h:424-438`

```cpp
// 前置：用 DataCopyScatter 把每行前缀和写入 countLocalAddr（向量 store）
for (uint16_t j = 0; j < static_cast<uint16_t>(cols); j++) {
    AscendC::Reg::Adds(index, sequence, (uint64_t)j, pregFull);
    AscendC::Reg::DataCopyGather(reg0, countLocalAddr, index, pregFull);
    AscendC::Reg::Add(reg1, reg0, tmpReg, pregFull);
    AscendC::Reg::Copy(tmpReg, reg1, pregFull);
    AscendC::Reg::DataCopyScatter(countLocalAddr, reg1, index, pregFull);  // 向量 store
}

// 第一处 barrier：VEC_STORE → VEC_LOAD（后续 reg1 是向量 load）
AscendC::Reg::LocalMemBar<AscendC::Reg::MemType::VEC_STORE,
                                AscendC::Reg::MemType::VEC_LOAD>();
AscendC::Reg::DataCopy(reg1, countLocalAddr);                     // 向量 load

AscendC::Reg::Adds(reg1, reg1, maxValue, pregFull);
AscendC::Reg::DataCopy(countLocalAddr, reg1, pregFull);           // 向量 store

__local_mem__ int64_t* countAddr = countLocalAddr;
for (uint16_t i = 1; i < rows; i++) {
    // ★★★ 关键 barrier：VEC_STORE → SCALAR_LOAD（下一条是标量下标读！）
    AscendC::Reg::LocalMemBar<AscendC::Reg::MemType::VEC_STORE,
                                    AscendC::Reg::MemType::SCALAR_LOAD>();

    int64_t max = countLocalAddr[i * cols - 1];   // ← 标量下标访问 UB，走 SCALAR 流水
    int64_t maxValue1 = max;
    countAddr += ALIGNMENT_32;
    AscendC::Reg::DataCopy(reg1, countAddr);
    AscendC::Reg::Adds(reg1, reg1, maxValue1, pregFull);
    AscendC::Reg::DataCopy(countAddr, reg1, pregFull);
}
```

**要点分析**：
- **依赖关系**：`countLocalAddr[i * cols - 1]` 是**普通 C 数组下标**，走标量 load / Scalar 流水；上一轮循环末尾的 DataCopy 是向量 store。这是**跨流水线的写-读依赖**（Vector 写 → Scalar 读同一段 UB）
- **不插的后果**：Vector 流水尚未把 reg1 落到 UB，Scalar 流水就去读 countLocalAddr[i*cols-1]，会拿到本地缓存 / 旧值。因为 Vector 和 Scalar 是**两条独立流水**，编译器**不知道**这个 C 表达式访问的地址与前一条 VF 指令写的地址重叠
- **MemType 必须**：用 `VEC_STORE → SCALAR_LOAD`。用 `VEC_STORE → VEC_LOAD` 只同步 Vector 流水，Scalar 流水的 load 仍可能提前
- **稀有性**：这是全 ops-nn/ops-math 唯一非 VEC_×→VEC_× 的实例，说明这种场景在实际工程里极稀有——**只有明确混用 vector store 与 C 下标标量 load 时才需要**

### 5.8 综合案例：add_layer_norm_quant 4-Pass 融合

**来源**：`norm/add_layer_norm_quant/op_kernel/arch35/add_layer_norm_quant_regbase_helper.h`

同一个函数内 **6 处 LocalMemBar**，展示了 mean-tree → mean-broadcast → var-tree → var-broadcast 的完整 4-pass 流：

| 行号 | MemType 组合 | 用途 |
|---|---|---|
| 430 | `VEC_STORE → VEC_LOAD` | Pass1 mean partial sum 写完 → Pass2 mean-tree 开始读 |
| 440 | `VEC_STORE → VEC_LOAD` | mean-tree 每一轮迭代之间 |
| **452** | **`VEC_LOAD → VEC_STORE`** | mean 计算读 x32Addr 完成 → 允许后续 var 计算把 (x-mean)² 写回 x32Addr（覆盖） |
| 504 | `VEC_STORE → VEC_LOAD` | Pass3 var partial sum 写完 → Pass4 var-tree 开始读 |
| 514 | `VEC_STORE → VEC_LOAD` | var-tree 每一轮迭代之间 |
| **523** | **`VEC_LOAD → VEC_STORE`** | var 计算读完 → 允许 normalize 阶段写回 |

**要点分析**：
- **单函数内同时展示 3 种方向组合**——完整 4-pass 融合的教科书级例子
- **RAW（VEC_STORE→VEC_LOAD）× 4**：多个 pass 之间的常规写-读
- **WAR（VEC_LOAD→VEC_STORE）× 2**：mean/var 读完后覆盖同一 UB 段
- **算法级理解**：barrier 位置直接反映算法的 pass 边界——研究一个 norm 类算子的 LocalMemBar 分布，就等于**画出了它的 pass 数据流图**

---

## 6. 常见陷阱（错误 vs 正确）

### 6.1 循环内 store→load 缺 barrier（RAW 数据竞争）

**症状**：Reduce 结果错乱、精度飘逸；测试时小 shape 可能"侥幸通过"、大 shape 或多核时暴露。

```cpp
// ❌ 错误：跨迭代 store→load 无 barrier
for (i = 0; i < N; i++) {
    DataCopy(workAddr + i * VL, resReg, mask);      // 上一轮 store
    DataCopy(nextReg, workAddr + (i-1) * VL);       // 本轮 load 前一位置 → 读到旧值
    Compute(...);
}

// ✅ 正确：循环内插 barrier
for (i = 0; i < N; i++) {
    DataCopy(workAddr + i * VL, resReg, mask);
    LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();  // ← RAW barrier
    DataCopy(nextReg, workAddr + (i-1) * VL);
    Compute(...);
}
```

### 6.2 In-place 覆盖前忘 barrier（WAR 违反）

**症状**：Split 累积错误、多轮更新的初值被清空。

```cpp
// ❌ 错误：读完 res 后立刻覆盖 res 同地址，无 barrier
LoadOneValue<T>(storeAddr, lastRes, pregOne, 0);
Add(res, res, lastRes, pregOne);
StoreOneValue<T>(storeAddr, res, mask, 0);   // ← store buffer forwarding 可能污染前面 load

// ✅ 正确：在 load 后 store 前插 WAR barrier
LoadOneValue<T>(storeAddr, lastRes, pregOne, 0);
Add(res, res, lastRes, pregOne);
LocalMemBar<MemType::VEC_LOAD, MemType::VEC_STORE>();  // ← WAR barrier
StoreOneValue<T>(storeAddr, res, mask, 0);
```

### 6.3 barrier 方向用反

**症状**：barrier 存在但不起作用，测试结果与"缺 barrier"完全一样。

```cpp
// ❌ 错误：写后读依赖，但方向填反
DataCopy(workAddr, resReg, mask);              // store
LocalMemBar<MemType::VEC_LOAD,  MemType::VEC_STORE>();  // ← 方向反了！
DataCopy(nextReg, workAddr);                   // load

// ✅ 正确：src=STORE, dst=LOAD
DataCopy(workAddr, resReg, mask);
LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();
DataCopy(nextReg, workAddr);
```

**判定口诀**：**src = "屏障之前"最后一条 VF 指令的流水线；dst = "屏障之后"第一条 VF 指令的流水线**。

### 6.4 混淆"寄存器保序"与"UB 地址保序"

**症状**：以为编译器会自动同步，实际上编译器只对寄存器保序。

```cpp
// ❌ 认为不需要 barrier（错误理解）
DataCopy(workAddr, srcReg, mask);           // 通过 UB 地址传递数据
DataCopy(dstReg, workAddr);                 // 期望读到 srcReg 的值
// 编译器：只看到 workAddr 是运行时值，不知道两条指令访问同一地址！

// ✅ 正确：显式 barrier
DataCopy(workAddr, srcReg, mask);
LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();
DataCopy(dstReg, workAddr);

// 对比：只有寄存器依赖时不需要 barrier
Add(dstReg, srcReg0, srcReg1, mask);        // 编译器知道 dstReg 由 srcReg0/1 生成
StoreAlign(dstAddr, dstReg, mask);           // 编译器保序：等 Add 完成才 store
```

### 6.5 循环外 barrier 无效

**症状**：barrier 放错位置，起不到保护作用。

```cpp
// ❌ 错误：barrier 在循环外，只对最后一轮生效
for (i = 0; i < N; i++) {
    DataCopy(workAddr + i, resReg, mask);
    DataCopy(nextReg, workAddr + (i-1));    // 每轮都有跨迭代依赖！
}
LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();  // ← 只保护"循环之后"

// ✅ 正确：barrier 在循环内
for (i = 0; i < N; i++) {
    DataCopy(workAddr + i, resReg, mask);
    LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();
    DataCopy(nextReg, workAddr + (i-1));
}
```

### 6.6 barrier 过度使用（性能损失）

**症状**：功能正确但性能远低于预期。norm 类算子吞吐下降 20~30%。

```cpp
// ❌ 错误：到处插 barrier"以防万一"
for (i = 0; i < N; i++) {
    LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();  // ← 无必要
    LoadAlign(reg0, addr0 + i);
    LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();  // ← 无必要
    LoadAlign(reg1, addr1 + i);
    Add(res, reg0, reg1, mask);
    LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();  // ← 无必要（addr2 不同段 UB）
    StoreAlign(addr2 + i, res, mask);
}

// ✅ 正确：只在有跨迭代依赖时插
for (i = 0; i < N; i++) {
    LoadAlign(reg0, addr0 + i);            // 编译器管保序
    LoadAlign(reg1, addr1 + i);
    Add(res, reg0, reg1, mask);
    StoreAlign(addr2 + i, res, mask);      // 无跨迭代依赖到 addr0/addr1
}
```

**判定原则**：
- 只有**同一 UB 段**在被写入后**又被立即读取**时才需要 barrier
- 只有 **UB 段被读完后立即被覆盖**时才需要 WAR barrier
- **不同 UB 段的读写**（addr0/addr1/addr2 互相独立）→ **不需要 barrier**

---

## 7. 相关模式

LocalMemBar 是几个未来 Pattern 的**核心构件**：

| Pattern | 用到的 barrier 特性 | 说明 |
|---|---|---|
| Pattern 3.x（RmsNorm / LayerNorm） | RAW × 多次 + WAR | 树形 reduce + in-place 累加 |
| Pattern 4.x（Softmax 3-pass） | RAW × 3 | max / sub-exp-sum / div 三段之间 |
| Pattern 6.x（Dynamic quant） | RAW × 3 | max 求 scale / cast quantize |
| Pattern 7.x（MX quant） | RAW × N | 二分归约每轮之间 |
| Pattern 11.x（Bitmask 累积 Pooling） | WAR + WAW | 状态累积 + pad/data 双写 |
| Pattern 12.x（Multi-pass LocalMemBar） | 综合 | norm 融合类算子完整流水 |

**结论**：**LocalMemBar 分布图 ≈ 算法 pass 分布图**。研究一个 norm 类算子里 LocalMemBar 的位置和方向，就能反推出它的完整 pass 数据流。

---

## 8. 相关知识源

- 官方 API：[LocalMemBar](../../../ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/同步控制/LocalMemBar.md)
- 硬件流水线：[ascend950_hardware_and_pipeline_control.md](../ascend950_hardware_and_pipeline_control.md) 四、流水控制与同步机制
- 编程指南：[ascend_regbase_programing_guide.md](../ascend_regbase_programing_guide.md) § 10 同步机制
- Kernel 编程入口：[asc_vf_call.md](../../../ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/asc_vf_call.md) —— `__simd_vf__` / `__simd_callee__` 内才允许使用 LocalMemBar

**与其他同步机制的边界**：
- **LocalMemBar**（本文档）：VF 内 Vector/Scalar 流水线之间的同步屏障
- **PipeBarrier**（在 `__aicore__` 层）：跨 pipeline（V/MTE2/MTE3/S 等）的同步——参考 `ascendc-sync` skill
- **SyncAll / IBSet**（多核）：跨核同步——参考 `ascendc-sync` skill

**判定规则**：
- `__simd_vf__` / `__simd_callee__` 函数内 → 用 `LocalMemBar`
- `__aicore__` 函数内（VF 外部） → 用 `PipeBarrier` / `SetFlag` / `WaitFlag`
- 多核之间 → 用 `SyncAll` / `IBSet` / `IBWait`

---

## 9. 引用协议（S2 使用）

| 引用前缀 | 定位章节 | 使用时机 |
|---|---|---|
| `vf-instructions:localmembar` | 本文档整体 | Compute 涉及 UB 内 pass 依赖的场景 |
| `vf-instructions:localmembar#raw` | § 3.2 + § 5.1 + § 6.1 | 树形 reduce / 多 pass 写-读依赖（VEC_STORE→VEC_LOAD） |
| `vf-instructions:localmembar#war` | § 3.2 + § 5.5 + § 6.2 | in-place 累加 / split 累积（VEC_LOAD→VEC_STORE） |
| `vf-instructions:localmembar#waw` | § 5.6 + § 3.2 | Pool pad+data 双写（VEC_STORE→VEC_STORE） |
| `vf-instructions:localmembar#cross-pipe` | § 5.7 | 跨 Vector/Scalar 流水混合场景（VEC_STORE→SCALAR_LOAD） |
| `vf-instructions:localmembar#in-place-reduce` | § 5.4 | in-place 二分归约每轮之间 |
| `vf-instructions:localmembar#multi-pass` | § 5.8 | 完整多 pass 融合算子 |

**触发规则**（供 s2-analysis 判断）：

| 算子设计特征 | 应追加 | 追加到哪一行 |
|---|---|---|
| Compute 涉及树形 reduce（RmsNorm/LayerNorm 系）| `vf-instructions:localmembar#raw` | C.3 Compute |
| Compute 涉及多 pass（Softmax、动态量化）| `vf-instructions:localmembar#raw` | C.3 Compute |
| Compute 涉及 in-place 累加（Split pool、adaptive pool）| `vf-instructions:localmembar#war` | C.3 Compute |
| Compute 涉及 pad + data 双写（Pool with padding）| `vf-instructions:localmembar#waw` | C.3 Compute |
| Compute 涉及 in-place 二分归约（MX quant）| `vf-instructions:localmembar#in-place-reduce` | C.3 Compute |
| Compute 混用 vector store + C 下标标量读 | `vf-instructions:localmembar#cross-pipe` | C.3 Compute |
| 复杂 norm 融合算子（多 pass 组合）| `vf-instructions:localmembar#multi-pass` | C.3 Compute |

**不触发场景**：
- 纯 element-wise 算子（无跨 pass 依赖，无跨迭代 UB 依赖）→ 无需引用
- 归约结果只落一次 GM 不再回读 UB → 无需引用
