# L4 实施方案：runner 层公共 artifact-retry 抽象

> 对应 L3 [02-analysis.md](02-analysis.md)（方案 C 冻结）。状态：待实施。

## 0. 目标

把"产物契约未满足 → 独立定向重试 → 不烧 iteration"从 codegen stage 专属实现**上移为 runner 层公共机制**，所有 agent 型 stage（design/codegen/precision）自动继承。同时让重试可观测（R2）。

## 1. 现状（改造前的两套机制）

**codegen 已有（要上移的模板）**：
```python
# state.py
codegen_artifact_retries: int = 0      # 独立计数
codegen_artifact_feedback: dict | None = None  # 下轮提示
# codegen.py _artifact_retry():
#   不发 deploy_result → runner has_all=False → 自动重 spawn
#   计数 >= limit → halt（error_type="incomplete_output"）
```

**design 缺陷（要修）**：
```python
# design_substages.py _missing_artifact_error():
#   设 last_error(error_type="missing_artifact") + user_feedback
#   → runner has_all=False → 但烧 iteration（无独立计数）
```

## 2. 改动清单（按实施顺序）

### 步骤 1：State 增加公共字段

`src/ascendc_devkit/orchestration/kernel/state.py`：
- 加 `artifact_retries: int = 0`（公共计数，替代 codegen_artifact_retries）
- 加 `artifact_feedback: dict | None = None`（公共反馈）
- `from_snapshot`/`to_snapshot` 的字段清单同步加（state.py:564-565 那类）

### 步骤 2：Stage 基类加属性 + config

`src/ascendc_devkit/orchestration/base.py`：
- Stage 加 `artifact_retry_max: int = 5`（默认对齐 codegen 现值）
- 加 `is_artifact_retry_error(self, error_type) -> bool` 默认判 `error_type in {"missing_artifact", "incomplete_output"}`

`resources/orchestration-config.json`：
- `codegen` 段的 `artifact_max_retries` 保持（向后兼容 codegen）
- 新增公共 `artifact.retry_max`（默认 5），`effective_artifact_retry_max(stage)` 优先 stage.artifact_retry_max → config artifact.retry_max → 5

`src/ascendc_devkit/orchestration/runtime_config.py`：
- 加 `artifact_retry_max()` 加载器（对齐 `codegen_artifact_max_retries` 风格，§1.3 加载期校验）

### 步骤 3：runner 迭代判定加第三分支（核心）

`src/ascendc_devkit/orchestration/kernel/runner.py`（循环内，Part 3 附近 535 行）：

```python
# 新增：产物契约未满足 → 独立 artifact-retry，不烧 iteration
_art = getattr(result_state, "last_error", None)
_is_art = (_art is not None
           and getattr(_art, "stage_name", None) == stage.name
           and stage.is_artifact_retry_error(getattr(_art, "error_type", "")))
if _is_art:
    _art_streak = getattr(result_state, "artifact_retries", 0) + 1
    if _art_streak < stage.effective_artifact_retry_max():
        # 独立计数递增，不烧 iteration，自动重 spawn
        result_state = result_state.with_updates(artifact_retries=_art_streak)
        self.Logger.warn(
            f"Stage '{stage.name}' artifact-retry ({_art.error_type}: "
            f"{_art.message}) retry {_art_streak}/{stage.effective_artifact_retry_max()}; "
            f"NOT consuming iteration budget")
        # 不递增 _iteration，continue 循环
        _iteration -= 1   # 用 continue 后 _iteration += 1 抵消，或重构循环变量
        continue
    else:
        # 耗尽 → 落回 iteration 语义（消耗 1 次迭代预算）
        self.Logger.warn(
            f"Stage '{stage.name}' artifact-retry exhausted "
            f"({_art_streak}/{stage.effective_artifact_retry_max()}); "
            f"falling back to iteration budget")
```

**注意**：此处必须小心循环结构。现有循环 `while _iteration <= ceiling` + `_iteration += 1`。artifact-retry 分支应**不执行 `_iteration += 1` 且 continue**。需要把 Part 3 的 `_iteration += 1` 挪到"非 artifact-retry 且非 cut"分支，或用一个 `continue` 跳过递增。用 `continue` 最清晰（与 cut 分支并列）。

