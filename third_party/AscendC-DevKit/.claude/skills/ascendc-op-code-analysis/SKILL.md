---
name: ascendc-op-code-analysis
description: 从现有/类似算子代码中提取设计约束或设计模式
triggers:
  - 代码分析
  - code-analysis
  - 分析现有代码
  - 分析类似算子
---

# AscendC 算子代码分析

## 职责

从现有/类似算子代码中提取设计约束或设计模式。

## 输入

- 算子代码路径（精确到算子目录）
- 模式参数：`--mode constraint` 或 `--mode reference`

## 输出

- 约束模式：`{workdir}/code_constraints.md`
- 参考模式：`{workdir}/code_reference.md`

## 执行步骤

1. 读取算子目录结构，识别关键文件：
   - tiling 实现（*_tiling.h / *_tiling.cpp）
   - kernel 实现（*.h / *.cpp）
   - TilingData 定义

2. 提取 TilingData 结构：字段名、类型、语义、共享字段标识

3. 提取切分策略：核间切分轴和映射公式、核内切分轴和 ubFactor 公式、blockIdx 分解逻辑

4. 提取 Buffer 架构：TQue/TBuf 分配方案、BUFFER_NUM 选择、常驻 buffer 识别

5. 提取 Kernel 函数结构：公共函数签名、C++ 模板参数设计、模板间代码复用模式

6. 生成约束/参考清单：
   - 约束模式：每条标记 [MUST]，附理由和违反后果
   - 参考模式：每条标记 [REFERENCE]，附适用条件

7. **输出自检**：
   - [ ] 输出文件已生成（`code_constraints.md` 或 `code_reference.md`）
   - [ ] 每条约束标记了 [MUST] 或 [REFERENCE]
   - [ ] 约束模式的每条有明确"违反后果"
   - [ ] 参考模式每条注明了适用条件
   - 自检失败 → 就地修正直到通过
   - 自检通过后产出主要产物即完成。可选：写入 `{workdir}/checkpoints/code-analysis.json`（格式见 checkpoint_convention.md）供人工审计——**工程层不消费此文件**（本 skill 是孤立工具 skill，不在 pipeline），非必需

## 约束

- 不做设计推导，只做代码分析和信息提取
- 不修改任何代码
- 约束模式下，约束清单必须明确标注"违反后果"
