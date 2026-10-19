# 13 类算子设计速查 + 详细策略索引

> 本文件是 skill 内嵌的**一页速查**；深度展开见 skill 根目录 **`kimi_simt_strategy.md`**（391 条策略、6766 行，含每条策略的源码片段与出处路径）。每类速查表末尾的「详细策略」行可直达对应章节。

## 一、速查表（每类算子核心设计决策）

### 逐元素数学函数（Elementwise Math）

| 项 | 设计 |
|----|------|
| Tiling | DAG 表达式模板（`Bind<Op, Inputs>` 声明计算图，`DAGSch` 编译期展开），tiling 走 `ElewiseBaseTiling`/`BroadcastBaseTiling`；blockDim 封顶物理核数；纯 SIMT 手写分核（atanh/tan） |
| Kernel | DAG 内嵌 SIMT 自定义节点（`ElemwiseUnaryOP` + `asc_vf_call` 在 UB tile 上启动）；纯 SIMT GM 直读写 + grid-stride + uint64 防溢出；int64 索引线程减半；精度处理（atanh 泰勒展开、expm1 fmaf 多项式、mul double 位软实现、gcd Stein 算法） |
| 详细策略 | 第一章（T1~T12 / K1~K16）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### 规约 / 扫描（Reduce/Scan）

| 项 | 设计 |
|----|------|
| Tiling | **不沿规约轴切核**，规约轴由线程/warp/核内部消化；每核最小工作量 1024/128B；按最大工作量子循环估核（prod_force）；单核全线程归约（trace BlockDim=1） |
| Kernel | 每线程一帧串行（volatile 防 FMA）；每 warp 一输出（lane 分摊 + asc_reduce_add/shfl_down）；每线程一条扫描线（cummin）；重算前缀免同步（cumulative_logsumexp）；预计算 stride 广播（cross/polar） |
| 详细策略 | 第二章（T1~T12 / K1~K13）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### 排序 / TopK

| 项 | 设计 |
|----|------|
| Tiling | 分层 Schedule 路由树（小轴→非尾轴→归并→radix 逐级 Try）；SIMT 预留 32KB UB；tileData 按 UB 反解向 256 对齐；TopK 7 级模式选择树 |
| Kernel | 多核 radix LSD（直方图指令 + lookback 软同步 + SIMT 散射）；两阶段小轴（SIMD Sort API + SIMT rank-inverse 还原）；kth radix select 缩桶；CRTP 基类复用（sort/kth/topk 共享） |
| 详细策略 | 第三章（T1~T14 / K1~K27）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### 直方图 / 计数（Histogram/Bincount）

| 项 | 设计 |
|----|------|
| Tiling | 三档路由：bins<UB→full_load；输入密集→分块多轮；稀疏→GM 原子直写；清零/统计双任务分核取 max |
| Kernel | UB 私有直方图 + 线程级 UB 原子 + DMA 原子折叠；确定性用 int32 原子代 float 原子三阶段；binary 输出 read+atomic_exch 防假共享；TwoSum/五 limb 精确累加 |
| 详细策略 | 第四章（T1~T8 / K1~K13）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### 数据转换 / 重排（Conversion）

| 项 | 设计 |
|----|------|
| Tiling | SIMT 作小 shape/高维/负步长兜底；按输出元素一维均分；cacheline(128B) 对齐分核；concat/split_v 负载偏斜启发式拒绝 SIMT；pad_v3 负 pad 转 slice / 合轴优化 |
| Kernel | 输出驱动 gather 主范式（每线程一输出元素→逆向算源地址）；magic 快除贯穿；维度模板展开 Dim1~8；连续侧 DMA + 离散侧 SIMT 混合；高维降参数（GET_TILING_DATA_PTR） |
| 详细策略 | 第五章（T1~T21 / K1~K28）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### 随机数生成（Random）

| 项 | 设计 |
|----|------|
| Tiling | OpTilingConfig 回调式统一框架（SIMD/SIMT 双模式）；SplitBlocks 递归对半切（32bit 索引）；每块 Philox counter 偏移预计算；stateless 填 0 占位 + kernel 读 GM |
| Kernel | Philox4x32-10（uint2 优化）+ SkipHi/Lo/FlashCounter 无状态并行；Transform 仿函数注入；IEEE754 尾数拼接归一化；拒绝采样每线程 256 配额；sort-by-key 洗牌（randperm） |
| 详细策略 | 第六章（T1~T12 / K1~K19）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### Gather / Embedding（索引收集）

