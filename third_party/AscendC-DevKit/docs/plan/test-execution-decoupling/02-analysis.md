# 测试执行外部化 — 方案分析（L3）

> **性质**：test-execution-decoupling 线 L3 方案分析。
> **状态**：**冻结**（2026-07-17，用户认可"服务型抽象 + 双向 adapter"方向）。
> **承接问题**：`01-problems.md` P1（run_test 路径内化 cann-bench 知识）。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点用函数/模块名、不写行号、不照搬外部脚本、不引用会话临时文件、外部依赖只读）。
> **调研依据**：框架侧代码阅读 + cann-bench `kernel_eval` 能力边界只读调研（2026-07-16/17）。

---

## 0. 问题重述与来龙去脉

### 0.1 两条评测线

self-evolution 流水线验证生成算子精度，有两条评测线：

| 线 | 角色 | 现状实现 | 耦合度 |
|----|------|---------|--------|
| ② 权威评测 | 全集三维分（compile/function/performance）打分 | `CannbenchEvalStage` subprocess 调 `kernel_eval.cli` + 解析 report | ✅ 已外部化 |
| ① 本地预检 | 单 case 快速判定 + 中间张量定位（precision_debug 迭代用） | `runner.execute` 自建 harness + import cann-bench 内部模块 | ❌ 内化 |

### 0.2 内化是怎么来的（commit 42ffca0）

① 本地预检最初是框架自建 harness（当时无外部评测工具可用，合理起点）。cann-bench 出现后：
- ② 加了 `CannbenchEvalStage` 调 CLI（外部化，正确）
- ① 为"用上 cann-bench 的 task 数据"，commit 42ffca0 做了专项适配：新增 `try_load_cannbench_task`（硬编码 `tasks/level*/<op_name>` 目录）+ `task_loader`（解析 cann-bench 格式）+ harness 内嵌 `import DataGenerator` + `import compare_tensors`

**内化是"让本地预检复用 cann-bench 数据"逐步加进去的，非初始设计**。P79（rule × backend 正交）已把"比较"后端协议化（`PrecisionComparer` + `DevkitComparer`/`CannbenchComparer`），部分解耦；**剩 `task_loader` 目录硬编码 + `DataGenerator` import 待解耦**——即本 step。per-input value_range bug（scatter）就是 `task_loader` 通路没跟齐正确实现的症状。

### 0.3 用户的三个设计意图（方案最高约束）

1. **通用能力优先**：框架默认能跑**任意算子仓**（ops-nn/ops-transformer）。这些仓不是评测仓、无评测脚手架（无 CLI/report/单 case 参数），框架**不能要求它们造这些**。
2. **cann-bench 标准对齐**：cann-bench 是重要标准仓。目标是 cann-bench 算子时，要**全面接入 cann-bench 评测标准**（数据生成/比较/阈值），保证评测一致——否则本地预判信号失真（本地过、权威挂，拿不到分）。
3. **未来可扩展（ATK/TTK）**：未来要接入 ATK/TTK 等通用测试工具（输入=其自身格式用例+配置，输出=结果表，支持单用例+批跑）。这些工具应能**快速接入**。

---

## 1. cann-bench kernel_eval 能力边界（调研结论）

> 只读调研，未修改任何文件。

### 1.1 CLI 支持单 case 判定

`kernel_eval.cli eval` 支持 `--operator <name>` + `--case-id <int>` + `--no-perf`（仅精度）+ `--skip-install`（隐藏参数，跳过编译直接用 PYTHONPATH 上的 cann_bench）。单 case 快速判定可行。`CannbenchEvalStage` 已是 CLI 调用范式（全集）。

### 1.2 Report 字段对失败定位充分

用例级含 `status`(success/failed/cascade/skipped) + `accuracy.max_diff` + `accuracy.output_results[i].metadata.max_diff` + mere/mare/mismatch_count/threshold + error_msg/failure_type。算子级含三维分 + compilation_error 透传。

### 1.3 Dumptensor/printf 完全缺失

对 `kernel_eval` 全树 grep dump/printf/intermediate —— **零命中**。它是端到端黑盒判定器，不给"CopyIn/Compute/CopyOut 哪步错"。逐层定位能力（DumpTensor/printf）全在 DevKit skills（`ascendc-dumptensor`/`ascendc-precision-dump-debug`）。

