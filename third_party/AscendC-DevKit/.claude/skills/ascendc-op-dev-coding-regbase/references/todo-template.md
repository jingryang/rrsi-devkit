# ascendc-dev 初始化任务清单模板

> 本 skill 在 session 首次触发时，应调用 `TaskCreate` 按此模板批量建立 **11 条 todo**。每条完成时通过 `TaskUpdate` 将 `status` 从 `pending` → `in_progress` → `completed`。
>
> **与 SKILL.md 同步**：本模板的 11 条 todo 与主 SKILL.md 第 174-188 行"Todo 管理"表一一对应。如发现不一致，以 SKILL.md 为权威。

## 使用约定

- **粒度**：每个 Stage 1~4 条，全流程 11 条，覆盖环境确认到编译收尾
- **创建时机**：进入本 skill 的**第一个工具调用**就是批量 `TaskCreate`；不要等到 Stage 1 再建
- **跳过条件**：若 session 已经存在 ascendc-dev 的 todo（通过 `TaskList` 查到），直接复用，不要重复建
- **状态流转**：
  - 进入 Stage → 将对应 todo 标 `in_progress`
  - 该 Stage 验收通过 → 标 `completed`
  - 重试/回退时保持 `in_progress` 不动，用 TaskGet 的 comments 记录原因
- **activeForm**：spinner 会显示此字段，写成"正在 Xxx"这种现在进行时
- **跨 session 恢复**：从 `meta.json` 读取 `current_stage` 后，按下方"跨 Session 恢复时的 todo 重对齐"表格重对齐 todo 状态

---

## Todo 清单（11 条，按 Stage 排序）

### Stage 1：环境与输入确认（4 条 todo，由 s1-env 执行）

**todo-1：检查 CANN 环境和芯片型号**
```json
{
  "subject": "[Stage 1] 检查 CANN 环境和芯片型号",
  "description": "执行 scripts/check_env.sh；调用 ascend-hardware skill 获取芯片型号、UB/核数/带宽；判断编程模型（A3 Membase / A5 Regbase / 不适用（纯 Cube））；将 chip_model 与 编程模型 写入开发记录",
  "activeForm": "正在检查 CANN 环境和芯片型号"
}
```

**todo-2：验证编译工具链可用性**
```json
{
  "subject": "[Stage 1] 验证编译工具链可用性",
  "description": "确认 cmake/make/npu 工具链可用（cmake --version、which ccec 等）。注意：知识库读取已下放至 Stage 2/4 按需执行，Stage 1 不预读知识库索引。",
  "activeForm": "正在验证编译工具链可用性"
}
```

**todo-3：收集开发输入（模式/路径/参考算子/需求）**
```json
{
  "subject": "[Stage 1] 收集开发输入（模式/路径/参考算子/需求）",
  "description": "用 AskUserQuestion 逐项确认：算子代码路径、参考算子（存量可选/新增必选）、需求来源（详设/简易文档/已有开发记录）；编译指令可延后到 Stage 5 确认；主 SKILL 在场景 A 已传算子名+开发模式，本 subagent 不再问",
  "activeForm": "正在收集开发输入"
}
```

**todo-4：初始化开发记录**
```json
{
  "subject": "[Stage 1] 初始化开发记录",
  "description": "执行 dev_record.sh init 创建开发记录目录（含 meta.json, progress.md, history.log, env_snapshot.md, requirements.md, clarification.md, coding_plan.md 及 issues/ 子目录）；执行 dev_record.sh set-progress 标记完成（自动计算初始进度）",
  "activeForm": "正在初始化开发记录"
}
```

### Stage 2：需求分析与开发记录（2 条 todo，由 s2-analysis 执行）

