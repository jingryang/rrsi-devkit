# 53 — precision-debug skill per-substage 拆分分析（L3）

> 性质：**L3 方案分析** —— 选项之间的取舍 + 理由。调研中演进、拍板后冻结；不含 L4 改行配方。
> 状态：**已拍板（2026-07-17）—— 选项 B + 混合切分**。L4 = `54-precision-debug-skill-split-impl.md`。
> 前置依赖：**doc 51 CompositeGroup 落地**（commit `588e248c` 已实施；编排权归框架后，skill 拆分才有干净承载点）—— **已满足**。
> 关联：L1 运行事实 `50-non429-issues-analysis.md` §1（编排层 bug）；L4 `51-precision-debugger-async-fix-impl.md`（CompositeGroup 主干已实施 + §12 正交增强）；L4 `54-precision-debug-skill-split-impl.md`（本 L3 的落地版）。
> 起因：讨论 doc 51 落地形态时确认「4 phase agent 共享一个 skill / 一个 checkpoint」，遂问能否按 substage 拆 skill、各 skill 自带 schema。

## 0. 一句话结论

**拆**——per-substage skill + 各 skill 自带 schema 是**框架既定范式**（design 阶段就这么做：`STAGE_SKILL_MAP` 每 substage 一个 skill、`_schema_files` 各 skill 自带 schema、`_INPUT_FILENAMES` 文件接力），precision-debug 现状「一个胖 skill + 一个胖 checkpoint」是 §2.1/§2.2/§2.3 smell。**但它是正交重构、不治 bug**（bug 在编排层，已由 doc 51 治），须作**独立 workstream**，且**等 doc 51 CompositeGroup 合并后**再做——编排权还在 LLM 编排器手里时拆 skill，收益打折。拆分边界：**A 类（各 phase 操作数据）按 owner 拆成 per-skill schema 文件；B 类（loop 控制态）不拆，归框架 State**（顺 doc 51 §7 已定方向）。

---

## 1. 问题（现状事实 + smell）

### 1.1 现状（实证）

- 4 个 phase agent（`ascendc-precision-{run-tests,diagnose,fix,printf-locate}`）frontmatter 都声明 `plugins: [stage-precision-debug, shared]` → **共享同一个 plugin / 同一个 skill** `ascendc-precision-debug`。
- phase 差异不在 skill，而在：① 各 agent 自己的 `.md` body（角色 + hard rules，自包含）；② 共享 skill 里的 `references/prompts/{run_tests,diagnose,fix,printf_location}.md` + `references/gates/`。
- schema 集中在**一个** `rules/checkpoint-spec.md`，状态集中在**一个** `<op_dir>/.precision-fix/checkpoint.json`。

### 1.2 smell（命中哪些原则）

| 原则 | 现状 | 说明 |
|---|---|---|
| §2.1 skill 自包含、可单独 `/skill` 跑 | ✗ | phase 方法埋在共享 skill 的 `prompts/`，单 phase 拿不出独立 skill |
| §2.2 schema 归各 skill 目录 | ✗ | 一个共享 `checkpoint-spec`，非各 skill 自带 |
| §2.3 skill 链文件接力闭环 | △ | run_tests→diagnose→fix→printf 这条链被捆在**一个** skill 里，非真接力 |
| §2.7 核心方法归 skill | △ | 方法散在 agent body + prompt 文件，归属含糊 |

### 1.3 这是模块化/合规问题，不是 bug

precision-debug 的 P0 bug 在**编排层**（SDK async ↔ LLM 编排器同步失配 → 空转 → context 爆，L3 `50` §1），由 doc 51 的 CompositeGroup 治。**skill 结构本身没坏**——本项是「让它更贴框架范式」的正交重构，不是缺陷修复（§1.2 须过四把尺子，见 §3）。

---

## 2. 选项

### 选项 A：不拆（维持一胖 skill + 一胖 checkpoint）

- 维持现状，零改动。
- 代价：§2.1/§2.2/§2.3 smell 长期在；与 design 阶段范式不一致（一个仓里两套 skill 组织方式）。

### 选项 B：拆——per-substage skill + 各 skill schema + 文件接力（A 类拆、B 类不拆）★ 推荐

