# step-76 — general-design-review 越界查 requirement + requirement 缺 golden 自检 致 corrective loopback 空转 — 方案分析（运行发现，核实后修正）

> 性质：self-evolution 线 L3 方案分析，step 76。**运行观察发现的真实缺陷**（batch_id=`20260727-145339-3dd653`，首跑 TS=`20260727_225324`）。
> 状态：**已实施（step-78，2026-07-28）**——根因"职责分层违反（review 越界查上游 + requirement 缺源头自检）"已修：① §2.9 增"门不越界查上游产物"原则；② step-78 gate scope & ownership contract（gate_scope.json 声明 + INV-A 运行期 drop 越界 issue + INV-B 加载期校验 + routes 声明序路由，结构性修掉字典序优先级 bug）；③ requirement `math-equiv-golden` 源头自检（slice-7）。自旋症状由 gate_scope INV-A 确定性防住，源头质量由 requirement 自检改进。实施细节见 `78-gate-scope-ownership-contract-impl.md`。
> 历史状态：**分析修正版**——初判为"控制流 loopback 路由 bug"，经代码核实 + 用户订正后，根因修正为"职责分层违反"。
> 承接：**step-60（design 逃生路径原则）**——本步核实后确认 60 的 halt 边界**无需扩展**（GD-R1 可修，不 halt）；但暴露 §2.9"门的边界"原则**不够 crisp**（"门不越界查上游"未显式化）。
> 不冲突：step-70/72 是 training-time 层（跨算子确认通道），本步是 inference-time 单算子 design 阶段，**不同层**。
> 纪律：语义锚点（stage / 字段名 / issue code），不写 `file:line`（落点留 L4）；外部依赖只读。

---

## 0. 一句话

`general-design-review` 越界查了本属 requirement 层的事（校验 requirement 的 `math_formula` 与 golden 的数值等价性）——这既不在它自己声明的 CR1/CR2/CR3 职责里，review 自己的 detail 也承认"属需求层语义裁定"，却仍查了并报 `target=requirement`/`verdict=infeasible` 的 blocking。而这项检查本应在前一 stage 由 requirement 自检完成（requirement 已读 golden、已有自检闭环，唯独缺数值等价这一项）。结果：review 报出一个 design producer 修不了的 issue，corrective loopback 又因字典序优先级把它和 `target=generator` 的可修 issue 一起回灌给 generator → generator 修不了 → review 每轮复现 → 空转至 `max_corrective` 耗尽后带 known-issue 前逃（**毒性前逃**：建在错误 requirement 上的设计进 codegen）。

**核心是职责分层违反，不是控制流 bug**：把"requirement 正确性校验"前移到源头自检（requirement）、并收回 review 到 CR1/CR2/CR3 范围，loopback 自然不再空转，**也不用扩 halt**（GD-R1 可修，不 halt）。

> **核实订正记录（L3 演进）**：初判（§2.0）主因是"loopback 不分 target 统一回灌 generator"。代码核实后**推翻**——路由器**本来就按 target 路由**（`issue_target_mapping`），且空转**有界**（机制 B：`max_corrective=2` 后前逃，**非"空转到 10h 硬超时"——该超时在代码里不存在**）。真主因是 review **越界产出** target=requirement（不该查的查了）+ requirement **缺源头自检**（该查的没查）。同时订正 §1.4"review 门本身没错"→ review **越界了**（明知属需求层还查）。

---

## 1. 事实（L1 产权，本文记录）

### 1.1 现象（5 算子对比，定位到 5c3b24 一个）

batch 首跑 5 算子，4 个 review 正常、1 个空转：

| 算子 | execution | review 迭代 | 结果 |
|---|---|---|---|
| scatter_pa_kv_cache | b45a5c | 1/3（1 次过） | completed, 0 issue |
| advance_step_v2 | c403fd | 1/3（1 次过） | completed, 就地修 narrative |
| ai_infra_aggregate_hidden_grad | dfd71a | 1/3（1 次过） | completed, 就地修 tiling_data |
| multi_add_rms_norm_dynamic_quant | 130f8b | 1/3（1 次过） | completed, 就地修 split_axis_priority |
| **ai_infra_manifold_constrained_hyper_connection_post** | **5c3b24** | **1/3→2/3→3/3 全 fail → corrective 1/2 → generator 重生 → review 1/3→2/3 再 fail …** | **空转后毒性前逃** |

> 注：4/5 正常证明 review 门 + corrective 机制对"target=design 本产物、可就地修"的 issue 工作良好；问题专属于 review **越界**产出的 `target=requirement`/`infeasible` 这一类。

### 1.2 5c3b24 时间线（run.log 实证）

