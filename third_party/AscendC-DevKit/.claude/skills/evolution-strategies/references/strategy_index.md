# AscendC Kernel Optimization Strategy Index

Source: 43 production-grade operators + 6 CV fused operator expert implementations (IdeaPool). Select all applicable strategies for your operator, then **Read each referenced detail file** before writing AscendC code.

## 编号说明
P 系列编号中存在间隙（P15, P23, P27, P31, P36, P39），这些编号为预留位，当前无对应策略文件。
P53-P88 为 fork-B 增量补充的高级策略，已纳入本索引。
所有有效策略 ID 均在下方表格中列出。Agent 在 strategy_combination 中只应使用下方表格中的 ID。

## Layer 定义
- **L0 (Universal)**: 适用于几乎所有算子的通用策略（D1-D5, P1-P13, A1-A8）
- **L1 (Advanced)**: 适用于特定类别算子的高级策略（P14-P88）
- **L2 (Discovered)**: 进化过程中发现的新策略（X1+）

## Tags 体系
- `omni-ops`: 通用数据搬运模式
- `cv_fusion`: Cube+Vector 融合算子
- `flash_attention`: Flash Attention 系列
- `quantization`: 量化相关
- `moe`: MoE 模型特定
- `matmul`: 矩阵乘相关
- `manual`: 需要手动调优

---

## 策略选择入口：按算子族分类（推荐流程）

**采用策略时，先依据算子类型（族）定位本节，查看该族推荐策略，再结合文末的"按瓶颈类型查表"精调。**


---

### 1. MatMul 矩阵乘类

**典型算子**: MatMul, BatchMatMul, MatMul_MXFP4, MatMul_A16W16, MatMul_AllReduce

**L0 策略（Primary）**:

| ID | 策略 | 说明 |
|----|------|------|
| D1 | Mixed precision architecture | FP16/BF16 混合精度 |
| D3 | TilingKey-driven type dispatch | Host 侧多类型选择 |
| P1 | Double buffering | 内存密集型核心优化 |
| P4 | Multi-core load balancing | 多核负载均衡 |
| P7 | 32B alignment + DataCopyPad | 对齐优化 |
| A3 | Rounding mode control | Cast 精度控制 |

**L1 策略（Secondary，按需选取）**:

| ID | 策略 | 适用场景 |
|----|------|---------|
| P46 | MatmulImpl high-level API | 替代手写 matmul 流水线 |
| P47 | Diagonal block scheduling | 多核 M×N 分块 L2 cache 优化 |
| P49 | Hardware-accelerated dequantization | 硬件反量化 |
| P51 | Dynamic AIC/AIV core ratio | K 维阈值动态核配比 |
| P52 | L2 Cache Hint optimization | 多核竞争场景 L2 禁用 |
| P63 | Iterate async interface | 异步迭代接口 |
| P70 | FixPipe buffer inline quantization | FixPipe 内联量化 |
| P71 | Matmul IBShare L1 sharing | B 矩阵 L1 共享 |
| P72 | Matmul Split-K | K 轴切分多核并行 |
| P78 | On-chip cache matmul acceleration | 片上缓存加速 |
| P79 | Grad Cube2+Cube3 fusion | 梯度融合 |
| P83 | L1 resident reuse partition | L1 常驻复用分区 |
| P86 | Matmul API transport efficiency tuning | 数据通路效率 |
| P87 | Manual mmad pipeline timing control | 手动 Mmad 流水时序 |

---

### 2. Reduction 归约类

**典型算子**: ReduceSum, Softmax, LayerNorm, RMSNorm, ArgMax, BatchNorm

**L0 策略（Primary）**:

| ID | 策略 | 说明 |
|----|------|------|
| D1 | Mixed precision architecture | FP16/BF16 混合精度 |
| D2 | Template kernel type dispatch | 编译期多类型分发 |
| P1 | Double buffering | 减少搬运等待 |
| P2 | Adaptive tiling | 变长维度分块 |
| P3 | Small-D multi-row merging | 小 hidden size 优化 |
| P5 | Pipeline sync | 双缓冲同步 |
| A1 | FP32 intermediate computation | 精度保持 |
| A2 | Welford numerically stable mean/var | 数值稳定性 |
| A4 | SetFlag/WaitFlag event sync | 跨 pipe 同步 |
| A5 | Softmax numerical stability | Softmax 防溢出 |
| A6 | High-precision rsqrt | 归一化精度 |

