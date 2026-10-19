# L4 实施方案 C — 次要修复

> 层级：**L4 / 实施方案**。具体改哪个函数、怎么验证。
> 覆盖问题：P6, P7, P8（见 `01-problems.md`）

## P7：requirement-analyst 注入 SKILL.md

### 改动文件：`src/ascendc_devkit/orchestration/stages/requirement.py`

**位置**：`_build_analysis_prompt` 方法（第 141 行）。

参考设计子阶段的 `_with_trigger()` 模式。当前 `_build_analysis_prompt` 首行为 `"## 任务..."` 或 `"## 模式..."`，需在最前插入 slash command 触发：

```python
def _build_analysis_prompt(self, state: State, iteration: int) -> str:
    sections = []

    # 新增：slash command 触发词，CLI 展开注入 SKILL.md
    sections.append("/stage-requirement:ascendc-op-req-analysis\n")

    # 后续保持不变...
```

## P8：partial agent 但 contract 满足

已在 `03-impl-a-fail-strategy.md` 中覆盖（runner.py 的 `stage_status` 判断）。

## P6：stall + RuntimeError（后期跟进）

优先级低于 P1-P4，不阻塞本次上线。修复方向：

1. `runner._execute_spawn_agent`：在 `_spawn` 返回的 except 分支中增加 `aclose()` 保护
2. `design_substages._build_prompt`：增加 iteration 上下文（`"## 重试上下文\n第 N 次尝试..."`），让 agent 感知迭代
