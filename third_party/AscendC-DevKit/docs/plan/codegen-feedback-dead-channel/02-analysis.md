# L3 方案分析 — codegen 反馈投递单点化（已拍板并实施，冻结）

- 拍板时间：2026-08-28，用户拍板方案 a；实施期经 L1 勘误后精化为终版。

## 勘误驱动的方案修订

原方案 a（通用摘要体 `_render_feedback_summary` 单点）基于「fresh 路径无反
馈段」的误判。L1 勘误后（fresh 一直有 kind 专属段），**正确单点是把既有
kind 专属段提取为可复用渲染**，而非在其上再叠一层通用摘要。

## 拍板方案（终版，已实施）

1. **kind 专属段提取**（§1.15 单点）：
   - `_render_build_feedback_section(fb, run_dir)`：六分支（opdef_optional /
     scalar_contract / schema_mismatch / smoke_host / smoke_owner_judge /
     else 编译失败）原文搬运，`sections.append` → `return`；
   - `_render_artifact_feedback_section(afb)`：artifact 段同。
2. **两场景共用同一渲染**：fresh prompt 反馈段（`_build_codegen_prompt` 调
   用）与 resume 消息（`_render_retry_resume_prompt` 调用同函数 + resume
   场景首句「同一会话继续修复」）——两条投递路径内容严格一致；场景首句分离
   （resume/fresh 语义相反，不共用整文案）。
3. **context 死键全删**（§2.5）：mode / existing_code / last_error /
   build_feedback / artifact_feedback / previous_sources 六键——前四者
   prompt builder 已有等价段，feedback 投递已由 1/2 接管。信息进 agent 的
   唯一通路是 prompt。
4. **context 参数本身的工程级去留**（含 requirement 侧 3 个死键）超出本
   step 产权，另立跟踪。

## 否决记录

- 通用摘要体叠加（初版方案 a）：在既有 kind 段之上再叠一层通用摘要 =
  双重注入（§2.5），且 resume 侧丢失 kind 上下文——勘误后废弃。
- backend 消费 context（b）：业务格式压传输层 + 双后端多通路。
- 只删不接（c）：名存实亡更误导。

## 关联

- step-100（resume 通路的引入者，其通用摘要被本步升级）、93/94（反馈生产
  端产权）、B1/B5→方案 Z（历史脉络）。
