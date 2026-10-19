# SIMT host tiling 未引导 Dynamic UB 配置 — 问题记录（L1）

> 事实快照（2026-09-02）。只陈述"哪里坏、凭什么"，不提方案不排序。决策见 `02-analysis.md`，改动见 `03-impl.md`。

## P1：skill 知识层教的是已废弃的配置接口名

- **现象**：`ascendc-simt-operator-design-patterns` 多篇参考把 SIMT host 共享内存配置写成 `context->SetLocalMemorySize(ubSize - DCACHE_SIZE)`，未标注：
  - 该接口是**同函数废弃名**，现接口为 `SetDynUBufSize`；
  - API 语义是"SIMT 算子设置所需 **Dynamic Unified Buffer** 大小，**默认 0 = 不声明**"。
- **证据**：
  - CANN 9.1.0 头文件 `/usr/local/Ascend/cann-9.1.0/aarch64-linux/include/exe_graph/runtime/tiling_context.h`：`SetLocalMemorySize` 标注 `@deprecated 即将废弃，改用 SetDynUBufSize`，函数体 `return SetDynUBufSize(local_memory_size)`（纯 wrapper）；`SetDynUBufSize` 注释"设置 dynamic unified buffer size, 默认值为0"。
  - skill 内命中：`SKILL.md` 决策速查、`references/workspace-contract.md §3`、`references/shared-memory.md`、`references/data-movement.md`、`references/dev-experience.md`、`kimi_simt_strategy.md` 教学格（均只写旧名或旧新混用）。
  - 知识库 API 文档 `ascendc-dev-knowledge/.../TilingContext/SetDynUBufSize.md` / `SetLocalMemorySize.md`：已载明上两条语义（本仓正确知识存在，但未被 simt skill / 设计编码链引用）。

## P2：设计/编码链的 SIMT host 配置引导缺位（生成代码漏配隐患）

- **现象**：
  - `ascendc-op-tiling`（SIMT 路由段 §0.5）、regbase 编码 host tiling 自检（`ascendc-op-dev-coding-regbase/references/per-substage-selfcheck.md §B2`）均无 "SIMT host 必配 Dynamic UB" 引导 → 照流程推导/编码不会主动写该配置。
  - 历史生成的完整算子（真实生产 gather，`cann-bench-batch/.../csrc/ops/gather/op_host/gather_tiling.cpp`）host tiling **无任何 Dynamic UB 声明**，SIMT VF 直访 GM；能过是因为单批 UB buffer ≈4KB、远小于运行时 SIMT 共享内存窗口（默认兜底窗口）。大共享 buffer 或 DCache 需要预留的场景属"未配置即潜在越界"。
- **证据**：
  - gather_tiling.cpp 全文件无 `SetDynUBufSize`/`SetLocalMemorySize`（只设 blockDim/workspace）。
  - 对照：主线仓 `ops-nn`（`/home/g00944280/code/ops-nn/index`）**92 处 arch35 SIMT tiling 全量调用** `context->SetLocalMemorySize(...)`（如 `gather_v2/op_host/arch35/gather_v2_tiling.cpp:938` 仅 SIMT 模式调用、`DCACHE_SIZE=128K`，SIMD 模式不调；`index_fill/.../index_fill_tiling_simt_dense_indices.cpp:140`、`segment_sum/..._simt_tiling.cpp:86`、`scatter_elements/..._base.cpp:521`、`unsorted_segment_sum/..._simt_tiling.cpp:63` 等），是主线 A5 SIMT 算子的标准 host 动作 → "host 调用生效、缺了会错" 的强反证。
  - 官方模型与 launch 语义：RTS SIMT 共享内存窗口由 launch 期动态共享内存决定（`simt_share_memory_size` / `dynamic_share_mem_size`；SingleOperatorLaunch 默认 0 → 8KB 兜底，可放大）——见 `simt-ub-window-misconception` workdir 设备实测。

## P3：isolated VF 测试工具（SingleOperatorLaunch）不暴露窗口放大参数

- **现象**：regbase-vf-test 的 `SingleOperatorLaunch/source_module.py` 构造 `LaunchKernelArgs(...)` 时不传 `simt_share_memory_size`（`__call__` 主路径与 `profile` 主循环两处），`_KernelFunction.__call__` / `profile` / `SourceModule.__call__` 签名均无该参数 → isolated VF 测试**只能拿到 RTS 兜底默认窗口**（实测 8KB），需放大 SIMT 共享内存窗口的 `__simt_vf__` 单测无公开途径。
- **证据**：`source_module.py` L443/L550（改动前）`LaunchKernelArgs(func_or_binary_hdl=..., op_args=..., block_dim=..., mix_kernel=..., tiling_data=...)` 无该字段；`ttk.core_modules.runtime.rts_structures.LaunchKernelArgs.simt_share_memory_size: int = 0`（默认 0）；此前探针必须绕过 SourceModule 低层手工构造 `LaunchKernelArgs(simt_share_memory_size=...)` 才能放大（`/tmp/opencode/simt_ub_probe/run_ub_probe.py::launch_with_simt_share_mem`）。
- 影响：simt skill 知识层已写"可放大"，但 isolated VF 测试环节实际做不到（工具缺口）；单测若隐含 >8KB 共享 buffer 会静默按 8KB 窗跑出 VEC_ERROR/错位，难诊断。

## 说明

- 本 workdir 承接 `simt-ub-window-misconception`（窗口机制事实）的"生成代码应如何配置"一问：机制事实见彼处 L1/L3/L4；此处记录"skill 知识层接口名过时 + 设计/编码链引导缺位 + VF 测试工具不暴露窗口参数"三类问题。
