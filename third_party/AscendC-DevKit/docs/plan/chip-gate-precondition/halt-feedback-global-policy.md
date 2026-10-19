# 专题 — halt / 迭代反馈 全局机制（单一权威源）

> 本文档回应「halt 与迭代反馈缺乏全局视图」的痛点：相关机制散落在 `runner.py` / `graph_executor.py` / `dispatcher.py` / `workflow.py` / 各 stage 的注释里，从未汇总，导致局部设计反复踩坑。本文件是**单一权威源**——遇到 halt/反馈/失败分类问题先查这里，再去翻代码。
>
> 诞生于 chip-gate 前置条件化专题（step-32），但内容是**全局**的（不限于 chip-gate）。`state.py` `ErrorFeedback.error_type` 注释指向本文件。

## 1. 两条 halt 通道（核心区分）

流水线有**两条**终止通道，语义不同，绝不可混：

| 通道 | 触发 | 谁设信号 | 终止表现 | reason 去向 | 典型用途 |
|---|---|---|---|---|---|
| **A. fail_strategy="halt"** | Stage 软失败（transition 产出失败态 / agent 崩）| runner `_run_stage_body` 设 `_stage_failed=(status, stage_name)`（`runner.py:409`） | **不抛异常**；graph_executor `_execute_atomic` 标 `node_status="failed"`（`graph_executor.py:286-288`），`is_terminal` 止遍历 | transition 写 `state.last_error`（ErrorFeedback） | codegen/precision_debug 等「失败即停」的重任 stage |
| **B. PreconditionError** | 前置条件不满足（gate / validate_inputs）| runner 在 spawn 前 `raise PreconditionError(stage, reason)`（`runner.py:183-185` gate、`runner.py:190-193` validate_inputs） | **抛 control-exception**；dispatcher 捕获（`dispatcher.py:677-688`）：`Logger.error(stage+reason)` + rollback + snapshot + report + `EX_DATAERR`，**无 traceback** | reason 在异常对象 + dispatcher 日志/报告；**不落** `state.last_error` | requirement underspec、codegen chip-mismatch（step-32） |

**关键不变式**：
- 通道 A 的 reason 进 `last_error`（下游/报告可读）；通道 B 的 reason **不进** `last_error`（与 requirement.py PreconditionError precedent 一致——precondition 类 reason 本就不落 last_error，resume 时 `validate_inputs` 重新无状态判定）。
- 通道 B 是 control-exception：`graph_executor._control_exceptions()`（`graph_executor.py:294-303`）含 `PreconditionError`，`_execute_atomic` 对其 re-raise（不进 except 分支、不合成 last_error）。
- **硬崩溃**（非 control、非软失败）：走 `_execute_atomic` except 分支（`graph_executor.py:240-273`），见 §3 `_classify_uncaught`。

## 2. 两类失败（halt-class vs selffix-class）

`error_type` 分三类，决定「重试有没有意义」：

| 类 | 语义 | error_type | 处置 |
|---|---|---|---|
| **halt-class（不可修）** | 重试无解——环境/基础设施/状态层缺陷 | `infra`、`framework`、`chip_mismatch`、`env_probe_timeout` | halt（不 loopback） |
| **selffix-class（可修）** | 改码/补产物可修 | `schema_violation`、`incomplete_output`、`deploy_failed`、`missing_artifact`、`integration_incomplete` | loopback 自修，`exhausted→__halt__` 兜底 |
| **gray-zone（兜底）** | 未归入上述任一 | `unclassified` | loopback（宁可烧 token 不漏修），由该 stage 自身 `exhausted→__halt__` 止损 |

> `design_needs_human` **不是** error_type——它是 `workflow.py:255,259` TRANSITION_TABLE 的**路由键**（`("__halt__","escalation")`）。混入 error_type 词表是常见误读。

**判据只有一条**（§1.2）：*这个失败改 code 能修好吗？* 能 → selffix；不能（环境/网关/状态损坏/硬件不匹配）→ halt；不确定 → gray-zone 兜底 loopback。

