# 多算子并行评测 — 临界资源隔离方案

> **性质**：self-evolution 线工作记录（L3 性质的方案分析），承接 `00-review-2026-06-29.md` §5 的 baseline 对接路径。
> **时点声明**：本方案的事实基础来自对 cann-bench（外部只读依赖）+ 本仓 `ascendc-ops-evaluation` skill 的代码核实，未在真实多算子并发场景跑通验证；§5 列出待验证项。
> **已定选型（2026-06-29）**：python 侧隔离 = `pip --target` + PYTHONPATH（轻）；评测执行层 = 复用 cann-bench `ProcessPool`，改造 env 注入。
> **建制化状态**：本线暂不进四层体系（用户决策），产物平铺在 `self-evolution/` 子目录，不挂 L2 总纲。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点不写行号、不维护现状快照、不照搬外部脚本、外部依赖只读、不引用会话临时文件）。

---

## 0. 问题

self-evolution 要把「算子生成能力」当可训练系统求 loss 迭代。训练集是 cann-bench 的算子集（如 phase0 的 35 算子），每个算子要独立「生成 → 编译 → 评测 → 收集 loss」。当多个算子**并发**推进时，一系列临界资源需要隔离调度：

- NPU 卡共享（多算子抢卡）
- CANN 环境 / 内置 opp 共享
- **自定义算子 opp 共存**（多算子的 opp 注册互踩）
- **并发编译安装**（pip / build.sh 全局资源冲突）

cann-bench 的 `--processes-per-card` 只回答了「**单份提交内**多 case 跨卡跨进程」，没回答「**多份独立生成的算子并发**」。本方案填这个空白。

---

## 1. 事实基础：两套现成模型的并发边界（核实）

### 1.1 cann-bench（kernel_eval）—「单份提交内并行」

- **提交单元**：一个 source-dir（含 `build.sh` + `csrc/ops/<op>/`）。
- **编译**：`build_packages` 跑 `bash build.sh` 整体编译，产 `dist/cann_bench*.whl` + `*.run`。设计哲学（`build_packages` 注释原话）：为「评测并行化」**故意放弃**早期「移动 `csrc/ops/<op>/` 重编」的隔离补救，改「整体编译、失败整批 0 分、不改用户源码」。
- **安装**：run 包经 `install.sh --install-path=<CANN opp 根>` 装到**全局 CANN opp 的 vendor 目录**；whl 经 `pip install --no-deps` 装到**全局 site-packages**。
- **评测**：`ProcessPoolCoordinator` 管 `卡数 × processes_per_card` 个子进程槽，每槽 `subprocess.Popen(start_new_session=True, env=注入 device_id)`，**共享全局装好的 opp**；带 OOM/超时/部分结果恢复。
- **独占假设**：`uninstall_packages` 先清全局 cann_bench whl → **同一时刻全局 opp/site-packages 只服务一份提交**。

> 边界：cann-bench 的并行是「一份已编译安装的提交，多个 case 分摊到多卡多进程」。它**不**支持多份独立提交并发 install（会互踩全局 opp vendor + site-packages）。

### 1.2 ops-evaluation（本仓 skill）—「多版本算子共存」（已验证）

- baseline / evolved 各自 build → 装到**独立 install-path**（`<path>/vendors/<vendor_subdir>/`），**完全不碰全局 CANN opp**。
- 评测子进程 env 设 `ASCEND_CUSTOM_OPP_PATH=<install-path>/vendors/<vendor>` + `LD_LIBRARY_PATH` 加该版本 `op_api/lib` + `ASCEND_DEVICE_ID`。
- 靠环境变量在子进程级切换 opp → 两版本算子共存，**不需 cp 仓、不需多 venv、不需 uninstall**。
- 边界：**串行评测、单卡**。

### 1.3 结论：两者正交，拼接即解

cann-bench 解决「一份提交内多 case 跨卡并行」（靠全局 opp 独占 + uninstall 串行化）；ops-evaluation 解决「多算子/版本共存」（靠 per-install-path opp + 子进程 env 切换）。**两者正交，拼起来正是多算子并发评测的解**，且都不需要 cp 仓 / 多 venv。

这印证 `00-review` §2 的核心纠正「框架不该造 cp 整份仓隔离」——**正确**；但澄清一点：**per-operator opp 目录隔离（install-path 维度）是真实需要的**，它不是 cp 仓，而是把 cann-bench「装全局 opp」改成「装 per-op opp 目录」。

