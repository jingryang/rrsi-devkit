# subprocess 级领卡 — 方案分析（L3，阶段 2）

> **性质**：self-evolution 线 L3 方案分析。承接 `06-problems.md` P67 阶段 2 + `41-batch-fusion-analysis.md` §2.3 冻结方向 + `01-multi-op-isolation.md` NPUSlotManager 复活方向。
> **立项依据**：用户 2026-07-13 推翻 `41` §2.3「依赖批跑规模确认」排期闸，立即立项阶段 2。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点写函数名不写行号、不照搬外部脚本、不引用会话临时文件、外部依赖只读）。
> **硬约束**：CLAUDE.md §1.2（改动落在职责正确的层）、§2.5（唯一通路，消灭 card_queue 旧根）、§1.4（不考虑向后兼容）、§1.6（依赖注入）。

---

## 0. 问题陈述

阶段 1（`41`/`42`，已交付）把批跑融合进 Python CLI，但卡池是 **run 级独占**：`batch_runner._run_one` 在 run 入口 `card_queue.get()` 领一张卡、跨整个 run 生命周期持有、run 结束 `finally: card_queue.put()`。run 内大量非 NPU 工作（design/codegen 的 LLM 网络 IO、文件读写）期间卡空占。

阶段 2 的目标：把领卡粒度从 **run 入口** 细化到 **NPU subprocess 边界**——真正起 CANN/eval 子进程那一刻领卡、结束即还。这样 run 的 LLM 思考期不占卡，卡可被别的 run 的 NPU subprocess 复用，提升「算子数 >> 卡数」时的吞吐。这是 `41` §0 的原始深层诉求、`01` §3.2 的资源模型纠正（生成 run 内部是 LLM-IO 与 NPU-计算多次交替的闭环，verify/perf 与最终评测共享 NPU 瓶颈）。

本方案回答三个问题：
1. NPU 物理领卡的真实注入点在哪几处？（调研修正了「5 处」的预估）
2. 如何在打破 `state.npu_id` run 级常量不变式的同时不破坏 resume / events / 既有 stage 契约？
3. 如何消灭阶段 1 的 `card_queue` 旧通路、统一到单一卡池（§2.5），且不过度设计？

---

## 1. 关键技术判定（调研事实）

### 1.1 NPU 真选卡的注入点 = 3 处（修正「5 处」预估）

全仓 grep + 逐点核实后，**真正做 NPU 设备选择的 subprocess 注入点只有 3 处**，且 3 个通道**互不一致**：

| 注入点 | 通道形态 | 选卡机制 | 覆盖的 stage |
|---|---|---|---|
| `cannbench_eval._run_eval` | CLI flag `--device-id <n>` | cann-bench `kernel_eval` 自行解析 | cannbench_eval |
| `NPURunner.execute` | env `ASCEND_NPU_ID`（建议性）+ harness 内 `torch_npu.npu.set_device(n)`（**authoritative**） | set_device 硬绑定 | verify / perf / precision_debug run-cases（均经 NPURunner） |
| `scheduling._run_subprocess` | CLI flag `--npu-id <n>` 起 ascendc-devkit 子进程 | 子 CLI 进 task_request → state.npu_id → 落到 NPURunner | OpScheduler（训练线，不在主路径） |

**否定项**（候选清单里**不是**直接选卡的）：
- `deploy._run_command`（profile 驱动的 build/install，不传 device）、`deploy._run_smoke`（仅 callable_target import 可解析性检查，不起 NPU kernel）—— 不选卡。
- `PerfStage` / `PrecisionDebugStage` 本身不起 subprocess：前者构造 evidence（含 `npu_id`）→ PerformanceGate → `NPURunner.execute`；后者 SpawnAgent 把 `device_id` 塞 agent context → agent 调 run-cases CLI → `debug_service.run_cases` → `NPURunner.execute`。**改 NPURunner 即覆盖两者。**
- `stages/smoke.py`（hello.cpp 占位，与 NPU 无关）。

**结论**：物理改点 = `cannbench_eval._run_eval` + `NPURunner.execute` 两处（主路径）；`scheduling._run_subprocess` 是训练线、不在 dispatch/batch 主路径，其 `--npu-id` 最终落到子 CLI 的 NPURunner，改 NPURunner 即顺带覆盖，不单独改。

