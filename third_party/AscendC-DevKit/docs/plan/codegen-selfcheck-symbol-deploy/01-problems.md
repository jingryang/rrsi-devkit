# codegen 自检/产物符号/deploy 门 + 批跑 eval — 问题记录（L1）

> 本文件仅记录**客观事实**（哪里坏了、凭什么这么说），不提方案、不排顺序、不写决策。
> 方案/取舍见同目录后续 L3；实施配方见 L4。产权分层：证据只在此层，步骤/依赖在 L2，
> 决策在 L3。
>
> 来源两次调查（同一会话 2026-08-18/19）：
> 1. **同事 h00939316 的 `__interpolate` 单算子 run**（2026-08-18 21:14 首跑，devkit commit
>    `13287ef4`，`output/20260818-131451-3f9d84/`，bench_lab 数据源）。run 最终
>    HALT in precision_debug（upstream deploy 缺陷）。其 codegen 阶段出现 8 类 WARN，逐条
>    追根因。产物 `libcust_opapi.so` 在本仓 artifacts 有拷贝，可本地 `nm` 验证。
> 2. **本会话批跑 batch `20260818-152906-dde0d9`**（3 算子 exp / adaptive_avg_pool3d /
>    fake_quantize_per_tensor_affine，task_XXXX_ 数据源）。3/3 workflow-done、2/3
>    eval-passed（adaptive 50 / exp 25 / fake 0），eval 侧 perf 全 0 + fake_quantize 评测崩溃。

---

## 一、`__interpolate` codegen 链（P1–P4）

### P1 — codegen agent manifest 契约自检违反（skill 维8 未执行到位）

**算子/上下文**：`__interpolate`，codegen 阶段 round 1（2026-08-18 21:59:59 同一时刻三连 WARN）。

**现象**（run.log 原文）：
- `plugin m.def tensor inputs ['input'] vs manifest inputs [] mismatch (phantom/unmatched input; plugin_only=['input'], manifest_only=[]) — drifts ACLNN_CMD position binding (Q3-aggregate EZ1001 root cause)`
- `codegen: derived callable_target.symbol 'torch.ops.cann_bench.interpolate' from op_plugin TORCH_LIBRARY_FRAGMENT registration (agent omitted it in manifest) — manifest auto-rescued, no halt`
- `codegen manifest non-conforming (missing ['inputs', 'outputs'], retry 1/5); NOT writing deploy_result — runner will re-spawn coder with artifact_feedback.`
- 22:07:14：`git diff found changes the agent didn't report: ['codegen_manifest.json', 'decision_log.json']`

**凭什么说是问题（证据）**：
1. `codegen_manifest.json` 初版 `inputs=[]` 而 plugin `m.def` 声明 `input`，二者不一致；skill
   维8（`.claude/skills/ascendc-op-dev-coding/SKILL.md`）明确要求 manifest 的 inputs/outputs 与
   m.def 逐字一致、`required_keys` 齐全、不含调试字段。
2. `callable_target` 由框架从 TORCH_LIBRARY 派生补全（agent 漏填）。
3. 框架定向重试（retry 1/5）后，**最终** `codegen_manifest.json` 已修正（实测
   `inputs=[{'name':'input'}]`、`callable_target` 已填）——即问题被框架兜住，但按 §2.9
   自检闭环，此应在 producer（codegen agent）自检内闭合，非依赖下游门/重试。
4. **上下文退化机制（实证，round 1 vs round 2）**：
   - round 1：会话 109 turn、累计 ≈98.6 万字符（≈33 万 token）；skill（含维8）在 **turn 2**
     加载（32.5K 字符）；`codegen_manifest.json`/`decision_log.json` 在 **turn 108（会话末）**
     才写 → 初版非契约。
   - round 2（框架「manifest non-conforming」反馈后）：**6-turn 短会话**，manifest 在 **turn 6**
     写 → 契约正确（inputs=[input]、callable_target 已填）。
   - 推断：长会话末尾写契约，早期加载的维8 契约要求被超长上下文稀释——同
     batch-20260810「会话后才查契约」模式。manifest 是框架规定的**最终交付物**，天然在 skill
     流程末尾写，故「末尾写契约」是流程设计使然，非 agent 偶然行为。

**产权**：codegen agent 自检质量（manifest 契约一致性）+ 流程设计（契约写盘位于上下文峰值时刻）。

