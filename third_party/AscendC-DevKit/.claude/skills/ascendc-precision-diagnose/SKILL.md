---
name: ascendc-precision-diagnose
description: precision_debug 闭环 diagnose phase（诊断+自实施一体）。先全局理解算子+golden → 形成假设（改动必带 predict）→ 验证推进认知 → 就地修那一处（Edit→build→单用例验证→commit/rollback）。判断决策权在模型——失败性质、全局推演还是就地查证、验证范围由你判断，框架不框死打法。可选弹药：全局推演/golden 比对/printf 二分/注释降级/知识库查证。不枚举错误类型、不生成候选池、不回炉重生成。尽力后假设空间穷尽写 stalled=true 诚实报告。入口一句 upstream 判据。读 control.json 路由上下文，写 fix_code_log/_summary（precision_diagnose.json）+ case.status（control.json）。history 由框架从 _summary 物化，agent 禁止直接写。
---

# AscendC Precision Debug — diagnose phase（诊断+自实施一体）

> **可独立在 Claude Code TUI 中使用**：本 skill 是 precision_debug 闭环的 diagnose 环节方法载体。DevKit 编排（CompositeGroup）spawn 你单次执行 diagnose；TUI 下把接力文件放进 `{debug_artifacts_dir}`（通常 `output/<run_id>/artifacts/debug/<op_name>/`）即可 `/ascendc-precision-diagnose` 运行。I/O 契约见下「## 输入 / ## 输出」，schema 在本 skill 目录 `schema/` 下。
>
> **边界声明**：本 skill 只产 raw 执行结果 + LLM 判定，**不维护状态机不变式**（case 推进 / stop-loss / upstream halt 属框架）。

## 你的职责（单 phase 执行者，非调度器）

你是 diagnose phase agent（**诊断 + 自实施一体**）。核心方法：**先全局理解算子 + golden → 形成假设 → 验证推进**（§1.13/§1.14「比对 golden 一致即对，不一致就地修」）。**判断决策权在你**——失败是什么性质、该用全局推演还是就地查证、验证哪些 case，由你基于完整上下文判断，框架不框死打法。可用的定位手段（全局推演 / golden 比对 / printf 二分 / 注释降级 / 知识库查证）都是**可选弹药**，按需取用。

框架（CompositeGroup + GraphExecutor）按 transition_table 驱动；每次 spawn 你**单次执行**。**你不控制循环**：路由判断（`status` / `current_case_index` 推进 / stop-loss）由框架读 `control.json` 完成。你不决定下一个 phase，不推进用例索引，不写 `debug_result.json`。

## 输入

框架 spawn 时通过 prompt 参数传递（cwd = `operator_dir`）：

| 参数 | 含义 |
|---|---|
| `control_path` | `control.json` 绝对路径（FW 路由 + 跨域共享态） |
| `phase_json_path` | `precision_diagnose.json` 绝对路径（你 owner 的 phase 产物，含 fix_code_log） |
| `operator_dir` | 算子工程根目录（你的 cwd） |
| `skill_dir` | 本 skill 根目录（读 references/techniques/ 参考用） |
| `design_paths` | **可选**。设计产物路径映射（内容：tiling 切分 / 流水编排 / 搬运路径 / 精度策略的声明文件）。框架注入时全局理解必读；未注入时若 `{debug_artifacts_dir}` 或算子工程根存在同内容文件则同样读取；都没有则按代码 + golden 理解（不要寻找设计产物，直接开始） |
| `op_name` | 算子名 |
| `build_command` | redeploy 命令（实施用） |
| `test_command` | run-cases 命令（实施时追加 `--case "<CASE_ID>"` 做单用例验证） |

**从 `control.json` 读取**：
- `failed_case_queue[current_case_index]`：当前用例（含 `case_id` / `failure_type` / `shape` / `dtype` / `max_err`）
- `history`：前几轮已修的、已回滚的（避开重复方向）
- `failure_type`：当前用例的失败类型（`precision` / `runtime` / `compilation`）
- `upstream_signal` / `upstream_stage` / `upstream_reason`：本阶段是否已上报上游缺陷

**跨 phase 只读**：可读 `{debug_artifacts_dir}/phases/run_tests/precision_run_tests.json` 的 `last_result_json` / `last_run_log`（run_tests phase 产出的最近一次 result.json/run.log 绝对路径），回溯完整误差分布 / `max_diff_location` / 运行日志上下文。

## 输出

### Step 0：上游判据（入口，先于任何定位）

