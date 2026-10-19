# L4 实施 — step-103 反馈投递单点化 + context 死键删除（as-built）

实施日期：2026-08-28。全量 UT 3782 绿（+7 例）。

## 改动（均在 `src/ascendc_devkit/orchestration/stages/codegen.py`）

1. `_render_build_feedback_section(fb, run_dir)`（新方法）：六 kind 分支
   反馈段原文搬运提取（`sections.append` → `return`，分支体零改动）。
2. `_render_artifact_feedback_section(afb)`（新方法）：artifact 段同。
3. `_build_codegen_prompt`：fb/afb 内联块替换为两方法调用（run_dir 派生保留
   在调用点）；scaffold 段及后续不变。
4. `_render_retry_resume_prompt(state)`（重构）：实例方法——resume 场景首句
   + 与 fresh 同源的 kind 专属段（build_feedback 优先，与 actions 取用顺序
   一致）；取代 step-100 的通用摘要（勘误后确认其丢失 kind 上下文）。
5. `_actions_membase`：context 死键六枚全删（mode/existing_code/last_error/
   build_feedback/artifact_feedback/previous_sources），SpawnAgent 不再传
   context。

## 实施期波折（诚实记录）

- 首次实现按误判的 L1 叠加了通用摘要段，全量 UT 揭出两处旧断言失败
  （守护 context 死通道的 `context.get("build_feedback")` 断言），顺藤摸瓜
  发现 prompt builder 函数体后半的既有 kind 段 → L1 勘误 → 方案修订为
  kind 段提取复用 → 撤重复段。
- 一次脚本化长块提取损坏文件（多行 append 参数变孤立表达式），`git checkout`
  恢复后改用逐段精确 Edit 重做——教训：长块搬运禁用正则变换脚本。

## 验证

- `tests/ut/orchestration/test_codegen_feedback_delivery.py` 7 例：fresh
  kind 段进 prompt（scalar/compile/artifact 三形态）、无反馈不误伤、
  **单点守护**（同一 feedback 的 fresh 段与 resume 体为同一段文本 +
  resume 首句分离）、context 死键清除。
- `test_codegen_retry_session_resume.py` 断言升级（resume_prompt 含完整
  kind 段与 violations 条目）；`test_stages.py` 两处死通道断言改为注释
  说明（活通路断言原样保留在前行）。
- 全量 UT 3782 passed。