## 3. 信号通道（错误如何被观测）

| 通道 | 内容 | 设置点 |
|---|---|---|
| `state.last_error`（ErrorFeedback） | 分类后的失败类 + 具体消息 + details | transition（软失败）/ `_execute_atomic` except 分支（硬崩溃，`graph_executor.py:257-259`） |
| 异常对象（PreconditionError 等） | reason 串 | runner `raise`（`runner.py:183-193`） |
| `subprocess/*.log` | 编译/smoke 的**完整** stdout+stderr | `Deployer._run_command` 持久化（deploy.py，旧 `[:1500]` 截断已删） |
| `events.jsonl` | 运行历史权威记录（`stage_enter`/`stage_done`/`stage_aborted`/`stage_iteration`） | runner `_run_stage_body`（`runner.py:114-117` 记 `stage_aborted(error_type=type(e).__name__)`——**异常类名**，非 ErrorFeedback.error_type） |

**注意两套 `error_type` 同名异物**：
- `ErrorFeedback.error_type`（state.py）——分类失败类（§2 词表）。
- `stage_aborted` event 的 `error_type`（events.jsonl）——**原始 Python 异常类名**（`type(e).__name__`，如 `"PreconditionError"`、`"TimeoutError"`），由 runner 包装器对**任何**未捕获异常记录（`runner.py:115-116`）。后者是「兜底观测」，比前者更宽。

## 4. `_classify_uncaught` —— 硬崩溃的兜底分类（已做对）

`graph_executor.py:119-135`：硬崩溃（非 control 异常）经 `_classify_uncaught(e)` → `infra` | `framework` | `unclassified`，写入 `last_error.error_type`（`graph_executor.py:254-259`），消息恒为 `f"{type(e).__name__}: {e}"`（**具体异常类名+消息全保留**）。

- `infra`：复用 agent 层 `_classify_error_type`（`sdk_backend.py`，识别 503/429/401/403/无通道/配额——**LLM 网关类**，非 CANN/NPU 缺失）。
- `framework`：`_FRAMEWORK_STATE_MARKERS`（`graph_executor.py:107-116`）——「dict/list/str/... has no attribute」签名 = state 反序列化层 bug（code 期望 domain object，拿到 Python primitive），codegen 改不了。
- `unclassified`：灰区兜底 → `_is_non_fixable` 为 False → loopback（`graph_executor.py:270-272` 走 `on_uncaught_failure`），由 stage 自身 `exhausted→__halt__` 止损。

**这就是「unknown 兜底」，且做对了**（§1.2 组合）：桶是 `unclassified`（灰区，不静默吞、不无限转），但 message 带具体异常类名——**信息零丢失**。**不需要**再叫一个 `unknown_error`：会与 `unclassified` 重复成第二套词（§2.5），且 `unknown` 的命名暗示「抹掉信息」，与现状（保具体异常）相悖。

## 5. halt vs 自修 —— 决策判据（何时该 halt）

新增一个失败处理点时，按此决策：

1. **是前置条件吗？**（spawn 前就能判、不产出工件、不消费 iteration）→ `validate_inputs` 返回 reason → 通道 B（PreconditionError）。例：chip-mismatch、requirement underspec。
2. **重试无解吗？**（环境/网关/状态层）→ halt-class（infra/framework/chip_mismatch）。通道 A（fail_strategy=halt）或通道 B，取决于是软失败还是前置。
3. **改码可修吗？** → selffix-class（loopback），`exhausted→__halt__` 兜底。
4. **不确定？** → gray-zone（`unclassified`），loopback 兜底（宁可烧 token 不漏修），止损防无限。
5. **判断（precondition）vs 任务（task-node）？** 判断归 `validate_inputs`/helper（可随处调用的小工具），**不**新立 stage——stage 是承担重任的任务节点（用户判据，见 `02-analysis.md` §为什么是 precondition 语义）。

## 6. chip-gate 在这套机制里的位置（step-32 落地）

