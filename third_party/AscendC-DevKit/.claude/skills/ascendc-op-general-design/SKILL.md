---
name: ascendc-op-general-design
description: 从算子需求规格生成标准概设文档
triggers:
  - 概设
  - 概要设计
  - general-design
  - 生成概设
  - 写概要设计
  - 概设文档
---

# AscendC 算子概要设计

## 职责

从算子需求规格（`requirement.json`）出发，结合业务背景信息，输出标准格式的概设文档。核心定位：**说清"为什么做"、"要做什么"和"打算怎么做"**，同时为后续模板划分（template-division）和 Tiling 推导提供明确的策略框架（模板候选方案 + TilingData 字段定义 + 循环结构伪代码），但不涉及"具体实现细节"。

## 开场白（首次加载时输出）

> 本 skill 负责生成算子概要设计结构化产物（`general_design.json`）。
>
> 概设的核心定位是策略级设计：**说清楚"为什么做"、"要做什么"和"打算怎么做"**，同时为后续的模板划分和 Tiling 推导提供明确的策略框架（TilingData 字段定义 + 模板结构循环框架），但不涉及"具体实现细节"。
>
> 我将从 `requirement.json` 出发，按八段式内容组织（算法背景→算子定义→架构设计→Tiling设计→Buffer/性能→可行性→约束→附录）为您生成 `general_design.json`——下游强依赖的四个节点（切分轴优先级/TilingData字段/循环框架/Buffer评估）落为顶层结构化字段，其余背景与推导性内容落为 `narrative` 自由文本。请确保 `{workdir}/requirement.json` 已存在，或在本会话中提供算子规格信息。同时请提供业务背景信息（目标模型场景、相关算子生态、典型 shape），以便生成完整的算法背景内容。

## 输入

> **输入来源**：算子规格/需求等**主要结构化输入已物化到当前工作目录**（`requirement.json` +
> 如有概设文档则为 `existing_general_design.md`）。算子身份同时以轻量标识在 prompt 提供。
> `references/*` 是本 skill 自带的设计参考资料（按需加载），不读其它设计步骤写出的中间文件。
> **读取纪律**：每个上游产物文件只读一次（读后缓存，不重复 Read 同一路径）；禁 `ls`/`cd` 目录侦查（只操作输入表显式路径，不遍历目录去「发现」文件）。

| 输入项 | 是否必须 | 说明 |
|--------|---------|------|
| `requirement.json` | 是 | 当前工作目录；算子规格/需求的结构化产物（设计的事实源） |
| `existing_general_design.md` | 否 | 当前工作目录；增量场景的已有概设文档（用于 pass-through/增量补全） |
| 用户口述的额外约束 | 否 | prompt 提供（性能目标、芯片平台、特殊限制等） |
| `references/design_patterns.md` | 否 | 算子设计模式索引文件（按需加载） |
| `references/general_design_common_knowledge.md` | 否 | 平台硬件参数与通用设计原则（与索引一并加载） |
| `references/patterns/atomic/*.md` | 否 | 原子模式文件（按需加载命中的模式） |
| `references/patterns/fused/*.md` | 否 | 融合模式文件（按需加载命中的融合编排） |

## 参数

本 skill 无需显式参数。是否基于已有概设文档增量补全取决于 `existing_general_design.md` 是否存在（→pass-through/增量补全；否则从零生成）。

## 输出（用 Bash（`cat`）写到当前工作目录）

