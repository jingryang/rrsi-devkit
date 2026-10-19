# P6: agent 自评路由（route_to）影响关键控制流

**状态**: ✅ 已修（2026-08-22，值域校验 + 违约可观测：route_to ∉ {fix, printf_location}（任意类型）→ WARN 携带原值与值域，按安全缺省 fix；缺省 None 原有 WARN 保留。"是否需设备取证"的判断本身是 LLM 语义（读代码后的结论），保留 agent 申报——修的是契约纪律（§1.3 与 scope_verdict 对齐），非判断权回收。UT 4 测试钉住）
**层归**: L1 问题记录（只述事实，方案在 L3）

## 哪里坏了？

diagnose 阶段的关键路由决策 `route_to`（`fix` / `printf_location`）由 **agent 自评**决定，框架信任该值路由（`printf_location` → 设备取证，缺省 → 实施模式）。agent 自评不准或不填 → 路由错误。

## 凭什么这么说？（证据）

### 事实 1：route_to 是路由决策，由 agent 申报

`DiagnoseSubstage.transition`:
```python
_route_to = summary.get("route_to")
if _route_to is None:
    Logger.warn("diagnose: route_to 缺失，默认进实施模式")
    _route_to = "fix"
if _route_to == "printf_location":
    # 纯分析路径：自评需设备取证
    ...
```
SKILL.md 要求 `route_to`（`fix` / `printf_location`，必写），但**框架对缺失默认 `fix`**（静默默认，非值域校验）。

### 事实 2：route_to 决定"是否设备取证"的语义分叉

- `route_to=printf_location`：diagnose 自评"静态手段不足，需 on-device printf 确认" → 不实施，转 printf
- `route_to=fix`（缺省）：diagnose 直接实施 fix_plan

这是**关键控制流分叉**，判断依据是"静态分析是否足够"，本可由框架确定性判定（如候选池是否含待验证项、失败是否纯 runtime），却让 agent 自评。

### 事实 3：缺省静默默认（非 §1.3 校验）

`route_to=None` → 默认 `fix`（静默默认），而非：
- 校验值域（`route_to in {fix, printf_location}`，否则 raise）
- 或由框架从确定性信号派生

这与 scope_guard 对 `scope_verdict` 的严格校验（`verdict not in {upstream, pass} → raise`）形成对比——**同一框架，scope_verdict 严格校验，route_to 静默默认**，不一致。

## 影响

- **路由决策依赖不可靠申报**：agent 自评 route_to 不准 → 错误地进/不进设备取证 → 调试方向错。
- **§1.10 违背**：route_to 是业务语义（"是否需要设备取证"），判据本可由框架从候选池状态/失败类型确定性派生，却让 agent 主观评。
- **§1.3 不一致**：同类契约字段，scope_verdict 严格校验、route_to 静默默认——校验纪律不统一。

## 与既有问题边界

- **P2**（agent 申报框架可算信号）：route_to 与 total_count 同属"确定性/半确定性信号委托给 agent"，但 route_to 是路由决策（更关键），P6 单列。
- **P1**（deploy_health）：同属 agent 申报影响框架决策，但 P1 是 deploy 健康、P6 是路由。
