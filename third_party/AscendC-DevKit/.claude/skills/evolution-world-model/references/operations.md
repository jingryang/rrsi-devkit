# 世界模型操作指南

本文件定义了 `lingxi-dsl-evo` Agent 在进化过程中对 `world_model.json` 执行的四种核心操作的推理框架。

**重要**：这里的"操作"不是调用外部 API，而是 `lingxi-dsl-evo` Agent 自身的推理过程——读取 JSON 文件，在自身思考中完成分析，然后用 Write/Edit 工具写回结果。

---

## 操作一：Init（初始化）

**时机**：步骤3（共享文件准备）完成后，进化轮次开始前执行一次。

**输入**：
- `output/{op_name}_evo_{timestamp}/shared/{op_name}_op_desc.json`
- `output/{op_name}_evo_{timestamp}/shared/{op_name}_functional.py`
- 基线评测结果（Mode B 专有）
- `.claude/skills/evolution-strategies/references/strategy_index.md`
- `parallel_num` 参数

**推理过程**（Agent 自身思考）：

```
1. 算子特性分析：
   - 这是内存密集型还是计算密集型算子？
     （判断依据：元素级操作→内存密集；矩阵乘→计算密集）
   - 数据类型：FP16/BF16/FP32？是否需要精度特殊处理？
   - 形状特征：输入shape固定还是可变？是否有对齐问题（非32字节倍数）？
   - 复杂度：是否有归约操作、广播、特殊数学函数？

2. 瓶颈假设（根据算子特性形成 open_questions）：
   - 内存密集型算子 → 首要假设是带宽利用率不足
   - 计算密集型算子 → 首要假设是计算流水线停顿
   - 存在尾块 → 假设尾块处理影响整体效率
   - FP16输入 → 假设精度问题可能影响正确性

3. 初始优化方向设计（每个方向 = 一个决策树节点）：
   - 数量：parallel_num × 2 个（确保前两轮不缺 open 节点）
   - 多样性要求：不同节点的 strategy_combination 不得完全相同
   - 覆盖范围：
     * 至少 2 个性能方向（P系列：双缓冲、分块、向量化等）
     * 1 个组合方向（P+P 组合）
     * 1 个精度/类型方向（A/D系列，如适用）
     * 1 个高难度深度方向（difficulty=4，复杂组合）
     * 1 个保守基础方向（difficulty=2，单一策略）
   - 参考 strategy_index.md 中的 "When to Apply" 列，识别匹配该算子类型的策略
   - 类型覆盖要求（用于 Select 多样性保底）：
     * 每个节点必须设置 optimization_type 字段
     * A3 架构 (220x/Membase): bandwidth/tiling/algorithm 三类各至少有 1 个节点
     * A5 架构 (351x/Regbase): 还包括 register_opt/vf_fusion/instruction_sched，
       按实际存在的类型动态分配保底槽位
     * 推导规则：策略中 P1/P7/P10/P11/R5 为主 → bandwidth；
       P2/P4/P5/P8 为主 → tiling；R2 → register_opt；R1 → vf_fusion；
       R3/R4/R8 → instruction_sched；其余或 open_exploration → algorithm
     * D/A 系列策略不影响类型标签（它们是精度约束）

4. 难度估计原则：
   - difficulty=1: 单一简单策略（如仅P7对齐）
   - difficulty=2: 单一中等策略（如P1双缓冲）
   - difficulty=3: 两策略组合（如P1+P7）
   - difficulty=4: 三策略组合或复杂单策略（如P2+P4+P10）
   - difficulty=5: 已知失败（评测后自动设置，初始化时不使用）
```

**输出**：按照 `schema.md` 格式写入 `world_model.json`。

**兜底**：若 JSON 写入失败，向用户报告警告，设置运行时标志 `world_model_active = false`，后续使用 tiered sampling 兜底。

---

## 操作二：Select（动作选择）

