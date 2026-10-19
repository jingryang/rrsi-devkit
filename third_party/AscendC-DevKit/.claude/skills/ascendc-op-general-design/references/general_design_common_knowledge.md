# 概要设计共性知识参考

> 本文件存放所有算子概要设计共用的知识。各模式文件（`patterns/` 目录下）引用本文件
> 而非重复写入，避免平台参数变更时需要逐一修改每个模式文件。
>
> **使用方式**：概设 skill 在 **算子设计模式匹配** 步骤加载模式文件时，也应一并加载本文件。
> 模式文件中的"平台相关设计考量"章节引用的硬件参数均来源于此。
>
> **硬件数值唯一来源（P24）**：UB/L1/带宽/核数等**精确硬件数值以 `hw_params.json`（来自
> ascend-hardware chip spec）为唯一来源**，本文件只给定性描述与架构差异，不再硬编码具体数值——
> 否则多份副本必然漂移（曾出现 192/240/248/256KB 四值并存）。需要精确数值时读 `hw_params.json`。
>
> **代际命名（P29）**：本文件代际码与全仓 canonical 一致 —— **A2 = Ascend910B、A3 = Ascend910C、
> A5 = 950 / 910_95xx**。架构上 **A2 与 A3 同属 Membase/SIMD 代**（Vector 128B、SetFlag/WaitFlag、
> ZZ 分形；910C 是 910B 的同架构升级，编程模型一致），**A5 属 Regbase/SIMT 代**（VF/RegTensor/Mutex）。
> 下文「平台硬件参数速查」按架构代组织：Membase 代（A2/A3）一节、Regbase 代（A5）一节；
> 各模式文件中“A3 vs A5”的对比即“Membase/SIMD 代 vs Regbase/SIMT 代”，**A2 行为与 A3 一致**。

---

## 一、平台硬件参数速查

### A2 / A3 (910B / 910C — Membase/SIMD 架构代)

| 参数 | 取值 | 说明 |
|------|------|------|
| UB 总大小 | 见 `hw_params.json`（A2/A3 Membase 代物理总量；唯一来源 chip spec） | 可用 = 总量 − 同步头/TilingData 占用 |
| Vector 向量长度 | 128B（vec_calc_size） | 单指令可处理元素数 = 128B / sizeof(T) |
| 向量架构 | Membase | LocalTensor 操作，中间结果在 UB |
| 核间同步 | SetFlag / WaitFlag | PipeBarrier 等 |
| AI Core 数量 | 20 AIC + 40 AIV（固定） | 核间切分时按固定核数规划 |
| 对齐要求 | 32B | DataCopy 等操作强制 32B 对齐 |
| Cube 分形参数 | BaseM/BaseN/Kunroll（固定值） | 影响 Cube MatMul 类算子的分块策略 |
| Cube 输入排布 | ZZ 分形 | L0A/L0B 的格式 |
| 特殊 | Subnormal 硬件支持 | |

### A5 (950 / 910_95xx — Regbase/SIMT 架构代)

