# L4 实施方案 — deploy 通用化 + generate_ascendc 真 kernel 精度通路

> **性质**：L4 实施方案。改哪个函数、什么顺序、怎么验证。动手前写。
> **上游**：`09-generate-ascendc-precision-path.md`（L3，D6-2 / D7 / D8 已定案）；覆盖 `06-problems.md` **P7**。
> **推翻**：本文取代 `08-impl-eval-correction-split.md` 的 **Step E**（deploy LLM 自救），并修正其 **Step P**（callable_target 来源）。见 §6。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不写 file:line）。TDD：先改/加测试再改实现（CLAUDE.md 3.1）。

---

## 0. 改动总览（按依赖顺序）

| 步 | 改动 | 归属决策 | 依赖 |
|---|---|---|---|
| **G1** | `codegen_manifest` schema 增 `callable_target{kind, symbol}`；codegen prompt 指引产出；State/解析透传 | D7 | — |
| **G2** | profile schema 的 `build_stage` 增 `role` 枚举（build/install_runtime/install_python/smoke）；加载期校验"deploy 必备 role" | D6-2 + D8 | — |
| **G3** | 三仓 profile.json 补 deploy role stages（cann-bench 先行，把现 DeployStage 硬编码搬进 profile） | D6-2 | G2 |
| **G4** | DeployStage 通用化：删硬编码 4 步链，改为按 profile role stages 跑 + 注入 per-op 路径 + 组装 DeployResult；smoke 按 `callable_target` 校验 | D6-2 | G1,G2,G3 |
| **G5** | deploy 失败 → `last_error(step+stderr)` → 回 codegen（删 LLM 自救分支，本就没实现）；转移表 `deploy: deploy_failed → codegen` 三 pipeline 共用 | D7 | G4 |
| **G6** | deploy 加入 `generate_ascendc`/`_dev` 的 stage 序列（`codegen → deploy → verify`）；加载期校验 profile 有 deploy role | D8 | G4 |
| **G7** | verify/NPURunner 真 kernel：读 `deploy_result`（路径+env）+ `codegen_manifest.callable_target`（符号）→ NPU 跑真 kernel 比 golden；缺失 → 报错不桩 | 承 08 Step P（修正） | G1,G4 |

顺序建议 **G1→G2→G3→G4→G5→G6→G7**。G1/G2 无依赖可并行起步。

---

## 步 G1：codegen_manifest 增 callable_target（D7）

**文件**：codegen 的 `schema/codegen_manifest.json`、codegen SKILL/prompt、`kernel/state.py`（若 manifest 结构化解析处需要）。

**改动**：
1. manifest schema 的 `required_keys` 增 `callable_target`；结构 `{"kind": "torch_op"|"aclnn"|..., "symbol": "torch.ops.<ns>.<op>"}`。
2. codegen prompt 追加指引：写完 `plugin_code`（`TORCH_LIBRARY_FRAGMENT(<ns>, <op>)`）后，**同步在 manifest 记 `callable_target`**——namespace/符号按目标仓注册约定现场定（与写 dtype 同机制，2.7）。
3. `codegen.transition` 解析 manifest 时把 `callable_target` 一并读入 `state.codegen_manifest`（现已透传 manifest，只需保证不丢字段）。

**验证**：
- UT：manifest 含 `callable_target` → 解析进 `state.codegen_manifest`；缺 `callable_target` → 加载/解析报错（D8 精神，必备）。
- UT：manifest schema 校验拒绝无 `callable_target` 的清单。

## 步 G2：profile schema 增 role + 加载期校验（D6-2 + D8）

**文件**：`resources/schemas/repository/profile.json`、`domain/repository.py`（`BuildStage`）、`profile_loader`/加载校验处。

**改动**：
1. schema 的 `build_stage` 增 `role`：枚举 `["build", "install_runtime", "install_python", "smoke"]`（默认 `"build"`，向下不留兼容——直接给所有现存 stage 显式标 role）。
2. `BuildStage` dataclass 增 `role: str = "build"`；`from_yaml` 读取。新增 `RepositoryProfile.deploy_stages(rel_op_dir)`（返回 enabled 的 install/smoke stages）+ `has_deploy_capability(rel_op_dir)`（有 install_runtime + smoke 即 True）。
3. **加载期校验（CLAUDE.md 1.3）**：非法 `role` 值由 profile schema（`_validate_profile_data`）在加载时拒绝。"deploy 必备 role 缺失"的校验**不在 profile 加载处 blanket 做**——一个仓缺 deploy role 本身不非法，只是"对 deploy-requiring workflow 不可用"；故该校验放在 **G6 的 dispatcher 组装 deploy-requiring workflow 时**用 `has_deploy_capability` 判定并报错。