| 产物 | 必需 | required_keys | schema |
|---|---|---|---|
| `general_design.json` | 是 | `op_name, split_axis_priority, tiling_data, loop_framework, buffer_eval` | `schema/general_design.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |

> 契约的机器校验来源：`schema/general_design.json`（JSON，含 required_keys + example）。
> 产出不符合 schema → DevKit 适配层拒绝，重试。
> **本 skill 唯一产物是 `general_design.json`**——不再单独产出 markdown 文档。四个顶层结构化字段（`split_axis_priority`/`tiling_data`/`loop_framework`/`buffer_eval`）是下游强依赖节点，机器强校验；`gradient_formula`（归一化梯度公式，条件性）与 `narrative`（其余背景、推导过程、模板候选、差分分析等叙述性内容，供人读与下游 CR3 扫描）为可选顶层字段。

## 概设内容组织（八段式，指导 narrative 的内容完整性，非文档章节骨架）

以下八段式是**内容组织指引**，帮助生成时思考完整性；落笔目标是 `general_design.json` 的顶层字段——四个下游强依赖节点写入对应结构化字段，其余内容整合进 `narrative` 字段（保留章节化小标题便于人读，但不再是独立文件）。

> **单一权威来源**：各段的完整占位符、小节划分与填写格式以 `references/general_design_template.md` 为准（作为内容checklist使用）。本 skill 不在此重复逐段要点——生成各段内容时读取 template 对应占位符填充。下表仅给内容职责一览，便于快速定位；末列标注该内容落入哪个 JSON 字段。

| 段 | 段名 | 一句话职责 | 关键小节（详见 template） | 落入字段 |
|----|------|-----------|--------------------------|---------|
| 1 | 算法背景与需求 | 说清"为什么做、什么场景用" | 业务背景 / 生态现状 / 需求清单 | `narrative` |
| 2 | 算子定义书 | 继承 op_spec，仅格式整理 | 数学公式·地址映射 / 接口定义 / 支持范围 / 边界语义 | `narrative`（含归一化梯度公式时另写 `gradient_formula`） |
| 3 | 架构设计 ⭐ | 数据怎么流、计算怎么分、模板怎么划 | 计算流程 / 数据流拓扑 / 轴分析 / **并行分解策略** / **模板划分策略** | 并行分解策略 → `split_axis_priority`；其余 → `narrative` |
| 4 | Tiling 设计 ⭐ | 从原则到策略级结构，喂详设 | 级数与切分 / **TilingData 字段定义** / **各模板循环结构** / 对齐策略 | TilingData 字段定义 → `tiling_data`；各模板循环结构 → `loop_framework`；其余 → `narrative` |
| 5 | Buffer 与性能设计 | 只答"能否放下"，不答"怎么放" | **Buffer 可行性评估** / 关键性能权衡 / 计算范式与瓶颈 | Buffer 可行性评估 → `buffer_eval`；其余 → `narrative` |
| 6 | 可行性论证 | 理论估算 + 瓶颈断言 + 风险 | 计算量·访存量估算 / 瓶颈断言 / 风险标注 | `narrative` |
| 7 | 设计约束记录 | 记录保持不变 / 新增变更的设计 | 保持不变 / 新增变更 | `narrative` |
| 附录 | — | 比对与典型数据 | A.Golden 代码 / B.典型 Shape / C.关键决策记录 | `narrative` |

> ⭐ 标记的段含**推导动作**（非纯填段），其设计要点在「执行步骤」中展开；其余为"读 template 占位符 → 按 op_spec/上游材料填充"。
> **Buffer 职责边界**：概设只回答"能否放得下"（共存约束 + 常驻/流式定性），不回答"具体怎么放"。Buffer 布局、BUFFER_NUM、TQue/TBuf、复用策略由 `ascendc-op-tiling` skill 负责。

---


## 边界红线（概设的核心约束）

概设 skill 必须严格遵守以下红线，确保不越界到详设范畴：

| 维度 | 概设层面（允许） | 详设层面（禁止） |
|------|----------------|----------------|
| Tiling | 几级、沿哪个轴、静态/动态、**模板结构的循环框架（伪代码级）、TilingData 字段定义（不含默认值）** | ubFactor 具体公式、具体数值、blockIdx 映射公式 |
| Buffer | 数据流拓扑、存储层级标注、**共存约束清单（需同时驻留 UB 的数据项）、常驻 vs 流式定性判断、UB 可行性验证（概设仅回答"能否放得下"）** | TQue/TBuf 具体分配、BUFFER_NUM、InitBuffer 参数、Buffer 复用策略、排布细节 |
| Kernel | 算法流程（文字/Mermaid） | 函数签名、伪代码、C++ 模板参数 |
| 精度 | 是否升 FP32 的方向性决策 | Cast 时机、具体精度链、atol/rtol 数值 |
| 性能 | 瓶颈类型、理论上限估算、**关键设计决策的 trade-off 分析（如多种搬运策略对比）** | Tile 级 cycle 估算、流水线有效性验证 |
| 数值 | 参数级表达式（如 `sizeof(T)`） | 代入具体 shape 的数值计算 |
| TilingData | **定义结构体字段名、类型、语义描述、取值来源** | 默认值、初始化代码、序列化代码 |
| 模板划分 | **候选模板列表、各模板支持范围、合并/拆分理由** | 具体 TILING_KEY 数值分配、模板选择函数实现 |
| 模板选择 | **编程模型判定（SIMD/SIMT/MIXED，经 `ascendc-op-design-template-select`，含 MIXED 的 shape 路由条件）** | 模板数量、TilingKey 分配、模板条目结构（归 template-division）、`vf_split` 段级拆分（首版不产出） |

**新增允许的边界说明**：
- **模板结构的循环框架**：允许给出类似 `for (xIdx) { for (zIdx) { CopyInA(); for (yIdx) { CopyInB(); ComputeElementwise(); CopyOut(); } } }` 的嵌套结构伪代码，但不允许代入具体 ubFactor 或 blockIdx 数值。
- **TilingData 字段定义**：允许定义 TilingData 的字段名、类型(int64_t/uint32_t)、语义描述，但禁止给出默认值或序列化代码。
- **Trade-off 分析**：允许对比多种设计方案（如 partial_rope 的4种数据搬运策略）并给出推荐选择，但禁止进行 Tile 级精确 cycle 估算。
- **模板划分策略**：允许多个 mode 合并/拆分的候选方案（如 "mode 0/1 可复用同一模板，mode 3 需独立模板"），但不允许分配具体 TILING_KEY 数值。

**核心原则**：

> 好的概要设计应该做到：详细设计人员拿到后，知道"要做什么"，了解"打算怎么做"的策略，并带着清晰的模板结构和 TilingData 框架进入详细设计阶段。不包含的是"具体实现细节"（ubFactor 数值、函数实现代码、Buffer 句柄初始化）。

## 执行步骤

### 步骤1：概设完整性判断（pass-through 决策点）

仅在上游提供了既有概设材料时执行（工程在 prompt 中注入了已有 `general_design.json` 或 `existing_general_design.md` 正文，或用户在本会话中提供了概设文档路径）。未提供既有概设材料时跳过本步骤，直接进入「加载上游决策记录 & 采集业务上下文」步骤。

读取既有概设材料（无论其自身是 JSON 还是 markdown 文本），按以下顺序检查是否满足全部条件——检查的是**内容语义是否齐全**，不绑定具体文件格式：

1. 算法背景与需求、算子定义、架构设计、Tiling 设计、Buffer 与性能设计、可行性论证、设计约束记录、附录八类内容均有对应素材（无论以 JSON 字段还是文本段落呈现）
2. 多核切分轴优先级描述存在（→ 对应 `split_axis_priority`）
3. TilingData 字段表格存在（字段名 / 类型 / 语义三列，→ 对应 `tiling_data`）
4. 各模板嵌套循环伪代码存在（→ 对应 `loop_framework`）
5. Buffer 共存约束清单和至少一个典型 shape 的可行性验证存在（→ 对应 `buffer_eval`）

**全部满足 → pass-through 模式**：

- 不对已有内容做实质性修改，仅将其转录/整理为 `general_design.json` 的顶层字段（四个结构化字段照抄，其余内容整合进 `narrative`）
- `narrative` 字段末尾追加 self-check 标记文本："general-design self-check: passed (pass-through, no modification)。"
- 直接跳至「质量自检」步骤，然后输出。

**任意一项不满足 → 增量补全**：

- 记录哪些条件不满足（内部临时记录，不输出）
- 继续执行「加载上游决策记录 & 采集业务上下文」步骤（正常流程），在「模板划分策略」步骤和「Tiling 设计」步骤中优先保留已有内容，仅补全缺失部分
- 所有补入内容在 `narrative` 中标注 `[增量补入]`；补入的结构化字段（`split_axis_priority`/`tiling_data`/`loop_framework`/`buffer_eval`）值本身即是补全结果，无需额外标注

---

### 步骤2：加载上游决策记录 & 采集业务上下文

若本次对话上下文已含上游需求分析的决策记录 / 自由扩展信息，则加载供参考；没有则不影响执行
（无需到别处搜寻中间文件）。然后通过 AskUserQuestion 采集以下业务上下文：

```
请确认以下信息：
1. 算法背景：该算子在哪个模型/场景中使用？解决了什么业务痛点？
2. 算子生态：是否存在相关算子？本算子的新增功能与存量算子的关系？
3. 典型 shape：业务场景的实际 shape 和 dtype？
4. 性能目标：是否有明确的性能指标（如"已有场景性能不劣化"）？
5. 约束条件：是否需要向后兼容、图模式支持等？
```

如果用户提供了 `code_constraints.md`（存量代码约束），读取其中的平台信息、存量接口兼容性约束。

### 步骤3：算子设计模式匹配 ⭐

> 本步骤基于**三维正交分类**（LP 循环结构模式、CP 计算通路、ES 执行结构），
> 通过 LP×CP 速查矩阵定位计算通路 + ES 维度定执行结构，决定走"路径一（精确复用）"、"路径一·差分（家族匹配）"还是"路径二（从零构建）"。

**快速对照**：为便于从旧框架（L1~L4）过渡，LP 维度对应原 L2（依赖图拓扑），CP 维度对应原 L3（计算范式），ES 维度为新增。L1（张量签名）和 L4（工程约束）降级为模式内部的属性参数。

#### 3.1 加载索引与共性知识

读取以下两个文件为全局上下文：

1. **`{skilldir}/references/design_patterns.md`** — 模式索引文件（轻量级），包含：
   - 三维正交分类框架说明（LP/CP/ES 维度定义）
   - LP×CP 速查矩阵 + ES 维度参考表
   - 原子模式索引表与融合模式索引表

2. **`{skilldir}/references/general_design_common_knowledge.md`** — 共性知识文件，包含：
   - 各平台（A3/A5/A6）硬件参数速查
   - 通用概要设计原则（D 轴全量处理、32B 对齐、多核切分策略等）
   - 三维分类参考表
   - 常用术语表

> 这两个文件是全局共用上下文，各模式文件不重复写入上述信息。

#### 3.2 提取三维分类特征

基于「加载上游决策记录 & 采集业务上下文」步骤采集的信息和 `op_spec`，提取当前算子的三维分类特征 + 属性参数：

**LP 循环结构模式**（核心判定要素——决定 tiling 策略和轴分析基架）：
```
类型: {全轴独立 / 索引间接 / 规约轴内嵌(非D轴) / D轴规约 / 范围迭代 / 矩阵乘积 / 选择排序 / 多阶段异构}
判定依据: {输出元素到输入元素的映射方式}
```

常见判定指引：
- 每个输出依赖 ≤1 个对应输入 → LP1(全轴独立)
- 含索引间接访存(Gather/Scatter) → LP2(索引间接)
- 沿非最后一维做 N→1 规约 → LP3(规约轴内嵌)
- 沿最后一维做全量规约 → LP4(D轴规约)
- 输出依赖某轴连续范围，需迭代累加 → LP5(范围迭代)
- 按[M,K,N]分形，内积轴积累 → LP6(矩阵乘积)
- 按值排序后选前K，输出位置不定 → LP7(选择排序)
- 计算流中不同阶段依赖拓扑变化 → LP8(多阶段异构)

**CP 计算通路**（决定硬件路径和瓶颈画像）：
```
硬件单元: {Vector / Cube / Cube+Vector / Vector多阶段}
瓶颈画像: {memory-bound / compute-bound / 按阶段分析}
核心操作: {简要描述}
```

**ES 执行结构**（决定模板结构和 workspace 需求）：
```
类型: {单次通过 / 遍历累加 / 多阶段WS / 多阶段UB内}
判定依据: {计算是单次过还是分多次、中间结果在哪}
```

**L1 张量签名**（属性参数——用于模式内部变体区分）：
```
输入: {数量}个, 角色: [{角色1}, {角色2}, ...]
输出: {数量}个, 角色: [{角色1}, ...]
维度语义: [{标签1}, {标签2}, ...]
```
角色取值：data / index / weight / mask / cache / bias
维度语义取值：[B, S, D] / [B, H, S, D] / [M, K, N] / ...

**L4 关键工程约束**（属性参数——标记同模式的变体差异）：
```
{约束名}: {取值}
```

**轴参算子识别（可配置计算轴）**：

判定：算子的拆分 / 计算 / 归约轴是**运行时属性**（如 `dim` / `axis`，通常带默认值如 -1、可在运行时取任意轴）而非固定轴，且算子语义沿该轴做 split / reduce / concat 等局部性敏感操作。

- 命中 → 标记为**轴参算子**，须在 `general_design.json` 填**可选**字段 `axis_param_design`（轴参泛化规格；字段结构见 schema example）。
- **`axis_param_design` 是必须被 template-division → tiling-buffer-kernel → codegen 全链实现的契约，不是可选装饰**。概设须为 **fast_path（dim=末轴，轴=最内连续维）与 generalization（dim≠末轴）两路径各自**给出可落地的 `tiling_data` 字段定义（字段名/类型/语义/取值来源）+ 循环结构骨架（`loop_sketch`）。`tiling_data` / `loop_framework` 须同时承载两路径（以路径标签分隔），**严禁只给末轴快路径**——只覆盖末轴会使 dim≠末轴 路径无落地设计，下游 host tiling 执行失败（EZ1008）。generalization 路径须明确 host 按 dim 推导的 GM 描述符字段（offset/stride/blockLen/blockCount）与 kernel strided CopyIn 规格。
- 非轴参算子（固定轴）不填 `axis_param_design`，设计照常。

#### 3.3 盲区预判（覆盖边界门，先于矩阵定位）⚠️

在 LP×CP×ES 矩阵定位前，先对照 `design_patterns.md`「框架覆盖边界与已知盲区」节做一次判定（三维框架是单 AI Core 核内坐标系，命中盲区不得假装覆盖）：

- 命中 **B1 跨卡集合通信**（AllReduce/AllGather/AllToAll/ReduceScatter，如 mc2 类）或 **B2 时间步递推**（`h_t=f(h_{t-1})` 串行状态，如 rnn 类）→ **强制 AskUserQuestion 声明限制**（话术与降级规则见盲区节），用户确认后仅对可分解计算部分继续，未覆盖部分在文档头部+「关键决策记录」显式标注。
- 命中 **B3 量化策略变体** → 不声明、不降级，量化粒度作为 L4 属性在差分清单中记录即可。

#### 3.4 基于速查矩阵的格-子定位与模式加载

**Step 1：判断是否为 LP8（多阶段异构）算子**

```
算子输入
  │
  ├── LP ≠ LP8 → 进入 Step 2（LP×CP 矩阵匹配 + ES 维度确认）
  │
  └── LP = LP8（多阶段异构）→ 子计算分解
        │
        ├── 分解为 SubOp 序列（每个 SubOp 独立判定 LP1~LP7）
        ├── 每个 SubOp 独立进入 Step 2（LP1~LP7 × CP1~CP5 × ES1~ES4 匹配）
        ├── 检查 SubOp 链是否匹配 patterns/fused/ 下的已知融合模式
        │     ├── 匹配 → 路径一（融合模式精确复用）
        │     │         加载 {skilldir}/references/patterns/fused/{模式文件}.md
        │     └── 不匹配 → 路径二·融合
        │           ├── 各 SubOp 的原子模式模板可复用
        │           └── 阶段编排从零设计
        └── 输出：融合设计路径标注
