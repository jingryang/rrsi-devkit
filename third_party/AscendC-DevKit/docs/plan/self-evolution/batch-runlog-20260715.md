# 五算子批量 self_evolve + cann-bench 评测 — 运行日志（20260715_192115）

> 诚实记录本次批跑（2026-07-15 19:21:15 拉起）的执行情况、失败现象与根因。
> 运行时事实，非方案设计。本次按用户指令**仅观察、不处置**（未修复任何问题、未改动任何代码/算子任务文件），下文「候选方向」仅作记录、非本次落实的修复。

## 任务

- 脚本：`scripts/batch_self_evolve.sh`（注：本次运行时该脚本处于 git 工作树已改未提交状态，`git status` 显示 `M scripts/batch_self_evolve.sh`；所跑即工作树当前版本）
- 算子清单（脚本头部 `DEFAULT_OPS`，cann-bench 原生 snake_case，5 个）：
  - `advance_step_v2`
  - `scatter_pa_kv_cache`
  - `ai_infra_aggregate_hidden_grad`
  - `ai_infra_manifold_constrained_hyper_connection_post`
  - `multi_add_rms_norm_dynamic_quant`
- 要求：拉起并观察是否正常执行；不替脚本正常运行买单，只诚实记录问题。
- CANN：默认 source `/usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh`。
- 卡数/并发：探测 NPU=8，本批 5 算子 → 并发 5（卡号 0..4）。
- worktree 根：`cann-bench-batch/20260715_192115/`，基仓 `/home/x00584171/code/cann-bench`。

## 结果概要

- **批跑以 exit code 1 结束，5 个算子全部 FAIL**。
- 失败模式：`reason=no_proto`（在 worktree 内 `tasks/level*/<op>/proto.yaml` 无命中）。
- 失败发生在派发瞬间（进度流全部时间戳为 `19:21:27`，从 `WT-ADD` 到 5 个 `FAIL` 同一秒）。
- **没有任何 LLM 生成发生**：per-op 日志仅 274–563 字节，内容只有「worktree add + no_proto 报错」；
  无 run_id 落盘（`.runid.*` 全空）。即本次 heavy_llm 全流程未真正启动，**未产生 LLM token 成本**，
  仅在 `pip install -e` + worktree 建立上消耗约 1 分钟。
- 结果汇总（脚本输出）：

  | 状态 | 算子 | exit | run_id |
  |---|---|---|---|
  | FAIL | advance_step_v2 | 1 | - |
  | FAIL | scatter_pa_kv_cache | 1 | - |
  | FAIL | ai_infra_aggregate_hidden_grad | 1 | - |
  | FAIL | ai_infra_manifold_constrained_hyper_connection_post | 1 | - |
  | FAIL | multi_add_rms_norm_dynamic_quant | 1 | - |

## 问题 1（主因）：5 算子全部 `reason=no_proto` — 算子任务文件在 cann-bench 未提交（untracked）

- **现象**：5 个算子的 per-op 日志均报：
  ```
  Preparing worktree (detached HEAD bcafd2f)
  HEAD is now at bcafd2f fix: 修复同用例精度和性能阶段生成整数tensor不一致
  [FAIL] <op>: tasks/level*/<op>/proto.yaml 未找到（扫描所有层级无命中；确认算子名用 snake_case）
  ```
  进度流：`WT-ADD <op> npu=N` 之后立刻 `FAIL <op> reason=no_proto`。

- **根因（已定位）**：**这 5 个算子的任务文件存在于 cann-bench 工作树，但从未 `git add`/提交，属 untracked**。
  因此：
  1. `git worktree add --detach "$wt"` 检出的是 HEAD 提交 `bcafd2f`，**untracked 文件不会被带入 worktree**。
  2. `resolve_task_level()` 在 worktree 内扫 `tasks/level*/<op>/proto.yaml`，0 命中 → 报 `no_proto` → exit 1。
  3. worktree 机制本身正常：检出成功、含 272 个已跟踪任务文件（如 level1 的 exp/gelu、level2 的 16 个 tracked 算子），
     只缺这 5 个 untracked 算子。

- **证据链**：
  - 基仓 `git status --short tasks/` 输出，5 个 untracked 项恰好就是本批 5 算子：
    ```
    ?? tasks/level2/advance_step_v2/
    ?? tasks/level2/ai_infra_aggregate_hidden_grad/
    ?? tasks/level2/ai_infra_manifold_constrained_hyper_connection_post/
    ?? tasks/level2/multi_add_rms_norm_dynamic_quant/
    ?? tasks/level2/scatter_pa_kv_cache/
    ```
    `tasks/` 下 untracked 总数 = 5（与本批算子数精确一致）。
  - `git ls-tree HEAD tasks/level2/` 列出的 HEAD 内 tracked level2 算子（apply_adam_w / cross_entropy_loss / rms_norm / … 共 16 个）**不含**这 5 个。
  - 基仓工作树 `tasks/level2/` 实际目录清单**含**这 5 个（即文件物理存在，但未被 git 跟踪）。
  - per-op worktree（如 `cann-bench-batch/20260715_192115/advance_step_v2/tasks/level2/`）有 16 个 tracked 算子目录，但**无** `advance_step_v2` 目录 —— 与 HEAD 一致，与 untracked 一致。
  - 这 5 个算子**确属 level2**（非 level1），但本现象与 `TASK_LEVEL=level1` 默认值无关：`resolve_task_level` 是跨层级扫描，level2 同样会命中——之所以 0 命中，纯粹因为 untracked 不进 worktree，而非层级错配。
  - `tasks/` 未被 `.gitignore` 忽略（`git check-ignore` 无命中），即普通 untracked，提交即可入 HEAD。

- **处置**：按用户指令**未处置**（未 `git add`/提交、未改算子清单、未改脚本）。

- **候选方向（仅记录，非本次落实）**：把 5 个算子目录 `git add -f`（如需，排除临时产物）后提交到 cann-bench，使 HEAD 含之 → worktree 自然带出 → `resolve_task_level` 命中 level2。需注意每个算子目录是否还含不应提交的中间产物（golden.py/proto.yaml/cases.csv 是脚本要求的必需产物，应提交）。

