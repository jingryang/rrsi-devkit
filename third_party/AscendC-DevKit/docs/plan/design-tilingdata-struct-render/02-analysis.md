# L3 方案分析 — Design 链 TilingData 旧宏渲染

> 本层记录有哪些选项、选了哪个、为什么。调研中演进、拍板后冻结。

## 决策 D1：根因层落在哪——知识库 vs design skill

| 选项 | 内容 | 取舍 |
|---|---|---|
| ① 改知识库 77 篇文档 | 加废弃横幅/逐文件改 struct/INDEX 摘出 | **否决**：`ascendc-dev-knowledge` 是 python 脚本爬取的官方文档，后续官方更新会再次爬取覆盖——改了也白改（用户反馈）。 |
| ② design skill 层自闭环增强 | 在 docgen skill 加 TilingData 渲染铁律，对知识库免疫 | **选定**：skill 是工程自有代码（不会被爬虫覆盖），把写法决策固化在 skill，即便知识库回退旧宏仍产 struct。符合 §1.2 构造性保证、§2.1 skill 自闭环。 |

## 决策 D2：修复落点——字段产出层 vs 渲染层

- 字段产出层（tiling-split/buffer-kernel）产出中性 JSON（`tiling_data_fields[]`，L1-F），**无写法倾向**，不需改。
- 污染在**渲染层**：docgen SKILL.md 对 TilingData 渲染空白（L1-E），LLM 只能抄模板旧宏占位（L1-D）。
- **选定**：修复落在 docgen 渲染层（A1 渲染铁律 + A2 模板占位改 struct）。符合 §1.2 架构合理——纠正移回污染产生的层，不越层。

## 决策 D3：last-resort 门加在哪——validate vs selfcheck vs anchor

| 候选 | 能力 | 取舍 |
|---|---|---|
| validate | 规则扫描 + **就地 Edit 修**（`:166/:221/:248`） | **选定**：design 链唯一兼具「扫描 + 就地修」的门。 |
| feedback-selfcheck | 消费上游 acceptance 回验 | 否决做主门：首跑无反馈不触发，旧宏会漏；但通过 validate issue 的 `acceptance` 字段**自动继承**回验，无需改。 |
| anchor-per-template/consistency | 只读对质，`绝编辑设计来修复`（:128/:130/:127） | 否决：职责正交（做硬件 API 可行性对质）且无就地修权限。 |

**选定**：validate 加 GV10（规则 + 就地修 + acceptance）。符合 §2.9——GV10 是就地确定性机械重写（宏→struct），非 discover+regenerate；且是 last resort，主防线是 docgen producer 自检（A1）。

## 决策 D4：codegen 端动不动

- codegen skill（`ascendc-op-dev-coding`）已有 Step 5 TilingData 归一化校验铁律（L1-G），保持。
- `coding_index.md` 生成 / s2-analysis 属 **A5 codegen 侧**（归同事，见 memory `codegen-a5-ownership-boundary`）→ **本次不动，单独与用户讨论**。

## 决策 D5：是否镜像 codegen 既有铁律

- docgen 渲染铁律、validate GV10「违规→修正为 struct」语义，**直接镜像** `ascendc-op-dev-coding/SKILL.md:215-223,231`，形成「详设/coding 一致契约」。符合 §1.2 可维护（澄清而非新造不变式）、复用不新造。

## 决策 D6：验证形态（调研中修正）

- 原设想扩展 `test_docgen_render.py` 断言渲染为 struct → **修正否决**：docgen/validate 均 LLM 驱动（L1-I），UT 测不到渲染内容（现有 UT 只验编排层 spawn/transition）。硬造测内容的 UT 会退化成 mock（§3.10）。
- **选定**验证三件套：①静态 grep（主，确定性）；②可选 docgen 模板静态契约守护 UT（防模板改回旧宏，参照 `test_testdesign_selfcontained.py` 先例）；③heavy ST（docgen TUI selfclosure）按 §3.11 跑前用户确认。

## 决策 D7：testdesign 案例清不清

- 4 个案例文档含旧宏，经 generate-casedesign「知识库自学习」few-shot 机制可能传播进新产物。
- 改 struct **零逻辑风险**（教学价值在字段等价类/红线表格，与宏外壳无关）。
- **选定**：清理（案例7 额外改提取规则#6 措辞）。
