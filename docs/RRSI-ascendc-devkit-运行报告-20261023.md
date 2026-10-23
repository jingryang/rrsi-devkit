# RRSI × AscendC-DevKit 自进化运行报告

- 运行日期：2026-10-22 16:00 — 2026-10-23 15:20
- 实例：`domains/ascendc-devkit`
- 被进化对象：`third_party/AscendC-DevKit/src/ascendc_devkit`
- 评测基准：cann-bench `tasks/level1/exp`
- 规模：最小端到端（训练集 1 个算子，`k=1`，`m=1`，`T=1`，`b_t=1`）

---

## 0. 结论摘要

| 阶段 | 状态 | 结果 |
|---|---|---|
| 环境接线 | ✅ | cann-bench / Python / CANN / NPU 卡全部指向本机 |
| Baseline（H₀） | ✅ | **S = 0.5000**，missing 0/1 |
| Round 0 · Analyst | ✅ | 识别出 `performance_dimension_zero_credit` |
| Round 0 · Proposer | ⚠️ | 产出了候选补丁，但最后一次提案未正常收尾（网关空响应） |
| Round 0 · Critic | ✅（人工补跑） | `accept`，6 条理由、3 条风险提示 |
| Round 0 · Smoke / Evaluate | ❌ | 未执行（每个 trial 约 5–6 小时） |

**一句话**：整条 RRSI 链路（baseline → 证据渲染 → analyst → proposer → critic）已经在本机跑通，瓶颈不在 RRSI，而在于单次 AscendC 算子生成 trial 长达 5–6 小时，以及网关偶发空响应。

---

## 1. 环境接线

原始 `rrsi.json` 是另一台机器的配置，本次全部改成本机实际路径：

| 配置项 | 原值 | 实际值 |
|---|---|---|
| `bench.cann_bench` | `/home/cann-bench` | `/home/s00940212/experiments/cann-bench` |
| `bench.python` | `/usr/local/python3.12.13/bin/python` | `/home/ma-user/anaconda3/envs/PyTorch-2.10.0/bin/python`（3.11.10，含 torch 2.10 + torch_npu） |
| `bench.cann_env` | `cann-9.0.0/set_env.sh` | `/usr/local/Ascend/cann-9.1.0/set_env.sh` |
| `bench.npu_ids` | `[]`（自动探测） | `[3]`（卡 3 健康；自动探测解析不了新版 `npu-smi` 输出，会回落到 Critical 的卡 0） |
| `bench.trial_timeout_sec` | `7200` | `14400`（实际续跑时为 28800） |
| `proposer_model` | `claude-opus-4-8` | `claude-opus-5-5` |
| `analyst_model` / `critic_model` | `claude-opus-4-8` | `m:deepseek-v4.1-flash-1017` |

### 1.1 关键代码改动

| 文件 | 改动 | 原因 |
|---|---|---|
| `rrsi/llm.py` | 无 Vertex 配置时回退到 Anthropic 兼容网关（`RRSI_ANTHROPIC_BASE_URL` + `RRSI_ANTHROPIC_API_KEY`） | 本机没有 GCP 凭证；网关支持原生 `/v1/messages` |
| `domains/ascendc-devkit/adapter.py` | 实现 `load_trial` / `render_trace` / `task_row`；接入 `briefs.py` 的四个角色提示词 | 原 adapter 未实现证据接口，round 0 直接 `NotImplementedError` / `KeyError: 'analyst'` |
| `rrsi/propose.py` | `Workspace.dump()` 增加 `DUMP_BUDGET = 120_000` 字符预算 + 文件索引 | 原来把 3.2 MB harness 全量塞进 prompt，单轮 248 万字符，模型无法处理 |
| `third_party/.../opencode_backend.py` | 支持 `ASCENDC_OPENCODE_PROJECT_CONFIG` 指定机器本地 `opencode.json` | 候选以 git worktree 运行，仓库内 `opencode.json` 被 `.gitignore` 排除，worktree 里不存在 |
| `domains/ascendc-devkit/data/ops_train.txt` | 训练集临时裁成只有 `tasks/level1/exp` | 最小端到端；正式搜索需恢复 6 算子清单 |

