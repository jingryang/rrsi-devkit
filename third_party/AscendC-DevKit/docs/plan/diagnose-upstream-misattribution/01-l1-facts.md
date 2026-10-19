# L1 — diagnose 归因误判（20260823 unique 批）客观事实

> 四层方案体系 L1：只记录客观事实（哪里坏了、凭什么这么说），不提方案、不排顺序、不写决策。
> 归属：precision_debug 阶段。溯源批：20260823-125944-7d3451（execution 20260823-125944-390892，unique 算子）。

## 事实 1：批最终 halt 在 precision_debug 的 upstream 上报，算子未交付

- 首跑被 SIGKILL（137，NPU 0 Alarm + devmm 泄漏 + 265 zombie 进程），resume 后正常跑到 halt。
- resume 最终状态：`0/1 workflow-done, 0/1 eval-passed, [FAIL(exit 65)]`。
- halt reason（批日志原文）：`deploy: runtime 加载系统 OPP 路径下的旧 kernel(01:38, 无 ShiftF32 修复)，workspace per-op 部署 kernel 未被加载；已实证：把修复后的 workspace kernel .o 复制到系统 OPP 后 507035 崩溃消失。强制 ASCEND_OPP_PATH=workspace 报 561000`。
- 即：diagnose 上报 `upstream_signal=true` + `upstream_stage=deploy`，框架 halt。

## 事实 2：diagnose 修好了 kernel 崩溃 bug（ShiftF32 对齐），实证有效

- 根因：`ShiftF32()` 里 `Duplicate(dst[n-j], 0.0f, j)` 在 `j*4%32!=0`（j=1/2/4）时未 32B 对齐 → vector core exception 507035（"UB address accessed by VEC instruction is not aligned"）。
- 修复：改标量 for-loop。iter-2 起单用例 kernel_done 正常（391.1ms），不再崩溃。

## 事实 3：修复后单用例失败原因是"输出为空"，非 deploy

- iter-2..7 单用例 result.json：`output_0（y）total_count=0`，error_msg 原文：
  `形状不匹配: output=torch.Size([0]), golden=torch.Size([19058])`
- kernel_first10: `[]`（kernel 输出空），golden_first10 有值（如 `[-1.0, -0.9995...]`）。
- golden 返回 `(y, inverse)` 两个输出：y=唯一值数组（应 19058 元素），inverse=逆索引。
- 即：kernel 修复后不再崩，但 y 输出 shape [0]（空数组），golden 期望 [19058]。

## 事实 4：iter-2 时 runtime 实际加载了修复后的 kernel（per-op 隔离生效）

- iter-2 run.log：`cann_bench.__file__ = .../artifacts/per-op/unique/python/cann_bench/__init__.py`（workspace per-op 路径）。
- iter-2 不崩（修复生效）而系统 OPP 当时还是 01:38 旧版（无修复）——若 runtime 加载系统 OPP 旧版应仍崩。
- 推论：runtime 通过 ASCEND_CUSTOM_OPP_PATH 加载了 workspace 修复版，per-op 隔离生效。
- 但 workspace per-op 部署目录创建时间 09:53:58，iter-2 是 09:26——deploy 时间线复杂（diagnose 反复 redeploy），此推论的完全确认需进一步证据。

## 事实 5：diagnose 的 upstream 上报基于"系统 OPP 有 stale kernel"观察，与当前失败无关

- diagnose 观察到系统 OPP vendor 路径有 Aug 24 01:38 的旧 unique kernel（无 ShiftF32 修复）。
- 该观察是**真事实**，但 iter-2 证明 runtime 实际加载 workspace 修复版（不崩）。
- 真根因（y 空输出）是 kernel 输出逻辑 bug，与 stale OPP 无因果。
- diagnose 未消费 iter-2 result.json 的 error_msg（"形状不匹配 output=[0] vs golden=[19058]"），转而依赖 stale OPP 假设。

## 事实 6：诊断产物记录

- precision_diagnose_r001_p001.json：`root_cause` 指 ShiftF32 对齐；`upstream_signal=false`（首版）→ 后续更新为 true。
- control.json history：run_tests（20/20 failed）→ diagnose（aborted）→ diagnose（symptom 507035）。
- diagnose 中途 abort 过一次（`{'aborted': True}`）。

## 未决问题（本层不回答，留 L3）

- 该误判是否 P3 重构引入（重构前 diagnose 是否也会误判）？
- 是否存在其他形式的误判（系统性模式）？
- precision_debug 阶段设计是否有问题（方法论对"形状/空输出"失败缺指引）？