**todo-5：分析需求文档与代码架构**
```json
{
  "subject": "[Stage 2] 分析需求文档与代码架构",
  "description": "逐章阅读详设文档（数学公式/接口变更/数据类型/I/O 约束/Tiling 变更/Kernel 变更/Golden）；交叉对比存量/参考算子代码（优先级 *_tiling.h → *_tiling.cpp → *_def.cpp → kernel）；识别变更点、收集不明确项（条件分支/边界/回退/并行/默认值）、审查 Tiling 策略假设",
  "activeForm": "正在分析需求与代码架构"
}
```

**todo-6：填写开发记录的所有章节**
```json
{
  "subject": "[Stage 2] 填写开发记录的所有章节",
  "description": "按开发记录目录中各文件职责填写所有章节（requirements.md 需求摘要与架构概述、clarification.md 不明确项清单、coding_plan.md 编码计划等）；⚠ 不明确项清单置顶（每项标注维度和问题描述，状态=待澄清）；变更点列表非空；编码计划已生成；执行 dev_record.sh set-progress 标记完成；同步更新 meta.json current_stage（Stage 2 ✅）",
  "activeForm": "正在填写开发记录的所有章节"
}
```

### Stage 3：需求澄清（1 条 todo，由 s3-clarify 执行）

**todo-7：逐项澄清不明确项**
```json
{
  "subject": "[Stage 3] 逐项澄清不明确项",
  "description": "遍历开发记录顶部的⚠不明确项清单；用 AskUserQuestion 结构化提问（说明背景/可选方案/各方案影响）；确认编程模型是否需要调整（澄清中发现纯 Cube / 含 Vector 的，需回退修正）；确认参考算子映射；逐项回写 9.1 澄清记录；所有项置 [已澄清] 后才能进 Stage 4",
  "activeForm": "正在逐项澄清不明确项"
}
```

### Stage 4：编码实现（2 条 todo，由 s4-coding 执行）

**todo-8：分层编码（4.0 / 4.A / 4.B1 / 4.B2 / 4.C.0~4.C.n / 4.E / 4.F）**
```json
{
  "subject": "[Stage 4] 分层编码（4.0 / 4.A / 4.B1 / 4.B2 / 4.C.0~4.C.n / 4.C.{N}.VT.{M} / 4.E / 4.F）",
  "description": "按 coding_index.md 步骤索引和检查点组调度完成分层编码：4.0 编码前置（A5 一次性完成前置文档读取）→ A（TilingData）→ B1（OpDef + InferShape）→ B2（Host Tiling）→ C.0~C.n（Kernel 入口/框架/各计算单元，按编程模型选择 A3/A5/Cube 拆分模板；A5 场景在 Compute 步骤前为每个 VF 函数插入独立的 .VT.{M} 子步骤，由 ascendc-vf-test-agent 逐个执行 VF 精度预验证）→ E（CMakeLists）→ F（编码后自检）。同一检查点组内的 sub-stage 在同一个 Agent 调用中连续执行，跨组返回主 SKILL 重新调度；每个 sub-stage 完成后输出【What】【Why】【Risk】三段式变更摘要并等待用户确认；不得跳步。",
  "activeForm": "正在分层编码"
}
```

**todo-9：编码后自检（A3 5 项 / A5 12 项）**
```json
{
  "subject": "[Stage 4] 编码后自检（A3 5 项 / A5 12 项）",
  "description": "A3 5 项：TilingData 字段对齐 / TilingKey 机制一致(host ASCENDC_TPL_SEL_PARAM ↔ kernel template+if constexpr) / 32 字节对齐 / 新增输入属性声明 / 功能关闭退化路径。A5 12 项：在 A3 基础上加 VF 函数签名合规 / RegTensor≤32 / MaskReg≤8 / SIMD/SIMT 隔离 / Membase API 入侵 / LocalTensor 直接计算 / 地址转换完整 / UB DCache 预留 / 32 字节对齐(LoadAlign/StoreAlign)。任一不过则回到对应 sub-stage 修复；重试上限 2 次",
  "activeForm": "正在执行编码后自检"
}
```

