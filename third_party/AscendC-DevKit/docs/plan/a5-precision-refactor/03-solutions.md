# A5 Precision Debug 问题层覆盖缺口与解决方案分析

> 层级：L3（方案分析 + 决策 + 理由；调研中演进，拍板后冻结）  
> 日期：2026-08-01  
> 依赖：  
> - `01-problems.md`（L1 事实记录）  
> - `02-analysis.md`（L3 新流程设计：双工具基线 + case-level 循环 + 6 阶段拓扑）  
> - `docs/guides/precision-debug-analysis-methods.md`（A3/A5 问题分类方法论）

---

## 1. 目标

`02-analysis.md` 完成了 A5 新流程的骨架设计，但尚未系统回答：**新流程对 A3/A5 方法论定义的六类问题覆盖如何？哪些能力缺口会影响交付？如何以最小改动补上？**

本文档对六类问题逐一做 "现状覆盖度 → 可选方案 → 推荐方案 → 实施建议" 分析，为新流程的技能设计、阶段 I/O 和开发优先级提供决策依据。

---

## 2. 覆盖度总览

| 问题层 | 确定性机械检查 | LLM 分析 | 动态定位 | 当前 A5 覆盖度 | 风险等级 |
|--------|--------------|----------|----------|----------------|----------|
| **Tiling（UB/对齐/总量/尾块）** | ❌ | ⚠️ 间接 | ❌ | **低** | 🔴 高 |
| **Kernel 计算逻辑 / API 误用 / 地址偏移** | ❌ Gate1/Gate2 | ✅ | ✅ DumpTensor | **中高** | 🟡 中 |
| **精度分类（系统/局部/随机/巨大）** | ❌ symptom 知识库 | ✅ | ✅ DumpTensor | **中** | 🟡 中 |
| **Vector error** | ✅ P1/P2/P3 guard | ✅ | ✅ P2 消融 | **高** | 🟢 低（A5 独有） |
| **op_plugin / aclnn 适配层** | ❌ plog 解析 | ✅ | ✅ 双跑交叉对比 | **中** | 🟡 中 |
| **流水同步** | ❌ sync-static-check | ❌ 无显式分析 | ❌ camodel 已删 | **零** | 🔴 高 |

> 注：当前 A5 指 `02-analysis.md` 定义的新流程（baseline → kernel_debug → vf_test / vector_error_debug → regression，条件 op_plugin_debug）。

---

## 3. 逐类问题：缺口与解决方案

### 3.1 Tiling 侧分析（UB 越界、对齐、UB 总量、尾块）

#### 3.1.1 现状与缺口

A3 有 `bounds_check` 阶段：通过 Python shadow 机械追踪每个 tensor 的地址偏移、UB 起始、长度、32B 对齐，输出可枚举的"可能越界/不对齐"清单。这是 A3 最强能力之一，能**确定性**发现 tiling 问题。

新 A5 删除 `bounds_check` 后，tiling 问题只能靠 `kernel_debug` 的 DumpTensor 间接发现：
- 如果 CopyIn 后数据就是错的，LLM 可推断"可能是 tiling 偏移错了"。
- 如果数据没错、计算也没错，但结果错在尾块，LLM 只能凭经验怀疑尾块 tile 大小。

**核心风险**：tiling 问题在 A3 中是常见根因（尤其尾块），新 A5 对此没有系统化检查，全部押注在 LLM 经验上。

#### 3.1.2 可选方案

