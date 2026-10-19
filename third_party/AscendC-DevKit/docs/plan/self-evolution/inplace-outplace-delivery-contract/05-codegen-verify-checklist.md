# codegen 端到端验证清单（in-place/out-of-place 交付契约，step-5 ②）

> 目的：验证 A3 codegen（`ascendc-op-dev-coding`）对 in-place 算子产 **clone+return** plugin（非真 in-place `-> ()` + `copy_` 写回）。
> 时机：**PR 合并前关键节点**（§3.11 heavy_llm；codegen stage 实测 ~27 分钟）。
> req-analysis 侧已由 `tests/st/test_req_analysis_selfclosure.py` 验证（agent 真产 mutation_mode 且自洽，2026-07-24 PASS, 171s）。
> codegen 侧无现成 selfclosure ST 可合并，本清单为手动验证；未来可酌情自动化（见末节）。

## 1. 重跑

重跑一个 **in-place 语义算子** 的 self_evolve_op（requirement → design → codegen 全链），用现有 batch/CLI（参考 batch 8b790c 的跑法）。

- **首选一个简单、已知正确的 in-place 算子**（避免 kernel 精度 bug 干扰 plugin 形态检查）。
- `advance_step_v2` 可用，但它有**独立的 kernel int64 精度 bug**（func=0 的另一个根因，见 `batch-20260721-8b790c-issues-handoff.md`）——本清单**只查 plugin 形态，不看 eval 精度**。

## 2. plugin 形态检查（核心验证点）

对 codegen 产出的 `op_plugin/<op>_plugin.cpp`，in-place 算子（`mutation_mode=in_place`）应满足：

| 检查项 | 期望（修复后） | 反例（旧 bug 形态） |
|---|---|---|
| `m.def` 返回值 | `-> (Tensor, ...)` 返回所有 output | `-> ()` 空 |
| in-place 输出获取 | `.clone()` 强制副本 | `.contiguous()`（已连续时返回 view 非副本） |
| 写回调用方本体 | **无** `copy_()` 写回 | `input_tokens.copy_(...)` |
| aclnn 调用 | clone 同时作 input + output（维持 alias 语义，kernel 零改动） | 把输入当 output 传两次 + `copy_` 写回 |

### grep 命令

```bash
PLUGIN=<run_output>/artifacts/codegen/op_plugin/<op>_plugin.cpp
grep -nE 'm\.def|\.clone\(|\.contiguous\(|copy_\(' "$PLUGIN"
```

期望：`m.def` 返回 `(Tensor…)`；`.clone(` 出现于状态张量；`copy_(` **不出现**。

## 3. mutation_mode 链路检查（构造性传递）

- `requirement.json` 含 `mutation_mode`（req-analysis 侧，已由 selfclosure ST 验证）
- `design_spec.json` 含 `mutation_mode`（design-integrate IO 契约对齐继承）
- plugin 行为与 `mutation_mode` 一致：`in_place` → clone+return；`out_of_place` → 直接 return

```bash
REQ=<run_output>/artifacts/requirement/requirement.json
DS=<run_output>/artifacts/design/integrate/design_spec.json
python3 -c "import json; print('req:', json.load(open('$REQ')).get('mutation_mode'))"
python3 -c "import json; print('design:', json.load(open('$DS')).get('mutation_mode'))"
```

## 4. 判定

- plugin 形态全部满足 §2 + mutation_mode 链路贯通 §3 → **交付契约修复验证通过**（本工作目标达成）。
- eval `function_score` 是否满分**不在本工作范围**（依赖各算子 kernel 自身精度，独立跟踪）。

## 5. 未来可选：codegen selfclosure ST（自动化）

若要把本清单自动化（而非 PR 前手动），可仿 `test_req_analysis_selfclosure.py` 新增 codegen selfclosure ST：跑 codegen agent 产 plugin，断言 `m.def` 返回值、`.clone()` 非 `.contiguous()`、无 `copy_` 写回。

属**新 heavy_llm 用例**（§3.11：codegen full-flow，分钟级起 + 高 token）——按 §3.11「新增 heavy_llm 优先合并」精神，**先确认无既有 codegen selfclosure 可合并、且价值足够**，再决定是否新增，避免膨胀 heavy 用例集。
