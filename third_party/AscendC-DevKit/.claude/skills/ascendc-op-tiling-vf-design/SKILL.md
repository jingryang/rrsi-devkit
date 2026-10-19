---
name: ascendc-op-tiling-vf-design
description: 对单个算子计算模板执行 A5 RegBase VF 编排选型（VF 数量、依赖关系、编排模式 + per-VF 函数接口）
triggers:
  - vf-design
  - VF 设计
  - VF 编排设计
---

# AscendC 算子 A5 VF 编排设计

## 适用条件

本 skill 用于 **A5 Regbase** 算子计算模板的 VF（Vector Function）编排设计。

- **A5 Regbase**：适用。
- **覆盖范围**：SIMD 类 VF 编排（elementwise / reduce / norm 等连续计算，单/多 VF、有/无依赖）。
- **不覆盖**：gather/scatter/条件分支密集的 SIMT 场景——其 VF 编排不在本 skill 范围。

## 职责

对单个算子计算模板，基于公式/golden 展开、聚合边界分析、变量依赖追踪，确定 VF 数量、VF 间依赖关系，经决策树选定编排模式（1-5 号模式），并为每个 VF 产出完整的函数接口定义（签名 + 参数表 + 伪代码）。

**职责边界**：本 skill 是 VF 编排的**决策层**——决定"划几个 VF、按什么顺序编排、边界在哪里"。上游 `ascendc-op-general-design` 已给出计算结构（`loop_framework`）与公式（`gradient_formula`）；下游 `ascendc-op-tiling-buffer-kernel`（A5 路径）消费本 skill 的编排结果，只做寄存器级定量核算（RegTensor 计数、MicroAPI 910D 查证、Cast 布局红线），不做 C1-C9 编排重决策（唯一例外：`handoff_notes.register_risk` 超阈时按 REG-2 做补救性 UB 中转/再拆，属定量落地而非编排重决策）。

## 流水线位置

```
tiling-split（切分方案 + loopCount）→ 【本 skill：VF 编排选型】→ tiling-buffer-kernel（寄存器定量 + VF_CALL 呈现）→ tiling-precision-perf
```

## 与其他 Skill 的关系

| Skill | 关系 |
|------|------|
| `ascendc-op-general-design` | 上游：`general_design.json` 提供 `loop_framework`（计算结构）与 `gradient_formula`（公式），本 skill 据此展开 VF 编排 |
| `ascendc-op-req-analysis` | 上游：`requirement.json` 的 `op_spec` 提供算子接口，`design_doc_path` 指向含 golden 的需求文档 |
| `ascendc-op-tiling-split` | 上游：`tiling_current_template.json` 的 `split` 段提供 loopCount、ubFactor、常驻数据 |
| `ascendc-op-tiling-buffer-kernel` | 下游：A5 路径消费本 skill 的 VF 编排结果（`vf_design`），做寄存器定量核算，不重新划分 VF |

## 输入

从当前工作目录读取上游产物文件：

- `requirement.json`：算子规格（`op_spec`：inputs/outputs/attrs + `design_doc_path` 指向含公式/golden 的需求文档）——公式与 golden 来源。
- `general_design.json`：概设产物（`loop_framework` 给计算结构、`gradient_formula` 给公式）。
- `template_division.json`：模板范围与锁定决策。
- `tiling_current_template.json`：当前模板已完成段（至少含 `split`：loopCount、ubFactor、常驻数据清单）。
- `hw_params.json`：硬件参数（UB 容量等，用于 UB 超限估算）。
- `cases.yaml`（如存在）：用例 shape 分布（含归约轴极值），供步骤 0 模板维度外推。
- 当前模板与算子身份已在 prompt 提供。

> 不读其它模板或其它设计步骤写出的中间文件。

## 输出（用 Bash（`cat`）写到当前工作目录）

| 产物 | 必需 | required_keys | schema |
|---|---|---|---|
| `tiling_vf_design.json` | 是 | `template, vf_design` | `schema/tiling_vf_design.json`（本 skill 同目录，可按需 Read 确认字段结构） |

> 契约的机器校验来源：`schema/tiling_vf_design.json`（JSON，含 required_keys + example）。
> 产出不符合 schema → DevKit 适配层拒绝，重试。

**VF 设计必须包含每个 VF 的函数接口定义**（函数签名 + 参数表 + 伪代码），放在 `vf_design.vfs[]` 每个条目内，格式对标 AscendC RegBase `__aicore__ inline void ComputeXxx(...)` 风格。所有 VF 函数均为本算子新增，自包含定义，不引用外部算子 helper。

## 执行步骤

### 0. 校验上游并提取计算结构

- 读取 `tiling_current_template.json` 的 `split` 段（split 已由流水线先于本步完成，无需检查 status）：加载 loopCount、ubFactor、常驻数据清单供参考。
- 读取 `general_design.json`：从 `loop_framework` 提取计算结构、从 `gradient_formula` 提取公式，作为 VF 编排的输入（公式/golden 优先级：`gradient_formula` → `requirement.json` 的 `design_doc_path` 指向的需求文档内联 golden 段）。
- 读取 `requirement.json` 的 `op_spec`：确认输入/输出张量与属性，供 VF 接口的端口命名与 dtype 对齐。

**模板维度外推（强制检查，防多模板盲区）**：golden/desc 是数学语义，**无法感知多模板**——模板分派阈值（如"整行驻留 vs 行切分重算"）来自硬件容量定量，属 tiling 层信息；上游模板划分缺失时必须外推，禁止默认单模板全称结论。