| 方案 | 做法 | 优点 | 缺点 | 与框架影响 |
|------|------|------|------|------------|
| A. 复刻 A3 `bounds_check` Python shadow | 在 `baseline` 或新增 `tiling_check` 阶段，读取 `TilingData` / `show_op_info` / `tiling_strategy.json`，用 Python 模拟每个 tile 的 start/length/alignment 并逐 case 检查 | 与 A3 能力对齐，确定性强 | 需要维护 A3 的 shadow 库；与 A5 新结构耦合 | 大：需新增阶段或合并进 baseline |
| B. 在 `kernel_debug` 中调用轻量 `tiling_bounds_check` 工具 | 不独立阶段，作为 kernel_debug 分析步骤的辅助脚本，输入当前 case 的 shape 和 tiling 参数，输出"可疑偏移/对齐"提示 | 改动小，不增加阶段 | 只能检查当前 case，不能全量枚举；逻辑上不如 A 完整 | 小：作为 skill 内部工具 |
| C. 强化 DumpTensor 阶段编号，让 LLM 更容易从中间态推断 tiling 错误 | 例如把 CopyIn 的 desc 再细分（110/120/130... 分别对应不同 tensor 的搬入），让 LLM 一眼看出"哪个 tensor 的 tile 数据异常" | 完全 skill 内，零框架改动 | 仍依赖 LLM 经验，没有机械兜底 | 极小 |

#### 3.1.3 推荐方案

**短期：B + C**
- **B** 作为 `kernel_debug` skill 内部的第一步："调用 `tiling_bounds_check` 脚本，对当前 case 的 tiling 参数做边界/对齐/尾块扫描，输出可疑项"。
- **C** 同步优化 DumpTensor 编号规范，让 CopyIn 阶段能区分不同 tensor 的 tile 数据，便于人工/LLM 复核。

**长期**：评估 A3 的 Python shadow 库能否被 A5 复用（抽象为通用 tiling 校验模块），再决定是否升级为独立阶段 `tiling_check`。

> **决策理由**：当前批次目标是最小可行闭环。B 能在不新增阶段、不引入 A3 大模块的前提下，给 kernel_debug 增加确定性输入；C 提升可诊断性。A 的工程量过大，应作为后续独立 PR 评估。

---

### 3.2 Kernel 计算逻辑 / API 误用 / 地址偏移 / 同步缺失

#### 3.2.1 现状与缺口

A3 的 `diagnose` 阶段有两层机械检查：
- **Gate1**：症状关键词匹配（symptom-table / common-traps / case-studies），快速映射历史经验。
- **Gate2**：调用 `ascendc-sync-static-check` 扫描同步缺陷（EnQue/DeQue 配对、SetFlag/WaitFlag、MTE2/MTE3 地址重叠、PipeBarrier、Mutex、Scalar 流水、TBuf 无同步）。

新 A5 删除 `diagnose` 后，这些能力消失。kernel_debug 依靠 LLM 读 DumpTensor 结果从头分析，没有历史知识库复用，也没有同步缺陷的系统性扫描。

**核心风险**：
1. 同步缺失是 kernel 精度/崩溃的常见根因；A3 靠 Gate2 能一次性扫描，A5 只能靠 DumpTensor 间接发现（数据搬入后是垃圾 → 可能同步缺失）。
2. 历史经验（common-traps / case-studies）无法复用，每个算子都重新踩坑。

> 但也有优势：A5 的 DumpTensor 比 A3 的 `printf` 二分更强（看完整 tensor 而非单个标量）；A5 的 `vector_error_debug` 比 A3 的 `comment_bisect` 更强（P1/P2/P3 guard 方法论）。

#### 3.2.2 可选方案

| 方案 | 做法 | 优点 | 缺点 | 与框架影响 |
|------|------|------|------|------------|
| A. 在 `kernel_debug` 中恢复 Gate1 知识库匹配 | 把 A3 diagnose 的 symptom-table / common-traps / case-studies 迁移为 A5 `kernel_debug` skill 的 `references/` 资源，分析前先查表 | 复用历史经验，降低 LLM  hallucination | 需要维护 A5 专属知识库；A3 知识库不一定直接适用于 A5 RegBase | 中：skill 资源目录新增 references |
| B. 在 `kernel_debug` 中调用 `ascendc-sync-static-check` | 分析失败模式前，先对当前 kernel 代码跑 sync-static-check，输出结构化同步缺陷清单 | 填补最大同步缺口；现成 skill 直接调用 | 只能扫描静态代码，不能覆盖运行态数据竞争；可能误报 | 小：skill 内部增加一步 |
| C. 保留 LLM 主导分析，仅补充 DumpTensor 编号规范 | 不引入机械检查，只靠 DumpTensor 和 LLM 推理 | 改动最小 | 同步问题无兜底，历史经验不复用 | 极小 |
| D. 复刻 A3 的 `fix` candidate_pool + A/B 验证 | 在 kernel_debug 内建候选修复池，每个候选修改后跑 KernelLaunch 对比，通过才 commit | 系统性强，减少反复 spawn | 需要修改 skill 输出 schema，增加框架负担 | 大：涉及阶段内状态机 |

