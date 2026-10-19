# step-84 — codegen↔precision_debug 职责边界重划：codegen 只保框架、device 级 runtime 崩溃下沉 precision — 方案分析（L3）

> 性质：**L3 方案分析**（选项 + 取舍 + 推荐，待用户拍板后冻结）。self-evolution 线，step 84。
> 上游 L1：`84-batch-205112-issues-summary.md` Q2（manifold runtime OOB）、Q3（aggregate runtime OOB）、Q1（scatter 缺 InferShape，作边界反例）。
> 触发：用户主张「让 codegen 去 debug 不合适——codegen 只保证算子框架没问题即可，算子问题（含崩溃）都应让 precision debug 解决」。
> 纪律：§1.8——事实产权在 L1，本文只记根因（L3 产权）+ 选项决策；代码改动配方留 L4。

---

## 0. 一句话

codegen 当前契约要求**真机 smoke 执行通过**（device 级 runtime 正确），把"编译过、首次上板崩"（Q2/Q3 的 507035 GM/scalar OOB）判为 codegen 失败并 halt；但 `precision_debug` 的 scope_guard 决策表**已把同一类 runtime 崩溃归为 `pass`（precision 自己该调的）**——两 stage 契约互相矛盾，且 codegen 用错层的工具（coder in-session loop，无 printf/DumpTensor/bounds-check）去 runtime 调试，耗尽预算 halt。修复方向：把 codegen 契约收敛到**框架级**（编译/链接/注册/tiling-key 派发/InferShape/schema），device 级 runtime 崩溃**下沉 precision_debug**（它有对的工具 + 独立预算），边界权威**复用 scope_guard 已有的 upstream/pass 表**，不另立第二套。

---

## 1. 事实（L1 产权，本文只引用 + 补代码 map）

### 1.1 现象（Q2/Q3，L1 已录）
manifold（`d7237a`）、aggregate（`e66710`）均**编译/打包/安装全过**，首次 NPU smoke launch 崩：`error code 507035 / aivec error / GM address exceeds 48 bits + MTE not aligned`（manifold）、`fftsplus aivector error / scalar internal buffer OOB / retCode=0x31`（aggregate）。`last_deploy.json: smoke_passed=false`。coder 在 in-session loop 里试图自修 runtime 崩溃，耗尽预算，`transition` 读 `smoke_passed=False` → `deploy_failed` → halt。

### 1.2 代码 map（本文首次落入，L4 实施锚点）
- **codegen 契约**：`orchestration/stages/codegen.py:86-91` `output_contract().provides=["generated_sources","codegen_iterations","build_result","deploy_result"]`——`build_result`/`deploy_result` 是硬 `provides`，runner `has_all(provides)` 不满足不算 done。
- **codegen `fail_strategy="halt"`**：`codegen.py:71`（base 默认 `"continue"`，`base.py:55`）。机制：`runner.py:509-514` 设 `_stage_failed` → `graph_executor.py:387-414` `is_terminal=True`+`halt_reason` → pipeline `break`。**codegen 失败=硬停，无 loopback。**
- **smoke 是真机单用例执行**（非编译/链接检查）：agent 在 in-session 跑 `ascendc-devkit redeploy` → `adapters/npu/deploy.py:80-166 Deployer.deploy()`；`_run_smoke`（deploy.py:523-603）经 `_build_smoke_harness`（deploy.py:406-490，复用 `NPURunner._build_test_harness`）**真机 `fn()` on real NPU tensor**（`state.test_cases[0]` 或合成 `[1024]fp16`）。判定（deploy.py:585-602）：`returncode==0` AND `case_details[0].error` 空。**507035 崩 → `case_details[0].error` 非空 → `smoke_passed=False`。**
- **agent 拥有 build/smoke loop**（非框架）：prompt `codegen.py:1085-1091`「False → 读 stderr 自修 → git commit → 再 redeploy，直到 smoke 通过或达 {max_rounds} 轮」；`max_rounds` `default_max_iterations=40`（codegen.py:70）= 日志"max iterations (40)"。transition 读 `last_deploy.json`：无文件→`no_last_deploy`；`not smoke_passed`→`deploy_failed`（codegen.py:1349-1367）→ halt。
- **关键反例**：**Regbase(A5) 路径已宽容**——`_transition_regbase_s5`（codegen.py:1675-1680）若 s5 agent 没写 `last_deploy.json` 则**合成 `DeployResult(smoke_passed=True)`，把真 smoke 推迟到 precision_debug**。即用户主张的模式 **A5 已在做，A3(Membase) 未对齐**。
- **scope_guard 决策表已画好边界**（`.claude/skills/ascendc-precision-scope-guard/SKILL.md:34-42`，routed `precision_debug_substages.py:1733-1736`）：
  - **`upstream`（halt，归 codegen/deploy）**：compilation failure / op_plugin schema mismatch / registration-not-found（SKILL.md:36-39）。
  - **`pass`（in-scope，precision 自己调）**：**runtime crash（kernel 跑起来后崩：越界/对齐/同步 = OOB/alignment/sync）→ `pass`**（SKILL.md:40）；all-0/NaN/Inf、精度 diff → `pass`（SKILL.md:41-42）。
  - **∴ 507035 GM/scalar OOB 按 scope_guard 表 = `pass` = precision_debug 的活。**
