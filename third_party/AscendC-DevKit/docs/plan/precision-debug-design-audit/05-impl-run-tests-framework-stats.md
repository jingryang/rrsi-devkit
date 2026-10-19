# L4 实施方案：run_tests 确定性信号框架接管（P2）——修订版

> 对应 L1 [01-problems.md](01-problems.md)（P2）+ L3 [02-analysis.md](02-analysis.md)（信任方向偏斜根因）。
> **修订记录（2026-08-22）**：首版方案"新建 `_derive_stats_from_result` + `_classify_failure_from_log`"在原则审查后发现 3 处违反（§1.4/§1.15/§2.5），且**未利用已有确定性基础设施**。本修订版改为"**框架直接消费自己已产的数据 + 复用已有确定性脚本**"——更小、更符合原则。
> 范围：仅 A3（A5 按用户指示保持原样）。
> **实施状态（2026-08-22）：✅ 完成**——见 §8 实施记录。

## 0. 目标

run_tests 让 agent 中转框架已确定性产出的信号（failed_case_queue / failure_type / total_count）。本方案把这些信号的**消费端从 agent 中转改为框架直接消费**，agent 只保留 LLM 独有的语义判断（observed_issues）。

## 1. 现状（深挖后的真相）

### 1.1 框架已有确定性基础设施（非 agent 申报）

| 信号 | 真实来源 | 确定性 |
|---|---|---|
| **failed_case_queue** | `build-failed-case-queue.py`（skill scripts/ 里，**stdlib-only**）从 result.json 确定性构建 | ✅ 框架脚本 |
| **run-level failure_type** | `runner.py:93` 落盘 result.json 时确定性写（`runtime_crash`/`timeout`） | ✅ 框架 runner |
| **total_count / failed_count** | 脚本 stdout 打印（`failed_count=... total_count=...`） | ✅ 框架脚本 |
| **per-case failure_type** | 脚本给初始猜测（`failure_type` 字段），agent 读日志**修正** | ⚠️ 脚本给了初始值，agent 修正 |
| **result_json 路径** | 脚本 stdout 打印（`result_json=<abs>`） | ✅ 框架脚本 |

### 1.2 当前 agent 的中转（冗余层）

SKILL.md 要求 agent：
- 跑 `build-failed-case-queue.py` → 读 stdout 的 failed_count/total_count → **折进 `_summary` 写 history**（脚本注释"run_tests agent to fold into its history entry"）
- 读日志**修正** per-case failure_type（第 72 行"脚本只给初始猜测，你必须读日志修正"）
- `_summary` 必须写 `failure_type`/`test_result`/`failed_count`/`total_count`/`max_err`

**问题**：框架已有全部统计（脚本 stdout + result.json），agent 只是**多一层中转**——折进 history 可能出错、可能覆盖脚本的确定性值。

### 1.3 框架的"唯一缺口"

**框架不直接跑 build-failed-case-queue.py**（脚本在 skill 目录，框架只在注释里引用）。这是 P2 要补的：**框架直接调用脚本**。

## 2. 设计：框架直接消费确定性信号（§2.5 唯一通路）

### 核心：框架在 run_tests transition 直接跑 build-failed-case-queue.py + 读 stdout

```
现状：agent 跑脚本 → 读 stdout → 折进 _summary → 框架读 _summary
目标：框架跑脚本 → 读 stdout → 写 history/best_* → agent 不中转统计
```

**这复用现有确定性脚本（§1.15），不新建框架逻辑，彻底删 agent 中转统计（§2.5 唯一通路）。**

### 改动 1：框架直接调用 build-failed-case-queue.py（复用，非新建）

`RunTestsSubstage.transition` 改为直接运行脚本（subprocess）：
```python
result = subprocess.run(
    [sys.executable, SCRIPT_PATH, "--result-json", result_json, "--control", control_path],
    capture_output=True, text=True)
# 解析 stdout: failed_count=... total_count=... result_json=...
# 写 history/best_*（替代 agent 折进 _summary）
```

**脚本位置**：现在在 `.claude/skills/ascendc-precision-run-tests/scripts/`。**缺口（新需求）**：框架要调用它，需：
- **方案 A（推荐）**：脚本上移为框架公共资源（`resources/` 或 `src/` 下），skill 与框架共用。但 §2.1 skill 即插即用要求 skill 自包含——**脚本不能移出 skill**（否则 skill 单独拿出缺脚本）。
- **方案 B（推荐，无 §2.1 冲突）**：**脚本保留在 skill 目录**（自闭环），框架通过 skill 路径调用（`_skill_dir()` 已有）。skill 与框架共用同一脚本，单一源（§1.15）。框架调用它不引入耦合（stdlib-only）。

**→ 采用方案 B**：脚本保留 skill 目录，框架经 `_skill_dir()` 定位调用。这是"现有基础设施满足"的正解。

