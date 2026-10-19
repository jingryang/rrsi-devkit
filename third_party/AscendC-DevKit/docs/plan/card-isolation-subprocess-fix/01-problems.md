# L1 问题记录 — P69 card 隔离在 CLI subprocess 路径失效（step-90）

> 原始记录：`docs/plan/self-evolution/batch-20260802-171400-issues.md` P1（2026-08-02 实测
> pool-acquire 模式并发算子挤 device 0）。本文件补 2026-08-25 调研后的机制事实。用户拍板：
> 非 A5 独有问题必须修（2026-08-25）。

## P1：CLI subprocess 看不见内存池——pool 模式下 NPU 工作全部落 device 0

**现行机制（设计意图，工作正常的一半）**：
- batch 建 shared `NPUSlotManager`（`build_shared_card_pool`），卡在**每个 NPU 子进程边界**经
  `card_context`（adapters/npu/card_context.py）acquire/release——run 的 LLM 思考段不占卡，
  其他 run 的 NPU 子进程可复用（batch_runner.py:383-388 设计声明）。
- task 显式 `npu_id` = hard-pin，不碰池。
- **in-process 边界已闭环**：`NPURunner.execute`（runner.py:529）与 `cannbench_eval`（scorer:111）
  都走 `card_context(npu_id, card_pool)` 单决策点。

**缺陷（另一半）**：CLI subprocess 进程内没有池（`State.card_pool` transient，快照 pop——
state.py:458），于是：
- `redeploy` CLI → Deployer smoke：`card = state.npu_id if state.npu_id is not None else 0`
  （deploy.py，**自旁路 card_context 单决策点**）；
- `run-cases` CLI → `run_precision_cases(op_spec, cases, state.npu_id, ...)`（debug_service.py:265）
  → `execute(npu_id, card_pool=None)` → `card_context(None, None)` → **yield 0**（card_context
  的 standalone 兜底——但 CLI 批跑场景并非 standalone）。

**后果**：pool-acquire 模式（task `npu_id=None`）下，precision_debug 的 redeploy/run-cases/
diagnose build/test 全部落 device 0，与框架进程内已正确隔离的边界（deploy/perf/eval）不一致；
并发算子挤卡（2026-08-02 06:17 实测）。

## P2：四类"只修一处"的半成品形态（每个都比不修差）

| 只修 | 失败方式 |
|---|---|
| 把分配卡持久化进 state 快照 | 卡被钉住整个 run 生命周期，破坏"LLM 段不占卡"池共享设计（并发可用卡减少） |
| 只在框架 spawn 时导出 ASCEND_NPU_ID | 无效——deploy.py/runner.py 覆写 `env["ASCEND_NPU_ID"]` |
| 只把 CLI 改成尊重继承环境 | 无效——batch 模式下没人导出过该环境变量 |
| 全修但不定义释放 | diagnose 会话全程持卡无释放 → 泄卡/并发回归 |

## P3：SpawnAgent/backend 环境注入是架构级障碍（调研事实）

opencode backend 的 agent Bash 子进程运行在 serve 进程树内，进程 env 在 serve 启动时固定；
per-round 卡分配无法经进程 env 注入既有 serve——SpawnAgent 加 env 字段需两 backend 手术，
面积大且与 serve 生命周期耦合。

## 边界

- A5 侧同病（precision_debug_a5.py:468 `state.npu_id or 0`）属同事产权，不动 A5 代码；
  共享层（card_context/deploy.py）修复对 A5 CLI 调用自动受益。

## P4：租约写 control.json 抢跑 init-checkpoint（step-90 实施回归，2026-08-26 发现）

**现象**（run 20260825-153847-ccad38）：run_tests 入口即
`[WARN] [PD-CONTRACT] control.json missing 16 required key(s) ... Auto-initializing to safe defaults`，
且首轮 init-checkpoint.py 未执行。

**机理**：`_acquire_card_lease` 在 actions() 开头把 `{"card_lease": N}` 落盘为 control.json
（`_load_control` 对缺失文件返回 `{}`，`_save_control` 无条件写）——而 control.json 的
**存在性**是首轮 init-checkpoint 的双重闸门（`_build_measure_command` 的 Python 侧
`ctrl.exists()` 决定 init 段是否进命令 + bash `[ -f ] ||` 兜底）。文件被提前创建后：

1. init-checkpoint 被跳过 → 16 个必需键缺失（触发 `_ensure_control_contract` WARN 与
   safe-defaults 自愈）→ config 种子值（max_iterations/time_budget/harness_timeout 等）
   静默换成 safe defaults；
2. `_common_context` 读到只有 card_lease 的文件，同样触发 WARN（01:58:55 实证）。

该 run 靠 defaults 恰好可跑（30/36000 与 config 同值）未造成后果，但契约闸门被绕过是
确定性缺陷。处置见 `03-impl-card-lease.md` as-built 追加；方案取舍见
`../precision-clean-exit-false-failure/02-analysis.md` 边界节。
