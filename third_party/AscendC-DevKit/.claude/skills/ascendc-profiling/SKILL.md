---
name: ascendc-profiling
description: "AscendC/NPU operator performance profiling and analysis. Supports two modes: (1) torch_npu.profiler for full profiling with kernel_details.csv and timeline; (2) msprof op_summary CSV for quick bottleneck diagnosis with structured JSON output. Use when: user asks '性能分析', 'profiling', '性能瓶颈', '算子太慢', '怎么优化性能', or analyzing profiling CSV output."
---

# AscendC Profiling

Performance profiling and analysis for AscendC operators on Ascend NPU. 支持两种分析模式：

| 模式 | 适用场景 | 入口脚本 |
|------|---------|---------|
| **方式一：torch_npu.profiler** | 完整 profiling，产出 kernel_details.csv、op_statistic.csv、timeline 等 | `scripts/profiling_utils.py` |
| **方式二：msprof op_summary CSV** | 快速瓶颈诊断，输出结构化 JSON 和 `profiling_one_liner` | `scripts/analyze_profiling.py` |

## Skill Structure

```text
ascendc-profiling/
├── SKILL.md
├── references/
│   └── metrics.md              # 详细指标定义
└── scripts/
    ├── profiling_utils.py      # 方式一：torch_npu.profiler reusable utilities
    └── analyze_profiling.py    # 方式二：msprof op_summary CSV bottleneck diagnosis
```

---

## 方式一：torch_npu.profiler 完整 Profiling

### Quick Start

```python
import sys
sys.path.insert(0, "skills/ascendc-profiling/scripts")

from profiling_utils import (
    create_profiler,
    profile_operator,
    analyze_kernel_details,
    diagnose_bottleneck,
    print_summary,
)
```

### Profiling Code Pattern

```python
import torch_npu

# Configure profiler
experimental_config = torch_npu.profiler._ExperimentalConfig(
    aic_metrics=torch_npu.profiler.AiCMetrics.PipeUtilization,
    profiler_level=torch_npu.profiler.ProfilerLevel.Level1,
)

profiler = torch_npu.profiler.profile(
    activities=[
        torch_npu.profiler.ProfilerActivity.CPU,
        torch_npu.profiler.ProfilerActivity.NPU,
    ],
    with_stack=False,
    profile_memory=False,
    with_modules=False,
    experimental_config=experimental_config,
    on_trace_ready=torch_npu.profiler.tensorboard_trace_handler(profile_dir)
)

# Profile the operator
profiler.start()
for _ in range(iterations):
    output = operator(inputs)
profiler.stop()
```

### Profiling Output Structure

```text
profile_dir/
└── {hostname}_{pid}_{timestamp}_ascend_pt/
    └── ASCEND_PROFILER_OUTPUT/
        ├── kernel_details.csv    # Per-kernel execution metrics
        ├── op_statistic.csv      # Operator-level statistics
        ├── operator_details.csv  # Host/device timing breakdown
        ├── api_statistic.csv     # ACL API call statistics
        └── trace_view.json       # Timeline for tensorboard
```

### Key Metrics

#### kernel_details.csv

| Metric             | Description                                |
|--------------------|--------------------------------------------|
| `Duration(us)`     | Total kernel time                          |
| `Block Dim`        | Number of cores used                       |
| `aiv_vec_ratio`    | Vector compute utilization                 |
| `aiv_scalar_ratio` | Scalar compute utilization                 |
| `aiv_mte2_ratio`   | MTE2 (GM→UB) memory transfer utilization   |
| `aiv_mte3_ratio`   | MTE3 (UB→GM) memory transfer utilization   |
| `aic_mac_ratio`    | Cube MAC utilization (for matmul/conv ops) |

#### op_statistic.csv

| Field              | Description                  |
|--------------------|------------------------------|
| `Count`            | Number of kernel invocations |
| `Total Time(us)`   | Accumulated execution time   |
| `Avg Time(us)`     | Average per-invocation       |
| `Min/Max Time(us)` | Variance indicator           |