#### 3.2.3 推荐方案

**短期：B + A（部分）**
- **B 必须做**：在 `kernel_debug` skill 任务清单中增加一步："对当前 kernel 代码调用 `ascendc-sync-static-check`，把输出同步缺陷清单作为分析输入"。这是填补当前最大缺口的最小改动。
- **A 选做**：先迁移 A3 的 `symptom-table` 和 `common-traps` 中**与 A5 RegBase 相关**的部分到 `kernel_debug/references/`。不追求完整 A3 知识库，只迁移高频、高置信陷阱。

**长期**：如果 A5 问题库积累足够，可发展为 A5 自己的 Gate1 知识库；如果 A/B 验证能显著减少 spawn 次数，再评估是否引入 D。

> **决策理由**：同步缺失是 A5 当前流程中完全没有覆盖的高风险点，而 `ascendc-sync-static-check` 是现成 skill，只需在 `kernel_debug` SKILL.md 中调用，性价比最高。Gate1 知识库是"锦上添花"，不应阻塞当前重构。

---

### 3.3 精度分类分析（系统误差 / 局部误差 / 随机误差 / 巨大误差 / dtype 特定）

#### 3.3.1 现状与缺口

A3 的 `diagnose` 阶段对输出误差做分类：
- 系统误差（所有点都偏）→ 常见根因：公式错、系数错、dtype 转换。
- 局部误差（热点）→ 常见根因：边界/尾块处理错、mask 错。
- 随机误差 → 常见根因：未初始化、OOB、数据竞争。
- 巨大误差 / Inf / NaN → 常见根因：除零、exp 溢出、同步缺失。

A3 通过 Gate1 的症状关键词匹配把这些分类直接关联到历史陷阱。新 A5 没有这层映射，LLM 只能自己从 `max_diff` 和 `diff_sign` 推断。

#### 3.3.2 可选方案

| 方案 | 做法 | 优点 | 缺点 | 与框架影响 |
|------|------|------|------|------------|
| A. 在 `kernel_debug` 中增加"误差分类"预处理步骤 | 从 KernelLaunch 结果计算 `max_diff` / `mean_diff` / `diff_sign` / `hotspot_ratio`，按规则分类后写入 result JSON，并提示 LLM 可能根因 | 给 LLM 明确信号，减少幻觉 | 规则需要维护；只是提示，不强制 | 小：skill 内部脚本 |
| B. 复用 A3 diagnose 的 symptom-table 做分类→陷阱映射 | 同 3.2 方案 A | 历史经验复用 | 需要维护 | 中 |
| C. 不额外处理，由 LLM 自主判断 | 零改动 | 简单 | 依赖 LLM 经验，稳定性差 | 无 |

#### 3.3.3 推荐方案

**A 必须做，B 选做**。

`kernel_debug` 的 skill 输出 `dump_evidence` 应包含结构化误差分类字段：
```json
{
  "error_pattern": "systematic | localized | random | huge | dtype_specific",
  "max_diff": 1.2e-4,
  "mean_diff": 3.4e-6,
  "hotspot_ratio": 0.02,
  "diff_sign": "positive"
}
```
并让 LLM 在分析前先读这些字段。这能让 DumpTensor 的二分更有方向（例如 `localized` 直接定位热点 tile；`huge` 先看 Inf/NaN）。