| 参数 | 取值 | 说明 |
|------|------|------|
| UB 总大小 | 见 `hw_params.json`（A5；唯一来源 chip spec） | 比 A3 可用空间大 |
| 编程模型 | **SIMT（Single Instruction, Multiple Threads）** | 与 A3 的 SIMD（向量化）模式完全不同。每个 thread 处理一个元素，不再以 Vector 长度为粒度编程 |
| VF 函数等价 | 每 VF 函数最多处理 256 个元素，对应 256 个 threads | Vector 长度 256B 在 SIMT 中转化为 256 个并行的 thread（每个处理 1B），而非 A3 的循环展开 |
| 向量架构 | **Regbase** | RegTensor，中间结果保留在寄存器。配合 SIMT 模型，每个 thread 的私有数据在寄存器中 |
| 寄存器约束 | 每 VF 函数最多 32 个 RegTensor | 在 SIMT 模型下，每个 thread 的私有变量都占用寄存器，寄存器压力取代 UB 容量成为首要约束 |
| 核间同步 | **Mutex + LocalMemBar** | 与 A3 的 SetFlag/WaitFlag 完全不同 |
| AI Core 数量 | 8~36 AIC（Tier 依赖） | 范围宽，核间切分粒度需动态适配 |
| 对齐要求 | 32B | 与 A3 一致 |
| Cube 分形参数 | 需通过 `ascend-hardware` 查询 | 不做预设 |
| Cube 输入排布 | **NZ 分形** | 与 A3 的 ZZ 分形不同，影响 DataCopy 到 L0A 的数据组织 |
| L0C 通路 | 新增 Fixpipe（L0C→UB 和 L0C→GM） | Cube 输出可直达 UB 或 GM |
| UB Bank 结构 | 8 groups × 2 banks × 16KB（2R+2W/group） | 比 A3 读写口翻倍 |
| 特殊 | Subnormal **软仿**，需 config 模板参数 `LnConfig` | RmsNorm 等规约算子需额外配置 |
| 特殊 | 稀疏支持不支持；int4b_t 不支持（需先 Cast 为 int8_t） | 影响 Cube MatMul 类算子 |
| 特殊 | A5 编程模型从 SIMD（单指令处理向量）转向 **SIMT（单指令处理多线程）**，本质差异见下方 2.6 节 | 所有模式文件的 A5 部分都应考虑此范式转变 |

### A6（预留）

> 待 A6 平台规格确定后补充。

---

## 二、通用概要设计原则

> 这些原则适用于所有算子的概要设计。各模式文件不重复写，概设 skill 自动引用。

### 2.1 D 轴（最后一维）全量处理原则

- D 维度（head_dim / hidden_size 的最后一轴）**通常**在核内全量单次处理，不跨核间切分
- 例外：当 D 维度超过 UB 容量时（如 D > UB_size / sizeof(T)），需要沿 D 轴切分，此时属于模式的特例，在各模式文件中记录
- D 轴全量处理的原因：减少核间通信、Vector 指令天然沿连续内存操作

### 2.2 32B 对齐要求

- DataCopy / DataCopyPad 等操作要求源地址和目标地址均为 32B 对齐
- 不对齐时：使用 DataCopyPad 填充对齐，或通过多次较小粒度的搬运组合
- 此约束影响模板路由（对齐 vs 非对齐分支）

### 2.3 多核切分的基本策略

- 优先沿非 D 轴的最外层轴做核间切分（以减少核间通信）
- 同一算子的不同模板可能需要不同的核间切分策略
- 核数固定（A3）或可变（A5 Tier 依赖）时，切分粒度的设计原则不同

## 三、三维分类参考表

> 本表供设计师在 **算子设计模式匹配** 步骤快速查阅 LP/CP/ES 三维分类的判定依据和设计影响。确保各维度的正交性（不重叠）和完备性（不遗漏）。

### LP：循环结构模式 — 快速判定指引

| 判定问题 | 对应 LP 编码 | 对 tiling 策略的影响 |
|---------|-----------|-------------------|
| 每个输出是否只依赖 ≤1 个对应输入？ | LP1(全轴独立) | 任意非 D 轴可切分，无跨元素依赖 |
| 是否有索引间接访存（Gather/Scatter）？ | LP2(索引间接) | index cache 优化，非连续访问处理 |
| 是否有沿非 D 轴的 N→1 规约？ | LP3(规约内嵌非D) | 规约轴可切分但需跨核通信 |
| 是否有沿 D 轴的 N→1 规约？ | LP4(D轴规约) | 规约轴 < UB，不可切分 |
| 输出是否依赖某轴的连续范围？ | LP5(范围迭代) | UB 内维护窗口/累加器 |
| 是否按 [M,K,N] 分形做内积积累？ | LP6(矩阵乘积) | Cube 分形参数约束 M/N/K 分块 |
| 是否按值排序后选前 K？ | LP7(选择排序) | 输出位置不固定，需排序网络 |
| 计算各阶段依赖拓扑是否变化？ | LP8(多阶段异构) | 分解为 SubOp，各独立匹配 |

### CP：计算通路 — 快速判定指引