### 1.4 DataGenerator 是 golden 对齐命脉

`DataGenerator.generate_input_tensors_from_case` 是 cann-bench 评测唯一数据生成入口。约定：`case_seed = (eval_seed + SHA256(case_id_str)[:8]) % 2^31`，`torch.rand(float64) → scale → clamp(finfo) → cast`，per-input value_range 显式支持嵌套 `[[lo,hi],...]`。框架 `runner` 已精确复刻 seed + 直接 import DataGenerator 保证逐字节一致。改自建生成器需完整复刻全部边界，任一偏差 → golden 对不上 → 冤杀。

### 1.5 compare_tensors 算法通用、阈值可覆盖

MERE/MARE + 小值域/相消兜底，算法通用；提供 `custom_thresholds` 可覆盖阈值（DevKit 已用它注入 proto 真值）。P79 的 `DevkitComparer` 已用框架自实现 MERE/MARE 替代其在 abs-diff 路径的职责。

---

## 2. 核心洞察

### 2.1 洞察一：判定 vs 定位是两个正交关注点

precision_debug 实际有两种正交需求，当前 `runner.execute` 把它们揉在一个 harness：

| 需求 | 含义 | 外部化可行性 |
|------|------|-------------|
| **判定** | 输出对不对、max_diff、哪个 case 失败 | 可委托外部（CLI/工具） |
| **定位** | CopyIn/Compute/CopyOut 哪步数值错 | **任何 backend 都不提供**（含 cann-bench），必须 DevKit 自建 |

→ **评测 backend 只管判定**；定位（printf/dumptensor）始终 DevKit 自建，与 backend 正交。

### 2.2 洞察二：backend 有两种形态，抽象层级必须建在普遍形态上

| 形态 | 代表 | 特征 |
|------|------|------|
| **零件注入型** | cann-bench 模块级 | 暴露内部模块（DataGenerator/compare_tensors），可拆解嵌入框架 harness |
| **整箱服务型** | ATK/TTK/cann-bench CLI | 黑盒，"给用例+配置 → 返回结果表"，不可拆 |

**零件注入型是 cann-bench 模块级的特例；整箱服务型是更普遍的形态**（ATK/TTK 天然如此，cann-bench CLI 也是）。抽象必须建在**整箱服务型**层级，否则 ATK/TTK 接不进来。

### 2.3 洞察三：标准一致性靠"选对 backend"，不靠"零件配套"

cann-bench 标准是一族配套能力（数据生成+比较+阈值），但保证一致性的正确机制不是"框架拼装配套零件"（那会允许混搭），而是"**选定一个自成体的 backend**"——cann-bench 算子选 CannbenchBackend，它内部用 cann-bench 全套，返回结果天然标准一致。混搭不可能发生，因为只调一个 `run()`。

---

## 3. 方案演进（诚实记录判断修正）

L3 调研中方案经历了三次修正，记录如下（体现"调研中演进"，最终冻结于 §4）：

| 阶段 | 方案 | 问题 |
|------|------|------|
| v1 | A（① 调 kernel_eval.cli）/ D（① 自建 DevkitComparer）二选一 | A 把判定绑死 cann-bench CLI（搭便车，`--skip-install` 隐藏参数脆弱）+ 强求所有后端造 CLI（外部负担重）；D 无法对齐 cann-bench 标准（拿不到高分） |
| v2 | `EvaluationBackend` 三件套（`make_data_generator`/`make_comparer`/`thresholds`）抽象工厂 | **抽象层级错**：假设 backend 可拆成零件，ATK/TTK（整箱黑盒）无法实现——伪通用 |
| **v3（冻结）** | **`EvaluationBackend.run() → TestReport` 服务型抽象 + 双向 adapter** | 抽象建在普遍形态（整箱服务）上，cann-bench/ATK/TTK/Devkit 都能实现；标准一致靠选对 backend；定位正交 |

v3 由用户提的 ATK/TTK 场景触发——它暴露了 v2 三件套只覆盖 cann-bench 模块级、接不进整箱工具的缺陷，推动抽象层级修正。

---

## 4. 冻结方案：服务型抽象 + 双向 adapter

