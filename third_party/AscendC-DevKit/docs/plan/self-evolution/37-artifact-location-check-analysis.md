# P62 — 设计阶段产物落盘位置无校验 — 方案分析（第三层）

> 层级：**第三层 / 方案分析**。有哪些选项、选了哪个、为什么。调研中演进、拍板后冻结。
> 依据：L1 `06-problems.md` P62（客观事实）；落地为 L4 `37-artifact-location-check-impl.md`。

---

## 0. 问题陈述（引用 L1，不重复产权）

设计阶段六条产物读取路径（`_parse_single` 路径2 dict 兜底、`_TilingSegmentStage.transition` 直接读 dict、Integrate/Validate/AnchorPerTemplate/DetailedDesignIntake 自定义 transition 读 dict）**都不校验「落盘位置正确性」**。CEL T1 buffer-kernel 实证：产物被 cwd 泄漏写到仓根，聚合器把 T1 默默聚成 `{split only}` → validate 远下游判 GV8 不完整 → corrective loopback，**位置错误本身零信号**。违反 §1.2 可诊断（不变式被假设却从未验证，fallback 还主动绕过）。

用户拍板四点：① Python 侧强制校验落盘目录；② 文件名适当放宽；③ 没落对 → 带原因重 spawn 当前 stage；④ 移除 dict 兜底；⑤ **孤儿泄漏不检测**。

---

## 1. 机制可行性（不造新机制）

- runner `_run_stage_body`：`terminal = has_all(provides) AND is_satisfied()`。不满足 → 自动重 spawn；iteration 耗尽才 halt。**既有 iteration 重试通道可直接复用**。
- `_build_prompt` 注入 `state.user_feedback` → 下一轮 prompt 告诉 agent 产物该落哪。**既有 feedback 通路**。
- 结论：不新增状态机 / 出口 / 机制。把「位置错」翻译成 `last_error + user_feedback + provides 不写 / is_satisfied=False`，runner 自动重 spawn。

---

## 2. 选项

### 选项 A：纯磁盘强制 + 名称放宽 + 缺失重 spawn（**选定**）

- 所有产物读取经单一 helper：磁盘 required 文件必须在 working_dir（位置硬），名称 `_locate_artifact` 放宽（精确 > 归一化相等 > 前后缀容忍；歧义保守 None）。
- 缺失/位置错 → `_missing_artifact_error`（last_error + user_feedback）→ runner 重 spawn。
- 删 agent-dict 兜底（§2.5 唯一通路）。
- tiling 聚合字段加 `is_satisfied` 检本切片。

### 选项 B：磁盘 + dict 兜底（保留兜底）

- 磁盘优先，磁盘无则 fallback dict。**否决**：这正是原缺陷——dict 兜底让位置错绿灯（CEL T1 实证），保留兜底 = 保留缺陷。违反 §2.5（新旧并存）+ §1.2（可诊断）。

### 选项 C：仅 feedback 不强制

- 位置错只记 feedback，仍接受 dict 产物。**否决**：feedback 是软引导，无强制则 agent 可忽略、位置错仍绿灯。等于不改。

### 选项 D（子决策）：孤儿泄漏检测

- 巡检 working_dir 外是否有 stage 产物泄漏。**用户裁定不做**：① 泄漏检测是另一独立职责（全局文件巡检），与本步「读取侧位置校验」正交；② 泄漏根因（cwd 退化）已由 P40 修，读取侧强制已是兜底；③ 巡检误报成本高（难判定「仓根某文件是否本 stage 产物」）。本步只做读取侧单通路。

---

## 3. 决策记录（D1-D4）

- **D1（名称放宽的尺度）**：精确名优先；归一化（去 `[_\-.]` + lower）后完全相等（rank 0）；前缀/后缀容忍（rank 1）；**同 rank 多命中保守 None**（触发重 spawn，不猜——猜错比重跑代价大，§1.2 可诊断）。不复用 `issue_fingerprint`（语义不符）。
- **D2（缺失的反馈通道）**：`_missing_artifact_error` 同设 `last_error`（halt 路由用）**与** `user_feedback`（下一轮 prompt 用）——区别于 `_error`（只 last_error）。两条信号各司其职：last_error 决定 iteration 耗尽后 halt，user_feedback 驱动重 spawn 修正。
- **D3（tiling 聚合字段的满足度）**：`provides=["tiling_results"]` 是聚合字段，split 先填则 has_all 恒 True → 靠 `is_satisfied` 检**本 segment_key 切片**而非聚合字段。否则 buffer-kernel 切片缺失也会被判 terminal（绿灯）。
- **D4（单通路归属）**：`_read_disk_artifacts` 放 `_DesignSubstage`（base-class），六条路径 + test_design（继承）全走它。`_locate_artifact`/`_normalize_stem` 放 design_substages 模块级（design 专用，不过度抽象到 util）。`decision_log.json` 作隐式 optional 并入单通路（base-class `_capture_decision_log` 统一找它）——单通路是「raw 里有什么」的唯一权威。

---

## 4. 四把尺子论证（§1.2，选项 A）

- **可维护**：澄清不变式「agent 在 working_dir 跑→产物落 working_dir」，由读取侧强制守住；与 P4（确定性磁盘读取）哲学一致；删 dict 兜底 = 消除「两套真理源」。
- **可扩展**：同类新情况（任何 design/test_design stage、任何 cwd 泄漏）自动正确归位——单通路 + 名称放宽，无需逐 stage 打补丁。
- **可诊断**：位置错当场拦截 + 带 feedback（含 wd 路径）重 spawn，而非绿灯放行到远下游 validate 才爆 GV8（CEL 那样耗 3h）。error_type=`missing_artifact` 是可观测信号。
- **架构合理**：校验落在「产物读取」职责边界（transition），不越层（不改 runner 状态机、不全局巡检）。stub backend 同步落盘 = 忠实模拟真 agent 契约。

单一方案满足全部四尺，无需组合兜底。

---

## 5. 与既有修复的关系

- **P4（确定性磁盘读取）**：P62 是 P4 的「位置正确性」补完——P4 保证「从磁盘读」，P62 保证「读对位置（working_dir）」。
- **P40（cwd 修复）**：P40 修泄漏根因（cwd 退化），P62 是读取侧防御（即使泄漏也不绿灯）。
- **P6（docgen 文件名放开）**：docgen 已磁盘优先 + 名称放开，P62 确认其不在改造范围（无 dict 兜底缺陷）。
- **P8（stale anchor_report 分离）**：正交（current/history 语义 vs 落盘位置），互不依赖。

---

## 6. 已否备选

- **runner 层加全局位置巡检**：越层（runner 不应懂 design 产物布局）、误报高。否。
- **manifest 声明每 stage 期望文件名 + 严格匹配**：名称过严（LLM 命名非确定，P6 已证），且 manifest 是 skill 资源不应耦合 stage 布局。否——名称放宽（D1）替代。
- **保留 dict 兜底作「宽容兜底」**：见选项 B，保留缺陷。否（§2.5）。