### 改动 2：agent 不再中转统计（§2.5 唯一通路）

run_tests skill 契约**彻底改**（非降级）：
- **删**：`_summary` 的 `total_count`/`failed_count`/`failure_type`（框架从脚本 stdout 读）
- **保留**：`last_result_json`/`last_run_log`（路径，供跨 phase 回溯）、`observed_issues`（LLM 语义判断）
- **保留 agent 修正 per-case failure_type 吗**：⚠️ 评估——脚本给初始值，agent 修正是"读日志语义判断"。**这是 LLM 独有的（关键词在错误上下文可能是误导）**，但 §1.10 要求判据业务语义。**倾向保留 agent 修正**（这是 LLM 语义），但框架以脚本值为权威兜底（agent 不修就用脚本值）。

### 改动 3：history/best_* 框架物化（§1.15 收敛）

run_tests transition 从脚本 stdout 直接算 history 条目 + best_*（替代 agent 折进 _summary）——与 `_append_history` 现有机制衔接。

### 改动 4：crash_sentinel / 超时放大保留脚本处理

脚本已处理 crash_sentinel（写 control.json）+ 超时放大（sidecar）——框架调用它**原样复用**，不重复实现。

## 3. 现有基础设施满足性评估

| 需求 | 现有基础设施 | 满足？ |
|---|---|---|
| 构建 failed_case_queue | build-failed-case-queue.py | ✅ 满足（框架直接调用） |
| total/failed 统计 | 脚本 stdout | ✅ 满足 |
| result_json 路径 | 脚本 stdout | ✅ 满足 |
| run-level failure_type | runner.py result.json | ✅ 满足 |
| per-case failure_type 初始值 | 脚本 | ✅ 满足 |
| crash_sentinel 判定 | 脚本写 control.json | ✅ 满足 |
| 超时放大 | 脚本 + sidecar | ✅ 满足 |
| **框架定位脚本** | 脚本在 skill 目录，`_skill_dir()` 可得 | ✅ 满足（方案 B） |
| **agent 修正 per-case failure_type** | agent 读日志语义判断 | ✅ 保留（LLM 语义，§1.10） |

**结论：现有基础设施完全满足，无缺口。不需要"新需求做修改"——只需框架调用 + agent 契约收敛。**

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `precision_debug_substages.py` | `RunTestsSubstage.transition` 直接调 build-failed-case-queue.py + 读 stdout → 物化 history/best_* |
| `ascendc-precision-run-tests/SKILL.md` | `_summary` 契约：删 total_count/failed_count/failure_type；保留 last_result_json/observed_issues |
| `ascendc-precision-run-tests/references/prompts/run_tests.md` | 同步收敛 |
| 测试 | 新增：框架跑脚本读 stdout 物化 history（agent 不填 total 也对）|

## 5. 验证（TDD）

### 新增测试

1. **框架直接跑脚本**：构造 result.json + control.json → 框架调用 build-failed-case-queue.py → failed_case_queue 正确写入 + stdout 统计解析正确
2. **history 物化**：agent 不填 `_summary.total_count` → 框架从脚本 stdout 算 → history/best_* 正确
3. **§2.1 兼容**：skill 独立在 TUI 用（agent 手动跑脚本）仍跑通（脚本保留在 skill 目录）
4. **crash_sentinel**：crash_sentinel_mode 场景 → 框架跑脚本仍正确置位 → 路由 direct_comment_bisect

### 回归

- 314 precision_debug 测试全绿
- 1820 orchestration 全绿

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 框架 subprocess 调脚本失败 | 脚本 stdlib-only 无外部依赖；失败 → 诚实报错（§3.7） |
| agent 修正 per-case failure_type 与脚本值冲突 | 框架以脚本值兜底（agent 不修就用脚本值）；修正属 LLM 语义，保留但非权威 |
| §2.1 skill 即插即用 | 脚本保留 skill 目录（自闭环），框架经 `_skill_dir()` 调用，不引入外部耦合 |
| 脚本路径硬编码 | 经 `_skill_dir()` 解析（§1.5 资源路径不硬编码） |

## 7. 完成判据

- [x] 框架直接跑 build-failed-case-queue.py（复用，非新建）——`RunTestsSubstage._framework_case_stats`
- [x] history/best_* 框架物化（agent 不中转 total/failed/failure_type）——history 条目由框架从脚本 stdout + queue 算术 + per-case 聚合组合
- [x] skill `_summary` 契约收敛（删 total_count/failed_count/failure_type/max_err/test_result；仅剩可选 observed_issues）
- [x] agent 修正 per-case failure_type 保留（LLM 语义，脚本初始值兜底；run-level 由 `_aggregate_failure_type` 从 per-case 派生）
- [x] 新增测试绿（8 个 `TestRunTestsFrameworkStats` + 3 个语义改写）+ precision_debug 236 全绿 + orchestration 1832 全绿

