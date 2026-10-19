# L3 方案分析 — 算子内层修正 vs cann-bench 评测的职责分离

> **性质**：L3 方案分析。记录有哪些选项、选了哪个、为什么。调研中演进，拍板后冻结。
> **覆盖问题**：`06-problems.md` P5（三层评价机制混淆）、P6（verify 精度是 CPU 桩）。**仅覆盖 self_evolve_op**（cann-bench 专用 DeployStage 已把算子注册成 `torch.ops.cann_bench.<op>` 可调用）。
> **P7 分流**：把 P6 的真 kernel 精度扩到 `generate_ascendc`/`_dev`（该二者无"编译产物→可调用"通路）另见 `09-generate-ascendc-precision-path.md`（L3）。本文的 Step P 依赖 09 的 D6/D7（deploy 放 adapter 协议、callable_target 由 deploy 产出）。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不写 file:line、不引用会话临时文件）。
> **前身**：`codegen-loopback-analysis.md` 建立在"cann-bench 应回灌 codegen"的错误前提上，已废弃删除，本文替代。

---

## 1. 三层评价机制（用户确认的心智模型）

三种性质完全不同的评价机制，此前被塞进了 self_evolve_op 的同一条反馈回路，必须分离：

| 机制 | 成本 | 语义 | 归属层 | 是否驱动 codegen 重生成 |
|---|---|---|---|---|
| **① 算子内层修正**（build + loop-precise 快速精度校验） | 最快 | 把**单个算子**调到"能跑对" | inference-time (a)，算子自身 | **是**——这是它的本职 |
| **② cann-bench 打分**（三维一次性客观分） | 中 | 平台自进化的 **loss 信号** | training-time (b) 的 loss 函数 | **否**——只出一次分 |
| **③ 算子全量用例测试** | 最慢 | 生产中**唯一正确性标准**（ground truth） | 最终门禁 | 否——太慢，不进迭代循环 |

**②③ 的代理关系（本次澄清的核心）**：③ 是真标准但太慢，不能每次迭代都跑；故用 ② 作**快速代理（proxy loss）**驱动 training-time 迭代。类比 ML 训练：用验证集指标代替"跑完整测试集"来指导每步训练，最终才用测试集验收。

**① 的独立性**：算子自我迭代靠自身的 build 成功 + 精度对齐信号收敛，**与 cann-bench 无关**。它是 `generate_ascendc` 已有的能力（verify build/precision → codegen loopback），不该在 cann-bench 上另造一套。

---

## 2. 当前实现的错配（P5 证据的方案视角）

```
现状 pipeline:  codegen → deploy → cannbench_eval → finalize
                   ▲         │            │
                   │         │ deploy_failed（回灌）
                   └─────────┘            │
                   ▲                      │ eval_failed（回灌）← 错！把 loss 当修正触发器
                   └──────────────────────┘

问题 1：没有 verify stage → ① 内层修正回路实际是断的
        （codegen 的 build_result/precision_result 反馈通道无人喂数据）
问题 2：cann-bench 的一次性打分被路由回 codegen → ② 越界干了 ① 的活
```

- `CannbenchEvalStage` 的 `resolve_condition("eval_failed")` + `last_error` 注入 → **要删**。
- `SelfEvolveOpWorkflow.TRANSITION_TABLE` 的 `cannbench_eval: eval_failed → codegen` → **要删**。
- `DeployStage` 的 `deploy_failed → codegen` 一刀切回灌 → **改为按原因分流**（见 §4 D3：脚手架 LLM 自救、核心代码回 codegen）。
- verify stage 缺失 + `NPURunner` 精度是 CPU 桩 → **要补 verify（deploy 之后）+ 修 P6 让精度跑真 kernel**。

---

## 3. 目标态 pipeline（候选）

```
codegen → deploy(仓相关,复用) → verify(①内层修正,用已部署 op 跑真 kernel 比 golden) → cannbench_eval(②一次性打分) → finalize
   ▲          │                      │
   │          │ 脚手架失败→LLM自救→重试deploy   │ build_failed / precision_failed（① 内层修正）
   │          │ 核心代码问题↓                    │
   └──────────┴──────────────────────────────────┘（回 codegen 重生）

verify 收敛（build ok + precision ok）后才进入 cann-bench 打分。
cann-bench 打分 = 一次性，不回灌。score 就是这个算子的 loss（training-time 用）。
```

