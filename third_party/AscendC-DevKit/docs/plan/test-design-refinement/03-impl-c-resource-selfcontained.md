# step-9 L4-c — 资源自包含 + 悬空引用清理（F4）（2026-06-17）

> **实施状态（2026-06-17）：✅ 已实施并验证。**
> - 任务1（common-rules 悬空）：采情形 B（全仓不存在、各 skill 已自带 `rules/`），**删除三处引用**，
>   改指本 skill `rules/core_rules.md`。
> - 任务2（知识库路径）：casedesign 的 `.claude/AIInfra-OPTest_knowledge/` → 本 skill `references/`。
> - 任务3（绝对路径）：generate-case 的 `D:\work\testdesign\...` Windows 路径 → CWD 相对示例。
> - 任务4（加载期校验）：以 `tests/ut/skills/test_testdesign_selfcontained.py` 守护——无 plugin 外
>   路径引用 / 无 workflow_context.json / 无强制 /clear / schema 随 skill 走。
> - 验证：21 个自包含守护测 + 全量 UT 1258 passed。三 SKILL.md 全仓 grep 无 live 外部引用
>   （仅余 changelog 中说明「已删除」的负向文字）。

> 层级：**L4 / 实施方案**。依据 `../first-principle-tui-compat/02-analysis.md`（F4 解法 + §F4 补充证据
> + 收敛-2 自包含粒度=plugin）。前置：L4-a/b。
>
> 范围：把 testdesign 三 skill 对**自身目录之外**资源的引用全部消除——悬空引用补建/删除、
> 绝对路径改相对、知识库路径指向 skill 内 `references/`。目标：plugin 取出即完整（收敛-2）。

## 已核实事实（开工前提，全部 grep 实证）

1. **外部引用共 5 处**（`grep .claude/rules|.claude/AIInfra|D:\` 三 SKILL.md）：
   - `analyze/SKILL.md:525` → `.claude/rules/common/AIInfra-OP-testdesign-common-rules.md`
   - `generate-casedesign/SKILL.md:14`、`:507` → 同上 common-rules
   - `generate-casedesign/SKILL.md:509` → `.claude/AIInfra-OPTest_knowledge/` 目录
   - `generate-case/SKILL.md:204` → `D:\work\testdesign\...合并版.md`（Windows 绝对路径,示例残留）
2. **两个被引资源全仓不存在**（§F4）：`find` 全仓无 `common-rules.md`、无 `AIInfra-OPTest_knowledge/`
   → **悬空引用**。
3. **真实资源已在 skill 内**：每个 skill 自带 `rules/`（analyze 有 `core_rules.md`/`document_skeleton.md`
   等、casedesign 有 `core_rules.md`/`generalization_rules.md` 等）;casedesign 知识库案例（16 个
   `案例*.md`）已在其 `references/`。
4. **分发单元 = plugin**（`plugin.json name=stage-testdesign` 打包 3 skill）→ 自包含边界 = plugin 完整。

---

## 任务 1 — common-rules 悬空引用处置（3 处）

> 决策依赖 L3 开放点 3「核实其规则是否有实质内容需保留」。本片落地分两种情形,实施时二选一:

### 情形 A：common-rules 确有实质规则内容（git 历史/其他分支可寻回）

- 寻回该文件,放 **plugin 根的共享位**：`.claude/plugins/stage-testdesign/shared/AIInfra-OP-testdesign-common-rules.md`
  （收敛-2:多 skill 共用 → plugin 根）。
- 三处引用改相对路径指向 plugin 内共享位。
- 校验:三 skill 都能从 plugin 内解析到它（不出 plugin）。

### 情形 B：common-rules 无实质内容 / 寻不回（很可能，因全仓悬空）

- **删除三处引用**;把其本应承载的「通用表格格式/层级规范」检查项,确认是否已被各 skill 自带的
  `rules/core_rules.md` 等覆盖——若已覆盖,直接删引用;若有缺口,把缺口规则内联进各 skill 的
  `rules/core_rules.md`（自包含,接受少量冗余）。
- **倾向情形 B**：全仓悬空 + 各 skill 已有 `rules/`,大概率是移植遗留的死引用。L4 实施时先 `git log`
  确认,无内容即按 B 删。

---

## 任务 2 — 知识库路径改 skill 内 references/（1 处）

- `generate-casedesign/SKILL.md:509`：`.claude/AIInfra-OPTest_knowledge/` → 改为本 skill 目录相对
  `references/`（案例实际所在,已实证 16 个 `案例*.md`）。
- 同步核对 SKILL.md 正文「知识库自学习机制」的路径映射表（`:88-103` 规则ID→目录名）——确认其拼接
  根是 `references/`（`:108-115` 伪码 `knowledge_root="references"` 已对,只 `:509` 索引段写错）。
  即:**机制本身已指向 references/,仅文末「核心规范遵循」段的路径写成悬空目录**,改这一处即可。

---

## 任务 3 — 绝对路径示例清理（1 处）

- `generate-case/SKILL.md:204`：`D:\work\testdesign\...合并版.md` 是 Windows 绝对路径示例残留
  （违「自包含/可移植」）。改为相对示例：`<当前工作目录>/{算子名}测试设计方案_合并版.md`,
  与 L4-b 修好的接力输入文件一致。

---

## 任务 4 — 加载期自包含校验（呼应 CLAUDE.md「加载期校验优于运行期暴露」）

- 扩 `PluginLoader.validate`（或 skill_config §P4 校验）：扫 stage-testdesign 三 SKILL.md,
  断言**无指向 plugin 之外的路径引用**（正则匹配 `.claude/rules/`、`.claude/AIInfra`、盘符 `[A-Z]:\`、
  `/home/`、`~/` 等),命中即加载期告警。这道守护防止未来再引入外部依赖（第一准则回归防线的一部分）。

---

## 验证（先红后绿）

- 红测 `tests/ut/skills/test_testdesign_selfcontained.py`：
  - 三 SKILL.md grep 不到 plugin 外路径（`.claude/rules/`、`AIInfra-OPTest_knowledge`、盘符、`/home`、`~`）。
  - casedesign 知识库引用解析到本 skill `references/`,且该目录确有 `案例*.md`。
  - common-rules 引用：情形 A 解析到 plugin 内共享位;情形 B 已删且规则有内联兜底。
  - 加载期校验（任务 4）：人为塞一个外部路径引用 → validate 报错。
- 回归全量 UT/ST。

## 与后续片交接

- **L4-d**：把任务 4 的「无外部引用」校验纳入 CI 守护;加「plugin 取出即完整」的打包自检
  （模拟把 plugin 目录拷出,断言三 skill 引用全可解析）。