**时机**：每轮进化开始时，创建并行目录前执行。

**输入**：`world_model.json`，`parallel_num`

**推理过程**（Agent 自身思考）：

```
1. 读取所有 status="open" 的节点列表

2. 对每个 open 节点计算效用分（统一公式，与 wm_ops.py 一致）：
   parent_node = decision_tree.nodes[node.parent_id]
   parent_score = parent_node.score（若为null则用1.0）

   w_root_explore = 2.0（若 parent_id == "root"）或 0.0（其他）
   w_evidence = 1.5（若父节点有 profiling_evidence）或 0.0

   utility = 3.0 × parent_score          // 父节点表现越好，子节点越值得探索
           + 2.5 × (5 - difficulty)       // 难度越低，优先级越高
           + 0.75 × depth                 // 适当鼓励深度探索（已证明方向继续挖掘）
           + w_root_explore               // 根节点直接子节点享有探索加成
           + w_evidence                   // 父节点有深度 profiling 数据时加成

   参数含义：
   | 参数 | 取值 | 说明 |
   |------|------|------|
   | parent_score | float ≥ 1.0 | 父节点的 speedup 评分，null 时用 1.0 |
   | difficulty | 1-5 整数 | 实现难度，越低优先级越高 |
   | depth | int ≥ 0 | 节点在决策树中的深度 |
   | w_root_explore | 2.0/0.0 | 根节点的直接子节点（parent_id=="root"）享有 +2.0 加成，保证第一层方向充分探索后才深化子分支 |
   | w_evidence | 1.5/0.0 | 父节点有 profiling_evidence（指令级深度分析）时加成，因为更精确的瓶颈数据使子节点策略推荐更可靠 |

3. 按 utility 降序排列所有 open 节点

**执行方式**（优先调用确定性脚本）：
```bash
SELECTIONS=$(python3 .claude/skills/evolution-world-model/scripts/wm_ops.py select \
  --path output/{op_name}_evo_{timestamp}/world_model.json \
  --n {parallel_num})
```
若脚本不可用，按上述公式手工计算。

4. 槽位分配（保底 + 放权，共 parallel_num 个槽位）：

   保底轮（确保类型覆盖）：
   - 对 bandwidth、tiling、algorithm 三类，各取该类型内效用分最高的 1 个 open 节点（strategy_guided 组）
   - 若某类型无 open 节点则跳过
   - 保底节点最多占 min(3, sg_slots) 个槽位

   剩余槽位（效用分驱动）：
   - 从未选中的 strategy_guided 节点中按效用分降序填充
   - 不再有类型约束

   open_exploration 专用槽位（不变）：
   - 槽位 (parallel_num-1) 保留给 open_exploration 组效用分最高的节点
   - 若无可用则由 strategy_guided 补位

   若 parallel_num == 1：取全局效用分最高节点，不区分类型

   - 若 open 节点总数不足：用自由探索占位节点补齐（strategy_combination=[], difficulty=2,
       description="自由探索，基于已有经验选择多样化策略"）

5. 将选中节点的 status 更新为 "in_progress"，写回 world_model.json

6. 输出选择结果（供 4.2 构建子agent提示词使用）：
   [{
     "parallel_index": 0,
     "node_id": "n1",
     "description": "双缓冲流水线 + 32字节对齐",
     "strategy_combination": ["P1", "P7"],
     "parent_solution_ref": null  // 父节点的solution_ref（如有）
   }, ...]
```

**兜底**：若读取 world_model.json 失败，返回空选择列表，子agent自由选择策略。

---

## 操作三：Refine（结果更新）

**时机**：每轮所有子agent完成后，收集结果后立即执行。

**输入**：
- `world_model.json`
- 本轮每个 parallel_p 的 `evaluation_results.json`
- 本轮 Select 的选择结果（node_id → parallel_index 的映射）

**推理过程**（Agent 自身思考）：

