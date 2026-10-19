# 硬超时与优雅退出 — L3 方案分析（2026-07-25）

> 层级：**L3 / 方案分析**。只陈述「有哪些选项、选了哪个、为什么」。
> 调研中演进、拍板后**冻结**。问题记录见 `01-problems.md`（L1）；实施方案见 `03-impl-*.md`（L4）。
>
> 上游依赖：本方案**复用** `stage-timeout-granularity/` 已建的软超时**检测层**（per-stage deadline + Option A 软放过），只补**执行层**。
> 泛化来源：`precision-debug-agent-abort/` 的中断善终场景，本方案将其提炼为通用机制。

---

## 一、总原则：检测层复用，执行层新增

现有 deadline 机制（`runtime_config.timeouts` + `runner._check_timeout` + Option A 软放过，源自 `stage-timeout-granularity`）是**检测层**，完备且不动。本方案只补**执行层**——让 deadline 在「卡死在 spawn 里」时也能兑现。

```
                ┌─ workflow_deadline ─┐
deadline 来源 ──┤   (stage-timeout    ├─→ runner 算剩余 ─→ spawn(deadline_monotonic=剩余)
                └─  -granularity 建) ─┘                         │
                                                                  ├─ iteration 边界: _check_timeout 照常检查（检测层，不动）
                                                                  └─ 卡在 spawn 里:    backend 硬墙到点杀掉（执行层，新增）
```

**同一个 deadline，两个执行点**。硬墙不引入新超时配置，只把现有 deadline 的剩余预算传进 spawn 内部。所以**不是「软超时改成硬超时」**，而是「给 deadline 装上牙齿，让它在任何时候都能兑现」。

---

## 二、分层架构

| 层 | 机制 | 解决的问题（L1 问题） |
|---|---|---|
| **L5 backend 执行层** | spawn 加 `deadline_monotonic` → 内部硬墙（claude A / opencode 接线） | P1（spawn 期间无中断点）、P2（claude 无硬终止） |
| **L5 信号层** | `AgentResult.aborted` 字段 | 让 stage 区分硬终止 vs 普通失败（支撑 L3 teardown） |
| **L3 stage 善终层** | `Stage.teardown()` 可重载钩子 + `Stage.uninterruptible` 声明 | P3（无通用善终）、P5（cann-bench 丢结果） |
| **L2 全局退出层** | SIGTERM handler + 进程组(killpg) + atexit 兜底 | P4（SIGTERM 不优雅、子进程孤儿） |
| **收口** | `_generate_report` 纳入 finalize teardown，删 dispatcher 手写调用 | P3 的 §2.5 债 |

---

## 三、关键决策（选项 / 选择 / 理由 / 证据）

### D1：claude SDK backend 的硬终止写法 —— 选 A（anyio.fail_after 包整个 _spawn）

**演进路径**（记录调研中为何从 B' 改判 A，含最初误判的修正）：

| 候选 | 写法 | 结论 |
|---|---|---|
| **A（选定）** | spawn 层 `anyio.run(_timed)`，`_timed` 内 `anyio.fail_after(剩余)` 包整个 `await self._spawn(...)` | cancel 取消整个 `_spawn` task；`_spawn` 主体**零改动**；anyio cancel scope 是 SDK `transport.close()` shield 认的取消方式 |
| ~~B'~~ | `ClaudeSDKClient` async-with + `asyncio.timeout` 打断 receive 循环 | 需把整个 `_spawn` 从 `query()` 函数式迁到 client 上下文；且 `receive_messages` 流式不自然停（见下）→ 大改 working code，风险高 |
| ~~C：asyncio.wait_for~~ | `asyncio.run` + `wait_for` 包 query | probe 证伪（见下） |
| ~~D：subprocess 化~~ | claude spawn 整体跑子进程 | 破坏 in-process 不变式，改动过大 |

**为何从 B' 改判 A**（最初选 B'，深 probe 后改判）：

