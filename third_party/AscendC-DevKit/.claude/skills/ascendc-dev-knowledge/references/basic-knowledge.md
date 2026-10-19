# basic_knowledge 检索指南

**关联指南**: [api-reference.md](api-reference.md)（API 接口详情）、[troubleshooting.md](troubleshooting.md)（故障排查）

## 文档概览

编程指南 + 算子实践参考 + 入门教程，涵盖 AscendC 编程概念、SIMD/SIMT 编程模型、算子开发实例和性能优化方法论。900 版本将原 `编程指南/` 的子目录全部上提到顶层，并按执行模型（SIMD / SIMT / SIMD+SIMT 混合）重组示例。

## 何时使用

- 理解编程概念（"什么是 PIPE？" "AI Core 抽象架构？"）
- 学习编程范式（"CopyIn → Compute → CopyOut 怎么写？"）
- 查算子开发实例（"矢量算子怎么写？" "Matmul 高阶 API 怎么用？"）
- 了解性能优化方法（"bank 冲突怎么避免？" "Tiling 怎么切？"）
- 工程化开发（"CMake 怎么配？" "算子怎么入图？"）
- 区分 SIMD vs SIMT vs 混合编程的差异

## 文档结构

```
./references/basic_knowledge_docs/
├── INDEX.md
├── 兼容性指南.md
├── 入门教程/
│   ├── 什么是Ascend_C.md
│   ├── 环境准备.md
│   └── 快速入门/                          # HelloWorld/Add 算子
│
├── 概念原理和术语/
│   ├── 神经网络和算子/                    # 算子基础概念
│   ├── 内存访问原理/                      # UB/L1/L2/GM 层次
│   ├── 性能优化技术原理/                  # 双缓冲/流水线
│   ├── 编程模型设计原理.md
│   └── 术语表.md
│
├── 硬件实现/
│   ├── 基本架构.md
│   ├── 架构规格/                          # AI Core 各代规格
│   └── 硬件约束/
│
├── 编程模型/
│   ├── 编程模型概述.md
│   ├── 异构并行编程模型.md
│   ├── AI_Core_SIMD编程/                  # 抽象硬件架构/核函数/SIMD编程/SIMD与SIMT混合编程
│   │   └── SIMD编程/                      # 范式/TPipe/TQue
│   ├── AI_Core_SIMT编程/                  # 线程架构/内存层级/同步机制/编程示例
│   └── AI_CPU编程.md
│
├── 语言扩展层/                            # AscendC 语言特性
│   ├── SIMD_BuiltIn关键字.md
│   ├── SIMD语言扩展层C_API.md
│   └── SIMT_BuiltIn关键字.md
│
├── C++类库API/
│   ├── 编程接口概述.md
│   ├── 基础API/                           # 接口分类说明 + 常用操作速查指导
│   └── 高阶API/                           # 常用操作速查指导
│
├── 编译与运行/
│   ├── AI_Core_SIMD编译/                  # bisheng/CMake/RTC/编译选项/约束
│   ├── AI_Core_SIMT编译/
│   ├── AI_CPU算子编译.md
│   └── 算子运行.md
│
├── 调试调优/
│   ├── 概述.md
│   ├── 性能调优.md
│   └── 功能调试/                          # CPU 域孪生调试 / NPU 域上板调试
│
├── 算子实践参考/
│   ├── 本文档组织结构.md
│   ├── 异构计算.md
│   ├── SIMD算子实现/
│   │   ├── 概述.md
│   │   ├── 矢量编程/                      # 基础矢量算子/DoubleBuffer/TBuf/Broadcast/非对齐/多核&Tiling切分
│   │   ├── 矩阵编程（基础API）/           # 耦合/分离模式
│   │   ├── 矩阵编程（高阶API）/           # Matmul 高阶/特性场景
│   │   └── 融合算子编程/                  # 通算融合/CV融合
│   ├── SIMD算子性能优化/
│   │   ├── 优化建议总览表.md
│   │   ├── Tiling策略/
│   │   ├── 内存访问/                      # bank 冲突/对齐
│   │   ├── 流水编排/                      # 双缓冲/pipeline
│   │   ├── 矢量计算/ 矩阵计算/
│   │   └── 头尾开销优化/
│   ├── SIMD与SIMT混合算子实现/            # 异构混合编程
│   ├── SIMD与SIMT混合算子性能优化/
│   ├── 优秀实践/                          # Matmul 调优案例
│   ├── 功能调试/                          # 调试技巧
│   └── 性能分析/
│
└── 附录/
    ├── FAQ/                               # 常见问题
    ├── 常用操作/                          # 工具命令
    ├── C++标准支持/
    ├── AI框架算子适配/                    # ONNX / TensorFlow 适配
    ├── 工程化算子开发/                    # 创建工程/Host Tiling/算子包编译/单算子调用
    ├── 算子入图（GE图）开发/
    ├── 简易自定义算子工程.md
    ├── 基于样例工程完成Kernel直调.md
    ├── msobjdump工具.md
    └── show_kernel_debug_data工具.md
```

