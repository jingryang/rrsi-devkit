# L4 实施 — step-102 eval 报告发现路径对齐产出位置（as-built）

实施日期：2026-08-28。全量 UT 3775 绿（新增 3 例）。
修订：2026-08-28 review 追修 M1（L1 P2 同族另一半），见文末。

## 改动

`src/ascendc_devkit/adapters/evaluation/cannbench_scorer.py`：

1. `_parse_report` 增 `ws=None` 参数；发现顺序（step-102 核心）：
   `_eval_partial_path(ws, op_name)` 目录（scorer 自指定给 kernel_eval 的
   `--output` 产出位置，kernel_eval `cli.py:278` 将其作为 reports_dir）glob
   `**/*_eval_*.json` **优先** → `repo_root/reports/` glob 回退（ws 缺失/
   目录空）→ 双空才 infra。
2. `_run_eval` 调用点传 `ws=ws`。
3. 文案整改（§1.10 猜测不冒充事实）：
   - 新增 `_no_report_error`：fact（搜索过哪些位置、无报告）与 suspected
     （kernel_eval 早退/崩溃——未验证，建议查 subprocess log）分离表述；
   - `_discovery_broken_error`（operators==[] 场景）：`Likely _C.abi3.so
     stale` → `fact: ...` + `suspected (not verified): ...` 结构。

## 验证

- UT 3 例：`prefers_output_dir_over_repo_reports`（顺序守护——两处都有
  报告时取 --output 目录的 50.01，防把旧批残留读成当轮）、
  `output_dir_empty_falls_back_to_repo_reports`、
  `no_report_reason_separates_fact_from_guess`（断言搜索路径列表 + suspected
  标记存在）。
- 既有 5 例 `TestDiscoveryAndLossSplit` 兼容通过（ws=None 回退路径）。
- **本批真实报告端到端验证**（20260827 批产物，未入库）：
  unique overall=50.01（compile 20.00/func 30.00/perf 0.01）20/20、
  moe_re_routing overall=68.52（perf 18.52）20/20——修复后无需重跑评测，
  批记录可据实恢复（batch 汇总 0/2 系误报）。

## 修订（2026-08-28，review M1 追修）— 超时归档同族另一半

`_archive_eval_partial`（超时分支）此前仍按**文件**语义读 `--output` 路径：
目录上 `read_text()` 必抛 `IsADirectoryError` 被 `except OSError` 静默吞，
「超时归档已完成 case 性能分布」自 `--output` 引入起从未工作（L1 P2）。

改动（同款目录发现，§1.15 同族单点）：

- `_archive_eval_partial`：`_eval_partial_path` 目录 → 复用
  `_find_latest_report` 发现最新 `*_eval_*.json` → 读 `total_cases`（增量
  报告的已完成 case 数）→ warn 报告路径；目录未成形 / 报告写一半仍静默
  return（无东西可归档）。
- `_no_report_error` 形参注解 `list` → `list[Path]`。

验证：改写 `TestEvalPartialReportArchive.test_timeout_archives_partial_report`
为真实形态（partial **目录**内含 `<op>_eval_<ts>.json`、schema 用
`total_cases`——旧 fixture 的文件形态 + `case_results` 键均偏离 kernel_eval
实际行为）+ 新增 `test_archive_silent_when_dir_not_formed`；scorer 文件
31 例全绿。
