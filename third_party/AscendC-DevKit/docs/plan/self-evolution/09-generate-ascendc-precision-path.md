# L3 方案分析 — deploy 通用化 + generate_ascendc 的"编译产物 → 可调用 kernel"通路

> **性质**：L3 方案分析。记录有哪些选项、选了哪个、为什么。调研中演进，拍板后冻结。
> **覆盖问题**：`06-problems.md` **P7**（P6 是全 workflow 通病；`generate_ascendc`/`_dev` 无 path-to-callable、无调用目标描述符）。
> **与 07 的边界**：`07-eval-vs-correction-analysis.md` 只覆盖 **self_evolve_op** 的 P5/P6。本文覆盖 **P7 —— 把 deploy 通用化并把真 kernel 精度扩到三条 pipeline**。**本文的 D6/D7/D8 推翻 07 的 D3 与 08 的 Step E**（deploy LLM 自救 + 按原因分流已作废，见 §5）。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不写 file:line、不引用会话临时文件）。

---

## 1. 问题框定 + 两个决定性事实

`verify` 被三条 pipeline 共享。要把 verify 精度从 CPU 桩（`max_diff` 恒 0）改成"跑真 kernel 比 golden"，前提是算子**已被部署成可调用符号**。现状只有 self_evolve_op 有 `DeployStage`（写死 cann-bench），`generate_ascendc`/`_dev` 止于 `adapter.build()` 就地编译，无部署/注册。

**调研确认的两个决定性事实（重塑了全部三个决策）**：

- **F1｜codegen 已经在写注册代码**：`plugin_code` section = 带 `TORCH_LIBRARY_FRAGMENT(<ns>, <op>)` 的 `.cpp`，由 **codegen agent 产出**。即"该注册到哪个 namespace / 什么符号"这一知识**本就由 codegen 现场从参考算子学到并落进代码**——和它现场学 dtype、CMakeLists 同机制（CLAUDE.md 2.7）。
- **F2｜codegen 已经在出结构化清单**：codegen 产出 `codegen_manifest.json`（`op_name`/`inputs`/`outputs`/`attrs`/`supported_dtypes` 等**实际采纳**的签名），是下游 stage（cannbench_adapt/eval）的**权威签名源**（P4 定：下游读 manifest、禁止跨 stage 重新推导）。

F1+F2 直接回答用户 D7 的追问——"该调什么符号"不该由 deploy 产出，**应由 codegen 在 manifest 里声明**（它是符号的作者）。

---

## 2. D6：deploy 是"可共用的抽象能力"，仓特定部分放哪？

**用户定调**：deploy 是**一个可共用的抽象能力**，实现可按 cann-bench / ops-nn / ops-transformer / omni-ops 各仓方式；但**整个流程直接下沉到 `CannbenchAdapter` 不妥**（只是把 monolith 换个地方）。

**分解 deploy——哪些不变、哪些随仓变**：

| 层面 | 内容 | 是否随仓变 |
|---|---|---|
| **骨架（不变）** | 序列 `build → install/register → smoke → 组装 DeployResult`；`DeployResult` 契约（verify 要的 per-op python/opp 路径 + LD_LIBRARY_PATH + smoke_passed）；smoke 语义 = "解析 `codegen_manifest.callable_target` 能 import/可调" | 否——三仓一致 |
| **仓特定（变）** | 具体 install/register 命令、per-op 路径产出、env 追加项 | 是——cann-bench 装 opp+whl、ops-nn/omni-ops 各自注册路径 |

骨架必须**留在唯一的通用 `DeployStage`**（CLAUDE.md 2.5 同一职责一条通路）；争的是**仓特定步骤放哪**。

### 决策：D6-2（profile 声明式 install stages）✅ 定案 2026-12-09

