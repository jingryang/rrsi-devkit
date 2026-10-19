# L1 — chip-gate 前置条件化：问题记录

> 本层只记客观事实（哪里坏 / 凭什么这么说），不提方案、不排顺序、不写决策。
> 方案见 `02-analysis.md`（L3）；halt/feedback 全局机制见 `halt-feedback-global-policy.md`（专题）；
> 步骤索引见根目录 `skills-integration-and-tdd-plan.md` step-32（L2）。

## 背景（事实，非方案）

step-31（P57 能力下沉）删除了 `DeployStage`/`VerifyStage`，deploy 收进 `Deployer` 服务（codegen agent 会话内 in-session build-loop 调用 `redeploy`）。构建 chip-gate（§1.9：构建目标平台必须 == 硬件平台）随之被塞进 `Deployer.deploy()` 开头，短路在任何 subprocess 之前。本工作记录由此连带的三个问题。

---

## P1 — gate 困在 Deployer 服务内 + 信号通道空

**事实**：chip-gate 在 `Deployer.deploy()` 内短路（原 `deploy.py:74-93`：`target != hardware` → 直接 `return DeployResult(smoke_passed=False), _resolve_fail("chip-gate", ...)`），发生在任何 subprocess 执行**之前** → **没有任何 `subprocess/*.log` 落盘**。而 codegen 的 in-session build-loop prompt（`codegen.py:440-463`）明确告诉 agent 在 `smoke_passed=False` 时读 `{run_dir}/subprocess/*.log`（`codegen.py:458`）自修。于是：gate 短路 → log 为空 → agent 无具体错误可读 → 空转到 `max_rounds` → codegen.transition（`codegen.py:578-590`）读 `last_deploy.json` 的 `smoke_passed=False` → 合成通用 `error_type="deploy_failed"` halt，**丢掉 gate 手里那个具体的 `'A5' vs 'A2'`**。

**凭据**：`deploy.py:74-93`（gate 短路点，pre-subprocess）；`codegen.py:458`（build-loop prompt 让 agent 读 `subprocess/*.log`）；`codegen.py:578-590`（transition 三出口：no handoff / smoke_passed=False → `deploy_failed` halt）。gate 短路时不产 subprocess log，与 prompt 的读 log 自修契约错位。

## P2 — 两类失败混淆于同一个 `deploy_failed`

**事实**：环境代际不匹配（target≠hardware，**不可由改码修复**）与代码缺陷（compile/smoke 失败，**可改码修复**）在表面上都被归为 `error_type="deploy_failed"`。codegen 的 build-loop（`codegen.py:440-463`）把 `deploy_failed` 当「可修代码缺陷」处理（读 log → 改码 → commit → redeploy）。于是不可修的环境不匹配也被丢进自修循环空转，直到 `max_rounds` 耗尽才 halt。

**凭据**：`deploy.py:_resolve_fail("chip-gate", ...)` 与 `deploy.py:_err(...)`（compile/smoke 失败）产出**同形** `error_type="deploy_failed"` 的 ErrorFeedback；codegen build-loop 消费 `deploy_failed` 时无 halt/loopback 之分（`codegen.py:440-463`）。

## P3 — gate 落错层（服务无 `fail_strategy`，无法 halt 流水线）

**事实**：`Deployer` 是服务（L3），不是 Stage（无 `fail_strategy` 属性、不进 graph_executor 的 halt/loopback 路由）。chip-gate 落在 `Deployer.deploy()` 内时，即便判出 mismatch，也无法直接 halt 流水线——只能 `return (DeployResult(smoke_passed=False), ErrorFeedback)`，把 halt 与否的决策甩给调用方（codegen agent 读 ErrorFeedback 自行判断），而调用方按 P1/P2 的契约把它当可修 `deploy_failed` 处理。判断（precondition 语义）被错放在了任务节点（service）里。

**凭据**：`Deployer` 类定义（`deploy.py:52-61`，无 `fail_strategy`）；gate 在 `Deployer.deploy()`（`deploy.py:74-93`）而非某 Stage 的 `validate_inputs`/`gate()`；halt 通道（`fail_strategy="halt"` → `_stage_failed` → `is_terminal`，或 `PreconditionError` → dispatcher）只对 Stage 生效，服务无入口。
