# P15 修复——diagnose API 查证链去假闭环（step-114）

> L1：`01-problems.md` P15（用户证词 + `ascendc-precision-diagnose/SKILL.md:176`
> 文本证据）。改动一处 skill 文本 + guard UT。L3/L4 合并（改动面一行段落，
> 分文件属官僚化）。

## L3 方案分析（2026-09-02 冻结）

**定性**：正确性缺陷（debug 域）——索引缺口被当 ground truth，且真值源被禁
无回退。用户裁定立项即修。

**选型**：

| 选项 | 裁定 | 理由 |
|---|---|---|
| 保留禁令+只补「问用户」 | 否 | 非交互批跑下问用户=卡死或默认跳过，回退不可达 |
| 全面放开 CANN grep | 否 | 经济性动机成立（全树读入撑爆上下文），连正确动机一起扔 |
| **禁令收窄为「广撒网」+ 定向查证回退 + 终态改「存疑降权」** | **采纳** | 下界=基线（最差退回今天的判「不存在」行为但需先付定向查证成本），上界=索引缺口被定向查证纠正；禁的从「读 CANN」收窄为「无锚定全树扫」 |

**终态语义**：「知识库无记录」的合法结论只有「知识库未覆盖」；经定点读 /
API 名锚定窄域 grep（限单目录树）/ 交互澄清三通道仍无证据 → 写
`_summary.validation`「存在性存疑」并**降权**（不排除）该方向。工具链证据
（linker cannot open .o 等）仍是真实存在性信号，不受影响。

**边界**：`.claude/rules/ascendc-dev.md:41` 不动——其版本无假闭环（只禁
broadly search、终端是 ask user），与收窄后语义兼容。coder skill
`:41`「禁自搜参考实现」是另一族（正确性/溯源动机，20/20 假信号实证），
不在本题范围。

## L4 实施

1. `ascendc-precision-diagnose/SKILL.md` API 红线段：③ 由「都找不到则 API
   不存在，按假设证伪处理——排除该修复方向」改为「知识库未覆盖，不等于
   API 不存在 + 三通道定向查证 + 终态存在性存疑降权」；禁令句由「禁止
   grep CANN 系统路径」收窄为「禁止**广撒网式全树** grep……定点读与窄域
   锚定查证不受禁」。
2. `tests/ut/skills/test_precision_debug_selfcontained.py` 增
   `TestApiLookupClosure`：断言假闭环文本（「则 API 不存在」）不回潮、
   回退标记（知识库未覆盖/存在性存疑/降权/广撒网/不受禁）在位。
3. §4.4 合规：澄清通道按自然语言写（「交互下向用户澄清确认」），不写死
   工具名。

## 验证

- `tests/ut/skills/test_precision_debug_selfcontained.py` 15 绿（+2）。
- skill 即插即用守护（live-ref 泄漏扫描）不受影响：CANN 路径字样仅出现
  在含「禁止」的否定行。
