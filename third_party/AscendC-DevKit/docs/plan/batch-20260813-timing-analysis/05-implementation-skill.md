# L4 — skill 内容改动实施方案（R3 / R4 / R10）

> 定位：L4 实施方案，覆盖「改 skill 内容（SKILL.md / references / schema）」的 3 个方案。改框架 Python 代码的 R1/R2/R5/R7 见 `04-implementation-framework.md`。
> 上游：L1 `01-problems.md`、L3 `02-analysis.md` §6、L4 内容草案 `03-gather-paradigm-skill-draft.md`（R3 的 api-gather.md 内容设计）。
> 原则：skill 即插即用（§2.1）、知识/数据归 references 不内联 workflow（§2.8）、结构特征不点名算子（§1.12）、不补丁式改现有文档（新建独立主题）。

> **实施状态（截至 2026-08-14）**：R3（R3-0 移植 best-practices + R3-1 api-gather.md + R3-2 G01 补变体 + R3-3 knowledge_policy + R3-4 检索优先级 + SKILL.md 索引）、R4（首稿纪律）、R10（读取纪律）**均已实施**。

## 改动清单总览

| 方案 | 改动对象 | 改动性质 | 依赖 |
|---|---|---|---|
| R3-1 | 新建 `ascendc-api-best-practices/references/api-gather.md` | 新增 API 用法主题 | 03 草案内容 |
| R3-2 | `ascendc-op-general-design/references/patterns/atomic/G01_gather-vector.md` | 补「采样/插值」变体 | 03 草案内容 |
| R3-3 | `ascendc-op-design-shared/references/knowledge_policy.md` | 加 best-practices 层级 + 查证门优先级 | R3-1 |
| R3-4 | `ascendc-dev-knowledge/SKILL.md` | 检索优先级加 best-practices | R3-1 |
| R4 | `ascendc-op-dev-coding/SKILL.md` Step 4 | 补「首动作先落全套文件」 | 无 |
| R10 | design/codegen skill 输入获取章节 | 补「每文件读一次 + 禁 ls/cd/find」 | 无 |

---

## R3 — API 最佳实践前置 + gather 主题（4 处波及面）

### R3-1 新建 `api-gather.md`（API 用法层）

- **内容来源**：`03-gather-paradigm-skill-draft.md` §3（原语选择）、§5（关键约束）、§6（反例）、§6.1（正例）。
- **格式**：对齐 `api-gathermask.md` 章节模板（`# 使用指南` → 适用场景 → 目录 → 概述 → 平台适用性 → API 详解 → 常见错误 → 检查清单 → 适用性检测 → 参考资料），见 03 草案 §0 精确落位表。
- **剥离**：算子名（§1.12）、编号（§2.11）、分析元信息（验证实例追溯等）不落正文。
- **验证**：格式与 `api-gathermask.md` 章节一致；内容只含「API 用法 + 约束 + 避坑」，不含建模范式（分块洞察归 R3-2）。

### R3-2 `G01_gather-vector.md` 补「采样/插值」变体

- **内容来源**：`03-gather-paradigm-skill-draft.md` §1（适用判据）、§2（分块范式）。
- **改动**：在 G01 的「已知变体」表（§五）加一行「坐标采样/插值」变体——触发条件「index 由坐标变换（floor/ceil）生成、角点有相邻结构（相邻维差 1 元素）」，与主模式差异「沿连续维分块 + 常数维 floor/ceil 退化 → 采样窗口退化为局部条带，非逐元素搬移」。
- **不越界**：G01 范围红线「不含 API 调用细节」——只写概要设计的切分策略，不写 Gather/srcOffset 具体用法（那归 R3-1）。
- **验证**：G01 的「已知变体」表新增采样/插值条目；切分策略补充「沿连续维分块」与现有「沿 index 轴切分」并存。

### R3-3 `knowledge_policy.md` 加 best-practices 层级 + 查证门优先级