### Bottleneck Diagnosis

Analyze pipeline utilization ratios to identify bottlenecks:

| Dominant Ratio                 | Bottleneck Type      | Optimization Direction                     |
|--------------------------------|----------------------|--------------------------------------------|
| `aiv_vec_ratio` highest        | Compute bound        | Optimize algorithm, reduce redundant ops   |
| `aiv_mte2_ratio` highest       | Memory input bound   | Reduce data movement, increase tile size   |
| `aiv_mte3_ratio` highest       | Memory output bound  | Fuse downstream operations                 |
| `aiv_scalar_ratio` significant | Scalar overhead      | Vectorize control flow                     |
| High variance (Max >> Min)     | Scheduling issue     | Check tiling balance                       |

Note: Ratios indicate relative pipeline activity. The dominant ratio(s) point to bottlenecks.

### Analysis Workflow

1. **Run profiling** using the code pattern above (wrap operator call with profiler.start/stop)
2. **Locate output** in `profile_dir/{hostname}_{pid}_{timestamp}_ascend_pt/ASCEND_PROFILER_OUTPUT/`
3. **Read op_statistic.csv** for summary: avg time, count, variance
4. **Read kernel_details.csv** for pipeline utilization breakdown
5. **Identify bottleneck** using ratio patterns above
6. **Apply optimization** based on bottleneck type

### Performance Optimization Checklist

Based on bottleneck type:

**Compute Bound** (`aiv_vec_ratio` dominant):

- Reduce redundant operations
- Use fused APIs (e.g., `Axpy` instead of `Mul + Add`)
- Leverage half-precision when possible

**Memory Bound** (`aiv_mte*_ratio` dominant):

- Increase tile size to reduce data movement frequency
- Enable double buffering: `BUFFER_NUM = 2`
- Reuse TBuf across stages

**Scalar Overhead** (`aiv_scalar_ratio` significant):

- Vectorize control flow with `Select`/`Compare`
- Use mask operations for tail handling
- Minimize EnQue/DeQue frequency

### Example Analysis Output

```text
Performance Summary:
  Kernel: MyOperator
  Avg Duration: 312.3 us
  Block Dim: 40 (AI Vector Cores)

Pipeline Utilization:
  Vector Compute: 74.4%
  Scalar Compute: 34.3%
  MTE2 (input):   7.2%
  MTE3 (output):  7.2%

Diagnosis: Compute-bound kernel (vector dominant) with noticeable scalar activity.
Recommendation: Analyze scalar code paths for vectorization opportunities.
```

详细指标定义见 [references/metrics.md](references/metrics.md)。

---

## 方式二：msprof op_summary CSV 快速诊断

自动读取 msprof 产出的 `op_summary_*.csv`，提取 AIV/AIC 流水线各阶段占比，按优先级判断性能瓶颈类型（`scalar_bound` / `memory_bound` / `compute_bound` / `icache_bound` / `output_bound` / `balanced`），输出结构化 JSON 和单行摘要（`profiling_one_liner`），供世界模型节点更新和子 agent prompt 注入使用。

### 调用方式

#### 从 profiling 目录自动搜索（推荐）

```bash
python3 skills/ascendc-profiling/scripts/analyze_profiling.py \
    <profiling_dir> \
    --task-type vector \
    --output result.json
```

脚本自动搜索 CSV 文件，按以下优先级：

1. `profiling_dir/ModelNew_*/PROF_*/mindstudio_profiler_output/op_summary_*.csv` (msprof native)
2. `profiling_dir/*_ascend_pt/ASCEND_PROFILER_OUTPUT/op_summary_*.csv` (torch_npu.profiler)
3. 递归搜索 `op_summary_*.csv`
4. **Fallback**: `kernel_details.csv` (torch_npu.profiler 有时只产出此格式)

#### 直接指定 CSV 文件

