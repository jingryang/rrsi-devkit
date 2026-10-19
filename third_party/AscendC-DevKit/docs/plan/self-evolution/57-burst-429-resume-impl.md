# 57 — 突发 429 收进 backend session-resume 内循环（实施方案）（L4）

> L4 实施方案：改哪个函数、什么顺序、怎么验证。关联 L1：`06-problems.md` P80；L3：`57-burst-429-resume-analysis.md`（决策冻结）。
> TDD：先写测试再改实现（§3.1）。改动落 L5 backend + L3 config，双 backend parity（§2.5 唯一通路）。

## 0. 改动总览（符号级）

| # | 文件 | 改动 | 类型 |
|---|---|---|---|
| A | `capabilities/agent/_shared.py` | 新增 `_RATE_LIMIT_MARKERS` + `_is_rate_limit_error()` + `compute_backoff_seconds()` 纯函数 | 新增 |
| B | `orchestration/runtime_config.py` | `resume_limits()` 扩为返回 4 个 rate-limit 退避参数 + 默认常量 | 扩展 |
| C | `resources/orchestration-config.json` | `agent` 段加 4 键 + `_comment` | 配置 |
| D | `application/dispatcher.py` | 3 处 backend 构造注入 rate-limit 参数（同 `resume_max_retries` 现有注入） | 接线 |
| E | `capabilities/agent/backend.py`（protocol）+ 各 backend `__init__` | 新增 `rate_limit_*` 构造参数（所有 fake backend 同步加 kwarg，§1.4 不留旧签名） | 签名 |
| F | `capabilities/agent/sdk_backend.py` | `_spawn` 循环加 429 elif 分支：命中 → `asyncio.sleep(退避)` → resume「继续」，独立退避预算 | 主改 |
| G | `capabilities/agent/opencode_backend.py` | message POST 外包退避-重试 wrapper（opencode 单发无循环，需新建）+ parity | 主改 |

## 1. A：`_shared.py` 纯函数（先可单测）

```python
# 429 burst 限流：服务端软拒、session 未坏、退避后 resume 可续（P80 实证 burst 非硬封）。
# 与 _TRANSIENT_ERROR_MARKERS 分开：429 被拒时天然零进展，不能共用 no_progress 闸（L3 §4）。
# 与 _INFRA_ERROR_MARKERS 分开：infra（No available channel/401/403）重试无意义（step-27 不变式保留）。
_RATE_LIMIT_MARKERS = (
    "Request rejected (429)",
    "(429)",                 # 兜底：措辞变体（Weekly/Monthly Limit Exhausted 常同现）
)

def _is_rate_limit_error(text: str | None) -> bool:
    """True when text names a 429 burst rate-limit (retry-after-backoff)."""
    if not text:
        return False
    return any(m in text for m in _RATE_LIMIT_MARKERS)

def compute_backoff_seconds(attempt: int, base_s: float, factor: float,
                            elapsed_total_s: float, max_total_s: float) -> float | None:
    """指数退避单次 sleep 秒；返回 None 表示总时长封顶已耗尽→不再重试（halt）。
    attempt 从 0 起。单次 = base * factor**attempt，但不超过剩余总预算。"""
    if elapsed_total_s >= max_total_s:
        return None
    want = base_s * (factor ** attempt)
    remaining = max_total_s - elapsed_total_s
    return min(want, remaining)
```

- 纯函数、确定性、毫秒级 → UT 覆盖，**不标记**（§3.5）。

## 2. B：`runtime_config.py` 退避参数（单一权威源）

- 新增默认常量（紧邻 `_DEFAULT_RESUME_MAX_RETRIES`）：
  ```python
  _DEFAULT_RATE_LIMIT_MAX_RETRIES = 6
  _DEFAULT_RATE_LIMIT_BACKOFF_BASE_S = 30.0
  _DEFAULT_RATE_LIMIT_BACKOFF_FACTOR = 2.0
  _DEFAULT_RATE_LIMIT_BACKOFF_MAX_TOTAL_S = 900.0
  ```