## 问题 2（潜在 / 未触发到运行期）：`set -u` + CANN `set_env.sh` 引用未设变量致警告，CANN 环境变量可能未正确落地

- **现象**：脚本启动即向 stderr 打印 3 行 `unbound variable`：
  ```
  /usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh: line 48: LD_LIBRARY_PATH: unbound variable
  /usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh: line 48: PYTHONPATH: unbound variable
  /usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh: line 31: CMAKE_PREFIX_PATH: unbound variable
  ```
  脚本未因此中止（`set -uo pipefail` 无 `-e`），继续走到 pip install 与派发。

- **根因（机制层面）**：脚本顶部 `set -uo pipefail`（`-u`=nounset）后 `source "$CANN_ENV_SCRIPT"`。
  set_env.sh 的若干行形如 `export LD_LIBRARY_PATH="...:$LD_LIBRARY_PATH"`；当这些变量在当前 shell 未设时，
  `$VAR` 引用在 `-u` 下即报 `unbound variable`，该 export 行**未完成赋值** → CANN 库路径**未 prepend 进 LD_LIBRARY_PATH 等变量**。

- **影响评估（未验证）**：本次 5 算子在 proto.yaml 校验阶段即失败，**未到达任何 CANN 编译 / NPU 运行代码**，
  故此问题**本次未造成运行期失败**，属潜在风险。但若问题 1 修复后算子进入 build/verify，**可能在 CANN 编译或
  运行期因 LD_LIBRARY_PATH 缺 CANN 路径而失败**（依赖库找不到等）。对照复现：以 `set -u` 并 `unset` 这三变量后
  source set_env.sh，source 后 `LD_LIBRARY_PATH` 内无任何 CANN 路径——佐证 CANN 路径未落地。
  （注：若用户 profile 已预设了这些变量则不会触发；本次触发说明启动 shell 中这三变量确为未设。）

- **处置**：未处置。仅记录为待确认的潜在问题。

- **候选方向（仅记录，非本次落实）**：在 `source "$CANN_ENV_SCRIPT"` 前 `set +u`、source 后 `set -u`；
  或先 `: "${LD_LIBRARY_PATH:=}"` 等给三变量默认空值再 source，避免 set_env.sh 在 `-u` 下引用未设变量。

## 本次覆盖范围诚实声明

- **未覆盖 heavy_llm**：本批 5 算子的真实 LLM 全流程（self_evolve_op 详设/codegen/deploy/eval）**一个都没真正跑**——
  全部在 proto.yaml 校验阶段即 FAIL，未进入任何 stage，无 run_id。故「heavy_llm 链路」本次零覆盖。
- 未修改任何代码或算子任务文件；5 个 worktree 保留于 `cann-bench-batch/20260715_192115/`（脚本默认 `KEEP_WORKTREES=1`）。
- 本日志为运行时事实记录（L1 性质：现象 + 根因 + 证据），不含已落实的修复；处置留待后续。

## 关键路径索引（便于复核）

- 总日志：`logs/batch_20260715_192115.log`
- 进度流：`logs/batch_progress_20260715_192115.log`
- per-op 日志：`logs/batch_<op>.log`（5 个，均 <600 字节）
- worktree 根：`cann-bench-batch/20260715_192115/`（含 `.status.*`=1、`.runid.*`=空、`.lock.*`）
- 基仓：`/home/x00584171/code/cann-bench`（分支 master，HEAD `bcafd2f`）

---

## 重跑（修复后，batch 20260715_194455）— 两处修复生效，进入正常 e2e

- **修复落地**：
  1. 问题2（本仓脚本）：`scripts/batch_self_evolve.sh` 的 source CANN set_env 处改为 `set +u; source "$CANN_ENV_SCRIPT"; set -u`。重跑首屏 `unbound variable` 警告 = **0**（已验证生效）。
  2. 问题1（外部仓数据）：cann-bench 仓 commit `4464566` 提交 5 个 level2 算子（30 文件 = 5×6），HEAD 已含；旧 batch worktree（20260715_192115）清理后重跑。
- **重跑结果**：5 算子全部 `RUN ... level=level2`（不再 no_proto），run_id 落盘（`20260715-114508-*`），进入 self_evolve_op 正常 e2e（entry→context→requirement→general-design…）。截至记录时 4 算子已过 requirement、advance_step_v2 因 429 在 requirement 重试。

## 重跑中观察到的疑似问题（防止丢失）

### 疑似 3：`context` stage 共性 WARN（output_contract 未满足但未 halt）

- **现象**：5 个算子**全部**报 `Stage 'context' reached max iterations (1) without satisfying output_contract: ['profile','adapter','op_identity','reference_code']`。
- **性质**：共性非个例；但流程未 halt，继续推进到 requirement（requirement 已正常 done）。
- **待确认**：context 是否实质缺失 profile/adapter/op_identity/reference_code 产物、是否影响下游 stage。**未深挖**，先记录防止丢失。

### 疑似 4：429 限流（advance_step_v2 命中，重试中）

- **现象**：advance_step_v2 的 requirement-analyst 首次 query 被拒 `Request rejected (429) · Weekly/Monthly Limit Exhausted`（reset 2026-07-18 16:57:13），自动进 iteration 2/10 重试；其余 4 算子 0 命中。
- **性质**：5 算子并发突发限流；参考上次六算子经验为软限流（iteration 内重试可过），待观察是否吃光重试预算。

### 疑似 5：批跑编排双通路 — `batch_self_evolve.sh` 自造并发/卡池 vs 工程 `--batch` 批跑能力（融合未完成，§2.5）