先看当前 failed case 是哪种错：

- **崩了**（SIGSEGV / 507035 vector core exception / CCU 越界）→ **本阶段职责**，就地修（kernel 运行时缺陷）
- **数值错**（max_diff / 形状 mismatch / NaN）→ **本阶段职责**，就地修（kernel 精度缺陷）
- **上游编译/注册/契约错**（编译失败 / op_plugin schema 不匹配 / golden 缺 get_input / 算子未注册 / devkit 自身抛错）→ **先尝试原地兜底解决，解决不了才上报**：
  - **凡修复目标代码在算子工程内的缺陷一律就地修**（属本阶段职责）——含 host 侧 tiling/launch/注册/脚手架缺陷，不因根因属上游生成而推诿（plugin/manifest 契约不一致等仅为子集例）——就地修（Edit → build → 单用例验证 → commit/rollback），修好按已修复处理
  - **确实超出本阶段职责的**（golden 语义错 / devkit 框架自身抛错 / 编译依赖缺失无法本地补）→ **如实上报**：写 `control.json.upstream_signal = true` + `upstream_stage`（`codegen` / `test_design` / `golden` / `deploy` / `framework` / `env`）+ `upstream_reason`（一句话事实），输出 `RESULT: DIAGNOSE_UPSTREAM`

混合失败按主导归类；拿不准时**倾向本阶段**（能修就修，别轻易上报——预算兜底）。上游错要留 `upstream_stage`/`upstream_reason` 供框架 halt 时展示。

### 写 `control.json`（只改本 phase 负责的跨域字段）
- `case.status`：修好后写 `resolved_pending`（框架据此转 run_tests 全量回归）；skip 写 `skipped` + `case_skipped_reason`
- `attempt_count`：递增（框架据此 + `max_attempts_per_case` 判 stop-loss）
- `upstream_signal` / `upstream_stage` / `upstream_reason`：上游编译/注册/契约错时（见 Step 0）
- `stalled` / `stalled_detail`：假设空间系统穷尽时写 `stalled=true` + `stalled_detail`（已试方向 + 为何认为超范围）。**与 upstream 同路径**——框架路由读 control.json 的 stalled（transition 透传到 dc），`_summary.stalled` 记录详情供报告。
- **禁止**写 `control.json.history`（由框架 transition 统一写入）
- **无 `best_*` 字段可写**：最优被测代码与计数由框架从测量史派生——你修好后无需、也无法「上报最优」；全量回归是框架自己的测量，交付选择不经过你的任何输出。

### 写 `precision_diagnose.json`（你 owner 的深数据，schema 在 `schema/precision_diagnose.json`）
- `diagnose_done`：`true`（完成标记）
- `fix_code_log`：实施记录——`applied_fix` / `tried_fixes` / `verification_result` / `side_effect_cases` / `fallback_masked`（host fallback 通过标记）/ `design_deviation`（结构偏离设计时必写，见「结构保真」）
- `_summary`：**必须写**。框架 transition 从此字段生成 history。字段：`symptom` / `case_id` / `root_cause` / `upstream_signal` / `upstream_stage` / `upstream_reason`（上游时）/ 实施时追加 `already_resolved` / `partial_outputs` / 假设驱动 `hypothesis` / `validation` / `stalled`。**实施（DIAGNOSED_AND_FIXED / already_resolved）时必填 `git_commit`**：记录你 commit 的完整 hash（`git rev-parse HEAD` 取），供框架写入修复史（root_cause_ledger）——漏填则修复史断链（commit 列显示 `-`）。
- **增量写（resume 状态传递）**：每完成一步定位 / 修复 / 验证后，就**更新** `_summary`——`symptom` / `root_cause` **覆盖为最新结论**，`fix_code_log.tried_fixes` / `_summary.validation` **追加**本条尝试。**不要只在收尾才写**：若被中断（进程被杀），resume 后你能从 `_summary` / `fix_code_log` 读到自己的进度继续，而非从零重头。`symptom` / `root_cause` 是覆盖更新（不追加），文件保持 KB 级，不会膨胀。

### 写 `report.json`（追加）
找到当前迭代条目，追加 `stage: "diagnose"` 条目（`analysis_thinking` / `findings` / `action_taken` / `outcome`）。

> 写入纪律见 `references/_shared-protocol.md`（§1 JSON 安全写入：python3 原子化 read→modify→write，禁止整体 Read→Write）。

## 定位方法（假设驱动，判断决策权在你）

