# L1 问题记录 — self-evolution 工作线

> **性质**：L1 问题/需求记录。只记录客观事实（哪里坏了、凭什么这么说），不提方案、不排顺序、不写决策。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不写 file:line、不引用会话临时文件）。每个事实只在此层有产权，其他层只引用。

---

## ✅ P1: codegen 产出 `op_plugin/*.cpp` 未同步更新 `cann_bench/__init__.py`，导致 `kernel_eval` 接口扫描不到算子

### 事实

- **观测**：`self_evolve_op` 最小环路实跑验证中，codegen 产出了 `op_plugin/exp_plugin.cpp`（含 `TORCH_LIBRARY_FRAGMENT(cann_bench, ...)` 注册），`DeployStage` 编译安装成功，冒烟测试 `import cann_bench` 通过。但 `CannbenchEvalStage` 拉起 `kernel_eval --skip-install` 后，`scan_interfaces()` 返回的接口列表不含 `exp`，导致 `match_operators` 匹配失败（"未匹配到tasks 中的算子"），评测无法执行。

- **根因**：`kernel_eval` 的 `scan_interfaces()` 通过 `dir(cann_bench)` 扫描 `cann_bench/__init__.py` 中定义的 Python wrapper 函数来发现算子。`TORCH_LIBRARY_FRAGMENT` 只把算子注册到 `torch.ops.cann_bench`，但 `__init__.py` 没有对应的 `def exp(...)` wrapper，所以 `dir(cann_bench)` 看不到 `exp`。

- **证据**：
  - 手动 `cp` 更新 `__init__.py` 添加 `exp()` wrapper 后，`scan_interfaces()` 立刻匹配到 `exp`，评测正常执行（`overall_score=31.40`，3/20 cases passed）
  - 手工补 `__init__.py` 前：`scan_interfaces` 只返回 `[add, sqrt]`；补后：返回 `[add, exp, sqrt]`
  - 对比 `add` 算子：`cann_bench/__init__.py` 中已有 `def add(...)` wrapper，故 `add` 能被正常扫描

- **影响范围**：**所有新算子**。任何通过 `self_evolve_op` pipeline 生成的新算子都会碰到此问题——codegen 产出的 `op_plugin/*.cpp` 不更新 `__init__.py`，导致 `kernel_eval` 无法发现新算子。`add`/`sqrt` 等 `__init__.py` 已有 wrapper 的存量算子不受影响。

- **临时绕过**：手动编辑 `cann_bench/__init__.py` 添加 wrapper 函数。**不是方案——是验证时的手动补丁**。

### 关联

- 承接 `h3-design-resolution.md` §1.3 的核心/非核心边界判断：`plugin_code` 是核心（含 `TORCH_LIBRARY_FRAGMENT`），但 `__init__.py` 的 wrapper 函数未进入 codegen 产出契约
- 与 CLAUDE.md 2.7（核心引导归 skill，脚手架外移）一致：`__init__.py` 中 `def exp(...)` wrapper 的模式是跨算子通用（每个算子只需一行 `return torch.ops.cann_bench.<op>(...)`），不是仓特定 boilerplate

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-01 | 初版：记录 P1（`__init__.py` wrapper 断裂点），来自最小环路实跑验证 |
| 2026-07-01 | **P1 已修复**：SKILL.md Step 4 追加「⑥ 算子导出检查」+ codegen prompt 追加对应指引。wrapper 与 CMakeLists.txt 同属非核心脚手架，不进 kernel_architecture 契约，LLM 参考目标仓学习。详见 `h3-design-resolution.md` §4 步骤 7 |

---

## ✅ P2: integrator 过设计 — `kernel_architecture` file-level → section-level

### 事实

- **观测**：当前 `kernel_architecture` 各 section 的 `files[]` 字段列出了每个算子的具体文件名（如 `exp_tiling.cpp`、`exp_infershape.cpp` 等）。这些文件名是机械映射（`{op}_` + 固定后缀），不是设计决策。

- **根因**：integrator（设计 LLM agent）承担了两类不同性质的工作——(a) 设计决策（哪个 section 需要）；(b) 机械映射（section 里的具体文件名）。后者和 CMakeLists.txt 同属"LLM 看参考算子现场学"的非核心内容，不应由另一 LLM agent 专门产出。

- **违反原则**：LLM agent 做机械活（违背 CLAUDE.md 2.7）；过设计——无关信息跨层传递（设计层不应该管 codegen 的文件命名）。

- **修复**：`kernel_architecture` 退到 section-level——只声明 `{section: {directory: "..."}}`，不声明 `files[]`。`_expected_code_files()` 返回 section 目录名，验证改为逐 section 非空检查。具体文件名由 codegen agent 参考目标仓确定（与 CMakeLists.txt 同机制）。

- **改动文件**：`codegen.py`（`_expected_code_files` + `_build_codegen_prompt` + `transition`）；`SKILL.md`（输入/输出/自检/Step 7）

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-01 | P2 记录 + 已修复（连同 P1 一起落地） |

---

## ✅ P3: section 声明归属错误 — `kernel_architecture` 放在设计阶段

### 事实

- **观测**：`kernel_architecture` 的四个 section（host_code / kernel_code / api_code / plugin_code）声明由 integrator（设计阶段 substage）产出。逐一检查每个 section 的必要性：host/kernel 是所有 AscendC 算子的硬需求，api/plugin 取决于目标仓是否要求 ACLNN 注册——**没有一个是来自算子设计的决策**。

- **根因**：section 需求是"目标仓需要什么布局"，不是"这个算子设计决定了什么"。设计阶段不应该知道目标仓的目录约定——同一个算子落到 cann-bench 和 omni-ops，设计产物应该完全一致。integrator 读 repo_profile 产出 section 声明 = 设计阶段耦合了仓特定知识。

- **证据**：
  - host_code / kernel_code：没有算子能以不同方式绕过
  - api_code："这个算子需要 ACLNN 注册"不是设计决策——所有 cann-bench 算子都需要
  - plugin_code：同上
  - 四个 section 的判断可以用 3 行机械规则写完

- **方案**：`kernel_architecture` section 声明移到 codegen 初始化 substage（`codegen_init`），从 design 的 output_contract 中移除。详见 `h3-design-resolution.md` §4.2。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-01 | P3 记录。方案已在 `h3-design-resolution.md` §4 确定，待实施（步骤 9） |
| 2026-07-03 | **P3 已修复**：`CodegenInitStage`（`src/ascendc_devkit/orchestration/stages/codegen_init.py`）落地——确定性 substage，读 `repo_profile` + `design_spec`/`tiling_strategy`，产出 `kernel_architecture`（section 声明，无 files[]）。design substages 不再产出 `kernel_architecture`（`design_substages.py` 明确注释"不再由设计阶段产出，由 codegen_init 确定性生成"），已从 required 降级/移除，改为 optional。三条 pipeline（`workflow.py`）均已插入 `codegen_init` stage，位于 design 与 codegen 之间。383 UT 全绿。 |

---

## ✅ P4: 跨 stage 读信息 — cannbench_adapt 若读 design_spec 会与 codegen 实际签名不一致

### 事实

- **观测**：当前 pipeline 中，cannbench_eval 需要的算子签名（op_name / attrs / dtypes）分散在两个来源——`generated_sources`（代码文件）和 `design_spec`（设计产物）。如果下游 stage 从 `design_spec` 取签名来生成 wrapper，会漏掉 codegen 的中途修正。

- **根因**：`design_spec` 是"预期"签名，codegen 产物是"实际"签名。两者可能因以下原因偏离：
  - codegen 发现硬件不支持某个 dtype（exp 的 bf16 在 Ascend950 上不支持 `AscendC::Exp`）
  - codegen 修正了参数默认值或类型
  - 两者偏离时，`design_spec` 不反映 codegen 的实际决策

- **证据**：实跑 exp 时，`design_spec`（来自 task proto.yaml）声明支持 bf16，但 codegen 在 `exp_tiling_key.h` 中移除了 bf16 模板（Ascend950DT 不支持）。如果 cannbench_adapt 从 `design_spec` 读 dtype 列表，会生成包含 bf16 的 wrapper，与 `_C.abi3.so` 中实际注册的算子不一致。

- **违反原则**：跨 stage 直接读非直接上游的信息 = 隐蔽不一致的根因。下游 stage 的输入应该来自**直接上游的 output_contract**，禁止跳到更上游。

- **方案**：codegen 新增结构化产出 `codegen_manifest`（算子实际签名），cannbench_adapt 从 manifest 读签名而非 design_spec。硬性规则：禁止跨 stage 读取 design_spec。详见 `h3-design-resolution.md` §4.4。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-01 | P4 记录。方案已在 `h3-design-resolution.md` §4 确定，待实施（步骤 10） |
| 2026-07-03 | **P4 已修复**：codegen 新增结构化产出 `codegen_manifest`（`CodegenStage.optional_provides`，含 `callable_target{kind,symbol}`），记录实际采纳签名（不拷贝 design_spec）。新建 `CannbenchAdaptStage`（`src/ascendc_devkit/orchestration/stages/cannbench_adapt.py`）——`input_contract.requires=["generated_sources","codegen_manifest","repo_root"]`，prompt 显式声明"以 codegen_manifest 为准，不是 design_spec"，全文件无一处实际读 `state.design_spec`。下游 `verify.py`/`deploy.py` 同步改读 `codegen_manifest.callable_target`。三条 pipeline 已插入 `codegen_init → codegen → deploy → cannbench_adapt → cannbench_eval`。383 UT 全绿。 |

---

## ✅ P5: 三层评价机制被混淆 — cann-bench 打分被当作算子内层修正的触发器

### 事实

- **观测**：`self_evolve_op` 的 stage 序列是 `codegen → deploy → cannbench_eval`，**没有 verify（build/precision）stage**。整条 pipeline 里，判断"算子对不对"的唯一环节是 `cannbench_eval`——它是 cann-bench 的一次性加权打分（compile 0.2 + function 0.3 + performance 0.5 → overall_score）。

- **根因**：三种性质完全不同的评价机制被塞进了同一个反馈回路：

  | 机制 | 成本 | 语义 | 应归属 |
  |---|---|---|---|
  | ① codegen 内层 loopback（build + loop-precise 快速精度校验） | 最快 | 驱动**单算子自我迭代**到"能跑对" | inference-time，算子自身，与 cann-bench 无关 |
  | ② cann-bench 打分（三维一次性客观分） | 中 | 平台自进化的 **loss 信号**（training-time 的 loss 函数） | training-time，**不回灌 codegen** |
  | ③ 算子全量用例测试 | 最慢 | 生产中**唯一正确性标准**（ground truth） | 最终门禁，太慢，不进迭代循环 |

  ②③ 关系：③ 是真标准但太慢，故用 ② 作**快速代理（proxy loss）**驱动 training-time 迭代（类比 ML 用验证集指标代替全测试集指导训练）。① 与 ②③ 均独立——靠自身 build/precision 信号收敛。

- **证据（代码里的错配）**：
  - `CannbenchEvalStage.resolve_condition()` 返回 `"eval_failed"`（overall_score==0 时），`SelfEvolveOpWorkflow.TRANSITION_TABLE` 把 `eval_failed → ("codegen", "corrective")`。即：**把 loss 信号 ② 当成了算子内层修正 ① 的触发器**。
  - `CannbenchEvalStage.transition()` 在 score==0 时注入 `last_error(error_type="eval_failed")`，喂给 codegen 的 loopback prompt。cann-bench 的职责是"出一次分"，注入 last_error 触发重生成越界。
  - `DeployStage.resolve_condition()` 返回 `"deploy_failed" → ("codegen", "corrective")`。deploy 属于"编译+安装"链，是否算 ① 的一部分待定，但当前它和 ② 一样都直接回灌 codegen，边界不清。
  - self_evolve_op 缺失 verify stage，`codegen` 的 `build_result`/`precision_result` 反馈通道（`_build_codegen_prompt` 的"修正任务"分支）在这条 pipeline 里**没有任何 stage 喂数据**——即 ① 内层修正回路实际上是断的。

- **影响范围**：整条 self_evolve_op pipeline 的正确性语义。当前实现下：算子没有内层修正回路（① 断），却把一次性 loss 打分误当修正触发器（② 越界回灌）。这与 `self-evolution-design.md` §2.2 两层迭代模型不符——文档明确 (a) inference-time 单算子修正是**已有能力**、独立于评测器，(b) training-time 才用 loss 迭代。

- **临时状态**：`eval_failed`/`deploy_failed` 的 `resolve_condition` + `last_error` 注入是上一轮误加的代码，尚未提交（工作树未 staged 改动）。

### 关联

- 违背 `self-evolution-design.md` §2.2（两层迭代）、§2.4（中间 loss 禁止用 LLM 主观打分、评测器职责单一）、P4/P5 原则（评测器可插拔、减少模型依赖）。
- 与 `avoid-overdesign-prefer-reuse` 记忆一致：① 的内层修正应复用 generate_ascendc 已有的 verify→codegen loopback，而非在 cann-bench 上另造一套。
- 方案分析见 `07-eval-vs-correction-analysis.md`（L3，替代已废弃的 `codegen-loopback-analysis.md`）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-01 | P5 记录：三层评价机制混淆，cann-bench 打分被误当算子内层修正触发器。用户确认三层拆分正确。 |
| 2026-12-09 | **P5 已修复**：三层评价机制按 `07`（L3）拆分落地——deploy 通用化为纯确定性 stage（不接 LLM 自救，见 P6/P7 变更记录 G4/G5），`eval_failed`/`deploy_failed` 不再越界回灌算子内层修正，① 内层回路改走真实 verify（见 P6）。详见 `10-generate-ascendc-deploy-impl.md` G4/G5/G6。 |

---

## ✅ P6: verify 精度校验是 CPU 桩 — 从不部署、从不在 NPU 上跑真 kernel

### 事实

- **观测**：`VerifyStage` 的 `PrecisionGate` 委托 `NPURunner.execute()` 做精度校验，但 `NPURunner._build_test_harness()` 生成的测试脚本**只在 CPU 上运行 golden 参考实现、与自身比较**，从不导入部署产物、不调 `torch.ops`、不在 NPU 核上执行算子 kernel。

- **证据（harness 逻辑）**：
  - harness 只加载 golden 模块并调 `golden_fn(input_data)`，随后 `results[shape] = 0.0`，注释明写 `# Golden validated against itself → max_diff = 0.0`。
  - 留有明确 TODO：`# NPU kernel comparison requires compiled .so integration (TODO). When the compiled kernel is available, call it on NPU with the same input and compute diff = |kernel_output - golden_out|.`
  - 输出 `max_diff` 恒为 `0.0`、`bottleneck='golden_reference_only'`。`NPURunner.execute()` 只要 harness 子进程 returncode==0 就返回 `passed=True`。
  - 即：verify 精度的"通过"实际只证明"golden 能加载、能在 CPU 跑完不抛异常"，**未验证算子 kernel 的正确性**。

- **根因**：verify 精度链缺少"部署产物 → NPU 调用 → 与 golden 比对"的真实闭环。真部署是仓强相关的（`DeployStage` 的 `build.sh → 装 opp → pip 装 whl → smoke`，注册到 `torch.ops.cann_bench`），而 `NPURunner` 独立于 DeployStage 自造了一套只跑 golden 的 harness，二者未打通。

- **影响范围**：
  - ① 内层精度修正回路即使接上，也拿不到真实精度信号——`precision_result` 永远 `passed=True, max_diff=0.0`，codegen 的精度修正分支永不触发，回归无法察觉任何精度错误。
  - 违背 CLAUDE.md 3.9（真实链路必须有真实测试守护）、3.10（真实用例不得退化成 mock）——当前精度校验退化成了自比桩。
  - 直接制约 P5 目标态：P5 要把 verify 作为 ① 内层修正回路插入 self_evolve_op，但若 verify 精度是桩，插入后回路仍是空的。**P6 是 P5 落地的前置。**

- **与 deploy 的顺序关系**：精度要跑真 kernel，必须先部署成 `torch.ops` 可调用。故正确 pipeline 是 `codegen → deploy → verify → cannbench_eval`（verify 在 deploy **之后**），verify 精度复用 deploy 产物跑真 kernel，而非 `NPURunner` 另起炉灶。

### 关联

- 阻塞 P5 落地（verify 作为 ① 回路的前提是精度真实）。
- 方案分析见 `07-eval-vs-correction-analysis.md`（L3）；实施见 `08-impl-eval-correction-split.md`（L4）。
- 与 `avoid-overdesign-prefer-reuse`：真 kernel 执行应复用 DeployStage 的部署产物（`torch.ops.cann_bench`），不在 `NPURunner` 里重造部署。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-01 | P6 记录：verify 精度是 CPU 桩（golden 自比、`max_diff` 恒 0、从不跑真 kernel），是 P5 落地的前置阻塞。 |
| 2026-12-09 | **P6 已修复（cann-bench 先行）**：`NPURunner.execute()` 改吃真实 `deploy_result`/`callable_target`，harness 重构为数据驱动 n-ary、`passed = max_diff <= threshold`（真精度判定，桩 `max_diff=0` 彻底消除）。真机验证：部署 `add` 后 `a+b` golden 过（max_diff=0.0）、`a-b` golden 挂（max_diff=1.92）。详见 `10-generate-ascendc-deploy-impl.md` G7。 |

---

## ✅ P7: P6 是全 workflow 通病 — `generate_ascendc`/`_dev` 算子根本没有"可调用"通路

### 事实

- **观测**：P6（verify 精度是 CPU 桩）不是 self_evolve_op 独有——`verify` 是被 `generate_ascendc`、`generate_ascendc_dev`、`self_evolve_op` **共享**的 stage。三条 pipeline 的精度校验都走同一个桩 harness，`max_diff` 恒 0。但要把 harness 改成"跑真 kernel"，三条 pipeline 的处境**根本不同**：只有 self_evolve_op 有 `deploy` stage 把算子注册成 `torch.ops.cann_bench.<op>` 可调用；`generate_ascendc`/`_dev` **没有任何 stage 把编译产物变成可调用 kernel**。

- **证据（调查代码库得出）**：
  - **无 deploy stage**：`DeployStage` 只挂在 `_SELF_EVOLVE_STAGE_NAMES`。`generate_ascendc`/`_dev` 的 stage 序列止于 `codegen → verify → perf → integrate`，无部署环节。
  - **build 只出产物、不出可调用**：`verify` 的 build 门 `BuildInRepoGate` 调 `adapter.build()`（`GenericRepositoryAdapter.build`），后者仅 `subprocess` 跑各 variant 的 `command_template`（如 ops-nn 的 `bash build.sh --pkg --soc=... --ops=...`）返回 `BuildResult(passed/stdout/stderr/artifacts)`。**从不装 opp、不设 `ASCEND_CUSTOM_OPP_PATH`、不 pip 装 whl、不注册 torch op**。build 通过后 Python 端仍无任何可 import/可调的东西。
  - **adapter 协议无 deploy 能力**：`RepositoryAdapter` ABC 只有四个抽象方法——`materialize_new_operator` / `scan_existing_operator` / `build` / `write_dev_record`。**没有 deploy/install/register/load**。适配层职责止于"就地编译"。
  - **spec/profile 都不带"调用目标"**：`OperatorSpec`（name/inputs/outputs/attrs）、`OperatorIdentity`（repo_root/op_dir/files）、`BuildResult`、`RepositoryProfile`/`profile.json` schema **均无 namespace / 调用符号 / 注册约定字段**（schema `additionalProperties:false` 明确禁止）。即便算子被部署了，harness 也无从知道该调 `torch.ops.cann_bench.X` 还是 `torch.ops.custom.npu_X` 还是某个 aclnn API。
  - **注册知识只在手动 skill 里、未接线**：唯一记录 ops-nn/omni-ops 注册路径的是 `ascendc-pta` skill（三仓集成 / `torch_ops_extension`），**是人工 skill，任何 stage 都不调用**。omni-ops profile 虽有 `torch_ext` stage 但 `enabled: false`。
  - **DeployStage 硬编码 cann-bench**：`_step_smoke` 写死 `import cann_bench; torch.ops.cann_bench`，构建路径写死 `examples/aclnn_launch_example` + `dist/*.run` + `dist/*.whl`。不能直接复用到 ops-nn/omni-ops。

- **根因**：DevKit 对 `generate_ascendc` 算子的自动化止于"就地编译"。"编译产物 → 可调用 kernel"这一步（装 opp、PTA/torch 注册、暴露 namespace）**没有任何自动化通路**，也没有数据结构承载"该调什么符号"。self_evolve_op 能跑真 kernel 纯粹因为它借了 cann-bench 仓专用的 DeployStage + 写死的 `torch.ops.cann_bench` 约定。

- **影响范围**：
  - Step P（修 P6）若要覆盖全 workflow，前提是先给 `generate_ascendc`/`_dev` 补齐"部署→注册→可调用"通路 + "调用目标描述符"——这需要**扩 `RepositoryAdapter` 协议 + 扩 `profile.json` schema + 为 ops-nn/ops-transformer/omni-ops 各写一个 DeployStage 类比**，远超 07/08 当前范围。
  - 在补齐之前，`generate_ascendc`/`_dev` 的 verify 精度**没有真实信号可取**：要么继续桩（违背 3.9/3.10），要么诚实报错（precision 无法在无部署下跑真 kernel）。

### 关联

- P7 是 P6 的上位泛化：P6 记录"harness 是桩"，P7 记录"修桩在 generate_ascendc 上缺前置通路"。
- 用户决策：一并修 generate_ascendc（而非只修 self_evolve_op），但该选项本身要求"先补写方案"——故 Step P 暂停，先做 P7 的 L3 方案分析。
- 方案分析见 `09-generate-ascendc-precision-path.md`（L3，D6 deploy 放 adapter 协议 / D7 callable_target 由 deploy 产出 / D8 无 deploy 仓诚实报错 + 分期）。
- 触及 CLAUDE.md 1.6（依赖注入 — adapter 协议扩展）、2.7（脚手架外移 vs 核心引导）、1.4（不留兼容层）。
- 调查结论详见本轮 general-purpose agent 的只读调研（未落文件，结论已并入本条）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-01 | P7 记录：P6 是全 workflow 通病；`generate_ascendc`/`_dev` 算子无"编译产物→可调用 kernel"通路，无调用目标描述符。修 P6 覆盖全 workflow 需先补部署/注册通路 + 协议/schema 扩展，超出 07/08 范围。 |
| 2026-12-09 | **P7 已修复（cann-bench 先行，其余仓诚实延后）**：`RepositoryAdapter` 协议 + profile schema 扩展 `role` 声明式 deploy stages（G2）；三条 pipeline 统一插入 `deploy` stage（codegen→deploy→verify，G6）；cann-bench 的 build/install_runtime/install_python/smoke 四 role stage 落地，`has_deploy_capability=True`（G3）。**ops-nn/ops-transformer/omni-ops 的 per-op 安装路径 + 注册命令依赖目标仓现场核实，按 D8"不桩/不猜"原则明确延后**——`_preflight_deploy_capability` 对这三仓的 deploy-requiring workflow 诚实报错（`has_deploy_capability=False`），不落桩、不猜命令。1421 UT + 100 ST（含 @npu/@slow 真 kernel 精度守护）全绿。详见 `09-generate-ascendc-precision-path.md`（D6/D7/D8）、`10-generate-ascendc-deploy-impl.md` G1–G7。 |

---

## ✅ P8: `TestCase` 不承载 attrs + harness 不传 attrs → 带 attrs 算子只测默认分支

### 事实

- **观测**：`TestCase`（domain/requirement）字段只有 `inputs`/`expected`/`generator`/`generator_params`，**无 attrs**。`NPURunner._build_test_harness` 生成的脚本对每个 case 只 `kernel_fn(*_npu_inputs)` 与 `golden_fn(*_np_inputs)`——**只按位置传张量，不传 attrs**。
- **根因**：`OperatorSpec` 已建模 attrs（`attrs: dict[str, AttrSpec]`，`from_dict` 专门把"张量 vs attrs"拆开），但 `TestCase` 这一层把 attrs 丢了——用例模型与算子规格在 attrs 维度不对齐。带 attrs（base/scale/shift）的算子，用例若不指定 attrs 值，kernel/golden 调用就只走默认分支。
- **证据**：exp 算子 proto 声明 base/scale/shift；但无论 test_design 产什么用例、golden 怎么写，harness 实际调用都是 `exp(x)`（默认 base=-1/scale=1/shift=0）。`exp(x, base>0)` / `exp(x, scale=1.5)` / bf16 等分支从不被 ① verify 触达。
- **影响范围**：**所有带 attrs 的算子、所有 workflow**（generate_ascendc / _dev / self_evolve_op 共享同一个 verify + `TestCase`）。不是 cann-bench 特有——是 test-case 模型的**既有缺陷**，独立于任何 cann-bench 对齐工作而存在。

### 关联

- 阻塞 P10（cann-bench 用例对齐）：cann-bench `cases.csv` 的用例恰靠 attrs 区分，`TestCase` 装不下 attrs 则对齐无意义。
- 方案见 `11-external-golden-cases-adapter.md`（L3）D7：P8 是 P9/P10/cann-bench 对齐的**共同前提**，须先修。
- 属通用缺陷，修复让所有 workflow 的 test_design/verify 都能真正测 attrs 分支。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-02 | P8 记录：`TestCase` 缺 attrs + harness 不传 attrs，带 attrs 算子只测默认分支。通用既有缺陷。 |
| 2026-07-02 | **P8 已修复**：`TestCase` 增 `attrs` 字段（A1）；harness 生成把 attrs 当 kwargs 透传给 kernel/golden，attrs 空时退化为纯位置参数零回归（A2）。详见 `12-...-impl.md` A1/A2。 |

---

## ✅ P9: 不能消费外部参考 golden，须手写凑 harness 契约

### 事实

- **观测**：harness 加载 `--golden` 文件后，只接受名为 `reference`/`run`/`compute` 的入口（回退链，取首个命中），且期望调用方传 numpy。cann-bench 的 `tasks/level<N>/<op>/golden.py` 入口函数名是**算子名**（如 `exp`）、期望 **torch.Tensor**——契约不匹配，cann-bench 的 golden **不能被 verify 直接消费**。
- **根因**：缺少"把任意源 golden 适配成 harness 规范入口"的能力。现状靠人手写（如 `tests/fixtures/add_golden.py` 的 `def reference(a, b)`）逐算子凑契约。
- **证据**：若直接把 cann-bench `golden.py` 当 `--golden`，harness 取不到 `reference`（函数名是 `exp`）→ `golden_fn=None` → 不做真比对 → `max_diff` 恒 0 → 假性 `passed=True`——**退化成 P6 已消灭的自比桩**。
- **影响范围**：通用。generate_ascendc 每个算子都得手写 golden；self_evolve_op 想复用 cann-bench 的权威 golden（避免与 ② 漂移）做不到。

### 关联

- 方案见 `11`（L3）golden-adapter（D1 代码非 LLM / D2 通用 / D3 契约驱动 harness 生成）。
- 依赖 P8：harness 要能传 attrs，否则适配后的 golden 仍只测默认分支。
- 与"golden 漂移"担忧的关系：适配器**直接 import 源 golden**（单一真相源），cann-bench 改 golden 这边自动跟随，物理上不可能漂移。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-02 | P9 记录：无外部 golden 适配能力，须手写凑 reference/numpy 契约；cann-bench golden 因函数名/类型不符无法直连。 |
| 2026-07-02 | **P9 已修复**：profile 增 `golden_source` 契约（A3）；golden-adapter 契约驱动 harness 生成——按 `{op}` 入口归一 + `input_type` 做 numpy↔torch 转换 + 包成单一 `reference`，收口 `run`/`compute` 回退（A4）；verify 优先 user `--golden`、其次 profile `golden_source`（A7）。NPU 真机 ST 守护（torch golden 契约 max_diff 真实非 0）。 |
| 2026-07-03 | **修复方式修订**：profile 预置 `golden_source`（用 `{op}`/`{N}` 代换）是架构错位（见 P11）——仓级 profile 承载算子级参数。golden 来源改为 CLI 显式三参（`--golden` + entry/input_type），删 profile 预置 + 代换逻辑。详见 `13`（L3）/`14`（L4）。 |

---

## ✅ P10: test_design 只能 LLM 自设计用例，无消费外部用例的通路

### 事实

- **观测**：`TestCaseGenStage`（test_design 子阶段）由 LLM 产出用例 → `state.test_cases`。**没有任何 stage 能从外部用例源（如 cann-bench `cases.csv`）加载用例**。
- **根因**：test-case 来源只有"LLM 设计"一条通路，缺"外部用例 → `TestCase`"的桥接。
- **证据**：grep 全仓无 `cases.csv` 解析；self_evolve_op 的 ① verify 用例完全由 test_design LLM 生成，与 cann-bench 实际评测用例（`cases.csv`）无关——① 过了不保证 ② 过（用例集不重合）。
- **影响范围**：self_evolve_op 想让 ① 对齐 ②（用 cann-bench 用例）做不到；generate_ascendc 暂无外部用例需求（test_design 即可）。

### 关联

- 方案见 `11`（L3）cases-loader（D4 代码非 LLM / D5 通用 loader 按 format 分派，首版只 `cann_bench_csv`，不预先抽象第二种）。
- 依赖 P8：`TestCase` 要能装 attrs，否则 cann-bench 用例的 attrs 维度被丢。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-02 | P10 记录：无外部用例消费通路，test_design 只能 LLM 自设计；self_evolve_op 的 ① 无法对齐 ② 用例。 |
| 2026-07-02 | **P10 已修复**：profile 增 `cases_source` 契约（A3）；cases-loader 按 format 分派，首版 `cann_bench_csv` parser（含 attrs/value_range→generator_params，A5）；`TestCaseGenStage` 在有 `cases_source` 且该算子存在 cann-bench task 时短路（NoOp、不调 LLM）加载用例，`{N}` 由 `resolve_task_level` 按存在性确定（A7）。cann-bench profile 声明双 source（A6）。真实 exp cases.csv 解析 ST 守护。 |
| 2026-07-03 | **修复方式修订**：profile 预置 `cases_source`（用 `{op}`/`{N}` 代换）是架构错位（见 P11）。cases 来源改为 CLI 显式（`--cann-bench-cases`，参数名编码格式），删 profile 预置 + 代换/探测逻辑。详见 `13`（L3）/`14`（L4）。 |

---

## ✅ P11: 仓级 profile 承载算子级 golden/cases 参数（用 `{op}`/`{N}` 代换）是架构错位

### 事实

- **观测**：A3–A7 落地后，`cann-bench.yaml` 声明 `golden_source`（path=`tasks/level{N}/{op}/golden.py`、entry=`{op}`、input_type=torch）+ `cases_source`（format=cann_bench_csv、path=`tasks/level{N}/{op}/cases.csv`）。仓级 profile 用 `{op}`/`{N}` 模板承载**算子级**参数（每个算子的 golden 路径/入口、cases 内容各异），运行期由 `resolve_task_level` 探测 `{N}` + `{op}` 代换还原成具体文件。
- **根因**：profile 是**仓级**配置（描述整个仓的布局/构建/命名），而 golden/cases 是**算子级**输入（每算子不同）。用仓级模板代换算子级差异，本质是把"本该算子级指定的参数"塞进仓级配置、再运行期代换回来——违背 CLAUDE.md 2.7（算子特定不固化进通用配置）+ 1.5（算子知识不进配置）。
- **凭什么说错**：
  - 为这套代换/探测存在的"多余解析逻辑"：`GoldenSource`/`CasesSource` dataclass 及其 `.resolve()`、profile schema 的 `golden_source`/`cases_source` 段及加载校验、`resolve_task_level`（`{N}` 存在性探测）、verify 的 `_resolve_golden_contract` 的 profile 分支、test_design 的 `_task_level`/`_has_external_cases`——一整套只为"把算子级参数从仓级配置代换回来"。
  - 预置=把 cann-bench 的目录约定固化进 DevKit profile；仓改目录就静默漂移（找不到文件→退化为无 golden→报错或迫使传 `--golden`）。
  - `golden_source` 是路径模板，加载期校验不了"运行期文件在不在"，1.3 加载期校验对它失效。
- **影响范围**：A3–A7 已落地代码（`golden_source`/`cases_source` 预置 + 代换/探测逻辑）。修订为算子级参数走 CLI 显式，删除整条代换/探测通路。

### 关联

- 修订 P9/P10 的**修复方式**（非问题本身）：从"profile 预置 + 代换"改为"CLI 显式"。详见 `13`（L3）/`14`（L4）。
- 与 deploy 通用化（D6-2）的边界：deploy 的仓特定部分（build/install 命令）确为**仓级**一致（同仓算子构建方式相同），进 profile 合理；golden/cases 是**算子级**，不该进 profile。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P11 记录：仓级 profile 承载算子级 golden/cases（用 `{op}`/`{N}` 代换）是架构错位；一整套代换/探测逻辑多余；预置静默漂移；加载期校验对路径模板失效。修订 P9/P10 修复方式（见 13/14）。 |
| 2026-07-03 | **P11 已修复**：B1–B9 全部实施完成——golden/cases 来源改 CLI 显式三参（`--golden`+entry/input_type、`--cann-bench-cases`），删净 profile 预置层（`GoldenSource`/`CasesSource`/`resolve_task_level`/schema 段/代换逻辑）。UT 1482 + ST 124（含 @npu 10 + @llm 13 + @slow）全绿。详见 `14-golden-cases-cli-refactor-impl.md`。 |

---

## ✅ P12: golden 被窄化为 verify 专属，应有定位是全链路参考实现

### 事实

- **观测**：现状代码里 `state.golden_path` 只被 verify stage 的 PrecisionGate 消费；design stages 不读 golden。golden 被当作"verify 的精度比对基准"。
- **根因**：对 golden 角色的认知窄化。golden 的应有定位是**算子的参考实现 / 语义权威**——design 阶段据 golden 做设计（算法/公式依据），后续 design 阶段甚至提前用 golden 做仿真验证（codegen 前比对设计正确性），verify 阶段用 golden 做精度比对。即 design 与 verify **共享** golden，性质类似 requirement（全链路输入），非 verify 专属。
- **凭什么这么说**：
  - design 做 kernel 设计须有"算子应该怎么算"的权威依据，golden 正是此依据（参考实现）；无 golden 的设计缺正确性锚点。
  - 后续 design 阶段提前仿真验证（用 golden）的能力，已在其他 SE 的系统初步实现（不在本仓）；本仓 design stages 暂未消费 golden，但应有。
  - 把 golden 绑 verify（如"无 verify 拒传 golden"拓扑、"含 verify 才校验 golden"）会阻碍 design 消费 golden。
- **影响范围**：
  - golden 机制（CLI 承载 + State 字段 + 早期校验 + 必选判据）不能绑 verify，须全链路可见、凡用 golden 的 workflow 都覆盖。
  - 当前仓 design stages 未消费 golden（SE 仿真在别处），但机制要为接入留通路。
  - golden 必选判据：做 design 或 verify 的 workflow 都必选（golden 是设计依据 + 验证基准）。

### 关联

- 详见 `13`（L3）E4（golden 全链路角色）/ E6（必选判据）。
- 与 P11 协同：golden 来源改 CLI（算子级参数归位）+ 角色正名为全链路，一并修订。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P12 记录：golden 被窄化为 verify 专属（现状只 verify 消费）；应有定位是全链路参考实现（design 参考/仿真 + verify 比对）；design stages 当前未消费（SE 仿真在别处系统）；必选判据=做 design 或 verify 的 workflow。详见 13/14。 |
| 2026-07-03 | **P12 已修复**：E4/E6 定案并随 B1–B9 一并实施——golden 角色正名为全链路参考实现（设计依据+验证基准），必选判据按"做 design 或 verify 的 workflow"声明式生效，`GeneralDesignStage`/`DetailedDesignStage` 视线路径纳入必选校验。详见 `13-golden-cases-cli-refactor.md` E4/E6、`14-golden-cases-cli-refactor-impl.md` B3。 |

---

## ✅ P13: docgen 确定性渲染器未装载 `kernel_pseudo_code`，终稿「Kernel 架构」节为空

### 事实

- **观测**：一次完整 `e2e_self_evolve` 运行（日志 `logs/e2e_self_evolve_20260703_200702.log`）中，最终 `design_doc.json` 的 markdown 末尾「## Kernel 架构」标题之后**无任何内容**。validate 反复报告 `GV8A-001`：终稿「Kernel 架构」节为空。
- **产物侧事实**：上游 `tiling_results.json` 的 `T1.buffer_kernel.kernel_pseudo_code` 含 **5 个 kernel 函数的完整伪码**（`init` / `copy_in` / `compute` / `copy_out` / `main_loop`，每函数带 cpp 代码块）——内容**已产生**，并未缺失。
- **渲染侧事实**：`DocgenStage._render_detailed` 在「Kernel 架构」段只做两件事——渲染 `kernel_architecture.pipeline` 的 Mermaid 图、原样 dump `kernel_architecture` JSON。`kernel_architecture.json` 本身**没有** pseudocode 字段（只有 host_code/kernel_code 的 responsibilities 文字描述、buffer_allocation、sync_model、base_routing_table、precision_chain）。即渲染器从未读取 `tiling_results.*.buffer_kernel.kernel_pseudo_code`。
- **凭什么说这是渲染缺陷而非产物缺失**：权威内容存在于 `tiling_results`，缺失仅发生在「产物 → 终稿」的组装环节。`ascendc-op-design-docgen` SKILL.md 与 `section_mapping_convention.md` 均要求「Kernel 设计节须全量装载 buffer_kernel 的 Kernel 伪代码节（禁摘要、禁省略函数）」——确定性渲染器未实现这段装载逻辑。
- **影响范围**：所有走 `self_evolve_op`（及任何含 docgen→validate 闭环的 workflow）的算子。只要算子有 kernel 伪码，终稿「Kernel 架构」节必然为空。

### 关联

- 直接触发 P14（validate 把此问题 route 给 docgen）与 P15（loopback 无法收敛）。
- 与 CLAUDE.md §2.5「唯一通路，不留旧债」相关：docgen 的实现机制已从 agent-based 组装改为确定性渲染，但「全量装载 kernel_pseudo_code」这条旧通路的职责未在新机制中落地——迁移未收口。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P13 记录：确定性 docgen 渲染「Kernel 架构」节时不读 `kernel_pseudo_code`，终稿该节为空；产物侧 5 函数伪码完整存在，属组装环节内容丢失。 |
| 2026-07-03 | **P13 已修复**：`DocgenStage._render_kernel_pseudocode` 装载 `tiling_results[*].buffer_kernel.kernel_pseudo_code`，渲染 overview + 5 函数（各带 description + ```cpp 代码块）入「Kernel 架构」节，多模板时按 `### 模板《T》` 分节。schema（`design_doc.json` 的 sections/mermaid_sources）不变，伪码只进 markdown。TDD：`test_docgen_render.py::TestKernelPseudocodeRender` 5 用例先红后绿。详见 `16-docgen-deadlock-impl.md` 改动1。 |

---

## ✅ P14: GV8-A 规则把「内容丢失」route 给确定性的 docgen —— target 语义与 stage 性质矛盾

### 事实

- **规则侧事实**：`ascendc-op-design-validate` SKILL.md 的 GV8-A 规则明文规定——终稿「Kernel 设计」节函数缺失/仅散文摘要属「内容丢失」，**不可由 validate 就地补全**，须记录到报告并指明「由 docgen 按全量装载规则重新组装」。validate reviewer 据此在 `blocking_status.json` 写 `target: docgen`。
- **路由侧事实**：`ValidateStage.resolve_condition` 把 `target=docgen` 映射为条件 `redo_doc`；转移表 `_DETAILED_DESIGN_TRANSITION_TABLE` 中 `"redo_doc": ("docgen", "corrective")` → loopback 目标钉死在 docgen。
- **stage 性质事实**：`DocgenStage` 是**确定性渲染器**——`actions` 返回空列表、不 spawn agent、渲染在 `transition` 中同步完成、输出是输入的纯函数（相同输入 → 相同输出，无采样随机性）。它既不读 GV8-A 所指的「全量装载规则」，也无从「重新组装」内容。
- **凭什么说矛盾**：GV8-A 规则的修复意图是「让能产生/重组内容的 stage 重新装载」，但其钉死的 target（docgen）在当前架构下结构上不可能履行该意图——一个不产生内容的确定性渲染器无法修复「内容未装载」。规则文本停留 docgen 还是 agent-based 组装器的时代，未随 docgen 确定性化（P13 所述迁移）同步更新 target 语义。
- **影响范围**：所有被 GV8-A 判为「内容丢失」的 case。只要 P13 未修，GV8-A 必然触发，且其 target 必然指向无法修复它的 docgen。

### 关联

- 上承 P13（内容丢失的源头），下接 P15（矛盾导致 loopback 死循环）。
- 与 CLAUDE.md §1.2「方案合理性」、§2.5「不留旧债」相关：route 决策的不变式（「target 必须是结构上能修复该问题的 stage」）未被任何层强制。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P14 记录：GV8-A 规则 target 钉死 docgen，而 docgen 已是确定性渲染器（无 agent、无内容重组能力），target 语义与 stage 性质矛盾，结构上不可达。 |
| 2026-07-03 | **P14 已修复（随 P15 兜底A一并落地）**：不再试图让 target 语义与 docgen 性质相容——`redo_doc` 边改为直接 `__halt__`，矛盾路由不再被执行，一次命中即停转人工 triage。GV8-A 规则文本未改（规则本身仍写"由 docgen 重新组装"），但路由层不再机械执行这条不可达指令。详见 P15 变更记录、`16-docgen-deadlock-impl.md` 改动2。 |

---

## ✅ P15: loopback 框架无「target 可达性 / 产物无进展」校验，确定性 stage 死循环至超时

### 事实

- **观测**：上述运行中 `events.jsonl` 记录 `validate → docgen` corrective loopback 共 **3 次**（count=1/2/3，max=3）。每次 docgen 耗时仅 6–23ms（确定性渲染，零实质工作），产出的 `design_doc` 与上一轮**逐字相同**。validate 随即再次报告同一 `GV8A-001`（`blocking_status.json` 自标「Retry #7 — same issue since attempt #1」）。三轮 validate 累计耗时约 599s + 533s + 622s。
- **框架侧事实**：`GraphExecutor` **确有**停滞检测——同一 `(from→to, error_signature)` 出现 ≥2 次即停止 corrective（记 `stagnation` 事件后前进），但它**依赖 stage 主动提供 `error_signature(state)`**。grep 证实仅 `verify` 定义了 `error_signature`，`ValidateStage` 未定义 → validate loopback 时 `sig=""` → 停滞检测的 `and sig` 条件不成立、整段跳过，故 validate→docgen 走完 3 次 `max_corrective` 配额。另：`Node` 级只有次数配额，无被动产物 hash 比对；`max_no_progress` 配置只作用于单 agent resume 不出新文本，不作用于 stage 间 loopback。
- **凭什么说框架未防御**：loopback 的隐含前提是「重试有期望收益」——对 LLM stage 成立（采样随机性 / loopback_feedback 注入新信息可使重决策产出不同结果），对「输入未变的确定性 stage」**数学上不成立**（纯函数相同输入必然相同输出）。框架虽有停滞检测机制，但接入是 opt-in（要 stage 提供 `error_signature`），gate stage 未接入即等于无防护；且无被动的加载期 target 可达性校验。P14 的不可达路由因此能无阻力地走完 3 次配额。
- **影响范围**：任何「确定性 stage 被 loopback target 命中且其输入未因 loopback 改变」的情形，必然死循环至 `max_corrective` 耗尽。P13/P14 是当前已知触发点，但不变式缺失是框架级通用缺口。

### 关联

- 上承 P13/P14（触发源）；直接造成 P16（超时致下游全跳过）。
- 与 CLAUDE.md §1.3「加载期校验优于运行期暴露」相关：target 可达性属可在加载期（转移表注册时）静态校验的不变式；停滞检测属运行期机制（已存在，需 gate stage 接入）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P15 记录：loopback 框架既无加载期 target 可达性校验、也无运行期产物无进展检测；确定性 stage 在输入不变时被 loopback 必然死循环，3 轮配额被无效烧尽。 |
| 2026-07-03 | **修复方向修订**：原计划接入既有停滞检测（`ValidateStage.error_signature`，2 次后停 corrective 并前进到 codegen）被推翻——"停滞后前进"等于把已确认的「终稿内容丢失」错误静默吞掉、推给下游，违反 CLAUDE.md §1.2。改为：`validate` 对 `docgen` 的这条 corrective 边直接改为 `__halt__`（不尝试 loopback，一次命中即停，走人工 triage）。停滞检测机制本身不变、不接入本条边（因为本条边根本不该发生 loopback）。详见 `15-docgen-deadlock-analysis.md`（L3）§2 事实 6/7、§3.2 修订版。 |
| 2026-07-03 | **P15 已修复（兜底A）**：`design_tree.py` 的 `_DETAILED_DESIGN_TRANSITION_TABLE["validate"]["redo_doc"]` 从 `("docgen", "corrective")` 改为 `("__halt__", "escalation")`——纯数据改动，复用既有 scope-agnostic `__halt__` 原语，`ValidateStage.resolve_condition`/`GraphExecutor` 未改。TDD：`test_design_routing.py::TestValidateDocgenHalt` 先红后绿；`test_design_routing.py`(7) + `test_graph_executor.py`(16) + 全量 `tests/ut/orchestration/`(776) 回归通过，`TestAnchorLoopback`/`TestReviewBubbleUp` 等既有 loopback/bubble-up 路径未受影响。详见 `16-docgen-deadlock-impl.md` 改动2。 |

---

## ✅ P16: workflow 超时在 design 死锁中耗尽预算，codegen/compile/test/deploy/verify 全跳过并回滚

### 事实

- **观测**：上述运行末尾 `[ERROR] Timeout: Workflow timeout: exceeded 3600s budget (ran 3626.9s)`，触发 `workflow_timeout`（stage=docgen）与 `stage_aborted`（docgen, error_type=WorkflowTimeoutError）。随后 `repo_rollback` 把算子目录恢复到运行前 HEAD。
- **下游事实**：整条 pipeline 停在 `detailed-design` 组内 docgen→validate 死锁，**从未到达** codegen / compile / test / deploy / cannbench_adapt / verify 中的任何一个。
- **凭什么说是 P13–P15 的衍生影响**：超时不是独立根因，而是 P13（内容丢失）→ P14（不可达路由）→ P15（无收敛校验）叠加后，3 轮 loopback 配额不足以让确定性 docgen 产出不同结果，剩余预算被 validate 的高成本全量重验（见 P18）吞噬，最终在 docgen 处撞 3600s 墙。死锁本身不消耗下游预算——它让下游永远得不到执行机会。
- **影响范围**：self-evolve 的「设计 → 代码 → 编译 → 测试 → 部署 → 评测」闭环在 design 阶段即断裂，平台北极星（生成生产级算子）在该 run 上零产出。

### 关联

- 衍生自 P13/P14/P15；修上游三者即消除本超时。
- 与 CLAUDE.md §3.6「默认全量真实环境模式」、闭环完整性相关：闭环在 design 断裂 = 整条 self-evolve 链路在该 run 无有效产出。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P16 记录：3600s 预算在 docgen→validate 死锁中耗尽，下游 5 个 stage 全未执行并触发 repo_rollback；属 P13–P15 的衍生影响，非独立根因。 |
| 2026-07-03 | **P16 随 P13/P15 修复而消除**：死锁根因（内容丢失+不可达路由+无收敛校验）已修，`redo_doc` 一次命中即 `__halt__`，不再有 loopback 空转烧尽预算的路径。未新增超时预算或重试上限改动——是死锁消除的直接结果，非独立修复。 |

---

## ✅ P17: docgen 确定性「空动作」触发 WARN 误报，诊断信号失真

### 事实

- **观测**：上述运行中 `Stage '.../docgen/docgen' produced no actions with no skip_reason (possible bug or misconfigured stage)` WARN 出现 **4 次**（初始 + 3 次 loopback）。
- **stage 侧事实**：`DocgenStage.actions` 返回空列表是**预期行为**——该 stage 是确定性渲染器，工作在 `transition` 中完成，不 spawn agent。空动作并非 bug。
- **凭什么说信号失真**：WARN 文案把「有意为之的空动作」与「bug / 配置错误导致的空动作」混为一谈。确定性 stage 未声明 `skip_reason`（或等价的「确定性渲染、无需 agent」标记），导致框架无法区分二者，每次 loopback 都误报。在本 run 中，4 次误报 WARN 反而掩盖了真正的异常（P13/P15）——观察者会被 WARN 噪声干扰，错过死循环信号。
- **影响范围**：所有确定性 stage（当前仅 docgen）。每次被 loopback 命中就多一条误报。

### 关联

- 独立于 P13–P15 的死锁链条，属可观测性问题；但在本 run 中放大了诊断难度。
- 与 CLAUDE.md §1.2「可诊断」（异常路径留下可观测信号，不误导）相关。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P17 记录：确定性 docgen 空动作未标 skip_reason，框架对预期空动作与 bug 空动作报同一 WARN，4 次误报在本 run 干扰了对死锁的定位。 |
| 2026-07-03 | **P17 已修复**：`DocgenStage.skip_reason` 无条件返回 `"deterministic_render"`（区别于 `DetailedDesignIntakeStage.skip_reason` 的条件式）——复用 `runner.py` 既有通用机制（`getattr(stage, "skip_reason", ...)`），未改 runner.py。WARN 降级为 `○ skipped (deterministic_render)` info 日志。TDD：`test_docgen_render.py::TestSkipReason` 2 用例先红后绿。详见 `16-docgen-deadlock-impl.md` 改动3。 |

---

## P18: validate reviewer 跨 loopback 轮次无增量，每轮从零全量重验

### 事实

- **观测**：上述运行 3 轮 validate loopback 中，每轮 reviewer 都从零开始——Glob 查找产物、Read 读取设计文档与 tiling 产物、逐条重验 GV1–GV9。`decision_log.json` 每轮都重新得出「GV1–GV5/GV7/GV9 PASS、GV8-B 已就地补 annotations、GV8-A 仍 blocking」的相同结论。`blocking_status.json` 自标「Retry #7 — same issue since attempt #1」。
- **跨轮事实**：loopback 重入 validate 时，框架未注入上一轮的 `decision_log` / 已确认 PASS 的规则集；reviewer 不知道上一轮已验证过什么，每轮全量重来。GV8-B 的 `[继承自概设独有设计]` 标注每轮都要用 Python 注入重新补回（因 docgen 每次重新生成会再次抹掉——这是 P13 渲染逻辑的连带表现）。
- **凭什么说是浪费**：单轮 validate 约 500–620s，3 轮累计约 1755s（占整 run 48%）。其中绝大部分是对「上轮已知 PASS 规则」的重复验证，对推进问题零贡献。reviewer 自报「Retry #7 same issue」却无任何机制让它停止或升级。
- **影响范围**：所有 validate（及同类 quality-gate reviewer）被 loopback 重入的情形。无增量机制 = loopback 次数越多，纯浪费占比越高。

### 关联

- 放大了 P15 的后果（无进展 loopback 每轮还附带高成本全量重验），共同吞噬预算导致 P16 超时。
- 与 CLAUDE.md §1.2「可诊断」、loopback_feedback 机制（`Stage.loopback_feedback`）相关：当前 feedback 只传 blocking_issues，不传历史决策上下文。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P18 记录：validate reviewer 跨 loopback 轮次无增量上下文，每轮从零全量重验 GV1–GV9，3 轮累计约 1755s 多为对已知 PASS 规则的重复验证。 |
| 2026-07-03 | **不修（主动删除方案）**：用户决策——兜底 A 后 P18 仅剩 `redo_tiling` 合法回路、`max_corrective=3` 有上限、触发频率未知；选项 A（注入 rule_results+产物指纹）需为每条 GV 规则维护「核对产物子集」映射，成本不抵收益，属过度设计。从方案删除、不实施；若未来 event_log 证实 `redo_tiling` 高频再立。详见 `15` §3.6。 |

---

## P19: general-design-review 单次 review 轮数/耗时偏高（轻）

### 事实

- **观测**：上述运行中 `general-design-review` 单次执行耗时 201.2s、48 turn。作为对比，同 run 内 `general-design-generator`（**生成**概设）仅 118.1s、28 turn——review 比 generate 慢约 70%、轮数多约 70%。
- **行为侧事实**：reviewer 做了大量 Bash 文件查找、逐文件 Read 读取上游产物，再就地 Edit 补了 3 个缺失字段（dtypeSize、循环框架伪码、Buffer 可行性清单），产出 `general_design_reviewed.json`（status=completed, blocking=[]）。流程本身合理（发现真问题并修补），但探测产物的开销偏高。
- **凭什么说是「轻」问题**：reviewer 的产出质量没问题（正确发现并修复了 3 个缺失点），仅效率偏低；且不构成阻断。与 P13–P18 的死锁/超时不同量级。
- **影响范围**：每次 design run 的 general-design-review 阶段。单次多耗约 80s，累积下影响 run 时长但不影响正确性。

### 关联

- 独立于死锁链条；归入「reviewer 探测效率」一类，与 P18（validate 无增量）同属 reviewer 行为侧，但严重度低得多。
- 与 CLAUDE.md §3.3（前台执行、实时观察）无直接冲突，仅影响观察时长。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P19 记录（轻）：general-design-review 单次 201s/48turn，慢于同 run 的概设生成（118s/28turn）；产出质量正常，仅探测产物开销偏高。 |
| 2026-07-03 | **已实施（升级：去 Bash+加 Write）**：根因是 reviewer 持 `Glob`/`Bash` 诱导全仓探测。实际改动比原方案更彻底——reviewer agent `allowed_tools` 去 `Bash`+`Glob`、加 `Write`（报告由 Write 写、不再靠 Bash `cat >`；探测工具连根去掉），validate/gd-review 两 skill 输出约定 Bash(cat)→Write，角色提示明示靶向 Read + Write 写报告。UT `test_capabilities::TestProjectAgentManifests::test_design_reviewer_no_probe_tools_write_for_reports` 守护工具集。详见 `15` §3.7、`16` 改动 4。 |

---

## P20: docgen 确定性渲染每次重新生成会抹掉 `[继承自概设独有设计]` 标注，须 loopback 外部 Python 注入补回

### 事实

- **观测**：P18 调研 `decision_log.json`/`blocking_status.json` 时发现，GV8-B（继承自概设的独有设计标注完整性）在每轮 validate loopback 之间都需要额外补一次——`design_doc` 中 `[继承自概设独有设计]` 标注在 docgen 每次重新生成终稿时被抹掉，须靠 loopback 外的 Python 注入逻辑重新补回，而非 docgen 渲染器自身保留。
- **凭什么说是独立于 P13 的另一处渲染缺陷**：P13 是「终稿『Kernel 架构』节缺 `kernel_pseudo_code` 内容」（缺装载），本条是「终稿中原本存在的标注在重新渲染后消失」（渲染幂等性缺陷）——二者都是 docgen 确定性渲染器的产物组装逻辑不完整，但触及的字段、修复点均不同，不能用同一次改动覆盖。
- **影响范围**：任何依赖标注在 docgen 重复渲染间保持稳定的下游校验（当前已知：validate 的 GV8-B）。只要 docgen 被 loopback（或以其它原因重跑）命中一次，标注即丢失一次，需要外部补丁介入。

### 关联

- 与 P13 同属 docgen 确定性渲染器的产物组装缺陷类，但字段/修复点不同，不在本轮 P13 修复范围内。
- 与 P18（validate 跨轮无增量）共同构成「validate 每轮重验」的成本来源之一：本条缺陷是 P18 高成本重验中被观测到的具体证据，但本身是 docgen 侧问题，不是 validate 侧问题。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P20 记录：docgen 重新生成终稿时会抹掉 `[继承自概设独有设计]` 标注，验证时依赖 Python 外部注入补回；独立于 P13（不同字段/不同修复点），本轮不修，仅记录。 |
| 2026-07-03 | **已实施（大修：design_doc 角色重定位）**：原 P20 小修（仅 GV8-B）升级为 §3.4 落地——根因是 GV8-A/GV8-B 把判定落点绑在 `design_doc`（无下游代码消费者的人类交付物）。改动：GV8-A 落点从终稿改 `buffer_kernel` 产物函数完整（`target=tiling`）；GV8-B 改核 `tiling_results.<tpl>.<segment>.inherited_design_points`、删终稿标注核对路径；GV5 降级（终稿格式归 docgen）；tiling 三段 schema 加可选 `inherited_design_points`、R7/R8/R4 回写；ValidateStage input_contract 改核对产物、design_doc 降 optional、`_upstream_inputs` 不物化终稿。UT `test_design_substages::TestValidateInputs` + `test_design_schemas::TestTilingInheritedDesignPoints` 守护；heavy_llm ST（design TUI 自闭环）用户确认后跑。详见 `15` §3.8、`16` 改动 5。 |

---

## P21: validate→tiling corrective loopback 丢失模板精确性（全量重跑）

### 事实

- **观测**：validate 的 GV8-A/GV8-B 校验失败、走 `redo_tiling` corrective loopback 时，tiling ForkJoin 的 rerun 决策是**全量重跑所有模板**，而非按 issue 的 `target_template` 精确重跑失败的那一个（或几个）模板分支。
- **凭什么说 selector 看不到 validate 的 issue**：`_tiling_rerun_selector`（tiling ForkJoin 的 `rerun_selector`）只读 `state.anchor_report.blocking_issues` 里 `target=="tiling"` 的 `target_template` 来圈定重跑分支；而 validate 的 GV8-A/GV8-B blocking_issues 写在 `design_doc.validation_report.blocking_issues`（由 `ValidateStage.transition` 折叠进 design_doc），**不在 anchor_report**。validate→tiling 跳转时 selector 读 anchor_report——此时 anchor-consistency 已 PASS（anchor_report 的 blocking_issues 为空或其 issue 已在前一轮处理），selector 返回 None → executor 清空整个 tiling subtree → 全量重跑。
- **影响范围**：多模板算子下，validate 报「模板 T2 的 buffer_kernel 缺 CopyOut 函数（`target_template=T2`）」时，T2 这个定位信息在 rerun 环节被丢弃，所有模板的 split/buffer_kernel/precision-perf 三段全部重跑。单模板算子无差异（本来就只有一个分支）。浪费量随模板数线性放大。
- **对比（同一 selector 的不对称）**：anchor→tiling 这一路是**模板精确**的——anchor-consistency 的 issue 也在 `anchor_report`，selector 能读到 `target_template`，故只 rerun 失败模板。即同一个 `_tiling_rerun_selector` 对 anchor→tiling 精确、对 validate→tiling 不精确，根因是两路 gate 的 issue 载体不同（`anchor_report` vs `design_doc.validation_report`），selector 只认前者。
- **非本轮 P18/P19/P20 引入**：R8（template-precise rerun）当时针对 anchor→tiling 落地；validate→tiling 这一路的模板精确性当时未覆盖。本轮 P20 大修把 GV8-A/GV8-B 的 target 归到 tiling 后，validate→tiling 这条 corrective 边变得更常用（GV8-A/B 失败都走它），该限制的暴露面变大。

### 关联

- 承接本轮 P20 大修后的 loopback 闭环审查发现（用户要求记录、后续解决）。
- 与 `_tiling_rerun_selector` / `_anchor_rerun_selector`（两者实现相同、都只读 `anchor_report`）相关。
- 与 CLAUDE.md §1.2「可扩展：同类新情况自动正确归位」相关——anchor→tiling 精确、validate→tiling 不精确，是 selector 没有统一消费「所有 gate 的 tiling-target issue」导致的不对称。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P21 记录：validate→tiling corrective loopback 丢失模板精确性——`_tiling_rerun_selector` 只读 `anchor_report`、不读 `design_doc.validation_report`，导致 validate 的 GV8-A/B issue 的 `target_template` 在 rerun 环节被丢弃、全量重跑 tiling；anchor→tiling 同 selector 则精确（issue 载体一致）。多模板算子浪费随模板数放大。后续解决。 |

---

## ✅ P23: resume 不支持覆盖 workflow/stage timeout 配置（已修复）

### 事实

- **观测**：`ascendc-devkit run --resume <run_id>` 时，CLI 重传的 `--workflow-timeout` / `--stage-timeout` **不生效**——resume 沿用旧 state 的 timeout 值。
- **根因**：dispatcher resume 段 `state.with_updates(...)` 更新了 `non_interactive / user_max_iterations / max_corrective / max_escalations / on_decision / enable_stubbed`，**唯独没有 `workflow_timeout_sec` / `stage_timeout_sec`**（这两个只在 fresh 段从 task_request 写进 state）。runner 算 deadline 时读 `state.workflow_timeout_sec` / `state.stage_timeout_sec`，故 resume 用旧值。
- **影响**：第一次因 stage_timeout=600 超时后，resume 传 `--stage-timeout 1200` 想放宽，resume 后那个 stage 仍按 600 计 → 再次超时。无法通过 resume 调整预算。
- **凭什么说是遗漏而非有意**：无注释表明「timeout 故意不随 resume 变」；`max_iterations` / `max_corrective` 等都更新了，独缺 timeout。属同类配置（CLI 可调的 run 预算）却没接同一通路。

### 修复

- dispatcher resume 段补两行：`workflow_timeout_sec`（task_request 值 `or` state，因 CLI 默认 0=disabled，0 视为「未传」沿用旧）；`stage_timeout_sec`（`is not None`，因 CLI 默认 None，显式 0=disabled 也能覆盖）。与 `max_iterations` 同模式。
- TDD：UT `test_resume_overrides_timeout_from_task_request` 先红（`assert 3600 == 7200`）后绿；application 全量 112 passed 回归。
- resume **重新计时**特性不变（runner monotonic 重设 deadline，resume 拿新预算）；本条只补「budget 值可由 CLI 覆盖」。

### 关联

- 来自续跑 e2e 的需求讨论（用户：第一次 stage 600 超时、resume 想设 1200）。
- 与 P21（validate→tiling 模板精确 rerun）同为 self-evolve run 机制改进，但独立。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | P23 记录 + 已修复：dispatcher resume 段补 `workflow_timeout_sec`/`stage_timeout_sec` 覆盖（UT `test_resume_overrides_timeout_from_task_request` 守护，application 112 passed）。 |

---

## P24: 硬件参数无唯一数据来源，多 skill 内置真值表互相漂移（UB 出现 192/240/248/256KB 四值）

### 事实

- **观测**：e2e run `20260704_040953` 中 `anchor-consistency` 误报 AC2 阻断——per-template anchor 报「产物 UB=192KB 与锁定真值表 240KB 冲突」。产物 192KB 取自 `platform_diff.md`（「A3 UB ~192KB」）与 chip spec（910B UB=196608B=192KB），实际 910B 硬件亦为 192KB；anchor 内置 P6-a 真值表标 245760B(240KB) 是离群错误值。
- **凭什么说无唯一来源**：同一硬件参数 UB 在仓内至少四处取值且互相矛盾——
  - `ascendc-op-design-anchor-per-template` SKILL 的 P6-a 锁定真值表：UB 总大小 = 245760B(240KB)，并自述「已在本 skill 给出，不需查文档」「禁止以上游 self_check 为依据，硬件能力必须自己对照内置真值表判定」。
  - `ascendc-op-general-design` 的 `general_design_common_knowledge.md`：同一文件一处写「256KB 物理 / ~192KB 可用」，另一处写「248KB」。
  - `ascendc-op-design-shared` 的 `platform_diff.md`：「A3 UB ~192KB / A5 ~248KB」（定性、约数，非机器可读常量）。
  - `ascend-hardware` 的 chip spec JSON（`ascend_910b.json` / `sd3403.json`）：`ub size_bytes = 196608`(192KB)——机器可读，且是 `ascend-hardware` skill 产出 `hw_params` 的来源。
  - 此外 `ascendc-profiling-analysis` 的 `check_feasibility.py` 把 `ub_size_bytes: 196608` 写死为 default；多个 pattern md 散写「~192KB」。
- **凭什么说 P6-a 是漂移而非权威**：P6-a 刻意把真值表内置、禁止查证，定位为「独立 ground truth」。但内置副本必然与源头漂移（本次 240 vs 192 即漂移产物）。**独立性的正当来源应是「直接读权威源 chip spec」，而非「维护一份手抄副本」**——后者只是把单源问题换成了多源问题。
- **影响范围**：任一 skill 内置硬件常量都会与 chip spec / platform_diff 漂移；漂移即触发 anchor 误报阻断 → 触发 P25（日志看不出在空转）+ P26（gate 空转/路由失效）。只把 P6-a 的 240→192 是治标，下次仍会漂移。
- **与框架原则冲突**：违反 CLAUDE.md §1.5（算子/硬件知识不进 Python/skill 代码，全在 resources）与单源精神；硬件参数应如 `ascend-hardware` 产出的 `hw_params` 那样单一来源、运行期注入，而非各 skill 各抄一份。

### 关联

- 是 P26 中 AC2 假阳性的直接根因（P24 不修，P26 的 gate 永远会被这条假 issue 触发）。
- 与 `ascend-hardware` skill（产 `hw_params`，框架已认定的硬件权威）相关——本条要求把 chip spec 确立为唯一来源、各 skill 改为引用而非复制。
- 与 CLAUDE.md §1.5、§1.7 相关。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-04 | P24 记录：硬件参数（UB 等）无唯一来源，仓内至少四值（192/240/248/256KB）；`ascendc-op-design-anchor-per-template` 的 P6-a 内置真值表(240KB) 与 chip spec/platform_diff.md(192KB) 漂移，是 run `20260704_040953` AC2 假阳性的根因。待解决。 |

---

## P25: stage 迭代/loopback 失败原因在日志中不可读（只打固定串，不携带 issue detail）

### 事实

- **观测**：run `20260704_040953` 日志中 `anchor-consistency` 的迭代行仅显示 `iteration 2/3 (quality check not satisfied)` / `3/3 (quality check not satisfied)`，不显示 `is_satisfied` 为何为 False、不显示 `blocking_issues` 的 code/target/detail（即 AC2 = UB 192 vs 240 冲突）。
- **凭什么说日志不可读**：runner 构造迭代 reason 时，quality 失败分支只赋一个固定串「quality check not satisfied」；issue 的 code/target/detail 从不写进该日志行。真实 AC2 detail 只存在于 `decision_log.json` 产物，光看日志无法判断「真在修还是空转」。
- **凭什么说「带个 code 也没意义」**：即便迭代行带上 `AC2(tiling)` 这样的简短 code，人不知道 AC2 指什么、下游 LLM 收到 loopback 也得回头查证、浪费 token。失败原因必须携带足够 detail（人 + LLM 可直读、无需二次查证）才有诊断与修正价值。
- **与现有 loopback 摘要的不对称**：graph_executor 已有确定性的 issue 摘要渲染（field-select + truncate，非 LLM 压缩），但**只在 routing transition 时触发**，不在 stage 内迭代行触发；两套日志面不一致，迭代行恰好是最需要诊断信息的地方却最贫乏。
- **影响**：诊断盲区——本次 anchor 空转、历史 validate 空转（P15/P18）这类「反复重试」问题，日志层面看不出每轮在解什么、是否在推进，只能事后翻产物。

### 关联

- 与 P26 互为表里：P26 是「控制流把 gate 拖入空转」，P25 是「空转过程在日志上不可观测」。修 P26 减少空转、修 P25 让剩余的每一次迭代/路由都可读。
- 与 step-12（pipeline 可观测性）同主题。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-04 | P25 记录：stage 迭代/loopback 失败原因日志不可读——runner 只打固定串「quality check not satisfied」，不携带 blocking_issues 的 code/target/detail；现有 issue 摘要渲染只在 routing 触发、不在迭代行触发。待解决。 |

---

## P26: read-only gate 靠 is_satisfied 自迭代无法改产物只能空转；corrective 路由被「自迭代 + 末轮 override」双重绕过

### 事实

- **观测**：run `20260704_040953` 中 `anchor-consistency` 自迭代 3 轮（ceiling = `default_max_iterations = 3`）：前 2 轮按 skill 默认「原样合并」传播 AC2 → `is_satisfied=False` → 同 stage 重跑（fresh agent、同输入、同结论、零产物进展）；第 3 轮 agent 推翻默认聚合、清空 `blocking_issues` → `is_satisfied=True` → 通过。整个 stage 耗时 1140.6s，其中前 2 轮为纯空转。
- **凭什么说「自迭代」是错的控制结构**：
  - anchor 按角色契约「只读产物 + 写锚点报告」，无权改 tiling 产物；AC2 的修法（改产物 UB 措辞）不归 anchor。anchor 能改自己的报告，但改不了被对质的产物。
  - runner 的 quality 自迭代循环在 stage **节点内**重跑同一 stage（最多 3 轮）；graph_executor 的 corrective 路由只在 stage **节点完成后**、按 transition_table 解析条件才触发。故自迭代期间不会路由——gate 在自己内部反复算同一个结论。
- **凭什么说 corrective 通路本来可用却被绕过**：
  - `anchor-consistency → tiling` 的 corrective 边**存在且模板精确**：design_tree 的 transition_table 把 `infeasible → ("tiling", "corrective")`，selector 按 `target_template` 只 rerun 失败分支（与 P21 同一 selector、同一精确机制）。
  - **双重绕过**：(1) 自迭代空耗前 2 轮；(2) 第 3 轮 agent 清空 `blocking_issues` 使 gate「自洽通过」→ 节点以 `is_satisfied=True` 完成 → 条件解析为「无 loopback」→ **不路由**。即 agent 的末轮 override 把本该 forward 给 tiling 的 issue 静默掉了。
- **凭什么说这是结构性而非个案**：若第 3 轮 agent 不推翻、保留 AC2，则节点以 `is_satisfied=False` 完成 → 解析为 infeasible → forward-route 到 tiling。但 AC2 因 P24 是假阳性，路由到 tiling 也修不好（tiling 的 R0 强制 192KB，AC2 要 240KB，循环矛盾）。**真·产物级 issue** 落到该 gate 同样会先空转 2 轮、再被末轮 override 盖掉——空转 + 静默两路都偏离「正向修正」。
- **影响**：read-only gate 的 quality 自迭代 = 确定性空转（结构上不可能在 gate 内修复指向他处的 issue），叠加末轮 override 静默，使 corrective 路由触发不到。本次浪费 ~10min 并最终撞 workflow 超时回滚、零产出。

### 关联

- 与 P21 互补：P21 是「validate→tiling loopback 丢模板精度」（边存在但粗）；P26 是「anchor gate 本应 forward-route 却被自迭代/override 绕过」（边存在但触发不到）。两者合起来才是「corrective loopback 真正可用」的两半。
- 与 P25 互为表里（空转的可见性）。
- 假阳性的源头是 P24（不修 P24，gate 永远被假 issue 触发）；即便修了 P24，P26 的控制结构缺陷对真 issue 依然存在。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-04 | P26 记录：read-only gate（anchor-consistency）靠 `is_satisfied` 自迭代空转（前 2 轮零进展），末轮 override 清空 blocking_issues 又静默掉本该 forward 到 tiling 的 corrective 路由（边存在且模板精确，但触发不到）。run `20260704_040953` 中耗 1140.6s、撞超时回滚。待解决。 |

---

## P27: 无统一「运行环境上下文」对象——run 不变的环境事实散落各处，逐 stage 传递声明即「传递丢失」载体

### 事实

- **观测**：单次 run 全程不变的「环境事实」散落在三处、无单一内聚对象承载：
  - **设计目标硬件**：`chip_version` 是 `State` 字段（CLI `--chip-version` → task_request → entry/context 解析）；`hw_params`（UB/L1/带宽/reg/对齐）**根本不在 State**，被各 skill 内置副本「自给自足」（即 P24 的多源漂移根源）。
  - **当前硬件环境**：`npu_id` 是 State 字段；真实检测到的芯片型号在 `adapters/npu/detect.py`（查 torch_npu device_name → 映射 chip），结果不回存 State；驱动版本经 `npu-smi` 在 `verify_env.py`（CLI 诊断命令，非管线内）。
  - **运行软件环境**：`ASCEND_TOOLKIT_HOME` / CANN compiler / 版本经 `os.environ.get` 散读于 `adapters/toolchain/cann.py`（CannAdapter）、`verify_env.py`、`verify.preflight_diagnostic`；`ASCEND_OPP_PATH`/`ASCEND_HOME_PATH` 散读于 `cannbench_eval`/`deploy`/`npu/runner`；python/torch_npu 版本仅在 `verify_env.py`。
- **凭什么说「逐 stage 传递声明 = 传递丢失载体」**：design substage 的 `_upstream_inputs` 是**逐 stage 显式声明**要消费哪些上游字段、再由 `_materialize_inputs` 物化成文件。一个 stage 若忘了声明某字段，该字段就**静默地不进它的 cwd**——没有任何加载期校验拦截。本次 P24 多源漂移正是这个机制的反面：因为没有全局可达的硬件源，每个 skill 只能自抄一份。若把 `hw_params` 仅作为又一个 State 字段、靠各 stage 逐个声明，则新增 stage 忘声明时 hw_params 同样静默丢失——**传递丢失是确定性发生、且不可观测的**。
- **凭什么说现有检测已半集中、缺收口**：`CannAdapter` 已集中 CANN toolchain 检测（toolkit 路径/compiler/set_env.sh），`npu/detect.py` 已集中芯片检测——但它们的产出未被收进一个统一上下文对象，而是各自被调用方直接 `os.environ`/导入消费。RunContext 不是再造检测，是**收口既有检测产出**。
- **影响范围**：环境事实不可统一查证（要查「这次 run 目标硬件/运行环境是什么」得拼多个字段 + env + skill 副本）；新 stage 接入环境信息靠手声明、易漏；P24 的「单源」若只停在「加个 hw_params 字段」仍受传递丢失威胁。是 P24/P25/P26 修复所依托的结构性地基。

### 关联

- 是 P24（硬件单源）的结构承载——hw_params 应住在 `run_context.hardware_target`，一次载入、全局可达、自动物化，而非逐 stage 声明。
- 与 CLAUDE.md §1.6（依赖注入：业务层持 protocol/ABC，实现经 adapter 注入）、§1.7（仓自闭环）、单源精神一致。
- 与既有 `CannAdapter`/`npu/detect.py`/`verify_env.py`/`verify.preflight_diagnostic` 复用关系：RunContext 收口它们的产出，不重做检测。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-04 | P27 记录：无统一运行环境上下文——run 不变的环境事实（设计目标硬件 / 当前硬件环境 / 运行软件环境）散落 State 字段 + ad-hoc `os.environ` 读 + skill 内置副本；逐 stage `_upstream_inputs` 声明即「传递丢失」载体（忘声明则静默丢失、无加载期校验）。是 P24 单源修复的结构地基。待解决（用户拍板三段一次性全做）。 |

---

## P28: heavy_llm 标记不一致 + §3.11「不引入 heavy_llm 标记」与仓内实际机制矛盾

### 事实

- **观测**：`tests/st/test_design_tui_selfclosure.py` 只标 `@pytest.mark.llm`（llm=3, heavy_llm=0），未标 `@pytest.mark.heavy_llm`。其 `TestDesignChainRelay`（template-division→integrate 链 relay，分钟级）属 heavy_llm 原型却漏标 → **默认 `pytest` 会自动跑它**，违反 §3.11「heavy_llm 不默认随 pytest 自动跑」。
- **凭什么说是不一致而非有意**：同胞 `test_testdesign_tui_selfclosure.py` 的 chain-relay 类**标了** `@heavy_llm`（line 159）；`test_smoke.py` 也标了（line 61）；`pyproject.toml` 注册了 `heavy_llm` marker（"long-running LLM chain-relay tests (~5min+); skip with 'not heavy_llm'"），conftest 支持按它选。design 这条漏标是孤例，不是约定。
- **凭什么说 §3.11 与机制矛盾**：CLAUDE.md §3.11 明文「**不新增 pytest 标记**（标记语义见 §3.5，`@heavy_llm` 属成本分类、非运行时依赖，不引入）」。但仓内**已有且在用** `@pytest.mark.heavy_llm`（pyproject 注册 + 2 处使用）。即「靠人工判断 gate、不加 mark」的方针实操站不住——无机械标记则无机械 gate，heavy 用例必漏进默认 pytest（`test_design_tui_selfclosure` 即活例），实际回到用 mark gate，但 §3.11 未同步。
- **影响范围**：凡 heavy 而未标的用例都在默认 pytest 自动跑、绕过 §3.11 gate。已知至少 design chain-relay；`test_skill_invocation.py`(llm=3,heavy=0)、`test_decision_transcript.py`(llm=2,heavy=0) 待审计是否同样该标未标。`test_design_tui_selfclosure` 的单 skill file-IO 类属真轻量（测试自述「不需要做深度设计推理」、秒级），应保持 `@llm` 不标 heavy。

### 关联

- 与 CLAUDE.md §3.11（heavy_llm 执行决策）、§3.5（标记语义=运行时依赖）、§1.3（加载期校验优于运行期暴露——机械 gate 优于人工纪律）相关。
- 与本工作线 step-15 的 Step 6（heavy_llm e2e 待用户确认）直接相关：标记不准 → gate 不准。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-04 | P28 记录：`test_design_tui_selfclosure` 漏标 `@heavy_llm`（chain-relay 类是 heavy 原型），默认 pytest 自动跑、绕过 §3.11 gate；且 §3.11「不引入 heavy_llm 标记」与仓内已注册+使用该 marker 的实际机制矛盾。用户指示：先记录，等当前修改（step-15 P24-P27）完成后再修（补标+审计+ reconcile §3.11）。 |

---

## P29: 强杀（SIGKILL/未捕获信号）后 `--resume` 无法从断点续跑——从头重跑

### 事实

- **观测（resume 的断点判定只信 snapshot，不读权威 events）**：`--resume <run_id>` 跳过已完成节点的能力完全依赖 `state_snapshot.json` 里的 `node_status` 字段——`_resume_node_status` 直接 `return dict(state.node_status)`，仅读 snapshot，不从 `events.jsonl` 重建。其 docstring 自陈「no node_status → reruns from the top」。
- **观测（snapshot 落盘节奏不含运行中）**：全工程写 `state_snapshot.json` 的点只在 dispatcher，一次普通非交互 run 实际触发的只有三处——运行**开始前**写初始值、**整个 workflow 跑完**后写终态、**优雅 SIGINT**（`RunnerCancelledError` 分支写 `executor.latest_state`）。运行中（逐节点/逐 stage）**无任何落盘**：GraphExecutor 在内存里随节点完成逐个更新 `node_status`，但这些进度只在上述三时机一次性 flush；runner/graph_executor 运行中只写 `pending_decision.json`，不写 state snapshot。
- **观测（强杀到不了任何落盘点）**：强杀（SIGKILL；或未注册 handler 的 SIGTERM/SIGHUP，如 OOM-kill、`kill -9`、终端强关）三个落盘点都到不了 → 内存 `node_status` 丢失 → 磁盘 snapshot 永久停在运行启动时的初始态：`node_status: {}`，且 `requirement`/`general_design` 等明明已产出的数据字段也都是 null（snapshot 是启动那一刻的快照）。
- **实测实例**：run `20260704-053333-c2911b`（exp 算子、`self_evolve_op`、cann-bench 对齐 e2e）跑到第 7 个 stage `template-division`（agent 第 10 turn）时被强杀；前序 6 个 stage（entry/context/requirement/general-design-generator/general-design-review/dd-intake）已完成——`events.jsonl` 里 6 个 `stage_complete` 齐全、产物文件都在盘上。但磁盘 `state_snapshot.json` 仍是启动初始态（mtime = 运行启动时刻）。用 dispatcher 自身的 `_load_state_from_run` + `_resume_node_status` + `_first_pending_leaf` 判定：`node_status` 读出为 `{}`，第一个 pending leaf = `entry` → `--resume 20260704-053333-c2911b` 会从 `entry` 从头重跑，把已完成的 6 个 stage 全部重做，而非从 `template-division` 续跑。
- **凭什么说是缺陷而非 by-design**：
  - CLAUDE.md §1 明文「Event Sourcing — events.jsonl 是运行历史的权威记录」。强杀场景下 `events.jsonl` 是完整的（逐事件 append），但 resume 完全不读它——**权威记录被冷落**。
  - 系统宣称支持 resume（CLI 有 `--resume`/`--resume-iteration`，dispatcher 有完整 resume 段），而强杀是长 run 最常见的中断方式之一（OOM、kill -9、ssh 断链、机器重启）。若 resume 只覆盖「优雅 SIGINT / 决策挂起 / 正常跑完」三种能落盘的退出，则「支持 resume」名实不符。
  - 曾有从历史记录重建 `node_status` 的 bridge，被当 migration debt 删（理由是 `stage_iterations` 摘要有损、合成的单层 phantom key 与 group 内部节点路径对不上、top-level `integrate` 与 detailed-design 子 stage `integrate` 撞名误跳）。但被删的是「**从有损摘要合成**」，不是「**从权威 events.jsonl 的 `stage_complete` 事件重建**」——后者是正当路径，却随前者一起被放弃。
- **影响范围**：任何被强杀的 run 都无法断点续跑，只能从头重跑——浪费已完成 stage 的 LLM 时间/成本，且 LLM 非确定性使重跑结果可能漂移。对长 run（`self_evolve_op` 端到端 20-40min，heavy 流水线更长）尤甚：跑到 80% 被杀 = 全部重来。与 P23（resume 不支持覆盖 timeout，已修）同处 dispatcher resume 段，是 resume 鲁棒性的又一缺口。

### 关联

- 与 CLAUDE.md §1（Event Sourcing，events.jsonl 权威）、§1.2（根因修复、可诊断、不掩盖）、§1.3（持久化/加载期校验优于运行期暴露）直接相关。
- 同 self-evolve run 机制工作线：step-15 的 P23（resume 覆盖 timeout，已修）与本问题同处 dispatcher resume 段；P25（迭代/loopback 可观测性）同属 run 可恢复性主题。
- 触发本问题的 run `20260704-053333-c2911b` 由 `scripts/e2e_self_evolve.sh` 拉起；该脚本本身不带 `--resume`（每次新建输出目录），是独立的另一个缺口，不与本问题混记。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-04 | P29 记录：强杀后 `--resume` 从头重跑——resume 断点判定仅信 `state_snapshot.json` 的 `node_status`、不读权威 `events.jsonl`；而 snapshot 只在运行开始/跑完/优雅 SIGINT 三时机落盘，强杀到不了任一落盘点 → 内存 `node_status` 丢失、磁盘 snapshot 停在初始空态。run `20260704-053333-c2911b` 实测印证（6 stage 已完成 + events 完整，仍从 entry 重跑）。用户指示：先记录，后续 step-16 支持强杀续跑。 |
| 2026-07-04 | P29 落地（step-16，前向修复）：L3 决策——逐节点原子 flush state snapshot（snapshot 继续作唯一权威，不重引入 events-rebuild，见 `19-resume-hardkill-analysis.md`）；L4 实施（`20-resume-hardkill-impl.md`）：GraphExecutor `_execute_node` 末尾 best-effort flush + 同步 `latest_state` 为完成态（让 Ctrl+C/cancel/timeout 等 handler 也 snapshot 正确前沿）+ `_write_state_snapshot` 改 temp+`os.replace` 原子写 + 主构造接回调（branch_exec 传 None 避免线程竞争）。**强杀（SIGKILL）与 Ctrl+C（SIGINT）现在都能断点续跑。** UT 1523（含 dispatch 层 Ctrl+C/cancel/timeout 中断→resume parametrized 用例）+ 相关 ST 34（resume/snapshot/eventlog）全绿，中断→resume 矩阵确定性覆盖完整。**未跑**真实 OS 信号 e2e（NPU 被占 + §3.11），列为 PR 前节点。旧 run `20260704-053333-c2911b` 不在救援范围（重跑）。 |

## P30: resume 不读 state.workflow_name——`--resume` 用 CLI 默认 `generate_ascendc` 加载错图、从头重跑 + 污染 snapshot

### 事实

- **观测（resume 的 workflow 选择没纳入"state 是唯一权威"不变式）**：`dispatcher.py` 的 `workflow_name = task_request.get("workflow", "generate_ascendc")` 取自 CLI（默认 `generate_ascendc`），位于 resume 分支之前；resume 分支内 `workflow = get_workflow(workflow_name)` 直接用了这个 CLI 默认值，**没有取恢复出的 `state.workflow_name`**。而 `_load_state_from_run` 经 `State.from_snapshot` 恢复出的 state 明明带着正确的 `workflow_name`（snapshot 里有该字段），却被忽略。同段代码注释自陈「node_status, the sole resume authority」——`node_status` 视 state 为权威，`workflow_name` 却漏了。
- **观测（节点名前缀错配 → 全判未完成 → 从头重跑）**：加载错误 workflow 图后，图节点名前缀（`generate_ascendc/*`）与 `state.node_status` 里真实的（`self_evolve_op/*`）完全错配，`_resume_node_status` / `_first_pending_leaf` 找不到任何匹配的 completed 节点 → 所有节点判未完成 → 从 `entry` 重头跑。
- **观测（次生：无上游产物 → partial / abort 链）**：重头跑时上游 design 产物不在当前 workflow 的预期路径，`entry`/`context` output_contract 不满足（partial），`requirement` 撞 `resolve_ambiguity` → on_decision=default 下抛 `DecisionPendingError`，但异常处理路径把 dict 当成有 `.question` 属性访问 → 次生 `'dict' object has no attribute 'question'`（这是跑错 workflow 的后果，非独立 bug）。
- **观测（错误 resume 还污染 snapshot）**：那次错误 resume 中途写 `state_snapshot.json`，把 `workflow_name` 持久化成 `generate_ascendc`、写入 `generate_ascendc/{entry,context,requirement}` 三个脏节点——**污染原 run**：即使代码修好，该 run 直接 `--resume` 仍会读到被改坏的 `workflow_name=generate_ascendc` 再次撞墙，必须先手动救回 snapshot。
- **实测实例**：run `20260705-072625-72f58b`（exp 算子、`self_evolve_op`、cann-bench 对齐 e2e）跑到 `validate` 撞 workflow timeout（3600s 预算、ran 3719.5s）被 abort、repo_rollback。对其执行 `ascendc-devkit run --resume 20260705-072625-72f58b`（不带 `--workflow`）：日志首行 `Resuming ... (completed nodes: ['self_evolve_op/context', ...])`，但紧接着执行 `generate_ascendc/entry/entry`、`generate_ascendc/context/context`、`generate_ascendc/requirement/requirement`——节点名前缀错配实证，`requirement` abort 于 `'dict' object has no attribute 'question'`。中断后查 snapshot：`workflow_name` 已被改成 `generate_ascendc`、node_status 含三个 `generate_ascendc/*` 脏节点（已备份 `state_snapshot.json.bak.polluted`）。
- **凭什么说是缺陷而非 by-design**：
  - CLAUDE.md §1.2「方案合理性」：resume 的职责是从 state 完整恢复执行上下文，workflow 选择属于执行上下文；同段注释已确立"state 是 resume 唯一权威"，`workflow_name` 不该是例外。
  - CLAUDE.md §1.3「加载期校验优于运行期暴露」：CLI `--workflow` 与 state `workflow_name` 不一致时应在加载期报错，而非静默用错图跑下去。
  - 「支持 resume」名实不符：resume 对非默认 workflow 的 run（如 `self_evolve_op`）完全失效，且静默（日志看不出用错了 workflow，只看到节点重跑）。
- **现有测试盲区（bug 漏网原因）**：`tests/ut/application/test_application.py::TestDispatcherResume` 构造的 state `workflow_name` 全是默认 `generate_ascendc`、dispatch 调用全不传 `workflow` 键 → 两者恰好一致，从未覆盖"state workflow 与 CLI 默认不一致"的场景。
- **影响范围**：任何用非 `generate_ascendc` workflow（当前即 `self_evolve_op`）跑的 run，resume 都会从头重跑 + 污染 snapshot。与 P29（强杀续跑，已修）症状相似（resume 从头跑）但根因不同——P29 是 snapshot 落盘节奏，本问题是 `workflow_name` 没从 state 恢复 + 加载期无冲突校验。

### 关联

- 与 CLAUDE.md §1.2（方案合理性/根因修复）、§1.3（加载期校验）、§1.1（state 是 resume 权威，同 P29）直接相关。
- 同 resume 正确性工作线：step-15 P23（resume 覆盖 timeout，已修）、step-16 P29（强杀续跑，已修）同处 dispatcher resume 段；本问题是该段的又一缺口。
- 触发实例 run `20260705-072625-72f58b` 由 `scripts/e2e_self_evolve.sh` 拉起；该脚本不带 `--resume`、日志按启动时间戳单文件覆盖写，是"resume 续日志"的独立缺口，不与本问题混记。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-05 | P30 记录 + 主修复落地：dispatcher resume 分支改用 `state.workflow_name` 为权威 + CLI 显式冲突 `--workflow` 加载期 `EX_USAGE`（§1.3）；TDD 新增 `test_resume_uses_workflow_name_from_state` / `test_resume_conflicting_workflow_returns_usage`（红→绿）；受污染 run `20260705-072625-72f58b` 的 snapshot 已救援（`workflow_name` 改回 `self_evolve_op` + 删 3 脏节点，备份 `.bak.polluted`）；回归 UT（TestDispatcherResume + dispatcher_resume_bridge + graph_resume 10 passed；state_machine_dispatcher + graph_executor 55 passed）全绿。**待讨论**：加载期 snapshot 污染校验（`_load_state_from_run` 用 events.jsonl 反推真实 workflow 与 `state.workflow_name` 比对、不一致告警）是否要做——防"历史被污染的 snapshot 救不回"。 |
| 2026-07-05 | **P30 主修复的 CLI 层缺口补全**：主修复加的"CLI 显式冲突 → EX_USAGE"检查有个前置缺陷——CLI `--workflow` 的 `default="generate_ascendc"` 让用户**不传**该参数时 click 也把 `generate_ascendc` 注入 task_request，于是 resume（脚本只传 `--resume`、不传 `--workflow`）仍被判"显式传了 generate_ascendc、与 state 的 self_evolve_op 冲突"→ `EX_USAGE`，resume 依旧不可用（用户实测撞此）。根因：dispatcher 该检查依赖"`task_request['workflow']` 为 None 才算未传"，但 click default 抹掉了"未传"与"显式传"的区分。修复：`--workflow` `default=None`（None 真正代表未提供）+ dispatcher 的 new-run 默认值改用 `or "generate_ascendc"` 兜底。同时修 `scripts/e2e_self_evolve.sh` resume 分支 `PIPESTATUS` 被 `echo` 冲掉的 bug（退出码恒显示 0、CI 误判成功）。回归测试盲区：P30 的两个 dispatcher 层测试均直接构造 task_request dict（不经 click），测不到 CLI default 回归，故新增 CLI 层 `test_run_without_workflow_defaults_to_none`（断言不传时 `task_request['workflow'] is None`）。真实链路 ST（归档 `tests/fixtures/resume_all_done_state.json` 合成快照 + `tests/st/test_resume_cli.py`，秒级、不跑 LLM/NPU——all_done 路径在 backend 初始化前 return）：用真实 click（CliRunner 不 mock）→ 真实 dispatch 焊上「CLI default → dispatcher workflow 检查」这条既有测试都没覆盖的缝；两用例：不传 `--workflow` → exit 0、显式传冲突值 → EX_USAGE。反向验证：临时把 default 改回 `generate_ascendc`，首用例即失败并报出与用户实测一致的「workflow 不一致」错误，证非假绿。 |

## P31: resume 运行控制参数（non_interactive / on_decision / enable_stubbed）继承断裂——CLI flag 默认值架空 dispatcher fallback

### 事实

- **观测（P30 同源病的推广）**：`--non-interactive`（`is_flag=True`，click 默认 `False`）、`--on-decision`（`default="default"`）、`--enable-stubbed`（`default=False`）三个 CLI 参数，用户**不传**时 click 仍把默认值注入 task_request。dispatcher resume 分支用 `task_request.get(key, state.xxx)` 想做「未传=继承 state」fallback，但 `.get` 只在 key 不存在时取 default——这三个 key 永远存在（带默认值），fallback 永远不触发 → 首次 run 存进 state 的值被 CLI 默认值覆盖。
- **实测**：run `20260705-072625-72f58b` 首次以 `--non-interactive` 跑（state.non_interactive=True）；resume 不带该参 → dispatcher 把 True 覆盖成 False → 非交互 run 变交互 run（在 validate 弹 human-review 菜单）。snapshot 被污染写回 non_interactive=False（同 P30 污染模式，该 run 目录另有 `.bak.polluted` 备份）。`--on-decision`/`--enable-stubbed` 同病，只是首次也用默认值故碰巧未暴露。
- **对比（为什么 timeout 能继承而这三不能）**：`workflow_timeout_sec`/`stage_timeout_sec`/`max_corrective`/`max_escalations` 在 dispatcher resume 用 `is not None`/`or` 显式区分「未传」与「显式传值」，故继承生效；这三个用 `.get(key, default)` 且 key 永远带值，故失效。同段代码两种写法、行为不一致。
- **凭什么是缺陷**：与 P30 同论证（§1.2 resume 应完整恢复执行上下文；运行控制类参数属于执行上下文）。P30 已为 `--workflow` 立「CLI `default=None` + dispatcher 区分未传/显式」修复范式，但未推广到这三个参数——同根因的半截子修复（§1.4）。

### 关联

- 与 P30 同根因（click default 抹掉「未传」与「显式传」区分）；P30 是特例（`--workflow`），本问题推广到 `--non-interactive`/`--on-decision`/`--enable-stubbed`。
- 同 dispatcher resume 段：P23（timeout 覆盖）、P29（强杀续跑）、P30（workflow 继承）。
- 与 CLAUDE.md §1.2（根因修复）、§1.4（不留半截子修复/过渡层）直接相关。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-05 | P31 记录 + 修复落地（P30 范式推广）：CLI 三参数 `default=None`（`--non-interactive` 改 `--non-interactive/--interactive` 配对 flag，三态可分：未传=None / True / False）；dispatcher new-run 分支用 `or` 兜底（None→实际默认 False/"default"）、resume 分支用 `is not None`（None=沿用 state、非 None=显式覆盖；布尔不能用 `or`——False 是合法显式值）。TDD：先红 `test_resume_inherits_run_control_when_cli_unset`（None 被直写 state 而非 fallback 到 True）+ `test_resume_overrides_run_control_when_explicit` + CLI `test_run_default_values`（三键 None）/ `test_run_interactive_flag_sets_false`（`--interactive`→False），改码后转绿。回归：全量 UT 1550 绿 + `tests/st/test_resume_cli.py`（真实 click→dispatch 链路）2 绿。**未覆盖（独立缺口，本次不动）**：A 类输入产物参数（requirement / golden / cases / chip_version 等）resume 时仍被**静默忽略**（dispatcher resume 分支不读这些 task_request key，下游 stage 读 State 快照字段）——传新值不生效、也不报错；是否做加载期显式拒绝（像 `--workflow` 冲突那样报 EX_USAGE），待讨论。 |

## P32: test-analyze 依赖 kernel_architecture，但 step-9 后该产物挪到 codegen_init（test_design 之后）→ test_design 永远 fail-fast（exit 65）

### 事实

- **观测（step-9 重构遗留的契约未同步）**：step-9（commit `abe4adf`）把 `kernel_architecture` 从 design 阶段挪到 `codegen_init`（codegen 阶段）产出，且语义从「kernel 计算架构（数据流/分块/流水）」变成「section 目录声明清单」（`codegen_init.py` 确定性生成 `{host_code, kernel_code, [+api_code, +plugin_code]}`，由 repo_profile 决定，**与算子设计内容无关**）。design 阶段多处注释明示「kernel_architecture removed (step 9): now produced by codegen_init」。
- **观测（契约未同步）**：但 `TestAnalyzeStage`（test_design 阶段）的 `input_contract.requires` / `validate_inputs` / `_upstream_inputs` / `prompt_intro` 仍硬依赖 `kernel_architecture`（写于 step-9 之前的 commit `848a955`/`8689305`），未随 step-9 同步。
- **实测**：run `20260705-072625-72f58b` resume 走到 test_design 首子 stage test-analyze → `validate_inputs` 报 `test-analyze requires 'kernel_architecture' (design product missing)` → `PreconditionError` → dispatcher halt → `EX_DATAERR`（exit 65）。文件 `design/integrate/kernel_architecture.json` 虽存在，但 step-9 后 design 不再把它读进 `state.kernel_architecture`（State 字段为 None），校验看的是 State 字段、非文件。
- **与 resume 无关**：workflow 顺序 design→test_design→codegen，test-analyze 跑时 codegen_init 未跑，`state.kernel_architecture` 必为 None。首次 run 跑到此处也会同样 exit 65；用户未早撞见仅因首次 run 在 design 的 validate 阶段就中断。
- **凭什么是缺陷而非 test-analyze 真需要它**：① test-analyze 真正做测试分析需要的是 `design_spec`+`tiling_strategy`+`requirement`（design 阶段仍产出、且 test-analyze 之前就绪）；`kernel_architecture` 现只是「codegen 建哪些目录」的清单，对测试分析无信息价值。② `test_analysis` 下游仅 `test-casedesign` 消费（`requires=["test_analysis"]`），不间接需要 kernel_architecture。③ step-9 改了产出方+语义+时机，唯独漏了 test-analyze 这一侧——重构没收尾，非真实依赖。

### 关联

- 与 step-9 重构（commit `abe4adf`）直接相关：那次把 kernel_architecture 从 design 挪到 codegen_init，test-analyze 契约漏改。
- 与 CLAUDE.md §1.2（可维护：澄清不变式——design 产物 = design_spec/tiling_strategy，不含 kernel_architecture）、§1.4（彻底改、不留过渡）相关。
- 触发实例 run `20260705-072625-72f58b` 由 `scripts/e2e_self_evolve.sh` 拉起；用户最初感知的「approve 后 exit 65」即此问题（approve 放行 validate 后，下游 test-analyze 立即 fail-fast），与 P31（非交互变交互）是两个独立 bug 叠加，须分开治。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-05 | P32 记录 + 修复落地（step-9 漏改的契约同步）：`TestAnalyzeStage` 四处删 `kernel_architecture` 依赖——`prompt_intro`、`input_contract.requires`（收敛为 `[requirement, design_spec, tiling_strategy]`）、`validate_inputs`（硬校验项去掉它，附注 step-9 后该字段挪到 codegen_init 且语义变成 section 目录清单、与测试分析无关）、`_upstream_inputs`（删该键）。同步 3 个 UT 的守卫契约演进（`test_test_design_stage` 的 requires 断言 + 新增 `validate_inputs` 无 kernel_architecture 即通过；`test_test_design_group` / `test_test_design_materialize` 的 requires / 物化文件断言）。属契约同步非逻辑 bug，未单独走红→绿，直接改 + 全量回归：UT 1550 绿。 |

## P33: test_design external-cases 短路 NoOp 与 output_contract 冲突——NoOp 死循环耗尽 budget 误 halt（exit 65）

### 事实

- **观测（短路设计与契约的矛盾）**：13 E1 引入 external cases 短路——`state.cases_path` 非空时，test_design 三 substage（`_TestDesignSubstage.actions`）返 `NoOp`、`transition` 纯 passthrough（不产出 `test_analysis`/`test_casedesign`），但各 substage 的 `output_contract` 仍硬 `provides` 这些字段。runner（`kernel/runner.py`）严格查 `output_contract.provides`（早终止条件 / max-iter warn / stage_status=partial）→ NoOp 永远不满足 → 死循环到 max_iter → `partial` + `fail_strategy=halt` → `EX_DATAERR`（exit 65）。
- **实测**：run `20260705-072625-72f58b`（Bug A/B 修完后 resume）走到 test-analyze。`events.jsonl` 铁证：`stage_skipped("external cases_path supplied ...")` → `iteration_complete ok` → `iteration_start "contract unsatisfied: test_analysis"`，该序列循环 3 次 → `stage_complete(total_iterations=3)` → partial + halt → exit 65。state：`cases_path='.../cases.csv'`（非空）、`test_analysis=None`、`stage_iterations["test-analyze"]=3`。
- **三 substage 都中招**：test-analyze / test-casedesign 短路时 transition 纯 passthrough（provides 永不满足）；test-casegen 短路时虽 `_load_external_cases` 设了 `test_cases`，但 `test_design_report` 没设（provides 仍不全）。test-analyze 最先撞，故日志只见它。
- **与 resume 无关**：首次 run 走到 test_design external-cases 也会撞；resume 仅因首次在 design 的 validate 中断而提前暴露。Bug A（非交互继承）/ Bug B（kernel_architecture）已修好（日志反证：未变交互模式、test-analyze 正常启动），本问题在其下游。
- **为什么不能简单「runner 对所有 NoOp 豁免 contract」**：现有 `_OutputNeededStage`（`test_kernel.py::TestMaxIterations`）就是 `actions=[NoOp()]` + `provides` 未满足，其裸 NoOp 代表「stage 本该产出却没产出」（真 bug），runner 的 warn/partial 是正确可观测信号。一刀切豁免会掩盖这类真 bug（违反 §3.4）。须区分「确定性跳过」（合法、应豁免）与「裸 NoOp」（疑似 bug、保留 warn）。

### 关联

- 与 13 E1（external cases 适配，`_has_external_cases` 短路）、CLAUDE.md §1.2（四把尺子：可维护/可扩展/可诊断/架构合理）、§3.4（不掩盖失败）直接相关。
- `output_contract(self)` 无 state 参数，不能基于 `state.cases_path` 动态返回空 provides → 修复落点：`NoOp` 显式声明「确定性跳过」+ runner 按声明豁免（职责正确：stage 声明意图、runner 按声明走，不猜）。
- 触发实例同 P30/P31/P32 的 run `20260705-072625-72f58b`，但根因独立（不在 resume 链路，在 test_design 短路与 output_contract 的设计矛盾，是 13 E1 引入的）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-05 | P33 记录 + 修复落地（TDD 红→绿）：① `action.py` `NoOp` 加 `contract_satisfied: bool=False`（显式「确定性跳过」声明）；② `runner.py` 三处识别 `NoOp(contract_satisfied=True)` 豁免 output_contract（早终止 + 不 warn + 不 partial），裸 `NoOp()` 行为不变（保留「stage 未产出」的可观测 warn/partial，`_OutputNeededStage` 测试仍绿）；③ `test_design_substages.py` 基类 `_TestDesignSubstage.actions` 的 external-cases NoOp 加 `contract_satisfied=True`（三 substage 共享一处）。测试：`test_kernel.py::TestNoOpContractSatisfied`（4 用例，红时精确再现 `{sc_stage: 3}` 死循环 + warn + partial）→ 绿；`test_test_design_stage.py::TestExternalCasesShortCircuit` 扩展断言三 substage 短路 NoOp 带 `contract_satisfied=True`（防回归）。回归：全量 UT 1554 绿。**已静态确认短路路径无下游阻塞**（回应「明知阻塞为何不修」）：`test_design_report` 全 src 无业务消费者；codegen `requires=["design_spec","tiling_strategy","mode","profile"]`、`validate_inputs` 只查 design_spec，不读任何 test_design 产物；`test_analysis`/`test_casedesign` 仅 substage 链内互消费且 `input_contract.requires` 无运行期硬校验（仅 `validate_chain` 静态 warning）；`test_cases` 由 `_load_external_cases` 真实加载喂 verify——test_design→codegen→verify 接力无 None 阻塞。**未覆盖**：真实 resume 续跑 e2e（heavy_llm，§3.11）由用户择机验证整体接力（静态已判无阻塞，e2e 兜真实 LLM/时序行为）。 |

## P34: cann-bench cases 加载链路名实不符 + 批量评测未接通外部 cases 喂入（self_evolve_op cases 来源待定稿）

### 事实

- **观测（命名名实不符，已修）**：`domain/cases_loader.py`（已正名 `cann_bench_cases_loader.py`）对外 API 旧名 `load_cases`，但实现 `parse_cann_bench_csv` 仅解析 cann-bench 专有格式——列名 `operator/case_id/input_shape/dtype/attrs/value_range`、dtype map（float16→fp16 等）、`value_range→generator` 均按 cann-bench 约定；文件头注释明示「Bridges an external cann-bench cases.csv」。对外通用名 `load_cases` 与 cann-bench 专属实现不符，误导维护者以为它支持多种 cases 格式（实际只有 cann-bench 一种）。
- **观测（批量评测未喂 cann-bench cases）**：`self_evolution/scheduling.py` 的 `_run_subprocess` 构造 `self_evolve_op` 子进程命令时不含 `--cann-bench-cases`（命令仅 `run --workflow self_evolve_op --non-interactive [--op-dir / --output-root / --npu-id]`）。批量跑 cann-bench 算子时，每个 op 的 `self_evolve_op` 因 `state.cases_path` 为空走 test_design 的 LLM 用例设计链路（`_has_external_cases` 为 False），而非用 cann-bench 预定义标准 cases。
- **观测（cann-bench cases 资源缺失）**：仓库内无任何 `cases.csv`；`tasks/` 目录不存在；`scripts/e2e_self_evolve.sh` 默认 `CASES=$REPO/tasks/level1/exp/cases.csv`（该路径不存在，占位）。
- **观测（cases 加载物理出口唯一）**：`cases_path → state.test_cases` 的唯一加载点是 `TestCaseGenStage.transition._load_external_cases`（调 `load_cann_bench_cases`）；`verify.py` 只读 `state.test_cases`，不读 `state.cases_path`。故删 test_design stage 而不迁移加载逻辑 → cases 进不了 state → verify 无用例。
- **凭什么是缺陷（benchmark 语境）**：cann-bench 是 benchmark，评测打分的可比性 / 公平性 / 可复现性来自所有算子用同一套预定义标准 cases。`cases_loader` 的整个设计（格式、列、dtype / 范围映射）就是为 cann-bench cases 服务，证明设计意图是「评测吃 cann-bench cases」。批量评测走 LLM 临时设计 cases = 自出题自考，不可比、不可复现，违背 benchmark 初衷。

### 关联

- 与 P33（external-cases 短路）同源：`_has_external_cases` 曾是二值开关，`_TestDesignSubstage.actions` 的 external-cases NoOp 短路是「互斥」语义（有外部 cases 就跳过整条 LLM 链路），不支持「cann-bench ∪ LLM」融合验收。**已解决（2026-09-23）**：`AscendCSTDesignStage` 改为增量融合——有 workspace 时外部 cases 与 LLM 产物合并（外部在前、`cases_source` 仍 `cannbench`），无 workspace 退化为确定性加载，见变更记录。
- 与 CLAUDE.md §1.2（可扩展：cases 来源应策略可切换）、§1.3（命名 / 加载期清晰反映约束）、§1.5（资源路径）相关。
- `self_evolve_op` 的定位（评测专用 vs 通用流水线）决定 test_design 在该图的去留与 cases 加载层的落点——属 L3 决策范畴；本层只记「定位待定稿、当前代码是通用流水线形状」这一事实。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-05 | P34 记录（客观事实）+ 命名修正落地（名实不符部分）：`cases_loader.py`→`cann_bench_cases_loader.py`、`load_cases`→`load_cann_bench_cases`（对外 API 自注释 cann-bench 专属；内部 `parse_cann_bench_csv` 名字本就正确不动）；调用点 `test_design_substages.py:_load_external_cases` 同步；测试 `test_cann_bench_cases_loader.py` 同步（类名 / 方法名 / import 路径）。回归：`test_cann_bench_cases_loader.py` + `test_test_design_stage.py` 共 33 绿。**待拍板（另立 L3）**：`self_evolve_op` 定位（评测专用 / 通用）、批量评测接通 cann-bench cases 喂入、test_design 在 `self_evolve_op` 图的去留、cases 来源策略。 |
| 2026-09-23 | **增量融合落地（cann-bench ∪ LLM，P34 关联「互斥语义」缺口关闭）**：`AscendCSTDesignStage.actions` 不再在 `cases_path` 存在时 NoOp 短路——有 workspace 时始终跑输入适配器 + spawn LLM；`transition` 融合 `external + generated`（外部在前，`cases_source="cannbench"` 保持 benchmark 标准对齐），任一来源为空不报错、仅合并仍空才失败，外部主源已交付而 LLM 补充缺失时留 `user_feedback` 可观测信号（§1.2）；无 workspace 退化为确定性加载外部 cases 的 standalone 路径。prompt 增增量补充提示（`_extra_prompt_sections`）。ST `TestExternalCasesIncremental`（8 用例）红→绿。**附带修复 codegen Regbase 缺口**：`_build_s2_prompt` / `_build_s4_prompt` 补指名 `test_cases.json`（此前只物化到 staging 未在 prompt 消费；Membase 路径早有），UT `TestRegbasePromptSurfacesTestCases` 4 用例守护。P34 其余部分（`self_evolve_op` 定位 / 批量 cann-bench cases 喂入）仍待拍板。 |

## P35: fail_strategy='halt' 的 stage 被标 node_status='completed' → dispatcher resume 误判 all_done、静默跳过未跑的下游 stage

### 事实

- **观测（resume 假完成）**：run `20260705-072625-72f58b` 在 `test-analyze` halt 后 resume，只输出 `[INFO] All stages already completed, regenerating report` 即退出（log `e2e_self_evolve_20260705-072625-72f58b.log:137`），但 `codegen`/`verify`/`cannbench_adapt`/`cannbench_eval` 实际从未运行。
- **观测（halt 不抛异常）**：`fail_strategy='halt'` 的 stage 失败时，`kernel/runner.py`（halt 处理段）不抛异常，只设 `state._stage_failed=(stage_status, stage.name)` 信号；`_execute_sequential` 读该信号设 `is_terminal=True` 停止当次遍历。
- **观测（_execute_atomic 无条件标 completed）**：`graph_executor.py:_execute_atomic` 在 `run_stage` 正常返回（无异常）后，无条件 `node_status[path]="completed"`。halt 走「无异常」返回路径 → halt leaf 被标 "completed"。
- **观测（_group_status 只识别 failed 子节点）**：`_group_status` 仅当某子节点 == "failed" 才标 group "failed"，否则 "completed"。halt leaf 是 "completed" → test_design / 根 一层层被标 "completed"。
- **观测（dispatcher resume 唯一判据）**：`application/dispatcher.py` 的 `all_done = ns.get(workflow.name) == "completed"` 是唯一判据；根 == "completed" → 误判 all_done → 静默退出、跳过未跑的下游 stage。
- **证据（snapshot）**：该 run 的 `state_snapshot.json` `node_status` 全为 "completed"（根=completed、test-analyze=completed），codegen/verify 节点缺席，`is_terminal=True`——与「全完成」表象吻合，但下游从未跑。
- **凭什么是缺陷**：halt 语义是「stage 耗尽修复预算、不可自动恢复的失败停机」，应反映为失败，而非 completed。`_group_status` docstring 自称「Bubbled-up halts use the separate is_terminal path and are not affected here」，但 `is_terminal` 不进 `node_status`、而 dispatcher resume 只认 `node_status`——`is_terminal` 救不了 resume 权威，halt 的 leaf 必须在 node_status 上标 failed，否则 resume 把「未跑下游」误判成「全完成」，用户只能从头重跑数十分钟的 design 才能续上。

### 关联

- 与 P29（resume 断点权威 = snapshot）同域：node_status 是 resume 唯一权威，halt 必须在 node_status 上正确反映为 failed，否则断点重建出错。
- 与 §1.2 四把尺子：可维护（halt 语义=失败，node_status 应如实反映）、可诊断（误判 all_done 把「未跑下游」掩盖成「全完成」，是最难定位的失败形态）、架构合理（node_status 标记职责在 `_execute_atomic`，is_terminal 是当次遍历停止信号，二者职责不同不可混用——不能指望 is_terminal 兼任 resume 权威）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-05 | P35 TDD 红→绿修复：`graph_executor.py:_execute_atomic` 在标 "completed" 前检查 `_stage_failed` 信号，若被设则标 "failed"（镜像既有异常分支 line 142-143）。halt leaf 标 failed → `_group_status` 自动传播 failed 到 test_design 与根 → dispatcher resume `all_done=False` → 找到 pending leaf 续跑。测试：`test_graph_executor.py::TestHaltMarksNodeFailed`（halt atomic 标 failed + 嵌套 group 传播到根）红→绿；`test_stage_failure_status.py` 既有 halt/failure 传播不变式守护全绿。回归：全量 UT 1556 绿（原 1554 + 新增 2）。 |
| 2026-07-05 | P35 补强：dispatcher `all_done` 纳入 `is_terminal`（halt 终止 ≠ 全完成）。P35 bug 遗留的脏 snapshot（root 被错标 completed + is_terminal=True）下，旧判据只认 `root=="completed"` → 静默 "All stages already completed" 退出、跳过未跑下游 stage；补强 `all_done = root_completed and not is_terminal` 后，即便 root 假完成也进续跑分支。ST `test_resume_cli.py::test_resume_terminal_with_root_completed_not_all_done` 红→绿；`test_resume_without_workflow_succeeds`（正常 all_done 路径）仍绿。回归 UT 1556 绿。**注**：此为通用防御（防未来任何 root 假完成静默退出）；该 run `20260705-072625-72f58b` 的历史脏 snapshot 另作一次性运维纠正（清 root/test_design 子树 completed + is_terminal=False，保留 design 阶段），不进代码——脏 snapshot 是 bug 遗留物，非正常数据，代码修复（_execute_atomic 标 failed + all_done 补强）已防未来不再产生。 |

---

## P36: docgen 详设说明书不达 v2.0 模板保真，design_doc.json 无文档消费者

### 事实

- run `20260705-072625-72f58b` 的 docgen 产物 `<op>_详细设计说明书.md` 仅 dump `design_spec`/`tiling_strategy` 的 JSON，未按 skill 自带 `doc_template_v2.0.md` 章节组装；`DocgenStage` 确定性渲染（`actions()` 恒空、不 spawn agent、不读模板）。
- design_doc 当前无「文档消费者」：design group 对外契约仅 `design_spec`/`tiling_strategy`（不含 design_doc）；validate 自 P20 不核 design_doc 内容、`redo_doc` 直接 `__halt__`；codegen 消费 `design_spec`/`tiling_strategy`。
- `state.design_doc` 字段被 ValidateStage 复用为 validation_report 路由载体（transition 折叠 report、resolve_condition 读 report 路由）——字段复用，非文档消费。
- DetailedDesignIntakeStage short-circuit（外部 `--detailed-design` 输入）直接调 `DocgenStage._render_detailed` 渲染 design_doc。
- skill 通路（SKILL.md + 模板 + section_mapping）完整存在未接线；`kernel_architecture` 已于 step 9 从设计输出移除。

### 关联

- 与 P13（kernel_pseudo_code 单条装载职责，已修）不同：P36 是整条模板保真 + skill 接线 + design_doc 去留的架构议题。
- 与 P20（validate 脱终稿）同源：design_doc 是无代码消费者的人类交付物；validation_report 寄生于 design_doc 字段是 P20 大修的连带。
- 上承 `15` §3.4（design_doc 角色重定位）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-05 | P36 记录，待拍板（见 `21-docgen-template-fidelity-analysis.md`）。 |
| 2026-07-06 | 定案 B（design_doc 降索引 + skill 降手工参考 + 改名）——**已推翻**（方向反：B 处置「md 无意义 dump」，正解是让 md 达模板保真 + 撤销聚合 json）。 |
| 2026-07-06 | **推翻 B，定案 Y**：撤销 design_doc.json；md 改 LLM 接 skill 生成 v2.0 模板保真文档；`state.design_doc` 存 md 路径（预留消费者锚点，不阻塞）；同步解 validation_report 寄生 + dd-intake 短路渲染两耦合。详见 `21`（L3）、`22`（L4）。 |
| 2026-07-06 | **实施完成（路径 Y，L4 步0-步7）**：① 回滚 B 残留；② 解 validation_report 寄生（独立 State 字段）；③ 解 dd-intake 短路耦合（`design_doc=str(path)`）；④ DocgenStage 改 LLM spawn（disk-first 读 `<op>_详细设计说明书.md`，无则 halt）；⑤ skill 接线 `STAGE_SKILL_MAP`；⑥ 撤销 `design_doc.json` schema + 清四引用；⑦ concept render 处置确认（`_render_concept` 已删，concept group 独立不接 docgen）。回归：UT 1548 绿、非 heavy ST 全绿（test_design_pipeline_e2e 适配 disk-first 注入 workspace + stub 写 md；test_npu 10/10）。heavy_llm `test_design_tui_selfclosure` 待用户决策跑。 |

---

## P37: dd-intake short-circuit 是「复用详设进 codegen」捷径，意图成立但未落地

### 事实

- DetailedDesignIntakeStage（detailed-design group 首节点）：用户提供 `--detailed-design <md>` 时 spawn agent 忠实转写为 design_spec/tiling_strategy，`short_circuit` 跳到 validate，跳过 division/tiling/anchor/integrate/docgen；codegen 消费两件套（`CodegenStage.requires` 只要 design_spec/tiling_strategy，short-circuit 链路对 codegen 成立）。
- 三个未落地点：① `--detailed-design` 仅见于 `docs/plan` 规划文档，scripts/CI/e2e 零实际调用，无 ST 真跑 short-circuit 全链路；② `validate.requires=[design_spec,tiling_results,anchor_report,template_division,general_design]`，short-circuit 跳过后三者全缺，validate 在 short-circuit 下契约未对齐（降级核接口、未显式处理）；③ 用 `ascendc-design-generator`（本职生成）做「忠实转写」（抽取），职责错配。

### 关联

- 服务「算子增量开发」（复用已有详设直接进 codegen）——未来主要开发场景，优先级中。
- 当前核心目标为 self-evolution cann-bench 端到端评测 + 自我迭代（非本条路径），故暂缓。
- P36 解耦 2 仅做最小处理（dd-intake 不崩），本条根本问题不在 P36 修。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-06 | P37 记录：dd-intake short-circuit 意图成立（codegen 只要两件套）但未落地（无实际使用 + validate 契约缺口 + 职责错配）；增量开发为未来主要场景、优先级中，当前核心为 cann-bench 端到端，暂缓补全。 |

---

## P38: docgen 真实 LLM 组装无 heavy_llm 守护（md 模板保真质量缺口）

### 事实

- P36 把 DocgenStage 从确定性渲染改为 LLM spawn（disk-first 读 `<op>_详细设计说明书.md`），docgen 真实链路变成「agent 按 skill 组装 md」。
- docgen **编排链路**（disk-first transition + 契约 + workspace）由 `test_design_pipeline_e2e`（stub ST）覆盖；但 md 的**模板保真质量**（v2.0 章节骨架 / Kernel 伪码全量装载无摘要 / 各 4.x 节独立 / mermaid flowchart）无真实 LLM 守护。
- `test_design_tui_selfclosure`（@llm heavy）测 integrate/template-division 自闭环，不覆盖 docgen skill。
- 即 P36 路径 Y 的核心交付「md 达 v2.0 模板保真」缺真实 LLM 兜底（§3.9）。

### 关联

- 上承 P36（docgen 改 LLM spawn 的连带缺口）。
- §3.9（真实链路必须有真实测试守护）+ §3.11（heavy_llm 执行前用户决策）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-06 | P38 记录并补全：新增 `tests/st/test_design_docgen_tui_selfclosure.py`（`@pytest.mark.llm`，heavy_llm）。seed design_spec/tiling_strategy/tiling_results(多模板 + `buffer_kernel.kernel_pseudo_code` 5 函数，各模板带独特标记)/general_design → spawn `/stage-design:ascendc-op-design-docgen` → 验证 `<op>_详细设计说明书.md` 模板保真（v2.0 章节骨架齐 / 两模板 kernel 标记均落地 / Init/CopyIn/Compute/CopyOut/MainLoop 5 函数名齐 / 无"同 4.x" / 含 mermaid `flowchart TD`）。跑绿 1/1（287s）。 |

---

## P39: resume 续跑 halt 终止的 run 时空转退出、失败 stage 不重试（is_terminal 临时旗子泄漏进 snapshot）

### 事实

- **观测（resume 空转 + halt 复报）**：run `20260706-153520-e8f653` 在 `general-design-generator` halt（key 额度耗尽、网关 401 Invalid token）后，`RESUME=20260706-153520-e8f653` 续跑只输出 `✓ workflow done (0.0s)` + 重复一遍 halt 消息即退出（log `e2e_self_evolve_20260706-153520-e8f653.log` 00:33 段），失败的 `general-design-generator` 从未重跑。
- **观测（is_terminal 是临时旗子却进 snapshot）**：`state.py` 把 `is_terminal` / `_stage_failed` / `_bubble_condition` 标注为 transient（同 `_loopback_feedback`），但 `to_snapshot` 只 pop 了 `_loopback_feedback`/`_workspace`，漏 pop 这 3 个 → halt 时 `_execute_sequential` 设的 `is_terminal=True` 被写进 `state_snapshot.json`。
- **观测（resume 读回旧旗子即空转）**：`from_snapshot` 透传 `is_terminal=True`；resume 当次 `execute` → `_execute_sequential` 开头 `if is_terminal: break` 立即停 → 失败 leaf（在 `node_status` 是 "failed"，本应被 `_execute_node` 重跑）根本没机会跑 → 整个 pass 空转、root 保持 "failed"、dispatcher 读 in-pass `is_terminal`（execute 当场未重立则 False，但 root 非 completed 已走续跑分支后又因 0 节点跑动复报 halt）。
- **证据（snapshot）**：该 run `state_snapshot.json` 含 `is_terminal=true`，与「该字段是 transient、不该跨次执行存活」自相矛盾。
- **凭什么是缺陷**：`is_terminal` 语义是「当次执行中途停了」的 per-pass 控制流旗子，不是「这个 run 永久停了」的持久态。让它跨次存活，等于把「上一趟停过」误当「本趟也已停」，resume 的重试语义被废。node_status 才是 resume 唯一权威（`_execute_node` 只 skip "completed"，"failed" leaf 本就会重跑），临时旗子不该掺和。

### 关联

- 上承 P35 / P35补强：P35 让 halt leaf 正确标 "failed"（node_status 维度修对）；但 P35补强 给 dispatcher `all_done` 加 `and not is_terminal` 是为防「is_terminal 泄漏进 snapshot 造成的脏态」。脏态根因（to/from_snapshot 漏 pop）一修，该子句即成死代码——故 P39 一并删除，判据交回 node_status 单一权威。
- 与 P29 / step-16（SIGKILL resume）同域：强杀 resume 靠 node_status 完成前沿，**不读 is_terminal**（`test_graph_executor.py::TestResumeAfterKill` 全程只看 node_status），故本修复不影响强杀 resume——反把「node_status 是唯一续跑权威」贯彻到 halt resume，更一致。
- §1.2 四把尺子：可维护（transient 字段在序列化边界统一 pop，澄清不变式）、可扩展（未来新增 transient 字段同类自动归位）、可诊断（resume 不再静默空转，失败 stage 真重跑留下 turn 流）、架构合理（临时信号 vs 持久权威职责分明）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-06 | P39 TDD 红→绿修复：① `state.py:to_snapshot` 挨着既有 `_loopback_feedback` pop，增 pop `is_terminal`/`_stage_failed`/`_bubble_condition`；`from_snapshot` 挨着 `_workspace` pop 同 3 字段（落回 dataclass 默认 False/None/""）——既修新写入，也让已坏的 run 文件（已存 is_terminal=True）能续跑。② `dispatcher.py` `all_done` 回退为 `ns.get(workflow.name)=="completed"`，删 P35补强 的 `and not is_terminal` 子句 + 注释（泄漏修了即死代码）。测试：UT A `test_state_routing.py::TestTransientFieldsNotPersisted`（to_snapshot 丢 3 字段 / from_snapshot 重置 / round-trip 清洗，3 例）+ UT B `test_graph_executor.py::TestResumeRetriesAfterHalt`（halt snapshot → execute 重跑失败 leaf → node_status 翻 completed、is_terminal False）红→绿；删 ST `test_resume_cli.py::test_resume_terminal_with_root_completed_not_all_done`（断言 root=completed+is_terminal 矛盾态须 exit≠0，post-fix 该态不可构造，§1.4）。回归：全量 UT 1552 绿 + `test_resume_cli` 2 绿 + `test_integration`/`test_self_evolution_stages` stub ST 77 绿；SIGKILL-resume 回归（`TestResumeAfterKill`、`TestInterruptResumePersistence`）仍绿。**未覆盖**：heavy_llm e2e 真实 RESUME 续跑（§3.11，quota 恢复后 `RESUME=20260706-153520-e8f653` 由用户择机验证 `general-design-generator` 真重跑）。 |

---

## P40: resume 不挂回 `state._workspace` → 设计类 stage cwd 退化到 artifacts 根、产物写错位置、契约死循环

### 事实

- **观测（cwd 退化）**：run `20260706-153520-e8f653` 首跑 `general-design-generator` 的 agent cwd 为 `<run>/artifacts/design/general-design-generator`；P39 修复 is_terminal 泄漏后 resume 同 run，该 stage 重跑时 cwd 退化为 `<run>/artifacts`（根目录）——agent 把 `general_design.json` 写到根目录、自检通过、结束 session，框架 `_parse_single` 却从子目录读不到 → `contract unsatisfied: general_design` 循环 5 轮耗尽 budget。
- **根因（resume 未挂回 workspace）**：`State._workspace` 是 transient，`to_snapshot`/`from_snapshot` 都 pop 它（workspace 含不可序列化对象，pop 本身正确）。但 dispatcher new-run 分支构造 State 时传了 `_workspace=workspace`，**resume 分支的 `with_updates(...)` 没传**——workspace 对象在 resume 段已重建（`Workspace.from_existing`），却没挂回 state。`_DesignSubstage._working_dir` 读 `state._workspace`，为 None 即返回 None → runner 的 cwd fallback 到 `self._workspace.artifacts`（根）。
- **凭什么说是 resume 恢复完整性的缺口**：与 P31（run-control 参数继承断裂）同构——new-run 传了、resume 漏传，半截子修复（§1.4）。P39 修了 transient 旗子（is_terminal 等）泄漏、让 halt leaf 真重跑，这个潜伏 bug 才被推到台前。
- **影响范围**：任何 resume 续跑、且用 `_working_dir(state)` 定位产物的设计类 substage（general-design-generator / detailed-design 各段 / tiling 各段）。首跑不受影响（new-run 挂了 workspace）。

### 关联

- 与 P39（is_terminal 泄漏，同 run 触发）同处 dispatcher resume / state 序列化边界；P39 修旗子泄漏、本条是 workspace 挂回缺失，二者独立。
- 与 P29 / P30 / P31 同属 dispatcher resume 段「state 完整恢复」工作族。
- 本次反复失败的真因是本条，非 P41（agent 自检已通过，只是 cwd 错位使自检文件 ≠ 框架读取文件）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-06 | P40 记录（小问题，仅 L1）+ 修复：dispatcher resume 分支 `with_updates` 补 `_workspace=workspace`（对齐 new-run 分支），resume 后 `_working_dir(state)` 不再返 None、cwd 不退化。TDD `test_resume_reattaches_workspace` 红→绿守护。 |

---

## P41（降级/待观察）: 同 stage 内迭代不把上次失败原因传给下一次 prompt

### 事实

- **原观察**：同 stage 内迭代重试时，下一轮 agent 的 prompt 仅含泛泛「这是第 N 次尝试」，不告知上一轮为何失败（文件没产出？schema 不合规？）。runner 算出的 `_iteration_reason`（contract unsatisfied / quality fail + rendered issues，P25/Step4 成果）只进日志行、不进 prompt；`_parse_single` 设的 `state.last_error` 也未被 `_build_prompt` 读取。
- **机制**：结构化反馈通路 `state._loopback_feedback` 只在**跨节点** loopback 时被 GraphExecutor 写入；runner 的同 stage 迭代 for 循环不写它，故同 stage 重试时恒为空。`GeneralDesignStage` 重写 `_build_prompt` 时还丢掉了基类对 `_loopback_feedback` 的读取。
- **重新定位（为什么降级）**：`ascendc-op-general-design` SKILL.md 步骤13 已强制「自检失败 → 就地修正直到通过，不自检通过则不允许结束」，且自检判据 `schema/general_design.json` ≡ 框架 `output_contract` 用的同一份 schema。即 **session 内自检闭环是设计意图**——自检通过 ≈ 框架接受，理论上不该触发同 stage 重试。故本条只在 **agent 偶发不遵守自检 / 自检与框架标准存在真实 gap** 时才有触发场景，是「兜底的兜底」，不是主修复。
- **本次失败真因不是本条**：run `20260706-153520-e8f653` resume 后反复 unsatisfied，根因是 P40（cwd 错位使 agent 自检的文件 ≠ 框架读取的文件），不是「原因没传递」。修 P40 后自检闭环即通。
- **stage 迭代的架构定位（为何降配而非删除）**：stage 内迭代有两个 session 自检替代不了的场景——① **session 异常退出**（API 雪崩 / stage-timeout / 进程崩溃）→ 根本无产物、自检没机会跑，只能 stage 层重 spawn 兜底；step-11 的 resume-retry 门控是 **SDK 层 turn 级**（session 还活着时吸收 API 抖动），**不覆盖 session 整体崩溃**，两层职责不重叠。② **LLM 非确定性**：重试吸收抖动（§3.10），次要价值。故 stage 迭代机制保留，触发面靠 P42 + 降配压缩。
- **凭什么是「待观察」而非「不修」**：触发条件随 P40/P42 收窄——P40 修复消除了「假性 contract unsatisfied」（cwd 错位致 agent 自检的文件 ≠ 框架读取的文件，正是 run `153520` 跑满 5 次的真因）；P42 落地（session 机械自检）使 session 一次合格率大升、自检漏网触发迭代大减；**P42 落地后收口动作：生成类 stage `default_max_iterations` 降配（如 general-design 5→2，只留异常兜底）**。本条触发条件随之改为「**降配后仍出现 agent 自检通过却重试的真实残余**」——届时才立 L3/L4；若基本不触发，P41 自然消解、不立。避免为可能不发生的重试场景预造原因传递机制（[avoid-overdesign]）。

### 关联

- 与 P25（迭代行日志不可读，已修）互补：P25 接「人看日志」这一半，本条是「agent 看下次 prompt」那一半——但仅在自检闭环漏网时才需要。
- 上游治本见 P42（把 session 内自检从主观判断升级为机械校验）；P42 落地后本条触发面进一步缩小。
- 本次失败真因是 P40（cwd 错位），非本条。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-06 | P41 记录并降级为待观察：同 stage 迭代不传失败原因是真实缺口，但 session 内自检闭环（skill 步骤13，自检标准 ≡ 框架 schema）是其上游治本；本次反复失败的真因是 P40（cwd 错位）非本条。暂不写 L3/L4，待 P40 修复后 e2e 验证是否仍有真实触发。 |
| 2026-07-06 | 补 stage 迭代架构定位：不删除（session 异常退出兜底 + SDK resume-retry 是 turn 级、不覆盖 session 整体崩溃，两层职责不重叠），触发面靠 P42 + `default_max_iterations` 降配（生成类 5→2）压缩；P41 触发条件收窄为「降配后仍出现 agent 自检通过却重试的真实残余」。 |

---

## P42: session 内自检是 agent 主观判断，缺机械保证 → 自检漏网即外溢为框架重试

### 事实

- **观测**：`ascendc-op-general-design` SKILL.md 步骤13 要求 agent「自检失败 → 就地修正直到通过」，判据是 `schema/general_design.json`（与框架 `output_contract` 同源）。但「自检」当前是 **agent 自己读 schema、自己判**——没有机械手段保证 agent 真跑了 schema 校验、且按其结果行动。LLM 可能：跳过自检、自检后不修、或自检标准被自己放宽。
- **凭什么说是「自检漏网即外溢」**：session 内自检是 P41（同 stage 迭代重试）的上游防线。自检可靠 → 产物在 session 内就合格 → 不触发框架重试 → P41 死代码。自检不可靠（主观）→ 漏网产物外溢到框架 → 框架判失败 → 触发重试 → 才需要 P41 的原因传递。即 P41 的触发概率正比于本条的自检不可靠度。
- **治本方向**：把 session 内自检从「agent 主观判断」升级为「机械校验」——给 skill 配一个确定性的自检脚本（jsonschema 校验产物 + 必填/语义检查），agent `bash` 跑通（exit 0）才允许结束 session。自检结果不依赖 LLM 自觉，session 内闭环有了机械保证。与 CLAUDE.md §1.3（机械校验优于运行期暴露 + LLM 自觉）一致。
- **影响范围**：所有产出型 stage 的 session 内自检（generator 类）。gate stage（anchor/validate）是独立 stage 的框架级校验，不在本条范围。

### 关联

- 是 P41 的上游治本；本条落地后 P41 触发面缩小，P41 是否仍需立 L3/L4 取决于本条后的残余漏网率。
- **落地后收口**：session 一次合格 → stage 内迭代自然不触发，故生成类 stage `default_max_iterations` 降配（general-design 5→2 等，只留 session 异常退出兜底，见 P41 架构定位）。stage 迭代机制不删除（session 整体崩溃的兜底不可由 session 自检替代；SDK resume-retry 是 turn 级、不重叠）。
- 与 CLAUDE.md §1.3（机械校验优于 LLM 自觉）、§3.4（不掩盖失败）相关。
- 边界：session 内机械自检只吃得下 schema/格式/字段类（generator 契约失败正是此类）；跨 stage 权威判定（anchor 可行性 / verify 精度）仍需独立 stage，不适用。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-06 | P42 记录（治本增强，仅 L1）：session 内自检当前是 agent 主观判断、无机械保证，漏网即外溢为框架重试（P41 的上游防线）。方向是给 skill 配确定性自检脚本（jsonschema + 语义检查），agent 跑通才结束。待优先级提升时立 L3/L4。 |
| 2026-07-06 | 补落地后收口：session 一次合格 → stage 迭代自然不触发，生成类 `default_max_iterations` 降配（5→2，见 P41）；机制不删（session 崩溃兜底不可替代）。 |

---

## ✅ P43: `Profile.build_commands()` 遍历全部角色（含 deploy）→ 部署期占位符 `{run_pkg}` 在 codegen prompt 构建期触发 KeyError，codegen 在 agent spawn 前即 abort

### 事实

- **观测（codegen 未 spawn 即 abort）**：run `20260706-192227-63c875` 的 codegen stage 在 agent spawn 前崩溃——events.jsonl 有 `stage_enter`/`iteration_start`/`stage_aborted`，但**无** `action_start`/`spawn_context`；`agents/` 无 coder transcript。报错 `Stage 'codegen' failed: run_pkg`（KeyError 的 str 即键名）。
- **机制（职责越界 + 占位符集合不匹配）**：`Profile.build_commands()` 自陈注释「Display/prompt helper — the adapter runs the real builds」，本只为 codegen prompt 渲染「编译命令预览」。但它遍历 variant 的**全部** `enabled_stages()`（含 `install_runtime`/`install_python`/`smoke` 等 deploy 角色），统一只用 `full_op_name`/`chip_version`/`soc_version` 三个 kwarg 格式化 `command_template`。而 deploy 角色模板含 `{run_pkg}`/`{whl_pkg}`/`{per_op_opp_dir}` 等 **DeployStage 运行期才注入**的占位符 → `.format()` 缺 kwarg → `KeyError('run_pkg')`。
- **机制（崩溃点在 try 块外）**：该函数被 `CodegenStage` 构建 prompt 时于 `actions()` 阶段调用；runner 的 `_run_stage_body` 中 `actions = stage.actions(...)` 位于 try 块**之外**（try 只包 `_execute_actions`）→ KeyError 直接上抛到 `run_stage` 的 except → `stage_aborted(error_type=KeyError)`。
- **连锁（abort → 部署期 smoke 失败 → halt）**：codegen abort → 无 `codegen_manifest.callable_target` → deploy 阶段 build/install 成功，但 smoke 校验「callable_target missing/invalid」失败 → workflow 在 ~9100s halt。state_snapshot 记 `codegen_consecutive_failures=0`（abort 路径未走 consecutive 计数）。
- **凭什么是缺陷**：`build_commands()` 合法职责只是渲染 **build 角色**的命令预览（build 角色模板只含 `full_op_name`/`chip_version`/`soc_version`，本就够用），不该染指 deploy 角色模板。根因是遍历未按 `role == "build"` 过滤——把「展示用」与「运行用」两类命令混进同一格式化路径，而二者占位符集合根本不同。

### 关联

- 独立于 P39–P42（resume / cwd / 自检）系列：本 run 是**首跑**（非 resume），P39/P40 不适用；本条是 codegen→deploy 链路的硬阻断。
- 与 deploy 能力声明（`has_deploy_capability`/`deploy_stages` 按 `_DEPLOY_ROLES` 过滤）形成对照：同文件已有「按 role 过滤」的正确范式，`build_commands` 是漏网未对齐者。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-07 | P43 记录（L1）：`build_commands()` 遍历全部角色致 deploy 占位符 `{run_pkg}` 在 codegen prompt 构建期 KeyError，codegen 未 spawn 即 abort，连锁致 deploy smoke 失败、workflow halt。已与用户确认修复方向：遍历加 `role == "build"` 过滤 + 补 UT。待立 L4。 |
| 2026-07-07 | P43 TDD 红→绿修复：`build_commands()` 遍历加 `if s.role != "build": continue`（对齐 `deploy.py` 既有的 `s.role == "build"` 过滤），docstring 注明只渲染 build 角色、deploy 角色模板（含 `{run_pkg}`/`{whl_pkg}`/`{per_op_opp_dir}`）不再进 prompt 构建期格式化。UT `test_build_commands_skips_deploy_role_placeholders`（构造 build+install_runtime({run_pkg})+install_python({whl_pkg})+smoke variant，断言只返回 build 命令、不抛 KeyError）红（复现 `KeyError: 'run_pkg'` at repository.py:171）→绿。回归：`test_domain.py` 97 绿 / `test_deploy.py` 8 绿（同域 deploy_stages/has_deploy_capability 不受影响）/ codegen stage 28 绿。**未覆盖 heavy_llm e2e，列为 PR 前节点**：P43 是 build_commands 构建期 KeyError（agent spawn 前）、确定性纯逻辑，UT 已复现并锁定根因，非 §3.9 LLM 行为守护对象；PR 前顺带跑一次完整 run 做端到端复盘（非验证此修复点本身）。 |

---

## ✅ P44: validate（check 类 stage）越界做硬件能力判定——把「API dtype 表未列 bf16」等价于「硬件不支持 bf16」，并跃迁到硬性补救（fp32/Cast + tileLength 减半）

### 事实

- **观测**：run `20260706-192227-63c875` 的 anchor-consistency/validate 链路中，AC1 判定项声称「A5（Ascend 950）不支持 bf16」，并据此要求 tiling 回退（fp32 计算 + Cast + tileLength 31744→15872）。该判定跨 loopback 3 轮（corrective 1/3、2/3、3/3）持续 UNVERIFIED/未消解。
- **凭什么是缺陷（两层）**：
  1. **事实层——API 表 ≠ 硬件能力**：A5（Ascend 950PR/950DT）硬件**支持** bf16——同知识库 `Adds`/`Muls` 的 operand 类型 T 表列有 `bfloat16_t` 为证。`Exp` 向量 API 的 T 支持表只列 `half`/`float`，是**该特定 API 未暴露 bf16 重载**（API 层），**不等于**硬件层不支持 bf16。把「某 API 未列 bf16」放大成「硬件不支持 bf16」是 API 层 vs 硬件层混淆。
  2. **职责层——check stage 越界下结构改造令**：即便 Exp API 确无 bf16 重载，正确处置也只是「该 API 调用点用 half/float」或「换等价 API」，**不应**直接跃迁到「全算子必须 fp32 + Cast + tileLength 减半」这种牵连 tiling/kernel 结构的硬补救。check stage 的职责是「对照真实硬件 API 判可行性并报告」，不是「替生成 stage 下结构改造令」。
- **旁证（已有记录的同一错误）**：P4 在阐述「不该跨 stage 读 design_spec dtype」时，把「exp 的 bf16 在 Ascend950 不支持」作为**支撑事实**引用（见 P4 证据段）——本条指出该引用本身即上述事实错误的产物。P4 的结论（跨 stage 读 dtype 会与 codegen 实际签名不一致）不受影响，但其示例事实需更正为「Exp API 未暴露 bf16 重载（非硬件不支持）」。

### 关联

- 与 P45（loopback 反馈不可控）同源：validate 的「硬补救」经 loopback 抛回 tiling，但 tiling 无对应修复 skill（见 P45），故 3 轮空转、判定无法消解。
- check stage 职责边界属讨论项（报告 vs 介入的程度、API 表缺项的归类），暂不展开方案。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-07 | P44 记录（L1）：validate 越界硬件能力判定——API dtype 表未列 bf16 ≠ 硬件不支持 bf16（A5 硬件支持，Adds/Muls 列 bfloat16_t），且不应据此跃迁到 fp32/Cast/tileLength 减半的硬补救。并更正 P4 示例事实。修复边界讨论中，未立 L3/L4。 |
| 2026-07-07 | 已展开 L3：`23-check-feedback-loop-analysis.md` §3（产出端）。定位为 17/18 延伸缺口——约束（disallowed_tools/SKILL/max_iter）齐了仍挡不住 consistency agent 越权（重查 + detail 下改造令），根因是 issue 无「判定/补救」分层 + consistency 拿得到原始知识库文档。推荐 B（能力约束断越权）+ C（schema 分层），A（SKILL 强化）兜底，待 §6 拍板。 |
| 2026-07-07 | **P44 已修复（B+C，详见 `24-check-feedback-loop-impl.md`）**：(C) schema 分层——issue 拆 `verdict`（判定面 unverified/infeasible/verified）+ 可选 `remediation`（非强制），`detail` 严禁结构改造令（`lint_directives` 命中即告警，§6.4 先告警）；三 schema example + consistency/per-template SKILL 同步。(B) 能力约束——**核实后 inputs 层本就未传知识库文档**（`_upstream_inputs` 只给 per-template 报告 + tiling 摘要），越权通道实为 agent `Read`/`Grep` + SKILL「Grep 知识库查证」引导；`AnchorConsistencyStage._extra_prompt_sections` 注入「唯一证据源=per-template 报告，禁止 Grep/Read 原文重查，缺项标 unverified 转 human」stage 级硬约束（工具层无法精确切路径，prompt 注入为唯一硬落点）。per-template 不动（它该查骨架级 API）。UT 18 绿（render_issue/lint_directives/consistency 约束）；heavy_llm e2e 已验证（anchor_hwparams_selfclosure 193s 真实 LLM，anchor 读 hw_params 不越界硬件判定成立）。 |

---

## ✅ P45: loopback 反馈不可控——反馈是自然语言描述（无机可判谓词、无 resolved/escalated 状态）、生成 stage 无修复 skill、问题逐字重报（第一刀+(a) 已修复；(b)(c) 后置）

### 事实

- **观测（3 轮空转）**：run `20260706-192227-63c875` 的 validate→tiling corrective loopback 跑满 3 轮（1/3、2/3、3/3），tiling 生成 stage 收到反馈但无对应「修问题」的 skill/契约，3 轮未实际消费反馈、判定（AC1 bf16）原样未消解。
- **观测（反馈是描述不是指令）**：`issue_render` 产出的 issue 是 `{code, target, target_template, detail, severity}`，`detail` 为自然语言描述，**无机可判谓词**（无 `must_hold`/`predicate` 字段）、issue **无 resolved/escalated 状态**。生成 stage 收到的是一段自然语言，没有可机械校验「是否已修」的判据 → 反馈是否被消费完全依赖 LLM 自觉 → 不可控。
- **观测（同一 issue 跨轮逐字重报）**：同一 AC1 判定跨 3 轮以近似原文重复出现，无「已尝试/已消解/应升级」的状态演进——issue 无生命周期，loopback 无法判定「该停了」还是「该升级」。
- **观测（validate blocked 仍放行下游）**：validate 置 `blocking_status=blocked`（AC1/AC3 blocker）后，下游 codegen 仍被调度（随后因 P43 abort）——blocked 未真正阻断图推进。
- **讨论中的方向（用户提出，未定案）**：
  1. check stage 发现问题，优先在该 stage 的 agent 内就地修，或由该 stage 起 bug-fix agent；把问题抛回「职责是生成、无修复 skill」的生成 stage 没有意义。
  2. 若保留 loopback 的重新生成语义，生成 agent 须**显式定义如何接收并消费**反馈（如约定 `issue_schema.json` 格式、agent 显式消费），否则反馈不可控、loopback 失去意义。
- **补充判据（讨论中）**：反馈宜升级为**机可判谓词**（而非自然语言），并在 issue 上加 resolved/escalated 状态 + 升级出口（N 轮未消解则停/转人工），使 loopback 可机械判定收敛。

### 关联

- 与 P15（✅ loopback 无 target 可达性/无进展校验致死循环）、P18（validate 跨轮无增量、全量重验）、P21（tiling corrective 丢模板精度）同域但正交：P15/P18/P21 是「框架层没检测到空转/重复」，本条是「反馈本身不可控 + 生成 stage 无修复职责」——即便框架检测到，反馈格式也驱动不了有效修复。
- 上游自检可靠性见 P42（session 内机械自检）；本条「生成 stage 显式消费 issue_schema」是其下游对偶——自检保证一次合格、loopback 保证反馈可消费。
- 用户明示「需要讨论、先别急着展开」：本条仅记事实与讨论方向，**未立 L3/L4**；loopback 是否整体过设计、check stage 就地修 vs 起 bug-fix agent vs 保留 loopback + 显式消费，待讨论定案。（**已闭环于 P47**：选「保留 loopback + skill 内自检消费」，否决「起 bug-fix agent」与「check stage 就地修」，详见 `25-feedback-consumption-closure-analysis.md` §5）

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-07 | P45 记录（L1，讨论中未定）：loopback 反馈不可控——反馈是自然语言描述（`issue_render.detail`，无机可判谓词、无 resolved/escalated 状态）、生成 stage 无修复 skill 致 3 轮空转、同一 issue 跨轮逐字重报、validate blocked 仍放行下游。记用户讨论方向（check stage 就地修/起 bug-fix agent；若保留 loopback 则生成 agent 显式消费 issue_schema）+ 补充机可判谓词/状态机/升级出口判据。未立 L3/L4。 |
| 2026-07-07 | 已展开 L3：`23-check-feedback-loop-analysis.md` §4（消费端）。代码调研坐实直接根因——`_TilingSegmentStage._build_prompt` 重写覆盖基类、丢了 `## 上次反馈` 段（已核实），反馈根本没进 tiling prompt。第一刀修此 bug（抽 `_feedback_section` 共用）；第二层先做 issue_id+跨轮追踪（激活停滞检测），must_hold/自动升级后置。待 §6 拍板。 |
| 2026-07-07 | **P45 已修复（第一刀+(a)，详见 `24-check-feedback-loop-impl.md`）**：第一刀——抽 `_feedback_section(state)` helper（基类 `_build_prompt` 与 `_TilingSegmentStage._build_prompt` 共用，**修复 run 3 轮零消费直接根因**：tiling 重写丢 `## 上次反馈` 段），渲染只取判定面（verdict/remediation 标「建议非强制」，不当代码执行）。(a)——issue 工程派生 `issue_id`（`code@target_template`，不入 schema、不需 agent 产出），三个 corrective gate（consistency/validate/general-review）override `error_signature` 返回 issue 指纹，激活既有 `same>=2` 停滞检测（gate 原 `fail_strategy=continue` 不设 `last_error` → 默认签名空 → 停滞检测跳过，run 3 轮空转根因之一）。**复用既有停滞机制，零新出口/状态机**；per-template（max_iter=1 无 corrective）不加。(b) must_hold/(c) 自动升级后置（avoid-overdesign，视第一刀+(a) 后真实残余再立）。UT 18 绿（_feedback_section/tiling 消费/issue_fingerprint/三 gate error_signature）；heavy_llm e2e 已验证（design_tui_selfclosure 285s 真实 LLM，tiling 自闭环消费反馈成立）。 |

---

## ✅ P46: 硬崩溃（actions/transition 抛异常）绕过 `fail_strategy=halt` 信号 → workflow 不停、继续跑下游耗至超时

### 事实

- **观测**：run `20260706-192227-63c875` codegen `KeyError('run_pkg')` 硬崩后，workflow **未停**，继续跑 deploy（build/install 成功、smoke 失败）耗至 ~9100s 超时。日志可见 `crash-halt [aborted]` → `[ERROR] Stage failed` → `should-not-run iteration`（下游照跑）。
- **机制（halt 只对软失败生效）**：`fail_strategy="halt"` 的 stage 有两条失败路径：
  1. **软失败**（quality/contract/迭代耗尽，stage 正常返回但不合格）→ 走 `runner._run_stage_body` 内部 halt 检查，设 `_stage_failed=(stage_status, stage.name)` → `_execute_sequential` 读到 → `break`，停。
  2. **硬崩溃**（`actions()` 抛异常——`actions` 调用在 try 块**之外**）→ `run_stage` except 直接 `raise`（绕过 runner 内 halt 检查）→ `_execute_atomic` 的 `except Exception` 分支只 `mark node "failed"`、**不设 `_stage_failed`** → `_execute_sequential` 读不到信号 → 不 `break` → 继续遍历下游。
- **凭什么是缺陷**：`fail_strategy=halt` 是 stage 的明确声明（"我失败就该停"），但该声明只在软失败路径生效，硬崩溃路径被 `_execute_atomic` 的「tolerate + advance linearly」韧性逻辑吞掉，与声明语义冲突。后果是崩溃后 workflow 在已知坏态上继续跑下游、浪费 budget 至超时——正是本 run 9100s 的直接放大器。

### 关联

- 与 P35（软失败 halt 的 `node_status`/`is_terminal` 信号传播）同域：P35 修软失败路径，本条补硬崩溃路径——两者合并才让 `fail_strategy=halt` 对**所有**失败形态生效。
- 与 P43 同源场景：run `20260706-192227-63c875` 的 9100s 超时是 P43（崩点）+ P46（崩后不停）双重作用。P43 消除崩点，P46 让「万一崩了」也能立即止损。
- 与 P45 的「validate blocked 仍放行下游」是**不同**的「该停没停」：P46 是 `fail_strategy=halt` 硬崩溃没停（halt 信号被吞），P45-C4 是 `blocking_status=blocked` 没阻断图推进（另一套 stop 机制）。两者不要混淆。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-07 | P46 记录 + TDD 红→绿修复：`graph_executor._execute_atomic` 的 `except` 分支在 `mark "failed"` 后，若 `node.stage.fail_strategy == "halt"` 补设 `_stage_failed=("aborted", node.name)`（格式对齐 runner 软失败），让 `_execute_sequential` 走 `break`；`fail_strategy != "halt"` 保留原「advance linearly」韧性（偶发崩溃不拖死整个 workflow）。UT `test_hard_crash_on_halt_stage_stops_pipeline`（halt stage `actions()` 抛 RuntimeError，断言下游不跑 + `is_terminal=True`）红（复现「crash-halt failed → should-not-run 继续跑」）→绿。回归：`test_graph_executor.py` 27 绿（含 P35/P39 `TestHaltMarksNodeFailed`/`TestResumeRetriesAfterHalt`/`TestHaltRouting`）/ `test_resume_cli.py` 2 绿 / `test_state_routing.py` 9 绿。**未覆盖 heavy_llm e2e，列为 PR 前节点**：P46 是 `_execute_atomic` except 控制流分支、确定性，UT 用 RuntimeError 模拟硬崩溃已覆盖 `_stage_failed` 设置（真实 codegen 崩走同一分支）；非 §3.9 LLM 行为对象，PR 前顺带端到端复盘。 |

---

## ✅ P47: 详设反馈消费是 LLM 概率行为——反馈进了 prompt 但「是否被生成 skill 消费」无确定性保证（已修复并实证：skill 内自检确定性消费闭环，heavy_llm e2e 已验证）

### 事实

- **观测（消费是概率性的）**：P45 第一刀（`_feedback_section`）已让 `## 上次反馈` 段进 tiling prompt（UT 守护渲染），但「LLM 是否读了、照做了」无实证——`test_design_tui_selfclosure` 是 happy path（空 `blocking_issues`）+ 直接 spawn 绕过 Stage，未触发 `_feedback_section`，不构成消费证据。
- **观测（反馈无历史/无判据）**：validate 的 `blocking_status.json` 每轮整份覆盖、上一轮 issue 丢失（无法多轮累积自检）；issue schema（P44-C）有 `verdict`/`remediation` 但无「消解判据」（skill 想自检也缺「判什么」）。
- **认知校正（用户主导）**：issue 是给 LLM 的，判据必须 LLM 可执行；不可判 = 判据不严谨 = 产出端缺陷，应修判据而非在消费端造特殊机制（§1.3 同构）。否定前序「机可判 vs 语义」二分（自检主体是 skill 内 LLM，不是框架代码）。

### 关联

- 承接 P44/P45（23/24）：P47 是详设反馈通路第三层闭环（产出端约束 → 产出端 schema + 消费端 prompt bug → 消费端确定性消费）。
- 闭环 P45 后置的 (b)(c)：原框架状态机落点 → 改 skill 内自检。
- 闭环 bug-fix agent 悬空（P45 讨论方向「待讨论定案」）：选 skill 内自检，否决独立 agent。
- 与 P41/P42（session 内自检）同源：P47 是「跨 stage 反馈被消费」的自检保证，是 P42 框架层自检在 skill 内的对偶。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-07 | P47 记录（L1）：详设反馈消费是 LLM 概率行为，缺确定性保证。记用户认知校正（issue 判据必须 LLM 可执行，不可判=产出端缺陷，否定机可判/语义二分；自检主体是 skill 内 LLM 非框架代码）。已展开 L3 `25-feedback-consumption-closure-analysis.md`：四步方案（step1 issue 迭代版本化地基 / step2 schema 补「消解判据」维度+产出端强制 / step3 loopback 写 prompt 降级为辅助=P45 第一刀现状已满足 / step4 生成 skill 末尾 LLM 自检全部 issue + halt 降级）。取舍：skill 内自检 > bug-fix agent（否决，过重）> 框架状态机（原(b)(c)落点，否决，框架膨胀）。**未实施**——用户指示先不动代码；待 L3 §7 待确认点拍板后立 L4。 |
| 2026-07-07 | P47 §7 四待确认点拍板（用户认可倾向）：①共享自检 skill+各 skill 调用 ②`acceptance` 自然语言 ③全量回验 ④halt 降级。L4 已立 `26-feedback-consumption-closure-impl.md`（5 步实施配方：step1 issue 迭代版本化 / step2 schema 补 `acceptance` 维度 / step3 loopback 降级保留 / step4 共享自检 skill+全量回验+halt 降级 / step5 日志+回归+收口；含填补 heavy_llm 反馈消费实证缺口——seed blocking issue → corrective 回退 → 断言产物真改）。**仍未实施**——用户指示先不动代码。 |
| 2026-07-07 | **P47 已修复（Step 1/2/4/5；Step 3=P45 第一刀现状满足不动）**，配方见 `26-feedback-consumption-closure-impl.md`。**Step1** issue 迭代版本化：`blocking_status`/`anchor_report` 的 issue 加 `iteration` 字段，transition 累积**全部历史轮**不覆盖；抽 `blocking_issues(state)` helper 按 `stage_iterations[name]` 过滤为**当前轮未消解**集——routing/`is_satisfied`/停滞签名语义不变（仅切到「当前轮」口径）。**Step2** 三 gate schema（validate/anchor-consistency/anchor-per-template）issue 加 `acceptance`（自然语言消解判据「怎样算此 issue 已解决」）+ `issue_required_keys:["acceptance"]` 加载期强制（§1.3）；`_parse_single` 增 `strict` 参数，validate/anchor-consistency gate 用 `strict=True` → 缺 `acceptance` 的 issue 被 `schema_violation` 拒收（不再被 lenient parse 静默收下）；三 gate SKILL.md 同步 acceptance 契约（「判据写不出 = issue 不成立」）。**Step4** 新共享 skill `ascendc-op-design-feedback-selfcheck`（读**全部历史轮** issue+本模板产物→逐条 `acceptance` **全量回验**防修新坏旧→未消解就地增量修、修不了如实标 unresolved）；三个 tiling 生成 skill（buffer-kernel/precision-perf/split）末尾 tail-call（工作目录有反馈报告时，§4.3 Skill 投递）；`_TilingSegmentStage._upstream_inputs` 物化 `validation_report`/`anchor_report` 到 tiling 工作目录供自检 skill 文件接力（§2.3，**全历史**而非只本轮 `_loopback_feedback`）；halt **复用既有 gate 停滞**（`error_signature` `same>=2`，skill unresolved → 下轮 gate 重报同指纹 → 停滞 halt → 转人工，§7④ 零新出口/状态机）。**Step5** `_lint_issues` 加本轮阻断摘要（`code#it{iteration}→target`，§1.2 可诊断性）。TDD 全程红→绿（`TestAcceptanceEnforcement` 3 + `TestFeedbackSelfcheckSkill` 3 + `TestTilingMaterializesGateReports` 2 + `TestLintIssuesIterationSummary` 2 + `TestIssueIterationAccumulation` 收口）；回归全量 UT **1623** + 非 heavy ST **1741** 全绿（6 heavy_llm deselected；4 NPU/cann-bench env-gated §3.7 诚实报错，非 §3.4 掩盖）。**heavy_llm e2e（§3.9 真实守护）未跑——待用户确认**（§3.11）：seed 带 acceptance 的 blocking issue（「AC1: bf16 骨架门不可行，`acceptance`=产物中不再出现 `bfloat16_t`」）→ Stage corrective 回退（触发 `_feedback_section`+skill 自检）→ 断言下一轮产物**真的不再用 bf16**（非只 schema 合法）。**heavy_llm e2e 已验证通过**——用例合并入 `test_design_tui_selfclosure.py::TestDesignFeedbackConsumption`（直 spawn tiling skill + seeded validation_report → 断言 selfcheck_report.json 产出 + bf16 真消解 or 如实 unresolved；§3.10 有界重试内至少一次；未新开 heavy 文件，复用同文件脚手架），3/3 heavy PASSED in 415.83s（真实 LLM 消费 seeded bf16 反馈成立，实证缺口闭合）。 |

---

## ✅ P48: resume 后 `State.from_snapshot` 只重建 `run_context`，其余嵌套 frozen dataclass 残留为 dict，首次属性访问即崩

### 事实

- **观测（崩点）**：run `20260707-091803-29a24f` 首跑在 integrate design substage 触 429（5h 用量上限）halt；resume 后到 codegen stage 崩：`Stage 'codegen' failed: 'dict' object has no attribute 'op_dir'`（`codegen.py:121` `working_dir = state.op_identity.op_dir`）。
- **凭证（snapshot 实证）**：`output/<run>/state_snapshot.json` 里 `op_identity`、`profile` 均为纯 dict（`{"spec":{...},"repo_root":"...","op_dir":"...",...}`），`op_dir`/`repo_root` 等已退化为 str。内存往返（`to_snapshot`→`from_snapshot`）不会暴露，真实 resume 经过 `json.dumps(default=str)` + `json.loads` 才两层全退化。
- **凭什么是缺陷（根因）**：`State.to_snapshot` 用 `dataclasses.asdict` **递归**展平所有嵌套 frozen dataclass 为 dict，JSON `default=str` 再把 `Path`→str；而 `State.from_snapshot`（state.py）只对 **`run_context` 一个字段**做了手写反重建（P27），`op_identity`/`op_spec`/`profile`/`build_result`/`precision_result`/`performance_result`/`deploy_result`/`eval_result`/`adapt_result`/`requirement`/`last_error` 全部遗漏——resume 后它们仍是 dict/str，凡对它们做属性访问的 stage 都崩。已确认的同类属性访问点：`cannbench_adapt.py`、`cannbench_eval.py`、`perf.py`、`finalize.py`、`integrate.py`、`requirement.py`、`gates.py`（`build_result.passed`/`precision_result.max_diff`）——即修好 codegen，deploy/eval/adapt 仍会连环崩。
- **本质**：P27 是「逐字段打补丁」式反序列化，只补了 run_context 一个特例；本条是「同类遗漏」的集中暴露。正解是把反重建收敛为通用机制（§1.2 可扩展：同类新情况自动正确归位，而非再补 op_identity 一个特例）。

### 关联

- 承接 P27（run_context 重建）：P27 是本条的同构前序——同一坑（asdict 展平 nested dataclass）只填了一个字段；P48 是该遗漏的集中爆发 + 通用化收口。
- 与 P46（halt 硬崩溃路径）不同域：P46 是「崩了没停」，P48 是「resume 后必崩」（首跑内存态不暴露，故一直潜伏到本次 429→resume 才触发）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-07 | P48 记录 + TDD 红→绿修复：`state.py` 新增通用反射重建 `_rebuild_dataclass`/`_rebuild_value`/`_strip_optional`（基于 `typing.get_type_hints` 遍历 `fields(State)`，按注解递归处理 `Optional`/`list`/`tuple`/`dict`/`Path`/嵌套 dataclass，容错：非预期 shape 原样返回不崩）；`from_snapshot` 用通用通路覆盖所有 dataclass 字段，删掉 run_context 手写特例（`run_context_from_dict` 作为 run_context 模块级 API 保留，独立测试仍守）。UT `test_state_snapshot_rebuild.py`（9 例，**经真实 JSON round-trip** 复现 `state.op_identity.op_dir` 属性访问崩 + 覆盖 op_identity/op_spec/profile/build_result/precision_result(per_case 嵌套 CasePrecision)/其它 verification 结果/last_error/run_context 收敛后仍工作/requirement 嵌套 list）红（精确复现 `'dict' object has no attribute 'op_dir'`）→绿。回归：全量 UT 1582 绿 / `test_run_context.py` 10 绿（收敛无回归）/ `test_resume_cli.py` 2 绿。**未覆盖 heavy_llm e2e**：P48 是 State 序列化边界纯逻辑，UT 经真实 JSON 往返已等价覆盖，非 §3.9 LLM 行为对象。 |

## ✅ P49: `models.default` 是死配置（`DEFAULT_MODEL` 零消费者）+ per-stage model 首次生效后指向网关无的频道致 codegen 503

### 事实

- **观测（崩点）**：P48 修复 resume 后再次 resume run `20260707-091803-29a24f`，codegen 首次成功 spawn，立即崩 `503 No available channel for model deepseek-v4-pro`，agent 卡死。
- **凭证（配置实证）**：`resources/orchestration-config.json` 中 `models.stages.codegen = "deepseek-v4-pro"` 是 **LIVE 配置**（`runner.py:528` 经 `stage_model()` 消费）；当前网关无该频道 → 503。
- **为什么"先前不生效、当前版本突然生效"**：P48 之前 codegen 从未成功 spawn（始终卡在 resume 崩溃链，最新一跳是 `op_dir` 属性崩），`stage_model("codegen")` 从未被调用到真正的 spawn；P48 修通 resume 反序列化后 codegen 首次抵达 spawn，`models.stages` 映射首次实际生效 → 暴露该配置指向的死频道。不是"配置突然生效"，是"先前根本没走到消费它的那一行"。
- **凭什么是缺陷（两处）**：
  - (a) **死配置 `models.default`**：`DEFAULT_MODEL` 零消费者——runner 的 model 解析链只有 `action.model > stage_map > SDK默认`，从不读全局 `default` 字段。它"曾让人误以为设了全局默认模型"，实则是僵尸配置（§1.4：不留死配置/过渡层）。
  - (b) **缺"用系统默认"的正向表达**：stage 想跟 SDK 默认走时只能靠"不配"，没有显式 token；用户需求是支持 `"default"` 明确表达"与系统设置一致"。本质是配置层语义不全 + 死配置并存。
- **澄清 model 配置维度**：model 按 **stage** 配（`models.stages.<stage>`），**不按 agent**——`.claude/agents/*.md` frontmatter 的 `model` 字段 runner 不读。

### 关联

- 承接 P48：P48 修通 codegen 到达 spawn，才让本配置首次生效、暴露 503。两条是同一 resume 链上的先后暴露。
- 更正记忆 `orchestration-default-model-deadconfig`：先前误记"stages.codegen 从不生效、全跑 GLM-5.2"——实因 codegen 从未 spawn 成功，故 `stage_model("codegen")` 从未真正执行；P48 修通后首次执行即暴露死频道。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-07 | P49 记录 + 修复：`model_config.py` 删死配置 `DEFAULT_MODEL`；新增 `DEFAULT_TOKEN="default"` + `stage_model()`（`absent/""/"default"` → `None` → spawn 传 `model=None` → SDK 默认 `.claude/settings.json`；具体 id 原样返回）；`runner.py:524-528` 改用 `stage_model()`；`orchestration-config.json` 删 `models.default`、`codegen` 设 `"default"`、`_comment` 说明 token 语义 + 删 default 原因(§1.4)。UT `test_model_config.py`（8 例，含 `test_shipped_codegen_uses_sdk_default` 503 回归守卫 + `test_no_dead_default_module_attr` 死配置不复生守卫）红→绿；`test_kernel.py` `TestSpawnAgentModelResolution` 更新（旧测依赖真实 codegen 值，改 monkeypatch 注入具体 id；新增 `test_default_token_in_map_yields_sdk_default`：`codegen="default"` → runner 传 `model=None` 而非字面 `"default"`）。回归：全量 UT 1591 绿。**非 §3.9 对象**：纯配置/字符串语义 + UT 等价覆盖，非 LLM 行为。 |

## ✅ P50: codegen 熔断器把 infra 错误误计为逻辑失败 + 熔断状态跨 resume 不复位（致 run 永久卡死）

### 事实

- **观测（死局）**：run `20260707-091803-29a24f` codegen 在 503「No available channel for model deepseek-v4-pro」下连烧 3 次迭代 → 熔断器跳闸（`codegen_consecutive_failures=3`）→ 计数器随 `state_snapshot.json` 持久化 → 后续 resume 在 `codegen.py` `actions()` 入口 0.0s 立即跳闸、**不 spawn agent**，run 永久卡死。同一 run 的 integrate 设计子阶段 429 也烧光 3 次迭代 halt（设计子阶段无 sticky 熔断器，resume 天然重跑已自愈）。
- **凭证（日志实证）**：`logs/e2e_self_evolve_20260707-091803-29a24f.log`——503×3 在 20:25 resume 段；21:23 resume 在 `actions()` 入口跳闸（0.0s、无 agent_spawn 行）；integrate 429×3 在 18:19–18:25。
- **503 性质澄清（用户定调）**：「No available channel」是 **distributor 无该模型上游频道**（本地/网关侧**配置缺口**），**非瞬时过载**——重试 1 次与 100 次同结果，重试无意义。
- **凭什么是缺陷（两层）**：
  - (a) **infra 错误被当逻辑失败计数**：`sdk_backend.py` `_TRANSIENT_ERROR_MARKERS` 只含 SSE「Content block not found」一项；503/429/401/403 既不重试、也无分类，落 `status="fatal"` → `codegen.py` transition 无差别 `codegen_consecutive_failures + 1`。熔断器不变式（*只数 coder 真修不动的逻辑失败*）被破坏。
  - (b) **熔断状态跨 resume 不复位**：`codegen_consecutive_failures` 是 State 字段、进快照；全仓唯一复位点在「成功生成时」，resume 入口不复位。后果：一次熔断后，哪怕网关已恢复、配置已修（P49 已把 codegen 改 `"default"`），该 run 的 codegen 仍因陈旧计数死锁——配置层修复穿透不了已被自身状态判死刑的 run。
- **本质**：(a) 是 backend 横切缺陷（同一 run 在 codegen 熔断 + integrate 迭代两处发作）；(b) 是 resume 把「临时 infra 故障」固化成「永久 halt」的可诊断性硬伤（§1.2 第三把尺子：resume 0.0s 内熔断、不 spawn，无法分辨「网关还死」/「coder 修不动」/「陈旧计数」）。

### 关联

- 承接 P49：P49 把 codegen 模型路由改 `"default"`（绕开死频道），但**修不到计数器已熔断的 in-flight run**——本 run 就是证据。模型层修复穿透不了状态层死锁，必须从状态层（本条 (b)）解。
- DEFERRAL（明确不做）：**设计子阶段（template-division/tiling/integrate/docgen/validate）的 stage 侧 infra 接线**。理由：无 sticky 熔断器、resume 天然重跑（本 run 19:04 resume 后 integrate 即成功，已实证），不会出现 codegen 那种永久卡死；backend 的 `error_type` 分类已就位（本条 (a)），将来给设计子阶段接线时信号免费可用，现逐个 substage 接线属扩大面、违反 avoid-overdesign。本次仅记录、不静默。
- 否决「infra 自动重试 / 退避」：用户定调配置错重试无意义；现状 backend 对非 transient 已不重试，保持。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-07 | P50 记录 + TDD 红→绿修复（方案见 `27-infra-error-classification-impl.md`）。(a) backend 分类：`backend.py` `AgentResult` 加 `error_type: str\|None`；`sdk_backend.py` 新增 `_INFRA_ERROR_MARKERS`（"No available channel"/"Usage limit reached"/"API Error: 401"/"API Error: 403"）+ `_classify_error_type()`，在 crashed 路径 fatal/partial 构造点设 `error_type`（**不**入 `_TRANSIENT_ERROR_MARKERS`、**不**加 backoff）。(a) codegen 接线：`codegen.py` transition 失败尾按 `error_type=="infra"` 分支——不递增 `codegen_consecutive_failures`、`last_error` 带 infra 原因（C）；`actions()` 熔断检查后加 infra 守卫——infra `last_error` → 记 error 日志 + `return []` halt（同熔断模式但不动计数器）。(b) resume 复位：`dispatcher.py` 抽纯函数 `_resume_breaker_reset(state)→dict`（`codegen_consecutive_failures=0` + 清 infra 类型 `last_error`，否则 infra 守卫会在 resume 首次 `actions()` 拦下、抵消复位），在 resume 分支 `with_updates` 展开。UT：`test_capabilities.py` +`TestInfraErrorClassification`(6)+`TestAgentResult` error_type(2)；`test_stages.py` `TestCodegenStage` +infra 不计数/actions halt/logic 仍 spawn(3)；`test_dispatcher_resume_bridge.py` +`TestResumeBreakerReset`(3) 红→绿；**salvage 接线锚**（用户追问"是否需新增 ST"时自查发现的盲点闭合）：原 UT 直接在 stub 上手设 `error_type`/直接调 `_classify_error_type()`，绕过 sdk_backend 真实 crash-salvage 构造点（820/831），删掉那两行接线原测试会全绿——补 `test_query_crash_infra_marker_classified_through_salvage`（经真实 `_spawn`，infra marker→`error_type=="infra"`）+ 既有两 crash UT 加 `error_type is None` 反例。回归：全量 UT **1606** 绿（+15）。**非 §3.9 对象**：纯逻辑/分类/字符串语义，UT 等价覆盖，非 LLM 行为；"真实 503 ST" 在 CI 无法确定性触发（§3.10），mock 出的 503 即 UT（§3.5），故不新增 ST。 |

---

## ✅ P51: `fail_strategy=continue` 的 stage 硬崩溃后照常推进下游——验证型崩溃吞信号、下游吃无意义 loss（P46 的 continue 侧对偶）

### 事实

- **观测**：run `20260707-091803-29a24f` resume 段，verify 硬崩溃 `AttributeError: 'dict' object has no attribute 'inputs'`（test_cases 反序列化失败，根因属 P48 类——`State.from_snapshot` 把 `list[TestCase]` 重建回原始 dict、verify 读 `tc.inputs` 崩，已**单独修复**：`state.py` 把 `test_cases` 字段类型从裸 `list` 改 `list[TestCase] | None`，让通用重建器能重建元素）。但 verify **崩溃本身**没有让 workflow 停——崩溃后继续跑了 cannbench_adapt（503 partial）→ cannbench_eval（Evaluator 崩、score=0）→ finalize。
- **崩溃根因 vs 控制流问题是两件事**：上面那条 test_cases 反序列化 bug 已修（P48 类）。**P51 要记录的是另一件事**——verify 是 `fail_strategy=continue` 的 stage，它**无论出于什么原因**崩溃，workflow 都不会停、也不会回 codegen，而是照常线性推进到依赖它产物的下游。把那个具体 bug 修了，不等于这个控制流问题消失（下次 verify 因别的原因崩，行为一致）。
- **机制（continue stage 的两条失败路径，软失败有路由、硬崩溃没有）**：
  1. **软失败**（`PrecisionGate.evaluate` 返回 `passed=False`，stage 正常返回）→ 走 `transition` → `resolve_condition` → `TRANSITION_TABLE` 路由（verify 的 build_failed/precision_failed → codegen loopback）。这正是 e2e-stability/02-analysis.md 分配表给 verify=continue 的理由（"由 TRANSITION_TABLE 路由"）。
  2. **硬崩溃**（`actions()`/`transition()` 抛异常，`PrecisionGate.evaluate` 在非 stub 模式 re-raise 也走这条路）→ `run_stage` except 直接 `raise`（绕过 `transition`/`resolve_condition`）→ `_execute_atomic` 的 `except Exception` 分支只 `mark node "failed"`、对 continue stage **不设** `_stage_failed`（P46 只让 halt stage 的崩溃设 `_stage_failed`）→ `_execute_sequential` 读不到信号 → 不 `break` → 继续遍历下游。
- **凭什么是问题**：e2e-stability/02-analysis.md 分配表把 verify 归 `continue` 的理由（"由 TRANSITION_TABLE 路由"）**只覆盖软失败路径**（gate 判定不合格 → 回 codegen 修），**不覆盖硬崩溃路径**（异常把 `transition`/`resolve_condition` 短路了，loopback 根本不触发）。而 verify 是精度门、cannbench_eval 的评测对象就是 verify 验过的 kernel——verify 一崩，eval 的 score（本 run 的 0 分来自 Evaluator 崩、不是真评测）就是无意义 loss，污染进化信号。这是「continue 韧性」与「下游依赖该 stage 成功」之间的设计张力，当前架构没有区分「可继续的 continue（下游不依赖）」与「该阻断的 continue（下游强依赖）」。

### 关联

- **P46 的 continue 侧对偶**：P46（已修）堵的是 **halt 侧**硬崩溃洞——halt stage 崩了不设 `_stage_failed`、不停；P46 让 halt stage 的崩溃也设 `_stage_failed` 停住。P51 是 **continue 侧**那个**还没堵、且是否该堵本身待定**的洞——continue stage 崩了照样推进。两者合起来才是"`fail_strategy` 声明对所有失败形态的完整语义"这一命题的全集：P46 闭环了 halt 全形态，P51 还在问 continue 全形态该不该、以及在哪个边界干预。
- **质疑 e2e-stability/02-analysis.md 分配表**：分配表 line「验证型 | verify, perf | continue | 由 TRANSITION_TABLE 路由」的判据只论证了软失败（gate 不合格回 codegen），没论证硬崩溃。P51 不一定推翻 verify=continue 这个结论（continue 的韧性价值成立），但要求分配表的判据补上「硬崩溃时下游如何被保护」这一维度——是给判据打补丁，还是给 verify 换 halt，还是给异常路径加路由，是 L3 要讨论的（见 `28-verify-continue-crash-analysis.md`）。
- **边界——P51 不是什么**：(1) 不是 P48/test_cases 反序列化那个具体 bug（已单独修复）。(2) 不是 P46（P46 是 halt 侧已闭环；P51 是 continue 侧待定）。(3) 不是「verify 该不该 continue」的简单翻案——continue 在软失败域有明确价值（loopback），P51 只问硬崩溃域。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-08 | P51 记录（仅事实，无方案）。源于 run `20260707-091803-29a24f` resume 后 verify 崩而 workflow 不停的现象追问。控制流问题与 test_cases 反序列化根因（P48 类、已修）分离记录。方案待 L3 讨论（`28-verify-continue-crash-analysis.md`，调研中未拍板），L2 新增 step 26 跟踪。 |
| 2026-07-08 | L3 冻结（`28-*.md`）：选项 E（失败根因分类驱动路由）。灰区默认值用户拍板 = **loopback**（保修复机会优先）+ 最终 halt+落盘交人；用户校正 segfault/精度错属可修类（非灰区）。止损静态核对纠正前版误述：verify-loopback 止损是 `verify_iterations→exhausted→__halt__`，**非** codegen breaker。立 L4（`30-*.md`）：二元分类器（非可修→halt；其余→loopback，灰区折叠进其余）+ 新 `Stage.on_uncaught_failure` hook（默认 no-op，verify override 自增 verify_iterations）+ 复用既有 `exhausted→__halt__` 止损。 |
| 2026-07-08 | L4 实施（`30-*.md`）完成。`_execute_atomic` except 分支：`_classify_uncaught`（复用 P50 infra marker + `_FRAMEWORK_STATE_MARKERS`）→ 非可修（infra/framework）设 `_stage_failed` halt（镜像 P46）；其余调 `node.stage.on_uncaught_failure`（base no-op，verify override 自增 `verify_iterations` + crash-failed `build_result`）让既有 `build_failed/exhausted→__halt__` 路由+止损接管。halt stage 保留 P46 无条件 halt。TDD 11 用例红→绿；UT **1653** + 非 llm ST **116** 全绿（0 回归，含 P51 crash-routing slow ST `TestP51VerifyCrashRouting` 2 例：真实 dispatch + 故障注入，断言下游不跑）；16 heavy_llm 按 §3.11 未默认跑（确定性控制流，非 §3.9 LLM 对象）。 |

---

## ✅ P52（已完成）: resume 不作废 failed 上游的下游 completed——node_status 缺因果有效性，resume 信任 stale「completed」

### 事实

- **需求（用户提出）**：某 stage failed 或未 completed，resume 须从该 stage 开始重跑，且其**后续已 completed 的步骤视作无效、一并重跑**——即使它们 node_status 是 "completed"。
- **现状（一半已 work，一半是 gap）**：
  - ✅ failed stage 重跑已 work：`graph_executor._execute_node` 的 resume skip 判据是 `node_status.get(path) == "completed"`，"failed" ≠ "completed" → 不 skip → 重跑。所以「从 failed stage 开始重跑」对 failed stage 本身已经成立。
  - ❌ 后续 "completed" 不被作废：resume 权威构建器 `_resume_node_status`（`dispatcher`）当前是 **passthrough**（`return dict(state.node_status)`），不做任何作废。于是 failed stage 之后那些 "completed" 的下游节点，resume 时被 `== "completed"` 判据跳过——带着 stale 结果。
- **凭证（实证）**：run `20260707-091803-29a24f`——verify node_status="failed"（P51 crash-advance 场景：verify 崩后 workflow 照跑下游），cannbench_adapt/cannbench_eval/finalize 在 verify 的坏态上跑出来、标 "completed"（eval score=0 来自 Evaluator 崩、非真评测）。resume 重跑 verify（✓），但 adapt/eval/finalize 因 "completed" 被跳过（✗）——stale score=0 被保留。
- **机制（node_status 是逐节点独立语义，无因果链）**：当前 node_status 只记「这个节点跑没跑完」，不记「它跑完所依赖的上游是否仍然有效」。一个 "completed" 节点可能建立在 failed 上游的坏输出上（P51 crash-advance 让下游在 verify 坏态上跑完）。resume 信任这种 "completed" → 用 stale 结果，污染进化信号。
- **凭什么是问题**：resume 的语义应该是「从首个未有效完成的节点起，重建有效完成前沿」，而当前是「跳过所有 ever-completed 的节点」。两者在「failed 上游 + completed 下游」时分歧——而该分歧直接导致 stale 结果被信任。

### 关联

- **可行性与修法（结论：可行；按 §1.2 整体合理性定案，非最小修先行）**：在 node_status 上加**因果有效性不变式（clean-prefix）**——一个 "completed" 节点仅当其同 scope（同一 SequentialGroup）内所有前序兄弟也 "completed" 才有效；scope 内首个 failed/缺失节点之后的所有 "completed" 视作无效、清除。**关键认知校正（推翻前述「复用 loopback 清除」的措辞）**：loopback 运行期清除下游 `[target_idx, i]`（`_execute_sequential` 路由回退时）和 resume 期作废下游 completed，**不是两套逻辑，而是同一不变式（clean-prefix 因果有效性）的两个触发点**。loopback 的 `[target,i]` 清除是该不变式的**残缺实例**（只覆盖 loopback 触发点、靠运行期路由才触发）；resume 场景缺这个触发点就漏掉。**正确落法**：抽**一个 primitive** `invalidate_completed_from(scope, start_idx)` 承载 clean-prefix 不变式，在 resume 入口（`_resume_node_status`）和 loopback（`_execute_sequential`）**两处都调用、替换 loopback 原本的 `[target,i]` ad-hoc 清除**，而非「resume 处新写一套、loopback 保留旧实现」。这符合 §1.2（同类新情况自动正确归位，非每次打补丁）+ §2.5（唯一通路不留旧债：消除「同一概念两套实现」的债）。fork-join 独立分支互不作废（A 分支 failed 不作废已 completed 的 B 分支）由同一 primitive 在 scope 边界自然承载。
- **与 P51 互补（正交）**：P51（选项 E）从**源头**避免「downstream completed on stale」产生——不可修类 halt → 下游根本不跑 → 不会出现 stale completed。P52 是**防御性不变式**，无论状态怎么进入「failed 上游 + completed 下游」（P51 漏网的 crash、未来同类 bug、手工改状态、soft-failure 边角），resume 都兜住。E 决定 verify 自己 halt 还是 loopback；P52 决定 verify 失败后下游 completed 是否作废。两者正交，分开落、互引用。
- **承接 P29/step-16（resume 逐节点 flush snapshot）+ P35（halt 的 node_status 标 failed）**：P29 让 node_status 成为 resume sole authority，P35 让 halt leaf 标 failed 传播到根。P52 给 node_status 补「因果有效性」这第三层语义——前两层管「记没记对」，P52 管「记的 completed 还信不信得过」。
- **边界——P52 不是什么**：(1) 不是 P51（P51 是 fail_strategy 路由；P52 是 node_status 因果有效性）。(2) **已校正**：原述「不是 loopback clearing，二者是不同机制」是**错的**——loopback 运行期清除与 resume 期作废是**同一不变式（clean-prefix）的两个触发点**，正确定法是统一为一个 primitive 在两处调用（见上「可行性与修法」），而非分立两套。(3) 不是「重跑整个 run」（只作废 failed 上游之后的下游，前序有效 completed 保留）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-08 | P52 记录（仅事实 + 可行性结论，无实施方案）。源于用户追问「failed/未 completed 的 stage，resume 是否能从该 stage 重跑且作废后续 completed」。可行性结论：可行——`_resume_node_status` 加 clean-prefix 因果有效性不变式，复用 loopback 下游清除机制。与 P51 正交互补。方案待 L3 讨论，L2 新增 step 27 跟踪。 |
| 2026-07-08 | **认知校正（按 §1.2 整体合理性，非最小修先行）**：用户纠正「永远以整体合理性为第一位，不是修改最小优先」。据此推翻前述「复用 loopback 清除」的措辞——loopback 运行期清除 `[target,i]` 与 resume 期作废是**同一 clean-prefix 不变式的两个触发点**，loopback 的清除是该不变式的**残缺实例**。定案：抽一个 primitive `invalidate_completed_from` 在 resume 入口与 loopback 两处调用，**替换** loopback 原 ad-hoc 清除（非保留两套），符合 §1.2 + §2.5。相应更正「边界」中「P52 与 loopback clearing 是不同机制」的错误表述。L2 step 27 状态更新为「与 loopback 清除同源，统一为一个 primitive」。 |
| 2026-07-08 | **实施完成（L4 `29-resume-causal-validity-impl.md`）**。primitive 命名经代码精读细化为两层（L1 关联所述 `invalidate_completed_from` 落地为）：底层 `_invalidate_subtree`（作废单节点+子树，含 rerun_selector 分支限定，提取自 loopback 原 ad-hoc 循环体——两端真正共用的复用单元）；中层 `_invalidate_sequential_range`（loopback 专用，范围 pop + rerun_selector 解析）。落点：① loopback（`GraphExecutor._execute_sequential`）改用 `_invalidate_sequential_range` 替换 ad-hoc 清除，行为等价；② resume（`_resume_node_status`）重写为遍历 workflow 树——每个 SequentialGroup scope 找首个非 completed（first_bad），作废其后 stale completed（first_bad 自身保留诊断标记），递归所有 children 处理嵌套 scope；ForkJoinGroup 分支并行独立不作 clean-prefix 但递归进分支。边界落地：ForkJoin 分支独立、forkjoin=failed 打破父 SequentialGroup 前缀、嵌套 scope 独立 clean-prefix。TDD 8 用例红→绿（含端到端 execute 驱动）；UT **1642** + 非 llm ST **114** 全绿（0 回归）；16 heavy_llm 按 §3.11 未默认跑（P52 纯逻辑非 §3.9 LLM 对象，UT 已充分覆盖）。更新既有 `test_node_status_passthrough_unchanged`：其 ns 构造的正是 P52 要修正的 stale 场景（detailed-design/dd-intake 缺失但后续 substages completed），verbatim passthrough 断言已过时，改为验证 sole authority + 不注入 phantom。 |

---

## P53: 精度失败反馈链路三连断裂——phantom max_diff + loopback 无原因 + codegen 无消费自检

### 事实

- **观测**：run `20260707-091803-29a24f` 中 verify `precision_failed`（max_diff 超阈值）loopback 回 codegen，但反馈链路**三处断裂**，codegen 拿到的是失真信号：
  1. **phantom max_diff=0.0**：`VerifyStage.transition` 读 `gate_result.get("max_diff")`（**顶层**），但 max_diff 实际在 `gate_result["metrics"]`（由 `NPURunner.execute` 组装、`PrecisionGate.evaluate` 放进 `GateResult.metrics`）。同函数内 `precision_metrics.get("stubbed")` 却**正确**地从 `metrics` 读——同一函数两种读法、行为不一致。结果 `PrecisionResult.max_diff` 恒 0.0，`CodegenStage._build_codegen_prompt` 的精度反馈段拿到 phantom 0.0，`VerifyStage.error_signature` 恒输出 `precision:max_diff=0.000000`。
  2. **loopback 日志无失败原因**：`VerifyStage` 不 override `blocking_issues()`（base 默认 `[]`），`GraphExecutor._log_loopback` 经 `_summarize_issues`/`renderIssues` 渲染时无 issue 可打 → loopback 行只显 `loopback verify → codegen (corrective 1/5)`，不显"精度不达标 max_diff=?"（spawn_context prompt 里有，但日志行无）。
  3. **codegen 无反馈消费自检**：P47 给**设计侧**三 tiling 生成 skill 加了 `ascendc-op-design-feedback-selfcheck`（读全部历史轮 issue 的 `acceptance` 逐条全量回验、修不了如实标 unresolved、复用既有停滞 halt）。**codegen 侧无等价物**——精度反馈进了 prompt，但"是否被 codegen 真消费"是 LLM 概率行为、无确定性保证（P45 第一刀+(a) 修的是设计侧 loopback，codegen 侧未同步）。

- **根因**：精度失败→codegen 的反馈链路三处断裂（字段读取错位 / 日志可见性缺 override / 消费确认缺 skill）。P45/P47 闭环了**设计侧**的反馈消费，**codegen 侧**未同步——同一类缺口在 codegen 边界重现。

- **证据（语义锚点）**：
  - `VerifyStage.transition`：max_diff 读顶层（`gate_result.get("max_diff")`）vs stubbed 读 metrics（`precision_metrics.get("stubbed")`）——同函数两读法。
  - `PrecisionGate.evaluate`：`GateResult.metrics={"max_diff":..., "actual_ms":..., "stubbed":...}`——max_diff 确在 metrics。
  - `NPURunner.execute`：返回 dict 的 `gate_result.metrics` 承载 max_diff（runner 组装层确认）。
  - `CodegenStage._build_codegen_prompt`：`md = getattr(state.precision_result, "max_diff", 0.0)` → 拿到 phantom 0.0。
  - `VerifyStage.error_signature`：`f"precision:max_diff={state.precision_result.max_diff:.6f}"` → 恒 0.000000 → 停滞检测 `same>=2` 误判（每次 sig 都同），但实际每轮可能不同 case 失败。
  - `VerifyStage` 无 `blocking_issues` override（base `Stage.blocking_issues` 默认 `[]`）。

- **影响**：精度失败 loopback 给 codegen 的反馈是**错的（0.0）+ 无原因 + 无消费保证** → codegen 空转（与 P41「同 stage 内迭代不把失败原因传给下一次 prompt」同病，本条是其 stage 间 loopback 变体）。即便 codegen 改了代码，因 sig 恒定，停滞检测无法区分"真停滞"与"不同 case 的合理重试"。

### 关联

- **P6**（精度 CPU 桩，已修）：P6 是"精度根本没跑真 kernel"（max_diff 恒 0 因没比对）；本条是"跑了真 kernel、真实 max_diff 非零，但传回 codegen 时因字段读取错位变 0.0"——**传递层 bug，非精度层**。P6 修了精度真值，P53 是真值传不回 codegen。
- **P25**（迭代行无失败原因）：P25 是 stage 内迭代行无 issue detail；本条是 **loopback 行**无 issue detail（`_log_loopback` 路径，非迭代行）。同主题（可观测性）不同触发点。
- **P41**（同 stage 内迭代丢原因，降级待观察）：本条是其 stage 间 loopback 变体。
- **P45/P47**（设计侧反馈消费闭环）：P45 第一刀+(a) + P47 skill 内自检闭环了设计侧；codegen 侧缺口是本条第 3 点。
- **P54**（重设计）：本条三连断裂是"精度失败回 codegen"这条路径的具体缺陷；P54 重设计绕开此路径（精度失败→独立调试 stage，不回 codegen），P53 的 phantom bug 作为遗留仍需修（debug stage 内部精度反馈也要读对字段）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-09 | P53 记录：精度失败反馈链路三连断裂（phantom max_diff 字段读取错位 + loopback 无 blocking_issues override + codegen 无反馈消费自检 skill）。源于 run `20260707-091803-29a24f` 诊断。P54 重设计绕开此路径，但 phantom bug 仍需修。方案见 `31-precision-debug-stage-analysis.md`（L3）。 |
| 2026-07-09 | P53 实施完成（L4 `31-precision-debug-stage-impl.md` §2.1/§7.6）：**第 1 点 phantom max_diff 已修**——`VerifyStage.transition` 改从 `gate_result["metrics"]` 读 `max_diff`（与 `stubbed` 同源），`PrecisionResult` 扩 `per_case`/`bottleneck`，`PrecisionGate.evaluate` metrics 含 `bottleneck`；UT 用例 1-2 守护。**第 2、3 点被 P54 绕开不修**（精度失败不再回 codegen，改走 `precision_debug` stage；按 L4 §6，修了是死代码）。 |

---

## P54: 精度失败后无 in-stage 调试闭环——loopback 回 codegen 上下文损失、debug workflow 不可复用

### 事实

- **需求（用户提出）**：精度失败后**不回 codegen**，在独立 stage 内闭环调试——agent 内部迭代（改代码 → git commit → redeploy → 跑用例 → 看 dumptensor 日志 → 再改），直到轮数耗尽或问题全部解决。复用 deploy 能力（反复安装验证）。

- **现状问题（三，用户论证）**：
  1. **loopback 上下文损失**：codegen 拿不到完整 debug 信息。即使修了 P53（phantom max_diff），per-case diff / bottleneck / dumptensor 中间值经日志/prompt 传递也不完整——精度调试需要"哪个 case、哪个元素、差多少、为什么"的全链信息，loopback 的 prompt 注入承载不了。
  2. **频繁启 agent 耗时**：每轮 loopback 重启 codegen agent，丢失上文、重新建会话，比同 agent 内部迭代慢。
  3. **debug workflow 不可复用**：未来"别人对算子代码提精度 issue"场景——只有代码仓 + 算子代码 + 可复现用例（+ golden），**没有 codegen stage**。若精度调试绑死在 codegen loopback 里，这个独立解 issue 场景无法复用。

- **目标态**：
  - 新增**精度调试 stage**（`PrecisionDebugStage`），verify `precision_failed` → 该 stage（不再 → codegen）。
  - agent 内部迭代闭环：改代码 → git commit（带修改说明，追踪历史防震荡不收敛）→ redeploy（build+install+smoke）→ 跑用例（全部或部分，按场景）→ 看 dumptensor+print 日志（落文件，防上下文压缩丢失）→ 按失败用例优先级排修复 → 再改。轮数耗尽或全部解决为止。
  - **复用 deploy 能力**：debug stage 内反复 redeploy，per-op 覆盖式安装（新 .so 即时生效）。
  - **debug skill 输入契约 = code + cases + golden**（不依赖 codegen/design 产物）→ debug workflow（独立解 issue）可直接复用该 stage。
  - **编译失败 in-stage 闭环**：agent 改代码引入的编译错，redeploy 的 build 步骤失败 → stderr 给 agent → agent 在 debug stage 内自修（不回 codegen，因代码是 debug stage 改的、codegen 无调试上下文）。轮数耗尽 → 回退最佳 commit + 转人工。

- **凭什么这是合理方向**：
  - 与 design 侧 P47 一致（in-stage 闭环 + 反馈消费确定性）：精度调试同属 inference-time 单算子自我修正（self-evolution-design.md §2.2 (a)），应在 stage 内闭环，而非跨 stage loopback 损失上下文。
  - debug workflow 复用：输入契约 = code+cases+golden 是"解精度 issue"的最小输入集，与 codegen 无关——这正是未来独立解 issue 场景的输入。

### 关联

- **P53**（反馈链路三连断裂）：是"精度失败回 codegen"路径的具体缺陷；本条重设计**绕开**该路径。P53 的 phantom bug 作为遗留仍需修（debug stage 内部精度反馈同样要读对字段）。
- **P45/P47**（设计侧 in-stage 闭环 + 反馈消费自检）：本条沿用同一思路（stage 内闭环 + 确定性消费），落到精度调试边界。
- **CLAUDE.md §2.5**（唯一通路不留旧债）：debug stage 复用 deploy 能力——抽 Deployer 服务单一来源，DeployStage + debug stage 共用，不重写 deploy 链。
- **CLAUDE.md §2.7**（核心引导归 skill、脚手架外移）：确定性 build/install/smoke/跑用例封装成 CLI 命令（脚手架），LLM 只负责改代码+读日志+推理根因（核心）；精度调试 skill 承载 dumptensor 定位根因 + 用例优先级 + 修复策略的引导。
- **CLAUDE.md §1.2**（四把尺子）：可维护（deploy 单一来源）/ 可扩展（debug workflow 复用）/ 可诊断（dumptensor 落盘）/ 架构合理（调试职责落在独立 stage，不越层兜底）。
- **self-evolution-design.md §2.2**（两层迭代）：本条属 (a) inference-time 单算子自我修正，独立于 (b) training-time loss 迭代。
- **边界——codegen 编译保证**：进入 debug stage 前代码必可编译，由 `VerifyStage` 的 `BuildInRepoGate` 兜（build_failed → codegen 不变）；codegen 不新增编译门。debug stage 内编译失败是 agent 自己改坏的，in-stage 自修。
- 方案分析见 `31-precision-debug-stage-analysis.md`（L3）；实施见 `31-precision-debug-stage-impl.md`（L4）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-09 | P54 记录（需求 + 目标态）：精度失败后无 in-stage 调试闭环，loopback 回 codegen 上下文损失 + 频繁启 agent 耗时 + debug workflow 不可复用。目标=独立精度调试 stage（agent 内迭代：改码→commit→redeploy→跑用例→dumptensor 日志→再改），复用 deploy 能力，skill 输入=code+cases+golden。方案见 `31`（L3/L4）。 |
| 2026-07-09 | P54 实施完成（L4 `31-precision-debug-stage-impl.md`，**UT 1700 + 非 heavy ST 全绿**）：`PrecisionDebugStage`（`fail_strategy=halt` + agent 内闭环 5 轮，**不** stage loopback）+ `ascendc-precision-debugger` agent + `ascendc-precision-debug` skill（§2.1 即插即用）+ CLI `redeploy`/`run-cases`（L1 薄壳 → L2 `DebugService` → L3 `Deployer`/`run_precision_cases`，§1.1 分层 + §2.5 单一 runner 装配路径）+ 抽 `Deployer`（DeployStage/precision_debug 共用）。as-built 冻结决策见 L4 §7。**heavy_llm 真实 self-evolve e2e 按 §3.11 未默认跑**（特性交付/PR 合并前由用户决策跑一次，§3.9）。 |

---

## P55: 单 stage 调试入口对 in-stage 闭环 stage（precision_debug）不可用——workspace 新建 + _workspace 未注入

### 事实

- **现象**：`ascendc-devkit stage run -n precision_debug --from-run <run_id>` 单跑必崩，无法独立调试 precision_debug stage（前置流程 codegen→deploy→verify 太长，反复全跑浪费大量时间/token）。

- **根因 A（workspace 新建，不复用原 run）**：`dispatch_single_stage` 的 workspace 构造无条件 `Workspace.create` 新建 run 目录，不复用 `--from-run` 的原 run → agent 拿到空 workspace，丢失原 run 已 deploy 的算子环境与真实 `state_snapshot.json`。

- **根因 B（_workspace 未注入 state）**：workspace 构造后只 `with_updates(run_id=...)`，不注入 `_workspace`。多个 stage 经 `state._workspace` 取 run 目录（`PrecisionDebugStage._build_prompt` 取 run 目录写进 prompt 给 agent 调 `redeploy`/`run-cases --workspace`；`RequirementStage` / `ContextStage` 同样用），取到 `None` → prompt 写死字面量 `<run_dir>` → agent 调 CLI 立刻 `Path` 校验失败。

- **凭什么这么说**：
  - `grep 'getattr(state, "_workspace")'` 命中 `precision_debug.py` / `requirement.py` / `context.py` —— `_workspace` 是 stage 取 run 目录的不变式依赖。
  - 主 `dispatch` 的 resume 分支正确范式 = `Workspace.from_existing(run_id)` + `state.with_updates(_workspace=workspace)`（P40/P31 同模式：workspace 是 transient，`to`/`from_snapshot` 都 pop，resume/单 stage 须挂回）；单 stage 路径与之分叉——同一职责（从某 run 恢复跑 stage）却两套 workspace 构造范式。

### 关联

- **P54**：本条是 P54 `PrecisionDebugStage` 的配套——stage 本身正确，但单 stage 调试入口对它（及所有依赖 `state._workspace` 的 stage）不可用。
- **P40/P31**：`_workspace` transient 须挂回的不变式（主 resume 已修，单 stage 路径漏修）。
- **CLAUDE.md §2.5**（唯一通路）：复用既有 `dispatch_single_stage` 修复，不新开单 stage 跑 precision_debug 的旁路。
- **CLAUDE.md §1.2**（四把尺子）：可维护（消除 workspace 构造两范式分叉）/ 可扩展（任何依赖 `_workspace` 或复用原 run 的 stage 自动受益，含未来 in-stage 闭环 stage）/ 可诊断（`from_existing` 在 run 不存在时前置报错 EX_USAGE，不 warn+empty 掩盖成下游「缺字段」）/ 架构合理（修复落在 dispatcher L2，不越层在 stage 内 fallback 打补丁）。
- **取舍（events 写入位置）**：单 stage 重跑把 stage 事件追加进**原 run 的 `events.jsonl`**（runner 持有 `from_existing` 的 workspace）——事件流连续、调试连贯（符合 Event Sourcing 单一权威）；不隔离到新 run（隔离须重建 deploy 环境，违背「省时省 token」初衷）。用户拍板采纳。
- 方案实施见 `32-single-stage-debug-entry-impl.md`（L4）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-09 | P55 记录 + 实施完成（L4 `32-single-stage-debug-entry-impl.md`）：`dispatch_single_stage` 的 workspace 构造提前到 `_build_state_for_stage` 之前；`--from-run` 时 `Workspace.from_existing` 复用原 run（自带存在性校验，不存在 → EX_USAGE 友好报错，且早于 `_load_state_from_run` 不触发误导性 warn），否则 `Workspace.create`；**两条路径都注入 `_workspace`**（修复所有依赖 `state._workspace` 的 stage 单跑，非仅 precision_debug）。对齐主 dispatch resume 分支范式（§2.5）。UT 新增 3（from-run 复用 + `_workspace` 注入 / from-run 不存在 → EX_USAGE / 无 from-run 也注入 `_workspace`）+ 全量 `test_application.py` 63 绿 + precision_debug 相关 38 绿，0 回归（主 resume 路径 `TestDispatcherResume` 全绿）。 |
| 2026-07-09 | P55 延续：precision_debug 的 agent 内循环轮数（`max_rounds`）接入 `--max-iterations`——抽 `_max_rounds(state)` helper（优先级 `user_max_iterations` > config > default 5），`actions` + `transition` 共用。precision_debug 不 loopback（halt），`--max-iterations` 作 stage 自循环上限对它无意义（恒 1 次），借用为 agent 内循环轮数（防轮数不足无法收敛），并兑现 config `_comment`「CLI wins over these」对 precision_debug 的意图。UT +2（`user_max_iterations` 覆盖 + transition 一致性），precision_debug 16 绿。引入 trade-off P56（`--max-iterations` 语义随 stage 分裂，低优先级待分析）。 |

---

## P56: `--max-iterations` 语义随 stage 分裂——precision_debug 借用为 agent 内循环轮数（低优先级，待分析）

### 事实

- **现状**：`--max-iterations`（→ `state.user_max_iterations`）本义是 **runner 的 stage 自循环上限**（loopback 次数，`runner.py` `iteration_ceiling`）。P55 延续工作中，precision_debug 把它**借用**为 agent 内循环轮数（`_max_rounds`：`user_max_iterations` > config > default），因 precision_debug 不 loopback（halt），该参数作 stage 循环对它无意义（恒 1 次）。

- **语义分裂**：同一个 `--max-iterations`，对 verify/perf = stage loopback 次数，对 precision_debug = agent 单会话内循环轮数。两者维度不同（stage 重启 vs 单次 agent 内迭代）。

- **更深的张力（非本条范围，仅记录）**：`orchestration-config.json` 的 `_comment` 声称「CLI --max-iterations wins over these（iterations.stages）」，但 `effective_max_iterations()` 只读 config/default、**不读** `user_max_iterations`——只有 runner 的 loopback ceiling 兑现了「CLI wins」，stage 内部决策点（verify `exhausted` / perf redesign 等）用的预算没兑现。precision_debug 因借用 `effective_max_iterations` 才把 CLI 接进了 agent 内循环。

### 凭什么这是 trade-off 而非缺陷

- precision_debug 不 loopback，`--max-iterations` 作 stage 循环对它本就无效（恒 1 次）；借用为 agent 内循环是「无意义参数变有意义」，**无功能冲突**，且 per-run 可调（防 agent 内循环轮数不足无法收敛）。
- 用户直觉（`--max-iterations N` → precision_debug 改 N 轮）符合预期。

### 关联

- **P55**：本 trade-off 由 P55 延续工作（让 `--max-iterations` 接进 precision_debug 的 agent 内循环）引入/显性化。
- **`effective_max_iterations` 语义缺口**（config `_comment` 与实现不一致）：若后续统一（让 `effective_max_iterations` 读 `user_max_iterations`），本条借用可自然消解为统一语义；但会影响所有 stage（verify/perf 等），需独立 L3。

### 待分析方向（低优先级，后续 L3 展开）

1. **维持借用**（现状）：precision_debug 特例借用，文档/help 说明语义。成本最低。
2. **独立参数 `--max-rounds`**：语义绝对清晰（专控 agent 内循环），但新增 CLI + state 字段 + dispatcher 透传，成本高。
3. **统一 `effective_max_iterations` 读 `user_max_iterations`**：根治 config `_comment` 与实现不一致，但影响所有 stage，需评估 verify/perf 等行为变化。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-09 | P56 记录（仅事实 + 待分析方向，低优先级）：`--max-iterations` 语义随 stage 分裂——precision_debug 借用为 agent 内循环轮数。由 P55 延续工作引入。方案待后续 L3 展开。 |

---

## ✅ P57: deploy build 失败后无 loopback 回 codegen + 无具体错误提示（fail_strategy=halt 抢占路由 + stderr 截断）

### 事实

run `20260709-094500-b3a241`（他人机器跑 self_evolve_op，profile cann-bench），deploy stage 的 build 步骤失败后呈现两件事：

- **现象 A（无 loopback）**：build 失败后 pipeline 直接 `Workflow halted`，**未 loopback 回 codegen 改代码**。
- **现象 B（无具体错误）**：控制台只打泛化串「deploy step 'build' failed」，看不到具体哪个算子哪一行编译错；run 产物里也找不到完整编译输出。

### 凭证（A — 无 loopback）

- 日志末段（`logs/e2e_self_evolve_20260709-094500-b3a241.log`）：
  - `deploy [build/ascendc] bash build.sh -c ascend910b`
  - `Stage 'deploy' failed with fail_strategy=halt; stopping pipeline.: deploy step 'build' failed`
  - `Workflow halted: a stage exhausted its correction budget on an unresolved build/precision failure.`
- `DeployStage.fail_strategy = "halt"`（halt stage 失败即停整条 pipeline）。
- `graph_executor._execute_sequential` 的 halt 信号检查（`_stage_failed`）在 `_resolve_condition` 路由**之前**触发——所以 transition_table 里写的 `deploy_failed: ("codegen","corrective")`（generate_ascendc / generate_ascendc_dev / self_evolve_op 三个 workflow 都有这条边）**是死边**：halt 先于路由抢断，该边永不生效。
- 结论：deploy 失败的既有设计本意是「回 codegen 改」，但因 `fail_strategy=halt` 抢占，实际行为是「直接停」。

### 凭证（B — 无具体错误）

- 控制台：runner 失败分支只打印 `last_error.error_type` + `message`，不打 `details`。
- `_run_command`（deploy 编译/安装命令执行）返回 `f"[{st.name}]\n{r.stderr[:1500]}"`——只留 stderr 前 1500 字符、**丢弃 stdout**；`_err` 的 `details.stderr` 再 `[:2000]` 截断。
- state_snapshot.json 的 `last_error.details.stderr` 实测是 CMake `PACKAGE_NAME is not supported now` warning + add op compile 行的切片；**真正的算子编译错（rms_norm 相关）落在截断之外**。
- run 产物 `subprocess/` 目录为空——失败子进程的完整 stdout/stderr **未落盘**，事后无法回溯。

### 凭证（bug 仍在 HEAD，非已修旧账）

- `git show de47633:src/.../stages/deploy.py`（run 对应提交期的版本）与 HEAD 对比：P54 把 deploy.py 内联逻辑抽成 `Deployer` 服务（§2.5 单一通路重构），但**未改** `fail_strategy="halt"`、**未改** stderr 截断（`_run_command` / `_err` 截断逻辑原样搬进 `Deployer`）。故 A/B 两现象在 HEAD 仍复现。
- P54/P55 是 precision_debug in-stage 闭环工作，与 deploy 失败处理正交。

### 关联

- **P54**（in-stage 闭环原则）：精度失败应 agent 内闭环、不跨 stage loopback 损失上下文。本条的 redesign 方向（`33-capability-sink-redundant-stages-analysis.md`）把同一原则从 precision_debug 边界**前移到 codegen/build/deploy 边界**——build/deploy/smoke 改为 codegen 内闭环的原子能力，deploy stage 作为独立确定性 shell stage 被删，A/B 两现象随之失效（无 deploy stage → 无 halt 抢占、无死边；codegen agent 直接读完整 build stderr → 无截断）。
- **P53**（精度失败反馈链路死边/失真）：同类「transition_table 写了边但因别处抢断而失效 + 错误信息丢失」现象。P53 被 P54 redesign 绕开，P57 被 step-31 redesign 绕开。
- **CLAUDE.md §3.4 / §1.2 可诊断**：失败不留完整 stderr 属可诊断性缺口。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-09 | P57 记录（仅事实 + 凭证，不含方案）：deploy build 失败无 loopback（halt 抢占死边）+ 无具体错误（stderr 截断未落盘）。git 证据确认 HEAD 仍在。方案归 step-31 / `33-capability-sink-redundant-stages-analysis.md`（L3 草案）。 |
| 2026-07-09 | **P57 已解决（step-31 实施）**：deploy stage 整删（无 stage → 无 halt 抢占、无死边）；`Deployer` 落盘完整子进程输出到 `<run>/subprocess/*.log`、err details 含 log 路径（无截断）。A/B 两现象随删 deploy stage 失效。UT 1670 / 非 heavy ST 106 passed。as-built 见 `34-*.md` §6。heavy_llm e2e（§3.11）：用户决策跑 1 件 `test_full_pipeline` passed（~35min，验证 codegen in-session build 闭环 → deploy_failed 止损机制端到端）。 |

---

## ✅ P58: generate_ascendc/dev/se 与 self_evolve_op 架构分叉——同样夹 deploy/verify 死边/截断，且精度失败无 in-stage 闭环（中优 follow-up）→ **已解决（2026-07-09）：随 step-31 / Option II 全局一致落地**

### 事实

`generate_ascendc` / `generate_ascendc_dev` / `generate_ascendc_se` 三个 workflow 的图仍是 `codegen → deploy → verify → perf → integrate → finalize`，与 self_evolve_op（已定稿删 deploy/verify、agent 内闭环）**架构分叉**。具体：

- **deploy/verify 死边/截断适用 P57**：三者 transition_table 均写 `deploy_failed: ("codegen","corrective")` + `verify build_failed/precision_failed: ("codegen","corrective")`，但 deploy 的 `fail_strategy="halt"` 同样抢占 `deploy_failed→codegen` 为死边；`_run_command` stderr 截断、不落盘同样存在。P57-A/B 两现象在这三个 workflow 同样复现。
- **精度失败无 in-stage 闭环**：三者 `precision_failed → codegen`（**无 precision_debug stage**），即精度失败仍跨 stage loopback 回 codegen——P53 反馈失真三连断裂 + P54 论证的 loopback 三硬伤（上下文损失 / 频繁启 agent / debug workflow 不可复用）在这三个 workflow 全部存在、未治理。
- **pipeline 无 precision_debug 节点**：三者的 `_PIPELINE_STAGE_NAMES` 不含 `precision_debug`。

### 凭证

- workflow.py：`generate_ascendc`（deploy 分支 `deploy_failed: ("codegen","corrective")`、verify 分支 `build_failed/precision_failed: ("codegen","corrective")`）、`generate_ascendc_dev`（同形）、`generate_ascendc_se`（同形）。三者 verify `precision_failed` 均 → codegen，无 precision_debug 边。
- 三者 pipeline stage 名序列含 `deploy`、`verify`，不含 `precision_debug`。
- P57 的 halt 抢占 + stderr 截断机制在 `DeployStage`/`Deployer`，三个 workflow 共用同一 deploy stage → 缺陷同源。

### 关联

- **P57**：deploy/verify 死边/截断的本源事实。P58 是其在 generate_* 三个 workflow 的同源复现。
- **P53/P54**：精度失败反馈断裂 + in-stage 闭环原则。P54 已在 self_evolve_op 落地 precision_debug；generate_* 三个 workflow 尚未跟进，P53 类断裂仍存。
- **step-31 / `33-*.md` §9.1 → §12**：self_evolve_op 的能力下沉 + 删 deploy/verify 方案。P58 是其向 generate_* 的推广——**收口时须与 self_evolve_op 方案一致**（同样删 deploy/verify、codegen 内闭环 build、precision 失败进 in-stage 闭环），不另立第二套架构。
- → **2026-07-09 吸收进 step-31 / Option II 全局一致**：codegen 共享 stage 的 build 闭环是 all-or-nothing（无法只对 self_evolve_op 开，L3 §12.1），用户获悉真实范围（perf 硬依赖 precision_result + 删两 stage 类的测试 churn）后改拍全 5 workflow 同步收口。**P58 不再独立 follow-up**；`DeployStage`/`VerifyStage` 类随本步删（不再保留）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-09 | P58 记录（仅事实 + 凭证，不含方案）：generate_ascendc/dev/se 与 self_evolve_op 架构分叉——同源 P57 死边/截断 + 精度失败无 in-stage 闭环（P53/P54 类）。中优 follow-up，收口须与 step-31 方案一致。 |
| 2026-07-09 | **P58 吸收进 step-31 / Option II 全局一致**：codegen 共享 stage 的 build 闭环 all-or-nothing（L3 §12.1）+ 取证发现 perf 硬依赖 precision_result / 删两 stage 类的测试 churn，用户改拍全 5 workflow 同步收口。P58 不再独立 follow-up；`DeployStage`/`VerifyStage` 类随删。L3 §12 / L4 已按 Option II 修订。 |
| 2026-07-09 | **P58 已解决（step-31 实施完成）**：全 5 workflow 同步删 deploy/verify、加 precision_debug（精度失败→agent in-session 闭环）；perf 门槛换源 debug_result；`DeployStage`/`VerifyStage`/`PrecisionResult` 类 + `precision_result` 字段随删。架构分叉消除。UT 1670 / 非 heavy ST 106 passed。as-built 见 `34-*.md` §6。 |

---

## ❌ P59: 设计侧 gate 把「判定=verified、非阻断、且 remediation 自指下游 owner」的跨模板一致性问题，强制 backward 回跳到上游 per-template 盲的 tiling——框架无「前向建议通道」路由语义

### 事实

`anchor-consistency` gate 产出的 issue 有三张面孔：`target`（指向某 stage）/ `verdict`（infeasible | unverified | verified）/ `remediation`（建议非强制）。`verified` 意为「问题真实存在但非阻断」，`remediation` 是非约束建议。该 gate 的转移逻辑把 `target=tiling` 映射为条件 `infeasible`，进而由 transition_table 路由回 `tiling`（corrective backward）——即只要 issue 的 `target` 落在 `tiling`，**无论 verdict 是否 verified、remediation 是否指向他处**，都回跳 tiling。

tiling 是 fork-join：每模板独立跑 split→buffer-kernel→precision-perf 一串 segment，且 segment 的 prompt 明令「对单模板执行，代入上游锁定决策，勿读其他模板」——每个 segment 绑死单一模板、结构上看不到其他模板。因此「两模板字段命名冲突」这类**跨模板一致性问题**，任何单一模板的 tiling segment 在结构上都无法修（它读不到别的模板），合法 owner 是跨模板的 `integrate`。框架无对应路由把这类非阻断问题前向投递给 `integrate`。

### 凭证

- 运行 `logs/e2e_self_evolve_20260710-140459-5d4217.log`：`anchor-consistency` 产出唯一阻断 issue `AC3→tiling`，`verdict=verified`，`remediation` 明写「建议非强制：integrate 阶段将两模板的 R5 tile 字段统一为单一命名约定」——问题本质是两模板字段命名冲突，合法 owner 是 `integrate`，不是任一模板的 tiling segment；但 gate 把它 `corrective→tiling`，迫使 tiling fork-join 全量重跑。后续 stagnation 放行才前进到 integrate。
- `AnchorConsistencyStage.resolve_condition`：`target=tiling → "infeasible"`（映射只看 target，不看 verdict / remediation）。
- design group 的 transition_table：tiling 相关边一律 backward corrective；全组路由表无前向非阻断边。
- `_TilingSegmentStage._build_prompt`：单模板约束 + 「勿读其他模板」。
- route_type 词表仅 `{corrective, escalation, validation}` 三种，无 forward / advisory 类型——框架词汇里没有「把非阻断问题前向带给下游合法 owner」这一类边。
- `issue_render` 渲染格式明示「判定=verdict ... （建议非强制：remediation）」——verdict 与 remediation 在表达层是分离两面，但路由层只用 `target` 决定去哪、不看 verdict 是否 verified。

### 关联

- **P15**（loopback 无收敛校验）：P15 管「该停的没停」（超额回跳），P59 管「方向错的回跳」（该前向给 integrate 却回 per-template 盲 tiling）——互补，同属 transition_table 路由方向族。
- **P13/P14/P16**（docgen 死锁族）：都是路由方向问题；P59 是同族在设计侧 fork-join 场景的新表现。
- 框架级缺口：route_type 词表无「前向建议」语义。方案见 `35-loopback-routing-and-incremental-analysis.md`（L3，调研中）。
- CLAUDE.md §1.2（可诊断）/§1.1（分层）：跨模板问题应落到跨模板 owner，回跳到 per-template 盲 segment 是路由越界。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-10 | P59 记录（仅事实 + 凭证，不含方案）：设计侧 gate 把 verified+advisory、remediation 自指 integrate 的跨模板一致性问题，强制 backward 回 per-template 盲 tiling；框架 route_type 词表无前向建议通道。方案归 `35-*.md`（L3 调研中）。 |
| 2026-07-13 | 主修复已上 commit `8e958f7` P0（advisory 前向通道 + target 正交化 D8 + 灰区 owner_ambiguous 默认前向并上报 D9），针对本条「方向错」。**维持 ❌**：P1-c[delta 前传]/P2[shift-left] 降级数据驱动 follow-up 未做，heavy_llm e2e 收敛曲线未重测（用户决策留 PR 前 §3.11）。L2 step 33 / L3 `35-*.md` / L4 `36-*.md`。 |

---

## ❌ P60: corrective loopback 重跑范围 = target→current 整段顺序区间；fork-join 下等于全部 per-template segment 全量重生成——即便单模板/单 segment 定向修改即可收敛，也按 target 粒度重跑，收敛慢、烧预算

### 事实

loopback 触发后，`graph_executor` 用 `_invalidate_sequential_range` 清掉 `target_idx .. current` 整段的 `node_status` 使其重跑；resume-skip 只跳过仍 completed 的节点。tiling 是 fork-join group（T1、T2… 多模板分支，每分支 split→buffer-kernel→precision-perf 多 segment）：回跳 `target=tiling` 时，**整组所有模板的所有 segment 都被清、都重跑**。即便问题只涉及一个模板（如 T1 的某字段）、或只需对一个 segment 做定向 patch，回跳仍重 spawn 全部模板的全部 segment agent。

### 凭证

- 运行 `logs/e2e_self_evolve_20260710-140459-5d4217.log`：`anchor-consistency` 一次 verified+advisory issue 触发 `tiling corrective 1/3`，fork-join 全量重跑（T1、T2 的 split/buffer-kernel/precision-perf 全部重新 spawn agent）；`anchor-consistency` 单轮数百秒、tiling 重跑再数百秒 × 模板数。
- `graph_executor` loopback 段：`_invalidate_sequential_range(cleared, path, order, by_name, target_idx, i + 1, ...)`——`i+1` 为当前位置、`target_idx` 为回跳目标，清中间整段顺序区间。
- group 可暴露 `rerun_selector(state) → set of branch names` 做 template-precise 回滚（代码注释标 C4 的既有原语）；当前 corrective 路径用 `_rerun_targets_of` 取 targets，但回跳 target 决定的清空范围仍是顺序区间，未据此收窄到「只改一个模板」。
- `runner.run_stage` 的 `start_iteration` 默认 1：loopback 重入时 segment 从 iteration 1 重新自迭代，不复用上轮 agent 进度。

### 关联

- **P59**：P59 是「方向错」（该去 integrate 却回 tiling），P60 是「范围粗」（即便方向对、该回 tiling，也是全组重跑而非定向）。二者叠加使收敛极慢。
- **P61**：P60 的全量重跑叠加 P61 的「增量修复 prompt 永不触发」，每次回跳 ≈ 从零再生成。
- CLAUDE.md §3.4 / 资源约束：全量重跑烧 token / 时间，影响 e2e 可达性预算与 §3.11 heavy_llm 决策。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-10 | P60 记录（仅事实 + 凭证，不含方案）：corrective loopback 按 target→current 整段顺序区间清空重跑，fork-join 下等于全模板全 segment 重生成；已有 template-precise 回滚原语（rerun_selector）未在 corrective 路径用于收窄。方案归 `35-*.md`（L3 调研中）。 |
| 2026-07-13 | 主修复已上 commit `8e958f7` P1-b（`blast_radius=localized` 加载期校验必带 `target_template`，缺则 last_error 拒绝；复用既有 `_tiling_rerun_selector` 做模板级回退收窄范围），针对本条「范围粗」。**维持 ❌**：同 P59，P1-c/P2 延后 + e2e 收敛未重测。 |

---

## ❌ P61: 「已有产物→增量修改」vs「从零生成」这一正交维度未被显式建模——tiling 的增量修复 prompt 被错误挂在 `iteration>1`，而 loopback 重入 iteration 重置为 1，导致即便回跳回来增量修复也永不触发、agent 从零再生成

### 事实

「这次 agent 调用是首次从零生成，还是基于已有产物做增量修改」是一个独立的语义维度（记 `entry-kind`：generate | modify），当前框架未显式建模该维度。tiling segment 的 `_build_prompt` 含一段「重试上下文：第 N 次尝试，工作目录已有之前迭代产出的文件，请基于已有产物增量修复，勿从零重复扫描」——该段 gated on `iteration > 1`。

`iteration` 是 stage 自迭代计数（`runner` 的 `for iteration in range(start_iteration, ceiling+1)`，默认 `start_iteration=1`），语义 = 「本 stage 本轮进入后第几次自迭代」，由 stage 自判产物是否合格决定是否续。loopback 重入一个 stage 时，runner 从 `start_iteration=1` 重新计数（iteration 不跨 loopback 续计）——所以回跳回来 iteration 又是 1，`iteration > 1` 的增量修复段不触发。后果：即便工作目录里已有上一轮 tiling 产物、`loopback_feedback` 也注入了「改什么」，agent 收到的 prompt 仍是「从零生成」口径（增量修复段缺席），等于全量重做。本质是把 `entry-kind`（generate/modify）这一正交维度，错误地用 `iteration`（自迭代计数）做代理量——而 iteration 的真实语义（自迭代）与 loopback（跨节点回跳）是两件事，代理不准。

### 凭证

- `_TilingSegmentStage._build_prompt`：增量修复段 `if iteration > 1:`。
- `runner.run_stage`：`for iteration in range(start_iteration, iteration_ceiling + 1)`，`start_iteration` 默认 1；loopback 重入未续计。
- `state.stage_iterations`：`stage_name → iteration`，按 stage 键，loopback 重入重置。
- corrective 计数是 scope（group）属性，与 iteration 正交（见 `35-*.md`（L3）§0 现状澄清）。

### 关联

- **P60**：P60 是范围粗（全组重跑），P61 是口径错（即便重跑也不走增量）。两者共同导致「回跳 ≈ 从零再生成」。
- 用户的正交三轴模型：`entry-kind`（generate/modify）/ `iteration`（自迭代，producer 自判）/ `corrective`（回跳，gate 判）应三者分离、显式建模——见 `35-*.md`（L3）。
- CLAUDE.md §1.4（不留过渡/别名）：entry-kind 应直接作为显式维度进 prompt 构造，不在 iteration 上挂代理。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-10 | P61 记录（仅事实 + 凭证，不含方案）：entry-kind（generate/modify）维度未显式建模，tiling 增量修复 prompt 错挂在 iteration>1，loopback 重入 iteration 重置致其永不触发。方案归 `35-*.md`（L3 调研中）。 |
| 2026-07-13 | 主修复已上 commit `8e958f7` P1-a（entry_kind[generate/modify] 按本 stage 自身产物文件是否存在于 working dir 判定，prompt 增量修复段从 `iteration>1` 改挂 entry_kind，loopback 重入 iteration=1 亦含增量段），针对本条「口径错」。**维持 ❌**：同 P59，P1-c/P2 延后 + e2e 收敛未重测。 |

---

## ✅ P62: 设计阶段产物读取无「落盘位置」校验——agent-dict 兜底 / 不碰磁盘的两类读取路径让产物写错目录（cwd 泄漏到仓根）也 result:ok，位置错误零信号，绿灯放行到远下游 validate 才爆 GV8

### 事实

设计阶段六条产物读取路径都不校验「产物是否落在正确目录（stage 的 working_dir 子目录）」：

1. **`_DesignSubstage._parse_single` 路径2 dict 兜底**（`design_substages.py`）：路径1 从 working_dir 读盘，但路径2 用 agent 返回的 `artifacts` dict 兜底判 success——磁盘没落对也能 parse 进 state → 绿灯。
2. **`_TilingSegmentStage.transition`**：直接从 `agent_result.artifacts` dict 读，**完全不碰磁盘**——产物没落盘 working_dir 也 `result:ok`。
3. **IntegrateStage / ValidateStage / AnchorPerTemplateStage / DetailedDesignIntakeStage 的自定义 transition**：各自直接读 agent dict，同一缺陷类（不走 `_parse_single`，故 P62 计划前提「_parse_single 覆盖全部设计阶段」不成立，已用户拍板扩展覆盖全部六条）。

全 `orchestration/` 无任何「产物是否落在 working_dir 下」的位置一致性 check（grep `relative_to`/孤儿/泄漏命中全是无关用途）。不变式「agent 在 working_dir 跑→产物自然落 working_dir」被假设却从未验证，dict 兜底还主动绕过它。

**CEL T1 实证**：批跑中 `cross_entropy_loss` 的 T1/buffer-kernel 子阶段 events 显示 `result:ok`，但 `artifacts/design/tiling/T1/` 无 `tiling_buffer_kernel.json`（产物被 cwd 泄漏写到仓根），聚合器 `tiling_results.json` 把 T1 默默聚成 `{split only}` → validate 远下游判 GV8「T1 tiling 不完整」→ corrective loopback。**位置错误本身零信号**——绿灯放行，直到远下游才爆。

`_TestDesignSubstage(_DesignSubstage)` 继承 `_parse_single`，故 test_design 阶段同受影响（同一缺陷类，正确外扩）。

### 凭证

- `_DesignSubstage._parse_single`：路径2 `artifacts = result.get("agent_result").artifacts` dict 兜底判 success（P62 前）。
- `_TilingSegmentStage.transition`：`raw = {self.schema_file: result["agent_result"].artifacts[...]}`，纯 dict、不碰磁盘。
- Integrate/Validate/AnchorPerTemplate/DetailedDesignIntake transition：各自 `result["agent_result"].artifacts[...]` dict 读。
- runner `_run_stage_body`：`terminal = output_contract.provides AND has_all AND quality_ok`；`last_error` 不在 terminal 计算，仅用于 iteration 耗尽后 halt 路由。`_build_prompt` 注入 `state.user_feedback`（既有重 spawn feedback 通路）。
- `_TestDesignSubstage(_DesignSubstage)`（`test_design_substages.py`）：继承 `_parse_single`。
- CEL 批跑 events / 聚合 `tiling_results.json`：T1 仅 `{split}`、buffer-kernel 缺，events 却 `result:ok`（runlog 问题 9 同事实）。

### 关联

- **P4（确定性磁盘读取）**：P62 是 P4 的「位置正确性」补完——P4 保证「从磁盘读」，P62 保证「读对位置」。
- **P40（cwd 修复）**：P40 修泄漏根因（cwd 退化），P62 是读取侧防御（即使泄漏也不绿灯）。
- **P59/P60 收敛修复（8e958f7）**：P62 不冲突——P59/P60 修 loopback 路由/范围，P62 修产物读取位置校验；二者正交。CEL 非收敛同时受两者影响（位置错绿灯 + 路由），P62 收口读取侧。
- CLAUDE.md §1.2（可诊断：异常路径留可观测信号，不静默吞）、§2.5（唯一通路：删 dict 兜底，不新旧并存）、§1.4（不向后兼容：兜底整删不留别名）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-11 | P62 记录（仅事实 + 凭证，不含方案）：六条设计产物读取路径无落盘位置校验，dict 兜底/不碰磁盘致位置错绿灯，CEL T1 实证；test_design 同受（继承 _parse_single）。方案归 `37-artifact-location-check-analysis.md`（L3，扩展覆盖六条路径）+ `37-artifact-location-check-impl.md`（L4）。 |
| 2026-07-13 | L1 header 同步 ✅：代码侧 commit `67821a7`（2026-07-11）已实施——六条设计 transition + test_design 收敛到 `_DesignSubstage._read_disk_artifacts` 磁盘单通路、删 agent-dict 兜底；UT 1726 + 非 heavy ST 96 随该 commit 绿（L2 step 35 / L3-L4 `37-*.md` 早已记录，本轮仅补 L1 header + changelog）。heavy_llm 留 PR 前 §3.11。 |

---

## ✅ P63: codegen `_programming_model_for` 误把 A2 归入 Regbase——与 design 层「A2 行为与 A3 一致」矛盾，910B 算子被引向 VF/RegTensor 路径三

### 事实

- **观测**：codegen 物化 meta.json 的 `_programming_model_for` 曾把 A2 与 A5 同归 Regbase（`if gen in ("A2","A5"): return f"{gen} Regbase"`），SKILL.md Step4 路径表亦列「A2 Regbase | 路径三 | VF 入口 + RegTensor」。A2 算子 programming_model="A2 Regbase" → skill 引导其走 VF 入口 + RegTensor 编码。

- **根因**：A2(910B)/A3(910C) 同属 Membase/SIMD 架构代，仅 A5(910D) 为 Regbase/VF 代。仓内 design 层早有正确认知（`general_design_common_knowledge.md`「Membase 代（A2/A3）/ Regbase 代（A5）」「A2 行为与 A3 一致」；`chip-version-generation/02-analysis.md` 同），codegen 侧映射与之不一致——910B 不支持 VF/MicroAPI，走路径三会生成无法编译的代码。

- **可诊断缺口**：`test_programming_model_mapping` 用 `assert "Regbase" in ...("A2")` 把错误映射锁死成绿灯，回归无法察觉（与 P62 同类：绿灯假信号）。SKILL 内部亦自相矛盾——Step4 让 A2 走 VF 路径三，Step3 限定「A5 Regbase 场景才查 VF 指令库」，A2 连 VF 指令参考都不查就被赶去写 VF 代码。

- **为何未早爆**：heavy_llm 的 codegen full_pipeline ST 默认不跑（§3.11）；大量用 A2 的 ST（chip gate 类）只测 chip 决策，未真跑到「A2 codegen → 产 VF 代码 → 编译」段。

- **修复**：A2 移出 Regbase 分支 → Membase（`_programming_model_for` 改为：仅 A5 Regbase，A2/A3/未知 均 Membase）；SKILL.md Step4 路径表 A2 改 Membase/路径二（与 A3 一致）；UT 断言改回 A2=Membase + 防回归注释。SKILL 的 A5 红线/【A5】自检本就限 A5，不动。

### 凭证

- `_programming_model_for`（codegen.py）：唯一调用点为 meta.json 物化的 programming_model 字段；修复后 A2→"A2 Membase"、A3→"A3 Membase"、A5→"A5 Regbase"。
- design 层正确认知：`general_design_common_knowledge.md`、`chip-version-generation/02-analysis.md`（A2=A3 Membase，A5 Regbase）。
- 验证：codegen UT 26 passed + orchestration 全量 991 passed；grep 无残留、无反向依赖。

### 关联

- CLAUDE.md §1.9（domain/chip.py 是命名权威源，但 programming_model 非 chip.py 职责、由 codegen 派生——本次对齐 design 层架构代划分）、§3.4/§3.9（UT 守护错误事实、绿灯假信号，与 P62 同类病根）、§1.2（可诊断）。
- 区别于 P64：P63 是已修复的映射 bug，P64 是 A5 VF 设计/验证闭环的未接入特性。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-11 | P63 修复：A2 programming_model 由 Regbase 改 Membase（codegen.py + SKILL.md Step4 + UT 三处连锁），对齐 design 层「A2=A3=Membase，A5=Regbase」。 |

---

## 🟦 P64: vf-design 已接入详设流水线；vf-test 单元验证闭环仍缺（优先级：中，用户标记）

### 进展（2026-07-19，vf-design 部分已落地）

- **vf-design 闭环已实现**（方案 B 完整闭环，过 §1.2 四把尺子）：移植外部 `ascendc-op-tiling-vf-design` 进本仓 flat skill 树，I/O 契约适配本仓 JSON（`tiling_vf_design.json`，`required_keys:["template","vf_design"]`）；新增 `TilingVfDesignStage`（`design_substages.py`，A5 门控 `skip_reason`+`chip_programming_model`，A2/A3 自跳过）；fork-join 工厂在 split↔buffer-kernel 间插入（`design_tree.py`）；`buffer-kernel` A5 路径消费 `vf_design` 作既定前提写 VF_CALL 伪代码（`ascendc-op-tiling-buffer-kernel/SKILL.md`）；`STAGE_SKILL_MAP`/`tail_calls`/`design_artifacts._rebuild_tiling_results` 接线；vendor `a5_regbase_design.md` 进 design-shared。**codegen 侧消费 vf_design（s2-analysis §2.4.0 + coder-regbase 蓝图约束）曾越界改动、已回退（d19bdb33）——P64 codegen 半交 A5 同事决策（见下「权责厘清」）。**
- **验证**：200 条相关 UT 全绿（含 vf-design 门控/transition/rebuild + A3 零回归）。真链路（§3.11 用户确认后跑）：vf-design producer 自闭环 `test_vfdesign_tui_selfclosure`（A5 RmsNorm，9min20s，PASS）+ docgen A5 渲染 `test_docgen_renders_vf_design_chapter_a5`（5min13s，PASS）+ dual-backend skill 投递守护（非-heavy）。codegen `.VT` 全闭环 e2e 未跑（A5 codegen 侧已转交同事）。
- **vf-test 部分仍缺**：`.VT.{M}` 单元精度验证（`ascendc-vf-test-agent` + `vf_verified/kernel_test/`）未接入——属独立能力，不在本次 vf-design 移植范围。
- **vf-design skip→transition 对齐修复（2026-07-20，P64 遗留）**：`TilingVfDesignStage` 在 A2/A3 经 `skip_reason`+`actions()->[]` 自跳过，但 `_TilingSegmentStage.transition` 开头无条件读 artifact——skip 时（无产物）误报 `missing_artifact` → `own_error` → `fail_strategy=halt`，A3 场景 detailed-design pipeline 在 join 点断（`test_design_pipeline_e2e::test_detailed_group_three_piece_and_tiling` 自 P64 起即红、因属非默认跑用例未被发现）。修复：transition 开头识别 `skip_reason`，skip 时干净 pass-through（不读 artifact、不写 vf_design slice、清 last_error）；落点在 stage 层（stage 自声明 skip 语义，可扩展至任一 segment skip，split/buffer-kernel/precision-perf 的 skip_reason 恒 None 零影响）。新增 skip→transition UT 守护；修正 2 个旧 transition UT（曾用 `State.empty()` 偷偷依赖「skip 仍读 artifact」的 bug 行为，现显式设 A5 chip 走非 skip 正路径）。237 design UT + e2e ST 全绿。

### 权责厘清（2026-07-19）：codegen A5 侧交还 A5 同事

- vf-design 移植（08d5ca22）当时未就 codegen A5 权责边界确认，越界改了两处 A5 codegen（同事负责区）：`ascendc-dev-s2-analysis.md` §2.4.0（临场发明 VF → 消费 vf_design）+ `ascendc-coder-regbase.md`（蓝图约束）。用户厘清"A5 codegen 由其他同事负责、用户只负责 A3"后，**已回退两处（d19bdb33）**，A5 codegen 消费侧交还 A5 同事自决。
- 正交性已实证：两文件还原 origin/main baseline 后，200 design UT + test_session_resume UT + vf-design production guard + schema 发现全绿——design 侧自洽，A5 codegen 消费形成独立场景可干净回退。
- **ascendc-coder.md（A3/通用 coder，用户领域）**同句蓝图约束经 §1.2 四原则评估：**可维护 ✗**（与 `ascendc-op-dev-coding` SKILL 的"实现蓝图主源/优先级/不猜测补全"重复，§2.5 唯一通路两来源）+ **架构合理 ✗**（方法论进 agent manifest，违 §4.1/§2.7，且与 manifest 自身"方法论经 slash 命令注入"原则矛盾）；动机源自 A5 vf-design 工作。**已回退**（零能力损失——"照蓝图实现"不变式仍由 A3 codegen SKILL 在正确层承载）。
- **交接契约 + 修改方案**：design 侧仍产出 staging `tiling_results.json` 的 `vf_design` 段（形状见 `docs/plan/self-evolution/p64-codegen-a5-vf-consumption-handoff.md`），A5 codegen 是否/如何消费由同事决策。design 侧承诺 vf_design 段形状稳定（schema 权威），需调整提需求给 design 侧。

### 事实

- **观测**：codegen skill 当前仅吸收 A5 VF 的「编码红线」（Step4 九条约束）+「VF 指令参考查阅」（Step3 指向 ascendc-dev-knowledge SIMD_API/Reg矢量计算 + 910D_knowledge_extra），**无 vf-design（VF 函数设计）与 vf-test（VF 单元测试验证）两个能力**。原 Phase C 的 `.VT.{M}` 子步骤 + `vf_verified/kernel_test/` 验证产物 + vf-test-agent 在当前框架无等价物。

- **影响**：A5 Regbase 算子的 VF 函数（`__simd_vf__`/`__simt_vf__`）生成后缺独立的「设计—验证」门——VF 逻辑正确性只能靠下游编译 + 精度循环被动暴露，无前置单测兜底。

- **既有决策约束**：`codegen-skill-a5-constraints/02-analysis.md` 已拍板「不照搬 ascendskills driver 机制（vf_verified/coding_index/.VT.{M}/RECORD_DIR）」——因其为 full-pipeline driver 产物，当前框架等价物 = staging 物化源产物 + skill 投递 + Event Sourcing。故 vf-design/vf-test 接入需独立设计，非照搬。

- **优先级**：中（用户标记）。排期归 L2，方案归 L3（待定）。

### 关联

- 原 Phase C 参考：`ascendskills/skills/ascendc-op-full-pipeline/references/phase-c-prompts.md`（C.3 ascendc-vf-test-agent 模板）。
- 既有 A5 约束方案：`codegen-skill-a5-constraints/`（已落地编码红线，明示不接 driver 机制）。
- CLAUDE.md §2.1/§2.5（接入须保 skill 即插即用 + 唯一通路，不与既有 codegen skill 并存第二套 VF 通路）。
- 区别于 P63：P63 是 A2 映射 bug（已修复），P64 是 A5 VF 设计/验证闭环的特性缺口。

---

## ✅ P65: 跨代 chip 判定用「代际严格相等」而非「编程模型兼容」——A5 真机无法验证 A2/A3 Membase codegen（向前兼容被误拦）

### 事实

- **观测**：用户要在当前 A5 真机上验证 A2 Membase codegen。域层面这是合法的**向前兼容**——A5 硬件支持 Membase（能编译运行 A2/A3 的 Membase 代码），但仓内三处 chip 判定**全部用「代际严格相等」**把它当硬阻塞拦掉：`adapters/npu/detect.py:chip_mismatch_reason`（`if design == runtime: return None`，被 codegen.validate_inputs PRIMARY gate + Deployer.deploy SECONDARY gate 共用）、`design_substages.py:_cross_generation_gate_fires`（design 前跨代确认软门）、codegen/deploy 的 `soc_version = to_soc_version(design)`（编译目标挂在 design 上）。

- **根因**：判定维度选错——以「代际码是否相等」判兼容，而非「runtime 真机是否支持 design 的编程模型」。Membase（A2/A3）与 Regbase（A5）的兼容性是**非对称**的：A5 向后兼容 Membase（低代际→高代际 = 兼容），A5 Regbase 不可降级到 A2/A3（高代际→低代际 = 硬阻塞）。严格相等把唯一真阻塞（A5 design + A2/A3 runtime）外的所有跨代组合一律拦掉，含合法的向前兼容。

- **衍生问题**：软门「改打本机」选项把 design 改成 A5 → codegen 产出 **Regbase** 代码，**篡改用户要的 Membase 风格**；soc_version 挂 design 导致兼容模式下编译目标代际错位。

- **修复**：新增 domain 单一源 `chip_programming_model(chip)` + `runtime_supports_design(design, runtime)`（兼容矩阵：Membase design→任意 A2/A3/A5 runtime 可；Regbase design→仅 A5 可）。三处 gate 改调矩阵；codegen/deploy 的 soc_version 改 **runtime 双源**（runtime 优先、design 回退）——`programming_model` 由 design 定代码风格，`chip_code`/`soc_version` 由 runtime 定编译目标，二者解耦。纯 design workflow（SE，requires_npu=False）维持跳过（已有 workflow_requires_npu 守护，不动）。反转既定决策：programming_model 由 codegen 私有上移至 domain（兼容矩阵需 detect/design_substages/codegen 三层共享，§2.5 唯一通路）。

### 凭证

- `domain/chip.py`：新增 `MEMBASE`/`REGBASE` 常量 + `_CHIP_PROGRAMMING_MODEL` + `_RUNTIME_SUPPORTED_MODELS` + 两函数；单一权威源（§1.9/§2.5）。
- 三处 gate：`detect.chip_mismatch_reason` / `design_substages._cross_generation_gate_fires` 改 `runtime_supports_design(design, runtime)`；`codegen._programming_model_for` 改调 `chip_programming_model` + meta.json 拆 design/runtime 双源；`deploy._template_vars` 编译目标改 runtime 优先；`context.py` 注释更新。
- 反转既有 UT 断言：(A2,A5)/(A3,A5)/(A2,A3)/(A3,A2) 由「不匹配」反转为「兼容 None」；(A5,A3)/(A5,A2) 保留「真不兼容」。新增 forward-compat / dual-source 用例（test_chip / test_chip_mismatch_pure / test_predesign_chip_gate / test_codegen_skill_delivery / test_deploy）。
- 验证：domain + orchestration + adapters UT 1277 passed + 命名守卫绿 + 静态 grep 无残留严格相等；ST test_predesign_chip_gate_resume（用 (A5,A2) 真不兼容）2 passed。

### 关联

- CLAUDE.md §1.9（domain/chip.py 命名/身份权威源，现并入编程模型）、§2.5（唯一通路——消灭三处私有的严格相等/编程模型副本）、§1.4（不留过渡层，programming_model 入 domain 直接改干净）、§3.7（runtime 未知→False 交调用方走「无法校验」分支，区分「不兼容」与「未知」）。
- 区别于 P63：P63 是 A2→Regbase 的**映射 bug**（哪代属哪个模型），P65 是「用代际相等判兼容」的**维度选错**（该用编程模型兼容矩阵）。P63 修对了映射，P65 修对了判定维度——二者正交，P63 是 P65 矩阵的正确性前提。
- 区别于 P64：P64 是 A5 VF 设计/验证闭环的特性缺口（未接入），P65 是 chip 兼容判定的修复（已落地）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-12 | P65 修复：domain/chip.py 新增编程模型 + 兼容矩阵（单一源）；三处 gate 改矩阵；codegen/deploy soc_version 改 runtime 双源；反转/新增 chip gate UT；ST predesign resume 对齐。 |

## ✅ P66: codegen working_dir 在 new 模式缺 state.op_dir 兜底 → cwd 退化到 workspace.artifacts → _persist_sources 反馈环 → artifacts/codegen/codegen/... 每跑累积一层嵌套

### 事实

- **观测**：从别机拷来的 run `output/20260710-140056-ba16cd` 出现 `artifacts/codegen/codegen/codegen/codegen/codegen/` 五层嵌套；规律是每次 codegen/RESUME 再跑加一层 `codegen/`。

- **根因（两级放大）**：
  1. **主因**：`CodegenStage.actions()` 取 `working_dir` 用 `op_identity.op_dir if op_identity else None`，**无 `state.op_dir` 兜底**。`op_identity` 是 **profile-gated** 的（`context.py` 仅当 `profile and state.op_dir` 均成立才构造）——本 run `repo_profile_name=''`（cann-bench 仓无 DevKit profile）→ profile 加载失败 → `op_identity` 全程 `None`（**尽管 `state.op_dir` 已设**）。于是 `working_dir=None` → spawn 传 `None` → `SDKBackend` 退化到实例默认 `working_dir=workspace.artifacts`（dispatcher 构造 backend 处设置）→ agent cwd=`<run>/artifacts`。对照 `deploy.py` / `cannbench_adapt.py`（文件定位 helper）取 op_dir 都用 `state.op_dir or op_identity.op_dir`（正确兜底），**唯独 codegen 的 spawn 漏了 `state.op_dir`** —— 单点遗漏。
  2. **放大器/反馈环**：cwd=artifacts 时，产物收集 rglob 扫整棵 artifacts 树（design/staging/requirement/debug/per-op/...）当 `generated_sources`；而 `_persist_sources` 又把镜像写进 `ws.artifacts/codegen/<key>` —— 落在收集根内部。下一轮 codegen 重扫 artifacts，把上一轮镜像的 `codegen/` 子树当新源收集，key 累加 `codegen/` 前缀 → 物理目录 `codegen/codegen/...`，**每跑一次加一层**。

- **凭证（数据）**：该 run 的 state snapshot —— `mode=new`、`op_dir` 已设（worktree 内 rms_norm 路径）、`repo_root` 已设、**`repo_profile_name=''`**、`op_identity=None`；`generated_sources` 592 项，`codegen/` 深度直方图 `{0:137, 1:129, 2:129, 3:123, 4:74}`，对应约 4–5 次 codegen 执行。最深一层 `changed_files.json` 自报 `reports_refreshed` 含 `artifacts/codegen/staging/...` —— agent 直接写进 artifacts 的直接证据。

- **同根因扩散（已一并修）**：静态 grep 确认编排层另有 **3 处 spawn working_dir 同型缺兜底** —— `perf.py`（working_dir + repo_root 双漏）、`cannbench_adapt.py`（agent spawn，同文件 _locate helper 反而正确，自相矛盾）、`precision_debug.py`。三者无 `_persist_sources` 放大器故未显形为嵌套，但在**任何无 profile 的 run**（如 cann-bench 批跑）都会 working_dir=None → cwd=artifacts → agent 在错误目录作业。按 §1.2 扩展性尺子（同类新情况自动正确归位，非逐处打补丁）一并加 `state.op_dir` 兜底，4 处 spawn working_dir 统一为 `state.op_dir or (op_identity.op_dir if op_identity else None)`。

### 凭证（修复落点）

- **主修复（断 cwd 退化）**：`CodegenStage.actions()` 的 `working_dir` 改 `state.op_dir or (op_identity.op_dir if op_identity else None)`，对齐 `deploy` / `cannbench_adapt._locate`。
- **纵深防御（锁死反馈环）**：`_persist_sources` 归一化 key —— 剥离重复前导 `codegen/` 段再写 `dest`（`startswith("codegen/")` 带斜杠，不误伤字面名为 codegen 的顶层文件）。即便 cwd 再误落 artifacts，伪源也落回正确深度、不累积。
- **同根因扩散一并修**：`perf.py`（working_dir + repo_root 兜底 `state.repo_root`）、`cannbench_adapt.py`（agent spawn working_dir）、`precision_debug.py`（working_dir）三处 spawn 同步加 `state.op_dir` 兜底。静态 grep 确认编排层 spawn working_dir 旧漏兜底模式已绝迹。
- **不动 dispatcher 构造 backend 的 `working_dir=workspace.artifacts` 默认**：design 子 stage 合法地以它为 cwd，非 codegen 职责，改了会误伤设计侧。
- **不动 `context.py` 的 op_identity profile-gate**：op_identity 绑定 profile + adapter（scan 文件需 adapter）是合理设计；cann-bench 仓无 DevKit profile 时 op_identity 合理为 None。正解是消费侧（各 spawn）兜底 `state.op_dir`，而非松绑 op_identity 构造条件。
- **TDD**：新增 `tests/ut/orchestration/test_codegen_output_paths.py` 两例锁死 codegen 根因 + 反馈环；precision_debug / cannbench_adapt / perf 三处各加 1 例锁死"op_identity=None + state.op_dir 已设 → SpawnAgent.working_dir == state.op_dir"。先红后绿。
- **数据清理**：损坏 run 目录的嵌套树清理是运维操作（`rm -rf` 该子树），非代码问题。

### 关联

- CLAUDE.md §1.2（根因优先；正确改动承担主修复保住不变式 + 纵深防御 last resort + 可观测，三者组合）、§2.5（唯一通路 —— 对齐 deploy/cannbench_adapt 既有写法，不另立）、§3.1（TDD 先红后绿）、§3.4（修根因不掩盖）。
- 区别于 **P62**：P62 是设计阶段产物「落盘位置无校验」（cwd 泄漏仓根零信号），本条是 codegen「working_dir 兜底缺失」+ `_persist_sources` 放大器（产物落点正确性的另一面）。同属 cwd/落点族，但 P62 在 design 侧无反馈环、本条在 codegen 侧有 persist 反馈环（每跑累积）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-12 | P66 记录 + 修复：codegen `working_dir` 兜底 `state.op_dir`（对齐 deploy）；`_persist_sources` 归一化 `codegen/` 前缀（断反馈环）；同根因扩散一并修 perf / cannbench_adapt / precision_debug 三处 spawn 兜底；新增 5 UT（codegen 2 + 三兄弟各 1）锁死根因、反馈环与 spawn 兜底。 |

---

## P67: 批跑仍依赖外部 shell（与具体代码仓耦合），Python CLI 无批跑入口；NPU 独占粒度=run 级

### 事实

- **观测**：多算子并发推进由外部 `scripts/batch_self_evolve.sh` 承担，Python `ascendc-devkit run` 一次只跑一个算子、无批跑参数。shell 脚本承担五类职责：git worktree 隔离、NPU 卡池 FIFO 分配、flock 互斥、resume 状态文件接力、日志路由。其中 worktree 创建、task 解析（`tasks/level*/<op>/proto.yaml`）、算子源码定位（`examples/.../csrc/ops/<op>`）三处直接写死了 cann-bench 仓的布局与目录约定。

- **约束冲突**：CLAUDE.md §1.7（资源路径指向项目自身，禁依赖外部路径）、§1.5（资源路径不硬编码）要求 Python 实现不得复刻 shell 的「与具体代码仓耦合」形态——即不能把 cann-bench 的 worktree/task 布局写进 Python。这是 shell→python 迁移的硬约束，不是风格偏好。

- **NPU 独占粒度**：当前 `--npu-id` 进 `task_request` → `state.npu_id`，**run 级独占**——一次 run 从 entry 到 finalize 的所有 NPU stage（deploy build/smoke、precision_debug run-cases、perf、cannbench_eval）共享同一张卡，卡在 run 入口绑定、跨整个 run 生命周期持有。多算子并发靠 shell 在 run 间分卡（FIFO 卡池），单 run 内部不分卡。这是「之所以要传 npu_id」的直接原因。

- **粒度细化的物理可行性**：NPU 实际占用只发生在 5 处 subprocess 调用点（deploy 的 build/smoke、precision_debug 的 run-cases、perf、cannbench_eval），这些点已用 `env = os.environ.copy()` + `subprocess(env=env)` 做子进程级 env 隔离（不写全局 `os.environ`），且 `device_id = str(state.npu_id)` 在子进程 env 注入。这意味着「subprocess 级领卡」在物理上可达——卡只在真正上 NPU 的子进程那一刻被占用，子进程结束即释放。run 内大量非 NPU 工作（design/codegen 的 LLM 网络 IO、文件 IO）期间卡是空闲的，run 级独占浪费了这部分。

- **并发模型**：当前 workflow 内已有 `ForkJoinGroup` + `ThreadPoolExecutor`（tiling/anchor 分支并行），但那是**单 run 内**的分支并发，不是多 run 实例并发。多实例并发在 Python 侧无现成通路。本 workload 的并发瓶颈是 LLM 网络 IO + CANN subprocess（两者都释放 GIL），ThreadPoolExecutor 对它而言是真并发，不需 ProcessPoolExecutor。

### 影响

- 批跑能力游离在 Python 框架之外：skill/agent/stage 体系演进时，shell 侧的批跑逻辑不随之演进；shell 的仓耦合无法被框架的加载期校验（§1.3）覆盖。
- run 级独占导致 NPU 利用率低：算子数 >> 卡数时，卡被 LLM 思考期空占；细化到 subprocess 级可提升并发吞吐。

### 关联

- **`self-evolution/01-multi-op-isolation.md`**（L3 性质，2026-06-29，明确「暂不进四层体系」）：已定稿多算子并发隔离方向——per-operator install-path opp 隔离（`ASCEND_CUSTOM_OPP_PATH` + `pip --target`/PYTHONPATH，复用 ops-evaluation 已验证模型）+ **`NPUSlotManager` 统一分卡**（当前孤儿待复活）。本条的 NPU 粒度细化方向与之同源，其 Stage 2 实质即复活该 `NPUSlotManager`，不另立。
- CLAUDE.md §1.7（仓自闭环）、§1.5（路径不硬编码）、§1.8（四层跟踪）、§1.2（方案合理性四尺子）、§2.5（唯一通路不留旧债）。
- 区别于 **`batch-sixops-runlog.md` / step-37**：后者记录六算子批跑中的运行期故障（P10 schema、软 stage timeout、session sidecar resume），是「批跑已经跑起来后暴露的具体 bug」；本条是「批跑能力本身该不该进 Python、NPU 粒度该不该细化」的架构问题，二者正交。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-13 | P67 记录：批跑 shell→python 迁移问题 + NPU 独占粒度从 run 级细化到 subprocess 级的真实意图。L3 见 `41-batch-fusion-analysis.md`（两阶段解耦：阶段 1 批跑融合 run 级卡池；阶段 2 NPU 粒度细化=复活 `01-multi-op-isolation.md` 的 `NPUSlotManager`，独立 follow-up，依赖批跑规模确认）。 |
| 2026-07-13 | 阶段 1 四项形态决策已拍板（见 L3 §4）：manifest=wrapper；卡池来源四级 fallback（含未配置 bounded 探测兜底）；并发=可选 `concurrency` 与卡数完全解耦（本地资源阀，未设=不设上限/全并发；阶段 1 run 级独占下 concurrency>cards 仅安全阀无吞吐收益，吞吐收益待阶段 2）；batch-prepare 阶段 1 不做。状态仍「待实施」，待 L4 + 实现。 |
| 2026-07-13 | **阶段 1 已交付**：`application/batch_runner.py`（manifest wrapper + 四级 fallback 卡池 + ThreadPoolExecutor run 级池 + 1-task 退化）+ `run_cmd --batch/--cards/--design-concurrency` 分支；零仓耦合（只认 manifest 项 `op_dir`，复用 `resolve_op_dir`/`dispatch`，不碰 stage/state.npu_id）。回归发现并修复 `bind_run_log` 并发竞态（见 P68）+ 测试污染。验收：全量 `tests/ut tests/st -m "not llm and not heavy_llm"` = 2000 passed / 0 failed；heavy_llm 真实并发跑留 PR 前用户决策。阶段 2（NPU 粒度细化）仍挂 P67 之下待规模确认。 |

---

## P68: bind_run_log 进程级全局状态在并发 dispatch 与测试间脆弱（阶段 1 回归期发现，已修复）

### 事实

- **观测**：`infra/log_capture.bind_run_log`（commit 7a150d1 引入）tee 控制台→`<run>/run.log`，方式是**改写进程级 `sys.stderr` + 模块级 `_BINDING` 单例**，拆除仅靠 `atexit`。批跑阶段 1 引入并发 dispatch（`batch_runner` ThreadPoolExecutor 多 run 实例）后暴露两类问题：
  - **并发竞态**：sibling 线程的 rebind 调 `unbind_run_log` 关掉本线程的 `_Tee._file`，本线程 `_Tee.write` 的 `self._file.write` 无保护 → `ValueError: I/O operation on closed file`（非确定性、时序敏感，stub 路径单跑常掩盖、全量回归才暴露）。
  - **测试污染**：`_BINDING` 跨 test 残留 → 后续 test 的 CliRunner 捕获到 stale `_Tee._terminal`，`result.output` 变空（`test_resume_cli` 全量跑红、单跑绿）；原仅 `test_state_machine_dispatcher` 本地 autouse unbind 兜自己一个文件。

### 根因与修复

- 根因：`sys.stderr`/`_BINDING` 是**可变进程级全局**，single-run-per-process 设计假设在并发 dispatch 下失效。`_Tee.write` 原只 swallow terminal 写、未 swallow file 写。
- 修复（落 `infra/log_capture.py` + `tests/conftest.py`，不碰 dispatch）：① `_Tee.write` 把 file 写纳入「logging 永不破坏 run」swallow 约定，catch `(ValueError, OSError)`；并发回归 UT `test_concurrent_binds_do_not_crash`（red 3/3 无修复 → green）。② 测试污染提升为 `tests/conftest.py` 顶层 autouse fixture（每 test 后 unbind，覆盖 UT+ST），删 `test_state_machine_dispatcher` 本地副本（§2.5）。
- **边界（留阶段 2）**：并发下 run.log 内容是 best-effort（控制台共享、输出交错），per-run 权威记录仍是 `events.jsonl`。真正的 per-run 控制台分离（multi-sink _Tee / thread-local stderr）留批跑阶段 2 / NPU 粒度细化时做，本次只取「不崩」。见 L4 `42-batch-fusion-impl.md` §6 补录。

### 关联

- P67（批跑融合，本缺陷在其实施期发现）、CLAUDE.md §3.4（失败必修根因）、§2.5（单一通路：删本地 unbind 副本）、memory `verify-known-risks-statically`（静态 grep 漏了「日志副作用」类全局，教训：进程级可变全局不只 os.environ/dict，还有 sys.stderr 改写）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-13 | P68 记录 + 即时修复：bind_run_log 并发竞态（swallow file I/O）+ 测试污染（conftest autouse unbind）。回归 2000 passed。 |

---

## P69: NPU 独占粒度从 run 级细化到 subprocess 级（阶段 2，用户推翻规模确认闸立项）

### 事实

- **背景**：P67 阶段 1 已交付 run 级独占卡池（`batch_runner.card_queue`：run 入口领卡、跨整个 run 持有、run 结束还卡）。run 内 design/codegen 的 LLM 网络 IO + 文件读写期间，NPU 卡空占。
- **立项**：用户 2026-07-13 推翻 `41-batch-fusion-analysis.md` §2.3「阶段 2 依赖批跑规模确认」排期闸，立即立项阶段 2。
- **调研修正**：`41` §1.2 估「5 处 NPU subprocess 点」，核实后**真正做设备选择的注入点只有 3 处**——`cannbench_eval._run_eval`（`--device-id` flag）、`NPURunner.execute`（`ASCEND_NPU_ID` env + harness `set_device` 双层 authoritative，覆盖 verify/perf/precision_debug run-cases）、`scheduling._run_subprocess`（`--npu-id`，训练线、不在 dispatch/batch 主路径、落到子 CLI NPURunner 顺带覆盖）。deploy/perf/precision_debug 本身不起 subprocess 选卡（perf/precision_debug 经 NPURunner）。grep 全仓**无 `ASCEND_VISIBLE_DEVICES`/`ASCEND_RT_VISIBLE_DEVICES` 用法**。
- **关键不变式**：`state.npu_id` 是 run 生命周期内常量（dispatch/entry 一次性写入），4 个 subprocess 消费者读同一值——这是阶段 2 要打破的（每个 subprocess spawn 瞬间从池领临时卡）。

### 方案（L3 `43` 冻结 9 项）

1. 卡池=**扩展现有 `NPUSlotManager`**（复用骨架，加阻塞 `acquire`/`acquire_context` + 死卡检测告警；用户拍板，不新建 `NpuCardPool`）。
2. 领卡粒度=**真 subprocess 级**（每处 NPU subprocess 独立领/还；opp 不绑卡故同 run 内不同 subprocess 可领不同卡，安全）。
3. `state.npu_id`：`int=0` → `int|None=None`，退化为 Optional 硬指定偏好（§1.4 直接改）。
4. **pool 总存在**：dispatch 接收共享池（batch）/传 None（单算子，card_context 兜底 yield preferred 或 0——实施定案推翻「dispatch 内部建单卡池」原计划，少一个分支，见 L4 §3），NPU subprocess 总走统一 `_card_context`，消除「None 走旧 state.npu_id」分支（§2.5）。
5. `card_queue` **收口步消灭**，统一到 NPUSlotManager（§2.5 不并存）。
6. 死卡回收=`with` + subprocess timeout + 检测告警；不上 lease/heartbeat（over-engineering）。
7. 线程模型沿用 batch_runner，不用 OpScheduler 子进程模型。
8. resume/events 影响轻：npu_id 普通标量走通用 snapshot rebuild、不进 events payload；卡是临时资源 resume 重新领。
9. **用户硬约束**：`--npu-id` 必须保留且 end-to-end 可用（ST 守护 card 值流到 subprocess spawn 边界，非 mock）。

### 关联

- P67（批跑融合阶段 1，本问题为其阶段 2）、`01-multi-op-isolation.md`（NPUSlotManager 复活方向 + 资源模型纠正[生成 run 内部 LLM-IO 与 NPU-计算交替闭环]）、CLAUDE.md §2.5（消灭 card_queue 单一通路）/§1.6（pool 依赖注入）/§1.4（npu_id 直接改）、memory `avoid-overdesign-prefer-reuse`（扩展非新建）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-13 | P69 立项：用户推翻 P67 阶段 2 规模确认闸。L3 `43`（9 项冻结）+ L4 `44`（10 Phase TDD）就绪。TDD Phase 1（NPUSlotManager 扩展）启动。 |
| 2026-07-13 | **P69 阶段 2 已交付**：NPUSlotManager 扩展（阻塞 acquire/acquire_context + 死卡告警）+ `card_context` 统一决策点 + 3 处注入点改造（NPURunner.execute[cannbench 双层注入 env+set_device] / cannbench_eval._run_eval[--device-id]，scheduling 训练线顺带覆盖）+ `state.npu_id: int\|None=None` + `state.card_pool` 瞬态字段（不进 snapshot，to_snapshot 经 `asdict(replace(card_pool=None))` 避 RLock pickle 崩）+ `dispatch(card_pool=)` 注入 + `--npu-id` 默认 0→None + L3 工厂 `orchestration.card_pool.build_shared_card_pool`（解 L2→L6 违规，§1.1）+ `card_queue` 消灭统一 NPUSlotManager（§2.5）。验收：UT 1925 passed（含 card→spawn 边界守护 4 例——真 NPURunner.execute/_run_eval+card_context+pool，只 mock OS 边界 subprocess.run 捕 env/argv，§3.9 真实链路守护）；非 heavy ST 70 passed（batch e2e + dispatch plumbing）。**用户硬约束满足**：`--npu-id` 保留且 card 值流到 subprocess spawn 边界有真实测试守护（非 mock 掉链路）。实施修正：L4 §9 原「stub-dispatch 真跑到 NPURunner」不可行（StubBackend design gate halt），card→边界守护下沉 adapter/stage 级真实 UT；真 LLM 全流程 e2e 留 heavy_llm Phase 10 用户决策。 |
| 2026-07-14 | **P69 收尾（3 项）**：① **CardAcquireTimeout 错误通道**——原不在 `graph_executor._control_exceptions` 白名单 → 被 swallow 成 stage_failed → 误导性 `EX_DATAERR`+"implementation bug" 日志（用户被误导去查代码 bug，实际卡池满）；修：白名单加入该异常（穿透到 dispatch）+ dispatch except 链加分支转 `EX_TEMPFAIL`（暂时性 back-pressure，非代码缺陷）+ 重试日志（§3.4 可诊断性；TDD 红→绿 `TestDispatcherCardAcquireTimeout`）。② **训练线 `--npu-id` 透传守护**——`scheduling._run_subprocess` 把领到的 card 注入子 CLI argv 此前无断言（L4 §9「scheduling 顺带覆盖」原为未验证假设），补 2 例 UT（mock OS subprocess.run 捕 argv，§3.9）。③ **类型债**——`test_cannbench_eval.py` 旧 UT `npu_id="0"`（str）→`0`（int，签名 `int\|None`）。验收：UT 1928 passed（+A 1 +B 2）、非 heavy ST 70 passed。 |

---

> 以下 P70-P75（2026-07-14 回补）为批跑六算子期（07-12/13）已修、已有 runlog 事实 + 方案 L3/L4 + commit，但**此前缺 06-problems.md L1 产权条目**的 6 条 doc-sync 回补（§1.8「每个事实只在一层有产权」——事实此前散在 runlog/方案，L1 缺）。客观事实记录于此，方案/实施细节引用既有 L3/L4。

## ✅ P70: docgen output_contract 文件名契约（PascalCase）与 design-generator 稳定产出（snake_case）不一致 → missing_artifact halt（已实施，批跑第二轮）

### 事实

- **观测**（批跑第二轮，runlog 问题6）：cross_entropy_loss / dynamic_quant 两算子 docgen `fail_strategy=halt`、correction budget 耗尽 exit=65。
- **根因（契约 vs skill 命名不一致，确定性）**：docgen output_contract 据 proto.yaml `name`（PascalCase，如 `CrossEntropyLoss`/`DynamicQuant`）期望 `<Pascal>_详细设计说明书.md`；design-generator agent **稳定产出 snake_case** `<op>_详细设计说明书.md`（实测两文件均落盘、内容齐全）。3 iteration 仍对不上 → `missing_artifact` → halt。重跑必复现。
- **凭证**：`batch-sixops-runlog.md` 问题6（:139-143）；两 snake_case 文件实测落盘。

### 处置（已修，批跑第三轮前）

放开文件名契约：DocgenStage 用 glob 匹配（与 P62「名称放宽 `_normalize_stem`」同向），不再硬期望 PascalCase。详见 runlog 第三轮（:176「修 P6」）+ commit；名称放宽机制见 P62 L3/L4（`37-artifact-location-check-{analysis,impl}.md`）。

### 关联

P62（产物落盘名称放宽，同向）、§1.3（加载期/契约校验）、§1.2（根因=命名契约非数值不确定性）。

## ✅ P71: anchor_report 在 corrective loopback 后未刷新 → validate 读陈旧 blocked → 路由 human → halt（已实施，批跑第二轮）

### 事实

- **观测**（批跑第二轮，runlog 问题8）：moe_re_routing validate `本轮阻断 (1): AC1#it2→human` → correction budget 耗尽 halt。
- **根因（anchor_report 陈旧，非设计真错）**：blocking_status.json(GV9-b) 自述——validate reviewer 复核发现 `anchor_report.json` 仍标 AC1 `verification=UNVERIFIED`（iteration-1/2 遗留、无 iteration-3），但**当前 tiling_results.json 中该问题实已消解**（T2 ComputeIdx 已是 4 参数 Arange、`verification=api_checked`、显式注「原 UNVERIFIED 已消解」）。corrective loopback 改了设计但**未刷新 anchor_report** → validate 读陈旧 blocked → 无法自动 relay → human → halt。
- **凭证**：`batch-sixops-runlog.md` 问题8（:153-157）；anchor_report.json 陈旧标记 vs tiling_results.json 已消解实测对照。

### 处置（已修）

anchor_report current/history 分离（`_merge_issue_history`）：当前轮 issue 与历史 issue 分开承载，validate 读 current 不被 history 陈旧标记污染。详见 runlog 第三轮（:176「修 P8」）+ commit。

### 关联

P21（anchor selector 读源——P21 是 selector 读 `anchor_report` vs `validation_report` 载体差异，本条是 `anchor_report` 自身在 loopback 后未刷新，不同层面）、§1.2（根因=刷新缺陷）。

## ✅ P72: codegen m.def schema 参数名不 fidelity proto/golden → cann-bench 关键字调用 `func(**params)` 全 case 0 分（devkit 自检盲区，已实施，方案38）

> **命名澄清**：runlog 问题10 自称「P10」、方案38 标题「P10 根治」——此处「P10」是 **runlog 内部对该 schema 问题的称呼**，**非 06-problems.md P10（test_design 外部用例通路）**，二者无关联。本条为 06-problems.md 独立编号 P72。

### 事实

- **观测**（批跑第四轮，runlog 问题10）：cann-bench eval 多算子全 case 0 分；salvage 实证 swi_glu schema `x`→`input` 后 77.42(20/20)、foreach_norm `p`→`scalar` 后 48.07(19/20)。
- **根因（schema 名 ≠ proto/golden 名）**：codegen 生成的 `op_plugin/<op>_plugin.cpp` `m.def("<op>(Tensor x, ...) -> ...")` schema 参数名（`x`/`p`）不 fidelity proto.yaml/golden 名（`input`/`scalar`）。cann-bench `kernel_eval` 按 golden 名**关键字调用** `func(**params)`（`param_builder.build_call_params` 用 golden 名建 dict），故 schema 名错 → `missing value for argument` → 全 case 0 分。
- **devkit 自检盲区**：smoke 只 `getattr` 验符号可解析、precision_debug 走 positional wrapper——positional 对参数名不敏感，故 schema 名错也过 devkit 全链路，到 cann-bench（关键字）才爆。
- **凭证**：`batch-sixops-runlog.md` 问题10（:265-304）；salvage 实测两算子 rename 后拿分。

### 处置（已实施 2026-07-12，plan step 37①）

`cannbench_adapt.transition()` 末尾 `_align_mdef_schema(state)` 确定性后处理（proto 单一真相源→正则解析 m.def→按位置 rename schema 字符串，不动 C++ 形参名/kernel→m.def 变更则 rebuild opp，失败设 `last_error=schema_adapt_failed` 阻断 eval）+ codegen `transition` warn（不自动改 manifest）。不入 codegen skill（§2.1/§2.7 桥接层职责）。L3/L4 = `38-p10-schema-adapt-{analysis,impl}.md`。

### 关联

P78（规格没进 spec 同构——schema 名是规格一面，proto→m.def 桥接）、§1.3（产物生成后校验）、§2.1/§2.7（不入 skill）。

## ✅ P73: _check_timeout 假杀「成功但慢」的 stage iteration → 产物完整可用被 StageTimeoutError 扔掉（已实施，方案39）

### 事实

- **观测**（批跑问题4/7，runlog）：swi_glu codegen 跑 4484s（budget 3600s）被判 `StageTimeoutError`，**但产物完整可用**（salvage 77.42, 20/20）；首跑 2976s>1200s budget 同样产物完整被判 exit 124。
- **根因（post-hoc 边界判定不区分成功/失败）**：`_check_timeout`（`runner.py`）是 post-hoc 迭代边界判定——agent 跑过 deadline 不被硬中断，返回后下个检查点才 raise。它不区分「上一 iteration agent 成功产出构建物但慢」与「失败/卡死」——成功但慢的 run 也被 raise，产物被扔。
- **凭证**：`batch-sixops-runlog.md` 问题4（:71-82）/ 问题7（:145-152）；salvage 77.42 实证产物可用。

### 处置（已实施 2026-07-12，plan step 37②）

Option A：`runner.run_stage` 记 `_last_iter_ok`（上一 iteration agent 是否 ok），`_check_timeout` stage 段 raise 加 `and not self._last_iter_ok`——成功但慢 → soft warn 不 raise（继续迭代）；失败/卡死仍 raise。workflow deadline 硬墙不变。不做 Option B 硬中断（asyncio mid-tool-use 取消脆弱）。L3/L4 = `39-soft-stage-timeout-{analysis,impl}.md`。

### 关联

§1.2（可维护/可诊断：soft 留 warn 不静默）；剩余防线（SDK stall 检测 / codegen 断路器 `codegen_consecutive_failures` / max_iterations / global `WorkflowTimeoutError`）已确认覆盖（不假杀 ≠ 无界）。

## ✅ P74: 429 crash 的 session_id 不持久化 → 手动 resume fresh 重跑丢 crashed session 推理记忆 → 浪费 token（已实施，方案40）

### 事实

- **观测**（批跑问题7，runlog）：429（Weekly/Monthly Limit，软限流非硬墙）打断 codegen agent mid-run（`agent crashed mid-run with partial output`），手动 resume 时 fresh 重跑整个 stage。本次 plan 期间两个 Explore agent 被 429 打断，实证场景现实性。
- **根因（session_id 不持久化 + State 覆盖不了 hard-kill）**：`session_id` 仅在单次 spawn 内为 "Content block not found" 瞬态错误捕获复用（`sdk_backend.py`），**不持久化**。手动 resume 走 `_resume_breaker_reset` fresh 重跑，丢 crashed session 推理记忆。且 hard-kill（SIGKILL/OOM）无 transition 可设 State 字段——State 字段在 `transition` 设，mid-spawn hard-kill 时 transition 没跑 → session_id 没进 State → resume 拿不到。
- **凭证**：`batch-sixops-runlog.md` 问题7（:145-152）/ 第五轮事实3（:321）。

### 处置（已实施 2026-07-12，plan step 37③）

sidecar **非 State**：`<run>/agents/<agent>.session.json` 由 `SDKBackend._spawn` 在捕获 session_id 当下写盘（mid-spawn，crash/kill 前已落盘→覆盖 hard-kill），clean finish 删；codegen.actions 读 sidecar 发 `SpawnAgent(resume_session_id=...)`；session-gone（`_is_session_gone` marker + stderr 盲区修复）降级 fresh。路径单一权威源 `infra/workspace.session_sidecar_path()`。heavy_llm ST 3/3 绿（含首次跑暴露并修复的 stderr 盲区：bogus resume 时 SDK 把 `No conversation found` 只写子进程 stderr）。L3/L4 = `40-session-resume-sidecar-{analysis,impl}.md`。

### 关联

P29（19/20-resume-hardkill）**互补不重叠**：P29=逐节点 flush `node_status`（resume 跳过已完成节点）；本条=sidecar 保 `session_id`（重入被中断节点续接 SDK session）——各一条通路各管一责（§2.5 无第二 session_id 路径）。

## ✅ P75: cann-bench build_run.sh `||` 把 kernel 编译失败吞成 RC=0 → devkit deploy 丢弃 stdout → smoke 假阳性绿灯 → codegen 自修循环收不到失败信号（已实施，方案45，第5类隐患）

### 事实

- **观测**（批跑第六轮，runlog 事实12）：CEL（cross_entropy_loss）eval 0/20——codegen 产出 5 处 AscendC API 签名错（Cast×3 + DataCopyPad×2），6 tiling_key 全 not generated，但 devkit 全链路 `smoke_passed=True`（假阳性绿灯）。
- **根因（kernel 编译失败被吞）**：cann-bench `build_run.sh` 的 `cmake --build --target binary || { echo WARNING; }` 把 kernel 编译失败吞成 RC=0（`.run` 包仍产出——host .so + opp 注册不依赖 kernel bin）；devkit `deploy.py:_run_command` 在 RC=0 分支 `return True,"",None` **丢弃整个 stdout**（含 `error: no matching function for call to 'Cast'`）且不落盘；smoke（aclnn kind 空操作）不验 kernel bin → `smoke_passed=True` → codegen in-session 自修循环（agent 读 `subprocess/*.log` 自修）**收不到失败信号**，从不修 kernel → kernel 0 bin → eval 全 0。
- **证伪（系统性盲区非 CEL 特例）**：rms_norm compilation=20 满 + function=12 低（精度）证明精度与 build 盲区正交，盲区只伤 compilation 维度。
- **凭证**：`batch-sixops-runlog.md` 事实12（:464-481）；精确丢失点 `deploy.py:332`（RC=0 时 `_persist_subprocess_output` 不调用 + stdout 丢弃）。

### 处置（已实施 2026-07-13，plan step 45）

选项 D：新建 `domain/build_log_scanner.py`（纯函数，匹配 CANN 工具链诊断模式 clang `error:` / `Op[..] compile failed`，非算子知识 §1.5）+ `deploy.py:_run_command` RC=0 且 `stage.role=="build"` 时扫描 stdout+stderr，命中 → 复用现有 RC≠0 通路（`_persist_subprocess_output` 落盘 + `smoke_passed=False` → redeploy CLI 返回 agent → 读 `subprocess/*.log` 自修）。零改动 codegen/transition/DeployResult（契合 B5/B1 in-session 自修 + §2.5 单通路，只让现有路径「看见」被吞的失败）。否决 A（跨仓改 build_run.sh §1.7）/B（adapter 重做 build.sh §2.5/§1.5/§2.7）/C（扩 DeployResult 字段多余）。L3/L4 = `45-build-output-scanner-{analysis,impl}.md`。

### 关联

P76（precision_debug artifacts-relay，第三类 path bug——**正交**：P76 是 transition 读源错配，本条是 build RC=0 吞失败）、§2.5（单通路：不新增第二条反馈路径）。

---

## ✅ P76: precision_debug transition 从 SDK artifacts dict 读 debug_result.json → dict 恒空 → 假值 halt 冤杀精度（批跑第三类 path bug，独立于 P66）

### 事实

- **观测**：六算子批跑 rms_norm（run `20260710-140056-ba16cd`）RESUME 进 precision_debug，agent 跑 394 turn / 4064s 后 halt exit 65（`agent 未产出 debug_result.json`）。但 worktree op_dir `debug_result.json` **实际产出且 `passed=True`**（max_diff=0.005423, iterations_used=3, best_commit=04299cf...）；`.precision-fix/checkpoint.json` status=passed。**精度实际通过，被 transition 误读成失败**（runlog 事实9）。

- **根因（机制错配，独立于 P66）**：`PrecisionDebugStage.transition`（`precision_debug.py:235-236`）从 `agent_result.artifacts`（SDK 内存 dict）读 `debug_result.json`；但 precision-debug skill 用脚本 `write-debug-result.py:28` 把文件写到 `<operator_dir>/debug_result.json`（= agent CWD = `state.op_dir`，SKILL.md:123 契约），**从不填 SDK artifacts dict**（`sdk_backend.py` 无 artifacts 捕获机制）。故 dict 读**恒为 None** → transition else 分支写假值 `passed=False/max_diff=999/iterations_used=30` → halt。**与 P66 不同源**：P66 是 spawn `working_dir` 缺 `state.op_dir` 兜底（cwd 漂移 + `_persist_sources` 反馈环，已修），本条是 transition **产物读取机制**错配（SDK dict vs 文件接力），P66 修了 precision_debug 的 spawn cwd 但没碰 transition 读源。

- **凭证**：(1) `write-debug-result.py:28` `out_path = os.path.join(operator_dir, "debug_result.json")` —— 写文件不填 dict；(2) `sdk_backend.py` grep `artifacts` 零命中 —— SDK 不捕获 cwd 文件入 dict；(3) 批跑实证 dict 空 → else halt（精度 passed=True 实证在盘）；(4) 对照 codegen.py:690-796 / perf.py:388 / requirement.py:224 读 `agent_result.artifacts` 是对的（那些 agent 填 dict）—— 故 SDK dict 机制本身正常，错在 precision_debug 用错了机制。

### 凭证（修复落点）

- **主修复（改读源 + 删死读）**：`PrecisionDebugStage.transition` 改读 `<op_dir>/debug_result.json` 文件，`op_dir = state.op_dir or (op_identity.op_dir if op_identity else None)`（对齐 P66/24d989f working_dir 解析）。删 `if hasattr(agent_result, "artifacts") ...` 两行 SDK dict 死读（§2.5 单通路，非 fallback——SDK dict 对本 stage agent 永远空，保留即留死代码/旧债）。
- **§2.5 单通路的正确含义**：非「全局 dict 或文件二选一」，而是「**每 stage 各守其 agent 的产出机制**」——codegen/perf/requirement 的 agent 填 SDK dict → transition 读 dict（对）；precision-debug agent 写文件 → transition 读文件（对）。机制选择由 agent 决定，stage transition 与之对齐。
- **§1.2 可诊断**：else 分支 message 从空泛「agent 未产出 debug_result.json」改为含期望路径（`期望路径: <op_dir>/debug_result.json` 或「op_dir 与 op_identity.op_dir 均未设」），让「agent 跑了但忘写/写错位置」一眼定位。
- **措辞对齐**：模块 docstring / transition docstring / prompt「写 debug_result.json 到 artifacts」→「到 operator_dir（= agent CWD）」，对齐 skill 实际契约。
- **不改**：parse 逻辑（PrecisionDebugResult 构造）/ routing（passed→cannbench_adapt / exhausted→降级）/ fail_strategy=halt / _max_rounds / skill 侧（write-debug-result.py + SKILL.md 写入契约已正确，§2.1 不动 skill）。
- **TDD**：改 3 现有 UT（`_agent_result(dict)` 塞 dict → `_write_debug_result(state, payload)` 写文件）；新增 3 守卫——`test_transition_reads_op_dir_file_ignores_sdk_artifacts`（op_dir 写真值 + SDK dict 塞矛盾假值 → 断言读文件，**事实9 防复发核心**）/ `test_transition_falls_back_to_op_identity_op_dir`（对齐 P66 兜底链）/ `test_transition_no_op_dir_incomplete`。先红后绿。

### 关联

- CLAUDE.md §1.2（根因优先；可维护——删死读、transition 与 skill 契约对齐 / 可诊断——message 含路径 / 架构合理——L3 stage 守自身文件接力产物，不渗 SDK 内部）、§2.3（skill I/O 契约=文件载体）、§2.5（单通路——每 stage 各守其 agent 机制，删 SDK dict 死读非 fallback）、§3.1（TDD 先红后绿）、§3.4（修根因不掩盖）。
- 区别于 **P66**：P66 = spawn `working_dir` 兜底缺失（cwd 漂移 + persist 反馈环，codegen 侧）；P76 = transition 产物读取机制错配（SDK dict vs 文件接力，precision_debug 侧）。同属批跑 path-bug family（事实5/8/9/10），P66 修 cwd 漂移根因后 P76 仍独立存在（transition 读源是另一处缺陷）。
- 与 **方案 45**（第 5 类隐患，build 输出扫描器）正交：45 是 build RC=0 吞 kernel 编译失败（deploy.py:_run_command），P76 是 precision_debug 读源错配。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-13 | P76 记录 + 修复：precision_debug `transition` 改读 `<op_dir>/debug_result.json` 文件（`state.op_dir or op_identity.op_dir` 兜底），删 SDK `agent_result.artifacts` dict 死读；else 分支 message 加期望路径；docstring/prompt 措辞对齐。改 3 现有 UT + 新增 3 守卫（file-wins-over-sdk-dict / op_identity fallback / no-op_dir）。UT 19 文件 + 全量 1889 + 非 heavy ST 102 全绿，0 回归。heavy_llm（§3.11）未跑。 |

---

## ✅ P77: 缺「用户指定重跑任意已完成 stage/substage」的入口——stage 迭代优化快速验证特性（已实施 2026-07-13，`--rerun-from`）

### 事实

- **需求（用户提出，2026-07-13）**：支持「从任意 stage/substage 强制重跑（哪怕已 completed）」，用于 **stage 迭代优化后的快速验证**——优化某 stage 后，基于前置 stage 的已有输出重跑该 stage 看改动效果，而不必从头跑整个 workflow。属快速验证特性，非 bug。
- **现状（无此入口）**：
  - `--resume <run_id>`（`dispatcher.py:448`）只跳过 `node_status=="completed"` 节点、从首个未完成继续，无 flag 反向「重置某已完成节点」。
  - loopback（`graph_executor._invalidate_sequential_range`）是 gate 触发的自动回跳，非用户指定。
  - `stage run --name X --from-run Y`（`stage.py` → `dispatch_single_stage`）能单跑一个 stage，但绕开 graph/node_status、无 loopback/路由、产物落独立 run——是「隔离单跑」非「graph 内重跑」。

### 调研结论（本轮三路调研，机制地图）

- **修改量：小到中**。底层原语全部就绪——`_invalidate_subtree` / `_invalidate_sequential_range`（`graph_executor.py:39-95`）、`rerun_selector`（`node_forkjoin.py:43-48`），loopback 与 resume 的 P52 因果校验已共用这套原语。缺的只是「用户触发的 rerun 入口 + 软上下文清理」，不动 graph_executor/stage 类/event schema。
- **「只改 node_status」机制上能触发重跑**（resume 硬门就 node_status 一道），**但不够干净**——会带历史包袱。
- **真实耦合（有理由，应保留）**：(1) P52 clean-prefix 因果级联作废下游（`_resume_node_status` `dispatcher.py:1509-1524`）——下游 stage 产物从上游推导/消费，上游重跑则下游 stale-completed 因果不可信，是正确性不变式非债；(2) events.jsonl 追加（Event Sourcing 契约：历史只增权威）；(3) sidecar 完成即删 → 重跑天然 fresh spawn；(4) 产物文件覆盖写（幂等）。
- **人为耦合（可消除）**：(1) stage 自管累加计数器 `codegen_iterations`/`debug_iterations`/`perf_iterations`（`state.py:182,193,196`）与 node_status 生命周期未对齐——P52 把 node_status 因果链理清，这层没跟上，重跑会继承抬高过的计数、离 halt 更近；(2) `last_error`/`decision_logs`/`pending_advisories` 残留（loopback「带反馈改」与 force-rerun「干净重跑」诉求相反却共用一套持久化）；(3) `routing_scopes` 配额残留（重跑不该继承旧配额）。
- **无物理不可逆副作用阻挡重跑**：deploy 是 per-op 隔离覆盖、git commit 是 agent 层行为非框架、产物覆盖写、`repo_baseline_ref` 保留供回滚。

### 候选方案（L3 待立项，细节归未来 `47-stage-rerun-analysis.md`）

- **方案 1（最小）**：CLI `--rerun-from <node_path>` + 手动同步清理一组软字段清单。代价中、易漏（每加自管计数器要记得补）。
- **方案 2（调研推荐）**：`State.reset_for_rerun(node_paths, mode="clean"|"incremental")` 集中管理「重跑需重置的全部 runtime state」，dispatcher rerun 入口与 loopback 共用；`mode` 区分干净重跑（清 last_error/decision_logs）与带反馈改（保留，兼容 loopback 语义）。职责落 State 层（§1.2）、复用全部 graph 原语、单一通路（§2.5）。
- **方案 3（根治）**：stage 显式声明拥有的 runtime 字段（类似 output_contract 加 `runtime_counters` 声明），`_invalidate_subtree` 按声明清。根治「字段漂移漏清」，但要改 stage 基类契约 + 所有有自管计数的 stage。

### 关联

- 承接 **P29**（resume 逐节点 flush snapshot）/ **P35**（halt 标 failed）/ **P52**（clean-prefix 因果有效性）：三者共构 node_status 生命周期管理，本条补「用户主动重跑」入口这一缺角。
- 区别于 loopback：loopback 是 gate 自动触发的回跳（框架内部）；本条是用户显式指定重跑（调试/迭代验证）。
- CLAUDE.md §1.2（可维护/可扩展——rerun primitive 让同类新情况自动归位）、§2.5（单一通路——rerun 与 loopback 共用 invalidate 原语，不另造）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-13 | P77 记录（需求 + 调研结论 + 候选方案）：用户提出 stage 迭代优化快速验证需求（重跑任意已完成 stage）。调研结论：修改量小到中（底层原语全齐）；真实耦合（P52 因果级联/events/sidecar）vs 人为耦合（自管计数器/软上下文/配额）已分清；无物理不可逆副作用。调研推荐方案 2（State.reset_for_rerun primitive）。**用户决策：当前不实施，优先级中**，L3 待立项（`47-stage-rerun-analysis.md`）。 |
| 2026-07-13 | **P77 实施**：用户改决策「需要实施完整的 P77」+ 核心约束「**rerun ≠ resume——重跑不能 resume 上一次会话的 agent**」。落地方案 2 变体（clean-mode only）：`_rerun_invalidate`（target 作 inclusive 断点的 P52 clean-prefix 作废 + 顺带 pop 祖先 group key 防 executor skip 整组 + ForkJoin sibling 平行独立不作废）+ `_delete_session_sidecars`（删 `<run>/agents/*.session.json` 保 fresh spawn）+ `Stage.rerun_reset_fields()` hook（默认=provides，codegen override 加断路器）+ `State.defaults_for()` + `_resolve_rerun_target`（裸名/全路径）+ CLI `--rerun-from`（需 `--resume`）。L3/L4 = `47-stage-rerun-{analysis,impl}.md`。UT 23 新增 + 全量 1911 绿 + resume ST 4 passed。详见 L4。 |

---

## ✅ P78: proto.yaml precision_thresholds 没作为「全链路精度规格」进 requirement spec → precision_debug 自造硬编码 1e-2 → int8 量化算子 false-alarm 冤杀（与 P10/P12 同构：规格的一面没进 spec，下游自造）（已实施 2026-07-14，commit 7696279；分歧 A+B 完整对齐）

### 事实

- **观测**：六算子批跑 DQ（dynamic_quant）—— devkit precision_debug 判 8 case failing，cann-bench eval 判 20/20 全过（kernel bit-exact 一致，runlog 事实12 / 第六轮收口）。
- **根因（不是数据问题，是规格没传递）**：devkit 与 cann-bench 用**同一份 golden.py**（`batch_self_evolve.sh:287`）、同 kernel（bit-exact）。差异 100% 在**比较容差层**：
  - cann-bench：dtype 感知 + proto.yaml `precision_thresholds: int8: 1.0`（DQ 精度规格，proto 最高优先 `evaluator.py:891-911`）。
  - devkit NPURunner harness：所有输出 cast float64 + 硬编码 `atol=1e-2`（`runner.py:101,228,496-500`），**完全不读 proto precision_thresholds**（`domain/` 零命中）。
  - DQ int8 `.5` 边界合法 ±1 量化差（CPU half-to-even vs NPU 取整）：cann-bench `1.0 > 1.0`=False 通过；devkit `1.0 > 0.01` 失败 → 冤杀 → 上百分钟 false-alarm grind。
- **第二处分歧（比较方法，非容差）**：devkit 全 dtype 一律 max-abs-diff（`runner.py:496-500` cast float64 绝对差，无 dtype/整数路径）；cann-bench 浮点走 MERE/MARE 相对误差、整数走精确匹配+abs-diff、另有 bit-exact/小值域/相消兜底（`compare.py:230-667`）。浮点路径系统性发散（小数值/大动态范围算子判定不同）；DQ 靠 int8 阈值碰巧盖住，但比较方法根因未除。
- **本质（与 P10/P12 同构）**：proto.yaml `precision_thresholds` 是**算子精度验收规格**（和 schema 参数名 P10、golden P12 一样是需求规则），应作**全链路单一真相源**——design/codegen/precision_debug/cann-bench 全引用同一份。当前**没进 requirement spec（OperatorSpec）**（`domain/` 零命中）→ precision_debug 自造硬编码 1e-2。cann-bench 能对是因直接读自己仓 proto；devkit harness 自包含、没读规格、用祖传默认。

### 凭证

- 同源：`scripts/batch_self_evolve.sh:287`（devkit GOLDEN=cann-bench golden.py）；runlog 事实12（bit-exact）。
- devkit 比较器：`adapters/npu/runner.py:101`（`precision_threshold: float = 1e-2`）、`:228`（`passed = max_diff <= precision_threshold`）、`:496-500`（全 cast float64 绝对差，无 dtype/整数路径）。
- 规格没进 spec：`grep precision_threshold src/ascendc_devkit/domain/` 零命中；harness 签名 `runner.py:93-103` 只接标量、不接 dtype 表/不接 proto。
- cann-bench 规格：`cann-bench/.../dynamic_quant/proto.yaml:18-20`（`precision_thresholds: int8: 1.0`）；`kernel_eval/utils/compare.py:291-347`（整数路径）/`:420-484`（浮点 MERE/MARE）。

### 关联

- **P10**（schema 名没进 spec，下游自造）/ **P12**（golden 窄化为 verify 专属）：同构——规格的一面没进 spec，下游自造。P10/P12 已修。
- §2.5（单一通路）：精度容差 devkit 与 cann-bench 各一套=双通路旧债，修复=收敛到 proto 进 spec 单一来源。
- §1.5：precision_thresholds 是验收规格（非算子实现知识），应进 requirement spec 全链路传递，非硬编码进 harness。

### 方案（已实施 2026-07-14，commit 7696279；分歧 A+B 完整对齐）

- **决策（用户 2026-07-14 拍板）**：分歧 A（容差）+ B（比较方法）**一起修**——devkit 完整对齐 cann-bench 精度判定。
- **方法来源 = devkit 自实现标准方法**：MERE/MARE/bit-exact/exact-int 是通用精度指标（非 cann-bench 专有），devkit 自有命名/结构实现，按 cann-bench 语义（dtype→方法派生）执行，**parity UT 对拍**守护一致；非逐字克隆、非运行时 import cann-bench（§1.7）。
- **阈值来源 = 默认表作传递数据**：默认 per-dtype 阈值是**数据**（dict literal，值对齐 cann-bench），经 spec 管线传递（proto 覆盖优先），runner 消费合并结果。
- **关键区分**：实现 cann-bench 所用标准方法 + 阈值作数据 ≠ 被否决的「devkit 自造第二份语义」（§2.5）；默认表回退 = cann-bench 自身合并行为（默认 ⊕ proto 覆盖），非凭空兜底。
- **否决（带可行性证据）**：原 A（跨仓 import cann-bench 比较器）反 §1.7；其 DI 变体（入参注入 callable）= 原 A 换皮——cann-bench import 名 `kernel_eval`、`package=false`、`PYTHONPATH` import 触发 torch_npu autoload 冲突（需 `TORCH_DEVICE_BACKEND_AUTOLOAD=0`），运行时外部依赖与硬 import 同质。原 B（devkit 自造 per-dtype 容差表）反 §2.5。
- **贯穿路径（确定性，非 LLM 提取——契约值非算子知识 §1.5/§2.7）**：proto `precision_thresholds` → `OperatorSpec.precision_thresholds`（Flow A `_attach_proto` post-step 重读 proto / Flow B `from_dict`），→ runner harness 调 `precision_compare.compare_outputs`。
- L3/L4：`self-evolution/48-precision-spec-threading-{analysis,impl}.md`。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-13 | P78 记录（需求 + 根因 + 修正方案）：proto precision_thresholds 应作全链路精度规格单一真相源进 requirement spec；当前没进 → precision_debug 自造硬编码 1e-2 → DQ int8 false-alarm 冤杀。与 P10/P12 同构。否决原 B（devkit 自造容差表）。**用户决策：写文档 + 审计整条链类似规格缺失并一并修复**。审计进行中，待结果统一规划实施。 |
| 2026-07-14 | **P78 实施**（commit `7696279`）：审计结论 = P10/P12/P78 三例同构，无新增同构病例。用户决策分歧 A+B 一起修（完整对齐 cann-bench）。方法来源 = devkit 自实现标准方法（MERE/MARE/bit-exact/exact-int + NaN-Inf 饱和 + 小值域/相消二阶段，零 import cann-bench §1.7）；阈值来源 = 默认表作传递数据（dict literal，proto 覆盖优先）。7 改动：domain（`OperatorSpec.precision_thresholds` + `TensorSpec.compare` + `coerce_precision_thresholds` + dtype list→scalar 降级）/ proto 双路解析（`read_proto_precision` + Flow A `_attach_proto` + Flow B `from_dict` 读 `operator:` 块）/ `adapters/npu/precision_compare`（新模块，自实现标准方法）/ runner（删 `precision_threshold=1e-2` 参 + harness 调 `compare_outputs` + 返回 `thresholds/case_details/precision_spec_declared`）/ perf（primary_dtype 从 inputs[0] 派生）/ debug_service（优先 `requirement.op_spec`）/ debug CLI + 3 skill 文档（指向 `case_details[].outputs[].passed` 权威，删 `0.01` 兜底）。UT +56（precision_compare 27 + domain 15 + requirement_proto 9 + runner_execute 5），全量 1954 passed（15 pre-existing env fail = NPU `_soc_version` raise / CANN toolkit 缺失，git stash 验证非回归）。heavy_llm/npu ST（DQ 真机 int8 ±1 端到端）按 §3.11 本次未跑，交付前决策。L3/L4 = `48-precision-spec-threading-{analysis,impl}.md`。 |
| 2026-07-14 | **P78 合并收敛**（merge origin/main）：精度比较方法收敛到 origin/main 设计——cann-bench 任务走 cann-bench 真实 `compare_tensors`（精确权威，`_cann_checker_used` 条件触发）；无 golden 回退 abs-diff（标量 `precision_threshold=1e-2` 作无-golden 回退，`_all_outputs_within_threshold` 逐输出判定）。`adapters/npu/precision_compare.py`（LOCAL 自实现标准方法 MERE/MARE/bit-exact）保留为 UT-only parity 参考（`test_precision_compare.py` 守护）——runner 不再调 `compare_outputs`、不返回 `precision_spec_declared`（上行的 P78 实施 行描述的是合并前 LOCAL 状态）。proto `precision_thresholds` 全链路 threading（domain `coerce_precision_thresholds`/`OperatorSpec` + proto 双路解析）沿用未变。`test_runner_execute.py` 7 例重写守护合并后 runner。 |

---

## ✅ P79: 合并取 origin/main runner 回退 P78 两个核心决策——维度 A（proto precision_thresholds 真值在生产运行时无消费点）+ 维度 B（try import cann-bench 重新引入）；解除 P78 选项 E（协议化）暂缓 + rule×backend 正交架构（已实施 2026-07-15，plan step 49）

### 事实

合并 commit `082c02f` 取 origin/main runner 后，P78（commit `7696279`）选定的方案 B 两个落地承诺均未在生产链路成立：

- **维度 A（阈值贯穿）未落地**：proto `precision_thresholds` 真值在生产运行时**无任何消费点**，三条比较路径都读不到真值。
  - **通路①**（cann-bench `compare_tensors`，`runner.py:648`）：threshold 来自硬编码字面量 `_custom_th = {'int8':1.0,'int16':1.0,...}`（`runner.py:682-688`），**不读 proto**。
  - **通路②**（abs-diff 兜底，`runner.py:38-66` `_all_outputs_within_threshold`）：`dts = dtype_thresholds or _DTYPE_THRESHOLDS_FALLBACK`（`runner.py:25` 自带默认表 `{'int8':1.0,'float16':0.001,...}`）。
  - **`dtype_thresholds` 上游断链**：来源是 `debug_service.py:130` `try_load_cannbench_task` → `task_loader._derive_thresholds` 读 `proto.get("thresholds", {})`（`task_loader.py:283`）——**字段名错**（proto 实际写 `precision_thresholds`），`explicit` 永远空 → 永远返回 `DEFAULT_DTYPE_THRESHOLDS`（`task_loader.py:34`）。
  - **悬空字段**：P78 引入的 `OperatorSpec.precision_thresholds`（`domain/operator.py:81`）`grep '\.precision_thresholds' src/` **零命中**——写进 spec 无人读。`debug_service.py:117` 注释称「优先 `requirement.op_spec`（携带 proto precision_thresholds）」，但只把 op_spec 当 operator 传给 runner，**未桥接 `.precision_thresholds → dtype_thresholds=`**（`debug_service.py:174-183`）。

- **维度 B（方法自包含）未落地**：runner 重新 `try import cann-bench`（`runner.py:466-479`：`_compare_tensors = None` → `if golden_source_path and 'tasks/' in str(...)` 路径嗅探 → 塞 `sys.path` → `from kernel_eval.utils.compare import compare_tensors`，软失败退 abs-diff）。P78 L3（`48-analysis.md` 选项 A/C）已否决此路径（§1.7 + torch_npu autoload 冲突 + `kernel_eval` import 名/`package=false`）。P78 自实现的 `adapters/npu/precision_compare.py`（MERE/MARE + 小值域/相消 + NaN-Inf 饱和，`test_precision_compare.py` parity 守护）**已就绪但 runner 未用**（UT-only）。

### 凭证

- `grep '\.precision_thresholds' src/ascendc_devkit/` → **零命中**（悬空字段实证，spec 侧 grep `.precision_thresholds` 无读取点）。
- `task_loader.py:283` → `proto.get("thresholds", {})`（字段名误读实证，proto 真实键为 `precision_thresholds`）。
- `runner.py:682` → `_custom_th` 字面量硬编码；`:466-479` → try import cann-bench + 路径嗅探；`:25` → `_DTYPE_THRESHOLDS_FALLBACK` 自带默认表。
- `debug_service.py:117`（注释）/ `:130`（dtype_thresholds 来源 `try_load_cannbench_task`）/ `:174-183`（`run_precision_cases(..., dtype_thresholds=dtype_thresholds, ...)`）。
- P78 L3 `48-analysis.md` 选项 A/C 否决理由（line 52-57）+ 选项 E 暂缓理由（line 65-69）。
- 四问溯源（用户 2026-07-15）：proto 格式/是否耦合、abs-diff 兜底可行性、proto 解析点、能否删 import → 全链路核实上述事实；用户进一步追问双标杆/命令注入/多仓复用 → 推翻选项 E 暂缓判据。

### 关联

- 承接 P78（精度规格单一真相源）；P78 选项 E（DI port + 可选 cann-bench adapter）的暂缓判据（「唯一出题方=cann-bench，adapter 空置属 §1.4 unused flexibility」）失效 → 本条**解除暂缓**。
- 与 P10/P12/P78 同构（规格一面没进 spec → 下游自造）；P10/P12 已修，P78 因合并回退需 P79 补齐。
- step 40（run_test 与 cann-bench 解耦：测试执行外部化）——P79 的精度对比器 backend 协议化与 step 40 的「外部测试命令通用契约」方向一致，P79 聚焦精度对比维度，step 40 聚焦测试执行整体，二者正交。

### 方案（已实施 2026-07-15，plan step 49）

解除 P78 选项 E 暂缓 + 补齐维度 A 贯通，设计 **rule（比什么怎么判，数据）× backend（谁来算，实现）正交架构**：
- **维度 A（已闭环）**：proto 真值经 `OperatorSpec.precision_thresholds` → `run_precision_cases`（L3 装配点）`merge_thresholds(op_spec.precision_thresholds)` → `CompareRule.dtype_thresholds` → runner harness 烘焙（`DTYPE_THRESHOLDS` + cann-bench 路径 `_custom_th`）+ 主进程聚合。`op_spec.precision_thresholds` 从悬空字段变**真实消费点**。
- **维度 B（已闭环）**：抽 `PrecisionComparer` 协议（`harness_setup_lines` + `aggregate`），默认 `DevkitComparer`（abs-diff，§1.7 自包含）+ 可选 `CannbenchComparer`（注入时才 import kernel_eval + 软降级 warn）；backend 由 `run_precision_cases(use_cannbench_checker=...)` **显式选择**（debug_service 算 flag，L2 不 import L6），**删** runner try import cann-bench + `'tasks/' in path` 嗅探。
- **三表合一（§2.5 单通路）**：删 `runner._DTYPE_THRESHOLDS_FALLBACK` / `task_loader.DEFAULT_DTYPE_THRESHOLDS` / `task_loader._derive_thresholds`（字段名误读）/ `CannbenchTask.thresholds` / `TaskCase.thresholds` / `_custom_th` 硬编。规范表唯一源 = `precision_compare.DEFAULT_THRESHOLDS`。
- **L3/L4 预留（不实现，YAGNI §2.7）**：双标杆/区间 rule、CommandBackend（命令注入）。接口签名留口（rule 用对象、comparer 是 Protocol）。
- **P79.1 预留**：FALLBACK abs-diff 升级为 `precision_compare` MERE/MARE（待 ST 真机验证）。

详见 L3/L4 = `self-evolution/49-precision-comparer-protocol-{analysis,impl}.md`。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-15 | P79 记录（事实 + 方向）：合并 `082c02f` 取 origin/main runner 回退 P78 维度 A（阈值真值三路径无消费点）/ 维度 B（try import cann-bench 重新引入）；用户四问溯源全链路核实 + 双标杆/命令注入/多仓追问推翻 P78 选项 E 暂缓判据 → 解除暂缓，立 rule×backend 正交方案。L3/L4 待写。 |
| 2026-07-15 | P79 v1 实施：新增 `domain/precision.py`（CompareRule）+ `adapters/npu/precision_comparer.py`（PrecisionComparer 协议 + DevkitComparer/CannbenchComparer + judge_case_details）+ `merge_thresholds`；`run_precision_cases` 作 L3 装配点（proto→rule + use_cannbench_checker 选 comparer）；runner.execute/_build_test_harness 改 rule+comparer；debug_service 桥接 flag；try_load_cannbench_task 3→2 元组；三表合一全删。UT 全绿（domain/precision 4 + precision_compare merge 4 + precision_comparer 16 + runner_execute 7 + precision_debug_assembly 5 + debug_cli 5），全量 UT 2041 passed/17 pre-existing fail（stash 交叉验证零回归）。ST DQ 真机守护待 NPU 环境（§3.11）。 |

---

## P80: 突发 429（`Request rejected (429)`）不匹配任何 marker 集 → 被当逻辑失败烧 stage iteration 预算，且 fresh 重跑丢 session 推理记忆

> L1 客观事实记录（不提方案、不排顺序）。证据源：`batch-runlog-20260715.md` 疑似 4/8 + 第四/六轮 + `50-non429-issues-analysis.md` §7 更正。

### 现象

批跑 20260715_194455 全程，多个算子在**长阶段尾部**（requirement / integrate turn 51 / docgen turn 68 / codegen / precision_debug）撞 `Request rejected (429) · Weekly/Monthly Limit Exhausted`（reset 2026-07-18 16:57:13）：

- requirement 阶段 429：`advance_step_v2` requirement-analyst **首次 query 即被拒**，自动进 `iteration 2/10` 重试（在 stage 层烧迭代预算，非 backend 层 resume）。
- integrate/docgen 阶段 429：`manifold` integrate turn 51（528s）、`multi_add` docgen turn 68（1340s）撞 429 → stage 标 `[partial]` → `fail_strategy=halt` → workflow exit 65。
- precision_debug 阶段 429：`aggregate` 03:44 debugger **首次 query 即被 429**（`precision-debugger query attempt 1 failed: API Error: Request rejected`），硬信号仅 7、debugger 几乎没跑就 halt。

### 客观事实 1：429 措辞落进代码的分类空隙，被当逻辑失败

- 实际 429 措辞 = `Request rejected (429) · Weekly/Monthly Limit Exhausted`。
- `_shared.py:_TRANSIENT_ERROR_MARKERS = ("Content block not found",)` —— **不含** 429 → `_is_transient_error()` 对 429 返回 False → backend 的 resume-retry 循环（`sdk_backend.py:585` `if not _is_transient_error(...): break`）**不接手** 429。
- `_shared.py:_INFRA_ERROR_MARKERS = ("No available channel", "Usage limit reached", "API Error: 401", "API Error: 403")` —— **不含** `"Request rejected"` 也不含 `"(429)"` → `_classify_error_type()` 对该措辞返回 None（非 infra）。
- 双重不匹配的净效果：429 被归入**逻辑失败**默认分支 → 计入 stage 的 N-strike / iteration 预算（`codegen_consecutive_failures` 或 requirement 的 `iteration 2/10`），每次是**丢弃 crashed session 的 fresh 重跑**（stage 层 re-dispatch，非 backend session resume）→ 丢推理记忆、白烧 token。

### 客观事实 2：runlog 实证 429 是 burst 突发限流，非账号硬封

- `manifold` 21:33 撞 429 后，其余 3 算子（advance/scatter/aggregate）**持续正常跑到 23:06+ 未被限** → 同一账号同一时刻并非全堵。
- `manifold` 经 3 次 resume（越过 integrate → validate → 全链路）终于 03:29:24 **DONE exit=0** → 同一被 429 打断的算子，隔窗重试可跑通。
- reset 日期（2026-07-18）是配额计数器滚动点，**不代表** reset 前请求全堵。
- 结论性事实：现措辞里的 `Weekly/Monthly Limit Exhausted` 是**服务端 burst 拒绝时借用的配额措辞**，无法凭措辞可靠区分「突发 burst」与「真硬配额」（两者可能同文案）。

### 客观事实 3：现有 backend 已具备 session-resume「继续」机制，但 429 走不进去

- `sdk_backend.py:315-620` 已有完整 resume-retry 循环：crash 后 `_dc.replace(options, resume=session_id)` + 发 `_RESUME_PROMPT = "继续"`（`_shared.py:367`），由 `resume_max_retries`（默认 10）+ `resume_max_no_progress`（默认 3）两闸兜底；`opencode_backend.py` 有 parity 通路。
- 该循环当前**只对** `_TRANSIENT_ERROR_MARKERS`（`"Content block not found"`）生效；429 因客观事实 1 不匹配而绕过它。
- 循环内**无 sleep/backoff**（step-27 当时判 429=infra 明确「不加 backoff（YAGNI）」，见 `27-infra-error-classification-impl.md`）。

### 凭证

- `src/ascendc_devkit/capabilities/agent/_shared.py:287`（`_TRANSIENT_ERROR_MARKERS`）/ `:298-303`（`_INFRA_ERROR_MARKERS`，含 `"Usage limit reached"` 但不含 `"Request rejected"`/`"(429)"`）/ `:367`（`_RESUME_PROMPT="继续"`）/ `:370-376`（`_is_transient_error`）。
- `src/ascendc_devkit/capabilities/agent/sdk_backend.py:315-620` resume-retry 循环，`:585` `if not _is_transient_error(last_result_text): break`（429 在此被踢出重试）。
- `batch-runlog-20260715.md`：疑似 4（requirement 429 进 iteration 2/10）、疑似 8（integrate/docgen 429 halt）、第四轮（manifold resume 3 次 DONE + aggregate debugger query1 即 429）、第六/七轮（区分 429 饿死 vs 非 429）。
- `50-non429-issues-analysis.md` §7：巡检期「硬信号计数」判据把 429 行误计为精度硬信号（advance_step_v2 实为 429 饿死 398s 即挂）。

### 关联

- **推翻 step-27（P50）对 429 的判定**：step-27 把 429 归 infra「不重试、不 backoff」，其证据是单次 503「No available channel」（真配置错）语境；本条以批跑多算子实证 429 是可 resume 的 burst 限流 → 该判定对 429 子类失效（对 `No available channel`/401/403 仍成立）。产权归本条，方案在 L3 `57-*-analysis.md`。
- 与疑似 9/10（precision_debug 非 429 硬失败 / 编排器 async 自转）正交：那两条是 debugger 链路 bug（step-52/53/56 处理），本条只治「429 被误分类 + 无退避重试」这一横切面。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-17 | P80 记录（事实 + 方向）：批跑 20260715 多算子 429 实证为 burst 突发限流（manifold resume 3 次 DONE 佐证）；现措辞 `Request rejected (429)` 不匹配 `_TRANSIENT_ERROR_MARKERS` 也不匹配 `_INFRA_ERROR_MARKERS` → 被当逻辑失败烧 stage 预算 + fresh 重跑丢 session 记忆。用户拍板 sleep+resume 落 backend 内循环、指数退避+封顶+可配置、统一按 burst 重试。L3/L4 见 step 57。 |
| 2026-07-17 | P80 已解决（step 57 实施）：backend 内 429 退避-resume 落地（`_shared` marker/backoff 纯函数 + `runtime_config` 4 可配参 + sdk `_spawn` 429 elif 分支 + opencode 退避 wrapper），重试轨迹经 `Logger.action('agent_backoff')`（sleep 前）+ `_Tee` per-write flush 落 run.log（SIGKILL during sleep 不丢）。全量 UT 2293 passed/7 skip + 非 llm ST 96 passed/2 skip，零回归。supersede step-27 对 429 子类的 infra 判定。heavy_llm 真实 429 全流程待用户决策跑（§3.11）。 |

---

## ✅ P81: requirement-analyst 凭空产出 hardware constraint design_target_chip=A5（需求文档无声明、CLI 没传、profile/runtime 均 A2）（已实施，方案60）

> L1 客观事实记录（不提方案、不排顺序）。证据源：run `20260717-070202-53f685` 产物 + events.jsonl + agents/requirement-analyst-01.jsonl。

### 现象

run 20260717-070202-53f685（同事机子，A2 硬件）的 requirement stage 产出 `requirement.json` 含 `constraints[1] = {"kind": "hardware", "design_target_chip": "A5"}`，requirement stage 据此 override `state.design_target_chip=A5`（run.log `design_target_chip override: -> A5`）。但该 run 运行环境实测 A2、CLI 未传、profile default_chip=A2、需求文档无任何芯片声明。

### 客观事实 1：A5 不是 CLI / profile / 需求文档 三个权威源给的

- CLI：`events.jsonl` 开头 `chip_decision` 事件 `design_chip=""` + `design_source=""`（该事件由 `application/dispatcher.py:815` 启动时从 `task_request.get("design_target_chip")` 直读，`design_source="cli" if design_chip else ""` `:458`）→ CLI 未传 `--design-target-chip`。
- profile：`resources/repository-profiles/cann-bench.yaml:26` `default_chip: "A2"`（注释"对齐本机 910B3 硬件"）→ profile 给的是 A2 不是 A5。所有 profile（cann-bench/ops-nn/omni-ops/ops-transformer）default_chip 均 A2。
- 需求文档：`artifacts/requirement/requirement_doc.md` 全文只有算子语义（WhereSyncBn = SyncBatchNorm + 两次 where），无任何芯片/硬件字段；agent prompt（`events.jsonl` spawn_context）明说 requirement_doc.md 是"唯一需求来源"。
- 权威源顺序声明在 `orchestration/kernel/state.py:88-89`（CLI > requirement doc constraint > profile default_chip > probe）。

### 客观事实 2：A5 是 requirement-analyst 自行产出（schema example 污染 + 当 ambiguity 决议）

- `agents/requirement-analyst-01.jsonl` 总结把"目标芯片"列为 ambiguity #4 自行决议为 "A5 (Ascend950)"——把需求文档里不存在的字段当成待决议 ambiguity。
- skill schema example 用 A5 作占位真值：`.claude/skills/ascendc-op-req-analysis/schema/requirement.json:13` `example.constraints` = `{"kind": "hardware", "design_target_chip": "A5"}`；`references/op_spec_schema.md:202` Add 算子示例同样 A5。该 example 经 `artifact.py` 渲染进 agent prompt（`requirement.py:190-195`）。
- agent 非交互模式 ambiguity 决议自动选 options 第一个（`.claude/agents/requirement-analyst.md:87-94`），被 example 的 A5 偏置。

### 客观事实 3：_apply_design_target_chip 无条件信 agent 产的 constraint，无文档溯源校验

- `orchestration/stages/requirement.py:265-266` constraints 直接从 agent 产的 `requirement.json` 反序列化；`:305-311` `design_chip` 取自 constraints 里第一个 `kind=="hardware"` 的条目；`:351-382` `_apply_design_target_chip` 无条件写入 `state.design_target_chip` 并重建 RunContext.hardware_target——**无任何"需求文档里真声明了才认"的校验**。
- 仓内无 doc-provenance/trace 校验（`grep -rn "constraint" orchestration/` 仅 `stages/perf.py:314-326` `_has_perf_constraint` 判存在性，不查文档）。
- 同族范式已存在：`requirement.py:326-349` `_attach_proto`（P69）以 proto 为单一真源、不信 agent 回显、确定性重读。

### 凭证

- `output/output/20260717-070202-53f685/events.jsonl`（chip_decision design_chip=""；requirement override A5）。
- `output/output/20260717-070202-53f685/artifacts/requirement/requirement_doc.md`（无芯片字样）+ `requirement.json`（constraints[1] hardware A5）。
- `output/output/20260717-070202-53f685/agents/requirement-analyst-01.jsonl`（ambiguity #4 决议 A5）。
- `src/ascendc_devkit/orchestration/stages/requirement.py:265-266, 305-311, 351-382, 326-349`；`application/dispatcher.py:457-458, 815`；`orchestration/kernel/state.py:88-89`。
- `.claude/skills/ascendc-op-req-analysis/schema/requirement.json:13`、`references/op_spec_schema.md:202`。
- `resources/repository-profiles/cann-bench.yaml:26`。

### 关联

- design_chip=A5（非 A2）本身不违反"design≠runtime 有意允许"（`requirement.py:300-304` 注释：A2 机器可做 A5 设计，design==runtime 校验在 deploy/verify gate）；本条的客观问题是 A5 **凭空产生**（非用户/需求文档声明），而非"故意跨代际设计"。
- 与 P82/P83 叠加：A5 触发 buffer_kernel 按 A5 Regbase 产出 VF 拆分 → P82 的 UNVERIFIED/selfcheck 打架 → P83 的 validate halt。
- 注：agents/*.jsonl 只记 agent 最终总结、不记工具调用（本次分析无法坐实 agent 内部推理，A5 来源基于三源排除 + session 总结 + schema example 巧合推断）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-17 | P81 记录（事实）：run 20260717-070202-53f685 实证 requirement-analyst 凭空产 hardware constraint A5（CLI/profile/需求文档三源均未给；schema example 用 A5 作占位 + agent 当 ambiguity 决议），`_apply_design_target_chip` 无条件信 agent constraint、无溯源校验。方向/方案在 L3 `58-*-analysis.md`。 |

---

## ✅ P82: verifiable_claims 的 UNVERIFIED 是无消费者的死状态；selfcheck 越界判查证 → 产物内部等级矛盾（已实施，方案60）

> L1 客观事实记录（不提方案、不排顺序）。证据源：run `20260717-070202-53f685` 产物 + agents/*.jsonl + checkpoint_convention.md。

### 现象

run 20260717-070202-53f685 的 buffer_kernel 产物（`tiling_results.json`）内部两个字段对同一事实（A5 VF 拆分）判定等级矛盾：`verifiable_claims[VC-BK-3].verification="UNVERIFIED"` 与 `selfcheck.a5_regbase_vf_split="PASS — ... per platform_diff.md A5 rule"`。validate GV3 据此"产物自洽性缺陷"报 blocker（target=human）。

### 客观事实 1：UNVERIFIED 是无消费者的死状态

- VC-BK-3 标 UNVERIFIED 后，无任何机制驱动查证升级（derived/api_checked）或确认超能力 escalate。validate 发现它即 target=human 交人，不执行查证。
- 但 VC-BK-3 的 `evidence` 字段已引用 `platform_diff.md 'Vector 函数: __simd_vf__/__simt_vf__'`（查证源在手边、agent 已读），按等级语义本该 `derived`（文档推导），却标 UNVERIFIED——`agents/ascendc-design-generator-T0_single-02.jsonl` 总结自陈"VF 选型依据 platform_diff 定性分类，未实测"。
- verification 等级（UNVERIFIED/derived/repo_aligned/api_checked）判据在 `.claude/skills/ascendc-op-design-shared/references/checkpoint_convention.md:190-195`，但 `derived` 仅举例"字节数推导"，未给完整判据（"文档推导是否够 derived"边界模糊）。

### 客观事实 2：selfcheck 越界判查证（本该只判结构）

- `selfcheck.a5_regbase_vf_split=PASS per platform_diff.md` 判的是查证维度（VF 分类是否对照 platform_diff），但 selfcheck 设计本该只判结构/逻辑（公式↔伪代码、Buffer↔Kernel、对齐）。
- selfcheck 字段无 schema 约束（`tiling_buffer_kernel.json` 只 required_keys，子字段自由产出，`a5_regbase_vf_split` 是 agent 自由命名）；`checkpoint_convention.md:125-131,184-186` self_check_summary 只规定结构（passed/failed/details），未规定"selfcheck 只判结构、不碰查证"。
- buffer-kernel skill `:134`"hardware_api_capability 字段每个数值已与 platform_diff.md 真值表对比"把 selfcheck 伸进查证领域。

### 客观事实 3：GV3 字面无 claims↔selfcheck 一致性条款，GV9-a 字面匹配漏网 a5_vf_split

- `.claude/skills/ascendc-op-design-validate/SKILL.md:69` GV3 字面只规定 TilingData↔Kernel、Buffer↔Kernel、切分公式↔Buffer 三方一致性——**无 claims↔selfcheck 等级一致性条款**；validate agent 自行扩展解读才报本条矛盾（见 `state_snapshot.json` "按 GV3 产物自洽性缺陷报告"）。
- GV9-a（`:118-120/:174/:231`）字面触发 `claim_type==hardware_api_capability && verification==UNVERIFIED`，精确串匹配；VC-BK-3 的 `claim_type="a5_vf_split"` 不命中 → 漏过 GV9-a（`claim_type` 枚举 `checkpoint_convention.md:136` 写死 3 种，agent 自由发明 a5_vf_split/buffer_layout/...）。

### 凭证

- `output/output/20260717-070202-53f685/artifacts/design/validate/tiling_results.json`（VC-BK-3 UNVERIFIED + selfcheck PASS）、`blocking_status.json`（GV3 detail）。
- `output/output/20260717-070202-53f685/agents/ascendc-design-generator-T0_single-02.jsonl`（"未实测"自陈 + "自检全 PASS"）。
- `.claude/skills/ascendc-op-design-shared/references/checkpoint_convention.md:125-145,184-195`。
- `.claude/skills/ascendc-op-design-validate/SKILL.md:69,118-120,174,231`。
- `.claude/skills/ascendc-op-tiling-buffer-kernel/SKILL.md:134,139` + `schema/tiling_buffer_kernel.json`。

### 关联

- 与 P81 叠加：A5 触发 VF 拆分产出（Membase 无 VF taxonomy，A5 Regbase 才有），VF 拆分的查证矛盾才出现。
- 与 P83 叠加：GV3/GV8-A 是 P83 validate halt 的直接燃料。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-17 | P82 记录（事实）：UNVERIFIED 无消费者（标了不查证/不升级/不 escalate），selfcheck 越界判查证（a5_regbase_vf_split PASS per platform_diff），GV3 字面无 claims↔selfcheck 条款（validate 自行扩展）、GV9-a 字面匹配漏 a5_vf_split；verification 等级判据不完整。方向/方案在 L3。 |

---

## ✅ P83: design gate 预算尽后 __halt__，无逃生到 codegen 的路径（halt 仅该留给 429 这类服务端不可用）（已实施，方案60）

> L1 客观事实记录（不提方案、不排顺序）。证据源：run `20260717-070202-53f685` events.jsonl/run.log + design_tree.py/graph_executor.py/workflow.py。

### 现象

run 20260717-070202-53f685 的 validate stage 跑满 3 轮预算（iteration 1/3→2/3→3/3）后，`resolve_condition` 返回 `redo_doc`（本轮同时有 target=human + target=docgen，`_route_from_issues` 按 dict 序 docgen 优先），`design_tree.py:64` TRANSITION_TABLE `redo_doc → (__halt__, escalation)` → 整个设计 halt（`events.jsonl` halt event condition=redo_doc），进不了 codegen。

### 客观事实 1：validate 把 escalation-only issue 当可重试的，corrective loop 空转烧预算

- `orchestration/stages/design_substages.py:1730-1732` ValidateStage.is_satisfied = `len(blocking_issues)==0`，**不区分 target**：target=human/docgen（validate 自己解不了）的 issue 也判 not satisfied → corrective loop 重试 validate。
- GV3(target=human, 需外部权威源)、GV8-A(target=docgen, 需 codegen 补 cpp) validate 重跑无法消除 → 3 轮预算白烧（每轮 ~12min）。
- ValidateStage 无 `default_max_iterations` 覆写，继承 Stage 基类默认 3（`orchestration/base.py:48`）；其他 design gate（general-design-review `:1063`/anchor-consistency `:1337`）显式设 1。

### 客观事实 2：预算尽后 redo_doc/human/redo_general 全 __halt__/__escalate__，design group 无法 completed

- `orchestration/design_tree.py:60-68` `_DETAILED_DESIGN_TRANSITION_TABLE.validate`：redo_doc→`__halt__`、human→`__escalate__:design_needs_human`、redo_general→`__escalate__:redo_general`，仅 redo_tiling→`(tiling, corrective)` 是可修 loopback。
- `orchestration/workflow.py:252-262` `_DESIGN_GROUP_PIPELINE_ROUTES["detailed-design"]`：design_needs_human→`__halt__`、redo_general→`(general-design, escalation)`。
- design group 是 codegen 的**线性后继**（`workflow.py:690-696` SequentialGroup：detailed-design → test_design → codegen_init → codegen），不 halt 即可 completed 推进到 codegen——**无需 TRANSITION_TABLE 加 codegen 边**。

### 客观事实 3：halt 文案误报为 build/precision failure

- `application/dispatcher.py:940-945` corrective_exhausted 文案："unresolved build/precision failure...implementation bug the coder could not fix...review the latest verify output"——实际是设计审查 unverified issue（非 build/precision、非 coder、无 verify output）。`halt_reason.message`（`graph_executor.py:428-433`）本意透真实原因但未覆盖该场景，落回模板文案。

### 客观事实 4：429 halt 与 design gate condition 路由正交（不同层）

- 429 退避在 `capabilities/agent/_shared.py` + `sdk_backend.py` + `opencode_backend.py`（P80/step-57），与 design gate（`design_tree.py`/`graph_executor.py`/`workflow.py`）零文件重叠；429 耗尽→AgentResult fatal→走 fail_strategy/last_error，不走 condition 路由。

### 凭证

- `output/output/20260717-070202-53f685/events.jsonl`（validate iteration 1-3 + halt condition=redo_doc）、`run.log:128-148`。
- `src/ascendc_devkit/orchestration/design_tree.py:42-69`、`stages/design_substages.py:1708-1738`、`workflow.py:252-262,690-696`、`application/dispatcher.py:940-945`、`orchestration/base.py:48`。

### 关联

- 与 P82 叠加：GV3/GV8-A（P82 的死状态/越界产物）是 validate halt 的直接燃料。
- 与 P80 正交：429 halt 是 backend 层（P80 已修），design gate halt 是编排层 condition 路由（本条）。
- 用户决策（事实记录）：设计阶段必须有必定逃生到 codegen 的路径，前提是①跑完所有预算②中间产物/交付件不能少；halt 仅留给 429 这类服务端不可用。方案细节在 L3。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-17 | P83 记录（事实）：validate is_satisfied 不区分 target 致 escalation-only issue 烧预算；预算尽后 redo_doc/human/redo_general 全 halt/escalate，design group 无法 completed 到 codegen；halt 文案误报 build/precision。429 halt 与本条正交（P80/backend 层）。方向/方案在 L3。 |

## ✅ P84: 概设 review 无闭环——reviewer 只能 halt 写 markdown，工程三向路由从未触发；known_issues 只 validate populate；SKILL 产物范式与工程层断裂（已实施，方案61）

### 客观事实 1：reviewer 遇 B1/B2/B3 写 markdown 阻断报告 halt，不进 blocking_issues → 工程三向路由从未触发

- `ascendc-op-general-design-review` SKILL.md（改前）「阻断条件」段教 reviewer 遇 B1（缺整章 §3~§5）/B2（梯度推导歧义）/B3（路径）写独立 markdown 阻断报告并终止；产物 `general_design_reviewed.json` 的 `blocking_issues[]` 恒空。
- 全量历史 review 产物 `output/**/general_design_reviewed.json` 的 `blocking_issues` 全为 `[]`（grep 实证）→ `GeneralDesignReviewStage.blocking_issues` 恒空 → `resolve_condition` 恒 `default` → `issue_target_mapping`（generator/requirement/human）三向路由从未被触发——「有路无车」。

### 客观事实 2：known_issues 只 validate populate，概设逃生 issue 丢失 + 跨 gate 覆盖

- `ValidateStage.transition` populate `design_known_issues`（本轮 blocking_issues，覆盖式）；`GeneralDesignReviewStage.transition` 不 populate → 概设 review 预算尽逃生时未消解 issue 不进 known_issues，丢失。
- validate 覆盖式 populate 会冲掉概设 review 先写入的遗留（review→validate 串行，后者覆盖前者）。

### 客观事实 3：SKILL 产物范式与工程层断裂 + 无 target 指导

- SKILL.md 步骤 7（改前）教写 `checkpoints/general-design.json`（旧 checkpoint 范式：step/review_result/self_check_summary），与工程层 `GeneralDesignReviewStage.transition` 经 `_parse_single` 读 `general_design_reviewed.json`（blocking_status 范式：status/blocking_issues/patched_nodes）不一致——文件名 + 结构双重断裂（reviewer 靠 schema/ + 通用能力实际写对了顶层，但 SKILL 文档与实际行为脱节）。
- SKILL 无 `blocking_issues[].target` 指导——reviewer 即便写 blocking_issues 也不知道 target 怎么填。

### 客观事实 4：review→requirement bubble 不带 feedback

- `graph_executor` 原只在 corrective-jump 路径注入 `state._loopback_feedback`（gate 的 blocking_issues），escalation-bubble 路径（review `design_input_invalid` → pipeline 层 requirement）不注入 → requirement 收不到 review 拒了啥，盲目重跑。

### 客观事实 5（附带发现）：checkpoint_convention.md manifest/planner 拓扑段过时

- `ascendc-op-design-shared/references/checkpoint_convention.md` 的 manifest.json（planner 生成）+ general-design.json 所有权段用 `checkpoints/{step}.json` + manifest 拓扑旧范式，工程层不消费（走 stage contract）。**已清理（step-62/P85）**：删 manifest.json/planner 段 + general-design.json 所有权段（错产物名）+ 顶部范围说明；保留字段定义/查证规则段（被 tiling schema/knowledge_policy 引用）。单步 JSON 文件格式段（checkpoints/{step}.json）+ code-analysis/req-analysis 的 op_spec.json/md 漂移由 **step-63/P86** 收敛。

### 凭证

- `output/**/general_design_reviewed.json`（blocking_issues 全空，grep 实证）。
- `src/ascendc_devkit/orchestration/stages/design_substages.py`（`GeneralDesignReviewStage.transition` / `ValidateStage.transition` / `issue_target_mapping`）、`graph_executor.py`（`_capture_loopback_feedback`）、`design_tree.py`（`_GENERAL_DESIGN_TRANSITION_TABLE`）。
- `.claude/skills/ascendc-op-general-design-review/SKILL.md`（改前「阻断条件」段 + 步骤 7）。

### 关联

- P83（详设 validate escape，方案60）的概设对偶：修C 解决详设 validate 无逃生，但概设 review 同类问题（无闭环 + 无 target 指导）未覆盖——本次补全。
- 用户决策（事实记录）：target 归属按根因（generator 凭现有需求能修→generator；根因在需求规格→requirement；连需求层都定不了→human），不按问题表象；review 与 validate 的未消解 issue 累积不互覆盖；review 闭环复用详设 redo_tiling 同款范式（gate→产出方 corrective）。方案细节在 L3 `61-design-review-closure-analysis.md`。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-18 | P84 记录（事实）：概设 reviewer 只能 halt 写 markdown（B1/B2/B3）致 blocking_issues 恒空、工程三向路由从未触发；known_issues 只 validate populate（概设逃生 issue 丢失 + 跨 gate 覆盖）；SKILL 产物范式（checkpoints/general-design.json）与工程层（general_design_reviewed.json）断裂 + 无 target 指导；review→requirement bubble 不带 feedback。已实施（方案61）。附带：checkpoint_convention.md manifest 拓扑段过时（独立遗留，未改）。 |

## ✅ P85: claims 链未落地——tiling schema 不要求 verifiable_claims，agent 服从 schema 不产，anchor AC1/AC2 对质空转（修B 收尾，已实施，方案62）

### 客观事实 1：tiling schema 不收口 verifiable_claims，SKILL 引导被 schema 机器契约压过

- tiling 三段 schema（`tiling_split`/`tiling_buffer_kernel`/`tiling_precision_perf`）`required_keys` 均不含 `verifiable_claims`；但三段 SKILL.md 都文字引导写 verifiable_claims（修B：buffer_kernel 骨架级 API 选型 `hardware_api_capability` / split 数值推导 `numeric_derivation` / precision_perf 硬件常量 `api_checked`）。
- agent 服从 schema 机器契约（required_keys）优先于 SKILL 文字引导 → tiling 产物从不写 verifiable_claims（最近 run 含 53f685 实证，三段产物全无该字段）。[[skill-product-contract-alignment]] 教训的又一实例。

### 客观事实 2：anchor AC1/AC2 对质空转（claims 是其对质唯一来源）

- `ascendc-op-design-anchor-per-template` 明文：verifiable_claims 是「对质的唯一来源」；AC0（含骨架级 API 但 claims 缺失→阻断）/ AC1（`verification==UNVERIFIED`→阻断）/ AC2（claim 与独立查证矛盾→阻断）。
- claims 不产出 → AC1/AC2 从不触发 → P82「产出方即查证」目标空转。
- claims 机制本身合理（双层：tiling 声明假设清单 + anchor 独立对照硬件 API 对质，破自评自证；anchor 依赖 claims 作输入——非冗余，删 claims = anchor 失核对对象）。

### 客观事实 3：53f685 未暴露因算子类型（elementwise）

- WhereSyncBn 用 Vector 原语（Sub/Muls/Add/Compare/Select/Rsqrt），无骨架级 API（gather/scatter/reduce/sort/topk/broadcast/transpose）→ anchor AC0 规则本就跳过（anchor_report 实证 "AC0 skipped per skill rule"）→ elementwise 算子不需 claims，缺失无害。
- 骨架级 API 算子（gather/scatter/reduce）才需 claims——这类算子若 tiling 不产 claims，AC0 会阻断（该产没产的卡点）；claims 收口后才能进 AC1/AC2 对质。

### 凭证

- tiling 三段 schema（required_keys 改前不含 verifiable_claims）、三段 SKILL.md（verifiable_claims 引导）。
- 最近 run tiling 产物（无 verifiable_claims，grep 实证）。
- `ascendc-op-design-anchor-per-template/SKILL.md`（AC0/AC1/AC2 + 「对质唯一来源」）、`ascendc-op-design-validate/SKILL.md`（GV9-a 消费 verifiable_claims）。
- `output/output/20260717-070202-53f685/artifacts/design/anchor-consistency/anchor_report.json`（skeleton_api_global_verdict N/A，AC0 skipped）。

### 关联

- P82（UNVERIFIED 死状态 + selfcheck 越界，方案60）的实质收尾：P82 标已实施，但 claims 链从未闭环（schema 没收口）→ P82 的 claims 部分空转；本步收口 schema 闭环（tiling 三段 required_keys 加 verifiable_claims）。
- P84 客观事实 5（checkpoint_convention manifest/planner 过时）：一并清理。
- 用户决策（事实记录）：claims 机制本身合理（不删），真问题是 schema 没收口；落 C 不是大重构，是 schema `required_keys` + `example` 收口——anchor/validate 核对规则修B 已写；elementwise 产 `[]` / 骨架级 API 算子产非空；tiling segment 不强制 errors（宽容）+ anchor AC0 兜底（骨架级算子）。方案细节在 L3 `62-claims-closure-analysis.md`。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-18 | P85 记录（事实）：claims 链未落地（tiling schema 不要求 verifiable_claims → agent 不产 → anchor AC1/AC2 对质空转）；53f685 因 elementwise 未暴露；claims 机制本身合理（anchor 依赖 claims 作对质输入）。已实施（方案62）。 |
| 2026-07-18 | P85 heavy_llm 验证通过（tests/st/test_design_claims_anchor_selfclosure.py，gather 算子）：A 产出端 tiling 按 schema 产 verifiable_claims / B1 anchor 一致 claim clean 通过 / B2 anchor 矛盾 claim 触发 AC2。三测试共 ~10.5 分钟，claims 链产出+消费两端 + 行为区间闭环实证。 |

## ✅ P86: SKILL 文档与工程层产物契约漂移——op_spec.json/md 教写但工程读 requirement.json（非断裂，文档陈旧债，已清理，方案63）

### 客观事实 1：design pipeline 6 SKILL 教写/教读 op_spec.json/md，工程层读 requirement.json

- req-analysis / general-design / general-design-review / design-intake / design-validate / general_design_template 6 处教写/教读 `op_spec.json`（结构化）+ `op_spec.md`（人类可读）。
- 但工程层 RequirementStage artifact_contract 用 `requirement.json`（schema 名 == 产物名 == 工程读写，三者合一），provides=["requirement"]；下游经 state.requirement 物化 requirement.json。
- **非断裂**：工程层 prompt（render_output_requirements 渲染 requirement.json schema example）override SKILL.md 文字引导，真实 run（53f685）agent 实际只写 requirement.json（无 op_spec.json/op_spec.md/checkpoints，全 run find 实证），pipeline 端到端跑通。单向文档陈旧债，非代码断裂。

### 客观事实 2：checkpoints/{step}.json 是死副产物；code-analysis 是孤立工具 skill

- req-analysis / code-analysis 教写 checkpoints/{step}.json，工程层 src 零引用（grep 0）；真实 run agent 也不写。
- code-analysis 无工程 stage、不在 STAGE_SKILL_MAP、不在 pipeline——孤立工具 skill，谈不上 stage 产物契约。

### 凭证

- 工程层自洽链路（requirement.py artifact_contract/transition + design_substages.py state.requirement 物化 + loader.py schema travels with skill）。
- 真实 run 53f685 artifacts/requirement/（requirement.json + requirement_doc.md，无 op_spec/checkpoints）。
- Explore 调研报告（grep 漂移面 + 真实产物实证 + 工程层行号 + 推翻"断裂"措辞）。

### 关联

- P84 客观事实 5（checkpoint_convention manifest/planner 过时）延伸：manifest/planner P85 已清，本步清 op_spec.json/md 漂移 + checkpoints/{step}.json 死债降级。
- 用户决策（事实记录）：只改 SKILL.md（不动工程层——工程自洽）；op_spec.json → requirement.json；op_spec.md 删（agent 不产 + 工程不读，人类可读已有入口 requirement_doc.md）；checkpoints/{step}.json 降级；op_spec_schema.md 字典化；precision-debug 独立不改。方案细节在 L3 `63-skill-doc-drift-analysis.md`。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-18 | P86 记录（事实）：design pipeline 6 SKILL 教 op_spec.json/md 但工程读 requirement.json（文档漂移，非断裂——真实 run agent 写对）；checkpoints/{step}.json 死债（工程零消费）；code-analysis 孤立工具 skill。已清理（方案63）。 |

## P87: general_design.json 是全仓唯一用非顶层 sections 包裹承载内容的 schema——CR1 四字段从未被 schema 强制过（已修，方案64）

### 客观事实 1：general_design.json 是 15 个 skill schema 里唯一把承载内容包在 sections 容器内的违例

- `general_design.json` 的 `required_keys` 改前为 `["op_name", "sections"]`——CR1 四个"核心字段"（切分轴优先级 / TilingData / 循环框架 / Buffer 评估）包在 `sections` 容器内部，**全仓 15 个 skill schema 里其余 14 个全部用顶层 `required_keys`**（如 `tiling_split.json: ['template','split','verifiable_claims']`、`template_division.json: ['templates','locked_decisions']`）。
- 后果：`sections` 容器本身存在与否才是唯一被强制的项，内部四个 CR1 字段全靠 agent 自觉——schema 形同虚设。

### 客观事实 2：validate_payload 只校验顶层 key，无嵌套/点路径校验

- `domain/artifact.py:64-94` `ArtifactSpec.validate_payload` 遍历 `required_keys`，只判 `key not in data`（顶层存在性）；全仓无任何嵌套校验逻辑。
- 推论：把 CR1 四字段从 `sections` 内提到顶层，validator 零改动即可真正强制——纯 schema + 文档修，不碰工程代码。

### 凭证

- `domain/artifact.py:64-94`（validate_payload 仅顶层 key）。
- 跨 schema grep：15 个 skill schema 的 `required_keys`，仅 general_design.json 含 `sections`（违例），其余 14 个全顶层。
- 改前 `general_design.json`（`required_keys: ["op_name","sections"]`）vs 改后（`["op_name","split_axis_priority","tiling_data","loop_framework","buffer_eval"]`）。
- 工程层 `design_substages.py` 的 `GeneralDesignStage`/`GeneralDesignReviewStage`：`_upstream_inputs`/`transition` 均已是 JSON-only 透传，零字段读取，故 schema 拍平零工程代码改动（实证：全量 UT 2333 passed/7 skip 零回归）。

### 关联

- P86（op_spec.json/md 文档漂移，方案63）同属"SKILL 文档与工程契约对齐"系列；P86 是文档名漂移（零行为变化），P87 是 schema 结构本身有盲区（required_keys 变严格——4 字段从未强制→现在强制），故 P87 存在"agent 按新 SKILL.md 产出拍平结构"这一真实链路需验证，沿用既有 design pipeline heavy_llm e2e 重跑（非新增独立 heavy）。
- docgen 的 `design_doc`（`state.py:191`）是"终态人读交付物无下游代码消费者"的先例；general-design 自身输出无独立人读终态文件需求，故 markdown/叙述内容降级为 JSON 内一个可选 `narrative` 字段（内嵌），不仿 design_doc 另设 State 字段 + 物化机制。
- 用户决策（事实记录）：方向 B（JSON 拍平为唯一机器契约，markdown/叙述降为 JSON 内可选 `narrative`）优于方向 A（把 markdown 章节整体译入 JSON `sections`）——四原则（可维护/可扩展/可诊断/架构合理）逐条对比，B 皆优，用户拍板"按你的建议做"。方案细节在 L3 `64-general-design-json-contract-analysis.md`。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-18 | P87 记录（事实）：general_design.json 是 15 个 skill schema 唯一用非顶层 sections 包裹承载内容的违例，CR1 四字段（切分轴/TilingData/循环框架/Buffer）从未被 schema 强制（validate_payload 只校验顶层 key）。已修（方案64）：required_keys 拍平为 4 字段 + 新增可选 narrative；schema + 两份 SKILL.md + 5 测试文件，工程代码零改动，全量 UT 2333 passed/7 skip 零回归。 |
| 2026-07-18 | P87 顺带清理：req-analysis SKILL `--from-general-design` 模式 3 处 `general_design.md` → `general_design.json`（P86/step-63 漏清——general-design 早产 JSON，该模式原会找不到文件）。属 general_design.json 契约同系列文档漂移，本轮一并收敛。 |

## ✅ P88: vf_design 消费侧覆盖——①docgen 已修+真链路证；②③④ 经 §2.9 审计 REJECT（非缺口，producer 自检闭环 + 构造性消费已保证）

### 事实

- P64 闭环（方案：vf-design 移植，方案 B 完整闭环）在**生产侧**完整：新 stage `TilingVfDesignStage`（A5 门控、A2/A3 自跳过）+ fork-join 挂点（split→vf-design→buffer-kernel）+ buffer-kernel 消费 vf_design 作既定前提 + UT 守护（200 passed）。（注：codegen s2-analysis 消费 vf_design **曾越界改动、已回退** d19bdb33，转交 A5 同事——见 P64「权责厘清」+ handoff 文档。）
- **消费侧 4 处未同步扩展**（同 P13 模式：新增设计产物但下游渲染/门/反馈不认）：
  1. docgen SKILL 渲染清单原只 `split/buffer_kernel/precision_perf` 三段 → A5 详设说明书缺 VF 编排章（**本轮已修**：加 `VF编排设计` 节 + 自检项 + Kernel 的 VF_CALL 一致性约束）。
  2. `ascendc-op-design-validate` skill 不认 `vf_design` 段 → vf_design 结构（vf_count 一致性/端口悬挂/函数签名）无专门质量门（**排队**）。
  3. `ascendc-op-design-anchor*` skill 不认 `vf_design` 段 → 无可行性门（**排队**）。
  4. `ascendc-op-design-feedback-selfcheck` SKILL:16/26 段清单只列 `split/buffer_kernel/precision_perf` → vf-design 因上游阻断重跑时 tail_call 调它，但不回验 vf_design 的 acceptance 判据（**排队**）。
- 间接覆盖（为何可排队、不紧急）：vf_design 有 (a) SKILL 内 10 项自检、(b) buffer-kernel 消费期对结构错误的暴露、(c) codegen `.VT.{M}`「无 vf_design 段→不得自行发明、标 clarification」守卫，三重间接兜底。

### 凭证

- `grep vf_design` 于 `.claude/skills/ascendc-op-design-{docgen,validate,anchor*}/` 与 `feedback-selfcheck/`：docgen 本轮已加；validate/anchor 零命中；feedback-selfcheck SKILL:16/26 段清单无 vf_design。
- 生产侧闭环凭证：`design_tree.py:113-118`（fork-join 4 段）、`design_substages.py:1973`（TilingVfDesignStage）、`ascendc-dev-s2-analysis.md:158/226`（codegen 消费）、200 UT 全绿。

### 状态

- ① docgen：本轮已修（+ 真链路证 `test_docgen_renders_vf_design_chapter_a5`，5min13s PASS）。
- **②③④ 经 §2.9（CLAUDE.md「自检闭环 + 门边界，禁止 discover+regenerate」）审计：REJECT，非缺口**：
  - **② validate**：vf_design 质量已由**两层闭环**保证——vf-design SKILL 自检（producer 闭环，line 281-289「自检失败→就地修正直到通过」）+ buffer-kernel 构造性消费 vf_design 派生 VF_CALL（§2.9「构造性保证优先于检查门」）。加 validate 跨段门查 vf_design↔buffer_kernel = 重复 + discover+regenerate（§2.9 禁止）。
  - **③ anchor**：错层（anchor-consistency 是跨模板 TilingKey/workspace/dtype vs VF per-template 结构；anchor-per-template 对质三段硬件 API 断言，VF 寄存器可行性归 buffer-kernel `verifiable_claims`）。
  - **④ feedback-selfcheck**：acceptance 驱动——动态处理任何 issue（含 vf_design），无 vf_design 门喂它即无专项缺口。
  - 故 vf_design **不需下游门**——producer 自检 + 构造性消费已正确保证；诚实记录归 producer（vf-design 自检 in-product + buffer-kernel `verifiable_claims`），不归门。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-19 | P88 记录（事实）：vf_design 生产侧闭环（P64 解），消费侧 4 处缺口（docgen/validate/anchor/feedback-selfcheck）。docgen 本轮已修（加 VF编排设计 节 + 自检）；validate/anchor/feedback 排队。 |
| 2026-07-19 | P88②③④ L3 审计结论（§2.9）：REJECT 非缺口。vf_design 质量由 producer 自检闭环（vf-design）+ 构造性消费（buffer-kernel）保证；加门属 discover+regenerate（违 §2.9）。同步把"自闭环 + workflow/知识分离 + 门边界（禁止 discover+regenerate）"补进 CLAUDE.md §2.8/§2.9。P88 关闭。 |

## P89: "编排型 agent 澄清走 resolve_ambiguity MCP、原生 AskUserQuestion 被 backend 默认 disallow" 硬不变式未写进 CLAUDE.md（已修）

### 事实

- load-bearing 约定：编排型 agent（SpawnAgent 拉起）澄清/反问走 `mcp__engine__resolve_ambiguity`（带 `on_decision` 非交互兜底，`default` 自动选首项），**非**原生 `AskUserQuestion`。`sdk_backend.py:164`/`opencode_backend.py:125` 默认 `disallowed_tools=["Task","AskUserQuestion"]`；各 agent manifest（design-generator/reviewer/requirement-analyst）`allowed_tools` 只列 resolve_ambiguity。
- 该约定**未进 CLAUDE.md**（根 CLAUDE.md + `.claude/rules/` 零提及），只散落在 3 个 agent manifest + 工具描述（`mcp_tools.py`）。
- 后果（§1.2 可维护）：skill 作者不可见此约定 → vf-design SKILL.md 按"普通提问"直觉写 `AskUserQuestion`，与 agent 实际唯一可用工具（resolve_ambiguity）措辞错配；靠 agent manifest 兜底映射，但属隐性知识，新 skill 易重蹈。

### 凭证

- `grep resolve_ambiguity CLAUDE.md .claude/rules/`：零命中。
- `grep resolve_ambiguity .claude/agents/`：3 个 manifest 命中（design-generator.md:35 等）。
- `sdk_backend.py:164`、`opencode_backend.py:125`：`disallowed_tools or ["Task","AskUserQuestion"]`。

### 状态

- 已修（本轮）：CLAUDE.md §四 新增 4.4「Agent 澄清/反问 = resolve_ambiguity MCP（非交互兜底）」。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-19 | P89 记录（事实）+ 已修：CLAUDE.md §4.4 落约定（编排型 agent 澄清走 resolve_ambiguity，原生 AskUserQuestion 被 disallow，skill 文档"AskUserQuestion"是 TUI 即插即用语境自然语言）。消解 skill 作者不可见导致的措辞错配。 |

## P90: vf-design 真实链路验证缺口——§3.9 ST 守护缺失（已修）+ 全闭环 heavy_llm e2e 待跑（未跑，§3.11 用户决策）

### 事实

- vf-design 移植后**真实链路验证有两层缺口**：
  1. **§3.9 ST 守护缺失**（skill 投递层）：`test_skill_invocation_dual_backend.py` 原只挂 `tiling-split`，未扩 vf-design → vf-design skill 在 claude/opencode 双后端的投递零真实测试守护。**本轮已修**：重构为 `(split, vf-design) × (claude, opencode)` 四组合参数化（production guard 验 vf-design A5 门控产 SpawnAgent、transcript methodology markers 验双后端真注入）。
  2. **全闭环 heavy_llm e2e 从未跑**（设计→codegen 端到端层）：vf-design 产出 → buffer-kernel 消费 → codegen `.VT.{M}` → docgen 渲染 VF 章，至今仅 UT(结构) + 代码阅读(契约) 验证，未用真 LLM 端到端跑过。**未跑，待用户决策**（§3.11：heavy_llm 不默认跑，特性交付/合并前由用户在关键节点决策跑一次）。
- 既有 heavy_llm 设计 pipeline e2e（`test_design_tui_selfclosure.py` / `test_design_docgen_tui_selfclosure.py`）均未覆盖 A5/vf-design；§3.11 合并优先——沿用既有 design pipeline heavy 重跑（A5 种子），非新增独立 heavy。

### 凭证

- ST 守护：`tests/st/test_skill_invocation_dual_backend.py` 重构后 collect 4 用例（split-claude/split-opencode/vf-design-claude/vf-design-opencode）；production guard（非 LLM）split+vf-design 双过；真 LLM 部分按 §3.6 默认套件跑（非 heavy_llm，秒级单 spawn）。
- heavy e2e：`grep vf.design|\.VT\. tests/st/` → 零命中（全闭环 e2e 不存在）。

### 状态

- ① ST 守护：本轮已修。
- ② heavy_llm e2e（分两层，§3.11）：
  - **Option A（skill 自闭环层）已跑通**（2026-07-19，用户确认后跑）：vf-design producer 自闭环（`test_vfdesign_tui_selfclosure`，A5 RmsNorm 种子，9min20s，PASS，产出合法 `tiling_vf_design.json`：vf_count≥1 + vfs[] 含 function_signature/interface_params）+ docgen A5 渲染（`test_docgen_renders_vf_design_chapter_a5`，5min13s，PASS，文档含「VF编排」章 + VF 函数名）。证 vf-design 产出 + docgen 渲染（P88①）真链路。
  - **Option B（全 P64 闭环 incl codegen）仍开放**：buffer-kernel 消费 vf_design（VF_CALL）+ codegen `.VT.{M}` 的真 LLM 端到端证明未跑（仅有 UT + 代码阅读覆盖）。交付/合并前由用户决策跑一次 fuller 闭环 e2e。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-19 | P90 记录（事实）：vf-design 真实链路验证两层缺口——①§3.9 ST 守护（本轮已修，dual-backend 四组合参数化）②全闭环 heavy_llm e2e（未跑，待用户决策，§3.11）。 |
| 2026-07-19 | P90② Option A 已跑通（用户确认）：vf-design producer 自闭环 + docgen A5 渲染双 heavy 绿（9min20s + 5min13s）。证 vf-design 产出 + docgen 渲染真链路。Option B（codegen `.VT` 全闭环）仍开放，交付前决策。 |

## P91: CR1 拍平 general_design.json 时遗弃了 `unique_design_points`——6 个 skill 仍在读一个生产者不再写、schema 不再含的字段（R7/R8 概设独有设计点吸收机制静默失效）

### 事实

- CR1（commit b69ca1d9，P87）把 `general_design.json` 的 `sections` 容器拍平、提 4 个 CR1 字段到顶层 required_keys。但原住在 `sections` 内的 `unique_design_points` **未被提升、未被迁移——直接遗弃**：
  - 生产者（`ascendc-op-general-design/SKILL.md`）CR1 后**不再写** `unique_design_points`。
  - schema（`general_design.json`）CR1 后**不再含** `unique_design_points`（required_keys = 4 CR1 字段 + 可选 gradient_formula/narrative，零 unique_design_points）。
- 但 **6 个下游 skill 仍读** `general_design.json.unique_design_points` 做 R7/R8「概设独有设计点吸收 → inherited_design_points」：
  - `tiling-split` / `tiling-buffer-kernel` / `tiling-precision-perf`（SKILL + schema）
  - `design-validate` / `general-design-review`（SKILL + reviewed schema）
  - `tiling-vf-design`（本轮新增，R1 照搬 sibling 写法）
- 后果：6 skill 的 inherited_design_points 吸收机制**静默失效**——读到空、回退空数组。feature 形同虚设但不报错（既不 halt 也不进 known_issues），属 §1.2「可诊断」违例（错误被静默吞掉）。
- 根因属 CR1，**非本轮引入**；本轮 vf-design 只是照搬 sibling 惯例受波及（未比 sibling 做得更差）。P87 只记了 4 字段拍平，**未记 unique_design_points 被顺带遗弃**。

### 凭证

- `grep unique_design_points .claude/skills/ascendc-op-general-design/`：零命中（生产者 + schema 均不再含）。
- `grep -rln unique_design_points .claude/skills/`：6 文件命中（split/buffer-kernel/precision-perf 的 SKILL+schema、design-validate SKILL、general-design-review SKILL+schema、vf-design SKILL+schema）。
- P87（06-problems.md:2466）变更记录未提 unique_design_points 去向。

### 状态

- **已解决（2026-07-20，方案 B 铲除）**。L3 决策：CR1 已让 4 个结构化字段（`split_axis_priority`/`tiling_data`/`loop_framework`/`buffer_eval`）成为权威单源，概设的详设级内容应落进这 4 字段（CR1 就地补）而非游离成"独有设计点"再让下游吸收。故 R7/R8「概设独有点 → inherited_design_points」是 CR1 之前的冗余旁路（§2.5 双通路、§2.9 discover+regenerate），应彻底铲除而非复活（A 案否决）。
- 已铲除范围（全仓 grep `unique_design_points`/`inherited_design_points`/`GV8-B`/`point_ref`/`独有设计点` 零机制残留，仅 UT 留 P91 迁移注释交代原因）：
  - **B 组**：4 tiling skill（split/buffer-kernel/precision-perf/vf-design）SKILL 移除 R7/R8/R4/R1 吸收规则 + inputs/step/self-check 引用；4 schema 移除 `inherited_design_points` 描述与 example。
  - **A 组**：general-design-review SKILL 的 CR3 从「分级 + 独有点标注」收敛为「只判定分级」（删 3b/4b 标注块、step4 标题、self-check、example cr3 块、review_summary 描述）；reviewed schema 移除 `unique_design_points` 描述与 example。
  - **C 组**：design-validate SKILL 移除 GV8-B（用途模式表、输入、GV8 伞描述、GV8-B 规则块、stage 映射、all/tiling 步骤与 self-check）；GV8 收敛为仅 GV8-A。
  - **D 组**：`design_substages.py` validate `input_contract.requires` + `_upstream_inputs` 移除 `general_design`（GV8-B 唯一消费者，死输入）；`general_design.json` narrative 描述、`section_mapping_convention.md`、docgen SKILL 同步去"独有设计点吸收"措辞；`test_design_schemas.py` 删 `TestTilingInheritedDesignPoints`；`test_design_substages.py` 两处断言改为「validate 不再 require/物化 general_design」。
- 验证：design 全量 UT 230 passed（test_design_schemas + test_design_substages + test_tiling_forkjoin + test_context_chain_e2e + test_fail_strategy + test_design_artifacts_reinjection）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-19 | P91 记录（事实）：CR1（b69ca1d9）拍平 general_design.json 时遗弃 unique_design_points——生产者不再写、schema 不再含，但 6 个 skill（split/buffer-kernel/precision-perf/design-validate/general-design-review/vf-design）仍读，R7/R8 inherited_design_points 吸收机制静默失效。根因 CR1、非本轮引入；vf-design 照搬 sibling 受波及。排队待 L3 决策（A 复活 vs B 铲除）。 |
| 2026-07-20 | P91 解决（方案 B 铲除）：CR1 结构化字段权威化后，R7/R8 独有点吸收是冗余旁路（§2.5/§2.9），彻底铲除而非复活。A/B/C/D 四组共改 6 skill SKILL + 5 schema + design_substages.py + 3 文档（general_design.json/section_mapping_convention.md/docgen SKILL）+ 2 test，全仓 grep 零机制残留，design UT 230 passed。 |

## P92: entry 把运行时填充的 npu_id 声明为硬 `provides` → batch 模式（npu_id=None 合法）误报 WARN；runner "reached max iterations" WARN 打印 provides 全集而非真正缺失字段，误导归因

### 事实

- **P92-a（entry 契约越界）**：`entry.py` 的 `output_contract.provides` 含 `npu_id`，即声明「entry 担保 npu_id 非 None」。但 `npu_id` 是**运行时填充字段**——`state.py:83-84` 明确 `npu_id: int | None = None`，**None 是合法语义值**（=「不硬钉卡，由 card_pool 运行时分配」），int=硬钉某卡（card_context skip pool）。batch 模式下 `batch_runner.py:244` `tr["npu_id"] = task_item.get("npu_id")` **总是 set 这个 key**（值可能 None）。于是 `entry.py:113` `npu_id=tr.get("npu_id", 0)` 撞 `dict.get` 语义——key 在、值 None 时返回 **None**（不走 default 0）→ `state.npu_id=None` → `has_all(provides)`（判据 `is None`）失败 → `default_max_iterations=1` 跑到 ceiling → 误报 WARN「reached max iterations without satisfying output_contract」。批跑 5 算子全中。
- **P92-b（runner WARN 文案误导）**：`runner.py:373` 的 WARN 打印 `{output_contract.provides}`（**全集 repr**，6 元素），而非真正缺失的字段列表。真正缺失的 `missing` 在 `runner.py:346` 算了，但只进 `_iteration_reason`（下一轮 iteration_start 日志），**没进 WARN 文案**。于是用户看到「6 个字段都缺」的错觉——本次批跑就被它误导去查 manifest 是不是漏配，实际 npu_id 本就不该由用户传（运行时分配）。
- 两层叠加：P92-a 让 entry 必然误报，P92-b 让误报看起来像「全配置崩盘」。属 §1.2「可诊断」违例——信号失真，狼来了。

### 凭证

- `entry.py:38`（`"npu_id"` in provides）、`entry.py:113`（`tr.get("npu_id", 0)`）。
- `state.py:83-84`（`npu_id: int | None = None`，注释 None=用 card_pool / int=hard-pin skip pool）。
- `batch_runner.py:244`（`tr["npu_id"] = task_item.get("npu_id")`，batch 总 set key）。
- `runner.py:373`（`{output_contract.provides}` 全集）、`runner.py:346-348`（missing 局部，只进 _iteration_reason）。
- 实跑：batch `20260720-104711-bf84a2`（5 算子），entry stage 5/5 WARN `[partial]`；logs/batch_20260720_184658.log。
- 注：本次批跑 5/5 FAIL（exit 65）的真凶是 requirement agent 的 LLM 网关 401（Invalid token），与 P92 无关、独立线。

### 状态

- **已解决（2026-07-20，方案 C+D，见 65-entry-npu-id-warn-contract-impl.md）**。
- C（P92-a）：`npu_id` 从 entry `provides` 降到 `optional_provides`（与 target_repo/requirement_path 同列，复用 entry.py:42-49 已有机制）——entry 不再为运行时字段做非 None 担保，has_all 不查它，WARN 消失。`entry.py:113` 不动（batch 透传 None 合法 / single-op default 0 合法，非 bug）。
- D（P92-b）：抽 module-level `_unsatisfied_contract_fields(state, provides)` helper（`runner.py:346` 与 `:370` 共用单一源），WARN 文案 `{provides}` → `{missing}`，精准列缺失字段。
- 否决 A（`tr.get("npu_id") or 0`）：会把 None→0，card_context 当硬钉卡 0（skip pool），5 并发算子全抢卡 0 → 卡分配回归/并发崩。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-20 | P92 记录（事实）：batch 20260720-104711-bf84a2 5/5 entry WARN，根因 entry 把运行时字段 npu_id 声明硬 provides（None 合法语义冲突）+ runner WARN 文案打 provides 全集而非 missing。与 401 FAIL 独立。 |
| 2026-07-20 | P92 解决（方案 C+D）：entry npu_id provides→optional_provides；runner 抽 _unsatisfied_contract_fields helper + WARN 文案改 missing。5 新 UT 守护（entry 3 + runner 2），orchestration UT 1351 passed。 |

## P93: 设计子阶段 infra 错误未分类传导——网关 400「价格未配置」+ spawn timed out 烧 buffer-kernel 3 轮，missing_artifact / iteration reason / halt 文案三重误报（step-27 设计子阶段 DEFER 的反例）

### 事实

- **P93-a（外部根因）**：run `20260720-095303-413565`（self_evolve_op，算子 moe_re_routing，A2/Membase，4 模板 T1–T4）在 detailed-design/buffer-kernel 阶段失败、`fail_strategy=halt` 终止管线。T4 buffer-kernel 成功；T1/T2/T3 三模板的 `tiling_buffer_kernel.json` 未产出。第 2/3 轮 agent transcript 逐字记录 LLM 网关（`http://192.168.0.212:8082/v1/messages`，new-api/one-api）返回：`APIError: 模型 GLM-5.2 的价格未配置 ... statusCode: 400, isRetryable: False`。即外部 LLM 网关的 GLM-5.2 价格配置在管线运行中途（约 19:12）失效——T4（18:15–18:26 完成）在失效前跑完，T1/T2/T3 第 1 轮（18:12–19:12）跨越失效点被掐断。
- **P93-b（第 1 轮 60 分钟硬切）**：T1/T2/T3 第 1 轮 buffer-kernel spawn 后正常工作过（产出 `tiling_current_template.json` 等中间文件，证明 cwd 正确、agent 能写盘），但跑了约 3630s（三者 elapsed 几乎完全相等：3632050/3631463/3630813 ms）后被 `opencode_backend.py:108 message_timeout=3600.0` 硬切，except 路径报 `spawn failed: timed out`。即第 1 轮并非「任务慢」，而是中途网关开始持续返回 400 后请求不再推进、耗满 3600s 硬墙。
- **P93-c（infra 分类 markers 不覆盖）**：`_build_result`（`base_backend.py:241-285`）crashed 路径会自动 `_classify_error_type(crash_reason)`（line 32-33），但 step-27 A-1 的 `_INFRA_ERROR_MARKERS` 仅含 `No available channel` / `Usage limit reached` / `API Error: 401` / `API Error: 403`。本次的 `"timed out"`（P93-b）与「价格未配置」/`price not configured`（P93-a）均不匹配 → `error_type=None` → 被判逻辑失败（非 infra）。
- **P93-d（设计子阶段不消费 error_type = step-27 DEFER）**：step-27（`27-infra-error-classification-impl.md`「范围边界」）明确把「设计子阶段（template-division/tiling/integrate/docgen/validate）的 stage 侧 infra 接线 = DEFER」，理由是无 sticky 熔断器、resume 天然重跑、不会永久卡死。故 buffer-kernel（`_DesignSubstage`）的 transition 不看 `agent_result.error_type`，infra 错误与逻辑失败同走 missing_artifact 路径 → 烧满 3 轮 iteration 预算。
- **P93-e（missing_artifact 误报「写错目录」）**：`_missing_artifact_error`（`design_substages.py:674-714`）先用 `_harvest_relocation_evidence(transcript,...)` 查 Write/Edit 证据；本次 transcript 里只有 APIError、无任何 Write 调用 → 返回 None → 走通用文案「产物 tiling_buffer_kernel.json 未在正确目录找到 ... 必须以相对路径写入当前工作目录」。该文案经 `user_feedback` 进下一轮 prompt（design-halt-diagnostics 决策5 已确认反馈通道本身有效），把「agent 被 infra 错误掐断、根本没机会写」误报成「agent 写错了路径」，直接误导下一轮 agent 去修路径（注定无效）。
- **P93-f（iteration reason 误归类）**：run.log 把 buffer-kernel 第 2/3 轮标为 `iteration 2/3 (quality check not satisfied)`——pipeline-observability P7 的 iteration reason 三分类（`contract unsatisfied` / `quality check not satisfied` / `agent continuing`）无 infra 类，spawn timed out / API 400 被归到「quality check not satisfied」，误导归因到 agent 质量。
- 三重误报（e/f + halt 文案）叠加：本次 triage 一度被「写错目录」+「quality check not satisfied」带偏去找 agent 的锅，实际真凶是外部 LLM 网关价格配置。属 §1.2「可诊断」违例——外部基础设施故障被框架多层面误报为 agent 自身质量问题。
- **旁证（网关类错误反复出现）**：P92 凭证已记录同日另一批跑（`20260720-104711-bf84a2`）requirement agent 撞 LLM 网关 401（Invalid token）致 5/5 FAIL。网关类配置/鉴权错误（400 价格未配置 / 401 Invalid token）在外部 LLM 网关上反复出现。

### 凭证

- run `20260720-095303-413565`：`report.md`/`report.json`（T1–T4 buffer-kernel 状态）、`run.log`（line 129–181：spawn timed out + missing_artifact WARN + ForkJoin halt）、`agents/ascendc-design-generator-T{1,2,3}-{02,03}.jsonl`（6 条 APIError「价格未配置」400，isRetryable=False；全量 error 字段仅此一类，已排除 429/网络）、`PROVENANCE.json`（agent_backend=opencode，base_url 192.168.0.212:3000，网关 8082）。
- `capabilities/agent/opencode_backend.py:108`（`message_timeout=3600.0`）、`:332-376`（transcript 写入 + `_message_error` + except `_build_result(crashed=True, crash_reason=str(e))`）。
- `capabilities/agent/base_backend.py:241-285`（`_build_result`，line 32-33 crashed → `_classify_error_type(crash_reason)`）、`backend.py:30`（`AgentResult.error_type`）。
- step-27 `_INFRA_ERROR_MARKERS` + 「范围边界：设计子阶段 infra 接线 = DEFER」。
- `orchestration/stages/design_substages.py:674-714`（`_missing_artifact_error`）、`:693`（`_harvest_relocation_evidence` 返回 None → 通用文案）。
- `runner.py` iteration reason（pipeline-observability P7 三分类，无 infra 类）。

### 状态

- **框架侧已解决（2026-07-21，step-69 层1/2/3 + P94）**。外部根因（网关 GLM-5.2 价格配置）不在框架职责（[[external-infra-not-framework-responsibility]]）。
- 层1（commit `f0d6a805`）：`_INFRA_ERROR_MARKERS` 加 `timed out`/`price not configured`/`价格未配置`/`Invalid token` → 这两类 infra 错误不再落入逻辑失败默认分支。
- 层2：`_DesignSubstage` infra 感知——`_read_disk_artifacts` 在 `agent_result.error_type=="infra"` 时改报 infra（不写误导性 user_feedback）+ `actions()` infra 短路（`return []` 终止迭代，不烧 3 轮）。**收窄** step-27 DEFER（补 infra 感知，保留「无熔断器/resume 重跑」内核）。
- 层3：runner iteration reason 加 `infrastructure error` 第 4 类，不再误归 `quality check not satisfied`。
- 注：第 1 轮 60 分钟空等的「1h 空烧」根因（MCP hang + `message_timeout=3600`）由 main 的 P-BC3 commit（`bb9b182e`）keepalive + hard-timeout watchdog 修复；本步层1 把超时判 infra + 层2 短路，使超时后不再重试。
- 产权关系：与 step-27（infra 分类 + 设计子阶段 DEFER 收窄）、step-57（429 marker 扩充先例）、design-halt-diagnostics 决策5（missing_artifact 反馈通道）、pipeline-observability P7（iteration reason 扩第 4 类）同源/相邻。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-20 | P93 记录（事实）：run 20260720-095303-413565 buffer-kernel T1/T2/T3 失败，外部 LLM 网关 GLM-5.2 价格未配置（400 isRetryable=False）+ spawn timed out（3600s 硬切）；markers 不覆盖 → error_type=None → step-27 DEFER 设计子阶段不消费 → 烧 3 轮 + missing_artifact / iteration reason / halt 文案三重误报。 |

## P94: buffer-kernel crash 轮 transcript 被 next iteration 覆盖——失败轮取证证据丢失（独立观察）

### 事实

- run `20260720-095303-413565` 的 `agents/` 归档中，`ascendc-design-generator-T{1,2,3}-01.jsonl` 的实际内容是 **split 阶段**（turn1 prompt「推导单模板切分」、末轮总结「tiling_split.json — 切分段产物」），而非 buffer-kernel。buffer-kernel 第 1 轮（iteration 1/3，18:12–18:13 spawn）的 transcript 在归档里缺失——现存的 buffer-kernel transcript 是第 2/3 轮（`-02`/`-03`，prompt 带「用户反馈：写错目录」）。
- 推断（待 L3 定位机制）：transcript 文件名 = `agents/<agent>-<branch_label>-<seq>.jsonl`，seq 按 (agent, branch_label) 递增；split 占 `-01`，buffer-kernel 第 1 轮本应占 `-02`，但该轮 spawn 被 message_timeout 硬切（P93-b）、transcript 已 `_open_transcript` 打开（truncate）却未来得及写 record，第 2 轮 `_open_transcript` 再次以 `-02` 打开并 truncate → 第 1 轮残留被覆盖。即 crash 轮 transcript 落盘与下一轮文件打开之间存在覆盖竞态。

### 凭证

- `agents/ascendc-design-generator-T2-01.jsonl`（154KB，内容为 split 阶段，turn1「推导单模板切分」）、`-02.jsonl`/`-03.jsonl`（各 7KB，buffer-kernel 第 2/3 轮，turn2 APIError）。
- `events.jsonl`：每个 transcript 路径在 spawn_context 中仅出现 1 次（16 文件 = 16 spawn）；buffer-kernel 第 1 轮（T1/T2/T3）的 spawn_context transcript 字段指向的文件，实际内容是 split。
- `capabilities/agent/opencode_backend.py:335`（`_open_transcript`）、`:347-350`（record 写入在 try 内、依赖 message 完成）。

### 状态

- **已解决（2026-07-21，step-69 P94）**。机制已确认（**非**"被 next iteration 覆盖"）：`_open_transcript`（`opencode_backend.py:530`）在 blocking message POST（`:450 _post_message_watched`）**之后**才调，故 message POST crash（如 timed out）时 `transcript=None`、第 1 轮**根本没有 transcript 文件**——这解释了 `-01` 号落到 split、第 1 轮无文件的观察（不是覆盖竞态，是 `_open_transcript` 没执行）。
- 修复：opencode_backend spawn 的 except 路径，若 `transcript is None` 当场 `_open_transcript` 补开 + 写一条 `{type:"crash", error:str(e)}` record，让失败轮留下"为何崩溃"的证据；native session 兜底见 step-67。
- 产权关系：与 opencode-artifact-provenance（step-66，P1/P2 schema+turn 已闭环）、run-diagnostic-provenance（step-67，落盘）不同——本项是「crash 轮 transcript 根本未创建」，落盘之前的缺口，现已补。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-20 | P94 记录（事实+推断）：buffer-kernel crash 轮（第 1 轮）transcript 缺失，`-01` 号文件实为 split 内容；疑似 spawn timed out 轮 transcript 被 next iteration `_open_transcript` truncate 覆盖。机制待 L3 确认。 |

## P95: cannbench_eval 子进程 PYTHONPATH 缺 cann_bench 包目录——`import cann_bench` 失败致 eval 全 0（e2e 评测失败链 A）

### 事实

- run `20260722-022209-e08f46`（self_evolve_op，算子 exp，cann-bench L1）codegen 全程跑完，cannbench_eval 阶段 `scan_interfaces()` 抛 `ImportError: No module named 'cann_bench'`、`torch.ops.cann_bench 中无算子`，eval `pass_rate=0.00`。
- **根因（确定性 stage 配置缺陷，非 transient / 非用户环境）**：`cannbench_eval.py` 构造 kernel_eval 子进程 PYTHONPATH 时只加了 `_tn_usercustomize_dir : per_op_python : kernel_eval_src(repo_root/src)`，**漏了 cann_bench 包所在目录**。而 `kernel_eval` 的 `scan_interfaces()`（`package_manager.py`）硬 `import cann_bench`；cann_bench 包物理上在 `examples/<ex>/cann_bench/`，**既不在 repo_root 顶层也不在 src/**。eval 子进程 `cwd=repo_root`（`cannbench_eval.py:221`）+ PYTHONPATH 不含 example 根 → `import cann_bench` 必 ModuleNotFoundError → scan 空 → eval 全 0。
- **三铁证**：(1) `cannbench_eval.py:170-183`（修复前）PYTHONPATH 仅 `_tn_usercustomize/per_op_python/kernel_eval_src`；(2) 实证 cwd=repo_root `import cann_bench` 失败、cwd=example 成功；(3) 注释 `cannbench_eval.py:159-170` 自己写「kernel_eval imports cann_bench」，却只配了 kernel_eval 模块路径、漏了 cann_bench 包。
- **归属判定（§1.2 四把尺子）**：框架缺陷——stage 接管 eval 子进程 env 却没配齐 cann_bench 包路径。**非用户环境**（PYTHONPATH 是 stage 内部构造、用户无配置项介入）、**非 transient**（确定性，任何环境复现）。修复落在职责正确的层（stage env 构造），反证归属。

### 凭证

- run `20260722-022209-e08f46`：`run.log`（cannbench_eval ImportError + pass_rate=0.00）、`events.jsonl`。
- `orchestration/stages/cannbench_eval.py:170-183`（修复前 PYTHONPATH 构造）、`:221`（cwd=repo_root）、`:159-170`（注释承认 import cann_bench）。
- 实证：cwd=repo_root `import cann_bench` → ModuleNotFoundError；cwd=examples/aclnn_launch_example → 成功。

### 状态

- **已解决（2026-07-22，commit `6fec78c5`，详见 `70-cannbench-eval-discovery-impl.md`）**。
- 新增 `_resolve_cann_bench_pkg_root(source_dir, repo_root)`：从 source_dir 向上探测含 `cann_bench/` 的祖先（限 repo_root 内）定位 example 根；PYTHONPATH 构造从双分支重构成统一列表，补入 cann_bench 包目录。
- 6 个 UT 守护（`tests/ut/orchestration/test_cannbench_eval.py::TestCannBenchPkgRootOnPythonpath`，10/10 passed）：helper 4 边界 + PYTHONPATH 注入/缺省契约。
- 产权关系：与 [[P96]]（_C 不收录新算子）、[[P97]]（operators 纳入）共同构成 e2e cann-bench 评测三层失败链（A→B→C）。方案见 `70-cannbench-eval-discovery-analysis.md`。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-22 | P95 记录+解决：cannbench_eval PYTHONPATH 缺 cann_bench 包目录致 eval 全 0；commit `6fec78c5` 加 `_resolve_cann_bench_pkg_root` + PYTHONPATH 补包目录 + 6 UT。 |

## P96: cann_bench/_C.abi3.so 不收录新增算子——CMake INTERNAL cache/GLOB 增量陷阱 + workflow 无 _C 重建环节（e2e 评测失败链 B）

### 事实

- run `20260722-022209-e08f46` 修 [[P95]] 后 eval 不再 ModuleNotFoundError，但 scan 仍发现不到 exp（发现 add/sqrt，`torch.ops.cann_bench.exp` MISSING），eval 对 exp 仍 0（「未匹配到 tasks 中的算子」）。
- **根因（CMake 构建缓存陷阱 + 框架流程缺陷复合，非 transient / 非环境 / 非 codegen）**：
  - cann-bench 算子发现 = `cann_bench/_C.abi3.so`（各 op_plugin 的 `TORCH_LIBRARY_FRAGMENT` 编译进去）+ `cann_bench/__init__.py` wrapper。`_C` 由 `PLUGIN_TARGET=cann_bench_plugin_obj`（`ALL_PLUGIN_SRCS` 的 OBJECT 库）link 而成。
  - `ALL_PLUGIN_SRCS` 是 CMake `INTERNAL` cache 变量（`CMakeCache.txt: ALL_PLUGIN_SRCS:INTERNAL=...`），由 `file(GLOB)` 收集算子目录 + 各 op `register_aclnn_plugin` 累积。**新增算子后增量 build 不重新求值该 cache**（CMake 经典陷阱：INTERNAL cache + GLOB 无 `CONFIGURE_DEPENDS`）→ PLUGIN_TARGET 永远只含首次 configure 时的算子（add/sqrt）→ exp 进不了 `_C`。
  - 实证铁证：`cann_bench_plugin_obj` 只编 `add_plugin.cpp`/`sqrt_plugin.cpp`；`_C` link 只用这两个 .o；`CMakeCache ALL_PLUGIN_SRCS` 只有 add/sqrt。而 `exp/CMakeLists.txt` 正确（含 `register_aclnn_plugin`，与 add 完全一致）→ 排除 codegen 产物缺陷。
  - **框架侧缺口**：workflow 全程无 stage 重建 `cann_bench/_C.abi3.so`——deploy 编算子部署到 per-op opp、adapt rebuild opp（`cannbench_adapt.py:261`，重建 opp 非 _C）、eval `--skip-install` 扫旧 `_C`；run.log 全程无 `build_run.sh`/`build_wheel.sh` 执行记录。
- **修复实证**：clean rebuild（`rm -rf build_py && bash build.sh`）→ `torch.ops.cann_bench.exp` 从 MISSING 变 EXISTS（exp 进 `_C`）。证明根因即 cache/GLOB 陷阱，修复即 clean rebuild。
- **归属**：cann-bench 构建陷阱（cache/GLOB）+ 框架流程缺陷（无 _C 重建环节）。**非 transient**（重跑 adapt 不解——adapt 不重建 _C）。

### 凭证

- run `20260722-022209-e08f46`：`run.log`（无 build_run.sh/build_wheel.sh 执行记录）、`events.jsonl`。
- cann-bench `examples/aclnn_launch_example/CMakeLists.txt:37/199-213`（ALL_PLUGIN_SRCS cache + PLUGIN_TARGET + _C link）、`csrc/ops/CMakeLists.txt`（`file(GLOB ...)` 无 CONFIGURE_DEPENDS）、`csrc/ops/exp/CMakeLists.txt`（register_aclnn_plugin 正确，与 add 一致）。
- `build_py/CMakeCache.txt`（`ALL_PLUGIN_SRCS:INTERNAL` 仅 add/sqrt）、`build_py/CMakeFiles/cann_bench_plugin_obj.dir/build.make`（仅 add/sqrt plugin）、`_C.dir/link.txt`（仅 add/sqrt .o）。
- 实证：clean rebuild 前 `exp` MISSING、后 `exp` EXISTS。
- `orchestration/stages/cannbench_adapt.py:261`（rebuild opp 非 _C）、`cannbench_eval.py:213-226`（--skip-install + cwd=repo_root）。

### 状态

- **框架根治已实施（2026-07-22，commit `4594229c`，方案 1）**。
- cannbench_adapt transition 统一一次 `Deployer.deploy(clean_build=True)`：agent 改 glue OR schema rename → clean rebuild（清 `variant.clean_dirs` = `["build_py","build","*.egg-info"]` 强制 CMake reconfigure 让新算子进 `_C`）+ 重 build wheel + redeploy per-op。
- 短期/手动（仍可用）：`rm -rf build_py && bash build.sh` clean rebuild（已实证 exp 进 `_C`）。
- cann-bench 侧（外部只读依赖，仅提建议）：`file(GLOB ... CONFIGURE_DEPENDS)` 或 `ALL_PLUGIN_SRCS` 不用 cache。
- 产权关系：[[P95]]（A，已修）→ 本条（B）→ [[P97]]（C，operators 纳入）三层链。方案见 `70-cannbench-eval-discovery-analysis.md`。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-22 | P96 记录（根因实证）：`_C` 不收录新算子 = CMake INTERNAL cache/GLOB 增量陷阱 + workflow 无 _C 重建环节；clean rebuild 实证 exp 进 _C。框架根治（强制 clean rebuild _C）待做。 |
| 2026-07-22 | P96 解决（方案 1，commit `4594229c`）：cannbench_adapt transition 统一 `Deployer.deploy(clean_build=True)`，清 `variant.clean_dirs`（build_py 等）强制 reconfigure 让新算子进 `_C` + redeploy per-op。BuildVariant.clean_dirs + profile schema + 5 UT。 |

## P97: kernel_eval 未把已注册算子纳入 operators——scan 发现 exp 但 `operators:[]`（e2e 评测失败链 C，待查）

### 事实

- run `20260722-022209-e08f46` 修 [[P95]]+[[P96]]（clean rebuild `_C`）后，`torch.ops.cann_bench.exp` EXISTS（scan 能发现 exp），但 eval 报告 `operators: []`、评测算子数 0、pass_rate 0.00%——scan 发现了 exp，却没被 kernel_eval 纳入评测。
- **根因已定位（2026-07-22）**：eval 子进程加载 **per-op 部署包**（`per-op/exp/python/cann_bench`，PYTHONPATH `per_op_python` 优先于 example 源）。per-op `_C` 含 exp（`torch.ops.cann_bench.exp` EXISTS），但 per-op `__init__.py` wrapper 只有 add/sqrt —— adapt 改 example 源 glue、不 redeploy per-op → per-op 包 deploy 时固化、没 exp wrapper。scan_interfaces 第 1 路 `dir(cann_bench)` 无 exp（wrapper 缺）→ 第 2 路 `for interface in interfaces` 不独立遍历 torch.ops → scan 发现不到 exp → match_operators 空 → `operators:[]`。
- **实证**：加 exp wrapper 到 per-op `__init__.py` 后 scan 发现 exp（6 接口）+ match（1 算子 20 用例）。**核心**：发现就绪（_C 含新算子 + wrapper）必须保证在 eval 加载的 per-op 包上，而非 example 源；adapt 改 example 不 redeploy per-op 是断裂点（与 [[P96]] 同源）。
- **前置依赖**：[[P95]]（import 链路）+ [[P96]]（exp 进 _C）已解决，本条是 B 之后的独立第三层，不阻塞 A/B 的固化。

### 凭证

- cann-bench `reports/exp_eval_20260722_202137.json`（`operators: []`）、`.md`（评测算子数 0）。
- `kernel_eval/data/package_manager.py` scan_interfaces（两路扫描：`dir(cann_bench)` wrapper + `torch.ops.cann_bench`）。
- 实证：[[P96]] clean rebuild 后 `torch.ops.cann_bench.exp` EXISTS，但 eval operators 空。

### 状态

- **根因已定位 + 方案 1+2 已实施（2026-07-22）**。根因：eval 加载 per-op 部署包，adapt 改 example 源 glue 不 redeploy per-op → per-op `__init__.py` 缺新算子 wrapper → scan 发现不到。
- 框架根治（commit `4594229c`，方案 1）：cannbench_adapt transition 统一 `Deployer.deploy(clean_build=True)` clean rebuild + redeploy per-op（含新算子 `_C` + wrapper）。
- 防御（commit `11a5bd73`，方案 2）：cannbench_eval 加载期校验 `len(operators)==0` → 报 infra error（不再静默全 0），兜住方案 1 失败/漏跑。
- 实证：加 exp wrapper 到 per-op 后 eval 发现 exp、1 算子 20 用例（出分取决于 kernel 精度，独立于发现链路）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-22 | P97 记录（待查）：[[P95]]+[[P96]] 修后 scan 发现 exp 但 eval `operators:[]`；根因在 kernel_eval 算子纳入匹配环节，待定位。 |
| 2026-07-22 | P97 根因定位+解决：根因 = eval 加载 per-op 部署包、adapt 改 example 不 redeploy per-op → per-op `__init__.py` 缺 exp wrapper；方案 1（`4594229c`，adapt clean rebuild + redeploy per-op）根治 + 方案 2（`11a5bd73`，cannbench_eval 加载期校验报 infra）防御。 |

## P98: regbase codegen manifest 兜底盲拼 callable_target.symbol——与 op_plugin 实际注册名不符致 deploy smoke 失败（P97 发现链路延伸：devkit deploy 验证点）

### 事实

- run `20260722-143612-b4fa39`（exp 算子，A5 Regbase 路径）在 `cannbench_adapt` 阶段失败，smoke 报：`torch.ops.cann_bench.exp did not resolve: AttributeError("'_OpNamespace' 'cann_bench' object has no attribute 'exp'")`。
- **根因**：exp 的 op_plugin 为避 torch 内置 `exp` 命名冲突，在 `TORCH_LIBRARY_FRAGMENT` 里实际注册成 `npu_exp`（`m.def("npu_exp(...)")`，`.so` 符号为 `npu_exp_npu`/`npu_exp_meta`）。但 regbase codegen 的 manifest 兜底分支（s5 未回传 `codegen_manifest.json` 时）用 `op_name`（exp）盲拼 `callable_target.symbol = torch.ops.cann_bench.exp`，与实际注册名不符。devkit deploy 的 smoke 符号解析探针 `getattr(torch.ops.cann_bench, <symbol>)` 查 `exp` → AttributeError。
- **与 [[P95]]-[[P97]] 的区分**：前者修的是 **cann-bench 评测侧**的发现链路（PYTHONPATH / `_C` 收录 / per-op wrapper）；本条是 **devkit deploy 自己的 smoke 验证门**——它消费 `codegen_manifest.callable_target.symbol` 做可调用性校验，是 P97 修完后才暴露的下一层（manifest.symbol 错位）。run 22:36 启动晚于 P97 三 commit（22:28-22:32），editable install 已指向本仓——即 P97 修完后仍失败。
- **影响范围**：所有走 regbase 路径、且 op_plugin 注册名 ≠ op_name 的算子（codegen 为避 torch 内置名冲突常用 `npu_<name>`）。`symbol` 还被 NPU runner 实际调用消费——盲拼不仅炸 smoke，也会让 runner 调用错符号。

### 凭证

- run `20260722-143612-b4fa39`：`subprocess/smoke.log`（smoke FAIL 原文）、`agents/cannbench-adapt-01.jsonl`（agent 探测 `.so` 符号全为 `npu_exp_*`、读 op_plugin 源确认 `m.def("npu_exp(...)")`）、`state_snapshot.json`（`codegen_manifest._fallback=true`、`callable_target.symbol=torch.ops.cann_bench.exp`）。
- cann-bench `examples/aclnn_launch_example/csrc/ops/exp/`：git status 显示 `D exp/codegen_manifest.json`（manifest 曾存在但未进 s5 artifacts，触发兜底）。

### 状态

- **已解决（2026-07-23）**。根因：regbase manifest 兜底盲拼 symbol，与 op_plugin 实际注册名脱节。
- 主修复：兜底分支从 op_plugin 源解析真实 C++ 注册名构造 symbol（不再盲拼 op_name）；m.def 解析原语集中到 `domain/mdef_parse`（§2.5 唯一通路）。
- 防御：修正 cannbench_adapt 适配 prompt——明确 `manifest.callable_target.symbol` 是 smoke/runner 权威符号、须与 op_plugin `m.def` 注册名一致，消除 agent「发现只靠 dir(cann_bench)、symbol 无关紧要」的系统性误判。
- 验证：新增 `domain.mdef_parse` UT + codegen regbase fallback UT（npu_exp 解析 / 磁盘回退）；全量 orchestration+domain UT 1589 passed、0 回归。e2e 复现（heavy_llm）待用户确认运行。
- 方案见 `71-cannbench-smoke-symbol-drift-analysis.md` / `-impl.md`。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-23 | P98 记录+解决：regbase manifest 兜底盲拼 symbol 与 op_plugin 实际注册名（npu_exp）不符致 deploy smoke AttributeError；主修复（兜底从 op_plugin 解析真实注册名 + m.def 解析集中 domain.mdef_parse）+ 防御（修正 adapt prompt）；UT 1589 passed、0 回归。 |

## P99: deploy install_python 的 pip --target 不覆盖已存在包——redeploy 后 per-op 包残留旧版，eval scan 发现不到新算子（operators=[]）（P97 redeploy 实施缺陷）

### 事实

- run `20260722-143612-b4fa39` 在 P98 修复后 rerun（cannbench_adapt 通过、smoke PASS `torch.ops.cann_bench.npu_exp`），cannbench_eval 仍 `operators=[]`、评测算子数 0、**未调起算子**。
- **根因**：devkit deploy 的 install_python 步骤用 `pip install --target <per_op_python_dir> --force-reinstall`，但 pip `--target` 模式**不覆盖已存在的包文件**（`__init__.py` 等）。cannbench_adapt agent 改的 example 源 `cann_bench/__init__.py`（加 exp wrapper）正确进了 whl，但 redeploy 时 `per_op_python_dir` 已有上次 install 的旧 `cann_bench/`（无 exp wrapper），pip 没覆盖 → per-op 包 `__init__.py` 仍旧版 → eval 的 `scan_interfaces` 第 1 路 `dir(cann_bench)` 无 exp → `operators=[]`。
- **与 [[P97]] 的关系**：P97 方案 1（adapt clean rebuild + redeploy per-op）的实施缺陷——redeploy 命令跑了、exit 0，但 pip `--target` 没真正覆盖 per-op 包。与 [[P98]]（codegen symbol）正交（P98 让 smoke 通过，本条让 eval 能发现算子）。
- **影响范围**：所有 cann-bench 算子 redeploy（adapt 改 glue 后 redeploy per-op）都会触发——per-op 包不更新，eval 发现不到新算子。

### 凭证

- run `20260722-143612-b4fa39`：per-op `__init__.py` mtime `16:02:32`（原始 run 的），rerun 19:18:20 的 install 没更新它；whl 里 `__init__.py` 实含 exp wrapper（打包正确，unzip 实证）。
- devkit deploy install_python 步骤原只清 `__pycache__`（不清 `cann_bench/` 包目录）。

### 状态

- **已解决（2026-07-23）**。根因：pip `--target` 不覆盖 + install_python 没清旧包。
- 修复：install_python 步骤 pip 前清空 `per_op_python_dir` 内容（不只 `__pycache__`，整个 dir 内容：包目录 + dist-info + 文件），让新 whl 干净覆盖。`per_op_python_dir` 是 per-op 隔离的 whl target dir（`_per_op_path`），清空安全。
- 验证：`test_deploy.py` 加 `TestInstallPythonReinstallOverwrite`（3 例）；全量 orchestration+domain UT **1592 passed**、0 回归。e2e 复现（heavy）待用户确认。
- 方案见 `72-cannbench-redeploy-overwrite-analysis.md` / `-impl.md`。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-23 | P99 记录+解决：deploy install_python 的 pip --target 不覆盖已存在包，redeploy 后 per-op 包残留旧版致 eval operators=[]、未调起算子；修复（install_python pip 前清空 per_op_python_dir 内容）+ 3 UT；1592 passed、0 回归。 |

---

## 本批说明（P100–P111）：loopback / iteration 不闭环专项排查

> 来源：2026-07-24 对 `src/ascendc_devkit/orchestration/stages/` 全 18 文件的 loopback/iteration 闭环审计（design 家族主审 + codegen/precision/deploy 三家族并行子 agent；所有 confirmed 项经主 agent 读码复核，不单转述子 agent）。
> 触发：run `20260724-045259-898837`（moe_re_routing，A2）design validate 反复判 blocked（AC0）。
> 性质：均为 **L1 事实记录，不提方案、不排顺序**；逐条 L3（选项/决策）+ L4（实施）后续展开。
> 失败模式分两类：
> - **A 类（loopback 死循环/空转）**：producer 正确产出、门/dispatch 反复重试、**终止信号或关键字段在编排层被结构性丢弃**，重跑 producer 永远修不好（违 §2.9「禁止 discover+regenerate」）。
> - **B 类（静默 false-green）**：门/测量是 no-op 默认 pass、缺陷向前流窜不被察觉（违 §3.7 诚实信号 / §1.2 可诊断）。

### 汇总（事实快照）

| P# | 家族 | file:line | 类 | 严重度 | 路径 | 当前 run 受影响 | 处置（2026-07-24 triage）|
|---|---|---|---|---|---|---|---|
| P100 | design | `design_substages.py:2050` | A | blocker | 全路径 | ✅ 是（AC0） | **已修**（方案73 S，端到端验证） |
| P101 | codegen | `codegen.py:1481-1492`+scheduler | A | blocker | A5 Regbase | 否（A2 Membase） | **跳过**（A5 codegen，归同事） |
| P102 | perf | `perf.py:215`+`runner.py:652` | B | 高 | perf 阶段 | 仅当本 run 含 perf | **deferred**（休眠功能，真实 run 不执行） |
| P103 | precision | `precision_debug_a5.py:605-621` | A | 中（已缓解） | A5 | 否（A2 走 precision_debug.py） | **跳过**（A5 precision） |
| P104 | codegen | `codegen.py:1493-1511` | A 轻 | 中 | A5 Regbase | 否 | **跳过**（A5 codegen） |
| P105 | design | `design_substages.py:1830-1869` | A 轻 | 潜伏 | 全路径 | 间接（被源头修兜住） | **deferred**（潜伏） |
| P106 | precision | `precision_debug_a5.py:772-778` | A 轻 | 中 | A5 | 否 | **跳过**（A5 precision） |
| P107 | precision | `precision_debug_substages.py:1520+` | A 轻 | 低（8 轮兜底） | A3 | 间接 | **待决**（活跃候选） |
| P108 | deploy | `cannbench_adapt.py:190-201` | B | 诊断性 | 线性 | 否 | **待决**（活跃候选） |
| P109 | deploy | `finalize.py:118-121` | B | 诊断性 | 终态 | 否 | **关闭**（非缺陷，write-only 字段无消费者） |
| P110 | design | 同 `:2050` | A | 潜伏 | 全路径 | 否（暂无门查） | **已消解**（随 P100/方案 S） |
| P111 | codegen | `codegen.py:1448/1528` | A | 潜伏 | A5 | 否 | **跳过**（A5 codegen/regbase，潜伏死代码） |

### triage 决策（2026-07-24）

逐条取舍判据（P102 教训）：**先判"活跃路径 vs 潜伏路径"再投入**；A5 家族（codegen + precision）归同事/暂不碰；无消费者的诊断默认非缺陷。

- **已修/消解**：P100（含 P110）。
- **跳过（A5 家族）**：P101、P103、P104、P106、P111——A5 codegen + A5 precision，归同事或暂不投入。
- **deferred（潜伏/休眠）**：P102（perf 休眠功能，真实 run 不执行）、P105（潜伏 shape 3，被源头修兜住）。
- **关闭（非缺陷）**：P109（write-only 诊断字段，无消费者）。
- **待决（活跃非 A5 真候选）**：**P107**（A3 precision candidate_pool 回写无框架校验，precision_debug 跑时触发）、**P108**（cannbench_adapt 重建失败信号截断，线性 deploy 路径）。

本批 12 条 triage 后：1 已修 + 1 消解 + 5 跳过(A5) + 2 deferred(潜伏) + 1 关闭(非缺陷) + **2 待决活跃**（P107/P108）。

---

### P100: tiling 段聚合丢弃 verifiable_claims 顶层兄弟字段 → AC0 判 blocked 死循环（A 类，[[P85]] 的下半段）

#### 事实

- tiling 三段 producer（split/buffer-kernel/precision-perf）按 schema（[[P85]] / 方案62 已把 verifiable_claims 加进 `required_keys`）**正确产出** verifiable_claims（带 `verification=api_checked` + `source_pointer`）；连 AC2 那条"A2 Gather 不可用"的能力误判 producer 也已在源头纠正（per-stage 文件 red_team_ruling/verifiable_claims 多处"前轮能力误判，已纠正"）。
- 但 `_TilingSegmentStage.transition` 聚合时 `tmpl_entry[self.segment_key] = payload.get(self.segment_key)`（`design_substages.py:2050`）**只抽内层 domain 对象**（split/buffer_kernel/precision_perf），**丢弃所有顶层兄弟字段**（verifiable_claims/decisions/key_parameters/self_check_summary）。
- 下游门只读聚合后物化的文件：anchor-per-template 读 `tiling_current_template.json`（SKILL.md:33/40/121 明禁 Glob）、validate GV9-a 读 `tiling_results.json`（SKILL.md:33）——两者 verifiable_claims 均 **0 命中**；而 per-stage 源文件 split:1 / buffer_kernel:3 / precision_perf:4 命中。
- 结果：producer 每轮正确产出，门每轮 grep 0 → 判 AC0 blocked → corrective 回退 producer 重跑 → 再丢 → **结构性死循环**。
- run `20260724-045259-898837` 实证：corrective 跑 3 轮（round1 / corrective1 / corrective2），per-stage 每轮都带 verifiable_claims，聚合物化文件每轮都 0。

#### 凭证

- `src/ascendc_devkit/orchestration/stages/design_substages.py:2048-2054`（单键聚合，唯一丢字段落点）；`:865-870` `_parse_single` 存完整 payload（对比：非段 design stage 不丢字段）。
- 该 run artifacts：per-stage 源 vs 聚合物化文件 verifiable_claims 命中数（1/3/4 vs 0/0/0）。
- `ascendc-op-tiling-split/schema/tiling_split.json:3` `required_keys=["template","split","verifiable_claims"]`（顶层必填）。
- 关联前序：[[P85]] / 方案62 收口了**产出端**（schema）；[[P37]]（37-artifact-location-check）当时写 `tiling_results[template][segment_key]` 单键（为 C1 分支隔离）时 verifiable_claims 尚非 schema 字段。本条是两次工作间的**时序/构造缺口**——产出端通了，聚合 relay 未同步。

#### 影响

- 当前 run blocker（AC0 死循环）。爆炸半径：同机制还丢 key_parameters/self_check_summary（见 [[P110]]）；decisions 经 `_capture_decision_log(state, raw)`（`:2051`）另存进 `state.decision_logs`，未丢。

#### 状态

- **L3 已拍板冻结（方案73 = 方案 S 结构性，含 T1 修正）**：`73-tiling-claims-aggregation-analysis.md`（L3 冻结）+ `73-tiling-claims-aggregation-impl.md`（L4）。方案 S = gate-relevant 设计内容（`verifiable_claims`/`key_parameters`/`kernel_structure`）进 segment（`self_check_summary` **留顶层**：过程元数据，对质原则门不读）+ 给 `ArtifactSpec` 加 `allowed_top_level_keys` 闭合 schema（拒未知顶层键，§1.3 精神）→ 复发面结构性消除（顶层只剩纯簿记/过程元数据，孤儿兄弟在 producer 边界即被拒），聚合 `:2050` 零逻辑改 / gate 零改。UT-A（schema 闭合+白名单纯洁，schema 集合驱动）/ UT-B（段 round-trip 不丢字段）纵深防回退。**已实施（2026-07-24，运行中任务结束后）**——全量 UT 2906 passed/7 skipped/0 failed；闭合对全部 4 段 segment schema 施加（vf_design 仅闭合无重构）；transition 补 `if errors:` enforcement hook（段 stage 原是 6 个 design substage 里唯一缺的，§1.1 实施发现）。heavy_llm ST 3 项全过（604s，真实 LLM：producer 真产段内 claims + anchor 真读段内对质 + AC0 不再误判）。**P100 端到端验证完成**。关联 [[P85]] / [[P37]] / [[P110]]。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P100 记录：tiling 段聚合（design_substages.py:2050）丢 verifiable_claims 顶层兄弟 → AC0 死循环；[[P85]]/方案62 收口产出端后的下半段缺口。 |
| 2026-07-24 | P100 展开 L3+L4（方案73）：推荐方案 N（时称 C，只挪 verifiable_claims 嵌进 segment；聚合 `:2050` 零改 / gate 零改 / 构造性保证），备选方案 R（时称 B，relay 变换）。待用户拍板，未实施。 |
| 2026-07-24 | P100 拍板升级为**方案 S（结构性）**（用户定）：不止挪 verifiable_claims，所有设计内容进 segment + `ArtifactSpec` 加 `allowed_top_level_keys` 闭合 schema（拒未知顶层键）→ 复发面结构性消除；UT-A/UT-B 纵深。L3 冻结、L4 更新，待运行结束实施。 |
| 2026-07-24 | P100 方案 S 细化 **T1**（用户定）：`self_check_summary` **不**进 segment——它是 producer 自检=过程元数据，按对质原则（不信自评）门不读，留顶层白名单即可；只挪 gate-relevant 的 `verifiable_claims`/`key_parameters`/`kernel_structure` 进段。L3/L4 同步更新。 |
| 2026-07-24 | **P100 已实施**（运行中任务结束后）：`ArtifactSpec.allowed_top_level_keys` + `validate_payload` 拒未知键 + `to_prompt_block` 渲染闭合；loader 读新字段；4 段 schema 设闭合（3 段 +claims/key_params 进 segment）；`_TilingSegmentStage.transition` 补 `if errors:` enforcement（实施发现：段 stage 原是唯一缺此 hook 的，6 sibling 里）；:2050 聚合零逻辑改仅注释；3 SKILL.md + checkpoint_convention 同步；heavy_llm ST 对齐新契约。UT-A/UT-B 15 项绿，全量 UT 2906/7skip/0fail。 |
| 2026-07-24 | P100 heavy_llm ST 3 项全过（604s，真实 LLM agent）：producer 真产 `buffer_kernel.verifiable_claims`（段内，闭合 schema 未误拒）；anchor 真读段内 claims 对质（矛盾→AC2 / 一致→pass）；AC0 不再误判。**P100 端到端验证完成**。 |

---

### P101: codegen A5 Regbase VF 精度预验证 retry 无生效终止条件 → 死循环（A 类）

#### 事实

- VF step 失败 → s4 dispatch FAILED 路径 → scheduler `check_retry_exceeded('CK-VF')` 读 `meta.retries.vf_test.used`（limit=2），未超限发 `call_vf_test(is_retry=True)`，超限才发 `vf_exhausted`（设计的 ⚠️-graceful-continue）。
- `meta.retries.vf_test.used` **全仓无写入点**：写 `meta["retries"]` 的唯一函数 `_update_meta_retries`（`codegen.py:361`）只在 `_handle_regbase_failure`（`:1723`）内 `:1746/:1752` 调用；`_handle_regbase_failure` 只从 s2（`:1412/:1416`）与 s5（`:1632`）触发，**s4 dispatch 路径不调用**；scheduler bash 也只读不写 retries。
- 且 s4 `call_vf_test` 分支（`:1481-1492`）**既不写 vf_test.used、也不累加 codegen_et** → 顶部 `et>=10` 兜底（scheduler bash:263）也触不到。
- → `vf_exhausted`（`:1512-1519`）成**死代码**；纯 VF 失败循环无任何生效终止条件（唯一出口：外层 GraphExecutor stagnation 硬停）。

#### 凭证

- `src/ascendc_devkit/orchestration/stages/codegen.py:355/361/1412/1416/1481-1492/1512-1519/1632/1723/1746/1752`。
- `.claude/skills/ascendc-op-dev-coding-regbase/scripts/stage4_scheduler.sh:258-291/323-335`（check_retry_exceeded + dispatch VF 分支）。
- `.claude/agents/ascendc-vf-test-agent.md:28`（全局预算外推给 scheduler）。
- 全仓 grep 确认 `_update_meta_retries` 仅 2 调用点、均在 `_handle_regbase_failure`；bash 无 retries 写入。

#### 影响

- A5 Regbase 算子 VF 函数有修不好的精度/编译 bug 时死循环（A2 Membase 路径不触发）。比 [[P100]] 更狠：P100 至少 stagnation 放行能带 unresolved 前进，P101 连 graceful 前进都没有。

#### 状态

- 待分析（未实施）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P101 记录：codegen A5 VF retry 终止信号（vf_test.used）全仓无写入点 → vf_exhausted 死代码 → 死循环。 |

---

### P102: perf PerformanceGate 是静默 no-op，永远默认 passed → false-green（B 类）

#### 事实

- `PerfStage` 发 `RunGate(gate_name="performance")` 无内联 `gate=`；`runner.py:652` `gate = action.gate or self._gate_registry.get(action.gate_name)`。
- `_gate_registry` 全仓**只在 `runner.py:72` 默认 `{}`**、`graph_executor.py:755` `getattr(t,"_gate_registry",None)`（从无人往 tree 节点设值），**无任何注册调用** → 永远空 → gate=None → `runner.py:661-664` 记 "Gate not found, defaulting to passed"。
- `PerformanceGate.evaluate`（`perf.py:54-143`）整段死代码；stage 永远 passed=true → 调优分支（`if perf_result and not perf_result.passed`）永不进 → 调优 agent 永不 spawn → resolve_condition 当有性能约束时返 `"tuned"` 向前路由（像真调优过一样）。
- 潜在恶化：若有人注册 gate "修"它却没补 `deploy_result` 参数（NPURunner 必需 `runner.py:279/286`）+ 调优后重建（perf.py 全程不 redeploy），会变 3 轮空转量 stale .so 后误判 redesign（shape 5）。

#### 凭证

- `src/ascendc_devkit/orchestration/stages/perf.py:54-143/121-123/215`；`src/ascendc_devkit/orchestration/kernel/runner.py:72/279/286/652/661-664`；`src/ascendc_devkit/orchestration/graph_executor.py:755`。
- 全仓 grep 确认 `_gate_registry` 仅默认值 + getattr，无赋值/注册。

#### 影响

- 性能门形同虚设，性能缺陷静默向前流窜（违 §3.7/§1.2）。与 `deploy.py:366-368` 标注的 false-green 反模式同类。

#### 状态

- **deferred（休眠功能，零真实 ROI，不做）**：`74-perf-gate-false-green-analysis.md`（L3）。判定依据：perf 调优**未正式上线**，真实 requirement **无一声明 perf constraint**（只 UT fixture 声明）→ PerfStage 永远 skip_reason 跳过 → false-green 路径**真实 run 从不执行**（潜伏，非活跃缺陷）。方案 W（让 perf 真量测）= 在没准备好的功能上盖楼（违 §1.2 方案合理性）；L1（runner unresolved RunGate→raise）虽是通用 §3.7 修复且**不会坏真实 run**（唯一 unresolved RunGate 是 perf 的，且只在声明 perf constraint 时 emit，真实 run 从不触发；finalize 带内联 gate 不受影响），但**零价值**（改一条没人走的路径）+ 徒增"谁声明 perf constraint 就炸"的陷阱 → 不做。**L2-L4 归 perf 功能正式上线工作；L1 攒到动 runner 或上线 perf 时一并。** 复盘：发现 P102 是"潜伏缺陷"，非活跃 blocker——这类不该按 P100 的节奏投入。关联 [[P109]]（finalize 内联 gate 正常，非同 bug，另查）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P102 记录：PerformanceGate 因 gate 注册表永空成 no-op，永远默认 passed（false-green）。 |
| 2026-07-24 | P102 根因细化（展开前审计）：①**直接根因一行可定位**——`perf.py:215` `RunGate(gate_name="performance", evidence=...)` **漏了内联 `gate=`**；对照 `finalize.py:84` `RunGate(gate_name="build_in_repo", gate=BuildInRepoGate(), ...)` 带内联 gate→runner.py:652 `action.gate` 非 None→真执行。`PerformanceGate` 类（perf.py:54-143）已完整写好，只是没接线（registry 全仓无注册调用）。②**但 wire 不是一行修复（shape-5 落实）**：`PerformanceGate.evaluate`（perf.py:123）调 `NPURunner.execute(op_spec, test_cases, npu_id, card_pool=...)` **不传 `deploy_result` 也不传 `callable_target`**；而 NPURunner.execute 两者皆必需（runner.py:279 无 deploy_result→抛 EnvironmentNotAvailableError；:286 无 callable_target→同）。`state.deploy_result` 存在（state.py:256，codegen/precision_debug agent 经 Deployer 写），但 PerfStage input_contract 只要 build_result、evidence 不含 deploy_result/callable_target。③**redeploy 缺口**：perf-tuner 改 code 后 transition 更新 generated_sources，但 perf 全程无 rebuild+redeploy 步骤→下轮量 stale .so。故完整修复需：wire 内联 gate + 把 deploy_result/callable_target 进 evidence 并透传 + 调优后 redeploy（或重审 perf-measures-via-NPURunner 是否该在 gate 里）。比 P100 投入大。关联 P109（finalize 用内联 gate 正常，非同 bug，P109 另查）。 |

---

### P103: precision A5 dump_debug 聚合丢 vf_functions → vf_test 缺必需输入（A 类，已缓解）

#### 事实

- `DumpDebugSubstage.transition`（`precision_debug_a5.py:605-621`）`cp.update` 与 history entry **只写 is_vf_issue，丢 vf_functions**（dump-debug 产物 schema `:577-578` 含该字段）。
- `resolve_condition`（`:635`）凭 is_vf_issue=true 路由 need_vf → vf_test；但 `VfTestSubstage._extract_loop_info`（`:672-702`）返回值无 vf_functions、`_phase_prompt`（`:704-743`）也不传 → vf_test agent 缺"测哪个 VF 函数 + dtype/shape"（vf-debug SKILL.md:5/61-66/88 列为必需前置输入）。
- 缓解：dump-debug result 文件 `dump_round_N_result.json` 仍带 vf_functions 落在 `operator_dir/precision_debug_a5/dump-debug/`，vf_test agent cwd=operator_dir，理论上能自找读（不像 [[P100]] 源在异目录+禁 Glob）；但框架接力断，vf_round 重试不可靠。

#### 凭证

- `src/ascendc_devkit/orchestration/stages/precision_debug_a5.py:605-621/635/672-702/704-743`；`.claude/skills/ascendc-precision-vf-debug/SKILL.md`。

#### 影响

- A5 路径 vf_round 重试缺关键输入，3 轮后 escalate（A2 走 precision_debug.py 不触发）。与 [[P106]] 叠加。

#### 状态

- 待分析（未实施）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P103 记录：A5 dump_debug transition 丢 vf_functions，vf_test 缺必需输入（dump result 文件可自找读，已缓解）。 |

---

### P104: codegen s4 selfcheck Layer-1 计数器失效，仅 E(t) 兜底（A 类轻）

#### 事实

- s4 coding step section 检查失败 → `retry_s4` 分支（`codegen.py:1493-1511`）只累加 codegen_et，不调 `_update_meta_retries`（同 [[P101]] 根因：s4 transition 全程不写 meta.retries）→ `stage4_selfcheck.used`（limit=4）永远 0 → `check_retry_exceeded` 永远 False → 永远 retry_s4 而非 paused。
- 因 `ERROR_WEIGHTS["CHK"]=2`，约 3 次 CHK 失败即 et>=5 回退 s2——**不会死循环**，仅 Layer-1（per-type 精细计数）失效 + 终止语义偏离设计。

#### 凭证

- `src/ascendc_devkit/orchestration/stages/codegen.py:1493-1511`；`stage4_scheduler.sh:276-280`。

#### 影响

- A5 s4 路径 Layer-1 保护成死字段，回退粒度变粗、多空转。

#### 状态

- 待分析（未实施）。与 [[P101]] 同源（s4 transition 不回写 meta.retries）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P104 记录：codegen s4 selfcheck Layer-1 计数（stage4_selfcheck.used）全仓无写入，仅 E(t) 兜底。 |

---

### P105: design validate 就地修正不回写 state（A 类轻，shape 3 潜伏）

#### 事实

- `ValidateStage.transition`（`design_substages.py:1830-1869`）只把 blocking_status.json 存进 `state.validation_report`，**从不把 validate 就地改的 tiling_results/design_spec 回写 state**。validate SKILL 说的"就地 Edit 可修的"只发生在工作副本，state 保持未修正值。
- 未致死循环：内层 domain 对象（如 ub_usage）经聚合 `:2050` 透传，producer 可在源头修后流回（GV4 +32 偏差即此路径走通）；validate 自己的就地改对下游不可见、是空忙。

#### 凭证

- `src/ascendc_devkit/orchestration/stages/design_substages.py:1830-1869`（transition 只存 validation_report）。

#### 影响

- validate 的就地修对下游 codegen 不可见（今天靠 producer 源头修复间接兜住）。

#### 状态

- 待分析（未实施）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P105 记录：validate 就地修正不回写 state.tiling_results/design_spec（间接路径兜住，非致命）。 |

---

### P106: precision A5 vf_test history 漏记 vf_func（A 类轻，放大 [[P103]]）

#### 事实

- `VfTestSubstage.transition`（`precision_debug_a5.py:772-778`）写 history 只记 vf_status/code_modified，**不记 vf_func**；而 `_extract_loop_info`（`:679`）下一轮读 `entry.get("vf_func")` 永远空 → previous_error 永远缺目标函数。

#### 凭证

- `src/ascendc_devkit/orchestration/stages/precision_debug_a5.py:676-683/772-778`。

#### 影响

- 与 [[P103]] 叠加，vf 函数指认在 dump_debug→vf_test 全链路传递断裂。

#### 状态

- 待分析（未实施）。与 [[P103]] 宜一并处理。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P106 记录：A5 vf_test history 漏记 vf_func，下轮 previous_error 丢目标函数。 |

---

### P107: precision candidate_pool verified 回写无框架校验（A 类轻，shape 3 变种）

#### 事实

- fix skill 要求 agent 在 control.json 把验证过的 plan 标 `verified=fixed/refuted`，但 `FixSubstage.transition`（`precision_debug_substages.py:1520-1643`）只 `_load_control` 读盘做 case 推进/corrective_cycles 递增，**不检查本轮是否有 pending→非pending 转换**；`_candidate_pool_exhausted`（`:467-496`）纯看 `verified=="pending"` 计数。
- agent 偶发漏写 verified → 同一 pending plan 被重复取 → 最多空转 `max_corrective_cycles=8`（`:1597`）后 `_advance_past_failure_type` 跳 case。

#### 凭证

- `src/ascendc_devkit/orchestration/stages/precision_debug_substages.py:467-496/1520-1643/1597`。

#### 影响

- agent 行为不可靠时退化为无意义重试（有 8 轮兜底）。

#### 状态

- 待分析（未实施）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P107 记录：fix candidate_pool verified 回写无框架校验，agent 漏写时最多空转 8 轮。 |

---

### P108: cannbench_adapt 重建失败信号截断（B 类/诊断性，无 loopback）

#### 事实

- `cannbench_adapt.py:190-201` 重建失败时把 last_error 重写为仅含 `details={"schema_renamed":...}` 的新 ErrorFeedback，**丢弃原 rebuild_err.details 的 log 路径与 stderr_tail**（`deploy.py:280-284` `_err` 产出）。

#### 凭证

- `src/ascendc_devkit/orchestration/stages/cannbench_adapt.py:190-201`；`src/ascendc_devkit/orchestration/stages/deploy.py:280-284`。

#### 影响

- 下游失去指向完整构建/smoke 日志的链接（诊断性回归 §1.2）；cannbench_adapt 是 continue + 无 TRANSITION_TABLE 条目 → 线性，**无 loopback**。

#### 状态

- 待分析（未实施）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P108 记录：cannbench_adapt 重建失败 last_error 丢弃 log 路径/stderr_tail（诊断性回归，无损循环）。 |

---

### P109: finalize gate_result 默认 passed=True（B 类/诊断性，终态）

#### 事实

- `finalize.py:118-121` `gate_result = result.get("gate_result", {})` 然后 `passed=gate_result.get("passed", True)`——无 passed 键时默认 True（终态 false-green）。

#### 凭证

- `src/ascendc_devkit/orchestration/stages/finalize.py:118-121`。

#### 影响

- 终态误报绿（§3.7）；终态 `max_iterations=1` 无路由，**非 loopback**。

#### 状态

- **非缺陷，关闭（2026-07-24）**：`final_build_result.passed` 是 **write-only 诊断字段**——全仓 grep 确认仅 finalize.py 写、state.py 存、tests 断言，**无任何下游 stage/runner/report 读它做决策**（无路由、无 gating）。无 integration 的场景（SE pipeline `requirement→design→finalize`，workflow.py:457/471）本就无 build，"passed=True" 语义≈"无 build=无事失败"。terminal、无 loopback、无消费者 → 零功能危害。修它（改默认）纯化妆、零效果，不做。区别于 P102（P102 是真 false-green 但在休眠功能；P109 连消费者都没有）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P109 记录：finalize gate_result 默认 passed=True（终态 false-green）。 |
| 2026-07-24 | P109 关闭（非缺陷）：final_build_result.passed 是 write-only 诊断字段，无消费者；无 integration 场景本就无 build。零功能危害，不做。 |

---

### P110: design tiling 聚合还丢 key_parameters / self_check_summary（[[P100]] 同机制定时炸弹）

#### 事实

- [[P100]] 的 `payload.get(segment_key)`（`design_substages.py:2050`）丢弃的顶层兄弟不止 verifiable_claims，还包括 key_parameters / self_check_summary。
- 当前无门查这两个字段（grep design 各 gate SKILL.md 0 命中），故未爆发；但任何未来 gate 规则一旦检查它们，会即刻复刻 [[P100]] 同型死循环。

#### 凭证

- 同 [[P100]]（`design_substages.py:2050`）；design gate SKILL.md 不查 key_parameters/self_check_summary（实测 0 命中）。

#### 影响

- 潜伏定时炸弹。

#### 状态

- 随 [[P100]] / 方案73 方案 S（+T1）消解：`key_parameters` 进 segment（流向门）；`self_check_summary` 留顶层白名单（对质原则门不读，不流向亦无害；UT-A 守"白名单字段若被门读需重审分类"，防潜伏）。**已随 P100 一并实施（2026-07-24）**——key_parameters 进 segment、self_check_summary 留顶层白名单均已落地，UT-A A2 守护白名单纯洁性。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P110 记录：design tiling 聚合还丢 key_parameters/self_check_summary（同 P100 机制，暂无门查故潜伏）。 |
| 2026-07-24 | P110 随 [[P100]]/方案73 方案 S（+T1）消解：key_parameters 进 segment；self_check_summary 留顶层白名单（过程元数据，对质原则门不读）。状态由"待分析"→"随 P100 一并实施"。 |

---

### P111: codegen rollback 路由是死代码，若触发则 target 丢失（A 类潜伏）

#### 事实

- `dispatch_status` 映射（`codegen.py:1448-1451`）只有 ok/failed/partial/paused，**无 rollback→"ROLLBACK"** → agent 返 rollback 被 `.get(...,"FAILED")` 兜底成 FAILED；scheduler 的 ROLLBACK 分支（`stage4_scheduler.sh:339-353`）与 Python `rollback_stage` 分支（`codegen.py:1528-1530`）均**死代码**。
- 即便人为触发：`rollback_stage` 把 cross-stage target 塞进 `codegen_s4_sub_stage`（字段语义错）；intra-stage rollback 在 et<5 时不设 last_error，下轮 `_actions_regbase_s4`（`:624-634`）走 else 调 `resolve-sub-stage continue` 不读 `codegen_s4_sub_stage`，且 transition 从不把 progress.md 里 ✅ 回退为 ⏳/❌ → continue 跳过已 ✅ 的 rollback target → rollback 意图丢失。

#### 凭证

- `src/ascendc_devkit/orchestration/stages/codegen.py:1448-1451/1528-1530/624-634`；`stage4_scheduler.sh:339-353`。

#### 影响

- 当前永不触发，无实际卡死；跨层契约断裂（门与驱动者不对齐），一旦给 agent 加 rollback 返回值即暴露。

#### 状态

- 待分析（未实施）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-24 | P111 记录：codegen rollback 路由是死代码（dispatch_status 无 rollback 映射），若触发则 target 丢失。 |

---

### P112: cann_bench/__init__.py wrapper 漏写 → cann-bench scan_interfaces 发现不到算子（cann-bench 发现链 D，[[P97]] 内容缺口复发）

#### 事实

- 算子经 codegen + precision_debug 正常退出（debugger 走 `torch.ops.cann_bench.<symbol>` 直调，smoke 已验证可调用）；但 cann-bench kernel_eval **检测不到/无法调用**该算子（`operators:[]` 或调用失败）。
- **机理（issue.md `/home/x00584171/temp/issue.md` 实证，算子 AiInfraManifoldConstrainedHyperConnectionPost）**：`TORCH_LIBRARY_FRAGMENT` 把算子注册进 **C++ Dispatcher**（`torch.ops.cann_bench` 投影），但**不回写 Python 模块 `__dict__`**。harness/debugger 走 `torch.ops`（Dispatcher）→ 不需 wrapper → 能调；cann-bench `scan_interfaces` 走 **Python 命名空间扫描**（`dir(cann_bench)` / `inspect.getmembers`）→ 只看 `cann_bench/__init__.py` 里显式 `def` 的 wrapper → **wrapper 漏写就发现不到**。
- **wrapper 由 LLM `cannbench-adapt` agent 写，无确定性保证**：cannbench_adapt 唯一的确定性后处理是 P10（`_rename_mdef_schema_if_needed`，对齐 m.def **C++ schema** 参数名）；**`__init__.py` 的 Python wrapper（存在性 + 参数名匹配 golden + 转发目标=symbol末段）三样全交 LLM，无校验/生成**。prompt（cannbench_adapt.py:306-330）只约束 wrapper **转发目标**（symbol末段），**不约束 wrapper 参数名匹配 golden/proto**。
- **间歇性实证**：同一 manifold 算子——`output/20260715-114508-075b61` 的 per-op `__init__.py` **有** wrapper（`def ai_infra_manifold_constrained_hyper_connection_post(x,h_res,h_out,h_post): return torch.ops.cann_bench.<...>(...)`，参数名对、转发目标对）；issue.md（2026-07-24 run）的 wrapper **不在**（`__init__.py` 只 add/sqrt/aggregate_hidden_grad）。→ wrapper 是否写 = LLM 非确定性。

#### 凭证

- `/home/x00584171/temp/issue.md`（机理：Dispatcher vs Python `__dict__`；manifold wrapper 漏写实例）。
- `output/20260715-114508-075b61/artifacts/per-op/ai_infra_manifold_constrained_hyper_connection_post/python/cann_bench/__init__.py`（wrapper **在**，间歇性对照）。
- `src/ascendc_devkit/orchestration/stages/cannbench_adapt.py:306-330`（prompt 只约束转发目标，不约束参数名/存在性）、`:157-165`（仅 P10 m.def rename 确定性、无 wrapper 处理）、`:38-40`（cann-bench `func(**golden_params)` 关键字调 wrapper）。
- `src/ascendc_devkit/domain/mdef_parse.py`（parse_mdef_params/rename_mdef_schema 原语，可复用做 wrapper 参数对齐）。
- 机理印证：`scan_interfaces` 两路扫描（`dir(cann_bench)` wrapper + `torch.ops.cann_bench`），见 [[P97]] 凭证。

#### 影响

- 算子功能正常但 cann-bench 评测 0/无法调用，浪费整轮 run（codegen+debugger 成果白费）。
- [[P97]] 方案 2（commit `11a5bd73`，cannbench_eval 加载期校验 `operators==0`→报 infra error）已使失败**可见**（非静默 0），但可见仍=失败（op 无法评测）。
- 违 §2.9（wrapper 存在性/正确性应构造性保证，非 discover+fail+rerun；cannbench_eval 的 operators==0 检查恰是 discover 门）。

#### 产权（区别于 [[P97]]，非重复）

- **[[P97]]（C，已修）= 传播缺口**：agent **写了** wrapper（在 example 源），redeploy 没传到 per-op → per-op 缺 wrapper。修法（commit `4594229c`）= clean rebuild + redeploy per-op（保证 per-op 包反映 glue）。**修了传输**。
- **P112（本条）= 内容缺口**：agent **整个漏写** wrapper → example 源与 per-op 都没有 → redeploy 修不了（无东西可传）。**P97 没修内容**——wrapper 是否存在/正确仍 LLM-driven。
- 关系同 [[P100]]之于[[P85]]：P85/[[P97]] 修产出/传播端，P100/P112 是内容/正确性的下半段缺口复发。cann-bench 发现链 A→B→C→D：[[P95]](import)→[[P96]](_C 收录)→[[P97]](wrapper 传播)→**P112(wrapper 内容)**。

#### 状态

- **已实施（2026-07-25）→ 方案 G + 退役 cannbench-adapt agent，UT/ST 绿**：`75-cannbench-wrapper-discovery-analysis.md`（L3 冻结）+ `75-cannbench-wrapper-discovery-impl.md`（L4）。决策：CannbenchAdaptStage 是 cann-bench 专用适配 stage（per-repo adapter 模式），cann-bench 机制经 P95-P99 已完全确定性化 → **确定性生成 wrapper**（manifest 派生：op_name + callable_target.symbol末段 + align_schema_params proto 参数名），**退役 cannbench-adapt LLM agent**（wrapper 确定性、CMake 由 codegen 强制产 + P96 GLOB+clean rebuild 覆盖、cann-bench 无 registry）。§4.3 当初"需要 LLM"理由修订：per-repo adapter 在其仓机制摸清后应收敛确定性（agent 只服务机制未知初生期）。**实施**：`cannbench_adapt.py` 收敛为确定性 stage（`actions()→[]`，transition 注入 wrapper + P10 rename + clean rebuild；删 `_build_prompt`/`_is_glue_file`/SpawnAgent）；删 `.claude/agents/cannbench-adapt.md`。**验证**：UT 35 项绿（W1 三维/W2 替换/W3 追加/W4 stage 集成/W5 退役确认 + P10/discovery 回归），全量 UT 2917 passed/7 skip/0 fail（零回归），ST `test_self_evolution_stages.py` 38 项绿。**待办（用户决策）**：CMake 退役验证（真实 run 确认 op 仍进 `_C`）+ heavy_llm ST（§3.11）。关联 [[P95]]-[[P99]] 链 + [[P100]]（构造性内容保证）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-25 | P112 记录：cann_bench/__init__.py wrapper 漏写（LLM 非确定性）→ cann-bench scan_interfaces 发现不到（Dispatcher 注册≠Python __dict__）。[[P97]] 内容缺口复发（P97 修传播、未修内容）。L3 方案75 待拍板。 |
| 2026-07-25 | P112 拍板：方案 G（确定性生成 wrapper）+ 退役 cannbench-adapt agent。依据：CannbenchAdaptStage 是 cann-bench 专用 stage（per-repo adapter），cann-bench 机制经 P95-P99 已确定性化；wrapper 是 manifest 纯函数；codegen 强制产 CMakeLists + P96 GLOB 覆盖 _C；cann-bench 无 registry。§4.3 rationale 修订。出 L4。 |
| 2026-07-25 | P112 实施：cannbench_adapt.py 确定性化（actions()→[]，transition 注入 wrapper+P10+rebuild，删 _build_prompt/_is_glue_file/SpawnAgent）+ 删 cannbench-adapt.md。UT 35 绿 / 全量 UT 2917 passed 0 fail / ST 38 绿。附修：cannbench_eval `_run_eval` 返回类型注解 `-> EvalResult` 更正为 `-> tuple[EvalResult, ErrorFeedback\|None]`（P95-P99 遗留，生产调用方 line96 本就解包元组，仅注解+1个 ST 用例过时）+ 对应 ST 解包。CMake 退役验证 + heavy_llm ST 待用户决策。 |

---

### P113: framework batch resume 多进程并发 NPU 预检误判「NPU 运行时缺失」致算子 abort（ERR99999 多进程 NPU runtime init 冲突）

#### 事实

- run `20260725-152037-8a4efa`（5 算子 batch resume，2026-07-26 08:40–09:27 多次重试；opencode HTTP 500 已由用户改配置修复后）：execution `20260725-152037-468ce8`（ai_infra_aggregate_hidden_grad）的 general-design-generator abort，报「NPU 运行时缺失，运行将中止（不会进入任何 Agent 阶段）」；其余算子 agent turn 1 恒 0 chars。
- 预检点：`application/dispatcher.py:_preflight_runtime`（dispatcher.py:781，位于 per-op dispatch 流程 709–781）；Check 2（dispatcher.py:412–425）用 `NPURunner()._torch_npu_available`，判据是 smoke test `torch.zeros(1).npu()`（`adapters/npu/runner.py:196`；注释明示「CPU-only torch import 成功但 .npu() runtime 失败」）；except（dispatcher.py:418，`ImportError/RuntimeError/AttributeError`）全吞 → 输出无 traceback。
- batch resume 并发度：`resume_batch` 不传 design_concurrency → `_resolve_max_workers` 返回 n_tasks=5 全并发（batch_runner.py:284–297）；`run --resume` CLI 无并发度 override。5 算子 per-op dispatch 并发 → 5 路并发 `_preflight_runtime` → 5 路并发 NPURunner smoke test。

#### 凭证（实证，非推测）

1. 单进程 `NPURunner()` → `_torch_npu_available=True`；smoke test `torch.zeros(1).npu()` → `npu:0` 成功。
2. 5 **线程**并发 `NPURunner()` → 全 True（线程共享 runtime，不冲突）。
3. 5 **进程**并发 `NPURunner()`（subprocess 同时）→ **全部 `ERR99999 UNKNOWN application exception`，exit 1**（NPU runtime 多进程同时初始化冲突）。
4. `detect_chip_version` 串行压测 6 次全 `A2` 稳定（首 7.6s、余 0s）——非 detect 偶发。
5. `torch 2.7.1+cpu` + `torch_npu 2.7.1.post7`，`torch.npu.device_count()=8 / is_available()=True`，npu-smi 8×910B3 全健康——NPU 并非真缺失。
6. framework resume 进程 env 正常（ASCEND_TOOLKIT_HOME + LD_LIBRARY_PATH 含 cann-9.1.0-beta.3 + driver lib64）。
7. 单 op resume（`run --resume <exec_id>`，不并发）预检通过、无「NPU 运行时缺失」——反证「并发」是触发条件。

#### 关联

- memory `resume-codegen-npu-prefetch-kill`（全批并发预检误杀；单算子 retry 不卡）——原记 codegen 阶段，**本条在 design 阶段复现同一类**（per-op 并发 NPU 预检，多进程 init 冲突）。
- 与 [[P100]]–[[P111]] loopback 专项正交（本条是预检层并发，非 loopback 闭环）。

#### 状态

- **已修复**（2026-07-26 实施）。根因：per-op 并发 dispatch 重复 NPU smoke，并发 NPU runtime init 冲突（ERR99999；代码核查修正：`batch_runner` 用 `ThreadPoolExecutor` **线程池**非进程池——同进程多线程并发 init 冲突，原「多进程」描述有误，修复方案对线程/进程并发都成立）。
- 修复（B3）：① dispatcher `_preflight_runtime` 抽 `_run_runtime_checks` + `_check_runtime_once`（进程内按 `(workflow.name, enable_stubbed)` 缓存 + `threading.Lock` 串行化）——并发 task 第一个持锁实跑、其余命中缓存，消除并发 smoke；② `runner.py:204` / `dispatcher.py:418` except 改 `Logger.warn/error(exc_info=True)` 保留首错 traceback；③ Logger 加可选 `exc_info`（`infra/logger.py`）。
- UT：`test_application.py::TestPreflightToolchain` 补 cache 单次实跑 + 5 并发只实跑 1 次 case（autouse fixture 隔离 cache）；`tests/st/test_preflight_concurrent_npu_init.py` 实证（`@npu @slow`，默认不跑）。全量 UT 3031 pass。关联 memory `resume-codegen-npu-prefetch-kill`（修法落地）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-26 | P113 记录：framework batch resume 多进程并发 NPU 预检（`_preflight_runtime` per-op 并发 + smoke test `torch.zeros(1).npu()`）触发 ERR99999 多进程 NPU runtime init 冲突 → 误判「NPU 运行时缺失」致算子 abort。实证：5 进程并发 NPURunner 全 ERR99999、单进程/5 线程全 True；单 op resume 不复现。关联 memory resume-codegen-npu-prefetch-kill（design 阶段复现）。workaround：串行 resume。L3 待展开。 |
| 2026-07-26 | **P113 已修复**：dispatcher `_check_runtime_once` 进程内 cache + Lock 串行化（并发 task 只实跑 1 次 smoke，消除 ERR99999 并发 init 冲突）+ except 保留 traceback + Logger exc_info。代码核查修正根因描述（batch 线程池非进程池）。全量 UT 3031 pass。详见 runlog 整改记录 + memory `resume-codegen-npu-prefetch-kill`。 |
| 2026-07-26 | **M1 根治（code review 发现）**：NPU smoke 改子进程 + 30s timeout（`_run_npu_smoke_subprocess`），防 driver hang（[[npu-driver-hdcdrv-hang]] hdcdrv 死等）在 cache+Lock 持锁时放大为全 batch 卡死。顺带消除 dispatcher→npu.runner 的 L2→L6 依赖违规（test_layer_dependencies KNOWN 移除）。UT +3（超时/成功/失败带 traceback）。全量 UT 3034 pass。 |
| 2026-07-26 | **实证修正根因**（`test_preflight_concurrent_npu_init` 真机跑）：baseline ✓ + 5 线程并发 NPURunner ok=5/5 + 5 进程 spawn ok=5/5，**均无 ERR99999**——证伪原「并发 NPU init 冲突」稳定根因推断（当前 driver/CANN 不复现）。真实根因更可能是 driver 偶发抖动（[[npu-driver-hdcdrv-hang]]）× 并发 smoke 放大偶发概率。B3 修复仍正确且 #1 真机回归验证有效（`run --resume` 5 算子并发预检不 abort + smoke 只跑 1 次，日志 4 次 `runtime check cached`）。 |

---

### P114: opencode 把网关非 200（503 model_not_found / 429 limit）silent 吞成 0 chars——framework/agent 无错误信号、silent 卡死（违 §1.2 可诊断）

#### 事实

- run `20260725-152037-8a4efa` 串行 resume（单 op，已绕过 [[P113]] NPU 并发后）：execution `20260725-152037-0760e5` 的 tiling/split 3 个 agent turn 1 恒 0 chars，5 分钟无 turn 2，silent 卡死。
- `opencode-config.json` model = `glm-5.2[1m]`（来自 `ANTHROPIC_DEFAULT_SONNET_MODEL`）；网关对该 model 返回 503 model_not_found。
- opencode serve 日志（`.opencode-serve-*.log`）仅 2 行启动行（`listening`），无 LLM 调用/error 日志；framework 日志 500/503/429/401 全 0，只见 `agent_stream turn 1 (text) 0 chars`。
- 即 opencode 收到网关 503 后**silent 吞错**（stream empty, 0 chars），framework/agent 看不到任何错误码。

#### 凭证（实证，当前会话 token 尾号 `...16l2Qr`）

1. `opencode-config.json` model = `glm-5.2[1m]`（devkit 从 `ANTHROPIC_DEFAULT_SONNET_MODEL` 生成，每次 spawn 重新生成覆盖手改）。
2. curl 网关：`glm-5.2[1m]` → 503 model_not_found；`glm-5.2`/`glm-5.1` → 429 limit exhausted；`glm-4.6` → 200。
3. opencode serve 日志仅 `listening` 启动行，无 error/LLM 调用记录。
4. framework 日志：`agent_stream turn 1 (text) 0 chars 8.7s`，无 500/503/429/401 任何错误码。
5. `opencode_backend.py:1003-1023` 注释已识别 silent failure 模式（baseURL 缺 `/v1` → stream empty, status ok, 0 tokens）；本条是同型 silent，但触发源是网关非 200（model 不可用），非 baseURL。

#### 关联

- 与 [[P113]] 串联：P113（NPU 并发预检）解决后暴露的本条（model 不可用 + opencode silent 吞错）。
- 触发源是**服务端**（网关 `glm-5.2[1m]` 无 channel / `glm-5.2` 额度耗尽）；**本条记的是工程层 silent 吞错**（opencode 不传播网关错误 → framework 无信号 → agent silent 卡死空等）。
- 伴生矛盾（待澄清，非本条根因）：用户反馈「glm-5.2 本地可用」，但本会话 token `...16l2Qr` curl `glm-5.2` = 429；疑用户本地用了不同 token（有额度）。

#### 状态

- **可诊断已修复**（2026-07-26 实施）；服务端 model 不可用属外部故障（归 memory `external-infra-not-framework-responsibility`，不归框架修）。工程层 silent 吞错已加可诊断信号。
- 修复（B4）：`opencode_backend.spawn` POST 返回后加 `_maybe_warn_silent_failure`——gateway 200（`err=None`）但 agent `consumer.full_response` 空 → 打 `Logger.warn` 诊断（含 turns/stalled/artifacts + 「curl 网关验证 model+token」提示）+ `_tail_serve_log` 附 serve log 末 n 行。**不改 crashed/status/error_type** → 重试行为零侵入（用户意愿：重试是吸收服务器抖动的增强行为，保留）。UT：`test_opencode_backend.py::TestSilentFailureDetection`（9 case）。全量 UT 3031 pass。关联 memory `opencode-silent-swallow-gateway-error`（可诊断落地）。
- 伴生 B2（unrecoverable 401 空烧重试）经用户决策**不立项**——重试是增强行为，只要日志有记录即可（B4 的 silent 诊断已补足信号）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-26 | P114 记录：opencode 把网关非 200（503 model_not_found / 429 limit）silent 吞成 0 chars，framework/agent 无错误信号、agent silent 卡死空等（违 §1.2 可诊断）。实证：opencode-config model=`glm-5.2[1m]`，网关 503，serve 日志无 error，framework 只见 0 chars。触发源服务端（model 不可用），本条记工程 silent 吞错。待新会话分析 token/model 矛盾 + silent 修复（L3）。 |
| 2026-07-26 | **P114 可诊断已修复**：opencode_backend.spawn 加 `_maybe_warn_silent_failure`（gateway 200 + 0 chars → Logger.warn 诊断 + serve log tail）。不改 crashed/status（重试行为零侵入，用户意愿）。B2（401 重试）经决策不立项（重试是增强行为，保留）。全量 UT 3031 pass。详见 runlog 整改记录 + memory `opencode-silent-swallow-gateway-error`。 |

---

### P115: design-generator 连 engine_mcp_stdio MCP stdio 握手 hang（memory `batch-design-primary-mcp-hang` 复发）+ P-BC3 keepalive watchdog 盲区（stdio 子进程 hang 期间 opencode 仍发 SSE 心跳刷新 last_event_ts，keepalive 不触发）

#### 事实

- run `20260725-152037-8a4efa` 全批 resume（5 算子并发，P113/P114 已修后重启）：design 阶段**全局卡**——所有非-abort 算子（0760e5/900f0c/ed4992/468ce8）run.log 停滞（ed4992 停于 23:41:43，48min 无更新）；resume 主进程 + 8 opencode serve 存活但 **opencode 无到网关(192.168.0.212:8082)的连接**（`ss` 全空，不在等 LLM）。
- 每个 opencode serve 都 spawn 一个 `engine_mcp_stdio` 子进程（`python -m ascendc_devkit.capabilities.engine_mcp_stdio`，共 8 个），**全 CPU 0.0%、etimes ~2987s（~50min）、Sl 状态**——design-generator 调 engine MCP（resolve_ambiguity）**stdio 握手 hang**，全空等。即 memory `batch-design-primary-mcp-hang` **复发**（仅记未修）。
- resume #6 初期 aggregate `chars>0=28` 正常（design-generator 不调 MCP 的 turn 正常产出）；一旦调 MCP（resolve_ambiguity）即 hang。

#### 凭证（进程铁证 + 代码核查）

1. **8 个 engine_mcp_stdio 全 hang**：`ps --ppid <opencode-serve>` → 每个都有 `python -m ascendc_devkit.capabilities.engine_mcp_stdio` 子进程（PID 3355733/3357356/3357359/3357360/3357599/3358031/3358304/3358320），全 `%CPU 0.0`、`ELAPSED 2986-3021s`、`Sl`。
2. **opencode serve 无网关连接**：`ss -tnp | grep 192.168.0.212` 全空（不在等 LLM）；opencode serve 自身 `Ssl`、CPU 2.5-3.6%（活跃，疑发 SSE 心跳/polling stdio）。
3. **resume 主进程**：`futex_wait_queue_me`（ThreadPoolExecutor join）+ 3 线程 `hrtimer_nanosleep`（疑 message_timeout/keepalive 定时器）。
4. **keepalive 盲区（代码核查）**：`opencode_backend.py` P-BC3 keepalive 判活看 `last_event_ts`（每 SSE frame 刷新，:276-279/:370-371），`keepalive_idle_s=600`。`engine_mcp_stdio.py:158-165` `_serve` 在 `stdin.readline` 等 JSON-RPC 握手请求（CPU 0 = opencode 未发/未读完）。MCP 握手 hang 在 stdio 子进程层，**不影响 opencode 发 SSE 心跳** → last_event_ts 持续刷新 → keepalive 误判存活 → 不 kick。
5. **唯一兜底 = message_timeout 硬墙**：`message_timeout=3600`（1h，:209/:243）。opencode serve etimes ~2987s（~50min）→ 还剩 ~10min 到 1h，届时 P-BC3 hard-timeout 会 `KeepaliveTimeout` fatal 收口（:166-178，不再 1h 空烧重试）。

#### 关联

- memory `batch-design-primary-mcp-hang`：design-generator（primary agent）连 engine MCP（stdio）握手 hang；subagent 不连 MCP 不卡；framework 吞 opencode stderr→/dev/null 致无诊断；message_timeout=1h 致空等。**仅记未修，本次复发**。
- commit `bb9b182e`（P-BC4）commit message 自承同型 keepalive gap：「permission-block 期间 opencode 发 SSE 心跳致 last_event_ts 刷新，keepalive 不触发，只抓 SSE 静默、抓不到 permission-block」。P115 的 MCP 握手 hang 是**同型盲区的新触发源**（permission-block 已由 external_directory=allow 解决，但 stdio 子进程 hang 仍能骗过 keepalive）。
- external_directory 已 `allow`（`opencode_backend.py:860-865`）→ 排除 P-BC4 permission-block。
- 非网关问题：opencode 没连网关（§1.11，且 curl 不代表 SDK，不作判据）。

#### 状态

- **根因已坐实（2026-07-27）**：**批跑并发 opencode SQLite DB lock**。详 L3 `opencode-batch-concurrency/05-*.md` §2.5（现场 serve log `database is locked` 铁证 + 隔离边界代码核查）。前述「MCP 握手 hang / engine 等 initialize」是**现象**（engine CPU 0 readline 阻塞），**触发条件是并发**（单算子健康、engine 无 bug、socketpair wiring 正确）——非 engine/opencode 单实例问题。
- **方案已评估（L3 §5）**：**G（per-spawn XDG 隔离——主修复根治）+ A/B（engine 握手超时 + keepalive 子进程监控——可观测兜底）+ C（message_timeout 收敛，可选）**。四把尺子评估 G+A/B 全 ✓（§1.2 组合原则：G 保不变式 + A/B 补可诊断短板）。待用户确认后转 L4 实施。
- **当前兜底有效**：`message_timeout=3600`（1h）硬墙 fatal 收口（P-BC3，本次实证 spawn→60min26s 收口），不无限空烧；但 1h 全废 + 占资源，G 实施后消除。
- **保留有效**：keepalive 盲区（P-BC3 只看 SSE frame，握手 hang 期间 SSE 心跳刷新 last_event_ts）——与并发根因**独立**，仍成立（A/B 补强覆盖「非 SSE 静默阻塞」整类盲区）。
- **关联 P-BC5**（startup retry）：P-BC5 已发现并发 DB lock 但只覆盖 startup crash；G（per-spawn DB 隔离）根治，落在更正确层（isolation 而非 retry）。

#### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-26 | P115 记录：全批 resume（8a4efa）design 阶段全局卡——8 个 engine_mcp_stdio 子进程全 CPU 0 hang（~50min），design-generator 连 MCP stdio 握手 hang（memory `batch-design-primary-mcp-hang` 复发，仅记未修）。P-BC3 keepalive 盲区：keepalive 看 last_event_ts（SSE frame），MCP 握手 hang 期间 opencode 仍发 SSE 心跳刷新 → keepalive 不触发（与 commit bb9b182e 记 permission-block 同型 gap，新触发源）。唯一兜底 message_timeout=3600（1h）会在 ~10min 后 fatal 收口。根因未根治，L3 待展开。详见 runlog `batch-runlog-20260725-152037.md`。 |
| 2026-07-27 | **P115 取证修正（归因不准，重要）**：apt 装 strace 5.16 + 单算子复现 + 手动测试，证实：① `engine_mcp_stdio` 手动测试**完全正常**（initialize + tools/list 正确响应，exit 0）→ **engine 侧无 bug**；② socketpair wiring **正确**（engine stdin/stdout ↔ opencode fd 连续 inode 对端，不错位）；③ **单算子 spawn 健康推进**（design-generator turn 1–4 调 bash+read，opencode recvfrom 正常收网关 LLM 响应；engine CPU 0 是**闲置**非 hang——design-generator 没调 resolve_ambiguity）。前归因「design-generator MCP 握手 hang / engine 等 initialize」**只抓现象（engine CPU 0）没定位触发条件，且没验证单算子是否复现**。修正：**MCP hang 仅在全批并发（5 算子）时触发**（昨晚 50min 是全批 resume，单算子不复现）；根因是**批跑并发触发**的某个条件（opencode 共享状态/握手竞争/资源并发，待定位），**非 engine/opencode 单实例 bug**。保留有效：keepalive 盲区（P-BC3 只看 SSE）+ message_timeout 兜底——与触发条件无关，仍成立。详见 runlog 取证修正段 + L3 `opencode-batch-concurrency/05-*.md`。 |

---

## P116: requirement stage 漏修 P93 infra 感知——网关 401 Invalid token 致 requirement 空烧 10 轮 + 产物缺失却 node_status="completed"，resume 跳过 → 下游 general-design abort

### 事实

- **观测**：run `20260725-152037-8a4efa` 算子 `abeb6c`，requirement 阶段遭遇网关 **401 Invalid token**（2026-07-25 15:56–15:59），10 次 iteration 全 401 失败（requirement-analyst never ran），**无 requirement.json 产出**；但 events 显示 `iteration_complete ok` + `stage_complete`（elapsed 2287s≈38min，total_iterations 10），`node_status="completed"`（产物缺失却 completed）；resume（2026-07-27 12:06）跳过 requirement → general-design-generator 读缺失 requirement → abort `"neither requirement nor design_doc_path is available"` → halt workflow。同批其余 4 算子（0760e5/900f0c/ed4992/468ce8）requirement 正常（有 requirement.json），design 阶段推进中。
- **根因（代码核查）**：
  - **P93 层2 infra 感知只修了 `_DesignSubstage`**（设计子阶段 template-division/tiling/integrate/docgen/validate），**requirement stage（`stages/requirement.py`）不是 `_DesignSubstage`，漏修**——P93 层2 给 `_DesignSubstage.actions()` 加了 infra 短路（`error_type=="infra"` → `return []`），requirement `.actions()` 无此短路。
  - **requirement stage `fail_strategy` 默认 `"continue"`**（无显式），对比 `codegen.py:71 fail_strategy="halt"` → 即使 stage_status=failed 也不设 `_stage_failed` → `graph_executor` 标 `node_status="completed"`（产物缺失却 completed，误判 resume 跳过）。
  - **`runner.py:388-396`（P93 层3）** 看到 `agent_result.error_type=="infra"` 只设 `_iteration_reason`（reason 文案可见），**不 halt**（halt 靠各 stage `.actions()` 自实现）→ requirement 无 infra halt → 每轮重试 spawn，每轮 401，**空烧 10 轮（38min）**。

### 凭证

- abeb6c `events.jsonl`：iteration 10 `iteration_start` reason=`"infrastructure error (agent never ran, unrecoverable): APIError Unauthorized Invalid token 401 isRetryable False"` + `iteration_complete ok` + `stage_complete`（elapsed 2287s）。
- `abeb6c/artifacts/requirement/`：只有 `requirement_doc.md`（输入），**无 requirement.json**（产物缺失）；对比 ed4992 有 `requirement/requirement.json`。
- `abeb6c/agents/requirement-analyst-{01..10}.jsonl`：iter1（57991B）+ iter2–10（均 2340B）transcript 全 `APIError Unauthorized Invalid token`（turn2 `blocks=[]` 空 = agent never ran 无产出）。
- `stages/requirement.py:61-100` `actions()` 无条件 `SpawnAgent`，无 infra halt；无显式 `fail_strategy`（默认 continue）。
- 对比 `codegen.py:476-484`（actions infra halt：`if last_error.error_type=="infra": return []`）+ `:71`（`fail_strategy="halt"`）。
- P93 层2（`_DesignSubstage` infra 感知）未覆盖 requirement（requirement 非 `_DesignSubstage`）。

### 关联

- **P93**（infra 错误分类传导：层2 只修 `_DesignSubstage`，requirement 漏——P116 是 P93 修复范围遗漏的延伸；P93 旁证 P93-e 已记「requirement agent 撞 401 Invalid token 反复出现」但修复未覆盖 requirement）。
- **P92**（旁证：requirement agent 撞 401 Invalid token 5/5 FAIL）。
- [[external-infra-not-framework-responsibility]]（外部 401 不归框架修，但框架不该空烧重试 + 误判 completed + resume 跳过——违 §1.2 可诊断）。
- §1.10（infra halt 是横切控制流，判据用业务语义 `error_type=="infra"`；P93 的 stage 层各加已证明会漏——requirement 漏）。

### 状态

- **已修复（2026-07-27）**：runner 层通用 infra halt（requirement 等顶层 stage 漏修 P93 infra 感知的根治，§1.10 横切控制流归 runner 层）。
  - **Change A**（`runner.py` iteration loop）：infra 提前 break——设 `is_terminal=True` 借 :378 既有 break，并删 :388-396 P93 reason-only 死代码（break 后不可达）。消除空烧重试（abeb6c 10 轮 38min → 1 轮）。
  - **Change B**（`runner.py:486-489` halt 触发）：加 `_last_infra` + `or _last_infra`，infra 无视 fail_strategy 强制 `_stage_failed`（参考 `graph_executor._is_non_fixable` crash 路径）。→ `node_status="failed"`（不误判 completed）→ resume 重跑。
  - **Change C**（`runner.py:492-494` P8 clause）：加 `not _last_infra`，防 infra partial + contract 满足被 P8 吸收成 ok（否则 stage_complete event 误报 status=ok）。
  - **Change D**（`requirement.py:323-333`）：`error_type=agent_result.status`（丢 infra）→ `"infra" if is_infra else status`（参考 codegen.py:1325-1338）。runner halt 不依赖它（用 agent_result.error_type），但闭合 bug + 对齐 codegen。
  - 保留 codegen/`_DesignSubstage` stage 层 infra halt 作纵深防御（runner halt 后不可达，不冲突）。
  - 验证：UT 8 新增（`test_p116_runner_infra_halt.py`：continue+infra→_stage_failed、不烧重试、逻辑失败不误伤、Change D 传播）+ 全量 UT **3048 passed, 7 skipped**（cann-bench 环境跳过）。
  - 详见 plan `bubbly-exploring-volcano.md`（四把尺子评估：可扩展/架构合理最强）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-27 | P116 记录（事实）：abeb6c requirement 撞网关 401 Invalid token → 空烧 10 轮（38min）+ 产物缺失却 `node_status="completed"` → resume 跳过 → general-design abort。根因（代码核查）：P93 层2 infra 感知只修 `_DesignSubstage`，requirement 非 `_DesignSubstage` 漏修 + `fail_strategy` 默认 continue（不标 _stage_failed → node_status completed）+ runner 层只设 `_iteration_reason` 不 halt。待 L3。 |
| 2026-07-27 | **P116 已修复**：runner 层通用 infra halt（§1.10 横切控制流归 runner，根治「stage 层各加会漏」）——Change A（iteration loop infra 提前 break 设 is_terminal + 删 :388-396 死代码）+ B（halt 触发加 `or _last_infra` 无视 fail_strategy 强制 _stage_failed）+ C（P8 clause 加 `not _last_infra` 防 partial infra 被吸收成 ok）+ D（requirement.py:328 last_error 传播 error_type or status）。保留 codegen/_DesignSubstage stage 层 halt 作纵深。UT 8 新增 + 全量 3048 passed。详见状态段 + plan `bubbly-exploring-volcano.md`。 |

---

## P117: 单算子 design-generator POST 后 opencode silent 重试卡 3600s——opencode session 层无限重试 + silent 吞网关错误 + SSE noise 骗 keepalive

### 事实

- **观测**：run `20260725-152037-8a4efa` 算子 `900f0c`（scatter_pa_kv_cache）的 docgen design-generator（P115 G+A 修后代码，commit 8e840aaf，per-spawn XDG 已生效）：spawn（serve :54355，13:32:28）→ POST message → **3600s hard cap abort**（14:32:36）。
- **opencode 内部根因（opencode.log 铁证）**：网关返回 **1313 Fair Usage Policy 限流**（账号被限频）。opencode.log 记 **184 次 `stream error [1313]`**（14:00→14:17，指数 backoff 2→4→…→1024s 翻倍 + backoff 到顶后重置多轮）。opencode **silent 吞 1313**（POST 不返回 framework）+ session 层无限重试期间持续发 SSE noise（loop/permission/skill frame）。
- **framework 侧根因（代码核查）**：keepalive `_post_message_watched` 存活判据是 `last_event_ts`（`_subscribe_sse._handle` :371 对 **ANY** SSE frame 刷新，注释"ANY parsed frame = liveness"）。opencode 重试期的 SSE noise 持续刷新 last_event_ts → **keepalive 误判存活** → 不 trip → 等 3600s hard cap。
- **证伪先前「last_event_ts=None 从未活跃」假设**：run.log 实测 docgen **turn 2-12 有 121 行 agent_stream**（13:32→13:55），last_event_ts 从未 None（POST 后 opencode 持续发 SSE）。先前 L3 假设与实证不符。
- **源码铁证（opencode-dev，opencode 不可改）**：① executor 层 `MAX_RETRIES=2`（有限）对 1313 **不生效**——`statusError:281 if (status<400) return response`，1313 是 HTTP 200 body 业务码当成功放行；② **session 层 `SessionRetry.policy`（retry.ts:181 `Schedule.fromStepWithMetadata`）无次数上限**——只靠 `retryable()` 返回 undefined 停，否则永远重试（docgen 184 次）；③ framework 已认识 1313（`_RATE_LIMIT_MARKERS` 含 `[1313]`/`Fair Usage Policy`，_shared.py:411-415），但 opencode 吞了信号，framework 收不到。
- **排除**：并发 DB lock（P115 G 修了 per-spawn DB；ed4992/docgen 同期正常 1142s）；crash（serve 活着，疯狂重试，serve log 仅 listening）；MCP 握手（POST message 非 engine stdio 握手，A fix 不覆盖此路径）。

### 凭证

- opencode.log `900f0c/.opencode_home/data/opencode/log/opencode.log`：184 次 `stream error [1313]`（指数 backoff 2→1024s + 多轮重置）。
- run.log `900f0c/run.log`：turn 2-12 有 121 行 agent_stream（13:32→13:55），最后 turn 12（13:55:13）→ hard cap（14:32:36）37min 静默窗；opencode.log 此窗口 1385 行内部活动（315 duplicate skill name + 169 stream + 151 permission）。
- opencode-dev 源码：`packages/llm/src/route/executor.ts:36 MAX_RETRIES=2`、`:281 status<400 放行`；`packages/opencode/src/session/retry.ts:181 Schedule.fromStepWithMetadata`（无 recurs/upTo 次数限制）；`packages/opencode/src/session/processor.ts:660 Effect.retry(SessionRetry.policy)`。
- framework `capabilities/agent/_shared.py:411-415 _RATE_LIMIT_MARKERS`（含 [1313]）；`opencode_backend.py:371`（ANY frame 刷新 last_event_ts）。

### 关联

- **P115**（[[batch-design-primary-mcp-hang]]）：keepalive SSE noise 误判存活盲区，P115 §3 已识别，B（子进程监控）deferred。**P117 是同型盲区**（SSE noise 骗 keepalive），触发源从 MCP 握手心跳换成网关 1313 重试的内部 SSE 活动。G（per-spawn DB）+ A（engine 握手）未覆盖此盲区。
- **P114**（[[opencode-silent-swallow-gateway-error]]）：opencode silent 吞网关错误（P114 是吞成 0 chars）。P117 是更严重形态（吞 + session 层无限重试 + SSE noise 保活）。
- [[external-infra-not-framework-responsibility]]：opencode 不可改（无限重试 + silent 吞是 opencode 行为），framework 只能观测 + 止损 + 留信号。
- §1.10：keepalive 存活判据（SSE noise）是机制特征代理，必然误判；路线 C 用业务语义（turn 进展 + 卡住 turn 的 tool 活动作为诚实信号），不读 opencode.log（§1.7 仓自闭环）。

### 状态

- **已实施（2026-07-27，修订）路线 C**：framework 侧（opencode 不可改）**turn-stall gate**（`state["turn_ts"]` 超 `turn_stall_s` 未更新 → trip；trip reason 带 `state["turn"]` + `state["block_types"]`——卡住前最后 turn 的 tool 活动，操作者可见 SDK 内部在做什么，对合法长 tool 有心理准备）。**不读 opencode.log**（§1.7 仓自闭环；路线决策后用户否决 A——不依赖外部文件）。2 阈值 config 可配（`orchestration-config.json` timeouts.opencode_turn_stall_s / opencode_message_timeout_s，0=disabled；spawn 超时全程可配，合法长 tool 可调大 turn_stall_s 留空间）。详见 L3 `opencode-batch-concurrency/07-post-silent-hang-analysis.md`。UT 9（test_p117_turn_stall_watchdog）+ heavy_llm ST（test_turn_stall_e2e，§3.9 真实守护，默认不跑）+ 全量 3070 passed/7 skipped。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-27 | P117 记录（事实）：900f0c/docgen POST 后 3600s hard cap。初判根因 keepalive `last_event_ts=None` 盲区（**后被实证证伪，见下行**）。 |
| 2026-07-27 | **根因修正**（opencode.log + run.log + opencode 源码铁证）：证伪「last_event_ts=None」——docgen turn 2-12 有 121 行 agent_stream，last 从未 None。真因 = opencode session 层无限重试（`SessionRetry.policy` Schedule 无上限）+ silent 吞 1313（POST 不返回）+ SSE noise 骗 keepalive（`:371` ANY frame 刷新 last_event_ts）。executor `MAX_RETRIES=2` 对 1313 不生效（HTTP 200 body 业务码）。framework 已认识 1313（`_RATE_LIMIT_MARKERS`）但 opencode 吞了信号收不到。opencode 不可改。 |
| 2026-07-27 | **实施路线 C**（framework 侧）：A `_tail_opencode_log` 增量读 opencode.log 检测 stream-error storm → trip（reason 含 1313，复用既有 `_RATE_LIMIT_MARKERS` 分类，PRIMARY 止损 + 诚实反馈 run.log）；B `state["turn_ts"]` turn-stall 兜底；4 阈值 config 可配（`opencode_timeouts()` reader → dispatcher → `__init__`：turn_stall_s/stream_error_trip/stream_error_window/message_timeout_s，0=disabled）。UT 10 新（test_p117_opencode_log_tail_turn）+ 全量 3073 passed/7 skipped。 |
| 2026-07-27 | **路线修订（回滚 A）**：用户否决 A（tail opencode.log 违 §1.7 仓自闭环）+ 要求 spawn 超时可配、trip reason 带 tool 调用信息（合法长 tool 有心理准备）。删 A 全部痕迹（`_tail_opencode_log`/`_OPENCODE_LOG_*` 常量/stream_error config/`import re`/`scratch_dir` 参数/dispatcher kwargs），保留 B turn-stall 并增强：trip reason 带 `state["turn"]` + `state["block_types"]`（卡住前最后 turn 活动，sorted join）。config 收敛为 turn_stall_s + message_timeout_s（0=disabled）。UT 重写为 test_p117_turn_stall_watchdog（8 用例）+ TestOpencodeTimeouts 收敛（8 用例）；全量 3069 passed/7 skipped。 |
| 2026-07-27 | **补测（§3.9 真实链路守护）**：① UT 补 trip reason 中间分支（turn>0 但无 block → "last turn 5" 无空 ':'），9 用例；② 新增 heavy_llm ST `tests/st/test_turn_stall_e2e.py`（turn_stall_s=8 + 长纯生成 → gate 真实 trip，断言 run.log `no new turn`/`turn_stall` 签名区分 hard cap；默认不跑 conftest:119，用户 `-m heavy_llm` 决策）；③ `_dual_backend.make_backend` 加 `**overrides` 透传 turn_stall_s/message_timeout（backward-compatible）。全量 3070 passed/7 skipped。 |

---

## P118: design gate 可把"可修 issue"误判 target=human → design_needs_human → `__halt__`（step-78 收口后的残余 attribution 缝）

### 事实

- **观测（订正：仅 review halt，非三 gate 都 halt）**：design 三质量门（review / anchor-consistency / validate）的 `gate_scope.json` 都**声明**了 `{"target":"human","escalate":true}` 路由，但**声明 ≠ 实际 halt**。逐门追踪 `condition → 转移表 → 后果`：
  - **review（general-design 组）**：`issue_target_mapping` human→`"human"` → `_GENERAL_DESIGN_TRANSITION_TABLE["general-design-review"]["human"]` = `("__escalate__:design_needs_human","escalation")`（`design_tree.py:44`）→ pipeline `_DESIGN_GROUP_PIPELINE_ROUTES["general-design"]["design_needs_human"]` = `("__halt__","escalation")`（`workflow.py:264`）→ **整轮 run 硬终止**。✅ 唯一会 halt 的门。
  - **validate（detailed-design 组）**：`issue_target_mapping` human→`"human"`，但 `_DETAILED_DESIGN_TRANSITION_TABLE["validate"]` 只有 `redo_tiling`（`design_tree.py:65-86`），无 human 路由 → `graph_executor.py:429-430` `route=None` → 线性前逃，带 `design_known_issues` 进 codegen，**不 halt**。step-60 修C 已显式删 validate 的 `redo_doc`/`human`/`redo_general` halt 出口（P83 逃生哲学）。
  - **anchor（detailed-design 组）**：`issue_target_mapping` human→`"human"`（`design_substages.py:1621-1623`），但转移表只有 `infeasible`/`advisory_integrate`（`design_tree.py:58-64`），无 human 路由 → 同前逃，**不 halt**。且 `anchor-consistency/SKILL.md:86` 把 `AC3 owner_ambiguous` 实际标 `target=integrate`（不 emit human）→ anchor 的 human 路由是**从未被触发的死配置**。
- **halt 的真实语义（"硬终止"非"挂起等人"）**：`graph_executor.py:470-497` 命中 `__halt__` → 设 `is_terminal=True`、`halt_reason={kind:"corrective_exhausted",...}`，"Remaining downstream stages are intentionally skipped"；`precision_debug_tree.py:12-13` 明文 "treats `__halt__` as whole-run termination"。**仓内无 pipeline 级 resume-from-halt 机制**——既有 `resume`（`runtime_config.py:434+`）全是 agent spawn 级韧性（B2-resume 崩溃 session / 429 backoff-resume），非 halt 后恢复。halt 后这一轮 run 结束，须人**离线介入后另起新 run**。所谓"交人"= 流程外离线诊断+决策+重启，流程内不自动恢复。
- **reviewer 已具备流程内提问工具**：`.claude/agents/ascendc-design-reviewer.md` 的 `allowed_tools` 含 `mcp__engine__resolve_ambiguity`（§4.4 编排型 agent 向人澄清/反问的通道）；`engine_mcp_stdio.py:178` "resolve_ambiguity waits on a decision"（阻塞等人决策后 agent 继续；交互 TUI 真实提问 / 非交互 `default` 策略选首项）。即 reviewer 判定"真方向歧义"时**本可在流程内向人提问**，不必让整条 pipeline halt。
- **与 step-60 已冻结决策冲突**：`60-design-escape-hatch-analysis.md:17` 用户拍板第 3 条——"**halt 仅留给 429 这类服务端不可用……设计质量门不 halt**"。review 的 `design_needs_human→__halt__` 是 design 质量门 halt，**直接违反该决策**（step-60 修C 已据此删 validate 的 human halt，review 的对称清理未做——本问题即该漏网之鱼）。
- **各 human issue code 的语义与"是否真需人"（SKILL 权威定义，事实层归类）**：
  - review `GD-H*`/`GD-CR2 真方向歧义`：方向性歧义、意图无法判断、超出算子开发范畴——"连需求层都定不了"（`general-design-review/SKILL.md:112,119`）。语义上确属 producer 无法决定（producer 只能猜）。
  - validate `GV7-A`：梯度公式修正项仍含位置下标（标量一致性违反）；`GV7-B`：公式↔Kernel 伪代码语义不等价——SKILL 判"以数学推导为准，标不可修正（需人工）"（`validate/SKILL.md:75-86`）。但公式由 producer（precision-perf / 上溯 design_spec/requirement）产出，语义上是 producer 产了自相矛盾/有缺陷的件。
  - validate `GV9-b`：上游 `anchor_report` 含 AC0/AC1/AC2 阻断的**再标记**（`validate/SKILL.md:111-115`）；而 AC0/AC1/AC2 在锚点门自身路由 `target=tiling`（corrective），非 human。
- **根因（attribution 质量 + halt 语义错配，非 scope 越界）**：双重——① attribution 质量：门把可修 issue 误判 human，INV-A 不 drop（`human∈routes` 合法）；② halt 语义错配：即便真·需人决策（GD-H*），用 `__halt__`（abort 语义）承载"需人决策"（本该 suspend 语义）是机制错配，违反 step-60「设计门不 halt」决策，且 reviewer 手上的 `resolve_ambiguity`（in-flow 提问通道）未被该路由使用。
- **凭证**：
  - `gate_scope.json` ×3 的 human 路由声明（review/anchor/validate 各一条）。
  - `design_tree.py:44` / `workflow.py:264` review human→halt 直通。
  - step-78 INV-A `_scope_filter`（`design_substages.py:951-985`）只 drop 越界，human 合法不 drop。
  - **新增（halt 语义 + 错配）**：`graph_executor.py:470-497`（halt=is_terminal 硬终止）；`precision_debug_tree.py:12-13`（whole-run termination）；`runtime_config.py:434+`（resume 仅 agent spawn 级，无 pipeline resume）；`.claude/agents/ascendc-design-reviewer.md` allowed_tools（含 `mcp__engine__resolve_ambiguity`）；`engine_mcp_stdio.py:178`（waits on a decision）；`60-design-escape-hatch-analysis.md:17`（设计门不 halt 拍板）；`design_tree.py:58-86`（anchor/validate 转移表无 human → 前逃）；`design_substages.py:1621-1623/1944`（anchor/validate issue_target_mapping）；`anchor-consistency/SKILL.md:86`（owner_ambiguous→integrate 非 human）。
- **影响范围（订正）**：真·halt 风险面 = **仅 review 的 `GD-H*`/`GD-CR2 真方向歧义` 误判**（其他门误判 human 是前逃/死配置，非 halt）。但"门判 human 即剥夺 producer corrective 试错机会"这一 attribution 缺陷三门共有；且 review halt 违反 step-60「设计门不 halt」决策。
- **与"带毒前逃"缝（Q1/Q3 讨论的 corrective 耗尽前逃）的区别**：那条是 producer 试了没修好→带 known_issue 前逃（不 halt）；本条 review 分支是门根本没让 producer 试→直接 halt。两缝同源（attribution 质量），表现相反（一前逃一 halt）。

### 关联

- **step-78**（gate scope & ownership contract，[[design-review-infeasible-loopback-deadloop]]）：INV-A 堵了越界 issue（review 不再查 requirement math），但 human 误判是 in-scope 语义判断，INV-A 不覆盖——本问题是 step-78 收口时识别的残余缝。
- **step-60**（设计逃生 + halt 仅限 429 拍板）：review 的 `design_needs_human→__halt__` 违反 `60-analysis.md:17`「设计质量门不 halt」决策；step-60 修C 已据此删 validate 的 human halt 出口，review 的对称清理未做——本问题的 halt 风险面集中在此。
- **§4.4**（编排型 agent 澄清走 `resolve_ambiguity` MCP）：reviewer 已在 `allowed_tools` 持有 `resolve_ambiguity`，本可在流程内向人提问而非 halt——这是 in-flow 替代 halt 的既有通道。
- **§2.9**（门不越界查上游产物）：本问题不是越界（human 在门 scope 内），是"门 scope 内该 corrective 还是该 human"的归属判断，§2.9 未直接覆盖。
- **Q2 讨论（2026-07-28）**：定性为 attribution 质量问题，控制流已把危害有界化（human 路由只留特定 code、INV-A drop 越界），但彻底关掉需结构性改造（human 路由收缩到真无解 + corrective-first）。

### 状态

- **已实施（2026-07-28）**。L4 落地（`79-design-human-channel-impl.md`）：①review 删 human→halt 链（**保留 human target 作前逃标记**，对齐 validate step-60 修C——target=human 过 INV-A 进 `design_known_issues` 可观测前逃，transition table 无 human→route=None→不 halt）；②reviewer in-flow `resolve_ambiguity` 提问（options[0]=pipeline-advancing 前逃项，方式 2，零 handler 改动），人决策转 generator/requirement corrective，default 写 `target=human`+`needs_human_decision` 前逃；③validate GV7-B/GV9-b→`target=tiling`（redo_tiling），GV7-A 保留 `target=human` 前逃+反馈强化 requirement 自检；④删 anchor human 死配置；⑤requirement `math-equiv-golden` 加结构校验子步（修正项不得含位置下标）。全量 UT **3119 passed/7 skip** 零回归；heavy_llm review GD-H* e2e **PASSED**（`TestReviewGDHOutOfScopeRoutesToHuman`，reviewer 真调 `resolve_ambiguity` + 判 GD-H* 前逃不 halt，R1/R2/R3 真实链路守护到位），Q1 留 PR 前人工审计（结构校验断言不可行）。根因深化（halt 语义错配——abort 承载了本该 suspend 的"需人决策"；reviewer 已持 `resolve_ambiguity` 却未用；违反 step-60「设计门不 halt」决策）已落 L3 `79-design-human-channel-analysis.md`。**用户拍板（2026-07-28）**：①人也无法决定→前逃（known_issue + `needs_human_decision`）不 halt；②`resolve_ambiguity` `default`→转前逃 + 标 `needs_human_decision`（非选首项）；③全范围（review/validate/anchor 凡涉此类 attribution 问题都改）；④公式=requirement 的 `math_formula`（`op_spec_schema.md:100`），且 requirement 已声明 `math-equiv-golden` 自检（`capabilities.json:4-5`）。GV7-A/B 落点已确认方案 X（GV7-B→tiling / GV7-A→强化 requirement `math-equiv-golden` 自检，不给详设加 escalation）。L3 已冻结（2026-07-28），待排 L4。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-28 | P118 记录（事实）：step-78 收口讨论中识别的残余 attribution 缝——gate 可把可修 issue 误判 human → `__halt__`。修复方向留 L3。 |
| 2026-07-28 | P118 根因深化 + 事实订正：①订正"三 gate 都 halt"→ 仅 review halt（validate/anchor 前逃、anchor human 死配置），并补三门转移表与 issue_target_mapping 逐门追踪；②补 halt=`is_terminal` 硬终止（`graph_executor.py:470-497`）+ 无 pipeline-level resume + reviewer 已持 `resolve_ambiguity`（`agents/ascendc-design-reviewer.md`）+ 违反 step-60:17「设计质量门不 halt」决策；③补各 human issue code（GD-H*/GV7-A/B/GV9-b/AC3）SKILL 语义事实；④L3 起草 step-79（调研中）。 |
| 2026-07-28 | P118 用户拍板 + c 查证：①人也无法决定→前逃（known_issue+`needs_human_decision`）不 halt；②`resolve_ambiguity` `default` 转前逃非选首项；③全范围（review/validate/anchor 凡涉此类 attribution 都改）；④公式=requirement.`math_formula`（`op_spec_schema.md:100`）+ requirement 已有 `math-equiv-golden` 自检（`capabilities.json:4-5`）。GV7-A/B 落点（GV7-B→tiling / GV7-A→强化 requirement 自检）为 L3 推荐待最终确认；L3 §5 改拍板记录。 |
| 2026-07-28 | P118 GV7-A/B 落点确认方案 X：公式正确性归 requirement 自检（构造性保证 §2.9），validate 只查一致性→tiling（GV7-B→`redo_tiling` / GV7-A→强化 `math-equiv-golden` 自检），不给详设加 requirement escalation（守 P83 + INV-A）。L3 冻结，待排 L4。 |
| 2026-07-28 | P118 L4 已实施（`79-design-human-channel-impl.md`）：删 review human→halt（保留 human 前逃语义，对齐 validate）+ reviewer in-flow resolve_ambiguity（options[0]=前逃项，方式 2）+ GV7-B/GV9-b→tiling + GV7-A 前逃 + 删 anchor 死配置 + requirement 结构校验子步。全量 UT 3119 passed 零回归。heavy_llm e2e 待用户确认（§3.11）。 |
| 2026-07-28 | P118 heavy_llm：review GD-H* e2e **PASSED**（`TestReviewGDHOutOfScopeRoutesToHuman`，reviewer 真调 `resolve_ambiguity` + 判 GD-H* 前逃不 halt）。requirement 结构校验 ST 评估断言不可行（`math_formula` 无 AST），Q1 留 PR 前人工审计。 |

## P119: docgen OpDef anchor gate 用 halt 违背框架 fail-forward 意图（md 是 presentation，codegen def.cpp 编译才是权威 backstop）

### 事实

- **观测**：batch `20260728-134831-ccda3b/51d915`（multi_add_rms_norm_dynamic_quant）确定性卡死 docgen stage——3 轮 iteration 全 `missing: ['design_doc']`，gate 报 `§2.3 OpDef 非 canonical（缺正向锚点：Input("epsilon")）` → `fail_strategy=halt` → 整算子 halt、进不了 codegen。非 token、非 flaky（其他 4 算子正常）。
- **凭什么说 gate 不该 halt**：① docgen 产出 md 是 **presentation，下游 validate/codegen 不读**（`DocgenStage` docstring `design_substages.py:1779-1780` + `ValidateStage.input_contract` design_doc optional）；codegen 独立从 `design_spec` 生成 `def.cpp` 并**编译**——那才是 OpDef 正确性权威 backstop（§2.9 构造性保证），gate 重复了它。② gate 报"缺锚点"只能靠 docgen agent 重跑碰运气（51d915 跑 3 轮没对齐）= **discover+regenerate 反模式**（§2.9）。③ 框架意图白纸黑字（`design_tree.py:78-82`）：*"docgen must not halt; ... rides forward as a known_issue."* ④ `design_known_issues` escape hatch（`state.py:200-209`）专为"设计无客观 pass bar、不完美设计继续到 codegen"建，validate 已用、codegen 已渲染"## 设计已知问题（非阻断）"（`codegen.py:889`）——通道端到端 wired，docgen 从没写它（写了 `_error`）。
- **具体误杀**：epsilon 标量被 docgen 正确渲染成 `Attr("epsilon").Float(1e-6f)`，但 gate 机械要求 inputs 每项有 `Input("epsilon")`（不认标量→Attr），3 轮全挡。

### 关联

- **P118**（review human→halt）：同源"design gate 不该 halt"（违反 step-60「设计门不 halt」），但 P118 是 review 的 human 路由 attribution，P119 是 docgen 的 OpDef canonical 检查——不同 gate、不同触发。
- **§2.9**（构造性保证优先于检查门 + 禁 discover+regenerate）；**§1.10**（gate 用 inputs 列表位置代理 Input 业务语义）；**step-60**（halt 仅 429）。
- **P120**：epsilon 提升进 inputs 是触发本 gate 误杀的直接场景；P120 治根（标量归 attrs）、P119 治 gate 不阻断，互补。

### 状态

- **已实施（2026-07-29）**。L4 `80-docgen-fail-forward-integrate-scalar-impl.md` slice A：`DocgenStage` anchor gate `_error(halt)` → 写 `design_known_issues`（source=docgen，按 source 分区不覆盖别 gate）+ `_success_updates` 放行；检查保留（虚构 OpDef 信号以 known_issue 流到 codegen/人审），只去阻断。即时验证 51d915 真实 md `missing=[]`/不 halt；UT 全量 3170 passed/7 skip。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-29 | P119 记录+实施：docgen anchor gate halt→advisory（带问题前进）。UT 3170 passed。51d915 重跑 heavy_llm 待用户确认（§3.11）。 |

## P120: integrate transition 零标量归一化致非确定性提升（标量在 inputs/attrs 间漂移）

### 事实

- **观测**：同算子 multi_add_rms_norm_dynamic_quant——batch `130f8b` 把 `epsilon` 正确归 `attrs`，batch `51d915` 提升进 `inputs[5]`（`shape:[]/format:SCALAR/default:1e-06`）。两者都过 integrate schema 检查。
- **凭什么说 integrate 该归一化**：① `IntegrateStage.transition`（`design_substages.py:1666-1701`）只做 `ArtifactSpec.parse`（required_keys），**零标量归一化**；`OperatorSpec.from_dict._route` 从未在 design_substages 调用（只 requirement `requirement.py:267`）。② 标量放置 100% 交 LLM → 非确定性；decision_log（`51d915/.../decision_log.json:12`）证据：agent 用 SKILL "IO 契约对齐 name-match" 统一处理所有参数（含 epsilon）扔进 inputs。③ 上游 `general_design` 本已正确识别 epsilon 是 attr（`general_design.json:16`），integrate 丢了分类。④ SKILL step2 无标量→attrs 指令；schema example 无 attrs。
- **`_route` 判据不够**（不能直接复用）：`operator.py:104` 判据 `"shape" not in e`（键缺失），epsilon `shape:[]`（键存在）→ 当 tensor 留 inputs，抓不住；且不能全量 `OperatorSpec` round-trip（design_spec 更丰富，会丢 platform/data_flow/templates/per-tensor semantic 等元数据）。

### 关联

- **P119**：标量提升进 inputs 触发 docgen gate 误杀；P120 治根、P119 治 gate 不阻断。**§1.2**（四把尺子：surgical in-place 搬移）。

### 状态

- **已实施（2026-07-29）**。L4 slice C：模块级 `_is_scalar_param`（判据 `role=="attr" or (role!="tensor" and (shape==[] or format=="SCALAR"))`，扩展 `_route` 抓 shape:[]）+ `_route_scalar_params`（in-place 扫 inputs/outputs 标量搬 attrs list，dict 归一、idempotent、保留元数据、不全量 round-trip、warn 可观测）+ 接入 `IntegrateStage.transition`（parse 后）+ schema example 加 attrs + SKILL step2 加标量→attrs 指令。UT 5 用例全绿。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-29 | P120 记录+实施：integrate `_route_scalar_params` 标量归一化治根 + schema/SKILL 配套。UT 全绿。 |

## P121: design 流程 input shape 无权威源——req-analysis 不物化 golden.py（SKILL 早有自检但工程层断裂）+ golden_alignment "pending" 静默流过 + 无 shape-vs-Golden 纠偏

### 事实

- **观测**：advance_step_v2（batch `20260728-134831-ccda3b/9d6e61`）halt 在 precision_debug（`aclnn input_tokens is null` EZ1001）。根因链：design_spec `input_tokens` shape 2D `[num_seqs, col]`，但 golden.py/cases.yaml 是 1D（`golden.py:66 input_tokens[:num_seqs]`）。2D 从 req-analysis 一路 verbatim 传播到 codegen → op_plugin `dim()==2` 硬化 → harness 用 cases 1D 构造 → aclnn host API 参数映射 null → EZ1001（kernel 从未执行）。
- **凭什么说是 design shape 无权威源**：
  ① **req-analysis 的 SKILL.md 早就要求 agent 读 golden.py 做 math-equiv 自检**（SKILL.md:175-198，capability `math-equiv-golden` 已声明），但 `RequirementStage._materialize_inputs`（requirement.py:127-145）**从不把 golden.py 写进 agent CWD**，`_build_analysis_prompt` 也不点名 → agent 被告知"读 golden.py"却找不到 → 只能凭"标准语义"经 resolve_ambiguity 猜 shape（猜成 2D）。**机械层断裂（golden 没物化），非缺自检**。
  ② `golden_alignment.status` 在 active schema（schema/requirement.json）只有 required_keys、无 enum；`ArtifactContract`（artifact.py:73-114）不支持 enum → agent 产的非法值 `"pending"` 被 `OperatorSpec.from_dict`/`filter_known_fields` 静默丢弃，一路流过无人查。
  ③ design 链 general-design→tiling→integrate→codegen 无 shape-vs-Golden 关卡/纠偏，2D verbatim 传播（runlog 实证"一路 verbatim 复制"）。
  ④ golden_path 在 State 早于一切 stage 就位（CLI `--golden`），但 req-analysis 从不读。

### 关联

- **P119/P120**：同为 design 段产物质量问题，但 P119/P120 是 docgen gate/integrate 标量（scalar），P121 是 input shape rank（tensor 维度）——不同缺陷类。
- **§2.9**：shape 一致性应由"下游消费上游既定前提"构造性保证（integrate design_spec 派生自 requirement）→ S2 producer 自检放 integrate（非下游 validate gate）；validate GV11 gate 经审计判 §2.9 冗余（shape 源头构造性正确 + ValidateStage 对 golden/requirement 零访问需 plumbing），**丢弃**。
- **§1.3**：req-analysis `input_contract.requires` 加 golden_path（契约诚实 + early validation；零影响：三 workflow 均挂 general-design 早已 requires golden_path，candidates 未变、triple 不新触发）。
- **§1.10/§1.2**：**shape 权威 = 需求描述**（正常开发 shape 在需求描述里；cases 是从需求描述派生的下游产物、非 shape 源，cann-bench cases-first 是异常、框架不耦合非常态）；golden 作 cross-check 旁证（非 cases）；golden_alignment 进 required_keys + 校验器（与 mutation_mode 平行：presence + 值双保险）。**四把尺子否决 validator-only**（曾为省 ~15-20 fixture 改动考虑，判为 §1.2「为了省事采用规避方案」——可维护/可扩展/可诊断/架构合理 四把 validator-only 都漏，required_keys 全过；fixture 改动是正确修复合理成本）。

### 状态

- **已实施（2026-07-29）**。L4 `81-design-shape-golden-authority-impl.md`（S1+S2）。
  - **S1 req-analysis 真根因**：`input_contract.requires` 加 golden_path；`_materialize_inputs` 物化 golden.py（镜像 reference_code）；`_build_analysis_prompt` 点名；SKILL.md golden 段补 shape_equiv_golden 自检（**需求描述 shape 权威 + golden cross-check**：不符时 golden 明确+doc 残缺→golden 修，否则问人、不自动覆盖 doc）+ checklist 项。
  - **S1-校验**：`golden_alignment` 进 `required_keys` + `_validate_golden_alignment` 校验器（拒 "pending"/畸形/缺失，与 mutation_mode 平行：presence + 值双保险）；schema/requirement.json `example` 补 golden_alignment。
  - **S2 integrate producer 自检**：`_reconcile_shape_ranks`（design_spec IO rank vs requirement 按 name 比，不符确定性修正 + warn）接入 `IntegrateStage.transition`。
- **UT**：3186 passed / 7 skipped（较 step-80 baseline 3170 +16，零回归）。
- **heavy_llm e2e（§3.11）**：golden_alignment 强制 e2e **PASS**（`test_req_analysis_selfclosure`，448s，真 glm-5.2：agent 产带 golden_alignment 的 requirement.json 过 required_keys）。shape-rank 推断（advance_step_v2 真根因）未覆盖——`add` shape 平凡；advance_step_v2 req-analysis 已 completed 无法 resume 重跑 → 留待下一含 shape 漂移的新算子端到端验证。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-29 | P121 记录+实施：req-analysis 物化 golden.py + shape_equiv 自检 + golden_alignment 进 required_keys+校验器（与 mutation_mode 平行）+ integrate shape rank producer 自检。四把尺子否决 validator-only（§1.2）。UT 3186 全绿。heavy_llm e2e 待用户确认。 |

## P122: general-design-review 经 op_dir 泄露越界查 proto-vs-golden → escalation 回 requirement 死循环（requirement 已闭环裁定）

### 事实

- **观测**：batch `20260729-141750-db504b` `ai_infra_aggregate_hidden_grad`(exec `20260729-141750-d0fb35`) 在 `requirement ↔ general-design-review` 反复（requirement-analyst spawn 3 次 / agent_stream 167 次 / escalation 1/2→2/2），耗尽后毒性前逃进 detailed-design，空转 30+ min + token。时序取证见 runlog `batch-runlog-20260729-141750-db504b.md` §2。
- **凭什么说是 review 越界 + escalation 毒性回路**（根因，runlog §2.3）：
  ① reviewer 经 prompt 注入的 `op_dir`（`design_substages.py` `_operator_section`）glob 到 cann-bench 任务树的 `proto.yaml`+`golden.py`，越界做 proto-vs-golden 比对，标 `GD-R1 target=requirement` → `design_input_invalid` → escalation 回 requirement。
  ② requirement **已正确裁定** proto-vs-golden（`math_equiv_golden` 自检通过 + `math_formula` 用 golden 序 + `unclear_items` 记录），且改不了 `proto.yaml`（用户输入只读）→ reviewer 顽固比对 proto 字面反复报**相同** issue → 死循环。
  ③ step-78 INV-A 没拦：general-design 是**开放命名空间 gate**，INV-A 只 target 级（`target∈routes`），reviewer 把 math issue 标合法 `target=requirement` 即绕过；「不查 math」只是 gate_scope `_doc` 声明性约束，无机制 enforce。

### 关联

- **P118**：同为 design gate attribution 缝（P118 是 target=human→`__halt__`；本条是 target=requirement→escalation 死循环）。step-78 修了 detailed-design validate 的同型毒性 loopback（redo_general→前逃），**遗漏 general-design review 这条 escalation 通路**。
- **两条架构原则（用户裁定）**：① `proto.yaml` 外部只读，错了不用修也不能修；② proto-vs-golden 校验归 requirement 闭环（已生效），概设 review 不该做。
- **§2.9**：「门不越界查上游」+「构造性保证优先于检查门」（用 INV-A 检查门防 LLM 越界查 math，开放命名空间防不住 → 应构造性保证 review 拿不到 proto）。
- memory `design-review-infeasible-loopback-deadloop`。

### 状态

- **已实施（2026-07-29）**。plan `snuggly-mixing-clover`（主修+兜底）。runlog §5。
  - **M1**：`_DesignSubstage.inject_op_dir` 开关 + `GeneralDesignReviewStage.inject_op_dir=False`（review prompt 不注入 op_dir → 构造性拿不到 proto/golden）。
  - **M2**：`GeneralDesignReviewStage._upstream_inputs` 物化 `requirement.json`（CR1 回填合法信息供给，无需读 proto）。
  - **B1+B2**：`graph_executor` escalate-bubble 传 gate 签名（`state._bubble_signature`）+ stagnation 原语扩到 escalation（同 signature ≥2 前逃，与 corrective 对称）。
  - SKILL.md 声明 proto 外部只读 / 比对基准 requirement.json。
- **UT**：全量 3221 passed / 7 skipped / 1 deselected（新增 `test_design_review_proto_isolation` + `test_design_routing::TestEscalationStagnation`；零回归）。
- **heavy_llm e2e（§3.11）**：**未跑**，留关键节点确认（复现 d0fb35 验证 review 不再 escalation 回 requirement）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-29 | P122 记录+实施：review op_dir 泄露致 proto-vs-golden 死循环。主修 M1（inject_op_dir=False）+ M2（物化 requirement.json）+ 兜底 B1/B2（escalation 同 signature 前逃）+ SKILL 加固。UT 3221 全绿。heavy_llm e2e 待确认。 |

## P123: design_spec 中途漂移丢失 requirement 权威字段（in-place outputs / DYNAMIC param_type）→ codegen abort / precision_debug halt

### 事实

- **观测**：batch `20260729-141750-db504b` run 完成后最终态（runlog §1.0/§6/§7）：3 算子未走到 finalize——
  - `advance_step_v2`(exec `d67f55`)/`scatter_pa_kv_cache`(exec `2f23fe`)：完成整条 design+test_design 后于 `codegen.validate_inputs` 拒 `design_spec.outputs is empty or missing`（0 iteration/2ms abort），各空耗 86min/36min。两者均 `mutation_mode=in_place`。
  - `multi_add_rms_norm_dynamic_quant`(exec `9034ae`)：codegen 出包 ok，`precision_debug/scope_guard` 判首轮 `HarnessContractError [PD-CONTRACT]: test_cases[0].inputs[0].shape must be list[int] (got [[152,7680]])` 属上游 test_design 缺陷而 halt。
- **凭什么说是 design_spec 漂移 + op_spec 有损**（根因，二次核实订正——原 runlog §7.2 "harness 读 design_spec" 系事实错误）：
  ① **P2（in-place outputs）**：requirement.json（权威，§1.3 `_validate_mutation_mode_consistency` 已校 in_place ⇔ outputs 含同名 alias，本非空）的 `outputs=[input_tokens,…]`；design_spec.json（integrate 产物）却 `outputs=[]`，alias 张量被挪进框架不认识的字段 `in_place_outputs`（`grep` 零命中，纯 agent/产物自造）→ codegen.validate_inputs（读 `state.design_spec.outputs`）拒 outputs 空。**这是真正的 codegen abort 根因。**
  ② **P3（DYNAMIC param_type / harness halt）真根因订正**：harness 校验器（`runner.py:_validate_case_form`）读的**不是** design_spec，而是 `state.requirement.op_spec`（经 `debug_service.py:122`），按位置读 `op_spec.inputs[j].param_type`。9034ae 的 requirement.json 里 x1 等输入**无 `shape` 键**（用 `shape_constraints`），`OperatorSpec.from_dict._route` 旧判据「无 shape→attr」把全部输入甩进 attrs → **`op_spec.inputs==[]`** → `inputs[0]` 越界 → `is_dynamic=False` → 拒正确的嵌套 shape。**与 design_spec.param_type 是 REQUIRED 还是 DYNAMIC 无关**（design_spec 只被 codegen/docgen 读，harness 不读）。codegen 在 REQUIRED 下**本就成功出包**（run.log `codegen done 3036.7s`），halt 100% 在 harness。
  ③ **同型根因**：design 段产物从 requirement（权威）漂移丢字段（P2）；**op_spec 投影有损**（P3）。深因是 `OperatorSpec.from_dict._route` 用「有没有 shape 键」这个**机制特征**（§1.10 禁止）当判据——标量 attr 与「无 shape 的变长/别名张量」共享该特征，后者被静默误判甩进 attrs。

### 关联

- **P121**：同型（design_spec 字段漂移）。P121 已在 IntegrateStage 加 `_reconcile_shape_ranks` producer 自检（shape rank 对齐 requirement）。P123 是**同型缺陷的另外两字段**（in-place outputs / param_type），缺同样 producer 自检——本条沿用 P121 的「requirement 为字段权威 + producer 自检就地修正」范式。
- **P122**：P122 是 review 侧越界（控制流），P123 是 design producer 自身漂移（数据流）；同 batch 不同缺陷。
- **§1.3**（加载期校验）/ **§2.9**（构造性保证/producer 自检优先于下游门）：P2/P3 本可由 design_spec↔requirement 跨字段自检构造性拦下，却落到 codegen/precision 当检查门（且太晚）。
- memory `ut-preexisting-env-failures`（baseline）/ `batch-214817-scaffolding-fixed-d1d2o2-deferred`（214817 批跑技术债，本批为其后续回归）。

### 状态

- **已实施（2026-07-30，二次根治订正）**。GLM 首版仅在 design_spec 加自检——对 P2（codegen abort）有效，对 P3（harness halt）**无效**（打错产物：harness 读 requirement.op_spec 不读 design_spec）。二次核实后落**根治**：
  - **根治 A（P3 真根因，§1.10）**：`OperatorSpec.from_dict._route` 判据从「有没有 shape 键」（机制特征）改为**业务语义**——`param_type`/`role:tensor`/in-place 别名/shape 信号 → 张量；显式标量 `type` → attr；判不了 → 保留为张量 + loud warn（§1.3 不静默丢）。op_spec 不再丢 DYNAMIC/别名张量 → `op_spec.inputs` 非空 → harness 位置映射自然对，**P3 halt 从源头消除**（不依赖 design_spec 自检）。
  - **根治 B（§2.5 唯一通路）**：删死字段 `state.op_spec`（全仓无任何生产写入点，恒 None，仅作 `A or B` 兜底壳）+ 清散落 fallback（codegen/cannbench_adapt 直接读 `requirement.op_spec`）。IO 规格权威唯一化：磁盘 requirement.json（给 LLM）+ 其无损投影 op_spec（给 Python）。
  - **P2 主修（保留，有效）**：`_reconcile_inplace_outputs`——`mutation_mode=in_place` 且 `outputs` 真空 → 从磁盘权威 requirement.json 回填 alias outputs（用同名 input shape/dtype 补全）。codegen.validate_inputs 读 `state.design_spec.outputs` → 回填后不再 abort。
  - **P3 自检重定位**：`_reconcile_param_types` 保留但**降级为纯 design_spec 防漂移**（保 codegen/docgen 生成正确 `Tensor[]` 签名），不再声称「修 harness halt」（那是根治 A 的功劳）。
  - `_load_authoritative_requirement` 读磁盘完整 requirement.json——理由订正：不是「绕开有损 op_spec」（根治 A 后 op_spec 无损），而是 `OperatorSpec` **根本不建模** `mutation_mode`/`shape_formula`，in-place 回填必须读原始 JSON。
  - **M2 订正**：review 物化改为拷**完整磁盘 requirement.json**（`_materialize_extra` + `shutil.copyfile`），非 `asdict(state.requirement)` 残缺版（丢 math_formula/golden_alignment）——兑现 SKILL「requirement.json 是 math 权威」承诺（§2.3 契约诚实）。
  - codegen.validate_inputs / harness 形态校验**保持不变**（§1.3 权威模型下正确）。
  - **四把尺子**：可维护（判据用业务语义、消歧义）/ 可扩展（**新增字段只要声明清楚 role/param_type/type 即自动归位，无需逐字段打补丁**——§1.2）/ 可诊断（判不了的 warn）/ 架构合理（根因层修 op_spec 投影，不在下游逐字段兜）。
- **UT**：`test_domain.py` 新增 4 例（DYNAMIC 无 shape 留 inputs / in-place 别名留 outputs / 判不了保留为张量 / 标量归 attr）；`test_runner_execute.py` 新增端到端 1 例（from_dict→harness 接受嵌套 shape，补 GLM 缺的「测 halt 解没解决」）；`test_design_substages.py::TestIntegrateReconcilesFieldDrift` 5 例保留；M2 测试改为断言拷完整文件。orchestration 1707 + domain 209 + 全量 2485 passed，零回归。
- **不再有遗留深因**：原「_route 有损单开跟踪」已由根治 A **就地解决**，不再延后。
- **heavy_llm e2e（§3.11）**：**未跑**，留关键节点确认（重跑 d67f55/2f23fe/9034ae 验证不再 abort/halt）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-30 | P123 记录+首版实施（GLM）：design_spec 字段漂移自检。 |
| 2026-07-30 | **二次根治订正**：核出 GLM P3 打错产物（harness 读 requirement.op_spec 非 design_spec）无效。落根治 A（`_route` 判据改业务语义，§1.10，从源头修 op_spec 有损 → P3 halt 根消）+ 根治 B（删死字段 state.op_spec，§2.5）+ P2 保留 + P3 自检重定位为纯 design_spec 防漂移 + M2 订正拷完整文件。新增 UT 含端到端 halt-fix 断言。全量 2485 passed 零回归。 |

## P124: relocation harvester 只认 SDK transcript schema → 对 opencode 越界写静默失明 + 正确副本并存时越界副本永久遗留

### 事实

- **观测**：batch `20260729-141750-db504b` 的 `advance_step_v2`(exec `d67f55`) 输出树里出现**孤儿文件** `output/…-db504b/20260729-141750-db504b/…-d67f55/artifacts/design/validate/blocking_status.json`（batch_id 被 agent 写重了一层，非框架 spawn cwd——框架 cwd 正确，见 run.log 1861 行）。
- **凭什么说是 harvester 后端 schema 失明**（根因）：
  ① validate reviewer（opencode backend）某轮用 **`write` 工具**把 `blocking_status.json` 写到了 doubled-run-id 路径（reviewer-04.jsonl 取证：`tool_input.input.filePath` = `…db504b/20260729-141750-db504b/…`）。
  ② `_harvest_relocation_evidence`（`design_substages.py`）只认 **SDK schema**：tool_name ∈ `("Write","Edit")`（大写）+ 路径在 `tool_input.file_path`。但**真实 opencode** 是 `tool_name="write"`（小写）+ 路径嵌在 `tool_input.input.filePath`（camelCase，多套一层 opencode tool-state）。→ harvester 对每一个 opencode 写**恒返回 None**，越界写**从不被检测**。
  ③ 且 relocation 门只在产物 **MISSING** 时触发（`_missing_artifact_error`）。d67f55 case 里 agent **同时**写了正确 wd 副本 AND 越界副本 → 走成功路径 → 越界副本无人清理，**永久遗留为垃圾**。
- **既有 UT 为何没拦住**：`test_harvest_works_on_opencode_produced_transcript` 喂的是**理想化** opencode part（`tool:"Write"` 大写 + `input.file_path` snake_case），非真实 schema（小写 `write` + `input.filePath` camelCase）→ 测试通过但生产失明。测试保真度缺陷（§3.10 真实性）。

### 关联

- **§1.1**（框架不耦合具体后端）：harvester 硬编码 SDK schema，未随双后端（SDK/opencode）容错。
- **§2.4**（中间产物在 wd）：越界副本违反，但无守卫清理。
- **§1.3**（加载期/运行期告警不静默）：越界写既不检测也不告警，静默遗留。
- **P123 同 batch**：P123 是 design 数据流漂移，P124 是产物落点治理；正交。

### 状态

- **已根治（2026-07-30）**：
  - `_extract_write_target`（新）：双 schema 容错——tool_name 大小写不敏感（write/edit/multiedit），路径查 `tool_input.{file_path,filePath}` + `tool_input.input.{file_path,filePath}`（opencode 嵌套）。`_harvest_relocation_evidence` 改用它。
  - `_read_disk_artifacts` 成功路径新增 `_sweep_located_strays`：产物在 wd 正确定位后，扫本 agent transcript 证据的**越界同名副本**并清除 + loud warn（§1.3）。有界安全：只删 (a) 名字匹配 (b) 本 agent transcript 证明写过 (c) 解析在 wd 外——非盲目 fs 遍历。
  - 清理了 d67f55 那个真实孤儿文件 + 空目录链。
- **UT**：新增 `test_harvest_real_opencode_schema_lowercase_nested`（真实 opencode block 形状，修前必 None 修后命中）+ `test_sweep_removes_stray_when_product_also_in_wd`（正确+越界并存时清越界）。用真实 d67f55 transcript 实证 harvester 抓到那个孤儿。orchestration+domain+adapters 2273 passed 零回归。
- **边界（不在本条）**：agent **用 bash**（heredoc/`cp`/`>` 重定向）写越界仍不被 transcript harvester 覆盖（bash command 无结构化 file_path）——本 batch 实际是 write 工具越界（已覆盖）；bash 越界属更边缘场景，若未来观测到再扩展（不预防性过度工程）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-30 | P124 记录+根治：relocation harvester 只认 SDK schema 对 opencode 越界写静默失明 + 成功路径越界副本无清理。修 `_extract_write_target` 双 schema 容错 + `_sweep_located_strays` 成功路径清越界 + 清真实孤儿。新增 2 UT（真实 opencode schema + sweep）。零回归。 |

---

## P137: turn_stall 产出活性误杀——turn_ts 仅 role=user 更新，慢但活的长单 turn 生成被误杀

### 事实

- **观测（源仓实证，随 fix 迁移落档）**：复杂 tiling 设计（buffer-kernel）的**单个 turn** 流式生成超长（14 万+ chars，>600s），但 `turn_ts` 仅 `message.updated role=user`（新 exchange）才更新；`turn_stall_s` 门限把「慢但活着」的长生成误判为死 stall 杀掉（batch 8 次全失败）。本仓为**修复迁移**：原观测属源仓 lineage，代码改动经 cherry-pick 5cd49173 迁入（ac6cdd58）。
- **根因（代码核查）**：`opencode_backend.py` `_handle_sse_event` 里 `turn_ts` 只在 `role=user`（新 exchange）时打点；`_post_message_watched` 看门狗 `(now - turn_ts) > turn_stall_s` 即判死。SSE 的 `message.part.delta`（text/reasoning）是**真实产出**但**不打点** `turn_ts` → 长生成期间 `turn_ts` 陈旧 → 误杀。
- **chars 为何是更准信号（与 P117 SSE 噪音对比）**：`chars` 只由 `message.part.delta`（text/reasoning）累加；P117 的 SSE 噪音（loop/permission/skill frame）**不带 delta、不累加 chars**——故「chars 静止」能保留 P117 的 anti-hang 语义，而「chars 增长」能识别慢但活的长生成。

### 关联

- **P117**（turn-stall 门，[[opencode-silent-swallow-gateway-error]] 家族）：本次是 P117 路线 C 的 follow-on 缺陷——门判据 `turn_ts`（仅 role=user 更新）对「单 turn 长生成」失明。修复不改变 P117 anti-hang 语义（SSE 噪音不带 delta → chars 静止 → 仍 trip）。
- **P131**（turn_stall 默认值解耦族，85-trial-20260730）：P131 处理 turn_stall 阈值与网关 timeout 耦合；本次处理 turn_stall 判据（turn_ts）对单 turn 长生成的误杀。两者正交、同为 turn-stall 误杀族。**注**：源仓将本问题标为 "P131-activity" 与本仓既有 P131 撞号，本仓改标 P137。
- **§1.11**：判据用实际产出（chars 增长）而非机制特征/探测——「慢但活着」以真实 delta 宽限。

### 状态

- **已实施（2026-08-10，cherry-pick 5cd49173 → ac6cdd58）**：`_post_message_watched` 循环内跟踪 `chars` 快照与最后增长时刻 `_last_chars_ts`；`turn_ts` 超时但 `chars` 仍在增长 → 宽限不判死；`chars` 也静止超 `turn_stall_s` → 才判死。reason 携带 `(chars static Ns)` 窗口提升可诊断性。`message_timeout` 仍是最终硬上限。
- **测试**：UT `test_p117_turn_stall_watchdog.py` 新增 2 例（`test_turn_stall_liveness_chars_growing_not_miskilled` 增长宽限 / `test_turn_stall_liveness_chars_static_trips` 静止 trip）+ 2 个既有用例 `message_timeout` 0.2→10s 消除硬上限竞争；11 passed。ST `test_turn_stall_e2e.py` 语义反转为「活跃长生成不被误杀」（heavy_llm，未实跑，§3.11）。
- **review**：ascendc-devkit-code-reviewer `reviews/cherrypick-5cd49173-turn-stall-liveness-review`（verdict=request_changes；唯一 major F1=编号冲突，已在本条落档 + 代码标注改 P137 解决；F2/F3 minor 与 F4/F5 nit 为方向性/风格记录）。

### 变更记录

| 日期 | 内容 |
|---|---|
| 2026-08-10 | P137 记录（事实）+ 实施（cherry-pick 5cd49173）：turn-stall 产出活性判据——chars 增长宽限活跃长生成。代码/测试标注原「P131-activity」（源仓编号，与本仓 P131 冲突）改标 P137。 |
