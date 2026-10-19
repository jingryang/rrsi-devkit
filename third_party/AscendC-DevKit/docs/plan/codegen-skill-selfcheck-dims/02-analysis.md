# codegen skill 多维自检 — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。
> 外部参考 `ascendskills/skills/ascendc-op-dev-coding/SKILL.md` Step6 维3/维4/维5（只读，只取思路，不照搬实现）。
> 与上游复用（`../codegen-skill-upstream-reuse/`）正交：上游复用管「读什么源产物」，本工作管「编码后自检哪些维度」。

## 前置问题（P3）— 维4/维5 资源：DevKit 无 registry，但规则机械可内联

**查证结论**（grep DevKit `.claude/` + `resources/`）：

1. **`buffer_pipeline_redline.md` / `high_risk_api_registry.md` 在 DevKit 不存在**（grep 0 命中）。仅命中：
   - `stage-testdesign/.../redline_rules.md`、`vector_redline_testcase_rules.md`——测试设计用，非 codegen 编码自检（与 01 P3 一致）。
   - `evolution-strategies/.../P82_manual_multi_buffer_pipeline_policy.md`——进化策略卡，非编码红线。
2. **Phase C 维4/维5 引用这两份 registry 的实际用途**：
   - `buffer_pipeline_redline.md` E1/E2/E3——给 AR-1/AR-2/AR-3 提供「何为主循环数据搬送 / 何为嵌套 GM 单点 / 何为非对齐」的**判定标签**。
   - `high_risk_api_registry.md` C1-C4——给「哪些 API 属高风险须 workspace」做**准入分类**。
3. **关键观察**：剥掉 E1/E2/E3、C1-C4 标签后，维3/维4/维5 的**实际判定是机械的**——grep 裸数值常数（维3）、grep 主循环 GetValue/SetValue（维4 AR-1）、字段枚举逐一比对（维5）。这些规则跨算子跨仓通用、可 grep/可字段比对、不需要 registry 撑语义。

## 决策 1 — 维4/维5 判定规则内联进 skill，不补 registry 资源

- **选项 A**：在 codegen skill 目录（或 ascendc-op-design-shared）新建 `buffer_pipeline_redline.md` + `high_risk_api_registry.md`，skill 引用之。
- **选项 B**：把维3/维4/维5 的判定规则**直接内联**进 SKILL.md Step6 表（同既有 7 行自检同格式）。
- **选 B**：
  1. **§2.7 判定**：维3/维4/维5 是「精度/性能红线 / 跨算子跨仓通用 / 编码时针对性校验」——属 §2.7 该留 skill 的核心内容；但它们**机械简洁**（grep 模式 + 字段比对），不是需独立文档承载的成体系知识。registry 是 Phase C 的组织方式，DevKit 无需照搬其组织。
  2. **§2.1 即插即用**：内联保 skill 自闭环——不依赖外部 registry 文件，skill 取出至他仓不缺依赖（若引用 registry，取出时须同带 registry，增即插即用摩擦）。
  3. **不增厚到膨胀**：维3（1 行）+ 维4（AR-1/2/3 共 3 行）+ 维5（3 行）= 7 行表项，与既有 Step6 7 行同量级，不触发 §2.7「使 skill 膨胀」红线。
  4. **§2.5 唯一通路**：DevKit 既无 registry，新建一份即是为照搬 Phase C 而造的资产——而规则本身可内联，新建 registry 是多余通路。
- **不选 A**：新建 registry = 引入 Phase C 的组织资产 + skill 对外部文件的引用耦合，且 DevKit 既无 design-shared registry 先例（design 侧 skill 也未用），孤例引入破规整。

## 决策 2 — 吸收边界：维3/维4/维5；不重复 ②③ 已覆盖项