**环境变量事实**（grep 全仓 0 命中）：**没有任何代码用 `ASCEND_VISIBLE_DEVICES` / `ASCEND_RT_VISIBLE_DEVICES`**。`ASCEND_DEVICE_ID` 仅被 `cannbench_eval._resolve_device_id` **读取**（作 state.npu_id 缺省兜底），从不被本仓**注入**。即：本仓的 NPU 设备选择从来只靠 `--device-id` / `set_device` / `--npu-id` 三条 CLI/env 通道，不存在「靠_VISIBLE_DEVICES 选卡」的既有机制。

### 1.2 `state.npu_id` 是 run 级常量（要打破的不变式）

- **Writers**（3 处一次性写入）：`dispatch` 建 State（`task_request.get("npu_id", 0)`）、`_build_state_for_stage`（单 stage CLI 三层 merge Layer 3）、`EntryStage.transition`（resume 重跑 entry 从 task_request 重写）。
- **Readers**（5 处）：`cannbench_eval._resolve_device_id`、`PerfStage.actions`（→ NPURunner）、`PrecisionDebugStage.actions`（→ agent → NPURunner）、`debug_service.run_cases`（→ NPURunner）、`ContextStage._build_run_context`（→ RunContext 记录性字段）。
- **关键结构事实**：4 个 subprocess 消费者读的是**同一个 run 级常量** `state.npu_id`，它在 run 生命周期内不变（无 stage 在 transition 改它）。这正是「subprocess 级领卡」要打破的不变式——让每个 NPU subprocess 在 spawn 瞬间从池领一张临时卡，而非读一个 run 级常量。

### 1.3 `NPUSlotManager` 现状（死代码，API 偏简，要扩展）

`adapters/npu/slot.py`：`acquire(npu_id=None)→int` / `release` / `list_available` / `list_acquired`，thread-safe（`threading.Lock`）。
- **生产路径从不实例化**：grep 全仓，仅 `scheduling.py` / `training_runner.py` 以**前向引用字符串** `"NPUSlotManager | None"` 接作可选参数（实际从未 import 这个类），测试里才真用。属为阶段 2 预留但未接线的半成品（印证 `01` §3.4「孤儿」）。
- **API 不足**：① `acquire` **非阻塞**（池满即 raise `RuntimeError`，不排队等）——subprocess 级下并发消费者多，需要阻塞 `acquire_wait(timeout)`；② **无死卡回收**——subprocess 崩溃未还时卡永久占住。
- **可复用部分**：`acquire`/`release`/Lock 骨架、`_detect_device_count`（env→torch_npu→默认）探针思路。

### 1.4 `card_queue` 是唯一在产卡池（run 级，要消灭）

`batch_runner.run_batch` 用 `queue.Queue` + `ThreadPoolExecutor`，`_run_one` = `card_queue.get()` → `dispatch(npu_id=card)` → `finally: card_queue.put(card)`。**模型 = run 级独占**（注释明示 stage 1 = run-level exclusive）。这是当前唯一生产路径工作的卡池。阶段 2 必须在收口步**消灭它**（§2.5：同一职责只允许一条实现通路，card_queue 与 NPUSlotManager 是两套卡分配，不能并存）。

### 1.5 resume / events 影响轻（比 `41` §2.3 担心的轻）

- `state.npu_id` 是 state.py 的**普通标量字段**（`npu_id: int = 0`），走通用 `to_snapshot` 的 `dataclasses.asdict` + `from_snapshot` 的 `_rebuild_value` 重建（无专属序列化）。
- grep `npu_id` × `snapshot/event/serialize` 全空：**npu_id 不进 events.jsonl 的 event payload**，仅随 state_snapshot.json 持久化。
- **结论**：语义变更走通用 rebuild，**不破坏 events schema**。卡是运行期临时资源——resume 时无需恢复「卡归属」（中断 run 的 NPU subprocess 早结束了，resume 重新领）。`41` §2.3 担心的「events schema 牵连」实际不成立，阶段 2 的 resume 风险显著低于预估。

---

## 2. 冻结决策

### 2.1 卡池：扩展 `NPUSlotManager`（用户 2026-07-13 拍板）