```

**Step 2：单计算算子的矩阵定位（非 LP8）**

基于 LP（Y 轴）× CP（X 轴）定位速查矩阵中的格子，再结合 ES 维度确执行结构：

```
读取 design_patterns.md 的 LP×CP 速查矩阵
  │
  ├── 命中格子（有对应的模式文件）
  │     │
  │     ├── 结合 ES 维度确认执行结构（参考 ES 分布表）
  │     ├── 加载 {skilldir}/references/patterns/atomic/{模式文件}.md
  │     ├── 比对三维特征
  │     │     ├── LP+CP+ES 全匹配 → 路径一（精确复用）
  │     │     ├── LP+CP 匹配       → 路径一·差分（ES 或 L1/L4 有差异）
  │     │     └── LP 不匹配        → 回退到路径二
  │     └── 输出路径标注 + 模式引用
  │
  └── 未命中格子（空单元格）
        │
        └── 路径二（从零构建）
              └── 输出路径标注 + 模式贡献建议
```

**路径判定三要素**：

```
要素 1: LP 循环结构模式 → 决定"tiling 策略和轴分析方案"（核心判定要素）
要素 2: CP 计算通路     → 决定"硬件路径和瓶颈画像"
要素 3: ES 执行结构     → 决定"模板结构和 workspace 需求"

→ LP+CP+ES 三要素全匹配 = 路径一（精确复用）
→ LP+CP 匹配（ES 不同） = 路径一·差分（执行结构有差异，模板结构需调整）
→ LP 不匹配 = 路径二（从零构建）
```

> **注意**：L1（张量签名）和 L4（工程约束）降级为属性参数，不再参与分类体系本身的三要素判定。但如果 L1（如输入输出数量、角色）存在本质差异（如单输入 vs 多输入），即使在同 LP/CP/ES 三元组内，也需要标记为差分点。

#### 3.5 输出分类结果

将设计路径分类以引导段落形式写入 `narrative` 字段（无独立结构化字段，归类信息供人读与下游参考，**注意此分类与 review 阶段 CR3 产出的 `general_design_level` 是不同概念**——后者由 review 判定概设详细度分级）：

**路径一 — 精确匹配**（`narrative` 内记录为）：
```
设计路径：路径一 — 精确匹配 → {模式名称}
三维分类：(LP={LP编码}, CP={CP编码}, ES={ES编码})
参考来源：references/patterns/atomic/{模式文件}.md
```

**路径一·差分**（`narrative` 内记录为）：
```
设计路径：路径一·差分 → {模式家族名称}
三维分类：(LP={LP编码}, CP={CP编码}, ES={ES编码})
差异点：[ES={实际值}≠{模式值}, L1={实际值}≠{模式值}]
参考来源：references/patterns/atomic/{模式文件}.md
```

**路径二**（`narrative` 内记录为）：
```
设计路径：路径二 — 未匹配模式
三维分类：(LP={LP编码}, CP={CP编码}, ES={ES编码})
参考来源：无
```

> **约束说明**：
> - 设计模式知识库是**参考性**而非**约束性**的。路径一只意味着"有相似算子的已知方案可用作起始点"，而非"必须遵循此模式"。
> - 即使走路径一，仍需要完整的差分分析（见「模板划分策略」步骤的差分分析），而不是简单复制。
> - 后续所有步骤（Tiling设计、Buffer/性能等）在两种路径下都执行，仅在设计和差分分析环节有差异。

#### 3.6 加载模式文件（仅路径一时）

路径一/路径一·差分命中模式文件后，按以下方式加载：

```
Step 1: 加载模式文件
         ├── 读分类无关层（三维分类标识 / 核心设计特征 / 模板结构）
         ├── 读 {目标平台} 实现要点（只读目标平台那一节，如 A3 或 A5）
         └── 忽略其他平台的实现要点

