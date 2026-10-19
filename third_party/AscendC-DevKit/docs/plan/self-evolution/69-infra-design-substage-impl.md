# 69 — 设计子阶段 infra 错误分类传导 + crash 轮 transcript 留证 — 实施方案（L4）

> L4 符号级改动配方 + TDD 红→绿。L3 决策已冻结如下；L1 见 `06-problems.md` P93/P94。
> **范围边界（用户定调）**：外部 LLM 网关价格配置不在框架职责内（[[external-infra-not-framework-responsibility]]）；本方案只解决「外部 infra 故障时框架如何不误报、不空烧、留可诊断信号」。UT 一律 mock，不碰真实网关。

## 方案决策（frozen，自 L3 摇落 + 摸底修正）

| 层 | 决策 | 摸底修正说明 |
|---|---|---|
| **层 1** backend 分类判据 | **选 A（扩充 `_INFRA_ERROR_MARKERS`）**，否决 L3 原推荐的 C | 摸底发现本次两类错误来源不同——`"timed out"` 是 backend HTTP 超时异常（`str(e)`，**无 statusCode**），「价格未配置」是网关 APIError（有 statusCode）；C 的结构化判据只对后者有效、前者仍需文本 marker，且要改 `_message_error` 签名牵动面大。A 与既有三集合范式（`_shared.py`）一致、最小改动、step-57 已接受 marker 扩充范式，四把尺子更优（可维护=续既有范式 / 架构合理=不引入新分类机制）。 |
| **层 2** 设计子阶段消费 | **选 C（infra 感知 + actions() 短路）**，**收窄** step-27 DEFER | 摸底确认 `_TilingSegmentStage.transition:1906-1908` 直接 `return err_state` → `_read_disk_artifacts` 设 infra `last_error` 即传导；`_DesignSubstage.actions()` 在最前加 `return []` 即终止迭代（与 codegen step-27 A-2 同构）。不引熔断器（保 DEFER「resume 天然重跑」内核），只在本 run 内「首次 infra 即停」。 |
| **层 3** iteration reason | **做**（P7 三分类扩第 4 类） | runner `:323` 已拿 `_agent_res`，`:355` reason 链最前加 infra 分支。 |
| **P94** transcript 留证 | **crash 路径写 crash record**（最小可诊断增强） | seq 覆盖机制复杂且 native session（step-67 pack-run）已兜底；本步只在 except 写一条 crash record，让失败轮 transcript 不再空/无声。 |

依赖：层 1 是层 2/3 的前提（提供 `error_type="infra"` 信号）。P94 独立。

---

## 改动配方

### 层 1 — `capabilities/agent/_shared.py` 扩充 markers

`_INFRA_ERROR_MARKERS`（:342）追加 4 条：

```python
_INFRA_ERROR_MARKERS = (
    "No available channel",
    "Usage limit reached",
    "API Error: 401",
    "API Error: 403",
    "timed out",              # P93: backend HTTP 超时（opencode except str(e)，message_timeout=3600）
    "price not configured",   # P93: 网关模型价格未配置（EN，new-api/one-api）
    "价格未配置",              # P93: 网关模型价格未配置（ZH）
    "Invalid token",          # P93: 网关鉴权 401（P92 旁证，new-api 包装文案不匹配 "API Error: 401"）
)
```

`_classify_error_type`（:350）不动。`_RATE_LIMIT_MARKERS`（429）不动——429 文本不含上述 marker，仍走 `_is_rate_limit_error` 独立路径，不冲突。

**注**：`"timed out"` 子串匹配，crash_reason 是 backend 异常文本（非 agent 输出），误匹配风险低；若 opencode 实际超时异常文本不含 "timed out"，UT 会暴露并补具体 marker。

### 层 2 — `orchestration/stages/design_substages.py`

**2-A `_read_disk_artifacts` infra 分支（:772-775）**：required 缺失时先判 infra。

```python
for fn in required:
    located = _locate_artifact(wd, fn)
    if located is None:
        # P93: agent 因 infra 错误（网关/配置/鉴权/spawn 超时）未产出 —— 不是写错
        # 目录。改报 infra（不写误导性 user_feedback），让 actions() 短路终止。
        if (agent_result is not None
                and getattr(agent_result, "error_type", None) == "infra"):
            return None, self._infra_no_product_error(state, fn, agent_result)
        return None, self._missing_artifact_error(state, fn, wd, transcript)
```

（`agent_result` 在 :762 已取；`transcript` 在 :761-764 已取。）

**2-B 新 helper `_infra_no_product_error`**（紧随 `_missing_artifact_error`，:714 后）：

