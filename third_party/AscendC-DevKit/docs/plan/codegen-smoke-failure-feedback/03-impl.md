# L4 实施方案 — 通道不变式 + 进度行 + 三带反馈（TDD，修订版）

> 对应 L3 修订版。改动 1-6；UT 先红后绿。

## 改动 1：rc 形态化 + 单点 failure-context（deploy.py）

- 模块级 `_rc_label(rc: int) -> str`：`rc<0` → `signal {N} (SIG{名})`
  （`signal.Signal(-rc).name`，未知信号回退 `signal {N}`）；`rc>0` → `exit {rc}`；
- `_persist_subprocess_output(..., rc_label="", argv_note="")`：非空时头部加
  `=== rc ===` 行（argv_note 预留同点扩展）；
- `_run_smoke` 失败路径：rc_label 传入持久化 + stderr prefix（`[rc] {label}`）
  + `_err` details 增 `"rc_label"`（结构化，§2.10）；
- build/install 失败路径同样传 rc（单点受益，L3 §2）。

## 改动 2：smoke 子进程 `-u` + script 落盘（deploy.py）

- `[sys.executable, "-u", "-c", script]`（仅 smoke 调用点）；
- script 执行前 best-effort 写 `<ws>/subprocess/smoke_script.py`
  （复用持久化纪律：失败不阻断执行）。

## 改动 3：harness 模板逐用例进度行（判界事实基础）

定位 harness 模板生成处（`_build_smoke_harness` / `_harness_template.py`），
逐用例循环内：

```python
print(f"[case {k}/{N}] start", flush=True)   # 先于该用例一切 op 调用
... fn() ...
print(f"[case {k}/{N}] ok", flush=True)       # 或 error（既有吞异常语义不变）
```

- **start 时机是规格**（L3 §3）：保证「零进度 ⇔ 首用例未开始 ⇔ CPU 侧」；
- 既有 case_details JSON 末行输出与吞异常语义不变（向后消费方不变）。

## 改动 4：env 现场 + smoke_context（deploy.py）

- `_run_smoke` 返回值携 `smoke_context = {rc_label, script_path, env_summary}`；
  `env_summary` = PYTHONPATH / ASCEND_CUSTOM_OPP_PATH / LD_LIBRARY_PATH /
  ASCEND_NPU_ID（框架构造 env 的确定性子集）；
- 透传进 ErrorFeedback.details["smoke_context"]。

## 改动 5：三带反馈渲染（codegen.py）

- `_classify_smoke_phase` 或同层新增**纯函数** `_smoke_band(rc_label, stdout)
  -> band`：从进度行 + rc 派生带标签（zero_progress / mid_case / completed），
  不改路由（三带共用 retry 通路）；
- smoke 失败反馈渲染段按 L3 §4 表格逐带生成：客观事实描述（主体）+ 实证方法
  指令（判界加日志 / 复现现场）+ 出口指引（就地修 / verdict 交棒 / stop-loss）；
- 反馈含复现块：`python -u subprocess/smoke_script.py` + env 四键 +
  「后续自检复用此脚本，勿自建副本」（§2.5 双通路收敛）；
- 前次产物指针：worktree decision_log.json 路径 + known_issues /
  scalar_access_points 计数摘要（读 on-disk，best-effort，缺失省略）；
- stop-loss 注释「~3 轮 ≈ 15 分钟」→ 如实（每轮完整 agent 会话，分钟级起步）。

## 改动 6：无（显式）

带级路由分支 / verdict 与 stop-loss 机制本体 / agent 结论文本搬运 /
resume 编排——均不做（L3 §7）。

## 验证

1. UT（先红后绿）：
   - `_rc_label`：-11 → `signal 11 (SIGSEGV)`；1 → `exit 1`；未知信号回退；
   - `_persist_subprocess_output`：rc 头部行；build 失败路径也带 rc；
   - `_smoke_band`：零进度+signal → zero_progress；start 有 done 无 → mid_case；
     完整 case_details → completed；无 stdout 的 timeout 形态 → 不误判带；
   - `_run_smoke` 失败路径（mock rc=-11 + stdout 含 `[case 2/8] start`）：
     smoke.log 含 rc 行与进度、script 落盘内容一致、details 含 rc_label +
     smoke_context 四键、argv 含 `-u`；
   - harness 模板：渲染产物含逐用例 start/ok 行且 start 先于 fn 调用（模板
     字符串断言）；
   - 反馈渲染：三带各自的文案要素（事实描述/方法/出口）；decision_log 缺失
     省略不炸；复现块含脚本路径与 env；
