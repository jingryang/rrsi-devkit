# 批跑融合进 Python CLI — 方案分析（L3）

> **性质**：self-evolution 线 L3 方案分析。**冻结**（2026-07-13，用户「按你的建议做」拍板两阶段解耦）。
> **承接问题**：`06-problems.md` P67。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点不写行号、不照搬外部脚本、不引用会话临时文件、外部依赖只读）。
> **硬约束**：Python 实现不得复刻 shell 的「与具体代码仓耦合」形态（CLAUDE.md §1.7/§1.5）。

---

## 0. 问题陈述

批跑能力（多算子并发生成→编译→评测→收 loss）当前由外部 `batch_self_evolve.sh` 承担，Python `run` 一次一算子、无批跑入口；且 shell 与 cann-bench 仓布局硬耦合。深层诉求是把 NPU 独占粒度从 run 级细化到「真正上 NPU 才占」（subprocess 级），以提升算子数 >> 卡数时的吞吐。详见 P67。

本方案回答两个问题：
1. 批跑能不能优雅地融合进 Python（不与代码仓耦合）？
2. NPU 独占粒度能不能细化？

---

## 1. 关键技术判定（四把尺子前置核实）

### 1.1 线程 vs 进程

- 本 workload 的并发瓶颈是 **LLM 网络 IO**（`claude_agent_sdk.query` 走 stdio spawn claude CLI 子进程）+ **CANN subprocess**（build/eval/precision），两者都**释放 GIL**。
- `ThreadPoolExecutor` 对此 workload 是**真并发**，不是「假并发」（GIL 只锁纯 Python CPU）。`ProcessPoolExecutor` 不仅无收益，反而有害：每个子进程要重新 `import torch_npu`（秒级开销 × N）+ pickle 传递 State（State 是 frozen dataclass 但携带大量产物路径/字符串）。
- **结论**：多实例并发用线程池，不上进程池。阶段 1 落地依据。

### 1.2 env 隔离的线程安全性

- 5 处 NPU subprocess 调用点（deploy build/smoke、precision_debug run-cases、perf、cannbench_eval）统一模式：`env = os.environ.copy()` → 局部 setdefault → `subprocess(env=env)`。
- **不写全局 `os.environ`**，env 是子进程级局部副本。多线程各跑各的 run、各 copy 各的 env，无竞争。
- **结论**：线程并发下 env 隔离天然安全，无需额外锁。这是 run 级池（阶段 1）可行的物理基础，也是 subprocess 级领卡（阶段 2）的物理基础——卡占用本就发生在 subprocess 那一刻，而非 run 入口。

### 1.3 NPU 独占粒度的现状

- `--npu-id` → `state.npu_id`（run 级），流到所有 NPU stage 的 subprocess `device_id`。卡在 run 入口绑定、跨整个 run 生命周期持有。
- run 内大量非 NPU 工作（design/codegen 的 LLM 网络 IO、文件读写）期间，卡是空占的。
- **action 级不够细**：`precision_debug` 一个 action 内混合 LLM（改码/日志分析）+ NPU（run-cases），在 action 级领卡会把 LLM 思考期也算进占用。理想粒度 = **subprocess 级**（真正起 CANN/eval 子进程那一刻领卡、结束即还）。

---

## 2. 冻结决策：两阶段解耦

### 2.1 为什么解耦（不裹挟进一次大改）

- 批跑融合（阶段 1）是**编排层**问题：多 run 实例调度 + run 间卡池。不动 `state.npu_id` 语义，不动任何 stage，run 内部行为零变化。改动面小、风险低、立刻等价 shell。
- NPU 粒度细化（阶段 2）是**能力层**问题：subprocess 级领卡要求 `state.npu_id` 语义从「入口绑定、run 跨生命周期持有」变为「运行期按需领用」，触动 5 处 subprocess 点 + State 不变式 + 所有 NPU stage 的领卡/还卡契约。改动面大、跨层（L5 能力 + L3 stage）。
- 把两者绑一起 = 让「批跑融合」这个低风险快赢背「NPU 语义重构」的全部风险与回归面，违反 §1.2（改动落在职责正确的层/边界，不越层兜底）。
- **分阶段**：阶段 1 先交付批跑融合（run 级池，等价 shell，立即收益）；阶段 2 作为独立框架演进 follow-up，**依赖批跑规模确认**（只有当实测「算子数 >> 卡数」且 run 内 LLM 空占比高到值得时才做——见 §2.3 判据）。