- **疑问来源**：`batch_self_evolve.sh` 是否按单算子方式拉起所有算子、由脚本自己处理 worktree/并发/卡池隔离，而非用工程本身的批跑能力？
- **确认（是）**：`run_one()` fork N 个独立 e2e 子进程，每个走 `ascendc-devkit run --workflow self_evolve_op --op-dir <单算子>`（`run` 的**单算子分支**，未传 `--batch`）。shell 层自己包办 worktree 建立 + flock 互斥 + FIFO 卡池 + 并发 wait + 状态汇总——**重新发明了工程已有的批跑编排**。
- **工程已有批跑能力**：`ascendc-devkit run --batch <manifest.yaml>` → `run_batch()`（`batch_runner.py`，L2）：同进程 `ThreadPoolExecutor` 并发 + 共享 `NPUSlotManager` 卡池 + manifest 每 task 带独立字段/`repo_root` + 汇总 exit code。这是 **P67 / `41-batch-fusion-analysis.md`（L3，2026-07-13 冻结）** 的产物——开篇即明「批跑能力当前由外部 `batch_self_evolve.sh` 承担……深层诉求是融合进 Python CLI，不与代码仓耦合」。
- **关键设计边界（为何 `--batch` 不做 worktree）**：`41-batch-fusion` §2.2(c) 明确——git worktree 创建 / task 目录解析 / 算子源码定位**都是 cann-bench 仓的布局知识，属该仓自身，不应进 Python**（§1.7/§1.5）。Python 侧只认 manifest 每项的 `op_dir`（绝对路径，已隔离目录）；worktree/task 解析是「清单准备阶段」的事，留仓侧（手写或仓侧脚本生成 manifest）。
- **理想形态 vs 现状**：
  - 理想（41-batch-fusion 意图）：**瘦仓侧脚本**只做 worktree 准备 + 生成 manifest → 调 `ascendc-devkit run --batch manifest.yaml`，并发/卡池交给工程。
  - 现状：`batch_self_evolve.sh` 是**融合前的遗留胖脚本**——worktree（合理，仓侧职责）+ 并发调度 + FIFO 卡池 + fork 单算子（后三者本该交给工程 `--batch`）全自己干。
- **子症状（原"NPU 双通路"）**：因本脚本多进程 fork，用不了进程内的 `NPUSlotManager`，退化为 shell FIFO 静态钉卡（`--npu-id` 全程独占），丧失动态复用——这只是批跑双通路的下游表现，根因在融合未收口。
- **判定**：**§2.5 双通路债务**。`41-batch-fusion` §2.2 自己写明「单算子是唯一退化通路，不并存两套」，现状恰恰并存了 shell 第三套。**非本次修复范围**——收口需把 `batch_self_evolve.sh` 瘦身为「worktree + manifest 生成器」并调 `--batch`，属架构决策。
- **处置决定（用户，2026-07-15）**：若当前脚本能达到既定目标（5 算子批跑生成+评测完成）则**先不动**架构；本问题（疑似 5）与疑似 3/4 **后续一并解决**。本次只诚实记录、不改造。

## 关键路径索引（重跑，20260715_194455）

- 总日志：`logs/batch_20260715_194455.log`
- 进度流：`logs/batch_progress_20260715_194455.log`
- per-op 日志：`logs/batch_<op>.log`（5 个，持续增长）
- worktree 根：`cann-bench-batch/20260715_194455/`
- run_id：`20260715-114508-{1956bf,563d1f,e1f3f6,075b61,d318a1}`（对应 5 算子）
- 基仓 HEAD：`4464566`（含 5 算子）

---

## 运行中演进（2026-07-15 22:28 起）— 续跑补救 + 新发现问题

> 5 算子进入正常 e2e 后，2 个在长阶段尾部撞 429 软失败 → halt（exit 65）；逐一续跑。
> 续跑过程中发现脚本 2 个 RESUME 相关 bug（疑似 6/7）。本节为运行时事实 + 已落地补救动作。

### 进展时间线（run.log / events.jsonl / 进度流）

| 时间 | 算子 | 事件 |
|---|---|---|
| 21:33:50 | manifold(075b61, 卡3) | integrate turn 51（528s）撞 429 → `[partial]` → `fail_strategy=halt`；workflow 6504s exit 65。**已产出 8 JSON 工件**（tiling_results 等） |
| 22:31:29 | multi_add(d318a1, 卡4) | docgen turn 68（1340s）撞 429 → `[partial]` → `fail_strategy=halt`；workflow 9964s exit 65。**已产出 docgen 工件**（含 980 行详细设计说明书.md） |
| 22:28:49 | manifold | **续跑启动（显式 WORKTREE_ROOT）**，4 运行中算子 flock-SKIP，manifold 走 RESUME 分支 |
| 23:03 | manifold | resume 越过原 halt 点 integrate → 进入 `[validate] ascendc-design-reviewer`（turn 30），续跑生效 |
| 23:06:00 | multi_add | **续跑启动（显式 WORKTREE_ROOT）**，重跑 docgen iteration 1/3 |
| 持续 | advance/scatter/aggregate | codegen/codegen/integrate 正常推进，未撞 429 |

### 疑似 6：RESUME 自动找最新 batch 目录用 `sort | tail -1` 误选旧目录（字典序 bug）

- **现象**：首次续跑用 `RESUME=1 bash batch_self_evolve.sh`（未显式指定 WORKTREE_ROOT），脚本自动找最新目录却落到 `cann-bench-batch/sixops_20260710_194016`（2026-07-10 的旧六算子目录），而非当前 `20260715_194455`。在该旧目录下 WT-ADD 5 个 worktree 后全 FAIL exit 1。
- **根因**：脚本 L117 `WORKTREE_ROOT="$(ls -d "$DEVKIT/../cann-bench-batch"/*/ 2>/dev/null | sort | tail -1)"`。`cann-bench-batch/` 下目录名前缀混用：`2026*`（数字 `2`，ASCII 0x32）与 `sixops_*`（字母 `s`，0x73）。字典序 `s` > `2`，故 `sort | tail -1` 恒取到 `sixops_*` 而非时间戳最新的 `2026*`。
- **证据**：误跑输出首屏 `worktree 根: .../cann-bench-batch/sixops_20260710_194016`；`git -C cann-bench worktree list` 显示 sixops 下被新建 5 个 4464566 worktree。
- **影响**：误选目录 → 在旧目录瞎建 worktree / 读不到当前批的 `.runid`/`.status` → 续跑失效 + 污染旧目录。
- **处置（已落地）**：①本次用显式 `WORKTREE_ROOT=.../20260715_194455 RESUME=1` 绕过（脚本 L115 `if [[ -z "${WORKTREE_ROOT:-}" ]]` 判空即跳过自动查找）；②清理 sixops 被误加的 5 个 worktree（保留原 `level1/{foreach_norm,swi_glu}`）。
- **候选方向（未落实，待用户定）**：把 L117 的 `sort | tail -1` 改为按目录 mtime 取最新（`ls -dt .../*/ | head -1`），或按时间戳目录名 `2026*` 数值排序。属脚本正确性修复（非架构），但按用户「先不动、后续一并解决」决策暂不改。