| 判定问题 | 对应 CP 编码 | 瓶颈画像 |
|---------|-----------|---------|
| 核心计算是否在 Vector 单元完成？ | CP1(Vector运算) | 通常 memory-bound |
| 核心工作是否只是搬运/重排？ | CP2(Vector搬运) | 100% memory-bound |
| 核心计算是否在 Cube 单元完成？ | CP3(Cube纯算) | compute-bound |
| 是否同时使用 Cube + Vector？ | CP4(CV混合) | 取决于流水排布 |
| 是否多阶段均在 Vector 单元？ | CP5(Vector多阶段) | 按阶段分析 |

### ES：执行结构 — 快速判定指引

| 判定问题 | 对应 ES 编码 | 对模板结构的影响 |
|---------|-----------|----------------|
| 是否 load → compute → write 一次完成？ | ES1(单次通过) | 最简单的循环结构 |
| 是否需要分块加载+累加器多轮迭代？ | ES2(遍历累加) | 需维护累加器状态，影响 UB 分配 |
| 是否需要 GM workspace 中转中间结果？ | ES3(多阶段WS) | 需 workspace 分配，多阶段编排 |
| 是否在 UB 内连续完成多个计算步骤？ | ES4(多阶段UB内) | UB 多步操作，无 GM 中转 |

### 经典算子的 (LP, CP, ES) 映射参考

| 算子 | LP | CP | ES | 模式文件 |
|------|---|---|---|---------|
| Add/Silu/Gelu | LP1(全轴独立) | CP1(Vector运算) | ES1(单次通过) | A01 |
| RotaryPositionEmbedding | LP1(全轴独立) | CP1(Vector运算) | ES4(多阶段UB内) | A01 |
| Gather/Scatter | LP2(索引间接) | CP2(Vector搬运) | ES1(单次通过) | G01 |
| Transpose/Reshape/Cast | LP1(全轴独立) | CP2(Vector搬运) | ES1(单次通过) | D01 |
| LayerNorm/RmsNorm | LP4(D轴规约) | CP1(Vector运算) | ES2(遍历累加) | B01 |
| Softmax(沿D轴) | LP4(D轴规约) | CP1(Vector运算) | ES2(遍历累加) | B01 |
| SegmentSum/非末维Reduce | LP3(规约轴内嵌非D轴) | CP1(Vector运算) | ES2(遍历累加) | B02 |
| AvgPool/MaxPool（滑窗） | LP5(范围迭代) | CP1(Vector运算) | ES2(遍历累加) | P01 |
| Cumsum/Cumprod（前缀扫描） | LP5(范围迭代) | CP1(Vector运算) | ES2(遍历累加) | P01 |
| MatMul | LP6(矩阵乘积) | CP3(Cube纯算) | ES1(单次通过) | C01 |
| 量化 GroupedMatMul | LP6(矩阵乘积) | CP4(CV混合) | ES1(单次通过) | C01(量化变体) |
| FlashAttentionScore | LP5(范围迭代) | CP4(CV混合) | ES2(遍历累加) | E01(FA) |
| MoeGatingTopK(Softmax+TopK) | LP8(多阶段异构) | CP1(Vector,SubOp) | ES4/ES3 | F02 |
| TopK/ArgMax/Sort | LP7(选择排序) | CP1(Vector运算) | ES1(单次通过) | H01 |

### 2.4 模式匹配的局限

- 匹配到已知模式 ≠ 完全复用，仍需做差分分析
- 未匹配到模式 ≠ 框架失效，按从零构建流程逐层推导
- 未知算子的设计完成后，如果 (LP, CP) 组合在模式库中不存在，建议贡献为新模式
- **框架边界**：LP×CP×ES 是**单 AI Core 核内**坐标系，对跨卡集合通信（mc2 类）和时间步递推（rnn 类）存在**结构性盲区**，无法用现有维度描述。命中盲区时必须向用户声明限制、不得假装覆盖——详见 `design_patterns.md`「框架覆盖边界与已知盲区」节与 SKILL.md「盲区预判」段。

### 2.5 模板数量控制原则