- 每 phase 一个独立 skill（含自己的 `schema/`）；A 类操作数据按 owner 拆成独立 json 文件；B 类 loop 控制态归 State。
- 收益：消除 §1.2 全部 smell、对齐 design 范式、§12.2 加载期校验天然 per-skill。
- 代价：4→多 skill 的迁移成本（scripts/agents 随之重构）；跨 slice 读依赖需 input_contract 声明。

### 选项 C：折中——不拆 skill，仅把 checkpoint schema 按字段标注 owner

- skill 仍合一，但 `checkpoint-spec` 标注每个字段的 owner phase。
- 收益：轻量、明确字段归属。
- 代价：不解决 §2.1（skill 仍不可独立拿出）、§2.2（schema 仍不在各 skill 目录）；只比 A 好一点，比 B 差很多。

**对比**：B 是正解；C 是「想做但不想动 skill」的半吊子；A 是「不动」。推荐 **B**。

---

## 3. 四把尺子评估（CLAUDE.md §1.2，针对选项 B）

| 尺子 | 评估 |
|---|---|
| **可维护** | ✓ 对齐 design 范式（一仓一套 skill 组织）；schema 演进只动对应 skill，无共享 schema 牵连 |
| **可扩展** | ✓ 新增 phase（如 memcheck 子阶段）= 加一个 skill + 一个 schema 文件，自动归位 |
| **可诊断** | ✓ 各 phase 产物独立文件，crash 留一致 per-slice 态（比一个半写的大文件更稳）；加载期校验 per-skill 更内聚 |
| **架构合理** ✓ | ✓ skill 链真接力（§2.3）、schema 归位（§2.2）、skill 可独立拿出（§2.1）；编排权仍在框架（doc 51 已归位） |

B 四把尺子全过，且不与 doc 51 主干冲突（正交）。

---

## 4. 关键设计决策：A/B 拆分边界（选项 B 的核心）

**最容易踩的坑是一刀切**。顺 doc 51 §7 已定的 A/B 分类：

### A 类（各 phase 操作数据）→ 按 owner 拆成 per-skill schema 文件

| skill | 拥有文件 | 字段 | schema 归属 |
|---|---|---|---|
| run_tests | `failed_case_queue.json` | failed_case_queue / history / current_case_index | run_tests skill `schema/` |
| diagnose | `candidate_pool.json` | candidate_pool / arch_gaps | diagnose skill `schema/` |
| fix | `fix_state.json` | fix_code_log / best_commit / debug_state | fix skill `schema/` |
| printf | `printf_state.json` | printf_location_result / bisect_progress | printf skill `schema/` |

### B 类（loop 控制态）→ **不拆，归框架 State `_debug_checkpoint`**

`status` / `current_iteration` / `current_stage` / `best_max_err` / `best_failed_count` / `diagnose_done` 是**全局**的，不属于任何单 phase，框架 `resolve_condition` 读它路由。**把 B 类也拆进某 phase 会让状态机崩**——只有 A 类拆、B 类留全局才是对的，且与 doc 51 §7 一致。

### 跨 slice 读依赖

fix 要读 run_tests 的 `failed_case_queue` + diagnose 的 `candidate_pool` → 用 `input_contract` 显式声明（design 子 stage 已这么做：`requires=["tiling_results","anchor_report"]`）。不是阻塞，但要落进各 skill 契约。

### §12.1 scope guard 一并拆

scope guard 有自己的 verdict schema（`scope_verdict`/`upstream_stage`/`scope_reason`）→ 也成独立 skill（`ascendc-precision-scope-guard`），与 doc 51 §12.1 的新 agent 天然成对。

### §12.2 加载期校验随之 per-skill

各 phase 拥有自己 schema 后，加载期契约校验 = 每 skill 加载自己 slice + 自己 schema 校验，比校验一个胖 checkpoint 更内聚；契约演进只动对应 skill。

---

## 5. 与 doc 51 / §12 的衔接 + 前置依赖

