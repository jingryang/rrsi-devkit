# AscendC Profiling Metrics Reference

## kernel_details.csv Full Schema

| Column           | Type  | Description                |
|------------------|-------|----------------------------|
| Device_id        | int   | NPU device ID              |
| Model ID         | int   | Internal model identifier  |
| Task ID          | int   | Task scheduling ID         |
| Stream ID        | int   | CUDA-like stream ID        |
| Name             | str   | Operator/kernel name       |
| Type             | str   | Operator type              |
| OP State         | str   | dynamic/static shape       |
| Accelerator Core | str   | AI_VECTOR_CORE / AI_CORE   |
| Start Time(us)   | float | Absolute start timestamp   |
| Duration(us)     | float | Total execution duration   |
| Wait Time(us)    | float | Time waiting in queue      |
| Block Dim        | int   | Number of cores used       |
| Input Shapes     | str   | Input tensor dimensions    |
| Input Data Types | str   | FP16/FP32/BF16 etc         |
| Output Shapes    | str   | Output tensor dimensions   |

### AIV (AI Vector Core) Metrics

| Metric                | Description                          |
|-----------------------|--------------------------------------|
| `aiv_time(us)`        | Total time on vector core            |
| `aiv_total_cycles`    | Total cycle count                    |
| `aiv_vec_time(us)`    | Vector unit execution time           |
| `aiv_vec_ratio`       | Vector compute utilization (0.0-1.0) |
| `aiv_scalar_time(us)` | Scalar unit execution time           |
| `aiv_scalar_ratio`    | Scalar compute utilization           |
| `aiv_mte2_time(us)`   | MTE2 (GM→UB) transfer time           |
| `aiv_mte2_ratio`      | MTE2 utilization                     |
| `aiv_mte3_time(us)`   | MTE3 (UB→GM) transfer time           |
| `aiv_mte3_ratio`      | MTE3 utilization                     |
| `aiv_icache_miss_rate`| Instruction cache miss rate          |

### AIC (AI Core / Cube Core) Metrics

| Metric                | Description                    |
|-----------------------|--------------------------------|
| `aicore_time(us)`     | Total time on cube core        |
| `aic_total_cycles`    | Total cycle count              |
| `aic_mac_time(us)`    | Matrix multiply-accumulate time|
| `aic_mac_ratio`       | MAC unit utilization           |
| `aic_scalar_time(us)` | Scalar processing time         |
| `aic_scalar_ratio`    | Scalar utilization             |
| `aic_mte1_time(us)`   | MTE1 (L1→L0) transfer time     |
| `aic_mte1_ratio`      | MTE1 utilization               |
| `aic_mte2_time(us)`   | MTE2 (GM→L1) transfer time     |
| `aic_mte2_ratio`      | MTE2 utilization               |
| `aic_fixpipe_time(us)`| Fixed-point pipeline time      |
| `aic_fixpipe_ratio`   | Fixpipe utilization            |
| `aic_icache_miss_rate`| Instruction cache miss rate    |
| `cube_utilization(%)` | Overall cube utilization       |

## Understanding Ratios

Ratio metrics indicate what percentage of execution time was spent on each pipeline stage. Since pipelines can execute in parallel, **ratios can sum to more than 100%**.

### Interpretation Guide

```text
Ratio > 0.7 (70%): This pipeline dominates execution
Ratio 0.3-0.7: Significant contribution
Ratio < 0.3: Not the bottleneck
```

### Common Patterns

#### Pattern 1: Compute-bound (vector)

```text
aiv_vec_ratio: 0.75+
aiv_mte2_ratio: <0.2
aiv_mte3_ratio: <0.2
```

Optimization: Algorithm improvement, precision reduction

#### Pattern 2: Memory-bound (input)

```text
aiv_vec_ratio: <0.5
aiv_mte2_ratio: 0.4+
```

Optimization: Increase tile size, reduce data movement

#### Pattern 3: Memory-bound (output)

```text
aiv_vec_ratio: <0.5
aiv_mte3_ratio: 0.4+
```

Optimization: Fuse downstream operations

#### Pattern 4: Scalar overhead

```text
aiv_scalar_ratio: 0.35+
```

Optimization: Vectorize control flow

## api_statistic.csv Reference

| Column      | Description               |
|-------------|---------------------------|
| Level       | acl / node                |
| API Name    | ACL API function name     |
| Time(us)    | Total accumulated time    |
| Count       | Number of invocations     |
| Avg(us)     | Average per-call time     |
| Min/Max(us) | Range of call durations   |
| Variance    | Timing variance           |

### Key APIs to Monitor

| API                                 | Description     | High Time Indicates     |
|-------------------------------------|-----------------|-------------------------|
| `aclnnXxx`                          | Kernel wrapper  | Kernel launch overhead  |
| `aclnnXxxGetWorkspaceSize`          | Workspace query | Tiling complexity       |
| `aclrtLaunchKernelWithHostArgs`     | Kernel launch   | Launch overhead         |
| `aclrtSynchronizeDeviceWithTimeout` | Sync barrier    | Wait time               |
