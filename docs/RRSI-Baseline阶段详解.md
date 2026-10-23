# RRSI Baseline 阶段详解（ascendc-devkit 实例）

> **对应代码**：`rrsi/loop.py:181` `Run.baseline`
> **触发命令**：`python3 rrsi.py --domain ascendc-devkit baseline`
> **所属文档**：《RRSI-AscendC-DevKit-整体运行流程.md》§6 的展开篇
> **文档日期**：2026-10-22

---

## 目录

1. [这一步在全局中的位置](#1-这一步在全局中的位置)
2. [通俗理解：给卫冕冠军测起点成绩](#2-通俗理解)
3. [触发命令与前置条件](#3-触发命令与前置条件)
4. [五步详解：每步做什么、为什么](#4-五步详解)
5. [测量的到底是什么](#5-测量的到底是什么)
6. [有效性门禁：为什么 missing 一票否决](#6-有效性门禁)
7. [产物详解：写下了什么、每一步去哪了](#7-产物详解)
8. [baseline 之后：这些数字如何被使用](#8-baseline-之后)
9. [边界情况与 FAQ](#9-边界情况与-faq)

---

## 1. 这一步在全局中的位置

RRSI 进化主循环（`run` 命令，round 0..T−1）的每一轮都在做同一件事：

```
起草候选 harness → 评测 → 和「当前冠军」比分数 → 谁分高谁上位
```

所有这些比较都要有一个**参照原点**——「原始（未进化）harness 的成绩」。
baseline 阶段就是**在开赛之前，认真测一次这个原点，并记入档案**。

```
┌── baseline（本文档）──┐      ┌────── 之后的每一轮 run ──────┐
│ 原始 harness 跑 k 遍  │      │ 改过的 harness 跑 k 遍        │
│        ↓             │      │        ↓                     │
│ 得到起点分 S₀         │ 比较 │ 挑战者分 ≥ S* − δ 才能上位？  │
│        ↓             │ ──→  │        ↓                     │
│ 记入记分板 S* = S₀    │      │ 赢了 → 成为新冠军，更新 S*     │
└──────────────────────┘      └──────────────────────────────┘
```

它**不提出任何修改、不做任何进化**——只测量、只记录。但没有它，后面 20 轮
的一切「进步/退步」判断都没有依据。

---

## 2. 通俗理解

把整个进化过程想象成一场**挑战赛**：

| 比喻 | 术语 | 实际含义 |
|---|---|---|
| 🏆 卫冕冠军 | incumbent（H₀） | **还没进化过**的原始 DevKit 流水线 |
| 🥊 挑战者 | candidate | 以后每轮提出的 harness 修改版本 |
| 📏 记分板 | frontier.json | 「当前冠军是谁、成绩多少」的档案 |
| 📜 历史最高纪录 | S*（S_star） | 迄今任何版本达到过的最高分 |

baseline = **给冠军做一次正式的起点测成绩**：

- 不测，比赛没法判胜负（任何一个候选跑出 72 分，你无法判断是「进步」
  还是「本来就这水平」）；
- 测得不准，比赛照样废（起点分被环境故障污染，后面全白跑）。

所以 baseline 有两条铁律：**必须先测**；**测不可靠就拒绝开赛**。

---

## 3. 触发命令与前置条件

```bash
python3 rrsi.py --domain ascendc-devkit baseline [--job base]
```

前置条件：

| 条件 | 说明 | 不满足时的表现 |
|---|---|---|
| cann-bench 任务集就位 | `rrsi.json` 的 `bench.cann_bench` 指向的目录里能找到 evolve split 的任务（本实例：`tasks/level1/exp`） | `bench/tasks.py` 解析报 `TaskError` |
| NPU 卡可用 | `npu_ids: [3]` 指定的卡健康 | trial 大量 missing → 触发 §6 门禁退出 |
| CANN 环境存在 | `/usr/local/Ascend/cann-9.1.0/set_env.sh` | 同上 |
| 仓库可建分支 | git 工作区允许创建 `evolve/ascendc-devkit` | `ensure_branch` 报错 |

可选预检（不强制）：先跑 `python3 rrsi.py --domain ascendc-devkit smoke`，
用 1 个任务快速确认 harness 能编译、能 import、能端到端跑通一个 trial。

---

## 4. 五步详解

### Step ① `ensure_branch` —— 给起点拍张快照

**做什么**：确保 git 分支 `evolve/ascendc-devkit` 存在（不存在则基于当前
HEAD 创建）。

**为什么**：把「原始 harness」的状态永久固定成一个 git 存档点。以后 20 轮
不管怎么改，这个存档点永远可回退、可 diff「改了什么」。冠军的身份从此是
一个具体 commit，不是「工作目录里现在的样子」。

**类比**：体检前先拍照存档——之后每次复查都和这张照片对比。

### Step ② checkout worktree —— 复印一份来测，不动原件

**做什么**：从 `evolve/ascendc-devkit` 分支 checkout 一个 detached worktree
到 `runs/ascendc-devkit/wt/incumbent`。

**为什么**：评测要**真的运行** harness，但不能污染原件。worktree 是 git 的
「平行工作副本」——在里面跑、装、写产物，原件分支纹丝不动。

**类比**：抽血化验，而不是把人切开。

### Step ③ 跑满 evolve split × k 个 trial —— 让冠军实际写两遍算子

**做什么**：调用 `rrsi/evaluate.py: evaluate` →

```
Domain.run  → 候选 worktree 里的 bench/run_tasks.py
              （负责 CANN 环境、NPU 卡探测、DevKit batch manifest）
              → DevKit 以 self_evolve_op 工作流完整跑一遍算子生成
Domain.score → 冻结的 bench/score.py 读产物打分
```

本实例的实际规模：

```
evolve split = 1 个任务（tasks/level1/exp）
k = 2
→ 共 2 个 trial：同一个算子，独立完整地写 2 遍、各评一次分
```

**为什么跑 2 遍而不是 1 遍**：真机运行有随机性（环境抖动、超时边缘、
agent 决策的随机性），同样的 harness 两次跑分可能不同。跑 k 次取平均，
把起点分磨得更可信。这个次数就是超参 `k=2`。

### Step ④ missing 门禁 —— 秤是坏的，就别开始减肥

**做什么**：统计「压根没跑起来」的 trial 数（无 meta.json 或无 verdict.json，
即基础设施失败，连评分产物都没留下），检查：

```
missing > invalid_missing_frac(0.15) × 期望 trial 数  →  SystemExit 退出
```

本实例的数值要特别注意：期望 trial 数 = 1 任务 × k=2 = **2**，
`0.15 × 2 = 0.3`，而 missing 是整数——所以 **2 个 trial 里只要挂 1 个，
baseline 直接失败退出**。（split 恢复成 6 任务 × k=2 = 12 trials 后，
容忍度放宽到挂 1 个仍可通过、挂 2 个退出。）

**为什么这么严**：区分两种「得 0 分」——

| | 算子写得烂 | 环境没跑起来 |
|---|---|---|
| 产物 | 有 verdict，reward=0（present-zero） | 无 verdict（missing） |
| 性质 | **能力问题**，正是要测量的东西 | **基础设施问题**，与能力无关 |
| 处理 | 正常计 0 分参与平均 | 计 0 分但占用分母；**超过容忍线 → 整个 baseline 作废** |

起点分被环境故障污染，后面所有「进步/退步」判断全是错的。带病继续跑，
等于跑完 20 轮才发现参照原点就是错的——全部评测算力白花。所以门禁的
选择是：**拒绝开赛，先修环境**。

### Step ⑤ 写 frontier.json —— 正式登记冠军成绩

**做什么**：把测量结果与档案写盘（详见 §7）。

**为什么**：从此刻起，「冠军是谁、多少分、历史最高纪录多少」这三件事
有了权威记录，主循环的每一轮都以它为起点。

---

## 5. 测量的到底是什么

### 5.1 一次 trial 的完整链路

```
DevKit harness（原始版）
  └─ workflow: self_evolve_op
     entry → context → requirement → [general-design | detailed-design]
     → test_design → codegen_init → codegen → precision_debug
     → cannbench_adapt → cannbench_eval → finalize
        ↓
cann-bench 评测报告（kernel_eval）
  compilation_score(20) + function_score(30) + performance_score(50) = overall_score(100)
        ↓
reward = clamp(overall_score / 100, 0, 1)
```

### 5.2 两个聚合量

`rrsi/evaluate.py: aggregate` 把 2 个 trial 折算成：

| 量 | 公式 | 本实例含义 | 后续用途 |
|---|---|---|---|
| **S**（得分） | 所有 trial reward 的加权平均 | 比如 2 次跑出 0.74 / 0.70 → S₀=0.72 | 比较「谁上位」 |
| **C**（成本） | 有 token 计数的 trial 的平均 policy tokens | 平均每次尝试花多少 token | 成本规则：增益要用 token 买单 |

另外 `score.py` 顺带产出领域聚合指标（`extra`）：`valid_rate`、`pass_rate`、
`no_submission_rate`、`eval_missing_rate`——它们进 frontier，供后续每轮的
**guards**（非补偿性准入检查）与 incumbent 对比。

### 5.3 关键语义：missing 与 present-zero 的区别

```
trial 三种结局：
├─ 正常完成        → reward = overall/100          （参与平均）
├─ 能力性失败      → 有 verdict，reward = 0        （present-zero，参与平均）
│   （编译失败 / 精度失败——正是要测量的对象）
└─ 基础设施失败    → 无 meta 或无 verdict           （missing）
    （计 0 分且占用分母；数量超限 → baseline 作废）
```

这个设计堵死了一条作弊路径：**候选无法靠「把 trial 搞挂」让自己显得更好**——
挂掉的 trial 不会从分母里消失。

---

## 6. 有效性门禁

汇总 Step ④ 的逻辑与处置：

```
missing ≤ 0.15 × 期望数 ？──是──→ 继续（写 frontier，进 calibrate）
        │否
        └──→ SystemExit("baseline invalid: m/n trials missing")
             主循环不启动；已落盘的 trial 产物保留（resume-safe），
             修好环境后重跑 baseline，已完成的 trial 自动跳过、只补挂掉的。
```

为什么用「占满分母的 0 分」而不是「从统计里剔除」？——剔除会制造漏洞：
一个 harness 可以故意让难的任务崩溃，从而只在自己擅长的任务上被平均。
**分母恒定**才能保证分数可比。

---

## 7. 产物详解

baseline 在**五个层面**各留下产物。全景树（⭐ = 删了会伤演化状态）：

```
git 层      evolve/ascendc-devkit 分支（新建的引用，非文件）  ← 起点存档
worktree 层 runs/ascendc-devkit/wt/incumbent/      ← H₀ 完整检出（~121 MB）
评测原始层  runs/ascendc-devkit/jobs/base/
            ├── batches/<stamp>/                   ← DevKit batch 完整现场
            │   ├── manifest.yaml                  ← 交给 DevKit 的任务清单
            │   ├── driver.log                     ← batch driver 完整日志
            │   ├── repos/<run_id>/                ← 本次 trial 的 cann-bench worktree
            │   └── devkit/<batch_id>/<run_id>/
            │       ├── state_snapshot.json        ← DevKit 最终状态（判分依据）
            │       ├── events.jsonl / run.log / PROVENANCE.json
            │       ├── agents/*.session.json      ← 各阶段 agent 会话
            │       └── artifacts/                 ← requirement.md、design 等
            ├── <op>/t<k>/
            │   ├── meta.json ⭐ + verdict.json ⭐  ← 判分输入（present/missing 判据）
            │   └── op_src/                        ← 拷回的生成代码
            ├── summary.json                       ← run_tasks.py 本次汇总
            └── eval.json ⭐                       ← EvalResult 聚合
聚合状态层  runs/ascendc-devkit/
            ├── frontier.json ⭐                   ← 记分板
            ├── history.jsonl ⭐                   ← 编辑历史（首条 BASELINE）
            └── calibration.json ⭐                ← 噪声带 δ（自动附带）
日志层      runs/ascendc-devkit/logs/base.log      ← runner 启动命令 + 汇总
```

`<stamp>` 格式为 `%Y%m%d-%H%M%S-t<trials>-<pid>`（如
`20261022-162821-t000-44888`）。产物**逐步出现**：batches 现场先写
（Step③ 进行中），聚合产物最后写（Step⑤ 收尾）——§7.9 的半途实况可以
直接对照。`runs/` 全景另见同目录 [runs-directory.md](runs-directory.md)。

### 7.1 `frontier.json`（记分板，主循环的权威状态）

```json
{
  "domain": "ascendc-devkit",
  "incumbent": {
    "t": 0,                      // 第 0 代（进化前的原始版本）
    "commit": "<evolve分支tip>",  // 冠军的 git 身份
    "harness_tree": "<tree哈希>", // harness 目录内容指纹（防中途被偷改）
    "job": "base",               // 这次测量对应的评测 job 名
    "S": 0.72,                   // 冠军成绩
    "C": 52300,                  // 平均每 trial token 成本
    "extra": { "valid_rate": ..., "pass_rate": ..., ... }
  },
  "S_star": 0.72,                // ★ 历史最高分纪录（后续只增不减）
  "trajectory": [
    { "t": 0, "S": 0.72, "C": 52300, "commit": "...", "job": "base" }
  ],
  "config": { "...完整超参快照..." }
}
```

逐字段说明：

| 字段 | 通俗含义 | 谁在什么时候读它 |
|---|---|---|
| `incumbent.commit` | 冠军是哪个 commit | 每轮起草时从这里开分支 |
| `incumbent.harness_tree` | 冠军内容的指纹 | 每轮开始前核对，不一致直接拒跑 |
| `S_star` | 历史最高纪录 | 每轮准入判断：`S′ ≥ S* − δ` |
| `trajectory` | 逐轮成绩曲线 | 停滞标志 σ_t、status 展示 |
| `config` | 本次 run 的超参快照 | 事后审计「当时用了什么参数」 |

### 7.2 `jobs/base/eval.json`（测量聚合）+ `summary.json`（发车汇总）

`eval.json` 是 `EvalResult` 序列化（`rrsi/evaluate.py:71-101`）：S、C、
missing 统计、领域聚合 `extra`，以及每任务的逐 trial 数据：

```json
{ "job": "base", "k": 2,
  "S": 0.72, "C": 52300,
  "n_expected": 2, "missing": 0,
  "extra": { "valid_rate": 1.0, "pass_rate": 0.9, "no_submission_rate": 0.0,
             "eval_missing_rate": 0.0 },
  "per_task": { "exp": { "rewards": [0.74, 0.70], "weights": [1.0, 1.0],
                         "tokens": [53100, 51500], "missing": 0, "extra": {} } } }
```

后续轮次做对比读的是它（`loop.py:112` `incumbent_eval`），而不是重新跑
一遍冠军；`extra` 里的四个率值是后续每轮 **guards** 的对比基准。
`summary.json` 是 `run_tasks.py` 自己写的运维汇总（发了哪些 batch、各
trial 状态），排障时先看它再下钻 batches。

### 7.3 `jobs/base/<op>/t<k>/`——判分输入：`meta.json` + `verdict.json`

整个评测体系中**决定分数的最小单元**，也是「present vs missing」的判据
（**两个都存在 = present**；只有 meta = 基础设施失败 = missing）。精度
问题溯源时的第一手证据。

`verdict.json` 关键字段（`bench/score.py` 从 DevKit 的
`state_snapshot.json` 冻结转换而来，转换后判分不再受现场变动影响）：

| 字段 | 含义 |
|---|---|
| `score` | `clamp(overall_score/100, 0, 1)`——RRSI 的 reward |
| `overall_score` | 编译+功能+性能，满分 100（20/30/50） |
| `pass_rate` | 用例通过率 |
| `valid` / `no_submission` | 是否拿到有效 eval_result / 是否没产出部署产物 |
| `scores_consistent` | 三项分相加是否等于总分；不一致时 score 直接记 0（防越界 reward） |
| `status` | `ok` / `score_inconsistent` / `harness_error` |
| `snapshot` / `report_path` | 指回原始产物，人工复核用 |

`meta.json` 记录运行元信息与溯源：状态、`attempts`（重试次数）、
`exit_code`、`timed_out`、`log_tail`、所用 NPU `card`、`repo_head`、
`harness_tree`。

### 7.4 `jobs/base/batches/<stamp>/`——DevKit batch 的完整现场

一次评测 = 一个 DevKit batch。这是体量最大的目录（agent 会话 + cann-bench
worktree + opencode 数据，合计约 89 MB），也是**过程证据**的主体：agent
到底干了什么，全在这里。

| 路径 | 内容 |
|---|---|
| `manifest.yaml` | 交给 AscendC-DevKit 的 batch 清单（任务、workflow、环境、卡） |
| `driver.log` | batch driver 完整日志——排障第一入口 |
| `repos/<run_id>/` | 本次 trial 的 cann-bench worktree（任务 + 生成代码落点） |
| `devkit/<batch_id>/<run_id>/state_snapshot.json` | DevKit 最终状态，**verdict 的判分依据** |
| `devkit/.../events.jsonl` | 事件流：阶段进出、门禁、回环、infra 重试 |
| `devkit/.../run.log` | 单任务运行日志 |
| `devkit/.../PROVENANCE.json` | 环境与版本溯源 |
| `devkit/.../agents/*.session.json` | 各阶段 agent 会话（requirement/design/codegen…） |
| `devkit/.../artifacts/` | requirement.md、design、hw_params 等中间产物 |

以后主循环 Step1 的失败分析（analyst 读的轨迹）就是从这些现场渲染出来的；
`logs/base.log` 只有启动命令和汇总行，真正的过程全在这里。

### 7.5 `history.jsonl` 的第一条记录

```json
{ "t": 0, "variant": "-", "edit_id": null, "component": null,
  "hypothesis": "H_0 baseline", "outcome": "BASELINE",
  "S": 0.72, "C": 52300, "accepted": true,
  "delta_S": null, "delta_C": null, "bundle": 0 }
```

编辑历史的时间从此开始计——proposer 以后读历史时，第一条就是起点。

### 7.6 自动触发的 `calibration.json`

CLI 里 `baseline` 子命令在 `run.baseline()` 之后**紧跟着执行
`run.calibrate([job])`**（`rrsi.py:100-102`）：用刚测的这批 trial 做
bootstrap，估出噪声带 δ 写入 `calibration.json`。也就是说，跑一次
`baseline` 命令 = 起点成绩 + 噪声带 一次拿到。（单 job 的估计样本较少；
需要更稳的 δ 可多次评测不同 job 后再跑 `calibrate --jobs base,base2`。）

### 7.7 `logs/base.log` 与 `wt/incumbent`（过程产物）

- **`logs/base.log`**：`Domain.run`（`adapter.py:197`）追加写入的 runner
  输出——启动命令行 + 少量汇总行（trial 数、用卡、python 路径）。排障时
  先看它确认「发车了吗、参数对不对」，再下钻 batches 的 `driver.log`。
- **`wt/incumbent/`**：从 `evolve/ascendc-devkit` 分支 detach 出的**整个
  仓库**的 git worktree（约 121 MB，对象与主仓硬链接共享）。注意它不是
  AscendC-DevKit 的单独副本——其中只有 `harness_path` 指向的
  `third_party/AscendC-DevKit/src/ascendc_devkit` 会随候选变化，`bench/`
  打分逻辑保持冻结。baseline 每次重跑会重新 `worktree add`；heldout 用
  同款命名（`wt/heldout_<label>`）。

### 7.8 哪些产物是「积分的」，哪些是「过程的」

| 类别 | 文件 | 说明 |
|---|---|---|
| ⭐ 积分的（删除伤状态） | `frontier.json`、`history.jsonl`、`calibration.json`、`jobs/base/eval.json`、`<op>/t<k>/{meta,verdict}.json` | 分数与演化状态本身，也是 resume 的最小依赖 |
| 过程证据（可安全清理） | `jobs/base/batches/`、`summary.json`、`logs/`、`wt/incumbent` | 分数一旦固化进 verdict/eval，删除只丢审计材料 |

完整清单与「完全重置」步骤见同目录
[runs-directory.md](runs-directory.md) §9。

### 7.9 当前 checkout 的实况（2026-10-22）

本仓库确实发起过一次 baseline，截至本文更新**尚未跑完**——正好可以
对照实物理解「产物是逐步出现的」：

- 启动时间就写在 batch 目录名里：`jobs/base/batches/20261022-162821-t000-44888/`
  （2026-10-22 16:28:21；`t000` = 启动时 0 个已完成 trial；`44888` = 进程号）；
- 实际命令（见 `logs/base.log`）：`run_tasks.py --job base --n 1 --ids exp`
  ——本次用的是 **k=1**（非默认 k=2）、1 个任务（`exp`）、NPU 卡 3；
- trial 正在推进：`devkit/.../state_snapshot.json` 显示
  `current_stage = "template-division"`（requirement 阶段的子步骤）；
- 因此 `eval.json` / `frontier.json` / `history.jsonl` / `calibration.json`
  **都还没出现**——它们要等 trial 完成、score.py 打分、通过 §6 门禁之后
  才落盘；
- 另有 `jobs/drycheck/dry-run/manifest.yaml`：来自一次 `run_tasks.py
  --dry-run`，只检查命令拼装、不发车、无分数。

这份「半途现场」正好演示了 §4 五步的时序：batches 现场先出现（Step③
进行中），聚合产物最后出现（Step⑤ 收尾）。

---

## 8. baseline 之后

起点分数如何进入主循环的每一个判断：

| 判断 | 用到 baseline 的什么 | 规则 |
|---|---|---|
| 噪声底线 | `S* = S₀` | 候选 `S′ ≥ S* − δ` 才有资格上位（不许顺着噪声下山） |
| 成本规则 | `C_t = C₀` | `ΔC = (C′ − C₀)/C₀`；增益大于 δ 时 token 增长须 ≤ β0 + β1·ΔS |
| 失败分析 | `jobs/base/eval.json` 的 per_task | 每轮 Step1 从这里取「最差任务的最差 trial + 最好任务的最好 trial」给 analyst |
| guards | `extra` 里的率值指标 | 候选不得让 missing 率/no-submission 率上升、valid/pass 率下降超过阈值 |
| 预测归因 | per_task 逐任务均值 | proposer 声称「此编辑会移动任务 X」→ 对照 incumbent 的任务分验证命中率 |

换句话说：**baseline 的一次测量，被后面 20 轮反复引用**——这正是它必须
先做、且必须可信的原因。

---

## 9. 边界情况与 FAQ

**Q1：baseline 中途挂了，重跑会重复花钱吗？**
不会。评测是 resume-safe 的：`run_tasks.py` 看到 trial 已有 meta+verdict
就跳过，只补挂掉的；`eval.json` 与 frontier 在成功收尾时才写。

**Q2：为什么 k=2、1 个任务时，挂 1 个 trial 就直接失败？**
`0.15 × 2 = 0.3`，missing 是整数，1 > 0.3。这是小 split 下的自然结果——
样本这么少，每一个 trial 都必须有效，起点分才可信。把 `ops_train.txt`
恢复成六算子 split 后，容忍度相应放宽（12 trials 容忍 1 个）。

**Q3：baseline 和 `heldout` 有什么区别？**
baseline 测 **evolve split**（本实例 `tasks/level1/exp`），结果进选择逻辑；
heldout 测 **从没参与过进化**的任务集（gather/scatter/transpose/top_k），
只做泛化验证，**不参与**任何候选提案或选择。两者都跑「评测并存 eval.json」，
但用途完全不同。

**Q4：想换超参（比如 k=3）重测起点？**
直接 `python3 rrsi.py --domain ascendc-devkit baseline --k 3 --job base3`。
注意：frontier 会被覆盖，且后续轮的 ΔS/ΔC 都相对新起点计算；正式 run 前
确定超参，中途别换。

**Q5：S 一定是「分数」吗？**
是本实例如此（`overall/100`）。框架本身支持带权 reward（如 Harvey LAB 的
「通过标准数/总标准数」配 weight=总标准数），但 ascendc-devkit 每个 trial
权重恒为 1。

**Q6：能跳过 baseline 直接 run 吗？**
不能。`run` 读不到 `frontier.json` 会直接 `SystemExit: no ...; run baseline
first`（`loop.py:96`）。这是有意设计：没有可信原点就不允许开赛。

---

## 附：本实例 baseline 的实际数值预期

| 项 | 值 |
|---|---|
| 任务数（evolve split） | 1（`tasks/level1/exp`，最小端到端配置） |
| 每任务 trial 数 k | 默认 2；本 checkout 首跑实际用 k=1（`logs/base.log` 中 `--n 1`） |
| 期望 trial 总数 | k × 任务数（默认 2；首跑为 1） |
| missing 容忍 | 0（挂 1 个即退出；k=1 时同样挂 1 个即退出） |
| 单 trial 超时 | 4 小时（+600s 宽限），每任务最多 3 次尝试 |
| reward 上限 | 1.0（= overall_score 100：编译 20 + 功能 30 + 性能 50） |
| 评测卡 | `npu_ids: [3]`，CANN 9.1.0，目标芯片 A5 |
| 结束后自动产出 | frontier.json + history 首条 + calibration.json(δ) |

---

*本文档为《RRSI-AscendC-DevKit-整体运行流程.md》§6 的展开篇，依据
`rrsi/loop.py`、`rrsi/evaluate.py`、`rrsi/calibrate.py`、
`domains/ascendc-devkit/{adapter.py, bench/}` 源码编写；行为以仓库当前
代码为准。*
