# 20260810 批（6 算子）系统性框架模式说明

> 用户问「问题7没看懂，需要展开说清楚」。这里把批跑 20260810_010146
> （batch_id `20260809-170202-976a7a`，算子 gelu/grid_sampler_3d/group_norm/
> resize_bilinear/transpose/unique）发现的**系统性框架模式**逐个展开：
> 现象 → 证据 → 根因 → 影响 → 处理状态。
>
> 判据：4 个以上独立算子同模式出现 = 框架缺陷，非算子巧合。

## 0. 先分清「模式」与「单算子问题」

批里每个算子各有自己的单算子问题（design 缺陷、硬件精度等，见
`04-convergence-analysis.md`）。**下面 6 个是跨算子复现的框架层模式**，与具体算子无关。
其中第 6 个（golden_precision）是本次会话新发现并已修。

---

## 模式 1：smoke failed (not callable) —— 4/6 算子

**现象**：gelu / resize_bilinear / grid_sampler_3d / unique 的 codegen 报
「build OK 但 smoke failed (not callable)」，携带 `smoke_passed=False` 进 precision，
由 scope_guard 分流。transpose / group_norm 除外。

**证据**：`20260809-170202-339545/run.log:3735` 等 4 处
`[WARN] codegen build OK but smoke failed (not callable); NOT halting — carrying deploy_result(smoke_passed=False) for precision_debug scope_guard to triage`。

**根因（2026-08-11 逐 log 复核修正）**：`smoke failed (not callable)` 是**误导性分类桶**，
把不同根因混为一类。真实报错各异：
| 算子 | smoke 真实报错 | 真根因 |
|---|---|---|
| resize_bilinear | `exactly one of output_size/scale_factor must be provided`（tiling） | 探针用例缺必需 attrs（`bind` 只有 x） |
| gelu | `invalid approximate value`（tiling） | 探针喂非法 attr 值 |
| grid_sampler_3d | `invalid numeric default value`（torch 注册期 abort） | codegen 生成 m.def 默认值非法（真·注册缺陷） |
| unique | `Cannot find bin of op UniqueStage2`（GetWorkspace） | 该 dtype 组合无 kernel bin（注册覆盖缺陷） |
前两类（resize_bilinear/gelu）op **可调用**、是探针用例喂参不合法——属 harness 喂参缺口
（非 codegen）；后两类是 codegen 生成/注册缺陷。

**影响**：批跑时代 smoke 失败被"宽容放行"进 precision，run_tests 在**同一根因**上崩
（resize_bilinear run_tests_iter-0 `missing value for scale_factor` → returncode -11）——
smoke-fail 不是被 precision 修好，而是把同一 bug 带到 run_tests 再崩一次，白烧一轮预算。

**处理状态**：**路由已修（a0860df4 smoke 阶段分流）**——host 阶段失败（kernel 未执行）回
codegen 重试，kernel 阶段交 precision。但根因未 gate 化：attrs 喂参缺口待修（见下
「待处理集合」模式1-attrs）；grid_sampler_3d/unique 靠重试+反馈自愈（可选加固=静态 m.def
attr 默认值校验门）。

---

## 模式 2：no_golden_reference —— 归属误读已纠偏（2026-08-11）

**【纠偏】原文档把 `no_golden_reference` 误记为 transpose/group_norm 的 run_tests 空判。
逐条核对 run.log 后实据推翻**：每条 `no_golden_reference` 前都紧跟
`[INFO] Deployer: smoke passed ... (no golden)`——全部是 **deployer smoke 探针的输出**
（探针故意无 golden，只验可调用），runner 分类器把 `golden_used=false` 统一标成
`no_golden_reference`（探针固有标签）。存档的 `run_tests_iter-0/result.json` 里
transpose/group_norm 均为 `golden_used: True, bottleneck: real_kernel_vs_golden`——真在对比。

**证据**：两算子 run.log 中每条 no_golden 的上下文 10 行内必有 `smoke passed`；run_tests
存档 result.json `golden_used: true`。

**真实的次生问题（已修）**：smoke 探针 result 长这样——`passed: true`、
`mismatch_count: 0, total_count: 0`、`golden_used: false`。任何**不看 golden_used 的消费者**
都可能把它误当成精度通过。这是**标签/可观测性缺陷**，不是"golden 没加载"缺陷。

**处理状态**：**已修（2026-08-11）**——smoke 探针 result 增加 `smoke_probe: true` 标记 +
`bottleneck: smoke_callable_only`（`_harness_template.py` + `_build_test_harness` 新增
`smoke_probe` 参数，deploy 探针置 True），与精度运行明确区分。文档归属已纠偏。

---

## 模式 3：PD-CONTRACT missing harness_timeout_sec —— 6+ 次

**现象**：run_tests agent 反复漏写 `harness_timeout_sec` 字段，
控制台 `[WARN] [PD-CONTRACT] control.json missing 1 required key(s): ['harness_timeout_sec']. Auto-initializing to safe defaults`。

**证据**：批 log 中该 WARN 出现 6+ 次（如 `20260809-170202-339545/run.log:4177`）。

**根因**：run_tests agent（LLM）写 control.json 时丢字段，契约门自动安全初始化续跑。
这是 LLM 产物的**字段完整性**问题，不是控制流 bug——契约门的设计（缺失→安全默认+WARN）
是对的，但反复触发说明 agent prompt / schema 约束不够硬。

**影响**：每次 WARN 都是 agent 一次契约违约。门兜底了（不中断），但这是「agent 纪律」
问题，应通过 prompt/schema 收紧减少触发。

