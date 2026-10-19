# subprocess 级领卡 — 实施方案（L4，阶段 2）

> **性质**：self-evolution 线 L4 符号级实施方案。承接 L3 `43-subprocess-card-pool-analysis.md`（已冻结 9 项决策）。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点写函数名不写行号、不照搬外部脚本、不引用会话临时文件、外部依赖只读）。
> **硬约束（用户 2026-07-13）**：`--npu-id` 必须保留且 end-to-end 功能可用；`card` 值从 CLI 流到 subprocess spawn 边界须有真实 ST 守护（断言注入值，非 mock 掉链路）。

---

## 0. 复用入口（已核实签名）

- `NPUSlotManager`（`adapters/npu/slot.py`）：`acquire(npu_id=None)→int` / `release(npu_id)` / `list_available` / `list_acquired`，thread-safe（Lock）。**扩展不重写**（§2.5 复用骨架）。
- `NPURunner.execute(operator, test_cases, npu_id, ...)`：npu_id 注入 env `ASCEND_NPU_ID`（建议性）+ harness 内 `torch_npu.npu.set_device(npu_id)`（authoritative）双层。**双层必须同时改**（同一领到的 card）。
- `cannbench_eval._resolve_device_id(state)`：`getattr(state,'npu_id',0) → str`，喂 `--device-id` CLI flag。
- `dispatch(task_request, progress_callback=None) → int`：run 级入口，建 State。**增可选 `card_pool` 参**。
- `batch_runner.run_batch(manifest, card_pool, ...)`：阶段 1 用 `card_queue`（run 级领卡）。**收口步消灭 card_queue**。
- State `npu_id: int = 0`（`orchestration/kernel/state.py`）：普通标量，走通用 `to_snapshot`/`from_snapshot` rebuild。
- 卡数探测：`batch_runner._probe_npu_card_count_bounded`（torch_npu 主 + npu-smi 兜底，bounded）。

## 1. NPUSlotManager 扩展（L3 §2.1）

新增/改：
- `acquire(timeout=None)→int`：**改阻塞语义**——池空 `Condition.wait(timeout)`，超时 raise `CardAcquireTimeout`（新异常，`domain/exceptions.py`）。保留指定 `npu_id` 硬领语义。记 `acquired_at[npu_id]=time.monotonic()` 供死卡检测。
- `acquire_context(timeout=None)→ContextManager[int]`：`@contextmanager`，yield card，`finally release`（异常路径也还）。
- 死卡检测：`acquire` 时若池空且某已领卡 `now - acquired_at > lease_warn_threshold`（runtime_config 暴露，默认如 600s）→ `Logger.warn`（best-effort 诊断信号，**不强制回收**——强制回收需 lease，L3 §2.1 否定项）。
- `release(npu_id)`：清 `acquired_at[npu_id]`。
- 不动 `_detect_device_count`（env→torch_npu→默认，复用）。

**初始化**：`NPUSlotManager(max_devices=N, allowed=list[int]|None)`——`allowed` 限定可用卡子集（batch 模式卡池四级 fallback 的结果），`None` = `range(max_devices)`。

## 2. `_card_context` 统一决策点（L3 §2.4）

新增 `adapters/npu/card_context.py`（或入 slot.py，L5 同层）：
- `_card_context(state, pool, timeout=None)→ContextManager[int]`：`@contextmanager`。
  - `state.npu_id is not None`（硬指定）→ `yield state.npu_id`（**不 acquire pool**，固定 card，`--npu-id`/task npu_id 走此分支）。
  - `state.npu_id is None` + pool → `with pool.acquire_context(timeout) as card: yield card`（subprocess 级领/还）。
- 单一决策点，3 处注入点都调它（§2.5 唯一通路）。

## 3. pool 生命周期 + dispatch 注入（L3 §2.3）