> 1. **上游优先**：`tiling_current_template.json` 的 `split` 段 / `template_division.json` 已给出模板划分（行全载/行切分等）时，以其结论为准，本步骤只核对登记；
> 2. **强制外推**（上游缺失时）：从 `requirement.json` op_spec 的 shape_support 与 `cases.yaml`（如存在）提取**归约轴 D 的 min/max**；结合 `hw_params.json`（UB 容量、VReg 宽度 → VL=VReg/4B）核算**整行驻留阈值**：`D_align_max × dtype 字节 × 双缓冲 + gamma 等常驻 + 折叠暂存 vs UB 可用容量`，并核对 `D_max vs VL²×4`（折叠归约两级全覆盖上限口径）；
> 3. **超阈强制分模板**：`D_max` 超过整行驻留容量或 `> VL²×4` 时，**强制产出第二个模板分支——行切分重算支**（归约段扫描 x 产部分和 → finalize → 应用段**重读 x** 应用统计量）：该支 data_flow 画成二段式（统计扫描→重读应用），`handoff_notes` 标注 x 双读带宽代价；未超阈则登记"单模板（行全载）结论：D_max={X} ≤ 阈值 {T}"（允许下游 tiling 修正）；
> 4. **产物衔接**：外推结论（阈值、判据、分支）登记进 decisions；vf_count 条件化分支须与外推出的模板分支一一对应（沿用 vf_count 条件化条款的模板维度标注要求）。

### 1. 分析公式 → 选模式

**核心问题**：golden 代码里有几个计算阶段？阶段之间有数据依赖吗？

**方法（4 步）**：

```
① 展开 golden → 操作序列
       │
② 按 C1-C9 规则画切分线 → 得到 VF 数
       │
③ 追踪变量流向 → 得到依赖关系
       │
④ loopCount + VF 数 + 依赖 → 决策树 → 模式 1-5
```

---

**① 展开 golden 代码为操作序列**

把 golden 代码按执行顺序展开为原子操作，**每个原子操作标注其在 golden 源文件中的行号锚点**（如 `L57`），供切分判据逐条引用与事后对质。公式本身给数学关系，golden 给实际计算过程。**简单公式（ReLU / Swish / GeLU）只有 1 步——只有一个 `__VEC_SCOPE__`。**

```
RmsNorm 展开:
  操作 A: x² → reduce → mean_sq     [golden L10]
  操作 B: rsqrt(mean_sq + ε) → rstd [golden L11]
  操作 C: x * rstd * γ → y          [golden L12]
```

**② 在切分边界画线（规则判定表）**

> **固定前提（A5 Regbase 数据流模型）**：本 skill 仅适用 A5 Regbase——中间结果（含聚合统计量）**驻留寄存器、不占 UB**，聚合结果可与紧随消费共存于同一 VF，因此**"聚合边界 = 切分线"不成立**，切分/拆分只由下方规则 C1-C9 决定（C5 为平局裁定；C6 为**弱默认拆分型**——统计量是输出时物化点默认成切分线，可显式豁免；C7 为多级归约链分段默认，含单遍归约豁免；C8 为实现约束型段边界；C9 为跨核归约终段成 VF）。
>
> 背景（防退化）：Membase 类平台（如 A3）中间结果须落 UB，聚合边界天然是切分线——本 skill 的融合结论（C1 等）不可外推到该类平台；也不要反过来把"见聚合就切"的 membase 习惯带回 A5。

**切分规则（结构化判定表，按序执行；每条切分/合并决策须引用规则编号 + golden 行号锚点；后判规则的拆分决定覆盖先判规则的融合结论——如 C1 融合成立的链仍可被 C6 在物化点拆分）**：

| 规则 | 判据 | 动作 |
|------|------|------|
| **C1（同轴消费融合）** | 聚合点与其紧随的广播消费：**统计轴相同、同一遍历轮次内** | 合入同一 VF（统计量驻留寄存器，见固定前提） |
| **C2（跨轴必切）** | 两个计算段的**统计轴不同**（如 row dim=-1 vs col dim=-2） | 必须分属不同 VF |
| **C3（跨遍历不同语义必切）** | 两段操作序列不同且分属**不同遍历轮次**（如首轮 softmax 段 vs 后续归一段） | 必须分属不同 VF |
| **C4（控制流等价才可融合）** | 相同循环次数/嵌套、无（或**相同**）条件分支？ | 不等价 → 禁止合并（引用 `a5_regbase_design.md` 规则 VF-2） |
| **C5（融合收益归零 → 模块化拆分）** | C1 融合对需**二次遍历**（首轮产统计量+中间量、次轮应用统计量），且中间量跨遍驻留需求 ≥ 寄存器文件容量（32 RegTensor × 256B = 8KB，粗估口径，含等号——占满后其余活跃量无寄存器可用）或融合链活跃 RegTensor 粗估 > 32 | **性能平局 → 默认在聚合边界拆分**（产统计量段 / 应用统计量段各自成 VF），模块化优先；引用 C5 + 容量判定记录 tie-break（判据见下方说明） |
| **C6（独立输出物化点，弱默认拆分）** | 聚合派生统计量/中间量**本身是算子输出**（写入 `requirement.json` 的 outputs，如 rstd/scale/mean 输出给下游算子消费） | **默认在物化点拆分**——该值反正必须中途物化（经 UB 写出 GM），拆/融代价相等 → 性能平局，模块化优先。可显式豁免保持融合（豁免条件见下方说明）；切分型规则已在该处切分时边界重合、无需重复拆；无论拆合均须在 `handoff_notes` 记录物化点（见下方说明） |
| **C7（多遍历归约链按统计阶段分段）** | 同时满足：①C6 判据成立（统计量是算子输出）；②golden 存在**串行依赖的多级归约**（第二级归约吃第一级结果，如 `Var = Σ(x−Mean)²/r`），或归约段与应用段需**重复遍历 x**（单遍归约豁免见下方说明） | **默认按统计阶段在物化点分段**：每级归约（Mean/Var 段）、应用归一化（Y 段）各自成 VF；统计量 finalize 段（Rstd 标量派生）默认独立成 VF（finalize 独立性判据见下方说明）；单次归约且 x 不重读（rms_norm 形态）不触发 |
| **C8（实现约束段边界）** | 计算链中必须调用高级 API（`ReduceSum`/`Sort32`/`Gather` 等**不可内联进自定义 `__VEC_SCOPE__`** 的库调用），或归约采用折叠/二分实现（VL 对齐约束使其无法与前后逐元素段共 scope）。**前置默认**：当 golden/desc 展开需要 reduce/max/sum/softmax 类归约且目标为 A5 RegBase 时，默认先假设归约不可内联；只有明确证据表明单遍可内联进自定义 `__VEC_SCOPE__` 时才保持融合，否则按 C8 拆并写条件表达式 | **高级 API 调用点 / 折叠对齐点构成天然段边界**：其前后的自定义 `__VEC_SCOPE__` 各自成 VF（如 softmax 折叠求和段与归一化段分离）；引用 C8 + golden 行号锚点，并注明具体约束（哪个 API / 哪种对齐 / 为何不能证明可内联） |
| **C9（跨核归约终段独立成 VF）** | split 段核间切分轴与统计轴相同（单核只产部分统计量，如 foreach 类多核归约），须 GM workspace + SyncAll 后做跨核最终归约 | 跨核 finalize 段**计为独立 VF**（串行依赖链的一环，vf_count +1，回决策树重取模式），不再仅作 handoff 标注；核内局部归约段与跨核 finalize 段分属两个 VF |