**架构现状（拍板的决定性依据）**：仓库现在是 **单一 `GenericRepositoryAdapter` + N 份 profile.json** 的数据驱动架构（2026-06-08 重构明确决定）。profile.json 已支撑四件事，**全部与 deploy 无关且删不掉**：
- **build**：`adapter.build()` 就是读 `build_variant.stages` 逐个跑 `command_template`——这是所有仓当前唯一的编译通路。
- **op 命名**：`op_naming.prefix` 推导 `full_op_name`。
- **变体选择**：`match_prefix` 判定算子属哪个子树。
- **参考搜索 + 仓识别**：`reference_roots` / 用 `name` 匹配 op_dir 路径段。

**D6-2 做法**：deploy 的 install/register 是往 `build_variant.stages` 里增加带 **typed role** 的阶段，仍由通用 adapter 照跑，**零新增类**：
```
profile.json 的 build_variant.stages 扩 typed role:
  [{name, role: "build",           command_template, ...},
   {name, role: "install_runtime", command_template, ...},   ← per-op opp 目录经 --install-path 注入
   {name, role: "install_python",  command_template, ...},   ← per-op python 目录经 --target 注入
   {name, role: "smoke",           ...}]                     ← 按 codegen_manifest.callable_target 校验
DeployStage(通用): 按 role 跑 enabled stages → 组装 DeployResult{install_path, python_path, ld_library_path_add, smoke_passed}
```
- **与既有架构自然延续**：`build()` 本就是"读 profile 命令模板来跑"，deploy 只是多几个 role 的 stage；omni-ops 已有的 `torch_ext` stage（`enabled:false`）就是天然锚点。符合 CLAUDE.md 1.5（增删资源只改清单）。
- **per-op 路径不别扭（推翻 v0.1 的顾虑）**：cann-bench 的 `.run --install-path=<per_op_opp>` / `pip install --target=<per_op_python>` 里的 per-op 路径是 **DevKit 算好注入的模板参数**（与现有 `{full_op_name}`/`{chip_version}` 同机制），`DeployResult` 里的路径 = 注入进去的那个值，**不是从命令输出解析**。typed role 正好告诉 DeployStage "这一步 `--target` 的值就是 python_path"。故不违背 profile"不记可变路径"——profile 记的是**命令模板**，运行期路径由 DevKit 注入，与 build 现状一致。

**为何否决 D6-1（adapter 窄原语）**：
- 删不掉 profile 那套（build/命名/变体/参考搜索都靠它），D6-1 只是**额外新增** deploy 方法，profile 机器原样保留——不省。
- 要给每仓写 `CannbenchAdapter`/`OpsNNAdapter` 子类 = **推翻 6 月"单一通用 adapter"决定**。
- 造成**双源分裂**：同一个仓，编译步读 profile 命令模板、部署步读 adapter 代码——两套来源，违背可维护。

**为何否决 D6-3（per-repo `adapter.deploy()` 全下沉）**：骨架被复制 N 份，违背 CLAUDE.md 2.5。

**加载期校验（配合 D8）**：profile 缺 install/smoke role 的 deploy stage → **加载期校验报错**（CLAUDE.md 1.3），不留到运行期。schema 增 `role` 枚举 + "deploy 必备 role" 的校验规则。

---

## 3. D7：不做归因分流，全部回 codegen；callable_target 进 manifest

**用户定调**：deploy 失败是脚手架还是算子问题**不好界定**，与其在 deploy 里接 LLM 做归因分流（原 07 D3 / 08 Step E），**不如全部交给 codegen 解决**——deploy 因此**不接入 LLM，退回纯确定性 stage**。

**这为什么对（四把尺子）**：

- **可维护**：脚手架 vs 算子的界线在 deploy 时确实模糊（build.sh 报错可能根因在 kernel 代码）。取消这条界线 = 取消一个不可靠的判定。**唯一 LLM 作者点 = codegen**，唯一确定性门 = deploy，失败只有一个去处。
- **架构合理**：codegen 是所有代码（含 `plugin_code` 注册、脚手架 wrapper）的**唯一作者**。deploy 失败回 codegen = 回到唯一能改代码的地方，天经地义。deploy 不再需要 deploy-fix agent、不需要"核心代码只读"的 mtime/hash 守护（那套是为归因分流服务的，一并作废）。
- **可诊断**：deploy 确定性链失败 → 把失败步骤 + stderr 作为 `last_error` 喂回 codegen 的 loopback prompt（codegen 已有"修正任务"分支）。信号不丢、不静默。
- **可扩展**：新仓 deploy 失败同样回 codegen，无需为每仓设计归因规则。

