# step-8 §P9 闭环 + L4-c 清理实施记录（方案 B：P9 落点 + L4-c 合并）

> 层级：**L4 / 实施记录**。决策依据见同目录 `02-analysis.md`（§P9 / §P4 / §P5 / D4）；
> 问题证据见 `01-problems.md`（P9 / P4 / P5）。本份记录 §P1 的闭环动作（首消息 slash 触发 +
> ST 守护 + SKILL.md 契约改写）与 L4-c 的 skill/agent 清理。

## 范围（方案 B = 一次闭环，避免"skill 调起但找错文件"中间态）

1. **P9 落点 1**：design substage 的 spawn 首消息以 `/stage-design:<skill 短名>` 开头触发。
2. **P9 落点 2**：`test_skill_invocation.py` 去 xfail，改断言"skill 设计方法进入 agent 上下文/transcript"。
3. **L4-c / §P4**：移出 `ascendc-tiling-strategy`；删 `ascendc-op-detailed-design` + 建 `ascendc-op-design-intake`。
4. **L4-c / 隐患 2**：改写各 SKILL.md 输入契约，铲除"校验上游完成状态 / 跨读 checkpoint"控制流（AC0 病根）。
5. **L4-c / §P5**：删 `ascendc-designer.md` + 删除闭包（A 类测试 / B 类文档）。

## 实施明细

### 1. P9 落点 1 —— 首消息 slash 触发（已完成）

- `design_substages.py` `_DesignSubstage` 新增 `_skill_trigger()`（返回 `/<assigned_skill>`，即
  `/stage-design:<skill>`）与 `_with_trigger(body)`（把 slash 命令置于消息首行）。
- 四个 `_build_prompt` 路径（base / GeneralDesign override / DetailedDesignIntake override /
  _TilingSegment override）的返回值统一改为 `self._with_trigger(...)`，首行即 slash 命令。
- `_skill_section()` 改为提示"本步骤设计方法和规范已在本会话加载（skill X）；请据此执行"
  （不再指示"用 Skill 工具调用"——本 CLI 无该工具）。
- 三个角色 agent.md body 同步：从"先用 Skill 工具调用指派 skill"改为"设计方法已在本会话加载，
  直接据此执行，勿 Bash/cat 搜寻 SKILL.md"。
- 单测：`test_design_substages.py` 新增 `TestSkillSlashTrigger`（6 substage + tiling segment +
  general-design doc-path branch，断言 prompt 首行 == `/stage-design:<skill>`）。

### 2. P9 落点 2 —— ST 守护翻绿（已完成，真实链路验证）

- `test_skill_invocation.py` 去 `@pytest.mark.xfail`；prompt 改由真实 `TilingSplitStage.actions()`
  构造（首行即 slash 触发，与生产一致）。
- 断言信号从 `"tool_name": "Skill"`（本 CLI 错误信号）改为 **transcript 出现 SKILL.md 独有术语**
  （`枚举验证法` / `loopTimes` / `tailRows` / `校验上游步骤完成状态`）——这些只可能来自被 slash
  注入的 SKILL.md，prompt 从不提供。
- **真实链路实测通过**（150s，1 passed）：证明 slash 触发把 tiling-split 的设计方法注入了 agent，
  §P1 终极目标（skill 设计方法真正进入 agent 上下文）**达成、闭环**。

### 3. L4-c / §P4 —— skill 精选与对齐（已完成）

- `git mv` 把 `ascendc-tiling-strategy` 从 `stage-design/skills/` 移到 `stage-perf/skills/`
  （性能/代码审查系列，perf-tuner agent 加载 stage-perf）。
- `git rm` 删 `ascendc-op-detailed-design`（旧一体化详设生成器，名实不符的历史债务）。
- 新建 `ascendc-op-design-intake`（D4：极薄转写 skill，"忠实转写详设文档为三件套、禁止重新设计"，
  禁 SubAgent/Phase 推导/execution_state/跨读 checkpoint/AskUserQuestion 决策门控）。
