# Precision Debug 分析方法论指南

> 文档版本：v2.0（A5 新流程适配版）  
> 适用范围：AscendC-DevKit A3/A5 算子精度调试  
> 目标读者：参与算子精度调试的 Agent / 开发者
> 
> **A5 适配说明**：本文档同时覆盖 A3 既有流程与 A5 新流程。A5 新流程为 `baseline → kernel_debug → vf_test / vector_error_debug / op_plugin_debug → regression`（见 `docs/stages/precision-debug-a5.md` 与 `docs/plan/a5-precision-refactor/02-analysis.md`）。原 A5 阶段 `pipeline_sync`、`dump_debug`、`finalize` 已删除，对应职责已拆分/迁移到 `baseline` / `kernel_debug` / `regression`。

---

## 1. 概述

算子精度调试涉及多个层面：tiling 分块策略、kernel 计算实现、精度本身、硬件异常（vector_error）、运行时框架（op_plugin / aclnn）以及流水同步。不同层面的问题需要不同的分析方法和工具。

本文档给出六类问题的分析方法论：

| 问题层面 | 典型症状 | A3 主要分析阶段 | A5 新流程主要分析阶段 |
|---|---|---|---|
| **tiling 侧** | UB 越界、对齐错误、UB 总量超限、shape 切分不均 | `bounds_check`、`diagnose` | `kernel_debug`（内嵌轻量 `tiling_bounds_check` 辅助脚本） |
| **kernel 侧** | 计算逻辑错误、API 误用、地址偏移错误、同步缺失 | `diagnose`、`fix`、`printf_location`、`comment_bisect` | `kernel_debug`（`ascendc-sync-static-check` + DumpTensor 二分） |
| **精度问题** | 输出与 golden 有 diff、特定 dtype/shape 失败 | `diagnose` Gate1/Gate2、`printf_location` | `kernel_debug`（误差分类 + DumpTensor 二分） |
| **vector_error** | A5 RegBase device exception、PC 异常、fault address | A3 不涉及 | `vector_error_debug`（由 `baseline`/`kernel_debug`/`vf_test`/`regression` 触发） |
| **op_plugin 问题** | aclnn 错误码 161xxx / 561xxx、算子注册失败、适配层引入额外 diff | `scope_guard`、`ascendc-runtime-debug` | `op_plugin_debug`（双跑交叉对比隔离，尝试修复适配层） |
| **流水问题** | 卡死、hang、double buffer 时序异常、MTE2/VF/MTE3 违例 | `ascendc-sync-*` | `kernel_debug` 内调用 `ascendc-sync-static-check`（`pipeline_sync` 已删除） |

> A5 新流程删除 `pipeline_sync` 阶段，且不切换 double buffer。因此 A5 的流水同步问题主要通过静态同步检查（`ascendc-sync-static-check`）和 DumpTensor 中间态推断来定位，不再使用 camodel trace 或单/双 buffer 切换实验。

---

## 2. tiling 侧分析

### 2.1 分析目标

tiling 侧负责把算子输入 shape 切分到多个核（block）和每个核内的多个 tile，并决定 UB buffer 大小、GM offset 计算等。tiling 错误通常表现为：

- UB_OOB：某个 tile 访问超出分配的 UB buffer
- ALIGN_32B：UB/LocalTensor 操作地址未 32B 对齐
- UB_TOTAL：tiling 估算的 UB 总量超过硬件 UB 大小
- 尾块处理错误：末核或末 tile 的计算边界没处理好

### 2.2 信息收集

需要收集以下信息：

| 信息 | 来源 |
|---|---|
| 失败用例 shape / dtype | `control.json.failed_case_queue[current_case_index]` |
| tiling 源码 | `op_host/*_tiling.cpp` |
| kernel 源码 | `op_kernel/*.h`、`op_kernel/*.cpp` |
| UB 大小等硬件参数 | `ascend-hardware` skill 或 agent context |
| InitBuffer 顺序和参数 | kernel 中 `pipe.InitBuffer(...)` |
| TilingData 字段 | tiling 结构体定义 |

### 2.3 常见 tiling 问题

| 问题 | 根因 | 典型修复 |
|---|---|---|
| `CalcUbRequirement` 漏算对齐 | tiling 用 `n * H * dtypeSize` 计算，未按 32B 对齐 | 改为 `AlignUp(n * H * dtypeSize, 32)` |
| `ubFactorB/S` 过大 | 单核 tile 太大，per-block UB 需求超硬件 | 在 `PickUbFactor` 中调小 factor 或加上限 |
| 尾块边界错误 | 末核 `blockFactorB` 取整后 `actualBlockFactorB` 计算错误 | 修正尾块公式，或 kernel 加守卫 |
| tiling 参数传到 kernel 后偏移公式错误 | kernel 用错 tiling 字段 | 核对 TilingData 字段名和语义 |
| UB buffer 起始地址不对齐 | `InitBuffer` 的 size 或 offset 未对齐 | 修正 tiling 对齐公式 |

### 2.4 分析步骤

#### Step 1：构建 Python 影子

把 tiling 和 kernel 的**标量地址计算**翻译成 Python：

1. 工具函数平移：`CeilDiv`、`CeilAlign`、`AlignUpKernel` → Python 版本；
2. struct/class → `@dataclass`，字段名 `camelCase_` → `snake_case`；
3. 控制流逐句复制，保留分支结构；
4. `GetBlockIdx()` → 枚举 `blockIdx ∈ [0, blockDim)`；
5. 地址公式原样保留，不合并化简。

#### Step 2：构建 UB buffer 映射

按 kernel 中 `InitBuffer` 出现顺序构建 `_buffer_map`：

```python
_buffer_map: dict[str, tuple[int, int]] = {}  # name -> (start_byte, capacity_byte)
_next_free = 0

# TBuf: InitBuffer(buf, size)
_buffer_map["bufA"] = (_next_free, size)
_next_free += size

# TQue: InitBuffer(que, N, block_size)
_buffer_map["queB"] = (_next_free, N * block_size)
_next_free += N * block_size
```

