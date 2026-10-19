# batch 20260801-050054-ab7283 — precision_debug 崩溃诚实报告（L3）

> **状态**：已拍板（用户 2026-08-02「按你的建议做」）→ 冻结。本会话实施。
> **来源**：L1 [`batch-...-issues.md`](./batch-20260801-050054-ab7283-issues.md) P4-D2「精确定位」5 缺陷。
> **适用范围**：通用框架改进（NPU runner 崩溃出口诚实报告 + scope_guard 消费硬信号），源于 scatter_pa_kv_cache 案例，方案不限算子/batch。
> **与 D1 的关系**：D1（CANN 路径漏调 get_input，喂入非法 slot）已在 commit `5a5dcdb2` 修掉（共享中段 `_apply_get_input`）。D1 修的是「别喂出导致崩溃的输入」；**本文 D2 修的是「崩溃发生后要诚实报告，不能让下游误判成 golden 缺陷」**。二者正交，D2 是 D1 之外的独立框架缺陷（即使 D1 修了，未来任何 fatal AICORE abort 仍会触发同一误报链）。

## 1. 核心矛盾（事实见 L1 P4-D2，此处只提炼判据）

NPU runner 用 subprocess 隔离跑 kernel（`runner.py:419-423`，`timeout=120`）。fatal AICORE abort 是 C 层 abort，杀的是**子进程**，父进程（runner）存活并写哨兵。问题在父进程写哨兵时**丢了崩溃身份**：

- 子进程被 timeout 杀 / 被信号杀 / 非零退出，runner 都返回**同一个不透明哨兵** `{passed:False, max_diff:999, case_details:[]}`，无 `failure_type`/`returncode`/`timed_out`（缺陷 A）。
- 哨兵的 `error` 字段是 `stderr[:500]` 头截断，砍掉尾巴上的真崩溃关键字（缺陷 B）。
- `golden_used` 字段只在 harness 自己的 `print(json.dumps(output))` 里（进程死在该行之前），从不进哨兵（缺陷 C，首要误报触发）。
- run.log（scope_guard 指定证据）写盘在 timeout 分支被跳过（缺陷 D）。
- CANN 必产的 `exception_info.*` dump（最硬崩溃信号）无人查（缺陷 E）。

下游 scope_guard 只能读这个信息全失的哨兵 → grep 不到 runtime 关键字 → 把「golden_used 字段不存在」读成「golden 没接线」→ 误 HALT(golden)。**根因不在 scope_guard 判得准不准，在 runner 没把崩溃身份传出来。**

## 2. 决策（用户 2026-08-02 拍板）

1. **runner 崩溃哨兵保留失败类型**：crash/timeout 哨兵新增 `failure_type ∈ {runtime_crash, timeout}`、`returncode`、`timed_out`、`crash_dump_path`。三种异常不再坍缩（缺陷 A/C）。
2. **stderr 头尾双留**：保留 `error`（头 `[:500]`，向后兼容可读性）+ 新增 `error_tail`（尾 `[-800:]`）。**决策依据是 `failure_type`，不是 grep 关键字**——stderr 头尾仅作可观测/LLM 上下文（缺陷 B）。
3. **run.log 写盘移到 `finally`**：timeout 分支也落盘，恢复 scope_guard 的证据通道（缺陷 D）。
4. **exception_info dump 存在性检查放 runner**：子进程跑完后扫 `<cwd>/extra-info/data-dump/**/exception_info.*`（mtime ≥ run 起点），命中 → `crash_dump_path` + `failure_type=runtime_crash`。best-effort（cwd 非 op 目录时 glob 落空，failure_type/returncode 仍兜底）（缺陷 E）。
5. **scope_guard 消费硬信号**：SKILL.md verdict 表加一行「`failure_type ∈ {runtime_crash, timeout}` / `returncode≠0` / dump 存在 → **pass**（runtime，本阶段职责）」；加负向规则「不要把 failure_type 标明的崩溃误判 golden——`golden_used` 字段在进程被杀时不写进 result.json，其缺失≠golden 没加载」。

## 3. 两个 tradeoff 的取舍（四把尺子推导）

### Q1：stderr 头尾双留 vs grep 已知崩溃关键字上浮

- **选头尾双留 + 结构化 failure_type 为决策依据**，不选 grep 关键字为决策依据。
- **§1.12**：维护「507035/SIGSEGV/RuntimeError/AICORE/...」关键字白名单 = 耦合 CANN/driver 错误词汇表，新崩溃类型要更新表、漏维护即静默漏判——正是当前 scope_guard 失败的根因。判据一律基于**客观结构信号**（returncode/timeout/dump 存在/failure_type），不认错误措辞身份。
- **§1.3**：头尾双留是可观测性（人/LLM 读得见完整 stderr），failure_type 是决策门——二者职责分离。grep 关键字可作 scope_guard 内部的 best-effort 辅助提示，但**不是**路由依据。
- **排除 grep-as-decision**：违 §1.12 + 脆弱（CANN 版本/措辞漂移即失效）。

### Q2：exception_info dump 检查放 runner 还是 scope_guard

- **选 runner**，scope_guard 消费。
- **§1.12 + §2.9**：dump 存在性是确定性结构检查（文件存在 + mtime 窗口），属**确定性代码**职责，不属 LLM agent 判断。runner 是子进程边界（崩溃出口）的拥有者——「子进程是否致命崩了」天然归它观测；放 runner 让**所有调用方**（precision_debug / codegen smoke / cannbench smoke / ST）都受益，而非仅 precision_debug 分诊。
- **§2.9**：scope_guard **消费** runner 已算好的 `failure_type`/`crash_dump_path`，不重新派生（构造性保证优先于检查门：崩溃身份由 runner 在出口构造性确定，下游忠实消费）。
- **排除放 scope_guard**：把确定性文件检查塞进 LLM prompt = 脆弱（正是当前失败的同类）；且只 precision_debug 受益，codegen/cannbench smoke 仍盲。

