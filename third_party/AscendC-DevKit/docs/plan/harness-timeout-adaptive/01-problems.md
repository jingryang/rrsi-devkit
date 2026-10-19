# 测试超时自适应 + scope_guard 职责边界 — L1 问题记录

> 层级：**L1 / 问题记录**。只陈述「哪里坏、凭什么这么说」（证据/现象/影响）。
> **不提方案、不排顺序、不写决策**。方案分析见 `02-analysis.md`（L3）；实施方案随 L3 落地。

与现有工作的边界：
- `cannbench-adapt-timeout-gap/` 是 **workflow 级超时**在 `CannbenchAdaptStage` 处断裂（D6 `uninterruptible` 漏声明），属于调度层软放行链路。本记录的 P1 是 **NPU 测试 harness 子进程看门狗**（`subprocess.run(timeout=120)`），是测试执行层的超时，不同层级、不同对象。
- `precision-env-blocker/` 记录环境缺陷（如 `decorator` 缺失）识别但无终止出口；本记录的 P4/P5 与其联动（run_tests 传递环境信号 → scope_guard 判定暴露）。

---

## P1（高）：NPU 测试 harness 子进程看门狗硬编码 120s，全仓唯一不可配置的测试超时

### 现象

`src/ascendc_devkit/adapters/npu/runner.py:500` 的 `subprocess.run(..., timeout=120)` 是测试执行唯一的看门狗。仓库其余超时（workflow / stage / deploy / eval）均有 CLI / config / env 入口，唯独它无任何配置入口。

### 证据

- `runner.py:498-502`：`subprocess.run([sys.executable, harness_path], capture_output=True, text=True, timeout=120, env=run_env)`——120 为硬编码字面量。
- grep 全仓：`timeout=120` 仅此一处与测试执行相关；`cannbench_scorer.py` / `deploy.py` / `codegen.py` 等其余超时均有对应 loader 或 CLI 参数。
- 大 shape 用例（如 `ScatterPaKvCache` input `[17, 4112, 8, 16]` ≈ 8.9M 元素，或更大）真实耗时可能超过 120s，但调用方无法调大。

### 影响

- 大 shape 算子无法稳定跑通精度测试；调用方没有手段给足超时。

---

## P2（高）：超时被当普通 runtime 失败进 diagnose→fix 精度循环，浪费预算且无法如实反馈

### 现象

超时触发后，runner 返回 `{passed: False, failure_type: "timeout"}`，用例进入 `failed_case_queue`，`failure_type` 归类为 `runtime`，precision_debug 循环把它当 kernel 运行时缺陷做 diagnose→fix。

### 证据

- `runner.py` catch 块（`subprocess.TimeoutExpired`）：返回 `passed=False`、`max_diff=999.0`、`failure_type="timeout"`（经 `_crash_extras`）。
- `build-failed-case-queue.py` 的 `_initial_failure_type`：case 带 `error` 字段 → 返回 `"runtime"`；超时用例带 error → 归 runtime。
- 探索报告：超时归 runtime，进 `failed_case_queue` 后诊断循环尝试 diagnose→fix→printf。

### 影响

- 大 shape 超时被误判为 kernel 缺陷，消耗 diagnose/fix/printf 预算；用户看到的是「精度/运行时失败」而非「超时（shape 过大 / 环境 / 死锁）」的真实原因。

---

## P3（中）：超时时 `case_details` 为空，shape 信息丢失，无法判断「是否大 shape 超时」

### 现象

harness 子进程超时死于最终 `print` 之前，runner 返回 `case_details: []`。`build-failed-case-queue` 对超时用例只能记 `shape="N/A"`，下游无法判断本次超时是否因 shape 过大。

### 证据

- `runner.py` catch 块返回字面量 `"case_details": []`。
- `build-failed-case-queue.py` 从 `case_details[].input_shapes[0]` 提取 shape；空列表 → 无法提取 → 硬错误路径记 `shape="N/A"`。

### 影响

- 判断「大 shape 超时 vs 环境/死锁超时」缺客观依据；即使要自适应放大超时重试，也无从决策。

---

## P4（中）：run_tests 发现的问题观察无统一传递机制，无法如实传递给 scope_guard 判定

### 现象

run_tests 阶段能观察到各类问题信号（二进制/dtype/format 匹配失败、编译错误、测试脚本报错、golden 缺 get_input、环境初始化失败、超时归因），但**没有结构化载体**把这些观察如实传递给判定方。

### 证据

- `precision_run_tests.json` 的 `_summary` 仅要求 `failure_type` / `test_result` / `failed_count` / `total_count` / `max_err` / `last_run_log`，无观察清单字段。
- `scope_guard` 当前只在首轮跑（`resolve_condition` 的 `needs_scope_check` 依赖 `scope_checked != true`），循环中 run_tests 新暴露的信号没有触发重判的机制。
- 实测案例（2026-08-02 scatter_pa_kv_cache）：run.log 出现 `Cannot find any bin for input 1 with [storage format 2, primary format 2]`，run_tests 无路径把它传递并触发判定，只能当普通失败继续精度循环。

### 影响

- 上游产物 / 环境缺陷在循环中被当作 kernel 缺陷反复尝试，浪费预算且不向用户暴露真实归属。

---

## P5（低）：scope_guard 判定输入不全 + 日志不够详细

### 现象

scope_guard 的判定依据主要是 `result.json` 的结构性崩溃身份 + `run.log`；对超时归因（大 shape vs 环境/死锁）、run_tests 观察到的信号类别没有结构化输入；`scope_verdict.json` 的 `evidence` 是字符串列表，缺少「日志行号 + 信号原文 + 判定依据」的逐条可审计结构。

### 证据

- `scope-guard/SKILL.md` 判定规则表：基于 `failure_type` / `returncode` / `crash_dump_path` / run.log 关键词，无 `observed_issues` 消费。
- `scope_verdict.json` schema example 的 `evidence` 为 `["control.json history[0].failure_type=compilation", "run.log:42 '...'"]` 字符串列表。

### 影响

- 判定过程难审计、难向用户解释「为什么判上游/pass」；超时类问题没有明确的判定指引。
