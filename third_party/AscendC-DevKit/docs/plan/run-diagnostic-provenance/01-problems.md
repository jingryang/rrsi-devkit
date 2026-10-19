# Run 诊断可观测性 — 问题/需求记录

> 来源：2026-07-18 用户反馈「他人拿 output/<run_id>/ 日志来分析时，版本定位与 agent session 获取两难」。
> 本文件只记客观事实（哪里缺、凭什么这么说），不提方案、不排顺序、不写决策。

## 问题清单

### P1: run 产物无 DevKit 自身版本/出处指纹，无法坐实对方跑的是哪个版本

**现象**：他人拿 `output/<run_id>/` 日志来分析时，无法判断对方用的是工程的哪个 commit、是否带本地未提交私改、本次用哪个 agent 后端跑的。

**证据**：
- `events.jsonl` 的事件 schema（`orchestration/kernel/event.py` 的 `make_event`）字段集合无任何版本/git/backend 字段；首事件恒为 `stage_enter`，**没有 run 级启动事件**可挂出处。
- `state.repo_baseline_ref`（`orchestration/kernel/state.py`）是**目标算子仓**的 HEAD（rollback 安全网用，被 dispatcher 的 `guard.rollback` 消费），**不是 DevKit 自身仓库**的 commit。
- `RunContext`（`orchestration/run_context.py`）只采集被测环境（CANN/python/torch_npu/compiler/detected_chip），**不采集 DevKit 自身 git、不记 agent backend 类型**。
- agent backend 类型（`application/agent_backend_factory.resolve_backend_kind`）解析后**不入任何产物**；事后无法回溯本次是 claude 还是 opencode。
- `pyproject` 的 version 是孤立字符串，运行时不读、不入产物；包 `__init__.py` 为空、无 `__version__`。
- `run.log` 是 best-effort tee（`infra/log_capture`），权威是 `events.jsonl`，而 events 里这些都没有。

**影响**：版本定位盲区——对方跑旧版本 / 带私改 / 用不同后端，从产物结构上无法判定，导致「按最新代码排查但对方其实是旧版」的无效往返。

### P2: agent session 已自闭环落盘，但不可定位 / 不可校验 / 易丢失

**现象**：session 已落 `<run>/agents/*.jsonl`（两后端均落，由本工程 Python 写），但他人提供日志时 session 难获取、拿到了也对不上号、且无法校验完整性。

**证据**：
- `agents/*.jsonl` 命名为 `<agent>[-<branch>]-<seq>.jsonl`（`infra/workspace.Workspace.transcript_path`），seq 是 per-stem spawn 计数，与 `events.jsonl` 的 `action_start` 无任何对应字段；`spawn_context` 事件（`event.py`）字段为 `agent/prompt/context_keys/skills/working_dir`，**无 transcript 文件名、无 session_id**——events 的 action 与 agents/ 的文件对不上号。
- 一个 run 的 `agents/` 体积可达数十 MB（单 transcript 实测 280KB~2.2MB），他人打包易遗漏/截断/挑拣，且无清单 + checksum 校验。
- 失败 action 对应的 session 是否存在/非空，无任何校验；session 缺失时无「不可诊断」信号。

**影响**：拿到一堆对不上号的 jsonl，无法定位到出问题的那个 action 的真实推理；对方若挑拣/截断也无法发现。

### P3: 用户运行时 LLM 配置不记录 + 输出截断无信号

**现象**：影响 LLM 输出的运行时配置（如模型输出上限）不进任何产物，且输出被截断时工程无感知。

**证据**：
- `opencode.json` 声明 `GLM-5.2` 的 `limit.output = 8192`（用户实证：8192 过小致输出被截断），但工程**从不读取** `opencode.json` 的 `limit`/`model` 进任何产物。
- claude 后端的 `max_turns`/`model`（`capabilities/agent/sdk_backend.py` 的 `ClaudeAgentOptions`）同样不入产物。
- `sdk_backend`/`opencode_backend` 全文 grep 不到 `finish_reason`/`stop_reason`/`max_tokens` 处理——输出被 8192 砍断时工程无任何事件/标记。
- `driver_version` 是 `RunContext` 的死字段（`_probe_hardware_env` 硬编码 `None`），`npu-smi` 调过但不解析回来。

**影响**：用户设了危险值（output 过小）→ 静默截断 → 产物里看不出来 → 排查南辕北辙。典型如「输出上下文 8192 导致截断」这类问题，事后从日志无法定位。

---

## Resolution（2026-07-19）

三个问题已闭环（方案 A/B/C 见 `02-analysis.md`，L2 step-67）：

- **P1**：`infra/provenance.py` 单一翻译点 `build_provenance()` 采集 DevKit git（commit/branch/dirty/describe）+ backend + skill/agent 内容指纹 + runtime_config + environment，写 `<run>/PROVENANCE.json`（不可变）+ events.jsonl `run_started` 首事件（双写，events 权威）+ report 头部。`repo_baseline_ref`→`target_repo_baseline_ref` 改名澄清（它本是目标算子仓 HEAD）。
- **P2**：`spawn_context` 加 transcript/session_id 字段（action↔session 定位）；`infra/run_manifest.py` MANIFEST.json（每文件 sha256）；cli `pack-run`（含 SDK native session 按 session_id 捞）+ `verify-run`（校验 missing/mismatched/extra）。
- **P3**：runtime_config 采 opencode.json `limit.output`（≤8192 加载期 WARN）；`AgentResult.truncated_turns` + backend stop_reason 检测 + runner per-turn `output_truncated` 事件。

全量 UT 2376 passed/7 skipped 零回归。heavy_llm e2e（真实 run 端到端）未跑，待用户决策（§3.11）。
