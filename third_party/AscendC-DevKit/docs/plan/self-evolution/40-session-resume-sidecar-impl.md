# 40 — 提案#1：session_id 持久化 + 跨 run resume + 降级（sidecar 方案）（L4 实施方案）

> 工作线：self-evolution
> 状态：**已实施**（2026-07-12）
> 关联 L3：`40-session-resume-sidecar-analysis.md`
> 上游 plan：`/root/.claude/plans/lovely-painting-aurora.md` 方案二

## 数据通路（sidecar，非 State）

> 设计决策（L3）：session_id 不进 State（非错误信息 + hard-kill 时 transition 不跑无法设 State 字段）。改用 sidecar：backend 在捕获 session_id 当下写盘（mid-spawn，强杀前已落盘），clean finish 删。

### `infra/workspace.py`（路径单一权威源，L7）
1. **模块函数 `session_sidecar_path(run_dir, agent_name, branch_label="") -> Path | None`**：`run_dir` 空 → None；否则 `Path(run_dir)/"agents"/f"{stem}.session.json"`（stem = `agent_name-branch_label` 或 agent_name）。L3 stage（持 Workspace）+ L5 backend（持 Path）共用，不漂移。
2. **`Workspace.session_sidecar(self, agent_name, branch_label="")`** 方法（`transcript_path` 之后）：委托模块函数。

### `capabilities/agent/sdk_backend.py`（sidecar 生命周期，L5）
1. **`_SESSION_GONE_MARKERS` + `_is_session_gone(text)`**（`_classify_error_type` 后）：6 个 marker（见 L3）；空 text → False。
2. **`_session_sidecar_path(agent_name, branch_label)`**：委托 `session_sidecar_path(self._decision_workspace, ...)`。
3. **`_write_session_sidecar(agent_name, branch_label, session_id)`**：写 JSON `{"agent_name","session_id"}`，best-effort（try/except 不崩主流程）。
4. **`_clear_session_sidecar(agent_name, branch_label)`**：`path.unlink(missing_ok=True)`，best-effort。
5. **`_spawn` init**（替换 `active_prompt = prompt; active_options = options`）：`resume_session_id` 非空 → `active_options = dataclasses.replace(options, resume=resume_session_id)` + `active_prompt = _RESUME_PROMPT` + `Logger.action("agent_resume", ...)`；否则 fresh。
6. **捕获当下写盘**（`if sid:` 块内，`session_id = sid` 后）：`self._write_session_sidecar(agent_name, branch_label, session_id)`——**关键：mid-spawn 写盘，强杀前已落盘**。
7. **session-gone 降级**（`if not crashed: break` 后，`if not _is_transient_error` 前）：`_crash_text = last_result_text or (str(last_exc) if last_exc else "")`；`resume_session_id and attempt==1 and _is_session_gone(_crash_text)` → warn + `_clear_session_sidecar` + `resume_session_id=None` + 恢复 fresh prompt/options + `attempt=0; no_progress=0; continue`。用 `last_result_text or str(last_exc)`（匹配 crash salvage 模式，session-gone 通常 raise 无 ResultMessage）。
8. **clean finish 清盘**（`finally` 后，`# —— Loop exited` 前）：`if not crashed: self._clear_session_sidecar(agent_name, branch_label)`。

### `orchestration/kernel/action.py`
- **`SpawnAgent.resume_session_id: str = None`**：注释说明——由 codegen.actions 从 resume sidecar 设（`<run>/agents/<agent>.session.json`，backend 在 session_id 捕获当下写，强杀也幸存）；backend 在 session 过期（TTL/gone）时降级 fresh。

### `orchestration/stages/codegen.py`（sidecar 读 → resume 分叉）
- **`actions()`**：`agent_name` 计算上移；`ws = getattr(state, "_workspace", None)`；**sidecar 检查在 staging/materialize 之前**：`session_sidecar_path(ws.dir, agent_name)` 存在 → 读 JSON `session_id`（corrupt → fresh）；非空 → `return [SpawnAgent(resume_session_id=_sid, prompt="[resume] continue interrupted session {_sid}", context={"mode","resume":True}, working_dir, repo_baseline, repo_root)]`（**不重投 skill slash**——session 已有上下文）。无 sidecar / 空 → 现有 fresh spawn 逻辑。

