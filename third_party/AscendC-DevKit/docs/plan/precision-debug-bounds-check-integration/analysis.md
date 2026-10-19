# ascendc-bounds-check → precision_debug 集成分析

## 一、两套系统概述

### 1.1 ascendc-bounds-check（目标合入 skill）

**性质**：纯静态、离线、确定性检查工具。不依赖 NPU。

| 维度 | 说明 |
|------|------|
| 输入 | tiling + kernel C++ 源码、**单个失败 shape**（来自 run_tests）、dtype、硬件参数 |
| 方法 | 对目标 shape 计算 tiling 参数 → 构建 Python 影子 → 该 shape 下全枚举 blockIdx × sOuterIdx 检查 |
| 检查项 | GM_OOB（越界）、UB_OOB（UB 溢出）、ALIGN_32B（对齐）、UB 总量 |
| 输出 | 结构化 findings（CRITICAL/WARNING/INFO）、UB 预算差距分析 |
| 退出码 | exit code = CRITICAL 数量 |

**核心工作流**：
1. 从 control.json 取当前用例的 shape 参数（run_tests 已有）
2. 读 C++ 源码，分类标量计算（地址计算 vs 纯数据操作）
3. 按 6 条 transform-rules 逐函数构建 Python 影子（用该 shape 实例化）
4. 该 shape 下全枚举 blockIdx × sOuterIdx + 检查（GM_OOB / UB_OOB / ALIGN_32B / UB 总量）
5. 报告生成（按 root cause 去重分组）

**与原 skill 的差异**：原 skill 设计为通用工具，支持"shape 参数矩阵兼容性扫描"（多 shape 批量扫）。集成到 precision_debug 后，**shape 由 run_tests 的失败用例提供，只需检查那一个 shape**——不需要扫 shape 矩阵。

### 1.2 precision_debug pipeline（合入目标）

**性质**：运行时驱动的闭环精度调试流水线。依赖 NPU。

```
run_tests → scope_guard → diagnose → fix → printf_location/comment_bisect
    ↑                                     ↓
    └─────────────────────────────────────┘
```

| Sub-stage | agent_name | 职责 |
|-----------|-----------|------|
| `RunTestsSubstage` | `ascendc-precision-run-tests` | 跑全量精度用例，构建 failed_case_queue |
| `ScopeGuardSubstage` | `ascendc-precision-scope-guard` | 首轮判定失败是否属于上游缺陷 |
| `DiagnoseSubstage` | `ascendc-precision-diagnose` | 静态分析失败症状，生成 candidate_pool |
| `FixSubstage` | `ascendc-precision-fix` | 按优先级验证 fix_plan（单用例），commit/rollback |
| `DiagnoseRefineSubstage` | `ascendc-precision-diagnose` | runtime→runtime 洋葱剥皮增量诊断 |
| `PrintfLocateSubstage` | `ascendc-precision-printf-locate` | printf 二分定位首个数值发散点 |
| `CommentBisectSubstage` | `ascendc-precision-comment-bisect` | 注释二分定位 runtime crash 根因 |

## 二、bounds-check 在 precision_debug 中的价值

### 2.1 当前 diagnose 的盲区

当前 `DiagnoseSubstage` 的 LLM agent 做 Gate1（静态模式匹配）+ Gate2（同步检查），但其分析依赖：
- 代码阅读 + 模式识别（受限于 LLM 的上下文窗口和理解能力）
- 对外部 skill（`ascendc-dev-knowledge`、`ascendc-sync-static-check`）的调用

**LLM 静态分析天然做不到的事**：
- 对**单个失败 shape** 下 `blockIdx ∈ [0, blockDim)` × `sOuterIdx ∈ [0, ubLoopNumS)` 的全枚举：LLM 一次只能追踪一条执行路径，无法穷举所有 blockIdx
- 末核尾块的精确越界判定（`CeilDiv` 产生的 phantom rows）：blockIdx=0 跑得好好的不代表 blockIdx=blockDim-1 安全，越界往往只在末核尾块触发
- UB 预算的精确计算（tiling 公式 vs 实际 Init 分配的差异）

