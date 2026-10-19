# L4：P14 实施——设计子阶段产物反馈重派 resume 统一（step-112）

> L3：`12-analysis-design-feedback-resume.md`（冻结）。TDD：先红后绿。
> 改动四件：State 锚点字段（删 codegen 旧字段）、runner 捕获单点、
> _DesignSubstage resume 决策、codegen 收口迁移。

## 1. 改动清单（按实施顺序）

### 1.1 UT 先行（红）

新增 `tests/ut/orchestration/test_design_feedback_resume.py`：

- **runner 捕获**（Runner.run_stage + stub stage/backend，参照
  test_artifact_retry_common 形态）：backend 返回 `session_id="ses_x"` →
  transition 后 `state.last_agent_session_id == "ses_x"`；无 session_id（空串）
  → 不覆盖既有锚点（镜像 codegen「宁续旧勿丢」语义——空值不清空）。
- **actions 条件矩阵**（_DesignSubstage 子类直驱）：
  - own-stage `last_error(incomplete_output)` + `user_feedback` + 锚点 →
    SpawnAgent 带 `resume_session_id=锚点`、`resume_prompt` 含「同一会话」+
    user_feedback 全文；
  - 缺锚点 → `resume_session_id is None`（fresh 兜底）；
  - `last_error.stage_name` 为他阶段（loopback 形态）→ None；
  - 无 `user_feedback` → None；
  - infra error_type → `actions == []`（既有短路不变）。
- **rerun_reset**：`_DesignSubstage.rerun_reset_fields` 含
  `last_agent_session_id`。
- **codegen 迁移守卫**：State 无 `codegen_coder_session_id` 字段（§2.5 删净）。

### 1.2 State：`orchestration/kernel/state.py`

- `codegen_coder_session_id: str = ""` → 删除；同位新增
  `last_agent_session_id: str = ""`（注释：step-112 runner 捕获的「本阶段最近
  agent 会话锚点」，产物反馈重派 resume 消费；rerun 重置=新会话）。

### 1.3 runner：`orchestration/kernel/runner.py`

`run_stage` 中 `result_state = stage.transition(result_state, result)` 之后：

```python
# step-112 (§1.15)：会话锚点统一捕获——产物反馈重派 resume 的机械单点。
# session_id 在 spawn 返回时首次出现于此层；空值不清空既有锚点（backend
# 异常时宁续旧勿丢）。消费与否是各 stage actions 的语义决策（设计子阶段
# 反馈重派轮 resume；见 _DesignSubstage.actions）。
_ar = result.get("agent_result")
_sid = (getattr(_ar, "session_id", "") or "") if _ar is not None else ""
if _sid:
    result_state = result_state.with_updates(last_agent_session_id=_sid)
```

### 1.4 设计子阶段：`orchestration/stages/design_substages.py`

1. `_DesignSubstage.actions`：infra 短路之后，构造 SpawnAgent 前加 resume
   决策（L3 §3.2 条件），SpawnAgent 增 `resume_session_id=`/`resume_prompt=`。
2. 新增 `_render_retry_resume_prompt(state)`：首句（同一会话继续修复、勿重做
   已交付部分）+ `state.user_feedback` 全文。
3. `rerun_reset_fields` 覆写：`provides + ["last_agent_session_id"]`。

### 1.5 codegen 收口：`orchestration/stages/codegen.py`

- `_transition_membase` 入口的 session 回写段删除（runner 捕获取代）。
- `_actions_membase` 的 `state.codegen_coder_session_id` →
  `state.last_agent_session_id`（两处）。
- `rerun_reset_fields` 列表中 `codegen_coder_session_id` →
  `last_agent_session_id`。
- 既有 `test_codegen_retry_session_resume.py`：字段名更新；transition 回写断言
  改为锚点经 runner 捕获的等价断言（actions 端消费不变——用例语义从「transition
  写回」迁到「runner 捕获 + actions 消费」）。

### 1.6 ST：`tests/st/test_design_pipeline_e2e.py`

F2 retry 场景扩展：stub spawn 返回递增 `session_id`（`ses_tiling_1`…）并记录
收到的 `resume_session_id`/`resume_prompt`；断言 retry 轮 tiling spawn 收到
`resume_session_id == 首轮会话 id`、`resume_prompt` 含修复指引——runner→actions
全链端到端（回填触发器维持「## 用户反馈」节不变）。

## 2. 不做的事（防走样）

- 不动 smoke 通道 / loopback / gate / A5 regbase（L3 §4）。
- 不做跨 stage 会话复用。
- 不留 `codegen_coder_session_id` 别名/迁移层（§1.4）。

## 3. 验证

- 全量 UT（--quick）+ 全量 ST 默认模式。
- 下批真实跑观测（L3 §5）：设计反馈重派轮修复 turn 与原推导 turn 同 session
  （db 可查）；重派轮耗时对照 fresh 重定向。

## 4. 风险与回退

- resume 后仍不修 → 既有预算链兜底（artifact-retry→iteration→halt），失败
  语义不变。
- codegen 迁移回归 → 其既有 retry-resume UT 全量绿即证等价。