在现有 `NPUSlotManager` 上扩展（复用骨架，不新建 `NpuCardPool`，避免两套过渡债 §2.5 + `avoid-overdesign-prefer-reuse`）：

- **`acquire(timeout=None)→int`**：改/增**阻塞**语义——池空时 `Condition.wait(timeout)` 排队等卡释放（等价阶段 1 `card_queue.get()` 的 FIFO 阻塞），超时 raise `CardAcquireTimeout`（可观测，不静默退化）。保留原「指定 npu_id 则硬领该卡」语义。
- **`acquire_context(timeout=None)→ContextManager[int]`**：`with pool.acquire_card() as card: subprocess(...)`，`__exit__` 必还（保证异常路径还卡，阶段 1 `_run_one` finally 语义的 subprocess 级等价）。
- **死卡回收**：起步用 **subprocess 生命周期绑定 + subprocess 自带 timeout**（NPURunner 已有 120s timeout、cannbench_eval 1800s）——`with` 块保证正常/异常还卡；subprocess timeout 触发 `with` 退出还卡。**不上 lease/heartbeat**（over-engineering，主进程 SIGKILL 时 pool 同进程同死、不存在「主进程活但卡没还」；subprocess hang 由其 timeout 兜底）。加**死卡检测告警**：`acquire` 时若发现某卡被领时间超阈值（`time.monotonic` 记 acquire 时刻）且池空，打 warn 日志供诊断（best-effort，不强制回收——强制回收需 lease，留规模确认后再议）。

**线程模型**：阶段 2 建立在阶段 1 batch_runner 的**线程模型**上（§1.2 已判线程池对 LLM-IO + CANN subprocess workload 真并发、优于进程池），pool 是进程内单例、线程间共享，Lock/Condition 足够。**不复用 `OpScheduler`/`TrainingRunner` 的子进程模型**（spawn 子 CLI `ascendc-devkit run`，每子进程重 import torch_npu 秒级开销 × N）——它在 self_evolution 训练线、不在 dispatch/batch 主路径。

### 2.2 领卡粒度：真 subprocess 级（每处独立领/还）

每处 NPU subprocess 独立 `with pool.acquire_card() as card: subprocess(...)`，**同 run 内不同 subprocess 可领不同卡**。

**安全性依据**：opp 装载不绑卡——deploy 装 opp 到 per-op `install_path`（文件系统），subprocess 靠 `ASCEND_CUSTOM_OPP_PATH` env 找（不绑 device）；卡选择独立靠 `set_device` / `--device-id`。每个 subprocess 是**独立进程**（`subprocess.run` 起新进程），进程间无 torch_npu 全局状态共享。故 verify subprocess 领卡 0、perf subprocess 领卡 1 安全（`01` §1.2 ops-eval 已验证多版本 opp 共存靠 env 切换、不靠卡绑定）。

这正是 `41` §1.3 的理想粒度，且否定了 action/stage 级（`precision_debug` 一 action 内 LLM+NPU 混合，action/stage 级会把 LLM 思考期算进占用）。

### 2.3 pool 生命周期与注入路径（依赖注入 §1.6）

- **创建**：`batch_runner.run_batch` 创建 **batch 级 pool 实例**（卡池来源复用阶段 1 四级 fallback：`manifest.cards > --cards > _probe_npu_card_count_bounded > ConfigError`，pool 用这个 list 初始化 `NPUSlotManager(max_devices, allowed=list)` 或等价）。
- **注入**：`dispatch(task_request, card_pool=None)` 增可选参 `card_pool: NPUSlotManager | None`。batch 模式 batch_runner 传**共享 pool**；`card_pool is None`（单算子 CLI `run`）时 dispatch **内部建单卡池**（基于 `state.npu_id` 或探测），保证 NPU subprocess **总走统一 `_card_context`**（pool.acquire 或硬指定固定 card），**无「None 走旧 state.npu_id」分支**——卡分配单一通路（§2.5）。单算子行为等价（单卡池领那张），仅多一次池实例化（可忽略）。
- **到达注入点**：pool 经 dispatch → State 携带（`state.card_pool` 字段，frozen dataclass 持引用，**不进 snapshot**——见 §2.5 resume）→ 各 stage 读 `state.card_pool` → 3 处注入点用。或更解耦：pool 不进 State（State 是不可变值对象，不该持可变 pool 引用），改由 stage 上下文/RunContext 携带——**实施时定**，倾向后者（State 保持纯数据，pool 走 RunContext 或 stage 构造参，符合 §1.6 依赖注入 + State 不可变哲学）。

