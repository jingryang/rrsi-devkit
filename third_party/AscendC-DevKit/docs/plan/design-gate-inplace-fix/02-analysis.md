# L3 — 设计阶段质量门：从「只读对质 + loopback」改为「就地修 + 确定性校验」

> 关联 L1：`01-problems.md`（P1–P5）
> 关联既有分析：`../batch-20260813-timing-analysis/02-analysis.md`（R5/R6）——本方案**取代** R6「anchor 定向回炉」的方向：R6 只把「全量重跑」降为「定向重跑」，仍保留 loopback 判断点；本方案进一步把「loopback」降为「就地修」，只在 architectural 重设计时保留 escalation。
> 本文件记录选项、取舍与决策，拍板后冻结（§1.8 L3 边界）。

---

## 0. 决策摘要

**设计阶段三个质量门（general-design-review / anchor / validate）一律「就地修」，删除全部 corrective loopback（`fix_owner` 路由），只保留两类出口：**

1. **就地修（self_fixable）**：发现即改。确定性可查的用**确定性 checker**（查硬件 API 事实表 + 算术校验），语义类的由门 agent **就地 Edit**（不再只读）。
2. **升级（escalation）**：只有 `blast_radius=architectural`（整条 tiling 策略 / 概念设计需重做）才路由回 producer 或 requirement——这是「设计自由度」缺陷，门不具备重做设计的能力，非 loopback。

**一句话**：把「loopback」这个单一原语拆成三态——确定性就地修 / LLM 就地修 / architectural 升级——前两态都**没有回炉**。

---

## 1. 选项对比

| 选项 | 描述 | 判断点数量 | 空转风险 | 复验 | 结论 |
|---|---|---|---|---|---|
| **A 现状（R6 定向 loopback）** | anchor 报 issue → 按 target_template 定向重跑 tiling | 2（发现 + 判断回哪个段） | 判错段 = 空转（P3） | 断（P1 branch 命名 bug） | ❌ 已证明无效 |
| **B 全量就地修** | 门发现即改产物，永不 loopback | 1（发现） | 最低 | 无独立复验（但门自检） | ⚠️ 编辑一致性风险 |
| **C 确定性 checker + 就地修（本方案）** | 可查表的用 checker 机械校验+修复；语义类的 LLM 门就地 Edit；architectural 才 escalation | 1 | 最低 | checker 复跑 = 确定性复验 | ✅ 选中 |

**选 C 的理由**：

1. **判断点最少**（用户核心关切：多算子泛化下，每多一个判断点就多一类空转）。A 有两个判断点（发现 + 回哪个段），C 只有一个（发现即改自己 flag 的那处）。
2. **「独立对质」本批实证无价值**（L1 P5）：anchor 的价值在「发现」（硬件 API 可行性知识），不在「只读」；只读 + loopback 这一半是负价值（P1 无复验 + P3 重跑贵/脆弱）。
3. **codegen 已经示范了正确姿势**：`workflow.py` codegen 无 transition table 条目——manifest 非契约走「构造性派生 + 机械校验 + 定向 retry」，不 loopback。设计门应与 codegen 对齐同一模式（§2.5 唯一通路、§2.9 构造性保证优先）。
4. **框架已有「就地修」一等概念**：`gate_scope.json` 的 `self_fixable_scope` + `stop_in_stage_retry` 已是现成机制，无需新建控制流，只需**重配置**三个门的 scope + 补 checker。

**B 的编辑一致性风险如何消解**：C 里 checker 复跑是确定性复验（改完再查同一张表），语义类 LLM 就地 Edit 后由门自身 `is_satisfied`（无残留 issue）判定 + 下游 integrate 消费已知问题兜底。B 的「改一处要连带改相邻 claim/伪代码/缓冲表」风险，C 用「checker 校验的是产物整体一致性」而非「只校验被改的那一处」来覆盖。

---

## 2. 端到端改动清单（覆盖所有阶段，不遗漏）

### 2.1 三个质量门（核心）