**吸收（L1 P1 明列的三块缺口）**：
- **维3 禁硬编码硬件参数**：`op_host/*_tiling.cpp`、`op_kernel/*` 含裸 CORE_NUM/BLOCK_NUM/UB_SIZE/对齐常数（`=32`/`=262144`/`=14336` 等）→ warning，改运行时查询 GetBlockNum/GetUBSize 或 sizeof(T)/GetSizeByDataType(dtype)/TilingData 字段。与 `.claude/rules/ascendc-dev.md`「No hardcoded hardware params」一致（01 P2 已述）。
- **维4 buffer-pipeline 红线**：
  - AR-1 主循环禁 GetValue/SetValue 数据搬送（过滤注释 + TilingData 元数据读取 + 纯索引）→ warning，改 DataCopy 批量搬送。
  - AR-2 嵌套 for 循环内 GM GetValue/SetValue 单点访问 → warning。
  - AR-3 tail/pad/copyLen%ALIGN≠0 非对齐场景用 DataCopyPad 而非单点 → warning。
- **维5 dtype 一致性**：
  - OpDef dtype ⊇ 详设 IO spec dtype（`{op}_def.cpp` DataType::X 枚举 vs `design_spec` IO spec dtype 矩阵逐一比对）→ 缺失 status=fail。
  - Tiling dtype 分支 ⊆ OpDef（`{op}_tiling.cpp` DT_X 运行时分支 ∈ OpDef 枚举）→ 不一致 status=fail。
  - Plugin cast 兜底检测（op_plugin 对非 OpDef dtype 做 cast）→ warning，记回报。

**不吸收（已被上游复用 ②③ 覆盖，不重复）**：
- Phase C 维2「BUFFER_NUM↔详设一致」「高风险 API workspace 分配存在性」「TilingData 字段↔详设对应」——DevKit 已由：② Step6「字段↔源逐一对应」（TilingData 字段 vs tiling 源）+ ③ Step2 锁定项入口校验（涉双缓冲→须 BUFFER_NUM / 涉 reduce/gather/...→须 workspace 预算，缺即 fail-fast）覆盖。本工作不重复造同维自检（§2.5）。
- 注：Phase C 维2 的 workspace 是**代码级**检查（tiling.cpp 是否分配 sharedTmpSize），DevKit ③ 是**入口级**检查（源是否含 workspace 预算字段）。两者互补不重叠——③ 守入口（源缺即停），本工作维4/维5 守代码级机械模式（禁单点搬送/dtype 枚举比对）。不扩 ⑤ 范围去补 BUFFER_NUM/workspace 代码级检查（超出 L1 P1 列示缺口，且 ③ 已守入口）。

## 决策 3 — 不照搬 E1/E2/E3 / C1-C4 标签，内联实际判定

- Phase C 用 E1/E2/E3（buffer_pipeline_redline）+ C1-C4（high_risk_api_registry）做判定标签——是其 registry 组织的一部分。
- DevKit 不引入 registry（决策 1），故**不照搬标签**，直接内联判定规则（grep 模式 / 字段比对）。标签是组织手段非语义必需；agent 看「主循环内 GetValue/SetValue 做数据搬送→warning」比看「违 E1→warning」更直白可执行。
- 维5 不再引用「high_risk_api_registry C1-C4」做 workspace 准入——workspace 准入已由 ③ 入口校验承担（涉 reduce/gather/scatter/sort/topk/broadcast→须 workspace 预算）；维5 只做 dtype 枚举一致性（不需 registry）。

## 四把尺子自检

- **可维护**：维3/维4/维5 内联单源在 SKILL.md Step6（与既有自检同表同格式），新增维度只加表行；不引入外部 registry 文件需同步。
- **可扩展**：未来加新自检维度（如新 dtype 规则）只需 Step6 加行；规则机械可 grep/可字段比对，agent 执行确定。
- **可诊断**：每维自检有明确失败处理（warning 计数 / status=fail + 具体字段），不静默；维3 禁硬编码与 rules/ascendc-dev.md 对齐，定位一致。
- **架构合理**：改动落在 skill 内容层（Step6 自检表扩行），不引入资源文件、不复制 Phase C registry、不重复 ②③ 已覆盖维度；与上游复用 ①②③（同 skill）同层不冲突。
