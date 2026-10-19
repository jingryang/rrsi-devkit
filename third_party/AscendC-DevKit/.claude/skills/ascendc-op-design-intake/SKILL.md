---
name: ascendc-op-design-intake
description: 忠实转写用户提供的现成详细设计文档为结构化三件套（design_spec / tiling_strategy / kernel_architecture），不重新设计
triggers:
  - 详设转写
  - design-intake
  - 详设录入
  - 解析详设文档
---

# AscendC 详设录入（Design Intake）

## 职责

把**用户已经写好**的详细设计文档**忠实转写**为机器可消费的结构化三件套
（`design_spec` / `tiling_strategy` / `kernel_architecture`，可选 `data_flow`）。

这是一个**极薄的转写 skill**：它做的是"录入 / 转录"，不是"设计"。类比——intake 之于
详细设计，如同"OCR 录入"之于"建筑设计"：同样产出三件套，一个是转录，一个是创作。

> **一句话定位**：读入现成详设文档 → 按文档原意映射到三件套字段 → 写出 JSON。
> 文档没写的字段标为缺失 / null，**绝不脑补、绝不重新设计**。

## 输入（从当前工作目录读文件，不从 prompt 取）

| 输入文件 | 必需 | 说明 |
|---|---|---|
| `existing_detailed_design.md` | 是 | 用户提供的现成详细设计文档（已由编排物化到当前目录）；这是你转写的唯一来源 |
| `requirement.json` | 是 | 算子需求规格，用于填充 design_spec.op_name 等字段 |

> 不读 `requirement.json`、`checkpoints/*.json` 或任何其它设计步骤写出的中间文件。
> 本步骤是详设录入入口，上游设计产物并不存在。文档里没有的内容标记为缺失/null，不是去别处找的理由。

## 输出（用 Bash（`cat`）写到当前工作目录）

| 产物 | 必需 | required_keys | schema |
|---|---|---|---|
| `design_spec.json` | 是 | `op_name, inputs, outputs` | `schema/design_spec.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |
| `tiling_strategy.json` | 是 | `无必填键（按已有详设文档忠实映射）` | `schema/tiling_strategy.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |
| `kernel_architecture.json` | 是 | `host_code, kernel_code` | `schema/kernel_architecture.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |
| `data_flow.json` | 是 | `无必填键` | `schema/data_flow.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |

> 契约的机器校验来源：`../ascendc-op-design-integrate/schema/design_spec.json`（JSON，含 required_keys + example）。
> 产出不符合 schema → DevKit 适配层拒绝，重试。
## 执行步骤

1. **读取已提供文档**：从「## 已有详细设计文档」段取得详设全文。这是唯一输入源，
   不去工作目录或别处搜寻其它文件。
2. **逐章映射，不推导**：
   - 算子定义 / 接口 / 张量规格 → `design_spec`（op_name / op_type / inputs / outputs / description）。
     每个 input/output 项须带 `param_type`（REQUIRED/OPTIONAL/DYNAMIC）：文档明示可选/动态 → 如实标；
     文档未提 → `REQUIRED`（默认，不臆造 OPTIONAL）。`requirement.json` 若已声明 param_type，优先采信。
   - Tiling / 切分 / 分核 章节 → `tiling_strategy`。
   - Kernel 设计 / 文件拆分 / host-kernel 章节 → `kernel_architecture`（host_code / kernel_code 各含 files）。
   - 数据流 / pipeline 章节 → `data_flow`（可选）。
3. **缺失即如实标缺**：文档未写的字段填 `null` 或省略（非必填项），并在该文件的
   `freeform_notes`（如该 schema 支持）记录"文档未提供"。**绝不为缺失字段编造设计值。**
   （`param_type` 例外：未声明按 `REQUIRED`，这是契约默认而非编造。）
4. **写出三件套**：用 Bash（`cat`）把上述 JSON 写到当前工作目录。
5. **输出自检**：
   - [ ] 三件套的每个字段都能在源文档中找到出处（或如实标缺）
   - [ ] 没有引入文档中不存在的设计决策（无脑补 tiling / kernel 细节）
   - [ ] `design_spec` 含 op_name / inputs / outputs；每个 input/output 含 `param_type`；`kernel_architecture` 含 host_code / kernel_code
   - 自检失败 → 修正后重写，直到每个字段都可追溯到源文档。

## 约束（与被替代的旧 detailed-design skill 的本质区别）

本 skill **只转写、不创作**。以下行为一律禁止（它们恰是旧 `ascendc-op-detailed-design`
一体化生成器的行为，与当前细粒度设计步骤拆分的架构冲突）：

- ❌ **禁止 spawn SubAgent / Agent 工具**：转写是单会话直做的事，不编排子 agent。
- ❌ **禁止 Phase 推导**（语义理解 → 设计推导 → 文档生成）：不做任何"从概设生成详设"的推导。
- ❌ **禁止写 `execution_state.json` / 任何断点恢复状态**：你只负责转写，不维护流程状态。
- ❌ **禁止跨读其它步骤的 checkpoint / 中间文件**：输入只有上下文里那份文档。
- ❌ **禁止 AskUserQuestion 决策门控**：转写无需用户裁决；文档没写的就标缺，不向用户追问设计。
- ❌ **禁止重新设计**：发现文档的设计有疑问也只忠实转写，不替用户改设计。

> 原则只有一条：**忠实映射文档章节到三件套字段，文档没写的标为缺失 / null，绝不脑补设计。**
