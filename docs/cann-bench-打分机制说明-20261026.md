# cann-bench 打分机制说明

- 依据：本地 checkout `/home/s00940212/experiment/cann-bench`（tasks VERSION `2.0.0`）
- 日期：2026-10-26
- 目的：说明一次 cann-bench 评测从“单个用例”到“单算子”再到“benchmark 总分”分别怎么算，以及哪些情况会得 0 分

---

## 0. 一句话版本

```
单用例:  是否通过(MERE/MARE 精度门)  +  性能分 Eq.3
              │                              │
              ▼                              ▼
单算子:  compile 分 + function 分 + bonus 分 + performance 分  (Eq.4, 满分名义 100, 封顶 120)
              │
              ▼
总分:    所有算子分数相加 (Eq.5)
```

对当前生产题集（`VERSION=2.0.0` → profile `"2"`），权重是：

```python
wc = 0.05   # 编译/运行
wf = 0.20   # 精度
wp = 0.70   # 性能
wb = 0.05   # 全用例通过奖励
```

一个“功能全对、性能没跑出来”的算子拿 **30 分**：`5 + 20 + 5 + 0`。

---

## 1. 评分口径是什么时候定的

权重档由题集大版本号决定，优先级（`src/kernel_eval/base/score_weights.py:48-69`）：

1. 显式参数 `weights="2"`
2. 环境变量 `CANN_BENCH_SCORE_WEIGHTS`
3. 评测入口从 `bench_root` 的 `metadata/VERSION` 读大版本号

本地 `tasks/metadata/VERSION` 是 `2.0.0`，所以生产评测走 profile `"2"`。没有可用来源或未知版本会直接报错，不会静默用默认档。

两套已定义的档位（`score_weights.py:41-44`）：

| profile | wc | wf | wp | wb | 说明 |
|---|---|---|---|---|---|
| `"1"` | 0.20 | 0.30 | 0.50 | 0.00 | 历史档（season1） |
| `"2"` | 0.05 | 0.20 | 0.70 | 0.05 | 当前 production（season2） |

---

## 2. 单用例：先过精度门，再算性能分

### 2.1 精度门（决定这个 case 算不算 pass）

默认 checker 是 `relative_error`（`src/kernel_eval/config.py:125` 附近），判据是：

```
MERE = avg(|actual - golden| / (|golden| + 1e-7))
MARE = max(|actual - golden| / (|golden| + 1e-7))
通过条件: MERE < threshold 且 MARE < 10 × threshold
```

各 dtype 的 `threshold`（`src/kernel_eval/utils/thresholds.py:28`）：

| dtype | threshold |
|---|---|
| float16 | `2^-10` ≈ 9.77e-4 |
| bfloat16 | `2^-7` ≈ 7.81e-3 |
| float32 / float64 | `2^-13` ≈ 1.22e-4 |
| hifloat32 | `2^-11` ≈ 4.88e-4 |
| float8_e4m3fn | `2^-3` = 0.125 |
| float8_e5m2 | `2^-2` = 0.25 |
| int8/16/32/64、uint* | 0（完全相等） |

除 MERE/MARE 外还有两条兜底：

- **小值域**：`|golden| < small_value_threshold` 时改用 ErrorCount 比值标准（避免“分母接近 0 导致相对误差爆炸”误判）；
- **相消**：接近 0 的相消结果单独按绝对误差标准判断。

另外，输出 dtype 必须符合 `proto.yaml` 的声明，不符合直接判 fail。

> 注意：失败不只有“数值不对”一种。运行期异常、shape/输出数量不匹配、dtype 不支持等属于 **compile/runtime 失败**，不是精度失败，会扣 compile 分（见 §3.2）。

### 2.2 性能锚点从哪来

`cases.yaml` 里**不内嵌** `baseline_perf_us` / `t_hw_us`。评测时从集中式基线库查：

```
tasks/metadata/<hardware>.json
```

硬件名由设备名解析（`src/kernel_eval/utils/baseline_resolver.py`）：
`Ascend950DT_9582` → `950dt`；`Ascend910_9362` → `910b2`。

