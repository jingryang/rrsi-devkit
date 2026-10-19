# L1 precision_report.md 渲染缺陷（2026-08-09 批跑取证）

> 触发事件：20260808-162146-ae8b74 批 8 算子的 `artifacts/debug/<op>/precision_report.md`。
> 本 L1 只记录客观事实（哪里坏、凭什么这么说），不提方案、不排顺序、不写决策。
> 归属：框架 `src/ascendc_devkit/orchestration/stages/precision_debug_substages.py` 的报告生成函数 `_write_precision_report_impl`（`:570-673`）。算子 debug 本身无缺陷（transpose 20/20 全过已核验：control.json `status=passed`、`run_tests_iter-7/result.json` 20 case 全 `accuracy.passed=True`、`kernel_first10==golden_first10`）。

---

## 全批 8 算子报告形态快照（L1 证据基线）

| 算子 | status | best 通过/失败/崩溃 | 用例表行数 | 迭代轮次 | 最大误差 | 修复历史 commit |
|---|---|---|---|---|---|---|
| transpose | passed | 20/0/0 | 0（空） | 1 | None | 8 行全 `-` |
| sigmoid | passed | 20/0/0 | 0（空） | 1 | None | 1 个 commit |
| softmax | passed | 20/0/0 | 0（空） | 1 | None | 3 个 commit |
| swi_glu | passed | 20/0/0 | 0（空） | 1 | None | 2 个 commit |
| apply_rotary_pos_emb | passed | 20/0/0 | 0（空） | 1 | None | 未看全 |
| resize_bilinear | running | 6/14/0 | 14 | 1 | 32.0 | 3 个 commit |
| group_norm | running | 16/4/0 | 4 | 1 | 1e-06 | 未看全 |
| unique | running | 0/1/1 | 1（陈旧） | 1 | None | 0 行 |

观察：**全过算子（passed）报告全部畸形；有残留失败的 running 算子（resize_bilinear/group_norm）报告基本正常**。差异根因是同一函数在不同终态下的退化（见 P2/P3/P5），非算子差异。

---

## P1 报告「迭代轮次」恒为 1（实际跑 2~5 轮）

- **area**: orchestration / report
- **symptom**: 8 份报告全部显示 `迭代轮次: 1`。transpose 实际跑 5 轮（history round 1..5，17:30→19:55），swi_glu 跑 2 轮，resize_bilinear 跑 4 轮。
- **evidence**:
  - `precision_debug_substages.py:580`：`rounds = max(int(cp.get("rounds") or 1), 1)`——报告从 control.json（cp）读 `rounds`。
  - 但 `rounds` 从不写进 control.json：`_extract_debug_checkpoint`（`:734`）透出字段里没有 `rounds`；rounds 只在 RunTestsSubstage.transition 里以 `dc["rounds"] = (state._debug_checkpoint or {}).get("rounds", 0) + 1` 写进 `state._debug_checkpoint`（`:1838/:1864`），是瞬时值。
  - 8 个 control.json 顶层均无 `rounds` 键（已逐一核验）。
- **影响**: 报告无法反映 debug 实际轮次，审计误导；`docstring` 自述 `rounds` 是 "framework-owned transient, routing-only"（`:218-227`）——持久化语义与本报告消费点不一致。

## P2 收敛趋势分母归零（`X/0 passed`）

- **area**: orchestration / report
- **symptom**: transpose 报告 `第 1 轮: 0/0 passed (20 failed)`、`当前最优: 20/0 passed`——分母恒 0。全过算子全部如此。
- **evidence**:
  - `precision_debug_substages.py:579`：`total = best_passed + best_failed if best_failed else 0`。`best_failed=0`（falsy）→ `total=0`。
  - transpose/swi_glu/softmax/sigmoid 的 `best_failed_count=0` → 趋势所有行分母 0。
- **影响**: 成功算子的收敛曲线不可读，把"20/20 全过"渲染成"20/0"，是最直观的"报告不像正常报告"来源。

## P3 「全量用例状态」表在全过时为空（表头误导）

- **area**: orchestration / report
- **symptom**: transpose/swi_glu 等全过算子的用例表只有表头、零数据行；表头却写「全量用例状态」。
- **evidence**:
  - `precision_debug_substages.py:581,598`：只遍历 `failed_case_queue`（失败队列），全过时队列空 → 空表。
  - transpose `failed_case_queue=[]`、swi_glu `[]`；resize_bilinear 有 14 条 → 表有 14 行。
- **影响**: 成功算子看不到任何用例级结论；表名与实际语义不符（它从来只列失败用例，不是"全量"）。

## P4 修复历史 commit 列全部缺失（成功修复的 commit 报告读不到）

