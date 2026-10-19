# step-9 L4-d — 守护测试（§P9 真实注入 + TUI 自闭环 + 契约同源 lint）（2026-06-17）

> **实施状态（2026-06-17）：任务1（§P9 真实注入守护）✅、任务2（TUI 自闭环守护）✅ 均已实施并通过
> 真实 LLM；任务3（UT lint）部分已由 L4-c 的 `test_testdesign_selfcontained.py` 覆盖。step-9 L4 全部完成。**
> - 任务1：`tests/st/test_testdesign_skill_invocation.py`（仿 design `test_skill_invocation.py`），
>   参数化三 substage，断言首消息 `/stage-testdesign:<skill>` 触发后 transcript 出现 SKILL.md-only
>   术语。真实 LLM 跑（16 分钟，3 substage × ≤3 attempt）：**analyze ✓ / casedesign ✓** 一次通过；
>   casegen 初次失败——经查 transcript **证明 skill 已注入**（agent 跑了
>   `scripts/{testcase_generator,duplicate_checker,self_checker}.py`、引用 `Self_Check_Report` 等
>   SKILL.md-only 内容），失败是**marker 选词问题**（用了精确短语「自检校验/去重脚本」，agent 复述为
>   「自检/去重」+ 脚本名）。已把 marker 改为脚本名（SKILL.md-only、prompt 不含、transcript 稳定命中
>   3×），定向重跑 casegen **121.69s 一次通过 ✓**。⇒ 三 substage 的 §P9 真实注入全部真实链路验证通过。
> - 任务2：`tests/st/test_testdesign_tui_selfclosure.py`（**不起 DevKit 框架**，裸目录直接 spawn，
>   模拟 TUI 人类 `/<skill>`）：
>   - **单 skill 文件 I/O ✓**（188s）：seed `test_analysis.json` → spawn casedesign → 读文件、写出
>     符合 schema 的 `test_casedesign.json`（F1+F2 在无框架下成立）。
>   - **skill 链文件接力闭环 ✓**（22 分钟，attempt 3 通过）：seed 三件套 → analyze→casedesign→casegen
>     在**同一共享目录**串跑、**spawn 之间零注入**，最终 `testcase_generator.py` 产出 5 份分类 CSV
>     全部 `parse_testcase_csv` 可解析（6+10+6+4+12 用例）。**这是第一准则 #4 的端到端验收**：skill 链
>     靠文件接力自闭环、不依赖工程框架。
> - 关键经验：
>   1. §P9 守护的 marker 必须选「skill 真正驱动行为时会留痕、且 prompt 绝不含」的标识
>      （脚本名 > 方法学短语），否则真注入也会因复述差异误报。
>   2. **真实可靠性发现（待 L4 后续跟踪，非阻塞）**：casegen agent **偶发**不跑确定性脚本
>      `testcase_generator.py`、而是**手写 CSV**——手写版列名漂移（`stc_format` 而非 `stc_input_formats`、
>      多 `stc_precision_abs/stc_case_level` 等），被适配层正确拒绝（ws_1 attempt）。有界重试下后续
>      attempt 跑了脚本→产出合规 CSV 通过（ws_2）。这暴露：**SKILL.md 应更强约束「必须用脚本生成、
>      禁止手写 CSV」**，以降低对重试的依赖。已登记为 step-9 收尾的 skill 正文强化项（见下「后续跟踪」）。

> 层级：**L4 / 实施方案**。依据 `02-analysis.md`（§P9 真实守护）+
> `../first-principle-tui-compat/02-analysis.md`（开放点 2「TUI 自闭环守护」+ 第一准则回归防线）。
> 前置：L4-a/b/c。本片是第一准则在 test_design 的**回归防线**——没有它,前三片的成果会悄悄退化。
>
> 范围：① §P9 真实链路守护（skill 方法学真注入,非 stub）；② TUI 自闭环守护（单 skill 文件输入能跑、
> skill 链文件接力能闭环,不起 DevKit 框架）；③ 契约同源 + 自包含 lint（UT 级,毫秒）。

## 已核实事实（开工前提）

1. **§P9 守护先例**：`tests/st/test_skill_invocation.py`（design 的 §P1/§P9 硬证）——`@pytest.mark.llm`,
   不 mock SDK/CLI,用**真实 substage** build prompt（首消息真带 `/stage-design:<skill>`）,spawn 真 agent,
   查 transcript 里出现**仅 SKILL.md 才有的术语**证明方法学注入。test_design 直接仿它。
2. **stub e2e 现状**：`test_test_design_e2e.py` 用 stub backend,**不验证 skill 真实注入**（L1 T3 影响:
   §P9 在 test_design 真实链路从未验证）。stub 测编排,llm 测真实注入——两者并存,职责不同（CLAUDE.md
   测试分层）。