```
22:54:07  requirement done (175s, iteration 1/10 第1次即过)   ← 错误 math_formula 在此引入（自检未拦）
22:57:02  generator 第一轮 done (274s)
23:01:36  review iteration 1/3 fail  (本轮阻断 2: GD-R1→requirement[越界产出], GD-G1→generator)
23:04:29  review iteration 1/3 fail（同上，重新 spawn reviewer）
23:07:28  review iteration 3/3 fail  (GD-R1 infeasible，已用数值反例证实)
23:09:17  review done (460.6s)
23:09:17  loopback general-design-review → general-design-generator (corrective 1/2)   ← 字典序优先级：generator 赢
23:09:17  generator 第二轮 iteration 1/5
23:15:19  generator 第二轮 done (361.8s)
23:15:19  review iteration 1/3
23:17:13  review iteration 2/3 fail  (GD-R1 infeasible 再现)
23:19:58  仍在 review 第二轮循环中……
```

> **核实订正**：timeline 显示的"corrective 1/2 → generator 重生"是**有界空转**——`max_corrective=2`，最多 2 轮后整组完成、带 `design_known_issues` 前逃到 codegen（机制 B：配额耗尽 `i+=1;continue` 前逃，**非** `__escalate__`，也非死循环）。危害是 (a) ~2 轮（~28min）无谓 token/时间；(b) **毒性前逃**——建在错误 requirement 上的设计进 codegen，下游 compile/test/precision 才暴露，known-issue 标签还可能压低告警。

### 1.3 铁证（review 判断属实，已二次核对源码）

**golden.py L94-95（权威，worktree 实读）**：
```python
y = (h_post_fp32.unsqueeze(-1) * h_out_fp32.unsqueeze(-2) +
     torch.sum(h_res_fp32.unsqueeze(-1) * x_fp32.unsqueeze(-2), dim=-3))
# 即 output[i,j] = h_post[i]*h_out[j] + Σ_k(h_res[i,k]*x[k,j])
# → h_post 只缩放 h_out 项（外积式 additive bias）
```

**requirement.json L8（requirement-analyst 产出，artifacts 实读）**：
```
math_formula: output[..., i, j] = (sum_k(h_res[..., i, k] * x[..., k, j])) * h_post[..., i] + h_out[..., j]
# → h_post 缩放整个 matmul 结果，h_out 作 additive bias
```

**两公式数学不等价**（h_post 作用域不同），是两个不同的算子。review 的 GD-R1 detail（含 golden 原文 + requirement 原文对照 + 数值反例）**判断属实**——即"requirement 的 math 确实错了"。**判断对，不等于"该由 review 来判"**（见 §1.4）。

### 1.4 凭什么说是缺陷（核实订正：review 越界，非"门没错"）

初判认为"review 门本身没错，错在控制流 transition 把 GD-R1 回灌 generator"。核实后**部分推翻**——review **越界了**：

- review SKILL.md 声明职责只有 **CR1**（下游强依赖节点：`split_axis_priority` / `tiling_data` / `loop_framework` / `buffer_eval`）/ **CR2**（`gradient_formula` 梯度公式基础正确性）/ **CR3**（概设详细度分级），**全是 `general_design.json` 字段**。**没有任何一条是"校验 requirement 的 math_formula 与 golden 数值等价"**。
- schema 里 `GD-R1 target=requirement` 的 example，detail 是 **"需求规格缺 dtype 矩阵，generator 无法凭现有信息产出 tiling_data 字段表"**——即 `target=requirement` 这条路**本意是"缺信息"**（design 填 CR1 节点时发现上游没给足信息）。5c3b24 的 GD-R1 是 **"requirement math 与 golden 数学不等价"**——纯 requirement 正确性检查，**连 schema example 本意都没覆盖**，是 review **自己越界**去做了 golden 等价校验。
- review 自己的 detail 都承认：**"本 skill 职责限于 CR1/CR2，不覆写算子数学公式（属需求层语义裁定），故标记 blocking 走工程路由"**——**它知道这是需求层的事，却还是查了并报了 blocking**。明知越界还做。

**缺陷定性**：review 越界查上游产物正确性，产出一个本 stage 修不了的 issue（`target=requirement`），落入 §2.9"禁止只发现问题无法解决"。正确做法是这项检查**前移到 requirement stage 自检**（§2.9 第一条：问题的发现与解决应在同一 agent 内闭合）。控制流 transition 把它回灌 generator 只是**下游放大**（§2.2），不是根因。

### 1.5 诊断过程的可诊断性教训（附记）