| 门 | 现状（gate_scope self_fixable / fix_owner） | 改动 |
|---|---|---|
| **general-design-review** | GD-G*→generator；CR1/CR2/CR3 就地修 | GD-G* 的「产物不全/自相矛盾」改为**就地修**（确定性可修：字段缺失补全、矛盾陈述改写）；仅 GD-CR2 math 素材缺失→requirement escalation；`redo_generator` 边删除 |
| **anchor-per-template** | `self_fixable_scope: 无`；AC0/1/2→tiling | 扩 self_fixable：AC2 且 `blast_radius=localized` 的**确定性**类（bf16 指数宽度 / int64 chunk 宽度 / API 存在性 / 整数除法÷支持域 / hw_params 查表）→ checker 就地校验+修复；AC2 语义类 → LLM 门就地 Edit；`default_max_iterations` 1→N（允许 Edit→复验） |
| **anchor-consistency** | 只汇总，AC2→tiling | 只汇总 + advisory（不再 loopback）；AC2 已由 per-template 原地修，consistency 只做聚合与 AC3 跨模板 advisory |
| **validate** | GV10-a/GV5 就地修；GV1-9+AC0-2→tiling | 扩 self_fixable：GV1 字段缺失 / GV5 格式 / GV7-B 伪代码错（公式权威已自检）/ GV10-a 机械重写 → 就地修；仅「需 tiling 技能重做算法/切分」的 architectural 才回 tiling；`redo_tiling` 边收紧为 architectural-only |

### 2.2 框架代码

- `design_tree.py`：
  - `_GENERAL_DESIGN_TRANSITION_TABLE` 删 `redo_generator`（保留 `design_input_invalid→requirement` escalation）。
  - `_DETAILED_DESIGN_TRANSITION_TABLE`：`infeasible→tiling` 收紧为仅 `architectural`；`validate` 的 `redo_tiling` 收紧为 architectural-only。
  - `_anchor_branch_factory` 修 branch 命名（P1）：`AtomicStage(AnchorPerTemplateStage(template=t), name=...)`（AtomicStage 需加 name override 参数，或包 `SequentialGroup(name=name)`，对齐 tiling_branch_factory）。
- `design_substages.py`：各 gate 的 `_raw_blocking_issues`/`resolve_condition`/`is_satisfied` 改口径——self_fixable 类不再进 `blocking_issues`（就地修后 issue 消失），只有 escalation 类进 routing。
- `graph_executor.py`：corrective loopback 机制**保留**（precision_debug / perf 的 escalation+validation 仍用），design 组不再产生 corrective 边。stagnation/fail-open 逻辑不动。

### 2.3 确定性 checker（新增，非 LLM）

- 位置：`src/ascendc_devkit/orchestration/design_checks.py`（或 `domain/`），单一入口，加载期校验（§1.3）。
- 覆盖类（本批 AC2 抽样，L1 P5）：bf16 指数域宽度、int64 chunk ≤24 位、API 存在性（SyncGrid 等）、整数除法÷支持域（cTile/8 对 C=7）、hw_params 核数/核对齐查表。**约 4-6/8 可确定性覆盖**。
- 语义类（DataCopyPad 单元素搬运语义、dstStride 布局断言、gather 范围 UB 预算）→ 仍 LLM，但改为「门就地 Edit」而非「报告回炉」。
- 与 R3（API 知识前置）分工：R3 让 design agent 产出时避开，checker 拦 R3 漏网；二者同源（都是「不知道 API 约束」），R3 治源头、checker 治残留。

### 2.4 下游消费一致性（端到端）

- `integrate`：现消费 `anchor_report` 的 `blocked` status + blocking_issues。改为消费「checker/门 修复后的产物 + design_known_issues（残留 advisory）」，不再有 blocked→loopback 语义。
- `codegen` / `codegen_init`：不变——原地产物 schema 由 checker 保证；但需回归验证「就地修后的 design_spec/tiling_strategy 能正常进 codegen」。
- `precision_debug/scope_guard`：不变——仍兜底 golden/schema/注册失败等上游缺陷；设计门就地修后上游缺陷变少，但 scope_guard 的兜底边界不能删。

