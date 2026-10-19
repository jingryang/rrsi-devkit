# 模式 G01：索引间接搬运（Gather/Scatter）

> ⚠️ **范围红线**：本文件严格限定在"概要设计"职责范围内。不包含 TilingData 字段结构、Buffer 大小数值、Kernel 循环代码、API 调用细节。平台硬件参数见 `general_design_common_knowledge.md`。
>
> **语料来源**：`ops-nn/index`（gather_v2、scatter、gather_nd、scatter_nd、gather_elements、scatter_elements、index_put_v2、inplace_scatter_add、masked_scatter，均已实地核实）。

---

## 一、三维分类标识（LP/CP/ES + L1/L4 属性描述）

### LP 循环结构模式

```
类型: LP2(索引间接)
描述: 输出（或输入）的访存地址由 index 张量动态决定，而非循环变量直接映射；
      读/写位置依赖运行期 index 值，呈非连续/散射访问
```

### CP 计算通路

```
硬件单元: Vector（搬运为主，部分含轻量规约）
瓶颈画像: memory-bound（非连续访存，带宽 + 地址计算受限）
核心操作: 按 index 做 gather（间接读）/ scatter（间接写），多数无算术计算
```

### ES 执行结构

```
类型: ES1(单次通过, 纯 gather/scatter) / ES2(遍历累加, scatter-add 类含规约)
数据流特征: gather = 按 index 间接 load → 直接 write（ES1）；
            scatter-add = 多个 update 按 index 累加到同一位置（ES2，AtomicAdd 或 UB 累加）
```

### L1 张量签名（属性参数）

```
输入: 2~3 个, 角色: [data, index] 或 [data, index, updates]
输出: 1 个, 角色: [data]（gather 输出新张量；scatter 多为 inout 原地写）
维度语义: data[..., axis, ...]; index 沿 axis 指定取/放位置；gather_nd/scatter_nd 的 index 末维=坐标维数
```

### L2 依赖图拓扑

```
类型: Indexed-access（索引间接）
输出依赖: 每个输出位置依赖 index[i] 指向的输入位置；scatter-add 时多个源累加到同一目标（多对一）
```

### L3 计算范式

```
硬件单元: Vector（含 DataCopy 间接寻址 / AtomicAdd）
核心操作: 间接搬运；scatter-reduce 含累加
```

### L4 关键工程约束

```
是否变长: 多数否（index 长度静态）；embedding 类可变长
是否含 Mask: 多数无；masked_scatter 有
是否需要 Index Cache: 是（index 张量驱动寻址，是本模式核心特征）
性能画像: memory-bound（非连续访存是主瓶颈）
```

---

## 二、模式总览

| 字段 | 内容 |
|------|------|
| **模式名称** | 索引间接搬运（Gather/Scatter） |
| **一句话描述** | 访存地址由 index 张量在运行期决定的间接搬运；gather 间接读、scatter 间接写，scatter-add 含多对一规约 |
| **适用条件** | 读或写的位置依赖 index 张量值，而非循环变量直接映射；核心是非连续/散射访存 |
| **典型算子** | Gather / GatherV2 / GatherNd / GatherElements / Scatter / ScatterNd / ScatterElements / IndexPut / InplaceScatterAdd / Embedding |

---

## 三、核心设计特征（概要设计层面）

### 3.1 轴行为分析

- **index 轴**：驱动间接寻址的维度，其长度决定输出（gather）或写入次数（scatter）；不可与 data 轴直接对齐。
- **gather/scatter 轴（axis）**：被索引的维度。axis 之外的维度（batch 维、内层 slice 维）为独立轴，可连续搬运。
- **内层连续块（slice）**：被索引单元内的连续数据（如 gather 一行/一个 slice）——是搬运的最小连续粒度，块越大越接近连续访存、带宽利用越高。

### 3.2 数据流拓扑概要

- **gather**：index → 计算源地址 → 间接 GM load → UB → 直接 GM write（ES1）。
- **scatter**：updates → UB → 按 index 计算目标地址 → 间接 GM write；scatter-add 用 AtomicAdd 或同地址累加（ES2）。
- 无 L0A/L0B/L0C，纯 Vector + 访存单元；地址计算（index×stride）是额外开销。
- **核间通信**：多数无；scatter-add 多核写同一地址时依赖 AtomicAdd 保证原子性（非显式核间同步）。

### 3.3 切分策略（概要级）

