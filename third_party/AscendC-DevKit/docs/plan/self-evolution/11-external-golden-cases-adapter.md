# L3 方案分析 — 外部 golden / 用例适配 + cann-bench ① 对齐 ②

> **性质**：L3 方案分析。记录有哪些选项、选了哪个、为什么。调研中演进，拍板后冻结。
> **覆盖问题**：`06-problems.md` **P8**（`TestCase`/harness 缺 attrs）、**P9**（无外部 golden 适配）、**P10**（无外部用例消费通路）。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不写 file:line、不引用会话临时文件、外部依赖只读）。

---

## 0. 统一原则：外部仓产物 → 框架契约的桥接

P9/P10 是同一类问题：把一个**外部、仓特定的产物**（cann-bench 的 `golden.py`、`cases.csv`）桥接成**框架内部契约**（harness 可执行的 golden 入口、`TestCase` 列表）。这与 `09/10` 的 deploy 通用化（D6-2）是**同一个模式**：

| 维度 | deploy（已落地 D6-2） | golden / cases（本文） |
|---|---|---|
| 仓特定部分 | build/install 命令、路径 | golden 路径/入口名/类型；cases 路径/格式 |
| 落点 | 声明在 `profile.json` 的 role stages | 声明在 `profile.json` 的 `golden_source`/`cases_source` |
| 执行 | 一条通用确定性代码（`DeployStage` 按 role 跑） | 一条通用确定性代码（适配器/loader 按 profile 声明跑） |
| LLM 角色 | 无 | **无**——纯机械桥接 |

**结论先行**：golden 适配与 cases 加载都是**确定性代码**（非 LLM），仓特定约定**声明在 profile**（非硬编码），与 deploy 通用化同构。cann-bench 在这套里只是"声明 + 消费"通用能力，自己不带特化代码（CLAUDE.md 2.1/1.5）。

---

## 1. 决策点

### D1：golden-adapter 由谁做 —— ✅ 代码（确定性），非 LLM

**决策**：golden 适配是纯代码。要做的事——定位源 golden、`import`、按入口名取函数、numpy↔torch 转换、透传 attrs、对外暴露规范入口——**每一步都是机械活，无任何需要 LLM 判断的点**。仓特定部分（源 golden 在哪、入口叫什么、期望什么类型）声明在 profile，代码照声明跑。

**否决 LLM**：LLM 适用于"需要创造性判断"的核心引导（CLAUDE.md 2.7），不适用于确定性管道活。让 LLM 推断入口名/类型会引入非确定性，而这里确定性唾手可得（profile 声明）。

### D2：golden-adapter 通用性 —— ✅ 通用能力，非 cann-bench 特化

**决策**：golden-adapter 是通用能力，所有 workflow 受益。

**理由（去 toil）**：generate_ascendc **现状就逼用户手写** `add_golden.py` 凑 harness 契约（`reference` 函数名 + numpy 类型），每个算子手写一遍。做成通用"把任意参考 golden 适配成 harness 规范入口"后，generate_ascendc 直接受益——`--golden` 指向任意参考实现（torch golden / cann-bench golden / 别仓 golden），适配器自动归一化。这是**去掉既有手活**，不是为 cann-bench 临时造。

**机制**：profile 顶层声明 `golden_source`（仓级约定，跨算子一致）；未声明时回退现状（用户 `--golden` 自带规范文件）。两种模式共存，不破坏 generate_ascendc 现有用法。

### D3：golden-adapter 实现机制 —— ✅ 契约驱动的 harness 生成，非运行时 wrapper 文件

**决策**：harness 生成时按 golden 契约 emit "加载源 golden + 入口归一 + 类型转换"代码；harness 入口仍**单一 `reference`**。

**否决"运行时生成 wrapper 文件"**：harness 本就是 `_build_test_harness` 生成的脚本，把 golden 契约处理内嵌进生成逻辑最自然；另造一个 wrapper 文件是多余产物（违反 2.5 唯一通路）。

**入口归一**：源 golden 入口名可能各异（cann-bench 用算子名 `exp`，别仓可能 `forward`/`golden`）。harness 生成时按契约 `{entry}` 取函数，统一包成 `reference`。harness 消费侧只认 `reference`。

