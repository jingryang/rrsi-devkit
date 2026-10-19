# turn-stall 恢复链路 — L4 实施方案（2026-08-12，待实施，rev2）

> 层级：**L4 / 实施方案**。记录「改哪个函数、什么顺序、怎么验证」。**待实施**（本版为配方，
> 未落地；落地后补「as-built + 踩坑 + 验证结果」）。
> 问题事实见 `01-problems.md`（L1）；方案选项与决策见 `02-analysis.md`（L3 rev2）。

## 方案一句话

两阶段恢复语义落进代码：**Phase 1 原地 resume**（turn-stall abort 后，P131c re-spawn 走 sidecar
续同一 session、"继续"、满窗 600s）；**Phase 2 计数退化 spawn**（sidecar 记录 `resume_fails`
连续失败次数，读到 `>= N`（`resume_attempts`，默认 3）→ 清 sidecar + fresh 新 session + 全量
prompt）。fresh 首跑卡死不计数。设计意图与实现一致（§1.2/§2.5）。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/ascendc_devkit/capabilities/agent/base_backend.py` | 改动 1（sidecar 加 `resume_fails` 字段 + bump helper） |
| `src/ascendc_devkit/orchestration/runtime_config.py` | 改动 2（`resume_attempts` 配置 + 加载期校验） |
| `resources/orchestration-config.json` | 改动 2b（`agent.resume_attempts` 键 + 注释） |
| `src/ascendc_devkit/capabilities/agent/opencode_backend.py` | 改动 3-5（主路径） |
| `src/ascendc_devkit/capabilities/agent/sdk_backend.py` | 改动 6（对称实现） |
| `tests/ut/capabilities/test_session_resume.py` | 新增计数/退化测试 |
| `tests/ut/capabilities/test_opencode_backend.py` | 新增 spawn 级退化测试 |
| `tests/ut/orchestration/test_timeout_backoff_config.py` | 新增配置测试 |
| `tests/ut/orchestration/test_infra_backoff_resume.py` | 仅回归守护（runner 不改） |

---

## 改动 1 — base_backend.py：sidecar 加 `resume_fails` + bump helper

### 1a. `_write_session_sidecar`（`:120-137`）加 `resume_fails` 字段

```python
def _write_session_sidecar(self, agent_name: str, branch_label: str,
                           session_id: str, stage_name: str = "",
                           resume_fails: int = 0) -> None:
    """...（原注释）+ resume_fails = 连续失败的 resume 次数（退化 spawn 阈值，见
    docs/plan/turn-stall-resume-escalation/）。fresh 新 session 写 0；resume 续写
    保留值；自然结束清 sidecar 一并清除。"""
    ...
    path.write_text(json.dumps({
        "agent_name": agent_name,
        "session_id": session_id,
        "stage_name": stage_name,
        "resume_fails": int(resume_fails),
    }, ensure_ascii=False), encoding="utf-8")
```

### 1b. 新增 `_bump_session_resume_fails`（`:149` `_clear_session_sidecar` 之后）

```python
def _bump_session_resume_fails(self, agent_name: str, branch_label: str,
                               stage_name: str = "") -> None:
    """P131d：resume-stall abort 时，sidecar 的连续失败计数 +1（read-modify-write，
    best-effort）。读到该计数 >= resume_attempts 的下一次 spawn 会退化 fresh。"""
    path = self._session_sidecar_path(agent_name, branch_label, stage_name)
    if path is None or not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["resume_fails"] = int(data.get("resume_fails", 0) or 0) + 1
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        Logger.warn(f"could not bump session resume_fails for {agent_name}: {e}")
```

---

## 改动 2 — runtime_config.py + config：`resume_attempts`

### 2a. `infra_backoff()`（`:675-701`）返回 dict 加键

```python
# P131d（rev2）：resume 连续失败 N 次后退化 spawn（fresh）。必须 < infra_retry_max_retries，
# 否则预算先耗尽、退化永远轮不到（§1.3 加载期校验）。
"resume_attempts": _positive_int(
    raw.get("resume_attempts", _DEFAULT_RESUME_ATTEMPTS),
    "agent.resume_attempts"),
```

常量（`_DEFAULT_INFRA_*` 附近）：

```python
# 默认 4 = resume 3 次 + 1 发 fresh（N < max_retries 保证预算内有退化槽位）。
_DEFAULT_INFRA_RETRY_MAX_RETRIES = 4
_DEFAULT_RESUME_ATTEMPTS = 3     # resume 连续失败 N 次 → 退化 spawn
```

并在 `infra_backoff()` 内交叉校验（两键同源，直接校验）：

```python
_ra = _positive_int(raw.get("resume_attempts", _DEFAULT_RESUME_ATTEMPTS),
                    "agent.resume_attempts")
_rl = _positive_int(raw.get("infra_retry_max_retries", _DEFAULT_INFRA_RETRY_MAX_RETRIES),
                    "agent.infra_retry_max_retries")