### 4.1 核心契约（接口草图，非最终实现）

抽象建在"执行测试 + 返回标准化结果"层级。框架定义两个中立格式，各 backend adapter 双向转译：

```python
# —— 中立格式 1：评测请求 ——
@dataclass(frozen=True)
class EvalRequest:
    op: OpRef                       # callable_target / op_dir / chip
    cases: list[TestCase]           # 标准用例（domain 已有 TestCase）
    rule: CompareRule               # 精度规格（proto 真值，domain 已有 CompareRule）
    deploy_result: DeployResult     # 部署产物路径（跑 kernel 需要）
    golden_contract: dict | None    # golden path/entry/input_type
    mode: "RunMode"                 # SINGLE_CASE（① 快速迭代）/ BATCH（② 全集打分）
    case_filter: list[str] | None   # 单 case 迭代时指定 case_id

# —— 中立格式 2：标准化结果 ——
@dataclass(frozen=True)
class CaseReport:                   # per-case
    case_id: str
    name: str
    status: str                     # pass / fail / skip / cascade
    max_diff: float
    mere: float; mare: float
    mismatch_count: int; threshold: float
    elapsed_us: float | None        # 性能（可选）
    error_msg: str

@dataclass(frozen=True)
class TestReport:                   # 聚合
    cases: list[CaseReport]
    total: int; passed: int; failed: int
    pass_rate: float
    overall_score: float | None     # 三维加权（cann-bench 有，Devkit 无 → None）
    compile_score: float | None     # 可选三维分
    function_score: float | None
    performance_score: float | None
    extra: dict                     # backend 特有细分透传（不丢，框架不解释）

# —— backend 协议 ——
class EvaluationBackend(Protocol):
    """评测后端：接收标准请求，执行测试，返回标准化 TestReport。"""
    name: str
    def run(self, request: EvalRequest) -> TestReport: ...
    def available(self, op: OpRef, state) -> bool: ...  # 该 backend 是否适用此算子
```

`TestCase` / `CompareRule` / `DeployResult` 复用 domain 现有。`TestReport` 新增（中立结果 schema）。

### 4.2 backend 实现（都是整箱服务型）

| backend | `run()` 内部 | 用途 |
|---------|------------|------|
| **DevkitBackend** | 自建 harness + DevkitComparer（P79 自实现 MERE/MARE）+ 自建数据生成（确定性 seed） | **通用默认**，任何算子仓，零外部负担 |
| **CannbenchBackend** | 调 `kernel_eval.cli`（CLI 形态）或自建 harness + cann-bench DataGenerator/compare_tensors（模块形态，避免 CLI 冷启动）→ 解析 report → TestReport | **cann-bench 标准对齐** |
| **AtkBackend**（未来） | 调 ATK CLI（单用例/批跑）→ 解析结果表 → TestReport | ATK 接入 |
| **TtkBackend**（未来） | 调 TTK CLI → 解析结果 → TestReport | TTK 接入 |

CannbenchBackend 的 CLI/模块两种内部形态都返回 cann-bench 标准 TestReport（内部选择，不暴露协议）。

### 4.3 双向 adapter（接入核心工作量）

每个 backend 是双向 adapter：
- **入**：标准 `EvalRequest` → backend 原生格式（cann-bench cases.yaml / ATK 用例+配置文件 / TTK 配置）
- **出**：backend 原生结果（cann-bench report JSON / ATK 结果表 / TTK 结果）→ 标准 `TestReport`

框架核心**只认中立格式**，不认任何 backend 原生格式。

### 4.4 选择逻辑（谁注入哪个 backend）

```python
def select_backend(op, state, backends: list[EvaluationBackend]) -> EvaluationBackend:
    """按优先级选第一个 available 的 backend。
    默认注册顺序：CannbenchBackend（标准对齐优先）> DevkitBackend（通用兜底）。
    未来 ATK/TTK 按算子仓 profile 或显式注入插入序列。"""
```

- cann-bench 算子（有 task 定义）→ **CannbenchBackend**（标准对齐）
- ops-nn/ops-transformer → **DevkitBackend**（通用，零负担）
- 未来 ATK/TTK 场景 → 插入对应 backend（按 profile/显式注入）

