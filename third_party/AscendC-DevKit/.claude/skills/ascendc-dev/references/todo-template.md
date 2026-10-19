# ascendc-dev 初始化任务清单模板

> 本 skill 在 session 首次触发时，应调用 `TaskCreate` 按此模板批量建立 10 条 todo。每条完成时通过 `TaskUpdate` 将 `status` 从 `pending` → `in_progress` → `completed`。

## 使用约定

- **粒度**：每个 Stage 1~2 条，全流程 10 条，覆盖环境确认到编译出包
- **创建时机**：进入本 skill 的**第一个工具调用**就是批量 `TaskCreate`；不要等到 Stage 1 再建
- **跳过条件**：若 session 已经存在 ascendc-dev 的 todo（通过 `TaskList` 查到），直接复用，不要重复建
- **状态流转**：
  - 进入 Stage → 将对应 todo 标 `in_progress`
  - 该 Stage 验收通过 → 标 `completed`
  - 重试/回退时保持 `in_progress` 不动，用 TaskGet 的 comments 记录原因
- **activeForm**：spinner 会显示此字段，写成"正在 Xxx"这种现在进行时

---

## Todo 清单（10 条，按 Stage 排序）

### Stage 1：环境与输入确认

**todo-1**
```json
{
  "subject": "[Stage 1] 验证 CANN 环境与硬件参数",
  "description": "执行 scripts/check_env.sh 检查 CANN/driver；调用 ascend-hardware skill 获取 UB/核数/带宽；读取 ascendc-dev-knowledge 的 basic_knowledge_docs 与 api_reference_docs 两个 INDEX.md",
  "activeForm": "正在验证 CANN 环境与硬件参数"
}
```

**todo-2**
```json
{
  "subject": "[Stage 1] 收集开发输入（模式/路径/参考算子/需求来源/编译指令）",
  "description": "用 AskUserQuestion 逐项确认：开发模式（存量改造/新增）、算子目录、参考算子（可选）、需求来源（详设/bug report）、编译指令（build.sh/make）",
  "activeForm": "正在收集开发输入"
}
```

**todo-3**
```json
{
  "subject": "[Stage 1] 初始化开发记录与 Memory 指针",
  "description": "按 references/dev-record-template.md 创建 <算子名>开发记录.md；在 Memory 写入开发记录路径；执行 scripts/update_progress.sh 计算初始进度",
  "activeForm": "正在初始化开发记录"
}
```

### Stage 2：需求分析与开发记录

**todo-4**
```json
{
  "subject": "[Stage 2] 分析需求文档与代码架构",
  "description": "逐章阅读详设文档；交叉对比存量/参考算子代码；识别变更点、收集不明确项、审查 Tiling 策略假设",
  "activeForm": "正在分析需求与代码架构"
}
```

**todo-5**
```json
{
  "subject": "[Stage 2] 填齐开发记录的 9 个章节",
  "description": "按 dev-record-template.md 填写：基本信息、需求摘要、代码架构、变更点详情、编码计划、编码执行（待办）、自检结果（待办）、Issue 注册表、迭代记录；⚠ 不明确项清单置顶；执行 scripts/update_progress.sh",
  "activeForm": "正在填写开发记录"
}
```

### Stage 3：需求澄清

**todo-6**
```json
{
  "subject": "[Stage 3] 逐项澄清不明确项",
  "description": "遍历开发记录顶部的⚠不明确项清单；用 AskUserQuestion 结构化提问；回写澄清结论到开发记录；确认参考算子映射；所有项置 resolved 后才能进 Stage 4",
  "activeForm": "正在澄清不明确项"
}
```

### Stage 4：编码实现

**todo-7**
```json
{
  "subject": "[Stage 4] 分层编码：TilingData → Host Tiling → Kernel → CMakeLists",
  "description": "按 4 个 sub-stage（A/B/C/D）推进；每个 sub-stage 完成后输出【What】【Why】【Risk】三段式变更摘要并等待用户确认；不得跳步",
  "activeForm": "正在分层编码"
}
```

**todo-8**
```json
{
  "subject": "[Stage 4] 编码后自检",
  "description": "5 项自检：TilingData 字段对齐、分支覆盖完整、所有 DataCopy 地址 32 字节对齐、kernel 属性声明正确、退化路径可达；任一不过则回到对应 sub-stage 修复",
  "activeForm": "正在执行编码后自检"
}
```

### Stage 5：编译与收尾

**todo-9**
```json
{
  "subject": "[Stage 5] 执行编译与错误处理",
  "description": "按 Stage 1 确认的编译指令运行；失败时用 scripts/classify_compile_error.sh 分类；按 error-handling.md 的梯度递进重试策略最多 3 次；仍失败则升级处理",
  "activeForm": "正在编译并处理错误"
}
```

**todo-10**
```json
{
  "subject": "[Stage 5] 编译通过后收尾",
  "description": "根据 Tiling 策略实际表现做优化；回写所有变更到开发记录迭代记录章节；删除 Memory 中的开发记录指针；按需路由到后续 ascendc-testing / ascendc-precision-loop 等 skill",
  "activeForm": "正在收尾"
}
```

---

## 批量创建建议用法

首次进入 skill 时，连续发 10 个 TaskCreate 调用（CC 支持单条消息里并行多个 tool_use），或者按 Stage 分批发。示例：

```
# 伪代码
for todo in load_from_this_template():
    TaskCreate(subject=todo.subject,
               description=todo.description,
               activeForm=todo.activeForm)
```

创建完马上将 todo-1 置为 `in_progress` 并开始 Stage 1。
