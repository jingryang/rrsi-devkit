# L3 precision_report.md 渲染缺陷 — 方案分析

> 对应 L1：`01-problems.md` P1-P7。
> 本 L3 逐问题给选项 + 取舍 + 拍板，最终收敛到一个**报告目标态**设计（§0），供 L4 按目标态落地。
> 四把尺子（§1.2）：可维护 / 可扩展 / 可诊断 / 架构合理。

---

## §0 报告目标态（拍板基线）

`precision_report.md` 的读者是**未参与调试的人**（docstring `:555-556` 明言 "readable by anyone not involved"），因此成功态与失败态都必须自洽。目标态：

1. **状态行**：`最优 commit` / `通过/失败/崩溃` / `最大误差` / `迭代轮次` / **新增 `状态`（passed/running/exhausted）**。
2. **用例状态表**：失败队列非空 → 列出失败用例；队列空（全过）→ 显式写 `✅ N/N 全部通过，无待处理失败用例`，不再留误导性空表。表头改为「失败用例状态」（诚实——它从不含已过用例）。
3. **修复历史**：聚合 `root_cause_ledger` + history 中所有 commit 载体，按 commit 去重，每行 `commit | 来源 phase | 根因摘要`。成功修复的 commit 不再漏。
4. **收敛趋势**：分母 = 真实用例总数（全过也非 0）；最终全过轮次必须出现；同一 round 多次 run_tests 只留最后一条。
5. **迭代轮次**：从 history 派生（`max run_tests round`），不再依赖不存在的 `cp.rounds`。
6. **写入时机**：每次 run_tests 全量回归后都刷新（含无 best 改善），消灭 P7 陈旧快照。

以下各 P 的选项均在向此目标态收敛。

---

## P1 迭代轮次恒 1（rounds 不落 cp）

**选项**
- **A**：RunTestsSubstage.transition 里 `cp["rounds"] = dc["rounds"]` 写回 control.json，报告读 cp。
- **B**：报告从 history 派生 `max(h["round"] for h in history if h["phase"]=="run_tests")`，空则回退 1。
- **C**：`_write_precision_report` 改签名，由两个调用点把 `dc.get("rounds")` 传进去。

**取舍**
- A 与 `_current_round` docstring（"framework-owned transient, routing-only"）矛盾——把 routing 瞬时计数升级为持久字段，扩大 state 面；且 A 只修报告这一个消费者，却给 control.json 增加一个本阶段语义不清晰的键。
- B 复用 history——history 是事件轨迹的权威记录（§1.1 Event Sourcing），报告作为只读消费方从 history 派生展示字段，不新增持久化耦合；history 必有 run_tests 条目（报告只在 run_tests 路径后写），回退 1 兜底。
- C 最直给但让报告函数签名耦合调用点内部对象（dc），且两处调用都要改，漏一处即回退。

**拍板：B**。派生自 history，符合"报告 = 只读消费者从权威轨迹派生可读视图"（§2.10 附属可读视图）；A 作 fallback 记录在案，若未来有第二个 cp.rounds 消费者再改 A。可扩展性：新增轮次语义变化不影响报告。可诊断：history 缺失时回退 1 不会崩。

## P2 收敛趋势分母归零（total 来源）

**问题**：`total` 要从哪来？四个候选来源在 8 算子上的实测：
| 来源 | transpose | resize_bilinear | unique |
|---|---|---|---|
| `best_total_count`（agent 写） | 20 ✓ | **None** | None |
| history 最新 run_tests `total_count` | 20 ✓ | 20 ✓ | **0**（sentinel 退化） |
| `best_passed+best_failed+best_crashed` | 20 ✓ | 20 ✓ | **2**（best 快照不完整） |
| 真实套件规模（golden cases 数） | 20 | 20 | 20 |

**选项**
- **A**：固定用 `best_passed + best_failed + best_crashed`（无条件，去掉 `if best_failed else 0`）。
- **B**：优先级链 `best_total_count` → history run_tests `max(total_count)` → 求和 → 0。
- **C**：报告去读 result.json `case_details` 数量。

**取舍**
- A 修掉短路 bug，但对 unique 类 best 快照不完整的情形只得 2（低估），且 best_failed 语义在 crashed 并列时可能重复。
- C 引入跨产物读（result.json 路径位置依赖、harness 契约耦合），违反"报告只读 control.json 权威态"的简洁性，过度设计。
- B 用 agent 权威字段优先、history 轨迹兜底、求和保底——三个来源逐级回退，任何单点异常都不会给 0 或崩；transpose/resize 都正确得到 20，unique 得到 2（其 harness 从未真正跑起套件，2 已是可解释下限）。

