# L3 方案分析：baseline st-design / cann-bench 用例来源拆分

> 对应 L1：`01-problems.md`（P1/P2）。拍板后冻结；决策与权衡只在本层。

## 0. 范围与边界

- **目标**：`## BASELINE_RESULT` 增加 `st-design-case: {pass}/{total}` 一行，并让该
  数字可被框架确定性消费/复核；不改任何路由语义（这是报告维度，不是验收闸门）。
- **不动**：run-cases 跑合并集、KernelLaunch 只跑 cann-bench `cases.csv` 的既有行为
  （§1.14 不加机制）；`double_tool_passed` / `failed_case_queue` 路由完全不变。
- **不引入命名启发式**：来源判定必须是结构信号（§1.12），不用 `aclnn` 前缀等名字约定。

## 1. 拆分依据：来源如何判定

### 方案 A：在产出 loader 给 `TestCase` 打 `source` 标记（**选用**）

- `TestCase` 增字段 `source: str = ""`；两个 loader 各自打标：
  - `load_cann_bench_cases` → `"cannbench"`；
  - `parse_testcase_csv`（test-design CSV adapter）→ `"devkit"`。
- 框架侧单点 `case_source_composition(cases)` 统计各来源计数，注入 baseline prompt
  并在 transition 复核 agent 上报的 st-design 总数。
- **正确性依据**：来源在**构造点**确定（§1.15 单点），下游只读标记；对任意算子通用，
  不认名字（§1.12）。存量/手写用例无标记 → 计入 `unknown`，**绝不静默并入任一来源**
  （fail-open 计数 + 框架复核）。
- **可扩展**：新增用例来源（如第三种 producer）只需打一个新标记，拆分逻辑自动归位。

### 方案 B：按 `case_id` / name 前缀启发式分类（否决）

- 否决理由：实测 st-design 的 `case_id` 也被 runner 反推成 cann-bench 风格
  （`level2/grid_sampler_3d_001`），前缀不可靠；靠 `aclnn` 名约定 = 命名启发式
  （§1.12 禁止），换算子/换命名即失效。

### 方案 C：只加一个 `case_set` 描述字段、不做结构标记（否决）

- 否决理由：仍是 agent 自描述、无法确定性消费/复核（§2.10），且格子里只剩名字猜测
  （退回方案 B）。GridSampler 现有产物正是这种临时做法。

## 2. 谁产出该数字：框架 vs agent

- **选用：框架注入权威组成 + agent 产出 + 框架复核**。
  - `_common_context` 注入 `test_case_source_composition`（cannbench/devkit/unknown 计数）；
    baseline `_phase_prompt` 渲染该组成并给出拆分规则。
  - agent 按 rc result.json 的 `case` 名（`{name}:{shape}`）与 `cases.csv` 的
    `{operator}_{case_id}` 集合比对，产出 `rc_result.by_source` 与 `st-design-case` 行。
  - 框架在 transition 复核 `by_source.devkit.total == composition.devkit`，不一致留
    WARN（§1.3 可观测），**不改路由**。
- 否决「框架全量计算并回写」：BASELINE_RESULT 是 agent 的返回契约（框架只解析
  RETURN 行），框架代算会把报告与返回块分裂成两个真相源；且框架读 rc per-case 结果
  需自行定位 iter 目录，耦合 CLI 产物布局（§2.9 越界）。复核（而非代算）已能保证诚实。
- 否决「纯 agent 层、无框架注入/复核」（用户已选框架方案）：分类退化为命名启发、
  无权威校验，正是 P2 的病。

## 3. 四把尺子

- **可维护**：来源在构造点单点打标；统计/注入/复核单点——无散点重复（§1.15）。
- **可扩展**：新来源打新标记即归位；`unknown` 桶兜住存量不误判。
- **可诊断**：组成计数进 checkpoint（`case_source_composition`）；不一致留 WARN，
  数字不可被编造。
- **架构合理**：来源属 domain（TestCase 固有属性），统计属编排层（baseline 报告维度），
  契约属 skill/agent——各落其位，不越层。

## 4. 已知边界（诚实记录）

- KernelLaunch 按 skill 约定只跑 cann-bench `cases.csv`，故 `kl_result` 无 st-design
  子集；`st-design-case` 只对 run-cases 有意义。若未来 kl 也覆盖 st-design，需另立。
- `unknown`（无 source 的存量/手写 case）计为独立桶，不进 cannbench/devkit；
  `devkit.total` 复核仅针对 `source=="devkit"`。

## 5. 修订（2026-09-29）：`rc_pass` 标记取 cann-bench 子集

- **事实**：初版实现让 `## BASELINE_RESULT` 的 `rc_pass` 行沿用 `rc_result.pass/total`
  全量合并总计（如某 run `rc_pass: 127/127`），与 `kl_pass`（只跑 cann-bench `cases.csv`，
  如 `20/20`）**不同基**，双工具标记无法直接交叉对比。
- **拍板**：`rc_pass` 行改取 **cann-bench 子集**（`by_source.cannbench`，与 `kl_pass`
  同基）；`st-design-case` 行仍取 `by_source.devkit`；`rc_result.pass/total`（JSON）与
  框架验收门（`double_tool_passed`）**保持全量合并**不变（st-design 失败仍阻断）。
  关系：`rc_pass`(cannbench) + `st-design-case`(devkit) = `rc_result` 全量。
- **边界**：仅标记语义澄清，不改路由/验收语义（用户拍板「仅标记改，门保持全量」）。
