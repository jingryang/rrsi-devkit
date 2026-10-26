# RRSI × AscendC-DevKit 四次运行复盘

- 日期：2026-10-23 18:01 → 2026-10-26（报告撰写时实验仍停在 round 0 崩溃处）
- 仓库：`/home/s00940212/experiment/rrsi-devkit`
- Domain：`domains/ascendc-devkit`
- 评测仓：`/home/s00940212/experiment/cann-bench`
- 算子：`swi_glu`（`tasks/level1/swi_glu`）
- 协议：`--T 1 --k 1 --m 1 --b-min 1 --b-max 1 --delta 0.02 run`
- 运行目录：`runs/ascendc-devkit`；历史尝试归档在 `runs/archive/`

---

## 0. 结论速览

四次尝试里，**前三次都死在基础设施上，第四次算子在 DevKit 内部真正跑通了**（20/20 case、总分 30/100），但随后被 RRSI 的评分一致性检查二次归零（记成 0 分而不是 0.30），紧接着 round 0 的 digester 又被网关 404 打断。

按重要性排序：

1. **已确认的代码级阻塞**：`domains/ascendc-devkit/bench/run_tasks.py` 的 `verdict_from_snapshot()` 在核对总分时只加了 `compile + function + performance`，漏掉 cann-bench profile `"2"` 的 **全用例通过奖励 `bonus_score`**（`w_b=0.05`，20/20 全过时为 5 分）。于是 `overall=30` 与它算出的 `expected=25` 对不上，一个有效算子被判 `score_inconsistent`，最终 `S=0.0`。
2. **最大的外部不稳定源**：LLM 网关 `http://1.95.37.146:8082`。出现过的形态包括 300 秒响应头超时、连接被关、空响应、HTTP 404。它同时影响 opencode 策略链路（`/v1/chat/completions`）和 RRSI 的 analyst/critic/proposer 链路（`/v1/messages`）。
3. **算力/环境成本**：一次完整 trial（需求 → 设计 → codegen → build/deploy → 精度 → cannbench_eval）在这台机器上要 **5–7 小时**。任何一次死掉都要按小时计。

| # | 启动 | 结束 | 耗时 | 结局 | 直接死因 |
|---|---|---|---|---|---|
| 1 | 10-23 18:01:45 | 10-24 01:10:45 | 7h09m | baseline `harness_error`；round 0 候选 smoke_fail | `turn_stall` 180s 误杀 deepseek 长推理 |
| 2 | 10-24 01:15:05 | 10-24 01:15:05 | 秒败 | baseline 1/1 trials missing | NPU 3 卡上下文耗尽，open-device probe 全失败 |
| 3 | 10-24 01:20:50 | 10-24 ~04:40 | ~3h20m | baseline `harness_error`；round 0 proposer 崩溃 | 网关 13 次 300s 头超时 + 空响应 |
| 4 | 10-24 05:04:34 | 10-24 ~12:05 | ~7h | **算子 30/100 通过，但 RRSI 记 0**；round 0 digester 404 | 评分一致性检查漏算 `bonus_score`；网关 404 |

---

## 1. 实验目标与协议

目标是在 `ascendc-devkit` 这个 domain 上跑 RRSI 的自进化闭环：先测出基线 H₀，再由 analyst/digester 从 trace 中提炼失败模式，proposer 提出对 DevKit 自身（prompt / 控制流 / 配置 / 输出管道等）的修改，critic 审核，smoke 做活性门，最后 adjudicate 决定是否进入 frontier。

为了把成本压到可接受范围，当前只用**一个算子**：

- `domains/ascendc-devkit/data/ops_train.txt` → `tasks/level1/swi_glu`
- `rrsi.json` → `smoke_ids: ["swi_glu"]`（活性门与进化任务同一个算子）
- `max_attempts: 1`（失败不自动重试，避免成本 ×3）
- `trial_timeout_sec: 43200`（12 小时硬上限）

