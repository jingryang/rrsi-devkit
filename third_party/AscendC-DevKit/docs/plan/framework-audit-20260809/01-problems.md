# L1 框架问题穷举审计（2026-08-09）

> 目的：把「框架问题不会遗漏」落到可核对的清单。两个来源合并：
> **Part A** = unique 批跑（20260808-162146-9f91c2）暴露的框架问题（F1-F6）；
> **Part B** = 全仓清扫（memory + docs/plan + docs/issue-analysis，只读核验到代码行号）未闭合的框架缺陷（21 条）。
> 每条标 area / 状态 / 证据。状态语义：`✅已修` / `❌未修` / `⚠仅方案未实施` / `⚖待决策` / `🔲范围边界`。
>
> 归属纪律：只记**框架侧**问题（AscendC-DevKit 框架代码/skill/编排）。算子正确性（kernel 数值/性能）与外部基础设施（LLM 网关/驱动/CANN）不在此清单——前者归算子仓，后者按 §1.11/§1.13 不归框架修，框架只负责留可诊断信号。

---

## Part A — unique 批跑暴露的框架问题

### F1 plugin 返回签名契约不一致（codegen 生成 m.def 与 C++ 实现返回类型矛盾）
- **area**: codegen
- **problem**: unique 的 `m.def` 声明 `(Tensor, Tensor?)`（定长 2），但生成实现返回 `std::vector<Tensor>`（推断 `Tensor[]` 1 变长）→ checkSchema 拒注册 → smoke 失败被 defer 到 precision_debug 烧预算。同类不一致无任何机械校验，只有运行期 checkSchema 暴露。
- **evidence**: unique_plugin.cpp:176/:149/:159；scope_guard transcript；control.json scope_reason
- **status**: ✅已修（本轮 A+B：`_plugin_return_schema_mismatch` 静态对质 + `_classify_smoke_schema_mismatch` 运行期兜底，定向 retry 回 codegen，不 defer）
- **note**: 全量 UT 3651 绿 + 40 算子语料零误报 + ST 部分绿。m.def 与 impl 返回类型一致性从此机械校验。

### F2 输出 arity / optional 存在性契约（可选输出 None vs 空占位）
- **area**: harness / skill
- **problem**: 可选输出（unique 的 inverse）在 raw op 层必须返回 None（非空占位），harness 按 proto 右补 None 对齐 golden；空占位冒充省略是契约 bug。
- **evidence**: 59b12b61 / 3c49a168（维11/P7）；同事 harness `_normalize_outputs`
- **status**: ✅已修（昨维11/P7 + 同事 harness 方案）
- **note**: 只覆盖 arity/optional **存在性**，不覆盖输出张量 **shape**（见 F4）。

### F3 GM workspace 契约（ws[0] 含 sysWs；kernel 拿用户区指针）
- **area**: skill / codegen
- **problem**: 工程（OpDef）模式框架在 workspace 前端预留系统区、kernel 入口指针偏移过系统区；tiling `ws[0]` 必须含 `GetLibApiWorkSpaceSize()`，只设用户量 → GM 越界 507015。
- **evidence**: SKILL.md §Step4②（维9）；unique_tiling.cpp:223-226（实现正确）
- **status**: ✅契约本身正确（skill 有文档 + 维9 自检；unique 的 tiling 实现正确）
- **note**: **F4 的 plugin readback 缺陷正是没遵守"kernel 指针=用户区起点"这个前提**（plugin 用完整缓冲字节偏移读用户区槽）。契约没错，是消费方（plugin）没按契约读。

