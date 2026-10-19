---
name: ascendc-op-design-integrate
description: 整合所有模板的推导结果，确保跨模板一致性
triggers:
  - 跨模板整合
  - integrate
  - 模板整合设计
---

# AscendC 算子跨模板整合

## 职责

整合所有模板的推导结果，确保跨模板一致性。

## 输入

从当前工作目录读取上游产物文件：

- `tiling_results.json`：所有模板的 tiling 三段产物（切分/buffer_kernel/precision_perf）。
- `anchor_report.json`：外部锚点门结论（含 blocking_issues）。
- `requirement.json`：需求级 IO 契约（inputs/outputs/attrs 的 `param_type`、算子写法特性 `mutation_mode` 等）。tiling 轨只携带计算结构、丢弃这类契约事实，故 integrate 按 name 把 requirement 的 IO 契约事实对齐进 design_spec（见执行步骤 2）。
- 存量代码约束（可选，增量场景）。

> 不跨读其它**设计步骤**写出的 checkpoint（防跨步骤控制流死循环）。**例外**：`requirement.json`
> 是需求规格（IO 契约源头），不是设计步产物；读取它**仅用于按 name 对齐 IO 契约事实**（如
> `param_type`）进 design_spec，不重新推导设计内容。
## 输出（用 Bash（`cat`）写到当前工作目录）

| 产物 | 必需 | required_keys | schema |
|---|---|---|---|
| `design_spec.json` | 是 | `op_name, inputs, outputs` | `schema/design_spec.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |
| `tiling_strategy.json` | 是 | `无必填键（按各模板结论聚合）` | `schema/tiling_strategy.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |
| `kernel_architecture.json` | 是 | `host_code, kernel_code` | `schema/kernel_architecture.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |
| `data_flow.json` | 是 | `无必填键` | `schema/data_flow.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |

> 契约的机器校验来源：`schema/design_spec.json`（JSON，含 required_keys + example）。
> 产出不符合 schema → DevKit 适配层拒绝，重试。
## 执行步骤

> **不校验上游完成状态、不跨读 checkpoint**：直接消费已提供的模板划分 / tiling 三段产物 /
> anchor_report 即可。**不去找各 skill"本应"写出的 checkpoint 来判断它"完成没"**——这正是要
> 铲除的跨步骤控制流死循环病根。

1. 对每个模板，从已提供的三段产物提取结论摘要：
   - 切分产物 → 切分方案和 ubFactor 摘要
   - buffer_kernel 产物 → Buffer 分配和 Kernel 结构摘要；其 `scalar_access_points[]`（R6 排除成立的标量通路声明，含排除论证）**原样汇总**进 `tiling_strategy.scalar_access_points[]`（编码阶段标量搬送逐点授权的声明来源，不改写、不合并 name）；各模板均无该字段则顶层省略
   - precision_perf 产物 → 精度和性能摘要
   并核对 anchor_report：若其 `blocking_issues` 含未解决的 AC0/AC1/AC2 阻断项，在整合结论中
   如实标注该问题（你只标注、不自行决定回退）。
2. **IO 契约对齐**（必须执行）：design_spec 的 inputs/outputs 由 tiling 模板结构派生（名/buffer/dtype），
   但需求级契约事实只在 `requirement.json` 里——tiling 轨会丢。按 **name 逐一匹配**对齐：
   - 每个 input/output 的 `param_type`（REQUIRED/OPTIONAL/DYNAMIC）并入 design_spec 对应项；未声明 → 默认 `REQUIRED`。
   - **算子写法特性 `mutation_mode`**（in_place/out_of_place）并入 design_spec **顶层**——它承载 plugin 交付契约（in_place 算子的同名状态张量须 clone+return，禁 copy_ 写回本体）。
   - **per-tensor 读写不再单列 `io`/`access_mode` 文字字段**：由 inputs/outputs 同名关系隐式定义（同名=read_write 状态张量、仅 input=read_only、仅 output=write_only）。kernel 计算语义（in-place 读写）从同名关系读；plugin 交付契约从 `mutation_mode` 读。
   - **标量参数归 `attrs`**（必须）：标量（shape 为空 `[]` / `format:"SCALAR"` / 类型为 int|float|str 且带 default，如 epsilon、mode 选择符）放 design_spec 的 `attrs` 列表（`[{name, type, default}]`），**不得**放 inputs/outputs——它们在 OpDef 渲染为 `Attr(name).<Setter>(default)`，不是 Input tensor。框架在 integrate 后会确定性地把误列进 inputs/outputs 的标量搬进 attrs（见 `_route_scalar_params`）。
   requirement 有而 design_spec 无的输入（或反之）→ 如实记入决策日志（命名漂移/契约不一致）。
3. 共享 TilingData 字段设计（AskUserQuestion 确认）：
   - 识别各模板共用的字段
   - 统一字段命名和语义
   - 确定字段来源标注（L1 参数 / L2 精度决策 / L3 切分结论 / 平台常量）
4. 公共函数签名确定：
   - 识别共享计算逻辑
   - 确定公共函数的参数列表（所有模板必须兼容）
   - 确定函数职责边界
5. 跨模板精度链一致性检查
6. 兼容性校验（增量场景，存量代码约束已提供时）
7. 发现不一致 → AskUserQuestion 确认修正方案
8. 按本 skill「## 输出」段的契约（required_keys）写出整合产物

> **TilingKey 路由不归 integrate**：`templates[].tiling_key` + `route_condition` 的**唯一权威作者**是
> 上游 `template_division.json`（step-2b 决策点）。路由完整性（无遗漏、无重叠）是 template_division
> 自身的自检职责——integrate **不重新 author、不重新验证**它（守本职、门不越界查上游产物）。下游 codegen
> 直接消费 template_division 的 tiling_key 作为既定前提，路由一致性由「单作者 + 忠实消费」构造性保证。

9. **输出自检**：
   - [ ] 所有模板的结论摘要均已读取
   - [ ] anchor_report 的阻断项已核对并在结论中如实标注（若有）
   - [ ] 共享 TilingData 字段已统一命名和语义
   - [ ] 跨模板精度链一致性检查通过
   - [ ] **IO 契约对齐**：design_spec 每个 input/output 必含 `param_type`（按 requirement.json name 对齐；未声明=REQUIRED）；顶层 `mutation_mode` 已从 requirement 继承；inputs/outputs 未残留 `io`/`access_mode` 文字字段（per-tensor 读写由同名关系隐式定义）；requirement 与 design_spec 的输入名集合差异已记入决策日志
   - 自检失败 → 报告用户不可修正问题
   - 自检通过后，用 Bash（`cat`）把整合产物写到当前工作目录（字段以本 skill「## 输出」段声明的 required_keys 为准）。

## 约束

- 不重新推导任何模板的切分/Buffer 设计
- 只做整合和一致性检查
- 发现需要修改模板时，输出修改建议，由用户手动执行
