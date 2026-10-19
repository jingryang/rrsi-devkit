# api_reference 检索指南

**关联指南**: [basic-knowledge.md](basic-knowledge.md)（编程概念）、[basic-data-api.md](basic-data-api.md)（Host 侧接口）

## 文档概览

Ascend C 算子开发接口文档，覆盖 Kernel 侧所有 API 的函数签名、参数说明、支持的数据类型、约束条件和示例代码。900 版本按执行模型组织：SIMD（矢量/矩阵主流）、SIMT（线程级）、AI_CPU、Utils。

## 何时使用

- 查 API 函数原型和参数说明（"DataCopy 的参数是什么？"）
- 查某个 API 支持的数据类型（"Sqrt 支持 half 吗？"）
- 查 mask 设置方式（"mask 参数怎么用？"）
- 查同步控制接口（"SetFlag/WaitFlag 怎么用？"）
- 查高阶 API 使用方法（"Matmul API 怎么调用？"）
- 区分 Memory 域 vs Reg 域矢量计算（910D/A5 引入 Reg 矢量）

## 文档结构

```
./references/api_reference_docs/
├── INDEX.md
├── Ascend_C_API列表.md                    # 总览
├── AI_CPU_API/                             # printf, assert, DataStoreBarrier
├── SIMD_API/                               # 矢量/矩阵主流
│   ├── 通用说明和约束.md
│   ├── 基础API/
│   │   ├── Memory数据搬运/                # DataCopy/Copy/DataCopyPad/Broadcast
│   │   ├── Memory矢量计算/                # 基础算术/类型转换/比较与选择/归约/复合/逻辑
│   │   ├── Reg矢量计算/                   # 寄存器域矢量（910D/A5 新增）
│   │   │   ├── 寄存器数据类型/            # RegTensor 等
│   │   │   ├── 基础算术/ 复合计算/ 归约计算/
│   │   │   ├── 数据压缩/ 数据填充/ MaskReg计算/
│   │   │   ├── Reg数据搬运/ 同步控制/
│   │   │   └── asc_vf_call.md
│   │   ├── 同步控制/
│   │   │   ├── 核内同步/                  # SetFlag/WaitFlag/PipeBarrier
│   │   │   ├── 核间同步/                  # SyncAll/CrossCoreSetFlag
│   │   │   └── 任务间同步/
│   │   ├── 资源管理/
│   │   │   └── Pipe和Que框架/             # TPipe/TQue/TQueBind/TSCM/TBuf
│   │   ├── 矩阵计算（ISASI）/             # Mmad
│   │   ├── Cube分组管理（ISASI）/         # CubeResGroupHandle
│   │   ├── Kernel_Tiling/                 # GetTilingDataPtr
│   │   ├── 标量计算/ 系统变量访问/        # GetBlockIdx/GetBlockNum
│   │   ├── 原子操作/ 缓存控制/ 调试接口/
│   │   ├── 工具函数/                      # Duplicate/CreateVecIndex
│   │   └── images/
│   ├── 高阶API/
│   │   ├── 矩阵计算/                      # Matmul Kernel侧 + Tiling侧
│   │   ├── 卷积计算/                      # Conv3D
│   │   ├── 数学计算/ 归约操作/ 排序操作/
│   │   ├── 激活函数/ 量化操作/ 归一化操作/
│   │   ├── 张量变换/ 索引计算/ 数据过滤/ 随机函数/
│   │   └── HCCL通信类/
│   ├── 基础数据结构/
│   │   ├── LocalTensor/ GlobalTensor/
│   │   ├── Layout/ Coordinate/ TensorTrait/
│   ├── 其他数据类型/                      # TensorDesc/TPosition/...
│   │   ├── BinaryRepeatParams.md UnaryRepeatParams.md
│   │   ├── ListTensorDesc.md ShapeInfo.md
│   │   └── TensorDesc/
│   └── images/
├── SIMT_API/                               # 线程级 (Warp/Atomic/Sync/Cache Hints)
│   ├── 简介.md 内置宏.md
│   ├── Warp函数/ Atomic函数/ 同步函数/
│   ├── 数学函数/ 比较函数/ 类型转换/ 精度转换/
│   ├── 向量类型构造函数/
│   ├── 使能Cache_Hints的Load_Store函数/
│   └── 核函数定义/
└── Utils_API/
    ├── Tiling模板编程/                    # TilingData 注册宏
    ├── Tiling数据结构注册/                # BEGIN/END_TILING_DATA_DEF
    ├── Tiling调测/ Tiling下沉/
    ├── 平台信息获取/                      # GetSocVersion/PlatformAscendC
    ├── 原型注册与管理/                    # OpDef 注册
    ├── 调测接口/ RTC/ log/
    └── C++标准库/                         # tuple/max/min/enable_if
```

> **900 版本要点**: 顶层不再是 `基础API/高阶API/Utils_API/...` 的混合扁平结构，而是 `SIMD_API/SIMT_API/AI_CPU_API/Utils_API`。原"矢量计算"被拆为 `Memory矢量计算`（主流）+ `Reg矢量计算`（910D/A5 寄存器域）。