已提交的 commit（`git log --oneline`）：

```
9e8f839 feat(experience-loop): 产物经验回流通路——出策环节审阅并入技能经验库
2d382ae feat(adapter): 接通 load_trial/briefs——修复 round 0 连续崩溃的两个缺口
ad06a4f feat(briefs): 技能树只读政策——废除 SELF-REPAIR/SEDIMENTATION 预期行为叙事
6cf4b30 Wire the ascendc-devkit instance to the local NPU box
```

> 机器本地配置 `runs/opencode.json`（含网关地址与 key）位于 gitignore 的 `runs/` 下，**未入库**。

---

## 2. Baseline（H₀）

### 2.1 时间线

| 时间 | 事件 |
|---|---|
| 16:28 | 启动 `rrsi.py baseline`（1 task × k=1） |
| 16:30 | DevKit 进入 `requirement` 阶段（opencode + deepseek 策略模型） |
| 18:07 | 进入 `codegen` |
| 20:30 | 触发 4h workflow 超时（codegen 尚未完成，exit 124） |
| 20:39 | 用 `run --resume <batch_id> --workflow-timeout 28800` 续跑同一个 trial |
| 21:30 | codegen 完成（build + deploy 成功） |
| 22:14 | precision_debug 完成 |
| 22:16 | `cannbench_eval` + `finalize` 完成，`eval=50.00` |
| 22:25 | 写入 verdict/meta，重新跑 `baseline` 建立 frontier |

续跑前主动杀掉 `run_tasks.py` 而非等待其超时清理，保住了 cann-bench worktree 与全部设计/编码产物。

### 2.2 结果

| 指标 | 值 |
|---|---|
| `overall_score` | **50.0 / 100** |
| `compile_score` | 20.0 / 20 |
| `function_score` | 30.0 / 30 |
| `performance_score` | **0.0 / 50** |
| `pass_rate` | 1.000（20 / 20 用例全过） |
| `status` | `ok`（分数自洽） |
| `no_submission` | 0 |
| RRSI `S` | **0.5** |
| RRSI `C` | `null`（当前 bench 未回传策略 token 数） |

生成的算子文件（13 个）：

```
CMakeLists.txt
op_api/{aclnn_exp.cpp, aclnn_exp.h, exp.cpp, exp.h}
op_host/{exp_def.cpp, exp_infershape.cpp, exp_tiling.cpp}
op_kernel/{exp.h, exp_kernel.cpp, exp_tiling_data.h, exp_tiling_key.h}
op_plugin/exp_plugin.cpp
```

> `delta` 无法从 k=1 的 baseline 标定（bootstrap 标准差为 0），本次用 `--delta 0.02` 手工给定。

---

## 3. Round 0

### 3.1 Analyst（deepseek-v4.1-flash）

产出 `runs/ascendc-devkit/r0/analysis_report.json`：

- **失败模式**：`performance_dimension_zero_credit`
  > 一次 trial 可以编译、部署并通过全部精度用例，却仍然丢掉整个效率分，最终停在约半分。决定性歧义是：效率维度的 0 可能来自「测了但低于目标」，也可能来自「根本没有测」。权重总分无法区分二者。
- **能力缺口**：`efficiency_credit_not_self_diagnosable`
- **成功习惯**：
  - `full_case_coverage_before_efficiency_work`
  - `end_to_end_delivery_to_scored_report`

### 3.2 Proposer（claude-opus-5-5）

**提案尝试记录**