> 方法 = **先全局理解 → 形成假设 → 验证推进 → 可选弹药按需取用**。你不是「按 failure_type
> 走固定步骤的执行器」，而是**判断决策权在模型**的调试者——先理解算子，再决定怎么打。

### 第 0 步：先全局理解（动手前必做）

按「**设计意图 → 实现 → golden 真值**」三层建立认知（设计产物存在时必读，见输入 `design_paths`）：

- **设计层**（有设计产物时）：先读设计产物，掌握 tiling 切分 / 流水编排 / 搬运路径 / 精度策略的设计意图——代码是设计实现的投影，先有意图再读代码，才能识别「**实现与设计偏差**」（一类高先验根因：实现没忠实落实设计）
- **实现 + 真值层**：读完整 kernel 源码 + golden + 失败证据，形成认知：
  - 这个算子做什么、数据流是什么
  - 失败症状（如全零输出）**可能指向哪层**——局部（一处 API/对齐/dtype）还是全局（算法/数据流）

这决定你选哪条路，不是「就地修那一处」的机械动作。**输出全零 / 全错 / 数据流断裂是强全局症状**，
先推演算法，别急着查 API 约束。

### 第 1 步：形成假设（改动必须有预测）

动手前写结构化假设（写进 `_summary.hypothesis`）：
- `hypothesis`：我改 X 因为认为根因是 Y
- `evidence`：支持该假设的证据（golden 对比 / printf 输出 / 数据流分析）
- `predict`：改完后应观察到的现象（如「M counter 应从 0 变为 19058」）

**没有 `predict` 的改动 = 试错法，禁止**。试错法的本质缺陷：无预测 → 证伪不产生新信息 → 认知不推进
→ 无限循环。

### 第 2 步：验证假设 → 更新认知（无论对错都回填 `_summary.validation`）

- 假设对 → 收敛修，commit
- 假设错 → **排除这个方向**，写 validation，生成新假设（认知推进）
- 验证结果必须回填——这是「认知推进」的来源，也是「分诊错了也能收敛」的兜底

### 可选弹药（按需选用，不框死）

| 手段 | 何时用 |
|------|--------|
| **全局推演** | 症状指向全局算法（全零/全错/数据流断裂）→ 首选，脑内跑算法找根因 |
| golden 比对 | 不一致时对照 numpy 期望找发散点 |
| printf 二分 | 数值发散时插探针收敛到首个错误位置（`references/techniques/printf-bisect.md`） |
| 注释降级 | runtime crash 时注释可疑路径看崩不崩（`references/techniques/comment-bisect.md`） |
| 知识库查证 | 不熟悉 API 约束查支持矩阵/round mode（`ascendc-dev-knowledge`） |

**判断判据（帮模型，非 gate）**：
- 症状指向局部（一处 API/对齐/dtype）→ 就地查证 + 修（快）
- 症状指向全局（全零/数据流断裂）→ 先全局推演，再动手（**可重写整段**，不受「就地修那一处」限制）
- 任意手段，只要是你认为最有效的——**框架不限制打法**

### 尽力后的诚实报告（不是放弃）

当假设空间已系统穷尽（所有方向试过、认知无法再推进）时，**先自检**（对齐设计阶段 §2.9
producer 自检——自己保证确实穷尽了，不是框架替你判断）：

```
声明 stalled 前，先逐个自检：
- [ ] 我已对失败做全局理解（读完整 kernel + golden），不是从局部盲试
- [ ] 我已形成并验证了多个假设（每个有 predict + validation 回填），不只试了一两个方向
- [ ] 我已用可选弹药（全局推演/golden 比对/printf/注释降级/知识库）系统排查
- [ ] 我确认：再试下去认知不会推进（假设空间已穷尽），不是因为我"累了/想放弃"
自检全过 → 写 control.json.stalled=true + stalled_detail（含 self_check 结论），
  同时 _summary.stalled 记录详情，输出 RESULT: DIAGNOSED_STALLED
自检任一不过 → 继续调试（不许 stalled）——自检发现还有方向没试，兜底继续解决
```

- 写 `control.json`：`stalled=true` + `stalled_detail`（含 `self_check` 数组，记录上述自检项 + 结论）——**与 upstream 同路径**，框架路由读它
- 写 `_summary`：`stalled=true` + 记录详情（供报告）
- 输出 `RESULT: DIAGNOSED_STALLED`
- 这是「模型尽力后的诚实报告」，供上游/人工接续，不是空手放弃。**框架校验 stalled 必须带 self_check**——缺失则打回 retry 继续调试（不是静默接受）

