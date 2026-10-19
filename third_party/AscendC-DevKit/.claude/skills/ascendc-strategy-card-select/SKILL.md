---
name: ascendc-strategy-card-select
description: 设计阶段的成熟策略检索与挑选（无算子代码、无 profiling）。把需求/设计文档压缩成冻结的结构化 Query，对照外部策略库的短卡粗筛 Top10，再逐条读完整策略 md 与设计约束核对，选出 ≤3 条（主策略 + 备选）供概设吸收。当开发方案/概设设计需要"选策略""检索成熟策略""把已验证策略吸收进设计"时使用。
---

> ## 依赖声明（driver 类 skill）
>
> 本 skill 是 **driver 类 skill**：其策略卡数据**不随 skill 打包**，运行期从**外部目录**挂载，
> 因此无法满足「从本仓取出后自包含」的字面要求。按工程规范 §2.1 显式声明本清单。
>
> | 依赖 | 形态 | 解析方式 | 缺失后果（三态） |
> |---|---|---|---|
> | 策略库（`strategies/`，113 张 md 卡） | 外部数据目录 | 环境变量 `ASCENDC_STRATEGY_ROOT`，或 `--strategy-root` | **未指定**（env 与 CLI 皆无）→ 合法「未启用」：脚本写 `run_inputs.json{status: skipped_no_library}` 后 exit 0，本流程到此结束，**不阻塞调用方**；**指定但无效**（路径不存在/非目录）→ **硬停**报出确切路径与设置方法 |
> | 策略库元数据解析器 `_catalog.py` | 跨库单源脚本 | 由 `--strategy-root` 派生（`<root>/.claude/skills/ascendc-strategy-curator/scripts/`） | 同上（这是卡元数据解析的唯一权威源） |
>
> **三态不混淆原则**：`skipped_no_library`（没配，未启用）、`error_invalid_root`（配了但路径坏，
> 硬停）、检索完成无命中（`selection.json` 正常产出但无 `applicable=true` 条目）是三个**不同**
> 的状态，以显式字段区分——不得用阻塞把「没配」伪装成故障，也不得用空结果把「没配」伪装成
> 「检索过了但没有合适策略」。
>
> **单源引用**：本 skill 不 vendor `_catalog.py`，也不在本仓保留任何策略卡副本；卡片由
> `scripts/build_cards.py` 在**运行目录内**按需生成（生成物不随仓跟踪）。外部目录内容的正确性
> 归其产权方自检，本 skill 只读不写。
>
> **设置方式**（机器本地，不进仓）：在 `.claude/settings.json` 的 `env` 块设
> `"ASCENDC_STRATEGY_ROOT": "<策略库检出目录>"`。`.claude/settings.json` 已被 gitignore，
> 故不会有任何**被跟踪**的资源指向仓外。

# AscendC 策略卡检索与挑选（设计阶段）

## 概述

在**设计阶段**（此时**不存在算子代码，也没有 profiling 数据**）为主 agent 完成两级策略挑选，
为概设/开发方案设计提供可吸收的成熟策略：

1. **Query 构建与冻结**：通读需求/设计文档，压缩成结构化检索 Query 并**冻结**。
   硬约束：本阶段结束前**禁止**读任何策略卡或策略 md——否则策略知识会污染对算子的客观认识。
2. **卡片粗筛**：用冻结 Query 对照该类**全量**短卡，粗筛 Top10 候选。
3. **全 md 核对**：逐候选读完整策略 md，对照设计文档与约束盲评，排序选出 ≤3 条。

> 本 skill 的 Query 只编码「算子是什么、计划怎么实现、预期哪里可能慢」，**不编码最终实现**，
> 也无法给出实测瓶颈——瓶颈一律是**设计预估**，必须如实标注。
> 脚本只做确定性校验/冻结/打包（纯标准库）；读文档、粗筛、核对等语义工作由主 agent 完成。

## 输入