| 项 | 设计 |
|----|------|
| Tiling | 尾轴字节数决定 SIMT/SIMD（2048B，按 dtype 收紧）；XDtypeImprove 提升拷贝粒度；线程数自适应收缩；UB 全载模板前置判定（bank 冲突规避）；embedding_no_contiguous 独立模板 |
| Kernel | 每线程一输出元素间接寻址；负索引回绕（NIS 模板）；越界填 0/skip；embedding_bag 二维线程块 bag 内串行聚合；no_contiguous 两遍协作（strided indices 搬 UB 致密化） |
| 详细策略 | 第七章（T1~T19 / K1~K21）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### Scatter（索引散布）

| 项 | 设计 |
|----|------|
| Tiling | 尾轴 128B 判定 SIMT；确定性关排序；UB 二分求 indicesFactor；按 updates 元素/输出槽位/行三粒度分核；mask-max 确定性 last-write |
| Kernel | 冲突 8 档谱系（见策略文档第八章 + 附录 B）；排序段内串行 + 单次原子；int8 三段式；SIMD SetAtomicAdd 整块原子拷贝；CAS 自旋乘法 |
| 详细策略 | 第八章（T1~T11 / K1~K15）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### Segment / 稀疏聚合

| 项 | 设计 |
|----|------|
| Tiling | 模板注册表竞选（SIMT 恒兜底）；入出比≥5 且 innerDim<512 启用 Sort+SIMT；索引降位 Cast；按行均分 + 首尾段原子 |
| Kernel | 原子聚合（Functor 注入）；排序段内归并；段边界向量指令检测（Compare NE + Squeeze + AR 寄存器）；跨界段两阶段确定性；空段/除零保护 |
| 详细策略 | 第九章（T1~T15 / K1~K18）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### Foreach（多张量逐元素）

| 项 | 设计 |
|----|------|
| Tiling | 扁平化一维逻辑空间 + per-core tensor 区间表 / 累计偏移表 / count 数组三流派；核数下限 1024 + 32 对齐 |
| Kernel | SimtGetTensorAddr/ListTensorDesc 地址表；4 种扁平空间定位模式；int32 除零保护；纯 embarrassingly parallel（无原子无同步） |
| 详细策略 | 第十章（T1~T8 / K1~K9）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### Pooling

| 项 | 设计 |
|----|------|
| Tiling | 多模板 IsCapable 竞争（SIMT 兜底）；输出/输入元素总数分核；窗口重叠检测决定 scatter/gather 路径；NaN 语义位编 key |
| Kernel | 每线程一输出元素，floor/ceil 公式反算窗口（magic 快除）；avg grad 按输入反算输出窗口 gather 免原子；max grad 两阶段（先重搜 argmax 再回传）；坐标分解按布局选轴序 |
| 详细策略 | 第十一章（T1~T12 / K1~K18）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### Hash / 稀疏优化器 / Loss

| 项 | 设计 |
|----|------|
| Tiling | 2D 线程块按 embeddingDim 划分；按稀疏元素总数分核（最小 1024）；batch 分核保证单写者（chamfer）；A 轴分核 + R 轴全载/切分双模板（sparse_softmax_ce） |
| Kernel | MurmurHash3 + atomicCAS 抢槽 + 状态位发布；threadX 分量级 AdamW 更新；sparse_apply 扁平 grid-stride 读改写（无原子 last-write）；nll_loss 三级确定性树形规约；CTC DP threadX 定状态位 + t 维串行 |
| 详细策略 | 第十二章（T1~T11 / K1~K20）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

### 其他 NN 算子（Misc）

| 项 | 设计 |
|----|------|
| Tiling | erfinv/threshold 复用 ElewiseBaseTiling 或轻量均分；值依赖 Tiling（sleep）；三阶段异构分核（sparse_mm）；按通道数路由 SIMT/Generic（msda） |
| Kernel | erfinv 用 SIMT 库函数嵌 DAG；deformable_offsets 每线程一采样点 + 4 邻域双线性 gather（grad 用 atomicAdd）；sparse_mm COO gather + atomicAdd（B16 走 fp32 workspace）；swiglu_group_grad 数值重写 + NumPy pairwise 位级复刻 |
| 详细策略 | 第十三章（T1~T8 / K1~K8）：[kimi_simt_strategy.md](../kimi_simt_strategy.md) |

---

