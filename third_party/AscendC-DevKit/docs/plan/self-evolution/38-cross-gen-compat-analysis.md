# P65 — 跨代 chip 兼容矩阵：从「代际严格相等」改为「编程模型兼容」 — 方案分析（第三层）

> 层级：**第三层 / 方案分析**。有哪些选项、选了哪个、为什么。调研中演进、拍板后冻结。
> 依据：L1 `06-problems.md` P65（客观事实）；落地为 L4 `38-cross-gen-compat-impl.md`。

---

## 0. 问题陈述（引用 L1，不重复产权）

用户要在当前 **A5 真机**上验证 **A2 Membase codegen**。域层面这是合法的**向前兼容**（A5 硬件支持 Membase，能编译运行 A2/A3 的 Membase 代码），但仓内三处 chip 判定**全部用「代际严格相等」**，把合法的向前兼容当硬阻塞拦掉：

- `adapters/npu/detect.py::chip_mismatch_reason`：`if design == runtime: return None`（被 codegen.validate_inputs PRIMARY gate + Deployer.deploy SECONDARY gate 共用）
- `orchestration/stages/design_substages.py::_cross_generation_gate_fires`：`if design == runtime: return False`（design 前跨代确认软门）
- `codegen.py` / `deploy.py`：`soc_version = to_soc_version(design)` —— 编译目标挂在 design 上

衍生：软门「改打本机」选项把 design 改成 A5 → codegen 产出 **Regbase** 代码，篡改用户要的 Membase 风格。

---

## 1. 兼容性模型（权威定义）

兼容是**非对称**的，由**编程模型**决定，非代际码相等：

| 编程模型 | 代际 | runtime 可运行于 |
|---|---|---|
| Membase（传统 AscendC SIMD Vector） | A2 / A3 | A2、A3、A5（A5 向后兼容 Membase） |
| Regbase（VF 入口 + RegTensor） | A5 | 仅 A5 |

→ 兼容判定 = `chip_programming_model(design) ∈ _RUNTIME_SUPPORTED_MODELS[runtime]`

兼容矩阵（design ↓ \ runtime →）：

| | A2 | A3 | A5 |
|---|---|---|---|
| **A2** (Membase) | ✓ | ✓ | ✓ |
| **A3** (Membase) | ✓ | ✓ | ✓ |
| **A5** (Regbase) | ✗ halt | ✗ halt | ✓ |

**唯一硬阻塞**：design=A5(Regbase) + runtime∈{A2,A3}。

> 方向性（易错点）：design 低代际 → runtime 高代际 = **兼容**（runtime 向后支持 Membase）；反向（A5 design → A2/A3）= **不兼容**。`design∈{A2,A3} + runtime=A5` 是兼容，原 UT 把它判「不匹配」须**反转**。

### 解耦：design 定代码风格，runtime 定编译目标

- `programming_model` ← **design** chip（固定代码风格：Membase 走路径二、Regbase 走路径三）
- `chip_code` / `soc_version` ← **runtime** chip（编译目标 = 真机；design 回退当 runtime 未设）

如此兼容模式下：A5 真机验证 A2 Membase codegen → `programming_model="A2 Membase"`（风格不变），`chip_code="A5"` / `soc_version="ascend950"`（为本机编译）。

---

## 2. programming_model 归属：为何上移到 domain（反转既定决策）

**既有决策**（codegen.py 旧注释）：「programming_model is a codegen-path concept so its derivation lives here, not in chip.py」。

**反转理由**：兼容矩阵需被**三层共享**——adapter（detect）+ orchestration（design_substages）+ codegen。若 programming_model 派生留 codegen 私有：
- detect（adapter 层）拿不到 → 只能继续用严格相等（缺陷不灭）
- 或 detect 反向依赖 codegen（违反 L1→L7 分层、跨层调用）

二者均不可接受。programming_model 是**芯片代际的固有属性**（A2/A3 固有 Membase、A5 固有 Regbase），属 domain 身份范畴，本就该在 chip.py。§2.5 唯一通路：消灭三处私有的严格相等/编程模型副本，收敛 domain 单一源。§1.4 不留过渡层，直接改干净。

domain 返回**纯模型名**（`MEMBASE`/`REGBASE`），skill 契约字面量 `"{chip} {model}"`（如 `"A5 Regbase"`）的拼装留 codegen——分层：domain 不知 skill 契约格式。

---

## 3. 选项

### 选项 A：domain 兼容矩阵 + 三 gate 改矩阵 + soc_version runtime 双源（**选定**）

- `domain/chip.py` 新增 `chip_programming_model` + `runtime_supports_design`（单一源）
- 三处 gate（detect / design_substages）改调 `runtime_supports_design(design, runtime)`
- codegen/deploy 的 soc_version 改 **runtime 优先、design 回退**
- meta.json 拆双源（programming_model←design，chip_code/soc_version←runtime）
- 反转/新增 UT：兼容组合 → None/通过 gate；真不兼容（A5→A2/A3）→ 保留阻断

满足四把尺子：① 可维护（维持「domain 单一源」不变式，§1.9/§2.5）；② 可扩展（新增代际只需补两张映射表，gate 自动正确归位）；③ 可诊断（runtime 未知→False→「无法校验」分支，区分「不兼容」与「未知」，§3.7）；④ 架构合理（矩阵落 domain 身份层，gate 各守其位，不越层兜底）。

### 选项 B：仅放宽 detect gate，design_substages/codegen 不动

- **否决**：detect 是 build gate，design_substages 是 design 前软门，codegen meta.json 是 skill 契约源——三处各自持有判定/soc_version 副本。只改一处 = 留两处严格相等 = 新旧并存（§2.5 长期债）。且 soc_version 挂 design 不改 → 兼容模式编译目标代际仍错位。

### 选项 C：runtime 永远 = design（禁止跨代，强一致）

- **否决**：直接否掉用户核心诉求（A5 真机验证 A2 codegen）。且 A5 真机是当前唯一可用硬件，禁止跨代 = 无法验证任何非 A5 design。违背方案合理性第一（CLAUDE.md §1.2）。

### 选项 D：保留严格相等 + 加白名单豁免（A2/A3 design on A5 特判）

- **否决**：白名单是「为省事打补丁」的典型——每加一个兼容组合就要补一行，违反可扩展尺子（§1.2）。且本质就是选项 A 矩阵的退化版，不如直接矩阵化。

---

## 4. 不做（边界）

- 不改 SKILL.md Step4 路径表字面量（`"A5 Regbase"` 等契约保留）
- 不改 CLI 旗标语义（`--design-target-chip` / `--runtime-target-chip`）
- 不动 `workflow_requires_npu` / `requires_npu`（纯 design SE workflow 跳过路径已正确）
- 不动 retarget/confirm 软门机制（只在真不兼容触发，文案「跨代产物无法本机 build/run」+「改打本机」均正确）
- 不引入新 pytest 标记
- 不跑 heavy_llm（§3.11）：本次 UT 级修复无真机依赖；兼容模式端到端（design=A2/runtime=A5 真跑 codegen→build）留用户在 A5 真机决策跑

---

## 5. 与既有问题的关系

- **P63**（已修复）：A2→Regbase 的**映射 bug**（哪代属哪个模型判错）。P65 是「用代际相等判兼容」的**维度选错**。P63 修对了映射，是 P65 矩阵的正确性前提——若 A2 仍被误判 Regbase，P65 矩阵会把 (A2,A5) 判不兼容。二者正交。
- **P64**（未接入）：A5 VF 设计/验证闭环的特性缺口。P65 不涉及 VF 闭环，仅修 chip 兼容判定。