```bash
python3 skills/ascendc-profiling/scripts/analyze_profiling.py \
    --op-summary /path/to/op_summary_xxx.csv \
    --task-type vector \
    --output result.json
```

#### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `profiling_dir` | (与 --op-summary 二选一) | profiling 根目录 |
| `--op-summary` | None | 直接指定 CSV 文件路径 |
| `--task-type` | `vector` | `vector` / `cube` / `cv-mix` |
| `--output` | stdout | 输出 JSON 路径 |

### 输出字段说明

```json
{
  "status": "success",
  "csv_format": "op_summary",
  "task_type": "vector",
  "task_duration_us": 5.36,
  "pipeline": {
    "mte2_pct": 45.0,
    "vec_pct": 37.0,
    "mte3_pct": 18.0,
    "scalar_pct": 12.0,
    "icache_miss_rate": 0.05
  },
  "bottleneck": "memory_bound",
  "bottleneck_description": "MTE2 搬入占 45.0%，带宽是主要瓶颈",
  "recommended_strategies": ["P1", "P2", "P10"],
  "optimization_hints": [
    "增大 tile_size 减少分块次数，降低 MTE2 调用频率",
    "启用双缓冲 (P1)，隐藏搬运延迟",
    "向量化数据加载 (P10)，提升带宽利用率"
  ],
  "profiling_one_liner": "MTE2:45.0% | Vec:37.0% | MTE3:18.0% | Scalar:12.0% | 瓶颈:memory_bound → 推荐 P1,P2,P10"
}
```

**关键字段说明**:

| 字段 | 用途 |
|------|------|
| `bottleneck` | 瓶颈类型标识，用于世界模型 `optimization_type` 映射 |
| `recommended_strategies` | 按优先级排序的策略 ID 列表，直接作为节点 `strategy_combination` |
| `optimization_hints` | 人类可读的优化建议，注入子 agent prompt |
| `profiling_one_liner` | 单行摘要，用于世界模型概览和日志输出 |
| `pipeline` | 原始流水线占比，供深度分析使用 |

### 瓶颈诊断规则

#### Vector 算子（aiv_* 列，按优先级判断）

| 条件 | 瓶颈类型 | 推荐策略 | optimization_type |
|------|---------|---------|-------------------|
| `aiv_scalar_ratio > 0.40` | `scalar_bound` | P67, P68, P5 | `tiling` |
| `aiv_mte2_ratio > 0.45` | `memory_bound` | P1, P10, P2 | `bandwidth` |
| `aiv_vec_ratio > 0.60` | `compute_bound` | P69, D1, P84 | `tiling` |
| `aiv_icache_miss_rate > 0.10` | `icache_bound` | P8, P54 | `algorithm` |
| `aiv_mte3_ratio > 0.35` | `output_bound` | P1, P8, P56 | `bandwidth` |
| 其余 | `balanced` | P4, P2, P7 | `tiling` |

注：`aiv_*_ratio` 列为 0–1 之间的浮点数（不是百分比），直接与阈值比较。

#### Cube 算子（aic_* 列）

| 条件 | 瓶颈类型 | 推荐策略 | optimization_type |
|------|---------|---------|-------------------|
| `cube_utilization(%) < 50` | `memory_bound` | P2, P46, P71 | `bandwidth` |
| `aic_mac_ratio > 0.70` | `compute_bound` | P13, P2, P72 | `tiling` |
| 其余 | `balanced` | P4, P47 | `tiling` |

#### CV-Mix 算子（AIC + AIV 联合诊断）

CV-Mix 算子需分别诊断 AIC 侧和 AIV 侧，若两侧耗时严重不匹配，额外识别 **cube-vector mismatch** 瓶颈：

| 条件 | 瓶颈类型 | 推荐策略 | optimization_type |
|------|---------|---------|-------------------|
| AIC 耗时 / AIV 耗时 > 2.0 或 < 0.5 | `cv_mismatch` | P14, P73, P51 | `algorithm` |