#### Step 3：枚举检查

对给定 shape 枚举 `blockIdx × sOuterIdx`，在每个访问点检查：

```python
# UB_OOB
if ub_off + access_len > buffer_capacity:
    CRITICAL("UB_OOB", buf_name, ub_off, access_len, capacity)

# ALIGN_32B（仅 UB/LocalTensor 操作）
if (ub_off * dtype_size) % 32 != 0:
    CRITICAL("ALIGN_32B", buf_name, ub_off, dtype_size)

# UB_TOTAL
if sum(buffer_sizes) > hw.ub_size:
    CRITICAL("UB_TOTAL", total_size, hw.ub_size)
```

> GM_OOB 暂不启用，因为 GM 地址通常由框架保证。

#### Step 4：修复与验证

修复优先级：**tiling 侧优先，kernel 侧后备**。

| finding | 第一优先 | 第二优先 | kernel 后备 |
|---|---|---|---|
| UB_TOTAL | 调小 `ubFactorB/S` | 修复 `CalcUbRequirement` 对齐公式 | 删 dead buffer / 缩 buffer |
| UB_OOB | 修正 offset / tiling 参数 | 插入 offset 守卫 | — |
| ALIGN_32B | 修正 offset 公式 | 修复 tiling 对齐公式 | — |

修复后用 Python 影子重跑验证，最多 3 轮迭代。

### 2.5 关键原则

- **不模拟数据，只追踪地址**：忽略 Mul/Add/Cast/Duplicate/EnQue/DeQue 等纯数据/同步操作。
- **表达式不简化**：保持 C++ 原始形式以便 1:1 对照。
- **末核尾块必须枚举**：block 0 正常不代表 block N-1 安全。
- **tiling 公式 vs 实际分配对比**：`CalcUbRequirement` 必须和 `InitBuffer` 实际总和对齐。

### 2.7 A5 新流程下的定位路径

A5 的 `kernel_debug` 阶段在分析当前 case 时，首先调用轻量 `tiling_bounds_check` 脚本：

1. 从 `checkpoint.json` 读取当前 case 的 shape / dtype / TilingData；
2. 按 `kernel_debug` 阶段扫描 `op_host/*_tiling.cpp` 和 `op_kernel/*.cpp` 中 `InitBuffer` 顺序，构建 UB buffer 映射；
3. 枚举当前 case 的 `blockIdx` 和 tile 索引，检查 UB_OOB / ALIGN_32B / UB_TOTAL / 尾块边界；
4. 输出可疑项列表，作为 LLM 分析失败模式和 DumpTensor 插点位置的辅助输入。

> 与 A3 `bounds_check` 的差异：A5 不枚举所有 case，只检查当前 case；不追踪 GM 地址；不自动修复 tiling 公式，只输出可疑提示。完整 Python shadow 能力作为后续增强项。



### 2.8 对应 Skill / Agent

| 角色 | 名称 | 位置 | 适用流程 |
|---|---|---|---|
| **Agent** | `ascendc-precision-bounds-check` | `.claude/agents/ascendc-precision-bounds-check.md` | A3 |
| **Skill** | `ascendc-precision-bounds-check` | `.claude/skills/ascendc-precision-bounds-check/SKILL.md` | A3 |
| **改造规则参考** | `transform-rules.md` | `.claude/skills/ascendc-precision-bounds-check/references/transform-rules.md` | A3 |
| **Schema** | `precision_bounds_check.json` | `.claude/skills/ascendc-precision-bounds-check/schema/precision_bounds_check.json` | A3 |
| **A5 轻量 tiling 检查脚本** | `tiling_bounds_check.py` | `src/ascendc_devkit/orchestration/stages/precision_debug_a5/scripts/` | A5（待实现） |

> tiling 侧问题在 A3 中由 `bounds_check` 阶段处理；**A5 新流程中由 `kernel_debug` 阶段内嵌的 `tiling_bounds_check` 轻量脚本辅助分析**。完整 Python shadow 能力作为后续增强项（见 `docs/plan/a5-precision-refactor/03-solutions.md` §3.1）。

---

## 3. kernel 侧分析

### 3.1 分析目标

kernel 侧负责实际计算。kernel 错误通常表现为：

- 计算结果与 golden 有 diff
- 特定 API 调用导致 crash
- 地址偏移计算错误
- 同步缺失导致数据竞争
- dtype 转换错误

### 3.2 信息收集

| 信息 | 来源 |
|---|---|
| 失败用例 | `failed_case_queue` |
| kernel 源码 | `op_kernel/` |
| 编译/运行日志 | `precision_run_tests.json.last_run_log` |
| golden 结果 | `precision_run_tests.json.last_result_json` |
| 参考算子 | sibling 目录中的同类型算子 |

### 3.3 常见 kernel 问题

| 问题 | 根因 | 修复方向 |
|---|---|---|
| 计算 diff | Cast RoundMode 错误、Reduce 精度不足、除零保护缺失 | 改 API 参数、加 guard、换高精度中间计算 |
| 地址偏移错误 | offset 公式写错、单位混淆（字节 vs 元素） | 修正 offset 公式 |
| dtype 误用 | `float` 当 `int32` 存取、half 累加溢出 | 修正数据类型处理 |
| 同步缺失 | SetFlag/WaitFlag/PipeBarrier 缺失或顺序错误 | 补同步、调整事件依赖 |
| UB 32B 对齐违规 | DataCopy/DataCopyPad 起始地址未对齐 | 加 padding 或调整 offset |
| API 误用 | API 不存在、dtype 不支持、参数顺序错误 | 查 `ascendc-dev-knowledge` 修正 |

### 3.4 分析步骤

#### Step 1：症状定位

读 `result.json` 和 `run.log`：

