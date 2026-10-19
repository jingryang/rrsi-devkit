# L4：P10 实施——设计产物物理级不变式层（step-111）

> L3：`10-analysis-design-physical-invariants.md`（冻结）。TDD：先红后绿。
> 改动四件：设计 skill 判据+载体（A1/A2）、coder skill 消费行（F1）、
> TilingStage 机械在位检查（F2）、source-guard UT。

## 1. 改动清单（按实施顺序）

### 1.1 UT 先行（红）

新增 `tests/ut/orchestration/test_design_layout_contract.py`：

- **F2 单元**（直接构造 TilingStage.transition 输入，参照既有 tiling 段测试形态）：
  - `buffer_kernel.workspace` 为 dict 且 `layout_contract` 为非空字符串数组 →
    正常汇总进 `tiling_results`（不触发 error）；
  - `workspace` 为 dict 而 `layout_contract` 缺失 → `last_error.stage_name=tiling`、
    `error_type=incomplete_output`（R1 artifact-retry 族）、`user_feedback` 非空且含
    「layout_contract」；
  - `workspace` 为 dict 而 `layout_contract=[]` → 同上（空数组=未交付）；
  - `workspace='none'`（字符串）/ 缺省 → 不触发（无契约无义务）；
  - `layout_contract` 非字符串数组（如 dict）→ 同触发（类型不符）；
  - 反馈通道断言：`user_feedback` 文案点名「补全 layout_contract」+ 指向 skill
    边界条款语义（不出现算子名）。
- **source-guard**（读文件断言，step-109 先例形态）：
  - `ascendc-op-tiling-buffer-kernel/SKILL.md` 含「物理层展开边界」「点名载体」
    「同构」三关键词 + 三条结构信号（「GM 布局」「跨界契约」「同步边界」）；
  - 同文件 :109 区域含 `layout_contract`；
  - `ascendc-op-dev-coding/SKILL.md` 含 `workspace.layout_contract` 消费语义
    （「直译」「known_issues」关键词）；
  - **§1.12 守卫**：三个文件新增段落中不得出现具体算子名（unique_dim/
    logcumsumexp/interpolate/take_along 等本批实例名）——用既有 op 名黑名单
    断言模式；
  - schema example 中 layout_contract 条目为通用占位（不含具体实例公式变量）。

### 1.2 A1+A2：`.claude/skills/ascendc-op-tiling-buffer-kernel/SKILL.md`

1. 「与上游的一致性约束」段（:84 后）新增「**物理层展开边界（留白纪律）**」条款
   ——文案按 L3 §3.1（点名载体 OR 同构测试；三条结构信号枚举）。
2. :84 既有轴参边界条款末尾补半句衔接：「…泛化发射属 codegen 责任（其物理寻址
   公式已由 `axis_param_design.tiling_data_extensions` 载体承载，符合物理层展开
   边界）」——不推翻原条款。
3. :109 GM workspace 预算条款：契约对象扩为
   `{user_workspace_bytes, rationale, layout_contract}`；补一段 layout_contract
   交付要求（数组形态沿用 `axis_param_design.tiling_data_extensions` 表达；每条
   一个跨界事实；workspace 在位 ⇒ 非空；布局平凡给一条公式）。

### 1.3 schema：`schema/tiling_buffer_kernel.json`（同 skill 目录）

- `description` 中 workspace 说明补 layout_contract 语义（含 F2 在位检查提示，
  让设计 agent 在产物期即知义务）。
- `example.buffer_kernel.workspace` 增：
  `"layout_contract": ["planeA: blockDim*rows*sizeof(T)", "planeA.stride: rows", "publishDst === foldSrc"]`
  （通用占位符，禁实例公式）。

### 1.4 F1：`.claude/skills/ascendc-op-dev-coding/SKILL.md`

GM workspace 设置节（:203「userWorkspaceSize 优先取设计产物」行后）新增消费行，
文案按 L3 §3.3：契约在位→直译禁重推；冲突/缺位→最小推导 + decision_log 记因 +
known_issues 交棒。**不动** `ascendc-op-dev-coding-regbase`（A5 归同事，需单独
确认后另行落）。

### 1.5 F2：`src/ascendc_devkit/orchestration/stages/design_substages.py`

`TilingStage.transition`（:1872 `parse` 通过后、segment 汇总循环前）：