评分口径来自 cann-bench 的 `score_weight_profile: "2"`（`src/kernel_eval/base/score_weights.py`：`wc=0.05, wf=0.20, wp=0.70, wb=0.05`）。`src/kernel_eval/report/scoring.py` 里 `aggregate_eq4()` 的定义是：

```
total_score = compilation_score + function_score + bonus_score + performance_score
```

其中 `bonus_score = wb × δ_all × 100`，`δ_all=1` 当且仅当全部用例精度通过（20/20 全过时贡献 5 分）。所以这次的结果是：

```
30 = compilation(5) + function(20) + bonus(5) + performance(0)
```

注意：报告里的 `compile_runtime_score` **不是第四个独立分项**，它在 `OperatorScoreInfo.to_dict()` / `OperatorReport.from_eval_operator_result()` 里就是 `compilation_score` 的别名（`'compile_runtime_score': self.compilation_score`），打印出来当然也是 5.0。它表示"编译/运行通过率"这一轴，和 `compilation_score` 是同一个数。

满分 100，RRSI 侧再除以 100 得到 `S ∈ [0,1]`。也就是说，一个功能全对、没有性能加成的算子，`overall=30`，对应的正确 `S` 应为 **0.30**。

---

## 2. 环境接线：三个提交

这台机器（Ascend950，容器内可见 NPU）与仓库里原有的配置并不匹配。原始 `rrsi.json` 指向的是另一台机器的路径（`experiments/` 复数、`/home/ma-user/...`、CANN 9.1.0）。拉起实验前先做了三件事，并分别提交：

### 2.1 `0ccddac` — 把 ascendc-devkit 接上本机，并把进化任务收窄为 swi_glu

- `bench.cann_bench` → `/home/s00940212/experiment/cann-bench`
- `bench.python` → `/home/s00940212/venvs/rrsi-agentic/bin/python`
- `bench.cann_env` → `/mnt/paas/gyx/cann/install/cann-9.1.1/set_env.sh`
- `bench.chip` → `A5`
- `ops_train.txt` 从 `tasks/level1/exp` 改为 `tasks/level1/swi_glu`
- `smoke_ids` 固定为 `swi_glu`
- `opencode.json`（未跟踪，含 API key）里的模型改成网关实际提供的 `m:deepseek-v4.1-flash-1017`；别名 `m:deepseek-v4.1-flash` 会被网关判 `channel_unavailable`

同时修了一个隐蔽的坑：`domains/ascendc-devkit/bench/config.py` 原先用 `_path()`（内部 `.resolve()`）解析解释器路径，会把 venv 的 `bin/python` 软链解析到 `/opt/uv/python/cpython-3.13.14-.../python3.13`，从而丢掉 venv 的 site-packages（没有 torch / torch_npu）。改为 `_executable_path()` 只用 `.absolute()`，保留软链。

验证方式：`bench.config.validate_environment()` 返回 `[]`。

### 2.2 `fb091e5` — 深度推理的 codegen turn 放宽到 600s 再触发看门狗

DevKit 的 `opencode_turn_stall_s` 默认 180s。deepseek 的深推理 turn 经常在 185–202s 之间才出下一个 turn，于是被看门狗当成死链杀掉（详见 §3.1）。提高到 **600s**。

### 2.3 `e9fd190` — 把 ascendc-devkit 的卡池换到 NPU 6

NPU 3 卡的 context pool 被宿主机上的遗留进程占满（容器内 `npu-smi` 看不到那个 PID），open-device probe 全部失败。逐卡探测后确认 6 卡可用，`npu_ids` 从 `[3]` 改为 `[6]`。

> 注意：evolve worktree 是从 **commit** 检出的，所以上述配置改动必须先提交再启动，否则候选树里看到的还是旧路径。

---

## 3. 四次运行逐次复盘

### 3.1 第一次：turn-stall 把 codegen 打死

**时间线**

