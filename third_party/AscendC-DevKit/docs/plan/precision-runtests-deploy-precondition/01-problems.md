# L1 问题记录 — N1 去 LLM 化后 run_tests 测量前提断裂及相关缺陷

> 记录客观事实。不提方案、不排顺序、不写决策。方案见 `02-analysis.md`（L3）。
> 触发事件：批跑 `output/20260825-083544-c52f0b/20260825-083544-608989/run.log`（pangu 弱模型，算子 unique）。

## P1：N1 迁移缺口——run_tests 测量前提（last_deploy.json）无人保证（根因）

- N1（commit `6a25613c`/`a3b0e6cf`，run_tests 收敛为 RunMeasure 纯 Python 测量）删除了 run_tests agent。被删 agent 的输入表明确含 `build_command`（"编译预检 / **首轮 redeploy**"，旧 SKILL.md 见 git `a3b0e6cf~1`）——该自适应前置**未迁移**为确定性步骤：`_build_measure_command`（precision_debug_substages.py:1882-1933）只有 init-checkpoint + run-cases + 建队列。
- `last_deploy.json`（`artifacts/debug/<op>/`）的**唯一写入者**是 `ascendc-devkit redeploy`（DebugService.redeploy，debug_service.py:70-85，**无条件落盘**——deploy 失败也写）；codegen 框架循环直调 `Deployer.deploy(state)`（不落盘）。
- 设计契约未变：codegen.py:3354 注释"完整 deploy/smoke 由 **precision_debug 阶段的 redeploy→run-cases 闭环**覆盖"——实现只剩 run-cases 半边。
- 触发证据（run.log:3305/3310）：run_tests 两轮 `rc=1: no last_deploy.json ... run redeploy first` → `consecutive_aborts=2 ≥ _ABORT_EXHAUST_THRESHOLD=2`（substages.py:384）→ abort_exhausted 熔断 → converge → 0 分。
- 影响面：**所有 post-N1 fresh entry**（smoke 通过与否皆然——codegen 成功路径只写 State.deploy_result，run-cases 只读 debug 目录文件）；20260823 及之前未暴露仅因 run_tests 还是 agent 架构，本次是 N1 后第一个真实批跑。

## P2：文件存在 ≠ 记录可用——空路径 DeployResult 可达链

- deploy.py:890-897 build 失败分支返回**无路径** `DeployResult(smoke_passed=False)`；install 失败分支（:929-936）仅部分路径；仅 smoke 失败分支（:945-955）带全套路径。
- 可达链：diagnose 构建失败 → 回滚 → 框架路由回 run_tests 回归 → 陈旧空路径记录仍在 → 仅判文件存在的门槛放过它 → run-cases 拿空 install_path/python_path → 误导性失败队列。

## P3：measurement abort 对确定性错误盲重试（§1.10 反模式实证）

- `rc≠0` 是机制特征；`no last_deploy.json — run redeploy first` 是自带修法的确定性业务信号；transition 仅按 rc 计数 abort（substages.py:2029-2061），未消费信号语义 → corrective 重试一轮必然同样失败（空转），随后熔断。

## P4：diagnose Step 0「工程内可修」枚举式表述的歧义风险

- SKILL.md/manifest/prompt 的 Step 0 以例子列举"工程内可修的"（plugin 注册/声明/manifest 不一致、算子未注册、golden 缺 get_input）——未显式含 host 侧崩溃/tiling/launch 脚手架缺陷；弱模型可将例子清单读成封闭枚举。
- 关联事实（同次 run）：smoke 空输出（smoke.log stdout 完全为空、stderr 仅一条无害 padding warning——正常批 eval stderr 亦有同款）→ `_classify_smoke_phase`（codegen.py:1782）无 kernel/host 证据返回 None → coder 判 `not_codegen`（run.log:3285，理由"log 只有 warning 无 error，环境问题非产物问题"）→ K 守卫放行 → D4。
- `upstream_signal` 的语义是 halt 整个 run（0 分，substages.py:1258-1282）——把 host 侧缺陷"只上报"等于判死 run。

## P5：N1 验证盲区——fresh entry 从未被测试覆盖

- heavy ST（test_precision_diagnose_inplace_loop）seed 了"run_tests 已跑完、result.json 已就位"状态，fresh entry 被跳过；UT 只断言命令文本构造 → P1 闸门失败在验证中不可见。

## P6：build-failed-case-queue.py docstring 陈旧

- :200-203/266-267 称 crash_sentinel_mode 使框架"route directly to comment_bisect (skipping diagnose/fix)"——comment_bisect 独立 phase 已在 P3 删除；实际路由进 diagnose（substages.py:2235 "diagnose 读 crash dump"）。

## P7（既有问题，声明不修）：P69 card 隔离 subprocess 旁路

- 新增前置的 redeploy 经 subprocess 执行，继承 `state.npu_id or 0` 旁路（与 diagnose 的 build_command 同行为）；既有问题，另行跟踪。

## P8（契约代价，声明接受）：smoke 通过的 first entry 同样无记录

- 每算子 run_tests 首轮固定多一次 redeploy（本批实测 build 27s + install 2s + smoke 16s）。codegen.py:3354 契约的本来要求，非回归。

## P9（有界残余，声明接受）：result.json 缺失时的手工建队列路径随 agent 删除

- 旧 agent 在 result.json 不存在时从 run.log 手工构造 failed_case_queue（旧 SKILL.md 硬错误处理节）；现行脚本覆盖 result.json **存在**的三档形态（失败明细 / tested_cases 回退 / crash 哨兵），文件缺失仅剩 run-cases CLI 级失败场景 → `set -e` → abort → 熔断（该场景熔断语义正确）。P3 减法的设计决策，残余有界。

## 教训（供 L3 引用）

**去 LLM 化一个 stage，必须把被删 agent 的隐式前置逐一枚举成显式确定性步骤**——隐式行为没有单点产权（§1.15 视角），删除载体即静默丢失。验证同理：被替换路径的 fresh-entry 形态必须有测试覆盖（P5）。