```python
ws = ((parsed.get("tiling_buffer_kernel") or {}).get("buffer_kernel")
      or {}).get("workspace")
lc = ws.get("layout_contract") if isinstance(ws, dict) else None
if isinstance(ws, dict) and not (isinstance(lc, list) and lc
                                 and all(isinstance(e, str) and e.strip()
                                         for e in lc)):
    msg = ("tiling: buffer_kernel.workspace 契约在位而 layout_contract 缺失/"
           "为空——GM workspace 布局契约须随 workspace 交付（平面公式/stride/"
           "地址恒等式，数组形态见 skill 物理层展开边界），补全后重交本段产物。")
    return state.with_updates(
        last_error=ErrorFeedback(stage_name=self.name,
                                 error_type="incomplete_output", message=msg),
        user_feedback=msg)
```

（复用 `_missing_artifact_error` 的「_error + user_feedback」通道形态；不新造
通道。`ErrorFeedback` import 同文件既有。二轮收紧（用户质询「F2 静默」后）：形态集
封闭为 {缺省, null, 'none', object}，畸形载体同样打回、反馈文案要求改形态——
UT 增 `test_workspace_malformed_shape_triggers_retry`（裸数字/list/字符串三态）+
`test_workspace_null_no_obligation`。）

## 2. 不做的事（防走样）

- 不给 `ascendc-op-tiling-split` / 概设 skill 加判据（布局产权在 buffer-kernel）。
- 不加「契约内容正确性」检查（内容归设计自检 + A1 判据，F2 只查在位）。
- 不加下游 validate 门查 layout（§2.9 门不越界）。
- 不动 A5 coder skill（同事产权）。
- 不做契约覆盖率实时统计（仅 known_issues/decision_log 观测留痕，§1.14）。

## 3. 验证

- 全量 UT（--quick）+ 全量 ST 默认模式。
- **测试充分性复核补充（2026-09-02）**：
  - UT +2：反馈消费闭环——`test_feedback_reaches_next_spawn_prompt`（F2 触发后
    `is_satisfied` False + 反馈进下次 spawn prompt 的「## 用户反馈」节）、
    `test_backfill_converges_and_clears_feedback`（同目录增量回填后契约进
    `tiling_results`、`user_feedback` 清空）——§2.9②「反馈可确定性消费」此前只测了
    字段置位、没测到达 prompt 与收敛。
  - ST +1（`test_design_pipeline_e2e.py`）：真实 Runner 循环端到端——stub 首轮写
    缺字段格式，**以 retry prompt 的「## 用户反馈」节为回填触发器**（首轮 prompt 的
    schema 渲染已含 layout_contract 字样，不能作判据——首版用例绿因错误，实证后
    修正）；断言恰 4 次 tiling spawn（2 模板 × 缺陷+retry）+ 下游 integrate/docgen
    未被一次有界 retry 拖垮。
  - **mutation 验证**：临时禁用 F2 检查 → 上述 ST 如期红（测试具备真实捕获力，
    非装饰性绿灯）。
  - **R1 归类修正**（实施期发现）：error_type 从 schema_violation 改
    `incomplete_output`——后者才在 `is_artifact_retry_error` 默认集内，走独立
    artifact-retry 预算（不烧 iteration），与 R1「确定性可纠正」定义逐字吻合；
    UT 增归类断言。既有 parse-errors 路径仍用 schema_violation（同形论证适用，
    但属既有行为、有既有测试锚定，不在本步扩改）。
- grep 审计：新增 skill 行零算子名、零 docs/plan 编号引用（§1.12/§2.11）。
- 下批端到端判据（真实验证，本步无法替代）：
  1. 复杂族（scan/carry/sort 族）coder 会话 ≥80k 补设计块占比 <20%（本批 66.9%）；
  2. `tiling_results.buffer_kernel.workspace.layout_contract` 在位且被 coder
     引用（run.log/tool 调用可见直译而非重推）；
  3. coder decision_log/known_issues 出现契约缺口信号（存量知识暴露，预期首批
     有、后续收敛）；
  4. 首批存量产物触发的一次性 F2 retry 有界（≤1 轮/模板）且反馈被消费（补全后
     通过）；
  5. 「FRAGILE (host/kernel formula drift)」类自评消失。

## 4. 风险与回退

- 首批一次性 retry 成本（预期、有界）；若某模板反复触发（>2 轮）说明 skill 文案
  不够可执行 → 修文案不修检查（判据方向正确性已由 L3 论证）。
- A5 侧契约消费缺口：设计链自动交付 layout_contract 但 A5 coder 无消费行 →
  无害（多余字段不被读），等同事确认后补齐对称消费。