**关键顺序（P6 修正）**：verify 精度要在 NPU 上跑**真 kernel** 比对 golden，必须先把算子部署成 `torch.ops` 可调用。故 verify 插在 **deploy 之后**，精度**复用 deploy 产物**跑真 kernel，而非 `NPURunner` 另起炉灶（当前 `NPURunner` 是 CPU 桩，只跑 golden 自比，见 `06-problems.md` P6）。

原则：
- **① 复用不新造**：verify stage 已在 `generate_ascendc` 中实现（build + precision → codegen corrective loopback）。self_evolve_op 直接复用同一个 verify stage 与转移表条目，不为 cann-bench 场景另写一套。但精度必须先修 P6（跑真 kernel），否则 ① 回路即使接上也是空的。
- **② 职责单一**：cannbench_eval 只做"跑 cann-bench → 出 overall_score → 写 EvalResult"。不返回非 default 的 condition，不注入 last_error，不回灌 codegen。score==0 就是 loss==0，交给 training-time 的归因引擎处理（`04-training-time-iteration.md` §3），不在 inference-time 环路内自救。
- **deploy 复用不自造**：deploy 是仓强相关的（`build.sh → 装 opp → pip 装 whl → smoke`，注册到 `torch.ops.cann_bench`），codegen 不自造部署方式（符合 CLAUDE.md 2.7）。verify 与 cannbench_eval 都消费同一次 deploy 的产物。

---

## 4. 决策点（已拍板，2026-07-01）

### D1：self_evolve_op 插入 verify stage 作为 ① 内层修正回路 —— ✅ 插入，位于 deploy **之后**

**决策（2026-07-01 修正顺序）**：插入 verify（复用 generate_ascendc 的 build+precision→codegen corrective loopback），且 verify 位于 **deploy 之后**：`codegen → deploy → verify → cannbench_eval`。
- 理由：精度校验要在 NPU 上跑**真 kernel**，必须先经 deploy 把算子装成 `torch.ops` 可调用；故 verify 精度复用 deploy 产物，插在 deploy 之后。
- **前置阻塞 P6**：当前 `NPURunner` 精度是 CPU 桩（golden 自比、`max_diff` 恒 0、从不跑真 kernel）。verify 作为 ① 回路要真正有效，须先修 P6 让精度跑真 kernel，否则回路即使接上也拿不到精度信号。
- 复用已有能力，符合 `avoid-overdesign-prefer-reuse`。

### D2：verify 精度校验的 golden 来源 —— ✅ 用户输入、纯 State 透传、两 workflow 共用同一通道（无解析）

**决策（2026-07-01 二次修正，定稿）**：golden **由用户输入**（`--golden`），**不由 DevKit 解析/伪造/执行**。两个 workflow 共用**同一条纯透传通道**，零差异。
- **产权边界**：cann-bench 的 `tasks/level<N>/<op_name>/golden.py` 是评测框架自身的资产，由框架按自己的规则定位并执行用于 ② 打分。DevKit **不得代为执行/注入/伪造** golden——塞入错误 golden 会污染 ② 评测、使分数不可信（用户约束）。
- **通道即现状**：golden 是初始 State 的种子字段，一路透传，谁需要谁自己读——
  `用户 --golden → task_request["golden_path"] → dispatcher → State(golden_path=...) → verify.actions() 直接读 state.golden_path → PrecisionGate`。
- **两 workflow 对齐**：generate_ascendc 已在用此通道；self_evolve_op **插入 verify 后自动复用同一通道**——同样靠用户 `--golden` → State → verify，无任何差异。
- **无需解析机制**：golden 用户给什么就透传什么，**不需要** ContextStage 解析、**不需要** profile 新增 golden 字段。此前 v0.3 的"ContextStage 从 profile 约定解析"是过度设计，作废（违背 `avoid-overdesign-prefer-reuse`，且等于 DevKit 代为供给 golden，触碰产权边界）。
- **必选语义不变**：verify 契约 `golden_path` 保持 required；用户未传 → verify 入参校验失败并**诚实报错**（符合 CLAUDE.md 3.7）。不静默跳过、不降级。
- **拓扑预检不变**：dispatcher 的"`--golden` 需要 verify stage"规则保留；self_evolve_op 插入 verify 后该规则自动放行 `--golden`。
- **推翻**：v0.2 的"golden 可选降级 build-only"、v0.3 的"ContextStage/profile 解析"两版方案均作废。

### D3：deploy 失败处理 —— ⚠️ 已被 `09` 推翻（保留原文供追溯）

