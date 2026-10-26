# RRSI 评分一致性检查漏算 `bonus_score` 问题

- 日期：2026-10-26
- 仓库：`/home/s00940212/experiment/rrsi-devkit`
- 影响范围：`domains/ascendc-devkit/bench/run_tasks.py` → `verdict_from_snapshot()`
- 触发条件：算子（几乎）全用例精度通过，且 profile 为 `"2"`
- 后果：有效 trial 被冻结为 `score=0.0`，baseline/frontier 失去有效分数
- 状态：**已修复**（见 §5.4，兼容 cann-bench 1.x / 2.x）

---

## 1. 一句话描述

cann-bench 的单算子总分是四项之和（`compile + function + bonus + performance`），RRSI 在验算时只加了三项（漏了 `bonus_score`），于是“算出来的和”与报告总分对不上，一个真实得分 30/100 的算子被判定为“分数不一致”，最终记 0 分。

---

## 2. 现象

某次 baseline trial（`swi_glu`）的真实评测结果：

| 指标 | 值 |
|---|---|
| 用例通过 | 20 / 20 |
| `pass_rate` | 1.0 |
| cann-bench `score` | **30.0** |
| `compilation_score` | 5.0 |
| `function_score` | 20.0 |
| `performance_score` | 0.0 |

RRSI 冻结的 verdict（`runs/ascendc-devkit/jobs/base/swi_glu/t0/verdict.json`）：

```json
{
  "status": "score_inconsistent",
  "overall_score": 30.0,
  "compile_score": 5.0,
  "function_score": 20.0,
  "performance_score": 0.0,
  "pass_rate": 1.0,
  "num_cases": 20,
  "num_passed": 20,
  "checks": ["overall_score 30.0 != compile+function+performance 25.0"]
}
```

因为 `scores_consistent=false`：

- `verdict["score"]` 被写成 `0.0`；
- `bench/score.py` 的 `_score()` 再看到 `scores_consistent=false`，同样返回 `0.0`；
- baseline `S=0.0`，frontier 以“零分基线”继续进化。

---

## 3. 根因

### 3.1 cann-bench 的真实公式

`cann-bench/src/kernel_eval/report/scoring.py:478-482`：

```python
compilation_score = (compile_runtime_pass_cases * wc / total_cases) * 100.0
function_score    = (n_func_pass * wf / total_cases) * 100.0
bonus_score       = wb * delta_all * 100.0
performance_score = (perf_score_sum * wp / total_cases) * 100.0
total_score = (compilation_score + function_score + bonus_score
               + performance_score)
```

profile `"2"` 的权重（`cann-bench/src/kernel_eval/base/score_weights.py:41-44`）：

```python
"2": ScoreWeights(wc=0.05, wf=0.20, wp=0.70, wb=0.05)
```

`bonus_score` 的语义是“全用例精度通过奖励”：`δ_all=1` 当且仅当编译通过且全部 case 精度通过。

本次：

```
compilation = 20/20 × 0.05 × 100 = 5
function    = 20/20 × 0.20 × 100 = 20
bonus       = 1     × 0.05 × 100 = 5
performance = 0     × 0.70 × 100 = 0
                                ────
total                           = 30
```

### 3.2 RRSI 的验算公式

`domains/ascendc-devkit/bench/run_tasks.py:314-330`：

```python
overall = _fnum(eval_result, "overall_score")
compile_score = _fnum(eval_result, "compile_score")
function_score = _fnum(eval_result, "function_score")
performance_score = _fnum(eval_result, "performance_score")

expected = compile_score + function_score + performance_score   # ← 漏 bonus
...
if abs(overall - expected) > 1.0:
    consistent = False
    checks.append(
        f"overall_score {overall} != compile+function+performance {expected}"
    )
```

`expected = 5 + 20 + 0 = 25`，与 `overall = 30` 相差 5，超过容差 `1.0`，于是 `consistent=False`。

`run_tasks.py:350`：

```python
score = max(0.0, min(1.0, overall / 100.0)) if consistent else 0.0
```

### 3.3 为什么 `eval_result` 里没有 bonus

DevKit 的 `eval_result` 只透传了这些字段：