---

### 3.4 Vector error（A5 独有优势）

#### 3.4.1 现状

`vector_error_debug` 已完整覆盖：P1 静态扫描 → P2 受控实验 → P3 修复 guard。这是 A5 相比 A3 的独有优势，不需要补缺口。

#### 3.4.2 仅建议：持续归档

每次 `vector_error_debug` 定位到的根因应写入 `vf_lesson.md` 或 `vector_error_lessons.md`，作为 A5 的专属知识库。这与 3.2 的 Gate1 知识库可共用同一个 `references/` 目录。

---

### 3.5 op_plugin / aclnn 适配层问题

#### 3.5.1 现状与缺口

A5 新流程通过"双跑交叉对比"自动隔离适配层问题：
- KernelLaunch 通过 = kernel 层没问题。
- run-cases 失败 = 问题在 op_plugin / aclnn 层。

这是 A3 没有的自动隔离能力。但 `op_plugin_debug` 的定位手段目前只依赖 LLM 读 op_plugin 代码和对比参数差异，**没有系统化的错误码解析和 plog 分析**。

A3 的 `scope_guard` 阶段在遇到上游缺陷时会调用 `ascendc-runtime-debug`（错误码解码 + plog 解析 + 注册/签名检查），然后直接 halt。A5 不 halt，而是尝试修复，但缺少同样的错误码解码能力。

#### 3.5.2 可选方案

| 方案 | 做法 | 优点 | 缺点 | 与框架影响 |
|------|------|------|------|------------|
| A. 在 `op_plugin_debug` 中调用 `ascendc-runtime-debug` | 把 run-cases 的 plog / 错误码输入 runtime-debug，输出结构化上游错误信息（错误码、注册失败、签名不匹配、tiling 参数类型错误） | 与 A3 上游诊断能力对齐；确定性高 | 需要解析 plog 路径；runtime-debug 可能假设 A3 环境 | 中：skill 调用另一个 skill 或读其 references |
| B. 在 `op_plugin_debug` 中只读错误码表，不做 plog 解析 | 把 `ascendc-runtime-debug` 的**错误码表和检查清单**作为 references，LLM 按表逐项排查 | 不依赖 plog 解析工具；改动小 | 仍是 LLM 主导，不如 A 自动化 | 小：skill 增加 references |
| C. 维持现状，全靠 LLM 读代码 | 零改动 | 简单 | 对注册/签名/tiling 类型问题诊断效率低 | 无 |

#### 3.5.3 推荐方案

**B 必须做，A 作为后续增强**。

- 在 `op_plugin_debug` 的 `references/` 中放入 `runtime-error-code-table.md` 和 `op_plugin-checklist.md`（检查项：注册宏、aclnn 接口签名、dtype 转换、shape reshape、attr 传递、tiling 参数映射）。
- skill 任务清单增加："先按错误码表解码 run-cases 的错误码，再按 op_plugin-checklist 逐项排查，最后才自由读代码"。

A 需要验证 `ascendc-runtime-debug` 是否能在 A5 环境正确解析 plog，可作为后续 PR 单独评估。

> **决策理由**：A5 的 op_plugin_debug 是"修复导向"而非"halt 导向"，必须能稳定定位问题。错误码表和检查清单是成本最低、最稳定的输入；plog 自动解析是增强项，不应阻塞当前重构。

---

### 3.6 流水同步问题（Pipeline sync）

#### 3.6.1 现状与缺口

旧 A5 有 `pipeline_sync` 阶段：关闭 double buffer → KernelLaunch 上板 → camodel 仿真 + 简化 trace 分析（MTE2/VF/MTE3 数量与时序约束）。

新 A5 删除 `pipeline_sync` 的决策依据是：
1. KernelLaunch 不再做 dynamic compile，camodel 仿真已从 KernelLaunch 移除。
2. 用户定调删除 double buffer 切换逻辑，全程使用原始 buffer 配置。

