# 参考算子表（代码调研入口）

> 13 类算子各列 1~2 个代表性真实实现，作为**筛选参考实现的线索**。表中路径为相对两仓库根的路径。
> 注意：名称/类型匹配只是筛选线索，不构成可复用证据——任何复用前仍需按本 skill 的 guardrails 做独立设计判断。

## 数学类算子（Math 系）

| 算子类别 | 代表实现 | 看什么 |
|---------|---------|--------|
| 逐元素数学函数 | `math/atanh/op_kernel/arch35/atanh_simt.h` | 纯 SIMT 大 kernel：grid-stride + uint64 防溢出 + 泰勒展开精度 |
| | `math/cos/op_kernel/arch35/cos_dag.h` | DAG 表达式模板 + SIMT 自定义节点 |
| 规约 / 扫描 | `math/cumulative_logsumexp/op_kernel/arch35/cumulative_logsumexp_simt.h` | 每线程一输出"重算前缀"免同步扫描 |
| | `math/cosine_similarity/op_kernel/arch35/cosine_similarity_simt.h` | warp 分摊 + shuffle 归约 + 两遍扫描防溢出 |
| 排序 / TopK | `math/sort/op_kernel/arch35/common/radix_more_core_base.h` | 多核 radix：直方图指令 + lookback 软同步 + SIMT 散射 |
| | `math/top_k_v2/op_host/arch35/top_k_v2_tiling_arch35.cpp` | TopK 7 级模式选择树 |
| 直方图 / 计数 | `math/histogram_fixed_width/op_kernel/arch35/histogram_fixed_width_simt_full_load.h` | UB 私有直方图 + 原子 DMA 折叠 + 6 路展开 |
| | `math/ragged_bin_count/op_kernel/arch35/ragged_bin_count_simt.h` | binary 假共享实证 + 确定性精确累加 |
| 数据转换 / 重排 | `conversion/as_strided/op_kernel/arch35/as_strided_simt.h` | 坐标变换主范式 + magic 快除 + 高维降参数 |
| | `conversion/view_copy/op_kernel/arch35/view_copy_simt_dim3.h` | 连续侧 DMA + 离散侧 SIMT 混合 |
| 随机数生成 | `random/random_common/op_kernel/arch35/random_kernel_base.h` | Philox 快进 + Transform 仿函数注入 + IEEE754 尾数拼接 |
| | `random/stateless_randperm/op_kernel/arch35/stateless_randperm.h` | sort-by-key 洗牌 + 岛内 Fisher-Yates |

## 神经网络类算子（NN 系）

| 算子类别 | 代表实现 | 看什么 |
|---------|---------|--------|
| Gather / Embedding | `index/gather_v2/op_kernel/arch35/gather_v2_simt_two_dim.h` | 尾轴字节数分流 + 间接寻址 + 负索引 NIS 模板 |
| | `index/embedding_bag/op_kernel/arch35/embedding_bag_regbase_1d_simt.h` | 2D 线程块 + bag 内串行聚合 |
| Scatter | `index/scatter_add/op_kernel/arch35/scatter_add_simt_sort.h` | 排序段内串行 + 单次原子 |
| | `index/scatter_update/op_kernel/arch35/scatter_update_common.h` | mask-max 确定性 last-write |
| Segment | `index/segment_sum/op_kernel/arch35/segment_sum_simt.h` | 段边界向量检测 + 首尾段原子 + 两阶段确定性 |
| | `index/unsorted_segment_common/op_kernel/arch35/unsorted_segment_base.h` | Functor 注入 + 输出幺元预填充 |
| Foreach | `foreach/foreach_log/op_kernel/arch35/foreach_log_simt.h` | SimtGetTensorAddr + grid-stride 遍历全 tensor |
| | `foreach/foreach_add_list/op_host/arch35/foreach_add_list_tiling_arch35.cpp` | per-core tensor 区间表 |
| Pooling | `pooling/adaptive_avg_pool2d/op_kernel/arch35/adaptive_avg_pool2d_simt.h` | floor/ceil 窗口公式 + magic 快除 |
| | `pooling/max_pool_grad/op_kernel/arch35/max_pool_grad_simt.h` | 两阶段（先重搜 argmax 再 gather 回传） |
| Hash / Optim / Loss | `hash/embedding_hash_table_lookup_or_insert/op_kernel/arch35/kernel_lookup_or_insert_general.h` | CAS 抢槽 + 状态位发布 + warp 广播 |
| | `loss/nll_loss/op_kernel/arch35/nll_loss_simt.h` | 三级确定性树形归约 |
| 其他 NN 算子 | `conv/deformable_offsets/op_kernel/arch35/deformable_offsets.h` | 每线程一采样点 + 4 邻域双线性 gather |
| | `matmul/sparse_tensor_dense_mat_mul/op_kernel/arch35/sparse_tensor_dense_mat_mul_b32.h` | COO gather + atomicAdd |

## 检索建议

- 同一类别先看**最简单**的实现建立心智模型，再看最复杂的（如排序先看 single-block 再看 multi-core radix）。
- 每个实现重点读三处：`op_host/arch35/*tiling*.cpp`（模板路由 + 分核）、`op_kernel/arch35/*.h`（VF 结构与线程映射）、`*_tiling_data.h`（host-kernel 契约布局）。