bounds-check 的 Python 影子**恰好填补了这个空缺**：它是确定性的、穷举的、可复现的。shape 来自 run_tests 的失败用例（不需要 shape 矩阵扫描）。

### 2.2 可以拦截的 bug 类型

| Bug 类型 | diagnose (LLM) | bounds-check (Python) | 确定性 |
|----------|---------------|----------------------|--------|
| GM 行越界（s_row >= S） | 可能漏（需理解循环守卫逻辑） | ✅ 全枚举必中 | 100% |
| GM 元素越界（offset+len > capacity） | 可能漏（需计算所有路径） | ✅ 全枚举必中 | 100% |
| UB buffer 越界 | 可能漏（需精确计算 offset） | ✅ 全枚举必中 | 100% |
| 32B 对齐违规 | 模式可匹配 | ✅ 全枚举必中 | 100% |
| UB 总量超限（tiling 公式漏算） | 几乎不可能 | ✅ 精确对比 | 100% |
| 同步缺失 | ✅ Gate2 专长 | ❌ 不覆盖 | N/A |
| API 约束违规 | ✅ Gate1 专长 | ❌ 不覆盖 | N/A |

**bounds-check 和 diagnose 是互补而非替代**。

### 2.3 节省的迭代成本

若 bounds-check 在 diagnose 之前运行并发现 CRITICAL：
- **跳过 LLM diagnose**：不需要 agent 推理 → 省 token + 省时间
- **fix_plan 确定性高**：bounds-check 的输出可直接转为 fix_plan（source="bounds_check"），不需要 LLM 猜测
- **首次 fix 命中率提升**：地址计算 bug 是 fix 的"硬骨头"，LLM 往往需要多次尝试才能定位；bounds-check 一次定位到行级

## 三、集成方案

### 方案 A：作为新 substage（推荐）

在 scope_guard 和 diagnose 之间插入 `BoundsCheckSubstage`：

```
run_tests → scope_guard → bounds_check → diagnose → fix → ...
```

**优点**：
- 职责清晰：bounds_check 有自己的 phase JSON（`precision_bounds_check.json`）、agent、skill
- 路由灵活：可以独立控制 loop-back（bounds_check 定位到问题 → 跳 fix；没定位到 → 线性到 diagnose）
- 可观测：每个 spawn 有独立的 history 条目
- 符合现有架构模式（每个 phase 一个 substage）

**需要创建的文件**：
```
.claude/skills/ascendc-precision-bounds-check/
├── SKILL.md                          # 从 ascendc-bounds-check/SKILL.md 改造
├── references/
│   └── transform-rules.md            # 从 ascendc-bounds-check/references/transform-rules.md 复制
├── schema/
│   └── precision_bounds_check.json   # phase JSON schema（新增）
└── scripts/
    └── run_bounds_check.py           # Python 影子生成 + 运行脚本（新增）

.claude/agents/
└── ascendc-precision-bounds-check.md  # agent manifest（新增）
```

**需要修改的文件**：
- `precision_debug_substages.py`：新增 `BoundsCheckSubstage`（~120 行，参考 `ScopeGuardSubstage`）
- `precision_debug_tree.py`：在 children 列表 + transition_table 中插入 bounds_check
- `skill_config.py`：注册新 skill 到 `STAGE_SKILL_MAP`

### 方案 B：作为 diagnose agent 的内置工具

bounds-check 不作为独立 substage，而是由 diagnose agent 在 Gate1 阶段调用。

**优点**：改动最小，不需要新 substage/skill/agent

**缺点**：
- 边界模糊：bounds-check 的结果混在 diagnose 的 candidate_pool 中，无法独立追踪
- 职责混淆：diagnose agent 的 prompt 已经很长，再加 bounds-check 流程会进一步膨胀
- 不可独立路由：无法跳过 diagnose 直接进入 fix（浪费 LLM token）

### 方案 C：作为 diagnose 的前置脚本（框架直接调用）

在 `DiagnoseSubstage.actions()` 中，先同步运行 Python bounds-check 脚本，将结果注入 agent prompt。

**优点**：不增加 substage 数量，结果直接给 LLM 消费

