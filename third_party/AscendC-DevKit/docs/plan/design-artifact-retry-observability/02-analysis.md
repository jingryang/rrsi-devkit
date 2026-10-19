# L3 方案分析：产物契约未满足的公共 artifact-retry 抽象（runner 层）

> 对应 L1: [01-problems.md](01-problems.md)（R1/R2）。
> 决策演进：初稿为"design 局部加预算"（方案 A）；用户拍板"必须做正确改动"，升级为 **runner 层公共抽象（方案 C）**——因为同类别失败（产物契约未满足）在 codegen/design/precision 三阶段是三种处理，违反 §1.15 统一抽象。本版冻结方案 C。

## 0. 目标重述（正确改动）

把"**产物契约未满足 → 独立定向重试 → 不烧 iteration 预算**"从 codegen stage 内部实现**上移为 runner 层公共机制**，让所有 agent 型 stage（design/codegen/precision/...）自动继承。同时让重试可观测（R2）。

约束（CLAUDE.md）：
- §1.15 统一行为抽象，禁止逐点复制（codegen 有、design 无、precision 无 → 必须收敛单点）。
- §2.5 唯一通路（改造删 codegen 内部专属实现，收敛到公共通道）。
- §1.2 四把尺子（可维护/可扩展/可诊断/架构合理）+ 正确改动优先。
- §1.10 判据用业务语义显式声明（"产物契约未满足"是业务语义，非机制特征）。

## 1. 现状机制盘点（谁管"产物契约未满足"）

| Stage | 机制 | 位置 | 重试预算 | 烧 iteration? |
|---|---|---|---|---|
| codegen | `_artifact_retry`（不发 deploy_result → has_all=False → runner 自动重 spawn） | codegen.py:1171 | `codegen.artifact_max_retries=5` | **否** |
| design | `_missing_artifact_error`（last_error → runner 判契约不满 → 烧 iteration） | design_substages.py:547 | 无独立预算 | **是（缺陷）** |
| precision_debug | `retry`→diagnose corrective（树内循环） | precision_debug_tree.py:84 | `max_corrective` | 阶段内，非独立 |

**核心发现**：
1. codegen 的"独立 artifact-retry"**不是真独立预算**，而是"不发产物字段 → `has_all=False` → runner 自动重 spawn"，`artifact_max_retries` 只是防死循环的计数。
2. runner 现在只认两种失败：**cut**（不烧 iteration，streak 计数）与**非 cut**（烧 iteration）。缺产物（missing_artifact）落进"非 cut"→ 烧 iteration——**这就是 R1 的根因**。
3. 同样"产物契约未满足"，三阶段三种处理，是 §1.15 要消灭的散点。

## 2. 候选方案

### 方案 A（初稿，已否决）：design 局部加独立预算
- 只在 `_DesignSubstage` 加 `artifact_max_retries`，对齐 codegen。
- **否决理由**：① 是逐点修（§1.15 违反）——codegen 已有专属实现、precision 没有，会留"三阶段三套语义"长期态；② 没有解决 precision 的同类问题。

### 方案 B（已否决）：调大 tiling=2
- 一行 config，不改机制。**否决**：只把预算调大不修归并根因，下次还炸。

### 方案 C（推荐）：runner 层公共 artifact-retry 抽象

**核心设计**：在 runner 迭代判定中，识别"产物契约未满足"这一失败类别，提供公共重试通道——独立计数、不烧 iteration、喂定向反馈、可配置上限。所有 agent 型 stage 自动继承。

**三层结构**：
1. **判定层**（怎么认出"产物契约未满足"）：stage 通过 `output_contract` 声明"产物契约"；runner 在 `has_all=False` 且 `last_error` 指向 stage 且 `error_type ∈ {missing_artifact, incomplete_output}` 时，判定为"产物契约未满足"类别。
2. **预算层**（重试几次）：新 config `artifact.retry_max`（默认 5，对齐 codegen 现值），加载期校验（§1.3）。独立于 iteration 预算。
3. **反馈层**（怎么喂给下轮）：复用 stage 的 `user_feedback` / `codegen_artifact_feedback` 通道（已有），由 stage 的 transition 在返回 last_error 时携带。

**关键机制（对齐 codegen 已验证的")**：
- 触发重试 = 通过 `output_contract` 未满足 + 独立计数未耗尽 → **runner 不递增 iteration，递增 artifact_streak，自动重 spawn**；
- 耗尽后 → 落回 iteration 语义（消耗 1 次迭代预算）或 halt（stage 声明 fail_strategy=halt）。

**与 silent-cut / infra 的关系**（三种失败互斥）：
```
silent-cut（agent 没跑完）        → cut_streak++，不烧 iteration   （既有）
infra（spawn 失败/网关断）        → infra_retry++，不烧 iteration  （既有，P116）
产物契约未满足（跑完但没按契约产出）→ artifact_streak++，不烧 iteration  （新增，本方案）
```

### 方案 C 如何改造各 stage（§2.5 收敛）