| 时刻 | 事件 |
|---|---|
| 18:01:45 | baseline 启动，job `base` |
| 18:08:19 | requirement-analyst 在 turn 12 被 stall 杀掉（188s > 180s）；stage 重试后恢复 |
| 18:51–19:43 | detailed-design（tiling 1363s/1582s、synthesize 377s、docgen 1004s）、ascendc-st-design 1473s |
| 19:43:04 | codegen 开始 |
| 20:57:29 | codegen 在 turn 72 被 stall 杀掉（202s）；stage 重试 |
| 23:37:12 | 重试后再次 stall（185s） |
| 23:41:09 / 23:45:40 / 23:51:31 | 连续三次 stall（189s），5 次迭代耗尽 |
| 23:51:31 | `codegen` 以 `fail_strategy=halt` 终止；codegen 阶段耗时 14907.6s，产物不完整 |
| 23:51:32 | baseline 判 `harness_error`，`S=0.0`，`no_submission=1.0` |
| 23:51–00:55 | round 0 analyst：5 个 digest，64 分钟，`top modes: []` |
| 01:10:45 | 候选 A smoke_fail；`no admissible candidate; H_1 = H_0` |

**根因**：`opencode_turn_stall_s=180` 与 deepseek 的推理节奏不匹配。看门狗判定的是“没有新 turn”，不是“进程死了”。多次 abort 的日志里 `chars static` 恰好也是 180–190s，说明流确实停住了，但随后又能继续——这是被误杀，不是真死。应用日志里没有任何 `stream error` 佐证网关故障。

**一个值得记录的细节**：这一轮 analyst 仍然产出了一个质量不错的候选 A——把 `AgentBackend.spawn()` 抛出的异常在调用点兜住，合成 `error_type=infra` 的 `AgentResult`，从而进入 runner 已有的有界退避重试通道，而不是让异常直接逃逸把整个 stage 判成 `infra_error`。critic 给了 `accept`。候选针对的失败类（后端瞬时不可用）恰好就是后来第 3、4 次运行真正的死因，但当时没有有效 baseline，smoke 门无法区分好坏，候选只能落选。

**修复**：`fb091e5` 把 stall 上限提到 600s。第 3、4 次运行再没出现过 turn-stall abort。

---

### 3.2 第二次：NPU 3 卡上下文耗尽（秒败）

启动后立刻失败，日志只有：

```
NPU card 3 probe failed — dropped from batch card pool [3]
ConfigError: Invalid config 'batch': all resolved cards failed the open-device probe;
every card in the pool [3] is unavailable
(driver context-pool exhaustion? check zombie processes or restart the container)
```

宿主机上 `npu-smi info` 显示 3 卡有约 829 MB 占用，占用进程 PID 在容器内不可见，属于典型的孤儿 host 进程导致的 device context 泄漏。容器内无法清理，于是换卡。

逐卡做 open-device probe 后确认 6 卡正常（`Ascend950DT_9582` 可以打开），提交 `e9fd190` 把池子切到 6 卡。

这次没有产生有效产物，直接归档。

---

### 3.3 第三次：网关 300 秒头超时

**时间线**

| 时刻 | 事件 |
|---|---|
| 01:20:50 | baseline 启动 |
| 01:20–03:36 | requirement 正常；general-design 阶段开始后网关抖动 |
| — | opencode.log 中累计 **13 次** `ProviderHeaderTimeoutError: Provider response headers timed out after 300000ms`，另有 1 次 socket close |
| 03:36:07 | `ascendc-design-generator` abort：`app-log stream error x2 recurring (newest 666s into silence; chars static 670s > probe 30s)`；general-design 5 次迭代未产出 `general_design.json` |
| 03:36:07 | stage `general-design-generator` 以 `fail_strategy=halt` 终止；baseline `harness_error`，`S=0` |
| 03:36–04:38 | round 0 analyst 仍跑完（62 分钟），`top modes: ['zero_case_evaluation_artefact_at_deploy_boundary']` |
| ~04:40 | proposer 调用 anthropic 链路，6 次全部返回空响应：`RuntimeError: generate failed after 6 tries: empty response`；round 0 崩溃 |