- 失败是 `precision` / `runtime` / `compilation` 哪一种？
- `max_diff_location` 指向哪个 tile / 哪个输出位置？
- 是否特定 dtype / shape / block 才失败？

#### Step 2：静态扫描（Gate1 + Gate2）

**Gate1：按症状关键词匹配常见陷阱**

读 `references/gates/static-check/` 中的 symptom-table、common-traps、case-studies，审查：

- Cast RoundMode（`CAST_RND`、`CAST_TRUNC` 等）
- Reduce 精度（`Add` 累加顺序、half 累加溢出）
- 除零保护（`Div` / `Reciprocal` / `Sqrt` 输入校验）
- dtype 降级（FP32 中间结果存成 FP16）
- 硬件约束（VEC 32B 对齐、UB 容量）

**Gate2：同步检查**

调用 `ascendc-sync-static-check` skill，扫描：

- EnQue/DeQue 配对
- 手动 SetFlag/WaitFlag 配对
- MTE2/MTE3 地址重叠
- PipeBarrier 使用
- Mutex/TBuf 同步
- Scalar 流水

#### Step 3：动态定位

如果静态扫描无法定位，使用动态方法：

**A3 精度问题 → printf 二分**

1. 把算子公式拆成 `formula_steps`；
2. 在 CopyIn 后、前处理后、主计算后、后处理后、CopyOut 前插入批量边界探针；
3. 单次编译 + 上板跑单用例；
4. 对比 CPU golden shadow，定位首个发散阶段；
5. 在发散阶段内做细粒度二分，直到定位到具体 API；
6. 查 `ascendc-dev-knowledge` 确认 API 用法后修复。

**A5 精度问题 → DumpTensor 二分（在 `kernel_debug` 阶段）**

A5 新流程不依赖 printf，而是使用 KernelLaunch 直测 + DumpTensor 看完整 tensor 中间态：

1. 读 `baseline/baseline_result.json` 中当前 case 的 KernelLaunch 失败上下文；
2. 计算误差分类字段（`error_pattern`：systematic / localized / random / huge / dtype_specific）；
3. 按 `error_pattern` 决定 DumpTensor 插点策略：
   - `systematic`：优先检查 CopyIn 后的数据转换和首个计算 API；
   - `localized`：优先定位 `max_diff_location` 所在的 tile / block；
   - `random`：优先检查同步缺失和未初始化 UB（结合 `ascendc-sync-static-check`）；
   - `huge`：优先检查 Inf/NaN、除零、索引越界；
   - `dtype_specific`：优先检查 Cast / 量化 / FP16 累加；
4. 在 CopyIn（desc 100-199）、非 `__simd_vf__` 计算（desc 200-299）、CopyOut（desc 300-399）插入 DumpTensor；
5. 用 KernelLaunch 跑当前 case，捕获完整中间 tensor；
6. 对比 CPU golden 分阶段定位首个发散阶段；
7. 在发散阶段内二分，直到定位到具体 API 或语句；
8. 查 `ascendc-dev-knowledge` 确认 API 用法后修复；
9. 用 KernelLaunch 回验当前 case 中间态正确，标 `fixed`。

**runtime crash → 注释二分（A3）**

1. 优先消融 `DataCopy` / `DataCopyPad` / `TQue` 调用点（参数降级，**禁止裸注释**）；
2. 不命中则做区域二分（CopyIn / Compute / CopyOut）；
3. 行级确认锁定触发行；
4. 生成 `fix_plan` 回到 `fix` 阶段验证。

**VECTOR_ERROR crash（A5）→ `vector_error_debug`**

1. 由 `baseline` / `kernel_debug` / `vf_test` / `regression` 任一阶段返回 `error_type=VECTOR_ERROR` 触发；
2. 使用 P1 静态风险扫描 + P2 Top-K 安全消融 + P3 区域二分/行级确认；
3. 修复后用同一 case 的 KernelLaunch 回验，错误签名消失。

### 3.5 修复验证

- 修改后用 `test_command --case <case_id>` 跑单用例验证；
- 通过则 `git commit`，标 `resolved_pending`；
- 失败则 `git checkout` 回滚，标 `refuted`。

### 3.6 对应 Skill / Agent

| 角色 | 名称 | 位置 | 适用流程 |
|---|---|---|---|
| ** diagnose Agent** | `ascendc-precision-diagnose` | `.claude/agents/ascendc-precision-diagnose.md` | A3 |
| ** diagnose Skill** | `ascendc-precision-diagnose` | `.claude/skills/ascendc-precision-diagnose/SKILL.md` | A3 |
| ** fix Agent** | `ascendc-precision-fix` | `.claude/agents/ascendc-precision-fix.md` | A3 |
| ** fix Skill** | `ascendc-precision-fix` | `.claude/skills/ascendc-precision-fix/SKILL.md` | A3 |
| ** printf 二分 Agent** | `ascendc-precision-printf-locate` | `.claude/agents/ascendc-precision-printf-locate.md` | A3 |
| ** printf Skill** | `ascendc-precision-printf` | `.claude/skills/ascendc-precision-printf/SKILL.md` | A3 |
| ** 注释二分 Agent** | `ascendc-precision-comment-bisect` | `.claude/agents/ascendc-precision-comment-bisect.md` | A3 |
| ** 注释二分 Skill** | `ascendc-precision-comment-bisect` | `.claude/skills/ascendc-precision-comment-bisect/SKILL.md` | A3 |
| ** API 查询** | `ascendc-dev-knowledge` | `.claude/skills/ascendc-dev-knowledge/SKILL.md` | A3/A5 |
| ** 同步静态检查** | `ascendc-sync-static-check` | `.claude/skills/ascendc-sync-static-check/SKILL.md` | A3/A5 |
| ** diagnose Schema** | `precision_diagnose.json` | `.claude/skills/ascendc-precision-diagnose/schema/` | A3 |
| ** fix Schema** | `precision_fix.json` | `.claude/skills/ascendc-precision-fix/schema/` | A3 |
| ** A5 kernel debug Agent** | `ascendc-precision-kernel-debug` | `.claude/agents/ascendc-precision-kernel-debug.md` | A5（待创建） |
| ** A5 kernel debug Skill** | `ascendc-precision-kernel-debug` | `.claude/skills/ascendc-precision-kernel-debug/SKILL.md` | A5（待创建） |
| ** A5 vector error debug Agent** | `ascendc-precision-vector-error-debug` | `.claude/agents/ascendc-precision-vector-error-debug.md` | A5 |
| ** A5 vector error debug Skill** | `ascendc-precision-vector-error-debug` | `.claude/skills/ascendc-precision-vector-error-debug/SKILL.md` | A5 |