### 2.2 阶段 1：批跑融合（本次实施范围）

**目标**：`ascendc-devkit run` 加批跑入口，等价 shell 的 run 级独占 + run 间 FIFO 卡池，但不与代码仓耦合。

**(a) 入口形态 — manifest = wrapper（批跑级配置 + 一组单算子任务）**

- 用户想法：批跑就是「把多个单算子命令装进来」。落地为 wrapper：顶层承载批跑级配置，`tasks[]` 每项是一个单算子任务。
- 顶层字段：`cards`（可用卡池，见 (b)）、`output_root` 等单算子公共默认；任务项继承顶层默认，只写差异。
- `tasks[]` 每项字段名与 `run` CLI option dest **一一对应**（`op_dir`/`requirement_path`/`golden_path`/`golden_entry`/`design_target_chip`/`npu_id`/…），等价于一次单算子 `dispatch(task_request)`。
- 这样：① 用户写 manifest = 写一串熟悉的单算子参数（顶层默认 + 任务项差异），零新概念；② 1 项自动退化 = 直接走单算子 dispatch，无批跑开销；③ manifest 字段契约 = CLI dest，单一权威源（CLI option 改名 manifest 自动同步），不另立 schema 词表。

**(b) 卡池来源与并发上限**

- **卡池来源四级 fallback**：manifest 顶层 `cards`（权威）> CLI `--cards` override > **未配置时 bounded NPU 探测兜底** > 探测失败报错（要求显式声明）。兜底走 bounded 模式（超时报错，**不 hang 死批跑**）；探测给的是物理卡数，若机器有别的任务占卡，用户应显式声明 `cards` 子集——兜底是「尽力而为」非权威。
- **并发上限：可选 `concurrency`，与卡数完全解耦**。`concurrency` 是**本地资源阀**（防大批量算子时线程数压垮 CPU/内存/文件句柄），卡池是 **NPU 临界资源阀**，两者正交。设置了 → `ThreadPoolExecutor(max_workers=concurrency)` 限制同时启动的 run 线程数；未设置 → 不设上限（`max_workers=任务数`，全并发，**大批量场景建议显式设置防本地资源耗尽**；注意 Python `max_workers=None` 会退化为 `min(32, cpu+4)`，故「不设上限」须显式传任务数）。每个 run 线程入口 `queue.get()` 领卡（池空阻塞等卡，等价 shell FIFO）、run 结束（含异常）`queue.put()` 还卡。**阶段 1 run 级独占下的诚实限制**：run 入口即领卡占全程，故 `concurrency > cards` 时多出的 run 阻塞等卡（不跑 LLM），此时 concurrency 只起「限制线程数防本地资源耗尽」的安全阀作用、**无吞吐收益**；`concurrency > cards` 真正的吞吐收益（更多 run 并行 LLM、NPU subprocess 才领卡排队）要等阶段 2 subprocess 级领卡（§1.3/§2.3）——届时此参数语义自然放宽，不用改。
- 任务项显式写 `npu_id` = 硬指定该卡（独占预约，须在卡池内，否则配置报错），不参与池分配。

**(c) 仓耦合剥离**

- shell 的仓耦合集中在：git worktree 创建、task 目录解析、算子源码定位。这些**都是 cann-bench 仓的布局知识，属该仓自身**，不应进 Python。
- Python 侧只认 **manifest 里每项提供的 `op_dir`（绝对路径，已隔离的算子目录）**，由 `resolve_op_dir` 解析 profile/repo_root/op_name——复用单算子既有通路（§2.5）。worktree/task 解析是**清单准备阶段**的事，留在仓侧（用户手写或仓侧脚本生成 manifest），Python 不掺和。
- **阶段 1 不做 `batch-prepare`**：避免过早做生成器（过度设计）。真有「从仓 task 目录批量生成 manifest」需求时再加，且加时必须走通用 glob 模式（用户传 task-glob / op-dir-pattern，Python 按模式展开），**严禁写死任何仓布局**——否则就是 shell 翻版。cann-bench 想自带 manifest 生成，是它仓自己的事，不进 DevKit。

**(d) 落点与回归**