### `orchestration/kernel/runner.py`（透传）
- **`_execute_spawn_agent`**：`backend.spawn(...)` 调用加 `resume_session_id=action.resume_session_id`（末尾 kwarg）。

### `application/dispatcher.py`
- **`_resume_breaker_reset`**（1127）：**无代码改动**（sidecar 非 State，reset 不碰它——正确）。docstring 更新：resume 不再 = fresh attempt——codegen.actions 先查 sidecar 发 session resume，backend 在 session 过期时降级 fresh；sidecar 是 backend 管的磁盘态，非 State。

## 验证（前台 pytest，§3.3/§3.8）

- **UT**（`tests/ut/capabilities/test_session_resume.py`，8 用例）：`session_sidecar_path` 无/有 branch/falsy run_dir；`_is_session_gone` markers；sidecar 在捕获当下写 + crash 后仍在（`SimpleNamespace(session_id="S-CAP-1")` + 写 out.cpp + raise "boom" → partial，sidecar 存 session_id）；clean finish 清（pre-write stale sidecar + clean _spawn → deleted）；resume init 用 resume options（`options.resume=="S-RES-1"` + `prompt==_RESUME_PROMPT`）；session-gone 降级 fresh（首次 query raise "session not found" → 二次 fresh，sidecar 清，result ok）。全绿。
- **UT**（`tests/ut/orchestration/test_session_resume.py`，4 用例）：codegen.actions sidecar 在 → `resume_session_id=="S-RES-1"` + prompt 不以 "/" 开头 + context["resume"]；无 sidecar → fresh；corrupt sidecar → fresh；runner 透传 `resume_session_id=="S-PASS-1"`。全绿。
- **回归**：全量 UT 1839 passed（含 12 新增），0 回归。非 heavy ST 94 passed。
- **fake backend 同步**：29 处 fake backend spawn 签名加 `resume_session_id=None`（protocol 扩展正常 churn）。
- **分层校验**：`test_layer_dependencies.py` 通过——sidecar 路径 helper 在 L7（infra），L3（codegen）+ L5（sdk_backend）均合法导入。

## heavy_llm（§3.11）

- **用例文件**：`tests/st/test_session_resume_e2e.py`（`@pytest.mark.llm` + `@pytest.mark.heavy_llm`，`TestCrossRunSessionResumeE2E` 3 用例）。
- **用例定位**：UT（`test_session_resume.py` capabilities+orchestration）已确定性覆盖 sidecar **接线**（路径/写盘/清盘/actions 读 fork/runner 透传/session-gone markers/降级逻辑）。heavy_llm ST 守护 UT 结构上无法覆盖的**真实链路**（§3.9/§3.10）：真实 claude_agent_sdk session 被 `_spawn` 捕获后，能跨 `_spawn` 调用真正 RESUME（SDK 接受 `resume=<sid>` 且 session 仍有效——非 gone、非降级），以及 resume 进一个不可能存在的 session 真实命中 gone 路径降级 fresh。两者都需真实 LLM 往返；mock `query()` 会架空证明。
- **3 用例**：① `test_fresh_spawn_captures_real_session_id`（fresh _spawn 捕获真实非空 session_id——捕获半边）；② `test_captured_session_resumes_without_degrade`（**核心**：捕获的 sid 回填 resume_session_id → SDK 真实 resume，session 有效不降级，断言 `agent_resume` log 在 + `degrading to fresh spawn` 不在 + status ok/partial/empty_artifacts）；③ `test_bogus_session_id_degrades_to_fresh`（bogus UUID → 真实 SDK 拒绝 → 命中 gone markers → 降级 fresh，断言降级 log + status ok/partial/empty_artifacts；若降级 log 断言失败 = 真实 SDK 对无效 session 的措辞≠`_SESSION_GONE_MARKERS`，需拓宽 markers，是 actionable 信号非 flaky）。
- **设计取舍**：_spawn 级（非 dispatch_single_stage）隔离真实 session 生命周期，省 token；断言走 resume **机制**（`agent_resume`/降级 log via capsys）而非模型记忆（`_RESUME_PROMPT` 覆盖用户 prompt + AgentResult 无 text 字段，记忆召回不可靠）。sidecar-on-disk→actions fork 由 UT 覆盖，ST 不重复。no-tools prompt 故意无产物 → `empty_artifacts` 是合法完成态（仅 `fatal` 算失败）。
- **状态**：**已执行 + 暴露并修复一个真实 bug**（2026-07-12，429 恢复后跑）。详见下节「ST 执行结果 + stderr 盲区修复」。