**已解决（2026-08-20，Part 1 实施落地）**：采用「manifest 收敛」——实测下游只消费
`callable_target` + `op_name`（deploy/smoke/precision/adapt），harness 绑 golden 用 op_spec，
**IO 结构不被下游消费**（三重冗余：冗余于 m.def、op_spec、下游）。故 `_REQUIRED_MANIFEST_KEYS`
收敛为 `(op_name, callable_target)`；inputs/outputs/attrs 降为可选，**不再触发 artifact-retry**，
P1 的 retry 门从源头消除。`_check_plugin_schema_consistency` 改为仅当 manifest 主动声明非空
inputs 时校验（plugin m.def 为运行时绑定唯一权威）。schema / skill 维8 / prompt / feedback hint
同步更新。全量 UT 3616 通过。方案细节见 02-analysis.md。

### P2 — codegen agent 自检缺「实际产物符号验证」

**算子/上下文**：`__interpolate` codegen rounds 1–3（21:31–22:08）。

**现象**：
- decision_log round 3 宣称：`verified the full registration chain end-to-end: func.cmake macro signature matches...; aclnn_interpolate.cpp defines extern "C" aclnnInterpolate/aclnnInterpolateGetWorkspaceSize compiled into libcust_opapi via ALL_API_OPS_SRCS -> npu_op_library(cust_opapi ...)`。
- 但实际 built 产物 `artifacts/per-op/__interpolate/opp/vendors/custom_ops/op_api/lib/libcust_opapi.so` 经 `nm -D` 仅有 `aclnnAdd/aclnnAddGetWorkspaceSize/aclnnSqrt/aclnnSqrtGetWorkspaceSize`（4 符号，来自既有算子），**无 `aclnnInterpolate`**。

**凭什么说是问题（证据）**：
1. coder agent 轨迹（`agents/ascendc-coder-*.jsonl`）共 85 条 bash，其中 build 类 27 条
   （`bash build.sh --soc=ascend910b`、`rm -rf build && bash build.sh`…），**`nm`/`objdump`/
   `readelf`/`-D` 类 = 0 条** —— agent 从不对 built 产物做符号存在性验证。
2. round 3 的「verified end-to-end」是**静态宏链推演**（读 CMake/宏定义推结论），非产物证据；
   与最终产物缺符号矛盾。
3. skill 自检清单（维1–维8，`ascendc-op-dev-coding/SKILL.md`）**全部为静态代码级检查**，无
   一条要求「构建后验证产物含预期 aclnn 符号」。维7 注释「codegen 有编译器 in-session 兜底」，
   但 agent 用 build 日志 grep 冒充编译验证（§1.11 反模式：中间信号代替实际产出）。

**产权**：codegen agent 自检质量 / skill 自检清单缺口。

### P3 — `_` 前缀算子目录被 csrc/ops/CMakeLists.txt GLOB 跳过

**算子/上下文**：`__interpolate`（目录名双下划线前缀），codegen round 2。

**现象**：
- `aclnn_interpolate.cpp` 已生成且符号定义正确（`extern "C" aclnnStatus aclnnInterpolate...`），
  但未编进 `libcust_opapi.so`。
- decision_log round 3 记录了 agent 自诊根因：`__interpolate lacked its own CMakeLists.txt and
  csrc/ops/CMakeLists.txt glob skipped '_'-prefixed dirs`；agent 声称 round 2 已修（新增
  `__interpolate/CMakeLists.txt` 带 `register_aclnn_op(Interpolate,...)+register_aclnn_plugin`；
  ops/CMakeLists.txt glob 改只排除 `op_kernel/_common`）。

**凭什么说是问题（证据）**：
1. 最终 `libcust_opapi.so`（nm 实测）仍缺 `aclnnInterpolate` —— agent 的修复声明与最终产物
   不符（修复未生效，或框架 deploy 构建未使用 agent 改的构建路径）。
2. 后续 smoke 连续失败（22:01/22:04）与 precision_debug 20/20 启动失败均指向同一符号缺失。

**产权**：构建层（CMake GLOB 配置 + 修复声明与产物脱节）。

### P4 — framework deploy 无「符号存在性门」

**算子/上下文**：`__interpolate`，deploy→smoke→precision_debug 时序。

