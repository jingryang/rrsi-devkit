# 41 — 第5类隐患根治：build 输出扫描器（L4 实施方案）

> 工作线：self-evolution
> 状态：**已实施**（2026-07-13）；UT 1885 全绿，ST 非 heavy 101 passed（2 预存失败与本方案正交）
> 关联 L3：`45-build-output-scanner-analysis.md`
> 上游 plan：`/root/.claude/plans/lovely-painting-aurora.md`

## 改动（函数级）

### `domain/build_log_scanner.py`（新建，纯函数模块）
`deploy.py:_run_command` RC=0 分支的「真传感器」。匹配 CANN 工具链诊断模式（asc_opc/TBE/clang），非算子知识（§1.5）。

1. **`KernelCompileError`**（frozen dataclass）：`op_name` / `source`（`op_kernel/<file>:<line>`）/ `message`（编译器原文）/ `kernel`（哈希名）。与 domain 其它领域对象同为 frozen。
2. **`scan_kernel_compile_errors(text) -> list[KernelCompileError]`**：
   - **真信号**：A7 clang error 行 `op_kernel/<file>.h:<line>:<col>: error: <msg>`（最具体，按 `(file,line,msg)` 去重——CEL 实测 6 tiling_key × 5 位置 = 30 次 → 去重 5 条）；A2 `Op[<op>] of index[<n>] compile failed` 取 op 名；A4 `Kernel Compilation Error: OpType <op>` 兜底 op 名。
   - **良性排除**：`WARNING: ... may have errors`（`||` 触发器非错误）、`Opc tool start working`（成功时也有）、clang `note:`（候选上下文）、`CMake Warning`/`Built target`/`Succeeded`。CMake/ld.lld/`No run package` 不匹配（那些是 host 链接错误，RC≠0 已由现有通路捕获，不属 kernel 编译失败）。
   - **兜底**：无 clang error 行但有 A1(`Opc tool compile failed`)/A2/A4 marker → 返回一条通用错误（op 名从 A2/A4 取）。
   - **空**：无任何真信号 → `[]`（干净 build 或仅良性信号）。
3. **`format_kernel_error_summary(errors) -> str`**：`op 名 + (N errors)` + 前 8 条 `source message`，超出截断。供 `ErrorFeedback.details['stderr_tail']`，agent 在 redeploy CLI 输出即可见要点。

### `orchestration/stages/deploy.py`
1. **import**（37 区）：`from ascendc_devkit.domain.build_log_scanner import (format_kernel_error_summary, scan_kernel_compile_errors)`。
2. **`_run_command` RC=0 分支**（原328-332 `return True, "", None` 之前）：`if stage.role == "build":` 扫描 `(r.stdout or "") + (r.stderr or "")`；命中 → `_persist_subprocess_output` 落盘 + `return False, format_kernel_error_summary(errors), log_path`（**复用 RC≠0 通路**）。
   - 只扫 `build` role（install/smoke 输出无 kernel 编译信号，避免误报+性能）。
   - 命中后 `_run_profile_chain` build 循环（deploy.py:418-424）现有 `if not ok` 捕获 → `_err("build", summary, log_path)` → `DeployResult(smoke_passed=False)` → redeploy CLI 返回 agent → agent 读 `subprocess/*.log` 自修（codegen.py:637 prompt 已指向该目录）。

## 不改（关键边界）
- `codegen.py` / `transition` / `DeployResult`（verification.py）/ `_persist_subprocess_output` / `_err` / `_run_profile_chain` —— in-session 自修反馈通路本就完备，只缺 `_run_command` 这个传感器在 RC=0 时失明。扩 DeployResult 字段（候选 C）多余：`smoke_passed=False` 已够 transition halt。

## 实施顺序（TDD，§3.1）
1. `tests/ut/domain/test_build_log_scanner.py`（11 用例：真实 CEL 片段命中 5 error / 良性返回空 / 空文本 / clang 去重 / note 不误报 / 兜底 / CMake 不误报 / frozen / summary 三例）→ 实现 `build_log_scanner.py` → 绿。
2. `tests/ut/orchestration/test_deploy.py` 加 `TestRunCommandDetectsSwallowedKernelCompileFailure`（4 用例：RC=0+kernel错→False+落盘 / RC=0干净→True不误报 / 无ws仍False / 非 build role 不扫描）→ 改 `_run_command` → 绿。
3. 全量回归：UT 1885 + 非 heavy ST。

## 验证
- **UT**：全量 **1885 passed**（含新增 15：scanner 11 + deploy 4），零失败。
- **ST（非 heavy，§3.6）**：**101 passed, 5 skipped, 2 failed**。2 failed 均在 `tests/st/test_resume_cli.py`（`test_resume_without_workflow_succeeds` / `test_resume_conflicting_workflow_returns_usage`），根因 = resume CLI 把「不一致」/「All stages already completed」经 `Logger` 写 **stderr**，UT 却断言 `result.output`（stdout，click CliRunner 默认 stdout/stderr 分离）——**契约对象错位 + test isolation**（`git stash` deploy.py 改动后仍 1 failed、另 1 反转 passed，证明与本方案正交、非本方案引入）。属 resume CLI/UT 的独立维护项，不混入本方案（§1.8 一事一产权）。
- **heavy_llm（§3.11）**：本改动不改 LLM 链路（只让信号可见，in-session 自修循环行为不变）。端到端「codegen 自修 kernel 编译失败」验证属 heavy_llm，**未跑**（待用户决策）——待跑项：人造 kernel API 错 → 跑 codegen → 断言 agent 读落盘日志后修好 → smoke 真·绿灯。**本次未覆盖 heavy_llm：codegen 自修 kernel 编译失败端到端**（诚实记录，§3.11）。
