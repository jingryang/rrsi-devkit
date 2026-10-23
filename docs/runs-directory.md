# `runs/` 目录说明

`runs/` 是 RRSI 在运行时写出的**唯一状态目录**。它不属于源码，已被
`.gitignore` 忽略（`.gitignore:1`），所有内容都可以在进程重启后被复用。
本文解释它为什么存在、每一层目录由谁写入、以及哪些数据可以安全清理。

- 默认位置：`<repo>/runs`
- 修改方式：`python3 rrsi.py --runs /path/to/runs ...`
- 代码入口：`rrsi/loop.py:78-91`（`Run.__init__` 统一创建目录）

```bash
python3 rrsi.py --domain ascendc-devkit baseline   # 评测 H_0，写入 runs/
python3 rrsi.py --domain ascendc-devkit run        # 多轮演化，继续写入 runs/
python3 rrsi.py --domain ascendc-devkit status     # 从 runs/ 读取并打印状态
```

---

## 1. 它解决什么问题

RRSI 的每一轮都会：

1. 分析当前 harness `H_t` 的评测轨迹；
2. 在独立 git worktree 中起草候选 `H'`；
3. 在完整训练集上评测候选；
4. 裁决（`S'`、成本、噪声带、领域 guard）并把结果写回编辑历史；
5. 采纳候选则 `fast-forward` `evolve/<domain>` 分支。

每一步都可能耗时数小时（一次 AscendC-DevKit trial 的超时默认 14400 秒）。
因此所有中间结果都落盘到 `runs/`，做到 **resume-safe**：

- 已完成的 trial 有 `meta.json` + `verdict.json`，重跑会直接跳过；
- 已起草并 commit 的候选有 `prep.json`，重跑会复用其分支和 worktree；
- 已评测的候选有 `eval.json`，重跑会复用分数；
- 已分析过的轮次有 `analysis_report.json`，不再重复调用 LLM。

崩溃后重新执行同一条命令即可从断点继续，而不是从头烧一遍算力。

---

## 2. 总体结构

```
runs/
├── opencode.json                     # opencode 后端凭据/模型配置（本机运行配置）
├── baseline.log                      # 人工重定向的输出（不是 RRSI 生成）
└── <domain>/                         # 每个 domain 一套独立演化状态
    ├── frontier.json                 # 演化前沿 H_t、S*、轨迹
    ├── calibration.json              # 噪声带宽 delta
    ├── history.jsonl                 # 编辑历史 L_t（每次编辑一行）
    ├── attribution.jsonl             # 逐编辑归因结果
    ├── global_analysis.json          # analyst 的全局失败模式/成功习惯
    ├── STOP                          # 存在时 driver 在当前轮结束后停止
    ├── logs/                         # 各阶段日志
    ├── wt/                           # 本仓库的 git worktree（完整检出）
    ├── r<t>/                         # 第 t 轮的分析、候选与裁决
    └── jobs/                         # 原始评测产物，按 job 隔离
```

本 checkout 的当前实例是 `runs/ascendc-devkit/`。

---

## 3. `runs/<domain>/` 下的状态文件

| 文件 | 写入者 | 作用 |
|---|---|---|
| `frontier.json` | `rrsi/loop.py:99` | 当前前沿。结构见下 |
| `calibration.json` | `rrsi/loop.py:209` | 由 `calibrate` 生成；`delta = z * sd(null ΔS)` |
| `history.jsonl` | `rrsi/history.py:70` | 每次编辑一条 JSON 记录（`L_t`） |
| `attribution.jsonl` | `rrsi/loop.py:175` | 每个编辑的预测任务命中率与未预测回归 |
| `global_analysis.json` | `rrsi/loop.py:265` | 最近一次分析出的失败模式/成功习惯，供下一轮使用 |
| `STOP` | 人工 `touch` | driver 在**当前轮结束后**退出（`rrsi/driver.py:75`） |

### `frontier.json`

