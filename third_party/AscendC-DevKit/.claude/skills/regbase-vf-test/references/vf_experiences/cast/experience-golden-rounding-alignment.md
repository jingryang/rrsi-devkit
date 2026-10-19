# 位级 golden 三要素 + 极端值探针

## 适用判据

任何涉及浮点计算 + cast 的 VF（cast / normalize / elementwise / dequant），需要与 kernel **位级一致**的 golden（`max_diff=0.0`）。判据统一走 `SingleOperatorLaunch.precision_check.compare_tensor`：纯位级目标传 `threshold=0.0`（bit-exact，区分 ±0.0/NaN payload/Inf 符号）；不可位级对齐时才用默认生态 MERE/MARE 阈值——**不要用默认阈值放行 cast 的 half-ulp 舍入差异**（默认 fp16 阈值 2^-10 有 10×MARE 余量，会掩盖舍入模式缺陷）。

## 关键实现要点（golden 位级三要素）

1. **单除链**：`np.float32(1.0)/np.float32(denom)` 单除——与 kernel `1.0f/(float)denom` 同 IEEE 单精度除法；**禁止**先乘后除 / 二次求倒数。
2. **乘法顺序镜像**：kernel 指令序（`Muls` 先、`Mul` 后；或"先标量后向量"）必须与 numpy `(a*inv).astype(f32)*invkw` 逐序一致——fp32 乘法不交换，顺序差可差 1 ulp。
3. **RNE cast**：numpy `astype(np_dtype)`（RN）与硬件 `RoundMode::CAST_RINT`（RNE）位级一致（多代 VF 实证）；`errstate(over='ignore')`。

**叠加规则**（accumulate/reduce 场景）：`acc = fp32(part_init); for w': acc = fp32(acc + x[w'])` 左折叠逐元素累加（含初值），**非**"段和再一次性加"——浮点加法不结合。

## 极端值探针（NO_SAT / inf 透传验证）

| 探针 | 验证目标 |
|------|----------|
| `1e8 / -1e8` | fp16 ±inf 饱和透传 |
| `65519.9` | RNE 越过 65504 → inf |
| `65504.0 / -65505.0` | 有限/inf 边界 |
| `3e38` | bf16 有限透传（fp32 max 内） |

**max_diff 统计**：含 inf 时 `np.abs(inf-inf)=nan` 污染——`d[np.isfinite(d)].max()` 只统计有限元素；±inf 一致性交给 `compare_tensor`（bit-exact 路径对 ±inf 符号区分）覆盖。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| 乘法顺序不同 → 1 ulp diff | fp32 不交换 | numpy 逐序镜像 kernel 指令序 |
| `np.max` 报 nan | inf 探针参与差值统计 | 有限元素掩码 + `compare_tensor`（bit-exact 覆盖 inf） |
| bf16 golden 对不上 | numpy 无原生 bf16 | `ttk.utilities.dtypes.numpy_bfloat16()`；随机数先 fp32 uniform 再 astype |

## 横切标签

`multi-dtype`。

## 实证来源

- `adaptive_avg_pool_3d` `normalize_cast_vf` / `normalize_cast_out_vf`（30/30+30/30 max_diff=0.0，含 SIMT 单除链）
- `moe_finalize_routing` `cast_output_vf`（astype RN 与硬件 RNE 位级一致实证）
