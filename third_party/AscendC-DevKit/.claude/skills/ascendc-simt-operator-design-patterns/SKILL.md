---
name: ascendc-simt-operator-design-patterns
description: "AscendC SIMT 算子设计最佳实践（全流程版）。基于 13 类 400+ SIMT 算子的代码级调研，覆盖 Tiling 设计（分核/模板路由/workspace 契约）、Kernel 编程（VF/线程映射/索引地址/数据搬运/同步原子/核内共享/TensorList）、踩坑清单与开发经验、13 类算子族速查 + 391 条深度策略索引（kimi_simt_strategy.md 内嵌）。Use when: 概设/详设判定算子为 SIMT（LP2 索引间接 / LP7 选择排序 / 条件分支密集）、编写 SIMT kernel 或 tiling、解决写冲突/确定性/精度、规划线程映射与 workspace、SIMT+SIMD 混合分工、审查或调试 SIMT 算子。"
triggers:
  - SIMT 算子
  - SIMT 设计
  - SIMT kernel
  - 写冲突
  - 确定性
  - 线程映射
  - workspace 规划
  - SIMT+SIMD 混合
---

# AscendC SIMT 算子设计最佳实践（全流程版）

> 本 skill 基于 **AscendC 算子实现中 13 类 400+ SIMT 算子**的代码级调研，覆盖从 Tiling 方案到 Kernel 实现的**全流程设计决策**，每条来自真实算子的实践模式并附出处。
>
> 与已有 skill 的分工：
> - **基础切分**（核数/线程数/DCache 分配）→ `ascendc-tiling-strategy`
> - **基础语法与 API**（VF 怎么写、API 怎么调）→ `ascendc-tips`、`ascendc-dev-knowledge`
> - **本 skill** → 全流程**方案设计 + 踩坑/经验**：Tiling 决策、Kernel 编程模式、事故教训、算子族速查

## When To Use

- 设计 SIMT 算子的整体方案（tiling + kernel 架构）
- 需要 Tiling 决策：分核、模板路由、workspace 规划
- 需要 Kernel 决策：线程映射、索引/地址、数据搬运、同步/原子
- 遇到写冲突、确定性、精度对齐问题
- 审查或调试 SIMT 算子（对照踩坑清单）
- 需要一个已落地的真实算子实现作参考（查参考算子表）

不使用场景：SIMT 基础语法/API 细节请走 `ascendc-tips` 与 `ascendc-dev-knowledge`；基础核数切分走 `ascendc-tiling-strategy`。

## Reading Order

1. 先读 [references/index.md](references/index.md) 全局检索地图，按任务阶段/知识类型/常见问题定位入口。
2. 需要按算子类别逐条展开时读深度策略库 **[kimi_simt_strategy.md](kimi_simt_strategy.md)**（391 条，每条含源码与出处）。
3. 需要一页速查 + 章节索引时读 [operator-family-cheatsheet.md](references/operator-family-cheatsheet.md)。
4. 单点设计问题按索引表直接加载对应 [references/](references/) 单篇；一个子问题最多展开 5 篇。
5. 审查/调试前必读 [pitfalls.md](references/pitfalls.md)；开发前读 [dev-experience.md](references/dev-experience.md)；选参考实现读 [reference-ops.md](references/reference-ops.md)。

## Asset Map

| 资产 | 用途 |
|------|------|
| [references/index.md](references/index.md) | 全局检索地图（按阶段/知识类型/常见问题路由） |
| [kimi_simt_strategy.md](kimi_simt_strategy.md) | 深度策略库：13 类算子 391 条策略 + 3 附录，每条含源码片段与出处 |
| [references/operator-family-cheatsheet.md](references/operator-family-cheatsheet.md) | 13 类算子一页速查 + 深度策略库详细索引 |
| [references/tiling-advanced.md](references/tiling-advanced.md) | Tiling 分核策略进阶 |
| [references/template-routing.md](references/template-routing.md) | 模板路由与经验阈值 |
| [references/workspace-contract.md](references/workspace-contract.md) | Workspace 规划与 host-kernel 强契约 |
| [references/vf-programming.md](references/vf-programming.md) | VF 声明与调用规范 |
| [references/thread-mapping.md](references/thread-mapping.md) | 线程映射模式 |
| [references/index-addressing.md](references/index-addressing.md) | 索引计算与地址合成 |
| [references/data-movement.md](references/data-movement.md) | 数据搬运选型 |
| [references/synchronization.md](references/synchronization.md) | 同步与原子谱系 |
| [references/shared-memory.md](references/shared-memory.md) | 核内共享内存 |
| [references/tensorlist-handling.md](references/tensorlist-handling.md) | TensorList 动态输入 |
| [references/pitfalls.md](references/pitfalls.md) | 踩坑清单（事故记录与成因） |
| [references/dev-experience.md](references/dev-experience.md) | 开发经验（模板选择/审查清单/性能实践） |
| [references/reference-ops.md](references/reference-ops.md) | 参考算子表（13 类代表实现路径） |

