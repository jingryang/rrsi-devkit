# L1 问题记录：策略卡检索接入概设阶段

> 本层**只记客观事实**：哪里不行、凭什么这么说。不提方案、不排顺序、不写决策。
> 每条都附实测证据与复现命令。

## P1 概设阶段没有成熟策略检索能力

**事实**：概设 skill `ascendc-op-general-design` 的 13 个步骤中，算子架构选型、切分轴优先级、
Tiling 与 Buffer 规划全部由 agent 依据 `design_patterns.md` 与自身知识现场推导，没有任何环节
查询已有策略库。

**凭什么这么说**：`grep -n '^### 步骤' .claude/skills/ascendc-op-general-design/SKILL.md`
列出 13 个步骤，无一步骤涉及策略检索；该 skill 的 `references/` 下亦无策略库引用。

**后果**：策略库中已验证的机制无法复用；已证伪的方向（负结果）也无从得知，可能重复踩坑。

## P2 上游 skill 的类别体系与本仓策略库不通用

**事实**：上游（外部 PR `guo-sj/cannbot-skills#16`）的检索 skill 用「算子族 × 芯片代际」六类
（`cv|FA|vec` × `A3|A5`），并把类别后缀写死为正则 `^(cv|FA|vec)-(A3|A5)$`。

**凭什么这么说**：`scripts/cardlib.py` 的 `CATEGORIES` 元组与 `CATEGORY_RE`；
`scripts/select_prepare.py:resolve_category` 的 `_check` 直接引用该正则。

**与目标的冲突**：本仓要挂载的策略库（`ascendc-strategy-opt`）用另一套二维分类
（`common` + `op-class/<13 类>`，实际 11 个目录有卡）。两套词汇表零重叠：

```
$ python3 -c "..."   # 见 03-impl 验证节
cannbot 六类 ∩ strategy-opt 类目 = ∅
```

**后果**：正则与候选清单必须改，否则任何类别参数都无法解析。

## P3 上游卡片格式常量自相矛盾，零裁剪也无法满足

**事实**：上游 `cardlib.py` 的字段预算之和超过整卡上限。

**凭什么这么说**（实测）：

```
FIELD_BUDGETS = {"动作":100,"适用":65,"限制":75,"范围":45,"检索词":75,"机会":65,"代价":55}
sum = 480
去掉「代价」= 425
TOTAL_LIMIT = 420
```

且上游实际产出的卡片各字段长度恰好等于各预算上限（89/65/75/45/75/65/53），说明上游是
**裁剪后**才装得进 420。

**后果**：直接把本策略库的元数据按该预算投影，每一张卡都会 `parse_card_text` 校验失败。

## P4 策略库的 md 是两层树，上游的路径约定是单层

**事实**：上游 `cardlib.source_md_path` 与 `list_strategy_md` 把目录名硬编码为字面量
`"strategy"`，期望布局是 `<root>/strategy/<category>/<id>.md` 单层。

**凭什么这么说**：`cardlib.py` 中 `Path(repo_root) / "strategy" / category / f"{strategy_id}.md"`。

**与目标的冲突**：本策略库是两层：

```
strategies/common/<slug>.md
strategies/op-class/<class>/<slug>.md
```

且合并池（`common ∪ 该类`）成员跨两层，**tier 不是 category 的函数**。

**后果**：按 id 定位 md 必须跨两层解析。

## P5 上游选类规则表格含具体算子名

**事实**：上游类目说明表带「典型算子」列，且已写入具体算子名。

**凭什么这么说**：策略库 `strategies/op-class/CLASSES.md:32`
`| \`broadcast\` | 形状广播的逐元素二元计算，整量 broadcast 语义 | gcd, maximum |`

**后果**：照抄该表进 skill 即违反 CLAUDE.md §1.12（禁止把具体算子名当分类锚点）。

## P6 上游依赖 skill 自带的 `_catalog.py`，本仓无此脚本

**事实**：策略卡的元数据解析器位于策略库自身的 curator skill：
`<策略库根>/.claude/skills/ascendc-strategy-curator/scripts/_catalog.py`，
负责解析卡片顶部 `<!-- strategy-metadata ... -->` 元数据块、渲染正文、校验条目。

