# 硬件规格计算公式手册

## 概述

本文档提供基于硬件定量参数的关键计算公式，供 Agent 在优化决策中使用。
所有公式中的具体数值从 `chips/ascend_910b.json` 读取。

## 0. 从 ini 参数计算带宽和算力

ini 文件中 `memory_rates` 单位为 **Bytes/cycle**，`cube_freq` 单位为 **MHz**。

```python
def calc_bandwidth_from_ini(rate_bytes_per_cycle, freq_mhz):
    """
    从 ini 参数计算带宽 (GB/s)

    Args:
        rate_bytes_per_cycle: ini 中的 rate 值（如 ddr_rate=32）
        freq_mhz: ini 中的 cube_freq（如 1800）

    Returns:
        bandwidth_gbps: 带宽 (GB/s)

    Example:
        910B3: ddr_rate=32, freq=1800
        → 32 × 1800 / 1000 = 57.6 GB/s per core
    """
    return rate_bytes_per_cycle * freq_mhz / 1000


def calc_vector_tflops(vec_calc_size_bytes, freq_mhz, dtype_size, core_count):
    """
    从 ini 参数计算 Vector 峰值算力

    Args:
        vec_calc_size_bytes: ini 中的 vec_calc_size（如 128）
        freq_mhz: cube_freq
        dtype_size: 元素字节数（fp16=2, fp32=4）
        core_count: 核数（对 Gen2 用 vector_core_cnt）

    Returns:
        aggregate_tflops

    Example:
        910B3 fp16: 128/2 × 1800MHz × 2(FMA) / 1e6 = 0.2304 TFLOPS/core
        × 40 vector_cores = 9.216 TFLOPS
    """
    elements_per_cycle = vec_calc_size_bytes // dtype_size
    per_core_tflops = elements_per_cycle * freq_mhz * 2 / 1e6  # ×2 for FMA
    return per_core_tflops * core_count


def calc_cube_tflops(m, n, k, freq_mhz, core_count):
    """
    从 ini 参数计算 Cube 峰值算力

    Args:
        m, n, k: cube_m/n/k_size（均为 16）
        freq_mhz: cube_freq
        core_count: cube_core_cnt

    Returns:
        aggregate_tflops

    Example:
        910B3: 16×16×16 × 2 × 1800 / 1e6 = 14.746 TFLOPS/core
        × 20 cores = 294.912 TFLOPS
    """
    macs_per_cycle = m * n * k
    per_core_tflops = macs_per_cycle * 2 * freq_mhz / 1e6
    return per_core_tflops * core_count
```

## 1. Tiling 计算公式

### 1.1 最大 Tile 大小

```python
def calc_max_tile(ub_usable_bytes, buffer_num, pipe_count, dtype_size, block_size=None):
    """
    计算单次处理的最大 tile 元素数

    Args:
        ub_usable_bytes: UB 可用字节数 (= ub_size - system_reserve)
        buffer_num: 缓冲数 (1=单缓冲, 2=双缓冲)
        pipe_count: 流水线中同时占用 UB 的 tensor 数量
                    (输入队列数 + 输出队列数 + 临时 TBuf 数)
        dtype_size: 每个元素的字节数 (fp16=2, fp32=4, int8=1)
        block_size: 对齐粒度（元素数），默认 = 32 / dtype_size

    Returns:
        aligned_tile_elements: 对齐后的 tile 元素数
    """
    if block_size is None:
        block_size = 32 // dtype_size  # 32B alignment

    raw_tile = ub_usable_bytes // (buffer_num * pipe_count * dtype_size)
    aligned_tile = (raw_tile // block_size) * block_size

    return aligned_tile
```

### 1.2 应用示例