> **C5 平局裁定（融合收益归零时模块化拆分——确定性默认，不触发提问）**：
> **平局论证（C5/C6/C7 共用）**：C1 融合的收益 = 省掉中间量的 UB 往返。当中间量反正要落 UB 时（C5：二次遍历且驻留 ≥8KB 放不下寄存器；C6：本身是输出须物化；C7：多级归约须重复遍历 x），融合与拆分的访存流量相等；同 V 引擎按序执行 + 统计量依赖屏障使两者均无流水重叠差异 → **性能平局 → 模块化优先拆**（单 VF 寄存器压力可控、独立变化轴各自演化、段级可独立单测复用）。
>
> C5 约束：
> 1. 拆分决策引用 **C5 + golden 行号锚点**，并记录容量判定依据（中间量驻留字节数 / 活跃 vreg 粗估 vs 8KB / 32 上限）——**平局必须由容量判据坐实**，"评估不出差异就拆"式裸描述不合格
> 2. 驻留前提不变：统计量本身仍驻留寄存器，经 UB 中转的是行/中间量
> 3. 无二次遍历、或中间量驻留 < 8KB 且活跃 vreg ≤ 32 时，C1 融合收益 > 0，**不触发 C5**（保持融合，防止退回"见聚合就切"的旧行为）
> 4. C5 只在聚合边界拆分，不引入 C2-C4 之外的新边界；VF 数变化后回决策树重取模式

> **C6 独立输出物化点（弱默认拆分型规则）**：
> 动因是**输出契约**：统计量/中间量本身是算子输出（`requirement.json` outputs，如 rstd/scale——下游算子必须拿到它）→ 该值反正必须中途物化到 UB 并写出 GM → 物化点处拆/融代价相等（平局论证见 C5 块）→ **默认在物化点拆分**（另获精度派生段独立演进、多 dtype 解耦的工程收益）。
> - **豁免（保持融合）**须同时满足：① 融合后单 VF `op_count` ≤10（8-10 须标注 `chain_length_risk`）；② 活跃 RegTensor 粗估 <20；并在 rationale 写明豁免理由 + C6 + 行号锚点（裸"融合更优"不合格）。容量门槛仅用于豁免判定，C6 的拆分动因是物化平局而非寄存器压力（与「寄存器压力不是拆 VF 的理由」条款不冲突）。
> - **边界重合**：切分型规则（C2-C5、C7、C8）已在物化点切分时无需重复拆，引用编号取实际触发者。
> - **产物义务**：凡触发 C6，`handoff_notes` 必须记录物化点清单（输出名、锚点、是否与切分线重合、宽度），引用 C6 + 行号锚点；裸遗漏 = 自检不合格。

> **C7 多遍历归约链按统计阶段分段（切分型默认规则；动因 = C6 物化点平局 + 多级归约的结构复杂度）**：
> - **触发两条件（须同时满足，缺一不触发）**：① **C6 判据成立**（统计量/中间量是算子输出，无论 C6 最终拆分还是豁免）；② **串行依赖的多级归约**——第二级归约的输入含第一级结果（`Var = Σ(x−Mean)²/r`），或归约段与应用段需重复遍历 x。**单遍归约豁免**：同一遍历内同算 Σx 与 Σx²（矩法 `Var=E[x²]−E[x]²` / Welford）→ 归约级数折叠，条件②不成立，退回 C6 两段拆，判定时须引用 golden 中双累加器同遍历的行号锚点。单次归约且 x 驻留不重读（rms_norm 形态）不触发，防止退回"见聚合就切"。
> - **分段方式**：沿物化点按统计阶段切——每级归约各自成 VF（Mean/Var 段）、应用归一化自成 VF（Y 段）、**统计量 finalize 段（Rstd 标量派生）默认独立成 VF**（判据见下方独立性专块），段间统计量经 UB 交接（与物化写出共用一次 StoreAlign）。
> - **与 C5/C6 的关系**：C6 弱默认拆 → C7 细分到统计阶段；C5 看容量（≥8KB）、C7 看结构（多级归约链 + 输出物化），判据独立、先 C5 后 C7，边界重合时引用实际触发者。
> - **产物义务**：rationale 引用 C7 + golden 行号锚点，写明哪两级归约串行依赖 / 哪些物化点（核对过单遍豁免须写明依据）；handoff_notes 物化点条目 `coincides_with_split` 置 `true`。

