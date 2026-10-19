# Issue: State.to_snapshot 启动即崩 `'State' object has no attribute 'reference_roots'`（反复出现）

**Date:** 2026-08-10
**Status:** 根因已定位（2026-08-28 深夜段：主进程内 torch_npu import 三向量）；修复已实施（step-104，2026-08-29，`docs/plan/dispatch-npu-probe-subprocess/`）——maps 验收已过（0 映射区/零塌缩），批实测待跑后关闭
**Trigger run:** `scripts/batch_self_evolve.sh` 首跑（worktree `cann-bench-batch/20260810_005800`，6 算子 gelu / grid_sampler_3d / group_norm / resize_bilinear / transpose / unique）
**Log:** `logs/batch_20260810_005800.log`
**Tag:** 启动即崩 / dispatch 期崩溃 / 概率性（用户反馈该问题已反复出现多次）

## 现象（客观事实）

- `ascendc-devkit run --batch manifest.yaml` 派发首个算子（gelu）时，dispatch 抛 `AttributeError` 崩溃：
  - 报错签名：`AttributeError: 'State' object has no attribute 'reference_roots'`
  - 崩溃调用链（日志原文）：
    ```
    dispatcher.py:838  dispatch → _write_state_snapshot(workspace, state)
    dispatcher.py:2151 _write_state_snapshot → state.to_snapshot()
    state.py:440        to_snapshot → asdict(replace(self, card_pool=None))
    dataclasses.py:1496 replace → changes[f.name] = getattr(obj, f.name)
    AttributeError: 'State' object has no attribute 'reference_roots'
    ```
- 崩溃只打在该算子 dispatch 记录里（`dispatch failed for .../gelu/...`），batch runner 未整体退出，其余算子继续并发派发。
- `State` dataclass 声明了 `reference_roots: list[str] = field(default_factory=list)`（`state.py:80`），
  但 `dataclasses.replace(self, card_pool=None)` 遍历字段做 `getattr(obj, 'reference_roots')` 时，该实例缺此属性。

## 伴随观测（同一运行，客观事实）

- 同一批 dispatch 的 preflight 阶段出现**交互式追问**并报缺必需输入：
  - 日志出现 `[preflight] 请输入 golden_path（留空跳过）: / 请输入 requirement_path（留空跳过）: / 请输入 golden_entry（留空跳过）: / 请输入 golden_input_type（留空跳过）:`
  - 随后 `[ERROR] 缺少必需的用户输入，无法启动工作流 'self_evolve_op'（mode=new）：- golden_path / - requirement_path / - golden_entry / - golden_input_type`
  - 而 manifest（`cann-bench-batch/20260810_005800/manifest.yaml`）每 task 已显式提供 `requirement_path` / `golden_path` / `golden_entry` / `golden_input_type` 字段。

## 复发记录

### 2026-08-27 晚：受控实验 + 静态穷举 + 埋点（根因未定位，机制边界已收窄）

- **受控实验（batch 20260827_crashexp，21:00）**：两个从未执行过的算子
  （logcumsumexp_custom / take_along_dim_custom，level2，worktree 预建 + 手工拷入
  untracked task 输入）并发首拉——**未复现**。两算子 preflight 全过、正常进入
  requirement 阶段（tr 完整，无 WARN/prompt 模式）。「新算子首拉」本身不是充分条件；
  与 0827 上午对照（unique 崩 / moe_re_routing 存活 / 实验批 2 算子均存活），崩溃为
  概率性，且两次已知复发均伴随「tr 读值与实传入不符」（preflight 报缺 manifest 已
  提供的四字段 + WARN 三个 resolve 必回填字段，而异常打印 `tr.get("op_dir")` 有值）。
- **静态穷举结论**：崩溃实例在 `dispatcher.py` dispatch() L762 经完整 dataclass
  `__init__` 构造（`reference_roots` 显式传参）→ L836 非交互/EOF prompt 路径返回同一
  对象 → L838 崩「缺属性」。全程无 try/except、无对象换绑、仓内无 `__dict__`/
  delattr/`__dataclass_fields__` 变异点、无重复模块身份、无 stdlib 遮蔽（CANN
  PYTHONPATH 已查）、.pyc 与源码行号一致、单线程与 4 线程冷启动合成复现均不崩。
  **现行源码纯 Python 语义下该崩溃不可产生**——存在解释器层之外的未知机制。