因此 `pipeline_sync` 没有存在基础。但删除后，**流水同步问题在新 A5 流程中完全没有系统化检测手段**。

#### 3.6.2 可选方案

| 方案 | 做法 | 优点 | 缺点 | 与框架影响 |
|------|------|------|------|------------|
| A. 以静态检查替代动态 camodel | 在 `kernel_debug` 中调用 `ascendc-sync-static-check`（同 3.2 B），覆盖 EnQue/DeQue、SetFlag/WaitFlag、PipeBarrier、地址重叠等 | 不依赖 camodel；现成 skill | 只能扫描代码，不能验证运行时序 | 小 |
| B. 用 DumpTensor 间接诊断同步缺失 | 规范 DumpTensor 在 CopyIn/Compute/CopyOut 的插入点，让 LLM 从"搬入后数据错"推断同步缺失 | 零新增工具 | 不确定性强，需要 LLM 经验 | 极小 |
| C. 恢复轻量 `pipeline_sync`（不依赖 camodel） | 阶段只做：关闭 double buffer → KernelLaunch 上板 → 如果 crash 或结果错再转 vector_error_debug / kernel_debug | 保留一个专门阶段处理 buffer 模式问题 | 与用户定调冲突；用户明确要删 double buffer 切换 | 大 |
| D. 不处理，接受缺口 | 零改动 | 最简单 | 流水同步问题无兜底 | 无 |

#### 3.6.3 推荐方案

**A + B**。

- **A 是核心**：`ascendc-sync-static-check` 能覆盖大部分常见同步缺陷（EnQue/DeQue 不匹配、手动 SetFlag/WaitFlag 问题、PipeBarrier、MTE2/MTE3 地址重叠、TBuf 无同步）。这是 camodel 删除后最合理的替代方案。
- **B 作为辅助**：DumpTensor 的 CopyIn 阶段数据异常是同步缺失的典型症状，规范 desc 编号让 LLM 能快速识别。

**C 不采纳**：与用户定调冲突。用户明确删除 double buffer 切换和 pipeline_sync，不应恢复。

> **决策理由**：同步问题不能完全没有兜底。`ascendc-sync-static-check` 不依赖 camodel，也不涉及 double buffer 切换，完全符合用户约束。把它作为 `kernel_debug` 的固定前置步骤，是最小可行方案。

---

## 4. 综合推荐方案与优先级

### 4.1 推荐方案汇总

| 问题层 | 推荐方案 | 改动位置 | 当前批次优先级 |
|--------|----------|----------|----------------|
| **Tiling** | B（轻量 `tiling_bounds_check` 脚本）+ C（DumpTensor 编号细化） | `kernel_debug` skill | 🟡 P1（与 kernel_debug 同步实现） |
| **Kernel 计算 / 同步** | B（调用 `ascendc-sync-static-check`）+ A 部分（迁移高频 trap 表） | `kernel_debug` skill | 🔴 P0（最大缺口） |
| **精度分类** | A（误差分类字段） | `kernel_debug` result schema + skill | 🟡 P1 |
| **Vector error** | 持续归档 lesson | `vector_error_debug` skill | 🟢 P2（已有能力） |
| **op_plugin** | B（错误码表 + 检查清单） | `op_plugin_debug` references/skill | 🟡 P1 |
| **流水同步** | A（调用 `ascendc-sync-static-check`）+ B（DumpTensor 推断） | `kernel_debug` skill | 🔴 P0（与 kernel 计算同步） |

### 4.2 实施顺序建议

1. **P0**：修改 `kernel_debug` skill，在任务清单最前面增加两步：
   - 调用 `ascendc-sync-static-check` 扫描同步缺陷。
   - 对当前 case 调用轻量 `tiling_bounds_check` 脚本扫描边界/对齐/尾块。
