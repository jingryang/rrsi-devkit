---
name: ascendc-op-design-docgen
description: 将设计产物按 v2.0 模板组装为《详细设计说明书》（模板保真，含 Mermaid 图与全量 Kernel 伪代码）
triggers:
  - 文档生成
  - docgen
  - 生成详设文档
---

# AscendC 算子详设文档生成

## 职责

将上游设计产物按自带 `references/doc_template_v2.0.md` 骨架组装为标准《详细设计说明书》。
纯文档组装（呈现归 LLM），不做设计推导；产物是面向人的交付件，下游 codegen/validate 不消费它。

## 输入（从当前工作目录读取，编排已物化为 JSON）

| 文件 | 内容 |
|---|---|
| `design_spec.json` | 算子两件套之一：`op_name` / `inputs` / `outputs` 等接口契约 |
| `tiling_strategy.json` | 算子两件套之一：TilingKey 路由、共享 TilingData、跨模板策略 |
| `tiling_results.json` | **聚合**所有模板的设计段产物：`{模板名: {split, vf_design?, buffer_kernel, precision_perf}}`（`vf_design` 仅 A5 Regbase 模板有，A2/A3 缺省）；`buffer_kernel.kernel_pseudo_code` 承载各模板 5 函数（init/copy_in/compute/copy_out/main_loop）伪码 |
| `general_design.json` | 概要设计（`关联需求`/`接口实现设计`/`总体设计` 三章的继承源；可缺省） |

- 文档骨架：本 skill 自带 `references/doc_template_v2.0.md`（按需 Read，每次 ≤ 100 行）。
- 不读其它步骤的 checkpoint；不修改任何输入文件。

> 编排物化的是 JSON（非 markdown）。`tiling_results.json` 已聚合各模板产物——按模板名键取 `split`/`vf_design`(A5)/`buffer_kernel`/`precision_perf` 各段，**不要去找 `template_{name}_*.md` 这类文件**（不存在）。

## 输出（用 Bash（`cat`）写到当前工作目录）

| 产物 | 必需 | 说明 |
|---|---|---|
| `<算子名>_详细设计说明书.md` | 是 | v2.0 模板保真的详设文档（算子名取自 `design_spec.json`/`general_design.json` 的 `op_name`） |
| `decision_log.json` | 否 | 本次组装的关键决策记录（供编排追踪） |

> 文件名必须严格为 `<算子名>_详细设计说明书.md`——编排的 DocgenStage 按此名定位产物，名错则视为未产出（halt 转人工，不放行空/坏文档）。

## 执行步骤

