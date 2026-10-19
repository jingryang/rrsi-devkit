# P47 — 详设反馈消费确定性闭环（skill 内自检）— 实施方案（第四层）

> 状态：**代码 + heavy_llm e2e 全部完成 ✅**——Step 1/2/4/5 已落（Step 3=P45 第一刀现状满足不动）；TDD 红→绿，UT 1623 + 非 heavy ST 1741 全绿；heavy_llm e2e 已验证：用例合并入 `test_design_tui_selfclosure.py::TestDesignFeedbackConsumption`，全文件 3/3 heavy PASSED in 415.83s（真实 LLM 消费 seeded bf16 反馈成立，§3.9 实证缺口闭合）。
> 层级：**第四层 / 实施方案**。精确到改哪个符号、什么顺序、怎么验证。
> 承接：L3 `25-feedback-consumption-closure-analysis.md`（§7 已拍板）。
> 约定：按符号定位（不写 file:line）；TDD 红→绿；外部依赖只读；§3.11 heavy_llm 执行需用户确认。

---

## §7 拍板结论（2026-07-07，用户认可倾向）

1. 自检 skill 落点 → **抽共享自检 skill + 各生成 skill 末尾调用**。
2. 消解判据 schema 形态 → **自然语言可执行描述**。
3. 多轮累积粒度 → **全量回验**。
4. 修不了的降级 → **halt 复用既有出口**。

---

## 实施步骤（按 L3 §6 时序）

### Step 1 — issue 迭代版本化（地基）

**改**：
- 三个 schema（`blocking_status.json` / `anchor_report.json` / `anchor_template_report.json`）：issue 加 `iteration` 字段（int，标发现轮次）。
- `ValidateStage` / `AnchorConsistencyStage` / `AnchorPerTemplateStage` 的 transition：写 issue 时带当前 iteration 号；`blocking_status` 不再整份覆盖——按迭代累积（issue 列表内每个带 iteration 即天然累积历史，不丢上一轮）。

**验证（UT）**：构造 2 轮 blocking → 断言两轮 issue 都在、`iteration` 各自正确（红：复现「第二轮覆盖丢第一轮」）。

### Step 2 — issue schema 补「消解判据」维度

**改**：
- 三个 schema：issue 加 `acceptance` 字段（自然语言可执行描述，「怎样算此 issue 已解决」，给 skill 自检用）。
- schema `required_keys` 把 `acceptance` 列为必填（产出端硬约束——判据写不出 = issue 不成立，§1.3 加载期校验）。
- validate/anchor 两个 SKILL.md：issue 产出规范加「每条必带 `acceptance`，且须 LLM 可执行（写不出可执行判据的 issue 不该产出）」。

**验证（UT + 加载期校验）**：schema example 带 `acceptance`；加载期校验 `acceptance` 必填。

### Step 3 — loopback 写 prompt（保留，不动）

= P45 第一刀 `_feedback_section`，现状已满足。**保留不动，降级为辅助提示**（主修复靠 Step 4）。

### Step 4 — 共享自检 skill + 生成 skill 末尾调用（核心）

**改**：
- 新建共享自检 skill（`stage-design/skills/ascendc-op-design-feedback-selfcheck/`，§2.2 资源归属 skill 目录）：职责 = 读当前轮 + 历史全部轮 issue（含 `acceptance`）→ 读产物 → LLM 自检每条 `acceptance` 是否满足 → 未消解内部修 → 修不了标 unresolved。
- 各生成 skill（`tiling-buffer-kernel` / `tiling-precision-perf` / `tiling-split` 等）SKILL.md 末尾加一步：调用共享自检 skill（§2.3 文件接力：读 `blocking_status` 类文件 + 自身产物）。
- **全量回验**：不只验当前 outstanding，回验历史全部轮 issue 无回归（依赖 Step 1 历史累积）。
- **降级 halt**：自检修不了的 issue 标 unresolved → stage halt（复用既有 halt 出口，不新造状态机）。

**验证（UT + heavy_llm e2e）**：
- UT：自检 skill 接线、issue 读取逻辑。
- **heavy_llm e2e（填补之前的实证缺口）**：seed 带 blocking issue 的 state（如「AC1: bf16 骨架门不可行，`acceptance`=产物中不再出现 bfloat16_t」）→ 走 Stage corrective 回退（真触发 `_feedback_section` + skill 自检）→ 断言下一轮产物**真的不再用 bf16**（不只验 schema 合法，验反馈点名的具体问题被消除）。**这是 §3.9 真正要求的守护，也是回答「LLM 会不会忽略反馈」的唯一实证。**

### Step 5 — python 侧日志 + 回归 + 收口

**改**：`design_substages` transition 读 `blocking_status` 打印 issue 摘要 + 迭代号（扩展 `_lint_issues`）。§1.2 可诊断性。

**验证**：全量 UT + 非 heavy ST + heavy_llm e2e（§3.11 用户确认）+ 四层文档收口。

---

## 关键时序与依赖

- **Step 1（迭代版本化）→ Step 2（acceptance）→ Step 4（自检）**：Step 4 依赖 1（历史）+ 2（判据），不可前置。
- Step 3 现状满足，不阻塞。
- Step 5 末尾收口。

---

## 不在本方案范围

- codegen/verify 阶段「需运行才能判」的 issue（精度/性能/编译）——L3 §3.3 边界，另议。
- bug-fix agent / 框架状态机——L3 §5 已否决。

---

状态：**方案已定，待用户授权实施**。