**缺点**：
- 违反 §2.7（workflow 与知识/数据分离）：框架直接执行业务逻辑
- 同步阻塞：Python 影子脚本需要生成 + 运行，可能耗时（shape 大时枚举量可观）
- 错误处理复杂：脚本失败时如何 fallback 到 LLM diagnose？

### 推荐：方案 A

理由：
1. **符合现有架构**：precision_debug 的每个 phase 就是一个 substage，bounds_check 是天然的一个 phase
2. **职责正交**：bounds_check 做 LLM 做不好的事（全枚举地址检查），diagnose 做 bounds_check 做不了的事（API 约束、同步检查、因果推理）
3. **可独立演进**：skill 按 §2.1 即插即用，agent manifest 独立配置
4. **可跳过**：当 C++ 代码不完整（编译都过不了）时，bounds_check 也跑不了，此时框架可按现有路径直接进 diagnose

## 四、BoundsCheckSubstage 设计

### 4.1 在 pipeline 中的位置 + 修复路径

```
run_tests ─── failed_case_queue[{case_id, shape, ...}] ───┐
                                                           │
scope_guard (pass) → bounds_check ← 取当前用例 shape ──────┘
                         ├── fixed → run_tests（全量回归确认）
                         ├── fix_failed → diagnose（fallback，LLM 可能有不同视角）
                         └── not_found → diagnose（正常 LLM 流程）
```

**shape 来源**：run_tests 在 `failed_case_queue` 的每个条目中记录用例的 shape 参数（如 `S=128, B=256, H=64`）。bounds_check 只读当前用例的 shape，计算一次 tiling，然后对该 shape 下所有 blockIdx × sOuterIdx 做全枚举。

### 4.1a 关键设计决策：bounds_check 直接修复 vs 经 fix agent

**两种 fix_plan 的根本差异**：

| 维度 | diagnose 的 fix_plan | bounds_check 的 finding |
|------|---------------------|------------------------|
| 性质 | 语义推测（"可能缺 guard"） | 确定性的（"s_row=7 越界 S=7"） |
| 定位精度 | 函数级 | 行号 + 越界数值 |
| 修复方式 | 需要 LLM 理解上下文后实现 | 机械的——加 guard 或修正 offset 公式 |
| 不确定性 | 高（LLM 可能修错） | 极低（公式已经算好了边界值） |

**结论：bounds_check 应直接修复，不经过 fix agent。**

理由：

1. **LLM 解释确定性 finding 是引入误差的**。bounds_check 的 Python 影子已经精确算出了越界位置和边界值（"line 235, s_row=7, S=7"），让另一个 LLM agent 重新理解这段描述再去修代码——中间多了一层语义转换，反而可能修错位置或方式。

2. **修复是机械的**。越界修复只有几种模板：加 `if (s_row < S_)` 守卫、修正 offset 公式的因子。不需要 LLM 推理。

3. **省一轮 agent spawn + token**。fix agent 对 bounds_check 来源的 plan 没有任何增值。

4. **修复失败不回退到 fix 循环**。如果 bounds_check 的机械修复编译不过或重检查仍越界 → `fix_failed → diagnose`（让 LLM 从不同视角分析，可能是 bounds_check 误判或需要更复杂的修复）。而不应该在同一个确定性 finding 上反复尝试。

### 4.1b 验证策略：重跑 Python 影子，不用单用例测

**问题**：用单用例测试验证 bounds fix 不可靠。算子可能同时存在越界 bug + 同步 bug（或其他 bug），即使越界修复正确，单用例仍然跑不通（同步 bug 未修）→ 假阴性。

**方案**：bounds_check 验证自己的修复用**自身工具**：

```
修复后 → 重跑 Python 影子（同 shape、同 blockIdx 枚举）
    ├── 目标 finding 消失 → 修复成功 → commit → fixed → run_tests
    └── 目标 finding 仍然存在 → 修复失败 → rollback → fix_failed → diagnose
```

| 验证方式 | 验证什么 | 优点 | 缺点 |
|---------|---------|------|------|
| 单用例 test | kernel 整体正确性 | 全面 | 被无关 bug 污染，假阴性高 |
| 重跑 Python 影子 | 越界/对齐是否消失 | 不受无关 bug 影响，确定性 | 只验证 bounds，不验证 kernel 功能 |

