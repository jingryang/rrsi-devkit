# DevKit(950) → 1903(910b) 合并台账

- 源:`AscendC-DevKit` @ `devA5Debug`(remoted as `devkit950`)
- 目标:`AscendC-DevKit_1903` @ `merge/devkit950-to-910b`
- 分叉点:`99b01ba1`

## 冻结现场(M0)

| 项 | SHA |
|---|---|
| 1903/main (base) | `a918952f815c6e52d325aa8640a0b392553fa650` |
| devkit950/devA5Debug (source tip) | `539a6fb9d58b7b1f84f39aa9d2b5bd1b2663d95d` |
| merge-base | `99b01ba10d98793c966bd517b4b253eab1fa63bf` |

方向:单向 950 → 910b。1903/main 全程冻结,改动只落在本分支。

## 状态图例

`P`=pending 待处理 · `M`=merged 原样合入 · `R`=rewritten 改写合入 · `S`=skipped 跳过 · `C`=conflict 需裁决

## 明细

### L0 迁移提交(单列)

| # | 源SHA | 主题 | A5 | 状态 | 新SHA | 备注 |
|---|---|---|---|---|---|---|
| 0 | `28c9c581` | claude 改为 opencode(15414 文件改名) | 否 | S | - | 核验跳过成立(M5 §1):7591 R100 纯改名 + 31 个<100% 改名抽验均为纯路径串改写,唯一非改名改动(.gitignore 删 settings 忽略行)1903 侧本就保留且布局正确 |

### L1 知识·经验·skill 文档层

