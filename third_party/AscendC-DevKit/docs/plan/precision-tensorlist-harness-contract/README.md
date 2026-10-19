# foreach/TensorList 算子 precision_debug 入口卡死（P1/P2/P3）

> **状态**：L1/L3/L4 已产出，**已实施并验证**（2026-08-08，`tests/ut` 全量 --quick 3544 passed 0 failed）。
> **发现运行**：`output/foreachnorm/`（self_evolve_op 批跑 `20260807-144939-310314`，foreach_norm）。

## 一句话

foreach 算子（`Tensor[]` 输入）进不了 precision_debug：requirement 把 TensorList 输入误标
`param_type=REQUIRED`（应 DYNAMIC）→ runner 的 DYNAMIC 放行分支永不触发 → 20/20 用例在
PD-CONTRACT 处中止、harness 一个不跑 → upstream halt；中途叠加 `max(real_errs)` 不滤 None 的
TypeError（P1）与顶层 halt 消息误用 last_error（P3），把真实契约原因掩盖成"实现 bug"。

## 三件套导航

| 层 | 文件 | 回答 |
|---|---|---|
| L1 | [`01-problems.md`](01-problems.md) | 哪里坏了？凭什么这么说？（P1 transition 崩溃 / P2 契约不一致 / P3 消息误导） |
| L3 | [`02-analysis.md`](02-analysis.md) | 有哪些选项、选了哪个、为什么？（P1 滤 None；P2 源头派生 is_list→DYNAMIC + PD-CONTRACT hint；P3 __halt__ 语义原因优先） |
| L4 | [`03-impl.md`](03-impl.md) | 改哪个函数、什么顺序、怎么验证？（6 步已实施：W4 relay / P2 派生 / P2 hint / W3 正则 / P1 滤 None / P3 消息；新增 9 UT，全量绿） |

## 与既有工作的关系

- [`precision-scope-upstream-halt-eval-loss/`](../precision-scope-upstream-halt-eval-loss/)：
  「upstream → 整 run 终止」的**评分丢失**问题（kernel 已对但 0 评分）。本包是同一路由下的
  **入口契约**问题（harness 一个用例都不跑）。正交，不重复产权。
- W3（m.def 正则假阳性）/ W4（codegen 阶段 smoke 假阴性）为相邻低优先项，另述，不在本包主修。

## 索引挂载

`docs/plan/00-status-summary.md` 与 L2 总纲为共享文件，并发期保守起见不主动改动；本工作子目录
已就绪，待统一挂载。