**根因**：网关侧。这个失败模式不是“慢”，而是上游在 300s 内连响应头都没发出来，opencode 的流式会话因此静止；DevKit 的 `gateway_error_probe_s=30` 发现字符数 670s 没动，提前判定网关故障并 kill `opencode serve`。这一轮的 600s stall 修复是有效的——没有任何一条 abort 是 turn_stall。

**另一个观察**：analyst 在没有有效算子的情况下仍然硬造出了一个“失败模式”（zero-case evaluation artefact），说明当 baseline 无效时，分析环节会从噪声里提炼伪信号。这类信号进 proposer 只会浪费下一轮。

**处置**：归档；重新探测网关（`/v1/chat/completions` 4–11s 返回 200，`/v1/messages` 5s 返回 200）后重启。

---

### 3.4 第四次：算子跑通，却被评分逻辑归零

这是目前最接近成功的一次。

**DevKit 侧时间线**

| 时刻 | 阶段 | 耗时 |
|---|---|---|
| 05:04:58 | workflow 启动，requirement | — |
| 05:18:53 | general-design | ~13 min |
| 05:39–07:10 | detailed-design：tiling / synthesize 811.8s / docgen 1143.9s | ~1.5h |
| 07:10:48 | ascendc-st-design | 1081.0s |
| 07:10:48 → 09:52:40 | codegen | 9712.0s |
| 09:52:40 → 11:43:08 | precision_debug / baseline | 6628.0s |
| 11:43:08 → 11:43:43 | cannbench_adapt（注入 wrapper + build.sh + 安装） | 35s |
| 11:43:47 → 12:00:57 | cannbench_eval | ~17 min |
| 12:00:58 | workflow done | 24928.4s |

**评测结果（DevKit 自己的日志）**

```
CannbenchScorer: overall=30.00 compile=5.00 func=20.00 perf=0.00 pass_rate=100.00%
batch 20261023-210453-141036: 1/1 workflow-done, 1/1 eval-passed
  [OK  ] swi_glu  exec=t000-swi_glu  eval=30.00/1%
```

cann-bench 报告（`.../subprocess/cannbench_eval_swi_glu.partial.json/swiglu_eval_20261024_114433.json`）：

```
score_weight_profile: "2"
operators[0].operator: SwiGlu
operators[0].score: 30.0
operators[0].compilation_score: 5.0
operators[0].compile_runtime_score: 5.0
operators[0].function_score: 20.0
operators[0].performance_score: 0.0
operators[0].pass_rate: 1.0    (20/20 cases success)
```

报告没有单独输出 `bonus_score` 字段，但 `30 - (5+20+0) = 5` 就是 profile `"2"` 的全用例通过奖励；`compile_runtime_score` 与 `compilation_score` 同值，是别名而非独立分项（见 §5.1）。

