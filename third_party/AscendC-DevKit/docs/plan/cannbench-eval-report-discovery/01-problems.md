# L1 问题记录 — eval 报告发现路径与产出位置错位（--output 目录 vs worktree reports/ glob）

- 立项时间：2026-08-28
- 实证批次：`20260827-132819-41aea1`（unique `…-95e52f` / moe_re_routing `…-db3570`）
- 状态：L1 冻结；L3 方向已拍板

## P1 — eval 实际执行且出分，scorer 在错误位置找报告 → 整批误报 0 分

### 现象（客观事实）

1. 批终态 `0/2 eval-passed`（两算子 eval=0.00），伴随 WARN
   `cann-bench discovery broken: target op not found by scan_interfaces
   (report operators=[], total_cases=0). no eval report — kernel_eval likely
   crashed`。
2. **eval 实际完整执行**（同批产物实证）：
   - 逐 case profiling：worktree `reports/prof_data/level3/<op>/{1..20}`
     每 case 一套 torch_npu profiler 数据（05:42–06:07 逐个生成）；
   - 完整汇总报告（`--output` 目录下 `<op>_eval_<ts>.json/html/md` 三件套）：
     - unique：`…/95e52f/subprocess/cannbench_eval_unique.partial.json/
       unique_eval_20260828_054218.json` →
       `total_cases=20, passed_cases=20, pass_rate=1.0, overall_score=50.0145`
     - moe_re_routing：`…/db3570/subprocess/cannbench_eval_moe_re_routing.partial.json/
       moererouting_eval_20260828_003615.json` →
       `total_cases=20, passed_cases=20, pass_rate=1.0, overall_score=68.5243`
   - 即批真实结果为 **2/2 eval-passed（50.01 / 68.52）**，0 分系误报。
3. `discovery broken / operators=[] / likely crashed` 文案为 scorer 的**猜测性
   推断**（`_discovery_broken_error` 默认文案），非实测事实——kernel_eval
   exit 正常、20 case 全跑完。

### 机制根因（代码事实）

| 侧 | 位置 | 事实 |
|---|---|---|
| devkit scorer | `cannbench_scorer.py:141` | 传 `--output <ws>/subprocess/cannbench_eval_<op>.partial.json`（step-91/92 为超时归档 partial 引入） |
| cann-bench kernel_eval | `src/kernel_eval/cli.py:278-279` | `if args.output: config.reports_dir = args.output`——`--output` 是**报告输出目录**覆盖，报告写在该目录内 |
| devkit scorer | `cannbench_scorer.py:391, 507-516` | `_parse_report` 却在 `repo_root/reports/` 下 glob `**/*_eval_*.json` 找最新报告 |

即 scorer **自己把报告位置指到 A（--output 目录），解析时却只在 B
（worktree reports/）找**——B 下只有 prof_data，必然找不到。`--output` 引入时
只改了超时分支（`_archive_eval_partial`），正常完成分支的报告发现路径未同步。

### "reports 变成 20 个目录"的澄清（非缺陷）

- `reports/prof_data/level3/<op>/<case_id>/` 是 kernel_eval 一贯的 per-case
  profiling 布局；99c4c0 批 worktree（`20260826_194806`）同款仅 prof_data。
- 感知差异的实质：以前（不传 `--output`）汇总 `<op>_eval_*.json` 落
  worktree `reports/` 下可见；现被 `--output` 移到 ws/subprocess——正是本
  bug 的另一面。

### 影响

- eval 真实结果被误报为 infra 断裂 0 分；**无需重跑评测**（报告已在 ws，
  可直接恢复真实分数）。
- 自 `--output` 引入（step-91/92）起，凡 ws 可用的正常完成 eval 均会命中
  此误报路径。

## P2 — 同族另一半：超时归档 `_archive_eval_partial` 对目录形态静默失效（review 补漏）

### 现象（客观事实）

- 2026-08-28 review（step-100~103）发现：`_archive_eval_partial`（step-91/92
  与 P1 同批引入）仍按**文件**语义读 `--output` 路径——`src.read_text()` 对
  目录必抛 `IsADirectoryError`（OSError 子类），被
  `except (json.JSONDecodeError, OSError)` 捕获后静默 return；注释理由
  「partial json 未成形」不成立，实为与 P1 同源的形态错位（`--output` 是
  目录，代码按文件读）。
- 确定性复现：UT 构造 partial 目录（内含 `exp_eval_<ts>.json`，`total_cases=9`）
  触发超时分支，归档 warn 为空（fix 前）。

### 机制根因

- P1 修的是**正常完成分支**（`_parse_report` 发现顺序）；超时分支
  （`_archive_eval_partial`）是同一错位的另一半，未同步修。

### 影响

- eval 超时场景的「已完成 case 性能分布可查」能力自 `--output` 引入起从未
  工作：超时仍 0 分且无 case 级归档信号（20260826 批 unique 超时 20 case
  只完成 9 个的场景即无归档）。

## 需求

- 报告发现位置与产出位置一致：scorer 优先在自指定的 `--output` 目录内发现
  报告；`repo_root/reports/` glob 仅作无 `--output` 场景回退。
- 误判文案与实测事实分离：找不到报告时的 infra 文案不得以猜测（"likely
  crashed"）冒充事实断言。
- 超时分支与正常完成分支同款目录发现（同一错位不修两半留一半）。

## 边界（已知残余风险）

- partial 目录按 mtime 取最新报告：同 op 同 ws 的旧报告在 eval 重跑且新
  eval 早退（一个 case 都没写）时会被读到/归档为陈旧结果——场景 = 批
  resume 后 eval 重跑，罕见；低于本 L1 所修的整批误报旧病，接受不防。