> **900 版本要点**: 顶层从 `编程指南/算子实践参考/入门教程/` 三段式变成展开后的多段（编程指南拆开成 `概念原理和术语/硬件实现/编程模型/语言扩展层/C++类库API/编译与运行/调试调优/附录`）。算子实践参考新增 `SIMD与SIMT混合算子实现/性能优化`。

## 极速检索示例

### find — 按文件名定位

```bash
# 找编程模型文档
find "./references/basic_knowledge_docs/编程模型/" -name "*.md"

# 找 Tiling 相关
find "./references/basic_knowledge_docs" -name "*Tiling*" -o -name "*tiling*"

# 找性能优化文档
find "./references/basic_knowledge_docs/算子实践参考/SIMD算子性能优化/" -name "*.md"

# 找矢量编程实例
find "./references/basic_knowledge_docs/算子实践参考/SIMD算子实现/矢量编程/" -name "*.md"

# 找 SIMD/SIMT 混合算子
find "./references/basic_knowledge_docs/算子实践参考/SIMD与SIMT混合算子实现/" -name "*.md"

# 找入门教程
find "./references/basic_knowledge_docs/入门教程/" -name "*.md"

# 找工程化开发
find "./references/basic_knowledge_docs/附录/工程化算子开发/" -name "*.md"

# 找硬件实现/架构
find "./references/basic_knowledge_docs/硬件实现/" -name "*.md"
```

### grep — 按内容搜索

```bash
# 查编程概念
grep -rl "抽象硬件架构\|AI Core" "./references/basic_knowledge_docs/编程模型/" "./references/basic_knowledge_docs/硬件实现/"
grep -rl "编程范式\|CopyIn.*Compute.*CopyOut" "./references/basic_knowledge_docs/"
grep -rl "TPipe\|TQue" "./references/basic_knowledge_docs/编程模型/" "./references/basic_knowledge_docs/C++类库API/"

# 查性能优化技术
grep -rl "DoubleBuffer\|双缓冲" "./references/basic_knowledge_docs/"
grep -rl "bank冲突\|bank conflict" "./references/basic_knowledge_docs/算子实践参考/"
grep -rl "流水编排\|pipeline" "./references/basic_knowledge_docs/算子实践参考/"

# 查 Tiling 方法
grep -rl "尾核\|尾块\|Tail" "./references/basic_knowledge_docs/算子实践参考/SIMD算子实现/矢量编程/"

# 查内存层次
grep -rl "Unified Buffer\|UB\|L1 Buffer\|Global Memory" "./references/basic_knowledge_docs/概念原理和术语/"

# 查编译相关
grep -rl "CMakeLists\|cmake\|bisheng" "./references/basic_knowledge_docs/编译与运行/"

# 查 SIMT 编程
grep -rl "SIMT\|warp\|线程" "./references/basic_knowledge_docs/编程模型/AI_Core_SIMT编程/"
```

### cat — 直接阅读

```bash
# 看索引
cat "./references/basic_knowledge_docs/INDEX.md"

# 读核心编程概念
cat "./references/basic_knowledge_docs/编程模型/AI_Core_SIMD编程/"*.md | head -100
cat "./references/basic_knowledge_docs/编程模型/AI_Core_SIMT编程/"*.md | head -100

# 读矢量编程实例
cat "./references/basic_knowledge_docs/算子实践参考/SIMD算子实现/矢量编程/基础矢量算子.md"

# 读 DoubleBuffer
cat "./references/basic_knowledge_docs/算子实践参考/SIMD算子实现/矢量编程/DoubleBuffer场景.md"

# 读 Tiling 策略
cat "./references/basic_knowledge_docs/算子实践参考/SIMD算子性能优化/Tiling策略/"*.md

# 看兼容性指南（900 新增）
cat "./references/basic_knowledge_docs/兼容性指南.md"
```

## 常用概念速查

| 概念 | 检索路径 |
|------|---------|
| AI Core 架构 | `硬件实现/基本架构.md` + `硬件实现/架构规格/` |
| AI Core 硬件约束 | `硬件实现/硬件约束/` |
| SIMD 编程范式 | `编程模型/AI_Core_SIMD编程/SIMD编程/` |
| SIMT 编程 | `编程模型/AI_Core_SIMT编程/` |
| SIMD/SIMT 混合 | `编程模型/AI_Core_SIMD编程/SIMD与SIMT混合编程.md` |
| TPipe/TQue | `C++类库API/基础API/接口分类说明/` |
| Tiling 切分 | `算子实践参考/SIMD算子实现/矢量编程/多核&Tiling切分/` |
| 性能优化总览 | `算子实践参考/SIMD算子性能优化/优化建议总览表.md` |
| bank 冲突 | `算子实践参考/SIMD算子性能优化/内存访问/` |
| 融合算子 | `算子实践参考/SIMD算子实现/融合算子编程/` |
| 工程化开发 | `附录/工程化算子开发/` |
| 编译选项 | `编译与运行/AI_Core_SIMD编译/常用的编译选项.md` |
| FAQ | `附录/FAQ/` |
