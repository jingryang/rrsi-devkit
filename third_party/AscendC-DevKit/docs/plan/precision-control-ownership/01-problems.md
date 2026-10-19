# control.json 产权缺口致 eval 评测修复前 binary + best_commit 语义缺陷 — L1 问题记录（2026-09-04）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/根因/影响），**不提方案**。
> 方案分析见 `02-analysis.md`（L3）；实施方案待方案评审通过后另立 L4。

## 证据来源

- **运行**：`output/20260903-073532-eddf10/20260903-073532-5ddae2`（self_evolve 批，op = `apply_adam_w` / ApplyAdamW，A2/ascend910b）
- **算子仓 worktree**：`/home/x00584171/code/cann-bench-batch/20260903_153508/apply_adam_w`
- **关键产物**：
  - `run.log`（时间线主证，L1531-1918）
  - `artifacts/debug/apply_adam_w/control.json`（终态：`best_commit=549ba00163a1…` + `best_passed_count=20` 错误配对）
  - `agents/ascendc-precision-diagnose-01.jsonl`（agent 越权写实证）
  - `artifacts/debug/apply_adam_w/run_tests_iter-{0,2}/result.json`、`diagnose_iter-1/result.json`
  - `subprocess/cannbench_eval_apply_adam_w.partial.json/applyadamw_eval_20260903_165735.json`
  - `artifacts/debug/apply_adam_w/precision_report.md`（被污染配对的用户可见渲染）

## 事实（客观，已实证）

### F1：debug 全过与 eval 崩溃并存，且两者测的不是同一份代码

- debug 链终态：`run_tests_iter-2/result.json` **20/20 通过，`golden_used=true`（真实 golden 比对）**，产出时间 16:53:47。
- cann-bench eval 终态：**1/20 通过**（pass_rate 5%，func 1.5/20），`kernel_eval exited 19`。
- **失败签名与「修复前」逐位一致**——证明 eval 跑的是修复前 binary：

| 证据 | run_tests_iter-0（修复前，16:42） | cann-bench eval（17:10） |
|---|---|---|
| case 1 max_diff | 11.033201 | 11.033201098442078 |
| case 1 mismatch | 1048337 / 1048576 | 1048337 / 1048576 |
| 唯一通过 case | `ApplyAdamW_14`（3x7x11x13x1013） | `level2/apply_adam_w_14`（同一个） |

- 算子层 bug 本身（diagnose 已正确定位）：`ComputeAdamWFp32` 最终步 `y = var ± lr*update`
  写入中间 buffer `mF32` 而非输出 buffer `yF32`，两条路径（NEED_CAST / 非 CAST）均中招。

### F2：完整时间线（run.log + 文件 mtime + git 三源对齐）

| 时刻 | 事件 |
|---|---|
| 16:41:11 | 框架创建 codegen 快照 commit `549ba00163a1`（"precision_debug entry"） |
| 16:41–16:42 | run_tests iter-0：**1/20**（唯一通过 = case 14）；框架记录 `(best_commit=549ba00, best_passed=1)` |
| 16:42:51–16:53 | diagnose agent 定位修复；16:47:55 自部署；16:51 `diagnose_iter-1` **20/20（真 golden）**；**16:52:11 commit `b760254`**（"write final AdamW result to output buffer yF32"） |
| 16:53:02.502 | **agent 越权写 control.json**（见 F3） |
| 16:53:11–16:53:47 | loopback corrective run_tests iter-2：**20/20（真 golden，被测的是 diagnose 16:47 部署的修复后 binary）** |
| ~16:53:48 | 框架 transition：`_update_best_metrics` 判 `20 > 20 = False` → **跳过 `_snapshot_best_commit`**（见 F6） |
| 16:53:51 | `_converge_to_best_commit`：`git checkout 549ba00 -- op_dir && clean -fd`——**把修复从工作区抹掉** |
| 16:53:51–16:54:38 | 从修复前源码重编译 + 安装 + smoke（仅 callable 探测，`golden_used=false`）→ "smoke ok" |
| 16:54:38 | 日志：`converge_best_commit op_dir → 549ba00163a1 + redeployed (smoke ok); eval will run the best-passed-count commit` |
| 16:57–17:10 | cann-bench eval 跑修复前 binary → **1/20** |

### F3：diagnose agent 越权写框架产权字段（transcript 实证）

`agents/ascendc-precision-diagnose-01.jsonl` 收尾阶段，agent 叙事块宣告的是
*"Now update control.json (case status + attempt_count)"*，实际命令额外写入：

```python
d["best_failed_count"] = 0
d["best_passed_count"] = 20
d["best_real_max_err"] = 0.5
```

- 写入值全部真实（它刚测得），**但未写 `best_commit`**——锚点仍停留在框架 iter-0 记录的修复前 `549ba00`，形成 `(best_passed=20, best_commit=修复前)` 的张冠李戴配对。
- 同一步它正确使用了授权通道（每个 case 写 `last_fix_commit: b760254`）——意图是完善交接，非篡改路由。
- 它不知道 converge 的锚点语义（该知识只在框架 Python 代码内），故没写也不写 `best_commit`。

### F4：契约缺口——`best_*` 在 agent 可见文本中处于「看得见、无标记、不在任何禁写清单」

