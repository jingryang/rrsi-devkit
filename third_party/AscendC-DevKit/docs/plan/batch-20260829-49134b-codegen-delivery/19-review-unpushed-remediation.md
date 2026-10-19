# 未推区间 review 整改（steps-103~116 全量评审，2026-09-03）

> L1 事实源：`reviews/unpushed-v020-ahead20-steps103-116-review.{md,json}`（评审
> 快照，verdict=reject：2 blocker + 14 major + ~35 minor）。本文记录整改
> as-built。用户裁定：**坐实的问题全部修复**。

## 范围与基线

- 评审对象：`4fa97d28...9d7197dd`（20 commits，140 文件 +11285/−2050）。
- 整改原则：只修已坐实项；每项带回归 UT 或守护 UT；不留兼容层（§1.4）。

## Blocker（2/2 修复）

### B1 dispatcher.py 死副本簇（step-116 编辑事故）

- 删除 ：1248-2270 死副本（1023 行；两段字节级 diff 仅 3 行——全部是死副本
  内拼写错的 `resolve_opop_card`），活副本（正确 `resolve_op_card`）单份留存，
  文件 3297→2280 行。
- 守护：`tests/ut/infra/test_duplicate_defs_guard.py`——AST 扫 src 全部顶层/
  类内函数重复定义（pyflakes F811 同类），参数化覆盖全部 src 文件 + 防腐
  （树规模下限）测试。该缺陷对运行时测试结构性不可见（last-def-wins 遮蔽），
  只能靠源级守护防复发。

### B2 precision-adapter skill ↔ init-checkpoint CLI 契约断裂

- 修复 device_id 死链拆除漏掉的 skill 侧 4 处：SKILL.md:52（读出表）/:75
  （命令模板）/:129（回显）、schema/adapter_config.json 字段、examples yaml。
- **契约 UT 抓出第二处更早的断裂**：`--time-budget-sec` 自 6d9a5022（N1
  run_tests 纯 Python 化）起为 argparse 必填，模板从未传——TUI 适配器在该
  接口上双断（多传 device_id + 漏传 time-budget，皆 exit 2）。补模板传参 +
  `adapter_config.time_budget_sec`（缺省 36000）。
- 守护：`tests/ut/skills/test_precision_adapter_cli_contract.py`——AST 解析
  脚本 argparse vs SKILL.md 模板正则，双向断言（模板参数 ⊆ argparse 定义；
  argparse 必填 ⊆ 模板传参）。

## Major（14/14 修复）

| # | 修复 | 落点 |
|---|---|---|
| M1 | manifest 读 `_contract/` 新路径 + `export_code` 排除 `_contract/` | export_trace.py + 2 UT |
| M2 | 判切「现在」= 流结束当场采样（双侧 `classify_cut(now=_stream_end_ts)`），消除后处理延迟灌入 gap + 双后端口径统一 | opencode/sdk_backend |
| M3 | filebackup 前缀基线=非 git 真值：`RepoGuard.is_git_baseline()` 单点 + 收集侧降级 scan（guard 缺位保持保守语义） | repo_guard.py + _shared.py + 2 UT |
| M4 | 纯度守卫装满三入口（dispatch/dispatch_single_stage/dispatch_single_skill）+ import_guard docstring 与 dispatch 注释改「漏斗之一」 | dispatcher.py + import_guard.py |
| M5 | 批脚本数卡改卡主行 grep（与 `_CARD_ROW` 同形；保留 NPU_COUNT 逃生口并**补入口校验**——非正整数当场 exit 2，堵住 bash 算术静默得 -1 → 空 CARDS → cards: [] 的远端失败链） | batch_self_evolve.sh + 多芯样例 + 六值边界验证 |
| M6 | 值形态守卫改字段内含正则（命中 f-string 内嵌段）+ 防腐测试证明非常绿 | test_harness_env_contract.py |
| M7 | staging 切片写前整体重建（prune）+ 碰撞分支清残留目录（回退确定性） | codegen.py + 2 回归 UT |
| M8 | `evt.agent_compacted`（N>0 发射；分母由既有 per-spawn 事件承载） | event.py + runner.py |
| M9 | coder skill「API 不存在」改「知识库未覆盖（≠存在性结论）」同族收口 | coder SKILL.md + 守护 UT |
| M10 | diagnose skill 负向约束改「非交互不提问/交互可澄清」+ manifest 增 `mcp__engine__resolve_ambiguity`（照 design-generator 先例） | diagnose SKILL.md + agent md |
| M11 | A5 ctx device_id 在 pin 子树内非法 + resume hard-pin 不排队=预期行为，写入 18 号文档边界节（A5 代码产权在同事，仅文档风险化） | 18-npu-op-card-lease.md |
| M12 | resume_prompt 并入**当前** last_error.message（陈旧反馈与新错误并存时真实错误可达 agent；同文不重复渲染） | design_substages.py + 2 UT |
| M13 | 锚点归属：State 增 `last_agent_stage`（runner 捕获时成对写）+ design/codegen 双侧消费校验 + rerun_reset 同步清 | state.py/runner.py/design/codegen + 4 UT |
| M14 | `Stage.outputs_delivered()` 谓词（默认=has_all；TilingStage 按模板必需段降粒度），runner 全部 8 处「已交付」判定统一走谓词 | base.py/design_substages/runner + 3 UT |