---

## 2. 临界资源逐项隔离策略

| 临界资源 | 真相 | 是否临界 | 隔离策略 | 机制来源 |
|---|---|---|---|---|
| **NPU 卡** | 多卡可分；生成内部 verify/perf + cann-bench 评测共抢 | 是 | `NPUSlotManager` 统一分配 `--device-id`：服务生成 run 内部 verify/perf（本仓改造走 slot）+ cann-bench 评测（外层传 `--device-id`，非侵入） | 复活并扩展 `NPUSlotManager`（当前孤儿） |
| **CANN 工具链 / LD_LIBRARY_PATH** | 全局单实例，编译器/库可重入 | **否** | 只读共享 | 无需处理 |
| **ASCEND_OPP_PATH（内置 opp）** | CANN 自带，只读 | **否** | 共享；anti_cheat 只读检查 | 无需处理 |
| **自定义算子 opp 共存** | cann-bench 装全局 opp → 互踩 | **是（核心）** | 每算子装**独立 install-path opp 目录**，子进程 `ASCEND_CUSTOM_OPP_PATH` 指向自己的 | 复用 ops-eval 已验证模型 |
| **cann_bench whl / python 模块** | pip 全局 → 同名覆盖 | **是** | 每算子 `pip install --target=<per-op-dir>`，子进程 `PYTHONPATH` 指向 | **已选型**：轻量路径 |
| **build.sh 编译** | 各 source-dir 独立 build | 弱 | 各自 source-dir、限并发数 | 天然不冲突 |

---

## 3. 整体架构（已定选型）

### 3.1 per-operator 隔离单元

每个算子绑定一个隔离单元：

```
{ source-dir,  opp-install-path,  python-module-path,  device-id }
```

- **source-dir**：算子源码（含各自 `build.sh`），编译产物落各自目录，互不干扰。
- **opp-install-path**：`bash build.sh ... --install-path=<per-op-opp-dir>`，**不碰全局 CANN opp**。多算子 opp 各占独立目录，靠评测子进程 `ASCEND_CUSTOM_OPP_PATH` 切换。
- **python-module-path**：golden / 评测 python 装到 per-op 目录（`pip install --target=<per-op-dir>`），子进程 `PYTHONPATH` 指向。
- **device-id**：评测时由调度层分配。

### 3.2 调度层：生成-评测流水线 + 统一 NPU 卡池（非侵入 cann-bench）

**调度形态：流水线，非批量两阶段**。每个算子的隔离单元（§3.1）自包含，**生成完即可独立进评测**，不需等其他算子——「等全部生成完」是人为 barrier。

**资源模型（关键事实，避免误判）**：生成阶段**不是**纯 LLM。`generate_ascendc` 一个 run 内部 = `design/codegen`（LLM-IO）+ `verify`（NPU 精度）+ `perf`（NPU 性能）+ 失败 loopback 回 codegen，是 **LLM-IO 与 NPU-计算多次交替的闭环**。真正的资源轴是 **LLM-IO vs NPU-计算**，不是「生成 vs 评测」：生成内部 verify/perf 与最终评测**都是 NPU-计算**，共享 NPU 瓶颈。（「生成用 CPU/LLM、评测用 NPU、资源正交」是错误前提，已弃。）

**为什么流水线仍优于批量**：吞吐来自 **LLM-IO 与 NPU-计算在多算子间交错复用**——一个算子等 LLM 时，NPU 跑别的算子的 verify/perf/评测。批量两阶段不让这两类资源在算子间交错。另：吸收生成不确定性、早失败暴露、失败隔离。

**非侵入边界（硬约束）**：cann-bench 是只读外部仓，**不改其任何代码**。所有控制通过 cann-bench **已有的 CLI 参数 + 环境变量**从外层（本仓 `scripts/`）传入：
- NPU 卡 → `--device-id <slot>`（cann-bench 单卡模式旋钮）
- python 模块路径 → `PYTHONPATH`（外层设，cann-bench 子进程继承，cann-bench 不覆盖）
- opp 路径 → `ASCEND_CUSTOM_OPP_PATH`（⚠ 受 cann-bench build/set_env 行为影响，归 opp 隔离 open 问题，见 §5.6）