```json
{
  "domain": "ascendc-devkit",
  "incumbent": {
    "t": 0,
    "commit": "<git sha>",
    "harness_tree": "<harness 子树的 tree hash>",
    "job": "base",
    "S": 0.0,
    "C": null,
    "extra": { "...": "领域聚合指标" }
  },
  "S_star": 0.0,
  "trajectory": [
    {"t": 0, "S": 0.0, "C": null, "commit": "<sha>", "job": "base"}
  ],
  "config": { "...": "本轮使用的 RRSI 超参数快照" }
}
```

- `incumbent` 是当前最优、已采纳的 harness；`harness_tree` 用于校验
  `evolve/<domain>` 分支没有被外部改动（`rrsi/loop.py:235`）。
- `S_star` 是历史最好分数，用于噪声带判定 `S' > S* - delta`。
- `trajectory` 的第 `t+1` 项存在，说明第 `t` 轮已经“settled”。

> 不要手工编辑 `frontier.json`。需要通过 `readjudicate --t` /
> `reevaluate --t` 重算时，让程序自己重写。

### `history.jsonl`

每条记录对应**一次编辑**（一个候选可以携带多次编辑，共享同一次测量）：

```json
{
  "ts": "2026-10-22 16:28:21",
  "t": 0, "variant": "A", "edit_id": "E1",
  "component": "prompt",
  "hypothesis": "把 tiling 约束写进 requirement 提示词",
  "targets_mode": "...",
  "predicted_affected": ["exp"],
  "diff": "/.../runs/ascendc-devkit/r0/A/diff.patch",
  "delta_S": 0.03, "delta_C": null,
  "accepted": true, "outcome": "ACCEPTED",
  "S": 0.42, "C": null,
  "bundle": 1, "detail": "..."
}
```

`outcome` 取值：`BASELINE` / `ACCEPTED` / `LOST` / `REJECTED` /
`critic_reject` / `smoke_fail` / `eval_invalid` / `no_proposal`。
未进入评测的候选 `delta_S = null`，不会进入 tried 集合与 yield 统计。

### `attribution.jsonl`

一行对应一个编辑：

```json
{
  "t": 0, "variant": "A", "edit_id": "E1", "component": "prompt",
  "hypothesis": "...",
  "n_predicted": 1, "predicted_hit": ["exp"], "hit_rate": 1.0,
  "unpredicted_regressions": []
}
```

用于检查“提案者声称会改善的任务”是否真的改善，以及是否引入了
未预测的回归。

### `logs/`

| 文件 | 写入者 | 内容 |
|---|---|---|
| `baseline.log` | `rrsi/driver.py:65` | `run` 模式下 driver 启动 baseline 的输出 |
| `calibrate.log` | `rrsi/driver.py:71` | 标定输出 |
| `r<t>.log` | `rrsi/driver.py:81` | driver 第 t 轮的控制流日志 |
| `base.log`、`r0A.log`、`heldout_champ.log`、… | `Domain.run`（`rrsi/evaluate.py:126`） | 每个 job 的评测命令与 stdout |

注意：`logs/base.log` 只记录 runner 的启动命令和汇总行；真正的 agent 过程
在 `jobs/<job>/batches/.../driver.log` 和 `devkit/.../run.log` 中。

---

## 4. `runs/<domain>/jobs/`：原始评测产物

`jobs/` 按 **job id** 隔离。job id 的约定：

| job | 含义 |
|---|---|
| `base` | baseline，即 `H_0` |
| `r<t><V>` | 第 t 轮候选 V（`A`、`B`、…） |
| `r<t><V>_smoke` | 候选 V 的存活检查（每次删除重跑） |
| `heldout_<label>` | 指定提交在 held-out 集上的评测 |
| `smoke` | 当前 incumbent 的冒烟检查 |
| `<job>/dry-run` | `run_tasks.py --dry-run` 生成的 manifest，不发车 |

### 目录布局