### F4 动态长度输出 shape 无验证护栏 ★本轮重点
- **area**: codegen / harness
- **problem**: unique 输出长度运行时才定（N_unique=19058），codegen **无 skill 指引**、语料**无先例**，agent 即兴设计"plugin 从 workspace 读回 N_unique 再 narrow y"机制，且 **readback 读回 0** → y 恒 `Size([0])`。更关键：**框架无 shape 验证**——smoke 只验可调用、shape 错一路静默到 precision 对比才暴露。
- **evidence**: fix_iter-9 result.json（`output=Size([0])` vs golden `Size([19058])`）；decision_log "Dynamic y output size via workspace N_unique readback"；codegen skill 无 readback/shape 指引；deploy smoke 只验 callable
- **status**: ✅已修（2026-08-09 review 整改：信号接线到 scope_guard）
- **note**: 这是"codegen 对首个新算子形态（动态长度输出）生成能力 + 验证能力缺口"。P4 的确切机制（readback 为何读 0）未插桩验证——候选：plugin 读偏移缺 sysWs / count 未写 / D2H 未同步，三者之一，需实测钉死。**整改（0f2ff389 后续）**：`_harness_template.py` `_comp` 补 `shape_mismatch`/`empty_output_suspect` 字段（信号确定性进 result.json）+ scope-guard skill/agent 判定表加「output 空 & golden 非空 → upstream」行，F4 立项目标（shape 缺陷不烧精度预算）落地。

### F5 OPTIONAL 输出 → __CCE_KernelArgSize 膨胀隐患 ★本轮重点
- **area**: codegen
- **problem**: codegen 生成的 OpDef 若把输出声明 `OPTIONAL`，AscendC 编译器发射 48 字节 `__CCE_KernelArgSize`（多 8B 槽），host 只给 40 字节 → kernel 读垃圾 tiling 指针 → 507057 向量核异常。codegen 无护栏（不拦/不警示 OPTIONAL 输出），本次在算子仓修（unique_def.cpp OPTIONAL→REQUIRED）。
- **evidence**: e599bf4 提交 + unique_def.cpp:44-56 注释（明确记录机制）；run candidate_pool diag-r004-001
- **status**: ✅已修（2026-08-09 review 整改：warn-only 升级为定向 retry）
- **note**: 框架侧缺口 = codegen 生成 OPTIONAL 输出无加载期校验/警示。**整改（0f2ff389 后续）**：`_check_opdef_optional_output` 从 warn-only 升级为返回 retry 判定 dict，transition 在 manifest 校验后、deploy 前接 `_plugin_schema_retry`（全 kind，复用 A+B 预算 + D4 逃生）——aclnn 的 fail-closed smoke 无执行探针拦不住运行期 507057，必须 retry 回 codegen 重修。加 prompt 专属反馈段（kind='opdef_optional'）+ UT（点前缀/多链/feedback 分支/transition 路由）。

### F6 非 torch_op（aclnn/pybind）schema 契约 ★本轮重点
- **area**: codegen
- **problem**: A+B 契约门只覆盖 `torch_op`（有 m.def/checkSchema 解析器）。aclnn/pybind 无 m.def/checkSchema 机制，A+B 的「返回签名对质」不适用。
- **evidence**: codegen.py `_resolve_torch_registration`（仅 torch_op 有解析器）；deploy.py `_run_smoke`（aclnn/unknown fail-closed 无执行探针；torch_op/pybind 走真实 fn() 调用）
- **status**: ✅已评估，记录为**范围边界决策**（2026-08-09）
- **note**: 三机制证据分层：(1) **aclnn** = fail-closed smoke（§3.7，无执行探针，坏 aclnn op 直接 smoke 失败，无假绿），其 schema 缺陷以 aclnn 运行期错误（EZ1001 类）暴露，已有部分覆盖（`_check_plugin_schema_consistency` 告警 ACLNN_CMD 输入绑定；维5 OpDef param_type）；(2) **pybind** = 真实 fn() 调用 smoke（同 torch_op），但 pybind 签名显式、无 C++ 返回类型推断错位类问题；(3) A+B 的 m.def 返回签名对质是 **torch 特有机制**（checkSchema 推断 C++ 返回类型），对 aclnn/pybind 无对应物。**结论**：不为未见过失败的机制过早建解析器（§1.2）；触发条件已备——若未来出现「aclnn/pybind schema 不一致 → smoke 失败 → 静默 defer 烧精度预算」的真实案例，按 A+B 同思路扩展（分类运行期契约错误信号 + 定向 retry 回 codegen）。

---

## Part B — 全仓清扫未闭合框架缺陷（21 条，均核验到 memory/文档/代码行号）

### precision_debug 系（9 条）