Step 2: 比对三维分类 → 确定路径一/路径一·差分

Step 3: 输出设计指导
         ├── 分类无关层用于匹配决策
         └── 平台相关层用于后续 Tiling 和模板推导

平台不支持时：
  - 如果模式文件中没有目标平台的章节
  - 输出警告："当前模式暂无 {平台} 实现要点，建议参考最近平台 + 手动适配"
```

#### 3.7 路径二增强处理（全新算子无匹配时的特殊流程）

当算子的 LP+CP+ES 三维分类与所有模式均不匹配时（路径二），不代表框架失效。按以下**从零构建流程**逐层推导，确保设计正确性：

```
路径二增强处理：从零构建流程（路径二专用）

① 轴行为分析（先于任何设计决策）
   ├─ 列出所有轴，标注各轴的计算角色：独立轴？广播轴？规约轴？搬运轴？
   ├─ 轴间关系：是否有轴合并的可能？轴间是否有数据依赖？
   └─ 输出：轴属性表 + 推荐轴抽象方案（XYZ vs 命名）

② 计算范式分类（无论多新，最终落在这几类或组合中）
   ├─ 逐元素？规约？矩阵乘？数据搬运？或若干种时序组合？
   └─ 输出：计算范式声明（确定后续瓶颈分析和模板结构基础）

③ 数据流建模（从数据源到最终输出）
   ├─ 每个数据在哪个存储层级操作？（GM / UB / L0A/L0B/L0C）
   ├─ 哪些数据是常驻的？哪些是流式的？
   └─ 输出：数据流拓扑图（文字 + Mermaid）

④ 模板候选构建（基于①②③，产出至少2个候选方案供比较）
   ├─ 每个候选方案的模板数量、mode分配策略、对齐分支策略
   ├─ 各候选的核心差异点
   └─ 输出：候选模板对比表（见「模板划分策略」步骤的输出格式）

⑤ AskUserQuestion 确认
   └─ 向用户展示对比表，确认首选方案进入后续步骤

