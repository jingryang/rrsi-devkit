# L4 实施方案：策略卡检索接入概设阶段

> 落地细节：改哪个文件、什么顺序、怎么验证。取舍论证见 `02-analysis.md`，问题事实见
> `01-problems.md`。**本方案已实施完毕**，故本文按实际形态记录。

## 1. 新增 skill `.claude/skills/ascendc-strategy-card-select/`

```
SKILL.md                        # workflow（§2.8：只承载"做什么/怎么做"）
scripts/
  cardlib.py                    # 卡片格式常量 + 校验 + 策略库路径解析
  select_prepare.py             # Phase 0 准备 / Phase 1 冻结 Query / Phase 2 生成工作单
  select_finalize.py            # Phase 2、4 门禁校验（含 digest 守卫）
  build_cards.py                # 七字段短卡生成器（跨仓元数据 → 运行期卡片）
  _strategy_catalog.py          # 外部 _catalog.py 的单源引用适配层
references/
  query-construction.md         # Phase 1 判据
  recall-screening.md           # Phase 2 六维判据
  verification.md               # Phase 3 盲评与排序
schema/
  query.json                    # Query v2（照搬上游）
  run_inputs.json               # 运行输入契约说明
  screening.json                # 粗筛契约说明
  selection.json                # 最终产物契约说明
resources/
  retrieval_terms.json          # slug → 检索词（113 条，唯一需 LLM 补齐的字段）
```

## 2. `cardlib.py` 相对上游的关键改动

| 改动 | 内容 |
|---|---|
| 类别体系 | 删 `CATEGORIES` 元组与 `CATEGORY_RE=^(cv\|FA\|vec)-(A3\|A5)$`；改为与 slug 同构的 `^[a-z0-9]+(?:-[a-z0-9]+)*$` + 常量 `COMMON_CATEGORY`/`OP_CLASS_DIR` |
| 新增 `categories(root)` | 由目录树派生合法类名（`common` + 含有卡目录的 op-class 子目录）；是类名唯一事实源 |
| 新增 `pool_members(root, cat)` | 合并池 = `common ∪ 该类`；同时做成员校验（放宽正则后的拼写门） |
| 新增 `md_root`/`MD_ROOT_DEFAULT` | md 树根 = `<root>/strategies` |
| 重写 `source_md_path` | 去掉 `category` 形参，**按 id 跨两层**解析（`common/<id>.md` 与 `op-class/*/<id>.md`）；1 命中才返回，**0 或 ≥2 都抛 ValueError** |
| 新增 `resolve_strategy_root` | CLI > `ASCENDC_STRATEGY_ROOT` > None；路径无效时抛出带补救说明的 ValueError |
| 新增 `catalog_digest` | 池内 md 的"相对路径:sha256"行拼接摘要，用于漂移复核 |
| 引用 token 化 | `FIELD_LABELS` 六项（**移除「代价」**）；`FIELD_BUDGETS` 与 `TOTAL_LIMIT` 按实测文本量放宽 |
| 删死代码 | `load_scan_config`/`list_strategy_md`/`category_of`/`now_utc`/`cards_path`/`default_repo_root`（上游三个脚本零调用；§2.5 不留旧债） |

**「≥2 命中必须报错」这一分支不可删**：本函数依赖"slug 全局唯一"这一**外部**不变式
（策略库侧 `validate_catalog.py:89-91` 保证）。若该不变式被放宽，必须响亮报错而非静默选一个。

## 3. `build_cards.py`（新增）

从外部元数据投影七字段短卡：

| 字段 | 来源 | 覆盖 |
|---|---|---|
| 动作 | `mechanism`；`negative_boundary`→前缀「负向边界：」、`lesson`→「反模式：」 | 113/113 |
| 适用 | `applicability.required_conditions` | 113/113 |
| 限制 | `applicability.excluded_conditions` + `.constraints` + `risks` | 113/113 |
| 范围 | generality 标签 + `operator_scope` | 113/113 |
| 检索词 | `resources/retrieval_terms.json` | 113/113（缺失则回退） |
| 机会 | `feature_signature.bottleneck`，缺失回退 `intent` | 105/113 直出，8 张回退 |

