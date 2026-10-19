# Codegen 连续子阶段调度合并方案

> 状态：冻结

## 1. 目标

减少同一实现职责内的上下文重建，同时保留细粒度子阶段的自检、审计、失败归属和
断点恢复。VF 精度验证与 S5 编译部署继续独立。

## 2. 方案比较

### A：直接删除细粒度子阶段

调度简单，但会丢失逐步骤 selfcheck/progress、精确失败点和中间恢复能力，不选。

### B：复用 `checkpoint_group` 直接批量执行

改动较小，但现有分组是上下文分类，无法表达 4.0+HOST、Kernel 基础/收尾分割、
API+LAST，且会混淆两个不同职责，不选。

### C：保留 sub-stage，新增 execution_group（选择）

`sub_stages` 继续作为质量与审计原子；S2 为每个非 VF 步骤声明
`execution_group`。框架一次调度同一 execution_group 的连续 pending 前缀。
`kind=vf` 无条件作为单例工作单元。

典型分组：

- `host_tiling`：4.0/A/B1/B2
- `kernel_base`：C.0/C.1/C.2
- 每个 VT：独立
- `kernel_finalize`：VF 集成与 Kernel 收尾
- `finalize`：API/Plugin/E/F

组名不绑定固定阶段编号；S2 可按实际计划产生 `kernel_finalize_2` 等连续且唯一的组。

## 3. 完成与失败协议

Agent 仍对组内每个子阶段逐一执行既有 Phase 0/1/2 和 selfcheck。RETURN 增加机器可读
`completed_sub_stages`：

- COMPLETED：应等于本次授权工作单元的完整列表。
- PARTIAL/FAILED：可包含从工作单元起点开始的连续已完成前缀，并声明失败点。
- 框架只接受授权列表内的连续前缀；越界、乱序或跳项不推进状态并暂停。
- 无 RETURN 的 backend 兜底只推进一个子阶段，不能猜测整组完成。
- `next_sub_stage` 只作审计，下一工作单元由计划状态确定性计算。

## 4. 质量边界

- 不删除任何 sub-stage、自检文件或 Stage 4→5 完整性门。
- VF Agent 一次仍只验证一个 VF。
- S5 编译、部署、smoke 门保持独立。
- 分组只减少会话启动和重复读取，不压缩单个子阶段的自检内容。
- malformed/missing `execution_group` 消费端安全降级为单步骤调度并告警，避免错误合并。