> **Stage 4 的 todo 推进规则**：
> - 进入 Stage 4 时：todo-8 → `in_progress`，todo-9 保持 `pending`。
> - 单个 sub-stage / 单个检查点组完成后：不更新 todo-8/9，仅更新 `progress.md` 和 `coding_plan.md`。
> - 自检失败重试期间：todo-8 保持 `in_progress`，todo-9 保持 `in_progress`（自检正在执行/重试）。
> - Stage 4 全部完成（S4 返回 `next_sub_stage == DONE`）：由主 SKILL 统一将 todo-8 和 todo-9 置 `completed`，再调度 Stage 5。

### Stage 5：编译与收尾（2 条 todo，由 s5-compile 执行）

**todo-10：编译与错误处理（含 Tiling 策略优化）**
```json
{
  "subject": "[Stage 5] 编译与错误处理（含 Tiling 策略优化）",
  "description": "按 Stage 1 确认的编译指令运行；失败时用 scripts/classify_compile_error.sh 分类（C-SYM/C-TYP/C-DUP/C-LNK/C-API/ENV-*）；按 error-handling.md 的梯度递进重试策略执行（同策略→换策略→返回 FAILED）；SubAgent 自行从 dev record header 读取重试计数器并自更新，不依赖主 SKILL 传入预算数字；SubAgent 不创建 Issue，返回 FAILED 后由主 SKILL 按 per-type 计数器与类别升级决定下一步；通过后调用 ascendc-tiling-strategy 优化 Tiling",
  "activeForm": "正在编译与处理错误"
}
```

**todo-11：收尾并输出开发总结**
```json
{
  "subject": "[Stage 5] 收尾并输出开发总结",
  "description": "编译通过后立即收尾：输出开发总结（含编程模型、芯片型号、算子名称）；在总结末尾附加可选后续能力指引（ ascendc-testing / ascendc-profiling / ascendc-pta / lingxi-dsl-evo / lingxi-ops-evo ），不询问、不阻塞；执行 dev_record.sh set-progress 标记 Stage 5 ✅；迭代记录追加 STAGE_COMPLETE | Stage 5 完成",
  "activeForm": "正在收尾与输出开发总结"
}
```

---

## 批量创建建议用法

首次进入 skill 时，11 个 TaskCreate 可并行发出（无顺序依赖，CC 支持单条消息多个 tool_use），或按 Stage 分批发。示例：

```
# 伪代码
for todo in load_from_this_template():
    TaskCreate(subject=todo.subject,
               description=todo.description,
               activeForm=todo.activeForm)
```

创建完马上将 todo-1 置为 `in_progress` 并开始 Stage 1。

---

## 跨 Session 恢复时的 todo 重对齐

跨 session 恢复时，从 `meta.json` 的 `current_stage` 字段读取当前 Step（regbase 为 3 步流水线：Step 1=s2-analysis、Step 2=s4-coding、Step 3=s5-compile），按下表重对齐 todo 状态：

| current_stage | 对应 Step | 涉及的 todo 索引 | 启动的 SubAgent |
|-----------|-----------|------------------|----------------|
| 1 | Step 1 | todo-1 | ascendc-dev-s2-analysis |
| 2 / 4 | Step 2 | todo-2, todo-3 | ascendc-dev-s4-coding（`.VT.{M}` 步骤逐个调度 ascendc-vf-test-agent） |
| 5 | Step 3 | todo-4 | ascendc-dev-s5-compile |

> `current_stage` 语义：1=s2 进行中；2=s2 已完成；4=s4 进行中；5=s5 进行中（Step 3 进入时写入）。

重对齐规则：
- 当前 Stage 之前所有 todo → `completed`
- 当前 Stage 对应 todo → `in_progress`
- 后续 Stage 对应 todo → `pending`
- TaskList 中有"in_progress 但已不在当前 Stage"的 todo → 改 `pending`

> **来源**：与主 SKILL.md §「Todo 管理 → Stage → Todo 索引」保持一致；如未来 todo 数量调整，需同步更新两处。