- **已落埋点**（定位后删除）：`dispatcher.py` `_log_state_integrity()`（探针字段
  run_id/non_interactive/target_repo/reference_roots/design_target_chip/op_name/
  golden_path/task_request）挂四处：dispatch 入口（tr id+keys+thread）、State 构造后
  （always 记 id+字段数）、`_preflight_user_inputs` 入口、`_write_state_snapshot`
  入口（健康零输出）；`batch_runner.py` `_dispatch_one` dispatch 调用前记 tr keys。
  判别假设：① 构造即坏（constructed 已 missing）② 构造后变异（constructed ok、
  snapshot-write missing、id 相同）③ 对象被换（id 不同）。下次复发时四点位输出直接
  定机制层。

### 2026-08-27（batch 20260827-120152-1ae227）

- 同签名复发，本次崩于 `unique`（首次 dispatch 即崩）；同批另一算子 `moe_re_routing` 正常派发并运行。
- 崩溃链与 20260810 完全同形（行号漂移）：`dispatcher.py:838 → :2174 _write_state_snapshot → state.py:457 to_snapshot → dataclasses.replace → AttributeError: 'State' object has no attribute 'reference_roots'`。
- 崩前零落盘：execution 目录 `output/20260827-120152-1ae227/20260827-120152-e81b85/` 仅有空 `artifacts/`、`subprocess/`、`agents/` 与 run.log，**无 events.jsonl、无 state_snapshot.json**。
- 伴随现象复现（与 20260810 一致）：unique 的 run.log 出现 `[preflight] 请输入 golden_path/...` 交互追问 + `[ERROR] 缺少必需的用户输入`（golden_path / requirement_path / golden_entry / golden_input_type）——而 manifest 每个 task 均显式提供了这四项；同批 moe_re_routing 的 preflight 正常。**输入未到达该 dispatch 的 preflight 与 State 崩溃同发于同一次 dispatch**。
- 本批另观测：manifest 校验 loud-fail 3 算子（interpolate_custom / mse_loss_cross_entropy_loss_custom / upsample_custom，`missing_task_files`——worktree 检出 HEAD 不含 cann-bench untracked task 目录），属 §1.3 加载期校验按设计工作，与本 issue 无关。

### 2026-08-28 深夜：埋点判别出结果（假设②成立）+ 进程原生暴露面实证 + 新形态整进程 SIGSEGV

- **埋点判别（假设②「构造后变异」成立）**：两例（batch `20260828-133112-54af2d/...43b694` 21:31、
  复现批 `20260828-150701-847fd3/...1acbb6` 23:07）均打出完整四点位：
  `constructed fields=124 ok` → `preflight-enter fields=2 / fields=20 missing=[8探针字段]` →
  `snapshot-write fields=同preflight`，**id 相同、type 相同、同一线程**。同一实例的 `__dict__`
  在构造返回后、进 preflight 前的亚秒级窗口内从 124 项塌缩为 2/20 项（两次批次数值不同，
  排除固定 20 字段类；`in` 检查对已设键返回缺失 = 键表本体错误，非 len 计数错）。
  「preflight 报缺 manifest 已提供四字段」的伴随症状同源：State 被掏空，preflight 读到全缺省。
- **新形态 F3（整进程 SIGSEGV，exit 139）**：23:00（batch `20260828-150048-413945`）与
  23:03（`20260828-150316-5b5a38`）两次 `run --batch` 均在 3 execution 全部 `constructed ok`
  后 1-2 秒整进程段错误，0/3 物化。23:07 faulthandler 复现批未段错误、命中 F1（1/3）。
  与 F1 并案推定：同一原生级破坏，打击烈度不同（轻=字典塌缩，重=进程段错误）。
