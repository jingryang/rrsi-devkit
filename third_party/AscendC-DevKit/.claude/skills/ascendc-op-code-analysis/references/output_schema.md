# 代码分析输出格式（v1.0）

## 头部

- 模式：约束 / 参考
- 分析对象：{代码路径}

## 1. TilingData 结构

[MUST/REFERENCE] 字段清单：
| 字段名 | 类型 | 语义 | 共享标识 |
|--------|------|------|---------|

## 2. 切分策略

[MUST/REFERENCE] 核间切分：沿 {轴} 切分，blockDim = {公式}
[MUST/REFERENCE] 核内切分：沿 {轴} 切分，ubFactor = {公式}

## 3. Buffer 架构

[MUST/REFERENCE] BUFFER_NUM = {值}，理由：{...}
[MUST/REFERENCE] 常驻 buffer：{列表}

## 4. Kernel 函数结构

[MUST/REFERENCE] 公共函数签名：
- {函数名}({参数列表})

## 5. C++ 模板参数

[MUST/REFERENCE] 模板参数设计：
- template<{参数列表}>

## 6. 兼容性约束清单（仅约束模式）

- CC1: {约束描述}（违反后果：{...}）
- CC2: {约束描述}（违反后果：{...}）
- ...