```python
# 910B3 Gen2 参数（从 ascend_910b.json 读取）
UB_SIZE = 196608       # 192KB
UB_RESERVE = 0         # 系统预留待确认，先按 0
UB_USABLE = UB_SIZE - UB_RESERVE  # 196608 bytes
BUFFER_NUM = 2          # 双缓冲
PIPE_COUNT = 3          # 1 input + 1 output + 1 temp
DTYPE_SIZE = 2          # fp16

max_tile = calc_max_tile(UB_USABLE, BUFFER_NUM, PIPE_COUNT, DTYPE_SIZE)
# = 196608 / (2 × 3 × 2) = 16384 元素
# 已经是 16 的倍数（fp16 block_size=16），无需再对齐
# → 16384 个 fp16 元素 = 32KB per buffer

# 对比 910B Gen1:
# UB_SIZE = 262144 (256KB)
# max_tile = 262144 / (2 × 3 × 2) = 21845 → 对齐到 21840
```

### 1.3 Tile 数量与核间分配

```python
def calc_tiling_plan(total_elements, tile_elements, core_count):
    """
    计算 tile 总数和核间分配

    Returns:
        total_tiles: 总 tile 数
        tiles_per_core: 每核 tile 数
        last_tile_elements: 最后一个 tile 的元素数（可能不满）
        core_utilization: 核利用率（实际使用核数 / 总核数）
    """
    total_tiles = (total_elements + tile_elements - 1) // tile_elements
    tiles_per_core = (total_tiles + core_count - 1) // core_count
    used_cores = min(total_tiles, core_count)
    last_tile = total_elements - (total_tiles - 1) * tile_elements

    return {
        "total_tiles": total_tiles,
        "tiles_per_core": tiles_per_core,
        "last_tile_elements": last_tile,
        "used_cores": used_cores,
        "core_utilization": used_cores / core_count,
    }
```

## 2. 带宽利用率计算

### 2.1 实际带宽

```python
def calc_actual_bandwidth(total_bytes, transfer_time_us):
    """
    计算实际搬运带宽

    Args:
        total_bytes: 搬运数据总字节数
        transfer_time_us: 搬运耗时（微秒）

    Returns:
        bandwidth_gbps: 实际带宽 (GB/s)
    """
    return total_bytes / (transfer_time_us * 1e-6) / 1e9
```

### 2.2 带宽利用率

```python
def calc_bandwidth_utilization(actual_gbps, peak_gbps):
    """
    计算带宽利用率

    Args:
        actual_gbps: 实际带宽
        peak_gbps: 理论峰值带宽（从 ascend_910b.json 读取）

    Returns:
        utilization: 利用率 (0.0 ~ 1.0)
    """
    return actual_gbps / peak_gbps
```

### 2.3 数据搬运量估算

```python
def estimate_transfer_bytes(input_shapes, output_shapes, dtype_size,
                            num_passes=1, has_intermediate_gm=False,
                            intermediate_bytes=0):
    """
    估算算子的总数据搬运量

    Args:
        input_shapes: 输入 tensor shape 列表 [(N, C, H, W), ...]
        output_shapes: 输出 tensor shape 列表
        dtype_size: 数据类型字节数
        num_passes: 需要扫描输入数据的次数（如 LayerNorm 需 2 pass）
        has_intermediate_gm: 是否有 GM 中间读写
        intermediate_bytes: GM 中间读写字节数

    Returns:
        total_bytes: 总搬运字节数
    """
    import math
    input_bytes = sum(math.prod(s) * dtype_size for s in input_shapes) * num_passes
    output_bytes = sum(math.prod(s) * dtype_size for s in output_shapes)
    total = input_bytes + output_bytes
    if has_intermediate_gm:
        total += intermediate_bytes
    return total
```

## 3. 计算利用率

### 3.1 FLOPS 估算

