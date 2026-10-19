# 03 — 实施方案（L4）

> 符号级改动 + TDD + as-built。事实产权在 L1 `01-problems.md`，选项/决策产权在 L3
> `02-analysis.md`（选定选项 A）。本文件只记「改哪个函数、什么顺序、怎么验证」。

## 改动清单（`src/ascendc_devkit/orchestration/stages/deploy.py`）

### 改动 1 — `_smoke_script` 收敛为 fail-closed（删 torch_op/pybind 分支）

torch_op/pybind 不再用 `_smoke_script`（改走改动 2 的 harness）。`_smoke_script` 只保留
aclnn/unknown 的 fail-closed 脚本（`raise SystemExit('smoke FAIL: no execution probe ...')`）。
- 旧行（torch_op getattr / pybind import_module / aclnn / unknown 四分支）→ 单一 fail-closed。
- aclnn/unknown 诚实失败（§3.7），不伪造 OK——回归守护旧 print-only no-op false-green 漏洞。

### 改动 2 — 新增 `_build_smoke_harness`（复用 precision_debug harness 真实调用）

`Deployer._build_smoke_harness(state, callable_target, per_op_python_dir, per_op_opp_dir, ld_path)`
→ 调 `NPURunner._build_test_harness` 生成「单 case 真实调用」脚本：
- op_spec：优先 `state.requirement.op_spec` → `state.op_identity.spec` → 合成最小
  `OperatorSpec`（harness 只用 operator.name 显示，调用走 callable_target.symbol）。
- case：优先 `state.test_cases[0]`（test_design 真实验收用例，合法 shape/dtype/attrs）；
  空则合成 `[1024] fp16`（test_design skip 的 workflow 兜底）。
- `golden_contract=None` + 默认 comparer（DevkitComparer，走 FALLBACK 路径，不碰 cann-bench
  路径）——smoke 验可调用不验精度。
- `NPURunner.__new__` 绕过 `__init__` 的 NPU 探测（脚本生成不需探测，照
  `test_runner_execute._runner` 先例），设 `_chip_version`（to_soc_version 用）。

### 改动 3 — `_run_smoke` 改：补卡 + harness 路由 + JSON 判据

- 路由：torch_op/pybind → `_build_smoke_harness`；aclnn/unknown → `_smoke_script`（fail-closed）。
- env 补 `ASCEND_NPU_ID = str(state.npu_id or 0)`（镜像 `runner.py:358`；harness 内
  `set_device(npu_id)` 真正生效）。**用 `state.npu_id` hard-pin，不用 card_pool**（redeploy
  子进程不可用，瞬态不序列化）。
- subprocess 改 `[sys.executable, "-c", script]`（原 `["python", ...]`）。
- 判据：`returncode==0` 且（torch_op/pybind）`_smoke_case_error(stdout)` 为 None。
  - harness 把 case 内 kernel 异常吞成 exit 0 + `case_details[0].error`（`_harness_template.py
    :443-455`），故 returncode 单独不能当通过——这正是旧 false-green 的坑。
- `_SMOKE_TIMEOUT` 30 → 60（真实 NPU 执行首进程 import torch/torch_npu + warmup 秒级主导）。

### 改动 4 — 新增 `_smoke_case_error` 辅助

`_smoke_case_error(stdout)`：解析 harness stdout 末行 JSON，取 `case_details[0].error`。
fn() 抛异常 → 返回 error 串；正常 → None。不可解析 → None（resolution 失败已 sys.exit(1)
兜底，exit 0 无 JSON 是边界，容忍不静默 fail）。

### 改动 5 — `DeployResult.smoke_passed` docstring（`domain/verification.py`）

点明 codegen smoke 经 harness 真实调用 fn() 一次，smoke_passed=True = 可执行；aclnn/unknown
fail-closed 不伪造。字段语义本就要求真实调用（P2），改动让实现名副其实。

### 改动 6 — harness 无 golden 路径 `diff` 未定义 bug（`_harness_template.py`，真机 ST 暴露）

smoke 传 `golden_contract=None` 首次走 harness 的无 golden 分支（precision_debug 总传 golden
走 if 分支，从未暴露）。FALLBACK 的 case 末尾 `max_diff = max(max_diff, diff)`（`:420`）在
if/else 之外统一收尾，但 `diff` 只在有 golden 的 if 分支（`:347`）赋值，**无 golden 的 else
分支没赋** → `NameError: name 'diff' is not defined`。修：else 分支补 `diff = -1.0` sentinel
（对 if 分支零影响）。同步更新 `harness_devkit_golden.txt` 快照。

### 改动 7 — fallback 合成 case 按必选/可选 + attrs（真机 ST 暴露 + 用户三问导出）

