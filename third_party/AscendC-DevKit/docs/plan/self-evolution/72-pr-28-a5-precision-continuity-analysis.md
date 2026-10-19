# 72 — PR #28 A5 precision_debug 进度接力 + TilingKey 路由 + 多 dtype 支持（L3 方案分析）

> 工作线：self-evolution / A5 RegBase 算子开发链路收口
> 性质：**L3 方案分析** —— 有哪些选项、选了哪个、为什么。
> 状态：已冻结（2026-07-24）。
> 前置 L1：`72-pr-28-a5-precision-continuity-problems.md`（P1-P5 事实快照）。
> 后置 L4：`72-pr-28-a5-precision-continuity-impl.md`。>

---

## 总体决策

PR #28 的 5 项改动均属于**A5 RegBase 链路的功能补齐与契约硬化**，彼此正交，但共享同一目标：让 A5 precision_debug 与 A5 codegen 的迭代闭环在跨轮次、跨模板、跨 dtype 场景下可收敛、可诊断、可自闭环。

| 问题 | 决策 | 选项 | 为什么选它 |
|---|---|---|---|
| P1 跨轮次接力 | **D1=A**：叶子 skill 写 `best_snapshot` + 框架防御性 fallback 重建 | A. 叶子写 + 框架兜底 fallback（推荐）<br>B. 框架集中写 snapshot | 叶子 skill 持有"本轮看到的最优失败集合"最自然；但 LLM 可能漏写，故框架加 fallback 从 `*_result.json` 重建，符合 §1.2「正确改动 + 宽容兜底 + 可观测」。 |
| P2 TilingKey 路由 | **D2=A**：通用 skill 只保留原则性描述，详细规则保留在 S4 agent | A. skill 去 driver 文件名、agent 保留详细规则（推荐）<br>B. 通用 skill 保留详细规则、修测试放宽容 | A 维持 §2.1 skill 自包含；B 破坏契约且会引入测试漂移。 |
| P3 多 dtype 指南 | **D3=A**：每个需要的 skill 在自身 `references/` 保留副本 | A. 各 skill 自包含副本（推荐）<br>B. 移到仓库级公共资源并由框架注入<br>C. 在 skill 目录放软链/清单 | PR 规模小、skill 数量少，A 最轻量且符合 §2.2 资源归属；B 需框架注入机制，本次不引入；C 对 TUI 复制不友好。 |
| P4 重试上限 | **D4=A**：上限改为 30 并补注释/L4 记录 | A. 30 + 注释说明（推荐）<br>B. 保持 6 并拆分失败类型<br>C. 30 但不做记录 | A 直接回应 A5 多 dtype + VF 融合场景迭代次数增加的事实；B 会增加复杂性且无证据；C 违反 §1.2 可诊断性。 |
| P5 baseline 类型 | **D5=A**：加载期校验 `baseline_status` + `best_snapshot` 必填字段 | A. 加载期校验 + 运行时 fail-safe 兜底（推荐）<br>B. 只做运行时 fail-safe<br>C. 只做加载期校验 | A 符合 §1.3「加载期校验优于运行期暴露」；B 是现状、延迟暴露；C 太严格，历史上可能有旧格式 checkpoint 需要兜底。 |

---

## 分问题展开

### D1 — A5 跨轮次进度接力

**背景**：A5 精度调试链路已按 step-53/54 拆为框架 CompositeGroup + 4 个子阶段，但子阶段之间没有传递"当前最优失败集合"的机制。每轮重启时，run_tests 从基线（baseline）从头扫，浪费 LLM 迭代预算。

**选项分析**：
- **A. 叶子 skill 写 `best_snapshot` + 框架 fallback 重建**：
  - 优点：职责正确（skill 知道本轮失败集合，框架只做持久化与兜底）；与现有 `checkpoint.json` / `*_result.json` 文件接力机制一致。
  - 缺点：需要给每个叶子 skill 增加写入提示与自检。
- **B. 框架集中解析 `*_result.json` 写 snapshot**：
  - 优点：skill 侧改动小。
  - 缺点：框架需理解每个叶子 skill 的私有 `*_result.json` 格式，耦合具体阶段；违反 §1.1 分层。

**结论**：选 A。框架在 `_load_a5_checkpoint` 增加轻量校验，在 transition 中提供 fallback 重建逻辑，形成"skill 写主路径 + 框架兜底"的双保险。

### D2 — TilingKey 路由方案