**L1 策略（Secondary）**:

| ID | 策略 | 适用场景 |
|----|------|---------|
| P19 | Custom ping-pong double buffer | 自定义双缓冲 |
| P55 | Block reduce-max optimization | 块级 ReduceMax 优化 |
| P68 | Low-latency reduction | 低延迟归约指令 |
| P69 | UB fused vector chain | UB 内多步计算融合 |
| P81 | Resident UB/TBuf reuse | 小参数常驻复用 |
| P84 | Vector compute efficiency patterns | Counter+低延迟+融合链综合 |

---

### 3. Elementwise 逐元素类

**典型算子**: Sin, Cos, Abs, Exp, Sigmoid, ReLU, Add, Mul, Sub

**L0 策略（Primary）**:

| ID | 策略 | 说明 |
|----|------|------|
| D1 | Mixed precision architecture | 混合精度 |
| D2 | Template kernel type dispatch | 多类型分发 |
| P1 | Double buffering | 搬运隐藏 |
| P2 | Adaptive tiling | 分块适配 |
| A1 | FP32 intermediate computation | 精度保持 |
| A4 | SetFlag/WaitFlag event sync | 跨 pipe 同步 |

**L1 策略（Secondary）**:

| ID | 策略 | 适用场景 |
|----|------|---------|
| P67 | Vector counter mode | Scalar 控制流向量化 |
| P69 | UB fused vector chain | 多步计算融合 |
| P84 | Vector compute efficiency patterns | 综合 Vector 效率优化 |

---

### 4. Broadcast 广播类

**典型算子**: Add, Mul, Sub (broadcast), Mask 操作

**L0 策略（Primary）**:

| ID | 策略 | 说明 |
|----|------|------|
| D1 | Mixed precision architecture | 混合精度 |
| P1 | Double buffering | 搬运隐藏 |
| P12 | Broadcast & mask operations | 广播掩码原生支持 |
| A5 | Softmax numerical stability | 数值稳定 |

**L1 策略（Secondary）**:

| ID | 策略 | 适用场景 |
|----|------|---------|
| P67 | Vector counter mode | 向量化 |

---

### 5. Conversion 数据转换类

**典型算子**: Transpose, Concat, Split, Cast, Scatter, Gather

**L0 策略（Primary）**:

| ID | 策略 | 说明 |
|----|------|------|
| D1 | Mixed precision architecture | 混合精度 |
| D2 | Template kernel type dispatch | 多类型分发 |
| D3 | TilingKey-driven type dispatch | Host 侧分发 |
| P1 | Double buffering | 搬运隐藏 |
| P7 | 32B alignment + DataCopyPad | 对齐优化 |
| A3 | Rounding mode control | Cast 精度 |
| A7 | Index & boundary safety | 索引安全 |

**L1 策略（Secondary）**:

| ID | 策略 | 适用场景 |
|----|------|---------|
| P24 | ND2NZ format copy | 格式转换搬运 |
| P26 | Stride fused transpose | 步长融合转置 |
| P32 | Scatter block stride | 散射块步长 |
| P59 | Output transpose fusion | 输出转置融合 |
| P64 | GM address conflict avoidance | 多核访存冲突规避 |

---

### 6. RadixSort 基数排序类

**典型算子**: TopK, KthValue, Sort, ArgSort, ArgMax, ArgMin

**L0 策略（Primary）**:

| ID | 策略 | 说明 |
|----|------|------|
| D1 | Mixed precision architecture | 混合精度 |
| P1 | Double buffering | 搬运隐藏 |
| P2 | Adaptive tiling | 分块适配 |
| P11 | Tail block handling | 非均匀分块尾块 |
| A7 | Index & boundary safety | 索引安全 |

**L1 策略（Secondary）**:

| ID | 策略 | 适用场景 |
|----|------|---------|
| P33 | Gather offset table | 聚集偏移表 |
| P45 | TopK index cache iterator | TopK 索引缓存 |
| P55 | Block reduce-max optimization | 块级 ReduceMax |
| P56 | DataCopy batch output | 批量输出 |
| P59 | Output transpose fusion | 输出转置融合 |

---

### 7. Convolution 卷积类

**典型算子**: Conv2D, DepthwiseConv

**L0 策略（Primary）**:

