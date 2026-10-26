# cann-bench 1.0 与 2.0 怎么跑

- 日期：2026-10-26
- 评测仓：`/home/s00940212/experiment/cann-bench`（`HEAD=1791da6`，`git describe = v1.1.2-16`，`tasks/metadata/VERSION=2.0.0`）
- 本机硬件：`Ascend950DT_9582` → 基线逻辑名 `950dt`，NPU 卡 6
- 目的：给出 1.x / 2.x 两种口径的运行命令，并说明哪些组合在本机真的能跑

---

## 0. 结论速览

| 组合 | 能否跑 | 依据 |
|---|---|---|
| cann-bench 2.0（当前 checkout） | ✅ 已实测 | 本次 `swi_glu` 20/20、总分 30，报告落在 `runs/ascendc-devkit/jobs/base/batches/20261024-050434-t000-1525700/...` |
| v1.1.2 tag（三项计分） | 🟡 静态核对通过，未实跑 | 有 `tasks/metadata/950dt.json`，`baseline_resolver` 有 `Ascend950DT → 950dt` 别名；DevKit 需要的 CLI 参数齐全 |
| v1.0.0 tag（三项计分） | ⚠️ 能启动，性能分不可信 | `tasks/metadata/` 只有 `910b2.json` / `950pr.json`，无 950dt；`BaselineStore` 会 fallback 到 910b2 的锚点 |
| 2.0 + `CANN_BENCH_SCORE_WEIGHTS=1` | ✅ 只是换权重档 | 环境变量优先级高于 `tasks/VERSION`；profile `"1"` 的 `wb=0` |

> 一句话：**要复现"1.0 的分数构成"，用 `v1.1.2` tag 或 `CANN_BENCH_SCORE_WEIGHTS=1`；不要用 `v1.0.0` tag 跑性能。**

---

## 1. 先分清三个"1.0"

| 说法 | 实际含义 | 与 2.0 的差别 |
|---|---|---|
| **真 v1.0.0 tag** | 2026 年早些时候的整仓快照 | 题集是 Season1（53 题后归档）；`tasks/metadata` 只有 910b2/950pr；无 950dt、无 `score_weights.py`、无 `OPERATOR_SCORE_CAP` |
| **v1.1.2 tag** | 1.x 线最后一个 tag | 三项计分、无 bonus；**有 950dt 锚点**；题集与 2.0 仍不同 |
| **profile `"1"`** | 2.0 代码里的一套权重 | 权重 0.2/0.3/0.5/0.0，bonus 恒 0；但题集仍是 Season2、HAP/反作弊/封顶都是 2.0 的 |

三者只有"分数怎么加"这一层是等价的，看到的分数不具可比性。

### 1.1 分数构成对照

```
v1.0.0 / v1.1.2:
    total = compilation + function + performance        # 无 bonus，无封顶
                wc=0.20     wf=0.30      wp=0.50

2.0 profile "1":
    total = compilation + function + bonus(0) + performance
                wc=0.20     wf=0.30              wp=0.50

2.0 profile "2"（当前生产档）:
    total = compilation + function + bonus + performance
                wc=0.05     wf=0.20            wp=0.70   wb=0.05
    单算子封顶 OPERATOR_SCORE_CAP = 120
```

两个值得记住的差异：

- **1.x 没有 120 封顶**。`v1.0.0` / `v1.1.2` 里搜不到 `OPERATOR_SCORE_CAP`，注释明确写"`T_cand<T_HW` 时可 >100（不截断）"。所以 1.x 的单算子分理论上可以超过 120。
- **1.x 报告没有 `score_weight_profile` 字段**。`EvalReport` 只输出 `framework_version / tasks_version / overall_score / operators[] ...`，所以 RRSI 解析出来这一项是空串，属预期。

这两条正是 RRSI 侧不能把 120 硬编码成不变式的原因（详见 `domains/ascendc-devkit/bench/run_tasks.py` 的上限取值逻辑）。

---

## 2. 环境准备（三个版本相同）

```bash
source /mnt/paas/gyx/cann/install/cann-9.1.1/set_env.sh
# 可选：确认卡可用
npu-smi info | head
```

1.x 要求 CANN ≥ 9.1.0（`examples/aclnn_launch_example` 引用了 9.1.0+ 才有的 `aclnn_kernels/contiguous.h`），本机 9.1.1 满足。

---

## 3. 直接跑 cann-bench

### 3.1 2.0（当前 checkout）

```bash
cd /home/s00940212/experiment/cann-bench
./scripts/run_evaluation.sh --source-dir <算子工程目录> --device-id 0
```

常用参数：

| 参数 | 作用 |
|---|---|
| `--source-dir <dir>` | 提交格式的工程目录（`build.sh` + `cann_bench/`，见 `docs/spec/submission_spec.md` §2） |
| `--operator SwiGlu` | 只评一个算子 |
| `--device-id 0` | 单卡模式；不传则多卡并行 |
| `--no-perf` | 只做精度，不测性能 |
| `--task-dir tasks/level1/swi_glu` | 按任务目录定位 |