| # | 模型 | prompt 预算 | 结果 |
|---|---|---|---|
| 1 | deepseek | 300k dump（实际 248 万字符/轮） | 40 轮只读不写，无编辑 |
| 2 | opus-5-5 | 300k dump | 中途终止（单轮最长 12 分钟） |
| 3 | opus-5-5 | 120k dump | **产出完整提案**（`A_proposal.json`，1 个声明编辑 C1） |
| 4 | opus-5-5 | 120k dump | 写出 2 文件 diff 后，网关连续 6 次空响应，未发出 `done` |

**候选机制**：把「perf=0」拆成两种可诊断的世界——从评测报告每个 case 的基线锚点判断效率维度是否真的被测量过，并把结论带到 `EvalResult` 与 scorer 日志。

**当前 worktree 中的 diff**（`runs/ascendc-devkit/wt/r0Apreview`）：

```
adapters/evaluation/cannbench_scorer.py | 113 ++++++++++++++++++++++++++--
domain/verification.py                  |  10 +++
2 files changed, 116 insertions(+), 7 deletions(-)
```

核心改动：

- `CannbenchScorer._classify_perf_measurement(cases)`：统计 `baseline_perf_us` / `baseline_us` 锚点数量，以及 `actual_perf_us` / `perf_us` / `latency_us` 的 actual/baseline 比值（min/median/max）。
- `perf=0` 时按 `measured` 分支输出不同的 `Logger.warn`：
  - 未测量 → 明确提示「不要从这里开始 tiling/pipeline 优化，先修复测量通路」；
  - 已测量 → 打印锚点数量与比值区间。
- `EvalResult` 新增 `perf_measurement: dict = field(default_factory=dict, compare=False)`。
- 整段分类逻辑 `try/except` 降级为 `not measured`，不影响评测热路径。

**验证**：在候选 worktree 中 `import ascendc_devkit` 成功；`_classify_perf_measurement([])` 返回 `{'measured': False, ...}`；带锚点的样例返回正确的 min/median/max 比值。

### 3.3 Critic（deepseek-v4.1-flash）

**verdict = accept**

理由摘要：

1. 纯描述性诊断，不修改分数、门禁或任何判定；
2. 无硬编码阈值、容差、参考值、算子名；
3. 增加了真实逻辑，没有删除任何安全机制；
4. 没有新增评测器访问通路；
5. 异常降级安全；
6. 无无界循环。

风险提示：

1. 额外的延迟字段与比值统计**必须保持诊断用途**，不能被注入成调优目标（否则等于泄露 grader 的 per-case 测量）；
2. 「repair the measurement path (baseline anchor) first」不能被理解为去修改评测侧的 baseline 配置；
3. 提案声明的编辑列表为空而 diff 覆盖两个文件——按「一个连贯机制」处理。

> 该 verdict 是对已保存 diff 人工补跑得到的（proposer 未收尾），记录在 `runs/ascendc-devkit/r0/A_critic.json`。

### 3.4 Smoke 策略

Smoke 是候选 harness 的存活检查，**不参与打分**。原策略是「训练集中第一个 incumbent 全部 trial 都拿到分的算子」，随数据集内容和顺序变化，可能挑到一个又贵又难的任务。

现在改为在 `rrsi.json` 里显式钉住：

```json
"smoke_n": 1,
"smoke_ids": ["exp"]
```

- 配置了 `smoke_ids` → 直接使用，与训练集无关，成本可预期；
- 未配置 → 回退到原策略（`smoke_n` 个「incumbent 全部 trial 有效」的训练任务）；
- 配置了但任务不在当前清单里 → 直接报错（fail fast），不会静默退回。

因此即使把训练集恢复成 6 个算子，round 0 的 smoke 仍然只跑 `exp` 一个 trial。

---

## 4. 未完成项与已知风险