## 二、详细策略索引（→ kimi_simt_strategy.md）

> `kimi_simt_strategy.md` 与本 skill 同目录。13 章正文 + 通用框架 + 3 附录，共 **391 条策略**（Tiling 163 条 / Kernel 228 条），每条含源码片段与出处路径。索引方式：先查下方章节表定位，再按策略编号（T= Tiling / K= Kernel）进入对应小节。

### 章节总览

| 章节 | 内容 | 策略规模 |
|------|------|---------|
| [第〇章](../kimi_simt_strategy.md) | SIMT 编程模型与跨类别通用约定（骨架、tiling/kernel 通用约定、写冲突方案谱系） | 0 条（约定 18 项） |
| [第一章](../kimi_simt_strategy.md) 逐元素数学函数 | DAG 表达式模板 + SIMT 节点、纯 SIMT 大 kernel、精度策略 | T12 + K15 = 27 |
| [第二章](../kimi_simt_strategy.md) 规约与扫描 | 核间切外轴、warp 归约、串行扫描线、四路径路由 | T12 + K13 = 25 |
| [第三章](../kimi_simt_strategy.md) 排序/TopK | 分层路由树、多核 radix + lookback、两阶段小轴、CRTP 复用 | T14 + K27 = 41 |
| [第四章](../kimi_simt_strategy.md) 直方图/计数 | 三档模板、原子三级落点、确定性三路线 | T8 + K13 = 21 |
| [第五章](../kimi_simt_strategy.md) 数据转换/重排 | 坐标变换主范式、混合流水、维度模板、降参数 | T21 + K28 = 49 |
| [第六章](../kimi_simt_strategy.md) 随机数生成 | Philox 快进、确定性三路线、Transform 注入 | T12 + K19 = 31 |
| [第七章](../kimi_simt_strategy.md) 索引收集 | 尾轴分流、间接寻址、前缀和定位、no_contiguous | T19 + K21 = 40 |
| [第八章](../kimi_simt_strategy.md) 索引散布 | 冲突 8 档、排序归并、mask-max、workspace 三段式 | T11 + K15 = 26 |
| [第九章](../kimi_simt_strategy.md) 段聚合 | 原子 vs 排序归并、跨界段确定性、向量段边界检测 | T15 + K18 = 33 |
| [第十章](../kimi_simt_strategy.md) Foreach | tensor-list 三流派、4 种定位模式、CRTP 复用 | T8 + K9 = 17 |
| [第十一章](../kimi_simt_strategy.md) 池化 | 窗口公式、gather 免原子 grad、双路径重叠处理 | T12 + K18 = 30 |
| [第十二章](../kimi_simt_strategy.md) Hash/Optim/Loss | CAS 抢槽、AdamW 分量更新、CTC DP、三级树形归约 | T11 + K20 = 31 |
| [第十三章](../kimi_simt_strategy.md) 其他 NN 算子 | 双线性 gather、COO+atomic、pairwise 复刻、值依赖 Tiling | T8 + K8 = 16 |
| [附录 A](../kimi_simt_strategy.md) | SIMT↔SIMD 模板选择经验阈值汇总表 | 13 项阈值 |
| [附录 B](../kimi_simt_strategy.md) | 确定性实现谱系（8 路线） | 8 路线 |
| [附录 C](../kimi_simt_strategy.md) | 性能优化技巧速查表 | 10 技巧 |

### 按设计问题索引（推荐检索路径）

| 想解决的问题 | 定位 |
|-------------|------|
| 我的算子该用 SIMT 还是 SIMD？ | 附录 A 阈值表 + 各章 T1（分流判据） |
| 核数怎么分？ | 第〇章 0.3 + 各章 Tiling 首条 |
| 写冲突怎么办？ | 第八章全部 + 第四章 K1-K3 + 附录 B |
| 要确定性结果？ | 附录 B + 第四章 K7/K8 + 第九章 K8/K10 |
| 精度对不上 golden？ | 第一章 K5-K7、第二章 K1、第五章 K6、附录 C |
| SIMT 与 SIMD 怎么分工？ | 第〇章 0.4 + 第五章 K28 + 第六章 K9/K10 |
| 想复用现有排序/归约逻辑？ | 第三章 K26（CRTP）、第九章 K2（Functor）、第八章 K9（公共库） |
| workspace 怎么规划？ | 第〇章 0.3 workspace 项 + 第三章 T7 + 第九章 T6 |