- `orchestration-config.json` 的 `skills.stages.dd-intake` 改指 `stage-design:ascendc-op-design-intake`。
- 一致性校验：`skill_config.py` 新增 `validate_skill_map()`（STAGE_SKILL_MAP 值 ⇄ stage-design
  实际 skill 集合一一对应），dispatcher 启动期与 `validate_agents()` 并行做 fail-fast（EX_CONFIG）。
- 单测：新建 `test_skill_config.py`（5 例：dd-intake 指向 / detailed-design 不再被引用 / live 一致 /
  缺失被报 / 非 stage-design 跳过）。

### 4. L4-c / 隐患 2 —— SKILL.md 输入契约改写（已完成，AC0 病根铲除）

铲除各 design SKILL.md 的"执行步骤 0 校验上游完成状态 + 跨读 `checkpoints/*.json` 判 `status==completed`
→ 报错阻断"控制流（P3 死循环病根）。改为"输入已在本次对话上下文 / 当前工作目录提供，不去别处搜寻、
不跨读其它步骤的中间文件"。改写覆盖：

- `ascendc-op-general-design`：输入契约（op_spec→上下文）、step-2 checkpoint 读取、输出（→ 输出要求 schema）。
- `ascendc-op-design-template-division`：删 step-0；输入/输出/步骤改为消费已提供概设产物。
- `ascendc-op-tiling-split` / `-buffer-kernel` / `-precision-perf`：删 step-0；输入/一致性约束/自检写出
  改为消费已提供产物（当前模板 + 上游结构化产物），不写 checkpoint。
- `ascendc-op-design-anchor-check`（AC0 直接病根）：删"校验三段 checkpoint 完成状态"控制流；只对质
  已提供的 tiling 产物；缺 claim 即结构化结论（AC0），不去搜寻；只产出 `anchor_report`，不自行回退。
- `ascendc-op-design-integrate`：删"校验所有模板 3 段 checkpoint + anchor-check checkpoint"控制流；
  消费已提供的 tiling 产物 + anchor_report，只标注阻断不自行回退。
- `ascendc-op-design-validate`：GV8-B/GV9 的 checkpoint 跨读改为消费已提供产物 + anchor_report；
  保留 `--stage X` 独立模式的 workdir 读写（其文档化的独立校验用途）。
- `ascendc-op-design-docgen`（非 spawn，仅参考）：同样去 step-0 控制流，标注消费已提供产物。

**解耦原则（用户纠正后执行）**：SKILL.md 不写"工程编排注入 / GraphExecutor / 数据流 c / State 事实源"
等耦合工程实现的措辞——skill 只声明"输入来自上下文或工作目录、不跨读他人中间文件、不校验上游时序"，
不让 skill 知晓编排存在。术语去口语化但避免生僻：删除全部"方法学"，改为"设计方法和规范 / 设计方法和步骤"。

### 4b. 隐患 2 的真实根因修复 —— 上游产物注入链补齐（验收期发现，已修）

改写 SKILL.md 输入契约时核查发现：消费型 substage（anchor-check / integrate / template-division /
validate / tiling 段）的 spawn prompt **既不注入上游结构化产物，cwd 也不物化**——`SpawnAgent.context`
仅 op_name/op_dir，且 backend 从不把 context 写进 prompt/cwd（只用于日志）。即 anchor-check/integrate
的 `input_contract.requires`（tiling_results / anchor_report 等）从未真正送达 agent（HEAD 基线即如此，
L4-a「上下文注入」只做了 op_name/op_dir/requirement）。这与 §P1「上下文注入」+ 数据流 (c)「skill 读
编排注入的本步输入产物」拍板决策直接冲突；若不修，改写后的 SKILL.md "输入已提供"会指向不存在的输入
（即"skill 调起但找错文件"的中间态）。

修复（落实 (c) 的"编排把上游产物送达消费 agent"一半）：
- `_DesignSubstage` 新增 `_upstream_inputs(state)` hook + `_inputs_section()`，在 `_build_prompt` 注入
  `## 上游输入`（各产物 JSON，8000 字上限）。