此流程确保即使是最陌生的算子，也有一致的设计入口。
```

> **兜底原则**：当设计无法从模式知识库获得参考时，优先依赖① 轴行为分析、② 计算范式分类、③ 数据流建模的客观分析结果（这些基于算子自身的数学语义，与历史模式无关），避免强行"套用"不合适的已有模式。

### 步骤4：读取 op_spec，提取算子定义书内容

1. 读取 `requirement.json`
   - 验证规格完整性：数学公式/地址映射、张量规格、属性参数、接口签名
   - 不完整 → 提示用户补充或标记"待确认"

2. 提取以下内容作为「算子定义书」素材（落入 `narrative`，用于上下文追溯）：
   - 数学公式 / 地址映射逻辑（按 mode 分列，标注新增/存量）
   - 接口定义（aclnn API 签名 + 参数表）
   - 支持范围清单（dtype × layout × mode 矩阵）
   - 边界语义约定
   - 附录的 Golden 代码参考（如有）
   - 附录的典型 Shape 表（如有）

> **归一化层反向传播特殊处理**：当算子涉及归一化层（LayerNorm/GroupNorm/RMSNorm 等）的反向传播时，正向 forward 公式落入 `narrative`，**归一化层的梯度公式单独写入顶层 `gradient_formula` 字段**（供 review 的 CR2 链式法则对质）。

### 步骤5：确认芯片平台与硬件参数

1. 确认目标芯片平台（A2 910B / A3 910B / A5 351x / 其他）
2. 通过 `ascend-hardware` skill 获取以下硬件参数用于后续策略推导：
   - UB 总大小
   - AICore 数量
   - GM → UB 带宽
   - 向量宽度
   - 对齐要求（默认 32B）
3. **特别注意 A5 平台**：A5 采用 SIMT 编程模型（与 A3 的 SIMD 模式不同），确认后需参考 `general_design_common_knowledge.md` 中 2.6 节的范式转变说明，评估对当前算子概要设计的影响（循环结构简化、寄存器预算约束等）
4. **A5 + SIMT 特征 → 先查 SIMT 模式库再继续**：当算子结构命中 SIMT 信号（LP2 索引间接 /
   LP7 选择排序 / 条件分支密集，即 gather/scatter/动态索引/排序类语义）时，用 Skill 工具读
   `ascendc-simt-operator-design-patterns` skill（分核/模板路由/workspace 契约 + Kernel
   VF/线程映射/索引寻址/写冲突确定性谱系 + 13 类算子族速查），据此约束模板候选、workspace
   预留与线程映射等概设决策——不要仅凭 SIMD 时代的惯性定切分与循环框架。
5. 如有 `code_constraints.md`，读取其中的平台差异化约束

### 步骤6：策略卡检索与策略吸收（概设的策略来源）

在「架构设计」「Tiling 设计」「Buffer 与性能设计」三章落笔**之前**，用 `ascendc-strategy-card-select`
skill 做一次成熟策略检索，把命中的策略约束吸收进本次概设。这是**建议输入**，不是对需求文档或
已定架构的改写。

**触发与跳过**（三态，以「用户是否指定策略库」为准）：

- 若「概设完整性判断」步骤判定 pass-through（直接沿用既有概设），跳过本步骤。
- **未指定策略库**（`ASCENDC_STRATEGY_ROOT` 未设置且无 `--strategy-root`）：**跳过本步骤**，
  不调用 `ascendc-strategy-card-select`，直接按后续步骤正常分析。在 `narrative` 中留痕一句
  （如「策略卡检索未执行：未指定策略库」）即可——策略库是可选知识源，未指定**不得以任何
  方式阻塞或打停概设**（不重试、不等待、不当错误上报）。
- **指定但路径无效**（设置了但目录不存在）：这是用户显式意图的失败，**如实报告**——把报错
  原文（含路径与设置方法）写进 `narrative` 留痕，然后**继续**后续步骤完成概设（同样不阻塞）；
  是否修复路径后重跑由上游/用户决定，本步骤不代为猜测。
- **指定且有效**：**必跑**本步骤。

**类别判定**：按「算子设计模式匹配」步骤得出的三维分类（LP/CP/ES）**按数据流特征**映射到
策略库类目，**不得按算子名归类**：

| 数据流特征（来自三维分类） | 候选类别 |
|---|---|
| 全轴独立、逐点映射 | `elementwise` |
| 全轴独立、但含整量广播语义 | `broadcast` |
| 全轴独立、仅重排布局 | `layout-transform` |
| 索引间接取数（读侧） | `index-gather` |
| 索引间接写回（写侧、有冲突） | `scatter-update` |
| 沿某轴归约/范围迭代 | `reduction` |
| 组内/行内统计后归一化 | `normalization` |
| 定序选择 | `sort-select` |
| 多阶段异构、向量多流水融合 | `vv-fusion` |
| 多算子融合的端到端子图 | `fused-composite` |

**兜底**：数据流特征不足以判定、或落在词汇表预留但**尚无卡片**的类时，用 `common` 池
（跨类通用卡，是唯一不对数据流作假设的池），并**把「类别不确定」作为设计歧义上报**，
而非静默选一个类。

**执行**：用 Skill 工具读 `ascendc-strategy-card-select`，按该 skill 的 Phase 0–4 逐步执行；
工作目录 `<workdir>/strategy_selection/`。输入的设计文档用本次概设的上游输入
（`requirement.json`，如有 `existing_general_design.md` 一并提供）。

**执行自检（进入步骤7 前必须逐条确认，不满足则先补做本步骤）**：

1. 已实际调用 `ascendc-strategy-card-select`（不是仅读取其 SKILL.md 正文）。
2. `<workdir>/strategy_selection/selection.json` 已落盘。
3. `narrative` 中已写明本步骤的结论 —— 吸收的策略条目，或"无适用成熟策略"，或跳过原因。

若三者任一不满足而策略库已指定且有效，即为**本步骤未完成**，不得进入步骤7（未指定/路径
无效的跳过态除外——见「触发与跳过」，跳过态只要求 narrative 留痕）。

**产物**：`strategy_selection/selection.json` + `selection_report.md`（人读报告）+ 
`strategy_usage.log`（使用留痕：选中→逐条 `USED`；无命中→`REASON` 原因说明——由 finalize
门禁通过后自动追加，不须手写），以及冻结的 `query.json` / `screening.json` /
`verification.json`。本步骤**不新增**本 skill 的 stage 产物——概设的唯一机器产物仍是
`general_design.json`。

**如何约束下游**（吸收方式）：对最终选定的 ≤3 条策略（`applicable=true`），逐条把它约束到
对应的结构化节点，并写进 `narrative` 的关键决策记录：

| 策略内容 | 约束到的节点 |
|---|---|
| 适用条件 / 正确性红线 | `split_axis_priority`（并行分解策略） |
| 实施要点 | `tiling_data`（TilingData 字段定义）、`loop_framework`（循环框架） |
| 代价（UB 占用 / 同步翻倍 / 寄存器压力） | `buffer_eval`（Buffer 共存约束），并作为权衡表的显式候选 |

每条都要写清依据、条与条之间的主次/冲突关系，以及风险与回退。若 `applicable=false`，在
`narrative` 中如实写"无适用成熟策略"，**不编造**。（「未指定策略库」的跳过态按「触发与跳过」
留痕，不写"无适用成熟策略"——两者语义不同，不得混写。）

**边界**：策略只影响**已定架构下的落地细节**，**不得**据此重开架构选型（架构是需求文档的既定
输入），也不得覆盖 `requirement.json`。策略结论不构成对需求文档的重解释。

### 步骤7：生成「算法背景与需求」章

将「算法背景与需求」内容（业务背景 / 算子生态现状 / 需求清单）写入 `narrative`：用「加载上游决策记录 & 采集业务上下文」步骤采集的信息 + 「确认芯片平台与硬件参数」步骤的平台信息填充。重点：业务痛点（含 profiling 数据如有）、生态对比表、编号需求清单（功能 + 性能 + 兼容性约束）。在 `narrative` 内以子标题保留段落结构以便人读。

### 步骤8：生成「架构设计」章 ⭐ 核心步骤

> 本步骤整体落笔目标：**7.4 并行分解策略**的多核切分轴优先级 → 顶层字段 `split_axis_priority`（CR1 强校验）；其余子节（计算流程/数据流拓扑/轴分析/模板划分策略/差分分析）作为支撑性推导，落入 `narrative`。

#### 7.1 计算流程
按 mode 分别绘制 Mermaid 流程图，标注核心数据变换（生成方式、后续引用方式）；modifier 特性（部分数据处理、mask 等）标注其在流程中的位置。→ `narrative`

#### 7.2 数据流拓扑
标准路径数据流（GM → UB → Compute → UB → GM）+ 特殊 code path（如 rotate 矩阵路径用 Cube）；每个节点标注存储层级（GM / UB / L0A / L0B / L0C）。→ `narrative`

#### 7.3 轴分析
逐维度列轴属性表（维度 / 语义 / 独立轴？ / 广播轴？ / 核间通信？ / 切分优先级）；给出合轴策略（相邻非广播轴是否合并、广播轴如何处理）与轴抽象方向（XYZ 抽象 vs 具体命名，视复杂度定）。→ `narrative`

#### 7.4 并行分解策略
- **多核切分轴优先级** → 写入顶层字段 `split_axis_priority`（数组形式，如 `["N", "C"]`，表达切分轴的优先顺序）
- 切分单元分配（AICore Vector 单元 / Cube 单元）、核间关系（无通信 / AllReduce / Gather 等）→ `narrative`
- **不给出** blockIdx 映射公式

#### 7.5 SIMD/SIMT 编程模型判定 ⭐（A5 路径执行）

> 目标平台为 **A5（Regbase/SIMT 代，950PR/950DT）** 时，在「模板划分策略」之前判定
> 算子编程模型（SIMD / SIMT / MIXED），使模板划分、Tiling 设计、Buffer 评估全部按判定
> 结果产出。A2/A3（Membase/SIMD 代）**跳过本步骤**：平台锁定 SIMD（能力规则 C-01），
> 在 `narrative` 关键决策记录中标注"平台锁定 SIMD（C-01）"即可，不产出
> `template_decision.json`。

1. **调用 `ascendc-op-design-template-select` skill**（Skill 工具，其方法论已在本会话加载）。
2. **输入**（会话上下文直接可读 + cwd 文件；不落盘中间文件、不做调用摘要）：
   - 会话上下文：7.1 计算流程（算法逻辑/计算阶段）、7.2 数据流拓扑（访问模式：
     连续/索引/随机）、7.3 轴分析（写冲突/数据规模结构）、7.4 并行分解（原子操作）；
   - cwd 文件：`requirement.json`（op_spec 张量角色/dtype/公式、确定性要求）、
     `hw_params.json`（chip_code → C-01 平台规则）。
3. **判定产出**（写入当前工作目录）：`template_decision.json`
   （`recommendation` = SIMD / SIMT / MIXED；MIXED 时 `routing` 给出 SIMD 性能路径 +
   SIMT 兜底路径的 shape 路由条件）。
   按该 skill 的 schema（`schema/template_decision.json`）与自检项执行。
4. **判定结果用于后续步骤**：
   - MIXED 时「模板划分策略」步骤**必须覆盖 SIMD 性能路径 + SIMT 兜底路径**（性能路径不可遗漏）；
   - 「Tiling 设计」步骤按模型写循环结构（SIMD 嵌套 for / SIMT 线程映射）与 TilingData 字段集；
   - 「Buffer 与性能设计」步骤按模型算（SIMD → UB 共存约束；SIMT → 寄存器预算 + DCache 预留）。
5. **冲突处理**：若「算子设计模式匹配」步骤的 LP 倾向与判定结论不一致，**以判定结论为准**
   （R 规则为 SIMD/SIMT 判定的唯一权威）；`confidence=low` 且信息不足时经
   AskUserQuestion（resolve_ambiguity）确认。

> **边界**：本步骤只判编程模型（SIMD/SIMT/MIXED），**不涉及模板**——模板数量、结构、
> TilingKey 路由是「模板划分策略」步骤与详设 template-division 的职责；`vf_split`
> （VF 段级拆分）首版不产出/不消费。

### 步骤8：生成「模板划分策略」章 ⭐

> 全部落入 `narrative`（无独立结构化字段——模板候选/差分分析属设计推理过程，非 CR1 强依赖节点）。

**两条路径的起点**：

- **路径一（匹配到历史模式）**：以 `patterns/atomic/` 或 `patterns/fused/` 中对应模式文件的核心设计特征和切分策略为起始点，做差分分析（见下方"差分分析"段落）后输出候选方案。
- **路径二（自由发挥）**：按下方"判断依据"逐项分析，从零构建候选方案。

**判断依据**（路径二从零构建时使用，路径一也可用以验证差分点）：
1. 各 mode 的计算流程是否有本质差异？
   - 如果依赖同一核心计算路径（仅有参数差异） → 可合并为同一模板的不同分支
   - 如果计算流程完全不同（如不同数据排布、不同操作类型） → 独立模板
2. modifier / 特殊边界处理：
   - 是 modifier（在各模板内部增加 if 分支判断）还是独立模板（当影响 Tiling 切分计算方式或改变数据流拓扑时）？
3. Layout 泛化方案：
   - BNSD/BSND/SBND/TND 不同排布是否合并统一处理？
   - XYZ 轴抽象 vs 各 layout 独立模板？
4. 对齐场景：
   - 32B 对齐 vs 非对齐是否需要独立模板分支？
5. **硬件平台差异化**（见「确认芯片平台与硬件参数」步骤确认的硬件参数，平台差异详见 `general_design_common_knowledge.md`，**特别注意 A5 的 SIMT 编程模型**）：
```