| ID | 策略 | 说明 |
|----|------|------|
| D1 | Mixed precision architecture | 混合精度 |
| P1 | Double buffering | 搬运隐藏 |
| P2 | Adaptive tiling | 分块适配 |
| P4 | Multi-core load balancing | 多核均衡 |
| P7 | 32B alignment + DataCopyPad | 对齐优化 |
| A1 | FP32 intermediate computation | 精度保持 |

**L1 策略（Secondary）**:

| ID | 策略 | 适用场景 |
|----|------|---------|
| P46 | MatmulImpl high-level API | 高阶 API |
| P47 | Diagonal block scheduling | L2 cache 优化 |
| P52 | L2 Cache Hint optimization | 多核竞争 |
| P78 | On-chip cache matmul acceleration | 片上缓存加速 |

---

### 8. NN 神经网络类

**典型算子**: FlashAttention, GroupNorm, FFN, MoE, Optimizer

**L0 策略（Primary）**:

| ID | 策略 | 说明 |
|----|------|------|
| D1 | Mixed precision architecture | 混合精度 |
| P1 | Double buffering | 搬运隐藏 |
| P5 | Pipeline sync | 流水同步 |
| A4 | SetFlag/WaitFlag event sync | 事件同步 |
| A5 | Softmax numerical stability | Softmax 稳定 |

**L1 策略（Secondary，按子类型细分）**:

| 子类型 | 策略 ID | 说明 |
|--------|---------|------|
| FlashAttention/Attention | P14, P16, P17, P18, P29, P38, P53, P57, P58, P60, P61, P62, P76, P77, P80 | Attention 专用优化 |
| FFN/MoE | P46, P48, P49, P50, P73, P75, P88 | FFN 融合与 MoE 优化 |
| GroupNorm/Normalization | P19, P55, P68, P69, P81, P84 | 同 Reduction 类策略 |
| Optimizer | P81, P84 | 状态复用与 Vector 效率 |

---

### 9. Random 随机类

**典型算子**: RandomUniform, Dropout

**L0 策略（Primary）**:

| ID | 策略 | 说明 |
|----|------|------|
| D1 | Mixed precision architecture | 混合精度 |
| P1 | Double buffering | 搬运隐藏 |
| P9 | Deterministic output | 确定性输出 |
| A1 | FP32 intermediate computation | 精度保持 |

**L1 策略（Secondary）**:

| ID | 策略 | 适用场景 |
|----|------|---------|
| P81 | Resident UB/TBuf reuse | 状态常驻 |
| P84 | Vector compute efficiency patterns | Vector 效率 |

---

### 10. CV 融合算子（跨族通用）

**典型算子**: Cube+Vector 融合算子（FlashAttention、CV Matmul、CV FFN 等）

**L0 策略（Primary）**:

| ID | 策略 | 说明 |
|----|------|------|
| D1 | Mixed precision architecture | 混合精度 |
| D3 | TilingKey-driven type dispatch | 多类型分发 |
| P1 | Double buffering | 搬运隐藏 |
| P4 | Multi-core load balancing | 多核均衡 |
| P7 | 32B alignment + DataCopyPad | 对齐优化 |
| A3 | Rounding mode control | Cast 精度 |

**L1 策略（Secondary）**:

| ID | 策略 | 适用场景 |
|----|------|---------|
| P14 | CV pipeline preload | 流水预发射 |
| P16 | Cost-driven core partition | 代价模型分核 |
| P17 | CV parallel block sizing | 并行基本块 |
| P18 | L1 7-buffer resident partition | L1 七缓冲分区 |
| P29 | Cross-core AIC-AIV sync | 跨核同步 |
| P46 | MatmulImpl high-level API | 高阶 matmul |
| P49 | Hardware-accelerated dequantization | 硬件反量化 |
| P50 | SwiGLU fusion pipeline | SwiGLU 融合 |
| P51 | Dynamic AIC/AIV core ratio | 动态核配比 |
| P73 | CV parallel AIC:AIV ratio | AIC:AIV 配比 |
| P75 | Dual AIV workload split | 双 AIV 负载拆分 |
| P88 | Multiphase compute phase decomposition | 多阶段拆分 |

---