> **统计量 finalize 段独立性判据（C6/C7/C8 分段后的组成规则）**：
> - **默认独立**：对部分和做最终归约/合并（批量 LevelMerge 类）或从统计量派生标量（rstd/scale 类）的 finalize 段——含 Sqrt/Div/rsqrt 等超越函数、Newton-Raphson 等迭代求精、多级部分和合并——**默认独立成 VF**。动因模板化登记：①超越函数/迭代求精的实现策略是独立演化轴（性能/精度动机，从 golden 数学语义不可见——同一公式按直解与按迭代求精是两种指令序列，需独立演进与独立验证）；②行切分重算支下 finalize 须等全量部分和齐备（天然依赖屏障，并入任一段均破坏该结构）；③跨算子公共件复用的工程组织惯例。
> - **并入豁免（三条件须同时成立，缺一保持独立）**：① finalize 为单遍标量一步（单条算术指令可完成，如 `s·avg`/`s+ε` 类——**含超越函数或迭代求精的不满足**）；② 行全载支（x 驻留不重读）；③ 归约可内联（C8 证据支成立）。豁免并入时在 rationale 记录三条件核验 + 规则编号 + 行号锚点。
> - **与 C8 的关系**：独立性判据**不依赖 C8 证据状态**——C8 证据支回填（归约可单遍内联）不改变含超越函数/迭代求精 finalize 段的独立结论，避免 vf_count 随下游查证回填震荡；边界与 C8 折叠 finalize 边界重合时，引用取实际触发者。
> - **产物义务**：finalize 段独立时按独立 VF 产出完整函数接口（签名 + 参数表 + 伪代码）；`handoff_notes.materialization` 记录物化点 `coincides_with_split: true`。

> **寄存器压力不是拆 VF 的理由**：即使单 VF 很长，只要 C1-C9 未触发切分就不拆（C6 触发即默认拆，不再属于"未触发"情形；其豁免条件见 C6 说明块）——额外 UB load/store 的代价通常大于节省的寄存器。寄存器压力是 profiling 之后的性能优化维度，不属于本步骤职责（定量核算留给 `ascendc-op-tiling-buffer-kernel`）。**粗估**：展开操作序列，数 RegTensor 声明数，<20 安全，20-30 关注，>30 高风险。但编译通过就不拆——超阈时在决策记录中标注风险点，交由下游定量判断。（例外：C7 由**结构**判据触发——多级归约链 + 输出物化，非寄存器压力；op_count 超红线是 C7 场景的佐证之一，不是触发条件。）

**③ 追踪变量流向 → 判断依赖**

```
操作 A 产出 mean_sq
   ├──→ 操作 B 消费 mean_sq    ← B 依赖 A
操作 B 产出 rstd
   ├──→ 操作 C 消费 rstd       ← C 依赖 B
gamma → 操作 C 消费 gamma      ← gamma 无依赖（外部输入）

依赖链: A → B → C  → 全部串行
（依赖关系只决定顺序约束与 data_flow 表达，VF 边界已由步骤②的 C1-C9 确定）
```

**④ 取 split.loopCount + 决策树 → 模式**

| VF 数 | 依赖 | loopCount | 模式 |
|-------|------|-----------|------|
| 1 | — | 1 | 模式 1 |
| 1 | — | ≥2 | 模式 2 |
| 2 | 有 | 任意 | 模式 3 |
| 3 | 有 | 任意 | 模式 4 |
| ≥4 | 有 | 任意 | 模式 4 推广 |
| ≥2 | 无 | 任意 | 模式 5（多 VF 独立，顺序无约束） |

> **C9 与决策树**：跨核归约终段（GM workspace + SyncAll 后的 finalize）计入 vf_count 后再查表（如核内局部归约 1 VF + 跨核 finalize 1 VF = 2 VF 有依赖 → 模式 3）。多核并行本身仍是一切模式的基底能力（见强制约束 4），C9 只针对"核间切分轴与统计轴相同"的两阶段归约形态。

> **vf_count 允许条件化/区间化**：当 C5/C7 判定依赖的容量或结构条件随 shape/attr 变化时（如 H≥2048 拆 3 / H<2048 融 1；reduction=none 2 段 / mean·sum 3 段），`vf_count` 必须写成**条件表达式**（如 `"1 (H<2048) / 3 (H≥2048)"`）而非单值，单值会被下游误读为全称结论。条件分支数 ≤3，每支注明判据（阈值来源：C5 的 8KB 口径、C7 的归约级数/输出契约、或 golden 的 attr 分支锚点）；**每支还须显式标注模板维度**（如"行全载融合支 / 行切分重算支"，分支来源：步骤 0 的上游模板划分或模板维度外推），与下游 tiling key 分派结构对应，便于 buffer-kernel/codegen 按模板落地；分支间模式可不同，须逐支对照决策树。

---

**完整判定样例（行号锚定）**：