真机 ST 首跑暴露 fallback 合成 case 只给单输入（add 是 x1+x2）→ `missing x2`。用户连续三问
（attrs / 必选可选 / in-place）导出根本认知（见下「合成 case 边界认知」）。fallback 改为按
`op_spec` 构造最小合法调用：只 REQUIRED tensor（`param_type != OPTIONAL`，OPTIONAL 省略让算子
用默认 None）+ 必选 attrs（`AttrSpec.default is None`）按 type 默认值（`_SMOKE_ATTR_DEFAULTS`），
可选取省略。复杂算子（必选 dtype/枚举 attr、in-place）fallback best-effort honest fail。

### 改动 8 — `test_npu.py::deployed_add` fixture 改为提供 test_cases

fixture 原本 bypass test_design（无 test_cases/op_spec）。改为提供 add 的合法 test_cases
（2 tensor），让 smoke 走 `state.test_cases[0]` 路径（与真实 pipeline test_design→codegen 同
hand-off），不依赖 fallback 合成。

## 合成 case 边界认知（用户三问导出，设计层面）

用户连续三问——**attrs（标量参数）/ 必选可选 / in-place**——合力表明：**smoke 自己合成合法
调用是无底洞**。op_spec 只携带前几维（tensor 数、必选/可选、attr 类型），不携带后几维（dtype
attr 的合法字面量、in-place output 提取、算子特定约束如 axis 越界）——这些只有 test_design
（读过 proto/golden）知道。

**结论（用户点破）**：「无 test_cases」是**伪命题**——precision_debug 的 run-cases 同样消费
`state.test_cases`，无 test_cases 它也跑不了。真实 pipeline `test_design→codegen→precision_debug`
里 test_design 先跑保证 test_cases 非空。所以：

- **smoke 真实调用靠 `state.test_cases[0]`**（test_design 处理一切算子语义）——唯一可靠且符合
  pipeline 的路径。标准 pipeline 保证它非空。
- **fallback（尽力按 op_spec 合成，用户选 B）** 只是善意兜底，真实 pipeline 永不触发；复杂算子
  honest fail 可接受（§3.7）。
- **fixture 应提供 test_cases**（像 pipeline），而非依赖 fallback——改动 8。

## TDD（先红后绿，§3.1）

被测：`src/ascendc_devkit/orchestration/stages/deploy.py`。主 UT：
`tests/ut/orchestration/test_deploy.py`。

- **替换** `TestSmokeScript`（旧 5 用例断言 getattr 片段，torch_op/pybind 改走 harness 后失效）
  → `TestSmokeFailClosedScript`（aclnn/unknown fail-closed，2 用例）。
- **新增** `TestSmokeHarnessRealCall`（4 用例）：torch_op/pybind harness 含 `kernel_fn(` 真实
  调用 + `set_device` 卡 + 无 golden 可跑 + 优先用 `state.test_cases[0]` 的 shape。
- **新增** `TestRunSmokeJudgement`（6 用例）：returncode0+无 error→通过 / **returncode0+error→
  失败**（fn raise，防 false-green 复发核心）/ returncode≠0→失败 / timeout→失败 /
  callable_target 缺失→失败 / **env 含 ASCEND_NPU_ID=state.npu_id** / aclnn fail-closed。
- **同步改** `tests/st/test_self_evolution_stages.py::TestDeployerHelpers` 两处误放的内容断言
  （旧测 `_smoke_script` torch_op）→ 测 `_build_smoke_harness` 由 callable_target.symbol 驱动。

## as-built 验证结果（2026-07-29）

| 范围 | 结果 |
|---|---|
| `tests/ut/orchestration/test_deploy.py` | 40 passed（含新增 fallback/多输入 UT） |
| `tests/ut/adapters/test_runner_execute.py` | 全绿（harness 无 golden 修复 + golden 快照更新） |
| `tests/st/test_self_evolution_stages.py::TestDeployerHelpers` | 7 passed（改后） |
| 全量 `tests/ut/` | **3216 passed, 7 skipped**（cann-bench env-gated §3.7）零回归 |
| **真机 ST** `tests/st/test_npu.py::TestNPURunnerRealExecution` | **4 passed（95s）**——`deployed_add` 的 smoke 真实调用 add(x1,x2) kernel 通过（不再是 getattr 假绿灯）+ 4 精度用例真实调用+golden 对比全过 = **codegen↔precision_debug 断裂点消除** |

真机 ST 途中暴露并修复两个真实 bug（旧 getattr smoke 必漏）：① fallback 合成 case arity/attrs
不匹配（改动 7）② harness 无 golden 路径 `diff` 未定义（改动 6）。

## 未跑（§3.11，留 PR 前节点）

- **heavy_llm e2e**（§3.11，PR 前用户决策跑）：真实 codegen→precision_debug 全流程（非 fixture
  直调），验证「smoke 通过 ⇒ precision_debug 首轮能调用」在完整 agent 链路成立。

## 复用点（§2.5 单一通路）

- `NPURunner._build_test_harness`（`runner.py:462-645`）——harness 脚本生成，零拆分复用。
- 卡 env 注入（`runner.py:356-360`）+ `set_device`（`_harness_template.py:62`）。
- TDD mock 模板：`test_runner_execute._FakeCompleted` / `_runner`。
