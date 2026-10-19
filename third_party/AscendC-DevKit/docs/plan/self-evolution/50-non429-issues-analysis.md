# 50 — 批跑（20260715_194455）非 429 问题根因分析（L3）

> 本文是 `batch-runlog-20260715.md`（L1 运行事实）所记录的**非 429 问题**的根因深挖与归档。
> 性质：L3 方案分析 —— 现象复述 → 根因 → 证据 → 候选方向（不含 L4 具体改哪行）。
> 产出时间：2026-07-16。深挖方式：precision_debug.py / debugger agent 定义 / skill / 三算子 `.precision-fix` artifacts 实证（两个 subagent 并行深挖 + 编排层复核）。
> **重要**：深挖推翻了巡检期（runlog 疑似 9/10）的多处判断，见 §7 误判更正表。

## 0. 问题清单（非 429）

批跑 5 算子终态：manifold ✅ DONE；advance_step_v2 / scatter / aggregate / multi_add 均 halt(65) @ precision_debug。
排除纯 429 软失败（疑似 4/8）后，需深挖的非 429 问题：

| 疑似 | 一句话 | 性质分层 | 优先级 |
|---|---|---|---|
| 10 | precision-debugger 编排器自转数百 turn halt | **DevKit 编排 bug（async/sync 失配）+ stale harness** | 🔴 高 |
| 9 | 3 算子 precision_debug halt | **分层：429饿死 / DevKit工具bug / 真kernel缺陷+600s ceiling** | 🔴 高 |
| 6 | RESUME 自动找目录 `sort\|tail -1` 字典序误选 | 脚本 bug | 🟡 中 |
| 7 | `RESUME=1` 环境泄漏进从头跑分支 | 脚本 bug | 🟡 中 |
| 5 | batch 脚本自造并发 vs 工程 `--batch` 双通路 | 架构债（§2.5，已记于 41-batch-fusion） | 🟢 低（已立项） |
| 3 | context stage output_contract WARN 共性误报 | 契约校验噪音，不阻塞 | 🟢 低 |

---

## 1. 疑似 10：precision-debugger 编排器自转（双根因）

### 1.1 现象（修正：并非"零派发"）

multi_add 两次 resume 都 halt @ precision_debug：编排器自转 246/345 turn、context 膨胀到 251K chars、`incomplete_output: agent 未产出 debug_result.json` → halt。

**巡检期 grep `ascendc-precision-{run_tests,diagnose,fix,printf}` 全 0 → 曾误判"零 phase 派发"。深挖 transcript（`agents/ascendc-precision-debugger-01.jsonl`）证实编排器**实际派发了 7 次**子 agent（4× `ascendc-precision-printf-locate` + 3× `ascendc-precision-fix`）。grep 漏计是因为派发日志格式（`tool:Agent` 行）与巡检 grep 模式不匹配 —— 这是**巡检判据缺陷**（见 §7）。

### 1.2 根因 A（编排层，主因）：SDK async 派发 ↔ prompt 同步语义失配

- precision_debug stage 入口 `precision_debug.py:238-299`（`_actions_legacy`）经 `SpawnAgent(agent_name="ascendc-precision-debugger")` 派发编排器；prompt 由 `_build_prompt()`（`:361-430`）拼装，**只含任务参数 + debug_result.json 文件接力契约**（`:174-181` `DEBUG_RESULT_CONTRACT`，期望 agent 在 op_dir 根写 `debug_result.json`，`transition()` `:488-557` 文件不存在则 halt）。
- 编排器 system prompt（`.claude/agents/ascendc-precision-debugger.md:23-44`）设计的是**同步阻塞** LOOP：`Agent(subagent_type=...) → Sub-agent returns → verify-checkpoint.py → 循环`。
- 但 Claude Code SDK 的 Agent 工具是**异步/后台**派发，回执原文（transcript turn 23/67/188 的 tool_result）：
  > "Async agent launched successfully. ... You will be notified automatically when it completes."
