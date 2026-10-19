# L4 实施 — step-100 schema-retry 反馈重派 resume 原会话（as-built）

> **修订注记（2026-08-28，step-103）**：本文件所述 `_render_retry_resume_prompt`
> 的「结构化反馈摘要」形态已在 step-103 升级——resume 消息改为**与 fresh
> prompt 同源的 kind 专属反馈段**（`_render_build_feedback_section` 复用，
> §1.15 单点），通用摘要因丢失 kind 上下文被取代。其余内容不变。

实施日期：2026-08-28。全量 UT 3775 绿（新增 8 例）。

## 改动

1. `src/ascendc_devkit/orchestration/kernel/state.py`
   - 新增 `codegen_coder_session_id: str = ""`——跨 iteration 会话续接的唯一
     State 锚点（持久字段，进 snapshot：批中断 RESUME 续跑后仍可续接会话）。
2. `src/ascendc_devkit/orchestration/stages/codegen.py`
   - `_transition_membase` 入口写回：`agent_result.session_id` 非空即
     `with_updates(codegen_coder_session_id=...)`——后续所有分支（含
     `_plugin_schema_retry` 的 with_updates）自然携带；空值不清空既有锚点
     （backend 异常宁续旧勿丢）。
   - `_actions_membase` resume 注入：`feedback`（build_feedback ∥
     artifact_feedback，取先非空者）且 session 非空 → `SpawnAgent` 带
     `resume_session_id` + `resume_prompt`。**统一抽象（§1.15）**：三类反馈
     同属「会话内可修的产物不合格带反馈重派」，统一 resume 不逐类分支
     （超出 L3 原范围——L3 只拍 schema-retry；build/artifact 同构并入）。
   - `_render_retry_resume_prompt`：简短「继续修复」消息 + 结构化反馈摘要
     （kind/reason/error_class/hint/log_path/violations/missing_fields 按实
     际携带键摘录）——原会话已有完整任务书，不重发全量 prompt（§1.14）。
   - `rerun_reset_fields` 增 `codegen_coder_session_id`（重跑=新会话）。
3. backend 零改动：`resume_session_id`/`resume_prompt` 通路既有（sdk
   `:533-541` / opencode `:668`——resume 时首条消息= resume_prompt、system
   跳过），且 session-gone 自动降级 fresh spawn 兜底。

## 验证

- `tests/ut/orchestration/test_codegen_retry_session_resume.py` 8 例：
  首轮 fresh / 三类反馈 resume / 无 session 兜底 / transition 写回 /
  空值保旧 / rerun 重置。
- resume 语义边界：首轮无 feedback 不带 resume（全新会话正确）；resume 时
  backend 以 resume_prompt 为新消息（全量 prompt 不进原会话）。
