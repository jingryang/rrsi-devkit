# L3 方案分析：precision_debug 整体设计原则符合性修复方向

> 对应 L1 [01-problems.md](01-problems.md)（P1-P8）。状态：调研中演进，拍板后冻结。

## 0. 排查结论一句话

precision_debug 的 8 个问题可归为**三类根因**：
1. **信任方向偏斜**（P1/P2/P6/P7/P8）：确定性/半确定性信号（build 结果、用例统计、路由决策、精度数字）委托给 LLM 申报，框架信任 LLM 的自我报告，LLM 不可靠就污染下游。
2. **过度复杂**（P3/P4）：transition 巨大 + 多计数器互锁，难维护难诊断。
3. **重复与缺口**（P5）：A3/A5 双实现重复，且 A5 缺 teardown/entry-commit/schema。

核心问题在**信任方向**——这是 R3 的实际根因，也是用户质疑的"确定性框架做、不确定 agent 做"原则的违背处。

## 1. 核心原则回顾（CLAUDE.md）

- **§1.2 四把尺子**：可维护/可扩展/可诊断/架构合理。
- **§1.3 加载期校验优于运行期暴露**：agent 产物的值域应在读取时校验，不静默默认。
- **§1.10 判据用业务语义，不用机制特征代理**：横切控制流判据应显式声明。
- **§1.14 最小结构优先**：删"控模型"的结构，留"帮模型"与骨架。
- **§1.15 统一抽象**：跨阶段重复行为收敛单点。
- **确定性框架做、不确定 agent 做**（用户核心诉求，贯穿 §1.2/§1.10）。

## 2. 三个根因的修复方向

### 根因 1：信任方向偏斜（P1/P2/P6/P7/P8）——核心

**现状**：deploy_health（build/run 结果）、total_count/failure_type/blocking（用例统计/分类/暴露）、route_to（路由）、is_vf_issue（路由）、best_snapshot（精度数字）全部由 agent 申报，框架信任。

**正确方向**：**框架从确定性源直接计算，agent 只申报"LLM 独有的判断"**。

| 信号 | 现状（agent 申报） | 正确（框架自算/派生） |
|---|---|---|
| deploy_health | agent 填 build_ok/output_ok | 框架从自己调用的 redeploy 返回码 + result.json 有无算 |
| total_count / failed_count | agent 填 | 框架从 run-cases 输出读（框架自有 CLI） |
| failure_type | agent 分类 | 框架从 build 返回码 + result.json 归（compilation/runtime） |
| blocking | agent 判定 | 框架从 failure 模式派生（或 scope_guard AI 判定） |
| cascade_suspected | agent 算（>80%） | 框架从 failed_case_queue 算术算 |
| route_to | agent 自评 | 框架从候选池状态/失败类型派生，或校验值域后信任 |
| is_vf_issue | agent 自评 | 框架从 DumpTensor 结构信号派生，或校验值域 |
| best_snapshot | skill 写、框架核对 | 框架直接读 result JSON 算 |

**保留 agent 的（LLM 独有判断）**：
- `root_cause`/`candidate_pool`/`fix_plan`（诊断假设）——LLM 语义判断，合理
- `scope_verdict`（upstream/pass）——语义判断，但**需值域校验**（现状已做，好）
- `observed_issues`（问题观察）——分类 + 证据，LLM 合理，但 `blocking` 应框架派生

**关键判据**：一个信号若框架能确定性观测/计算 → 框架做；只有 LLM 语义理解才 agent 做。这是 §1.10/§1.2 的直接落点。

### 根因 2：过度复杂（P3/P4）

**现状**：diagnose transition 190 行，五计数器互锁。

**方向**：
- transition 拆分：读 agent 产物 / 写 control.json / 路由决策 / 历史物化 分开（单一职责）。
- 计数器收敛：用"单一 rounds + 语义止损信号"，替代 corrective_cycles/refine_cycles/diagnose_stalls/attempt_count 互锁。保留必要的（case 级 attempt stop-loss），删可派生的（stall 可从"本轮 vs 上轮无进展"派生）。

### 根因 3：重复与缺口（P5）

**方向**：A3/A5 共用基类 + 抽公共 helper（`_operator_dir`/`_sync_debug_result`/`_common_context`/transition 模板），删重复；A5 补 teardown rollback / entry-commit / schema 校验（与 A3 对齐）。

## 3. 修复优先级

- **P0（紧急，先修）**：P1（deploy_health）——已实际导致 rms_norm eval 0 分。最小修：框架自算 deploy 健康，或至少 null 不误判。P2（run_tests 申报）——框架从 run-cases 输出算统计。
- **P1（重要）**：P6/P7（路由委托）——值域校验 + 框架派生兜底。P8（精度权威）——框架读 result JSON。
- **P2（渐进）**：P3/P4（复杂度）——transition 拆分 + 计数器收敛。
- **P3（重构）**：P5（A3/A5 合并）——需较大重构，可单独推进。

## 4. 实施注意

- **最小改动 vs 正确改动**（§1.2）：P1/P2 是"框架接管确定性信号"，属正确改动但改动面大（改 transition + skill 契约）。建议**分步**：先 P1（最小修 null 误判 + 框架自算 deploy 健康），验证后逐步 P2→P6/P7。
- **§2.5 唯一通路**：框架接管后删 agent 申报字段（如 deploy_health 从 skill 契约删除），不留双通道。
- **§1.14 最小结构**：修复不增加新 gate，只把已有信号的来源从"agent 申报"改为"框架自算"——结构不增不减，只是来源归位。

## 5. 结论

precision_debug 的 8 个问题根因是**信任方向偏斜**（确定性信号委托 LLM）+ **过度复杂** + **重复缺口**。核心修复是**框架接管确定性信号、agent 只保留语义判断**——这正是用户质疑的"确定性框架做、不确定 agent 做"原则的落地。按 P0→P3 分步实施，先救 rms_norm 类误熔断，再逐步重构。
