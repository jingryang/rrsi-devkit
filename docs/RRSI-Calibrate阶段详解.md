# RRSI Calibrate 阶段详解（ascendc-devkit 实例）

> **对应代码**：`rrsi/calibrate.py`（119 行）+ `rrsi/loop.py:209` `Run.calibrate`
> **触发命令**：`python3 rrsi.py --domain ascendc-devkit calibrate [--jobs base,base2]`
> 　（注意：`baseline` 子命令末尾会**自动附带执行一次**单 job 校准，见 §3）
> **所属文档**：《RRSI-AscendC-DevKit-整体运行流程.md》§7 的展开篇
> **文档日期**：2026-10-22

---

## 目录

1. [这一步在全局中的位置](#1-这一步在全局中的位置)
2. [通俗理解：先搞清楚你的秤有多准](#2-通俗理解)
3. [触发命令与前置条件](#3-触发命令与前置条件)
4. [核心问题：没有 δ 会发生什么](#4-核心问题没有-δ-会发生什么)
5. [δ 的定义与公式](#5-δ-的定义与公式)
6. [两种估计方法详解](#6-两种估计方法详解)
7. [产物详解：相对 baseline 新增了什么](#7-产物详解相对-baseline-新增了什么)
8. [δ 之后如何被使用](#8-δ-之后如何被使用)
9. [边界情况与 FAQ](#9-边界情况与-faq)

---

## 1. 这一步在全局中的位置

baseline（阶段一）测出了起点成绩 S₀；calibrate（阶段二）要回答下一个问题：

> **「分数波动多大算正常？」**

```
阶段一 baseline：测出起点分        阶段二 calibrate：测出「分数的抖动范围」
   S₀ = 0.72          ──────────→      δ = 0.02
   「冠军能跑 72 分」                    「同一个冠军重测，分数会上下飘 ~2 分」
              \                    /
               \                  /
                ▼                ▼
        之后每一轮 run 的所有判断都以 (S₀, δ) 这两个数为标尺：
        候选跑出 0.705 → 比 0.72 低 0.015 < δ →「在噪声范围内，不算退化」
        候选跑出 0.75  → 比 0.72 高 0.03  > δ →「真进步，但要付 token 账单」
```

它同样**不提出任何修改、不做任何进化**——只测量「测量本身的不确定度」。
但没有它，后面 20 轮的胜负判定会把运气当进步、把抖动当退化。

---

## 2. 通俗理解

### 比喻一：体重秤

你减肥前称了体重 72kg。第二天早上再称，显示 71.6kg——你瘦了吗？

**不知道。** 你还缺一个关键数据：**这台秤本身的波动范围**。家用体重秤
早上晚上差个 0.5~1kg 很正常。如果你不知道秤的误差，就会把每次 0.3kg 的
波动当成「瘦了/胖了」，行为完全被噪声牵着走。

calibrate 做的就是：**在正式开始减肥计划前，先站上秤称 20 次，搞清楚
这台秤的抖动范围是 ±0.8kg**。从此定规则：

- 体重变化 < 0.8kg → 「没变，是秤在抖」；
- 变化 > 0.8kg → 「真的变了」。

### 比喻二：考试成绩

同一个学生、同样的水平，两次月考分别考了 82 和 85——他进步了吗？要回答
这个问题，你得先知道「同一水平的学生两次考试的分数差」通常有多大
（也许就是 ±4 分）。这个「通常波动多大」就是 δ。

### 对应到本系统

「秤」= 在 NPU 上跑一遍 harness 评测；「体重」= 得分 S。**同一个 harness
原封不动地评测两次，分数也不会完全一样**——agent 决策有随机性、NPU 环境
有抖动、超时在边缘。δ 就是这个「重测波动范围」的正式度量。

---

## 3. 触发命令与前置条件

```bash
python3 rrsi.py --domain ascendc-devkit calibrate [--jobs base,base2]
```

两条路径：

| 路径 | 触发方式 | 用的数据 |
|---|---|---|
| **自动附带** | `python3 rrsi.py --domain ascendc-devkit baseline` 跑完 baseline 后紧接着自动执行（`rrsi.py:100-102`） | 刚测的这 1 个 job 的 trial 数据 |
| **手动加强** | 显式跑 `calibrate --jobs base,base2`（需要先用 `baseline --job base2` 之类的命令多测几个 job） | 多个独立评测的成绩 |

前置条件：

| 条件 | 说明 |
|---|---|
| `jobs/<job>/eval.json` 存在 | 至少要有一个已完成的基础评测（通常是 baseline 产的 `base`） |
| `cfg.delta` 未显式指定 | 若命令行给了 `--delta 0.02`，直接用给定值，**跳过估计**（`loop.py:102-104`） |

**δ 的查找顺序**（每轮 round 开始时，`loop.py:102` `Run.delta`）：

```
1. cfg.delta 显式给定？      → 用它（最高优先级）
2. calibration.json 存在？   → 读它的 "delta" 字段
3. 都没有                    → SystemExit: no noise band: set cfg.delta or run calibrate
                               （没有 δ 不允许开赛——同 baseline 门禁一个逻辑）
```

---

## 4. 核心问题：没有 δ 会发生什么

### 4.1 攻击场景一：顺噪声下山（downhill ratchet）

假设没有 δ，选择规则就是简单的「谁分高谁上位」。考虑真机噪声 ±0.015：

```
第 0 轮：冠军 S = 0.720
第 1 轮：候选 A 其实是个倒退版（改坏了一点），但赶上运气好测出 0.718
         → 0.718 < 0.720？是的 → 本应拒绝 ✓（这个例子侥幸挡住了）
第 2 轮：候选 B（又一个倒退版），运气好测出 0.721
         → 0.721 > 0.720 → 上位！其实 B 是个更差的 harness ✗
第 3 轮：在 B 的基础上继续……0.719 上位 ✗
第 4 轮：0.716 上位 ✗
……每轮「看起来差不多」的候选靠运气上位，harness 一路阴跌
```

这就是「**顺着看似噪声的退化一路下山**」——每一步的跌幅都小于噪声，
单看哪一步都「像没变」，但 10 轮下来 harness 实质性变差了。

**δ 的防线**：准入底线不是「比当前冠军高」，而是

```
S′ ≥ S* − δ      （S* = 历史最高分，只增不减）
```

任何候选想上位，成绩不得低于「历史最高分 − 一个噪声带」。倒退的候选
就是运气再好，也撞不上这条线；而 S* 锚定在历史最高值上，**不会随冠军
平庸化而下移**——退化的自动扶梯被焊死了。

### 4.2 攻击场景二：假进步骗 token 预算

反方向的漏洞：候选其实在噪声范围内波动（+0.01，可能纯属运气），却按
「真进步」领取更大的 token 预算（成本规则是「增益越大允许加越多 token」）。

**δ 的防线**：成本规则只对 `ΔS > δ` 的候选全额生效；带内波动走另一条
更严格的塑形规则（必须靠 novelty 等额外理由才放行）。**运气不够格
兑换预算**。

### 4.3 一句话

> δ 把「运气」和「实力」在数学上分开：**比 δ 差的退化不允许发生，
> 比 δ 好的进步才算数。**

---

## 5. δ 的定义与公式

### 5.1 目标量：「同一 harness 两次独立评测之差」的波动

记同一个 harness H 独立评测两次得到 S₁、S₂，定义**零差异**（null
difference）`ΔS_null = S₁ − S₂`——两个数都来自**同一个** harness，
所以这个差**纯粹是噪声**。calibrate 的全部工作就是估计它的标准差：

```
δ = z · sd(null ΔS)          z = cfg.delta_z，默认 2.0
```

### 5.2 为什么 z = 2？—— 97.5% 的含义

若 `null ΔS` 近似正态，`z=2` 意味着：

```
P(同一 harness 重测一次，分数 ≥ S* − δ) ≈ 97.5%（单侧 2σ）
```

也就是源码 docstring 那句话（`calibrate.py:39`）：**原封不动的 harness
有约 97.5% 的概率通过噪声底线**。反过来，一个候选若跌出 `S* − δ`，
只有 ~2.5% 的概率是运气不好——基本可以断定是真退化了。z 是可调的：
`--delta-z 3` 更保守（几乎不会误杀），`--delta-z 1` 更激进（容忍更高
换 qualified 进步的门槛降低）。

### 5.3 √2 从哪来（`calibrate.py:92,101`）

两个独立同方差的测量之差，方差是两者之和：

```
Var(S₁ − S₂) = Var(S₁) + Var(S₂) = 2σ²   →   sd(S₁ − S₂) = √2 · σ
```

所以不管哪条估计路径，算出单次评测的波动 σ 后都要乘 √2 才是「两次
之差」的波动。

---

## 6. 两种估计方法详解

`calibrate()`（`calibrate.py:85`）按手头数据的多少自动二选一：

### 方法 A：多次独立评测 —— 直接观测零差异（最可信）

**条件**：`evals >= 2`（比如你已经对 base harness 跑了 `base`、`base2`
两个 job，各 k=2 trials）。

**做法**：把 R 次评测的分数两两作差，直接得到零差异的样本：

```python
scores = [e.S for e in evals]                        # 每次评测的总分
sd_null = stdev(scores) * sqrt(2)                    # 两次之差的标准差
method = "repeated base evaluations"
observed = {"S_per_eval": scores, "max_abs_diff": max_diffs}
```

这是**直接测量**——零差异的实际分布就摆在眼前，不依赖任何分布假设。
产物里还会记录 `max_abs_diff`（观测到的最大绝对波动），供事后检查
「δ 是否盖住了实际见过的抖动」。

### 方法 B：单次评测 —— bootstrap 重抽样（baseline 自动附带的路径）

**条件**：只有 1 个评测 job（比如刚跑完 baseline）。

**做法**（`bootstrap_se`，`calibrate.py:54`）：把这次评测里的 trial 当作
「分数的总体」，**在每个任务内部、带权重地、有放回地重抽 k 个 trial**，
重算一遍平均分——重复 2000 次（`reps=2000, seed=7`，完全确定性、可复现）：

```
原始数据：task exp 的 2 个 trial → [0.74, 0.70]  → 平均 0.72
重抽 2000 次，每次得到一个「假想重测」的平均分：
   [0.74, 0.70] → 0.72
   [0.74, 0.74] → 0.74
   [0.70, 0.74] → 0.72
   [0.70, 0.70] → 0.70      …… × 2000
→ 这 2000 个平均分的标准差 = se（单次评测的标准误）
```

**类比**：只有一小袋豆子，想知道「再抓一把的均值的波动」——反复从袋里
抓来模拟。这是经典的 bootstrap 思想：**用手中样本模拟「重测一次」**。

最后按 §5.3 换算成两次之差的标准差（`calibrate.py:101`）：

```python
sd_boot = sqrt(2) * se * sqrt(pooled_k / eval_k)    # pooled_k = Σ各job的k
```

（`sqrt(pooled_k/eval_k)` 是修正因子：pool 了多个 job 时样本更多、
标准误按比例缩小。单 job 时该因子 = 1。）

### 选择优先级（`calibrate.py:103`）

```python
sd_use = sd_null if (len(evals) >= 2 and sd_null > 0) else sd_boot
```

> **能用直接观测就用直接观测**；只有当多次评测的分数完全相同（`sd_null=0`，
> 退化情形，通常意味着样本太少或分数粒度太粗）才退回 bootstrap。
> 无论走哪条路，两条估计都会写进产物（`sd_null` 与 `sd_null_bootstrap`），
> 供事后对比「直接观测与 bootstrap 差多少」。

### 数值例（本实例 1 任务 × k=2）

```
base job：exp 算子两次 trial = [0.74, 0.70]
→ bootstrap：重抽 2000 次 → se ≈ 0.014（4 种组合的离散度）
→ sd_boot = √2 × 0.014 ≈ 0.020
→ δ = 2.0 × 0.020 = 0.040
→ 噪声底线 = S* − 0.040 = 0.72 − 0.04 = 0.68
```

（真实数值以实际跑出的 `calibration.json` 为准；论文三实例的固定 δ 为
0.017 / 0.004 / 0.020，量级即「一到四个百分点」。）

---

## 7. 产物详解：相对 baseline 新增了什么

### 7.0 增量总览：一新增、一例外、全不变

calibrate 是整个流程里**最轻**的阶段——它**不发车、不评测、不碰 NPU、
不调 agent**，只读 baseline 留下的聚合结果做统计，然后写一个新文件：

| 相对 baseline 的变化 | 内容 |
|---|---|
| ★ **新增文件 ×1** | `runs/ascendc-devkit/calibration.json`（δ 及全部估计过程） |
| **例外新增 ×1** | `logs/calibrate.log`——仅 `run` driver 模式下出现（§7.3） |
| **其余全部不变** | `frontier.json`、`history.jsonl`、`jobs/**`（含 eval.json、batches）、`wt/**`、`global_analysis.json`、`attribution.jsonl` 原样不动 |

与 baseline 产物的**衔接关系**（只进不出，除了那一个新文件）：

```
baseline 留下的                        calibrate 的动作              新产物
┌─────────────────────────┐
│ jobs/base/eval.json     │──读──┐
│ (jobs/base2/eval.json …)│──读──┼─→ 纯统计计算          ──写─→ calibration.json
└─────────────────────────┘      │   (bootstrap / 两两作差)
   注意：只读 EvalResult 聚合，   ┘
   不读 trial 级 meta/verdict，   另：stdout 打一行汇总（终端或 driver 日志）
   不读 frontier.json
```

对照记忆：baseline 在五个层面各留产物（见 Baseline 篇 §7 全景树）；
calibrate 只在「聚合状态层」加一个文件。两条「不新增」值得专门澄清：

- **不追加 `history.jsonl`**——校准不是一次「编辑」，历史第一条仍是
  baseline 的 `BASELINE` 记录；
- **不改 `frontier.json`**——S₀ / S* / trajectory 都不动。δ 只在每轮
  开始时被 `Run.delta()` **读取**（`loop.py:102`），从不写回。

### 7.1 新增文件：`calibration.json` 逐字段

写入 `runs/ascendc-devkit/calibration.json`（`calibrate.py:111` `write`）：

```json
{
  "delta": 0.040000,           // ★ 最终采用的噪声带 = z × sd_use
  "z": 2.0,                    // 用的分位数系数
  "sd_null": 0.020000,         // 实际采用的标准差（= delta/z）
  "sd_null_bootstrap": 0.020,  // bootstrap 路径的估计（即使没被采用也记录）
  "se_bootstrap": 0.014,       // 单次评测的标准误（bootstrap 原始产出）
  "method": "bootstrap over trials of one base evaluation",
  //            ↑ 或 "repeated base evaluations"
  "n_evals": 1,                // 参与校准的评测数
  "k": 2,                      // 每任务 trial 数
  "n_tasks": 1,                // 任务数（本实例当前 1）
  "S_base": 0.720000,          // 基础评测的分数（即 S₀）
  "C_base": 52300,             // 基础评测的平均 token 成本
  "jobs": ["base"],            // Run.calibrate 包装层追加（loop.py:212）；
  //                            ↑ 多 job 加强时为 ["base", "base2"]
  "S_per_eval": [0.72, 0.71],  // ★ 方法 A 独有：各次独立评测的分数
  "max_abs_diff": 0.010        // ★ 方法 A 独有：观测到的最大绝对波动
}
```

字段分层理解——**哪些字段随估计方法变化**：

| 字段组 | 方法 B（单 job bootstrap） | 方法 A（多次评测） |
|---|---|---|
| 恒有：`delta`/`z`/`sd_null`/`sd_null_bootstrap`/`se_bootstrap` | ✓ | ✓ |
| 恒有：`method`/`n_evals`/`k`/`n_tasks`/`S_base`/`C_base`/`jobs` | ✓ | ✓ |
| 观测字段：`S_per_eval`/`max_abs_diff` | ✗（不写） | ✓（只有这里写） |
| `method` 取值 | `bootstrap over trials of one base evaluation` | `repeated base evaluations` |
| `sd_null` 的来源 | 即 `sd_null_bootstrap`（优先级规则下 bootstrap 被采用） | 直接观测值（`sd_null>0` 时） |

字段用途速查：

| 字段 | 用途 |
|---|---|
| `delta` | 主循环每轮 `Run.delta()` 读的就是它 |
| `method` / `n_evals` | 事后审计：这个 δ 是直接观测的还是 bootstrap 估的 |
| `sd_null_bootstrap` 与 `sd_null` 并存 | 两条路径互相印证；差异过大说明样本不足，值得多跑几个 job |
| `S_per_eval` / `max_abs_diff` | 检查「δ 是否盖住了实际见过的抖动」（`max_abs_diff > delta` 是危险信号） |

### 7.2 stdout 上的新增内容（不落盘，但肉眼可见）

命令执行完终端会多一行（`loop.py:213` `log`）：

```
[rrsi:ascendc-devkit] 16:35:02 calibrated delta=0.04000 (sd_null 0.02000, z=2.0, bootstrap over trials of one base evaluation)
```

手动逐条跑命令时它只到终端；用 driver 时进 `logs/calibrate.log`（下节）。

### 7.3 例外：`logs/calibrate.log`（仅 `run` driver 模式）

`python3 rrsi.py --domain ascendc-devkit run` 从零启动时，driver 会
按序补齐前置（`rrsi/driver.py:63-72`）：

```
frontier.json 不存在？  ──是──→ 子进程跑 baseline
                                stdout 追加到 logs/baseline.log
                                （baseline 子命令附带的 calibrate 输出也在这里）
calibration.json 不存在？──是──→ 子进程跑 calibrate        ← 防御性补跑
                                stdout 追加到 logs/calibrate.log
```

三点说明：

- 第二步是**防御性**的：正常情况下 `baseline` 子命令已经把
  calibration.json 写好，这里的 calibrate 只在前置意外缺失（比如 baseline
  成功但附带校准失败）时才真正执行；
- 它与 Baseline 篇 §7.7 的 `logs/base.log` 是**两个不同的文件**：
  `logs/base.log` 是 `Domain.run` 写的评测 runner 输出（发车命令、trial
  汇总）；`logs/baseline.log` 是 driver 重定向的 `rrsi.py baseline` 子命令
  输出（含 `baseline S=...` 与 `calibrated delta=...` 汇总行）；
- 手动逐条跑命令（不经 driver）时这两个 `.log` 都不会出现。

### 7.4 当前 checkout 的实况（2026-10-22）

baseline 尚未跑完（见 Baseline 篇 §7.9），所以 `calibration.json` **还
不存在**——磁盘上能看到的仍是 baseline 的半途现场（`jobs/base/batches/…`）。
此时若直接跑 `round` 或 `run`，会在 `Run.delta()` 处 SystemExit
（`no noise band: set cfg.delta or run calibrate`），正好演示 §3 的门禁：
**δ 必须先于主循环存在**。跑完 `baseline` 命令后它会自动出现。

---

## 8. δ 之后如何被使用

δ 在主循环里出现在**三个判断点**（`rrsi/selection.py`）：

### 8.1 噪声底线（准入的第一道门）

```
admissible 要求：S′ ≥ S* − δ
```

- 作用：挡住「顺噪声下山」（§4.1）；
- 锚点：S\* 是**历史最高分**且只增不减，不随冠军的平庸化下移。

### 8.2 成本规则的分界线（「真进步」的定义）

```
若 ΔS > δ  →  视为真实增益，须满足 ΔC ≤ β0 + β1·ΔS
              （β0=0.10：10% token 免费；β1=40：每 +1pp 得分买 +40% token）
若 ΔS ≤ δ  →  带内波动，走塑形规则：w_s·ΔS − w_c·ΔC + w_n·ν > 0
              （ν = novelty，结构性组件的探索加分）
```

- 作用：运气波动（≤ δ）**不能**兑换更大的 token 预算（§4.2）；
- 数值例：δ=0.04 时，候选 +0.03 的「进步」不会被按真进步对待——要么
  靠 novelty 证明结构探索的价值，要么被成本塑形规则刷掉。

### 8.3 停滞标志（提案侧的探索触发器）

```
σ_t = 1[S_t − S_{t−w} ≤ δ]        （w=3 轮窗口，`history.py:189`）
```

连续 w 轮的净变化没超过一个噪声带 → 判定「停滞」→ 本轮保留候选槽位给
**从未试过的组件**（探索槽位）。这里 δ 的作用是：**「没动静」本身也要
超过噪声才算数**——小于 δ 的蠕动不叫进展。

### 8.4 全景小结

```
              δ = 「重测波动范围」
                     │
     ┌───────────────┼────────────────┐
     ▼               ▼                ▼
 底线 S*−δ       增益分界 ΔS>δ      停滞判定 σ_t
 (选择侧：       (选择侧：          (提案侧：
  不许退)         真进步才给预算)     没进展就换方向探索)
```

---

## 9. 边界情况与 FAQ

**Q1：`--delta 0.02` 显式给了值会怎样？**
直接采用给定值，完全跳过估计，也不写 calibration.json（`loop.py:102`）。
适合已经知道噪声量级、不想花评测成本的场合；论文三实例就是固定值
（0.017 / 0.004 / 0.020）。

**Q2：δ 估计得太大 / 太小会怎样？**

| δ 偏大 | δ 偏小 |
|---|---|
| 底线过低 → 轻微真退化被当噪声放行 | 底线过高 → 真进步被误杀（成绩动辄跌破底线） |
| 真进步门槛虚高 → 大量带内走塑形规则 | 假进步轻易兑换 token 预算 |
| 停滞判定过松 → 该探索时不探索 | 停滞判定过敏 → 频繁强制探索 |

δ 本质是**假阳性/假阴性的权衡旋钮**；样本不足时宁可多测几个 job
（`baseline --job base2` → `calibrate --jobs base,base2`）再定。

**Q3：为什么 bootstrap 要固定 `seed=7`、`reps=2000`？**
固定 seed 保证**同样数据 → 同样 δ**（可复现、可审计）；2000 次让标准误
估计本身稳定（再多点收益边际递减）。两者都可通过代码参数调整。

**Q4：只有 1 个任务 × 2 个 trial，δ 可信吗？**
统计上是薄弱的——4 种重抽组合的离散度信息有限。这正是源码优先采用
「多次独立评测直接观测」的原因，也是 FAQ Q2 里「多跑几个 job」建议的
由来。正式搜索（六算子 split）下建议至少 2~3 个 base job。

**Q5：δ 会在运行中途自动更新吗？**
不会。calibration.json 写定后，主循环每轮原样读取。若中途想改 δ
（比如换成论文固定值），直接改配置后用 **`readjudicate --t <t>`** 对已存
测量重新裁决——**零新评测**，因为每轮的 (S′, C′) 都已落盘，换一把尺子
重判即可（这正是该命令存在的意义，`loop.py:348`）。

**Q6：calibrate 和 baseline 的执行顺序能反吗？**
不能反、也不需要反。`baseline` 命令 = 评测 + 紧跟的单 job 校准，一次
拿到 (S₀, δ)；若想加强 δ，再手动 `baseline --job base2`（测第二个 job）
+ `calibrate --jobs base,base2`（两两作差的直接观测）。

**Q7：为什么「没有 δ 不允许开赛」（SystemExit）？**
同 baseline 的 missing 门禁一个逻辑：开赛前先确认尺子可用。没有 δ，
每轮的胜负判定、成本规则、停滞判定全部失效——带病跑 20 轮不如立刻停下。

---

## 附：本实例 calibrate 的实际数值预期

| 项 | 值 |
|---|---|
| 参与校准的数据 | `baseline` 自动附带：1 个 job（`base`）× 1 任务 × 2 trials |
| 估计方法 | `bootstrap over trials of one base evaluation`（单 job 路径） |
| bootstrap 参数 | reps=2000，seed=7，任务内带权重重抽 |
| z | 2.0（≈97.5% 单侧覆盖） |
| δ 量级 | 一至四个百分点（论文三实例：0.017/0.004/0.020；本实例以实际产出为准） |
| 加强建议 | 正式 run 前 `baseline --job base2` + `calibrate --jobs base,base2` 切到直接观测法 |
| 产物 | `runs/ascendc-devkit/calibration.json`（唯一新增文件） |
| 相对 baseline 的文件增量 | +`calibration.json`；driver 模式另加 `logs/calibrate.log`；**其余全不变**（不发车、不评测、不追加 history、不改 frontier） |

---

*本文档为《RRSI-AscendC-DevKit-整体运行流程.md》§7 的展开篇，依据
`rrsi/calibrate.py`、`rrsi/selection.py`、`rrsi/loop.py` 源码编写；行为以
仓库当前代码为准。*