**收口 `run`/`compute` 回退（2.5）**：现状 harness 的 `reference→run→compute` 回退链是"给手写 golden 留的命名宽容"。等 golden-adapter 落地、手写 golden（`add_golden.py` 等）被取代后，harness 收成单一 `reference` 入口，删 `run`/`compute` 兼容。此事随 golden-adapter 一起收口，不单独做。

**类型契约**：`golden_source.input_type`（`torch`/`numpy`）声明源 golden 期望的输入类型；harness 生成按此决定是否 numpy→torch 转换。

### D4：cases-loader 由谁做 —— ✅ 代码（确定性），非 LLM

**决策**：解析已知 schema 的 CSV 是纯机械活，代码做。仓特定部分（cases 路径、格式）声明在 profile。

### D5：cases-loader 通用性 —— ✅ 通用 loader 按 format 分派，首版只 `cann_bench_csv`，不预先抽象

**决策**：cases-loader 做成"profile 声明 `cases_source`（含 `format`）→ 通用 loader 按 format 分派"的架构，但**首版只实现 `cann_bench_csv` 一种 parser**。

**理由（避免过度设计）**：目前只有 cann-bench 有外部用例（`cases.csv`）；generate_ascendc 用 test_design；ops-nn/omni-ops 有无外部用例格式未知。按 `avoid-overdesign-prefer-reuse`，正确做法是**别把 cann-bench 写死**（声明 + 分派架构留扩展位），但**不为尚不存在的第二种 format 预先抽象**。第二种格式真出现时再加 parser。

### D6：cann-bench ① 对齐 ② —— ✅ self_evolve_op 声明 golden_source + cases_source，① 成 ② function 维度本地预检

**决策**：cann-bench profile 声明 `golden_source`（指 `tasks/level<N>/<op>/golden.py`，entry=`{op}`，input_type=torch）+ `cases_source`（format=`cann_bench_csv`，指 `tasks/level<N>/<op>/cases.csv`）。self_evolve_op 中：

- **test_design**：profile 有 `cases_source` 时，用 cases-loader 加载 cann-bench 用例（确定性）填 `state.test_cases`，**不再 LLM 自设计**。无 `cases_source` 时维持 LLM 设计（generate_ascendc 不受影响）。
- **verify**：profile 有 `golden_source` 时，golden-adapter 把 cann-bench golden 适配成规范入口喂 harness；`state.golden_path`（用户 `--golden`）优先级更高（用户显式输入压过 profile 约定）。
- **结果**：① verify 跑的就是 ② cann-bench 会跑的那批用例 + 同一份 golden 公式，只是本地快速跑、不经 cann-bench 完整评测 harness。① 真正成为 ② 的**快速预检**——① 过了，② 的 function 维度基本稳。

**② 不变**：cannbench_eval 仍是 cann-bench `kernel_eval` 完整跑（compile + function + performance + anti-cheat），① 替代不了它。① 只省掉"明显错的代码还去跑完整 cann-bench"的浪费。

**不违背三层评价（07）**：三层模型要求 **②⊥③**（loss 与 ground truth 独立），**不要求 ①⊥②**。① 是 ② 的快速帮手，对齐反而让内层回路真正服务目标。①② 共用用例/golden 不损害 ② 的独立性，因为 ② 用的是 cann-bench **自己内部**的 golden/cases，DevKit 既无法注入也无法伪造。

**语义边界提醒**：① 对齐 ② 后，"通过 ①"是 self_evolve_op 的**操作目标**，但 ≠ **正确性**——② 是 proxy loss，③（全量用例）才是 ground truth。op 可能过 ② 但在 ② 不覆盖的维度仍错。此区分在三层模型中刻意保留。

### D7：依赖与实施顺序 —— ✅ P8 先修，其余建立在正确 TestCase 模型上

**决策**：P8（attrs）是 P9/P10/cann-bench 对齐的**共同前提**，须最先修。顺序：

```
P8（TestCase.attrs + harness 传 kwargs）
   ↓
golden-adapter（D1/D2/D3）   cases-loader（D4/D5）   ← 并行，都依赖 P8
   ↓                              ↓
cann-bench 对齐（D6）：profile 声明 + test_design/verify 消费
```

**理由**：cann-bench 的用例和 golden 都靠 attrs 工作；harness 不传 attrs，则无论适配多完美都只测默认分支（P8 未修则 P9/P10 落地也是半桩）。

---

## 2. profile 声明形态（示意）

