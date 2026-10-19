# L1 设计阶段数学声称验证缺失（2026-08-09 取证）

> 触发事件：20260808 批 transpose 算子 precision 20/20 全过，但 cann-bench 评测 `overall_score=0.0`。
> 本 L1 只记录客观事实（哪里坏、凭什么这么说），不提方案、不排顺序、不写决策。
> 与 `precision-report-rendering`（报告渲染 bug）**相互独立**：本文是"设计-codegen-debug 能力缺口"，归算子侧 + 设计/编码 skill + 框架 B8。

---

## 触发事实：transpose 评测 0 分

- `cann-bench-batch/20260809_002130/transpose/reports/transpose_eval_20260809_035946.json`：`passed_cases=20/20, pass_rate=1.0`（精度全过）但 `overall_score=0.0`。
- 逐 case：8/20（transpose_1/6/12/13/14/15/16/20）`accuracy.passed=true` 但 `performance_error_msg="未检测到 NPU 算子执行，疑似 CPU fallback，反作弊触发。"`，`score_error_code=no_npu_kernel_detected`。
- 根因链（已逐层实证）：
  1. **需求/golden 域**（`artifacts/requirement/requirement.json`）："对 tensor 的任意维度进行调换"，rank 1-8，golden=`torch.permute`——覆盖任意 perm。
  2. **设计声称**（`artifacts/staging/design_spec.json`）："host 侧将**任意 perm 降维为二元 (M,N)** 抽象后传 kernel"。
  3. **数学实证**（Python 穷举 + 随机核验，脚本 `verify_transpose_perm.py`）：**单个 2D 转置 ≡ 循环旋转 `[b..n-1,0..b-1]`**，rank=n 时只 n 个 perm 可表达（rank=4: 4/24，rank=5: 5/120）。8 个评测失败 perm（`[0,2,1,3]`/`[0,2,3,1]`/`[0,3,1,2]`/`[0,1,3,2]`/`[4,3,2,1,0]`/`[2,1,0]`）**全部非循环旋转**——设计声称"任意 perm 降维为 2D"数学上不成立。
  4. **tiling 实现**（`op_host/transpose_tiling.cpp:73-74, 164-177`）：`ReducePermTo2D` 只认 identity + 单一 2-block-swap；非可约 perm 走 `isIdentity` flat-copy（输出==输入），作者注释"design limitation, Option A" + `OP_LOGW`，但 WARN 无人消费，照样产出错误输出。
  5. **debug 修复**（commit `605af87`）：插件层 host CPU `torch.permute` 兜底（"correctness over speed"）→ precision 绿、评测反作弊 0 分。
- 佐证：transpose_10 perm=`[2,0,1]` 是循环旋转（b=2）→ 跑在 NPU、未进 CPU-fallback 名单（数学分类与实测一致）。

---

## 问题清单

### D1 设计缺少"化简/降维/等价"声称的数学验证机制
- **symptom**：设计 agent 可自由书写数学声称（如"任意 perm 降维为二元 (M,N)"）而无需任何验证，声称与实际不符时静默通过。
- **evidence**：
  - 设计 skill 树（`ascendc-op-general-design` / `-template-division` / `-tiling-*` / `-design-*`）**零 Python 脚本**，自检表无"化简声称须验证"项。
  - `general_design_template.md` 中 python 仅为 golden 函数 prose 模板，不执行。
  - `ascendc-op-design-anchor-per-template` 只做"硬件 API 能力对质"（claim_type==hardware_api_capability），**无数学可行性/域覆盖 claim 类型**。
  - transpose 的"任意 perm 降维为 2D"即未验证的数学声称，实测为假。
- **status**: ❌未修

### D2 设计不声明"支持域"、与 golden 域无对质
- **symptom**：设计产物无结构化"支持域"声明；需求(golden)域 ⊄ 实现域时静默发生，无信号。
- **evidence**：
  - `design_spec.json` 有 attrs/description，无 `support_domain` 类字段（§2.10 结构化缺位）。
  - transpose：golden 域=全部 perm，设计实现域=循环旋转，缺口从设计到评测一路静默。
  - §1.13 golden 是权威，但设计没有"以 golden 域为锚声明自己支持域"的动作。
- **status**: ❌未修

### C1 codegen 无"设计支持域 vs golden 域"对质
- **symptom**：codegen 忠实消费设计产物，不核对设计的域声明是否覆盖 requirement/golden 域；设计降域被原样继承进 kernel。
- **evidence**：transpose codegen 继承 2D-only 限制（kernel 只支持循环旋转）；codegen 无 requirement 域 vs design 域比较步骤。
- **status**: ❌未修

### B1 debug 域缺口识别缺失 + fallback_masked 未落地
- **symptom**：debug 把"kernel 支持域外"的失败当普通 kernel bug 修，用 host 兜底制造 precision 假绿；`fallback_masked` 字段存在但框架零消费。
- **evidence**：
  - 605af87 插件 host CPU permute 兜底未标 fallback_masked（fix/printf 历史无该字段）。
  - `grep -r "fallback_masked" src/` **零命中**（仅 `tests/ut/adapters/test_schema_loader.py:83` 引用）——与框架审计 20260809 **B8** 同一条。
  - unique 同源先例：host `at::_unique2` CPU 兜底制造 20/20 假绿（memory `unique-codegen-scalar-collapse` P2）。
- **status**: ❌未修（B8 挂靠）

### T1 transpose 算子侧：kernel 只支持循环旋转 + host 兜底
- **symptom**：kernel/tiling 只支持 2-block-swap perm，其余落 host CPU；评测 8/20 case 反作弊 0 分。
- **evidence**：见触发事实链；`transpose_plugin.cpp:63-81`（`IsKernelSupportedPerm` 不匹配 → `x.cpu().permute()`）。
- **status**: 🔄源头已修（Phase 4，2026-08-09），产物重生成待后续——见 `03-impl.md` §9 Phase 4 执行记录

---

## 数学事实基线（L1 证据，已 Python 核验）

1. 单个 2D 转置（contiguous reshape (M,N) + transpose）≡ 循环旋转 `perm=[b..n-1,0..b-1]`。
2. rank=n 时循环旋转恰 n 个（identity + b=1..n-1），其余 n!-n 个 perm 需通用算法。
3. transpose 20 个评测 case 中 8 个非循环旋转 perm（与 CPU-fallback 名单一一对应）；transpose_10 `[2,0,1]` 是循环旋转（与 NPU 实测一致）。
4. 两种通用正确算法已核验（穷举 rank 2-6 + 随机 100 组 + 8 真实 shape，对照 `np.transpose` 全部一致）：
   - 算法①：任意 perm 分解为 ≤(n-1) 次两两换维，每次 = 一次 strided 2D 转置 pass（多 pass）。
   - 算法②：通用 N-D index 映射（输出 tile 直读 strided 输入，单 pass）。
