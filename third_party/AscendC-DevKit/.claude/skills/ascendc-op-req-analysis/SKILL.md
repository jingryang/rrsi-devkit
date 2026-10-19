---
name: ascendc-op-req-analysis
description: 从算子语义描述（公式或地址映射逻辑）和 Golden 代码中提取算子规格，输出 requirement.json 结构化规格，为概要设计提供完整输入
triggers:
  - 需求分析
  - req-analysis
  - 算子规格分析
---

# AscendC 算子需求分析（增强版）

## 职责

从算子语义描述和 Golden 代码中提取算子规格，输出 `requirement.json`（结构化规格模型，供概要设计直接读取）。

支持两种工作模式：
- **标准模式**：从公式/Golden/代码推导算子规格（默认）
- **`--from-general-design` 模式**：从已有概设文档提取 `requirement.json`

## 输入

### 标准模式

- 算子语义描述（以下任一形式均可）：
  - 数学公式（计算类算子，如 LayerNorm、Softmax）
  - 地址映射/索引逻辑描述（搬运类算子，如 Gather、Scatter、Transpose、Pad）
  - 功能描述文档或概设文档中的相关章节
- 算子的 ACLNN 接口名（必填）：从用户输入照抄进顶层 `aclnn_name`，缺失时向用户确认，不推断
- Golden 代码路径（Python/C++ 参考实现）
- [可选] 类似算子代码路径
- [可选] 输入取值范围声明：有则照抄进 `inputs[].value_range`，没写则不写该字段

### `--from-general-design` 模式

- `{workdir}/general_design.json`（必须存在）
- 此模式下不需要用户提供 Golden 代码或数学公式文件；所有规格从概设文档提取

## 参数

| 参数 | 说明 |
|------|------|
| `--from-general-design` | 从 `general_design.json` 提取规格（见下文） |

## 输出

| 文件 | 格式 | 用途 |
|------|------|------|
| `{workdir}/requirement.json` | JSON | 供下游概要设计 Skill 直接读取的结构化规格模型（工程层 RequirementStage 读此文件） |

输出格式机器校验契约见 `schema/requirement.json`（required_keys: `op_name, aclnn_name, mutation_mode, inputs, outputs, golden_alignment`，含 example）；字段语义详解见 `references/op_spec_schema.md`。

**`domain` 字段（golden 域形式化声明，供 codegen 域对质）**：产出 `domain`（结构化，词汇表见本 skill `schema/requirement.json` 的 example）：`rank{min,max}` / `inputs[].dtypes` / `attrs[].domain{kind,constraint}`。从 golden 事实派生（rank 界、dtype 集、attr 值域）。attr domain kind 用 canonical 集（当前 `permutation`: `any`|`cyclic_rotation`；新 kind 可扩展，判据=结构信号不认算子名，§1.12）。**golden 支持"任意 X"就如实写 `any`**——不缩水，缩水会被 codegen 域对质抓到（设计 support_domain 若比它还窄 → gap 信号）。

## 算子类型判定

启动时先判定算子类型，后续步骤按类型分支执行：

| 类型 | 特征 | 典型算子 |
|------|------|---------|
| 计算类 | 有数学公式，输出值由输入值经计算得到 | LayerNorm, Softmax, RoPE, Activation |
| 搬运类 | 无数学公式，输出值等于输入值，核心是地址映射 | Gather, Scatter, Transpose, Pad, Concat |
| 混合类 | 既有地址映射又有计算 | GatherPaKvCache（gather + rope） |

## 算子写法特性（mutation_mode）判定

每个算子必填顶层 `mutation_mode` 字段（`in_place` / `out_of_place`），描述算子写法特性、决定 plugin 交付契约。**权威源是 golden**：mutation 语义以 golden.py 的读写行为为准，需求描述作辅助印证；判据如下：

| mutation_mode | 判据（读 golden） | 结构特征 | plugin 交付 |
|---|---|---|---|
| `in_place` | golden 中某个**入参张量**被更新后作为输出返回（其结果语义上就是该入参的原地更新）——该入参即状态张量；requirement 的 outputs 里以**与该 input 同名**的张量表示它 | 存在与某输入同名的状态输出张量 | 同名状态张量 clone 后 return（禁 `copy_` 写回调用方原张量本体） |
| `out_of_place` | golden 产出与所有入参都不对应的独立新结果并 return | 输出名与所有输入名不相交 | 直接 return output |

