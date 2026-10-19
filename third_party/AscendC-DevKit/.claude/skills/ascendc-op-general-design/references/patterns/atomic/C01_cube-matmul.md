# 模式 C01：Cube MatMul

> ⚠️ **范围红线**：本文件严格限定在"概要设计"职责范围内。不包含 TilingData 字段结构、Buffer 大小数值、Kernel 循环代码、API 调用细节。平台硬件参数见 `general_design_common_knowledge.md`。

---

## 一、三维分类标识（LP/CP/ES + L1/L4 属性描述）

### LP 循环结构模式

```
类型: LP6(矩阵乘积)
描述: 按[M,K,N]分形模式，内积轴积累，M/N 为独立循环轴
```

### CP 计算通路

```
硬件单元: Cube + Vector（后处理）
瓶颈画像: compute-bound（Cube 算力密集）
核心操作: 矩阵乘（Cube 单元） + 可选后处理（Vector 单元）
```

### ES 执行结构

```
类型: ES1(单次通过)
数据流特征: GM→L1→L0A/L0B→Cube(L0C)→UB(后处理)→GM，无跨迭代累加状态
```

### L1 张量签名（属性参数）

```
输入: 2 个, 角色: [data, weight]
输出: 1 个, 角色: [data]
维度语义: [M, K, N]（M=输出行，K=内积轴，N=输出列）
```

### L2 依赖图拓扑

```
类型: MatMul
输出依赖: 每个输出元素依赖两个输入的 K 维内积结果，M/N 为独立循环轴
```

### L3 计算范式

```
硬件单元: Cube + Vector（后处理）
核心操作: 矩阵乘（Cube 单元） + 可选后处理（Vector 单元）
```

### L4 关键工程约束

```
是否变长: 否
是否含 Mask: 否
是否需要 Index Cache: 否
是否需要核间通信: 可能（沿 M 切需 ReduceScatter，沿 N 切需 AllGather）
性能画像: compute-bound（Cube 算力密集）
关键约束: Cube 分形参数（BaseM/BaseN/Kunroll）约束 M/N/K 分块
```

---

## 二、模式总览

| 字段 | 内容 |
|------|------|
| **模式名称** | Cube MatMul |
| **一句话描述** | 使用 Cube 单元做矩阵乘，受 Cube 分形参数约束，M/N/K 三维分块 |
| **适用条件** | 算子核心计算是矩阵乘，M/N/K 维度满足 Cube 分形约束 |
| **典型算子** | MatMul / Linear / BatchMatMul |

---

## 三、核心设计特征（概要设计层面）

### 3.1 轴行为分析

- **M 轴**（输出行）：可做核间切分和核内循环，受 BaseM 分形约束
- **N 轴**（输出列）：可做核间切分和核内循环，受 BaseN 分形约束
- **K 轴**（内积轴）：在核内循环，受 Kunroll 分形约束，需做 Main/Tail 处理
- 各轴的分形粒度决定了最小切分单元

### 3.2 数据流拓扑概要

- GM → L1 → L0A/L0B → Cube（L0C）→ UB（后处理）→ GM
- 涉及完整的 Cube 存储层级：L0A（输入 A）、L0B（输入 B）、L0C（累加输出）
- 后处理（bias/activation/quant）在 UB 中用 Vector 单元完成
- L0C→UB（Fixpipe）或 L0C→GM（Fixpipe）的输出路径选择

### 3.3 切分策略（概要级）

- **核间切分**：沿 M 或 N 维度（优先沿输出轴中较大的那个）
  - 沿 M 切 → 各核输出 M 的一部分，可能需要 ReduceScatter
  - 沿 N 切 → 各核输出 N 的一部分，可能需要 AllGather
- **核内循环**：K 维作为最内层循环，每次加载一个 Kunroll 块
- **Main/Tail**：K 维的 Main 块对齐 Kunroll，Tail 处理剩余部分
- **Double Buffer**：通常需要乒乓操作掩盖数据加载延迟

### 3.4 模板数量与路由原则

- 模板数量：通常 1~2 个
  - 纯 MatMul 模板：无融合后处理
  - 融合后处理模板：含 bias/activation/quant 等
- 路由条件：是否含融合后处理、精度链要求、稀疏模式

---

## 四、平台相关设计考量

### 以 A3 为基准的设计要点

| 维度 | 如何影响本模式的概要设计 |
|------|------------------------|
| Cube 分形参数（BaseM/BaseN/Kunroll 固定值） | 决定 M/N/K 的最小分块和尾块处理策略 |
| L0A 分形格式（ZZ 分形） | 影响 DataCopy 到 L0A 的数据排布 |
| 同步机制（SetFlag/WaitFlag） | Cube 和 Vector 的流水线同步方案 |

### 其他平台的概设差异

- **A5**：L0A 分形从 ZZ→NZ，影响输入数据排布策略。L0C 新增 Fixpipe 通路（L0C→UB 和 L0C→GM），提供新的输出路径选择。同步机制改为 Mutex + LocalMemBar。核数范围宽需动态适配。不支持结构化稀疏。int4b_t 需先 Cast 为 int8_t。分形参数需通过 `ascend-hardware` 查询。**SIMT 影响**：后处理的 Vector 部分从显式循环变为 SIMT 线程映射，但 Cube 计算部分不受 SIMT 影响（Cube 单元本身仍然是固定的硬件数据流）。
- **A6（预留）**：待补充。

---

## 五、已知变体

| 变体 | 触发条件 | 与主模式的差异 |
|------|---------|--------------|
| 含融合后处理 | 需要 bias/activation/quant | 增加 Vector 后处理阶段，UB 需额外分配后处理 Buffer |
| Batch MatMul | 多 batch 的 MatMul | M 维度可能包含 batch 维度，切分策略需考虑 batch 间独立性 |
| 稀疏 MatMul | 结构化稀疏输入 | 仅 A3 支持，利用结构化稀疏加速 |
| 量化 GMM（CP4 CV 混合，LP6×CP4） | 分组矩阵乘 + 输入/输出量化反量化（quant_grouped_matmul_inplace_add 等，已实地核实用 Matmul+Mmad Cube + Vector 量化） | Cube 矩阵乘与 Vector 量化/反量化深度交织成 CV 混合（CP4）；分组（grouped）按 group 切 M 维，各 group 独立内积；inplace_add 时输出原地累加 |

---

## 六、关键决策记录

| 决策问题 | 选择 | 替代方案 | 理由 |
|---------|------|---------|------|
| 沿 M 切还是沿 N 切 | 取较大维度优先 | 固定切分策略 | 较大维度提供更多并行度，减少单核负载 |
| Double Buffer 同步方案 | SetFlag/WaitFlag（A3）/ Mutex+LocalMemBar（A5） | PipeBarrier | 取决于平台的同步机制 |
| 后处理融合 vs 分离 | 推荐融合 | 分离为独立 Kernel | 减少 GM 往返，但增加 UB 空间压力 |

