# codegen skill 上游产物复用 — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。
> 外部参考 `ascendskills/skills/ascendc-op-full-pipeline`（只读，只取思路，不照搬实现）。

## 决策 1（P5）— 是否照搬 Phase C 的 S2-analysis → **不照搬，复用上游 stage 产物**

- full-pipeline C.2 的 ascendc-dev-s2-analysis **重做需求/设计分析**。当前框架 requirement + design
  阶段已产出更丰富产物（概设 general_design、详设的源中间产物 tiling_results 等），照搬 S2 = 重复劳动，
  违反 §2.5（分析归 requirement/design，codegen 复用）。用户明确指示「需求分析在 requirement 阶段已完成，
  不要照搬，复用前置 stage 结果」。→ 复用，不重做。

## 决策 2（关键）— 详细设计说明书.md vs 源中间产物 → **读源中间产物，不读详细设计说明书**

- **选项 A 以详细设计说明书.md 为 codegen 输入**：docgen 产出的叙述文档作实现蓝图。
- **选项 B 以源中间产物为输入**：直接读 `tiling_results`（含 `buffer_kernel.kernel.pseudocode`）、
  `general_design`、`template_division` 等 design stage 的源中间产物。
- **选 B 的理由（铁证 + 原则）**：
  1. **铁证**：详细设计说明书 §4.1.4 Kernel设计 自述「**全量装载自
     `tiling_results.json[T1].buffer_kernel.kernel.pseudocode`，无摘要、无省略」」——它是源中间产物
     的**忠实誊抄渲染**，不是独立信息源。codegen 最需要的 Kernel 伪代码源头就是 `tiling_results`。
  2. **§2.5 + Event Sourcing**：源中间产物（在 State 上，event 权威）才是 ground truth；详细设计说明书
     是 docgen LLM 从源生成的**派生叙述**（人面向，供评审/留痕）。读派生 = 引入第二份会漂移的信息源
     （渲染走样风险），违反「同一职责一条通路」。
  3. **无整合负担**：源中间产物在 State 上已是**整合态**（`state.tiling_results = {template:{split,
     buffer_kernel{kernel.pseudocode}, precision_perf}}`，非碎片化），codegen 直接读，无需自行重装；
     详细设计说明书的"整合便利"不成立（design stage 已整合进结构化产物）。
  - 用户指正：「详细设计说明书也是以前置 stage 中间产物做输入生成的」——正是此理。codegen 该沿
    **源链**读，不该在派生节点截取。

## 决策 3（P4）— 明确参考内容表（codegen 复用哪些**源中间产物**，各翻译为哪层代码）

| 源中间产物（State 字段） | 来源 stage | codegen 分步翻译为 |
|---|---|---|
| `general_design` | general-design-generator | 算子分类 / sections 骨架 / precision 策略 |
| `template_division` | template-division | 模板结构 + 全局锁定决策 |
| `tiling_results`（**含 `buffer_kernel.kernel.pseudocode`**） | tiling(split/buffer-kernel/precision-perf)→integrate | **每模板 Kernel 伪代码 / Buffer / split / precision（代码主蓝图源）** |
| `design_spec` | integrate | IO spec / attrs / tiling_key_router（紧凑契约） |
| `tiling_strategy` | integrate | 跨模板整合：tile 因子 / buffer_model / UB 预算 / shared_tiling_data_fields |
| `kernel_architecture` | codegen_init | section 声明（产出 op_host/op_kernel/op_api/op_plugin 哪些目录） |
| `requirement` | requirement | IO/公式/约束权威源（详细设计说明书 §1 关联需求即引用它） |
| `test_cases` | test_design | 验收用例（TDD：用例先于 codegen 固化，codegen 须满足） |
| `reference_code`（ref_ 文件） | context | 参考算子真实代码（API 用法/文件布局/命名）；为空回退 tiling_results + 知识库 |
| `meta.json` | codegen（本次新增） | programming_model / chip_code / soc_version（驱动编码路径） |

> 当前 codegen 缺的是**源中间产物 `tiling_results`（含 kernel.pseudocode）+ general_design +
> template_division + requirement + test_cases 没被物化/声明**——这才是 agent 转去 grep CANN 的真实信息
> 缺口（01 P1/P4）。决策 2 已证实现蓝图源头是 `tiling_results`（详细设计说明书是其忠实誊抄渲染）。

## 决策 4（边界）— 复用 vs 重做的声明 + 分步编码
skill 须写明**复用边界**：codegen 是「把上游**源中间产物**分步翻译成 AscendC 代码」——需求分析、概设、
详设（tiling/buffer/kernel 伪代码）、section 声明、验收用例均**上游已定，复用不重做**。codegen 自身只
决定代码层落地（API 调用、TilingData struct 形态、文件命名/布局、ACLNN/Plugin 注册细节），且：
- **分步翻译**（对应源中间产物的依赖序）：general_design/template_division → 骨架 →
  tiling_results.kernel.pseudocode → Kernel/Buffer → design_spec/tiling_strategy → Host Tiling/TilingData →
  kernel_architecture section → ACLNN/Plugin。