### 疑似 7：`RESUME=1` 经环境泄漏进子 e2e（从头跑分支未 `unset RESUME`）

- **现象**：sixops 误跑时，5 个算子的 per-op 日志出现 `[resume] run_id=1  权威日志 → output/1/run.log` 随后 `exit code: 1`。
- **根因**：续跑以 `RESUME=1 bash batch_self_evolve.sh` 启动，`RESUME=1` 作为前缀赋值**导出到环境**，被子进程继承。脚本的「从头跑」分支（L286 `bash "$E2E"`）**未显式 `unset RESUME` 也未覆盖**，故子 e2e 继承到 `RESUME=1`，把字面量 `"1"` 当作 run_id 去 resume → 读不存在的 `output/1` → exit 1。而 RESUME 分支（L256 `RESUME="$rid" bash "$E2E"`）显式覆盖为真实 run_id，正常。
- **触发条件**：`RESUME=1`（续跑模式）**且**某算子无 `.runid`（首次失败前未落 run_id，如 no_proto/worktree_add 失败）→ 走从头跑分支 → 泄漏触发。正常续跑场景（算子都有 `.runid`）不触发。
- **证据**：sixops 5 算子均无 `.runid`（旧目录）→ 全走从头跑分支 → 全 `[resume] run_id=1` → exit 1。
- **影响**：续跑模式下若有「无 run_id 的失败算子」，会被静默带去 resume 一个不存在的 run_id，而非真正从头跑。
- **处置（未落实）**：本次正确续跑（manifold/multi_add 均有 `.runid`）未触发；按用户决策暂不改脚本。
- **候选方向（未落实）**：从头跑分支前 `unset RESUME`（或 `env -u RESUME bash "$E2E"`），切断环境继承。

### 疑似 8：两个 429 软失败（manifold@integrate / multi_add@docgen）— 长阶段尾部突发限流

- **现象**：manifold 在 integrate turn 51、multi_add 在 docgen turn 68，均在「单 turn 耗时极长（528s / 1340s）」后撞 `Request rejected (429) · Weekly/Monthly Limit Exhausted`（reset 2026-07-18 16:57:13）→ 该 stage 标 `[partial]` → `fail_strategy=halt` → exit 65。
- **性质判据**：manifold 429（21:33）后，其余 3 个算子（advance/scatter/aggregate）**持续正常跑到 23:06+ 未被限** → 证明 429 是**突发 burst 拒绝**而非账号硬封；reset 日期是配额计数器滚动点，不代表请求全堵。故**可续跑重试通过**（iteration 预算 + 重试吸收抖动，§3.10）。
- **共性**：长阶段（integrate/docgen 动辄 50–68 turn、单 turn 数百秒）尾部是 429 高发点；5 算子并发突发加剧。与疑似 4（advance_step_v2 requirement 429）同源。
- **处置（已落地）**：两算子均已用显式 WORKTREE_ROOT 续跑（manifold bgi8od69z / multi_add bqmdfy041），resume 从 state_snapshot.json 恢复、卡由 state.npu_id 决定（manifold 卡3 / multi_add 卡4，均空闲不撞）。
- **风险**：advance/scatter/aggregate 仍在长阶段（codegen turn 219+ / codegen turn 89+ / integrate），有再撞 429 的可能，需持续盯；若再挂，同手法续跑。

### 补救动作汇总（本轮已落地）

1. 显式 `WORKTREE_ROOT=.../20260715_194455 RESUME=1` 续跑 manifold（bgi8od69z）—— 已越过原 halt 点，validate 推进中。
2. 同法续跑 multi_add（bqmdfy041）—— 重跑 docgen 中。
3. 清理 sixops_20260710_194016 被误加的 5 个 worktree（`git worktree remove --force`），保留原 `level1/{foreach_norm,swi_glu}`。
4. 疑似 6/7/8 如实记录于本节；脚本修复（L117 mtime 排序 / 从头跑分支 unset RESUME）按用户「先不动、后续一并解决」决策暂不落实。

---

## 第二轮失败（2026-07-15 23:37–23:54）— 全 5 算子 halt，含 1 个精度硬失败

> 续跑的 manifold/multi_add 再次 halt；3 个首次跑的算子也在此窗口集中 halt。**重查真实失败 stage 后发现 1 个非 429**。

### 时间线（进度流）

| 时间 | 算子 | 事件 |
|---|---|---|
| 23:37:12 | scatter(563d1f) | halt exit 65（codegen） |
| 23:37:14 | advance_step_v2(1956bf) | halt exit 65（**precision_debug**） |
| 23:41:30 | manifold(075b61) | **续跑后再次 halt** exit 65（codegen） |
| 23:47:23 | aggregate(e1f3f6) | halt exit 65（codegen） |
| 23:54:42 | multi_add(d318a1) | **续跑后再次 halt** exit 65（integrate） |

### 失败分类（按「真实失败 stage」= `Stage '...' failed with fail_strategy` 行，非末个 done stage）

| 算子 | 真实失败 stage | 末40行 429 密度 | 硬错误信号 | 判定 |
|---|---|---|---|---|
| advance_step_v2 | **precision_debug** | 1 | **33**（`.precision-fix/original_backup/` 备份产物） | ⛔ **精度硬失败，非 429** |
| scatter_pa_kv_cache | codegen | 7 | 0 | 429 饿死 → 续跑 |
| ai_infra_aggregate_hidden_grad | codegen | 6 | 0 | 429 饿死 → 续跑 |
| manifold | codegen | 4 | 0 | 429 饿死 → 续跑 |
| multi_add | integrate | 3 | 0 | 429 饿死 → 续跑 |

