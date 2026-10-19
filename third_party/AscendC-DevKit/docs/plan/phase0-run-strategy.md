# Phase 0 运行方式推荐

> 本文回答「后续怎么跑这 35 个算子的基线」以及「如何新增/替换算子」。
> Phase 0 清单：`docs/plan/phase0-ops.json`（当前 35 个算子；数量以文件为准，本文不维护打勾快照）。
> **只读边界（硬约束）**：cann-bench 是**外部只读依赖**。本仓只**引用**其仓内权威脚本，**绝不修改/新增 cann-bench 的任何文件**。所有方案性内容（调度、loss 收集、baseline 策略）保存在**本仓** `docs/plan/` 与 `scripts/`。
> **文档纪律**：不写 `file:line` 行号、不维护代码/文件现状快照（与仓 CLAUDE.md「以代码为准」一致）；引用代码用语义锚点，具体位置实施时核实。

---

## 1. cann-bench 真实评测模型（权威来源：cann-bench 仓内脚本）

cann-bench 的评测由其**仓内权威脚本**驱动。本节是摘要，**以 cann-bench 仓内脚本为准**（只读核实）：

- **评测入口**：`scripts/run_evaluation.sh` → `python -m kernel_eval.cli eval`
- **评测对象**：AI 生成的算子源码目录（`--source-dir`）或仓内 task 目录（`--task-dir`）
- **多算子/多卡**：**进程级并行** —— `--processes-per-card <n>`（默认 2）+ `--device-id <id>`（单卡）或自动检测全部卡（多卡）。**无需复制整份仓**。
- **golden 基准**：`scripts/utils/build_golden_wheel.sh` 把 `tasks/` 下 `golden.py` 打成纯 Python `cann_bench` whl，注册到 `torch.ops.cann_bench`；评测前 `pip uninstall` 旧包避免重复注册冲突。
- **报告**：按 `bench_name` 分目录（`reports/` 或 `reports/<bench>/`），避免互相覆盖。
- **反作弊**：`scripts/anti_cheat/` 操作 `ASCEND_OPP_PATH` 下被评测算子的内置 kernel（禁用内置实现，逼被测算子真跑自己的实现）。

### 关键澄清：推翻早期草案的错误约束

早期草案（及已弃用的会话临时脚本 `batch_run_vector_ops.sh`）曾断言 cann-bench 是「整仓 cmake 构建 + 全局 opp 安装 + **每卡 cp -a 整份仓 + 每卡独立 opp/venv**」模型。**这是错的**：

- ❌ 那个 `batch_run_vector_ops.sh` 位于会话日志目录（`session_logs_all_related/workspace/`），**非 git-tracked、跨会话易失**，且其描述的 cp 模型与 cann-bench 仓内权威实现**不符**。已弃用，不再引用。
- ✅ 真实模型：多算子并行是 **kernel_eval CLI 的进程级调度**（`--processes-per-card` + `--device-id`），**不 cp 仓、不装多 opp、不建多 venv**。框架要对接的是这个 CLI 的参数与报告输出，**不是**自行 cp/隔离 repo。

> 结论：所谓「多算子互踩」在 cann-bench 真实模型里**由 kernel_eval CLI 的进程隔离 + reports 分目录已经解决**。框架层不需要、也不应该再造一套 cp/opp 隔离——那是把不存在的约束当真。

---

## 2. 推荐运行方式：对齐 kernel_eval CLI（不另造执行模型）

baseline 驱动应直接对齐 cann-bench 仓内权威入口，**只读调用**、不改 cann-bench：

1. **生成算子源码**：DevKit 的 `generate_ascendc` workflow 产出一个算子的源码目录（结构对齐 cann-bench 期望：`op_host/`、`op_kernel/` 等）。
2. **驱动评测**（对每个算子，只读调用 cann-bench 脚本）：
   - **方式 A（推荐，对齐真实模型）**：`run_evaluation.sh --source-dir <生成的源码目录> --device-id <slot> [--no-perf]`
   - **方式 B（对齐 task 目录）**：`run_evaluation.sh --task-dir tasks/level{N}/{op} --device-id <slot>`
3. **收集 loss**：评测产出 `reports/eval_report.json`（编译 / 精度 / 性能三维度）→ 提取为 baseline loss。
4. **NPU 分配**：`--device-id` 由 DevKit 的 `NPUSlotManager` 分配（slot 集成待落地，见 `l1-framework-contract.md` §7）。
5. **多算子并行**：复用 kernel_eval CLI 自身的 `--processes-per-card` 多进程能力；外层调度器按 slot 可用性分发算子到 device-id。**不 cp 仓、不装多 opp**。

> 所有调度 / loss 收集 / 报告聚合逻辑写在本仓（如后续 `scripts/phase0_baseline.py`）；cann-bench 仅作为只读被调对象。

### 为什么这样

| 需求 | 满足方式 |
|---|---|
| 便于分析 | `reports/eval_report.json`（结构化）→ 本仓聚合为 CSV |
| 新增/替换算子 | 改 `phase0-ops.json` 再跑，脚本不变 |
| 多算子并行 | 复用 kernel_eval CLI `--processes-per-card` + 外层 slot 调度 |
| 避免 cann-bench 互踩 | 进程级并行本就无 repo 互踩；reports 按 bench_name 分目录 |
| 只读边界 | 只调 cann-bench 脚本，不改其仓 |
| 一开始工程跑不通 | 可用 `--dry-run` 只检查 task_dir 文件完整性，不跑 pipeline |
| 换机器 | 改 `phase0-ops.json` 的 `repo_root` 一处或导出 `CANN_BENCH_ROOT`（见 `_path_convention`） |

---

## 3. 新增/替换算子的 SOP

1. 在 `$CANN_BENCH_ROOT/tasks/level{N}/{op}/`（**只读查看**）确认算子存在。
2. 编辑 `docs/plan/phase0-ops.json`，在 `ops` 数组新增/修改一项（**路径相对 `repo_root`，不内联绝对主机路径**）：
   ```json
   {
     "op_name": "new_op",
     "level": "level1",
     "task_dir": "tasks/level1/new_op",
     "desc_md": "tasks/level1/new_op/desc.md",
     "golden_py": "tasks/level1/new_op/golden.py",
     "proto_yaml": "tasks/level1/new_op/proto.yaml",
     "cases_csv": "tasks/level1/new_op/cases.csv",
     "selected": true,
     "note": "baseline task"
   }
   ```
3. 运行 baseline 脚本（后续在本仓 `scripts/` 实现）。

---

## 4. Phase 0 交付物清单

**状态以实际文件为准，不在此维护打勾快照**（清单数量、文件存在性会变，固化打勾会过期）：

- 算子清单：`docs/plan/phase0-ops.json`（当前 35 个 / selected 35；换机器改 `repo_root` 或设 `CANN_BENCH_ROOT`）
- CANN 安装脚本：`scripts/install_cann_env.sh`
- 运行方式文档：本文
- 每个 op 的 `task_dir` 子文件存在性与真实命名：**实施前现场核实**（以 cann-bench 仓为准，只读）

> **进入下一步的判据**：能跑通至少一次「生成→评测」产出 baseline loss（对应 `self-evolution-design.md §7` 路线图的「最小 baseline loss 验证」），再进入 Phase 1（L1 扩展契约落地）。**先有 baseline 信号，再精修框架** —— 避免在未验证「loss 迭代有信号」前凭空优化 L1。