**RRSI 侧冻结的 verdict**

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
  "wall_s": 24983.487,
  "checks": ["overall_score 30.0 != compile+function+performance 25.0"]
}
```

因为 `scores_consistent=false`，`score = 0.0`，baseline 的 H₀ 又被记成 0，frontier 里的 `S=0.0`。**一个 20/20 全过、DevKit 判 30 分的算子，在 RRSI 的世界里等于没交。**

紧接着 round 0 启动，digester 调 `/v1/messages` 连续 6 次拿到 HTTP 404：

```
RuntimeError: generate failed after 6 tries:
Error code: 404 - {'error': {'type': '<nil>', 'message': 'bad response status code 404 (request id: ...)'}}
```

round 0 在分析阶段就崩了，没有产出任何候选。

---

## 4. RRSI 流水线本身的表现

抛开基础设施，闭环的机械部分是通的：

- **analyst / digester**：单任务 5 个 digest 约 1 小时；按任务并行。
- **proposer**（`claude-opus-5-5`）：能产出结构化的 `edits`，且第 1 次的候选 A 是一个真正的机制级修改（不是改 prompt 措辞），critic 直接 `accept`。
- **critic**（deepseek）：会按 `targets_mode / trigger_condition / predicted_affected / retroactive_check / regression_risk` 审查。
- **smoke → adjudicate**：路径能走完；第 1 次正确地拒绝了 smoke 失败的候选并回退 `H_1 = H_0`。

问题在于**输入质量**：

1. baseline 没有有效 trial 时，analyst 的输出要么为空（第 1 次 `top modes: []`），要么是伪模式（第 3 次）。
2. smoke 门比的是候选 trial 与 baseline 的分数；baseline `S=0` 时候选只要不崩就能“赢”，但实际第 1 次连 smoke 自己都崩了，门退化成“能不能跑完”。
3. 所以**先把一次 baseline 记成有效分数，比任何算法调参都重要**。

另外两个可观测性问题：

- `rrsi.py run` 在某一轮崩溃后仍会打印 “all rounds settled”（for 循环正常结束），容易误判为成功。
- 第一次启动时用 `... | tee runs/driver.log`，拿到的退出码是 `tee` 的，不是 `rrsi.py` 的；后续改为 `exec ... > log 2>&1`。

---

## 5. 当前阻塞：评分一致性检查漏项

### 5.1 先澄清一个容易搞混的点

cann-bench 的单算子总分**不是** `compile + function + performance` 三项，而是四项：

```
total_score = compilation_score + function_score + bonus_score + performance_score
```

`bonus_score` 是 profile `"2"` 独有的“全用例精度通过”奖励（`w_b=0.05`，全部 case 通过时贡献 5 分）。这次 20/20 全过，所以：

```
30 = 5 (compilation) + 20 (function) + 5 (bonus) + 0 (performance)
```

而报告里的 `compile_runtime_score` 只是 `compilation_score` 的别名（`to_dict()` 里直接赋同一个值），不是第四个分项。它是"编译/运行通过率"这一轴的展示名，数值恒等于 `compilation_score`。

### 5.2 证据链

1. cann-bench 报告：`score=30.0`，分项 `compilation=5.0 / compile_runtime=5.0（=compilation 别名）/ function=20.0 / performance=0.0`；`pass_rate=1.0`，20/20。
2. DevKit 的 `eval_result` 只透传了 `overall_score / compile_score / function_score / performance_score / pass_rate / num_cases / num_passed / report_json`，既没有 `compile_runtime_score`，也没有 `bonus_score`。
3. `verdict_from_snapshot()` 用 `compile + function + performance` 反推总分，得到 25，与 30 差 5——差的正是 `bonus_score`。
4. `|30 − 25| > 1.0` → `consistent=False` → `score=0.0` → `score.py` 再看到 `scores_consistent=false`，同样返回 0。

### 5.3 根因位置

`domains/ascendc-devkit/bench/run_tasks.py:284-371`：

```python
overall = _fnum(eval_result, "overall_score")
compile_score = _fnum(eval_result, "compile_score")
function_score = _fnum(eval_result, "function_score")
performance_score = _fnum(eval_result, "performance_score")

expected = compile_score + function_score + performance_score   # ← 漏 bonus_score
...
if abs(overall - expected) > 1.0:
    consistent = False
    checks.append(f"overall_score {overall} != compile+function+performance {expected}")