报告输出到 `reports/cann/<bench>_<stage>_eval_<时间戳>.{json,md,html}`。

### 3.2 1.x（推荐 v1.1.2）

monorepo 里同时保留多个版本用 worktree，不要切分支（会打断正在跑的实验）：

```bash
cd /home/s00940212/experiment/cann-bench
git worktree add ../cann-bench-1.1.2 v1.1.2

cd ../cann-bench-1.1.2
./scripts/run_evaluation.sh --source-dir <算子工程目录> --device-id 0
```

原始 1.0.0：

```bash
git worktree add ../cann-bench-1.0.0 v1.0.0
cd ../cann-bench-1.0.0
./scripts/run_evaluation.sh --source-dir <算子工程目录> --device-id 0
```

⚠️ v1.0.0 在本机的问题：`tasks/metadata/` 只有 `910b2.json` 和 `950pr.json`，`PLATFORM_ALIAS` 里也没有 `Ascend950DT`。`BaselineStore.load()` 找不到 `Ascend950DT_9582.json` 后的行为是：

1. 打印 WARNING，fallback 加载默认平台 `910b2.json`；
2. 主数据为空时直接把 fallback 当主数据；
3. 之后 `get_perf()` / `get_t_hw()` 都用 910B2 的锚点。

结果就是**编译分/功能分可信，性能分是按另一张卡的锚点算的**。要看 1.x 的性能，只能用 v1.1.2。

### 3.3 报告落在哪

每个 checkout 各自一个 `reports/`，互不覆盖：

```
cann-bench/reports/cann/...            # 2.0
cann-bench-1.1.2/reports/cann/...      # 1.1.2
```

记录口径的三个字段：

| 字段 | 2.0 | v1.1.2 / v1.0.0 |
|---|---|---|
| `tasks_version` | `2.0.0` | `1.1.2` / `1.0.0` |
| `score_weight_profile` | `"2"`（或 `"1"`） | 字段不存在 |
| `operators[0].score` | 四项之和、封顶 120 | 三项之和、不封顶 |

---

## 4. 用 RRSI 跑

RRSI 不直接调 `run_evaluation.sh`，而是走 `AscendC-DevKit` 的评测适配器，最终等价于：

```python
python -m kernel_eval.cli eval \
    --source-dir <部署好的工程目录> --operator <OpPascal> \
    --device-id 0 --skip-install --task-dir <tasks/levelN/op> \
    --eval-seed 0 --output <partial.json>
```

（`third_party/AscendC-DevKit/src/ascendc_devkit/adapters/evaluation/cannbench_scorer.py:137-155`）

所以只要目标 checkout 的 `kernel_eval.cli eval` 支持这 7 个参数，就能被 DevKit 驱动。v1.0.0 和 v1.1.2 都支持（`--skip-install`、`--eval-seed`、`--output` 在 v1.0.0 就有）。

### 4.1 2.0

```bash
cd /home/s00940212/experiment/rrsi-devkit
python rrsi.py --domain ascendc-devkit --T 1 --k 1 --m 1 --b-min 1 --b-max 1 --delta 0.02 run
```

### 4.2 1.x

改一个字段：

```jsonc
// domains/ascendc-devkit/rrsi.json
"bench": {
  "cann_bench": "/home/s00940212/experiment/cann-bench-1.1.2",
  ...
}
```

**必须先提交再启动**：trial 的候选 worktree 是从 commit 检出的，工作区改动带不进去。

```bash
git add domains/ascendc-devkit/rrsi.json
git commit -m "Point ascendc-devkit at cann-bench v1.1.2"
python rrsi.py --domain ascendc-devkit --T 1 --k 1 --m 1 --b-min 1 --b-max 1 --delta 0.02 run
```

`swi_glu` 在三个版本里都有（`tasks/level1/swi_glu`），任务 id 与 `data/ops_train.txt` 不用改。

### 4.3 verdict 解析不用担心

RRSI 的 `verdict_from_snapshot()` 现在以报告里的权威总分为准（`operators[0].score`，旧报告回退顶层 `overall_score`），所以：

- 2.0 四项之和 → 直接比对报告 `score`；
- 1.x 三项之和 → 同样比对报告 `score`；
- 1.x 没有 `score_weight_profile` → verdict 里该字段为空串；
- 1.x 没有 120 封顶 → 报告给多少就是多少，不会因为 120 被误判越界。

---

## 5. 只想换"1.0 的权重"，不换版本

```bash
cd /home/s00940212/experiment/cann-bench
CANN_BENCH_SCORE_WEIGHTS=1 ./scripts/run_evaluation.sh --source-dir <dir> --device-id 0
```

RRSI 侧也一样，`export` 之后再启动即可——`run_tasks.py` → DevKit → `kernel_eval` 每一层都是 `os.environ.copy()`（`cannbench_env.py:134`），环境变量能传到评测子进程。

