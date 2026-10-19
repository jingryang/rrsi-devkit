# 03 — 实施方案（L4）：批次2 —— precision_debug 最小化（§1.14 减法，非加法）

> 本文是**独立批次 2** 的实施方案，可单独修改、单独提交，与批次 1（`02-impl-codegen.md`）互不依赖。
> 依据 `01-analysis.md` 的漏检根因，但**方向改为 §1.14 的"最小结构优先"**：precision_debug 现在的「枚举错误类型 + 候选池 + 回炉」本身就是"控模型"结构，该做**减法**（删结构），不是**加法**（加定位手段）。
> **本批次实施前须先过方案评审 + 四把尺子（§1.2）**；这是大重构，触框架 orchestration，建议分阶段。

---

## 一、改动目标

按 §1.14，把 precision_debug 从「run_tests → scope_guard → bounds_check → diagnose(Gate1/Gate2/candidate_pool) → printf_location → comment_bisect」这套**六 phase 结构化定位/回炉**，简化为「**run_tests（golden 比对）→ 一个诊断+修复阶段（就地定位+修）→ 回跑验证**」的最小闭环。

- 定位**不靠枚举规则**（错误类型无界，枚举 = 打补丁），靠 **golden 比对不一致 → 就地查 API 约束/插 printf 二分 → 就地修**（§1.13/§1.14「比对 golden 一致即对，不一致就地修」）。
- 定位是** agent 的自然动作**，不是**框架编排的独立 phase**。

## 二、删什么（控模型结构清单）

| 结构 | 归属 | 删的理由（§1.14） |
|------|------|-------------------|
| `diagnose` Gate1 枚举（symptom-table → common-traps → case-studies） | 控模型 | "不靠枚举规则（错误类型无界，枚举 = 打补丁）" |
| `diagnose` Gate2 独立 sync gate（`ascendc-sync-static-check` 独立 gate 编排） | 控模型 | 同上，门不该当定位主路径 |
| `candidate_pool`（hits≤2 + priority + verified 状态机 + excluded_hypotheses） | 控模型 | "模型在填表而非解算子" |
| fix 分级（Grade A/B/S）+ 分级验证 + commit/rollback 状态机 | 控模型 | 回炉机制 |
| `route_to` 三问自检（根因唯一性 / 症状歧义度 / 结构性排除） | 控模型 | 门 + 假阴性传导（见 `01-analysis.md` §3.4） |
| `bounds_check` Python shadow checker（UB_OOB/ALIGN_32B/UB_TOTAL 静态影子） | 控模型 | 静态 checker，覆盖不到"数据依赖越界"（`01-analysis.md` §3.2） |
| `printf_location` 独立 phase（bisect_progress / max_rounds=30 / tried_bisect_paths / RESULT 协议） | 控模型 | 回炉编排 |
| `comment_bisect` 独立 phase（Layer0/1/2 + 实验预算 + RESULT 协议） | 控模型 | 回炉编排 |
| `scope_guard` 首轮入口守卫 | 控模型（评估） | 门；但其"拦 upstream 缺陷避免空转"有真实价值，见 §四 保留项 |

## 三、留什么（帮模型 + 最小骨架）

1. **`run_tests`（golden 比对）** + 文件 I/O 接力——这是"golden 可运行产物"的最小骨架，权威兜底。
2. **知识前置**：`ascendc-dev-knowledge`（官方镜像）+ `ascendc-api-best-practices`（我们的经验库）可查。
3. **一个"诊断+修复"阶段**：agent 读 `failed_case_queue` → **就地定位**（比对 golden 找发散点 → 查对应 API 的 round mode / 对齐 / 支持矩阵 → 插 printf 二分收敛到行）→ **就地修那一处** → 回跑 golden 验证。**无候选池、无分级、无回炉**——"谁发现谁改、只改那一处"（§2.9 原地修改优先于回炉）。

### 定位怎么写进 skill（不加结构，一句话引导）

在"诊断+修复"阶段的 skill 里写（不是新 gate/新 step，是既有流程里的一句判据）：

> 比对 golden 不一致时：先读对应 API 的支持矩阵 / round mode / 对齐约束（知识库 + 经验库），再插 printf 二分定位发散点；定位后**就地改那一处**，不生成候选池、不回炉重生成。

### scope_guard 的去留（保留价值评估）

`scope_guard` 的唯一价值是"拦 upstream 缺陷（编译失败/schema 不匹配/golden 缺 get_input）避免在非本阶段 bug 上空转"。这条**不属"控模型"的枚举**，而属"路由"（§4.1 契约）。建议：**保留但降级**——不再独立 spawn，改为"诊断+修复"阶段入口的**一句判据**（"先看 failed case 是崩了/数值错/还是上游编译注册错，上游错则 halt"），删掉它的独立 schema / RESULT 协议 / control.json 字段。

