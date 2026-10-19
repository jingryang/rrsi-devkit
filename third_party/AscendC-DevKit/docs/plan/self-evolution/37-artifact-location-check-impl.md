# P62 — 设计阶段产物落盘位置强制校验 — 实施方案（第四层）

> 范围：**所有走 `_DesignSubstage._parse_single` / `_read_disk_artifacts` 的设计（含 test_design）阶段产物读取**——统一收敛到「磁盘位置强制 + 名称放宽 + 缺失带 feedback 重 spawn」单通路。**移除 agent-dict 兜底判 success**（§2.5 唯一通路）。
> 层级：**第四层 / 实施方案**。改哪个符号、什么顺序、怎么验证（TDD）。
> 依据：L3 `37-artifact-location-check-analysis.md`（冻结，D1-D4）。
> 约定：按符号定位（不写 file:line）；外部依赖只读；TDD 先红后绿。

---

## 0. 基线（已存在，复用，不重建）

- **runner `_run_stage_body`**（`runner.py`）：靠 `has_all(provides) AND is_satisfied()` 决定 terminal——任一 False 自动重 spawn 当前 stage agent；iteration 耗尽才看 `fail_strategy=halt` halt。**不造新机制，复用既有 iteration 重试通道**（用户拍板）。
- **runner `_build_prompt`**：把 `state.user_feedback` 注入下一轮 prompt。**re-spawn 的 feedback 通路已存在**。
- **`_DesignSubstage._error`**（`design_substages.py`）：只设 `last_error`（用于 halt 路由）。本步保留，schema_violation 场景仍用。
- **`ErrorFeedback(stage_name, error_type, message)`**（`state.py`）：既有。
- **`output_contract.provides` + `state.has_all` + `Stage.is_satisfied`**：产物存在性 / 满足度既有原语。
- **`_DesignSubstage._parse_single` / `_TilingSegmentStage.transition` / Integrate/Validate/AnchorPerTemplate/DetailedDesignIntake 的自定义 transition**：本步改造的六条产物读取路径（同一缺陷类）。
- **`_TestDesignSubstage(_DesignSubstage)`**（`test_design_substages.py`）：继承 `_parse_single`，故 test_design 阶段自动纳入单通路（§2.5，正确外扩，无需另改）。

---

## 1. 单通路 helper（新增，模块级 / 基类方法）

### 1.1 `_normalize_stem(name)` + `_locate_artifact(wd, filename)`（`design_substages.py` 模块级新增）

名称归一化定位——容忍大小写 / 下划线 / 连字符 / 点；精确名优先，不在则 working_dir 内 glob：

- `_normalize_stem`：`re.sub(r"[_\-.]+", "", name.lower())`。
- `_locate_artifact(wd, filename)`：
  1. 精确名 `wd / filename` 命中 → 返回；
  2. 否则按 ext glob，归一化 stem **完全相等**（rank 0）> **前缀/后缀容忍**（rank 1）；
  3. 同 rank 多命中 → 保守返回 `None`（触发重 spawn，不猜）。
- 不复用 `issue_render.issue_fingerprint`（`code@target` 拼接，不适合文件名归一化）——新写、放 design_substages 模块级（design 阶段专用，不过度抽象）。

### 1.2 `_missing_artifact_error(self, state, filename, wd)`（`_DesignSubstage` 方法新增）

位置错需同时给下一轮 agent 反馈 → 设 `last_error`（`ErrorFeedback(error_type="missing_artifact")`）**且** `user_feedback`（位置要求文案，含 `wd`）。区别于 `_error`（只设 last_error）。message：`"{stage}: 产物 {filename} 未在正确目录找到。必须以相对路径写入当前工作目录（spawn 时 cwd 已设为 {wd}），请勿使用绝对路径或写出到仓根/其他目录。"`

### 1.3 `_read_disk_artifacts(self, state, result, required, optional=())`（`_DesignSubstage` 方法新增）—— **THE 单通路（§2.5）**

- `wd = result.get("_working_dir")`；None → `_missing_artifact_error`（无 working_dir = 产物无处落）。
- required 文件逐个 `_locate_artifact`：None → `_missing_artifact_error`；OSError → `_error(schema_violation)`。
- optional 文件：命中才读（不强制）。
- **`decision_log.json` 隐式 optional**：自动并入 optional（每个 design substage 都可能产 decision_log，base-class `_capture_decision_log` 在 raw 里找它）。集中此处 = 单通路是「raw 里有什么」的唯一权威，对齐 P62 前 raw 是整 dict 的行为。
- 返回 `(raw, None)` 成功（`raw = {filename: text}`，即 `artifact_contract().parse` 与 `_capture_decision_log` 期望的形状）；`(None, error_state)` 缺失/不可读。

---

## 2. 六条产物读取路径改造（全部走 `_read_disk_artifacts`）

### 2.1 `_DesignSubstage._parse_single`

- `fpath = _locate_artifact(wd, filename)` 取代裸 `Path(wd)/filename`（位置即 working_dir，名称放宽）。
- **删除路径2 dict fallback**（agent_result.artifacts 兜底判 success）：产物必须落盘 working_dir（P4 确定性磁盘读取）。
- 全程经 `_read_disk_artifacts(state, result, [filename])`；缺失 → `_missing_artifact_error`；strict schema_violation 保留。
- 单 field provides 不写 → `has_all=False` → runner 自动重 spawn。

### 2.2 `_TilingSegmentStage.transition`

