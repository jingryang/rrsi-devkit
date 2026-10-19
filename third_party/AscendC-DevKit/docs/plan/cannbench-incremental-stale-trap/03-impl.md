# L4 实施 — step-101 cann-bench 删增量只走全量（as-built）

实施日期：2026-08-28。全量 UT 3775 绿（净 +2 守卫例，删 1 旧例）。

## 改动（彻底删除，§1.4/§2.5 不留兼容层）

1. `resources/repository-profiles/cann-bench.yaml`：删
   `incremental_command_template` 块与全部动机注释，替换为 4 行 step-101
   记录注释（为何不做增量 + 真实仓启用前提）。
2. `resources/schemas/repository/profile.json`：删 `incremental_command_template`
   属性——`additionalProperties: false` 使任何 profile 再声明该键即加载期
   ValueError（§1.3 防误加回）。
3. `src/ascendc_devkit/domain/repository.py`：删 `BuildStage` 字段与
   `_parse_build_stage` 解析行。
4. `src/ascendc_devkit/orchestration/stages/deploy.py`：删
   `incremental or command_template` 回落，恒用 `command_template`。

## 验证

- `test_schema_rejects_incremental_command_template`（声明即拒绝）、
  `test_build_stage_has_no_incremental_field`（属性不存在）。
- 删 `test_incremental_command_template_takes_precedence`（被测行为已不存在）。
- 真实 `ProfileLoader.load("cann-bench")` 加载通过，build stage 唯一模板
  `bash build.sh --soc={soc_version}`。

## 行为变化

cann-bench deploy 恒全量（build.sh 内部 `rm -rf build/`），+~35s/次
（run 级 ~6 min），接受（L3 拍板）；mtime 陷阱（kernel 源变更不进 binary）
随增量通路从 cann-bench 移除而消除。
