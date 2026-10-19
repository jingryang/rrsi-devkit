# ops-partial 子agent Prompt 模板

供 ops-evo 步骤 4.3.2 中启动 ops-partial 子agent 时使用。
主 agent 读取此模板，按 ops_evo.md 中的"Prompt 变量填充规则"填充 `{变量}` 后作为 prompt 传给子 agent。

---

```
[TASK]
Modify, build, and evaluate AscendC kernel code for {op_name} operator in ops repository.

Operator: {op_description_from_def_cpp}
Source: {output_dir}/shared/original/
Output: {output_dir}/round_{r}/parallel_{p}/modified_files/

[MANDATORY OPTIMIZATION DIRECTION]
你被分配的优化方向是:
  方向描述: {node_description}
  策略组合: {strategy_combination}
  模式: {mode}

⚠️ 你必须严格按此方向实现优化。
- 禁止偏离到其他方向（如仅调整 tiling 阈值、仅改 BUFFER_NUM 等简单参数修改不算"实现策略"）
- 你的修改必须体现上述方向描述中的核心优化思路
- 如果此方向在技术上不可行，在 implementation_note.txt 中说明原因，而不是静默切换到其他方向

同轮其他变体的方向（禁止重复）:
{other_variants_summary}

[STRATEGY REFERENCE CODE]
{strategy_reference_code}

⚠️ 以上是精简策略卡片（~50行/策略），只包含核心模式和关键陷阱。
**禁止读取完整策略文件**（500-1000行，会爆上下文窗口）。

你的任务：
1. **读策略卡片**（上面已提供）：理解核心模式（代码骨架 + 关键修改点 + 常见陷阱）
2. **用 Grep 搜索当前代码**：按卡片底部的"代码搜索关键词"定位对应结构
3. **只读相关函数**：用 `sed -n 'START,ENDp'` 读取包含关键结构的函数（不要读整个文件）
4. **映射并重构**：将专家模式映射到当前代码，按关键修改点实施重构
5. **如果不可行**：在 implementation_note.txt 中说明原因（架构不匹配/已存在更优实现）

[STRATEGY PLAYBOOKS]
Playbook 已加载的策略 ID: {playbooks_loaded_ids}
Preconditions 过滤报告: {precond_filter_report}

{strategy_playbooks}

⚠️ **Playbook 使用规则（强制）**：
- 若上方 `Playbook 已加载的策略 ID` 为空（即 `{playbooks_loaded_ids}` 为空字符串）→ 走卡片流程（ops_partial.md 阶段 1-2）
- 若 `Playbook 已加载的策略 ID` 含 X,Y → 对 X 和 Y **必须**按其 Playbook 的 Step 1-6 逐步执行；其他没有 Playbook 的策略走卡片流程
- Playbook 在 `===== PLAYBOOK {ID} BEGIN =====` 和 `===== PLAYBOOK {ID} END =====` 之间，正文含 `---` 是 markdown 分隔线（不是 Playbook 边界）
- Playbook 的 Step 5 grep 自检**任一失败 = 回到 Step 3 重做**。禁止在 implementation_note 中把失败检查标记为"不适用"
- 若确有合法的另类实现不匹配 Step 5 的 grep，必须在 implementation_note 中说明**具体 grep 项、实际代码、为什么等价**
- Preconditions 已在主 agent 阶段过滤：你看到的策略（除被过滤的 X 外）都是**已通过适用性检查**的，放心应用

[Optimization Approach]
If Mode=open_exploration:
  DO NOT read strategy files. Reason from first principles.
  Analyze bottleneck and profiling data, design novel optimization approach.

If Mode=profiling_driven:
  DO NOT read strategy files. The node description contains specific profiling bottleneck data — use it as your optimization target.
  a. Read parent kernel code and understand current implementation
  b. Parse the profiling bottleneck from node description (e.g., "MTE2 stall 62%", "scalar compute blocking 40%")
  c. Design a TARGETED optimization specifically addressing the diagnosed bottleneck
  d. Modify kernel/tiling files with targeted patches (don't rewrite from scratch)
  e. In implementation_note: state what profiling bottleneck was targeted and how

If Mode=strategy_guided:
  策略卡片已在上方的 [STRATEGY REFERENCE CODE] 中提供。
  执行步骤：
  a. 阅读策略卡片，理解核心模式（代码骨架 + 关键修改点）
  b. 按卡片底部的"代码搜索关键词"用 Grep 定位当前代码中的对应结构
  c. 只读包含关键结构的函数体（用 sed 提取，禁止读完整文件）
  d. 按"关键修改点"逐条实施重构，而不仅仅是改常量
  e. 对照"常见陷阱"检查修改是否正确

[CONTEXT]
Node: {node_id} | Parent: {parent_solution_ref} | Best: {best_solution_ref}

{inspirations_text}

Kernel: {kernel_summary}
Score: global best {best_score}x | this variant from {parent_score}x ({parent_solution_ref or "baseline"})

[Profiling Context]
Pipeline: {profiling_one_liner}
Bottleneck: {bottleneck}
Recommended: {recommended_strategies}
{若有 profiling_evidence:}
Bubble Analysis: D-class={d_class_pct}% C-class={c_class_pct}%
Primary stall: {primary_bottleneck}
DMA efficiency: MTE2 short={mte2_short_pct}% MTE3 short={mte3_short_pct}%
Pattern: {pattern_type} | Overlap: {overlap_status}
{/若}

Bottleneck-targeted guidance:
  memory_bound → increase tile size, enable double buffer, merge DMA transfers
  scalar_bound → reduce GetValue calls, vectorize reductions, hoist loop-invariants
  compute_bound → algorithm optimization, eliminate redundant compute
  mte2_stall → redesign data layout, enlarge transfer blocks, batch small DMAs
  tiling_imbalance → rebalance core workload, adjust block_dim partitioning
  no_overlap → restructure CopyIn/Compute/CopyOut stage boundaries for pipeline overlap

Hardware: {hw_params_one_liner}

Steps:
1. **Read strategy cards** from [STRATEGY REFERENCE CODE] above (~50 lines, lightweight)
   → Understand: core pattern + key changes + common pitfalls

2. **Grep search current code** (DO NOT read full files yet):
   ```bash
   # Use keywords from strategy card's "代码搜索关键词" section
   grep -n "KEYWORD1\|KEYWORD2" op_kernel/*.cpp op_host/*_tiling.cpp
   ```
   → Locate: which file, which line contains the structure to modify

3. **Read only relevant functions** (NOT full files):
   ```bash
   # Extract just the function containing the target structure
   sed -n 'START_LINE,END_LINEp' op_kernel/xxx.cpp
   ```
   → Understand: current implementation of the target structure

4. **If parent_solution_ref non-empty**: read parent variant's modified files (already filtered)

5. **Map strategy to code structure**:
   a. Compare expert pattern (from card) with current code (from step 3)
   b. Determine if pattern can be applied (architecture match check)
   c. Plan: which functions to refactor, what changes to make

6. **Implement the refactoring** — follow the expert pattern, NOT just parameter tuning

7. operator-coding-red-line check (read .claude/skills/operator-coding-red-line/SKILL.md only, skip ascendc-code-review)

8. Save modified files + code_changes.json + implementation_note.txt

9. Apply modified files to worktree and build

10. Evaluate with eval-lock (baseline vs evolved on bound device)

Implementation Quality Standards (STRICTLY ENFORCED):
- ✅ 允许: 重构循环结构、增加/修改同步点、修改buffer分配策略、重新设计数据流
- ✅ 允许: 修改多个函数、跨文件协调修改、引入新的辅助函数
- ❌ 禁止: 仅修改常量/阈值而不改变代码结构（如只改 BUFFER_NUM 不改循环）
- ❌ 禁止: 策略不可行时不说明原因、静默改参数应付
- ❌ 禁止: 修改后代码逻辑与策略描述不符（如说"双缓冲"但循环还是单缓冲模式）

Modification Constraints (STRICTLY ENFORCED):
- op_kernel/*.cpp, *.h: Free to modify (do not change call signatures)
- op_host/*_tiling.h, *_tiling.cpp: Allowed to modify (do not change field names)
- op_host/*_def.cpp: Restricted (compile options/optimization attributes ONLY; NEVER change inputs/outputs/type constraints)

[BUILD & EVAL CONTEXT]
Worktree Path: {worktree_base}/round_{r}_p{p}
Worktree Repo Root: {worktree_base}/round_{r}_p{p}
Worktree Op Path: {worktree_base}/round_{r}_p{p}/{OP_PATH_RELATIVE}
Z-Search Root: {z_search_root}
Install Path: $(pwd)/output/{op_name}_ops_evo_{timestamp}/round_{r}/parallel_{p}/evolved
Baseline Install Path: $(pwd)/output/{op_name}_ops_evo_{timestamp}/baseline
Device ID: {session_device_id}
Eval Lock Path: {eval_lock_path}
Baseline Cache: $(pwd)/output/{op_name}_ops_evo_{timestamp}/baseline_evaluation.json
Call Spec: $(pwd)/output/{op_name}_ops_evo_{timestamp}/shared/call_spec.json
Op Name: {op_name}
Build Op Name: {build_op_name}
SOC: {soc}
Task Type: {task_type}
Eval Lock Timeout: 300

[MULTI-SHAPE CONTEXT]
{multi_shape_context}

[HISTORY]
{open_questions_rendered}

Output all modified files to: {output_dir}/round_{r}/parallel_{p}/modified_files/
```
