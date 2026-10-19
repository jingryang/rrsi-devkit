# P7: A5 is_vf_issue 确定性路由门控纯 LLM 自评

**状态**: 待修
**层归**: L1 问题记录（只述事实，方案在 L3）

## 哪里坏了？

A5 的 `is_vf_issue`（dump_debug 产物，决定是否进入 vf_test 隔离）是**确定性路由门控**，却**完全依赖 LLM 自评**——框架零校验、无缺失默认、无违约日志。误报（漏标 true）→ 跳过 VF 隔离直接 finalize，可能放行 VF 缺陷；误标 true → 白跑一轮 vf_test。

## 凭什么这么说？（证据，来自 A5 深度审计）

### 事实 1：is_vf_issue 直接决定路由

`precision_debug_a5.py`:
- dump_debug 的 `resolve_condition`（L963-979）：`ps == "fixed" and dc["is_vf_issue"] → need_vf`（进 vf_test）
- `is_vf_issue` 由 dump_debug skill 在 result JSON 里自报（L937 读取）
- 文档自查为"仅当 DumpTensor 证据明确指向某 VF 函数输出错误时置 true"（L878）——**纯 LLM 语义判断**

### 事实 2：比 A3 的 route_to 更裸

- A3 的 `route_to` 至少有"缺失默认 fix + 日志"（substages L2231-2242）
- A5 的 `is_vf_issue` **无默认、无校验、无违约日志**——缺失时 `dc["is_vf_issue"]` 为 None → 不满足 `== True` → 静默跳过 vf_test

### 事实 3：框架零校验

与 A3 的 scope_guard 对 `scope_verdict` 严格校验（`verdict not in {upstream,pass} → raise`）形成鲜明对比。A5 对 `is_vf_issue` **零校验**。

## 影响

- **§1.10 违背**："是否需 VF 隔离"是路由决策，判据是 DumpTensor 证据是否指向 VF 函数——这本质是**结构信号**（dump 输出与 VF 边界对应），框架可部分派生，却纯委托 LLM。
- **误判放大**：漏标 → VF 缺陷进入 finalize → 最终全量验证失败，浪费更大预算；误标 → 白跑 vf_test。
- **§1.3 缺失**：无值域校验，错误静默。

## 与既有问题边界

- **P6**（A3 route_to）：同类"路由委托 agent"，P6 是 A3、P7 是 A5。
- **P8**（A5 best_snapshot）：同 A5 的"agent 申报框架决策"，P7 是路由、P8 是精度权威。