| 参数 | 环境变量 | 必填 | 说明 |
|---|---|---|---|
| `op_name` | `OP_NAME` | 是 | 算子名（输出目录命名用） |
| `design_doc` | `DESIGN_DOC` | 是 | 需求/设计文档路径（Query 构建的**唯一**算子侧输入） |
| `category` | `STRATEGY_CATEGORY` | 是 | 目标策略类别（见下表） |
| `out_dir` | `AOA_OUT_DIR` | 否 | 输出目录，默认 `<workdir>/strategy_selection/` |
| `used_strategies` | `USED_STRATEGIES_FILE` | 否 | 已用策略名文本文件（每行一个）；三重排除防重复选择 |

**类别选定**——按「算子数据流特征」映射，**禁止按算子名归类**。类别清单由策略库目录树派生
（`common` + `op-class/<class>`），调用 `cardlib.categories()` 获取，不在此维护第二份类名表：

| 数据流特征 | 候选类别 |
|---|---|
| 逐点映射，元素间无依赖（一元/二元逐元素） | `elementwise` |
| 形状广播的逐元素二元计算，整量 broadcast 语义 | `broadcast` |
| 布局/形状变换（转置、切片、重排、routing） | `layout-transform` |
| 索引驱动的查表/gather，输出取决于索引位置 | `index-gather` |
| 索引 scatter/更新与分段归约，写侧冲突处理 | `scatter-update` |
| 跨元素归约/扫描 | `reduction` |
| 组内/行内统计后归一化 | `normalization` |
| 排序/选择/top-k，全局或部分定序 | `sort-select` |
| 向量引擎多流水融合的复合算子 | `vv-fusion` |
| 多算子融合复合管线（量化/门控/注意力等端到端子图） | `fused-composite` |
| 无合适类、或数据流特征不足以判定 | **`common`（保守兜底）** |

**回退与兜底**：无法确定类别、或算子的数据流落在词汇表预留但**尚无卡片**的类（如矩阵乘收缩、
掩码条件筛选、数值稳定损失等）时，用 **`common` 池**——它是唯一不对数据流作假设的池，只含
跨类通用卡，**永不比猜错一个类更差**（猜错会静默丢掉正确卡）。此时应把「类别不确定」作为
设计歧义上报，而非静默选择。

## 输出

```
<out_dir>/
  cards/                        # 先由 build_cards.py 生成本轮卡片（不随仓跟踪）
    common.texts.json
    op-class/<category>.texts.json
  run_inputs.json               # Phase 0：类别、策略库根、卡片 sha256、正文摘要、排除名单
  query.json                    # 冻结的结构化 Query（schema_version=2）
  query.sha256.txt
  screening_worksheet.md        # 粗筛工作单：冻结 Query + 全量筛选池卡片
  screening.json                # 粗筛结果 Top10
  verification.json             # 逐候选盲评条目
  selection.json                # 最终结果（≤3 条）
  selection_report.md           # 人读报告（供把选定策略吸收进开发方案）
  strategy_usage.log            # 使用留痕（追加式，由 finalize 门禁通过后自动写）：
                                #   选中 → 逐条 USED <id> status= confidence= fit=
                                #   无命中 → REASON <原因说明（取 selection.rationale）>
```

## 主流程

### Phase 0：准备 → `run_inputs.json`

1. 确认外部策略库状态：`ASCENDC_STRATEGY_ROOT` 或 `--strategy-root`（三态）：
   - **未指定**（两者皆无）：合法「未启用」状态。`select_prepare.py --prepare` 会写
     `run_inputs.json` 含 `"status": "skipped_no_library"` 并 **exit 0**——看到此状态，
     本流程**到此结束**（不进入 Phase 1），向调用方如实返回「策略检索未执行：未指定
     策略库」。**不得**视为错误，**不得**重试，**不得**回退空库。
   - **指定但无效**（设置了但路径不存在/非目录）：脚本 **硬停**（exit 2）并报出确切
     路径与设置方法——这是用户显式意图的失败，静默跳过会把配错的路径伪装成「未启用」。
   - **指定且有效**：继续下面的卡片生成。
