# 技巧：printf 二分定位（就地诊断用）

> 这是 diagnose 就地定位时的一个**可用技巧**，不是独立 phase——**可选参考**，按需取用，
> 不产生 phase 协议（无 bisect_progress / max_rounds / RESULT 行）。**是否使用由你基于对
> 问题的理解判断**（症状指向数值发散 → 用；指向全局算法 → 先全局推演）。

## 何时用

kernel 数值发散、静态分析无法唯一确定根因时——把公式拆成步骤，逐步缩小到首个数值发散点。适合「多 dtype 精度」「Cast/Compare 位序」「中间值错但最终错因不明」类问题。

## 怎么做

1. **拆公式**：把算子数学公式拆成 `formula_steps`（如 Softmax = `[ReduceMax, Sub, Exp, ReduceSum, Div]`；Sinh = `[Exp(x), Exp(-x), Sub, Div]`）。
2. **首轮全步骤插探针**：在**所有顶层步骤**插 printf 探针（单轮覆盖全部步骤，≤ 200 行），build → 跑**当前失败用例**（不跑全量）→ 读 printf 输出 → 与 CPU golden 按相同步骤对比。
3. **缩小范围**：定位到首个可疑步骤 → 在该步骤的所有直接子步骤插探针 → build + 跑当前用例 + 读输出 → 对比 → 继续二分。
4. **退探针**：每轮 `git checkout -- <改过的文件>` 退探针（**探针不入 commit**）。
5. **收敛到行**：重复直到定位到第一个数值发散点（某 API / 某行 / 某中间值）。

## Heisenbug 告诫（必读）

**printf 改变时序 → 失败变 pass**：
- printf 探针的隐式流水线停顿可能掩盖 sync bug（SetFlag/WaitFlag/PipeBarrier 缺失）或未初始化数据（UB 恰好变零）。
- **信号**：插探针后测试从 fail 变 pass，或探针输出显示垃圾值但最终结果正常。
- **处理**：疑 sync 缺失 → 调 `ascendc-sync` skill 查同步；疑未初始化 → 查变量声明/分配是否初始化。**不 commit 探针**。

## 纪律

- **只跑当前失败用例**，禁止全量（探针编译慢 + 改变时序）。
- **commit 前必删探针**——commit 只含逻辑修复。
- 连续 3 次缩小范围无好转 → 放弃二分，改用受控实验（改一处看效果）或检查是否上游/ground-truth 约束问题。