> 判定以 golden 为源头：读 golden 弄清"哪个（若有）输出在语义上是某入参的更新"，再把该关系**忠实转写**成 requirement 的 inputs/outputs 命名（in_place 状态张量在 inputs 与 outputs 中同名）。
> 注意 golden 常对入参先 `clone()` 再更新再 return（避免污染评测共享输入）——**clone 是交付实现细节，不是分类依据**；是否 in_place 看"返回值语义上是否某入参的更新"，不看运行期是否真改了入参对象。
> per-tensor 读写不再单列 `access_mode`，由 inputs/outputs 同名关系隐式定义（同名=read_write、仅 input=read_only、仅 output=write_only）。
> 自洽：`in_place` ⇔ 存在同名 input-output 对。写入 requirement.json 顶层 `mutation_mode`（必填，加载期校验）。golden 语义模糊或与需求描述冲突 → `resolve_ambiguity` 问用户（默认以 golden 为准）。

## 执行步骤

### 标准模式

0. **确认输入来源**：

   - AskUserQuestion：请提供算子语义描述的来源（数学公式文件、功能描述、或直接粘贴）
   - AskUserQuestion：请提供 Golden 代码路径（Python/C++ 参考实现）

   > 注：工程模式下，目标平台 / 公式 / Golden 路径等通常已由上游 requirement stage 经 prompt 上下文注入；上述提问仅在信息缺失时触发。

1. **判定算子类型**（计算类 / 搬运类 / 混合类）

2. **目标芯片确认**（基于已确定的 design_target_chip，不自行决议）：
    - design_target_chip 由需求文档顶层 YAML 字段或 CLI/入口决定（见 op_spec_schema）；**不得**自行决议目标芯片、不得写入 constraints（P81 step-58：agent 产的 constraint 不作为 chip 来源，防照搬示例污染）
    - 基于已确定的 design_target_chip，通过 `ascend-hardware` skill 查询硬件参数（UB 大小、核数、带宽、L1/L0C 大小等，禁止硬编码默认值）

3. **提取算子语义**：
   - **计算类**：读取数学公式，提取所有计算变体/分支、参数语义和取值范围
   - **搬运类**：读取地址映射逻辑，提取索引计算规则、边界处理策略、padding 值
   - **混合类**：分别提取计算部分和搬运部分的语义

4. **读取 Golden 代码**，逐行分析：
   - 计算/搬运步骤序列
   - 条件分支逻辑
   - 与语义描述的对齐验证（不一致则 AskUserQuestion 确认）
   - **搬运类特别关注**：索引越界处理、非连续访存模式、输出地址是否有重叠

5. **数据类型支持矩阵分析**（必须执行）：
   - 列出每个输入支持的 dtype（基于 Golden 代码和硬件常识）
   - 检查所有输入 dtype 组合的合法性（如 fp16+fp16 合法，fp16+fp32 是否合法）
   - 基于目标芯片的昇腾硬件约束（如 Cube 指令要求 fp16 或 int8，Vector 指令支持 bf16 等）
   - 确定输出 dtype 推导规则（`same_as_input`、`promote`、`fixed`）
   - 若存在不支持组合，记录到”不支持功能列表”

6. **形状约束与推导**（必须执行）：
   - **以 golden 为源头**：从 golden 的张量运算读出形状关系（rank/广播/规约维度），需求描述作辅助印证。
   - 提取符号化形状约束（例如 `N == M`、`H = ceil(H_in / stride)`）
   - 标记动态维度（如 batch 可变），给出输出形状计算公式
   - 判断是否需要广播，明确广播规则（Numpy 风格 / 单侧广播 / 无广播）
   - 将约束写入 requirement.json 的 `shape_constraints` 字段

