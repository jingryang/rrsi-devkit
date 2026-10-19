# L4 — 实施方案：queue 的 max_diff_kl 按最新 KL 测量回写

> 层级：L4（改哪个函数、什么顺序、怎么验证）。覆盖 L1 P9，设计依据 `02-analysis.md` 附录 B。
> 代码基线：branch `devA5Debug`。

## 目标

「当前待处理 case」注入块的 `max_diff_kl` 不再冻结在 baseline，kernel_debug / regression 重测后由框架回写最新值，消除"修复后 agent 仍看到 65506 大 diff"的误导。

## 改动总览

| # | 主题 | 关键文件 |
|---|---|---|
| 1 | 回写 helper | `precision_debug_a5/case_loop.py` |
| 2 | kernel_debug 回写 `verification.after_max_diff_kl` | `precision_debug_a5/kernel_debug.py` |
| 3 | regression 从 `baseline/kl_result.json` 刷新全 queue | `precision_debug_a5/regression.py` |
| 4 | 注入块语义标注 | `precision_debug_a5/base.py` `_format_current_case_block` |
| 5 | 导出 helpers | `precision_debug_a5/__init__.py` |
| 6 | TDD 用例 | `test_precision_debug_a5_routing.py` |

## 改动 1 — case_loop.py 两个 helper

- `_case_diffs_from_kl_result(kl_data) -> dict[str, float]`：从 KL 脚本输出的 `kl_result.json` 构建 `{case_id(str): max_diff}`，优先 `all_results`（全量）回退 `failed_cases`；`max_diff` 为 None（crash）跳过。
- `_refresh_queue_kl_diffs(cp, case_diffs)`：按 `str(case_id)` 匹配刷新 `failed_case_queue[i].max_diff_kl`；不在 map 中的 case 不动。

## 改动 2 — kernel_debug transition

在 attempt_count 递增后：

```python
ver = phase_result.get("verification") or {}
if ver.get("after_max_diff_kl") is not None and 0 <= case_idx < len(queue):
    queue[case_idx]["max_diff_kl"] = ver["after_max_diff_kl"]
```

## 改动 3 — regression transition

在 queue 更新（new_failed_cases 追加）后、advance 前：

```python
d = _debug_artifacts_dir(state)
if d is not None:
    kl_path = d / "baseline" / "kl_result.json"
    if kl_path.exists():
        try:
            kl_data = json.loads(kl_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            kl_data = {}
        _refresh_queue_kl_diffs(cp, _case_diffs_from_kl_result(kl_data))
```

（regression.py 补模块级 `import json`。）

## 改动 4 — 注入块标注

`_format_current_case_block` 在 diff 两行后加：`max_diff_kl` = 最新 KL 测量（重测后框架回写），`max_diff_rc` = 最近一次 run-cases 测量（仅 baseline 双跑更新）。

## 改动 5 — 导出

`__init__.py` 导出 `_case_diffs_from_kl_result` / `_refresh_queue_kl_diffs`。

## 改动 6 — TDD 用例

1. `test_kernel_debug_writes_back_after_max_diff_kl`：kernel_debug 带 `verification.after_max_diff_kl` → queue[0].max_diff_kl 更新。
2. `test_kernel_debug_without_verification_keeps_queue_untouched`：无 verification → 不回写。
3. `test_regression_refreshes_queue_kl_diffs`：regression 后从 `baseline/kl_result.json` 刷新全部 case。

## 改动 7 — 契约与测试配套

- `ascendc-precision-kernel-debug/SKILL.md`：result JSON schema 补 `verification` 字段（`before_max_diff_kl` / `after_max_diff_kl` / `after_mare_kl` / `after_mere_kl` / `after_passed` 等 + 框架回写说明）——此前 agent 实际写了但 schema 未声明（契约缺口）。
- `test_precision_debug_a5_source_safety.py`：`framework_owned` 白名单加 `kl_result.json`（KL 脚本输出、框架 regression 消费，非 agent phase 结果；skill 的 `verification.kl_log` 示例引用了它）。

## 验证

- `test_precision_debug_a5_routing.py` 全绿（53 passed）。
- 回归：`test_precision_debug_stage.py` + `test_precision_debug_a5_source_safety.py` + `test_graph_executor.py` + `test_precision_debug_runtime_refine.py` + `test_codegen_regbase_phases.py` 全绿（470 passed / 3 skipped，skip 为环境类）。
- 端到端脚本验证：baseline(queue=65506) → kernel_debug(fixed, after=0.00098) → 下一 regression 注入块显示 `max_diff_kl: 0.0009765625`。
