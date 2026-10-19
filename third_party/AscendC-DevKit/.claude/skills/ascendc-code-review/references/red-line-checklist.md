# 编码红线检查清单与模板

## 输入参数规范

```yaml
operator_path: string    # 算子路径（相对于仓库根目录）
operator_name: string    # 算子名称
review_output_dir: string  # 整改报告输出目录（默认 review/）
```

## 整改报告模板

```markdown
# {算子名称} 编码红线整改报告

## 一、整改概述

### 1.1 算子信息
- 算子名称：
- 功能描述：
- 所在路径：
- 审查日期：

### 1.2 问题统计
| 严重性 | 数量 | 修复时限 |
|--------|------|----------|
| P0 - 极严重 | X | 立即修复 |
| P1 - 严重 | X | 24小时内 |
| P2 - 中等 | X | 1周内 |
| P3 - 低 | X | 2周内 |

## 二、问题清单与修复方案

{每个问题的详细分析和修复方案}

## 三、整改成果

### 3.1 编码红线覆盖率
### 3.2 修改统计

## 四、验证建议
```

## 验证清单模板

```markdown
## 整改验证清单

### 编码红线核查（必须100%通过）
- [ ] 1.1 除零保护
- [ ] 1.2 数组越界
- [ ] 1.3 溢出保护
- [ ] 1.4 变量初始化
- [ ] 1.5 空指针保护
- [ ] 1.6 资源匹配
- [ ] 1.7 数据竞争

### 验证步骤
1. [ ] 编译通过：`./build.sh -n "{算子名称}"`
2. [ ] 单元测试通过：`./build.sh -u -n "{算子名称}"`
```

## 七大编码口诀

1. **除法必检查，0是拦路虎**（红线1.1）
2. **下标递增前，边界要问遍**（红线1.2）
3. **内存偏移量，int64保安康**（红线1.3）
4. **变量必有值，不能靠运气**（红线1.4）
5. **指针用之前，非空要验遍**（红线1.5）
6. **外来数据毒，校验是解药**（TopN2.2）
7. **特殊值万千，文档说在前**（TopN2.1）

## 编码红线扫描关键词

| 红线 | 搜索关键词 |
|------|-----------|
| 1.1 除零保护 | `/`, `%`, `CeilDiv`, `GetBlockNum()` |
| 1.2 数组越界 | `SetValue`, `[index]`, `offset++` |
| 1.3 溢出保护 | `uint32_t offset`, `+`, `*`, `sizeof` |
| 1.4 变量初始化 | 成员变量声明、局部变量声明 |
| 1.5 空指针保护 | `->`, `*ptr`, 指针参数 |
| 1.6 资源匹配 | `InitBuffer`, `AllocTensor`, `FreeTensor` |
| 1.7 数据竞争 | `GetBlockIdx`, 全局变量写入 |
| TopN2.1 特殊值 | 文档中 nan/inf/±0 说明 |
| TopN2.2 输入校验 | Tiling 中 shape/attr 验证 |
| TopN2.3 int64偏移 | GM 偏移是否使用 int64_t |
| TopN2.4 GM workspace 契约 | `GetWorkspaceSizes`, `GetLibApiWorkSpaceSize`, `ws[0]`, `currentWorkspace` |
| TopN2.5 dtype 中转漏斗 | 元素循环内 `ToFloat(`/`ToBfloat16(`/`ScalarCast<`；int 经 FP；intermediate dtype ≠ IO dtype |

> **TopN2.4 检查项**：`op_host/*_tiling.cpp` 中 `GetWorkspaceSizes(...)` 的赋值（`ws[0]`/`currentWorkspace[0]`）**必须含 `GetLibApiWorkSpaceSize()`**。工程（OpDef）模式下框架把 kernel 入口 workspace 指针偏移过系统区，只设用户 workspace（或写死 `=0`/`=16*1024*1024` 常量）→ 总分配 < 偏移量 → GM 越界 → aicore exception(507015)。正确：`ws[0] = userWorkspaceSize + ascendcPlatform.GetLibApiWorkSpaceSize()`（对纯低阶 API 算子亦然，禁硬编码 16M）。

> **TopN2.5 检查项**：元素循环内禁用标量 cast helper（`ToFloat`/`ToBfloat16`/`ScalarCast<…>`）做 tensor 级 dtype 转换——改 vector `Cast()`。两类违规：① 非计算算子（compare/sort/dedup/gather/scatter/mask）引入 intermediate dtype ≠ IO dtype（升精度无累加可保）；② **int 经 FP 中转**（必丢精度 >2²⁴）。升精度只对浮点算术累加有意义。