> kernel 侧问题贯穿 A3 precision_debug 的 `diagnose → fix → printf_location / comment_bisect` 主循环；**A5 新流程中由 `kernel_debug` 阶段统一承担 diagnose + fix + DumpTensor 定位的职责**，并通过 `ascendc-sync-static-check` 填补同步扫描缺口。

---

## 4. 精度问题分析

### 4.1 精度失败分类

| 类型 | 特征 | 常见原因 |
|---|---|---|
| **系统误差** | 所有点 diff 相近 | Cast 截断、量化、FP16 精度不足 |
| **局部误差** | 特定位置 diff 大 | 边界处理、尾块、gather/scatter 索引错误 |
| **随机误差** | diff 不稳定 | 未初始化 UB、数据竞争、同步缺失 |
| **巨大误差** | diff 接近量级 | 除零、指数溢出、索引越界读错数据 |
| **特定 dtype** | FP32 过 FP16 败 | 半精度累加、中间结果截断 |

### 4.2 症状分析

用 numpy 对比 output vs golden：

```python
max_err = np.max(np.abs(output - golden))
mean_err = np.mean(np.abs(output - golden))
diff_sign = np.sign(output - golden)
# 误差聚集区域
err_hotspot = np.where(np.abs(output - golden) > threshold * max_err)
```

关注：

- `max_diff_location` 的精确多维坐标；
- 误差是否沿某个轴聚集（如特定 row/channel/tile）；
- 多 dtype 交叉验证：FP32 过 FP16 败 → 半精度精度不足方向。

### 4.3 Gate1 静态匹配

按 symptom 关键词检索静态检查知识库：

1. 从 `symptom-table.md` 查表；
2. 读 `common-traps.md` 确认具体 API 陷阱；
3. 读 `case-studies.md` 找相似历史 case；
4. 代码语义审查：Cast RoundMode、Reduce 精度、除零保护、dtype 降级、VEC 32B 对齐。

### 4.4 Gate2 同步检查

调用 `ascendc-sync-static-check`：

- 组装输入（kernel 路径、失败用例、问题症状）；
- 接收 JSON `{check_summary, findings, clean_areas}`；
- 高置信 finding 直接加入 `candidate_pool`；
- 低置信写入 `excluded_hypotheses`。

### 4.5 Gate3 动态二分

当 Gate1/Gate2 无法定位时：

**A3：printf 二分**

1. **批量边界探针**：按计算模式（GEMM / Element-wise / Reduce）在关键阶段边界插探针；
2. **单次编译 + 上板**：获取全阶段中间值；
3. **对比 golden shadow**：定位首个发散阶段；
4. **阶段内二分**：直到定位到具体 API 或语句；
5. **查 API 文档**：用 `ascendc-dev-knowledge` 确认 API 签名、dtype、约束；
6. **修复 + 单用例验证**。

**printf 注意事项：**

- 探针优先放循环外；
- 循环内探针必须加限流条件（如 `GetBlockIdx() == 0 && dSeg == 0 && _pi < 5`）；
- 修复后必须 `git checkout` 清理探针。

**A5：DumpTensor 二分（在 `kernel_debug` 阶段）**

A5 新流程不使用 printf，使用 KernelLaunch 直测 + DumpTensor 看完整 tensor 中间态：

1. 计算误差分类字段（`error_pattern`）作为 DumpTensor 插点策略输入；
2. 在 CopyIn（desc 100-199）、非 `__simd_vf__` 计算（desc 200-299）、CopyOut（desc 300-399）插入 DumpTensor；
3. 用 KernelLaunch 跑当前 case，捕获完整中间 tensor；
4. 对比 CPU golden 分阶段定位首个发散阶段；
5. 在发散阶段内二分，直到定位具体 API 或语句；
6. 修复后用 KernelLaunch 回验当前 case 中间态正确，标 `fixed`。

> A5 的 DumpTensor 优势：看完整 tensor 而非单个标量；约束：不得在 `__simd_vf__` 函数体内插探针或修改 VF 代码（VF 黑盒），定位到 VF 输出错误时标 `need_vf` 转 `vf_test`。

### 4.6 对应 Skill / Agent

| 角色 | 名称 | 位置 | 适用流程 |
|---|---|---|---|
| ** diagnose Agent** | `ascendc-precision-diagnose` | `.claude/agents/ascendc-precision-diagnose.md` | A3 |
| ** diagnose Skill** | `ascendc-precision-diagnose` | `.claude/skills/ascendc-precision-diagnose/SKILL.md` | A3 |
| ** printf 二分 Agent** | `ascendc-precision-printf-locate` | `.claude/agents/ascendc-precision-printf-locate.md` | A3 |
| ** printf Skill** | `ascendc-precision-printf` | `.claude/skills/ascendc-precision-printf/SKILL.md` | A3 |
| ** 同步检查 Skill** | `ascendc-sync-static-check` | `.claude/skills/ascendc-sync-static-check/SKILL.md` | A3/A5 |
| ** diagnose 静态检查参考** | `symptom-table.md` / `common-traps.md` / `case-studies.md` | `.claude/skills/ascendc-precision-diagnose/references/gates/static-check/` | A3 |
| ** A5 kernel debug Agent** | `ascendc-precision-kernel-debug` | `.claude/agents/ascendc-precision-kernel-debug.md` | A5（待创建） |
| ** A5 kernel debug Skill** | `ascendc-precision-kernel-debug` | `.claude/skills/ascendc-precision-kernel-debug/SKILL.md` | A5（待创建） |