1. **B' 的隐藏代价**：B' 要求 `_spawn` 从 `query()` 函数式（`async for in query()`）迁到 `ClaudeSDKClient` 上下文（connect / query / `async for in receive_messages()`）。但 probe 发现 **`receive_messages` 是流式模式，收到 `ResultMessage` 后不停止**（CLI 不退出，等下一条 query）——即 receive 循环没有自然终止点，仍需自己包中断逻辑。同时 stall / resume / 429 / sidecar / transcript 全部是绑在 `query()` 事件流上的成熟代码，迁到 client 上下文 = 重写整个 `_spawn` 核心，风险与回归面都大。
2. **最初否 A 的两条理由都站不住**（实测修正）：
   - 「引入 anyio 第三方依赖」→ **伪命题**：anyio 已是 `claude_agent_sdk` 的传递依赖（SDK transport 内部用 `anyio.open_process` / `anyio.CancelScope`，见下证据 1-2）。环境已装 anyio-4.14.1（pytest plugins 列表可见），零新增依赖。
   - 「需 `asyncio.sleep`→`anyio.sleep` 全替换」→ **伪命题**：`anyio.run` 跑的是 asyncio backend，原生 `asyncio.sleep` 照常工作，**无需替换**。实测 `_spawn` 的 429 backoff 仍用 `asyncio.sleep`，UT（test_session_resume 3 个 429 用例）全绿。
3. **A 是最小改动 + 最低风险**：硬墙是 spawn 入口的薄 wrapper（`anyio.run` + `fail_after`），`_spawn` 主体一行不动 → 不碰成熟逻辑、无回归面。B' 反而是大改核心。

**关键技术证据（probe claude_agent_sdk 0.2.x / 2.1.202）**：

1. claude SDK 默认 transport 是 `SubprocessCLITransport`（client.py:191），`anyio.open_process` 拉起 `claude` CLI 子进程；句柄在 `transport._process`（subprocess_cli.py:128）。
2. `transport.close()`（subprocess_cli.py:624）跑在 `anyio.CancelScope(shield=True)` 内，有完整 escalation：关 stdin（让 CLI flush session 文件）→ wait 5s → `terminate`（SIGTERM）→ wait 5s → `kill`（SIGKILL）。**这就是「秒级优雅退出 + 保 session 可 resume」的现成原语。**
3. **关键 caveat（subprocess_cli.py:641-650）**：shield **只防 anyio cancel scope 的取消；raw asyncio cancel（`asyncio.wait_for` / `task.cancel()`）会穿透 shield**，让 escalation 的 `except TimeoutError` 漏掉，CLI 子进程只能靠 atexit 兜底（进程退出时才杀）→ 孤儿。**这证伪了 C。**

**A 为何成立**（恰好踩在 shield 认的取消方式上）：

```python
def spawn(self, ..., deadline_monotonic=None):
    async def _timed() -> AgentResult:
        coro = self._spawn(...)                 # 主体零改动
        if deadline_monotonic is None:
            return await coro
        with anyio.fail_after(剩余):            # anyio cancel scope
            return await coro
    try:
        return anyio.run(_timed)                # asyncio backend
    except TimeoutError:                         # 到点：cancel 已结束才抛
        Logger.warn("hard timeout")
        return self._build_result(..., aborted="hard_timeout")
```

- C 失败的本质：raw asyncio cancel 穿透 shield，close() escalation 漏跑 → CLI 孤儿。
- A 成立的本质：**anyio cancel scope 正是 shield 认的取消方式**（caveat 3 的「防 anyio cancel scope 的取消」），到点 cancel 整个 `_spawn` task → 流式 query 的 await 点抛 CancelledError → SDK 内部 `__aexit__`/disconnect 跑 `transport.close()`，此时 fail_after 的 cancel 已转入 `TimeoutError` 路径、shield 正常生效 → SIGTERM/SIGKILL escalation 正常跑完。

**改动面**：仅 spawn 入口加 `_timed` wrapper（~15 行）；`_spawn` 主体零改动。`asyncio.sleep`（429 backoff）保留不动。

**可 resume 保证（构造性）**：close() 先关 stdin 让 CLI flush session 文件（subprocess_cli.py:686 注释「避免 SIGTERM 中断 session 写入丢失最后消息 #625」）+ sidecar 在 session_id 捕获瞬间已落盘（sdk_backend.py）+ crash 时不清除（`if not crashed: clear`）。硬终止场景 consumer 随 `_spawn` 栈丢失，session_id 靠 sidecar 保留 = 构造性 resume 保证。

**SLA**：close() 内每个 await 都有界（subprocess_cli.py:634 注释「~20s worst case」），故硬墙触发后 ≤~20s `anyio.run` 必返回（通常 CLI 收 stdin EOF 秒级退出）。

---