---

## 设计模式分类索引

| 层 | 核心主题 | 参考文档 | 关键要点 |
|----|---------|---------|---------|
| **Tiling 设计** | 分核策略进阶 | [tiling-advanced.md](references/tiling-advanced.md) | blockDim 封顶物理核数防 507035、每核最小工作量 1024、双任务分核取 max、线程数自适应收缩、按最大工作量子循环估核、按最大单 tensor 定核 |
| | 模板路由 | [template-routing.md](references/template-routing.md) | IsCapable 优先级竞选、SIMT 大号兜底、经验阈值表（SIMT↔SIMD）、tilingKey 三代编码、索引降位 Cast |
| | Workspace 契约 | [workspace-contract.md](references/workspace-contract.md) | 16MB 系统区惯例、host-kernel 强契约（padM 复算事故）、SIMT Dynamic UB 声明（SetDynUBufSize，DCache 三档）、SetScheduleMode(1) 死锁防护、VF 间同步限制 |
| **Kernel 编程** | VF 声明与调用 | [vf-programming.md](references/vf-programming.md) | `__simt_vf__`/`__simt_callee__`、LAUNCH_BOUND 与寄存器、参数传递 3 方式、高维降参数、GM_ADDR 直接转换 |
| | 线程映射模式 | [thread-mapping.md](references/thread-mapping.md) | grid-stride 三范式、4 种线程↔数据映射、2D/3D 线程块、warp 协作、线程数分档原则 |
| | 索引与地址合成 | [index-addressing.md](references/index-addressing.md) | magic 快除、int32/int64 双轨、坐标分解链按布局选轴序、负索引回绕、越界处理、前缀和定位、bank 冲突规避 |
| | 数据搬运 | [data-movement.md](references/data-movement.md) | GM 直读 / UB 中转 / 连续侧 DMA + 离散侧 SIMT / 原子 DMA 归约 / 低比特三段式 |
| | 同步与原子 | [synchronization.md](references/synchronization.md) | SyncAll、asc_syncthreads、event 链、shuffle 原语、原子操作完整谱系 |
| | 核内共享 | [shared-memory.md](references/shared-memory.md) | TBuf VECCALC、__ubuf__ 传递、UB 私有副本、共享 buffer 生命周期复用 |
| | TensorList | [tensorlist-handling.md](references/tensorlist-handling.md) | SimtGetTensorAddr、ListTensorDesc、4 种扁平空间定位模式、scalar 三种传入 |
| **踩坑 / 经验** | 踩坑清单 | [pitfalls.md](references/pitfalls.md) | 507035、VEC_ERROR 越界、magic 溢出、假共享、死锁、两级 blockIdx 混用 |
| | 开发经验 | [dev-experience.md](references/dev-experience.md) | 模板选择启发、审查清单、性能实践、host-kernel 一致性自检 |
| | 参考算子表 | [reference-ops.md](references/reference-ops.md) | 13 类算子代表实现路径（代码调研入口） |
| **算子族速查** | 13 类算子 + 策略索引 | [operator-family-cheatsheet.md](references/operator-family-cheatsheet.md) | 每类算子一页核心决策速查 + 深度策略库详细索引（章节/策略编号/检索路径） |

---

## 核心设计决策速查