1. 读 `design_spec.json` 取 `op_name` → 确定输出文件名 `<op_name>_详细设计说明书.md`。
2. 读 `references/doc_template_v2.0.md` 骨架，按章节顺序组装：
   - **第 1 章 关联需求**：优先从 `general_design.json` 同名章继承，缺失部分从 `design_spec.json` 的接口/需求信息补充。
   - **第 2 章 接口实现设计**：优先从 `general_design.json` 同名章继承；接口契约（inputs/outputs/属性）以 `design_spec.json` 为权威。
     - **§2.3 算子信息库（OpDef）**：渲染 C++ OpDef 前**必读**设计共享资源 `ascendc-op-design-shared/references/OpDef渲染规格映射.md`（+ 官方 `ascendc-dev-knowledge/references/basic_knowledge_docs/编程指南/附录/工程化算子开发/算子原型定义.md`）。按其中的映射表与渲染规程，从 `design_spec.json`（inputs/outputs/attrs/`param_type`）逐字段套：builder 链 `.Input(name).ParamType(param_type).DataType({mapped}).Format({mapped}).UnknownShapeFormat({mapped}).AutoContiguous()`、`this->Attr(name).<Setter>(default)`、`OpAICoreConfig` + `AddConfig`。**组合数跨 IO 一致铁律**：`DataType`/`Format`/`UnknownShapeFormat` 三组列表是**跨 IO 按位对齐的支持组合**——同一算子内**所有 Input/Output 的个数必须一致**，恒定单 dtype 的 IO（如恒 `int64` 的 indices）**把同一枚举重复填满**到与主输入相同个数；`x/y 列 3 个 dtype 而 indices 只列 1 项 INT64` 的混排是**错误案例**（input/output dtype 候选数不一致 → ops-info 静默丢 dtype/format 行 → kernel binary 编译崩）；正确形态见映射 doc「多 IO 组合对齐」节，**勿按 design_spec 各 IO 独立裸填**。**chip 从 `hw_params.json` 的 `chip_code` 取**，经 `to_soc_version()` 翻译成真 soc 字面量——**禁留 `<占位>` 串**（`hw_params.json` 无 chip_code 时停下来报缺，不编造型号）。**原地（in-place）算子**：被更新的输入同时声明为同名 Output（详见 recipe「原地」节），勿发明 `.Inplace()`/`.To()` 等不存在的 API。渲染后必过 recipe 的「canonical 形态门」（**正向锚点**：`OP_ADD(`/`.ParamType(`/`.DataType(`/`AddConfig(` + 每个 design_spec 输入→`Input("<name>")`、输出→`Output("<name>")` + **各 IO 三组列表个数一致（单一 dtype 的 IO 已重复填满，禁 N 项混 1 项）** + 真 soc 字面量；`#include` 不要求——那是 codegen 脚手架）。
   - **第 3 章 总体设计**：从 `general_design.json` 同名章继承，`tiling_strategy.json` 的模板划分/TilingKey 路由作补充细化。

     **第 3 章计算流程图规则**：算子计算含以下任一特征时，必须在第 3 章生成 Mermaid 计算流程图：
     a. 反向传播算子（≥ 3 步且存在梯度路由/scatter）；b. 多模式算子（各模式路径不同）；c. 含条件分支的融合算子。
     要求：Mermaid `flowchart TD`（禁止 ASCII art）；每步一节点，标签含步骤名+核心操作；箭头标注主要数据名（如 `gradY` → `dw`）；不标 Buffer 名（Buffer 细节在第 4 章）。

   - **第 4.0 章 跨模板共享内容**：从 `tiling_strategy.json`（共享 TilingData / 公共函数签名 / 跨模板精度链）。
   - **第 4.x 章 各算子计算模板**：遍历 `tiling_results.json` 的每个模板键，按节名映射装载（见下「组装规则」）：
     - `4.x.2 Tiling实现设计` ← 该模板的 `split`
     - `4.x.{N} VF编排设计` ← 该模板的 `vf_design`（**A5 条件触发**：仅当该模板含 `vf_design` 段时生成此节，含 VF 编排模式/数量/依赖 + per-VF 函数接口；A2/A3 无此段则跳过此节，不影响其它节号）
     - `4.x.3 Buffer设计` ← 该模板的 `buffer_kernel`（Buffer 设计部分）
     - `4.x.4 Kernel设计` ← 该模板的 `buffer_kernel.kernel_pseudo_code`，**全量装载**（见下）
     - `4.x.7/4.x.8 精度/性能分析及设计` ← 该模板的 `precision_perf`
   - **第 5 章 维测设计**：从各模板 `precision_perf` 的精度分析。
   - **附录：代码生成任务拆分表**。
3. 格式规范检查：Mermaid 流程图（禁 ASCII art）；行内代码块包裹特殊符号；具名常量（禁裸数字）；`sizeof(T)` 替代字节数。
4. 分段写入（每次 ≤ 10000 字符，在章节边界拆分；`Kernel设计` 全量装载不得因分段而压缩）。

5. **输出自检**：
   - [ ] `关联需求`/`接口实现设计`/`总体设计` 三章已从 `general_design.json` 优先继承（继承边界仅此三章）
   - [ ] 第 4.x 章数量与 `tiling_results.json` 的模板键数一致
   - [ ] 各 4.x 节独立完整（无 "同 4.1" 写法）
   - [ ] 各模板 `Kernel设计` 节函数清单与 `tiling_results.json[模板].buffer_kernel.kernel_pseudo_code` 完全一致（无摘要、无缺函数，每个函数保留代码块；**轴参算子须含 fast_path + generalized 两路径的 CopyIn 伪代码**）
   - [ ] A5 一致性（条件）：含 `vf_design` 段的模板已生成 `VF编排设计` 节，且其 VF 划分与 `Kernel设计` 节的 `VF_CALL` 调用一致；A2/A3 模板（无 `vf_design` 段）无此节、本项跳过
   - [ ] 格式规范：Mermaid（非 ASCII art）、无裸数字
   - [ ] TilingData 设计代码块为 plain C struct（无 `BEGIN_TILING_DATA_DEF`/`TILING_DATA_FIELD_DEF`/`END_TILING_DATA_DEF`/`REGISTER_TILING_DATA_CLASS` 等 CANN 旧宏），字段与 `tiling_data_fields[]` 一一对应（含数组 `length`）
   - [ ] 计算流程图存在性：算子含反向传播/多模式/融合分支时，第 3 章已有 Mermaid flowchart TD
   - [ ] **§2.3 OpDef canonical 形态（正向锚点）**：渲染的 OpDef 含 `OP_ADD(` / builder 链 `.Input(...).ParamType(...).DataType(...)` 与 `.Output(...).ParamType(...).DataType(...)` / `AddConfig(` + 真 soc_version 字面量（`ascend910b`/`ascend910_93`/`ascend950` 之一，**禁 `<占位>`**）；每个 `design_spec` 输入→`Input("<name>")`、输出→`Output("<name>")`（原地算子同名项两侧都渲染）；**所有 IO 的 `DataType`/`Format`/`UnknownShapeFormat` 三组列表个数一致（恒定单 dtype 的下标 IO 已重复填满，禁 N 项与 1 项混排）**。`#include` 不作要求（codegen 脚手架，§2.7）。缺任一正向锚点即判 fail 就地修；勿用 `desc.MutatableInputDesc`/`OutputAttrMapping`/`ScalarValueType` 等不存在的 API（虚构文本必缺真 builder 链 → 缺锚点）
   - 自检失败 → 就地修正直到通过；通过后写出 `<算子名>_详细设计说明书.md`（+ 可选 `decision_log.json`）