### 疑似 9（新）：advance_step_v2 精度硬失败 — 区别于 429 软失败

- **现象**：advance_step_v2 halt 在 `precision_debug`（非 codegen/设计阶段），产出 `.precision-fix/original_backup/{op_host,op_kernel,op_plugin}/...` 备份；末 40 行 429 密度仅 1（非 429 驱动）。
- **性质**：codegen 已通过、进入精度调试，**精度调试器耗尽 correction budget 仍未修好精度** → halt。是真实精度 bug，非服务端限流。halt 信息原文：「an implementation bug the coder could not fix automatically — review the latest verify output」。
- **判据**：失败 stage = `precision_debug`（非 codegen/integrate/设计）+ 有 precision-fix 备份产物 + 末尾 429 密度低 → 精度硬失败，区别于疑似 8 的 429 软失败。
- **处置**：**不盲目 resume**（debugger 已耗尽预算，resume 大概率重败 + 白烧 token；真修需动算子核心代码，用户已嘱不直接改）。用 `flock` 持 `.lock.advance_step_v2` 使 batch 自动 SKIP 该算子（hold），待用户定夺 resume / 人工精度调试。

### 补救动作（本轮）

1. **续跑 4 个 429 算子**（scatter / aggregate / manifold / multi_add）：显式 `WORKTREE_ROOT=.../20260715_194455 RESUME=1 bash scripts/batch_self_evolve.sh`（429 是服务端软限流，用户判定只能 resume，§3.10 有界重试吸收）。
2. **hold advance_step_v2**：后台 `flock` 持 `.lock.advance_step_v2`，batch run_one 的 `flock -n` 失败 → SKIP（不耗卡、不重复 resume），待用户决策。
3. 疑似 9 如实记录；精度硬失败不纳入自动续跑轮次（避免 cron 每 30 min 无意义重试烧 token）。

### 第三轮（2026-07-16 03:09）— scatter 也成精度硬失败（疑似 9 波及范围扩大）

- scatter_pa_kv_cache(563d1f) 03:09:27 halt exit 65：真实失败 stage=**precision_debug**、末 40 行 429 密度=**0**、硬错误信号 34（precision-fix 备份）。与 advance_step_v2 同款精度硬失败（codegen 已过、卡在精度调试），**非 429**。
- **疑似 9 波及范围**：advance_step_v2、scatter_pa_kv_cache 共 2 个。处置同 advance_step_v2 —— flock 持 `.lock.scatter_pa_kv_cache` hold（bmrfesd8z），batch/cron 自动 SKIP，不盲目 resume。
- aggregate / manifold / multi_add 仍在 codegen 往 precision_debug 推进，**有继续冒出精度硬失败的可能**（若生成算子精度问题系统性）。届时同样 hold + 记录，不 resume。
- **信号**：这是生成算子自身的精度质量问题（debugger 耗尽预算仍未修好），非 429 限流可解；集中爆发提示 self_evolve 输出在该批算子上精度收敛困难，需后续人工精度调试介入。

### 第四轮（2026-07-16 03:29–03:54）— manifold 成功 + precision_debug halt 判据细化

- 🎉 **manifold(075b61) 03:29:24 DONE exit=0**：第 1 个成功（finalize 完成）。续跑第 3 次终过 429 窗口跑通全链路。`.status=0`。
- aggregate(563d1f 的 e1f3f6) 03:44:28 halt @ precision_debug —— **经查实为 429 软失败，非精度硬失败**：错误是 `precision-debugger query attempt 1 failed: API Error: Request rejected`（调试器**首次 query 即被 429**），硬信号仅 7、debugger 几乎没跑。已续跑（非 hold）。

#### 疑似 8/9 判据细化：precision_debug halt 需二次区分（429 饿死 vs 真精度 bug）

`precision_debug` 阶段 halt 不能只看 stage 名就判硬失败，要区分 debugger 是否真跑过：

| 子类 | 特征 | 判定 | 处置 |
|---|---|---|---|
| 真精度硬失败 | debugger 真跑过多轮迭代、硬信号高（33–34）、有 `.precision-fix` 大量备份、耗尽 correction budget | 精度 bug | **hold**（resume 大概率重败） |
| 429 饿死 debugger | `query attempt 1 failed: API Error: Request rejected(429)`、硬信号低（≤7）、debugger 首query即挂 | 429 软失败 | **resume** |

- 波及：真精度硬失败 = advance_step_v2、scatter（hold）；429 饿死 = aggregate（续跑）。
- 此判据供后续巡检分类 precision_debug halt 用，避免把 429 饿死误当硬失败 hold（或反之）。

### 第五轮（2026-07-16 04:34）— aggregate 续跑后转为真精度硬失败（hold 第 3 个）

- aggregate(e1f3f6) 04:34:04 halt @ precision_debug：**这次 debugger 真跑了**（产出 `.precision-fix/report.json` 107 行 + `redeploy_workaround.py` + original_backup 备份），仍修不好精度 → `agent 未能修复` → halt。区别于其 03:44 那次（429 饿死、debugger query1 即挂）—— **续跑让 debugger 真正跑过后，暴露出是真精度 bug**。
- **真精度硬失败波及范围 = 3**：advance_step_v2、scatter_pa_kv_cache、ai_infra_aggregate_hidden_grad，均 flock hold（bidel2wi8 / bmrfesd8z / b9kiahozq）。
- 启示：429 饿死型 precision_debug halt 续跑后，若 debugger 真能跑起来仍修不好，即确认真精度 bug（疑似 8/9 判据表的两子类是同一算子在不同时点的两种表现）。
- 当前终态逼近：manifold DONE(1 成功) / multi_add 运行中 / 3 个精度 hold。multi_add 跑完后若也精度 hold，则全批终态（1 成 + 4 精度待人工），届时停巡检 cron。

### 第六轮（2026-07-16 05:49）— multi_add 终态：429 饿死耗尽 budget（非真精度 bug，已续跑）