- **precision_debug 不结构性依赖 codegen 的 smoke**：它自己 redeploy + run-cases（`precision_debug_substages.py:1228-1229`、`converge_best_commit` 899-948）。但 **codegen halt 门让控制流永远到不了 precision_debug**——图序 `codegen → precision_debug`（`workflow.py:646-647`），codegen `fail_strategy=halt` 在 codegen 处 `break`，TRANSITION_TABLE **无 codegen 条目**（workflow.py:676-677）。

---

## 2. 核心矛盾（根因，L3 产权）

**两 stage 的契约互不对齐，且中间那类失败被错层处理：**

1. **边界其实已定义**：scope_guard 表把"编译/schema/注册"归 `upstream`（codegen 的活）、把"runtime 崩溃/精度"归 `pass`（precision 的活）。这是系统里**已存在的、唯一的**职责分界线。
2. **codegen 的 smoke 门无视这条线**：它对 `smoke_passed=False` 一律判失败 halt——不区分失败落在 `upstream` 类（真该 codegen 修）还是 `pass` 类（该 precision 修）。于是 `pass` 类（Q2/Q3 的 device runtime OOB）被 codegen 门拦下，永远到不了唯一接受它的 precision。
3. **错层工具**：被拦在 codegen 后，coder 用 in-session loop（Bash + 读 stderr + 改码）试图 runtime 调试。但 runtime OOB 需要的是 printf 二分/DumpTensor/bounds-check/comment-bisect——**这些是 precision_debug 的 phase 工具，coder 没有**。coder 只能靠猜，耗尽 40 轮预算 halt。
4. **A3/A5 不一致**：A5 已把真 smoke 推迟给 precision（codegen.py:1675-1680），A3 仍卡真机 smoke pass。同一职责两条通路两种契约（违反 §2.5 唯一通路）。

**∴ 根因 = codegen 契约越界要求 device 级 runtime 正确性**（本属 precision 职责），而非框架级正确性；表现为 codegen smoke 门与 scope_guard 表这两个"边界定义"互相打架，中间类（compile-ok/runtime-crash）被错误地留在 codegen 用错工具死磕。这是**职责分层问题**（§2.9 各阶段守本职），非控制流 bug。

---

## 3. 选项（四把尺子）

**边界问题**：codegen 的 `smoke`/`deploy_result` 门应要求"真机执行通过（runtime 正确）"，还是只要求"框架可加载/可启动（launchable）"？

### 选项 A：维持现状（codegen 卡真 smoke pass）
- 否决（用户前提 + §2.9）。codegen 越界做 runtime 调试、用错工具、A3/A5 不一致。**不展开。**

### 选项 B1：codegen smoke **重分类**——device runtime 崩溃判为"框架 OK / runtime 待定"，非 codegen 失败（**推荐**）
- codegen 仍跑 smoke（保留"是否 launchable"信号），但**判定改用 scope_guard 的 upstream/pass 分类**：
  - 失败落 `upstream` 类（编译/链接/注册缺失/tiling-key 派发/InferShape 缺失致 EZ1008 tiling failed/schema mismatch/`cannot find bin`）→ **仍是 codegen 失败 halt**（框架没搭对，本就 codegen 的活——**Q1 scatter 缺 InferShape 正落此类，仍归 codegen**）。
  - 失败落 `pass` 类（kernel 已 launch、device 侧 507035/OOB/对齐/同步崩）→ **非 codegen 失败**；记 `deploy_result.framework_ok=True, runtime_ok=False, runtime_error=<507035…>`，控制流放行到 precision_debug（它 redeploy+run-cases 首次真跑，scope_guard 判 `pass` 接手调）。