## 组装规则

- **章节映射一律用语义节名，禁止节号**：以节名（`Kernel设计`/`Buffer设计`/`Tiling实现设计`）定位，不用 `4.x.4` 之类节号（模板节号会漂移，节号映射易错配）。
- **多模板用 `{name}` 参数化**：每个模板都有同名子节，按 `tiling_results.json` 的模板键限定作用域。
- **轴参泛化设计渲染（条件）**：若 `general_design.json` 含 `axis_param_design`（即轴参算子），在第 3 章「总体设计」末尾渲染「轴参泛化设计」小节——明示 fast_path（dim=末轴）与 generalized（dim≠末轴）**两路径**的 tiling 设计：两路径都已在 tiling 阶段产出 kernel 伪代码 + TilingData 字段（见第 4 章各模板 `Kernel设计`），由 codegen 翻译实现。**不得渲染"codegen 仅实现主路径 / 泛化需 codegen 支持"之类降级话术**——那是已废弃声明，两路径都是必须实现的设计契约。纯呈现，不做推导。
- **第 4 章单源权威**：`算子计算模板` 章及之后章节一律以 `tiling_results.json` 各模板的 split/vf_design/buffer_kernel/precision_perf 为**唯一权威**，**不从概设继承**。概设继承唯一范围是第 1/2/3 章的三章（受控合并，既不替换丢弃产物，也不丢弃概设独有内容）。
- **TilingData 渲染铁律（重点）**：`4.x.2.1 TilingData设计` 代码块必须渲染为 **plain C struct（POD）**，**禁用** `BEGIN_TILING_DATA_DEF` / `TILING_DATA_FIELD_DEF[_ARR|_STRUCT]` / `END_TILING_DATA_DEF` / `REGISTER_TILING_DATA_CLASS` 等 CANN 旧宏——与 codegen `ascendc-op-dev-coding` Step 5「TilingData 归一化校验」同一不变式（详设/coding 一致契约，旧宏为将废弃写法）。渲染方法：遍历 `tiling_results.json[模板].split.tiling_data_fields[]`（字段四键 `field`/`dtype`/`source`/`length`，`length` 仅数组字段有），按 `dtype field;`（数组 `dtype field[length];`）逐行生成 struct 成员；struct 名取 PascalCase（如 `SwiGluTilingData`）；字段名/类型/数量与源**逐一对应**不得增删；数组长度表达式（如 `vectorCoreNum + 1`）原样填入 `[]`，不得改用 `TILING_DATA_FIELD_DEF_ARR`。
- **`Kernel设计` 全量装载（重点）**：← `tiling_results.json[模板].buffer_kernel.kernel_pseudo_code`。源中每个函数（init/copy_in/compute/copy_out/main_loop 及各子函数）都必须出现并保留各自代码块，**禁止摘要、禁止省略任何函数**。即使触发分段写入 ≤10000 字符，也按节边界/函数边界拆成多次写入，不得压缩内容。**轴参算子双路径**：轴参算子的 `kernel_pseudo_code` 含 per-dim-path 多份 CopyIn 伪代码（fast_path 的 CopyInContiguous + generalized 的 CopyInStrided），**全部装载，不得因"看起来重复"而省略 generalized 路径**——省略会使 dim≠末轴 路径在终稿消失。**A5 一致性**：当该模板含 `vf_design` 段时，`Kernel设计` 节中的 `VF_CALL` 调用序列必须与 `VF编排设计` 节的 VF 划分（数量/顺序/函数名）一致。
- 概设中超出四个结构化字段的详设级内容，docgen 不在第 4 章从概设直接拼入——第 4 章单源是 `tiling_results.json` 各模板的 split/vf_design/buffer_kernel/precision_perf。

## 约束

- 纯文档组装，不做设计推导；不修改任何输入文件。
- 按需分段读取 `references/doc_template_v2.0.md`（每次 ≤ 100 行）。
- 多模板时各 4.x 节必须独立完整（禁止 "同 4.1" 写法）。
- 输出文件名严格 `<算子名>_详细设计说明书.md`。