```
jobs/<job>/
├── eval.json                     # RRSI 的 EvalResult（S、C、missing、per_task）
├── summary.json                  # run_tasks.py 的本次汇总
├── <op>/t<k>/                    # 单个算子、单次 trial 的判分输入
│   ├── meta.json                 # 运行元信息 + 状态 + 分数
│   ├── verdict.json              # 由 state_snapshot 转换出的冻结判分
│   └── op_src/                   # 从 cann-bench worktree 拷回的生成代码
└── batches/<stamp>/              # 一次 DevKit batch 的完整现场
    ├── manifest.yaml             # 交给 AscendC-DevKit 的 batch 清单
    ├── driver.log                # DevKit batch driver 的完整日志
    ├── repos/<run_id>/           # 本次 trial 的 cann-bench worktree
    └── devkit/<batch_id>/<run_id>/
        ├── state_snapshot.json   # DevKit 的最终状态（判分依据）
        ├── events.jsonl          # 事件流
        ├── run.log               # 单任务运行日志
        ├── PROVENANCE.json       # 环境与版本溯源
        ├── agents/*.session.json # 各 agent（requirement/design/codegen…）会话
        ├── artifacts/            # requirement.md、design、hw_params 等产物
        ├── subprocess/
        └── .opencode_home/       # opencode 服务端配置、数据与日志
```

`<stamp>` 格式：`%Y%m%d-%H%M%S-t<trials>-<pid>`，例如
`20261022-162821-t000-44888`。

### `meta.json` 与 `verdict.json`

- **两个文件都存在** → trial 视为 present，`verdict.json` 给出分数；
- **只有 `meta.json`** → 基础设施失败（timeout / harness_error / infra_error），
  计为 missing；
- **都没有** → 计为 missing。

missing trial 的 reward 为 0，但**占用完整分母**（`rrsi/evaluate.py:28-36`）。
因此候选不能靠“让 trial 失败”来抬高分数；编译失败、精度失败仍然是
present-zero。

`verdict.json` 关键字段：

| 字段 | 含义 |
|---|---|
| `score` | `clamp(overall_score / 100, 0, 1)`，RRSI 的 reward |
| `overall_score` | `compile + function + performance`，满分 100（20/30/50） |
| `pass_rate` | 用例通过率 |
| `valid` | 是否拿到有效 `eval_result` |
| `no_submission` | 是否没有生成/部署产物 |
| `scores_consistent` | 三项分数相加是否等于总分；不一致时 `score = 0` |
| `status` | `ok` / `score_inconsistent` / `harness_error` |
| `checks` | 交叉校验失败的说明 |
| `snapshot` / `report_path` | 指回原始产物，便于人工复核 |

`meta.json` 还会记录 `attempts`、`exit_code`、`timed_out`、`log_tail`、
`card`、`repo_head`、`harness_tree` 等溯源信息。

### `eval.json`

job 级别的聚合结果（`rrsi/evaluate.py:71-101`）：

```json
{
  "job": "base", "k": 1,
  "S": 0.0, "C": null,
  "n_expected": 1, "missing": 0,
  "extra": {"valid_rate": 0.0, "pass_rate": 0.0, "no_submission_rate": 1.0, "...": "..."},
  "per_task": {
    "exp": {"rewards": [0.0], "weights": [1.0], "tokens": [null], "missing": 0, "extra": {}}
  }
}
```

`extra` 是领域聚合指标，`guards`（`domains/ascendc-devkit/adapter.py:234`）
正是比较 incumbent 与候选的 `missing`、`valid`、`pass`、`no_submission`
四项来拒绝“用可评测性换分”的候选。

---

## 5. `runs/<domain>/r<t>/`：第 t 轮的决策现场

