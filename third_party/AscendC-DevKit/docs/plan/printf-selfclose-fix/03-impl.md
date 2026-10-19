# L4 — 实施方案：printf_location 自闭环修复

## 改动清单（共 6 类 10 个文件）

### 一、框架层（2 文件）

#### 1. `src/ascendc_devkit/orchestration/precision_debug_tree.py`

**L86**：删 `"located": ("fix", "corrective")`，改为：
```python
"located_fixed": ("run_tests", "linear"),         # printf 自闭环修复成功 → 全量回归
```

**L87 "printf_done"**：从 `("run_tests", "corrective")` 改为 `("fix", "corrective")`。skip 完同 failure_type 后回 fix 而非跑全量回归。

#### 2. `src/ascendc_devkit/orchestration/stages/precision_debug_substages.py`

**L1811**：`_phase_prompt` 中"定位到则生成新 fix_plan 入池...写 control.printf_location_result='located'"改为"定位到则自己修复...修好写 'located_fixed'，修不好写 'exhausted'"。

**L1840**：返回协议行从 `PRINTF_CONTINUE / PRINTF_LOCATED / PRINTF_EXHAUSTED` 改为 `PRINTF_CONTINUE / PRINTF_FIXED / PRINTF_EXHAUSTED`。

**L1871 前**（`transition()` 的 exhausted 分支前）：插入 `located_fixed` 处理：
```python
if cp.get("printf_location_result") == "located_fixed":
    pass  # agent 已 commit + 标 resolved_pending，不放行到 exhausted/skip
```

**L1924-1926**：删 `if result == "located": return "located"`，替换为：
```python
if result == "located_fixed":
    return "located_fixed"
```

### 二、Agent manifest（1 文件）

#### 3. `.claude/agents/ascendc-precision-printf-locate.md`

**"Located" 段（L57-67）**：完全重写为自闭环修复流程：

```markdown
#### Located (root cause found)

1. 查知识库确认 API 用法（同现状）。
2. **直接修复**：
   a. Edit 代码，注意：只改定位到的根因，不做无关改动
   b. build_command 编译
   c. 单用例验证（test_command --case "<CASE_ID>"）
   d. 通过 → git commit → 写 control.json：
      - case.status = "resolved_pending"
      - case.last_fix_commit = <HEAD SHA>
      - printf_location_result = "located_fixed"
      - debug_state = "fresh"
      → 输出 RESULT: PRINTF_FIXED
   e. 失败 → git checkout 回退 → 分析原因 → 调整方案重试：
      - 有好转（diff 下降）→ 不限重试次数，持续修复
      - 连续 3 次无好转（diff 不变或上升）→ 放弃
3. **放弃时**：printf_location_result = "exhausted"
   → 输出 RESULT: PRINTF_EXHAUSTED（框架 skip 当前 case）
4. 不再生成 fix_plan 入 candidate_pool。
```

**返回协议（L95）**：删 `RESULT: PRINTF_LOCATED`，加 `RESULT: PRINTF_FIXED`。

### 三、Skill 方法载体（3 文件）

#### 4. `.claude/skills/ascendc-precision-printf/SKILL.md`

**L3 description**："生成新 fix_plan 加入 control.json.candidate_pool（source="bisect"），供 fix phase 验证" 改为 "定位到则自己修复、验证、commit；修不好跳过用例"

**L21**："生成新 fix_plan 入 candidate_pool..." 段改为自闭环修复流程

**L61**：`printf_location_result` 文档注释加 `"located_fixed"`

**L62**：删 `candidate_pool.hits[]` 的说明行（不再写）

**L127**：返回协议 `PRINTF_LOCATED` 改为 `PRINTF_FIXED`

#### 5. `.claude/skills/ascendc-precision-printf/references/prompts/printf_location.md`

**L36**：路由说明 "framework routes to fix" 改为 "framework routes to run_tests"

**L47**：删 `candidate_pool.hits[]` 说明

**L90**（首轮定位）："生成新 fix_plan...printf_location_result='located'" 改为直接修复流程

**L103**（续探定位）：同上

**L134**：删 `source="bisect"` fix_plan 生成伪代码段

**L231-305**：删 fix_plan 追加到 candidate_pool 的完整伪代码段 + `PRINTF_LOCATED` 返回说明。改为自闭环修复伪代码段 + `PRINTF_FIXED` 返回。

#### 6. `.claude/skills/ascendc-precision-printf/references/gates/gate3-printf-bisect.md`

**L44**："写 root_cause + fix_plan...printf_location_result='located'" 改为直接修复

**L63**：同上

### 四、Adapter 过渡脚本（2 文件）

#### 7. `.claude/skills/ascendc-precision-adapter/SKILL.md`

**L131**：`PRINTF_LOCATED` 改为 `PRINTF_FIXED`

**L150**：`PRINTF_LOCATED→fix` 改为 `PRINTF_FIXED→run_tests`

#### 8. `.claude/skills/ascendc-precision-adapter/scripts/transition.py`

**L228-229**：`PRINTF_LOCATED` 分支改为 `PRINTF_FIXED`，目标从 `"fix", "located(new bisect fix_plan)"` 改为 `"run_tests", "located_fixed(self-closed)"`

### 五、测试（1 文件）

#### 9. `tests/ut/orchestration/test_precision_debug_stage.py`

**L360-361**：`test_printf_located_resolve_condition` → 改为 `test_printf_located_fixed_resolve_condition`，mock `"located_fixed"`，assert 返回 `"located_fixed"`

**L745**：comment_bisect 的 `located` 路由测试 — **保留不变**（本次只改 printf）

**L752-754**：`test_printf_located_routes_to_fix` → 改为 `test_printf_located_fixed_routes_to_run_tests`，assert `transition_table["printf_location"]["located_fixed"] == ("run_tests", "linear")`

**L1706-1709**：同上改为 `"located_fixed"`

**新增测试**：
- `test_printf_done_routes_to_fix`：mock `case_skipped=True, more_cases=False` → assert resolve_condition 返回 `"printf_done"` → assert 路由到 `("fix", "corrective")`

### 六、状态文档（1 文件）

#### 10. `docs/plan/00-status-summary.md`

新增条目：
```
| printf-selfclose-fix | ✅ 已实施（日期） | [[printf-selfclose-fix/]] |
```

## 不在此次范围的清理项（后续收口）

- `fix.md:70,119` — `source="bisect"` 知识库前置确认，因 printf 不再生成此类 plan 成为死代码
- `ascendc-precision-fix.md:106,109` — bisect-sourced plans 的 sync check 和知识库验证
- `ascendc-precision-fix/SKILL.md:123` — `source="bisect"` 强制知识库查询
- comment_bisect — 保持现状，后续独立评估是否同理改造

## 验证顺序

1. UT：跑 `tests/ut/orchestration/test_precision_debug_stage.py` 全量，确认修改的测试通过 + 未修改的测试无回归
2. 真实链路：选 `ai_infra_aggregate_hidden_grad` 跑一轮 printf→自闭环→run_tests（需 NPU 环境，按 §3.11 用户决策）