> **实施定案（2026-07-13）**：L3 §2.3 「倾向 RunContext」未采纳——pool 落 **State 瞬态字段**（`state.card_pool: Any = field(repr=False, compare=False)`，与既有 `_workspace` 同模式：frozen dataclass 持运行期引用、不参与相等/快照）。理由：① stage 读 pool 已有统一入口（`state.card_pool`），无需另立 RunContext 字段；② `_workspace` 已开「State 持瞬态 adapter 引用」先例，pool 同类。dispatch 单算子**不自建池**（推翻 §3 原计划）——传 `None`，由 `card_context` 统一兜底（preferred 非 None yield 固定卡 / pool None yield 0），卡分配单一通路（§2.5），少一个 dispatch 内建池分支。

- `dispatch(task_request, progress_callback=None, card_pool=None)`：增 `card_pool: NPUSlotManager | None`。
  - `card_pool` 非 None（batch）：直接用 batch_runner 传的共享池，挂 `state.card_pool`。
  - `card_pool is None`（单算子 CLI）：state.card_pool=None；card_context 兜底（npu_id 非 None yield 该卡 / None yield 0）。
- pool 经 **State 瞬态字段** `card_pool` 携带到 stage（不进 snapshot，见 §6）；stage 读 `state.card_pool` 喂 `card_context`。
- L2→L3 工厂 seam：batch_runner（L2）经 `orchestration.card_pool.build_shared_card_pool(card_ids)→NPUSlotManager`（L3，可 import L6）拿池——L2→L6 直 import 违分层（§1.1），工厂是 L3 解耦点。
- `run_cmd` 单算子分支：不建 pool（传 None 给 dispatch，card_context 兜底）。

## 4. NPURunner.execute 改造（L3 §2.4，主注入点 B）

- `execute(..., npu_id, ...)` → `execute(..., state, pool, ...)`（或保留 npu_id 参 + 增 pool，实施时定）。
- 内部：`with _card_context(state, pool) as card:` 包住 `subprocess.run([sys.executable, harness_path], env=run_env)`。
- 双层注入用领到的 `card`：env `ASCEND_NPU_ID=str(card)` + harness `set_device({card})` + `setdefault('ASCEND_NPU_ID', {card})`（三处用同一 card，L3 §1.1 一致性）。
- `with` 保证 subprocess 正常/异常/timeout 都还卡。

## 5. cannbench_eval._run_eval 改造（L3 §2.4，注入点 A）

- `_resolve_device_id(state)` → 改用 `_card_context`：`with _card_context(state, pool) as card:` 包住 `subprocess.run([... --device-id str(card) ...])`。
- 覆盖 cannbench_eval 的 NPU subprocess。

## 6. state.npu_id 语义变更（L3 §2.5）

- `state.npu_id: int = 0` → `npu_id: int | None = None`。§1.4 直接改，不留别名。
- Writers 同步：`dispatch`（`task_request.get("npu_id")` → None 默认）、`_build_state_for_stage`、`EntryStage.transition`。
- Readers：5 处中 4 处（cannbench_eval/perf/precision_debug/debug_service）改走 `_card_context`（不再直读 state.npu_id 喂 subprocess）；`ContextStage._build_run_context` 改记 preferred/hint（`state.npu_id` 可 None）。
- **pool 在 State 但不进 snapshot**：pool 是 State 瞬态字段（`card_pool: Any, repr=False, compare=False`，§3），但不序列化。`to_snapshot` 必须 `asdict(replace(self, card_pool=None))`——不能直接 `asdict(self)`：NPUSlotManager 含 `threading.Condition→RLock`（un-pickleable），`asdict` 深拷贝会先在 Lock 上 `TypeError` 再到 pop（`_workspace` 是 pickleable 故原 pop-after-asdict 能过，pool 不行）。`from_snapshot` 不恢复 card_pool（resume 重建池）。snapshot round-trip 验证 None/N 都正确（`test_state_snapshot_rebuild`）。

## 7. card_queue 消灭（L3 §2.6，§2.5 收口）