> 精度问题主要走 A3 `diagnose` → `printf_location` 路径；**A5 新流程中由 `kernel_debug` 阶段通过 DumpTensor 二分替代 printf 二分**，同步导致的随机精度问题会由 `ascendc-sync-static-check` 辅助定位。

---

## 5. vector_error 问题分析（A5 RegBase）

### 5.1 什么是 VECTOR_ERROR

A5 RegBase 架构下，vector core 发生硬件异常（如非法地址、指令异常、寄存器访问违例）时会产生 VECTOR_ERROR。这类问题通常没有正常 printf 输出（kernel 死在 flush 前），也不能用普通 DumpTensor 分析。

### 5.2 触发场景

在 A5 `precision_debug` 的以下阶段返回 `VECTOR_ERROR` 时触发 `vector_error_debug`：

- `baseline`
- `kernel_debug`
- `vf_test`
- `regression`

> 旧 A5 阶段 `pipeline_sync` / `dump_debug` / `finalize` 已删除，对应触发场景由 `baseline` / `kernel_debug` / `regression` 承接。

### 5.3 证据归一化

从 Driver 获取归一化证据：

```json
{
  "case_id": "...",
  "error_code": "...",
  "kernel_name": "...",
  "pc": "...",
  "pc_offset": "...",
  "fault_va": "...",
  "exception_type": "...",
  "run_log": "...",
  "plog": "...",
  "tiling_key": "...",
  "buffer_mode": "single/double",
  "source_phase": "pipeline_sync"
}
```

证据质量分级：

| 级别 | 含义 |
|---|---|
| `pc_mapped` | 有 kernel 和 PC/PC offset |
| `runtime_identified` | 有 kernel 和 error code |
| `partial` | 只有 case 或 error code |
| `insufficient` | 缺少稳定标识 |

### 5.4 分析流程

#### Step 0：建立复现基线

1. 用当前源码 build；
2. 运行目标 case，确认能复现相同 VECTOR_ERROR；
3. 记录 error signature；
4. 若无法复现 → 返回 `not_reproduced`。

#### Step 1：A5 静态风险扫描

运行确定性扫描器 `scan_a5_vector_risks.py`，覆盖：

- `gm_ub_transport`：GM→UB 搬运对齐、长度、stride
- `ub_reg_load_store`：UB→register 加载/存储
- `mask_tail`：mask 处理、尾块
- `address_generation`：地址生成公式
- `layout_cast_dist`：数据排布转换
- `vf_call_abi`：VF 函数调用约定
- `incore_sync`：核内同步
- `queue_lifecycle`：TQue/TBuf 生命周期
- `crosscore_tscm`：核间 TSCM
- `tiling_boundary`：tiling 边界

#### Step 2：Top-K 定向安全消融

按静态扫描分数排序，对高风险区域做安全消融：

- 修改参数（如 blockLen 降级）而不是裸注释；
- 每次消融后 build + 跑目标 case；
- 判定信号：`same_error` / `error_disappeared` / `different_error` / `compile_fail`。

#### Step 3：区域二分与行级确认

若 Top-K 不命中：

1. 区域二分 CopyIn / Compute / CopyOut；
2. 在命中区域内逐行确认；
3. 多根因时记录 `located_roots`，下次进入跳过已定位区域。

#### Step 4：修复与回验

定位后修复，用同一 case 确认原错误签名消失。写 `vector_error_round_{round}_result.json`。

### 5.5 关键约束

- **不使用 printf**：VECTOR_ERROR kernel 可能无法刷新输出；
- **不改变 buffer 模式**：来源阶段是 single buffer 就保持 single，是 double 就保持 double；
- **不更新 checkpoint 路由字段**：只写本阶段 result JSON；
- **不运行全量用例**：只跑目标 case。

### 5.6 对应 Skill / Agent

| 角色 | 名称 | 位置 | 适用流程 |
|---|---|---|---|
| **Agent** | `ascendc-precision-vector-error-debug` | `.claude/agents/ascendc-precision-vector-error-debug.md` | A5 |
| **Skill** | `ascendc-precision-vector-error-debug` | `.claude/skills/ascendc-precision-vector-error-debug/SKILL.md` | A5 |
| **前置阶段** | `baseline` / `kernel_debug` / `vf_test` / `regression` | A5 `precision_debug_a5` 新流程 | A5 |
| **A5 静态扫描脚本** | `scan_a5_vector_risks.py` | `.claude/skills/ascendc-precision-vector-error-debug/scripts/`（由 skill 调用） | A5 |

> vector_error 是 A5 RegBase 专属问题，仅在 A5 `precision_debug` 流程中由 `vector_error_debug` 阶段处理。旧触发阶段 `pipeline_sync` / `dump_debug` / `finalize` 已删除，新触发阶段为 `baseline` / `kernel_debug` / `regression`。

---

## 6. op_plugin 问题分析

### 6.1 op_plugin 的作用

op_plugin 是 PyTorch Adapter（PTA）与自定义算子的接口层。问题通常出现在：

- 算子注册到 torch 失败
- OpAPI 签名与 kernel 不匹配
- dtype/shape 推导错误
- 环境变量或 opp 路径配置错误

### 6.2 常见错误码

| 错误码 | 含义 | 排查方向 |
|---|---|---|
| `161001` | 参数为 nullptr | 检查输入/输出指针、attr 是否为空 |
| `161002` | 参数非法 | 检查 dtype/shape 是否符合接口声明 |
| `561002` | Tiling 错误 | 检查 tiling 函数、`TilingKey` 路由 |
| `561003` | Kernel 查找失败 | 检查算子是否编译出包、opp 路径、vendor_name |
| `561107` | `ASCEND_OPP_PATH` 环境变量缺失 | 检查环境变量配置 |
| `561112` | 算子二进制包未加载 | 检查 `.so` 是否在 opp 目录、LD_LIBRARY_PATH |
| `561108~561119` | JSON 配置错误 | 检查 `op_info.json`、静态二进制 json 字段 |

