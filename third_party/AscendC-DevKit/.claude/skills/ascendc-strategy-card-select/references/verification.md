# 全 md 核对与盲评排序（Phase 3，设计阶段）

输入：粗筛候选（≤10）+ 设计文档（`run_inputs.json` 的 `design_doc`）。
输出：`verification.json` + 排序结论。

源策略 md 路径由 `cardlib.source_md_path(<策略库根>, <strategy_id>)` 按 id **跨两层**解析
（`strategies/common/<id>.md` 与 `strategies/op-class/<class>/<id>.md`）；命中恰 1 个才有效。

**卡片只是索引，本 Phase 的一切判定以完整策略 md 为准。**

> 对照"源码 + profiling"的检索，本阶段对照"设计文档 + 设计约束"：判定的是
> 「这条策略是否与当前设计方案相容、是否值得吸收进方案」，不是「是否已在代码里落地」。
> 无法从设计文档回答的问题记为 `missing_information`，并压低 `confidence`。

## 逐候选核对清单

对每个候选：

1. **读源 md**：按上述约定定位 → 完整读该 md（**全文**，不只标题和适用条件段）。
2. **适用/泛化条件逐条核对**：md 的适用/泛化条件是**合取关系**，逐条对照设计文档——
   成立的记入 `supporting_facts`（写明"条件 X ↔ 设计文档哪一节的设计意图/约束"）；
   不成立的记入 `contradictions`；文档回答不了的记入 `missing_information`。
3. **红线核对**：md 的正确性红线/禁止事项/不适用边界是否被设计意图触及。
   任何一条被触及，`status` 至多 `uncertain`；直接冲突给 `contradicted`。
4. **前置问题核对**：md 若列「LLM 前置问题」，逐条尝试从设计文档回答；
   回答不了的进 `missing_information` 并压低 `confidence`。
5. **already_present 判定**：md 的机制是否**已被设计纳入**（对照 Query 的
   `current_optimizations` 与设计文档）。已纳入选了也是空转，标 `already_present=true` 并降级。
6. **数值语义**：md 若要求等价性/精度验收，对照设计文档的 `constraints` 判断是否可行。

## 盲评字段

```json
{
  "strategy_id": "...",
  "applicability_status": "supported|uncertain|contradicted",
  "supporting_facts": ["适用条件 2（行间独立）↔ 设计文档相邻章节规划的逐行独立搬入，无跨行依赖"],
  "contradictions": ["限制要求 UB 容纳整行，但设计 shape 上限 W=8192 fp32 超限"],
  "missing_information": ["无 profiling，无法确认预期瓶颈量级是否达该策略的机会阈值"],
  "already_present": false,
  "bottleneck_fit": "直接作用于主瓶颈假设 1（预期 MTE2 搬入带宽受限）",
  "confidence": 0.7
}
```

- `applicability_status`：`supported` = 条件全成立无红线冲突；`uncertain` = 机制对口但有
  未回答的前提；`contradicted` = 存在确凿冲突（条件不成立/红线触及/已纳入）。
- `supporting_facts` / `contradictions` 必须是「md 侧内容 ↔ 设计文档侧位置」的**对应**，
  不是单方复述。
- `confidence`：综合条件满足度 + 瓶颈直接度；无 profiling 时整体保守，
  `contradicted` 给低值（≤0.3）。

## 排序与选择规则

按序比较，产出 `ranked_candidates`（`confidence` 值即盲评条目的）：

1. **status 优先**：`supported` > `uncertain` > `contradicted`（contradicted 排最后或不入选）。
2. **`already_present=true` 降级**：排到同 status 组末尾（组内再按 3/4 级排）。
3. **confidence 降序**（同组内）。
4. **bottleneck_fit 直接度**（同 confidence）：直接作用于主瓶颈假设 > 作用于次假设 > 泛化改善。

**选择（Top3）**：排序后取前 3 条 `status ∈ {supported, uncertain}`（contradicted 不入选），
其中第 1 条必须是 `supported`（主策略）；supported 不足 3 条时按 `uncertain` 补足，
仍不足则少给（**如实记录，不凑数**）。

**至少 1 条 supported 才 `applicable=true`**；若 supported 为 0 而只有 1~2 条 `uncertain`，
可在 rationale 里写明"无完全适用策略，选最接近者（差距 X）"按 `uncertain` 落盘，
或判 `applicable=false`。全部 contradicted → `applicable=false`，rationale 逐条说明被否原因。

**防重复**：排序前再核对一次 `excluded_ids`（`run_inputs.json`），命中的候选直接丢弃并记录。

## 输出

- `verification.json`：盲评条目数组（粗筛候选**全量**，含被否的——被否理由也是证据）。
- 排序结论进 Phase 4 的 `ranked_candidates` 与 `selection.json`；门禁会校验
  `ranked ⊆ 粗筛候选集`、`selected_strategies`（≤3 条）`⊆ 粗筛候选集`且 `[0]` 即
  `selected_strategy`（主策略）。
- **吸收建议**：对最终选定的 ≤3 条策略，分别写明其对该算子设计的
  Buffer / Tiling / 多核切分 / 接口验证给出的具体约束或调整，并指出条与条之间的主次/冲突关系，
  供概设阶段写进开发方案。