7. **输入/输出 ParamType（可选性）分析**（必须执行）：
   - 为每个 input/output 判定 `param_type`（`REQUIRED`/`OPTIONAL`/`DYNAMIC`，对齐 CANN `OpParamDef::ParamType`）。
   - 判据：该入参/出参是否可缺省？必选 → `REQUIRED`（默认，绝大多数）；可选（如可选 bias/可选 mask/可选 residual，aclnn 侧可传 nullptr）→ `OPTIONAL`；动态长度输入 → `DYNAMIC`。
   - **以 golden 为源头**（golden 签名与用法：默认值/`is None` 分支 → 可选，`*args`/变长 → DYNAMIC），需求文档辅助印证；未声明一律 `REQUIRED`（不臆造 OPTIONAL）。
   - 写入 requirement.json 每个 input/output 项的 `param_type` 字段（下游 integrate 按 name 对齐进 design_spec，codegen 据此渲染 OpDef `.ParamType(X)`）。

8. **数据排布（Format）分析**（必须执行）：
   - **以 golden 为源头**：从 golden 的张量排布/维度语义/`.contiguous()` 等读出排布约束；golden 未体现排布时，用算子类型 + 目标芯片昇腾最佳实践 + 需求描述辅助补，**并标注来源**（"golden 未表达、按最佳实践推断"）。
   - 可能的排布：
     - NHWC / NCHW / HWCN（图像类）
     - FRACTAL_NZ（矩阵乘/卷积类，AI Core 内部高效格式）
     - NC1HWC0（卷积专用）
     - ND（无特定排布，按逻辑顺序）
   - 记录到 `data_format` 字段

9. **边界与异常语义分析**（必须执行）：
   - **先从 golden 读边界/异常语义**（空张量分支、溢出/饱和/截断处理、0-D 支持）；golden 未显式表达时用需求描述 + 最佳实践辅助补，**并标注**"golden 未表达、辅助推断"（不硬判、可诊断）。
   - 零维张量（0-D scalar）是否支持（多数 Vector 算子支持，搬运类需特别说明）
   - 空张量（某维度为 0）行为：跳过 kernel 执行、返回空输出、或报错
   - 溢出处理：饱和（saturate）、截断（truncate）、未定义（undefined）
   - 记录到 `boundary_handling` 字段

9b. **取值范围与接口名（照抄，不推理）**：

   - `aclnn_name`（必填，顶层）：从用户输入**照抄**；缺失时按 unclear/resolve_ambiguity 向用户确认，不生成、不推断。
   - `inputs[].value_range`（可选）：仅用户**明确声明**了取值范围（`[[min,max], ...]`）才照抄填写；没写就不写（缺省 = 下游用通用类型值域兜底，非漏写）。

   **禁止推理/推测取值范围**——输入没写就是没有。

10. **生成输出文件**：
    - 生成 `requirement.json`（按 `schema/requirement.json` 契约 + `references/op_spec_schema.md` 字段语义）

### `--from-general-design` 模式

0. 读取 `{workdir}/general_design.json`
   - 若文件不存在 → 报错并提示用户提供概设文档

1. 提取第一层（算子定义书）内容：
   - 1.1 数学公式 / 地址映射逻辑
   - 1.2 支持范围清单（数据类型、形状、属性取值范围）
   - 1.3 边界语义约定

2. 提取第二层中与规格相关的信息（如有）：
   - 计算范式归类（用于 op_spec 的算子类型标注）
   - 数据排布要求

3. **格式转换与补充分析**（注：此模式并非简单搬运）：
   - 若概设中已明确提供了数据类型支持矩阵、形状约束、数据排布等内容，直接转换
   - 若概设中缺少上述部分关键字段，则尝试从数学公式/Golden 路径（若概设中引用了）进行推导
   - 若完全缺失且无法推导，标记为“待确认”
   - **特别注意**：`--from-general-design` 模式仍需完成「数据类型支持矩阵分析」「形状约束与推导」「数据排布（Format）分析」「边界与异常语义分析」四项分析，但信息来源改为概设文档；不得忽略数据排布等昇腾关键信息

4. 组装 `requirement.json`：
   - 按 `references/op_spec_schema.md` 的结构组织
   - 缺失字段填写 `"pending"` 并添加注释 `<!-- 待用户确认 -->`

5. 完整性检查：
   - 若提取后关键字段（输入/输出规格、数学公式/地址映射）仍缺失 → 提示用户补充
   - 否则直接输出文件