- 模板数量的增加会带来验证和维护成本
- 应优先将相似分支合并到同一个模板内（通过 if/switch 分支），而非拆分为独立模板
- 模板拆分的决策依据：
  - 轴行为不同（如不同的 layout 组合）→ 拆
  - 仅参数不同（如不同的 mode 值）→ 合并在一个模板内
  - 计算通道不同（如对齐 vs 非对齐）→ 视情况，通常建议拆

### 2.6 A5 SIMT 编程模型范式转变

> A5 的编程模型从 A3 的 **SIMD（单指令处理向量）** 转向 **SIMT（单指令处理多线程）**。这是一个根本性的范式转变，影响所有算子的概要设计决策。

**核心差异：**

| 维度 | A3（Membase / SIMD） | A5（Regbase / SIMT） |
|------|---------------------|---------------------|
| 基本处理单元 | Vector（128B 向量） | Thread（单元素） |
| 并行模型 | 单指令处理一批连续元素 | 单指令同时执行多个线程，每个线程处理一个独立数据 |
| 循环结构 | `for` 循环遍历 tile 内元素 | 无显式循环，256 个线程并行执行 |
| 数据访问 | 按 Vector 长度对齐的连续访问 | 每个 thread 独立计算地址 |
| 临时变量 | LocalTensor 在 UB 中 | RegTensor 在寄存器中 |
| 寄存器压力 | 不存在该概念（UB 中转） | 每 VF 最多 32 RegTensor，是首要约束 |
| 代码形态 | Vector 计算 + Loop 嵌套 | VF 函数内 256 threads 并行 |
| 适用直觉 | "一次处理 128B 的数据" | "每个 thread 处理一个元素" |

**对概要设计的具体影响：**

1. **Tiling 策略差异**：A5 SIMT 下不再需要显式的 UB 级循环（`for (xIdx) { for (yIdx) { ... } }`），而是将每个 thread 映射到一个输出元素。"循环"变成了"线程分配"。

2. **切分粒度变化**：A3 中以 UB 容量为约束切分 tile；A5 中以寄存器预算为约束切分 thread block（每个 thread 的私有 RegTensor 数量决定单 VF 能容纳的数据量）。

3. **平台切换的概设影响**：同一算子的概设，切换到 A5 时：
   - 循环结构从嵌套 `for` 简化为线程映射
   - UB 空间分析不再是硬约束（寄存器替代）
   - 新增寄存器压力分析（32 RegTensor 上限）
   - DataCopy 模式不变（硬件搬运 API 同一套）

4. **概设文档中 A5 部分的写法**：当在模式文件的"平台相关设计考量"中写 A5 差异时，应说明：
   - SIMT 是否改变该模式的循环结构（通常简化为无显式循环）
   - 寄存器预算是否会影响该模式的模板数量或切分策略
   - 是否仍需要 Main/Tail 处理（SIMT 下仍需，但实现方式不同）

| 术语 | 含义 |
|------|------|
| UB (Unified Buffer) | AI Core 内部通用缓冲区，数据从 GM 加载到 UB 后进行计算 |
| GM (Global Memory) | 片外全局内存，容量大但访问延迟高 |
| L0A / L0B | Cube 单元的输入 Buffer |
| L0C | Cube 单元的累加 Buffer |
| AIV | AIC 内部的 Vector 计算单元（A3 上 1 AIC + 2 AIV） |
| Tiling | 将大数据切分为小分块，分块处理以适配 UB 容量 |
| TilingKey | 用于区分不同模板的枚举值 |
| Main / Tail | Main 处理对齐的全量数据，Tail 处理剩余的非对齐余量 |
| SetFlag / WaitFlag | A3 上用于核间/核内同步的机制 |
| Mutex / LocalMemBar | A5 上的同步机制 |
| Membase | A3 向量架构，LocalTensor 和中间结果位于 UB |
| Regbase | A5 向量架构，RegTensor 和中间结果位于寄存器 |
| SIMT | A5 编程模型：Single Instruction Multiple Threads，每个 thread 处理一个元素 |
| VF (Vector Function) | A5 上的向量函数，有寄存器约束（最多 32 个 RegTensor），内部 256 threads 并行 |