- `resume_limits()` 返回 dict 追加 4 键（复用同一 `agent` 段读取 + `_positive_int` / 新增 `_positive_float` 校验；缺失→默认，present-but-invalid→`ConfigError` fail-fast，与现有策略一致）。键名：`rate_limit_max_retries` / `rate_limit_backoff_base_s` / `rate_limit_backoff_factor` / `rate_limit_backoff_max_total_s`。
- factor 允许 float ≥ 1.0，base/max_total 允许 float > 0 → 需 `_positive_float` helper（若无则新增，参照 `_positive_int`）。

## 3. C：`orchestration-config.json`

`agent` 段追加（附 `_comment` 说明 burst 429 退避-resume 机制 + 指向 L3 step 57）：
```json
"rate_limit_max_retries": 6,
"rate_limit_backoff_base_s": 30,
"rate_limit_backoff_factor": 2.0,
"rate_limit_backoff_max_total_s": 900
```

## 4. D+E：注入链（L2→L5，不越层）

- `backend.py` protocol / `SDKBackend.__init__` / `OpencodeBackend.__init__` / `StubBackend` / 所有 fake backend：新增构造参数 `rate_limit_max_retries: int`、`rate_limit_backoff_base_s: float`、`rate_limit_backoff_factor: float`、`rate_limit_backoff_max_total_s: float`（默认值兜底，供未注入的测试路径）。**同步改所有 fake（§1.4 不留旧签名包装）**。
- `dispatcher.py` 3 处 backend 构造（:747 / :1109 / :1285）：从 `_resume_limits()` 展开注入这 4 个值（同 `resume_max_retries` 现有写法）。

## 5. F：`sdk_backend.py` 主改（既有循环加 429 分支）

在 `_spawn` 的 crash 分类段（`:585` 附近，`if not _is_transient_error(...): break` **之前**）插入 429 分支：

```python
# 429 burst：独立退避预算（不与 SSE no_progress 混，L3 §4）。
if _is_rate_limit_error(last_result_text):
    sleep_s = compute_backoff_seconds(
        rl_attempt, self._rl_backoff_base_s, self._rl_backoff_factor,
        rl_elapsed_s, self._rl_backoff_max_total_s)
    if sleep_s is None or rl_attempt >= self._rl_max_retries or not session_id:
        # 退避预算/总时长耗尽，或无 session 可 resume → halt，reason 可操作。
        Logger.warn(f"Agent {agent_name} 429 backoff exhausted "
                    f"(attempts={rl_attempt}, waited={rl_elapsed_s:.0f}s); "
                    f"treating as hard quota → halt.")
        last_result_text = (last_result_text or "") + \
            " [429 burst backoff exhausted → hard quota]"
        break
    Logger.action("agent_backoff",
                  f"{agent_name} 429 rate-limited; sleeping {sleep_s:.0f}s "
                  f"then resuming session {session_id} "
                  f"(429-attempt {rl_attempt + 1}/{self._rl_max_retries})")
    await asyncio.sleep(sleep_s)
    rl_elapsed_s += sleep_s
    rl_attempt += 1
    active_options = _dc.replace(options, resume=session_id)
    active_prompt = _RESUME_PROMPT   # "继续"
    continue
```

- 循环顶初始化 `rl_attempt = 0`、`rl_elapsed_s = 0.0`（与 `attempt`/`no_progress` 并列）。
- 构造参数存 `self._rl_*`（`__init__` 里）。
- **429 命中不复用 `no_progress` 闸**、**不烧 `resume_max_retries`**（独立计数），保证退避有机会跑满。
- 分支落在 `_is_session_gone` degrade 之后、`_is_transient_error` 之前：session-gone 仍先降级 fresh；非 429 非瞬态仍走逻辑失败 break。

## 6. G：`opencode_backend.py` parity（单发→退避重试 wrapper）

opencode `spawn` 是单发 blocking POST（`:195-208`），**无循环**。需把 message POST + build_result 包进退避-重试 wrapper：