```
r<t>/
├── analysis_report.json     # Analyze(H_t, D_evolve) 的输出
├── directives.json          # 本轮 b_t、sigma_t、tried、探索/剪枝指令、delta、S*
├── decisions.json           # 每个候选的裁决（Algorithm 2）
└── A/  B/  ...              # 每个候选一个目录
    ├── prep.json            # 提交号、分支、编辑标签（resume 依据）
    ├── proposal.json        # 提案者首次输出
    ├── proposal_r1.json     # 被 critic 打回后的修复输出（如有）
    ├── diff.patch           # harness 目录的 diff
    ├── critic_a0.json       # 第 0 次评审意见
    ├── critic_a1.json       # 修复后的复审
    ├── critic.json          # 最终评审结论
    ├── smoke.json           # 存活检查结果
    └── eval.json            # 候选评测的副本
```

`decisions.json` 中每一项：

```json
{
  "variant": "A",
  "admissible": true,
  "reason": "gain +0.0300 > delta 0.0200; cost change ...",
  "S": 0.42, "C": null,
  "delta_S": 0.03, "delta_C": null,
  "novelty": 1,
  "guards": []
}
```

候选的生命周期：

1. 在 `wt/r<t><V>` 新建 worktree，分支 `<domain>/r<t><V>`；
2. 提案 → 写 `proposal.json` / `diff.patch`；
3. critic 评审，可有限次修复 → `critic*.json`；
4. commit 到候选分支 → 写 `prep.json`；
5. 冒烟 → `smoke.json`；
6. 评测 → `r<t>/<V>/eval.json` 与 `jobs/r<t><V>/...`；
7. 轮末删除 worktree；**分支与提交保留**在 git 中。

---

## 6. `runs/<domain>/wt/`：git worktree

这里不是文件拷贝，而是本仓库的 `git worktree`：

```bash
$ cat runs/ascendc-devkit/wt/incumbent/.git
gitdir: /home/s00940212/experiments/rrsi-devkit/.git/worktrees/incumbent
```

| 路径 | 分支 | 生命期 |
|---|---|---|
| `wt/incumbent` | detached at `evolve/ascendc-devkit` | baseline / heldout 使用；每次重新 `worktree add` |
| `wt/r<t><V>` | `ascendc-devkit/r<t><V>` | 仅本轮；轮末删除，崩溃时保留供 resume |
| `wt/smoke` | detached at `evolve/<domain>` | `rrsi.py smoke` 使用 |
| `wt/heldout_<label>` | detached at 指定 ref | held-out 评测使用 |

每个候选 worktree 都是**整个 rrsi-devkit 仓库**在该 commit 下的检出，
而不是 AscendC-DevKit 的单独副本。只有 `domains/ascendc-devkit/rrsi.json`
中 `harness` 指向的 `third_party/AscendC-DevKit/src/ascendc_devkit`
会随候选变化；`bench/` 打分逻辑被冻结。

被采纳的候选通过 `git fast-forward` 合并进 `evolve/<domain>`，因此
**incumbent 永远是一个 git commit**，可以随时 `git checkout` 复核。

---

## 7. 一次完整运行的文件生命周期

```
smoke
  └─ jobs/smoke/                     （每次删除重跑）

baseline
  ├─ wt/incumbent/
  ├─ jobs/base/batches/<stamp>/{manifest.yaml,driver.log,repos/,devkit/}
  ├─ jobs/base/<op>/t<k>/{meta.json,verdict.json,op_src/}
  ├─ jobs/base/{eval.json,summary.json}
  ├─ logs/base.log
  ├─ frontier.json
  ├─ history.jsonl                   （BASELINE 记录）
  └─ calibration.json                （rrsi.py baseline 会自动 calibrate）

round t
  ├─ r<t>/{analysis_report,directives,decisions}.json
  ├─ r<t>/<V>/{proposal,diff,critic,smoke,eval}
  ├─ wt/r<t><V>/                     （轮末删除）
  ├─ jobs/r<t><V>_smoke/             （轮内冒烟）
  ├─ jobs/r<t><V>/                   （候选完整评测）
  ├─ history.jsonl / attribution.jsonl（追加）
  ├─ frontier.json                   （trajectory 增加第 t+1 项）
  └─ logs/{r<t>.log,r<t><V>.log}

heldout
  ├─ wt/heldout_<label>/
  ├─ jobs/heldout_<label>/...
  └─ logs/heldout_<label>.log
```