score = max(0.0, min(1.0, overall / 100.0)) if consistent else 0.0
```

### 5.4 建议修复（不要在 RRSI 里重算权重）

**错误修法**：把 `compile_runtime_score` 加进求和。虽然在这个特定结果上 `5+5+20+0` 碰巧等于 30，但它是把 `compilation_score` 重复计了一次，只是数值上恰好等于 bonus：

- 19/20 通过时，cann-bench 总分 = `5 + 19 + 0 + 0 = 24`；重复计 compile 会得 `5+5+19 = 29`，**把合法结果误判成 inconsistent**；
- profile `"1"`（`wc=0.2, wb=0`）下，满分结果 = `20 + 30 + 0 = 50`；重复计 compile 会得 70，同样误判。

**推荐修法**：RRSI 不应该复制 cann-bench 的权重表和加分公式（这次 bug 的根源就是复制了一份不完整的公式）。`report_json` 里的 `operators[0].score` / 顶层 `overall_score` 就是 cann-bench 算好的权威总分，直接用它做交叉校验：

```python
def _load_report(eval_result: dict, base: Path) -> dict | None:
    raw = eval_result.get("report_json")
    report = _as_mapping(raw)
    if report is None and isinstance(raw, str) and raw:
        path = Path(raw)
        if not path.is_absolute():
            path = base / path
        report = read_json(path)
    return report

report = _load_report(eval_result, snapshot_path.parent)
ops = report.get("operators") if report else None
if isinstance(ops, list) and len(ops) == 1 and isinstance(ops[0], dict):
    report_total = _fnum(ops[0], "score")
    # 唯一的硬校验：DevKit 抄出来的 overall 必须等于报告自己算的算子分
    if abs(overall - report_total) > 1e-6:
        consistent = False
        checks.append(f"overall_score {overall} != report operator score {report_total}")
elif report is not None:
    consistent = False
    checks.append("report does not contain exactly one operator entry")

# 诊断项（不参与判罚）：bonus 只可能非负
implied_bonus = overall - (compile_score + function_score + performance_score)
# 例外是封顶：未截断总分越过 120 时报告记封顶值，分项和高于它属正常
if overall < OPERATOR_SCORE_CAP - _SCORE_EPS \
        and compile_score + function_score + performance_score > overall + _SCORE_EPS:
    consistent = False
    checks.append(f"compile+function+performance {compile_score + function_score + performance_score} "
                  f"exceeds overall_score {overall}")
```

要点：

- `overall` 与报告总分严格相等，这是有意义的防篡改校验（防止 DevKit 层抄错或聚合错）；
- 分项加和只检查“不超过总分”这一条，因为 `bonus >= 0` 是唯一能跨 profile 成立的不变式；
- 把 `implied_bonus` 写进 verdict 作为诊断字段（这次它会等于 5.0，一眼就能看出是哪一项）；
- 顺手把 `_report_entry_count()` 合并进 `_load_report()`，避免两条读报告的通路；
- 如果将来 cann-bench 再改公式（eq3_log、profile 3……），RRSI 侧不需要跟着改。

**已落地（2026-10-26）**：上述修法已写进 `run_tasks.py`，并补齐 1.x / 2.x 的边界行为——报告不可读时只保留 `分项和 <= 总分` 的不变式校验（不因缺报告判 0），显式有 `bonus_score` 时才做四项严格加法，`overall` 上限从 100 放宽到 cann-bench 的封顶 120。verdict 新增 `implied_bonus` 与 `score_weight_profile` 两个诊断字段。单测见 `tests/test_ascendc_verdict.py`（11 条，覆盖 profile 1 / profile 2 / 篡改 / 缺报告 / HAP >100 / 非有限分项）。

### 5.5 验证方式

**离线验证（几秒钟，推荐先做）**：patch 之后直接拿已存的 snapshot 重算：

```
runs/ascendc-devkit/jobs/base/batches/20261024-050434-t000-1525700/devkit/20261023-210453-141036/t000-swi_glu/state_snapshot.json
```

期望 `status` 从 `score_inconsistent` 变为 `ok`，`score` 从 0.0 变为 0.3，`checks` 为空。这一步不消耗 NPU，也不重新跑算子。

实测结果（2026-10-26）：

```json
{"status": "ok", "score": 0.3, "overall_score": 30.0, "pass_rate": 1.0,
 "implied_bonus": 5.0, "score_weight_profile": "2", "checks": []}