- **四把尺子**：
  - **可维护**：不新造边界——**复用 scope_guard 已有的 upstream/pass 表作单一权威**，codegen smoke 判定与 scope_guard 用同一分类器（澄清既有不变式：两处边界定义必须一致，消除 §2 矛盾）。
  - **可扩展**：任何"编译过、runtime 崩"的新算子自动流向 precision，不再每个都 halt；新 runtime 错误码在单一分类器加。
  - **可诊断**：崩溃不被吞——codegen 记 `runtime_deferred`+错误码留信号，precision 带完整上下文接手（§1.3 不静默推迟到更难定位处）。
  - **架构合理**：职责归位——框架缺陷@codegen、kernel 执行缺陷@precision（唯一有 printf/DumpTensor/bounds-check/comment-bisect 的 stage）；**A3 对齐 A5 已有做法**，收敛到唯一通路（§2.5）。
- **代价/风险**：① 需一个"框架 vs device-runtime"错误分类器（判定 hook 在 deploy.py:585-602 `case_details[0].error`）——但分类逻辑 scope_guard 已有（SKILL.md 表）+ 疑似 `27-infra-error-classification-impl.md` 已有基建，L4 复用不新造。② **是否只是把 halt 挪到 precision？**——见 §4 论证：不是，precision 有对的工具 + 独立预算。

### 选项 B2：codegen **移除** device-execution smoke，只保 build+install+launchability 探针；precision run_tests 作首次真跑
- codegen 契约降为 `build_result`（编译/打包/安装）+ 一个**框架探针**（aclnn 能 resolve op + tiling-key 派发存在 + 注册成功，不真跑 device kernel）；device 首次执行完全交 precision。
- **四把尺子**：**可维护/架构** 更彻底（消除 codegen smoke 与 precision run-cases 的**双重真机 launch 冗余**——map 证 precision 已自 redeploy+run-cases）；但 **可诊断** 弱一档——失去 codegen 边界的"至少 launchable"早信号，需自建 launchability 探针补回 `upstream` 类（注册/tiling/schema）的早拦，否则这些框架缺陷推迟到 precision 才炸（违反 §1.3 加载/早期暴露）。
- **取舍**：B2 少一次真机 smoke（省时），但把 `upstream` 类框架缺陷的暴露点也后移，除非探针做全。**比 B1 激进，收益（省一次 launch）不足以抵 `upstream` 早拦的损失。**

---

## 4. 推荐 + 关键设计约束

**推荐 B1**（codegen smoke 重分类，边界=scope_guard 表），理由与约束：

1. **单一边界权威**：codegen smoke 判定与 precision scope_guard **必须用同一 upstream/pass 分类**（§2.5 唯一通路；§1.2 可维护=澄清既有不变式）。L4 把这条线抽成单一分类器，两处引用，不各写一套。
2. **"codegen 只保框架"≠"codegen 不管正确性"**：框架缺陷（编译/链接/注册/InferShape/tiling-key/schema）**仍归 codegen 且仍 halt**——Q1 scatter 缺 InferShape（EZ1008 tiling failed）**明确留在 codegen**。下沉的**只有** device 侧 kernel 执行崩溃（507035/OOB/对齐/同步）。这条区分是本方案的核心，必须在 L4/skill 里写清，避免 codegen 借"只保框架"放水框架质量。
3. **下沉是"错层→对层"，非"把 halt 挪后"**（关键论证）：
   - **对的工具**：precision_debug 有 printf-locate / DumpTensor / bounds-check / comment-bisect phase 专治 OOB/runtime crash；coder in-session loop 没有。
   - **独立且新鲜的预算**：codegen 的 40 轮预算被编译层错误吃掉（Q10：aggregate 138 次编译命中），runtime 崩到手时预算已耗尽；下沉后 runtime 崩拿到 precision 的**独立、未被编译错误消耗**的预算。
   - **终态更合理**：codegen 不再因 runtime 崩硬 halt 整条 pipeline；precision `exhausted→cannbench_adapt`（best-effort 到 eval，非 halt，workflow.py:682-686）符合 cann-bench 终态 loss/NO loopback 哲学（step-70 §07）。