#### B1 precision-debug-abort-false-positive
- **problem**: abort 判据单维度（`_agent_produced_output` 只看 round-suffixed phase JSON 存在性）误杀自修复型 phase（comment_bisect/printf_location）成功 spawn——成功 commit + 写 control 终态但漏写 round JSON → `consecutive_aborts=3` → `abort_exhausted` 提前退出整个 group，跳过 located_fixed 承诺的 run_tests 全量回归。
- **evidence**: memory/precision-debug-abort-false-positive.md；`precision_debug_substages.py:1582` 仍是 `_agent_produced_output`
- **status**: ⚠仅方案未实施（三维度判据 L1/L3/L4 已备 2026-08-06）
- **note**: 与 unique 批跑 P4（y=Size([0]) 只在 precision 暴露）同源——都是"框架判据/验证不完整"类。

#### B2 precision-upstream-halt-eval-loss
- **problem**: scope_guard 判 `upstream` → workflow.py:696 `upstream→__halt__` 整 run 0 评分；D9 软门只放行 `exhausted` 不放行 `upstream`——kernel 已修对（19/20+diff=0）仍被判 upstream 丢分，构造性保证未达成。
- **evidence**: memory/precision-upstream-halt-eval-loss-v020.md；docs/plan/precision-scope-upstream-halt-eval-loss/
- **status**: ⚖待决策（用户 2026-08-07 决定机制层暂不处理；方案 A/D 已备）
- **note**: 同事 243b2514 已修 harness NaN-sentinel 堵死本案触发路径，但路由/判定未改（非构造性保证）。

#### B3 precision-harness-nullable-attrs-phaseB
- **problem**: 阶段 B 未做——scope_guard 归属判据仍按错误形态误判、passed 计数不诚实（`best_passed_count=total−failed` 算术假象）、failure_type 非结构性分类（`Error:` 关键词误判 compilation）。
- **evidence**: memory/precision-harness-rejects-optional-attrs.md；docs/plan/precision-harness-nullable-attrs/
- **status**: ⚠部分实施（阶段 A v2 已落地消除 halt，阶段 B 待用户定）

#### B4 precision-debug-unique-3of20-p2p3p4
- **problem**: P2 printf_location 假 abort（agent 跑通用例未落 round JSON → 提前退出）；P3 diagnose 把系统性 dtype 缺陷 route 到单点 printf；P4 d7ba88e 未回归致 best_commit/report 不一致。
- **evidence**: docs/plan/precision-debug-unique-3of20-rca/
- **status**: ⚠仅方案未实施（P2 已并入 B1；P3/P4 未实施）

#### B5 best-commit-multidim-d1
- **problem**: `_update_best_metrics` 仍 "passed_count strictly greater only"——converge 全 0 通过时 rollback 到 entry，打掉 crash-fix 的修复。
- **evidence**: memory/batch-214817-scaffolding-fixed-d1d2o2-deferred.md；batch-134831-fixes-verified-v020.md
- **status**: ⚠仅方案未实施（D1-A 已备；触发场景已消除，不阻塞重跑）

#### B6 scope-guard-design-dim-d2
- **problem**: scope_guard 判定表无 design 维度，误判 upstream(codegen) 实为 design shape。
- **evidence**: memory/batch-214817-scaffolding-fixed-d1d2o2-deferred.md；D2-A 方案已备
- **status**: ⚠仅方案未实施（待真复现）

#### B7 precision-dtype-coverage-gap
- **problem**: 纯 devkit 模式（无 cann-bench cases.csv）退回 LLM 生成 case，dtype 覆盖靠 LLM、无硬门强制 bf16 → precision 全绿但终评掉分。
- **evidence**: memory/precision-debug-dtype-coverage-gap.md
- **status**: ❌未修（batch 主路径已解决；残留为纯 devkit 模式硬门）

#### B8 fallback-masked-report-rendering
- **problem**: 框架 report 不区分「kernel 验证通过」vs「host 兜底通过」（`fallback_masked` 字段已落盘但框架 Python 渲染零命中）。
- **evidence**: docs/plan/unique-codegen-scalar-collapse/03-impl-skill-guardrails.md:101,136；`grep fallback_masked src/` 零命中
- **status**: ❌未实施