### failure_type 参考（作为参考，非强制流程）

不同失败类型常配的手段（**不是必须按顺序走的步骤**——你基于全局理解判断用哪些、怎么组合）：

### failure_type == "compilation"（编译错误）
- 读编译日志（`operator_dir` 下 build log），定位第一个错误（文件:行号 + 错误描述）→ 就地修那一处 → 编译验证。
- 若为 `schema_contract`（`PD-CONTRACT` / schema 校验拒合法参数 / `not registered` / `torch.ops... not found`）→ 查 plugin 注册代码/manifest/算子声明与运行时契约的一致性（声明 dtype/format/attr 形态 vs 实际传入），修工程内对应文件（注册/声明/manifest），随 deploy 交付。

### failure_type == "runtime"（运行时错误）
1. **解码错误码**：读运行时日志提取错误码（如 507035 / 161xxx / 561002 / 561003）→ 查 `ascendc-runtime-debug` 或 `ascendc-dev-knowledge` 的错误码表 → 定位越界/同步/地址错的确切路径。
2. **ground-truth 查证**：涉及不熟悉的 API 约束（dtype 支持 / 对齐 / 同步语义），**可读 CANN 头文件 / 知识库 / 支持矩阵**（`ascendc-dev-knowledge` + `ascendc-api-best-practices`）确认真实约束——不要猜。知识源信息遗漏时先下沉各层，都没有才上报（见 knowledge_policy）。
3. **受控实验**：用单用例（`test_command --case <id>`）+ 最小改动，验证"改 X 后崩不崩"——比静态猜根因可靠。
4. **就地修**：定位到那一处 → Edit → build → 单用例验证 → commit/rollback。

**Heisenbug 告诫**：插 printf 后失败变 pass → 疑 sync 缺失或未初始化数据（时序相关）→ 调 `ascendc-sync` 查同步，**不 commit 探针**。printf 探针只在定位期用，commit 前必删。

### failure_type == "precision"（数值错误）
1. **对比 golden**：numpy 对比 output vs expected（max_err / mean_err / 误差符号 / 聚集区域）；利用 `max_diff_location`（`multi_index` 多维坐标）结合 tiling 推断嫌疑代码；多 dtype 交叉验证（FP32 过 FP16 败 → 半精度精度不足方向）。
2. **查 API 约束**：涉及 Cast / Compare / Select / Reduce 等，查对应 API 的 RoundMode / dtype 支持 / 对齐约束（`ascendc-api-best-practices/references/api-precision.md` 等）——**确认当前使用的转换/比较是否有损**（如 int64 转 fp32 排序必错、Cast 用错 RoundMode 静默留垃圾）。
3. **二分收敛**：在发散点前后插 printf 探针（或注释部分路径），逐步缩小到第一个数值发散位置。
4. **就地修**：定位到那一处 → Edit → build → 单用例验证 → commit/rollback。

**级联崩溃隔离**：若 `control.json._summary.observed_issues` 含 `cascade_suspected`，或 runtime 失败率 >80%，选 2-3 个不同 shape/dtype 的 case 独立单用例运行——单用例通过 → 确认级联，先修第一个独立崩溃的 case；单用例也崩 → case 有独立 bug。

## 结构保真（修复与设计一致，或显式记录偏离）

设计产物（tiling 切分 / 流水编排 / 搬运路径 / 精度策略的声明）是 kernel **结构**的准绳；golden 是**数值**的唯一权威。修复时：

- **「实现与设计偏差」是合法假设方向**：确认偏差 → 把实现修回设计的样子（原地修，不回炉）
- **设计与 golden 冲突时以 golden 为准**就地修（数值正确性不因设计让步）
- **结构完备性断言**：修复引起的 kernel 结构变化，**要么与设计产物声明一致，要么必须写 `fix_code_log.design_deviation`**（偏离维度 + 理由）——禁止未记录的结构偏离。维度取值：`tiling` / `pipeline` / `data-movement` / `precision-strategy`

## API 使用红线（实施前必读）

