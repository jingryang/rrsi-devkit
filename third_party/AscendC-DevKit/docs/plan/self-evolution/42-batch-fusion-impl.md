# 批跑融合进 Python CLI — 实施方案（L4）

> **性质**：self-evolution 线 L4 符号级实施方案。承接 L3 `41-batch-fusion-analysis.md`（已冻结两阶段解耦 + 四项决策）。
> **范围**：仅阶段 1（批跑融合，run 级卡池）。不动 `state.npu_id` 语义、不动任何 stage、不动 `resolve_op_dir`/`dispatch`（复用）。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点写函数名不写行号、不照搬外部脚本、外部依赖只读）。
> **命名说明**：`design_concurrency` 指**批跑 run 级并发上限**（本地资源阀），非 pipeline 的 design 阶段并发；命名指向其终极语义（阶段 2 控制更多 run 并行 design/LLM 阶段），阶段 1 下先作安全阀。

---

## 0. 复用入口（已核实签名）

- `dispatch(task_request: dict, progress_callback: Callable | None = None) -> int` —— 返回 exit code；线程并发调用安全（每 run 独立 Workspace + `env=os.environ.copy()` 子进程级隔离，L3 §1.2）。
- `resolve_op_dir(op_dir, profile_override=None, repo_root_override=None, op_name_override=None)` → 返回带 `confidence/repo_root/profile_name/rel_op_dir/full_op_name/op_name/variant_name`；失败抛 `OpDirResolveError`。
- `Workspace.create(output_root, run_id)` → 每 run 独立目录（events.jsonl/state_snapshot/run.log 自包含）。
- NPU device count 探测：`verify_env` 已用 `torch_npu.npu.device_count()`（主）+ `npu-smi info -l`（torch_npu 不可用时兜底）；bounded 超时值复用 `runtime_config.hw_probe_timeout_sec()`。

## 1. manifest schema（wrapper）

```yaml
# 顶层 = 批跑级配置（全 optional，除 tasks）
cards: [0, 1, 2]            # 可用卡池；缺省走四级 fallback
design_concurrency: 4       # run 级并发上限；缺省=不设上限（全并发）
output_root: output         # 全局默认，任务项可覆盖
design_target_chip: A2      # 单算子公共默认，任务项可覆盖
tasks:                      # 每项 = 单算子 task_request（字段 1:1 = run_cmd CLI dest）
  - op_dir: /abs/path/opA
    requirement_path: /abs/path/req.md
    golden_path: /abs/path/golden.py
    golden_entry: opA
  - op_dir: /abs/path/opB
    npu_id: 1               # 硬指定该卡（须 ∈ 卡池，否则配置报错）
    requirement_path: /abs/path/reqB.md
```

**合并规则**（优先级低 → 高）：`run_cmd` 内置 default < manifest 顶层默认 < task 项字段。即 `task_request = {**run_cmd_defaults, **manifest_top_defaults, **task_item}`，再经 `resolve_op_dir` 补 profile/repo_root 等解析字段。

**校验**（加载期，§1.3）：tasks 非空；task 项非空 dict（至少一个字段——定位算子靠 `op_dir` 或 `target_repo`/`op_name`，与 run_cmd 一致、`op_dir` 非必填、运行期由 dispatch 校验）；per-task `npu_id` 若指定须 ∈ 最终卡池（卡池解析后校验）。未知字段告警降级 follow-up（需 run_cmd dest 集合，L2 不能 import L1，见 §2）。

## 2. 新增 `application/batch_runner.py`

函数骨架：