- 删 `batch_runner.run_batch` 的 `card_queue: Queue` + `_run_one` 的 `card_queue.get()/put()`。
- `run_batch`：建共享 `NPUSlotManager(allowed=card_pool)` → 传每个 `dispatch(task, card_pool=shared)`。run **不在入口领卡**。
- `_run_one` 退化为 `dispatch(task_item, card_pool=shared_pool)`（NPU subprocess 边界领/还）。
- 1 项退化路径同步：`_should_degrade` 仍直接 dispatch，但传 shared_pool（单卡池或探测）。
- **不留 card_queue 与 pool 并存**（§2.5）。

## 8. `design_concurrency` 语义升级（L3 §2.6）

- 阶段 1 run 级独占下 `concurrency > cards` 无吞吐收益；阶段 2 subprocess 级后**有真实收益**（多出 run 在 LLM 思考期不占卡、NPU stage 才领卡排队）。
- 参数名不变、语义自然放宽。docstring 注明（消歧 design 阶段，L4 `42` §0 已注）。

---

## 9. TDD 红→绿顺序

**Phase 1 — NPUSlotManager 扩展（UT 红）**：
- `test_acquire_blocks_when_empty_then_wakes_on_release`：池空 acquire 阻塞，另一线程 release 后唤醒（threading + Event）。
- `test_acquire_timeout_raises_card_acquire_timeout`：超时 raise `CardAcquireTimeout`。
- `test_acquire_context_releases_on_exception`：with 块 raise → `__exit__` 仍还卡（池恢复）。
- `test_acquire_context_releases_on_normal_exit`：正常退出还卡。
- `test_acquire_hard_pin_specific_card`：`acquire(npu_id=N)` 硬领 N。
- `test_allowed_subset_restricts_pool`：`allowed=[0,2]` → 只能领 0/2。
- `test_dead_card_warns_when_lease_exceeds_threshold`：领卡后 `acquired_at` 超阈值 + 池空 → warn（不强制回收）。

**Phase 2 — 实现 NPUSlotManager 扩展 + CardAcquireTimeout** → Phase 1 绿。

**Phase 3 — `_card_context`（UT 红）**：
- `test_card_context_hard_pin_yields_fixed_no_acquire`：`state.npu_id=N` → yield N，pool 未 acquire（`list_acquired()` 空）。
- `test_card_context_none_acquires_from_pool`：`state.npu_id=None` → acquire pool。
- `test_card_context_releases_on_exit`：with 退出还卡。

**Phase 4 — 实现 `_card_context`** → Phase 3 绿。

**Phase 5 — pool 注入 + dispatch（UT 红）**：
- `test_dispatch_builds_single_card_pool_when_none_passed`：单算子 `card_pool=None` → dispatch 自建池（state.npu_id 硬指定→单卡池；None→探测池）。
- `test_dispatch_uses_shared_pool_when_passed`：batch 传共享池，dispatch 用之不新建。
- `test_pool_carried_via_run_context_not_state`：pool 在 RunContext，不在 State/snapshot。

**Phase 6 — NPURunner.execute 改造（UT 红）**：
- `test_runner_acquires_card_from_pool`：`state.npu_id=None` + pool → execute 时 acquire，harness env/harness 收领到的 card。
- `test_runner_hard_pin_uses_state_npu_id`：`state.npu_id=N` → execute 用 N（pool 未 acquire）。
- `test_runner_releases_card_on_success_and_exception`：with 还卡（成功/异常）。
- `test_runner_double_injection_consistent`：env `ASCEND_NPU_ID` 与 harness `set_device` 同一 card。

**Phase 7 — cannbench_eval 改造（UT 红）**：
- `test_cannbench_eval_device_id_from_card_context`：`--device-id` 注入领到的 card（非 state.npu_id 常量）。
- `test_cannbench_eval_hard_pin`：`state.npu_id=N` → `--device-id N`。