bounds_check 的职责是越界/对齐——用影子重跑验证这个就够了。kernel 整体正确性由 run_tests 全量回归兜底。

**bounds_check 的修复职责**：
- ✅ 机械修复 → 重跑影子验证 → commit → **编译装包（redeploy）** → fixed → run_tests 全量回归
- ✅ 修复失败 → rollback → 记录 finding 细节 → fallthrough 到 diagnose
- ❌ 不跑单用例 test（被无关 bug 污染）
- ✅ 每 finding 最多 2 次尝试（第一次失败换修复方式，两次都失败才退给 diagnose）
- ❌ 不做 printf 二分（越界 bug 不是数值发散）

### 4.2 transition_table 新增条目

```python
"bounds_check": {
    "fixed": ("run_tests", "corrective"),         # 机械修复 + 单用例验证通过 → 全量回归
    "fix_failed": ("diagnose", "default"),         # 修复失败 → fallback 到 LLM diagnose
    "not_found": ("diagnose", "default"),          # 无 CRITICAL → 正常流程
    "agent_aborted": ("bounds_check", "corrective"),
    "abort_exhausted": ("__escalate__:exhausted", "validation"),  # 持久 abort → halt
},
```

**注意**：`fixed` 和 `fix_failed` 都不经过 fix agent。bounds_check 对确定性 finding 自己完成修复+验证闭环。

### 4.3 control.json 新增字段

```python
# _CONTROL_REQUIRED_KEYS 新增：
"bounds_check_done": False,       # bool: 本轮是否已完成 bounds_check
"bounds_check_result": None,      # dict | None: {critical_count, fixed_count, fix_failed_count, findings_summary}
```

### 4.4 bounds_check 的修复产物（不写入 candidate_pool）

bounds_check **不写 control.json.candidate_pool**。它的修复闭环完全在自身 phase 内完成：

1. 对每个 CRITICAL finding，agent 生成代码 edit → 应用 → 重跑 Python 影子验证
2. 目标 finding 消失则 commit，仍存在则 rollback
3. transition 从 `_summary` 读取 `fixed_count / fix_failed_count`，决定路由

只有 fallthrough 到 diagnose 时（`fix_failed` 或 `not_found`），diagnose 才按原有逻辑生成 candidate_pool。这避免了两种不同性质的修复混在同一个 candidate_pool 中互相干扰。

### 4.6 skill 改造要点

原始 `ascendc-bounds-check/SKILL.md` 需要改造的项：

| 原始内容 | 改造后 | 原因 |
|---------|--------|------|
| "调 ascend-hardware 获取硬件参数" | 从 control.json / agent context 读取 chip 信息 | agent context 已有 `design_target_chip` |
| "若无需 NPU 环境，读取 chip JSON" | 始终从 context 取（框架保证传入） | 框架已有 chip 信息 |
| 产物路径 `<算子路径>/bounds_check.py` | `<debug_artifacts_dir>/phases/bounds_check/bounds_check.py` | 统一到 debug artifacts |
| 独立 CLI 模式 | 作为 agent 子流程 | 集成到 precision_debug 文件接力 |

**保留不变的部分**：
- 6 条 transform-rules（核心方法，独立于框架）
- Step 2-5 的检查逻辑（GM_OOB / UB_OOB / ALIGN_32B / UB 总量）
- 全枚举不采样原则
- 表达式不简化原则
- C++ 守卫逐条对照原则

### 4.7 agent 设计