> golden 含迭代结构（首轮 softmax 归一化、后续轮纯归一化交替，行/列两统计轴），展开后：
>
> | 段 | 操作 | 轴 | 轮次 | 锚点 |
> |---|------|----|------|------|
> | S1 | ReduceMax(row) → Sub(broadcast) → Exp → ReduceSum(row) → Div(broadcast, 分母无 eps) → Adds(+eps) | row | 首轮 | L51-L57 |
> | S2 | ReduceSum(row) → Div(broadcast, 分母含 eps) | row | 后续轮 | L63-L64 |
> | S3 | ReduceSum(col) → Div(broadcast, 分母含 eps) | col | 每轮 | L59-L60, L65-L66 |
>
> 逐规则判定：
> - **C1**：S1 内 ReduceSum 的紧随消费 Div 与其统计轴相同、同轮 → 融入 S1；S2/S3 内规约同理 → 不因聚合多切。
> - **C2**：S1/S2（row 轴）与 S3（col 轴）统计轴不同 → S3 独立成 VF。
> - **C3**：S1 与 S2 操作序列不同（max-shift+exp+分母无 eps vs 分母含 eps）且分属不同轮次 → 各自独立成 VF。
> - **C4**：S1 与 S2 控制流不等价 → 禁止合并。VF 内 if-else 本身合法，但 S1/S2 是两个**结构不同**的 op 序列。
> - **结论**：3 个 VF（S1 / S2 / S3），串行依赖，模式 4。

---

**快速判断口诀**：

> 前提：A5 统计量驻留寄存器——聚合边界不自动成切分线，切分只看 C1-C9（勿把"见聚合就切"的 membase 习惯带入）。
> 看 golden：统计轴只有一种且逐段同轮消费 → C1 融合不切；出现第二种统计轴 → C2 必切。
> 看轮次：首轮与后续轮操作序列不同 → C3 必切——if-else 塞一个 VF 不算融合（参数分支可融，结构分支必切）。
> 看容量：二次遍历且中间量 ≥ 8KB（或活跃 vreg > 32）→ C1 收益归零 → C5 平局拆分（模块化优先）；中间量 < 8KB → 保持 C1 融合。
> 看输出：统计量/中间量本身是算子输出（rstd/scale 类）→ C6 弱默认拆——物化点默认成切分线，仅当单 VF op_count≤10（8-10 须标注 chain_length_risk）且寄存器粗估 <20 时可显式豁免；拆与豁免都须记 handoff_notes。
> 看归约级数：统计量是输出（C6）且第二级归约吃第一级结果（Var 依赖 Mean）或需重复遍历 x → C7 按统计阶段分段（Mean/Var/R/Y 各自成 VF，finalize 段默认独立——三条件豁免才并入）；单遍同算 Σx/Σx²（矩法/Welford）→ 归约级数折叠，退回 C6 两段拆；单次归约不重读 x（rms_norm 形态）→ 不按 C7 分段。
> 看实现：归约/排序须走高级 API（ReduceSum/Sort32/Gather 等）或折叠归约对齐 → C8 以 API 调用点为段边界，前后自定义 __VEC_SCOPE__ 各自成 VF。
> 看跨核：核间切分轴与统计轴相同 → C9 跨核 finalize 独立成 VF（vf_count+1），不再只是标注。
> 看变量：B 用不用 A 的结果？用→有依赖（串行链）。不用→无依赖（独立，顺序任意）。
> 看 tiling：单轮→模式 1，多轮→模式 2。

---

模式详情见 [`vf_archetypes.md`](references/vf_archetypes.md)。决策树见 [`common_design_decisions.md`](references/common_design_decisions.md)。VF 数≥2 时"能否合并相邻 VF"的判据另见 `ascendc-op-design-shared/references/a5_regbase_design.md`「VF 函数划分策略」节的规则 VF-2/VF-3。

内部记录（不落盘，供步骤 3 生成产物使用）：

```yaml
pattern: 4
pattern_name: "三 VF 全流水"
vf_count: 3
has_dependency: true
loop_count: 1
rationale: "C1 融合同轴消费；C2 切 col 轴；C3 切首轮 softmax 段（含 golden 行号锚点）"
c5_tie_break: "（若触发）二次遍历 + 中间量驻留 {X}KB ≥ 8KB → C5 平局拆分于聚合边界"
  c7_stage_split: "（若触发）C6 输出物化 + Var 依赖 Mean 二级归约/重复遍历 x → 按统计阶段分段 M/V/R/Y（R 默认独立，三条件豁免才并入）"
handoff_notes:                  # 三类移交标注（无触发项时为空数组，字段本身必填）
  - {type: materialization, item: rstd, anchor: L11, coincides_with_split: true, width: scalar}    # C6：弱默认拆后物化点与切分线重合；豁免拆分时为 false
  - {type: register_risk, item: exp 行中间量, vf: vf_0, bytes: "D×4B vs 8KB", vreg: 18}             # C1 融合遗留风险
  - {type: cross_core_stats, item: per-core 部分和, via: "GM workspace + SyncAll", anchor: L63}    # C9：跨核 finalize 段已计入 vf_count
```

> 注：yaml 中 `handoff_notes` 三条为三类标注的**字段示意**；上方完整判定样例（S1/S2/S3，无统计量输出）的 handoff_notes 实际应为空数组。

### 2. 快速通道判定（简单算子优化）

若步骤 1 判定结果为 `vf_count == 1`（模式 1 或模式 2，无跨 VF 依赖）：

- **跳过「关键决策点」一节的逐项决策点提问**，直接进入步骤 3 实例化——单 VF 场景不存在"依赖关系是否明确""能否合并相邻 VF"这两类决策点，UB 超限检查仍保留（若触发则仍需提问）。
- 决策记录中标注 `fast_path: true`，`rationale` 写明"vf_count=1，无跨 VF 决策点，直接实例化"。

否则（`vf_count ≥ 2`）走完整流程（步骤 3 + 「关键决策点」一节）。