- 提取 message POST 为内部循环：每轮 POST 后取 `_message_error(message)`（clean error）或捕获异常 `reason`；
- 若 `_is_rate_limit_error(err_or_reason)` 且退避预算未耗尽且 `session_id` 在 → `time.sleep(退避)`（opencode 是同步 requests，用 `time.sleep`）→ **复用同一 session_id 重发 `_RESUME_PROMPT`**（opencode session 由 `POST /session/:id/message` 续，session 未销毁）→ continue；
- 退避耗尽 → 落既有 `_build_result` / 异常 salvage 路径（status=partial/fatal，reason 带 backoff-exhausted 标记）。
- backoff 计算复用 `compute_backoff_seconds`（同一纯函数，两 backend 不各写一份，§2.5）。

## 7. TDD 用例（先红后绿）

### UT（纯逻辑，不标记 §3.5）

1. `test_is_rate_limit_error`：`"Request rejected (429) · Weekly/Monthly Limit Exhausted"` → True；`"Content block not found"` → False；`"No available channel"` → False；`None` → False。
2. `test_compute_backoff_seconds`：attempt 0/1/2 → 30/60/120；`elapsed>=max_total` → None；单次被剩余预算截断。
3. `test_resume_limits_rate_limit_keys`：缺失段 → 4 默认值；present → 读取值；非法（负数/非数）→ `ConfigError`。
4. `test_sdk_backoff_branch`（用 fake query 生成器，注入连续 429 ResultMessage 再转成功）：断言 sleep 被调用（monkeypatch `asyncio.sleep` 记参）、resume 用同 session_id + `"继续"`、429 不烧 `no_progress`/`resume_max_retries`、成功后正常返回。
5. `test_sdk_backoff_exhausted_halts`：连续 429 直到总时长封顶 → break、AgentResult failure_reason 带「hard quota」标记、未无限循环。
6. `test_opencode_backoff_branch` / `_exhausted`：monkeypatch `time.sleep` + fake HTTP 返回 429 error message，断言退避重发同 session + 耗尽落 partial/fatal。
7. fake backend 签名同步：全量 UT 里构造 backend 的测试不因新 kwarg 报错（默认值兜底）。

### ST / heavy_llm（§3.9 / §3.11）

- 真实 429 无法确定性构造（服务端触发），**不新增强依赖 429 的 ST**（§3.5：不能 mock 掉还标记）。
- 退避-resume 的真实链路守护并入既有 `llm` 可达性 ST 即可（backoff 分支的真实触发靠 monkeypatch UT 覆盖，真实 resume 语义已由 step-11/40 的 resume ST 守护）。
- heavy_llm 全流程批跑（首跑+续跑）本就待用户决策跑一次（step-55 §3.11 遗留）——该次跑天然覆盖 429 退避路径（若窗口内撞 429）。**不单独造 heavy_llm 用例**（§3.11 合并优先）。

## 8. 回归范围

- 全量 `pytest -m "not heavy_llm"`：UT 全量 + 非 heavy ST，预检 LLM/NPU/CANN 可达（§3.6）。
- 重点回归：既有 SSE `Content block not found` resume 路径不变（新分支在其之前 elif，互不干扰）；step-27 infra 路径不变（429 从 infra 拆出，infra marker 集不动）；`resume_limits()` 既有二键调用方（dispatcher 3 处）兼容（dict 加键不破坏既有 key 读取）。

## 9. 实施顺序

1. A（纯函数）+ UT 1/2 红→绿。
2. B+C（config）+ UT 3 红→绿。
3. E+D（签名+注入，含全 fake backend kwarg）→ 全量 UT 不因签名破。
4. F（sdk 主改）+ UT 4/5 红→绿。
5. G（opencode parity）+ UT 6 红→绿。
6. 全量回归（§8）。
7. supersede：`27-infra-error-classification-impl.md` 顶部加注记指向本 step；L2 总纲 step 57 状态更新为「已实施」。

---

## 10. 实施记录（2026-07-17，已交付）

按 §9 顺序落地，全部 TDD 红→绿。环境：Linux aarch64（NPU/CANN 缺失，纯 UT 用 `--no-env-check`；`TORCH_DEVICE_BACKEND_AUTOLOAD=0` 规避 torch_npu autoload 冲突）。

### 改动落点（符号级，实际）