- API 签名查 `ascendc-dev-knowledge` 知识库；**禁 grep/cat `$ASCEND_TOOLKIT_HOME`、`/usr/local/Ascend/`**；
  仍查不到停下报告，不自搜参考实现、不翻 SDK 源码。

## 决策 5（采纳的 Phase C 思路，非实现）— 三条具体吸收 + 原则翻译

读完 Phase C 编码 skill 本体（ascendskills `ascendc-op-dev-coding` SKILL.md + 祖先 `ascendc-dev-s4-coding`
agent），对照当前 DevKit 同名 skill，**具体**吸收 3 条（每条过「只参考思路 / 符合当前框架 / 复用上游不重做」）：

- **① 参考来源纪律的例外条款 + Why**（Phase C SKILL.md:38-41）：禁自搜参考实现，**但**调用方在 prompt
  显式给定参考路径时读它**允许**（禁的是自搜，不是受控参考）；并附 Why——自搜抄来的实现产生"看似通过
  实则通路不符"虚假信号（历史 20/20 通过却迁移崩溃根因）。当前 skill 把 `reference_code`（正是显式注入
  参考路径）和「自搜」混说不清。→ 补例外条款 + Why：reference_code 该读、自搜/grep CANN 该禁。
- **② 字段↔源逐一对应铁律**（Phase C SKILL.md:224-225，P-023/P-030）：生成 TilingData 字段须与详设字段
  清单逐一对应，缺失/不符→fail。当前 skill 只有 host↔kernel 两份一致，无"生成的 vs 设计源字段清单"维。
  → 吸收并**改接到源**：权威源是 `tiling_strategy`/`tiling_results` 的字段（Event Sourcing：State 源为
  ground truth，不读派生文档）。
- **③ 详设完整性「锁定项」入口校验 fail-fast**（Phase C SKILL.md:144-148）：涉双缓冲→须 BUFFER_NUM、涉
  reduce/gather/...→须 workspace 公式、TilingData→须字段清单、dtype→须矩阵，缺即 fail 不猜测补全。
  → 吸收为**入口校验纪律**：codegen 发现源缺必要字段时**停下报告**（"上游缺 X"），不 grep/不自搜/不猜。
  注：DevKit 无 high_risk_api_registry，故③是 fail-fast 纪律 + 文档化字段期望，**不做 registry 查询**
  （Phase C 用 registry 判高风险 API，我们没有→不照搬该机制）。

**不吸收（driver 编排机制，§2.6 第三类耦合）**：RECORD_DIR / coding_index.md / dev_record.sh /
progress.md / 检查点组调度 / CTX_DRIFT / RETURN error_type 编码——这些是 full-pipeline driver 产物；
当前框架等价物 = staging 物化 + skill 投递（§4.3）+ Event Sourcing（events.jsonl），照搬即开第二套 driver
（§2.5）。**只取原则**：「信息源装进显式有界集合」→「staging 物化源产物 + skill 显式声明参考集」。

**另两块有价值但正交（本轮不动，单独立 L1 follow-up）**：
- ④ A5 Regbase 编码硬约束（s4-coding §4.5 九条 + §4.6 专属规则）——当前 skill 对 A5 只一句、无可执行红线，
  是最大内容缺口；属核心计算红线（§2.7）但与源复用正交 → `codegen-skill-a5-constraints/`。
- ⑤ 多维编码自检（维3 禁硬编码/维4 buffer-pipeline/维5 dtype 一致性）——同样正交，且维4/维5 引用
  buffer_pipeline_redline/high_risk_api_registry（DevKit 无）需先补资源 → `codegen-skill-selfcheck-dims/`。

## 四把尺子自检
- **可维护**：参考集单源在 skill（SKILL.md 声明表）+ staging 物化（codegen._materialize_inputs 读 State
  源字段），与既有 P4 物化机制一致；不引入详细设计说明书这条派生通路（§2.5）。
- **可扩展**：design 新增源产物只需扩物化 + 参考表，agent 自动读到。
- **可诊断**：信息源有界且为源（非派生）→ 失败定位「哪个源中间产物缺字段」，不再静默 grep CANN。
- **架构合理**：改动落在 skill 内容层（参考声明 + 复用边界 + 分步翻译）+ codegen 物化层（staging 多写
  几个 State 源字段），与设计侧 staging 物化对称，不越层、不引入 driver 编排。