**实施记录（2026-12-09）**：G2 已落地——`role` 字段 + schema 枚举 + `deploy_stages`/`has_deploy_capability` helper + 20 条 UT 绿；4 个真实 profile 加载正常、暂报 `has_deploy_capability=False`（待 G3 补 role stages）。

**验证**：
- UT：schema 接受带 role 的 stage、拒绝非法 role 值。
- UT：profile 缺 deploy 必备 role → 加载校验抛错，错误信息列出缺失项。

## 步 G3：三仓 profile 补 deploy role stages（D6-2）

**文件**：cann-bench / ops-nn(-transformer) / omni-ops 的 `profile.json`。

**改动**：
1. **cann-bench 先行**：把现 DeployStage 硬编码的 4 步搬进 profile 的 role stages——
   - `build`（现有 build stage 保留，标 role）
   - `install_runtime`：`bash {run_pkg} --quiet --install-path={per_op_opp_dir}`
   - `install_python`：`pip install --target={per_op_python_dir} --force-reinstall --no-deps {whl_pkg}`
   - `smoke`：按 `callable_target.symbol` 校验（G4 提供执行器 + 注入变量）。
2. ops-nn/omni-ops：各自注册命令（参考 `ascendc-pta` skill 现场写，本 L4 不冻结具体命令，属 2.7 外移）。omni-ops 复用其已声明的 `torch_ext` stage 位、标 role 并 `enabled:true`。

**注入变量**：DeployStage 提供的模板参数扩展——除 `{full_op_name}`/`{chip_version}` 外，增 `{per_op_opp_dir}`/`{per_op_python_dir}`/`{run_pkg}`/`{whl_pkg}`（G4 定义、注入）。

**验证**：
- UT：cann-bench profile 经 G2 校验通过、role stages 齐全。
- ST（@pytest.mark.npu/slow）：cann-bench profile 驱动的 deploy 与旧硬编码 DeployStage **等价**（对 `add`/`exp` 产出相同 DeployResult 路径 + smoke_passed）。

**实施记录（2026-12-09）**：**cann-bench 先行已落地**——4 个 role stage（build/install_runtime/install_python/smoke）写进 profile，`has_deploy_capability=True`，role 顺序正确，UT 绿。**ops-nn/ops-transformer/omni-ops 暂缓**：其 per-op 安装路径映射（omni-ops 用全局 `${ASCEND_OPP_PATH}` vs cann-bench 的 per-op `--install-path`）、`torch.ops.custom.npu_{op}` 注册的确切命令依赖各仓现场（`ascendc-pta` skill 记录了 shape 但 per-op 隔离细节需目标仓在手才能验证）。按 CLAUDE.md 2.7 + D8"不桩/不猜"，这三仓的 deploy role 留待在目标仓在手时现场补齐；补齐前 G6 的 dispatcher 对这三仓的 deploy-requiring workflow **诚实报错**（`has_deploy_capability=False`），不猜命令、不桩。

## 步 G4：DeployStage 通用化（D6-2）

**文件**：`stages/deploy.py`；执行 role stages 的逻辑可复用/类比 `GenericRepositoryAdapter` 跑 stage 的机器（单一数据驱动方法，非 per-repo）。

**改动**：
1. **删** `_run_deploy_chain` / `_step_build` / `_step_install_opp` / `_step_install_whl` / `_step_smoke` 的**硬编码 cann-bench 逻辑**（build.sh 路径、`examples/aclnn_launch_example` 约定、`import cann_bench`、写死 `torch.ops.cann_bench`）。
2. `transition` 改为：
   - 选 variant（复用 `profile.select_variant`）。
   - 计算 per-op 路径（保留 `_per_op_path`，与注入变量对应）。
   - 按 role 顺序跑 `build → install_runtime → install_python`，每步渲染 `command_template`（注入 §G3 变量），任一失败 → `DeployResult(smoke_passed=False)` + 记 `last_error(step+stderr)`。
   - **smoke 按 `callable_target` 校验**：从 `state.codegen_manifest.callable_target` 取 `kind`/`symbol`，构造 smoke 脚本（`torch_op` → import 后解析 `symbol`；`aclnn` → 对应校验）。**删写死 `import cann_bench`**。
   - 组装 `DeployResult{install_path, python_path, ld_library_path_add, smoke_passed, run_package, wheel_package}`。