- `load_manifest(path: Path) -> BatchManifest` —— 解析 YAML + 加载期校验。
- `BatchManifest`（dataclass）：`cards: list[int] | None`、`design_concurrency: int | None`、`top_defaults: dict`、`tasks: list[dict]`。
- `resolve_card_pool(manifest: BatchManifest, cli_cards: list[int] | None) -> list[int]` —— 四级 fallback（见 §3）。
- `_probe_npu_card_count_bounded() -> int | None` —— 就地实现 thread-bound `torch_npu.npu.device_count()`（主）+ `npu-smi info -l` "Total Count" 解析（兜底），超时复用 `hw_probe_timeout_sec()`。**不提取共享 helper、不改 verify_env**：本探针职责=「拿卡数决策卡池」，verify_env._check_* 职责=「诊断面板条目」（且 _check_npu_device 现独立验 npu-smi returncode，改调 helper 会走 torch_npu 主通路、失去 npu-smi 独立诊断语义，反破坏诊断面板），detect.py 职责=「探芯片代际」——三者职责不同；§2.5 管「同一职责两套实现」，不管「`torch_npu.npu.device_count()` 底层 API 多处调用」（底层 API 多处调用如多处 `open()`，正常）。单一 API 即物理单一出口。thread-bound 5 行模式与 detect.py 重复，但抽成跨层 helper = 单消费者 + 跨层依赖，过度（avoid-overdesign），保留就地复制。
- `run_batch(manifest, card_pool, progress_callback=None) -> BatchResult` —— 主循环：
  - `card_queue = queue.Queue()`，初始化装入 `card_pool`。
  - `max_workers = manifest.design_concurrency or len(manifest.tasks)`（未设=全并发）。
  - `ThreadPoolExecutor(max_workers)` 提交每 task 一个 worker；worker 内：`card = card_queue.get()`（try）→ 组装 `task_request`（注入领到的 `npu_id`，除非 task 项硬指定）→ `resolve_op_dir` → `dispatch(task_request)` → `card_queue.put(card)`（finally，保证异常还卡）。
  - 汇总每 task 的 `(op_name, exit_code, run_id)` → `BatchResult`。
- `BatchResult`（dataclass）：`results: list[RunOutcome]`、`summary()`（成功/失败计数 + 每 run 日志路径）。

**1 项退化**：`run_batch` 检测 `len(tasks)==1` → 跳过线程池/卡池，直接同步 `resolve_op_dir` + `dispatch`（保留 L3「1 项无批跑开销」承诺，仍走 `dispatch` 唯一通路，§2.5）。

## 3. 卡池四级 fallback

`resolve_card_pool` 顺序：
1. `manifest.cards`（权威）→ 用之。
2. 缺 → `cli --cards` override → 用之。
3. 缺 → `_probe_npu_card_count_bounded()` → `list(range(n))`。
4. 探测失败/超时 → 抛 `ConfigError`（要求用户显式声明 `cards`，不静默退化到 0 卡或瞎猜）。

兜底是「尽力而为非权威」：探测给物理卡数，机器有别的任务占卡时用户应显式声明 `cards` 子集。

## 4. CLI 改动 `cli/commands/run.py` `run_cmd`

新增 options：
- `--batch`（type=click.Path(exists=True)，default=None）—— manifest 路径。
- `--cards`（multiple int 或 comma str，default=None）—— 卡池 override。
- `--design-concurrency`（int，default=None）—— 并发 override。

分支：`--batch` 传入 → `load_manifest` → 合并 cli override（`--cards`/`--design-concurrency` 覆盖 manifest 顶层）→ `resolve_card_pool` → `run_batch`；否则原单算子路径（`task_request` + `dispatch`，零改动）。

`--batch` 与单算子互斥 options（`--op-dir`/`--requirement` 等）的冲突处理：`--batch` 传入时忽略单算子 options 并告警（或 click 互斥组），实施时定。

## 5. 不碰清单（边界）

- `state.npu_id` 语义（run 级入口绑定不变）。
- 任何 stage（deploy/precision_debug/perf/cannbench_eval 零改动）。
- `resolve_op_dir` / `dispatch` / `Workspace`（复用）。
- 5 处 NPU subprocess 点的 env 隔离（不动）。

## 6. 线程安全核实（已结论）

