# L4 实施方案：codegen 迭代预算 A3/A5 统一为 40（F10）

> 对应问题：F10（各 stage 重试预算与失败模式不匹配）。
> 用户决策（2026-08-21）：A3/A5 统一 40（"A3 和 A5 能不能用同一个计数，可以
> 用 40 覆盖 1000"）。

## 一、F10 主诉已被 F3/F5/F8 结构性解决

L1 的"预算只表达试几次、不表达试完怎样，不可修复失败硬耗"——策略维度已逐个
落在具体失败模式处置（F3 孤儿搬回、F4 fresh 退化、F5 空跑熔断、F8 窗口升级），
属失败产权方（§1.10），不集中在一个预算对象。

## 二、残留修复：双层预算字段语义冲突 → 统一 40

原：Membase 迭代上限 / build-retry 均 1000，Regbase 类默认 40——同 stage 两套
语义（40 vs 1000），且 build-retry 注释自述"Both aligned to 1000"。

统一 40（A3/A5 同一计数）：
- `codegen.py`：`default_max_iterations = 40`（恢复单一字段，含 Regbase 兜底）；
- `orchestration-config.json`：`iterations.stages.codegen: 1000 → 40`、
  `codegen.build_max_retries: 1000 → 40`（保持 build-retry ≤ 迭代上限约束）。

## 三、行为变化披露

- Membase build-retry 从 1000 → 40：极端"编译地狱"场景 40 轮后**提前 D4 逃生**
  （carry smoke_passed=False 交下游，不 halt）而非拖到 1000。正常场景无感
  （build-retry 每轮有确定性 deploy 验证，正常几到几十轮收敛）；40 后提前止损
  恰是"预算与失败模式匹配"。
- Regbase 无配置覆盖时以类默认 40 兜底（多步编排 ~10-16 迭代 + VT 余量），
  A3/A5 统一。
- 空跑熔断（5）与孤儿窗口（2+5）不受影响——它们独立于迭代上限（F5/F8）。

## 四、验证

- codegen/regbase 套件零回归；全量 UT `--quick`。