- 各消费 substage override `_upstream_inputs`：general-design-review/template-division → general_design；
  anchor-check → tiling_results；integrate → tiling_results + anchor_report；validate → design_doc +
  tiling_results + anchor_report；tiling 段 → general_design + template_division +
  `tiling_results[本模板]`（本模板已完成段，按分支隔离不读其它模板）。
- SKILL.md 输入契约的"已在本次对话提供"补指「## 上游输入」段定位。
- 单测 `TestUpstreamInputInjection`（8 例）：断言各消费 substage 的 prompt 含其上游产物 payload
  marker；空产物不产生 `## 上游输入` 段。
- 真实链路 ST 增 `TestConsumingSubstageGetsInjectedInput`：anchor-check（角色 C）真实 spawn，断言
  ①anchor skill 方法（AC0/AC1/AC2）经 slash 注入 ②注入的 tiling_results marker 出现在 transcript
  （证明消费 agent 读到编排送达的上游输入，而非跨读 checkpoint）。**实测通过**。

> 此项严格说属 §P1「上下文注入」的未竟部分（超出 P9+L4-c 字面范围），但与本工作包"避免 skill 调起
> 却找错文件的中间态"目标同源，且不补齐则 anchor-check/integrate 的 §P1 仍未闭环，故在本包内一并完成
> （已向用户报告并获确认）。

### 5. L4-c / §P5 —— 删 ascendc-designer + 删除闭包（已完成）

- `git rm .claude/agents/ascendc-designer.md`。
- A 类（真依赖测试）：
  - `test_capabilities.py`：AGENTS 列表去 ascendc-designer、补三角色 agent；decision-tool 断言
    改用 `ascendc-design-generator`（其 manifest 含 `mcp__engine__resolve_ambiguity`）。
  - `test_kernel.py:1099`：`skills=["ascendc-designer"]` 样例改 `stage-design:ascendc-op-general-design`。
  - `test_cli.py:688/702`：spawn_context 字符串样例改 `ascendc-design-generator`。
- B 类（陈旧文档）：
  - `CLAUDE.md`：design 行从 `SpawnAgent("ascendc-designer")` 改为细粒度 substage 编排 +
    design_spec 唯一权威来源（integrate 整合 / dd-intake 解析）。
  - `docs/stages/design.md`：§1 位置、§5 编排结构、§6 三角色、§7 错误分类、§9 事件 schema 全部重写。
  - `docs/architecture-overview.md:344`：agents 树替换为三角色 agent。
  - `docs/layers/L5-capabilities.md:142`：frontmatter 示例从 `skills:[ascendc-designer,...]` 改为
    `plugins:[stage-codegen,...]`（skill 经 plugins 加载）。

## 验证

- 全量 UT：**1172 passed**（含 TestSkillSlashTrigger / TestUpstreamInputInjection 8 例 /
  test_skill_config 5 例 / 删除闭包同改）。
- 非-llm 设计 ST：13 passed（design_pipeline_e2e / test_design_e2e）。
- **真实链路 ST（§P1 闭环硬指标）**：`test_skill_invocation.py` **2 passed**（515s）：
  - tiling-split（角色 A）：slash 首消息触发把 SKILL.md 设计方法注入 agent transcript；
  - anchor-check（角色 C）：slash 注入 anchor 方法（AC0/AC1/AC2）**且**编排注入的 tiling_results
    marker 出现在 transcript（证明消费 agent 读到送达的上游输入，非跨读 checkpoint）。
- 全量 ST（含 @llm，排除 npu/cann/slow）：71 passed / 1 skipped（首次运行，注入链补齐前；补齐后
  按上述定向 ST 复验）。
- 一致性：`validate_skill_map()` 对现网 STAGE_SKILL_MAP 返回 `[]`（10 个指派 skill 全部在盘）。

## 结论

§P1 闭环达成：首消息 slash 触发 + ST 守护翻绿 + SKILL.md 输入契约改写（AC0 病根铲除）+ 真实链路
transcript 出现 skill 设计方法注入，四项齐备。L4-c（§P4 skill 精选 / §P5 designer 退役）随同完成、零债务。
