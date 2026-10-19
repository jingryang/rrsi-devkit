# L3 补充 — 设计阶段中间产物访问范围与约束（authoritative）

> 本文件是「原地修」方案的前置契约，**修订并取代** `02-analysis.md` §2.1/§4 中「语义类 LLM 门就地 Edit」的表述（见 §7）。
> 关联 L1：`01-problems.md`（P1/P2/P4/P5）；框架机制：`StageIOContract`（`domain/contract.py`）、`_materialize_inputs`/`_read_disk_artifacts`（`design_substages.py` P62）。

---

## 0. 问题：为什么「原地修」必须先定访问契约

现状的产物隔离机制（P62）：

1. 每个 stage 有**独立 working_dir**（`artifacts/design/<name>/`，tiling 分支为 `design/tiling/<template>/`，anchor 分支为 `design/anchor/<template>/`）。
2. 框架把上游产物**物化（复制）**进下游 stage 的 working_dir（`_materialize_inputs`），下游读的是**副本**。
3. 下游只能写自己的 working_dir；`_read_disk_artifacts` 拒绝 working_dir 之外的产物（P62 不变式）。

**推论**：gate（anchor/review/validate）拿到的是 producer 产物的**副本**，它「改」只能改自己 working_dir 里的副本，**碰不到 producer 的原产物**。所以「原地修」不是字面上的"改原文件"，而是"**对副本做归一化，归一化结果作为新权威回流 State，覆盖 producer 原版**"——这需要一个明确的回流机制 + 严格的写权限边界，否则要么违反 P62 隔离，要么门替 producer 做设计决策（越权）。

---

## 1. 核心模型：按「修复是否唯一正确解」分层，而非按「发现」分层

「谁发现问题谁修改」的正确边界是**修复的性质**，不是发现的性质：

| 修复性质 | 定义 | 谁改 | 是否 loopback |
|---|---|---|---|
| **确定性归一化** | 修复是**唯一正确解**，可由确定性 checker 复算（不用 LLM 判断） | **checker**（在 producer commit 路径上机械应用） | 否 |
| **设计自由度** | 修复有多个可选解，需设计技能权衡（选哪种排序/buffer 布局/gather 是否分块） | **owner（producer）**，gate 只能 escalate | 是（architectural escalation，非 localized 重跑） |

**本批 AC2 抽样对照**（L1 P5）：

| finding | 修复 | 性质 |
|---|---|---|
| bf16 分数 Cast 到 fp16 有损 | 分数改 float（唯一升宽） | 确定性 → checker |
| int64 两趟 (低24,高32) 不保序 | 改三趟 (低24,中24,高8)（chunk ≤24 唯一约束） | 确定性 → checker |
| `SyncGrid` API 不存在 | 用 SetFlag/WaitFlag/…（多选） | 设计自由度 → escalate |
| 8 邻域 gather 建模为逐元素搬运 | 整块搬入+UB 内掩码 或 GatherMask（多选，需 UB 预算权衡） | 设计自由度 → escalate |
| 核数断言 A2=40 | 查 hw_params（唯一） | 确定性 → checker |

**结论**：只有「确定性归一化」才允许"谁发现谁改"；「设计自由度」必须回 owner——这不是无效 loopback，而是 owner 才有的设计所有权（§1.13 golden 权威、§2.9 构造性派生）。

---

## 2. 产物归属图（谁 owns 哪个文件）

| 产物（State 字段 / 文件） | **Owner（单一作者）** | 确定性归一化者 | 可读者 |
|---|---|---|---|
| requirement.json / golden.py | requirement（req-analysis） | 无（golden 权威，门不碰） | 全下游 |
| general_design.json | general-design-generator | general-design-review（CR1 字段补全、矛盾陈述改写） | template-division、tiling、validate |
| template_division.json | template-division | 无（上游，门不碰） | tiling、integrate、validate |
| tiling_split.json | tiling/split | anchor checker（核数/对齐/÷支持域） | anchor、integrate、validate |
| tiling_buffer_kernel.json | tiling/buffer-kernel | anchor checker（bf16→float、int64 趟数、API 存在性） | anchor、integrate、validate |
| tiling_precision_perf.json | tiling/precision-perf | anchor checker | anchor、integrate、validate |
| anchor_template_report.json | anchor-per-template | 无 | anchor-consistency |
| anchor_report.json | anchor-consistency | 无 | integrate、validate |
| design_spec.json / tiling_strategy.json | integrate | validate checker（GV1 字段缺失/GV5 格式/GV10-a 机械重写） | codegen、docgen、validate |

