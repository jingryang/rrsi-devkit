# run-cases result.json 解析参考（执行 / 失败判定 / failure_type 分类）

> baseline phase 的 run-cases 结果解析知识库：产物位置、result.json 结构、失败权威判据、
> failure_type 症状分类规则、指标提取、硬错误处理。供 Step 2（执行 run-cases 全量）与
> Step 4（交叉对比 + 构建 failed_case_queue）按需查阅。

## run-cases 执行与产物位置

`{test_command} --label baseline --iter 0` 执行后，CLI 自动落盘 `run.log` 与
`result.json`（通常在 `<workspace>/artifacts/debug/<op>/<label>_iter-N/`）；从 CLI
输出的 `log:` / `result:` 行提取 harness 产出的真实路径（不要用 tee 临时文件路径）。

## result.json 结构

### 顶层字段

`passed`、`max_diff`、`actual_ms`、`case_details`（list）、`dtype_thresholds`（dict）。

**超时额外字段**（`timed_out: true` 时存在，`case_details` 为空）：`timed_out`、
`timeout_sec`（本次实际看门狗秒数）、`tested_cases`（list，本次执行各用例的
`case_id` / `shape` / `max_input_elements`）——供评估「是否大 shape 超时」。

### case_details 条目结构

```json
{
  "case": "S-float16-1M-对齐-对称小值域 | baseline_kernels: DynamicQuant×1:1024x1024",
  "case_id": "level2/dynamic_quant_1",
  "diff": 1.0,
  "elapsed_ms": 278.705,
  "accuracy": {
    "passed": true,
    "threshold": 1.0,
    "mere": 0.0,
    "mare": 1.2e-7,
    "max_diff": 1.0,
    "error_msg": ""
  },
  "output_results": [
    {
      "index": 0,
      "name": "output_0",
      "dtype": "int8",
      "passed": true,
      "mismatch_count": 0,
      "total_count": 1048576,
      "diff": 1.0,
      "threshold": 1.0,
      "mere": 0.0,
      "mare": 1.2e-7,
      "dtype_category": "int",
      "small_value_error_count": 0,
      "cancel_error_count": 0,
      "kernel_first10": ["..."],
      "golden_first10": ["..."],
      "max_diff_location": {
        "flat_index": 1048576,
        "multi_index": [512, 2048],
        "kernel_value": 42.0,
        "golden_value": 43.0,
        "context_start": 1048571,
        "context_end": 1048582,
        "kernel_context": ["..."],
        "golden_context": ["..."]
      }
    }
  ]
}
```

- `accuracy.passed`：该 case 整体是否通过（所有 output 的 `passed` 按 AND 聚合）
- `output_results[].passed`：该 output 是否通过（cann-bench compare_tensors 判定，MERE/MARE + 小值域兜底 + 相消兜底）
- `output_results[].mismatch_count` / `total_count`：不匹配元素数 / 总元素数
- `output_results[].dtype_category`：`"int"` | `"float"`，整数类型精确匹配，浮点用 MERE/MARE
- `case_id`：cann-bench 格式 case 标识（`levelN/<name>_<N>`），可用于 `--case` 单用例重跑
- case 级 `error` / `input_shapes`：case 执行异常时存在（如 kernel exception、崩溃），该 case 即为失败

### 失败判定（权威）

不依赖顶层 `diff` 或固定阈值。**失败权威判据：`case_details[].accuracy.passed == false`
或 case 级 `error`**（runner 已按 proto `precision_thresholds` + cann-bench 语义逐输出
判定）。**禁止**自己造阈值（如固定 `diff > 1e-2` 会把 int8 量化输出的 ±1 合法差误杀）。

## failure_type 判定规则（症状分类器，强制遵守）

**failure_type 是症状分类器，不是根因分类器。判定依据只能是测试日志中实际出现的内容，禁止基于「根因假设」倒推分类。**

**按优先级判定**（高优先级命中即停止）：

1. **`"runtime"`** — 日志中出现任一以下信号（即使部分 case 有数值输出）：
   - 错误码 `507035`（向量核异常）、`507046`（超时）
   - `segmentation fault` / `core dumped` / `SIGSEGV` / `SIGABRT`
   - `AclrtSynchronizeDeviceWithTimeout` / `aclrtSynchronizeStream failed`
   - `vector core exception` / `cube core exception` / `mte core exception`
   - `npuSynchronizeDevice` 报错
   - `ERR00100 PTA call acl api failed`
   - `RuntimeError`（来自 NPU 执行，非 Python 测试框架逻辑）

2. **`"compilation"`** — 日志中出现编译错误信号（且无 runtime 信号）：
   - `error:` / `undefined reference` / `compilation terminated`
   - `fatal error` / `collect2: error` / `CMake Error`

3. **`"precision"`** — 有测试结果输出、有失败用例、但不满足以上两条。

**混合故障时的优先级**：`"runtime"` > `"compilation"` > `"precision"`。

### Per-case failure_type

对每个失败 case：
- 检查该 case 的日志段是否触发 runtime / compilation 关键词
- 触发了 → 标对应的 failure_type
- 未触发但有 diff → `"precision"`
- 该 case 通过 → 不入失败清单

### 常见陷阱（禁止这样判）

```
❌ "根因是 UB 对齐，属 precision/code bug → failure_type = precision"
✓ "日志出现 507035 vector core exception → failure_type = runtime"
```

下游 phase 据此选择完全不同的诊断路径（runtime 走错误码解码 + 架构对比，precision
走静态分析），判错会走错修复路线。

## 指标提取

- `pass` / `total`：从 `case_details` 逐条计数（权威判据 `accuracy.passed`）；顶层
  `passed` 可交叉核对
- `max_diff`：case 级取 `accuracy.max_diff`；run 级取全部 `output_results[].diff`
  的最大值（顶层 `max_diff` 即全 case 实际 |kernel − golden| 最大值）
- 提取不到数值结果（case 崩溃 / 无输出）→ `null`（无数值结果，计入 crashed）；
  验证时可在日志 grep `max_abs_diff` / `max_err` / `max relative` / `最大误差`

## 硬错误（run-cases 非零退出 + 无 result.json 落盘）

harness 根本没跑起来（编译失败 / 部署缺字段 / 注册失败 / 调用侧错误）——没有逐
case 结果可解析：

- **读 `run.log` 取证**：`tail -20` 取尾部错误 +
  `grep -iE "error|fail|undefined|not found|missing|unknown|callable" | head -10`
- **按症状分类规则判定 failure_type**（compilation 优先于 runtime），判据是日志中
  实际出现的关键词，禁止根因倒推
- **如实报告为框架层错误**（crash / 编译错误 / 注册失败），不编造逐 case 结果

## 大日志读取

预期输出超 200 行时，不整体 Read——先落盘，再 `tail -200` +
`grep -iE "fail|error|diff|mismatch|nan|inf" | head -50` 提取。