**Phase 8 — state.npu_id Optional + card_queue 消灭（UT 红）**：
- `test_state_npu_id_default_none` / `test_state_npu_id_hard_pin`。
- `test_snapshot_roundtrip_none_and_int`：None/N 都正确 rebuild。
- `test_batch_runner_no_card_queue`：`run_batch` 无 card_queue，run 不入口领卡。
- `test_batch_shared_pool_subprocess_level`：2 task 共享 pool，NPU subprocess 各领各卡（mock dispatch 计 acquire/release）。
- `test_batch_hard_pin_task_skips_pool`：task npu_id=N → 该 task 用 N 不 acquire pool。

**Phase 9 — `--npu-id` 可用性（card 流到 spawn 边界，用户硬约束）**：

> **实施修正（2026-07-13）**：原计划「stub backend 真跑 dispatch 到 NPURunner subprocess.run 前」**不可行**——StubBackend（SDKBackend mock 不可用）按构造在 design gate 即 halt（`EX_DATAERR`，见 `tests/st/test_integration.py` / `tests/st/test_batch_e2e.py` 全部断 `EX_DATAERR`），**永不到达 verify/cannbench 的 NPU subprocess**。故 card→spawn 边界守护下沉到 **adapter/stage 级真实测试**（真 `NPURunner.execute` + 真 `_run_eval` + 真 `card_context` + 真 `NPUSlotManager`，只 mock OS 边界 `subprocess.run` 以捕 env/argv——这是「捕」非「mock 掉链路」，§3.9 真实链路守护成立，§3.5 无真 NPU 故不标 `npu`），归 UT（与既有 `test_cannbench_eval.py` mock subprocess.run 断 env 的约定一致，§3.8）。真 LLM 全流程 e2e（CLI→design→codegen→build→真 NPU 设备）属 heavy_llm，Phase 10 用户决策。

实际落地（4 例，全绿）：
- `TestNPURunner::test_npu_id_hard_pin_flows_to_subprocess_env_and_harness`（`tests/ut/adapters/test_adapters.py`）：`npu_id=2` + `card_pool=None` → card_context yield 2 不碰池 → subprocess env `ASCEND_NPU_ID="2"` + harness `set_device(2)`，池 `list_acquired()==[]`。
- `TestNPURunner::test_pool_acquire_flows_to_subprocess_env_and_releases`：`npu_id=None` + pool `[0,1]` → 领卡（∈{0,1}）→ env `ASCEND_NPU_ID=<leased>` + harness `set_device(<leased>)`，退出还卡（池满）。
- `TestCardDeviceIdInjection::test_hard_pin_flows_to_device_id`（`tests/ut/orchestration/test_cannbench_eval.py`）：`npu_id=3` → `--device-id 3`，不碰池。
- `TestCardDeviceIdInjection::test_pool_acquire_flows_to_device_id_and_releases`：`npu_id=None` + pool → `--device-id=<leased>`，退出还卡。

CLI→task_request 半段由 `tests/ut/cli/test_run_chip_flags.py::TestRunNpuIdFlag`（`--npu-id` 进 task_request、unset→None）+ `tests/ut/cli/test_cli.py::test_run_no_stubbed_flag`（`task["npu_id"] is None`）守护。dispatch→State→stage 半段由 `test_state_snapshot_rebuild`（npu_id Optional round-trip + card_pool 不进 snapshot）+ reader-wiring UT 守护。批跑编排（2 算子共享池、独立 Workspace、events.jsonl 自包含）由 `tests/st/test_batch_e2e.py`（非 heavy，stub dispatch）守护。

**Phase 10 — heavy_llm 决策（§3.11）**：候选 = 真 2 算子 `self_evolve_op` 批跑上真 NPU，验 subprocess 级领卡下卡池互不踩 + 各 run events 自包含 + `--npu-id` 真上设备。分钟级 + token。**执行前用户确认**（§3.11），未跑则诚实记录。

---

## 10. 验收 + heavy_llm 决策