### VF 接口规范

每个 VF 由四要素定义：**输入端口 + 输出端口 + 计算公式 + 计算操作序列**。详见 [`vf_interface_spec.md`](references/vf_interface_spec.md)。

### 3. 实例化，填参数

给定模式和 VF 接口规范，为每个 VF 填充 **计算内容 + 输入输出端口 + 函数接口定义**，落进 `vf_design.vfs[]`：

| 参数 | 来源 | 示例 |
|------|------|------|
| VF 编排 | 模式决定 | 3 VF 串行，同 V 引擎顺序执行，VF 间无同步 |
| 每 VF 的输入端口 | 变量流向追踪 | VF_1: `mean_sq(float, from vf_0)`, `eps(float, from tiling)` |
| 每 VF 的输出端口 | 变量流向追踪 | VF_0: `mean_sq(float, to vf_1, buf=mean_sq_buf)` |
| 每 VF 的计算公式 | 步骤 1 展开的操作序列 | VF_0: `mean_sq = reduce_sum(x²) / D` |
| 数据流图 | 端口连接关系 | `copy_in → vf_0 → vf_1 → vf_2 → copy_out` |
| Buffer 策略 | loopCount + 硬件 UB 容量（取自 split 段 + `hw_params.json`） | 双 buffer，buf 名与端口 `storage` 对齐 |
| 同步点 | 模式 + 跨引擎边界 | 仅 MTE↔V 跨引擎边界通过 TQue EnQue/DeQue 实现流水同步，VF 间（同 V 引擎）无同步 |
| **每 VF 的函数接口** | **参数流向 + RegBase 风格** | **`__aicore__ inline void ComputeXxx(LocalTensor<DX>&..., uint64_t...)`** |
| **每 VF 的 dtype 组合矩阵** | **算子 `op_spec` 支持的 dtype 集合 × VF 计算语义** | `supported_dtype_combinations` 列出所有合法 (inputs→outputs) 组合 |
| **移交标注 `handoff_notes[]`** | **C6 物化点 + 寄存器驻留风险 + 跨核统计量物化点**（判定来源见下） | 三类下游决策点的显式清单，见下方说明 | 

**`handoff_notes[]` 移交标注（本 skill 与下游的分歧显式化契约，三类，均在步骤 1 判定过程中产生）**：

| 类型 | 触发判据 | 记录内容 | 移交对象 |
|------|---------|---------|---------|
| `materialization`（C6 物化点） | 统计量/中间量是算子输出（见 C6 说明） | 输出名、产出锚点、是否与切分线重合（弱默认拆后通常为 true；豁免拆分时为 false 并附豁免理由）、标量宽度 | buffer-kernel（物化写出与输出队列流水对接；豁免时裁决单 VF 内物化） |
| `register_risk`（寄存器驻留风险） | C1 融合成立但行/中间量驻留需求 ≥ 8KB 且未触发 C5（无二次遍历），或活跃 vreg 粗估 20-32 | 风险位置（VF 名 + 锚点）、驻留字节数估算、vreg 粗估 | buffer-kernel（定量核算后决定是否按 REG-2 再拆/UB 中转） |
| `cross_core_stats`（跨核统计量物化） | 核间切分使单核只产部分统计量（split 段核间切分轴与统计轴相同，如 foreach 类多核归约） | 统计量名、部分和落点（GM workspace + SyncAll）、锚点；finalize VF 已按 C9 计入 vf_count | tiling-split 多核层（两阶段执行） |

> 约束：`register_risk` 为**纯标注**，不改变 vf_count；`materialization` 与 `cross_core_stats` 除标注义务外还分别经 C6（弱默认拆）/ C9（终段成 VF）影响 vf_count——先按 C6/C9 定 vf_count，再如实标注。

**函数接口定义要求**（步骤 3 强制输出，写入 `vf_design.vfs[]` 每个条目）：

1. **函数签名**（`function_signature`）：`__aicore__ inline void` 完整声明，含所有参数的类型和名称。参数类型使用 AscendC 标准类型：`LocalTensor<T>&` / `TBuf<...>&` / 标量 (`uint16_t`, `float` 等)。若 VF 需支持多种输入 dtype，签名中使用模板参数（如 `template <typename DX>` / `LocalTensor<DX>&`）。
2. **参数表**（`interface_params`）：每个参数的方向（in/out/tmp）、存储来源、UB 布局、**dtype**。`dtype` 字段使用统一类型标识（`fp16`/`bf16`/`fp32`/`int8`/`int32`/… 或模板占位符 `DX`/`DY`）。
3. **逻辑端口**（`inputs` / `outputs`）：每个端口的 `name`、`from`/`to`、**dtype**，与 `interface_params` 一致。
4. **支持的 dtype 组合矩阵**（`supported_dtype_combinations`）：必填。从 `requirement.json` 的 `op_spec` 提取算子支持的 dtype 集合，按 VF 计算语义展开为该 VF 必须验证的输入/输出 dtype 组合矩阵。每种组合表示为 `{inputs: {name: dtype, ...}, outputs: {name: dtype, ...}}`。**vf-test 阶段必须对该矩阵中每种组合做独立精度验证**。
5. **模板参数说明**（如有）：每个模板参数的取值和原因。
6. **伪代码**（`pseudocode`）：`__VEC_SCOPE__` 内的 RegTensor 操作序列。
7. **Process() 主循环伪代码**（`process_pseudocode`）：展示各 VF 的调用顺序和 buffer 生命周期。
8. **链长计数 `op_count`**（必填，与 `compute_ops` 同源）：单 VF 内 Vector 计算指令条数（Load/Store/Cast 不计）。**红线参考值 7**（工程惯例值，非本 skill 硬约束）：≤7 安全；8-12 标注 `chain_length_risk`（不强制拆——与「寄存器压力不是拆 VF 的理由」条款同构，C1-C9 未触发就保持融合）；>12 高风险，除标注外须在 `handoff_notes.register_risk` 补一条记录并写明理由——若该超长由"多级归约链 + 输出物化"结构导致，回查 C7 是否应触发而未触发（op_count 超红线是 C7 场景的**回查信号**，非 C7 触发条件）。