### 步骤 4：codegen 收敛到公共通道（§2.5 删专属）

`src/ascendc_devkit/orchestration/stages/codegen.py`：
- `_artifact_retry` 改为：写 `state.artifact_retries` / `state.artifact_feedback`（不再写 codegen_artifact_retries），last_error 用 `error_type="incomplete_output"` 触发公共通道。
- 删 `codegen_artifact_retries` / `codegen_artifact_feedback` 字段（state.py）——收敛，不保留新旧并存（§2.5）。
- `codegen_artifact_max_retries()` 保留但作为公共 `effective_artifact_retry_max` 对 codegen 的 override。

### 步骤 5：design 接入公共通道

`src/ascendc_devkit/orchestration/stages/design_substages.py`：
- `_missing_artifact_error` 已经返回 `error_type="missing_artifact"` + `user_feedback`——**已天然匹配**公共通道判定（`is_artifact_retry_error` 含 missing_artifact）。无需改 transition，只需确认 runner 公共分支识别它。
- 删掉 `_DesignSubstage` 里任何"烧 iteration"的隐性依赖（如果有），确保走公共通道。

### 步骤 6：precision_debug run_tests 子阶段接入

`src/ascendc_devkit/orchestration/precision_debug_tree.py`：
- run_tests 子阶段缺产物时（产物契约未满足）→ 返回 `error_type="missing_artifact"`，走公共通道。
- 保持 corrective 循环（那是阶段内"更多候选"语义，非缺产物重试）。

### 步骤 7：R2 可观测性（公共通道自带三信号）

`src/ascendc_devkit/orchestration/kernel/runner.py`：
1. **iteration 重试标注 retry-N**：`stage_iteration`/`iteration_start` 非首轮加 `(retry-N/max)`。
2. **新增事件 `artifact_missing_retry`**：含 artifact、attempt/max、反馈摘要、剩余 iteration（在步骤 3 的 Logger.warn 处 emit）。
3. **spawn 语义区分**：`agent_spawn`（新起）/ `agent_artifact_respawn`（产物重试）——在 actions 返回 SpawnAgent 时根据 stage 上下文标注。

## 3. 验证（TDD，§3.1）

### 回归测试（先写，后实施）

`tests/` 新增 `test_artifact_retry_common.py`：

**用例 1（R1 核心）**：构造 design 子阶段，agent 产物 `tiling_split.json` 写错目录。
- 断言：第一次 missing_artifact → `artifact_retries=1`，**iteration 不递增**（仍是 1）；
- 断言：第 2、3 次 → 递增 artifact_retries，iteration 仍不变；
- 断言：耗尽 `artifact_retry_max` → 落回 iteration（iteration 才递增）→ 终 halt。

**用例 2（codegen 收敛回归）**：既有 codegen manifest 非契约行为不变。
- 断言：`_artifact_retry` 走后 `artifact_retries` 递增、不发 deploy_result、耗尽 halt 行为同旧。

**用例 3（R2 可观测）**：
- 断言：events.jsonl 出现 `artifact_missing_retry` 事件，含 `attempt/max`；
- 断言：`stage_iteration` 重试带 `retry-N`。

**用例 4（precision 回归）**：run_tests 子阶段缺产物走公共通道，corrective 循环不受影响。

### 全量验证

- `pytest`（UT 全量 + 非 heavy ST，§3.6）
- 真实 T2 复现场景（可选，用 DRY_RUN 或单算子 resume 验证缺产物重试）

## 4. 风险与回滚

- **风险**：动 runner 全局核心。缓解：先写用例 1（T2 复现）验证公共分支，再动 codegen/design 收敛。
- **回滚**：公共分支是加法（新增 if 分支），不破坏既有 cut/infra 路径；若回归，先 revert runner 分支，codegen/design 的字段收敛可单独回滚。

## 5. 完成判据

- [ ] UT 用例 1-4 全绿
- [ ] `pytest` 全量通过（无回归）
- [ ] codegen `_artifact_retry` 删除，`codegen_artifact_retries`/`codegen_artifact_feedback` 字段移除（§2.5）
- [ ] events.jsonl 能观测到 `artifact_missing_retry` + iteration retry-N
