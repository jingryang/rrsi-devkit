# Phase 4 起始提示词（transpose 通用 N-D 转置 kernel）

> 用法：把下面的提示词块整个粘贴到新 session 的首条消息。新 session 无需本对话上下文，提示词自包含。

---

## 起始提示词

你在 AscendC-DevKit 仓 `/home/x00584171/code/AscendC-DevKit`（分支 v0.2.0，环境 Linux aarch64 + CANN 9.1.0-beta.3 + Ascend910B3）。继续 **Phase 4：让 transpose 算子的 AscendC kernel 支持任意 perm，删除插件 host CPU 兜底**。

### 背景（已完成上下文，两个 commit 已落库）
- `8d72745f`：设计化简声称验证机制三层防线（设计自检 + codegen 域对质 + debug fallback_masked）
- `a03a3221`：precision_report.md 渲染修复
- 待办：transpose 评测 0 分的根因 = kernel 只支持"循环旋转"perm，非循环旋转 perm（8/20 评测 case）走插件 host CPU `torch.permute` 兜底 → 评测反作弊 `no_npu_kernel_detected` → 0 分。precision 却 20/20 全过（host 兜底数值对）。

### 先读这些文档（再动手）
1. `docs/plan/design-math-claims-verification/01-problems.md`（L1 事实 + 数学基线 + 根因链）
2. `docs/plan/design-math-claims-verification/02-analysis.md`（L3 §T1 算法选型：算法②主 / 算法① fallback）
3. `docs/plan/design-math-claims-verification/03-impl.md`（L4 §5 transpose 落地步骤）
4. `docs/plan/design-math-claims-verification/verify_transpose_perm.py`（数学验证脚本，先复跑确认结论）
5. `.claude/skills/ascendc-op-design-shared/references/design-math-claims/`（新机制：claim-verification-checklist / verify_simplification_claim.py / verified_facts.md）

### 数学事实（已 Python 穷举核验，脚本可复跑）
- 单个 2D 转置（contiguous reshape (M,N)+transpose）≡ 循环旋转 `perm=[b..n-1,0..b-1]`；rank=n 恰 n 个 perm 可做（rank=4: 4/24，rank=5: 5/120）。
- 8 个非循环旋转评测 perm：`[0,2,1,3]`,`[0,2,3,1]`,`[0,3,1,2]`,`[0,1,3,2]`,`[4,3,2,1,0]`,`[2,1,0]`。
- 正确实现路径（均已对照 `np.transpose` 核验）：
  - **算法②（推荐）**：通用 N-D index 映射 kernel——输出 tile 直读 strided 输入，单 pass。`y[i0..in-1] = x[i_perm[0]..i_perm[n-1]]`。
  - **算法①（fallback）**：任意 perm 分解为 ≤(n-1) 次两两换维，每 pass = strided 2D 转置（多 pass，可复用现有 2D 转置思路）。

### 目标
1. 设计：transpose `design_spec.support_domain` = 全部 perm（rank 1-8，perm 为 [0..n-1] 排列）。
2. kernel/tiling：实现算法②（若②的 tiling 复杂度不可控则算法①，记录取舍）。
3. 插件：删 `IsKernelSupportedPerm` host 兜底分支（`op_plugin/transpose_plugin.cpp:63-81`），全 perm 走 `ACLNN_CMD(aclnnTranspose, ...)` 真 kernel。
4. 验证：precision 20/20（kernel 真跑）+ cann-bench 评测非 0 分（无 CPU-fallback 反作弊）。

### 原则（必须遵守）
- **§1.13 Golden 权威**：kernel 行为对齐 `torch.permute`；正确性第一。
- **正确性优先 + 正确性内尽可能好性能**（性能优化有专门 stage 未实现，不越级做性能 stage）。
- **用新机制**：设计声称必须 Python 验证（对照 golden，用 `verify_simplification_claim.py` 骨架）；脚本跑不通先 agent 内部多轮自修，多次后仍不行标 `known_limitations` 继续，**不 halt**。
- §1.12 不认算子名，判据用结构信号（perm 类型学）。
- TDD（§3.1）；全量 UT + ST 不回归（§3.2）。
- 环境先 source CANN set_env（cann-9.1.0-beta.3）；查 `ascend-hardware` skill 获取硬件参数（UB 大小/核数/对齐）。

### 环境
- transpose 算子仓：`/home/x00584171/code/cann-bench-batch/20260809_002130/transpose`（HEAD=59abb23；precision 修复链 be17c2c→605af87→be4857e→6969dd0→59abb23，605af87 是待删的 host 兜底）
- 算子代码：`examples/aclnn_launch_example/csrc/ops/transpose/`（op_kernel / op_host / op_plugin / op_api）
- 评测报告：`.../reports/transpose_eval_20260809_035946.json`（8/20 `no_npu_kernel_detected` → 0 分，精度 20/20）
- precision_debug 20 个用例与评测同源（cases_source=cannbench，10 fp16 + 10 bf16）；20 个 perm 见 `docs/plan/design-math-claims-verification/01-problems.md` 或 `test_cases.json`
- 算子是 A3（用户 owns A3 codegen + 全部 design；A5 regbase 不在此范围）

### 验收
- transpose precision_debug 20/20（kernel 真跑，非 host 兜底）
- cann-bench 评测：8 个非循环旋转 case 真跑 NPU，`no_npu_kernel_detected` 消失，评分非 0
- 全量 UT/ST 不回归（`pytest --quick` 跑 UT；NPU ST 用真实环境）
- 实现中若用算法①，在 L1/L3 记录取舍理由（tiling 复杂度 vs 性能）

---

## 附：给新 session 的核查清单（读完文档后自检）
- [ ] 已复跑 `verify_transpose_perm.py` 确认数学结论
- [ ] 已读 tiling 现状 `op_host/transpose_tiling.cpp`（ReducePermTo2D + isIdentity 退化）
- [ ] 已读 kernel 现状 `op_kernel/transpose.h`（CopyIn/CopyOut）
- [ ] 已读插件现状 `op_plugin/transpose_plugin.cpp`（IsKernelSupportedPerm host 兜底）
- [ ] 已按 design-math-claims 机制给设计加 support_domain + 验证
- [ ] 已确认 8 个非循环旋转 perm 的 shape/dtype（用于 kernel 单测）