**差分分析**（仅路径一使用，以命中的模式文件为参照，逐项检查差异）：

```
差分分析模板（以 `patterns/atomic/{模式文件}.md` 或 `patterns/fused/{模式文件}.md` 中的条目为参照）：
┌────────────────────────────────────────────────────────────────┐
│ 检查项                    │ 模式的特征 │ 本算子的特征 │ 结果  │
│──────────────────────────│───────────│─────────────│──────│
│ 【三维分类】                                                     │
│ LP 循环结构模式            │ {来自模式}  │ {本算子}      │ 一致/差异│
│ CP 计算通路                │ {来自模式}  │ {本算子}      │ 一致/差异│
│ ES 执行结构                │ {来自模式}  │ {本算子}      │ 一致/差异│
│ 【强制差分因素清单（逐条必填，见 design_patterns.md 同名节）】     │
│ 输入输出数量/角色          │ {来自模式}  │ {本算子}      │ 一致/差异│
│ 广播轴存在与位置           │ {来自模式}  │ {本算子}      │ 一致/差异│
│ 变长/动态 shape           │ {来自模式}  │ {本算子}      │ 一致/差异│
│ Mask 存在                 │ {来自模式}  │ {本算子}      │ 一致/差异│
│ Layout 集合               │ {来自模式}  │ {本算子}      │ 一致/差异│
│ 对齐场景                  │ {来自模式}  │ {本算子}      │ 一致/差异│
│ 【结构/模板差分】                                                │
│ modifier 嵌入 vs 独立     │ {来自模式}  │ {本算子}      │ 一致/差异│
│ 轴抽象方案（XYZ vs 命名）  │ {来自模式}  │ {本算子}      │ 一致/差异│
│ 多核切分主/次轴            │ {来自模式}  │ {本算子}      │ 一致/差异│
│ 典型循环结构               │ {来自模式}  │ {本算子}      │ 一致/差异│
│ TilingData 增减字段       │ {来自模式}  │ {本算子}      │ 一致/差异│
│ ───────────────────────── │              │              │        │
│ 结论：继承 {X} 项，调整 {Y} 项，新增 {Z} 项                   │
└────────────────────────────────────────────────────────────────┘
```

> L1（张量签名）、L4（工程约束）已拆解为上表【强制差分因素清单】各行（输入输出数量/角色、变长、Mask、Layout、对齐等），逐条判定，不再以单行"L1/L4"笼统带过。

**差分分析的输出方式**：
- **强制要求**：无论差异项多少，【强制差分因素清单】的每一项都必须在差分表中显式标注一致/差异——不允许因"差异少"而省略任何一项。
- 凡判定为"差异"的项，须在 `narrative` 内（关键决策记录段落）逐条记录其对设计的调整理由（调整了哪个模板/buffer/切分决策、为什么）。
- 完整差分表保留在 `narrative` 内（架构设计·模板划分策略段落），作为路径一/路径一·差分的可追溯依据。

输出候选模板列表，格式：
```markdown
| 候选模板 | 支持的 mode | 支持的 layout | 对齐要求 | 核心差异 | 候选 TILING_KEY 范围 |
|---------|------------|-------------|---------|---------|-------------------|
| ...     | ...        | ...         | ...     | ...     | ...               |
```
（上表落入 `narrative`）

### 步骤9：生成「Tiling 设计」章 ⭐ 核心步骤

> 本步骤落笔目标：**9.2 TilingData 字段定义** → 顶层字段 `tiling_data`；**9.3 各模板循环结构** → 顶层字段 `loop_framework`（两者均 CR1 强校验）；9.1/9.4 落入 `narrative`。
> **编程模型驱动**：循环结构与 TilingData 字段集按「SIMD/SIMT 编程模型判定」步骤的
> `recommendation` 写——SIMD 走嵌套 for + ubLoopNum 类字段；SIMT 走线程映射（无显式循环）
> + vfBlockDim/寄存器预算类字段。

#### 9.1 Tiling 级数与切分策略
确定几级 Tiling（通常 Core-level + UB-level）、每级切分维度与切分逻辑类型（动态等分 / 静态循环）；标注边界条件：下限（至少 1 个完整 head）、上限（UB 空间上限）、对齐（32B）。→ `narrative`

#### 9.2 TilingData 字段定义
写入顶层字段 `tiling_data`（数组形式，每项含 `field`/`dtype`/`semantic`/`source`）。参考格式：
```markdown
| 字段名 | 类型 | 语义描述 | 取值来源 |
|--------|------|---------|---------|
| X | int64_t | x 输入 shape 的 X 维大小 | input shape |
| blockNumX | int64_t | X 维多核切分的核数 | 核数分配公式 |
| ubLoopNumX | int64_t | X 维 UB 切分的循环次数 | UB 空间计算 |
| ... | ... | ... | ... |
```
**不给出**默认值和序列化代码。

> **规约类算子累加方式条款**：沿规约轴计算 sum/mean/var 的算子，概设须在「对齐策略」或
> `narrative` 的 Tiling 设计节**显式声明累加方式**（二分/顺序）。A5 平台规约轴全载时命中
> 二分累加（判据见 `ascendc-op-design-shared/references/a5_regbase_design.md`
> 「树形/二分累加设计要点」节），`tiling_data` 必须包含**二分折叠点字段**（`fold_point`，
> 整数法取 R 向下最近的 2 的幂）及其派生的二分中间结果 tmp 空间依据（并入 ub_factor 估算）。

#### 9.3 各模板循环结构 ⭐
写入顶层字段 `loop_framework`（字符串形式，承载各模板嵌套循环伪代码；多模板时以注释分隔）。为每个模板绘制 Mermaid 流程图或伪代码嵌套结构：