输出格式（`tiling_vf_design.json` 的 `vf_design` 结构）详见 [`output_format.md`](references/output_format.md)（字段定义对齐 JSON，原 YAML 字段一一映射）。字段 schema 见 [`vf_design_schema.yaml`](references/vf_design_schema.yaml) 与本 skill `schema/tiling_vf_design.json`。

## 参考资料

| 文档 | 用途 |
|------|------|
| [vf_archetypes.md](references/vf_archetypes.md) | 5 个模式的定义 + 处理示意图 + 实例 |
| [common_design_decisions.md](references/common_design_decisions.md) | 决策树 + 设计决策框架 |
| [vf_design_schema.yaml](references/vf_design_schema.yaml) | `vf_design` 字段结构定义（JSON 产物按此映射） |
| [kernel_organization_patterns.md](references/kernel_organization_patterns.md) | Kernel 代码组织模式（基类继承、helper struct 等） |

## 设计范式库（只读参考）

```
library/patterns/standard/
├── pattern_1_single_vf_v1.yaml        # 模式 1/2：单 VF 纯计算
├── pattern_1_single_vf_index_v1.yaml  # 模式 1/3：单 VF + idx 辅助
├── pattern_3_dual_vf_v1.yaml          # 模式 3：双 VF reduce→normalize
├── pattern_4_triple_vf_v1.yaml        # 模式 4：三 VF 全流水
├── pattern_4_chain_vf_v1.yaml         # 模式 4：5 VF softmax 链
└── pattern_5_parallel_vf_v1.yaml      # 模式 5：多 VF 独立
```

范式库作为**参考模板**——步骤 3 实例化时可以参考最近似范式的 buffer 分配、同步点配置等数值。**不执行"匹配→派生"流程，模式由决策树决定。**

## 关键决策点（触发 AskUserQuestion）

以下决策点仅在 `vf_count ≥ 2` 时适用（`vf_count == 1` 走快速通道，见步骤 2）：

| 触发条件 | 询问内容 |
|---------|---------|
| VF 间依赖关系不明确 | "vf_A 的输出是否被 vf_B 消费？有依赖链还是各自独立？" |
| 依赖链中是否可合并相邻 VF | "操作 B（纯标量运算）是否可合并到 A 或 C？合并后 VF 数由 {N} 降为 {N-1}"（判据引用 `a5_regbase_design.md` 规则 VF-2） |

**C5 平局不触发提问**：容量判据（≥8KB / >32 vreg）可静态判定，平局裁定（模块化拆分）是确定性默认规则——若需偏离默认（如强经验表明融合更优），由下游 profiling 数据驱动回改，不在本 skill 裁量。

以下决策点不受快速通道影响，任何 `vf_count` 均适用：

| 触发条件 | 询问内容 |
|---------|---------|
| UB 占用超限 | "估算 UB {X}KB 超过目标平台容量 {Y}KB，请选择：降 tile / 拆 VF / 接受" |

## 强制约束

1. **CopyIn/CopyOut 不是 VF**：只数 `__VEC_SCOPE__` 块
2. **公式优先**：与 golden 代码冲突时以数学公式为准
3. **队列深度是通用配置**：与 VF 数量无关，任何模式都可用
4. **多核是所有模式共有的基底能力**：不是某个模式专属
5. **不输出参考算子信息**：VF 设计方案是独立产物，不包含任何对其他算子的引用（包括但不限于：差异对比表、「参考基准」标注、`based_on` 字段、「与 xxx 算子不同」描述）。参考算子仅用于步骤 1 分析阶段的内部推导，不出现在最终产出中。
6. **不做寄存器级定量核算**：RegTensor 逐个计数、MicroAPI 910D 查证、Cast 布局红线是 `ascendc-op-tiling-buffer-kernel`（A5 路径）的职责，本 skill 只产出编排结构和函数接口定义
7. **特殊值语义必读（elementwise Max/Min 类 compute_ops 选型当下）**：需与 golden 逐位对齐的 `maximum`/`minimum` 及 foreach 变体，**不得**默认 `Max`/`Maxs` 指令可用——SIMD Max 的 NaN 语义未文档化且其 ±0 tie（`-0/+0→+0`）与 golden tie 取 self 冲突；默认走语义确定的 `Compare(NE)+Compare(GT)+Select` 复合原语。规则、锚点与对照表见 `ascendc-op-design-shared/references/special-value-semantics-max-min.md`。

## 知识引用策略

通用知识引用策略（三层优先级 + 禁止猜测）详见 `ascendc-op-design-shared/references/knowledge_policy.md`。

平台差异化参考（A3 vs A5）详见 `ascendc-op-design-shared/references/platform_diff.md`。A5 VF/RegBase 判定规则详见 `ascendc-op-design-shared/references/a5_regbase_design.md`。

本 skill 特有的查询场景：

| 层级 | 查询场景 | 对应执行步骤 |
|------|---------|-------------|
| Tier 1 | 目标平台 UB 容量（用于「UB 占用超限」决策点的估算基准） | 步骤 3（实例化，Buffer 策略） |
| Tier 2 | VF 编排模式的设计模式参考（范式库以外的补充场景） | 步骤 1（选模式）、步骤 3（实例化） |