报告会带 `score_weight_profile: "1"`，`bonus_score` 实际恒为 0。

**但它不等于真正的 1.0**：

| 维度 | profile `"1"` | 真 1.x tag |
|---|---|---|
| 权重 | 0.2/0.3/0.5/0.0 ✅ | 0.2/0.3/0.5 ✅ |
| bonus 项 | 存在但恒 0 | 不存在 |
| 题集 | Season2（60 题） | Season1 |
| HAP / 反作弊 | 2.0 实现 | 旧实现 |
| 单算子封顶 | 120 | 无 |

---

## 6. 已验证 / 未验证

**已验证（今天实跑或读代码确认）**

- 2.0 全链路：`run_tasks.py` → DevKit → `kernel_eval.cli eval` → 报告 → RRSI verdict，`swi_glu` 20/20、30 分；
- v1.0.0 / v1.1.2 都有 `scripts/run_evaluation.sh --source-dir`，且 `kernel_eval.cli eval` 支持 DevKit 传的全部参数；
- v1.1.2 有 `tasks/metadata/950dt.json` 与 `Ascend950DT → 950dt` 别名；
- v1.0.0 的 `tasks/metadata/` 无 950dt，且 `PLATFORM_ALIAS` 无 `Ascend950DT`，会 fallback 到 910b2；
- 1.x 无 `OPERATOR_SCORE_CAP`、无 `score_weights.py`、报告无 `score_weight_profile`；
- `CANN_BENCH_SCORE_WEIGHTS` 优先级高于 `tasks/VERSION`。

**未验证**

- v1.1.2 在本机的端到端实跑（编译、反作弊、profiler、报告解析）；
- DevKit 的 `eval_prepare`（按需构建 `cann_bench_utils`）在 1.x checkout 上是否同样成功——构建步骤来自 DevKit 的 `resources/repository-profiles/cann-bench.yaml`，与被评版本无关，但 1.x 的 `src/cann_bench_utils` 构建脚本未实测；
- 1.x 的 `OperatorReport` 在**真实产物**上的字段完整性（代码层面与 2.0 同构）。

---

## 7. 常见坑

1. **`--source-dir` 不是 DevKit 落盘的 `op_src` 裸目录**
   评测器要的是提交格式（`build.sh` + `cann_bench/`），`op_src/` 里是 `op_api/op_host/op_kernel/op_plugin` 的算子工程目录，直接传会卡在构建阶段。走 RRSI 时由 DevKit 生成并部署，手跑时得自己准备。

2. **不要在同一个 checkout 上切分支**
   canonical 仓可能正被 RRSI 的 worktree 引用；用 `git worktree add` 开副本。

3. **卡是独占的**
   `rrsi.json` 的 `npu_ids` 是硬编码 `[6]`；2.0 和 1.x 不要并发跑。

4. **1.x 分数不能和 2.0 直接比**
   题集、权重、封顶、反作弊规则都不同。要比只能比"同一份提交在两个口径下的相对变化"。

5. **v1.0.0 的 WARNING 容易被日志淹没**
   看到 `BaselineStore: hardware=... 的平台文件不存在` 就说明性能分不可信，别当成普通噪音。

---

## 8. 源码索引

| 内容 | 位置 |
|---|---|
| 权重档定义 | `src/kernel_eval/base/score_weights.py:41-44` |
| 权重档解析（env > VERSION） | `src/kernel_eval/base/score_weights.py:48-69` |
| Eq.4 四项求和与封顶 | `src/kernel_eval/report/scoring.py:478-492` |
| 单算子封顶常量 | `src/kernel_eval/base/perf_metric.py:61` |
| HAP 单用例封顶 | `src/kernel_eval/base/perf_metric.py:56` |
| 950dt 别名（v1.1.2） | `git show v1.1.2:src/kernel_eval/utils/baseline_resolver.py:78-82` |
| 锚点缺失 fallback | `git show v1.0.0:src/kernel_eval/utils/baseline_store.py:146-190` |
| 1.x 三项公式 | `git show v1.1.2:src/kernel_eval/report/scoring.py:435` |
| 评测入口脚本 | `scripts/run_evaluation.sh` |
| 提交输入规范 | `docs/spec/submission_spec.md` §2 |
| DevKit 的 CLI 调用 | `third_party/AscendC-DevKit/src/ascendc_devkit/adapters/evaluation/cannbench_scorer.py:137-155` |
| DevKit 评测子进程环境 | `third_party/AscendC-DevKit/src/ascendc_devkit/adapters/evaluation/cannbench_env.py:110-150` |
| DevKit 仓 profile | `third_party/AscendC-DevKit/resources/repository-profiles/cann-bench.yaml` |

相关文档：

- `docs/cann-bench-打分机制说明-20261026.md` —— 2.0 打分全链路
- `docs/RRSI-评分一致性检查-bonus漏项-20261026.md` —— RRSI 侧 1.x/2.x 兼容修复