- **area**: orchestration / report
- **symptom**: transpose 报告「修复历史」8 行 commit 全 `-`；实际有 5 个真实修复 commit：`be17c2c`（bounds_check MTE 对齐）、`605af87`（非可约 perm host 兜底）、`be4857e`（DMA dummy-pad 广播）、`6969dd0`（多核 DCache SetValue）、`59abb23`（n-tail per-tile UB 行步长）。
- **evidence**:
  - `precision_debug_substages.py:635`：只读 history 条目 `content.git_commit`。
  - transpose history 17 条 `git_commit` 全 None（已 dump 核验）。成功修复的 commit 实际记录在别处：
    - `root_cause_ledger[].fix_commit`（transpose 4 条：RC-A/B/C/D 各带 fix_commit）；
    - printf_location history `content.ledger_updates[].fix_commit`（4 条）；
    - bounds_check history `content.commit_sha`（be17c2c）。
  - transpose 仅有的 2 条 fix-phase 历史是被 refuted 的（`git_commit=None`、无 root_cause/finding → 被 `:645` 的 `if root or commit` 整条跳过）。
  - **写侧事实（深层根因）**：`root_cause_ledger` 在 `src/` 框架代码零引用，是 agent 写的（diagnose 创建、printf 更新）；`ascendc-precision-fix` 与 `ascendc-precision-bounds-check` 的 skill 均不写 ledger，commit 只落 history content（`git_commit`/`commit_sha`）——同一职责"哪条根因被哪个 commit 解决"有 4 套无约定记录。
- **对照**: swi_glu 的修复走 fix phase（history `content.git_commit` 有值 `a96ab21a5d82`、`9541b25cf2e4`）→ 报告能显示 2 行。**证明该列能力依赖"修复走哪条路径"，而非报告本身完整。**
- **影响**: 审计丢失 commit→根因映射，报告的"根因/发现"列与真实修复脱节。

## P5 最大误差渲染字面 `None`

- **area**: orchestration / report
- **symptom**: 全过算子报告 `最大误差: None`（字面 None 文本）。
- **evidence**: `precision_debug_substages.py:578` `best_err = cp.get("best_real_max_err")`（全过时 None），`:589` f-string 直接渲染 → 文本 "None"。transpose/swi_glu/sigmoid/softmax 全过算子均如此。
- **影响**: 文本层面不专业；成功态应表达"0.0 / 无误差"而非 None。

## P6 收敛趋势过滤掉最终全过轮次

- **area**: orchestration / report
- **symptom**: transpose 实际第 5 轮 20/20 全过，但趋势只有第 1-4 轮（20/12/10/5 failed）；最终成功轮次从趋势里消失。
- **evidence**: `precision_debug_substages.py:663` `if r > 0 and fc > 0`——fc=0（全过轮）不进 snapshots。transpose round 5 `failed_count=0` 被滤掉。
- **附带现象**: 同一 round 的多次 run_tests（如 bounds_check 前的 init run_tests 与之后的 run_tests 都记 round=1）会渲染成两行重复「第 1 轮」——transpose 报告里出现两次 `第 1 轮: 0/0 passed (20 failed)`，swi_glu 同样。
- **影响**: 报告缺少"从失败到全过"的最后一跳，成功收敛在趋势上不可见。

## P7 非终态算子报告陈旧（unique 停早快照）

- **area**: orchestration / report
- **symptom**: unique 报告更新时间 17:40:45，显示 `通过/失败/崩溃: 0/1/1`、用例表仅 1 行（`unique:smoke_failed_schema_mismatch`）；但终态 control.json `failed_case_queue` 有 20 条、`status=running`、`best_passed=0`。
- **evidence**:
  - `_write_precision_report` 只在两处调用：`:1935`（`_update_best_metrics` 返回 True，即 best 通过数严格改善时）与 `:1209`（`_sync_debug_result` 终态）。
  - unique `best_passed_count=0` 从未改善、status 从未到 passed/exhausted（elapsed 19484/36000）→ 报告停在首轮 `best_passed=None→0` 首次写入的快照。
  - 报告内容与终态 control.json 明显不一致（1 行 vs 20 条队列）。
- **影响**: running 算子的报告不代表当前进度，可观测性失真。

---

## 汇总

| P | 一句话 | 触发条件 | 严重度 |
|---|---|---|---|
| P1 | 迭代轮次恒 1（rounds 不落 cp） | 所有算子 | 中（审计误导） |
| P2 | 趋势分母归零 | 全过（best_failed=0） | 高（成功态不可读） |
| P3 | 用例表全过为空 + 表头误导 | 全过 | 高 |
| P4 | 修复 commit 全缺失 | 修复走 printf/bounds 路径 | 高（审计缺失） |
| P5 | 最大误差渲染 None | 全过 | 低（文本） |
| P6 | 趋势缺最终全过轮 + 同轮重复 | 全过 | 中 |
| P7 | running 算子报告陈旧 | 无 best 改善且非终态 | 中（可观测） |

共性根因：报告函数按**失败态语义**设计（表=失败队列、误差=残留误差、趋势=只画 fc>0），对**成功态（best_failed=0）退化**——全过算子集中爆发 P2/P3/P5/P6，P1/P4/P7 则与终态无关普遍存在。