**查询约束**：
- 本 skill 不做硬件 API 能力查证（不含 gather/scatter/reduce 等骨架级 API 的 Tier 3 查证门），该职责在下游 `ascendc-op-tiling-buffer-kernel`
- UB 容量优先从本工作目录物化的 `hw_params.json` 读取，禁止裸数字估算

## 输出自检

- [ ] **固定前提 + 切分判据可对质**：产物为 A5 Regbase 编排（统计量驻留寄存器），未引入"见聚合就切"的 membase 式切分；rationale 或 decisions 中每处切分/合并/物化点标注决策均引用 C1-C9 规则编号 + golden 行号锚点（裸"沿聚合边界切"式描述不合格）；触发 C5 时容量判定已记录（中间量驻留字节数 / 活跃 vreg 粗估 vs 8KB / 32），触发 C7 时结构判定已记录（哪两级归约串行依赖 / 哪些物化点），未触发时无需记录
- [ ] **C6 弱默认拆已执行**：`requirement.json` outputs 中每个"统计量/中间量型输出"（rstd/scale/mean 类）默认已在物化点拆分；豁免拆分的已同时满足 op_count≤10 且活跃 RegTensor <20 并在 rationale 记录豁免理由（op_count 8-10 的豁免 VF 已标注 chain_length_risk）；无论拆合，`handoff_notes` 有对应 `materialization` 条目（含锚点与 coincides_with_split）；无此类输出时 `handoff_notes` 为空数组
- [ ] **C7 判定无漏判/误判**：norm 家族形态（统计量是输出 + 依赖统计量的归一化）已逐条核对 C7 两条件（C6 判据成立 / 串行依赖多级归约或重复遍历 x），含**单遍归约豁免**核对（golden 是否在同一遍历内同算 Σx 与 Σx²——矩法/Welford，如有则退回 C6 两段拆）；触发时分段正确（M/V/R/Y 各自成 VF；统计量 finalize 段默认独立，并入须三条件豁免核验并在 rationale 记录）、`coincides_with_split: true` 已置位；单次归约不重读 x 的场景（rms_norm 形态）确认未误触发
- [ ] **C8 实现约束已前置核对**：计算链中的高级 API 调用（ReduceSum/Sort32/Gather 等不可内联进自定义 `__VEC_SCOPE__` 的库调用）与折叠/二分归约对齐约束已识别；对 reduce/max/sum/softmax 类需求，若无法证明单遍可内联进自定义 `__VEC_SCOPE__`，已按 C8 默认拆或写成条件表达式，并注明不能证明可内联的原因
- [ ] **C9 跨核终段已计数**：split 核间切分轴与统计轴相同时，跨核 finalize 段（GM workspace + SyncAll 后的最终归约）已计入 vf_count 并重取模式；`handoff_notes` 有对应 `cross_core_stats` 条目
- [ ] **handoff_notes 字段完整**：materialization（C6 条已核）与 cross_core_stats（C9 条已核）之外，register_risk（C1 融合但行/中间量驻留 ≥8KB 且未触发 C5，或活跃 vreg 粗估 20-32）无遗漏；三类条目字段完整（含锚点/宽度/vreg 粗估）
- [ ] **vf_count 条件化正确**：依赖 shape/attr 的结论写成条件表达式（分支 ≤3 且各有判据、**模板维度标注**与模式），无条件依赖时为单值；未把条件结论误写为单一全称值
- [ ] **模板维度外推已执行**：上游模板划分（split 段/template_division）存在时已核对登记；缺失时已按归约轴 D 极值 × `hw_params` 容量外推整行驻留阈值，超阈已强制产出行切分重算支（二段式 data_flow + x 双读 handoff 标注），未超阈已登记单模板结论与阈值判据
- [ ] **op_count 已产出且红线处理**：每个 VF 的 `op_count` 必填；>7 已标注 `chain_length_risk`，>12 已入 `handoff_notes.register_risk`
- [ ] 模式编号（1-5）与 VF 数/依赖/loopCount 组合一致（对照决策树表；vf_count 条件化时逐支对照）
- [ ] `vf_count == 1` 时已走快速通道（跳过依赖/合并类提问），决策记录标注 `fast_path: true`
- [ ] 每个 VF 均已产出完整函数接口定义（签名 + 参数表 + 伪代码 + dtype 组合矩阵）写入 `vf_design.vfs[]`，无遗漏
- [ ] 每个 VF 的 `interface_params` / 逻辑端口均含 `dtype`，且与 `supported_dtype_combinations` 一致
- [ ] `supported_dtype_combinations` 已穷举该 VF 需支持的所有输入/输出 dtype 合法组合，无遗漏、无多余
- [ ] VF 间数据流（`data_flow`）与端口定义一致，无悬空引用
- [ ] Buffer 策略与 `tiling_current_template.json` 的 `split` 段 loopCount/ubFactor 结论一致
- [ ] **统计量不占 UB 常驻缓冲**：中间统计量驻留寄存器，不出现在 `ub_layout` 常驻缓冲中；经 C5/C6/C7 拆分后段间交接的量除外——此类量须有对应 UB buffer 条目
- [ ] 未输出任何参考算子信息（无差异对比表、`based_on` 字段等）
- 自检失败 → 就地修正直到通过
- 自检通过后，最终产出 `tiling_vf_design.json`（`required_keys: ["template","vf_design"]`，schema 见 `schema/tiling_vf_design.json`）

## 完成后

产出 `tiling_vf_design.json`（见「输出」节），供下游 `ascendc-op-tiling-buffer-kernel`（A5 路径）作既定前提消费、供 codegen 阶段作 `.VT.{M}` 规格消费。