## 多数据类型支持策略 (D1-D5) [Layer: L0]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| D1 | Mixed precision architecture | L0 | omni-ops | Any op with FP16/BF16 input | strategy_cards/D1_mixed_precision.md |
| D2 | Template kernel type dispatch | L0 | omni-ops | Compile-time multi-type kernel | strategy_cards/D2_template_kernel.md |
| D3 | TilingKey-driven type dispatch | L0 | omni-ops | Host-side multi-type selection | strategy_cards/D3_tilingkey_dispatch.md |
| D4 | FP8/INT4 quantization conversion | L0 | quantization | Quantization output operators | strategy_cards/D4_fp8_int4_conversion.md |
| D5 | BF16-specific handling | L0 | omni-ops | BF16 output with rounding control | strategy_cards/D5_bf16_special_handling.md |

## 性能优化策略 — 通用 (P1-P13) [Layer: L0]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P1 | Double buffering (BUFFER_NUM=2) | L0 | omni-ops | Any memory-bound kernel | strategy_cards/P1_double_buffer.md |
| P2 | Adaptive tiling (Split-N vs Split-D) | L0 | omni-ops | Variable row/column dimensions | strategy_cards/P2_adaptive_tiling.md |
| P3 | Small-D multi-row merging | L0 | omni-ops | Hidden size ≤ 640 or small D | strategy_cards/P3_small_d_optimization.md |
| P4 | Multi-core load balancing | L0 | omni-ops | Uneven data distributions | strategy_cards/P4_load_balance.md |
| P5 | Pipeline sync (PipeBarrier/events) | L0 | omni-ops | All double-buffered kernels | strategy_cards/P5_pipeline_sync.md |
| P6 | Multi-algorithm adaptive selection | L0 | omni-ops | Normalization, reduction ops | strategy_cards/P6_multi_algo_selection.md |
| P7 | 32B alignment + DataCopyPad | L0 | omni-ops | Non-aligned input shapes | strategy_cards/P7_data_alignment.md |
| P8 | UB memory partitioning | L0 | omni-ops | Kernels with multiple UB tensors | strategy_cards/P8_ub_memory_mgmt.md |
| P9 | Deterministic output (workspace) | L0 | omni-ops | Training ops needing reproducibility | strategy_cards/P9_deterministic_output.md |
| P10 | Vectorized data copy | L0 | omni-ops | CopyIn/CopyOut optimization | strategy_cards/P10_vectorized_copy.md |
| P11 | Tail block handling (GatherMask) | L0 | omni-ops | Pooling/gather with uneven splits | strategy_cards/P11_tail_block_handling.md |
| P12 | Broadcast & mask operations | L0 | omni-ops | Operators with mask inputs, broadcasting | strategy_cards/P12_broadcast_mask.md |
| P13 | Special algorithms & high-level APIs | L0 | omni-ops | Complex control flow, irregular access | strategy_cards/P13_special_algorithms.md |

## 性能优化策略 — CV融合/高级调优 (P14-P18) [Layer: L1]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P14 | CV pipeline preload (3-slot task cache) | L1 | cv_fusion, flash_attention | Flash Attention Cube-Vector 流水预发射 | strategy_cards/P14_cv_pipeline_preload.md |
| P16 | Cost-driven core partition | L1 | cv_fusion, manual | Alignment-aware 代价模型分核 | strategy_cards/P16_cost_driven_core_partition.md |
| P17 | CV parallel block sizing | L1 | cv_fusion | CV 并行基本块设计 | strategy_cards/P17_cv_parallel_block_sizing.md |
| P18 | L1 7-buffer resident partition | L1 | cv_fusion, flash_attention | L1 七缓冲常驻分区 | strategy_cards/P18_l1_7buf_resident_partition.md |

## 性能优化策略 — 高级数据搬运 (P19-P45) [Layer: L1]

### 队列管理与双缓冲 (P19-P22)

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P19 | Custom ping-pong double buffer | L1 | omni-ops | 自定义 Ping-Pong 双缓冲管理 | strategy_cards/P19_custom_pingpong_double_buffer.md |
| P20 | Triple buffer rotation | L1 | omni-ops | 三缓冲轮转（搬入/计算/搬出完全重叠） | strategy_cards/P20_triple_buffer_rotation.md |
| P21 | Matrix 2×2 buffer policy | L1 | omni-ops | 2×2 矩阵缓冲策略 | strategy_cards/P21_matrix2x2_buffer_policy.md |
| P22 | TQueBind bidirectional reuse | L1 | omni-ops | TQueBind 双向复用 | strategy_cards/P22_tquebind_bidirectional_reuse.md |

