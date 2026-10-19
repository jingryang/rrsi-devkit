# Root Cause Analysis: GM Workspace 缺失 sysWorkspaceSize 致 507015（全链路 skill 缺口）

**Date:** 2026-08-04
**Issue:** `ai_infra_aggregate_hidden_grad` precision debug 出现 `ACL stream synchronize failed, error code:507015`（aicore exception），9/20 例崩溃
**Status:** Fixed（skill 全链路修复，未 commit；算子级验证待 heavy_llm 重跑）
**Trigger log:** `output/20260803-135146-96fb95`

## 现象（客观事实）

- `output/20260803-135146-96fb95` 的 `ai_infra_aggregate_hidden_grad`：codegen 编译通过、算子加载成功（11/20 例可运行），但精度仅 8/20 通过；9 例运行期崩溃 `RuntimeError('ACL stream synchronize failed, error code:507015')`。
- 错误码 507015 = aicore exception（`fftsplus aivector error` / `CCU instruction address check error` / `mte error info: 0x10000008c`）。
- precision_debug 多轮（scope_guard/bounds_check/diagnose/printf_location/fix）后停滞于 8/20，未定位到根因。

## 根因（人工实证定位）

**codegen 产出的 `op_host/*_tiling.cpp` 把 `ws[0]` 只设成用户 workspace，漏加系统 workspace（`GetLibApiWorkSpaceSize()`）。**

### 证据

1. `output/.../artifacts/codegen/op_host/ai_infra_aggregate_hidden_grad_tiling.cpp:268-270`：
   ```cpp
   size_t* ws = context->GetWorkspaceSizes(1);
   ws[0] = static_cast<size_t>(workspaceGmSize);   // 只用户量，无 sysWorkspaceSize
   ```
2. 官方契约（知识库 `ascendc-dev-knowledge/.../如何使用workspace.md` + `GetLibApiWorkSpaceSize.md`）：`ws[0] = usrSize + sysWorkspaceSize`。
3. **用户实证**：给该算子 tiling 加上 `+ GetLibApiWorkSpaceSize()` 后 507015 消失、转绿。

### 机理

工程（OpDef）模式下框架在 workspace 总分配前端预留系统区、并把 kernel 入口的 workspace 指针**偏移过系统区**后交给 kernel（知识库「kernel 入口 workspace 为用户的 workspace 指针」）。`ws[0]` 只设用户量 → 总分配 < 偏移量 → kernel 写入落在分配之外 → **GM 越界 → aicore exception(507015)**。

**关键**：该算子只用低阶 API（`DataCopyPad`/`Add`/`Cast`，无 Matmul），仍崩溃——证明此规则**对纯低阶 API 算子同样成立**，比知识库字面「使用 Matmul 等高阶 API 时才需加」的条件性措辞**更强**（工程模式框架无条件偏移系统区）。

### 概念区分（防误改）

- 本次 bug = **tiling 函数的 `ws[0]`**（GM workspace，kernel 用，`op_host/*_tiling.cpp` 里 `GetWorkspaceSizes`）。
- `ascendc-op-dev-coding/SKILL.md:203`「Workspace 计算：通过 executor 图构建获取，不手动估算」= **ACLNN L2 API 层 executor workspace**（`aclnnXxxGetWorkspaceSize`），与 bug 无关、正确、不动。

## skill 全链路缺口（四重）

知识库 `ascendc-dev-knowledge` **有**完整正确契约（`如何使用workspace.md` + `GetLibApiWorkSpaceSize.md` + `GetUserWorkspace/SetSysWorkSpace/GetSysWorkSpacePtr`），但 design/codegen/tips/code-review/docgen **全链路 0 引用、0 范本、0 自检、0 红线**：

| 环节 | 缺口 |
|---|---|
| A3 codegen (`ascendc-op-dev-coding`) | 无 `ws[0]` 写法范本、Step6 自检无 workspace 项 |
| A5 codegen (`ascendc-op-dev-coding-regbase`) | 默认值表 `phase-c-prompts.md:46` 把 workspace 默认成 **0**；B2 selfcheck 只查参数顺序 |
| 设计 (`ascendc-op-tiling-buffer-kernel` + design schema) | 只管 UB 侧 Buffer，0 处教 GM workspace sizing；`design_spec/tiling_strategy/kernel_architecture.json` 无 workspace 字段；docgen `4.x.3.2` 空节 |
| 质量门 (`ascendc-code-review` 红线 / `ascendc-op-design-validate`) | 7 大红线 + TopN、validation_rules 对 workspace **0 覆盖** |
| `ascendc-tips` Memory Management 类 | 9 条全讲 UB/TBuf，0 条讲 GM workspace |

Python codegen **无任何 workspace 模板硬编码**（`src/` 0 命中）——pattern 由 agent 在 skill 引导下自由发挥产出，符合 §1.5/§2.7，故修复在 skill、不在 Python。

## 修复范围（已实施，未 commit）

全链路 skill 教会并自检 `ws[0] = userWs + GetLibApiWorkSpaceSize()`，禁硬编码 16M（权威源是 `GetLibApiWorkSpaceSize()`）：

- A3 codegen `SKILL.md`：Step2 入口校验泛化、Step3 KB 必读加 workspace 文档、Step4② GM workspace 设置 pattern+why、Step6【维9】自检。
- A5 codegen：`phase-c-prompts.md` 默认值表第9行、`per-substage-selfcheck.md` B2 第5项（A5 归同事，已越界授权）。
- 设计：`ascendc-op-tiling-buffer-kernel/SKILL.md`（步骤2 GM workspace 预算 + 自检 + 知识引用）、`schema/tiling_buffer_kernel.json`（`buffer_kernel.workspace` 内层字段）。
- `ascendc-op-design-validate/references/validation_rules.md`：GV11。
- `ascendc-code-review/references/red-line-checklist.md`：TopN2.4。
- `ascendc-tips/SKILL.md`：MM-10。
- `ascendc-op-design-docgen/references/doc_template_v2.0.md`：填 `4.x.3.2` 节。

决策与权衡见 plan 文件 `/root/.claude/plans/temporal-sparking-rain.md`（本次充当 L3/L4）。

## 待验证

- 端到端 heavy_llm：重跑 `ai_infra_aggregate_hidden_grad` 的 codegen→deploy→精度，确认产出 tiling.cpp 含 `+ GetLibApiWorkSpaceSize()`、507015 不复现（§3.11，跑前向用户确认）。
