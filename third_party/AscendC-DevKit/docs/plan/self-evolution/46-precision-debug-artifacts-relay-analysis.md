# 42 — precision_debug artifacts-relay bug 根治（L3 方案分析）

> 工作线：self-evolution
> 状态：**已拍板冻结 + 已实施**（2026-07-13）
> 关联 L4：`46-precision-debug-artifacts-relay-impl.md`
> 上游 plan：`/root/.claude/plans/lovely-painting-aurora.md`
> L1 事实：`batch-sixops-runlog.md` 事实 9；L1 问题：`06-problems.md` P76

## 问题（事实9）

`PrecisionDebugStage.transition`（`precision_debug.py:235-236`）从 SDK `agent_result.artifacts` dict 读 `debug_result.json`。但 precision-debug skill 用脚本 `write-debug-result.py:28` 写文件到 `<operator_dir>/debug_result.json`（= agent CWD = `state.op_dir`，SKILL.md:123 契约），**从不填 SDK dict**（`sdk_backend.py` 无 artifacts 捕获）。故 dict 读**恒 None** → else 分支假值 `passed=False/max_diff=999/iterations=30` → halt。批跑 rms_norm 精度被冤杀（agent 跑 394 turn / 4064s，worktree 实证 `passed=True/max_diff=0.005423`）。

**判明**：SDK dict 读对本 stage agent 是**死代码**。`agent_result.artifacts` 是真机制——codegen/perf/requirement 的 agent 都填它（codegen.py:690-796 读 codegen_manifest.json/decision_log.json 对的），唯独 precision-debug agent 用脚本写文件。

## 选项

### A. transition 改读 op_dir 文件（删 SDK dict 死读）✅ 选定
transition 读 `<op_dir>/debug_result.json`（`state.op_dir or op_identity.op_dir` 兜底，对齐 P66/24d989f working_dir 解析），删 SDK dict 读。
- ✅ §2.3（skill I/O 契约=文件载体）、§2.5（单通路——每 stage 各守其 agent 机制，删死读非 fallback）、§1.2 可维护（transition 与 skill 契约对齐）/ 可诊断（message 含路径）/ 架构合理（L3 stage 守自身文件接力产物，不渗 SDK 内部）。
- ✅ 零改 skill 侧（写入契约已正确）、零改 parse/routing。
- 代价：transition 读源换（但 parse 逻辑不变）。

### B. 教 skill 填 SDK artifacts dict ✗ 否决
让 precision-debug skill 既写文件又填 SDK dict。
- ✗ §2.1（skill 即插即用、不耦合框架——SDK artifacts 是 SDK 内部机制，skill 不应知）、§2.3（文件是契约载体，再加 dict 是双契约）。
- ✗ skill 取出仓后单跑无 SDK dict 概念，耦合死。

### C. 双源 fallback（先 dict 后文件）✗ 否决
保留 SDK dict 读，文件作 fallback。
- ✗ §2.5（同一职责只允许一条通路——SDK dict 对本 agent 永远空，保留即留死代码/旧债，违反「不留新旧并存」）。
- ✗ §1.4（无向后兼容——不为「万一未来 agent 填 dict」留过渡层）。

## 决策（冻结）

**选项 A**。理由：
1. **机制选择由 agent 决定，stage transition 与之对齐**——precision-debug agent 写文件（skill 便携、§2.1），故 transition 读文件。这是「每 stage 各守其 agent 产出机制」的单通路含义（§2.5），非「全局 dict/文件二选一」。
2. SDK dict 读对本 stage 是死代码（实证 dict 恒空），删而非 fallback（§2.5 + §1.4）。
3. 对齐 P66/24d989f 的 `op_dir` 解析（`state.op_dir or op_identity.op_dir`），transition 读源与 spawn working_dir 同一兜底链，不漂移。
4. 最小改动：只换读源，parse/routing/fail_strategy/skill 全不动。

## 边界（不改）

- **parse 逻辑**（PrecisionDebugResult 构造 238-260）/ **routing**（passed→cannbench_adapt / exhausted→降级）/ **fail_strategy=halt** / **_max_rounds**——只换 `dr_content` 来源。
- **skill 侧**（write-debug-result.py / SKILL.md / main-loop.md）——写入契约 `<operator_dir>/debug_result.json` 已正确，§2.1 不动。
- **SDK artifacts 机制全局**——codegen/perf/requirement 读 dict 是对的，不动。