- **主路径（pipeline）**：`codegen.validate_inputs` 调 `chip_mismatch_reason` → 通道 B（PreconditionError）→ 干净 halt，codegen 永不 spawn。halt-class（chip_mismatch）。
- **深防路径（redeploy CLI / 直接调用）**：`Deployer.deploy()` 调同一 helper → `ErrorFeedback(error_type="chip_mismatch")` → halt-class，与 `deploy_failed`（selffix）泾渭分明。
- 共享 helper `detect.chip_mismatch_reason` 是「判断+消息」单一来源（§2.5）。

### 6.1 驱动探机超时 + `--assume-chip` 旁路（§3.7 driver-hang，step-32 收尾）

`detect_chip_version()` 的 torch_npu 探机（`device_count`/`get_device_name`）偶发卡在内核态 `hdcdrv_connect_wait_reply`（无 timeout、不抛异常，观测过 0.05s / 7.4s / 13min+ 三态）。**§1.2 组合**落地：

- **主修复（保不变式）**：探机包进 daemon 线程 `join(timeout_sec)` **有界**——超时 `raise EnvironmentProbeTimeout`，**不**静默回退错代际（§3.7：诚实报，不掩盖成 wrong-chip）。界在 detect 这一层加，故**所有调用点**（dispatcher auto-detect / `codegen.validate_inputs` / `Deployer.deploy`）统一受护（§1.2 可扩展）。
- **两条 halt 通道**（同 chip_mismatch）：
    - pipeline：`codegen.validate_inputs` 捕获 `EnvironmentProbeTimeout` → 转 PreconditionError → 干净 halt，codegen 永不 spawn。
    - 深防：`Deployer.deploy()` 捕获 → `ErrorFeedback(error_type="env_probe_timeout")` → halt-class。
- **不混淆失败类（§1.2）**：`env_probe_timeout`（驱动 hung，环境失败）、`chip_mismatch`（代际不匹配）、`deploy_failed`（compile/smoke，可修）三者泾渭分明——这正是本专题 P2 修掉的「两类失败混于 deploy_failed」的同源约束。
- **宽容兜底（`--assume-chip`）**：`state.assume_chip` 非空 → `detect_chip_version(assume_chip=…)` 跳过探机、用声明值喂比较——驱动抽风但用户确知本机代际时的逃生口。旁路**喂比较、不抑制**：`target≠assume` 仍报 mismatch。
- **超时界可调**：`orchestration-config.json` `timeouts.hw_probe_sec`（默认 10s，须 >0）经 `runtime_config.hw_probe_timeout_sec()` 由 **L3 调用方**传入 **L4 detect**（§1.1：detect 不反向 import config 模块）。默认值单一来源 `detect._DEFAULT_HW_PROBE_TIMEOUT`，config 导入之、不复制。
- dispatcher auto-detect 路径（`target_chip` 无显式值时探机）也接同界：探机超时 → `Logger.error + EX_DATAERR` 干净退出，不抛 traceback。

## 7. 词表总表（grounded，2026-07-10 核实）

`ErrorFeedback.error_type` 实际出现的全部取值（grep `src/` 字面 + 动态分类器）：

```
halt-class:    infra, framework, chip_mismatch, env_probe_timeout
selffix-class: schema_violation, incomplete_output, deploy_failed,
               missing_artifact, integration_incomplete
gray-zone:     unclassified
（design_needs_human = TRANSITION_TABLE 路由键，非 error_type）
```

来源：
- 字面赋值：`schema_violation`(×7)、`incomplete_output`(×4)、`deploy_failed`(×4)、`infra`(×2)、`missing_artifact`(×1)、`integration_incomplete`(×1)。
- 动态分类器：`_classify_uncaught` → `infra`/`framework`/`unclassified`（`graph_executor.py:119-130`）。
- 新增：`chip_mismatch`（step-32，deploy 深防路径；pipeline 路径走 PreconditionError 不落 error_type）。
- 新增：`env_probe_timeout`（step-32 收尾，driver-hang 有界探机超时，deploy 深防路径；pipeline 路径走 PreconditionError 不落 error_type；与 `chip_mismatch`/`deploy_failed` 三分）。