profile 顶层新增两个可选字段（仓级约定，跨算子一致；`additionalProperties:false` 须同步放开）：

```yaml
# cann-bench.yaml（示意）
name: cann-bench
op_naming: { prefix: "" }
build_variants: [ ... ]        # 既有，不变

golden_source:                 # P9 / D2：源 golden 适配契约
  path: "tasks/level{N}/{op}/golden.py"   # {N}=难度层级，{op}=算子名，运行期代入
  entry: "{op}"                            # cann-bench 用算子名当函数名
  input_type: torch                        # 源 golden 期望 torch.Tensor

cases_source:                  # P10 / D5：外部用例源
  format: cann_bench_csv
  path: "tasks/level{N}/{op}/cases.csv"
```

- `{op}`/`{N}` 运行期由算子名 + task 层级代入（层级如何确定见 L4，可能与 op_dir 或 task 约定相关）。
- 未声明 `golden_source`/`cases_source` 的仓（ops-nn/omni-ops/generate_ascendc 默认）：维持现状（用户 `--golden` + test_design LLM）。
- 加载期校验（CLAUDE.md 1.3）：`golden_source`/`cases_source` 字段合法性在 profile 加载时校验（path 非空、format 属已知枚举、input_type 属 {torch,numpy}）。

---

## 3. 与已有决策 / 原则的关系

- **承接 `09/10` deploy 通用化（D6-2）**：本文是同一模式（仓特定声明 profile + 通用确定性执行）在 golden/cases 上的再次应用。一致性即正确性。
- **承接 `07` 三层评价（①②③）**：D6 的 ① 对齐 ② 不违背 ②⊥③；① 是 ② 快速预检。
- **承接 P7/`10` G7 真 kernel 精度**：D6 的 ① 用真 kernel + 权威 golden + cann-bench 用例，是 G7 真 kernel 通路的自然延伸（用例/golden 来源对齐 ②）。
- **CLAUDE.md 1.5**（资源/约定不硬编码进 Python）：仓特定路径/入口/格式在 profile，不在代码。
- **CLAUDE.md 2.5**（唯一通路）：golden-adapter 收掉 `run`/`compute` 回退；cases 来源"有 `cases_source` 走 loader、否则走 test_design"是互斥分支非并存债。
- **CLAUDE.md 2.7**（核心归 skill、脚手架归 LLM）：golden/cases 桥接是**管道活**，既非算子核心知识（不进 skill）也无需判断（不归 LLM），归确定性框架代码。
- **CLAUDE.md 1.3**（加载期校验）：profile 的 `golden_source`/`cases_source` 合法性加载期校验。
- **`avoid-overdesign-prefer-reuse`**：D5 cases-loader 不预先抽象第二种 format；golden-adapter 复用既有 harness 生成机制（不另造 wrapper 文件，D3）。

---

## 4. 推翻 / 修正的前序内容

- 本文 **D6 推翻**先前讨论中"为 exp 手写 numpy `exp_golden.py`"的临时想法——改为 profile 声明 + 通用适配器直连 cann-bench golden（单一真相源，零漂移）。手写 fixture（`add_golden.py`/`exp_golden.py`）作为过渡产物，golden-adapter 落地后被取代。
- 本文澄清"harness 的 `reference/run/compute` 是回退链取一个，不是要三个函数"——否决"封装成三个函数"的理解。

---

## 5. 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-02 | 初版：覆盖 P8/P9/P10。统一原则（外部产物→契约桥接，同 deploy D6-2）。D1 golden 适配代码非 LLM；D2 通用；D3 契约驱动 harness 生成 + 收口 run/compute；D4 cases 加载代码非 LLM；D5 通用 loader 首版只 cann_bench_csv；D6 cann-bench ① 对齐 ②；D7 P8 先修。 |
| 2026-07-03 | **source 层修订**：D6 的"profile 声明 source + 运行期代换/探测"消费方式由 `13/14` 重构为 CLI 显式（P11 仓级 profile 承载算子级参数的架构错位 + P12 golden 全链路正名）。**D1–D5 的 consumer 机制保留**（golden-adapter 契约驱动 harness 单一 `reference` + numpy↔torch 转换、cases-loader `cann_bench_csv` parser）。即两层分离：source 层改、consumer 层不动。详见 `13`（L3）/`14`（L4）。 |