```
1. 读取 world_model.json

2. 对每个执行的 (node_id, parallel_index) 对：
   读取 output/{op_name}_evo_{ts}/round_{r}/parallel_{p}/evaluation_results.json

   【新增步骤：提取 evaluation_digest 写入节点】
   无论通过还是失败，从 evaluation_results.json 提取结构化摘要：
   node.evaluation_digest = {
     "status": "passed" | "compile_fail" | "precision_fail" | "runtime_error",
     "speedup": float | null,
     "error_hint": "一句话描述失败原因" | null,
     "precision_gap": "max_ae=X, max_re=Y" | null,  // 仅精度失败时填写
     "cv_pct": float | null,                         // 评测变异系数（std/mean×100），反映测量稳定性
     "measurement_quality": "good" | "acceptable" | "noisy" | null
     // good: cv<5%, acceptable: 5-15%, noisy: >15%；用于 Refine 动态阈值
   }
   此摘要供后续子节点的 sub-agent 直接参考，了解父节点"在哪里失败"或"性能卡在哪里"。

   判断评测结果：

   ✅ 若 compilation_success=true AND precision_passed=true（评测通过）：
      - 设置 node.status = "passed"
      - 设置 node.score = evaluation_results.speedup
      - 设置 node.solution_ref = "round_{r}/parallel_{p}"
      - 同时写入 solution_db.jsonl（通过 solution_db.py 追加）：
        * solution_id = "round_{r}_parallel_{p}"
        * parent_solution_id = 父节点的 solution_ref（若存在，否则 null）
        * kernel_path = "round_{r}/parallel_{p}/{op_name}Custom/op_kernel/{op_name}_custom.cpp"
        * speedup、strategy_combination、round、op_name、evo_timestamp 等字段一并填写

      判断是否生成子节点：
      parent_score = decision_tree.nodes[node.parent_id].score 或 1.0

      **动态阈值（基于评测质量）**：
      读取 evaluation_results.json 中的 measurement_quality 字段：
      - "good" (cv < 5%)       → improve_threshold = 1.05, stag_threshold = 1.02
      - "acceptable" (cv 5-15%) → improve_threshold = 1.08, stag_threshold = 1.03
      - "noisy" (cv > 15%)     → improve_threshold = 1.15, stag_threshold = 1.05
      若字段缺失，默认使用 "good" 级别阈值。

      if node.score > parent_score × improve_threshold:  // 动态阈值，相对父节点有实质提升
         生成 2 个子节点，推理如下：
         - 子节点A：当前策略 + 互补策略（如 P1+P4 → P1+P4+D1）
           description 说明新增的互补策略解决的问题
         - 子节点B：当前策略 + 不同角度（如 P1+P4 → P1+P4+A5）
           description 说明从不同角度进一步深化
         - 两个子节点的 strategy_combination 必须不同
         - 子节点 difficulty = min(5, parent.difficulty + 1)
         - 子节点 depth = node.depth + 1
         - 将子节点ID追加到 node.children，并加入 nodes 字典

      elif speedup > 0（通过但无实质提升，即 node.score ≤ parent_score × 1.05）:
         生成 1 个延续子节点：
         - 从当前策略的未探索角度继续（description 必须含"延续探索"字样，
           避免子agent误以为该方向已被充分验证）
         - difficulty = parent.difficulty（不递增，因未确认有效）
         - depth = node.depth + 1
         - 将子节点ID追加到 node.children，并加入 nodes 字典

      else（failed）:  // 编译失败 or 精度不通过
         执行失败诊断（见下方 ❌ 分支），根据 failure_type 决定 difficulty 和子节点

   ❌ 若失败（编译失败 or 精度不通过）：

      【第一步：层次化诊断（3层递进，替代自由推理）】

      从 evaluation_results.json 中提取诊断信息（无需读取额外文件）：
      - `compilation_success` / `precision_passed`：判断失败类型
      - `implementation_note`：子agent实现时写入的摘要
      - `error_message`（若存在）：编译错误的简短描述

      **若 implementation_note 缺失**：仅作为兜底，读取内核代码的 Compute 函数部分
      （不超过 50 行）进行判断。

      【第二步：层次化 failure_type 诊断】

      按以下 3 层递进判断（每层回答一个确定性问题）：

      **Layer 1 — 编译层**：能否编译通过？
        → 否 → 错误类型是？
          · API 调用错误 / 参数类型错误 / 函数未声明 → failure_type = "impl_error"
          · 硬件不支持该指令集 / 平台限制（极少数）→ failure_type = "strategy_infeasible"
        → 是 → 进入 Layer 2

      **Layer 2 — 精度层**：精度是否通过？
        → 否 → 精度偏差量级是？
          · max_ae > 1.0（数量级错误）→ 大概率是计算逻辑错误 → failure_type = "impl_error"
          · max_ae < 1.0 但超出阈值 → 检查 implementation_note：
            - 策略要求的关键步骤在代码中缺失/偏差 → failure_type = "impl_error"
            - 代码与策略描述吻合，精度仍不满足 → failure_type = "strategy_infeasible"
        → 是 → 进入 Layer 3（不在此分支处理，属于通过路径）

      【第三步：根据 failure_type 设置节点字段并决定是否重试】

      设置：
         node.status = "failed"
         node.failure_type = <推理结果>
         node.failure_reason = <推理说明（1-2句）>

      若 failure_type = "impl_error" 且 node.retry_count < 2：
         - node.difficulty = min(4, original_difficulty + 1)  // 不设为5，仅适度提升难度
         - 生成 1 个修复子节点：
           * id = "{node_id}_fix{retry_count+1}"
           * description = "[修复实现] {failure_reason}。
             修复要点：{从策略文件和错误信息中提炼的具体修复指导，1-2句}"
           * strategy_combination = node.strategy_combination（继承，不变）
           * difficulty = node.difficulty（继承修正后的值）
           * depth = node.depth + 1
           * retry_count = node.retry_count + 1
           * status = "open"
         - 将子节点加入 node.children 和 nodes 字典
         - open_question 措辞：
           "[{策略组合}] 判断为实现错误（{failure_reason}），已生成修复节点 {fix_node_id}"

      若 failure_type = "strategy_infeasible" 或 node.retry_count >= 2：
         - node.difficulty = 5  // 彻底封锁该策略方向
         - 不生成子节点
         - open_question 措辞：
           "[{策略组合}] 已封锁（{failure_reason}）"

3. 更新顶层字段：
   - best_score = max(best_score, 所有本轮 passed 节点的 score)

   本轮最佳 speedup = max(本轮所有 evaluation_results.speedup，仅passed节点)
   本轮测量质量 = 本轮所有 passed 节点中 measurement_quality 最差的一个
   （优先取最悲观估计，避免噪声导致的假阳性）
   stag_threshold = 1.02（good）/ 1.03（acceptable）/ 1.05（noisy）
   if 本轮最佳 speedup <= 上一轮 best_score × stag_threshold:
      stagnation_count += 1
   else:
      stagnation_count = 0

   // 第二计数器：vs parent_base（K-Search 风格）
   // 检测：本轮探索的变体中，是否至少有一个超越了其父节点得分？
   round_base = max(
      decision_tree.nodes[node.parent_id].score ?? 1.0
      for each executed node in this round
   )
   if 本轮最佳 speedup > round_base:
      stagnation_count_vs_base = 0   // 有变体超越其父节点，分支仍然活跃
   else:
      stagnation_count_vs_base += 1  // 所有变体均未超越其父节点，分支停滞

4. 写回 world_model.json
```