#### B9 diagnose-route-codegen-db2
- **problem**: diagnose `route_to=codegen` 路由暂缓——若 codegen 自检拦不住且 fix 产生 host 兜底，无反馈通道。
- **evidence**: docs/plan/unique-codegen-scalar-collapse/02-analysis.md:203
- **status**: ⚖待决策（用户拍板暂缓留档）

### codegen 系（3 条）

#### B10 a5-regbase-manifest-callable-target-gap
- **problem**: `_transition_regbase_s5` 在「manifest 在、callable_target 缺」仍 halt（`reason=callable_target_missing`），未收敛到 A3 已提取的 `_ensure_manifest_callable_target` + `_artifact_retry`（§2.5 分歧）。
- **evidence**: docs/issue-analysis/20260804-codegen-manifest-contract-a5-regbase-handoff.md；`codegen.py:2478`
- **status**: 🔲范围边界（A5 regbase 归同事，codegen-a5-ownership-boundary）
- **note**: handoff 已给收敛建议。

#### B11 q3-plugin-manifest-input-mismatch
- **problem**: codegen 产出 plugin m.def tensor inputs 与 manifest inputs 不对齐 → ACLNN_CMD 位置绑定漂移 → launch 崩（507035 cascade eval 0）。`_check_plugin_schema_consistency` 仍 "Observable warn only"，未根治。
- **evidence**: memory/batch-20260802-171400-q3-launch-drift.md；`codegen.py:1663`（warn only）
- **status**: ⚠部分缓解（仅告警，agent 侧非确定性仍在）

#### B12 codegen-native-dtype-dispatch
- **problem**: 多 dtype 算子 codegen 仍可能生成「统一 float 中转」有损路径（unique 17/20 bit-exact 失败）；native-dtype 自动分派未实施，仅 skill 引导。
- **evidence**: docs/plan/codegen-dtype-strategy/；precision-debug-unique-3of20-rca/（P1）
- **status**: ⚠部分实施（skill 引导落地，无确定性 dtype 分派机制）

### card 隔离（1 条）

#### B13 card-isolation-subprocess-bypass
- **problem**: card 隔离在 precision_debug/deploy subprocess 路径失效——`state.npu_id or 0` 硬编码，pool-acquire 模式下所有并发算子挤 device 0（实测并发占用）。违反 §2.5 + P69。
- **evidence**: memory/card-isolation-subprocess-bypass.md；`precision_debug_substages.py:1398` / `deploy.py:815`
- **status**: ❌未修（方案待新会话 L3）

### harness（1 条）

#### B14 harness-string-input-npu-crash
- **problem**: harness/golden 输入生成对所有 input 统一 `.npu()`，string 型输入（scatter_pa_kv_cache cache_mode）抛 AttributeError → kernel 未跑即崩 11/11 → scope_guard 判 upstream(golden) halt。
- **evidence**: memory/batch-20260802-5438ad-2e74cb0b-validated.md；batch-20260801-231442-5438ad-issues.md P1
- **status**: ⚖待决策（产权待裁定；`_apply_get_input` 已滤非 tensor 标量为部分缓解）

### 可观测性（3 条）

#### B15 opencode-retry-log-blindspot
- **problem**: opencode 内部限流重试（[1310]/[1313]）在 run.log 是静默 gap；诊断只活在 opencode.log（UTC）+ db，run.log 零信号（违 §1.2 可诊断性）。本次 unique halt 的 4 次 turn_stall 正是此盲区。
- **evidence**: memory/opencode-app-log-retry-blindspot.md；本次 run `.opencode_home/data/opencode/log/opencode.log` 62 次 1313
- **status**: ❌未修（可观测性缺口；网关限流本身不归框架修，缺的是 run.log 信号）

#### B16 batch-id-echo-resume-gap
- **problem**: `run --batch` 不 echo `batch_id:` 到 tee 日志 → 脚本 grep 失败 → `RESUME=1` 报"找不到历史 batch"。
- **evidence**: memory/batch-id-utc-timestamp-resume-caveat.md
- **status**: ❌未修（便利性缺口，有绕过）