### 6.3 排查步骤

#### Step 1：判断是否为 op_plugin 层问题（A3）

`scope_guard` 首轮会判定：若出现 `161xxx` / `561003` / `561112` / schema 不匹配 / 注册失败，归为 upstream 缺陷，halt precision_debug。

#### Step 1'：判断是否为 op_plugin 层问题（A5 新流程）

A5 `baseline` 阶段同时跑 `run-cases` 和 `KernelLaunch` 双工具，通过**交叉对比自动隔离**适配层问题：

- **run-cases 失败 + KernelLaunch 同 case 通过** → 问题在 `op_plugin` / `aclnn` 适配层（`error_layer=op_plugin`），路由到 `op_plugin_debug` 阶段尝试修复。
- **run-cases 失败 + KernelLaunch 同 case 失败** → 问题在 `kernel` / `tiling` 层（`error_layer=kernel`），路由到 `kernel_debug` 阶段。
- **run-cases 全 pass** → 精度交付通过，流程结束（不论 KernelLaunch 结果）。

#### Step 2：检查算子注册

```bash
# 检查 op-plugin 中是否有算子注册
find op-plugin -name "*.cpp" | xargs grep -n "npu_your_op"

# 检查 op_api 声明
find op_plugin/op_api -name "*.h" | xargs grep -n "your_op"

# 检查 meta 注册
find op_plugin/meta -name "*.cpp" | xargs grep -n "your_op"
```

#### Step 3：检查接口签名一致性

对比三层：

1. **kernel 侧**：`__global__ __aicore__` 函数参数、TilingData 字段；
2. **op_plugin 侧**：`npu_your_op` 的 C++ OpAPI 参数列表、dtype 支持；
3. **json 配置**：`op_info.json` 中的 `inputs`、`outputs`、`attrs`、dtype 列表。

#### Step 4：检查 opp 包与环境

```bash
# 环境变量
echo $ASCEND_OPP_PATH
echo $LD_LIBRARY_PATH

# opp 目录结构
ls $ASCEND_OPP_PATH/vendors/custom_ops/

# 算子 so 是否存在
find $ASCEND_OPP_PATH -name "*your_op*.so"
```

#### Step 5：解析 plog / 错误码

**A3**：`ascendc-runtime-debug` skill 会解析 plog 中的具体错误码和调用栈，定位是参数问题、tiling 问题还是 kernel 未找到。

**A5 新流程**：`op_plugin_debug` 阶段首先按错误码表解码 `run-cases` 返回的错误码（`161xxx` / `561xxx`），再按 `op_plugin-checklist.md` 逐项排查：

1. 注册宏是否齐全；
2. aclnn / C++ OpAPI 签名与 kernel 参数是否一致；
3. dtype 转换、shape reshape 是否正确；
4. attr 传递是否完整；
5. tiling 参数映射是否正确；
6. `op_info.json` 字段是否正确；
7. 环境变量 / opp 路径是否加载。

> 完整 plog 自动解析作为后续增强项（见 `docs/plan/a5-precision-refactor/03-solutions.md` §3.5）。当前阶段先给 LLM 提供错误码表和检查清单，由 LLM 主导定位。

#### Step 6：A5 修复与双跑收敛验证

`op_plugin_debug` 是**框架层修复循环**，不是 per-case 调试：

1. 读 `op_plugin` / `aclnn` 层代码（`{op_name}.cpp` / C++ OpAPI 实现 / aclnn 接口定义）；
2. 对比 KernelLaunch 传给 kernel 的参数 vs `op_plugin` 传给 kernel 的参数，找 dtype / shape / attr / tiling 差异；
3. 修改 `op_plugin` 代码 → `redeploy` 重编出包；
4. 双跑验证（`run-cases` + `KernelLaunch` 全量重跑）：
   - `run-cases` 不再报框架层错误；
   - `run-cases` 结果与 `KernelLaunch` 基本一致；
5. 满足上述两条 → `converged`，回 `baseline` 重新交叉对比；否则 `retry`（达 `max_op_plugin_rounds` 则 `exhausted`）。

### 6.4 修复方向

| 问题 | 修复 |
|---|---|
| 注册缺失 | 在 op-plugin 补充 `npu_xxx` 注册和 OpAPI 实现 |
| 签名不匹配 | 统一 kernel / op_api / json 三处的参数、dtype、attr |
| Tiling 错误 | 检查 `TilingKey` 路由和 `TilingFunc` 实现 |
| 环境未加载 | 配置 `ASCEND_OPP_PATH`、LD_LIBRARY_PATH、source set_env.bash |
| JSON 字段错误 | 修正 `op_info.json` 或静态二进制 json |
| 适配层 dtype/shape 转换错误（A5） | 修正 op_plugin C++ OpAPI 中的 dtype / reshape 逻辑 |
| 适配层 attr 传递缺失（A5） | 补全 aclnn 接口到 kernel 的 attr 透传 |
| 适配层 tiling 映射错误（A5） | 核对 aclnn 侧 tiling 参数类型与 kernel TilingData 字段 |

### 6.5 对应 Skill / Agent