- multi_add(d318a1) 05:49:43 halt exit 65 @ precision_debug。**经深度区分，判为 429 饿死变种，非真精度硬失败**，已续跑（非 hold）。
- **关键区分证据**（对照疑似 8/9 判据表「debugger 是否真跑过」）：
  - precision_debug 段 **run_tests / diagnose / fix / printf 四类 phase 标记全 = 0** → debugger **从未执行一个真实修复循环**（246 turn 全是重试空转，非 diagnose→fix→verify）。
  - **`.precision-fix/` 零产物**（无 report.json / 无 original_backup / 无 redeploy_workaround.py）→ 与已 hold 的 3 个（advance/scatter/aggregate 均有 artifacts 证明 debugger 真跑过且失败）形成对照。
  - 全 run.log 429=33、`query attempt 1 failed`=15；halt 末行 `incomplete_output: agent 未产出 debug_result.json` + `exhausted its correction budget`。
- **机制**：precision_debug 编排器在 429 burst 下反复重试/重派子 agent（子 agent 首 query 即被 429），246 turn 把 turn/budget **烧在重试上**，未完成任一真实 phase → budget 耗尽 halt。比 aggregate 03:44 那种「首 query 即挂、低信号快 halt」更磨人（磨满 budget 才挂），但**性质同为 429 饿死**（debugger 没真跑过修复逻辑）。
- **处置（已续跑）**：归 RESUME 类（用户「429→resume」前置授权 + 判据表 429 饿死→resume）。resume 重入 precision_debug 给 debugger 全新 budget；429 是 burst 级非账号硬封（reset 07-18 但请求不全堵，manifold 多次 resume 终过窗口 DONE 已证）。续跑命令：`WORKTREE_ROOT=.../20260715_194455 RESUME=1 bash scripts/batch_self_evolve.sh`（3 held flock SKIP + manifold .status=0 SKIP + multi_add RESUME）。
- **续跑后两种走向**：①debugger 真能跑起来修好精度 → 第 2 个成功；②debugger 真跑后仍修不好（产出 artifacts）→ 确认真精度 bug，转 hold（第 4 个），届时一并问用户。③若再被 429 磨尽 budget halt → 同手法再 resume（用户 standing instruction）。
- **当前全批终态**：manifold DONE(1 成功) / multi_add 续跑中(429 饿死类) / advance+scatter+aggregate 3 个精度 hold(待用户决策人工精度调试)。**巡检 cron 保留**——multi_add 续跑需持续盯其重入 precision_debug 后走向。

### 第七轮（2026-07-16 08:01）— ⚠️ 更正：multi_add 非 429 饿死，是 precision-debugger 编排器自转死循环（疑似 10）；全批终态

- multi_add(d318a1) 第六轮续跑(07:28)后，08:01:14 再次 halt exit 65 @ precision_debug：从 07:28 turn 1 空转到 turn 345，halt 原因与前次完全一致（`incomplete_output: agent 未产出 debug_result.json` + `correction budget exhausted`）。
- **⚠️ 诚实更正第六轮诊断**：第六轮把 multi_add 归为「429 饿死耗尽 budget」**是错的**。本轮续跑窗口（07:28–08:01，33min）**429=0**，却仍空转 345 turn → 证明空转**不是 429 驱动**。第六轮的判断（基于「全文 429=33 + halt 在 precision_debug」）把巧合的 429 当成了根因，实际根因见疑似 10。

#### 疑似 10（新）：precision-debugger 编排器自转死循环 —— 从不派发 phase 子 agent（非 429、非真精度 bug，resume 无效）

- **现象**：两次独立 resume（第一次空转 246 turn、第二次空转 345 turn），precision-debugger 编排器全程 `agent_stream [precision_debug] ascendc-precision-debugger turn N` 自转，**run_tests / diagnose / fix / printf 四类 phase 子 agent 派发计数全程 = 0**（grep `ascendc-precision-run-tests|ascendc-precision-diagnose|ascendc-precision-fix|ascendc-precision-printf` 全 0）。turn 行全文形如 `turn 345 (budget 10000/query, tool:Bash), 243140 chars, 1980s` —— 编排器在自己的 agent-loop 里转（Bash/thinking/text），context 膨胀到 243K chars 不收敛，**从不进入派发 phase 子 agent 的正路**，直至 correction budget 耗尽 → halt。
- **性质（三重排除）**：
  - ❌ 非 429（本轮窗口 429=0，仍空转）；
  - ❌ 非「debugger 真跑过失败的精度 bug」（零 phase 派发、零 `.precision-fix` 产物 —— 与 advance/scatter/aggregate 的真精度硬失败完全不同，那 3 个都有 artifacts 证明 debugger 真跑过修复循环）；
  - ✅ 是 **precision-debugger 编排器自身卡在 agent-loop 自转、无法/不会派发 phase 子 agent** —— 编排层/调试器配置问题，非算子核心代码问题。
- **resume 有效性（已铁证无效）**：两次 resume 产出**完全相同**的非生产性空转 + 相同 halt（246 turn / 345 turn，均 `incomplete_output` + budget 耗尽）。resume 给的全新 turn budget 只是被同样的自转重新烧光，不会触发 phase 派发。**故 multi_add 不再自动续跑**。
- **处置（已落地）**：flock-hold `.lock.multi_add_rms_norm_dynamic_quant`（与 advance/scatter/aggregate 同款，挡 cron/手动 auto-resume）。multi_add 成为第 4 个 hold 算子。**不盲目 resume**（resume 无效，且持续空转烧 token —— 243K context × 数百 turn 的真实 API 调用成本）。
- **候选方向（仅记录，待用户定，非本次落实）**：①查 precision-debugger 编排器为何不派发 phase（checkpoint/输入缺失？orchestrator prompt/工具配置问题？）——属 DevKit 调试器链路排查，非算子核心代码；②若确属 multi_add 触发的调试器边界 bug，单独定位；③退路：人工精度调试（需动算子核心代码，须用户 OK）。