## Minor（~35 项，已修 33，见下两项裁定）

全部按 reviews 报告 Minors 表逐项落地（subagent A 13 项 infra/adapters +
subagent B 12 项 skills/docs/tests + 主会话 8 项 backends/_shared）。要点：
detect/env_contract/repo_guard 的 rc≠0 可观测化、`--no-renames`+rename UT、
`_validate_attrs` 上移 `domain.operator.validate_case_attrs`（orchestration 不再
import adapter 私有符号）、文法递归深度界（16/256→透传+WARN）、coerce 放宽
union 分支、perf 探测进程级缓存 + npu_probe 预载 torch_npu（消孙进程冷导）、
opencode 证据 regex 字段序无关化 + offset 修复 + 失配事实行、sse 无 sid
compaction 不计入、extra_metrics 键冲突 fail-fast、card_pin 负值 env 拒收、
`.gitignore` 锚定仓根、陈旧注释簇与 `P13`/card_context 残留清理、L4
05/14/17/18 文档回填、租约打点+事件、F6/F7 文案纠偏与 derived 标记。

### 未修裁定（2 项，非坐实缺陷或已有权衡记录）

1. **conftest 纯度全 stage 干跑扫**（G1 F10）：作者已权衡的取舍（L4 有记录，
   pytest 插件预载约束），报出供裁决——不属坐实缺陷，未改。
2. **step-110 硬切无 @llm 真链路守护**（G3 F8）：网关硬切现象不可按需复现，
   L4 已诚实挂「待下批」——补确定性触发器不可行，未改。

### 遗留观察（范围外，既有代码非本区间引入）

- deploy.py `_per_op_path` 的 `Path.home()` 兜底（ws 缺位时的 TUI 缓存路径，
  有设计注释）——§1.7 严格意义违规，需独立问题条目裁定，未顺手改。
- deploy.py:766 空 chip `or "A2"`（build.sh 自动探测的合法流，subagent A 裁定
  不属 item 6 范围）——同上，待独立裁定。

## 验证

- 定向套件（整改期间逐批跑）：~1000 用例绿（含新增守护/回归 UT ~25 例）。
- **全量 UT 终验：4253 passed / 0 failed（381.27s，2026-09-03）**——整改前基线 4059，增量 = 新增守护/回归用例 + 源级守护参数化（F811 扫描按 src 文件参数化）。
- 非 heavy ST / heavy_llm：评审基线已全跑（129/129；29 例），本整改未触及
  ST 覆盖的行为面（整改后需复跑的 ST 子集=无——所有修改均有 UT 级锁定；
  下批真实跑含全部端到端判据）。