## 极速检索示例

### find — 按文件名定位

```bash
# 找特定 API（不确定路径用 -name 全树搜）
find "./references/api_reference_docs" -name "Sqrt.md"
find "./references/api_reference_docs" -name "DataCopy*.md"
find "./references/api_reference_docs" -name "SetFlag*"
find "./references/api_reference_docs" -name "Matmul*"
find "./references/api_reference_docs" -name "RegTensor*"

# 同名 API 多版本（Memory 域 vs Reg 域）一起列
find "./references/api_reference_docs" -name "Sqrt.md"
# api_reference_docs/SIMD_API/基础API/Memory矢量计算/基础算术/Sqrt.md
# api_reference_docs/SIMD_API/基础API/Reg矢量计算/基础算术/Sqrt.md

# 列出某类别下所有 API
find "./references/api_reference_docs/SIMD_API/基础API/Memory矢量计算/" -name "*.md"
find "./references/api_reference_docs/SIMD_API/基础API/同步控制/" -name "*.md"
find "./references/api_reference_docs/SIMD_API/基础API/Memory数据搬运/" -name "*.md"
find "./references/api_reference_docs/SIMD_API/高阶API/矩阵计算/" -name "*.md"
find "./references/api_reference_docs/SIMD_API/基础API/资源管理/" -name "*.md"

# 统计某类 API 数量
find "./references/api_reference_docs/SIMD_API/基础API/Memory矢量计算/" -name "*.md" | wc -l
```

### grep — 按内容搜索

```bash
# 查函数签名（限定 Memory 域避免被 Reg 域污染）
grep -r "void Sqrt" "./references/api_reference_docs/SIMD_API/基础API/Memory矢量计算/"
grep -r "void DataCopy" "./references/api_reference_docs/SIMD_API/基础API/Memory数据搬运/"
grep -r "void SetFlag" "./references/api_reference_docs/SIMD_API/基础API/同步控制/"

# 查某数据类型支持
grep -rl "bfloat16\|bf16" "./references/api_reference_docs/SIMD_API/"
grep -rl "half" "./references/api_reference_docs/SIMD_API/基础API/Memory矢量计算/"

# 查参数说明
grep -A10 "参数说明" "./references/api_reference_docs/SIMD_API/基础API/Memory矢量计算/基础算术/Sqrt.md"

# 查约束条件
grep -r "32字节对齐\|32Byte\|32B对齐" "./references/api_reference_docs/SIMD_API/" | head -10

# 查 mask 用法
grep -rl "mask" "./references/api_reference_docs/SIMD_API/基础API/Memory矢量计算/" | head -10

# 查 LocalTensor / GlobalTensor 方法
grep -rl "LocalTensor" "./references/api_reference_docs/SIMD_API/基础数据结构/LocalTensor/"
grep -rl "GlobalTensor" "./references/api_reference_docs/SIMD_API/基础数据结构/GlobalTensor/"

# 查 PIPE 类型
grep -r "PIPE_V\|PIPE_MTE\|PIPE_M\|PIPE_S" "./references/api_reference_docs/SIMD_API/基础API/同步控制/"

# 查 Reg 域专属（910D/A5）
find "./references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/" -name "*.md"
grep -rl "RegTensor\|asc_vf_call" "./references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/"
```

### cat — 直接阅读

```bash
# 看索引
cat "./references/api_reference_docs/INDEX.md"
cat "./references/api_reference_docs/Ascend_C_API列表.md"

# 读特定 API
cat "./references/api_reference_docs/SIMD_API/基础API/Memory矢量计算/基础算术/Sqrt.md"
cat "./references/api_reference_docs/SIMD_API/基础API/Memory数据搬运/DataCopy/"   # 目录
cat "./references/api_reference_docs/SIMD_API/基础API/同步控制/核内同步/SetFlag_WaitFlag（ISASI）.md"
cat "./references/api_reference_docs/SIMD_API/基础API/资源管理/Pipe和Que框架/TQue/AllocTensor.md"
cat "./references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/寄存器数据类型/RegTensor.md"
```

## 组合查询模式

```bash
# find + cat: 找到文件直接读
find "./references/api_reference_docs" -name "Sqrt.md" -exec cat {} \;

# grep + xargs cat: 搜函数名然后读上下文
grep -rl "void Sqrt" "./references/api_reference_docs/" | xargs cat

# grep 交集: 多关键词
grep -rl "DataCopy" "./references/api_reference_docs/" | xargs grep -l "Pad"

# INDEX 导航: 先看索引找到路径
cat "./references/api_reference_docs/INDEX.md" | grep -i "matmul"
cat "./references/api_reference_docs/INDEX.md" | grep -i "reg"     # 找 Reg 域 API

# Memory 域 vs Reg 域同名 API 同时读
for f in $(find "./references/api_reference_docs" -name "Sqrt.md"); do echo "=== $f ==="; cat "$f"; done
```