```python
def estimate_flops(op_counts):
    """
    估算算子总浮点运算次数

    Args:
        op_counts: dict, 各操作的 (调用次数, 每次处理元素数)
            键为操作名, 值为 (count, elements)

    FLOPS 系数参考:
        Add/Sub/Mul/Div/Abs/Neg/Muls/Adds: 1 FLOP/element
        Exp/Log: ~10 FLOPS/element (多项式近似)
        Sqrt/Rsqrt: ~5 FLOPS/element
        Compare/Select: 2 FLOPS/element
        ReduceSum(N): N-1 FLOPS
        FMA (a*b+c): 2 FLOPS/element
    """
    COST = {
        "Add": 1, "Sub": 1, "Mul": 1, "Div": 1,
        "Abs": 1, "Neg": 1, "Muls": 1, "Adds": 1,
        "Exp": 10, "Log": 10,
        "Sqrt": 5, "Rsqrt": 5,
        "Compare": 2, "Select": 2,
        "FMA": 2,
    }
    total = 0
    for op_name, (count, elements) in op_counts.items():
        if op_name.startswith("Reduce"):
            total += count * (elements - 1)
        else:
            cost = COST.get(op_name, 1)
            total += count * elements * cost
    return total
```

### 3.2 计算利用率

```python
def calc_compute_utilization(total_flops, compute_time_us, peak_tflops):
    """
    计算计算利用率

    Args:
        total_flops: 总浮点运算次数
        compute_time_us: 计算耗时（微秒）
        peak_tflops: 峰值算力 TFLOPS（从 ascend_910b.json 读取）

    Returns:
        utilization: 计算利用率 (0.0 ~ 1.0)
        actual_tflops: 实际算力 (TFLOPS)
    """
    actual_tflops = total_flops / (compute_time_us * 1e-6) / 1e12
    utilization = actual_tflops / peak_tflops
    return {
        "utilization": min(utilization, 1.0),  # cap at 100%
        "actual_tflops": actual_tflops,
    }
```

## 4. 双缓冲收益预估

```python
def estimate_double_buffer_speedup(mte2_time_us, compute_time_us, mte3_time_us,
                                    current_buffer_num=1):
    """
    预估从单缓冲升级到双缓冲的理论加速比

    单缓冲: total = (mte2 + compute + mte3) × N
    双缓冲: total ≈ max(mte2, compute, mte3) × (2N) + startup + drain
            其中 tile 数翻倍但重叠执行

    Args:
        mte2_time_us: 单 tile MTE2 搬入时间
        compute_time_us: 单 tile 计算时间
        mte3_time_us: 单 tile MTE3 搬出时间
        current_buffer_num: 当前 buffer 数

    Returns:
        estimated_speedup: 预估加速比
    """
    if current_buffer_num >= 2:
        return 1.0  # 已经是双缓冲

    serial_time = mte2_time_us + compute_time_us + mte3_time_us
    # 双缓冲后 tile 数翻倍，但 pipeline 重叠
    pipeline_bottleneck = max(mte2_time_us, compute_time_us, mte3_time_us)
    # 粗略估算（忽略 startup/drain）
    overlap_time = pipeline_bottleneck * 2  # 翻倍 tile 但重叠

    speedup = serial_time / overlap_time
    return speedup
```

## 5. 负载均衡分析

```python
def analyze_load_balance(per_core_times_us, core_count):
    """
    分析多核负载均衡

    Args:
        per_core_times_us: 各核执行时间列表
        core_count: 总核数

    Returns:
        load_balance analysis
    """
    used = len(per_core_times_us)
    if used == 0:
        return {"score": 0, "issue": "no cores used"}

    fastest = min(per_core_times_us)
    slowest = max(per_core_times_us)
    balance_score = fastest / slowest if slowest > 0 else 1.0
    idle_cores = core_count - used
    wasted_time_us = sum(slowest - t for t in per_core_times_us)

    return {
        "balance_score": balance_score,
        "fastest_core_us": fastest,
        "slowest_core_us": slowest,
        "idle_cores": idle_cores,
        "core_utilization": used / core_count,
        "wasted_time_us": wasted_time_us,
        "verdict": (
            "excellent" if balance_score > 0.9 else
            "good" if balance_score > 0.7 else
            "poor" if balance_score > 0.5 else
            "critical"
        ),
    }
```
