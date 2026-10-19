# 多算子调度框架 — TrainingRunner

> **性质**：self-evolution 线工作记录（L3），串起 `01`/`02`/`03`/`04`。
> **定位**：DevKit **两层编排的上层**。单算子内 = stage 树 + State + event-sourcing（现有 `generate_ascendc`）；多算子间 = 任务级并发调度（本文 TrainingRunner）。两者各司其职，不强行把多算子塞进单算子 State 模型。
> **纪律**：遵守 `plan-doc-discipline`；聚焦设计决策，实现留 L4。

---

## 1. 为什么是上层 runner，不是单算子 Workflow 内的 stage

DevKit 的 stage/State 模型为**单算子内的多阶段编排**设计（一个算子的 design→codegen→verify→perf，共享一个 State）。多算子是**任务级并发**（N 个独立算子各跑闭环），超出单 State 范围。强行用 ForkJoinGroup 嵌套会让单 State 承载多算子字段，破坏单算子模型。故多算子调度作为独立 runner（类比 `application/dispatcher.py` 是单算子 run 入口，TrainingRunner 是多算子集入口）。

## 2. 核心组件

```
TrainingRunner（src/，调度级 State + 调度 event-log）
  ├─ 算子集队列（phase0 35 算子）
  ├─ 生成 pool：并发派发单算子生成任务
  ├─ 就绪队列（无 barrier）：生成完 → 评测就绪
  ├─ 评测 pool：并发派发 cann-bench 评测任务
  ├─ NPUSlotManager（01）：统一分卡给生成内部 verify/perf + 评测
  ├─ per-op 隔离目录管理（02 D 方案：per-op opp-dir + python-dir）
  └─ loss 聚合器（04）
```

调度级 State = 算子集进度 + 各算子 loss + epoch + 聚合 loss + 改进记录（04）。调度 event-sourcing 独立于单算子 event-log。

## 3. 单算子任务形态

**倾向 subprocess 起 run（进程级隔离）**：每算子一个 `generate_ascendc` 子进程，独立 State/event-log，CANN/NPU 状态进程级隔离。

- **NPU 分卡**（01 落地）：`NPUSlotManager.acquire()` → 传 `--npu-id <slot>` 给生成 run（verify/perf 已用 `state.npu_id`，无需改 stage 内部）；评测子进程传 cann-bench `--device-id <slot>`。
- **opp/whl 隔离**（02 D 方案）：per-op opp-dir + python-dir，环境变量注入子进程。
- 备选：内嵌调 `dispatch(task_request)`（同进程，线程并发）——共享进程资源争用风险高，倾向不用。

## 4. 与四份方案的衔接

- **01 NPU 隔离**：TrainingRunner 持 `NPUSlotManager`，生成 run（`--npu-id`）+ 评测（`--device-id`）都从它分卡。01 §3.2 的"verify/perf 走 slot"经 `--npu-id` 参数实现（免改 stage）。
- **02 opp+whl 隔离**：评测 pool 按D方案起 cann-bench `--skip-install` + per-op opp/python-dir + `PYTHONPATH`/`ASCEND_CUSTOM_OPP_PATH`。
- **03 框架化**：生成 run 内部用框架化后的 codegen（完整 ACLNN）→ DeployStage → 评测。
- **04 training-time**：TrainingRunner 的外层 epoch 循环 = 04（推理评测→归因→改进）；每 epoch 内调生成+评测 pool 跑全算子。

## 5. 流水线（01 §3.2 落地）

生成与评测**重叠**（资源轴 = LLM-IO vs NPU-计算，01）：一个算子等 LLM 时，NPU 跑别的算子的 verify/perf/评测。生成 pool 并发度受 LLM 限流约束；评测 pool 并发度受 NPU 卡数约束。失败算子（生成/编译失败）→ loss=0，不阻塞其他。

---

## 6. 待定

- 单算子任务：subprocess run（倾向）vs 内嵌 dispatch
- 调度级 State schema（算子集进度 + loss 聚合字段）
- 生成/评测 pool 并发度（LLM 限流 × NPU 卡数）
- 调度 event-sourcing 的事件 schema
