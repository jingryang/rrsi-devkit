# L4 实施方案 — codegen 构建职责归属（方案 2：agent 只写码 + python 编译-注入循环 + 保留 ccec 验 API）

- 层级：**L4 / 实施方案**。改哪个函数、什么顺序、怎么验证。
- 上游：`docs/plan/codegen-build-ownership/01-problems.md`（L1 P1/P2 事实）、
  `02-analysis.md`（L3，**已拍板冻结 2026-09-05**，决策 D1–D7）。
- 状态：**已实施（2026-09-05）**。改动 1-4 全部落地 + UT 守护 + 既有测试适配。见文末「实施记录」。

## 改动 1 — Deployer 拆独立 `compile()`（只 build，不装系统不 smoke）

> **边界（决策 D4/D5/D7）**：禁轮次纪律；保留读 Bash + ccec 单文件（保质量）；不做命令级硬闸
> （纯 prompt/skill 软引导）。本 L4 不涉及 agent manifest 工具声明改动、不涉及命令墙。

---

## 改动 1 — Deployer 拆独立 `compile()`（只 build，不装系统不 smoke）

### 目标

让「只编译验证、不触发安装/污染」成为 Deployer 的一等入口。现状 `_run_build_install`
（`deploy.py:960`）把 build + install 绑定：build 段产出 `dist/*.run + *.whl`（`:995-1013`），
install 段装到 per-op dirs（`:1016-1027`）。

### 改动

**1a.** `_run_build_install` 加 `build_only: bool = False` 参数。在 `tvars["run_pkg"] = run_pkg;
tvars["whl_pkg"] = whl_pkg`（`:1012-1013`）之后、install 段（`:1015`）之前插入：

```python
# 只编译验证（方案 2 D6）：build 出 .run/.whl 后即返回，不装系统不 smoke。
# run_pkg/whl_pkg 已在 DeployResult 携带，调用方（codegen transition）可据产物路径
# 决定下一步（compile 过 → 再 install+smoke，复用本产物，不重 build）。
# 【质疑后修正】install_path/python_path 留空——compile() 未 install，不得带非空值误导
# 下游以为装好了（§1.2 不留误导信号）。只带 run_package/wheel_package + source_identity。
if build_only:
    return (
        DeployResult(
            run_package=run_pkg, wheel_package=whl_pkg,
            smoke_passed=False, source_identity=inputs.source_identity,
        ),
        None,
    )
```

**1b.** 新增公开入口 `compile()`：

```python
def compile(self, state: State, clean_build: bool = False,
            ) -> tuple[DeployResult, ErrorFeedback | None]:
    """build only（方案 2 D6）——不 install、不 smoke。产物 .run/.whl 落在 build cwd/dist。

    codegen transition 用它做「编译验证门」：compile 错 → resume agent 修；compile 过 →
    才调 install+smoke（deploy 后半段）。与 build_install() 的区别：build_install 会 install
    （cannbench_adapt 用）；compile() 只到 build，物理不装系统。
    """
    inputs, err = self._resolve(state)
    if err is not None:
        return DeployResult(smoke_passed=False), err
    self._programming_model = chip_programming_model(
        getattr(state, "design_target_chip", "") or "")
    return self._run_build_install(state, inputs, clean_build=clean_build,
                                   build_only=True)
```

**1c.** `clean_build` 语义保留：build 段前清 `variant.clean_dirs`（`deploy.py:987-993`），
compile() 首次编新算子仍需 clean（CMake GLOB 缓存），与现状一致。

**1d.** 新增 `install_and_smoke(state, compile_result)`——**跳过 build 段，用 compile 已产出的
产物 install + smoke**（build/install/smoke 三段按需组合，质疑后修正：复用产物不重 build）：

