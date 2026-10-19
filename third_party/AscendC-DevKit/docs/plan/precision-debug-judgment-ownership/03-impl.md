# precision_debug 判断决策权缺失 — L4 实施方案（2026-08-24）

> 层次：**L4 实施方案**。记录具体改哪个函数、什么顺序、怎么验证。
> 问题记录见 `01-problems.md`（L1）；方案分析见 `02-analysis.md`（L3）。
>
> 本方案在 P3 减法（`precision-debug-blindspot/`）已删「控模型」结构的基础上**补功能**：
> 把「失败性质判定 / 打法选择」的判断决策权交还模型，框架管弹药 + 边界 + 可观测。
> **不重建候选池 / 不恢复强制回炉 / 不新增独立 phase**。

## 一、改动总览

| # | 层 | 文件 | 改动 |
|---|----|------|------|
| A | skill | `diagnose-skill/SKILL.md` | 重写定位方法：先全局理解 → 假设驱动 → 可选弹药 |
| B | skill | `diagnose-skill/references/techniques/*.md` | printf/注释降级从「流程」改「可选参考」 |
| C | skill | `diagnose-skill/schema/precision_diagnose.json` | `_summary` 加 `hypothesis`/`validation`/`stalled` |
| D | agent | `.claude/agents/ascendc-precision-diagnose.md` | 同步「判断决策权在模型」+ 假设纪律 |
| E | framework | `substages.DiagnoseSubstage` | `resolve_condition` 加 `stalled` 出口 + transition 读 `stalled` |
| F | framework | `precision_debug_tree.py` | transition_table 加 `stalled` 路由 |
| G | framework | `substages.RunTestsSubstage` | prompt 分层放权：路由判断交模型，status 框架算 |
| H | framework | `substages.DiagnoseSubstage` | prompt 注入「验证范围自主决定」 |

## 二、逐项实施

### A. `diagnose-skill/SKILL.md` 重写定位方法（核心）

**现状**：`## 就地定位方法（不枚举，靠 ground-truth + 受控实验）` 按 failure_type 分步框死
（compilation/runtime/precision 各有固定步骤）。

**改为**：

```markdown
## 定位方法（假设驱动，判断决策权在你）

### 第 0 步：先全局理解（动手前必做）
读完整 kernel 源码 + golden + 失败证据，形成认知：
- 这个算子做什么、数据流是什么
- 失败症状（如全零输出）可能指向哪层（局部 API/对齐 还是 全局算法/数据流）
这决定你选哪条路，不是「就地修那一处」的机械动作。

### 第 1 步：形成假设（改动必须有预测）
动手前写结构化假设（写进 _summary.hypothesis）：
- hypothesis：我改 X 因为认为根因是 Y
- evidence：支持该假设的证据（golden 对比 / printf 输出 / 数据流分析）
- predict：改完后应观察到的现象（"M counter 应从 0 变为 19058"）

### 第 2 步：验证假设 → 更新认知（无论对错都回填）
- 假设对 → 收敛修，commit
- 假设错 → 排除这个方向，写 validation，生成新假设（认知推进）
- 禁止无 predict 的改动（那是试错法，不产生新信息）

### 可选弹药（按需选用，不框死）
| 手段 | 何时用 |
|------|--------|
| 全局推演 | 症状指向全局算法（全零/全错/数据流断裂）→ 首选，脑内跑算法找根因 |
| golden 比对 | 不一致时对照 numpy 期望找发散点 |
| printf 二分 | 数值发散时插探针收敛到首个错误位置（references/techniques/printf-bisect.md）|
| 注释降级 | runtime crash 时注释可疑路径看崩不崩（references/techniques/comment-bisect.md）|
| 知识库查证 | 不熟悉 API 约束查支持矩阵/round mode |

### 判断判据（帮模型，非 gate）
- 症状指向局部（一处 API/对齐/dtype）→ 就地查证 + 修（快）
- 症状指向全局（全零/数据流断裂）→ 先全局推演，再动手（可重写整段，不受「就地修那一处」限制）
- 任意手段，只要是你认为最有效的——框架不限制打法

### 尽力后的诚实报告（不是放弃）
当假设空间已系统穷尽（所有方向试过、认知无法再推进）：
- 写 _summary：`stalled=true` + 已试方向 + 为何认为超范围
- 输出 RESULT: DIAGNOSED_STALLED
- 这是「模型尽力后的诚实报告」，供上游/人工接续，不是空手放弃
```

### B. `diagnose-skill/references/techniques/*.md` 改「可选参考」

**现状**：printf-bisect.md / comment-bisect.md 是「何时用/怎么做/告诫」——基本已是可选参考。
**微调**：开头加「本技巧是**可选弹药**，不是强制流程；是否使用由你基于对问题的理解判断」。

### C. `diagnose-skill/schema/precision_diagnose.json` 加字段

