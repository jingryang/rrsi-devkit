---
name: ascendc-dev-knowledge
description: "AscendC operator development knowledge base. Use when looking up AscendC API signatures, programming concepts, operator examples, error codes, or troubleshooting. Covers Kernel-side APIs, Host-side data structures, programming guides, performance optimization patterns, and fault diagnosis. Triggers on AscendC API, operator development, Tiling, InferShape, DataCopy, error codes, troubleshooting, programming guide."
---

# AscendC Knowledge Base

本知识库为 L2 层级（完整官方文档），提供 AscendC 开发的全量 API 参考和编程指南。

与两个独立知识 skill 的关系：
- **ascendc-api-best-practices**: API 正确用法 + 避坑（间接采样用 Gather 非逐元素 DataCopyPad、越界钳制、粒度/dtype 约束）；查 API 用法时优先于本库
- **evolution-knowledge**: a3/a5 两套精选知识，面向进化优化决策（策略选择、硬件约束、API 陷阱）
- **本知识库（L2）**: ~3700 篇官方文档，面向代码编写时的精确 API 查阅（裸签名/参数约束）
- **检索优先级**: ascendc-api-best-practices（API 用法/避坑）→ evolution-knowledge guide.md → 本知识库按需 grep → WebSearch

## 前置检查

使用前先确认知识库数据是否就绪：

```bash
ls ./references/api_reference_docs/INDEX.md ./references/basic_knowledge_docs/INDEX.md \
   ./references/basic_data_api_docs/INDEX.md ./references/troubleshooting_docs/INDEX.md \
   ./references/log_reference_docs/INDEX.md 2>/dev/null | wc -l
```

- 结果为 **5**：知识库就绪，可直接检索。
- 结果 < 5：需要先构建知识库，执行以下命令：

```bash
python3 ./scripts/ascendc_spider.py -v 900
python3 ./scripts/restructure_kb.py -v 900
```

## 知识库路径

知识库数据位于本 skill 的 `./references/` 目录内：

| 目录 | 说明 |
|------|------|
| `./references/cache/` | 原始的文档（清洗后默认删除） |
| `./references/*_docs/` | 清洗后的知识库（检索目标） |

支持 850、900beta1、900 等多个 CANN 版本，通过 `-v` 参数切换，共用同一组目录名。当前默认数据为 900（CANN 9.0.0 正式版）。

## 知识库结构

结构因版本而异，以下为典型布局（具体子目录以实际 INDEX.md 为准）：

```
./references/
├── api_reference_docs/         — Ascend C 算子开发接口（按执行模型分组）
│   ├── INDEX.md
│   ├── Ascend_C_API列表.md
│   ├── AI_CPU_API/                 # printf / assert / DataStoreBarrier
│   ├── SIMD_API/
│   │   ├── 通用说明和约束.md
│   │   ├── 基础API/                # Memory数据搬运 / Memory矢量计算 / Reg矢量计算
│   │   │                          # 同步控制 / 资源管理(Pipe&Que) / 矩阵计算（ISASI）
│   │   │                          # Cube分组管理 / Kernel_Tiling / 标量计算 / 系统变量访问
│   │   │                          # 原子操作 / 缓存控制 / 调试接口 / 工具函数
│   │   ├── 高阶API/                # 矩阵计算(Matmul) / 卷积计算 / 数学计算 / 归约 / 排序
│   │   │                          # 激活函数 / 量化 / 归一化 / 张量变换 / 索引 / 数据过滤
│   │   │                          # 随机函数 / HCCL通信类
│   │   ├── 基础数据结构/           # LocalTensor / GlobalTensor / Layout / Coordinate / TensorTrait
│   │   └── 其他数据类型/           # TensorDesc / TPosition / *RepeatParams / ListTensorDesc
│   ├── SIMT_API/                   # Warp / Atomic / 同步函数 / 数学/比较/类型/精度转换
│   │                              # 向量类型构造函数 / Cache_Hints Load_Store / 核函数定义
│   └── Utils_API/                  # Tiling模板/数据结构注册/调测/下沉 / 平台信息
│                                  # 原型注册与管理 / 调测接口 / RTC / log / C++标准库
│
├── basic_knowledge_docs/       — 编程指南 + 算子实践参考 + 入门教程
│   ├── INDEX.md
│   ├── 兼容性指南.md
│   ├── 入门教程/                   # 什么是Ascend_C / 环境准备 / 快速入门
│   ├── 概念原理和术语/             # 神经网络和算子 / 内存访问原理 / 性能优化技术原理 / 术语表
│   ├── 硬件实现/                   # 基本架构 / 架构规格 / 硬件约束
│   ├── 编程模型/                   # AI_Core_SIMD编程 / AI_Core_SIMT编程 / AI_CPU编程 / 异构并行
│   ├── 语言扩展层/                 # SIMD/SIMT BuiltIn 关键字 / SIMD 语言扩展 C API
│   ├── C++类库API/                 # 基础API / 高阶API（接口分类说明 + 速查指导）
│   ├── 编译与运行/                 # AI_Core_SIMD编译 / AI_Core_SIMT编译 / AI_CPU算子编译 / 算子运行
│   ├── 调试调优/                   # 功能调试 / 性能调优
│   ├── 算子实践参考/               # SIMD算子实现 + SIMD算子性能优化
│   │                              # SIMD与SIMT混合算子实现 + 性能优化 / 优秀实践 / 功能调试 / 性能分析
│   └── 附录/                       # FAQ / 常用操作 / C++标准支持 / AI框架算子适配
│                                  # 工程化算子开发 / 算子入图（GE图）开发 / msobjdump / show_kernel_debug_data
│
├── basic_data_api_docs/        — Host 侧基础数据结构和接口
│   ├── INDEX.md
│   ├── 基础数据结构和接口列表.md
│   ├── gert命名空间/               # TilingContext / TilingData / InferShape*Context / Shape / Tensor*
│   │                              # OpImplRegisterV2 / Op*ContextBuilder / RuntimeAttrs / ...
│   ├── ge命名空间/                 # Shape / Tensor / TensorDesc / AscendString / Allocator / MemBlock
│   │                              # KernelLaunchInfo / OpRegistrationData / FrameworkRegistry / ...
│   └── C接口/                      # C_DataType / C_Format / gert_TilingContextBuilder_Set*
│
├── troubleshooting_docs/       — 故障处理
│   ├── INDEX.md
│   ├── 故障处理简介.md
│   ├── 错误码参考/                 # GE / RTS / HCCL / AI_CPU / FE / Driver / DVPP / Auto_Tune
│   │                              # TBE_Pass_Compiler / TEFusion (使用说明.md)
│   ├── 典型故障专题/               # AI_Core_Error / 内存OOM / 进程中断 / 进程卡住
│   └── 故障定位工具/               # asys工具使用指导 / msaicerr工具使用指导
│
└── log_reference_docs/         — 日志参考
    ├── INDEX.md
    ├── 日志简介.md / 设置日志级别.md / 重启日志进程.md
    ├── 查看日志（Ascend_EP / Ascend_RC / Control_CPU开放形态）.md
    ├── 查看日志配置文件.md / 查看trace日志.md
    └── FAQ/
```