- **失配后果**：dispatch 后编排器按同步语义等"子 agent return"，但 SDK 没有 sleep 原语、每 turn 必须产东西 → 编排器空转 ~30 turn 等通知（transcript turn 24-54 自述"我将等待完成通知"），且**漂移到违规自己做调试**（违反 hard rule 4 `:109` "You NEVER execute debugging work" —— 实测 100 次 Bash 调用里有 17 次 inline python 自检 + 编排器自己跑了 4 次 run-cases + 1 次 redeploy）。
- 7 轮 dispatch × ~30 turn 空转 ≈ 210 turn + 探索/收尾 = 345 turn；每轮空转把 checkpoint + 自写分析堆进 context → 251K → halt。
- `budget 10000/query` = `ClaudeAgentOptions(max_turns=10000)`（`sdk_backend.py:647`），是**单 query 内 turn 预算而非 token 预算**，不防 context 字节膨胀 —— 放大器，非触发器。

### 1.3 根因 B（数据层，触发器）：stale harness 致不可修 TypeError

- 为什么独 multi_add 触发长空转（对照组 advance/scatter/aggregate 不触发）？**不是 dispatch 行为差异**，而是 multi_add 的精度失败恰好**修不掉**。
- `output/20260715-114508-d318a1/artifacts/debug/multi_add_*/iter-{1..6,99}/result.json` 全部 20 case 同一报错：
  > `TypeError("int() argument must be a string ... not 'list'")`
- 源头：multi_add 的 **TensorList 嵌套 shape**（`input_shapes: [[[152,7680]], [152,7680], [7680], ...]`）。
- 该 bug 已由 commit **`734557f` "fix(harness): TensorList nested-shape + numeric attr coercion for cann-bench cases"**（2026-07-16 05:47:52）修复并入 DevKit。
- 但磁盘上 multi_add 的 `iter-1/harness.py` 时间戳 **05:30:05（pre-fix）** —— 批跑前半段用的 DevKit 还没有 734557f，生成的 harness 带 bug；后续 resume（07:28）虽用已修复 DevKit，但**未 redeploy 刷新 iter-1 harness**，stale harness 仍在 → 无论 fix/printf 怎么折腾，每次重测仍是同一 TypeError → 状态机在 `printf_location ↔ fix` 反复横跳、永不收敛 → 耗尽 budget。
- 对照组：advance/scatter/aggregate 的失败要么真精度（fix 一两轮过）、要么早 halt，不进入长时间空转 → context 不爆。

### 1.4 候选修复方向（均不碰算子核心代码）

| 方向 | 内容 | 落点 | 预估 | 治本? |
|---|---|---|---|---|
| **A（治本，推荐）** | Agent dispatch 改同步阻塞：A1 调研 `ClaudeAgentOptions` 是否有 foreground 开关并在 `sdk_backend.py:634-653` 打开；A2 若无，把 phase 子 agent 逻辑下沉为 stage 内部子 action（DevKit kernel 顺序 spawn，不让 LLM 自派发） | `sdk_backend.py` / `precision_debug.py` / `ascendc-precision-debugger.md` | A1≈1-3 行；A2≈200-400 行 | ✅ |
| **B（治标+防漂移）** | 编排器 prompt 显式承认 async 语义：dispatch 后下一 turn 必须是单行 wait/no-op、禁止 dispatch 未完成期间做任何 Bash/Read on 算子源（强化 hard rule 4） | `ascendc-precision-debugger.md:23-33,97-134` + `_build_prompt()` | ≈50 行 prompt | ⚠️ 半 |
| **C（防 context 爆，独立收益）** | `sdk_backend.py` query 循环加 context-size watchdog（>100K 且有未完成 task → 强制单行 await turn）；LOOP 每 verify 后写 partial `debug_result.json`（best_commit/max_diff/failing_cases），halt 时 transition 读到非空结果而非 incomplete | `sdk_backend.py` + LOOP | ≈80-150 行 | ⚠️ 兜底 |
| **D（数据层，独立）** | multi_add stale harness 重生：跑一次 `ascendc-devkit redeploy` 刷新 iter-1 harness（用已修复 DevKit）即可验证精度真实状态 | 数据，非代码 | 分钟级 | ✅ 针对 B |

**建议**：A+B 组合（A 治本承担主修复、B 防漂移兜底），C 作为健壮性增强；D 立即可做（验证 multi_add 精度是否本就 OK）。

---

## 2. 疑似 9：3 算子 precision_debug halt（分层，无一是"精度长期不收敛"）