**负向前缀是功能性的、不是装饰**：粗筛规则把动作以「反模式：/负向边界：」开头的卡识别为
已证伪方向，命中时选入并标 `uncertain`。实测 30 张 `negative_boundary` + 12 张 `lesson` = 42 张，
全部正确加前缀（见验证节）；不加则这 42 张会以正面策略面貌进入粗筛。

**「代价」整行省略**：无元数据来源。生成器 docstring 写明原因，避免后来者凭空补。

**产物**：`<out>/cards/common.texts.json` 与 `<out>/cards/op-class/<class>.texts.json`，
行合约**保持三键**（`validate_card_rows` 的精确集合校验与 finalize 门禁共同依赖）。

## 4. `select_prepare.py` 相对上游的关键改动

| 改动 | 内容 |
|---|---|
| `resolve_category(args, valid_categories)` | 改为**对实际类目清单的成员校验**；die 消息列出真实类名 |
| 根目录解析 | `--strategy-root` > `ASCENDC_STRATEGY_ROOT` > **硬停**（报设置方法，不回退空库） |
| 字段改名 | `repo_root` → `strategy_root`（§1.4；唯一读者是 SKILL.md 正文） |
| 删 `created_at` | 全流程唯一非确定性，零消费者；删之使 `run_inputs.json` 可字节复现 |
| 新增 `source_md_digest` | 记录本轮所见策略正文版本 |
| `--cards-file` 必需 | 去掉了"卡片库随 skill 打包"的默认路径（已无内置卡） |
| 新增 `--md-dir` | 适配外部库的目录名 |
| 新增 `warn_if_md_drifted` | `emit-screening` 时复核正文漂移 |

## 5. `select_finalize.py` — 仅一处改动

`stage_selection` 开头调用 `warn_if_md_drifted(ri)`。理由见 `02-analysis.md` §H。
其余逻辑（门禁校验）**逐行保持上游**——它不碰类别、不碰根目录，只读 `run_inputs.json`
与 agent 传入的 `selection.json`。

## 6. 概设接入

**`resources/orchestration-config.json`**：

```json
"ascendc-op-general-design": ["ascendc-simt-operator-design-patterns", "ascendc-strategy-card-select"]
```

**`.claude/skills/ascendc-op-general-design/SKILL.md`**：

- 在「确认芯片平台与硬件参数」步骤之后插入新步骤「策略卡检索与策略吸收」，
  其后各步顺延（原 6–13 → 7–14）。已先验证全文**无 `§N`/`步骤N` 式语义引用**
  （跨引用全部为名称制），故重编号只改标题、不影响任何引用。
- 新步骤内容：触发与跳过（pass-through / 库不可达软跳过并留痕）、类别判定表
  （**按数据流特征，不按算子名**，且**不照抄 CLASSES.md 的典型算子列**）、`common` 兜底、
  执行方式（`Skill` 工具 + `<workdir>/strategy_selection/`）、产物、**如何约束下游**
  （逐条映射到 `split_axis_priority` / `tiling_data` / `loop_framework` / `buffer_eval`）、边界。
- 「质量自检」追加 3 项：检索是否执行或留痕、选定策略是否落到具体节点、是否越界。
- 「知识引用策略」Tier 2 行加入新步骤名。

**顺序约束**：`orchestration-config.json` 的改动**必须在 SKILL.md 落地之后**，
否则 `validate_skill_map()` 会因引用幽灵 skill 而报错。

## 7. 测试

