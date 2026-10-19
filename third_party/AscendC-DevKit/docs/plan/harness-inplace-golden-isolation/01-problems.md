# harness in-place golden 输入污染 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 触发算子：`aten_mish_inplace`（level1），运行 `20260918-100406-d6f1b0`（verifier）。
> 涉及代码：`adapters/npu/_harness_template.py`（harness 生成：golden 调用链）。
> 判定参照 cann-bench `kernel_eval/utils/compare.py`、`checkers/relative_error_checker.py`（只读，非本仓 bug）。

## P1 — precision_debug 判 20/20，cann-bench eval 判 18/20

### 现象
同一次 codegen 交付的算子在两阶段判定不一致：

- precision_debug：`artifacts/debug/aten_mish_inplace/precision_report.md` = **20/20 passed**（迭代 1 轮，状态 passed，无待处理失败用例）。
- cann-bench eval：`subprocess/cannbench_eval_aten_mish_inplace.partial.json/atenmishinplace_eval_20260918_123508.json`
  = **passed_cases=18 / failed_cases=2**，overall_score=47.0。失败用例 `level1/aten_mish_inplace_5`
  （fp32, 8192×8192, [-100,100]）与 `level1/aten_mish_inplace_20`（fp32, 2×3×17×1024×101, [-20,40]），
  error_msg 均 `精度不达标`（MERE/MARE 超阈 + 小值域/相消兜底 ❌，`failure_type=precision_mismatch`）。

即 debug 的 `20/20` 是**假收敛**，eval 的 18/20 才是真实结果（两例失败是真实的 kernel 精度问题，产权在 kernel/codegen 侧，非本问题范围）。

### 机制
harness 为对齐 cann-bench eval 的 `golden_precision=fp64_cpu` 语义，对**同一批输入对象**连续调用两次 golden：

1. native 参考（同精度 CPU 参考，喂比较器 `native_output`）——旧 `_harness_template.py:521`：`_golden_core(_torch_inputs, _attrs)`；
2. 权威 golden（fp64 真值）——旧 `_harness_template.py:538`：`_golden_core(_upcast_fp64(_torch_inputs), _attrs)`。

`_golden_core` 只做 `list(_inputs)` 浅拷贝后 bind 传参，**不复制张量**：

```python
def _golden_core(_inputs, _attrs):                       # 旧实现
    return _golden_raw(**bind_golden_args(_golden_raw, list(_inputs), _attrs))
```

而 `mutation_mode=in_place` 算子的 golden 会**原地写回入参并返回**（本例 golden.py：`x.copy_(y); return x`）。
于是第 1 次（native）调用把 `_torch_inputs` 改写为 `g(x)`，第 2 次（fp64 权威）实际算的是 **`g(g(x))`**。

harness 的 kernel 段用设备副本（`.npu()` / `.cpu()`）不受影响，故比较的是 `kernel = g(x)` vs `golden = g(g(x))`。

### 凭证（数值逐位复现）
debug `run_tests_iter-2/result.json`，case `level1/aten_mish_inplace_1`（fp16, 1024×1024, [-1,1]）：

| i | kernel_first10 | golden_first10 | `mish(kernel_first10[i])` |
|---|---|---|---|
| 0 | -0.27587890625 | -0.14109824610751645 | **-0.14109824610751645** |
| 1 | -0.0933837890625 | -0.05323015375462714 | **-0.05323015375462714** |
| 2 | 0.5419921875 | 0.41287408274005105 | **0.41287408274005105** |
| … | … | … | …（10/10 精确吻合）|

`golden_first10 == mish(kernel_first10)` 对 10 个元素全部逐位成立 ⇒ 权威 golden 确为 `g(g(x))`。

## P2 — 污染同时传导到 native 与权威两侧，使兜底判据被平凡满足

### 现象
同一 case（`aten_mish_inplace_1`）的 compare 计数：

- `small_value_error_count = 1375`，`small_value_cpu_error_count = 1375`，`small_value_total_count = 1448`；
- `cancel_error_count = 53118`，`cancel_cpu_error_count = 53118`，`cancel_total_count = 53118`。

`compare.py` 的小值域 / 相消兜底判据为 `NPU错误数 / max(CPU错误数, 1) ≤ 2`；两侧计数相等 ⇒ 比值恒 1 ⇒ 判通过。

### 机制
被污染的不只是权威 golden：native 参考 `_n_tensors` 取自同一次（第 1 次）调用后 `o.detach().cpu()` 的结果快照，
其值仍是 `g(x)`；而权威 golden 变成 `g(g(x))`。比较器内小值域/相消的 CPU 对照量正是 `|native − golden|`
（`compare.py` 的 `cpu_diff`），于是
`CPU错误数 = |g(x) − g(g(x))|` 与 `NPU错误数 = |kernel(=g(x)) − g(g(x))|` **同源同值**。
兜底判据本意是「候选不比同精度参考更差」，此时却退化为「候选与自身相等」的平凡成立。

即：污染**结构性**地让兜底判据失效，而不仅是抬高了误差数值。

## P3 — 影响面：所有 `mutation_mode=in_place` 且 golden 原地写回入参的算子

触发条件（三者同时）：

1. `golden_precision == 'fp64_cpu'`（`runner.py` 默认；决定是否发生第 2 次 golden 调用）；
2. golden 会原地改写入参（`mutation_mode=in_place` 的定义，`requirement.json` 权威）；
3. golden 调用路径复用同一批输入对象（CANN torch / CANN numpy / 独立 fallback 三条路径均如此）。

满足即**必然**发生双算。表现随算子而异：`g(g(x)) ≈ g(x)` 时表现为**假通过**（本例）；否则表面为**假失败**并触发一轮无意义的诊断/修复；`g` 幂等时无可见影响。

非 in-place 算子不受影响（golden 不改写入参）。

## 关联
- **引入来源**：`cannbench-precision-alignment`（step 85）引入「native + fp64 两遍 golden」结构，本次污染是该结构的副作用。
- **同族但不同维度**：`golden-precision-harness-eval-alignment` 记录的是 harness 与 eval 判定分裂中的「golden 参考**精度**」维度（原生 vs fp64）；本问题维度是「golden **输入**被原地改写」，二者独立。
- **eval 侧不受影响**：cann-bench `evaluator.py` 在跑 AI 算子前先 `tensors_to_fp64_cpu`（`tensor.cpu().double()` 新分配副本）算 golden，故 in-place golden 污染不到其输入；eval 判定可信。
- **codegen 交付侧不受影响**：plugin 按交付契约强制 `x.clone()` 后 return（`inplace-outplace-delivery-contract`），非真 in-place 写回调用方本体。
