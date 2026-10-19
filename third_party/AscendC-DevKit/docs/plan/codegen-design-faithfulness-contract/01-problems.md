# L1 问题记录 — codegen 结构忠实缺口（设计标量契约 / 归属边界 / 交棒证据）

> 记录客观事实，不提方案。实证来源：run 20260825-153847-ccad38（unique 算子，
> eval 慢 baseline 4 数量级）的代码取证 + 框架代码核勘（2026-08-26）。

## P1：设计标量声明无机器可读锚点

- AR-1（ascendc-op-dev-coding 维4）要求每个标量访问点的 `reference` **必须指向设计
  产物声明的标量路径**，decision_log schema 也定义了 `scalar_access_points[]`
  （location/usage/reason/reference）；
- 但 tiling_strategy（ascendc-op-design-integrate/schema/tiling_strategy.json）**没有**
  声明标量点的字段——本次设计只在 prose 里提到（tiling_results 的 buffer 表
  `"size": "scalar"`、叙述「数据依赖散射」「prevKey/uniqCnt 标量」）；
- 结果：`reference` 无处可指，自检条款**不可判定**，模型走了弱形式——decision_log
  只有一条 topic 级 `decisions[]` 条目（「radix 数据通路全标量化（调试期修正）」），
  `scalar_access_points[]` 为空。

## P2：scalar 契约无框架消费（自检被形式合规穿透）

- 代码实际状态：unique.h 466 行，18 SetValue + 18 GetValue + 21 for，**0 DataCopy /
  0 向量 API**；unique_tiling.cpp `MIN_ELEM_PER_CORE = INT64_MAX` 强制单核。
- AR-1 是纯模型自检（维4 表格），框架收集了 `decision_logs`（State 字段）但**无任何
  机械校验**消费 `scalar_access_points[]`；
- 判据条款「主循环搬送有 DataCopy 等价物 → 理由不成立」未被任何机制执行：x 读入、
  WS 键/秩搬运均有等价物，仍全标量化。落盘的 topic 级理由（三类实测竞态）形式上
  满足「理由落盘」，豁免被穿透。

## P3：host/kernel 归属边界只在框架出口门生效，会话内无镜像

- 框架侧边界**已存在且正确**：`codegen.py _classify_smoke_phase`（§1.12 结构信号：
  kernel 执行证据 507035/507057/AICORE/越界 → "kernel" → D4 交 precision；
  tiling/infershape/注册/launch 的 EZ/561xxx 家族 → "host" → 回 codegen）；
- 但 skill（ascendc-op-dev-coding L178「会话内构建……自检定位错误」）引导的 in-session
  构建循环跑 `ascendc-devkit redeploy`（含真 NPU smoke），coder 在会话内撞到 kernel
  阶段错误（507035 崩溃、实测「键读出陈旧/全零」——后者只有跑过数据才观察得到）；
- skill/agent 说明中**无一处**告知 coder「kernel 阶段错误不归会话内吸收、kernel 阶段
  smoke 红是合法交接」；失败在到达出口门前被会话内修掉（本批 2h / 上批同算子 160min），
  出口门看到绿 smoke，分类器永不触发——边界被绕过。

## P4：会话内调试证据随吸收而丢失，precision 冷启动

- coder 会话内 2 小时观察到的真实同步竞态证据（TBuf 标量写 vs MTE3 读、散射写 vs
  下趟 MTE2 读、非对齐 507035）只以 topic 级 rationale 形式存在，无结构化交棒；
- 若走 D4 交 precision，diagnose 拿到的是 crash dump / 失败 case（step-88 已注入设计
  上下文），但 coder 已排除的方向、已观察的现象不在交接面内——重复摸索。

## 边界与关联

- 本工作线只动**框架与 skill 引导**，不动任何具体算子（§1.12）。
- 性能反压缺失（闭环无性能判据）是正交长线，产权 `codegen-perf-eval-gap/`（step-92
  选项①，已记录待独立立项）；本线不重复覆盖。
- 与 step-88（precision 侧 design_deviation 守护）对称：本线把结构忠实约束补在
  codegen 侧。