| 文件 | 覆盖 |
|---|---|
| `tests/ut/skills/test_strategy_card_select.py`（新增，36 例） | 类别派生/合并池/笔误拒绝；跨两层解析的四个分支（common/op-class/未知/重复）；`resolve_strategy_root` 四分支；**生成器两次运行字节一致**；每行过 `validate_card_rows`；**显式断言行集合恰为三键**；负向前缀；无 bottleneck 回退；检索词缺失回退 + 有值时的使用；超预算裁剪；`_catalog` 异常隔离；静态守卫（依赖声明、无 vendor 副本、无芯片字面量、无上游类别残留、无绝对路径、纯标准库） |
| `tests/ut/orchestration/test_skill_config.py`（扩展 2 例） | `validate_skill_map()==[]` + **固定断言**新 tail-call 挂在 `ascendc-op-general-design` 下且进 allowlist |
| `tests/st/test_strategy_card_select_tui_selfclosure.py`（新增） | 确定性部分：框架外跑通 build_cards + select_prepare，且 `run_inputs` 无 `created_at`。`heavy_llm` 部分：真实 LLM 跑完 Phase 0–4 并过门禁，断言每条 `strategy_path` 落在**外部策略库内**（证明是挂载而非副本） |

`heavy_llm` 用例按 §3.11 **不默认跑**，需用户确认；未跑须诚实记录。

## 8. 验证记录（实施时实际执行）

| 检查 | 结果 |
|---|---|
| `cardlib.categories()` 对真实库 | 11 类，与目录树一致 |
| 池并集 vs 真实卡数 | 113 = 113，**零缺漏零多余** |
| `build_cards --all` 对真实库 | `ok: true`，**11 个池全零校验错误** |
| 生成器确定性 | 两次运行**字节一致** |
| 负向卡前缀 | 应带 42 / 实带 42，**缺 0** |
| 字段预算 | 各字段 max 均 ≤ budget |
| 策略库只读性 | 全程 `git status` 为空 |
| Phase 0→4 全脚本链 | 无 LLM 跑通；`selection` 门禁 `status: ok` |
| 门禁抗破坏 | 故意改错 sha → 拦截；候选不足未写 `shortfall_reason` → 拦截 |
| digest 守卫 | 模拟外部 md 漂移 → 两处均告警；恢复后静默 |
| `validate_skill_map()` | 零错误；allowlist 含新 skill |
| UT | 36 + 13 通过 |

## 9. 残余风险与后续动作

| # | 风险 | 状态 / 后续 |
|---|---|---|
| 1 | 放宽预算后卡片变长是否影响粗筛质量 | **未 A/B**。低成本探针：对最大的池（`fused-composite` 34 张）生成工作单，与上游裁剪版目测对比。不过度打磨 |
| 2 | `_catalog.py` 位置属策略库内部约定，可能被其产权方改名 | 有 `--curator-scripts` 逃生口与带补救说明的报错；`run_inputs` 记录根路径可追溯 |
| 3 | SDK backend 是否透传 `ASCENDC_STRATEGY_ROOT` | **未实测**（需真实 LLM 环境）。TUI 走 `.claude/settings.json` 的 `env` 块已验证可读；编排路径若不通需补 stage 级 env 注入 |
| 4 | `<skill_dir>` 在 tail-call 加载路径下能否解析自身 scripts/ | 由 ST 的 `heavy_llm` 用例实测；该用例正是为此设计 |
| 5 | 薄类池的 `shortfall_reason` 是结构性必需 | 已在 SKILL.md 与 recall-screening.md 写明"不是异常"，避免被当成缺陷 |
| 6 | 外部库新增卡未补检索词 | 回退 + 告警，不阻断；`terms_fallback` 可观测 |

## 10. 明确非目标

- 不改 `ascendc-strategy-opt` 任何文件（其 `format_catalog.py` / `validate_catalog.py` 必须继续通过）
- 不新建 design substage，不动 `design_substages.py` / `design_tree.py`
- 不把策略卡提交进 DevKit
- 不在卡行内加 md 溯源字段（溯源放 `run_inputs.json` 的兄弟字段）

## 9. P9 三态语义：未指定策略库不阻塞（2026-09-24 实施完毕）

P9（见 `01-problems.md`）落地为「用户是否指定策略库」三态，用**显式状态字段**替代阻塞，
保住原反混淆初衷（不把「没配」伪装成「无命中」）：