```markdown
---
name: ascendc-precision-bounds-check
description: precision_debug 闭环 bounds_check phase —— Python 影子离线检查 GM/UB 越界与对齐，并机械修复
skills:
  - ascendc-precision-bounds-check
tools: Read, Write, Edit, Bash, Glob, Grep
model: haiku
---

一、静态检查：
对当前用例的 kernel + tiling C++ 源码构建 Python 影子，
全枚举 blockIdx × sOuterIdx，检查 GM_OOB / UB_OOB / ALIGN_32B / UB 总量。

二、机械修复（CRITICAL finding 命中时）：
对每个 CRITICAL finding，按 finding 类型执行模板化修复：
- GM_OOB / UB_OOB → 在越界访问前插入行/元素守卫（if 条件使用 Python 影子算出的边界值）
- ALIGN_32B → 修正 offset 公式使 ub_off * dtype_size 对齐到 32B
- UB_TOTAL → 减小 InitBuffer 的块大小参数
修复后 **重跑 Python 影子**（同 shape、同枚举）验证目标 finding 是否消失：
- 消失 → commit → fixed
- 仍存在 → rollback → fix_failed
**不跑单用例 test**（可能被无关 bug 污染，产生假阴性）。

三、输出：
RESULT: BONDS_CHECK_FIXED / BOUNDS_CHECK_FIX_FAILED / BOUNDS_CHECK_CLEAN / BOUNDS_CHECK_ERROR
```

**model 选 haiku** 的理由：核心检查逻辑是确定性 Python 执行；修复是模板化的机械 edit。不需要深度推理。

### 4.8 phase JSON schema（`precision_bounds_check.json`）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["findings", "shadow_script_path", "ub_budget_analysis", "_summary"],
  "properties": {
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["severity", "check_type", "location", "detail"],
        "properties": {
          "severity": {"enum": ["CRITICAL", "WARNING", "INFO"]},
          "check_type": {"enum": ["GM_OOB", "UB_OOB", "ALIGN_32B", "UB_TOTAL", "MISSING_GUARD"]},
          "location": {"type": "string"},
          "detail": {"type": "string"},
          "fix_plan_generated": {"type": "boolean"}
        }
      }
    },
    "shadow_script_path": {"type": "string"},
    "ub_budget_analysis": {
      "type": "object",
      "properties": {
        "tiling_formula_total": {"type": "integer"},
        "init_actual_total": {"type": "integer"},
        "hw_ub_size": {"type": "integer"},
        "gap": {"type": "integer"}
      }
    },
    "fixes": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "finding_index": {"type": "integer"},
          "file": {"type": "string"},
          "line": {"type": "integer"},
          "fix_type": {"enum": ["add_guard", "fix_offset", "reduce_buffer"]},
          "patch_applied": {"type": "boolean"},
          "verify_passed": {"type": "boolean"},
          "commit_sha": {"type": "string"}
        }
      }
    },
    "_summary": {
      "type": "object",
      "required": ["critical_count", "warning_count", "fixed_count", "fix_failed_count"],
      "properties": {
        "critical_count": {"type": "integer"},
        "warning_count": {"type": "integer"},
        "fixed_count": {"type": "integer"},
        "fix_failed_count": {"type": "integer"},
        "shadow_script_valid": {"type": "boolean"},
        "error": {"type": "string"}
      }
    }
  }
}
```

## 五、实现步骤

### Step 1: 创建 skill 目录与文件

```
.claude/skills/ascendc-precision-bounds-check/
├── SKILL.md                    # 改造自 ascendc-bounds-check/SKILL.md
├── references/
│   └── transform-rules.md      # 直接从 ascendc-bounds-check 复制
├── schema/
│   └── precision_bounds_check.json
└── scripts/
    └── run_bounds_check.py     # 新增：影子生成→运行→报告