## 4. 落地改点

**`src/ascendc_devkit/adapters/npu/runner.py`**（核心）：
- 新增模块级 helper `_detect_crash_dump(run_started_at: float) -> str | None`（best-effort glob `extra-info/data-dump/**/exception_info.*`，mtime ≥ start）。
- 新增 helper `_crash_extras(returncode, timed_out, stderr, run_started_at) -> dict`：算 `failure_type`/`returncode`/`timed_out`/`crash_dump_path`/`error_tail`。
- `execute` 内 `subprocess.run` 前 `run_started_at = time.time()`；把 `result.stdout/stderr/returncode`（及 TimeoutExpired 的 partial `e.stdout/e.stderr`）捕进局部变量。
- run.log 写盘从 `:429-435`（内层 try）移到 `finally`（与 `os.unlink(harness_path)` 同级），保证 timeout 也落盘——内容用捕好的局部 stdout/stderr。
- returncode≠0 哨兵（`:488-495`）+ TimeoutExpired 哨兵（`:496-508`）：合并 extras，保留原 `error`（头）+ 加 `error_tail`（尾）+ `failure_type` 等。

**`.claude/skills/ascendc-precision-scope-guard/SKILL.md`** + **`.claude/agents/ascendc-precision-scope-guard.md`**：
- verdict 表加崩溃/超时行（→ pass）。
- 加负向规则：`golden_used` 缺失在 failure_type=crash/timeout 时不等于 golden 缺陷。
- 输入表加：读 result.json 的 `failure_type`/`returncode`/`crash_dump_path`/`error_tail`。

**不改**：run_tests SKILL（failure_type 直接在 result.json，scope_guard 已读 result.json，无需 run_tests 中转传播）；ScopeGuardSubstage 框架代码（§2.9：不越界替 agent 判定，仅 enum 校验维持）；harness template（D1 已修；崩溃诚实报告归 runner 父进程侧）。

## 5. 四把尺子评估

- **可维护**：failure_type 是客观结构信号，与 CANN 错误措辞解耦（§1.12）；run.log-on-timeout 是纯改善（无语义变化）。
- **可扩展**：任何 fatal AICORE abort（不限 scatter/算子）自动归位 runtime_crash → diagnose，无需逐算子补丁；新调用方（未来 stage）自动继承诚实报告。
- **可诊断**：崩溃出口留下 `failure_type`/`returncode`/`crash_dump_path`/完整 run.log/头尾 stderr 五重可观测信号，diagnose 拿得到 dump 路径直接解码。
- **架构合理**：崩溃观测归 runner（子进程边界拥有者），分诊消费归 scope_guard，层各司职（§2.9）。

## 6. 边界 / 不做

- 不在框架层（ScopeGuardSubstage）做「agent 说 upstream 但 failure_type=runtime → 推翻」的二次裁决（§2.9：框架不替 agent 做语义判断；用确定性信号 + 清晰指令让 agent 判对，而非框架兜底）。
- 不把 dump 检查做成 CANN dump 路径的硬依赖（best-effort glob，落空不报错——failure_type/returncode 兜底）。
- 不改 `timeout=120` 本身（120s 看门狗已正确兜住卡；卡的根因是外部 CANN teardown 死等，非框架可修，见 memory `npu-driver-hdcdrv-hang` / `external-infra-not-framework-responsibility`）。
- 不为「修 scope_guard 偶发误判」加 LLM 重试/多投票（成本高、收益边际；确定性信号到位后信任 agent）。

## 7. 验证（已实施 2026-08-02）

- **UT**：`tests/ut/adapters/test_runner_execute.py` 加 `TestExecutePrecisionVerdict` 内 6 个 D2 用例——signal-kill→runtime_crash / error_tail 保住被头截断的关键字 / timeout→failure_type=timeout + run.log 落盘 / dump 存在→crash_dump_path / dump 缺席无 key / 干净运行不带 failure_type。全文件 31 passed。
- **全量 UT**：3455 passed / 7 skipped（cann-bench parity 需 PYTHONPATH）/ 0 failed（403s，0 回归）。
- **真 NPU ST**（`-m npu`，7 个）：7 passed / 0 failed（108s）——含 `test_npu.py::TestNPURunnerRealExecution` 4 个真机 kernel+golden 用例，验证 c00605ee fixture golden / D1 共享中段 / D2 runner 改动在真 NPU 无回归。
- **heavy_llm 全量**（`-m heavy_llm`，29 个）：29 passed / 0 failed（3654s ≈ 1h）——含 `test_smoke::test_full_pipeline`（全流程 e2e，走 deploy + precision_debug）、`session_resume_e2e`×6、`subagent_dispatch_dual_backend[claude/opencode]`、design TUI selfclosure 全套。7 个本地 commit 在真实 LLM/全流程链路无回归。
- **heavy_llm 覆盖范围说明**：本轮 heavy_llm 验的是 7 个本地 commit（b491123b/5a5dcdb2/924d0438/2e74cb0b/c00605ee/62198428/ddabe8b8）整体在端到端无回归；其中 D2 自身的「scope_guard 读 failure_type 判 runtime 不再误 HALT golden」属 LLM 判定行为,由这套 heavy_llm 间接守护(全流程不崩),精确的 scatter-crash 场景重跑仍可作后续可选节点。