**凭什么这么说**：策略库 `validate_catalog.py` 与 `format_catalog.py` 均 `from _catalog import ...`；
本仓 `find .claude/skills -name '_catalog.py'` 无结果。

**后果**：卡片生成器要么跨仓引用该脚本（单源），要么在本地复刻（违反 §2.5）。

## P7 策略库的 `.claude/settings.json` 已被 gitignore

**事实**：DevKit 的 `.gitignore:25` 为 `.claude/settings.json*`，通配覆盖该文件及其变体。

**凭什么这么说**：

```
$ git check-ignore -v .claude/settings.json
.gitignore:25:.claude/settings.json*	.claude/settings.json
```

**后果**（这是事实层面的直接影响）：机器本地配置无法进仓，故在此注入的任何环境变量
都不会产生被跟踪的仓外路径引用。

## P8 策略 md 正文是派生文件，与元数据字节等价

**事实**：策略库的 md 正文不是手写的，而是从其内嵌元数据确定性渲染出的。

**凭什么这么说**（实测 113/113 一致）：

```
$ python3 -c "..."   # 逐卡比对 read_text() == render_entry(load_entry(p))
正文与 metadata 一致: 113   不一致: 0
```

且 `validate_catalog.py:84` 强制该等式（不符即报错）。

**后果**：任何对策略 md 的本地修改都会使其无法通过策略库侧校验；且正文可在不触碰 md 的情况下
由元数据重建。

## P9 「未指定策略库」被当成故障处理，存在任务阻塞风险

**事实**：原实现把策略库缺失一律当硬停故障处理——`select_prepare.py --prepare` 在
`ASCENDC_STRATEGY_ROOT` 未设置且无 `--strategy-root` 时 `die()`（exit 2）；SKILL.md
Phase 0 写明「不可达即硬停」，未区分「未指定」与「指定但路径无效」。

**凭什么这么说**（20260922 批 5 算子概设实测 + 代码事实）：

- 批内 5 个概设 agent 中 4 个**静默跳过**了策略检索步骤（无 `strategy_selection/` 产物、
  `narrative` 无留痕），仅 1 个（fc_cross_entropy_isnan）按规则留痕「外部策略库未挂载，
  软跳过」——概设 skill 的软跳过条款靠 agent 自觉遵守，无机器可读的跳过信号；
- 直接调用 `ascendc-strategy-card-select`（未经概设预检）时，Phase 0 硬停 exit 2，
  对调用方表现为故障。

**后果**：策略库是可选知识源，「没配置」与「配置坏了」两种语义不同的状态共用一条
硬停路径——前者阻塞/吓退调用方（用户约束：未指定不得阻塞任务），后者才是应当硬停的
显式意图失败；且跳过无结构化留痕，无法区分「未启用」与「检索过但无命中」。

**用户新增约束**（2026-09-24）：指定了策略库 → 执行筛选吸收；未指定 → 正常分析、
跳过策略筛选阶段，不得因未指定发生任务阻塞。

## P10 策略使用结果缺 log 留痕：选了什么/为什么没选无持久记录

**事实**：指定策略库并完成检索后，选择结果只存在于 `selection.json` /
`selection_report.md`（结构化 + 人读报告）与概设 `narrative` 摘要中——没有追加式 log。
无命中（`applicable=false`）时的被否原因同样只落在 selection.rationale 字段里。

**凭什么这么说**（代码事实）：`select_finalize.py` 门禁只做校验与 stdout JSON 输出，
无任何持久 log 写入；skill 产物清单（SKILL.md 输出段）不含 log 文件。

**后果**：跨算子/跨批回看「哪些策略实际被用、无命中的原因分布」需要逐个解析 JSON，
无快速 grep 通道；选择行为缺审计轨迹。

**用户新增需求**（2026-09-24）：指定了策略库时，筛选出使用的策略后要 log 记录所用
策略；未选中任何匹配策略则说明原因，同样记录在 log 中。