### 4.5 定位能力正交（不进 backend）

precision_debug 工作流：
```
run_tests（评测）   → backend.run(mode=SINGLE_CASE) 判定哪个 case 挂
diagnose（分析）    → DevKit 静态分析
fix（修复）         → DevKit 改代码
printf_location（定位）→ DevKit 自建 dumptensor/printf（与 backend 无关）
```
backend 只服务 run_tests（判定），通过 checkpoint.json 把"哪个 case 挂"告诉定位环节。定位始终 DevKit 自建——不论接哪个 backend 都不变。

### 4.6 设计模式

- **adapter（主导，双向）**：每个 backend 双向转译用例（入）和结果（出）到/从中立格式
- **策略**：backend 可替换，框架持 `EvaluationBackend` 抽象
- **依赖注入（§1.6）**：框架持抽象，`select_backend` 注入实现
- **桥接**：精度规格数据（rule）× backend 实现族正交（P79 已立，TestReport 携带 rule 信息）

（v2 的抽象工厂退居 CannbenchBackend 模块形态内部——组织 DataGenerator/compare_tensors 配套，但不在协议层。）

---

## 5. 落地形态

### 5.1 ① 本地预检（precision_debug run_tests 子 stage）

P0（precision_debug CompositeGroup）拆出 `run_tests` 子 stage 后，该子 stage 调 `select_backend(...).run(request, mode=SINGLE_CASE)`。判定结果经 transition 提取到 State（`_debug_checkpoint`，对标 P0 设计），驱动后续 diagnose/fix/printf_location。

### 5.2 ② 权威评测（CannbenchEvalStage）

**保持调 `kernel_eval.cli` 不变**（已是外部化范式，天然 cann-bench 标准）。可选择性重构为 `CannbenchBackend.run(mode=BATCH)` 以统一入口，但非必须（CannbenchEvalStage 已是该 backend BATCH 形态的等价实现）。是否统一为 §8 待确认。

### 5.3 定位（printf_location 子 stage）

DevKit 自建 dumptensor/printf，与 backend 无关（§4.5）。

---

## 6. 如何满足三个意图

| 意图 | 满足方式 |
|------|---------|
| **通用（不给 ops-nn/ops-transformer 加负担）** | DevkitBackend 默认，外部只需"算子可调用 + golden"，无需评测脚手架 |
| **cann-bench 标准对齐** | cann-bench 算子自动选 CannbenchBackend，`run()` 返回 cann-bench 标准结果（内部全套 cann-bench 能力），本地预判信号与权威评测一致 |
| **未来 ATK/TTK 快速接入** | 写一个 AtkBackend/TtkBackend adapter（CLI 调用 + 双向格式转译），实现 `run()`。**框架零改动**（协议/TestReport/编排不变） |

### per-input value_range bug（scatter）

不单独修。CannbenchBackend 用 cann-bench DataGenerator（正确处理嵌套 per-input range）→ bug 消失；DevkitBackend 自建数据生成独立正确处理。bug 随 backend 抽象落地自然消失。

---

## 7. 与既有工作的关系

- **P79（rule × backend 正交）**：`PrecisionComparer`（比较策略）/ DevkitComparer / CannbenchComparer 保留，成为 DevkitBackend/CannbenchBackend（模块形态）的内部组件。服务型抽象吸纳 P79，不推翻。
- **P0（precision_debug CompositeGroup，`51-precision-debugger-async-fix-impl.md`）**：天然协同，改的是 precision_debug 的不同层（P0=编排层，本 step=执行层）。详见 §11 整体实施视图。要点：① 接口点 = `run_precision_cases()`（P0 调接口、本 step 换内部，透明无返工）；② 依赖序 = P0 先行，本 step 阶段 4 依赖 P0 的 run_tests 子 stage作落点；③ `try_load_cannbench_task()` 归本 step 删（P0 暂留）。
- **CannbenchEvalStage（②）**：保持现状（已是外部化范式）。
- **step-38/39（批跑/卡池）**：已交付，无冲突。

---

## 8. 实施分阶段（L3 给方向，L4 待 P0 推进/待确认解决后、临近实施再写）