6. **输出自检**（两种模式共用）：
   - [ ] `requirement.json` 已生成
   - [ ] 算子类型已标注（计算类/搬运类/混合类）
   - [ ] `mutation_mode` 已判定（in_place/out_of_place）且与 inputs/outputs 同名关系自洽
   - [ ] 数学公式或地址映射逻辑已记录
   - [ ] 数据类型支持矩阵已填写（不完整的字段标记为 `"pending"`）
   - [ ] 形状约束和推导规则已记录
   - [ ] 所有的 `pending` 字段已在文档头部汇总（`<!-- 待确认项列表 -->`）
   - [ ] **math_formula 与 golden 数值等价已验证**（计算类算子必做，见下方「数值等价自检」）
   - [ ] **inputs[*].shape rank 与 golden 一致已验证**（shape_equiv_golden，见下方「shape 对齐自检」；rank 漂移是精度炸点真根因）
   - [ ] **attrs[*].type 如实声明、忠实 golden 结构**：记法 = Python typing 形态（`int`|`float`|`str`|`bool` 及 `list[T]` **任意嵌套**、`T1|T2` 联合、`X|None` 可空），从 golden 形参注解与真实调用值派生。**嵌套结构必须声明嵌套**（golden 收 `[[1,1],[2,2]]` → 声明 `list[list[int]]`）；**禁止为迁就类型系统发明编码变换**（压平/序列化/自创配对规则）——类型表达不了 golden 语义时，如实按 golden 语义声明并保留原注解写法，框架会在 requirement 期响亮报错并给出处置指引，绝不静默改写（历史实证：把嵌套压平成"扁平+散文配对约定"会与用例/golden 三方脱钩，迟至数小时后才在下游爆炸）

   **数值等价自检（math_equiv_golden，计算类算子必做；搬运类无 math_formula 跳过）**：
   golden.py 是算子数学语义的**唯一真值源**，requirement 的 `math_formula` 是其转写，**必须数值等价**——
   不等价的公式会让下游 design/codegen 基于错公式生成错算子，迟至 review/precision 才暴露（即
   step-76 类根因）。步骤：
   1. 从 golden.py 取一个最小可跑 shape（小张量，如 [2,3]）。
   2. 用 Bash 跑 golden.py 得该 shape 的参考输出（或读 golden 自带的预期）。
   3. 用 `math_formula` 手算（或写一行 numpy/torch）该 shape 的输出。
   4. 对比：数值等价（误差 < 1e-5 或合理相对容差）→ 通过；**不等价 → 根因是 math_formula 转写错**：
      - **就地 re-derive**：重读 golden.py 的计算步骤，修正 `math_formula`——常错点：缩放系数的作用域
        （如 `h_post` 是只缩放某一项还是整个求和结果）、广播轴、规约维度、加法/乘法结合次序、
        **修正项（消除位置耦合的减法项）误含输出位置下标 `i`/`p`/`j`→应替换为跨位置无关的规约标量**。
      - 改后**重跑第 2-3 步重验**，直到等价才输出（自检闭环，§2.9）。
      - **禁止**带着不等价的 math_formula 输出。
   4b. **结构校验（数值等价之外的维度，catch 数值退化漏网）**：即便第 4 步数值等价通过，还要查
       `math_formula` 的**结构可分性**——数值等价抓不到结构缺陷（小 shape 上位置相关项可能恰好
       退化/抵消，数值仍等价，却会在 tiling 跨 tile 时崩，即 design validate GV7-A 要拦的那类）。
       对含**修正项**（减法项，消除位置间耦合，如 normalization/softmax 反向）的公式断言：
       **修正项不得引用当前输出位置下标**（`i`/`p`/`j`）——应为全局量或跨位置规约的标量；
       含位置下标 → 视同不等价，按第 4 步就地 re-derive。数值等价保留（仍必要），结构校验叠加。
   5. 若 golden 语义与需求描述**真冲突**（非转写错，是源头歧义）→ 走 `AskUserQuestion`/`resolve_ambiguity`
      澄清，不臆断。

   **shape 对齐自检（shape_equiv，必做）**：
   **golden.py 是 input shape rank 的权威源**：正常开发 shape 应从 golden 的张量运算读出，需求描述/cases
   作**辅助印证**（需求描述常自然语言、易含糊或残缺，cases 是从需求描述派生的下游产物，均非权威）。
   rank 错会一路 verbatim 传播到 codegen 硬化成错的 op_plugin `dim()`，迟至 precision_debug 才以
   `aclnn ... is null`（EZ1001）炸（9d6e61 真根因：proto 残缺无 shape、agent 凭"标准语义"猜 2D、实际
   golden 1D）。步骤：
   1. **先从 golden.py 读**每个 input 的 shape rank（权威源）：从张量索引/`.shape`/`view` 操作推断——
      - `x[:n]` / `x[i]` 整体一维索引 → **1D**（铁证，按一维下标取段/取元素）。
      - `x[i, j]` / `x[:, k]` 多维索引 → 对应多维。
      - `x.view(-1, k)` / `x.reshape(m, n)` → **内部 reshape，不改 input 本身 rank**（看 view 之前 x 怎么被索引/传入）。
      - `x.shape[d]` / `x.size(d)` → 显式维度引用，佐证 rank。
   2. **需求描述作辅助印证**：读 requirement_doc.md 的 shape 描述与 golden 推出的 rank 互相印证。
   3. **不符时**：golden 明确指示（如 `[:num_seqs]` 一维索引铁证 1D）→ **以 golden 为准**修正 shape rank
      （就地 re-derive，§2.9 自检闭环，维名保留语义命名如 `[num_seqs]` 而非 `[num_seqs, col]`）。**仅当
      golden 本身语义模糊、判断不了 rank 时** → 走 `resolve_ambiguity` 问用户（默认选项以 golden 侧为准，
      §1.13）；不臆断、不用含糊的需求描述压过 golden 的明确指示。
   - `golden_alignment.status`：shape_equiv + math_equiv 都过 → `pass`；有意分叉 → `diff`（differences[]
     记录）。**禁止 `pending`**（=未检；工程层 `_validate_golden_alignment` 会拒、强制重试）。

   - 自检失败 → 就地修正直到通过
   - 自检通过后产出 requirement.json 即完成（工程层 RequirementStage 读此文件）。可选：写入 `{workdir}/checkpoints/req-analysis.json`（格式见 checkpoint_convention.md）供人工审计/跨 skill 参考——**工程层不消费此文件**，非必需

