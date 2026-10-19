# e2e-self-evolve 跑 moe_re_routing — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。

## 决策 1（P2）— precision_debug 耗尽：软门放行 vs 保持 __halt__ → **选软门**

- **选项 A 软门**：`precision_debug.exhausted → (cannbench_adapt, validation)`，① 不阻断 ②。
- **选项 B 保持 halt**：交人 triage（原设计）。
- **选 A 的理由**：① 在 workflow 注释里本就被描述为「② 的本地快速预检」；耗尽只是「预检不足以收敛」，
  不是「链路不该继续」。② 用自己健全的 harness 产出真实分数，分数本身（含零 function 分）即诚实信号。
  A2-on-A5 不可执行（codegen chip 门已证），故必须 A5；CLI 传 A5 时 ② 必然可达。
- **边界**：仅 `self_evolve_op` 软门（它有 ② 评分器）；`generate_ascendc` / `generate_ascendc_dev`
  无 ②，precision_debug 后是 perf/integrate，保持 `__halt__`（耗尽交人，无评分可降级）。

## 决策 2（P3）— 修 6 harness gap vs 仅软门 → **选彻底修（用户拍板）**

- **选项 A 仅软门**：harness 坏着也能出分（② 自己健全）。最快，但 ① 给不了 codegen 精度反馈，
  最终 kernel 可能精度不对、② function 分（权重 0.3）偏低。
- **选项 B 软门 + 修 6 gap**：① 能正确比对 4 输出 + 用 get_input 修 sum==A + 整数 dtype + 每输入值域，
  给 codegen 真实精度信号。moe_re_routing 是纯路由算子（无算术精度损失），逻辑对则比特精确通过。
- **选 B 的理由**：首个多输出算子，① 修对才有 self-evolve 价值；修法对单输出向后兼容
  （多输出走 list、单输出即长度 1 的 list，exp/add 不回归）。四把尺子：可维护（① 回归忠实预检）、
  可扩展（后续多输出/可选输入/整数算子自动归位）、可诊断（get_input 产出结构合法输入，失败即真 bug）、
  架构合理（改动落在 harness 生成层 + cases 解析层）。

## 决策 3（P4）— 4 个 pre-existing chip-UT 失败：不在本轮修 → **记为 follow-up**

- 属环境前置条件（A2-硬编码 UT 跑在 A5 机），非本轮引入、非被测代码缺陷（§3.7）。
- 不挡 A5 E2E 跑。正确修法待定（UT mock 探测 vs 全量对齐 A5），单开 follow-up 评估，不在本链路扩范围。
