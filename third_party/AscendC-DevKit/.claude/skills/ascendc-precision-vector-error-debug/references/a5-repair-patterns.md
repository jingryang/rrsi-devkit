# A5 VECTOR_ERROR 修复模式

本文供 P3 `plan_a5_vector_repairs.py` 生成和复核 repair intent。repair plan
不是 patch；脚本不修改源码、不 build/run/NPU、不读取全局日志。

## P2 根因门禁

只有同一个 experiment 同时满足以下条件才可规划修复：

- outcome 为 `error_disappeared`；
- P2 `valid_for_inference/root_cause_confirmation_allowed=true`；
- P2 全部门禁为 true，尤其是
  `outcome_fingerprint_consistent`、`changed_files_within_scope`、
  `rollback_verified` 和 `rollback_original_fingerprint_reproduced`；
- validator 的 SHA256 rollback 为 true；
- 原 experiment record 证明修改态未出现原 fingerprint，恢复后又观测到
  P0 原 fingerprint。
- Step 4 `located_root` 与同一 experiment/file/line/fingerprint 绑定，
  `confidence=confirmed`，并显式证明 baseline、消失、恢复复现和 A5
  invariants 四项行级确认门禁。

P2 runtime case、buffer/core 差分只证明因素相关，不自动等于具体行根因。
静态 `candidate/suspected` 只能提供 rule/API 上下文，不能提升为 confirmed。

## 通用修复规则

- 只修 P2 动态证据锚定的 file/line/API 及同文件最小依赖闭包；需要新增文件时
  defer 并重新规划。
- 不保留 identity、清零或安全 buffer 等实验占位代码。
- 保持 RegTensor/VF Load→Compute→Store、地址映射、active lanes、队列和
  producer-consumer 完整。
- API/SoC/CANN 证据必须记录 `target/soc/cann_version/doc/source/version/
  claim`。所有 A5 API 修复均须对目标 910D 和当前 CANN verified 后才可执行。
- 禁止凭摘要硬编码 alignment、VL、dtype、Dist/PostUpdate 或 event 结论。
- 保存 repair-local reverse patch/restore artifact；禁止 `git reset/checkout`。

## Subtype 意图

- `gm_ub_transport`：修正已证明的 GM/UB source、destination、length、stride
  或 tail bound，保持 DataCopy/TQue 完整链。
- `address_generation`：修正 AddrReg/index/stride/整数宽度或指针推进；元素单位
  以当前 API 查证。
- `ub_reg_load_store`：修正 UB↔RegTensor Load/Store、Mask/AddrReg、
  LoadDist/StoreDist 或 PostUpdate 契约，不能破坏 Load→Compute→Store。
- `vf_call_abi`：修正 inline void/POD pointer、GetPhyAddr 或 SIMD/SIMT
  callee 域，不改变 VF 计算语义。
- `mask_tail`：修正 MaskReg dtype/active lanes/UpdateMask reset scope；禁止
  未证明 padding 时强制 all-valid。
- `layout_cast_dist`：只采用 910D/CANN 已验证的 CastTrait、Dist 和 lane
  layout restoration；未 verified 必须 deferred。
- `incore_sync`：只修已证明的 RAW/WAR/WAW 和 LocalMemBar pipeline 方向，
  不用全局串行化掩盖问题。
- `queue_lifecycle`：恢复完整 Alloc→EnQue→DeQue→Free 和 buffer ownership。
- `crosscore_tscm`：修正核角色、Set/Wait、event identity/count 和 TSCM/L1
  可见性；保持所有参与核分支对称。
- `tiling_boundary`：修正 zero/one/tail/last-repeat/last-core，zero-work 核仍
  参加强制同步。

## 修复回验

至少连续两次运行原 case，每次都必须：

- 完成运行且有证据；
- 未观测到原 fingerprint；
- 未出现 different device exception。

此外，plan 中状态为 `ready` 的已有 aligned/tail、zero-one、last-core、
必须有一致的验证结果支撑，不得臆造结论。
缺少已有 case/control 时矩阵项保持 deferred，不得臆造命令。

修复记录还必须证明：

- build passed 且有日志；
- changed scope 与 plan 同文件锚点/最小依赖闭包一致；
- A5 invariants 经复核；
- API verification 与 plan 一致且 verified；
- rollback/restore artifact 完整。

全部满足才允许 `repair_verified=true` 和 VECTOR_ERROR fixed。修复后出现普通
数值精度失败不否定 VECTOR_ERROR 已清除，只写入 `next_hint` 并回到后续精度流程。