- `SKILL.md:55-60`（写 control.json 契约）：正向授权 `case.status` / `attempt_count` /
  `upstream_*` / `stalled_*`，仅禁 `history`；清单**无排他性声明**（未列 ≠ 禁止）。
- `references/_shared-protocol.md:15`：把 `best_*` 列入 control.json「跨域共享态」字段清单（**邀请性描述**）。
- `_shared-protocol.md:35`：只读栅栏仅覆盖 `history` + 5 个路由计数器（corrective_cycles /
  refine_cycles / consecutive_aborts / run_iter_counter / diagnose_stalls）——`best_*` 不在栅栏内。
- 框架侧「framework-owned」声明只存在于 Python 注释（`_update_best_metrics` docstring），agent 永远看不到。

### F5：栅栏沿革——曾经存在，两次重构先后删除，无机制报警

- `951a92c5`（2026-07-24）时代：diagnose 旧 prompt 有显式禁写清单
  「不得修改：`status` / `current_case_index` / `debug_state` / `printf_location_result` / **`best_*`**（框架或其他 phase 负责）」。
- `dbf4d65a`（2026-08-23，P3-A diagnose 去枚举）：删除旧 prompt 体系（含上述栅栏），**未迁移进新 SKILL.md**。
- `6d9a5022`（N1 run_tests 纯 Python 化）：删除 `ascendc-precision-run-tests` skill——
  「`best_*` 框架 `_update_best_metrics` 维护，agent 不写」这句话的最后栖身之处。
- 本 run（2026-09-03）是栅栏消失后第 11 天。文本栅栏的删除无任何机制可察觉。

### F6：框架侧放大器——严格大于比较跳过快照 + 快照语义错误

- `precision_debug_substages.py:2322-2323`：仅当 `_update_best_metrics` 返回 True（passed **严格大于**旧值）
  才调 `_snapshot_best_commit`。agent 预写了 20 → 复测 20 → `20 > 20 = False` → **本应拍到 `b760254` 的快照被跳过**。
- `_snapshot_best_commit`（:1050）语义 = 「测后 HEAD」而非「被测二进制的构建源 commit」：
  本次 harness 测的是 16:47 部署的 binary，commit 16:52 才打——即使正常快照拍到 `b760254` 也属时序巧合，非 provenance 关联。

### F7：部署记录与源码 commit 零关联

`last_deploy.json` 全部字段：`run_package` / `wheel_package` / `ld_library_path_add` /
`smoke_passed` / `install_path` / `python_path`——**无 `source_commit`**。部署产物无法追溯到构建源。

### F8：converge 后果链——回退抹掉修复 + callable smoke 无法拦截 + 表述误导

- rollback（scoped checkout+clean）把修复从工作区抹掉（`b760254` 仍在 git 历史，但工作树回修复前）。
- smoke 仅 callable 探测（`smoke_probe=true, golden_used=false, diff=-1`），精度崩坏不可见。
- 日志「eval will run the best-passed-count commit」字面为真、语义为假（best_passed=20 属于 `b760254` 的代码）。
- **工作区残留至今**：worktree HEAD=`b760254` 但 `apply_adam_w.h` 为修复前内容（git diff 呈现修复的反向）。

### F9：平局盲区独立于 agent 写入存在

`_update_best_metrics` 的严格大于语义：若 iter-0 直接 20/20、diagnose 修复部分问题、loopback 复测仍 20/20
（passed 相等），`best_commit` 同样不更新、converge 同样回退掉修复——**无需 agent 越权即可复现同类事故**。

### F10：`root_cause_ledger` 空置，修复史断链

agent `_summary` 未写 `git_commit` 字段 → `_merge_fix_into_ledger`（:671）no-op →
`root_cause_ledger=[]` → `precision_report.md` 修复历史表 commit 列为 `-`（另一条本可纠偏的通道失效）。

### F11：教学双通路

框架渲染的 prompt（`precision_debug_substages.py:2522`「写 control.json：case.status…」）与
SKILL.md 契约是两条并行教学路径——历史上改一处漏一处的结构性根源。

### F12：兄弟 skill 生态仍在教同类行为

`ascendc-precision-dump-debug/SKILL.md:215-240`、`ascendc-pipeline-sync-debug/SKILL.md:319-344`
至今指示 agent 维护 `best_snapshot`（更优才覆盖比较）。diagnose agent 不加载它们，但同仓生态内
「agent 更新 best 记账」是被明令要求的正常行为，强化了越权的合理推断。

### F13：用户可见的误导渲染

`precision_report.md` 终态：「最优 commit: `549ba00163a1…`」+「通过/失败: 20/0/0」——
把被污染的配对原样呈现给用户，「20 全过」归到了修复前 commit 头上。

## 根因（事实链）

1. **契约层（第一因）**：`best_*` 的框架产权在 agent 可见的全部文本中零表达，反而在共享态清单被列为可读写对象（F4/F5）；触发条件是 agent 现场看到的过期计数（1/19）与自己刚证明的事实（20/20）矛盾（F3）。
2. **框架层（放大器）**：比较基线无 provenance 甄别（F6 前半）+ 快照语义为「测后 HEAD」（F6 后半）+ 部署无 commit 关联（F7）。
3. **收尾层（后果落地）**：converge 消费裸 `best_commit` 锚点回退工作区（F8），callable smoke 无质量信号拦不住（F8），平局盲区使该族事故不依赖 agent 越权即可复发（F9）。