```json
{
  "overall_score": 30.0,
  "pass_rate": 1.0,
  "compile_score": 5.0,
  "function_score": 20.0,
  "performance_score": 0.0,
  "num_cases": 20,
  "num_passed": 20,
  "report_json": ".../swiglu_eval_20261024_114433.json"
}
```

没有 `bonus_score`，也没有 `compile_runtime_score`。分项之外的 `bonus` 只能从报告总分与分项之差反推。

### 3.4 报告里也没有 `bonus_score`

这一点容易误判，因为 cann-bench 源码里确实有个带 `bonus_score` 字段的
`OperatorReport`（`src/kernel_eval/report/scoring.py:75`）。但**写报告的不是它**：

| 层 | 类 | 有 `bonus_score` 吗 |
|---|---|---|
| 计分 | `report/scoring.py` 的 `OperatorScoreInfo` / `OperatorReport` | 有（`w_b·δ_all·100`） |
| 落盘 | `report/report_generator.py` 的 `OperatorReport` | **没有**，只有 `score`（= 四项之和） |
| 消费者 | `EvalReport.to_dict()` → `asdict(op)` | 按落盘类的字段序列化 |

实测最后一份报告（`swiglu_eval_20261024_114433.json`）的 `operators[0]` 有
18 个键，`score = 30.0`，**没有 `bonus_score`**：

```
avg_speedup, cases, compilation_error, compilation_score,
compile_runtime_fail_cases, compile_runtime_score, failed_cases,
function_score, operator, pass_rate, passed_cases, performance_score,
rel_path, score, score_error, score_error_code,
subprocess_failure_reason, total_cases
```

v1.0.0 / v1.1.2 的全仓 grep 对 `bonus` 是 0 命中：1.x 根本没有 bonus 概念，
2.x 只在计分内部有，落盘报告不输出。

所以 RRSI 侧一开始那个"报告缺失时读显式 `bonus_score` 做四项严格加法"的兜底是
死代码：两个来源（`operators[0]`、`eval_result`）永远拿不到值。已删除，缺报告时
统一走 3.2 的不变式校验。

---

## 4. 一个必须澄清的误区：不是漏了 `compile_runtime_score`

报告里确实有 `compile_runtime_score: 5.0`，看起来“正好是缺的 5 分”，但它**不是独立分项**：

```python
# cann-bench/src/kernel_eval/report/scoring.py:95
'compile_runtime_score': self.compilation_score,

# cann-bench/src/kernel_eval/report/report_generator.py:169
compile_runtime_score=score_info.compilation_score if score_info else 0.0,
```

它是 `compilation_score` 的别名（“编译/运行”轴的展示名），数值恒等于 `compilation_score`。

如果按“把 `compile_runtime_score` 加进求和”来修：

| 场景 | 真实总分 | 错误修法算出的和 | 结果 |
|---|---|---|---|
| 20/20 全过（本次） | 5+20+5 = 30 | 5+5+20 = 30 | 碰巧通过 |
| 19/20 通过 | 5+19+0 = 24 | 5+5+19 = 29 | **误判 inconsistent** |
| profile `"1"` 全过 | 20+30+0 = 50 | 20+20+30 = 70 | **误判 inconsistent** |

也就是说，这个修法会把本次的“假阴性”换成未来所有非满分结果的“假阳性”。

---

## 5. 修复方案

### 5.1 方案对比

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| A. 补 `bonus` | 在 RRSI 里按 profile 和 `δ_all` 重算 bonus | 保留分项验算 | 必须在 RRSI 里复制 cann-bench 的权重表和判定逻辑；cann-bench 改公式就得同步改 |
| B. 以报告总分为准（推荐） | 直接比对 `eval_result.overall_score` 与报告里的算子 `score` | 不复制公式；跨 profile/版本稳定；校验强度更高 | 放弃“从分项反推”的验算路径 |

推荐 **B**。这次 bug 的根源就是 RRSI 复制了一份不完整的公式；继续维护第二份公式，未来还会因为权重档、`eq3_log`、反作弊规则的变化再次漂移。

### 5.2 实现

把 `_report_entry_count()` 替换为一条读报告通路：`_load_report()` 取报告，
`_report_total()` 同时给出“权威总分”和“算子条目数”。

