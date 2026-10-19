# docs/plan 问题状态总览（2026-06-27 截止）

> 快照时刻：commit `7bf79a6`，包含本轮 mode-误判-blocking 修复 + 通路 ST 精简。
> 各目录的 L1 问题记录均以 `01-problems.md` 为入口，L3 方案分析为 `02-analysis.md`，L4 实施方案为 `03-impl-*.md`。

## 各 plan 目录状态

### ✅ 已解决（有分析 + 有实施）

| 目录 | 问题 | 状态 |
|------|------|------|
| **design-stage-refinement** | P1-P6（详设 agent 缺 skill / 裸上下文 / 产物覆盖 / loopback 黑盒 / 混入旧 skill / 旧 agent 脱节 / 缺产物清单） | `02-analysis.md` + 4 份 impl doc |
| **e2e-stability** | P1-P8（max_turns 截断 / 失败静默继续 / skill 缺失 / stall 等，全部标记 ✅） | `02-analysis.md` + 3 份 impl doc |
| **first-principle-tui-compat** | F1-F4（schema 不随 skill / 输入靠 prompt 注入 / 文件接力被剥离 / 目录外资源） | `02-analysis.md` + `03-impl-a-schema-converge.md` |
| **test-design-refinement** | T1-T4（输入失配 / 多 skill 投递 / 文件名接力缺口 / 游离 skill 体系） | `02-analysis.md` + 4 份 impl doc |

### ✅ 已实施但问题文档未更新 mark（pipeline-observability）

| 问题 | 实施内容 | 涉及文件 |
|------|---------|---------|
| P8 日志行缺时间戳 | `Logger._ts()` 为每行输出添加 `[HH:MM:SS]` 前缀 | `infra/logger.py` |
| P9 stage abort 后 workflow done 显示 0.0s | runner 拆两层 + `stage_aborted` event + dispatcher 墙钟兜底 | `kernel/runner.py`, `kernel/event.py`, `application/dispatcher.py`, `application/report.py` |
| P10 agent session_id 未在日志中打印 | 首次捕获 session_id 时打一条一次性 `agent_session` 日志 | `capabilities/agent/sdk_backend.py` |
| P11 load_profile 日志重复打印 | 添加 `@lru_cache` 缓存 | `adapters/repository/profile_loader.py` |
| P12 "IO chain issue" WARN 误导用户 | warn→info + 措辞改为 `(user-provided inputs — validated by preflight)` | `application/dispatcher.py`, `orchestration/workflow.py` |
| P13 agent_stream 不区分 block 类型 | 追加 `[text]` / `[thinking]` / `[tool:<name>]` 标签 | `capabilities/agent/sdk_backend.py` |

### ✅ 本轮新解决

