# L4 实施方案：stage 收尾统一错误归一化（F6）——通用行为统一抽象（§1.15）

> 对应问题：F6（成功却记 failed）。用户决策（2026-08-21）：采纳统一抽象方案；
> 同时新增 CLAUDE.md §1.15「通用行为统一抽象，禁止逐点复制」。
> L1 归因已修正（issues/F6-*.md）：真根因是 requirement 成功 return 不清 sticky
> last_error，深层原因是"成功清错"散落为各 stage 手工纪律。

## 一、统一抽象的依据

"stage 成功了吗"的判定信号**全部在 runner 手里**：末轮 agent 过程状态
（ok/partial，排除 infra）、output_contract.provides 是否全就位（含 noop_satisfied
确定性跳过）、is_satisfied 质量门收尾值。三信号齐 ⇒ 已交付 ⇒ 本 stage 之前记的
失败错误必然过时（全仓约定：记错分支与交付产物互斥）。故归一化收口在 runner
stage 收尾，单一实现点。

## 二、改动

### 1. runner（新增单点）

stage 收尾、status 推导**之前**：

```
delivered = noop_satisfied
         or (末轮 agent status ∈ {ok, partial}
             and 非 infra（P116：infra 不可恢复，错误必须保留）
             and result_state.has_all(provides)
             and _final_quality_ok)
if delivered and own_error is not None:
    WARN "cleared stale own-stage error after delivered success"
    result_state = result_state.with_updates(last_error=None)
```

- `_final_quality_ok`：循环内每轮 stash `quality_ok`，收尾取末值。
- 只清**署名本 stage** 的错误（own_error 判定已按 stage_name 过滤）；上游遗留
  错误不动（比手工 clear 无条件清空更精确）。
- 与 P129（runner 为失败 stage 反向**补写** last_error）对称：同一边界、同一
  职责的正向清除。

### 2. 删除被取代的散点（终态成功 return 里的手工 clear，§2.5/§1.15）

- `design_substages.py:1887`（tiling 成功 return）
- `test_design_substages.py:240`、`:281`（两处 cases 成功 return）

### 3. 保留的散点（非同构，不删——实施时核实发现）

以下属**中途流转语义**（stage 未结束，runner 边界不可达），不是"收尾清错"的
重复实现：

- `design_substages.py:772` `_commit` helper——design 各 substage 中途成功提交，
  防前轮失败毒害后续迭代（docstring 明示；design actions :199 读 last_error）。
- `codegen.py:1214/1388/1409/1581`——重试请求 / D4 交接路径；codegen actions
  读 `state.last_error` 做熔断决策（:664）与 retry prompt（:721），中途清错是
  其状态机语义。

## 三、行为变化披露

- d8d4d9 形态（round N-1 记错、round N 交付且不清）→ stage_status 从 failed 变
  **ok**，state.last_error 收尾为 None；stale 错误不再可能触发无谓 loopback。
- 上游 stage 遗留错误不再被下游成功 return 顺手抹掉（原手工 clear 无条件清空
  整字段）——保留真实溯源。
- 已交付但残留错的矛盾态出现时打 WARN（可观测）；正常成功路径无额外噪音。

## 四、验证（TDD）

runner 级新增（test_stage_failure_status.py）：
1. d8d4d9 回归：两轮 stage（round1 记 own 错、round2 交付且不清）→ status=ok
   且 last_error=None。
2. 质量门未过 / 契约未满足 / 末轮 infra → 错误保留、status 非 ok。
3. 上游遗留错误 + 本 stage 交付 → 不清（last_error 存活）、status=ok。
4. 清除时 WARN 可见（capsys）。

迁移：仅触及被删 3 处的直接断言用例改为 runner 级预期；design `_commit` 与
codegen 中途清错用例原样（行为未变）。回归全量 UT `--quick`。

## 五、实施结果（2026-08-21）

- runner 归一化落地（`_final_quality_ok` 循环 stash + `_delivered` 三信号判定 +
  WARN 可观测清除 + own_error 重算）；`_last_infra` 计算上移单点复用。
- 3 处终态手工 clear 删除（design tiling / test_design×2），均附指向说明注释；
  design `_commit` helper 与 codegen×4 中途清错原样保留（非同构语义）。
- 需求即治愈：requirement/integrate/cannbench_adapt **零改动**——统一抽象点覆盖。
- UT 3660 passed / 0 failed（+6：F6 六用例）。中途清错相关既有用例
  （detailed-design sticky-clear 等）零回归——其走 `_commit` helper 路径，未受
  删除影响。