```python
def _load_report(eval_result: dict, base: Path) -> dict | None:
    """读取 ``report_json`` 指向的 cann-bench 评测报告。"""
    raw = eval_result.get("report_json")
    report = _as_mapping(raw)
    if report is None and isinstance(raw, str) and raw:
        path = Path(raw)
        if not path.is_absolute():
            path = base / path
        report = read_json(path)
    return report


def _report_total(report: dict | None) -> tuple[float | None, int | None]:
    """返回 ``(报告总分, 算子条目数)``。"""
    if not isinstance(report, dict):
        return None, None
    ops = report.get("operators")
    if isinstance(ops, list):
        if len(ops) == 1 and isinstance(ops[0], dict):
            total = _optional_fnum(ops[0], "score")
            if total is None:
                total = _optional_fnum(ops[0], "total_score")
            return total, 1
        return None, len(ops)
    total = _optional_fnum(report, "overall_score")
    if total is None:
        total = _optional_fnum(report, "score")
    return total, None
```

在 `verdict_from_snapshot()` 中：

```python
report = _load_report(eval_result, snapshot_path.parent)
report_total, entries = _report_total(report)

# 诊断项：bonus 只可能非负，因此总分不得低于分项之和
component_sum = compile_score + function_score + performance_score
implied_bonus = overall - component_sum

if report_total is not None:
    upper = max(OPERATOR_SCORE_CAP, report_total)   # 封顶值由报告说了算
    if abs(overall - report_total) > 1e-6:
        consistent = False
        checks.append(
            f"overall_score {overall} != report operator score {report_total}"
        )
else:
    checks.append(
        f"report total unavailable; only checked component sum "
        f"{component_sum} <= overall_score {overall}"
    )

# 分项和不得高于总分；例外是封顶——HAP 让未截断总分越过 120 时，
# 报告记的是封顶值，分项和自然高于它。
capped = overall >= OPERATOR_SCORE_CAP - _SCORE_EPS
if not capped and component_sum > overall + _SCORE_EPS:
    consistent = False
    checks.append(
        f"compile+function+performance {component_sum} "
        f"exceeds overall_score {overall}"
    )
```

返回的 verdict 增加两个诊断字段：

```python
"implied_bonus": round(_finite(implied_bonus), 6),
"score_weight_profile": profile,     # 1.x 报告没有该键 → ""
```

要点：

- **硬校验**：`overall_score` 必须与报告里的 `operators[0].score` 严格相等（`1e-6`），这是真正有意义的防篡改检查；
- **软校验**：分项和 `<= overall`，因为 `bonus >= 0` 是唯一跨 profile、跨版本成立的不变式，不要求相等；
- `implied_bonus` 写进 verdict，本次会显示 `5.0`，一眼看出缺的是哪项；
- `bonus_score` 不做独立对账——1.x/2.x 的报告都不输出它（见 3.4）；
- 旧的 `_report_entry_count()` 删除，避免两条读报告的通路；
- `bench/score.py` 不用改——它只看 `scores_consistent`。

### 5.3 兼容性注意

- 老报告可能没有 `score` 字段：依次回退到 `total_score`、报告顶层 `overall_score`；
- 多算子 trial（当前不会出现）：`len(ops) != 1` 直接判不一致，与原逻辑一致；
- `report_json` 缺失或不可读：不要因此把有效分数判 0，保留原有“仅做数值校验”的行为，并在 `checks` 里记一条说明。

---

### 5.4 已落地的实现（兼容 1.x / 2.x）

`domains/ascendc-devkit/bench/run_tasks.py` 现在按“版本无关”的方式校验：

| 情况 | 校验方式 |
|---|---|
| 报告可读（1.x / 2.x 均可） | `eval_result.overall_score` 必须等于 `operators[0].score`（容差 `1e-6`）；老报告没有 `score` 时回退 `total_score`，再回退顶层 `overall_score` |
| 报告不可读 | 只校验不变式 `compile + function + performance <= overall`，并在 `checks` 记一条“report total unavailable”，**不把有效分数判 0** |
| 未封顶时 | 分项和大于总分 → 不一致（容差 `_SCORE_EPS = 1e-6`，分项是报告里的原始 float，无四舍五入） |
| 封顶时（`overall >= 120`） | 跳过上面的分项和校验：HAP 让未截断总分越过 120 时，报告记的是封顶值，分项和高于它属正常 |
| 任何情况 | `overall` 上限取 `max(120, 报告总分)`，报告在时不因封顶常量漂移误杀 |