## ST 执行结果 + stderr 盲区修复（2026-07-12）

429 恢复后执行 3 个 heavy_llm 用例。**首次跑暴露一个 UT 结构上无法覆盖的真实缺陷**（正是 §3.9 real-link ST 的价值）：

- **现象**：用例③（bogus session）`status=fatal`，真实 SDK stderr 打印 `No conversation found with session ID: 00000000-...`，但**降级未触发**。用例①② `status=empty_artifacts`（断言过严漏了这个合法态）。
- **根因**：bogus/expired resume 时 SDK 抛通用 `ProcessError("Command failed with exit code 1", exit_code=1, stderr="Check stderr output for details")`——可操作诊断 `No conversation found...` **只进子进程 stderr，不进异常 message**（SDK 0.2.111 把 stderr 填成占位符）。原 `_crash_text = last_result_text or str(last_exc)` 永远看不到该诊断 → `_is_session_gone` 必 False → 降级不触发 → fatal。光加 marker 没用——诊断不在 `_crash_text` 里。
- **机制确认**（SDK `subprocess_cli.py:532-533`）：`options.stderr is None` → 子进程 stderr 继承 fd 2（到终端不到异常）；`options.stderr` 设了 callback → PIPE + 逐行回调（`_handle_stderr:595`）。
- **修复**（`capabilities/agent/sdk_backend.py`，principled §1.2 可诊断/§1.3）：
  1. `_spawn` 注册 `options.stderr=_on_sdk_stderr` callback（仅当 caller 未设）：累积每行到 per-attempt `_stderr_lines`，**同时 tee 回 `sys.stderr`**（保留终端可见性，不吞 stderr）。
  2. 每个 attempt 顶部 `_stderr_lines.clear()`（fresh 窗口，避免上轮 session-gone 文本污染下轮）。
  3. `_crash_text` 并入 `"\n".join(_stderr_lines)`——异常 message + stderr 都喂给 `_is_session_gone`/`_classify_error_type`。
  4. `_SESSION_GONE_MARKERS` 加宽：纳入 SDK 真实措辞 `"no conversation found"`/`"conversation not found"`/`"no such conversation"`（"conversation" = SDK 的 resumable session 术语）。
  5. `partial`/`fatal` 的 `failure_reason` + `_classify_error_type` 改用 enriched `_crash_text`——死因从通用的 "exit code 1" 变成真实的 "No conversation found..."（可观测性提升；`_INFRA_ERROR_MARKERS` 无冲突，不误判 infra）。
- **UT 补强**：`test_is_session_gone_markers` 加 SDK 真实措辞用例 + `Usage limit reached`（infra）不误匹配 session-gone。`test_session_gone_degrades_to_fresh`（mock 路径 stderr 空，`_crash_text` 退化为纯 exc text）仍绿。
- **验证**：重跑 ST 3/3 全绿（37.78s，真实 LLM）；全量 UT 1858 passed，0 回归。

## 诚实边界

- sidecar 覆盖 hard-kill（session_id 捕获当下写盘），但**不覆盖 capture 之前的 hard-kill**（session_id 还没拿到就杀——此时无 session 可 resume，fresh 是唯一选择，正确行为）。
- session-gone 降级仅 `attempt==1` 首次（rare case：session TTL 过期）；非首次的 session-gone 走原 crash salvage（避免无限降级循环）。
- stderr callback 仅在 caller 未设 `options.stderr` 时注入；当前工程 `_spawn` 自建 options 不设 stderr，故全链路生效。若未来 caller 自带 stderr callback，需链式包裹（当前 guard 跳过，不覆盖该假设场景）。
