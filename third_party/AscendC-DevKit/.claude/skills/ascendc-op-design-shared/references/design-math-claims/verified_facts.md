# 已核验数学事实库（design-math-claims）

> 设计声称可**引用**本库条目，引用时标注核验日期与方式。新增算子验证结果验证后追加。
> 核验方式说明：穷举 = 全空间枚举；对照 golden = 与 golden/参考实现逐元素一致。

## transpose：单个 2D 转置的覆盖域

- **事实**：单个 2D 转置（contiguous reshape (M,N) + transpose）≡ **循环旋转** `perm = [b..n-1, 0..b-1]`（b=1..n-1）或 identity。
- **覆盖计数**：rank=n 时循环旋转恰 **n** 个；其余 **n!-n** 个 perm 无法用单个 2D 转置表达。
  - rank=3: 3/6 可，3/6 不可；rank=4: 4/24 可，20/24 不可；rank=5: 5/120 可，115/120 不可。
- **核验方式**：Python 穷举 rank 2-5 全空间 + 随机 100 组 (rank 2-6) + 8 个真实评测 shape，对照 `np.transpose`。
- **核验日期**：2026-08-09。脚本：`docs/plan/design-math-claims-verification/verify_transpose_perm.py`。
- **反例**：`[0,2,1,3]`（4D 交换中间两维）、`[4,3,2,1,0]`（5D 全反转）、`[2,1,0]`（3D 反转）均非循环旋转。
- **推论**：设计声称"任意 perm 降维为二元 (M,N)"**不成立**——单次 2D 转置只覆盖循环旋转，其余 perm 需通用算法（见下）。

## transpose：任意 perm 的正确实现路径

- **算法① 两两换维分解**：任意 perm 可分解为 ≤(n-1) 次两两换维，每次 = 一次 strided 2D 转置 pass（多 pass）。
- **算法② 通用 N-D index 映射**：输出 tile 直读 strided 输入（单 pass）：`y[i0..] = x[i_perm[0]..]`。
- **核验方式**：两种算法对照 `np.transpose`，穷举 rank 2-6 + 随机 100 组全一致。
- **核验日期**：2026-08-09。

## 沉淀规则

- 新算子验证通过后：追加条目（事实 + 核验方式 + 日期 + 脚本路径）。
- 引用格式：`引用 verified_facts：<条目>（核验 <日期>）`——`known_limitations`/`support_domain` 里标注引用来源。