### DataCopy 参数与对齐 (P24-P26)

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P24 | ND2NZ format copy | L1 | omni-ops | ND→NZ 格式转换搬运 | strategy_cards/P24_nd2nz_format_copy.md |
| P25 | DataCopy pad alignment | L1 | omni-ops | DataCopy 填充对齐优化 | strategy_cards/P25_datacopy_pad_alignment.md |
| P26 | Stride fused transpose | L1 | omni-ops | 步长融合转置 | strategy_cards/P26_stride_fused_transpose.md |

### 同步与流水控制 (P28-P30)

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P28 | HardEvent producer-consumer | L1 | omni-ops | HardEvent 生产者-消费者同步 | strategy_cards/P28_hardevent_producer_consumer.md |
| P29 | Cross-core AIC-AIV sync | L1 | cv_fusion | 跨核 AIC-AIV 同步 | strategy_cards/P29_crosscore_aic_aiv_sync.md |
| P30 | Dense PipeBarrier vector | L1 | omni-ops | 密集 PipeBarrier 向量同步 | strategy_cards/P30_dense_pipebarrier_vector.md |

### 特殊搬运模式 (P32-P33)

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P32 | Scatter block stride | L1 | omni-ops | 散射块步长搬运 | strategy_cards/P32_scatter_block_stride.md |
| P33 | Gather offset table | L1 | omni-ops | 聚集偏移表搬运 | strategy_cards/P33_gather_offset_table.md |

### 缓冲驻留与复用 (P34-P45)

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P34 | Weight load-once reuse | L1 | omni-ops | 权重一次加载多次复用 | strategy_cards/P34_weight_load_once_reuse.md |
| P35 | TBuf resident accumulator | L1 | omni-ops | TBuf 常驻累加器 | strategy_cards/P35_tbuf_resident_accumulator.md |
| P37 | Grad accumulator cross-batch | L1 | omni-ops | 梯度跨 batch 累加器 | strategy_cards/P37_grad_accumulator_cross_batch.md |
| P38 | Softmax state resident | L1 | flash_attention | Softmax 状态常驻 buffer | strategy_cards/P38_softmax_state_resident.md |
| P40 | Workspace double buffer | L1 | omni-ops | Workspace 双缓冲 | strategy_cards/P40_workspace_double_buffer.md |
| P41 | Gamma/scale resident | L1 | omni-ops | Gamma/scale 常驻 buffer | strategy_cards/P41_gamma_scale_resident.md |
| P42 | Workspace zone reuse | L1 | omni-ops | Workspace 分区复用 | strategy_cards/P42_workspace_zone_reuse.md |
| P43 | Grad ping-pong deferred scatter | L1 | omni-ops | 梯度 Ping-Pong 延迟散射 | strategy_cards/P43_grad_pingpong_deferred_scatter.md |
| P44 | Transpose buffer resident | L1 | omni-ops | 转置 buffer 常驻 | strategy_cards/P44_transpose_buffer_resident.md |
| P45 | TopK index cache iterator | L1 | omni-ops | TopK 索引缓存迭代器 | strategy_cards/P45_topk_index_cache_iterator.md |
## 性能优化策略 — CV融合算子架构模式 (P46-P52) [Layer: L1]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P46 | MatmulImpl high-level API | L1 | cv_fusion, matmul | 替代手写 matmul 流水线 | strategy_cards/P46_matmulimpl_highlevel_api.md |
| P47 | Diagonal block scheduling | L1 | cv_fusion, matmul | 多核 M×N 分块 L2 cache 优化 | strategy_cards/P47_diagonal_block_scheduling.md |
| P48 | Multi-quantization mode dispatch | L1 | quantization, matmul | 多量化模式编译期分发 | strategy_cards/P48_multi_quant_dispatch.md |
| P49 | Hardware-accelerated dequantization | L1 | quantization | AscendDequant 硬件反量化 | strategy_cards/P49_hw_dequantization.md |
| P50 | SwiGLU fusion pipeline | L1 | moe, cv_fusion | MoE FFN SwiGLU 融合 (narrow scope) | strategy_cards/P50_swiglu_fusion.md |
| P51 | Dynamic AIC/AIV core ratio | L1 | cv_fusion, matmul | K 维阈值动态核配比 | strategy_cards/P51_dynamic_aic_aiv_ratio.md |
| P52 | L2 Cache Hint optimization | L1 | cv_fusion, matmul | 多核竞争场景 L2 禁用 | strategy_cards/P52_l2_cache_hint.md |