**拍板：B**。优先级链最稳、最可扩展（未来新增 total 来源只需在链上加一级）。

## P3 用例表全过为空 + 表头误导

**选项**
- **A**：表头改「失败用例状态」，队列空时显式渲染 `✅ N/N 全部通过`。
- **B**：从最新 result.json `case_details` 渲染全量 20 行（含 PASS）。
- **C**：保持现状（空表 + "全量用例状态"表头）。

**取舍**
- B 让报告变成"全量清单"，更完整，但要求报告层定位并解析 result.json（跨产物、契约耦合 result.json schema），且全量 20 行对"快速浏览失败"场景是噪音；失败态下与队列表重复。
- A 只改语义 + 加一行成功摘要：诚实（它从来只列失败）、轻量（零跨产物依赖）、可诊断（成功态不再像"没完成"）。
- C 维持误导。

**拍板：A**。附目标态 1 的 `状态` 行（`cp.status`）进一步消除歧义。架构上报告仍是 control.json 的纯派生视图（§2.10）。

## P4 修复历史 commit 全缺失

**问题**：commit 真实存在，但分散在 4 个载体：`root_cause_ledger[].fix_commit`（transpose 4 条）、printf history `content.ledger_updates[].fix_commit`（4 条）、bounds_check history `content.commit_sha`（1 条）、fix-phase history `content.git_commit`（swi_glu 2 条、transpose 0 条 refuted）。报告只读最后一个且要求同时有 root/finding。

**先定位根因**（§1.2）：报告读不到 commit 是**表象**。真根因是**写侧数据模型散乱**——`root_cause_ledger` 在 `src/` 框架代码零引用，它是 agent 写的：diagnose 创建、printf 更新；**fix 和 bounds_check 的 skill 都不写 ledger**，commit 只落 history content（`git_commit`/`commit_sha`）。所以同一职责"哪条根因被哪个 commit 解决"有 4 套无约定记录。

**选项**
- **A（报告聚合 4 载体）**：报告成为 4 套数据形状的 scavenger；新载体出现要再打补丁；写侧散乱永久保留。
- **B（写侧归一化到 ledger，报告只读 ledger）**：fix/bounds_check 的 transition 把 agent 已报告的 `git_commit`/`commit_sha`（确定性字段）合并进 `root_cause_ledger`（与框架物化 history 同类操作，`_append_history` 已有 summary 在手）；printf 维持写 ledger（skill 契约）；报告「修复历史」只读 ledger 单一源。§1.4 一并删报告对 4 载体的读取。
- **C**：现状。

**四把尺子对比（A vs B）**
| 尺子 | A 聚合 | B 归一化 |
|---|---|---|
| 可维护 | 报告携带 4 套 phase 数据形状知识，散乱债务保留 | 单一权威（ledger），报告读一处 |
| 可扩展 | 新载体 → 打补丁 | 新修复路径自动写 ledger → 报告自动可见 |
| 可诊断 | 报告正确（修表象） | 报告正确 + ledger 成为完整"commit→根因"机器契约（§2.10） |
| 架构合理 | 报告为写侧散乱兜底 = **越层兜底**（违反 §1.2） | 归一化落在写边界（transition），报告只读权威源，无越层 |

**拍板：B**。A 是"报告侧兜底"，违反 §1.2 架构合理/可扩展、§1.4 改干净、§2.5 单一通路；B 把修复落在职责正确的层/边界。风险可控：transition 合并是**追加 resolved 条目**（不增 open 数，不扰 diagnose 按 open 路由与框架停滞检测），且读取的是 agent 已确定性报告的字段，不依赖 LLM 记得写 ledger（§1.10 确定性优于让 agent 自觉）。诊断/printf 路径的纯根因分析行（无 commit）仍从 history 渲染，commit 列 `-`，保留审计价值。

## P5 最大误差渲染 None

**选项**
- **A**：`None → "-"`（无误差/未记录），0.0 正常显示。
- **B**：`None → "0.0"`（全过即零误差）。
- **C**：现状。

**取舍**：A 语义最诚实（None 可能 = 全过 也可能 = 从未记录），B 会把"从未记录"冒充"零误差"。一行改动。
**拍板：A**。

## P6 趋势缺最终全过轮 + 同轮重复

**问题**：`:663` 的 `fc > 0` 过滤掉全过轮；同 round 多次 run_tests（init + post-bounds）渲染成重复行。