| 角色 | 名称 | 位置 | 适用流程 |
|---|---|---|---|
| **scope guard Agent** | `ascendc-precision-scope-guard` | `.claude/agents/ascendc-precision-scope-guard.md` | A3 |
| **scope guard Skill** | `ascendc-precision-scope-guard` | `.claude/skills/ascendc-precision-scope-guard/SKILL.md` | A3 |
| **运行时调试 Skill** | `ascendc-runtime-debug` | `.claude/skills/ascendc-runtime-debug/SKILL.md` | A3（A5 部分复用其错误码表） |
| **错误码参考** | `error_codes.md` | `.claude/skills/ascendc-runtime-debug/references/error_codes.md` | A3/A5 |
| **调试流程参考** | `debug_workflow.md` | `.claude/skills/ascendc-runtime-debug/references/debug_workflow.md` | A3 |
| **PTA 集成 Skill** | `ascendc-pta` | `.claude/skills/ascendc-pta/SKILL.md` | A3/A5 |
| **A5 op_plugin debug Agent** | `ascendc-precision-op-plugin-debug` | `.claude/agents/ascendc-precision-op-plugin-debug.md` | A5（待创建） |
| **A5 op_plugin debug Skill** | `ascendc-precision-op-plugin-debug` | `.claude/skills/ascendc-precision-op-plugin-debug/SKILL.md` | A5（待创建） |

> op_plugin / aclnn 问题在 A3 中由 `scope_guard` 首轮判为 upstream 缺陷并 halt；**A5 新流程中由 `baseline` 双跑交叉对比自动隔离，并进入 `op_plugin_debug` 阶段尝试修复适配层**，而非直接 halt。

---

## 7. 流水问题分析

### 7.1 流水同步基础

AscendC 核内三条主要流水：

| 流水 | 职责 | 常见 API |
|---|---|---|
| MTE2 | GM → UB 搬运 | `DataCopy`、`DataCopyPad` |
| VF / VEC | 向量/标量计算 | `Add`、`Mul`、`Cast`、`Duplicate` |
| MTE3 | UB → GM 搬出 | `DataCopy`（UB→GM） |

双缓冲（double buffer）让两轮数据在流水上重叠，提升性能，但也可能掩盖同步 bug。调试流水问题时通常先**关闭 double buffer**。

### 7.2 常见流水问题

| 症状 | 可能原因 |
|---|---|
| 卡死 / hang | SetFlag/WaitFlag 不匹配、EnQue/DeQue 死锁、TQue buffer 不足 |
| 数据随机错误 | MTE2 没完成就计算、MTE3 没完成就下一轮搬入、同步缺失 |
| MTE2/VF/MTE3 时序违例 | PipeBarrier 缺失、事件依赖错误 |
| double buffer 下精度正常，单 buffer 下异常 | 双缓冲掩盖了同步 bug |
| A5 VECTOR_ERROR | VF/MTE 时序或地址生成错误 |

### 7.3 A5 新流程下的流水同步诊断

A5 新流程**已删除 `pipeline_sync` 阶段**，全程不切换 double buffer。因此 A5 的流水同步问题诊断方式发生变化：

#### 诊断入口

1. **`baseline` 阶段**：双跑（`run-cases` + `KernelLaunch`）失败时，若 KernelLaunch 也失败，先排除 op_plugin 层问题，再进入 `kernel_debug`。
2. **`kernel_debug` 阶段**：分析当前 case 前，先调用 `ascendc-sync-static-check` 对 kernel 代码做同步缺陷扫描；若扫描发现高置信同步问题，优先修复后再做 DumpTensor 二分。
3. **`regression` 阶段**：双跑回归时再次全量验证，确保修复没有引入新同步问题。

#### 诊断手段

- **静态检查为主**：`ascendc-sync-static-check` 覆盖 EnQue/DeQue 配对、手动 SetFlag/WaitFlag 配对、MTE2/MTE3 地址重叠、PipeBarrier 使用、Mutex/TBuf 同步、Scalar 流水、TBuf 无同步访问。
- **DumpTensor 辅助推断**：若 CopyIn 后数据就是垃圾值，或计算阶段数据异常但代码逻辑无明显错误，结合 sync-static-check 结果推断同步缺失。
- **动态死锁跟踪**：对 hang 类问题，可调用 `ascendc-sync-incore-tracker` 用 runnable case 定位具体 SetFlag/WaitFlag 行。

#### 已移除的手段

- **关闭 double buffer 实验**：A5 新流程全程使用原始 buffer 配置，不切换。
- **camodel trace 分析**：KernelLaunch 已移除 camodel 仿真能力，不再分析 MTE2/VF/MTE3 指令时序。

> 如果后续实践表明静态检查 + DumpTensor 无法覆盖某类流水同步问题，再评估是否重新引入一个不切换 double buffer 的轻量 `pipeline_sync` 阶段（仅用于 KernelLaunch 上板验证）。当前按用户定调不恢复。

### 7.4 通用同步检查（A3/A5 都适用）

调用 `ascendc-sync-static-check` 扫描：

- EnQue/DeQue 配对
- SetFlag/WaitFlag 配对
- PipeBarrier 使用位置
- MTE2/MTE3 地址重叠
- TBuf 无同步访问

调用 `ascendc-sync-incore-debug` 对具体函数做静态同步分析。

调用 `ascendc-sync-incore-tracker` 用 runnable case 动态定位死锁。

### 7.5 修复原则

- **先关 double buffer 再定位**：避免双缓冲掩盖问题；
- **同步事件必须成对出现**：每个 `SetFlag` 有对应 `WaitFlag`；
- **数据依赖用事件，全局同步用 `PipeBarrier`**；
- **TQue 深度要匹配生产消费节奏**：避免 EnQue 满或 DeQue 空；
- **修复后先单 buffer 验证，再恢复 double buffer 验证**。

### 7.6 对应 Skill / Agent

