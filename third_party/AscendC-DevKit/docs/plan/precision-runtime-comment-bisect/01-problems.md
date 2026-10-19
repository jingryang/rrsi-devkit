# precision_debug runtime 注释二分定位 — L1 问题记录（2026-07-22）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/根因/影响）。
> **不提方案**。方案分析见 `02-analysis.md`（L3）；实施方案见 `03-impl.md`（L4）。

## 证据来源

- **代码**：`src/ascendc_devkit/orchestration/stages/precision_debug_substages.py`（FixSubstage）、`src/ascendc_devkit/orchestration/precision_debug_tree.py`（transition_table）
- **fix skill**：`.claude/skills/ascendc-precision-fix/SKILL.md`、`references/prompts/fix.md`、`.claude/agents/ascendc-precision-fix.md`
- **路由事实**：`pool_exhausted + runtime` 当前返回 `"retry"`（substages.py:1498），定位实际由 fix agent 内嵌「消融实验模式」承担（fix.md:177-212）

---

## P1（严重）：runtime 定位缺乏二分收敛状态机

### 证据
- `FixSubstage.resolve_condition`（substages.py:1495-1500）：`pool_exhausted + runtime` → `return "retry"`，回 fix
- fix.md:177-212「runtime 消融实验模式」：策略为固定三档「参数消融（硬编码 ubFactorS=1）→ 阶段消融（注释 CopyIn/Compute/CopyOut）→ 算子消融（注释单个运算）」，非「注释一半→收敛→再注释一半」的二分
- fix.md:188「单次 spawn 最多做 3 个消融实验」；fix.md:189-190「3 个后未定位 → FIX_REFUTED，框架 respawn 续跑」

### 根因
定位逻辑以 ad-hoc 注释策略内嵌在 fix agent 单次 spawn 内，无 `suspect_region` 随实验收缩的二分状态机。

### 影响
无法保证收敛到问题代码区域；大 kernel 上 3 次实验可能打不中，靠 respawn 累积 `ablation_log` 碰运气，`corrective_cycles ≥ 8` 兜底跳 case（substages.py:1467）。

---

## P2（中等）：无行级确认层

### 证据
fix.md:185-186 算子消融「注释单个运算（Cast/Mul/Add/DataCopy）」是最细粒度；无「区块内逐行注释确认触发行」步骤。

### 根因
消融设计止于算子粒度。

### 影响
定位到「某运算崩溃」后无法确认具体代码行/参数，fix_plan 的 `location` 粒度粗。

---

## P3（严重）：无多根因机制

### 证据
- fix.md:200-201 `ablation_log.append(...)` 线性追加实验
- fix.md:196 `if result.located_root_cause: break`——定位到一个即 break，不继续二分剩余区域

### 根因
单根因假设。

### 影响
多处独立 bug 时只修一处，其余被掩盖；run_tests 回归仍 crash → fix 池空 → respawn 消融从零开始（`ablation_log` 无「已排除区域」记忆），重复劳动。

---

## P4（严重）：定位与应用职责混杂（架构）

### 证据
- fix SKILL.md:15-22 职责声明同时含「候选池验证应用」与「runtime 消融定位」
- fix.md:49-208 把 candidate_pool 循环（应用）与消融实验（定位）混在同一个内部循环伪码
- 消融证据借用 `fix_code_log.ablation_log`（fix.md:201），无独立 schema/产物

### 根因
runtime 定位无独立 stage 承载，塞进 fix。

### 影响
违反 §2.5（fix 既是应用通路又内嵌定位通路，非唯一通路）、§2.7（fix skill 职责膨胀）；消融无独立产物可观测；单 spawn 内 candidate 验证 + 多次 redeploy 消融，context 易爆。

---

## P5（中等）：comment-bisect 悬空引用

### 证据
fix SKILL.md:118/139、fix.md:130/398、`.claude/agents/ascendc-precision-fix.md:45` 四处写「回退 comment-bisect（见 printf-debug.md）」；但 `.claude/skills/ascendc-precision-printf/references/gates/printf/printf-debug.md` 是 printf 二分（依赖输出），非注释二分。

### 根因
注释二分从未实现，引用指向不相干的 printf 文档。

### 影响
维护者按引用读到错误的二分方法；runtime crash（kernel 死在 flush 前、无输出）根本不适用 printf 二分。

---

## 问题汇总矩阵

| 问题 | 严重度 | 性质 | 核心锚点 |
|------|--------|------|---------|
| P1 runtime 定位无二分收敛状态机 | 严重 | 机制缺失 | fix.md:177-212 ad-hoc 消融 |
| P2 无行级确认层 | 中等 | 机制缺失 | 消融止于算子粒度 |
| P3 无多根因机制 | 严重 | 单根因假设 | fix.md:196 locate 即 break |
| P4 定位与应用职责混杂 | 严重 | 架构违反 §2.5/§2.7 | fix SKILL.md:15-22 |
| P5 comment-bisect 悬空引用 | 中等 | 文档错引 | 指向 printf-debug.md |

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-07-22 | 初版：P1–P5，基于 fix skill + substages 现状 |
