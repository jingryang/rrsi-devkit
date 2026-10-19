# R3: precision_debug deploy_health 职责错位——确定性信号委托给 agent 申报，null 触发误熔断

**状态**: ✅ 已修，且已被 P1 完整版取代（2026-08-22。R3 值域校验是申报消费期的过渡补丁且**漏了 comment_bisect 的重复 override**（阶段 C 漏删，原始 bug 一直活着）；P1 完整版删除申报层——框架从 redeploy CLI 落盘的 last_deploy.json 自算（spawn 窗口内），见 [07-impl](../07-impl-deploy-health-framework.md)）
**层归**: L1 问题记录（只述事实，不提方案，方案在 L3）

## 哪里坏了？

precision_debug 的 `deploy_fail_streak` 熔断（连续 3 次 deploy 失败 → deploy_broken → 提前退出组）的**输入是 agent 申报的 `deploy_health`**，而 deploy 成功/失败本是框架可直接观测的确定性事实。agent 填 null（未检测）时，`not None = True` 被误判为失败，累积 3 次触发熔断，**提前杀掉还有大量预算的 precision_debug**。

## 凭什么这么说？（证据）

### 事实 1：rms_norm 因 deploy_health null 提前退出，eval 0 分

`output/20260821-111953-bca2fa/20260821-111953-894eb8` control.json:
```json
elapsed_sec: 8069         // 实际耗时 2.24h
time_budget_sec: 36000    // 预算 10h —— 远未耗尽！
deploy_fail_streak: 3     // 触发熔断
corrective_cycles: 3      // 远低于 max 6
```

run.log:
```
22:43  comment_bisect done (2620.2s)     // 第 3 轮
22:44  loopback precision_debug → cannbench_adapt (validation)  // 熔断退出
22:48  CannbenchScorer: overall=0.00 ... 20/20 rc=-11
```

时间预算（8069s）远未耗尽（36000s），但 `deploy_fail_streak=3` 触发 `deploy_broken` 熔断 → 提前退出 → eval 用旧包 → 0 分。

### 事实 2：deploy_health 是 agent 申报的，填了 null

comment_bisect 各轮 `_summary.deploy_health` 全部是:
```json
{"build_ok": null, "output_ok": null, "agent_fallback": false}
```
而 SKILL.md 明确要求"每轮必写 `{build_ok, output_ok, agent_fallback}`，`build_ok=false` 编译失败、`output_ok=false` 运行无产出"。agent **违反契约填了 null**（未检测）。

### 事实 3：框架把 null 当 False（失败）

`precision_debug_substages.py` 熔断更新逻辑:
```python
dh = summary.get("deploy_health")
if dh and isinstance(dh, dict):
    build_ok = dh.get("build_ok", True)     # 缺省 True，但 null → None
    output_ok = dh.get("output_ok", True)
    if not build_ok or not output_ok:        # not None = True → 误判失败
        cp["deploy_fail_streak"] += 1
    else:
        cp["deploy_fail_streak"] = 0
```
`dh.get("build_ok", True)` 只处理"字段缺失"（缺省 True），**未处理"字段是 null"**。null → `not None = True` → 走失败分支，每轮 +1。

### 事实 4：deploy 健康是框架可观测的确定性事实，却被委托给 agent 申报

框架自己调用 `ascendc-devkit redeploy`（build_command），能看到：
- build 返回码（编译成功/失败）
- result.json 是否产出（运行成功/无产出）

这些是**框架 100% 可观测的确定性信号**，却让 agent 在 `_summary` 里申报。agent 是 LLM，填不准（null）就把确定性决策建立在不可靠申报上。

## 影响

- **所有跑 comment_bisect/printf_location 的算子都可能误熔断**：rms_norm 已中招（eval 0 分），moe_re_routing 正在 comment_bisect，大概率同样提前退出。
- **浪费大量已投入预算**：precision_debug 修到一半，因 agent 填 null 被熔断，2h+ 投入白费。
- **§1.3 缺失**：agent 产出（deploy_health）无值域校验，null 静默流入熔断逻辑。

## 与既有问题编号的边界

- **R1/R2**（20260821 批）: runner 层 artifact-retry 抽象，与本问题无直接关系（不同层）。
- **§P8**（deploy health meltdown）：本问题的机制是 P8 引入的，但 P8 假设 agent 正确申报 deploy_health，未考虑 agent 填 null 的契约违反。本问题是 P8 的输入不可靠问题。