| 项目 | 说明 |
|---|---|
| Smoke / Evaluate | 每条候选需要先完整跑一次 trial（存活检查），再跑一次评测；按本次观测约 5–6 小时/次，合计 10–12 小时 |
| Proposer 未收尾 | 最后一次提案在写完 diff 后遇到网关空响应（6 次重试均失败），`edits` 元数据缺失 |
| 策略 token 统计 | `C = null`，成本规则（ΔC）本轮退化为 0 |
| `delta` | k=1 无法标定，手工设 0.02 |
| 磁盘 | 宿主机 overlay 已用 97%（容器内仍可写），长时间评测前需确认空间 |
| 训练集 | 当前只有 1 个算子；正式搜索需恢复 `ops_train.txt` 的 6 个任务 |

---

## 5. 产物清单

| 路径 | 内容 |
|---|---|
| `runs/ascendc-devkit/frontier.json` | H₀：S=0.5，commit `6cf4b30` |
| `runs/ascendc-devkit/history.jsonl` | BASELINE 记录 |
| `runs/ascendc-devkit/jobs/base/exp/t0/` | `meta.json` + `verdict.json`（冻结打分器口径） |
| `runs/ascendc-devkit/jobs/base/batches/20261022-162821-t000-44888/` | DevKit 原始产物（`state_snapshot.json`、`report.md`、`run.log`、`events.jsonl`、算子源码 worktree） |
| `runs/ascendc-devkit/r0/analysis_report.json` | Analyst 产出 |
| `runs/ascendc-devkit/r0/A_proposal.json` | Proposer 产出（第 3 次尝试，完整 `done`） |
| `runs/ascendc-devkit/r0/A_diff.patch` | 候选 diff（第 4 次尝试） |
| `runs/ascendc-devkit/r0/A_critic.json` | Critic verdict |
| `runs/ascendc-devkit/wt/r0Apreview/` | 候选 worktree（保留以检查 diff） |
| `runs/finalize_base_trial.py` | 把续跑得到的 snapshot 转成 RRSI 的 meta/verdict |
| `runs/preview_r0.py` | 只跑 propose + critic、不触发 smoke/eval 的预览脚本 |

---

## 6. 复现命令

```bash
cd /home/s00940212/experiments/rrsi-devkit

export RRSI_ANTHROPIC_BASE_URL=http://<gateway>:8082
export RRSI_ANTHROPIC_API_KEY=<key>
export RRSI_SEARCH_MODEL=m:deepseek-v4.1-flash-1017
export ASCENDC_OPENCODE_PROJECT_CONFIG=$PWD/runs/opencode.json

# 1) baseline（H₀）
python3 rrsi.py --domain ascendc-devkit --k 1 --delta 0.02 baseline

# 2) 只要 analyst
python3 rrsi.py --domain ascendc-devkit --T 1 --k 1 --m 1 \
    --b-min 1 --b-max 1 --delta 0.02 round --t 0 --dry-run

# 3) 只跑 proposer + critic（不评测）
python3 runs/preview_r0.py

# 4) 完整 round 0（含 smoke + evaluate，约 10–12 小时）
python3 rrsi.py --domain ascendc-devkit --T 1 --k 1 --m 1 \
    --b-min 1 --b-max 1 --delta 0.02 round --t 0
```

---

## 7. 建议的下一步

1. **先跑完整 round 0**：确认 smoke → evaluate → adjudicate 三步能走完，再考虑恢复 6 算子训练集。
2. **给 proposer 加收尾保护**：在 prompt 预算接近上限时追加一次「必须调用 `done`」的强制提示（参考 `rrsi/digester.py` 里 `BUDGET_WARN_AT` 的做法），减少走到 turn cap / 空响应后白跑。
3. **网关空响应重试**：`llm.generate` 目前对空响应重试 6 次仍会失败退出；可以考虑区分「空响应」与「真实错误」，对空响应做更长退避或换模型重试。
4. **补 token 统计**：在 `run_tasks.py` 的 meta 里回传策略 token 数，恢复 RRSI 的成本规则（ΔC）。
5. **恢复训练集**：`domains/ascendc-devkit/data/ops_train.txt` 改回 6 个任务后再做正式搜索。