4. **A3/A5 对齐**：B1 让 A3(Membase) 与 A5(Regbase 已 defer 真 smoke) 收敛到同一契约（§2.5）。L4 需核对 A5 `_transition_regbase_s5` 合成 `smoke_passed=True` 是否也应升级为"框架探针通过"而非无条件 True（A5 当前更宽——连 launchable 都没验就 defer；B1 反而给 A5 补上框架级早拦）。
5. **precision 可达性前置**：下沉的前提是控制流能到 precision。B1 靠"runtime 类不 halt codegen"实现；需确认 codegen transition 对 `runtime_ok=False` 走**非 halt 放行**（新增 codegen→precision 的非 halt 通路，或让 `deploy_result` 在 framework_ok 时即满足 output_contract）。

**scope（本 L3 只覆盖边界重划 = Q2/Q3 + 用户主张）**。不含：
- **Q1/Q10 codegen 收敛加速**（缺 InferShape 系统盲点、ASCENDC_TPL 模板派发试错、moe_re_routing 带毒、编译层内耗）——用户第二方向"全局化/通用化加速 codegen 收敛"，属**独立 L3**（建议 `84-codegen-convergence-analysis.md`，下一步开）。
- **Q5–Q8 design validate 门**（越界查 docgen / 空转 / 信 log 不信文件 / advisory 触发全尾 loopback）——独立 L3。
- **Q11 硬超时业务语义**——独立，但与本方案协同（下沉后 codegen 不再在 runtime 崩上耗到超时）。

---

## 5. 决策点（用户 2026-07-31 已拍板 — 冻结）

- **D1 ✅ 取 B1**：重分类保留 smoke，判定改用 scope_guard 的 upstream/pass 分类作单一边界权威。
- **D2（用户订正 — 推翻"框架类=codegen"简单切法）**：**不按静态类别硬分，按"哪个 stage 更能合理解决"分**。用户明确：InferShape/tiling-key 这类**与算子实现强耦合**，不该只因"是框架产物"就划归 codegen；要从**合理性**（谁有对的工具、谁产出这类事实、谁改的代价小）判定归属，逐类论证，不一刀切。→ 详见 §7 逐类归属表。
- **D3 ✅ A5 不动**：`_transition_regbase_s5` 保持现状，本轮只动 A2/A3(Membase) 相关。A5 codegen 归同事（记忆 codegen-a5-ownership-boundary）。
- **D4（用户订正 — 原则级）**：**所有代码问题一律不许 halt**——代码问题不是硬阻塞。halt 仅保留给真正的硬阻塞（如 server-side 429、环境前置缺失）。任何代码缺陷（编译/注册/schema/InferShape/tiling-key/runtime 崩溃/精度）都必须**路由到能合理解决它的步骤**处理，不 halt。→ 这重塑了整个模型：不是"codegen 只 halt 框架类"，而是"codegen 对代码问题**从不 halt**，按归属 loopback/下沉"。

---

## 6. 句柄（取证 + 代码锚点）

---

## 6. 句柄（取证 + 代码锚点）

- L1：`84-batch-205112-issues-summary.md` Q1/Q2/Q3
- 边界代码：`orchestration/stages/codegen.py:{70-91 契约/fail_strategy,846-866 读deploy,1332-1367 halt判定,1675-1680 A5宽容}`、`adapters/npu/deploy.py:{80-166 deploy,406-490 smoke harness,523-603 _run_smoke,585-602 判定}`、`domain/verification.py:57-82 Build/DeployResult`
- 边界权威：`.claude/skills/ascendc-precision-scope-guard/SKILL.md:34-42`（upstream/pass 表）
- 图/转移：`orchestration/.../workflow.py:{630-647 stage序,676-686 TRANSITION_TABLE}`、`graph_executor.py:387-414 halt`、`runner.py:509-514`
- precision 自 redeploy：`precision_debug_substages.py:{1228-1229,899-948,1733-1736 scope_guard route}`
- 关联：`27-infra-error-classification-impl.md`（错误分类基建，L4 复用候选）、`31/33/54 precision-debug`、step-70 §07（cann-bench NO loopback）
