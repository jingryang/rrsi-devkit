# codegen 框架化方案 — full-pipeline 纯 skill → Python 编排 + skill 叶子

> **性质**：self-evolution 线工作记录（L3 方案分析），承接 `01-multi-op-isolation.md`（NPU）/ `02-opp-isolation.md`（opp+whl）。
> **核心命题**：full-pipeline skill 已端到端验证「生成 ACLNN → 部署 → cann-bench 打分」链路可行，但它是**纯 skill 驱动**（一个大 Driver SKILL.md 编排叶子 skill）。有意义的工作不是集成整个 skill，而是**把这条链路框架化到 DevKit**（Python 编排 + skill 叶子），获得可观测性、并发调度、training-time 迭代能力。
> **已定设计原则（2026-06-29）**：skill 职责边界 = 核心代码（op_host/op_kernel/op_api）质量引导归 skill，脚手架（CMakeLists 等）归 LLM 自身能力，命令编排归 Stage。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点不写行号、不维护现状快照、不照搬外部脚本、外部依赖只读、不引用会话临时文件）。

---

## 0. 为什么不是"集成 skill"

full-pipeline skill 的端到端闭环是**纯 skill 实现**（Driver SKILL.md 编排，每步 Agent 派叶子 skill）。直接集成整个 skill = DevKit 不做任何改动就有一套能跑的链路，但拿不到框架化的任何价值（可观测性 / State 产物袋 / event-sourcing / 并发调度 / training-time 迭代 / 跨算子复用）。所以目标定为**框架化吸收**，不是集成。

---

## 1. 事实基础

### 1.1 full-pipeline 已验证的链路（ascendskills 仓，只读参考）

- **Phase C（coding skill）**：分层生成完整 ACLNN 工程（op_host + op_kernel + op_api + op_plugin + CMakeLists），直写 cann-bench `examples/aclnn_launch_example/csrc/ops/<op>/`。
- **Phase C-deploy（dev-deploy skill）**：`build.sh → 装 .run → export LD_LIBRARY_PATH → pip install wheel → smoke`，填补「compile ≠ 可测试」断裂点（06-17 断裂点分析 #4，v2 已补）。
- **Stage-2（cannbench-eval skill）**：拉起 `run_evaluation.sh` 出 `overall_score`（编译 0.2 + 功能 0.3 + 性能 0.5）。

### 1.2 DevKit 框架化起点

- **设计阶段已框架化**：`stage-design` / `stage-requirement` plugin = Python stage 编排 + skill 叶子 + `schema/*.json`（step-2 编排归位 + step-8 详设精细化 + step-13 schema 迁 skill 目录 的成熟产物）。**这是框架化的范式参考**。
- **codegen 之后能力未框架化**：codegen stage 当前只产 `op_host`/`op_kernel`（面向 ops 仓）；无完整 ACLNN 生成、无 cann-bench 评测通路（verify/perf 用 `NPURunner` 自产自销）、无部署链 stage。

---

## 2. 框架化分层（核心 skill / 脚手架 LLM / 命令 Stage）

| 文件类 | 性质 | 落点 | 依据 |
|---|---|---|---|
| **op_host / op_kernel / op_api** | 核心（算子实质逻辑） | **skill 引导 LLM 生成** | 质量需针对性引导；属通用算子开发知识 |
| **CMakeLists / 脚手架 / 非核心** | 非核心 | **LLM 自身能力**（参考目标仓现有算子模式） | 不耦合具体仓 / 算子（CLAUDE.md 2.1 / 1.5） |
| **compile / deploy / eval** | 命令编排 | **DevKit Stage**（Python 编排调子进程） | 确定性命令链，不需 LLM |

### 2.1 skill 职责边界（关键原则）

skill **只写核心代码的质量引导**——AscendC kernel 最佳实践、tiling 策略、ACLNN API 规范、精度/性能红线，这些是**跨算子、跨仓通用**的算子开发知识（落在 `resources/` + skill 提示，对应 CLAUDE.md 1.5）。

skill **绝不写**：仓特定布局（`register_aclnn_op` 等 cann-bench 专有内容）、算子特定细节、脚手架内容。仓特定的东西靠 **LLM 现场参考目标仓现有算子学**（对应 2.1 即插即用、不耦合具体仓）。

> 反例（已否决）：用 Python 工具机械生成 op_api/op_plugin/CMake。错在——op_api 有核心成分（参数校验/workspace/attrs/dtype dispatch）非纯模板；Python 工具会耦合 cann-bench 仓布局 + 枚举算子特性而膨胀。boilerplate 框架 LLM 凭 ACLNN 知识自然能写，核心质量才需 skill 引导。