## 四、改动清单（按文件，分阶段）

### 阶段 A（低风险，先做）：diagnose 内部去枚举

1. `.claude/agents/ascendc-precision-diagnose.md`：删 Step 1 的 Gate1/Gate2 枚举，改为"读 failed case → 就地定位（golden 发散点 + API 约束 + printf 二分）→ 就地修"。
2. `.claude/skills/ascendc-precision-diagnose/SKILL.md`：删 Gate1/Gate2/candidate_pool/route_to 的 reference 索引 + 流程正文，改为"就地定位+修"引导（§三的一句话）。
3. 删 `references/gates/gate1-static-check.md`、`gate2-sync-check.md`、`static-check/`（symptom-table/common-traps/case-studies）。

### 阶段 B（中风险）：删独立 phase 的回炉编排

4. `.claude/agents/ascendc-precision-printf-locate.md`、`ascendc-precision-comment-bisect.md`：删独立 phase 的 bisect_progress / max_rounds / RESULT 协议，改为"诊断+修复阶段内部可用的 printf 二分 / 注释降级**技巧**"（进 skill references，不作为独立 phase）。
5. `.claude/agents/ascendc-precision-bounds-check.md`：删 Python shadow checker（静态越界影子覆盖不到数据依赖越界）。

### 阶段 C（高风险，最后）：框架 orchestration 收敛

6. `src/ascendc_devkit/orchestration/stages/precision_debug_*`：删 scope_guard / bounds_check / printf_location / comment_bisect 的 transition 路由 + phase 类，收敛到「run_tests → 诊断+修复」两段。
7. 删对应 schema（`precision_diagnose.json` 的 candidate_pool/runtime_error_info/arch_gaps 等字段；`precision_printf.json`、`precision_comment_bisect.json`、`precision_bounds_check.json`）。
8. 删对应 UT（`tests/ut/.../test_precision_debug_*` 里测已删结构的用例）。

## 五、验证

- **UT**：全量绿（删结构后，同步删/改受影响用例，§3.4 不 skip）。
- **ST（真实链路，§3.9 触发）**：用一个 known-bug 算子（unique 的 Cast/对齐现场）跑最小闭环，验证「run_tests → 诊断+修复 → 回跑」能定位并修对（此前六 phase 漏检的，最小闭环能检出）。属 heavy_llm（真实 LLM 全流程），跑前向用户列清单（§3.11）。
- **回归**：确认删除后没有"假阴性传导 / 候选池去重 / 回炉循环"这些被删机制的回归——因为它们本就是要删的，回归即验证"删干净"。

## 六、边界（本批次不碰）

- 不改 codegen / 经验库（`ascendc-op-dev-coding` / `ascendc-api-best-practices` / `ascendc-tips`）——批次 1（`02-impl-codegen.md`）。
- 不改 `run_tests` 的 golden 比对主体（那是留的最小骨架）。
- 不改算子代码。
- `ascendc-tips` 去留仍是独立议题（见 `02-impl-codegen.md` §七），不并入本批次。

## 七、风险与分阶段理由

- 这是**大重构**（六 phase → 两 phase），直接一步到位会同时触碰 agent + skill + orchestration + schema + UT，回归面大。
- 故按 §三/§四 分 A（diagnose 内部去枚举，纯 prompt/skill 层）→ B（删独立 phase 的编排）→ C（framework orchestration 收敛）三阶段推进，每阶段独立可测、可回退。
- 每个阶段交付前用 §1.2 四把尺子（可维护/可扩展/可诊断/架构合理）过一遍，尤其"架构合理"——删掉的"回炉/候选池"若被下游 stage 或 harness 依赖，须先确认无消费者再删。

---

## 八、实施记录（2026-08-23，P3 减法完成）

本方案（批次 2）已按 A→B→C 三阶段**全部实施**，随 commit（阶段 A）与（阶段 B/C）落地：

- **阶段 A**：diagnose 去枚举（Gate1/Gate2/candidate_pool/route_to/fix 分级删）→ 就地定位+修；scope_guard 降级为 diagnose 入口 upstream 判据；techniques（printf 二分/注释降级）进 references。
- **阶段 B**：删 5 个独立 phase 载体（scope_guard/bounds_check/printf/comment_bisect/diagnose_refine 的 agent+skill+schema）+ 框架 phase 类 + transition_table 塌缩为 run_tests⇄diagnose + workflow 删 deploy_broken + adapter transition.py 收敛。
- **阶段 C**：清理残留控模型 helper/字段（candidate_pool/corrective_cycles/deploy_fail_streak 等）+ runtime_config 删 max_corrective_cycles + UT 收口 + 全量绿。

验证：precision_debug 相关 UT 全绿 + 全量 UT 绿。本次 unique 20260822 批实证（5 phase 空转 3.2h 零通过）是减法的必要性背书。
