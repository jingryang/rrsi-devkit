# infra/未知失败默认有界重试（fail-open）— 实施（L4）

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md`（B），事实见 `01-problems.md`（P1/P2/P3）。
> 反散弹（§2.5）：分类、结果构造、重试谓词、重试决策各只有**一个权威实现点**；marker 列表降级为诊断标签。

## 改动清单（4 个单一职责点）

### 1. 单一分类点（fact）— `capabilities/agent/_shared.py`

新增纯函数，两 backend 共用：

```python
def classify_spawn_exception(exc, crash_reason):
    # 连接异常按类型判（RemoteDisconnected / ConnectionResetError / httpx.TransportError…）
    if isinstance(exc, (ConnectionError,)):   # 覆盖 http.client.RemoteDisconnected 等
        return "infra_transient"
    return _classify_error_type(crash_reason)  # 复用现有永久 marker，不动
```

- `error_type` 由二值（None/`"infra"`）扩为三值（+`"infra_transient"`），§1.4 不向后兼容：直接改干净、不留 alias。
- 按**异常类型**不按文案：`Remote end closed connection without response` 文案变体几十种，类型判定一次覆盖。

### 2. 单一结果工厂（已存在）— `capabilities/agent/base_backend.py:_build_result`（:265）

不改签名。`error_type_override` 现由 backend 传入；backend 的 `except` 块把 `_is_hard_timeout_exc(e)` 得的
`aborted` **照旧**，**另**把 `classify_spawn_exception(e, str(e))` 作为 `error_type_override` 传入（两值正交、互不冒充）。
`:298-311` 的 `_classify_error_type` 兜底保留。backend 侧改动（opencode `:851` / sdk 对应 `except`）只是**调用**
共享函数，不复制逻辑。

### 3. 单一重试谓词（policy）— `capabilities/agent/_shared.py`

```python
def is_infra_failure(result) -> bool:
    return (result.status in ("partial", "fatal")   # crash（_build_result 里仅 crashed=True 产生）
            or result.aborted is not None            # 被杀活 spawn
            or result.error_type is not None)        # 环境故障(infra / infra_transient)
```

- `empty_artifacts`（干净跑完、无产物）是 logic，**不**进此谓词；`cut` 有自己的 cut-streak 机制，也不进。

### 4. 单一重试决策点 — `orchestration/kernel/runner.py`

- **P131c 循环（:354-381）**：进入条件 `_abort = result.aborted` 改为 `if is_infra_failure(result)`；
  teardown 仅 `aborted` 非空时跑（连接重置不回滚 op_dir）。
- **P116 块（:433-442）删除**：永久 infra「立即 `is_terminal`」被上面的有界重试接管（先烧预算、耗尽才 halt），
  删掉旧「立即 halt」通路（§2.5 删旧债）。
- **`fail_strategy=halt` 判定（:613-618）不变**：仍只对 logic + design halt 语义生效；infra 失败走重试→耗尽 halt。

## 顺序

1→2→3→4 无跨文件顺序依赖，建议按 1→4 依次落地，每步补对应 UT。

## 验证（TDD，先红后绿）

**UT — `tests/`（`test_shared` / `test_base_backend` / `test_runner` 对应文件）**：
- `classify_spawn_exception(RemoteDisconnected(...), ...)` → `"infra_transient"`；`(None, "API Error: 401")` → `"infra"`；`(None, "foo")` → `None`。
- `is_infra_failure`：partial/fatal → True；`empty_artifacts` 无 aborted/error_type → False；`cut` → False。
- runner：`infra_transient` → 进重试 → 预算耗尽 → halt（带「retried N×，<reason>」）；`aborted` 仍重试且触发 teardown；
  永久 `"infra"` → 有界重试后 halt（不再首见即 halt）。

**回归**：现有 `base_backend` / `_shared` / `runner` 全量 UT 绿；重跑本次 grid_sampler_3d 场景确认「连接重置」
从「halt」变为「重试后收敛或诚实 halt」。

## 为什么不是散弹

| 职责 | 权威实现点 | 数量 |
|---|---|---|
| 异常→业务类 | `_shared.classify_spawn_exception` | 1 |
| 结果构造 | `base_backend._build_result`（已有） | 1 |
| 重试谓词 | `_shared.is_infra_failure` | 1 |
| 重试决策 | `runner` P131c 循环 | 1 |

## 实施状态

**✅ 已实施（2026-08-14）**。落地时的实际改动（比初稿多出「兜底 + 下游消费方」两处，见下）：

### 实际改动清单（相对初稿的修正）

1. **`_shared.py`**：新增 `classify_spawn_exception`（异常类型→error_type）、`is_infra_error_type`
   （error_type 值是否 infra 类）、`is_infra_failure`（AgentResult 是否「没干成活」，只看 error_type/aborted）。
2. **`base_backend._build_result`**：error_type 三值化，并新增**兜底**——`crashed` 且无 marker、无 aborted、
   也非连接异常 → `error_type="infra_transient"`（未知 crash 也归瞬时，默认有界重试）。
3. **backend（opencode `:851` / sdk `:769`）**：崩溃 `except` 块调 `classify_spawn_exception` 传
   `error_type_override`（与 `aborted` 正交，互不冒充）。
4. **`runner.py`**：P131c 循环进入条件 `_abort` → `is_infra_failure`；teardown 仅 `aborted`；P116 块
   改为「补诚实诊断 reason（bounded retry exhausted）」，不再「首见即 halt」；`_last_infra` 用 `is_infra_failure`。
5. **下游消费方（6 处 `error_type == "infra"`）**：`requirement.py` / `codegen.py`（×2）/ `design_substages.py`
   （×2）/ `dispatcher.py` 改为 `is_infra_error_type(...)`，且 last_error 传播改为透传实际 error_type
   （`infra_transient` 不再被降级成 `"fatal"`）。

### 测试

新增 `test_fail_open_retry.py`；改 `test_p125`（未知 crash 兜底 + logic 用 crashed=False）、`test_p116` 与
`test_stage_failure_status`（infra 现走有界重试 → `_no_sleep` + spawn 数 1→5）、`test_infra_backoff_resume`
（新增 infra_transient 连接重置重试用例）、`test_capabilities`（未知 crash → infra_transient）。