3. `LD_LIBRARY_PATH`/`ASCEND_CUSTOM_OPP_PATH` 组装（`_cann_lib_paths` 保留，通用）。

**验证**：
- UT：给 stub profile（含 role stages）+ manifest，`transition` 按 role 顺序渲染命令、注入 per-op 变量（命令字符串断言）。
- UT：smoke 脚本按 `callable_target.symbol` 解析（断言脚本内容含该符号，不含写死的 `cann_bench`）。
- UT：install 步失败 → `smoke_passed=False` + `last_error` 携带失败步骤 + stderr。

**实施记录（2026-12-09）**：G4 落地。DeployStage 改为 `transition` 选 variant → 计 per-op 路径 → 按 role 顺序跑 build/install_runtime/install_python（注入 `{run_pkg}/{whl_pkg}/{per_op_opp_dir}/{per_op_python_dir}`）→ smoke 按 manifest.callable_target。删净 cann-bench 硬编码。**真实验证**：对 cann-bench 的 `add` 跑通完整链（build→install→smoke_passed=True）。**关键发现**：`torch.ops.<ns>.<op>` 惰性注册——op 在被 `getattr` 访问前不出现在 `dir(ns)`，故 smoke 用 `getattr` 探测（触发 C++ TORCH_LIBRARY 解析）而非 `dir()` 成员判断。

## 步 G5：deploy 失败全回 codegen（D7）

**文件**：`stages/deploy.py`（`resolve_condition`/`transition`）、各 workflow 的 `TRANSITION_TABLE`。

**改动**：
1. `resolve_condition` 保留返回 `"deploy_failed"`（smoke 未过时），**不做归因分流**（无 `core_build_failed` 之分——D7 取消）。
2. `transition` 在任一步失败时写 `last_error(error_type="deploy_failed", step, stderr)`，喂 codegen loopback（codegen 已有"修正任务"分支消费 `last_error`）。
3. `SelfEvolveOpWorkflow` + `generate_ascendc`/`_dev` workflow 的 `TRANSITION_TABLE` 统一含 `"deploy": {"deploy_failed": ("codegen", "corrective")}`。
4. **删**任何 deploy-fix agent 相关设想（08 Step E，本就未实现，确保不落地）；deploy 保持无 agent 的确定性 stage。

**验证**：
- UT：deploy 失败 → `resolve_condition == "deploy_failed"`；转移表路由回 codegen；`state.last_error` 含 step+stderr。
- UT：deploy 无 agent Action（`actions()` 返回 `[]`）。

**实施记录（2026-12-09）**：G5 落地。deploy 失败任一步写 `last_error(deploy_failed, step, stderr)`；三条 pipeline 转移表统一 `deploy: deploy_failed → codegen`。无 deploy-fix agent、无核心只读守护（D3/Step E 作废）。

## 步 G6：deploy 加入 generate_ascendc/_dev pipeline（D8）

**文件**：`workflow.py`（`generate_ascendc`/`_dev` 的 stage 名单 + root after_names + 转移表）、dispatcher 加载期校验。

**改动**：
1. `generate_ascendc`/`_dev` 的 stage 序列插入 `deploy`：`codegen → deploy → verify`（deploy 在 verify 前，verify 精度靠 deploy 产物）。
2. root `after_names` 同步。
3. 转移表加 `deploy: deploy_failed → codegen`（G5）。
4. **加载期校验（D8）**：dispatcher 组装 workflow 时，校验目标仓 profile 含 deploy 必备 role（G2）；缺 → 报错（该仓无可调用通路，须先建 deploy），**不跳过、不桩**。

**验证**：
- UT：`generate_ascendc`/`_dev` 的 flat_stages 含 deploy，位置在 codegen 后、verify 前。
- UT：目标仓 profile 缺 deploy role → dispatcher 加载报错。

**实施记录（2026-12-09）**：G6 落地。`_PIPELINE_STAGE_NAMES`/`_DEV_STAGE_NAMES` + 两 root after_names 插入 deploy（codegen→deploy→verify）。dispatcher 新增 `_preflight_deploy_capability`：workflow 含 deploy stage 且 profile 可在 dispatch 期解析（repo_profile + rel_op_dir）时，`has_deploy_capability=False` → `EX_USAGE` 报错；不可解析时延到 DeployStage 运行期校验。

## 步 G7：verify/NPURunner 真 kernel（承 08 Step P，修正 callable_target 来源）

**文件**：`adapters/npu/runner.py`（`_build_test_harness`/`execute`/`_stub_result`）、`stages/verify.py`（evidence 组装）。