---

## 8. 当前 checkout 的实际状态（2026-10-22）

- `runs/ascendc-devkit/jobs/base/batches/20261022-162821-t000-44888/`
  正在跑 baseline：训练集 1 个任务（`exp`）、`k=1`、NPU 卡 `3`。
- 该 trial 的 `state_snapshot.json` 显示 `current_stage = "requirement"`，
  尚未产出 `eval.json`、`frontier.json` 和 `calibration.json`。
- `runs/ascendc-devkit/jobs/drycheck/dry-run/manifest.yaml` 来自一次
  dry-run，只用于检查命令拼装，不产生分数。
- `runs/baseline.log` 是启动命令里的 `| tee runs/baseline.log` 产生的，
  不是 RRSI 自己写的文件。

当前磁盘占用约 139 MB：

| 路径 | 大小 | 说明 |
|---|---:|---|
| `wt/incumbent` | 121 MB | 整个仓库的 worktree |
| `jobs/base/.../devkit` | 71 MB | agent 会话、artifacts、opencode 数据 |
| `jobs/base/.../repos` | 18 MB | cann-bench worktree |

（`du` 对 worktree 中的硬链接/共享对象的统计会偏高，实际增量小于上述之和。）

---

## 9. 清理与恢复

### 可以安全删除

- 已 settled 轮次的 `jobs/<job>/batches/`：分数已经固化在
  `jobs/<job>/<op>/t<k>/verdict.json` 与 `eval.json`；删除只丢失过程证据。
- `runs/<domain>/r<t>/`：仅用于复核某轮提案与裁决。
- `wt/` 下残留的候选 worktree（先 `git worktree prune`）。
- `logs/`：纯日志。

### 不要删除

- `frontier.json`、`history.jsonl`：演化状态本身。
- 未 settled 轮次的 `jobs/<job>/`：删除会迫使整个 job 重新评测。
- `r<t>/<V>/prep.json`：resume 时定位候选分支与提交的依据。

### 完全重置

```bash
# 1) 确保没有进程在写
ps aux | grep rrsi.py

# 2) 删除所有 worktree 注册，再删 runs/
git worktree list
git worktree prune
rm -rf runs/

# 3) 如需连演化分支一起重置
git branch -D evolve/ascendc-devkit
git branch | grep 'ascendc-devkit/r' | xargs -r git branch -D
```

只删 `runs/` 不会删除 `evolve/<domain>` 分支上的演化成果；重新 `baseline`
会以当前分支为 `H_0` 重建 frontier。

---

## 10. 注意事项

1. **`runs/opencode.json` 含明文 provider API key**，它通过
   `ASCENDC_OPENCODE_PROJECT_CONFIG` 传给 opencode 后端
   （`third_party/AscendC-DevKit/src/ascendc_devkit/capabilities/agent/opencode_backend.py:1379`）。
   该文件是运行时机密，永远不要提交或外传。
2. **`runs/` 已被 git 忽略**，不会出现在 `git status` 中；备份/迁移时需要单独处理。
3. **不要在运行中手改 `frontier.json` / `history.jsonl`**，否则
   `harness_tree` 校验（`rrsi/loop.py:235`）或 resume 逻辑会失败。
4. 候选分支（`ascendc-devkit/r<t><V>`）在轮末不会删除，只删除 worktree；
   长期运行后分支会累积，可在确认不再需要后手动清理。
5. 本 domain 的 `Domain.load_trial` / `render_trace` / `task_row` 目前没有在
   `adapter.py` 中实现（`rrsi/domain.py:87-94` 为 `NotImplementedError`，
   `render.py` 提供了渲染工具但尚未接线）。`baseline` 不触发这条路径，
   但首次 `round` 的 `Analyze(H_t, D_evolve)` 会调用 `load_trial`，届时需要补齐。