**Refine 完成后，验证写入结果**：
```bash
python3 .claude/skills/evolution-world-model/scripts/wm_ops.py validate \
  --path output/{op_name}_evo_{timestamp}/world_model.json
```
若验证失败，输出错误列表并尝试修正（如补充缺失的延续子节点）。

**兜底**：若写入失败，执行 tiered sampling（原有分层采样），不阻断进化流程。

---

## 操作四：Analyze（假设更新）

**时机**：Refine 完成后立即执行。

**输入**：更新后的 `world_model.json`，本轮所有评测结果

**推理过程**（Agent 自身思考）：

```
1. 读取 world_model.json

2. 基于本轮及历史评测结果，对 open_questions 进行推理：

   分析模式（从评测结果中归纳规律）：
   - 哪些策略组合取得了最好的效果？
     → "策略X在该算子上表现良好，应优先在后续变体中使用"
   - 哪些策略组合失败或效果不佳？
     → "策略Y导致编译失败，后续子节点应避免单独使用Y"
   - 已通过节点之间是否有共同特征？
     → "所有通过节点都包含双缓冲，这可能是关键因素"
   - 是否识别出新的瓶颈假设？
     → "P10（向量化）提升有限，可能不是带宽瓶颈，而是计算瓶颈"

3. 将归纳出的假设写入 open_questions（最多5条，用简洁的陈述句）：
   - 每条不超过50字
   - 直接可指导下一轮子节点生成的具体建议优先
   - 删除已被证伪的旧假设

4. 写回 world_model.json
```