| 目录 | 问题 | 方案 |
|------|------|------|
| **precision-runtime-comment-bisect** | P1 runtime 定位无二分收敛状态机 / P2 无行级确认 / P3 单根因即 break / P4 定位与应用职责混杂违 §2.5·§2.7 / P5 comment-bisect 悬空引用 | 新建 `CommentBisectSubstage`（仿 printf_location）+ skill 四件套 + agent；fix `pool_exhausted+runtime`→`need_comment_bisect`；删 fix 内嵌消融（§2.5）。D1-O2 独立 substage / D2-O1 增量多根因 / D4-O2 DataCopy·TQue 先验定向消融。**A3-only**，全量 orchestration UT 1419 passed/0 failed。heavy_llm 真实全流程待用户决策（§3.11） |
| **precision-debug-agent-abort** | P1 run_tests agent 中断后 scope_guard 被跳过（`agent_aborted` 在 `scope_checked` 之前被检查）；P2 其他 5 个 substage 无中断检测；P3 无连续中断退火 | 基类统一检测（`_agent_produced_output`）+ `_resolve_abort_condition` 统一路由 + 独立 `consecutive_aborts` 计数器（≥3 → escalate）。改动 2 文件（substages + tree），7 个 substage 全覆盖（run_tests 自有 abort 路径 + diagnose/fix/diagnose_refine/printf_location/comment_bisect/scope_guard 走 `_handle_abort`）。**代码曾因未提交丢失（`git log -S consecutive_aborts`=0 证实从未入库），2026-07-23 已恢复 + 补 TDD `test_precision_debug_agent_abort.py`（31 用例守护：transition_table 路由 / `_resolve_abort_condition` 优先级 / 计数器磁盘往返 / `_agent_produced_output` 判据 / `_handle_abort` bump_counters 区分 / RunTests 自有路径 / 退火升级 / 正常产出清零 / ScopeGuard abort 不触发契约错误）+ 全量 orchestration UT 1450 passed/0 回归** |
| **pipeline-observability** | mode 误判 blocking 导致 non-interactive run abort | L1 `requirement-analyst.md` skill prompt 明确区分 C API 必传参数；L2 `requirement.py` 框架兜底（首次注入 loopback feedback，二次才 abort）。通路 ST 测试精简（1500s→125s） |
| **e2e-moe-re-routing** | P1 脚本 chip 默认 A2≠硬件 A5；P2 precision_debug 耗尽 __halt__ 掐断链路致 cannbench_eval 不出分；P3 devkit ① harness 按单输入单输出设计，对多输出算子 moe_re_routing 失真（6 gap） | P1 对齐 A5；P2 precision_debug 软门（仅 self_evolve_op，耗尽→cannbench_adapt）；P3 修 6 gap（多输出 zip 比对 / get_input / int dtype / 每输入值域 / 丢弃 null 可选输入）。TDD 6 测试，全量 UT 0 回归。**E2E 跑出分待运行（heavy_llm）**；P4（4 个 A2-硬编码 UT 在 A5 机失败）记 follow-up |
| **printf-selfclose-fix** | P1 printf 只定位不修，上下文在 handoff 中丢失，fix 重建上下文重复查知识库；P2 复杂 case fix 验证失败后 `fix→printf→fix` ping-pong；P3 `located→fix` 路由在改为自闭环后成为死代码 | printf 定位到根因后自己修复、编译、验证、commit；修好 → `located_fixed → run_tests`；修不好（连续 3 次无好转）→ exhausted → skip case → fix。删 `located → fix` 路由。改 10 文件：框架 2（tree + substages）+ agent manifest 1 + skill 方法载体 3（SKILL.md + printf_location.md + gate3-printf-bisect.md）+ adapter 2（SKILL.md + transition.py）+ 测试 1 + 状态文档 1。comment_bisect 保持现状后续评估。 |
| **per-output-sinking** | P1 多输出算子按 case 整体判定 refuted：一个 output 未修复 → 所有 output 的改善全被回滚；P2 `partial_output` 改善检测纯靠 agent 声明 | fix agent 按 output 逐项追踪修复效果（`per_output` 记录 diff_before/diff_after）；任一 output 改善即 commit + 标 `partial_output`；无改善的 output 标记 refuted 供 printf 二分细修。框架 `partial_output → run_tests` 路由。`best_commit` 语义修复：仅 RunTestsSubstage 全量回归后记录，bounds_check 不再记。 |
| **bounds-check-iterative-fix** | P1 bounds_check 修复失败即回滚（含有效改善如 dead buffer 删除）；P2 `fix_failed → diagnose` 而非 `→ run_tests`；P3 修复不优先查 tiling 侧 | 3 轮迭代选最优（轮间不 rollback），有改善即 `FIXED`，`fix_failed → run_tests`。修复优先级：UB_TOTAL→查 tiling factor / 对齐 padding→查 tiling 公式 / kernel buffer 缩减后备。 |
| **scope-guard-dedup** | ScopeGuard 两段短路重复；`scope_verdict` 新增 `pass`/`upstream` 快捷路径 | 合并为单段短路：`scope_checked or verdict in (upstream,pass)` → 跳过。新增 `scope_verdict` 字段（`pass`/`upstream`/`none`）。 |
| **route-scalar-param-elementwise-miskill** | P1 `_is_scalar_param` 用 `shape==[]` 判 scalar，误把逐元素/广播算子(Maximum)的 wire tensor 全搬 attrs 清空 inputs/outputs → codegen `PreconditionError` halt（致死主因）；P2 归档存 route 前版本掩盖 transition 改写（诊断误导）；P3 误搬 WARN 产生但无消费者（§1.2 可诊断失守）；P4 validate(reviewer) 跑 28 turns 未校验 design_spec schema 完整性（防线失守）；P5 `_is_scalar_param` 第二调用点 docgen OpDef 渲染同源受污染 | **A'** 提取共享 `is_scalar_entry`（业务语义 6 级 precedence：role/param_type/alias/format:SCALAR/shape 键存在性/scalar-type，§1.10 不用机制特征 `shape==[]` 代理）让 `_route`/`_route_scalar_params`/`_opdef_anchors` 三路径共用，**删 `_is_scalar_param`**（§2.5 单一通路）→ 治 P1/P5；**D 终版** design_spec IO 以 golden 函数签名（`classify_golden_params` 按 `Tensor` 注解确定性分，§1.13 主权威）+ requirement 输出（辅）就地确定性修复——误搬撤销 + 缺失回填，**不 halt 不 loopback 空转**（IO 权威在 golden 固定输入，重跑 design/req-analysis LLM 是空转）→ 治 P1 兜底/P2/P3；codegen halt 仅兜底「golden+requirement 都解析不出 IO=算子真无 IO」（真不可解决）；F（validate 非空门）**撤**（§2.9 只拦截不解决=discover+regenerate 禁区），P4 由 D 让 design_spec 不再被清空 + 既有 schema 校验缓解。全量 UT **3504 passed/0 failed**；heavy_llm（逐元素算子 design→codegen，§3.11）待用户重跑该算子验证 |
| **op-knowledge-constraints** | P1 `SetAtomicAdd` 不支持 int64 → 跨核写同 GM 地址丢更新；P2 strided `DataCopyPad` 尾块搬运行距≠寻址行距 → 行错位/越界；P3 `ReduceSum` 高阶 API A2/A3 `srcInnerPad` 仅 true → 非对齐 OOB；P4 `Tanh` 原语两种精度不足模式（`1±tanh` 抵消 / 近零域 ULP 爆炸） | **L1 记录 + 知识固化（PR #62）**：P1–P4 各配 `ascendc-op-design-shared/references/` 参考文档（atomicadd_dtype_fallback / datacopy-stride-consistency / reduce_align_strategy / numerical-stability-guide）+ 8 个设计/编码/调试 skill 的结构信号判据与自检项 + sync 陷阱13（DataSyncBarrier 非流水间同步）。L1 见 `op-knowledge-constraints/01-problems.md`。无 Python 改动，UT/ST 回归通过 |