#### B17 q9-report-loopback-observability
- **problem**: report.md 的 `iterations` 列折叠隐藏跨 stage loopback，判真实 loopback 须读 events.jsonl 重入。
- **evidence**: memory/q9-design-loopback-observability-deferred.md；84-batch-205112-issues-summary.md Q9
- **status**: ⚠待办（用户指示先记录暂不做）

### eval（1 条）

#### B18 cannbench-crash-cascade-zero-score
- **problem**: cann-bench kernel_eval 单 case 崩 → cascade 全部 → 0 分；profiler 活跃时评测跳过 recover_full → 判 unrecoverable。
- **evidence**: memory/cannbench-eval-crash-cascade-zero-score.md
- **status**: ⚖待决策（用户 2026-08-03 决定不处理，改"让 debug 通过全部用例"）

### skill / tech debt（2 条）

#### B19 build-error-classify-dual-source
- **problem**: build 错误分类双源——skill `classify_compile_error.sh`（shell）与 `domain.build_log_scanner.classify_build_error`（Python）未统一（§2.5）。
- **evidence**: memory/codegen-signature-footer-phase1.md（登记 tech debt）
- **status**: ❌未修（tech debt，改一处漏一处风险）

#### B20 stage-timeout-granularity-p4p5
- **problem**: P4 stage→单 skill 限制；P5 `_schema_files` 硬编码在 Python stage class（双重来源）。
- **evidence**: docs/plan/stage-timeout-granularity/01-problems.md；`design_substages.py:258`
- **status**: ❌未修（低优先级）

---

## 汇总与下一步

| 状态 | 数量 | 条目 |
|---|---|---|
| ✅已修 | 5 | F1（A+B 本轮）、F2（昨维11）、F3（skill 契约本身）、**F4（动态输出 shape）★**、**F5（OPTIONAL argsize）★** |
| ❌未修（正确性/隔离） | 1 | B13（card 隔离） |
| ❌未修（可观测/便利/tech debt） | 7 | B7、B8、B15、B16、B17、B19、B20 |
| ⚠仅方案未实施/部分 | 7 | B1、B3、B4、B5、B6、B11、B12 |
| ⚖待决策 | 4 | B2、B9、B14、B18 |
| 🔲范围边界 | 2 | F6（aclnn/pybind，A+B 明确未覆盖）、B10（A5 regbase 归同事） |

**本轮已闭环（2026-08-09，用户拍板 F4/F5/F6 + review 整改）**：
- **F4 ✅**：skill 新增「动态长度输出定型」指引 + 自检表维12 + comparator 结构化信号（`shape_mismatch`/`empty_output_suspect`）+ **接线（review 整改）**：`_harness_template.py` 把信号落进 result.json `output_comparisons`，scope-guard 判定表加「output 空 & golden 非空 → upstream」行——scope_guard 判归 plugin/harness 层不烧精度循环的目标落地。
- **F5 ✅**：skill 自检表维5b（OpDef 输出禁 OPTIONAL，可选性归 schema `Tensor?` + plugin None）+ **门升级（review 整改）**：`_check_opdef_optional_output` 从 warn-only 升级为返回 retry 判定 dict，transition 接 `_plugin_schema_retry`（全 kind 防 507057，aclnn fail-closed smoke 拦不住运行期异常→必须 retry 重修）。
- **F6 ✅已评估**：记录为范围边界决策（aclnn fail-closed / pybind 真实调用 / A+B 是 torch 特有机制），触发条件已备。

**剩余未闭合**（非本轮范围）：Part B 的 21 条（B1-B20）+ Part A 已修项之外的算子侧 P4 具体修法（readback 偏移需在算子侧按新指引修正并插桩验证）、P5 性能（算子侧）。

**确认无遗漏的依据**：Part B 由只读 agent 全量清扫 memory + docs/plan + docs/issue-analysis，每条核验到文件:行号；Part A 由 unique 批跑实际产物（control.json / result.json / decision_log / plugin/kernel 源码）支撑。两者无交集重复，且未发现"memory 声称已修但代码仍有痕迹"的第四条漏网（agent 已核验 10 项"声称已修实为已修"）。