**注意**：Analyze 的结果（open_questions）会在下一轮 Refine 的子节点生成阶段被参考，形成"假设→验证→新假设"的循环。

---

## 操作时序图

```
Step 3.5:  [Init] → 创建初始世界模型，生成 N×2 个 open 节点

Round 1:
  [Select] → 选 parallel_num 个 open 节点，标记 in_progress
  [并行生成] → lingxi-dsl-partial × parallel_num（每个变体有明确策略）
  [收集结果]
  [Refine]      → 更新节点状态，生成通过节点的子节点
  [CSV Profile] → 每个 passed 节点做 CSV 级瓶颈诊断，检测瓶颈迁移
  [Deep Profile] → 条件触发：瓶颈迁移/CSV盲区/停滞破局时做指令级空泡分析
  [Analyze]     → 更新 open_questions

Round 2:
  [Select] → 从 open 节点（含 Round1 生成的子节点）选 parallel_num 个
  [并行生成] → lingxi-dsl-partial × parallel_num
  [收集结果]
  [Refine]      → 继续更新树
  [CSV Profile] → 更新瓶颈诊断，检测相对上轮的瓶颈迁移
  [Deep Profile] → 条件触发（含与上次深度分析的 diff 对比）
  [Analyze]     → 继续更新假设
  ...

终止条件满足 → 输出最优解 + 保存 world_model.json 快照
```

---

## 效用函数参数调整建议

在默认效用函数 `utility = 3.0×parent_score + 2.5×(5-difficulty) + 0.75×depth + w_root_explore` 中：

| 场景 | 建议调整 |
|------|---------|
| 探索阶段（前1-2轮）| depth 权重降为 0（避免过早深度优先） |
| 剥削阶段（best_score已很高）| parent_score 权重提升到 4.0 |
| 停滞时（stagnation_count>0）| 强制选择 depth 最浅的节点（重新探索） |

---

## 停滞阈值配置

```
stagnation_window = 2   // 默认值
                        // 根据 max_rounds 自动调整：
                        // max_rounds <= 3 → stagnation_window = 1
                        // max_rounds == 4 → stagnation_window = 2
                        // max_rounds >= 5 → stagnation_window = 3

// 双计数器共享同一阈值，任意一个触发即停止（OR 逻辑）：
//   stagnation_count ≥ stagnation_window      → 全局停滞（本轮最佳 vs best_score×1.02）
//   stagnation_count_vs_base ≥ stagnation_window → 分支停滞（本轮最佳 vs 父节点得分）
```