2. **P1**：
   - 为 `kernel_debug` 增加结构化误差分类字段（`error_pattern` 等）。
   - 为 `op_plugin_debug` 增加错误码表和检查清单 references。
   - 细化 DumpTensor desc 编号规范（区分 CopyIn 的不同 tensor）。
3. **P2**：
   - 评估是否从 A3 迁移完整 Gate1 知识库。
   - 评估是否复刻 A3 Python shadow tiling 检查。
   - 评估 `op_plugin_debug` 是否接入 `ascendc-runtime-debug` 做 plog 自动解析。

### 4.3 关键决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | **不新增独立阶段**（如 `tiling_check` / `sync_check`），把这些能力作为 `kernel_debug` 内部的前置步骤 | 保持 6 阶段拓扑简洁；这些检查是 per-case 的，与 kernel_debug 同一调用上下文 |
| 2 | **优先复用现成 skill**（`ascendc-sync-static-check`）而不是重新写检查工具 | 符合 §1.2 可维护/可扩展原则；避免重复造轮子 |
| 3 | **不恢复 `pipeline_sync` 或 camodel 依赖** | 尊重用户定调；用静态检查替代动态 trace 是可行退路 |
| 4 | **知识库（Gate1）采用渐进迁移**，先只迁移高频 A5 RegBase 相关陷阱 | 避免一次性搬运 A3 大库导致质量不可控；后续逐步积累 lesson |
| 5 | **`op_plugin_debug` 先给检查清单，后给 plog 自动解析** | 检查清单成本低、稳定；plog 解析依赖外部工具，单独评估 |

---

## 5. 风险与保留项

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 静态 sync check 不能覆盖运行时数据竞争 | 某些同步问题只能通过上板行为复现 | 保留 DumpTensor 阶段编号规范，让 LLM 能从中间态推断；必要时在后续迭代评估动态检测 |
| 轻量 `tiling_bounds_check` 不如 A3 Python shadow 完整 | 复杂 tiling 问题仍可能漏检 | 明确记录为"轻量检查"；后续评估是否升级为完整 shadow |
| 没有 Gate1 知识库时 LLM 对罕见问题分析不稳定 | 修复成功率低于 A3 | 高频陷阱先迁移；每次定位到的根因写入 lesson 文件 |
| `op_plugin_debug` 缺少 plog 解析，对注册/签名问题效率低 | 适配层修复时间变长 | 先通过错误码表和检查清单覆盖 80% 常见情况；plog 自动解析后续增强 |

---

## 6. 关联改动清单

完成本文档推荐方案后，需要同步更新以下文件：

- `docs/stages/precision-debug-a5.md`：在 kernel_debug 阶段描述中增加 sync check 和 tiling check 步骤。
- `docs/plan/a5-precision-refactor/02-analysis.md`：
  - 在 `kernel_debug` 任务清单中增加 `ascendc-sync-static-check` 和 `tiling_bounds_check`。
  - 在 `op_plugin_debug` 任务清单中增加错误码表/检查清单。
  - 更新 `kernel_debug` result schema 增加 `error_pattern` 等字段。
- `.claude/skills/ascendc-precision-kernel-debug/SKILL.md`：增加调用 `ascendc-sync-static-check` 和 `tiling_bounds_check` 的步骤。
- `.claude/skills/ascendc-precision-op-plugin-debug/SKILL.md`：增加错误码表和检查清单 references。
- `docs/guides/precision-debug-analysis-methods.md`：更新 A5 流程对六类问题的覆盖说明。

---

## 7. 下一步

待用户确认 §4 的优先级和决策后，进入 L4 实施方案：
1. 更新 `02-analysis.md` 中 `kernel_debug` / `op_plugin_debug` 的任务清单和 schema。
2. 开始 PR-1：拆分 `precision_debug_a5.py` 为 per-phase 子包，并在新 `kernel_debug` 阶段中预留 sync check / tiling check 调用点。
3. 同步补充 UT：验证 `resolve_condition()` 和 `transition()` 在新增字段存在时正确路由。