```python
def install_and_smoke(self, state: State, compile_result: DeployResult,
                      ) -> tuple[DeployResult, ErrorFeedback | None]:
    """用 compile() 已产出的 .run/.whl 做 install + smoke（跳过 build 段）。

    codegen transition 用它实现「先 compile、compile 过才 install+smoke」，且不重 build
    （质疑后修正：compile 产物直接复用）。compile_result 须带 run_package/wheel_package。
    """
    inputs, err = self._resolve(state)
    if err is not None:
        return DeployResult(smoke_passed=False), err
    self._programming_model = chip_programming_model(
        getattr(state, "design_target_chip", "") or "")
    run_pkg = compile_result.run_package or ""
    whl_pkg = compile_result.wheel_package or ""
    if not run_pkg:
        return (DeployResult(smoke_passed=False),
                self._err("build", "install_and_smoke: compile_result 无 run_package"))
    tvars = dict(inputs.tvars); tvars["run_pkg"] = run_pkg; tvars["whl_pkg"] = whl_pkg
    # install 段（复用 _run_build_install 的 install 逻辑，改为传入产物；或抽 install-only helper）
    # → _run_smoke_phase(...)。实现细节：把 _run_build_install 的 install 循环 + _run_smoke_phase
    # 抽成可复用片段，_run_build_install / install_and_smoke 共用（§1.15 单点）。
    ...
```

> 这段引出一个实现决策：install 段循环（`deploy.py:1016-1027`）应从 `_run_build_install` 抽成
> 独立 helper（如 `_run_install_stages(inputs, tvars)`），`build_install()` 和 `install_and_smoke()`
> 共用（§1.15——同一 install 逻辑不得在两处重复）。`deploy()` 保持 = build + install + smoke
> 的组合，既有调用方（debug_service / precision / cannbench_adapt）不受影响。

### 验证（改动 1）

- UT：`Deployer.compile()` 只跑到 build（产出 .run/.whl），**不触发** install_runtime /
  install_python 的 command_template；返回 DeployResult **install_path/python_path 为空**。
- UT：`Deployer.install_and_smoke(state, compile_result)` 用给定产物 install+smoke，**不重跑
  build**（build role command 未被调用）。
- 回归：既有 `deploy()` / `build_install()` 行为不变（4 处既有调用方
  `debug_service.py:81` / `cannbench_adapt.py:131` / `precision_debug_substages.py:1322` /
  `codegen.py:3157` 中前三处用 deploy()/build_install() 不变；codegen 改用新节奏见改动 2）。

---

## 改动 2 — codegen transition 改「先 compile 再全链」（决策 D6）

### 目标

现状 `_transition_membase`（`codegen.py:2937`）阶段 2 直接 `Deployer().deploy(state)` 跑
build+install+smoke 全链（`:3156-3157`）。改为：**先 `compile()`；compile 错 → resume 修
（build_failed 路径，现状已有）；compile 过 → 才 install+smoke（deploy 后半段）**。

### 改动

**2a.** `_transition_membase` 阶段 2 拆分两步，**compile 产物复用 install+smoke（不重 build）**：

```python
# —— 阶段 2a：compile 门（方案 2 D6：先编译验证，不装系统不 smoke）——
from ascendc_devkit.orchestration.stages.deploy import Deployer
deployer = Deployer()
compile_result, compile_err = deployer.compile(state)
build_result = BuildResult(passed=bool(compile_result.run_package))
step = (compile_err.details.get("step") if compile_err is not None else None)
if compile_err is not None and step == "build":
    # compile 失败 → build-retry（resume 修），不写 deploy_result → runner 重 spawn
    return self._build_failed_retry(state, agent_result, manifest, compile_err)  # 现状逻辑抽取
# compile 过 → 阶段 2b：install + smoke，复用 compile 已产出的 .run/.whl，不重 build
# （质疑后修正：不得无码改动做两次 build——compile_result.run_package 已是产物）
deploy_result, err = deployer.install_and_smoke(
    state, compile_result)   # 见改动 1d：跳过 build 段，直接用产物 install+smoke
# ... 后续 smoke 路由不变（kernel→precision，host→回 codegen）
```

> **【质疑后修正】原稿是 compile 过 → 再 `deploy()` 全链，会重跑一遍 build = 无码改动做两次
> build，浪费。改为 compile 产物复用**：Deployer 拆成可组合三段后，新增
> `install_and_smoke(state, compile_result)`——**跳过 build 段**，直接用 compile 已产出的
> `.run/.whl` 跑 install + smoke。这正是用户最初意图「build/install/smoke 按需单独或组合调用」。

**2b.** `_build_failed_retry`：把现状 build_failed 分支（`:3191-3230`）抽取为方法，compile 错与
install/smoke 错共用同一 retry 逻辑（不重复实现，§1.15）。

### 验证（改动 2）

- UT：transition 在 compile 失败时不写 `deploy_result`、写 `codegen_build_feedback`；compile 过
  才走到 install+smoke 分支。
- 回归：既有 build-retry / smoke 分流（kernel→D4 precision、host→回 codegen）行为不变。

