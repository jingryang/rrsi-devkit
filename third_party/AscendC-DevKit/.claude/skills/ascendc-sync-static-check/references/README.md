# References 目录说明

> ascendc-sync-static-check skill 的参考文件索引。
> 子 agent 调用本 skill 时按需读取，主入口 SKILL.md 不内联这些内容。

## 文件映射

| 文件 | 用途 | 读取时机 |
|------|------|---------|
| [sync-static-checklist.md](sync-static-checklist.md) | 7 类检查项完整版（含原理 + 正确/错误代码模式） | 子 agent 遇到不确定的检查项时读取 |
| [sync-symptoms.md](sync-symptoms.md) | 常见同步问题表现形式（独立可迭代） | 子 agent 需结合症状缩小范围时读取 |
| [sync-check-prompt.md](sync-check-prompt.md) | 子 agent prompt 模板（Base + 精简策略） | 调用方派发子 agent 时读取 |

## 子 agent 调用流程

```
调用方（debugAgent）:
  1. 读取 sync-check-prompt.md，提取 Base Template
  2. 填入占位符: {operator_dir} {analysis_result} {failed_cases} {scheme}
  3. 按 scheme 选择精简策略段（或全量），追加到模板末尾
  4. 派发子 agent (subagent_type="general")
  5. 接收子 agent 返回的 JSON 问题清单
  6. 自行决定如何处理（修改代码、验证、或反馈给用户）
```

## 设计约束

- 子 agent **只输出 JSON**，不修改代码、不执行测试
- 子 agent 是**无状态**的：不读写 checkpoint、不维护任何跨调用状态
- 所有状态管理（checkpoint、迭代计数、回归检测）由调用方负责
- 本 skill **不依赖也不委派**其他 skill，完全自包含