**NPU 统一卡池（非侵入）**：`NPUSlotManager`（本仓）统一分配 device-id 给两类 NPU 消费者——
- **生成 run 内部 verify/perf**（本仓代码）：改造为从 `NPUSlotManager` acquire 卡（替换 `NPURunner(chip_version)` 直连的 `state.npu_id` 默认 0），用完 release。
- **cann-bench 评测**（外部）：外层调 `run_evaluation.sh` 前 acquire 卡 → `--device-id <slot>` 传入 → 评测完 release。
- **强制纪律**：所有并发 cann-bench 调用必须 `--device-id` 单卡模式；**禁用**其多卡自动模式（那会抢占全部卡、与别的实例冲突）。cann-bench 内部 ProcessPool 在单卡模式下自行跑（card_count=1），一行不动。

**「复用 cann-bench」的真实含义**：复用 cann-bench **作为评测引擎**（编译/评测/报告全用它，经 CLI 调用），**跨算子的并发调度 + 卡分配在外层本仓**（NPUSlotManager + 多个 subprocess 起 `run_evaluation.sh`）。cann-bench 的「多卡并行」能力在本场景**不用**（它假设独占全部卡），只用其单卡评测。

**实现形态（本仓 `scripts/` 训练集 runner）**：
- **生成 pool**：并发多个 `generate_ascendc` run（独立 op_dir/State/event-log）；run 内 verify/perf 从 `NPUSlotManager` acquire/release 卡。并发度受 LLM 限流 + NPU 卡数双约束。
- **就绪队列（无 barrier）**：run 完成（内部 verify/perf 收敛）→ 布局适配包成 cann-bench 兼容 source-dir → 推评测队列。
- **评测 pool**：worker 从 `NPUSlotManager` acquire 卡 → subprocess 起 `run_evaluation.sh --device-id <slot> --source-dir <per-op>`（env 带 per-op `PYTHONPATH`）→ 收 `reports/<op>/eval_report` → release 卡。

**与 cann-bench 整批编译的关系**：cann-bench `build_packages`「整批编译」是「一份提交内多算子共享 build.sh」的优化；self-evolution 每算子独立 source-dir，本就是每算子独立 build，无整批 barrier——「生成完一个即评测」是自然形态。

### 3.3 python 侧隔离（已选型：pip --target + PYTHONPATH）

- 每算子 whl `pip install --target=<per-op-python-dir>`，**不进全局 site-packages**。
- 评测子进程 env 设 `PYTHONPATH=<per-op-python-dir>`。
- 共享一个 Python 解释器；要求所有算子的 torch/torch_npu ABI 一致（同环境天然满足）。
- 否定多 venv：过重（每 venv 装 torch_npu 是 GB 级），不符合 baseline 最小验证的轻量诉求。

### 3.4 NPU 调度现状与接入节奏

- `NPUSlotManager`（`adapters/npu/slot.py`）当前是孤儿（production 零引用；同目录 `NPURunner` 单卡执行已被 verify/perf 深度集成，但直连 `state.npu_id` 不走 slot）。
- 统一卡池的调度逻辑见 §3.2（非侵入：cann-bench 走 `--device-id`，verify/perf 走本仓 slot 改造）。接入节奏：baseline 单算子阶段暂不启用（cann-bench `--device-id` 单卡串行即可）；并发阶段才接入，届时 verify/perf 与评测都走 `NPUSlotManager`。

---

## 4. 否定项（明确不做）

- ❌ **cp 整份仓**（`00-review` §2 已证臆造；cann-bench / ops-eval 都不需要）。
- ❌ **多 venv**（过重，已选 `pip --target` 替代）。
- ❌ **修改 / 污染全局 CANN opp**（互踩根源；改用 per-op install-path）。
- ❌ **另造进程隔离框架**（复用 cann-bench `ProcessPool`）。
- ❌ **保留 cann-bench「全局 install + uninstall 清场」通路用于并发**（它是单份提交独占模型，并发必互踩）。

---

## 5. 待验证风险（诚实）