## 8. 实施记录（2026-08-22）

### 8.1 落地形态（超出原计划的确定性收益）

| 信号 | 旧路（agent 申报） | 新路（框架派生） |
|---|---|---|
| total/failed counts | `_summary.total_count`（缺则 0 → passed=0 错） | 脚本 stdout 解析（`failed_count=(\d+) total_count=(\d+)`） |
| status=passed | agent 写 control.json | **框架派生**：`stats.failed_count==0 && total>0` → passed；agent 写 passed 但脚本有失败 → WARN + 回退 running |
| run-level failure_type | agent 申报 | `_aggregate_failure_type(queue)`：per-case 聚合（runtime > compilation > precision） |
| history 条目 | `_append_history(state, summary)` 原样提升 agent _summary | 框架组合（failure_type/test_result/failed/total/max_err/last_run_log） |
| max_err | agent 申报 | 框架从 queue real_errs 算（既有逻辑） |
| abort 判据 | `_summary` 为空 = abort | `_agent_produced_output`（phase 产物本身；`_summary` 缺失 = 正常轮） |

### 8.2 result.json 定位（两级解析，派生优先）

1. 派生约定：`<debug_artifacts_dir>/run_tests_iter-{run_iter_counter}/result.json`（`run_iter_counter` 在 transition 增位前读，即本 round 的 iter；放大重跑写同一 iter 目录 → 派生路径恒为最新产物）——**框架算术优先**（§P2 信任方向：派生 > 申报，agent 幻觉报 stale 路径被忽略，有回归测试钉住）
2. `phase_data.last_result_json`（agent 申报路径，磁盘存在才算）——agent 偏离 `--iter` 约定时的兜底

两者皆无（硬错误轮）→ `stats=None` → total=0 + history 标 `total unknown`（可观测降级，§3.7）；queue 由 agent 手动构建的语义不变。

### 8.3 脚本重跑的副作用（均有语义）

- **queue 幂等重建**：`merge_with_existing` 保留 agent 修正的 per-case failure_type / tried_fix_plan_ids / attempt_count；agent 漏跑脚本时框架兜底物化 queue
- **crash_sentinel_mode 置位/清除**：transition 重读 control 后镜像进 dc → `direct_comment_bisect` 路由
- **超时放大单调**：只在有 headroom 时向 cap 推进，重跑不回退

### 8.4 死代码清除（§2.5）

`resolved_pending → resolved` 升级块删除：脚本强制每轮运行后，all-pass 轮 queue 必为空（failed-only 结构 + merge 语义），升级循环永无输入——自脚本强制起即死代码，测试改为钉新语义（派生 passed + queue 清空 / 仍失败回 pending）。

### 8.5 实现顺序陷阱（B2 复现与防护）

`cp["status"] = derived` 若写在 `_append_history` 磁盘往返**之前**会被其内部 re-read 丢弃（B2 同款陷阱第三次出现）。防护：派生值先存局部变量 `derived_status`，`_append_history` 返回新鲜 cp 后再落；所有派生统计走局部变量（locals 天然免疫磁盘往返）。

### 8.6 契约同步

- 框架 prompt（`_phase_prompt`）：读写契约改为"只经脚本写 failed_case_queue；status/best_*/history 框架算"；`_summary` 段改为可选 observed_issues-only
- SKILL.md：职责清单 5/7、control.json/phase-json 契约表、硬错误 (c)、failure_type 分类（per-case only）
- references/prompts/run_tests.md：任务流 7 步、两个 heredoc（删 best_*/status 写入块与 _summary 统计块）、硬错误流程、`<op_name>:hard_error` 占位符违例修正

### 8.7 遗留（后续收敛记录）

- `cascade_suspected` / `crash_masking_probe_needed` 的发现**已于 2026-08-22 框架派生收敛**（第二段实施）：RunTestsSubstage.transition 在物化 observed_issues 处单点派生（`runtime 失败率 >80%` → cascade；`全量 runtime（passed=0）` → probe；均 `blocking: false`，按 category 与 agent 条目去重合并；分母无意义（stats 缺失/total=0）不派生）。agent 申报面删除（SKILL.md 申报条目改为"框架自动派生，你无需申报"，category 枚举同步收窄）；**消费端零改动**——diagnose 读 `control.json.observed_issues` 的契约不变，probe 的 `{rowsPerTile=1, bufferNum=1}` 行动引导留在 diagnose 侧。UT `TestFrameworkDerivedObservations` 4 测试钉住（cascade >80%、全量双派生、混合/少数失败不派生、agent 旧习惯申报去重）。
- `observed_issues[].blocking` 仍由 agent 判定（LLM 语义：读日志判断问题是否使有效 case 无法被消费；框架只消费该标志——§1.10 语义声明的消费侧已正确），**保留 agent**（非遗留缺陷）