| 角色 | 名称 | 位置 | 适用流程 |
|---|---|---|---|
| **同步机制指南** | `ascendc-sync` | `.claude/skills/ascendc-sync/SKILL.md` | A3/A5 |
| **核内同步静态检查** | `ascendc-sync-static-check` | `.claude/skills/ascendc-sync-static-check/SKILL.md` | A3/A5 |
| **核内同步静态调试** | `ascendc-sync-incore-debug` | `.claude/skills/ascendc-sync-incore-debug/SKILL.md` | A3/A5 |
| **核内同步动态跟踪** | `ascendc-sync-incore-tracker` | `.claude/skills/ascendc-sync-incore-tracker/SKILL.md` | A3/A5 |
| **DumpTensor 调试** | `ascendc-dumptensor` | `.claude/skills/ascendc-dumptensor/SKILL.md` | A3/A5 |
| ~~A5 流水同步调试 Agent/Skill~~ | ~~`ascendc-pipeline-sync-debug`~~ | ~~`.claude/agents/...` / `.claude/skills/...`~~ | ~~A5 旧流程，已删除~~ |

> A5 新流程中，流水同步问题由 `kernel_debug` 阶段调用 `ascendc-sync-static-check` 做静态扫描，结合 DumpTensor 中间态推断定位；`pipeline_sync` 阶段和 double buffer 切换已删除。A3 遇到同步/卡死问题可直接调用 `ascendc-sync-static-check` / `ascendc-sync-incore-debug` / `ascendc-sync-incore-tracker`。

---

## 8. 各问题对应阶段速查表

| 问题 | 判定入口 | 主要分析工具/Skill | 对应 Agent | 修复验证方式 | 适用流程 |
|---|---|---|---|---|---|
| tiling 侧（UB/对齐/总量） | `bounds_check` | Python shadow、`ascendc-hardware` | `ascendc-precision-bounds-check` | shadow 重跑 + `run_tests` 全量 | A3 |
| tiling 侧（A5） | `kernel_debug` | `tiling_bounds_check` 轻量脚本、DumpTensor 中间态 | `ascendc-precision-kernel-debug` | KernelLaunch 回验 | A5 |
| kernel 计算错误 | `diagnose` / `fix` | `ascendc-dev-knowledge`、Gate1/Gate2 | `ascendc-precision-diagnose` / `ascendc-precision-fix` | 单用例验证 + 全量回归 | A3 |
| kernel 计算错误（A5） | `kernel_debug` | `ascendc-sync-static-check`、DumpTensor 二分、`ascendc-dev-knowledge` | `ascendc-precision-kernel-debug` | KernelLaunch 回验 + `regression` 双跑 | A5 |
| 精度问题 | `diagnose` / `printf_location` | numpy 对比、golden shadow、printf 二分 | `ascendc-precision-diagnose` / `ascendc-precision-printf-locate` | 单用例验证 + 全量回归 | A3 |
| 精度问题（A5） | `kernel_debug` | numpy 对比、误差分类、DumpTensor 二分 | `ascendc-precision-kernel-debug` | KernelLaunch 回验 + `regression` 双跑 | A5 |
| runtime crash | `comment_bisect` | 注释二分、DataCopy/TQue 消融 | `ascendc-precision-comment-bisect` | 单用例 crash/no-crash | A3 |
| runtime crash（A5） | `vector_error_debug` | P1/P2/P3 guard、`scan_a5_vector_risks.py` | `ascendc-precision-vector-error-debug` | 同一 case 错误签名消失 | A5 |
| vector_error（A5） | `vector_error_debug` | `scan_a5_vector_risks.py`、Top-K 消融、区域二分 | `ascendc-precision-vector-error-debug` | 同一 case 错误签名消失 | A5 |
| op_plugin / aclnn | `scope_guard` / `ascendc-runtime-debug` | plog 解析、注册/签名/JSON 检查 | `ascendc-precision-scope-guard` / `ascendc-runtime-debug` | 注册成功 + run-cases 通过 | A3 |
| op_plugin / aclnn（A5） | `op_plugin_debug` | 双跑交叉对比、错误码表、op_plugin 检查清单 | `ascendc-precision-op-plugin-debug` | run-cases + KernelLaunch 双跑收敛 | A5 |
| 流水问题 | `ascendc-sync-*` | `ascendc-sync-static-check`、`ascendc-sync-incore-debug`、`ascendc-sync-incore-tracker` | `ascendc-sync-static-check` / `ascendc-sync-incore-debug` / `ascendc-sync-incore-tracker` | 单用例验证 + 全量回归 | A3 |
| 流水问题（A5） | `kernel_debug` | `ascendc-sync-static-check`、DumpTensor 推断 | `ascendc-precision-kernel-debug` / `ascendc-sync-static-check` | KernelLaunch 回验 + `regression` 双跑 | A5 |

---

## 9. 参考文档

- `docs/stages/precision-debug-a3.md`
- `docs/stages/precision-debug-a5.md`
- `docs/plan/a5-precision-refactor/01-problems.md`
- `docs/plan/a5-precision-refactor/02-analysis.md`
- `docs/plan/a5-precision-refactor/03-solutions.md`
- `.claude/skills/ascendc-precision-bounds-check/SKILL.md`
- `.claude/skills/ascendc-precision-bounds-check/references/transform-rules.md`
- `.claude/skills/ascendc-precision-diagnose/SKILL.md`
- `.claude/skills/ascendc-precision-fix/SKILL.md`
- `.claude/skills/ascendc-precision-printf/SKILL.md`
- `.claude/skills/ascendc-precision-comment-bisect/SKILL.md`
- `.claude/skills/ascendc-precision-vector-error-debug/SKILL.md`
- ~~`.claude/skills/ascendc-pipeline-sync-debug/SKILL.md`~~（A5 旧流程，已删除）
- `.claude/skills/ascendc-runtime-debug/SKILL.md`
- `.claude/skills/ascendc-runtime-debug/references/error_codes.md`
- `.claude/skills/ascendc-runtime-debug/references/debug_workflow.md`
- `.claude/skills/ascendc-sync/SKILL.md`
- `.claude/skills/ascendc-sync-static-check/SKILL.md`
- `.claude/skills/ascendc-sync-incore-debug/SKILL.md`
- `.claude/skills/ascendc-sync-incore-tracker/SKILL.md`
- `.claude/skills/ascendc-pta/SKILL.md`
