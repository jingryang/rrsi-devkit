# SIMT 开发经验（模板选择 / 审查清单 / 性能实践）

> 开发与审查 SIMT 算子时的经验沉淀。设计决策细节见各设计单篇与深度策略库；本节给"怎么做"的工程级建议。

## 1. 模板选择启发式（决定走 SIMT 还是别的路）

按以下顺序判断，命中即停：

1. **语义保证**：indices 唯一 → 免原子直写（scatter_non_aliasing_add 模式）。
2. **确定性需求**（`GetDeterministic()`）：命中确定性路线（见深度策略库附录 B），并在 tiling 侧识别 dtype 白名单。
3. **访存形态**：两侧连续 → SIMD/DMA；两侧离散或一连续一离散 → SIMT（或混合）。
4. **尾轴连续块字节数**：对照经验阈值表（`template-routing.md` §3 / 深度策略库附录 A），够大走 SIMD 批量搬，小颗粒走 SIMT。
5. **冲突率**：重复索引多 → 排序归并；目标可入 UB → 私有副本。
6. **数据规模**：小 shape / 高维 / 负步长 → SIMT 兜底。

## 2. 审查清单（上线前逐项自查）

### Tiling 侧
- [ ] blockDim 是否封顶物理核数（防 507035）？
- [ ] 小 shape 是否做每核最小工作量钳制 + 32 对齐？
- [ ] 多阶段算子（清零+计算）是否两套分核取 max？
- [ ] kernel 有 `SyncAll()` 时是否 `SetScheduleMode(1)`？
- [ ] workspace 大小含 16MB 系统区？分段公式与 kernel 逐段一致？有无 uint64 溢出？
- [ ] SIMT 模板 host tiling 已 `SetDynUBufSize` 声明 Dynamic Unified Buffer（默认 0 = 不声明；旧名 SetLocalMemorySize 语义一致）且大小与 DCache/静态预留一致（host 私有化决策 = device 分配）？
- [ ] tilingKey 与 kernel 侧 `TILING_KEY_IS` / `if constexpr` 一一对应？
- [ ] deterministic 分支：dtype 白名单 + workspace 追加 + 模板选择？

### Kernel 侧
- [ ] VF 内索引/stride 全程 uint64 防溢出？
- [ ] 除法是否全部换 magic 快除（大索引场景除外）？
- [ ] int32/int64 双轨判定含**中间乘积**（shape*stride / isize*osize）？
- [ ] 负索引回绕 + 越界处理是否覆盖（NIS 模板 / 归一化 / skip）？
- [ ] 无原子指令 dtype（int8/fp16 等）是否走 workspace 三段式？
- [ ] 需要跨 VF 全核同步处是否显式 `SyncAll()`（不能依赖 VF 顺序）？
- [ ] 需要算子核号时是否在外层读取后显式传参（勿用 VF 内 blockIdx）？
- [ ] 精度：half/bf16 升 fp32？需要对齐 golden 处是否 volatile 阻 FMA / 复刻 Pairwise？
- [ ] 共享 buffer：host `CalcUBTotalSize` 与 kernel `InitBuffer` 逐项对称？

## 3. 性能实践要点

| 实践 | 说明 | 出处 |
|------|------|------|
| 循环展开 | 6 路展开交叠加载与原子加延迟；8 路展开 rank 统计 | histogram、sort 两阶段 |
| asc_ldcg/stcg | 绕 L1 cache 的 GM 读写（随机读带宽） | histogram、coalesce_sparse |
| 连续侧 DMA + 离散侧 SIMT | 一侧连续一侧离散时混合，不要全 SIMT 也不要全 DMA | view_copy、batch_to_space_nd |
| UB 私有副本 + DMA 原子折叠 | 随机写打 UB，GM 只有每核一次连续原子 DMA | histogram full_load |
| 线程数按寄存器分档 | 纯搬运 2048 / 默认 1024 / 寄存器密集 512 / 高维累加 256 及以下 | 全仓库 |
| warp shuffle 规约 | asc_reduce_add 仅部分 dtype；手写 shfl_down 兼容全 dtype | trace、cosine_similarity |
| bank 冲突 padding | 行跨距 4×32B 整数倍时加 1 block padding | sort 非尾轴 |
| dtype 提升扩大拷贝粒度 | 尾轴字节可整除时按 B64/B32/B16 搬运 | gather_v2、index |
| 高维参数瘦身 | ≥5 维 shape/stride 走 GM tiling 结构体，寄存器只留热参数 | as_strided、pad_v3 |

## 4. host-kernel 一致性自检（最主要的工程风险）

- workspace 分段公式：host 算多少，kernel 就读多少——用**共享头文件**（`*_tiling_data.h` / `*_precision_policy.h`）定义布局，防两端漂移。
- 任何一侧的近似（如 `"+128 margin"`）都会在大 shape 下爆雷（见 pitfalls.md 坑 2）。
- 新增/删除任一 buffer，tiling 的 `CalcUBTotalSize` 与 kernel 的 `InitBuffer` 必须同步更新。

## 5. 从参考算子起步

新算子设计前，先在 `reference-ops.md` 找同类算子真实实现读一遍：
- 看它的**模板路由链**（哪些路径、SIMT 何时兜底）；
- 看它的**冲突/确定性处理**；
- 看它的**线程映射与访存形态**；
- 参考其 tiling 与 kernel 的分工，而不是直接照抄。