### D2：opencode backend 硬墙接入 —— 复用已有机制，接外部 deadline

opencode 已有 per-spawn 硬墙（`_post_message_watched` keepalive + `_stop_serve`，P-BC3）。改动仅：spawn 入口取 `min(剩余 deadline, self._message_timeout)` 作为本次 `message_timeout`。**核心机制已存在，只接外部 deadline。**

两 backend 共享：`spawn(deadline_monotonic)` 协议契约（到点必返回）+ 同一种优雅退出语义（SIGTERM→SIGKILL，殊途同归）+ 同一个收口（crash-salvage `_build_result` + sidecar 保留）。**协议统一、实现分化**（opencode 我们直接 kill proc；claude 触发 SDK close escalation）——符合 §1.6/§2.5，不强行统一物理实现。

---

### D3：软/硬切换 —— 默认硬，env escape hatch，无正式「软模式」

| 维度 | 控制 | 状态 |
|---|---|---|
| 计不计时 | `--stage-timeout` / config `timeouts.*`（0=不计时） | 已有（stage-timeout-granularity） |
| 硬墙开/关 | 默认**开**；`ASCENDC_NO_HARD_KILL=1` env 临时退回软 | 新增 |

**不给正式 config/CLI 软模式开关**的理由：硬墙纯收益（没超时不触发，零副作用），该是唯一通路（§2.5）。给正式「软/硬切换」会让用户困惑且留两条通路长期并存 = 债。软行为只配做调试 escape hatch（观察卡死现场 / attach debugger / 灰度）。

迁移期如需灰度，用限时 config 开关（`timeouts.hard_kill`），**验证稳定后删除**（§1.4 不留过渡层）。

可观测：spawn 时 events 记 `hard_kill_enabled: true/false`，事后能区分「硬墙该杀没杀（被关了）」vs「硬墙杀了」（§1.2 可诊断）。

---

### D4：硬终止信号 —— `AgentResult.aborted` 字段

```python
@dataclass(frozen=True)
class AgentResult:
    ...
    aborted: str | None = None   # None=正常；"hard_timeout"/"cancelled"/"keepalive"=被硬终止
```

取代文本匹配（现状只能靠 `failure_reason` 文本，stage 区分不出硬终止 vs 普通崩溃）。backend 硬墙触发处各填一处（claude A 的 `except TimeoutError`、opencode 的 `_KeepaliveAbort`）。runner 额外 emit `agent_aborted` event（审计）。

---

### D5：teardown 钩子 —— Stage 可重载的「被中断时收尾」（finally 语义）

**演进**（记录语义纠正）：初版误把「teardown」当「中断后补跑必达 stage」；用户澄清后对齐为软件工程标准含义——**stage 被硬超时中断瞬间的收尾钩子**（类比 `try: actions() finally: teardown()`、context manager `__exit__`、pytest tearDown）。

```python
class Stage:
    def teardown(self, state, *, interrupt_reason: str) -> State:
        """被硬超时/中断时的收尾钩子。默认 no-op。stage/substage 重载做善终。
        best-effort：失败不阻塞退出。interrupt_reason 见 D4。"""
        return state
```

- **由 stage/substage 自己重载**（和 `actions`/`transition`/`gate` 一样，领域知识下沉，主流程只调度，§1.6/§2.7）。
- 触发点：runner 在 spawn 被硬墙杀（`aborted != None`）后、stage 返回前调用。
- 例子：precision-debug fix substage → `git reset --hard best_commit`（回退最后可用版本）；codegen → 清理 half-written 临时文件；cann-bench → 关 subprocess。
- **与构造性保证互补**（§2.9）：构造性保证（ok 才 commit/采用）自动覆盖「不留半个产物」；`aborted` 是信号；`teardown` 是 stage 主动的显式善终（覆盖构造性管不到的脏改动/资源清理）。
- **budget**：teardown 是秒级收尾（git reset、删文件、flush），默认 60s 绰绰有余。重型操作（cann-bench 评测）不进 teardown，走 D6。

---

### D6：cann-bench「硬超时也走完」—— `uninterruptible` 声明（不是 teardown）

**演进**：初版把 cann-bench 也塞进 teardown（补跑），被两个事实否决：① cann-bench 评测自身分钟～30min（cannbench_eval.py:259 `timeout=1800`），60s teardown 装不下；② 「硬超时也走完」是「保护进行中的不被中断」，不是「被中断后补跑」。

