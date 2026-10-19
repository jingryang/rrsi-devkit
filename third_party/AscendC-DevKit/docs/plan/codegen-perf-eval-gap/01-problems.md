# L1 问题记录 — 生成算子性能差 4 个数量级 + eval 性能信号被超时墙掩盖

> 记录客观事实，不提方案。发现于 ccad38 回放（2026-08-26），实例算子 unique。

## P1：生成算子 kernel 相对 baseline 慢 4 个数量级（实例：unique）

**证据**（eval 子进程 `kernel_details` 采集，同一 eval 同一 profiler 下 baseline 与 kernel 同源）：

| case | kernel(ai_us) | baseline(us) | 慢倍率 |
|---|---|---|---|
| unique_1 | 712,821 | 18.4 | ~39,000× |
| unique_2 | 2,856,593 | 174.8 | ~16,000× |
| unique_4 | 39,735,316 | 3,494 | ~11,000× |
| unique_6 | 49,803,986 | 11,883 | ~4,200× |

- kernel 单 case 40-50s（正常毫秒级），随 shape 单调恶化（baseline 18µs→11.9ms 对应
  kernel 0.7s→49.8s）；
- 20 个 case 只完成 9 个即撞 30 分钟超时墙（上次原始 run 走至 case 10，同构复现）；
- 完成的 9 个 case **全部 acc_passed=True**——精度正确、性能差。

**排除项**：非 profiler 采集开销（baseline 同源微秒级）；非环境抖动（两次独立 run 复现）；
非精度问题（全 passed）。

## P2：框架精度闭环无性能判据

precision_debug 闭环（run_tests→diagnose）只查精度（acc/err），性能不在判据内——
性能问题只能经 cannbench_eval 的 30 分钟超时墙以「0 分」暴露，且无性能门在 eval 前拦截。

## P3：eval 30 分钟超时墙挡掉完整性能报告

kernel 慢 → 每个 case 数分钟 → 20 个 case 跑不完 30 分钟墙 → 报告只有前 ~9 个 case、
无完整 score/性能分布，性能问题本身被「超时」信号掩盖（原本是性能信号，读成 infra）。

## 边界

- P1 根因在**算子产物**（codegen 输出质量），产权不在框架——优化该实例算子需
  ascendc-profiling / perf-tuner / lingxi-dsl-evo 类工具链。
- P2/P3 是**框架可观测性/判据缺口**（§3 无性能判据、超时墙无完整报告落档）。
- §1.12：P1 的「修 unique」是实例处置；框架侧任何机制必须按结构信号通用，不得按算子名。

## P1 根因细化（2026-08-26 代码取证）

**设计无责**：design_spec.data_flow / general_design.loop_framework 给的是 LSD radix
并行算法（多核 N 维切分 + CopyIn/CopyOut 分块 + UB 向量位序变换 + 每趟 3×SyncAll）；
tiling_results 声明的标量点仅两处（数据依赖散射、跨 tile prevKey/uniqCnt），
并明言「全流式无常驻大缓冲」——即数据通路设计是向量式的。

**coder 调试期修正扩张（实证）**：
- `decision_log.json`：「radix 数据通路全标量化（调试期修正）」——x 读入、WS 键/秩
  读写、y/inverse 写出**全部** GetValue/SetValue（18+18 处、21 个 for、0 DataCopy），
  理由是实测三类硬件级竞态/约束（TBuf 标量写后 MTE3 读缺流水同步 / 散射标量 GM 写与
  下趟 MTE2 读竞态 / DataCopyPad 基址非 32B 对齐 507035）；代码 466 行 unique.h 注释
  同证「不使用搬运队列」。
- 「分核收敛为单核（调试期修正）」——`unique_tiling.cpp` `MIN_ELEM_PER_CORE =
  INT64_MAX` 强制 blockDim=1（设计是多核切分）。

**机制定性**：真实同步难题（MTE↔标量流水竞态、非对齐）的正解是同步原语选型
（ascendc-sync §3，skill 已有「落码前必读」），coder 选择了「消灭流水」——以标量化
+单核让竞态物理消失，换正确性、牺牲全部性能。设计声明的窄豁免（仅散射标量）被扩张
为全数据通路。

**框架放大因素（两条）**：
1. AR-1 豁免被形式合规穿透：coder 逐点落盘理由（硬件实测非主观，满足字面要求），
   但扩张范围远超设计声明点；skill 判据「主循环搬送有 DataCopy 等价物 → 理由不成立」
   未被执行（x 读入/键秩搬运均有等价物）。
2. 无性能反压（=P2）：闭环只奖励 20/20 通过，标量化零成本信号，直到 eval 0 分才暴露。
3. （对照）step-88 的 design_deviation 守护只覆盖 precision diagnose，codegen 框架驱动
   build-retry 循环（本次「调试期修正」发生地）没有等价守护。