verdict 新增两个诊断字段：`implied_bonus`（总分减三项分项之和）和 `score_weight_profile`（报告中的权重档，旧报告为空串）。

`bonus_score` 不参与对账：报告（`report_generator.OperatorReport`）不输出该键，
DevKit 的 `eval_result` 也不写，两个来源都永远取不到值，所以对应的严格加法分支
已删除（原因见 3.4）。

这样 1.x 报告（三项之和）与 2.x 报告（四项之和）都只依赖报告自身的权威总分，RRSI 不再维护第二份权重表。

---

## 6. 验证

### 6.1 离线验证（推荐先做，秒级）

用已存的 snapshot 重算，不重新跑算子：

```
snapshot:
runs/ascendc-devkit/jobs/base/batches/20261024-050434-t000-1525700/
  devkit/20261023-210453-141036/t000-swi_glu/state_snapshot.json
```

修复前：

```
status = score_inconsistent
score  = 0.0
checks = ["overall_score 30.0 != compile+function+performance 25.0"]
```

修复后预期：

```
status = ok
score  = 0.3
implied_bonus = 5.0
checks = []
```

### 6.2 单元测试（`tests/test_ascendc_verdict.py`，13 条）

1. profile `"2"`、20/20 全过、性能缺失 → `ok`，`score=0.3`，`implied_bonus=5.0`；
2. 19/20 通过 → `ok`，`score=0.24`，`implied_bonus=0.0`；
3. profile `"1"` 老报告（无 `score_weight_profile`、无 bonus）→ `ok`；
4. `overall_score` 与报告 `score` 不一致 → `score_inconsistent`，`score=0`；
5. 分项和大于总分 → `score_inconsistent`；
6. 报告有 2 个 operator 条目 → `score_inconsistent`；
7. `report_json` 缺失 → 不因缺报告而判 0，只记 `report total unavailable`；
8. `report_json` 缺失但多出一个 `bonus_score` 键 → 忽略该键，仍走不变式校验（分项和超总分照抓）；
9. HAP 奖励导致总分 >100（≤120）→ 不误判；
10. 封顶场景：未截断 125 被记为 120、分项和高于总分 → 不误判（`implied_bonus=-5`）；
11. 报告总分 130（封顶常量被调高）→ 不误判；
12. 分项含 NaN → `score_inconsistent`，且 verdict 仍是严格 JSON；
13. snapshot 无 `eval_result` → `harness_error`。

### 6.3 修复后的 baseline 处理

`verdict.json` 与 `frontier.json` 是冻结产物，离线重算只证明“同一份证据在新逻辑下应得 0.30”，不会自动改写它们。两个选择：

- **重跑 baseline**（约 7 小时）：得到从头到尾干净的 H₀；
- **一次性重算**（分钟级）：用修正后的 `verdict_from_snapshot()` 重算 verdict，再走现有的 adjudicate/frontier 更新路径。是否可行取决于 `readjudicate` 是否支持 baseline（当前它只声明支持 round）。

---

## 7. 附：证据文件

| 内容 | 路径 |
|---|---|
| 冻结 verdict | `runs/ascendc-devkit/jobs/base/swi_glu/t0/verdict.json` |
| trial 快照 | `runs/ascendc-devkit/jobs/base/batches/20261024-050434-t000-1525700/devkit/20261023-210453-141036/t000-swi_glu/state_snapshot.json` |
| cann-bench 报告 | 同目录下 `subprocess/cannbench_eval_swi_glu.partial.json/swiglu_eval_20261024_114433.json` |
| RRSI 验算代码 | `domains/ascendc-devkit/bench/run_tasks.py:284-371` |
| RRSI 分数门 | `domains/ascendc-devkit/bench/score.py:81-89` |
| cann-bench 聚合公式 | `/home/s00940212/experiment/cann-bench/src/kernel_eval/report/scoring.py:478-482` |
| cann-bench 权重档 | `/home/s00940212/experiment/cann-bench/src/kernel_eval/base/score_weights.py:41-44` |

打分机制本身见：`docs/cann-bench-打分机制说明-20261026.md`。
