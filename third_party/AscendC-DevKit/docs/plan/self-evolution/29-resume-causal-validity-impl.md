# P52 — resume 因果有效性（node_status clean-prefix）实施方案（第四层）

> 状态：**已完成 ✅**（2026-07-08）。UT 1642 + 非 llm ST 114 全绿；16 heavy_llm 按 §3.11 未默认跑。
> 层级：**第四层 / 实施方案**。改哪个函数、什么顺序、怎么验证。
> 覆盖问题：P52（L1 `06-problems.md`）。方案分析见 L1「可行性与修法」+「边界」条（已冻结，无独立 L3——方案在讨论中收敛、无灰区、无选项分歧）。
> L2：step 27。
> 约定：按符号定位（不写 file:line）；外部依赖只读；TDD 红→绿（§3.1）。

---

## 1. 设计决策（冻结）

### 1.1 不变式：clean-prefix 因果有效性

一个 SequentialGroup scope 内，**「completed 有效」⟺ 该节点在 scope 的 children 顺序中，所有前序兄弟也是 completed**。scope 内首个「非 completed」（failed / missing / 其他）节点之后的所有 completed，**视作无效、作废**（→ resume 重跑）。

- 「非 completed」判据：`node_status.get(child_path) != "completed"`（failed、缺失、任何中间态都算打破前缀）。
- 仅作用于 **SequentialGroup**（children 有顺序依赖）。
- **ForkJoinGroup 不作用**：分支并行独立，A failed 不作废 B completed（见 §1.3）。

### 1.2 统一通路（§1.2 + §2.5）

loopback 运行期清除（`GraphExecutor._execute_sequential` 路由回退时清 `order[target_idx..i]` 含子树、尊重 `rerun_selector`）与 resume 期作废下游 completed，**是同一 clean-prefix 不变式的两个触发点**。loopback 现有的 ad-hoc range 清除是该不变式的**残缺实例**（只覆盖 loopback 触发点、且靠运行期路由才触发；resume 场景缺触发点就漏）。

**定法**：抽承载不变式的 primitive，loopback 与 resume 两端调用、**替换** loopback 原 ad-hoc 清除（非保留两套）。L1 关联所述 `invalidate_completed_from` 在此**细化为两层**（经代码精读，loopback 清除还含 group 子树 + `rerun_selector` 分支选择，primitive 必须完整承载，不能比现有更残缺）。

### 1.3 primitive 分层（实施定稿）

经代码精读 + TDD，落地为两层（L1 关联所述 `invalidate_completed_from` 细化为）：

- **底层 `_invalidate_subtree(ns, child_path, child_node, targets=None)`**（两端真正共用的复用单元）
  - 作废 `child_path` 本身 + 其子树。
  - AtomicStage：仅 pop `child_path`。
  - group：pop `child_path`，再清 `child_path + "/"` 前缀子树键；`targets` 为 None 全清，为分支名集合只清选中分支（loopback 的 template-precise rollback）。
  - 提取自 loopback 原 ad-hoc 循环体——**行为与原 loopback 一致**，只是变成可复用函数。
  - 纯函数（mutate 调用方传入的 ns 副本）。

- **中层 `_invalidate_sequential_range(ns, scope_path, order, by_name, start, end, state, targets_of=None)`**（loopback 专用便利层）
  - 对 `order[start:end]` 逐个调底层，`targets_of(child_node, state)` 解析每个节点的 rerun_selector。
  - **仅 loopback 用**（pop 范围内所有节点含子树，不管状态——loopback 要重跑这一段）。
  - 配 `_rerun_targets_of(child_node, state)` 解析 rerun_selector。

- **resume 不用中层**——resume 的语义是「只作废 first_bad **之后**的 **completed**（保留 failed/missing 诊断标记）」，与 loopback「pop 范围所有」不同。resume 直接用底层 `_invalidate_subtree(ns, cp, c)`（targets=None），自己控制「first_bad 之后 + 仅 completed」的过滤 + 递归（见 §2.2）。这符合 [avoid-overdesign-prefer-reuse]：共用底层 subtree invalidation，两端各自的「范围+过滤」逻辑不强塞进一个中层。

落点：底层 + 中层放 `orchestration/graph_executor.py` 模块级（loopback 在此），dispatcher resume import 底层。

---

## 2. 改造点

### 2.1 改造点 A：loopback（`GraphExecutor._execute_sequential`）

路由回退清除段（现 ad-hoc `for j in range(target_idx, i + 1)` 循环体）替换为：

```
cleared = _invalidate_sequential_range(
    state.node_status, path, order, by_name, target_idx, i + 1, state)
state = state.with_updates(node_status=cleared)
```

行为**等价**于原循环（`range(target_idx, i+1)` ⟺ `[target_idx, i+1)`），由回归测试守护（§4 用例 8 + 现有 loopback ST 全绿）。

### 2.2 改造点 B：resume（`_resume_node_status`，dispatcher）

现状是 `return dict(state.node_status)`（passthrough，不作废）。重写为遍历 workflow 树 + clean-prefix（实际落地）：