> **L4 时机**：本 step 实施依赖 P0 先行（阶段 4）+ 5 项待确认未决。L4 是符号级、动手前写；现在写会被待确认项答案推翻，属过早冻结。L3 五阶段方向已足够——**等 P0 推进、待确认解决、临近实施时再写 L4**。

- **阶段 1**（不依赖 P0，可并行预备）：定义中立格式——`EvaluationBackend` 协议 + `EvalRequest` / `TestReport` / `CaseReport` / `RunMode`（domain 层）。`TestCase`/`CompareRule` 复用。
- **阶段 2**（不依赖 P0，可并行预备）：`DevkitBackend`——迁现有 `runner.execute` + DevkitComparer + 自建数据生成进来，实现 `run()`。
- **阶段 3**（不依赖 P0，可并行预备）：`CannbenchBackend`——CLI 形态（复用 `CannbenchEvalStage._run_eval`/`_parse_report` 收进共享 helper）+ 模块形态（DataGenerator/compare_tensors，避免 CLI 延迟），实现 `run()`。删 `task_loader` 目录嗅探 + `try_load_cannbench_task`。
- **阶段 4**（**依赖 P0 完成**）：① 本地预检改为调 `select_backend().run(SINGLE_CASE)`。落点 = P0 拆出的 run_tests 子 stage。
- **阶段 5**（未来，触发时）：`AtkBackend` / `TtkBackend`。

---

## 9. 待确认项 → 决策（自主执行默认，check 可推翻）

> 为支持自主执行，4 项待确认转为**合理默认决策**。每项标注理由 + 推翻条件——用户 check 时可推翻，推翻则相应 L4 段落返工。

1. **TestReport schema 字段集** → **分层：精度必需 + 性能可选 + 三维分 Optional + extra 透传**
   - `CaseReport`（per-case 必需）：case_id/name/status(pass|fail|skip|cascade)/max_diff/mere/mare/mismatch_count/threshold/error_msg；性能可选 `elapsed_us`
   - `TestReport`（聚合必需）：cases/total/passed/failed/pass_rate；三维分 `overall_score/compile_score/function_score/performance_score` 全 `Optional`（cann-bench 有、Devkit 无→None）；`extra: dict` 透传 backend 特有数据（框架不解释）
   - 理由：对齐 cann-bench report + Devkit 结果的公共集；三维分 Optional 因 DevkitBackend 产不出
   - 推翻条件：若 check 发现需要框架解释三维分（而非透传），则改为分层强类型

2. **CannbenchBackend 默认形态** → **模块形态**（自建 harness + cann-bench DataGenerator/compare_tensors）
   - ① 本地预检用模块形态（无 CLI 冷启动延迟，单 case 快速迭代友好）；② 权威评测仍走 `CannbenchEvalStage` 调 CLI（BATCH，现状不变）
   - 理由：① 需要秒级反馈，模块形态避免每次起 `python -m kernel_eval.cli` 的 import torch_npu + Evaluator 冷启动
   - 推翻条件：执行计划含"实测 CLI 延迟"步骤；若实测 CLI 单 case 可接受（秒级），可改 CLI 形态（更纯、与 ② 趋同）

3. **② 是否统一为 CannbenchBackend.run(BATCH)** → **不统一**（保持 CannbenchEvalStage 现状）
   - 理由：CannbenchEvalStage 已是外部化范式且可用；统一是锦上添花但增改动面 + 回归风险（YAGNI）
   - 推翻条件：若 check 认为入口一致性优先，可作为独立小步后做

4. **EvalRequest 标准用例格式** → **直接用 domain `TestCase`**（per-input value_range 在 generator_params）
   - 理由：TestCase 已是 domain 中立格式，各 backend adapter 负责转译到原生格式；generator_params 携带 value_range（含 per-input）足够
   - 推翻条件：若实施中发现 TestCase 不承载 backend 所需全部信息，再扩展

5. **与 P0 协同时序**：已定（见 §11）—— P0 先行，本 step 阶段 1-3 可与 P0 并行预备，阶段 4 等 P0 完成。此项不再悬空。

---

## 10. 关键路径索引

