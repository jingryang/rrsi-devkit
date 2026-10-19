# L3 — chip_version 命名代际化:方案分析

> 选项、决策、理由。调研中演进、拍板后冻结。
> 问题事实见 `01-problems.md`(L1);实施结果见文末。

## D1 — canonical 身份收敛为代际码 {A2, A3, A5}
**选项**:(a) 保留多套词表逐 key 打补丁;(b) 收敛为单一 canonical 代际码。
**选 b**。理由:逐 key 打补丁不自动归位(§1.2 可扩展尺子——同类新芯片仍会错位);单一 canonical 一处定义、全链路派生,新增代际只改一处。代际码:**A2 = Ascend910B / Atlas A2、A3 = Ascend910C / 910_93xx / Atlas A3、A5 = David / 950 / Atlas 350**。

## D2 — 三层架构:canonical → hw_params 单源 → 编译翻译
- **L1 外部/人类接口**:CLI `--chip-version`、profile `default_chip`、state.chip_version、日志、显示名 一律 A2/A3/A5。
- **L2 代际级 hw_params(单源)**:A2→`ascend_910b.json`、A3→`ascend_910_93xx.json`、A5→`ascend_910_95xx.json`(复用 step-15 P24 单源)。
- **L3 编译期翻译**:`to_soc_version()` 把 canonical 译成 CANN soc_version,**仅两个物理出口**调用(cann 编译 `--chip`、profile `command_template` 渲染)。

**关键不变式**:canonical 是唯一 authority;soc_version 是 canonical 的纯函数派生,**不作为 state 冗余字段**(避免双字段漂移,对齐 state.py 既有 "chip_version truth / hw_params derived" 哲学)。
**技术纠正**(用户原话"运行时动态获取"不完全准确):编译期必须给 CANN/build.sh 精确 soc_version,设计期 tiling 必须静态 UB;"运行时动态获取"只覆盖核数等 perf 参数。故编译翻译层必需。

## D3 — 范围:仅 A2/A3/A5;其余芯片退出管线
310B/310P/610/sd3403/910初代 无开发场景,从项目管线消费的映射移除(spec 映射、device 关键字表只留 A 系列)。spec JSON 文件不删——留作 ascend-hardware skill 通用参考数据。理由:用户决策 + §1.4 不留无场景分支。

## D4 — 清理边界:客观标识/规格保留,内部身份/输入硬编码清理
**保留**(客观标识/规格记载):
- CANN INI 文件名(`Ascend910B3.ini`)、SoC_version、JSON 速查表文件名(`ascend_910b.json`)
- 官方产品族名(Atlas A2 训练系列、Atlas 350 加速卡)
- CANN op_def `AddConfig("ascend910b")` 字面
- build.sh 的 soc_version 物理参数、formulas / ascend-hardware 的 chip spec 计算示例
- 知识库 ascendc-dev-knowledge 全部(§1.5)

**清理**(DevKit 内部身份 / UB 输入硬编码):内部 chip 身份字符串 → A2/A3/A5;概设 patterns 把 UB 当量级/输入的硬编码 → 读 hw_params.json。
**理由**:客观标识是 CANN/磁盘认的物理标识,改了断链;内部身份是 DevKit 自定命名,应统一 canonical。

## D5 — common_knowledge 代际模型:架构代映射说明(非全量重命名)
**选项**:(a) common_knowledge + ~15 patterns 全量把架构代 "A3"(Membase 代)改 "A2/A3";(b) 章节标题对齐 canonical + 顶部加代际映射说明,patterns 保留 "A3 vs A5" 架构对比表述。
**选 b**。理由:910B(A2)与 910C(A3)同属 Membase/SIMD 架构代(910C 是 910B 同架构升级),文档按架构代组织合理;顶部映射说明("A2 与 A3 同属 Membase 代、A5 属 Regbase 代;文中 A3 vs A5 即 Membase 代 vs Regbase 代、A2 行为与 A3 一致")消除简称歧义,无需全量重命名 ~15 patterns(避免大规模改动 + 保留架构对比语义)。