`_summary` 增加：
```json
"hypothesis": {"type": ["object", "null"], "properties": {
    "hypothesis": {"type": "string"},   // 我改 X 因为认为根因是 Y
    "evidence": {"type": "string"},      // 支持证据
    "predict": {"type": "string"}        // 改完后应观察到的现象
}},
"validation": {"type": ["array", "null"], "items": {"type": "object"}, 
    "description": "每次验证结果回填：confirmed/refuted + 新认知"},
"stalled": {"type": "boolean", "default": false,
    "description": "假设空间系统穷尽，诚实报告（DIAGNOSED_STALLED）"}
```

### D. `.claude/agents/ascendc-precision-diagnose.md` 同步

Step 2「就地定位（按 failure_type 分支）」改为「先全局理解 → 假设驱动 → 可选弹药」。
Hard rules 加：
- **判断决策权在你**：路由判断（局部 vs 算法级）由你基于完整上下文做，框架不替你定打法
- **改动必须有预测**（`_summary.hypothesis.predict`），验证必回填 `validation`
- **不试错**：无 predict 的改动禁止（那是盲试，不推进认知）
- **尽力后诚实报告**：假设空间穷尽写 `stalled=true`，输出 `DIAGNOSED_STALLED`

### E. `substages.DiagnoseSubstage` — `resolve_condition` 加 `stalled` 出口

`resolve_condition`（L2292）在 `upstream` 之后加：
```python
# §P5: 模型尽力后诚实报告——假设空间系统穷尽（stalled），非上游缺陷。
# 这是「模型判断已尽力」，不同于 upstream（上游的错）；框架按已尽力收敛，
# 不再无限 retry。DC 由 diagnose 写 _summary.stalled=true 驱动。
if dc.get("stalled"):
    return "stalled"
```
transition 里 `_extract_debug_checkpoint` 读 `stalled`（与 `upstream_signal` 同源）。

### F. `precision_debug_tree.py` — transition_table 加 `stalled`

```python
"diagnose": {
    ...
    "stalled": ("__escalate__:stalled", "validation"),
    ...
}
```
根 workflow 的 precision_debug 行：`"stalled": ("__halt__", "escalation")` 或
`cannbench_adapt` 软门（对齐 `exhausted` 处理——已尽力保留 best_commit，交 eval）。

### G. `substages.RunTestsSubstage` — prompt 分层放权

`_phase_prompt`（L1697）保留「全量回归 / status 框架算」的确定性契约（防 P2 历史 bug 回归），
但加一段：
```
## 路由判断在你
「这些失败是什么性质」由你判断（局部 API 错 / 算法级 bug / 上游契约错），
这决定后续 diagnose 怎么处理。你在 failed_case_queue 里如实反映失败性质，
供 diagnose 决策。
```

### H. `substages.DiagnoseSubstage` — prompt 注入「验证范围自主决定」

`_phase_prompt`（L2133）加：
```
## 验证节奏由你定
算法级 bug 可「改完整个算法再验证」，不必每改一处就全量回归。
run_tests 最终全量判定，但中间的验证范围/节奏由你判断（改一处验证一处，
或改完一起验证）。
```

## 三、验证（TDD）

### UT
- `resolve_condition`：`stalled=true` → 返回 `stalled`；无 stalled → 原行为不变
- transition_table：`stalled` 路由存在且接 `__escalate__:stalled`
- `_extract_debug_checkpoint`：读 `stalled`
- diagnose prompt 含「假设驱动 / 判断决策权在你」；run_tests prompt 含「路由判断在你」

### ST
- **heavy_llm**（§3.11 跑前向用户列清单）：`test_precision_diagnose_hypothesis_driven.py`——
  构造一个算法级 bug 现场，断言 diagnose：① 先读全（有全局理解痕迹）② 改动带 hypothesis/predict
  ③ 验证回填 validation ④ 若穷尽则 stalled=true（而非无限 retry）
- 现有 `test_precision_diagnose_inplace_loop.py`（局部 bug 就地修）保持通过——验证「局部 bug 仍快」

### 全量
- 全量 UT（非 heavy ST）绿；`validate_skill_map()` 无 phantom

## 四、风险与回退

| 风险 | 缓解 | 回退 |
|------|------|------|
| 模型能力依赖（假设驱动执行不了） | predict 判据强制验证对照；ST 实证 | `git revert` skill/schema 层 |
| 确定性下降（模型定节奏） | run_tests 全量权威兜底 + status 框架算 | 分层放权单独 revert |
| 回归 P2 历史 bug（run_tests 写错） | 只放「失败性质」判断，status/best_* 框架算 | revert G |

## 五、关键文件

- `.claude/skills/ascendc-precision-diagnose/SKILL.md`（重写定位方法）
- `.claude/skills/ascendc-precision-diagnose/references/techniques/*.md`（可选参考标注）
- `.claude/skills/ascendc-precision-diagnose/schema/precision_diagnose.json`（hypothesis/validation/stalled）
- `.claude/agents/ascendc-precision-diagnose.md`（判断决策权 + 假设纪律）
- `src/ascendc_devkit/orchestration/stages/precision_debug_substages.py`（resolve_condition + prompt）
- `src/ascendc_devkit/orchestration/precision_debug_tree.py`（transition_table）

