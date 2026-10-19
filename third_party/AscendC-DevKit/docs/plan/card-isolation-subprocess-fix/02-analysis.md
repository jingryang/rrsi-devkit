# L3 方案分析 — card 隔离 subprocess 修复：env 兜底 + 命令串前缀注入（已冻结）

> 对应 L1 P1-P3。2026-08-25 用户拍板启动 step-90，冻结。

## 0. 设计判据

- **单决策点不动摇**：卡解析优先级只存在于 `card_context`（§2.5，其 docstring 自我声明为
  single path）。CLI 侧的一切解析收拢到它，不开旁路。
- **持卡粒度对齐现行哲学**：run_tests 一轮 ≈ 一次测量子进程；diagnose 一轮 ≈ 一次 agent 会话。
  acquire 在 actions()（spawn 前）、release 在 transition() **入口**（子进程/agent 已结束）——
  持卡跨度 ≈ 精确的 NPU 工作跨度，LLM 主导的 design/codegen 长段仍不占卡。
- **零 backend 手术**（L1 P3）：卡的传递不走 SpawnAgent/RunMeasure 的进程 env，走**命令串本身**
  ——build/test 命令由 `_common_context` 单点构造（§1.15），前缀注入
  `ASCEND_NPU_ID=<card> `（shell 单命令 env 赋值形），diagnose 的 Bash 与 RunMeasure 的
  shell 原样继承，子进程树内所有 CLI 自动读到。

## 1. 四项改动

### 改动 1：`card_context` 增加继承 env 兜底（优先级：preferred > pool > env > 0）

```python
if preferred is not None: yield preferred; return
if pool is None:
    env_card = os.environ.get("ASCEND_NPU_ID")  # CLI subprocess：池不可达，继承导出值
    yield int(env_card) if env_card (isdigit) else 0
    return
with pool.acquire_context(...): ...
```

CLI 进程（pool 恒 None）由此读到父 shell 导出的卡；框架进程（pool 存在）不受影响。

### 改动 2：deploy.py smoke 卡解析收拢进 card_context（删自旁路）

`card = state.npu_id if ... else 0` → `with card_context(state.npu_id, None) as card:` 包住
smoke 子进程（pool=None 走 env 兜底）。单决策点闭合（deploy 原先是唯一绕开 card_context 的
NPU 子进程点）。

### 改动 3：precision_debug 阶段级持卡 + 命令串前缀注入

- `_acquire_card_lease(state) -> int`：actions() 开头调用。hard-pin（`state.npu_id` 非 None）
  → 直接返回不碰池（对齐 card_context hard-pin 语义）；pool 模式 → `state.card_pool.acquire()`
  （阻塞，lease WARN 阈值既有语义），**租约记 control.json `card_lease`**（per-run 状态，
  batch 线程安全；hard-pin 时记 null）。
- `_common_context`：`build_command` / `test_command` / `device_id` 统一用本轮解析卡
  （hard-pin 或 control.json `card_lease`，缺省 0）——命令串前缀
  `ASCEND_NPU_ID=<card> `，diagnose（SpawnAgent prompt）与 run_tests（RunMeasure 命令）
  两条路径单点覆盖。
- `_release_card_lease(state)`：两个 substage 的 `transition()` **第一行**调用（子进程/agent
  已结束）：读 control.json `card_lease`，非 null 则 `pool.release(card)` 并清字段——在入口
  释放天然覆盖 transition 的所有分支（measurement-abort 早退、正常路径、escalation）。
- hard-kill 整 run：池随进程消亡，无跨进程泄卡问题。

### 改动 4：验证（TDD）

- card_context 四态（preferred/pool/env 合法/env 非法→0）；
- deploy smoke 经 card_context（env 注入后选对卡）；
- 命令前缀注入三态（hard-pin / pool lease / 无 pool 缺省 0）+ `device_id` 一致；
- acquire→release 配对（正常 transition、measurement-abort 早退 transition 均释放、
  release 幂等/无租约 no-op）。

## 2. 否决项

| 否决 | 理由 |
|---|---|
| SpawnAgent 加 env 字段 + 两 backend 注入 | L1 P3：opencode serve env 启动时固定，per-round 注入需 serve 生命周期手术，面积大；命令串前缀零 backend 改动同效 |
| 持久化卡进 state 快照 | L1 P2 第一形态：钉死整个 run，破坏池共享 |
| RunMeasure 加 env 字段 + runner 边界 acquire | 可行但多余——命令串已由框架单点构造，前缀注入同效且少两个接触面（Action/runner） |
| 修 A5 侧（precision_debug_a5.py:468） | 同事产权（记忆 codegen-a5-ownership-boundary）；共享层修复自动惠及 A5 CLI |
| pool 耗尽 fail-fast | 维持池既有阻塞语义（与其他 in-process 边界一致；lease WARN 已有可观测） |

## 3. 四把尺子

- 可维护：卡优先级单点（card_context）；注入单点（_common_context）。
- 可扩展：所有 CLI 子进程（现存与未来）经 env 兜底自动归位；新 substage 用 `_acquire/_release` 对即入轨。
- 可诊断：命令串中卡可见（prompt/日志直接可读）；lease 在 control.json 可查。
- 架构合理：L6 单决策点不动；L3 stage 只做租约管理；backend 零改动。