本机 swi_glu 的部分锚点（`tasks/metadata/950dt.json`）：

| case | baseline_perf_us (B) | t_hw_us (H) |
|---|---|---|
| 1 | 6.18 | 1.023 |
| 2 | 15.98 | 8.184 |
| 3 | 30.32 | 16.368 |
| 4 | 119.38 | 65.4721 |
| 5 | 240.21 | 130.3369 |

- `B` = baseline 性能（通常是历史/参考实现的耗时）
- `H` = 理论硬件下界
- `C` = 候选算子实测耗时

### 2.3 性能分 Eq.3

默认公式 `eq3`（`src/kernel_eval/base/perf_metric.py:81`）：

```
score_i = (B - H) / ((C - H) + (B - H))
```

性质：

- `C = B`（和 baseline 一样快）→ **0.5**
- `C = H`（达到硬件下界）→ **1.0**
- `C > B`（比 baseline 慢）→ **< 0.5**，可以低到 0
- `C < H`（快过硬件下界）→ 走 HAP 奖励，见下

可选的对数版 `eq3_log`（`perf_metric.py:89`）：

```
score_i = lg(B/H) / (lg(C/H) + lg(B/H))
```

同样在 `C=B` 处 0.5、`C=H` 处 1，但把“每快 10 倍”映射成等距分差，适合跨数量级的算子。默认不启用，只能通过 `metric="eq3_log"` 或 `CANN_BENCH_PERF_METRIC=eq3_log` 切换。

**HAP 奖励**（`perf_metric.py:104-120`）：当 `C < H` 时，两个公式都会出现极点，所以统一脱离 baseline 锚：

```
score_i = min(H / C, PER_CASE_SCORE_CAP)      # PER_CASE_SCORE_CAP = 10
```

即“快过硬件下界”按硬件加速比给奖励，单用例最多 10 分。

**锚点缺失/异常时**：

- `C` 或 `H` 非正 / NaN → 该 case 性能分按 0 计（精度分不受影响）；
- `B` 缺失（≤0）但 `H` 有效 → 用 `max(H×10, 10)` 作为代理基线，并打 warning；
- `B < H` → 视为基线标定可疑，仍计算但 warn。

---

## 3. 单算子：Eq.4

代码位置：`src/kernel_eval/report/scoring.py` 的 `aggregate_eq4()`（318 行起），实际求和在第 478-482 行。

### 3.1 四个分项

设：

- `N` = case 数（`max(声明数, 实际结果数, 1)`；声明 0 且实测 0 的“空壳算子”直接 0 分）
- `δ_compile_runtime` = 编译通过则为 1；通过后按 `(N - 编译/运行失败 case 数) / N` 计
- `n_func_pass` = 精度通过的 case 数
- `δ_all` = 编译通过且全部 N 个 case 精度都通过才为 1，否则 0
- `perf_score_sum` = 所有通过 case 的 Eq.3 分数之和（缺锚点按 0）

则：

```
compilation_score = (N - n_compile_runtime_fail) / N × wc × 100
function_score    = n_func_pass / N × wf × 100
bonus_score       = δ_all × wb × 100
performance_score = perf_score_sum / N × wp × 100

total_score = compilation_score + function_score + bonus_score + performance_score
```

最后 `total_score` 超过 **`OPERATOR_SCORE_CAP = 120`** 时封顶（`perf_metric.py:61`）。

### 3.2 编译失败 = 0 分，不是只扣 wc

这是设计上的硬规则（`scoring.py:351-364`）：`δ_pass = 0` 时，所有 case 的 `δ_acc,i` 也强制为 0：

```
编译失败 → compilation_score = 0
         → function_score    = 0
         → bonus_score       = 0
         → performance_score = 0
         → total_score       = 0
```

理由：没编译出来的 kernel 没有任何可信的数值可供评测；如果只扣 5 分，会出现“完全不能跑”比“跑通但全错”分数还高。

### 3.3 精度失败 vs 编译/运行失败

两者扣的分项不同：