- 本次先被 **batch 总日志**误导：batch log 的 `agent_stream` 只捕获了 `requirement-analyst`（印证记忆 `opencode-backend-transcript-provenance-gap` AU-6/AU-7：batch log 无 op 归属 / stream 捕获不全），一度误判"5 算子都还在 requirement 阶段"。
- 真相在 **per-op run.log**（带 `[<op>/<stage>]` 归属）+ `stage_iteration` 行 + `general_design_reviewed.json`。
- **教训**：观察 batch 推进必须看 per-op run.log 的 `stage_iteration` 序列，不能只看 batch 总日志的 agent_stream。

---

## 2. 根因（L3 产权）

### 2.0 初判（已推翻，保留以记录 L3 演进）

初判主因：corrective loopback "把所有 blocking issue（不分 target/verdict）统一回灌给 design producer（generator）"，违反 §2.9 discover+regenerate。

**核实推翻**：路由器**本来就按 target 路由**——
- `target=generator` → `redo_generator`（组内 corrective，`max_corrective=2`）
- `target=requirement` → `design_input_invalid` → `__escalate__` → pipeline 路由回 requirement stage
- `target=human` → halt

所以"不分 target 统一回灌"不成立。真主因见 §2.1。

### 2.1 真主因：职责分层违反（review 越界 + requirement 缺源头自检）

**层 1（review 越界产出）**：review 做了不在其 CR1/CR2/CR3 职责内的"requirement math vs golden 等价"检查，产出 `target=requirement`/`infeasible` blocking。这项检查本该在前一 stage 由 requirement 自检完成。门越界查上游产物正确性，必落入 §2.9"发现问题但本 stage 修不了"。

**层 2（requirement 缺源头自检）**：requirement stage 已读 golden（逐行分析推导 spec）、已有自检闭环（"自检失败 → 就地修正直到通过"），**唯独自检没含"math_formula 与 golden 数值等价"这一项**。错误公式因此 `iteration 1/10` 第 1 次即过，迟至 design-review 才被抓——而抓它的还越了界。

两层合起来：**该查的（requirement 自检）没查，不该查的（review）查了又报给修不了的人**。这是 §2.9"门不越界查上游"+ "源头自检优先"的违反——而这两个原则在 CLAUDE.md 里**前者不够 crisp（未显式化，铁证：review skill 自己的 schema 允许 target=requirement、CR1 明文"根因在需求规格→target=requirement"，说明推导没被 enforce），后者已存在但 requirement skill 未落实**。

### 2.2 次因（已降级）：orchestration loopback 路由（休眠，非主修）

核实发现路由器的两个次要问题（职责分层修好后进入休眠，可选硬化）：
- **字典序优先级**：`_route_from_issues` 按 `issue_target_mapping` 插入序探测，`generator` 排在 `requirement` 前 → 当 review 同轮报 `target=generator`+`target=requirement` 时，`redo_generator` 永远赢，requirement 的 escalation 路径形同虚设。这是 5c3b24 空转的**直接控制流机制**。
- **verdict 盲**：`verdict` 字段在 schema 里，路由从不读（`design_tree.py` 注释明说"仅机械映射 target，无 verdict 检查"）。

但这两条都是"review 已经越界产出 target=requirement 之后"的下游放大。源头（review 不越界 + requirement 自检）修好，这两条不再触发。作为 last-resort 兜底可选硬化（多 target 归并时硬阻断优先于可修），非主修。

### 2.3 step-60 的 halt 边界：核实后确认**无需扩展**

初判担忧"design composite 未接入 escalate 可能空转到硬超时"，想扩 step-60 的 halt 范围到"evidenced infeasible"。核实后**两者都不需要**：
- design 组用机制 B（配额耗尽 `i+=1;continue` 前逃），**确定性结束，不空转**。这是 P83 escape hatch 的有意设计（design 无客观 pass bar，imperfect design 仍推进），不是疏漏。
- "10h 硬超时"在代码里**不存在**（`workflow_timeout_sec` 默认 0 禁用，无硬编码默认值）。
- **GD-R1 可修**（requirement 重读 golden re-derive 即可），**不属 halt**。halt 仅留给真不可修（genuine human ambiguity / 429）。扩 halt 到 evidenced infeasible 是错的——**evidenced infeasible ≠ unfixable**。step-60 原样。

---

## 3. 修复方向（L4 待实施，本文给方向 + 四把尺子）

按 §2.9 + §1.2 四把尺子，**主修落在 skill 职责层**（非 orchestration 路由层）：