### 复合瓶颈诊断（增强）

单一指标不足以描述所有场景，以下组合诊断提供更高精度：

| 指标组合 | 复合瓶颈 | 根因 | 追加策略 |
|---------|---------|------|---------|
| 高 vec_ratio + 高 bank_cflt | VEC 被 bank conflict 放大 | bank conflict 阻塞 Vector | 追加 P65 |
| 高 mte2 + 低 L2 hit rate | L2 未命中导致搬运慢 | 数据局部性差 | 追加 P52, P74 |
| 高 mte2 + 高 mte3 | 双向搬运饱和 | tile_size 过小 | 追加 P56 |
| 高 fixpipe_ratio | 地址未 512B 对齐 | GM 地址不对齐 | 追加 P66 |
| 高 scalar + 低 Task Duration | 数据量过小，头开销大 | 核数过多/数据量过小 | 追加 P4, P54 |
| 各核耗时差异大 | Tiling 切分不均 | 负载不均衡 | 追加 P4, P11 |
| 无明显瓶颈 + 高 Duration | 流水线气泡 | Cube/Vector 互等 | 追加 P14, P19, P82 |

### 策略映射深度参考

完整的瓶颈 → 策略映射表（含优先级、预期收益、实施要点）见：

**`references/bottleneck_strategy_mapping.md`**

该文档将每种瓶颈类型映射到进化策略中的完整策略组合，包含：
- Primary 策略（必须实施）
- Secondary 策略（锦上添花）
- 禁忌策略（避免使用）
- 预期收益范围
- 实施要点和避坑指南

### 与进化流程的集成

#### 1. 世界模型节点初始化（步骤 3.7）

在初始化世界模型时，将 `recommended_strategies` 作为策略导向节点的初始 `strategy_combination`：

```python
# 示例：baseline profiling 后初始化节点
node = {
    "id": "n1",
    "mode": "strategy_guided",
    "strategy_combination": profiling_result["recommended_strategies"],  # ["P1", "P2", "P10"]
    "optimization_type": _map_bottleneck_to_opt_type(profiling_result["bottleneck"]),  # "bandwidth"
    ...
}
```

#### 2. 子 Agent Prompt 注入（步骤 4.3）

将 `profiling_one_liner`、`bottleneck`、`recommended_strategies` 注入 ops-partial 子 agent 的 `[Profiling Context]` 部分，指导代码修改方向。

#### 3. 瓶颈迁移检测（步骤 4.4.1）

逐轮对比父节点和子节点的 `bottleneck` 类型：
- 若瓶颈从 `memory_bound` 迁移到 `compute_bound`，说明 P1/P2 生效，后续应追加 P69/D1
- 若瓶颈未迁移，说明当前策略未触及根因，应调整策略组合

### 兜底策略

| 场景 | 处理 |
|------|------|
| CSV 文件缺失 | `status: "error"`，抛出异常，不降级 |
| 列名不存在或值为空 | 该列按 0.0 处理，不抛异常 |
| 所有 AI_CPU 行被过滤后无剩余行 | `status: "error"`，抛出异常 |
| `kernel_details.csv` 格式 | `csv_format: "kernel_details"`，`bottleneck: "balanced"`，建议深度 profiling |
| 列名兼容 | 自动处理 `Task Duration(us)`/`Duration(us)` 和 `Task Type`/`Type` |

**调用方应检查 `status` 字段，失败时抛出异常而非静默跳过，确保 profiling 数据质量。**

---

## 模式选择建议

| 场景 | 推荐模式 |
|------|---------|
| 开发调试期，查看完整执行 timeline | 方式一 |
| 进化优化循环中快速判断瓶颈 | 方式二 |
| 需要 PyTorch 集成（Python API） | 方式一 |
| 已有 msprof CSV 想离线分析 | 方式二 |
| 给世界模型节点注入 `profiling_one_liner` | 方式二 |