---

## 改动 3 — SKILL.md 去「会话内自研构建」授权，引导 ccec 验 API（决策 D5）

### 目标

去掉 skill 里授权 agent 会话内整仓 build/自研的措辞，改为「整仓 build 归框架」+「会话内可
ccec 单文件验 API + 读」+「kernel 错交棒」。P1 病根之一就是 skill「构建经济性/会话内自检」把
「自研编译」当授权。

### 改动（SKILL.md `:185-187`，精确原文见 L4 附录）

将两段合并改写为：

```
> **构建归属（方案 2）**：**整仓 build / install / smoke 归框架**——codegen 完成后框架自动
> 运行编译验证（build → 错误注入 → 你修 → 再 build），**禁止在会话内执行整仓构建**
> （`bash build.sh` / `cmake --build` / install / smoke / pip / 写系统 vendors）——那会污染
> 共享环境且与框架 deploy 门重复。**最终编译正确性由框架验证**，会话内不自行整仓构建。
>
> **会话内可用的验证手段**：
> - **读操作全可用**（ls/cat/grep/find/git diff）——知识搜索/仓探索。
> - **ccec 单文件编译到临时目录**（不装系统不 smoke）——**API 签名不确定时用它快速验证**
>   （写码时验 `ReduceSum`/`Duplicate`/`Cast` 等签名能否编译，秒级反馈，是算子质量保障）。
>   不要因此去 grep CANN 头文件（CLAUDE.md 禁），查不到用知识库/ascendc-tips。
> - **kernel 阶段错误**（vector core 异常/运行期数据错/同步竞态）不在会话内吸收——记
>   `decision_log.json.known_issues` 按原样交棒（框架转 precision）。
```

> **为什么保留 ccec**（用户裁定，保质量）：最重要目标是写出高质量算子。整仓编译分钟级反馈太慢，
> 禁 ccec 会让 agent 写错 API 只能等整仓编译才暴露，往返变慢、损质量。ccec 单文件到 /tmp 无污染，
> 是写码时验签名的正确姿势。

### 验证（改动 3）

- 静态核对：SKILL.md 不再含「会话内自检编译」「cmake --build」「优先增量」等授权整仓 build 措辞。
- 保留「kernel 错交棒」「不要污染环境」等正确内容。

---

## 改动 4 — fresh prompt 软引导（决策 D5/D7）

### 目标

fresh 首轮 prompt 现状（`codegen.py:2321-2323`）把 `bash build.sh` 当「目标仓约定」注入，等于
暗示 agent 可用它。改为：编译命令标注「框架自动执行，agent 禁整仓构建」+ 引导 ccec 验 API。

### 改动（codegen.py `_build_codegen_prompt`）

**4a.** 「## 目标仓约定 编译命令」段（`:2321-2323`）改：

```python
sections.append(
    "## 目标仓约定（构建归属）\n"
    "整仓编译/部署/冒烟由框架在 codegen 之后自动执行（编译失败会注入本会话修复）。"
    "**不要在会话内自行执行整仓构建**（bash build.sh / cmake --build / install / smoke / pip）"
    "——会污染共享环境且与框架验证重复。\n"
    "参考编译命令（框架用，仅供了解，勿手动执行）:\n"
    + "\n".join(f"  {c}" for c in build_cmds)
)
```

**4b.** 「文件放置规则」段后加一段引导（若 ccec 是 agent 可用的，这里点明）：

```
## 会话内验证手段
- 读操作全可用（ls/cat/grep/find/git diff）。
- **API 签名不确定时，用 ccec 单文件编译到临时目录验证**（不装系统不 smoke）——例如写 kernel
  时确认某个 AscendC API 的调用形式/参数能否编译。这是快速验签名的正确姿势，不要等整仓编译。
- kernel 阶段（runtime/数据/同步）错误不在本会话吸收——记 decision_log.json known_issues 交棒。
```

### 验证（改动 4）

- UT：prompt 文本不再把 build 命令当「可执行约定」注入；含「禁整仓构建」「ccec 验 API」引导。

---

## 改动顺序

1. **改动 1**（Deployer compile）——最底层，先拆，独立可测。
2. **改动 2**（transition 先 compile 再全链）——依赖改动 1，改 codegen 节奏。
3. **改动 3**（SKILL.md）——去授权措辞，独立。
4. **改动 4**（fresh prompt）——依赖改动 2 的语义，独立。

