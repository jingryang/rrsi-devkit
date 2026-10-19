# L1: test_smoke.TestCodegenStageEndToEnd fixture 与 codegen scaffolding_kind 不兼容（pre-existing，§3.9 守护缺口）

## 现象（客观事实）
- `tests/st/test_smoke.py::TestCodegenStageEndToEnd::test_full_pipeline` 跑 **0.17s pass**，
  但 codegen stage 立即 failed，**从未 spawn codegen agent**：
  ```
  [codegen] 1/1 → ✗ codegen done (0.0s) [aborted]
  [ERROR] Stage 'codegen' failed: 'dict' object has no attribute 'scaffolding_kind'
  ```

## 根因（凭什么这么说）
- `tests/fixtures/add_state.json` 的 `profile` 是**裸 dict**（`{"name":"omni-ops","build":{...}}`），
  **无 `scaffolding` 字段、无 `repo_profile_name`**。
- `dispatch_single_stage` 在 `repo_profile_name` 缺失时不调 `load_profile`（`dispatcher.py:358-363`），
  profile 留 dict 不转 `RepositoryProfile` 对象。
- codegen transition（commit `6355b4d6 "fix(codegen): enforce torch plugin registration contract"`）
  访问 `profile.scaffolding_kind()`（`codegen.py:356/1202/1357` 等多处）需 `RepositoryProfile` method；
  dict 无此 method → `'dict' object has no attribute 'scaffolding_kind'` → transition 抛错 → stage failed。

## 为什么长期没被发现（掩盖机制）
- test 断言只查 workspace 产物（`events.jsonl` / `state_snapshot.json` 存在 + `current_stage=="codegen"`），
  **不断言 exit_code==0**（`:80` 注释 "may exit 0 or non-zero if agent hits turn limit"）。
- dispatcher 即使 stage failed 也写出 workspace（events 记 stage_enter/failed + state_snapshot），
  故 test 一直 green，但 codegen agent 从未真实执行。

## pre-existing 归属（非本次改造引入）
- `git diff src/ascendc_devkit/orchestration/stages/codegen.py` 中**不含** `scaffolding_kind` 访问行
  （`git diff | grep scaffolding_kind` 无输出）。scaffolding_kind 访问来自 `6355b4d6`，本次
  codegen build-retry 改造（方案 Z，2026-08-03）未触及。

## 影响范围
- **§3.9 守护缺口**：codegen 端到端无有效 ST 守护（唯一端到端 ST 失效）。
- **方案 Z 验证局限**：即便修 fixture 让 test_smoke 真跑，add 算子 `max_iterations=1` 只走
  happy path（1 次 build 成功 → done），**不触发 build-retry 循环**（方案 Z 核心：build 失败→respawn）。
  故 test_smoke 对方案 Z 真实生效验证价值有限；build-retry 循环的确定性验证靠 UT
  （`test_codegen_build_failure_triggers_respawn` / `build_retry_exhausted_escapes_to_d4` /
  `smoke_passed_resets_build_retry_counters` / `build_feedback_injected_into_prompt`），
  真实 turn 数下降观测靠批跑（复杂算子触发 build-retry，~小时级，非 PR 前硬门）。

## 根因深化 + 解决（2026-08-03）

**根因不是 fixture，是 State mutation 边界不转换类型**：`with_field`/`with_updates` 走
`dataclasses.replace`（state.py:362/365），replace **不按注解转换**——Python dataclass 注解
`profile: RepositoryProfile` 只是声明、运行时不强制；`to_snapshot` 的 `asdict` 有损拍平 nested
dataclass 为 dict，逆转换 `_rebuild_value` 只在 `from_snapshot` 一个入口做。dispatcher Layer 2 用
`with_field(profile_dict)` → 留 dict → codegen `profile.scaffolding_kind()` 炸。**fixture 是触发点非根因**
（任何 with_field/with_updates 赋 dict 都会炸同类问题，profile 只是第一个被访问 method 的）。

**一劳永逸修法（构造性保证 §2.9 / 单一通路 §2.5）**：`State._coerce_kwargs` chokepoint（state.py）——
`with_field`/`with_updates` 的值在进 State 前按 field 注解 `_rebuild_value` 重建（dict→dataclass、
str→Path、list 逐元素）。任何 mutation 入口自动转换，dict 进不了 State，不需每个调用点记得转换。已转值
pass through（idempotent，`_rebuild_dataclass` 对 `isinstance(v, cls)` 返回 as-is），标量 fast-path，零损耗。

**验证（全部 OK）**：
- 全量 UT **3532 passed/0 failed**（零回归——idempotent + fast-path 不破坏现有 with_field/with_updates 调用）。
- 受影响 ST **74 passed**（self_evolution/integration/predesign/design_pipeline/smoke）。
- **test_smoke.TestCodegenStageEndToEnd heavy_llm 真跑 230.51s pass**（修前 0.17s 炸 scaffolding_kind
  从未 spawn agent → 修后真 spawn codegen agent + transition 调 deploy，transition→deploy 真链路验证）。
- dispatcher Layer 2 撤回（单一通路：State 边界转，不需 dispatcher 显式 from_snapshot）。

**不再需要原"待排期"的 fixture/profile 补字段方案**——构造保证已从根上治住，fixture 保持原样即可。