| # | 源SHA | 主题 | A5 | 状态 | 新SHA | 备注 |
|---|---|---|---|---|---|---|
| 1 | `6aba3068` | 修复对 A3 已删除 skill 的引用 | 否 | M | `d441ad92` | 有冲突已裁决,见 §冲突决策#1 |
| 2 | `875a55f2` | SIMT 模式库接入设计/编码链 + Dynamic UB | 否 | M | `1139699c` | 条件门控(950 生效/910b 忽略),见 §冲突决策#2 |
| 3 | `3c48b64e` | A5 max_min API 特殊用法经验 | 是 | M | `058fe6a7` | 条件触发;950 受益 |
| 4 | `673f8256` | softmax_family 经验入 tiling | 否 | M | `47e0bd72` | 干净 |
| 5 | `4e7c32ee` | docgen: OpDef 渲染跨 IO 组合数铁律 | 否 | M | `420b740d` | 干净 |
| 6 | `d01bfef8` | vf_compute integration 改进 | 否 | M | `42c247dc` | 冲突手工改址:落 regbase.py,见 #4 |
| 7 | `3cff28f5` | add vf experience | 否 | M | `6b6be3da` | 干净(早于 #6 合入) |
| 8 | `f279db4c` | max_argmax_L3 算子说明 | 否 | M | `5b6a5b94` | 干净 |
| 9 | `938b444a` | VF-Split 优化 | 否 | M | `87c2b22c` | 冲突:编号错位,见 #3 |
| 10 | `77f960ed` | 类目 tiling 模式库迁入并接入流程 | 否 | M | `84fed062` | 干净 |
| 11 | `c54277c6` | tiling 索引补 Norm/归一化路由 | 否 | M | `74432bff` | 干净 |
| 12 | `946e69d8` | norm 二分设计 skill 迁入 | 否 | M | `f21258a5` | 冲突:编号错位+各自加自检,见 #3 |
| 13 | `11c6bbf7` | vf-test MicroAPI 改为 Reg | 是 | M | `8850cbc0` | 纯改名,全在 A5 skill 内 |

### L2 工具链·脚本·测试基建

| # | 源SHA | 主题 | A5 | 状态 | 新SHA | 备注 |
|---|---|---|---|---|---|---|
| 14 | `b2a99275` | batch_self_evolve 卡数探测改 npu-smi -l | 否 | S | - | 1903 已独立修同 bug,见 #5 |
| 15 | `52177c9e` | s5-compile 编译重试上限 6→24 | 否 | M | `33c393ab` | 冲突:retry 模型分叉,见 #5 |
| 16 | `4a39767c` | SKILL.md 快速参考 s5 计数器 6→24 | 否 | M | `de0b131c` | 干净 |
| 17 | `b17b6d9e` | vf_test 重试 2→4,stage4_selfcheck 4→8 | 否 | M | `7223c1c2` | 冲突:codegen.py 失址+模型分叉,见 #5 |
| 18 | `49120b76` | LLM 预检后端感知 + settings 收敛 | 否 | M | `de352b15` | 冲突:.opencode→.claude,见 #6 |

### L3 编排代码 src/(codegen / precision-debug)

| # | 源SHA | 主题 | A5 | 状态 | 新SHA | 备注 |
|---|---|---|---|---|---|---|
| 19 | `b09044ee` | baseline rc+kl 全 pass 输出 DONE 总结 | 否 | M | `be733d2b` | 冲突:cann-bench-eval 行按 #1 预留,见 #8 |
| 20 | `8148f824` | A5 编译验证收敛 s5,移除增量探针 | 是 | R | `76469f70` | codegen.py 失址→regbase.py;见 #9 |
| 21 | `d6827246` | vf 并行 python 取结果冲突修复 | 否 | R | `6b793d64` | codegen.py 失址→regbase.py branch_label;见 #9 |
| 22 | `d1bc9b2a` | VF 并行派发按模板组分批 | 否 | R | `c474e101` | codegen.py 失址→regbase.py;plan 索引取 1903;见 #9/#10 |
| 23 | `31bf916b` | s4 子阶段重试改 per-substage 计数 | 否 | R | `4a0c088a` | **s4 计数模型改 per-substage(取代 #5 该层裁决)**;见 #11 |
| 24 | `57fae86b` | A5 baseline 分流 kernel 层失败优先 | 是 | M | `1721a229` | 干净 |
| 25 | `8a12f607` | RETURN 信号解析中文兜底 | 否 | M | `123d12bc` | 干净 |
| 26 | `f61f28d7` | A5 baseline 双工具验收门槛 | 是 | M | `6d3de198` | 干净 |
| 27 | `1b2622bf` | regbase s5 质量门失败改走修复路由 | 是 | R | `745bb925` | codegen.py 失址→regbase.py `_regbase_gate_retry`;见 #9/#12 |
| 28 | `79783a95` | vf-test 精度判定对齐 MERE/MARE | 否 | M | `5b747545` | 干净;其 precision_check UT 依赖 `ttk`,环境缺失未跑(§3.7) |
| 29 | `0fa7ddce` | baseline rc-pass+kl-fail 处置 | 否 | M | `825ac3d0` | 干净(skill/agent) |
| 30 | `1e96ed2d` | L2_DFX_PHASE_1 必须加 attr | 否 | M | `6dd57b14` | 干净(skill) |
| 31 | `0314c026` | s4-coding F.7 跨层对账 | 否 | M | `d8c0a17f` | 干净(skill/agent) |

### L4 新功能

| # | 源SHA | 主题 | A5 | 状态 | 新SHA | 备注 |
|---|---|---|---|---|---|---|
| 32 | `fc03851d` | 概设接入策略卡检索 | 否 | R | `175bfef9` | 路径改写 `.opencode→.claude`;3 冲突:config/SKILL 取并集、plan 保留 1903 编号,见 #13 |
| 33 | `f3db1969` | 适配 .claude→.opencode 目录迁移 | 否 | R | `a83a013f` | **部分采纳**:仅「ST settings-env 收敛到 tests._llm_env 单点」;改名类全跳过,见 #13 |
| 34 | `2114ce7b` | 策略库三态语义 + 使用留痕 log | 否 | M | `96acf027` | 干净(路径改写后) |
| 35 | `3ae0e064` | st-design 增量融合 + 值域/去重/两两覆盖 + baseline 来源拆分 | 否 | R | `7f0c1cd7` | st_design 并集;csv 计数模型分叉取 1903;codegen 失址;见 #14 |
| 36 | `f86380ea` | BASELINE_RESULT rc_pass 取 cann-bench 子集 | 否 | M | `27107bad` | 干净(路径改写后) |

### L5 merge 提交(无内容,记录即可)

| # | 源SHA | 主题 | 状态 | 备注 |
|---|---|---|---|---|
| M1 | `7b91218a` | !7 merge devA5Debug_0902 | P | 内容已并入上方各笔 |
| M2 | `d9c978c3` | !9 merge dc_0903 | P | 同上 |
| M3 | `c7b9064b` | !11 merge dc_0904 | P | 同上 |
| M4 | `d4deea75` | !13 merge dc_0907_2 | P | 同上 |
| M5 | `b59f9353` | !14 merge dc_0907 | P | 同上 |
| M6 | `4e881cb3` | !15 merge devA5Debug | P | 同上 |
| M7 | `389047c8` | !16 merge devA5Debug | P | 同上 |
| M8 | `539a6fb9` | !19 merge add_st_design | P | 同上 |

---

## 冲突决策记录

### #1 — L1-1 `6aba3068` 的 `ascendc-precision-baseline/SKILL.md`
- **现象**:该文件的「工具依赖」段冲突。根源是**跨层依赖**——DevKit 侧 `b09044ee`(L3)先在此处新增了 `cann-bench-eval` 一行,`6aba3068`(L1)再改相邻的 `ascendc-precision-run-tests` 行;L1 先行单摘导致相邻行冲突。
- **裁决**:采纳 `6aba3068` 侧——保留新增的 `references/run-cases-result-json.md` 行,删除已删 skill `ascendc-precision-run-tests` 的引用;`cann-bench-eval` 一行**留给 L3 `b09044ee`** 合入时带入(不在此提前引入)。
- **验证**:`pytest tests/ut/orchestration/test_precision_debug_a5_source_safety.py` → 32 passed。
- **LEARN**:L1 与 L3 存在跨层相邻改动;后续若冲突加剧,考虑回退严格时间序。

### #2 — L1-2 `875a55f2` 的 orchestration-config.json + 2 UT
- **决策(用户)**:SIMT 是 950 能力,910b 不支持——合入目标是「950 能正确用起来,910b 忽略」。
- **确认**:该提交的接线本就是**条件门控** 的——general-design SKILL 写「A5 + SIMT 特征 → 先查」,tiling §0.5 写「非 SIMT 模板跳过本步」,regbase 本身即 A5 链。故 910b 走普通路径时不会触发 SIMT 知识 → **整笔合入**。
- **冲突解**:
  - `orchestration-config.json`:同键 `ascendc-op-general-design` 双方修改(1903→`template-select`,DevKit→`simt`)→ 取**并集** `[template-select, simt]`;DevKit 新增 `ascendc-op-dev-coding-regbase` 键全保留。
  - `test_design_substages.py`:GeneralDesignStage 期望 skills → 取并集三项。
  - `test_skill_config.py`:保留 1903 的注释(改用 template-division 作 no-tailcall 例),采纳提交的 skill 名。
- **验证**:`test_design_substages + test_skill_config + test_tiling_forkjoin` → 143 passed;`test_launch_args.py` **未能跑**(依赖外部 `ttk`,环境缺失,如实记录);`source_module.py` 眼过确认默认不变(None/0→RTS 默认)。

### #3 — L1-9/L1-12 的「步骤编号错位」类冲突
- **现象**:`ascendc-op-design-template-division/SKILL.md`、`ascendc-op-general-design/SKILL.md` 的**步骤编号错位**——1903 的步骤序列比 DevKit 多一步(如 1903 的 Step 8 ↔ DevKit 的 Step 7;1903 的 `9.3` ↔ DevKit 的 `8.3`)。根源:1903 分叉后独立增/删了步骤,导致同段文字行号不同 → 文本 diff 判为修改。
- **裁决**:一律**保留 1903 的编号** + **并入 DevKit 的新增内容**(如「模板 notes 内容边界」子项、「规约类算子累加方式条款」、A5 二分累加自检项)。
- **验证**:`test_design_substages + test_skill_config` 等 → 见 M1 回归。

### #4 — L1-6 `d01bfef8`:codegen.py 重构导致的「改动失址」
- **现象**:源改动落在单体 `src/.../stages/codegen.py` 的一行;但 **1903 已把该单体(4646 行)重构成 mixin 包**——`codegen.py`(819 行)+ `codegen_s4.py` + `codegen_stage_mixin/*.py`。那段 prompt 构建代码现位于 `codegen_stage_mixin/regbase.py:1471`。→ cherry-pick 在该文件硬冲突。
- **裁决**:`codegen.py` 保留 1903 版本(该改动不在此处);把 `d01bfef8` 的意图**手工落到新址** `codegen_stage_mixin/regbase.py` 的 execution_group 说明行。另两个 agent 文件自动合并。
- **验证**:`test_codegen_regbase_phases.py` → 144 passed。
- **LEARN(重要)**:L2/L3 里所有**改动 `codegen.py` 逻辑**的提交(非仅 docs/重试常量)都可能遇此「失址」——需按 1903 的新 mixin 布局重定位。已在本台账标注,后续逐笔检查新址。

### #5 — L2 的「retry 子系统分叉」类冲突(52177c9e / b17b6d9e)
- **现象**:测试基建两侧结构性不同——1903 用 **meta.json 的 per-counter `retries`**(`_set_meta(retries={...})`),DevKit 用 plan 里的 **per-sub-stage `retry_count`**(`_set_step_retry_count`)。
- **裁决**:统一以 **1903 模型**为准(meta.json 计数器);取源提交的**数值意图**(VALUE)落到 1903 的限值常量/断言:
  - `stage5_compile` 6→24(`codegen_s4.py` 自动应用);`vf_test` 2→4、`stage4_selfcheck` 4→8;`regbase.py` 默认值 4→8(失址手工改)。
  - `b17b6d9e` 对 `codegen.py` 的改动:该文件 1903 已重构,**恢复 1903 版**;默认值落入新址 `codegen_stage_mixin/regbase.py`。
  - 测试断言中旧的 `used=2/limit=2`、`used=4/limit=4` 全部按新限更新(2→4, 4→8),含 `used>=limit` 语义维持。
- **验证**:`test_codegen_regbase_phases + test_codegen_s4_dispatch + test_regbase_script_behavior` → 206 passed。
- **未做的降级**:`codegen_stage_mixin/regbase.py:1362` 的硬编码默认 `4`(仅防御性,生产必中 RETRY_LIMITS 键)保持未改——与既有一致,非正确性缺陷。

### #6 — L2-18 `49120b76` 的 `.opencode`→`.claude` 路径改写 + ST 去重
- **决策**:LLM 预检收敛到单一模块(`tests/_llm_env.py`)是良好重构(§1.15),合入;但路径需按 1903 布局改写。
- **冲突解**:
  - 新增 `tests/_llm_env.py`:`SETTINGS_PATH` 与全部措辞 `.opencode/settings.json` → **`.claude/settings.json`**(1903 布局);`opencode.json` 引用**保留**(1903 也用该后端配置文件)。
  - 6 个 ST 文件(`_dual_backend` 等):**删各自本地 `_load_settings_env` 副本,改用 `tests._llm_env`**(取 theirs)。
  - `test_design_algorithm_family_selection.py`:取 theirs 的 import,但 `_SKILLS_ROOT` 保留 1903 的 `.claude/skills`。
- **验证**:`_llm_env` 可导入,`SETTINGS_PATH` 正确,`llm_precheck()` 正常(无 opencode.json 如实报 False);10 个 ST 文件 **collect-only 通过**(实跑需真实 LLM,按 §3.11 待用户确认)。

### #7 — M2 回归:`tests/ut/application` · `tests/ut/cli` 挂死 = 既有环境问题(非本次合并引入)

- **现象**:M2 全量 `tests/ut` 回归卡死(exit 143)。逐目录隔离:`adapters`(599)/`scripts`(24)/`infra`(340)/`self_evolution`(60)全过,唯 `application`、`cli` 挂死。
- **归因方法**:在**纯净 `1903/main`(`a918952f`)**上以 `git worktree` 复现同一目录 → **同样挂死**。再逐文件定位到 3 个真挂死文件:`ut/application/test_application.py`、`ut/application/test_state_machine_dispatcher.py`、`ut/cli/test_cli.py`(另 `test_dispatcher_path_anchoring.py` 只是慢,26s 通过)。
- **裁决**:挂死**先于本次合并存在**(base 已挂),非 L2 引入 → 不阻塞 M2;按 §3.7 如实记录,不对挂死文件打桩/跳过。核心目录回归(orchestration+skills+capabilities+domain)= **3361 passed**;L2 定向回归 206 passed。
- **遗留**:挂死根因(疑为测试依赖真实外部服务/阻塞 IO)另案处理,不在本合并范围。

### #8 — L3-19 `b09044ee` 的 `ascendc-precision-baseline/SKILL.md`(L1 #1 预留行的到达)
- **现象**:L1 #1 裁决「`cann-bench-eval` 一行留给 L3 `b09044ee` 合入时带入」——本笔到达,与该文件冲突。
- **裁决**:采纳 `b09044ee` 侧——保留 1903 本地 `references/run-cases-result-json.md` 行 + 并入 `cann-bench-eval`（性能-only）行;**不**引入 devkit 侧的 `ascendc-precision-run-tests`(1903 已删)。三方一致收口。
- **验证**:`test_cann_bench_eval_perf + test_precision_debug_a5_source_safety` → 43 passed。

### #9 — L3 的「codegen.py 重构失址」批量现象(#20/#21/#22/#23/#27)
- **现象**:L3 中 **5 笔**改动 devkit 单体 `codegen.py` 的 Regbase 逻辑,而 1903 已把该单体拆为 mixin 包。cherry-pick 在该文件全部硬冲突(HEAD 侧多为空)。
- **裁决**:统一「`codegen.py` 保留 1903 版 + 改动手工落到新址 `codegen_stage_mixin/regbase.py`」：
  - #20:删 `_run_regbase_compile_probes`/`_clear_regbase_last_error`/probe 门控块/import;新增 `_render_last_error_diagnostic_block`;`_handle_regbase_failure` 加 `_with_reason`;s4/s2 prompt 尾注入共用渲染器。
  - #21:并行 VF `SpawnAgent` 加 `branch_label=vs`。
  - #22:新增 `vf_group_base` import + 批量按模板组过滤(逻辑取源)。
  - #23/`#27`:见 #11/#12。
- **验证**:各笔定向 + M3 广度 `orchestration+skills+capabilities+domain+infra+adapters` → **4330 passed, 19 skipped**。

### #10 — L3 的 docs/plan 步骤编号撞名(#22/#23)
- **现象**:devkit 的 `skills-integration-and-tdd-plan.md` 步骤 104/105 与 1903 的 104/105(NPU 探测/属性类型系统)**编号撞名**。
- **裁决**:沿用 L1 #3 策略——**保留 1903 的编号**(取 HEAD);devkit 侧新增的 plan 文档子目录(`vf-dispatch-template-grouping/`、`codegen-s4-retry-counter/`)本身保留。

### #11 — L3-23 `31bf916b`：s4 计数模型改 per-substage（**实质覆盖 L2 #5 对 s4 层的裁决**）
- **背景**:L2 #5 曾裁决 s4 retry 统一到 1903 的 meta.json 计数器模型。L3 #23 则把 **s4 子阶段计数**改为落在 `orchestration_plan.json` 的 `sub_stage.retry_count`(per-substage),`check_retry_exceeded(rd, sid, type)` 读、`bump_retry_counter` 写,`_set_status(done)` 清零;**s2/s5 仍用 meta.json 阶段级计数**(`_handle_regbase_failure` 不变)。
- **核实(重要)**:1903 的 `dispatch()` FAILED 分支与并行 VF transition **确实只读 `check_retry_exceeded` 不写计数** → `used` 恒 0 → 「s4 自检 4 次回退 s2」「vf_test 2 次 exhausted」升级门**永不触发**(与 #23 所述 09-01 devkit 根因同型)。故 #23 是**真实 bug 修复**,其 per-substage 模型为上游用户拍板设计。
- **裁决**:采纳 #23 完整改写(结构 + 模型);其测试值按 1903 现值移植(devkit 旧 6/2/4 → 1903 新 **24/4/8**)——`test_codegen_s4_dispatch`(selfcheck 8 / vf 4 / compile 24)、`test_regbase_script_behavior`(retry_count 4)、`test_codegen_regbase_phases`(bumps_until_rollback 8、isolated 7→8)。`_set_meta` helper 删除(无引用)。
- **净效果**:s4 层计数权威源 = plan per-substage(取代 meta.json);L2 #5 的 24/4/8 **limit 值仍有效**,仅 s4 的**存储位置**改变。`_handle_regbase_failure`(s2/s5 路径)继续用 meta.json。
- **验证**:`test_codegen_s4_dispatch + test_codegen_regbase_phases + test_regbase_script_behavior + test_codegen_skill_delivery` → 227 passed;`tests/ut/orchestration` 全目录 → **2209 passed**。
- **⚠️ 需人工复核点**:此笔改变了 s4 计数模型(与 L2 #5 表述冲突)。若 910b 侧重「保持 meta.json 统一模型」优于「采纳 upstream per-substage」,本笔可单独 revert(`git revert 4a0c088a`),此时 s4 门不触发 bug 会复现——需另做「在 meta 模型内补写计数」的最小修复。

### #12 — L3-27 `1b2622bf` 的 s5 质量门修复路由(失址 + 数值漂移)
- **现象**:`codegen.py` 失址(同 #9);其新增测试 `test_s5_gate_retry_exhausted_rolls_back_to_s4` 设 `stage5_compile used=6`(devkit 旧 limit),1903 现值 24 → 未耗尽致 phase 停在 s5。
- **裁决**:落新址 `regbase.py`:5 处 s5 质量门 `return state.with_updates(codegen_phase="done", …)` → `_regbase_gate_retry(state, artifacts, error)`;新增单点 `_regbase_gate_retry`(路由到 `_handle_regbase_failure` 既有预算链)。测试值 `used=6/limit=6` → **24/24**。
- **验证**:`test_codegen_regbase_phases + test_codegen_s4_dispatch` → 204 passed。

### #13 — L4 的 `.opencode`→`.claude` 路径改写 + `f3db1969` 部分采纳(32/33)
- **现象**:L4 5 笔源路径全为 `.opencode/`(devkit `28c9c581` 改名之后);本仓 1903 保持 `.claude/` 布局(§4.2)。
- **裁决(路径)**:统一用 `git format-patch … | sed 's|\.opencode/|.claude/|g' | git am -3` 改写后合入;`.claude/skills/…` 内的 skill 树落位正确,无 `.opencode` 残留。
- **裁决(#33 `f3db1969`)**:该笔整体是「为适配 devkit 改名而做的**反向归位**」(git mv 到 .opencode、UT/ST 常量 .opencode 化、SKILL.md 指引 .opencode 化)——本仓不适用,**跳过**;仅摘取与本仓布局无关、纯属 §1.15 收口的一条:「ST 本地 `_load_settings_env` 副本 → `tests._llm_env` 单一解析点」(与 L2 #18 对其它 ST 文件的收口同源)。
- **#32 `fc03851d` 冲突解**:
  - `orchestration-config.json`:`ascendc-op-general-design` tail_calls 取**并集** `[design-template-select, simt-operator-design-patterns, strategy-card-select]`。
  - `ascendc-op-general-design/SKILL.md`:取并集——保留 HEAD 的 SIMT Tier 1 行 + devkit 的策略卡 Tier 2 行。
  - `docs/plan/skills-integration-and-tdd-plan.md`:按 #10 保留 1903 编号(devkit 的 104/105/106 撞名行不入 1903 索引);其 `docs/plan/strategy-card-select/` 子目录作为新文件保留。
  - `test_design_substages.py`:GeneralDesignStage 期望 skills 由三项 → **四项**(+`ascendc-strategy-card-select`)——config tail_calls 并集的直接连锁(L1 #2 已同样为 SIMT 增补过本测试)。
- **验证**:#32 `test_strategy_card_select + test_skill_config` → 37 passed/12 skipped(12 skip = 外部策略库 `/home/l00940202/…` 不在本机,driver 类 skill 外挂依赖缺失,§3.7 诚实记录);#34 → 30 passed/12 skipped;L4 广度 `tests/ut/{orchestration,skills,capabilities,domain}` → **3443 passed, 16 skipped, 0 failed**。

### #14 — L4-35 `3ae0e064` 的三处结构裁决(st_design 并集 / csv 计数模型 / codegen 失址)
- **a) `codegen.py` 失址(同 #9)**:源改动落在单体 `codegen.py` 的 s2/s4 prompt 构建器(2 处 `test_cases.json` 指名);1903 已重构为 mixin 包 → `codegen.py` 保留 1903 版,改动手工落新址 `codegen_stage_mixin/regbase.py` 的 `_build_s2_prompt`(kernel_arch 之后)/`_build_s4_prompt`(ref_op 之后)。守护测试 `TestRegbasePromptSurfacesTestCases`(本笔新增)通过。
- **b) `ascendc_st_design.py` = 同基线正交改动的并集(重要)**:核实 1903 HEAD 与源笔父 `3ae0e064^` 的唯一差异 = **1903 step-127**(E-1/E-3 的 03 对质 + feedback 累积 + prompt 边界条款;devkit 无 `verify_param_def.py`)。源笔把「外部 cases 短路 NoOp」改为「始终跑 LLM + 外部/生成增量融合(P34)」。二者正交 → **取并集**:以 devkit 增量融合结构为基底(`_parse_generated_cases`/`_load_external_cases`/`_extra_prompt_sections`/合并 transition),**回填** 1903 step-127 三处——E-1(actions 的 feedback 累积+03 对质)、**E-3 提升为 transition 顶部硬门**(agent 跑过时校验 03,防适配器静默丢参复现,与融合正交;未降级为软信号)。
- **c) `csv_to_testcases.py` `_build_inputs` 计数模型分叉(与 #23 同型)**:1903 step-128 用「compact 列表 + 显式 `proto_idx`」处理缺省可选输入(无 None 整段分支);devkit `3ae0e064` 新增「proto-aligned 1:1」分支(镜像 cann-bench null,`n_total = len(flat_shapes)`)。auto-merge 曾把 devkit 分支与 1903 的 `n_total = len - len(absent)` **混成不一致混合体** → 守卫误触发 `2 != 3`,1903 十个 step-128 测试挂。**裁决**:取 1903 模型(删整段分支),仅**吸收 devkit 的安全片段**——非 DYNAMIC 位置取用处对「in-range None 且非 OPTIONAL/DYNAMIC」抛 `not declared OPTIONAL`(in-range 守卫,out-of-range 仍静默降级)。效果:**1903 全绿 + devkit 4 条新测试亦全绿**。生产端 `_flat_inputs` 两侧本就相同,本笔对该文件唯一新增 = `source="devkit"` 来源标签(保留)。
- **d) `generate_test_cases.py` 死代码清理**:auto-merge 使 devkit 的「缺省可选输入 None 占位」helper `_append_absent_input_placeholder` 与 1903 的等价位(三容器同位 None)并存;1903 early-continue 使 devkit 的 `if not exists:` 块成死代码(条件等价于提前 continue)→ 删死块 + 孤立 helper(§1.4 不留死代码)。devkit 新增的 L1 两两覆盖/pairwise(`_generate_l0_l1_cases`/`complete_case`/`select_pairwise_factors`/`_enum_param_names`)无冲突**保留**。
- **e) 其余**:`runner.py` 解析回 1903 HEAD(devkit 保留「按名字 `input_{i}` 反解 proto_idx」兜底,与 1903 step-128 明文「删猜名字、只读显式字段」冲突 → 取 1903);`test_codegen_regbase_phases.py` 为文件尾双向追加 → 取**并集**(`TestFirstVtInGroup` + `TestRegbasePromptSurfacesTestCases`);`docs/plan` 索引取 1903 编号。
- **验证**:`test_st_design_scripts + test_merge_test_cases + test_csv_to_testcases + test_case_source_provenance + test_codegen_regbase_phases + test_test_design_e2e` → **224 passed, 1 skipped**。

### #15 — M5 复盘:st-design 增量融合对 A3 的影响面(用户裁决:A3 沿用)
- **背景**:M5 复盘发现 `ascendc_st_design` **无芯片门控**(A3/A5 共用 stage),`3ae0e064` 的融合把 1903 旧的「外部 cases → NoOp 跳过 LLM」语义改为「有 workspace 即跑 LLM + 融合补充」→ A3 每次带外部 cases 的运行**多付一轮真实 LLM 调用(分钟级+token),验收用例集相应变多**。与 SIMT(纯 950 硬件能力)不同,融合是芯片无关的覆盖增强,不属于必须按芯片隔离的知识。
- **裁决(用户)**:**A3 沿用 A5 的融合行为,不加芯片门控**——外部基准仍为主源(`cases_source=cannbench`),LLM 补集对 A3 同样是覆盖增强,用户知情成本后接受。曾实施过 Regbase 门控方案(代码+UT/ST 全绿)供对比,用户了解权衡后拍板「a3 沿用a5的也是可以的」→ 门控整体撤销,合并态即最终态,以本决策记录存档。**完整复盘(影响面核对/方案权衡/最终行为矩阵/后续观察点)见 `st-design-fusion-chip-impact-review.md`。**
- **验证**:合并态既有守护测试即覆盖(`TestExternalCasesIncremental`:融合/外部在前/cases_source/LLM 失败时外部兜底/无 workspace 降级);ST e2e + 广度 UT 全绿(M5 记录)。

## 阶段记录

| 阶段 | 范围 | 完成 | tag |
|---|---|---|---|
| M0 | 建分支+台账+冻结 | 2026-10-09 | - |
| M1 | L1 (13) | 2026-10-09 | `merge-stage-L1` |
| M2 | L2 (5) | 2026-10-09 | `merge-stage-L2` |
| M3 | L3 (13) | 2026-10-09 | `merge-stage-L3` |
| M4 | L4 (5) | 2026-10-09 | `merge-stage-L4` |
| M5 | 验收 | 2026-10-09 | - |

## M5 整体验收

### 1) 源侧提交全覆盖(可追溯性)
- `merge-base..源tip` 非 merge 提交 **37 笔**,与台账 #0–#36 **逐 SHA 一一对应**(集合差为空);merge 提交 **8 笔**(M1–M8)亦全在册。无漏记、无串号。
- 逐笔记名 **归属归因**:把每笔改动文件(归一 `.opencode/→.claude/` 前缀)与「我方 changed 集合」比对——除 **#0 `28c9c581`(改名,判跳过)**、**#14 `b2a99275`(S,1903 独立修同 bug)** 外,**其余 35 笔的改动文件全部落位**(untouched=0)。
- **#0 `28c9c581` 核验**:7591 R100 改名 + 31 个 <100% 改名(**抽验确认为纯 `.claude/`↔`.opencode/` 路径串改写,无实质内容**)+ `.gitignore` 删 `.claude/settings.json*` 忽略行(1903 侧本就保留且布局正确,无需动)。跳过判定成立。

### 2) 测试总览(本机环境)
| 范围 | 结果 |
|---|---|
| `tests/ut/{orchestration,skills,capabilities,domain}` | 3443 passed, 16 skipped, 0 failed |
| `tests/ut/{adapters,infra,scripts,self_evolution}` | 1018 passed, 16 skipped, 0 failed |
| `tests/st`(非 llm/npu/slow 子集,116 用例) | 106 passed, 8 skipped, **2 failed** |

- **UT 合计 4461 passed / 32 skipped / 0 failed**;`tests/ut/{application,cli}` 未跑 = 既有挂死(#7 已归因于 base,非本次引入)。
- **ST 2 failed = 既有 NPU 环境问题**:`tests/st/test_batch_e2e.py`(2 例)在 **纯 `1903/main` `a918952f` 上以完全相同报错复现**(`NPU card 0 probe failed`, `resolve_card_pool` 丢卡致池空 ConfigError);且相关 5 文件 `batch_runner/card_pool/card_pin/test_batch_e2e/dispatcher` 与 base **逐字节相同**(本次合并未触碰)→ 非合并引入(§3.7 如实记录)。
- **未跑的 llm/heavy_llm**(环境缺失,无 `opencode.json`;`llm_precheck` → False)按 §3.11/§3.7 诚实记录:heavy_llm 20 文件/用例待用户确认后跑;`tests/st` 其余 57 个 llm 用例本机不可达。

### 3) 结构完整性
- `validate_skill_map()` → **无违规**;新增 skill 落位:`ascendc-strategy-card-select`(18 文件)、`ascendc-simt-operator-design-patterns`(17 文件)。
- **无 `.opencode` 残留**(tracked=0,工作树无该目录);**无冲突标记残留**(src/tests/.claude 扫描 0 命中)。

## M5 后续:合并后 A3 侧演进与发现(2026-10-12 追记)

### 合并触发暴露的既有缺陷已修(A3 侧)——符号值域流入用例
- **事件**:A3 批量精度全挂(run `20261010-075905-02c9f4`,109 条 devkit 用例 cross_entropy IndexError)。根因链:04 声明候选含符号 `[[0,"C-1"]]` → 求解器三读取口零校验原样落盘 → 转换端历史实现装箱死字段 `generator_params.ranges`(零消费者)→ harness 回退 [-1,1] 为 int64 targets 生成 -1。**缺陷 950 侧同源存在但未触发**(其算子无受限整数域);#15 融合裁决改变触发面,109 条 devkit 用例首次进入 A3 test set——合并改变的是触发面,非引入缺陷。
- **处置**:A3 侧已修(用户裁决「改a3通路」):声明候选数值化契约 + 求解/渲染/转换三层诚实闸口 + 转换端逐输入挂载。全量 UT 4527 绿;真实产物四步链验证(事故设计指名报错、修正设计全链零符号)。四层文档:`docs/plan/st-design-symbolic-value-range/`。
- **950 侧缺口未回写**:runner/harness 的 ranges 处理缺失在 950 侧同源存在,按用户裁决不同步。950 侧若后续出现同类整数域算子批量失败,根因即此。

### A3 侧已演进文件(下一轮合并的 P8 类分叉点)
950 起源的以下文件在 A3 侧已含本方独立演进(950 无对应改动),下轮 devkit→1903 合并时按「路径基线约定」(#13 关联)处理分叉:
- `.claude/skills/ascendc-st-design/scripts/utils.py`(+3 校验函数)
- `.claude/skills/ascendc-st-design/scripts/generate_factor_values.py`(三读取口校验 + ValueError 防吞)
- `.claude/skills/ascendc-st-design/scripts/generate_test_cases.py`(渲染端兜底)
- `.claude/skills/ascendc-st-design/scripts/generate_implicit_constraints.py`(符号候选不产机械约束)
- `.claude/skills/ascendc-st-design/SKILL.md`(§2.1 作者契约)
- `src/ascendc_devkit/orchestration/stages/precision_debug_a5/git_safety.py`(快照排除表豁免构建清单 CMakeLists.txt——快照×回滚组合缺陷根治,见 `precision-debug-cmakelists-snapshot/`;950 侧不同步)