## 性能优化策略 — 片上缓存与常驻复用 (P53-P56) [Layer: L1]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P53 | L1 resident reuse | L1 | cv_fusion, flash_attention | Q 矩阵 L1 常驻跨迭代复用，消除重复搬运 | strategy_cards/P53_l1_resident_reuse.md |
| P54 | Launch overhead optimization | L1 | omni-ops | 减少 kernel launch 开销，合并小 kernel | strategy_cards/P54_launch_overhead_optimization.md |
| P55 | Block reduce-max optimization | L1 | omni-ops | 块级 ReduceMax 优化，二分累加 | strategy_cards/P55_block_reduce_max_optimization.md |
| P56 | DataCopy batch output | L1 | omni-ops | 批量 DataCopy 输出，减少搬运次数 | strategy_cards/P56_datacopy_batch_output.md |

## 性能优化策略 — FlashAttention/Decode 专用 (P57-P58) [Layer: L1]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P57 | FlashDecode G-partition reduction | L1 | flash_attention | FlashDecode G 维分区归约 | strategy_cards/P57_flashdecode_g_partition.md |
| P58 | TND load-balanced partition | L1 | flash_attention | T/N/D 维负载均衡分区 | strategy_cards/P58_tnd_load_balance_partition.md |

## 性能优化策略 — 数据搬运与格式优化 (P59-P66) [Layer: L1]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P59 | Output transpose fusion | L1 | omni-ops | 输出转置融合，减少额外搬运 | strategy_cards/P59_output_transpose_fusion.md |
| P60 | KV NZ format optimization | L1 | matmul, flash_attention | KV cache NZ 格式优化 | strategy_cards/P60_kv_nz_format_optimization.md |
| P61 | L2 cache optimization | L1 | flash_attention | 关闭双页表开启 L2 Cache，KV 数据缓存 | strategy_cards/P61_l2_cache_optimization.md |
| P62 | Sparse/dense dual-path dispatch | L1 | flash_attention | 稀疏/稠密双路径分发 (draft) | strategy_cards/P62_sparse_dense_dual_path_dispatch_dra.md |
| P63 | Iterate async interface | L1 | matmul | 异步迭代接口，隐藏搬运延迟 | strategy_cards/P63_iterate_async_interface.md |
| P64 | GM address conflict avoidance | L1 | omni-ops | GM 地址冲突规避，优化多核访存 | strategy_cards/P64_gm_address_conflict_avoidance.md |
| P65 | UB bank conflict avoidance | L1 | omni-ops | UB bank 冲突规避，优化地址分配 | strategy_cards/P65_ub_bank_conflict_avoidance.md |
| P66 | GM 512B alignment bandwidth | L1 | omni-ops | GM 512B 对齐带宽优化 | strategy_cards/P66_gm_512b_alignment.md |

## 性能优化策略 — Vector 计算效率 (P67-P69) [Layer: L1]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P67 | Vector counter mode | L1 | omni-ops | Vector counter 模式，Scalar 控制流优化 | strategy_cards/P67_vector_counter_mode.md |
| P68 | Low-latency reduction | L1 | omni-ops | 低延迟归约指令组合 (BlockReduceSum+WholeReduceSum) | strategy_cards/P68_low_latency_reduction.md |
| P69 | UB fused vector chain | L1 | omni-ops | UB 融合连续 Vector 计算链，中间结果保留 UB | strategy_cards/P69_ub_fused_vector_chain.md |

## 性能优化策略 — Matmul/量化专用 (P70-P72) [Layer: L1]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P70 | FixPipe buffer inline quantization | L1 | matmul, quantization | FixPipe buffer 内联量化 | strategy_cards/P70_fp_buffer_inline_quant.md |
| P71 | Matmul IBShare L1 sharing | L1 | matmul | Matmul IBShare L1 共享，减少重复搬运 | strategy_cards/P71_matmul_ibshare_l1.md |
| P72 | Matmul Split-K | L1 | matmul | K 轴切分多核并行，AtomicAdd 累加 | strategy_cards/P72_matmul_split_k.md |