**背景**：TilingKey 方案 A/B 的选型规则需要同时指导 S4 agent（执行者）和通用编码 skill（编码者）。通用 skill 不应引用 driver 文件 `coding_index.md` / `template_division.json`，因为 skill 只应消费 staging 产物，不感知 pipeline 编排文件。

**选项分析**：
- **A. 通用 skill 去 driver 文件名，只保留原则性描述；详细规则保留在 S4 agent**：
  - 优点：恢复 skill 自包含；避免 agent 与 skill 重复内容漂移（skill 只保留"二选一、禁混用"一句话）。
  - 缺点：需要改两处文件。
- **B. 通用 skill 保留详细规则，测试放宽对 `coding_index` 的禁用**：
  - 优点：改动最小。
  - 缺点：破坏 §2.1 契约；测试守护失效，后续可能再次引入 driver 概念。

**结论**：选 A。S4 agent 是执行子 stage 的编排者，引用 `coding_index.md` / `template_division.json` 是合理的；通用编码 skill 只负责根据 staging 产物写出正确代码，不应知道 driver 文件。

### D3 — 多 dtype numpy 指南归属

**背景**：低精度 numpy（bfloat16 / int4 / float8 / float4）的构造、打包、golden 比较逻辑被多个 precision 叶子 skill 共用。PR 初稿把指南放在 `regbase-vf-test/references/`，导致其他 skill 跨目录引用。

**选项分析**：
- **A. 各 skill 在自身 `references/` 保留副本**：
  - 优点：完全自包含；TUI 复制单个 skill 目录即可运行。
  - 缺点：同一份内容多副本，更新时需同步。
- **B. 移到仓库级公共资源（如 `resources/`）并由框架注入**：
  - 优点：单一副本。
  - 缺点：需要框架注入机制，本次 PR 不引入；且 skill 仍依赖框架上下文。
- **C. 在 skill 目录放软链/清单**：
  - 优点：单副本 + 自包含。
  - 缺点：TUI 复制可能丢失软链目标；清单解析需要额外工具。

**结论**：选 A。PR 规模小，4 个 skill 各持一份副本的成本最低；后续若同类指南增多，再统一升公共资源。

### D4 — S5 编译重试上限

**背景**：A5 多 dtype + VF 融合代码生成场景下，编译-修复-再编译循环往往需要超过 6 轮。PR 把上限从 6 改为 30。

**选项分析**：
- **A. 30 + 注释说明 + L4 记录**：
  - 优点：直接回应场景需求；留下取值依据，未来可审计。
  - 缺点：数字主观。
- **B. 保持 6，按失败类型拆分重试预算**：
  - 优点：更精细。
  - 缺点：无数据支撑；增加配置复杂度。
- **C. 30 但不做记录**：
  - 优点：改动最小。
  - 缺点：未来维护者无法判断依据；可能掩盖工具链 flakiness。

**结论**：选 A。在代码注释中说明"按 A5 多 dtype + VF 融合场景下最多 30 轮内部修复实验设定"，并在 L4 记录 rationale。

### D5 — `baseline_status` 类型与加载期校验

**背景**：原先 `baseline_passed` 字段在 bool 与 count 之间漂移，PR 改为枚举 `baseline_status` + 三个 count 字段。但校验只在 `InitBaselineSubstage.transition` 运行时做。

**选项分析**：
- **A. 加载期校验 + 运行时 fail-safe 兜底**：
  - 优点：§1.3 加载期优先；malformed 文件早暴露；运行时仍兜底不崩。
  - 缺点：需要维护校验函数。
- **B. 只做运行时 fail-safe**：
  - 优点：简单。
  - 缺点：错误延迟到子 agent 已返回后，不符合 §1.3。
- **C. 只做加载期校验**：
  - 优点：严格。
  - 缺点：旧格式 checkpoint 无法恢复，可能误杀历史 run。

**结论**：选 A。`_load_a5_checkpoint` 中增加 `baseline_status ∈ {"passed","failed"}` 及 `best_snapshot` 必填字段校验；格式错误时 warn 并按 failed 处理，保留运行时兜底。

---

## 与上下游步骤的关系

- **依赖**：step-53（A5 precision_debug 编排根治）建立了 `pipeline_sync → dump_debug → vf_test → finalize` 的框架 CompositeGroup 基础；step-54 完成了 per-substage skill 拆分；step-51 是 A5 路径的 L4 前身。本步在它们之上补齐跨轮次状态、TilingKey 选型、多 dtype 指南、编译重试、baseline 类型硬化。
- **被依赖**：A5 端到端真实链路 heavy_llm ST（§3.11）需要本步记录的状态字段与校验逻辑作为前置。