3. **llm 标记语义**：`@pytest.mark.llm` = 运行时真依赖（联网真跑、禁 mock）;有界重试内至少触发一次
   即判可达（吸收 LLM 抖动,不退化成 mock）。

---

## 任务 1 — §P9 真实注入守护（`tests/st/test_testdesign_skill_invocation.py`，@pytest.mark.llm）

- 仿 `test_skill_invocation.py`,对三个 test substage 各验一次「方法学真注入」：
  - 用真实 `TestAnalyzeStage`/`TestCaseDesignStage`/`TestCaseGenStage` 的 `actions()` build prompt
    （首消息真带 `/stage-testdesign:<skill>`,与生产一致）。
  - spawn 真 agent（`ascendc-design-generator`,真加载 stage-testdesign plugin）。
  - 查 transcript：出现**仅各 SKILL.md 才有**的术语（如 analyze 的「章节拆解执行模式」、casedesign 的
    「知识库自学习/风格校准」、casegen 的「自检校验/反向算子名」）→ 证明 slash 注入了方法学。
  - 有界重试内至少一次命中即通过（吸收抖动）。
- **这是 L1 T3「§P9 在 test_design 真实链路从未验证」的正式闭合。**

---

## 任务 2 — TUI 自闭环守护（开放点 2，第一准则核心防线）

> 证明:不起 DevKit 框架,① 单 skill 从文件输入能产出;② skill 链靠文件接力能闭环。

### 2.1 单 skill 文件输入守护（`tests/st/test_testdesign_tui_single.py`，@pytest.mark.llm）

- 在一个**裸临时目录**（非 DevKit workspace 布局）放好某 skill 的约定输入文件
  （如 casedesign 需要的 `test_analysis.json`,内容取自真实样例）。
- **不经任何 stage/runner/State**,直接 spawn 一个 agent,首消息 `/stage-testdesign:<skill>` + 「从当前
  目录读输入文件」——模拟 TUI 里人类 `/skill` 的行为。
- 断言:skill 读到文件输入、产出约定输出文件（`test_casedesign.json`),且产物满足 skill 目录 schema。
- ⇒ 证明 F2（输入走文件）+ F1（契约随 skill）在无框架下成立。

### 2.2 skill 链文件接力闭环守护（`tests/st/test_testdesign_tui_chain.py`，@pytest.mark.llm）

- 裸临时目录放好链首输入（三件套 JSON + requirement.json）。
- **手动**依次 spawn analyze→casedesign→casegen（每次首消息对应 slash + 「读当前目录」),**共享同一
  目录**,不经 DevKit 编排、不在 spawn 之间注入任何东西。
- 断言:每步读到上一步留在目录里的产物文件(接力生效),最终产出 13 列 CSV 且 `parse_testcase_csv` 能解析。
- ⇒ 证明 F3（文件接力在 TUI 自闭环）。**这是第一准则 #4 的验收测试。**

---

## 任务 3 — 契约同源 + 自包含 lint（UT 级，毫秒，无 LLM）

> 这些是确定性守护,放 UT,每次 `pytest --quick` 都跑,防漂移。

### 3.1 SKILL.md 内联契约 ⇄ schema 文件 同源（防 L4-a 任务 3.2 的漂移）

- `test_testdesign_contract_sourcing.py`：解析三 SKILL.md 的「## 输出」段复述的 required_keys,
  比对本 skill `schema/*.json` 的 `required_keys`,不一致即 fail。

### 3.2 接力文件无控制流字段（防 L4-b 收敛-3 退化）

- 断言 chain_context.json 的约定 schema 只含数据指针键（op_name/output_dir/produced),
  出现 status/retry/gate 等控制流键即 fail（M4 纪律的回归防线）。

### 3.3 自包含 lint（落实 L4-c 任务 4）

- `test_testdesign_selfcontained.py`（L4-c 已起头,这里并入 CI 守护）：三 SKILL.md + schema 引用
  无 plugin 外路径;模拟「plugin 目录拷出到隔离路径」后三 skill 所有相对引用仍可解析（plugin 取出即完整）。

---

## 验证与运行

- llm 守护（任务 1/2）：`pytest -m llm tests/st/test_testdesign_*.py`（需真实 LLM,CI 全量模式跑）。
- UT lint（任务 3）：`pytest --quick tests/ut/skills/`（毫秒,每次内环跑）。
- 全量回归:`pytest tests/ut tests/st -q`。

## step-9 收尾自检（四片闭环）

- L4-a：拆 substage + schema 迁 skill 目录 + SKILL.md 自带契约 ✅（结构地基）
- L4-b：输入物化文件 + 接力修复 ✅（F2/F3 落地）
- L4-c：资源自包含 + 悬空清理 ✅（F4 落地）
- L4-d：§P9 真实注入 + TUI 自闭环 + 同源 lint ✅（回归防线）
- ⇒ test_design 成为第一准则首个落地验证场景;通过后,step-10 的 design 回溯复用本套范式与守护模板。
