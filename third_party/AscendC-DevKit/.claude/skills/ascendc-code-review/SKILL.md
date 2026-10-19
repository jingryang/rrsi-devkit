---
name: ascendc-code-review
description: "AscendC 算子编码红线 Review + 修复 + 验证完整工作流。系统性审查 7 大类编码红线问题和 13 条 TopN 问题，自动修复并三层验证。触发词：code review, 编码红线, red line, 安全检查, coding red line。包含 ascendc-review, ascendc-fix, ascendc-verify 三个子流程。"
---

# ascendc-code-review

完整的 AscendC 算子编码规范审查、修复、验证工作流。

## 使用场景

- 新开发的 AscendC 算子提交前的安全审查
- 现有算子的编码规范升级
- 编码红线问题的系统性排查和修复
- 代码 Review 和技术债务清理
- 提交代码前的强制检查

## 输入参数

- `operator_path`: 算子路径（相对于仓库根目录）
- `operator_name`: 算子名称
- `review_output_dir`: 整改报告输出目录（默认为 `review/`）

## 工作流概览

```
┌─────────────────────────────────────────────┐
│   ascendc-code-review (主入口)              │
│                                             │
│   1. 解析用户请求                           │
│   2. 确定算子范围                           │
│   3. 调度子流程                             │
│   4. 汇总最终报告                           │
└─────────────────────────────────────────────┘
              │
              ├──→ Phase 1: Review (references/ascendc-review.md)
              │    - 读取算子代码
              │    - 应用编码红线检查清单
              │    - 输出问题清单 (JSON)
              │
              ├──→ Phase 2: Fix (references/ascendc-fix.md)
              │    - 读取问题清单
              │    - 应用标准修复模式
              │    - 生成整改报告 (Markdown)
              │
              └──→ Phase 3: Verify (references/ascendc-verify.md)
                   - 编译验证 (build.sh)
                   - UT 验证 (运行单元测试)
                   - ST 验证 (运行集成测试)
                   - 生成验证报告 (Markdown)
```

## 执行流程

### Phase 1: Review (检查阶段)

按 `references/ascendc-review.md` 指引执行：

1. 读取 `op_kernel/*.h` 和 `op_host/*_tiling.cpp` 文件
2. 应用编码红线检查清单（7 大类 + 13 条 TopN）：
   - 红线 1.1: 除零保护
   - 红线 1.2: 数组越界
   - 红线 1.3: 溢出保护
   - 红线 1.4: 变量初始化
   - 红线 1.5: 空指针保护
   - 红线 1.6: 资源匹配
   - 红线 1.7: 数据竞争
   - TopN 2.1-2.13: 特殊值、输入校验、int64 偏移等
3. 输出 JSON 格式问题清单 + Markdown 检查报告

### Phase 2: Fix (修复阶段)

按 `references/ascendc-fix.md` 指引执行：

1. 按优先级排序问题 (P0 → P1 → P2 → P3)
2. 应用标准修复模式：

| 问题类型 | 修复模式 |
|---------|---------|
| 除零保护 | `if (divisor == 0) return;` |
| 数组越界 | `if (index >= size) return;` |
| 溢出保护 | 改为 int64_t + 溢出检查 |
| 变量初始化 | 声明时赋初值 |
| 空指针保护 | `if (ptr == nullptr) return;` |
| 输入校验 | Tiling 中 `OP_LOGE` + `GRAPH_FAILED` |

3. 生成整改报告（修复前后对比）

### Phase 3: Verify (验证阶段)

按 `references/ascendc-verify.md` 指引执行：

1. **编译验证**：`bash build.sh -c "ascend910b"` — 0 错误 0 警告
2. **UT 验证**：`./transformer_op_host_ut --gtest_filter="*OpName*"` — 100% 通过
3. **ST 验证**（如存在）：`pytest --device npu:* tests/st/` — 100% 通过
4. 生成最终验证报告

## 使用方式

### 完整工作流（推荐）

```
使用 ascendc-code-review 技能对 {算子名称} 算子进行完整检查
```

### 仅 Review（不修复）

```
只检查 {算子名称} 算子的编码红线问题，不要修复
```

### 批量整改

```
对 {算子目录路径} 路径下的所有算子进行编码红线整改并验证
```

## 子流程文件

- `references/ascendc-review.md` — 编码红线检查引擎
- `references/ascendc-fix.md` — 标准修复模式应用
- `references/ascendc-verify.md` — 编译和测试验证
- `references/red-line-checklist.md` — 整改报告模板、验证清单模板、七大编码口诀

## 配置

可在项目根目录创建 `.ascendc-review.json`：

```json
{
  "rules": {
    "division_by_zero": true,
    "array_bounds": true,
    "overflow_protection": true,
    "null_pointer": true,
    "variable_initialization": true,
    "special_values": true,
    "input_validation": true,
    "int64_offsets": true
  },
  "verify": {
    "compile": true,
    "ut": true,
    "st": true,
    "required_pass_rate": 100
  }
}
```

## 依赖

- CANN 环境（`source $ASCEND_CANN_PACKAGE_PATH/bin/setenv.bash`）
- bisheng 编译器 + CMake 3.16+
- 算子源代码（`op_kernel/`, `op_host/`, `tests/`）

## 输出产物

1. **整改报告** — `review/{算子名称}_红线整改.md`
2. **修复后的源代码** — 原地修改
3. **验证报告** — 编译/UT/ST 通过率
4. **更新的算子文档** — `docs/npu_{算子名称}.md`（如适用）