1. **build.sh 的 `--install-path` 可定制性**：ops-eval 标准仓 `build.sh` 支持 `--install-path`；cann-bench 的 `install.sh --install-path` 已确认可用（package_manager 这么调）。但 **DevKit `generate_ascendc` 产出的算子，其 build.sh 是否支持任意 install-path，未验证**——这本质是「布局适配」问题（`00-review` §4 清单 #3），现归入 per-op 隔离单元的 source-dir 子问题，不再是独立阻塞点。
2. **anti_cheat 在 per-op opp 下的行为**：cann-bench `security/` 的 guard（api_guard / device_residency_guard / torch_op_guard / type_checker）是评测时检查（非安装期），理论上与 per-op 隔离兼容；但 `device_residency_guard` 等是否假设全局 opp，需跑通验证。
3. **同算子多 case 跨卡（cann-bench 已解决）× 多算子各占卡（本方案）** 叠加时的卡槽调度，需 `NPUSlotManager` 与 `ProcessPool` 协调（谁拥有卡的所有权、单卡内 processes_per_card 是否仍适用）。
4. **DevKit 产出布局 → cann-bench source-dir 兼容包** 的适配层（`00-review` §4 #3）：DevKit 产出落 repo 内 op_dir（`op_host/` + `op_kernel/`），cann-bench source-dir 期望自包含包（`build.sh` + `csrc/ops/<op>/` + `setup.py`）。需一个包装层把产出包成 cann-bench 兼容 source-dir。这是布局适配，本方案不展开，归入后续实施。
5. **verify/perf 走 slot 的前置改造**：DevKit 当前 verify/perf stage 直连 `NPURunner(chip_version)` 用 `state.npu_id`（默认 0），多 run 并发抢同一卡。要并发须改造为从 `NPUSlotManager` acquire/release——改的是本仓 verify/perf stage（不碰 cann-bench），是生成 pool 并发的前置改造。
6. **opp + whl 隔离（已分析，见 `02-opp-isolation.md`）**：`--device-id` 只解决卡冲突；cann-bench install 装 **opp**（全局 `vendors/custom_ops`）+ **whl**（全局 site-packages）两类资源，多实例并发互踩。已定方案：**A 起步**（单实例批量，cann-bench 原生，opp/whl 都不冲突）→ **D 升级**（`--skip-install` + 外层 install opp/whl 到 per-op，细粒度流水线），**B 弃**（whl 全局遗留）。详见 `02-opp-isolation.md`。

---

## 6. 对 `00-review` baseline 路径的修正

`00-review` §5 的 baseline 对接路径：

> DevKit `generate_ascendc` 产出 → 只读调用 `run_evaluation.sh --source-dir` → 收集 reports 为 baseline loss。

本方案修正为：

> DevKit 产出 → **布局适配层**包成 cann-bench 兼容 source-dir → per-op 隔离单元（独立 opp-install-path + `pip --target` python 路径 + device-id）→ 复用 cann-bench `ProcessPool` 评测（env 注入 per-op `ASCEND_CUSTOM_OPP_PATH`/`PYTHONPATH`/`device-id`）→ 收集 `reports/<op>/eval_report` 为 baseline loss。

即：`--source-dir` 直接消费不成立（布局不匹配），且单卡串行只是 baseline 最小步；并发评测必须 per-op 隔离，不能依赖 cann-bench 的全局 install 通路。

---

## 7. 与已有决策 / 记忆的关系

- 承接 `00-review` §3 决策：cann-bench 只读边界（本方案所有改造在本仓 `scripts/`，不改 cann-bench）；弃用临时脚本；baseline 先行。
- 承接 `00-review` §2 核心纠正：不造 cp/opp 隔离——本方案澄清「不 cp 仓」对，但「per-op opp 目录隔离（install-path 维度）」是真实需要，与 cp 仓不同。
- 项目记忆 `avoid-overdesign-prefer-reuse`：本方案优先复用 cann-bench `ProcessPool` + ops-eval `ASCEND_CUSTOM_OPP_PATH` 模型 + 本仓 `NPUSlotManager`，不另造。
- 项目记忆 `self-evolution-direction`：baseline 先行；本方案给出 baseline 的并发评测底座。

---

## 8. 下一步（路线图）

1. **布局适配层**（§5.4）：证 DevKit 产出能包成 cann-bench 兼容 source-dir。单算子、单卡、串行跑通一次「生成 → 评测 → loss」，证 loss 有信号。
2. **per-op 隔离单元**（§3.1）：把单算子路径包成隔离单元（独立 opp-install-path + `pip --target`）。
3. **并发调度**（§3.2 + §3.4）：接入 `NPUSlotManager` + 改造 `ProcessPool` env 注入，多算子并发。
4. 据 baseline 暴露的真实约束，回精修 L1 框架（P0 registry 自动发现 / P1 State 产物袋；P2 节点树已实现，见本次核实）。