```c
// 以模板A为例的多核+核内循环框架
xBlockIdx = (blockIdx 分配方式在此描述)
zBlockIdx = (blockIdx 分配方式在此描述)

for (xIdx = 0; xIdx < ubLoopNumX; xIdx++) {
    for (zIdx = 0; zIdx < ubLoopNumZ; zIdx++) {
        CopyInA(offset=..., size=[xSize, zSize, D]);    // 常驻/广播数据
        for (yIdx = 0; yIdx < ubLoopNumY; yIdx++) {
            CopyInB(offset=..., size=[...]);             // 主输入
            ComputeElementwise(inA, inB → out, size=[...]);
            CopyOut(out, offset=..., size=[...]);
        }
    }
}
```
**不代入** ubFactor 具体数值和 blockIdx 映射公式。

#### 9.4 对齐策略
D 维度未 32B 对齐时的 DataCopyPad 方案；判断非对齐场景是否需要独立模板分支。→ `narrative`

> **reduce 类算子强制条款**：若使用 `ReduceSum`高阶归约 API，A2/A3 上 `srcInnerPad` 当前**只支持 true**（最内层 reduce 轴数据必须 32B 对齐）。当 reduce 最内层轴元素数非 32B 对齐时，`narrative`「对齐策略」节须明确补零策略（DataCopyPad 尾部补零）。完整约束与范式见 `ascendc-op-design-shared/references/reduce_align_strategy.md`（A5 Regbase 不适用，见 `a5_regbase_design.md`）
> **二分累加尾块补零联动**：命中二分累加的规约设计（见「TilingData 字段定义」的累加方式条款），尾块不足一个 VL 的部分**必须**保证归约前为 0——DataCopyPad 开 isPad，或 kernel 内尾 mask 清零；本节须写明所采用的补零路径（红线 RG-B1，见 `a5_regbase_design.md`）

### 步骤10：生成「Buffer 与性能设计」章

> 本步骤落笔目标：**10.1 Buffer 可行性评估** → 顶层字段 `buffer_eval`（CR1 强校验）；10.2/10.3 落入 `narrative`。
> **编程模型驱动**：可行性评估按「SIMD/SIMT 编程模型判定」步骤的 `recommendation` 算——
> SIMD → UB 共存约束；SIMT → 寄存器预算（每 VF ≤32 RegTensor）+ DCache 预留。

#### 10.1 Buffer 可行性评估（仅约束提供）

> 概设只负责验证 tiling 策略在 UB 容量下是否可行，不负责具体 Buffer 布局。本节产物 → 顶层字段 `buffer_eval`（对象形式，含共存约束清单/常驻流式判定/融合阶段共存验证结论）。

- **共存约束清单**：列出各模板中必须同时驻留 UB 的数据项（输入、中间结果、常驻数据），每项给出类型和估算大小（参数级表达式，如 `sizeof(half) * D * X`）
- **常驻 vs 流式定性判断**：基于数据复用距离（同一数据被反复使用的频率），定性判断哪些应常驻、哪些应流式。不做具体 Buffer 分配
- **融合算子阶段共存验证**（融合模式时）：各阶段 UB 占用总和 ≤ 目标平台 UB 容量。如果超标，标注"需拆分阶段或减小 tile 粒度"

> **输出示例**：
> ```markdown
> **模板A 共存约束**：输入x(half[D×X]) + 广播cos(half[D]) + 输出y(half[D×X]) = 总 UB 需求 (2X+1)×D×2B
> → 当 X=1 时：(2+1)×128×2 = 768B，远小于 UB 上限（ub_size_bytes，见 hw_params.json） ✅
> → 当 X=128 时：(256+1)×128×2 = 65.8KB，小于 UB 上限（ub_size_bytes，见 hw_params.json） ✅
> → 结论：所有典型 shape 下均可行，无需沿 D 轴切分
> ```

#### 10.2 关键性能设计权衡 ⭐
如有多方案，进行结构化的 trade-off 分析。→ `narrative`

```markdown
| 方案 | 描述 | 优点 | 缺点 | 推荐？ |
|------|------|------|------|--------|
| 方案1 | ... | ... | ... | |
| 方案2 | ... | ... | ... | ⭐推荐 |
```

常见权衡场景举例：
- 多元输入处理：多路输入数据的搬运策略对比（合并搬运 vs 分别搬运 vs 按需加载）
- 广播数据处理：常驻 UB vs 随行按需加载的权衡
- 跨步访存策略：DataCopy+Gather 方案 vs 多次连续 DataCopy+UB重排方案
- interleave 模式：跨步访存的数据重排用 DataCopy 还是 L1 辅助？
- cos/sin 广播：常驻 UB 还是随行按需加载？

#### 10.3 计算范式与瓶颈分析
- 主导范式判定（逐元素 / 规约 / 矩阵乘 / 混合）
- 算术强度估算（参数级表达式，不代入具体数值）
- 瓶颈类型标注（计算受限 / 带宽受限）

→ `narrative`

### 步骤11：生成「可行性论证」章

将「可行性论证」内容写入 `narrative`：
- **6.1**：用参数级表达式（如 `O(B*N*S*D)`）推导计算量与访存量 + 算术强度公式，**不代入**具体数值。
- **6.2**：基于算术强度与硬件计算密度拐点对比断言瓶颈类型，给出理论效率上限范围。
- **6.3**：识别边界场景（极小 shape、极大 D、特殊 dtype、广播效率），标注需详设专项处理的场景及缓解建议。

### 步骤12：采集附录内容

将附录内容写入 `narrative`：A.Golden 代码（从 requirement.json 测试/代码路径或用户提供）、B.典型 Shape（从业务背景采集）。材料不可获取时通过 AskUserQuestion 请求用户提供。C.关键决策记录由各推导步骤（含差分分析）的差异项汇总而来。

### 步骤13：组装文档

按以下结构组装 `general_design.json`（Write 一次性写出）：

- `op_name`：算子名（来自 requirement.json）
- `split_axis_priority`：来自「并行分解策略」步骤的多核切分轴优先级（数组）
- `tiling_data`：来自「TilingData 字段定义」步骤的字段定义（数组，每项含 `field`/`dtype`/`semantic`/`source`）
- `loop_framework`：来自「各模板循环结构」步骤的嵌套循环伪代码（字符串，多模板以注释分隔）
- `buffer_eval`：来自「Buffer 可行性评估」步骤的共存约束/常驻流式判定/融合阶段验证（对象）
- `gradient_formula`（可选）：来自「读取 op_spec」步骤——当涉及归一化层反向传播时填入归一化层梯度公式，否则省略
- `narrative`（可选）：拼接其余所有人读/CR3 扫描内容——按八段式内容组织（算法背景与需求 / 算子定义书素材 / 架构设计计算流程·数据流拓扑·轴分析·模板划分策略·差分分析 / Tiling 级数·对齐策略 / 性能权衡·瓶颈分析 / 可行性论证 / 附录），段落内保留子标题结构以便人读与 review CR3 扫描

### 步骤14：质量自检

检查以下各项：