| 状态 | 判定 | 行为 |
|---|---|---|
| 未指定 | `ASCENDC_STRATEGY_ROOT` 未设且无 `--strategy-root` | `--prepare` 写 `run_inputs.json{status: skipped_no_library}` 后 **exit 0**；下游子命令（emit-screening / finalize）遇该标记**干净退出**（exit 0）；SKILL.md 流程到此结束，调用方跳过策略步骤 |
| 指定但无效 | 设置了但路径不存在/非目录 | **硬停 exit 2** + 报出确切路径与设置方法（显式意图失败，不伪装成未启用） |
| 指定且有效 | — | 原全流程不变 |

改动清单：

| 文件 | 改动 |
|---|---|
| `scripts/select_prepare.py` | `cmd_prepare` None 分支：die → 写 skip 标记 + `out_json` + return；`load_run_inputs` 加 skip 守卫（emit-screening 路径） |
| `scripts/select_finalize.py` | `load_run_inputs` 加同款 skip 守卫 |
| `SKILL.md`（本 skill） | 依赖声明表改三态列；Phase 0 第 1 步重写为三态判定（含「看到 skipped 即结束，不重试不回退空库」）；新增「三态不混淆原则」段 |
| `ascendc-op-general-design/SKILL.md` 步骤6 | 「触发与跳过」重写：未指定=不调用 skill 直接跳过（narrative 留痕一句）；指定但无效=报错原文留痕后**继续**概设（不阻塞，不代为猜测）；自检门与吸收段措辞对齐三态 |
| `tests/ut/skills/test_strategy_card_select.py` | 新增 `TestPrepareThreeState`（3 用例：skip 标记契约+反混淆字段断言 / 无效根硬停 / 下游干净退出） |

验证：`pytest tests/ut/skills/test_strategy_card_select.py` 39 passed（36 旧 + 3 新）；
`tests/ut/orchestration/test_skill_config.py` 13 passed（tail-call 接线未受影响）。

## 10. P10 使用留痕 `strategy_usage.log`（2026-09-24 实施完毕）

落点选择：由 `select_finalize.py --stage selection` **门禁通过后确定性追加**（§2.10——
结构化产出走脚本，不依赖主 agent 自由发挥），文件 `<out_dir>/strategy_usage.log`，
追加式书写（重跑不覆盖历史）：

```
[2026-09-24T16:05:32] op=<op_name> category=<cat> outcome=selected count=2
  USED <strategy_id> status=<supported|uncertain> confidence=<c> fit=<bottleneck_fit>
  USED ...
[2026-09-24T16:09:01] op=<op_name> category=<cat> outcome=no_match count=0
  REASON <selection.rationale（门禁已强制 applicable=false 时写明被否原因）>
```

改动清单：

| 文件 | 改动 |
|---|---|
| `scripts/select_finalize.py` | 新增 `append_usage_log()`；挂到 `stage_selection` 门禁通过点（写失败报 WARN 不改判定）；ok 输出附 `usage_log` 路径 |
| `SKILL.md`（本 skill） | 输出产物树 + Phase 4 门禁说明补 `strategy_usage.log`（注明自动写、无需手写） |
| `ascendc-op-general-design/SKILL.md` 步骤6 | 产物段补 `strategy_usage.log` |
| `tests/ut/skills/test_strategy_card_select.py` | 新增 `TestUsageLog`（3 用例：选中逐条 USED / 无命中 REASON 含原因正文 / 追加语义重跑留史） |

验证：`pytest tests/ut/skills/test_strategy_card_select.py
tests/ut/orchestration/test_skill_config.py` → **55 passed**（52 + 3 新）。

与三态的关系：`strategy_usage.log` 只在「指定且有效 → 完成检索」路径产生；`skipped_no_library`
（未指定）不写 log（run_inputs.json 的 skip 标记已是该态的留痕）——两态留痕通道不同、不混淆。
