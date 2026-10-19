# step-64 — general_design.json 契约拍平 — 方案分析（第三层）

> L1 见 `06-problems.md` P87。已实施。

## 0. 核心判断

- **不是文档漂移，是 schema 结构本身有盲区**：`general_design.json` 是全仓 15 个 skill schema 里唯一把承载内容包在非顶层 `sections` 容器内的违例。`validate_payload`（`domain/artifact.py:64-94`）只校验顶层 key 是否存在，无嵌套/点路径校验——CR1 四字段（切分轴优先级 / TilingData / 循环框架 / Buffer 评估）被包在 `sections` 内，从未被 schema 真正强制（`required_keys` 改前是 `["op_name","sections"]`，强制的只有 `sections` 容器本身存在与否，内部四字段全靠 agent 自觉）。
- 与 P86（方案63）的区别：P86 是文档名漂移、零行为变化；P87 是 `required_keys` 变严格（4 字段从未强制→现在强制），存在"agent 按新 SKILL.md 产出拍平结构"这一真实链路需验证，故沿用既有 design pipeline heavy_llm e2e 重跑（非新增）。
- **拍平零工程代码改动**：validator 已正确处理顶层 key，改 schema + 两份 SKILL.md 即可，`GeneralDesignStage`/`GeneralDesignReviewStage` 代码零改动。

## 1. 方向对比（CLAUDE.md §1.2 四原则）

用户追问"为什么不能像详设那样直接校验 JSON、markdown 只做人读产物"，促成本次对两方向的四原则对比：

| 维度 | 方向 A：把 markdown 章节整体译入 JSON `sections` | 方向 B：JSON 拍平为唯一机器契约，markdown/叙述降为 JSON 内可选 `narrative` |
|---|---|---|
| 可维护 | 差——两套表达源（文本骨架 + JSON schema）需同步 | 优——单一结构化源 |
| 可扩展 | 差——新章节要同时改文本骨架 + JSON schema | 优——加顶层字段即可 |
| 可诊断 | 差——agent 可能只改一边，漂移不可见 | 优——单一权威 |
| 架构合理 | 差——SKILL 越权定义工程从不消费的中间形态 | 优——与 docgen 的 `design_doc` 先例同构 |

**结论（用户拍板"按你的建议做"）**：方向 B，四原则皆优。

## 2. narrative 字段设计取舍

为何不仿 docgen 的 `design_doc`（`state.py:191`）另设一个独立 State 字段 + 物化机制？

- docgen 的 `design_doc` 是**终态人读交付物**，有独立的下游消费者（写 markdown 文件、被人读）。
- general-design 自身的 markdown/叙述内容**无独立下游代码消费者**——review 的 CR3 扫描"详设独有设计点"只需能在 JSON 里读到文本即可，不需一个独立的 .md 文件。
- 故叙述内容降级为 `general_design.json` 内一个**可选顶层 `narrative` 字符串字段**（内嵌），复用现有 `_upstream_inputs`/materialize 管线，不新增 State 字段、不新增文件物化机制。CR3 扫描 `narrative` 即可。

## 3. 字段落点映射（SKILL.md 重写依据）

CR1 四强依赖字段 → 顶层 `required_keys`：
- 步骤 7.4 并行分解策略·多核切分轴优先级 → `split_axis_priority`（数组）
- 步骤 8.2 TilingData 字段定义 → `tiling_data`（数组）
- 步骤 8.3 各模板循环结构 → `loop_framework`（字符串）
- 步骤 9.1 Buffer 可行性评估 → `buffer_eval`（对象）

CR2 条件性字段 → 顶层可选：
- 归一化层反向传播梯度公式 → `gradient_formula`（字符串，存在时 CR2 检查）

CR3 扫描源 + 其余人读内容 → 顶层可选 `narrative`（字符串）：算法背景/算子定义素材/计算流程/数据流拓扑/轴分析/模板划分/差分分析/Tiling 级数/对齐策略/性能权衡/瓶颈分析/可行性论证/附录。

> 易混点澄清：步骤 3.5 写入 `narrative` 的「设计路径分类（路径一/差分/路径二）」≠ review CR3 的 `general_design_level`（真概设/偏详设/完整详设）。前者由 generator 写、描述模板复用来源；后者由 review 判、描述概设详细度丰俭。两者落不同位置（前者 narrative 内文案，后者 review 自身输出 `review_summary.cr3`）。

## 4. review SKILL.md 的"覆写文档"步骤简化

旧步骤 5"汇总结果并覆写概设文档"含两动作：(a) 写回步骤 2~3 就地修改，(b) 文档顶部插入审查摘要 blockquote。

新模型下：
- (a) 就地修改在步骤 2/3 已通过 Edit 直接落盘各字段（持久化），无需额外"写回"。
- (b) 审查摘要（CR1~CR3 判定 + 分级 + 计数）已完整记在 review 自身输出产物 `general_design_reviewed.json` 的 `review_summary` 中，回写进被评审产物是冗余 → **取消摘要块插入**。

可审计性由 `patched_nodes[]`（既有输出字段）承载，不再需行内文字批注（`[由 general-design-review 自动补入]` 这类标注废弃）。

## 5. 不做的（避免误伤）

- 不改 `domain/artifact.py`（validator 已正确处理顶层 key，零改动）。
- 不改 `design_substages.py` 两 stage 类（JSON-only 透传，零字段读取）。
- 不改 `state.py`（不仿 `design_doc` 设独立字段——`narrative` 内嵌进 JSON 即可）。
- 不动 `_materialize_extra`（用户提供既有概设 `existing_general_design.md` 的输入侧机制，是输入灵活性，与输出格式修正无关）。
- 不改 CR1/CR2/CR3 判定方法论、blocking_issues 的 target 路由规则（generator/requirement/human）——只改"读写介质"，不改判断逻辑。