if _ra >= _rl:
    raise ConfigError(str(_CONFIG_PATH),
                      f"agent.resume_attempts({_ra}) must be < "
                      f"agent.infra_retry_max_retries({_rl}) — 预算内须留一发 fresh")
```

### 2b. `resources/orchestration-config.json` `agent` 段（`:130-133` infra_* 旁）

```json
"_comment_resume_attempts": "P131d (rev2): turn-stall 后先原地 resume（续同一 session，满窗 600s），连续失败 resume_attempts 次后退化 spawn（fresh 新 session）。须 < infra_retry_max_retries。",
"resume_attempts": 2
```

---

## 改动 3 — opencode_backend.py：`__init__` 加 `resume_attempts`

`:228` `turn_stall_s` 后加参数 `resume_attempts: int = 3`；`:273` 附近存 `self._resume_attempts`。
默认与 `runtime_config._DEFAULT_RESUME_ATTEMPTS` 一致（dispatcher 经 factory 注入实际值）。

---

## 改动 4 — opencode_backend.py：spawn sidecar 读取处（`:556-591`）计数退化

在 `if not resume_session_id:` 块内读 `resume_fails`，达阈值即**清 sidecar + 不走 resume**（fall
through 到 fresh 分支）：

```python
_resume_fails = 0
if not resume_session_id:
    _sc = self._session_sidecar_path(agent_name, branch_label, stage_name)
    if _sc is not None and _sc.exists():
        import json as _json
        try:
            _data = _json.loads(_sc.read_text(encoding="utf-8"))
            _sid = _data.get("session_id", "") or ""
            _fails = int(_data.get("resume_fails", 0) or 0)
        except Exception:  # noqa: BLE001 — corrupt sidecar → fresh
            _sid, _fails = "", 0
        if _sid:
            if _fails >= self._resume_attempts:
                # P131d Phase 2：resume 连续失败 N 次 → 退化 spawn（清 sidecar，fresh）。
                self._clear_session_sidecar(agent_name, branch_label, stage_name)
                Logger.action(
                    "agent_degrade",
                    f"{attribution}{agent_name} resume failed {_fails}x >= "
                    f"resume_attempts {self._resume_attempts}; degrading to fresh spawn")
            else:
                resume_session_id = _sid
                _resume_fails = _fails          # 续写保留计数
                Logger.action("agent_resume", ...原样...)
if resume_session_id:
    session_id = resume_session_id
    self._write_session_sidecar(agent_name, branch_label, session_id,
                                stage_name, resume_fails=_resume_fails)
    ...原样...
else:
    ...fresh 分支原样（新 session + `_write_session_sidecar(..., resume_fails=0)` 默认）...
```

- 退化后 `resume_session_id` 仍为 None → 走 else 分支 fresh（新 `/session` + 全量 prompt + skill
  steer，`:578-` 既有逻辑），新 sidecar 写 `resume_fails=0`。
- within-spawn session-gone degrade（`:675`）同样写 `resume_fails=0`（新 session 全新预算）。

---

## 改动 5 — opencode_backend.py：crash-salvage abort 处 bump（`:826`）

```python
_aborted = "hard_timeout" if _is_hard_timeout_exc(e) else None
if _aborted and resume_session_id:
    # P131d Phase 1 失败计数：resume 会话被 stall-kill → 连续失败 +1（fresh 首跑不计数）。
    self._bump_session_resume_fails(agent_name, branch_label, stage_name)
```

- `resume_session_id` 在 crash-salvage（同一 `spawn` 作用域）可见；within-spawn degrade 后为 None
  → fresh 卡死不计数（符合「fresh 首跑先 resume」）。
- cut / 非 abort 崩溃不进此分支 → 20260810 Part 2 的 silent-cut resume 原样保留。

---

## 改动 6 — sdk_backend.py：对称实现

### 6a. 自动 resume 读取处（`:428-442`）计数退化

与改动 4 同构：读 `resume_fails`，`>= self._resume_attempts` → 清 sidecar、不 resume（fresh）；
否则 resume 并保留计数到本地 `_resume_fails`。`SDKBackend.__init__` 同步加 `resume_attempts: int = 3`
（默认与 opencode 一致）。

### 6b. 中途 sidecar 写（`:482-484`）保留计数

```python
self._write_session_sidecar(agent_name, branch_label, consumer.session_id,
                            stage_name=stage_name, resume_fails=_resume_fails)
```

（`_resume_fails` 为 6a 读取的保留值；fresh 首跑为默认 0。）

### 6c. 硬超时 abort 处（`:216-220`）bump（含自动 resume 标志位）

```python
# spawn 顶部：self._spawn_was_resume = bool(resume_session_id)
# _spawn 内 auto-resume 分支（读到 sidecar 续跑时）：self._spawn_was_resume = True
...
except TimeoutError:
    if self._spawn_was_resume or resume_session_id:
        self._bump_session_resume_fails(agent_name, branch_label, stage_name)
    return self._build_result(... aborted="hard_timeout")