---

## 3. 读范围（每 stage 只读声明的 `requires`）

| Stage | 可读（声明 requires） | 禁读 |
|---|---|---|
| general-design-generator | requirement.json + golden.py + hw_params | — |
| general-design-review | requirement.json + general_design.json（**仅本门产品 + 权威上游**） | 不查 requirement 的 math 正确性（归 requirement 自检，R5 slice-7 已定） |
| template-division | general_design.json | — |
| tiling/*（split/buffer-kernel/precision-perf） | template_division.json + general_design.json + hw_params | — |
| anchor-per-template | 本模板 tiling_*.json + hw_params + API reference | 不跨模板读、不读 template-division |
| anchor-consistency | anchor_template_reports.json（per-template 报告） | 不跨读 template-division 等他人中间文件（R5 已定） |
| integrate | anchor_report.json + tiling_*.json + template_division.json | — |
| validate | design_spec.json + tiling_strategy.json + anchor_report.json + template_division.json | 不查 requirement（上游自检） |

---

## 4. 写范围（每 stage 只写声明的 `provides`）

| 角色 | 可写 |
|---|---|
| **Producer**（generator/template-division/tiling/integrate） | 自己的产物（commit 前经 checker 归一化） |
| **Gate（review/anchor/validate）** | ① 自己的 report（general_design_reviewed.json / anchor_template_report.json / anchor_report.json / blocking_status.json）；② **checker 归一化回流**（见 §5 约束） |
| **Checker（非 stage，commit 钩子）** | 对 producer 产物做**确定性归一化**，产出归一化副本 → 覆盖 State 原版 |

**归一化回流机制**（新）：checker 在 producer 的 `transition`（commit 路径）对产物做确定性归一化，归一化结果作为 `provides` 的新值写回 State 同名字段——**不产生新 stage、不产生新 working_dir、不产生新 State 字段**，只是把"原始产出"换成"归一化产出"。gate 读到的、下游消费的，都是归一化后的权威版本。

---

## 5. 约束（硬规则，逐条可验证）

1. **确定性归一化限定**：gate/checker 写 producer 产物，只能是"唯一正确解、checker 可复算"的归一化。判据：**这个改写能否由确定性代码复算（不经 LLM 判断）？** 能 → 允许；不能（多解、需设计权衡）→ 禁止，escalation。
2. **禁止代做设计决策**：gate 不得替 producer 选排序算法 / buffer 布局 / gather 分块策略。这些是 owner 的设计所有权，gate 只能 escalate（`blast_radius=architectural`）。
3. **可观测**：每次归一化必须记录——改哪个文件哪个字段、从什么值到什么值、依据哪个硬件/API 事实——写入该 gate 的 report 或 `decision_log.json`，**不静默改**（§1.2 可诊断）。
4. **schema 一致性**：归一化后产物必须仍满足 schema；checker 归一化后立即复跑校验（§1.3 加载期校验）。
5. **不越界读 + P62 不破**：gate 只读自己 scope 声明的产物；归一化只发生在 producer commit 路径，不产生 working_dir 外写；gate 的 working_dir 隔离不变。

---

## 6. 强制（加载期 + 运行期）

| 层 | 机制 | 内容 |
|---|---|---|
| **加载期（§1.3）** | gate_scope.json + IO contract 校验 | `self_fixable_scope` 必须是"确定性归一化"规则（可枚举的 checker 规则 id），**不得含设计决策**；`requires`/`provides` 与 §2-§4 归属图一致 |
| **运行期** | checker 归一化 + 复验 | producer commit 时 checker 跑；归一化后复跑校验；checker 无法复算的改动（=设计自由度）→ 拒绝并转 escalation |

---

## 7. 对 02-analysis.md 的修订

`02-analysis.md` §2.1 原文「AC2 语义类 → LLM 门就地 Edit」、§4「语义类 LLM 门就地 Edit 后由门自身复验」**作废**，统一修订为本文件的 §1 分层：

- 语义类 AC2 中，**修复唯一正确解的**（如 SyncGrid → 用存在的同步原语，但具体选型若有唯一约束）→ 归 checker；
- **修复多解、需设计权衡的**（gather 建模、UB 预算、排序算法选型）→ 一律 escalation 回 owner，gate **不**就地 Edit。

即：**「原地修」只由确定性 checker 承担；LLM gate 不再就地改 producer 产物**（避免"门替 producer 做设计决策"的越权，这是用户"交代清楚访问约束"的核心关切）。