- **UT 全绿**：`pytest tests/ut/ -m "not llm"` = **1925 passed**（0 failed）。含 stage-2 新增：NPUSlotManager 扩展（阻塞 acquire/acquire_context + 死卡告警）+ `card_context`（硬领/pool 领/None 兜底/release）+ dispatch `card_pool` 注入 + `--npu-id` 默认 None + State `npu_id:int|None` + `card_pool` 瞬态（snapshot rebuild/pickle 避崩）+ batch_runner card_queue 消灭（共享池线程化）+ **card→spawn 边界守护 4 例**（真 NPURunner.execute/`_run_eval`+card_context+pool，mock OS subprocess.run 捕 env/argv）。
- **非 heavy ST 全绿**：`test_batch_e2e`（2 算子共享池、独立 Workspace、events.jsonl 自包含）+ `test_integration`（dispatch plumbing）+ `test_self_evolution_stages` = **70 passed**。
- **`--npu-id` 可用性（用户硬约束，已满足）**：card 值从 CLI（`test_run_chip_flags`/`test_cli`）→ task_request → State（`test_state_snapshot_rebuild`）→ stage reader-wiring → **subprocess spawn 边界**（`ASCEND_NPU_ID`/`set_device`/`--device-id`，4 例真实断言注入值、非 mock 掉链路）全链路有真实测试守护。
- **heavy_llm（§3.11）—— 本次未覆盖**：候选 = 真 2 算子并发 `self_evolve_op` 批跑上真 NPU，验 subprocess 级领卡下卡池互不踩 + 各 run events 自包含 + `--npu-id` 真上设备（分钟级 + token）。**用户 2026-07-13 决策=不跑，留 PR 合并前关键节点再决策**（§3.11）。card→边界守护已由 adapter/stage 级真实 UT 承担（§3.9 真实链路守护成立）；真 LLM 全流程 e2e 为额外硬件置信度，非硬约束必需。
- **命名守卫**：`design_concurrency` 语义升级在 batch_runner docstring + L3 §2.6 注明。
- **P69 收尾（2026-07-14，3 项）**：① **CardAcquireTimeout 错误通道**——红测（`TestDispatcherCardAcquireTimeout`，mock `Runner.run_stage` raise）暴露：该异常原不在 `graph_executor._control_exceptions` 白名单 → 被 §P7.1 swallow 成 stage_failed → workflow halt → 误导性 `EX_DATAERR`+"implementation bug" 日志。修：白名单加入该异常（穿透到 dispatch，与 `EnvironmentNotAvailableError` 同类资源/control-flow 异常）+ dispatch except 链加 `except CardAcquireTimeout` 分支转 `EX_TEMPFAIL`（暂时性 back-pressure，非代码缺陷）+ 清晰重试日志 + `_preserve_repo_with_hint`（资源短缺不丢弃产物）（§3.4 可诊断性）。② **训练线 `--npu-id` 透传守护**——`TestNpuIdInjectedToSubprocessArgv`（2 例，直接调 `_run_subprocess`，mock OS `subprocess.run` 捕 argv 断 `--npu-id`/`str(card)`；None 则省略 flag）；§9「scheduling 顺带覆盖」原为未验证假设，现补盲区（§3.9）。③ **类型债**——`test_cannbench_eval.py` 旧 UT `npu_id="0"`（str）→`0`（int，签名 `int|None`）。UT 1928 passed（1925+A1+B2）、非 heavy ST 70 passed。

## 11. 实施顺序与依赖

Phase 1→2（pool 扩展）独立先行 → Phase 3→4（`_card_context`）依赖 pool → Phase 5（dispatch 注入）依赖 pool → Phase 6→7（NPURunner/cannbench_eval）依赖 `_card_context` + dispatch 注入 → Phase 8（state Optional + card_queue 消灭）依赖前述 → Phase 9（ST e2e）依赖全部。card_queue 消灭放在 Phase 8（最后收口），保证中间阶段 pool 与 card_queue 不长期并存（§2.5）。