---

## 六、2026-08-25 用户新增需求（实施范围扩展）

### N1 — run_tests 确定性执行下沉 Python（杜绝「LLM 当执行器」）

**问题**：run_tests 的绝大多数动作是确定性执行（跑测试 / 解析 result.json / 构建
failed_case_queue / 分类 failure_type / 写 control.json）——这些应该写成 Python，不需要 LLM。
现在用 LLM 当「执行器」跑它们，慢、贵、且容易写错（才需要 §P2 框架重跑脚本核对）。

**原则**：确定性执行 → Python；只有「需要读完整上下文、框架规则做不了」的判断才留 LLM。
§1.15（通用行为统一抽象）+ §1.14（留帮模型删控模型）。

**形态**（按用户 2026-08-25 决策「run_tests 相关操作就是诊断 agent 调用的工具函数，需决策的部分交给诊断 agent」，一步到位实施）：
- **纯 Python 测量**：跑测试、解析结果、构建 failed_case_queue、派生统计（rounds/best_*/history/observed_issues 框架派生非 LLM）、写 control.json——由新增 `RunMeasure` Action 确定性执行（`_measure` 单点，§1.15），脚本收敛到 `src/.../stages/precision_debug_run_tests/scripts/`
- **判断全归 diagnose**：run_tests 不再 spawn agent，`failure_type`/失败性质判断由 diagnose Step 0 做（N2）；run_tests node 保留（graph 构造性「先测量再诊断」不变，§2.9）
- **删除项**（§2.5）：`.claude/agents/ascendc-precision-run-tests.md` + `.claude/skills/ascendc-precision-run-tests/` + STAGE_SKILL_MAP 条目

**验证**：run_tests 的确定性测量有 UT 守护（`_measure` 行为 / measure_result abort / RunMeasure 分支）；判断归 diagnose 有 diagnose context golden 契约 UT。

### N2 — 上游问题原地兜底解决（不直接 halt）

**问题**：现在上游问题（编译失败 / schema 不匹配 / golden 缺 get_input / 算子未注册 / devkit
抛错）diagnose 直接上报 halt，无「先尝试本地修」的兜底。

**需求**：上游问题也要有**原地兜底解决**的能力——diagnose 先尝试在本地（本阶段职责内）解决，
**解决不了才上报**。不是「遇到上游就 halt」。

**形态**（对齐 §1.2「宽容兜底做 last resort」）：
- diagnose Step 0 上游判据：从「直接上报」改为「**先尝试原地兜底**」——
  - 编译失败 / schema 不匹配：先看是否工程内可修（plugin 注册/声明/manifest 是本阶段职责），能修就地修
  - golden 缺 get_input / 算子未注册：若工程内能补/能修，就地修；**确实超出本阶段职责**（golden 语义错 / devkit 框架错）才上报
- 混合失败按主导归类；**拿不准先倾向本阶段**（能修就修，别轻易上报）
- 上游上报仍是 last resort（试过兜底解决不了才 halt）

**验证**：heavy_llm ST 断言 diagnose 遇上游信号先尝试本地修，修不了才上报；现有 upstream 测试
保持（上报路径仍存在，只是加了「先兜底」前置）。

### 与既有改动的关系

- N1 与 G 步（run_tests prompt 分层放权）收敛于「判断归模型」——G 步是「路由判断交模型」，N1 是
  「确定性下沉 Python + 判断统一归 diagnose」：run_tests 最终 = 纯 Python 测量（`RunMeasure`）+ 判断全在 diagnose。
- N2 与 Step 0 上游判据相关——从「直接上报」改为「先兜底后上报」。

## 七、实施进度

| 项 | 状态 |
|----|------|
| A-D 引导层 | ✅ 已实施 + 提交 `63b6aa41` |
| E-H 框架层（stalled + self_check + agent 瘦身 + adapter） | ✅ 已实施 + 提交 `1aa5b74e` |
| N2 上游兜底（agent/skill/prompt 三处 + UT） | ✅ 已实施 + 提交 `f8216e37` |
| N1 run_tests 下沉 Python（`RunMeasure` 纯 Python 测量） | ✅ 已实施 + 提交 `a3b0e6cf`；heavy_llm 全闭环验证通过（`6a25613c`：实测揭出并修复 device-0 吞没、shell 换行两 bug） |
| 弱模型就绪（拒因可见 + 产物缺失定向提示 + infra 分流 + 死线复活） | ✅ 已实施（待提交）。消费继承链公共能力（`_missing_artifact_error`/`_infra_no_product_error`/孤儿搬回），不动 design。产物缺失走 rounds 预算不进熔断（「能解决尽量解决」）；infra 才熔断（P93 不教修路径）；`last_reject_reason` 按轮 consumed-once；`_last_agent_transcript` setter 迁 diagnose（N1 剪断的 9a883cc9 接线复活）；首轮不再误注入"被杀" |
