# L3 设计阶段数学声称验证 — 方案分析

> 对应 L1：`01-problems.md` D1/D2/C1/B1/T1。
> 用户决策（2026-08-09）：
>   ① 设计验证**通用**、覆盖面尽量广，但**不为通用牺牲正确性**；
>   ② 性能优化有专门 stage（暂未实现），目前**正确性优先 + 在正确性内尽可能好性能**；
>   ③ 先落文档，再走下一步。

---

## §0 三层防线总览（目标态）

| 层 | 防线 | 职责 | 归属原则 |
|---|---|---|---|
| 第一层 | **设计自检**（主防线） | 化简/降维/等价声称必须验证或显式标域限制；产物带 `support_domain` 结构化声明 | §1.2 / §1.3 / §1.13 / §2.9 构造性保证 |
| 第二层 | **codegen 域对质**（次防线） | 机械比较 `requirement(golden 域) ⊆ design.support_domain`，缺口 → 反馈 design | §2.9 正当跨 agent 对齐 + 可消费反馈 |
| 第三层 | **debug 兜底** | 域缺口识别 + `fallback_masked` 落地；禁止 host 兜底制造假绿 | §1.10 / §2.9 / B8 |

三层是**纵深防御**：主防线在设计闭合（构造性保证，§2.9），次防线兜设计漏网，第三层兜 codegen 也漏网的极端情况。每层都比上一层独立。

---

## D1 通用数学验证机制（用户决策①：通用、覆盖面广、不牺牲正确性）

**核心机制（用户洞察采纳）**：不是"预置验证脚本库"，而是**提示设计 LLM 在设计时主动用 Python 操作化并验证声称**——把"任意 perm 降维为 2D"这类 prose 声称变成可运行代码，跑通=有证据、跑不通=必须自洽。这是**概率性提升**（LLM 写的 Python 本身可能错，transpose 首次 pairwise-swaps 版本实测 63/100 失败），但有杠杆压住不可靠（见下）。

**设计目标**：任何"化简/降维/等价/复用/覆盖"声称都必须经过验证或显式标域限制；机制覆盖多种声称类型，但**"验不了"时宁标域限制、绝不假装覆盖**。

**验证方法分层（覆盖面广 = 适配多种声称类型）**：

| 声称类型 | 示例 | 验证方法 | 工具 |
|---|---|---|---|
| 可穷举 | perm 类型学、rank≤5 置换分类 | 穷举全空间（确定性） | `verify_simplification_claim.py` 模板 |
| 可形式化 | 降维等价、reshape 等价、shape 公式 | 代数/集合推导（支持域 = 显式集合） | 形式化声明 + 推导 |
| 可原型 | 地址映射、dtype 转换、broadcast 等价 | numpy/torch **对照 golden** 随机核验 | Python 原型模板 |
| 可引用 | 已核验事实库（循环旋转=n 个等） | 引用参考文献 + 标注核验日期 | `references/design-math-claims/` 事实库 |
| 不可验证 | 性能估计、启发式 | **显式标"未验证 + 域限制"** | 禁止伪装覆盖 |

**概率性可靠性的五根杠杆（把"LLM 写的 Python 可能错"压到可控）**：
1. **ground truth = golden**：验证脚本必须对照 golden 函数（transpose=`np.transpose`）比，裁判是 golden 不是 LLM 脑补的期望——golden 不会撒谎，域缺口藏不住（§1.13）。
2. **模板骨架已知正确，LLM 只填算子特定逻辑**：`verify_simplification_claim.py` 给"生成输入→调 golden→对比→出报告"骨架（骨架本身 UT 守护，L4 V1），缩小 LLM 错误表面积。
3. **能穷举就穷举**：小参数空间（rank≤5）全枚举，确定性；大空间才随机抽样。
4. **记录验证方法 + 残余风险**：产物写清"验证了什么（穷举/随机 N/引用）"，残余风险进 `known_limitations`——**不把"跑过 Python"冒充"已证明"**。
5. **fail-loud 优于静默**：脚本断言不通过即失败，触发声称/测试二选一自洽，绝不静默通过。

**验证失败不 halt（用户洞察采纳）：概率性 aid 不是 gate**。设计验证脚本跑不通 / 无法运行 / 声称被证伪，**一律不 halt**，处理路径：
- **先本 agent 自修（§2.9 自检闭环，用户明确）**：脚本跑不通（LLM 代码 bug / 环境缺库）→ agent 先**内部多轮增量修正**（改脚本→重跑→再改），修到能跑为止；"跑不通"的定义 = **多次内部尝试后仍跑不通**，不是一次机会。
- 自修后仍跑不通 → 标 `known_limitations`（reason=验证不可运行）+ `support_domain`（声明域，哪怕未验证）→ **继续进入 codegen/debug**。
- 声称被证伪（脚本断言不过）→ 设计就地修正声称或显式标域限制 → **仍不 halt**，修正后继续。
- 仅当问题**真正不可解且需上游裁决**（需求/golden 歧义、算法不可行需人决策）才走既有 `resolve_ambiguity` / `blocking_issues target=human` 通道。