### 2.4 3 处注入点改造（统一决策点）

抽一个**单一领卡决策点** `_resolve_run_card(state, pool) → int | None`：
- `state.npu_id` 非默认（硬指定）→ 返回 `state.npu_id`（跳过 pool，独占预约，等价阶段 1 task 项 npu_id 硬指定语义）。
- `state.npu_id` 默认 + `pool is not None` → `pool.acquire_card()`（subprocess 级领）。
- `state.npu_id` 默认 + `pool is None`（单算子）→ 返回 `state.npu_id`（=0，旧行为）。

3 处注入点改造：
- **`NPURunner.execute`**：npu_id 参数 → 内部 `with pool.acquire_card() as npu_id`（pool 从调用方注入或 NPURunner 持有）。覆盖 verify/perf/precision_debug。**双层注入必须同时改**（env `ASCEND_NPU_ID` + harness `set_device` 用同一个领到的 card，否则不一致）。
- **`cannbench_eval._run_eval`**：`_resolve_device_id` 改用 `_resolve_run_card`，`--device-id` 注入领到的 card。
- **`scheduling._run_subprocess`**（训练线，低优先）：`--npu-id` 传 state.npu_id（硬指定），子 CLI 内部 NPURunner 走 pool——改 NPURunner 后自动覆盖，不单独改。

### 2.5 `state.npu_id` 语义：退化为 Optional 硬指定

- 字段 `npu_id: int = 0` → `npu_id: int | None = None`。`None` = 默认走 pool；非 None = 硬指定该卡（task 项 `npu_id` / 单算子 `--npu-id` 走它，跳过 pool）。
- §1.4 不考虑向后兼容：直接改字段类型，旧 `npu_id=0` 写法改 `None`，不留别名/迁移。
- `pool` 引用**不进 State**（见 §2.3）：State 仍是不可变值对象，pool 是运行期可变资源、走 RunContext/构造参。故 snapshot 不含 pool，resume 自然重建 pool。
- `HardwareEnvironment.npu_id`（run_context.py，记录性字段）：语义改「preferred/hint」——run 起始时未必知下游 subprocess 会领哪张卡，该字段记 `state.npu_id`（硬指定偏好或 None）。非机制，仅诊断面板展示用。

### 2.6 `card_queue` 消灭（§2.5 收口步）

阶段 2 内一次收口：删除 `batch_runner.run_batch` 的 `card_queue` + `_run_one` 的 `card_queue.get()/put()`，run 不再在入口领卡。卡分配统一走 `NPUSlotManager`（NPU subprocess 边界领）。`_run_one` 退化为纯 `dispatch(task_item, card_pool=shared_pool)`。**不留 card_queue 与 pool 并存的过渡态**（§2.5：过渡期并存只能限时、紧随收口步删旧根）。

`design_concurrency` 参数语义自然放宽（`41` §2.2(b) 决策演进已预言）：阶段 1 run 级独占下 `concurrency > cards` 无吞吐收益（多出 run 阻塞等卡不跑 LLM）；阶段 2 subprocess 级领卡后，`concurrency > cards` **有真实吞吐收益**——多出的 run 在 LLM 思考期不占卡、NPU stage 才领卡排队，LLM-IO 与 NPU-计算在 run 间交错复用。参数名不变、语义升级。

---

## 3. 四把尺子复核