- L1 问题：`test-execution-decoupling/01-problems.md`（P1）
- 框架内化点：`adapters/npu/task_loader.py`（目录嗅探）、`adapters/npu/runner.py`（harness + import DataGenerator/compare_tensors）、`adapters/npu/precision_comparer.py`（P79 协议 + CannbenchComparer import compare_tensors）
- 已外部化范式：`orchestration/stages/cannbench_eval.py`（subprocess 调 kernel_eval.cli + 解析 report）
- 可复用 domain：`domain/verification.py`（EvalResult/PrecisionDebugResult/DeployResult）、`domain/precision.py`（CompareRule）、`domain/requirement.py`（TestCase）
- 相关 step：P0（`self-evolution/51-precision-debugger-async-fix-impl.md`，precision_debug CompositeGroup）、P79（`49-precision-comparer-protocol-*.md`，rule×backend 正交）

---

## 11. 与 P0 的整体实施视图

> P0（编排层）与本 step（执行层）改的是 precision_debug 的不同层，代码接触面极小，但有明确依赖序。P0 L4 `51` §13 是本节的镜像（两份文档互引）。

### 11.1 分工

| | P0（编排层） | 本 step（执行层） |
|---|---|---|
| 核心动作 | PrecisionDebugStage → CompositeGroup + 4 子 stage + 状态机 | `run_precision_cases` 内化 → `EvaluationBackend.run()` |
| 解决 | async/sync 失配、context 爆、600s ceiling（批跑 halt 直接原因） | cann-bench 内化、标准不一致、per-input bug、ATK/TTK 可接入 |

### 11.2 接口点：`run_precision_cases()`

两者共享唯一函数接口：
- **P0**：run_tests 子 stage 调用它做判定，**只调接口不绑内部**。
- **本 step**：把其内部换为 `select_backend().run()`。

替换对 P0 的 run_tests 子 stage **透明**（签名不变）→ **不存在返工**。

### 11.3 依赖序

- **P0 不依赖本 step**：run_tests 子 stage 调 `run_precision_cases()`，内化版/backend 版都行。
- **本 step 阶段 4 依赖 P0**：`backend.run(SINGLE_CASE)` 的落点 = P0 拆出的 run_tests 子 stage。P0 没做时，本 step 无法完整落地（只能经 debug_service 间接接）。
- **本 step 阶段 1-3 不依赖 P0**：协议 + DevkitBackend + CannbenchBackend 可与 P0 并行预备。

### 11.4 推荐推进顺序

1. **P0 先行**：根治批跑 halt（紧迫）+ 拆出 run_tests 子 stage 作本 step 落点。
2. **本 step 阶段 1-3 并行预备**（与 P0 同时）：协议设计 + 两 backend 实现。
3. **本 step 阶段 4 等 P0 完成**：run_tests 子 stage 接入 backend。
4. **本 step L4 在阶段 4 临近时写**（P0 推进 + 待确认 1-4 解决后）。

### 11.5 `try_load_cannbench_task()` / per-input bug 归属

- `try_load_cannbench_task()`：P0 暂留不删，归本 step 阶段 3 删（与 `task_loader` 外部化统一处理，避免抢改）。
- per-input value_range bug（scatter）：执行层 bug，P0 不碰；本 step 消灭（CannbenchBackend 用 cann-bench DataGenerator 正确处理 per-input）。P0 交付前若需验证 scatter，用 redeploy 重生 harness 零成本路径临时绕过，不打局部补丁。

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-16 | 初版：cann-bench 能力调研，确立"判定可外部化/定位无法外部化"分界，A/D 方案分叉 |
| 2026-07-17 | v2：`EvaluationBackend` 三件套（抽象工厂）+ 四方案多维度对比 |
| 2026-07-17 | **v3 冻结**：用户 ATK/TTK 场景暴露三件套抽象层级错（整箱工具接不进）；修正为 `run() → TestReport` 服务型抽象 + 双向 adapter。记录 v1→v2→v3 演进。主导模式从抽象工厂改为 adapter（双向）+ 策略 + DI。用户认可，冻结为最终方案 |
| 2026-07-17 | 补 §11 与 P0 整体实施视图（分工/接口点/依赖序/推进顺序/归属）；§8 标注各阶段 P0 依赖 + L4 时机（待 P0 推进+待确认解决后写）；§9 待确认 5 协同时序定论；与 P0 L4 `51` §13 互引 |