```python
def _infra_no_product_error(self, state, filename, agent_result):
    """P93: agent 因 infra 错误未产出，非写错目录。与 _missing_artifact_error 的
    关键差别：不写 user_feedback（infra 下重试无意义，不教 agent 修路径）；
    last_error.error_type='infra' 让 actions() 短路终止迭代（step-27 DEFER 收窄：
    设计子阶段补 infra 感知，不引熔断器，resume 天然重跑）。"""
    crash = ""
    metrics = getattr(agent_result, "metrics", None) or {}
    if isinstance(metrics, dict):
        crash = str(metrics.get("failure_reason", ""))
    msg = (f"{self.name}: agent 因基础设施错误未产出 {filename}"
           f"（非写错目录，重试无意义，终止迭代）。原因：{crash}")
    return state.with_updates(last_error=ErrorFeedback(
        stage_name=self.name, error_type="infra", message=msg))
```

**2-C `_DesignSubstage.actions()` infra 短路（:261，置最前，pending_relocation 之前）**：

```python
def actions(self, state, iteration=1):
    # P93 infra 短路（step-27 DEFER 收窄）：上轮 agent 因 infra 错误未产出 →
    # return [] 终止迭代，不烧 budget（配置/鉴权/网关不可达/spawn 超时不会自愈）。
    # 设计子阶段无 sticky 熔断器，resume 天然重跑（保 DEFER 内核）；本守卫仅在
    # run 内"首次 infra 即停"，与 codegen step-27 A-2 同构。
    if (state.last_error is not None
            and state.last_error.stage_name == self.name
            and state.last_error.error_type == "infra"):
        return []
    # artifact-location-provenance: ...（原 pending_relocation 逻辑不变）
```

### 层 3 — `orchestration/kernel/runner.py:355` reason 链

`:355` if-elif 链最前加 infra 分支（复用 `:323` 的 `_agent_res`）：

```python
# P93: infra 错误优先于 contract/quality reason —— 外部基础设施故障不是 agent
# 质量问题，标 infra 让日志/halt 文案指向真凶，不被 "quality check not satisfied"
# 带偏（pipeline-observability P7 扩第 4 类）。
if (_agent_res is not None
        and getattr(_agent_res, "error_type", None) == "infra"):
    _fr = ""
    _m = getattr(_agent_res, "metrics", None) or {}
    if isinstance(_m, dict):
        _fr = str(_m.get("failure_reason", ""))
    self._iteration_reason = (
        "infrastructure error (agent never ran, unrecoverable)"
        + (f": {_fr}" if _fr else ""))
elif not result_state.has_all(output_contract.provides):
    ...（原 contract unsatisfied 分支不变）
```

### P94 — `capabilities/agent/opencode_backend.py:364` except 写 crash record

```python
except Exception as e:
    Logger.error(f"Agent {agent_name} opencode spawn failed: {e}")
    # P94: crash 轮留证——把 crash 原因写进 transcript，避免 spawn-timed-out /
    # fatal 轮 transcript 空文件/无声丢失（native session 兜底见 step-67；此处
    # 至少在工程 transcript 副本留 crash 信号，供 events.jsonl spawn_context 溯源）。
    if transcript is not None:
        self._write_transcript_record(transcript, {
            "ts": start_ms, "type": "crash", "turn": 0,
            "blocks": [], "result": "crashed", "error": str(e),
        }, agent_name)
    artifacts = self._collect_artifacts(effective_cwd, repo_baseline, repo_root)
    return self._build_result(...（不变）)
```

**sdk parity**：检查 `sdk_backend.py` crash 路径是否已留证；若否，补同构 crash record（L4 实施时确认，保持两后端一致）。

---

## 验证（TDD 红→绿）

### 层 1 — `tests/ut/capabilities/test_capabilities.py` `TestInfraClassification`

新增：
- `test_timeout_is_infra`：`_classify_error_type("opencode spawn ... timed out")` → `"infra"`
- `test_price_not_configured_is_infra`：EN `"Model GLM-5.2 price not configured"` + ZH `"模型 GLM-5.2 的价格未配置"` → `"infra"`
- `test_invalid_token_is_infra`：`"Invalid token"` → `"infra"`
- `test_rate_limit_still_not_infra`（回归守护）：`"Request rejected (429)"` → `None`（429 仍走 `_is_rate_limit_error` 独立路径，不被新 marker 误收）

### 层 2 — `tests/ut/orchestration/test_design_substages.py`