1. `_walk(node, scope_prefix)` 递归遍历（复用 `Workflow.flat_stages` 的 `_walk` 模式，但访问所有 group 节点）。
2. 对每个 **SequentialGroup scope**（含 root）：
   - 遍历 children，找首个 `ns.get(child_path) != "completed"` = `first_bad`。
   - 若存在：对 `children[first_bad+1:]` 中 `ns.get(path) == "completed"` 的，调底层 `_invalidate_subtree(ns, cp, c)`（targets=None，全清子树）。**first_bad 自身保留**（failed/missing 已会重跑，保留其标记有诊断价值）。
   - **递归进所有 children**（含 first_bad 及之前）——一个 failed/invalidated group 内部可能仍持 valid prefix（嵌套 scope，用例 6）；fork-join child 也要递归。
3. **ForkJoinGroup**：不作 clean-prefix（分支并行独立），递归进 children（其内可能嵌套 SequentialGroup）。
4. path 拼接：模块内 `_node_path(node, scope_prefix)` 镜像 `GraphExecutor._path` 规则（`node.name if not scope_prefix else f"{scope_prefix}/{node.name}"`），保证与 execute 一致。
5. `workflow.root` 存在才遍历（duck-typed：只需 `.root`）。

---

## 3. 实施顺序（TDD 红→绿）

1. **红**：写 §4 全部用例（先失败）。
2. **绿-底层**：提取 `_invalidate_subtree`（从 loopback 循环体平移，行为不变）。
3. **绿-中层**：`_invalidate_sequential_range`，loopback 改造点 A 切换（回归测试验证等价）。
4. **绿-resume**：改造点 B，`_resume_node_status` 加 clean-prefix（§4 用例 1–7 转绿）。
5. **回归**：UT 全量 + 非 heavy ST（§5）。

---

## 4. TDD 用例（红→绿）

| # | 用例 | 场景 | 期望 |
|---|---|---|---|
| 1 | `test_resume_invalidates_downstream_completed_after_failed` | root scope: codegen=completed, verify=failed, adapt/eval/finalize=completed | adapt/eval/finalize 作废；codegen 保留、verify 非 completed 本就重跑（**本 run 实证场景**） |
| 2 | `test_resume_preserves_valid_completed_prefix` | a/b=completed, c=failed, d=completed | a/b 保留, d 作废 |
| 3 | `test_resume_all_completed_unchanged` | 全 completed | 不动作 |
| 4 | `test_resume_missing_breaks_prefix` | a=completed, b 缺失, c=completed | c 作废（missing 也打破 clean-prefix） |
| 5 | `test_resume_forkjoin_branches_independent` | fork-join: A=failed, B=completed | B 保留（分支并行独立，互不作废） |
| 6 | `test_resume_nested_sequential_scope` | group G 内: g1=completed, g2=failed, g3=completed | G 内 g3 作废（递归 scope） |
| 7 | `test_resume_forkjoin_failed_breaks_parent_prefix` | root: a=completed, forkjoin=failed, b=completed | b 作废（forkjoin 在父 scope 是 failed，打破父 clean-prefix；但 forkjoin 内部已 completed 分支不被作废，见用例 5） |
| 8 | `test_loopback_invalidation_equivalence` | loopback 用新 primitive 后 | 现有 loopback ST 全绿（行为等价回归） |

用例 5 与 7 是 ForkJoinGroup 边界的两面：内部不作 clean-prefix（5），但 forkjoin 节点自身在父 SequentialGroup 的 clean-prefix 中正常参与（7）。

测试落点：复用既有 resume / graph_executor 测试文件（能合并进既有文件就不新开，[heavy-llm-test-design] 同精神）。这些是纯逻辑/编排用例，用 StubBackend，标 UT（§3.5/§3.8）。

---

## 5. 验证（已通过）

- **UT 1642 全绿**（含 §4 的 8 个新 P52 用例 + 既有 loopback/resume/graph_executor 套件 0 回归）。
- **非 llm ST 114 全绿 / 16 deselected**（含 test_npu 真实 kernel 执行、test_resume_cli、test_loopback_e2e、test_design_pipeline_e2e）。
- 改造点 A 行为等价由现有 loopback ST（loopback_e2e / composite_loopback / tiling_precise_rollback）全绿守护。
- 改造点 B 由 §4 的 1–7 + 端到端用例守护。
- **heavy_llm（16 deselected，tui_selfclosure 类）按 §3.11 未默认跑**：P52 是确定性控制流/纯逻辑（clean-prefix 不变式 + 结构清除），非 §3.9 LLM 行为对象，UT 已充分覆盖；特性交付/PR 合并前由用户决策是否跑一次完整 self-evolve e2e 做 resume 节点复盘。
- **既有用例更新**：`test_node_status_passthrough_unchanged` → `test_node_status_sole_authority_no_phantoms`。原 ns 构造的是 detailed-design 内部 dd-intake 缺失但 template-division/tiling completed 的 stale 场景，verbatim passthrough 断言描述的是 P52 修复前的 bug 行为；改为验证 sole authority + 不注入 phantom（P52 后仍成立的核心产权）。

---

## 6. 不在本次范围

- **P51（verify continue 侧硬崩溃控制流）正交**：P52 不挡 verify 首次崩溃推进下游（P52 只在 resume 兜底）。P51 的灰区默认值待用户拍板后立 L4。两者互引用，分开落。
- **loopback 的 `rerun_selector` 分支选择语义**：本次只把它的承载从 ad-hoc 循环移到 primitive，**不改其语义**。
- 不改 `fail_strategy`、不改 transition_table、不改 fork-join 并行执行。