2. 全量 `tests/ut --quick`；
3. 下批跑自然观测（§3.11 用户决策）：silent 失败首轮反馈是否带 rc+进度+现场；
   中间带 coder 判界执行率（加日志重跑）与 verdict 交棒率；对照 gelu 3 轮基线。

## as-built（2026-08-26 实施完成）

- **signal 覆盖面**：`_rc_label` 经 `signal.Signals(-rc).name` 解析任意信号
  （SIGSEGV/SIGABRT/SIGBUS/SIGKILL/SIGTERM…全枚举内），区间外信号回退
  `signal N`；正 rc → `exit N`（Python 异常/SystemExit）。已验证 -11 与 1。
- **三带简化为「最后打点」**：发现 harness 模板既有 `kernel_done`/`golden_done`
  打点（flush=True，超时归因用）后，band 判定收口为 `_smoke_last_marker`
  提取最后一条打点 + `_render_smoke_facts_lines` 按 marker 条件渲染——
  不做带级枚举分支，事实第一性。
- **打点位置修正（自检缺陷①）**：`start` 在输入生成**前**、`invoking` 在
  `_log_bind` 后紧邻 `_run_kernel`（CANN/FALLBACK 双路径各一处）——输入
  生成段（harness/golden 结构代码，非 coder 产物）崩在 start 后 invoking 前，
  不会误指给 coder 的 glue/device。
- **判界指令与方案 Z 一致（自检缺陷②）**：探针经框架验证循环交付（git diff
  →框架重编译重跑→下一轮反馈携带日志），目标导向不框死手段。
- **`_first_smoke_error_line` 同步收口**：跳过 `===` 结构头行——静默失败的
  首条错误行不再是 `=== stdout ===` 字面量（也无 rc 头污染）。
- **`_smoke_error_signature` 转 classmethod**（引用 `_smoke_last_marker`），
  前缀 `rc_label/last_marker@…`——既有 UT 断言兼容（签名仅前缀扩展）。
- 既有测试适配（§1.4 直改不留旧形态）：`test_deploy.py` 6 处 3 元组解包 →
  4 元组；harness golden（`harness_devkit_golden.txt`）按既有再生成惯例重写
  （含 3 处新打点，55388 chars）。
- **rc 头单行化（补 UT 时发现）**：`=== rc === signal 11 (SIGSEGV)` 单行——
  两行形态会让 `_first_smoke_error_line` 的 fallback 把 rc 值行误当首条内容行；
  单行化后结构行统一以 `===` 开头、按前缀跳过。
- **补 UT 7 例**（盲点收口）：`_err` extra 合并、两收集器含 facts、
  `_build_codegen_prompt` 端到端渲染事实块（transition 级）、
  `_first_smoke_error_line` 跳头两形态。
- **ST（§3.2/§3.6 默认范围，非 heavy_llm）**：`tests/st/test_npu.py` 11 passed
  （真实 harness 执行——新打点/-u 在真机零回归，结果 JSON 解析不变）；
  其余非 heavy 非 npu ST 115 passed；preflight_concurrent_npu_init 3 passed。
  heavy_llm（test_smoke 全流程等）§3.11 待用户决策（在跑批 99c4c0 本身即
  E2E 观测载体）。
- UT：`test_codegen_smoke_feedback_facts.py` 22 例（rc 形态/头行、模板打点
  位置断言、marker 提取、签名含事实、facts 聚合与降级、渲染三形态、
  `_run_smoke` 全通道（script 落盘/env 四键/rc 头/argv -u）、build 单点受益）；
  全量 `tests/ut --quick` **3687 passed**（基线 3658+29，零回归）。
- 待下批跑自然观测：silent 失败首轮反馈带 rc+现场、invoking 段判界执行率、
  verdict 交棒率、stop-loss 触发前收敛率（对照 gelu 3 轮基线）。