- **前置依赖 = doc 51 CompositeGroup 合并**。理由：skill 拆分的承载点是「框架驱动的子 stage + 文件接力」；编排权还在 LLM 编排器手里时（现状），phase agent 由编排器 Agent() 派发、skill 拆分收益打折。doc 51 落地后编排权归框架 GraphExecutor，子 stage `transition()` 读各 phase 文件 → State，拆分才有干净落点。
- **不改 doc 51 核心**：skill-split 是独立 workstream，**禁止塞进 doc 51 的 P0**（§1.2 方案合理性 + 范围纪律——P0 必须先干净落地）。
- **与 §12 同待遇**：二者都是 doc 51 主干之后的正交增强；§12（scope guard + 加载期校验）可与本项协同（scope guard skill 化、加载期校验 per-skill）。
- **A/B 边界与 doc 51 §7 一致**：本项 = 把 §7 的 A 类从「同住一个 checkpoint.json」推进为「各 skill 独立 schema 文件」，B 类不动（已在 State）。

---

## 6. 迁移路径选项（待拍板，属 L4 细节，此处只列方向）

| 子决策 | 选项 | 倾向 |
|---|---|---|
| **文件切分粒度** | (a) 每 phase 一个独立 json 文件（真 §2.2） / (b) 一个 checkpoint 多 section | (a)——对齐 design 的 general_design.json/tiling_results.json/anchor_report.json 独立文件范式 |
| **方法论归位（§2.7）** | phase 核心方法进各 skill `SKILL.md`，agent 当执行器（design 范式）；脚手架留 agent/LLM | 进 skill |
| **scripts per-skill 化** | init/verify/update 按 owner 拆；stage-transition 已由 doc 51 删 | per-skill，§1.4 直接改干净不留兼容 |
| **scope guard skill** | 独立 skill + 独立 verdict schema（与 §12.1 agent 成对） | 独立 |

§1.4 约束：工程未发布、无外部用户，**直接改干净**，不留旧 checkpoint 兼容/迁移分支。

---

## 7. 落地节奏建议 + 待拍板项

### 节奏
1. doc 51 CompositeGroup 合并（P0 先行）。
2. §12 落地（scope guard + 加载期校验）——可与本项协同。
3. **本项立 L4 实施**（拍板后）。

### 待拍板（用户决策）— 已拍板（2026-07-17）
- [x] 采用选项 B（per-substage skill + 各 skill schema + 文件接力）。
- [x] 文件切分粒度：**混合切分** —— 5 per-phase json（纯 owner A 类）+ `control.json`（跨域 candidate_pool/history + B 类控制态）。
- [x] scope guard 一并拆成独立 skill（`ascendc-precision-scope-guard`，与 51 §12.1 agent 成对）。
- [x] 本 L3 拍板后即立 L4 实施（用户选「完整范围一次性做」= Phase 5 + Phase 6 + 完整 53 拆分）。

> 字段 owner 映射表、as-built、分阶段配方见 L4 `54-precision-debug-skill-split-impl.md`。

---

## 8. 关键路径索引

- 现状（待拆）：
  - 4 phase agent：`.claude/agents/ascendc-precision-{run-tests,diagnose,fix,printf-locate}.md`（frontmatter `plugins: [stage-precision-debug, shared]`）
  - 共享 skill：`.claude/plugins/stage-precision-debug/skills/ascendc-precision-debug/`（`SKILL.md` + `scripts/` + `rules/{main-loop,checkpoint-spec}.md` + `references/{prompts,gates}/`）
  - 共享 schema：`rules/checkpoint-spec.md`；共享状态：`<op_dir>/.precision-fix/checkpoint.json`
- 对标范式（已实证存在）：
  - `src/ascendc_devkit/orchestration/design_tree.py`（`CompositeGroup` + scoped transition_table）
  - `src/ascendc_devkit/orchestration/stages/design_substages.py`（`_DesignSubstage`：`_assigned_skill()` 读 `STAGE_SKILL_MAP`、`_schema_files` 各 skill 自带 schema 经 `SchemaLoader.load_contract_from_skill` 加载、`_INPUT_FILENAMES` 文件接力、`input_contract` 声明跨阶段读依赖）
- 依赖与协同：
  - L4 `51-precision-debugger-async-fix-impl.md`（CompositeGroup 主干 + §7 A/B 归属 + §12 正交增强）
  - L4 `54-precision-debug-skill-split-impl.md`（本 L3 的落地版）
  - L3 `50-non429-issues-analysis.md` §1（编排层 bug，非本项范围）
- 框架原则：CLAUDE.md §1.2（四把尺子）/ §1.4（不留兼容）/ §2.1（skill 自包含）/ §2.2（schema 归各 skill）/ §2.3（文件接力）/ §2.7（核心方法归 skill）
