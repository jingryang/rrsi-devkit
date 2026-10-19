# L3 方案分析 — cann-bench 评测任务级 scoping（冻结 2026-09-11）

## 约束（用户裁定）

- **不修改 cann-bench**（外部仓产权）；
- 不注入极值/特殊值用例（算子交付 workflow 产权，非评测 workflow 职责）；
- 只针对 cann-bench 目标任务自身的 20 用例；
- 名称仅差大小写的算子之间不得相互影响。

## 候选方案

### A. `--task-dir` 传任务目录（选定）

任务身份 = **rel_path（唯一）**，不是算子名。把 `--task-dir` 从评测集根改成任务目录
（`<tasks>/level3/<op>`），激活 kernel_eval 原生 filter_prefix 通路：

- cann-bench `resolve_task_dir`（`path_resolver.py:29`）把任务目录拆成
  `bench_root=评测集根 + filter_prefix=<level>/<op>`；
- bench_root 归位根目录 → `match_operators`/golden_loader/baseline 行为不变；
- `cli.py:441-445` 的 `rel_path.startswith(prefix + '/')` 把用例集**构造性限定**
  到目标任务——精确路径匹配，大小写重名无从相撞。

DevKit 侧改动单点（`_resolve_task_dir` 是 task-dir 解析唯一通路，§2.5），
零 cann-bench 改动。

### B. 报告解析后只取目标 operator 的分（否决）

执行污染已经发生：孪生任务的 4D 崩溃、NaN/极值用例在同一 eval 进程里先跑，
已实证会触发目标 kernel 的间歇性单元素错误（P2 复现记录）；且白付孪生任务
约 12 分钟执行时间。事后挑分数治标不治本。

### C. 改 cann-bench 的 operator 过滤为大小写敏感（否决）

违反"不动 cann-bench"约束；且名字匹配本身治标——同 lower 名、不同路径的任务
（当前案例恰好只差大小写，但完全同名跨 level 的任务同理）仍会撞。路径才是
任务的唯一身份。

### D. 生成侧改符号名避开碰撞（否决）

方向反了：碰撞在任务集侧，不在生成物侧；且无法枚举未来任务名（§1.12 通用性
判据——按名字避让 = 按已知实例打补丁）。

## 防御纵深（随 A 一并落地）

- **多 operator 守卫**：`_parse_report` 见 `len(operators) > 1` → EvalResult 0 分 +
  infra reason（列出全部 rel_path）。scope 万一失效（cann-bench 行为漂移），
  混合分是错数据，不得静默流入 converge（拒绝错误冒充）；
- **task_dir 进 eval INFO 日志**：可诊断性。

## 副作用审计（已核查，2026-09-11）

1. **分数量纲回归单任务**（上限 ~50）：下游全查——`batch_runner.py:287` 仅判
   `>0` + 展示；converge/best-commit 用 passed-count（`precision_debug_substages.py:620`）
   不用分数；`domain/evolution.py:33` `epoch_loss=100-overall_score` 有 100 假设但
   零消费者。历史批次本就是单任务量纲（50.01/68.52/80.49），本次回归正确语义。
2. **find_bench_root 退化路径**（找不到命名祖先 → filter_prefix=None → 退化旧行为）：
   被多 operator 守卫暴露为 infra 错误，不静默混合；实际 worktree 结构保证命中。
3. **守卫无误伤**：报告 operators 来自用例分组，单任务恒 1；scorer API 本就单 op。
4. **无反向误 glob**：level2 目录名带 `task_0258_` 前缀，`<op>/cases.yaml` glob
   天然只命中目标目录。
5. `--operator` 保留（compile-failure 合成路径消费；单任务内过滤无歧义）——既有
   CLI 契约的防御纵深，非新旧并存。

## 原则符合性（§1.2 四把尺子）

可维护=单点改动澄清既有不变式；可扩展=结构信号（rel_path）判据，任何未来重名
任务自动归位；可诊断=守卫 + 日志；架构合理=修复落在命令构造产权层（L6 adapter），
不在报告解析处打下游补丁（§1.14 构造性保证优先）。
