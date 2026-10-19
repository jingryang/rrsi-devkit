# L4 实施方案：孤儿豁免有界化 + retry_budgets 统一配置组（F8 + 方案 B）

> 对应问题：F8（纠正反馈无执行保障——已实证连续孤儿可烧满迭代预算）。
> 用户决策（2026-08-21）：① F8 孤儿豁免有界化；② 方案 B——次数类参数统一收敛
> 为 retry_budgets 配置组（"这些修改设计到次数的都是可配置的吧"），统一配置源
> 但保留 backend 注入链（分层边界）。

## 一、F8 机制（孤儿豁免有界化）

组合现状曾致最坏 ~1000 发（孤儿豁免熔断 + codegen 迭代上限 1000）：
- 孤儿轮 = 模型无视确定性路径反馈、零信息产出；豁免不该无限。
- 语义先例（F4）："有界公平机会 → 升级"。孤儿窗口 = 2（retry_budgets），
  窗口内豁免熔断（模型有机会改）；超窗后按空跑同样消耗熔断。
- 最坏预算 = 窗口(2) + 熔断阈值(5) = 7 发，而非 1000。
- 实现：State 加 `codegen_orphan_streak`；codegen transition 孤儿分支在窗口内
  +0、超窗 +1（WARN 明示）；成功路径（熔断清零的 16 处 productive 点）与空跑/
  failure 尾分支清 streak；infra 轮中立。

## 二、方案 B：retry_budgets 统一配置组（§1.15）

| 配置项 | 迁移前散点 | 消费方 |
|---|---|---|
| cut_streak_threshold | runner 模块常量 MAX_CUT_STREAK | runner while 守卫 / WARN |
| consecutive_failures_max | CodegenStage.max_consecutive_failures 类属性 | codegen 熔断门 |
| orphan_exempt_window | F8 新增 | codegen 孤儿分支 |
| resume_attempts | 已在 agent 组（config 层，侦察确认） | backend（注入链保留） |

- 统一源 = orchestration-config retry_budgets section + runtime_config.retry_budgets()
  （§1.3 加载期校验：缺失→文档默认，非法→ConfigError）。
- backend 注入链保留（resume_attempts 经 dispatcher _resume_limits 注入），
  统一的是配置源不是注入链（§1.1 分层）。

## 三、行为变化披露

- 孤儿连续 7 发（2+5）触发熔断 halt，而非烧满 1000；窗口内行为不变。
- 空跑/failure 中断孤儿计数（streak 清零）；成功路径清 streak。
- 无 config 时默认值 = 迁移前原值，行为不变。

## 四、验证

- F8 六用例（窗口内豁免 / 超窗消耗+WARN / 空跑清 streak / 成功清 streak /
  7 连触发熔断 / 反馈照注）。
- 迁移：test_cut_allowance（MAX_CUT_STREAK→cut_streak_threshold）、
  test_codegen_orphan_escape（类属性断言→config）、test_stages（breaker 用例）。
- 全量 UT 3669 passed / 0 failed（+5）。