- 原「只从 agent_result.artifacts dict 读、不碰磁盘」（CEL T1 直接根因）→ 改先 `_read_disk_artifacts(state, result, [self.schema_file])`（保留 `if not result.get("_working_dir"): result = {**result, "_working_dir": self._working_dir(state)}` fallback）；缺失 → `_missing_artifact_error`（不写切片）；落盘 → 磁盘确定性读取 + `artifact_contract().parse` + 写 `tiling_results[template][segment_key]`。
- **新增 `_TilingSegmentStage.is_satisfied`**：`provides=["tiling_results"]` 是聚合字段（split 先填则 has_all 恒 True）→ 靠 is_satisfied 检**本 segment_key 切片**：`_own_last_error` 则 False；否则 `tiling_results[template].get(segment_key) is not None`。切片缺失（位置错没写）→ False → runner 重 spawn。

### 2.3 IntegrateStage.transition

`_read_disk_artifacts(state, result, ["design_spec.json", "tiling_strategy.json"], optional=["data_flow.json"])`，删 dict 读。

### 2.4 ValidateStage.transition

`_read_disk_artifacts(state, result, ["blocking_status.json"])`，删 dict 读。

### 2.5 AnchorPerTemplateStage.transition

`_read_disk_artifacts(state, result, ["anchor_template_report.json"])`，**删 dict fallback**，`json.loads(raw[...])` → `_parse_and_wrap`。

### 2.6 DetailedDesignIntakeStage.transition

`_read_disk_artifacts(state, result, ["design_spec.json"], optional=["tiling_strategy.json", "data_flow.json"])`，删 dict 读。

### 2.7 DocgenStage.transition —— 不动

P6 已是磁盘优先（`glob("*_详细设计说明书.md")`，名称已放开）；agent_result.artifacts 仅用于 `_capture_decision_log`（无缺陷）。本步确认不回归。

---

## 3. StubBackend 配合落盘（src + ST）

设计/test_design transition 现磁盘强制，stub backend 必须像真 agent 一样把产物写进 cwd：

- **canonical `StubBackend.spawn`**（`capabilities/agent/stub_backend.py`）：返回 canned 前把 `result.artifacts` 落到 `working_dir`（`working_dir is not None and artifacts`，非 str 值 JSON 兜底）。模型真 agent 行为（§1.2 stub 应忠实于所模拟契约）。
- **ST `_StubBackend`**（`tests/st/test_design_pipeline_e2e.py`）：同样落 artifacts 到 working_dir（docgen md 仍按 P36 特判写）。
- **ST `_GroupStub`**（`tests/st/test_test_design_e2e.py`）：test-analyze/test-casedesign 的 JSON 落 working_dir（test-casegen 的 CSV/md 原已落盘）。

---

## 4. 爆半径（已核）

- `_parse_single` 经 `_DesignSubstage` + `_TestDesignSubstage` 被全设计/test_design substage 用 → 改它覆盖全产物读取，**不波及 codegen/cannbench/precision/deploy**（独立 Stage，不走此方法）。
- tiling segment：3 子类（split/buffer-kernel/precision-perf）。`is_satisfied` 新增不影响聚合（join 在 `design_tree.merge_forkjoin`，按模板 key 浅合并，不读 is_satisfied）。
- `_locate_artifact` 只在 design_substages.py 内用。
- 下游读者（integrate 聚合 tiling_results / validate）现保证产物落盘 → 聚合更可靠（修掉 CEL T1 缺段根因）。
- StubBackend 落盘仅当 `working_dir is not None and artifacts`：working_dir=None（无 workspace）或无 artifacts 的 spawn 不受影响。

---

## 5. 验证（TDD，§3.1/§3.4，不掩盖）

- **UT**（`tests/ut/orchestration/`）：939 passed（含 `test_design_substages` 119、`test_tiling_forkjoin`、`test_tiling_precise_rollback`、`test_advisory_routing`、`test_review_redirect`、`test_decision_log`、`test_detailed_design_intake`、`test_stages`）；全量 `tests/ut/` 1726 passed。
  - 新增/改 P62 用例：dict 兜底删除回归、名称放宽（Pascal/hyphen/前后缀）、歧义保守 None、精确优先、tiling 切片磁盘读 / dict-only fail / `is_satisfied`、CEL 回归（产物写 working_dir 外→fail）、missing_artifact 带 feedback。
- **ST**（非 heavy_llm）：96 passed（`test_design_pipeline_e2e` 6、`test_test_design_e2e` 6、`test_self_evolution_stages`、`test_integration`、`test_resume_cli`、`test_training_runner`、`test_decision_transcript`、`test_skill_invocation`、`test_testdesign_skill_invocation`）。
- **heavy_llm**（`test_design_docgen_tui_selfclosure.py` 等，§3.11）：跑前向用户确认；docgen 用 transition glob，受影响小。**特性交付前由用户在关键节点决策跑一次**。
- `git diff` 触及：`design_substages.py`（`_locate_artifact`+`_normalize_stem` 模块级、`_missing_artifact_error`、`_read_disk_artifacts`、`_parse_single` 删路径2、`_TilingSegmentStage.transition`+`is_satisfied`、4 自定义 transition）、`stub_backend.py`（落盘）、相关 UT、ST stub（`test_design_pipeline_e2e`/`test_test_design_e2e`）。**不动 runner / state / codegen / SKILL.md**。

---

## 6. 不向后兼容（§1.4）

agent-dict 兜底判 success 整条路径删除，不留别名 / 迁移分支 / deprecated 包装。产物读取唯一通路 = `_read_disk_artifacts`（磁盘）。