```

**完整重跑（约 7 小时）**：只有当你需要一个从头到脚干净的 baseline/frontier 时才必要。离线重算只能修正“同一份证据的算术”，不能证明新补丁在未来 trial 上的行为；但后者其实也只依赖报告字段，风险很低。

注意：baseline 的 verdict 是冻结产物；即使离线重算通过，现有 `frontier.json` 里仍是 `S=0.0`。要把它变成有效基线，需要重跑 baseline，或者写一个一次性的重算脚本并走 `adjudicate` 的路径（`readjudicate --t` 只覆盖 round，不覆盖 baseline，需先确认可行性）。

---

## 6. 其他待解决项

### 6.1 网关不稳定

出现过的四种形态：

| 形态 | 出现位置 | 后果 |
|---|---|---|
| 300s 响应头超时（13 次） | opencode 策略链路 | general-design 无产物，stage halt |
| socket close | opencode 策略链路 | 流中断，触发 gateway probe |
| 空响应（6 次） | RRSI proposer（`/v1/messages`） | round 崩溃 |
| HTTP 404（6 次） | RRSI digester（`/v1/messages`） | round 崩溃 |

`rrsi/llm.py` 目前是固定 6 次重试、无退避、无超时参数（`generate(..., max_retries=6)`）。可选加固：

- 重试之间加指数退避（现在是立即重试，遇到短暂的 404/空响应窗口时会连续打空）；
- 把 404 与空响应分开处理：404 更像路由/模型别名问题，空响应更像上游过载；
- 在启动 `run` 前做一次真实产出探测（不是 curl 探活），确认 `/v1/messages` 能返回非空内容。

### 6.2 启动前检查清单

每次重启前建议依次确认：

1. `bench.config.validate_environment()` 为空；
2. 目标 NPU 卡能 open-device（换卡后尤其要跑）；
3. opencode 策略链路能产出 `chars>0` 的 turn；
4. `/v1/messages` 能返回非空文本；
5. 配置改动已提交（worktree 从 commit 检出）。

### 6.3 观测入口

```bash
# 总状态
/home/s00940212/venvs/rrsi-agentic/bin/python rrsi.py --domain ascendc-devkit status

# 实时日志（rrsi 驱动层）
tail -f runs/ascendc-devkit/logs/driver.log

# 当前 frontier
cat runs/ascendc-devkit/frontier.json

# 单次 trial 的 DevKit 阶段日志
tail -f runs/ascendc-devkit/jobs/base/batches/<stamp>/driver.log
```

启动命令（后台、日志重定向、保住退出码）：

```bash
nohup /home/s00940212/venvs/rrsi-agentic/bin/python rrsi.py \
  --domain ascendc-devkit --T 1 --k 1 --m 1 --b-min 1 --b-max 1 --delta 0.02 \
  run > runs/ascendc-devkit/logs/driver.log 2>&1 &
