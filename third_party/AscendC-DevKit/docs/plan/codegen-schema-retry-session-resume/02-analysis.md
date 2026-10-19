# L3 方案分析 — schema-retry 反馈重派 resume 原会话（事后回填）

- 说明：本文件为实施后回填（立项时用户直接拍板方向进入实施，L3 未独立成文）。
  记录当时实际考量的选项与决策，供追溯；决策已由 03-impl as-built 落地。
- 拍板时间：2026-08-28，用户拍板。

## 候选方案

### 方案 a — 反馈重派 resume 原会话（✅ 拍板采纳）

transition 写回本轮 coder `session_id` 进 State；反馈重派轮 `SpawnAgent` 带
`resume_session_id` + 简短 `resume_prompt`（反馈摘要，不重发全量任务书）。

- 优点：§1.14 原地修改优先于回炉（只改被指认处）；§2.9 问题发现与解决在同一
  agent 内闭合（原会话最了解"哪个标量点为什么这么写"）；省每轮 ~7.5min 冷启动
  + skill/产物重读 token。
- 失配处理：backend 既有 session-gone 自动降级 fresh spawn，会话过期不卡死。

### 方案 b — 维持全新 spawn + feedback 注入（否决）

- 否决：冷启动成本按轮放大（retry 上限 40）；且实证 coder 重派后只修 manifest
  一处——原会话上下文是资产非负债。

### 方案 c — backend 层泛化跨调用 resume（否决）

- 否决：silent-cut auto-resume 是「同一次 spawn 内流断恢复」（传输层语义），
  泛化为跨 iteration 续接会把业务决策（何时该续）压进 backend 层——决策属
  stage 层（业务语义 §1.10），backend 只执行。

## 范围决策（实施期扩展，如实记录）

- **统一抽象（§1.15）**：L1 立项仅指 schema-retry；实施时把 build_feedback
  （编译失败）/ artifact_feedback（manifest 缺字段）并入统一 resume——三者同属
  「coder 会话内可修的产物不合格带反馈重派」，smoke 重派经查证同走
  `codegen_build_feedback` 字段（`_smoke_retry` docstring 实证），自然被覆盖。
- **regbase（A5）路径不动**：`_actions_regbase` 无 resume 注入、
  `_transition_regbase` 无 session 写回——A5 产权归同事，不越界。
- **发现但不修（范围外，另行跟踪）**：`context["build_feedback"]` 注入通道
  是死的（两 backend 均不消费 context、prompt builder 反馈分支早被 B5 删除）
  ——方案 Z 的反馈注入从未真正到达 coder。resume_prompt 是活通道，resume 路径
  反馈已通；fresh 兜底路径的反馈断裂属独立问题。