- [ ] `split_axis_priority` 字段存在且为非空数组（多核切分轴优先级）？
- [ ] `tiling_data` 字段存在且为非空数组（TilingData 字段定义）？
- [ ] `loop_framework` 字段存在且为非空字符串（各模板循环结构伪代码）？
- [ ] `buffer_eval` 字段存在且为非空对象（Buffer 可行性评估）？
- [ ] **规约累加方式声明（规约轴 mean/var 类算子必查）**：`narrative` 是否显式声明累加方式（二分/顺序）？A5 全载命中二分累加时，`tiling_data` 是否含折叠点字段（`fold_point`）且二分 tmp 空间已并入 ub_factor 估算依据？尾块补零路径是否已在「对齐策略」写明？（判据与红线见 `a5_regbase_design.md`「树形/二分累加设计要点」）
- [ ] **轴参算子路径覆盖度**：若为轴参算子（含 `axis_param_design`），fast_path（dim=末轴）与 generalization（dim≠末轴）两路径是否**各自**都有可落地的 `tiling_data_fields[]` + `loop_sketch`？只给末轴快路径 = 自检失败（会导致 dim≠末轴 路径下游 host tiling 执行失败 EZ1008）。非轴参算子跳过此项。
- [ ] **梯度公式自检（仅当产出 `gradient_formula`）**：归一化层反向传播的梯度公式中，若存在修正项（减法右侧消除位置间耦合的项），该项须是与当前输出位置无关的标量（不含位置下标 `i`/`p`/`j`）；若修正项仍含位置下标 → 公式有误，从链式法则重新推导后覆写 `gradient_formula`
- [ ] `narrative` 内已标注设计路径（路径一/路径一·差分/路径二）？
- [ ] **盲区预判是否已执行？** 若命中跨卡通信（B1）/ 时间步递推（B2）盲区，是否已通过 AskUserQuestion 向用户声明框架限制，且 `narrative` 内（含关键决策记录段）已显式标注未覆盖范围？（不允许静默跳过或假装覆盖）
- [ ] 路径一/路径一·差分时，模式文件是否已正确加载并引用？
- [ ] 路径一·差分时，差分分析是否已完成？差异点是否已自动生成为差分检查清单？
- [ ] **强制差分因素清单是否每一项都已在差分表中显式判定一致/差异？（不允许省略）** 凡判为差异的项，是否已在 `narrative` 关键决策记录段中记录调整理由？
- [ ] `narrative` 是否包含算法背景与需求（业务背景 + 需求清单）？
- [ ] `narrative` 是否包含模板划分策略候选方案？
- [ ] `narrative` 是否包含关键性能设计权衡分析？
- [ ] `narrative` 是否包含可行性论证（理论估算和风险标注）？
- [ ] `narrative` 是否包含附录（Golden 代码和典型 Shape）？
- [ ] **化简/降维/等价声称验证（主动验证）**：若设计含"化简/降维/等价/复用/覆盖"声称（如"任意 perm 降维为 2D""reshape 等价"），**优先写并运行 Python 验证（对照 golden）**：把声称操作化为可运行代码（用 `ascendc-op-design-shared/references/design-math-claims/verify_simplification_claim.py` 骨架），对 golden 穷举/随机核验，得到"声称支持域 vs 实测可覆盖域"。必须给出①`support_domain`（形式化支持域）+ ②验证方式与证据（穷举范围 / 随机 N / 引用 `ascendc-op-design-shared/references/design-math-claims/verified_facts.md`）+ ③与 golden 域对比结论 + ④残余风险进 `known_limitations`。**禁止裸描述；禁止把"跑过 Python"冒充"已证明"**。脚本跑不通/被证伪 → 先 agent 内部多轮自修（§2.9），多次尝试后仍不行才标 `known_limitations` 继续，**不 halt**。方法与判据详见 `ascendc-op-design-shared/references/design-math-claims/claim-verification-checklist.md`。
- [ ] **SIMD/SIMT 判定自检（「SIMD/SIMT 编程模型判定」步骤）**：
  - [ ] A5 路径：`template_decision.json` 已产出且通过其 schema 校验；A2/A3 路径：`narrative` 关键决策记录已标注"平台锁定 SIMD（C-01）"
  - [ ] 「Tiling 设计」的 `loop_framework` / `tiling_data` 与 `recommendation` 一致（SIMD 嵌套 for / SIMT 线程映射）
  - [ ] MIXED 时「模板划分策略」候选含 **SIMD 性能路径 + SIMT 兜底路径**（性能路径未遗漏），`routing` 条件已记录
- [ ] **边界红线检查**：
  - [ ] 是否有 ubFactor 具体数值或 blockIdx 映射公式？（禁止）
  - [ ] 是否有 BUFFER_NUM 或 TQue/TBuf 具体分配？（禁止）
  - [ ] 是否有函数实现代码或 C++ 模板参数？（禁止）
- [ ] 各结构化字段值与 `narrative` 推导是否为"参数级表达式"而非"代入具体 shape 的数值计算"？
- [ ] `narrative` 内交叉引用是否全部为名称制（无 §N / 第N章 / 步骤N 形式的语义引用）？
- [ ] **策略检索是否已执行或已留痕？** 「策略卡检索与策略吸收」步骤要么已跑且产出 `strategy_selection/selection.json`，要么已在 `narrative` 显式中标注跳过原因（pass-through / 策略库未挂载）——不允许静默略过。
- [ ] **选定策略是否已落到具体节点？** 若 `applicable=true`，选定的 ≤3 条策略是否逐条说明了各自约束 `split_axis_priority` / `tiling_data` / `loop_framework` / `buffer_eval` 中的哪一项，并写清主次与回退？`applicable=false` 时是否已如实写明"无适用成熟策略"而非编造？
- [ ] **策略是否越界？** 选定的策略是否只影响**已定架构下的落地细节**，未据此重开架构选型、未覆盖 `requirement.json`？
- 自检失败 → 就地修正直到通过，不自检通过则不允许结束
- 自检通过后，在 `narrative` 末尾追加自检摘要文本（不写入 checkpoint 文件）：
  ```
  general-design self-check: passed。
  ```

## 知识引用策略

通用知识引用策略（三层优先级 + 禁止猜测 + AskUserQuestion 兜底）详见 `ascendc-op-design-shared/references/knowledge_policy.md`。

本 skill 特有的查询场景：

| 层级 | 查询场景 | 对应执行步骤（名称制） |
|------|---------|-------------|
| Tier 1 | 目标芯片的 UB 大小、核数、带宽、向量宽度（用于 Tiling 原则边界条件、Roofline 估算） | **确认芯片平台与硬件参数** 步骤、**架构设计** 步骤、**可行性论证** 步骤 |
| Tier 1 | SIMD/SIMT 编程模型判定规则（C-01 / R-01~R-07）、MIXED 路由策略、平台能力约束 | **SIMD/SIMT 编程模型判定** 步骤（经 `ascendc-op-design-template-select` skill） |
| Tier 2 | 类似算子的设计模式参考、Tiling 策略选择、瓶颈类型判断、通信模式选择 | **策略卡检索与策略吸收** 步骤、**并行分解策略**（在「架构设计」步骤内）、**Tiling 设计** 步骤、**计算范式与瓶颈分析**（在「Buffer 与性能设计」步骤内） |
| Tier 3 | 具体 API 可用性、存储层级细节、数据格式转换开销 | **数据流拓扑**（在「架构设计」步骤内）、**Tiling 级数与切分策略**（在「Tiling 设计」步骤内） |

**查询约束**：
- 按需查询，不做全量加载
- 查询结果仅用于策略级决策支撑，不用于推导具体实现

## 文档维护约定（引用纪律）

本文档及其 `references/` 下文件的章节/步骤**标题采用连续编号**；任何增删章节/步骤后，必须对其后所有受影响标题**重新连续编号**（不留空号/跳号）。所有**交叉引用一律用名称**（如「模板划分策略」步骤、「Buffer 可行性评估」节），不得用编号（§N / 第N章 / 步骤N）——这样重编号只改标题，名称引用不受影响。

> 例外：对**生成的概设输出**（`general_design.json`）八段式内容组织的描述性引用，因内容组织方式固定、不随本 skill 重编号变动，可保留段名。