#### 全批终态（2026-07-16 08:01）— 自动救援路径已尽，4 个精度算子待用户决策

| 算子 | run_id | .status | 性质 | 处置 |
|---|---|---|---|---|
| manifold | 075b61 | 0 | ✅ 全链路成功 | 终态 |
| advance_step_v2 | 1956bf | 65 | 真精度硬失败（debugger 真跑过、33 硬信号、有 artifacts） | flock hold |
| scatter_pa_kv_cache | 563d1f | 65 | 真精度硬失败（34 硬信号、有 artifacts） | flock hold |
| ai_infra_aggregate_hidden_grad | e1f3f6 | 65 | 真精度硬失败（report.json + redeploy_workaround） | flock hold |
| multi_add_rms_norm_dynamic_quant | d318a1 | 65 | **疑似 10**：debugger 编排器自转、零 phase 派发（非 429、非真精度 bug、resume 无效） | flock hold |

- **1 成功 + 4 precision_debug halt（3 真精度 + 1 编排器自转）**。
- **自动救援路径已尽**：4 个 halt 全是非 429（3 真精度 bug + 1 编排器自转），按巡检要点「verify/精度类硬失败（非429）：不改算子代码，先诚实记录再问用户」—— resume 对真精度 bug 大概率重败烧 token、对疑似 10 已铁证无效。**4 个全部 flock hold，待用户决策**。
- **本次覆盖范围诚实声明**：heavy_llm 全流程 5 算子中 1 个(manifold)端到端成功；4 个 halt 在 precision_debug（3 个 debugger 真跑过但精度未收敛、1 个 debugger 编排器自转未派发 phase）。halt 算子的 codegen/详设/deploy 阶段均已过、卡在精度收敛环节。未修改任何算子核心代码或 DevKit 调试器代码（仅编排层 flock/续跑救援）。
- **巡检 cron 已停**（fa548f3c）：5 算子全终态、自动救援路径已尽，cron 每 30min 重查静态状态无意义。用户就 4 个精度算子决策后可手动重启或指派新动作。

---

## 附录：深挖更正（2026-07-16，详见 L3 `50-non429-issues-analysis.md`）

> 本 runlog 疑似 3-10 各节为巡检期**当时快照**（L1 写定即冻结，保持不动）。事后对 precision_debug.py / debugger agent 定义 / skill / 三算子 `.precision-fix` artifacts 做实证深挖，**推翻多处巡检期判断**，更正统一记于此、详见 L3。

- **疑似 10「零 phase 派发」= 误判**：transcript 实证编排器**派发了 7 次**子 agent（4 printf + 3 fix）；巡检 grep 模式漏计 `tool:Agent` 行。真根因 = **Claude Code SDK async 派发 ↔ 编排器 prompt 同步语义失配**（dispatch 后空转等通知 + 漂移违规自做调试，context 爆 251K）+ **stale harness**（multi_add 的 `iter-1/harness.py` pre-fix 734557f，TensorList 嵌套 shape 致不可修 TypeError，状态机反复横跳不收敛）。
- **疑似 9 三算子「真精度硬失败」= 过度概括**：
  - advance_step_v2：`checkpoint.history=[]` 零精度数据，实为 **429 饿死**（398s 即挂）；"33 硬信号"是把 429 行误计。
  - scatter：实为 **DevKit `task_loader.py:180` per-input value_range bug**，debugger 正确拒绝 patch；零算子精度数据。
  - aggregate：确有真 kernel 缺陷 GAP-C（grad_weight noMask reduction），但叠加 GAP-A(schema 漏`=None`)/GAP-B(bf16 未注册)，且被 **600s BG-wait ceiling** 杀（非 budget/429）。
- **关键连带发现**：commit `734557f`（TensorList fix）在批跑进行中(05:47)才入 DevKit；multi_add + scatter 的"失败"本质是**用了 pre-fix 的 stale 测试框架产物，算子精度从未被真实验证** → redeploy 重生 harness 很可能直接通过，**无需人工精度调试**。
- **巡检判据「硬信号计数 + artifacts 有无」不可靠**：scatter 有 artifacts 却是 DevKit bug、advance 标硬信号却实为 429。正解判据 = 查 `checkpoint.json.history` 是否空 + 子 agent 派发 transcript + 真实 max_err。
- **处置优先级**（L3 §9）：P0 stale harness 重生验证 + 根因 A 编排修复（async/sync）；P1 600s ceiling；P3 GAP-C 真缺陷需人工精度调试（动算子代码，须用户 OK）。

---

## 收口：方案 E — 批跑分层 ID + 合一 resume + 脚本瘦身（2026-07-17，疑似 5/6/7 已解决）

> 疑似 5（批跑双通路 §2.5）+ 疑似 6（`sort|tail` 字典序误选）+ 疑似 7（`RESUME=1` 环境泄漏）+ run_id 从未对调用方暴露的预存缺口，由**方案 E** 一并根治。L4：`54-batch-id-hierarchy-resume-impl.md`。

### 方案（用户逐轮拍板，四把尺子筛掉 X'/W/D 中间方案）

- **分层 ID**：`execution_id` = 现有 `run_id` 语义；`batch_id` = 一次批跑唯一 ID（`new_run_id()` 同款 ts+uuid，单一源）。
- **目录**：单算子 `output/<exec>/`（flat，零变化）；批跑 `output/<batch_id>/<exec>/`（nested）。
- **文件系统即映射**：`ls output/<batch_id>/` = 批→算子，**不引入 batch.json 索引**（索引有与实际不一致风险，目录结构不会）。
- **合一 `--resume <id>`**：按**位置**判三态（flat-run / top-batch / nested-exec），batch_id/exec_id 同格式所以位置判而非字符串判，无歧义。
- **execution_id 由 batch_runner 预生成注入**（保证 dispatch 前 exec 目录即落位、零并发竞态）；单算子 run.py 不注入 → dispatch 自生成（"单算子与当前一致"）。
- **Workspace 零改**：nesting 由 batch_runner scope `output_root=<根>/<batch_id>` 表达。

### 落地（实现 + 验证）

