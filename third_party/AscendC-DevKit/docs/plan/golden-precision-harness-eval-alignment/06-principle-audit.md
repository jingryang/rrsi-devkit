# #3 改动原则审计（对 CLAUDE.md 基本原则逐条对照）

> 用户问「这次的修改已经完美符合工程中定义的那些基本原则了吗」。
> 诚实审计：**不完美**——发现并修正 3 处原则张力。记录如下，供后续改动借鉴。

## 审计对象
- `.claude/skills/ascendc-op-tiling-precision-perf/SKILL.md` 新增 R4（golden 算术等价性）
- `.claude/skills/ascendc-op-tiling-buffer-kernel/SKILL.md` 新增 R9（算术形式对齐 golden）
- 初版曾尝试在 `design_substages.py` 物化 requirement.json 进 tiling（已撤回）

## 发现的问题（逐条）

### 问题 A：R4 的 golden 算术来源在 skill 运行上下文不可得（§2.1 即插即用）
- **现象**：初版 R4 写「golden 算术来源 = requirement.json 的 golden_alignment → 设计公式段 →
  golden.py」，但 precision-perf skill 的声明输入只有 `template_division.json` /
  `tiling_current_template.json` / prompt，`_TilingSegmentStage._upstream_inputs` 也不含
  `requirement`——**引用取不到 → 检查永远落「未核对」→ 规则空转**。
- **原则**：§2.1 skill 即插即用；引用 skill 运行时拿不到的文件 = 违反。
- **修正**：golden 算术来源改为 **`general_design.json`（概设 narrative/公式段，tiling 段既有输入）**
  为主，requirement/golden.py 为可选次级。实证 resize_bilinear 概设 narrative 含公式/加权/插值。

### 问题 B：R4 的「否则改用 golden 同形」越权 + 「记录为阻断→交回环」无保证消费（§2.9）
- **现象**：初版 R4 写「否则改用 golden 同形」——但 precision-perf 的职责边界是
  「记录到自检结论，不直接修改前两段产物」，它改不了 buffer_kernel 的 Kernel 伪代码。
- **二次修正（用户追问「feedback 之后能保证被明确消费吗」）**：进一步核实发现——
  ① precision-perf 的 schema（`tiling_precision_perf.json` allowed_top_level）**不允许发
  路由 blocking_issue**（只有 self_check_summary），记录无法被下游确定性消费；② validate GV8
  的 target=tiling 回环是 validate 自己做、且比对设计公式（round-2 里设计文档把 lerp 也当合法
  公式写了），不消费 precision-perf 记录、也没拦下 lerp-vs-golden。
- **用户纠正（关键）**：「为什么要到 validate 阶段才发现？太迟了，命名（应该）很早就通过自检
  发现，validate 最多只是兜底。」——§2.9 的判据是问题在**书写处自检就地闭合**，不外推下游门。
- **修正（最终）**：
  - **buffer-kernel R9 是书写期主自检**：写 Kernel 伪代码时就取 `general_design.json` 的 golden
    算术、用 golden 同形分解或给目标 dtype 等价性证据，**发现问题就地修**——round-2 的 lerp-vs-golden
    应在此处被拦，而非 validate。
  - **precision-perf R4 是校验/第二道**：正常情况下 R9 已对齐，本步确认精度达成；若发现 R9 违约
    （异常），记录差异证据 + 标注「R9 违约」，**不假装自己能闭环、也不依赖 validate 作主发现点**。
  - **validate GV8 仅兜底**：不是主发现点。

### 问题 C：物化 requirement.json 进 tiling 是跨层跳（§1.1 分层架构）
- **现象**：为让 R4 拿到 golden 算术，初版在 `_TilingSegmentStage._upstream_inputs` 加了
  `requirement`，把 requirement.json（L1 需求层）直接物化进详设 tiling 工作目录。
- **原则**：§1.1 严格向下依赖，禁止跨层调用；tiling 应消费自然上游（概设/模板划分），不跳
  requirement 层。
- **修正**：撤回 requirement 物化；golden 算术改从 general_design.json 取（tiling 已有输入）。

## 逐条原则对照结果

| 原则 | 结论 | 说明 |
|---|---|---|
| §1.1 分层 | ✅（修正后） | R4/R9 取 general_design（自然上游），不跨层跳 |
| §1.2 方案合理性 | ✅ | 检查写/验分离：R9 书写期预防（可自修）+ R4 校验兜底 |
| §1.12 不耦合算子 | ✅ | 用结构语义（lerp 形 vs 加权和形），无算子点名 |
| §2.1 即插即用 | ✅（修正后） | golden 来源 = skill 既有输入；取不到显式标未核对 |
| §2.5 唯一通路 | ✅ | R4/R9 是新增规则，无冲突通路 |
| §2.8 workflow/知识分离 | ✅ | R4 是流程判据，golden 算术作为参考数据 |
| §2.9 自检闭环/门边界 | ✅（修正后） | R4 只记录不越权改；R9 书写处就地修 |
| §2.11 不耦合编号 | ✅ | 无问题/步骤编号引用 |
| §3.x 测试 | ✅ | skill 加载/自包含 141 过；tiling 子阶段 504 过 |

## 经验
1. **skill 引用的输入必须 = 该 skill 的实际运行上下文**（§2.1）——写规则前先核实 skill 声明输入
   与 `_upstream_inputs` 物化。
2. **职责边界先行**（§2.9）——写"否则就 X"前确认 X 在本 agent 职责内；不在则写"记录 + 交回环"。
3. **分层是硬约束**（§1.1）——某数据离得远，先问"它是否已在其自然上游被承载"，不要跳层物化。
4. **validate 是兜底不是主发现点**（§2.9，用户纠正）——问题应在**书写处自检就地闭合**（如算术形式
   在 buffer-kernel 写的时候就对齐 golden），不推到 validate 才发现；validate 最多拦漏网，不能当
   主机制。
