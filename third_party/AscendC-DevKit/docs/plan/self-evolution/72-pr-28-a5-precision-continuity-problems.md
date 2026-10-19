# 72 — PR #28 A5 precision_debug 进度接力 + TilingKey 路由 + 多 dtype 支持（L1 问题记录）

> 工作线：self-evolution / A5 RegBase 算子开发链路收口
> 性质：**L1 问题/需求记录** —— 客观事实（哪里缺失 / 凭什么这么说），不提方案、不排顺序、不写决策。
> 状态：冻结快照（2026-07-24，PR #28 提出时 HEAD `72fec4a6c6ce1d0fa72f91fb4b7c9b0d2e1d150d`）。
> 来源：仓外 review `reviews/PR-28-review.md`（ascendc-devkit-code-reviewer skill 产出）；本文件是其在仓内的产权落地（§1.7 自闭环）。
> 对应 L3：`72-pr-28-a5-precision-continuity-analysis.md`。
> 对应 L4：`72-pr-28-a5-precision-continuity-impl.md`。>
> 被记录对象：PR #28 分支 `pr-28-review` 相对 `upstream/main` 的 5 项实质性改动。

---

## 核实方法

PR #28 的改动内容经 `reviews/PR-28-review.md` 逐条核对代码/文档，5 项均为**已实施但未在 docs/plan 四层体系留痕**的实质性决策。下方每条给出：客观现象 + 凭证（文件:行）+ 影响。结论性判定属事实快照一部分。

---

## P1 — A5 precision_debug 跨阶段/跨轮次进度接力缺失

- **现象**：A5 RegBase 精度调试链路分为 `pipeline_sync → dump_debug → vf_test(条件) → finalize` 四个阶段，每轮失败后重跑时从基线从头扫，不保留"当前最优失败集合"。
- **凭证**：`src/ascendc_devkit/orchestration/stages/precision_debug_a5.py:77-86` `_load_a5_checkpoint` 仅做 `json.loads`；`:524-529` `InitBaselineSubstage.transition` 运行时才校验 `baseline_status`；PR 在相同文件引入 `best_snapshot` 字段（`max_err`/`passed`/`total`/`failed_cases`/`updated_by`/`updated_round`）及框架防御性 fallback（从 `*_result.json` 重建）。
- **影响**：LLM 叶子 skill 每轮重复分析已收敛的基线，浪费 token；框架 fallback 机制无加载期校验，延迟暴露格式错误。

## P2 — TilingKey 路由方案 A/B 在通用编码 skill 与 S4 agent 中重复且引用 driver 文件

- **现象**：TilingKey 选型规则（方案 A 模板参数编码 vs 方案 B 显式整数 Key）同时出现在通用编码 skill 和 S4 coding agent 中，且通用 skill 直接引用 `template_division.json` / `coding_index.md` 等 driver 文件。
- **凭证**：
  - `.claude/skills/ascendc-op-dev-coding/SKILL.md:164-178` "TilingKey 路由方案" 提到 `template_division.json` 和 `coding_index.md`；
  - `.claude/skills/ascendc-op-dev-coding/SKILL.md:267` SELFCHECK 表再次出现 `template_division.json` / `coding_index.md` / `tiling_strategy.json`；
  - `.claude/agents/ascendc-dev-s4-coding.md:221-237` 有几乎相同的选型表。
- **影响**：违反 CLAUDE.md §2.1/§2.2 通用 skill 自包含契约；`tests/ut/orchestration/test_codegen_a5_constraints.py` 因此失败；后续只改一处会导致 agent 与 skill 指引漂移。

## P3 — 多 dtype numpy 支持指南被多个 skill 跨目录引用，单 skill 取出后不可运行

- **现象**：新增的低精度 numpy 构造/打包/golden 比较指南 `multi-dtype-numpy.md` 放在 `regbase-vf-test/references/`，被 4 个 precision 叶子 skill 直接引用。
- **凭证**：
  - `.claude/skills/ascendc-pipeline-sync-debug/SKILL.md:455` 引用 `skills/regbase-vf-test/references/multi-dtype-numpy.md`；
  - `.claude/skills/ascendc-precision-dump-debug/SKILL.md:388` 同引用；
  - `.claude/skills/ascendc-precision-vf-debug/SKILL.md:463` 同引用；
  - `.claude/skills/ascendc-custom-op-precision/SKILL.md:20,410` 同引用；
  - `.claude/skills/ascendc-precision-finalize/SKILL.md`（新文件）也引用该文件。
- **影响**：单独抽取 `ascendc-pipeline-sync-debug` / `ascendc-precision-dump-debug` 等 skill 目录到干净 TUI 后，`/<skill>` 读取不到兄弟目录资源，违反 §2.1 即插即用。

## P4 — S5 编译重试上限 6 在 A5 多 dtype + VF 融合场景下不足

- **现象**：A5 RegBase 多 dtype + VF 融合代码生成链路迭代修复时，6 轮重试不够收敛。
- **凭证**：`src/ascendc_devkit/orchestration/stages/codegen.py:411` 处 `retries.stage5_compile.limit` 从 6 改为 30；PR 同步修改 regbase skill 和相关测试。
- **影响**：阈值无设计文档或注释说明，未来维护者无法判断 30 是实测收敛值还是拍脑袋兜底；若工具链本身不稳定，30 可能掩盖 flakiness。

## P5 — `baseline_passed` count/bool 类型混淆

- **现象**：A5 精度调试的 checkpoint 用 `baseline_passed` 字段，其语义在 bool 与 count 之间漂移，导致下游读取错误。
- **凭证**：`src/ascendc_devkit/orchestration/stages/precision_debug_a5.py:524-529` 用 `baseline_status` 枚举（`passed`/`failed`）+ `baseline_total_count` / `baseline_passed_count` / `baseline_failed_count` 替代原先类型；`:77-86` `_load_a5_checkpoint` 未在加载期校验新 schema。
- **影响**：malformed baseline result 文件要到子 agent 返回、框架进入 transition 时才发现；虽然 fail-safe 会按 failed 处理，但加载期缺校验不符合 §1.3。

---

## 汇总（事实快照）

| P# | 问题 | 级别 | 结论 | 核心证据 |
|---|---|---|---|---|
| P1 | A5 跨轮次进度接力缺失 | major | 成立 | `precision_debug_a5.py` best_snapshot 字段 + 无加载期校验 |
| P2 | TilingKey 路由重复 + 引用 driver 文件 | major | 成立 | `ascendc-op-dev-coding/SKILL.md:164-178` / `:267` vs `ascendc-dev-s4-coding.md:221-237` |
| P3 | 多 dtype 指南跨目录引用 | major | 成立 | 4 个 precision skill 引用 `regbase-vf-test/references/multi-dtype-numpy.md` |
| P4 | S5 编译重试上限 6→30 无依据 | minor | 成立 | `codegen.py:411` + 无注释/design doc |
| P5 | baseline_passed 类型混淆 | minor | 成立 | `precision_debug_a5.py` 运行时 fail-safe 替代加载期校验 |
