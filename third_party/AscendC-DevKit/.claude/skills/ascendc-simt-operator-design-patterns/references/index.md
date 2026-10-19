# SIMT 算子设计知识索引

本文件是 `ascendc-simt-operator-design-patterns` 的全局检索入口，按**任务阶段、知识类型、常见问题**三个维度组织，让 agent 快速定位到正确的参考文档或深度策略库章节。

## 路由规则

- 首选入口：`kimi_simt_strategy.md`（深度展开）或 `operator-family-cheatsheet.md`（一页速查 + 章节索引）或 `index.md`（本文件）。
- 单点设计问题：直接按下方"设计模式索引"表加载对应单篇 reference，一个子问题最多展开 5 篇。
- 审查/调试前必读 `pitfalls.md`；开发前读 `dev-experience.md`；选参考实现读 `reference-ops.md`。
- 深度策略库（`kimi_simt_strategy.md`）按算子类别逐条展开，每条含源码片段与出处；检索入口见 `operator-family-cheatsheet.md` 第二节。

## By Task Stage

| 任务阶段 | 入口 |
|---------|------|
| 算子整体方案设计 | `operator-family-cheatsheet.md`（速查+索引）→ `kimi_simt_strategy.md`（对应章节） |
| Tiling 设计 | `tiling-advanced.md` + `template-routing.md` + `workspace-contract.md` |
| Kernel 实现 | `vf-programming.md` → `thread-mapping.md` → `index-addressing.md` → `data-movement.md` → `synchronization.md` → `shared-memory.md` |
| 动态输入 | `tensorlist-handling.md` |
| 写冲突 / 确定性 / 精度 | `kimi_simt_strategy.md` 第八章 + 附录 B + 附录 C；`synchronization.md` |
| 审查 | `pitfalls.md`（必读）+ `dev-experience.md`（审查清单） |
| 调试修复 | `pitfalls.md`（症状→成因） |
| 选参考实现 | `reference-ops.md` |

## 设计模式索引（单篇直达）

| 主题 | 参考文档 | 关键要点 |
|------|---------|---------|
| 分核策略 | [tiling-advanced.md](tiling-advanced.md) | blockDim 封顶、每核最小 1024、双任务分核、线程自适应收缩 |
| 模板路由 | [template-routing.md](template-routing.md) | IsCapable 竞选、SIMT 兜底、经验阈值、tilingKey 三代 |
| Workspace 契约 | [workspace-contract.md](workspace-contract.md) | 16MB 惯例、host-kernel 强契约、DCache、ScheduleMode |
| VF 编程 | [vf-programming.md](vf-programming.md) | 三层结构、LAUNCH_BOUND、参数传递、降参数 |
| 线程映射 | [thread-mapping.md](thread-mapping.md) | grid-stride 三范式、4 种映射、2D/3D 线程块 |
| 索引地址 | [index-addressing.md](index-addressing.md) | magic 快除、位宽双轨、坐标分解、负索引、bank |
| 数据搬运 | [data-movement.md](data-movement.md) | GM 直读/UB 中转/混合/原子 DMA/三段式 |
| 同步原子 | [synchronization.md](synchronization.md) | SyncAll/syncthreads/event/shuffle/原子谱系 |
| 核内共享 | [shared-memory.md](shared-memory.md) | TBuf、__ubuf__、私有副本、buffer 复用 |
| TensorList | [tensorlist-handling.md](tensorlist-handling.md) | 地址解析、4 种定位模式、scalar 传入 |
| 踩坑清单 | [pitfalls.md](pitfalls.md) | 事故记录与成因、症状→修复 |
| 开发经验 | [dev-experience.md](dev-experience.md) | 模板选择、审查清单、性能实践 |
| 参考算子表 | [reference-ops.md](reference-ops.md) | 13 类代表实现路径 |

## By Knowledge Type

- 深度策略库（按算子类别 391 条展开）：`kimi_simt_strategy.md`
- 一页速查 + 详细索引：`operator-family-cheatsheet.md`
- Tiling 设计：`tiling-advanced.md`、`template-routing.md`、`workspace-contract.md`
- Kernel 编程：`vf-programming.md`、`thread-mapping.md`、`index-addressing.md`、`data-movement.md`、`synchronization.md`、`shared-memory.md`、`tensorlist-handling.md`
- 踩坑：`pitfalls.md`
- 开发经验：`dev-experience.md`
- 参考实现：`reference-ops.md`

## Common Questions

- 我的算子该用 SIMT 还是 SIMD？→ `operator-family-cheatsheet.md` 附录 A 阈值表 + 各章 T1
- 核数怎么分？→ `tiling-advanced.md` + 深度策略库第〇章 0.3
- 写冲突怎么办？→ 深度策略库第八章 + `synchronization.md`（原子谱系）
- 要确定性结果？→ 深度策略库附录 B + 第四章 K7/K8
- 精度对不上 golden？→ 深度策略库附录 C + 第一章 K5-K7 + `data-movement.md`（三段式）
- SIMT 与 SIMD 怎么分工？→ `data-movement.md` + 深度策略库第〇章 0.4
- 算子挂了/结果错？→ `pitfalls.md`（症状→成因）
- 从哪个真实算子看起？→ `reference-ops.md`
- 审查清单？→ `dev-experience.md` + `pitfalls.md`