- **数值精度不达标**（MERE/MARE 超阈值）→ 只扣 function 分（该 case 不计 `n_func_pass`），不影响 compilation；
- **运行期/结构失败**（aclnn 调用失败、shape 不匹配、dtype 不支持、case 执行抛异常）→ 扣 compilation 分（`n_compile_runtime_fail`），同时该 case 也不算 function 通过。

判定函数：`src/kernel_eval/base/result.py:248` 的 `is_compile_runtime_case_failure()`。

### 3.4 反作弊置零

两条路径会把整个算子的所有分项清零（`scoring.py:428-470`）：

| 触发条件 | 错误码 |
|---|---|
| 精度通过、但检测不到 NPU kernel（疑似 CPU fallback） | `no_npu_kernel_detected` |
| profiler 检测到 `aclrtMemcpy`（疑似把计算外包给 CPU） | `cpu_fallback_detected` |

**关键区分**：profiler 自己没采到数据（`perf_collection_failed=True`，例如没有产出 `kernel_details.csv`）**不算**反作弊，只算“这个 case 没有性能分”。本次 swi_glu 就属于这种情况（见 §6）。

### 3.5 报告里的字段名

`OperatorReport`（`src/kernel_eval/report/report_generator.py:124-141`）输出：

```json
{
  "score": 30.0,                 // ← 算子总分，Eq.4 的结果
  "compilation_score": 5.0,
  "compile_runtime_score": 5.0,  // ← 注意：只是 compilation_score 的别名
  "function_score": 20.0,
  "performance_score": 0.0
}
```

**`compile_runtime_score` 不是独立分项**：`to_dict()` / `from_eval_operator_result()` 里直接赋 `compilation_score` 的值（`report_generator.py:169`、`scoring.py:95`）。它只是“编译/运行”这一轴的展示名。

另外报告**不输出** `bonus_score`，所以只看报告字段做加法会少 5 分；`score` 才是权威总分。

---

## 4. Benchmark 总分：Eq.5

`src/kernel_eval/report/scoring.py:664`：

```python
overall_score = sum(info.total_score for info in score_infos)
```

即 **总分 = 所有算子得分之和**，不是平均分。

- 单算子名义满分 100，所以 10 个算子的 benchmark 名义满分是 1000；
- 单算子有 HAP 奖励时可超过 100，但封顶 120，因此单个算子最多贡献 120；
- Level 分（`calculate_level_score`，679 行）= 该 level 下所有算子分之和，按 `rel_path` 首段精确匹配（`level1/swi_glu` → `level1`）。

报告另外给出平均分 `calculate_average_score()`（总分 / 算子数）作为跨题集可比的辅助指标，但它**不替代** Eq.5 总分。

### 4.1 pass_rate 与 genuine_pass_rate

`report_generator.py:294-304`：

- `pass_rate = passed_cases / total_cases`
- `genuine_pass_rate = passed_cases / (total_cases - cascade_cases)`

`cascade_cases` 是设备异常 / skipped 导致的级联失败，不计入真实失败。看算子实际质量时，`genuine_pass_rate` 更有参考价值。

---

## 5. 常见分数形态（profile `"2"`，单算子，N 个 case）

| 场景 | compilation | function | bonus | performance | 总分 |
|---|---|---|---|---|---|
| 编译失败 | 0 | 0 | 0 | 0 | **0** |
| 编译过，精度全错 | 5 | 0 | 0 | 0 | **5** |
| 编译过，19/20 精度通过 | 5 | 19 | 0 | 0 | **24** |
| 精度 20/20，全无性能分 | 5 | 20 | 5 | 0 | **30** |
| 精度 20/20，性能恰好等于 baseline | 5 | 20 | 5 | 35 | **65** |
| 精度 20/20，性能达到硬件下界 | 5 | 20 | 5 | 70 | **100** |
| 快过硬件下界（HAP 奖励） | 5 | 20 | 5 | ≥70 | 最高 **120** |

> 性能项按 `perf_score_sum / N × wp × 100` 计算；单 case 的 Eq.3 分在 `[0,1]`（HAP 区间可到 10）。

---

## 6. 本次 swi_glu 的实例拆解

评测报告：`runs/ascendc-devkit/jobs/base/batches/20261024-050434-t000-1525700/devkit/20261023-210453-141036/t000-swi_glu/subprocess/cannbench_eval_swi_glu.partial.json/swiglu_eval_20261024_114433.json`