**现象**：符号缺失缺陷直到
`smoke failed (retry 1/1000)`（22:01）→ `retry 2/1000`（22:04）→ `同一错误签名连续 3 次` stop-loss
（22:08）→ precision_debug 20/20 全部启动失败 → scope_guard 判 upstream deploy → HALT（22:11）
才暴露。

**凭什么说是问题（证据）**：
1. deploy 完成时无构建期/加载期 `nm` 断言预期 `aclnn<Op>` 符号；当前代码对 `libcust_opapi`
   仅有 eval LD_LIBRARY_PATH 引用（`src/ascendc_devkit/adapters/evaluation/cannbench_env.py:165`），
   无符号存在性校验。
2. §1.3：配置/产物合法性应在加载期/构建期校验并告警，本缺陷推迟到 smoke 重试 + precision
   阶段才暴露。

**产权**：框架 deploy 校验时机。

---

## 二、批跑 eval 链（P5–P6）

### P5 — 批跑 eval perf 全 0：worktree 缺 910b3 perf baseline

**批次/上下文**：batch `20260818-152906-dde0d9` 三算子 eval（2026-08-19 00:47–02:05）。

**现象**：三算子 `overall` 分别为 adaptive 50.0 / exp 25.0 / fake 0.0，**perf 全为 0**；eval
stderr 每 case 报 `per_case_sol_score: T_cand (X us) 或 T_HW (0.0000 us) 非正，本 case 性能项按
None 处理`。

**凭什么说是问题（证据）**：
1. 三算子 eval stderr 同型：`T_HW=0.0000` → 性能项全 None → perf=0。
2. worktree（全新 cann-bench 检出）报 `BaselineStore: hardware='910b3' 的平台文件不存在
   (tasks/metadata/910b3.json)，将 fallback 到默认平台 '910b2'`；910b2 亦无这些新算子的
   T_HW → 性能 baseline 缺失。

**产权**：评测数据侧（cann-bench `tasks/metadata/` 缺 910b3 perf baseline / 新算子 T_HW）。

### P6 — fake_quantize eval 崩溃（kernel_eval exit 20, stderr 空）

**批次/上下文**：batch `20260818-152906-dde0d9` 的 `fake_quantize_per_tensor_affine`
（exec `20260818-152906-e72f73`）。

**现象**：eval `overall=0.00 compile=0.00 func=0.00 perf=0.00`、`0/20`；`kernel_eval exited 20`；
eval stderr 日志为空（`subprocess/cannbench_eval_fake_quantize_per_tensor_affine.stderr.log`）。

**凭什么说是问题（证据）**：
1. report JSON：`operators: pass_rate=0.0, total_cases=20, passed=0`。
2. stderr 空 + exit 20 → 评测早期（加载/编译期）崩溃，非 case 级精度失败；无 crash_dump 残留。

**产权**：待诊断（评测侧 vs 算子部署侧）。

---

## 三、已解决（追溯）

### P7 — task_XXXX_ 数据源 golden_entry 错位 [已解决 2026-08-18 23:28]

**批次/上下文**：batch `20260818-141301-bbe498`（首跑）3/3 FAIL(exit 65)；本会话已修。

**现象**：脚本按 task 目录 basename 写 `golden_entry`（`task_XXXX_aten_<op>`），而 golden.py
顶层函数为不带前缀的真实算子名（`exp`/`adaptive_avg_pool3d`/`fake_quantize_per_tensor_affine`）
→ harness `getattr(golden_mod, entry)` 找不到 → `golden_entry_missing`（0/20 无用例执行）→
scope_guard 判上游 golden 缺陷 → halt。

**证据**：manifest `golden_entry: task_0001_aten_exp` vs golden.py `def exp(`；harness
`_harness_template.py` `getattr` 缺失即 `golden_entry_missing`。

**解决**：`scripts/batch_self_evolve.sh` 改为从 golden.py 顶层入口函数派生 op（排除 `get_input`，
非恰 1 个则加载期 FAIL §1.3）；重跑 batch `20260818-152906-dde0d9` 3/3 workflow-done。

---

## 四、非问题（记录在案，不修）

- **`[codegen domain-gap] design.support_domain 未覆盖 requirement(golden) 域`（×4）**：
  设计质量问题**信号**，by design 注入 coder prompt（§1.13 golden 权威），非缺陷。
- **`opencode serve :37783 startup failed (attempt 1/3)`**：外部基础设施瞬时超时，有界重试
  后恢复（§1.11 / 外部 infra 非框架职责）。
