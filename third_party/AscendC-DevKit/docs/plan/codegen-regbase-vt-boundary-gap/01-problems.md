# CodegenStage `_first_vt_in_group` 步骤比对失配，A5 Regbase VT 边界恒为空 — L1 问题记录

> 层级：**L1 / 问题记录**。只陈述客观事实（哪里坏了、凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：2026-09-08 codegen 低覆盖方法补齐（m1 拆分前置）的定向测试撰写中坐实。
> 状态：**已修复**（2026-09-08, commit `23a4ae60`）——比对前对步骤列同样去 `4.` 前缀（`step_key = step[2:] if step.startswith("4.") else step`），
> 真实无前缀表可命中；9 例标定测试 + 新增带前缀表兼容用例守护（24 passed），全量 UT 4296→绿。

## P1：`_first_vt_in_group` 按错误比对键匹配，任何 coding_index.md 下均返回 None

### 现象（事实）

- `src/ascendc_devkit/orchestration/stages/codegen.py:551` `_first_vt_in_group(rd, current_sub_stage, group)` 的比对逻辑：
  - 先把 `current_sub_stage` **去掉 `4.` 前缀**得到 `lookup`（如 `4.C.1` → `C.1`）；
  - 再与 coding_index.md 表中步骤列 `step` 做较等比对 `step == lookup`。
- 但 `coding_index.md` 的**步骤列本来就无 `4.` 前缀**（`C.1` / `C.2.VT.0`），与 `stage4_scheduler.sh`
  `get-group`/`dispatch` 同源一致（见 `ascendc-op-dev-coding-regbase/references/orchestrator-logic.md` §7.9：
  `.VT.{M}` 行步骤写 `C.{N}.VT.{M}`）。`4.` 前缀只出现在 progress.md 的子阶段 ID。
- 结果：`lookup`（去前缀后）与表中本就无前缀的 `step` **永不相等** → `found_current` 恒 False →
  函数恒返回 `None`。

### 影响（可观测后果）

- `_actions_regbase_s4_step:1119` 调用后 `vt_boundary` 恒为 `None`：
  - `_build_s4_prompt` 的「VT 边界规则」段（`4166`-`4177`）恒不注入 → s4-coding 收不到
    「完成到 vt_boundary 之前、禁止越过、`.VT.{M}` 归 vf-test-agent」的指令；
- A5 Regbase 场景中，`.VT.{M}` 步骤的归属退化为依赖 `resolve-sub-stage continue` 落到哪个
  子阶段而隐式路由（`.VT.{M}` 本身会被 `_is_vf_step` 捕获交给 vf-test-agent），但**同组后续
  Compute 步骤与 VT 的边界**既无显式指令、也无进度侧防护 → 同组内「先编完 Compute 到 VT 前停」
  的编排约束失效。

### 判定边界（诚实）

- **not-new**：函数与 `vt_boundary` 消费链自 Regbase 引入（`ac3bf505`）即存在，非本批引入。
- **影响路径为 A5 Regbase**（`programming_model == REGBASE` 分支）。本机 A2 no-regbase 的
  常规批量不受影响——这是「换 A5 才炸」的同类（区别于当前 A2 批量不触发）。
- 修复属单行等值比对修正（比对前对 `step` 同样去前缀，或 `lookup` 带前缀比对），动线小，
  但须配回归（`_first_vt_in_group` 已由本批补测试守护 90.3%）。

## 关联

- 测试补集：`tests/ut/orchestration/test_codegen_regbase_phases.py` `TestFirstVtInGroup`（9 例，
  按真实无前缀格式标定）。
- 上游消费链：`_build_s4_prompt` VT 边界段（`ast/upstream` 已就位，缺的是 `vt_boundary` 值）。
- m1 拆分：regbase 专用簇拆分时本缺陷应先修，避免把低频代码连同缺陷拆入新模块。