# 56 — PR#10 review 第二轮复核 + 整改完成记录

> 工作线：self-evolution / precision-debug skill 拆分收口
> 性质：**L1 + L4 合记** —— 第二轮 review 的事实快照 + 整改完成状态。
> 状态：**已整改完成（2026-07-19）**。
> 来源：仓外 review `/home/g00940185/PR-10-review-0719`（第二轮 · 更新后复核，head `62dd42d`）。
> 关联：L1 `55-precision-debug-review-problems.md`（首轮，head `22d7877`）、L4 `55-precision-debug-review-fixes-impl.md`。

## 第二轮 review 摘要

- **分支/HEAD**: `pr-10-review` @ `62dd42d`（forced update from 昨日 `22d7877`）
- **基线**: main @ `d047b38` ｜ **规模**: 75 files, +7726/−3933
- **Verdict**: `request_changes`（昨日 `reject` → 3 blocker 基本修通，2 major 待收尾）
- **测试**: UT 2381 passed / 8 skipped
- **同事整改方案**: `55-precision-debug-review-{problems,fixes-impl}.md`（L1+L4，reviewer 评价「质量高」）

## 第二轮主要发现（promote 为待收尾 major）

### F1 — skill 文档 prose 层残留「谁写 history」自相矛盾

- **已修好**: heredoc 骨架统一改为「禁止 `cp["history"].append`，写 `_summary`」
- **残留**: prose 描述层 10+ 文件同文件内矛盾（如 run-tests/SKILL.md:23 写 "history（追加本轮）" vs :61 "禁止直接修改"）
- **影响**: LLM 读到矛盾措辞，行为不可预期

### M2 — harness 形态校验漏网

1. `shape=None` 漏网 — `if shape is not None and not (...)` 软化，shape 缺失静默通过
2. numeric attr 零校验 — `_validate_case_form` 对 `tc.attrs` 不验
3. 无 `[PD-CONTRACT]` 分类 — caller 链 generic `except` 吞前缀

## 整改结果（2026-07-19 全部完成）

| 项 | 级别 | 状态 | 说明 |
|---|---|---|---|
| **F1** prose 扫描 | major | ✅ 已修 | 14 文件统一：agent 写 `_summary`，框架物化 history |
| **M2** harness 形态校验 | major | ✅ 已修 | 收紧 `_validate_case_form` + 新增 `_validate_attrs` + `[PD-CONTRACT]` 前缀 + op_spec plumbing |
| N1 scope-guard 嵌套同步 | minor | ✅ 已修 | 静态文档同步 `history[-1].content.failure_type` 嵌套路径 |
| N5/N6 `best_max_err` 别名 + `import re` | nit | ✅ 已修 | 全仓统一为 `best_real_max_err`；`import re` 置顶 |
| N7 文档状态回填 | minor | ✅ 已修 | 55-fixes-impl.md 状态「已实施」；54-impl.md §10 as-built 回填 |
| N2 init-checkpoint.py 注释 | trivial | ✅ 已修 | "each phase appends" → "framework materializes" |
| N3 inputs=None 静默 | minor | ✅ 已修 | 含在 M2 `_validate_case_form` 收紧中 |

### 整改涉及文件

```
src/ascendc_devkit/adapters/npu/runner.py          — M2 核心
src/ascendc_devkit/adapters/evaluation/_common.py   — M2 op_spec 传入
src/ascendc_devkit/domain/evaluation.py              — M2 EvalRequest.op_spec
src/ascendc_devkit/orchestration/stages/precision_debug.py — M2
src/ascendc_devkit/orchestration/stages/precision_debug_substages.py — N5/N6 + P5 abort 修复
src/ascendc_devkit/cli/commands/debug.py             — M2 HarnessContractError catch
.claude/skills/ascendc-precision-run-tests/SKILL.md  — F1 + N5
.claude/agents/ascendc-precision-run-tests.md        — F1 + N5
.claude/skills/ascendc-precision-run-tests/references/prompts/run_tests.md — F1 + N5
.claude/skills/ascendc-precision-run-tests/scripts/init-checkpoint.py — N2 + N5
.claude/skills/ascendc-precision-diagnose/SKILL.md   — F1
.claude/agents/ascendc-precision-diagnose.md         — F1
.claude/skills/ascendc-precision-diagnose/references/prompts/diagnose.md — F1
.claude/skills/ascendc-precision-diagnose/references/gates/gate2-sync-check.md — F1
.claude/skills/ascendc-precision-fix/SKILL.md        — F1
.claude/agents/ascendc-precision-fix.md              — F1
.claude/skills/ascendc-precision-printf/SKILL.md     — F1
.claude/skills/ascendc-precision-printf/references/prompts/printf_location.md — F1 + N5
.claude/skills/ascendc-precision-printf/references/gates/gate3-printf-bisect.md — F1
tests/ut/adapters/npu/test_runner_contract.py        — 新增 25 UT
tests/ut/orchestration/test_precision_debug_stage.py — N5 + P5 abort 修复
docs/plan/self-evolution/55-precision-debug-review-fixes-impl.md — N7
docs/plan/self-evolution/54-precision-debug-skill-split-impl.md  — N7 §10 as-built
```

### 测试结论

```
258 passed in 3.70s
  114 — precision_debug stage UT
   25 — runner contract UT (new)
  119 — adapter/runner/evaluation existing tests
```

## review 元信息

- **reviewer**: ascendc-devkit-code-reviewer skill（第二轮 · 更新后复核）
- **原始 review 存档**: `/home/g00940185/PR-10-review-0719`