### ⚠️ 未实施

| 目录 | 问题 | 状态 |
|------|------|------|
| **stage-timeout-granularity** | P4 stage→单 skill 限制（同 stage 无法调用多个 skill） | 无分析无实施。doc 标记"低"优先级，"暂不影响本次" |
| **stage-timeout-granularity** | P5 `_schema_files` 仍硬编码在 Python stage class 中 | 部分缓解（`artifact_contract()` 从 STAGE_SKILL_MAP 取 skill 名化了单一来源），但 `_schema_files = [...]` 列表本身还在 |
| **integration-quality** | P6-a agent stall（tiling 阶段 agent 频繁 3 轮无输出崩溃） | 无分析无实施。doc 标记"严重" |
| **integration-quality** | P6-c loopback 中 schema 不对齐（`tiling_results.json` 聚合缺失 buffer_kernel / precision_perf） | 无分析无实施。doc 标记"严重" |
| **precision-debug-unique-3of20-rca** | P1 unique kernel float 中转 → 17/20 精度（codegen/详设 dtype 策略）；P2 printf_location「假 abort」（agent 跑通用例但未落 round JSON）→ `consecutive_aborts=3` → `abort_exhausted` 提前退出（3/20，预算未耗尽）；P3 diagnose 把系统性 dtype 缺陷 route 到单点 printf；P4 d7ba88e 未回归致 best_commit/report 不一致 | **有 L1+L3 分析，未实施**（本轮按用户要求只落文档、不改代码）。决策：P2=A(relay 实质产出判据)+B(agent 强制落 round JSON)；P3=A(diagnose 系统性分支，业务语义判据)；P1=方向 native-dtype 路径，移交 codegen/详设另立。与 `precision-debug-agent-abort`（abort 机制）正交——本 P 修「abort 判据语义被契约失配污染」 |
| **codegen-dtype-strategy** | P1 precision-perf R1「一律升精度」对非计算/位敏感算子误导 + 无往返/特殊值保真分析；P2 template-division LD1 二元「是否升 FP32」无派生判据；P3 buffer-kernel workspace 示例硬编码 `sizeof(float)`；P4 codegen 维4 漏 UB 侧标量 cast 漏斗；P5 coder agent「Use fp16 for compute」放任自选；P6 red-line 无 lossy dtype 项；P7 知识库 A1 卡误导 | **Phase 1+2 完成（L1+L3 文档 + 7 文件引导编辑落地）**。三路调研确认根因在详设 skills（codegen 忠实实现 float 漏斗、未自创）。全链引导文本已落地 7 文件（precision-perf/template-division/buffer-kernel/dev-coding 维4/coder/red-line/A1 卡）。实施期沉淀两点框架精化：①**解耦「升精度」与「升到 FP32」**（升精度是浮点算术累加技巧，非普适 reflex）；②**升精度是浮点概念，整数不升精度（int→FP 丢精度禁止）**。按 §1.12 全部按算子类别（是否计算型+是否 bit-exact）判不认名。desk-check 确认每条新规则拦住旧 unique float 漏斗；无 Python 改动 |
| **precision-debug-a5-dump-evidence-misroute** | P10 dump_evidence 自由文本 regex 把 kernel_debug 叙述的**修复前崩溃历史**误判为当前 VECTOR_ERROR，覆盖结构化声明 `debug_status=fixed` + `verification.crash=resolved` → 已修复 case 被连续误路由回 vector_error_debug 空转（真实轨迹 group_norm 20260808_090335 中 kernel_debug round 4/5/6 各误路由一次，浪费 3 轮 agent 调度，最终第 4 次才到 regression） | **已修（L1 P10 记录 + 修复 + UT）**。`_extract_error_type` 新增 `_declares_resolved_crash` 业务语义判据（§1.10）：结构化 `verification.crash=resolved` / `after_passed=true` / `vector_error_evidence.cleared=true` 声明优先于自由文本 regex；无验证证据的历史叙述仍触发 override（legacy 安全网保留）。新增 3 个 UT（`test_verified_fix_not_routed_as_vector_error` / `test_fixed_without_verification_still_overrides_to_vector_error` / `test_verified_fix_routes_to_fixed_not_vector_error`），相关 UT 全量通过（258+107 passed，0 回归） |
| **precision-report-rendering** | P1-P7（precision_report.md 渲染缺陷：迭代轮次恒 1 / 趋势分母归零 / 全过用例表空且表头误导 / 修复 commit 全缺失 / 最大误差渲染 None / 趋势缺最终全过轮 + 同轮重复 / running 算子报告陈旧）。20260808 批 8 算子中 5 个全过算子的报告全部畸形，resize_bilinear/group_norm（有残留失败）报告正常——触发条件=全过终态 | **✅ 已实施（2026-08-09）**：`_write_precision_report_impl` 重构（total 优先级链 / history 派生 round / 全过显式 ✅ / None→`-` / 趋势去 fc>0 过滤 + 同轮去重）+ **P4 写侧 ledger 归一化**（fix/bounds_check transition 合并 commit 进 `root_cause_ledger`，报告只读 ledger 单一源）+ P7 写点移出 if 块。TDD 10+7 用例过；orchestration UT 1890 零回归；8 算子快照回放：transpose（痛点）轮次5/全过✅/分母20/5 commit 全可见。残余观察：sigmoid 等轮次=history max round（框架轮次计数未递增，非渲染问题） |
| **design-math-claims-verification** | D1 设计缺"化简/降维"声称的数学验证机制（设计 skill 零 Python）/ D2 设计不声明 support_domain 与 golden 域无对质 / C1 codegen 无域对质 / B1 debug 域缺口识别缺失 + fallback_masked 零消费（=审计 B8）/ T1 transpose kernel 只支持循环旋转 + host 兜底 → 评测 8/20 CPU-fallback 反作弊 0 分（precision 却 20/20）。数学实证：单个 2D 转置≡循环旋转，rank=4 只 4/24、rank=5 只 5/120 perm 可做 | **Phase 1+2+3 skill 已实施（2026-08-09）**：①设计侧 `references/design-math-claims/`（检查清单+通用验证模板+verified_facts）+ general-design/template-division 自检项（主动 Python 验证、不 halt、先自修）+ design_spec `support_domain`/`known_limitations` 字段；②codegen 域对质 `domain/support_domain.py` 引擎 + requirement.json `domain` 结构化字段 + `_emit_domain_gap_signal`（非 halt 信号，缺口写 domain_gap_signal.json，不 loopback）；③debug printf skill 补 host-fallback 检测（标 fallback_masked）+ scope-guard 判定表「fallback_masked→upstream(design)」行（fix skill 本有）。UT 331+139 过零回归。anchor 扩展已撤（§2.9 门边界）。**待实施**：Phase 4 transpose 算子算法②落地（需 NPU 验证）、框架消费 fallback_masked（B8，归 precision-report-rendering）。用户拍板：①通用不损正确性②正确性优先+尽可能好性能③先落文档再实施 |