## 开放项
- ~~A3 soc_version~~ **已定稿(2026-07-05)**:`to_soc_version("A3") = "ascend910_93"`(非早前推测的 `ascend910c`)。证据:ops-nn build.sh `SUPPORT_COMPUTE_UNIT_SHORT` 含 `ascend910_93`、help 注释 `"A3(--soc=ascend910_93)"`、`SOC_TO_ARCH["ascend910_93"]="2201"`(与 910B 同架构,印证 910C=910B 同架构升级)、platform_config 对应 `Ascend910_93xx.ini`(无 `Ascend910C.ini`)。用户确认"910_93 就是 910C 也是 A3,所有仓一样,历史遗留命名"。原推测 `ascend910c` 已废——ops-nn build.sh 不支持该 soc,真拿它编会 `The soc [ascend910c] is not support` 退出。教训:按"A2=ascend910b"格式机械外推成 `ascend910c` 是错的,910C 的 build.sh soc 名带下划线代际后缀 `ascend910_93`。
- ~~A3 device 探测关键字~~ **用户确认免测(2026-07-05)**:用户保证 A3 无需真机验证。`detect.device` 关键字保留推测值 `Ascend910C`(910C 真机未跑),按命名分层纪律(§1.9)小型号差异不影响算子代码,风险可接受。
- ~~相邻发现 ascendc-dev-auto 映射~~ **已修正(2026-07-05)**:`.claude/skills/ascendc-dev-auto/` 的 SKILL.md:94 + README.md:76 原写 `A3→ascend910c / A5→ascend910d`。经 ops-nn 真实算子 AddConfig 实证(A2=164×`ascend910b` / A3=133×`ascend910_93` / A5=26×`ascend950`)**确认:OpDef `AddConfig` 字符串 = build.sh soc_version 同一套命名**(推翻早前"AddConfig 是另一体系"的推测);其 scaffold `build.sh --soc=${SOC_VERSION}` / `-DASCEND_COMPUTE_UNIT=${SOC_VERSION}` 印证同源。原映射值错(A3 应 ascend910_93、A5 应 ascend950;`ascend910d` 实为 910D 另一芯片),已改。仓内 `ascend910c` 归零;剩余 `ascend910d` 均为 910D 真芯片知识库条目(§1.5 客观知识,保留)。
- ~~相邻发现(cann 编译旁路 flag)~~ **已删除(2026-07-05)**:用户定调"cce/ccec 不在本项目范围——本项目走算子仓 build.sh 编译,从不直接调 cce 编译器"。已删 `CANNToolchain.compile()`/`install()`/`_generate_cmake()`(`[ccec,"--chip",to_soc_version(...)]` 直接编译旁路,且 `--chip` 实为 CANN 不接受的错值——真实 flag 是 `--cce-soc-version`)及唯一调用方 legacy `BuildGate`(已被 `BuildInRepoGate` 取代,§2.5 旧通路不留)。`CANNToolchain` 收敛为纯 presence probe(`is_available`/`diagnostic_hint`,供 dispatcher 预检 + verify/perf gate);sentinel 列表仍含 `ccec` 仅作"CANN 已 source"探测标记(`shutil.which`),绝不调用。UT 1542 全绿。

## 实施结果(已完成)
- **canonical 单源**:新增 `domain/chip.py`(代际常量 + `to_soc_version` + `validate_chip_compatibility` + `chip_display_name`);detect 只识 A2/A3/A5(修 910B=A2、补 910C=A3);run_context spec 映射/默认 variant 收敛 3 项;state/stages 默认 A2。
- **编译链**:DeployStage tvars、repository/generic 的 command_template 显示、runner 的 CHIP_VERSION env 三处统一调 `to_soc_version`(原"cann 编译出口"已随 `CANNToolchain.compile` 删除);profile `default_chip` → A5/A2/A3(顺带修 omni-ops 的 soc_version typo)、占位符 `{chip_version}` → `{soc_version}`;CLI `--chip-version` 加 `click.Choice(["A2","A3","A5"])`。
- **文档**:common_knowledge 代际标签修正(章节对齐 canonical)+ 顶部代际映射说明;ascend-hardware PCI 表已对齐(无需改);概设 patterns(atomic×8 + fused×5)UB 硬编码 → 读 hw_params.json。
- **测试**:改全仓字面量 + 新增 `test_chip.py`(`to_soc_version` 契约 + 穷尽性 + unknown raise 守护);UT 1542 + ST 全绿。
- **DeployStage 渲染回归(已修+守护)**:step-17 把 profile `command_template` 占位符 `{chip_version}`→`{soc_version}` 时,只改了 repository/generic 的 `build_commands` 显示路径,漏了 DeployStage 真跑路径的 tvars——`str.format` 在 build role 渲染时抛 `unknown template var 'soc_version'`,致 NPU 真机 4 用例一度全 skip(ST 仅显示路径有覆盖,渲染路径零 UT,故回归漏网)。修法:tvars 补 `soc_version` + 抽 `_template_vars` 静态方法 + 新增 `test_deploy.py`(占位符/tvars 键契约 + 三代际 soc_version 派生 + 缺键 abort 守护)。NPU 真机 4 用例补跑全绿。
- **cann adapter 收敛为 presence probe(§2.5)**:删除 `CANNToolchain.compile()`/`install()`/`_generate_cmake()` 及 legacy `BuildGate`(见开放项"相邻发现(cann 编译旁路 flag)已删除")。
- **未跑**:cann-bench e2e 回归(heavy_llm,§3.11 需用户确认)。