2. 生成该类合并池卡片：

   ```bash
   python3 <skill_dir>/scripts/build_cards.py \
     --strategy-root "$ASCENDC_STRATEGY_ROOT" --category "$STRATEGY_CATEGORY" --out "$OUT_DIR"
   ```

   产物 `<OUT_DIR>/cards/op-class/<category>.texts.json` 为 **common ∪ 该类** 的合并池。
   卡片格式问题只告警、不中止；缺检索词会回退并在报告里记 `terms_fallback`。

3. 落盘运行输入：

   ```bash
   python3 <skill_dir>/scripts/select_prepare.py --prepare \
     --op-name "$OP_NAME" --out-dir "$OUT_DIR" --design-doc "$DESIGN_DOC" \
     --category "$STRATEGY_CATEGORY" \
     --cards-file "$OUT_DIR/cards/op-class/$STRATEGY_CATEGORY.texts.json" \
     [--used-strategies-file "$USED_STRATEGIES_FILE"]
   ```

   `run_inputs.json` 记录策略库根、md 目录名与 `source_md_digest`（池内 md 正文的目录摘要，
   供后续复核正文是否在运行中途被改写）。

### Phase 1：Query 构建（冻结；读卡前完成）→ `query.json`

> **硬约束：本 Phase 结束前禁止读 `cards/`、任何策略 md、任何旧选择报告。**
> **硬停止**：设计文档不可读或不含可识别的算子语义/设计要点时，停止并报告确切路径与检查范围，
> 不输出空或猜测的 Query。

按 `references/query-construction.md` 通读需求/设计文档，产出 `query.json`（schema 见
`schema/query.json`，含 `operator_semantics` / `workload` / `current_implementation[]` /
`bottleneck_hypotheses[]` / `constraints` / `current_optimizations` / `missing_information` /
`retrieval_hints`）。

- 设计文档里的实现方案是**规划（设计意图）**，不是既成事实，写入时须标注「规划」；
- 瓶颈是**设计推演**，须给置信度并在 `missing_information` 声明"无 profiling，均为设计预估"；
- workload 只记录文档**实际给出**的 shape/dtype/layout 支持范围，**不得自行补造**；
- `retrieval_hints.direct_strategy_query` **不含任何策略名/机制名**（那是策略库的词，
  写了会让检索先入为主）。

冻结：

```bash
python3 <skill_dir>/scripts/select_prepare.py --freeze-query \
  --query "$OUT_DIR/query.json" --out-dir "$OUT_DIR"
```

校验失败就地修复重跑，通过后生成 `query.sha256.txt`。此后 query 不得改动。

### Phase 2：卡片粗筛（Top10）→ `screening.json`

1. 生成粗筛工作单：

   ```bash
   python3 <skill_dir>/scripts/select_prepare.py --emit-screening --out-dir "$OUT_DIR"
   ```

2. 主 agent 读 `screening_worksheet.md`，按 `references/recall-screening.md` 的七维判据粗筛。
   **机会症状命中瓶颈假设是最高权重维度**。不足 10 条（可为 0）须在 `shortfall_reason` 写明原因，
   **绝不发明支持凑数**。
3. 写 `screening.json`（六键候选行，`supported` 必须引用观察编号 O001…）。
4. 门禁：

   ```bash
   python3 <skill_dir>/scripts/select_finalize.py --stage screening --out-dir "$OUT_DIR"
   ```

### Phase 3：全 md 核对与盲评 → `verification.json`

对每个粗筛候选（≤10 个）：

1. 定位源 md：`cardlib.source_md_path(<策略库根>, <strategy_id>)` 按 id 跨两层解析
   （`strategies/common/` 与 `strategies/op-class/<class>/`）。