> **状态（2026-12-09）**：本决策的"deploy 失败按脚手架/核心代码归因分流 + LLM 自救"方案**已被 `09-generate-ascendc-precision-path.md` D7 推翻**。理由：脚手架 vs 算子的界线在 deploy 时不可靠界定，故 deploy 退回**纯确定性 stage、失败全部回 codegen（唯一 LLM 作者点），deploy 不接 LLM**。下方原文保留仅供追溯，不再执行。

**决策（2026-07-01，正当性重述）**：deploy 失败**必须**接入 LLM 自救——**理由是保 loss 信号纯净 + 归因正确**，不是"deploy 常失败"。

**为什么必须自救(而非诚实报错终止)**：pipeline 是 `codegen → deploy → verify → cannbench_eval`，deploy 在最前。deploy 失败又不修 →
- verify **跑不起来**（算子没被装成 `torch.ops` 可调用）→ ① 精度迭代根本没发生；
- 最终 cann-bench 打分低/为 0；
- **但归因错了**——分数低是**脚手架**（build.sh / `__init__.py` wrapper / CMakeLists / env / 安装）的锅，不是算子的锅。

在"loss 训练"心智模型里这是致命的：loss 必须反映**算子质量**，脚手架故障把算子判零分 = 训练信号被噪声污染，training-time 会朝错误方向迭代。故 deploy 失败必须 LLM 修脚手架，让 verify 能跑、让分数反映算子本身。

**归因边界(核心价值)——按失败原因分流**：

| 失败原因 | 处理 | 归因语义 |
|---|---|---|
| **脚手架**（build.sh/CMake/`__init__.py` wrapper/env/安装） | LLM 自救修复 → deploy 重试 → verify 能跑 | **不怪算子**——分数不该因此变低 |
| **核心代码**（codegen 产出的 op_host/op_kernel/op_api/op_plugin 四 section） | LLM **只读、禁改** → 回 codegen 重生（等价 build_failed） | **该怪算子**——分数如实变低 |

- "核心代码只读"不是限制，而是**归因正确性的保证**：脚手架问题被自动抹平（不该算到算子头上），核心代码问题**必须**流下去（该算到算子头上）。
- **路由不能一刀切删**：原计划"删掉 `deploy_failed → codegen`"作废。改为**按原因分流**——脚手架可修 → LLM 自救 → 重试 deploy；核心代码问题 → 回 codegen。判定手段（stderr 指向哪个文件 / deploy-fix agent 自报核心编译错）留 L4 定。
- **不回灌 codegen 的是"脚手架失败"**，核心代码失败**要**回 codegen——二者分流，不是全删也不是全灌。

### D4：cann-bench score==0 区分编译/精度/性能 —— ✅ 可区分，细节后议

**决策**：保留区分能力（compile/function/performance 三维）。**详细方案用户后续再详谈**——本次不落地维度分接入，只保证不丢失区分能力（现有 EvalResult 三维字段保留）。

### D5：verify 精度改为跑真 kernel（P6 修复） —— ✅ 复用 deploy 产物，不在 NPURunner 里重造部署

**决策（2026-07-01，承接 P6）**：`NPURunner` 精度校验当前是 CPU 桩（golden 自比、`max_diff` 恒 0），必须改为**导入 deploy 产物、在 NPU 上跑真 kernel、与 golden 比对**。
- **复用不自造**：真 kernel 调用走 deploy 已注册的 `torch.ops.cann_bench`（deploy 产出的 per-op opp + whl），`NPURunner` 消费该产物，不自造部署（符合 CLAUDE.md 2.7、`avoid-overdesign-prefer-reuse`）。
- **前置关系**：D5 是 D1 的前提——verify 作为 ① 回路要真正有效，须先让精度跑真 kernel，否则回路即使接上也拿不到精度信号（`precision_result` 永远 `passed=True`）。
- **依赖 deploy 在前**：故 pipeline 顺序 `deploy → verify` 是 D5 的结构前提（deploy 产物先就位，verify 才能调 `torch.ops`）。
- **诚实语义**：torch_npu/部署产物缺失 → 诚实报错（`EnvironmentNotAvailableError`），不退化成桩（符合 CLAUDE.md 3.7/3.10）。删除 `_stub_result` 的静默降级路径（除非显式 `--enable-stubbed`）。

---

## 5. 本次改动边界（L4 落地）

**无条件做（纠正混淆）**：
1. 删除 `CannbenchEvalStage.resolve_condition` 的 `eval_failed` 分支 + score==0 的 `last_error` 注入。cannbench_eval 回归"只出分"。
2. 删除 `SelfEvolveOpWorkflow.TRANSITION_TABLE` 的 `cannbench_eval: eval_failed → codegen` 条目。