**改动**：
1. **harness 真跑 kernel**：设置 deploy 产物 env（`PYTHONPATH`=per-op python、`ASCEND_CUSTOM_OPP_PATH`、`LD_LIBRARY_PATH`，复用 deploy 的路径约定）；**按 `codegen_manifest.callable_target` 调符号**（不再写死 `torch.ops.cann_bench`），在 NPU 上以相同输入跑 kernel；`diff = |kernel_out - golden_out|` 写真 `max_diff`。删 `results[shape]=0.0` 占位 + TODO。
2. **verify.actions() 组 evidence 增两项来源**：`state.deploy_result`（路径+env）+ `state.codegen_manifest.callable_target`（符号）。二者缺任一 → 精度**诚实报错**（`EnvironmentNotAvailableError` 类比），不桩。
3. **删静默桩降级**：`_stub_result` 仅 `--enable-stubbed` 显式启用；默认 torch_npu/产物/符号缺失 → 抛错（CLAUDE.md 3.7/3.10）。

**验证**：
- ST（@pytest.mark.npu）：**P7 核心守护**——已 deploy 的 `add` 算子，正确 kernel + `a+b` golden → `max_diff` 容差内 `passed=True`；`add` + `a-b` golden → `max_diff` 超容差 `passed=False`。证明精度不再恒真。
- UT：harness 脚本含按 `callable_target.symbol` 的调用 + deploy env（字符串断言，不含写死 `cann_bench`）。
- UT：无 `--enable-stubbed` 且产物/符号缺失 → `execute()` 抛 `EnvironmentNotAvailableError`（不返回桩）。

**实施记录（2026-12-09）**：G7 落地。`execute()` 增 `deploy_result`/`callable_target`/`precision_threshold` 参数：缺 python_path 或 callable_target → 抛 `EnvironmentNotAvailableError`（不桩）；子进程注入 deploy env；`passed = max_diff <= threshold`（真精度判定，非"harness 跑通即过"）。harness 重构为**数据驱动 n-ary**：test_cases 序列化后逐 case 把所有输入位置传给 kernel 和 golden（支持 `add(a,b)`/`rope(x,cos,sin,mode)`，不再限一元）。verify.actions() evidence 增 `deploy_result` + `callable_target`；input_contract 增 `deploy_result`/`codegen_manifest` required。**真实 NPU 验证**：deploy `add` 后，`a+b` golden → passed/max_diff=0.0；`a-b` golden → not passed/max_diff=1.92。桩 `max_diff=0` 彻底消除。

---

## 测试影响面（TDD 先行）

- `tests/st/test_self_evolution_stages.py`：DeployStage 通用化后的 transition 断言（按 profile role 跑、smoke 按 callable_target）；deploy 失败 → deploy_failed + last_error。
- `tests/ut/orchestration/test_workflow.py`：`generate_ascendc`/`_dev` stage 序列含 deploy（codegen→deploy→verify）；三 pipeline 转移表含 `deploy: deploy_failed → codegen`。
- `tests/ut/application/test_application.py`：目标仓 profile 缺 deploy role → dispatcher 加载报错；`--golden` 拓扑预检对含 verify 的三 pipeline 放行。
- `tests/st/test_npu.py`：3 个 `@npu` 用例从 `gelu`（未部署）**演进**到已 deploy 的 `add`——正确 kernel `passed`、错误 golden `not passed`（替换现依赖 harness 假 `max_diff=0` 的断言）。
- profile schema role 校验 UT；codegen_manifest callable_target 解析 UT。

全量：UT + ST 必须全绿（CLAUDE.md 3.2），npu/llm/heavy_llm 标签不跳过。

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-12-09 | 初版：承接 09（D6-2/D7/D8 定案）。G1–G7 七步：manifest 加 callable_target、profile 加 role + 加载校验、三仓补 deploy role、DeployStage 通用化、deploy 失败全回 codegen、deploy 进 generate_ascendc pipeline、verify 真 kernel 按 manifest 符号调用。明列推翻 08 Step E、修正 08 Step P 的 callable_target 来源。 |
| 2026-12-09 | **G1–G7 全部落地**：1421 UT + 100 ST（含 @npu/@slow 真 kernel 精度守护）全绿。cann-bench 先行（ops-nn/omni-ops deploy role 待目标仓在手补齐）。真实验证：`add` 部署+精度守护（a+b 过 / a-b 挂，max_diff 1.92）。关键发现：torch.ops 惰性注册 → smoke 用 getattr 探测；harness 重构为 n-ary 数据驱动。 |
