# L3：P14 方案分析——设计子阶段产物反馈重派 resume 统一（step-112）

> 状态：**冻结**（2026-09-02 拍板——用户确认「resume 是正确解，仅过程另立 step」；
> 方向由 §1.15 + step-100 先例裁定，本文解决实施形态与边界）。
> L1 事实：`01-problems.md` P14。L4：`13-impl-design-feedback-resume.md`。

## 1. 问题与裁定回顾

同一行为类「产物不合格 + 带反馈重派 + 会话内可修」：codegen step-100 统一为
resume（实测代价：fresh spawn 丢 152-turn 上下文、改一处重付 ~7.5min 冷启动）；
设计子阶段仍全新 spawn。§1.15：同一行为必须单点统一，修复必须收口（新增单点 +
删除既有散点）——设计侧 fresh spawn 是未完成的收口，不是并列选项。

## 2. 与 step-94 的语义分界（表面张力消解）

step-94 否决 resume（codegen **smoke** 通道）与 step-100 采纳 resume（codegen
**schema/build/artifact** 通道）不矛盾——判据是**修复需要什么**（§1.10 精神：
按语义不按机制）：

| 维度 | smoke 通道（step-94 否决 resume） | 产物契约通道（step-100/本步采纳） |
|---|---|---|
| 反馈内容 | 自含事实（rc/最后打点/script+env 现场/前次产物指针）——重试方不需要会话记忆即可定位修复 | 指认「哪个字段缺/什么形态错」——修复动作触及会话刚做的工作本体 |
| 会话状态 | iter1 **带错误信念结束**（会话上下文可能被污染），且历史实证过「无界会话泥潭」（方案 Z 病灶） | 会话正常收尾、产物已交付大半——上下文是**资产**（推导/决策就在里面） |
| 最优形态 | fresh + 自含事实（避免拖着污染上下文续走） | resume（保留上下文，修复限于被指认处） |

设计子阶段的 missing_artifact / F2 打回属右列：要补的布局公式就是 agent 几分钟
前推导完的内容，会话上下文正是修复所需——resume。设计会话另有天然安全阀：
设计子阶段有独立迭代天花板 + fail_strategy=halt，无 codegen marathon 式长会话
泥潭土壤。

## 3. 方案（两个单点，各在掌握所需信号的层）

### 3.1 会话锚点捕获——runner 层（机械单点）

**位置**：`Runner.run_stage`，`stage.transition(result_state, result)` 之后、
stage_iterations 更新处。`agent_result.session_id` 非空 → 
`result_state.with_updates(last_agent_session_id=sid)`。

- 为什么在 runner：session_id 在 spawn 返回时**首次出现于 runner**；放 stage 层
  则每个子阶段 transition 各自记回写（§1.15「漏写一处即出错」——设计侧 8+ 个
  transition 全是子类覆写，无公共入口；曾评估 `_read_disk_artifacts` 作咽喉点，
  但其成功路径只返回 raw、状态经调用方局部变量流转，捕获会丢失）。
- 捕获时序（transition **之后**）同样正确：下一轮 `actions()` 才消费锚点；
  error_state 由 runner 事后补锚点，与 transition 内写入等效。
- 通用性：字段对所有 stage 生效（机械事实：本 stage 最近一次 agent 会话）；
  消费与否是各 stage 的语义决策。fork-join 安全：merge 只合并 provides 字段，
  分支局部锚点不进 join（已核实 merge_forkjoin:108）。review 为交互提问
  （AskUserQuestion）非 agent spawn，无双写。

### 3.2 resume 决策与消息——`_DesignSubstage.actions`（语义单点）

**条件**（全部满足才 resume，缺一 fresh spawn 兜底——镜像 step-100「无上轮
session → fresh 兜底」）：

```python
state.last_error 且 last_error.stage_name == self.name   # 本阶段产物不合格
and state.user_feedback                                    # 定向反馈在位
and state.last_agent_session_id                            # 会话锚点在位
```

- **loopback 边界**（fresh 保持）：门反馈走 `_loopback_feedback`（不同字段），
  且门错误 `stage_name` 是门不是本阶段 → 条件自然不命中——语义边界由既有
  字段语义承载，不新增机制（§1.10）。
- **infra 边界**：infra 错误既有短路 `return []` 在前，不受影响。
- **cut 边界**：cut 的 resume 由 backend 层 sidecar 决策（step-110）；显式
  resume_session_id 恒优先（step-110 路由），两者同会话不冲突。
- resume_prompt（§1.14 不重发全量）：`「上一轮产物未通过框架校验，请在同一会话
  继续修复（勿重做已交付的正确部分，只修正被指认的问题后重新交付）：」+ 
  user_feedback 全文`——与 fresh prompt 的「## 用户反馈」段同一信息源（§1.15
  两条投递路径同一渲染语义）。
- rerun 安全：`rerun_reset_fields` 增 `last_agent_session_id`（镜像 codegen
  「重跑=新会话」裁定）。

### 3.3 codegen 侧收口（§2.5 删旧通路）

`codegen_coder_session_id` 字段 + transition 入口回写 + rerun_reset 引用全部
删除，统一消费 `last_agent_session_id`（runner 捕获覆盖 codegen——transition
之后同一时序）。§1.4 不留兼容别名。

## 4. 不做的事

- 不改 smoke 通道（step-94 裁定独立成立，属左列语义）。
- 不给 gate/review/loopback 加 resume（会话陈旧，fresh 语义正确）。
- 不做跨 stage 会话复用（锚点随 stage 迭代覆盖，语义=「本阶段最近会话」）。
- 不动 A5 regbase 编排状态机（其会话管理自成体系且归同事产权，需求出现时另行评估）。

## 5. 验证判据

- UT：runner 捕获（stub backend 返回 session_id → state 锚点在位）；actions
  条件矩阵（三条件全命中→resume；缺 session→fresh；他阶段 last_error→fresh；
  无 feedback→fresh；infra→[]）；resume_prompt 组成；rerun_reset 含锚点字段；
  codegen 迁移后既有 retry-resume 用例绿（字段名更新）。
- ST：F2 retry 场景扩展——stub 返回 session_id，断言 retry 轮 spawn 收到
  `resume_session_id == 首轮会话`（runner→actions 全链接线端到端）。
- 下批真实跑观测：设计反馈重派轮的修复 turn 是否出现在原会话（db 同 session id）；
  重派轮耗时对照（预期显著低于 fresh 重定向）。

## 6. 风险

- resume 后 agent 仍不修 → 预算机制照常兜（artifact-retry 3 次→iteration→halt），
  resume 不改变失败语义只改重试形态。
- 老会话上下文逼近 backend 上限 → backend 自有 compaction/硬墙，非本层职责。
