# L3 方案分析 — golden/cases 来源从 profile 预置改为 CLI 显式 + golden 全链路正名

> **性质**：L3 方案分析。记录有哪些选项、选了哪个、为什么。调研中演进，拍板后冻结。
> **覆盖问题**：`06-problems.md` **P11**（仓级 profile 承载算子级 golden/cases 是架构错位）、**P12**（golden 被窄化为 verify 专属）。
> **修订前序**：修订 `11`（D6 的"profile 声明 source"消费方式）与 `12`（A3/A6/A7 的 profile 预置路径）的**修复方式**（非问题本身）。`11` D1–D5 的**机制**（golden-adapter 代码化、契约驱动 harness 单一 `reference`、cases-loader 代码化、`cann_bench_csv` parser）继续有效，见 §0。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不写 file:line、不引用会话临时文件、外部依赖只读）。

---

## 0. 关键洞察：两层分离 — source 层（改）vs consumer 层（不动）

P11 的修订落在 golden/cases 的**来源层**（source layer）：golden/cases 从哪来。这一层从"profile 预置 + `{op}`/`{N}` 代换"改为"CLI 显式"。

**consumer 层（消费层）不动**：harness 如何消费 golden（importlib 加载 + 入口归一 + numpy↔torch 转换 + 单一 `reference`）、cases-loader 如何解析 `cann_bench_csv` → `TestCase`——这些是 `11` D1–D5 定下的机制，与"golden 从哪来"正交。consumer 层的输入原来是"profile 代换出的契约对象"，改后是"State 里的三标量"，只是喂入数据形状变了，机制本身不变。

| 层 | 职责 | 现状（11/12） | 本文修订 |
|---|---|---|---|
| **source 层** | golden/cases 从哪来 | profile 预置 `golden_source`/`cases_source` + `{op}`/`{N}` 代换 | **CLI 显式**（`--golden`/`--golden-entry`/`--golden-input-type`/`--cann-bench-cases`） |
| **consumer 层** | harness 怎么用 golden / loader 怎么解析 cases | golden-adapter 契约驱动 emit + 单一 `reference` + 类型转换；`cann_bench_csv` parser | **不变** |

**推论**：本文删的是 source 层的一整套代换/探测逻辑（`GoldenSource`/`CasesSource` dataclass + `.resolve()`、`resolve_task_level`、profile schema 的 source 段、verify 的 profile 分支、test_design 的 `_task_level`/`_has_external_cases`），不动 consumer 层（`_build_test_harness` 的 golden 加载段、`parse_cann_bench_csv`）。

---

## 1. 决策点

### E1：golden/cases 来源 —— ✅ CLI 显式，非 profile 预置

**选项**：
- (A) 维持现状（11/D6）：profile 顶层声明 `golden_source`/`cases_source`，用 `{op}`/`{N}` 模板承载算子级参数，运行期 `resolve_task_level` 探测 `{N}` + 代换还原。
- (B) CLI 显式：`--golden <path> --golden-entry <fn> --golden-input-type {torch|numpy} --cann-bench-cases <csv>`。

**选 (B)**。**理由（P11）**：profile 是**仓级**配置（描述整个仓的布局/构建/命名，跨算子一致），golden/cases 是**算子级**输入（每个算子的 golden 路径/入口名、cases 内容各异）。用仓级模板代换算子级差异，是把"本该算子级指定的参数"塞进仓级配置、再运行期代换回来——违背 CLAUDE.md 2.7（算子特定不固化进通用配置）+ 1.5（算子知识不进配置）。

**附带删除（2.5 唯一通路）**：选 (B) 后，(A) 的整条代换/探测通路失去存在意义，一并删干净（`GoldenSource`/`CasesSource` dataclass + `.resolve()`、`resolve_task_level`、profile schema 的 `golden_source`/`cases_source` 段及加载校验、verify `_resolve_golden_contract` 的 profile 分支、test_design 的 `_task_level`/`_has_external_cases`）。不留并存债。