```cpp
// ============ Tiling 侧决策 ============
// 1. blockDim 封顶物理核数（SIMT 核内 grid-stride 覆盖全部元素，勿随元素数膨胀）
int64_t usedCoreNum = std::min(CeilDiv(total, coreNum), coreNum);
context->SetBlockDim(std::max(usedCoreNum, 1));

// 2. 每核最小工作量钳制（防小 shape 空转核）
int64_t perCore = std::max(CeilDiv(total, coreNum), PER_CORE_MIN /*1024*/);
context->SetBlockDim(CeilDiv(total, perCore));

// 3. 多阶段分核取 max（清零/计算两阶段并行度需求不同）
context->SetBlockDim(std::max(computeCoreNum, clearCoreNum));

// 4. 需要 SyncAll 时（多核协作）必须 batch 独占调度，防多流死锁
if (needSyncAll) { context->SetScheduleMode(1); }

// 5. workspace 16MB 系统区打底 + 算子专属区；host/kernel 分段公式必须逐段一致
currentWorkspace[0] = RESERVED_WS_SIZE /*16MB*/ + opSpecificSize;

// 6. SIMT 模板 host 必配 Dynamic Unified Buffer（= RTS SIMT 共享内存窗口；API 默认 0 = 不声明，
//    不声明则共享 buffer / DCache 越界）。SetLocalMemorySize 为同函数废弃名（主线仓 arch35 仍大量用
//    旧名，语义一致）——生成代码用 SetDynUBufSize（详见 workspace-contract §3）
if (simtMode) { context->SetDynUBufSize(Ops::Base::GetUbSize(context) - DCACHE_SIZE); }

// ============ Kernel 侧决策 ============
// 7. 写冲突策略选择：冲突低→原子逐元素；冲突高→排序段内串行+单次原子；需确定性→ownership/mask-max/两阶段
//    （详见深度策略库第八章冲突谱系 + 附录 B 确定性谱系）
// 8. SIMT 管随机 GM 读写，vector 管排序/搬运/Cast（asc_vf_call 是连接点）
CopyIn();                    // vector: DataCopyPad GM→UB
SortAndUnique(indicesUb);    // vector: AscendC::Sort + MicroAPI Squeeze
asc_vf_call<SimtCompute>(dim3{x, y}, ...);   // SIMT: 随机读写 + 段内串行归约
// 9. 精度：half/bf16 升 fp32 计算、volatile 阻止 FMA 收缩、必要时复刻 Pairwise 树
```

---

## 写冲突处理谱系速查（详见深度策略库第八章 + 附录 B）

| 档位 | 策略 | 确定性 | 适用条件 | 代表算子 |
|------|------|--------|---------|---------|
| 1 | `asc_atomic_add` 逐元素 | 否 | 冲突低、尾轴小 | scatter_add、unsorted_segment |
| 2 | UB 私有副本 + DMA 原子归约 | 否 | 直方图可入 UB | histogram full_load |
| 3 | UB 分桶多轮轮转 | 否 | 直方图大、输入密集(>bins/100) | bincount batch_load |
| 4 | 排序 + 段内串行 + 单次原子 | 段内确定 | 冲突率高（重复索引多） | scatter_add_sort、index_put |
| 5 | 行/槽位 ownership 分核 | 是 | 行归属可静态划分 | scatter_max_with_argmax |
| 6 | mask-max 全局序号胜出 | 是（last-write） | update 语义 | scatter_update |
| 7 | 跨界段 partial + 单核归并 | 是 | 排序已知、段可能跨核 | segment_sum |
| 8 | 无别名语义免原子 | 是 | indices 唯一由语义保证 | scatter_non_aliasing_add |

---

## Guardrails

- **先查后写**：写冲突 / 确定性 / 精度对齐 / 分核问题，先查深度策略库对应章节（见 cheatsheet 第二节"按设计问题索引"），不要凭直觉实现。
- **控制加载量**：一个子问题最多展开 5 篇 reference；不够就拆分子问题。
- **host-kernel 强契约**：workspace 分段公式、magic 参数、per-core 区间表、tiling struct 布局，host 与 kernel 两侧必须逐段一致——这是本体系最主要的正确性风险点。
- **SIMT host 必配 Dynamic UB**：模板走 SIMT 路径时 host tiling 必须 `context->SetDynUBufSize(usableUb)`（当前接口，默认 0 = 不声明；`SetLocalMemorySize` 为同函数废弃名，主线仓 arch35 仍用旧名，语义一致）；大小 = 平台 UB − DCache（32K/58K/128K 按算子选）− 静态预留，host 私有化决策与 device TPipe 分配用同一个数（见 [workspace-contract.md](references/workspace-contract.md) §3）。
- **参考算子只是线索**：[reference-ops.md](references/reference-ops.md) 的算子仅用于筛选真实实现来阅读，不可直接复用/照抄而不做设计判断。
- **平台语境要显式**：若某条经验来自兼容性而非 `ascend950 / arch35` 主路径，需在方案中说明。
- **review 必查清单**：提交前过一遍 [pitfalls.md](references/pitfalls.md) 与 [dev-experience.md](references/dev-experience.md) 的审查清单。