> 深挖结论：**3 个算子没有一个跑出真实的"精度长期不收敛"**。失败模式高度异质，分属外部阻断 / DevKit 工具 bug / 真 kernel 缺陷三层。巡检期（runlog 疑似 9）把它们一概归为"真精度硬失败"是过度概括（见 §7）。
> 注：`.precision-fix/` artifacts 实际在 cann-bench worktree `<op_dir>/.precision-fix/`，run 顶层 `report.json/report.md` 是 stub。

### 2.1 advance_step_v2（1956bf）—— 429 饿死，零精度数据

- `checkpoint.json`：`history=[]`、`candidate_pool=null`、`best_max_err=null`。codegen 成功（5 文件）、build OK，但 precision_debug **未执行一次 run-cases**。
- run.log：session 23:30:36 启动，23:37:14（398s 后）`Agent ascendc-precision-debugger query attempt 1 failed: API Error: Request rejected (429) · Weekly/Monthly Limit Exhausted` → `[partial]` → halt。
- **根因**：429 月配额耗尽，**与算子精度无关**。真实精度状态**未被验证**（巡检期 grep 到的"33 硬信号"是把 `query attempt 1 failed` 等 429 行误计，见 §7）。

### 2.2 scatter_pa_kv_cache（563d1f）—— DevKit 工具 bug，debugger 正确拒绝 patch

- run_tests iter 1 在到 NPU 之前 Python 层崩溃，`failed_count=0/total_count=0`，`final_status="blocked"`。
- debugger 诊断定位到**具体文件行**：`src/ascendc_devkit/adapters/npu/task_loader.py:180` `value_range = {"low": float(vr[0]), "high": float(vr[1])}` —— 该算子 cases.yaml 提供 **per-input** value_range（`[[-100,100],[-100,100],[-1,135],...]`，输入 2 是 int32 索引），加载器假定扁平 `[low,high]`，对嵌套列表执行 `float([-100,100])` → TypeError。
- **关键**：DevKit 自己有正确实现 `domain/cann_bench_cases_loader.py::_per_input_value_range`，但 run-cases 路径仍用旧 task_loader（双通路残留，与 §2.5 同源）。
- debugger 做出**正确工程判断——不修**：扁平化会把 `[-100,100]` 广播给 int32 索引输入 → 非法负索引 → 精度结果无意义；真修复要贯穿 task_loader + TaskCase schema + precision_debug.py:150-160 + runner.py:400-421 + 数据生成器（共享工具工程，超算子调试范围）。
- **根因**：DevKit 测试框架 bug（per-input value_range 不支持，与 734557f 同类的 cases 加载缺陷）。算子本身是纯 ND→FRACTAL_NZ 数据搬运（kernel 头注释"Bit-exact data movement, no arithmetic"），预期精度 0，但**未被验证**。

### 2.3 ai_infra_aggregate_hidden_grad（e1f3f6）—— 唯一真跑，多层级 + 真 kernel 缺陷，被 600s ceiling 杀

`report.json` 完整，唯一真定位到根因并做 fix 的算子。iter 1（20 case 全集）：15/20 失败且 `max_err=999.0`（runtime error 哨兵），5/20 通过（全 fp16+hasMask，diff=0 位精确）。

诊断定位 2 个 arch gap（Gate A2 runtime）：
- **GAP-A（11 cases, blocking）**：`op_plugin/..._plugin.cpp:53-54` torch schema 写 `Tensor? mask)` **缺 `=None`**，3 参 noMask 调用被 torch dispatcher 在到 C++ impl 前拒绝；而 proto.yaml + golden.py 都写了 `mask=None`。
- **GAP-B（4 direct + 8 latent, blocking）**：bf16（dtype id 27）未注册进 DTYPE_SUPPORT（`op_api/aclnn_*.cpp:34-36` + `tiling_key.h` 只 route C_DT_FLOAT16）；`decision_log D4` 明确写了"bf16 shapes will not match a tiling key; acceptable for current smoke" —— **详设主动延后了 proto 声明的 dtype，但未留回归守护**。

修复（1 轮 correction，FP-1）：plugin.cpp `Tensor? mask)` → `Tensor? mask=None)`（commit `07f780c`），build+smoke 通过。验证 case 2（fp16 noMask）`grad_input` 位精确（diff=0），但暴露**新根因 GAP-C**：`grad_weight` diff=79.53125、1152/1728 元素完全发散（非 fp16 漂移，是数值完全不同）→ noMask 路径 grad_weight reduction/correctness 缺陷（kernel `op_kernel/..._hidden_grad.h` 第 28/30/267 行 add-fold；hasMask 对、noMask 错）。