```
score_weight_profile: "2"
tasks_version: 2.0.0
operators[0].operator: SwiGlu
operators[0].score: 30.0
operators[0].pass_rate: 1.0          (20/20)
operators[0].compilation_score: 5.0
operators[0].compile_runtime_score: 5.0   (别名，不是额外分)
operators[0].function_score: 20.0
operators[0].performance_score: 0.0
```

拆解：

```
compilation = 20/20 × 0.05 × 100 = 5
function    = 20/20 × 0.20 × 100 = 20
bonus       = 1    × 0.05 × 100 = 5
performance = 0    × 0.70 × 100 = 0
                                ────
total                           = 30
```

**为什么 performance 是 0**：报告里每个 case 都是 `perf_collection_failed: true`、`_perf_result: null`、`elapsed_us: 0.0`。这是 profiler 采集功能异常，不是 CPU fallback 反作弊（否则整个算子会被置 0，而不是 30）。所以这次的 30 分含义是“**功能正确 + 全用例通过**，性能维度没有测到”。

---

## 7. 容易踩的坑

1. **`compile_runtime_score` 不等于“额外的 5 分”**
   它是 `compilation_score` 的别名。`30 = 5(compile) + 20(function) + 5(bonus) + 0(perf)`，缺的那项是 `bonus_score`。

2. **报告里没有 `bonus_score` 字段**
   只看 JSON 字段做加法会得到 25，与 `score=30` 对不上。校验时应该直接信 `score`。

3. **`overall_score` 是求和不是平均**
   单算子题集里它等于该算子分；多算子会把所有算子分相加。

4. **0 分有四种完全不同的含义**
   - 编译失败（真 0 分）；
   - 反作弊置零（CPU fallback / 无 NPU kernel）；
   - 评分器自身判 `score_inconsistent`（RRSI 侧才会发生，不是 cann-bench 行为）；
   - 根本没跑起来（infra error，报告里可能连 `operators[0]` 都没有）。

   看分之前先看 `status` / `score_error_code` / `pass_rate`。

5. **性能分缺失 ≠ 性能差**
   `perf_collection_failed=true` 时 performance 记 0，但 `score_error_code` 是空的，不会被反作弊清零。想区分“真慢”和“没测到”，看 case 的 `_perf_result` 与 `perf_collection_failed`。

6. **精度失败与运行失败扣的不是同一项**
   数值不达标扣 function；运行期/结构错误扣 compilation。两者都表现为 case 不通过，但总分不同。

---

## 8. 源码索引

| 内容 | 位置 |
|---|---|
| 权重档定义 | `src/kernel_eval/base/score_weights.py:41-44` |
| 权重档解析优先级 | `src/kernel_eval/base/score_weights.py:48-69` |
| Eq.3 性能分 | `src/kernel_eval/base/perf_metric.py:81-133` |
| HAP 奖励与两个 cap | `src/kernel_eval/base/perf_metric.py:56-120` |
| Eq.4 聚合 | `src/kernel_eval/report/scoring.py:318-497` |
| Eq.5 总分 | `src/kernel_eval/report/scoring.py:664-666` |
| Level 分 | `src/kernel_eval/report/scoring.py:679-697` |
| 精度阈值表 | `src/kernel_eval/utils/thresholds.py:28-48` |
| 精度判据说明 | `src/kernel_eval/checkers/relative_error_checker.py:17-26` |
| 编译/运行失败判定 | `src/kernel_eval/base/result.py:248` |
| 性能锚点加载 | `src/kernel_eval/benches/cann_loader.py:409-410` |
| 硬件名 → 基线文件 | `src/kernel_eval/utils/baseline_resolver.py:52-70` |
| 报告字段组装 | `src/kernel_eval/report/report_generator.py:124-180` |
| 总分与 pass_rate | `src/kernel_eval/report/report_generator.py:288-312` |
| 生产题集版本 | `tasks/metadata/VERSION`（`2.0.0`） |
| 950dt 性能锚点 | `tasks/metadata/950dt.json` |