- **可维护**：统一领卡决策点 `_resolve_run_card`（硬指定 vs pool 单点判定），3 处注入点不再各读各的 `state.npu_id`；State 保持不可变值对象（pool 不进 State）；消灭 card_queue（§2.5 单一通路）。与既有「State frozen dataclass + Event Sourcing」哲学一致。
- **可扩展**：subprocess 级领卡是 NPU 资源的正交抽象，新 NPU stage 只需调 `_resolve_run_card`；`design_concurrency` 语义升级不用改名；OpScheduler 训练线改 NPURunner 后自动受益。
- **可诊断**：死卡检测告警（acquire 时 lease 超阈值 warn）+ `CardAcquireTimeout`（不静默退化）；per-run 权威记录仍是 events.jsonl（线程安全、per-Workspace）；run.log 并发下 best-effort（阶段 1 P68 已修 swallow）。
- **架构合理**：卡池落 L6 adapters（`NPUSlotManager` 现位置，与 NPURunner 同层），消费在 L3 stage / L2 batch_runner——向下依赖不越层。dispatch 注入 pool 符合 §1.6。

---

## 4. 已拍板决策（2026-07-13）

| 项 | 定案 | 依据 |
|---|---|---|
| 卡池实现 | 扩展现有 `NPUSlotManager`（加阻塞 `acquire`/`acquire_context` + 死卡检测告警） | 用户拍板；`avoid-overdesign-prefer-reuse`；§2.5 |
| 领卡粒度 | 真 subprocess 级（每处 NPU subprocess 独立领/还） | `41` §1.3；opp 不绑卡故安全 |
| 真注入点 | `cannbench_eval._run_eval` + `NPURunner.execute`（scheduling 训练线顺带覆盖，不单改） | 调研修正「5 处」→ 3 处 |
| state.npu_id | `int = 0` → `int \| None = None`，退化为硬指定偏好 | §1.4 直接改 |
| pool 注入 | `dispatch(card_pool=None)`；batch 传共享 pool，单算子 None（旧行为） | §1.6 依赖注入 |
| 统一决策点 | `_resolve_run_card(state, pool)`：硬指定优先，否则 pool.acquire | §2.4 |
| card_queue | 阶段 2 收口步消灭，统一到 NPUSlotManager | §2.5 |
| 死卡回收 | subprocess 生命周期绑定（`with` + timeout）+ 检测告警；不上 lease/heartbeat | avoid-overdesign |
| 线程模型 | 沿用 batch_runner 线程池，不用 OpScheduler 子进程模型 | `41` §1.2 |

**待 L4 实施时定**（非决策分叉，实施细节）：pool 引用走 RunContext 还是 stage 构造参（倾向 RunContext，State 保持纯数据）；`design_concurrency` 默认值是否随语义升级调整。

---

## 5. 与阶段 1 / `01` 文档的关系

- 承接 `41` §2.3 冻结方向（subprocess 级、复活 NPUSlotManager），推翻其「依赖规模确认」排期闸（用户 2026-07-13 决策）。
- 承接 `01` §3.2 资源模型纠正（生成 run 内部 LLM-IO 与 NPU-计算交替闭环）、§3.4/§5.5 改造点（verify/perf 直连 state.npu_id → 走 slot）。但 `01` 的 cann-bench 评测线（per-op opp 隔离、`--device-id` 非侵入）**不在本阶段范围**——本阶段只做「NPU subprocess 级领卡」这一条，cann-bench 评测的 opp/whl 隔离（`01` §5.6 / `02-opp-isolation.md`）是另一条独立线。
- 承接阶段 1 `42` §9 接口预留：`design_concurrency` 参数 + 卡池 `queue` 已就位——本阶段把 `queue` 升级为 `NPUSlotManager`（消灭旧 queue），`design_concurrency` 语义升级。

---

## 6. 否定项（明确不做）

- ❌ **新建 `NpuCardPool`**（用户拍板扩展 NPUSlotManager）。
- ❌ **保留 `card_queue` 与 pool 并存**（§2.5：收口步必须消灭旧根）。
- ❌ **lease/heartbeat 死卡回收**（over-engineering，subprocess timeout + `with` 兜底足够，留规模确认后再议）。
- ❌ **改 OpScheduler/TrainingRunner 子进程模型**（不在主路径，改 NPURunner 自动覆盖其下游）。
- ❌ **用 `ASCEND_VISIBLE_DEVICES` 注入**（全仓无此先例，靠 `--device-id`/`set_device`/`--npu-id` 三通道）。
- ❌ **pool 进 State / 进 snapshot**（State 保持不可变值对象，pool 走 RunContext）。
- ❌ **cann-bench opp/whl 隔离**（`01`/`02` 另一条线，本阶段不裹挟）。