## 附：pipeline-observability 问题全景

| 编号 | 问题 | 状态 |
|------|------|------|
| P1 | SDKBackend LLM provider 信息错误 | ✅ |
| P2 | gd-generate 命名不一致 | ✅ |
| P3 | ForkJoin 并行日志不含模板路径 | ✅ |
| P4 | gate stage is_satisfied 不检查 blocking_issues | ✅ |
| P5 | 超时检查粒度太粗，overshoot | ✅ |
| P6 | SDKBackend LLM provider 与 SDK 脱节 | ✅（随 P1 删） |
| P7 | 多轮迭代不输出触发原因 | ✅ |
| P8 | 日志行缺时间戳 | ✅（文档待更新） |
| P9 | stage abort 后 workflow done 0.0s | ✅（文档待更新） |
| P10 | agent session_id 未打印 | ✅（文档待更新） |
| P11 | load_profile 重复打印 | ✅（文档待更新） |
| P12 | IO chain issue WARN 误导 | ✅（文档待更新） |
| P13 | agent_stream 不区分 block 类型 | ✅（文档待更新） |
| A | mode 误判 blocking | ✅（本轮） |

### 🔄 进行中

| 目录 | 问题 | 状态 |
|------|------|------|
| **opencode-streaming-transport** | P-S1 中间 turn 不实时落日志（阻塞 POST 黑盒）/ P-S2 serve 中途杀中间 turn 全丢 / P-S4 SSE 事件载荷未实测 | spike 全绿（2026-07-20）→ 实施 **B**（POST 权威+SSE 观测，L3 §10 A→B 修正）：新增 `opencode_sse.py`+`_subscribe_sse` seam，`agent_stream` 实时落日志（真 serve 验证 8 条含 tool:read）；全量 UT 2614 绿。A 收敛/@llm ST 固化/tokens-填-metrics 留 follow-up |
| **step-82 cannbench-adapter-convergence** | cann-bench eval 全 0：PYTHONPATH namespace 遮蔽（src/cann_bench_utils src-layout 嵌套包外层无 `__init__`）+ cann_bench_utils `_C` 未构建（profile 未声明）+ cann-bench 适配散落 stage/domain/adapter 三层 | 适配收敛到 `adapters/evaluation/`（cannbench_env 共享装配 / cannbench_scorer 评分+预检 / cannbench_adapt wrapper-gen+m.def）；两 stage 退化编排；src-layout 扫描根治遮蔽 + 可达性预检 + `eval_prepare` 自动 build；UT 3206 绿、分层依赖过、0 回归。**heavy_llm 真实链路 ST 待 NPU 环境验证**（review M1，ST 延后） |
| **harness-timeout-adaptive** | P1 harness 看门狗硬编码 120s 不可配置 / P2 超时被当 runtime 进精度循环 / P3 超时时 case_details 空 shape 丢失 / P4 run_tests 观察无传递机制 / P5 scope_guard 判定输入不全 | 超时配置化（`timeouts.harness_sec` 默认 + control.json `harness_timeout_sec` per-run 覆盖）+ run_tests agent 大 shape 语义评估放大重试（×4 每级、上限 1200、持久化共享三阶段）+ `observed_issues` 通用观察清单如实传递 + scope_guard 重判（含「fix 引入回归 vs 真实上游缺陷」区分，防误 halt）。7 代码 + 3 skill 文件，改动极小 |
| **unique-codegen-scalar-collapse** | P1 codegen 把设计的向量化实现降级为单核标量 O(n²) 插入排序（多核 bug 误诊为硬件一致性，D4，tiling 硬编码 blockDim=1）/ P2 precision fix 用 host `at::_unique2` CPU 兜底绕过 NPU kernel 制造 20/20 假绿 / P3 cannbench_eval 30min 超时失败无分 / P4 plugin 越界脚手架（手写 ACL 管道 + host 归约 + CPU 兜底）/ P5 可选输出 harness 契约隐性耦合 / P6（观察）D3 私改设计 F3 NaN 语义 / **P7 harness 输出数量不匹配空对比假绿洞——条件输出算子 11/20 用例空对比假绿（=算子产出契约 bug：raw op 返回二元组 vs golden 单张量）** | 设计链分析全部正确，断点全在 codegen+fix。L1 `01-problems.md`（P1-P7）+ L3 `02-analysis.md`（用户拍板冻结）+ L4 `03-impl-skill-guardrails.md`。**护栏 + 假绿洞 + 契约根治已实施（2026-08-08）**：①codegen 维4 AR-1 升级 ②维10 plugin 脚手架边界 ③fix host fallback 检测 + `fallback_masked` ④fix L142 扩展 ⑤schema optional 字段 ⑥**P7 双端**（空 verdicts→raise + judge 查 error）⑦**P7 根治三层**：A harness golden-arity + proto-OPTIONAL 消费；B cannbench_adapt 保留 codegen 非直通裁剪 wrapper；C codegen 维11 条件输出建模（通用、禁空占位冒充、脚手架不实现算子内部逻辑）。**验证：受影响 UT 702 passed 0 回归 + 新增 golden-arity/保留 wrapper 测试**。遗留：D-P4 kernel 不重做、D-B2 路由暂缓、框架 report 渲染 fallback_masked 未实施 |
| **simt-ub-window-misconception** | P1 vf_experiences 把 SingleOperatorLaunch 默认 SIMT 共享内存窗口（8KB）误记为"绝对 [0,8192B) 硬约束、与分配方式无关"，导致生产 gather 全程按 256×dtype 压批、isolated vf-test 手工 `LocalTensor(VECCALC,0,8192)` 规避；P2 错误已传播至 INDEX/gather/rmw 经验 + regbase SKILL 检索说明；P3 skill 未写清 SIMT 共享内存申请/使用方式 | **设备实测反证（2026-09-02, Ascend950DT/CANN 9.1.0）**：SIMT 共享内存窗口 = launch 配置（RTS `dynamic_share_mem_size` / `<<<>>> dynUBufSize`），SingleOperatorLaunch 默认 0→8KB；数据 64KB + 配置 65536 → **64KB 全窗口 PASS**，默认下 >8KB → VEC_ERROR。官方模型：SIMT 共享内存 = UB（256KB），分区 static/dynamic/预留8KB/DCache≥32KB，动态共享可配到 ≈216KB。L1/L3/L4 见 `simt-ub-window-misconception/`。**修订**：源头 infra 文件改"窗口=launch 配置（默认 8KB，可放大）"+ 实测表 + 官方分区模型 + 正确用法（TPipe/TQue + GetPhyAddr）；INDEX/gather/rmw/SKILL 同步去"绝对/硬约束"措辞 |
| **simt-host-dynubuf-guidance** | P1 simt skill 知识层教的是已废弃接口 `SetLocalMemorySize`，未标注现名 `SetDynUBufSize` 与"默认 0 = 不声明"语义；P2 设计/编码链（tiling SIMT 路由段 / regbase B2 host tiling 自检）无 SIMT Dynamic UB 必配引导，历史生成完整算子（真实 gather）host tiling 零声明、靠单批 ~4KB < 默认窗口碰巧通过；**P3（阶段B）SingleOperatorLaunch 不暴露 `simt_share_memory_size`，isolated VF 测试无法放大 SIMT 窗口（默认恒 8KB）** | **API/头文件/主线仓三源证据 + 引导落地 + 路径1工具缺口闭合（2026-09-02）**：CANN 9.1 头文件 `SetLocalMemorySize` deprecated wrapper ≡ `SetDynUBufSize`（语义"SIMT Dynamic Unified Buffer，默认 0"）；主线仓 ops-nn arch35 **92 处 SIMT tiling 全量调用**（gather_v2 仅 SIMT 模式、DCache=128K）。**决策（用户拍板）**：不做 path2 GE 真机实证；生成代码写当前接口 `SetDynUBufSize`。**改动**：①simt skill 规范源 `workspace-contract §3` 升级 + SKILL/4 篇 ref 新名与废弃桥接 + tiling §0.5 SIMT host 契约 + regbase B2 自检行 7（纯 md）；②路径1工具闭合：`SingleOperatorLaunch/source_module.py` 加 `_make_launch_args` seam + 三个公开入口可选 `simt_share_memory_size` 透传（默认 None/0→8KB 不变），新增 `tests/test_launch_args.py`（8 用例），**真机 smoke**（Ascend950DT）：默认窗 8KB 部分正确/VEC_ERROR，显式 65536 → **64KB 全窗口 PASS**。UT：SOL 71 passed + skill_config 11 passed，0 回归。L1/L3/L4 见 `simt-host-dynubuf-guidance/`；P3 原始工具缺口记录于 `simt-ub-window-misconception` 语境，承接其"生成代码/单测如何配置窗口"一问 |