## 全量验证（§3 TDD + §3.2 全覆盖）

- UT：上述每改动对应测试（先红后绿）。
- 相关既有套件回归：deploy / codegen / build_log_scanner 相邻 UT 全绿。
- ST：真实 codegen 任务跑通——agent 写码 → 框架 compile → 注入 → 修 → compile 过 → install+smoke。
  (若需 heavy_llm 按 §3.11 用户确认。)

## 不做（边界，明确排除）

- 命令级硬闸 / agent manifest 工具声明改动（D7：软引导）。
- agent 工具层拦 build（D7 不做）。
- 环境层「smoke 分代码错/环境错」补强（L1 另行跟踪）。
- 无码改动重复 build（已由改动 1d `install_and_smoke` 解决——compile 产物复用，不做双 build）。

## 附录：SKILL.md `:185-187` 原文（改动 3 依据）

```
> **构建经济性（Part 2，省 in-session 构建成本）**：会话内构建**优先增量**——`build/CMakeCache.txt`
> 存在时用 `cmake --build build --parallel $(nproc)`，**禁止无谓 `rm -rf build && bash build.sh`
> 全量重编**… 最终构建正确性由框架 deploy/smoke 门验证，会话内构建只为自检定位错误。
>
> **会话内自检的职责边界（合格完成路径，非禁令）**：会话内自检范围 = **编译错误 + host 阶段
> 错误**… kernel 阶段错误… 按原样交棒…
```

---

## 实施记录（2026-09-05）

改动 1-4 全部落地，UT 全绿。

### 改动明细（as-built）

| 改动 | 落地内容 | 文件 |
|---|---|---|
| 1 | `_run_build_install` 加 `build_only`（install 前 return，DeployResult install/python path 留空）；install 段抽 `_run_install_stages` helper（§1.15 单点）；新增 `compile()` + `install_and_smoke()` | `deploy.py` |
| 2 | transition deploy 段改：先 `compile()`（错→build-retry/unfixable 沿用三分支），compile 过 → `install_and_smoke()`（复用产物不重 build） | `codegen.py:_transition_membase` |
| 3 | SKILL.md 构建经济性/会话内自检两段改写：整仓 build 归框架 + 读全可用 + ccec 单文件验 API + kernel 交棒 | `ascendc-op-dev-coding/SKILL.md` |
| 4 | fresh prompt 目标仓约定改「构建归框架、勿手动整仓构建」+ 新增会话内验证手段段（ccec 引导） | `codegen.py:_build_codegen_prompt` |

### UT（TDD 先红后绿 + 既有适配）

- **新增**：`test_deploy.py::TestCompileBuildOnly`（compile 只 build 不 install/smoke、DeployResult 留空）、
  `TestInstallAndSmoke`（复用产物不重 build）；`test_codegen_upstream_reuse.py::TestCodegenFreshPromptBuildOwnership`
  （fresh prompt 禁整仓构建 + ccec 引导）。
- **既有适配**（codegen 不再走 deploy 全链，mock 旧 Deployer.deploy 的测试改 mock compile/install_and_smoke）：
  `test_plan_a_inrepo.py::_patch_deploy`、`test_stages.py::_patch_deploy` + `TestCodegenSmokeHostBackstop._transition`
  + `TestCodegenSmokeSchemaBackstop::test_smoke_schema_mismatch_routes_to_retry`、
  `test_codegen_plugin_schema_consistency.py::test_transition_relays_manifest_before_deploy`。
- **文案措辞**：fresh prompt 构建归属说明避开「编译失败」字面（不撞 build_result 反馈段断言）。

### 测试结果

- deploy UT 70 passed、codegen+deploy+adapt 受影响套件 581 passed、orchestration 全量（除 test_stages 慢 runner）通过。
- 全量 UT（tests/ut，--ignore llm）首轮 1 failed = `test_plan_a_inrepo`（旧 deploy mock），修复后重跑受影响套件全绿；
  test_stages 内 16 failed 逐批修复（helper 三处 + schema 一处）后 82 相关类 passed。

### 遗留 / 待后续

- **环境层 smoke 分「代码错 vs 环境错」补强**：L1 另行跟踪（本 L4 未涉及）。
- ST 真实 codegen 链路（agent 写码 → 框架 compile → 注入 → 修）未跑（§3.11 heavy_llm 需用户确认）。
