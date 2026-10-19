# diagnose 流不进二分 — L4 实施方案（as-built，2026-08-12）

> 层级：**L4 / 实施方案**。记录「改哪个函数、什么顺序、怎么验证」。已落地。
> 问题事实见 `01-problems.md`（L1）；方案选项与决策见 `02-analysis.md`（L3）。
>
> **落地 commit**：`943cc222`（PR #78 内，commit message 仅 "enhance debug"——
> 本目录 L1/L3/L4 即该 commit 的完整动机/方案/验证记录，追溯以本目录为准）。
> 同 PR 的 `1264e90b`（fix-diagnose-merge 收口）对应 `fix-diagnose-merge/` 目录。

## 方案一句话

新增 diagnose 专属计数器 `diagnose_stalls`，连续 2 次「无进展」即按 failure_type 降级二分
（precision→printf / runtime→comment_bisect / compilation→advance），早于 cc(6) 耗尽兜底；
有进展则清零。`stall`（早判据）与 `cc`（晚兜底）并存，各司其职。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/ascendc_devkit/orchestration/stages/precision_debug_substages.py` | 改动 1/2/3（核心代码） |
| `tests/ut/orchestration/test_precision_debug_stage.py` | 新增 `TestStalledToBisect`（11 测试） |
| `.claude/skills/ascendc-precision-{run_tests,diagnose,printf,comment_bisect,scope-guard}/references/_shared-protocol.md` | 改动 4（防幻视声明，5 份） |

---

## 改动 1 — DiagnoseSubstage.transition：stall 计数 + 早转分流

### 1a. 模块常量（DiagnoseSubstage 类前，`:2092-2096`）

```python
# §stall-detect: diagnose 连续"无进展"次数阈值。达阈即降级二分（precision→printf /
# runtime→comment_bisect），早于 cc 兜底（max_corrective_cycles）……
_DIAGNOSE_STALL_THRESHOLD = 2
```

阈值 2 的依据：合并前 fix 轻量实施用完候选（1~3 次）即转 printf；stall=2 在「无进展」语境下
等价「少量尝试即转」，恢复快时序，对比 cc=6 的 6 次重型 diagnose spawn。

### 1b. stall 计数 + 早转分流块（`:2304-2336`，位于 regression evidence 之后、`_validate_phase_json` 之前）

`cc` 耗尽 advance 块（`:2273-2274`）**保留原样不动**——它是 cc 兜底出口，删了会导致 cc 耗尽时
transition 不 advance、resolve 误判 skip_done 丢 case。stall 块在其后，`not skipped` 守卫防边界重入。

```python
# §stall-detect: 本轮进展判定（§1.10 业务语义，非 spawn 次数代理）。
_progress = (bool(_partial) or bool(already and case)
             or bool(dc.get("applied_partial")) or dc.get("case_resolved"))
cp["diagnose_stalls"] = 0 if _progress else int(cp.get("diagnose_stalls", 0)) + 1
_save_control(state, cp)   # 立即落盘：下方 _append_history 会 re-read 磁盘，不 save 即丢

# §early-bisect: 连续 stall 达阈值 = diagnose 静态手段停滞 → 按 failure_type 降级二分。
if (not skipped and case is not None
        and int(cp["diagnose_stalls"]) >= _DIAGNOSE_STALL_THRESHOLD):
    ft = dc.get("failure_type") or _get_current_failure_type(cp)
    if ft == "compilation":
        _advance_past_failure_type(cp)   # 不可 bisect：advance 换 case + skip（与 cc 兜底同语义）
        cp["corrective_cycles"] = 0
        cp["diagnose_stalls"] = 0         # 新 case 全新预算
        _save_control(state, cp)
        skipped = True
        more_cases = cp["current_case_index"] < len(cp.get("failed_case_queue", []) or [])
        dc["case_skipped"] = skipped
        dc["more_cases"] = more_cases
    else:                                 # precision/runtime：降级二分
        cp["corrective_cycles"] = 0       # reset cc 给二分阶段全新预算（diagnose/printf 共享 cc）
        _save_control(state, cp)
        dc["_stalled_to_bisect"] = ft     # precision→printf, runtime→comment_bisect