**与 deploy 通用化（09/10 D6-2）的边界**：deploy 的仓特定部分（build/install 命令）确为**仓级**一致（同仓所有算子构建方式相同），进 profile 合理；golden/cases 是**算子级**，不该进 profile。两类参数落在不同层是正确的，不是不一致。

### E2：cases CLI 参数命名 + 内部确定性转 TestCase —— ✅ `--cann-bench-cases`，参数名编码格式

**决策**：
- CLI 参数名 `--cann-bench-cases`（而非 `--cases`）：参数名**编码格式**，与"这是 cann-bench 的 cases.csv"这一实际意义对应。
- 内部步骤把 cases 转成可测试执行的 `TestCase`：**确定性代码**直接 `parse_cann_bench_csv`（`11` D4/D5 已落地的 parser，consumer 层，不变）。无需额外"转换步骤"——loader 本就是"CSV → TestCase"这一步。

**与 D5（首版只 `cann_bench_csv`）的关系**：参数名编码格式 = 把 format 写进参数名，避免在通用 loader 里**预先抽象 format 分派**。第二种 format 真出现时再加对应参数（如 `--xxx-cases`）与 parser，不在首版造分派框架。延续 `avoid-overdesign-prefer-reuse`。

### E3：golden 在 State 里的表示 —— ✅ 三标量 + 明确报错（不猜测默认）

**决策**：State 承载三个标量 `golden_path` / `golden_entry` / `golden_input_type`（不再是用 profile 代换出的契约对象）。三标量配套——golden 不能"只有 path 没 entry"。

**明确报错（F2）**：用户输入不符合要求时报错，不静默退化/不桩：
- `golden_path` 不存在 → CLI 层 `click.Path(exists=True)` 拦。
- `golden_entry` 在 golden 文件里取不到 → harness 期报 `golden_entry_missing`（已有，consumer 层）。
- `golden_input_type` 非法 → CLI 枚举校验（`{torch, numpy}`）。
- 三标量组合不完整（有 path 缺 entry/input_type，或反之）→ 明确报错，**不猜测默认值**。

### E4：golden 的角色 —— ✅ 全链路参考实现（设计依据 + 验证基准），非 verify 专属

**决策**（P12）：golden 的应有定位是**算子的参考实现 / 语义权威**，性质类似 requirement（全链路输入）：
- **design 阶段**据 golden 做设计（算法/公式依据）；后续 design 阶段甚至提前用 golden 做仿真验证（codegen 前比对设计正确性）。
- **verify 阶段**用 golden 做精度比对。

design 与 verify **共享** golden。把 golden 绑 verify（如"无 verify 拒传 golden"拓扑、"含 verify 才校验 golden"）会阻碍 design 消费 golden。

**现状与目标态**：
- 现状：`state.golden_path` 只被 verify 的 `PrecisionGate` 消费；design stages 不读 golden。
- 目标态：golden 机制（CLI 承载 + State 字段 + 早期校验 + 必选判据）**全链路可见**，凡用 golden 的 workflow 都覆盖。
- 当前仓 design stages 未消费 golden（SE 的 design 仿真已在**别的系统**初步实现，不在本仓），但机制要为接入留通路——故 golden 机制不绑 verify。

### E5：早期校验分层 —— ✅ dispatch 期（环境无关）+ verify harness 期（环境依赖 import）

**诉求**：golden 要**早期**校验"reference 函数存在/可 import"，避免执行到 verify 后期才发现 golden 用不了（P11 原始动机）。

**约束**：早期校验**不能假设环境**。实际开发场景，golden 可能依赖 `torch_npu`/`cuda`/`tensorflow` 等第三方库，这些在 dispatch 期未必可用。这是**真实场景**，非过设计——不能从"cann-bench golden 只依赖 torch"推广到"所有仓 golden 都不依赖重库"（以偏概全，违背 CLAUDE.md 1.2）。

**分层方案**：