| Stage | 现状 | 改造后 |
|---|---|---|
| codegen | `_artifact_retry` 专属实现 | 删专属实现，transition 返回 `error_type="incomplete_output"` + 不发产物字段 → 走公共通道 |
| design | `_missing_artifact_error` 烧 iteration | transition 返回 `error_type="missing_artifact"` → 走公共通道 |
| precision_debug | 树内 corrective 循环 | 保持（precision 是复合组、树内循环，产物契约判定语义不同），但**其 run_tests 子阶段缺产物时同样走公共通道** |

## 3. R2 可观测性增强（公共通道自带）

公共通道实现时内置三种日志信号（所有阶段统一受益）：
1. **iteration 重试显式标注**：`stage_iteration` / `iteration_start` 非首轮带 `retry-N/max`。
2. **独立事件类型 `artifact_missing_retry`**：含 artifact 文件名、`attempt/max`、反馈摘要、剩余 iteration。
3. **spawn 语义区分**：`agent_spawn`（新起）/ `agent_respawn`（iteration 重试）/ `agent_resume`（silent-cut）/ `agent_artifact_respawn`（产物重试）。

## 3.5 为什么上移 runner 而非公共 Stage 基类（架构论证）

方案 C 选 runner 层，不是"Stage 基类更高"，而是两条硬约束决定：

1. **纯函数边界：只有 runner 能控制 iteration**。
   `Stage.transition(state, result) -> State` 是纯函数（base.py 明示），不能改循环变量、不能 break 循环。`_iteration` 是 runner 的 while 循环变量，`iteration_ceiling` 由 runner 从 config 解析——"烧不烧 iteration"这个决策**只有 runner 能做**。若上移公共 Stage 基类，只能加"`should_artifact_retry()` 返回 True/False"的查询方法，但"真的不烧 iteration 并重 spawn"仍得 runner 执行——判定与执行分两半，反而更散。

2. **§1.10 归属：重试/超时/配额是横切控制流，唯一产权层是 runner**。
   CLAUDE.md §1.10 明确"横切控制流（超时/重试/放行/熔断/配额）判据用业务语义显式声明"，其执行归"掌握判定所需全部信号的层"（§1.15）。runner 同时持有 `_iteration`、`has_all`、`is_satisfied`、`last_error`——产物契约未满足的所有信号都在 runner，收敛于此天然正确。

3. **codegen 已隐式依赖 runner 的 has_all 机制，上移是显式化既有依赖**。
   codegen `_artifact_retry` 靠"不发 deploy_result → has_all=False → runner 自动重 spawn"这个**隐性约定**触发重试，计数（codegen_artifact_retries）藏在 stage。上移 = 把隐性约定显式化为 runner 公共分支，是收敛非新发明。

**分层结论**：Stage 基类声明语义（`error_type` 分类、`effective_artifact_retry_max`、`is_artifact_retry_error`），runner 执行控制（递增、重 spawn、日志）。查询在 Stage、控制在 runner——L4 已按此设计。

## 4. 四把尺子自检（方案 C）

- **可维护**：一份公共机制替代三处散点；config 一处声明；代码结构与 codegen 已验证模式同构。
- **可扩展**：任何新 agent 型 stage 只要声明 output_contract 就自动获得"产物契约未满足→定向重试"，同类新失败自动归位（§1.12）。
- **可诊断**：R2 三信号让重试全程可观测，不再静默。
- **架构合理**：runner 是"重试/超时/配额"横切控制流的唯一产权层（§1.10），公共 artifact-retry 放在 runner 天然正确——不是 stage 各自兜底。

## 5. 风险与验证

**风险**：动 runner 核心（全局影响）；删 codegen 专属实现可能引入回归。

**验证**（TDD，§3.1）：
1. **回归测试**：构造 T2 复现场景（agent 跑完但 tiling_split.json 写错目录）→ 断言"缺产物走独立 retry，不烧 iteration"→ N 次后仍缺才落 iteration/halt。
2. **codegen 回归**：既有 `artifact_max_retries` 行为不变（UT 覆盖）。
3. **precision 回归**：run_tests 子阶段缺产物走公共通道，corrective 循环不受影响。
4. **全量 UT + 非 heavy ST**（§3.6）。

## 6. 结论

采用**方案 C（runner 层公共 artifact-retry 抽象）**，同时闭合 R1（预算归并）+ R2（可观测）。这是正确改动：收敛三阶段散点为单点，所有 agent 型 stage 自动继承，不违反 §1.15/§2.5。

L4 实施方案按此展开。改动范围：
- `resources/orchestration-config.json`：新增 `artifact.retry_max`（公共默认 5）。
- `src/ascendc_devkit/orchestration/base.py`：Stage 加 `artifact_retry_max` 属性。
- `src/ascendc_devkit/orchestration/kernel/runner.py`：迭代判定加第三分支（产物契约未满足 → artifact_streak++，不烧 iteration）+ 三日志信号。
- `src/ascendc_devkit/orchestration/kernel/state.py`：加公共 `artifact_retries` 字段。
- `src/ascendc_devkit/orchestration/stages/codegen.py`：删 `_artifact_retry` 专属实现，transition 走公共通道。
- `src/ascendc_devkit/orchestration/stages/design_substages.py`：`_missing_artifact_error` 返回 `error_type="missing_artifact"` 走公共通道。
- `src/ascendc_devkit/orchestration/precision_debug_tree.py`：run_tests 子阶段缺产物走公共通道。