新增：
- `test_read_disk_artifacts_infra_no_product`：`agent_result.error_type="infra"` + required 缺失 → 返回 err_state，`last_error.error_type=="infra"`、`user_feedback` 未被设（非路径修正文案）
- `test_read_disk_artifacts_logic_failure_keeps_missing_artifact`（回归）：`agent_result.error_type=None` + 缺失 → 仍走 `_missing_artifact_error`（"写错目录"文案 + user_feedback）
- `test_actions_infra_short_circuits`：`state.last_error(stage=self.name, error_type="infra")` → `actions()==[]`
- `test_actions_missing_artifact_still_retries`（回归）：`state.last_error(stage=self.name, error_type="missing_artifact")` → `actions()` 非空（正常重试）

### 层 3 — `tests/ut/orchestration/test_runner*.py`（或 design workflow integration）

新增：
- `test_iteration_reason_infra`：本轮 `agent_result.error_type="infra"` + 产物缺失 → `_iteration_reason` 含 `"infrastructure error"`，**不含** `"quality check not satisfied"` / `"contract unsatisfied"` 作为主因

### P94 — `tests/ut/capabilities/test_ir_consumer.py`（或 opencode backend UT）

新增：
- `test_opencode_crash_writes_crash_record`：stub serve 让 message POST raise → transcript 末条为 `{type:"crash", error:...}`

### 回归

全量 `pytest -m "not heavy_llm"`（§3.6 默认范围），零回归。heavy_llm 不跑（§3.11，本次改动纯确定性分支，UT mock 覆盖；真实网关故障链路属外部，不在框架验证职责）。

---

## 范围边界（不做）

- 不改外部网关配置（用户职责，[[external-infra-not-framework-responsibility]]）。
- 不重构 marker 集合统一（step-27/57/本步 marker 合并）——另一次工作。
- 不撤销 step-27 DEFER，只**收窄**（补 infra 感知，保「无熔断器/resume 重跑」内核）。
- 不深挖 P94 seq 覆盖机制（native session step-67 已兜底；本步只补 crash record 留证）。
- `message_timeout=3600` 的时长不改（那是另一个独立问题——单轮硬墙；本步靠层 1 把超时判 infra + 层 2 短路，使超时后不再重试，间接缓解；调时长另议）。

---

## 实施结果（2026-07-21，frozen）

四层全部落地，全量 UT **2653 passed / 7 skipped** 零回归（新增 12 UT）。

| 层 | 实际落点 | 与 L4 配方差异 |
|---|---|---|
| 层1 | `_shared.py:_INFRA_ERROR_MARKERS` +4 条；commit `f0d6a805` | 选 A（文本 marker），否决 L3 原推荐的 C（结构化判据）——摸底发现 `timed out` 是 backend HTTP 超时异常（无 statusCode），C 只对网关 APIError 有效、超时类仍需文本 marker；A 与既有三集合范式一致 |
| 层2 | `design_substages.py`：`_read_disk_artifacts` infra 分支 + `_infra_no_product_error` + `_DesignSubstage.actions()` 短路 | 按配方；`_TilingSegmentStage.transition:1906` 直接 `return err_state`，故 `_read_disk_artifacts` 设 infra last_error 即传导 |
| 层3 | `runner.py:355` reason 链最前加 infra 分支（复用 `:323 _agent_res`） | 按配方 |
| P94 | `opencode_backend.py` except（`:559`）补开 transcript + 写 crash record | **机制修正**：摸底发现 `_open_transcript`（`:530`）在 blocking message POST（`:450 _post_message_watched`）**之后**才调，message POST crash 时 `transcript=None`——P94 现象是"第 1 轮根本没创建 transcript 文件"（**非**"被 next iteration 覆盖"，L1 P94 原推断已更正）。故修复是 except 里 `transcript is None` 时当场 `_open_transcript` 补开 + 写 crash record |

### 第 1 轮 60 分钟空等的根因归属

本次故障第 1 轮 POST 60 分钟空等的根因（primary agent 连 engine MCP stdio 握手 hang + `message_timeout=3600`）由 main 的 P-BC3 commit（`bb9b182e`）keepalive + hard-timeout watchdog 修复（[[batch-design-primary-mcp-hang]]）。本步层1 把超时判 infra + 层2 短路，使**超时发生后**不再空烧 3 轮重试 + 不误报；P94 让**超时那一轮**留下 crash 证据。两层正交互补。

### heavy_llm

按 §3.11 本次未跑（改动纯确定性分支，UT mock 覆盖全部分支；真实网关故障链路属外部 [[external-infra-not-framework-responsibility]]，不在框架验证职责）。