| 层 | 校验内容 | 是否依赖环境 | 失败语义 |
|---|---|---|---|
| **dispatch 期** | `path` 存在、`entry`/`input_type` 语法合法（标量齐全、`input_type ∈ {torch,numpy}`）、必选满足 | 否（不 import） | 即时拒绝，列缺失项 |
| **verify harness 期** | `importlib` 加载 golden + `getattr(entry)` 真实取函数 | 是（需 import） | `golden_entry_missing` / 导入错误 |

**env 同源保证 harness 期可靠**：harness 子进程 `run_env = {**os.environ, ...}` 继承 dispatch 期 env + deploy 产物（`PYTHONPATH`/`ASCEND_CUSTOM_OPP_PATH`/`LD_LIBRARY_PATH`）。故 **harness 期能 import ≡ 真实执行期可 import**——harness 期 import 失败不是"误报"，而是 golden 真实不可用。

**否决两极端**：
- 否决"所有仓 dispatch 期都 import golden"：以偏概全，重库依赖仓会在 dispatch 期误报。
- 否决"完全不早期校验"：违背诉求，让用户执行到后期才炸。

### E6：golden 必选判据 + 切换可选↔必选声明式 —— ✅ 凡用 golden 的 workflow 必选；声明式切换

**判据**：做 **design 或 verify** 的 workflow 都必选 golden。因 golden 是设计依据 + 验证基准（E4），任何设计都须有 golden 作正确性锚点。

**与 verify 解耦**：必选判据**不绑 "has verify"**（那是 P12 的窄化）。判据是"workflow 用 golden"——只要该 workflow 会 design 或 verify，golden 即必选。

**声明式机制（保灵活性）**：必选**不硬编码在 if 分支**，而是通过 dispatcher 的声明式必选配置（`_USER_INPUT_FIELDS` / `_SOFT_INPUT_FIELDS` / `_preflight_user_inputs` 的 `hard_missing` 机制）。把"哪些参数必选"**声明进配置**，切换某参数可选↔必选**只改声明、不改逻辑**。满足"后续将任意参数从可选改成必选/必选改成可选只需简单修改"的要求。

**冲突处理**：golden 与其他必选/语义不符时（如某 workflow 不该有 golden 却传了）→**明确报错、与用户讨论**，不猜测、不静默吞。

### E7：批量执行不冲突 + `resolve_task_level` 去留 —— ✅ 批量是 run 外层编排；探测能力归批量工具

**批量不冲突**：批量执行（用 cann-bench 多算子跑 self_evolve_op）是 `run` 的**外层编排**——对每个算子调一次 `run`，每次显式列 golden/cases 参数。`run` 是单算子入口，批量工具负责"算子集合 → 每算子的参数"。两者职责分离，不冲突。

**`resolve_task_level`（原 `{N}` 存在性探测）去留**：E1 删 profile 预置后，`{N}` 代换失去载体，`resolve_task_level` 在单算子 `run` 通路上**删除**。当未来批量工具需要"按算子定位 task 层级"时，该能力由**批量工具自带**（批量工具天然持有"算子 → task 层级"的映射，是编排知识，不是单算子 run 的参数）。即：`{N}`/task 层级归批量层，不进单算子 run 通路。

---

## 2. CLI 形态（示意）

```bash
# self_evolve_op（exp，对齐 cann-bench ②）—— golden 三参 + cases 全显式
ascendc-devkit run --workflow self_evolve_op \
  --repo-root <cann-bench> --op-dir <.../ops/exp> \
  --requirement <cann-bench>/tasks/level1/exp/proto.yaml \
  --golden          <cann-bench>/tasks/level1/exp/golden.py \
  --golden-entry    exp \
  --golden-input-type torch \
  --cann-bench-cases <cann-bench>/tasks/level1/exp/cases.csv \
  --chip-version ascend950 --mode new --npu-id 0 \
  --non-interactive --on-decision default

# generate_ascendc（无 cases；golden 若提供则用，机制全链路可见）
ascendc-devkit run --workflow generate_ascendc \
  --golden <golden.py> --golden-entry forward --golden-input-type torch \
  ...   # golden 必选（generate_ascendc 有 design + verify）
```