- **核间切分**：优先沿 index 轴（gather 输出行 / scatter 写入次数）做核间均衡分配；index 各元素独立，切分简单。
- **核内循环**：每次处理一个或一批 index 项，搬运其对应的连续 slice。
- **slice 全量 vs 分块**：单个 slice 较大时核内再沿 slice 内连续维分块；slice 小时一次搬完。
- **scatter-add 冲突**：多个 index 指向同一目标时，写入需累加——核间靠 AtomicAdd，核内靠 UB 累加缓冲。
- **采样/插值变体**（index 由坐标变换隐式生成，非显式 index 张量）：沿「坐标连续变化的维」切块（相邻输出对应相邻输入，通常是最内维），其余维的 floor/ceil 在块内**近似常数**——采样窗口从「散布全平面的 2^d 角点」退化为「沿连续维展开的局部条带」（常数维各 2 个 × 连续维一段），条带可进 UB。**切分轴从主模式的「index 轴」变为「连续维」**，是这类变体的核心差异。

### 3.4 模板数量与路由原则

- 模板数量：通常 2~4 个，主要按以下条件路由：
  - **对齐 vs 非对齐**：slice 起止是否 32B 对齐（index 寻址极易产生非对齐，常需独立非对齐模板或 DataCopyPad）。
  - **slice 大小档位**：大 slice（连续搬运为主）vs 小 slice（地址计算占比高、可能 SIMT 逐元素 gather）分别优化。
  - **gather vs scatter vs scatter-reduce**：纯搬运 vs 含累加分支。
  - **index 维数**：单维 index（gather_v2/scatter）vs 多维坐标 index（gather_nd/scatter_nd，末维=坐标维数）。

---

## 四、平台相关设计考量

### 以 A3 为基准的设计要点

| 维度 | 如何影响本模式的概要设计 |
|------|------------------------|
| UB 容量（见 hw_params.json） | 决定单次缓存的 index 数量与 slice 大小；index 与 data slice 需共存 |
| 非连续访存 | 间接寻址打断连续性，DataCopy 效率低于逐元素模式；slice 越大越能摊薄地址计算开销 |
| AtomicAdd 支持 | scatter-add 多核写同址依赖硬件 AtomicAdd；需确认 dtype 是否支持 |

### 其他平台的概设差异

- **A5**：SIMT 模型使逐元素 gather（小 slice）可直接用线程映射，每 thread 处理一个 index 项，省去显式循环；Regbase 使 index 值与地址计算留寄存器。但**非连续访存仍是带宽瓶颈**，slice 过小时地址计算占比高。寄存器预算（每 VF 最多 32 RegTensor）约束单次并行处理的 index 批量。
- **A6（预留）**：待补充。

---

## 五、已知变体

| 变体 | 触发条件 | 与主模式的差异 |
|------|---------|--------------|
| 多维坐标 index（gather_nd/scatter_nd） | index 末维为坐标维数 | 地址计算为多维 stride 内积，slice 粒度变小 |
| scatter-reduce（scatter_nd/scatter_elements/inplace_scatter_add） | reduce 模式（add/max 等） | 多对一累加，ES1→ES2，多核写同址需 AtomicAdd |
| 含 mask（masked_scatter） | 传入 bool mask | mask 决定哪些位置写入，需前缀和算写出位置 |
| 变长 index（embedding_bag） | offsets 动态划分 | index 分段长度运行期决定，含分段规约（偏向融合） |
| 原地写（inplace_scatter_add/index_put） | 输入输出复用同地址 | 无独立输出 buffer，inout 语义 |
| 坐标采样/插值 | index 由坐标变换（floor/ceil）+ 相邻结构隐式生成，非显式 index 张量 | 角点有相邻结构（相邻维差 1 元素）→ 沿连续维分块 + 常数维退化，采样窗口退化为局部条带；非逐元素搬移（见 §3.3 采样/插值变体） |

---

## 六、关键决策记录

| 决策问题 | 选择 | 替代方案 | 理由 |
|---------|------|---------|------|
| 核间切分轴 | 沿 index 轴（输出行/写入次数） | 沿 data 轴 | index 各项独立，切分均衡且无依赖 |
| 小 slice 的处理 | SIMT 逐元素 gather（A5）或批量地址计算 | 强制连续 DataCopy | 小 slice 连续搬运收益低，逐元素更灵活 |
| scatter-add 多核冲突 | AtomicAdd（多核）+ UB 累加（核内） | 串行化写入 | 保证正确性同时保留并行度 |
| 非对齐 slice | 独立非对齐模板 / DataCopyPad | 强制对齐填充 | index 寻址天然非对齐，需专门处理避免越界 |