理由：①§2.9 禁止 discover+regenerate——验证失败阻塞 = 只报问题、解决靠重跑设计；②§1.2 可诊断——问题是"未验证"，应显式携带而非静默或硬拦；③三层防线——设计这层挂，codegen 域对质 / debug fallback_masked / 评测反作弊仍是独立的更硬的网。**"带问题前进"的前提是问题被显式携带**（结构化 `known_limitations` 让下游真的读到），不是悄悄滑过——transpose 现状（tiling 作者打无人消费的 WARN）就是反面。

**不牺牲正确性的兜底（关键判据）**：声称的**支持域 ⊇ 需求(golden)域**是硬要求；不满足或未验证 → 设计产物必须显式标注域限制（`support_domain` 与 `known_limitations` 并列），由 codegen 域对质（D2/C1）决定是否放行。**"未验证"不等于"域限制"，只有显式声明才算数**——这是"宁标限制不伪装覆盖"的机械落地。

**架构（§2.7/§1.12）**：**机制**（提示 LLM 验证 + 模板 + 检查清单）是 op 无关的 skill 内容；**实例**（每个算子的验证脚本）是设计时产物，可归档进 verified_facts 库复用——二者分离，不把具体算子写进 skill 流程锚点。

**改动落点**：
- 新增 references 资源 `ascendc-op-design-shared/references/design-math-claims/`（或通用 shared）：
  - `claim-verification-checklist.md`：声称类型 → 验证方法 → 自检判据；
  - `verify_simplification_claim.py` 通用模板（已知正确骨架：生成输入→调 golden→对比→报告；LLM 只填声称逻辑）；
  - `verified_facts.md`：已核验数学事实库（首批：transpose perm 分类；后续算子验证结果持续沉淀）。
- `ascendc-op-general-design` / `-template-division` SKILL.md 自检表新增项："化简/降维/等价声称 → **优先写并运行 Python 验证（对照 golden）**，仅在不可运行时用引用事实或显式标域限制；禁止裸描述、禁止把'跑过'当'已证明'"。
- **不扩展 anchor**（实施期收敛，§2.9 门边界）：`ascendc-op-design-anchor-per-template` 保持硬件可行性对质（`hardware_api_capability`/`repo_convention`），**不**加 `math_feasibility`/`domain_coverage` claim_type。理由：①anchor 是对"硬件 API 能力"做独立对质（破自评自证），数学/域验证的外部真相 = golden + 穷举 Python，可由设计 agent 确定性验证，独立性需求低；②一个门混两条验证轴，且 anchor 无 golden/verified_facts 上下文，硬加会越界查上游（§2.9）。域验证由**设计自检（主）+ codegen 域对质（机械次防线）**覆盖，anchor 不参与。

**通用 vs 正确性的取舍**（用户决策①）：机制层面**通用**（声称必验 + 主动提示 LLM 验证），执行层面**分层**（穷举/形式化/原型/引用/标限制五档）——覆盖面广由"适配多种声称类型 + LLM 现场写验证"体现，不牺牲正确性由"golden 锚定 + 记录验证方法与残余风险 + 验不了必标域限制"兜底。不为追求通用而把不可验证的声称硬算作已验证。

## D2 支持域声明（结构化，§2.10）

- `design_spec` 新增结构化字段：`support_domain`（声称支持的输入域，集合形式）+ `known_limitations`（未覆盖/未验证部分）。
- transpose 目标态：`support_domain = {perm: len(perm)∈[1,8], perm 是 [0..n-1] 排列}`（= golden 全域）；`known_limitations = {}`。
- 机器可消费（§2.10）：下游 codegen 对质直接读字段，不读 prose。

## C1 codegen 域对质（次防线，§2.9 正当性）—— 已实施（非 halt 结构化信号）

- **结构化域词汇表**：requirement.json `domain` + design_spec `support_domain` 共享（rank/dtypes/attrs[].domain{kind,constraint}），经 `ATTR_DOMAIN_COVERAGE` 可扩展（§1.12 结构信号不认算子名）。
- **引擎**：`domain/support_domain.py::domain_covers` 机械判定 `golden 域 ⊆ support_domain`（rank/dtype/attr 三轴）。
- **接入**：`codegen.py::_emit_domain_gap_signal`（物化后、spawn 前）——缺口 → `Logger.warn` + `staging/domain_gap_signal.json`（结构化信号）→ **不 halt、不 feedback loopback**。
- **收敛说明**（相对初版"缺口→反馈 design loopback"）：域对质定位为**声明级安全网**——防"声称任意 perm 实为循环旋转"这类设计声明错误；实际域外失败仍由 debug（scope_guard 对域外 case 识别设计缺口）/ eval 兜底。**不做 codegen→design 无界 loopback**（§2.9 不引入 discover+regenerate 空转）；问题显式携带（信号文件），debug 侧消费。
- transpose 示例：需求 `perm:any`，设计 `support_domain.perm:cyclic_rotation` → 引擎机械抓出 gap 信号。