```

（sdk 的 stall 由 IRConsumer `should_stop` 处理为 partial，不走 abort；此处仅硬超时走计数退化，语义一致。
**关键**：sidecar 自动 resume 在 `_spawn`（异步协程）内部决定，硬超时 cancel 后外层 `spawn` 拿不到局部
`resume_session_id`——用实例标志 `_spawn_was_resume` 把「本次是否 resume」跨出 `_spawn`，否则自动 resume
的硬超时 bump 永不触发。）

---

## 测试（§3.1 TDD，as-built）

### 测试 1 — `test_session_resume.py`（sidecar 计数 + sdk 对称）

| 测试 | 守护点 |
|---|---|
| `test_sidecar_write_carries_resume_fails` / `test_sidecar_default_resume_fails_zero` | 写计数落盘 / 缺省 0 |
| `test_bump_session_resume_fails_increments` / `test_bump_session_resume_fails_noop_without_sidecar` | bump +1 不动 session 句柄 / 无 sidecar no-op |
| `test_sdk_auto_resume_degrades_when_resume_fails_ge_threshold` | sdk `resume_fails>=N` → fresh（全量 prompt、无 resume option） |
| `test_sdk_hard_timeout_abort_bumps_resume_fails` | sdk 硬超时 abort（自动 resume 会话）→ bump +1（覆盖 `_spawn_was_resume` 标志） |
| `test_sdk_resume_preserves_counter_below_threshold` | sdk mid-stream 写保留计数（不清零） |

### 测试 2 — `test_opencode_backend.py`（spawn 级端到端退化）

| 测试 | 守护点 |
|---|---|
| `test_spawn_degrades_to_fresh_after_n_resume_fails` | 预置 sidecar `resume_fails=3` → spawn 走 fresh（新 /session + 全量 prompt + skill steer，非 "继续"） |
| `test_spawn_resume_preserves_counter_below_threshold` | `resume_fails<N` → resume 且续写保留计数 |
| `test_resume_stall_abort_bumps_sidecar` / `test_fresh_stall_abort_does_not_bump` | resume 被杀 bump / fresh 首跑被杀不 bump |
| `test_full_resume_degrade_converge_sequence` | **完整收敛序列**：fresh-stall → resume×3（各 bump 0→1→2→3）→ 第 5 发退化 fresh 成功；body 序列 全量/"继续"×3/全量 |
| `test_session_gone_degrade_resets_resume_fails` | within-spawn 404 degrade → 新 sidecar `resume_fails=0` |

### 测试 3 — `test_timeout_backoff_config.py`

| 测试 | 守护点 |
|---|---|
| `test_infra_backoff_defaults` | 默认 `max_retries=4`、`resume_attempts=3` |
| `test_infra_backoff_resume_attempts_lt_max_retries_required` | `resume_attempts >= max_retries` → `ConfigError`（§1.3 交叉校验） |
| `test_infra_backoff_resume_attempts_negative_rejected` | 非正 → `ConfigError` |
| `test_infra_backoff_resume_attempts_custom_accepted` | 合法自定义值（< max_retries）接受 |

### 测试 4 — `test_infra_backoff_resume.py`（回归守护）

runner P131c 逻辑**零改动**（预算/退避/`_infra_backoff_retry` 原样）——预算耗尽断言随默认
`max_retries=3→4` 更新（`spawns == 5`）；StubBackend 返回 aborted 的重试行为不变即回归守护。

---

## 验证命令

```bash
/usr/bin/python3.11 -m pytest \
  tests/ut/capabilities/test_session_resume.py \
  tests/ut/capabilities/test_opencode_backend.py \
  tests/ut/orchestration/test_timeout_backoff_config.py \
  tests/ut/orchestration/test_infra_backoff_resume.py \
  tests/ut/capabilities/test_p125_aborted_infra.py -v
```

目标：5 文件全绿（新增 ~12 + 既有零回归）。再跑编排/能力全量 UT 确认零回归。

## 未覆盖（诚实，§3.11）

- **heavy_llm / 真实 opencode 链路 ST 未跑**：`tests/st/test_turn_stall_e2e.py` /
  `test_session_resume_e2e.py`（真实 serve + 模型服务下退化端到端行为）需真实环境，按 §3.11
  由用户决策跑 / 不跑。日常迭代靠 backend UT（模拟 server 驱动）+ 编排 UT 兜底。
- 模型服务侧（网关 fail-fast / 自身超时）不在此范围。

## 不在本次范围

- P131c 退避节奏 / 累计 600s（`runtime_config.py:630-633`）不动；`infra_retry_max_retries` 默认 3→4（为 `resume_attempts=3` 让出发退化槽位）。
- 短窗 resume 探测（L3 rev1 选项①，否决）——记为未来优化，若实证 resume 死窗占绝对主导再评估。
- 429 in-session resume 与 SDK 的 SSE-error resume 路径不动。