- **改动 1**：三级知识源体系表加一行 `ascendc-api-best-practices` 为「API 用法层」（插在 Tier 2 与 Tier 3 之间，或标 Tier 2.5）。
- **改动 2**：「骨架级 API 强制查证门」的「无条件完成 Tier 3 明文查证」改为「**先查 `ascendc-api-best-practices`（API 用法 + 避坑）→ 查不到再查 Tier 3（裸签名细节）**」。
- **依据**：现有查证门只查裸签名，gather 的坑（怎么分块、禁逐元素 DataCopyPad）在用法/范式层不在裸签名——grid_sampler AC2 查了签名没查用法坑。调整后 gather 强制查证先命中 api-gather.md。
- **验证**：knowledge_policy.md 三级表含 best-practices；查证门文字含「先 best-practices → 再 Tier 3」。

### R3-4 `ascendc-dev-knowledge/SKILL.md` 检索优先级

- **改动**：「检索优先级: evolution-knowledge guide.md → 本知识库按需 grep → WebSearch」改为「**`ascendc-api-best-practices`（API 用法/避坑）→ evolution-knowledge → 本知识库按需 grep → WebSearch**」（best-practices 在 API 查询时最前）。
- **验证**：SKILL.md 检索优先级链含 best-practices 在最前。

---

## R4 — 首稿纪律（补缺）

- **改动点**：`ascendc-op-dev-coding/SKILL.md` Step 4（分层编码）。
- **改动内容**：Step 4 开头加一条纪律——「**首动作按 `kernel_architecture.json` 文件清单 + 脚手架模板，一次性落全套文件骨架（允许有编译错误），再针对编译错误迭代；禁止先做大量 read/bash 调研而不落码**」。与现有「参考来源纪律」（禁自行搜罗）「落盘纪律」（每完成一文件立即落盘）衔接。
- **依据**：P3 silent-cut——coder 首轮 78 read + 55 bash + 0 Write，只调研不写码。现有纪律只禁「搜罗参考实现」，未禁「先长时调研不落码」。
- **验证**：coding SKILL.md Step 4 含首动作纪律；人工审查「首动作 = 落全套文件」表述无歧义。

---

## R10 — 读取纪律（补缺）

- **改动点**：`ascendc-op-general-design/SKILL.md` 输入章节 + `ascendc-op-dev-coding/SKILL.md` 输入/参考来源章节。
- **改动内容**：现有「输入路径清单 + 禁自行搜罗」基础上，补两条显式约束：
  1. **每个上游产物文件只读一次**（读后缓存，禁止重复 Read 同一路径）。
  2. **禁 `ls`/`cd`/`find` 目录侦查**——只操作输入表显式路径，不遍历目录发现文件。
- **依据**：P18——73 次 read 去重 31（重复 2.4×）、`ls/cd/find` 侦查 30 次。现有纪律禁「搜罗参考实现」，但未禁「重复读」和「目录侦查」。
- **验证**：design/coding SKILL.md 含「每文件读一次 + 禁 ls/cd/find」表述。

---

## 实施顺序与依赖

依赖链：**R3-1（api-gather.md）→ R3-2/R3-3/R3-4**（后三者引用前者的内容）。R4、R10 独立。

建议顺序：

1. **R3-1 新建 api-gather.md**（内容已设计好，直接落地）。
2. **R3-2 G01 补变体**（内容已设计好，直接落地）。
3. **R3-3 + R3-4 查询优先级调整**（依赖 R3-1 存在，改两处索引）。
4. **R4 首稿纪律补缺**（独立，小改）。
5. **R10 读取纪律补缺**（独立，小改）。

> 前置：`ascendc-api-best-practices` 需先从外部仓移植到本仓 `.claude/skills/`（R3 的移植动作）。若暂不移植，R3-3/R3-4 的「best-practices」引用会悬空——故移植是 R3 的第一步。
