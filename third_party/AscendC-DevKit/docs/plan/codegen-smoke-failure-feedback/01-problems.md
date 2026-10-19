# L1 问题记录 — codegen smoke 失败反馈通道：可观测性缺失 + 不自含

> 记录客观事实，不提方案。实证来源：run 20260826-114823-99c4c0（gelu 算子，
> smoke 静默失败 3 轮后 stop-loss D4，~1h50m）+ 框架代码核勘（2026-08-26）。
> 用户定性：「理论上所有的问题都要有明确的解决方法，否则就是问题」——
> 静默失败是当前没有明确解决通路（只有重试上界）的失败形态。

## P1：smoke 静默失败丢弃进程死亡方式（rc/信号）

- `deploy.py _run_smoke`（L833-846）：`subprocess.run` 返回后判
  `r.returncode != 0` 触发失败分支，但只持久化 stdout/stderr、只回传
  `r.stderr`——**returncode 的值在判断后被丢弃**，不进 smoke.log、不进
  ErrorFeedback、不进 coder 反馈；
- gelu 实证（99c4c0/94b926）：smoke 15s 死亡，stdout 空、stderr 仅一条
  allocator warning → coder 反馈的「首条错误行」为字面量 `=== stdout ===`；
  框架**已观测到** rc≠0（否则不进失败分支）却未传递——区分「native 段错误
  （rc=-11）」与「Python 异常退出（rc=1）」的关键信号在框架手里被扔掉；
- 下游 `_classify_smoke_phase` 只消费文本：无错误码签名 → None →
  smoke_owner_judge（coder 自判归属）。

## P2：harness 输出缓冲策略使 native 死亡不可分辨

- smoke harness 模板逐用例异常吞进 exit 0 + `case_details[0].error`（
  `_smoke_case_error` docstring），用例结果 JSON 在 stdout **最后一行**统一
  打印；
- smoke 子进程调用为 `[sys.executable, "-c", script]`（无 `-u`、无逐用例
  flush）：进程原生死亡（signal）时 Python stdout 缓冲整体丢失 → 空输出；
- 空输出无法区分「import 期崩 / 首用例前崩 / 第 N 用例中崩」——「kernel
  是否执行过」（分类器的归属判据）不可判。

## P3：smoke 失败反馈不自含，re-spawn 架构的隐含前提被违反

- 方案 Z（build-retry 阶段3）的 re-spawn + footer 反馈设计隐含前提：**反馈
  自含可诊断**——编译错误 footer 满足前提，该通路高效；
- smoke 失败反馈（codegen.py L2331 渲染段）只含：首条错误行（可能为空或
  字面量）、smoke.log 路径、stderr 摘要、归属判定指引；**不含** rc/信号、
  **不含 smoke 调用现场**（script 是 `-c` 内联字符串，未落盘——coder 无法
  直接复现，只能逆向重建）、**不含框架注入的 env**（PYTHONPATH /
  ASCEND_CUSTOM_OPP_PATH / LD_LIBRARY_PATH / ASCEND_NPU_ID 全是框架构造的，
  但没告诉 coder）、**不含前次会话结论**（iter1 自检 NPU smoke 8/8 全绿
  记录在其 decision_log 与最终结论文本里，iter2 不知道）；
- gelu iter2 实证：65min 逆向重建复现环境（exact_smoke_script.py 副本 +
  AST 分析 + 用例顺序 bisect + dlopen 链追踪）才重新发现「前次已全绿、
  差异在环境」——这些信息框架全部持有，只是没喂。

## P4：stop-loss 时间上界假设过期

- `_SMOKE_ERROR_STOP_LOSS_STREAK = 3`（codegen.py L215）注释假设
  「~3 轮 ≈ 15 分钟」；
- gelu 实际 3 轮 ≈ **1h50m**（iter1 25min + iter2 83min + iter3 5min），
  每轮是完整 agent 会话（真实 LLM 全流程成本）；
- silent 失败签名 `no_code@@` 的 3 轮对 coder **均不可诊断**——3 轮同价
  （都是盲试），stop-loss 封顶了浪费但没有减少无效轮次；上界存在 ≠
  解决通路存在。
