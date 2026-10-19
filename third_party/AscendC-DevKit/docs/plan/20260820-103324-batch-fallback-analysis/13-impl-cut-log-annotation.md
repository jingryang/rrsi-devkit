# L4 实施方案：cut 日志并置两套计数说明（F11）

> 对应问题：F11（silent-cut 不消耗 iteration 计数，日志读数误导）。
> 用户决策（2026-08-21）：按建议实施（纯展示层改动）。

## 一、性质

F11 是**日志展示**问题，非机制缺陷——cut 不烧预算、cut_streak 单独兜底是刻意
设计（可恢复中断不算逻辑失败，F4/F8 已补齐机制层）。修复只改 WARN 文本，不改
任何计数/机制（与 F4 的 cut_streak、F8 的窗口正交，无重复）。

## 二、改动

`runner.py` cut 分支 WARN 补充并置说明：
- cut_streak=N/M（连续 silent-cut 预算，不消耗 iteration）；
- iteration 保持 i/K（cut 是可恢复中断，不烧生产迭代预算；生产迭代按真实
  成功/失败轮消耗）；
- 放弃 cut-recovery 于 cut_streak 达 M 或 iteration 达 K。

## 三、验证

- 套件零回归（无测试断言旧 WARN 文本）；全量 UT `--quick`。