**"该调什么符号"随之解决（用户的洞察）**：既然回 codegen、且 codegen 是注册代码作者（F1），则**callable_target 由 codegen 在 `codegen_manifest.json` 里声明**最自然：

```
codegen_manifest.json 增字段:
  "callable_target": {
    "kind": "torch_op",                       # torch_op | aclnn | ...
    "symbol": "torch.ops.cann_bench.exp"      # codegen 现场按参考算子/目标仓约定定型
  }
```
- **符号的作者声明符号**：codegen 写 `TORCH_LIBRARY_FRAGMENT(cann_bench, exp)`，就在 manifest 同步记 `torch.ops.cann_bench.exp`。ops-nn/omni-ops 算子由 codegen 按各仓注册约定写代码、同步记各自符号。
- **verify 从 manifest 读**（符合 P4：下游读 manifest 权威签名，不重新推导）。deploy 只产出**路径 + env + smoke_passed**，**不产 callable_target**（推翻本文 v0.1 的 D7-B："deploy 产出描述符"作废）。
- **smoke 用 manifest 校验**：deploy 的 smoke 步 = 按 `codegen_manifest.callable_target.symbol` 尝试 import/解析，验证注册确实生效——把 manifest 声明与实际部署对上，对不上即 deploy 失败 → 回 codegen。

---

## 4. D8：deploy 是关键步骤，无则报错，禁止跳过/打桩

**用户定调**：deploy 是关键步骤，没有就报错，**禁止跳过或打桩**。

- deploy 成为**三条 pipeline 的必备 stage**（`codegen → deploy → verify`），不是 self_evolve_op 专属。
- 某仓 adapter 未实现 deploy 原语（D6-1）/ profile 未声明 install stages（D6-2）→ **加载期校验失败并报错**（CLAUDE.md 1.3：配置合法性加载时校验），不留到运行期；绝不"无 deploy 能力就桩/跳过"。
- deploy 运行期失败 → 回 codegen（D7），不桩、不静默降级（CLAUDE.md 3.7/3.10）。
- **推翻本文 v0.1 的 D8-B**："无 deploy 能力的仓 verify 精度诚实报错 + 分期"作废——deploy 现在是**所有仓的必备能力**，不是可缺省的优雅降级项。要跑 generate_ascendc/_dev 的 verify，就**必须先给该仓建 deploy 通路**（这正是"一并修"的含义）。

---

## 5. 对 07/08 的推翻（唯一通路，不留旧债 — CLAUDE.md 1.4/2.5）

| 原方案 | 处置 |
|---|---|
| 07 **D3**（deploy 失败 LLM 自救、核心代码只读、按原因分流） | **作废**——D7 取消归因分流，deploy 退回纯确定性、失败全回 codegen |
| 08 **Step E**（DeployStage 接 deploy-fix agent + `core_build_failed` 分流 + mtime/hash 守护 + `.claude/agents/deploy-fix.md`） | **作废**——不新增 deploy-fix agent；不做核心代码只读守护 |
| 08 **Step P**（NPURunner 真 kernel 读 `state.deploy_result` 的 callable_target） | **修正**——callable_target 改从 `codegen_manifest` 读（D7），deploy_result 只提供路径+env |
| 07/08 DeployStage 写死 cann-bench | **作废**——DeployStage 通用化（D6），cann-bench 逻辑进 cann-bench adapter 原语（D6-1）或 profile stages（D6-2） |
| self_evolve_op 转移表 `deploy: deploy_failed → codegen` | **保留并推广**——三条 pipeline 的 deploy 失败都 `→ codegen`（不再有 `core_build_failed` 之分） |

冻结后 07/08 需回改：07 的 D3、08 的 Step E 标注"被 09 推翻"，08 Step P 的 callable_target 来源改注 manifest。

---

## 6. 目标态（候选，D6 待选 1/2）