---

## 3. 融合策略（吸收，不保留独立通路）

full-pipeline 能力按性质吸收进 DevKit 既有框架，**full-pipeline 独立 skill 通路不保留**（CLAUDE.md 2.5 唯一通路）：

- **LLM 核心**（kernel + host + api）→ 扩展 DevKit **codegen stage** 产出契约；codegen 调的 LLM skill 吸收 coding skill 的「分层编码 + TilingData 归一化 + 自检 + 核心质量引导」逻辑。
- **脚手架**（CMakeLists）→ 不进 skill/工具；codegen stage prompt 提示「参考目标仓现有算子 CMakeLists 模式」，由 LLM 生成。
- **命令**（compile/deploy/eval）→ 新建 DevKit **CompileStage / DeployStage / CannbenchEvalStage**，吸收 full-pipeline skill 的 bash 编排逻辑（**不作为 skill 保留**）。
- **设计层** → DevKit 设计体系已有且更细（**权威，不融合**）。

---

## 4. schema / 第一准则落点

schema 与第一准则要求**只压在 skill 叶子上**，框架代码走另一套契约：

- **skill 叶子（LLM 层）**：满足第一准则——`schema/*.json` 自包含、I/O 文件契约、即插即用（脱离 DevKit 在 TUI 能跑）。参照 DevKit 设计 skill 范式。full-pipeline coding 的 prompt 参数（`task_mode` / `code_path` / `detailed_design_path` / `meta_json_path` ...）**逆写为 schema 字段**。
- **Python Stage / 工具（框架代码，`src/ascendc_devkit/`）**：遵循 DevKit 框架契约——Stage 的 `input_contract` / `output_contract` + State 产物袋 + `artifact_contract`。**不要求即插即用**（它是框架本身）。

---

## 5. 棘手点（3 个）

1. **codegen stage 产出契约扩展**：`generated_sources` 从 `op_host`/`op_kernel` 扩到完整 ACLNN host 层（+ `{op}_infershape.cpp` / `{op}_def.cpp` / host tiling 完整）；`artifact_contract` + agent prompt + skill schema 同步改。脚手架（CMakeLists）不进契约硬约束，prompt 提示参考目标仓。
2. **codegen LLM skill 的 schema 逆写**：full-pipeline coding 是 prompt 参数驱动、无 schema；融合后 codegen 调的 LLM skill 要补 `schema/*.json`（第一准则），把「分层编码顺序 + TilingData plain-C-struct 归一化 + 编码自检 + 核心质量引导」契约化（不契约化仓特定脚手架内容）。
3. **Deploy / Eval Stage 的 I/O 契约**：定义 `input_contract`（`code_path` / `repo_root` / `device_id` / `op_name` ...）/ `output_contract`（deploy 产物路径 / `overall_score`）+ State 字段；接入既有 `codegen → verify → perf` 之后；与 `01`（NPU `--device-id` 由 `NPUSlotManager` 分配）/ `02`（opp+whl D 方案：外层 install opp/whl 到 per-op + `--skip-install` 评测）衔接。

---

## 6. 与既有方案的关系

- **`01` NPU 隔离**：DeployStage / CannbenchEvalStage 的 `--device-id` 由 `NPUSlotManager` 分配（生成 run 内部 verify/perf 也走 slot）。
- **`02` opp+whl 隔离**：DeployStage 落地 D 方案（外层 `run_pkg --install-path=<per-op-opp-dir>` + `pip install --target=<per-op-python-dir>` + cann-bench `--skip-install` 评测）。
- **`self-evolution-direction`**：框架化是 L1 框架基石的扩展（补全 codegen 之后能力），契合北极星「生成可上生产的 AscendC 算子」（完整 ACLNN = 生产形态）。
- **多算子并发**：框架化后的 codegen→deploy→eval 是单算子链路；多算子并发由 `01`/`02` 隔离 + 流水线调度（生成-评测流水线，`01` §3.2）覆盖。

---

## 7. 下一步（路线图）

1. **验证 full-pipeline v2 端到端跑通**（框架化前提）：跑 1 个 phase0 算子过 full-pipeline，出 `overall_score`，证链路可行 + 暴露真实 gap。
2. **棘手点 #1**：codegen stage 产出契约扩展设计（文件清单 + schema 字段 + prompt 改造）。
3. **棘手点 #2**：codegen LLM skill schema 逆写（参照 DevKit 设计 skill 范式）。
4. **棘手点 #3**：Deploy / Eval Stage 契约 + 与 01/02 衔接。
5. 据框架化暴露的真实约束，回精修 L1（P0 registry 自动发现 / P1 State 产物袋；P2 节点树已实现）。
