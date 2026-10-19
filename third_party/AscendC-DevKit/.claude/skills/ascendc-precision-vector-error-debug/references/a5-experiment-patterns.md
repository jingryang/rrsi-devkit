# A5 VECTOR_ERROR 受控实验模式

本文由 `plan_a5_vector_experiments.py` 的 P2 实验计划引用。实验计划是安全
recipe，不是自动 patch；脚本不修改源码、不执行编译/测试/NPU，也不自动回滚。

## 统一安全门

每个实验必须只改变一个诊断因素，并保持：

- 目标 case 和 P0 fingerprint 不变，除非 recipe 明确要求使用受控条件做差分。
- 所有消费者读取已初始化数据；生产者、消费者、参与核集合保持闭合。
- Alloc/EnQue/DeQue/Free、Set/Wait、CrossCore、LocalMemBar 不得只删除或
  绕过单侧。
- 实验前生成目标源码 SHA256 manifest；实验只允许修改 plan 声明的目标源码，
  实验后只反向应用本实验局部 patch，再由 guard 验证 hash。若闭合实验需要改
  另一源码文件，必须 defer 并重新生成显式包含该文件的 plan。禁止
  `git reset/checkout` 或覆盖整文件回滚。
- 原 fingerprint 是唯一错误身份；日志正文和路径只作为审计证据。

只有以下条件全部成立，结果才可用于推理：

1. 未修改源码时复现 baseline；
2. 单变量和全部不变量经执行者明确确认；
3. build passed、目标 case run completed；
4. outcome 为 `same_error` 或 `error_disappeared`；
5. 执行记录声明已回滚，且 guard 计算的源码 SHA256 恢复；
6. 回滚后重新运行目标 case，并再次观测到 P0 原 fingerprint。

`different_error/compile_fail/not_reproduced/not_run` 或 rollback 失败均无效。
`error_disappeared` 只能得到 `suspect_root`，仍需恢复后再次复现原错误，才能进入
行级确认。

## `transport_address_bounds_probe`

适用：`gm_ub_transport/address_generation`。

- 保持完整 GM/UB producer-consumer 链，只安全缩小目标 tile/burst/repeat，
  或替换成同 dtype/layout、容量正确、已初始化且有有效消费者的诊断 buffer。
- 禁止裸删 DataCopy/Load/Store。
- 若现有 harness 支持，使用
  `regbase-vf-test/SingleOperatorLaunch/diagnostics.py` 的 sentinel guard 和
  unchanged-output 检查，或显式配置 memcheck。planner 本身不访问设备。

## `vf_load_compute_store_isolation`

适用：`ub_reg_load_store/vf_call_abi`。

- 首选保留 Load/Store，只将 Compute 替换为 lane/layout 等价的 identity。
- 隔离 Load 或 Store 时，必须提供完全初始化的 UB/RegTensor 占位，保持 mask、
  lane、dtype、LoadDist/StoreDist、PostUpdate 和下游覆盖。
- 不得通过破坏 VF_CALL ABI、GetPhyAddr provenance 或让 Store 使用未初始化寄存器
  来制造“错误消失”。

## `mask_tail_boundary_matrix`

适用：`mask_tail`。

- 优先运行已有合法 case 做 aligned 与 `VL-1/VL/VL+1` 差分；VL 必须按当前
  dtype 和目标 CANN/SoC API 查证。
- 受控 all-valid mask 仅用于已证明 padding/分配覆盖所有激活 lane 的诊断。
  未证明安全时禁止规划/执行。
- 如检查 UpdateMask，只改变目标 row/tile 层的 counter reset，不同时修改
  dtype、Store mask 或地址推进。

## `layout_equivalent_control`

适用：`layout_cast_dist`。

- 必须先提供目标 SoC/CANN 文档支持的 lane-for-lane 等价证明。
- 保持 dtype、逻辑 lane 顺序、mask 和地址推进完全一致。
- 无等价证明时 planner 将候选标为 blocked/deferred，不生成“试着换一个
  LoadDist/StoreDist/CastTrait”的危险实验。

## `sync_buffer_core_differential`

适用：`incore_sync/queue_lifecycle/crosscore_tscm`。

- 仅使用调用方显式提供的控制参数做差分；不得临时猜测或拼装控制参数。
- intermittent 错误先在完全相同配置下重复目标 case，记录原 fingerprint 频率。
- 代码隔离必须覆盖一条完整生产消费链和所有参与核。
- 禁止删除、绕过或单独移动 Set/Wait/LocalMemBar/CrossCore/queue endpoint。

## `tiling_boundary_case_matrix`

适用：`tiling_boundary`。

- 优先使用已有合法的 zero/one/tail/last-core/last-repeat case，不改 kernel。
- 若必须增加 zero-work guard，只隔离已经证明为空的工作分支；所有核必须参与的
  同步仍须执行。

## 执行记录最小格式

```json
{
  "id": "a5ve-...",
  "outcome": "same_error",
  "baseline_reproduced": true,
  "single_variable_verified": true,
  "invariants_verified": true,
  "changed_files": ["kernel.cpp"],
  "build": {"status": "passed", "evidence": "build log path"},
  "run": {
    "status": "completed",
    "evidence": "target-case result path",
    "original_error_observed": true,
    "observed_fingerprint": "a5-vector-v1|..."
  },
  "rollback": {
    "verified": true,
    "baseline_reproduced": true,
    "observed_fingerprint": "a5-vector-v1|...",
    "evidence": "restored target-case result path"
  }
}
```

outcome 只能是：
`same_error/error_disappeared/different_error/compile_fail/not_reproduced/not_run`。
执行记录中的 `rollback.verified=true` 只是声明，最终仍以 guard 重算的 SHA256
为准。`same_error` 的 run fingerprint 必须等于 P0 fingerprint；
`error_disappeared` 必须显式记录未观测到原错误。两者都必须在回滚后再次复现
原 fingerprint，结果才可用于推理。