### 2.5 Skills（3 门 + feedback-selfcheck）

| skill | 改动 |
|---|---|
| `ascendc-op-general-design-review` | SKILL.md + gate_scope：GD-G* 从「报告不可修」改「确定性可修就地 Edit」 |
| `ascendc-op-design-anchor-per-template` | SKILL.md + gate_scope：从「只读对质」改「校验→就地修→复验」；确定性类交给 checker，语义类就地 Edit |
| `ascendc-op-design-anchor-consistency` | SKILL.md：删「汇总后 loopback」语义，只聚合 + advisory |
| `ascendc-op-design-validate` | SKILL.md + gate_scope：扩 self_fixable，architectural 才回 tiling |
| `ascendc-op-design-feedback-selfcheck` | 若 loopback 删除后无消费者，按 §2.5 唯一通路删除；否则保留为「复验自检」 |

### 2.6 测试（§3 全覆盖）

- **UT**：transition table 无 design corrective 边（assert）；checker 对每类确定性约束正确校验/修复（含反例）；branch 命名后 rerun_selector 命中。
- **ST**：端到端 design 流程零 loopback——用会触发 AC2 的算子（如 grid_sampler_3d 的 gather 建模、unique 的 int64 排序）验证「门就地修 + 产物可进 codegen」，断言 events.jsonl 无 design 组 loopback 事件。
- **回归**：既有 R5（删越界门）196 UT、R6（rerun_selector）UT 不回归。

---

## 3. 端到端完成判据（「修改完成」的定义）

1. `design_tree.py` 三个 transition table 中，design 组**不再存在任何 `fix_owner` corrective 边**（grep 断言 `redo_generator`/`infeasible→tiling`/`redo_tiling` 均删除或收窄为 architectural-only）。
2. 三个 gate_scope.json 的 `self_fixable_scope` 已扩展，`fix_owner` 路由只剩 architectural/escalation。
3. 确定性 checker 落地且覆盖类清单在加载期可枚举（§1.3）。
4. 三个门 skill 的「就地修」判据与 gate_scope 一致（无 skill/代码两套口径，对齐 L1 P2 的 R5 教训——代码改了 skill 没跟上）。
5. events.jsonl 实证：跑一批（含会触发 AC2 的算子）设计阶段**零 loopback 事件**，且产物能进 codegen。
6. 全量 UT + 非 heavy_llm ST 通过；`pytest` 预检 LLM/NPU/CANN 可达性（§3.6）。

---

## 4. 风险与取舍

| 风险 | 消解 |
|---|---|
| 门就地修可能改错（编辑一致性） | checker 复跑 + `is_satisfied` 无残留 issue + 下游 integrate 消费 known_issues 兜底；语义类 LLM 门 Edit 后由门自身复验 |
| 语义类 AC2 门修不了（需设计技能重做） | 明确 `blast_radius=architectural` → escalation（保留唯一 loopback，且属「设计自由度」缺陷，非无效回炉） |
| 确定性 checker 覆盖不全 | 诚实记录覆盖边界（§4 约 50-70%），语义类退化为 LLM 就地修，不硬凑确定性 |
| 「独立对质」消失，谁复核门自身 | 门的价值本就在「发现」（硬件事实），不在「只读」；checker 是客观复核，比 LLM 第二双眼睛更可靠（不会读过期证据） |

---

## 5. 与既有方案的关系（不重复、不冲突）

- **取代 R6**（anchor 定向回炉）：R6 只降「全量→定向」，本方案进一步「定向→就地」。
- **延续 R5**（删越界门）：R5 已把 AC3（证据缺失）回炉彻底消灭；本方案把 AC2（真实设计错误）的回炉也从「重跑」降为「就地修」，是 R5 同一 §2.9 原则在 AC2 上的延伸。
- **独立于 R1/R3/R4**（codegen 时间黑洞根治）：本方案只动设计门，不碰 codegen 的「机械试错」根治（那是 R3+R4 的事）。