**D1 + D2 + D5（插 verify 于 deploy 之后 + golden 纯透传 + 精度跑真 kernel）**：
3. self_evolve_op pipeline 插入 verify stage（**deploy 之后、cannbench_eval 之前**）+ 转移表加 `verify: build_failed/precision_failed → codegen`、`exhausted → __halt__`。
4. **verify 契约不变、golden 通道不新建**：golden 由用户 `--golden` → State → verify 直接读，两 workflow 共用同一透传通道。**不改 ContextStage、不改 profile**。插入 verify 后，dispatcher 的 `_preflight_input_topology` 自动放行 `--golden`（规则本身不变）。
5. **修 P6**：`NPURunner` 精度改为导入 deploy 产物、跑真 kernel 比 golden；删除静默桩降级（除非 `--enable-stubbed`）。这是 D1 生效的前提。

**D3（deploy LLM 自救 + 按原因分流）**：
6. DeployStage 升级：确定性链失败时接入 LLM agent 修复非核心脚手架（build.sh/CMake/`__init__.py` wrapper/env/安装），硬约束核心代码只读。**按原因分流**——脚手架可修 → LLM 自救 → 重试 deploy；核心代码问题 → 回 codegen（等价 build_failed）。不是一刀切删 `deploy_failed` 路由。

**不做（本次范围外）**：
- D4 维度分接入 training-time 归因（用户后续详谈）。
- training-time 归因引擎接入 cann-bench loss（属 training 线）。

---

## 6. 变更记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-07-01 | v0.1 | 初版：替代废弃的 `codegen-loopback-analysis.md`。确立三层评价机制分离（用户确认）；列 D1–D4 待决策点。 |
| 2026-07-01 | v0.2 | **D1–D4 拍板**：D1 插 verify；D2 golden 从 context 读、可选、不强依赖 cann-bench；D3 deploy 失败接 LLM 自救、禁改核心代码、不回灌 codegen；D4 保留三维区分、细节后议。改动边界见 §5，落 L4。 |
| 2026-07-01 | v0.3 | **D2 修正**：用户指正 golden 必选、两 workflow 必须对齐。推翻"golden 可选降级 build-only"。verify 契约不变；self_evolve_op 的 golden 由 ContextStage 从 profile 约定解析进 State（源自 cann-bench `golden.py`，经 profile 抽象不硬依赖）；解析失败诚实报错不降级。 |
| 2026-07-01 | v0.4 | **D2 定稿**：用户明确 golden 由用户 `--golden` 输入、DevKit 不解析/伪造/执行（cann-bench golden 是评测框架资产，代为执行会污染 ② 打分）。核实通道现状：golden 是 State 种子字段，`用户 → dispatcher → State.golden_path → verify 直接读`，generate_ascendc 已在用。推翻 v0.3 的"ContextStage/profile 解析"（过度设计 + 触碰产权边界）。**通道不新建**，self_evolve_op 插入 verify 后自动复用同一透传通道；Step B（解析机制）删除、并入 Step C。 |
| 2026-07-01 | v0.5 | **顺序修正 + D3 正当性重述 + 新增 D5/P6**：用户指出精度迭代须先部署再测、deploy 仓相关不自造。① verify 改到 **deploy 之后**（`codegen→deploy→verify→cannbench_eval`），精度复用 deploy 产物跑真 kernel。② **D3 收回"降级"**：deploy 失败**必须** LLM 自救修脚手架——理由是保 loss 信号纯净 + 归因正确（脚手架故障不该错怪算子降分）；核心代码只读；**按原因分流**（脚手架自救、核心回 codegen），不是一刀切删路由。③ 新增 **P6**（`NPURunner` 精度是 CPU 桩、从不跑真 kernel）+ **D5**（精度改跑真 kernel、复用 deploy 产物、删静默桩），D5 是 D1 生效前提。 |
| 2026-12-09 | v0.6 | **D3 被 `09` 推翻**：P7 分析中用户判定脚手架 vs 算子归因不可靠界定，deploy 退回纯确定性 stage、失败全回 codegen、不接 LLM。D3 的"LLM 自救 + 按原因分流"作废（原文保留追溯）。deploy 通用化 + generate_ascendc 真 kernel 通路见 `09`（L3）/`10`（L4）。本文范围收敛回 self_evolve_op 的 P5（cann-bench 一次性 loss 不回灌，已落地）。 |