```python
@register_stage
class CannbenchEvalStage(Stage):
    uninterruptible = True      # ← 一行。一旦开始跑，workflow deadline 延后到它跑完
```

- **机制**：`runner._check_timeout` 检查 workflow deadline 时，若当前 stage `uninterruptible` 且在跑 → 不 raise，设 `pending_timeout` 标志；stage 跑完后检查 `pending_timeout`，那时再 raise。
- **不卡死保证**：cann-bench 自带 30min subprocess timeout（:259）兜底，uninterruptible 最多等它自己超时，不会无限等。
- **「编译通过才进」由 stage 自己保证**：cann-bench transition 已判断 `deploy_result.smoke_passed`（:77），编译没过 → 根本不开始 → 无所谓保护。不需主流程判断。
- **与 teardown 的分工**：teardown = 被中断 → 收尾（finally）；uninterruptible = 别中断 → 保护跑完。cann-bench 用 uninterruptible，不用 teardown。

---

### D7：全局优雅退出 —— SIGTERM→cancel + 进程组 + atexit

- 注册 `signal.SIGTERM` handler → 转发为 `runner.cancel()` + 主流程 KeyboardInterrupt，复用现有 `dispatcher.py:987-994` 保存状态路径（EX_SIGINT）。
- `_start_serve`（opencode）`subprocess.Popen` 加 `start_new_session=True`；`_stop_serve` 用 `os.killpg` 杀整组（含 engine MCP stdio 子进程），杜绝孤儿。
- `atexit` 注册兜底清理所有活跃 proc handle（与 claude SDK 自带的 `_kill_active_children` 双保险）。
- **Option A 软放开的收紧**（D3 硬墙引入后的交互）：硬墙触发（`aborted="hard_timeout"`）= 连单 spawn 都耗尽 deadline = 真卡了，**不该再软放过**。runner._check_timeout 的 Option A 分支用 `aborted` 区分：spawn 被硬墙杀 → 不软放过；spawn 正常返回但 stage 总时长略超 → 照旧软放过。

---

### D8：收口 `_generate_report` —— 纳入 finalize teardown（§2.5）

现有 `_generate_report`（dispatcher.py:1048，多分支硬编码调用）是 teardown 语义的 ad-hoc 实现。引入 D5 teardown 后，把 report 生成收进 `FinalizeStage.teardown()`，**删掉 dispatcher 里散落的手写调用**——同一职责一条通路。一期一起做（用户已确认）。

> **【S3 实施期发现缺陷 — 原 D8 处方不可直接实施，待重 scope】** 深 probe 发现：
> 1. `FinalizeStage.actions` 的 `GenerateReport` action 落 runner `else: pass`（"consumed by transition"），但 `FinalizeStage.transition` 不引用它 → **GenerateReport 是 inert marker**；真正 report 生成只在 dispatcher `_generate_report`。
> 2. dispatcher `_generate_report` 仅 PreconditionError(:955) + 正常完成(:997) 调用；**timeout(:940)/env/card/sigint 路径无 report**（硬超时场景目前就无 report）。
> 3. FinalizeStage 只在 workflow 跑到 finalize 时执行；timeout/early-stage 中断时**没跑** → 收进其 teardown 覆盖不到异常路径 → 删 dispatcher 调用会丢 PreconditionError 路径 report，且不补 timeout 路径。
>
> **「report on all graceful-exit paths」是 dispatcher 层 finally-block 的事，与 D8 原处方相反。** 建议 D8 重 scope：dispatcher `_generate_report` 改 `finally`（覆盖含 timeout 在内的所有退出路径）+ 顺手删 FinalizeStage 的 inert `GenerateReport` action（§2.5）。**待用户确认后单独切片**——S3（D5/D6）不含 D8。详见 `06-impl-s3-teardown-uninterruptible.md` 末尾。

---

## 四、四把尺子评估（CLAUDE.md §1.2）

| 尺子 | claude A（anyio） | 备注 |
|---|---|---|
| **可维护** | ✅ anyio 是 SDK 传递依赖（零新增）；anyio backend 下 `asyncio.sleep` 原生可用（无 sleep 混用陷阱）；`_spawn` 主体零改动 | B' 此处为 ⚠️（需重写整个 `_spawn` 核心 + `receive_messages` 流式不自然停） |
| **可扩展** | ✅ `deadline_monotonic` 协议级，第三个 backend 自动归位 | teardown/uninterruptible 声明式，新 stage 自动适用 |
| **可诊断** | ✅ `aborted` 字段 + `agent_aborted` event + close 耗时可观测 | hard_kill 开关状态进 events |
| **架构合理** | ✅ 硬墙在 backend 内、runner 只传 deadline；走 SDK intended 的 close 路径 | teardown 善终归 stage、uninterruptible 归 runner 检查处 |