**选项**
- **A**：去掉 `fc > 0` 过滤（保留 fc=0 轮），并按 `(round)` 分组只留该轮最后一条（去重）。
- **B**：只去掉过滤，不去重。
- **C**：现状。

**取舍**：A 的分组去重解决"两次第 1 轮"的歧义（那是同一轮内的两次 run_tests，非两轮），渲染为"第 1 轮：最后一次 20 failed"；B 保留重复行，读者误读为两轮。分母修在 P2。
**拍板：A**。

## P7 running 算子报告陈旧

**选项**
- **A**：每次 run_tests 全量回归后无条件刷新报告（把 `:1935` 的写从 `if _update_best_metrics(...)` 块内移出）。
- **B**：在 `_sync_debug_result` 对非终态也写。
- **C**：现状（best 改善或终态才写）。

**取舍**
- B 语义矛盾：`_sync_debug_result` 是 terminal-only 函数，非终态直接 return（`:1203`），为报告硬改终态判定，架构不合理。
- A 语义干净：报告 = "最近一次全量回归后的状态视图"，每次 run_tests 自然刷新，终态恰好是最后一次 run_tests 后的那次写（`:1209` 的终态写保留为兜底）。运行态唯一写点，改动最小（一行移动）。
- C 维持陈旧。

**拍板：A**。成本=每次 run_tests 多渲染一个 ~10KB markdown（可忽略）。可诊断：running 算子报告始终反映当前进度。

---

## 实施范围与依赖

- **报告侧**：`precision_debug_substages.py::_write_precision_report_impl` 重构 + `_report_total` 辅助（total 推导）。P1/P2/P3/P5/P6 全部在此函数内收敛。
- **写侧**（P4 归一化）：`FixSubstage.transition` 与 `BoundsCheckSubstage.transition` 各加一处 ledger 合并（读取 agent summary 的 `git_commit`/`commit_sha`，追加 resolved 条目到 `cp.root_cause_ledger`）。printf 维持写 ledger（skill 契约不动）。报告删 4 载体读取，只读 ledger。
- 依赖顺序：P2（total）→ P6（趋势）共用 total；P1 与 P6 共用 history 遍历。P4 写侧独立于报告侧，可并行。
- 无新持久化字段、无 schema 变更、无跨产物读取、不动 agent skill 契约。UT 在 `tests/ut/orchestration/test_precision_debug_stage.py` 扩展。

## 原则符合性自检（CLAUDE.md §1/§2/§3）

| 原则 | 落实点 |
|---|---|
| §1.1 框架完整 / Event Sourcing | 只改 orchestration 层；P1 报告从 history（权威轨迹）派生轮次；P4 ledger 归一化在 transition（框架物化 agent 事实的既有职责） |
| §1.2 四把尺子 | P4 用四把尺子选了 B（写边界归一化）而非报告兜底；P2 链/其余轻量项均评估过 |
| §1.4 不留旧债 / §2.5 单一通路 | P4 删报告对 4 载体的旧读取，收敛到 ledger 单一源；过渡期并存=零（一步到位） |
| §1.10 确定性优于 agent 自觉 | P4 归一化由 transition 读 agent 已报告的确定性字段，不依赖 LLM 记得写 ledger |
| §1.12 禁算子耦合 | 代码零算子名；L1 用 transpose/swi_glu 作举证属文档 |
| §2.10 结构化 | 报告是可读视图；ledger 归一化让"commit→根因"成为完整机器契约 |
| §3.1 TDD | 测试先行（T1-T8） |
| §3.7 诚实降级 | total=0 兜底不假装有总数；快照回归是**一次性脚本**，非提交测试（§1.7 测试仓内自闭环） |
| §3.2 全覆盖 | 全量 orchestration UT + 8 算子快照对照 |

## 决策汇总

| P | 拍板 | 核心理由 |
|---|---|---|
| P1 | history 派生 round（B） | 只读视图派生自权威轨迹，不扩 state |
| P2 | total 优先级链（B） | 三来源实测逐级回退；单一权威 total（框架 init 落 `total_count`）记作低优先 future refinement |
| P3 | 表头改「失败用例状态」+ 全过显式 ✅（A） | 诚实 + 轻量，零跨产物 |
| P4 | **写侧 ledger 归一化 + 报告只读 ledger（B）** | 修复落在写边界，不越层兜底；单一权威，可扩展 |
| P5 | None → `-`（A） | 不把"未记录"冒充"零误差" |
| P6 | 去 fc>0 过滤 + 按轮去重（A） | 最终轮可见、同轮不重复 |
| P7 | 每次 run_tests 无条件刷新（A） | 唯一运行态写点，语义干净 |