## 检索指南

| 文档集 | 检索指南 | 用途 |
|--------|---------|------|
| `api_reference_docs/` | `references/api-reference.md` | Kernel 侧 API 签名、参数、约束、数据类型、mask、同步控制 |
| `basic_knowledge_docs/` | `references/basic-knowledge.md` | AI Core 架构、编程范式、算子示例、Tiling 策略、性能优化 |
| `basic_data_api_docs/` | `references/basic-data-api.md` | TilingContext、InferShape、Shape、TensorDesc、OpDef 注册 |
| `troubleshooting_docs/` | `references/troubleshooting.md` | 错误码 (EZ/EE/EG/...)、AI Core Error、OOM、进程卡死、asys 工具 |
| `log_reference_docs/` | `references/log-reference.md` | 日志级别配置、plog 框架、日志 FAQ |

检索指南文件包含 grep/find/cat 示例和常见查询模式。任何 section 先 `cat INDEX.md` 查看目录。

## 快速检索速查

```bash
# 找 API 文档
find "./references/api_reference_docs" -name "DataCopy*.md"
grep -rl "void Sqrt" "./references/api_reference_docs/"

# 找编程概念
grep -rl "DoubleBuffer\|双缓冲" "./references/basic_knowledge_docs/算子实践参考/"

# 找性能优化
find "./references/basic_knowledge_docs/算子实践参考/SIMD算子性能优化/" -name "*.md"

# 找 Host 侧接口
grep -rl "GetInputShape" "./references/basic_data_api_docs/gert命名空间/"

# 找错误码
grep -rl "EZ9999" "./references/troubleshooting_docs/错误码参考/"

# 看某个 section 的完整索引
cat "./references/api_reference_docs/INDEX.md"
```

## 知识库构建工具

脚本位于 `./scripts/`，详细参数见各脚本 `--help`。

### Pipeline: 爬虫（spider）→ cache → 清洗（restructure）→ *_docs

```
ascendc_spider.py          restructure_kb.py
   -v {version}               -v {version}
      │                          │
      ▼                          ▼
  references/cache/        references/*_docs/
  (raw pages + images)     (hierarchical, cleaned)
```

清洗默认删除 cache（`--keep-cache` 可保留）。

### 完整 Rebuild 流程

```bash
# 1. 爬取
python3 ./scripts/ascendc_spider.py -v 900
# 2. 清洗（自动删除 cache）
python3 ./scripts/restructure_kb.py -v 900
```

> 切换到其他 CANN 版本时，把 `-v 900` 替换为目标版本（`850` / `900beta1`）。两步必须使用同一版本号。