| # | 文件 | 实际改动 |
|---|---|---|
| A | `_shared.py` | `_RATE_LIMIT_MARKERS`（`"Request rejected (429)"` + `"(429)"` 兜底）+ `_is_rate_limit_error()` + `compute_backoff_seconds(attempt, base, factor, elapsed, max_total)`（返回 None=总时长封顶耗尽） |
| B | `runtime_config.py` | 新增 `_positive_float`（>0）+ `_at_least_one_float`（≥1.0，factor 专用）；4 默认常量；`resume_limits()` 返回 dict 追加 `rate_limit_max_retries/backoff_base_s/backoff_factor/backoff_max_total_s` |
| C | `orchestration-config.json` | `agent` 段加 4 键（6/30/2.0/900）+ `_comment_rate_limit` |
| D | `dispatcher.py` | 3 处 backend 构造注入 4 参（`_resume_limits()[...]`） |
| E | `sdk_backend.py`/`opencode_backend.py` | 两 `__init__` 加 `rate_limit_*` 参 → `self._rl_*`；backend.py protocol 无需改（只声明 `spawn`）；factory 靠 `inspect.signature` kwarg-filter 自动路由，无需改 |
| F | `sdk_backend.py` | `_spawn` 循环：init `rl_attempt=0`/`rl_elapsed_s=0.0`；429 elif 分支落在 session-gone degrade 之后、`_is_transient_error` 之前；命中→`compute_backoff_seconds`→`Logger.action("agent_backoff")`（**sleep 前**）→`await asyncio.sleep`→`_dc.replace(options, resume=session_id)`+`_RESUME_PROMPT`→continue；耗尽→`Logger.warn`+把 exhausted 因由拼进 `last_result_text` **和** `_crash_text`（后者才是 `failure_reason` 源）→break |
| G | `opencode_backend.py` | message-POST 包进 `while True` 退避 wrapper：`_message_error` 命中 429→`compute_backoff_seconds`→`Logger.action`（sleep 前）→`time.sleep`→重建 body 为 `_RESUME_PROMPT` re-POST 同 session；耗尽→`Logger.warn`+break（message 仍带 429 error→`_build_result` 落 partial/fatal，`failure_reason` 含 429） |

### 日志落盘验证（用户诉求「重试信息写入日志避免丢失」）

- 重试信息经 `Logger.action("agent_backoff", ...)`（sleep 前）+ `agent_resume` + 耗尽 `Logger.warn` 输出到 `sys.stderr`。
- `infra/log_capture._Tee.write()` 对每次写 `self._file.flush()`（crash-safe tail）→ 落 `<run>/run.log`。
- 故：**即使进程在 backoff sleep 期间被 SIGKILL，已记录的退避轨迹仍在 run.log**（sleep 前已 flush）。满足诉求。

### 测试结果

- **UT 新增**：`test_capabilities.py::TestRateLimitClassification`(6)+`TestComputeBackoffSeconds`(4)；`test_runtime_config.py::TestRateLimitBackoffLimits`(8)；`test_agent_backend_factory.py` parity(1)；`test_session_resume.py` sdk 429(3)；`test_opencode_backend.py` 429(2)。
- **全量 UT 2293 passed / 7 skipped**（7=既有 cann-bench skip），25.97s。
- **非 llm ST 96 passed / 2 skipped**（含 `test_resume_cli.py`、`test_batch_self_evolve_script.py`），零回归。
- **heavy_llm 未跑**（§3.11）：真实 429 无法确定性构造；`test_session_resume_e2e.py` 是 heavy_llm，待用户在交付节点决策跑一次。退避-resume 分支已由 monkeypatch（`asyncio.sleep`/`time.sleep` no-op + fake query/HTTP 注入连续 429）确定性覆盖，非 mock 掉真实性——真实 resume 语义本就由 step-11/40 的 resume 链路守护。

### 与设计的偏差

- 无实质偏差。唯一细化：耗尽 halt 时需同时 enrich `_crash_text`（不止 `last_result_text`），因 `failure_reason` 下游读 `_crash_text`——L4 §5 伪代码原只改 `last_result_text`，实施时补上（否则 halt 原因丢 429 因由）。已在 F 行记录。
- factory 无需改：`build_agent_backend` 用 `inspect.signature` 过滤 kwargs，新参加到两 backend `__init__` 即自动路由（L4 §4 预期「filter」已够，未新增 factory 代码）。