C（asyncio.wait_for）在「可诊断」直接挂（CLI 孤儿无信号，§1.2「推迟到下游」）；D（subprocess 化）在「可维护」挂（破坏不变式）。均排除。

---

## 五、与现有工作的边界

| 现有工作 | 关系 |
|---|---|
| `stage-timeout-granularity/` | **上游依赖**。它建的 deadline 检测层（runtime_config.timeouts + _check_timeout + Option A）本方案**原样复用**，只补执行层。Option A 的软放开语义在 D7 做了一处收紧（硬墙触发时不放过）。 |
| `precision-debug-agent-abort/` | **泛化来源**。它的中断善终是 precision-debug 特定的；本方案 D5（teardown 钩子）+ D4（aborted）将其泛化为所有 stage 通用的善终机制，precision-debug 成为 teardown 的一个重载者（`git reset best_commit`）。 |
| `opencode-sdk-backend/` | P-BC3（keepalive 硬墙）是 D2 的基础，本方案只接外部 deadline。 |

---

## 六、退出场景优雅矩阵（回应「各种粒度都优雅」）

| 触发 | 检测 | 执行（杀） | 善终（teardown） | 落状态 | resume |
|---|---|---|---|---|---|
| 单 spawn 卡死 | backend 硬墙 | opencode `_stop_serve` / claude A→SDK close | stage.teardown | crash-salvage + sidecar | ✅ |
| stage 总量超限 | _check_timeout(stage) | raise StageTimeoutError | 中断 stage 的 teardown | state_snapshot 原子写 | ✅ --resume 跳 completed |
| workflow 总量超限 | _check_timeout(workflow) | raise WorkflowTimeoutError | 同上 | 同上 | ✅ |
| Ctrl+C | SIGINT→KeyboardInterrupt | runner.cancel + 硬墙秒级返回 | teardown | dispatcher.py:987 保存 | ✅ |
| SIGTERM | **D7 新增 handler→cancel** | 同 Ctrl+C | teardown | 同上 | ✅ |
| cann-bench 进行中触发超时 | uninterruptible | **延后**，等它跑完/自己 30min timeout | — | 评测结果正常落 | ✅ |
| forkjoin 单 branch 卡死 | branch stage_deadline | per-spawn 硬墙 | branch teardown | branch 标 failed→halt | ✅ |
| SIGKILL/OOM | 不可捕获 | — | — | sidecar 已 flush + snapshot 原子写 | ✅（最后完成节点） |

---

## 七、实施切片（指向 L4）

| 切片 | 内容 | 对应决策 |
|---|---|---|
| S1 backend 硬墙 | `spawn` 加 `deadline_monotonic`；claude A（spawn 层 `anyio.fail_after` wrapper，`_spawn` 主体零改动）；opencode 接线。UT：stub backend 验 deadline 到点必返回 + sidecar 保留 | D1/D2 |
| S2 信号 + 接线 | `AgentResult.aborted` 字段；runner 算剩余预算传入；`agent_aborted` event；Option A 收紧 | D3/D4/D7 |
| S3 stage 善终 | `Stage.teardown()` 钩子 + `Stage.uninterruptible`；cann-bench 声明 uninterruptible；finalize teardown 收口 `_generate_report` | D5/D6/D8 |
| S4 全局退出 | SIGTERM handler；opencode `start_new_session`+`killpg`；atexit 兜底 | D7 |
| S5 ST 守护 | 真机 dual-backend 验「硬超时秒级返回 + 落状态 + --resume 恢复 + cann-bench 走完」闭环（§3.9，heavy_llm） | 全部 |

---

## 八、冻结状态

以上 D1–D8 已与用户讨论拍板。实施按 S1–S5 顺序，每切片先写 L4（`03-impl-<topic>.md`）再 TDD。`teardown` 钩子的具体 stage 重载（precision-debug git reset、codegen 清理等）在各 stage 的 L4 里展开，不在本 L3 展开。