`dispatch` 调用链有无**进程级可变全局**（`os.environ` 写、全局 dict/list 修改、模块级缓存写入）？静态 grep 核实（memory `verify-known-risks-statically`：30s 静态判定优先于运行期暴露）：

- **os.environ 写**：dispatch 调用链（`application/`+`orchestration/`+`capabilities/`）无 `os.environ[...]=` / `setdefault` / `putenv` / `update` / `pop`。5 处 NPU subprocess 点用 `env=os.environ.copy()` 子进程级隔离（不写全局）。
- **模块级可变全局**：`runtime_config._CONFIG/_ITER/_RAW/_REVIEW`、`dispatcher._NEW_PIPELINE/_USER_INPUT_FIELDS/_FIELD_HELP` 均为 import 时一次性加载的只读 dict/list/set，运行期无 `[...]=` / append / update / pop 写入。
- **run_id 唯一性**：`Workspace.create` 用 `uuid.uuid4().hex[:6]`+ts 生成 run_id（`infra/workspace.py`），uuid4 线程安全、并发唯一 → 每 run 独立目录无冲突。
- **bind_run_log（回归期补录，原 grep 漏项）**：dispatch 创建 workspace 时调 `infra/log_capture.bind_run_log`，它**改写进程级 `sys.stderr` + 模块级 `_BINDING`**（tee 控制台→`<run>/run.log`）。上述 grep 只扫「调用链逻辑」、漏了「日志副作用」——bind_run_log 不在那三类里。并发 dispatch 下 sibling 线程的 rebind 会 mid-write 关掉本线程的 `_Tee._file` → `ValueError: I/O operation on closed file`（非确定性、时序敏感，stub 路径下易被时序掩盖、全量回归才暴露）。根因修复：`_Tee.write` 把 file 写也纳入「logging 永不破坏 run」的 swallow 约定（原本只 swallow terminal 写），catch `(ValueError, OSError)`；并发回归 UT `test_concurrent_binds_do_not_crash` 守护（red 3/3 无修复 → green 有修复）。**并发下 run.log 内容是 best-effort**（控制台本就共享、输出交错），per-run 权威记录仍是 `events.jsonl`（per-Workspace、线程安全）。真正的 per-run 控制台分离（multi-sink _Tee / thread-local stderr）留阶段 2，本次不做（avoid-overdesign，阶段 1 只需「不崩」）。
- **顺带修复的测试污染**：bind_run_log 的 `_BINDING` 是 process-global、atexit 才拆，测试间残留 → 后续 CliRunner 捕获到 stale `_Tee._terminal`、`result.output` 变空（`test_resume_cli` 全量跑红、单跑绿）。原 UT 仅 `test_state_machine_dispatcher` 本地 autouse unbind 兜自己一个文件。修复：提升为 `tests/conftest.py` 顶层 autouse fixture（每 test 后 unbind，覆盖 UT+ST），删本地副本（§2.5 单一通路）。

结论（修订）：ThreadPoolExecutor 并发 dispatch **在补上 bind_run_log 的 swallow 修复后**安全。原「只读共享前提」结论不完整——`sys.stderr`/`_BINDING` 是可变进程级全局，但经 swallow 后并发下不再致命。Phase 5 ST（2 task 并发各创建独立 Workspace + events，`test_batch_e2e.py`）+ 全量回归（2000 passed）经验验证一致。

## 7. TDD 红→绿顺序

**Phase 1 — manifest + 卡池（UT 红）**：
- `test_load_manifest_wrapper`：解析顶层 cards/design_concurrency/output_root + tasks。
- `test_load_manifest_task_inherits_top_defaults`：task 项继承顶层 output_root/design_target_chip，只写差异。
- `test_load_manifest_per_task_npu_id_must_be_in_pool`：npu_id=5 但 cards=[0,1,2] → ConfigError。
- `test_load_manifest_unknown_field_warns`：未知字段告警（不静默）。
- `test_resolve_card_pool_manifest_authoritative`：manifest.cards > cli > probe。
- `test_resolve_card_pool_cli_override`：无 manifest.cards，cli 覆盖。
- `test_resolve_card_pool_probe_fallback`：mock 探测返 N → pool=[0..N-1]。
- `test_resolve_card_pool_probe_failure_raises`：mock 探测超时/失败 → ConfigError。
- `test_manifest_to_task_request_mapping`：字段 1:1 = run_cmd dest + 合并优先级。