2. **完整读策略 md**——卡片只是索引，卡与 md 冲突时**以 md 为准**。
3. 对照设计文档逐条核对：适用/泛化条件是否与设计意图相容？正确性红线是否被触及？
   「LLM 前置问题」能否从设计文档回答？设计是否已纳入该机制（`already_present`）？
4. 写盲评条目到 `verification.json`。
5. 按 `references/verification.md` 排序：supported 优先 → `already_present=true` 降级 →
   confidence 降序 → 对主瓶颈最直接优先；取前 **3 条**（第 1 条须为 supported 主策略；
   contradicted 不入选）。全部 contradicted → `applicable=false`。

### Phase 4：输出 → `selection.json`、`selection_report.md`

1. 写 `selection.json`：`selected_strategy` / `selected_strategy_path` 恒为第 1 条（主策略），
   `selected_strategies` 为 1~3 条交付（不足就少给、**不凑数**）。
2. 门禁：

   ```bash
   python3 <skill_dir>/scripts/select_finalize.py --stage selection --out-dir "$OUT_DIR"
   ```

   **`applicable=false` 也要落盘 `selection.json`**。门禁通过后脚本会**自动追加**
   `strategy_usage.log`（选中 → 逐条 `USED`；无命中 → `REASON` 原因说明）——这是强制
   使用留痕，无需主 agent 手写。
3. 写 `selection_report.md`，尤其写明**如何把选定的 ≤3 条策略落入开发方案**：每条对
   Buffer / Tiling / 多核切分 / 接口验证的哪一项提出什么约束或调整、彼此主次与冲突、风险与回退。

## 异常处理

- **策略库不可达 / 设计文档不可读**：停止并报告确切路径，**禁止**编造 Query 或回退空库。
- **类别无法确定**：用 `common` 池保守兜底，并把该歧义上报（不静默猜一个类）。
- **筛选池过小**：正常情况，`pool_count` 如实记录，候选数可少于 10，`shortfall_reason` 写明。
- **所有候选 contradicted**：`applicable=false` 落盘，rationale 逐条说明被否原因，不强行选。
- **外部策略正文中途变更**：脚本会以 `source_md_digest` 不符告警；如需严格可复现，重跑 Phase 0。

## 关键约定（违反即失败）

1. **读卡前冻结 Query**：Phase 1 通过 `--freeze-query` 前，禁止读 `cards/` 或任何策略 md。
2. **不伪造实测**：无 profiling，瓶颈只能是设计预估，如实标注，不得编造数值。
3. **不修改设计文档**：本 skill 只做检索与吸收建议，改写由概设阶段在开发方案中完成。
4. **选择理由必须具体**：不能只说"适合"，要指出适用条件中的哪一条匹配了设计文档的哪一处意图。
5. **失败不静默**：任何异常都以日志 + `selection_report.md` 落盘。
6. **必须写 `selection.json`**：即使 `applicable=false` 也要写，字段齐全。
7. **跳过已用策略**：`USED_STRATEGIES_FILE` 提供的名字在粗筛池剔除 + finalize 拒收。
8. **`未知≠矛盾`**：Query 缺失某条件信息时给 `uncertain`，不因未知排除；只有限制字段与约束
   **显式硬冲突**才排除。

## 脚本

| 脚本 | 职责 |
|---|---|
| `scripts/build_cards.py` | 从外部策略库元数据生成七字段短卡（运行期产物） |
| `scripts/select_prepare.py` | Phase 0 准备 / Phase 1 冻结 Query / Phase 2 生成粗筛工作单 |
| `scripts/select_finalize.py` | Phase 2、4 门禁校验 |
| `scripts/cardlib.py` | 卡片格式常量、校验、策略库路径解析 |
| `scripts/_strategy_catalog.py` | 外部 `_catalog.py` 的单源引用适配层（隔离其 SystemExit） |

`<skill_dir>` 指本 skill 所在目录（TUI 单跑时即 `.claude/skills/ascendc-strategy-card-select/`）。