**处理状态**：**未修**（属 agent 纪律 / schema 约束，非本次会话范围）。

---

## 模式 4：git diff 未报告改动 —— 6/6 算子

**现象**：所有 6 个算子的 coder agent 改了文件但没在报告里声明改动，
控制台 `[WARN] git diff found changes the agent didn't report: [...15 个文件]`。

**证据**：`20260809-170202-339545/run.log:3231` 等 6 处。

**根因**：codegen agent 的产物声明（decision_log / 报告）与 git 实际 diff 不一致——
agent 改了代码但没写进决策记录。这是 agent 纪律 / 报告契约问题。

**影响**：审计/追溯断裂（改了什么是黑盒），但**不阻断流程**（WARN 留痕）。

**处理状态**：**未修**（agent 报告契约，非本次会话范围）。

---

## 模式 5：workflow_timeout 10h 太短 —— 4/6 被截断

**现象**：gelu / grid_sampler_3d / group_norm / unique 4 个算子
`FAIL(exit 124)`，`[ERROR] Timeout: Workflow timeout: exceeded 36000s budget (ran 36927.8s)`。
resize_bilinear / transpose 刚好 9.5h 内跑完。

**证据**：批 log `[FAIL(exit 124)] gelu exec=...` 等 4 行；`scripts/batch_self_evolve.sh:195`
`workflow_timeout_sec: ${WORKFLOW_TIMEOUT:-36000}`。

**根因**：`workflow_timeout_sec` 默认 36000s（10h），对「每算子含 ~7h precision_debug 循环」
的批来说太紧。4 个算子跑满 10h 被硬截断（**非正确性失败**，分已产出但流程没走到收尾）。

**影响**：**本批 4/6 算子没走完完整流程**（截断在 eval 或 finalize 前）。分数已产出，
但流程状态是「截断」不是「完成」。

**处理状态**：**用户确认不改（2026-08-10）**——workflow_timeout 默认 10h 视为既有设计
（分数已产出、截断非正确性失败），不做修改。**本模式从待处理集合移除**。

---

## 模式 6（本会话新增）：golden_precision harness-eval 分裂 —— 已修

**现象**：debug 判 20/20、eval 判 13/20（resize_bilinear）。

**根因**：eval 默认 golden_precision=fp64_cpu（升 fp64 算参考），harness 用原生 dtype
参考 → 两侧参考不同 → 假收敛。

**处理状态**：**已修**（commit `0f07d53e`）：golden_precision 契约化 + harness 三处
golden 调用上抛 fp64。详见本目录 01-04。

---

## 与本次 golden_precision 修复的关系

模式 2（no_golden）和模式 6（golden_precision）初看同族（都是 harness golden 参考链路），
但 2026-08-11 复核后模式 2 被证为**误读**（no_golden 全来自 smoke 探针固有标签，run_tests
真在对比）——非 harness golden 缺口，是 smoke 标签可观测性问题（已修）。模式 6
（golden_precision 口径分裂）是真实缺陷（已修）。模式 1/3/4 独立，各有产权。

## 待处理集合（2026-08-11 更新）

- **已修**：
  - 模式 6（golden_precision，commit `0f07d53e`）。
  - 模式 1-attrs（harness 喂参缺口，2026-08-11）：harness 按 op_spec 声明补齐用例缺的
    attrs——optional→None、有默认→默认值，镜像输入侧 None 占位语义（§2.5）。resize_bilinear
    run_tests 崩根因（m.def 声明 `float[2]? scale_factor` 可选类型但无默认 → torch 要求
    kwarg 必须传，harness 只传用例 attrs 不补 None）已由结构信号修复，不认算子名（§1.12）。
  - 模式 2（smoke 标签 + 文档纠偏，2026-08-11）：smoke 探针 result 加 `smoke_probe: true` +
    `bottleneck: smoke_callable_only`；no_golden 归属误读已修正。
  - 模式 3（harness_timeout_sec 框架自有化，2026-08-11）：放大值写框架自有 sidecar
    （`harness_timeout.fw.json`，agent 的 control.json 重写碰不到）；契约对框架自有字段
    缺省静默（不 WARN、不填默认打回 120）；debug_service 读取 control.json → sidecar →
    默认。agent 从时间字段循环彻底摘除。
  - 模式 4（changed_files.json 读写契约，2026-08-11）：根因是**读写契约断裂**（agent 按
    skill 写 staging、框架从 op_dir 读，三处错位：位置/格式/路径基准），非 agent 纪律。
    修法=§2.9 构造性：框架从 git diff 派生权威报告进 artifacts（审计链永远完整）；
    解析器学会 agent 的 section 格式 + 后缀归一化，自报降为交叉校验；skill 改在
    cwd 写报告（读端对齐）。
- **模式1-codegen（已路由，可选加固）**：grid_sampler_3d/unique 由 a0860df4 smoke 阶段
  分流回 codegen 重试（host 阶段失败回生产者自闭环，不再交 precision 白烧预算）；
  可选加固=静态 m.def attr 默认值校验门（把 grid_sampler_3d 的 `invalid numeric default
  value` 在 pre-build 拦下），低优先。
- **排除（用户确认不改）**：模式 5（workflow_timeout 10h，视为既有设计）。
- 产权：① harness 喂参链（precision harness）；② 超时字段（框架自有 sidecar）；
  ③ agent 产物契约（agent prompt + schema 约束）；④ changed_files 审计链（git diff 派生）。