**Phase 2 — 实现 `batch_runner.py`**（manifest schema + resolve_card_pool + _probe_bounded 复用）→ Phase 1 绿。

**Phase 3 — 并发执行 + 退化（UT 红）**：
- `test_card_pool_get_put_normal`：领/还。
- `test_card_pool_release_on_exception`：worker 抛异常，finally 仍还卡（池恢复）。
- `test_batch_single_task_degrades_to_sync_dispatch`：1 项不起 ThreadPool、不领卡，直接 dispatch。
- `test_batch_design_concurrency_sets_max_workers`：design_concurrency=N → max_workers=N（mock dispatch 计并发数）。
- `test_batch_no_design_concurrency_full_parallel`：未设 → max_workers=len(tasks)。
- `test_run_cmd_batch_branch`：`--batch` 传 → 走 batch_runner；不传 → 原路径（单测 click runner）。

**Phase 4 — 实现 CLI `--batch` 分支 + 退化**→ Phase 3 绿。

**Phase 5 — ST 红**：
- `test_batch_two_ops_e2e_stub`：2 task（StubBackend），并发跑，2 卡池各分 1、各自 exit code 汇总 + 各 run 独立 Workspace/events。不标 llm（stub 确定性）。
- `test_batch_one_op_degrades_e2e`：1 task 走退化路径端到端。

**Phase 6 — ST 绿**（可能需 StubBackend 并发支持核实）。

## 8. 验收 + heavy_llm 决策（状态：阶段 1 已交付）

- **UT 全绿**：batch 新增 27 例（`test_batch_runner`）+ 5 例（`test_run_batch` CLI）+ 1 例并发回归（`test_log_capture::test_concurrent_binds_do_not_crash`）。
- **全量回归绿**：`pytest tests/ut tests/st -m "not llm and not heavy_llm"` = **2000 passed / 3 skipped / 0 failed**（含 conftest 每-test unbind 修复的 `test_resume_cli` 污染 + log_capture 并发竞态修复）。
- **非 heavy ST 绿**：`test_batch_e2e` 2 算子并发 stub 端到端（独立 Workspace + events 全生命周期）+ 1-task 退化。
- **线程安全**：§6 已补录 bind_run_log 发现并修复（swallow file I/O + 并发回归 UT）。
- **heavy_llm（§3.11）**：本特性 stub ST 不依赖真 LLM。heavy 候选 = 真实 2 算子并发 `self_evolve_op`（并发下 LLM+NPU 链路 + 卡池互不踩 + 各 run events 自包含），分钟级 + token。**本次未跑**（§3.11 用户决策），留 PR 前决策；若跑，按 §3.4 失败必修根因。
- **命名守卫**：`design_concurrency` 语义在 `batch_runner.py` docstring + L3 注明（消歧 design 阶段）。

## 9. 与阶段 2 的接口预留

阶段 1 完成后，`design_concurrency` 参数已就位（阶段 2 升级为吞吐阀不用改名）、卡池 `queue.Queue` 已就位（阶段 2 改领卡时机为 subprocess 级）。阶段 2 立项时改的是「领卡时机」（run 入口绑定 → 5 处 NPU subprocess 边界按需领/还）+ `NpuCardPool` 能力下沉 L5，不动 manifest/CLI 形态。口径以 L3 §1.3/§2.3 为准：**subprocess 级**（起 CANN/eval 子进程那一刻领卡、结束即还），非 stage/action 级——`precision_debug` 一 action 内 LLM+NPU 混合，stage/action 级会把 LLM 思考期也算进占用。
