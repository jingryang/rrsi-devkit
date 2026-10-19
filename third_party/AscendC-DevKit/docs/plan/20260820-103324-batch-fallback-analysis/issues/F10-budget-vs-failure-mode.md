# F10: 各 stage 重试预算与失败模式不匹配

## 现象

`resources/orchestration-config.json` 里各 stage 的重试预算用**统一"次数"**表达，不区分失败模式：

| stage | 预算 | 本次实际 |
|-------|------|---------|
| requirement | 10 | 3 次（silent-cut 不计 iteration，见 F11） |
| general-design-generator | 5 | 5 次（孤儿产物，路径幻觉必然耗尽） |
| tiling | 2 | 2 次（孤儿产物，必然耗尽） |
| codegen | 1000 | 3 次（circuit breaker 熔断） |

## 凭什么这么说（证据）

- `resources/orchestration-config.json` `iterations.stages`。
- rms_norm：5/5 耗尽；d8d4d9 tiling：2/2 耗尽；moe_re_routing codegen：3 次熔断。
- `codegen` 类级 `default_max_iterations=40`（`codegen.py:122`）与配置 1000 也冲突（配置覆盖）。

## 影响

- 写错目录（路径幻觉）下，`tiling:2`/`general-design:5` 的预算必然耗尽——**预算不区分"可修复"与"不可修复"**。
- 不可修复的失败（模型路径幻觉）应尽早 halt 或换策略（fresh/搬回），而不是用"重试次数"硬耗。
- 预算"次数"只约束迭代数，不随失败模式调整策略（重试 vs fresh vs 自动搬回）。

## 根因定位

预算只表达"最多试几次"，不表达"试完这几次应该怎样"（继续重试？fresh？halt？搬回？）。策略维度缺失。