**未收敛原因（非 budget、非 429）**：commit 后 23 秒被 **Claude Code harness 的 600s 后台任务等待 ceiling** 杀掉：
```
[04:33:58] turn 296 tool:Bash
Background tasks still running after 600s; terminating.
  Set CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 to wait indefinitely.
```
orchestrator 派发子 agent 走 background + 等通知，单次 BG wait 超 600s 整 session 被终止 —— 与疑似 10 的 async 问题**同源**（编排架构与 Claude Code CLI BG-wait 上限不兼容）。

### 2.4 共性总结

**非同一类问题，而是清晰的"问题层级"**：

| 层 | 涉及算子 | 性质 | 是否算子精度问题 |
|---|---|---|---|
| L1 外部阻断 | advance（429）、aggregate（600s ceiling） | API 配额 / 编排架构 | 否 |
| L2 DevKit 工具 bug | scatter（task_loader）、aggregate（state_snapshot 丢字段→redeploy 阻塞） | DevKit 自身债务 | 否 |
| L3 生成代码缺陷 | aggregate（GAP-A schema 漏 token、GAP-B dtype 延后、GAP-C 真 reduction bug） | codegen/设计/kernel | **是（仅 aggregate 有证据）** |

**系统性薄弱点（样本 n=1 真跑通，证据有限）**：
1. **proto 契约 → codegen 的"零 token 漏写"**（GAP-A）：proto 写 `mask=None`、codegen 没复刻 `=None`。可改进 —— codegen plugin 模板对 optional Tensor 应强制从 proto 推导 default。
2. **"延迟实现"债务**（GAP-B）：smoke 阶段允许延后 dtype，但应在 op_def/DTYPE_SUPPORT 加显式 TODO + 阻止带该 dtype 的 case 入测试集（否则就是 EZ1001）。
3. **多输出算子"一路对一路错"**（GAP-C）：grad_input 位精确 + grad_weight 全错，reduction 在 noMask 分支错 —— LLM 生成易错区，需 printf 定位 + case simplifier。

---

## 3. 疑似 6：RESUME 自动找目录 `sort | tail -1` 字典序误选

- `scripts/batch_self_evolve.sh:117`：`WORKTREE_ROOT="$(ls -d "$DEVKIT/../cann-bench-batch"/*/ 2>/dev/null | sort | tail -1)"`。
- `cann-bench-batch/` 下目录名前缀混用 `2026*`（数字 `2`, ASCII 0x32）与 `sixops_*`（字母 `s`, 0x73）；字典序 `s`>`2` → `sort|tail -1` 恒取 `sixops_*` 而非时间戳最新的 `2026*`。
- 影响：`RESUME=1` 不显式指定 `WORKTREE_ROOT` 时误选旧目录、在旧目录瞎建 worktree、读不到当前批 `.runid/.status` → 续跑失效 + 污染旧目录（本次已触发，误跑 sixops）。
- 候选方向（脚本正确性修复，非架构）：L117 改按 mtime 取最新 `ls -dt .../*/ | head -1`，或按时间戳目录名 `2026*` 数值排序。本次用显式 `WORKTREE_ROOT=.../20260715_194455` 绕过。

## 4. 疑似 7：`RESUME=1` 环境泄漏进从头跑分支

- `scripts/batch_self_evolve.sh:286` 从头跑分支 `bash "$E2E"` **未 `unset RESUME`**；`RESUME=1` 作前缀赋值导出到环境、被子进程继承 → 子 e2e 把字面量 `"1"` 当 run_id 去 resume → 读不存在的 `output/1` → exit 1。
- 触发条件：`RESUME=1` 且某算子无 `.runid`（首次失败前未落 run_id，如 no_proto/worktree_add 失败）→ 走从头跑分支 → 泄漏触发。正常续跑（算子都有 `.runid`）不触发。
- 候选方向：从头跑分支前 `unset RESUME`（或 `env -u RESUME bash "$E2E"`）切断环境继承。

## 5. 疑似 5：batch 脚本双通路（架构债，已立项）