## 性能优化策略 — CV 并行与核配比 (P73-P75) [Layer: L1]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P73 | CV parallel AIC:AIV ratio | L1 | cv_fusion | AIC:AIV 核配比与多 Workspace 流水 | strategy_cards/P73_cv_parallel_aic_aiv_ratio.md |
| P74 | Selective L2 cache disable | L1 | omni-ops | 选择性 L2 cache 禁用，减少多核竞争 | strategy_cards/P74_selective_l2_cache_disable.md |
| P75 | Dual AIV workload split | L1 | cv_fusion | 双 AIV M/S1 轴负载拆分 | strategy_cards/P75_dual_aiv_workload_split.md |

## 性能优化策略 — Sparse Attention 专用 (P76-P78) [Layer: L1]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P76 | V_TEMPLATE KV pre-merge workspace | L1 | flash_attention | KV 预合并 Workspace 管理 | strategy_cards/P76_v_template_kv_premerge.md |
| P77 | L1 chunk iterator sparse aggregation | L1 | flash_attention | L1 分块迭代器稀疏自适应聚合 | strategy_cards/P77_l1_chunk_iterator_sparse_aggregatio.md |
| P78 | On-chip cache matmul acceleration | L1 | matmul | 片上缓存加速 Matmul | strategy_cards/P78_onchip_cache_matmul_acceleration.md |

## 性能优化策略 — 高级流水与融合 (P79-P84) [Layer: L1]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P79 | Grad Cube2+Cube3 fusion | L1 | matmul | 梯度 Cube2+Cube3 融合 | strategy_cards/P79_grad_cube23_fusion.md |
| P80 | Sink task pipeline injection | L1 | flash_attention | Sink task 流水注入与 S2 block skip | strategy_cards/P80_sink_task_pipeline_injection.md |
| P81 | Resident UB/TBuf reuse | L1 | omni-ops | 小参数/状态常驻 UB/TBuf，跨迭代复用 | strategy_cards/P81_resident_ub_tbuf_reuse.md |
| P82 | Manual multi-buffer pipeline policy | L1 | omni-ops, manual | 手动 BufferPolicy 多阶段流水管理 | strategy_cards/P82_manual_multi_buffer_pipeline_policy.md |
| P83 | L1 resident reuse partition | L1 | matmul | L1 常驻复用多缓冲分区 | strategy_cards/P83_l1_resident_reuse_partition.md |
| P84 | Vector compute efficiency patterns | L1 | omni-ops | Counter 模式+低延迟指令+UB 融合链 | strategy_cards/P84_vector_compute_efficiency_patterns.md |

## 性能优化策略 — 缓冲区复用与 Matmul 调优 (P85-P88) [Layer: L1]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| P85 | On-chip buffer zone reuse | L1 | omni-ops | 片上 buffer 分区复用 | strategy_cards/P85_on_chip_buffer_zone_reuse.md |
| P86 | Matmul API transport efficiency tuning | L1 | matmul | Matmul 内部数据通路效率调优 | strategy_cards/P86_matmul_api_transport_efficiency_tun.md |
| P87 | Manual mmad pipeline timing control | L1 | matmul, manual | 手动 Mmad 流水时序控制 | strategy_cards/P87_manual_mmad_pipeline_timing_control.md |
| P88 | Multiphase compute phase decomposition | L1 | cv_fusion | 多阶段计算拆分，独立 TPipe 资源重分配 | strategy_cards/P88_multiphase_compute_phase_decomposit.md |

## 精度优化策略 (A1-A8) [Layer: L0]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| A1 | FP32 intermediate computation | L0 | omni-ops | BF16/FP16 with precision requirement | strategy_cards/A1_fp32_intermediate.md |
| A2 | Welford numerically stable mean/var | L0 | omni-ops | LayerNorm, BatchNorm, RMSNorm | strategy_cards/A2_welford_algorithm.md |
| A3 | Rounding mode control (CAST_*) | L0 | omni-ops | Any Cast to lower precision | strategy_cards/A3_rounding_mode.md |
| A4 | SetFlag/WaitFlag event sync | L0 | omni-ops | Data dependencies across pipes | strategy_cards/A4_pipeline_barrier.md |
| A5 | Softmax numerical stability | L0 | omni-ops | Softmax, attention score ops, NaN/Inf risk | strategy_cards/A5_softmax_stability.md |
| A6 | High-precision rsqrt (Newton-Raphson) | L0 | omni-ops | Normalization ops needing rsqrt | strategy_cards/A6_high_precision_rsqrt.md |
| A7 | Index & boundary safety | L0 | omni-ops | Gather/scatter, user-controlled indices | strategy_cards/A7_index_boundary.md |
| A8 | Quantization-specific precision | L0 | quantization | Quantization output, dequantization with bias | strategy_cards/A8_quant_precision.md |