## 知识引用策略

通用知识引用策略（三层优先级 + 禁止猜测 + AskUserQuestion 兜底）详见 `ascendc-op-design-shared/references/knowledge_policy.md`。

本 skill 特有的查询场景：

| 层级 | 查询场景 | 对应执行步骤 |
|------|---------|-------------|
| Tier 1 | 目标芯片的 UB 大小、核数、带宽、向量宽度 | 「目标芯片确认」步骤 |
| Tier 2 | Cube/Vector 指令对 dtype 的硬件约束、数据格式在各芯片上的性能特征 | 「数据类型支持矩阵分析」「数据排布（Format）分析」步骤 |
| Tier 3 | 具体 API 的 dtype/format 兼容性、对齐规则 | 「边界与异常语义分析」步骤 |

## 约束

- 不做切分设计、Buffer 设计、Tiling 必要性判断（属于概要设计和 Tiling 推导范畴）
- 不引用 NPU 编程规则（NK/R 系列），但需引用硬件约束（UB 大小、Cube/Vector 指令要求）
- 搬运类算子的 requirement.json 中使用 `address_mapping` 字段代替 `math_formula`
- **必须输出 `requirement.json`**（required_keys: op_name/aclnn_name/mutation_mode/inputs/outputs/golden_alignment），否则下游概要设计 Skill 将拒绝执行

## 与下游 Skill 的契约

- requirement.json 的机器校验契约在 `schema/requirement.json`，字段语义详解在 `references/op_spec_schema.md`
- 下游 `ascendc-op-general-design` Skill 从工作目录读取 `requirement.json`（工程层经 state.requirement 物化）
- 若 requirement.json 缺失关键字段（required_keys op_name/aclnn_name/mutation_mode/inputs/outputs/golden_alignment），下游将报错并终止