```

### Step 2: 创建 agent manifest

```
.claude/agents/ascendc-precision-bounds-check.md
```

### Step 3: 在 substages 中新增 BoundsCheckSubstage

在 `precision_debug_substages.py` 中新增类，参照 `ScopeGuardSubstage` 的模式：
- `name = "bounds_check"`
- `agent_name = "ascendc-precision-bounds-check"`
- `_schema_files = ["precision_bounds_check.json"]`
- `_phase_prompt()` — 传递 control_path / phase_json_path / operator_dir / skill_dir 等
- `transition()` — 读 findings → 生成 fix_plan 入池 → 设置 bounds_check_result
- `resolve_condition()` — CRITICAL>0 → found_critical，否则 not_found

### Step 4: 修改 precision_debug_tree.py

- 在 children 列表中，BoundsCheckSubstage 插入在 ScopeGuardSubstage 之后、DiagnoseSubstage 之前
- transition_table 新增 `bounds_check` 条目
- scope_guard 的 `pass` 条件改为路由到 `bounds_check`（原来是直接到 diagnose）

### Step 5: 修改 skill_config.py

注册 `ascendc-precision-bounds-check` 到 STAGE_SKILL_MAP。

### Step 6: 测试

- UT：`BoundsCheckSubstage` 的 transition/resolve_condition 逻辑（mock control.json）
- ST：真实 bounds-check 在已知有越界 bug 的算子上运行，验证 CRITICAL 被检测到

## 六、边界情况与风险

### 6.1 C++ 代码不可解析

算子编译失败时，kernel 源码可能语法不完整 → Python 影子构建失败。

**处理**：`_summary.error` 记录失败原因，`shadow_script_valid=false`，resolve_condition → `not_found`（不阻塞，正常进 diagnose）。

### 6.2 blockIdx 枚举量

一个 shape 下的枚举量 = `blockDim × ubLoopNumS`。在极端 shape（如大 S 导致大 blockDim 或大 ubLoopNumS）下可能达到 10^4–10^5 级检查点。

**处理**：
- 10^5 级 Python 循环通常 <1s，不需要采样
- 真正的瓶颈是 Python 影子脚本的生成（agent 读码→写脚本），不是运行
- 若单 shape 枚举量确实超过 10^6 → 采样 + warn，但末核（blockIdx=blockDim-1）的尾块必须全量（越界高发区）

### 6.3 与 diagnose 的 candidate_pool 合并

bounds_check 和 diagnose 都写 candidate_pool → 需要确保不互相覆盖。

**处理**：遵循现有 contract — 写 control.json 时必须 `json.load → 修改 candidate_pool → json.dump`（保留其他字段），与 diagnose 的写入纪律一致。

### 6.4 A5 Regbase 兼容性

A5 走 `_build_precision_debug_group_a5()`（init_baseline → pipeline_sync → dump_debug → vf_test → finalize），这是一个完全不同的流水线。

**处理**：bounds_check 仅集成到 A3 Membase 流水线。A5 的 regbase 模型有独立的内存模型（regbase 不直接操作 UB/GM offset），越界检查的适用性待评估。

## 七、不做的集成方式

### 7.1 不做：作为 DiagnoseSubstage 的子步骤

理由见方案 B 的缺点分析。核心论据：bounds_check 是确定性计算、不依赖 LLM 推理；把它塞进 LLM agent 的 prompt 是浪费 token。

### 7.2 不做：作为 RunTestsSubstage 的预检

bounds_check 需要 kernel 源码，而 run_tests 阶段 kernel 可能尚未编译通过。放在 scope_guard 之后、diagnose 之前是最佳时机——此时已知失败在本阶段职责内，但尚未投入 LLM token。

### 7.3 不做：替换 diagnose

bounds_check 只覆盖地址计算类 bug（GM_OOB / UB_OOB / ALIGN_32B / UB_TOTAL），不覆盖：
- API 使用错误（dtype 不匹配、参数越界但 offset 正确）
- 同步缺失导致的数值发散
- 逻辑错误（用错公式、漏算因子）

这些仍是 diagnose 的职责。两者是互补关系。

## 八、总结

| 维度 | 结论 |
|------|------|
| **是否应该集成** | ✅ 是。bounds-check 填补 diagnose 的盲区（确定性地址计算检查） |
| **集成方式** | 方案 A：独立 substage，scope_guard→bounds_check→(diagnose)，bounds_check 自己修复 |
| **修复路径** | bounds_check 机械修复 → run_tests 全量回归；不经过 fix agent |
| **优先级** | 中。不阻塞现有流程，但能显著减少 address-bug 类问题的迭代次数 |
| **新建文件** | skill(4 文件) + agent(1 文件) + schema(1 文件) + 脚本(1 文件) |
| **修改文件** | precision_debug_substages.py + precision_debug_tree.py + skill_config.py |
| **预估代码量** | ~150 行（BoundsCheckSubstage）+ ~30 行（tree 改动）+ Python 影子脚本 ~200 行 |
| **风险** | 低。放在 diagnose 之前，失败时 fallback 到 diagnose（graceful degradation） |
| **A5 兼容** | 仅 A3 Membase，A5 Regbase 待评估 |
