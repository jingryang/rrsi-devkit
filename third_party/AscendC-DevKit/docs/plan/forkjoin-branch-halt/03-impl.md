# ForkJoin 分支失败在 join 点无处理 — 实施（L4）：A+B+C 组合

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md`（A+B+C 组合），事实见 `01-problems.md`（P1/P2）。
> 触点集中在 `orchestration/graph_executor.py:_execute_forkjoin` 与 `orchestration/node_forkjoin.py:merge_forkjoin`；
> 复用 step-50 已建的 `State.halt_reason` 字段与 dispatcher 终止分支，不新增 State 字段、不改 dispatcher。

## 前置事实（已核实，无需再改）

- 分支内 `split` 触发 `fail_strategy=halt` 时，`_execute_sequential`（`graph_executor.py:361–368`）
  已在**该分支的 branch state** 上写 `is_terminal=True` + `halt_reason={"kind":"fail_strategy_halt",
  "stage":<split 名>, "message":<落盘原因>}` 并 break。故失败分支返回的 state **已带**这两个信号，
  action A 只需在 join 处把它们提升到 merged state。
- `_execute_forkjoin` 已用 `ns.get(self._path(c, path)) == "failed"` 判定 failed 分支
  （`graph_executor.py:664`）——action A/B 复用同一权威判据。
- dispatcher（`dispatcher.py:925–930`）已对 `is_terminal` + `halt_reason.kind=="fail_strategy_halt"`
  输出点名 `stage`+`message` 的终止文案 → A 提升的 halt_reason 直接被现有路径消费。

## 改动 1（B）— `merge_forkjoin` 只折叠成功分支、对 None 字段设防

`node_forkjoin.py:merge_forkjoin`：
- 入参维持 `(base, children, child_states)`；`_execute_forkjoin` 侧只传**成功分支**（见改动 2），
  失败分支不进 merge。
- 循环内读 `val = getattr(cstate, f)` 后，新增 `if val is None: continue`（last-resort 兜底：
  某字段从未写入 → 不贡献、不参与 None-vs-dict 判定）。这条同时闭合 P1 的直接崩溃面，即便未来
  某成功分支的可选字段恰为 None 也不误判。
- 其余 dict 键合并 / sibling-vs-sibling 冲突检测逻辑不变。

## 改动 2（A+C）— `_execute_forkjoin` 在 merge 前分离失败分支，join 处传播 halt + 落日志

`graph_executor.py:_execute_forkjoin`（605–674），在 `ran_children`/`ran_states` 组装后、
`merge_forkjoin` 调用处（原 line 651）改为：

1. **判失败分支**（复用既有 node_status 判据）：
   ```
   def _branch_failed(child, cstate):
       return cstate.node_status.get(self._path(child, path)) == "failed" \
              or getattr(cstate, "is_terminal", False)
   failed = [(c, s) for c, s in zip(ran_children, ran_states) if _branch_failed(c, s)]
   ok     = [(c, s) for c, s in zip(ran_children, ran_states) if not _branch_failed(c, s)]
   ```
2. **只 merge 成功分支**（B）：
   ```
   merged = merge_forkjoin(state, [c for c, _ in ok], [s for _, s in ok])
   ```
   成功兄弟（T2）结果照常并入 merged state → 后续 `_persist_progress` 落盘 → resume 跳过它。
3. **join 传播 halt（A）+ 可观测（C）**：`failed` 非空时，取首个失败分支的 `halt_reason`
   （分支 state 已带；缺省则兜底构造 `{"kind":"fail_strategy_halt","stage":<branch path>,
   "message":"fork-join 分支失败"}`），提升到 merged：
   ```
   if failed:
       fc, fs = failed[0]
       hr = getattr(fs, "halt_reason", None) or {default...}
       merged = merged.with_updates(is_terminal=True, halt_reason=hr)
       for fc, _ in failed:
           Logger.warn(f"ForkJoin 分支 '{fc.name}' 失败，join 处停止管线：{hr.get('message','')}")
   ```
4. 原有「标 failed 分支路径 + group failed」逻辑（656–668）保持不变——group 仍标 `"failed"`，
   与新设的 `is_terminal`/`halt_reason` 一致。

效果：父 `_execute_sequential` 下一轮循环顶 `if is_terminal: break`（line 333）→ **不进
anchor-forkjoin**；dispatcher 终止分支按 halt_reason 打点名文案；`state_snapshot` 落盘失败分支
path=failed + 成功分支 completed → resume 只重跑失败分支（正是 Run 2 实际成功的路径）。

## 顺序

改动 1 与改动 2 无跨文件顺序依赖（改动 2 传给 merge 的已是过滤后的成功分支，改动 1 的 None-guard
是独立兜底）。建议先 1 后 2，便于分别写 UT。

## 验证（TDD，先红后绿）

**UT — `tests/ut/orchestration/`**：
- `test_forkjoin_dict_merge.py`（改动 1）：构造两分支，一分支 `tiling_results=None`（模拟未写入）、
  另一分支 `tiling_results={"T2":{...}}`，断言 `merge_forkjoin` **不抛** `StateConflictError`、
  结果只含 `{"T2":...}`。（此即 P1 复现→修复的核心守卫。）
- `test_forkjoin.py` / `test_tiling_forkjoin.py`（改动 2）：用 stub 分支使 T1 分支返回
  `node_status[branch]="failed"` + `is_terminal=True` + `halt_reason=...`、T2 分支成功。断言
  `_execute_forkjoin` 返回的 merged state：① `is_terminal is True`；② `halt_reason.stage` 点名
  失败分支、`kind=="fail_strategy_halt"`；③ `tiling_results` 含 T2、不含 T1；④ group path 与
  T1 path 均 `"failed"`、T2 path `"completed"`。
- 端到端 sequential 守卫：构造 `tiling[ForkJoin] → anchor[ForkJoin]` 的最小 SequentialGroup，
  T1 分支失败，断言 driver **不执行 anchor 子节点**（`is_terminal` break 生效）——防 P2 复发核心。

**回归**：现有 `test_forkjoin_dict_merge.py` 里「两分支各写 dict 正常合并」「sibling 同 key 冲突
仍抛」「非 dict 双写仍抛」用例断言不变（None-guard 不影响这些真实写入路径）。

**全量**：CLAUDE.md §3.6 全量 UT + 非 heavy ST 绿。**heavy_llm（§3.11）**：本改动是确定性控制流/
数据合并（fork-join join 语义），非 §3.9 的真实 LLM 行为对象，UT 已确定性覆盖崩溃复现与 halt 传播；
真实全流程 e2e（一次分支抖动触发 halt）留 PR 前节点由用户决策跑一次做端到端复盘。

## 后续（不在本轮）
- Run 2 anchor 阶段中断＝运行环境问题（`02-analysis.md` 决策 4），不修。

## 实施结果（2026-07-18，✅ 已完成）

**实测确认的机制细节**（探针 `/tmp` 复现，落地时据此收敛）：
- 崩溃 100% 复现：最小 fork-join（一分支 halt-no-artifact + 一分支写 dict）→ 修前
  `StateConflictError`，修后 `NO CRASH`。
- 失败分支返回态：SequentialGroup 分支（真实 tiling 形态）返回 `node_status[branch]="failed"`
  + `is_terminal=True` + `halt_reason={kind:fail_strategy_halt, stage:<inner>, message}`；**该
  node_status 只在分支返回态里、不随 `merge_forkjoin` 进 merged**（merge 只并 provides）——故改动 2
  显式从 `ran_states` 分类携带失败分支状态，不依赖原 656-668 对 `merged.node_status` 的隐式读取。
- `halt_reason.stage` 用**分支名限定**（`f"{fc.name}/{seg}"`，如 `T1_large_reduce_split/split`），
  避免多模板共用的 `split` 段名在终止文案里指认不清（C 可诊断）。

**改动落点**：
- `node_forkjoin.py:merge_forkjoin` — 循环内 `val = getattr(cstate, f)` 后加 `if val is None: continue`（B）。
- `graph_executor.py:_execute_forkjoin` — merge 前按 `_branch_failed`（分支 node_status=="failed"
  或 is_terminal）分离失败分支，只 merge 成功分支（B）；显式据分支返回态标 node_status failed/completed；
  失败时提升 `is_terminal`+分支名限定的 `halt_reason` 到 merged（A）+ `Logger.warn` 点名（C）。

**测试**（TDD 红→绿 + 覆盖自审补充 §3.2）：
- `test_forkjoin_dict_merge.py::TestFailedBranchNoneGuard` 3 例（None 字段跳过、顺序无关、空 ok 列表返回 base 不崩）。
- `test_forkjoin.py::TestForkJoinBranchFailure` 4 例（失败分支干净 halt 不崩 + 成功兄弟结果保留 +
  node_status 三态；失败分支阻断下游 anchor 不执行；多分支全失败均标 failed + group halt；**resume round-trip**：
  halt 产出的 node_status 喂回去 → 只重跑失败分支、跳过成功兄弟、失败分支成功后清回 completed）。
- 回归：`test_forkjoin_dict_merge.py` 既有「dict 合并 / sibling 同 key 冲突 / 非 dict 双写冲突」断言不变。

**resume round-trip 测试发现并修复了 1 个实现 bug**（正是补该覆盖的价值）：首版 node_status 标注用
`if cp in failed_paths or ns.get(cp) == "failed"` 保留 base 的 `"failed"`，导致一个 base 为 failed、本次重跑
成功的分支被**永远卡在 failed**（跨 resume 永不收敛）。修正：标注只看本次 outcome（`"failed" if cp in
failed_paths else "completed"`）——base failed 分支恒 pending（resume 重跑任何非 completed 节点），其本次
成功必须清回 completed。修正后 round-trip 测试转绿、全量零回归。

**验收**：forkjoin 相关定向 48 passed；全量 orchestration UT 1163 passed；**全量 UT 2328 passed / 7 skipped**
（既有 cann-bench 外部依赖 skip，与本改动无关），零回归；相关 stub-based 非 heavy ST 15 passed
（含 `test_design_pipeline_e2e` 6 + `test_resume_cli` 2）。**heavy_llm（§3.11）** 未跑：本改动是确定性
控制流/数据合并，非 §3.9 真实 LLM 行为对象，UT 已确定性覆盖崩溃复现与 halt 传播；真实全流程 e2e
留 PR 前节点由用户决策跑一次。