```
codegen (唯一 LLM 作者):
    写 host/kernel/api/plugin_code(含 TORCH_LIBRARY_FRAGMENT 注册)
    出 codegen_manifest.json{signature..., callable_target{kind, symbol}}   ← D7 新字段

deploy (通用 DeployStage, 三 pipeline 必备 — D8):
    D6-1: adapter.install_runtime/install_python/env_additions 窄原语
       或 D6-2: 按 profile 的 typed-role install stages
    骨架: build → install/register → smoke(按 manifest.callable_target 校验) → DeployResult
    失败 → last_error(step+stderr) → 回 codegen (D7, 无 LLM 自救)
    加载期: 该仓无 deploy 能力 → 校验报错 (D8, 不桩)

verify / NPURunner (承 07/08 Step P):
    读 state.deploy_result(路径+env) + codegen_manifest.callable_target(符号)
    → NPU 跑真 kernel 比 golden → 真 max_diff
    deploy_result 缺失 → 报错(不桩, D8)
```

---

## 7. 本文不做（范围外）

- **各仓 install/register/smoke 的具体命令模板**：仓特定，参考 `ascendc-pta` skill 现场写进各仓 profile.json 的 role stages，不在本 L3 冻结（2.7）。本文只定**骨架归属（D6-2）+ callable_target 归属（D7）+ 必备性（D8）**。
- **training-time 归因、D4 维度分**：见 07 / `04-training-time-iteration.md`。

---

## 8. 待决清单（拍板后冻结，产出 L4 `10-*`）

- [x] **D6**：骨架留通用 DeployStage；仓特定部分 = **D6-2（profile 声明式 typed-role install stages）**——**定案 2026-12-09**（否决 D6-1 双源分裂 / 推翻单一 adapter，否决 D6-3 骨架复制）。
- [x] **D7**：deploy 退纯确定性、失败全回 codegen（不接 LLM）；callable_target 进 `codegen_manifest`——定案。
- [x] **D8**：deploy 三 pipeline 必备，profile 缺 role 加载期报错、失败不桩——定案。
- [ ] 冻结后写 L4 `10-*`（profile schema 加 role / codegen_manifest 加 callable_target / DeployStage 通用化 / verify 读 manifest 的具体改法 + TDD 顺序 + 验证），并回改 07（D3 作废）/08（Step E 作废、Step P callable_target 来源修正）。

---

## 9. 变更记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-12-09 | v0.1 | 初版：覆盖 P7。列 D6（deploy 放 adapter 协议）/D7（callable_target 由 deploy 产出）/D8（无 deploy 仓诚实报错 + 分期）三倾向。 |
| 2026-12-09 | v0.2 | **按用户三条反馈重塑**：① 调研确认 F1（codegen 已写注册代码）/F2（codegen 已出 manifest）。② **D6** 重写——deploy 是共用抽象能力，骨架留唯一通用 DeployStage，仓特定部分在 D6-1/D6-2 间待选（排除全下沉 cann-bench adapter）。③ **D7** 反转——取消归因分流，deploy 退纯确定性、失败全回 codegen、不接 LLM；callable_target 改由 **codegen_manifest** 声明，推翻 v0.1 的"deploy 产出描述符"。④ **D8** 收紧——deploy 三 pipeline 必备、加载期校验、失败不桩，推翻 v0.1 的"无 deploy 仓诚实报错 + 分期"。⑤ 新增 §5 明列**推翻 07 D3 / 08 Step E**。 |
| 2026-12-09 | v0.3 | **D6 定案 D6-2**：核实架构现状为"单一 GenericRepositoryAdapter + N 份 profile"，profile 已支撑 build/命名/变体/参考搜索（删不掉）。D6-1 会推翻单一 adapter 决定、造成 build 读 profile / deploy 读代码的双源分裂，故否决；D6-2 是既有数据驱动架构的自然延续（deploy = 多几个 typed-role stage），且 per-op 路径本就是 DevKit 注入的模板参数、不违背"profile 不记可变路径"。§2 改写为定案，§6/§8 同步。 |