```

**关键约束**：
- `_save_control` 必须在改 cp 后立即调（`:2309`/`:2322`/`:2334`）——`_append_history` 会 re-read 磁盘，
  内存改写不落盘即丢失（实施时踩过的坑，见 §陷阱）。
- 瞬态标志 `_stalled_to_bisect` 写 `dc`（debug checkpoint）而非 `cp`（control.json）：
  `_extract_debug_checkpoint`（`:822-884`）构造全新 dict（显式键集，无 `**cp` 透传），
  下轮重建即丢 → 标志只活一次 resolve_condition，无 sticky misfire。
- precision/runtime 降级时 **不 advance**（二分需当前 case 作 context），**不 reset diagnose_stalls**
  （printf 接管不看它；run_tests 回流时 reset）。

---

## 改动 2 — RunTestsSubstage.transition：reset diagnose_stalls

新 debug round 从 run_tests 进入，diagnose 无进展计数应从 0 重计（与 cc/refine 同生命周期）。
两条路径都加：

- **中止路径**（`:1945-1946`，refine reset 之后、`_save_control` 之前）：
  ```python
  # §stall-detect: 同语义——abort 也是跨回归点，diagnose 无进展计数一并重置。
  cp["diagnose_stalls"] = 0
  ```
- **常规路径**（`:1989-1991`，refine reset 之后）：
  ```python
  # §stall-detect: 同语义清零 diagnose_stalls — 全量回归意味着新一轮 debug，
  cp["diagnose_stalls"] = 0
  ```

两条路径都要加——否则中止回流时 stall 残留，下轮 diagnose 从非零起算（实施时踩过：中止路径漏 reset
导致 `test_run_tests_resets_diagnose_stalls` 失败）。

---

## 改动 3 — DiagnoseSubstage.resolve_condition：消费瞬态标志（`:2355-2357`）

位于 `route_to_printf` 检查之后、cc 耗尽 safety-net（`:2365-2366`）之前：

```python
# §stalled-to-bisect: transition 在 stall 达阈值时 reset cc=0 + 置此瞬态标志 =
# diagnose 静态手段停滞 → 降级二分。shadow 下方 cc safety-net（cc 已 reset，不触发）。
_sb = dc.get("_stalled_to_bisect")
if _sb == "runtime":
    return "need_comment_bisect"
if _sb:  # precision
    return "need_printf"