- `batch_self_evolve.sh` 自造并发/FIFO 卡池/fork 单算子，与工程 `ascendc-devkit run --batch`（`batch_runner.py`，L2）的 `ThreadPoolExecutor` + 共享 `NPUSlotManager` 卡池**并存**——§2.5 双通路债务。
- **非新问题**：`41-batch-fusion-analysis.md` §开篇即明"批跑能力当前由外部 batch_self_evolve 承担……深层诉求是融合进 Python CLI"；`42-batch-fusion-impl.md` 为其 L4。本次疑似 5 是该架构债的**运行期再确认**（多进程 fork 退化为 shell FIFO 静态钉卡、丧失动态复用）。
- 处置（用户 2026-07-15 已定）：若当前脚本能达既定目标则先不动架构；与疑似 3/6/7 后续一并解决。本文仅引用、不重复展开。

## 6. 疑似 3：context stage output_contract WARN 共性误报

- `stages/context.py:54-62` `output_contract.provides=[profile,adapter,op_identity,reference_code]`，由确定性 action 串（LoadProfile/InitAdapter/收集 reference）产出，非 LLM stage，`max_iterations=1`。
- 5 算子**全部**报 `Stage 'context' reached max iterations (1) without satisfying output_contract`，但**全部越过**（manifold 甚至端到端成功）。
- 根因：output_contract satisfaction 判定与确定性 action 的实际产出/标记不一致 → **误报 WARN 噪音**（profile/adapter 实际已 init，后续 stage 正常使用）。不阻塞流程。
- 候选方向（低优先）：核对 context.py 的 contract provides 列表与 action 实际标记 satisfied 的字段是否一致；若 action 确实产出但未标记，补标记；若 contract 列了 action 不产出的字段，收窄 contract。属可观测性清理，非功能 bug。

---

## 7. 巡检期误判诚实更正表

> 巡检期（runlog 疑似 8/9/10）基于 grep 计数判根因，深挖实证推翻多处。本表是"判断演进"的事实记录，详见各节。

| 巡检期判断（runlog 原文） | 深挖真相 | 出处 |
|---|---|---|
| 疑似 10："precision-debugger 零 phase 派发" | **误判**：实际派发 7 次（4 printf + 3 fix）；grep 模式漏计 `tool:Agent` 行 | §1.1 |
| 疑似 10："429 饿死"（第六轮曾误归） | **误判**：07:28 续跑窗口 429=0；真根因是 async/sync 失配 + stale harness | §1.2/1.3 |
| 疑似 9：advance_step_v2 "真精度硬失败，33 硬信号，有 artifacts" | **误判**：`checkpoint.history=[]` 零精度数据，是 429 饿死（398s 即挂）；"33 硬信号"是把 429 行误计 | §2.1 |
| 疑似 9：scatter "真精度硬失败，34 硬信号" | **误判**：是 DevKit `task_loader.py:180` per-input value_range bug，debugger 正确拒绝 patch；零算子精度数据 | §2.2 |
| 疑似 9：aggregate "真精度 bug（report.json + redeploy_workaround）" | **部分对**：确有真 kernel 缺陷 GAP-C，但叠加 GAP-A/B + 被 600s BG-wait ceiling 杀（非 budget/429）；redeploy_workaround 是绕 state_snapshot 丢字段 | §2.3 |
| 巡检判据"硬信号计数 + artifacts 有无 → 真精度 vs 429 饿死" | **不可靠**：scatter 有 artifacts 却是 DevKit bug、advance 标硬信号却实为 429。判据应改为查 `checkpoint.json.history` 是否空 + 子 agent 派发 transcript + 真实 max_err | §2/§7 |

---

## 8. 关键连带发现：commit 734557f 与 stale artifacts

- commit **`734557f` "fix(harness): TensorList nested-shape + numeric attr coercion for cann-bench cases"** 在批跑进行中（2026-07-16 05:47:52）才入 DevKit。
- 批跑前半段（19:21 起）用的 DevKit **没有此 fix** → multi_add 的 `iter-1/harness.py`（05:30:05 生成，pre-fix）带 TensorList 嵌套 shape bug；scatter 的 `task_loader.py:180` per-input value_range 是**另一处未被 734557f 完全覆盖**的同类 cases 加载缺陷（待确认 734557f 是否覆盖 task_loader 路径，或 task_loader 仍走旧通路 —— 与疑似 5 双通路同源）。
- **结论**：**multi_add 与 scatter 的"精度失败"本质是用了 pre-fix 的 stale 测试框架产物，算子精度从未被真实验证**。重新生成 harness（redeploy，用当前已修复 DevKit）很可能让这两个算子真正跑通精度测试 —— **无需人工精度调试**。
- aggregate 是唯一确证有真生成代码缺陷（GAP-A/B/C）的算子，但其失败也被 600s ceiling 提前截断，GAP-C（真 reduction bug）尚未修复验证。