- 新增 L2 Application 层 `batch_runner.py`：读 manifest → 线程池并发跑 `dispatch` → 卡池调度 → 汇总每 run 的 exit code/state。不碰 L3 stage、不碰 `state.npu_id` 语义。
- CLI `run_cmd` 增加 `--batch` 分支：传了 `--batch` 走 batch_runner，否则原单算子路径（§2.5：单算子是唯一退化通路，不并存两套）。
- 守护：UT 测 manifest→task_request 映射、卡池四级 fallback（含兜底探测 bounded + 失败报错）、get/put 正确性（含异常还卡）、1 项退化、任务项 npu_id 硬指定校验；ST 测 2 算子批跑端到端（stub backend，不依赖真 LLM）。

### 2.3 阶段 2：NPU 粒度细化（独立 follow-up，本次不做）

**实质**：复活 `01-multi-op-isolation.md` 已定稿的 `NPUSlotManager` 方向（当前孤儿），把领卡从 run 入口下沉到 5 处 subprocess 点。

**改动面**（why 须独立、不进阶段 1）：
- L5 新增 `NpuCardPool` 能力（领/还/超时/死卡回收）。
- `state.npu_id` 语义变更：从「入口绑定、run 跨生命周期」→「运行期按需领用」。State 是 frozen dataclass + Event Sourcing 权威记录，语义变更牵动 resume（中断 run 的卡归属）、stage 契约、events schema。
- 5 处 subprocess 点改造：subprocess 起 → 领卡设 device_id → subprocess 终 → 还卡。`precision_debug` 这类「一个 action 内 LLM+NPU 混合」的 stage，领卡要落在 run-cases subprocess 边界，而非 action 边界（§1.3）。

**触发判据（依赖批跑规模确认，不预先排期）**：
- 阶段 1 落地后实测批跑：算子数 >> 卡数 且 run 内 LLM 空占比显著（卡被 design/codegen 思考期空占）→ 做阶段 2。
- 反之若实测卡数足够 / LLM 空占比低（run 级独占已近满载）→ 不做，run 级池足矣。
- 阶段 2 立项时按 §1.8 单独立 L1（挂在 P67 之下，标「依赖批跑规模确认」）+ L3 + L4，不复用本文件。

---

## 3. 四把尺子复核

- **可维护**：manifest 字段 = CLI dest（单一权威），不立新 schema 词表；阶段 1 不动 State 语义/任何 stage，与既有设计哲学一致。
- **可扩展**：阶段 1 的卡池是 run 级抽象，阶段 2 的 `NpuCardPool` 是 subprocess 级抽象，两者正交、可叠加；新算子/新仓只改 manifest，不改 Python。
- **可诊断**：批跑每 run 自带 events.jsonl + run.log（既有 Workspace 自包含），batch_runner 只汇总 exit code/state，错误信号落在各 run（不吞、不推迟到下游）。
- **架构合理**：阶段 1 落 L2（编排），阶段 2 落 L5（能力）+ 触动 L3 stage 契约——各归各位，不越层。

---

## 4. 已拍板决策（2026-07-13，用户确认）

阶段 1 四项形态决策已定（L4 直接据此实施，无前置）：

| 项 | 定案 |
|---|---|
| manifest 格式 | wrapper：顶层批跑级配置（`cards`/`output_root`/公共默认）+ `tasks[]` 单算子项（字段 = run CLI dest） |
| 卡池来源 | 四级 fallback：manifest `cards` > CLI `--cards` > 未配置 bounded 探测兜底 > 报错 |
| 并发上限 | 可选 `concurrency`，与卡数完全解耦（本地资源阀）；未设=不设上限（全并发，大批量建议显式设） |
| batch-prepare | 阶段 1 不做；未来要做须走通用 glob，禁写死仓布局 |

**决策 3 演进记录**：① 初稿以「限流防 429」论证独立 `--concurrency`，用户澄清 429 与本地并发数无强关联（服务端是数百人共享大资源池），该论据不成立；② 进而考虑去除独立参数、并发=卡池大小；③ 用户最终定：保留 `concurrency` 为**可选参数**，但理由切换为**本地资源阀**（防大批量算子时线程数压垮 CPU/内存/文件句柄），与卡数完全解耦——未设=不设上限（全并发），设了才限。**阶段 1 run 级独占下 `concurrency > cards` 无吞吐收益**（run 入口即领卡占全程，多出的 run 阻塞等卡不跑 LLM），此时仅起安全阀作用；吞吐收益（更多 run 并行 LLM、NPU subprocess 才领卡排队）待阶段 2 subprocess 级领卡（§1.3）——届时此参数语义自然放宽，不用改。

L4（符号级实施步骤 + TDD）另文 `42-batch-fusion-impl.md`，本文件不写实施细节。