## 探索发现策略 (Discovered Strategies) [Layer: L2]

| ID | Strategy | Layer | Tags | When to Apply | Detail File |
|----|----------|-------|------|---------------|-------------|
| X1 | Inline Target Capture | L2 | — | Reduce + single-element lookup ops | discovered/disc_X1.md |

---

## 策略文件三层结构 (Three-Tier Architecture)

本索引中的策略文件按以下三层结构组织：

1. **Strategy Cards** (`strategy_cards/{ID}_{slug}.md`)：精简策略卡片（~40行），含 YAML frontmatter（id, bottlenecks, op_families, complexity, conflicts_with, synergizes_with），用于快速筛选和定性判断。
2. **Strategy Playbooks** (`strategy_playbooks/{ID}_{slug}.md`)：详细操作手册（Step 1-6：定位 → 计划 → 改造 → 约束复核 → 编码自检 → 已知陷阱），子 agent 执行策略时必须遵循的强制流程。
3. **Strategy Preconditions** (`strategy_preconditions/{ID}.yaml`)：先决条件检查（grep_count / grep_value / profiling_metric），用于在注入策略前硬门控验证当前算子是否适用。

> **读取优先级**：对于已有 Playbook 的策略（P1, P2, P4, P5, P7, P8, P10, P13, P14, P55, P66, P67, P68, P69, P81, D1），Agent 应遵循 `Card → Preconditions → Playbook` 的读取流程；其余策略读取 Card 即可。

---

## How to Use

1. **确定算子族**: 根据算子名称和功能，从本文档"按算子族分类"章节定位所属算子族
2. **选择策略**: 从该族推荐的 L0（Primary）和 L1（Secondary）策略中，结合算子特性（dtype, shape）选取所有适用策略
3. **三层读取流程**：
   a. 读取 `strategy_cards/{ID}_{slug}.md` 了解策略概要、瓶颈匹配、适用算子类型、冲突与协同策略
   b. （如策略有 Playbook）读取 `strategy_preconditions/{ID}.yaml` 验证当前算子代码是否满足先决条件
   c. （如策略有 Playbook）读取 `strategy_playbooks/{ID}_{slug}.md` 获取 Step 1-6 的详细操作步骤
   d. 其余策略直接读取 Card 即可
4. Apply the selected patterns in `tiling_pass`, `init_pass`, `process_pass`, `process_nonaligned_pass`
5. **Check compatibility**: Read `strategy_compatibility.md` to verify no mutual exclusions and all dependencies are met
6. **Preconditions 硬门控**：在注入策略代码前，必须先通过 `strategy_preconditions/{ID}.yaml` 中定义的所有检查项，任一失败则放弃该策略或记录跳过原因

### 按瓶颈类型查表 (Bottleneck-Driven Strategy Selection)

供世界模型 profiling_evidence 参考：

| Bottleneck Type | Primary | Secondary | Anti |
|-----------------|---------|-----------|------|
| mte2_stall | P1, P10 | P2, P7, P19, P18, P56, P59, P66 | P3 |
| mte3_stall | P1 | P8, P19, P40, P56, P59 | — |
| tiling_imbalance | P4, P2 | P11, P47, P51, P58, P72, P73, P75 | P3 |
| scalar_loading | P5, P67 | P2, P54 | — |
| scalar_compute | P5, P67 | P84 | — |
| compute_bound | P13, D1, P46 | A1, P47, P68, P69, P79, P84 | — |
| near_optimal | — | — | — |
| no_overlap | P1 | P10, P19, P63, P82 | — |
| partial_overlap | P1, P2 | P8, P18, P26, P53, P83 | — |
| undersize_transfer | P2, P10 | P7, P25, P45, P66 | — |
| icache_miss | — | — | P13 |
| bus_contention | P8, P65 | P1, P28, P64 | — |
| l2_cache_thrash | P52, P74 | P61, P78 | — |
| ub_memory_pressure | P8, P85 | P81, P88 | P20 |