- **主进程原生暴露面实证（/proc/pid/maps）**：真 CLI `run --batch`（CHIP 未设）主进程
  t=3s 即 map `torch/_C.cpython-311-aarch64-linux-gnu.so` 等 **418-460 个 Ascend|torch 映射区**，
  线程数 **73**（本进程自有 3 个 dispatch 线程 + ThreadPool，其余为 torch OMP/CANN/driver 线程）。
  注入路径共**三处**：`adapters/npu/detect.py:75`（`_probe_chip_blocking` 子线程内 import，
    dispatcher.py:781→588 调用；**runtime probe 无条件执行**——design_target_chip 仅携带 CLI 值，
    runtime 侧"probe authority"恒探测，故设 CHIP 也绕不开，2026-07-01 85308e70 引入）；
  `adapters/npu/slot.py:79`（NPUSlotManager 探卡数，env 未设 ASCEND_NPU_COUNT 时兜底 import，
    2026-05-28 引入）；`infra/provenance.py:283/326`（`_npu_device_count`/
  `_probe_torch_npu_version` 主进程 import，经 `dispatcher.py:982/1007 build_provenance` 调用，
    位于 preflight→snapshot 的 F1 崩溃窗口内）。环境：torch 2.10.0+cpu + torch_npu 2.10.0.post4 + CANN 9.1.0-beta.3。
  dispatch-enter→constructed 间稳定的 ~7s 间隙 = probe 子线程 import torch_npu 耗时。
- **旁证**：`/root/.local/lib/python3.11/site-packages/sitecustomize.py`（2026-08-21）注释自述
  本机既往病史「CANN library loading triggers SIGSEGV (-11)」。
- **排除项（2026-08-28 夜取证）**：仓内无 `__dict__` 交换/改写；全仓无 ctypes；引擎 dispatch 窗口
  代码全纯 Python（Logger/log_capture 无原生操作）；yaml 全部走 `safe_load`（纯 Python
  SafeLoader，libyaml .so 虽被 import 但不执行解析）；NPU smoke 为干净子进程（无 preexec_fn）；
  无 `/etc/ld.so.preload`、无 LD_PRELOAD、无 greenlet/gevent；独立合成压测（6 线程 × 81498 次
  124 字段 frozen dataclass 构造+校验+asdict/replace+并发文件日志，90s）零塌缩零段错误。
- **与 22:56 e17e62da（registry 双检锁）的关系**：非因果。修复前并发线程死于导入链早期
  ImportError（21:12 批 5/6，掩盖更深层暴露）；修复后线程存活至原生损坏窗口，F3 才得以显现。
- **第四向量（2026-08-29 验证批实证，已修）**：step-104 守卫在批 20260829-024316-f0252f
  upsample_custom exec 拦下主进程 `import torch`——codegen 尾段 smoke harness 生成
  （`runner._build_test_harness(rule=None)`）lazy import `precision_compare` 拿
  `merge_thresholds`，而该模块顶层 `import torch`；同形态另有 `runner.execute` 与
  `precision_debug.py:66` 两处。修复 = 阈值核心上移 `domain/precision.py`（torch-free），
  三处改模块级域层 import。详见 `docs/plan/dispatch-npu-probe-subprocess/02-impl.md`。
- **第五向量（静态清点，2026-08-29 发现，未触发未修）**：`NPURunner.__init__` 构造期
  `_check_environment`（`adapters/npu/runner.py:400/406`）进程内 `import torch`。全仓
  构造点三处：`_common.py:139`（run-cases 子进程，合法）；**`orchestration/stages/perf.py:123`**
  （PerfGate 测量，主进程构造且在 try 外——触发即 stage 报错）；**`perf.py:179`**
  （`_check_npu_available`，主进程构造且包在 `except Exception` 里——守卫错误会被
  **吞掉、静默判 NPU 不可用**，§1.2 可诊断性违规最恶劣形态）。self_evolve_op 工作流
  无 perf stage 故本批未触发；属 devkit 单算子工作流潜伏向量。

## 已确认的代码位置（仅定位，不含分析）


- `src/ascendc_devkit/orchestration/kernel/state.py:440`（`to_snapshot`）
- `src/ascendc_devkit/application/dispatcher.py:2151`（`_write_state_snapshot`）、`:838`（`dispatch`）
- `src/ascendc_devkit/orchestration/kernel/state.py:80`（`reference_roots` 字段声明）
- 用户反馈：此「启动即崩」问题已出现多次，属反复出现的概率性问题。