**主修-1（requirement 自检加 golden 数值等价，源头）**——落 requirement skill 自检环节：
- requirement 产 math_formula 后，自检数值等价 golden（确定性脚本：构造小张量数值反例比对）。
- 不等 → 就地 re-derive（golden 是数学真值源，re-derive 确定可收敛），直到等价才出。
- 真修不了（description 与 golden 语义真冲突）→ 真 ambiguity，走 resolve_ambiguity→human。
- 四把尺子：可维护（复用 requirement 已有 golden-read + 自检闭环，增量加一项）✓；可扩展（任何数值类 requirement 错误源头拦截）✓；可诊断（自检失败就地留信号，不推迟到 design）✓；架构合理（检查落在职责正确的层 = 产出方自检，不越层）✓。

**主修-2（review 收回 CR1/CR2/CR3 范围，去越界）**——落 review skill：
- 禁止 review 做"requirement math vs golden"这类纯上游正确性检查（不在 CR1/CR2/CR3）。
- `target=requirement` 仅保留给"design 填 CR1 时发现上游缺信息"（schema example 本意）；且 requirement 自检加强后应极少触发。
- review 能就地修的（4/5 算子：narrative / tiling_data / split_axis_priority）继续就地修。

**主修-3（review 就地修优先，loopback 仅留 generator 可修且自己修不了的）**——现状已是（4/5 算子验证），保持。§2.9 第一条。

**halt：不扩**（§2.3 已论证）。step-60 原样。

**次因兜底（可选，非必需）**：`_route_from_issues` 多 target 归并时，硬阻断（`target≠producer` / `infeasible`）优先于可修 target——防未来其他越界场景。主修-1/2 落地后休眠。

**CLAUDE.md 原则强化**（§2.9 加一条 crisp 子原则）：把"门不越界查上游产物"显式化——门检查范围限于本 stage 产物层，上游产物正确性归上游自检；不准在门里查了又报 `target=上游` 让控制流兜底。铁证：review skill 自己的 schema 允许 `target=requirement`，证明现有 §2.9 推导没被 enforce。

---

## 4. 临时止血（用户决策，非本文实施）

- 5c3b24 当前在 design 阶段空转（核实后确认有界，最多 ~2 轮后自动前逃，不会无限空烧）；其余 4 算子正常推进，不受影响（per-op worktree 隔离）。
- 是否手动停掉 5c3b24（避免毒性前逃到 codegen 浪费下游算力）由用户定：`ascendc-devkit run --resume <5c3b24-execution_id>` 定向处理，或 kill 该 op 子进程（不影响 batch 其他算子）。
- 根因修复前，该算子的 requirement.json math_formula 需人工修正（按 review remediation：改为 `output[...,i,j] = Σ_k(h_res[...,i,k]*x[...,k,j]) + h_post[...,i]*h_out[...,j]`）后重跑。

---

## 5. 句柄（取证路径）

- 5c3b24 run.log：`output/20260727-145339-3dd653/20260727-145339-5c3b24/run.log`
- review 产物：`output/20260727-145339-3dd653/20260727-145339-5c3b24/artifacts/design/general-design-review/general_design_reviewed.json`
- golden 源：`cann-bench-batch/20260727_225324/ai_infra_manifold_constrained_hyper_connection_post/bench_lab/kernel_bench/level2/ai_infra_manifold_constrained_hyper_connection_post/golden.py` L94-95
- requirement 产物：`output/20260727-145339-3dd653/20260727-145339-5c3b24/artifacts/requirement/requirement.json` L7-8

---

## 6. 代码核实锚点（L4 实施参考，本文首次落入）

- 路由器：`_route_from_issues` / `_resolve_with_redirect` / `_DesignGate.resolve_condition`（`orchestration/stages/design_substages.py`）；`GeneralDesignReviewStage.issue_target_mapping = {generator→redo_generator, requirement→design_input_invalid, human→human}`。
- transition table：`_GENERAL_DESIGN_TRANSITION_TABLE`（`orchestration/design_tree.py`）：`redo_generator→组内 corrective`、`design_input_invalid→__escalate__→requirement`、`human→__escalate__→__halt__`。
- 耗尽机制 B：`graph_executor._execute_sequential` 配额耗尽 `i+=1;continue` 前逃（非 `__escalate__:exhausted`，后者仅 precision_debug 用）。
- known-issue 前逃：`State.design_known_issues`（`orchestration/kernel/state.py`）+ `_set_known_issues` + codegen 消费（`stages/codegen.py`）。
- review 职责声明：`.claude/skills/ascendc-op-general-design-review/SKILL.md`（CR1/CR2/CR3）；schema target 字段 example 见 `schema/general_design_reviewed.json`。
- requirement 自检现状：`.claude/skills/ascendc-op-req-analysis/SKILL.md`（L94 读 golden、L165-173 自检闭环，缺数值等价）。