- golden 三参配套（E3）；cases 可选（仅 self_evolve_op 对齐 cann-bench 时需要）。
- 参数名 `--cann-bench-cases` 编码格式（E2）。
- 早期校验在 dispatch 期（path/语法/必选）+ harness 期（import/entry）（E5）。

---

## 3. 与已有决策 / 原则的关系

- **修订 `11` D6（非推翻）**：D6 的 ① 对齐 ② **目标**（① 跑 cann-bench 用例 + 同源 golden 作 ② 快速预检）不变；变的是**source 层**（profile 预置 → CLI 显式）。D1–D5 的 consumer 机制（golden-adapter、cases-loader、`cann_bench_csv` parser）继续有效（§0）。
- **修订 `11`/`12` 的 profile 路径**：A3（profile schema 增 source 段）、A6（cann-bench profile 声明 source）、A7（按 profile 消费）的 source 部分作废，改 CLI；A1/A2（TestCase.attrs + harness 传 kwargs）、A4/A5 的 consumer 部分（harness golden 加载段、`parse_cann_bench_csv`）保留。
- **承接 P12**：E4 把 golden 正名为全链路参考实现，纠正"现状只 verify 消费"的窄化。
- **CLAUDE.md 1.2（四把尺子）**：E1 用"正确改动"（source 归 CLI）保住"算子级参数不进仓级配置"的不变式；E5 分层校验兼顾"早期发现"（可诊断）与"不假设环境"（架构合理）。
- **CLAUDE.md 1.3（加载期校验）**：E5 的 dispatch 期校验（path/语法/必选）= 加载期/前置校验；harness 期 import 是环境依赖部分，诚实分层。
- **CLAUDE.md 1.5 / 2.7**：golden/cases 算子级参数走 CLI，不固化进通用 profile。
- **CLAUDE.md 2.5（唯一通路）**：E1 删净 source 层旧代换通路，不留并存。
- **CLAUDE.md 3.7（环境缺失诚实报错）**：E5 harness 期 import 失败如实报 golden 不可用，不桩。
- **`avoid-overdesign-prefer-reuse`**：E2 参数名编码 format（不预先抽象分派）；E6 复用既有声明式必选机制。

---

## 4. 推翻 / 修正的前序内容

- **修订 `11` §2 profile 声明形态**：`golden_source`/`cases_source` 顶层声明 + `{op}`/`{N}` 代换的方案作废。改 CLI 显式（E1）。`{op}` 代换被"用户直接传算子对应的 golden 路径"取代；`{N}` 代换被"用户直接传对应层级路径"取代。
- **修订 `12` A3/A6/A7**：profile schema 增 source 段、cann-bench profile 声明 source、按 profile 消费——这些 source 层步骤作废。consumer 层（A1/A2、A4 的 harness golden 加载段、A5 的 `parse_cann_bench_csv`）保留。
- **纠正"golden 绑 verify"的隐含假设**：`12` A7"verify 有 golden_source 时 adapter 喂 harness"把 golden 隐式绑在 verify。E4 正名为全链路，E6 必选判据解耦 verify。
- **保留 `11` D7（P8 先修）**：attrs 仍是 golden/cases 正确工作的前提，本修订不改变其优先级。

---

## 5. 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | 初版：覆盖 P11/P12。§0 两层分离（source 改/consumer 不动）。E1 source 改 CLI 显式（删 profile 预置 + 代换/探测）；E2 `--cann-bench-cases` 参数名编码 format；E3 golden 三标量 State + 明确报错；E4 golden 全链路参考实现（非 verify 专属）；E5 早期校验分层（dispatch 环境无关 + harness 环境依赖 import，env 同源）；E6 凡用 golden 的 workflow 必选 + 声明式切换；E7 批量是 run 外层编排、`resolve_task_level` 归批量工具。修订 11 D6 / 12 A3/A6/A7 的 source 层。 |
