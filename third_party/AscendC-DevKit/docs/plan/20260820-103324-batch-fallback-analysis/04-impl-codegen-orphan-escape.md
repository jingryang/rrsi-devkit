# L4 实施方案：codegen 孤儿检测 + 熔断/空跑区分

> 对应问题：F2 剩余缺口（codegen 孤儿产物不可见）、F5（empty_artifacts 语义冲突）。
> 前置：commit `4a066149` 已解决设计子阶段孤儿（方案 A）；本方案处理 codegen 层。
> 用户决策（2026-08-20 确认）：空跑与孤儿**都要重试**，但区分重试次数；circuit breaker 只对空跑（5 次）；1000 是修 bug 的迭代预算，两者不混；孤儿注入路径反馈 + 重生成。

## 一、背景与机制澄清

### 三个失败模式的机制差异

| 失败模式 | 根因 | 重试有意义吗 | 现在处理 | 应该处理 |
|---------|------|------------|---------|---------|
| **空跑**（moe_re_routing） | 模型 thinking 泥潭，0 产出 | 低（模型没进入写阶段） | empty_artifacts → 3 次熔断 halt | 熔断合理（防空烧 token），阈值 3→5 |
| **孤儿**（写错目录） | 模型路径幻觉，写了但写错地方 | 高（反馈后能改正） | empty_artifacts → 3 次熔断 halt | **不该熔断**，注入路径反馈 + 重试 |
| **编译失败** | 代码有错 | 高（build-retry 专门处理） | 走 build-retry（独立预算） | 已合理 |

### 两层机制的关系（用户明确）

```
runner 迭代层：iteration_ceiling = 1000（配置 codegen:1000）
  └─ 这是"修 bug"的迭代预算——孤儿、编译失败等可修复问题用这个

codegen 内部 circuit breaker：codegen_consecutive_failures
  └─ 这是"防空跑"的熔断——只对空跑（0 产出，重试无意义）计费
```

**两者不能混为一谈**：
- **1000 = 修 bug 的迭代次数**：孤儿（反馈后能改正）、编译失败（build-retry）等可修复问题，用 1000 预算反复尝试。
- **circuit breaker = 空跑熔断**：空跑（模型没进入写阶段，反馈无用）5 次后 halt，防空烧 token。

## 二、复用 vs 新增（改动性质标注）

**核心结论：区分"circuit breaker"与"修 bug 计数"是复用现有能力，不是新增机制。**

| 能力 | 现状 | 本方案 | 性质 |
|------|------|--------|------|
| 熔断计数 `codegen_consecutive_failures` | 任何非 ok 非 infra 都 +1 | 只空跑 +1；孤儿不 +1 | **复用字段，改累加条件**（`_transition_membase` 一处） |
| 熔断触发 `actions()` 返回 [] → runner break | 已存在（codegen.py:648, runner.py:465） | 阈值 3→5 | **复用机制，改常量** |
| 修 bug 迭代 `iteration_ceiling=1000` | runner 机械循环上限 | 孤儿天然落进去（不熔断→继续迭代到成功/1000） | **复用 runner，零改动** |
| 孤儿反馈通道 `codegen_artifact_feedback` | 已有（manifest 缺字段用，注入下轮 coder context） | 孤儿路径塞进该字段 | **复用通道，改内容** |
| 孤儿判定 `_transcript_orphan_paths` | 无 | 新增（扫描 transcript 找 wd 外 Write） | **唯一新增**（判据，非机制） |
| error_type `artifact_misplaced` | 无 | 新增（区分孤儿/空跑，供日志/scope_guard 辨） | 小新增（枚举值） |

**为什么是复用**：
- 熔断与迭代是**两个独立维度**，机制都已存在——熔断防空跑（空 actions → break），迭代给可修 bug 预算（1000）。
- 孤儿当前**错误地**消耗熔断（3 次 halt），是因为 `_transition_membase` 把所有非 ok 都 +1。改判据后，孤儿不 +1 → circuit breaker 不触发 → runner 的 1000 迭代预算接管。
- 反馈通道（`artifact_feedback`）已是 codegen 修 bug 的既有路径，孤儿复用即可。

## 三、改动点

### 改动点 1：`max_consecutive_failures` 3 → 5

`codegen.py:129`：`max_consecutive_failures = 5`。空跑熔断阈值放宽（用户决策：空跑可做 5 次重试）。

### 改动点 2：孤儿判定 + 熔断/孤儿区分（`_transition_membase` 失败分支）

`codegen.py:2848-2867`（失败分支）。当前所有非 ok 非 infra 都 `codegen_consecutive_failures + 1`。改为：