修改 kernel 代码前，对不熟悉的 AscendC API 按知识源优先级查证：**用法/避坑先查 `ascendc-api-best-practices`**（API 正确用法、精度/对齐/dtype 约束，如 `references/api-precision.md`）；**裸签名/存在性判定再查 `ascendc-dev-knowledge`**（`api_reference_docs/INDEX.md`：① 精确搜 API 全名 → ② 模糊搜（去前缀/后缀 + 按功能分类「数据填充」「基础算术」等）→ ③ 都找不到 = **知识库未覆盖，不等于 API 不存在**——知识库是精选子集，索引缺口不能当 ground truth 排除修复方向。此时先定向查证再下结论：已知精确路径的定点读 / API 名锚定的窄域符号 grep（限定单目录树，禁跨全树广撒网）/ 交互下向用户澄清确认——定向查证一次未果即降权该方向继续其余方向，不在查证上无界打转；定向查证仍无证据，才写 `_summary.validation`「存在性存疑（知识库与定向查证均未覆盖）」并**降权**该方向（不写死「不存在」排除）。**禁止的是广撒网式全树 grep CANN 系统路径**（`$ASCEND_TOOLKIT_HOME`、`/usr/local/Ascend/`——读入量撑爆上下文）；定点读与窄域锚定查证不受禁）。编译报 linker "cannot open .o" 时先找 compiler error——通常是 API 不存在/dtype 不匹配导致静默编译失败。

## printf 二分 / 注释降级（可选技巧，按需参考）

定位手段是**可选技巧**（不是独立 phase、不是强制流程）——需要时按需使用：
- **printf 二分**：数值发散时，把公式拆成步骤，在关键点插 printf，build→跑单用例→读输出→对比 golden 中间值→缩小到首个发散点。见 `references/techniques/printf-bisect.md`。
- **注释降级**：runtime crash 时，注释掉/降级可疑路径（DataCopy/TQue 定向消融优先），用 crash/no-crash 判定定位。见 `references/techniques/comment-bisect.md`。
- **Heisenbug 告诫**：printf 改变时序 → 失败变 pass → 疑 sync/未初始化，不 commit 探针。

## 负向约束

- **不枚举错误类型**：不靠 Gate1/common-traps/枚举表猜根因——比对 golden 不一致就地查对应 API，不猜。
- **不生成 candidate_pool**：不维护 fix_plan 候选池、不做优先级排序、不做去重——定位到一个就修一个。
- **不 route_to**：不写 `route_to` / 不判"转 printf"——printf 二分是就地技巧，不是独立 phase。
- **不试错**：改动必须有 `_summary.hypothesis.predict`（改完应观察到什么）。无 predict 的改动是盲试、不产生新信息、认知不推进——禁止。
- **不控制循环**：不推进 `current_case_index`、不改 `status` / `debug_state` / 其他 phase 字段。
- **不写 `debug_result.json`**（由框架 `_sync_debug_result` 物化）。
- **不写别的 phase json**：`precision_run_tests.json` 只读不写。
- **非交互/编排态不提问**：诊断逻辑自包含——存在性存疑时按存疑降权继续，不阻塞；交互 TUI 下可向用户澄清。
- **不空手返回**：即使没修好，也要写 `_summary`（root_cause / 已试方向 / 假设与验证），输出对应 RESULT。
- **原子化写入**：`control.json` / `precision_diagnose.json` / `report.json` 禁止整体 Read→Write，必须 python3 read→modify→write。
- **实施纪律**：每次失败必须回滚再试下一个方向；commit 只含逻辑修复绝不含调试 printf；不熟悉 API 必先查 `ascendc-dev-knowledge` / `ascendc-api-best-practices`；编译验证 mandatory。

## 参考文件索引（本 skill 自包含）

| 用途 | 文件（相对本 skill 目录） |
|---|---|
| 通用执行纪律（JSON 安全写入 / 文件读取规范） | `references/_shared-protocol.md` |
| printf 二分技巧（何时用 / 怎么做 / Heisenbug 告诫） | `references/techniques/printf-bisect.md` |
| 注释降级技巧（runtime crash 定位） | `references/techniques/comment-bisect.md` |
| 本 phase 产物 schema | `schema/precision_diagnose.json` |

## 返回协议（RESULT 行仅供人读；路由由 _summary 结构化字段 + case.status 驱动，非 RESULT 字符串）

- 上游错：`RESULT: DIAGNOSE_UPSTREAM`
- 修好 / already_resolved：`RESULT: DIAGNOSED_AND_FIXED`
- 部分输出好转：`RESULT: FIX_PARTIAL_OUTPUT`
- 本轮无修复（尝试后未果）：`RESULT: DIAGNOSED_NO_FIX`（框架按 stop-loss 处理）
- 假设空间系统穷尽（尽力后诚实报告）：`RESULT: DIAGNOSED_STALLED`（`_summary.stalled=true`，供上游/人工接续）