## 9. 优先级与处置（2026-07-16 用户拍板）

> 拍板记录：用户确认 P0 根因 A 采用 **CompositeGroup + 子 stage 模式**（对标 design 阶段），
> 否决了 L3 原建议的方向 A1/A2（SDK foreground 开关 / DevKit kernel 内自派发），
> 理由：Stage 是阶段节点，框架本身才是编排器。详见 L4 `51-precision-debugger-async-fix-impl.md`。
> stage-transition.py：选项 B（删除，逻辑内联到各子 stage resolve_condition）。
> checkpoint.json 路由字段：State 字段 `_debug_checkpoint`，对标 `state.anchor_report`。

| 优先级 | 项 | 决策 | 是否动算子核心代码 | L4 |
|---|---|---|---|---|
| 🔴 P0 | **疑似 10 根因 A**（async/sync 失配 + 600s ceiling） | ✅ **已拍板**：CompositeGroup + 子 stage 替换 LLM 编排器，对标 design 阶段模式 | 否（编排层） | `51-precision-debugger-async-fix-impl.md` |
| 🔴 P0 | **stale harness 重生验证**（multi_add/scatter） | 操作步骤：redeploy 刷新 iter-1 harness，验证精度真实状态 | 否（数据重生） | 见 L4 §数据重生 |
| 🟡 P2 | 疑似 5+6+7 脚本收口（双通路 + 两 bug） | ✅ **已拍板**：瘦身为 manifest 生成器，调 `ascendc-devkit run --batch`。疑似 6/7 随旧逻辑一并删除（§2.5 收口）。**不阻塞 P0**，先落 L4 方案。 | 否（脚本） | `52-batch-script-refactor-impl.md` |
| 🟡 P2 | scatter 的 task_loader per-input value_range | 待拍板：接 `_per_input_value_range` 到 run-cases 路径 | 否（DevKit 工具） | 待建 |
| 🟡 P3 | aggregate GAP-A/B/C 真缺陷 | 待拍板：GAP-A/B codegen 改进 / GAP-C kernel reduction bug | **GAP-C 是**（须用户 OK） | 待建 |
| 🟢 P4 | 疑似 3 context WARN | 低优先，待排期 | 否 | 待建 |

**P0 已封板**：CompositeGroup 方案一次修复惠及所有 precision_debug halt（async/sync 失配 + context 膨胀 + 600s ceiling 三合一）。

## 关键路径索引

- L1 运行事实：`docs/plan/self-evolution/batch-runlog-20260715.md`（疑似 3-10 + 巡检演进 + §7 误判更正指针）
- precision_debug 编排：`src/ascendc_devkit/orchestration/stages/precision_debug.py`、`.claude/agents/ascendc-precision-debugger.md`、`src/ascendc_devkit/capabilities/agent/sdk_backend.py`
- DevKit 工具 bug 位点：`src/ascendc_devkit/adapters/npu/task_loader.py:180`、`domain/cann_bench_cases_loader.py::_per_input_value_range`（正确实现未接通）
- stale harness 证据：`output/20260715-114508-d318a1/artifacts/debug/multi_add_*/iter-*/harness.py`（05:30:05，pre-fix 734557f@05:47:52）
- aggregate 真缺陷：`cann-bench-batch/20260715_194455/ai_infra_aggregate_hidden_grad/.../.precision-fix/{report.json,checkpoint.json,redeploy_workaround.py}`、FP-1 commit `07f780c`、GAP-C 位点 `op_kernel/ai_infra_aggregate_hidden_grad.h:28,30,267`
- 相关 L3/L4：`41-batch-fusion-analysis.md`（疑似 5）、`46-precision-debug-artifacts-relay-*`、`39-soft-stage-timeout-*`（与 600s ceiling 相关）