```

- cc 耗尽 safety-net（`:2365-2366` 返回 `skip_more`/`skip_done`）**保留**——当 stall 不达 2 但 cc 满
  （多次有进展逐步逼近）时兜底 skip。该路径对 precision 的「绕过 printf」问题已由 stall 早转消除
  （stall 必先于 cc 满触发）。
- 转换表**无需改**：`need_printf`/`need_comment_bisect` → printf_location/comment_bisect 已存在。
- runtime 对称：comment_bisect 共享同一 cc，方案完全对称，**未改 CommentBisectSubstage**。

---

## 改动 4 — B：skill 文档防幻视声明（5 份 `_shared-protocol.md`）

`diagnose_stalls` 由框架 Python 确定性写入（`transition`），子 agent 契约不写；但子 agent
read-modify-write control.json 时若**幻视主动改写**为非 int，框架侧 `int(cp.get(...))` 会崩。
B 在模型可见处显式声明，堵此低概率事件。在 5 份 `_shared-protocol.md` 的 control.json 字段契约行后插入：

> **框架路由计数器（子 agent 只读、绝不写，由框架 `transition` 确定性维护）**：`corrective_cycles` /
> `refine_cycles` / `consecutive_aborts` / `run_iter_counter` / `diagnose_stalls`。你读 `control.json`
> 时会看到这些顶层字段——它们是框架路由/收敛信号，非你的产出。read-modify-write `control.json`
> 时**原样保留**，禁止改写、删除或写入非 int 值（框架侧 `int()` 解析，改坏即崩）。

5 份（run_tests / diagnose / printf / comment_bisect / scope-guard）保持一致（§2.2 各 skill 自带资源副本）；
不耦合具体算子/实例（§2.1/§1.12），符合 skill 即插即用。

---

## 测试（§3.1 TDD，全部在 `test_precision_debug_stage.py`）

新增 `TestStalledToBisect` 类（`:1925`），11 个测试：

| # | 测试 | 级别 | 守护点 |
|---|---|---|---|
| 1 | `test_resolve_stalled_to_bisect_precision_returns_need_printf` | resolve | 标志=precision → need_printf |
| 2 | `test_resolve_stalled_to_bisect_runtime_returns_need_comment_bisect` | resolve | 标志=runtime → need_comment_bisect |
| 3 | `test_stalled_flag_takes_priority_over_cc_safety_net` | resolve | 标志 + cc=max → need_printf（非 skip） |
| 4 | `test_transition_stall_increments_on_no_progress` | transition | cc<满、无进展 → stall+1 |
| 5 | `test_transition_stall_resets_on_progress` | transition | partial/case_resolved → stall=0 |
| 6 | `test_transition_stall_threshold_precision_routes_to_printf` | transition | stall=2、precision → reset cc、case 不 advance、标志=precision、resolve→need_printf |
| 7 | `test_transition_stall_threshold_runtime_routes_to_comment_bisect` | transition | runtime 对称 |
| 8 | `test_transition_stall_threshold_compilation_advances` | transition | **回归守护**：compilation stall=2 仍 advance+skip |
| 9 | `test_stall_flag_not_persisted_to_control_json` | transition | 读 cp 断言无 `_stalled_to_bisect` 键 |
| 10 | `test_run_tests_resets_diagnose_stalls` | run_tests | 跨回归点 reset |
| 11 | `test_full_cycle_stall_to_printf_to_run_tests_clears_counters` | 集成 | stall=2→printf 6 次→printf_done→run_tests→stall=0/cc=0 |

**transition 级测试范式（关键）**：必须 `_seed_phase(state, stage._phase_filename(), summary={...})`
预置 phase JSON，否则 `_agent_produced_output=False` → 走 abort 分支，不执行 stall 计数逻辑。
进展测试（#5/#6）的 summary 须带 `outputs` + `partial_outputs`，触发 stall reset。

**现有 cc 耗尽 / bump 测试不变**：resolve 级直接构造 dc 调 `resolve_condition`、不经 transition →
不设 `_stalled_to_bisect`，stall 检查跳过；transition 级 stall 从无键→1（<2 不触发早转），不影响 cc bump 断言。
pool_exhausted 路径测试（pool 真耗尽时原有兜底）不变。

---

## 实施时踩过的坑（诚实记录，供后人）

### 坑 1：`_append_history` re-read 磁盘陷阱

`cp["diagnose_stalls"]` 改的是内存 cp，下方 `_append_history`（源码注释明示）会 **re-read 磁盘**，
内存改写不 save 即丢失。症状：`test_transition_stall_increments_on_no_progress` KeyError、
`test_transition_stall_resets_on_progress` stall 仍是初始值未改。

**根因**：阈值测试（#6/#7/#8）通过是因为早转块内提前分支调了 `_save_control`；纯计数块（#4/#5）
改 cp 后没立即 save，被 _append_history 覆盖。

**修复**：stall 计数行（`:2309`）后立即 `_save_control(state, cp)`。

**普适教训**：任何在 `_append_history` 之前修改 cp 的代码，都必须先 `_save_control` 落盘。

### 坑 2：RunTestsSubstage 中止路径漏 reset

只在常规路径加了 stall reset，中止早返路径（`:1920-1953`）漏了。症状：
`test_run_tests_resets_diagnose_stalls`（stall=3 初始值）失败——中止回流时 stall 未清零。

**修复**：中止路径 `:1946` 加 `cp["diagnose_stalls"] = 0`。两条跨回归路径都要加。

---

## 验证结果（as-built）

```bash
# Python 环境须 /usr/bin/python3.11（base conda 3.10 无 ascendc_devkit）
cd /home/g00940185/AscendC-DevKit2cann-batch-2/AscendC-DevKit-hys
/usr/bin/python3.11 -m pytest tests/ut/orchestration/test_precision_debug_stage.py \
  tests/ut/orchestration/test_precision_debug_runtime_refine.py \
  tests/ut/orchestration/test_precision_debug_agent_abort.py \
  tests/ut/orchestration/test_per_output_sinking.py -v
```

- 4 文件 precision_debug 相关：**308 passed**（含新增 11）。
- 编排全量 UT：**1961 passed in 209s**，零回归。
- 现有 cc 耗尽 / pool_exhausted / abort bump 测试全绿（行为未改，stall 与 cc 并存不互扰）。

## 未覆盖（诚实，§3.11）

- **heavy_llm 端到端未跑**：precision_debug 真实 agent 全流程（diagnose 自实施 + stall 触发转 printf）
  属 heavy_llm，不默认随 pytest 跑，需用户确认。PR 合并前应由用户在关键节点决策跑一次真实链路守护。
- 日常迭代靠 UT（编排层确定性逻辑）+ 非 heavy ST + LLM 预检兜底。

## 不在本次范围

- B2 增量生成的 skill 行为优化（低效来源，非「流不进 printf」产权）——留独立工作线。
- scope_guard / bounds_check 路由不动。