```python
# 区分空跑 vs 孤儿：扫描 transcript 是否有写到 op_dir 外的 Write 证据
transcript_path = getattr(agent_result, "transcript", None)
orphan_paths = _transcript_orphan_paths(transcript_path, working_dir)  # 新辅助

is_infra = is_infra_error_type(agent_result.error_type)
if orphan_paths:
    # 孤儿：不消耗熔断，注入路径反馈，走迭代预算重试
    feedback = (
        f"你上次把文件写到了 {orphan_paths}（op_dir 之外），"
        f"正确位置是 op_dir（{working_dir}）。请重新生成到正确位置，"
        f"用相对路径写入。"
    )
    return state.with_updates(
        last_error=ErrorFeedback(
            stage_name="codegen",
            error_type="artifact_misplaced",  # 新 error_type 区分
            message=feedback,
        ),
        codegen_artifact_feedback=feedback,   # 复用反馈通道，注入下轮 coder
        codegen_consecutive_failures=state.codegen_consecutive_failures,  # 不累加
        codegen_iterations=iterations,
    )
else:
    # 空跑：累加熔断
    return state.with_updates(
        last_error=ErrorFeedback(
            stage_name="codegen",
            error_type=agent_result.error_type if is_infra else agent_result.status,
            message=...,
        ),
        codegen_iterations=iterations,
        codegen_consecutive_failures=(
            state.codegen_consecutive_failures if is_infra
            else state.codegen_consecutive_failures + 1
        ),
    )
```

### 改动点 3：新增辅助函数 `_transcript_orphan_paths`

放 `_shared.py`（转录解析的通用层，codegen 和 design_substages 都依赖 `_shared`，无循环依赖）。扫描 transcript 返回所有写到 `wd` 外的 Write/Edit 目标路径列表。

```python
def _transcript_orphan_paths(transcript, wd) -> list[str]:
    """Scan a transcript for Write/Edit targets outside ``wd``.
    Returns list of absolute paths the agent wrote outside its working_dir,
    or [] when no transcript / no such writes. Used by codegen to distinguish
    'orphan' (wrote but misplaced) from 'empty run' (wrote nothing)."""
    ...
```

**batch 判定分两情形**（实施中发现的设计要点）：
- **wd 有 batch 锚点**（design 子阶段，wd 在 artifacts 树下）→ 孤儿必须同 batch，跨 batch 明确拒绝（防跨 run 误搬/误判）。
- **wd 无 batch 锚点**（codegen，op_dir 在 cann-bench 仓、不在 artifacts 树）→ batch 锚点无意义，**只看"wd 外 + transcript 证据"就算孤儿**。反馈重试是安全行为（不搬移，最坏误判也只是让 coder 重写）。

### 改动点 4：`last_error.error_type` 新增 `artifact_misplaced`

让下游（scope_guard / halt reason）能区分"孤儿"与"空跑"。`ErrorFeedback` 接受任意 error_type（现有 codegen 已用 status 作 error_type，无白名单），`artifact_misplaced` 直接可用。

**反馈通道用 `user_feedback`（不用 `codegen_artifact_feedback`）**：`codegen_artifact_feedback` 的数据结构是 dict（`missing_fields/retry_count/...`），供 manifest 非契约重试渲染（`_build_codegen_prompt:2204`）；孤儿反馈是路径字符串，塞进去会 AttributeError（str 无 `.get`）。`user_feedback` 是 str、已渲染（`_build_codegen_prompt:2053`），是干净通道。成功出口已清 `user_feedback`（P5）。

## 四、孤儿反馈内容

`codegen_artifact_feedback` 注入下轮 coder context（`codegen.py:727-728` 现有机制）：
```
你上次把文件写到了 [路径列表]（op_dir 之外），正确位置是 op_dir（[op_dir 绝对路径]）。
请重新生成到正确位置，用相对路径写入。
```

配合改动点 5（prompt 注入 op_dir 绝对路径）双保险。

## 五、验证方案（已实施）

### UT（tests/ut/orchestration/test_codegen_orphan_escape.py，10 用例全过）

`TestTranscriptionOrphanPaths`（6）：
1. **孤儿判定**：同 batch wd 外 Write → `_transcript_orphan_paths` 返回该路径 ✅
2. **空 transcript** → [] ✅
3. **无 transcript** → [] ✅
4. **wd 内 Write** → []（不算孤儿）✅
5. **wd 有锚点 + 跨 batch Write** → []（防跨 run 误判）✅
6. **codegen wd 无锚点 + wd 外 Write** → 识别为孤儿 ✅

`TestCodegenBreakerSemantics`（4）：
7. **max_consecutive_failures = 5** ✅
8. **孤儿不熔断**：`codegen_consecutive_failures` 不累加，`user_feedback` 含路径反馈，`last_error.error_type == artifact_misplaced` ✅
9. **空跑熔断**：`codegen_consecutive_failures + 1`，无路径反馈 ✅
10. **孤儿反馈渲染进下轮 coder prompt**（消费端验证）✅

### 回归（已跑）

- `test_codegen*.py` + 相关（cut_allowance/rerun/stage_failure_status）：221 passed。
- orchestration 全套：**1793 passed, 0 failed**。
- 全量 UT 待跑。

## 六、原则符合性（待确认后实施）

- §1.2 合理性优先：孤儿是"写了但写错"，反馈后重试是最小且正确的修复；不搬移（避免跨仓不可控）。
- §1.10 业务语义：用"有无 Write 证据"（业务语义：是否产出过）区分空跑/孤儿，不用机制特征。
- §2.9 自检闭环：孤儿反馈由 coder 下一轮消费（有明确反馈渠道）。
- §1.3 加载期校验：`max_consecutive_failures` 是加载期常量，改动集中。
- 可诊断：孤儿路径 WARN + error_type=artifact_misplaced，日志可辨。

## 七、范围界定

- **不搬移** codegen 孤儿（用户决策：搬移大量代码不可控）。
- **不碰** build-retry（独立预算，已合理）。
- **不碰** design_substages 的方案 A（已解决设计子阶段）。