```

---

## 7. 产物位置

| 内容 | 路径 |
|---|---|
| 当前 baseline verdict | `runs/ascendc-devkit/jobs/base/swi_glu/t0/verdict.json` |
| 当前 baseline state snapshot | `runs/ascendc-devkit/jobs/base/batches/20261024-050434-t000-1525700/devkit/20261023-210453-141036/t000-swi_glu/state_snapshot.json` |
| cann-bench 评测报告 | 上述目录下 `subprocess/cannbench_eval_swi_glu.partial.json/swiglu_eval_20261024_114433.json` |
| round 0 崩溃栈 | `runs/ascendc-devkit/logs/r0.log` |
| 第 1 次尝试归档 | `runs/archive/20261024-baseline-turnstall/` |
| 第 2 次尝试归档 | `runs/archive/20261024-card3-exhausted/` |
| 第 3 次尝试归档 | `runs/archive/20261024-gateway-timeout/` |
| 候选 A（第 1 次） | `runs/archive/20261024-baseline-turnstall/r0/A/{proposal,critic,smoke}.json` |

---

## 8. 下一步（按优先级）

1. **修 `verdict_from_snapshot()` 的漏项**，用已存 snapshot 离线验证 `S=0.30`。这是让实验“有意义”的前提。
2. **决定 baseline 怎么补**：重跑（~7h，干净）或一次性重算（分钟级，但需确认 `readjudicate` 能否覆盖 baseline）。
3. **给 `rrsi/llm.py` 加重试退避**，并把空响应/404 分型处理；启动前跑真实产出探测。
4. **重跑 round 0**：baseline 有效之后，analyst 才能拿到有意义的 trace；第 1 次那个“spawn 异常 → infra 重试”的候选也才有机会被 smoke 公平评估。
5. 若 round 0 仍因网关崩溃，至少现在 baseline 是有效的，可以用 `readjudicate`/重跑 round 0 继续，不必再付 baseline 的 7 小时。

---

## 附录 A：当前生效配置（`domains/ascendc-devkit/rrsi.json`）

```json
{
  "smoke_n": 1,
  "smoke_ids": ["swi_glu"],
  "regression_threshold": 0.1,
  "guards": {
    "max_missing_rate_rise": 0.1,
    "max_no_submission_rise": 0.2,
    "max_valid_rate_drop": 0.1,
    "max_pass_rate_drop": 0.1
  },
  "bench": {
    "harness": "../../third_party/AscendC-DevKit",
    "cann_bench": "/home/s00940212/experiment/cann-bench",
    "runs_dir": "../../runs",
    "data_dir": "data",
    "repo_profile": "cann-bench",
    "op_subdir": "examples/aclnn_launch_example/csrc/ops",
    "chip": "A5",
    "python": "/home/s00940212/venvs/rrsi-agentic/bin/python",
    "cann_env": "/mnt/paas/gyx/cann/install/cann-9.1.1/set_env.sh",
    "npu_ids": [6],
    "trial_timeout_sec": 43200,
    "hard_timeout_grace_sec": 600,
    "stage_timeout_sec": 0,
    "keep_worktrees": false,
    "max_attempts": 1
  },
  "proposer_model": "claude-opus-5-5",
  "analyst_model": "m:deepseek-v4.1-flash-1017",
  "critic_model": "m:deepseek-v4.1-flash-1017"
}
```

## 附录 B：关键错误原文

**第 1 次 — turn-stall**

```
Agent ascendc-dev-s4-coding [swi_glu/codegen] abort:
no new turn for 189s > stall bound 180s (chars static 190s)
Stage 'codegen' failed with fail_strategy=halt; stopping pipeline.
```

**第 2 次 — 设备耗尽**

```
NPU card 3 probe failed — dropped from batch card pool [3]
ConfigError: Invalid config 'batch': all resolved cards failed the open-device probe;
every card in the pool [3] is unavailable
(driver context-pool exhaustion? check zombie processes or restart the container)
```

**第 3 次 — 网关头超时**

```
ProviderHeaderTimeoutError: Provider response headers timed out after 300000ms
Agent ascendc-design-generator [swi_glu/general-design-generator] abort:
app-log stream error x2 recurring (newest 666s into silence; chars static 670s > probe 30s)
Stage 'general-design-generator' reached max iterations (5) without satisfying
output_contract; missing: ['general_design']
```

**第 3 次 — proposer 空响应**

```
RuntimeError: generate failed after 6 tries: empty response
```

**第 4 次 — 评分不一致**

```
overall_score 30.0 != compile+function+performance 25.0
→ status=score_inconsistent, scores_consistent=false, score=0.0
```

**第 4 次 — digester 404**

```
RuntimeError: generate failed after 6 tries:
Error code: 404 - {'error': {'type': '<nil>', 'message': 'bad response status code 404 (request id: ...)'}}
```