- `infra/workspace.py`：抽 `new_run_id()` 单一源（run_id/exec_id/batch_id 共用）。
- `application/dispatcher.py`：新 run 分支 `Workspace.create(run_id=task_request.get("run_id"))` 兑现调用方注入（1 行；不传则自生成，单算子零变化）。
- `application/batch_runner.py`：`run_batch` 生成 batch_id + 每 task 注入 run_id/scoped output_root；新增 `resume_batch`（列 `output/<batch_id>/` 重建 resume manifest，复用单算子 resume）；`BatchResult.batch_id` + `RunOutcome.run_id` 填充。
- `application/resume_resolver.py`（新）：`resolve_resume_target` 三态位置判据。
- `cli/commands/run.py`：`--batch`/`--resume` 互斥；`--resume <id>` 走 resolver 分流（batch→resume_batch / single→dispatch）；`--batch` 打印 batch_id（续跑句柄）。
- `scripts/batch_self_evolve.sh`：瘦身 345→277 行，删 `run_one()`/FIFO 卡池/fork/wait/`.runid`/`.status`/`.lock`/`sort|tail`（疑似6）/RESUME 泄漏（疑似7）/run_id grep；改为生成 manifest + 调 `run --batch`（首）/`run --resume <batch_id>`（续，1 个 `.batch_id` 句柄）。

### 验证（全绿，零回归）

- 全量 UT：**2266 passed / 7 skipped**（新增 `test_resume_resolver` 6 + `test_batch_runner::TestBatchIdHierarchy` 6 + `test_run_batch::TestRunCmdResumeUnified` 4；改 `test_batch_e2e` 2 反映 nesting）。
- ST：`test_batch_self_evolve_script`（脚本首跑 manifest 生成 + batch_id 捕获 / 续跑 `run --resume` 路由，fake cann-bench + fake CLI）+ `test_batch_e2e`（真 dispatch + StubBackend，验证 dispatch→Workspace run_id 透传端到端、目录名=注入 exec_id）。
- **heavy_llm 待用户决策（§3.11）**：真实多算子批跑全流程（首跑 + 续跑）守护 batch_id 分层 + 合一 resume 端到端，交付前由用户在关键节点决策跑一次。

### 仍未解决（本批范围外，独立跟进）

- **疑似 10（precision-debugger 编排根治）**：用户已解决大部分，剩余由他人接手。
- **aggregate GAP-B（bf16 dtype）/GAP-C（reduction bug）**：验证依赖疑似 10 落地，暂不做。

---

## 收口：疑似 3（context WARN）—— resolve_op_dir 加载期校验治根（2026-07-17）

> 疑似 3 由 **resolve_op_dir 层 fail-fast（治根）+ 脚本 repo_profile（instance）** 修复。四把尺子过硬（前一版"context fail-fast"方案经审在「架构合理/可维护」有越层缺口，否决）。

### 根因（实证）

批跑 5/5 算子 `profile=None, repo_profile_name=''`。链路：worktree 检出在 `cann-bench-batch/<ts>/<op>/` → op_dir 路径段 `cann-bench-batch` 不在 `_identify_profile` 的 known 列表（`cann-bench/omni-ops/ops-nn/ops-transformer`）→ unmatched → `resolve_op_dir` 旧逻辑「有 `repo_root_override` 就豁免 profile」放行 `profile_name=''` → `ProfileLoader.load('')` 失败 → `profile=None` → context.transition `if profile and ...` 连带 `adapter/op_identity=None` → `has_all` False → WARN；并静默丢 `reference_roots`/`build_in_repo gate`（对 `generate_ascendc`/`dev` 会在 deploy `profile is None` 硬失败）。**非无害噪音**。

### 修法（落在职责正确的层，不越层兜底）

- **主修复（L2 `op_dir_resolver`，治根）**：去掉「`repo_root_override` 豁免 profile」的错误假设——`profile unmatched 且无 profile_override` → **raise `OpDirResolveError`**（不管 repo_root）。`repo_root` 只钉仓根**路径**，不替代 profile（下游 variant/scan/deploy-capability/reference_roots 需 profile 对象）。复用既有 `confidence` 判定，不自造判据；profile 解析失败在解析层即暴露（§1.3 加载期校验、§1.2 可诊断/架构合理、§3.4 不掩盖）。
- **instance（脚本）**：`batch_self_evolve.sh` manifest 加 `repo_profile: cann-bench`（`REPO_PROFILE` 可覆盖），让 worktree 经 `profile_override` 正确匹配、不触发新 raise，顺带恢复 reference_roots/build_in_repo gate。
- **宽容边界**：`reference_code` 等真可选契约仍 WARN-不-halt（new mode 无参考合法）；纯设计交付（无 op_dir）不调 resolve_op_dir，不受影响。

### 落地 + 验证

- `application/op_dir_resolver.py`：`if profile_name is None and not repo_root_override` → `if profile_name is None`，错误信息更新（repo-root 不替代 profile，须 --repo-profile）。
- `scripts/batch_self_evolve.sh`：`REPO_PROFILE`（默认 cann-bench）+ manifest top_defaults 加 `repo_profile`。
- UT 新增 2（`test_unmatched_with_repo_root_only_still_raises` / `test_unmatched_with_profile_override_resolves`）守护新边界；脚本 ST 断言 manifest 含 `repo_profile`。零回归（三调用方 batch/run/verify_repo 均 try/except OpDirResolveError，报错路径畅通）。
- **边界补全（同根因收尾）**：`op_dir_resolver` 的 `load_profile` 原 `except FileNotFoundError: pass` 静默吞——profile 名字已定（路径匹配或 override）但 yaml 未装时放行无 variant 的 `profile_name`，绕过上面的 `profile_name is None` raise → 下游 context 再 `load_profile` 又 FileNotFoundError → `profile=None` 静默退化（疑似3 同源）。改 `except → raise OpDirResolveError`，覆盖 **override 拼错 / 路径匹配名但 yaml 缺失**两种来源；profile 该加载就加载、加载失败即报，加载期校验无死角。UT +1（`test_unknown_profile_override_raises`）；全量 **2269 pass/7 skip**。