## B1 debug 兜底（第三层，B8 落地点）

- `fallback_masked` 落地：fix/printf 用 host 兜底（`x.cpu()`/CPU 计算/绕过 kernel）必须标 `fallback_masked=true`；scope_guard 判定表加"**host 兜底通过 → 上游设计缺口**"行；报告区分"kernel 真通过"vs"host 兜底通过"。
- debug 把"kernel 支持域外"失败识别为**设计覆盖缺口**（走反馈通道回 design），**禁止**插件 host 兜底制造假绿（605af87 反面教材）。
- §1.10：`fallback_masked` 是显式业务声明（"这次通过靠 host 兜底"），不用机制特征代理。

## T1 transpose 落地（用户决策②：正确性优先 + 尽可能好性能）

**实现方向选型**：
| | 算法①两两换维分解 | 算法②通用 N-D index 映射 |
|---|---|---|
| 正确性 | ✅ 已核验（≤n-1 pass） | ✅ 已核验（单 pass） |
| 性能 | 多 pass，每 pass 全 tensor 读写 | **单 pass**，直接 strided 读写 |
| tiling 复杂度 | 复用 2D 转置思路，较简单 | 更复杂（N-D strided tile） |

**拍板：算法②为主方向**。理由：用户决策②"正确性优先 + 在正确性内尽可能好性能"——算法②正确性已核验（=golden 定义），且单 pass 性能天然优于多 pass；性能优化 stage 未实现，但算法②在不牺牲正确性的前提下就给出更好性能，符合"尽可能好"。算法①保留为 fallback（若②的 tiling 复杂度过高导致实现风险，先①正确后换②）。
**落地内容**：设计补 `support_domain=全部 perm`，kernel/tiling 实现通用 N-D 转置（算法②），删插件 host 兜底，8 个 case 真跑 NPU → 反作弊解除。详细 tiling 属设计工作，按新验证要求产出。

---

## 四把尺子（§1.2）

| 尺子 | 评估 |
|---|---|
| 可维护 | 验证机制收敛到 references 单一资源 + 自检项，无散落特判；`support_domain` 单一字段 |
| 可扩展 | 新声称类型 → 加验证方法档位/事实库条目，不动流程骨架 |
| 可诊断 | 声称未验证 → 显式 known_limitations（可观测）；域缺口 → codegen 反馈信号；host 兜底 → fallback_masked |
| 架构合理 | 主修在设计自检（构造性保证），codegen/debug 只做对质/兜底，不越层补数学 |

## 原则符合性

| 原则 | 落实点 |
|---|---|
| §1.2 | 三层防线四把尺子过；主修在设计，codegen/debug 兜底不越层 |
| §1.3 | 数学声称设计时（加载期）验证，不等运行期暴露 |
| §1.13 | golden 域为锚；golden 域 ⊄ 设计域 = 设计缺陷，显式信号不归工程兜 |
| §2.9 | 设计自检=构造性保证；codegen 对质=正当跨 agent 对齐+可消费反馈；debug 不 patch 假绿 |
| §2.5 | `fallback_masked` 作为"host 兜底"唯一信号通路；验证资源单一来源 |
| §1.10 | 域/兜底用显式声明，不用机制特征 |
| §2.10 | `support_domain`/`known_limitations` 结构化字段机器可消费 |
| §1.12 | perm 类型学、域包含判定是结构信号，不认算子名 |

## 决策汇总

| 项 | 拍板 | 依据 |
|---|---|---|
| 验证机制 | 通用五档（穷举/形式化/原型/引用/标限制），声称必验、验不了必标域限制 | 决策① |
| 设计自检 | 主防线：自检项 + `support_domain` 字段 + references 模板库 | §2.9 构造性保证 |
| codegen | 域对质：golden 域 ⊆ support_domain，缺口反馈 design | §2.9 跨 agent 对齐 |
| debug | fallback_masked 落地 + 域缺口识别 | B8 / §1.10 |
| transpose 实现 | 算法②（通用 N-D 单 pass）主，算法① fallback | 决策②：正确性优先+尽可能好性能 |
| 实施顺序 | 先落文档（本次）→ 用户确认 → 按 L4 实施 | 决策③ |
